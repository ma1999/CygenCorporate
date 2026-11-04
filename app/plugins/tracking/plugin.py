"""Visitor tracking plugin — captures every request/page load.

For each HTTP request the plugin records:
- referrer (origin) and target URL
- response status code
- IP address (REMOTE_ADDR, X-Forwarded-For, X-Real-IP) in 3 columns
- full User-Agent + parsed browser type/version/device type
- country of the *real* client IP via MaxMind GeoLite2 (country + city DB)
- logged-in user id (if any)
- persistent AT-sitename cookie key (issued on first visit)

Schema (auto-created):
- tracking_visitors:   one row per visitor keyed by AT cookie
- tracking_requests:   one row per HTTP request, linked to the visitor
"""
from __future__ import annotations

import fnmatch
import queue
import re
import secrets
import threading
from pathlib import Path

from flask import request, redirect, url_for
from user_agents import parse as ua_parse

from app.core.base_plugin import BasePlugin

try:
    import maxminddb  # type: ignore
except Exception:  # pragma: no cover - graceful degradation
    maxminddb = None


PLUGIN_DIR = Path(__file__).resolve().parent
COUNTRY_DB = PLUGIN_DIR / "GeoLite2-Country.mmdb"
CITY_DB = PLUGIN_DIR / "GeoLite2-City.mmdb"
COOKIE_PREFIX = "AT-"  # AT-sitename (site name is taken from settings.site_title)

# PluginCache namespaces — see app/core/cache.py
GEO_NS = "tracking_geo"          # IP -> {country_code, country_name, city}
VISITOR_NS = "tracking_visitor"  # cookie pair -> visitor_id
ADMIN_NS = "tracking_admin"      # API response cache (dashboard, visitors, ...)
GEO_TTL = 86400                  # 1 day (ISP-assigned IPs can change)
VISITOR_TTL = 3600               # 1 hour (long enough for a typical session)
ADMIN_TTL = 86400                   # short — invalidated on every new write
MAX_VISITOR_CACHE_ENTRIES = 50000 # memory bound for the visitor namespace


def _visitor_cache_key(cookie_name: str, cookie_value: str) -> str:
    """Build a namespaced cache key for visitor lookups.

    Format: ``tracking_visitor:<cookie_name>=<cookie_value>`` — matches the
    PluginCache convention (namespace is the first segment separated by ``:``)
    so stats() reports it correctly.
    """
    return f"{VISITOR_NS}:{cookie_name}={cookie_value}"


# Cache keys for the admin/API responses. Keeping them as module-level
# helpers so the worker (which invalidates them) and the API handlers
# (which read/write them) use the exact same string.
def _admin_dashboard_key() -> str:
    return f"{ADMIN_NS}:dashboard"


def _admin_visitors_key(page: int) -> str:
    return f"{ADMIN_NS}:visitors:p{page}"


def _admin_visitor_detail_key(vid: int) -> str:
    return f"{ADMIN_NS}:visitor:{vid}"


# Internal hooks so the worker thread (which has no `self`) can still find
# the running plugin instance and its app/cache. Populated by ``__init__``.
_plugin_registry: list = []


def _get_plugin_for_worker():
    """Return the running Plugin instance (or None if not loaded yet)."""
    return _plugin_registry[0] if _plugin_registry else None


def _invalidate_admin_cache() -> None:
    """Drop every cached admin response. Called from the worker thread
    after each successful write so the next API call re-reads fresh data
    instead of returning stale numbers."""
    p = _get_plugin_for_worker()
    if p is None:
        return
    c = p._cache
    if c is None:
        return
    try:
        c.invalidate_namespace(ADMIN_NS)
    except Exception as e:
        p.app.logger.error(f"[tracking] admin cache invalidate failed: {e}")


def _refresh_admin_cache_dashboard(visitor_id: int, request_row: dict) -> None:
    """Write-through: update the cached dashboard payload in place so the
    next API call returns fresh data without hitting MySQL.

    The cached payload is a dict with keys: total_requests, total_visitors,
    unique_ips, by_country, by_device, by_browser, recent[]. We:
      1. bump total_requests by 1
      2. (only for a brand-new visitor) bump total_visitors by 1 and the
         per-country / per-device / per-browser counts if applicable
      3. prepend the new request to recent[] and trim to 50 rows
    """
    p = _get_plugin_for_worker()
    if p is None or p._cache is None:
        return
    cache = p._cache
    try:
        existing = cache.get(_admin_dashboard_key(), namespace=ADMIN_NS)
        if not existing:
            # nothing cached yet — the next API call will rebuild from DB
            return
        # 1) request counter
        existing["total_requests"] = (existing.get("total_requests") or 0) + 1
        # 2) country bucket
        cc = request_row.get("country_code")
        if cc:
            found = False
            for row in existing.get("by_country") or []:
                if row.get("country_code") == cc:
                    row["hits"] = (row.get("hits") or 0) + 1
                    found = True
                    break
            if not found:
                existing.setdefault("by_country", []).insert(0, {
                    "country_code": cc,
                    "country_name": request_row.get("country_name") or cc,
                    "hits": 1,
                })
                # cap at 10
                existing["by_country"] = existing["by_country"][:10]
        # 3) device bucket
        dev = request_row.get("device_type")
        if dev:
            for row in existing.get("by_device") or []:
                if row.get("device_type") == dev:
                    row["hits"] = (row.get("hits") or 0) + 1
                    break
            else:
                existing.setdefault("by_device", []).append(
                    {"device_type": dev, "hits": 1}
                )
        # 4) browser bucket
        bf = request_row.get("browser_family")
        if bf:
            for row in existing.get("by_browser") or []:
                if row.get("browser_family") == bf:
                    row["hits"] = (row.get("hits") or 0) + 1
                    break
            else:
                existing.setdefault("by_browser", []).append(
                    {"browser_family": bf, "hits": 1}
                )
        # 5) prepend the new request to the recent list and trim
        recent = existing.setdefault("recent", [])
        recent.insert(0, request_row)
        del recent[50:]
        # 6) write back (preserve TTL window by reusing the same key)
        cache.set(
            _admin_dashboard_key(),
            existing,
            ttl=ADMIN_TTL,
            namespace=ADMIN_NS,
        )
    except Exception as e:
        p.app.logger.error(f"[tracking] admin cache refresh failed: {e}")


