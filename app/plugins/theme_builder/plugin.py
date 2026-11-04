"""Theme builder plugin.

- Lists theme folders under templates/themes/ and lets the admin pick the
  active one (settings.active_theme) — and, unlike the old dead core
  /admin/themes page, this selection is actually applied to the public
  homepage.
- For themes with a registered widget catalog (currently just "conspro"),
  provides an Elementor-style drag/drop builder for one or more pages: rows
  of widgets, live preview, save/activate/list/delete named designs stored
  as JSON files under designs/<theme>/<page>/. "home" overrides the site's
  "/"; other pages (e.g. "product-detail") override the matching plugin
  route (e.g. products' /product/<slug>) and can bind widgets to whichever
  entity that route is showing via a page_context dict.
"""
import json
import os

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    jsonify, send_from_directory, Response,
)

from app.core.base_plugin import BasePlugin
from app.core.decorators import admin_required
from app.core.admin_api import api_route, body, invalid, page_route, render_admin, reply
from app.core.public import ApiError

from . import storage, renderer
from .widgets import get_registry, widget_catalog_json, default_row_order, pages_for_theme


def _safe_rel(rel: str) -> str:
    rel = (rel or "").replace("\\", "/").strip("/")
    if ".." in rel.split("/"):
        raise ValueError("invalid path")
    return rel


def _safe_theme_name(theme: str) -> str:
    if not theme or "/" in theme or "\\" in theme or theme in (".", ".."):
        raise ValueError("invalid theme")
    return theme


def _normalize_product(product: dict) -> dict:
    """The products plugin stores ``extra`` as a raw JSON column (comes
    back from mysql-connector as text, same as it does for schema_json —
    see products/plugin.py's own json.loads(schema) call). Parse it once
    here so widget templates can do plain ``product.extra.items()``."""
    if not product:
        return product
    extra = product.get("extra")
    if isinstance(extra, str):
        try:
            product["extra"] = json.loads(extra) if extra else {}
        except (TypeError, ValueError):
            product["extra"] = {}
    elif extra is None:
        product["extra"] = {}
    return product


