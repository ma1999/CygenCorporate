# Feature: Visitor tracking

## Relevant files

- `app/plugins/tracking/plugin.py`
- `app/plugins/tracking/README.md` — plugin-authored deep-dive (columns
  table, exclude-rule reference, tuning knobs) — read that first; this
  file adds what it doesn't cover: caching internals, auth, and gotchas.
- `app/plugins/tracking/GeoLite2-{Country,City}.mmdb` — MaxMind GeoIP DBs
  (binary, checked into the repo; plugin degrades gracefully if either is
  missing)
- `templates/plugins/tracking/{dashboard,visitors,visitor_detail,settings}.html`

## Responsibilities

Records (almost) every HTTP request as an analytics row, deduped into
persistent "visitors" by a first-party cookie, with GeoIP, device/browser
parsing, and an admin dashboard — all designed so tracking adds
negligible latency to the actual response.

## Data flow (request path — see the README for the full column reference)

1. `_before_request` is currently a no-op placeholder.
2. `_after_request` (registered via `app.after_request`) does **only
   in-memory work** on the hot path: parse UA, check exclude rules (cached
   settings), look up GeoIP (cached by IP), look up the visitor id (cached
   by cookie value) — then `put_nowait()`s a small dict onto a
   `queue.Queue` and returns immediately. If the visitor id isn't cached
   (first request from that visitor), the dict is enqueued with
   `cached_visitor_id: None` and resolved later.
3. A dedicated daemon thread (`tracking-writer`, its own asyncio event
   loop) drains the queue and does the actual MySQL work per item
   (`_flush_one`): resolve/create the visitor row if needed, insert the
   `tracking_requests` row, touch `tracking_visitors.last_seen`/
   `request_count`, then **write-through** update the cached admin
   dashboard payload in place (bump counters, prepend to `recent[]`,
   re-cache) so the next `/api/admin/tracking/dashboard` call doesn't need
   to hit MySQL at all for a request that just happened.
4. Excluded requests (matched by path/method/status/UA/bot rules) still
   mint the visitor cookie via `_ensure_cookie`, so an excluded visitor
   never gets miscounted as "new" the first time they hit a *non*-excluded
   page.

## Important rules

- Auto-enables itself on first boot (`is_enabled()` override inserts an
  enabled `plugins` row if none exists) — unlike every other plugin, which
  defaults to disabled until toggled on.
- Timestamps are Jalali strings in `VARCHAR(32)` columns, not SQL
  `DATETIME` — see [database.md](../database.md#tracking-plugin). Sorting
  relies on the zero-padded format staying stable; don't change
  `_now_jalali()`'s format string without also handling any existing rows.
- The default exclude rules already cover `/admin/tracking*` and
  `/api/admin/*` specifically **to prevent a feedback loop**: without that
  exclusion, an admin refreshing the tracking dashboard would itself
  generate tracking writes that invalidate the very cache the dashboard
  just read, defeating the caching. `_ensure_admin_paths_excluded()` runs
  at boot to append these required patterns even into a customized
  `tracking_exclude_paths` setting if they're missing.
- `reload_rules()` must be called (it is, by `settings_view`'s POST
  handler) after changing exclude-rule settings, or the in-process
  `_rules_cache` will keep using stale rules until the process restarts.

## Dependencies

- `user_agents` (UA parsing), `maxminddb` (GeoIP; optional — the plugin
  logs a warning and returns empty geo data if not installed or the
  `.mmdb` files are missing), `jdatetime` (Jalali timestamps; falls back to
  ISO Gregorian if not installed).
- `app.cache` (`PluginCache`) for four purposes: GeoIP-by-IP
  (`tracking_geo`, 1-day TTL), visitor-id-by-cookie (`tracking_visitor`,
  1-hour TTL, size-bounded and auto-trimmed at
  `MAX_VISITOR_CACHE_ENTRIES`), and cached/write-through admin API
  responses (`tracking_admin`).

## Things that must not break

- The request path must never perform a **blocking** DB call — all writes
  go through the queue + background thread. Adding a synchronous
  `await db.query(...)` directly inside `_after_request` would reintroduce
  the exact latency problem this design exists to avoid (the README cites
  5–6s page loads on a high-RTT DB before this was built).
- `_write_queue.put_nowait()` must stay non-blocking; a full queue
  (`maxsize=10000`) logs a warning and **drops the row** rather than
  blocking the response — this is a deliberate availability-over-completeness
  tradeoff.
- Admin/API routes must keep their `@admin_required` decorator — this is
  the one plugin's admin surface that's actually protected; don't use the
  `products`/`categories`/`images` plugins as a copy-paste template for new
  admin routes here.
- `_invalidate_admin_cache()` / the write-through helpers assume there is
  exactly one `Plugin` instance registered in `_plugin_registry` — the
  module-level list is intentionally only ever appended to once
  (`if not _plugin_registry: _plugin_registry.append(self)`), because the
  background worker thread has no `self` and needs a global way to find
  the running plugin instance.
