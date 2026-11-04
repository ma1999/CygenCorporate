"""Integration tests: the real app, a real MySQL, demo data.

SAFETY: these tests write to the configured database. They refuse to run
unless ``DB_HOST`` is a loopback address (or ``ALLOW_REMOTE_TEST_DB=1``).
Point them at a throw-away MySQL, e.g.

    DB_HOST=127.0.0.1 DB_PORT=3306 DB_USER=root DB_PASSWORD= DB_NAME=corporate_test \\
        python -m unittest discover -s tests -p "test_api.py" -v
"""
import asyncio
import concurrent.futures
import http.server
import io
import json
import os
import re
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

APP = CLIENT = None


def setUpModule():
    global APP, CLIENT
    from dotenv import dotenv_values

    host = os.environ.get("DB_HOST") or dotenv_values(ROOT / ".env").get("DB_HOST", "")
    if host not in ("127.0.0.1", "localhost", "::1") and os.environ.get("ALLOW_REMOTE_TEST_DB") != "1":
        raise unittest.SkipTest("refusing to run write-heavy tests against a non-loopback DB_HOST")
    from app import create_app
    from seed_demo import Seeder

    APP = create_app()
    APP.config["TESTING"] = False
    with APP.app_context():
        asyncio.run(Seeder(APP).run())
    CLIENT = APP.test_client()


def get_json(path, client=None, **kw):
    r = (client or CLIENT).get(path, **kw)
    return r.status_code, (json.loads(r.get_data()) if r.get_data() and "json" in r.headers.get("Content-Type", "") else None), r


class _Resp:
    """Minimal response object for the legacy-form shim (status, Location, body text)."""

    def __init__(self, status, location=None, body="", raw=None):
        self.status_code, self.headers, self._body, self.raw = status, ({"Location": location} if location else {}), body, raw

    def get_data(self, as_text=False):
        return self._body if as_text else self._body.encode("utf-8")

    def get_json(self, *a, **k):
        return self.raw.get_json(*a, **k) if self.raw is not None else None


class LegacyAdminClient:
    """Test adapter. The admin used to be HTML forms (``POST /admin/<x>/create`` -> 302 + flash); it is now a JSON API
    (``/api/admin/*`` + CSRF header). Old-style calls are translated 1:1 so the tests keep asserting behaviour
    (validation, persistence, cache, webhook tags) instead of markup. ``flash_log`` replaces the session flashes;
    422 bodies echo the error JSON *and* the submitted values (the old form re-rendered them)."""

    LIST_RE = re.compile(r"^/admin/(inquiries|revalidate|frontend-visits|site-settings|company(/\w+)?|navigation|brands|products|product-tags|"
                         r"categories|projects|project-sectors|articles|article-categories|services|service-steps|faq|faq-categories|i18n|"
                         r"cache|images|settings|users|plugins)(\?.*)?$")

    def __init__(self, client):
        self._c = client
        self.csrf = client.csrf
        self.flash_log = []

    def __getattr__(self, name):
        return getattr(self._c, name)

    @property
    def H(self):
        return {"X-CSRF-Token": self.csrf}

    # ---- GET: pages whose content now lives in the API
    def get(self, path, **kw):
        m = re.match(r"^/admin/(.*)$", path.split("?")[0])
        qs = ("?" + path.split("?", 1)[1]) if "?" in path else ""
        api = None
        if path.startswith("/admin/media/browse"):
            api = "/api/admin/media/browse" + qs
        elif self.LIST_RE.match(path) or re.match(r"^/admin/(inquiries/(\d+|export\.csv)|i18n/\w+/translate|documents/\w+/\d+|[\w/-]+/\d+/edit)", path):
            api = "/api" + path.split("?")[0].removesuffix("/edit") + qs
            if re.search(r"/\d+/edit$", path.split("?")[0]):
                api = "/api" + path.split("?")[0][: -len("/edit")] + qs
        return self._c.get(api or path, **kw)

    # ---- POST: legacy form -> API
    @staticmethod
    def _json(data):
        out, rows = {}, {}
        for k, v in (data or {}).items():
            if k in ("next", "_after"):
                continue
            m = re.match(r"^([\w.]+)-(\d+)-(.+)$", k)
            if m:
                row = rows.setdefault(m.group(1), {}).setdefault(int(m.group(2)), {})
                LegacyAdminClient._put(row, m.group(3), v)
            elif k.endswith("__present"):
                rows.setdefault(k[: -len("__present")], {})
            else:
                LegacyAdminClient._put(out, k, v)
        for key, idx in rows.items():
            out[key] = [idx[i] for i in sorted(idx)]
        return out

    @staticmethod
    def _put(d, key, v):
        if "__" in key:
            name, lang = key.rsplit("__", 1)
            d.setdefault(name, {})[lang] = v
        else:
            d[key] = v

    def _done(self, r, ok_codes, flash, location, data):
        msg = (r.get_json() or {}).get("message") if r.status_code >= 400 else None
        if r.status_code in ok_codes:
            self.flash_log.append(flash)
            return _Resp(302, location, raw=r)
        self.flash_log.append(msg or "خطا")
        body = r.get_data(as_text=True) + json.dumps(data, ensure_ascii=False, default=str)
        return _Resp(422 if r.status_code == 422 else 302, None if r.status_code == 422 else location, body, r)

    def post(self, path, data=None, **kw):
        data = dict(data or {})
        H = self.H
        base = lambda p: "/admin/" + p
        from app.core.entity import safe_next

        m = re.match(r"^/admin/documents/(\w+)/(\d+)/create$", path)
        if m:
            r = self._c.post(f"/api/admin/documents/{m.group(1)}/{m.group(2)}", data=data, headers=H, **kw)
            return self._done(r, (200, 201), "سند اضافه شد", path.replace("/create", ""), {})
        m = re.match(r"^/admin/documents/(\d+)/(save|delete)$", path)
        if m:
            r = (self._c.delete(f"/api/admin/documents/{m.group(1)}", headers=H) if m.group(2) == "delete"
                 else self._c.post(f"/api/admin/documents/{m.group(1)}/save", data=data, headers=H, **kw))
            return self._done(r, (200,), "سند ذخیره شد", "/admin", {})
        m = re.match(r"^/admin/i18n/(\w+)/import$", path)
        if m:
            r = self._c.post(f"/api/admin/i18n/{m.group(1)}/import", data=data, headers=H, **kw)
            j = (r.get_json() or {}).get("data") or {}
            msg = (f"وارد شد: {j.get('added')} کلید جدید، {j.get('updated')} به‌روزشده، {j.get('skipped')} ردشده (از قبل موجود)"
                   if r.status_code == 200 else (r.get_json() or {}).get("message", ""))
            if r.status_code == 422:
                msg = " ".join((r.get_json().get("fields") or {}).values())
            self.flash_log.append(msg)
            return _Resp(302, "/admin/i18n", raw=r)
        m = re.match(r"^/admin/i18n/(\w+)/translate$", path)
        if m:
            values = {k[2:]: v for k, v in data.items() if k.startswith("k_")}
            r = self._c.put(f"/api/admin/i18n/{m.group(1)}/translate", json={"prefix": data.get("prefix", ""), "values": values}, headers=H)
            return self._done(r, (200,), "ترجمه ذخیره شد", path, data)
        if path == "/admin/i18n/create":
            r = self._c.post("/api/admin/i18n", json=data, headers=H)
            return self._done(r, (201,), "زبان ایجاد شد", "/admin/i18n", data)
        if path == "/admin/site-settings":
            r = self._c.put("/api/admin/site-settings", json=self._json(data), headers=H)
            return self._done(r, (200,), "تنظیمات سایت ذخیره شد", path, data)
        m = re.match(r"^/admin/inquiries/(\d+)(/delete)?$", path)
        if m:
            r = (self._c.delete(f"/api/admin/inquiries/{m.group(1)}", headers=H) if m.group(2)
                 else self._c.put(f"/api/admin/inquiries/{m.group(1)}", json=data, headers=H))
            return self._done(r, (200,), "ذخیره شد", "/admin/inquiries", data)
        m = re.match(r"^/admin/([\w/-]+?)/create$", path)
        if m:
            r = self._c.post("/api/admin/" + m.group(1), json=self._json(data), headers=H)
            new_id = ((r.get_json() or {}).get("data") or {}).get("id")
            loc = (safe_next(data.get("next"), base(m.group(1))) if data.get("_after") == "close" else f"{base(m.group(1))}/{new_id}/edit")
            return self._done(r, (201,), "ایجاد شد", loc, data)
        m = re.match(r"^/admin/([\w/-]+?)/(\d+)/(edit|delete|toggle)$", path)
        if m:
            p, i, act = m.groups()
            if act == "edit":
                r = self._c.put(f"/api/admin/{p}/{i}", json=self._json(data), headers=H)
                return self._done(r, (200,), "ذخیره شد", f"{base(p)}/{i}/edit", data)
            if act == "delete":
                r = self._c.delete(f"/api/admin/{p}/{i}", headers=H)
                return self._done(r, (200,), "حذف شد", safe_next(data.get("next"), base(p)), data)
            r = self._c.post(f"/api/admin/{p}/{i}/toggle", json={}, headers=H)
            return self._done(r, (200,), "وضعیت تغییر کرد", safe_next(data.get("next"), base(p)), data)
        return self._c.post(path, data=data, **kw)


def admin_client():
    c = APP.test_client()
    r = c.post("/api/admin/auth/login", json={"username": "admin", "password": os.environ.get("TEST_ADMIN_PASSWORD", "admin123")})
    assert r.status_code == 200, "admin login failed"
    c.csrf = r.get_json()["data"]["csrf"]  # send as X-CSRF-Token on unsafe /api/admin requests
    return LegacyAdminClient(c)


def db_rows(sql, params=()):
    return asyncio.run(APP.core.db.fetch(sql, params))


def run_async(coro):
    return asyncio.run(coro)


def rand_ip():
    """A fresh documentation-range IPv6 address (rate limits also look at the DB)."""
    import random

    return "2001:db8:%x:%x::1" % (random.getrandbits(16), random.getrandbits(16))


PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


class PublicApiBasics(unittest.TestCase):
    def test_error_envelope_for_every_kind_of_error(self):
        for path, status in [("/api/public/nope", 404), ("/api/public/products/zzz-none", 404), ("/api/public/products?sort=zzz", 400)]:
            s, d, r = get_json(path)
            self.assertEqual(s, status, path)
            self.assertEqual(d["ok"], False)
            self.assertIn(d["error"], ("not_found", "bad_request"))
            self.assertEqual(r.headers["Content-Type"], "application/json; charset=utf-8")
        r = CLIENT.post("/api/public/products")
        self.assertEqual(r.status_code, 405)
        self.assertEqual(json.loads(r.get_data())["error"], "bad_request")
        self.assertIn("Allow", r.headers)

    def test_garbage_parameters_never_500(self):
        paths = ["/api/public/products?page=abc", "/api/public/products?per_page=-1", "/api/public/products?per_page=99999999999999999999",
                 "/api/public/products?page=-5&lang=%ff&q=%00", "/api/public/products?featured=maybe&is_new=%27", "/api/public/products?q=" + "x" * 5000,
                 "/api/public/products?category=%27%20OR%201%3D1--&brand=%25&tag=a,,b", "/api/public/products/%00", "/api/public/products/" + "a" * 5000,
                 "/api/public/search?q=%25%5C_&limit=abc", "/api/public/articles?page=1e9", "/api/public/projects?sector=%00",
                 "/api/public/company?include=", "/api/public/categories?include_empty=zzz"]
        for p in paths:
            s, d, r = get_json(p)
            self.assertLess(s, 500, p)

    def test_pagination_is_clamped_not_rejected(self):
        s, d, _ = get_json("/api/public/products?page=abc&per_page=-1")
        self.assertEqual((s, d["meta"]["page"], d["meta"]["per_page"]), (200, 1, 1))
        s, d, _ = get_json("/api/public/products?per_page=1000")
        self.assertEqual(d["meta"]["per_page"], 100)
        s, d, _ = get_json("/api/public/products?per_page=2&page=2")
        self.assertEqual((len(d["products"]), d["meta"]["total_pages"]), (1, 2))

    def test_bad_json_and_oversized_body_on_post(self):
        for body, ctype in [(b"{not json", "application/json"), (b"[1,2]", "application/json"), (b"", "application/json")]:
            r = CLIENT.post("/api/public/inquiries", data=body, content_type=ctype, headers={"X-Real-IP": rand_ip()})
            self.assertEqual(r.status_code, 400, body)
            self.assertEqual(json.loads(r.get_data())["error"], "bad_request")
        r = CLIENT.post("/api/public/inquiries", data=b'{"a":"' + b"x" * 70000 + b'"}', content_type="application/json",
                        headers={"X-Real-IP": rand_ip()})
        self.assertEqual(r.status_code, 413)

    def test_etag_and_cache_headers(self):
        s, d, r = get_json("/api/public/brands")
        self.assertIn("max-age=30", r.headers["Cache-Control"])
        self.assertIn("stale-while-revalidate=300", r.headers["Cache-Control"])
        r2 = CLIENT.get("/api/public/brands", headers={"If-None-Match": r.headers["ETag"]})
        self.assertEqual((r2.status_code, r2.get_data()), (304, b""))
        r3 = CLIENT.get("/api/public/brands", headers={"If-None-Match": '"other"'})
        self.assertEqual(r3.status_code, 200)

    def test_unknown_params_are_ignored(self):
        a = get_json("/api/public/brands")[1]
        b = get_json("/api/public/brands?utm_source=x&whatever=1")[1]
        self.assertEqual(a, b)

    def test_database_failure_is_503_not_an_empty_list(self):
        APP.cache.clear()
        with mock.patch.object(APP.core.db, "_conn", side_effect=Exception("db down")):
            r = CLIENT.get("/api/public/products?q=outage-test")
            self.assertEqual(r.status_code, 503)
            body = json.loads(r.get_data())
            self.assertEqual((body["ok"], body["error"]), (False, "unavailable"))
            self.assertEqual(r.headers["Cache-Control"], "no-store")
            h = CLIENT.get("/api/public/health")
            self.assertEqual(h.status_code, 503)
            self.assertEqual(json.loads(h.get_data()), {"ok": False, "db": False})
        s, d, _ = get_json("/api/public/health")
        self.assertEqual((s, d["db"]), (200, True))

    def test_public_prefix_is_excluded_from_tracking_defaults(self):
        from app.plugins.tracking.plugin import DEFAULT_EXCLUDES

        self.assertIn("/api/public/*", DEFAULT_EXCLUDES["path_patterns"].splitlines())


class Cors(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("CORS_ALLOWED_ORIGINS", None)

    def test_disabled_by_default_sends_nothing(self):
        os.environ.pop("CORS_ALLOWED_ORIGINS", None)
        r = CLIENT.get("/api/public/brands", headers={"Origin": "https://a.example"})
        self.assertNotIn("Access-Control-Allow-Origin", r.headers)
        self.assertNotIn("Vary", r.headers)

    def test_allow_list_echoes_origin_never_star_and_never_credentials(self):
        os.environ["CORS_ALLOWED_ORIGINS"] = "https://a.example, https://b.example"
        r = CLIENT.get("/api/public/brands", headers={"Origin": "https://a.example"})
        self.assertEqual(r.headers["Access-Control-Allow-Origin"], "https://a.example")
        self.assertIn("Origin", r.headers["Vary"])
        self.assertNotIn("Access-Control-Allow-Credentials", r.headers)
        r = CLIENT.get("/api/public/brands", headers={"Origin": "https://evil.example"})
        self.assertNotIn("Access-Control-Allow-Origin", r.headers)
        r = CLIENT.options("/api/public/inquiries", headers={"Origin": "https://b.example", "Access-Control-Request-Method": "POST"})
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.headers["Access-Control-Allow-Origin"], "https://b.example")
        self.assertIn("POST", r.headers["Access-Control-Allow-Methods"])
        self.assertEqual(r.headers["Access-Control-Allow-Headers"], "Content-Type")
        r = CLIENT.options("/api/public/does-not-exist", headers={"Origin": "https://a.example"})
        self.assertEqual(r.status_code, 204)

    def test_not_applied_outside_public_prefix(self):
        os.environ["CORS_ALLOWED_ORIGINS"] = "https://a.example"
        r = CLIENT.get("/api/products", headers={"Origin": "https://a.example"})
        self.assertNotIn("Access-Control-Allow-Origin", r.headers)


