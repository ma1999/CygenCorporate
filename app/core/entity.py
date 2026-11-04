"""Spec-driven entity engine (admin forms + persistence).

A plugin describes an entity declaratively (``Entity`` / ``Field`` / ``Child``)
and gets:

- schema declaration (``Entity.declare(schema)``) – additive columns/tables
- multilingual storage (``<field>_i18n`` JSON columns, ``fa`` mirrored into an
  optional legacy column)
- form parsing with the "absent field = untouched, present-but-empty = clear"
  rule, server-side validation with per-field messages, values preserved on
  error
- transactional save of the row *and* its repeater children
- generic admin routes (list/search/filter/sort/paginate, create, edit,
  delete, toggle) rendered with ``templates/admin_entity/*``

Public API serialisation stays in each plugin (it differs per entity).
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import re
from typing import Callable

from flask import current_app, request

from . import content as C
from .database import DatabaseError

UNSET = object()
TRUE_VALUES = ("1", "true", "on", "yes", "y")
PAGE_SIZE = 20

PUBLISHED_SQL = "status='published' AND (published_at IS NULL OR published_at <= UTC_TIMESTAMP())"


def published_sql(alias: str = "") -> str:
    a = f"{alias}." if alias else ""
    return f"{a}status='published' AND ({a}published_at IS NULL OR {a}published_at <= UTC_TIMESTAMP())"


def fa_sql(col: str, fallback: str = "''") -> str:
    """SQL expression: Persian value of an ``*_i18n`` JSON column."""
    return f"COALESCE(NULLIF(JSON_UNQUOTE(JSON_EXTRACT({col}, '$.fa')), ''), {fallback})"


def lang_sql(col: str, lang: str, fallback: str = "''") -> str:
    """SQL expression: value for ``lang`` falling back to ``fa`` then ``fallback``."""
    lang = re.sub(r"[^a-z0-9_-]", "", (lang or "fa").lower()) or "fa"
    return (
        f"COALESCE(NULLIF(JSON_UNQUOTE(JSON_EXTRACT({col}, '$.{lang}')), ''), "
        f"NULLIF(JSON_UNQUOTE(JSON_EXTRACT({col}, '$.fa')), ''), {fallback})"
    )


class FormError(Exception):
    """Raised inside a transaction to roll back and report field errors."""

    def __init__(self, errors: dict):
        super().__init__("form errors")
        self.errors = errors


class DeleteBlocked(Exception):
    pass


# ---------------------------------------------------------------------------
# field
# ---------------------------------------------------------------------------
class Field:
    """One editable attribute.

    kinds: text textarea slug url email hex phone int float bool select datetime
           fk media list lines paragraphs
    ``lines``/``paragraphs`` are list-valued: one item per line / per
    blank-line separated block. With ``i18n=True`` they are stored per
    language; ``list`` is a language-independent list of strings.
    """

    def __init__(
        self, name, kind="text", label=None, *, i18n=False, required=False, min=None, max=None,
        options=None, options_fn=None, default=None, help="", legacy=None, legacy_html=False,
        rows=3, ltr=False, ref=None, label_sql=None, ref_where="", sql=None, placeholder="",
        publish_required=False, counter=None, companion_of=None, max_items=60, max_item_len=300,
        alt=True, declare=True, alt_legacy=None,
    ):
        self.name = name
        if kind in ("lines", "paragraphs") and not i18n:
            kind = "list"  # language-independent list of strings
        # "tokens": list of strings typed one per line but NOT stored in a column;
        # the owning plugin persists them (many-to-many) from ``after_save``
        self.virtual = kind == "tokens"
        if kind == "tokens":
            kind = "list"
        self.kind = kind
        self.label = label or name
        self.i18n = i18n
        self.required = required
        self.min = min
        self.max = max
        self.options = options
        self.options_fn = options_fn
        self.default = default
        self.help = help
        self.legacy = legacy
        self.legacy_html = legacy_html
        self.rows = rows
        self.ltr = ltr or kind in ("slug", "url", "email", "hex", "phone")
        self.ref = ref
        self.label_sql = label_sql
        self.ref_where = ref_where
        self.sql = sql
        self.placeholder = placeholder
        self.publish_required = publish_required
        self.counter = counter
        self.companion_of = companion_of
        self.max_items = max_items
        self.max_item_len = max_item_len
        self.alt_field = None
        self.alt = alt  # media only: add a translatable alt-text companion field
        self.declare = declare  # False: column already declared elsewhere (legacy tables)
        self.alt_legacy = alt_legacy  # media only: legacy single-language alt column to mirror fa into

    # ---- schema ----
    @property
    def is_list(self):
        return self.kind in ("lines", "paragraphs", "list")

    def columns(self) -> dict:
        n = self.name
        if self.virtual:
            return {}
        if self.i18n:
            # the ``<name>_i18n`` column is always new; ``declare=False`` only
            # concerns the pre-existing legacy single-language column
            return {f"{n}_i18n": self.sql or "LONGTEXT NULL"}
        if not self.declare:
            return {}
        if self.sql:
            return {n: self.sql}
        k = self.kind
        if k == "media":
            return {n: "VARCHAR(600) NULL"}
        if k == "list":
            return {n: "LONGTEXT NULL"}
        sql = {
            "text": f"VARCHAR({self.max or 255}) NULL",
            "textarea": "TEXT NULL",
            "slug": "VARCHAR(191) NULL UNIQUE",
            "url": "VARCHAR(500) NULL",
            "email": "VARCHAR(200) NULL",
            "hex": "VARCHAR(9) NULL",
            "phone": "VARCHAR(60) NULL",
            "int": "INT NULL",
            "float": "DOUBLE NULL",
            "bool": "TINYINT(1) NOT NULL DEFAULT 0",
            "select": "VARCHAR(64) NULL",
            "datetime": "DATETIME NULL",
            "fk": "INT NULL",
        }[k]
        return {n: sql}

    # ---- form -> raw ----
    def read(self, form, langs):
        """Return UNSET when the field is absent from the form."""
        n, k = self.name, self.kind
        if self.i18n:
            out = {}
            for code in langs:
                key = f"{n}__{code}"
                if key in form:
                    out[code] = self._read_text(form.get(key, ""))
            if "fa" not in out and n in form:  # legacy single-input alias
                out["fa"] = self._read_text(form.get(n, ""))
            return out if out else UNSET
        if n not in form:
            return UNSET
        return self._read_text(form.get(n, ""))

    def _read_text(self, raw):
        raw = raw if raw is not None else ""
        if self.kind == "paragraphs":
            return C.split_paragraphs(C.strip_tags(raw))
        if self.kind in ("lines", "list"):
            return C.lines_to_list(C.strip_tags(raw))
        if self.kind in ("text", "textarea"):
            return C.strip_tags(str(raw)).strip() if self.kind == "text" else C.strip_tags(str(raw)).replace("\r\n", "\n").strip()
        return str(raw).strip()

    # ---- raw/db -> typed ----
    def empty_value(self):
        if self.default is not None:
            return self.default
        if self.i18n:
            return {}
        if self.is_list:
            return []
        if self.kind == "bool":
            return False
        return None if self.kind in ("int", "float", "datetime", "fk") else ""

    def from_row(self, row):
        n = self.name
        if self.i18n:
            d = C.parse_i18n(row.get(f"{n}_i18n"))
            if self.is_list:
                d = {k: v for k, v in d.items() if isinstance(v, list)}
                if "fa" not in d and self.legacy and row.get(self.legacy):
                    d["fa"] = C.split_paragraphs(C.html_to_text(row[self.legacy])) if self.kind == "paragraphs" else C.lines_to_list(row[self.legacy])
                return d
            d = {k: v for k, v in d.items() if isinstance(v, str)}
            if not d.get("fa") and self.legacy and row.get(self.legacy):
                v = row[self.legacy]
                d["fa"] = C.html_to_text(v) if self.legacy_html else str(v)
            return d
        v = row.get(n)
        if self.kind == "bool":
            return bool(v)
        if self.kind == "list":
            return C.parse_list(v)
        if v is None and self.kind not in ("int", "float", "datetime", "fk"):
            return ""
        return v

    # ---- validation / coercion ----
    def coerce(self, value, errors: dict, key: str, langs, grandfather=None):
        """Return the typed value; append Persian messages to ``errors[key]``.

        ``grandfather``: a pre-existing value (legacy slug) that is accepted
        as is even if it would not pass today's format rules."""
        k = self.kind
        label = self.label

        def err(msg):
            errors.setdefault(key, msg)

        if self.i18n:
            d = dict(value or {})
            out = {}
            for code, v in d.items():
                if self.is_list:
                    v = [str(x).strip()[: self.max_item_len] for x in (v or []) if str(x).strip()]
                    if len(v) > self.max_items:
                        err(f"«{label}»: حداکثر {self.max_items} مورد مجاز است")
                    if v:
                        out[code] = v
                else:
                    v = (v or "")
                    v = v if isinstance(v, str) else str(v)
                    v = v.strip() if k != "textarea" else v.strip()
                    if self.max and len(v) > self.max:
                        err(f"«{label}» ({code}) بیش از {self.max} نویسه است")
                    if self.min and v and len(v) < self.min:
                        err(f"«{label}» ({code}) حداقل {self.min} نویسه باشد")
                    if v:
                        out[code] = v
            if self.required and not out.get("fa"):
                err(f"«{label}» (فارسی) الزامی است")
            return out

        if self.is_list:
            items = [str(x).strip() for x in (value or []) if str(x).strip()]
            if len(items) > self.max_items:
                err(f"«{label}»: حداکثر {self.max_items} مورد مجاز است")
            if any(len(x) > self.max_item_len for x in items):
                err(f"«{label}»: هر مورد حداکثر {self.max_item_len} نویسه")
            if self.required and not items:
                err(f"«{label}» الزامی است")
            return items

        if k == "bool":
            if isinstance(value, str):
                return value.strip().lower() in TRUE_VALUES
            return bool(value)

        if k in ("int", "float", "fk"):
            if value is None or (isinstance(value, str) and not value.strip()):
                if self.required:
                    err(f"«{label}» الزامی است")
                return None
            try:
                num = float(value) if k == "float" else int(str(value).strip())
            except (TypeError, ValueError):
                err(f"«{label}» باید عدد معتبر باشد")
                return None
            if self.min is not None and num < self.min:
                err(f"«{label}» نباید کمتر از {self.min} باشد")
            if self.max is not None and num > self.max:
                err(f"«{label}» نباید بیشتر از {self.max} باشد")
            return num

        if k == "datetime":
            if value in (None, ""):
                if self.required:
                    err(f"«{label}» الزامی است")
                return None
            if isinstance(value, _dt.datetime):
                return value
            s = str(value).strip().replace("T", " ")
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    return _dt.datetime.strptime(s, fmt)
                except ValueError:
                    continue
            err(f"«{label}» تاریخ/زمان معتبر نیست")
            return None

        # string-like
        s = "" if value is None else str(value).strip()
        if k == "media":
            s = C.norm_media_path(s)
            if s and not C.valid_media_path(s):
                err(f"«{label}»: آدرس تصویر نامعتبر است")
            if s and len(s) > 600:
                err(f"«{label}»: آدرس خیلی طولانی است")
            if self.required and not s:
                err(f"«{label}» الزامی است")
            return s
        if not s:
            if self.required:
                err(f"«{label}» الزامی است")
            return ""
        if self.max and len(s) > self.max:
            err(f"«{label}» بیش از {self.max} نویسه است")
        if self.min and len(s) < self.min:
            err(f"«{label}» حداقل {self.min} نویسه باشد")
        if k == "slug":
            if grandfather is not None and s == grandfather:
                return s  # existing (possibly Persian / spaced) slug stays untouched
            s = s.lower()
            if not C.valid_slug(s):
                err("slug فقط شامل حروف کوچک انگلیسی، عدد و خط تیره (مثل my-product-1) باشد")
        elif k == "email":
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s) or len(s) > 200:
                err(f"«{label}»: ایمیل معتبر نیست")
        elif k == "url":
            if not re.match(r"^(https?://|tg://|mailto:)\S+$", s, re.I):
                err(f"«{label}»: آدرس باید با https:// (یا http://) شروع شود")
        elif k == "hex":
            if not re.match(r"^#[0-9a-fA-F]{6}$", s):
                err(f"«{label}»: رنگ باید به شکل #rrggbb باشد")
            s = s.lower()
        elif k == "select":
            valid = [o[0] for o in (self.options or [])]
            if self.options is not None and s not in valid:
                err(f"«{label}»: مقدار نامعتبر")
        return s

    # ---- typed -> db columns ----
    def to_db(self, value) -> dict:
        n = self.name
        if self.virtual:
            return {}
        if self.i18n:
            cols = {f"{n}_i18n": C.dump_i18n(value or {})}
            if self.legacy:
                fa = (value or {}).get("fa")
                if self.is_list:
                    cols[self.legacy] = "\n".join(fa or []) if fa else None
                else:
                    cols[self.legacy] = fa or ("" if self.required else None)
            return cols
        k = self.kind
        if k == "list":
            return {n: json.dumps(value, ensure_ascii=False) if value else None}
        if k == "bool":
            return {n: 1 if value else 0}
        if k in ("int", "float", "fk", "datetime"):
            return {n: value}
        return {n: (value if value not in ("", None) else None)}


