# Feature: Categories

## Relevant files

- `app/plugins/categories/plugin.py`
- `templates/plugins/categories/{list,form,public}.html`
- Consumed by `app/plugins/products/plugin.py` (`category_id`, `_category_tree`)

## Responsibilities

Two-level category tree (top-level + one level of subcategories) with SEO
fields and JSON-LD, soft delete, and a manual "purge" step to hard-delete
unused soft-deleted rows.

## Data flow

- **Create/edit** → `_save_category()`: trims `name`, mirrors it into the
  legacy `title` column, auto-generates a slug from `name` if none is
  given (`_slugify` — spaces → dashes, collapse repeats), then guarantees
  slug uniqueness at the **application level** via `_unique_slug()`
  (appends `-2`, `-3`, ... on collision). Also refuses to let a category
  become a child of its own child (checks one level down and clears
  `parent_id` if so).
- **Delete** (`admin_delete`) is a **soft delete**: sets
  `is_deleted=1, is_active=0` on the category and on every direct child —
  rows stay in the DB.
- **Purge** (`admin_purge` → `_purge_unused`): hard-deletes soft-deleted
  rows that are (a) not referenced as another row's `parent_id`, and (b)
  not referenced by any `products.category_id`. The `products` table
  lookup is wrapped in `try/except` so purge still works if `products`
  doesn't exist for some reason.
- **Public** (`/category/<slug>`, `/api/categories`, `/api/categories/<slug>`):
  only ever return `is_active=1 AND is_deleted=0` rows; the tree endpoint
  nests children directly under their parent object.

## Important rules

- `name` is the real field; `title` is a legacy NOT-NULL column kept in
  sync (see [database.md](../database.md#schema-merge-gotchas)) — same
  pattern as `products`.
- **Slug uniqueness is NOT a DB constraint here** — see the schema-merge
  gotcha in [database.md](../database.md#schema-merge-gotchas). Any code
  path that inserts/updates `categories.slug` without going through
  `_save_category`/`_unique_slug` can create duplicate slugs.
- Nesting is capped at two levels by convention, not by a schema
  constraint — `_save_category` only checks "is the proposed parent
  actually a child of this row", it does not check the *proposed parent's*
  own depth. Assigning a category's `parent_id` to a category that is
  already a subcategory is not currently prevented.
- Soft delete cascades one level (children of a deleted parent are also
  soft-deleted), but **does not** touch `products.category_id` — a product
  can end up pointing at a soft-deleted/inactive category (see
  [products.md](products.md)).

## Dependencies

- None beyond the core `Database`/schema machinery. `products` depends on
  this plugin, not the other way around.

## Things that must not break

- **No route in this plugin is authenticated** (see [api.md](../api.md)) —
  including `admin_purge`, which is destructive (hard delete).
- `_purge_unused`'s "used" check must keep covering both the
  parent-reference case and the products-reference case — removing either
  check would let purge delete a category that's still referenced
  elsewhere, orphaning data.
- The public API/page filters must keep requiring both `is_active=1` and
  `is_deleted=0` — relaxing either would surface soft-deleted or
  deliberately-hidden categories publicly.


## Update: headless-frontend support

Create/edit use the generic multilingual form (parent must be a live root; a category with children cannot become a child). Every write clears the `products` cache and notifies the frontend. Public API: `/api/public/categories`. See [headless-api.md](headless-api.md).
