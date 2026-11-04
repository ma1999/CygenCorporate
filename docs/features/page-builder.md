# Feature: Page builder (`page_builder` plugin)

Elementor-style editing for the headless frontend. **The layout of a page (order of sections / columns / widgets and every
setting) is data in the backend database**; the frontend only knows how to render widget *types*. Replacing or re-deploying the
frontend therefore loses no page: run its manifest sync again and everything renders as before. Another template = another
`theme` id with its own widgets — no backend change.

The older `theme_builder` plugin (Jinja themes, file-based designs) is unrelated and untouched.

## Files

- `app/plugins/page_builder/plugin.py` — schema, public + admin API, manifest sync
- `app/plugins/page_builder/layout.py` — pure validation (manifest, layout, rich-text sanitiser, slugs) — unit-tested
- `assets/admin-ui/app/pages-builder.js` (+ `.pb-*` rules in `admin.css`) — list page and visual editor
- tests: `tests/test_page_builder.py` (pure logic, runnable anywhere) and `PageBuilderApi` in `tests/test_api.py` (loopback test DB)
- frontend (`corporate-07`): `src/lib/builder/` (manifest, helpers), `src/components/builder/` (renderer, widgets, bridge),
  `scripts/sync-manifest.mjs`, `src/app/page.tsx`, `src/app/[...slug]/page.tsx`

## Data

| Table | Purpose |
|---|---|
| `page_themes(theme PK, name, version, manifest_json, synced_at)` | widget catalog + system pages + factory layouts a frontend sent |
| `site_pages(id, theme, slug, path, kind system/custom, title_i18n, seo_json, draft_json, published_json, status draft/published, revision, …)` unique `(theme, slug)` | one row per page per theme |
| `site_page_revisions(page_id, layout_json, note, created_at)` | one snapshot per publish, last 30 kept |

Layout document: `{"v":1,"sections":[{"id","hidden","settings":{…},"columns":[{"id","span":1-12,"settings":{…},"widgets":[{"id","type","hidden","settings":{…}}]}]}]}`.
Translatable settings are `{"fa":…,"en":…}`. Widgets store *query settings* (limit, …) never fetched data; dynamic widgets fetch server-side in the frontend.

Manifest (per theme): `{theme, name, version, section_fields, column_fields, pages:[{key, path, label, layout}], widgets:[{type, label, category, icon, dynamic, fields, defaults}]}`.
Field types: `text textarea richtext number select switch color image link icon entity repeater` (`i18n:true` on the text types).
The admin settings form is generated from `fields`; `defaults` seed new widgets; `pages[].layout` is the factory layout of a system page.

## Flow

1. Frontend → `PUT /api/public/themes/<theme>/manifest` (header `X-Revalidate-Secret` = `FRONTEND_REVALIDATE_SECRET`; 30 req/min/IP).
   Stores the manifest, creates a `system` page row (status `draft`, draft = factory layout) for each manifest page that has none. Existing drafts are never touched.
2. Admin edits in `/admin/page-builder`: every change autosaves the **draft** (`PUT /api/admin/page-builder/pages/<id>`), the editor tells the iframe
   (`postMessage pb:refresh`) to `router.refresh()`. The iframe is the real frontend with a signed `?preview=` token (`make_preview_token("page", id)`) and `builder=1`.
3. **Publish** copies draft → published, bumps `revision`, snapshots a revision, `revalidate.notify("pages","sitemap","page:<slug>")`.
4. Frontend `GET /api/public/pages/<slug>?theme=` returns the published layout (404 when unpublished ⇒ system pages fall back to their built-in
   component, custom pages 404). With `?preview=<token>` it returns the draft (never cached; the token is bound to one page).

## API

Public: `GET /pages?theme=` · `GET /pages/<path:slug>?theme=[&preview=]` · `PUT /themes/<theme>/manifest`.
Admin (`/api/admin/page-builder`, envelope + CSRF as in [admin-api.md](../admin-api.md)): `GET /themes`, `GET /themes/<theme>` (manifest + languages),
`GET/POST /pages?theme=`, `GET/PUT/DELETE /pages/<id>`, `POST /pages/<id>/publish|unpublish|reset|preview-url|restore`, `GET /pages/<id>/revisions|export`,
`POST /pages/import`. System pages cannot be deleted (use *reset*). Custom slugs: lowercase latin segments, ≤ 3 parts, first part not reserved
(`layout.RESERVED_SLUGS` — existing frontend routes).

