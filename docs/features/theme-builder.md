# Feature: Theme builder

## Relevant files

- `app/plugins/theme_builder/plugin.py` — routes, homepage view override, theme-asset serving
- `app/plugins/theme_builder/widgets.py` — per-theme widget catalog (field-specs + defaults + dynamic data providers)
- `app/plugins/theme_builder/storage.py` — file-based design storage (`designs/<theme>/<page>/`)
- `app/plugins/theme_builder/renderer.py` — single render pipeline shared by the public page and the admin live preview
- `templates/plugins/theme_builder/` — admin UI (`site_theme.html`, `builder.html`) and, under `widgets/<theme>/`, the Jinja partial for each widget type plus `_page_shell.html`

## Responsibilities

1. Lists theme folders under `templates/themes/` and lets an admin pick the
   active one — unlike the old core `/admin/themes` page (still present,
   untouched, now redundant), this selection **actually** changes what `/`
   renders for every visitor.
2. For a theme with a registered widget catalog, provides an
   Elementor-style page builder per **page**: drag widgets from a palette
   onto a canvas of rows, edit each row's settings in a generic
   data-driven form, see changes live in a preview iframe, and save named
   designs. `conspro` has two pages: `home` (overrides `core.index`, i.e.
   `/`) and `product-detail` (overrides the products plugin's
   `/product/<slug>`, i.e. it's rendered once per product, not once for
   the whole site). `creek` only has `home`.
3. Some widgets are dynamic: either a plugin-wide query (`projects` /
   `projects_showcase`, which read `products`/`categories` directly) or
   bound to **the specific entity the page is showing** — on
   `product-detail`, `page_title_banner`/`product_main`/`related_projects`
   render whichever product the visitor is on, via a `page_context` dict
   threaded through the renderer (see below), not through widget settings.

## Data flow

1. `settings.active_theme` (same key the old core route already used) is
   the single source of truth for which theme is live.
2. On `register()`, the plugin saves the previously-registered
   `core.index` view function on `app._theme_builder_orig_index` and
   replaces `app.view_functions["core.index"]` with its own async view.
   Every request to `/` then checks `active_theme`: if it has a widget
   registry, `renderer.render_page()` renders it; otherwise the original
   `index.html` view runs unchanged. `unregister()` restores the original
   function, so disabling the plugin cleanly reverts `/`.
3. A page's content is a **design**: an ordered list of rows, each with
   one box holding a widget type + its settings
   (`{"rows": [{"id", "boxes": [{"id", "widget", "settings"}]}]}`). This
   shape is deliberately one level deeper than currently used (`boxes` is
   already a list) so a future multi-column-per-row UI doesn't need a data
   migration.
4. Designs are files, not DB rows (the user explicitly asked for
   folder-based storage): `designs/<theme>/<page>/<design-id>.json` plus a
   `manifest.json` recording every saved design's id/name and which one is
   active. `designs/` is a runtime-data folder at the project root, a
   sibling of `uploads/`/`logs/` — not under `templates/`.
5. `renderer.render_page()`/`renderer.render_preview()` are the **same**
   function for the public site and the admin builder's iframe — the admin
   never sees a preview that could diverge from what gets published.
6. If no design has been saved yet for a theme/page, `storage.seed_default_design()`
   builds one from every widget's `defaults` (which reproduce the theme's
   original static demo content) and marks it active — switching to a
   theme is never a blank page.
7. Theme static assets (`templates/themes/<theme>/assets/**`) are served
   through `/theme-assets/<theme>/<path:filename>`, guarded against `..`
   traversal the same way `app/plugins/images/plugin.py`'s `_safe_rel`/
   `_abs_path` guard the uploads folder.

## Admin UI: API-driven, no Jinja-injected data

