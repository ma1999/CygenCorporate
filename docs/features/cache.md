# Feature: Caching (PluginCache + cache admin plugin)

## Relevant files

- `app/core/cache.py` — `PluginCache`, `init_cache()`
- `app/plugins/cache/plugin.py` — admin UI over the same object

## Responsibilities

A single in-process, namespaced, TTL-based cache (`app.cache`) shared by
every plugin, plus an admin panel to inspect and clear it.

## Data flow

- `init_cache(app, default_ttl)` (called once in `create_app`) attaches one
  `PluginCache` instance as `app.cache`; every plugin reaches it via
  `self.app.cache`.
- Keys are conventionally `"<namespace>:<...>"` (built by
  `PluginCache.make_key` or by plugins constructing the string directly,
  e.g. `f"{self.CACHE_NS}:id:{pid}"`); the namespace is either passed
  explicitly to `get`/`set`/`get_or_set` or inferred as the text before the
  first `:` in the key.
- `get_or_set(key, factory, ttl=None, namespace=None)` is the main entry
  point plugins use: returns the cached value if fresh, otherwise calls
  `factory()` (sync or async — both are handled), stores the result
  **only if it's not `None`**, and returns it.
- `invalidate(*keys)` drops specific keys; `invalidate_namespace(ns)` drops
  every key under a namespace (and resets its stats) — this is how a
  plugin clears just its own cache without touching others.
- The `cache` plugin's `/admin/cache` dashboard renders `PluginCache.stats()`
  (hits/misses/hit-rate/key-count per namespace) and exposes clear-one /
  clear-all / change-TTL actions.

## Important rules

- **A `None` result is never cached** (`get_or_set` only calls `self.set`
  when `value is not None`) — a factory that legitimately returns `None`
  will be re-run on every call, not just misses. This is intentional for
  things like "product not found" (so a product that *becomes* published
  later is immediately visible without a stale negative cache), but means
  a hot path that frequently returns `None` gets no caching benefit at all.
- **Eviction under `max_keys` (default 5000)** is a single "remove the
  entry with the earliest expiry" — not LRU. Under sustained load past the
  cap this can evict a frequently-used-but-long-TTL entry before a
  rarely-used-but-short-TTL one.
- There is **no cross-process sharing** — see
  [architecture.md](../architecture.md#caching-model). Fine for the
  single-process dev server this app ships with; would silently break
  invalidation correctness under a multi-worker deployment.

## Dependencies

- Nothing beyond the standard library (`threading.Lock`, `time`).

## Things that must not break

- `invalidate_namespace` must keep resetting that namespace's stats
  entry too (not just the keys) — several plugins call it expecting a
  clean slate for hit/miss reporting after a bulk change.
- **No route in the `cache` plugin is authenticated** (see
  [api.md](../api.md)) — anyone can wipe the entire application cache or
  change the default TTL at any time.
- Plugins that cache computed/aggregated values (not just raw rows) — e.g.
  `tracking`'s write-through dashboard cache — depend on `set()` accepting
  arbitrary Python objects (dicts, lists) by reference; don't change
  `PluginCache` to serialize values (e.g. to JSON) without checking every
  caller that mutates a cached object in place after reading it.


## Update: headless-frontend support

Admin routes and `/api/cache/*` are `@admin_required`. The public API has its own namespace `public_api` (TTL `PUBLIC_API_CACHE_TTL`), cleared by `app.revalidate.notify()` on every content write. See [headless-api.md](headless-api.md).
