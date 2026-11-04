"""company plugin — about-us content: stats, timeline, team, certifications,
industries, testimonials, offices (spec 6.9).

Admin hub: ``/admin/company`` (each collection has its own list/form under
``/admin/company/<name>``). Public: ``GET /api/public/company?include=...``.
A certification can carry one downloadable document (shared documents model).
"""
from __future__ import annotations

from flask import Blueprint, request

from app.core import content as C
from app.core import migrate
from app.core.base_plugin import BasePlugin
from app.core.admin_api import api_route, page_route, reply
from app.core.entity import Entity, Field as F, register_admin
from app.core.public import bad_request, public_blueprint, public_get

SECTIONS = ["stats", "timeline", "team", "certifications", "industries", "testimonials", "offices"]
INDUSTRY_ICONS = ["Flame", "Droplets", "Factory", "FlaskConical", "Zap", "Cpu"]


def _common(extra_order="sort_order, id"):
    return dict(active=True, created_col="created_at", order=extra_order, per_page=50)


def _lst(label, key):
    return lambda r, v: ((v.get(key) or {}).get("fa") if isinstance(v.get(key), dict) else v.get(key)) or "—"


STATS = Entity(
    "company_stat", "company_stats", "آمار", "آمار شرکت",
    [
        F("value", "float", "عدد (شمارنده‌ی انیمیشنی)", required=True, min=0, max=10 ** 12),
        F("suffix", "text", "پسوند (مثل «+ سال»)", i18n=True, max=40),
        F("label", "text", "برچسب", i18n=True, required=True, max=191),
        F("sublabel", "text", "زیربرچسب", i18n=True, max=255),
        F("sort_order", "int", "ترتیب", min=0, max=1000000, default=0),
    ],
    path="/admin/company/stats", tags=lambda e, i, r, o: ["company"], search=["label_i18n"],
    list_columns=[("عدد", lambda r, v: r.get("value")), ("ترتیب", lambda r, v: r.get("sort_order") or 0)], **_common(),
)
TIMELINE = Entity(
    "company_timeline", "company_timeline", "رویداد گاه‌شمار", "گاه‌شمار",
    [
        F("year", "text", "سال (میلادی)", required=True, max=8, ltr=True),
        F("title", "text", "عنوان", i18n=True, required=True, max=191),
        F("description", "textarea", "توضیحات", i18n=True, rows=3, max=2000),
        F("sort_order", "int", "ترتیب", min=0, max=1000000, default=0),
    ],
    path="/admin/company/timeline", tags=lambda e, i, r, o: ["company"], search=["year", "title_i18n"],
    list_columns=[("سال", lambda r, v: r.get("year")), ("ترتیب", lambda r, v: r.get("sort_order") or 0)], **_common("sort_order, year, id"),
)
TEAM = Entity(
    "company_team", "company_team", "عضو تیم", "تیم مدیریت",
    [
        F("name", "text", "نام", i18n=True, required=True, max=191),
        F("role", "text", "سمت", i18n=True, max=191),
        F("qualification", "text", "تحصیلات/صلاحیت", i18n=True, max=255),
        F("bio", "textarea", "معرفی", i18n=True, rows=4, max=3000),
        F("photo", "media", "عکس"),
        F("sort_order", "int", "ترتیب", min=0, max=1000000, default=0),
    ],
    path="/admin/company/team", tags=lambda e, i, r, o: ["company"], search=["name_i18n"],
    list_columns=[("ترتیب", lambda r, v: r.get("sort_order") or 0)], **_common(),
)
CERTS = Entity(
    "company_cert", "company_certifications", "گواهینامه", "گواهینامه‌ها",
    [
        F("code", "text", "کد (مثل ISO 9001:2015)", required=True, max=80, ltr=True),
        F("title", "text", "عنوان", i18n=True, required=True, max=191),
        F("issuer", "text", "صادرکننده", i18n=True, max=191),
        F("description", "textarea", "توضیحات", i18n=True, rows=3, max=2000),
        F("logo", "media", "لوگو"),
        F("sort_order", "int", "ترتیب", min=0, max=1000000, default=0),
    ],
    path="/admin/company/certifications", tags=lambda e, i, r, o: ["company"], search=["code", "title_i18n"],
    list_columns=[("کد", lambda r, v: r.get("code")), ("ترتیب", lambda r, v: r.get("sort_order") or 0)],
    row_actions=[lambda r: ("سند قابل‌دانلود", f"/admin/documents/certification/{r['id']}")], **_common(),
)
INDUSTRIES = Entity(
    "company_industry", "company_industries", "صنعت", "صنایع هدف",
    [
        F("icon", "select", "آیکن", options=[(i, i) for i in INDUSTRY_ICONS]),
        F("title", "text", "عنوان", i18n=True, required=True, max=191),
        F("description", "textarea", "توضیحات", i18n=True, rows=3, max=2000),
        F("sort_order", "int", "ترتیب", min=0, max=1000000, default=0),
    ],
    path="/admin/company/industries", tags=lambda e, i, r, o: ["company"], search=["title_i18n"],
    list_columns=[("آیکن", lambda r, v: r.get("icon") or "—"), ("ترتیب", lambda r, v: r.get("sort_order") or 0)], **_common(),
)
TESTIMONIALS = Entity(
    "company_testimonial", "company_testimonials", "نظر مشتری", "نظرات مشتریان",
    [
        F("quote", "textarea", "متن نظر", i18n=True, required=True, rows=4, max=3000),
        F("author_name", "text", "نام", i18n=True, required=True, max=191),
        F("author_role", "text", "سمت", i18n=True, max=191),
        F("organization", "text", "سازمان", i18n=True, max=191),
        F("sector", "text", "بخش صنعتی", i18n=True, max=191),
        F("photo", "media", "عکس"),
        F("sort_order", "int", "ترتیب", min=0, max=1000000, default=0),
    ],
    path="/admin/company/testimonials", tags=lambda e, i, r, o: ["company"], search=["author_name_i18n", "quote_i18n"],
    list_columns=[("ترتیب", lambda r, v: r.get("sort_order") or 0)], **_common(),
)
OFFICES = Entity(
    "company_office", "company_offices", "دفتر", "دفاتر",
    [
        F("title", "text", "عنوان", i18n=True, required=True, max=191),
        F("address", "textarea", "آدرس", i18n=True, required=True, rows=3, max=1000),
        F("phone", "phone", "تلفن", max=60),
        F("email", "email", "ایمیل"),
        F("hours", "text", "ساعات کاری", i18n=True, max=255),
        F("lat", "float", "عرض جغرافیایی", min=-90, max=90),
        F("lng", "float", "طول جغرافیایی", min=-180, max=180),
        F("is_primary", "bool", "دفتر اصلی (فقط یکی)"),
        F("sort_order", "int", "ترتیب", min=0, max=1000000, default=0),
    ],
    path="/admin/company/offices", tags=lambda e, i, r, o: ["company"], search=["title_i18n", "phone"],
    list_columns=[("اصلی", lambda r, v: "★" if r.get("is_primary") else ""), ("ترتیب", lambda r, v: r.get("sort_order") or 0)],
    **_common(),
)
ENTITIES = {"stats": STATS, "timeline": TIMELINE, "team": TEAM, "certifications": CERTS, "industries": INDUSTRIES,
            "testimonials": TESTIMONIALS, "offices": OFFICES}


