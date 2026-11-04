"""Infrastructure for the admin JSON API (``/api/admin/*``).

The admin panel (Vuexy shell + ``fetch``) and a future React admin talk to the
backend only through this API. Conventions:

- success: ``{"ok": true, "data": ..., "meta": {...}?}``
- error:   ``{"ok": false, "error": "<code>", "message": "...", "fields": {...}?}``
  (the same envelope as ``/api/public/*``; see :mod:`app.core.public`)
- auth: the Flask session cookie. ``401`` = not logged in, ``403`` = not an
  administrator or CSRF failure. Every non-GET request must send the token
  returned by ``/api/admin/auth/me`` (or login) in ``X-CSRF-Token``.
"""
from __future__ import annotations

import asyncio
import functools
import hmac
import secrets

from flask import Blueprint, current_app, request, session

from .auth import AuthManager
from .public import ApiError, RateLimiter, bad_request, client_ip, dumps, json_body, json_response

PREFIX = "/api/admin"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
MAX_BODY = 2 * 1024 * 1024
LOGIN_LIMIT = RateLimiter()

# tabler icon per plugin for the sidebar (emoji icons in ``admin_entry`` stay for the legacy dashboard)
MENU_ICONS = {
    "products": "ti-package", "categories": "ti-category", "brands": "ti-tag", "projects": "ti-building",
    "articles": "ti-news", "services": "ti-tool", "faq": "ti-help", "company": "ti-building-skyscraper",
    "inquiries": "ti-mail", "images": "ti-photo", "i18n": "ti-language", "cache": "ti-bolt",
    "navigation": "ti-menu-2", "site_settings": "ti-settings", "theme_builder": "ti-palette",
    "tracking": "ti-chart-line", "visits": "ti-chart-bar", "public_api": "ti-plug", "documents": "ti-file-text",
    "page_builder": "ti-layout-board",
}


def api_blueprint(name: str) -> Blueprint:
    return Blueprint(name, __name__, url_prefix=PREFIX)


def is_admin_api_path() -> bool:
    p = request.path
    return p == PREFIX or p.startswith(PREFIX + "/")


# ---------------------------------------------------------------------------
# responses
# ---------------------------------------------------------------------------
def reply(data=None, status=200, meta=None):
    body = {"ok": True, "data": data}
    if meta:
        body["meta"] = meta
    resp = json_response(dumps(body), status)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def invalid(fields: dict, message="Validation failed") -> ApiError:
    return ApiError(422, "validation_failed", message, fields=fields)


def body() -> dict:
    return json_body(MAX_BODY)


# ---------------------------------------------------------------------------
# auth / csrf
# ---------------------------------------------------------------------------
def csrf_token() -> str:
    tok = session.get("csrf")
    if not tok:
        tok = session["csrf"] = secrets.token_urlsafe(32)
    return tok


def _check_csrf():
    sent = request.headers.get(CSRF_HEADER, "")
    if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
        raise ApiError(403, "csrf_failed", "Missing or invalid CSRF token")


