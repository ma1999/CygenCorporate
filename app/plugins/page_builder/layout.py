"""Pure helpers of the page builder: manifest + layout validation and HTML sanitising.

No Flask / DB here so everything is unit-testable (``tests/test_logic.py``).

Layout document (stored verbatim in ``site_pages.draft_json`` / ``published_json``)::

    {"v": 1, "sections": [
        {"id", "hidden", "settings": {...}, "columns": [
            {"id", "span": 1-12, "settings": {...}, "widgets": [
                {"id", "type", "hidden", "settings": {...}}]}]}]}

Rules that keep content safe when a frontend is replaced or older than the data:

- a widget whose ``type`` is not in the theme manifest is KEPT (its settings are only JSON-sanitised) and reported in
  ``unknown``; the renderer simply skips it, nothing is deleted;
- known widgets only keep keys declared in the manifest, every value is coerced/clamped by its field type;
- rich text goes through an allow-list sanitiser; links/media paths are scheme-checked.
"""
from __future__ import annotations

import json
import re
import uuid
from html import escape
from html.parser import HTMLParser

from app.core import content as C

MAX_LAYOUT_BYTES = 1_000_000
MAX_SECTIONS = 60
MAX_COLUMNS = 12
MAX_WIDGETS = 200
MAX_MANIFEST_BYTES = 512 * 1024
MAX_MANIFEST_WIDGETS = 200
MAX_FIELDS = 60
MAX_REPEATER_ROWS = 60
MAX_DEPTH = 4
MAX_JSON_DEPTH = 16

FIELD_TYPES = ("text", "textarea", "richtext", "number", "select", "switch", "color", "image", "link", "icon",
               "entity", "repeater")
ENTITY_KINDS = ("category", "product", "project", "article", "brand", "tag", "sector", "article_category")
TEXT_LIMITS = {"text": 500, "textarea": 10_000, "richtext": 100_000}

THEME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{1,48}$")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,48}$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
SLUG_PART_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgba?\([0-9., %/]{3,40}\)|var\(--[a-z0-9-]{1,40}\)|transparent)$")
ICON_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
ENTITY_RE = re.compile(r"^[^\s<>\"'\\]{1,191}$")

# first path segments the frontend already serves (a custom page may not shadow them)
RESERVED_SLUGS = {
    "products", "product", "projects", "news", "services", "faq", "contact", "about", "search", "api", "admin",
    "assets", "login", "logout", "static", "_next", "robots.txt", "sitemap.xml", "favicon.ico", "preview", "home", "header", "footer", "pb-area",
}


class LayoutError(ValueError):
    pass


# ---------------------------------------------------------------------------
# HTML allow-list sanitiser (rich text fields)
# ---------------------------------------------------------------------------
_ALLOWED_TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "s", "ul", "ol", "li", "a", "h2", "h3", "h4", "h5", "blockquote",
    "span", "hr", "sub", "sup", "code",
}
_VOID = {"br", "hr"}
_DROP_CONTENT = {"script", "style", "iframe", "object", "embed", "template", "noscript", "svg", "math"}
_SAFE_HREF = re.compile(r"^(https?://|mailto:|tel:|/|#)[^\s<>\"']*$", re.I)


def safe_href(value) -> str:
    """Return ``value`` when it is a relative path, anchor or http(s)/mailto/tel URL; else ``""``."""
    v = (value or "").strip() if isinstance(value, str) else ""
    if not v or len(v) > 2000:
        return ""
    if v.startswith("//"):
        return ""
    return v if _SAFE_HREF.match(v) else ""


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list = []
        self.open: list = []
        self.skip = 0  # depth inside a dropped element

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in _ALLOWED_TAGS:
            return
        extra = ""
        if tag == "a":
            href = safe_href(dict(attrs).get("href"))
            if href:
                extra = f' href="{escape(href, quote=True)}"'
                if dict(attrs).get("target") == "_blank":
                    extra += ' target="_blank" rel="noopener noreferrer"'
        self.out.append(f"<{tag}{extra}>")
        if tag not in _VOID:
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in _DROP_CONTENT or self.skip:
            return
        if tag in _VOID:
            self.out.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag in _DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in _ALLOWED_TAGS or tag in _VOID or tag not in self.open:
            return
        while self.open:  # close any unclosed inner tags first
            top = self.open.pop()
            self.out.append(f"</{top}>")
            if top == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data, quote=False))

    def result(self) -> str:
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out)


