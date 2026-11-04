# Architecture

## Stack

- **Flask** with async view functions (`flask[async]`), run via Flask's
  built-in dev server (`app.run(..., debug=True, use_reloader=True)`) —
  there is no WSGI/ASGI production server configured anywhere in this repo.
- **MySQL** via `mysql-connector-python`, accessed through a small async
  wrapper (`Database`) that runs blocking driver calls in a thread pool
  (`asyncio.to_thread`) on top of a `MySQLConnectionPool`.
- **Jinja2** templates, **Tailwind CSS via CDN** script tag — no frontend
  build step, no bundler, no JS framework. A couple of admin pages
  (tracking) render an empty shell and fetch JSON client-side.
- **Plugin architecture**: everything beyond core auth/settings/users is a
  self-contained plugin under `app/plugins/`.

## Boot sequence (`app/__init__.py: create_app`)

1. Build the Flask app; template/static folders come from `.env`
   (`TEMPLATES_DIR`, `ASSETS_DIR`).
2. Construct `Database()`, `AuthManager(db)`, `PluginManager(app, db)`,
   `PluginCache` (via `init_cache`); attach them all as `app.core.{db,auth,plugins,cache}`.
3. `register_core_routes(app)` — registers the `core` Blueprint (see
   [api.md](api.md)).
4. `AuthManager.ensure_admin()` — inserts a hidden `administrator` user if
   none exists.
5. **Core schema pass**: build a `SchemaManager`, call `.register(schema)`
   on every model in `app/core/models.py::ALL_MODELS` (`Product`,
   `Category`, `Page`). This only registers table/column *definitions* in
   memory — nothing is synced to MySQL yet.
6. `plugins.discover()` — imports `app.plugins.<name>.plugin` for every
   subdirectory of `app/plugins/` that has a `plugin.py`, instantiates
   `Plugin(app, db)`, and stores it in `plugins.plugins[name]`. This runs
   for **every** plugin directory found, regardless of whether it's enabled.
7. For every discovered plugin, call `plugin.declare_schema(schema)` if
   defined — plugins add/extend tables here (e.g. `products`,
   `product_images`, `categories`, `i18n_languages`, `images`,
   `tracking_visitors`, ...).
8. `schema.sync()` — now the merged table/column definitions are actually
   applied to MySQL: `CREATE DATABASE IF NOT EXISTS`, then for each table
   either `CREATE TABLE IF NOT EXISTS` (new table) or one `ALTER TABLE ...
   ADD COLUMN` per column that doesn't exist yet on an existing table. See
   [database.md](database.md) for why table/column *order* here matters.
9. For every discovered plugin, call `plugin.maybe_run_migration()` if
   defined — a hook for changes `SchemaManager` can't express declaratively
   (unique indexes, column type changes). Used by `i18n` (adds a unique key)
   and `tracking` (converts legacy `TIMESTAMP` columns to `VARCHAR` for
   Jalali date strings, then warms its request-path caches).
10. `plugins.activate_enabled()` — for each plugin, `await plugin.is_enabled()`
    (reads the `plugins` table); if true, call `plugin.register()`, which
    wires the plugin's Blueprint(s) and any `before_request`/`after_request`
    hooks onto the live app.

Steps 5–9 all run inside `with app.app_context():` blocks because they use
`asyncio.run(...)` internally and some plugin code (`url_for`, `current_app`)
needs an app context.

## Plugin lifecycle

See [features/plugin-system.md](features/plugin-system.md) for the full
contract. In short: a plugin is a class `Plugin(BasePlugin)` in
`app/plugins/<name>/plugin.py`. `PluginManager` owns discovery and
enable/disable; `is_enabled()` is a DB-backed check (row in `plugins` table)
that plugins can override (the `tracking` plugin overrides it to
auto-enable itself on first boot). Toggling a plugin from
`/admin/plugins/toggle` calls `register()`/`unregister()` on the live
instance — no process restart needed for most plugins.

## Request flow

