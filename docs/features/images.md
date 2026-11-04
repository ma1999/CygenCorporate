# Feature: Media library (images plugin)

## Relevant files

- `app/plugins/images/plugin.py`
- `templates/plugins/images/{manager,editor}.html`
- Storage root: `uploads/` at the project root (created if missing)

## Responsibilities

A file-manager-style media library over the `uploads/` directory: folder
create/rename/delete/move, multi-file upload with a size quota, inline
editing of small text files, image dimension detection, and a DB "mirror"
table intended to make the library queryable without walking the
filesystem.

## Data flow

- **Browsing** (`/admin/images`): scans the target directory (optionally
  recursively) and caches the raw `(folders, files)` listing per
  `folder:recursive` key in `PluginCache` (namespace `images`, no
  explicit TTL → falls back to the cache's default TTL). Search/extension/
  size/date filters are applied **after** the cache read, against the
  cached listing, so filters don't cause extra disk I/O or additional
  cache entries.
- **Upload** (`/admin/images/upload`): checks the configured quota
  (`ASSETS_DIR_Max_Size` env var, GB) against current usage
  (`_used_bytes()`, a full `os.walk` — not cached) plus incoming file
  sizes before writing anything; auto-renames on a filename collision
  (`name-1.ext`, `name-2.ext`, ...); calls `_db_upsert()` per file.
- **Rename/move/delete**: mutate the filesystem first, then call the
  matching `_db_*` helper to keep the `images` table's `rel_path`/`folder`/
  `url` columns in sync (including recursive path rewrites for everything
  under a renamed/moved folder).
- **Serving**: `/assets/uploads/<path:filename>` streams via
  `send_from_directory` — this is the actual public URL used everywhere
  else in the app (product images, etc.), independent of the DB mirror.

## Important rules

- All path inputs go through `_safe_rel()` (rejects any segment equal to
  `..`) and `_abs_path()` (re-resolves and asserts the result is still
  inside `UPLOAD_ROOT`) before touching the filesystem. Any new route that
  accepts a path from the client **must** reuse these, not build paths by
  hand.
- The storage quota (`MAX_SIZE_BYTES`) is `0` (unlimited) unless
  `ASSETS_DIR_Max_Size` is set in `.env` to a nonzero value; the live
  `.env` in this repo sets it to `0.1` GB (~107 MB) for the whole
  `uploads/` tree.
- Only these extensions are treated as images for dimension detection /
  thumbnailing: `png, jpg, jpeg, gif, webp, bmp, svg`. Only these are
  treated as inline-editable text: `txt, md, css, js, json, html`.
  Everything else is just a generic file entry.

## Known issue — DB mirror silently doesn't populate

`declare_schema()` for the `images` table does **not** include a
`base64_data` column, but `_db_upsert()`'s `INSERT` statement references
one (`INSERT INTO images (..., url, base64_data) VALUES (...)`).
`Database.execute()` catches the resulting MySQL error internally and
returns `-1` rather than raising, so:

- Every upload/rename/move on-disk operation still succeeds.
- The corresponding `images` table row is **never actually created or
  updated** — the insert fails every time.
- Nothing currently reads from the `images` table (the browse view scans
  the filesystem directly, not the DB), so this has no visible symptom
  today, but any future feature planned around querying the `images` table
  (e.g. "recently uploaded", full-text search over `alt` text) will find it
  empty. Verify with `SHOW COLUMNS FROM images;` and either drop
  `base64_data` from the insert or add the column before relying on this
  table.

## Dependencies

- `Pillow` (`PIL.Image`) for image dimensions, with a hand-rolled PNG/GIF
  header parser as a fallback if Pillow fails.
- `python-dotenv` for the quota env var (loaded independently of the main
  app's `.env` load, from the same file).

## Things that must not break

- **No route in this plugin is authenticated** (see [api.md](../api.md)) —
  upload, delete, move, and the text editor are all publicly reachable.
  This is a materially higher-risk gap than the same issue on
  products/categories, since it allows arbitrary file upload (subject only
  to the byte quota) and arbitrary text-file overwrite within `uploads/`.
- The `_abs_path` containment check (`p.startswith(os.path.abspath(UPLOAD_ROOT))`)
  must stay in place on every filesystem-touching route — it's the only
  thing preventing path traversal out of `uploads/`.


## Update: headless-frontend support

Admin routes are `@admin_required`; `GET /admin/media/browse` serves the media picker from disk; `/assets/uploads/*` is sent with `Cache-Control: public, max-age=86400` and SVG with a sandbox CSP. See [headless-api.md](headless-api.md).