# ---------------------------------------------------------------------------
# child (repeater) table
# ---------------------------------------------------------------------------
class Child:
    """Rows owned by a parent (specs, variants, gallery, sections, ...).

    Saved with replace-all semantics inside the parent's transaction."""

    def __init__(self, key, table, fk, label, fields, *, order="sort_order, id", max_rows=100, item_label="ردیف", help=""):
        self.key = key
        self.table = table
        self.fk = fk
        self.label = label
        self.fields = expand_fields(fields)
        self.order = order
        self.max_rows = max_rows
        self.item_label = item_label
        self.help = help

    def declare(self, schema):
        cols = {"id": "INT AUTO_INCREMENT PRIMARY KEY", self.fk: "INT NOT NULL", "sort_order": "INT NOT NULL DEFAULT 0"}
        for f in self.fields:
            cols.update(f.columns())
        schema.register_table(self.table, cols)

    def read(self, form, langs):
        """Rows from the form; UNSET if the group marker is absent."""
        if f"{self.key}__present" not in form:
            return UNSET
        idxs = set()
        pat = re.compile(rf"^{re.escape(self.key)}-(\d+)-")
        for k in form.keys():
            m = pat.match(k)
            if m:
                idxs.add(int(m.group(1)))
        rows = []
        for i in sorted(idxs):
            sub = {k[len(f"{self.key}-{i}-"):]: form.get(k) for k in form.keys() if k.startswith(f"{self.key}-{i}-")}
            row = {}
            for f in self.fields:
                v = f.read(sub, langs)
                row[f.name] = f.empty_value() if v is UNSET else v
            if self._is_blank(row):
                continue
            rows.append(row)
        return rows

    def _is_blank(self, row):
        for f in self.fields:
            v = row.get(f.name)
            if f.kind == "bool":
                continue
            if v in (None, "", [], {}):
                continue
            if isinstance(v, dict) and not any(x for x in v.values()):
                continue
            return False
        return True

    def from_rows(self, rows):
        return [{f.name: f.from_row(r) for f in self.fields} for r in rows]