def sanitize_html(src) -> str:
    if not isinstance(src, str) or not src.strip():
        return ""
    p = _Sanitizer()
    try:
        p.feed(src)
        p.close()
    except Exception:
        return escape(C.strip_tags(src), quote=False)
    return p.result()


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------
def _label(raw, fallback="") -> object:
    """A label is a plain string or an ``{lang: text}`` dict."""
    if isinstance(raw, dict):
        return {str(k)[:8]: C.strip_tags(str(v))[:200] for k, v in list(raw.items())[:12] if isinstance(v, str)}
    return C.strip_tags(str(raw))[:200] if isinstance(raw, str) and raw else fallback


def _json_safe(v, depth=0):
    """Plain JSON value (str/num/bool/None/list/dict) with bounded depth; anything else becomes None.
    The limit must exceed a whole layout document (page > section > column > widget > settings > repeater row > i18n text)."""
    if depth > MAX_JSON_DEPTH:
        return None
    if isinstance(v, (str, bool)) or v is None:
        return v[:20_000] if isinstance(v, str) else v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, list):
        return [_json_safe(x, depth + 1) for x in v[:200]]
    if isinstance(v, dict):
        return {str(k)[:64]: _json_safe(x, depth + 1) for k, x in list(v.items())[:200]}
    return None


def _norm_field(raw, errors, path, depth=0):
    if not isinstance(raw, dict):
        errors[path] = "field must be an object"
        return None
    name = raw.get("name")
    ftype = raw.get("type")
    if not isinstance(name, str) or not NAME_RE.match(name):
        errors[path] = "invalid field name"
        return None
    if ftype not in FIELD_TYPES:
        errors[path] = f"unknown field type '{ftype}'"
        return None
    f = {"name": name, "type": ftype, "label": _label(raw.get("label"), name)}
    if isinstance(raw.get("help"), (str, dict)):
        f["help"] = _label(raw["help"])
    if ftype in ("text", "textarea", "richtext"):
        f["i18n"] = bool(raw.get("i18n"))
        f["max"] = min(int(raw["max"]), TEXT_LIMITS[ftype]) if isinstance(raw.get("max"), int) and raw["max"] > 0 else TEXT_LIMITS[ftype]
    if ftype == "number":
        for k in ("min", "max", "step"):
            if isinstance(raw.get(k), (int, float)) and not isinstance(raw.get(k), bool):
                f[k] = raw[k]
    if ftype == "select":
        opts = []
        for o in (raw.get("options") or [])[:100]:
            if isinstance(o, dict) and isinstance(o.get("value"), (str, int)):
                opts.append({"value": o["value"], "label": _label(o.get("label"), str(o["value"]))})
            elif isinstance(o, (str, int)):
                opts.append({"value": o, "label": str(o)})
        f["options"] = opts
    if ftype == "entity":
        f["entity"] = raw.get("entity") if raw.get("entity") in ENTITY_KINDS else "category"
        f["multiple"] = bool(raw.get("multiple"))
    if ftype == "link":
        f["label_field"] = bool(raw.get("label_field"))
    if ftype == "repeater":
        if depth >= 2:
            errors[path] = "repeaters nest at most 2 levels"
            return None
        subs = []
        for i, sub in enumerate((raw.get("fields") or [])[:MAX_FIELDS]):
            nf = _norm_field(sub, errors, f"{path}.fields[{i}]", depth + 1)
            if nf:
                subs.append(nf)
        f["fields"] = subs
        f["max_rows"] = min(int(raw["max_rows"]), MAX_REPEATER_ROWS) if isinstance(raw.get("max_rows"), int) and raw["max_rows"] > 0 else MAX_REPEATER_ROWS
        f["item_label"] = _label(raw.get("item_label"), "")
    if "default" in raw:
        f["default"] = _json_safe(raw["default"])
    if isinstance(raw.get("group"), str):
        f["group"] = C.strip_tags(raw["group"])[:60]
    return f


