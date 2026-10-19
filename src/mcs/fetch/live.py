"""Live snapshot fetch (spec §6.2): host resolution, robots.txt (canonical + apex), ads.txt,
raw homepage HTML (robots-compliant), DNS TXT via DNS-over-HTTPS."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from mcs.fetch.challenge import is_challenge
from mcs.fetch.direct import Response, get, make_client
from mcs.fetch.ratelimit import HostLimiter
from mcs.fetch.store import FetchLog, FetchRecord, save_body
from mcs.parse.robots import is_allowed, looks_like_html, parse
from mcs.parse.tokens import EXACT, PREFIX, is_wildcard, match_mode

HOSTS_FILE = Path("data/processed/hosts.json")
DOH_URL = "https://dns.google/resolve"


def classify_robots(r: Response) -> tuple[str, bool]:
    """Map a robots.txt response to a §6.4 fetch_status. Returns (status, challenge_detected).

    SOFT_404 and CHALLENGE are the two flavours of the spec's INVALID_HTML.
    """
    if r.error and r.status is None:
        return "NETWORK_ERROR", False
    s = r.status or 0
    chal = is_challenge(r.body, r.content_type)
    if s == 429:
        return "RATE_LIMITED_429", chal
    if 500 <= s <= 599:
        return "UNREACHABLE_5XX", chal
    if 400 <= s <= 499:
        # A WAF challenge served with 403/503 is not "the file doesn't exist".
        return ("CHALLENGE", True) if chal else ("UNAVAILABLE_4XX", False)
    if 200 <= s <= 299:
        if chal:
            return "CHALLENGE", True
        if not r.body.strip():
            return "OK_EMPTY", False
        if looks_like_html(r.body):
            return "SOFT_404", False
        return "OK", False
    if 300 <= s <= 399:
        return "NETWORK_ERROR", False  # redirect loop / too many redirects
    return "NETWORK_ERROR", chal


def _record(domain, host, snapshot, resource, r: Response, *, status=None, chal=False,
            body_kind="bodies", store_body=True) -> FetchRecord:
    rec = FetchRecord(
        domain=domain, host=host, snapshot=snapshot, resource=resource, source="live_direct",
        requested_url=r.requested_url, final_url=r.final_url, redirect_chain=r.chain,
        http_status=r.status, fetch_status=status, content_type=r.content_type,
        bytes=len(r.body), truncated=r.truncated, challenge_detected=chal, error=r.error,
    )
    if store_body and r.body:
        rec.sha256, rec.body_path = save_body(r.body, body_kind)
    return rec


def ua_allows_root(robots_body: bytes | None, status: str, our_token: str) -> bool:
    """Robots compliance for our own UA (fall back to `*`)."""
    if status in ("UNAVAILABLE_4XX", "OK_EMPTY", "SOFT_404"):
        return True
    if status != "OK" or robots_body is None:
        return False  # indeterminate -> be conservative
    p = parse(robots_body)
    named, wild = [], []
    for g in p.groups:
        if any(match_mode(a.raw, our_token) in (EXACT, PREFIX) for a in g.agents):
            named.extend(g.rules)
        if any(is_wildcard(a.raw) for a in g.agents):
            wild.extend(g.rules)
    return is_allowed(named if named else wild, "/")[0]


async def resolve_host(client, lim, domain) -> tuple[str, Response]:
    r = await get(client, lim, f"https://{domain}/", headers_only=True)
    if r.status is None and r.error_kind in ("tls", "connect", "timeout", "other"):
        r2 = await get(client, lim, f"http://{domain}/", headers_only=True)
        if r2.status is not None:
            r = r2
    host = urlsplit(r.final_url).hostname if r.final_url and r.status else None
    return (host or domain).lower(), r


async def fetch_robots(client, lim, host) -> Response:
    r = await get(client, lim, f"https://{host}/robots.txt")
    if r.status is None and r.error_kind in ("tls", "connect", "timeout", "other"):
        r2 = await get(client, lim, f"http://{host}/robots.txt")
        if r2.status is not None:
            return r2
    return r


async def doh_txt(client: httpx.AsyncClient, name: str) -> tuple[list[str], str | None]:
    try:
        resp = await client.get(DOH_URL, params={"name": name, "type": "TXT"})
        data = resp.json()
        return [a.get("data", "") for a in data.get("Answer", []) if a.get("type") == 16], None
    except Exception as e:  # noqa: BLE001
        return [], f"{type(e).__name__}: {e}"[:200]


async def process_domain(client, lim, doh_client, log: FetchLog, snapshot: str, domain: str,
                         *, with_ads: bool, with_signals: bool, our_token: str,
                         hosts: dict, done: set) -> None:
    # 1. host resolution (once per snapshot)
    if (domain, "host") not in done:
        host, hr = await resolve_host(client, lim, domain)
        rec = _record(domain, host, snapshot, "host", hr, store_body=False,
                      status="OK" if hr.status else "NETWORK_ERROR")
        log.append(rec)
        hosts[domain] = host
    host = hosts.get(domain, domain)

    # 2. robots.txt on canonical host (+ apex for QA)
    robots_body, robots_status = None, "NETWORK_ERROR"
    if (domain, "robots") not in done:
        r = await fetch_robots(client, lim, host)
        st, chal = classify_robots(r)
        if host == domain and r.final_url and r.status:
            # Homepage didn't resolve (e.g. tarpitted); fall back to robots.txt's redirect target.
            fh = (urlsplit(r.final_url).hostname or "").lower()
            if fh and fh != domain and fh.endswith("." + domain):
                host = hosts[domain] = fh
        rec = _record(domain, host, snapshot, "robots", r, status=st, chal=chal)
        if r.final_url:
            fh = urlsplit(r.final_url).hostname
            rec.robots_redirected_cross_host = bool(fh and fh.lower() != host)
        log.append(rec)
        robots_body, robots_status = r.body, st
    if host != domain and (domain, "robots_apex") not in done:
        r = await fetch_robots(client, lim, domain)
        st, chal = classify_robots(r)
        log.append(_record(domain, domain, snapshot, "robots_apex", r, status=st, chal=chal))

    # 3. ads.txt
    if with_ads and (domain, "ads") not in done:
        r = await get(client, lim, f"https://{host}/ads.txt", max_bytes=2_000_000)
        st, chal = classify_robots(r)  # same outcome taxonomy
        log.append(_record(domain, host, snapshot, "ads", r, status=st, chal=chal))

    if not with_signals:
        return
    # 4. raw homepage HTML, only if robots.txt allows "/" for our UA
    if (domain, "homepage") not in done:
        if robots_body is None and robots_status == "NETWORK_ERROR":
            # resumed run: reload robots result from log
            for row in reversed(log.read()):
                if row["domain"] == domain and row["resource"] == "robots":
                    from mcs.fetch.store import load_body
                    robots_body, robots_status = load_body(row["body_path"]), row["fetch_status"]
                    break
        if ua_allows_root(robots_body, robots_status, our_token):
            r = await get(client, lim, f"https://{host}/", max_bytes=8_000_000)
            st = "OK" if r.status and 200 <= r.status < 300 else (
                "NETWORK_ERROR" if r.status is None else f"HTTP_{r.status}")
            chal = is_challenge(r.body)
            log.append(_record(domain, host, snapshot, "homepage", r, status=st, chal=chal,
                               body_kind="homepage"))
        else:
            log.append(FetchRecord(domain=domain, host=host, snapshot=snapshot,
                                   resource="homepage", source="live_direct",
                                   requested_url=f"https://{host}/",
                                   fetch_status="DISALLOWED_FOR_US"))
    # 5. DNS TXT of the registered domain apex
    if (domain, "dns") not in done:
        recs, err = await doh_txt(doh_client, domain)
        body = json.dumps(recs).encode()
        rec = FetchRecord(domain=domain, host=domain, snapshot=snapshot, resource="dns",
                          source="doh", requested_url=f"{DOH_URL}?name={domain}&type=TXT",
                          fetch_status="OK" if err is None else "NETWORK_ERROR", error=err,
                          bytes=len(body))
        rec.sha256, rec.body_path = save_body(body)
        log.append(rec)


async def run_live(domains: list[str], snapshot: str, cfg: dict, *, with_ads: bool,
                   signals_domains: set[str] | None = None, progress_every: int = 250) -> dict:
    rl = cfg["rate_limits"]
    ua = cfg["identity"]["user_agent"]
    our_token = ua.split("/", 1)[0].lower()
    lim = HostLimiter(rl["per_host_min_interval_s"], rl["global_concurrency"])
    log = FetchLog(snapshot)
    done = log.done_keys()
    hosts: dict[str, str] = {}
    for row in log.read():
        if row["resource"] == "host":
            hosts[row["domain"]] = row["host"]
    signals_domains = signals_domains or set()
    sem = asyncio.Semaphore(rl["global_concurrency"] * 2)
    t0 = time.time()
    counter = {"n": 0}

    async with make_client(ua, rl["connect_timeout_s"], rl["read_timeout_s"]) as client, \
            httpx.AsyncClient(timeout=15, headers={"User-Agent": ua, "accept":
                              "application/dns-json"}) as doh:

        async def worker(d):
            async with sem:
                try:
                    await process_domain(client, lim, doh, log, snapshot, d, with_ads=with_ads,
                                         with_signals=d in signals_domains,
                                         our_token=our_token, hosts=hosts, done=done)
                except Exception as e:  # noqa: BLE001
                    print(f"[{snapshot}] {d}: unexpected {e!r}", file=sys.stderr)
                counter["n"] += 1
                if counter["n"] % progress_every == 0:
                    print(f"[{snapshot}] {counter['n']}/{len(domains)} "
                          f"({time.time() - t0:.0f}s)", flush=True)

        await asyncio.gather(*(worker(d) for d in domains))

    HOSTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    prev = json.loads(HOSTS_FILE.read_text()) if HOSTS_FILE.exists() else {}
    prev.update(hosts)
    HOSTS_FILE.write_text(json.dumps(prev, indent=0, sort_keys=True))
    return {"domains": len(domains), "seconds": round(time.time() - t0)}
