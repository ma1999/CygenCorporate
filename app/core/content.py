"""Shared helpers for multilingual content.

Used by the content plugins (products, categories, brands, projects, ...) and
by the public JSON API. Nothing here touches Flask routing; it is plain
functions so it can also be used from scripts and tests.

Conventions (see docs/frontend-api.md):
- an i18n field is stored as a JSON object ``{"fa": "...", "en": "..."}`` in a
  ``<field>_i18n`` column; ``fa`` is the source language
- list-like i18n fields store ``{"fa": [...], "en": [...]}``
- times are naive UTC ``datetime`` in the DB and ISO-8601 ``...Z`` in the API
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import json
import mimetypes
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

SOURCE_LANG = "fa"
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
UPLOAD_ROOT = ROOT_DIR / "uploads"
UPLOAD_PREFIX = "/assets/uploads/"

# ---------------------------------------------------------------------------
# text normalisation (search, slugs)
# ---------------------------------------------------------------------------
_DIGIT_MAP = {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_DIGIT_MAP.update({ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")})
_CHAR_MAP = {
    ord("ي"): "ی", ord("ى"): "ی", ord("ك"): "ک", ord("ة"): "ه", ord("ۀ"): "ه",
    ord("أ"): "ا", ord("إ"): "ا", ord("ٱ"): "ا",
}
_STRIP_RE = re.compile(r"[‌‍‎‏ـً-ٰٟ﻿]")
_WS_RE = re.compile(r"\s+")


def normalize_search(text) -> str:
    """Lower-case, unify Arabic/Persian letter + digit variants, drop ZWNJ,
    kashida and diacritics, collapse whitespace."""
    if text is None:
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    s = s.translate(_DIGIT_MAP).translate(_CHAR_MAP)
    s = _STRIP_RE.sub("", s).lower()
    return _WS_RE.sub(" ", s).strip()


def escape_like(s: str) -> str:
    """Escape LIKE wildcards (``\\`` ``%`` ``_``)."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_TAG_RE = re.compile(r"</?[a-zA-Z!][^>]*>")


def strip_tags(s: str) -> str:
    """Remove HTML tags from user-typed plain text (keeps ``a < b``)."""
    return _TAG_RE.sub("", s or "")


