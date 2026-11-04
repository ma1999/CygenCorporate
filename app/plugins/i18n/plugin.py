"""i18n plugin — multilingual site.

Responsibilities:
    1. Admin manages a list of languages (code, name, direction, flag, is_default).
    2. A *source* language holds the canonical Persian strings in
       ``app/plugins/i18n/locales/<code>.json`` (read-only at runtime).
       Each subsequent language the admin translates is persisted in
       ``i18n_translations`` table; the file is created on first save and
       cached for read-heavy serving.
    3. URL routing: a language prefix like ``/en/...`` activates that
       language. Without a prefix, the source language (``fa``) is used.
       Language selection is strictly request/URL scoped; it is never stored
       in a process-global variable, cookie, or session.
    4. Plugin exposes a public ``t()`` function (and a Jinja ``_``
       filter) so any plugin or template can render the right string
       without knowing the active language.

The translation flow is:
    - ``t('products.list.title')``  →  looks up the key in the active
      language's translation table; if missing, falls back to the source
      file; if still missing, returns the key verbatim.

The plugin also offers a "translate response" hook: any object with
string fields can be passed to ``translate_payload(obj)`` and every
value matching a known translation key (or any Persian string present
in the source file) is replaced with the active-language equivalent.
This is the "translate from the core before returning to the user"
behaviour the user asked for.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    g,
    current_app,
)
from jinja2 import pass_context

from app.core.base_plugin import BasePlugin
from app.core.admin_api import api_route, body, invalid, page_route, reply
from app.core.public import ApiError
from app.core.entity import safe_next


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLUGIN_DIR = Path(__file__).resolve().parent
LOCALES_DIR = PLUGIN_DIR / "locales"
CACHE_NS = "i18n"
SOURCE_LANG_CODE = "fa"   # canonical Persian source

# Stable list of translation keys exposed to the admin. Plugins can extend
# this list at runtime via :func:`register_keys`. Keys are dotted paths;
# the source language file holds the original Persian text.
DEFAULT_KEYS: list[str] = [
    # core / nav
    "nav.home", "nav.dashboard", "nav.logout", "nav.login",
    "nav.products", "nav.categories", "nav.images", "nav.cache",
    "nav.tracking", "nav.languages",
    # common actions (also referenced as nav.* for layout)
    "action.logout",
    # common buttons / actions
    "action.save", "action.delete", "action.edit", "action.create",
    "action.cancel", "action.search", "action.confirm",
    "action.activate", "action.deactivate", "action.back",
    "action.purge", "action.next", "action.prev", "action.submit",
    # flash messages
    "flash.saved", "flash.deleted", "flash.created", "flash.error",
    "flash.not_found", "flash.unauthorized", "flash.invalid_input",
    # product
    "product.title", "product.price", "product.stock", "product.sku",
    "product.category", "product.status.published", "product.status.draft",
    "product.list.title", "product.list.empty",
    "product.detail.not_found", "product.add",
    # category
    "category.title", "category.list.title", "category.list.empty",
    "category.add", "category.parent", "category.root",
    # settings
    "settings.title", "settings.site_title", "settings.meta_description",
    "settings.meta_keywords", "settings.saved",
    # users
    "users.title", "users.create", "users.delete",
    # tracking
    "tracking.title", "tracking.dashboard", "tracking.visitors",
    # 404
    "error.404.title", "error.404.body",
]


# Translation key aliases: when a key has no direct translation,
# we look up its alias(es) and use that value instead. This avoids
# forcing the admin to translate the same phrase twice (e.g. once for
# the navbar and once for a page heading).
ALIASES: dict[str, str] = {
    "dashboard.title": "nav.dashboard",
    "dashboard.settings": "settings.title",
    "dashboard.users": "users.title",
    "dashboard.roles": "roles.title",
    "dashboard.themes": "themes.title",
    "dashboard.plugins": "plugins.title",
    "dashboard.limited_access": "flash.unauthorized",
    "users.col.username": "login.username",
    "users.col.id": "users.col.id",
    "cache.icon_label": "cache.title",
    "login.submit": "nav.login",
}


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

class Plugin(BasePlugin):
    name = "i18n"
    # enabled by default on a fresh database (the headless frontend needs it);
    # an existing "plugins" row (enabled or not) is never touched
    auto_enable = True

    admin_entry = {
        "title": "چند زبانه",
        "icon": "🌐",
        "url": "/admin/i18n",
        "order": 1,
    }
    output_type = "html"

    CACHE_NS = CACHE_NS

    @property
    def _cache(self):
        return self.app.cache

    # ------------------------------------------------------------------
    # runtime registry of translation keys
    # ------------------------------------------------------------------
    _extra_keys: set[str] = set()

    @classmethod
    def register_keys(cls, keys):
        """Public API: plugins can register their own translation keys."""
        if isinstance(keys, str):
            keys = [keys]
        cls._extra_keys.update(keys)

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------
    def declare_schema(self, schema):
        schema.register_table("i18n_languages", {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "code": "VARCHAR(8) UNIQUE NOT NULL",      # e.g. "en", "ar"
            "name": "VARCHAR(64) NOT NULL",            # e.g. "English"
            "native_name": "VARCHAR(64)",              # e.g. "English"
            "direction": "VARCHAR(3) DEFAULT 'ltr'",   # ltr | rtl
            "flag": "VARCHAR(8)",                      # emoji 🇬🇧 or url
            "is_default": "TINYINT(1) DEFAULT 0",
            "is_active": "TINYINT(1) DEFAULT 1",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        })
        schema.register_table("i18n_translations", {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "lang_code": "VARCHAR(8) NOT NULL",
            "translation_key": "VARCHAR(191) NOT NULL",
            "value": "MEDIUMTEXT",
            "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP "
                          "ON UPDATE CURRENT_TIMESTAMP",
        })

    def maybe_run_migration(self):
        """Post-sync: add the unique index on (lang_code, translation_key)
        to ``i18n_translations`` if it's missing. The schema API only
        accepts column definitions, so the index is added here."""
        import asyncio
        from mysql.connector import connect
        async def go():
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            def add():
                conn = connect(**self.db._config)
                try:
                    cur = conn.cursor()
                    # ensure the source language row exists (idempotent): the
                    # public API always lists fa, even on a fresh database
                    cur.execute("SELECT COUNT(*) FROM i18n_languages WHERE code=%s", (SOURCE_LANG_CODE,))
                    if cur.fetchone()[0] == 0:
                        cur.execute("SELECT COUNT(*) FROM i18n_languages WHERE is_default=1")
                        has_default = cur.fetchone()[0] > 0
                        cur.execute(
                            "INSERT IGNORE INTO i18n_languages "
                            "(code, name, native_name, direction, flag, is_default, is_active) "
                            "VALUES (%s,%s,%s,%s,%s,%s,1)",
                            (SOURCE_LANG_CODE, "Persian", "فارسی", "rtl", "🇮🇷", 0 if has_default else 1),
                        )
                        conn.commit()
                        print("[i18n] created source language row 'fa'")
                    cur.execute(
                        "SELECT COUNT(*) FROM information_schema.statistics "
                        "WHERE table_schema=DATABASE() "
                        "AND table_name='i18n_translations' "
                        "AND index_name='uniq_lang_key'"
                    )
                    exists = cur.fetchone()[0] > 0
                    if not exists:
                        try:
                            cur.execute(
                                "ALTER TABLE i18n_translations "
                                "ADD UNIQUE KEY uniq_lang_key "
                                "(lang_code, translation_key)"
                            )
                            conn.commit()
                            print("[i18n] added unique index on "
                                  "i18n_translations")
                        except Exception as e:
                            print(f"[i18n] unique index add skipped: {e}")
                finally:
                    conn.close()
            if loop is None:
                await asyncio.to_thread(add)
            else:
                await loop.run_in_executor(None, add)
        try:
            asyncio.run(go())
        except Exception as e:
            print(f"[i18n] post-sync migration skipped: {e}")

    # ------------------------------------------------------------------
    # routes + middleware
    # ------------------------------------------------------------------
    def register(self):
        # ensure the locales directory exists with the source file
        LOCALES_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_source_locale()
        self._register_web_keys()

        bp = Blueprint("plugin_i18n", __name__)

        # ---- admin pages (shells) ----
        for rule, ep in (("/admin/i18n", "admin_languages"), ("/admin/i18n/create", "admin_create_lang"),
                         ("/admin/i18n/<code>/edit", "admin_edit_lang"), ("/admin/i18n/<code>/translate", "admin_translate"),
                         ("/admin/i18n/<code>/import", "admin_import")):
            page_route(bp, rule, ep, "i18n", "چند زبانه", "pages-i18n")

        async def lang_or_404(code):
            lang = await self.db.query("SELECT * FROM i18n_languages WHERE code=%s", (code,), one=True)
            if not lang:
                raise ApiError(404, "not_found", "زبان یافت نشد")
            return lang

        def lang_out(l):
            return {k: l.get(k) for k in ("id", "code", "name", "native_name", "direction", "flag", "is_default", "is_active")}

        # ---- admin API: languages ----
        @api_route(bp, "/api/admin/i18n", "api_languages_admin", ["GET", "POST"])
        async def api_languages_admin():
            if request.method == "POST":
                data = body()
                code = str(data.get("code") or "").strip().lower()
                name = str(data.get("name") or "").strip()
                native = str(data.get("native_name") or "").strip() or name
                direction = "rtl" if data.get("direction") == "rtl" else "ltr"
                flag = str(data.get("flag") or "").strip()[:16]
                is_default = 1 if data.get("is_default") else 0
                if not code or not name:
                    raise invalid({"code": "کد و نام زبان الزامی است"} if not code else {"name": "کد و نام زبان الزامی است"})
                if not re.match(r"^[a-z][a-z0-9_-]{1,7}$", code):
                    raise invalid({"code": "کد زبان نامعتبر است (مثلاً en, fa, pt-br)"})
                if not (LOCALES_DIR / f"{code}.json").exists():
                    (LOCALES_DIR / f"{code}.json").write_text("{}", encoding="utf-8")
                if is_default:
                    await self.db.execute("UPDATE i18n_languages SET is_default=0")
                await self.db.execute(
                    "INSERT INTO i18n_languages (code, name, native_name, direction, flag, is_default, is_active) "
                    "VALUES (%s,%s,%s,%s,%s,%s,1) "
                    "ON DUPLICATE KEY UPDATE name=VALUES(name), native_name=VALUES(native_name), "
                    "direction=VALUES(direction), flag=VALUES(flag), is_default=VALUES(is_default), is_active=1",
                    (code, name, native, direction, flag, is_default),
                )
                self._cache.invalidate_namespace(self._ns_for_lang(code))
                self.app.revalidate.notify("i18n", "site")
                return reply({"code": code}, 201)
            # If no language is marked default yet, make fa the default
            self.ensure_default_persisted()
            langs = await self.db.query("SELECT * FROM i18n_languages ORDER BY is_default DESC, name") or []
            stats = {}
            for l in langs:
                row = await self.db.query(
                    "SELECT COUNT(*) AS c FROM i18n_translations WHERE lang_code=%s", (l["code"],), one=True)
                stats[l["code"]] = int(row["c"]) if row else 0
            return reply({"languages": [lang_out(l) for l in langs], "source_lang": SOURCE_LANG_CODE,
                          "stats": stats, "total_keys": len(self.all_keys())})

        @api_route(bp, "/api/admin/i18n/default/fa", "api_set_default_fa", ["POST"])
        async def api_set_default_fa():
            await self.db.execute("UPDATE i18n_languages SET is_default=0")
            await self.db.execute(
                "INSERT INTO i18n_languages (code, name, native_name, direction, flag, is_default, is_active) "
                "VALUES (%s,%s,%s,%s,%s,1,1) ON DUPLICATE KEY UPDATE is_default=1, is_active=1",
                (SOURCE_LANG_CODE, "Persian", "فارسی", "rtl", "🇮🇷"),
            )
            self._cache.invalidate(f"{self.CACHE_NS}:default_code")
            return reply({"default": SOURCE_LANG_CODE})

        @api_route(bp, "/api/admin/i18n/<code>", "api_language", ["GET", "PUT", "DELETE"])
        async def api_language(code):
            lang = await lang_or_404(code)
            if request.method == "DELETE":
                if code == SOURCE_LANG_CODE:
                    raise ApiError(409, "conflict", "زبان مبدأ (فارسی) قابل حذف نیست")
                await self.db.execute("DELETE FROM i18n_languages WHERE code=%s", (code,))
                await self.db.execute("DELETE FROM i18n_translations WHERE lang_code=%s", (code,))
                self._cache.invalidate_namespace(self._ns_for_lang(code))
                self.app.revalidate.notify("i18n", "site")
                return reply({"deleted": code})
            if request.method == "PUT":
                d = body()
                data = {
                    "name": str(d.get("name") or "").strip() or lang["name"],
                    "native_name": str(d.get("native_name") or "").strip() or lang["native_name"],
                    "direction": "rtl" if d.get("direction") == "rtl" else "ltr",
                    "flag": str(d.get("flag") or "").strip()[:16],
                    "is_active": 1 if d.get("is_active") else 0,
                }
                is_default = 1 if d.get("is_default") else 0
                if is_default:
                    await self.db.execute("UPDATE i18n_languages SET is_default=0")
                data["is_default"] = is_default
                await self.db.update_table("i18n_languages", lang["id"], data)
                self._cache.invalidate_namespace(self._ns_for_lang(code))
                self.app.revalidate.notify("i18n", "site")
                lang = await lang_or_404(code)
            return reply(lang_out(lang))

        @api_route(bp, "/api/admin/i18n/<code>/translate", "api_translate_admin", ["GET", "PUT"])
        async def api_translate_admin(code):
            """Per-language translation editor. PUT ``{prefix, values: {key: text}}`` touches only the keys sent
            (empty text = delete the row so the source language shows through)."""
            lang = await lang_or_404(code)
            prefix = (request.args.get("prefix") or "").strip()
            if request.method == "PUT":
                data = body()
                prefix = str(data.get("prefix") or prefix).strip()
                values = data.get("values")
                if not isinstance(values, dict):
                    raise invalid({"values": "values باید شیء {کلید: متن} باشد"})
                allowed = {k for k in self.all_keys() if k.startswith(prefix)}
                count = 0
                new_values: dict[str, str] = {}
                for key, val in values.items():
                    if key not in allowed:
                        continue
                    val = str(val or "").strip()
                    if not val:
                        await self.db.execute(
                            "DELETE FROM i18n_translations WHERE lang_code=%s AND translation_key=%s", (code, key))
                        continue
                    await self.db.execute(
                        "INSERT INTO i18n_translations (lang_code, translation_key, value) VALUES (%s,%s,%s) "
                        "ON DUPLICATE KEY UPDATE value=VALUES(value)", (code, key, val))
                    new_values[key] = val
                    count += 1
                # mirror values to alias keys (and back), unless the admin set both explicitly
                for alias_key, target_key in ALIASES.items():
                    for src, dst in ((target_key, alias_key), (alias_key, target_key)):
                        if dst in new_values or not new_values.get(src):
                            continue
                        await self.db.execute(
                            "INSERT INTO i18n_translations (lang_code, translation_key, value) VALUES (%s,%s,%s) "
                            "ON DUPLICATE KEY UPDATE value=VALUES(value)", (code, dst, new_values[src]))
                self._cache.invalidate_namespace(self._ns_for_lang(code))
                self.app.revalidate.notify("i18n")
                return reply({"saved": count})
            scoped_keys = [k for k in self.all_keys() if k.startswith(prefix)]
            source = dict(self._load_source_locale())
            # frontend ("web.*") source strings live in the DB as fa rows
            fa_rows = await self.db.query(
                "SELECT translation_key, value FROM i18n_translations WHERE lang_code=%s", (SOURCE_LANG_CODE,)) or []
            for r in fa_rows:
                source.setdefault(r["translation_key"], r["value"])
            existing = await self.db.query(
                "SELECT translation_key, value FROM i18n_translations WHERE lang_code=%s", (code,)) or []
            existing_map = {r["translation_key"]: r["value"] for r in existing}
            keys = []
            for k in scoped_keys:
                parts = k.split(".")
                group = ".".join(parts[:2]) if k.startswith("web.") and len(parts) > 2 else parts[0]
                keys.append({"key": k, "source": source.get(k, k), "value": existing_map.get(k, ""), "group": group})
            keys.sort(key=lambda r: (r["group"], r["key"]))
            prefixes = sorted({("web." if k.startswith("web.") else k.split(".")[0] + ".") for k in self.all_keys()})
            return reply({"lang": lang_out(lang), "keys": keys, "prefix": prefix, "prefixes": prefixes,
                          "is_source": code == SOURCE_LANG_CODE})

        @api_route(bp, "/api/admin/i18n/<code>/export", "api_export")
        async def api_export(code):
            """Download the language file (so the admin can keep a backup)."""
            await lang_or_404(code)
            data = await self._load_translation_dict(code)
            from flask import Response
            return Response(
                json.dumps(data, ensure_ascii=False, indent=2), mimetype="application/json",
                headers={"Content-Disposition": f'attachment; filename="{code}.json"'},
            )

        @api_route(bp, "/api/admin/i18n/<code>/seed", "api_seed", ["POST"])
        async def api_seed(code):
            """Copy every source-language value into this language as a starting point (never overwrites)."""
            await lang_or_404(code)
            if code == SOURCE_LANG_CODE:
                raise ApiError(409, "conflict", "زبان مبدأ نیاز به seed ندارد")
            count = 0
            for k, v in self._load_source_locale().items():
                existing = await self.db.query(
                    "SELECT id FROM i18n_translations WHERE lang_code=%s AND translation_key=%s", (code, k), one=True)
                if existing:
                    continue
                await self.db.execute(
                    "INSERT INTO i18n_translations (lang_code, translation_key, value) VALUES (%s,%s,%s)", (code, k, v))
                count += 1
            self._cache.invalidate_namespace(self._ns_for_lang(code))
            self.app.revalidate.notify("i18n")
            return reply({"copied": count})

        # ---- public API ----
        @bp.route("/api/i18n/languages")
        async def api_languages():
            langs = await self.db.query(
                "SELECT code, name, native_name, direction, flag, is_default "
                "FROM i18n_languages WHERE is_active=1 ORDER BY is_default DESC, name"
            ) or []
            return self.respond({"languages": langs, "current": self.current_lang()})

        @bp.route("/api/i18n/translate/<code>")
        async def api_translate(code):
            # Optional params (all additive; with none the body is exactly the
            # merged {key: value} dict as before):
            #   prefix=web.     only keys with this prefix
            #   strip_prefix=1  drop the prefix from the returned keys
            #   fallback=1      fill untranslated keys from the source language
            from flask import Response
            import hashlib

            data = await self._load_translation_dict(code)
            prefix = (request.args.get("prefix") or "").strip()

            def flag(n):
                return (request.args.get(n) or "").strip().lower() in ("1", "true", "yes", "on")

            if flag("fallback") and code != SOURCE_LANG_CODE:
                merged = dict(await self._load_translation_dict(SOURCE_LANG_CODE))
                merged.update({k: v for k, v in data.items() if v not in (None, "")})
                data = merged
            if prefix:
                data = {k: v for k, v in data.items() if k.startswith(prefix)}
                if flag("strip_prefix"):
                    data = {k[len(prefix):]: v for k, v in data.items()}
            body = json.dumps(data, ensure_ascii=False)
            etag = '"' + hashlib.sha1(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24] + '"'
            if request.headers.get("If-None-Match", "").strip() == etag:
                return Response(status=304, headers={"ETag": etag})
            return Response(
                body, mimetype="application/json",
                headers={"ETag": etag, "Cache-Control": "public, max-age=30, stale-while-revalidate=300"},
            )

        # ---- admin: import UI strings from a (nested) JSON file ----
        @api_route(bp, "/api/admin/i18n/<code>/import", "api_import", ["POST"])
        async def api_import(code):
            await lang_or_404(code)
            f = request.files.get("file")
            prefix = (request.form.get("prefix") or "web.").strip()
            mode = request.form.get("mode", "missing")
            if mode not in ("missing", "overwrite"):
                mode = "missing"
            if mode == "overwrite" and request.form.get("confirm_overwrite") not in ("1", "true", "on"):
                raise invalid({"confirm_overwrite": "برای بازنویسی ترجمه‌های موجود باید تأیید صریح بدهید"})
            if not f or not f.filename:
                raise invalid({"file": "فایل JSON انتخاب نشده است"})
            raw = f.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise invalid({"file": "حجم فایل بیش از ۲ مگابایت است"})
            try:
                data = json.loads(raw.decode("utf-8-sig"))
                if not isinstance(data, dict):
                    raise ValueError("ریشه‌ی JSON باید یک شیء باشد")
            except (ValueError, UnicodeDecodeError) as e:
                raise invalid({"file": f"فایل JSON نامعتبر است: {e}"})
            res = await self.import_strings(code, data, prefix=prefix, mode=mode)
            return reply({**res, "prefix": prefix})

        # ---- language switcher (redirect to <code> prefix) ----
        @bp.route("/lang/<code>")
        async def switch_lang(code):
            # The language is selected ONLY by the resulting URL prefix.
            # Do not store it in a cookie/session/global state.
            row = await self.db.query(
                "SELECT code FROM i18n_languages "
                "WHERE code=%s AND is_active=1", (code,), one=True,
            )
            target = url_for("core.index")
            if row:
                # ``next`` may already be a path beginning with the
                # language prefix; just use it as‑is when provided.
                nxt = request.args.get("next", "/")
                if not nxt.startswith(f"/{row['code']}") and nxt != "/":
                    nxt = f"/{row['code']}{nxt if nxt.startswith('/') else '/' + nxt}"
                target = nxt
                # Do **not** set a persistent cookie – language should be
                # derived solely from the URL prefix. The request without a
                # prefix must fall back to the default language.
                return redirect(target)
            return redirect(target)

        self.app.register_blueprint(bp)

        # ------------------------------------------------------------------
        # Language-aware URL generation
        # ------------------------------------------------------------------
        # Existing templates in the project use ``url_for(...)`` directly.
        # Keep that compatibility, but make the wrapper depend ONLY on the
        # current request's explicit URL prefix (g.lang_prefix). It therefore
        # cannot carry /en from one request into another.
        #
        # ``flask_url_for(...)`` remains available when a raw, unprefixed
        # Flask URL is explicitly required.
        from flask import url_for as flask_url_for
        self.app.jinja_env.globals['flask_url_for'] = flask_url_for
        self.app.jinja_env.globals['url_for'] = self.url_for_lang

        # ---- URL prefix middleware ----------------------------------
        # Any /<code>/... path where <code> is a known active language
        # activates that language and the rest of the path is routed as
        # if the prefix wasn't there. This is transparent to the rest
        # of the app: existing routes keep working without registering
        # every URL twice.
        #
        # Implementation: we wrap the app's WSGI callable so we can
        # strip the language prefix from PATH_INFO *before* Flask's URL
        # router runs. A `before_request` hook would run too late
        # (after URL matching), and Werkzeug's request object caches
        # PATH_INFO at request creation time, so neither works. The
        # WSGI layer is the only place where the rewrite is visible to
        # the URL map.
        if not getattr(self.app, "_i18n_wsgi_wrapped", False):
            original_wsgi = self.app.wsgi_app

            def _i18n_wsgi(environ, start_response):
                path = environ.get("PATH_INFO", "/") or "/"
                seg = path.lstrip("/").split("/", 1)[0] if path != "/" else ""

                # Determine language based on the first URL segment.
                # Previously we consulted the DB ``_known_codes_set`` which
                # could miss a language that has a locale file but is not
                # yet marked active. To make the prefix work independently of
                # DB state, we now treat the segment as a language when a
                # corresponding ``<code>.json`` file exists in the locales
                # directory.
                if seg:
                    locale_path = LOCALES_DIR / f"{seg}.json"
                    if locale_path.is_file():
                        # remember the language in a header so the
                        # `before_request` hook below (running inside the
                        # app context) can pick it up and set g.lang.
                        environ["HTTP_X_I18N_LANG"] = seg
                        environ["HTTP_X_I18N_PREFIX"] = f"/{seg}"
                        rest = path[len(f"/{seg}"): ] or "/"
                        environ["PATH_INFO"] = rest
                        # Warm the per-language cache SYNCHRONOUSLY before
                        # Flask enters the request. We do this in the WSGI
                        # layer (not in `before_request` or inside an
                        # async route) because:
                        #   1) here there is no running event loop, so
                        #      ``asyncio.run()`` works;
                        #   2) by the time the route handler runs, the
                        #      translation dict is already in the in-process
                        #      cache and ``t()`` never has to touch the DB.
                        self._warm_translation_cache_sync(seg)
                else:
                    # No language prefix: always treat the request as the
                    # source language (Persian). This ensures that URLs
                    # without a language code never inherit the language
                    # from the configured default (which might be English).
                    # We still warm the cache for the source language so
                    # ``t()`` works efficiently.
                    try:
                        default_lang = SOURCE_LANG_CODE
                        environ["HTTP_X_I18N_LANG"] = default_lang
                        environ["HTTP_X_I18N_PREFIX"] = ""
                        self._warm_translation_cache_sync(default_lang)
                    except Exception:
                        pass
                return original_wsgi(environ, start_response)

            self.app.wsgi_app = _i18n_wsgi
            self.app._i18n_wsgi_wrapped = True

        @self.app.before_request
        def _set_g_lang():
            """Initialize language state for THIS request only.

            Preference order:
            1. Language explicitly set by the WSGI wrapper via
               ``HTTP_X_I18N_LANG``/``HTTP_X_I18N_PREFIX``. The wrapper runs
               before Flask routing and injects the original URL prefix, so
               this is the most reliable source for a prefixed request like
               ``/en/...``.
            2. If the wrapper did not set a language (e.g. request has no
               prefix), fall back to inspecting ``request.path`` – the first
               segment is treated as a potential language code if a matching
               locale file exists.
            3. Ultimately, default to the source language (Persian).
            """
            from flask import g
            # 1️⃣ Check the WSGI‑injected environ values first.
            env_lang = request.environ.get("HTTP_X_I18N_LANG")
            if env_lang:
                g.lang = env_lang
                g.lang_prefix = request.environ.get("HTTP_X_I18N_PREFIX", "")
                g.i18n_explicit = True
            else:
                # 2️⃣ No explicit prefix – derive from the request path.
                path = request.path.lstrip("/")
                first_seg = path.split("/", 1)[0] if path else ""
                lang_candidate = first_seg.lower()
                locale_path = LOCALES_DIR / f"{lang_candidate}.json"
                if lang_candidate and locale_path.is_file():
                    g.lang = lang_candidate
                    g.lang_prefix = f"/{lang_candidate}"
                    g.i18n_explicit = True
                else:
                    # 3️⃣ Default to source language.
                    g.lang = SOURCE_LANG_CODE
                    g.lang_prefix = ""
                    g.i18n_explicit = False

        # register a Jinja filter so templates can use {{ 'nav.home'|_ }}
        self.app.jinja_env.filters.setdefault("_", self._jinja_t)

        # inject a context processor so templates can use
        # {{ lang.code }} / {{ lang.direction }} / {{ all_languages }}.
        # We read from g.lang (set by the before_request hook) and
        # fall back to the cached default when there's no active
        # request context (e.g. background renders).
        @self.app.context_processor
        def _inject_i18n_ctx():
            from flask import has_request_context, g as _g, request as _req
            if has_request_context():
                # g.lang/g.lang_prefix are initialized for every request.
                # Do NOT fall back to a previous/default language here.
                code = getattr(_g, "lang", SOURCE_LANG_CODE) or SOURCE_LANG_CODE
                prefix = getattr(_g, "lang_prefix", "") or ""
            else:
                code = SOURCE_LANG_CODE
                prefix = ""
            return {
                "current_lang": code,
                "lang_prefix": prefix,
            }

        # Expose a global template helper: {{ lurl('core.dashboard') }} →
        # /en/dashboard  when current lang is 'en', otherwise /dashboard.
        # This is the recommended way to build language-aware links.
        @self.app.template_global("lurl")
        def _lurl(endpoint, **values):
            """Build a URL while preserving ONLY the current URL language.

            ``/en/...`` request -> generated links are ``/en/...``.
            Unprefixed request -> generated links remain unprefixed.
            This is intentionally independent of the DB default language.
            """
            from flask import has_request_context, g as _g, url_for
            base = url_for(endpoint, **values)
            if not has_request_context():
                return base
            prefix = getattr(_g, "lang_prefix", "") or ""
            if prefix and base.startswith("/"):
                # Avoid double-prefixing if a caller supplied a path that
                # already starts with the active language prefix.
                if base == prefix or base.startswith(prefix + "/"):
                    return base
                return f"{prefix}{base}"
            return base

        # expose helpers on the app for plugins to import
        self.app.i18n_t = self.t
        self.app.i18n_translate_payload = self.translate_payload
        self.app.i18n_current_lang = self.current_lang

    # ------------------------------------------------------------------
    # frontend ("web.*") UI strings import
    # ------------------------------------------------------------------
    def _register_web_keys(self):
        """Imported frontend keys must appear in the translate screen, so
        register every ``web.*`` key found in the DB at boot."""
        try:
            import asyncio
            rows = asyncio.run(self.db.query(
                "SELECT DISTINCT translation_key FROM i18n_translations WHERE translation_key LIKE 'web.%'"
            )) or []
            self.register_keys([r["translation_key"] for r in rows])
        except Exception as e:
            print(f"[i18n] web keys registration skipped: {e}")

    @staticmethod
    def flatten_json(data: dict, prefix: str = "") -> tuple[dict, int]:
        """Nested JSON -> ``{"prefix.a.b": "text"}``. Values keep their
        ``{placeholders}`` untouched. Returns ``(flat, ignored_count)`` where
        ignored counts lists/null/bool leaves that cannot be a UI string."""
        flat, ignored = {}, 0

        def walk(node, path):
            nonlocal ignored
            for k, v in node.items():
                key = f"{path}.{k}" if path else str(k)
                if isinstance(v, dict):
                    walk(v, key)
                elif isinstance(v, str):
                    flat[key] = v
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    flat[key] = str(v)
                else:
                    ignored += 1

        walk(data, "")
        return {prefix + k: v for k, v in flat.items()}, ignored

    async def import_strings(self, code: str, data: dict, *, prefix: str = "web.", mode: str = "missing") -> dict:
        """Import a nested UI-string dict for language ``code``.

        ``mode='missing'`` (default) only inserts keys that do not exist yet,
        so admin edits are never overwritten; ``'overwrite'`` upserts.
        Returns counts ``{added, updated, skipped, ignored}``."""
        flat, ignored = self.flatten_json(data, prefix)
        existing = await self.db.fetch(
            "SELECT translation_key FROM i18n_translations WHERE lang_code=%s", (code,)
        )
        have = {r["translation_key"] for r in existing}
        new = {k: v for k, v in flat.items() if k not in have}
        old = {k: v for k, v in flat.items() if k in have}
        added, updated = len(new), 0
        sql = (
            "INSERT INTO i18n_translations (lang_code, translation_key, value) VALUES (%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE value=VALUES(value)"
        )
        rows = [(code, k, v) for k, v in new.items()]
        if mode == "overwrite":
            rows += [(code, k, v) for k, v in old.items()]
            updated = len(old)

        def go(tx):
            tx.many(sql, rows)

        await self.db.transaction(go)
        skipped = 0 if mode == "overwrite" else len(old)
        self._cache.invalidate_namespace(self._ns_for_lang(code))
        self.register_keys(list(flat.keys()))
        self.app.revalidate.notify("i18n")
        return {"added": added, "updated": updated, "skipped": skipped, "ignored": ignored}

    # ------------------------------------------------------------------
    # helpers: source locale / per-language file
    # ------------------------------------------------------------------
    def _ensure_source_locale(self):
        """Write a default ``fa.json`` if it doesn't exist yet, with the
        canonical Persian strings for every registered key. Admins can
        edit this file directly on disk; changes are picked up on the
        next request (cache invalidation drops the in-memory copy)."""
        path = LOCALES_DIR / f"{SOURCE_LANG_CODE}.json"
        if path.exists():
            return
        default_values = {
            "nav.home": "خانه",
            "nav.dashboard": "داشبورد",
            "nav.logout": "خروج",
            "nav.login": "ورود",
            "nav.products": "محصولات",
            "nav.categories": "دسته‌بندی‌ها",
            "nav.images": "تصاویر",
            "nav.cache": "کش",
            "nav.tracking": "ردگیری",
            "nav.languages": "زبان‌ها",
            "action.save": "ذخیره",
            "action.delete": "حذف",
            "action.edit": "ویرایش",
            "action.create": "ایجاد",
            "action.cancel": "انصراف",
            "action.search": "جستجو",
            "action.confirm": "تأیید",
            "action.activate": "فعال‌سازی",
            "action.deactivate": "غیرفعال‌سازی",
            "action.back": "بازگشت",
            "action.purge": "پاکسازی",
            "action.next": "بعدی",
            "action.prev": "قبلی",
            "action.submit": "ارسال",
            "flash.saved": "ذخیره شد",
            "flash.deleted": "حذف شد",
            "flash.created": "ایجاد شد",
            "flash.error": "خطایی رخ داد",
            "flash.not_found": "یافت نشد",
            "flash.unauthorized": "دسترسی غیرمجاز",
            "flash.invalid_input": "ورودی نامعتبر",
            "product.title": "محصول",
            "product.price": "قیمت",
            "product.stock": "موجودی",
            "product.sku": "کد محصول",
            "product.category": "دسته‌بندی",
            "product.status.published": "منتشر شده",
            "product.status.draft": "پیش‌نویس",
            "product.list.title": "لیست محصولات",
            "product.list.empty": "محصولی وجود ندارد",
            "product.detail.not_found": "محصول یافت نشد",
            "product.add": "افزودن محصول",
            "category.title": "دسته‌بندی",
            "category.list.title": "لیست دسته‌بندی‌ها",
            "category.list.empty": "دسته‌بندی‌ای وجود ندارد",
            "category.add": "افزودن دسته‌بندی",
            "category.parent": "دسته والد",
            "category.root": "دسته اصلی",
            "settings.title": "تنظیمات سایت",
            "settings.site_title": "عنوان سایت",
            "settings.meta_description": "توضیحات متا",
            "settings.meta_keywords": "کلیدواژه‌ها",
            "settings.saved": "تنظیمات ذخیره شد",
            "users.title": "کاربران",
            "users.create": "ایجاد کاربر",
            "users.delete": "حذف کاربر",
            "tracking.title": "ردگیری بازدیدها",
            "tracking.dashboard": "داشبورد ردگیری",
            "tracking.visitors": "بازدیدکنندگان",
            "error.404.title": "صفحه پیدا نشد",
            "error.404.body": "صفحه‌ای که دنبال آن می‌گردید وجود ندارد.",
        }
        path.write_text(
            json.dumps(default_values, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_source_locale(self) -> dict:
        """Read the canonical Persian file (cached briefly)."""
        path = LOCALES_DIR / f"{SOURCE_LANG_CODE}.json"
        cache_key = f"{self.CACHE_NS}:source:locale"
        cached = self._cache.get(cache_key, namespace=self.CACHE_NS)
        if cached is not None:
            return cached
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        self._cache.set(cache_key, data, ttl=60, namespace=self.CACHE_NS)
        return data

    async def _load_translation_dict(self, code: str) -> dict:
        """Return the merged translation dict for a single language:
        {key: value} where missing keys fall back to the source file."""
        ns = self._ns_for_lang(code)
        cache_key = f"{ns}:dict"
        cached = self._cache.get(cache_key, namespace=self.CACHE_NS)
        if cached is not None:
            return cached
        rows = await self.db.query(
            "SELECT translation_key, value FROM i18n_translations "
            "WHERE lang_code=%s",
            (code,),
        ) or []
        result = {r["translation_key"]: r["value"] for r in rows}
        # also pick up any keys the admin saved into the on-disk file
        # (in case they want to ship a pre-translated locale by uploading
        # a JSON file via the export endpoint)
        path = LOCALES_DIR / f"{code}.json"
        if path.exists():
            try:
                on_disk = json.loads(path.read_text(encoding="utf-8"))
                for k, v in on_disk.items():
                    result.setdefault(k, v)
            except Exception:
                pass
        # cache aggressively: translations don't change between edits
        self._cache.set(cache_key, result, ttl=600, namespace=self.CACHE_NS)
        return result

    def _warm_translation_cache_sync(self, code: str) -> None:
        """Synchronously fetch the translation dict for ``code`` and
        put it in the cache. Called from the WSGI wrapper (where no
        event loop is running) so that the per-request route handler
        can read the dict from cache without ever needing ``asyncio.run``.

        Skips:
        - the source language (no per-language dict is needed)
        - cache hits (already warm)
        - any DB error (the route handler falls back to source).
        """
        if code == SOURCE_LANG_CODE:
            return
        ns = self._ns_for_lang(code)
        cache_key = f"{ns}:dict"
        if self._cache.get(cache_key, namespace=self.CACHE_NS) is not None:
            return
        try:
            import asyncio
            rows = asyncio.run(self.db.query(
                "SELECT translation_key, value FROM i18n_translations "
                "WHERE lang_code=%s",
                (code,),
            )) or []
        except Exception:
            # already inside a loop, or DB unavailable — let the
            # route handler deal with it.
            return
        result = {r["translation_key"]: r["value"] for r in rows}
        path = LOCALES_DIR / f"{code}.json"
        if path.exists():
            try:
                on_disk = json.loads(path.read_text(encoding="utf-8"))
                for k, v in on_disk.items():
                    result.setdefault(k, v)
            except Exception:
                pass
        self._cache.set(cache_key, result, ttl=600, namespace=self.CACHE_NS)

    # ------------------------------------------------------------------
    # helpers: namespaces & code sets
    # ------------------------------------------------------------------
    @staticmethod
    def _ns_for_lang(code: str) -> str:
        return f"i18n_lang_{code}"

    def _known_codes_set(self) -> set:
        cache_key = f"{self.CACHE_NS}:known_codes"
        cached = self._cache.get(cache_key, namespace=self.CACHE_NS)
        if cached is not None:
            return cached
        rows = self._run_sync(
            "SELECT code FROM i18n_languages WHERE is_active=1"
        ) or []
        codes = {SOURCE_LANG_CODE} | {r["code"] for r in rows}
        self._cache.set(cache_key, codes, ttl=30, namespace=self.CACHE_NS)
        return codes

    def _run_sync(self, sql, params=()):
        """Run a sync DB query from sync-only call sites (like the
        url_value_preprocessor which is invoked outside an async context).
        Uses ``asyncio.run`` on a fresh loop just like ``routes.py`` does
        for its ``inject_settings`` processor."""
        import asyncio
        try:
            # Fast path: no running loop → fresh asyncio.run.
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False
        if not in_loop:
            return asyncio.run(self.db.query(sql, params))
        # Already inside a loop: schedule the coroutine on a thread
        # so we don't block the running loop. Use asyncio.run in the
        # worker thread; the result is awaited via a future.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            future = ex.submit(asyncio.run, self.db.query(sql, params))
            return future.result()

    def _default_code(self) -> str:
        """Return the active default language code (sync).

        Lookup order:
        1. Cache (the result is stable until an admin changes it).
        2. The row marked ``is_default=1`` in ``i18n_languages``.
        3. If none is marked, but ``fa`` exists as a row → treat it as
           default and persist the flag back to the DB.
        4. If ``fa`` doesn't exist either → lazily insert it (Persian
           name, RTL, active, default) so the system always has *some*
           default. This is the "no default configured? fa is the
           default" behaviour the user asked for.
        """
        cache_key = f"{self.CACHE_NS}:default_code"
        cached = self._cache.get(cache_key, namespace=self.CACHE_NS)
        if cached is not None:
            return cached

        # 2) look for an explicit default
        rows = self._run_sync(
            "SELECT code FROM i18n_languages "
            "WHERE is_default=1 AND is_active=1 LIMIT 1"
        ) or []
        if rows:
            code = rows[0]["code"]
            self._cache.set(cache_key, code, ttl=30, namespace=self.CACHE_NS)
            return code

        # 3) no explicit default — does fa exist as a row?
        fa = self._run_sync(
            "SELECT id, is_default FROM i18n_languages WHERE code=%s LIMIT 1",
            (SOURCE_LANG_CODE,),
        ) or []
        if fa:
            # promote fa to default
            self._run_sync(
                "UPDATE i18n_languages SET is_default=1, is_active=1 "
                "WHERE id=%s",
                (fa[0]["id"],),
            )
            self._cache.set(cache_key, SOURCE_LANG_CODE, ttl=30, namespace=self.CACHE_NS)
            return SOURCE_LANG_CODE

        # 4) nothing at all — lazily insert fa as the default
        try:
            self._run_sync(
                "INSERT INTO i18n_languages "
                "(code, name, native_name, direction, flag, "
                " is_default, is_active) "
                "VALUES (%s,%s,%s,%s,%s,1,1) "
                "ON DUPLICATE KEY UPDATE "
                "is_default=1, is_active=1",
                (SOURCE_LANG_CODE, "Persian", "فارسی", "rtl", "🇮🇷"),
            )
        except Exception:
            pass
        self._cache.set(cache_key, SOURCE_LANG_CODE, ttl=30, namespace=self.CACHE_NS)
        return SOURCE_LANG_CODE

    def ensure_default_persisted(self) -> None:
        """Public hook the admin UI can call to guarantee the default
        language row exists in the DB. Idempotent; safe to call often."""
        # drop the cache so the lookup re-runs against the DB
        self._cache.invalidate(f"{self.CACHE_NS}:default_code")
        self._default_code()

    def all_keys(self) -> list:
        """Return the union of default keys, runtime-registered keys,
        and any keys present in the source file (so newly added lines
        become editable without a restart)."""
        keys = set(DEFAULT_KEYS) | set(self._extra_keys)
        source = self._load_source_locale()
        keys.update(source.keys())
        return sorted(keys)

    # ------------------------------------------------------------------
    # public translation API
    # ------------------------------------------------------------------
    def current_lang(self) -> str:
        """Code of the language active for this request."""
        from flask import g, has_request_context
        if has_request_context():
            code = getattr(g, "lang", None)
            if code:
                return code
        # Outside a request there is no URL prefix, so use the canonical
        # source language rather than leaking a DB-configured default into
        # generated/background content.
        return SOURCE_LANG_CODE

    def url_for_lang(self, endpoint: str, lang: str = None, **values) -> str:
        """Build an explicitly language-aware URL.

        When ``lang`` is omitted, preserve the language prefix of the
        CURRENT request. If the current request is unprefixed, the returned
        URL is also unprefixed. This prevents an ``/en`` request from leaking
        into later unprefixed requests.

        Pass ``lang="en"`` (or another active code) when an explicit target
        language is required. ``fa`` intentionally has no URL prefix.
        """
        from flask import url_for, g, has_request_context
        base = url_for(endpoint, **values)
        if not base.startswith("/"):
            return base

        if lang is None:
            if has_request_context():
                # The prefix, not merely g.lang, is authoritative for URL
                # generation. An unprefixed request must stay unprefixed.
                prefix = getattr(g, "lang_prefix", "") or ""
            else:
                prefix = ""
        else:
            lang = str(lang).strip().lower()
            prefix = "" if not lang or lang == SOURCE_LANG_CODE else f"/{lang}"

        if prefix:
            if base == prefix or base.startswith(prefix + "/"):
                return base
            return f"{prefix}{base}"
        return base

    def _lookup_with_aliases(self, mapping: dict, key: str):
        """Look up ``key`` in ``mapping``; if absent, follow the
        ALIASES chain and try the alias(es). Returns the value or
        None."""
        if key in mapping and mapping[key]:
            return mapping[key]
        alias = ALIASES.get(key)
        if alias and alias in mapping and mapping[alias]:
            return mapping[alias]
        return None

    async def t_async(self, key: str, default: str | None = None) -> str:
        """Async variant: looks up ``key`` in the current language, then
        the source, then returns ``default`` or ``key``."""
        lang = self.current_lang()
        if lang == SOURCE_LANG_CODE:
            source = self._load_source_locale()
            # also try aliases
            v = self._lookup_with_aliases(source, key)
            if v is not None:
                return v
            return source.get(key, default or key)
        tr = await self._load_translation_dict(lang)
        v = self._lookup_with_aliases(tr, key)
        if v is not None:
            return v
        # fall back to source
        source = self._load_source_locale()
        v = self._lookup_with_aliases(source, key)
        if v is not None:
            return v
        return source.get(key, default or key)

    def t(self, key: str, default: str | None = None) -> str:
        """Sync variant: returns the string for the active language. Use
        this in templates or anywhere you don't have an ``await`` handy."""
        lang = self.current_lang()
        if lang == SOURCE_LANG_CODE:
            source = self._load_source_locale()
            v = self._lookup_with_aliases(source, key)
            if v is not None:
                return v
            return source.get(key, default or key)
        # 1) hot path: cache (populated by the async loaders and the
        # WSGI-layer warmer). This is the path that almost always
        # hits in production.
        ns = self._ns_for_lang(lang)
        cache_key = f"{ns}:dict"
        cached = self._cache.get(cache_key, namespace=self.CACHE_NS)
        if cached is not None:
            v = self._lookup_with_aliases(cached, key)
            if v is not None:
                return v
        # 2) cache miss: synchronously query the DB. We can only do
        # this if we're NOT already inside a running event loop
        # (asyncio.run would raise). When we are inside a loop — e.g.
        # the caller is an async route handler that forgot to use
        # ``t_async`` — we just skip and fall back to the source file.
        # The WSGI warmer takes care of hitting this path in practice
        # so the fallback is rare.
        try:
            import asyncio
            try:
                asyncio.get_running_loop()
                in_loop = True
            except RuntimeError:
                in_loop = False
            if not in_loop:
                rows = asyncio.run(self.db.query(
                    "SELECT translation_key, value FROM i18n_translations "
                    "WHERE lang_code=%s",
                    (lang,),
                )) or []
                fresh = {r["translation_key"]: r["value"] for r in rows}
                path = LOCALES_DIR / f"{lang}.json"
                if path.exists():
                    try:
                        on_disk = json.loads(path.read_text(encoding="utf-8"))
                        for k, v in on_disk.items():
                            fresh.setdefault(k, v)
                    except Exception:
                        pass
                self._cache.set(cache_key, fresh, ttl=600, namespace=self.CACHE_NS)
                v = self._lookup_with_aliases(fresh, key)
                if v is not None:
                    return v
        except Exception:
            pass
        # 3) final fallback: source file (with alias)
        source = self._load_source_locale()
        v = self._lookup_with_aliases(source, key)
        if v is not None:
            return v
        return source.get(key, default or key)

    @pass_context
    def _jinja_t(self, _context, key):
        """Jinja filter wrapper.

        Marked with ``pass_context`` so Jinja treats it as context-dependent.
        Without this, Jinja's compiler constant-folds ``{{ 'key' | _ }}``
        (a filter call on a literal string) at template *compile* time and
        bakes the result into the cached compiled template — so whichever
        language happened to be active on the first render of a given
        template would stick for every later request until the process
        restarted, regardless of the actual request's language.
        """
        return self.t(key)

    # ------------------------------------------------------------------
    # payload translation
    # ------------------------------------------------------------------
    async def translate_payload(self, obj):
        """Recursively walk a dict/list payload and replace every string
        value with its translated counterpart. Translation is performed
        using the active language's dictionary: any string that
        *exactly* matches a source-language value is swapped for the
        same key's translated value.

        This is the "translate from the core before returning to the
        user" behaviour: plugins that return Persian data to the
        browser can pass their payload through this helper and get
        an English/Arabic/... version back without any per-plugin
        changes.
        """
        if obj is None:
            return obj
        if isinstance(obj, str):
            return await self._translate_string(obj)
        if isinstance(obj, list):
            return [await self.translate_payload(v) for v in obj]
        if isinstance(obj, dict):
            return {k: await self.translate_payload(v) for k, v in obj.items()}
        return obj

    async def _translate_string(self, value: str) -> str:
        lang = self.current_lang()
        if lang == SOURCE_LANG_CODE:
            return value
        source = self._load_source_locale()
        # build reverse map: source value -> key
        rev = {v: k for k, v in source.items() if v}
        key = rev.get(value)
        if not key:
            return value
        tr = await self._load_translation_dict(lang)
        return tr.get(key) or value
