"""projects plugin — executed projects / case studies (spec 6.5).

Admin: ``/admin/projects`` and ``/admin/project-sectors``.
Public: ``GET /api/public/projects``, ``/projects/<slug>``, ``/project-sectors``.
"""
from __future__ import annotations

import asyncio
from urllib.parse import quote

from flask import Blueprint

from app.core import content as C
from app.core import migrate
from app.core.base_plugin import BasePlugin
from app.core.entity import Child, DeleteBlocked, Entity, Field as F, fa_sql, published_sql, register_admin
from app.core.public import (
    arg_choice, arg_flag, arg_int, arg_str, meta, not_found, paginate_args, preview_target, public_blueprint, public_get,
)

SECTOR_SEED = [
    ("energy", "انرژی", "Energy"), ("water", "آب و نمک‌زدایی", "Water & Desalination"),
    ("petrochemical", "پتروشیمی", "Petrochemical"), ("pharma", "دارویی", "Pharmaceutical"),
    ("manufacturing", "تولید صنعتی", "Manufacturing"),
]
SORTS = ("newest", "manual")

SECTOR = Entity(
    "project_sector", "project_sectors", "بخش صنعتی", "بخش‌های صنعتی پروژه",
    [
        F("slug", "slug", "Slug (خالی = خودکار)"),
        F("label", "text", "برچسب", i18n=True, required=True, max=120),
        F("sort_order", "int", "ترتیب", min=0, max=1000000, default=0),
    ],
    path="/admin/project-sectors", slug_field="slug", created_col="created_at", order="sort_order, id",
    slug_from=lambda c: (c["label"].get("en") or ""), search=["slug", "label_i18n"],
    list_columns=[("Slug", lambda r, v: r["slug"] or "—")],
    tags=lambda ent, id, row, old: ["project-sectors", "projects"],
)


def _sector_before_delete(tx, sid):
    n = tx.one("SELECT COUNT(*) AS c FROM projects WHERE sector_id=%s", (sid,))
    if n and n["c"]:
        raise DeleteBlocked(f"این بخش به {n['c']} پروژه اختصاص دارد؛ ابتدا بخش آن پروژه‌ها را تغییر دهید.")


SECTOR.before_delete = _sector_before_delete


def _status_label(r, v):
    if r.get("status") != "published":
        return "پیش‌نویس"
    return "زمان‌بندی‌شده" if r.get("published_at") and r["published_at"] > C.utcnow() else "منتشرشده"


ENT = Entity(
    "project", "projects", "پروژه", "پروژه‌ها",
    [
        F("slug", "slug", "Slug (خالی = خودکار)", publish_required=True),
        F("title", "text", "عنوان پروژه", i18n=True, required=True, max=191),
        F("sector_id", "fk", "بخش صنعتی", ref="project_sectors", required=True,
          label_sql=fa_sql("project_sectors.label_i18n", "project_sectors.slug")),
        F("client", "text", "کارفرما", i18n=True, max=191),
        F("location", "text", "محل اجرا", i18n=True, max=191),
        F("completion_year", "int", "سال بهره‌برداری (میلادی)", min=1900, max=2100),
        F("cover_image", "media", "تصویر کاور"),
        F("short_description", "textarea", "توضیح کوتاه", i18n=True, rows=2, max=500),
        F("challenge", "textarea", "چالش", i18n=True, rows=5, max=10000),
        F("solution", "textarea", "راهکار", i18n=True, rows=5, max=10000),
        F("is_featured", "bool", "شاخص (صفحه‌ی اصلی)"),
        F("sort_order", "int", "ترتیب دستی", min=0, max=1000000, default=0),
        F("meta_title", "text", "Meta Title", i18n=True, max=191, counter=60),
        F("meta_description", "textarea", "Meta Description", i18n=True, rows=2, max=500),
        F("meta_keywords", "text", "Meta Keywords", i18n=True, max=255),
        F("og_image", "media", "تصویر OG", alt=False),
        F("noindex", "bool", "noindex (عدم ایندکس)"),
    ],
    children=[
        Child("gallery", "project_gallery", "project_id", "گالری تصاویر", [F("image", "media", "تصویر", required=True)], item_label="تصویر"),
        Child("impact_metrics", "project_metrics", "project_id", "دستاوردهای کمی (معمولاً ۳ مورد؛ اولی روی کارت نمایش داده می‌شود)", [
            F("label", "text", "برچسب", i18n=True, required=True, max=191),
            F("value", "text", "مقدار", i18n=True, required=True, max=191),
        ], item_label="دستاورد"),
        Child("specifications", "project_specs", "project_id", "شناسنامه فنی", [
            F("label", "text", "برچسب", i18n=True, required=True, max=191),
            F("value", "text", "مقدار", i18n=True, required=True, max=500),
        ], item_label="مشخصه"),
        Child("products", "project_products", "project_id", "تجهیزات به‌کاررفته (محصولات)", [
            F("product_id", "fk", "محصول", ref="products", required=True,
              label_sql="CONCAT(COALESCE(NULLIF(products.model_code,''), '—'), ' · ', products.name)"),
        ], item_label="محصول"),
    ],
    path="/admin/projects", slug_field="slug", status=True, created_col="created_at",
    slug_from=lambda c: (c["title"].get("en") or c["title"].get("fa") or ""),
    order="COALESCE(completion_year, 0) DESC, id DESC", search=["slug", "title_i18n", "search_text"],
    filters=[("status", "وضعیت", [("draft", "پیش‌نویس"), ("published", "منتشرشده")])],
    list_columns=[("سال", lambda r, v: r.get("completion_year") or "—"), ("وضعیت", _status_label),
                  ("شاخص", lambda r, v: "★" if r.get("is_featured") else "")],
    view_path=lambda v: f"/projects/{quote(v['slug'])}" if v.get("slug") else None,
    tags=lambda ent, id, row, old: ["projects", f"project:{row.get('slug') or id}"]
    + ([f"project:{old['slug']}"] if old and old.get("slug") and old["slug"] != row.get("slug") else []),
)


