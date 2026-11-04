"""Products plugin — extensible product management.

Tables (auto-created via declare_schema):
- products: legacy columns (name, stock, old_price, price, meta tags, schema json, ...)
  + headless-frontend columns: model_code, ``*_i18n`` multilingual JSON,
  certifications, brand_id, is_featured, is_new, sort_order, published_at,
  og_image, noindex, search_text, updated_at
- product_images: images with alt text (alt is now translatable, order is real)
- product_specs / product_variants: technical specifications and model variants
- product_tags + product_tag_map: tags (many-to-many)

Admin: ``/admin/products`` (multilingual form, repeaters, tags),
``/admin/product-tags``; documents via ``/admin/documents/product/<id>``.
Public JSON API: see ``catalog.py`` (``/api/public/products`` ...).
The legacy ``/api/products`` and ``/product/<slug>`` keep their exact shape.
"""
import asyncio
import json
from urllib.parse import quote

from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.core import content as C
from app.core import migrate
from app.core.base_plugin import BasePlugin
from app.core.decorators import admin_required
from app.core.entity import (
    Child, DeleteBlocked, Entity, Field as F, fa_sql, published_sql, register_admin,
)
from app.core.public import not_found, public_blueprint, public_get
from app.plugins.products.catalog import Catalog

# legacy response shape: only the original columns (new columns stay out of /api/products)
LEGACY_COLS = (
    "id, title, slug, description, price, stock, status, created_at, name, old_price, sku, "
    "meta_title, meta_description, meta_keywords, schema_json, extra, category_id"
)
_pending_files: dict = {}   # product id -> stored document paths to delete after commit


# ---------------------------------------------------------------------------
# entity definitions
# ---------------------------------------------------------------------------
async def _category_options(db, exclude_id=None):
    """Active categories as parent / ↳ child; the category the product already
    has stays selectable even if it was deactivated (no silent clearing)."""
    rows = await db.fetch(
        "SELECT id, name, parent_id, is_active FROM categories WHERE is_deleted=0 ORDER BY sort_order, name"
    )
    cur = None
    if exclude_id:
        r = await db.fetch("SELECT category_id FROM products WHERE id=%s", (exclude_id,), one=True)
        cur = r["category_id"] if r else None
    live = [r for r in rows if r["is_active"] or r["id"] == cur]
    out = []
    for p in [r for r in live if not r["parent_id"]]:
        out.append((p["id"], p["name"] + ("" if p["is_active"] else " (غیرفعال)")))
        for c in [x for x in live if x["parent_id"] == p["id"]]:
            out.append((c["id"], "↳ " + c["name"] + ("" if c["is_active"] else " (غیرفعال)")))
    seen = {o[0] for o in out}
    for r in live:  # orphans (parent inactive) stay selectable too
        if r["id"] not in seen:
            out.append((r["id"], r["name"]))
    return out


async def _tag_chips(db, exclude_id=None):
    rows = await db.fetch("SELECT slug, label_i18n FROM product_tags ORDER BY sort_order, id")
    return [(r["slug"], C.parse_i18n(r["label_i18n"]).get("fa") or r["slug"]) for r in rows]


async def _category_filter(db):
    return await _category_options(db, None)


def _status_label(r, v):
    if r.get("status") != "published":
        return "پیش‌نویس"
    pa = r.get("published_at")
    if pa and pa > C.utcnow():
        return "زمان‌بندی‌شده"
    return "منتشرشده"