def _refresh_admin_cache_visitors(visitor_id: int, visitor_row: dict) -> None:
    """Write-through: invalidate visitors list (we don't know the visitor's
    position in the paginated list without re-querying) and refresh the
    per-visitor detail cache with the fresh row so /api/admin/tracking/
    visitor/<id> serves the latest data immediately."""
    p = _get_plugin_for_worker()
    if p is None or p._cache is None:
        return
    cache = p._cache
    try:
        # drop the paginated lists (their order depends on last_seen etc.)
        # so the next call rebuilds them; the visitor detail itself is
        # updated in place.
        keys_to_drop = [k for k in cache._store if k.startswith(ADMIN_NS + ":visitors:")]
        for k in keys_to_drop:
            cache.invalidate(k)
        # refresh visitor detail
        cache.set(
            _admin_visitor_detail_key(visitor_id),
            {"visitor": visitor_row, "requests": []},
            ttl=ADMIN_TTL,
            namespace=ADMIN_NS,
        )
    except Exception as e:
        p.app.logger.error(f"[tracking] admin cache visitors refresh failed: {e}")

# --------------------------------------------------------------------------- #
# Default exclude rules (used when the settings key has no value yet)
# --------------------------------------------------------------------------- #
DEFAULT_EXCLUDES = {
    # path globs (request.path + "?" + query when relevant) — one per line
    # NOTE: admin pages and admin API endpoints are excluded so the admin
    # dashboard refreshes don't trigger tracking writes that would
    # invalidate the admin response cache in an endless loop.
    "path_patterns": (
        "/assets/*\n"
        "/static/*\n"
        "/uploads/*\n"
        "/favicon.ico\n"
        "/robots.txt\n"
        "/sitemap*.xml\n"
        "*/.well-known\n"
        "*/.well-known/*\n"
        "/*well-known*\n"
        "/admin/plugins*\n"
        "/admin/tracking\n"
        "/admin/tracking/*\n"
        "/api/admin/*\n"
        "/api/public/*"
    ),
    # HTTP methods to skip (one per line, upper-case: GET, POST, ...)
    "method_patterns": "",
    # status code filter:
    #   "all"       — log everything (default)
    #   "success"   — only 2xx/3xx
    #   "errors"    — only 4xx/5xx
    "status_filter": "all",
    # skip rows whose User-Agent matches any of these glob patterns (bots)
    "ua_patterns": (
        "*bot*\n"
        "*crawl*\n"
        "*spider*\n"
        "*slurp*\n"
        "*facebookexternalhit*\n"
        "*headlesschrome*\n"
        "*python-requests*\n"
        "*curl/*\n"
        "*wget/*"
    ),
    # skip bots identified by user-agents (mobile/tablet/pc/bot detection)
    "ignore_bots": "1",
}

SETTING_KEYS = {
    "paths":   "tracking_exclude_paths",
    "methods": "tracking_exclude_methods",
    "status":  "tracking_status_filter",
    "uas":     "tracking_exclude_uas",
    "bots":    "tracking_ignore_bots",
}