def expand_fields(fields):
    """Media fields get a companion i18n ``<name>_alt`` field."""
    out = []
    for f in fields:
        out.append(f)
        if f.kind == "media" and not f.i18n and f.alt:
            alt = Field(f"{f.name}_alt", "text", f"متن جایگزین (alt) {f.label}", i18n=True, max=255, companion_of=f.name,
                        legacy=f.alt_legacy)
            f.alt_field = alt
            out.append(alt)
    return out


# ---------------------------------------------------------------------------
# entity
# ---------------------------------------------------------------------------
class Entity:
    def __init__(
        self, key, table, label, plural, fields, *, children=(), path=None, title="name",
        slug_field=None, slug_from: Callable | None = None, order="id DESC", search=(), filters=(),
        sorts=None, list_columns=(), status=False, active=False, created_col=None,
        updated_col="updated_at", per_page=PAGE_SIZE, view_path: Callable | None = None,
        tags: Callable | None = None, row_actions=(), id_col="id", help="", icon="",
    ):
        self.key = key
        self.table = table
        self.label = label
        self.plural = plural
        self.fields = expand_fields(fields)
        self.children = list(children)
        self.path = path or f"/admin/{key}s"
        self.title = title
        self.slug_field = slug_field
        self.slug_from = slug_from
        self.order = order
        self.search = list(search)
        self.filters = list(filters)       # [(column, label, options|callable)]
        self.sorts = sorts or {}
        self.list_columns = list(list_columns)  # [(header, callable(row)->str|html-safe)]
        self.status = status
        self.active = active
        self.created_col = created_col
        self.updated_col = updated_col
        self.per_page = per_page
        self.view_path = view_path
        self.tags = tags or (lambda ent, id, row, old: [ent.plural_key])
        self.row_actions = list(row_actions)
        self.help = help
        self.icon = icon
        # hooks (assign after construction)
        self.extra_cols: Callable | None = None    # (clean) -> {column: value} (e.g. legacy NOT NULL title)
        self.prepare: Callable | None = None       # (tx, clean, existing, is_new)
        self.extra_validate: Callable | None = None  # (clean, errors, existing)
        self.after_save: Callable | None = None    # (tx, id, clean, is_new)
        self.before_delete: Callable | None = None  # (tx, id) -> raise DeleteBlocked
        self.after_delete: Callable | None = None   # (tx, id)
        self.after_commit: Callable | None = None   # (app, id, row, old_values) after a successful save/delete/toggle
        self.load_extra: Callable | None = None    # async (db, id, values) -> None (fill virtual fields)
        self.hidden_fields: Callable | None = None  # async (db) -> set of field names hidden in the form (kept untouched on save)
        self.preview_kind: str | None = None        # 'product'|'project'|'article': adds a draft-preview button to the form
        self.form_panels: Callable | None = None   # async (db, id, values) -> [{"title","text","links":[{"label","url"}]}]
        self.extra_context: Callable | None = None
        self.by_name = {f.name: f for f in self.fields}

    @property
    def plural_key(self):
        return self.table

    # ---- schema ----
    def declare(self, schema, existing_table=False):
        cols = {"id": "INT AUTO_INCREMENT PRIMARY KEY"}
        for f in self.fields:
            cols.update(f.columns())
        if self.status:
            cols.setdefault("status", "VARCHAR(20) DEFAULT 'published'")
            cols.setdefault("published_at", "DATETIME NULL")
        if self.active:
            cols.setdefault("is_active", "TINYINT(1) NOT NULL DEFAULT 1")
        if self.created_col:
            cols.setdefault(self.created_col, "DATETIME NULL")
        if self.updated_col:
            cols.setdefault(self.updated_col, "DATETIME NULL")
        if existing_table:
            cols.pop("id")
            schema.register_columns(self.table, cols)
        else:
            schema.register_table(self.table, cols)
        for ch in self.children:
            ch.declare(schema)

    # ---- values <-> row ----
    def values_from_row(self, row: dict, children: dict | None = None) -> dict:
        v = {"id": row.get("id")}
        for f in self.fields:
            v[f.name] = f.from_row(row)
        if self.status:
            v["status"] = row.get("status") or "published"
            v["published_at"] = row.get("published_at")
        if self.active:
            v["is_active"] = bool(row.get("is_active", 1))
        for ch in self.children:
            v[ch.key] = ch.from_rows((children or {}).get(ch.key, []))
        return v

    def empty_values(self) -> dict:
        v = {"id": None}
        for f in self.fields:
            v[f.name] = f.empty_value()
        if self.status:
            v["status"] = "draft"
            v["published_at"] = None
        if self.active:
            v["is_active"] = True
        for ch in self.children:
            v[ch.key] = []
        return v

    def read_form(self, form, langs) -> dict:
        got = {}
        for f in self.fields:
            r = f.read(form, langs)
            if r is not UNSET:
                got[f.name] = r
        if self.status:
            if "status" in form:
                got["status"] = (form.get("status") or "").strip()
            if "published_at" in form:
                got["published_at"] = (form.get("published_at") or "").strip()
        if self.active and "is_active" in form:
            got["is_active"] = (form.get("is_active") or "").strip().lower() in TRUE_VALUES
        for ch in self.children:
            r = ch.read(form, langs)
            if r is not UNSET:
                got[ch.key] = r
        return got

    def merge(self, existing: dict | None, incoming: dict) -> dict:
        out = dict(existing) if existing else self.empty_values()
        for k, v in incoming.items():
            f = self.by_name.get(k)
            if f is not None and f.i18n and isinstance(v, dict):
                base = dict(out.get(k) or {})
                base.update(v)
                out[k] = base
            else:
                out[k] = v
        return out

    # ---- validation ----
    def validate(self, values: dict, langs, existing: dict | None = None) -> tuple[dict, dict]:
        """Return ``(clean, errors)``; ``clean`` is typed and ready to persist."""
        errors: dict = {}
        clean: dict = {"id": values.get("id")}
        for f in self.fields:
            gf = (existing or {}).get(f.name) if f.kind == "slug" else None
            clean[f.name] = f.coerce(values.get(f.name, f.empty_value()), errors, f.name, langs, grandfather=gf)
        if self.status:
            st = (values.get("status") or "draft").strip()
            if st not in ("draft", "published"):
                errors["status"] = "وضعیت نامعتبر است"
                st = "draft"
            clean["status"] = st
            pf = Field("published_at", "datetime", "زمان انتشار")
            clean["published_at"] = pf.coerce(values.get("published_at"), errors, "published_at", langs)
        if self.active:
            clean["is_active"] = bool(values.get("is_active", True))
        # required-to-publish
        if self.status and clean.get("status") == "published":
            for f in self.fields:
                if f.publish_required and f.name != self.slug_field and clean.get(f.name) in ("", None, [], {}):
                    errors.setdefault(f.name, f"«{f.label}» برای انتشار الزامی است")
        for ch in self.children:
            rows = []
            for i, row in enumerate(values.get(ch.key) or []):
                crow = {}
                for f in ch.fields:
                    crow[f.name] = f.coerce(row.get(f.name, f.empty_value()), errors, f"{ch.key}-{i}-{f.name}", langs)
                rows.append(crow)
            if len(rows) > ch.max_rows:
                errors[ch.key] = f"حداکثر {ch.max_rows} ردیف مجاز است"
            clean[ch.key] = rows
        if self.extra_validate:
            self.extra_validate(clean, errors, values)
        return clean, errors

    # ---- persistence ----
    async def load(self, db, id) -> dict | None:
        row = await db.fetch(f"SELECT * FROM `{self.table}` WHERE id=%s", (id,), one=True)
        if not row:
            return None
        kid_rows = await asyncio.gather(*[
            db.fetch(f"SELECT * FROM `{ch.table}` WHERE `{ch.fk}`=%s ORDER BY {ch.order}", (id,)) for ch in self.children
        ])
        kids = {ch.key: rows for ch, rows in zip(self.children, kid_rows)}
        values = self.values_from_row(row, kids)
        if self.load_extra:
            await self.load_extra(db, id, values)
        return values

    def _persist(self, tx, id, clean: dict, existing: dict | None):
        is_new = id is None
        errors: dict = {}
        # foreign keys exist?
        for f in self.fields:
            if f.kind == "fk" and f.ref and clean.get(f.name) is not None:
                if not tx.one(f"SELECT id FROM `{f.ref}` WHERE id=%s", (clean[f.name],)):
                    errors[f.name] = f"«{f.label}»: مورد انتخاب‌شده وجود ندارد"
        # slug: auto-generate / uniqueness
        auto_slug = False
        if self.slug_field:
            sf = self.slug_field
            slug = clean.get(sf) or ""
            if not slug and (is_new or (existing and not existing.get(sf))):
                auto_slug = True
                base = C.slugify(self.slug_from(clean)) if self.slug_from else ""
                slug = base
            if slug:
                cand, n = slug, 1
                while True:
                    dup = tx.one(f"SELECT id FROM `{self.table}` WHERE `{sf}`=%s AND id<>%s", (cand, id or 0))
                    if not dup:
                        break
                    if not auto_slug:
                        errors[sf] = "این slug قبلاً استفاده شده است"
                        break
                    n += 1
                    cand = f"{slug[: C.SLUG_MAX - 4]}-{n}"
                slug = cand
            clean[sf] = slug or None
        if errors:
            raise FormError(errors)
        if self.prepare:
            self.prepare(tx, clean, existing, is_new)
        # publish defaults
        if self.status and clean.get("status") == "published" and not clean.get("published_at"):
            clean["published_at"] = C.utcnow()
        cols: dict = {}
        for f in self.fields:
            cols.update(f.to_db(clean.get(f.name)))
        if self.status:
            cols["status"] = clean["status"]
            cols["published_at"] = clean.get("published_at")
        if self.active:
            cols["is_active"] = 1 if clean.get("is_active") else 0
        if self.extra_cols:
            cols.update(self.extra_cols(clean))
        # NB: raw expressions for timestamps
        exprs = {}
        if self.updated_col:
            exprs[self.updated_col] = "UTC_TIMESTAMP()"
        if is_new and self.created_col:
            exprs[self.created_col] = "UTC_TIMESTAMP()"
        names = list(cols) + list(exprs)
        if is_new:
            sql = (
                f"INSERT INTO `{self.table}` ({', '.join('`'+n+'`' for n in names)}) VALUES ("
                + ", ".join(["%s"] * len(cols) + [exprs[e] for e in exprs]) + ")"
            )
            id = tx.run(sql, tuple(cols.values()))
        else:
            sets = ", ".join([f"`{k}`=%s" for k in cols] + [f"`{k}`={v}" for k, v in exprs.items()])
            tx.run(f"UPDATE `{self.table}` SET {sets} WHERE id=%s", (*cols.values(), id))
        if self.slug_field and not clean.get(self.slug_field) and is_new:
            fallback = f"{self.key.replace('_', '-')}-{id}"
            tx.run(f"UPDATE `{self.table}` SET `{self.slug_field}`=%s WHERE id=%s", (fallback, id))
            clean[self.slug_field] = fallback
        # children: replace-all
        for ch in self.children:
            if ch.key not in clean:
                continue
            tx.run(f"DELETE FROM `{ch.table}` WHERE `{ch.fk}`=%s", (id,))
            for pos, row in enumerate(clean[ch.key]):
                ccols = {ch.fk: id, "sort_order": pos}
                for f in ch.fields:
                    ccols.update(f.to_db(row.get(f.name)))
                tx.run(
                    f"INSERT INTO `{ch.table}` ({', '.join('`'+k+'`' for k in ccols)}) VALUES ({', '.join(['%s']*len(ccols))})",
                    tuple(ccols.values()),
                )
        # slug history
        if self.slug_field and existing and existing.get(self.slug_field) and existing[self.slug_field] != clean.get(self.slug_field):
            tx.run(
                "INSERT INTO slug_history (entity_type, old_slug, entity_id) VALUES (%s,%s,%s)",
                (self.key, existing[self.slug_field], id),
            )
        if self.after_save:
            self.after_save(tx, id, clean, is_new)
        return id

    async def save(self, db, id, *, form=None, values=None, langs=("fa",)):
        """Create (``id=None``) or update. Pass either ``form`` (request.form
        like) or ``values`` (python dict, same shape as ``values_from_row``).

        Returns ``(id, merged_values, errors)``; ``id`` is ``None`` on error."""
        existing = await self.load(db, id) if id else None
        if id and existing is None:
            return None, self.empty_values(), {"_": "مورد یافت نشد"}
        incoming = self.read_form(form, langs) if form is not None else (values or {})
        merged = self.merge(existing, incoming)
        merged["id"] = id
        clean, errors = self.validate(merged, langs, existing)
        if errors:
            return None, merged, errors
        try:
            new_id = await db.transaction(lambda tx: self._persist(tx, id, clean, existing))
        except FormError as fe:
            return None, merged, fe.errors
        except DatabaseError:
            raise
        except Exception as e:  # IntegrityError etc.
            name = type(e).__name__
            if name == "IntegrityError" and self.slug_field and "slug" in str(e).lower():
                return None, merged, {self.slug_field: "این slug قبلاً استفاده شده است"}
            if name == "IntegrityError" and "Duplicate" in str(e):
                return None, merged, {"_": "مقدار تکراری: یکی از فیلدهای یکتا قبلاً ثبت شده است"}
            raise
        merged["id"] = new_id
        row = await db.fetch(f"SELECT * FROM `{self.table}` WHERE id=%s", (new_id,), one=True)
        if self.after_commit:
            self.after_commit(current_app, new_id, row or {}, existing)
        current_app.revalidate.notify(*self.tags(self, new_id, row or {}, existing))
        return new_id, merged, {}

    async def delete(self, db, id):
        """Delete row + children; raises DeleteBlocked with a Persian message."""
        row = await db.fetch(f"SELECT * FROM `{self.table}` WHERE id=%s", (id,), one=True)
        if not row:
            return False

        def go(tx):
            if self.before_delete:
                self.before_delete(tx, id)
            for ch in self.children:
                tx.run(f"DELETE FROM `{ch.table}` WHERE `{ch.fk}`=%s", (id,))
            tx.run(f"DELETE FROM `{self.table}` WHERE id=%s", (id,))
            if self.after_delete:
                self.after_delete(tx, id)

        await db.transaction(go)
        if self.after_commit:
            self.after_commit(current_app, id, row, None)
        current_app.revalidate.notify(*self.tags(self, id, row, None))
        return True

    # ---- helpers for serialisers / migrations ----
    def i18n_of(self, row: dict, name: str) -> dict:
        """Language dict of an i18n field from a raw DB row (``fa`` falls back
        to the legacy column)."""
        return self.by_name[name].from_row(row)

    def backfill(self, cur) -> int:
        """Idempotent: copy legacy single-language columns into the ``fa`` slot
        of ``<field>_i18n`` where it is still empty. Never touches the legacy
        column. Returns the number of updated rows."""
        n = 0
        for f in self.fields:
            if not (f.i18n and f.legacy):
                continue
            col = f"{f.name}_i18n"
            cur.execute(f"SELECT id, `{f.legacy}` AS v FROM `{self.table}` WHERE `{col}` IS NULL AND `{f.legacy}` IS NOT NULL AND `{f.legacy}`<>''")
            for rid, v in cur.fetchall():
                if f.is_list:
                    val = C.split_paragraphs(C.html_to_text(v)) if f.kind == "paragraphs" else C.lines_to_list(v)
                else:
                    val = C.html_to_text(v) if f.legacy_html else str(v)
                if val:
                    cur.execute(f"UPDATE `{self.table}` SET `{col}`=%s WHERE id=%s", (C.dump_i18n({"fa": val}), rid))
                    n += 1
        if self.updated_col:
            created = self.created_col or "created_at"
            cur.execute(f"SHOW COLUMNS FROM `{self.table}` LIKE %s", (created,))
            if cur.fetchone():
                cur.execute(
                    f"UPDATE `{self.table}` SET `{self.updated_col}` = "
                    + (
                        "UTC_TIMESTAMP() "
                        if self.created_col
                        else f"COALESCE(DATE_SUB(`{created}`, INTERVAL TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), NOW()) SECOND), UTC_TIMESTAMP()) "
                    )
                    + f"WHERE `{self.updated_col}` IS NULL"
                )
        return n

    # ---- select options ----
    async def options_for(self, db, f: Field, exclude_id=None):
        if f.options_fn:
            return await f.options_fn(db, exclude_id)
        if f.kind == "fk" and f.ref:
            label = f.label_sql or fa_sql(f"{f.ref}.name_i18n", f"{f.ref}.slug")
            where = f"WHERE {f.ref_where}" if f.ref_where else ""
            rows = await db.fetch(f"SELECT id, {label} AS label FROM `{f.ref}` {where} ORDER BY label")
            return [(r["id"], r["label"] or f"#{r['id']}") for r in rows]
        if callable(f.options):
            return await f.options(db)
        return list(f.options or [])

    async def all_options(self, db, exclude_id=None) -> dict:
        fs = [f for f in self.fields if f.kind in ("select", "fk") or f.options_fn]
        res = await asyncio.gather(*[self.options_for(db, f, exclude_id) for f in fs])
        return {f.name: r for f, r in zip(fs, res)}


