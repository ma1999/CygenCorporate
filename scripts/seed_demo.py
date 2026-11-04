"""Demo data for the frontend / smoke tests (idempotent, removable).

    python scripts/seed_demo.py            # create (re-running is a no-op)
    python scripts/seed_demo.py --remove   # delete exactly what this script created

What is created is *sample* content (2 categories, 1 brand, 3 products with
specs/variants/images/PDF documents, projects, articles, services, FAQ,
company data, a few inquiries). Everything goes through the same entity engine
as the admin panel, so it also exercises validation, translation storage and
cache invalidation. Created row ids are remembered in ``settings.demo_seed_manifest``
so ``--remove`` never touches real content. Site settings are only filled where
they are still empty.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from werkzeug.datastructures import FileStorage, MultiDict  # noqa: E402

MANIFEST_KEY = "demo_seed_manifest"
DEMO_DIR = os.getenv("SEED_DEMO_DIR", "demo")          # uploads/<DEMO_DIR>/...
LANGS = ["fa", "en"]


# ---------------------------------------------------------------------------
# sample files
# ---------------------------------------------------------------------------
def make_pdf(title: str) -> bytes:
    """A tiny valid one-page PDF (ASCII text)."""
    text = f"BT /F1 20 Tf 72 720 Td ({title}) Tj ET".encode("latin-1", "replace")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(text) + text + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def make_images(uploads: Path) -> dict:
    """Generate sample JPEGs + an SVG logo under uploads/demo/. Returns web paths."""
    from PIL import Image, ImageDraw

    d = uploads / DEMO_DIR
    d.mkdir(parents=True, exist_ok=True)
    paths = {}
    specs = {
        "hero": ((1600, 900), (11, 79, 138)), "intro": ((1200, 800), (8, 61, 107)), "cap": ((1200, 800), (194, 120, 3)),
        "hq": ((1200, 800), (15, 23, 42)), "placeholder": ((800, 600), (100, 116, 139)),
        "p1a": ((1000, 750), (30, 64, 175)), "p1b": ((1000, 750), (37, 99, 235)), "p1c": ((1000, 750), (59, 130, 246)),
        "p2a": ((1000, 750), (21, 128, 61)), "p3a": ((1000, 750), (126, 34, 206)),
        "cat1": ((1000, 600), (234, 88, 12)), "cat2": ((1000, 600), (13, 148, 136)),
        "proj1": ((1400, 800), (30, 41, 59)), "proj2": ((1400, 800), (51, 65, 85)), "art1": ((1200, 700), (88, 28, 135)),
        "favicon": ((512, 512), (11, 79, 138)),
    }
    for name, (size, color) in specs.items():
        im = Image.new("RGB", size, color)
        dr = ImageDraw.Draw(im)
        dr.rectangle([20, 20, size[0] - 20, size[1] - 20], outline=(255, 255, 255), width=6)
        dr.text((60, 60), f"demo {name}", fill=(255, 255, 255))
        ext = "png" if name == "favicon" else "jpg"
        im.save(d / f"{name}.{ext}")
        paths[name] = f"/assets/uploads/{DEMO_DIR}/{name}.{ext}"
    (d / "brand-logo.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="48"><rect width="160" height="48" fill="#0b4f8a"/>'
        '<text x="12" y="31" fill="#fff" font-size="20">DEMO</text></svg>', encoding="utf-8")
    paths["logo"] = f"/assets/uploads/{DEMO_DIR}/brand-logo.svg"
    return paths


def file_storage(name: str, data: bytes) -> FileStorage:
    return FileStorage(stream=io.BytesIO(data), filename=name)


# ---------------------------------------------------------------------------
# seed
# ---------------------------------------------------------------------------
class Seeder:
    def __init__(self, app):
        self.app = app
        self.db = app.core.db
        self.manifest = {"rows": {}, "settings": [], "files": []}

    def note(self, table, rid):
        self.manifest["rows"].setdefault(table, []).append(rid)

    async def load_manifest(self):
        row = await self.db.fetch("SELECT `value` FROM settings WHERE `key`=%s", (MANIFEST_KEY,), one=True)
        if row:
            self.manifest = json.loads(row["value"])

    async def save_manifest(self):
        await self.db.execute(
            "INSERT INTO settings (`key`,`value`) VALUES (%s,%s) ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",
            (MANIFEST_KEY, json.dumps(self.manifest)),
        )

    async def ensure(self, ent, natural_col, natural_val, values):
        """Create via the entity engine unless a row with ``natural_col=natural_val`` exists."""
        row = await self.db.fetch(f"SELECT id FROM `{ent.table}` WHERE `{natural_col}`=%s", (natural_val,), one=True)
        if row:
            return row["id"]
        rid, merged, errors = await ent.save(self.db, None, values=values, langs=LANGS)
        if not rid:
            raise SystemExit(f"seed failed for {ent.table} {natural_val}: {errors}")
        self.note(ent.table, rid)
        return rid

    async def run(self):
        await self.load_manifest()
        try:
            await self._run()
        finally:
            await self.save_manifest()   # partial runs must stay removable
        self.app.revalidate.notify("*")
        print("demo seed OK:", {k: len(v) for k, v in self.manifest["rows"].items()})

    async def _run(self):
        from app.plugins.articles.plugin import CATEGORY as ART_CAT, ENT as ARTICLE
        from app.plugins.brands.plugin import ENT as BRAND
        from app.plugins.categories.plugin import ENT as CATEGORY
        from app.plugins.company import plugin as company
        from app.plugins.faq.plugin import CATEGORY as FAQ_CAT, ITEM as FAQ_ITEM
        from app.plugins.products.plugin import ENT as PRODUCT, TAG
        from app.plugins.projects.plugin import ENT as PROJECT, SECTOR
        from app.plugins.services.plugin import SERVICE, STEP

        uploads = ROOT / "uploads"
        img = make_images(uploads)
        self.manifest["files"] = [f"uploads/{DEMO_DIR}"]
        T = lambda fa, en=None: {"fa": fa, **({"en": en} if en else {})}
        L = lambda fa, en=None: {"fa": fa, **({"en": en} if en else {})}

        # ---- site settings: only the empty ones ----
        await self.seed_settings(img)

        # ---- categories ----
        root = await self.ensure(CATEGORY, "slug", "demo-flow-control", {
            "name": T("کنترل سیالات", "Flow Control"), "slug": "demo-flow-control", "icon": "Gauge",
            "short_description": T("شیرآلات و تجهیزات کنترل جریان", "Valves and flow-control equipment"),
            "description": T("طراحی و ساخت تجهیزات کنترل سیالات صنعتی.\n\nمطابق استانداردهای بین‌المللی.",
                             "Design and manufacture of industrial flow-control equipment."),
            "standards": ["IEC 60534", "ASME B16.34"], "cover_image": img["cat1"], "cover_image_alt": T("کنترل سیالات", "Flow control"),
            "key_highlights": {"fa": ["دقت بالا", "ایمنی SIL-3"], "en": ["High accuracy", "SIL-3 safety"]},
            "sort_order": 1, "is_active": True,
        })
        child = await self.ensure(CATEGORY, "slug", "demo-control-valves", {
            "name": T("شیرآلات کنترلی", "Control Valves"), "slug": "demo-control-valves", "parent_id": root, "icon": "Cpu",
            "short_description": T("شیرهای کنترل پنوماتیک", "Pneumatic control valves"), "cover_image": img["cat2"],
            "standards": ["IEC 60534"], "sort_order": 1, "is_active": True,
        })
        # ---- brand ----
        brand = await self.ensure(BRAND, "slug", "demo-aspd", {
            "slug": "demo-aspd", "name": T("آریا صنعت", "Arya Sanat"), "description": T("برند نمونه", "Sample brand"),
            "logo": img["logo"], "logo_alt": T("لوگو", "Logo"), "website_url": "https://example.com", "sort_order": 1, "is_active": True,
        })
        # ---- products ----
        p1 = await self.ensure(PRODUCT, "slug", "demo-as-fcv-940", {
            "slug": "demo-as-fcv-940", "model_code": "DEMO-AS-FCV-940", "status": "published",
            "name": T("شیر کنترل جریان ۹۴۰", "Flow Control Valve 940"),
            "subtitle": T("سری حرفه‌ای SIL-3", "Professional SIL-3 series"),
            "short_description": T("شیر کنترل پنوماتیک با دقت بالا.", "High-accuracy pneumatic control valve."),
            "description": T("این شیر برای کنترل دقیق جریان در صنایع نفت و گاز طراحی شده است.\n\nدارای گواهی SIL-3.",
                             "Designed for precise flow control in oil & gas.\n\nSIL-3 certified."),
            "features": {"fa": ["دقت ±۰٫۵٪", "بدنه استیل ۳۱۶", "گواهی SIL-3", "عمر بالا", "نصب آسان"],
                         "en": ["±0.5% accuracy", "316 stainless body", "SIL-3 certified", "Long life", "Easy install"]},
            "category_id": child, "brand_id": brand, "tags": ["SIL-3", "ابزار دقیق", "کنترل"],
            "certifications": ["IEC 60534", "SIL-3"], "is_featured": True, "is_new": True, "sort_order": 1, "sku": "DEMO-SKU-940",
            "specs": [
                {"label": T("فشار کاری", "Working pressure"), "value": T("تا ۱۶۰ بار", "Up to 160 bar")},
                {"label": T("دما", "Temperature"), "value": T("‎-۴۰ تا ۴۲۵ درجه", "-40 to 425 °C")},
                {"label": T("اندازه", "Size"), "value": T("۱ تا ۱۲ اینچ", "1 to 12 in")},
                {"label": T("جنس بدنه", "Body material"), "value": T("استیل ۳۱۶", "316 SS")},
                {"label": T("کلاس نشتی", "Leakage class"), "value": T("IV", "IV")},
            ],
            "variants": [
                {"model_code": "DEMO-AS-FCV-940-S2", "name": T("مدل S2", "Model S2"), "configuration": T("فلنجی", "Flanged"),
                 "operating_range": T("۰ تا ۱۶۰ بار", "0–160 bar"), "application": T("گاز", "Gas")},
                {"model_code": "DEMO-AS-FCV-940-S4", "name": T("مدل S4", "Model S4"), "configuration": T("ولد", "Welded"),
                 "operating_range": T("۰ تا ۱۰۰ بار", "0–100 bar"), "application": T("نفت", "Oil")},
            ],
            "images": [
                {"url": img["p1a"], "url_alt": T("نمای جلو", "Front view")},
                {"url": img["p1b"], "url_alt": T("نمای کناری", "Side view")},
                {"url": img["p1c"], "url_alt": T("برش", "Cut-away")},
            ],
        })
        p2 = await self.ensure(PRODUCT, "slug", "demo-as-pt-210", {
            "slug": "demo-as-pt-210", "model_code": "DEMO-AS-PT-210", "status": "published",
            "name": T("ترانسمیتر فشار ۲۱۰", "Pressure Transmitter 210"), "subtitle": T("ابزار دقیق", "Instrumentation"),
            "short_description": T("ترانسمیتر فشار هوشمند.", "Smart pressure transmitter."),
            "description": T("ترانسمیتر فشار با خروجی HART.", "Pressure transmitter with HART output."),
            "category_id": root, "brand_id": brand, "tags": ["ابزار دقیق"], "certifications": ["IEC 61508"],
            "is_featured": True, "sort_order": 2,
            "specs": [{"label": T("دقت", "Accuracy"), "value": T("۰٫۰۷۵٪", "0.075%")}],
            "images": [{"url": img["p2a"], "url_alt": T("ترانسمیتر", "Transmitter")}],
        })
        p3 = await self.ensure(PRODUCT, "slug", "demo-as-plc-500", {
            "slug": "demo-as-plc-500", "model_code": "DEMO-AS-PLC-500", "status": "published",
            "name": T("کنترلر PLC ۵۰۰", "PLC Controller 500"), "short_description": T("کنترلر برنامه‌پذیر.", "Programmable controller."),
            "description": T("کنترلر صنعتی ماژولار.", "Modular industrial controller."), "category_id": root, "sort_order": 3,
            "images": [{"url": img["p3a"], "url_alt": T("PLC", "PLC")}],
        })
        # extra: draft + scheduled product (must stay invisible in the public API)
        await self.ensure(PRODUCT, "slug", "demo-draft-product", {
            "slug": "demo-draft-product", "model_code": "DEMO-DRAFT-1", "status": "draft", "name": T("پیش‌نویس", "Draft")})
        # English tag labels
        en_map = {"ابزار دقیق": "Instrumentation", "کنترل": "Control", "SIL-3": "SIL-3"}
        for t in await self.db.fetch("SELECT id, label_i18n FROM product_tags"):
            fa = json.loads(t["label_i18n"] or "{}").get("fa")
            if fa in en_map:
                await TAG.save(self.db, t["id"], values={"label": {"en": en_map[fa]}}, langs=LANGS)
        # ---- documents (PDF fa + en) ----
        await self.seed_documents(p1, img)

        # ---- projects (sectors are seeded by the plugin) ----
        sec = {r["slug"]: r["id"] for r in await self.db.fetch("SELECT id, slug FROM project_sectors")}
        await self.ensure(PROJECT, "slug", "demo-power-plant", {
            "slug": "demo-power-plant", "status": "published", "title": T("نیروگاه نمونه", "Sample Power Plant"),
            "sector_id": sec["energy"], "client": T("شرکت برق", "Power Co."), "location": T("تهران", "Tehran"),
            "completion_year": 2024, "cover_image": img["proj1"], "cover_image_alt": T("نیروگاه", "Plant"),
            "short_description": T("تأمین تجهیزات کنترلی.", "Control equipment supply."),
            "challenge": T("فشار بالا.", "High pressure."), "solution": T("شیرهای SIL-3.", "SIL-3 valves."),
            "is_featured": True,
            "gallery": [{"image": img["proj1"], "image_alt": T("گالری ۱", "Gallery 1")}, {"image": img["proj2"]}],
            "impact_metrics": [{"label": T("کاهش مصرف", "Energy saving"), "value": T("۱۲٪", "12%")},
                               {"label": T("زمان توقف", "Downtime"), "value": T("−۴۰٪", "−40%")}],
            "specifications": [{"label": T("ظرفیت", "Capacity"), "value": T("۵۰۰ مگاوات", "500 MW")}],
            "products": [{"product_id": p1}, {"product_id": p2}],
        })
        await self.ensure(PROJECT, "slug", "demo-desalination", {
            "slug": "demo-desalination", "status": "published", "title": T("نمک‌زدایی نمونه", "Sample Desalination"),
            "sector_id": sec["water"], "client": T("آب منطقه‌ای", "Regional Water"), "location": T("بوشهر", "Bushehr"),
            "completion_year": 2023, "cover_image": img["proj2"], "short_description": T("خط تصفیه.", "Treatment line."),
            "products": [{"product_id": p3}],
        })
        # ---- articles ----
        cats = {r["slug"]: r["id"] for r in await self.db.fetch("SELECT id, slug FROM article_categories")}
        import datetime as dt
        now = dt.datetime.utcnow().replace(microsecond=0)
        for i, (slug, fa, en) in enumerate([
            ("demo-valve-selection", "راهنمای انتخاب شیر کنترل", "Control valve selection guide"),
            ("demo-sil-intro", "مقدمه‌ای بر SIL", "An introduction to SIL"),
            ("demo-company-news", "خبر شرکت", "Company news"),
        ]):
            await self.ensure(ARTICLE, "slug", slug, {
                "slug": slug, "status": "published", "published_at": now - dt.timedelta(days=i + 1),
                "title": T(fa, en), "excerpt": T("چکیده " + fa, "Excerpt of " + en),
                "category_id": cats["engineering" if i < 2 else "corporate"],
                "author_name": T("تیم مهندسی", "Engineering team"), "author_role": T("مهندس", "Engineer"),
                "cover_image": img["art1"], "cover_image_alt": T("مقاله", "Article"), "is_featured": i == 0,
                "sections": [
                    {"heading": T("مقدمه", "Introduction"), "paragraphs": {"fa": ["پاراگراف اول. " * 30, "پاراگراف دوم."], "en": ["First paragraph. " * 30]}},
                    {"heading": T("جمع‌بندی", "Conclusion"), "paragraphs": {"fa": ["نتیجه."], "en": ["Conclusion."]}},
                ],
            })
        await self.ensure(ARTICLE, "slug", "demo-draft-article", {
            "slug": "demo-draft-article", "status": "draft", "title": T("پیش‌نویس مقاله", "Draft article"),
            "category_id": cats["engineering"]})
        await self.ensure(ARTICLE, "slug", "demo-scheduled-article", {
            "slug": "demo-scheduled-article", "status": "published", "published_at": now + dt.timedelta(days=30),
            "title": T("مقاله‌ی زمان‌بندی‌شده", "Scheduled article"), "category_id": cats["engineering"]})
        # ---- services + steps ----
        for i, (slug, icon, fa, en) in enumerate([("demo-integration", "Settings", "یکپارچه‌سازی", "Integration"),
                                                   ("demo-calibration", "Award", "کالیبراسیون", "Calibration")]):
            await self.ensure(SERVICE, "slug", slug, {
                "slug": slug, "icon": icon, "title": T(fa, en), "short_description": T("خدمت " + fa, "Service " + en),
                "description": T("توضیح " + fa, "About " + en), "deliverables": {"fa": ["گزارش", "گواهی"], "en": ["Report", "Certificate"]},
                "industries": {"fa": ["نفت"], "en": ["Oil"]}, "sort_order": i, "is_active": True})
        for i, (fa, en) in enumerate([("مطالعه", "Study"), ("طراحی", "Design"), ("ساخت", "Build"), ("تست", "Test"), ("تحویل", "Deliver")]):
            await self.ensure(STEP, "title_i18n", json.dumps(T(fa, en), ensure_ascii=False), {
                "title": T(fa, en), "description": T("مرحله " + fa, "Step " + en), "sort_order": i, "is_active": True})
        # ---- FAQ ----
        fc = {r["slug"]: r["id"] for r in await self.db.fetch("SELECT id, slug FROM faq_categories")}
        for i, (cat, q, a) in enumerate([
            ("engineering", "آیا شیرها SIL-3 هستند؟", "بله، گواهی دارند."), ("documentation", "دیتاشیت کجاست؟", "در صفحه‌ی محصول."),
            ("support", "پشتیبانی چگونه است؟", "۲۴ ساعته."), ("corporate", "دفتر کجاست؟", "تهران.")]):
            await self.ensure(FAQ_ITEM, "question_i18n", json.dumps(T(q, "Q" + str(i)), ensure_ascii=False), {
                "category_id": fc[cat], "question": T(q, "Q" + str(i)), "answer": T(a, "A" + str(i)), "sort_order": i, "is_active": True})
        # ---- company ----
        E = company.ENTITIES
        for i, (v, fa, en, suf) in enumerate([(27, "سال تجربه", "Years of experience", "+"), (350, "پروژه", "Projects", "+"),
                                               (45, "مهندس", "Engineers", ""), (12000, "متر مربع", "Sqm", "")]):
            await self.ensure(E["stats"], "label_i18n", json.dumps(T(fa, en), ensure_ascii=False), {
                "value": v, "suffix": T(suf), "label": T(fa, en), "sublabel": T("زیر " + fa), "sort_order": i, "is_active": True})
        for i, (y, fa, en) in enumerate([("1998", "تأسیس", "Founded"), ("2010", "گسترش", "Expansion"), ("2024", "امروز", "Today")]):
            await self.ensure(E["timeline"], "year", y, {"year": y, "title": T(fa, en), "description": T("شرح " + fa), "sort_order": i, "is_active": True})
        for i, (fa, en) in enumerate([("مدیرعامل", "CEO"), ("مدیر فنی", "CTO")]):
            await self.ensure(E["team"], "name_i18n", json.dumps(T("آقای " + fa, "Mr " + en), ensure_ascii=False), {
                "name": T("آقای " + fa, "Mr " + en), "role": T(fa, en), "qualification": T("دکتری", "PhD"), "bio": T("معرفی", "Bio"),
                "sort_order": i, "is_active": True})
        cert_ids = []
        for i, code in enumerate(["DEMO ISO 9001:2015", "DEMO ISO/IEC 17025"]):
            cert_ids.append(await self.ensure(E["certifications"], "code", code, {
                "code": code, "title": T("گواهی " + code, "Certificate " + code), "issuer": T("صادرکننده", "Issuer"),
                "description": T("توضیح", "Description"), "sort_order": i, "is_active": True}))
        await self.seed_documents(cert_ids[0], img, owner="certification")
        for i, (icon, fa, en) in enumerate([("Flame", "نفت و گاز", "Oil & Gas"), ("Droplets", "آب", "Water"), ("Zap", "برق", "Power")]):
            await self.ensure(E["industries"], "title_i18n", json.dumps(T(fa, en), ensure_ascii=False), {
                "icon": icon, "title": T(fa, en), "description": T("توضیح " + fa), "sort_order": i, "is_active": True})
        for i, (fa, en) in enumerate([("عالی بود", "Excellent"), ("قابل اعتماد", "Reliable")]):
            await self.ensure(E["testimonials"], "quote_i18n", json.dumps(T(fa, en), ensure_ascii=False), {
                "quote": T(fa, en), "author_name": T("مشتری " + str(i), "Customer " + str(i)), "author_role": T("مدیر", "Manager"),
                "organization": T("شرکت", "Company"), "sector": T("انرژی", "Energy"), "sort_order": i, "is_active": True})
        for i, (fa, en, primary, lat, lng) in enumerate([("دفتر مرکزی", "Head office", True, 35.7742, 51.4128), ("کارخانه", "Factory", False, 35.55, 51.2)]):
            await self.ensure(E["offices"], "title_i18n", json.dumps(T(fa, en), ensure_ascii=False), {
                "title": T(fa, en), "address": T("تهران، خیابان نمونه", "Tehran, Sample St."), "phone": "+98 21 8865 4200",
                "email": "demo@example.com", "hours": T("۸ تا ۱۷", "8–17"), "lat": lat, "lng": lng, "is_primary": primary,
                "sort_order": i, "is_active": True})
        await self.seed_inquiries()

    async def seed_settings(self, img):
        plugin = self.app.core.plugins.plugins["site_settings"]
        cur = await plugin.load_values(self.db)
        wanted = MultiDict()

        from app.plugins.site_settings.plugin import DEFAULTS

        def put(key, value):
            """Only fill what is empty (or still the built-in default) so real
            configuration is never overwritten."""
            base = key.split("__")[0]
            have = cur.get(base)
            if not have or have == {} or have == [] or have == DEFAULTS.get(base):
                wanted[key] = value
                self.manifest["settings"].append(key.split("__")[0])

        put("name__fa", "آریا صنعت پویا"); put("name__en", "Arya Sanat Precision Dynamics")
        put("short_name__fa", "آریا صنعت"); put("tagline__fa", "مهندسی تجهیزات دقیق"); put("tagline__en", "Precision engineering")
        put("logo_subtitle__fa", "ASPD ENGINEERING GROUP")
        put("site_url", "https://example-frontend.test")
        put("logo_light", img["logo"]); put("logo_light_alt__fa", "لوگو"); put("logo_light_alt__en", "Logo")
        put("favicon_png", img["favicon"])
        put("og_default_image", img["hero"]); put("og_default_image_alt__fa", "تصویر اشتراک")
        put("phone", "+98 21 8865 4200"); put("email", "demo@example.com")
        put("address__fa", "تهران، خیابان نمونه"); put("address__en", "Tehran, Sample St.")
        put("working_hours__fa", "شنبه تا چهارشنبه ۸ تا ۱۷")
        put("map_lat", "35.7742"); put("map_lng", "51.4128"); put("map_label__fa", "دفتر مرکزی")
        put("header_badges", "ISO 9001:2015\nIEC 61508 SIL-3\nISO/IEC 17025")
        put("search_suggestions__fa", "DEMO-AS-FCV-940\nکوریولیس"); put("search_suggestions__en", "DEMO-AS-FCV-940\nCoriolis")
        put("seo_default_title__fa", "آریا صنعت پویا | مهندسی تجهیزات دقیق")
        put("seo_default_description__fa", "طراح و تولیدکننده تجهیزات کنترل سیالات و ابزار دقیق.")
        put("media.home.hero", img["hero"]); put("media.home.hero_alt__fa", "کارخانه")
        put("media.home.intro", img["intro"]); put("media.home.capabilities", img["cap"])
        put("media.about.hq", img["hq"]); put("media.product.placeholder", img["placeholder"])
        put("pm.home.title__fa", "خانه | آریا صنعت پویا")
        put("pm.about.title__fa", "درباره ما | آریا صنعت پویا")
        put("inquiry_reference_prefix", "ASPD")
        wanted["social__present"] = "1"
        wanted["social-0-platform"] = "linkedin"; wanted["social-0-url"] = "https://linkedin.com/company/demo"
        wanted["social-0-is_active"] = "1"
        errors, _ = await plugin.save_form(wanted, LANGS)
        if errors:
            raise SystemExit(f"site settings seed failed: {errors}")

    async def seed_documents(self, owner_id, img, owner="product"):
        from app.plugins.documents.plugin import validate_and_store, Plugin as Docs

        exists = await self.db.fetch("SELECT id FROM documents WHERE owner_type=%s AND owner_id=%s", (owner, owner_id))
        if exists:
            return
        specs = [("datasheet", "دیتاشیت", "Datasheet", "Rev 4.2"), ("manual", "راهنمای نصب", "Installation manual", "2026")]
        if owner == "certification":
            specs = [("certificate", "گواهینامه", "Certificate", "2025")]
        from app.core import content as C

        for i, (dtype, fa, en, rev) in enumerate(specs):
            fa_file = validate_and_store(file_storage(f"{fa}-{owner_id}-fa.pdf", make_pdf(f"{en} FA {owner_id}")))
            en_file = validate_and_store(file_storage(f"{en.replace(' ', '-')}-{owner_id}-en.pdf", make_pdf(f"{en} EN {owner_id}")))

            def go(tx):
                did = tx.run(
                    "INSERT INTO documents (owner_type, owner_id, doc_type, title_i18n, revision, sort_order, is_public, created_at, updated_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,1,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                    (owner, owner_id, dtype, C.dump_i18n({"fa": fa, "en": en}), rev, i))
                Docs._insert_file(tx, did, "fa", fa_file)
                Docs._insert_file(tx, did, "en", en_file)
                return did

            did = await self.db.transaction(go)
            self.note("documents", did)

    async def seed_inquiries(self):
        have = await self.db.fetch("SELECT COUNT(*) AS c FROM inquiries WHERE email LIKE %s", ("%@demo-seed.test",), one=True)
        if have["c"]:
            return
        def post_all():
            c = self.app.test_client()
            for i in range(3):
                r = c.post("/api/public/inquiries", json={
                    "full_name": f"مشتری نمونه {i}", "email": f"c{i}@demo-seed.test", "phone": "+98 21 1234 5678",
                    "subject": "استعلام قیمت نمونه", "message": "لطفاً قیمت و زمان تحویل را اعلام کنید. " * 2,
                    "product_code": "DEMO-AS-FCV-940", "locale": "fa"}, headers={"X-Real-IP": f"198.51.100.{20 + i}"})
                if r.status_code != 201:
                    raise SystemExit(f"inquiry seed failed: {r.status_code} {r.get_data(as_text=True)}")

        await asyncio.to_thread(post_all)
        ids = [r["id"] for r in await self.db.fetch("SELECT id FROM inquiries WHERE email LIKE %s", ("%@demo-seed.test",))]
        for i in ids:
            self.note("inquiries", i)

    # ------------------------------------------------------------------ removal
    async def remove(self):
        from app.plugins.articles.plugin import ENT as ARTICLE
        from app.plugins.brands.plugin import ENT as BRAND
        from app.plugins.company import plugin as company
        from app.plugins.faq.plugin import ITEM as FAQ_ITEM
        from app.plugins.products.plugin import ENT as PRODUCT, TAG
        from app.plugins.projects.plugin import ENT as PROJECT
        from app.plugins.services.plugin import SERVICE, STEP

        await self.load_manifest()
        rows = self.manifest.get("rows", {})
        by_table = {
            "projects": PROJECT, "articles": ARTICLE, "services": SERVICE, "service_process_steps": STEP, "faq_items": FAQ_ITEM,
            "products": PRODUCT, "brands": BRAND, **{e.table: e for e in company.ENTITIES.values()},
        }
        await self.db.execute("DELETE FROM inquiries WHERE id IN (%s)" % ",".join(["0"] + [str(int(i)) for i in rows.get("inquiries", [])]))
        order = ["projects", "articles", "services", "service_process_steps", "faq_items", "company_stats", "company_timeline",
                 "company_team", "company_certifications", "company_industries", "company_testimonials", "company_offices",
                 "products", "brands"]
        for table in order:
            for rid in rows.get(table, []):
                try:
                    await by_table[table].delete(self.db, rid)
                except Exception as e:
                    print(f"  could not delete {table}#{rid}: {e}")
        # tags created for demo products (no product uses them any more)
        for t in await self.db.fetch(
            "SELECT t.id FROM product_tags t LEFT JOIN product_tag_map m ON m.tag_id=t.id WHERE m.id IS NULL"):
            await TAG.delete(self.db, t["id"])
        ids = ",".join(["0"] + [str(int(i)) for i in rows.get("categories", [])])
        await self.db.execute(f"DELETE FROM categories WHERE id IN ({ids}) ")
        # leftover documents (owners deleted already, but be safe)
        # settings the seed filled
        plugin = self.app.core.plugins.plugins["site_settings"]
        for key in dict.fromkeys(self.manifest.get("settings", [])):
            await self.db.execute("DELETE FROM site_settings WHERE skey=%s", (key,))
            await self.db.execute("DELETE FROM site_settings WHERE skey=%s", (key + "_alt",))
        await self.db.execute("DELETE FROM site_social_links WHERE url LIKE %s", ("https://linkedin.com/company/demo",))
        for k in ("favicon_png_32", "favicon_png_192", "favicon_png_512", "favicon_apple_180"):
            await self.db.execute("DELETE FROM site_settings WHERE skey=%s", (k,))
        for f in self.manifest.get("files", []):
            shutil.rmtree(ROOT / f, ignore_errors=True)
        shutil.rmtree(ROOT / "uploads" / "generated", ignore_errors=True)
        await self.db.execute("DELETE FROM settings WHERE `key`=%s", (MANIFEST_KEY,))
        self.app.revalidate.notify("*")
        print("demo seed removed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true", help="delete what the seed created")
    args = ap.parse_args()
    from app import create_app

    app = create_app()
    s = Seeder(app)
    with app.app_context():
        asyncio.run(s.remove() if args.remove else s.run())


if __name__ == "__main__":
    main()
