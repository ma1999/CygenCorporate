"""public_api plugin — cross-cutting public endpoints.

- ``GET /api/public/health``      liveness + DB check (never cached)
- ``GET /api/public/redirects``   old slug -> current slug (301 support)
- ``GET /api/public/home``        aggregated home page payload
- ``GET /api/public/sitemap``     all published slugs (noindex excluded)
- ``GET /api/public/search``      unified search over registered providers
- admin ``/admin/revalidate``     webhook status + "clear frontend cache"

Content plugins register providers in ``app.public_providers`` (``search``,
``sitemap``, ``home``); this plugin only aggregates them, so a disabled
plugin simply drops out of the results.
"""
from __future__ import annotations

import os

from flask import Blueprint, request

from app.core import content as C
from app.core import migrate
from app.core.base_plugin import BasePlugin
from app.core.admin_api import api_route, page_route, reply
from app.core.public import (
    ApiError, arg_int, arg_str, bad_request, json_response, dumps, not_found, public_blueprint, public_get,
)

SEARCH_TYPES = ("products", "projects", "articles", "pages")
SLUG_TYPES = {  # entity_type -> table (for /redirects)
    "product": "products", "category": "categories", "brand": "brands", "project": "projects",
    "article": "articles",
}


def _version() -> str:
    v = os.getenv("APP_VERSION") or os.getenv("GIT_SHA")
    if v:
        return v
    try:
        import subprocess

        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, timeout=2)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return "dev"


