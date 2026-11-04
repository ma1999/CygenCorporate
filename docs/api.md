# API / Routes

All routes are registered as Flask Blueprints. When the `i18n` plugin is
enabled, every path below is also reachable prefixed with an active
language code (e.g. `/en/admin/products`) — see [features/i18n.md](features/i18n.md).
Routes returning JSON do so via `BasePlugin.respond()`, which returns JSON
when the plugin's `output_type == "json"` (none currently set this) or a
rendered template otherwise — the `/api/*` routes call `jsonify`/`respond`
directly regardless of `output_type`.

> **Auth legend:** 🔒admin = `@admin_required` (must be logged in AND
> `role == "administrator"`). 🔑login = `@login_required` (any logged-in
> user). **none** = no decorator at all — reachable by anyone,
> unauthenticated, despite living under `/admin/...`. This is called out
> explicitly per section below because it's easy to assume `/admin/*`
> implies protection in this codebase, and for several plugins it does not.

## Core (`app/core/routes.py`, Blueprint `core`, no URL prefix)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/` | none | Home page (`index.html`) — **overridden at runtime** by the `theme_builder` plugin when enabled, see below |
| GET/POST | `/login` | none | Login form / submit |
| GET | `/logout` | none | Clears session |
| GET | `/dashboard` | 🔑login | Aggregates each enabled plugin's `admin_entry` into tile links |
| GET/POST | `/admin/settings` | 🔒admin | Site title/meta/theme/default-pages key-value settings |
| GET | `/admin/users` | 🔒admin | List non-hidden users |
| POST | `/admin/users/create` | 🔒admin | Create a user (`INSERT IGNORE`, silently no-ops on duplicate username) |
| POST | `/admin/users/<int:uid>/delete` | 🔒admin | Delete a user (cannot delete an `administrator` role row) |
| GET/POST | `/admin/roles` | 🔒admin | Create/update a named permission set — **stored but never enforced**, see [features/auth.md](features/auth.md) |
| GET | `/admin/themes` | 🔒admin | Lists subdirectories of `templates/themes/` |
| POST | `/admin/themes/activate` | 🔒admin | Sets `settings.active_theme`, read back only by `admin/themes.html` to highlight the active choice — no code path actually switches which template folder is rendered based on it. **Superseded by `theme_builder`'s `/admin/site-theme` below**, which sets the same setting key but actually applies it; this old page is left in place unchanged and is now a harmless, redundant UI. |
| GET | `/admin/plugins` | 🔒admin | List discovered plugins + enabled state |
| POST | `/admin/plugins/toggle` | 🔒admin | Enable/disable a plugin (calls its `register()`/`unregister()` live) |

## `products` plugin (Blueprint `plugin_products`)