# ---------------------------------------------------------------------------
# misc helpers shared by plugins
# ---------------------------------------------------------------------------
ADMIN_CACHE_NS = "admin"   # short-lived admin-panel cache; cleared by ``revalidate.notify`` (every content write)
ADMIN_CACHE_TTL = 60


def _admin_cache():
    try:
        return current_app.cache
    except Exception:
        return None


async def get_langs(db) -> list:
    """Active languages for admin tabs: ``fa`` first, always present (cached 60 s)."""
    cache = _admin_cache()
    if cache is not None:
        hit = cache.get("admin:langs", namespace=ADMIN_CACHE_NS)
        if hit is not None:
            return hit
    langs = await _load_langs(db)
    if cache is not None:
        cache.set("admin:langs", langs, ttl=ADMIN_CACHE_TTL, namespace=ADMIN_CACHE_NS)
    return langs


async def _load_langs(db) -> list:
    rows = await db.query(
        "SELECT code, name, native_name, direction FROM i18n_languages WHERE is_active=1 ORDER BY is_default DESC, id"
    ) or []
    langs = [{"code": "fa", "name": "Persian", "native_name": "فارسی", "direction": "rtl"}]
    for r in rows:
        if r["code"] != "fa":
            langs.append({"code": r["code"], "name": r["name"], "native_name": r["native_name"] or r["name"], "direction": r["direction"] or "ltr"})
    return langs


