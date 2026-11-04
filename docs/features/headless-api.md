# Feature: Headless frontend support (public API, multilingual content, entity engine)

The Next.js frontend consumes `/api/public/*`. The contract for the frontend
agent is [../frontend-api.md](../frontend-api.md) (generated from the live
server by `scripts/build_frontend_doc.py`). This file is for backend work.

## Relevant files

- `app/core/public.py` — API infrastructure (always installed by `create_app`): `ApiError`, JSON error envelope for **every** error under `/api/public/`, DB failure ⇒ `503`, CORS (`CORS_ALLOWED_ORIGINS`, empty = no headers), `ETag`/`304`, `Cache-Control`, short-TTL response cache (`PUBLIC_API_CACHE_TTL`), `Ctx` (serialisation helpers bound to a request), `public_get()` route decorator, param helpers (`arg_int` clamps, `arg_choice` ⇒ 400), `RateLimiter`, `client_ip()`.
- `app/core/content.py` — pure helpers: search normalisation (`normalize_search`, `escape_like`), slugs, `*_i18n` JSON (de)serialisation, `I18nText`/`I18nList` builders, media (absolute URLs, Pillow size cache), ISO time, HTML→text, reading time.
- `app/core/entity.py` — spec-driven entity engine (see below).
- `app/core/revalidate.py` — `app.revalidate.notify(*tags)`: clears the public API cache immediately and (if `FRONTEND_REVALIDATE_URL`/`_SECRET` are set) posts the merged tags to the frontend from a daemon thread.
- `app/core/migrate.py` — idempotent helpers for `maybe_run_migration()` (`ensure_index`, `seed_once`, `run`).
- `app/core/database.py` — adds `fetch()` (raises `DatabaseError` instead of returning `None`), `transaction(fn)` (one commit, rollback on error) and a pool that **waits** (`DB_POOL_WAIT`) instead of failing when all connections are busy.
- `app/core/captcha.py` — optional Turnstile/hCaptcha verification (`CAPTCHA_PROVIDER/_SECRET/_SITE_KEY`, `CAPTCHA_VERIFY_URL` override for tests).
- Plugins (all `auto_enable`): `public_api` (health, redirects, home, sitemap, search, `/admin/revalidate`), `site_settings`, `brands`, `documents`, `projects`, `articles`, `services`, `faq`, `company`, `inquiries`, `navigation`, `visits`; extended: `products`, `categories`, `i18n`, `images`, `cache`.
- Templates: `templates/admin_entity/{list,form,_macros,_scripts}.html` (generic admin UI), `templates/plugins/{site_settings,documents,inquiries,company,public_api}/`.
- `scripts/seed_demo.py`, `scripts/smoke_public_api.py`, `scripts/build_frontend_doc.py`, `tests/`.

## Multilingual storage

Every translatable field `x` is stored as JSON in `x_i18n` (`{"fa": "...", "en": "..."}`;
lists as `{"fa": [...]}`) — no join table, no N+1. Legacy single-language columns
(`products.name`, `description`, `meta_*`, `title`, categories likewise) stay in sync with
the Persian value on every save, and reading falls back to them when `x_i18n` is still
empty, so old code and `/api/products` keep working. `maybe_run_migration()` back-fills
`x_i18n.fa` from the legacy columns (never touching the legacy column).

## The entity engine (`app/core/entity.py`)

Describe an entity with `Entity(..., fields=[Field(...)], children=[Child(...)])` and get
schema declaration, form parsing, validation, transactional save, delete, and generic
admin routes (`register_admin(bp, ent)`):

- **Absent form field = untouched; present-but-empty = cleared** (per language for i18n
  fields; a repeater is only replaced when its `<key>__present` marker is posted).
- Validation returns Persian messages per field (`errors["rows-0-label"]` for repeater
  rows); the form re-renders (HTTP 422) with the entered values. "Saved" flashes only
  after a real commit.
- `slug` fields: auto-generated (English name → model code → transliterated Persian →
  `<key>-<id>`), unique (pre-check + DB `UNIQUE`), old slugs are recorded in `slug_history`
  (`GET /api/public/redirects`). An existing legacy slug that is left unchanged is accepted
  even if it would not pass the new format rule (`grandfather`).
- Hooks (assign on the `Entity`): `prepare`, `extra_validate`, `extra_cols`, `after_save`,
  `before_delete` (raise `DeleteBlocked`), `after_delete`, `after_commit`, `load_extra`,
  `form_panels`, `tags` (revalidate tags).
- Every successful write calls `app.revalidate.notify(...)`, which also clears the public
  API cache. If you write to a content table outside the engine, call it yourself.

## Adding a public endpoint