def _after_save(tx, pid, clean, is_new):
    """Search text: title, short description, location, sector label (all languages)."""
    sector = tx.one("SELECT label_i18n FROM project_sectors WHERE id=%s", (clean.get("sector_id"),)) if clean.get("sector_id") else None
    parts = C.all_text_values(clean.get("title") or {}, clean.get("short_description") or {}, clean.get("location") or {})
    parts += C.all_text_values(sector["label_i18n"]) if sector else []
    tx.run("UPDATE projects SET search_text=%s WHERE id=%s", (C.normalize_search(" ".join(parts)), pid))


ENT.after_save = _after_save
ENT.preview_kind = "project"


class Plugin(BasePlugin):
    name = "projects"
    auto_enable = True
    admin_entry = {"title": "پروژه‌ها", "icon": "🏗️", "url": "/admin/projects", "order": 14}
    output_type = "json"

    def declare_schema(self, schema):
        SECTOR.declare(schema)
        ENT.declare(schema)
        schema.register_columns("projects", {"search_text": "LONGTEXT NULL"})

    def maybe_run_migration(self):
        def seed(cur):
            for i, (slug, fa, en) in enumerate(SECTOR_SEED):
                cur.execute(
                    "INSERT IGNORE INTO project_sectors (slug, label_i18n, sort_order, created_at, updated_at) "
                    "VALUES (%s,%s,%s,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                    (slug, C.dump_i18n({"fa": fa, "en": en}), i),
                )

        def go(cur):
            migrate.seed_once(cur, "seed_project_sectors", seed)
            for table, name, cols in [
                ("projects", "idx_proj_status_pub", "status, published_at"),
                ("projects", "idx_proj_sector", "sector_id, status"),
                ("projects", "idx_proj_feat", "is_featured, sort_order"),
                ("project_gallery", "idx_pg_proj", "project_id"),
                ("project_metrics", "idx_pm_proj", "project_id"),
                ("project_specs", "idx_ps_proj", "project_id"),
                ("project_products", "idx_pp_proj", "project_id"),
            ]:
                migrate.ensure_index(cur, table, name, cols)

        migrate.run(self.db, go)

    # ------------------------------------------------------------------
    def register(self):
        bp = Blueprint("plugin_projects", __name__)
        register_admin(bp, SECTOR)
        register_admin(bp, ENT)
        self.app.register_blueprint(bp)

        pub = public_blueprint("public_projects")
        self.app.public_providers["search"]["projects"] = self.search
        self.app.public_providers["home"]["featured_projects"] = self.home
        self.app.public_providers["sitemap"]["projects"] = self.sitemap

        @public_get(pub, "/projects", params=("sector", "q", "featured", "sort", "page", "per_page", "slugs"))
        async def projects(ctx):
            sort = arg_choice("sort", SORTS, "newest")
            page, per_page = paginate_args(12, 100)
            where, params = [published_sql("p"), "p.slug IS NOT NULL", "p.slug<>''"], []
            picked = [x.strip() for x in arg_str("slugs", 2000).split(",") if x.strip()][:24]
            if picked:   # hand-picked projects (page builder): exactly these, in this order
                rows = await ctx.db.fetch(
                    f"SELECT p.* FROM projects p WHERE p.slug IN ({','.join(['%s'] * len(picked))}) AND {' AND '.join(where)}", tuple(picked))
                by = {r["slug"]: r for r in rows}
                ordered = [by[x] for x in picked if x in by]
                return {"projects": await self.cards(ctx, ordered), "meta": meta(len(ordered), 1, max(len(ordered), 1))}
            sector = arg_str("sector", 191)
            if sector:
                where.append("p.sector_id=(SELECT id FROM project_sectors WHERE slug=%s)")
                params.append(sector)
            q = C.normalize_search(arg_str("q", 120))
            for word in q.split():
                where.append("p.search_text LIKE %s")
                params.append("%" + C.escape_like(word) + "%")
            if arg_flag("featured"):
                where.append("p.is_featured=1")
            w = " AND ".join(where)
            order = "p.sort_order ASC, p.id ASC" if sort == "manual" else "COALESCE(p.completion_year, 0) DESC, p.id DESC"
            total_row, rows = await asyncio.gather(
                ctx.db.fetch(f"SELECT COUNT(*) AS c FROM projects p WHERE {w}", tuple(params), one=True),
                ctx.db.fetch(f"SELECT p.* FROM projects p WHERE {w} ORDER BY {order} LIMIT %s OFFSET %s",
                             (*params, per_page, (page - 1) * per_page)),
            )
            return {"projects": await self.cards(ctx, rows), "meta": meta(total_row["c"], page, per_page)}

        @public_get(pub, "/projects/<slug>", params=("related_limit",))
        async def project(ctx, slug):
            return {"project": await self.detail(ctx, slug)}

        @public_get(pub, "/project-sectors")
        async def sectors(ctx):
            rows = await ctx.db.fetch(
                f"SELECT s.id, s.slug, s.label_i18n, COUNT(p.id) AS c FROM project_sectors s "
                f"JOIN projects p ON p.sector_id=s.id AND {published_sql('p')} AND p.slug IS NOT NULL AND p.slug<>'' "
                f"GROUP BY s.id, s.slug, s.label_i18n, s.sort_order ORDER BY s.sort_order, s.id"
            )
            return {"sectors": [{"slug": r["slug"], "label": ctx.text(r["label_i18n"]), "project_count": r["c"]} for r in rows]}

        self.app.register_blueprint(pub)

    # ------------------------------------------------------------------ serialisers
    async def cards(self, ctx, rows) -> list:
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        ph = ",".join(["%s"] * len(ids))
        sids = sorted({r["sector_id"] for r in rows if r["sector_id"]})
        sectors, metrics = await asyncio.gather(
            ctx.db.fetch(f"SELECT id, slug, label_i18n FROM project_sectors WHERE id IN ({','.join(['%s'] * len(sids))})", tuple(sids))
            if sids else asyncio.sleep(0, result=[]),
            ctx.db.fetch(f"SELECT project_id, label_i18n, value_i18n FROM project_metrics WHERE project_id IN ({ph}) ORDER BY project_id, sort_order, id", tuple(ids)),
        )
        sec = {s["id"]: s for s in sectors}
        first = {}
        for m in metrics:
            first.setdefault(m["project_id"], m)
        out = []
        for r in rows:
            s = sec.get(r["sector_id"])
            hm = first.get(r["id"])
            out.append({
                "id": r["id"], "slug": r["slug"], "title": ctx.text(ENT.i18n_of(r, "title")),
                "sector": {"slug": s["slug"], "label": ctx.text(s["label_i18n"])} if s else None,
                "location": ctx.text(ENT.i18n_of(r, "location")),
                "completion_year": r.get("completion_year"),
                "cover": ctx.media(r.get("cover_image"), r.get("cover_image_alt_i18n")),
                "short_description": ctx.text(ENT.i18n_of(r, "short_description")),
                "featured": bool(r.get("is_featured")),
                "highlight_metric": {"label": ctx.text(hm["label_i18n"]), "value": ctx.text(hm["value_i18n"])} if hm else None,
                "updated_at": ctx.iso(r.get("updated_at")),
            })
        return out

    async def detail(self, ctx, slug) -> dict:
        pv = preview_target("project")
        if pv:
            r = await ctx.db.fetch("SELECT p.* FROM projects p WHERE p.id=%s AND p.slug=%s", (pv, slug), one=True)
        else:
            r = await ctx.db.fetch(
                f"SELECT p.* FROM projects p WHERE p.slug=%s AND {published_sql('p')}", (slug,), one=True)
        if not r:
            raise not_found("Project not found")
        pid = r["id"]
        rel_limit = arg_int("related_limit", 2, 1, 12)
        gal, mets, specs, prods, related = await asyncio.gather(
            ctx.db.fetch("SELECT * FROM project_gallery WHERE project_id=%s ORDER BY sort_order, id", (pid,)),
            ctx.db.fetch("SELECT * FROM project_metrics WHERE project_id=%s ORDER BY sort_order, id", (pid,)),
            ctx.db.fetch("SELECT * FROM project_specs WHERE project_id=%s ORDER BY sort_order, id", (pid,)),
            ctx.db.fetch("SELECT product_id FROM project_products WHERE project_id=%s ORDER BY sort_order, id", (pid,)),
            ctx.db.fetch(
                f"SELECT p.* FROM projects p WHERE p.id<>%s AND {published_sql('p')} AND p.slug IS NOT NULL AND p.slug<>'' "
                f"ORDER BY (p.sector_id <=> %s) DESC, COALESCE(p.completion_year, 0) DESC, p.id DESC LIMIT %s",
                (pid, r["sector_id"], rel_limit)),
        )
        card = (await self.cards(ctx, [r]))[0]
        products_plugin = self.app.core.plugins.plugins.get("products")
        product_cards = []
        if products_plugin is not None and getattr(products_plugin, "catalog", None):
            product_cards = await products_plugin.catalog.by_ids(ctx, [p["product_id"] for p in prods])
        card.update({
            "client": ctx.text(ENT.i18n_of(r, "client")),
            "challenge": ctx.text(ENT.i18n_of(r, "challenge")),
            "solution": ctx.text(ENT.i18n_of(r, "solution")),
            "gallery": [m for m in (ctx.media(g["image"], g.get("image_alt_i18n")) for g in gal) if m],
            "impact_metrics": [{"label": ctx.text(m["label_i18n"]), "value": ctx.text(m["value_i18n"])} for m in mets],
            "specifications": [{"label": ctx.text(s["label_i18n"]), "value": ctx.text(s["value_i18n"])} for s in specs],
            "products": product_cards,
            "related_projects": await self.cards(ctx, related),
            "seo": ctx.seo(
                title=ENT.i18n_of(r, "meta_title"), name=ENT.i18n_of(r, "title"),
                description=ENT.i18n_of(r, "meta_description"), short=ENT.i18n_of(r, "short_description"),
                keywords=ENT.i18n_of(r, "meta_keywords"), og=r.get("og_image"), cover=r.get("cover_image"),
                cover_alt=r.get("cover_image_alt_i18n"), noindex=r.get("noindex"),
            ),
        })
        return card

    # ------------------------------------------------------------------ providers
    async def search(self, ctx, nq, limit, lang):
        where, params = [published_sql("p"), "p.slug IS NOT NULL", "p.slug<>''"], []
        for word in nq.split():
            where.append("p.search_text LIKE %s")
            params.append("%" + C.escape_like(word) + "%")
        w = " AND ".join(where)
        total_row, rows = await asyncio.gather(
            ctx.db.fetch(f"SELECT COUNT(*) AS c FROM projects p WHERE {w}", tuple(params), one=True),
            ctx.db.fetch(f"SELECT p.* FROM projects p WHERE {w} ORDER BY COALESCE(p.completion_year, 0) DESC, p.id DESC LIMIT %s", (*params, limit)),
        )
        return await self.cards(ctx, rows), total_row["c"]

    async def home(self, ctx, limit):
        limit = limit or 3
        base = f"SELECT p.* FROM projects p WHERE {published_sql('p')} AND p.slug IS NOT NULL AND p.slug<>''"
        rows = await ctx.db.fetch(base + " AND p.is_featured=1 ORDER BY p.sort_order, p.id LIMIT %s", (limit,))
        if len(rows) < limit:
            have = [r["id"] for r in rows] or [0]
            more = await ctx.db.fetch(
                base + f" AND p.id NOT IN ({','.join(['%s'] * len(have))}) ORDER BY COALESCE(p.completion_year, 0) DESC, p.id DESC LIMIT %s",
                (*have, limit - len(rows)))
            rows += more
        return await self.cards(ctx, rows)

    async def sitemap(self, ctx):
        rows = await ctx.db.fetch(
            f"SELECT p.slug, p.updated_at FROM projects p WHERE {published_sql('p')} AND p.slug IS NOT NULL AND p.slug<>'' "
            f"AND (p.noindex IS NULL OR p.noindex=0) ORDER BY p.id")
        return [{"slug": r["slug"], "updated_at": ctx.iso(r["updated_at"])} for r in rows]
