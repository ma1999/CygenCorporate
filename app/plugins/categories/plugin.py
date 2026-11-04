"""Categories plugin — two-level categories (parent / sub) with SEO fields.

Tables:
- categories: parent_id (NULL = main category), name, slug, description,
  meta_title/meta_description/meta_keywords, schema_json, is_active, is_deleted
  + (headless frontend) ``*_i18n`` JSON columns for every translatable field,
  short_description, icon, cover_image, standards, key_highlights, sort_order,
  og_image, noindex, updated_at. The legacy single-language columns stay in
  sync with the Persian value.

Delete behavior (soft delete):
- DELETE marks is_deleted=1 (row stays in DB).
- "پاکسازی" (purge) permanently removes soft-deleted rows that are NOT used
  anywhere (no children, not referenced by products.category_id).

Public JSON API (``/api/public``): ``GET /categories``, ``GET /categories/<slug>``.
"""
import json
import re

from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.core import content as C
from app.core import migrate
from app.core.base_plugin import BasePlugin
from app.core.admin_api import api_route, page_route, reply
from app.core.entity import Entity, Field as F, FormError, PUBLISHED_SQL, published_sql, register_admin
from app.core.public import ApiError, arg_flag, not_found, public_blueprint, public_get

ICONS = ["Gauge", "Cpu", "Activity", "Zap"]
LEGACY_COLS = "id, parent_id, name, title, slug, description, meta_title, meta_description, meta_keywords, schema_json, is_active, is_deleted, created_at"


async def _parent_options(db, exclude_id=None):
    rows = await db.fetch(
        "SELECT id, name FROM categories WHERE parent_id IS NULL AND is_deleted=0 AND id<>%s ORDER BY sort_order, name",
        (exclude_id or 0,),
    )
    return [(r["id"], r["name"]) for r in rows]


def _prepare(tx, clean, existing, is_new):
    """Two levels only: the parent must be a live root category and a
    category that already has children cannot become a child."""
    pid = clean.get("parent_id")
    cid = clean.get("id")
    if not pid:
        return
    if cid and int(pid) == int(cid):
        raise FormError({"parent_id": "یک دسته نمی‌تواند والد خودش باشد"})
    parent = tx.one("SELECT id, parent_id, is_deleted FROM categories WHERE id=%s", (pid,))
    if not parent or parent["is_deleted"]:
        raise FormError({"parent_id": "دسته‌ی والد یافت نشد"})
    if parent["parent_id"]:
        raise FormError({"parent_id": "فقط دو سطح مجاز است؛ والد باید دسته‌ی اصلی باشد"})
    if cid and tx.one("SELECT id FROM categories WHERE parent_id=%s AND is_deleted=0 LIMIT 1", (cid,)):
        raise FormError({"parent_id": "این دسته زیرمجموعه دارد و نمی‌تواند خودش زیرمجموعه شود"})