def _norm_fields(raw, errors, path):
    out, seen = [], set()
    for i, f in enumerate((raw or [])[:MAX_FIELDS]):
        nf = _norm_field(f, errors, f"{path}[{i}]")
        if nf and nf["name"] not in seen:
            seen.add(nf["name"])
            out.append(nf)
    return out


def normalize_manifest(raw) -> tuple:
    """Validate a theme manifest sent by a frontend. Returns ``(manifest, errors)``; unusable input gives ``(None, errors)``."""
    errors: dict = {}
    if not isinstance(raw, dict):
        return None, {"_": "manifest must be an object"}
    theme = raw.get("theme")
    if not isinstance(theme, str) or not THEME_RE.match(theme):
        return None, {"theme": "theme must match [a-z0-9_-]{2,64}"}
    m = {
        "theme": theme, "name": _label(raw.get("name"), theme) or theme,
        "version": C.strip_tags(str(raw.get("version") or ""))[:40],
        "section_fields": _norm_fields(raw.get("section_fields"), errors, "section_fields"),
        "column_fields": _norm_fields(raw.get("column_fields"), errors, "column_fields"),
        "pages": [], "widgets": [],
    }
    keys = set()
    for i, p in enumerate((raw.get("pages") or [])[:50]):
        if not isinstance(p, dict) or not isinstance(p.get("key"), str) or not SLUG_PART_RE.match(p["key"]) or p["key"] in keys:
            errors[f"pages[{i}]"] = "invalid or duplicate page key"
            continue
        path = p.get("path") if isinstance(p.get("path"), str) and p["path"].startswith("/") else "/" + p["key"]
        role = p.get("role") if p.get("role") in ("page", "area", "template") else "page"
        entry = {"key": p["key"], "path": path[:191], "label": _label(p.get("label"), p["key"]), "role": role}
        if p.get("sample") in ENTITY_KINDS:    # template pages: which record the editor previews with
            entry["sample"] = p["sample"]
        if isinstance(p.get("layout"), dict):  # factory-default layout (equals the hard-coded page)
            entry["layout"] = _json_safe(p["layout"])
        keys.add(p["key"])
        m["pages"].append(entry)
    types = set()
    for i, w in enumerate((raw.get("widgets") or [])[:MAX_MANIFEST_WIDGETS]):
        if not isinstance(w, dict) or not isinstance(w.get("type"), str) or not TYPE_RE.match(w["type"]) or w["type"] in types:
            errors[f"widgets[{i}]"] = "invalid or duplicate widget type"
            continue
        types.add(w["type"])
        m["widgets"].append({
            "type": w["type"], "label": _label(w.get("label"), w["type"]),
            "category": C.strip_tags(str(w.get("category") or "general"))[:40],
            "icon": ICON_RE.match(str(w.get("icon") or "")) and w["icon"] or "ti-box",
            "description": _label(w.get("description")),
            "dynamic": bool(w.get("dynamic")),
            "fields": _norm_fields(w.get("fields"), errors, f"widgets[{i}].fields"),
            "defaults": _json_safe(w.get("defaults")) if isinstance(w.get("defaults"), dict) else {},
        })
    if len(json.dumps(m, ensure_ascii=False)) > MAX_MANIFEST_BYTES:
        return None, {"_": "manifest too large"}
    return m, errors


