# Admin JSON API + Vuexy panel

The admin panel is a Vuexy (RTL, Persian) shell whose pages fill themselves from `/api/admin/*` with `fetch`.
A React admin can later replace the page JS and keep this API unchanged.

## Contract

- Auth: Flask session cookie (`SameSite=Lax`). Only `administrator` can log in to the API.
  Every non-GET request must send `X-CSRF-Token` (value from login / `GET /api/admin/auth/me`; the shell also
  puts it in `<meta name="csrf-token">`).
- Success: `{"ok": true, "data": ..., "meta": {total,page,per_page,total_pages}?}` — always `Cache-Control: no-store`.
- Error: `{"ok": false, "error": "<code>", "message": "...", "fields": {field: msg}?}` — same envelope as `/api/public/*`.
  Codes: `unauthorized` 401, `forbidden`/`csrf_failed` 403, `not_found` 404, `conflict` 409, `validation_failed` 422,
  `rate_limited` 429, `unavailable` 503. Helpers: `app/core/admin_api.py` (`admin_api`, `reply`, `invalid`, `body`).
- Bodies are JSON (≤ 2 MB). Translatable fields are `{"fa": …, "en": …}`; list fields are arrays;
  "absent key = untouched, present-but-empty = cleared" (same rule as the old forms — JSON is flattened to the
  form shape by `json_to_form` in `app/core/entity.py`, so tag-stripping/validation are unchanged).

## Endpoints

| Area | Endpoints |
|---|---|
| Auth | `POST /api/admin/auth/login` `{username,password}` · `POST …/logout` · `GET …/me` (user, csrf, menu, languages, site) |
| Core | `GET /dashboard` · `GET/PUT /settings` · `GET/POST /users`, `DELETE /users/<id>` · `GET/PUT /roles` · `GET /themes`, `POST /themes/activate` · `GET /plugins`, `POST /plugins/toggle` |
| Every `Entity` (via `register_admin`) | `GET <api>` list (`q,page,per_page,sort,f_<col>`) · `GET <api>/schema` (entity meta, fields, children, languages, defaults, options, filters) · `GET <api>/<id>` · `POST <api>` · `PUT <api>/<id>` · `DELETE <api>/<id>` · `POST <api>/<id>/toggle` |

`<api>` is `/api` + the entity's `path` (e.g. `/api/admin/products`, `/api/admin/product-tags`, `/api/admin/company/stats`).
Page URLs are unchanged (`/admin/products`, `/admin/products/create`, `/admin/products/<id>/edit`) but are now only shells.

## Front-end files

`templates/admin_ui/` (`layout.html` chrome + server-rendered menu, `entity.html`, `page.html`, `login.html`) and
`assets/admin-ui/` (copied Vuexy `vendor/`, `css/`, `js/main.js`, `js/config.js`) + `assets/admin-ui/app/`:
`api.js` (fetch client, toasts, confirm), `shell.js`, `entity.js` (generic list + form from `/schema`), `pages-core.js`.

## Migration status

All admin areas are ported; no admin page renders server-side forms any more.

| Area | API | Page JS |
|---|---|---|
| Entities (products, tags, projects, sectors, articles + categories, brands, services + steps, faq + categories, company sections, navigation, categories create/edit) | `register_admin` | `entity.js` |
| Product documents panel | `form_panels` -> `item.panels` | `entity.js` |
| Categories tree (toggle / soft delete / purge) | `/api/admin/categories[...]` | `pages-categories.js` |
| Core: dashboard, settings, users, roles, legacy themes, plugins | `routes.py` | `pages-core.js` |
| Cache, revalidate, frontend visits, company hub | `/api/admin/cache`, `/revalidate`, `/frontend-visits`, `/company` | `pages-system.js` |
| Inquiries (+CSV) | `/api/admin/inquiries[...]` | `pages-inquiries.js` |
| Documents (multipart per language) | `/api/admin/documents/...` | `pages-documents.js` |
| Site settings (grouped single record) | `GET/PUT /api/admin/site-settings` | `entity.js` (`settings` mode) |
| i18n (languages, translate, import/export/seed) | `/api/admin/i18n[...]` | `pages-i18n.js` |
| Images / file manager / media picker | `/api/admin/images[...]`, `/api/admin/media/browse` | `pages-images.js`, `media-picker.js` |
| Tracking | `/api/admin/tracking[...]` | `pages-tracking.js` |
| Page builder (pages, drafts, publish, preview) | `/api/admin/page-builder[...]` | `pages-builder.js` |
| Site theme + visual builder | `/api/admin/site-theme[...]` | `pages-theme.js`, `templates/admin_ui/builder.html` (Alpine from CDN) |

