# Tracking plugin

A request/page logging plugin with a persistent visitor cookie.

## What it captures (every request)

Stored in `tracking_requests` (one row per HTTP request):

| Column | Source |
| --- | --- |
| `origin` | `Referer` header |
| `destination` | `request.full_path` (path + query) |
| `status_code` | response status |
| `method` | `GET / POST / ...` |
| `ip_remote`, `ip_forwarded`, `ip_real` | 3 candidate client IPs from `REMOTE_ADDR`, `X-Forwarded-For` (first hop), `X-Real-IP` |
| `country_code`, `country_name`, `city` | MaxMind GeoLite2 lookup against the *real* client IP |
| `user_agent` | raw `User-Agent` |
| `browser_family`, `browser_version` | parsed via `user-agents` |
| `device_type` | `mobile / tablet / pc / bot / other` |
| `user_id` | id of the logged-in user (NULL if anonymous) |

Stored in `tracking_visitors` (one row per visitor, deduped by cookie):

| Column | Source |
| --- | --- |
| `cookie_name` | `AT-<site-slug>` where `site-slug` comes from `settings.site_title` |
| `cookie_value` | random 24-byte token issued on first visit, kept for 1 year |
| `first_ip_remote/forwarded/real` | IPs from the first request |
| `first_country` | country code from the first request |
| `request_count` | incremented on every subsequent request |
| `user_id` | last known logged-in user (preserved via `COALESCE`) |

## Files to drop next to `plugin.py`

- `GeoLite2-Country.mmdb`
- `GeoLite2-City.mmdb`

If either file is missing, geo lookup silently returns empty values and the plugin keeps working.

## Admin panel

- `/admin/tracking` — summary cards + recent requests
- `/admin/tracking/visitors` — paginated list of visitors
- `/admin/tracking/visitor/<id>` — per-visitor detail (info + 200 most recent rows)
- `/admin/tracking/settings` — exclude rules (path globs, methods, status filter, UA patterns, bot skip)

## Exclude rules

Stored in the `settings` table under these keys:

| Setting key | Field name | Default |
| --- | --- | --- |
| `tracking_exclude_paths` | `paths` | `/assets/*`, `/static/*`, `/uploads/*`, `/favicon.ico`, `/robots.txt`, `/sitemap*.xml`, `/admin/plugins*` |
| `tracking_exclude_methods` | `methods` | (empty — log everything) |
| `tracking_status_filter` | `status` | `all` (other options: `success`, `errors`) |
| `tracking_exclude_uas` | `uas` | common bots and crawlers |
| `tracking_ignore_bots` | `bots` | `1` (skip rows where user-agents reports `is_bot`) |

Pattern types:

- Plain lines use `fnmatch` (glob, case-insensitive) against either `request.path` or `request.full_path`.
- Lines starting with `re:` are treated as Python regex (case-insensitive).
- Excluded requests still mint/refresh the visitor cookie so a bot-only visitor never inflates the visitor table.

## Performance

The plugin is designed so the **request path never waits on a database
write or repeated I/O**:

1. GeoIP mmdb files are opened **once** during plugin init in
   `_load_geoip`. Lookups are cached in `app.cache` under the
   `tracking_geo` namespace (TTL = 1 day). Repeat lookups for the same
   IP are a single dict read.
2. All exclude rules and the cookie name are cached in process memory
   after the first request per process.
3. Visitor lookups are cached in `app.cache` under the
   `tracking_visitor` namespace (TTL = 1 hour). The first time a visitor
   appears we run one `SELECT` (or `INSERT` for new visitors); all
   subsequent requests reuse the cached id and never touch MySQL.
4. Each HTTP request only enqueues one row (and one visitor "touch")
 onto
   a small in-process queue (capacity 10k rows).
5. A daemon thread (`tracking-writer`) drains the queue into MySQL using
   its own connection-pool instance.

Result: a tracked request adds **<1 ms** to the response time even when
the database has a 100–200 ms RTT, which previously added 5–6 s per page.

Cache inspection: the two PluginCache namespaces appear in the admin
cache dashboard (`/admin/cache`) and can be invalidated manually:

- `tracking_geo` — IP → {country, city}
- `tracking_visitor` — cookie pair → visitor_id

Tuning knobs:

- `DB_POOL_SIZE` (env var, default `8`) — controls the size of the
  `MySQLConnectionPool` used by both the request path and the background
  writer. Increase if you see `queue.Full` warnings in logs.
- `tracking_visitor` namespace is auto-trimmed to
  `MAX_VISITOR_CACHE_ENTRIES` (default 5000). When the limit is hit,
  the whole namespace is cleared.

## Enable

1. From `/admin/plugins` toggle **tracking** to *enabled*.
2. Done — schema (`tracking_visitors`, `tracking_requests`) is auto-created on next boot.

## Enable

1. From `/admin/plugins` toggle **tracking** to *enabled*.
2. Done — schema (`tracking_visitors`, `tracking_requests`) is auto-created on next boot.