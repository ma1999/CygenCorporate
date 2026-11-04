"""Infrastructure for the public JSON API (``/api/public/*``).

Always installed by ``create_app()`` (it is framework code, not a feature).
Content plugins build their routes with :func:`public_blueprint` /
:func:`public_get`; this module provides, for every path under the prefix:

- JSON error envelope (``{"ok": false, "error": "<code>", ...}``) for *every*
  error, including Flask's own 404/405/500 and unhandled exceptions
- database failures => ``503 unavailable`` (never an empty list)
- CORS (opt-in through ``CORS_ALLOWED_ORIGINS``; empty = no headers at all)
- ``ETag`` / ``If-None-Match`` => 304, ``Cache-Control`` on successful GETs
- a short-TTL in-process response cache that is cleared by every content write
  (see :mod:`app.core.revalidate`)
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import threading
import time
from decimal import Decimal
import datetime as _dt

from flask import Blueprint, Response, current_app, request
from werkzeug.exceptions import HTTPException

from . import content as C
from .database import DatabaseError

PREFIX = "/api/public"
CACHE_NS = "public_api"
MAX_BODY_BYTES = 64 * 1024
NO_STORE_PATHS = {PREFIX + "/health"}

log = logging.getLogger("cms.public")


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str = "", fields=None, headers=None):
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code
        self.fields = fields
        self.headers = headers or {}


def bad_request(message="Bad request") -> ApiError:
    return ApiError(400, "bad_request", message)


def not_found(message="Not found") -> ApiError:
    return ApiError(404, "not_found", message)


def validation_failed(fields: dict) -> ApiError:
    return ApiError(422, "validation_failed", "Validation failed", fields=fields)


def _error_response(status, code, message, fields=None, headers=None):
    body = {"ok": False, "error": code, "message": message}
    if fields:
        body["fields"] = fields
    resp = Response(
        json.dumps(body, ensure_ascii=False),
        status=status,
        headers={"Content-Type": "application/json; charset=utf-8", **(headers or {})},
    )
    return resp


_HTTP_CODES = {404: "not_found", 422: "validation_failed", 429: "rate_limited", 503: "unavailable"}


# ---------------------------------------------------------------------------
# request parameter helpers (clamp, never raise 500)
# ---------------------------------------------------------------------------
def arg_int(name, default, lo=None, hi=None) -> int:
    raw = request.args.get(name)
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    if lo is not None and v < lo:
        v = lo
    if hi is not None and v > hi:
        v = hi
    return v


def arg_str(name, maxlen=200, default="") -> str:
    v = (request.args.get(name) or "").strip()
    return v[:maxlen] if v else default


def arg_flag(name) -> bool:
    return (request.args.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def arg_choice(name, choices, default):
    v = (request.args.get(name) or "").strip()
    if not v:
        return default
    if v not in choices:
        raise bad_request(f"Invalid '{name}'. Allowed: {', '.join(choices)}")
    return v


def arg_lang(default="fa") -> str:
    v = (request.args.get("lang") or "").strip().lower()
    return v if v and len(v) <= 8 and v.replace("-", "").replace("_", "").isalnum() else default


def paginate_args(default_per_page=12, max_per_page=100):
    page = arg_int("page", 1, 1, 100000)
    per_page = arg_int("per_page", default_per_page, 1, max_per_page)
    return page, per_page


def meta(total: int, page: int, per_page: int) -> dict:
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, -(-total // per_page)) if total else 0,
    }


def json_body(max_bytes: int = MAX_BODY_BYTES) -> dict:
    """Parse a JSON object body (<= 64KB). Anything else => 400/413."""
    if request.content_length is not None and request.content_length > max_bytes:
        raise ApiError(413, "bad_request", "Request body too large")
    raw = request.stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ApiError(413, "bad_request", "Request body too large")
    try:
        data = json.loads(raw.decode("utf-8")) if raw else None
    except (ValueError, UnicodeDecodeError):
        raise bad_request("Body must be valid JSON")
    if not isinstance(data, dict):
        raise bad_request("Body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# draft preview tokens (admin -> frontend -> API)
# ---------------------------------------------------------------------------
PREVIEW_PARAM = "preview"
_PREVIEW_SALT = "public-preview-v1"


def _preview_serializer():
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(current_app.secret_key, salt=_PREVIEW_SALT)


def preview_ttl() -> int:
    try:
        return max(1, int(os.getenv("PREVIEW_TOKEN_TTL", "3600") or 3600))
    except ValueError:
        return 3600


def make_preview_token(kind: str, entity_id: int) -> str:
    """Signed, short-lived token that lets ONE draft/scheduled item be read
    through the public detail endpoint (``?preview=<token>``)."""
    return _preview_serializer().dumps({"k": kind, "i": int(entity_id)})


def preview_target(kind: str):
    """Entity id carried by a valid ``?preview=`` token for ``kind`` (``None``
    when no token is present). A bad/expired/other-kind token => 400."""
    token = request.args.get(PREVIEW_PARAM)
    if not token:
        return None
    from itsdangerous import BadData

    try:
        data = _preview_serializer().loads(token, max_age=preview_ttl())
    except BadData:
        raise bad_request("Invalid or expired preview token")
    if not isinstance(data, dict) or data.get("k") != kind or not isinstance(data.get("i"), int):
        raise bad_request("Invalid or expired preview token")
    return data["i"]


def client_ip() -> str:
    """Real client IP: X-Real-IP -> X-Forwarded-For (first) -> remote_addr."""
    candidates = [
        request.headers.get("X-Real-IP", ""),
        (request.headers.get("X-Forwarded-For", "") or "").split(",")[0],
        request.remote_addr or "",
    ]
    for c in candidates:
        c = (c or "").strip()
        if not c:
            continue
        try:
            return str(ipaddress.ip_address(c))
        except ValueError:
            continue
    return request.remote_addr or "0.0.0.0"


class RateLimiter:
    """Sliding-window limiter, in-process (per worker)."""

    def __init__(self):
        self._hits: dict = {}
        self._lock = threading.Lock()

    def check(self, key: str, rules) -> int:
        """Record a hit; return 0 when allowed else seconds to wait.

        ``rules`` = [(max_hits, window_seconds), ...]. A rejected hit is not
        recorded."""
        now = time.time()
        horizon = max(w for _, w in rules)
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < horizon]
            for limit, window in rules:
                recent = [t for t in hits if now - t < window]
                if limit and len(recent) >= limit:
                    wait = int(window - (now - min(recent))) + 1
                    self._hits[key] = hits
                    return max(wait, 1)
            hits.append(now)
            self._hits[key] = hits
            if len(self._hits) > 20000:
                for k in list(self._hits)[:5000]:
                    self._hits.pop(k, None)
        return 0

    def reset(self):
        with self._lock:
            self._hits.clear()


# ---------------------------------------------------------------------------
# per-request context passed to public handlers
# ---------------------------------------------------------------------------
class Ctx:
    """Serialisation helpers bound to one request (active languages, base URL)."""

    def __init__(self, db, base, langs, offset):
        self.db = db
        self.base = base
        self.langs = langs          # active language codes, 'fa' always included
        self.offset = offset        # server local-time offset from UTC (seconds)

    def text(self, raw, fallback="") -> dict:
        return C.i18n_text(raw, fallback, self.langs)

    def lst(self, raw, fallback=None) -> dict:
        return C.i18n_list(raw, fallback, self.langs)

    def media(self, path, alt_raw=None):
        return C.media_obj(path, alt_raw, self.base, self.langs)

    def url(self, path):
        return C.abs_url(path, self.base)

    def effective(self, *raws, trunc=200) -> dict:
        """Per language: first non-empty value across ``raws`` (i18n values in
        priority order). Fallback-sourced values are truncated; ``fa`` is
        always present."""
        ds = [C.parse_i18n(r) for r in raws]
        out = {}
        for lang in self.langs:
            for i, d in enumerate(ds):
                v = d.get(lang)
                if isinstance(v, str) and v.strip():
                    out[lang] = v if i == 0 or len(v) <= trunc else v[:trunc].rsplit(" ", 1)[0].rstrip() + "…"
                    break
        out.setdefault("fa", "")
        return out

    def seo(self, *, title, name, description, short=None, long=None, keywords=None, og=None, cover=None,
            cover_alt=None, noindex=False) -> dict:
        """The effective ``Seo`` object: meta values fall back to the
        name/short description, og_image falls back to the cover image."""
        return {
            "title": self.effective(title, name),
            "description": self.effective(description, short, long),
            "keywords": self.effective(keywords),
            "og_image": self.media(og, cover_alt) or self.media(cover, cover_alt),
            "noindex": bool(noindex),
        }

    @staticmethod
    def iso(dt):
        return C.iso(dt)

    def iso_local(self, dt):
        """For legacy TIMESTAMP columns that hold server-local time."""
        return C.iso(C.local_to_utc(dt, self.offset))


async def active_langs(db) -> list:
    cache = current_app.cache
    key = f"{CACHE_NS}:langs"
    hit = cache.get(key, namespace=CACHE_NS)
    if hit is not None:
        return hit
    rows = await db.fetch("SELECT code FROM i18n_languages WHERE is_active=1 ORDER BY is_default DESC, id")
    codes = ["fa"] + [r["code"] for r in rows if r["code"] != "fa"]
    cache.set(key, codes, ttl=30, namespace=CACHE_NS)
    return codes


async def make_ctx() -> Ctx:
    db = current_app.core.db
    langs = await active_langs(db)
    off = await C.server_utc_offset_seconds(db)
    return Ctx(db, C.public_base_url(request), langs, off)


# ---------------------------------------------------------------------------
# routing helpers
# ---------------------------------------------------------------------------
def public_blueprint(name: str) -> Blueprint:
    return Blueprint(name, __name__, url_prefix=PREFIX)


def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (_dt.datetime, _dt.date)):
        return C.iso(o)
    if isinstance(o, (bytes, bytearray)):
        return o.decode("utf-8", "replace")
    raise TypeError(f"not serialisable: {type(o).__name__}")


def dumps(data) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=_json_default).encode("utf-8")


def json_response(body: bytes, status=200) -> Response:
    return Response(body, status=status, headers={"Content-Type": "application/json; charset=utf-8"})


def ok(data: dict, status=200) -> Response:
    return json_response(dumps(data), status)


def public_get(bp: Blueprint, rule: str, *, params=(), ttl=None):
    """Register ``GET <PREFIX><rule>``.

    The handler is ``async def fn(ctx, **url_args) -> dict``. Only the query
    parameters listed in ``params`` take part in the response-cache key (the
    rest are ignored), so random query strings cannot flood the cache.
    ``ttl`` overrides ``PUBLIC_API_CACHE_TTL`` (0 = never cache)."""

    def deco(fn):
        async def view(**url_args):
            cache = current_app.cache
            use_ttl = _default_ttl() if ttl is None else ttl
            if request.args.get(PREVIEW_PARAM):
                use_ttl = 0          # previews are never cached
            key = None
            if use_ttl > 0:
                q = "&".join(f"{p}={request.args.get(p, '')}" for p in sorted(params))
                # absolute media/download URLs depend on the origin the client used
                key = f"{CACHE_NS}:resp:{C.public_base_url(request)}{request.path}?{q}"
                hit = cache.get(key, namespace=CACHE_NS)
                if hit is not None:
                    return json_response(hit)
            ctx = await make_ctx()
            data = await fn(ctx, **url_args)
            body = dumps(data)
            if key:
                cache.set(key, body, ttl=use_ttl, namespace=CACHE_NS)
            return json_response(body)

        view.__name__ = fn.__name__
        view.__doc__ = fn.__doc__
        bp.add_url_rule(rule, endpoint=fn.__name__, view_func=view, methods=["GET"])
        return fn

    return deco


def _default_ttl() -> int:
    try:
        return max(0, int(os.getenv("PUBLIC_API_CACHE_TTL", "30") or 0))
    except ValueError:
        return 30


def clear_response_cache(app=None):
    app = app or current_app
    app.cache.invalidate_namespace(CACHE_NS)


# ---------------------------------------------------------------------------
# install (idempotent): error handlers, CORS, ETag
# ---------------------------------------------------------------------------
def is_public_path() -> bool:
    p = request.path
    return p == PREFIX or p.startswith(PREFIX + "/")


def is_json_api_path() -> bool:
    """Paths whose errors must use the JSON envelope: the public API and the admin API."""
    return is_public_path() or request.path == "/api/admin" or request.path.startswith("/api/admin/")


def _allowed_origins() -> list:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "") or ""
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


def install_public_api(app):
    if getattr(app, "_public_api_installed", False):
        return
    app._public_api_installed = True
    app.public_providers = {"search": {}, "sitemap": {}, "home": {}}

    @app.errorhandler(ApiError)
    def _api_error(e: ApiError):
        return _error_response(e.status, e.code, e.message, e.fields, e.headers)

    @app.errorhandler(DatabaseError)
    def _db_error(e):
        log.error("database error on %s: %s", request.path, e)
        if is_json_api_path():
            return _error_response(503, "unavailable", "Database unavailable")
        raise e

    @app.errorhandler(HTTPException)
    def _http_error(e: HTTPException):
        if not is_json_api_path():
            return e
        code = _HTTP_CODES.get(e.code, "server_error" if (e.code or 500) >= 500 else "bad_request")
        headers = {}
        if e.code == 405 and getattr(e, "valid_methods", None):
            headers["Allow"] = ", ".join(e.valid_methods)
        return _error_response(e.code or 500, code, e.name, headers=headers)

    @app.errorhandler(Exception)
    def _unhandled(e: Exception):
        if not is_json_api_path():
            raise e
        log.exception("unhandled error on %s", request.path)
        return _error_response(500, "server_error", "Internal server error")

    @app.before_request
    def _public_preflight():
        if request.method == "OPTIONS" and is_public_path():
            return Response(status=204)

    @app.after_request
    def _public_headers(resp: Response):
        if not is_public_path():
            return resp
        # ---- CORS (no credentials; allow-origin echoes a listed origin) ----
        allowed = _allowed_origins()
        if allowed:
            resp.headers.add("Vary", "Origin")
            origin = (request.headers.get("Origin") or "").rstrip("/")
            if origin and origin in allowed:
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
                resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
                resp.headers["Access-Control-Expose-Headers"] = "ETag, Retry-After"
                resp.headers["Access-Control-Max-Age"] = "600"
        # ---- caching headers ----
        if resp.status_code >= 400:
            resp.headers["Cache-Control"] = "no-store"
        elif request.path in NO_STORE_PATHS:
            resp.headers["Cache-Control"] = "no-store"
        elif request.args.get(PREVIEW_PARAM):
            resp.headers["Cache-Control"] = "private, no-store"
            resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        elif (
            request.method in ("GET", "HEAD")
            and resp.status_code == 200
            and resp.mimetype == "application/json"
            and not resp.direct_passthrough
        ):
            body = resp.get_data()
            etag = '"' + hashlib.sha1(body).hexdigest()[:24] + '"'
            resp.headers["ETag"] = etag
            resp.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=300"
            inm = request.headers.get("If-None-Match", "")
            if inm and (inm.strip() == "*" or etag in [t.strip().removeprefix("W/") for t in inm.split(",")]):
                resp.status_code = 304
                resp.set_data(b"")
                resp.headers.pop("Content-Type", None)
        return resp
