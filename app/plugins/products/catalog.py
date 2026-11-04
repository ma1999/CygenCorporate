"""Public catalogue queries + serialisers for ``/api/public/products`` & friends.

All list endpoints build their payloads with a fixed number of batched
(``IN (...)``) queries — no per-product queries.
"""
from __future__ import annotations

import asyncio

from flask import request

from app.core import content as C
from app.core.entity import published_sql, lang_sql
from app.core.public import (
    arg_choice, arg_flag, arg_int, arg_lang, arg_str, meta, not_found, paginate_args, preview_target,
)

SORTS = ("featured", "name", "model_code", "newest", "manual")
VISIBLE = "p.model_code IS NOT NULL AND p.model_code<>'' AND p.slug IS NOT NULL AND p.slug<>''"


def _ph(n: int) -> str:
    return ",".join(["%s"] * n)


class Filters:
    """Parsed + resolved list filters. ``empty`` = a filter references
    something that does not exist, so the result is empty (not an error)."""

    def __init__(self):
        self.q = ""
        self.category_ids = None   # list[int] | None
        self.brand_id = None
        self.tag_ids = []
        self.featured = False
        self.is_new = False
        self.empty = False

    def where(self, exclude=None):
        w = [published_sql("p"), VISIBLE]
        params = []
        if self.q and exclude != "q":
            for word in self.q.split():
                w.append("p.search_text LIKE %s")
                params.append("%" + C.escape_like(word) + "%")
        if self.category_ids is not None and exclude != "category":
            w.append(f"p.category_id IN ({_ph(len(self.category_ids))})")
            params += list(self.category_ids)
        if self.brand_id is not None and exclude != "brand":
            w.append("p.brand_id=%s")
            params.append(self.brand_id)
        if exclude != "tag":
            for tid in self.tag_ids:
                w.append("EXISTS (SELECT 1 FROM product_tag_map m WHERE m.product_id=p.id AND m.tag_id=%s)")
                params.append(tid)
        if self.featured and exclude != "featured":
            w.append("p.is_featured=1")
        if self.is_new and exclude != "is_new":
            w.append("p.is_new=1")
        return " AND ".join(w), params


async def live_categories(db) -> list:
    rows = await db.fetch(
        "SELECT id, slug, name, name_i18n, parent_id FROM categories WHERE is_active=1 AND is_deleted=0 ORDER BY sort_order, id"
    )
    roots = {r["id"] for r in rows if not r["parent_id"]}
    return [r for r in rows if not r["parent_id"] or r["parent_id"] in roots]


async def resolve_filters(db, *, q="", category="", brand="", tag="", featured=False, is_new=False) -> Filters:
    f = Filters()
    f.q = C.normalize_search(q)
    f.featured, f.is_new = featured, is_new
    jobs = {}
    if category:
        jobs["cat"] = live_categories(db)
    if brand:
        jobs["brand"] = db.fetch("SELECT id FROM brands WHERE slug=%s AND is_active=1", (brand,), one=True)
    slugs = [s.strip() for s in tag.split(",") if s.strip()] if tag else []
    if slugs:
        jobs["tags"] = db.fetch(f"SELECT id, slug FROM product_tags WHERE slug IN ({_ph(len(slugs))})", tuple(slugs))
    res = dict(zip(jobs.keys(), await asyncio.gather(*jobs.values()))) if jobs else {}
    if category:
        cats = res["cat"]
        target = next((c for c in cats if c["slug"] == category), None)
        if not target:
            f.empty = True
        else:
            f.category_ids = [target["id"]] + [c["id"] for c in cats if c["parent_id"] == target["id"]]
    if brand:
        if not res["brand"]:
            f.empty = True
        else:
            f.brand_id = res["brand"]["id"]
    if slugs:
        found = {r["slug"]: r["id"] for r in res["tags"]}
        if any(s not in found for s in slugs):
            f.empty = True
        else:
            f.tag_ids = [found[s] for s in slugs]
    return f


