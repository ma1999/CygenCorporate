"""site_settings plugin — identity, branding, contact, SEO, fixed image slots,
per-page meta and social links for the headless frontend (spec 6.1).

Storage: ``site_settings(skey, value)`` key/value (i18n values are JSON
objects, lists are JSON arrays) + ``site_social_links``. The legacy
``settings`` table is untouched; its ``site_title/meta_description/
meta_keywords`` seed the Persian values on first run.

Public: ``GET /api/public/site``.  Admin: ``/admin/site-settings``.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from types import SimpleNamespace

from flask import Blueprint, request

from app.core import captcha
from app.core import content as C
from app.core.base_plugin import BasePlugin
from app.core.admin_api import api_route, body, invalid, render_admin, reply
from app.core.decorators import admin_required
from app.core.entity import Child, Field, UNSET, _plain, expand_fields, field_meta, get_langs, json_to_form
from app.core.public import make_ctx, public_blueprint, public_get

PAGES = ["home", "about", "products", "services", "projects", "news", "contact", "faq", "search"]
PAGE_LABELS = {
    "home": "صفحه اصلی", "about": "درباره ما", "products": "محصولات", "services": "خدمات",
    "projects": "پروژه‌ها", "news": "اخبار", "contact": "تماس", "faq": "پرسش‌های متداول", "search": "جستجو",
}
# front i18n key (without the "web." prefix) holding the default title/description of a page
SEO_KEY = {"home": "site"}

MEDIA_SLOTS = [
    ("home.hero", "پس‌زمینه hero صفحه اصلی"), ("home.intro", "تصویر معرفی شرکت"),
    ("home.capabilities", "تصویر توانمندی‌ها"), ("about.hq", "تصویر صفحه درباره ما"),
    ("product.placeholder", "تصویر جایگزین محصول بدون تصویر"),
    ("og.products", "OG محصولات"), ("og.projects", "OG پروژه‌ها"), ("og.news", "OG اخبار"),
    ("og.services", "OG خدمات"), ("og.contact", "OG تماس"), ("og.about", "OG درباره ما"),
]
PLATFORMS = ["linkedin", "instagram", "telegram", "whatsapp", "youtube", "twitter", "facebook",
             "aparat", "eitaa", "bale", "rubika", "github"]
MAP_DOMAINS = ("google.com", "openstreetmap.org", "neshan.org", "balad.ir")

DEFAULTS = {
    "theme_primary": "#0b4f8a", "theme_primary_hover": "#083d6b", "theme_accent": "#c27803",
    "theme_secondary": "#0f172a", "theme_dark_surface": "#09111f", "theme_color": "#0b4f8a",
    "robots_index": True, "address_country_code": "IR", "seo_title_template": "{title} | {site_name}",
    "inquiry_reference_prefix": "INQ",
    # sections visible by default; maintenance / catalog mode / tracking are opt-in
    "feature_inquiry_form": True, "feature_search": True, "feature_news": True, "feature_projects": True,
    "feature_services": True, "feature_faq": True,
}
FEATURES = ["inquiry_form", "search", "news", "projects", "services", "faq"]

F = Field
GROUPS = [
    ("identity", "هویت", [
        F("name", "text", "نام سایت/شرکت", i18n=True, required=True, max=191),
        F("short_name", "text", "نام کوتاه", i18n=True, max=191),
        F("legal_name", "text", "نام حقوقی", i18n=True, max=255),
        F("tagline", "text", "شعار (نوار بالای هدر)", i18n=True, max=255),
        F("logo_subtitle", "text", "زیرعنوان لوگو", i18n=True, max=191),
        F("alternate_name", "text", "نام جایگزین (JSON-LD)", max=191),
        F("site_url", "url", "آدرس عمومی سایت (فرانت)", required=True, max=300,
          help="مطلق و بدون اسلش پایانی، مثل https://example.ir — برای canonical، sitemap و لینک اشتراک"),
    ]),
    ("branding", "برندینگ", [
        F("logo_light", "media", "لوگو روی پس‌زمینه روشن (هدر)"),
        F("logo_dark", "media", "لوگو روی پس‌زمینه تیره (فوتر)"),
        F("logo_mark", "media", "لوگوی مربع (آیکن/JSON-LD)", alt=False),
        F("favicon_ico", "media", "favicon.ico", alt=False),
        F("favicon_svg", "media", "favicon (SVG)", alt=False),
        F("favicon_png", "media", "favicon (PNG، حداقل ۵۱۲×۵۱۲)", alt=False,
          help="اندازه‌های 32/192/512/180 به‌صورت خودکار از روی آن ساخته می‌شود"),
        F("apple_touch_icon", "media", "apple-touch-icon", alt=False),
        F("og_default_image", "media", "تصویر OG پیش‌فرض"),
        F("theme_color", "hex", "theme-color مرورگر"),
    ]),
    ("colors", "رنگ‌ها", [
        F("theme_primary", "hex", "رنگ اصلی"), F("theme_primary_hover", "hex", "رنگ اصلی (hover)"),
        F("theme_accent", "hex", "رنگ تأکیدی"), F("theme_secondary", "hex", "رنگ ثانویه"),
        F("theme_dark_surface", "hex", "سطح تیره"),
    ]),
    ("contact", "تماس", [
        F("phone", "phone", "تلفن", max=60), F("email", "email", "ایمیل"),
        F("address", "textarea", "آدرس", i18n=True, rows=3, max=1000),
        F("working_hours", "text", "ساعات کاری", i18n=True, max=255),
        F("map_lat", "float", "عرض جغرافیایی", min=-90, max=90),
        F("map_lng", "float", "طول جغرافیایی", min=-180, max=180),
        F("map_embed_url", "url", "آدرس embed نقشه", max=600,
          help="فقط https و دامنه‌های google.com/maps، openstreetmap.org، neshan.org، balad.ir"),
        F("map_label", "text", "برچسب نقشه", i18n=True, max=191),
        F("address_street", "text", "خیابان (ساختاریافته)", i18n=True, max=255),
        F("address_city", "text", "شهر", i18n=True, max=120),
        F("address_region", "text", "استان/ناحیه", max=120),
        F("address_postal_code", "text", "کد پستی", max=30),
        F("address_country_code", "text", "کد کشور (ISO-3166 alpha-2)", max=2),
    ]),
    ("header", "هدر و جستجو", [
        F("header_badges", "list", "نشان‌های بالای هدر (هر مورد در یک خط)", max_items=12, max_item_len=80, rows=4),
        F("search_suggestions", "lines", "کلیدواژه‌های پیشنهادی صفحه جستجو", i18n=True, max_items=12, max_item_len=80),
    ]),
    ("seo", "سئو", [
        F("seo_default_title", "text", "عنوان پیش‌فرض", i18n=True, max=191),
        F("seo_default_description", "textarea", "توضیح پیش‌فرض", i18n=True, rows=3, max=500),
        F("seo_default_keywords", "text", "کلمات کلیدی پیش‌فرض", i18n=True, max=255),
        F("seo_title_template", "text", "قالب عنوان", max=120, help="جاگذارها: {title} و {site_name}"),
        F("robots_index", "bool", "ایندکس موتورهای جستجو (خیر = noindex برای staging)"),
        F("twitter_handle", "text", "شناسه توییتر", max=60),
        F("google_site_verification", "text", "Google site verification", max=200),
        F("bing_site_verification", "text", "Bing site verification", max=200),
    ]),
    ("analytics", "تحلیل", [
        F("ga4_measurement_id", "text", "GA4 Measurement ID (G-XXXX)", max=30),
        F("gtm_container_id", "text", "GTM Container ID (GTM-XXXX)", max=30),
    ]),
    ("advanced", "پیشرفته", [
        F("maintenance_enabled", "bool", "حالت تعمیر (فرانت صفحه‌ی تعمیر نشان می‌دهد)"),
        F("maintenance_message", "textarea", "پیام حالت تعمیر", i18n=True, rows=3, max=1000),
        F("feature_inquiry_form", "bool", "نمایش فرم استعلام/تماس"),
        F("feature_search", "bool", "نمایش جستجو"),
        F("feature_news", "bool", "نمایش اخبار و مقالات"),
        F("feature_projects", "bool", "نمایش پروژه‌ها"),
        F("feature_services", "bool", "نمایش خدمات"),
        F("feature_faq", "bool", "نمایش پرسش‌های متداول"),
        F("track_enabled", "bool", "ثبت بازدید صفحات فرانت (POST /api/public/track؛ پیش‌فرض خاموش — فقط GA/GTM)"),
        F("catalog_mode", "bool", "حالت کاتالوگ سازمانی (قیمت/قیمت قدیم/موجودی از فرم محصول مخفی شود)",
          help="فقط روی پنل اثر دارد؛ در API عمومی این فیلدها هرگز نیستند"),
    ]),
    ("inquiry", "استعلام (داخلی)", [
        F("inquiry_notify_emails", "list", "ایمیل‌های دریافت اعلان استعلام (هر ایمیل در یک خط)", max_items=10, max_item_len=200,
          help="هرگز در API عمومی نمایش داده نمی‌شود"),
        F("inquiry_reference_prefix", "text", "پیشوند شماره رهگیری", max=10,
          help="حروف بزرگ انگلیسی/عدد؛ مثل ASPD → ASPD-2026-0001"),
    ]),
    ("slots", "تصاویر ثابت سایت", [
        F(f"media.{k}", "media", label) for k, label in MEDIA_SLOTS
    ]),
    ("pages", "متای صفحات", sum([
        [
            F(f"pm.{p}.title", "text", f"{PAGE_LABELS[p]} — عنوان", i18n=True, max=191, counter=60),
            F(f"pm.{p}.description", "textarea", f"{PAGE_LABELS[p]} — توضیح", i18n=True, rows=2, max=500),
            F(f"pm.{p}.keywords", "text", f"{PAGE_LABELS[p]} — کلمات کلیدی", i18n=True, max=255),
            F(f"pm.{p}.og_image", "media", f"{PAGE_LABELS[p]} — تصویر OG", alt=False),
            F(f"pm.{p}.noindex", "bool", f"{PAGE_LABELS[p]} — noindex"),
        ]
        for p in PAGES
    ], [])),
]
ALL_FIELDS = expand_fields([f for _g, _t, fs in GROUPS for f in fs])
BY_NAME = {f.name: f for f in ALL_FIELDS}

SOCIAL = Child(
    "social", "site_social_links", "site_id", "شبکه‌های اجتماعی",
    [
        F("platform", "select", "پلتفرم", required=True, options=[(p, p) for p in PLATFORMS]),
        F("url", "url", "آدرس", required=True, max=500),
        F("label", "text", "برچسب (اختیاری)", i18n=True, max=120),
        F("is_active", "bool", "فعال", default=True),
    ],
    item_label="شبکه",
)


# ---- key/value (de)serialisation -------------------------------------------
def from_store(f: Field, raw):
    if f.i18n:
        d = C.parse_i18n(raw)
        if f.is_list:
            return {k: v for k, v in d.items() if isinstance(v, list)}
        return {k: v for k, v in d.items() if isinstance(v, str)}
    if f.kind == "list":
        return C.parse_list(raw)
    if f.kind == "bool":
        if raw is None:
            return bool(DEFAULTS.get(f.name, False))
        return str(raw) == "1"
    if f.kind in ("int", "float"):
        try:
            return float(raw) if raw not in (None, "") else None
        except ValueError:
            return None
    if raw is None or raw == "":
        return DEFAULTS.get(f.name, "") if f.kind != "media" else ""
    return str(raw)


def to_store(f: Field, clean):
    if f.i18n:
        return C.dump_i18n(clean)
    if f.kind == "list":
        return json.dumps(clean, ensure_ascii=False) if clean else None
    if f.kind == "bool":
        return "1" if clean else "0"
    if clean in (None, "", []):
        return None
    if f.kind == "float":
        return repr(float(clean))
    return str(clean)


class Plugin(BasePlugin):
    name = "site_settings"
    auto_enable = True
    admin_entry = {"title": "تنظیمات سایت", "icon": "🏷️", "url": "/admin/site-settings", "order": 2}
    output_type = "json"

    # ---------------- schema ----------------
    def declare_schema(self, schema):
        schema.register_table("site_settings", {
            "skey": "VARCHAR(100) PRIMARY KEY",
            "value": "LONGTEXT NULL",
            "updated_at": "DATETIME NULL",
        })
        SOCIAL.declare(schema)

    def maybe_run_migration(self):
        """First run: seed fa name/description/keywords from the legacy
        ``settings`` rows (idempotent: only when the key is absent)."""
        from app.core import migrate

        def go(cur):
            cur.execute("SELECT skey FROM site_settings WHERE skey IN ('name','seo_default_description','seo_default_keywords')")
            have = {r[0] for r in cur.fetchall()}
            cur.execute("SELECT `key`, `value` FROM settings WHERE `key` IN ('site_title','meta_description','meta_keywords')")
            legacy = {r[0]: r[1] for r in cur.fetchall()}
            for skey, lk in (("name", "site_title"), ("seo_default_description", "meta_description"), ("seo_default_keywords", "meta_keywords")):
                v = (legacy.get(lk) or "").strip()
                if skey not in have and v:
                    cur.execute(
                        "INSERT IGNORE INTO site_settings (skey, value, updated_at) VALUES (%s,%s,UTC_TIMESTAMP())",
                        (skey, json.dumps({"fa": v}, ensure_ascii=False)),
                    )

        migrate.run(self.db, go)

    # ---------------- data ----------------
    async def load_raw(self, db) -> dict:
        rows = await db.fetch("SELECT skey, value, updated_at FROM site_settings")
        return {r["skey"]: r for r in rows}

    async def load_values(self, db) -> dict:
        raw = await self.load_raw(db)
        vals = {f.name: from_store(f, (raw.get(f.name) or {}).get("value")) for f in ALL_FIELDS}
        soc = await db.fetch("SELECT * FROM site_social_links WHERE site_id=1 ORDER BY sort_order, id")
        vals["social"] = SOCIAL.from_rows(soc)
        vals["_updated"] = (raw.get("_updated") or {}).get("value")
        return vals

    # ---------------- validation ----------------
    @staticmethod
    def _extra_validate(clean: dict, errors: dict):
        url = clean.get("site_url") or ""
        if url:
            p = urlparse(url)
            if p.scheme not in ("http", "https") or not p.netloc:
                errors["site_url"] = "آدرس سایت باید مطلق باشد (https://example.ir)"
            elif url.endswith("/"):
                clean["site_url"] = url.rstrip("/")
        emb = clean.get("map_embed_url") or ""
        if emb:
            p = urlparse(emb)
            host = (p.hostname or "").lower()
            ok = p.scheme == "https" and any(host == d or host.endswith("." + d) for d in MAP_DOMAINS)
            if ok and host.endswith("google.com") and not p.path.startswith("/maps"):
                ok = False
            if not ok:
                errors["map_embed_url"] = "فقط https و دامنه‌های مجاز نقشه (google.com/maps، openstreetmap.org، neshan.org، balad.ir)"
        cc = (clean.get("address_country_code") or "").upper()
        if cc and not re.match(r"^[A-Z]{2}$", cc):
            errors["address_country_code"] = "کد کشور دو حرفی (مثل IR) باشد"
        clean["address_country_code"] = cc
        ga = clean.get("ga4_measurement_id") or ""
        if ga and not re.match(r"^G-[A-Z0-9]{4,20}$", ga):
            errors["ga4_measurement_id"] = "قالب GA4 باید مثل G-ABC123XYZ باشد"
        gtm = clean.get("gtm_container_id") or ""
        if gtm and not re.match(r"^GTM-[A-Z0-9]{4,12}$", gtm):
            errors["gtm_container_id"] = "قالب GTM باید مثل GTM-ABC123 باشد"
        tpl = clean.get("seo_title_template") or ""
        if tpl and not set(re.findall(r"\{(\w*)\}", tpl)) <= {"title", "site_name"}:
            errors["seo_title_template"] = "فقط جاگذارهای {title} و {site_name} مجازند"
        pre = clean.get("inquiry_reference_prefix") or ""
        if pre and not re.match(r"^[A-Za-z0-9]{1,10}$", pre):
            errors["inquiry_reference_prefix"] = "فقط حروف انگلیسی و عدد (حداکثر ۱۰)"
        clean["inquiry_reference_prefix"] = pre.upper()
        for i, e in enumerate(clean.get("inquiry_notify_emails") or []):
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", e):
                errors["inquiry_notify_emails"] = f"ایمیل نامعتبر: {e}"
                break
        fav = clean.get("favicon_png") or ""
        if fav and not fav.lower().split("?")[0].endswith(".png"):
            errors["favicon_png"] = "favicon باید فایل PNG باشد"
        elif fav:
            w, h = (C.media_meta(fav).get("width"), C.media_meta(fav).get("height"))
            if w is not None and (w < 512 or h < 512):
                errors["favicon_png"] = f"favicon PNG حداقل ۵۱۲×۵۱۲ باشد (فعلی {w}×{h})"

    # ---------------- favicons ----------------
    @staticmethod
    def generate_favicons(src_url: str) -> dict:
        """32/192/512 PNG + 180 apple icon from a ≥512px PNG; returns
        ``{key: '/assets/uploads/generated/...'}`` (empty when not possible)."""
        out = {}
        if not src_url.startswith(C.UPLOAD_PREFIX):
            return out
        try:
            from PIL import Image

            src = C.UPLOAD_ROOT / src_url[len(C.UPLOAD_PREFIX):]
            dest = C.UPLOAD_ROOT / "generated"
            dest.mkdir(parents=True, exist_ok=True)
            with Image.open(src) as im:
                im = im.convert("RGBA")
                for size, key in ((32, "favicon_png_32"), (192, "favicon_png_192"), (512, "favicon_png_512")):
                    name = f"favicon-{size}.png"
                    im.resize((size, size), Image.LANCZOS).save(dest / name, "PNG")
                    out[key] = f"{C.UPLOAD_PREFIX}generated/{name}"
                bg = Image.new("RGB", (180, 180), "white")
                ic = im.resize((180, 180), Image.LANCZOS)
                bg.paste(ic, (0, 0), ic)
                bg.save(dest / "apple-touch-180.png", "PNG")
                out["favicon_apple_180"] = f"{C.UPLOAD_PREFIX}generated/apple-touch-180.png"
        except Exception as e:
            print(f"[site_settings] favicon generation failed: {e}")
        return out

    # ---------------- save ----------------
    async def save_form(self, form, langs):
        """Return ``(errors, values)``. Absent field = untouched."""
        current = await self.load_values(self.db)
        incoming = {}
        for f in ALL_FIELDS:
            r = f.read(form, langs)
            if r is not UNSET:
                incoming[f.name] = r
        social = SOCIAL.read(form, langs)
        merged = dict(current)
        for k, v in incoming.items():
            f = BY_NAME[k]
            if f.i18n and isinstance(v, dict):
                base = dict(merged.get(k) or {})
                base.update(v)
                merged[k] = base
            else:
                merged[k] = v
        if social is not UNSET:
            merged["social"] = social
        errors, clean = {}, {}
        for f in ALL_FIELDS:
            clean[f.name] = f.coerce(merged.get(f.name, f.empty_value()), errors, f.name, langs)
        rows = []
        for i, row in enumerate(merged.get("social") or []):
            crow = {f.name: f.coerce(row.get(f.name, f.empty_value()), errors, f"social-{i}-{f.name}", langs) for f in SOCIAL.fields}
            rows.append(crow)
        self._extra_validate(clean, errors)
        # only report problems for what this request actually sent (partial
        # updates must not be blocked by unrelated, never-configured fields)
        errors = {k: m for k, m in errors.items() if k in incoming or k.startswith("social-")
                  or (k == "favicon_png" and "favicon_png" in incoming)}
        if errors:
            return errors, merged
        extra = {}
        changed_fav = "favicon_png" in incoming and clean.get("favicon_png") != current.get("favicon_png")
        if changed_fav or (clean.get("favicon_png") and not (await self.load_raw(self.db)).get("favicon_png_192")):
            if clean.get("favicon_png"):
                extra = self.generate_favicons(clean["favicon_png"])
            for k in ("favicon_png_32", "favicon_png_192", "favicon_png_512", "favicon_apple_180"):
                extra.setdefault(k, None)
        write_social = social is not UNSET

        def go(tx):
            for f in ALL_FIELDS:
                if f.name not in incoming:
                    continue
                self._put(tx, f.name, to_store(f, clean[f.name]))
            for k, v in extra.items():
                self._put(tx, k, v)
            if write_social:
                tx.run("DELETE FROM site_social_links WHERE site_id=1")
                for pos, row in enumerate(rows):
                    cols = {"site_id": 1, "sort_order": pos}
                    for f in SOCIAL.fields:
                        cols.update(f.to_db(row.get(f.name)))
                    tx.run(
                        f"INSERT INTO site_social_links ({', '.join('`'+k+'`' for k in cols)}) VALUES ({', '.join(['%s']*len(cols))})",
                        tuple(cols.values()),
                    )
            self._put(tx, "_updated", C.iso(C.utcnow()))

        await self.db.transaction(go)
        self.app.revalidate.notify("site")
        return {}, merged

    @staticmethod
    def _put(tx, key, value):
        if value is None:
            tx.run("DELETE FROM site_settings WHERE skey=%s", (key,))
        else:
            tx.run(
                "INSERT INTO site_settings (skey, value, updated_at) VALUES (%s,%s,UTC_TIMESTAMP()) "
                "ON DUPLICATE KEY UPDATE value=VALUES(value), updated_at=UTC_TIMESTAMP()",
                (key, value),
            )

    # ---------------- routes ----------------
    def register(self):
        bp = Blueprint("plugin_site_settings", __name__)

        @bp.route("/admin/site-settings")
        @admin_required
        async def admin_form():
            return await render_admin("admin_ui/entity_settings.html", api="/api/admin/site-settings",
                                      page="/admin/site-settings", page_title="تنظیمات سایت")

        def meta():
            def fm(fields):
                return [field_meta(f) for f in fields]

            return {
                "key": "site_settings", "label": "تنظیمات سایت", "status": False, "active": False, "fields": fm(ALL_FIELDS),
                "children": [{"key": SOCIAL.key, "label": SOCIAL.label, "item_label": SOCIAL.item_label,
                              "max_rows": SOCIAL.max_rows, "help": SOCIAL.help, "fields": fm(SOCIAL.fields)}],
            }

        async def payload(langs):
            values = await self.load_values(self.db)
            return {
                "entity": meta(), "languages": langs, "values": values,
                "options": {"platform": [{"value": p, "label": p} for p in PLATFORMS]},
                "groups": [{"key": k, "title": t, "fields": [f.name for f in expand_fields(list(fs))]} for k, t, fs in GROUPS],
            }

        @api_route(bp, "/api/admin/site-settings", "api_settings", ["GET", "PUT"])
        async def api_settings():
            langs = await get_langs(self.db)
            codes = [l["code"] for l in langs]
            if request.method == "PUT":
                form, errs = json_to_form(SimpleNamespace(fields=ALL_FIELDS, children=[SOCIAL]), body(), codes)
                if errs:
                    raise invalid(errs)
                errors, _values = await self.save_form(form, codes)
                if errors:
                    raise invalid(errors, "ذخیره انجام نشد؛ خطاهای فرم را بررسی کنید")
            return reply(_plain(await payload(langs)))

        self.app.register_blueprint(bp)

        # ---- public API ----
        pub = public_blueprint("public_site")

        @public_get(pub, "/site")
        async def site(ctx):
            return await self.build_public(ctx)

        self.app.public_providers["search"]["pages"] = self.search_pages
        self.app.register_blueprint(pub)

    async def search_pages(self, ctx, nq, limit, lang):
        """Static pages found through their (all-language) page_meta text."""
        meta = (await self.build_public(ctx))["site"]["page_meta"]
        out = []
        for key in ("about", "products", "services", "projects", "contact", "faq"):
            m = meta[key]
            blob = C.normalize_search(" ".join(C.all_text_values(m["title"], m["description"])))
            if all(w in blob for w in nq.split()):
                out.append({"page_key": key, "path": f"/{key}", "title": m["title"], "description": m["description"]})
        return out[:limit], len(out)

    async def build_public(self, ctx) -> dict:
        db = ctx.db
        raw = await self.load_raw(db)
        v = {f.name: from_store(f, (raw.get(f.name) or {}).get("value")) for f in ALL_FIELDS}
        soc = await db.fetch("SELECT * FROM site_social_links WHERE site_id=1 AND is_active=1 ORDER BY sort_order, id")
        langs_rows = await db.fetch(
            "SELECT code, name, native_name, direction, flag FROM i18n_languages WHERE is_active=1 ORDER BY is_default DESC, id"
        )
        i18n_defaults = await self._i18n_defaults(db)

        def T(name):  # I18nText
            return ctx.text(json.dumps(v.get(name) or {}, ensure_ascii=False))

        def M(name, alt=True):
            path = v.get(name) or ""
            alt_raw = (raw.get(f"{name}_alt") or {}).get("value") if alt else None
            return ctx.media(path, alt_raw)

        def opt(name):
            return v.get(name) or None

        favicon = {
            "ico": ctx.url(v.get("favicon_ico")), "svg": ctx.url(v.get("favicon_svg")),
            "png_32": ctx.url((raw.get("favicon_png_32") or {}).get("value")),
            "png_192": ctx.url((raw.get("favicon_png_192") or {}).get("value")),
            "png_512": ctx.url((raw.get("favicon_png_512") or {}).get("value")),
            "apple_touch": ctx.url(v.get("apple_touch_icon") or (raw.get("favicon_apple_180") or {}).get("value")),
        }
        addr_struct = {
            "street": T("address_street") if v.get("address_street") else None,
            "city": T("address_city") if v.get("address_city") else None,
            "region": opt("address_region"), "postal_code": opt("address_postal_code"),
            "country_code": v.get("address_country_code") or "IR",
        }
        default_fa = {n: (v.get(n) or {}) for n in ("seo_default_title", "seo_default_description")}
        page_meta = {}
        for p in PAGES:
            fb_title, fb_desc = i18n_defaults.get(p, ({}, {}))
            title = v.get(f"pm.{p}.title") or fb_title or v.get("seo_default_title") or {}
            desc = v.get(f"pm.{p}.description") or fb_desc or v.get("seo_default_description") or {}
            page_meta[p] = {
                "title": ctx.text(json.dumps(title, ensure_ascii=False)),
                "description": ctx.text(json.dumps(desc, ensure_ascii=False)),
                "keywords": ctx.text(json.dumps(v.get(f"pm.{p}.keywords") or {}, ensure_ascii=False)),
                "og_image": ctx.media(v.get(f"pm.{p}.og_image"), None) or self._og_fallback(ctx, v, raw, p),
                "noindex": bool(v.get(f"pm.{p}.noindex")),
            }
        active = [{"code": "fa", "name": "Persian", "native_name": "فارسی", "direction": "rtl", "flag": "🇮🇷"}]
        for r in langs_rows:
            if r["code"] == "fa":
                active[0] = {"code": "fa", "name": r["name"], "native_name": r["native_name"] or "فارسی",
                             "direction": r["direction"] or "rtl", "flag": r["flag"] or "🇮🇷"}
            else:
                active.append({"code": r["code"], "name": r["name"], "native_name": r["native_name"] or r["name"],
                               "direction": r["direction"] or "ltr", "flag": r["flag"]})
        lat, lng = v.get("map_lat"), v.get("map_lng")
        enabled = await self.app.core.plugins.enabled_names()
        site = {
            "name": T("name"), "short_name": T("short_name"), "legal_name": T("legal_name"),
            "tagline": T("tagline"), "logo_subtitle": T("logo_subtitle"),
            "alternate_name": opt("alternate_name"), "site_url": opt("site_url"),
            "branding": {
                "logo_light": M("logo_light"), "logo_dark": M("logo_dark"),
                "logo_mark": M("logo_mark", alt=False), "favicon": favicon,
                "og_default_image": M("og_default_image"), "theme_color": v.get("theme_color") or DEFAULTS["theme_color"],
            },
            "theme": {
                "primary": v.get("theme_primary") or DEFAULTS["theme_primary"],
                "primary_hover": v.get("theme_primary_hover") or DEFAULTS["theme_primary_hover"],
                "accent": v.get("theme_accent") or DEFAULTS["theme_accent"],
                "secondary": v.get("theme_secondary") or DEFAULTS["theme_secondary"],
                "dark_surface": v.get("theme_dark_surface") or DEFAULTS["theme_dark_surface"],
            },
            "contact": {
                "phone": opt("phone"), "phone_tel": C.phone_tel(v.get("phone")), "email": opt("email"),
                "address": T("address"), "working_hours": T("working_hours"),
                "map": {"lat": lat, "lng": lng, "embed_url": opt("map_embed_url"), "label": T("map_label")},
            },
            "address_structured": addr_struct,
            "social": [
                {"platform": s["platform"], "url": s["url"], "label": ctx.text(s.get("label_i18n"))} for s in soc
            ],
            "header_badges": v.get("header_badges") or [],
            "search_suggestions": ctx.lst(json.dumps(v.get("search_suggestions") or {}, ensure_ascii=False)),
            "seo": {
                "default_title": ctx.text(json.dumps(default_fa["seo_default_title"], ensure_ascii=False)),
                "default_description": ctx.text(json.dumps(default_fa["seo_default_description"], ensure_ascii=False)),
                "default_keywords": T("seo_default_keywords"),
                "title_template": v.get("seo_title_template") or DEFAULTS["seo_title_template"],
                "robots_index": bool(v.get("robots_index")), "twitter_handle": opt("twitter_handle"),
                "verification": {"google": opt("google_site_verification"), "bing": opt("bing_site_verification")},
            },
            "analytics": {"ga4_id": opt("ga4_measurement_id"), "gtm_id": opt("gtm_container_id"),
                          "track": bool(v.get("track_enabled"))},
            "maintenance": {"enabled": bool(v.get("maintenance_enabled")), "message": T("maintenance_message")},
            "features": {f: bool(v.get(f"feature_{f}")) for f in FEATURES},
            # plugin on/off switch (/admin/plugins): a disabled plugin's endpoints answer 404, so the frontend must hide its pages
            "plugins": {name: name in enabled for name in sorted(self.app.core.plugins.plugins)},
            "captcha": captcha.public_config(),
            "media": {k: M(f"media.{k}") for k, _l in MEDIA_SLOTS},
            "page_meta": page_meta,
            "languages": {"default": "fa", "active": active},
        }
        return {"site": site, "updated_at": (raw.get("_updated") or {}).get("value")}

    @staticmethod
    def _og_fallback(ctx, v, raw, page):
        """og_image for a page: its own, else the matching ``og.<page>`` slot,
        else the site default OG image."""
        slot = ctx.media(v.get(f"media.og.{page}"), (raw.get(f"media.og.{page}_alt") or {}).get("value"))
        if slot:
            return slot
        return ctx.media(v.get("og_default_image"), (raw.get("og_default_image_alt") or {}).get("value"))

    async def _i18n_defaults(self, db) -> dict:
        """Default per-page title/description from the imported frontend
        strings (``web.seo.<page>Title`` / ``...Description``)."""
        keys = []
        for p in PAGES:
            base = SEO_KEY.get(p, p)
            keys += [f"web.seo.{base}Title", f"web.seo.{base}Description"]
        ph = ",".join(["%s"] * len(keys))
        rows = await db.fetch(
            f"SELECT lang_code, translation_key, value FROM i18n_translations WHERE translation_key IN ({ph})", tuple(keys)
        )
        by = {}
        for r in rows:
            by.setdefault(r["translation_key"], {})[r["lang_code"]] = r["value"]
        out = {}
        for p in PAGES:
            base = SEO_KEY.get(p, p)
            out[p] = (by.get(f"web.seo.{base}Title", {}), by.get(f"web.seo.{base}Description", {}))
        return out