# ---------------------------------------------------------------------------
# settings coercion
# ---------------------------------------------------------------------------
def _i18n(value, langs, limit, strip=True, html=False):
    """Normalise a translatable value to ``{lang: text}`` (languages in ``langs`` + ``fa``)."""
    if isinstance(value, str):
        value = {"fa": value}
    if not isinstance(value, dict):
        return {}
    allowed = set(langs) | {"fa"}
    out = {}
    for lang, text in value.items():
        if lang not in allowed or not isinstance(text, str):
            continue
        text = sanitize_html(text) if html else (C.strip_tags(text) if strip else text)
        out[lang] = text.strip()[:limit] if not html else text[:limit]
    return out


def coerce_value(f, value, langs, errors, path):
    t = f["type"]
    if t in ("text", "textarea", "richtext"):
        limit = f.get("max", TEXT_LIMITS[t])
        if f.get("i18n"):
            return _i18n(value, langs, limit, html=(t == "richtext"))
        if not isinstance(value, str):
            return ""
        return sanitize_html(value)[:limit] if t == "richtext" else C.strip_tags(value).strip()[:limit]
    if t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            try:
                value = float(str(value).strip())
            except (TypeError, ValueError):
                return f.get("default")
        lo, hi = f.get("min"), f.get("max")
        if lo is not None and value < lo:
            value = lo
        if hi is not None and value > hi:
            value = hi
        return int(value) if float(value).is_integer() else value
    if t == "select":
        allowed = [o["value"] for o in f.get("options", [])]
        return value if value in allowed else f.get("default", allowed[0] if allowed else None)
    if t == "switch":
        return bool(value)
    if t == "color":
        return value.strip() if isinstance(value, str) and COLOR_RE.match(value.strip()) else ""
    if t == "image":
        v = C.norm_media_path(value) if isinstance(value, str) else ""
        return v if v and C.valid_media_path(v) and len(v) <= 500 else ""
    if t == "link":
        if isinstance(value, str):
            value = {"href": value}
        if not isinstance(value, dict):
            return {"href": "", "new_tab": False}
        out = {"href": safe_href(value.get("href")), "new_tab": bool(value.get("new_tab"))}
        if f.get("label_field"):
            out["label"] = _i18n(value.get("label"), langs, 200)
        return out
    if t == "icon":
        return value if isinstance(value, str) and ICON_RE.match(value) else ""
    if t == "entity":
        if f.get("multiple"):
            items = value if isinstance(value, list) else []
            return [v for v in items[:24] if isinstance(v, str) and ENTITY_RE.match(v)]
        return value if isinstance(value, str) and ENTITY_RE.match(value) else ""
    if t == "repeater":
        rows = value if isinstance(value, list) else []
        return [coerce_settings(r, f.get("fields", []), langs, errors, f"{path}[{i}]")
                for i, r in enumerate(rows[: f.get("max_rows", MAX_REPEATER_ROWS)]) if isinstance(r, dict)]
    return None


def coerce_settings(settings, fields, langs, errors, path="settings") -> dict:
    """Keep only declared keys, each coerced by its field type."""
    settings = settings if isinstance(settings, dict) else {}
    out = {}
    for f in fields:
        if f["name"] in settings:
            out[f["name"]] = coerce_value(f, settings[f["name"]], langs, errors, f"{path}.{f['name']}")
    return out


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------
def empty_layout() -> dict:
    return {"v": 1, "sections": []}


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# platform-level ("common") settings: every section / column / widget can carry them in ``node["common"]``.
# They are theme independent: the frontend renderer (PageRenderer) implements them for every widget.
# ---------------------------------------------------------------------------
INNER_ROW = "inner_row"          # built-in container widget: a row of columns inside a column (one level only)
MAX_INNER_COLUMNS = 6


def _cf(name, ftype, label, group, **kw):
    f = {"name": name, "type": ftype, "label": label, "group": group}
    if ftype in ("text", "textarea"):
        f.setdefault("i18n", False)
    f.update(kw)
    return f


def _opts(*pairs):
    return [{"value": v, "label": l} for v, l in pairs]


