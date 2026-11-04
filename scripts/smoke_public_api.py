"""Smoke test of every ``/api/public`` endpoint: calls them and checks the
documented shape (required keys, types, ``fa`` in every I18n value, absolute
media URLs, ISO times). Exit code != 0 on any failure.

    python scripts/smoke_public_api.py                       # in-process (Flask test client)
    python scripts/smoke_public_api.py --base http://127.0.0.1:5000   # against a running server

Run ``python scripts/seed_demo.py`` first so the lists are not empty.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS: list = []
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  FAIL:", msg)
    return cond


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------
class Client:
    def __init__(self, base=None):
        self.base = base.rstrip("/") if base else None
        self.flask = None
        if not base:
            from app import create_app

            self.flask = create_app().test_client()

    def request(self, method, path, body=None, headers=None):
        headers = headers or {}
        if self.flask:
            fn = getattr(self.flask, method.lower())
            kw = {"headers": headers}
            if body is not None:
                kw["json"] = body
            r = fn(path, **kw)
            raw = r.get_data()
            ctype = r.headers.get("Content-Type", "")
            data = json.loads(raw) if raw and "json" in ctype else None
            return r.status_code, dict(r.headers), data, raw
        req = urllib.request.Request(self.base + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw, status, hdrs = r.read(), r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            raw, status, hdrs = e.read(), e.code, dict(e.headers)
        ctype = hdrs.get("Content-Type", "")
        return status, hdrs, (json.loads(raw) if raw and "json" in ctype else None), raw

    def get(self, path, headers=None):
        return self.request("GET", path, headers=headers)


# ---------------------------------------------------------------------------
# shape validators
# ---------------------------------------------------------------------------
def i18n(v, where, lst=False):
    if not check(isinstance(v, dict), f"{where}: I18n must be an object, got {type(v).__name__}"):
        return
    check("fa" in v, f"{where}: missing 'fa'")
    for k, val in v.items():
        if lst:
            check(isinstance(val, list) and all(isinstance(x, str) for x in val), f"{where}.{k}: must be list[str]")
            if k != "fa":
                check(len(val) > 0, f"{where}.{k}: empty non-fa list must be omitted")
        else:
            check(isinstance(val, str), f"{where}.{k}: must be str (never null)")
            if k != "fa":
                check(val != "", f"{where}.{k}: empty non-fa text must be omitted")


def media(v, where):
    if v is None:
        return
    if not check(isinstance(v, dict), f"{where}: Media must be object|null"):
        return
    check(isinstance(v.get("url"), str) and v["url"].startswith(("http://", "https://")), f"{where}.url must be absolute: {v.get('url')}")
    i18n(v.get("alt"), f"{where}.alt")
    for k in ("width", "height"):
        check(v.get(k) is None or isinstance(v[k], int), f"{where}.{k} int|null")
    check(v.get("mime") is None or isinstance(v["mime"], str), f"{where}.mime str|null")


def keys(obj, required, where):
    if not check(isinstance(obj, dict), f"{where}: must be object"):
        return False
    missing = [k for k in required if k not in obj]
    check(not missing, f"{where}: missing keys {missing}")
    return not missing


def iso(v, where, nullable=False):
    if v is None and nullable:
        return
    check(isinstance(v, str) and bool(ISO_RE.match(v)), f"{where}: not ISO-8601 Z: {v!r}")


def meta_ok(m, where):
    keys(m, ["total", "page", "per_page", "total_pages"], where)


def seo(s, where):
    if keys(s, ["title", "description", "keywords", "og_image", "noindex"], where):
        for k in ("title", "description", "keywords"):
            i18n(s[k], f"{where}.{k}")
        media(s["og_image"], f"{where}.og_image")
        check(isinstance(s["noindex"], bool), f"{where}.noindex bool")


def product_card(p, where):
    if not keys(p, ["id", "slug", "model_code", "name", "subtitle", "short_description", "featured", "is_new", "cover",
                    "category", "brand", "tags", "certifications", "updated_at"], where):
        return
    for k in ("name", "subtitle", "short_description"):
        i18n(p[k], f"{where}.{k}")
    media(p["cover"], f"{where}.cover")
    check(isinstance(p["featured"], bool) and isinstance(p["is_new"], bool), f"{where}: booleans")
    for t in p["tags"]:
        keys(t, ["slug", "label"], f"{where}.tags[]")
        i18n(t["label"], f"{where}.tags[].label")
    check(all(isinstance(c, str) for c in p["certifications"]), f"{where}.certifications")
    iso(p["updated_at"], f"{where}.updated_at")
    for banned in ("price", "old_price", "stock"):
        check(banned not in p, f"{where}: commercial field {banned} must not be exposed")


def category_card(c, where):
    if keys(c, ["id", "slug", "parent_slug", "name", "short_description", "icon", "cover", "standards", "product_count", "sort_order"], where):
        i18n(c["name"], f"{where}.name")
        i18n(c["short_description"], f"{where}.short_description")
        media(c["cover"], f"{where}.cover")
        check(isinstance(c["product_count"], int), f"{where}.product_count int")


def project_card(p, where):
    if keys(p, ["id", "slug", "title", "sector", "location", "completion_year", "cover", "short_description", "featured",
                "highlight_metric", "updated_at"], where):
        i18n(p["title"], f"{where}.title")
        media(p["cover"], f"{where}.cover")
        iso(p["updated_at"], f"{where}.updated_at")


def article_card(a, where):
    if keys(a, ["id", "slug", "title", "excerpt", "category", "published_at", "reading_time_minutes", "author", "cover", "featured",
                "updated_at"], where):
        i18n(a["title"], f"{where}.title")
        iso(a["published_at"], f"{where}.published_at")
        check(isinstance(a["reading_time_minutes"], int) and a["reading_time_minutes"] >= 1, f"{where}.reading_time_minutes")


def document(d, where):
    if keys(d, ["id", "type", "title", "revision", "updated_at", "files"], where):
        i18n(d["title"], f"{where}.title")
        check(d["type"] in ("datasheet", "manual", "certificate", "cad", "brochure", "other"), f"{where}.type")
        check(len(d["files"]) >= 1, f"{where}.files empty")
        for lang, f in d["files"].items():
            keys(f, ["download_url", "view_url", "format", "mime", "size_bytes", "size_label"], f"{where}.files.{lang}")
            check(f["download_url"].startswith("http"), f"{where}: download_url must be absolute")


# ---------------------------------------------------------------------------
def run(c: Client):
    print("health")
    s, h, d, _ = c.get("/api/public/health")
    check(s == 200 and d.get("ok") is True and d.get("db") is True and isinstance(d.get("version"), str), "health body")
    iso(d.get("time"), "health.time")
    check("no-store" in h.get("Cache-Control", ""), "health must not be cached")

    print("site")
    s, h, d, _ = c.get("/api/public/site")
    check(s == 200, f"/site status {s}")
    site = d["site"]
    keys(site, ["name", "short_name", "legal_name", "tagline", "logo_subtitle", "alternate_name", "site_url", "branding", "theme",
                "contact", "address_structured", "social", "header_badges", "search_suggestions", "seo", "analytics", "media",
                "page_meta", "languages", "maintenance", "features", "captcha"], "site")
    keys(site["maintenance"], ["enabled", "message"], "site.maintenance")
    i18n(site["maintenance"]["message"], "site.maintenance.message")
    keys(site["features"], ["inquiry_form", "search", "news", "projects", "services", "faq"], "site.features")
    check(all(isinstance(v, bool) for v in site["features"].values()), "site.features must be booleans")
    keys(site["captcha"], ["provider", "site_key"], "site.captcha")
    keys(site["analytics"], ["ga4_id", "gtm_id", "track"], "site.analytics")
    check(isinstance(site["analytics"]["track"], bool), "analytics.track bool")
    for k in ("name", "short_name", "legal_name", "tagline", "logo_subtitle"):
        i18n(site[k], f"site.{k}")
    keys(site["branding"], ["logo_light", "logo_dark", "logo_mark", "favicon", "og_default_image", "theme_color"], "site.branding")
    keys(site["branding"]["favicon"], ["ico", "svg", "png_32", "png_192", "png_512", "apple_touch"], "site.branding.favicon")
    keys(site["theme"], ["primary", "primary_hover", "accent", "secondary", "dark_surface"], "site.theme")
    for slot in ("home.hero", "home.intro", "home.capabilities", "about.hq", "product.placeholder", "og.products", "og.projects",
                 "og.news", "og.services", "og.contact", "og.about"):
        check(slot in site["media"], f"site.media missing slot {slot}")
        media(site["media"].get(slot), f"site.media[{slot}]")
    for page in ("home", "about", "products", "services", "projects", "news", "contact", "faq", "search"):
        if check(page in site["page_meta"], f"page_meta missing {page}"):
            seo({**site["page_meta"][page]}, f"page_meta.{page}")
    check(any(l["code"] == "fa" for l in site["languages"]["active"]), "languages.active must include fa")
    check("inquiry_notify_emails" not in json.dumps(d) and "inquiry_reference_prefix" not in json.dumps(d), "internal inquiry settings leaked")
    iso(d.get("updated_at"), "site.updated_at", nullable=True)
    etag = h.get("ETag")
    check(bool(etag), "ETag header")
    s2, _, _, _ = c.get("/api/public/site", headers={"If-None-Match": etag})
    check(s2 == 304, f"If-None-Match must give 304, got {s2}")

    print("categories")
    s, _, d, _ = c.get("/api/public/categories")
    check(s == 200, "/categories status")
    cats = d["categories"]
    for ct in cats:
        category_card(ct, "category")
        for ch in ct["children"]:
            category_card(ch, "category.child")
    slug = next((x["slug"] for x in cats if x["slug"].startswith("demo-")), cats[0]["slug"] if cats else None)
    if slug:
        s, _, d, _ = c.get(f"/api/public/categories/{quote(slug)}")
        check(s == 200 and keys(d["category"], ["description", "key_highlights", "parent", "children", "seo", "updated_at"], "category detail"),
              "category detail")
        seo(d["category"]["seo"], "category.seo")
        i18n(d["category"]["key_highlights"], "category.key_highlights", lst=True)
    s, _, d, _ = c.get("/api/public/categories/does-not-exist")
    check(s == 404 and d.get("error") == "not_found" and d.get("ok") is False, "category 404 json")

    print("brands / tags")
    s, _, d, _ = c.get("/api/public/brands")
    check(s == 200 and "brands" in d and "meta" in d, "/brands")
    meta_ok(d["meta"], "brands.meta")
    for b in d["brands"]:
        keys(b, ["id", "slug", "name", "description", "logo", "website_url", "product_count"], "brand")
        media(b["logo"], "brand.logo")
    if d["brands"]:
        s, _, bd, _ = c.get(f"/api/public/brands/{d['brands'][0]['slug']}")
        check(s == 200 and "seo" in bd["brand"], "brand detail has seo")
    s, _, d, _ = c.get("/api/public/tags")
    check(s == 200 and "tags" in d, "/tags")
    for t in d["tags"]:
        keys(t, ["slug", "label", "product_count"], "tag")

    print("products")
    s, _, d, _ = c.get("/api/public/products?facets=1&per_page=100")
    check(s == 200, "/products")
    keys(d, ["products", "meta", "facets"], "products")
    meta_ok(d["meta"], "products.meta")
    for p in d["products"]:
        product_card(p, "product")
    keys(d["facets"], ["categories", "brands", "tags"], "facets")
    slug = next((p["slug"] for p in d["products"] if p["slug"].startswith("demo-")), d["products"][0]["slug"] if d["products"] else None)
    if slug:
        s, _, pd, _ = c.get(f"/api/public/products/{quote(slug)}?related_limit=2")
        check(s == 200, "product detail status")
        p = pd["product"]
        product_card(p, "product.detail")
        keys(p, ["sku", "description", "features", "images", "specifications", "variants", "documents", "category_path", "related", "seo",
                 "created_at", "published_at"], "product.detail")
        i18n(p["description"], "product.description")
        i18n(p["features"], "product.features", lst=True)
        for im in p["images"]:
            media(im, "product.images[]")
        for sp in p["specifications"]:
            keys(sp, ["label", "value"], "spec")
        for v in p["variants"]:
            keys(v, ["model_code", "name", "configuration", "operating_range", "application"], "variant")
        for doc in p["documents"]:
            document(doc, "product.documents[]")
        check(len(p["related"]) <= 2, "related_limit respected")
        seo(p["seo"], "product.seo")
        iso(p["created_at"], "product.created_at")
        iso(p["published_at"], "product.published_at", nullable=True)
        check(all(r["slug"] != p["slug"] for r in p["related"]), "related excludes itself")
        for doc in p["documents"]:
            for lang, f in doc["files"].items():
                url = f["download_url"]
                path = url[url.index("/api/public"):]
                s, h, _, raw = c.get(path)
                check(s == 200 and raw[:5] == b"%PDF-", f"document download {path} -> {s}")
                check("attachment" in h.get("Content-Disposition", ""), "download Content-Disposition attachment")
                check(h.get("X-Content-Type-Options") == "nosniff", "download nosniff")
                break
            break
    s, _, d, _ = c.get("/api/public/products/does-not-exist")
    check(s == 404 and d["error"] == "not_found", "product 404")

    print("projects / articles")
    s, _, d, _ = c.get("/api/public/projects")
    check(s == 200, "/projects")
    meta_ok(d["meta"], "projects.meta")
    for p in d["projects"]:
        project_card(p, "project")
    if d["projects"]:
        s, _, pd, _ = c.get(f"/api/public/projects/{d['projects'][0]['slug']}")
        pr = pd["project"]
        project_card(pr, "project.detail")
        keys(pr, ["client", "challenge", "solution", "gallery", "impact_metrics", "specifications", "products", "related_projects", "seo"],
             "project.detail")
        for pc in pr["products"]:
            product_card(pc, "project.products[]")
        seo(pr["seo"], "project.seo")
    s, _, d, _ = c.get("/api/public/project-sectors")
    check(s == 200 and "sectors" in d, "/project-sectors")
    s, _, d, _ = c.get("/api/public/articles")
    check(s == 200, "/articles")
    meta_ok(d["meta"], "articles.meta")
    for a in d["articles"]:
        article_card(a, "article")
    check(all("scheduled" not in a["slug"] and "draft" not in a["slug"] for a in d["articles"]), "draft/scheduled article leaked")
    if d["articles"]:
        s, _, ad, _ = c.get(f"/api/public/articles/{d['articles'][0]['slug']}")
        a = ad["article"]
        article_card(a, "article.detail")
        keys(a, ["sections", "related", "seo"], "article.detail")
        for sec in a["sections"]:
            keys(sec, ["anchor", "heading", "paragraphs"], "section")
            i18n(sec["paragraphs"], "section.paragraphs", lst=True)
    s, _, d, _ = c.get("/api/public/article-categories")
    check(s == 200 and "categories" in d, "/article-categories")

    print("services / faq / company")
    s, _, d, _ = c.get("/api/public/services")
    keys(d, ["services", "process_steps"], "services")
    for i, st in enumerate(d["process_steps"]):
        check(st["step_number"] == f"{i + 1:02d}", "step_number sequence")
    s, _, d, _ = c.get("/api/public/faq")
    keys(d, ["categories", "items"], "faq")
    s, _, d, _ = c.get("/api/public/company")
    keys(d, ["stats", "timeline", "team", "certifications", "industries", "testimonials", "offices"], "company")
    for o in d["offices"]:
        keys(o, ["id", "title", "address", "phone", "phone_tel", "email", "hours", "lat", "lng", "coordinates_label", "is_primary"], "office")
    for cert in d["certifications"]:
        if cert["document"]:
            document(cert["document"], "certification.document")
    s, _, d2, _ = c.get("/api/public/company?include=stats,offices")
    check(set(d2) == {"stats", "offices"}, "company include filter")
    s, _, d3, _ = c.get("/api/public/company?include=nope")
    check(s == 400 and d3["error"] == "bad_request", "company bad include -> 400")

    print("navigation / service detail / track")
    s, h, d, _ = c.get("/api/public/navigation")
    check(s == 200, "/navigation status")
    keys(d, ["header", "footer", "updated_at"], "navigation")
    for menu in ("header", "footer"):
        for it in d[menu]:
            keys(it, ["id", "label", "href", "new_tab", "children"], f"navigation.{menu}[]")
            i18n(it["label"], f"navigation.{menu}[].label")
            for ch in it["children"]:
                keys(ch, ["id", "label", "href", "new_tab", "children"], f"navigation.{menu}[].children[]")
                check(ch["children"] == [], "navigation has only two levels")
    s, _, sv, _ = c.get("/api/public/services")
    if sv["services"]:
        slug = sv["services"][0]["slug"]
        s, _, d, _ = c.get(f"/api/public/services/{slug}")
        check(s == 200 and keys(d["service"], ["id", "slug", "icon", "title", "short_description", "description", "deliverables",
                                              "industries", "seo", "updated_at"], "service detail"), "service detail")
        seo(d["service"]["seo"], "service.seo")
    s, _, d, _ = c.get("/api/public/services/does-not-exist")
    check(s == 404 and d["error"] == "not_found", "service 404")
    s, _, d, raw = c.request("POST", "/api/public/track", body={"path": "/smoke-test"}, headers={"X-Real-IP": "2001:db8:1:2::9"})
    check(s == 204 and raw == b"", f"track must answer 204 (stored only when enabled), got {s}")
    s, _, d, _ = c.request("POST", "/api/public/track", body={"path": "nope"}, headers={"X-Real-IP": "2001:db8:1:2::9"})
    check(s == 422 and "path" in d["fields"], "track validation")
    s, _, d, _ = c.get("/api/public/products/does-not-exist?preview=garbage")
    check(s == 400 and d["error"] == "bad_request", "invalid preview token -> 400")

    print("search / home / sitemap")
    s, _, d, _ = c.get("/api/public/search?q=" + quote("DEMO-AS-FCV-940"))
    keys(d, ["query", "totals", "products", "projects", "articles", "pages"], "search")
    check(d["totals"].get("all") is not None and d["totals"]["products"] >= 1, "search finds the model code")
    s, _, d, _ = c.get("/api/public/search?q=a")
    check(s == 200 and d["totals"]["all"] == 0 and d["products"] == [], "short query -> empty, not an error")
    s, _, d, _ = c.get("/api/public/home")
    keys(d, ["featured_products", "categories", "featured_projects", "latest_articles", "stats", "industries", "certifications",
             "testimonials", "offices"], "home")
    s, _, d, _ = c.get("/api/public/sitemap")
    keys(d, ["site_url", "pages", "categories", "products", "projects", "articles", "services"], "sitemap")
    for p in d["products"]:
        keys(p, ["slug", "updated_at", "images"], "sitemap.products[]")
        iso(p["updated_at"], "sitemap.products[].updated_at")
        check(all(u.startswith("http") for u in p["images"]), "sitemap images absolute")

    print("error handling")
    for path, want in [("/api/public/products?page=abc", 200), ("/api/public/products?per_page=-1", 200), ("/api/public/products?per_page=999999", 200),
                       ("/api/public/products?sort=zzz", 400), ("/api/public/nope", 404), ("/api/public/products/%00x", None),
                       ("/api/public/products?page=-5&lang=%ff", 200), ("/api/public/search?types=zzz&q=ab", 400)]:
        s, h, d, _ = c.get(path)
        check(s < 500, f"{path} -> {s} (must never be 5xx)")
        if want:
            check(s == want, f"{path}: expected {want}, got {s}")
        if s >= 400:
            check(d is not None and d.get("ok") is False and "error" in d, f"{path}: error body must be the JSON envelope")
    s, _, d, _ = c.request("POST", "/api/public/site")
    check(s == 405 and d["error"] == "bad_request", "405 is JSON")

    print("inquiries")
    s, _, d, _ = c.request("POST", "/api/public/inquiries", body={"full_name": "x", "email": "bad"}, headers={"X-Real-IP": "203.0.113.77"})
    check(s == 422 and d["error"] == "validation_failed", f"422 expected, got {s}")
    if s == 422:
        check(d["fields"]["email"]["code"] == "invalid_email", "email code")
        check(d["fields"]["full_name"]["code"] == "too_short" and d["fields"]["full_name"]["min"] == 3, "full_name too_short with min")
        check(d["fields"]["message"]["code"] == "required", "message required")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", help="base URL of a running server (default: in-process)")
    args = ap.parse_args()
    c = Client(args.base)
    run(c)
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S)")
        sys.exit(1)
    print("smoke OK")


if __name__ == "__main__":
    main()