class Plugin(BasePlugin):
    name = "public_api"
    auto_enable = True
    admin_entry = {"title": "اتصال به فرانت", "icon": "🔌", "url": "/admin/revalidate", "order": 6}
    output_type = "json"

    def maybe_run_migration(self):
        migrate.run(self.db, lambda cur: migrate.ensure_index(cur, "slug_history", "idx_slug_lookup", "entity_type, old_slug"))

    # ------------------------------------------------------------------ routes
    def register(self):
        pub = public_blueprint("public_core")
        self._version = _version()

        @pub.route("/health", methods=["GET"])
        async def health():
            from flask import current_app

            try:
                await current_app.core.db.fetch("SELECT 1 AS ok", one=True)
            except Exception:
                return json_response(dumps({"ok": False, "db": False}), 503)
            return json_response(dumps({"ok": True, "db": True, "version": self._version, "time": C.iso(C.utcnow())}))

        @public_get(pub, "/redirects", params=("type", "slug"))
        async def redirects(ctx):
            etype = arg_str("type", 40)
            slug = arg_str("slug", 191)
            table = SLUG_TYPES.get(etype)
            if not table or not slug:
                raise bad_request("'type' (product|category|brand|project|article) and 'slug' are required")
            hist = await ctx.db.fetch(
                "SELECT entity_id FROM slug_history WHERE entity_type=%s AND old_slug=%s ORDER BY id DESC LIMIT 1",
                (etype, slug), one=True,
            )
            if not hist:
                raise not_found("No redirect for this slug")
            row = await ctx.db.fetch(f"SELECT slug FROM `{table}` WHERE id=%s", (hist["entity_id"],), one=True)
            if not row or not row["slug"] or row["slug"] == slug:
                raise not_found("No redirect for this slug")
            return {"redirect_to": row["slug"]}

        @public_get(pub, "/home", params=("featured_products", "projects", "articles"))
        async def home(ctx):
            n_prod = arg_int("featured_products", 4, 1, 12)
            n_proj = arg_int("projects", 3, 1, 12)
            n_art = arg_int("articles", 3, 1, 12)
            providers = self.app.public_providers["home"]
            out = {"featured_products": [], "categories": [], "featured_projects": [], "latest_articles": [],
                   "stats": [], "industries": [], "certifications": [], "testimonials": [], "offices": []}
            limits = {"featured_products": n_prod, "featured_projects": n_proj, "latest_articles": n_art}
            for key, fn in providers.items():
                out[key] = await fn(ctx, limits.get(key))
            return out

        @public_get(pub, "/sitemap")
        async def sitemap(ctx):
            sp = self.app.public_providers["sitemap"]
            site_url, updated = await self._site_info(ctx)
            out = {"site_url": site_url, "pages": [], "categories": [], "products": [], "projects": [], "articles": [], "services": []}
            out["pages"] = [{"path": "/", "updated_at": updated}] + [
                {"path": f"/{p}", "updated_at": updated} for p in ("about", "products", "services", "projects", "news", "faq", "contact")
            ]
            for key, fn in sp.items():
                out[key] = await fn(ctx)
            return out

        @public_get(pub, "/search", params=("q", "limit", "types", "lang"))
        async def search(ctx):
            q = arg_str("q", 120)
            limit = arg_int("limit", 20, 1, 50)
            raw_types = arg_str("types", 100)
            types = [t.strip() for t in raw_types.split(",") if t.strip()] if raw_types else list(SEARCH_TYPES)
            bad = [t for t in types if t not in SEARCH_TYPES]
            if bad:
                raise bad_request(f"Invalid types: {', '.join(bad)}. Allowed: {', '.join(SEARCH_TYPES)}")
            nq = C.normalize_search(q)
            out = {"query": q, "totals": {t: 0 for t in SEARCH_TYPES}, "products": [], "projects": [], "articles": [], "pages": []}
            out["totals"]["all"] = 0
            if len(nq) < 2:
                return out
            lang = (request.args.get("lang") or "fa").strip().lower()[:8] or "fa"
            for t in types:
                fn = self.app.public_providers["search"].get(t)
                if not fn:
                    continue
                items, total = await fn(ctx, nq, limit, lang)
                out[t] = items
                out["totals"][t] = total
            out["totals"]["all"] = sum(out["totals"][t] for t in SEARCH_TYPES)
            return out

        self.app.register_blueprint(pub)

        # ---- admin: revalidate status ----
        bp = Blueprint("plugin_public_api", __name__)

        page_route(bp, "/admin/revalidate", "admin_revalidate", "revalidate", "اتصال به فرانت", "pages-system")

        @api_route(bp, "/api/admin/revalidate", "api_revalidate")
        async def api_revalidate():
            import json
            from urllib.parse import urlparse

            rv = self.app.revalidate
            url, secret = rv.config()
            last = rv.last
            if last is None:
                row = await self.db.query("SELECT `value` FROM settings WHERE `key`='revalidate_last'", one=True)
                try:
                    last = json.loads(row["value"]) if row else None
                except Exception:
                    last = None
            return reply({
                "enabled": rv.enabled, "has_url": bool(url), "has_secret": bool(secret),
                "host": urlparse(url).netloc if url else "", "last": last,
                "cors": [o for o in (os.getenv("CORS_ALLOWED_ORIGINS", "") or "").split(",") if o.strip()],
                "base_url": os.getenv("PUBLIC_BASE_URL", "") or "(از درخواست جاری)",
            })

        @api_route(bp, "/api/admin/revalidate/flush", "api_revalidate_flush", ["POST"])
        async def api_revalidate_flush():
            rv = self.app.revalidate
            if not rv.enabled:
                self.app.cache.invalidate_namespace("public_api")
                return reply({"flushed": "api_cache", "frontend": False,
                              "message": "کش API پاک شد؛ اما اتصال به فرانت (FRONTEND_REVALIDATE_URL / SECRET) تنظیم نشده است"})
            rv.notify("*")
            return reply({"flushed": "all", "frontend": True, "message": "درخواست پاک‌کردن کش فرانت (تگ *) در صف ارسال قرار گرفت"})

        self.app.register_blueprint(bp)

    async def _site_info(self, ctx):
        row = await ctx.db.fetch("SELECT skey, value FROM site_settings WHERE skey IN ('site_url','_updated')")
        d = {r["skey"]: r["value"] for r in row}
        return (d.get("site_url") or None), (d.get("_updated") or C.iso(C.utcnow()))
