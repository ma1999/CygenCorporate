"""Frontend revalidation webhook + public-API cache invalidation.

Every content write calls ``app.revalidate.notify(*tags)``. That

1. immediately clears the in-process ``public_api`` response cache (so the
   JSON API never serves stale data after an admin edit), and
2. if ``FRONTEND_REVALIDATE_URL`` and ``FRONTEND_REVALIDATE_SECRET`` are set,
   queues a ``POST`` to the Next.js app. Tags raised within a 2 second window
   are merged into one request; the request is sent from a daemon thread
   (timeout 3s, 3 attempts with back-off); failures are logged, never raised.

The secret is read from the environment at send time and is never logged.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from . import content as C

log = logging.getLogger("cms.revalidate")

COALESCE_SECONDS = 2.0
TIMEOUT = 3
ATTEMPTS = 3
CACHE_NS = "public_api"


def expand_tags(tags) -> list:
    """Add the tags that always change together (see docs/frontend-api.md)."""
    out = set(t for t in tags if t)
    for t in list(out):
        head = t.split(":", 1)[0]
        if head in ("categories", "category"):
            out |= {"products", "sitemap"}
        if head in ("products", "product", "brands", "tags"):
            out |= {"products", "search"}
        if head in ("products", "product", "projects", "project", "articles", "article", "categories", "category"):
            out |= {"sitemap", "search"}
    return sorted(out)


class Revalidator:
    def __init__(self, app):
        self.app = app
        self._pending: set = set()
        self._lock = threading.Lock()
        self._timer = None
        self.last: dict | None = None
        self.window = COALESCE_SECONDS
        self._idle = threading.Event()
        self._idle.set()

    # ---- config ----
    @staticmethod
    def config():
        url = (os.getenv("FRONTEND_REVALIDATE_URL") or "").strip()
        secret = (os.getenv("FRONTEND_REVALIDATE_SECRET") or "").strip()
        return url, secret

    @property
    def enabled(self) -> bool:
        url, secret = self.config()
        return bool(url and secret)

    # ---- api ----
    def notify(self, *tags):
        tags = expand_tags(tags)
        try:
            self.app.cache.invalidate_namespace(CACHE_NS)
            self.app.cache.invalidate_namespace("admin")  # languages / site url / menu used by the admin panel
        except Exception:  # cache must never break a write
            pass
        if not tags or not self.enabled:
            return
        with self._lock:
            self._pending.update(tags)
            self._idle.clear()
            if self._timer is None:
                self._timer = threading.Timer(self.window, self._flush)
                self._timer.daemon = True
                self._timer.start()

    def wait_idle(self, timeout=15.0) -> bool:
        """Block until queued events were sent (tests/scripts)."""
        return self._idle.wait(timeout)

    # ---- worker ----
    def _flush(self):
        with self._lock:
            tags = sorted(self._pending)
            self._pending.clear()
            self._timer = None
        try:
            if tags:
                self.last = self._send(tags)
                self._persist(self.last)
        except Exception as e:  # pragma: no cover - defensive
            log.error("revalidate worker failed: %s", e)
        finally:
            with self._lock:
                if not self._pending and self._timer is None:
                    self._idle.set()

    def _send(self, tags: list) -> dict:
        url, secret = self.config()
        payload = json.dumps(
            {"event": "content.changed", "tags": tags, "at": C.iso(C.utcnow())}
        ).encode("utf-8")
        host = urlparse(url).netloc
        status, error, attempt = None, None, 0
        for attempt in range(1, ATTEMPTS + 1):
            try:
                req = urllib.request.Request(
                    url,
                    data=payload,
                    method="POST",
                    headers={"Content-Type": "application/json", "X-Revalidate-Secret": secret},
                )
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    status = r.status
                if 200 <= status < 300:
                    error = None
                    break
                error = f"HTTP {status}"
            except urllib.error.HTTPError as e:
                status, error = e.code, f"HTTP {e.code}"
            except Exception as e:
                status, error = None, type(e).__name__
            if attempt < ATTEMPTS:
                time.sleep(0.5 * attempt)
        ok = error is None
        if ok:
            log.info("revalidate sent to %s tags=%s", host, tags)
        else:
            log.warning("revalidate to %s failed after %d attempts (%s)", host, attempt, error)
        return {
            "at": C.iso(C.utcnow()), "ok": ok, "status": status, "attempts": attempt,
            "tags": tags, "error": error, "host": host,
        }

    def _persist(self, result: dict):
        """Remember the last attempt for the admin panel (best effort)."""
        try:
            import asyncio

            asyncio.run(self.app.core.db.execute(
                "INSERT INTO settings (`key`,`value`) VALUES ('revalidate_last',%s) "
                "ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",
                (json.dumps(result, ensure_ascii=False),),
            ))
        except Exception:
            pass


def init_revalidate(app) -> Revalidator:
    if not hasattr(app, "revalidate"):
        app.revalidate = Revalidator(app)
    return app.revalidate