def html_to_text(src) -> str:
    """Convert legacy HTML (old ``products.description``) to plain text with
    ``\\n`` between paragraphs."""
    if not src:
        return ""
    s = re.sub(r"(?i)<\s*br\s*/?>", "\n", str(src))
    s = re.sub(r"(?i)</\s*(p|div|li|h[1-6]|tr)\s*>", "\n\n", s)
    s = _TAG_RE.sub("", s)
    s = _html.unescape(s).replace("\r\n", "\n").replace("\r", "\n")
    s = "\n".join(line.strip() for line in s.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def split_paragraphs(text) -> list:
    """Paragraphs are separated by blank lines."""
    if not text:
        return []
    parts = re.split(r"\n\s*\n", str(text).replace("\r\n", "\n").replace("\r", "\n"))
    return [p.strip() for p in parts if p.strip()]


def lines_to_list(text) -> list:
    if not text:
        return []
    return [ln.strip() for ln in str(text).replace("\r\n", "\n").split("\n") if ln.strip()]


# ---------------------------------------------------------------------------
# slugs
# ---------------------------------------------------------------------------
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SLUG_MAX = 120

_TRANSLIT = {
    "ا": "a", "آ": "a", "ب": "b", "پ": "p", "ت": "t", "ث": "s", "ج": "j", "چ": "ch",
    "ح": "h", "خ": "kh", "د": "d", "ذ": "z", "ر": "r", "ز": "z", "ژ": "zh", "س": "s",
    "ش": "sh", "ص": "s", "ض": "z", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh", "ف": "f",
    "ق": "gh", "ک": "k", "گ": "g", "ل": "l", "م": "m", "ن": "n", "و": "v", "ه": "h",
    "ی": "y", "ئ": "y", "ؤ": "v", "ء": "", "ّ": "",
}


def slugify(text) -> str:
    """ASCII slug from Latin text or transliterated Persian ('' if nothing)."""
    s = normalize_search(text)
    s = "".join(_TRANSLIT.get(ch, ch) for ch in s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:SLUG_MAX].strip("-")


def valid_slug(s) -> bool:
    return bool(s) and len(s) <= SLUG_MAX and bool(SLUG_RE.match(s))


# ---------------------------------------------------------------------------
# i18n values
# ---------------------------------------------------------------------------
def parse_i18n(raw) -> dict:
    """Decode a stored ``*_i18n`` JSON value (str/bytes/dict/None) to a dict."""
    if raw in (None, "", b""):
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def dump_i18n(d: dict) -> str | None:
    """Encode for storage; drops empty values; ``None`` when nothing is left."""
    clean = {}
    for k, v in (d or {}).items():
        if isinstance(v, list):
            v = [x for x in v if isinstance(x, str) and x.strip()]
            if v:
                clean[k] = v
        elif isinstance(v, str) and v.strip():
            clean[k] = v
    return json.dumps(clean, ensure_ascii=False) if clean else None


def i18n_text(raw, fa_fallback="", langs=None) -> dict:
    """``I18nText`` for the API: ``fa`` always present (maybe ``""``); other
    languages only when non-empty and (if ``langs`` given) active."""
    d = parse_i18n(raw)
    out = {"fa": d.get("fa") if isinstance(d.get("fa"), str) and d.get("fa") else (fa_fallback or "")}
    for code, val in d.items():
        if code == SOURCE_LANG or not isinstance(val, str) or not val.strip():
            continue
        if langs is not None and code not in langs:
            continue
        out[code] = val
    return out


def i18n_list(raw, fa_fallback=None, langs=None) -> dict:
    """``I18nList`` for the API (``fa`` always a list)."""
    d = parse_i18n(raw)
    fa = d.get("fa")
    out = {"fa": [x for x in fa if isinstance(x, str)] if isinstance(fa, list) and fa else list(fa_fallback or [])}
    for code, val in d.items():
        if code == SOURCE_LANG or not isinstance(val, list):
            continue
        items = [x for x in val if isinstance(x, str) and x.strip()]
        if not items:
            continue
        if langs is not None and code not in langs:
            continue
        out[code] = items
    return out


def parse_list(raw) -> list:
    """Decode a stored JSON array column (non-i18n list)."""
    if raw in (None, "", b""):
        return []
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, list):
        return raw
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return data if isinstance(data, list) else []


def all_text_values(*raws) -> list:
    """Flatten i18n dicts/lists into every string they contain (search text)."""
    out = []
    for raw in raws:
        d = parse_i18n(raw) if not isinstance(raw, dict) else raw
        for v in d.values():
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, list):
                out.extend(x for x in v if isinstance(x, str))
    return out


# ---------------------------------------------------------------------------
# time
# ---------------------------------------------------------------------------
def utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None, microsecond=0)


def iso(dt) -> str | None:
    """Naive-UTC datetime -> ``2026-09-07T17:15:14Z``."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if isinstance(dt, _dt.datetime):
        if dt.tzinfo is not None:
            dt = dt.astimezone(_dt.timezone.utc).replace(tzinfo=None)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(dt, _dt.date):
        return dt.strftime("%Y-%m-%dT00:00:00Z")
    return None


_offset_cache = {"v": None, "t": 0.0}
_offset_lock = threading.Lock()


async def server_utc_offset_seconds(db) -> int:
    """Seconds the MySQL server clock is ahead of UTC (cached for an hour).

    Legacy ``TIMESTAMP DEFAULT CURRENT_TIMESTAMP`` columns come back in the
    server's local time; this lets us convert them to real UTC."""
    now = time.time()
    with _offset_lock:
        if _offset_cache["v"] is not None and now - _offset_cache["t"] < 3600:
            return _offset_cache["v"]
    row = await db.fetch("SELECT TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), NOW()) AS d", one=True)
    off = int(row["d"]) if row and row.get("d") is not None else 0
    # round to the nearest minute (the two calls are microseconds apart)
    off = int(round(off / 60.0)) * 60
    with _offset_lock:
        _offset_cache.update(v=off, t=now)
    return off