ENT = Entity(
    "product", "products", "محصول", "محصولات",
    [
        F("slug", "slug", "Slug (خالی = خودکار)", declare=False, publish_required=True,
          help="حروف کوچک انگلیسی، عدد و خط تیره. اسلاگ‌های فعلی (حتی فارسی) تا وقتی تغییر نکنند معتبرند."),
        F("model_code", "text", "کد مدل", max=80, publish_required=True, ltr=True, placeholder="AS-FCV-940",
          help="مثل AS-FCV-940 — برای انتشار و جستجو لازم است"),
        F("name", "text", "نام محصول", i18n=True, required=True, max=191, legacy="name", declare=False),
        F("subtitle", "text", "زیرعنوان", i18n=True, max=255),
        F("short_description", "textarea", "توضیح کوتاه (کارت و متای توضیح)", i18n=True, rows=2, max=500),
        F("description", "textarea", "توضیحات کامل (متن ساده؛ پاراگراف‌ها با خط خالی)", i18n=True, rows=8,
          legacy="description", legacy_html=True, declare=False, max=50000),
        F("features", "lines", "ویژگی‌ها و مزایای کلیدی (هر مورد در یک خط)", i18n=True, max_items=30, max_item_len=300),
        F("category_id", "fk", "دسته‌بندی", ref="categories", options_fn=_category_options, declare=False),
        F("brand_id", "fk", "برند", ref="brands", ref_where="is_active=1",
          label_sql=fa_sql("brands.name_i18n", "brands.slug")),
        F("tags", "tokens", "تگ‌ها (هر تگ در یک خط؛ تگ جدید با نوشتن برچسب ساخته می‌شود)", options_fn=_tag_chips, rows=3,
          max_items=30, max_item_len=120),
        F("certifications", "list", "گواهی‌ها/استانداردها (هر مورد در یک خط؛ مثل IEC 60534)", max_items=30, max_item_len=80),
        F("is_featured", "bool", "شاخص (کارت پررنگ، صفحه‌ی اصلی)"),
        F("is_new", "bool", "جدید (نشان «نسل جدید»)"),
        F("sort_order", "int", "ترتیب دستی", min=0, max=1000000, default=0),
        F("sku", "text", "SKU (اختیاری)", max=64, declare=False, ltr=True),
        F("meta_title", "text", "Meta Title", i18n=True, max=191, legacy="meta_title", declare=False, counter=60),
        F("meta_description", "textarea", "Meta Description", i18n=True, rows=2, max=500, legacy="meta_description", declare=False),
        F("meta_keywords", "text", "Meta Keywords", i18n=True, max=255, legacy="meta_keywords", declare=False),
        F("og_image", "media", "تصویر OG", alt=False),
        F("noindex", "bool", "noindex (عدم ایندکس)"),
        F("stock", "int", "موجودی (قدیمی؛ در API عمومی نمایش داده نمی‌شود)", min=0, max=10 ** 9, declare=False, default=0),
        F("old_price", "float", "قیمت قدیم (قدیمی؛ در API عمومی نیست)", min=0, declare=False),
        F("price", "float", "قیمت (قدیمی؛ در API عمومی نیست)", min=0, declare=False),
        F("schema_json", "textarea", "اسکیمای محصول (JSON-LD — خالی = خودکار)", rows=6, declare=False),
    ],
    children=[
        Child("specs", "product_specs", "product_id", "مشخصات فنی", [
            F("label", "text", "برچسب", i18n=True, required=True, max=191),
            F("value", "text", "مقدار", i18n=True, required=True, max=500),
        ], item_label="مشخصه"),
        Child("variants", "product_variants", "product_id", "مدل‌ها / پیکربندی‌ها", [
            F("model_code", "text", "کد مدل", required=True, max=80, ltr=True),
            F("name", "text", "نام", i18n=True, required=True, max=191),
            F("configuration", "text", "پیکربندی", i18n=True, max=500),
            F("operating_range", "text", "محدوده‌ی کاری", i18n=True, max=255),
            F("application", "text", "کاربرد", i18n=True, max=500),
        ], item_label="مدل"),
        Child("images", "product_images", "product_id", "تصاویر (اولین تصویر = کاور)", [
            F("url", "media", "تصویر", required=True, declare=False, alt_legacy="alt"),
        ], item_label="تصویر", help="با دکمه‌های ↑/↓ ترتیب را تغییر دهید؛ اولین تصویر کاور محصول است."),
    ],
    path="/admin/products", slug_field="slug", status=True, updated_col="updated_at",
    slug_from=lambda c: (c["name"].get("en") or c.get("model_code") or c["name"].get("fa") or ""),
    order="id DESC",
    search=["name", "slug", "model_code", "sku", "search_text"],
    filters=[
        ("status", "وضعیت", [("draft", "پیش‌نویس"), ("published", "منتشرشده")]),
        ("category_id", "دسته", _category_filter),
    ],
    sorts={"جدیدترین": "id DESC", "قدیمی‌ترین": "id ASC", "کد مدل": "model_code ASC", "ترتیب دستی": "sort_order ASC, id ASC"},
    list_columns=[
        ("کد مدل", lambda r, v: r.get("model_code") or "⚠ بدون کد (در API عمومی دیده نمی‌شود)"),
        ("وضعیت", _status_label),
        ("شاخص", lambda r, v: "★" if r.get("is_featured") else ""),
    ],
    view_path=lambda v: f"/products/{quote(v['slug'])}" if v.get("slug") else None,
    row_actions=[lambda r: ("اسناد", f"/admin/documents/product/{r['id']}")],
    tags=lambda ent, id, row, old: ["products", f"product:{row.get('slug') or id}"]
    + ([f"product:{old['slug']}"] if old and old.get("slug") and old["slug"] != row.get("slug") else []),
)
# legacy NOT NULL ``title`` mirrors the Persian name; price/stock default to 0
ENT.extra_cols = lambda c: {
    "title": (c["name"].get("fa") or ""),
    "price": c.get("price") or 0,
    "stock": c.get("stock") or 0,
}