`site_theme.html` and `builder.html` are thin HTML shells — neither
receives `themes`/`catalog`/`design`/`designs` as Jinja context anymore.
Both are `x-data` Alpine components whose `init()` fetches everything from
JSON endpoints on `DOMContentLoaded`, and every subsequent interaction
(activating a theme, switching/loading/saving/deleting a design, editing
settings) goes through `fetch()` — no `<form method="post">` submission and
no full-page navigation. This means the admin routes
(`admin_site_theme`/`admin_builder`) only ever render an (almost) static
shell; the frontend can be redesigned or rewritten independently of the
server as long as it keeps talking to the same JSON endpoints:

- `GET /api/admin/site-theme/themes` → `{themes, active, theme_pages,
  page_labels}` — same data `site_theme.html` used to get as Jinja context.
- `POST /api/admin/site-theme/activate` → JSON body `{theme}`, sets
  `settings.active_theme`, returns `{ok, active}`. Same effect as the old
  `POST /admin/site-theme/activate` form endpoint (kept, unchanged, for
  backward compatibility), just without a redirect/reload.
- `GET /api/admin/site-theme/builder/<theme>/<page>` → `{catalog, design,
  designs, needs_sample_product}` — the builder's bootstrap call, replacing
  what `admin_builder` used to inject via `{{ ... |tojson }}`. Seeds a
  default design the same way the old route did if none is active yet.
- The existing `.../designs`, `.../designs/<id>`, `.../designs/<id>/activate`,
  `.../designs/<id>/delete`, and `.../preview` routes were already
  JSON/fetch-based (unchanged by this refactor) — the builder UI keeps
  using them as-is.

One consequence for `builder.html`: the widget palette can no longer be
server-rendered Jinja (`{% for w in catalog %}`) since the catalog now
arrives after page load via `fetch()`. It's built with a small
`renderPalette()` that sets `paletteList.innerHTML` from a plain JS
template string — **not** an Alpine `x-for` — to stay consistent with the
"no live Alpine directives on the SortableJS-cloned `<li>` nodes" fix
documented below.

## Widget catalog

**conspro / home**: `header`, `hero_slider`, `welcome_intro`,
`services_showcase`, `counters`, `projects` (dynamic), `process_steps`,
`team`, `testimonials`, `news`, `sponsors_subscribe`, `footer` — one per
section of the original `templates/themes/conspro/home.html` (+ its
separate `haeder.html`/`footer.html`).

**conspro / product-detail**: `header`, `sponsors_subscribe`, `footer`
(literally the same widget-def dict objects reused from the `home`
registry — see `EXTRA_PAGE_REGISTRIES` in `widgets.py`), plus three new
ones bound to whichever product the page is showing:
`page_title_banner` (admin sets bg image/breadcrumb labels; the `<h1>`
itself always shows `product.name`), `product_main` (image, description,
and — if the product's `extra` JSON column has been populated — a 4-column
info grid built from its keys/values; nothing here is admin-editable, it's
pulled live), `related_projects` (dynamic: other published products,
same category preferred, current product excluded).

**creek / home**: `header`, `hero_slider`, `cta_banner`, `services_grid`,
`about_history`, `running_projects`, `counters`, `projects_showcase`
(dynamic), `cta_quote`, `team`, `contact_form`, `news_posts`,
`testimonials`, `clients_logos`, `footer`.

Every widget has a `fields` list (`text`/`textarea`/`image`/`url`/
`number`/`repeater`) that drives a **generic** settings form in
`builder.html` — there is no per-widget hand-written form.

### Adding a page (not just a theme)

`WIDGET_REGISTRIES[theme]` only ever holds a theme's `home` widgets (kept
flat, unchanged from the single-page version of this feature, to avoid
touching ~700 already-working lines). Any other page's widgets go in
`EXTRA_PAGE_REGISTRIES[theme][page]` instead, with matching entries in
`EXTRA_ROW_ORDER[theme][page]`. Always go through `get_registry(theme,
page)` / `default_row_order(theme, page)` / `pages_for_theme(theme)` —
never read `WIDGET_REGISTRIES`/`DEFAULT_ROW_ORDER` directly, since for
`page != "home"` the data actually lives in the `EXTRA_*` dicts.