async def get_site_url(db) -> str:
    cache = _admin_cache()
    if cache is not None:
        hit = cache.get("admin:site_url", namespace=ADMIN_CACHE_NS)
        if hit is not None:
            return hit[0]
    try:
        row = await db.query("SELECT `value` FROM site_settings WHERE skey='site_url'", one=True)
        url = (row or {}).get("value") or ""
    except Exception:
        return ""
    if cache is not None:
        cache.set("admin:site_url", (url,), ttl=ADMIN_CACHE_TTL, namespace=ADMIN_CACHE_NS)
    return url


def _dtlocal(v):
    """Jinja filter: value for ``<input type=datetime-local>``."""
    if isinstance(v, _dt.datetime):
        return v.strftime("%Y-%m-%dT%H:%M")
    return v or ""


def install_template_helpers(app):
    app.jinja_env.filters.setdefault("dtlocal", _dtlocal)
    app.jinja_env.filters.setdefault("tojson_fa", lambda v: json.dumps(v, ensure_ascii=False))


def safe_next(url: str, default: str) -> str:
    """Only internal paths (``/x``, never ``//x``) – open-redirect guard."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return default


# ---------------------------------------------------------------------------
# generic admin: JSON API (+ page shells for the Vuexy panel)
# ---------------------------------------------------------------------------
_DT_OUT = "%Y-%m-%dT%H:%M:%S"


def _plain(v):
    """JSON-ready value: datetimes as ISO strings the form parser accepts back."""
    if isinstance(v, _dt.datetime):
        return v.strftime(_DT_OUT)
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def _flat(f: Field, v) -> str:
    """JSON value -> the string the form reader (``Field.read``) expects."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (list, tuple)):
        return ("\n\n" if f.kind == "paragraphs" else "\n").join(str(x) for x in v)
    return str(v)