_ANIM_TYPES = _opts(("none", "بدون"), ("fade", "محو شدن"), ("slide-left", "از چپ"), ("slide-right", "از راست"),
                    ("slide-up", "از پایین"), ("slide-down", "از بالا"), ("zoom-in", "زوم ورودی"), ("zoom-out", "زوم خروجی"),
                    ("rotate", "چرخش"), ("flip", "برگشت (flip)"))
_EASINGS = _opts(("ease-out", "نرم (ease-out)"), ("ease-in-out", "ease-in-out"), ("linear", "خطی"), ("spring", "فنری"))
_HOVERS = _opts(("none", "بدون"), ("lift", "بالا رفتن"), ("scale", "بزرگ‌شدن"), ("glow", "سایه / درخشش"),
                ("tilt", "کج‌شدن"), ("brighten", "روشن‌تر شدن"))
_LOOPS = _opts(("none", "بدون"), ("float", "شناور"), ("pulse", "ضربان"), ("bounce", "جهش"), ("spin", "چرخش آهسته"),
               ("wiggle", "لرزش ملایم"))
_ALIGNS = _opts(("", "پیش‌فرض"), ("start", "شروع"), ("center", "وسط"), ("end", "پایان"))
_RADII = _opts(("", "پیش‌فرض"), ("none", "بدون"), ("sm", "کم"), ("md", "متوسط"), ("lg", "زیاد"), ("xl", "خیلی زیاد"), ("full", "کامل"))
_SHADOWS = _opts(("", "پیش‌فرض"), ("none", "بدون"), ("sm", "کم"), ("md", "متوسط"), ("lg", "زیاد"))

_SPACING = [
    _cf("margin_top", "number", "فاصلهٔ بیرونی بالا (px)", "style", min=0, max=400),
    _cf("margin_bottom", "number", "فاصلهٔ بیرونی پایین (px)", "style", min=0, max=400),
    _cf("padding_top", "number", "فاصلهٔ داخلی بالا (px)", "style", min=0, max=400),
    _cf("padding_bottom", "number", "فاصلهٔ داخلی پایین (px)", "style", min=0, max=400),
]
_BOX = [
    _cf("box_bg", "color", "رنگ پس‌زمینهٔ باکس", "style"),
    _cf("box_radius", "select", "گردی گوشه‌ها", "style", options=_RADII, default=""),
    _cf("box_shadow", "select", "سایه", "style", options=_SHADOWS, default=""),
    _cf("box_border", "switch", "حاشیه", "style"),
    _cf("box_border_color", "color", "رنگ حاشیه (دلخواه)", "style"),
    _cf("box_padding", "number", "فاصلهٔ داخلی همهٔ اطراف (px)", "style", min=0, max=200),
    _cf("max_width", "number", "حداکثر عرض (px، ۰ = بدون)", "style", min=0, max=2000),
    _cf("block_align", "select", "چینش باکس", "style", options=_ALIGNS, default=""),
    _cf("text_align", "select", "چینش متن", "style", options=_ALIGNS, default=""),
]
_MOTION = [
    _cf("anim_type", "select", "انیمیشن ورود (هنگام رسیدن اسکرول)", "motion", options=_ANIM_TYPES, default="none"),
    _cf("anim_duration", "number", "مدت (ثانیه)", "motion", min=0.1, max=5, step=0.1),
    _cf("anim_delay", "number", "تأخیر (ثانیه)", "motion", min=0, max=5, step=0.1),
    _cf("anim_distance", "number", "فاصلهٔ حرکت (px)", "motion", min=0, max=300),
    _cf("anim_easing", "select", "شتاب", "motion", options=_EASINGS, default="ease-out"),
    _cf("anim_repeat", "switch", "هر بار که دیده شد تکرار شود", "motion"),
    _cf("hover_effect", "select", "افکت هاور", "motion", options=_HOVERS, default="none"),
    _cf("loop_effect", "select", "حرکت مداوم", "motion", options=_LOOPS, default="none"),
    _cf("loop_seconds", "number", "مدت هر دور (ثانیه)", "motion", min=0.5, max=30, step=0.5),
]
_ADVANCED = [
    _cf("hide_desktop", "switch", "مخفی در دسکتاپ", "advanced"),
    _cf("hide_tablet", "switch", "مخفی در تبلت", "advanced"),
    _cf("hide_mobile", "switch", "مخفی در موبایل", "advanced"),
    _cf("css_id", "text", "شناسهٔ CSS (id)", "advanced", max=60),
    _cf("css_class", "text", "کلاس CSS", "advanced", max=120),
]