## Safety rules (`layout.py`)

- Known widgets keep only keys declared in the manifest, every value coerced/clamped by field type; text has tags stripped, rich text goes through an allow-list
  sanitiser (no scripts/handlers/`javascript:`), links are scheme-checked, media paths traversal-checked.
- Widgets whose `type` is not in the manifest are **kept** (JSON-sanitised) and skipped by the renderer — a lost/older frontend never destroys data.
- Caps: 1 MB layout, 60 sections, 12 columns/section, 200 widgets, 60 repeater rows; ids are regenerated when invalid or duplicate; `validate_layout` is idempotent.

## Frontend contract

- `type` and field `name` strings are permanent (stored in layouts). Add, don't rename. A new template: new `THEME_ID`, own `manifest.mjs` + widgets.
- `THEME_ID` env (default `corporate-07`); `npm run sync:manifest` (also `prebuild`, soft-failing) after deploys / widget changes.
- Home: `app/page.tsx` renders the published `home` layout, else the built-in `HomePageClient`.
- Environment: backend `FRONTEND_PREVIEW_URL` (optional; defaults to the origin of `FRONTEND_REVALIDATE_URL`, then `site_settings.site_url`).

## Phase 2

### Live editing on the page itself

The editor's preview is the real frontend rendered at the real device width (1366 / 820 / 390) and scaled to fit. Inside it the frontend's
`BuilderBridge` draws an overlay (hover/selection boxes, toolbars, "+" between rows, drop lines, column resize handles) from the `data-pb-*`
attributes the renderer puts on every section / column / widget in editor mode, and talks to the editor with `postMessage`
(only to/from the embedding origin; protocol documented at the top of `BuilderBridge.tsx`).

- **Rows**: "+" between rows → structure picker (12, 6+6, 4+4+4, 3+3+3+3, 8+4, 3+6+3, … or a custom `3,6,3`) → empty columns appear on the live page.
- **Widgets**: drag from the palette (pointer drag, a shield covers the iframe) into a column or between rows; drag the ✥ handle of a placed widget to move it;
  click-to-add also works. Rows can nest once (`inner_row`, built-in container widget, ≤ 6 columns).
- **Width**: drag the handle between two columns (snaps to 12ths, edits desktop / tablet / mobile spans depending on the preview width) or use the column panel.
- Section toolbar: ↑ ↓ duplicate hide ★ (save as reusable template) delete. Undo/redo, Ctrl+S, Delete key work from inside the preview too.

### Platform-level ("common") settings

Every section / column / widget carries `node["common"]` (validated by `layout.COMMON_FIELDS`, delivered to the editor in `GET /themes/<theme>` as `common_fields`,
rendered as the **Style / Motion / Advanced** tabs): spacing, box background/radius/shadow/border/max-width, text & block alignment;
entrance animation (fade, slide from left/right/top/bottom, zoom in/out, rotate, flip — duration, delay, distance, easing, repeat), hover effect
(lift/scale/glow/tilt/brighten), continuous motion (float/pulse/bounce/spin/wiggle), per-device hide, css id/class; sections also get min height,
vertical alignment, column gap, gradient background, fixed background, **parallax**, **staggered column animation** and `sticky`.
Columns have `span` (desktop) plus optional `span_tablet` / `span_mobile`. The frontend implements them once in `PageRenderer` / `NodeShell` / `Motion`
(`lib/builder/common.ts`) — no per-widget code. Text effects and counters are widgets (`animated_text`, `counter`).

### Global areas, built-in pages and detail templates

`page_themes.manifest_json.pages[]` entries have a `role`:

| role | slugs (corporate-07) | rendered by |
|---|---|---|
| `page` | `home`, `about`, `services`, `faq`, `contact`, `products`, `projects`, `news`, `search` + custom pages | the page's route (`builderPageOrNull`), built-in design until published |
| `area` | `header`, `footer` | root layout (`PageRenderer area="header|footer"`), built-in `Header`/`Footer` until published |
| `template` | `product-detail`, `project-detail`, `article-detail`, `category-detail` (`/products/{slug}` …) | the detail route fetches the record, then `PageRenderer entity={…}` |

