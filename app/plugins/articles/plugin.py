"""articles plugin — news / technical articles (spec 6.6).

Admin: ``/admin/articles`` and ``/admin/article-categories``.
Public: ``GET /api/public/articles``, ``/articles/<slug>``, ``/article-categories``.
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
    arg_flag, arg_int, arg_str, meta, not_found, paginate_args, preview_target, public_blueprint, public_get,
)

CATEGORY_SEED = [
    ("engineering", "مهندسی", "Engineering"), ("innovation", "نوآوری", "Innovation"),
    ("standards", "استانداردها", "Standards"), ("corporate", "اخبار شرکت", "Corporate"),
]

CATEGORY = Entity(
    "article_category", "article_categories", "موضوع مقاله", "موضوعات مقاله",
    [
        F("slug", "slug", "Slug (خالی = خودکار)"),
        F("label", "text", "برچسب", i18n=True, required=True, max=120),
        F("sort_order", "int", "ترتیب", min=0, max=1000000, default=0),
    ],
    path="/admin/article-categories", slug_field="slug", created_col="created_at", order="sort_order, id",
    slug_from=lambda c: (c["label"].get("en") or ""), search=["slug", "label_i18n"],
    list_columns=[("Slug", lambda r, v: r["slug"] or "—")],
    tags=lambda ent, id, row, old: ["article-categories", "articles"],
)


def _cat_before_delete(tx, cid):
    n = tx.one("SELECT COUNT(*) AS c FROM articles WHERE category_id=%s", (cid,))
    if n and n["c"]:
        raise DeleteBlocked(f"این موضوع به {n['c']} مقاله اختصاص دارد؛ ابتدا موضوع آن مقاله‌ها را تغییر دهید.")


CATEGORY.before_delete = _cat_before_delete


def _status_label(r, v):
    if r.get("status") != "published":
        return "پیش‌نویس"
    return "زمان‌بندی‌شده" if r.get("published_at") and r["published_at"] > C.utcnow() else "منتشرشده"


ENT = Entity(
    "article", "articles", "مقاله", "اخبار و مقالات",
    [
        F("slug", "slug", "Slug (خالی = خودکار)", publish_required=True),
        F("title", "text", "عنوان", i18n=True, required=True, max=191),
        F("excerpt", "textarea", "چکیده", i18n=True, rows=3, max=600),
        F("category_id", "fk", "موضوع", ref="article_categories", required=True,
          label_sql=fa_sql("article_categories.label_i18n", "article_categories.slug")),
        F("reading_time_minutes", "int", "زمان مطالعه (دقیقه؛ خالی = خودکار)", min=1, max=600,
          help="خالی بگذارید تا از تعداد کلمات (≈۲۰۰ کلمه در دقیقه) محاسبه شود"),
        F("author_name", "text", "نام نویسنده", i18n=True, max=120),
        F("author_role", "text", "سمت نویسنده", i18n=True, max=160),
        F("cover_image", "media", "تصویر کاور"),
        F("is_featured", "bool", "مقاله‌ی ویژه"),
        F("meta_title", "text", "Meta Title", i18n=True, max=191, counter=60),
        F("meta_description", "textarea", "Meta Description", i18n=True, rows=2, max=500),
        F("meta_keywords", "text", "Meta Keywords", i18n=True, max=255),
        F("og_image", "media", "تصویر OG", alt=False),
        F("noindex", "bool", "noindex (عدم ایندکس)"),
    ],
    children=[
        Child("sections", "article_sections", "article_id", "بخش‌های مقاله", [
            F("anchor", "text", "anchor (خالی = خودکار از عنوان)", max=80, ltr=True),
            F("heading", "text", "عنوان بخش", i18n=True, required=True, max=191),
            F("paragraphs", "paragraphs", "پاراگراف‌ها (با یک خط خالی جدا کنید)", i18n=True, required=True, rows=8, max_items=100, max_item_len=5000),
        ], item_label="بخش"),
    ],
    path="/admin/articles", slug_field="slug", status=True, created_col="created_at",
    slug_from=lambda c: (c["title"].get("en") or c["title"].get("fa") or ""),
    order="COALESCE(published_at, created_at) DESC, id DESC", search=["slug", "title_i18n", "search_text"],
    filters=[("status", "وضعیت", [("draft", "پیش‌نویس"), ("published", "منتشرشده")])],
    list_columns=[("وضعیت", _status_label), ("ویژه", lambda r, v: "★" if r.get("is_featured") else "")],
    view_path=lambda v: f"/news/{quote(v['slug'])}" if v.get("slug") else None,
    tags=lambda ent, id, row, old: ["articles", f"article:{row.get('slug') or id}"]
    + ([f"article:{old['slug']}"] if old and old.get("slug") and old["slug"] != row.get("slug") else []),
)


def _validate(clean, errors, values):
    seen = set()
    for i, s in enumerate(clean.get("sections") or []):
        a = (s.get("anchor") or "").strip().lower()
        if a:
            if not C.valid_slug(a):
                errors[f"sections-{i}-anchor"] = "anchor فقط حروف کوچک انگلیسی، عدد و خط تیره"
            elif a in seen:
                errors[f"sections-{i}-anchor"] = "anchor باید در مقاله یکتا باشد"
            seen.add(a)


def _prepare(tx, clean, existing, is_new):
    """Unique anchors from headings; auto reading time from the Persian text."""
    used = {(s.get("anchor") or "").strip().lower() for s in clean.get("sections") or [] if s.get("anchor")}
    for i, s in enumerate(clean.get("sections") or []):
        a = (s.get("anchor") or "").strip().lower()
        if not a:
            base = C.slugify((s.get("heading") or {}).get("en") or (s.get("heading") or {}).get("fa") or "") or f"section-{i + 1}"
            a, n = base, 1
            while a in used:
                n += 1
                a = f"{base}-{n}"
            used.add(a)
        s["anchor"] = a


ENT.extra_validate = _validate
ENT.prepare = _prepare
ENT.extra_cols = lambda c: {
    "reading_time_auto": C.reading_time_minutes(
        [p for s in c.get("sections") or [] for p in ((s.get("paragraphs") or {}).get("fa") or [])]
        + [(c.get("excerpt") or {}).get("fa", "")]
    )
}


def _after_save(tx, aid, clean, is_new):
    cat = tx.one("SELECT label_i18n FROM article_categories WHERE id=%s", (clean.get("category_id"),)) if clean.get("category_id") else None
    parts = C.all_text_values(clean.get("title") or {}, clean.get("excerpt") or {})
    parts += C.all_text_values(cat["label_i18n"]) if cat else []
    tx.run("UPDATE articles SET search_text=%s WHERE id=%s", (C.normalize_search(" ".join(parts)), aid))


ENT.after_save = _after_save
ENT.preview_kind = "article"


class Plugin(BasePlugin):
    name = "articles"
    auto_enable = True
    admin_entry = {"title": "اخبار و مقالات", "icon": "📰", "url": "/admin/articles", "order": 15}
    output_type = "json"

    def declare_schema(self, schema):
        CATEGORY.declare(schema)
        ENT.declare(schema)
        schema.register_columns("articles", {"search_text": "LONGTEXT NULL", "reading_time_auto": "INT NULL"})

    def maybe_run_migration(self):
        def seed(cur):
            for i, (slug, fa, en) in enumerate(CATEGORY_SEED):
                cur.execute(
                    "INSERT IGNORE INTO article_categories (slug, label_i18n, sort_order, created_at, updated_at) "
                    "VALUES (%s,%s,%s,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                    (slug, C.dump_i18n({"fa": fa, "en": en}), i),
                )

        def go(cur):
            migrate.seed_once(cur, "seed_article_categories", seed)
            for table, name, cols in [
                ("articles", "idx_art_status_pub", "status, published_at"),
                ("articles", "idx_art_cat", "category_id, status"),
                ("article_sections", "idx_as_art", "article_id"),
            ]:
                migrate.ensure_index(cur, table, name, cols)

        migrate.run(self.db, go)

    def register(self):
        bp = Blueprint("plugin_articles", __name__)
        register_admin(bp, CATEGORY)
        register_admin(bp, ENT)
        self.app.register_blueprint(bp)

        pub = public_blueprint("public_articles")
        self.app.public_providers["search"]["articles"] = self.search
        self.app.public_providers["home"]["latest_articles"] = self.home
        self.app.public_providers["sitemap"]["articles"] = self.sitemap

        base_where = f"{published_sql('a')} AND a.slug IS NOT NULL AND a.slug<>''"

        @public_get(pub, "/articles", params=("category", "q", "featured", "page", "per_page", "slugs"))
        async def articles(ctx):
            page, per_page = paginate_args(12, 100)
            where, params = [base_where], []
            picked = [x.strip() for x in arg_str("slugs", 2000).split(",") if x.strip()][:24]
            if picked:   # hand-picked articles (page builder): exactly these, in this order
                rows = await ctx.db.fetch(
                    f"SELECT a.* FROM articles a WHERE a.slug IN ({','.join(['%s'] * len(picked))}) AND {base_where}", tuple(picked))
                by = {r["slug"]: r for r in rows}
                ordered = [by[x] for x in picked if x in by]
                return {"articles": await self.cards(ctx, ordered), "meta": meta(len(ordered), 1, max(len(ordered), 1))}
            cat = arg_str("category", 191)
            if cat:
                where.append("a.category_id=(SELECT id FROM article_categories WHERE slug=%s)")
                params.append(cat)
            for word in C.normalize_search(arg_str("q", 120)).split():
                where.append("a.search_text LIKE %s")
                params.append("%" + C.escape_like(word) + "%")
            if arg_flag("featured"):
                where.append("a.is_featured=1")
            w = " AND ".join(where)
            total_row, rows = await asyncio.gather(
                ctx.db.fetch(f"SELECT COUNT(*) AS c FROM articles a WHERE {w}", tuple(params), one=True),
                ctx.db.fetch(f"SELECT a.* FROM articles a WHERE {w} ORDER BY a.published_at DESC, a.id DESC LIMIT %s OFFSET %s",
                             (*params, per_page, (page - 1) * per_page)),
            )
            return {"articles": await self.cards(ctx, rows), "meta": meta(total_row["c"], page, per_page)}

        @public_get(pub, "/articles/<slug>", params=("related_limit",))
        async def article(ctx, slug):
            pv = preview_target("article")
            if pv:
                r = await ctx.db.fetch("SELECT a.* FROM articles a WHERE a.id=%s AND a.slug=%s", (pv, slug), one=True)
            else:
                r = await ctx.db.fetch(f"SELECT a.* FROM articles a WHERE a.slug=%s AND {base_where}", (slug,), one=True)
            if not r:
                raise not_found("Article not found")
            limit = arg_int("related_limit", 3, 1, 12)
            secs, rel = await asyncio.gather(
                ctx.db.fetch("SELECT * FROM article_sections WHERE article_id=%s ORDER BY sort_order, id", (r["id"],)),
                ctx.db.fetch(f"SELECT a.* FROM articles a WHERE a.id<>%s AND {base_where} ORDER BY a.published_at DESC, a.id DESC LIMIT %s",
                             (r["id"], limit)),
            )
            card = (await self.cards(ctx, [r]))[0]
            card.update({
                "sections": [
                    {"anchor": s["anchor"] or f"section-{i + 1}", "heading": ctx.text(s["heading_i18n"]),
                     "paragraphs": ctx.lst(s["paragraphs_i18n"])}
                    for i, s in enumerate(secs)
                ],
                "related": await self.cards(ctx, rel),
                "seo": ctx.seo(
                    title=ENT.i18n_of(r, "meta_title"), name=ENT.i18n_of(r, "title"),
                    description=ENT.i18n_of(r, "meta_description"), short=ENT.i18n_of(r, "excerpt"),
                    keywords=ENT.i18n_of(r, "meta_keywords"), og=r.get("og_image"), cover=r.get("cover_image"),
                    cover_alt=r.get("cover_image_alt_i18n"), noindex=r.get("noindex"),
                ),
            })
            return {"article": card}

        @public_get(pub, "/article-categories")
        async def article_categories(ctx):
            rows = await ctx.db.fetch(
                f"SELECT c.slug, c.label_i18n, COUNT(a.id) AS n FROM article_categories c "
                f"LEFT JOIN articles a ON a.category_id=c.id AND {base_where} "
                f"GROUP BY c.id, c.slug, c.label_i18n, c.sort_order ORDER BY c.sort_order, c.id"
            )
            return {"categories": [{"slug": r["slug"], "label": ctx.text(r["label_i18n"]), "article_count": r["n"]} for r in rows]}

        self.app.register_blueprint(pub)

    # ---------------------------------------------------------------- serialisers
    async def cards(self, ctx, rows) -> list:
        if not rows:
            return []
        cids = sorted({r["category_id"] for r in rows if r["category_id"]})
        cats = {}
        if cids:
            for c in await ctx.db.fetch(
                f"SELECT id, slug, label_i18n FROM article_categories WHERE id IN ({','.join(['%s'] * len(cids))})", tuple(cids)):
                cats[c["id"]] = c
        out = []
        for r in rows:
            c = cats.get(r["category_id"])
            out.append({
                "id": r["id"], "slug": r["slug"], "title": ctx.text(ENT.i18n_of(r, "title")),
                "excerpt": ctx.text(ENT.i18n_of(r, "excerpt")),
                "category": {"slug": c["slug"], "label": ctx.text(c["label_i18n"])} if c else None,
                "published_at": ctx.iso(r.get("published_at")),
                "reading_time_minutes": int(r.get("reading_time_minutes") or r.get("reading_time_auto") or 1),
                "author": {"name": ctx.text(ENT.i18n_of(r, "author_name")), "role": ctx.text(ENT.i18n_of(r, "author_role"))},
                "cover": ctx.media(r.get("cover_image"), r.get("cover_image_alt_i18n")),
                "featured": bool(r.get("is_featured")),
                "updated_at": ctx.iso(r.get("updated_at")),
            })
        return out

    async def search(self, ctx, nq, limit, lang):
        where, params = [f"{published_sql('a')} AND a.slug IS NOT NULL AND a.slug<>''"], []
        for word in nq.split():
            where.append("a.search_text LIKE %s")
            params.append("%" + C.escape_like(word) + "%")
        w = " AND ".join(where)
        total_row, rows = await asyncio.gather(
            ctx.db.fetch(f"SELECT COUNT(*) AS c FROM articles a WHERE {w}", tuple(params), one=True),
            ctx.db.fetch(f"SELECT a.* FROM articles a WHERE {w} ORDER BY a.published_at DESC, a.id DESC LIMIT %s", (*params, limit)),
        )
        return await self.cards(ctx, rows), total_row["c"]

    async def home(self, ctx, limit):
        rows = await ctx.db.fetch(
            f"SELECT a.* FROM articles a WHERE {published_sql('a')} AND a.slug IS NOT NULL AND a.slug<>'' "
            f"ORDER BY a.published_at DESC, a.id DESC LIMIT %s", (limit or 3,))
        return await self.cards(ctx, rows)

    async def sitemap(self, ctx):
        rows = await ctx.db.fetch(
            f"SELECT a.slug, a.updated_at FROM articles a WHERE {published_sql('a')} AND a.slug IS NOT NULL AND a.slug<>'' "
            f"AND (a.noindex IS NULL OR a.noindex=0) ORDER BY a.id")
        return [{"slug": r["slug"], "updated_at": ctx.iso(r["updated_at"])} for r in rows]
