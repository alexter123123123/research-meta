"""Assemble Meta business-tool signals (spec §8) from the T2 / RENDER / WB_HOME / GTM fetch logs."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from mcs.fetch.direct import get, make_client
from mcs.fetch.ratelimit import HostLimiter
from mcs.fetch.store import FetchLog, FetchRecord, load_body, save_body
from mcs.signals.adstxt import parse_ads_txt
from mcs.signals.gtm import gtm_has_meta_pixel, gtm_url
from mcs.signals.homepage import (
    combine_signals,
    extract_homepage_signals,
    parse_dns_txt,
    write_signals,
)


def _latest(rows: list[dict], resource: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows:
        if r["resource"] == resource:
            out[r["domain"]] = r
    return out


def _html_signals(rec: dict | None) -> dict | None:
    if not rec or rec.get("fetch_status") != "OK" or rec.get("challenge_detected"):
        return None
    body = load_body(rec.get("body_path"))
    if not body:
        return None
    return extract_homepage_signals(body.decode("utf-8", "replace"),
                                    rec.get("final_url") or f"https://{rec['host']}/")


async def build_signals(cfg: dict, panel_csv: str = "data/panel/panel.csv") -> dict:
    panel = pd.read_csv(panel_csv)
    news = list(panel[panel.panel == "news"].domain.drop_duplicates())
    t2 = FetchLog("T2").read()
    raw = _latest(t2, "homepage")
    dns = _latest(t2, "dns")
    ads = _latest(t2, "ads")
    rendered = _latest(FetchLog("RENDER").read(), "homepage_rendered")
    wbhome = _latest(FetchLog("WB_HOME").read(), "homepage_wayback")

    per_dom = {}
    need_gtm: set[str] = set()
    for d in news:
        raw_s = _html_signals(raw.get(d))
        ren_s = _html_signals(rendered.get(d))
        source, fid = None, None
        if raw_s or ren_s:
            source = "live"
            fid = (rendered.get(d) or raw.get(d) or {}).get("fetch_id")
        else:
            wb_s = _html_signals(wbhome.get(d))
            if wb_s:
                raw_s, source, fid = wb_s, "wayback", wbhome[d]["fetch_id"]
        per_dom[d] = (raw_s, ren_s, source, fid)
        pages = [s for s in (raw_s, ren_s) if s]
        if pages and not any(s["e2_pixel"] for s in pages):
            for s in pages:
                need_gtm.update(s["gtm_ids"])

    # Public GTM container JS, once per container id (cached in the GTM log).
    glog = FetchLog("GTM")
    gtm_flags: dict[str, bool] = {}
    for r in glog.read():
        b = load_body(r.get("body_path"))
        gtm_flags[r["host"]] = gtm_has_meta_pixel(b.decode("utf-8", "replace")) if b else False
    todo = sorted(need_gtm - set(gtm_flags))
    if todo:
        rl = cfg["rate_limits"]
        lim = HostLimiter(rl["per_host_min_interval_s"], 1)
        async with make_client(cfg["identity"]["user_agent"]) as client:
            for gid in todo:
                resp = await get(client, lim, gtm_url(gid), max_bytes=5_000_000)
                rec = FetchRecord(domain="googletagmanager.com", host=gid, snapshot="GTM",
                                  resource="gtm", source="live_direct",
                                  requested_url=gtm_url(gid), http_status=resp.status,
                                  fetch_status="OK" if resp.status == 200 else "ERROR",
                                  bytes=len(resp.body), error=resp.error)
                if resp.status == 200 and resp.body:
                    rec.sha256, rec.body_path = save_body(resp.body)
                glog.append(rec)
                gtm_flags[gid] = resp.status == 200 and gtm_has_meta_pixel(
                    resp.body.decode("utf-8", "replace"))

    rows = []
    for d in news:
        raw_s, ren_s, source, fid = per_dom[d]
        drec = dns.get(d)
        dsig = None
        if drec and drec.get("fetch_status") == "OK":
            dsig = parse_dns_txt(json.loads((load_body(drec["body_path"]) or b"[]").decode()))
        arec = ads.get(d)
        asig = None
        if arec and arec.get("fetch_status") == "OK":
            asig = parse_ads_txt((load_body(arec["body_path"]) or b"").decode("utf-8", "replace"))
        if raw_s is None and ren_s is None and dsig is None and asig is None:
            continue  # nothing observable for this domain: leave it out of M7/M8 denominators
        ids = set()
        for s in (raw_s, ren_s):
            if s:
                ids.update(s["gtm_ids"])
        rows.append(combine_signals(d, raw_s, ren_s, dsig, asig,
                                    {g: gtm_flags.get(g, False) for g in ids}, source, fid))
    df = write_signals(rows)
    Path("data/processed").mkdir(parents=True, exist_ok=True)
    return {"news_domains": len(news), "gtm_fetched": len(todo),
            "levels": df.meta_linked_level.value_counts().to_dict()}