def order_by(sort: str, lang: str, f: Filters):
    """Return ``(order_sql, params)``; with ``q`` an exact model_code / name
    prefix match ranks first."""
    parts, params = [], []
    if f.q:
        name = lang_sql("p.name_i18n", lang, "p.name")
        parts.append(f"CASE WHEN LOWER(p.model_code)=%s THEN 0 WHEN LOWER({name}) LIKE %s THEN 1 ELSE 2 END")
        params += [f.q, C.escape_like(f.q) + "%"]
    if sort == "name":
        parts.append(f"{lang_sql('p.name_i18n', lang, 'p.name')} ASC")
        parts.append("p.id ASC")
    elif sort == "model_code":
        parts += ["p.model_code ASC", "p.id ASC"]
    elif sort == "newest":
        parts += ["p.published_at DESC", "p.id DESC"]
    elif sort == "manual":
        parts += ["p.sort_order ASC", "p.id ASC"]
    else:  # featured
        parts += ["p.is_featured DESC", "p.model_code ASC", "p.id ASC"]
    return ", ".join(parts), params


class Catalog:
    def __init__(self, plugin):
        self.plugin = plugin
        self.app = plugin.app

    def _documents(self):
        return self.app.core.plugins.plugins.get("documents")

    # ------------------------------------------------------------------ cards
    async def cards(self, ctx, rows: list) -> list:
        """ProductCard list for DB rows (``products.*``) using batched queries."""
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        cat_ids = {r["category_id"] for r in rows if r.get("category_id")}
        brand_ids = {r["brand_id"] for r in rows if r.get("brand_id")}
        jobs = {
            "tags": ctx.db.fetch(
                f"SELECT m.product_id, t.id, t.slug, t.label_i18n FROM product_tag_map m JOIN product_tags t ON t.id=m.tag_id "
                f"WHERE m.product_id IN ({_ph(len(ids))}) ORDER BY t.sort_order, t.id", tuple(ids)),
            "imgs": ctx.db.fetch(
                f"SELECT product_id, url, alt, url_alt_i18n, sort_order, id FROM product_images WHERE product_id IN ({_ph(len(ids))}) "
                f"ORDER BY product_id, sort_order, id", tuple(ids)),
            "cats": live_categories(ctx.db) if cat_ids else asyncio.sleep(0, result=[]),
            "brands": ctx.db.fetch(
                f"SELECT id, slug, name_i18n, logo, logo_alt_i18n FROM brands WHERE is_active=1 AND id IN ({_ph(len(brand_ids))})",
                tuple(brand_ids)) if brand_ids else asyncio.sleep(0, result=[]),
        }
        res = dict(zip(jobs.keys(), await asyncio.gather(*jobs.values())))
        tags_by, cover_by = {}, {}
        for t in res["tags"]:
            tags_by.setdefault(t["product_id"], []).append({"slug": t["slug"], "label": ctx.text(t["label_i18n"])})
        for im in res["imgs"]:
            cover_by.setdefault(im["product_id"], im)
        cats = {c["id"]: c for c in res["cats"]}
        brands = {b["id"]: b for b in res["brands"]}
        out = []
        for r in rows:
            cat = cats.get(r.get("category_id"))
            br = brands.get(r.get("brand_id"))
            cv = cover_by.get(r["id"])
            out.append({
                "id": r["id"], "slug": r["slug"], "model_code": r["model_code"] or "",
                "name": ctx.text(self.plugin.ent.i18n_of(r, "name")),
                "subtitle": ctx.text(self.plugin.ent.i18n_of(r, "subtitle")),
                "short_description": ctx.text(self.plugin.ent.i18n_of(r, "short_description")),
                "featured": bool(r.get("is_featured")), "is_new": bool(r.get("is_new")),
                "cover": self._media(ctx, cv),
                "category": {"slug": cat["slug"], "name": ctx.text(cat["name_i18n"], cat["name"])} if cat else None,
                "brand": {
                    "slug": br["slug"], "name": ctx.text(br["name_i18n"]),
                    "logo": ctx.media(br.get("logo"), br.get("logo_alt_i18n")),
                } if br else None,
                "tags": tags_by.get(r["id"], []),
                "certifications": C.parse_list(r.get("certifications")),
                "updated_at": ctx.iso(r.get("updated_at")),
            })
        return out

    @staticmethod
    def _media(ctx, im):
        if not im:
            return None
        alt = im.get("url_alt_i18n")
        if not alt and im.get("alt"):
            alt = {"fa": im["alt"]}
        return ctx.media(im["url"], alt)

    async def by_ids(self, ctx, ids: list) -> list:
        """ProductCards for ``ids`` in that order (published + visible only)."""
        ids = [i for i in ids if i]
        if not ids:
            return []
        rows = await ctx.db.fetch(
            f"SELECT p.* FROM products p WHERE p.id IN ({_ph(len(ids))}) AND {published_sql('p')} AND {VISIBLE}", tuple(ids))
        by = {r["id"]: r for r in rows}
        return await self.cards(ctx, [by[i] for i in ids if i in by])

    # ------------------------------------------------------------------ list
    async def list(self, ctx) -> dict:
        picked = [x.strip() for x in arg_str("slugs", 2000).split(",") if x.strip()][:24]
        if picked:   # hand-picked products (page builder): exactly these, in this order, published + visible only
            rows = await ctx.db.fetch(
                f"SELECT p.* FROM products p WHERE p.slug IN ({_ph(len(picked))}) AND {published_sql('p')} AND {VISIBLE}", tuple(picked))
            by = {r["slug"]: r for r in rows}
            ordered = [by[x] for x in picked if x in by]
            return {"products": await self.cards(ctx, ordered), "meta": meta(len(ordered), 1, max(len(ordered), 1))}
        sort = arg_choice("sort", SORTS, "featured")
        lang = arg_lang()
        page, per_page = paginate_args(12, 100)
        f = await resolve_filters(
            ctx.db, q=arg_str("q", 120), category=arg_str("category", 191), brand=arg_str("brand", 191),
            tag=arg_str("tag", 400), featured=arg_flag("featured"), is_new=arg_flag("is_new"),
        )
        want_facets = arg_flag("facets")
        if f.empty:
            out = {"products": [], "meta": meta(0, page, per_page)}
            if want_facets:
                out["facets"] = {"categories": [], "brands": [], "tags": []}
            return out
        where, params = f.where()
        order, oparams = order_by(sort, lang, f)
        jobs = [
            ctx.db.fetch(f"SELECT COUNT(*) AS c FROM products p WHERE {where}", tuple(params), one=True),
            ctx.db.fetch(
                f"SELECT p.* FROM products p WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s",
                (*params, *oparams, per_page, (page - 1) * per_page)),
        ]
        if want_facets:
            jobs.append(self.facets(ctx, f))
        res = await asyncio.gather(*jobs)
        total, rows = res[0]["c"], res[1]
        out = {"products": await self.cards(ctx, rows), "meta": meta(total, page, per_page)}
        if want_facets:
            out["facets"] = res[2]
        return out

    async def facets(self, ctx, f: Filters) -> dict:
        wc, pc = f.where("category")
        wb, pb = f.where("brand")
        wt, pt = f.where("tag")
        jobs = [
            ctx.db.fetch(f"SELECT p.category_id AS k, COUNT(*) AS c FROM products p WHERE {wc} AND p.category_id IS NOT NULL GROUP BY p.category_id", tuple(pc)),
            ctx.db.fetch(f"SELECT p.brand_id AS k, COUNT(*) AS c FROM products p WHERE {wb} AND p.brand_id IS NOT NULL GROUP BY p.brand_id", tuple(pb)),
            ctx.db.fetch(
                f"SELECT m.tag_id AS k, COUNT(DISTINCT m.product_id) AS c FROM product_tag_map m JOIN products p ON p.id=m.product_id WHERE {wt} GROUP BY m.tag_id",
                tuple(pt)),
            live_categories(ctx.db),
            ctx.db.fetch("SELECT id, slug FROM brands WHERE is_active=1"),
            ctx.db.fetch("SELECT id, slug FROM product_tags"),
        ]
        cat_counts, brand_counts, tag_counts, cats, brands, tags = await asyncio.gather(*jobs)
        by_cat = {r["k"]: r["c"] for r in cat_counts}
        cat_out = []
        for c in cats:
            n = by_cat.get(c["id"], 0)
            if not c["parent_id"]:  # a root counts its direct children too
                n += sum(by_cat.get(k["id"], 0) for k in cats if k["parent_id"] == c["id"])
            if n:
                cat_out.append({"slug": c["slug"], "count": n})
        bslug = {b["id"]: b["slug"] for b in brands}
        tslug = {t["id"]: t["slug"] for t in tags}
        return {
            "categories": cat_out,
            "brands": [{"slug": bslug[r["k"]], "count": r["c"]} for r in brand_counts if r["k"] in bslug],
            "tags": sorted(
                [{"slug": tslug[r["k"]], "count": r["c"]} for r in tag_counts if r["k"] in tslug],
                key=lambda x: (-x["count"], x["slug"]),
            ),
        }

    # ------------------------------------------------------------------ tags
    async def tags(self, ctx) -> dict:
        category = arg_str("category", 191)
        where, params = [published_sql("p"), VISIBLE], []
        if category:
            cats = await live_categories(ctx.db)
            t = next((c for c in cats if c["slug"] == category), None)
            if not t:
                return {"tags": []}
            ids = [t["id"]] + [c["id"] for c in cats if c["parent_id"] == t["id"]]
            where.append(f"p.category_id IN ({_ph(len(ids))})")
            params += ids
        rows = await ctx.db.fetch(
            f"SELECT t.id, t.slug, t.label_i18n, COUNT(DISTINCT p.id) AS c FROM product_tags t "
            f"JOIN product_tag_map m ON m.tag_id=t.id JOIN products p ON p.id=m.product_id "
            f"WHERE {' AND '.join(where)} GROUP BY t.id, t.slug, t.label_i18n, t.sort_order ORDER BY t.sort_order, t.id",
            tuple(params),
        )
        return {"tags": [{"slug": r["slug"], "label": ctx.text(r["label_i18n"]), "product_count": r["c"]} for r in rows]}

    # ------------------------------------------------------------------ detail
    async def detail(self, ctx, slug: str) -> dict:
        pv = preview_target("product")      # ?preview=<signed token>: this ONE draft/scheduled product
        if pv:
            r = await ctx.db.fetch("SELECT p.* FROM products p WHERE p.id=%s AND p.slug=%s", (pv, slug), one=True)
        else:
            r = await ctx.db.fetch(
                f"SELECT p.* FROM products p WHERE p.slug=%s AND {published_sql('p')} AND {VISIBLE}", (slug,), one=True
            )
        if not r:
            raise not_found("Product not found")
        pid = r["id"]
        rel_limit = arg_int("related_limit", 3, 1, 12)
        docs = self._documents()
        jobs = {
            "card": self.cards(ctx, [r]),
            "imgs": ctx.db.fetch("SELECT * FROM product_images WHERE product_id=%s ORDER BY sort_order, id", (pid,)),
            "specs": ctx.db.fetch("SELECT * FROM product_specs WHERE product_id=%s ORDER BY sort_order, id", (pid,)),
            "variants": ctx.db.fetch("SELECT * FROM product_variants WHERE product_id=%s ORDER BY sort_order, id", (pid,)),
            "docs": docs.public_documents(ctx, "product", [pid]) if docs else asyncio.sleep(0, result={pid: []}),
            "cats": live_categories(ctx.db),
            "related": ctx.db.fetch(
                f"SELECT p.* FROM products p WHERE p.id<>%s AND {published_sql('p')} AND {VISIBLE} "
                f"ORDER BY (p.category_id <=> %s) DESC, p.is_featured DESC, p.model_code ASC, p.id ASC LIMIT %s",
                (pid, r.get("category_id"), rel_limit)),
        }
        res = dict(zip(jobs.keys(), await asyncio.gather(*jobs.values())))
        card = res["card"][0]
        ent = self.plugin.ent
        cats = {c["id"]: c for c in res["cats"]}
        path = []
        cat = cats.get(r.get("category_id"))
        if cat:
            if cat["parent_id"] and cat["parent_id"] in cats:
                p = cats[cat["parent_id"]]
                path.append({"slug": p["slug"], "name": ctx.text(p["name_i18n"], p["name"])})
            path.append({"slug": cat["slug"], "name": ctx.text(cat["name_i18n"], cat["name"])})
        images = [self._media(ctx, im) for im in res["imgs"]]
        images = [m for m in images if m]
        detail = dict(card)
        detail.update({
            "sku": r.get("sku") or None,
            "description": ctx.text(ent.i18n_of(r, "description")),
            "features": ctx.lst(ent.i18n_of(r, "features")),
            "images": images,
            "specifications": [
                {"label": ctx.text(s["label_i18n"]), "value": ctx.text(s["value_i18n"])} for s in res["specs"]
            ],
            "variants": [
                {
                    "model_code": v["model_code"] or "", "name": ctx.text(v["name_i18n"]),
                    "configuration": ctx.text(v["configuration_i18n"]),
                    "operating_range": ctx.text(v["operating_range_i18n"]),
                    "application": ctx.text(v["application_i18n"]),
                }
                for v in res["variants"]
            ],
            "documents": res["docs"].get(pid, []),
            "category_path": path,
            "related": await self.cards(ctx, res["related"]),
            "seo": ctx.seo(
                title=ent.i18n_of(r, "meta_title"), name=ent.i18n_of(r, "name"),
                description=ent.i18n_of(r, "meta_description"), short=ent.i18n_of(r, "short_description"),
                long=ent.i18n_of(r, "description"), keywords=ent.i18n_of(r, "meta_keywords"),
                og=r.get("og_image"),
                cover=(res["imgs"][0]["url"] if res["imgs"] else None),
                cover_alt=((res["imgs"][0].get("url_alt_i18n") or ({"fa": res["imgs"][0]["alt"]} if res["imgs"][0].get("alt") else None)) if res["imgs"] else None),
                noindex=r.get("noindex"),
            ),
            "created_at": ctx.iso_local(r.get("created_at")),
            "published_at": ctx.iso(r.get("published_at")),
        })
        return detail

    # ------------------------------------------------------------------ providers
    async def search(self, ctx, nq: str, limit: int, lang: str):
        f = Filters()
        f.q = nq
        where, params = f.where()
        order, oparams = order_by("featured", lang, f)
        total_row, rows = await asyncio.gather(
            ctx.db.fetch(f"SELECT COUNT(*) AS c FROM products p WHERE {where}", tuple(params), one=True),
            ctx.db.fetch(f"SELECT p.* FROM products p WHERE {where} ORDER BY {order} LIMIT %s", (*params, *oparams, limit)),
        )
        return await self.cards(ctx, rows), total_row["c"]

    async def home(self, ctx, limit: int):
        limit = limit or 4
        rows = await ctx.db.fetch(
            f"SELECT p.* FROM products p WHERE {published_sql('p')} AND {VISIBLE} AND p.is_featured=1 "
            f"ORDER BY p.is_featured DESC, p.model_code ASC, p.id ASC LIMIT %s", (limit,))
        if len(rows) < limit:
            have = [r["id"] for r in rows] or [0]
            more = await ctx.db.fetch(
                f"SELECT p.* FROM products p WHERE {published_sql('p')} AND {VISIBLE} AND p.id NOT IN ({_ph(len(have))}) "
                f"ORDER BY p.published_at DESC, p.id DESC LIMIT %s", (*have, limit - len(rows)))
            rows = rows + more
        return await self.cards(ctx, rows)

    async def sitemap(self, ctx):
        rows = await ctx.db.fetch(
            f"SELECT p.id, p.slug, p.updated_at, p.created_at FROM products p WHERE {published_sql('p')} AND {VISIBLE} "
            f"AND (p.noindex IS NULL OR p.noindex=0) ORDER BY p.id"
        )
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        imgs = await ctx.db.fetch(
            f"SELECT product_id, url FROM product_images WHERE product_id IN ({_ph(len(ids))}) ORDER BY product_id, sort_order, id",
            tuple(ids))
        by = {}
        for im in imgs:
            u = ctx.url(im["url"])
            if u:
                by.setdefault(im["product_id"], []).append(u)
        return [
            {"slug": r["slug"], "updated_at": ctx.iso(r["updated_at"]) or ctx.iso_local(r["created_at"]),
             "images": by.get(r["id"], [])}
            for r in rows
        ]