# Map between short field names (used in admin form + cache keys) and the
# longer DEFAULT_EXCLUDES keys (raw defaults shown in the settings UI).
FIELD_TO_DEFAULT = {
    "paths":   "path_patterns",
    "methods": "method_patterns",
    "status":  "status_filter",
    "uas":     "ua_patterns",
    "bots":    "ignore_bots",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _slugify(value: str, fallback: str = "site") -> str:
    """Convert 'شرکت من' / 'My Site 1!' to 'site-1' style slug."""
    if not value:
        return fallback
    # transliterate Persian/Arabic digits and a few common letters
    fa_map = {
        "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
        "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
        "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    }
    s = str(value)
    for k, v in fa_map.items():
        s = s.replace(k, v)
    s = s.lower()
    # non-ASCII -> drop (kept readable slug; Persian turns into "site")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or fallback


def _client_ips() -> dict:
    """Return 3 candidate client IPs parsed from common proxy headers."""
    xff = request.headers.get("X-Forwarded-For", "") or ""
    first_xff = xff.split(",")[0].strip() if xff else None
    return {
        "remote": request.remote_addr or None,
        "forwarded": first_xff or None,
        "real": request.headers.get("X-Real-IP") or None,
    }


def _device_type(ua) -> str:
    if ua.is_mobile:
        return "mobile"
    if ua.is_tablet:
        return "tablet"
    if ua.is_pc:
        return "pc"
    if ua.is_bot:
        return "bot"
    return "other"


def _split_lines(value: str | None) -> list[str]:
    """Split a multi-line settings value into clean patterns."""
    if not value:
        return []
    return [ln.strip() for ln in str(value).splitlines() if ln.strip()]


def _match_any(target: str, patterns: list[str]) -> bool:
    """Return True if `target` matches any of the glob `patterns` (or regex if
    the pattern starts with ``re:``)."""
    for pat in patterns:
        if pat.startswith("re:"):
            try:
                if re.search(pat[3:], target, re.IGNORECASE):
                    return True
            except re.error:
                continue
        elif fnmatch.fnmatchcase(target.lower(), pat.lower()):
            return True
    return False


# --------------------------------------------------------------------------- #
# Jalali datetime helper
# --------------------------------------------------------------------------- #
def _now_jalali() -> str:
    """Return the current local time formatted as a Persian (Jalali) string.

    Stored format is purely numeric: ``1405/05/05 15:45:23``. Date and time
    parts are separated by ``/`` and a single space so the value remains
    easy to read in logs while still being sortable.

    Falls back to ISO-8601 Gregorian if jdatetime is not installed.
    """
    try:
        import jdatetime

        now = jdatetime.datetime.now()
        # zero-pad month/day so the format is stable (05 vs 5)
        return now.strftime("%Y/%m/%d %H:%M:%S")
    except Exception:
        # fallback so the plugin still works without jdatetime
        from datetime import datetime
        return datetime.now().strftime("%Y/%m/%d %H:%M:%S")


def format_jalali(value, *, with_time: bool = True) -> str:
    """Pretty-print a Jalali datetime string written by :func:`_now_jalali`.

    Accepts strings like ``"1405/05/05 15:45:23"`` or ``"1405-05-05 15:45:23"``
    (legacy format) and returns a purely numeric display:
    ``1405/05/05 - 15:45:23``. Returns ``"—"`` for empty values.
    """
    if not value:
        return "—"
    try:
        s = str(value).strip()
        if " " in s:
            date_part, time_part = s.split(" ", 1)
        else:
            date_part, time_part = s, ""
        # accept both `-` and `/` as separators
        sep = "/" if "/" in date_part else "-"
        y, m, d = (int(x) for x in date_part.split(sep))
        date_str = f"{y:04d}{sep}{m:02d}{sep}{d:02d}"
        if with_time and time_part:
            return f"{date_str} - {time_part}"
        return date_str
    except Exception:
        return str(value)


# --------------------------------------------------------------------------- #
# Plugin
# --------------------------------------------------------------------------- #
class Plugin(BasePlugin):
    name = "tracking"

    admin_entry = {
        "title": "آمار بازدیدها",
        "icon": "📊",
        "url": "/admin/tracking",
        "order": 5,
    }
    output_type = "html"

    # shared by hooks + admin views
    _geo_country = None
    _geo_city = None

    # in-memory caches (populated lazily)
    _cookie_name_cache: str | None = None   # AT-<slug>
    # Visitor-id cache lives in app.cache (PluginCache) so it can be
    # inspected, invalidated, and shared with other plugins in the future.
    # We keep a local counter to enforce a memory bound.
    _visitor_id_cache_size: int = 0

    # background write queue: keeps the response path free of DB writes
    _write_queue: "queue.Queue | None" = None
    _write_worker_started: bool = False

    def __init__(self, app, db):
        super().__init__(app, db)
        # register globally so the worker thread can find this instance
        # (it has no `self`). Only one tracking plugin ever runs.
        if not _plugin_registry:
            _plugin_registry.append(self)
        self._registered = False
        # exclude-rule cache: populated lazily on first request
        self._rules_cache: dict | None = None
        # pre-load GeoIP handles once (file IO + mmdb parse happens here,
        # not on every request)
        self._load_geoip()
        # register Jinja filter once per app instance
        if not getattr(app, "_tracking_jalali_filter", False):
            try:
                app.jinja_env.filters["jalali"] = (
                    lambda v, with_time=True: format_jalali(v, with_time=with_time)
                )
                app._tracking_jalali_filter = True
            except Exception as e:
                self.app.logger.error(
                    f"[tracking] failed to register jinja filter: {e}"
                )
        # start the background DB writer once per plugin instance
        self._start_write_worker()

    @property
    def _cache(self):
        return self.app.cache

    def _migrate_timestamps(self) -> None:
        """Convert the legacy TIMESTAMP columns to VARCHAR(32) so the app
        can store Jalali strings. Safe to run repeatedly. Called from the
        main app bootstrap after schema sync (NOT from a worker thread)."""
        try:
            with self.app.app_context():
                import asyncio
                asyncio.run(self._async_migrate_timestamps())
        except Exception as e:
            self.app.logger.error(f"[tracking] timestamp migration failed: {e}")

    def maybe_run_migration(self) -> None:
        """Public entrypoint called by the CMS bootstrap after schema.sync()
        has completed, so the column types are migrated in a clean
        app-context without using background timers."""
        self._migrate_timestamps()
        # also warm up caches used by the request hot path so the first
        # request doesn't have to hit the DB for exclude rules or cookie
        # name
        try:
            import asyncio
            with self.app.app_context():
                asyncio.run(self._warmup_caches())
        except Exception as e:
            self.app.logger.error(f"[tracking] cache warmup failed: {e}")

    async def _warmup_caches(self) -> None:
        """Pre-populate the rules cache so the first request is non-blocking.
        Also ensures the admin/API paths are excluded even when the user has
        a custom path_patterns in the DB (otherwise each admin page refresh
        would track itself and invalidate the admin cache in a loop)."""
        await self._ensure_admin_paths_excluded()
        await self._load_rules(force=True)
        await self._cookie_name()
        self.app.logger.info("[tracking] request-path caches warmed up")

    async def _ensure_admin_paths_excluded(self) -> None:
        """Make sure the required tracking-protected paths are in the
        persisted path_patterns. If the user has never edited the setting,
        the new DEFAULT_EXCLUDES is used as-is. If they have a custom value,
        we append the missing patterns only so existing customizations are
        preserved.

        Three groups of patterns are auto-appended when missing:
        - admin / api paths (so admin page refreshes don't invalidate cache)
        - .well-known paths (RFC 8615 — certificate challenges, security.txt)
        """
        required = (
            # admin / api — don't track our own admin pages
            "/admin/tracking", "/admin/tracking/*", "/api/admin/*",
            # public JSON API: server-side renders of the Next.js frontend
            # would otherwise count as visits and pollute the statistics
            "/api/public/*",
            # .well-known — RFC 8615 standard directory, must not be tracked
            "*/.well-known", "*/.well-known/*",
        )
        try:
            current = await self.get_setting(SETTING_KEYS["paths"], None)
        except Exception as e:
            self.app.logger.error(f"[tracking] read paths failed: {e}")
            return
        # if the user has no custom value, the default already includes
        # every required pattern — nothing to persist.
        if current in (None, ""):
            return
        lines = [ln.strip() for ln in current.splitlines() if ln.strip()]
        if all(r in lines for r in required):
            return  # already up-to-date
        # append only what's missing (preserve user's existing patterns)
        merged = list(lines)
        for r in required:
            if r not in merged:
                merged.append(r)
        try:
            await self.set_setting(SETTING_KEYS["paths"], "\n".join(merged))
            self.app.logger.info(
                "[tracking] appended required paths (admin/api + .well-known) to tracking_exclude_paths"
            )
        except Exception as e:
            self.app.logger.error(f"[tracking] persist required paths failed: {e}")

    # ------------------------------------------------------------------ #
    # Background write worker
    # ------------------------------------------------------------------ #
    def _start_write_worker(self) -> None:
        """Spawn a daemon thread that drains the write queue into MySQL.
        This keeps tracking writes off the request path so each page load
        only takes the time needed to enqueue the row (~microseconds).
        """
        if self._write_worker_started:
            return
        try:
            import queue as _q

            self._write_queue = _q.Queue(maxsize=10000)
        except Exception as e:
            self.app.logger.error(f"[tracking] queue init failed: {e}")
            self._write_queue = None
            return

        def _worker():
            """Worker runs in daemon thread, processing tracking writes from the queue."""
            import asyncio as _aio

            db = self.db
            loop = _aio.new_event_loop()
            _aio.set_event_loop(loop)
            
            while True:
                try:
                    item = self._write_queue.get(timeout=1)
                except Exception:
                    continue  # timeout, loop again
                
                if item is None:
                    break  # shutdown sentinel
                
                try:
                    loop.run_until_complete(self._flush_one(db, item))
                except Exception as e:
                    self.app.logger.error(f"[tracking] writer error: {e}")
                finally:
                    try:
                        self._write_queue.task_done()
                    except Exception:
                        pass
            
            loop.close()

        t = threading.Thread(target=_worker, name="tracking-writer", daemon=True)
        t.start()
        self._write_worker_started = True

    async def _flush_one(self, db, item: dict) -> None:
        """Persist a single tracking row using the worker's DB instance.

        New payload shape (kind no longer used — ``item`` is a tracking
        request envelope). Visitor resolution happens here in the worker
        thread so the request path never blocks on MySQL.
        """
        # resolve visitor id (cache hit or DB lookup)
        visitor_id = item.get("cached_visitor_id")
        cache_key = item.get("cache_key")
        if not visitor_id:
            visitor_id = await self._resolve_visitor_id(
                db,
                cookie_name=item["cookie_name"],
                cookie_value=item["cookie_value"],
                user_id=item.get("user_id"),
                ip_remote=item.get("ip_remote"),
                ip_forwarded=item.get("ip_forwarded"),
                ip_real=item.get("ip_real"),
                country_code=item.get("country_code"),
            )
            if visitor_id and cache_key:
                # populate the in-memory cache so future requests skip DB
                self._visitor_cache_set(cache_key, visitor_id)
        if not visitor_id:
            # DB lookup failed entirely; drop the row to avoid crashing
            return

        # 1) insert the request row
        await db.execute(
            "INSERT INTO tracking_requests ("
            "  visitor_id, user_id, origin, destination, status_code, method,"
            "  ip_remote, ip_forwarded, ip_real,"
            "  country_code, country_name, city,"
            "  user_agent, browser_family, browser_version, device_type,"
            "  created_at"
            ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                visitor_id, item["user_id"],
                item["origin"], item["destination"],
                item["status_code"], item["method"],
                item["ip_remote"], item["ip_forwarded"], item["ip_real"],
                item["country_code"], item["country_name"], item["city"],
                item["user_agent"],
                item["browser_family"], item["browser_version"],
                item["device_type"],
                item["created_at"],
            ),
        )
        # 2) touch visitor stats (last_seen + request_count + user_id)
        await db.execute(
            "UPDATE tracking_visitors SET "
            "last_seen=%s, request_count=request_count+1, "
            "user_id=COALESCE(%s, user_id) "
            "WHERE id=%s",
            (item["created_at"], item["user_id"], visitor_id),
        )
        # 3) WRITE-THROUGH the admin cache so the next /api/admin/.../dashboard
        # call serves the new row immediately (no MySQL re-query needed).
        # We build a synthetic recent[] row from the in-memory payload.
        new_request_row = {
            "id": None,  # will be filled by the cache consumer if needed
            "created_at": item.get("created_at"),
            "destination": item.get("destination"),
            "status_code": item.get("status_code"),
            "ip_remote": item.get("ip_remote"),
            "ip_forwarded": item.get("ip_forwarded"),
            "ip_real": item.get("ip_real"),
            "country_code": item.get("country_code"),
            "country_name": item.get("country_name"),
            "browser_family": item.get("browser_family"),
            "browser_version": item.get("browser_version"),
            "device_type": item.get("device_type"),
            "user_id": item.get("user_id"),
            "visitor_id": visitor_id,
            "cookie_value": item.get("cookie_value"),
        }
        _refresh_admin_cache_dashboard(visitor_id, new_request_row)

    async def _resolve_visitor_id(
        self, db, *, cookie_name, cookie_value, user_id,
        ip_remote, ip_forwarded, ip_real, country_code,
    ) -> int | None:
        """Find or create the visitor row. Called from the worker thread
        when the request path has no cached visitor id."""
        row = await db.query(
            "SELECT id FROM tracking_visitors WHERE cookie_name=%s AND cookie_value=%s",
            (cookie_name, cookie_value), one=True,
        )
        if row:
            return row["id"]
        new_id = await db.execute(
            "INSERT INTO tracking_visitors ("
            "  cookie_name, cookie_value, user_id,"
            "  first_ip_remote, first_ip_forwarded, first_ip_real, first_country,"
            "  first_seen, last_seen"
            ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                cookie_name, cookie_value, user_id,
                ip_remote, ip_forwarded, ip_real, country_code,
                _now_jalali(), _now_jalali(),
            ),
        )
        # New visitor => visitor counts changed; drop the cached dashboard
        # so the next API call rebuilds it (we don't try to patch the
        # total_visitors counter — simpler and safer). Then pre-populate
        # the new visitor's detail cache so the per-visitor page is fast
        # on first open.
        _invalidate_admin_cache()
        if new_id and new_id > 0:
            visitor_row = {
                "id": new_id,
                "cookie_name": cookie_name,
                "cookie_value": cookie_value,
                "user_id": user_id,
                "request_count": 0,
                "first_ip_remote": ip_remote,
                "first_ip_forwarded": ip_forwarded,
                "first_ip_real": ip_real,
                "first_country": country_code,
                "first_seen": _now_jalali(),
                "last_seen": _now_jalali(),
            }
            _refresh_admin_cache_visitors(new_id, visitor_row)
        return new_id if new_id > 0 else None

    async def _async_migrate_timestamps(self) -> None:
        """ALTER legacy TIMESTAMP columns to VARCHAR(32). Idempotent."""
        # detect if migration is needed by inspecting column types
        info = await self.db.query(
            "SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.columns "
            "WHERE table_schema=DATABASE() "
            "AND table_name IN ('tracking_visitors','tracking_requests') "
            "AND COLUMN_NAME IN ('first_seen','last_seen','created_at')"
        ) or []
        # map (table, column) -> data_type
        needs_change = [
            (row["COLUMN_NAME"], row["DATA_TYPE"])
            for row in info
            if (row["DATA_TYPE"] or "").lower() != "varchar"
        ]
        if not needs_change:
            return
        # column -> table
        col_to_table = {
            "first_seen": "tracking_visitors",
            "last_seen":  "tracking_visitors",
            "created_at": "tracking_requests",
        }
        for col, _dt in needs_change:
            table = col_to_table.get(col)
            if not table:
                continue
            try:
                await self.db.execute(
                    f"ALTER TABLE `{table}` MODIFY COLUMN `{col}` VARCHAR(32) DEFAULT NULL"
                )
                self.app.logger.info(
                    f"[tracking] migrated {table}.{col} -> VARCHAR(32) for Jalali"
                )
            except Exception as e:
                self.app.logger.error(
                    f"[tracking] failed to migrate {table}.{col}: {e}"
                )

    # ------------------------------------------------------------------ #
    # Auto-enable on first run (override BasePlugin.is_enabled)
    # ------------------------------------------------------------------ #
    async def is_enabled(self) -> bool:
        """Returns True if enabled. On first detection (no DB row yet) the
        plugin is auto-registered as enabled so the user doesn't have to
        toggle it from the admin panel. Subsequent toggles via the admin
        panel are respected normally."""
        try:
            row = await self.db.query(
                "SELECT enabled FROM plugins WHERE name=%s", (self.name,), one=True
            )
        except Exception as e:
            self.app.logger.error(f"[tracking] is_enabled query failed: {e}")
            return False
        if row is None:
            try:
                await self.db.execute(
                    "INSERT INTO plugins (name, enabled) VALUES (%s, 1)",
                    (self.name,),
                )
                self.app.logger.info(
                    "[tracking] no DB row found — auto-enabled on first run"
                )
                return True
            except Exception as e:
                self.app.logger.error(f"[tracking] auto-enable failed: {e}")
                return False
        return bool(row["enabled"])

    # ------------------------------------------------------------------ #
    # Exclude rules (settings-driven, in-process)
    # ------------------------------------------------------------------ #
    async def _load_rules(self, *, force: bool = False) -> dict:
        """Resolve exclude rules from the ``settings`` table.

        Results are cached on the instance and reloaded on demand via
        :meth:`reload_rules` (e.g. from the admin form).
        """
        if self._rules_cache is not None and not force:
            return self._rules_cache

        async def val(key: str, default: str) -> str:
            v = await self.get_setting(SETTING_KEYS[key], None)
            if v in (None, ""):
                return DEFAULT_EXCLUDES[FIELD_TO_DEFAULT[key]]
            return v

        paths_raw   = await val("paths",   DEFAULT_EXCLUDES["path_patterns"])
        methods_raw = await val("methods", DEFAULT_EXCLUDES["method_patterns"])
        status_raw  = await val("status",  DEFAULT_EXCLUDES["status_filter"])
        ua_raw      = await val("uas",     DEFAULT_EXCLUDES["ua_patterns"])
        bots_raw    = await val("bots",    DEFAULT_EXCLUDES["ignore_bots"])

        self._rules_cache = {
            "paths":   _split_lines(paths_raw),
            "methods": [m.upper() for m in _split_lines(methods_raw)],
            "status":  (status_raw or "all").strip().lower(),
            "uas":     _split_lines(ua_raw),
            "ignore_bots": bots_raw.strip() in ("1", "true", "yes", "on"),
        }
        return self._rules_cache

    def reload_rules(self) -> None:
        """Drop the cached rules so the next request reloads them.
        Also clears the cookie-name cache so a renamed site takes effect
        on the next request."""
        self._rules_cache = None
        self._cookie_name_cache = None

    def _should_track_sync(self, ua_string: str, parsed_ua, status: int) -> bool:
        """Sync version of should_track using the cached rules (no DB access)."""
        # Always build a complete rules dict; .get() with defaults so a
        # partially-populated cache never raises KeyError mid-request.
        rules = self._rules_cache or {}
        paths    = rules.get("paths",    _split_lines(DEFAULT_EXCLUDES["path_patterns"]))
        methods  = rules.get("methods",  [])
        status_f = rules.get("status",   "all")
        uas      = rules.get("uas",      _split_lines(DEFAULT_EXCLUDES["ua_patterns"]))
        ignore   = rules.get("ignore_bots", DEFAULT_EXCLUDES["ignore_bots"].strip() == "1")
        rules = {
            "paths": paths, "methods": methods, "status": status_f,
            "uas": uas, "ignore_bots": ignore,
        }
        # 1) path
        path = request.path or ""
        full = request.full_path if request.method == "GET" else path
        if _match_any(path, rules["paths"]) or _match_any(full, rules["paths"]):
            return False
        # 2) method
        if request.method and request.method.upper() in rules["methods"]:
            return False
        # 3) status filter
        sf = rules["status"]
        if sf == "success" and not (200 <= status < 400):
            return False
        if sf == "errors" and not (status >= 400):
            return False
        # 4) bot via user-agents lib
        if rules["ignore_bots"] and parsed_ua is not None and parsed_ua.is_bot:
            return False
        # 5) UA glob
        if rules["uas"] and _match_any(ua_string or "", rules["uas"]):
            return False
        return True
    def _load_geoip(self) -> None:
        if maxminddb is None:
            self.app.logger.warning("[tracking] maxminddb not installed; geo lookup disabled")
            return
        try:
            if COUNTRY_DB.exists():
                self._geo_country = maxminddb.open_database(str(COUNTRY_DB))
                self.app.logger.info(f"[tracking] loaded {COUNTRY_DB.name}")
            else:
                self.app.logger.info(f"[tracking] {COUNTRY_DB.name} not found next to plugin")
        except Exception as e:
            self.app.logger.error(f"[tracking] country db error: {e}")
            self._geo_country = None
        try:
            if CITY_DB.exists():
                self._geo_city = maxminddb.open_database(str(CITY_DB))
                self.app.logger.info(f"[tracking] loaded {CITY_DB.name}")
            else:
                self.app.logger.info(f"[tracking] {CITY_DB.name} not found next to plugin")
        except Exception as e:
            self.app.logger.error(f"[tracking] city db error: {e}")
            self._geo_city = None

    def _geo_lookup(self, ip: str) -> dict:
        """Return country code/name + city from the best DB available.

        Results are cached in ``app.cache`` under the ``tracking_geo``
        namespace so a repeat lookup for the same IP is a single dict read.
        The mmdb file is opened once in :meth:`_load_geoip` and never
        re-checked on the hot path.
        """
        empty = {"country_code": None, "country_name": None, "city": None}
        if not ip:
            return empty
        # cache key per IP — `make_key` builds "tracking_geo:ip:<ip>"
        cache = self._cache
        if cache is not None:
            key = f"ip:{ip}"
            hit = cache.get(key, namespace=GEO_NS)
            if hit is not None:
                return hit
        result = self._geo_lookup_uncached(ip)
        if cache is not None:
            try:
                cache.set(
                    f"ip:{ip}",
                    result,
                    ttl=GEO_TTL,
                    namespace=GEO_NS,
                )
            except Exception as e:
                self.app.logger.error(f"[tracking] geo cache write failed: {e}")
        return result

    def _geo_lookup_uncached(self, ip: str) -> dict:
        """Raw mmdb lookup without touching the cache."""
        empty = {"country_code": None, "country_name": None, "city": None}
        if not ip:
            return empty
        # 1) try city DB (richer)
        if self._geo_city:
            try:
                rec = self._geo_city.get(ip)
                if rec:
                    return {
                        "country_code": (rec.get("country") or {}).get("iso_code"),
                        "country_name": (rec.get("country") or {}).get("names", {}).get("en"),
                        "city": ((rec.get("city") or {}).get("names") or {}).get("en"),
                    }
            except Exception:
                pass
        # 2) fall back to country DB
        if self._geo_country:
            try:
                rec = self._geo_country.get(ip)
                if rec:
                    return {
                        "country_code": (rec.get("country") or {}).get("iso_code"),
                        "country_name": (rec.get("country") or {}).get("names", {}).get("en"),
                        "city": None,
                    }
            except Exception:
                pass
        return empty

    # ------------------------------------------------------------------ #
    # Cookie helpers
    # ------------------------------------------------------------------ #
    async def _cookie_name(self) -> str:
        """Build the per-site cookie name: AT-<site-slug>.

        Cached in-process so we don't hit the ``settings`` table on every
        request. Reloaded automatically when the rules cache is reloaded.
        """
        if self._cookie_name_cache:
            return self._cookie_name_cache
        title = await self.get_setting("site_title", "site")
        slug = _slugify(title, fallback="site")
        self._cookie_name_cache = f"{COOKIE_PREFIX}{slug}"
        return self._cookie_name_cache

    def _cookie_name_sync(self) -> str:
        """Same as :meth:`_cookie_name` but using the cached value directly.
        Returns a generic ``AT-site`` fallback if the cache hasn't been
        populated yet (the request will refresh it on the first call)."""
        if self._cookie_name_cache:
            return self._cookie_name_cache
        return f"{COOKIE_PREFIX}site"

    async def _ensure_cookie(self, response) -> str | None:
        """Make sure AT-sitename cookie exists; return its value (new or old)."""
        cookie_name = await self._cookie_name()
        value = request.cookies.get(cookie_name)
        if not value:
            value = secrets.token_urlsafe(24)
            # 1 year, accessible server-side
            response.set_cookie(
                cookie_name,
                value,
                max_age=60 * 60 * 24 * 365,
                httponly=True,
                samesite="Lax",
                path="/",
            )
        return value

    # ------------------------------------------------------------------ #
    # Schema
    # ------------------------------------------------------------------ #
    def declare_schema(self, schema):
        # NOTE: time columns are stored as VARCHAR (Jalali string written
        # by the app) because MySQL TIMESTAMP cannot represent Persian
        # dates; queries still order by id and treat these as labels.
        schema.register_table("tracking_visitors", {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "cookie_name": "VARCHAR(64) NOT NULL",
            "cookie_value": "VARCHAR(128) NOT NULL",
            "first_seen": "VARCHAR(32) DEFAULT NULL",
            "last_seen": "VARCHAR(32) DEFAULT NULL",
            "user_id": "INT DEFAULT NULL",
            "first_ip_remote": "VARCHAR(64)",
            "first_ip_forwarded": "VARCHAR(64)",
            "first_ip_real": "VARCHAR(64)",
            "first_country": "VARCHAR(8)",
            "request_count": "INT DEFAULT 0",
        })
        schema.register_table("tracking_requests", {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "visitor_id": "INT NOT NULL",
            "user_id": "INT DEFAULT NULL",
            "created_at": "VARCHAR(32) DEFAULT NULL",
            "origin": "VARCHAR(500)",
            "destination": "VARCHAR(500)",
            "status_code": "INT DEFAULT 0",
            "method": "VARCHAR(16)",
            "ip_remote": "VARCHAR(64)",
            "ip_forwarded": "VARCHAR(64)",
            "ip_real": "VARCHAR(64)",
            "country_code": "VARCHAR(8)",
            "country_name": "VARCHAR(64)",
            "city": "VARCHAR(128)",
            "user_agent": "VARCHAR(500)",
            "browser_family": "VARCHAR(64)",
            "browser_version": "VARCHAR(32)",
            "device_type": "VARCHAR(32)",
        })

    # ------------------------------------------------------------------ #
    # Hooks
    # ------------------------------------------------------------------ #
    def register(self):
        """Wire before/after request hooks + admin blueprint.

        Safe to call multiple times (Flask reloader, toggle from admin):
        a per-instance flag prevents double registration.
        """
        if getattr(self, "_registered", False):
            self.app.logger.debug("[tracking] already registered; skipping")
            return
        self._registered = True
        self.app.before_request(self._before_request)
        self.app.after_request(self._after_request)
        self.register_admin(self.app)
        # log every URL rule we just attached (helps debugging 404s)
        rules = sorted(
            f"{','.join(sorted(r.methods - {'HEAD','OPTIONS'})):<8} {r.rule}"
            for r in self.app.url_map.iter_rules()
            if "tracking" in (r.endpoint or "")
        )
        self.app.logger.info(
            "[tracking] registered. routes:\n  " + "\n  ".join(rules) if rules
            else "[tracking] registered. routes: (none)"
        )

    def _before_request(self):
        # placeholder hook — currently no per-request setup needed;
        # cookie minting happens in after_request when we have a response.
        return None

    async def _after_request(self, response):
        """Runs after the view. **Strictly non-blocking**: every DB write
        (visitor lookup, visitor insert, request insert, visitor touch)
        is enqueued onto ``self._write_queue`` and processed by the
        daemon ``tracking-writer`` thread.

        The request path only does in-process work:
        - read request headers / cookies (no I/O)
        - in-memory rule check (cached)
        - in-memory GeoIP cache lookup (cached)
        - in-memory visitor-id cache lookup (may miss on first visit)
        - put_nowait() the row onto the queue (~µs)

        Visitor resolution on cache miss is **deferred** to the worker:
        the worker thread does the SELECT/INSERT and populates the cache
        so subsequent requests from the same visitor are instant.
        """
        try:
            # 0) collect request metadata (no I/O)
            ua_string = request.headers.get("User-Agent", "")[:500]
            ua = ua_parse(ua_string)

            # 1) resolve rules (cached after first call) + exclusion check
            rules = await self._load_rules()
            if not self._should_track_sync(ua_string, ua, response.status_code):
                # still mint the visitor cookie so excluded visitors are not
                # re-created as new ones when they hit non-excluded pages.
                await self._ensure_cookie(response)
                return response

            # 2) cookie handling (no DB hit — uses cached cookie name)
            cookie_name = self._cookie_name_sync()
            cookie_value = request.cookies.get(cookie_name)
            if not cookie_value:
                cookie_value = secrets.token_urlsafe(24)
                response.set_cookie(
                    cookie_name,
                    cookie_value,
                    max_age=60 * 60 * 24 * 365,
                    httponly=True,
                    samesite="Lax",
                    path="/",
                )
            if not cookie_value:
                return response

            # 3) collect remaining metadata (all in-memory, no DB)
            ips = _client_ips()
            real_ip = ips["real"] or ips["forwarded"] or ips["remote"]
            geo = self._geo_lookup(real_ip)
            device = _device_type(ua)
            origin = request.headers.get("Referer") or ""
            destination = (
                request.full_path if request.method == "GET" else request.path
            ) or request.path

            from app.core.auth import AuthManager
            user = AuthManager.current_user()
            user_id = user["id"] if user else None

            # 4) visitor id resolution — in-memory cache only (NO DB hit here)
            cache_key = _visitor_cache_key(cookie_name, cookie_value)
            cached_visitor_id = self._visitor_cache_get(cache_key)

            # 5) enqueue writes — never blocks the response.
            #    The worker resolves the visitor (SELECT or INSERT) and writes
            #    the request row + visitor touch in the background.
            now = _now_jalali()
            payload = {
                "cookie_name": cookie_name,
                "cookie_value": cookie_value,
                "cache_key": cache_key,
                "user_id": user_id,
                "origin": origin[:500],
                "destination": destination[:500],
                "status_code": response.status_code,
                "method": request.method,
                "ip_remote": ips["remote"],
                "ip_forwarded": ips["forwarded"],
                "ip_real": ips["real"],
                "country_code": geo["country_code"],
                "country_name": geo["country_name"],
                "city": geo["city"],
                "user_agent": ua_string,
                "browser_family": ua.browser.family or "",
                "browser_version": ua.browser.version_string or "",
                "device_type": device,
                "created_at": now,
                "cached_visitor_id": cached_visitor_id,
            }
            if self._write_queue is not None:
                try:
                    self._write_queue.put_nowait(payload)
                except queue.Full:
                    self.app.logger.warning("[tracking] write queue full, dropping row")
                except Exception as e:
                    self.app.logger.error(f"[tracking] enqueue error: {e}")
            else:
                # fallback: synchronous write (worker not started)
                await self._flush_one(self.db, payload)
        except Exception as e:
            # never break the user-facing response because of tracking
            self.app.logger.error(f"[tracking] after_request error: {e}")
        return response

    # ------------------------------------------------------------------ #
    # Visitor-id cache helpers (backed by app.core.cache.PluginCache)
    # ------------------------------------------------------------------ #
    def _visitor_cache_get(self, key: str) -> int | None:
        """Read a visitor id from the plugin cache; returns ``None`` on miss
        or when no cache is configured."""
        cache = self._cache
        if cache is None:
            return None
        try:
            v = cache.get(key, namespace=VISITOR_NS)
            return int(v) if v is not None else None
        except Exception as e:
            self.app.logger.error(f"[tracking] visitor cache read failed: {e}")
            return None

    def _visitor_cache_set(self, key: str, visitor_id: int) -> None:
        """Write a visitor id to the plugin cache. Keeps the namespace size
        bounded by trimming when :data:`MAX_VISITOR_CACHE_ENTRIES` is hit."""
        cache = self._cache
        if cache is None:
            return
        try:
            cache.set(key, visitor_id, ttl=VISITOR_TTL, namespace=VISITOR_NS)
            self._visitor_id_cache_size += 1
            if self._visitor_id_cache_size > MAX_VISITOR_CACHE_ENTRIES:
                # clear half the namespace to bound memory
                cache.invalidate_namespace(VISITOR_NS)
                self._visitor_id_cache_size = 0
                self.app.logger.info(
                    "[tracking] visitor cache namespace trimmed"
                )
        except Exception as e:
            self.app.logger.error(f"[tracking] visitor cache write failed: {e}")

    # ------------------------------------------------------------------ #
    # Admin views
    # ------------------------------------------------------------------ #
    def unregister(self):
        """Remove admin blueprint + view functions so the toggle from
        /admin/plugins works cleanly. URL rules are reset by Flask on the
        next app restart; for in-place toggles we drop our own rules."""
        try:
            name = "plugin_tracking_admin"
            if name in self.app.blueprints:
                # drop view functions registered under this blueprint
                to_remove = [
                    ep
                    for ep in list(self.app.view_functions)
                    if ep.startswith(f"{name}.")
                ]
                for ep in to_remove:
                    self.app.view_functions.pop(ep, None)
                self.app.blueprints.pop(name, None)
        except Exception as e:
            self.app.logger.error(f"[tracking] unregister error: {e}")
        self._registered = False

    def register_admin(self, app):
        from flask import Blueprint, request
        from app.core.admin_api import api_route, body, page_route, reply
        from app.core.public import ApiError

        # guard against double-registration on Flask reloader
        if "plugin_tracking_admin" in app.blueprints:
            self.app.logger.debug(
                "[tracking] admin blueprint already registered; skipping"
            )
            return

        bp = Blueprint("plugin_tracking_admin", __name__)

        # page shells only — data is fetched by the browser after load
        page_route(bp, "/admin/tracking", "dashboard", "tracking_dashboard", "آمار بازدیدها", "pages-tracking")
        page_route(bp, "/admin/tracking/visitors", "visitors", "tracking_visitors", "بازدیدکنندگان", "pages-tracking")
        page_route(bp, "/admin/tracking/visitor/<int:vid>", "visitor_detail", "tracking_visitor", "بازدیدکننده", "pages-tracking")
        page_route(bp, "/admin/tracking/settings", "settings_view", "tracking_settings", "تنظیمات ردگیری", "pages-tracking")

        # ----------------------------------------------------------------- #
        # JSON API endpoints — called by the browser after page load so the
        # initial HTML response stays small and fast. Every endpoint is
        # served from `self.app.cache` (PluginCache) so repeat visits don't
        # hit MySQL. The background writer invalidates the namespace after
        # each successful insert so the next API call re-reads fresh data.
        # ----------------------------------------------------------------- #
        @api_route(bp, "/api/admin/tracking/dashboard", "api_dashboard")
        async def api_dashboard():
            cache = self._cache
            async def _build():
                db = self.db
                total_requests = (await db.query(
                    "SELECT COUNT(*) AS c FROM tracking_requests"
                )) or [{"c": 0}]
                total_visitors = (await db.query(
                    "SELECT COUNT(*) AS c FROM tracking_visitors"
                )) or [{"c": 0}]
                unique_ips = (await db.query(
                    "SELECT COUNT(DISTINCT ip_remote) AS c FROM tracking_requests "
                    "WHERE ip_remote IS NOT NULL"
                )) or [{"c": 0}]
                by_country = await db.query(
                    "SELECT country_code, country_name, COUNT(*) AS hits "
                    "FROM tracking_requests "
                    "WHERE country_code IS NOT NULL "
                    "GROUP BY country_code, country_name "
                    "ORDER BY hits DESC LIMIT 10"
                ) or []
                by_device = await db.query(
                    "SELECT device_type, COUNT(*) AS hits "
                    "FROM tracking_requests "
                    "GROUP BY device_type ORDER BY hits DESC"
                ) or []
                by_browser = await db.query(
                    "SELECT browser_family, COUNT(*) AS hits "
                    "FROM tracking_requests "
                    "WHERE browser_family<>'' "
                    "GROUP BY browser_family ORDER BY hits DESC LIMIT 10"
                ) or []
                recent = await db.query(
                    "SELECT r.id, r.created_at, r.destination, r.status_code, "
                    "       r.ip_remote, r.ip_forwarded, r.ip_real, "
                    "       r.country_code, r.country_name, "
                    "       r.browser_family, r.browser_version, r.device_type, "
                    "       r.user_id, r.visitor_id, v.cookie_value "
                    "FROM tracking_requests r "
                    "LEFT JOIN tracking_visitors v ON v.id=r.visitor_id "
                    "ORDER BY r.id DESC LIMIT 50"
                ) or []
                return {
                    "total_requests": total_requests[0]["c"],
                    "total_visitors": total_visitors[0]["c"],
                    "unique_ips": unique_ips[0]["c"],
                    "by_country": by_country,
                    "by_device": by_device,
                    "by_browser": by_browser,
                    "recent": recent,
                }
            if cache is not None:
                payload = await cache.get_or_set(
                    _admin_dashboard_key(),
                    _build,
                    ttl=ADMIN_TTL,
                    namespace=ADMIN_NS,
                )
            else:
                payload = await _build()
            return reply(payload)

        @api_route(bp, "/api/admin/tracking/visitors", "api_visitors")
        async def api_visitors():
            cache = self._cache
            page = max(int(request.args.get("page", 1) or 1), 1)
            per_page = 50
            async def _build():
                db = self.db
                offset = (page - 1) * per_page
                rows = await db.query(
                    "SELECT id, cookie_name, cookie_value, user_id, "
                    "       request_count, first_ip_remote, first_ip_forwarded, "
                    "       first_ip_real, first_country, first_seen, last_seen "
                    "FROM tracking_visitors "
                    "ORDER BY last_seen DESC LIMIT %s OFFSET %s",
                    (per_page, offset),
                ) or []
                total = (await db.query(
                    "SELECT COUNT(*) AS c FROM tracking_visitors"
                )) or [{"c": 0}]
                return {
                    "visitors": rows,
                    "page": page,
                    "per_page": per_page,
                    "total": total[0]["c"],
                }
            if cache is not None:
                payload = await cache.get_or_set(
                    _admin_visitors_key(page),
                    _build,
                    ttl=ADMIN_TTL,
                    namespace=ADMIN_NS,
                )
            else:
                payload = await _build()
            return reply(payload)

        @api_route(bp, "/api/admin/tracking/visitor/<int:vid>", "api_visitor")
        async def api_visitor_detail(vid):
            cache = self._cache
            async def _build():
                db = self.db
                v = await db.query(
                    "SELECT id, cookie_name, cookie_value, user_id, "
                    "       request_count, first_ip_remote, first_ip_forwarded, "
                    "       first_ip_real, first_country, first_seen, last_seen "
                    "FROM tracking_visitors WHERE id=%s",
                    (vid,), one=True,
                )
                if not v:
                    return None
                reqs = await db.query(
                    "SELECT id, created_at, method, destination, origin, "
                    "       status_code, ip_remote, ip_forwarded, ip_real, "
                    "       country_code, country_name, city, "
                    "       browser_family, browser_version, device_type, user_id "
                    "FROM tracking_requests WHERE visitor_id=%s "
                    "ORDER BY id DESC LIMIT 200",
                    (vid,),
                ) or []
                return {"visitor": v, "requests": reqs}
            if cache is not None:
                payload = await cache.get_or_set(
                    _admin_visitor_detail_key(vid),
                    _build,
                    ttl=ADMIN_TTL,
                    namespace=ADMIN_NS,
                )
            else:
                payload = await _build()
            if payload is None:
                raise ApiError(404, "not_found", "بازدیدکننده یافت نشد")
            return reply(payload)

        @api_route(bp, "/api/admin/tracking/settings", "api_settings", ["GET", "PUT"])
        async def api_settings():
            """Exclude rules, stored in the ``settings`` table so they survive restarts."""
            if request.method == "PUT":
                data = body()
                for field, key in SETTING_KEYS.items():
                    if field not in data:
                        continue
                    raw = data[field]
                    if field == "bots":
                        raw = "1" if raw in (True, 1, "1", "on", "true") else "0"
                    elif field == "status":
                        raw = raw if raw in ("all", "success", "errors") else "all"
                    await self.set_setting(key, str(raw if raw is not None else ""))
                self.reload_rules()
                _invalidate_admin_cache()
            current = {}
            for field, key in SETTING_KEYS.items():
                v = await self.get_setting(key, None)
                current[field] = DEFAULT_EXCLUDES[FIELD_TO_DEFAULT[field]] if v in (None, "") else v
            return reply({"current": current, "defaults": DEFAULT_EXCLUDES})

        app.register_blueprint(bp)