COMMON_FIELDS = {
    "widget": _SPACING + _BOX + _MOTION + _ADVANCED,
    "column": _SPACING + _BOX + _MOTION + _ADVANCED,
    "section": _SPACING + [
        _cf("min_height", "number", "حداقل ارتفاع (px)", "style", min=0, max=1600),
        _cf("content_valign", "select", "چینش عمودی ستون‌ها", "style", options=_opts(("", "پیش‌فرض"), ("start", "بالا"), ("center", "وسط"), ("end", "پایین")), default=""),
        _cf("gap_x", "select", "فاصلهٔ ستون‌ها", "style", options=_opts(("", "پیش‌فرض"), ("none", "بدون"), ("sm", "کم"), ("md", "متوسط"), ("lg", "زیاد")), default=""),
        _cf("grad_from", "color", "گرادیانت: از رنگ", "style"),
        _cf("grad_to", "color", "گرادیانت: تا رنگ", "style"),
        _cf("grad_angle", "number", "گرادیانت: زاویه (درجه)", "style", min=0, max=360),
        _cf("bg_fixed", "switch", "تصویر پس‌زمینهٔ ثابت", "style"),
        _cf("parallax", "number", "پارالاکس تصویر پس‌زمینه (۰ تا ۶۰)", "motion", min=0, max=60),
        _cf("anim_stagger", "number", "تأخیر پله‌ای بین ستون‌ها (ثانیه)", "motion", min=0, max=2, step=0.05),
        _cf("sticky", "switch", "چسبیده به بالا هنگام اسکرول", "advanced"),
    ] + _MOTION + _ADVANCED,
}


def _clean_common(raw, kind, langs, errors, path) -> dict:
    out = coerce_settings(raw, COMMON_FIELDS[kind], langs, errors, path)
    if "css_id" in out:
        out["css_id"] = re.sub(r"[^A-Za-z0-9_-]", "", out["css_id"])
    if "css_class" in out:
        out["css_class"] = " ".join(re.sub(r"[^A-Za-z0-9_-]", "", c) for c in out["css_class"].split() if c)
    return {k: v for k, v in out.items() if not (v == "" or v is None or v is False)}   # 0 is a real value (explicit margin)


def _span(v, default=None):
    return v if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 12 else default


