"""navigation plugin — editable header/footer menus (spec 6.16 "منوی قابل‌ویرایش").

Admin: ``/admin/navigation``. Public: ``GET /api/public/navigation``.

Two levels: a root item may have children (a footer "column" is a root with no
``href`` and children). An empty menu means "use the frontend's built-in menu".
Product categories stay dynamic (``GET /categories``) — they are not menu items.
"""
from __future__ import annotations

import re

from flask import Blueprint

from app.core import content as C
from app.core import migrate
from app.core.base_plugin import BasePlugin
from app.core.entity import Entity, Field as F, FormError, fa_sql, register_admin
from app.core.public import public_blueprint, public_get

MENUS = [("header", "هدر"), ("footer", "فوتر")]
HREF_RE = re.compile(r"^(/(?!/)[^\s]*|https?://[^\s]+|mailto:[^\s]+|tel:[+0-9\-\s()]+|#[\w\-]+)$", re.I)
SEED = {
    "header": [("/", "خانه", "Home"), ("/about", "درباره ما", "About"), ("/products", "محصولات", "Products"),
               ("/services", "خدمات", "Services"), ("/projects", "پروژه‌ها", "Projects"), ("/news", "اخبار و مقالات", "News"),
               ("/faq", "پرسش‌های متداول", "FAQ"), ("/contact", "تماس با ما", "Contact")],
    "footer": [("/about", "درباره ما", "About"), ("/products", "محصولات", "Products"), ("/contact", "تماس با ما", "Contact")],
}


async def _parent_options(db, exclude_id=None):
    rows = await db.fetch(
        "SELECT id, menu, label_i18n FROM nav_items WHERE parent_id IS NULL AND id<>%s ORDER BY menu, sort_order, id", (exclude_id or 0,)
    )
    names = dict(MENUS)
    return [(r["id"], f"{names.get(r['menu'], r['menu'])} › {C.parse_i18n(r['label_i18n']).get('fa') or r['id']}") for r in rows]


ENT = Entity(
    "nav_item", "nav_items", "آیتم منو", "منوی سایت",
    [
        F("menu", "select", "منو", required=True, options=MENUS, default="header"),
        F("label", "text", "عنوان", i18n=True, required=True, max=120),
        F("href", "text", "لینک", max=500, ltr=True, placeholder="/products یا https://…",
          help="مسیر داخلی (/products)، https://، mailto:، tel: یا #بخش. خالی = عنوان گروه (فقط وقتی زیرمنو دارد)"),
        F("new_tab", "bool", "باز شدن در تب جدید"),
        F("parent_id", "fk", "والد (خالی = آیتم اصلی)", ref="nav_items", options_fn=_parent_options),
        F("sort_order", "int", "ترتیب", min=0, max=1000000, default=0),
    ],
    path="/admin/navigation", active=True, created_col="created_at", order="menu, COALESCE(parent_id, id), parent_id IS NOT NULL, sort_order, id",
    search=["label_i18n", "href"], per_page=100,
    filters=[("menu", "منو", MENUS)],
    list_columns=[("منو", lambda r, v: dict(MENUS).get(r.get("menu"), r.get("menu"))), ("لینک", lambda r, v: r.get("href") or "—"),
                  ("والد", lambda r, v: r.get("parent_id") or "—"), ("ترتیب", lambda r, v: r.get("sort_order") or 0),
                  ("وضعیت", lambda r, v: "فعال" if r.get("is_active") else "غیرفعال")],
    tags=lambda ent, id, row, old: ["navigation"],
)


def _validate(clean, errors, values):
    href = (clean.get("href") or "").strip()
    if href and not HREF_RE.match(href):
        errors["href"] = "لینک نامعتبر است (مسیر داخلی با / ، https:// ، mailto: ، tel: یا #)"
    if clean.get("menu") not in dict(MENUS):
        errors["menu"] = "منوی نامعتبر"


