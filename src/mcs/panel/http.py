"""Polite HTTP helpers for panel building (SPEC §6.1, §11).

* Every request carries the study User-Agent from config; cookies are never stored or sent.
* robots.txt of each host is read (and cached) before any other path on that host is fetched,
  and obeyed for our UA token (Protego falls back to ``*``).
* >= 2 s between requests to the same host, 1 in flight per host; the async variant also caps
  global concurrency.
* Every downloaded source file is cached under ``data/panel/sources/`` so reruns do not refetch.
"""

from __future__ import annotations

import asyncio
import hashlib
import http.cookiejar
import json
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import yaml
from protego import Protego

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCES = REPO_ROOT / "data" / "panel" / "sources"


def load_config(config_path: str | Path = "config/study.yaml") -> dict:
    p = Path(config_path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return yaml.safe_load(p.read_text())


def ua_token(user_agent: str) -> str:
    """Product token of our UA (``MetaCrawlerStudy/1.0 (...)`` -> ``MetaCrawlerStudy``)."""
    return user_agent.split("/", 1)[0].split()[0]


def _no_cookie_jar() -> http.cookiejar.CookieJar:
    return http.cookiejar.CookieJar(policy=http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))


def safe_name(s: str, maxlen: int = 150) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")
    if len(s) > maxlen:
        s = s[:maxlen] + "_" + hashlib.sha1(s.encode()).hexdigest()[:10]
    return s


class RobotsDisallowed(Exception):
    pass


@dataclass
class RobotsResult:
    host: str
    status: int | None  # None = network error
    parser: Protego | None
    allow_all: bool
    disallow_all: bool

    def can_fetch(self, url: str, token: str) -> bool:
        if self.allow_all:
            return True
        if self.disallow_all or self.parser is None:
            return False
        return self.parser.can_fetch(url, token)


def robots_from_response(host: str, status: int | None, body: bytes | None) -> RobotsResult:
    """RFC 9309: 2xx parse; 4xx allow all; 5xx / unreachable -> disallow all."""
    if status is None or status >= 500 or status == 429:
        return RobotsResult(host, status, None, False, True)
    if 400 <= status < 500:
        return RobotsResult(host, status, None, True, False)
    text = (body or b"")[:512000].decode("utf-8", errors="replace")
    return RobotsResult(host, status, Protego.parse(text), False, False)