class Plugin(BasePlugin):
    name = "theme_builder"

    admin_entry = {
        "title": "قالب سایت",
        "icon": "🎨",
        "url": "/admin/site-theme",
        "order": 15,
    }
    output_type = "html"

    def list_themes(self):
        base = os.path.join(self.app.config["TEMPLATES_DIR"], "themes")
        if not os.path.isdir(base):
            return []
        return sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))

    def _theme_assets_root(self, theme: str) -> str:
        theme = _safe_theme_name(theme)
        return os.path.join(self.app.config["TEMPLATES_DIR"], "themes", theme)

    def _products_plugin(self):
        """Soft dependency on the products plugin, same pattern as the
        i18n lookup in app/core/decorators.py — degrades gracefully (no
        product-detail override) if products isn't loaded/enabled."""
        return self.app.core.plugins.plugins.get("products") if hasattr(self.app, "core") else None

    # ---------------- public route overrides ----------------
    async def _public_home(self):
        active = await self.get_setting("active_theme", "default")
        if get_registry(active, "home"):
            return await renderer.render_page(active, "home", self.db)
        orig = getattr(self.app, "_theme_builder_orig_index", None)
        if orig is not None:
            return await orig()
        return render_template("index.html")

    async def _public_product_detail(self, slug):
        active = await self.get_setting("active_theme", "default")
        products = self._products_plugin()
        orig = getattr(self.app, "_theme_builder_orig_product_page", None)
        if get_registry(active, "product-detail") and products is not None:
            product = await products._load_product_by_slug(slug)
            if product:
                product = _normalize_product(product)
                return await renderer.render_page(
                    active, "product-detail", self.db, page_context={"product": product},
                )
        if orig is not None:
            return await orig(slug)
        return render_template("404.html"), 404

    # ---------------- routes ----------------
    def register(self):
        bp = Blueprint("plugin_theme_builder", __name__)

        # ---------- admin: page shells (the pages fetch everything from the JSON API below) ----------
        page_route(bp, "/admin/site-theme", "admin_site_theme", "site_theme", "قالب سایت", "pages-theme")

        @bp.route("/admin/site-theme/builder/<theme>/<page>")
        @admin_required
        async def admin_builder(theme, page):
            if not get_registry(theme, page):
                return redirect("/admin/site-theme")
            return await render_admin("admin_ui/builder.html", theme=theme, page=page, page_title="ویرایشگر قالب")

        # ---------- admin: JSON API ----------
        def need_registry(theme, page):
            if not get_registry(theme, page):
                raise ApiError(404, "not_found", "این قالب/صفحه ویرایشگر ندارد")

        @api_route(bp, "/api/admin/site-theme/themes", "api_theme_list")
        async def api_theme_list():
            themes = self.list_themes()
            active = await self.get_setting("active_theme", "default")
            return reply({
                "themes": themes, "active": active,
                "theme_pages": {t: pages_for_theme(t) for t in themes},
                "page_labels": {"home": "ویرایش صفحه اصلی", "product-detail": "ویرایش صفحه محصول/پروژه"},
            })

        @api_route(bp, "/api/admin/site-theme/activate", "api_activate_theme", ["POST"])
        async def api_activate_theme():
            theme = str(body().get("theme") or "default").strip()
            if theme != "default" and theme not in self.list_themes():
                raise invalid({"theme": "قالب یافت نشد"})
            await self.set_setting("active_theme", theme)
            return reply({"active": theme})

        @api_route(bp, "/api/admin/site-theme/builder/<theme>/<page>", "api_builder_bootstrap")
        async def api_builder_bootstrap(theme, page):
            need_registry(theme, page)
            design = storage.get_active_design(theme, page)
            if design is None:
                design = storage.seed_default_design(
                    theme, page, get_registry(theme, page), default_row_order(theme, page),
                )
            return reply({
                "catalog": widget_catalog_json(theme, page), "design": design,
                "designs": storage.list_designs(theme, page), "needs_sample_product": (page == "product-detail"),
            })

        @api_route(bp, "/api/admin/site-theme/builder/<theme>/<page>/designs", "api_designs", ["GET", "POST"])
        async def api_designs(theme, page):
            need_registry(theme, page)
            if request.method == "POST":
                data = body()
                design_id = data.get("id") or None
                name = (str(data.get("name") or "")).strip() or "طرح بدون‌نام"
                rows = data.get("rows") or []
                doc = storage.save_design(theme, page, design_id, name, rows, set_active=bool(data.get("set_active")))
                return reply({"design": doc})
            return reply({"designs": storage.list_designs(theme, page), "active": storage.read_manifest(theme, page).get("active")})

        @api_route(bp, "/api/admin/site-theme/builder/<theme>/<page>/designs/<design_id>", "api_design", ["GET", "DELETE"])
        async def api_design(theme, page, design_id):
            need_registry(theme, page)
            if request.method == "DELETE":
                if not storage.delete_design(theme, page, design_id):
                    raise ApiError(404, "not_found", "طرح یافت نشد")
                return reply({"deleted": design_id})
            doc = storage.get_design(theme, page, design_id)
            if not doc:
                raise ApiError(404, "not_found", "طرح یافت نشد")
            return reply({"design": doc})

        @api_route(bp, "/api/admin/site-theme/builder/<theme>/<page>/designs/<design_id>/activate", "api_activate_design", ["POST"])
        async def api_activate_design(theme, page, design_id):
            need_registry(theme, page)
            if not storage.activate_design(theme, page, design_id):
                raise ApiError(404, "not_found", "طرح یافت نشد")
            return reply({"active": design_id})

        @api_route(bp, "/api/admin/site-theme/builder/<theme>/<page>/preview", "api_preview", ["POST"])
        async def api_preview(theme, page):
            need_registry(theme, page)
            data = body()
            rows = data.get("rows") or []
            page_context = None
            sample_slug = (str(data.get("sample_product_slug") or "")).strip()
            if sample_slug:
                products = self._products_plugin()
                if products is not None:
                    product = await products._load_product_by_slug(sample_slug)
                    if product:
                        page_context = {"product": _normalize_product(product)}
            html = await renderer.render_preview(theme, page, rows, self.db, page_context)
            return Response(html, mimetype="text/html")

        # ---------- public: theme static assets ----------
        @bp.route("/theme-assets/<theme>/<path:filename>")
        async def theme_asset(theme, filename):
            try:
                root = self._theme_assets_root(theme)
                rel = _safe_rel(filename)
            except ValueError:
                return ("invalid path", 400)
            return send_from_directory(root, rel)

        self.app.register_blueprint(bp)

        # ---------- override the public homepage ----------
        if not hasattr(self.app, "_theme_builder_orig_index"):
            self.app._theme_builder_orig_index = self.app.view_functions.get("core.index")
        self.app.view_functions["core.index"] = self._public_home

        # ---------- override the public product-detail page ----------
        # Only if the products plugin's route is already registered (it
        # discovers/activates alphabetically before "theme_builder", so
        # this is populated whenever products is enabled).
        if "plugin_products.public_page" in self.app.view_functions:
            if not hasattr(self.app, "_theme_builder_orig_product_page"):
                self.app._theme_builder_orig_product_page = \
                    self.app.view_functions["plugin_products.public_page"]
            self.app.view_functions["plugin_products.public_page"] = self._public_product_detail

    def unregister(self):
        orig_index = getattr(self.app, "_theme_builder_orig_index", None)
        if orig_index is not None:
            self.app.view_functions["core.index"] = orig_index
        orig_product = getattr(self.app, "_theme_builder_orig_product_page", None)
        if orig_product is not None and "plugin_products.public_page" in self.app.view_functions:
            self.app.view_functions["plugin_products.public_page"] = orig_product