def admin_api(view):
    """Gate an async API view: logged-in administrator + CSRF on unsafe methods."""

    @functools.wraps(view)
    async def wrapper(*args, **kwargs):
        if not AuthManager.current_user():
            raise ApiError(401, "unauthorized", "Login required")
        if not AuthManager.is_admin():
            raise ApiError(403, "forbidden", "Administrator role required")
        if request.method not in SAFE_METHODS:
            _check_csrf()
        return await view(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# menu
# ---------------------------------------------------------------------------
GROUP_LABELS = {"content": "محتوا", "media": "رسانه", "site": "سایت و فرانت", "insight": "ارتباط و گزارش‌ها", "system": "سیستم"}
GROUP_ORDER = ["core", "content", "media", "site", "insight", "system"]
PLUGIN_GROUP = {
    "products": "content", "categories": "content", "brands": "content", "projects": "content", "articles": "content",
    "services": "content", "faq": "content", "company": "content", "images": "media",
    "site_settings": "site", "page_builder": "site", "navigation": "site", "i18n": "site", "theme_builder": "site", "public_api": "site",
    "inquiries": "insight", "tracking": "insight", "visits": "insight", "cache": "system",
}
CORE_MENU = [
    {"key": "dashboard", "title": "داشبورد", "icon": "ti-smart-home", "url": "/admin", "order": -100, "group": "core"},
    {"key": "settings", "title": "تنظیمات پایه", "icon": "ti-adjustments", "url": "/admin/settings", "order": 900, "group": "system"},
    {"key": "users", "title": "کاربران", "icon": "ti-users", "url": "/admin/users", "order": 910, "group": "system"},
    {"key": "roles", "title": "نقش‌ها", "icon": "ti-shield-lock", "url": "/admin/roles", "order": 920, "group": "system"},
    {"key": "themes", "title": "قالب‌های قدیمی", "icon": "ti-brush", "url": "/admin/themes", "order": 930, "group": "system"},
    {"key": "plugins", "title": "افزونه‌ها", "icon": "ti-puzzle", "url": "/admin/plugins", "order": 940, "group": "system"},
]


async def build_menu(app) -> list:
    """Sidebar entries grouped for the panel. Cached 30 s (plugin switches / content writes clear the ``admin`` namespace)."""
    cache = app.cache
    hit = cache.get("admin:menu", namespace="admin")
    if hit is not None:
        return [dict(m) for m in hit]
    items = [dict(m) for m in CORE_MENU]
    try:  # one (cached) query for all plugins; a plugin enabled after boot has no routes yet -> not listed until restart
        enabled = await app.core.plugins.enabled_names()
    except Exception:
        enabled = set()
    for name, plugin in app.core.plugins.plugins.items():
        if name not in enabled or name not in app.core.plugins.registered:
            continue
        try:
            entry = plugin.get_admin_entry()
        except Exception:
            continue
        if not entry:
            continue
        items.append({
            "key": name, "title": entry.get("title") or name, "url": entry["url"], "badge": entry.get("badge"),
            "icon": MENU_ICONS.get(name, "ti-puzzle"), "order": entry.get("order", 100), "group": PLUGIN_GROUP.get(name, "content"),
        })
    items.sort(key=lambda e: (GROUP_ORDER.index(e["group"]), e["order"], e["key"]))
    cache.set("admin:menu", items, ttl=30, namespace="admin")
    return [dict(m) for m in items]


async def render_admin(template: str, **ctx):
    """Render a panel page: the Vuexy chrome (menu, user, CSRF meta) is server-side,
    page content is filled client-side from the API."""
    from flask import render_template

    menu = await build_menu(current_app)
    path = request.path.rstrip("/") or "/"
    # section = the menu entry owning this URL (longest prefix) -> breadcrumb in the navbar
    owners = [m for m in menu if path == m["url"] or (m["url"] != "/admin" and path.startswith(m["url"] + "/"))]
    section = max(owners, key=lambda m: len(m["url"])) if owners else None
    return render_template(template, menu=menu, csrf=csrf_token(), user=AuthManager.current_user() or {},
                           group_labels=GROUP_LABELS, section=section, **ctx)


def page_route(bp, rule, endpoint, page, title, script=None):
    """Register a panel page shell (``admin_required`` => 302 to /login). ``page`` is the key the page JS
    registers in ``Admin.pages``; ``script`` is the optional extra file ``app/<script>.js`` that does so."""
    from .decorators import admin_required

    async def view(**kw):
        return await render_admin("admin_ui/page.html", page=page, page_title=title, script=script, params=kw)

    view.__name__ = endpoint
    bp.add_url_rule(rule, endpoint=endpoint, view_func=admin_required(view), methods=["GET"])


def api_route(bp, rule, endpoint, methods=("GET",)):
    """Decorator: register an async view as a JSON admin API route (``admin_api`` gate)."""

    def deco(fn):
        bp.add_url_rule(rule, endpoint=endpoint, view_func=admin_api(fn), methods=list(methods))
        return fn

    return deco


# ---------------------------------------------------------------------------
# core endpoints: auth + me
# ---------------------------------------------------------------------------
def install_admin_assets(app):
    """``asset('app/x.js')`` -> ``/assets/admin-ui/app/x.js?v=<mtime>`` (cache-busting) and long browser caching for the panel files."""
    import os

    root = os.path.join(app.config["ASSETS_DIR"], "admin-ui")

    def asset(rel):
        try:
            v = int(os.path.getmtime(os.path.join(root, rel)))
        except OSError:
            v = 0
        return f"/assets/admin-ui/{rel}?v={v}"

    app.jinja_env.globals["asset"] = asset

    @app.after_request
    def _admin_asset_cache(resp):
        if request.path.startswith("/assets/admin-ui/") and resp.status_code == 200:
            resp.headers["Cache-Control"] = (
                "public, max-age=31536000, immutable" if request.args.get("v") else "public, max-age=2592000")
        return resp


def register_auth_api(app):
    install_admin_assets(app)
    bp = api_blueprint("admin_api_auth")

    async def session_payload():
        from .entity import get_langs

        db = app.core.db

        async def site_settings():
            try:
                return {r["key"]: r["value"] for r in await db.query("SELECT `key`,`value` FROM settings")}
            except Exception:
                return {}

        menu, langs, site = await asyncio.gather(build_menu(app), get_langs(db), site_settings())
        return {
            "user": AuthManager.current_user(),
            "csrf": csrf_token(),
            "menu": menu,
            "languages": langs,
            "site": {"title": site.get("site_title", ""), "locale": "fa", "direction": "rtl"},
        }

    @bp.post("/auth/login")
    async def login():
        data = body()
        username, password = str(data.get("username", "")).strip(), str(data.get("password", ""))
        if not username or not password:
            raise invalid({"username": "نام کاربری و رمز عبور را وارد کنید"})
        wait = LOGIN_LIMIT.check(f"login:{client_ip()}", [(10, 300)])
        if wait:
            raise ApiError(429, "rate_limited", "تلاش‌های ناموفق زیاد؛ کمی بعد دوباره امتحان کنید",
                           headers={"Retry-After": str(wait)})
        if not await app.core.auth.login(username, password):
            raise ApiError(401, "bad_credentials", "نام کاربری یا رمز عبور اشتباه است")
        if not AuthManager.is_admin():
            AuthManager.logout()
            raise ApiError(403, "forbidden", "این بخش فقط برای مدیر سیستم است")
        return reply(await session_payload())

    @bp.post("/auth/logout")
    async def logout():
        AuthManager.logout()
        return reply({"logged_out": True})

    @bp.get("/auth/me")
    @admin_api
    async def me():
        return reply(await session_payload())

    app.register_blueprint(bp)