A non-`home` page needs a **public route to override** and, if any widget
is bound to a specific entity (like a product), a `page_context` dict for
the renderer:
- `renderer.render_row_box/render_rows/render_page/render_preview` all
  accept an optional `page_context` dict; when set, its keys (e.g.
  `product`) are spread as extra top-level Jinja variables into **every**
  widget on that page, dynamic-flagged or not — a widget that doesn't care
  just ignores the unused variable.
- `plugin.py`'s `_public_product_detail(slug)` builds `page_context` from
  a real product (looked up via a **soft dependency** on the `products`
  plugin instance, `self.app.core.plugins.plugins.get("products")` — same
  pattern `app/core/decorators.py` already uses for `i18n`) and overrides
  `app.view_functions["plugin_products.public_page"]`, guarded on that
  endpoint already existing (i.e. only if `products` is enabled and
  discovered before `theme_builder` — alphabetical plugin-dir order
  already guarantees this).
- The admin builder can't know "which product" while editing, so for a
  page whose widgets need one, `admin_builder` passes
  `needs_sample_product=True` to `builder.html`, which then fetches
  `/api/products` (already-public products JSON API) to populate a
  "پیش‌نمایش با کدام محصول؟" picker; the chosen slug rides along in the
  `/preview` POST body as `sample_product_slug`, and `admin_preview`
  builds the same kind of `page_context` from it.

## Known simplifications (deliberate, not oversights)

- The original theme's Revolution Slider (`templates/themes/conspro/slider.html`)
  is a browser-frozen DOM snapshot of a paid jQuery plugin, not editable
  source — `hero_slider` is a simpler from-scratch slider (image/title/
  text/button per slide, owl.carousel rotation) styled with the same
  `theme-btn` classes instead of a Revolution Slider re-implementation.
- The `image` field type is a plain URL text input, not a media-library
  picker.
- Header menu / footer links are flat `{label, url}` lists — no nested
  submenus in this phase.
- Core's own `/admin/themes` page (`app/core/routes.py`) is left exactly
  as-is; `/admin/site-theme` from this plugin is the functional
  replacement. This is a deliberate minimal-diff choice, not an oversight
  — see [api.md](../api.md).

## Things that must not break

- `renderer.render_page`/`render_preview` must stay the only code path
  that turns a design into HTML — duplicating rendering logic between the
  admin preview and the public page would let them silently drift apart.
- The `settings` dict passed into every widget template must never use a
  repeater/list field key that collides with a Python `dict` method name
  (`items`, `keys`, `values`, `get`, ...) — Jinja's `foo.bar` resolves via
  `getattr` first, so `settings.items` silently returns the bound
  `dict.items` method instead of a stored `"items"` key and blows up with
  `TypeError: 'builtin_function_or_method' object is not iterable`. This
  bit us once during development (field was renamed to `entries`); the
  same repo's `main.py` has a `safe_length` Jinja filter working around
  the identical class of bug for `|length`.
- `app.view_functions["core.index"]` must only ever be reassigned, never
  deleted — `unregister()` depends on `app._theme_builder_orig_index`
  still being the real original view function.

## Known pre-existing bug this feature ran into (not caused by it, not fixed by it)

`PluginManager.set_enabled()` (`app/core/plugin_manager.py`) calls
`plugin.register()` — which calls `app.register_blueprint(...)` — live,
from inside the `/admin/plugins/toggle` request handler. Flask 2.3+ raises
`AssertionError`-style `RuntimeError: The setup method 'register_blueprint'
can no longer be called...` if the app has already served at least one
request, which in practice it always has by the time an admin toggles a
plugin on. **Enabling any previously-disabled plugin from `/admin/plugins`
on an already-running server currently fails.** The workaround used during
this feature's development and verification: set the `plugins.enabled`
row directly (or enable it before the very first request) and restart the
process, so `PluginManager.activate_enabled()` runs the registration at
boot instead. This is a pre-existing gap in core, not specific to
`theme_builder` — flagged here rather than silently patched.
