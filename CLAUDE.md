# CLAUDE.md

Guidance for AI agents (and humans) working in this repository.

## What this is

A plugin-based CMS backend built on **Flask (async views)** with **MySQL**
(via `mysql-connector-python`, connection-pooled, offloaded to threads with
`asyncio.to_thread`). No JS build step — Tailwind is loaded from a CDN,
templates are server-rendered Jinja2, and a few admin pages (tracking) fetch
JSON client-side with plain `fetch()`.

Full docs live in [PROJECT_MAP.md](PROJECT_MAP.md) and `docs/`:
- [docs/architecture.md](docs/architecture.md) — boot sequence, plugin lifecycle, request flow, caching, i18n routing
- [docs/database.md](docs/database.md) — tables, columns, schema-merge behavior, known gotchas
- [docs/api.md](docs/api.md) — every route, grouped by blueprint
- `docs/features/*.md` — one file per feature area (products, categories, i18n, images, tracking, cache, auth, plugin system, **page-builder**)

## Running it

```
pip install -r requirements.txt
python main.py                    # runs on http://127.0.0.1:5000, debug=True, reloader on
python main.py resetpass <user>   # CLI: interactively reset a user's password
```

Config comes from `.env` at the project root (`DB_HOST`, `DB_PORT`, `DB_USER`,
`DB_PASSWORD`, `DB_NAME`, `DB_POOL_SIZE`, `SECRET_KEY`, `TEMPLATES_DIR`,
`ASSETS_DIR`, `ASSETS_DIR_Max_Size`, `CACHE_TTL`). New optional variables (CORS, revalidate webhook, documents, SMTP, rate limits) are listed in `.env.example`. `.env` in this repo
contains live credentials — never print/echo its contents, never commit
secrets elsewhere.

Tests: `python -m unittest discover -s tests -v` (see "Headless frontend" below for the DB safety rule).
There is no linter config in this repo.

## Architecture in one paragraph

`main.py` sets up daily-rotating file logging and calls `app.create_app()`.
`create_app()` builds the Flask app, a `Database` (connection pool), an
`AuthManager`, a `PluginManager`, and a `PluginCache`, then: registers core
routes → ensures a hidden admin user exists → syncs the **core** schema
(`app/core/models.py` + `app/core/schema.py`) → discovers plugins under
`app/plugins/*/plugin.py` → lets every discovered plugin declare its own
tables/columns → syncs the **full** merged schema → runs each plugin's
post-sync migration hook → activates only the plugins marked `enabled` in
the `plugins` table (registers their Blueprints/hooks). See
[docs/architecture.md](docs/architecture.md) for the full sequence.

## Conventions to follow

- **Views are `async def`.** DB access goes through `await db.query(...)` /
  `await db.execute(...)` (see [app/core/database.py](app/core/database.py)). Never call blocking
  `mysql.connector` directly from a route.
- **New features are plugins**, not core code. A plugin is a directory
  under `app/plugins/<name>/` with a `plugin.py` exposing `class Plugin(BasePlugin)`.
  See [docs/features/plugin-system.md](docs/features/plugin-system.md) before adding one.
- **Schema changes are declarative and additive.** Add/extend columns via
  `declare_schema(self, schema)` using `schema.register_table(...)` /
  `schema.register_columns(...)`. `SchemaManager` only ever does
  `CREATE TABLE IF NOT EXISTS` and `ADD COLUMN` for *missing* columns — it
  never alters an existing column's type or drops anything. If you need a
  type change, index, or constraint, do it in `maybe_run_migration()`
  (called once after schema sync), following the pattern in
  `app/plugins/i18n/plugin.py` or `app/plugins/tracking/plugin.py`.
- **Cache invalidation is manual and namespaced.** Each plugin owns a
  `PluginCache` namespace (`self.app.cache`) and must invalidate its own
  keys after writes — nothing expires the cache for you except TTL. See
  [docs/features/cache.md](docs/features/cache.md).
- **i18n: language is derived ONLY from the URL prefix** (`/en/...`), never
  from a cookie or session. This is intentional and repeated throughout
  `app/plugins/i18n/plugin.py` — do not "fix" it into session-based
  language storage. Build language-aware links with the `lurl()` Jinja
  global, not raw `url_for()`. See [docs/features/i18n.md](docs/features/i18n.md).
- **Admin routes are gated by `@admin_required`** (role == `administrator`
  in the session), not by the `roles`/`permissions` table — that table is
  populated by `/admin/roles` but nothing ever reads it back into a
  session. Don't assume `AuthManager.can()` is wired into any route; it
  isn't. See [docs/features/auth.md](docs/features/auth.md).
- **Plugins with `auto_enable = True`** get an enabled `plugins` row on a fresh database (an existing row is
  never touched); all new content plugins use it.

## Admin panel = Vuexy shell + `/api/admin/*` (migration in progress)