def _prepare(tx, clean, existing, is_new):
    pid, nid = clean.get("parent_id"), clean.get("id")
    if not pid:
        return      # a root without href is a group heading; the API hides it while it has no visible child
    if nid and int(pid) == int(nid):
        raise FormError({"parent_id": "یک آیتم نمی‌تواند والد خودش باشد"})
    parent = tx.one("SELECT id, menu, parent_id FROM nav_items WHERE id=%s", (pid,))
    if not parent:
        raise FormError({"parent_id": "والد یافت نشد"})
    if parent["parent_id"]:
        raise FormError({"parent_id": "فقط دو سطح مجاز است"})
    if parent["menu"] != clean.get("menu"):
        raise FormError({"parent_id": "والد باید در همان منو باشد"})
    if nid and tx.one("SELECT id FROM nav_items WHERE parent_id=%s LIMIT 1", (nid,)):
        raise FormError({"parent_id": "این آیتم زیرمنو دارد و نمی‌تواند خودش زیرمنو شود"})
    if not (clean.get("href") or "").strip():
        raise FormError({"href": "زیرمنو باید لینک داشته باشد"})


def _before_delete(tx, nid):
    # children go with their parent (a dangling child would never be shown)
    tx.run("DELETE FROM nav_items WHERE parent_id=%s", (nid,))


ENT.extra_validate = _validate
ENT.prepare = _prepare
ENT.before_delete = _before_delete


class Plugin(BasePlugin):
    name = "navigation"
    auto_enable = True
    admin_entry = {"title": "منوها", "icon": "🧭", "url": "/admin/navigation", "order": 7}
    output_type = "json"

    def declare_schema(self, schema):
        ENT.declare(schema)

    def maybe_run_migration(self):
        def seed(cur):
            for menu, items in SEED.items():
                for i, (href, fa, en) in enumerate(items):
                    cur.execute(
                        "INSERT INTO nav_items (menu, label_i18n, href, new_tab, sort_order, is_active, created_at, updated_at) "
                        "VALUES (%s,%s,%s,0,%s,1,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                        (menu, C.dump_i18n({"fa": fa, "en": en}), href, i),
                    )

        def go(cur):
            migrate.seed_once(cur, "seed_navigation", seed)
            migrate.ensure_index(cur, "nav_items", "idx_nav_menu", "menu, is_active, sort_order")
            migrate.ensure_index(cur, "nav_items", "idx_nav_parent", "parent_id")

        migrate.run(self.db, go)

    def register(self):
        bp = Blueprint("plugin_navigation", __name__)
        register_admin(bp, ENT)
        self.app.register_blueprint(bp)

        pub = public_blueprint("public_navigation")

        @public_get(pub, "/navigation")
        async def navigation(ctx):
            rows = await ctx.db.fetch(
                "SELECT * FROM nav_items WHERE is_active=1 ORDER BY sort_order, id"
            )
            roots = {r["id"]: r for r in rows if not r["parent_id"]}

            def item(r):
                return {
                    "id": r["id"], "label": ctx.text(ENT.i18n_of(r, "label")), "href": r.get("href") or None,
                    "new_tab": bool(r.get("new_tab")), "children": [],
                }

            out = {m: [] for m, _l in MENUS}
            by_id = {}
            for r in rows:
                if not r["parent_id"] and r["menu"] in out:
                    it = item(r)
                    by_id[r["id"]] = it
                    out[r["menu"]].append(it)
            for r in rows:                      # children of inactive/missing roots are not shown
                if r["parent_id"] and r["parent_id"] in by_id and roots.get(r["parent_id"], {}).get("menu") == r["menu"]:
                    by_id[r["parent_id"]]["children"].append(item(r))
            # a group heading without any visible child would be an empty label
            for m in out:
                out[m] = [i for i in out[m] if i["href"] or i["children"]]
            stamp = max((r["updated_at"] for r in rows if r.get("updated_at")), default=None)
            return {**out, "updated_at": ctx.iso(stamp)}

        self.app.register_blueprint(pub)
