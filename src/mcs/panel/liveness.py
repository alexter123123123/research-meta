"""Liveness check for Tier B candidates (SPEC §4.2, politeness per §6.1/§11).

Per domain:
1. Resolve ``domain`` (then ``www.domain``) with the local resolver. No address => drop (dns).
2. GET ``https://domain/robots.txt`` (``http://`` if https fails at connection level),
   following <=5 redirects. robots.txt itself may be fetched by convention.
3. If robots.txt permits ``/`` for our UA token (RFC 9309: 4xx => allow, 5xx => disallow),
   GET ``/`` following <=5 redirects manually, re-checking robots.txt for every new host.
   404 at root => drop. If ``/`` is disallowed, the robots.txt response itself proves the host
   is alive (``method=robots``).
4. No HTTP response at all on either scheme => drop (unreachable).

Max 1 request in flight per host, >=2 s between requests to a host, global concurrency <=25.
Results are cached in ``data/panel/sources/liveness/results.jsonl`` (robots.txt bodies included)
so reruns do not refetch.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import socket
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from mcs.panel.http import SOURCES, AsyncHostPacer, _no_cookie_jar, robots_from_response, ua_token

CACHE = SOURCES / "liveness" / "results.jsonl"


_CLIENT: contextvars.ContextVar[httpx.AsyncClient] = contextvars.ContextVar("liveness_client")

# Outcomes that prove a domain dead; everything else that failed is transient/local.
DEFINITIVE_MARKERS = ("Name or service not known", "No address associated with hostname",
                      "404 at root", "CERTIFICATE_VERIFY_FAILED", "certificate verify failed")


def is_definitive_failure(rec: dict) -> bool:
    if rec.get("ok"):
        return False
    if rec.get("liveness_method") == "dns":
        return any(m in rec.get("error", "") for m in DEFINITIVE_MARKERS[:2])
    if rec.get("liveness_method") == "homepage" and rec.get("status") == 404:
        return True
    if rec.get("liveness_method") == "unreachable":
        # a TLS certificate failure on https (with http also failing) is definitive
        return "CERTIFICATE_VERIFY_FAILED" in rec.get("error", "") or \
            "certificate verify failed" in rec.get("error", "")
    return False


def is_transient_failure(rec: dict) -> bool:
    return not rec.get("ok") and not is_definitive_failure(rec)


class Checker:
    def __init__(self, user_agent: str, rl: dict, concurrency: int | None = None,
                 pool_timeout: float = 30.0):
        self.ua = user_agent
        self.token = ua_token(user_agent)
        self.concurrency = int(concurrency or rl.get("global_concurrency", 25))
        self.pacer = AsyncHostPacer(float(rl.get("per_host_min_interval_s", 2.0)), self.concurrency)
        self.max_redirects = int(rl.get("max_redirects", 5))
        self.timeout = httpx.Timeout(float(rl.get("read_timeout_s", 20)),
                                     connect=float(rl.get("connect_timeout_s", 10)),
                                     pool=pool_timeout)
        self.robots_cache: dict[str, tuple] = {}  # scheme://host -> (RobotsResult, status)

    def new_client(self) -> httpx.AsyncClient:
        """A fresh client per domain check: no pool shared across domains (avoids the pool
        saturation / PoolTimeout seen with one long-lived client behind the proxy)."""
        return httpx.AsyncClient(
            headers={"User-Agent": self.ua}, timeout=self.timeout, follow_redirects=False,
            cookies=_no_cookie_jar(),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )

    @property
    def client(self) -> httpx.AsyncClient:
        return _CLIENT.get()

    async def _get(self, url: str) -> httpx.Response:
        host = urlsplit(url).hostname or ""
        async with self.pacer.lock(host):
            await self.pacer.wait(host)
            async with self.pacer.sem:
                try:
                    r = await self.client.get(url)
                    await r.aread()
                    return r
                finally:
                    self.pacer.mark(host)
                    self.client.cookies.clear()

    async def _get_follow(self, url: str, robots_check: bool) -> tuple[httpx.Response | None, str, list[str], str]:
        """Follow redirects manually. Returns (response, final_url, chain, stop_reason)."""
        chain = [url]
        for _ in range(self.max_redirects + 1):
            if robots_check:
                rr = await self.robots_for(url)
                if not rr.can_fetch(url, self.token):
                    return None, url, chain, "robots-disallowed"
            r = await self._get(url)
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                chain.append(url)
                continue
            return r, str(r.url), chain, ""
        return None, url, chain, "too-many-redirects"

    async def robots_for(self, url: str):
        sp = urlsplit(url)
        key = f"{sp.scheme}://{sp.netloc}"
        if key not in self.robots_cache:
            try:
                r, _, _, _ = await self._get_follow(key + "/robots.txt", robots_check=False)
                status, body = (r.status_code, r.content) if r is not None else (None, b"")
            except httpx.HTTPError:
                status, body = None, b""
            self.robots_cache[key] = (robots_from_response(sp.netloc, status, body), status, body)
        return self.robots_cache[key][0]

    @staticmethod
    async def resolves(host: str) -> tuple[bool | None, str]:
        """True = resolves; False = authoritative no-such-name/no-address; None = transient."""
        loop = asyncio.get_running_loop()
        err = ""
        for attempt in range(4):
            try:
                await asyncio.wait_for(loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM), 15)
                return True, ""
            except socket.gaierror as e:
                if e.errno in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", -5)):
                    return False, f"dns: {e}"
                err = f"dns: {e}"
            except asyncio.TimeoutError:
                err = "dns: timeout"
            await asyncio.sleep(2 * (attempt + 1))
        return None, err

    async def check(self, domain: str) -> dict:
        async with self.new_client() as client:
            tok = _CLIENT.set(client)
            try:
                return await self._check(domain)
            finally:
                _CLIENT.reset(tok)

    async def _check(self, domain: str) -> dict:
        rec = {"domain": domain, "ok": False, "final_url": "", "status": None, "error": "",
               "liveness_method": "", "robots_status": None, "robots_url": "",
               "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        ok1, e1 = await self.resolves(domain)
        if not ok1:
            ok2, e2 = await self.resolves("www." + domain)
            if ok2 is False and ok1 is False:
                rec.update(error=e1, liveness_method="dns")
                return rec
            if not ok2:
                # transient resolver failure: not a verdict; retried on the next run
                rec.update(error=f"{e1}; www: {e2}", liveness_method="error")
                return rec
        # robots.txt (https, then http on connection failure)
        robots_resp = None
        errors = []
        for scheme in ("https", "http"):
            url = f"{scheme}://{domain}/robots.txt"
            try:
                r, final, chain, _ = await self._get_follow(url, robots_check=False)
                robots_resp = (scheme, r, final)
                break
            except httpx.HTTPError as e:
                errors.append(f"{scheme} robots: {type(e).__name__}: {str(e)[:120]}")
        if robots_resp is None:
            rec.update(error="; ".join(errors), liveness_method="unreachable")
            return rec
        scheme, r, final = robots_resp
        rr = robots_from_response(urlsplit(final).netloc, r.status_code, r.content)
        self.robots_cache[f"{scheme}://{domain}"] = (rr, r.status_code, r.content)
        rec["robots_status"] = r.status_code
        rec["robots_url"] = final
        rec["robots_body"] = r.content[:100_000].decode("utf-8", "replace") if r.status_code < 300 else ""
        home = f"{scheme}://{domain}/"
        if not rr.can_fetch(home, self.token):
            rec.update(ok=True, final_url=final, status=r.status_code, liveness_method="robots",
                       error="'/' disallowed (or robots 5xx) for our UA; robots.txt response counted as alive")
            return rec
        try:
            hr, hfinal, chain, stop = await self._get_follow(home, robots_check=True)
        except httpx.HTTPError as e:
            rec.update(ok=True, final_url=final, status=r.status_code, liveness_method="robots",
                       error=f"homepage {type(e).__name__}: {str(e)[:120]}; robots.txt responded")
            return rec
        if hr is None:
            rec.update(ok=True, final_url=hfinal, status=r.status_code, liveness_method="robots",
                       error=f"homepage stopped: {stop}")
            return rec
        rec.update(final_url=hfinal, status=hr.status_code, liveness_method="homepage")
        if hr.status_code == 404:
            rec.update(ok=False, error="404 at root")
        else:
            rec["ok"] = True
        return rec

    async def aclose(self):
        pass


def load_cache(path: Path = CACHE) -> dict[str, dict]:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                if d.get("liveness_method") != "error":  # transient checker errors are retried
                    out[d["domain"]] = d
    return out


async def _run(domains: list[str], user_agent: str, rl: dict, progress_every: int = 100,
               cache_path: Path = CACHE, concurrency: int | None = None) -> dict[str, dict]:
    cache = load_cache(cache_path)
    todo = [d for d in domains if d not in cache]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    chk = Checker(user_agent, rl, concurrency=concurrency)
    done = 0
    t0 = time.time()
    q: asyncio.Queue = asyncio.Queue()
    for d in todo:
        q.put_nowait(d)

    async def worker():
        nonlocal done
        with cache_path.open("a") as fh:
            while True:
                try:
                    d = q.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    rec = await asyncio.wait_for(chk.check(d), 300)
                except Exception as e:  # never let one domain kill the run
                    rec = {"domain": d, "ok": False, "final_url": "", "status": None,
                           "error": f"checker error: {type(e).__name__}: {str(e)[:150]}",
                           "liveness_method": "error"}
                cache[d] = rec
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                done += 1
                if done % progress_every == 0:
                    print(f"[liveness] {done}/{len(todo)} in {time.time() - t0:.0f}s", flush=True)

    # Distinct domains are distinct hosts; the pacer still serialises per host.
    n_workers = chk.concurrency
    try:
        await asyncio.gather(*(worker() for _ in range(n_workers)))
    finally:
        await chk.aclose()
    return {d: cache[d] for d in domains}


CACHE_PASS2 = SOURCES / "liveness" / "results_pass2.jsonl"


def check_domains(domains: list[str], user_agent: str, rl: dict) -> dict[str, dict]:
    return asyncio.run(_run(domains, user_agent, rl))


def recheck_transient(domains: list[str], user_agent: str, rl: dict, concurrency: int = 5) -> dict[str, dict]:
    """Second pass for transient failures: low concurrency, fresh clients, generous pool timeout."""
    return asyncio.run(_run(domains, user_agent, rl, progress_every=25, cache_path=CACHE_PASS2,
                            concurrency=concurrency))
