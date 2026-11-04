# PROJECT_MAP.md

Directory and file map with one-line responsibilities. See
[docs/architecture.md](docs/architecture.md) for how these pieces connect at runtime.

```
Corporate/
├── main.py                      Process entry point: logging setup, create_app(), CLI (resetpass)
├── requirements.txt              flask[async], mysql-connector-python, python-dotenv, pillow,
│                                  user-agents, maxminddb, jdatetime
├── .env                          DB creds, SECRET_KEY, TEMPLATES_DIR/ASSETS_DIR, upload quota
│
├── app/
│   ├── __init__.py               create_app(): Flask app factory, boot sequence (see architecture.md)
│   │
│   ├── core/                     Framework code shared by the whole app (not a plugin)
│   │   ├── database.py           Database — pooled async wrapper over mysql-connector-python
│   │   ├── schema.py              SchemaManager — declarative CREATE TABLE / ADD COLUMN sync
│   │   ├── models.py              Model/Product/Category/Page — schema declarations for core
│   │   │                          tables; CRUD helper methods exist but are unused at runtime
│   │   │                          (real CRUD lives in each plugin's own queries)
│   │   ├── auth.py                AuthManager — password hashing, session login/logout, ensure_admin
│   │   ├── decorators.py          @login_required / @admin_required route guards
│   │   ├── plugin_manager.py      PluginManager — discovers/enables/disables plugins
│   │   ├── base_plugin.py         BasePlugin — base class every plugin's Plugin extends
│   │   ├── cache.py               PluginCache — in-process namespaced TTL cache + init_cache()
│   │   ├── public.py              /api/public infrastructure: JSON errors, CORS, ETag, response cache, Ctx
│   │   ├── content.py             i18n JSON helpers, search normalisation, slugs, absolute media URLs
│   │   ├── entity.py              spec-driven entity engine (multilingual forms, repeaters, transactional save)
│   │   ├── revalidate.py          frontend revalidation webhook + public-API cache invalidation
│   │   ├── captcha.py             optional Turnstile/hCaptcha verification for the contact form
│   │   ├── migrate.py             idempotent migration helpers (indexes, seed_once)
│   │   ├── routes.py              Core Blueprint: /, /login, /logout, /dashboard, /admin/settings,
│   │   │                          /admin/users, /admin/roles, /admin/themes, /admin/plugins
│   │   └── logs/                  Stray log output directory (see note below)
│   │
│   └── plugins/                  Self-contained features; each dir is one plugin (see
│       │                          docs/features/plugin-system.md for the contract)
│       ├── products/plugin.py     Product catalog: admin CRUD, public page, JSON API, caching
│       ├── categories/plugin.py   Two-level categories: admin CRUD, soft delete, public page/API
│       ├── i18n/                  Multi-language via URL prefix (/en/...); no cookie/session state
│       │   ├── plugin.py
│       │   └── locales/{fa,en}.json   fa.json = canonical source strings (read-only at runtime)
│       ├── images/plugin.py       File-manager media library over uploads/, DB mirror table
│       ├── cache/plugin.py        Admin UI for PluginCache: stats, clear namespace/all, set TTL
│       ├── tracking/              Visitor/request analytics (before/after_request hooks + GeoIP)
│       │   ├── plugin.py
│       │   ├── README.md          Plugin-authored deep-dive on the tracking design (kept as-is)
│       │   └── GeoLite2-*.mmdb    MaxMind GeoIP databases (binary, checked into repo)
│       ├── theme_builder/         Makes `settings.active_theme` actually apply to `/`; Elementor-style
│       │   │                      drag/drop page builder for a theme's home page (conspro only so far)
│       │   ├── plugin.py           routes, homepage view override, theme-asset serving
│       │   ├── widgets.py          per-theme widget catalog (field-specs, defaults, dynamic data)
│       │   ├── storage.py          file-based design storage under designs/<theme>/<page>/
│       │   └── renderer.py         single render pipeline shared by the public page and admin preview
│       ├── sample_hello/plugin.py Minimal example plugin (one JSON endpoint) — reference only
│       ├── public_api/            health, redirects, home, sitemap, search aggregators; /admin/revalidate
│       ├── site_settings/         identity/branding/SEO/media slots/social → GET /api/public/site
│       ├── brands/ documents/     brands; downloadable PDF/STEP/DWG documents (storage/documents, outside uploads/)
│       ├── projects/ articles/    portfolio and news (published/draft/scheduled)
│       ├── services/ faq/ company/ services + process, FAQ, about-us collections (stats, team, certifications…)
│       ├── inquiries/             contact form (POST /api/public/inquiries, optional CAPTCHA) + admin inbox
│       ├── navigation/            editable header/footer menus → GET /api/public/navigation
│       └── visits/                optional page-view tracking (POST /api/public/track) + report
│
├── scripts/                     seed_demo.py (demo data, --remove), smoke_public_api.py, build_frontend_doc.py
├── tests/                       test_logic.py (no DB) + test_api.py (real MySQL, loopback only)
├── docs/frontend-api.md         the API contract for the frontend agent (generated)
├── storage/                     Runtime data: private document files (not source)
├── designs/                      Runtime data: saved page-builder designs, written by theme_builder
│                                   (designs/<theme>/<page>/manifest.json + <design-id>.json) — not source
│
├── templates/                    Jinja2 templates, server-rendered, Tailwind via CDN (no build step)
│   ├── base.html                  Layout: nav, flash messages, `{{ lurl(...) }}` / `{{ 'key'|_ }}`
│   ├── index.html, login.html
│   ├── admin/                     dashboard.html, settings.html, users.html, roles.html, themes.html,
│   │                               plugins.html — core admin screens (see docs/api.md)
│   └── plugins/<name>/            Each plugin's own templates, mirroring its route names
│
├── uploads/                       Runtime data: files served by the images plugin (not source)
├── logs/                          Runtime data: logs/YYYY-MM-DD.log, one file per day (not source)
├── Corporate.zip                  Stray archive at repo root — verify before relying on it
├── ctx_trace.txt, wsgi_trace.txt  Ad-hoc debug trace output left at repo root — not source
```

## Notes on things that look like duplication but aren't (or might be stale)

- **Two log directories exist**: `logs/` (created by `main.py`, the one actually
  used by the app logger) and `app/core/logs/` (contains a single stale file
  from a prior run with a different working directory). No code in `app/core`
  creates or writes to `app/core/logs/` today — treat it as leftover, not a
  second logging sink.
- **`app/core/models.py`'s `Product`/`Category`/`Page` classes** only matter for
  their `columns` dicts (merged into the schema at boot). Their `.all()` /
  `.find()` / `.insert()` / `.update()` / `.delete()` methods are never called;
  the `products` and `categories` plugins do their own SQL directly against
  `self.db`. Don't be misled into thinking these are the live data-access layer.
- **`pages` table** is declared in `app/core/schema.py` and `app/core/models.py`
  but no route, plugin, or template reads or writes it — it's scaffolded and
  currently dead. `admin/roles.html`'s permission section list also includes a
  `"pages"` entry with nothing behind it.
- **Root-level `Corporate.zip`, `ctx_trace.txt`, `wsgi_trace.txt`** are not part
  of the application; they look like a backup archive and debug traces
  accidentally left in the project root.