def json_to_form(ent: Entity, data: dict, langs) -> tuple[dict, dict]:
    """Flatten a JSON body into the form-shaped mapping ``Entity.read_form`` consumes.

    Going through the form reader keeps one code path for sanitising (tag
    stripping), the "absent = untouched, present-but-empty = cleared" rule and
    child repeaters. Returns ``(form, errors)``."""
    form: dict = {}
    errors: dict = {}

    def put(prefix, f, v, key):
        if f.i18n:
            if not isinstance(v, dict):
                errors[key] = "مقدار باید شیء زبان‌ها باشد (مثل {\"fa\": ...})"
                return
            for code, x in v.items():
                if code in langs:
                    form[f"{prefix}{f.name}__{code}"] = _flat(f, x)
        else:
            form[f"{prefix}{f.name}"] = _flat(f, v)

    for f in ent.fields:
        if f.name in data:
            put("", f, data[f.name], f.name)
    for extra in ("status", "published_at", "is_active"):
        if extra in data:
            form[extra] = _flat(Field(extra), data[extra])
    for ch in ent.children:
        if ch.key not in data:
            continue
        rows = data[ch.key]
        if not isinstance(rows, list):
            errors[ch.key] = "باید فهرست باشد"
            continue
        form[f"{ch.key}__present"] = "1"
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                errors[ch.key] = "هر ردیف باید شیء باشد"
                break
            for f in ch.fields:
                if f.name in row:
                    put(f"{ch.key}-{i}-", f, row[f.name], f"{ch.key}-{i}-{f.name}")
    return form, errors