TAG = Entity(
    "tag", "product_tags", "تگ", "تگ‌های محصول",
    [
        F("slug", "slug", "Slug (خالی = خودکار)"),
        F("label", "text", "برچسب", i18n=True, required=True, max=120),
        F("sort_order", "int", "ترتیب", min=0, max=1000000, default=0),
    ],
    path="/admin/product-tags", slug_field="slug", created_col="created_at", order="sort_order, id",
    slug_from=lambda c: (c["label"].get("en") or ""), search=["slug", "label_i18n"],
    list_columns=[("Slug", lambda r, v: r["slug"] or "—")],
    tags=lambda ent, id, row, old: ["tags", "products"],
)


# ---------------------------------------------------------------------------
# search text + tags (sync helpers working on a Tx)
# ---------------------------------------------------------------------------
def rebuild_search_text(tx, ids):
    """Rebuild ``products.search_text`` (normalised, all languages) for ``ids``."""
    ids = list(ids)
    if not ids:
        return
    ph = ",".join(["%s"] * len(ids))
    prods = tx.rows(
        f"SELECT id, model_code, sku, name, name_i18n, subtitle_i18n, short_description_i18n, certifications, brand_id "
        f"FROM products WHERE id IN ({ph})", tuple(ids))
    tags = {}
    for r in tx.rows(
        f"SELECT m.product_id, t.label_i18n, t.slug FROM product_tag_map m JOIN product_tags t ON t.id=m.tag_id "
        f"WHERE m.product_id IN ({ph})", tuple(ids)):
        tags.setdefault(r["product_id"], []).extend(C.all_text_values(r["label_i18n"]) + [r["slug"] or ""])
    variants = {}
    for r in tx.rows(f"SELECT product_id, model_code FROM product_variants WHERE product_id IN ({ph})", tuple(ids)):
        variants.setdefault(r["product_id"], []).append(r["model_code"] or "")
    bids = sorted({p["brand_id"] for p in prods if p["brand_id"]})
    brands = {}
    if bids:
        bph = ",".join(["%s"] * len(bids))
        for b in tx.rows(f"SELECT id, name_i18n FROM brands WHERE id IN ({bph})", tuple(bids)):
            brands[b["id"]] = C.all_text_values(b["name_i18n"])
    for p in prods:
        parts = [p["model_code"] or "", p["sku"] or "", p["name"] or ""]
        parts += C.all_text_values(p["name_i18n"], p["subtitle_i18n"], p["short_description_i18n"])
        parts += [str(x) for x in C.parse_list(p["certifications"])]
        parts += brands.get(p["brand_id"], [])
        parts += tags.get(p["id"], [])
        parts += variants.get(p["id"], [])
        text = C.normalize_search(" ".join(x for x in parts if x))
        tx.run("UPDATE products SET search_text=%s WHERE id=%s", (text, p["id"]))