def _office_after_save(tx, oid, clean, is_new):
    """Exactly one primary office: marking one clears the others."""
    if clean.get("is_primary"):
        tx.run("UPDATE company_offices SET is_primary=0 WHERE id<>%s", (oid,))


OFFICES.after_save = _office_after_save


def _cert_before_delete(tx, cid):
    from app.plugins.documents.plugin import remove_stored  # noqa: F401  (import check only)
    files = tx.rows(
        "SELECT f.stored_path FROM document_files f JOIN documents d ON d.id=f.document_id "
        "WHERE d.owner_type='certification' AND d.owner_id=%s", (cid,))
    _pending[cid] = [f["stored_path"] for f in files]


def _cert_after_delete(tx, cid):
    for d in tx.rows("SELECT id FROM documents WHERE owner_type='certification' AND owner_id=%s", (cid,)):
        tx.run("DELETE FROM document_files WHERE document_id=%s", (d["id"],))
    tx.run("DELETE FROM documents WHERE owner_type='certification' AND owner_id=%s", (cid,))


_pending: dict = {}


def _cert_after_commit(app, cid, row, old):
    for rel in _pending.pop(cid, []):
        try:
            from app.plugins.documents.plugin import remove_stored

            remove_stored(rel)
        except Exception:
            pass


CERTS.before_delete = _cert_before_delete
CERTS.after_delete = _cert_after_delete
CERTS.after_commit = _cert_after_commit


