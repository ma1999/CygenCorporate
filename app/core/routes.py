from flask import Blueprint, render_template, request, redirect, url_for, session

from .admin_api import admin_api, api_blueprint, body, build_menu, invalid, render_admin, reply
from .auth import AuthManager
from .decorators import admin_required
from .entity import safe_next
from .public import ApiError

DEFAULT_SETTINGS = {
    "site_title": "شرکت من",
    "meta_description": "",
    "meta_keywords": "",
    "active_theme": "default",
    "default_pages": "home,about,contact",
}


ROLE_SECTIONS = ["settings", "users", "pages", "plugins", "products", "seo"]
DASHBOARD_COUNTS = [
    ("products", "محصولات", "ti-package", "/admin/products"),
    ("categories", "دسته‌بندی‌ها", "ti-category", "/admin/categories"),
    ("projects", "پروژه‌ها", "ti-building", "/admin/projects"),
    ("articles", "مقالات", "ti-news", "/admin/articles"),
    ("services", "خدمات", "ti-tool", "/admin/services"),
    ("inquiries", "استعلام‌ها", "ti-mail", "/admin/inquiries"),
]


def register_core_routes(app):
    # create a fresh blueprint on every app creation (fixes re-registration error)
    bp = Blueprint("core", __name__)
    bp.db = app.core.db

    @bp.app_context_processor
    def inject_settings():
        try:
            import asyncio

            coro = bp.db.query("SELECT `key`,`value` FROM settings")
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                rows = asyncio.run(coro)
            else:
                # inside a running loop: schedule and wait via task
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(1) as ex:
                    rows = ex.submit(asyncio.run, coro).result()
            settings = {r["key"]: r["value"] for r in rows}
        except Exception:
            settings = dict(DEFAULT_SETTINGS)
        return {"settings": settings, "current_user": AuthManager.current_user()}

    @bp.route("/")
    async def index():
        return render_template("index.html")

    # ---------- panel pages (Vuexy shells; data comes from /api/admin/*) ----------
    @bp.route("/login")
    async def login():
        if AuthManager.is_admin():
            return redirect(safe_next(request.args.get("next"), "/admin"))
        return render_template("admin_ui/login.html")

    @bp.route("/logout")
    def logout():
        AuthManager.logout()
        return redirect(url_for("core.login"))

    @bp.route("/dashboard")
    def dashboard():
        return redirect("/admin")

    def panel_page(rule, endpoint, page, title):
        async def view():
            return await render_admin("admin_ui/page.html", page=page, page_title=title)

        view.__name__ = endpoint
        bp.add_url_rule(rule, endpoint=endpoint, view_func=admin_required(view))

    panel_page("/admin", "dashboard_page", "dashboard", "داشبورد")
    panel_page("/admin/settings", "admin_settings", "settings", "تنظیمات پایه")
    panel_page("/admin/users", "admin_users", "users", "کاربران")
    panel_page("/admin/roles", "admin_roles", "roles", "نقش‌ها")
    panel_page("/admin/themes", "admin_themes", "themes", "قالب‌های قدیمی")
    panel_page("/admin/plugins", "admin_plugins", "plugins", "افزونه‌ها")

    # ---------- admin API: core ----------
    api = api_blueprint("admin_api_core")

    async def write(sql, params=()):
        # Database.execute swallows errors and returns -1: surface that as 503 instead of a fake success
        if await bp.db.execute(sql, params) == -1:
            raise ApiError(503, "unavailable", "Database write failed")

    async def settings_map():
        rows = await bp.db.query("SELECT `key`,`value` FROM settings")
        return {**DEFAULT_SETTINGS, **{r["key"]: r["value"] for r in rows}}

    @api.get("/dashboard")
    @admin_api
    async def api_dashboard():
        cache = app.cache
        existing = cache.get("admin:tables", namespace="admin")
        if existing is None:  # which dashboard tables exist (changes only on schema sync): cached 10 min
            rows = await bp.db.query("SELECT table_name AS t FROM information_schema.tables WHERE table_schema=DATABASE()")
            existing = {r["t"] for r in rows}
            cache.set("admin:tables", existing, ttl=600, namespace="admin")
        enabled = await app.core.plugins.enabled_names()   # no tiles for disabled plugins (table name == plugin name here)
        wanted = [d for d in DASHBOARD_COUNTS if d[0] in existing and d[0] in enabled]
        counts = {}
        if wanted:  # one UNION query instead of one COUNT per table
            sql = " UNION ALL ".join(f"SELECT '{t}' AS k, COUNT(*) AS c FROM `{t}`" for t, *_ in wanted)
            counts = {r["k"]: r["c"] for r in (await bp.db.query(sql) or [])}
        stats = [{"key": t, "title": title, "icon": icon, "url": url, "count": counts.get(t, 0)} for t, title, icon, url in wanted]
        return reply({"stats": stats, "menu": await build_menu(app)})

    @api.get("/settings")
    @admin_api
    async def api_settings_get():
        return reply(await settings_map())

    @api.put("/settings")
    @admin_api
    async def api_settings_put():
        data = body()
        for key in DEFAULT_SETTINGS:
            if key in data:
                val = str(data[key] if data[key] is not None else "")[:2000]
                await write(
                    "INSERT INTO settings (`key`,`value`) VALUES (%s,%s) ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",
                    (key, val),
                )
        return reply(await settings_map())

    @api.get("/users")
    @admin_api
    async def api_users():
        rows = await bp.db.query("SELECT id, username, role, created_at FROM users WHERE is_hidden=0 ORDER BY id")
        return reply(rows)

    @api.post("/users")
    @admin_api
    async def api_users_create():
        from .auth import hash_password

        data = body()
        username, password = str(data.get("username", "")).strip(), str(data.get("password", ""))
        role = str(data.get("role", "editor")).strip() or "editor"
        errors = {}
        if not username or len(username) > 60:
            errors["username"] = "نام کاربری الزامی است (حداکثر ۶۰ نویسه)"
        if len(password) < 6:
            errors["password"] = "رمز عبور حداقل ۶ نویسه باشد"
        if errors:
            raise invalid(errors)
        if await bp.db.query("SELECT id FROM users WHERE username=%s", (username,), one=True):
            raise invalid({"username": "این نام کاربری قبلاً ثبت شده است"})
        await write(
            "INSERT INTO users (username, password_hash, role) VALUES (%s,%s,%s)", (username, hash_password(password), role)
        )
        return reply({"username": username, "role": role}, 201)

    @api.delete("/users/<int:uid>")
    @admin_api
    async def api_users_delete(uid):
        if uid == session.get("uid"):
            raise ApiError(409, "conflict", "نمی‌توانید حساب خودتان را حذف کنید")
        row = await bp.db.query("SELECT id FROM users WHERE id=%s AND role<>'administrator'", (uid,), one=True)
        if not row:
            raise ApiError(404, "not_found", "کاربر یافت نشد یا مدیر سیستم است")
        await write("DELETE FROM users WHERE id=%s", (uid,))
        return reply({"deleted": uid})

    @api.get("/roles")
    @admin_api
    async def api_roles():
        import json

        rows = await bp.db.query("SELECT * FROM roles")
        for r in rows:
            try:
                r["permissions"] = json.loads(r.get("permissions") or "{}")
            except ValueError:
                r["permissions"] = {}
        return reply({"roles": rows, "sections": ROLE_SECTIONS})

    @api.put("/roles")
    @admin_api
    async def api_roles_save():
        import json

        data = body()
        name = str(data.get("name", "")).strip()
        if not name or len(name) > 60:
            raise invalid({"name": "نام نقش الزامی است"})
        perms = {s: 1 for s in ROLE_SECTIONS if (data.get("permissions") or {}).get(s)}
        await write(
            "INSERT INTO roles (name, permissions) VALUES (%s,%s) ON DUPLICATE KEY UPDATE permissions=VALUES(permissions)",
            (name, json.dumps(perms)),
        )
        return reply({"name": name, "permissions": perms})

    @api.get("/themes")
    @admin_api
    async def api_themes():
        import os

        base = os.path.join(app.config["TEMPLATES_DIR"], "themes")
        themes = sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))) if os.path.isdir(base) else []
        return reply({"themes": themes, "active": (await settings_map()).get("active_theme")})

    @api.post("/themes/activate")
    @admin_api
    async def api_themes_activate():
        import os

        theme = str(body().get("theme", "default"))
        base = os.path.join(app.config["TEMPLATES_DIR"], "themes")
        if theme != "default" and not os.path.isdir(os.path.join(base, os.path.basename(theme))):
            raise invalid({"theme": "قالب یافت نشد"})
        await write(
            "INSERT INTO settings (`key`,`value`) VALUES ('active_theme',%s) ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",
            (theme,),
        )
        return reply({"active": theme})

    @api.get("/plugins")
    @admin_api
    async def api_plugins():
        return reply(await app.core.plugins.list_plugins())

    @api.post("/plugins/toggle")
    @admin_api
    async def api_plugins_toggle():
        data = body()
        name = str(data.get("name", ""))
        if name not in app.core.plugins.plugins:
            raise ApiError(404, "not_found", "افزونه یافت نشد")
        await app.core.plugins.set_enabled(name, bool(data.get("enabled")))
        app.cache.invalidate_namespace("admin")
        return reply({"name": name, "enabled": bool(data.get("enabled"))})

    app.register_blueprint(api)

    app.register_blueprint(bp)