New admin features are JSON endpoints guarded by `@admin_api` (`app/core/admin_api.py`: 401/403 JSON, CSRF header on
non-GET, `{"ok":…}` envelope) plus a page JS under `assets/admin-ui/app/`; entities get both for free from
`register_admin`. Contract, endpoint list and what is still on old HTML pages: [docs/admin-api.md](docs/admin-api.md).
Page routes stay `@admin_required` (302 to `/login`).

## Admin auth (the old "open routes" gap is closed)

`products`, `categories`, `images` and `cache` admin routes (plus `POST /api/cache/clear/<ns>` and
`GET /api/cache/stats`) are now `@admin_required`, as is every admin route added for the headless
frontend. Public reads stay open on purpose: `/api/products*`, `/api/categories*`, `/api/i18n/*`,
`/assets/uploads/*`, `/api/public/*`. `tests/test_api.py::AuthOnAdminRoutes` pins this; any new
`/admin/*` route must carry `@admin_required` (the entity engine's `register_admin` already does).

## Headless frontend (Next.js) support

The frontend consumes `/api/public/*` (contract: [docs/frontend-api.md](docs/frontend-api.md), regenerate it with
`python scripts/build_frontend_doc.py` on a throw-away DB; backend notes:
[docs/features/headless-api.md](docs/features/headless-api.md)). Rules when touching it:

- Translatable content is JSON in `<field>_i18n` (`{"fa": …, "en": …}`); legacy single-language columns mirror `fa`.
- New content entities are declared with the engine in `app/core/entity.py` (`Entity`/`Field`/`Child` +
  `register_admin`) — don't hand-roll forms. "Absent form field = untouched; present-but-empty = cleared."
- Public handlers use `public_get` + `ctx.db.fetch` (DB error ⇒ 503, never an empty list); every error under
  `/api/public/` is the JSON envelope; nothing internal (inquiry data, `sha256`, drafts, prices) may leak.
- Every content write must call `app.revalidate.notify(*tags)` (the engine does) — it clears the public API cache
  and pings the frontend.
- Keep `/api/products`, `/api/categories`, `/api/i18n/*`, `/product/<slug>` byte-compatible in shape.
- Draft preview: detail handlers of products/projects/articles call `preview_target(kind)` (signed `?preview=` token, never cached);
  `site_settings` flags (`maintenance`, `features`, `track`, `catalog_mode`) and CAPTCHA are described in
  [docs/features/headless-api.md](docs/features/headless-api.md).
- Tests: `python -m unittest discover -s tests -v`. `tests/test_api.py` writes to the configured DB and refuses to
  run unless `DB_HOST` is loopback — **never point it at the live database**. `scripts/seed_demo.py [--remove]`
  creates/removes sample content; `scripts/smoke_public_api.py [--base URL]` checks every endpoint's shape.

## Things that must not break

- The i18n WSGI wrapper (`app/plugins/i18n/plugin.py`, `_i18n_wsgi`) strips
  the language prefix from `PATH_INFO` *before* Flask's router runs. This
  must stay a WSGI-level rewrite, not a `before_request` hook — Werkzeug
  caches `PATH_INFO` at request-object creation, so a `before_request`
  rewrite runs too late.
- `images` plugin path helpers (`_safe_rel`, `_abs_path` in
  `app/plugins/images/plugin.py`) block `..` path traversal outside
  `uploads/`. Any new file-manager route must reuse them, not roll its own
  path joining.
- The hidden `administrator` user is auto-created (`admin` / `admin123`) on
  first boot by `AuthManager.ensure_admin()` if no administrator row
  exists. Change this password immediately on any real deployment; don't
  remove the bootstrap without another way to create the first admin.
- Category/product **slug uniqueness for categories is enforced only at
  the application level** (`_unique_slug` in the categories plugin), not by
  a DB constraint — see [docs/database.md](docs/database.md#schema-merge-gotchas) for why.











## Context and Token Efficiency

Follow these rules to minimize unnecessary context usage.

### Before modifying code

1. Read this CLAUDE.md first.
2. Read PROJECT_MAP.md only when you need to understand project structure.
3. Identify the specific feature involved in the task.
4. Read only the relevant file from docs/features/.
5. Inspect only the source files directly related to the requested change.
6. Do NOT scan or read the entire repository unless the task genuinely requires it.
7. Do NOT read unrelated plugins or features.
8. Prefer targeted searches for symbols, routes, functions, classes, and database tables.

### Documentation priority

Use documentation as the first source of architectural context:

CLAUDE.md
↓
PROJECT_MAP.md
↓
docs/architecture.md
↓
docs/features/<relevant-feature>.md
↓
relevant source files

Do not load all documentation when only one feature is involved.

### Coding behavior

- Reuse existing code before creating new abstractions.
- Do not duplicate existing functionality.
- Do not modify unrelated files.
- Do not refactor unrelated code.
- Preserve existing APIs and behavior unless explicitly requested.
- Before changing architecture, inspect the existing implementation.
- Keep changes minimal and focused.

### After modifying code

1. Review the changed files.
2. Check imports and references.
3. Check for obvious syntax/runtime issues.
4. Review the final diff.
5. Do not modify unrelated files.