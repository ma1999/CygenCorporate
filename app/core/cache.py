"""PluginCache — in-process cache with per-plugin namespaces.

هر پلاگین یک namespace جداگانه دارد (مثلاً "products" یا "images")، بنابراین
کش‌ها از هم ایزوله هستند و می‌توان کل کش یک پلاگین را بدون دست زدن به بقیه پاک کرد.

Features:
- TTL per entry (default 300s)
- get_or_set(): اگر کش تازه باشد دیتا از کش برمی‌گردد، وگرنه factory صدا زده
  می‌شود و نتیجه در کش ذخیره می‌شود.
- invalidate(key) / invalidate_namespace(ns) / clear()
- آمار hit/miss برای پنل ادمین
"""
import time
import asyncio
import threading


class PluginCache:
    def __init__(self, default_ttl: int = 300, max_keys: int = 5000):
        self.default_ttl = default_ttl
        self.max_keys = max_keys
        self._store = {}          # full_key -> {"exp": float, "value": ...}
        self._lock = threading.Lock()
        self._stats = {}          # namespace -> {"hits": n, "misses": n}

    # ---------------- keys ----------------
    @staticmethod
    def make_key(namespace: str, *parts) -> str:
        return namespace + ":" + ":".join(str(p) for p in parts)

    # ---------------- basic ops ----------------
    def get(self, key: str, namespace: str = None):
        ns = namespace or key.split(":", 1)[0]
        now = time.time()
        with self._lock:
            entry = self._store.get(key)
            if entry is None or entry["exp"] <= now:
                self._store.pop(key, None)
                st = self._stats.setdefault(ns, {"hits": 0, "misses": 0})
                st["misses"] += 1
                return None
            st = self._stats.setdefault(ns, {"hits": 0, "misses": 0})
            st["hits"] += 1
            return entry["value"]

    def set(self, key: str, value, ttl: int = None, namespace: str = None):
        ns = namespace or key.split(":", 1)[0]
        with self._lock:
            if len(self._store) >= self.max_keys:
                self._evict_expired_locked()
                if len(self._store) >= self.max_keys:
                    # ساده: قدیمی‌ترین ورودی حذف شود
                    oldest = min(self._store, key=lambda k: self._store[k]["exp"])
                    self._store.pop(oldest, None)
            self._store[key] = {
                "exp": time.time() + (ttl or self.default_ttl),
                "value": value,
            }
            self._stats.setdefault(ns, {"hits": 0, "misses": 0})

    def delete(self, key: str):
        with self._lock:
            self._store.pop(key, None)

    def invalidate(self, *keys: str):
        """پاک کردن چند کلید مشخص."""
        with self._lock:
            for k in keys:
                self._store.pop(k, None)

    def invalidate_namespace(self, namespace: str):
        """کل کشِ یک پلاگین را پاک می‌کند (بقیه پلاگین‌ها دست‌نخورده می‌مانند)."""
        prefix = namespace + ":"
        with self._lock:
            for k in [k for k in self._store if k.startswith(prefix)]:
                self._store.pop(k, None)
            self._stats[namespace] = {"hits": 0, "misses": 0}

    def clear(self):
        with self._lock:
            self._store.clear()
            self._stats.clear()

    def _evict_expired_locked(self):
        now = time.time()
        for k in [k for k, v in self._store.items() if v["exp"] <= now]:
            self._store.pop(k, None)

    # ---------------- high level ----------------
    async def get_or_set(self, key: str, factory, ttl: int = None, namespace: str = None):
        """اگر در کش بود برگردان؛ وگرنه factory (sync یا async) را اجرا و ذخیره کن."""
        cached = self.get(key, namespace)
        if cached is not None:
            return cached
        if asyncio.iscoroutinefunction(factory):
            value = await factory()
        else:
            value = factory()
            # lambda ممکن است coroutine برگرداند
            if asyncio.iscoroutine(value):
                value = await value
        if value is not None:
            self.set(key, value, ttl=ttl, namespace=namespace)
        return value

    # ---------------- stats ----------------
    def stats(self):
        with self._lock:
            out = []
            for ns, st in sorted(self._stats.items()):
                total = st["hits"] + st["misses"]
                out.append({
                    "namespace": ns,
                    "hits": st["hits"],
                    "misses": st["misses"],
                    "hit_rate": round(st["hits"] / total * 100, 1) if total else 0.0,
                    "key_count": sum(1 for k in self._store if k.startswith(ns + ":")),
                })
            return out

    def size(self):
        with self._lock:
            return len(self._store)


def init_cache(app, default_ttl: int = 300):
    """Flask extension: app.cache از هر جای برنامه (و پلاگین‌ها) در دسترس است."""
    if not hasattr(app, "cache"):
        app.cache = PluginCache(default_ttl=default_ttl)
    return app.cache
