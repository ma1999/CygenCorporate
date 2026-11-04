"""Base plugin class all plugins must inherit."""
from flask import render_template


class BasePlugin:
    name = "base"
    # admin panel entry: shown on dashboard when plugin is enabled
    admin_entry = {
        "title": None,      # display name (e.g. "محصولات"); defaults to name
        "icon": "🧩",       # emoji/icon
        "url": None,        # panel path (e.g. "/admin/products"); None = hidden
        "order": 100,       # sort order on dashboard
    }
    # output type: "json" -> API responses returned as JSON; else normal render
    output_type = "html"

    def __init__(self, app, db):
        self.app = app
        self.db = db

    async def is_enabled(self) -> bool:
        row = await self.db.query("SELECT enabled FROM plugins WHERE name=%s", (self.name,), one=True)
        return bool(row and row["enabled"])

    def register(self):
        """Hook routes/blueprints when enabled."""

    def declare_schema(self, schema):
        """Optional: plugin registers its tables/columns here via
        schema.register_table(...) / schema.register_columns(...)."""

    def unregister(self):
        """Cleanup when disabled."""

    def get_admin_entry(self):
        """Return dashboard entry for the admin panel, or None to hide."""
        entry = dict(self.admin_entry)
        if not entry.get("url"):
            return None
        entry.setdefault("title", self.name)
        return entry

    def respond(self, data, template=None, **ctx):
        """Unified output: JSON when output_type == 'json', otherwise template."""
        from flask import jsonify, render_template

        if self.output_type == "json":
            return jsonify(data)
        payload = data if isinstance(data, dict) else {"data": data}
        if not template:
            return payload
        return render_template(template, **{**payload, **ctx})

    # helpers
    async def get_setting(self, key, default=None):
        row = await self.db.query("SELECT `value` FROM settings WHERE `key`=%s", (key,), one=True)
        return row["value"] if row else default

    async def set_setting(self, key, value):
        await self.db.execute(
            "INSERT INTO settings (`key`,`value`) VALUES (%s,%s) "
            "ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",
            (key, str(value)),
        )