def _opts(options: dict) -> dict:
    return {k: [{"value": v, "label": l} for v, l in lst] for k, lst in options.items()}


def field_meta(f: Field) -> dict:
    return {
        "name": f.name, "kind": f.kind, "label": f.label, "i18n": f.i18n, "required": f.required,
        "publish_required": f.publish_required, "min": f.min, "max": f.max, "help": f.help,
        "placeholder": f.placeholder, "rows": f.rows, "ltr": f.ltr, "counter": f.counter,
        "companion_of": f.companion_of, "max_items": f.max_items, "max_item_len": f.max_item_len,
        "virtual": f.virtual, "is_list": f.is_list, "ref": f.ref,
    }


def entity_meta(ent: Entity) -> dict:
    return {
        "key": ent.key, "label": ent.label, "plural": ent.plural, "icon": ent.icon, "help": ent.help,
        "page": ent.path, "api": "/api" + ent.path, "title_field": ent.title, "slug_field": ent.slug_field,
        "status": ent.status, "active": ent.active, "searchable": bool(ent.search),
        "per_page": ent.per_page, "sorts": list(ent.sorts), "preview": bool(ent.preview_kind),
        "columns": [h for h, _ in ent.list_columns],
        "fields": [field_meta(f) for f in ent.fields],
        "children": [{
            "key": ch.key, "label": ch.label, "item_label": ch.item_label, "max_rows": ch.max_rows, "help": ch.help,
            "fields": [field_meta(f) for f in ch.fields],
        } for ch in ent.children],
    }


