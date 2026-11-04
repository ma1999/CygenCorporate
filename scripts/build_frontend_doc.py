"""Builds docs/frontend-api.md from scripts/frontend_api.template.md.

Every ``@@GET /path@@`` / ``@@POST /path {json}@@`` token in the template is
replaced by the REAL response of the running app (in-process Flask test
client, seeded with scripts/seed_demo.py). Large payloads are shortened so the
document stays readable: lists keep ``N`` items (``|n=2``), and dicts named
``media`` / ``page_meta`` keep their first keys; a ``"…"`` marker says what was
cut. Run on a *throw-away* database (it posts one inquiry for the sample).

    python scripts/build_frontend_doc.py
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEMPLATE = ROOT / "scripts" / "frontend_api.template.md"
OUT = ROOT / "docs" / "frontend-api.md"
TOKEN = re.compile(r"@@(GET|POST|ERR503)\s*([^|@]*?)\s*(\{.*?\})?\s*(?:\|n=(\d+))?@@", re.S)


def shorten(node, n, key=None):
    if isinstance(node, list):
        out = [shorten(x, n) for x in node[:n]]
        if len(node) > n:
            out.append(f"… (+{len(node) - n} more)")
        return out
    if isinstance(node, dict):
        items = list(node.items())
        limit = 3 if key in ("media", "page_meta") else None
        out = {k: shorten(v, n, k) for k, v in (items[:limit] if limit else items)}
        if limit and len(items) > limit:
            out["…"] = f"{len(items) - limit} more keys"
        return out
    return node


def pretty(node, level=0, width=110) -> str:
    """JSON with small flat objects/arrays (I18nText, tags, ...) kept on one line."""
    one = json.dumps(node, ensure_ascii=False)
    pad = "  " * level
    if not isinstance(node, (dict, list)) or not node:
        return one
    flat = all(not isinstance(v, (dict, list)) for v in (node.values() if isinstance(node, dict) else node))
    if len(one) + len(pad) <= width and (flat or len(one) <= 60):
        return one
    inner = "  " * (level + 1)
    nl = chr(10)
    if isinstance(node, dict):
        rows = [f"{inner}{json.dumps(k, ensure_ascii=False)}: {pretty(v, level + 1, width)}" for k, v in node.items()]
        return "{" + nl + ("," + nl).join(rows) + nl + pad + "}"
    rows = [f"{inner}{pretty(v, level + 1, width)}" for v in node]
    return "[" + nl + ("," + nl).join(rows) + nl + pad + "]"


def main():
    from app import create_app

    app = create_app()
    client = app.test_client()
    ip = "2001:db8:%x:%x::7" % (random.getrandbits(16), random.getrandbits(16))

    def render(m):
        kind, path, body, n = m.group(1), m.group(2), m.group(3), int(m.group(4) or 3)
        if kind == "ERR503":
            app.cache.clear()
            with mock.patch.object(app.core.db, "_conn", side_effect=Exception("down")):
                r = client.get(path or "/api/public/products")
            data = json.loads(r.get_data())
        elif kind == "GET":
            r = client.get(path)
            data = json.loads(r.get_data()) if r.get_data() and "json" in r.headers.get("Content-Type", "") else r.get_data(as_text=True)
        else:
            r = client.post(path, json=json.loads(body), headers={"X-Real-IP": ip})
            data = json.loads(r.get_data())
        shown = shorten(data, n) if isinstance(data, (dict, list)) else data
        text = pretty(shown)
        return f"```json\n// HTTP {r.status_code}\n{text}\n```"

    template = TEMPLATE.read_text(encoding="utf-8")
    doc = TOKEN.sub(render, template)
    OUT.write_text(doc, encoding="utf-8")
    print(f"wrote {OUT} ({len(doc.splitlines())} lines, {len(TOKEN.findall(template))} live samples)")


if __name__ == "__main__":
    main()
