# Database

MySQL, no ORM. Schema is declarative (`app/core/schema.py::SchemaManager`)
and additive-only: on every boot it creates missing databases/tables and
adds missing columns, but never alters an existing column's type or drops
anything. See [architecture.md](architecture.md#boot-sequence-app__init__py-create_app) for when this runs.

## How the final schema is assembled

`SchemaManager.tables` starts as a copy of `CORE_TABLES` (in `schema.py`),
then gets merged with:
1. `app/core/models.py::ALL_MODELS` (`Product`, `Category`, `Page`) via
   `Model.register(schema)` → `schema.register_table(name, columns)`.
2. Every discovered plugin's `declare_schema(schema)`.

`register_table`/`register_columns` both do `dict.update()` on the table's
column map — so if two registrations declare the *same column name* with a
*different SQL type/constraint string*, **the later call wins** for a
brand-new database (because `CREATE TABLE` only runs once, using whatever
the merged dict looks like at sync time). Order is: core tables → models →
plugins (in directory-listing order), and `declare_schema` runs for every
plugin *after* models are registered.

## Tables

### Core (`app/core/schema.py`)

| Table | Purpose | Key columns |
|---|---|---|
| `users` | Login accounts | `username` UNIQUE, `password_hash`, `role` (default `editor`), `is_hidden` |
| `roles` | Named permission sets | `name` UNIQUE, `permissions` JSON — **written by `/admin/roles` but never read back into a session; has no effect on access control.** See [features/auth.md](features/auth.md). |
| `settings` | Site-wide key/value config | `key` (PK), `value` — read by `core.inject_settings` context processor and `BasePlugin.get_setting/set_setting` |
| `pages` | Declared, unused | No route, plugin, or template reads/writes this table. Dead schema. |
| `plugins` | Which plugins are enabled | `name` UNIQUE, `enabled` |
| `products` / `categories` | Baseline columns from `app/core/models.py`; **superseded/extended** by the plugin tables below | see gotcha below |

### `products` plugin

- **`products`** — merges the core columns above with: `name` (NOT NULL —
  the column actually used; `title` is kept in sync for legacy
  compatibility, see gotcha below), `slug` UNIQUE, `description`, `stock`,
  `old_price`, `price`, `sku`, `category_id`, `status`, `meta_title`,
  `meta_description`, `meta_keywords`, `schema_json` (JSON-LD override),
  `extra` (JSON, free-form extensibility), `created_at`.
- **`product_images`** — `product_id`, `url`, `alt`, `sort_order`,
  `created_at`. One row per image; no FK constraint, cleaned up manually by
  the plugin on product delete.

### `categories` plugin

- **`categories`** — merges core columns with: `name` (NOT NULL, actually
  used column), `parent_id` (NULL = top-level), `slug`, `description`,
  `meta_title`/`meta_description`/`meta_keywords`, `schema_json`,
  `is_active`, `is_deleted` (soft-delete flag), `created_at`. Two levels
  only — a category whose `parent_id` points at another child is corrected
  back to `NULL` by the plugin (`_save_category`), not by a DB constraint.

### `i18n` plugin

- **`i18n_languages`** — `code` UNIQUE (e.g. `en`), `name`, `native_name`,
  `direction` (`ltr`/`rtl`), `flag`, `is_default`, `is_active`.
- **`i18n_translations`** — `lang_code`, `translation_key`, `value`. A
  unique index on `(lang_code, translation_key)` is added by
  `maybe_run_migration()` (not expressible via the declarative column API).
  Persian (`fa`) is the canonical **source** language and lives in
  `app/plugins/i18n/locales/fa.json` on disk, not in this table.

### `images` plugin

- **`images`** — DB mirror of the `uploads/` directory tree: `rel_path`
  UNIQUE, `file_name`, `folder`, `format`, `size_bytes`, `width`, `height`,
  `is_image`, `alt`, `url`, `status`, timestamps.
  **Gotcha:** `Plugin._db_upsert()` inserts a `base64_data` column that is
  **not** declared anywhere in `declare_schema()`. `Database.execute()`
  swallows the resulting MySQL error and returns `-1` (it never raises), so
  every upload silently fails to create/update its `images` row — the file
  itself is still written to disk and served fine, but the DB mirror (and
  anything that would query it) stays empty. Verify this against the live
  DB (`SHOW COLUMNS FROM images`) before building any feature that reads
  from the `images` table.

### `tracking` plugin

- **`tracking_visitors`** — one row per browser, deduped by a persistent
  cookie: `cookie_name`/`cookie_value`, `first_seen`/`last_seen` (Jalali
  strings, see below), `user_id`, first-request IP/country snapshot,
  `request_count`.
- **`tracking_requests`** — one row per HTTP request: `visitor_id`,
  `user_id`, `origin`/`destination`, `status_code`, `method`, 3 candidate
  IPs, GeoIP country/city, user-agent + parsed browser/device, `created_at`.
- **Gotcha:** `first_seen`/`last_seen`/`created_at` are declared as
  `VARCHAR(32)` and hold **Jalali (Persian calendar) date strings**
  (`1405/05/05 15:45:23`), not SQL `TIMESTAMP`/`DATETIME` — `ORDER BY` on
  these columns works only because the string format is zero-padded and
  lexicographically sortable. `maybe_run_migration()` converts any
  pre-existing `TIMESTAMP` columns to `VARCHAR(32)` on upgrade. See
  [features/tracking.md](features/tracking.md).

## Schema-merge gotchas (verified against source)

- **`categories.slug` is NOT unique at the DB level**, even though
  `CORE_TABLES` declares it `VARCHAR(191) UNIQUE`. The `categories` plugin's
  `declare_schema()` re-declares the same column as plain `VARCHAR(191)`
  (no `UNIQUE`), and because plugin `declare_schema()` calls run *after*
  the core models register, that's the definition present when
  `CREATE TABLE` actually runs. Uniqueness is enforced only in application
  code (`Plugin._unique_slug()` in `app/plugins/categories/plugin.py`,
  which appends `-2`, `-3`, ... on collision). **Do not rely on a DB-level
  unique constraint for `categories.slug`** — e.g. a raw `INSERT` bypassing
  `_save_category` can create duplicate slugs.
- **`products.slug` IS unique at the DB level** — both the core model and
  the products plugin declare it the same way (`VARCHAR(191) UNIQUE`), so
  there's no conflict there.
- **`products.title` and `categories.title`** exist only because the core
  `Model` classes declared them `NOT NULL` first; both plugins now use
  `name` as the real field and set `title = name` on every save purely so
  the `NOT NULL` legacy column doesn't reject the insert
  (`data.setdefault("title", data["name"])` / equivalent in
  `_save_category`). Don't add new code that reads `title` from either
  table — read `name`.
- Once a table exists, adding a *new* key to `declare_schema()` in a later
  code change is safe (it becomes an `ADD COLUMN` on next boot); *changing*
  an existing key's type/constraint is a no-op against an existing
  database — you'll need a `maybe_run_migration()` step instead, following
  the `i18n`/`tracking` pattern.

## Relationships (application-enforced, no FKs)

- `products.category_id` → `categories.id` (nullable; category delete does
  not cascade or null this out).
- `product_images.product_id` → `products.id` (rows deleted explicitly by
  the plugin when a product is deleted).
- `categories.parent_id` → `categories.id` (self-referential, one level of
  nesting expected/enforced by app logic, not the schema).
- `i18n_translations.lang_code` → `i18n_languages.code` (deleting a
  language explicitly deletes its translations in the same request).
- `tracking_requests.visitor_id` → `tracking_visitors.id`.
- `users.role` is a free-text string compared against the literal
  `"administrator"` — there's no `roles.name` FK relationship despite the
  `roles` table existing.

There are no MySQL foreign key constraints anywhere in this schema —
referential integrity, cascades, and uniqueness beyond what's noted above
are entirely the application's responsibility.


## Headless-frontend tables and columns (additive)

All i18n fields are stored as JSON in `<field>_i18n` (see [features/headless-api.md](features/headless-api.md));
legacy single-language columns stay in sync with the Persian value. New tables are created by each plugin's
`declare_schema`; indexes and seeded defaults by `maybe_run_migration` (idempotent).

| Table | Notes |
|---|---|
| `products` (+cols) | `model_code`, `subtitle_i18n`, `short_description_i18n`, `name_i18n`, `description_i18n`, `features_i18n`, `certifications`, `brand_id`, `is_featured`, `is_new`, `sort_order`, `published_at` (UTC), `og_image`, `noindex`, `meta_*_i18n`, `search_text`, `updated_at` (UTC) |
| `product_specs`, `product_variants` | repeater children (replace-all on save) |
| `product_images` (+cols) | `url_alt_i18n`; legacy `alt` mirrors Persian alt; real `sort_order` (first = cover) |
| `product_tags`, `product_tag_map` | tags + many-to-many (unique `(product_id, tag_id)`) |
| `categories` (+cols) | `name_i18n`, `short_description_i18n`, `description_i18n`, `icon`, `cover_image`(+alt), `standards`, `key_highlights_i18n`, `sort_order`, `meta_*_i18n`, `og_image`, `noindex`, `updated_at`. `slug` is UNIQUE only on databases created by the original schema |
| `brands` | `slug` UNIQUE, i18n name/description/meta, logo, website, sort/active |
| `documents`, `document_files` | shared by products and certifications (`owner_type`, `owner_id`); one file per language (unique `(document_id, lang_code)`); files live in `storage/documents/` |
| `projects` + `project_sectors`, `project_gallery`, `project_metrics`, `project_specs`, `project_products` | published/draft/scheduled |
| `articles` + `article_categories`, `article_sections` | `reading_time_auto`, `search_text` |
| `services`, `service_process_steps`, `faq_categories`, `faq_items` | |
| `company_stats`, `company_timeline`, `company_team`, `company_certifications`, `company_industries`, `company_testimonials`, `company_offices` | each with `is_active`, `sort_order` |
| `site_settings` (`skey`, `value`), `site_social_links` | singleton key/value settings; `_updated` row = last change |
| `inquiries`, `inquiry_counters` | `reference_code` UNIQUE; counter row locked per year |
| `nav_items` | editable header/footer menus (`menu`, `parent_id`, `label_i18n`, `href`, `new_tab`) |
| `frontend_pageviews` | optional `POST /api/public/track` data (`visitor`, `path`, `referrer`, `locale`, salted `ip_hash`); pruned after `TRACK_RETENTION_DAYS` |
| `slug_history` | old slugs for `GET /api/public/redirects` |
| `settings` (legacy) | untouched; extra keys used internally: `seed_*` flags, `demo_seed_manifest`, `revalidate_last` |

Publication rule (products, projects, articles): `status='published' AND (published_at IS NULL OR published_at <= UTC_TIMESTAMP())`.
Legacy `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` columns are in the MySQL server's local time; the API converts them to UTC.