def register_admin(bp, ent: Entity, *, routes=("list", "create", "edit", "delete", "toggle")):
    """Add the JSON API (``/api<ent.path>``) and the page shells (``ent.path``) for ``ent`` to ``bp``.

    API: ``GET`` list / ``GET schema`` / ``GET <id>`` / ``POST`` create / ``PUT <id>`` / ``DELETE <id>`` /
    ``POST <id>/toggle``. ``routes`` lets a plugin keep its own list/delete/toggle views."""
    from .admin_api import admin_api, body, invalid, render_admin, reply
    from .decorators import admin_required
    from .public import ApiError

    page = ent.path
    api = "/api" + ent.path
    k = ent.key

    def db():
        return current_app.core.db

    async def langs_of(d):
        return [l["code"] for l in await get_langs(d)]

    async def _none():
        return None

    async def item_payload(d, id, values):
        site_url, options, hidden, panels = await asyncio.gather(
            get_site_url(d), ent.all_options(d, id),
            ent.hidden_fields(d) if ent.hidden_fields else _none(),
            ent.form_panels(d, id, values) if ent.form_panels else _none(),
        )
        out = {
            "id": id, "values": _plain(values), "options": _opts(options),
            "hidden": sorted(hidden or []), "view_url": None, "preview_url": None, "panels": panels or [],
        }
        if id and ent.view_path and site_url:
            try:
                p = ent.view_path(values)
                out["view_url"] = site_url.rstrip("/") + p if p else None
                if ent.preview_kind and p:
                    from .public import make_preview_token

                    out["preview_url"] = f"{site_url.rstrip('/')}{p}{'&' if '?' in p else '?'}preview={make_preview_token(ent.preview_kind, id)}"
            except Exception:
                pass
        return out

    async def save(id):
        d = db()
        langs = await langs_of(d)
        form, errs = json_to_form(ent, body(), langs)
        if errs:
            raise invalid(errs)
        new_id, _values, errors = await ent.save(d, id, form=form, langs=langs)
        if not new_id:
            if errors.get("_") == "مورد یافت نشد":
                raise ApiError(404, "not_found", f"{ent.label} یافت نشد")
            raise invalid(errors, "ذخیره انجام نشد؛ خطاهای فرم را بررسی کنید")
        return new_id

    # ---- API handlers ----
    async def api_schema():
        d = db()
        empty = ent.empty_values()
        for kk in request.args:  # prefill (?parent_id=3)
            if kk in ent.by_name and not ent.by_name[kk].i18n:
                empty[kk] = request.args[kk]

        async def _static(v):
            return v

        langs, item, *filter_opts = await asyncio.gather(
            get_langs(d), item_payload(d, None, empty),
            *[opts(d) if callable(opts) else _static(opts) for _c, _l, opts in ent.filters],
        )
        filters = [{"col": col, "label": label, "options": [{"value": v, "label": l} for v, l in options]}
                   for (col, label, _o), options in zip(ent.filters, filter_opts)]
        return reply({
            "entity": entity_meta(ent), "languages": langs, "defaults": item["values"],
            "options": item["options"], "hidden": item["hidden"], "filters": filters,
        })

    async def api_list():
        d = db()
        q = (request.args.get("q") or "").strip()
        raw_page = request.args.get("page") or ""
        page_no = int(raw_page) if raw_page.isdigit() and int(raw_page) > 0 else 1
        per_page = ent.per_page
        if (request.args.get("per_page") or "").isdigit():
            per_page = min(max(int(request.args["per_page"]), 1), 100)
        where, params = [], []
        if q and ent.search:
            where.append("(" + " OR ".join(f"{col} LIKE %s" for col in ent.search) + ")")
            params += ["%" + C.escape_like(q) + "%"] * len(ent.search)
        for col, _label, _opts_ in ent.filters:
            val = (request.args.get(f"f_{col}") or "").strip()
            if val != "":
                where.append(f"`{col}`=%s")
                params.append(val)
        order = ent.sorts.get(request.args.get("sort") or "") or ent.order
        wsql = ("WHERE " + " AND ".join(where)) if where else ""
        total_row, rows, site_url = await asyncio.gather(
            d.fetch(f"SELECT COUNT(*) AS c FROM `{ent.table}` {wsql}", tuple(params), one=True),
            d.fetch(f"SELECT * FROM `{ent.table}` {wsql} ORDER BY {order} LIMIT %s OFFSET %s",
                    (*params, per_page, (page_no - 1) * per_page)),
            get_site_url(d),
        )
        total = total_row["c"]
        items = []
        for r in rows:
            vals = ent.values_from_row(r)
            title = vals.get(ent.title)
            title = title.get("fa") if isinstance(title, dict) else title
            view = None
            if ent.view_path and site_url:
                try:
                    pth = ent.view_path({**vals, **r})
                    view = site_url.rstrip("/") + pth if pth else None
                except Exception:
                    view = None
            item = {
                "id": r["id"], "title": title or f"#{r['id']}",
                "cells": [str(fn(r, vals)) for _h, fn in ent.list_columns],
                "view_url": view,
                "actions": [{"label": act[0], "url": act[1]} for act in (a(r) for a in ent.row_actions)],
            }
            if ent.status:
                item["status"] = r.get("status")
            if ent.active:
                item["is_active"] = bool(r.get("is_active"))
            if ent.updated_col:
                item["updated_at"] = r.get(ent.updated_col)
            items.append(item)
        return reply(items, meta={"total": total, "page": page_no, "per_page": per_page,
                                  "total_pages": max(1, -(-total // per_page)) if total else 0})

    async def api_get(id):
        d = db()
        values = await ent.load(d, id)
        if values is None:
            raise ApiError(404, "not_found", f"{ent.label} یافت نشد")
        return reply(await item_payload(d, id, values))

    async def api_create():
        new_id = await save(None)
        d = db()
        return reply(await item_payload(d, new_id, await ent.load(d, new_id)), 201)

    async def api_update(id):
        await save(id)
        d = db()
        return reply(await item_payload(d, id, await ent.load(d, id)))

    async def api_delete(id):
        try:
            done = await ent.delete(db(), id)
        except DeleteBlocked as e:
            raise ApiError(409, "conflict", str(e))
        if not done:
            raise ApiError(404, "not_found", f"{ent.label} یافت نشد")
        return reply({"deleted": id})

    async def api_toggle(id):
        d = db()
        row = await d.fetch(f"SELECT * FROM `{ent.table}` WHERE id=%s", (id,), one=True)
        if not row:
            raise ApiError(404, "not_found", f"{ent.label} یافت نشد")
        await d.execute(f"UPDATE `{ent.table}` SET is_active = 1 - is_active WHERE id=%s", (id,))
        if ent.after_commit:
            ent.after_commit(current_app, id, row, None)
        current_app.revalidate.notify(*ent.tags(ent, id, row, None))
        return reply({"id": id, "is_active": not bool(row.get("is_active"))})

    # ---- page shells (the panel is rendered client-side from the API) ----
    def shell(mode):
        titles = {"list": ent.plural, "create": f"{ent.label} جدید", "edit": f"ویرایش {ent.label}"}

        async def view(id=None):
            return await render_admin("admin_ui/entity.html", mode=mode, ent=ent, entity_id=id, page_title=titles[mode])

        return admin_required(view)

    def api_rule(rule, name, fn, methods):
        bp.add_url_rule(rule, endpoint=f"{k}_{name}", view_func=admin_api(fn), methods=methods)

    if "list" in routes:
        api_rule(api, "api_list", api_list, ["GET"])
        bp.add_url_rule(page, endpoint=f"{k}_list", view_func=shell("list"), methods=["GET"])
    api_rule(f"{api}/schema", "api_schema", api_schema, ["GET"])
    api_rule(f"{api}/<int:id>", "api_get", api_get, ["GET"])
    if "create" in routes:
        api_rule(api, "api_create", api_create, ["POST"])
        bp.add_url_rule(f"{page}/create", endpoint=f"{k}_create", view_func=shell("create"), methods=["GET"])
    if "edit" in routes:
        api_rule(f"{api}/<int:id>", "api_update", api_update, ["PUT", "PATCH"])
        bp.add_url_rule(f"{page}/<int:id>/edit", endpoint=f"{k}_edit", view_func=shell("edit"), methods=["GET"])
    if "delete" in routes:
        api_rule(f"{api}/<int:id>", "api_delete", api_delete, ["DELETE"])
    if ent.active and "toggle" in routes:
        api_rule(f"{api}/<int:id>/toggle", "api_toggle", api_toggle, ["POST"])
