"""Cache plugin — مدیریت کش پلاگین‌ها از پنل ادمین.

- آمار hit/miss و تعداد کلیدها برای هر namespace (پلاگین)
- پاک کردن کش یک پلاگین یا کل کش
- تنظیم TTL پیش‌فرض
"""
from flask import Blueprint

from app.core.admin_api import api_route, body, invalid, page_route, reply
from app.core.base_plugin import BasePlugin


class Plugin(BasePlugin):
    name = "cache"
    # enabled by default on a fresh database (the headless frontend needs it);
    # an existing "plugins" row (enabled or not) is never touched
    auto_enable = True

    admin_entry = {
        "title": "کش",
        "icon": "⚡",
        "url": "/admin/cache",
        "order": 5,
    }
    output_type = "html"

    def register(self):
        bp = Blueprint("plugin_cache", __name__)
        cache = self.app.cache

        def snapshot():
            return {"stats": cache.stats(), "total_keys": cache.size(), "ttl": cache.default_ttl}

        page_route(bp, "/admin/cache", "dashboard", "cache", "کش", "pages-system")

        @api_route(bp, "/api/admin/cache", "api_stats")
        async def api_stats():
            return reply(snapshot())

        @api_route(bp, "/api/admin/cache/clear", "api_clear_all", ["POST"])
        async def api_clear_all():
            cache.clear()
            return reply(snapshot())

        @api_route(bp, "/api/admin/cache/clear/<namespace>", "api_clear_ns", ["POST"])
        async def api_clear_ns(namespace):
            cache.invalidate_namespace(namespace)
            return reply(snapshot())

        @api_route(bp, "/api/admin/cache/ttl", "api_set_ttl", ["PUT"])
        async def api_set_ttl():
            try:
                ttl = int(body().get("ttl"))
            except (TypeError, ValueError):
                raise invalid({"ttl": "TTL باید عدد (ثانیه) باشد"})
            if ttl < 10:
                raise invalid({"ttl": "حداقل ۱۰ ثانیه"})
            cache.default_ttl = ttl
            await self.set_setting("cache_ttl", ttl)
            return reply(snapshot())

        self.app.register_blueprint(bp)

    def unregister(self):
        pass