ENT = Entity(
    "category", "categories", "دسته‌بندی", "دسته‌بندی‌ها",
    [
        F("name", "text", "نام دسته", i18n=True, required=True, max=191, legacy="name", declare=False),
        F("slug", "slug", "Slug (خالی = خودکار)", declare=False,
          help="حروف کوچک انگلیسی، عدد و خط تیره. اسلاگ‌های فعلی (حتی فارسی) تا وقتی تغییر نکنند معتبرند."),
        F("parent_id", "fk", "دسته‌ی والد (خالی = دسته‌ی اصلی)", ref="categories", options_fn=_parent_options, declare=False),
        F("short_description", "textarea", "توضیح کوتاه (کارت/منو)", i18n=True, rows=2, max=500),
        F("description", "textarea", "توضیح کامل", i18n=True, rows=5, legacy="description", legacy_html=True, declare=False),
        F("icon", "select", "آیکن", options=[(i, i) for i in ICONS]),
        F("cover_image", "media", "تصویر کاور"),
        F("standards", "list", "استانداردها (هر مورد در یک خط؛ مثل IEC 60534)", max_items=20, max_item_len=80),
        F("key_highlights", "lines", "شاخصه‌های مهندسی (هر مورد در یک خط)", i18n=True, max_items=12, max_item_len=240),
        F("sort_order", "int", "ترتیب نمایش", min=0, max=1000000, default=0),
        F("meta_title", "text", "Meta Title", i18n=True, max=191, legacy="meta_title", declare=False, counter=60),
        F("meta_description", "textarea", "Meta Description", i18n=True, rows=2, max=500, legacy="meta_description", declare=False),
        F("meta_keywords", "text", "Meta Keywords", i18n=True, max=255, legacy="meta_keywords", declare=False),
        F("og_image", "media", "تصویر OG", alt=False),
        F("noindex", "bool", "noindex (عدم ایندکس)"),
        F("schema_json", "textarea", "اسکیمای JSON-LD (اختیاری)", rows=6, declare=False),
    ],
    path="/admin/categories", slug_field="slug", active=True,
    slug_from=lambda c: (c["name"].get("en") or ""),
    order="COALESCE(parent_id, id), parent_id IS NOT NULL, sort_order, name",
    view_path=lambda v: f"/products/category/{v.get('slug')}" if v.get("slug") else None,
    tags=lambda ent, id, row, old: ["categories", f"category:{row.get('slug') or id}"]
    + ([f"category:{old['slug']}"] if old and old.get("slug") and old["slug"] != row.get("slug") else []),
)
ENT.extra_cols = lambda c: {"title": (c["name"].get("fa") or "")}   # legacy NOT NULL column
ENT.prepare = _prepare