Widgets of a built-in page are the page's body as one widget each (`about_content`, `catalog_products`, `product_detail` …) so rows can be added above/below;
header/footer are made of parts shared with the built-in components (`site_logo`, `nav_menu`, `header_tools`, `topbar_*`, `footer_*`).
Templates preview with a sample record picked in the editor (`POST …/preview-url {sample}`; the page's `path` contains `{slug}`). Preview tokens travel as `?pb=`
(detail routes use `?preview=` for the record's own draft token). Per-page options `hide_header` / `hide_footer` (page settings) are applied with a `<style>` rule.

### Publishing

`POST …/publish {publish_at?}`: a future time stores `status='scheduled'`; no cron is needed — public reads treat `scheduled AND publish_at <= now` as published
(`plugin.LIVE_SQL`). Areas and templates cannot be scheduled. Reusable sections: `GET/POST /templates`, `GET/DELETE /templates/<id>` (`page_templates`).

### Database upgrades

New tables/columns (`site_pages.role|publish_at|options_json`, `page_templates`) are declared in `declare_schema`, so `create_app()` creates/adds them on every boot
(additive only, like the rest of the CMS); indexes come from `maybe_run_migration`.

### Atomic elements (the factory home page)

The factory `home` layout is built from single-purpose elements nested in rows / columns / `inner_row`s, so every piece can be selected on the live page,
edited in the panel and dragged on its own: `heading` (size / colour / tag), `text` (eyebrow / body / lead / small, colour), `badge`, `button`
(6 styles, size, arrow), `image` (+ optional `media_slot` that lets the "site settings → images" picture win), `icon_box` (dark / light card, numbered item),
`metric`, `bullet_list`, `info_card`. Data-driven lists (`stats`, `categories_grid`, `featured_products`, `projects_showcase`, `industries_grid`, `certifications`,
`testimonials`, `latest_news`, `offices_strip`) stay one widget each; their built-in heading can be switched off (`show_header`) in favour of separate
heading / text / button elements. The older composite blocks (`hero`, `intro`, `capabilities`, `features_numbered`, `cta_banner`) remain in the palette.
A site that published the older monolithic layout gets the atomic one with **Reset to the theme's default layout** in the editor menu.
Common style fields also include `box_padding` and `box_border_color`.

### Data filters on list widgets

`featured_products`, `projects_showcase`, `latest_news` and `categories_grid` take `entity` fields (editor shows a searchable picker; `multiple` ones
keep the order you picked, max 24): **hand-picked** items (`picks`, win over every filter), and filters `category` (products incl. sub-categories / article
category), `brand`, `tag`, `sector` (projects), `only_featured`, `only_new`, `sort`, `limit`. Hand-picking goes through the public list endpoints' `slugs`
parameter (`/api/public/products|articles|projects?slugs=a,b` — order preserved, drafts never returned). Entity kinds the editor can pick:
`category, product, project, article, brand, tag, sector, article_category` (`ENTITY_KINDS` in `layout.py`).

### Built-in pages are atomic too

`about`, `services`, `faq`, `contact`, `products`, `projects`, `news` (and the `search` page's banner) are seeded from the manifest as rows of the
same atoms (breadcrumb, eyebrow badge, heading, text, button, image, `icon_box`…) plus data parts: `timeline`, `team_grid`, `service_cards`,
`service_steps`, `faq_browser`, `contact_form`, `contact_offices`, `contact_map`; list pages use the `product_list` / `project_list` / `news_list` widgets
whose `presets` (category, brand, tag…) merge under the URL query. Section background `dark_grid` is the engineering-grid page banner. Because the layout is
data, an image/text pair can be swapped between columns, re-ordered or hidden like any other row. Detail templates (product / project / article / category)
are split into one widget per block (`product_summary`, `product_tabs`, `product_related`, `category_hero`, `category_products` …). To get the new
atomic layout on an already-published page use **Reset to the theme's default layout** (it overwrites the draft).

## Still open

An HTML-embed widget (needs an iframe/script policy), finer-grained widgets for the detail pages (gallery, specs, related …; today one widget per detail page),
search/sitemap providers for custom pages (the frontend reads `GET /pages` for its sitemap), theme switcher / duplicate-to-theme.