def validate_layout(raw, manifest, langs) -> tuple:
    """Return ``(layout, errors, unknown_types)``. Raises :class:`LayoutError` when the document is unusable
    (not an object, too large, too many nodes)."""
    if not isinstance(raw, dict):
        raise LayoutError("layout must be an object")
    try:
        size = len(json.dumps(raw, ensure_ascii=False))
    except (TypeError, ValueError):
        raise LayoutError("layout is not valid JSON")
    if size > MAX_LAYOUT_BYTES:
        raise LayoutError("layout is too large")
    sections = raw.get("sections")
    if not isinstance(sections, list):
        raise LayoutError("layout.sections must be a list")
    if len(sections) > MAX_SECTIONS:
        raise LayoutError(f"at most {MAX_SECTIONS} sections")

    widgets_by_type = {w["type"]: w for w in (manifest or {}).get("widgets", [])}
    section_fields = (manifest or {}).get("section_fields", [])
    column_fields = (manifest or {}).get("column_fields", [])
    errors: dict = {}
    unknown: set = set()
    seen_ids: set = set()
    count = {"widgets": 0}

    def take_id(value, prefix):
        v = value if isinstance(value, str) and ID_RE.match(value) and value not in seen_ids else _new_id(prefix)
        seen_ids.add(v)
        return v

    def do_widgets(items, path, depth):
        out = []
        for wi, w in enumerate(items if isinstance(items, list) else []):
            if not isinstance(w, dict) or not isinstance(w.get("type"), str):
                continue
            count["widgets"] += 1
            if count["widgets"] > MAX_WIDGETS:
                raise LayoutError(f"at most {MAX_WIDGETS} widgets per page")
            wpath = f"{path}.widgets[{wi}]"
            wtype = w["type"][:49]
            node = {"id": take_id(w.get("id"), "w"), "type": wtype, "hidden": bool(w.get("hidden"))}
            if wtype == INNER_ROW:
                if depth >= 1:
                    raise LayoutError("rows can be nested only one level deep")
                node["settings"] = {}
                node["columns"] = do_columns(w.get("columns"), wpath, depth + 1, MAX_INNER_COLUMNS)
            else:
                wdef = widgets_by_type.get(wtype)
                if wdef:
                    node["settings"] = coerce_settings(w.get("settings"), wdef["fields"], langs, errors, wpath + ".settings")
                else:
                    unknown.add(wtype)
                    node["settings"] = _json_safe(w.get("settings")) if isinstance(w.get("settings"), dict) else {}
            node["common"] = _clean_common(w.get("common"), "widget", langs, errors, wpath + ".common")
            out.append(node)
        return out

    def do_columns(items, path, depth, limit=MAX_COLUMNS):
        items = items if isinstance(items, list) else []
        if len(items) > limit:
            raise LayoutError(f"at most {limit} columns per row")
        out = []
        for ci, c in enumerate(items):
            if not isinstance(c, dict):
                continue
            cpath = f"{path}.columns[{ci}]"
            col = {"id": take_id(c.get("id"), "c"), "span": _span(c.get("span"), 12)}
            for key in ("span_tablet", "span_mobile"):
                if _span(c.get(key)):
                    col[key] = c[key]
            col["settings"] = coerce_settings(c.get("settings"), column_fields, langs, errors, cpath)
            col["common"] = _clean_common(c.get("common"), "column", langs, errors, cpath + ".common")
            col["widgets"] = do_widgets(c.get("widgets"), cpath, depth)
            out.append(col)
        return out

    out_sections = []
    for si, s in enumerate(sections):
        if not isinstance(s, dict):
            continue
        spath = f"sections[{si}]"
        out_sections.append({
            "id": take_id(s.get("id"), "s"), "hidden": bool(s.get("hidden")),
            "settings": coerce_settings(s.get("settings"), section_fields, langs, errors, spath),
            "common": _clean_common(s.get("common"), "section", langs, errors, spath + ".common"),
            "columns": do_columns(s.get("columns"), spath, 0),
        })
    return {"v": 1, "sections": out_sections}, errors, sorted(unknown)


def check_slug(slug) -> str:
    """Normalise and validate a custom page slug (``a/b`` nesting allowed, max 3 parts). Returns the slug or raises."""
    s = (slug or "").strip().strip("/").lower() if isinstance(slug, str) else ""
    parts = s.split("/") if s else []
    if not parts or len(parts) > 3 or len(s) > 150 or not all(SLUG_PART_RE.match(p) for p in parts):
        raise LayoutError("نشانی (slug) فقط شامل حروف انگلیسی کوچک، عدد و خط تیره است (حداکثر ۳ بخش با /)")
    if parts[0] in RESERVED_SLUGS:
        raise LayoutError(f"«{parts[0]}» نشانی رزرو شده است")
    return s


def seo_clean(raw, langs) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    og = C.norm_media_path(raw.get("og_image")) if isinstance(raw.get("og_image"), str) else ""
    return {
        "title": _i18n(raw.get("title"), langs, 200), "description": _i18n(raw.get("description"), langs, 400),
        "og_image": og if og and C.valid_media_path(og) else "", "noindex": bool(raw.get("noindex")),
    }
