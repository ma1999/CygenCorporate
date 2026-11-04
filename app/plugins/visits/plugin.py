"""visits plugin — optional page-view tracking for the headless frontend (spec 6.16).

The old ``tracking`` plugin only sees requests that reach Flask, i.e. never the
pages Next.js renders. The frontend can report a view with
``POST /api/public/track`` — but only when the owner switched
``track_enabled`` on in /admin/site-settings (tab "پیشرفته"); the default is
OFF (GA/GTM only) and then the endpoint accepts and discards the call (204).

Privacy: no raw IP is stored (a salted hash only); bots are ignored;
rows older than ``TRACK_RETENTION_DAYS`` (default 180) are pruned.
Admin report: ``/admin/frontend-visits``.
"""
from __future__ import annotations

import hashlib
import os
import random
import re

from flask import Blueprint, Response, current_app, request

from app.core import content as C
from app.core import migrate
from app.core.base_plugin import BasePlugin
from app.core.admin_api import api_route, page_route, reply
from app.core.public import ApiError, RateLimiter, client_ip, json_body, public_blueprint, validation_failed

LIMITER = RateLimiter()
BOT_RE = re.compile(r"bot|crawl|spider|slurp|headless|curl/|wget/|python-requests|facebookexternalhit|preview", re.I)
VISITOR_RE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")


def _enabled_cache_key():
    return "public_api:track_enabled"


class Plugin(BasePlugin):
    name = "visits"
    auto_enable = True
    admin_entry = {"title": "بازدید صفحات فرانت", "icon": "📈", "url": "/admin/frontend-visits", "order": 8}
    output_type = "json"

    def declare_schema(self, schema):
        schema.register_table("frontend_pageviews", {
            "id": "BIGINT AUTO_INCREMENT PRIMARY KEY",
            "visitor": "VARCHAR(64) NOT NULL",
            "path": "VARCHAR(500) NOT NULL",
            "referrer": "VARCHAR(500) NULL",
            "locale": "VARCHAR(8) NULL",
            "ip_hash": "CHAR(16) NULL",
            "user_agent": "VARCHAR(300) NULL",
            "created_at": "DATETIME NOT NULL",
        })

    def maybe_run_migration(self):
        def go(cur):
            migrate.ensure_index(cur, "frontend_pageviews", "idx_pv_created", "created_at")
            migrate.ensure_index(cur, "frontend_pageviews", "idx_pv_path", "path(191), created_at")
        migrate.run(self.db, go)

    # ------------------------------------------------------------------ helpers
    async def _enabled(self, db) -> bool:
        cache = current_app.cache
        hit = cache.get(_enabled_cache_key(), namespace="public_api")
        if hit is not None:
            return hit == "1"
        row = await db.fetch("SELECT value FROM site_settings WHERE skey='track_enabled'", one=True)
        flag = "1" if row and row["value"] == "1" else "0"
        cache.set(_enabled_cache_key(), flag, ttl=30, namespace="public_api")
        return flag == "1"

    @staticmethod
    def _hash_ip(ip: str) -> str:
        salt = (current_app.secret_key or "") if isinstance(current_app.secret_key, str) else ""
        return hashlib.sha256(f"{salt}|{ip}".encode()).hexdigest()[:16]

    @staticmethod
    def _retention_days() -> int:
        try:
            return max(1, int(os.getenv("TRACK_RETENTION_DAYS", "180") or 180))
        except ValueError:
            return 180

    # ------------------------------------------------------------------ routes
    def register(self):
        db = self.db
        pub = public_blueprint("public_visits")

        @pub.route("/track", methods=["POST"])
        async def track():
            wait = LIMITER.check(f"track:{client_ip()}", [(240, 60)])
            if wait:
                raise ApiError(429, "rate_limited", "Too many requests", headers={"Retry-After": str(wait)})
            data = json_body(8 * 1024)
            errors = {}
            path = data.get("path")
            if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or len(path) > 500 or re.search(r"[\s\x00-\x1f]", path):
                errors["path"] = {"code": "required" if path in (None, "") else "invalid_value"}
            ref = data.get("referrer")
            if ref not in (None, "") and (not isinstance(ref, str) or len(ref) > 500):
                errors["referrer"] = {"code": "invalid_value"}
            locale = data.get("locale")
            if locale not in (None, "", "fa", "en"):
                errors["locale"] = {"code": "invalid_value"}
            vid = data.get("visitor_id")
            if vid not in (None, "") and (not isinstance(vid, str) or not VISITOR_RE.match(vid)):
                errors["visitor_id"] = {"code": "invalid_value"}
            if errors:
                raise validation_failed(errors)
            ua = (request.headers.get("User-Agent") or "")[:300]
            if not await self._enabled(db) or BOT_RE.search(ua):
                return Response(status=204)               # accepted, deliberately not stored
            ip_hash = self._hash_ip(client_ip())
            row = (vid or ip_hash, path, (ref or None), locale or None, ip_hash, ua or None)

            def go(tx):
                tx.run(
                    "INSERT INTO frontend_pageviews (visitor, path, referrer, locale, ip_hash, user_agent, created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP())", row)
                if random.random() < 0.01:                # cheap retention without a scheduler
                    tx.run("DELETE FROM frontend_pageviews WHERE created_at < UTC_TIMESTAMP() - INTERVAL %s DAY", (self._retention_days(),))

            await db.transaction(go)
            return Response(status=204)

        self.app.register_blueprint(pub)

        bp = Blueprint("plugin_visits", __name__)

        page_route(bp, "/admin/frontend-visits", "report", "visits", "بازدید صفحات فرانت", "pages-system")

        @api_route(bp, "/api/admin/frontend-visits", "api_report")
        async def api_report():
            try:
                days = min(90, max(1, int(request.args.get("days", 14))))
            except ValueError:
                days = 14
            enabled = await self._enabled(db)
            since = "UTC_TIMESTAMP() - INTERVAL %s DAY"
            daily = await db.fetch(
                f"SELECT DATE(created_at) AS d, COUNT(*) AS views, COUNT(DISTINCT visitor) AS visitors FROM frontend_pageviews "
                f"WHERE created_at >= {since} GROUP BY DATE(created_at) ORDER BY d DESC", (days,))
            totals = await db.fetch(
                f"SELECT COUNT(*) AS views, COUNT(DISTINCT visitor) AS visitors FROM frontend_pageviews WHERE created_at >= {since}", (days,), one=True)
            top_paths = await db.fetch(
                f"SELECT path, COUNT(*) AS views FROM frontend_pageviews WHERE created_at >= {since} GROUP BY path ORDER BY views DESC LIMIT 20", (days,))
            top_refs = await db.fetch(
                f"SELECT referrer, COUNT(*) AS views FROM frontend_pageviews WHERE created_at >= {since} AND referrer IS NOT NULL "
                f"GROUP BY referrer ORDER BY views DESC LIMIT 10", (days,))
            return reply({
                "enabled": enabled, "days": days, "daily": daily, "totals": totals,
                "top_paths": top_paths, "top_refs": top_refs, "retention": self._retention_days(),
            })

        self.app.register_blueprint(bp)