class PoliteClient:
    """Synchronous polite client used for the handful of source documents."""

    def __init__(self, user_agent: str, min_interval: float = 2.0, connect_timeout: float = 10,
                 read_timeout: float = 20, max_retries: int = 2, max_redirects: int = 5):
        self.ua = user_agent
        self.token = ua_token(user_agent)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.connect_timeout = connect_timeout
        self.total_timeout = connect_timeout + read_timeout
        self.max_redirects = max_redirects
        self.client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=httpx.Timeout(read_timeout, connect=connect_timeout),
            follow_redirects=True, max_redirects=max_redirects, cookies=_no_cookie_jar(),
        )
        self._last: dict[str, float] = {}
        self._robots: dict[str, RobotsResult] = {}
        self._lock = threading.Lock()
        self.log: list[dict] = []

    # -- pacing -----------------------------------------------------------------
    def _pace(self, host: str, extra: float = 0.0) -> None:
        with self._lock:
            last = self._last.get(host)
            now = time.monotonic()
            wait = 0.0 if last is None else self.min_interval + extra - (now - last)
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()

    def _httpx_get(self, url: str, headers: dict | None, timeout: float | None) -> "SimpleResponse":
        kw = {"headers": headers or {}}
        if timeout:
            kw["timeout"] = httpx.Timeout(timeout, connect=self.connect_timeout)
        r = self.client.get(url, **kw)
        self.client.cookies.clear()
        return SimpleResponse(r.status_code, str(r.url),
                              {k.lower(): v for k, v in r.headers.items()}, r.content)

    def _raw_get(self, url: str, headers: dict | None = None, timeout: float | None = None) -> "SimpleResponse":
        host = urlsplit(url).hostname or ""
        attempt = 0
        extra = 0.0
        while True:
            self._pace(host, extra)
            try:
                r = self._httpx_get(url, headers, timeout)
                final_host = urlsplit(r.url).hostname
                if final_host and final_host != host:
                    self._last[final_host] = time.monotonic()
                self.log.append({"url": url, "status": r.status_code, "final_url": r.url,
                                 "ts": time.time()})
                if (r.status_code >= 500 or r.status_code == 429) and attempt < self.max_retries:
                    ra = r.headers.get("retry-after", "")
                    if ra.isdigit() and float(ra) > 120:
                        return r  # server asks us to stay away for long: give up, don't hammer
                    extra = float(ra) if ra.isdigit() else (2 ** attempt) * 5 + random.random()
                    attempt += 1
                    continue
                return r
            except httpx.TransportError as e:
                self.log.append({"url": url, "status": None, "error": repr(e), "ts": time.time()})
                if attempt < self.max_retries:
                    extra = (2 ** attempt) * 3 + random.random()
                    attempt += 1
                    continue
                raise

    # -- robots -----------------------------------------------------------------
    def robots(self, url: str) -> RobotsResult:
        sp = urlsplit(url)
        key = f"{sp.scheme}://{sp.netloc}"
        if key in self._robots:
            return self._robots[key]
        cache = SOURCES / "robots" / (safe_name(sp.netloc) + ".robots.json")
        if cache.exists():
            d = json.loads(cache.read_text())
            res = robots_from_response(sp.netloc, d["status"], d["body"].encode())
        else:
            try:
                r = self._raw_get(key + "/robots.txt")
                status, body = r.status_code, r.content
            except httpx.TransportError:
                status, body = None, b""
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"url": key + "/robots.txt", "status": status,
                                         "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                         "body": body.decode("utf-8", errors="replace")}))
            res = robots_from_response(sp.netloc, status, body)
        self._robots[key] = res
        return res

    def allowed(self, url: str) -> bool:
        return self.robots(url).can_fetch(url, self.token)

    # -- cached fetch -----------------------------------------------------------
    def get(self, url: str, cache_name: str, headers: dict | None = None,
            timeout: float | None = None, check_robots: bool = True,
            cache_errors: bool = False) -> tuple[bytes, dict]:
        """Return (body, meta) from cache or network. Raises RobotsDisallowed / httpx errors."""
        path = SOURCES / cache_name
        meta_path = path.with_name(path.name + ".meta.json")
        if path.exists() and meta_path.exists():
            return path.read_bytes(), json.loads(meta_path.read_text())
        if check_robots and not self.allowed(url):
            raise RobotsDisallowed(url)
        r = self._raw_get(url, headers=headers, timeout=timeout)
        meta = {"url": url, "final_url": r.url, "status": r.status_code,
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "headers": {k: v for k, v in r.headers.items()
                            if k.lower() in ("content-type", "last-modified", "etag",
                                             "content-disposition", "date")},
                "sha256": hashlib.sha256(r.content).hexdigest()}
        if r.status_code == 200 or cache_errors:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
            meta_path.write_text(json.dumps(meta, indent=1))
        return r.content, meta

    def close(self):
        self.client.close()


@dataclass
class SimpleResponse:
    status_code: int
    url: str
    headers: dict
    content: bytes


# ---------------------------------------------------------------------------------------------
# Async liveness checker (many hosts)
# ---------------------------------------------------------------------------------------------

class AsyncHostPacer:
    def __init__(self, min_interval: float, global_concurrency: int):
        self.min_interval = min_interval
        self.sem = asyncio.Semaphore(global_concurrency)
        self.locks: dict[str, asyncio.Lock] = {}
        self.last: dict[str, float] = {}

    def lock(self, host: str) -> asyncio.Lock:
        if host not in self.locks:
            self.locks[host] = asyncio.Lock()
        return self.locks[host]

    async def wait(self, host: str):
        last = self.last.get(host)
        if last is not None:
            d = self.min_interval - (time.monotonic() - last)
            if d > 0:
                await asyncio.sleep(d)

    def mark(self, host: str):
        self.last[host] = time.monotonic()