class Plugin(BasePlugin):
    name = "company"
    auto_enable = True
    admin_entry = {"title": "درباره‌ی شرکت", "icon": "🏢", "url": "/admin/company", "order": 18}
    output_type = "json"

    def declare_schema(self, schema):
        for e in ENTITIES.values():
            e.declare(schema)

    def maybe_run_migration(self):
        def go(cur):
            for e in ENTITIES.values():
                migrate.ensure_index(cur, e.table, f"idx_{e.table}_active", "is_active, sort_order")
        migrate.run(self.db, go)

    def register(self):
        bp = Blueprint("plugin_company", __name__)
        for e in ENTITIES.values():
            register_admin(bp, e)

        page_route(bp, "/admin/company", "hub", "company", "درباره‌ی شرکت", "pages-system")

        @api_route(bp, "/api/admin/company", "api_hub")
        async def api_hub():
            items = []
            for key in SECTIONS:
                e = ENTITIES[key]
                n = await self.db.fetch(f"SELECT COUNT(*) AS c FROM `{e.table}`", one=True)
                items.append({"key": key, "label": e.plural, "path": e.path, "count": n["c"]})
            return reply(items)

        self.app.register_blueprint(bp)
        self._register_documents()

        pub = public_blueprint("public_company")
        for key in ("stats", "industries", "certifications", "testimonials", "offices"):
            self.app.public_providers["home"][key] = (lambda k: (lambda ctx, _l: self.section(ctx, k)))(key)

        @public_get(pub, "/company", params=("include",))
        async def company(ctx):
            raw = (request.args.get("include") or "").strip()
            want = [s.strip() for s in raw.split(",") if s.strip()] if raw else list(SECTIONS)
            bad = [s for s in want if s not in SECTIONS]
            if bad:
                raise bad_request(f"Invalid include: {', '.join(bad)}. Allowed: {', '.join(SECTIONS)}")
            return {k: await self.section(ctx, k) for k in want}

        self.app.register_blueprint(pub)

    # ---------------------------------------------------------------- documents owner (certifications)
    def _register_documents(self):
        try:
            from app.plugins.documents.plugin import register_owner
        except Exception:
            return

        async def title(d, cid):
            r = await d.fetch("SELECT code FROM company_certifications WHERE id=%s", (cid,), one=True)
            return r["code"] if r else None

        async def visible(d, ids):
            if not ids:
                return set()
            rows = await d.fetch(
                f"SELECT id FROM company_certifications WHERE is_active=1 AND id IN ({','.join(['%s'] * len(ids))})", tuple(ids))
            return {r["id"] for r in rows}

        async def tags(d, cid):
            return ["company"]

        async def touch(d, cid):
            await d.execute("UPDATE company_certifications SET updated_at=UTC_TIMESTAMP() WHERE id=%s", (cid,))

        register_owner(self.app, "certification", label="گواهینامه", title=title, visible=visible, tags=tags, touch=touch,
                       back=lambda cid: "/admin/company/certifications")

    # ---------------------------------------------------------------- serialisers
    async def section(self, ctx, key: str) -> list:
        e = ENTITIES[key]
        rows = await ctx.db.fetch(f"SELECT * FROM `{e.table}` WHERE is_active=1 ORDER BY {e.order}")
        T = lambda r, f: ctx.text(e.i18n_of(r, f))
        if key == "stats":
            def num(v):
                return int(v) if v is not None and float(v) == int(float(v)) else v
            return [{"id": r["id"], "value": num(r["value"]), "suffix": T(r, "suffix"), "label": T(r, "label"),
                     "sublabel": T(r, "sublabel")} for r in rows]
        if key == "timeline":
            return [{"year": r["year"], "title": T(r, "title"), "description": T(r, "description")} for r in rows]
        if key == "team":
            return [{"id": r["id"], "name": T(r, "name"), "role": T(r, "role"), "qualification": T(r, "qualification"),
                     "bio": T(r, "bio"), "photo": ctx.media(r.get("photo"), r.get("photo_alt_i18n"))} for r in rows]
        if key == "certifications":
            docs_plugin = self.app.core.plugins.plugins.get("documents")
            docs = {}
            if docs_plugin and rows:
                docs = await docs_plugin.public_documents(ctx, "certification", [r["id"] for r in rows])
            return [{"id": r["id"], "code": r["code"], "title": T(r, "title"), "issuer": T(r, "issuer"),
                     "description": T(r, "description"), "logo": ctx.media(r.get("logo"), r.get("logo_alt_i18n")),
                     "document": (docs.get(r["id"]) or [None])[0]} for r in rows]
        if key == "industries":
            return [{"id": r["id"], "icon": r.get("icon") or None, "title": T(r, "title"),
                     "description": T(r, "description")} for r in rows]
        if key == "testimonials":
            return [{"id": r["id"], "quote": T(r, "quote"), "author_name": T(r, "author_name"),
                     "author_role": T(r, "author_role"), "organization": T(r, "organization"), "sector": T(r, "sector"),
                     "photo": ctx.media(r.get("photo"), r.get("photo_alt_i18n"))} for r in rows]
        # offices
        return [{
            "id": r["id"], "title": T(r, "title"), "address": T(r, "address"), "phone": r.get("phone") or None,
            "phone_tel": C.phone_tel(r.get("phone")), "email": r.get("email") or None, "hours": T(r, "hours"),
            "lat": r.get("lat"), "lng": r.get("lng"), "coordinates_label": C.coords_label(r.get("lat"), r.get("lng")),
            "is_primary": bool(r.get("is_primary")),
        } for r in rows]