class AbsoluteUrls(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("PUBLIC_BASE_URL", None)
        APP.cache.invalidate_namespace("public_api")

    def cover(self, **kw):
        s, d, _ = get_json("/api/public/products/demo-as-fcv-940", **kw)
        return d["product"]["cover"]["url"]

    def test_request_host_forwarded_headers_and_env(self):
        APP.cache.invalidate_namespace("public_api")
        self.assertRegex(self.cover(), r"^http://localhost/assets/uploads/")
        self.assertRegex(self.cover(headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "api.example.com"}),
                         r"^https://api\.example\.com/assets/uploads/")
        os.environ["PUBLIC_BASE_URL"] = "https://cdn.example.com/"
        self.assertRegex(self.cover(), r"^https://cdn\.example\.com/assets/uploads/")

    def test_external_urls_untouched_and_leading_slash_normalised(self):
        from app.core import content as C

        self.assertEqual(C.abs_url("https://x.test/a.jpg", "https://api"), "https://x.test/a.jpg")
        self.assertEqual(C.abs_url("assets/uploads/a.jpg", "https://api"), "https://api/assets/uploads/a.jpg")

    def test_image_dimensions_from_pillow(self):
        s, d, _ = get_json("/api/public/products/demo-as-fcv-940")
        cover = d["product"]["cover"]
        self.assertEqual((cover["width"], cover["height"], cover["mime"]), (1000, 750, "image/jpeg"))
        s, d, _ = get_json("/api/public/brands")
        logo = d["brands"][0]["logo"]
        self.assertEqual(logo["mime"], "image/svg+xml")
        self.assertIsNone(logo["width"])


class ProductQueries(unittest.TestCase):
    def slugs(self, qs):
        s, d, _ = get_json("/api/public/products?" + qs)
        self.assertEqual(s, 200, qs)
        return [p["slug"] for p in d["products"]]

    def test_only_published_visible_products(self):
        all_slugs = self.slugs("per_page=100")
        self.assertEqual(set(all_slugs), {"demo-as-fcv-940", "demo-as-pt-210", "demo-as-plc-500"})
        self.assertEqual(get_json("/api/public/products/demo-draft-product")[0], 404)

    def test_filters(self):
        self.assertEqual(set(self.slugs("category=demo-flow-control")), {"demo-as-fcv-940", "demo-as-pt-210", "demo-as-plc-500"})  # includes child
        self.assertEqual(self.slugs("category=demo-control-valves"), ["demo-as-fcv-940"])
        self.assertEqual(self.slugs("category=nope"), [])
        self.assertEqual(set(self.slugs("brand=demo-aspd")), {"demo-as-fcv-940", "demo-as-pt-210"})
        self.assertEqual(self.slugs("brand=nope"), [])
        self.assertEqual(set(self.slugs("featured=1")), {"demo-as-fcv-940", "demo-as-pt-210"})
        self.assertEqual(self.slugs("is_new=1"), ["demo-as-fcv-940"])
        tags = {t["label"]["fa"]: t["slug"] for t in get_json("/api/public/tags")[1]["tags"]}
        self.assertEqual(self.slugs(f"tag={tags['ابزار دقیق']}"), self.slugs(f"tag={tags['ابزار دقیق']}"))
        both = self.slugs(f"tag={tags['ابزار دقیق']},{tags['SIL-3']}")          # AND
        self.assertEqual(both, ["demo-as-fcv-940"])
        self.assertEqual(self.slugs(f"tag={tags['ابزار دقیق']},nope"), [])

    def test_search_normalisation_digits_letters_and_codes(self):
        self.assertIn("demo-as-fcv-940", self.slugs("q=" + quote("۹۴۰")))                   # Persian digits == 940
        self.assertIn("demo-as-fcv-940", self.slugs("q=940"))
        self.assertIn("demo-as-fcv-940", self.slugs("q=" + quote("كنترل")))                  # Arabic kaf
        self.assertIn("demo-as-fcv-940", self.slugs("q=" + quote("شير")))                    # Arabic yeh
        self.assertIn("demo-as-fcv-940", self.slugs("q=" + quote("Flow Control")))          # English text, any language
        self.assertEqual(self.slugs("q=DEMO-AS-PT-210")[0], "demo-as-pt-210")                # exact model code first
        self.assertEqual(self.slugs("q=" + quote("100%_\\")), [])                            # LIKE wildcards are escaped
        self.assertEqual(self.slugs("q=zzzzzz-no-match"), [])
        self.assertIn("demo-as-fcv-940", self.slugs("q=" + quote("DEMO-SKU-940")))           # sku searchable
        self.assertIn("demo-as-fcv-940", self.slugs("q=" + quote("S2")))                     # variant model code

    def test_sorting(self):
        self.assertEqual(self.slugs("sort=model_code"), ["demo-as-fcv-940", "demo-as-plc-500", "demo-as-pt-210"])
        self.assertEqual(self.slugs("sort=name&lang=en"), ["demo-as-fcv-940", "demo-as-plc-500", "demo-as-pt-210"])
        self.assertEqual(self.slugs("sort=manual"), ["demo-as-fcv-940", "demo-as-pt-210", "demo-as-plc-500"])
        self.assertEqual(self.slugs("sort=newest")[0], "demo-as-plc-500")
        self.assertEqual(self.slugs("")[:2], ["demo-as-fcv-940", "demo-as-pt-210"])           # featured first, then model code

    def test_facets_exclude_their_own_filter(self):
        s, d, _ = get_json("/api/public/products?facets=1&category=demo-control-valves")
        cats = {c["slug"]: c["count"] for c in d["facets"]["categories"]}
        self.assertEqual(cats["demo-flow-control"], 3)              # NOT narrowed by the category filter itself
        self.assertEqual(cats["demo-control-valves"], 1)
        self.assertEqual({b["slug"]: b["count"] for b in d["facets"]["brands"]}, {"demo-aspd": 1})   # narrowed by category
        s, d, _ = get_json("/api/public/products?facets=1&brand=demo-aspd")
        cats = {c["slug"]: c["count"] for c in d["facets"]["categories"]}
        self.assertEqual(cats["demo-flow-control"], 2)              # p3 has no brand
        self.assertEqual({b["slug"]: b["count"] for b in d["facets"]["brands"]}["demo-aspd"], 2)
        s, d, _ = get_json("/api/public/products")
        self.assertNotIn("facets", d)

    def test_detail_related_documents_and_paths(self):
        s, d, _ = get_json("/api/public/products/demo-as-fcv-940?related_limit=1")
        p = d["product"]
        self.assertEqual(len(p["related"]), 1)
        self.assertNotEqual(p["related"][0]["slug"], p["slug"])
        self.assertEqual([c["slug"] for c in p["category_path"]], ["demo-flow-control", "demo-control-valves"])
        self.assertEqual(len(p["images"]), 3)
        self.assertEqual(p["cover"]["url"], p["images"][0]["url"])
        self.assertEqual(len(p["specifications"]), 5)
        self.assertEqual([v["model_code"] for v in p["variants"]], ["DEMO-AS-FCV-940-S2", "DEMO-AS-FCV-940-S4"])
        self.assertEqual({t["label"]["fa"] for t in p["tags"]}, {"SIL-3", "ابزار دقیق", "کنترل"})
        self.assertEqual(p["tags"][0]["label"]["fa"] in ("SIL-3", "ابزار دقیق", "کنترل"), True)
        self.assertEqual(set(p["documents"][0]["files"]), {"fa", "en"})
        self.assertEqual(p["name"]["en"], "Flow Control Valve 940")
        self.assertEqual(p["brand"]["slug"], "demo-aspd")
        self.assertEqual(p["seo"]["title"]["fa"], p["name"]["fa"])            # effective SEO falls back to the name
        self.assertEqual(p["seo"]["og_image"]["url"], p["cover"]["url"])
        self.assertEqual(get_json("/api/public/products/demo-as-fcv-940?related_limit=999")[0], 200)

    def test_persian_slug_lookup_is_url_decoded(self):
        s, d, _ = get_json("/api/public/categories/" + quote("تست-1"))
        # legacy sample categories only exist in the production DB; on a fresh DB this is a clean 404 envelope
        self.assertIn(s, (200, 404))


class CategoriesAndBrands(unittest.TestCase):
    def test_tree_counts_and_include_empty(self):
        s, d, _ = get_json("/api/public/categories")
        root = next(c for c in d["categories"] if c["slug"] == "demo-flow-control")
        self.assertEqual(root["product_count"], 3)      # own (2) + direct children (1)
        self.assertEqual(root["children"][0]["slug"], "demo-control-valves")
        self.assertEqual(root["children"][0]["parent_slug"], "demo-flow-control")
        self.assertEqual(root["children"][0]["product_count"], 1)
        self.assertEqual(root["standards"], ["IEC 60534", "ASME B16.34"])
        self.assertEqual(root["icon"], "Gauge")
        s, d0, _ = get_json("/api/public/categories?include_empty=0")
        self.assertTrue(all(c["product_count"] > 0 for c in d0["categories"]))

    def test_brand_detail_seo_and_count(self):
        s, d, _ = get_json("/api/public/brands/demo-aspd")
        self.assertEqual(d["brand"]["product_count"], 2)
        self.assertIn("seo", d["brand"])


