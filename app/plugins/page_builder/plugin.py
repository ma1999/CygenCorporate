"""page_builder plugin — Elementor-style pages whose layout lives in the database.

The Next.js frontend only knows how to render widget *types*; the order of sections/columns/widgets and every
setting is data stored here, so replacing or re-deploying the frontend never loses a page. Each frontend theme
sends a *manifest* (widget catalog + system pages + factory-default layouts) that this plugin stores per theme;
the admin editor builds its settings forms from that manifest, so a new theme needs no backend change.

Public (``/api/public``):  ``GET /pages?theme=`` · ``GET /pages/<slug>?theme=[&preview=<token>]`` ·
``PUT /themes/<theme>/manifest`` (shared-secret guarded, used by the frontend's sync script).
Admin (``/api/admin/page-builder``): themes, page CRUD, draft save, publish/unpublish/reset, revisions,
preview URL, export/import.  Panel: ``/admin/page-builder``.  Docs: ``docs/features/page-builder.md``.
"""
from __future__ import annotations

import hmac
import json
import os
from urllib.parse import urlparse

from flask import Blueprint, request

from app.core import content as C
from app.core import migrate
from app.core.admin_api import api_route, body, invalid, page_route, reply
from app.core.base_plugin import BasePlugin
from app.core.entity import get_langs
from app.core.public import (
    ApiError, RateLimiter, arg_str, bad_request, client_ip, dumps, json_body, make_preview_token, not_found,
    preview_target, public_blueprint, public_get,
)

from . import layout as L

REVISIONS_KEPT = 30
MANIFEST_LIMIT = RateLimiter()


def _j(data) -> str:
    return dumps(data).decode("utf-8")


def _loads(raw, default=None):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


# a page is live when published, or scheduled and its time has come (no cron: evaluated on every read)
LIVE_SQL = "(status='published' OR (status='scheduled' AND publish_at IS NOT NULL AND publish_at<=UTC_TIMESTAMP()))"
ROLES = ("page", "area", "template")
OPTION_KEYS = ("hide_header", "hide_footer")


def _parse_when(value):
    """ISO-8601 string -> naive UTC datetime (None when empty/invalid)."""
    import datetime as dt

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        d = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(dt.timezone.utc).replace(tzinfo=None) if d.tzinfo else d