All `/admin/products*` routes are now `@admin_required` (the old "no auth" gap was closed for the headless-frontend work).
Create/edit/delete use the generic multilingual form (`app/core/entity.py`); `/api/products*` and
`/product/<slug>` are public and unchanged in shape. See [features/products.md](features/products.md) and
[features/headless-api.md](features/headless-api.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/admin/products` | 🔒admin | List (up to 200) with image counts |
| GET/POST | `/admin/products/create` | 🔒admin | Create form / submit |
| GET/POST | `/admin/products/<int:pid>/edit` | 🔒admin | Edit form / submit |
| POST | `/admin/products/<int:pid>/delete` | 🔒admin | Delete product + its images |
| POST | `/admin/products/<int:pid>/images/add` | 🔒admin | Attach an image URL to a product |
| POST | `/admin/products/images/<int:img_id>/delete` | 🔒admin | Remove one product image |
| GET | `/api/products` | none | Published products list (cached) |
| GET | `/api/products/<int:pid>` | none | Single product; 404 unless `status == "published"` |
| GET | `/product/<slug>` | none | Public product page with JSON-LD `Product` schema — **overridden at runtime** by `theme_builder` when the active theme has a `product-detail` page design, see below |

## `categories` plugin (Blueprint `plugin_categories`)

All `/admin/categories*` routes are now `@admin_required`; create/edit use the generic multilingual form, and every
write also clears the `products` cache. `/api/categories*` and `/category/<slug>` stay public. See
[features/categories.md](features/categories.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/admin/categories` | 🔒admin | List grouped by parent |
| GET/POST | `/admin/categories/create` | 🔒admin | Create form / submit |
| GET/POST | `/admin/categories/<int:cid>/edit` | 🔒admin | Edit form / submit |
| POST | `/admin/categories/<int:cid>/toggle` | 🔒admin | Flip `is_active` |
| POST | `/admin/categories/<int:cid>/delete` | 🔒admin | Soft-delete (+ its children) |
| POST | `/admin/categories/purge` | 🔒admin | Hard-delete soft-deleted, unused rows |
| GET | `/api/categories` | none | Active category tree (parent → children) |
| GET | `/api/categories/<slug>` | none | One category + its children |
| GET | `/category/<slug>` | none | Public category page with JSON-LD schema |

## `i18n` plugin (Blueprint `plugin_i18n`)

Admin routes are properly gated with `@admin_required`; public/API routes
are intentionally open (they serve translation data to any page).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/admin/i18n` | 🔒admin | List languages + translated-key counts |
| POST | `/admin/i18n/default/fa` | 🔒admin | Force Persian back to default |
| GET/POST | `/admin/i18n/create` | 🔒admin | Add a language |
| GET/POST | `/admin/i18n/<code>/edit` | 🔒admin | Edit a language's metadata / default flag |
| POST | `/admin/i18n/<code>/delete` | 🔒admin | Delete a language + its translations (blocked for `fa`) |
| GET/POST | `/admin/i18n/<code>/translate` | 🔒admin | Per-key translation editor |
| GET | `/admin/i18n/<code>/export` | 🔒admin | Download merged translations as JSON |
| POST | `/admin/i18n/<code>/seed` | 🔒admin | Copy every source string into a language as an untranslated starting point |
| GET | `/api/i18n/languages` | none | Active languages + current request's language |
| GET | `/api/i18n/translate/<code>` | none | Merged translation dict for one language |
| GET | `/lang/<code>` | none | Redirects to the `next` path under `/<code>/...` |

## `images` plugin (Blueprint `plugin_images`)

All `/admin/images*` routes (and the new `GET /admin/media/browse` picker API) are now `@admin_required`;
`/assets/uploads/*` stays public (`Cache-Control: public, max-age=86400`, SVG served with a sandbox CSP).
Path-traversal is guarded (`_safe_rel`/`_abs_path`). See [features/images.md](features/images.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/admin/images` | 🔒admin | File-manager browser (search/filter/recursive) |
| POST | `/admin/images/folder/create` | 🔒admin | Create a folder |
| POST | `/admin/images/upload` | 🔒admin | Upload one or more files (enforces `ASSETS_DIR_Max_Size` quota) |
| POST | `/admin/images/folder/rename` | 🔒admin | Rename a folder (updates DB mirror paths) |
| POST | `/admin/images/rename` | 🔒admin | Rename a file |
| POST | `/admin/images/delete` | 🔒admin | Delete one or more files/folders |
| POST | `/admin/images/move` | 🔒admin | Move files/folders to another folder |
| GET/POST | `/admin/images/edit` | 🔒admin | View/save a text file (`.txt`, `.md`, `.css`, `.js`, `.json`, `.html`) inline |
| GET | `/assets/uploads/<path:filename>` | none | Serves an uploaded file (intentionally public — these are site assets) |

## `cache` plugin (Blueprint `plugin_cache`)

All routes below are now `@admin_required`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/admin/cache` | 🔒admin | Dashboard: per-namespace hit/miss stats |
| POST | `/admin/cache/clear/<namespace>` | 🔒admin | Clear one plugin's cache namespace |
| POST | `/admin/cache/clear` | 🔒admin | Clear the entire cache |
| POST | `/admin/cache/ttl` | 🔒admin | Change the default TTL |
| GET | `/api/cache/stats` | 🔒admin | Same stats as JSON |
| POST | `/api/cache/clear/<namespace>` | 🔒admin | Same clear, JSON response |

## `tracking` plugin (Blueprints `plugin_tracking_admin`, plus global hooks)

Admin/API routes are properly gated with `@admin_required`. In addition,
every request to the app (unless excluded by the settings-driven rules) is
recorded by global `before_request`/`after_request` hooks — see
[features/tracking.md](features/tracking.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/admin/tracking` | 🔒admin | Dashboard shell (data fetched client-side) |
| GET | `/admin/tracking/visitors` | 🔒admin | Visitors list shell |
| GET | `/admin/tracking/visitor/<int:vid>` | 🔒admin | Visitor detail shell |
| GET | `/admin/tracking/settings` (POST too) | 🔒admin | Edit exclude rules (paths/methods/status/UA/bots) |
| GET | `/api/admin/tracking/dashboard` | 🔒admin | Aggregate counts/breakdowns (cached, write-through updated) |
| GET | `/api/admin/tracking/visitors` | 🔒admin | Paginated visitor list (cached) |
| GET | `/api/admin/tracking/visitor/<int:vid>` | 🔒admin | One visitor + up to 200 recent requests (cached) |

## `theme_builder` plugin (Blueprint `plugin_theme_builder`)

Makes `settings.active_theme` actually take effect on `/`, and provides an
Elementor-style drag/drop builder per page. `conspro` has two pages —
`home` (→ `/`) and `product-detail` (→ products' `/product/<slug>`, one
render per product via a `page_context` dict, see
[features/theme-builder.md](features/theme-builder.md#adding-a-page-not-just-a-theme));
`creek` only has `home`. All admin routes are properly gated with
`@admin_required` (this plugin follows the i18n/tracking pattern, not the
open products/categories/images/cache pattern).

**The admin UI is fully API-driven** (see
[features/theme-builder.md](features/theme-builder.md#admin-ui-api-driven-no-jinja-injected-data)):
`admin_site_theme`/`admin_builder` render near-empty HTML shells and every
piece of data (theme list, catalog, active design, saved designs) is
fetched client-side via the `/api/admin/site-theme/*` routes below;
activating a theme or switching/saving/loading a design never triggers a
full-page navigation.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/admin/site-theme` | 🔒admin | HTML shell — JS fetches theme list from `/api/admin/site-theme/themes` on load |
| GET | `/admin/site-theme/builder/<theme>/<page>` | 🔒admin | HTML shell — JS fetches catalog/design/designs from `/api/admin/site-theme/builder/<theme>/<page>` on load |
| GET | `/api/admin/site-theme/themes` | 🔒admin | JSON `{themes, active, theme_pages, page_labels}` |
| POST | `/api/admin/site-theme/activate` | 🔒admin | JSON body `{theme}` → sets `settings.active_theme`, returns `{ok, active}` (no redirect) |
| GET | `/api/admin/site-theme/builder/<theme>/<page>` | 🔒admin | Builder bootstrap JSON: `{catalog, design, designs, needs_sample_product}` (seeds a default design first time) |
| POST | `/admin/site-theme/activate` | 🔒admin | Old form-post activation (kept for backward compatibility; sets the same setting, then redirects). The admin UI itself now uses the JSON route above instead |
| GET | `/admin/site-theme/builder/<theme>/<page>/designs` | 🔒admin | List saved designs (JSON) |
| POST | `/admin/site-theme/builder/<theme>/<page>/designs` | 🔒admin | Create/update a design; body `{id?, name, rows, set_active?}` |
| GET | `/admin/site-theme/builder/<theme>/<page>/designs/<id>` | 🔒admin | Fetch one saved design (JSON) |
| POST | `/admin/site-theme/builder/<theme>/<page>/designs/<id>/activate` | 🔒admin | Make a previously-saved design the live one |
| POST | `/admin/site-theme/builder/<theme>/<page>/designs/<id>/delete` | 🔒admin | Delete a saved design |
| POST | `/admin/site-theme/builder/<theme>/<page>/preview` | 🔒admin | Body `{rows, sample_product_slug?}` → full rendered HTML for the live-preview iframe (same renderer as the public page; `sample_product_slug` supplies `page_context` on pages that need one) |
| GET | `/theme-assets/<theme>/<path:filename>` | none | Serves `templates/themes/<theme>/assets/...` (traversal-guarded like the `images` plugin) — intentionally public, these are page assets |

## `sample_hello` plugin

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/plugins/hello` | none | Reference example endpoint — returns `{"plugin": "sample_hello", "message": "..."}` |


## Headless-frontend additions

The Next.js frontend uses the **public JSON API** under `/api/public/*` — full reference with real
sample responses: [frontend-api.md](frontend-api.md); implementation notes:
[features/headless-api.md](features/headless-api.md).

Admin screens added (all 🔒admin; list/create/edit/delete(/toggle) generated by `app/core/entity.py` unless noted):

| Path | Plugin |
|---|---|
| `/admin/site-settings` (tabs; one form) | `site_settings` |
| `/admin/brands`, `/admin/product-tags` | `brands`, `products` |
| `/admin/documents/<product\|certification>/<id>` (+ `/create`, `/<doc_id>/save`, `/<doc_id>/delete`) | `documents` |
| `/admin/projects`, `/admin/project-sectors` | `projects` |
| `/admin/articles`, `/admin/article-categories` | `articles` |
| `/admin/services`, `/admin/service-steps` | `services` |
| `/admin/faq`, `/admin/faq-categories` | `faq` |
| `/admin/company` (hub) + `/admin/company/{stats,timeline,team,certifications,industries,testimonials,offices}` | `company` |
| `/admin/inquiries` (+ `/<id>`, `/<id>/delete`, `/export.csv`) | `inquiries` |
| `/admin/revalidate` (+ `/flush`) | `public_api` |
| `/admin/i18n/<code>/import` (JSON import), `/admin/i18n/<code>/translate?prefix=web.` | `i18n` |
| `/admin/media/browse` (JSON, media picker) | `images` |

Public JSON endpoints (no auth; `POST /api/public/inquiries` is the only non-GET):
`health, site, navigation, categories(/<slug>), brands(/<slug>), tags, products(/<slug>), documents/<id>/download, projects(/<slug>),
project-sectors, articles(/<slug>), article-categories, services(/<slug>), faq, company, inquiries, track, search, home, sitemap, redirects`.
Detail endpoints of products/projects/articles also accept `?preview=<signed token>` (draft preview).
`/api/i18n/translate/<code>` gained `prefix`, `strip_prefix`, `fallback` and `ETag`.

Also (all 🔒admin): `/admin/navigation` (generic CRUD, `navigation` plugin) and `/admin/frontend-visits` (`visits` plugin report).
