"""faq plugin — frequently asked questions (spec 6.8).

Admin: ``/admin/faq`` (items) and ``/admin/faq-categories``.
Public: ``GET /api/public/faq`` (whole list, ordered by category then item).
"""
from __future__ import annotations

from flask import Blueprint

from app.core import content as C
from app.core import migrate
from app.core.base_plugin import BasePlugin
from app.core.entity import DeleteBlocked, Entity, Field as F, fa_sql, register_admin
from app.core.public import public_blueprint, public_get

CATEGORY_SEED = [
    ("engineering", "مهندسی", "Engineering"), ("documentation", "مستندات", "Documentation"),
    ("support", "پشتیبانی", "Support"), ("corporate", "شرکتی", "Corporate"),
]

CATEGORY = Entity(
    "faq_category", "faq_categories", "دسته‌ی پرسش", "دسته‌های پرسش‌های متداول",
    [
        F("slug", "slug", "Slug (خالی = خودکار)"),
        F("label", "text", "برچسب", i18n=True, required=True, max=120),
        F("sort_order", "int", "ترتیب", min=0, max=1000000, default=0),
    ],
    path="/admin/faq-categories", slug_field="slug", created_col="created_at", order="sort_order, id",
    slug_from=lambda c: (c["label"].get("en") or ""), search=["slug", "label_i18n"],
    list_columns=[("Slug", lambda r, v: r["slug"] or "—")],
    tags=lambda ent, id, row, old: ["faq"],
)


def _cat_before_delete(tx, cid):
    n = tx.one("SELECT COUNT(*) AS c FROM faq_items WHERE category_id=%s", (cid,))
    if n and n["c"]:
        raise DeleteBlocked(f"این دسته {n['c']} پرسش دارد؛ ابتدا پرسش‌ها را منتقل یا حذف کنید.")


CATEGORY.before_delete = _cat_before_delete

ITEM = Entity(
    "faq_item", "faq_items", "پرسش", "پرسش‌های متداول",
    [
        F("category_id", "fk", "دسته", ref="faq_categories", required=True,
          label_sql=fa_sql("faq_categories.label_i18n", "faq_categories.slug")),
        F("question", "text", "پرسش", i18n=True, required=True, max=500),
        F("answer", "textarea", "پاسخ (متن ساده)", i18n=True, required=True, rows=5, max=10000),
        F("sort_order", "int", "ترتیب", min=0, max=1000000, default=0),
    ],
    path="/admin/faq", active=True, created_col="created_at", order="category_id, sort_order, id",
    search=["question_i18n"],
    filters=[("category_id", "دسته", None)],  # options filled in register()
    list_columns=[("دسته", lambda r, v: r.get("category_id")), ("ترتیب", lambda r, v: r.get("sort_order") or 0),
                  ("وضعیت", lambda r, v: "فعال" if r.get("is_active") else "غیرفعال")],
    tags=lambda ent, id, row, old: ["faq"],
)


async def _category_filter(db):
    rows = await db.fetch("SELECT id, label_i18n, slug FROM faq_categories ORDER BY sort_order, id")
    return [(r["id"], C.parse_i18n(r["label_i18n"]).get("fa") or r["slug"]) for r in rows]


ITEM.filters = [("category_id", "دسته", _category_filter)]


class Plugin(BasePlugin):
    name = "faq"
    auto_enable = True
    admin_entry = {"title": "پرسش‌های متداول", "icon": "❓", "url": "/admin/faq", "order": 17}
    output_type = "json"

    def declare_schema(self, schema):
        CATEGORY.declare(schema)
        ITEM.declare(schema)

    def maybe_run_migration(self):
        def seed(cur):
            for i, (slug, fa, en) in enumerate(CATEGORY_SEED):
                cur.execute(
                    "INSERT IGNORE INTO faq_categories (slug, label_i18n, sort_order, created_at, updated_at) "
                    "VALUES (%s,%s,%s,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                    (slug, C.dump_i18n({"fa": fa, "en": en}), i),
                )

        def go(cur):
            migrate.seed_once(cur, "seed_faq_categories", seed)
            migrate.ensure_index(cur, "faq_items", "idx_faq_cat", "category_id, is_active, sort_order")

        migrate.run(self.db, go)

    def register(self):
        bp = Blueprint("plugin_faq", __name__)
        register_admin(bp, CATEGORY)
        register_admin(bp, ITEM)
        self.app.register_blueprint(bp)

        pub = public_blueprint("public_faq")

        @public_get(pub, "/faq")
        async def faq(ctx):
            cats = await ctx.db.fetch("SELECT * FROM faq_categories ORDER BY sort_order, id")
            items = await ctx.db.fetch("SELECT * FROM faq_items WHERE is_active=1 ORDER BY sort_order, id")
            by_cat = {}
            for it in items:
                by_cat.setdefault(it["category_id"], []).append(it)
            live = [c for c in cats if by_cat.get(c["id"])]
            return {
                "categories": [
                    {"slug": c["slug"], "label": ctx.text(CATEGORY.i18n_of(c, "label")), "count": len(by_cat[c["id"]])}
                    for c in live
                ],
                "items": [
                    {
                        "id": it["id"],
                        "category": {"slug": c["slug"], "label": ctx.text(CATEGORY.i18n_of(c, "label"))},
                        "question": ctx.text(ITEM.i18n_of(it, "question")),
                        "answer": ctx.text(ITEM.i18n_of(it, "answer")),
                    }
                    for c in live for it in by_cat[c["id"]]
                ],
            }

        self.app.register_blueprint(pub)
