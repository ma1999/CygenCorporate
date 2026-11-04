"""File-based storage for saved page designs.

Layout (project root, sibling to uploads/ and logs/ — runtime data, not
source):

    designs/<theme>/<page>/manifest.json     {"active": "<id>", "designs": [...]}
    designs/<theme>/<page>/<design-id>.json  full design document

No DB table is used here on purpose — the user explicitly asked for
folder-based storage for designs.
"""
from __future__ import annotations

import json
import os
import time
import uuid

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))  # project root (plugin.py is 4 levels deep)
DESIGNS_ROOT = os.path.join(ROOT_DIR, "designs")


def _page_dir(theme: str, page: str) -> str:
    d = os.path.join(DESIGNS_ROOT, theme, page)
    os.makedirs(d, exist_ok=True)
    return d


def _manifest_path(theme: str, page: str) -> str:
    return os.path.join(_page_dir(theme, page), "manifest.json")


def _design_path(theme: str, page: str, design_id: str) -> str:
    safe_id = "".join(c for c in design_id if c.isalnum() or c in "-_")
    return os.path.join(_page_dir(theme, page), f"{safe_id}.json")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def read_manifest(theme: str, page: str) -> dict:
    path = _manifest_path(theme, page)
    if not os.path.isfile(path):
        return {"active": None, "designs": []}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"active": None, "designs": []}


def write_manifest(theme: str, page: str, manifest: dict) -> None:
    with open(_manifest_path(theme, page), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)


def list_designs(theme: str, page: str) -> list:
    manifest = read_manifest(theme, page)
    return sorted(manifest.get("designs", []), key=lambda d: d.get("updated_at", ""), reverse=True)


def get_design(theme: str, page: str, design_id: str) -> dict | None:
    path = _design_path(theme, page, design_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def save_design(theme: str, page: str, design_id: str | None, name: str,
                 rows: list, set_active: bool = False) -> dict:
    """Create or update a design document. Returns the saved document."""
    manifest = read_manifest(theme, page)
    now = _now()
    is_new = not design_id
    if is_new:
        design_id = f"design-{uuid.uuid4().hex[:10]}"
        created_at = now
    else:
        existing = get_design(theme, page, design_id)
        created_at = (existing or {}).get("created_at", now)

    doc = {
        "id": design_id, "theme": theme, "page": page,
        "name": name or "طرح بدون‌نام", "rows": rows,
        "created_at": created_at, "updated_at": now,
    }
    with open(_design_path(theme, page, design_id), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)

    designs = [d for d in manifest.get("designs", []) if d.get("id") != design_id]
    designs.append({"id": design_id, "name": doc["name"], "updated_at": now})
    manifest["designs"] = designs
    if set_active or not manifest.get("active"):
        manifest["active"] = design_id
    write_manifest(theme, page, manifest)
    return doc


def activate_design(theme: str, page: str, design_id: str) -> bool:
    if not get_design(theme, page, design_id):
        return False
    manifest = read_manifest(theme, page)
    manifest["active"] = design_id
    write_manifest(theme, page, manifest)
    return True


def delete_design(theme: str, page: str, design_id: str) -> bool:
    manifest = read_manifest(theme, page)
    designs = manifest.get("designs", [])
    if not any(d.get("id") == design_id for d in designs):
        return False
    designs = [d for d in designs if d.get("id") != design_id]
    manifest["designs"] = designs
    if manifest.get("active") == design_id:
        manifest["active"] = designs[0]["id"] if designs else None
    write_manifest(theme, page, manifest)
    path = _design_path(theme, page, design_id)
    if os.path.isfile(path):
        os.remove(path)
    return True


def get_active_design(theme: str, page: str) -> dict | None:
    manifest = read_manifest(theme, page)
    active = manifest.get("active")
    if not active:
        return None
    return get_design(theme, page, active)


def seed_default_design(theme: str, page: str, registry: dict, row_order: list) -> dict:
    """Build and save a factory-default design from each widget's
    default settings, in ``row_order``, and mark it active."""
    rows = []
    for widget_type in row_order:
        wdef = registry.get(widget_type)
        if not wdef:
            continue
        rows.append({
            "id": f"row-{uuid.uuid4().hex[:8]}",
            "boxes": [{
                "id": f"box-{uuid.uuid4().hex[:8]}",
                "widget": widget_type,
                "settings": dict(wdef.get("defaults", {})),
            }],
        })
    return save_design(theme, page, None, "طرح پیش‌فرض", rows, set_active=True)
