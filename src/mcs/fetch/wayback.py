"""Wayback Machine baselines + version history (spec §6.5) and Meta docs history (§6.6).

Politeness: one connection, >=1 s between requests, exponential backoff on 429/503 and
connection resets (30 s doubling to 10 min). Everything is cached on disk so a capture
is never fetched twice; runs are resumable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from mcs.fetch.store import FetchLog, FetchRecord, now_iso, save_body
from mcs.parse.robots import parse
from mcs.parse.tokens import EXACT, PREFIX, is_wildcard, match_mode

CDX = "https://web.archive.org/cdx/search/cdx"
WB_DIR = Path("data/raw/wayback")
DIGEST_MAP = WB_DIR / "digests.json"  # wayback digest -> {sha256, body_path, status}
FULL_FETCH_MAX = 12
_TS_IN_URL = re.compile(r"/web/(\d{14})")


def ts_to_dt(ts: str) -> datetime:
    return datetime.strptime(ts[:14], "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def iso_to_ts(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y%m%d%H%M%S")


class Wayback:
    def __init__(self, user_agent: str, min_interval: float = 1.0, backoff_start: float = 30,
                 backoff_max: float = 600):
        self.ua = user_agent
        self.min_interval = min_interval
        self.backoff_start, self.backoff_max = backoff_start, backoff_max
        self._last = 0.0
        self._lock = asyncio.Lock()
        self.client = httpx.AsyncClient(
            headers={"User-Agent": user_agent}, timeout=httpx.Timeout(60, connect=20),
            follow_redirects=True, limits=httpx.Limits(max_connections=1),
        )
        self.requests = 0
        self.digests: dict = json.loads(DIGEST_MAP.read_text()) if DIGEST_MAP.exists() else {}

    async def close(self):
        await self.client.aclose()
        self.save_digests()

    def save_digests(self):
        DIGEST_MAP.parent.mkdir(parents=True, exist_ok=True)
        DIGEST_MAP.write_text(json.dumps(self.digests, sort_keys=True))

    async def _get(self, url: str, params: dict | None = None) -> httpx.Response | None:
        backoff = self.backoff_start
        for _attempt in range(8):
            async with self._lock:
                wait = self._last + self.min_interval - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    resp = await self.client.get(url, params=params)
                    err = None
                except httpx.HTTPError as e:
                    resp, err = None, e
                finally:
                    self._last = time.monotonic()
                    self.requests += 1
            if resp is not None and resp.status_code not in (429, 503, 502, 504):
                return resp
            print(f"[wayback] backoff {backoff:.0f}s on {url[:100]} "
                  f"({resp.status_code if resp is not None else err!r})", file=sys.stderr)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.backoff_max)
        return None

    async def cdx(self, url_key: str, frm: str, to: str, cache_name: str) -> list[dict]:
        cache = WB_DIR / "cdx" / f"{cache_name}.json"
        if cache.exists():
            return json.loads(cache.read_text())
        resp = await self._get(CDX, {
            "url": url_key, "matchType": "exact", "from": frm, "to": to, "output": "json",
            "fl": "timestamp,original,statuscode,mimetype,digest,length",
            "collapse": "digest",
        })
        if resp is None or resp.status_code != 200:
            return []  # not cached -> retried next run
        try:
            data = resp.json() if resp.text.strip() else []
        except ValueError:
            return []
        rows = [dict(zip(data[0], r, strict=False)) for r in data[1:]] if data else []
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rows))
        return rows

    async def capture(self, row: dict, kind: str = "bodies") -> dict:
        """Fetch raw bytes of a capture (id_), cached by digest."""
        dg = row["digest"]
        if dg in self.digests:
            return self.digests[dg]
        url = f"https://web.archive.org/web/{row['timestamp']}id_/{row['original']}"
        resp = await self._get(url)
        if resp is None:
            return {"status": None, "error": "wayback unreachable"}
        m = _TS_IN_URL.search(str(resp.url))
        out = {
            "status": resp.status_code,
            "landed_ts": m.group(1) if m else row["timestamp"],
            "final_url": str(resp.url),
            "content_type": resp.headers.get("content-type"),
        }
        if resp.status_code == 200:
            out["sha256"], out["body_path"] = save_body(resp.content, kind)
            out["bytes"] = len(resp.content)
        self.digests[dg] = out
        if len(self.digests) % 50 == 0:
            self.save_digests()
        return out


# ---------------------------------------------------------------------------

META_SIG_TOKENS = ["meta-externalagent", "meta-externalads", "meta-webindexer",
                   "meta-externalfetcher", "facebookexternalhit", "facebookbot", "facebot",
                   "facebookcatalog"]


def meta_signature(body: bytes | None, status: str) -> str:
    """Probe-independent signature of what applies to Meta tokens. Equal signature =>
    equal verdicts for any probe set."""
    if body is None:
        return f"status:{status}"
    p = parse(body)
    sig = {}
    for tok in META_SIG_TOKENS:
        named, wild = [], []
        for g in p.groups:
            if any(match_mode(a.raw, tok) in (EXACT, PREFIX) for a in g.agents):
                named += [(r.type, r.path) for r in g.rules]
            if any(is_wildcard(a.raw) for a in g.agents):
                wild += [(r.type, r.path) for r in g.rules]
        sig[tok] = ("N", sorted(named)) if named else ("W", sorted(wild))
    return hashlib.sha1(json.dumps(sig).encode()).hexdigest()


def _status_of(code: str) -> str:
    if code.startswith("2"):
        return "OK"
    if code.startswith("3"):
        return "REDIRECT"
    if code == "429":
        return "RATE_LIMITED_429"
    if code.startswith("4"):
        return "UNAVAILABLE_4XX"
    if code.startswith("5"):
        return "UNREACHABLE_5XX"
    return "UNKNOWN"


def select_rows(rows: list[dict], canonical: str, domain: str) -> tuple[list[dict], bool]:
    """Rows for the canonical host; fall back to apex/www rows (flagged)."""
    def host(r):
        return (urlsplit(r["original"]).hostname or "").lower()
    exact = [r for r in rows if host(r) == canonical]
    if exact:
        return exact, False
    alt = {domain, "www." + domain}
    return [r for r in rows if host(r) in alt], True


async def history_for_domain(wb: Wayback, log: FetchLog, domain: str, canonical: str,
                             frm: str, to: str, cutoffs: dict[str, str]) -> None:
    rows = await wb.cdx(f"{domain}/robots.txt", frm, to, domain)
    if canonical not in (domain, "www." + domain):
        rows = rows + await wb.cdx(f"{canonical}/robots.txt", frm, to, canonical)
    rows, host_fallback = select_rows(rows, canonical, domain)
    rows = sorted({r["timestamp"]: r for r in rows}.values(), key=lambda r: r["timestamp"])
    # Revisit records ("-" status / warc/revisit) inherit the previous status for that digest.
    last_status: dict[str, str] = {}
    for r in rows:
        if r["statuscode"] in ("-", ""):
            r["statuscode"] = last_status.get(r["digest"], "200")
        last_status[r["digest"]] = r["statuscode"]
    # Collapse consecutive identical (digest, status) into versions.
    versions: list[dict] = []
    for r in rows:
        if versions and versions[-1]["digest"] == r["digest"] \
                and versions[-1]["statuscode"] == r["statuscode"]:
            versions[-1]["last_ts"] = r["timestamp"]
            continue
        versions.append({**r, "first_ts": r["timestamp"], "last_ts": r["timestamp"]})
    if not versions:
        log.append(FetchRecord(domain=domain, host=canonical, snapshot="WB", resource="robots",
                               source="wayback", requested_url=f"cdx:{domain}/robots.txt",
                               fetch_status="NO_CAPTURE"))
        return

    def pick(cutoff_ts: str) -> int | None:
        idx = None
        for i, v in enumerate(versions):
            if v["timestamp"] <= cutoff_ts:
                idx = i
        return idx

    must = {len(versions) - 1}
    for c in cutoffs.values():
        i = pick(c)
        if i is not None:
            must.add(i)

    fetched: dict[int, str] = {}

    async def fetch_idx(i: int) -> str:
        if i in fetched:
            return fetched[i]
        v = versions[i]
        st = _status_of(v["statuscode"])
        cap = None
        body = None
        if st in ("OK", "REDIRECT"):
            cap = await wb.capture(v)
            if cap.get("status") == 200 and cap.get("body_path"):
                from mcs.fetch.store import load_body
                body = load_body(cap["body_path"])
                st = "OK"
            elif cap.get("status") is None:
                st = "WAYBACK_ERROR"
            elif cap.get("status") in (404, 410):
                st = "UNAVAILABLE_4XX"
            else:
                st = _status_of(str(cap.get("status")))
        from mcs.fetch.direct import Response
        from mcs.fetch.live import classify_robots
        if st == "OK" and body is not None:
            st, chal = classify_robots(Response(requested_url="", status=200, body=body,
                                                headers={"content-type":
                                                         (cap or {}).get("content_type") or ""}))
        else:
            chal = False
        prev_ts = versions[i - 1]["last_ts"] if i > 0 else None
        rec = FetchRecord(
            domain=domain, host=canonical, snapshot="WB", resource="robots", source="wayback",
            requested_url=f"https://web.archive.org/web/{v['timestamp']}id_/{v['original']}",
            final_url=(cap or {}).get("final_url"),
            http_status=int(v["statuscode"]) if v["statuscode"].isdigit() else None,
            fetch_status=st, content_type=(cap or {}).get("content_type"),
            bytes=(cap or {}).get("bytes", 0), sha256=(cap or {}).get("sha256"),
            body_path=(cap or {}).get("body_path"), wayback_ts=v["first_ts"],
            challenge_detected=chal,
            error=json.dumps({"last_ts": v["last_ts"], "prev_capture_ts": prev_ts,
                              "host_fallback": host_fallback, "digest": v["digest"],
                              "landed_ts": (cap or {}).get("landed_ts")}),
        )
        log.append(rec)
        sig = meta_signature(body, st)
        fetched[i] = sig
        return sig

    if len(versions) <= FULL_FETCH_MAX:
        for i in range(len(versions)):
            await fetch_idx(i)
        return
    # Bisection between fetched versions whose Meta signature differs.
    first = 0
    must.add(first)
    for i in sorted(must):
        await fetch_idx(i)
    changed = True
    while changed:
        changed = False
        idxs = sorted(fetched)
        for a, b in zip(idxs, idxs[1:], strict=False):
            if b - a > 1 and fetched[a] != fetched[b]:
                await fetch_idx((a + b) // 2)
                changed = True
                break


async def run_history(domains: list[str], hosts: dict[str, str], cfg: dict, frm: str, to: str,
                      deadline_s: float | None = None) -> dict:
    ua = cfg["identity"]["user_agent"]
    wcfg = cfg["wayback"]
    wb = Wayback(ua, wcfg["min_interval_s"], wcfg["backoff_start_s"], wcfg["backoff_max_s"])
    log = FetchLog("WB")
    done = {r["domain"] for r in log.read()}
    cutoffs = {k: iso_to_ts(cfg["snapshots"][k]["cutoff"]) for k in ("T0", "T1")}
    t0 = time.time()
    n = 0
    try:
        for d in domains:
            if d in done:
                continue
            if deadline_s and time.time() - t0 > deadline_s:
                print(f"[wayback] deadline reached after {n} domains; resume later")
                break
            try:
                await history_for_domain(wb, log, d, hosts.get(d, d), frm, to, cutoffs)
            except Exception as e:  # noqa: BLE001
                print(f"[wayback] {d}: {e!r}", file=sys.stderr)
            n += 1
            if n % 50 == 0:
                print(f"[wayback] {n} domains, {wb.requests} requests, "
                      f"{time.time() - t0:.0f}s", flush=True)
    finally:
        await wb.close()
    return {"domains_processed": n, "requests": wb.requests, "seconds": round(time.time() - t0)}


async def run_wayback_homepages(targets: list[tuple[str, str]], cfg: dict, frm: str,
                                to: str) -> dict:
    """§8.3: homepage disallowed for us (or blocked) -> latest capture within 30 days."""
    wb = Wayback(cfg["identity"]["user_agent"], cfg["wayback"]["min_interval_s"],
                 cfg["wayback"]["backoff_start_s"], cfg["wayback"]["backoff_max_s"])
    log = FetchLog("WB_HOME")
    done = {r["domain"] for r in log.read()}
    n = ok = 0
    try:
        for domain, host in targets:
            if domain in done:
                continue
            rows = await wb.cdx(f"{host}/", frm, to, "home_" + host)
            rows = [r for r in rows if r["statuscode"].startswith("2")
                    and "html" in (r.get("mimetype") or "")]
            rec = FetchRecord(domain=domain, host=host, snapshot="WB_HOME",
                              resource="homepage_wayback", source="wayback",
                              requested_url=f"cdx:{host}/", fetch_status="NO_CAPTURE")
            if rows:
                r = rows[-1]
                cap = await wb.capture(r, "homepage")
                rec.requested_url = f"https://web.archive.org/web/{r['timestamp']}id_/{r['original']}"
                rec.final_url = r["original"]
                rec.http_status = cap.get("status")
                rec.sha256, rec.body_path = cap.get("sha256"), cap.get("body_path")
                rec.wayback_ts = r["timestamp"]
                rec.fetch_status = "OK" if cap.get("body_path") else "WAYBACK_ERROR"
                ok += rec.fetch_status == "OK"
            log.append(rec)
            n += 1
    finally:
        await wb.close()
    return {"targets": n, "ok": ok}


# ---------------------------------------------------------------------------
# Meta crawler docs history (M12)

DOCS_URLS = [
    "developers.facebook.com/docs/sharing/webmasters/web-crawlers",
    "developers.facebook.com/docs/sharing/webmasters/web-crawlers/",
    "developers.facebook.com/documentation/sharing/webmasters/web-crawlers",
    "developers.facebook.com/documentation/sharing/webmasters/web-crawlers/",
    "developers.facebook.com/docs/sharing/webmasters/crawler",
    "developers.facebook.com/docs/sharing/webmasters/crawler/",
    "developers.facebook.com/documentation/sharing/webmasters/crawler",
]
DOC_TOKENS = ["meta-externalagent", "meta-externalads", "meta-webindexer",
              "meta-externalfetcher", "facebookexternalhit", "facebookcatalog"]


async def run_meta_docs(cfg: dict, to: str) -> list[dict]:
    wb = Wayback(cfg["identity"]["user_agent"], cfg["wayback"]["min_interval_s"],
                 cfg["wayback"]["backoff_start_s"], cfg["wayback"]["backoff_max_s"])
    log = FetchLog("META_DOCS")
    obs: list[dict] = []
    try:
        for u in DOCS_URLS:
            rows = await wb.cdx(u, "20240101", to, "metadocs_" + re.sub(r"\W+", "_", u))
            for r in rows:
                if not r["statuscode"].startswith("2"):
                    continue
                cap = await wb.capture(r)
                from mcs.fetch.store import load_body
                body = load_body(cap.get("body_path")) or b""
                text = body.decode("utf-8", "replace").lower()
                present = {t: (t in text) for t in DOC_TOKENS}
                obs.append({"url": r["original"], "timestamp": r["timestamp"], **present})
                log.append(FetchRecord(domain="facebook.com", host="developers.facebook.com",
                                       snapshot="META_DOCS", resource="meta_docs",
                                       source="wayback", requested_url=r["original"],
                                       http_status=cap.get("status"), sha256=cap.get("sha256"),
                                       body_path=cap.get("body_path"), wayback_ts=r["timestamp"],
                                       fetch_status="OK" if cap.get("body_path") else "ERROR",
                                       fetched_at=now_iso()))
    finally:
        await wb.close()
    obs.sort(key=lambda o: o["timestamp"])
    out = []
    for t in DOC_TOKENS:
        first = next((o["timestamp"] for o in obs if o[t]), None)
        last_absent = None
        if first:
            before = [o["timestamp"] for o in obs if not o[t] and o["timestamp"] < first]
            last_absent = before[-1] if before else None
        out.append({"token": t, "first_seen_capture": first, "last_absent_capture": last_absent,
                    "captures_checked": len(obs)})
    return out