class Plugin(BasePlugin):
    name = "categories"
    # enabled by default on a fresh database (the headless frontend needs it);
    # an existing "plugins" row (enabled or not) is never touched
    auto_enable = True

    admin_entry = {
        "title": "دسته‌بندی‌ها",
        "icon": "🗂️",
        "url": "/admin/categories",
        "order": 11,
    }
    output_type = "html"

    # ---------------- schema ----------------
    def declare_schema(self, schema):
        # new (headless) columns first, then the legacy declaration so the
        # legacy definitions of shared columns win on a fresh database
        ENT.declare(schema, existing_table=True)
        schema.register_table("categories", {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "parent_id": "INT DEFAULT NULL",          # NULL = دسته اصلی
            "name": "VARCHAR(191) NOT NULL",
            "slug": "VARCHAR(191)",
            "description": "TEXT",
            # سئو
            "meta_title": "VARCHAR(191)",
            "meta_description": "TEXT",
            "meta_keywords": "VARCHAR(255)",
            "schema_json": "LONGTEXT",                # JSON-LD
            "is_active": "TINYINT(1) DEFAULT 1",
            "is_deleted": "TINYINT(1) DEFAULT 0",     # soft delete flag
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        })

    def maybe_run_migration(self):
        """Back-fill the Persian ``*_i18n`` values + ``updated_at`` from the
        legacy columns (idempotent) and add lookup indexes."""
        def go(cur):
            n = ENT.backfill(cur)
            if n:
                print(f"[categories] back-filled {n} i18n values")
            migrate.ensure_index(cur, "categories", "idx_cat_parent_active", "parent_id, is_active, is_deleted")
            migrate.ensure_index(cur, "categories", "idx_cat_sort", "sort_order")
        migrate.run(self.db, go)

    # ---------------- cache ----------------
    def _clear_products_cache(self, *_a):
        """Product payloads embed category info (and the public API caches
        counts), so any category write must drop the products cache too."""
        self.app.cache.invalidate_namespace("products")

    # ---------------- routes ----------------
    def register(self):
        db = self.db
        bp = Blueprint("plugin_categories", __name__)
        ENT.after_commit = lambda app, id, row, old: self._clear_products_cache()
        # create/edit use the generic multilingual form; list/delete/toggle/purge
        # keep their existing behaviour below
        register_admin(bp, ENT, routes=("create", "edit"))

        page_route(bp, "/admin/categories", "admin_list", "categories", "دسته‌بندی‌ها", "pages-categories")

        @api_route(bp, "/api/admin/categories", "api_admin_list")
        async def api_admin_list():
            rows = await db.query(
                "SELECT c.id, c.name, c.slug, c.parent_id, c.is_active, c.sort_order, p.name AS parent_name FROM categories c "
                "LEFT JOIN categories p ON p.id=c.parent_id "
                "WHERE c.is_deleted=0 ORDER BY COALESCE(c.parent_id, c.id), c.parent_id IS NOT NULL, c.sort_order, c.name"
            ) or []
            for r in rows:
                r["is_active"] = bool(r["is_active"])
            return reply(rows, meta={"total": len(rows)})

        @api_route(bp, "/api/admin/categories/<int:cid>/toggle", "api_admin_toggle", ["POST"])
        async def api_admin_toggle(cid):
            row = await db.query("SELECT slug, is_active FROM categories WHERE id=%s AND is_deleted=0", (cid,), one=True)
            if not row:
                raise ApiError(404, "not_found", "دسته‌بندی یافت نشد")
            await db.execute(
                "UPDATE categories SET is_active = 1 - is_active, updated_at=UTC_TIMESTAMP() WHERE id=%s", (cid,)
            )
            self._after_write(cid, row.get("slug"))
            return reply({"id": cid, "is_active": not bool(row["is_active"])})

        @api_route(bp, "/api/admin/categories/<int:cid>", "api_admin_delete", ["DELETE"])
        async def api_admin_delete(cid):
            """Soft delete (row stays in the DB) of the category and its subcategories."""
            row = await db.query("SELECT slug FROM categories WHERE id=%s AND is_deleted=0", (cid,), one=True)
            if not row:
                raise ApiError(404, "not_found", "دسته‌بندی یافت نشد")
            await db.execute(
                "UPDATE categories SET is_deleted=1, is_active=0, updated_at=UTC_TIMESTAMP() WHERE id=%s OR parent_id=%s", (cid, cid)
            )
            self._after_write(cid, row.get("slug"))
            return reply({"deleted": cid})

        @api_route(bp, "/api/admin/categories/purge", "api_admin_purge", ["POST"])
        async def api_admin_purge():
            """Permanently remove soft-deleted categories that are unused."""
            removed = await self._purge_unused(db)
            if removed:
                self._after_write(None, None)
            return reply({"removed": removed})

        # ---------- legacy public API (shape unchanged) ----------
        @bp.route("/api/categories")
        async def api_list():
            rows = await db.query(
                f"SELECT {LEGACY_COLS} FROM categories WHERE is_active=1 AND is_deleted=0 "
                "ORDER BY COALESCE(parent_id, id), parent_id IS NOT NULL"
            ) or []
            tree = [
                {**r, "children": [s for s in rows if s["parent_id"] == r["id"]]}
                for r in rows if not r["parent_id"]
            ]
            return self.respond({"categories": tree})

        @bp.route("/api/categories/<slug>")
        async def api_one(slug):
            r = await db.query(
                f"SELECT {LEGACY_COLS} FROM categories WHERE slug=%s AND is_active=1 AND is_deleted=0",
                (slug,), one=True,
            )
            if not r:
                return self.respond({"error": "not found"}), 404
            r["children"] = await db.query(
                f"SELECT {LEGACY_COLS} FROM categories WHERE parent_id=%s AND is_active=1 AND is_deleted=0",
                (r["id"],),
            ) or []
            return self.respond(r)

        # ---------- public page with schema ----------
        @bp.route("/category/<slug>")
        async def public_page(slug):
            c = await db.query(
                "SELECT * FROM categories WHERE slug=%s AND is_active=1 AND is_deleted=0",
                (slug,), one=True,
            )
            if not c:
                return render_template("404.html"), 404
            c["children"] = await db.query(
                "SELECT * FROM categories WHERE parent_id=%s AND is_active=1 AND is_deleted=0",
                (c["id"],),
            ) or []
            try:
                schema = json.loads(c["schema_json"]) if c.get("schema_json") else None
            except Exception:
                schema = None
            if not schema:
                schema = self._default_schema(c)
            return render_template(
                "plugins/categories/public.html", cat=c,
                schema_json=json.dumps(schema, ensure_ascii=False),
            )

        self.app.register_blueprint(bp)
        self._register_public()

    def _after_write(self, cid, slug):
        self._clear_products_cache()
        tags = ["categories"] + ([f"category:{slug}"] if slug else [])
        self.app.revalidate.notify(*tags)

    # ---------------- public JSON API ----------------
    def _register_public(self):
        pub = public_blueprint("public_categories")
        self.app.public_providers["sitemap"]["categories"] = self._sitemap
        self.app.public_providers["home"]["categories"] = self._home

        @public_get(pub, "/categories", params=("include_empty",))
        async def categories(ctx):
            include_empty = request.args.get("include_empty", "1").strip() not in ("0", "false", "no")
            return {"categories": await self.tree(ctx, include_empty)}

        @public_get(pub, "/categories/<slug>")
        async def category(ctx, slug):
            c = await self.detail(ctx, slug)
            if not c:
                raise not_found("Category not found")
            return {"category": c}

        self.app.register_blueprint(pub)

    @staticmethod
    async def counts(db) -> dict:
        rows = await db.fetch(
            f"SELECT category_id, COUNT(*) AS c FROM products WHERE category_id IS NOT NULL AND {PUBLISHED_SQL} GROUP BY category_id"
        )
        return {r["category_id"]: r["c"] for r in rows}

    @staticmethod
    async def live_rows(db) -> list:
        """Active, non-deleted categories whose parent (if any) is also live."""
        rows = await db.fetch(
            "SELECT * FROM categories WHERE is_active=1 AND is_deleted=0 ORDER BY sort_order, id"
        )
        roots = {r["id"] for r in rows if not r["parent_id"]}
        return [r for r in rows if not r["parent_id"] or r["parent_id"] in roots]

    def card(self, ctx, r, counts, children_of, slug_of) -> dict:
        own = counts.get(r["id"], 0)
        total = own + sum(counts.get(cid, 0) for cid in children_of.get(r["id"], []))
        return {
            "id": r["id"], "slug": r["slug"],
            "parent_slug": slug_of.get(r["parent_id"]) if r["parent_id"] else None,
            "name": ctx.text(ENT.i18n_of(r, "name")),
            "short_description": ctx.text(ENT.i18n_of(r, "short_description")),
            "icon": r.get("icon") or None,
            "cover": ctx.media(r.get("cover_image"), r.get("cover_image_alt_i18n")),
            "standards": C.parse_list(r.get("standards")),
            "product_count": total,
            "sort_order": r.get("sort_order") or 0,
        }

    async def tree(self, ctx, include_empty=True) -> list:
        rows = await self.live_rows(ctx.db)
        counts = await self.counts(ctx.db)
        slug_of = {r["id"]: r["slug"] for r in rows}
        children_of = {}
        for r in rows:
            if r["parent_id"]:
                children_of.setdefault(r["parent_id"], []).append(r["id"])
        out = []
        for r in rows:
            if r["parent_id"]:
                continue
            card = self.card(ctx, r, counts, children_of, slug_of)
            kids = [self.card(ctx, k, counts, children_of, slug_of) for k in rows if k["parent_id"] == r["id"]]
            if not include_empty:
                kids = [k for k in kids if k["product_count"] > 0]
                if card["product_count"] == 0:
                    continue
            card["children"] = kids
            out.append(card)
        return out

    async def detail(self, ctx, slug):
        rows = await self.live_rows(ctx.db)
        by_slug = {r["slug"]: r for r in rows}
        r = by_slug.get(slug)
        if not r:
            return None
        counts = await self.counts(ctx.db)
        slug_of = {x["id"]: x["slug"] for x in rows}
        children_of = {}
        for x in rows:
            if x["parent_id"]:
                children_of.setdefault(x["parent_id"], []).append(x["id"])
        c = self.card(ctx, r, counts, children_of, slug_of)
        parent = next((x for x in rows if x["id"] == r["parent_id"]), None) if r["parent_id"] else None
        c.update({
            "description": ctx.text(ENT.i18n_of(r, "description")),
            "key_highlights": ctx.lst(ENT.i18n_of(r, "key_highlights")),
            "parent": {"slug": parent["slug"], "name": ctx.text(ENT.i18n_of(parent, "name"))} if parent else None,
            "children": [self.card(ctx, k, counts, children_of, slug_of) for k in rows if k["parent_id"] == r["id"]],
            "seo": ctx.seo(
                title=ENT.i18n_of(r, "meta_title"), name=ENT.i18n_of(r, "name"),
                description=ENT.i18n_of(r, "meta_description"), short=ENT.i18n_of(r, "short_description"),
                long=ENT.i18n_of(r, "description"), keywords=ENT.i18n_of(r, "meta_keywords"),
                og=r.get("og_image"), cover=r.get("cover_image"), cover_alt=r.get("cover_image_alt_i18n"),
                noindex=r.get("noindex"),
            ),
            "updated_at": ctx.iso(r.get("updated_at")),
        })
        return c

    async def _home(self, ctx, _limit):
        return await self.tree(ctx, True)

    async def _sitemap(self, ctx):
        rows = await self.live_rows(ctx.db)
        return [
            {"slug": r["slug"], "updated_at": ctx.iso(r.get("updated_at"))}
            for r in rows if not r.get("noindex")
        ]

    # ---------------- helpers ----------------
    @staticmethod
    def _slugify(text: str) -> str:
        """Replace spaces between words with dashes."""
        text = text.strip()
        text = re.sub(r"\s+", "-", text)          # فاصله‌ها -> خط تیره
        text = re.sub(r"-{2,}", "-", text)        # چند خط پشت سر هم -> یکی
        return text.strip("-")

    def _default_schema(self, c):
        """Auto-generated JSON-LD (BreadcrumbList + CollectionPage) for a category."""
        return {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": c["name"],
            "description": c.get("description") or c.get("meta_description") or "",
            "url": f"/category/{c.get('slug') or c['id']}",
        }

    async def _purge_unused(self, db) -> int:
        """Hard-delete soft-deleted categories that are truly unused."""
        deleted_ids = await db.query(
            "SELECT id FROM categories WHERE is_deleted=1"
        ) or []
        ids = [r["id"] for r in deleted_ids]
        if not ids:
            return 0
        used = set()
        # used as parent of any remaining row?
        parents = await db.query(
            "SELECT DISTINCT parent_id FROM categories WHERE parent_id IS NOT NULL"
        ) or []
        used |= {p["parent_id"] for p in parents}
        # used by products (if products has category_id)?
        try:
            prods = await db.query(
                "SELECT DISTINCT category_id FROM products WHERE category_id IS NOT NULL"
            ) or []
            used |= {p["category_id"] for p in prods}
        except Exception:
            pass  # column/table doesn't exist — ignore
        removable = [i for i in ids if i not in used]
        if not removable:
            return 0
        ph = ", ".join(["%s"] * len(removable))
        await db.execute(f"DELETE FROM categories WHERE id IN ({ph})", tuple(removable))
        return len(removable)
