import asyncio
import importlib
import os
import threading

from flask import abort, current_app, request


class PluginManager:
    """Discovers plugins in app/plugins/<name>/ with plugin.py exposing Plugin class."""

    def __init__(self, app, db):
        self.app = app
        self.db = db
        self.plugins = {}  # name -> instance
        self.bp_owner = {}      # blueprint name -> plugin name (filled when a plugin registers)
        self.registered = set()  # plugins whose register() ran in this process
        self._providers = {}     # plugin -> {kind: {key: fn}} public data providers it added (search/home/sitemap)
        self._parked = {}        # plugin -> providers removed while the plugin is disabled
        self._lock = threading.RLock()
        self._last_enabled = None  # last successfully read set of enabled plugin names
        self._install_gate()

    # ---- enabled/disabled gate -------------------------------------------------
    async def enabled_names(self) -> set:
        """Enabled plugin names (``plugins`` table), cached 30 s in the ``admin`` namespace (cleared by ``set_enabled``)."""
        cache = getattr(self.app, "cache", None)
        hit = cache.get("admin:enabled", namespace="admin") if cache is not None else None
        if hit is not None:
            return hit
        try:
            rows = await self.db.fetch("SELECT name, enabled FROM plugins")   # strict: a DB error must not look like "no plugin is enabled"
        except Exception:
            if self._last_enabled is not None:
                return set(self._last_enabled)   # DB hiccup: keep serving with the last known switches (not cached)
            raise
        names = {r["name"] for r in rows if r["enabled"]}
        self._last_enabled = set(names)
        if cache is not None:
            cache.set("admin:enabled", names, ttl=30, namespace="admin")
        return names

    def _install_gate(self):
        """Routes of a disabled plugin (admin pages, admin API, public API) answer 404 immediately, without a restart."""
        from .public import ApiError

        @self.app.before_request
        async def _plugin_gate():
            owner = self.bp_owner.get(request.blueprint) if request.blueprint else None
            if not owner:
                return None
            try:
                enabled = await self.enabled_names()
            except Exception:  # never lock the admin out because the DB hiccuped
                return None
            if owner in enabled:
                return None
            if request.path.startswith("/api/"):
                raise ApiError(404, "plugin_disabled", "این افزونه غیرفعال است")
            abort(404)

    def _register(self, name, plugin):
        """Run ``plugin.register()`` and remember which blueprints / providers it added.

        Flask refuses to add routes once the first request was served. A plugin enabled at runtime must work without a
        restart, so the "first request served" flag is lifted for the duration of the registration (the URL map is
        thread-safe for additions; the registration itself is serialised by a lock)."""
        app = self.app
        with self._lock:
            before = set(app.blueprints)
            prov_before = {k: dict(v) for k, v in getattr(app, "public_providers", {}).items()}
            late = getattr(app, "_got_first_request", False)
            if late:
                app._got_first_request = False
            try:
                with app.app_context():
                    plugin.register()
            finally:
                if late:
                    app._got_first_request = True
            for bp in set(app.blueprints) - before:
                self.bp_owner[bp] = name
            added = {}
            for kind, d in getattr(app, "public_providers", {}).items():
                new = {k: fn for k, fn in d.items() if prov_before.get(kind, {}).get(k) is not fn}
                if new:
                    added[kind] = new
            self._providers[name] = added
            self.registered.add(name)

    def _park_providers(self, name):
        """Disabled plugin: stop contributing to /search, /home and the sitemap."""
        for kind, items in self._providers.get(name, {}).items():
            for key in items:
                self.app.public_providers.get(kind, {}).pop(key, None)

    def _restore_providers(self, name):
        for kind, items in self._providers.get(name, {}).items():
            self.app.public_providers.setdefault(kind, {}).update(items)

    def discover(self):
        base = os.path.join(os.path.dirname(__file__), "..", "plugins")
        for name in sorted(os.listdir(base)):
            path = os.path.join(base, name)
            if not os.path.isdir(path) or name.startswith("_"):
                continue
            if not os.path.exists(os.path.join(path, "plugin.py")):
                continue
            try:
                module = importlib.import_module(f"app.plugins.{name}.plugin")
                instance = module.Plugin(self.app, self.db)
                self.plugins[name] = instance
            except Exception as e:
                self.app.logger.error(f"Plugin '{name}' failed to load: {e}")

    def ensure_defaults(self):
        """Plugins with ``auto_enable = True`` get an enabled ``plugins`` row
        the first time they are discovered. An existing row (enabled or not)
        is never touched, so an admin can still switch them off."""
        import asyncio

        for name, plugin in self.plugins.items():
            if not getattr(plugin, "auto_enable", False):
                continue
            try:
                row = asyncio.run(self.db.query("SELECT enabled FROM plugins WHERE name=%s", (name,), one=True))
                if row is None:
                    asyncio.run(self.db.execute(
                        "INSERT IGNORE INTO plugins (name, enabled) VALUES (%s, 1)", (name,)
                    ))
            except Exception as e:
                self.app.logger.error(f"Plugin '{name}' default enable failed: {e}")

    def activate_enabled(self):
        import asyncio

        self.ensure_defaults()
        with self.app.app_context():
            for name, plugin in self.plugins.items():
                try:
                    if asyncio.run(plugin.is_enabled()):
                        self._register(name, plugin)
                except Exception as e:
                    self.app.logger.error(f"Plugin '{name}' activation failed: {e}")

    async def set_enabled(self, name: str, enabled: bool):
        await self.db.execute(
            "INSERT INTO plugins (name, enabled) VALUES (%s,%s) "
            "ON DUPLICATE KEY UPDATE enabled=VALUES(enabled)",
            (name, int(enabled)),
        )
        try:
            self.app.cache.invalidate_namespace("admin")   # gate + sidebar pick the change up at once
        except Exception:
            pass
        plugin = self.plugins.get(name)
        if plugin:
            try:
                if enabled:
                    if name not in self.registered:   # first enable in this process: build routes now (no restart)
                        await asyncio.to_thread(self._register, name, plugin)   # off the event loop: register() may use asyncio.run
                    else:
                        self._restore_providers(name)
                else:
                    self._park_providers(name)
                    plugin.unregister()
            except Exception as e:
                self.app.logger.error(f"Plugin '{name}' toggle failed: {e}")
        # the public `site.plugins` map, menus and every cached page changed: clear the API cache and the frontend's
        try:
            self.app.revalidate.notify("*", "site")
        except Exception:
            pass

    async def list_plugins(self):
        rows = {r["name"]: r["enabled"] for r in await self.db.query("SELECT name, enabled FROM plugins")}
        return [
            {"name": name, "enabled": bool(rows.get(name, False)), "loaded": name in self.plugins,
             # only true if registering the routes at runtime failed (see the server log)
             "needs_restart": bool(rows.get(name, False)) and name not in self.registered}
            for name in self.plugins
        ]
