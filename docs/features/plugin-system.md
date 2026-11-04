# Feature: Plugin system

## Relevant files

- `app/core/plugin_manager.py` — `PluginManager` (discover, activate, toggle)
- `app/core/base_plugin.py` — `BasePlugin` base class
- `app/plugins/<name>/plugin.py` — one per plugin, each exposing `class Plugin(BasePlugin)`
- `app/__init__.py` — wires discovery/schema/activation into the boot sequence

## Responsibilities

Turns every feature area (products, categories, i18n, images, cache,
tracking, plus the trivial `sample_hello` example) into an independently
enable/disable-able unit with its own routes, schema, and templates,
without core code needing to know about any specific plugin.

## Data flow

1. `PluginManager.discover()` walks `app/plugins/*/`, imports
   `app.plugins.<name>.plugin`, and instantiates `Plugin(app, db)` for every
   directory that has a `plugin.py` and doesn't start with `_`. A failure to
   import or instantiate one plugin is logged and skipped — it does not
   abort startup.
2. Every discovered plugin (enabled or not) gets `declare_schema(schema)`
   called once during boot, then `schema.sync()` applies the merged schema.
   `maybe_run_migration()` runs once after that.
3. `PluginManager.activate_enabled()` reads the `plugins` table
   (`name`, `enabled`) via each plugin's `is_enabled()` and calls
   `plugin.register()` for the ones that are enabled — this is what actually
   attaches Blueprints / hooks to the live Flask `app`.
4. Toggling a plugin from `/admin/plugins/toggle` calls
   `PluginManager.set_enabled()`, which flips the DB row and calls
   `register()` or `unregister()` on the already-instantiated plugin object
   — no process restart required, provided the plugin implements
   `unregister()` cleanly (most just no-op; `tracking` actually removes its
   Blueprint and view functions).

## The `BasePlugin` contract

| Method | When called | Required? |
|---|---|---|
| `__init__(self, app, db)` | At discovery time | Provided by `BasePlugin`; override only to do one-time setup (see `tracking`, `images`) |
| `is_enabled() -> bool` | Before `register()`, and in `/admin/plugins` listing | Default: reads `plugins.enabled`. Override to auto-enable on first run (see `tracking`) |
| `declare_schema(self, schema)` | Once at boot, before `schema.sync()` | Optional — only if the plugin owns tables/columns |
| `maybe_run_migration(self)` | Once at boot, after `schema.sync()` | Optional — for changes the declarative schema API can't express (indexes, type changes) |
| `register(self)` | When enabled (at boot or via toggle) | Required if the plugin has any routes/hooks |
| `unregister(self)` | When disabled via toggle | Optional; default no-op |
| `get_admin_entry(self)` | Building the `/dashboard` tile list | Uses the class-level `admin_entry` dict unless overridden |
| `respond(self, data, template=None, **ctx)` | From within a route | Returns JSON if `output_type == "json"`, else renders `template` with `data` merged in |
| `get_setting`/`set_setting` | Anywhere | Thin wrapper over the core `settings` key/value table, namespaced by nothing — plugins share the same flat key space, so prefix your keys (e.g. `tracking_exclude_paths`) |

## Important rules

- **Discovery happens for every plugin directory, whether enabled or not**
  — including schema declaration. A disabled plugin's tables still get
  created. Only `register()` (routes/hooks) is gated by the enabled flag.
- **`declare_schema` calls run in directory-listing (alphabetical) order,
  after core models.** If your plugin redeclares a column that a core model
  or another plugin already declared with a different type/constraint,
  your version wins for a fresh database (see [database.md](../database.md#schema-merge-gotchas)
  for the concrete `categories.slug` example). Avoid redeclaring a column
  you don't own unless you mean to change its definition.
- **Two plugins should not silently fight over the same table** unless one
  is deliberately extending the other's schema (as `products`/`categories`
  extend the core models). Prefer `register_columns` for additive fields.
- Blueprint names must be globally unique (`plugin_<name>`, or
  `plugin_<name>_admin` for a second blueprint like `tracking` uses) —
  Flask raises on a duplicate blueprint name.

## Dependencies

- Depends on `app/core/database.py` (`Database`), `app/core/cache.py`
  (`app.cache`), and `app/core/decorators.py` (`login_required`/
  `admin_required`) — none of these are optional for a plugin that needs
  DB access, caching, or route protection.
- `app/core/decorators.py`'s `_localized_url` helper looks up
  `current_app.core.plugins.plugins.get("i18n")` directly — the decorators
  module has a soft runtime dependency on the `i18n` plugin's
  `url_for_lang` method, guarded by `hasattr`/`try/except` so it degrades
  gracefully when `i18n` isn't installed/enabled.

## Things that must not break

- `PluginManager.discover()` must keep catching and logging per-plugin
  import errors rather than propagating them — a broken plugin must not be
  able to take down the whole app at boot.
- New plugins **must not assume `/admin/*` routes are automatically
  protected** — see the auth gap called out in [CLAUDE.md](../../CLAUDE.md#known-gap-several-admin-routes-have-no-auth-check)
  and [api.md](../api.md). Copy the `i18n`/`tracking` pattern
  (`from app.core.decorators import admin_required`, then `@admin_required`
  on each admin view) rather than the `products`/`categories`/`images`/`cache` pattern.
