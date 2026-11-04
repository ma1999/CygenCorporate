# Feature: Products

## Relevant files

- `app/plugins/products/plugin.py`
- `templates/plugins/products/{list,form,public}.html`
- Depends on `app/plugins/categories/plugin.py` for category data (soft
  dependency — see below)

## Responsibilities

Admin CRUD for a product catalog (name, price, stock, SKU, category,
images, SEO meta tags, JSON-LD schema override), plus a cached public
product page and a small JSON API.

## Data flow

- **Write path**: `admin_create`/`admin_edit` → `_save_product()` reads
  `request.form`, coerces types, drops `None` values, force-sets
  `title = name` (legacy compatibility, see [database.md](../database.md#schema-merge-gotchas)),
  then inserts/updates via `db.execute`/`db.update_table`. Every write is
  followed by `_invalidate_product(pid=...)`.
- **Read path (cached)**: `_load_product(pid)` / `_load_product_by_slug(slug)`
  go through `self.app.cache.get_or_set(...)` under the `products`
  namespace. A cache miss calls `_fetch_product`, which loads the row,
  attaches `images` (from `product_images`), `category` (via
  `_category_info`, including the parent category if the product's
  category is itself a subcategory), and pre-rendered `metatags` (a list of
  ready-to-inject `<meta>`/`<title>`/`<link>` HTML strings, HTML-escaped).
- **Public page** (`/product/<slug>`): loads the cached product, then
  either uses its stored `schema_json` or falls back to
  `_default_schema()` (a JSON-LD `Product` object with `Offer`
  availability derived from `stock > 0`).
- **API** (`/api/products`, `/api/products/<id>`): same cached loaders;
  `/api/products/<id>` 404s unless `status == "published"`.

## Cache invalidation pattern (`_invalidate_product`)

This is the reference implementation other plugins' caching follows:
1. Compute every cache key that could be stale (`products:list`,
   `products:list:ids`, `products:id:<pid>`, and both the old and new
   `products:slug:<slug>` if the slug changed).
2. `self._cache.invalidate(*keys)` — drop them all at once.
3. **Immediately re-populate** the same keys from the DB ("warm-up") so the
   very next request is still a cache hit instead of a guaranteed miss.
4. If the product no longer exists in the DB (e.g. after delete), skip the
   warm-up for that key on purpose — the next lookup should correctly miss
   and return `None`/404.

## Important rules

- `name` is the real title field; `title` is a NOT-NULL legacy column kept
  in sync purely for schema compatibility — don't read/write `title`
  directly in new code.
- The category dropdown (`_category_tree`) filters on
  `is_active=1 AND is_deleted=0` — a product whose `category_id` points at
  a category that gets soft-deleted or deactivated *after* assignment will
  keep that `category_id` (nothing cascades), but the product's own
  `_category_info()` lookup does **not** filter on active/deleted, so the
  public product page will still show the (now-inactive) category.
- Metatag HTML is built by simple string concatenation with `html.escape` —
  don't reuse `_build_metatags`'s output as anything other than raw HTML to
  inject into a template.

## Dependencies

- `app.cache` (`PluginCache`) — required; without it every read would hit
  MySQL directly (the code still works, `get_or_set` just always misses).
- `categories` table (owned by the `categories` plugin) for
  `category_id`/`_category_tree`/`_category_info` — if the `categories`
  plugin has never run its `declare_schema`, the `categories` table may not
  exist and these queries will fail. In practice `categories` is a core-ish
  plugin expected to always be present.

## Things that must not break

- **No route in this plugin is authenticated** (see [api.md](../api.md)) —
  this is a known, unaddressed gap, not a design choice specific to
  products.
- The invalidate-then-warm-up cache pattern must stay atomic from the
  caller's perspective (invalidate fully before warming) — reversing the
  order would let a concurrent request re-populate a key with stale data
  right before it gets deleted.
- `_default_schema()`'s `availability` logic (`InStock` iff `stock > 0`)
  is depended on by any SEO/structured-data expectations for the public
  product page — don't change the stock-to-availability mapping without
  updating both the fallback and any product-specific `schema_json` guidance.


## Update: headless-frontend support

The admin form is now the generic multilingual form (`app/core/entity.py`): language tabs, specs/variants/images repeaters, tags, brand, SEO; documents are managed at `/admin/documents/product/<id>`. Public API: `app/plugins/products/catalog.py`. Legacy `/api/products*` and `/product/<slug>` keep their shape (explicit column list). Products without a `model_code` are not exposed by `/api/public/products*`. See [headless-api.md](headless-api.md).