```python
pub = public_blueprint("public_things")
@public_get(pub, "/things", params=("q", "page"))        # only listed params enter the cache key
async def things(ctx):                                    # ctx.text()/lst()/media()/seo()/iso()
    rows = await ctx.db.fetch("SELECT ...")               # fetch() raises -> 503, never an empty list
    return {"things": [...], "meta": meta(total, page, per_page)}
self.app.register_blueprint(pub)
```
Raise `not_found()` / `bad_request()` / `validation_failed({...})` for errors. Register
`search` / `sitemap` / `home` providers in `app.public_providers` if the entity belongs
there. Add the entity's revalidate tags to its `Entity.tags`.

## Documents

`documents` + `document_files` (one file per language) are shared by products and company
certifications through `register_owner()`. Uploads are validated (extension allow-list,
never executable/script, size cap, `%PDF-`/ZIP/Pillow signature check), stored **outside**
`uploads/` as `storage/documents/<yyyy>/<uuid>.<ext>` and served only by
`GET /api/public/documents/<id>/download` (Range/HEAD, download counter on plain GET).
Quota: `ASSETS_DIR_Max_Size` covers `uploads/` + documents together.

## Inquiries

`POST /api/public/inquiries`: the zod rules are repeated server-side, honeypot `website`,
rate limit per IP (in-process + DB), atomic sequential reference
`<PREFIX>-<year>-<0001>` (row-locked counter row committed together with the inquiry),
optional SMTP notification in a thread. Never exposed through any public endpoint.

## Testing

```
python -m unittest discover -s tests -v        # tests/test_logic.py (no DB) + tests/test_api.py (real MySQL)
python scripts/smoke_public_api.py [--base URL]
python scripts/seed_demo.py [--remove]
```
`tests/test_api.py` writes to the configured DB and **refuses to run unless `DB_HOST` is
loopback** (`ALLOW_REMOTE_TEST_DB=1` overrides). Use a throw-away MySQL and set `DB_HOST`,
`DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` (environment variables win over `.env`).

## Things that must not break

- The legacy `/api/products`, `/api/categories`, `/api/i18n/*`, `/product/<slug>`,
  `/category/<slug>` keep their exact shape (explicit column lists, not `SELECT *`).
- `plugin_products.public_page` must stay a registered view (the theme builder replaces it).
- `/api/public/*` stays excluded from visitor tracking.
- Public handlers must use `ctx.db.fetch` (not `db.query`) so DB errors become `503`.


## P2 features (all implemented)

- **Draft preview** — `make_preview_token(kind, id)` / `preview_target(kind)` in `app/core/public.py` (itsdangerous, salted with
  `SECRET_KEY`, `PREVIEW_TOKEN_TTL`). Entities with `Entity.preview_kind` (`product`, `project`, `article`) get a
  "پیش‌نمایش پیش‌نویس" link in the admin form (`site_url + view_path + ?preview=<token>`). Detail handlers call
  `preview_target(kind)`: a valid token bypasses the published filter for that one id (slug must match); an invalid one is `400`.
  `public_get` never caches a request that carries `preview`, and the response gets `Cache-Control: private, no-store` +
  `X-Robots-Tag: noindex, nofollow`.
- **Navigation** (`navigation` plugin) — `nav_items(menu, parent_id, label_i18n, href, new_tab, sort_order, is_active)`, two levels,
  seeded once with the main links; `GET /api/public/navigation`, tag `navigation`.
- **Service detail** — `GET /api/public/services/<slug>` (+ `services` in the sitemap), tag `service:<slug>`.
- **Site flags** — `site_settings` group "پیشرفته": `maintenance_enabled/_message`, `feature_*`, `track_enabled`, `catalog_mode`.
  They surface as `site.maintenance`, `site.features`, `site.analytics.track`; `catalog_mode` is panel-only
  (`Entity.hidden_fields` hides `price/old_price/stock` in the product form; hidden fields stay untouched on save).
- **Plugin switches** — `site.plugins` = `{plugin_name: enabled}` for every discovered plugin (the `/admin/plugins` toggle). A disabled
  plugin's endpoints answer `404 plugin_disabled`, so the frontend ANDs it with `site.features` (`src/lib/api/mappers.ts`) and hides
  menus/pages. `PluginManager.set_enabled` calls `revalidate.notify("*", "site")` so the toggle shows up without waiting for the TTL.
- **CAPTCHA** — `POST /inquiries` requires `captcha_token` when configured; verified last (tokens are single-use), unreachable
  verifier ⇒ `503` (never a bypass); `site.captcha = {provider, site_key}`.
- **Page-view tracking** (`visits` plugin) — `POST /api/public/track` (always `204`; stored only when `track_enabled`), salted IP hash,
  bots ignored, retention pruning, report at `/admin/frontend-visits`.