class Plugin(BasePlugin):
    name = "page_builder"
    auto_enable = True
    admin_entry = {"title": "صفحه‌ساز", "icon": "🧱", "url": "/admin/page-builder", "order": 3}
    output_type = "json"

    # ------------------------------------------------------------------ schema
    def declare_schema(self, schema):
        schema.register_table("page_themes", {
            "theme": "VARCHAR(64) PRIMARY KEY", "name": "VARCHAR(191)", "version": "VARCHAR(40)",
            "manifest_json": "LONGTEXT", "synced_at": "DATETIME NULL",
        })
        schema.register_table("site_pages", {
            "id": "INT AUTO_INCREMENT PRIMARY KEY", "theme": "VARCHAR(64) NOT NULL", "slug": "VARCHAR(191) NOT NULL",
            "path": "VARCHAR(191) NULL", "kind": "VARCHAR(10) NOT NULL DEFAULT 'custom'",
            "title_i18n": "TEXT", "seo_json": "TEXT", "draft_json": "LONGTEXT", "published_json": "LONGTEXT",
            "status": "VARCHAR(12) NOT NULL DEFAULT 'draft'", "revision": "INT NOT NULL DEFAULT 0",
            "published_at": "DATETIME NULL", "created_at": "DATETIME NULL", "updated_at": "DATETIME NULL",
            "role": "VARCHAR(12) NOT NULL DEFAULT 'page'",      # page | area (header/footer) | template (detail page of an entity)
            "publish_at": "DATETIME NULL",                      # scheduled publishing (status 'scheduled')
            "options_json": "TEXT",                             # per-page switches: hide_header, hide_footer
        })
        schema.register_table("page_templates", {
            "id": "INT AUTO_INCREMENT PRIMARY KEY", "theme": "VARCHAR(64) NOT NULL", "name": "VARCHAR(191) NOT NULL",
            "layout_json": "LONGTEXT", "created_at": "DATETIME NULL",
        })
        schema.register_table("site_page_revisions", {
            "id": "INT AUTO_INCREMENT PRIMARY KEY", "page_id": "INT NOT NULL", "layout_json": "LONGTEXT",
            "note": "VARCHAR(191) NULL", "created_at": "DATETIME NULL",
        })

    def maybe_run_migration(self):
        def go(cur):
            migrate.ensure_index(cur, "site_pages", "uq_site_pages_theme_slug", "theme, slug", unique=True)
            migrate.ensure_index(cur, "site_pages", "idx_site_pages_status", "theme, status")
            migrate.ensure_index(cur, "site_page_revisions", "idx_page_rev", "page_id, id")
            migrate.ensure_index(cur, "page_templates", "idx_page_tpl_theme", "theme")

        migrate.run(self.db, go)

    # ------------------------------------------------------------------ data helpers
    async def langs(self) -> list:
        return [l["code"] for l in await get_langs(self.db)]

    async def load_manifest(self, theme):
        row = await self.db.fetch("SELECT manifest_json FROM page_themes WHERE theme=%s", (theme,), one=True)
        return _loads(row["manifest_json"]) if row else None

    async def sync_manifest(self, manifest: dict):
        """Store a validated manifest and make sure every system page of the theme has a row (draft = factory layout)."""
        langs = await self.langs()
        theme = manifest["theme"]
        rows = []
        for p in manifest["pages"]:
            try:
                lay, _errs, _unk = L.validate_layout(p.get("layout") or L.empty_layout(), manifest, langs)
            except L.LayoutError:
                lay = L.empty_layout()
            title = p["label"] if isinstance(p["label"], dict) else {"fa": p["label"]}
            rows.append((p["key"], p["path"], _j(title), _j(lay), p.get("role", "page")))

        def go(tx):
            tx.run(
                "INSERT INTO page_themes (theme, name, version, manifest_json, synced_at) VALUES (%s,%s,%s,%s,UTC_TIMESTAMP()) "
                "ON DUPLICATE KEY UPDATE name=VALUES(name), version=VALUES(version), manifest_json=VALUES(manifest_json), "
                "synced_at=UTC_TIMESTAMP()",
                (theme, manifest["name"] if isinstance(manifest["name"], str) else (manifest["name"].get("fa") or theme),
                 manifest["version"], _j(manifest)),
            )
            for key, path, title, lay, role in rows:
                have = tx.one("SELECT id FROM site_pages WHERE theme=%s AND slug=%s", (theme, key))
                if have:
                    tx.run("UPDATE site_pages SET path=%s, kind='system', role=%s WHERE id=%s", (path, role, have["id"]))
                else:
                    tx.run(
                        "INSERT INTO site_pages (theme, slug, path, kind, role, title_i18n, seo_json, draft_json, status, revision, "
                        "created_at, updated_at) VALUES (%s,%s,%s,'system',%s,%s,%s,%s,'draft',0,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                        (theme, key, path, role, title, _j({}), lay),
                    )

        await self.db.transaction(go)
        self.app.revalidate.notify("pages", "sitemap")

    def _notify(self, *slugs):
        self.app.revalidate.notify("pages", "sitemap", *[f"page:{s}" for s in slugs if s])

    async def get_row(self, pid):
        row = await self.db.fetch("SELECT * FROM site_pages WHERE id=%s", (pid,), one=True)
        if not row:
            raise not_found("Page not found")
        return row

    @staticmethod
    def page_out(row, full=False) -> dict:
        draft, pub = row.get("draft_json") or "", row.get("published_json") or ""
        live = row["status"] in ("published", "scheduled")
        out = {
            "id": row["id"], "theme": row["theme"], "slug": row["slug"], "path": row.get("path") or "/" + row["slug"],
            "kind": row["kind"], "role": row.get("role") or "page", "title": _loads(row.get("title_i18n"), {}),
            "status": row["status"], "publish_at": row.get("publish_at"),
            "revision": row["revision"], "published_at": row.get("published_at"), "updated_at": row.get("updated_at"),
            "has_changes": live and draft != pub,
        }
        if full:
            out["options"] = _loads(row.get("options_json"), {}) or {}
            out["seo"] = _loads(row.get("seo_json"), {})
            out["layout"] = _loads(draft, L.empty_layout())
        return out

    async def frontend_origin(self) -> str:
        explicit = (os.getenv("FRONTEND_PREVIEW_URL") or "").strip().rstrip("/")
        if explicit:
            return explicit
        rv = (os.getenv("FRONTEND_REVALIDATE_URL") or "").strip()
        if rv:
            u = urlparse(rv)
            if u.scheme and u.netloc:
                return f"{u.scheme}://{u.netloc}"
        row = await self.db.fetch("SELECT value FROM site_settings WHERE skey='site_url'", one=True)
        v = (row or {}).get("value") or ""
        v = _loads(v, v) if v.startswith('"') else v
        return str(v).strip().rstrip("/")

    # ------------------------------------------------------------------ routes
    def register(self):
        self._register_admin()
        self._register_public()

    def _register_public(self):
        pub = public_blueprint("public_pages")

        def theme_arg() -> str:
            theme = arg_str("theme", 64)
            if not L.THEME_RE.match(theme):
                raise bad_request("'theme' is required")
            return theme

        @public_get(pub, "/pages", params=("theme",))
        async def pages_list(ctx):
            theme = theme_arg()
            rows = await ctx.db.fetch(
                "SELECT slug, path, kind, role, title_i18n, seo_json, updated_at FROM site_pages "
                f"WHERE theme=%s AND {LIVE_SQL} ORDER BY slug", (theme,),
            )
            return {"pages": [{
                "slug": r["slug"], "path": r.get("path") or "/" + r["slug"], "kind": r["kind"], "role": r.get("role") or "page",
                "title": ctx.text(r.get("title_i18n") or "{}"),
                "noindex": bool((_loads(r.get("seo_json"), {}) or {}).get("noindex")),
                "updated_at": ctx.iso(r["updated_at"]),
            } for r in rows]}

        @public_get(pub, "/pages/<path:slug>", params=("theme",))
        async def page_detail(ctx, slug):
            theme = theme_arg()
            row = await ctx.db.fetch(f"SELECT *, {LIVE_SQL} AS live FROM site_pages WHERE theme=%s AND slug=%s", (theme, slug), one=True)
            pid = preview_target("page")
            if not row:
                raise not_found("Page not found")
            if pid is not None:
                if row["id"] != pid:
                    raise not_found("Page not found")
                raw = row.get("draft_json")
            else:
                if not row["live"]:
                    raise not_found("Page not found")
                raw = row.get("published_json")
            seo = _loads(row.get("seo_json"), {}) or {}
            return {"page": {
                "slug": row["slug"], "path": row.get("path") or "/" + row["slug"], "kind": row["kind"],
                "role": row.get("role") or "page", "options": _loads(row.get("options_json"), {}) or {},
                "title": ctx.text(row.get("title_i18n") or "{}"),
                "seo": {
                    "title": ctx.text(_j(seo.get("title") or {})), "description": ctx.text(_j(seo.get("description") or {})),
                    "og_image": ctx.media(seo.get("og_image") or "", None), "noindex": bool(seo.get("noindex")),
                },
                "layout": _loads(raw, L.empty_layout()), "revision": row["revision"],
                "updated_at": ctx.iso(row["updated_at"]), "preview": pid is not None,
            }}

        @pub.route("/themes/<theme>/manifest", methods=["PUT"])
        async def put_manifest(theme):
            """Frontend -> backend: publish a theme's widget catalog. Guarded by the shared revalidate secret."""
            secret = (os.getenv("FRONTEND_REVALIDATE_SECRET") or "").strip()
            if not secret:
                raise ApiError(503, "unavailable", "FRONTEND_REVALIDATE_SECRET is not configured on the backend")
            wait = MANIFEST_LIMIT.check(f"manifest:{client_ip()}", [(30, 60)])
            if wait:
                raise ApiError(429, "rate_limited", "Too many requests", headers={"Retry-After": str(wait)})
            sent = request.headers.get("X-Revalidate-Secret", "")
            if not sent or not hmac.compare_digest(sent.encode(), secret.encode()):
                raise ApiError(401, "unauthorized", "Invalid secret")
            data = json_body(L.MAX_MANIFEST_BYTES)
            manifest, errors = L.normalize_manifest(data)
            if manifest is None:
                raise ApiError(422, "validation_failed", "Invalid manifest", fields=errors)
            if manifest["theme"] != theme:
                raise ApiError(422, "validation_failed", "Theme in URL and manifest differ", fields={"theme": "mismatch"})
            await self.sync_manifest(manifest)
            return json_response_ok({"theme": theme, "widgets": len(manifest["widgets"]), "pages": len(manifest["pages"]),
                                     "warnings": errors})

        self.app.register_blueprint(pub)

    def _register_admin(self):
        bp = Blueprint("plugin_page_builder", __name__)
        A = "/api/admin/page-builder"

        page_route(bp, "/admin/page-builder", "admin_page_builder", "page_builder", "صفحه‌ساز", "pages-builder")
        page_route(bp, "/admin/page-builder/edit/<int:pid>", "admin_page_builder_edit", "page_builder_edit", "ویرایش صفحه",
                   "pages-builder")

        @api_route(bp, A + "/themes", "pb_api_themes")
        async def themes():
            rows = await self.db.fetch("SELECT theme, name, version, synced_at, manifest_json FROM page_themes ORDER BY theme")
            out = []
            for r in rows:
                m = _loads(r["manifest_json"], {}) or {}
                out.append({"theme": r["theme"], "name": r["name"], "version": r["version"], "synced_at": r["synced_at"],
                            "widgets": len(m.get("widgets", [])), "pages": m.get("pages", [])})
            return reply({"themes": out, "frontend_origin": await self.frontend_origin()})

        @api_route(bp, A + "/themes/<theme>", "pb_api_theme")
        async def theme(theme):
            m = await self.load_manifest(theme)
            if not m:
                raise not_found("Theme not found")
            return reply({"manifest": m, "languages": await get_langs(self.db), "common_fields": L.COMMON_FIELDS,
                          "inner_row": L.INNER_ROW})

        @api_route(bp, A + "/pages", "pb_api_pages", ["GET", "POST"])
        async def pages():
            if request.method == "GET":
                th = arg_str("theme", 64)
                rows = await self.db.fetch(
                    "SELECT id, theme, slug, path, kind, role, title_i18n, status, publish_at, revision, published_at, updated_at, draft_json, "
                    "published_json FROM site_pages WHERE theme=%s ORDER BY FIELD(role,'page','area','template'), kind DESC, slug", (th,))
                return reply([self.page_out(r) for r in rows])
            data = body()
            th = data.get("theme") if isinstance(data.get("theme"), str) else ""
            if not await self.load_manifest(th):
                raise invalid({"theme": "قالب ناشناخته"})
            langs = await self.langs()
            errors = {}
            try:
                slug = L.check_slug(data.get("slug"))
            except L.LayoutError as e:
                slug = ""
                errors["slug"] = str(e)
            title = L._i18n(data.get("title"), langs, 200)
            if not title.get("fa"):
                errors["title"] = "عنوان فارسی الزامی است"
            if errors:
                raise invalid(errors)
            if await self.db.fetch("SELECT id FROM site_pages WHERE theme=%s AND slug=%s", (th, slug), one=True):
                raise ApiError(409, "conflict", "این نشانی قبلاً استفاده شده است", fields={"slug": "تکراری است"})
            pid = await self.db.transaction(lambda tx: tx.run(
                "INSERT INTO site_pages (theme, slug, path, kind, title_i18n, seo_json, draft_json, status, revision, created_at, "
                "updated_at) VALUES (%s,%s,%s,'custom',%s,%s,%s,'draft',0,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                (th, slug, "/" + slug, _j(title), _j({}), _j(L.empty_layout()))))
            return reply(self.page_out(await self.get_row(pid), full=True), 201)

        @api_route(bp, A + "/pages/<int:pid>", "pb_api_page", ["GET", "PUT", "DELETE"])
        async def page(pid):
            row = await self.get_row(pid)
            if request.method == "GET":
                return reply(self.page_out(row, full=True))
            if request.method == "DELETE":
                if row["kind"] == "system":
                    raise ApiError(409, "conflict", "صفحه‌های سیستمی حذف نمی‌شوند؛ می‌توانید آن را «بازنشانی» کنید")
                await self.db.transaction(lambda tx: (
                    tx.run("DELETE FROM site_page_revisions WHERE page_id=%s", (pid,)),
                    tx.run("DELETE FROM site_pages WHERE id=%s", (pid,))))
                self._notify(row["slug"])
                return reply({"deleted": pid})
            data = body()
            langs = await self.langs()
            manifest = await self.load_manifest(row["theme"]) or {}
            sets, params, errors = [], [], {}
            new_slug = row["slug"]
            if "layout" in data:
                try:
                    lay, lerrs, unknown = L.validate_layout(data["layout"], manifest, langs)
                    sets.append("draft_json=%s")
                    params.append(_j(lay))
                except L.LayoutError as e:
                    errors["layout"] = str(e)
                    lerrs, unknown = {}, []
            else:
                lerrs, unknown = {}, []
            if "title" in data:
                title = L._i18n(data["title"], langs, 200)
                if not title.get("fa"):
                    errors["title"] = "عنوان فارسی الزامی است"
                sets.append("title_i18n=%s")
                params.append(_j(title))
            if "seo" in data:
                sets.append("seo_json=%s")
                params.append(_j(L.seo_clean(data["seo"], langs)))
            if "options" in data:
                opts = data["options"] if isinstance(data["options"], dict) else {}
                sets.append("options_json=%s")
                params.append(_j({k: bool(opts.get(k)) for k in OPTION_KEYS if opts.get(k)}))
            if "slug" in data and row["kind"] == "custom":
                try:
                    new_slug = L.check_slug(data["slug"])
                except L.LayoutError as e:
                    errors["slug"] = str(e)
                if new_slug != row["slug"] and not errors.get("slug"):
                    if await self.db.fetch("SELECT id FROM site_pages WHERE theme=%s AND slug=%s", (row["theme"], new_slug), one=True):
                        errors["slug"] = "این نشانی قبلاً استفاده شده است"
                    sets += ["slug=%s", "path=%s"]
                    params += [new_slug, "/" + new_slug]
            if errors:
                raise invalid(errors)
            if sets:
                await self.db.transaction(lambda tx: tx.run(
                    f"UPDATE site_pages SET {', '.join(sets)}, updated_at=UTC_TIMESTAMP() WHERE id=%s", (*params, pid)))
                if row["status"] in ("published", "scheduled") and (
                        new_slug != row["slug"] or "title" in data or "seo" in data or "options" in data):
                    self._notify(row["slug"], new_slug)   # a draft-only layout edit changes nothing public
            out = self.page_out(await self.get_row(pid), full=True)
            out["unknown_widgets"] = unknown
            out["warnings"] = lerrs
            return reply(out)

        @api_route(bp, A + "/pages/<int:pid>/publish", "pb_api_publish", ["POST"])
        async def publish(pid):
            row = await self.get_row(pid)
            import datetime as _dt

            when = _parse_when((request.get_json(silent=True) or {}).get("publish_at"))
            scheduled = when is not None and when > _dt.datetime.utcnow() + _dt.timedelta(seconds=30)
            if row["role"] != "page" and scheduled:
                raise invalid({"publish_at": "برای هدر/فوتر و قالب‌ها زمان‌بندی پشتیبانی نمی‌شود"})

            def go(tx):
                cur = tx.one("SELECT draft_json FROM site_pages WHERE id=%s", (pid,))
                tx.run("UPDATE site_pages SET published_json=draft_json, status=%s, publish_at=%s, revision=revision+1, "
                       "published_at=IF(%s, %s, UTC_TIMESTAMP()), updated_at=UTC_TIMESTAMP() WHERE id=%s",
                       ("scheduled" if scheduled else "published", when if scheduled else None, scheduled, when, pid))
                tx.run("INSERT INTO site_page_revisions (page_id, layout_json, note, created_at) VALUES (%s,%s,%s,UTC_TIMESTAMP())",
                       (pid, cur["draft_json"], "schedule" if scheduled else "publish"))
                tx.run("DELETE FROM site_page_revisions WHERE page_id=%s AND id NOT IN "
                       "(SELECT id FROM (SELECT id FROM site_page_revisions WHERE page_id=%s ORDER BY id DESC LIMIT %s) t)",
                       (pid, pid, REVISIONS_KEPT))

            await self.db.transaction(go)
            self._notify(row["slug"])
            return reply(self.page_out(await self.get_row(pid), full=True))

        @api_route(bp, A + "/pages/<int:pid>/unpublish", "pb_api_unpublish", ["POST"])
        async def unpublish(pid):
            row = await self.get_row(pid)
            await self.db.execute("UPDATE site_pages SET status='draft', publish_at=NULL, updated_at=UTC_TIMESTAMP() WHERE id=%s", (pid,))
            self._notify(row["slug"])
            return reply(self.page_out(await self.get_row(pid), full=True))

        @api_route(bp, A + "/pages/<int:pid>/reset", "pb_api_reset", ["POST"])
        async def reset(pid):
            """System pages: copy the theme's factory-default layout back into the draft."""
            row = await self.get_row(pid)
            manifest = await self.load_manifest(row["theme"]) or {}
            entry = next((p for p in manifest.get("pages", []) if p["key"] == row["slug"]), None)
            if row["kind"] != "system" or not entry or not entry.get("layout"):
                raise ApiError(409, "conflict", "برای این صفحه طرح پیش‌فرضی تعریف نشده است")
            lay, _e, _u = L.validate_layout(entry["layout"], manifest, await self.langs())
            await self.db.execute("UPDATE site_pages SET draft_json=%s, updated_at=UTC_TIMESTAMP() WHERE id=%s", (_j(lay), pid))
            return reply(self.page_out(await self.get_row(pid), full=True))

        @api_route(bp, A + "/pages/<int:pid>/revisions", "pb_api_revisions", ["GET"])
        async def revisions(pid):
            await self.get_row(pid)
            rows = await self.db.fetch(
                "SELECT id, note, created_at FROM site_page_revisions WHERE page_id=%s ORDER BY id DESC LIMIT %s", (pid, REVISIONS_KEPT))
            return reply(rows)

        @api_route(bp, A + "/pages/<int:pid>/restore", "pb_api_restore", ["POST"])
        async def restore(pid):
            await self.get_row(pid)
            rid = body().get("revision_id")
            rev = await self.db.fetch("SELECT layout_json FROM site_page_revisions WHERE id=%s AND page_id=%s",
                                      (rid if isinstance(rid, int) else 0, pid), one=True)
            if not rev:
                raise not_found("Revision not found")
            await self.db.execute("UPDATE site_pages SET draft_json=%s, updated_at=UTC_TIMESTAMP() WHERE id=%s",
                                  (rev["layout_json"], pid))
            return reply(self.page_out(await self.get_row(pid), full=True))

        @api_route(bp, A + "/pages/<int:pid>/preview-url", "pb_api_preview_url", ["POST"])
        async def preview_url(pid):
            row = await self.get_row(pid)
            origin = await self.frontend_origin()
            if not origin:
                raise ApiError(409, "conflict", "آدرس فرانت تنظیم نشده است (FRONTEND_PREVIEW_URL یا FRONTEND_REVALIDATE_URL)")
            token = make_preview_token("page", pid)
            path = row.get("path") or "/" + row["slug"]
            if "{slug}" in path:        # detail-page template: needs a real entity to render
                sample = (request.get_json(silent=True) or {}).get("sample")
                if not isinstance(sample, str) or not sample.strip():
                    raise ApiError(409, "conflict", "برای پیش‌نمایش این قالب یک نمونه انتخاب کنید", fields={"sample": "required"})
                from urllib.parse import quote

                path = path.replace("{slug}", quote(sample.strip(), safe=""))
            return reply({"url": f"{origin}{path}?pb={token}&builder=1", "origin": origin})

        @api_route(bp, A + "/templates", "pb_api_templates", ["GET", "POST"])
        async def templates():
            if request.method == "GET":
                rows = await self.db.fetch("SELECT id, name, created_at FROM page_templates WHERE theme=%s ORDER BY id DESC",
                                           (arg_str("theme", 64),))
                return reply(rows)
            data = body()
            th = data.get("theme") if isinstance(data.get("theme"), str) else ""
            manifest = await self.load_manifest(th)
            if not manifest:
                raise invalid({"theme": "قالب ناشناخته"})
            name = C.strip_tags(str(data.get("name") or "")).strip()[:191]
            if not name:
                raise invalid({"name": "نام الزامی است"})
            try:
                lay, _e, _u = L.validate_layout({"sections": [data.get("section")]}, manifest, await self.langs())
            except L.LayoutError as e:
                raise invalid({"section": str(e)})
            if len(lay["sections"]) != 1:
                raise invalid({"section": "بخش معتبر نیست"})
            tid = await self.db.transaction(lambda tx: tx.run(
                "INSERT INTO page_templates (theme, name, layout_json, created_at) VALUES (%s,%s,%s,UTC_TIMESTAMP())",
                (th, name, _j(lay["sections"][0]))))
            return reply({"id": tid, "name": name}, 201)

        @api_route(bp, A + "/templates/<int:tid>", "pb_api_template", ["GET", "DELETE"])
        async def template(tid):
            row = await self.db.fetch("SELECT id, name, layout_json FROM page_templates WHERE id=%s", (tid,), one=True)
            if not row:
                raise not_found("Template not found")
            if request.method == "DELETE":
                await self.db.execute("DELETE FROM page_templates WHERE id=%s", (tid,))
                return reply({"deleted": tid})
            return reply({"id": row["id"], "name": row["name"], "section": _loads(row["layout_json"], {})})

        @api_route(bp, A + "/pages/<int:pid>/export", "pb_api_export", ["GET"])
        async def export(pid):
            row = await self.get_row(pid)
            out = self.page_out(row, full=True)
            return reply({"v": 1, "kind": "page", "theme": row["theme"], "slug": row["slug"], "title": out["title"],
                          "seo": out["seo"], "layout": out["layout"]})

        @api_route(bp, A + "/pages/import", "pb_api_import", ["POST"])
        async def import_page():
            data = body()
            if data.get("kind") != "page" or not isinstance(data.get("layout"), dict):
                raise invalid({"_": "فایل صفحهٔ معتبر نیست"})
            th = data.get("theme") if isinstance(data.get("theme"), str) else ""
            manifest = await self.load_manifest(th)
            if not manifest:
                raise invalid({"theme": "قالب این صفحه روی این سرور همگام‌سازی نشده است"})
            langs = await self.langs()
            try:
                slug = L.check_slug(data.get("slug"))
                lay, _e, _u = L.validate_layout(data["layout"], manifest, langs)
            except L.LayoutError as e:
                raise invalid({"_": str(e)})
            if await self.db.fetch("SELECT id FROM site_pages WHERE theme=%s AND slug=%s", (th, slug), one=True):
                raise ApiError(409, "conflict", "صفحه‌ای با این نشانی وجود دارد", fields={"slug": "تکراری است"})
            title = L._i18n(data.get("title"), langs, 200) or {"fa": slug}
            pid = await self.db.transaction(lambda tx: tx.run(
                "INSERT INTO site_pages (theme, slug, path, kind, title_i18n, seo_json, draft_json, status, revision, created_at, "
                "updated_at) VALUES (%s,%s,%s,'custom',%s,%s,%s,'draft',0,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                (th, slug, "/" + slug, _j(title), _j(L.seo_clean(data.get("seo"), langs)), _j(lay))))
            return reply(self.page_out(await self.get_row(pid), full=True), 201)

        self.app.register_blueprint(bp)


def json_response_ok(data: dict):
    from app.core.public import json_response

    return json_response(dumps({"ok": True, **data}))
