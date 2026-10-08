"""Two-level cache for data read often and changed rarely (rules, settings).

A read looks in this process's memory first (`local`, seconds), then in Redis (`default`, shared
by every process, hours), and only then loads from the database, storing the value in both.
A value found in Redis is copied back to memory.

`clear()` empties Redis and this process's memory. Other processes (the other gunicorn
workers, the menu worker) keep their memory copy until it expires: a change shows up there
within `CACHE_MEMORY_TIMEOUT_SECONDS`. Every change to rules or settings clears the cache, and so
does every start of the backend (after its migrations), so seeded data is never hidden. The
clearing hangs on model signals: write rules and settings with `save()` / `delete()`, never
with a bulk `update()`, which sends none.

The counters are this process's own: each process keeps its own.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable
from typing import Any

from django.core.cache import caches
from django.utils import timezone

log = logging.getLogger(__name__)

# Stands for "not cached", so that None can be cached too.
_MISSING = object()
# Kept in Redis after a clear: when, and by whom.
LAST_CLEARED_KEY = "cache:last_cleared"


class CacheManager:
    def __init__(self, memory: str = "local", shared: str = "default") -> None:
        self._memory_alias = memory
        self._shared_alias = shared
        self._lock = threading.Lock()
        self.reset_counters()

    @property
    def memory(self):
        return caches[self._memory_alias]

    @property
    def shared(self):
        return caches[self._shared_alias]

    def reset_counters(self) -> None:
        self.counters = {"memory_hits": 0, "shared_hits": 0, "misses": 0, "errors": 0}

    def _count(self, name: str) -> None:
        with self._lock:
            self.counters[name] += 1

    def get_or_load(self, key: str, loader: Callable[[], Any]) -> Any:
        """The cached value of `key`, or what `loader` returns (then cached in both levels).

        If Redis is unreachable the value is loaded and kept in memory only: the app keeps
        working, a little slower."""
        value = self.memory.get(key, _MISSING)
        if value is not _MISSING:
            self._count("memory_hits")
            return value
        try:
            value = self.shared.get(key, _MISSING)
        except Exception as exc:  # Redis down: degrade to the database
            log.warning("cache: Redis unavailable (%s)", exc)
            self._count("errors")
            value = _MISSING
        if value is not _MISSING:
            self._count("shared_hits")
            self.memory.set(key, value)
            return value
        self._count("misses")
        value = loader()
        try:
            self.shared.set(key, value)
        except Exception as exc:
            log.warning("cache: Redis unavailable (%s)", exc)
            self._count("errors")
        self.memory.set(key, value)
        return value

    def clear(self, by: str = "") -> None:
        """Empty Redis and this process's memory, and record when and by whom."""
        self.memory.clear()
        try:
            self.shared.clear()
            self.shared.set(
                LAST_CLEARED_KEY, {"at": timezone.now().isoformat(), "by": by}, timeout=None
            )
        except Exception as exc:
            log.warning("cache: could not clear Redis (%s)", exc)
            self._count("errors")

    def stats(self) -> dict[str, Any]:
        """What is easy to know: this process's counters, Redis's own figures, the last clear."""
        shared: dict[str, Any] = {"available": False}
        last_cleared = None
        try:
            client = self.shared._cache.get_client(None, write=False)
            info = client.info()
            hits, misses = info.get("keyspace_hits", 0), info.get("keyspace_misses", 0)
            shared = {
                "available": True,
                "version": info.get("redis_version"),
                "keys": client.dbsize(),
                "used_memory": info.get("used_memory_human"),
                "max_memory": info.get("maxmemory_human"),
                "hits": hits,
                "misses": misses,
                "uptime_seconds": info.get("uptime_in_seconds"),
            }
        except Exception as exc:
            shared["error"] = str(exc)[:200]
        with contextlib.suppress(Exception):
            last_cleared = self.shared.get(LAST_CLEARED_KEY)
        return {
            "process": dict(self.counters),
            "shared": shared,
            "timeouts": {
                "memory_seconds": self.memory.default_timeout,
                "shared_seconds": self.shared.default_timeout,
            },
            "last_cleared": last_cleared,
        }


cache_manager = CacheManager()
