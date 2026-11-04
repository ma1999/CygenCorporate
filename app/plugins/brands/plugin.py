"""brands plugin — product brands (spec 6.2).

Admin: ``/admin/brands``. Public: ``GET /api/public/brands``,
``GET /api/public/brands/<slug>``; products can be filtered with ``?brand=<slug>``.
"""
from __future__ import annotations

from flask import Blueprint

from app.core import content as C
from app.core import migrate
from app.core.base_plugin import BasePlugin
from app.core.entity import DeleteBlocked, Entity, Field as F, PUBLISHED_SQL, register_admin
from app.core.public import (
    arg_int, not_found, meta, paginate_args, public_blueprint, public_get,
)

ENT = Entity(
    "brand", "brands", "برند", "برندها",
    [
        F("slug", "slug", "Slug (خالی = خودکار)"),
        F("name", "text", "نام برند", i18n=True, required=True, max=191),
        F("description", "textarea", "توضیحات (متن ساده)", i18n=True, rows=4, max=2000),
        F("logo", "media", "لوگو"),
        F("website_url", "url", "وب‌سایت", max=500),
        F("sort_order", "int", "ترتیب نمایش", min=0, max=1000000, default=0),
        F("meta_title", "text", "Meta Title", i18n=True, max=191, counter=60),
        F("meta_description", "textarea", "Meta Description", i18n=True, rows=2, max=500),
        F("meta_keywords", "text", "Meta Keywords", i18n=True, max=255),
        F("og_image", "media", "تصویر OG", alt=False),
    ],
    path="/admin/brands", slug_field="slug", active=True, created_col="created_at",
    slug_from=lambda c: (c["name"].get("en") or c["name"].get("fa") or ""),
    order="sort_order, id",
    search=["slug", "name_i18n"],
    list_columns=[
        ("Slug", lambda r, v: r["slug"] or "—"),
        ("وضعیت", lambda r, v: "فعال" if r.get("is_active") else "غیرفعال"),
        ("ترتیب", lambda r, v: r.get("sort_order") or 0),
    ],
    view_path=lambda v: None,
    tags=lambda ent, id, row, old: ["brands", f"brand:{row.get('slug') or id}"],
)


def _before_delete(tx, bid):
    n = tx.one("SELECT COUNT(*) AS c FROM products WHERE brand_id=%s", (bid,))
    if n and n["c"]:
        raise DeleteBlocked(
            f"این برند به {n['c']} محصول اختصاص دارد؛ ابتدا برند آن محصولات را تغییر دهید یا برند را غیرفعال کنید."
        )


ENT.before_delete = _before_delete


def _after_save(tx, bid, clean, is_new):
    """Brand name is part of product search text -> rebuild for its products."""
    if is_new:
        return
    ids = [r["id"] for r in tx.rows("SELECT id FROM products WHERE brand_id=%s", (bid,))]
    if ids:
        try:
            from app.plugins.products.plugin import rebuild_search_text

            rebuild_search_text(tx, ids)
        except Exception as e:  # products plugin missing: nothing to rebuild
            print(f"[brands] search_text rebuild skipped: {e}")


ENT.after_save = _after_save


class Plugin(BasePlugin):
    name = "brands"
    auto_enable = True
    admin_entry = {"title": "برندها", "icon": "🏷️", "url": "/admin/brands", "order": 13}
    output_type = "json"

    def declare_schema(self, schema):
        ENT.declare(schema)

    def maybe_run_migration(self):
        def go(cur):
            migrate.ensure_index(cur, "brands", "idx_brand_active", "is_active, sort_order")
        migrate.run(self.db, go)

    def register(self):
        bp = Blueprint("plugin_brands", __name__)
        register_admin(bp, ENT)
        self.app.register_blueprint(bp)

        pub = public_blueprint("public_brands")

        @public_get(pub, "/brands", params=("page", "per_page"))
        async def brands(ctx):
            page, per_page = paginate_args(50, 100)
            total = (await ctx.db.fetch("SELECT COUNT(*) AS c FROM brands WHERE is_active=1", one=True))["c"]
            rows = await ctx.db.fetch(
                "SELECT * FROM brands WHERE is_active=1 ORDER BY sort_order, id LIMIT %s OFFSET %s",
                (per_page, (page - 1) * per_page),
            )
            counts = await self.counts(ctx.db)
            return {"brands": [self.card(ctx, r, counts) for r in rows], "meta": meta(total, page, per_page)}

        @public_get(pub, "/brands/<slug>")
        async def brand(ctx, slug):
            r = await ctx.db.fetch("SELECT * FROM brands WHERE slug=%s AND is_active=1", (slug,), one=True)
            if not r:
                raise not_found("Brand not found")
            counts = await self.counts(ctx.db)
            b = self.card(ctx, r, counts)
            b["seo"] = ctx.seo(
                title=ENT.i18n_of(r, "meta_title"), name=ENT.i18n_of(r, "name"),
                description=ENT.i18n_of(r, "meta_description"), short=ENT.i18n_of(r, "description"),
                keywords=ENT.i18n_of(r, "meta_keywords"), og=r.get("og_image"), cover=r.get("logo"),
                cover_alt=r.get("logo_alt_i18n"),
            )
            return {"brand": b}

        self.app.register_blueprint(pub)

    @staticmethod
    async def counts(db) -> dict:
        rows = await db.fetch(
            f"SELECT brand_id, COUNT(*) AS c FROM products WHERE brand_id IS NOT NULL AND {PUBLISHED_SQL} GROUP BY brand_id"
        )
        return {r["brand_id"]: r["c"] for r in rows}

    @staticmethod
    def card(ctx, r, counts) -> dict:
        return {
            "id": r["id"], "slug": r["slug"], "name": ctx.text(ENT.i18n_of(r, "name")),
            "description": ctx.text(ENT.i18n_of(r, "description")),
            "logo": ctx.media(r.get("logo"), r.get("logo_alt_i18n")),
            "website_url": r.get("website_url") or None,
            "product_count": counts.get(r["id"], 0),
        }