Helpers for a new plugin page: `page_route(bp, rule, endpoint, page_key, title, script)` (shell, `admin_required`) and
`@api_route(bp, rule, endpoint, methods)` (JSON, `admin_api`) from `app/core/admin_api.py`; the page JS registers
`Admin.pages[page_key] = async (root, params) => {...}` and `Admin.ui` has `card/fmtDate/fieldErrors`.

Behaviour changes vs the old panel: `POST /login` is gone (use `/api/admin/auth/login`); `/api/cache/stats` and
`/api/cache/clear/<ns>` moved to `/api/admin/cache[...]`; per-image product routes were dropped (the gallery is the
`images` child repeater); the i18n translate editor sends only changed keys; tracking JSON now uses the envelope and
ISO dates.

## Performance & UX notes (admin panel)

- `pool_reset_session=False` in `app/core/database.py`: a pooled connection is returned without a `cmd_reset_connection`
  round trip (every path is autocommit or restores it in `Database.transaction`).
- Short-lived `admin` cache namespace (60 s languages / site url, 30 s sidebar menu, 10 min table list for the dashboard);
  `revalidate.notify()` (every content write) and the plugin toggle clear it. Independent lookups of an entity form
  (children, select options, hidden fields, panels, site url) run with `asyncio.gather`.
- Sidebar is grouped (`GROUP_LABELS` / `PLUGIN_GROUP` in `admin_api.py`; a plugin's `admin_entry["badge"]` renders as a badge),
  the navbar shows page title + breadcrumb, lists/forms/pages show skeletons (`templates/admin_ui/_sk.html`, `Admin.sk`),
  forms warn about unsaved changes and save on Ctrl/Cmd+S, the translation editor pages 80 keys at a time.

## Tests

`tests/test_api.py` drives the admin through `LegacyAdminClient` (see the top of the file): old-style calls
(`POST /admin/products/create`, `.../edit`, `.../delete`, site-settings, i18n, inquiries, documents) are translated to the
JSON API with the CSRF header, 302/Location/flash behaviour is emulated, and pages that used to carry data are read from
their API payload. Set `TEST_ADMIN_PASSWORD` if the test DB admin is not `admin123`. The suite refuses to run on a
non-loopback `DB_HOST` (see CLAUDE.md) — run it against a throw-away local MySQL.

## Enabling / disabling plugins (no restart)

`PluginManager` remembers which blueprints and public providers (search / home / sitemap) each plugin registered.
- **Disable:** a `before_request` gate answers 404 (`{"error":"plugin_disabled"}` under `/api/`) for every route of the
  plugin — admin pages, admin API, public API — its providers are parked, and it leaves the sidebar and dashboard.
- **Enable:** a plugin that was disabled at boot is registered on the spot in a worker thread (`_register`: Flask's
  "first request served" flag is lifted for the duration of the registration, serialised by a lock); an already registered
  plugin just gets its providers restored. `GET /api/admin/plugins` reports `needs_restart` only if that registration failed.
- The enabled set is cached 30 s in the `admin` cache namespace and cleared by `set_enabled`.
