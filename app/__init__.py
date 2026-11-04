import os
from flask import Flask

from .core.database import Database
from .core.plugin_manager import PluginManager
from .core.auth import AuthManager
from .core.routes import register_core_routes
from .core.admin_api import register_auth_api
from .core.cache import init_cache
from .core.entity import install_template_helpers
from .core.public import install_public_api
from .core.revalidate import init_revalidate


def create_app() -> Flask:
    # paths from .env (relative to project root)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    templates_dir = os.path.join(base_dir, os.getenv("TEMPLATES_DIR", "templates"))
    assets_dir = os.path.join(base_dir, os.getenv("ASSETS_DIR", "assets"))

    app = Flask(
        __name__,
        template_folder=templates_dir,
        static_folder=assets_dir,
        static_url_path="/assets",
    )
    app.config["TEMPLATES_DIR"] = templates_dir
    app.config["ASSETS_DIR"] = assets_dir
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret")
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")  # admin API relies on it (plus the CSRF header)

    db = Database()
    auth = AuthManager(db)
    plugins = PluginManager(app, db)
    cache = init_cache(app, default_ttl=int(os.getenv("CACHE_TTL", "300") or 300))

    app.core = type("Core", (), {"db": db, "auth": auth, "plugins": plugins, "cache": cache})()

    # public JSON API infrastructure (errors/CORS/ETag), revalidation webhook,
    # shared Jinja helpers for the entity admin forms
    init_revalidate(app)
    install_public_api(app)
    install_template_helpers(app)

    register_core_routes(app)
    register_auth_api(app)

    # ensure hidden administrator + default settings exist
    with app.app_context():
        import asyncio

        asyncio.run(auth.ensure_admin())

        # 1) sync schema: create DB/tables/columns automatically
        from .core.schema import SchemaManager
        from .core.models import ALL_MODELS

        schema = SchemaManager(db._config)
        for model in ALL_MODELS:
            model.register(schema)
        plugins.schema = schema  # plugins can register their own tables/columns

    # discover plugins, sync schema (incl. plugin tables), then activate
    plugins.discover()

    with app.app_context():
        # let each plugin declare its schema before syncing
        for name, plugin in plugins.plugins.items():
            try:
                if hasattr(plugin, "declare_schema"):
                    plugin.declare_schema(schema)
            except Exception as e:
                app.logger.error(f"Plugin '{name}' declare_schema failed: {e}")

        schema.sync()

        # let plugins perform post-sync migrations (column type changes etc.)
        for name, plugin in plugins.plugins.items():
            try:
                if hasattr(plugin, "maybe_run_migration"):
                    plugin.maybe_run_migration()
            except Exception as e:
                app.logger.error(f"Plugin '{name}' post-sync migration failed: {e}")

    plugins.activate_enabled()

    return app
