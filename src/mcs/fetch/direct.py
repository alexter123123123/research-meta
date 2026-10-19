"""Direct HTTP client (spec §6.1): our UA, no cookies, per-host politeness, bounded retries."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import httpx

from mcs.fetch.ratelimit import HostLimiter

RETRY_STATUSES = {429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
MAX_RETRY_AFTER = 120.0


@dataclass
class Response:
    requested_url: str
    final_url: str | None = None
    status: int | None = None
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    truncated: bool = False
    chain: list[str] = field(default_factory=list)
    error: str | None = None
    error_kind: str | None = None  # dns|connect|tls|timeout|other

    @property
    def content_type(self) -> str | None:
        return self.headers.get("content-type")


class _NoCookies(httpx.Cookies):
    def extract_cookies(self, response):  # never store cookies
        return None


def make_client(user_agent: str, connect_timeout: float = 10, read_timeout: float = 20
                ) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        http2=False,
        follow_redirects=False,
        timeout=httpx.Timeout(read_timeout, connect=connect_timeout),
        headers={
            "User-Agent": user_agent,
            "Accept": "text/plain,text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "en",
        },
        cookies=_NoCookies(),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )


def _kind(exc: Exception) -> str:
    s = repr(exc).lower()
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if "name or service not known" in s or "nodename nor servname" in s or "getaddrinfo" in s \
            or "no address" in s or "temporary failure in name resolution" in s:
        return "dns"
    if "ssl" in s or "certificate" in s or "tls" in s:
        return "tls"
    if isinstance(exc, httpx.ConnectError):
        return "connect"
    return "other"


def _retry_after(headers) -> float | None:
    v = headers.get("retry-after")
    if not v:
        return None
    try:
        return min(float(v), MAX_RETRY_AFTER)
    except ValueError:
        try:
            from datetime import UTC, datetime
            return min(max((parsedate_to_datetime(v) - datetime.now(UTC)).total_seconds(), 0),
                       MAX_RETRY_AFTER)
        except Exception:
            return None


async def _one(client: httpx.AsyncClient, lim: HostLimiter, url: str, max_bytes: int,
               headers_only: bool) -> Response:
    host = urlsplit(url).hostname or ""
    r = Response(requested_url=url)
    async with lim.host_slot(host):
        try:
            async with client.stream("GET", url) as resp:
                r.status = resp.status_code
                r.headers = {k.lower(): v for k, v in resp.headers.items()}
                r.final_url = str(resp.url)
                if headers_only or 300 <= resp.status_code < 400:
                    return r
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        r.truncated = True
                        break
                r.body = bytes(buf[:max_bytes]) if r.truncated else bytes(buf)
        except Exception as e:  # noqa: BLE001
            r.error = f"{type(e).__name__}: {e}"[:300]
            r.error_kind = _kind(e)
    return r


async def get(client: httpx.AsyncClient, lim: HostLimiter, url: str, *, max_bytes: int = 512000,
              max_redirects: int = 5, max_retries: int = 2, headers_only: bool = False
              ) -> Response:
    """GET with manual redirect following (chain recorded) and bounded retries.

    Retries only on network errors and 5xx/429, with exponential backoff + jitter,
    honouring Retry-After.
    """
    chain: list[str] = []
    current = url
    for _hop in range(max_redirects + 1):
        attempt = 0
        while True:
            r = await _one(client, lim, current, max_bytes, headers_only)
            retryable = r.error is not None and r.error_kind not in ("dns", "tls") or (
                r.status in RETRY_STATUSES)
            if not retryable or attempt >= max_retries:
                break
            attempt += 1
            delay = _retry_after(r.headers) if r.status in (429, 503) else None
            if delay is None:
                delay = (2 ** attempt) + random.uniform(0, 1.5)
            await asyncio.sleep(delay)
        chain.append(current)
        if r.status and 300 <= r.status < 400 and r.headers.get("location"):
            current = urljoin(current, r.headers["location"].strip())
            continue
        r.requested_url = url
        r.chain = chain
        r.final_url = r.final_url or current
        return r
    r.requested_url = url
    r.chain = chain
    r.error = r.error or "too many redirects"
    r.error_kind = r.error_kind or "other"
    return r