def local_to_utc(dt, offset_seconds: int):
    if isinstance(dt, _dt.datetime):
        return dt - _dt.timedelta(seconds=offset_seconds)
    return dt


# ---------------------------------------------------------------------------
# media
# ---------------------------------------------------------------------------
_media_cache: dict = {}
_media_lock = threading.Lock()


def norm_media_path(value) -> str:
    """Store media as ``/assets/uploads/...`` (leading slash) or an external
    ``http(s)://`` URL. Returns ``""`` for empty input."""
    v = (value or "").strip().replace("\\", "/")
    if not v:
        return ""
    if re.match(r"^https?://", v, re.I):
        return v
    return "/" + v.lstrip("/")


def valid_media_path(value) -> bool:
    v = norm_media_path(value)
    if not v:
        return True
    if re.match(r"^https?://[^\s]+$", v, re.I):
        return True
    return v.startswith("/") and ".." not in v.split("/") and not re.search(r"[\s<>\"']", v)


def public_base_url(req=None) -> str:
    """Origin used for absolute media/download URLs."""
    env = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if env:
        return env
    if req is None:
        return ""
    proto = (req.headers.get("X-Forwarded-Proto") or req.scheme or "http").split(",")[0].strip()
    host = (req.headers.get("X-Forwarded-Host") or req.host or "").split(",")[0].strip()
    return f"{proto}://{host}"


def abs_url(value, base: str) -> str | None:
    v = norm_media_path(value)
    if not v:
        return None
    if re.match(r"^https?://", v, re.I):
        return v
    return f"{base}{v}"


def media_meta(value) -> dict:
    """``{width, height, mime}`` for a stored media path (disk lookups are
    cached by mtime). External URLs give only a guessed mime."""
    v = norm_media_path(value)
    mime = mimetypes.guess_type(v.split("?")[0])[0]
    if not v.startswith(UPLOAD_PREFIX):
        return {"width": None, "height": None, "mime": mime}
    rel = v[len(UPLOAD_PREFIX):]
    try:
        p = (UPLOAD_ROOT / rel).resolve()
        p.relative_to(UPLOAD_ROOT.resolve())
        st = p.stat()
    except (OSError, ValueError):
        return {"width": None, "height": None, "mime": mime}
    key = (str(p), st.st_mtime_ns, st.st_size)
    with _media_lock:
        hit = _media_cache.get(key)
    if hit:
        return hit
    w = h = None
    if (mime or "").startswith("image/") and mime != "image/svg+xml":
        try:
            from PIL import Image

            with Image.open(p) as im:
                w, h = im.width, im.height
        except Exception:
            w = h = None
    meta = {"width": w, "height": h, "mime": mime}
    with _media_lock:
        if len(_media_cache) > 2000:
            _media_cache.clear()
        _media_cache[key] = meta
    return meta


def media_obj(value, alt_raw, base: str, langs=None) -> dict | None:
    """The API ``Media`` object (``None`` when no image)."""
    url = abs_url(value, base)
    if not url:
        return None
    meta = media_meta(value)
    return {
        "url": url,
        "alt": i18n_text(alt_raw, "", langs),
        "width": meta["width"],
        "height": meta["height"],
        "mime": meta["mime"],
    }


def fmt_size(n) -> str:
    """``2.4 MB`` (English units, Latin digits)."""
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def phone_tel(phone) -> str | None:
    """``+98 21 8865 4200`` -> ``+982188654200`` (only ``+`` and digits)."""
    s = normalize_search(phone or "")
    out = re.sub(r"[^0-9+]", "", s)
    if "+" in out:
        out = ("+" if out.startswith("+") else "") + out.replace("+", "")
    return out or None


def coords_label(lat, lng) -> str | None:
    if lat is None or lng is None:
        return None
    lat, lng = float(lat), float(lng)
    return f"{abs(lat):.4f}° {'N' if lat >= 0 else 'S'}, {abs(lng):.4f}° {'E' if lng >= 0 else 'W'}"


def reading_time_minutes(paragraph_groups) -> int:
    """≈200 words/minute over all given texts, minimum 1."""
    words = 0
    for text in paragraph_groups:
        words += len(re.findall(r"\S+", text or ""))
    return max(1, round(words / 200.0))
