"""services plugin — engineering services + the global process steps (spec 6.7).

Admin: ``/admin/services`` and ``/admin/service-steps``.
Public: ``GET /api/public/services`` (both lists, ordered, not paginated).
"""
from __future__ import annotations

from flask import Blueprint

from app.core import migrate
from app.core.base_plugin import BasePlugin
from app.core.entity import Entity, Field as F, register_admin
from app.core.public import not_found, public_blueprint, public_get

ICONS = ["Settings", "ShieldCheck", "Compass", "Cpu", "Wrench", "Award"]

SERVICE = Entity(
    "service", "services", "خدمت", "خدمات",
    [
        F("slug", "slug", "Slug (خالی = خودکار)"),
        F("icon", "select", "آیکن", options=[(i, i) for i in ICONS]),
        F("title", "text", "عنوان", i18n=True, required=True, max=191),
        F("short_description", "textarea", "توضیح کوتاه", i18n=True, rows=2, max=500),
        F("description", "textarea", "توضیحات (متن ساده)", i18n=True, rows=6, max=10000),
        F("deliverables", "lines", "خروجی‌ها (هر مورد در یک خط)", i18n=True, max_items=30, max_item_len=300),
        F("industries", "lines", "صنایع بهره‌مند (هر مورد در یک خط)", i18n=True, max_items=30, max_item_len=200),
        F("sort_order", "int", "ترتیب", min=0, max=1000000, default=0),
        F("meta_title", "text", "Meta Title", i18n=True, max=191, counter=60),
        F("meta_description", "textarea", "Meta Description", i18n=True, rows=2, max=500),
        F("meta_keywords", "text", "Meta Keywords", i18n=True, max=255),
    ],
    path="/admin/services", slug_field="slug", active=True, created_col="created_at", order="sort_order, id",
    slug_from=lambda c: (c["title"].get("en") or ""), search=["slug", "title_i18n"],
    list_columns=[("آیکن", lambda r, v: r.get("icon") or "—"), ("ترتیب", lambda r, v: r.get("sort_order") or 0),
                  ("وضعیت", lambda r, v: "فعال" if r.get("is_active") else "غیرفعال")],
    tags=lambda ent, id, row, old: ["services"] + ([f"service:{row['slug']}"] if row.get("slug") else [])
    + ([f"service:{old['slug']}"] if old and old.get("slug") and old["slug"] != row.get("slug") else []),
)

STEP = Entity(
    "service_step", "service_process_steps", "مرحله‌ی فرایند", "مراحل فرایند خدمات",
    [
        F("title", "text", "عنوان", i18n=True, required=True, max=191),
        F("description", "textarea", "توضیحات", i18n=True, rows=3, max=1000),
        F("sort_order", "int", "ترتیب (شماره‌ی مرحله از روی ترتیب ساخته می‌شود)", min=0, max=1000000, default=0),
    ],
    path="/admin/service-steps", active=True, created_col="created_at", order="sort_order, id",
    search=["title_i18n"], list_columns=[("ترتیب", lambda r, v: r.get("sort_order") or 0),
                                          ("وضعیت", lambda r, v: "فعال" if r.get("is_active") else "غیرفعال")],
    tags=lambda ent, id, row, old: ["services"],
)


class Plugin(BasePlugin):
    name = "services"
    auto_enable = True
    admin_entry = {"title": "خدمات", "icon": "🛠️", "url": "/admin/services", "order": 16}
    output_type = "json"

    def declare_schema(self, schema):
        SERVICE.declare(schema)
        STEP.declare(schema)

    def maybe_run_migration(self):
        def go(cur):
            migrate.ensure_index(cur, "services", "idx_svc_active", "is_active, sort_order")
            migrate.ensure_index(cur, "service_process_steps", "idx_step_active", "is_active, sort_order")
        migrate.run(self.db, go)

    def register(self):
        bp = Blueprint("plugin_services", __name__)
        register_admin(bp, SERVICE)
        register_admin(bp, STEP)
        self.app.register_blueprint(bp)

        pub = public_blueprint("public_services")

        self.app.public_providers["sitemap"]["services"] = self.sitemap

        def card(ctx, s):
            return {
                "id": s["id"], "slug": s["slug"], "icon": s.get("icon") or None,
                "title": ctx.text(SERVICE.i18n_of(s, "title")),
                "short_description": ctx.text(SERVICE.i18n_of(s, "short_description")),
                "description": ctx.text(SERVICE.i18n_of(s, "description")),
                "deliverables": ctx.lst(SERVICE.i18n_of(s, "deliverables")),
                "industries": ctx.lst(SERVICE.i18n_of(s, "industries")),
            }

        @public_get(pub, "/services/<slug>")
        async def service(ctx, slug):
            s = await ctx.db.fetch("SELECT * FROM services WHERE slug=%s AND is_active=1", (slug,), one=True)
            if not s:
                raise not_found("Service not found")
            d = card(ctx, s)
            d["seo"] = ctx.seo(
                title=SERVICE.i18n_of(s, "meta_title"), name=SERVICE.i18n_of(s, "title"),
                description=SERVICE.i18n_of(s, "meta_description"), short=SERVICE.i18n_of(s, "short_description"),
                long=SERVICE.i18n_of(s, "description"), keywords=SERVICE.i18n_of(s, "meta_keywords"),
            )
            d["updated_at"] = ctx.iso(s.get("updated_at"))
            return {"service": d}

        @public_get(pub, "/services")
        async def services(ctx):
            svc = await ctx.db.fetch("SELECT * FROM services WHERE is_active=1 ORDER BY sort_order, id")
            steps = await ctx.db.fetch("SELECT * FROM service_process_steps WHERE is_active=1 ORDER BY sort_order, id")
            return {
                "services": [card(ctx, s) for s in svc],
                "process_steps": [
                    {"step_number": f"{i + 1:02d}", "title": ctx.text(STEP.i18n_of(s, "title")),
                     "description": ctx.text(STEP.i18n_of(s, "description"))}
                    for i, s in enumerate(steps)
                ],
            }

        self.app.register_blueprint(pub)

    async def sitemap(self, ctx):
        rows = await ctx.db.fetch("SELECT slug, updated_at FROM services WHERE is_active=1 AND slug IS NOT NULL AND slug<>'' ORDER BY sort_order, id")
        return [{"slug": r["slug"], "updated_at": ctx.iso(r["updated_at"])} for r in rows]