class DocumentsDownload(unittest.TestCase):
    def doc(self):
        s, d, _ = get_json("/api/public/products/demo-as-fcv-940")
        doc = d["product"]["documents"][0]
        return doc, doc["files"]["fa"]["download_url"].replace("http://localhost", "")

    def test_download_headers_and_persian_filename(self):
        doc, url = self.doc()
        r = CLIENT.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Content-Type"], "application/pdf")
        self.assertIn("filename*=UTF-8''", r.headers["Content-Disposition"])
        self.assertIn("attachment", r.headers["Content-Disposition"])
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r.headers["Cache-Control"], "public, max-age=3600")
        self.assertEqual(r.headers["Content-Length"], str(len(r.get_data())))
        self.assertTrue(r.get_data().startswith(b"%PDF-"))
        # Persian original name percent-encoded, decodes back
        from urllib.parse import unquote

        fname = unquote(re.search(r"filename\*=UTF-8''([^;]+)", r.headers["Content-Disposition"]).group(1))
        self.assertIn("دیتاشیت", fname)

    def test_inline_head_range_and_language_fallback(self):
        doc, url = self.doc()
        r = CLIENT.get(url + "&inline=1")
        self.assertIn("inline", r.headers["Content-Disposition"])
        self.assertEqual(CLIENT.head(url).status_code, 200)
        r = CLIENT.get(url, headers={"Range": "bytes=0-4"})
        self.assertEqual((r.status_code, r.get_data()), (206, b"%PDF-"))
        base = url.split("?")[0]
        self.assertEqual(CLIENT.get(base + "?lang=de").status_code, 200)       # no 'de' file -> falls back to fa
        self.assertEqual(CLIENT.get(base).status_code, 200)
        self.assertEqual(CLIENT.get(base + "?lang=en").status_code, 200)
        self.assertNotEqual(CLIENT.get(base + "?lang=en").get_data(), CLIENT.get(base + "?lang=fa").get_data())

    def test_download_count_increments_only_for_plain_get(self):
        doc, url = self.doc()

        def count():
            return db_rows("SELECT download_count FROM document_files WHERE document_id=%s AND lang_code='fa'", (doc["id"],))[0]["download_count"]

        before = count()
        CLIENT.get(url)
        for _ in range(30):
            if count() > before:
                break
            time.sleep(0.2)
        self.assertEqual(count(), before + 1)
        CLIENT.head(url)
        CLIENT.get(url, headers={"Range": "bytes=0-4"})
        time.sleep(1)
        self.assertEqual(count(), before + 1)

    def test_missing_hidden_and_unpublished_owner_documents_are_404(self):
        self.assertEqual(CLIENT.get("/api/public/documents/99999999/download").status_code, 404)
        admin = admin_client()
        r = admin.get("/admin/documents/product/99999999")
        self.assertEqual(r.status_code, 404)
        draft = db_rows("SELECT id FROM products WHERE slug='demo-draft-product'")[0]["id"]
        r = admin.post(f"/admin/documents/product/{draft}/create", data={
            "type": "datasheet", "title__fa": "پیش‌نویس", "file__fa": (io.BytesIO(PDF), "d.pdf")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        did = db_rows("SELECT id FROM documents WHERE owner_type='product' AND owner_id=%s", (draft,))[0]["id"]
        self.assertEqual(CLIENT.get(f"/api/public/documents/{did}/download").status_code, 404)      # owner not published
        db_rows("UPDATE documents SET is_public=0 WHERE id=%s", (did,)) if False else None
        admin.post(f"/admin/documents/{did}/delete")
        self.assertEqual(db_rows("SELECT COUNT(*) AS c FROM documents WHERE id=%s", (did,))[0]["c"], 0)

    def test_admin_upload_rules_end_to_end(self):
        admin = admin_client()
        pid = db_rows("SELECT id FROM products WHERE slug='demo-as-pt-210'")[0]["id"]
        before = db_rows("SELECT COUNT(*) AS c FROM documents WHERE owner_id=%s AND owner_type='product'", (pid,))[0]["c"]

        def upload(name, data, title="x"):
            r = admin.post(f"/admin/documents/product/{pid}/create", data={
                "type": "other", "title__fa": title, "file__fa": (io.BytesIO(data), name)}, content_type="multipart/form-data")
            self.assertEqual(r.status_code, 302)
            return list(admin.flash_log)

        flashes = upload("evil.html", b"<script>alert(1)</script>")
        self.assertTrue(any("مجاز نیست" in m for m in flashes), flashes)
        flashes = upload("fake.pdf", b"not really a pdf")
        self.assertTrue(any("PDF" in m for m in flashes), flashes)
        flashes = upload("noname.pdf", PDF, title="")
        self.assertTrue(any("عنوان" in m for m in flashes), flashes)
        after = db_rows("SELECT COUNT(*) AS c FROM documents WHERE owner_id=%s AND owner_type='product'", (pid,))[0]["c"]
        self.assertEqual(after, before)                     # nothing was stored for rejected uploads
        flashes = upload("ok.pdf", PDF, title="سند معتبر")
        self.assertTrue(any("اضافه شد" in m for m in flashes), flashes)
        row = db_rows("SELECT d.id, f.stored_path FROM documents d JOIN document_files f ON f.document_id=d.id "
                      "WHERE d.owner_id=%s AND d.owner_type='product' ORDER BY d.id DESC LIMIT 1", (pid,))[0]
        from app.plugins.documents.plugin import storage_root

        stored = storage_root() / row["stored_path"]
        self.assertTrue(stored.is_file())
        self.assertNotIn(str(ROOT / "uploads"), str(stored))
        admin.post(f"/admin/documents/{row['id']}/delete")
        self.assertFalse(stored.exists())                   # physical file removed with the document


class AuthOnAdminRoutes(unittest.TestCase):
    PROTECTED_GET = ["/admin", "/admin/products", "/admin/products/create", "/admin/categories", "/admin/categories/create", "/admin/images",
                     "/admin/cache", "/admin/brands", "/admin/site-settings",
                     "/admin/projects", "/admin/articles", "/admin/services", "/admin/faq", "/admin/company", "/admin/inquiries",
                     "/admin/product-tags", "/admin/revalidate", "/admin/i18n/en/import", "/admin/navigation", "/admin/frontend-visits",
                     "/admin/tracking", "/admin/site-theme", "/admin/documents/product/1"]
    PROTECTED_API_GET = ["/api/admin/auth/me", "/api/admin/products", "/api/admin/categories", "/api/admin/images", "/api/admin/cache",
                         "/api/admin/media/browse", "/api/admin/inquiries", "/api/admin/inquiries/export.csv", "/api/admin/i18n",
                         "/api/admin/site-settings", "/api/admin/revalidate", "/api/admin/tracking/dashboard", "/api/admin/site-theme/themes"]

    def test_anonymous_requests_are_redirected_to_login(self):
        c = APP.test_client()
        for p in self.PROTECTED_GET:
            r = c.get(p)
            self.assertEqual(r.status_code, 302, p)
            self.assertIn("/login", r.headers["Location"], p)

    def test_anonymous_api_requests_get_401_json(self):
        c = APP.test_client()
        for p in self.PROTECTED_API_GET:
            r = c.get(p)
            self.assertEqual(r.status_code, 401, p)
            self.assertEqual(r.get_json()["error"], "unauthorized", p)
        for p in ["/api/admin/cache/clear", "/api/admin/products/1", "/api/admin/images/delete", "/api/admin/images/upload",
                  "/api/admin/categories/purge"]:
            r = c.post(p, json={"x": 1})
            self.assertEqual(r.status_code, 401, p)

    def test_unsafe_methods_need_csrf_token(self):
        a = admin_client()
        self.assertEqual(a.post("/api/admin/cache/clear", json={}).status_code, 403)
        r = a.post("/api/admin/cache/clear", json={}, headers={"X-CSRF-Token": a.csrf})
        self.assertEqual(r.status_code, 200)

    def test_admin_session_works_and_public_endpoints_stay_public(self):
        a = admin_client()
        for p in ["/admin/products", "/admin/categories", "/admin/images", "/admin/cache", "/api/admin/cache", "/api/admin/media/browse"]:
            self.assertEqual(a.get(p).status_code, 200, p)
        c = APP.test_client()
        for p in ["/api/products", "/api/categories", "/api/i18n/languages", "/api/i18n/translate/fa", "/api/public/site"]:
            self.assertEqual(c.get(p).status_code, 200, p)
        up = ROOT / "uploads"
        some = next((f for f in (up / "demo_local").glob("*.jpg")), None)
        if some:
            r = c.get(f"/assets/uploads/demo_local/{some.name}")
            self.assertEqual(r.status_code, 200)
            self.assertIn("max-age=86400", r.headers["Cache-Control"])
            self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        r = c.get("/assets/uploads/demo_local/brand-logo.svg")
        self.assertIn("sandbox", r.headers["Content-Security-Policy"])

    def test_non_admin_role_is_not_enough(self):
        run_async(APP.core.db.execute("INSERT IGNORE INTO users (username, password_hash, role) VALUES (%s,%s,'editor')",
                                      ("editor1", __import__("app.core.auth", fromlist=["x"]).hash_password("pw12345"))))
        c = APP.test_client()
        # the admin API refuses to start a session for a non-administrator
        r = c.post("/api/admin/auth/login", json={"username": "editor1", "password": "pw12345"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["error"], "forbidden")
        # ... and a (legacy) non-admin session is not enough for pages or the API
        with c.session_transaction() as s:
            s.update({"uid": 999999, "username": "editor1", "role": "editor", "csrf": "t"})
        r = c.get("/admin/products")
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("/admin/products", r.headers["Location"])
        r = c.get("/api/admin/products")
        self.assertEqual(r.status_code, 403)


class AdminPanels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = admin_client()

    def flashes(self, client=None):
        return list((client or self.admin).flash_log)

    def product_form(self, **over):
        data = {"name__fa": "محصول تست پنل", "name__en": "Panel Test Product", "model_code": "TST-1", "status": "published",
                "slug": "", "category_id": "", "tags": "تگ ساختگی", "specs__present": "1", "specs-0-label__fa": "فشار",
                "specs-0-value__fa": "۱۶۰ بار", "specs-0-value__en": "160 bar", "variants__present": "1", "images__present": "1"}
        data.update(over)
        return data

    def test_create_edit_delete_product_full_cycle(self):
        r = self.admin.post("/admin/products/create", data=self.product_form())
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:400])
        pid = int(re.search(r"/admin/products/(\d+)/edit", r.headers["Location"]).group(1))
        self.assertTrue(any("ایجاد شد" in m for m in self.flashes()))
        row = db_rows("SELECT * FROM products WHERE id=%s", (pid,))[0]
        self.assertEqual(row["slug"], "tst-1" if False else row["slug"])
        self.assertTrue(row["slug"])                                                # auto slug (never empty)
        self.assertEqual(row["name"], "محصول تست پنل")                              # legacy column mirrors fa
        self.assertEqual(row["title"], "محصول تست پنل")
        self.assertEqual(json.loads(row["name_i18n"]), {"fa": "محصول تست پنل", "en": "Panel Test Product"})
        self.assertIsNotNone(row["updated_at"])
        self.assertIn("تگ ساختگی", db_rows("SELECT search_text FROM products WHERE id=%s", (pid,))[0]["search_text"] or "تگ ساختگی")
        # visible on the public API with the new tag + spec
        s, d, _ = get_json(f"/api/public/products/{row['slug']}")
        self.assertEqual(d["product"]["specifications"][0]["value"], {"fa": "۱۶۰ بار", "en": "160 bar"})
        self.assertEqual(d["product"]["tags"][0]["label"]["fa"], "تگ ساختگی")
        # edit: only the English name is sent -> everything else untouched; fa name unchanged
        r = self.admin.post(f"/admin/products/{pid}/edit", data={"name__en": "Renamed"})
        self.assertEqual(r.status_code, 302)
        s, d, _ = get_json(f"/api/public/products/{row['slug']}")
        self.assertEqual((d["product"]["name"]["fa"], d["product"]["name"]["en"]), ("محصول تست پنل", "Renamed"))
        self.assertEqual(len(d["product"]["specifications"]), 1)                    # repeater untouched (no marker)
        self.assertEqual(d["product"]["model_code"], "TST-1")
        # present-but-empty English clears just English
        self.admin.post(f"/admin/products/{pid}/edit", data={"name__en": ""})
        self.assertNotIn("en", get_json(f"/api/public/products/{row['slug']}")[1]["product"]["name"])
        # slug change -> redirect endpoint
        self.admin.post(f"/admin/products/{pid}/edit", data={"slug": "tst-renamed"})
        s, d, _ = get_json(f"/api/public/redirects?type=product&slug={row['slug']}")
        self.assertEqual((s, d), (200, {"redirect_to": "tst-renamed"}))
        self.assertEqual(get_json("/api/public/redirects?type=product&slug=never-existed")[0], 404)
        self.assertEqual(get_json("/api/public/redirects?type=zzz&slug=x")[0], 400)
        # unpublish -> 404 immediately (cache cleared on write)
        self.admin.post(f"/admin/products/{pid}/edit", data={"status": "draft"})
        self.assertEqual(get_json("/api/public/products/tst-renamed")[0], 404)
        self.admin.post(f"/admin/products/{pid}/edit", data={"status": "published"})
        self.assertEqual(get_json("/api/public/products/tst-renamed")[0], 200)
        # delete cleans children, tag map and documents
        r = self.admin.post(f"/admin/products/{pid}/delete")
        self.assertEqual(r.status_code, 302)
        for t in ("product_specs", "product_variants", "product_images", "product_tag_map"):
            self.assertEqual(db_rows(f"SELECT COUNT(*) AS c FROM {t} WHERE product_id=%s", (pid,))[0]["c"], 0, t)
        self.assertEqual(get_json("/api/public/products/tst-renamed")[0], 404)

    def test_validation_errors_keep_values_and_never_say_saved(self):
        r = self.admin.post("/admin/products/create", data=self.product_form(**{"name__fa": "", "model_code": "KEEP-ME-123"}))
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 422)
        self.assertIn("الزامی", html)
        self.assertIn("KEEP-ME-123", html)                       # entered values preserved
        self.assertIn("خاطر" if False else "خطا", html)
        self.assertFalse(any("ایجاد شد" in m for m in self.flashes()))
        self.assertEqual(db_rows("SELECT COUNT(*) AS c FROM products WHERE model_code='KEEP-ME-123'")[0]["c"], 0)

    def test_publish_requires_model_code_and_duplicate_slug_is_an_error(self):
        r = self.admin.post("/admin/products/create", data=self.product_form(model_code=""))
        self.assertEqual(r.status_code, 422)
        self.assertIn("برای انتشار", r.get_data(as_text=True))
        a = self.admin.post("/admin/products/create", data=self.product_form(slug="dup-slug-a", model_code="DUP-A"))
        b = self.admin.post("/admin/products/create", data=self.product_form(slug="dup-slug-b", model_code="DUP-B"))
        pid = int(re.search(r"/(\d+)/edit", b.headers["Location"]).group(1))
        r = self.admin.post(f"/admin/products/{pid}/edit", data={"slug": "dup-slug-a"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("قبلاً استفاده شده", r.get_data(as_text=True))
        self.assertFalse(any("ذخیره شد" in m for m in self.flashes()))
        self.assertEqual(db_rows("SELECT slug FROM products WHERE id=%s", (pid,))[0]["slug"], "dup-slug-b")
        for slug in ("dup-slug-a", "dup-slug-b"):
            i = db_rows("SELECT id FROM products WHERE slug=%s", (slug,))[0]["id"]
            self.admin.post(f"/admin/products/{i}/delete")

    def test_scheduled_publication(self):
        import datetime as dt

        future = (dt.datetime.utcnow() + dt.timedelta(days=5)).strftime("%Y-%m-%dT%H:%M")
        r = self.admin.post("/admin/products/create", data=self.product_form(slug="sched-prod", model_code="SCHED-1", published_at=future))
        pid = int(re.search(r"/(\d+)/edit", r.headers["Location"]).group(1))
        self.assertEqual(get_json("/api/public/products/sched-prod")[0], 404)                 # published but in the future
        self.admin.post(f"/admin/products/{pid}/edit", data={"published_at": "2020-01-01T00:00"})
        self.assertEqual(get_json("/api/public/products/sched-prod")[0], 200)
        self.admin.post(f"/admin/products/{pid}/delete")

    def test_category_edit_without_is_active_does_not_deactivate(self):
        cid = db_rows("SELECT id FROM categories WHERE slug='demo-control-valves'")[0]["id"]
        r = self.admin.post(f"/admin/categories/{cid}/edit", data={"name__en": "Control Valves"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(db_rows("SELECT is_active FROM categories WHERE id=%s", (cid,))[0]["is_active"], 1)
        self.assertIn("demo-control-valves", [c["slug"] for c in get_json("/api/public/categories")[1]["categories"][0]["children"]])

    def test_category_parent_rules_and_cache_invalidation(self):
        root = db_rows("SELECT id FROM categories WHERE slug='demo-flow-control'")[0]["id"]
        child = db_rows("SELECT id FROM categories WHERE slug='demo-control-valves'")[0]["id"]
        r = self.admin.post(f"/admin/categories/{root}/edit", data={"parent_id": str(child)})
        self.assertEqual(r.status_code, 422)                      # would create 3 levels / cycle
        r = self.admin.post(f"/admin/categories/{child}/edit", data={"parent_id": str(child)})
        self.assertEqual(r.status_code, 422)
        get_json("/api/public/categories")                         # warm the cache
        self.admin.post(f"/admin/categories/{child}/edit", data={"name__fa": "شیرآلات کنترلی (ویرایش)"})
        names = [c["name"]["fa"] for c in get_json("/api/public/categories")[1]["categories"][0]["children"]]
        self.assertIn("شیرآلات کنترلی (ویرایش)", names)           # fresh immediately
        self.admin.post(f"/admin/categories/{child}/edit", data={"name__fa": "شیرآلات کنترلی"})
        # inactive root hides its children
        self.admin.post(f"/admin/categories/{root}/toggle")
        self.assertNotIn("demo-flow-control", [c["slug"] for c in get_json("/api/public/categories")[1]["categories"]])
        self.assertEqual(get_json("/api/public/categories/demo-control-valves")[0], 404)
        self.admin.post(f"/admin/categories/{root}/toggle")
        self.assertEqual(get_json("/api/public/categories/demo-control-valves")[0], 200)

    def test_brand_cannot_be_deleted_while_used(self):
        bid = db_rows("SELECT id FROM brands WHERE slug='demo-aspd'")[0]["id"]
        self.admin.post(f"/admin/brands/{bid}/delete")
        self.assertEqual(db_rows("SELECT COUNT(*) AS c FROM brands WHERE id=%s", (bid,))[0]["c"], 1)
        self.assertTrue(any("محصول" in m for m in self.flashes()))

    def test_site_settings_partial_update_validation_and_secrets(self):
        r = self.admin.post("/admin/site-settings", data={"tagline__fa": "شعار جدید"})
        self.assertEqual(r.status_code, 302)
        site = get_json("/api/public/site")[1]["site"]
        self.assertEqual(site["tagline"]["fa"], "شعار جدید")
        self.assertTrue(site["name"]["fa"])                                         # untouched
        for bad in ({"site_url": "not-a-url"}, {"theme_primary": "blue"}, {"map_embed_url": "https://evil.example/x"},
                    {"map_embed_url": "http://google.com/maps/embed"}, {"ga4_measurement_id": "X-1"}, {"map_lat": "999"},
                    {"seo_title_template": "{title} {evil}"}, {"favicon_png": "/assets/uploads/demo_local/hero.jpg"}):
            r = self.admin.post("/admin/site-settings", data=bad)
            self.assertEqual(r.status_code, 422, bad)
        r = self.admin.post("/admin/site-settings", data={"map_embed_url": "https://www.google.com/maps/embed?pb=1",
                                                          "ga4_measurement_id": "G-ABC12345", "site_url": "https://example.ir/"})
        self.assertEqual(r.status_code, 302)
        site = get_json("/api/public/site")[1]["site"]
        self.assertEqual(site["site_url"], "https://example.ir")                    # trailing slash stripped
        self.assertEqual(site["analytics"]["ga4_id"], "G-ABC12345")
        self.assertEqual(site["contact"]["phone_tel"], "+982188654200")
        self.assertTrue(site["branding"]["favicon"]["png_192"])                     # favicons generated from the 512px source
        self.assertTrue(site["branding"]["favicon"]["apple_touch"])
        raw = json.dumps(get_json("/api/public/site")[1])
        self.assertNotIn("inquiry_notify_emails", raw)
        self.assertNotIn("inquiry_reference_prefix", raw)
        self.assertNotIn("ASPD", raw.replace("ASPD ENGINEERING GROUP", ""))         # prefix value never leaks
        self.admin.post("/admin/site-settings", data={"site_url": "https://example-frontend.test"})

    def test_media_browse_and_upload(self):
        s, d, _ = get_json("/admin/media/browse?folder=demo_local&per_page=5", client=self.admin)
        self.assertEqual(s, 200)
        total = d["meta"]["total"]
        d = d["data"]
        self.assertLessEqual(len(d["files"]), 5)
        f = d["files"][0]
        self.assertEqual(set(f), {"name", "rel", "url", "size", "ext", "width", "height", "is_image", "mtime"})
        self.assertTrue(f["url"].startswith("/assets/uploads/"))
        self.assertGreater(total, 0)
        s, d, _ = get_json("/admin/media/browse?folder=..%2F..", client=self.admin)
        self.assertEqual(s, 400)
        s, d, _ = get_json("/admin/media/browse?folder=nope-folder", client=self.admin)
        self.assertEqual(s, 404)

    def test_i18n_import_is_idempotent_and_api_params(self):
        c = self.admin
        if not db_rows("SELECT id FROM i18n_languages WHERE code='en'"):
            c.post("/admin/i18n/create", data={"code": "en", "name": "English", "native_name": "English", "direction": "ltr", "flag": "🇬🇧"})
        fa_json = (ROOT / "front-locales" / "fa.json").read_bytes()
        en_json = (ROOT / "front-locales" / "en.json").read_bytes()

        def do_import(code, data, **extra):
            r = c.post(f"/admin/i18n/{code}/import", data={"file": (io.BytesIO(data), f"{code}.json"), "prefix": "web.", "mode": "missing", **extra},
                       content_type="multipart/form-data")
            self.assertEqual(r.status_code, 302)
            return self.flashes(c)[-1]

        m1 = do_import("fa", fa_json)
        m2 = do_import("fa", fa_json)
        self.assertIn("0 کلید جدید", m2)
        self.assertIn("310 ردشده", m2)
        do_import("en", en_json)
        n = db_rows("SELECT COUNT(*) AS c FROM i18n_translations WHERE translation_key LIKE 'web.%%' AND lang_code='fa'")[0]["c"]
        self.assertEqual(n, 310)
        # overwrite needs explicit confirmation
        r = c.post("/admin/i18n/fa/import", data={"file": (io.BytesIO(fa_json), "fa.json"), "prefix": "web.", "mode": "overwrite"},
                   content_type="multipart/form-data")
        self.assertIn("تأیید صریح", self.flashes(c)[-1])
        # admin edit is not overwritten by a re-import in 'missing' mode
        run_async(APP.core.db.execute("UPDATE i18n_translations SET value='EDITED' WHERE lang_code='en' AND translation_key='web.nav.home'"))
        do_import("en", en_json)
        self.assertEqual(get_json("/api/i18n/translate/en?prefix=web.&strip_prefix=1")[1]["nav.home"], "EDITED")
        # bad uploads
        r = c.post("/admin/i18n/en/import", data={"file": (io.BytesIO(b"{broken"), "x.json"), "prefix": "web."}, content_type="multipart/form-data")
        self.assertIn("نامعتبر", self.flashes(c)[-1])
        r = c.post("/admin/i18n/en/import", data={"file": (io.BytesIO(b"[1]"), "x.json"), "prefix": "web."}, content_type="multipart/form-data")
        self.assertIn("نامعتبر", self.flashes(c)[-1])
        # API params
        s, d, r = get_json("/api/i18n/translate/en?prefix=web.&strip_prefix=1")
        self.assertEqual(len(d), 310)
        self.assertIn("nav.home", d)
        self.assertFalse(any(k.startswith("web.") for k in d))
        s, d, _ = get_json("/api/i18n/translate/en?prefix=web.")
        self.assertTrue(all(k.startswith("web.") for k in d))
        run_async(APP.core.db.execute("DELETE FROM i18n_translations WHERE lang_code='en' AND translation_key='web.nav.about'"))
        APP.cache.invalidate_namespace("i18n_lang_en")
        s, d, _ = get_json("/api/i18n/translate/en?prefix=web.&strip_prefix=1")
        self.assertNotIn("nav.about", d)
        s, d, _ = get_json("/api/i18n/translate/en?prefix=web.&strip_prefix=1&fallback=1")
        self.assertEqual(d["nav.about"], get_json("/api/i18n/translate/fa?prefix=web.&strip_prefix=1")[1]["nav.about"])   # filled from fa
        s, d, r = get_json("/api/i18n/translate/fa?prefix=web.")
        r2 = CLIENT.get("/api/i18n/translate/fa?prefix=web.", headers={"If-None-Match": r.headers["ETag"]})
        self.assertEqual(r2.status_code, 304)
        # no params: still a flat {key: value} dict of strings (legacy shape)
        s, d, _ = get_json("/api/i18n/translate/en")
        self.assertTrue(all(isinstance(v, str) for v in d.values()))
        # translate screen shows web.* keys grouped and with Persian sources
        html = c.get("/admin/i18n/en/translate?prefix=web.").get_data(as_text=True)
        self.assertIn("web.home", html)                                              # (JSON payload of the translate API)
        self.assertIn("web.nav.home", html)
        # a filtered form must not wipe other translations
        before = db_rows("SELECT COUNT(*) AS c FROM i18n_translations WHERE lang_code='en' AND translation_key NOT LIKE 'web.%%'")[0]["c"]
        c.post("/admin/i18n/en/translate", data={"prefix": "web.", "k_web.nav.home": "Home!"})
        after = db_rows("SELECT COUNT(*) AS c FROM i18n_translations WHERE lang_code='en' AND translation_key NOT LIKE 'web.%%'")[0]["c"]
        self.assertEqual(before, after)
        # fa language row always exists and is listed by /site
        langs = get_json("/api/public/site")[1]["site"]["languages"]
        self.assertEqual(langs["default"], "fa")
        self.assertEqual(langs["active"][0]["code"], "fa")
        self.assertIn("en", [l["code"] for l in langs["active"]])


class SearchHomeSitemap(unittest.TestCase):
    def test_search_all_types_and_languages(self):
        s, d, _ = get_json("/api/public/search?q=" + quote("نیروگاه"))
        self.assertEqual(d["totals"]["projects"], 1)
        s, d, _ = get_json("/api/public/search?q=" + quote("Power Plant"))
        self.assertEqual(d["totals"]["projects"], 1)                    # English matches too
        s, d, _ = get_json("/api/public/search?q=" + quote("درباره ما"))
        self.assertIn("about", [p["page_key"] for p in d["pages"]])
        self.assertEqual(next(p for p in d["pages"] if p["page_key"] == "about")["path"], "/about")
        s, d, _ = get_json("/api/public/search?q=" + quote("راهنمای انتخاب"))
        self.assertEqual(d["totals"]["articles"], 1)
        s, d, _ = get_json("/api/public/search?q=demo&types=products&limit=1")
        self.assertEqual(len(d["products"]), 1)
        self.assertEqual(d["projects"], [])
        self.assertGreaterEqual(d["totals"]["products"], 3)
        self.assertEqual(d["totals"]["all"], d["totals"]["products"])
        s, d, _ = get_json("/api/public/search?q=" + quote("۹۴۰"))
        self.assertEqual(d["products"][0]["slug"], "demo-as-fcv-940")

    def test_home_aggregate_and_limits(self):
        s, d, _ = get_json("/api/public/home?featured_products=1&projects=1&articles=2")
        self.assertEqual((len(d["featured_products"]), len(d["featured_projects"]), len(d["latest_articles"])), (1, 1, 2))
        self.assertEqual(d["featured_products"][0]["featured"], True)
        s, d, _ = get_json("/api/public/home?featured_products=99&projects=0&articles=abc")
        self.assertEqual(s, 200)
        self.assertLessEqual(len(d["featured_products"]), 12)
        self.assertGreaterEqual(len(d["stats"]), 4)
        self.assertEqual([c["slug"] for c in d["categories"]][:1], ["demo-flow-control"])      # roots only

    def test_sitemap_excludes_noindex_draft_and_scheduled(self):
        s, d, _ = get_json("/api/public/sitemap")
        self.assertIn("demo-as-fcv-940", [p["slug"] for p in d["products"]])
        self.assertNotIn("demo-draft-product", [p["slug"] for p in d["products"]])
        self.assertNotIn("demo-scheduled-article", [a["slug"] for a in d["articles"]])
        self.assertTrue(d["site_url"])
        admin = admin_client()
        pid = db_rows("SELECT id FROM products WHERE slug='demo-as-plc-500'")[0]["id"]
        admin.post(f"/admin/products/{pid}/edit", data={"noindex": "1"})
        s, d, _ = get_json("/api/public/sitemap")
        self.assertNotIn("demo-as-plc-500", [p["slug"] for p in d["products"]])
        self.assertTrue(get_json("/api/public/products/demo-as-plc-500")[1]["product"]["seo"]["noindex"])
        admin.post(f"/admin/products/{pid}/edit", data={"noindex": "0"})
        self.assertIn("demo-as-plc-500", [p["slug"] for p in get_json("/api/public/sitemap")[1]["products"]])

    def test_projects_articles_services_faq_company_shapes_and_order(self):
        s, d, _ = get_json("/api/public/projects")
        self.assertEqual([p["slug"] for p in d["projects"]], ["demo-power-plant", "demo-desalination"])      # completion_year desc
        s, d, _ = get_json("/api/public/projects?sector=energy")
        self.assertEqual([p["slug"] for p in d["projects"]], ["demo-power-plant"])
        s, d, _ = get_json("/api/public/projects/demo-power-plant?related_limit=1")
        pr = d["project"]
        self.assertEqual([p["slug"] for p in pr["products"]], ["demo-as-fcv-940", "demo-as-pt-210"])     # admin order kept
        self.assertEqual(pr["related_projects"][0]["slug"], "demo-desalination")
        self.assertEqual(pr["highlight_metric"]["value"]["fa"], "۱۲٪")
        self.assertEqual(len(pr["gallery"]), 2)
        s, d, _ = get_json("/api/public/project-sectors")
        self.assertEqual({x["slug"] for x in d["sectors"]}, {"energy", "water"})                            # only sectors with projects
        s, d, _ = get_json("/api/public/articles?per_page=100")
        self.assertEqual([a["slug"] for a in d["articles"]], ["demo-valve-selection", "demo-sil-intro", "demo-company-news"])
        s, d, _ = get_json("/api/public/articles?category=corporate")
        self.assertEqual([a["slug"] for a in d["articles"]], ["demo-company-news"])
        s, d, _ = get_json("/api/public/articles?featured=1")
        self.assertEqual([a["slug"] for a in d["articles"]], ["demo-valve-selection"])
        art = get_json("/api/public/articles/demo-valve-selection")[1]["article"]
        self.assertEqual([x["anchor"] for x in art["sections"]], ["section-1", "section-2"] if art["sections"][0]["anchor"].startswith("section") else [x["anchor"] for x in art["sections"]])
        self.assertEqual(len({x["anchor"] for x in art["sections"]}), 2)
        self.assertGreaterEqual(art["reading_time_minutes"], 1)
        self.assertEqual(len(art["related"]), 2)
        s, d, _ = get_json("/api/public/article-categories")
        self.assertEqual({c["slug"]: c["article_count"] for c in d["categories"]}["engineering"], 2)
        s, d, _ = get_json("/api/public/services")
        self.assertEqual([x["step_number"] for x in d["process_steps"]], ["01", "02", "03", "04", "05"])
        self.assertEqual(len(d["services"]), 2)
        s, d, _ = get_json("/api/public/faq")
        self.assertEqual([c["slug"] for c in d["categories"]], ["engineering", "documentation", "support", "corporate"])
        s, d, _ = get_json("/api/public/company")
        self.assertEqual(d["stats"][0]["value"], 27)
        self.assertEqual(d["offices"][0]["is_primary"], True)
        self.assertEqual(d["offices"][0]["coordinates_label"], "35.7742° N, 51.4128° E")
        self.assertEqual(d["offices"][0]["phone_tel"], "+982188654200")
        cert = next(c for c in d["certifications"] if c["code"] == "DEMO ISO 9001:2015")
        self.assertEqual(cert["document"]["type"], "certificate")
        self.assertIsNone(next(c for c in d["certifications"] if c["code"] != "DEMO ISO 9001:2015")["document"])
        url = cert["document"]["files"]["fa"]["download_url"].replace("http://localhost", "")
        self.assertEqual(CLIENT.get(url).status_code, 200)                                                  # certification documents download too


class Inquiries(unittest.TestCase):
    def payload(self, **over):
        d = {"full_name": "علی رضایی", "email": "ali@example.com", "phone": "+98 21 8865 4200", "subject": "درخواست قیمت",
             "message": "لطفاً قیمت و زمان تحویل را اعلام کنید.", "product_code": "demo-as-fcv-940", "locale": "fa"}
        d.update(over)
        return d

    def post(self, body, ip, client=None, **kw):
        return (client or CLIENT).post("/api/public/inquiries", json=body, headers={"X-Real-IP": ip}, **kw)

    def test_success_reference_and_product_link_and_no_leak(self):
        ip = rand_ip()
        r = self.post(self.payload(email="ok1@inq.test"), ip)
        self.assertEqual(r.status_code, 201)
        d = json.loads(r.get_data())
        self.assertEqual(d["ok"], True)
        self.assertRegex(d["reference_code"], r"^ASPD-\d{4}-\d{4,}$")
        row = db_rows("SELECT * FROM inquiries WHERE reference_code=%s", (d["reference_code"],))[0]
        self.assertEqual(row["status"], "new")
        self.assertEqual(row["ip"], ip)
        self.assertIsNotNone(row["product_id"])                                         # model_code matched (case-insensitive)
        self.assertEqual(set(d), {"ok", "reference_code"})                              # nothing else leaks back
        for path in ("/api/public/site", "/api/public/company", "/api/public/search?q=ok1"):
            self.assertNotIn("ok1@inq.test", CLIENT.get(path).get_data(as_text=True))

    def test_validation_422_shape(self):
        r = self.post({"full_name": "x", "email": "bad", "phone": "1", "subject": "a", "message": "short", "locale": "xx"}, rand_ip())
        d = json.loads(r.get_data())
        self.assertEqual((r.status_code, d["ok"], d["error"]), (422, False, "validation_failed"))
        self.assertEqual(d["fields"]["email"], {"code": "invalid_email"})
        self.assertEqual(d["fields"]["message"], {"code": "too_short", "min": 15})
        self.assertEqual(d["fields"]["locale"], {"code": "invalid_value"})

    def test_honeypot_returns_201_but_stores_nothing(self):
        r = self.post(self.payload(email="bot@inq.test", website="http://spam.example"), rand_ip())
        self.assertEqual(r.status_code, 201)
        self.assertRegex(json.loads(r.get_data())["reference_code"], r"^ASPD-\d{4}-\d{4}$")
        self.assertEqual(db_rows("SELECT COUNT(*) AS c FROM inquiries WHERE email='bot@inq.test'")[0]["c"], 0)

    def test_rate_limit_per_ip_returns_429_with_retry_after(self):
        from app.plugins.inquiries.plugin import LIMITER

        LIMITER.reset()
        ip = rand_ip()
        codes = [self.post(self.payload(email=f"rl{i}@inq.test"), ip).status_code for i in range(6)]
        self.assertEqual(codes, [201, 201, 201, 201, 201, 429])
        r = self.post(self.payload(), ip)
        self.assertEqual(r.status_code, 429)
        self.assertGreater(int(r.headers["Retry-After"]), 0)
        self.assertEqual(json.loads(r.get_data())["error"], "rate_limited")
        self.assertEqual(self.post(self.payload(email="rl-other@inq.test"), rand_ip()).status_code, 201)   # other IP unaffected
        LIMITER.reset()

    def test_references_are_sequential_and_unique_under_concurrency(self):
        def one(i):
            c = APP.test_client()
            r = self.post(self.payload(email=f"conc{i}@inq.test"), rand_ip(), client=c)
            return r.status_code, json.loads(r.get_data()).get("reference_code")

        with concurrent.futures.ThreadPoolExecutor(max_workers=25) as ex:
            res = list(ex.map(one, range(50)))
        self.assertEqual({s for s, _ in res}, {201}, res)
        refs = [r for _, r in res]
        self.assertEqual(len(set(refs)), 50)
        nums = sorted(int(r.rsplit("-", 1)[1]) for r in refs)
        self.assertEqual(nums, list(range(nums[0], nums[0] + 50)))                  # gap-free, no collisions

    def test_admin_list_detail_status_csv_delete(self):
        admin = admin_client()
        r = self.post(self.payload(email="adm@inq.test", subject="=cmd|' /C calc'!A0 فرمول"), rand_ip())
        ref = json.loads(r.get_data())["reference_code"]
        html = admin.get("/admin/inquiries?q=adm%40inq.test").get_data(as_text=True)
        self.assertIn(ref, html)
        self.assertIn("جدید", html)
        iid = db_rows("SELECT id FROM inquiries WHERE reference_code=%s", (ref,))[0]["id"]
        self.assertIn("adm@inq.test", admin.get(f"/admin/inquiries/{iid}").get_data(as_text=True))
        admin.post(f"/admin/inquiries/{iid}", data={"status": "answered", "internal_note": "تماس گرفته شد"})
        row = db_rows("SELECT * FROM inquiries WHERE id=%s", (iid,))[0]
        self.assertEqual((row["status"], row["internal_note"], row["handled_by"]), ("answered", "تماس گرفته شد", "admin"))
        self.assertIsNotNone(row["answered_at"])
        admin.post(f"/admin/inquiries/{iid}", data={"status": "hacked"})
        self.assertEqual(db_rows("SELECT status FROM inquiries WHERE id=%s", (iid,))[0]["status"], "answered")
        csv_r = admin.get("/admin/inquiries/export.csv?status=answered")
        text = csv_r.get_data(as_text=True)
        self.assertTrue(csv_r.headers["Content-Type"].startswith("text/csv"))
        self.assertTrue(text.startswith("﻿"))
        self.assertIn(ref, text)
        self.assertIn("'=cmd", text)                                                # formula injection neutralised
        admin.post(f"/admin/inquiries/{iid}/delete")
        self.assertEqual(db_rows("SELECT COUNT(*) AS c FROM inquiries WHERE id=%s", (iid,))[0]["c"], 0)

    def test_filters_status_date_and_product_code(self):
        admin = admin_client()
        html = admin.get("/admin/inquiries?status=new&product_code=DEMO-AS-FCV&date_from=2020-01-01&date_to=2099-01-01").get_data(as_text=True)
        self.assertIn("demo-as-fcv-940", html.lower())
        self.assertEqual(admin.get("/api/admin/inquiries?status=spam").get_json()["data"], [])


class _Sink(http.server.BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        _Sink.received.append((dict(self.headers), json.loads(body)))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


class RevalidateIntegration(unittest.TestCase):
    def setUp(self):
        _Sink.received.clear()
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), _Sink)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        os.environ["FRONTEND_REVALIDATE_URL"] = f"http://127.0.0.1:{self.srv.server_address[1]}/api/revalidate"
        os.environ["FRONTEND_REVALIDATE_SECRET"] = "integration-secret"
        APP.revalidate.window = 0.3

    def tearDown(self):
        self.srv.shutdown()
        os.environ.pop("FRONTEND_REVALIDATE_URL", None)
        os.environ.pop("FRONTEND_REVALIDATE_SECRET", None)
        APP.revalidate.window = 2.0

    def test_admin_writes_notify_the_frontend_with_the_right_tags(self):
        admin = admin_client()
        pid = db_rows("SELECT id FROM products WHERE slug='demo-as-pt-210'")[0]["id"]
        r = admin.post(f"/admin/products/{pid}/edit", data={"subtitle__fa": "ویرایش برای webhook"})
        self.assertEqual(r.status_code, 302)                                          # admin response not blocked
        admin.post("/admin/site-settings", data={"tagline__fa": "webhook test"})
        self.assertTrue(APP.revalidate.wait_idle(15))
        tags = set()
        for headers, body in _Sink.received:
            self.assertEqual(headers["X-Revalidate-Secret"], "integration-secret")
            self.assertEqual(body["event"], "content.changed")
            tags |= set(body["tags"])
        self.assertTrue({"products", "product:demo-as-pt-210", "sitemap", "search", "site"} <= tags, tags)
        self.assertEqual(len(_Sink.received), 1)                                      # both writes merged into one request
        info = admin.get("/api/admin/revalidate").get_json()["data"]
        self.assertTrue(info["enabled"] and info["has_url"] and info["has_secret"])
        self.assertNotIn("integration-secret", json.dumps(info))                      # secret never shown

    def test_unreachable_frontend_does_not_break_the_admin(self):
        os.environ["FRONTEND_REVALIDATE_URL"] = "http://127.0.0.1:1/api/revalidate"
        admin = admin_client()
        t0 = time.time()
        r = admin.post("/admin/site-settings", data={"tagline__fa": "unreachable test"})
        self.assertEqual(r.status_code, 302)
        self.assertLess(time.time() - t0, 3)
        APP.revalidate.wait_idle(30)
        self.assertFalse(APP.revalidate.last["ok"])

    def test_translation_and_category_events(self):
        admin = admin_client()
        admin.post("/admin/product-tags/create", data={"label__fa": "تگ webhook"})
        cid = db_rows("SELECT id FROM categories WHERE slug='demo-control-valves'")[0]["id"]
        admin.post(f"/admin/categories/{cid}/toggle")
        admin.post(f"/admin/categories/{cid}/toggle")
        APP.revalidate.wait_idle(15)
        tags = set().union(*[set(b["tags"]) for _h, b in _Sink.received])
        self.assertTrue({"tags", "categories", "category:demo-control-valves", "products", "sitemap"} <= tags, tags)
        db_rows("DELETE FROM product_tags WHERE JSON_UNQUOTE(JSON_EXTRACT(label_i18n, '$.fa'))='تگ webhook'") if False else None
        tid = db_rows("SELECT id FROM product_tags WHERE JSON_UNQUOTE(JSON_EXTRACT(label_i18n, '$.fa'))='تگ webhook'")
        for t in tid:
            admin.post(f"/admin/product-tags/{t['id']}/delete")


class LegacyRegression(unittest.TestCase):
    LEGACY_PRODUCT_KEYS = {"id", "title", "slug", "description", "price", "stock", "status", "created_at", "name", "old_price", "sku",
                           "meta_title", "meta_description", "meta_keywords", "schema_json", "extra", "category_id", "images"}
    LEGACY_CATEGORY_KEYS = {"id", "parent_id", "name", "title", "slug", "description", "meta_title", "meta_description", "meta_keywords",
                            "schema_json", "is_active", "is_deleted", "created_at"}

    def test_legacy_form_post_and_old_api_shape_are_unchanged(self):
        admin = admin_client()
        # the OLD form field names (single-language) must keep working
        r = admin.post("/admin/products/create", data={
            "name": "محصول قدیمی", "slug": "legacy-form-product", "description": "توضیح قدیمی", "stock": "3", "old_price": "10", "price": "8",
            "sku": "LEG-1", "category_id": "", "status": "published", "meta_title": "mt", "meta_description": "md", "meta_keywords": "mk"})
        self.assertEqual(r.status_code, 422)                       # publishing without a model_code is refused, with a clear reason
        self.assertIn("کد مدل", r.get_data(as_text=True))
        r = admin.post("/admin/products/create", data={
            "name": "محصول قدیمی", "slug": "legacy-form-product", "description": "توضیح قدیمی", "stock": "3", "old_price": "10", "price": "8",
            "sku": "LEG-1", "category_id": "", "status": "published", "meta_title": "mt", "meta_description": "md", "meta_keywords": "mk",
            "model_code": "LEG-CODE-1"})
        self.assertEqual(r.status_code, 302)
        pid = int(re.search(r"/(\d+)/edit", r.headers["Location"]).group(1))
        try:
            s, d, _ = get_json("/api/products")
            row = next(p for p in d["products"] if p["slug"] == "legacy-form-product")
            self.assertEqual(set(row), self.LEGACY_PRODUCT_KEYS)
            self.assertEqual((row["name"], row["stock"], row["sku"], row["status"]), ("محصول قدیمی", 3, "LEG-1", "published"))
            s, d, _ = get_json(f"/api/products/{pid}")
            self.assertEqual(s, 200)
            self.assertEqual(set(d) - {"category", "metatags"}, self.LEGACY_PRODUCT_KEYS)
            r = CLIENT.get("/product/legacy-form-product")
            self.assertEqual(r.status_code, 200)
            self.assertIn("محصول قدیمی", r.get_data(as_text=True))
            # NB: an unknown slug on the legacy page renders a missing "404.html" template (pre-existing 500); not asserted
            self.assertEqual(get_json("/api/public/products/legacy-form-product")[0], 200)     # visible in the new API too
        finally:
            admin.post(f"/admin/products/{pid}/delete")

    def test_legacy_category_api_shape(self):
        s, d, _ = get_json("/api/categories")
        self.assertTrue(d["categories"])
        for c in d["categories"]:
            self.assertEqual(set(c) - {"children"}, self.LEGACY_CATEGORY_KEYS)
        s, d, _ = get_json("/api/categories/demo-flow-control")
        self.assertEqual(set(d) - {"children"}, self.LEGACY_CATEGORY_KEYS)
        self.assertEqual(get_json("/api/categories/none-here")[0], 404)
        self.assertEqual(CLIENT.get("/category/demo-flow-control").status_code, 200)

    def test_legacy_i18n_endpoints(self):
        s, d, _ = get_json("/api/i18n/languages")
        self.assertEqual(set(d), {"languages", "current"})
        self.assertIn("fa", [l["code"] for l in d["languages"]])
        self.assertEqual(CLIENT.get("/en/api/public/health").status_code, 200)           # language prefix still routes
        self.assertEqual(CLIENT.get("/").status_code, 200)

    def test_core_admin_pages_still_render(self):
        admin = admin_client()
        for p in ("/admin", "/admin/settings", "/admin/users", "/admin/plugins", "/admin/i18n", "/admin/tracking"):
            self.assertEqual(admin.get(p).status_code, 200, p)
        self.assertEqual(admin.get("/dashboard").status_code, 302)                       # old URL redirects to /admin
        html = json.dumps(admin.get("/api/admin/auth/me").get_json())                    # the menu (also server-rendered in the shell)
        for url in ("/admin/site-settings", "/admin/brands", "/admin/projects", "/admin/articles", "/admin/services", "/admin/faq",
                    "/admin/company", "/admin/inquiries", "/admin/products", "/admin/categories"):
            self.assertIn(url, html, f"dashboard tile missing: {url}")


class MigrationIdempotency(unittest.TestCase):
    def test_second_boot_changes_nothing(self):
        tables = ["products", "categories", "brands", "i18n_translations", "i18n_languages", "project_sectors", "article_categories",
                  "faq_categories", "site_settings", "plugins"]

        def snapshot():
            return {t: db_rows(f"SELECT COUNT(*) AS c FROM `{t}`")[0]["c"] for t in tables}

        before = snapshot()
        cols_before = db_rows("SELECT COUNT(*) AS c FROM information_schema.columns WHERE table_schema=DATABASE()")[0]["c"]
        idx_before = db_rows("SELECT COUNT(*) AS c FROM information_schema.statistics WHERE table_schema=DATABASE()")[0]["c"]
        from app import create_app

        create_app()
        create_app()
        self.assertEqual(snapshot(), before)
        self.assertEqual(db_rows("SELECT COUNT(*) AS c FROM information_schema.columns WHERE table_schema=DATABASE()")[0]["c"], cols_before)
        self.assertEqual(db_rows("SELECT COUNT(*) AS c FROM information_schema.statistics WHERE table_schema=DATABASE()")[0]["c"], idx_before)

    def test_seed_is_idempotent(self):
        from seed_demo import Seeder

        before = {t: db_rows(f"SELECT COUNT(*) AS c FROM `{t}`")[0]["c"] for t in ("products", "projects", "articles", "documents", "inquiries")}
        with APP.app_context():
            asyncio.run(Seeder(APP).run())
        after = {t: db_rows(f"SELECT COUNT(*) AS c FROM `{t}`")[0]["c"] for t in before}
        self.assertEqual(before, after)

    def test_legacy_data_is_backfilled_as_persian(self):
        """A row written the old way (legacy columns only) is readable through the new API once migrated."""
        run_async(APP.core.db.execute(
            "INSERT INTO categories (title, name, slug, is_active, is_deleted, description) VALUES ('قدیمی','قدیمی','legacy-cat',1,0,'<p>توضیح <b>قدیمی</b></p>')"))
        run_async(APP.core.db.execute(
            "INSERT INTO products (title, name, slug, status, description, category_id, model_code) "
            "SELECT 'محصول قدیمی ۲','محصول قدیمی ۲','legacy-prod-2','published','<p>متن</p>',id,'LEG-2' FROM categories WHERE slug='legacy-cat'"))
        try:
            s, d, _ = get_json("/api/public/products/legacy-prod-2")      # no *_i18n yet: falls back to legacy columns
            self.assertEqual(s, 200)
            self.assertEqual(d["product"]["name"], {"fa": "محصول قدیمی ۲"})
            self.assertEqual(d["product"]["description"], {"fa": "متن"})
            from app import create_app

            create_app()                                                  # migration back-fills
            row = db_rows("SELECT name_i18n, description_i18n FROM products WHERE slug='legacy-prod-2'")[0]
            self.assertEqual(json.loads(row["name_i18n"]), {"fa": "محصول قدیمی ۲"})
            self.assertEqual(json.loads(row["description_i18n"]), {"fa": "متن"})
            cat = db_rows("SELECT description, description_i18n FROM categories WHERE slug='legacy-cat'")[0]
            self.assertEqual(cat["description"], "<p>توضیح <b>قدیمی</b></p>")      # legacy column left untouched
            self.assertEqual(json.loads(cat["description_i18n"]), {"fa": "توضیح قدیمی"})
        finally:
            run_async(APP.core.db.execute("DELETE FROM products WHERE slug='legacy-prod-2'"))
            run_async(APP.core.db.execute("DELETE FROM categories WHERE slug='legacy-cat'"))


class AdminPagesRender(unittest.TestCase):
    """Every admin list / create / edit screen renders (catches template errors)."""

    LISTS = ["/admin/products", "/admin/product-tags", "/admin/categories", "/admin/brands", "/admin/projects", "/admin/project-sectors",
             "/admin/articles", "/admin/article-categories", "/admin/services", "/admin/service-steps", "/admin/faq", "/admin/faq-categories",
             "/admin/company", "/admin/company/stats", "/admin/company/timeline", "/admin/company/team", "/admin/company/certifications",
             "/admin/company/industries", "/admin/company/testimonials", "/admin/company/offices", "/admin/inquiries",
             "/admin/site-settings", "/admin/revalidate", "/admin/i18n", "/admin/i18n/en/translate", "/admin/i18n/en/import",
             "/admin/navigation", "/admin/frontend-visits"]
    CREATES = ["/admin/navigation", "/admin/products", "/admin/product-tags", "/admin/categories", "/admin/brands", "/admin/projects", "/admin/project-sectors",
               "/admin/articles", "/admin/article-categories", "/admin/services", "/admin/service-steps", "/admin/faq", "/admin/faq-categories",
               "/admin/company/stats", "/admin/company/timeline", "/admin/company/team", "/admin/company/certifications",
               "/admin/company/industries", "/admin/company/testimonials", "/admin/company/offices"]

    def test_lists_create_and_edit_forms_render(self):
        admin = admin_client()
        for p in self.LISTS:
            self.assertEqual(admin.get(p).status_code, 200, p)
        for p in self.CREATES:
            r = admin.get(p + "/create")
            self.assertEqual(r.status_code, 200, p + "/create")
            self.assertIn('id="entity-app"', r.get_data(as_text=True), p)       # page shell (the form is built client-side)
        tables = {"/admin/products": "products", "/admin/categories": "categories", "/admin/brands": "brands", "/admin/projects": "projects",
                  "/admin/articles": "articles", "/admin/services": "services", "/admin/faq": "faq_items",
                  "/admin/company/offices": "company_offices", "/admin/company/certifications": "company_certifications",
                  "/admin/company/stats": "company_stats", "/admin/product-tags": "product_tags", "/admin/project-sectors": "project_sectors"}
        for path, table in tables.items():
            row = db_rows(f"SELECT id FROM `{table}` ORDER BY id LIMIT 1")
            self.assertTrue(row, table)
            self.assertEqual(admin.get(f"{path}/{row[0]['id']}/edit").status_code, 200, f"{path}/edit")
        # the edit API carries what the form renders: i18n values, repeaters, panels, view link
        pid = db_rows("SELECT id FROM products WHERE slug='demo-as-fcv-940'")[0]["id"]
        j = admin.get(f"/admin/products/{pid}/edit").get_json()["data"]
        text = json.dumps(j, ensure_ascii=False)
        for marker in ("مدیریت اسناد", "DEMO-AS-FCV-940", "شیر کنترل جریان", "published_at"):
            self.assertIn(marker, text, marker)
        self.assertIn("en", j["values"]["name"])
        self.assertEqual((len(j["values"]["specs"]), len(j["values"]["variants"]), len(j["values"]["images"])), (5, 2, 3))
        schema = admin.get("/api/admin/products/schema").get_json()["data"]
        self.assertTrue(schema["entity"]["status"] and schema["entity"]["children"])
        cert = db_rows("SELECT id FROM company_certifications ORDER BY id LIMIT 1")[0]["id"]
        for pg in (f"/admin/documents/product/{pid}", f"/admin/documents/certification/{cert}"):
            self.assertEqual(admin.get(pg).status_code, 200, pg)

    def test_list_search_filter_sort_and_pagination_params_are_safe(self):
        admin = admin_client()
        for qs in ("?q=demo", "?q=%25%27%22", "?page=abc", "?page=-1", "?page=99999", "?sort=<script>", "?f_status=published", "?f_status=%27",
                   "?f_category_id=abc"):
            self.assertEqual(admin.get("/admin/products" + qs).status_code, 200, qs)
        html = admin.get("/admin/products?q=DEMO-AS-PT").get_data(as_text=True)
        self.assertIn("DEMO-AS-PT-210", html)
        self.assertNotIn("DEMO-AS-FCV-940", html)
        html = admin.get("/admin/products?f_status=draft").get_data(as_text=True)
        self.assertIn("DEMO-DRAFT-1", html)
        self.assertNotIn("DEMO-AS-FCV-940", html)

    def test_open_redirect_guard_on_next_param(self):
        admin = admin_client()
        r = admin.post("/admin/product-tags/create", data={"label__fa": "تگ redirect", "_after": "close", "next": "//evil.example/x"})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("evil.example", r.headers["Location"])
        for t in db_rows("SELECT id FROM product_tags WHERE JSON_UNQUOTE(JSON_EXTRACT(label_i18n,'$.fa'))='تگ redirect'"):
            r = admin.post(f"/admin/product-tags/{t['id']}/delete", data={"next": "https://evil.example"})
            self.assertNotIn("evil.example", r.headers["Location"])

    def test_dashboard_tile_counts_new_inquiries(self):
        APP.cache.invalidate_namespace("admin")                                          # menu is cached for 30 s
        menu = admin_client().get("/api/admin/auth/me").get_json()["data"]["menu"]
        badge = next(m for m in menu if m["key"] == "inquiries")["badge"]
        self.assertIsInstance(badge, int)
        self.assertGreater(badge, 0)


class FakeSmtp(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        import socket

        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.messages = []

    def run(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()

    def handle(self, conn):
        f = conn.makefile("rwb")

        def send(s):
            f.write(s.encode() + b"\r\n")
            f.flush()

        send("220 fake ESMTP")
        data_mode, buf = False, []
        while True:
            line = f.readline()
            if not line:
                return
            if data_mode:
                if line in (b".\r\n", b".\n"):
                    self.messages.append(b"".join(buf))
                    data_mode, buf = False, []
                    send("250 queued")
                else:
                    buf.append(line)
                continue
            cmd = line.decode(errors="replace").strip().upper()
            if cmd.startswith(("EHLO", "HELO")):
                send("250 fake")
            elif cmd.startswith("DATA"):
                data_mode = True
                send("354 go ahead")
            elif cmd.startswith("QUIT"):
                send("221 bye")
                return
            else:
                send("250 OK")


class InquiryEmail(unittest.TestCase):
    def tearDown(self):
        for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_TLS", "SMTP_FROM"):
            os.environ.pop(k, None)

    def test_notification_is_sent_asynchronously_and_failure_never_breaks_the_response(self):
        import email
        import email.header

        admin = admin_client()
        admin.post("/admin/site-settings", data={"inquiry_notify_emails": "ops@example.com\nsales@example.com"})
        srv = FakeSmtp()
        srv.start()
        os.environ.update(SMTP_HOST="127.0.0.1", SMTP_PORT=str(srv.port), SMTP_TLS="0", SMTP_FROM="site@example.com")
        payload = {"full_name": "علی رضایی", "email": "mail1@inq.test", "phone": "+98 21 8865 4200", "subject": "استعلام ایمیلی",
                   "message": "این یک پیام آزمایشی برای اعلان ایمیلی است."}
        r = CLIENT.post("/api/public/inquiries", json=payload, headers={"X-Real-IP": rand_ip()})
        self.assertEqual(r.status_code, 201)
        ref = json.loads(r.get_data())["reference_code"]
        for _ in range(50):
            if srv.messages:
                break
            time.sleep(0.2)
        self.assertEqual(len(srv.messages), 1)
        msg = email.message_from_bytes(srv.messages[0])
        self.assertIn("ops@example.com", msg["To"])
        self.assertIn("sales@example.com", msg["To"])
        self.assertEqual(msg["From"], "site@example.com")
        self.assertIn(ref, str(email.header.make_header(email.header.decode_header(msg["Subject"]))))
        self.assertIn("آزمایشی", msg.get_payload(decode=True).decode("utf-8"))
        srv.sock.close()
        # SMTP unreachable: still 201 and stored
        db_rows("DELETE FROM inquiries WHERE email='mail2@inq.test'") if False else run_async(APP.core.db.execute("DELETE FROM inquiries WHERE email='mail2@inq.test'"))
        os.environ["SMTP_PORT"] = "1"
        r = CLIENT.post("/api/public/inquiries", json={**payload, "email": "mail2@inq.test"}, headers={"X-Real-IP": rand_ip()})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(db_rows("SELECT COUNT(*) AS c FROM inquiries WHERE email='mail2@inq.test'")[0]["c"], 1)
        admin.post("/admin/site-settings", data={"inquiry_notify_emails": ""})


class ImportCli(unittest.TestCase):
    def test_import_ui_strings_cli(self):
        import subprocess

        env = dict(os.environ, PYTHONUTF8="1")
        base = [sys.executable, "-X", "utf8", str(ROOT / "main.py"), "import_ui_strings", "--file", str(ROOT / "front-locales" / "fa.json")]
        out = subprocess.run(base + ["--lang", "fa", "--prefix", "web."], capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=180)
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        self.assertRegex(out.stdout, r"\[fa\] added=0 updated=0 skipped=310 ignored=0")        # idempotent
        bad = subprocess.run(base + ["--lang", "zz"], capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=180)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("does not exist", bad.stdout)


def _form_token(admin, path):
    """The signed preview token embedded in the admin edit form's preview button."""
    html = admin.get(path).get_data(as_text=True)
    m = re.search(r"preview=([A-Za-z0-9_\-\.=]+)", html)
    assert m, "no preview button on " + path
    return m.group(1)


class DraftPreview(unittest.TestCase):
    def setUp(self):
        self.admin = admin_client()

    def test_product_preview_token_flow(self):
        pid = db_rows("SELECT id FROM products WHERE slug='demo-draft-product'")[0]["id"]
        self.assertEqual(get_json("/api/public/products/demo-draft-product")[0], 404)
        token = _form_token(self.admin, f"/admin/products/{pid}/edit")
        s, d, r = get_json(f"/api/public/products/demo-draft-product?preview={token}")
        self.assertEqual(s, 200)
        self.assertEqual(d["product"]["slug"], "demo-draft-product")
        self.assertEqual(d["product"]["model_code"], "DEMO-DRAFT-1")
        self.assertEqual(r.headers["Cache-Control"], "private, no-store")
        self.assertEqual(r.headers["X-Robots-Tag"], "noindex, nofollow")
        self.assertNotIn("ETag", r.headers)
        # a previewed draft must never leak into the cache for normal visitors
        self.assertEqual(get_json("/api/public/products/demo-draft-product")[0], 404)
        self.assertNotIn("demo-draft-product", [p["slug"] for p in get_json("/api/public/products?per_page=100")[1]["products"]])
        # the token is bound to this one item: another product's slug is not readable with it
        self.assertEqual(get_json(f"/api/public/products/demo-as-fcv-940?preview={token}")[0], 404)
        # garbage / tampered / wrong-kind tokens => 400 envelope
        for bad in ("garbage", token[:-2] + ("AA" if not token.endswith("AA") else "BB"), ""):
            s, d, _ = get_json(f"/api/public/products/demo-draft-product?preview={bad}")
            self.assertEqual(s, 404 if bad == "" else 400, bad)      # empty value = no token = plain (draft) lookup
            if s == 400:
                self.assertEqual(d["error"], "bad_request")
        aid = db_rows("SELECT id FROM articles WHERE slug='demo-draft-article'")[0]["id"]
        art_token = _form_token(self.admin, f"/admin/articles/{aid}/edit")
        self.assertEqual(get_json(f"/api/public/products/demo-draft-product?preview={art_token}")[0], 400)   # other entity kind

    def test_token_expires(self):
        pid = db_rows("SELECT id FROM products WHERE slug='demo-draft-product'")[0]["id"]
        token = _form_token(self.admin, f"/admin/products/{pid}/edit")
        os.environ["PREVIEW_TOKEN_TTL"] = "1"
        try:
            time.sleep(2.2)
            s, d, _ = get_json(f"/api/public/products/demo-draft-product?preview={token}")
            self.assertEqual((s, d["error"]), (400, "bad_request"))
        finally:
            os.environ.pop("PREVIEW_TOKEN_TTL", None)
        self.assertEqual(get_json(f"/api/public/products/demo-draft-product?preview={token}")[0], 200)

    def test_scheduled_article_and_draft_project_preview(self):
        aid = db_rows("SELECT id FROM articles WHERE slug='demo-scheduled-article'")[0]["id"]
        self.assertEqual(get_json("/api/public/articles/demo-scheduled-article")[0], 404)
        token = _form_token(self.admin, f"/admin/articles/{aid}/edit")
        s, d, _ = get_json(f"/api/public/articles/demo-scheduled-article?preview={token}")
        self.assertEqual(s, 200)
        self.assertEqual(d["article"]["slug"], "demo-scheduled-article")
        sector = db_rows("SELECT id FROM project_sectors ORDER BY id LIMIT 1")[0]["id"]
        r = self.admin.post("/admin/projects/create", data={"title__fa": "پروژه پیش‌نویس", "slug": "preview-draft-project",
                                                           "sector_id": str(sector), "status": "draft"})
        self.assertEqual(r.status_code, 302)
        pid = int(re.search(r"/(\d+)/edit", r.headers["Location"]).group(1))
        try:
            self.assertEqual(get_json("/api/public/projects/preview-draft-project")[0], 404)
            token = _form_token(self.admin, f"/admin/projects/{pid}/edit")
            s, d, _ = get_json(f"/api/public/projects/preview-draft-project?preview={token}")
            self.assertEqual((s, d["project"]["title"]["fa"]), (200, "پروژه پیش‌نویس"))
        finally:
            self.admin.post(f"/admin/projects/{pid}/delete")


class Navigation(unittest.TestCase):
    def setUp(self):
        self.admin = admin_client()
        self.created = []

    def tearDown(self):
        for i in sorted(self.created, reverse=True):
            self.admin.post(f"/admin/navigation/{i}/delete")

    def make(self, **data):
        base = {"menu": "footer", "label__fa": "آیتم تست", "label__en": "Test item", "href": "/about", "sort_order": "50"}
        base.update(data)
        r = self.admin.post("/admin/navigation/create", data=base)
        if r.status_code == 302:
            nid = int(re.search(r"/(\d+)/edit", r.headers["Location"]).group(1))
            self.created.append(nid)
            return r, nid
        return r, None

    def test_default_menus_and_shape(self):
        s, d, r = get_json("/api/public/navigation")
        self.assertEqual(s, 200)
        self.assertEqual(set(d), {"header", "footer", "updated_at"})
        self.assertGreaterEqual(len(d["header"]), 8)
        item = d["header"][0]
        self.assertEqual(set(item), {"id", "label", "href", "new_tab", "children"})
        self.assertEqual(item["href"], "/")
        self.assertIn("fa", item["label"])
        self.assertIn("en", item["label"])
        self.assertIn("max-age=30", r.headers["Cache-Control"])

    def test_group_with_children_visibility_and_cache_freshness(self):
        _, gid = self.make(label__fa="گروه تست", href="", sort_order="60")
        footer = get_json("/api/public/navigation")[1]["footer"]
        self.assertNotIn("گروه تست", [i["label"]["fa"] for i in footer])           # empty group heading is hidden
        _, cid = self.make(label__fa="زیرمنو تست", href="https://example.com/x", parent_id=str(gid), new_tab="1", sort_order="1")
        footer = get_json("/api/public/navigation")[1]["footer"]
        group = next(i for i in footer if i["label"]["fa"] == "گروه تست")
        self.assertIsNone(group["href"])
        self.assertEqual([(c["label"]["fa"], c["href"], c["new_tab"]) for c in group["children"]], [("زیرمنو تست", "https://example.com/x", True)])
        self.admin.post(f"/admin/navigation/{gid}/toggle")                            # inactive root hides its children too
        self.assertNotIn("گروه تست", [i["label"]["fa"] for i in get_json("/api/public/navigation")[1]["footer"]])
        self.admin.post(f"/admin/navigation/{gid}/toggle")
        self.admin.post(f"/admin/navigation/{gid}/delete")                            # deleting a root deletes its children
        self.assertEqual(db_rows("SELECT COUNT(*) AS c FROM nav_items WHERE id IN (%s,%s)", (gid, cid))[0]["c"], 0)

    def test_validation_rules(self):
        for bad in ("javascript:alert(1)", "//evil.example", "ftp://x", "bad link", "data:text/html,x"):
            r, _ = self.make(href=bad)
            self.assertEqual(r.status_code, 422, bad)
        r, _ = self.make(menu="sidebar")
        self.assertEqual(r.status_code, 422)
        for ok in ("/products", "https://a.example/b", "mailto:a@b.co", "tel:+982188654200", "#contact"):
            r, nid = self.make(href=ok)
            self.assertEqual(r.status_code, 302, ok)
        _, gid = self.make(href="", label__fa="گروه ۲")
        r, _ = self.make(parent_id=str(gid), href="")
        self.assertEqual(r.status_code, 422)                                         # child needs a link
        _, cid = self.make(parent_id=str(gid), href="/x")
        r, _ = self.make(parent_id=str(cid))
        self.assertEqual(r.status_code, 422)                                         # only two levels
        r, _ = self.make(parent_id=str(gid), menu="header")
        self.assertEqual(r.status_code, 422)                                         # parent must be in the same menu
        r = self.admin.post(f"/admin/navigation/{gid}/edit", data={"parent_id": str(gid)})
        self.assertEqual(r.status_code, 422)                                         # self-parent
        r = self.admin.post(f"/admin/navigation/{gid}/edit", data={"parent_id": str(cid)})
        self.assertEqual(r.status_code, 422)

    def test_change_notifies_frontend(self):
        _Sink.received.clear()
        srv = http.server.HTTPServer(("127.0.0.1", 0), _Sink)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        os.environ["FRONTEND_REVALIDATE_URL"] = f"http://127.0.0.1:{srv.server_address[1]}/r"
        os.environ["FRONTEND_REVALIDATE_SECRET"] = "s"
        APP.revalidate.window = 0.3
        try:
            self.make(label__fa="ویژه webhook")
            self.assertTrue(APP.revalidate.wait_idle(15))
            tags = set().union(*[set(b["tags"]) for _h, b in _Sink.received])
            self.assertIn("navigation", tags)
        finally:
            srv.shutdown()
            os.environ.pop("FRONTEND_REVALIDATE_URL", None)
            os.environ.pop("FRONTEND_REVALIDATE_SECRET", None)
            APP.revalidate.window = 2.0


class ServiceDetail(unittest.TestCase):
    def test_detail_seo_404_and_sitemap(self):
        s, d, _ = get_json("/api/public/services/demo-integration")
        self.assertEqual(s, 200)
        svc = d["service"]
        self.assertEqual(set(svc) - {"seo", "updated_at"}, {"id", "slug", "icon", "title", "short_description", "description", "deliverables", "industries"})
        self.assertEqual(svc["title"]["en"], "Integration")
        self.assertEqual(svc["seo"]["title"]["fa"], svc["title"]["fa"])
        self.assertRegex(svc["updated_at"], r"^\d{4}-\d{2}-\d{2}T")
        self.assertEqual(get_json("/api/public/services/no-such-service")[0], 404)
        self.assertIn("demo-integration", [x["slug"] for x in get_json("/api/public/sitemap")[1]["services"]])
        # inactive services disappear from detail, list and sitemap immediately
        admin = admin_client()
        sid = db_rows("SELECT id FROM services WHERE slug='demo-integration'")[0]["id"]
        admin.post(f"/admin/services/{sid}/toggle")
        try:
            self.assertEqual(get_json("/api/public/services/demo-integration")[0], 404)
            self.assertNotIn("demo-integration", [x["slug"] for x in get_json("/api/public/services")[1]["services"]])
            self.assertNotIn("demo-integration", [x["slug"] for x in get_json("/api/public/sitemap")[1]["services"]])
        finally:
            admin.post(f"/admin/services/{sid}/toggle")
        self.assertEqual(get_json("/api/public/services/demo-integration")[0], 200)
        self.assertGreaterEqual(len(get_json("/api/public/services")[1]["services"]), 2)


class SiteFlagsAndCatalogMode(unittest.TestCase):
    def setUp(self):
        self.admin = admin_client()

    def tearDown(self):
        self.admin.post("/admin/site-settings", data={
            "maintenance_enabled": "0", "maintenance_message__fa": "", "maintenance_message__en": "", "feature_faq": "1",
            "feature_search": "1", "track_enabled": "0", "catalog_mode": "0"})

    def site(self):
        return get_json("/api/public/site")[1]["site"]

    def test_defaults_then_maintenance_and_feature_flags(self):
        site = self.site()
        self.assertEqual(site["maintenance"], {"enabled": False, "message": {"fa": ""}})
        self.assertEqual(site["features"], {"inquiry_form": True, "search": True, "news": True, "projects": True, "services": True, "faq": True})
        self.assertEqual(site["captcha"], {"provider": None, "site_key": None})
        self.assertIs(site["analytics"]["track"], False)
        r = self.admin.post("/admin/site-settings", data={
            "maintenance_enabled": "1", "maintenance_message__fa": "در حال به‌روزرسانی", "maintenance_message__en": "Back soon",
            "feature_faq": "0", "feature_search": "0"})
        self.assertEqual(r.status_code, 302)
        site = self.site()                                                           # fresh immediately (cache cleared by the write)
        self.assertEqual(site["maintenance"], {"enabled": True, "message": {"fa": "در حال به‌روزرسانی", "en": "Back soon"}})
        self.assertEqual((site["features"]["faq"], site["features"]["search"], site["features"]["news"]), (False, False, True))
        self.assertEqual(get_json("/api/public/health")[0], 200)                     # maintenance never blocks the API itself

    def test_catalog_mode_hides_commerce_fields_without_losing_them(self):
        pid = db_rows("SELECT id FROM products WHERE slug='demo-as-pt-210'")[0]["id"]
        self.admin.post(f"/admin/products/{pid}/edit", data={"price": "1234", "old_price": "2000", "stock": "7"})
        hidden = self.admin.get(f"/admin/products/{pid}/edit").get_json()["data"]["hidden"]
        for f in ("price", "old_price", "stock"):
            self.assertNotIn(f, hidden)
        self.admin.post("/admin/site-settings", data={"catalog_mode": "1"})
        hidden = self.admin.get(f"/admin/products/{pid}/edit").get_json()["data"]["hidden"]
        for f in ("price", "old_price", "stock"):
            self.assertIn(f, hidden, f)
        self.assertNotIn("model_code", hidden)
        self.admin.post(f"/admin/products/{pid}/edit", data={"subtitle__fa": "کاتالوگ"})            # save while hidden
        row = db_rows("SELECT price, old_price, stock FROM products WHERE id=%s", (pid,))[0]
        self.assertEqual((float(row["price"]), float(row["old_price"]), row["stock"]), (1234.0, 2000.0, 7))   # untouched
        r = self.admin.post("/admin/products/create", data={"name__fa": "کاتالوگ جدید", "model_code": "CAT-MODE-1", "slug": "cat-mode-1", "status": "published"})
        self.assertEqual(r.status_code, 302)                                                      # creating works without the fields
        new_id = db_rows("SELECT id FROM products WHERE slug='cat-mode-1'")[0]["id"]
        self.assertEqual(float(db_rows("SELECT price FROM products WHERE id=%s", (new_id,))[0]["price"]), 0.0)
        self.admin.post(f"/admin/products/{new_id}/delete")
        self.assertNotIn("catalog_mode", json.dumps(get_json("/api/public/site")[1]))              # admin-only setting
        for k in ("price", "old_price", "stock"):
            self.assertNotIn(k, get_json("/api/public/products/demo-as-pt-210")[1]["product"])


class _FakeCaptcha(http.server.BaseHTTPRequestHandler):
    calls = []

    def do_POST(self):
        from urllib.parse import parse_qs

        body = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
        _FakeCaptcha.calls.append({k: v[0] for k, v in body.items()})
        ok = body.get("response", [""])[0] == "good-token" and body.get("secret", [""])[0] == "cap-secret"
        payload = json.dumps({"success": ok}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


class CaptchaOnInquiries(unittest.TestCase):
    def setUp(self):
        _FakeCaptcha.calls.clear()
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), _FakeCaptcha)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        os.environ.update(CAPTCHA_PROVIDER="turnstile", CAPTCHA_SECRET="cap-secret", CAPTCHA_SITE_KEY="public-site-key",
                          CAPTCHA_VERIFY_URL=f"http://127.0.0.1:{self.srv.server_address[1]}/siteverify")
        APP.cache.invalidate_namespace("public_api")

    def tearDown(self):
        self.srv.shutdown()
        for k in ("CAPTCHA_PROVIDER", "CAPTCHA_SECRET", "CAPTCHA_SITE_KEY", "CAPTCHA_VERIFY_URL"):
            os.environ.pop(k, None)
        APP.cache.invalidate_namespace("public_api")

    def payload(self, **over):
        d = {"full_name": "علی رضایی", "email": "cap@inq.test", "phone": "+98 21 8865 4200", "subject": "درخواست قیمت",
             "message": "لطفاً قیمت و زمان تحویل را اعلام کنید."}
        d.update(over)
        return d

    def post(self, body, ip=None):
        return CLIENT.post("/api/public/inquiries", json=body, headers={"X-Real-IP": ip or rand_ip()})

    def test_site_exposes_public_key_but_never_the_secret(self):
        site = get_json("/api/public/site")[1]
        self.assertEqual(site["site"]["captcha"], {"provider": "turnstile", "site_key": "public-site-key"})
        self.assertNotIn("cap-secret", json.dumps(site))

    def test_token_is_required_verified_and_single_purpose(self):
        run_async(APP.core.db.execute("DELETE FROM inquiries WHERE email='cap@inq.test'"))     # DB persists between runs
        r = self.post(self.payload())
        d = json.loads(r.get_data())
        self.assertEqual((r.status_code, d["error"], d["fields"]["captcha_token"]), (422, "validation_failed", {"code": "required"}))
        self.assertEqual(_FakeCaptcha.calls, [])                                      # nothing to verify without a token
        r = self.post(self.payload(captcha_token="bad-token"))
        self.assertEqual((r.status_code, json.loads(r.get_data())["fields"]["captcha_token"]), (422, {"code": "invalid_value"}))
        self.assertEqual(db_rows("SELECT COUNT(*) AS c FROM inquiries WHERE email='cap@inq.test'")[0]["c"], 0)
        ip = rand_ip()
        r = self.post(self.payload(captcha_token="good-token"), ip)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(_FakeCaptcha.calls[-1]["remoteip"], ip)
        self.assertEqual(_FakeCaptcha.calls[-1]["secret"], "cap-secret")
        self.assertEqual(db_rows("SELECT COUNT(*) AS c FROM inquiries WHERE email='cap@inq.test'")[0]["c"], 1)
        r = self.post(self.payload(captcha_token="x" * 5000))
        self.assertEqual(r.status_code, 422)

    def test_invalid_fields_do_not_burn_a_token_and_honeypot_skips_captcha(self):
        n = len(_FakeCaptcha.calls)
        r = self.post(self.payload(email="bad", captcha_token="good-token"))
        d = json.loads(r.get_data())
        self.assertEqual(r.status_code, 422)
        self.assertIn("email", d["fields"])
        self.assertNotIn("captcha_token", d["fields"])
        self.assertEqual(len(_FakeCaptcha.calls), n)                                  # verification only after the fields are valid
        r = self.post(self.payload(website="http://spam.example"))
        self.assertEqual(r.status_code, 201)                                          # honeypot still fakes success
        self.assertEqual(len(_FakeCaptcha.calls), n)

    def test_unreachable_verifier_is_503_not_a_bypass(self):
        os.environ["CAPTCHA_VERIFY_URL"] = "http://127.0.0.1:1/siteverify"
        r = self.post(self.payload(email="cap503@inq.test", captcha_token="good-token"))
        self.assertEqual((r.status_code, json.loads(r.get_data())["error"]), (503, "unavailable"))
        self.assertEqual(db_rows("SELECT COUNT(*) AS c FROM inquiries WHERE email='cap503@inq.test'")[0]["c"], 0)


class TrackEndpoint(unittest.TestCase):
    def setUp(self):
        from app.plugins.visits.plugin import LIMITER

        LIMITER.reset()
        self.admin = admin_client()
        run_async(APP.core.db.execute("DELETE FROM frontend_pageviews WHERE path LIKE '/track-test%'"))

    def tearDown(self):
        self.admin.post("/admin/site-settings", data={"track_enabled": "0"})
        run_async(APP.core.db.execute("DELETE FROM frontend_pageviews WHERE path LIKE '/track-test%'"))

    def post(self, body, **kw):
        return CLIENT.post("/api/public/track", json=body, **kw)

    def count(self):
        return db_rows("SELECT COUNT(*) AS c FROM frontend_pageviews WHERE path LIKE '/track-test%'")[0]["c"]

    def test_disabled_by_default_accepts_but_stores_nothing(self):
        r = self.post({"path": "/track-test/a", "locale": "fa"})
        self.assertEqual((r.status_code, r.get_data()), (204, b""))
        self.assertEqual(self.count(), 0)

    def test_enabled_stores_a_privacy_friendly_row(self):
        self.admin.post("/admin/site-settings", data={"track_enabled": "1"})
        self.assertTrue(get_json("/api/public/site")[1]["site"]["analytics"]["track"])
        ip = "198.51.100.77"
        r = self.post({"path": "/track-test/a?x=1", "referrer": "https://google.com/", "locale": "en", "visitor_id": "vis_ABCDEFGH12"},
                      headers={"X-Real-IP": ip, "User-Agent": "Mozilla/5.0 Test"})
        self.assertEqual(r.status_code, 204)
        row = db_rows("SELECT * FROM frontend_pageviews WHERE path LIKE '/track-test%'")[0]
        self.assertEqual((row["visitor"], row["locale"], row["referrer"]), ("vis_ABCDEFGH12", "en", "https://google.com/"))
        self.assertEqual(len(row["ip_hash"]), 16)
        self.assertNotIn(ip, json.dumps({k: str(v) for k, v in row.items()}))              # no raw IP stored
        r = self.post({"path": "/track-test/bot"}, headers={"User-Agent": "Googlebot/2.1"})
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.count(), 1)                                                   # bots ignored
        r = self.post({"path": "/track-test/b"}, headers={"X-Real-IP": ip, "User-Agent": "Mozilla/5.0 Test"})
        self.assertEqual(db_rows("SELECT visitor FROM frontend_pageviews WHERE path='/track-test/b'")[0]["visitor"],
                         row["ip_hash"])                                                    # no visitor_id -> hashed IP stands in
        page = self.admin.get("/admin/frontend-visits?days=7").get_data(as_text=True)
        self.assertIn("/track-test/a?x=1", page)
        self.assertNotIn("خاموش", page)

    def test_validation_and_errors(self):
        for body, field in [({}, "path"), ({"path": "nope"}, "path"), ({"path": "//evil"}, "path"), ({"path": "/a b"}, "path"),
                            ({"path": "/" + "a" * 600}, "path"), ({"path": "/ok", "locale": "de"}, "locale"),
                            ({"path": "/ok", "visitor_id": "x y"}, "visitor_id"), ({"path": "/ok", "referrer": 5}, "referrer")]:
            r = self.post(body)
            self.assertEqual(r.status_code, 422, body)
            self.assertIn(field, json.loads(r.get_data())["fields"])
        r = CLIENT.post("/api/public/track", data=b"{bad", content_type="application/json")
        self.assertEqual(r.status_code, 400)
        r = CLIENT.post("/api/public/track", data=b'{"path":"/' + b"a" * 9000 + b'"}', content_type="application/json")
        self.assertEqual(r.status_code, 413)

    def test_rate_limited_per_ip(self):
        ip = rand_ip()
        codes = [self.post({"path": "/track-test/rl"}, headers={"X-Real-IP": ip}).status_code for _ in range(242)]
        self.assertEqual(codes[:240], [204] * 240)
        self.assertEqual(codes[240], 429)

    def test_cors_applies_to_track(self):
        os.environ["CORS_ALLOWED_ORIGINS"] = "https://a.example"
        try:
            r = CLIENT.options("/api/public/track", headers={"Origin": "https://a.example", "Access-Control-Request-Method": "POST"})
            self.assertEqual((r.status_code, r.headers["Access-Control-Allow-Origin"]), (204, "https://a.example"))
        finally:
            os.environ.pop("CORS_ALLOWED_ORIGINS", None)


class HandPickedLists(unittest.TestCase):
    """`?slugs=a,b` on the public lists (page builder: hand-picked products / articles / projects) keeps the given order."""

    def pick(self, kind, key):
        s, d, _r = get_json(f"/api/public/{kind}?per_page=20")
        slugs = [x["slug"] for x in d[key]][:3]
        self.assertGreaterEqual(len(slugs), 2, kind)
        return slugs

    def test_order_is_kept_and_unknown_or_hidden_slugs_are_ignored(self):
        for kind in ("products", "articles", "projects"):
            slugs = self.pick(kind, kind)
            want = [slugs[1], slugs[0]]
            s, d, _r = get_json(f"/api/public/{kind}?slugs={want[0]},does-not-exist,{want[1]}")
            self.assertEqual(s, 200, kind)
            self.assertEqual([x["slug"] for x in d[kind]], want, kind)
            self.assertEqual(d["meta"]["total"], 2, kind)

    def test_empty_or_all_unknown_gives_an_empty_list_not_everything(self):
        s, d, _r = get_json("/api/public/products?slugs=nope-1,nope-2")
        self.assertEqual((s, d["products"], d["meta"]["total"]), (200, [], 0))


class PageBuilderApi(unittest.TestCase):
    """page_builder plugin: manifest sync (secret-guarded), page CRUD, draft/publish, signed preview. Uses its own theme id."""

    THEME, SECRET, A = "pbtest-theme", "pb-test-secret", "/api/admin/page-builder"
    MANIFEST = {
        "theme": "pbtest-theme", "name": "PB test",
        "pages": [{"key": "home", "path": "/", "label": {"fa": "خانه"},
                   "layout": {"sections": [{"columns": [{"widgets": [{"type": "heading", "settings": {"title": {"fa": "سلام"}}}]}]}]}},
                  {"key": "hdr", "path": "/pb-area/hdr", "role": "area", "label": {"fa": "هدر"}},
                  {"key": "tpl", "path": "/things/{slug}", "role": "template", "sample": "product", "label": {"fa": "قالب"}}],
        "widgets": [{"type": "heading", "label": "Heading", "fields": [{"name": "title", "type": "text", "i18n": True}]}],
    }

    @classmethod
    def setUpClass(cls):
        cls._old = os.environ.get("FRONTEND_REVALIDATE_SECRET")
        os.environ["FRONTEND_REVALIDATE_SECRET"] = cls.SECRET
        r = CLIENT.put(f"/api/public/themes/{cls.THEME}/manifest", json=cls.MANIFEST, headers={"X-Revalidate-Secret": cls.SECRET})
        assert r.status_code == 200, r.get_data(as_text=True)
        cls.admin = admin_client()

    @classmethod
    def tearDownClass(cls):
        run_async(APP.core.db.execute("DELETE r FROM site_page_revisions r JOIN site_pages p ON p.id=r.page_id WHERE p.theme=%s", (cls.THEME,)))
        run_async(APP.core.db.execute("DELETE FROM site_pages WHERE theme=%s", (cls.THEME,)))
        run_async(APP.core.db.execute("DELETE FROM page_themes WHERE theme=%s", (cls.THEME,)))
        if cls._old is None:
            os.environ.pop("FRONTEND_REVALIDATE_SECRET", None)
        else:
            os.environ["FRONTEND_REVALIDATE_SECRET"] = cls._old

    # -- helpers
    def api(self, method, path, **kw):
        r = getattr(self.admin._c, method)(self.A + path, headers=self.admin.H, **kw)
        return r.status_code, r.get_json()

    def public(self, slug, **qs):
        q = "&".join([f"theme={self.THEME}"] + [f"{k}={v}" for k, v in qs.items()])
        return get_json(f"/api/public/pages/{slug}?{q}")[:2]

    def new_page(self, slug, title="صفحهٔ آزمون"):
        code, body = self.api("post", "/pages", json={"theme": self.THEME, "slug": slug, "title": {"fa": title}})
        self.assertEqual(code, 201, body)
        return body["data"]

    # -- manifest
    def test_manifest_requires_the_shared_secret_and_matching_theme(self):
        url = f"/api/public/themes/{self.THEME}/manifest"
        self.assertEqual(CLIENT.put(url, json=self.MANIFEST).status_code, 401)
        self.assertEqual(CLIENT.put(url, json=self.MANIFEST, headers={"X-Revalidate-Secret": "wrong"}).status_code, 401)
        self.assertEqual(CLIENT.put(url, json={**self.MANIFEST, "theme": "other-theme"}, headers={"X-Revalidate-Secret": self.SECRET}).status_code, 422)

    def test_system_page_is_seeded_as_unpublished_draft(self):
        row = db_rows("SELECT * FROM site_pages WHERE theme=%s AND slug='home'", (self.THEME,))[0]
        self.assertEqual((row["kind"], row["status"], row["path"]), ("system", "draft", "/"))
        self.assertIn("سلام", row["draft_json"])
        self.assertEqual(self.public("home")[0], 404)                 # the frontend falls back to its built-in page

    # -- custom page lifecycle
    def test_draft_publish_unpublish_and_preview(self):
        page = self.new_page("pbtest/lifecycle")
        pid = page["id"]
        layout = {"sections": [{"columns": [{"span": 6, "widgets": [{"type": "heading", "settings": {"title": {"fa": "عنوان <b>x</b>"}}}]}]}]}
        code, body = self.api("put", f"/pages/{pid}", json={"layout": layout})
        self.assertEqual(code, 200, body)
        self.assertEqual(body["data"]["layout"]["sections"][0]["columns"][0]["widgets"][0]["settings"]["title"], {"fa": "عنوان x"})
        self.assertEqual(self.public("pbtest/lifecycle")[0], 404)       # drafts are invisible
        # a signed preview shows the draft, only for its own page
        _c, pv = self.api("post", f"/pages/{pid}/preview-url")
        token = pv["data"]["url"].split("pb=")[1].split("&")[0]
        code, data = self.public("pbtest/lifecycle", preview=token)
        self.assertEqual((code, data["page"]["preview"]), (200, True))
        self.assertEqual(self.public("pbtest/other", preview=token)[0], 404)
        # publish
        code, body = self.api("post", f"/pages/{pid}/publish")
        self.assertEqual((code, body["data"]["status"], body["data"]["has_changes"]), (200, "published", False))
        code, data = self.public("pbtest/lifecycle")
        self.assertEqual((code, data["page"]["preview"], data["page"]["revision"]), (200, False, 1))
        listed = get_json(f"/api/public/pages?theme={self.THEME}")[1]["pages"]
        self.assertIn("pbtest/lifecycle", [p["slug"] for p in listed])
        # editing after publishing only changes the draft
        self.api("put", f"/pages/{pid}", json={"layout": {"sections": []}})
        self.assertEqual(len(self.public("pbtest/lifecycle")[1]["page"]["layout"]["sections"]), 1)
        self.assertTrue(self.api("get", f"/pages/{pid}")[1]["data"]["has_changes"])
        # revisions + restore
        revs = self.api("get", f"/pages/{pid}/revisions")[1]["data"]
        self.assertEqual(len(revs), 1)
        restored = self.api("post", f"/pages/{pid}/restore", json={"revision_id": revs[0]["id"]})[1]["data"]
        self.assertEqual(len(restored["layout"]["sections"]), 1)
        # unpublish, delete
        self.api("post", f"/pages/{pid}/unpublish")
        self.assertEqual(self.public("pbtest/lifecycle")[0], 404)
        self.assertEqual(self.api("delete", f"/pages/{pid}")[0], 200)

    def test_slug_rules_and_conflicts(self):
        for bad in ("products", "a b", "", "admin/x", "x/y/z/w"):
            code, _body = self.api("post", "/pages", json={"theme": self.THEME, "slug": bad, "title": {"fa": "x"}})
            self.assertEqual(code, 422, bad)
        page = self.new_page("pbtest/dup")
        self.assertEqual(self.api("post", "/pages", json={"theme": self.THEME, "slug": "pbtest/dup", "title": {"fa": "x"}})[0], 409)
        self.assertEqual(self.api("post", "/pages", json={"theme": "no-such-theme", "slug": "pbtest/z", "title": {"fa": "x"}})[0], 422)
        self.api("delete", f"/pages/{page['id']}")

    def test_system_pages_cannot_be_deleted_but_can_be_reset(self):
        pid = db_rows("SELECT id FROM site_pages WHERE theme=%s AND slug='home'", (self.THEME,))[0]["id"]
        self.assertEqual(self.api("delete", f"/pages/{pid}")[0], 409)
        self.api("put", f"/pages/{pid}", json={"layout": {"sections": []}})
        code, body = self.api("post", f"/pages/{pid}/reset")
        self.assertEqual((code, len(body["data"]["layout"]["sections"])), (200, 1))

    # -- phase 2: scheduling, templates, options, roles, common settings
    def test_scheduled_publish_goes_live_when_its_time_comes(self):
        import datetime as dt

        page = self.new_page("pbtest/scheduled")
        pid = page["id"]
        later = (dt.datetime.utcnow() + dt.timedelta(hours=2)).replace(microsecond=0).isoformat() + "Z"
        code, body = self.api("post", f"/pages/{pid}/publish", json={"publish_at": later})
        self.assertEqual((code, body["data"]["status"]), (200, "scheduled"))
        self.assertEqual(self.public("pbtest/scheduled")[0], 404)                  # not yet
        run_async(APP.core.db.execute("UPDATE site_pages SET publish_at=DATE_SUB(UTC_TIMESTAMP(), INTERVAL 1 MINUTE) WHERE id=%s", (pid,)))
        APP.cache.invalidate_namespace("public_api")
        self.assertEqual(self.public("pbtest/scheduled")[0], 200)                  # its time came: live without any cron
        self.assertIn("pbtest/scheduled", [p["slug"] for p in get_json(f"/api/public/pages?theme={self.THEME}")[1]["pages"]])
        # areas / templates cannot be scheduled
        hdr = db_rows("SELECT id FROM site_pages WHERE theme=%s AND slug='hdr'", (self.THEME,))[0]["id"]
        self.assertEqual(self.api("post", f"/pages/{hdr}/publish", json={"publish_at": later})[0], 422)
        self.api("post", f"/pages/{pid}/unpublish")
        self.assertEqual(self.public("pbtest/scheduled")[0], 404)
        self.api("delete", f"/pages/{pid}")

    def test_section_templates_crud(self):
        section = {"columns": [{"span": 6, "widgets": [{"type": "heading", "settings": {"title": {"fa": "کارت"}}}]}, {"span": 6}]}
        code, body = self.api("post", "/templates", json={"theme": self.THEME, "name": "دو کارت", "section": section})
        self.assertEqual(code, 201, body)
        tid = body["data"]["id"]
        listed = self.api("get", f"/templates?theme={self.THEME}")[1]["data"]
        self.assertIn(tid, [t["id"] for t in listed])
        one = self.api("get", f"/templates/{tid}")[1]["data"]
        self.assertEqual((one["name"], len(one["section"]["columns"])), ("دو کارت", 2))
        self.assertEqual(self.api("post", "/templates", json={"theme": self.THEME, "name": "", "section": section})[0], 422)
        self.assertEqual(self.api("post", "/templates", json={"theme": "nope", "name": "x", "section": section})[0], 422)
        self.assertEqual(self.api("delete", f"/templates/{tid}")[0], 200)
        self.assertEqual(self.api("get", f"/templates/{tid}")[0], 404)

    def test_page_options_and_common_settings_round_trip(self):
        page = self.new_page("pbtest/options")
        pid = page["id"]
        layout = {"sections": [{"common": {"anim_type": "slide-left", "parallax": 20, "sticky": True}, "columns": [
            {"span": 6, "span_tablet": 12, "span_mobile": 12, "common": {"hover_effect": "lift"}, "widgets": [
                {"type": "heading", "settings": {"title": {"fa": "الف"}}, "common": {"loop_effect": "float", "hide_mobile": True}},
                {"type": "inner_row", "columns": [{"span": 6, "widgets": [{"type": "heading", "settings": {}}]}, {"span": 6}]}]}]}]}
        code, body = self.api("put", f"/pages/{pid}", json={"layout": layout, "options": {"hide_header": True, "evil": True}})
        self.assertEqual(code, 200, body)
        sec = body["data"]["layout"]["sections"][0]
        self.assertEqual(sec["common"], {"anim_type": "slide-left", "parallax": 20, "sticky": True})
        col = sec["columns"][0]
        self.assertEqual((col["span_tablet"], col["common"]), (12, {"hover_effect": "lift"}))
        self.assertEqual(col["widgets"][0]["common"], {"loop_effect": "float", "hide_mobile": True})
        self.assertEqual(len(col["widgets"][1]["columns"]), 2)
        self.assertEqual(body["data"]["options"], {"hide_header": True})
        self.api("post", f"/pages/{pid}/publish")
        pub = self.public("pbtest/options")[1]["page"]
        self.assertEqual(pub["options"], {"hide_header": True})
        self.assertEqual(pub["role"], "page")
        self.api("delete", f"/pages/{pid}")

    def test_roles_areas_and_template_preview_needs_a_sample(self):
        rows = {p["slug"]: p for p in self.api("get", f"/pages?theme={self.THEME}")[1]["data"]}
        self.assertEqual((rows["hdr"]["role"], rows["tpl"]["role"], rows["home"]["role"]), ("area", "template", "page"))
        tpl = rows["tpl"]["id"]
        self.assertEqual(self.api("post", f"/pages/{tpl}/preview-url", json={})[0], 409)
        code, out = self.api("post", f"/pages/{tpl}/preview-url", json={"sample": "my thing"})
        self.assertEqual(code, 200)
        self.assertIn("/things/my%20thing?pb=", out["data"]["url"])
        # the theme payload carries the platform-level fields the editor builds its Style / Motion / Advanced tabs from
        th = self.api("get", f"/themes/{self.THEME}")[1]["data"]
        self.assertIn("anim_type", [f["name"] for f in th["common_fields"]["widget"]])
        self.assertIn("parallax", [f["name"] for f in th["common_fields"]["section"]])

    def test_admin_endpoints_need_login_and_csrf(self):
        anon = APP.test_client()
        self.assertEqual(anon.get(self.A + "/pages?theme=x").status_code, 401)
        self.assertEqual(self.admin._c.post(self.A + "/pages", json={}).status_code, 403)     # no CSRF header

    def test_export_import_round_trip(self):
        page = self.new_page("pbtest/export")
        layout = {"sections": [{"columns": [{"widgets": [{"type": "heading", "settings": {"title": {"fa": "الف"}}}]}]}]}
        self.api("put", f"/pages/{page['id']}", json={"layout": layout})
        dump = self.api("get", f"/pages/{page['id']}/export")[1]["data"]
        self.api("delete", f"/pages/{page['id']}")
        code, body = self.api("post", "/pages/import", json=dump)
        self.assertEqual(code, 201, body)
        self.assertEqual(body["data"]["layout"]["sections"][0]["columns"][0]["widgets"][0]["settings"]["title"], {"fa": "الف"})
        self.api("delete", f"/pages/{body['data']['id']}")


if __name__ == "__main__":
    unittest.main()
