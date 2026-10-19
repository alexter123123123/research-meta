"""Per-host politeness: 1 concurrent request per host, min interval between requests."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict


class HostLimiter:
    def __init__(self, min_interval_s: float = 2.0, global_concurrency: int = 25):
        self.min_interval = min_interval_s
        self.global_sem = asyncio.Semaphore(global_concurrency)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last: dict[str, float] = {}

    def host_slot(self, host: str) -> _Slot:
        return _Slot(self, host.lower())


class _Slot:
    def __init__(self, lim: HostLimiter, host: str):
        self.lim, self.host = lim, host

    async def __aenter__(self):
        await self.lim._locks[self.host].acquire()
        wait = self.lim._last.get(self.host, 0) + self.lim.min_interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        await self.lim.global_sem.acquire()

    async def __aexit__(self, *exc):
        self.lim.global_sem.release()
        self.lim._last[self.host] = time.monotonic()
        self.lim._locks[self.host].release()