1. **WSGI layer** — if the `i18n` plugin is enabled, its wrapper around
   `app.wsgi_app` inspects the first URL segment before Flask does any
   routing. If it matches a known locale file, the segment is stripped from
   `PATH_INFO` and stashed in a custom WSGI environ header
   (`HTTP_X_I18N_LANG` / `HTTP_X_I18N_PREFIX`) so it survives into the
   Flask request. This has to happen at the WSGI level — see
   [features/i18n.md](features/i18n.md) for why a `before_request` hook is too late.
2. **`before_request`** — `i18n` sets `g.lang` / `g.lang_prefix` from the
   WSGI-injected header (or derives it from the path as a fallback).
   `tracking`'s `before_request` is currently a no-op placeholder.
3. **View function** — resolved by Flask's router against the
   *prefix-stripped* path, so plugin routes never need to know about
   language prefixes.
4. **`after_request`** — `tracking` (if enabled) records the request: it
   reads request/response metadata synchronously (headers, cookies, a
   cached GeoIP/visitor-id lookup) and pushes a small dict onto an
   in-process `queue.Queue`; a dedicated daemon thread drains that queue
   into MySQL so the response is never blocked on a DB write. See
   [features/tracking.md](features/tracking.md).
5. **Context processors** — `core.inject_settings` loads the `settings`
   table into every template context (`settings`, `current_user`); `i18n`
   injects `current_lang` / `lang_prefix`.

## Caching model

`app.cache` (a `PluginCache`, see `app/core/cache.py`) is a single
in-process dict guarded by a `threading.Lock`, namespaced by a `<namespace>:`
key prefix, with per-entry TTL and hit/miss stats surfaced at
`/admin/cache`. It is **not** shared across processes — running multiple
worker processes (e.g. behind gunicorn with `--workers > 1`) would give
each worker its own independent cache, silently breaking any invalidation
logic that assumes a single shared cache. As shipped, `main.py` only ever
runs a single process, so this doesn't currently bite, but it's a hazard if
the deployment model changes.

Every plugin that caches is responsible for invalidating its own keys after
a write — there's no automatic invalidation-on-write. See
[features/cache.md](features/cache.md) and the `products`/`i18n`/`tracking`
plugins for the invalidate-then-warm pattern they each use.

## i18n URL routing (summary)

Language is derived **only** from the URL prefix (`/en/...`), never from a
cookie, session, or `Accept-Language` header, and this is deliberate (see
comments throughout `app/plugins/i18n/plugin.py`). The plugin overrides the
Jinja global `url_for` with a language-aware version and exposes `lurl()`
for the same purpose; `t()` / the `_` Jinja filter translate a dotted key
against the active language, falling back to the Persian source file
(`app/plugins/i18n/locales/fa.json`) and then to the key itself. Full
details in [features/i18n.md](features/i18n.md).

## Async / threading model

- Route handlers are `async def`; `Database.query`/`execute` offload the
  actual (blocking) `mysql-connector-python` call to a thread via
  `asyncio.to_thread`, reusing a pooled connection.
- A few call sites need a DB value from **synchronous** code (e.g. Jinja
  filters, the WSGI wrapper, `url_value_preprocessor`-style helpers) where
  there is no `await` available. These use `asyncio.run(...)` when no loop
  is running, or spin up a one-off `ThreadPoolExecutor` to run
  `asyncio.run` on a separate thread when already inside a loop (see
  `core/routes.py::inject_settings` and `i18n`'s `_run_sync`). This is a
  workaround, not a general pattern — prefer plain `await` in new async
  view code.
- `tracking` runs its own dedicated background thread (`tracking-writer`)
  with its own event loop, fed by a thread-safe `queue.Queue`, so its DB
  writes never share the request's event loop.


## Update: headless-frontend additions

`create_app()` now also installs, before registering routes: `init_revalidate(app)` (`app.revalidate`),
`install_public_api(app)` (JSON error handlers, CORS, ETag/Cache-Control for `/api/public/*`, `app.public_providers`)
and `install_template_helpers(app)`. `PluginManager.activate_enabled()` first calls `ensure_defaults()`: a plugin with
`auto_enable = True` and no row in `plugins` is enabled (existing rows are never touched). Content plugins register
`search` / `sitemap` / `home` providers in `app.public_providers`; `public_api` aggregates them. Details:
[features/headless-api.md](features/headless-api.md).