def _resolve_tag_ids(tx, tokens):
    """Tokens are existing slugs or Persian labels; unknown ones are created."""
    ids = []
    for raw in tokens:
        token = (raw or "").strip()
        if not token:
            continue
        row = tx.one("SELECT id FROM product_tags WHERE slug=%s", (token,)) or tx.one(
            "SELECT id FROM product_tags WHERE JSON_UNQUOTE(JSON_EXTRACT(label_i18n, '$.fa'))=%s", (token,))
        if not row:
            base = C.slugify(token) or "tag"
            cand, n = base, 1
            while tx.one("SELECT id FROM product_tags WHERE slug=%s", (cand,)):
                n += 1
                cand = f"{base}-{n}"
            tid = tx.run(
                "INSERT INTO product_tags (slug, label_i18n, sort_order, created_at, updated_at) VALUES (%s,%s,0,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                (cand, C.dump_i18n({"fa": token})))
        else:
            tid = row["id"]
        if tid not in ids:
            ids.append(tid)
    return ids


def _after_save(tx, pid, clean, is_new):
    ids = _resolve_tag_ids(tx, clean.get("tags") or [])
    tx.run("DELETE FROM product_tag_map WHERE product_id=%s", (pid,))
    for tid in ids:
        tx.run("INSERT INTO product_tag_map (product_id, tag_id) VALUES (%s,%s)", (pid, tid))
    rebuild_search_text(tx, [pid])


async def _load_extra(db, pid, values):
    rows = await db.fetch(
        "SELECT t.slug, t.label_i18n FROM product_tag_map m JOIN product_tags t ON t.id=m.tag_id "
        "WHERE m.product_id=%s ORDER BY t.sort_order, t.id", (pid,))
    values["tags"] = [C.parse_i18n(r["label_i18n"]).get("fa") or r["slug"] for r in rows]


def _before_delete(tx, pid):
    files = tx.rows(
        "SELECT f.stored_path FROM document_files f JOIN documents d ON d.id=f.document_id "
        "WHERE d.owner_type='product' AND d.owner_id=%s", (pid,))
    _pending_files[pid] = [f["stored_path"] for f in files]


def _after_delete(tx, pid):
    tx.run("DELETE FROM product_tag_map WHERE product_id=%s", (pid,))
    docs = tx.rows("SELECT id FROM documents WHERE owner_type='product' AND owner_id=%s", (pid,))
    for d in docs:
        tx.run("DELETE FROM document_files WHERE document_id=%s", (d["id"],))
    tx.run("DELETE FROM documents WHERE owner_type='product' AND owner_id=%s", (pid,))


def _tag_after_save(tx, tid, clean, is_new):
    if is_new:
        return
    ids = [r["product_id"] for r in tx.rows("SELECT product_id FROM product_tag_map WHERE tag_id=%s", (tid,))]
    rebuild_search_text(tx, ids)


def _tag_before_delete(tx, tid):
    _pending_files[("tag", tid)] = [r["product_id"] for r in tx.rows("SELECT product_id FROM product_tag_map WHERE tag_id=%s", (tid,))]


def _tag_after_delete(tx, tid):
    tx.run("DELETE FROM product_tag_map WHERE tag_id=%s", (tid,))
    rebuild_search_text(tx, _pending_files.pop(("tag", tid), []))


async def _hidden_fields(db):
    """Enterprise-catalog mode hides the commerce fields in the admin form."""
    row = await db.fetch("SELECT value FROM site_settings WHERE skey='catalog_mode'", one=True)
    return {"price", "old_price", "stock"} if row and row["value"] == "1" else set()


ENT.hidden_fields = _hidden_fields
ENT.preview_kind = "product"
ENT.load_extra = _load_extra
ENT.after_save = _after_save
ENT.before_delete = _before_delete
ENT.after_delete = _after_delete
TAG.after_save = _tag_after_save
TAG.before_delete = _tag_before_delete
TAG.after_delete = _tag_after_delete


class Plugin(BasePlugin):
    name = "products"
    # enabled by default on a fresh database (the headless frontend needs it);
    # an existing "plugins" row (enabled or not) is never touched
    auto_enable = True
    ent = ENT

    # shown on admin dashboard when enabled
    admin_entry = {
        "title": "محصولات",
        "icon": "📦",
        "url": "/admin/products",
        "order": 10,
    }
    # "json" -> /api/products returns JSON; anything else -> normal data
    output_type = "html"

    # ---------------- cache ----------------
    CACHE_NS = "products"

    @property
    def _cache(self):
        return self.app.cache

    async def _load_product(self, pid):
        """دیتای کامل محصول (به همراه عکس‌ها) — از کش اگر تازه باشد."""

        return await self._cache.get_or_set(
            f"{self.CACHE_NS}:id:{pid}",
            lambda: self._fetch_product(pid),
            namespace=self.CACHE_NS,
        )

    async def _load_product_by_slug(self, slug):
        """محصول بر اساس slug — از کش؛ کلید slug به کلید id اشاره می‌کند."""
        pid = await self._cache.get_or_set(
            f"{self.CACHE_NS}:slug:{slug}",
            lambda: self._resolve_slug(slug),
            namespace=self.CACHE_NS,
        )
        if not pid:
            return None
        return await self._load_product(pid)

    async def _fetch_product(self, pid):
        r = await self.db.query(f"SELECT {LEGACY_COLS} FROM products WHERE id=%s", (pid,), one=True)

        if not r:
            return None
        # لیست عکس‌ها فقط با alt و url
        imgs = await self.db.query(
            "SELECT url, alt FROM product_images WHERE product_id=%s ORDER BY sort_order, id",
            (pid,),
        ) or []
        r["images"] = [{"url": i["url"], "alt": i["alt"]} for i in imgs]
        # اطلاعات دسته‌بندی (به همراه والد در صورت وجود)
        r["category"] = await self._category_info(r.get("category_id"))
        # متا تگ‌های آماده HTML
        r["metatags"] = self._build_metatags(r)

        return r

    def _build_metatags(self, p):
        """ساخت لیست متا تگ‌های آماده HTML برای محصول."""
        tags = []
        title = p.get("meta_title") or p.get("name") or ""
        desc = p.get("meta_description") or ""
        keywords = p.get("meta_keywords") or ""
        img = next((i["url"] for i in (p.get("images") or []) if i.get("url")), None)

        def esc(v):
            from html import escape
            return escape(str(v), quote=True)

        if title:
            tags.append(f'<title>{esc(title)}</title>')
            tags.append(f'<meta property="og:title" content="{esc(title)}">')
            tags.append(f'<meta name="twitter:title" content="{esc(title)}">')
        if desc:
            tags.append(f'<meta name="description" content="{esc(desc)}">')
            tags.append(f'<meta property="og:description" content="{esc(desc)}">')
            tags.append(f'<meta name="twitter:description" content="{esc(desc)}">')
        if keywords:
            tags.append(f'<meta name="keywords" content="{esc(keywords)}">')
        if img:
            tags.append(f'<meta property="og:image" content="{esc(img)}">')
            tags.append(f'<meta name="twitter:image" content="{esc(img)}">')
        slug = p.get("slug")
        if slug:
            url = f"/product/{slug}"
            tags.append(f'<link rel="canonical" href="{esc(url)}">')
            tags.append(f'<meta property="og:url" content="{esc(url)}">')
        tags.append('<meta property="og:type" content="product">')
        return tags

    async def _category_info(self, cat_id):
        """دیتای دسته‌بندی محصول: slug و title؛ اگر زیر‌دسته باشد، والد هم برمی‌گردد."""
        if not cat_id:
            return None
        c = await self.db.query(
            "SELECT id, slug, title, parent_id FROM categories WHERE id=%s", (cat_id,), one=True
        )
        if not c:
            return None
        info = {"id": c["id"], "slug": c["slug"], "title": c["title"]}
        if c.get("parent_id"):
            parent = await self.db.query(
                "SELECT id, slug, title FROM categories WHERE id=%s",
                (c["parent_id"],),
                one=True,
            )
            if parent:
                info["parent"] = {
                    "id": parent["id"],
                    "slug": parent["slug"],
                    "title": parent["title"],
                }
        return info

    async def _resolve_slug(self, slug):
        row = await self.db.query(
            "SELECT id FROM products WHERE slug=%s", (slug,), one=True
        )
        return row["id"] if row else None

    async def _invalidate_product(self, pid=None, slug=None):
        """پاک کردن کش یک محصول بعد از تغییر در دیتابیس + warm-up فوری.

        رفتار:
        1) کلیدهای مرتبط پاک می‌شوند:
           - products:list و products:list:ids
           - products:id:<pid> (اگر pid داشته باشیم یا از slug حل شود)
           - products:slug:<slug> (اگر در DB موجود باشد)
        2) بلافاصله بعد، همان کلیدها با داده‌ی تازه از DB پُر می‌شوند
           تا درخواست بعدی به کش hit بخورد (warm-up).

        اگر محصول در DB وجود نداشته باشد (مثلاً بعد از admin_delete)،
        warm-up انجام نمی‌شود ولی کلیدها همچنان پاک می‌مانند تا درخواست
        بعدی پاسخ `404 / None` بگیرد.
        """
        # ---- 1) تعیین کلیدهایی که باید حذف شوند ----
        keys = [f"{self.CACHE_NS}:list", f"{self.CACHE_NS}:list:ids"]
        if pid is None and slug:
            pid = await self._resolve_slug(slug)
        if pid:
            row = await self.db.query(
                "SELECT slug FROM products WHERE id=%s", (pid,), one=True
            )
            keys.append(f"{self.CACHE_NS}:id:{pid}")
            # اگر ردیف هنوز در DB هست، slug فعلی را هم در لیست حذف بگذار
            if row and row.get("slug"):
                keys.append(f"{self.CACHE_NS}:slug:{row['slug']}")
            # اگر slug آرگومان داده شده ولی با slug فعلی DB فرق دارد
            # (مثلاً rename)، کلید slug قدیمی را هم پاک کن
            if slug and row and row.get("slug") != slug:
                keys.append(f"{self.CACHE_NS}:slug:{slug}")
        elif slug:
            keys.append(f"{self.CACHE_NS}:slug:{slug}")

        # ---- 2) حذف یک‌باره‌ی همه‌ی کلیدها ----
        self._cache.invalidate(*keys)

        # ---- 3) warm-up فوری: همان داده‌ی تازه از DB در کش گذاشته می‌شود ----
        if pid:
            # _load_product از get_or_set استفاده می‌کند، پس اگر محصول در DB
            # نباشد چیزی کش نمی‌شود (مقدار None ذخیره نمی‌گردد).
            await self._load_product(pid)
            # کش دوباره پر کردن slug → id mapping (برای مسیر /product/<slug>)
            if slug:
                # اگر اسلاگ تغییر کرده، mapping قبلی منقضی شده و دوباره
                # از DB باید resolve شود
                row = await self.db.query(
                    "SELECT slug FROM products WHERE id=%s", (pid,), one=True
                )
                if row and row.get("slug"):
                    await self._cache.get_or_set(
                        f"{self.CACHE_NS}:slug:{row['slug']}",
                        lambda: self._resolve_slug(row["slug"]),
                        namespace=self.CACHE_NS,
                    )
            else:
                # pid داده شده، حالا slug فعلی را بخوان و mapping را warm کن
                row = await self.db.query(
                    "SELECT slug FROM products WHERE id=%s", (pid,), one=True
                )
                if row and row.get("slug"):
                    await self._cache.get_or_set(
                        f"{self.CACHE_NS}:slug:{row['slug']}",
                        lambda: self._resolve_slug(row["slug"]),
                        namespace=self.CACHE_NS,
                    )
            # لیست عمومی محصولات (products:list) هم warm شود
            await self._load_product_list()
        elif slug:
            # فقط slug داده شده، pid در DB پیدا نشد
            pass

        return keys

    async def _load_product_list(self):
        """لیست محصولات منتشر‌شده به‌همراه عکس‌ها — از کش اگر تازه باشد.

        کلید کش: products:list
        """
        return await self._cache.get_or_set(
            f"{self.CACHE_NS}:list",
            lambda: self._fetch_product_list(),
            namespace=self.CACHE_NS,
        )

    async def _fetch_product_list(self):
        rows = await self.db.query(
            f"SELECT {LEGACY_COLS} FROM products WHERE {published_sql()} ORDER BY id DESC LIMIT 100"
        ) or []
        for r in rows:
            r["images"] = await self.db.query(
                "SELECT url, alt FROM product_images WHERE product_id=%s ORDER BY sort_order, id", (r["id"],)
            ) or []
        return rows

    # ---------------- schema ----------------
    def declare_schema(self, schema):
        # new (headless) columns first; the legacy declaration below wins for
        # shared columns on a fresh database
        ENT.declare(schema, existing_table=True)
        schema.register_columns("products", {
            "search_text": "LONGTEXT NULL",       # normalised multi-language search blob
        })
        TAG.declare(schema)
        schema.register_table("product_tag_map", {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "product_id": "INT NOT NULL",
            "tag_id": "INT NOT NULL",
        })
        schema.register_table("products", {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "name": "VARCHAR(191) NOT NULL",
            "slug": "VARCHAR(191) UNIQUE",
            "description": "MEDIUMTEXT",
            "stock": "INT DEFAULT 0",
            "old_price": "DECIMAL(15,2) DEFAULT NULL",   # قیمت قدیم
            "price": "DECIMAL(15,2) DEFAULT 0",          # قیمت جدید
            "sku": "VARCHAR(64)",
            "category_id": "INT DEFAULT NULL",           # دسته‌بندی محصول
            "status": "VARCHAR(20) DEFAULT 'published'",
            # متا تگ‌های محصول
            "meta_title": "VARCHAR(191)",
            "meta_description": "TEXT",
            "meta_keywords": "VARCHAR(255)",
            # اسکیمای محصول (JSON-LD)
            "schema_json": "LONGTEXT",
            # extensibility: extra fields as JSON
            "extra": "JSON",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        })
        schema.register_table("product_images", {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "product_id": "INT NOT NULL",
            "url": "VARCHAR(500) NOT NULL",
            "alt": "VARCHAR(255) DEFAULT ''",
            "sort_order": "INT DEFAULT 0",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        })

    def maybe_run_migration(self):
        """Idempotent post-sync migration: Persian i18n back-fill from the
        legacy columns, updated_at, search text, lookup indexes."""
        def go(cur):
            n = ENT.backfill(cur)
            if n:
                print(f"[products] back-filled {n} i18n values")
            for table, name, cols, uniq in [
                ("products", "idx_prod_status_pub", "status, published_at", False),
                ("products", "idx_prod_cat_status", "category_id, status", False),
                ("products", "idx_prod_feat_sort", "is_featured, sort_order", False),
                ("products", "idx_prod_model", "model_code", False),
                ("products", "idx_prod_brand", "brand_id", False),
                ("product_tag_map", "uniq_prod_tag", "product_id, tag_id", True),
                ("product_tag_map", "idx_tagmap_tag", "tag_id", False),
                ("product_specs", "idx_spec_prod", "product_id", False),
                ("product_variants", "idx_variant_prod", "product_id", False),
                ("product_images", "idx_img_prod", "product_id", False),
            ]:
                migrate.ensure_index(cur, table, name, cols, unique=uniq)
        migrate.run(self.db, go)
        try:
            rows = asyncio.run(self.db.fetch("SELECT id FROM products WHERE search_text IS NULL"))
            if rows:
                ids = [r["id"] for r in rows]
                asyncio.run(self.db.transaction(lambda tx: rebuild_search_text(tx, ids)))
                print(f"[products] built search_text for {len(ids)} products")
        except Exception as e:
            print(f"[products] search_text build skipped: {e}")

    # ---------------- cache drop (sync; used after commits) ----------------
    def _drop_cache(self, app, pid, row, old):
        keys = [f"{self.CACHE_NS}:list", f"{self.CACHE_NS}:list:ids", f"{self.CACHE_NS}:id:{pid}"]
        for r in (row, old):
            if r and r.get("slug"):
                keys.append(f"{self.CACHE_NS}:slug:{r['slug']}")
        self._cache.invalidate(*keys)
        for rel in _pending_files.pop(pid, []):
            try:
                from app.plugins.documents.plugin import remove_stored

                remove_stored(rel)
            except Exception:
                pass

    # ---------------- routes ----------------
    def register(self):
        db = self.db
        bp = Blueprint("plugin_products", __name__)
        ENT.after_commit = self._drop_cache
        # list / create / edit / delete use the generic multilingual admin
        register_admin(bp, ENT)
        register_admin(bp, TAG)

        # ---------- legacy public API (respects output_type; shape unchanged) ----------
        @bp.route("/api/products")
        async def api_list():
            # ابتدا از کش بخوان؛ اگر نبود، لودر اجرا و در کش ذخیره می‌شود.
            rows = await self._load_product_list()
            return self.respond({"products": rows})

        @bp.route("/api/products/<int:pid>")
        async def api_one(pid):
            r = await self._load_product(pid)
            if not r or r.get("status") != "published":
                return self.respond({"error": "not found"}), 404
            return self.respond(r)

        # ---------- public product page with schema ----------
        @bp.route("/product/<slug>")
        async def public_page(slug):
            p = await self._load_product_by_slug(slug)
            if not p:
                return render_template("404.html"), 404
            schema = p.get("schema_json")
            try:
                schema = json.loads(schema) if schema else self._default_schema(p)
            except Exception:
                schema = self._default_schema(p)
            return render_template(
                "plugins/products/public.html", product=p,
                schema_json=json.dumps(schema, ensure_ascii=False),
            )

        self.app.register_blueprint(bp)
        self._register_public()
        self._register_document_owner()

    async def _slug_tags(self, pid):
        r = await self.db.query("SELECT slug FROM products WHERE id=%s", (pid,), one=True)
        return [f"product:{r['slug']}"] if r and r.get("slug") else []

    # ---------------- public JSON API ----------------
    def _register_public(self):
        cat = Catalog(self)
        self.catalog = cat   # reused by projects (equipment used) etc.
        pub = public_blueprint("public_products")
        self.app.public_providers["search"]["products"] = cat.search
        self.app.public_providers["home"]["featured_products"] = cat.home
        self.app.public_providers["sitemap"]["products"] = cat.sitemap

        @public_get(pub, "/products", params=(
            "q", "category", "brand", "tag", "featured", "is_new", "sort", "lang", "page", "per_page", "facets", "slugs"))
        async def products(ctx):
            return await cat.list(ctx)

        @public_get(pub, "/products/<slug>", params=("related_limit",))
        async def product(ctx, slug):
            return {"product": await cat.detail(ctx, slug)}

        @public_get(pub, "/tags", params=("category",))
        async def tags(ctx):
            return await cat.tags(ctx)

        self.app.register_blueprint(pub)

    def _register_document_owner(self):
        try:
            from app.plugins.documents.plugin import register_owner
        except Exception:
            return
        db = self.db

        async def title(d, pid):
            r = await d.fetch("SELECT name FROM products WHERE id=%s", (pid,), one=True)
            return r["name"] if r else None

        async def visible(d, ids):
            if not ids:
                return set()
            ph = ",".join(["%s"] * len(ids))
            rows = await d.fetch(f"SELECT id FROM products p WHERE id IN ({ph}) AND {published_sql('p')}", tuple(ids))
            return {r["id"] for r in rows}

        async def tags(d, pid):
            r = await d.fetch("SELECT slug FROM products WHERE id=%s", (pid,), one=True)
            return ["products"] + ([f"product:{r['slug']}"] if r and r["slug"] else [])

        async def touch(d, pid):
            await d.execute("UPDATE products SET updated_at=UTC_TIMESTAMP() WHERE id=%s", (pid,))
            self._cache.invalidate(f"{self.CACHE_NS}:id:{pid}")

        register_owner(
            self.app, "product", label="محصول", title=title, visible=visible, tags=tags, touch=touch,
            back=lambda pid: f"/admin/products/{pid}/edit" if pid else "/admin/products",
        )

        async def panel(d, pid, values):
            if not pid:
                return [{"title": "اسناد و فایل‌ها", "text": "ابتدا محصول را ذخیره کنید، سپس اسناد (PDF، STEP، DWG …) را اضافه کنید.", "links": []}]
            n = await d.fetch("SELECT COUNT(*) AS c FROM documents WHERE owner_type='product' AND owner_id=%s", (pid,), one=True)
            return [{"title": "اسناد و فایل‌ها", "text": f"{n['c']} سند ثبت شده است.",
                     "links": [{"label": "مدیریت اسناد", "url": f"/admin/documents/product/{pid}"}]}]

        ENT.form_panels = panel

    # ---------------- helpers ----------------
    def _default_schema(self, p):
        """Product JSON-LD schema."""
        img = [i["url"] for i in p.get("images", [])]
        return {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": p["name"],
            "description": p.get("description") or "",
            "image": img,
            "sku": p.get("sku") or str(p["id"]),
            "offers": {
                "@type": "Offer",
                "price": str(p.get("price") or 0),
                "priceCurrency": "IRR",
                "availability": (
                    "https://schema.org/InStock"
                    if (p.get("stock") or 0) > 0
                    else "https://schema.org/OutOfStock"
                ),
            },
        }
