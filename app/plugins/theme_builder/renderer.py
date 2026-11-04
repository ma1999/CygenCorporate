"""Renders a saved (or in-progress) page design to HTML.

Single render pipeline shared by the public site route AND the admin
builder's live-preview endpoint, so what the admin sees while editing is
always exactly what gets published.
"""
from __future__ import annotations

from flask import current_app

from . import storage
from .widgets import get_registry, default_row_order


def _render(template_name: str, **context) -> str:
    """Render a template without going through Flask's context processors.

    ``flask.render_template`` merges every registered context processor —
    including core's ``inject_settings``, which (when called from inside an
    already-running event loop, as every call here is) spins up a fresh
    thread + nested event loop to run a DB query synchronously. That's fine
    for the one-render-per-request case it was written for, but this
    renderer calls ``render_template`` many times per request (once per
    widget row), which turned a single preview into several seconds of
    thread-spawning overhead. None of these widget/shell templates need
    ``settings``/``current_user``/``current_lang`` from context processors
    (they use their own explicitly-passed ``settings`` context var), so
    rendering straight off ``current_app.jinja_env`` is safe and skips that
    cost entirely.
    """
    return current_app.jinja_env.get_template(template_name).render(**context)


def _asset_fn(theme: str):
    base = f"/theme-assets/{theme}"

    def asset(path):
        if not path:
            return ""
        if path.startswith(("http://", "https://", "/")):
            return path
        return f"{base}/{path}"

    return asset


async def render_row_box(theme: str, page: str, box: dict, db, page_context: dict = None) -> str:
    registry = get_registry(theme, page)
    wdef = registry.get(box.get("widget"))
    if not wdef:
        return ""
    settings = {**wdef.get("defaults", {}), **(box.get("settings") or {})}
    extra = {}
    if wdef.get("dynamic") and wdef.get("data_provider"):
        extra = await wdef["data_provider"](db, settings, page_context)
    return _render(
        wdef["template"], settings=settings, asset=_asset_fn(theme),
        theme=theme, **(page_context or {}), **extra,
    )


async def render_rows(theme: str, page: str, rows: list, db, page_context: dict = None) -> str:
    parts = []
    for row in rows or []:
        for box in row.get("boxes", []):
            parts.append(await render_row_box(theme, page, box, db, page_context))
    return "\n".join(parts)


async def render_shell(theme: str, content_html: str) -> str:
    return _render(
        f"plugins/theme_builder/widgets/{theme}/_page_shell.html",
        content=content_html, asset=_asset_fn(theme), theme=theme,
    )


async def render_page(theme: str, page: str, db, page_context: dict = None) -> str:
    design = storage.get_active_design(theme, page)
    if design is None:
        design = storage.seed_default_design(
            theme, page, get_registry(theme, page), default_row_order(theme, page),
        )
    content = await render_rows(theme, page, design.get("rows", []), db, page_context)
    return await render_shell(theme, content)


async def render_preview(theme: str, page: str, rows: list, db, page_context: dict = None) -> str:
    content = await render_rows(theme, page, rows, db, page_context)
    return await render_shell(theme, content)
