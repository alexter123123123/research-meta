"""Write a small, internally consistent fake dataset for end-to-end analysis tests.

Usage:  make_synthetic(root) -> dict of paths
Creates root/data/panel/panel.csv and root/data/processed/{verdicts,history,signals,
meta_docs}.parquet with ~60 news domains (Tier A + B) and 100 control domains, snapshots
T0, T1 (wayback), T2 (live) and optionally one daily monitor snapshot D20261021.
No network, deterministic (seeded).
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[3]
BOTS = yaml.safe_load((REPO / "config" / "bots.yaml").read_text())
META = BOTS["META_TOKENS"]
LEGACY = BOTS["LEGACY_META"]
ALL_BOTS = list(dict.fromkeys(META + LEGACY + BOTS["PEER_AI_TRAINING"] + BOTS["PEER_AI_SEARCH"]
                              + BOTS["CLASSIC_SEARCH"]))
SNAP_DATES = {"T0": date(2026, 9, 28), "T1": date(2026, 10, 12), "T2": date(2026, 10, 20),
              "D20261021": date(2026, 10, 21)}


def _panel(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for i in range(60):
        tier = "A" if i < 25 else "B"
        if tier == "A":
            country = "US" if i < 13 else "GB" if i < 22 else "DE"
            owner = ["NYT Co", "News Corp", "Guardian Media", "independent/unknown"][i % 4]
            src, srank = ("pg_us_top50_2026-09" if country == "US" else "pg_uk_top50_2026-09"), i
        else:
            country = "US" if i % 3 else "GB"
            owner = ("Gannett" if i < 38 else "Lee Enterprises" if i < 49
                     else "independent/unknown")
            src, srank = "wikidata", None
        rows.append({
            "domain": f"news{i:02d}.example", "panel": "news", "tier": tier,
            "country": country, "brands": json.dumps([f"News {i}"]), "owner_group": owner,
            "source_list": src, "source_rank": srank,
            "tranco_rank": int(rng.integers(100, 50000)) if i % 5 else None,
            "control_top1000": False, "is_news": True,
            "added_at": "2026-10-20T08:00:00Z", "source_url": "https://example.org/list",
        })
    for j in range(100):
        dom = f"news{j:02d}.example" if j < 3 else f"ctrl{j:03d}.example"
        rank = (j + 1) * 50
        rows.append({
            "domain": dom, "panel": "control", "tier": "control", "country": "XX",
            "brands": "[]", "owner_group": "independent/unknown", "source_list": "tranco_TEST",
            "source_rank": rank, "tranco_rank": rank, "control_top1000": rank <= 1000,
            "is_news": j < 3, "added_at": "2026-10-20T08:00:00Z",
            "source_url": "https://tranco-list.eu/list/TEST",
        })
    return pd.DataFrame(rows)


def _base_state(rng, is_news: bool) -> dict:
    s = {}
    p_agent = 0.35 if is_news else 0.15
    s["meta-externalagent"] = rng.random() < p_agent
    s["meta-externalads"] = s["meta-externalagent"] and rng.random() < 0.3
    s["meta-webindexer"] = rng.random() < 0.08
    s["meta-externalfetcher"] = rng.random() < 0.05
    s["facebookexternalhit"] = rng.random() < 0.05
    for b in ("gptbot", "claudebot", "google-extended", "ccbot", "anthropic-ai", "bytespider"):
        s[b] = rng.random() < (0.55 if is_news else 0.25)
    s["_wildcard"] = rng.random() < 0.03
    s["_legacy_only"] = rng.random() < 0.04
    s["_cf"] = rng.random() < 0.2
    return s


def _verdict_rows(dom, snap, state, rng, indeterminate, cluster, source):
    rows = []
    for b in ALL_BOTS:
        blocked = bool(state.get(b))
        named = blocked or (b == "googlebot" and rng.random() < 0.2) or (
            b in ("facebot",) and state.get("_legacy_only"))
        if indeterminate:
            v, named = "INDETERMINATE", False
        elif blocked:
            v = "FULL_BLOCK"
        elif named:
            v = "ALLOWED_EXPLICIT"
        elif state.get("_wildcard"):
            v = "WILDCARD_BLOCK"
        else:
            v = "ALLOWED_DEFAULT"
        in_cf = bool(named and state.get("_cf") and b in META + BOTS["PEER_AI_TRAINING"])
        sd = SNAP_DATES[snap]
        rows.append({
            "domain": dom, "snapshot": snap, "bot": b, "verdict": v, "named": bool(named),
            "named_raw": json.dumps([f"User-agent: {b}"] if named else []),
            "match_mode": "exact" if named else None,
            "probes_total": 0 if indeterminate else 4,
            "probes_disallowed": 4 if v in ("FULL_BLOCK", "WILDCARD_BLOCK") else 0,
            "protego_agree": None if indeterminate else True,
            "in_cf_managed_block": in_cf, "fetch_id": f"{dom}-{snap}",
            "fetch_status": "NETWORK_ERROR" if indeterminate else "OK",
            "template_cluster": cluster, "generator_hint": "cloudflare" if state.get("_cf")
            else None,
            "snapshot_date": sd,
            "wayback_ts": (datetime.combine(sd, datetime.min.time()) + timedelta(hours=12)
                           ).strftime("%Y%m%d%H%M%S") if source == "wayback" else None,
            "prev_capture_ts": None, "source": source,
        })
    return rows


def make_synthetic(root: str | Path, seed: int = 20261030, with_daily: bool = True) -> dict:
    root = Path(root)
    rng = np.random.default_rng(seed)
    panel_dir = root / "data" / "panel"
    proc = root / "data" / "processed"
    panel_dir.mkdir(parents=True, exist_ok=True)
    proc.mkdir(parents=True, exist_ok=True)
    panel = _panel(rng)
    panel.to_csv(panel_dir / "panel.csv", index=False)

    vrows, hrows, srows = [], [], []
    domains = panel.drop_duplicates("domain")
    snaps = ["T0", "T1", "T2"] + (["D20261021"] if with_daily else [])
    for r in domains.itertuples(index=False):
        is_news = r.panel == "news"
        st0 = _base_state(rng, is_news)
        st1 = dict(st0)
        st2 = dict(st0)
        # ~12% of news domains newly block Meta after 15 Oct; Gannett changes as a chain
        changed = is_news and (rng.random() < 0.12 or r.owner_group == "Gannett")
        if changed:
            st2["meta-externalagent"] = True
            st2["meta-externalads"] = rng.random() < 0.6
            if r.owner_group == "Gannett":  # chain-wide change inside a Cloudflare block
                st2["_cf"] = True
        std = dict(st2)
        if is_news and rng.random() < 0.05:
            std["meta-externalads"] = True
        states = {"T0": st0, "T1": st1, "T2": st2, "D20261021": std}
        cluster0 = "tpl-gannett-v1" if r.owner_group == "Gannett" else f"h-{r.domain}"
        cluster2 = "tpl-gannett-v2" if r.owner_group == "Gannett" else (
            f"h2-{r.domain}" if changed else cluster0)
        has_wb = is_news or rng.random() < 0.5  # control wayback subsample
        for snap in snaps:
            if snap in ("T0", "T1") and not has_wb:
                continue
            if snap == "T1" and rng.random() < 0.1:
                continue  # no T1 capture
            indet = snap in ("T2", "D20261021") and rng.random() < 0.03
            src = "wayback" if snap in ("T0", "T1") else "live"
            vrows += _verdict_rows(r.domain, snap, states[snap], rng, indet,
                                   cluster0 if snap in ("T0", "T1") else cluster2, src)
        # history (Wayback versions): first version in Sept, maybe a change on 16-18 Oct
        tup0 = {b: ("FULL_BLOCK" if st0.get(b) else "ALLOWED_DEFAULT") for b in META + LEGACY}
        if has_wb:
            hrows.append({"domain": r.domain, "version_ts": "2026-09-05T10:00:00Z",
                          "prev_capture_ts": None, "meta_tuple": json.dumps(tup0),
                          "in_cf_managed_change": False, "source": "wayback"})
            if changed:
                tup2 = {b: ("FULL_BLOCK" if st2.get(b) else "ALLOWED_DEFAULT")
                        for b in META + LEGACY}
                day = 16 + int(rng.integers(0, 3))
                hrows.append({"domain": r.domain,
                              "version_ts": f"2026-10-{day:02d}T09:00:00Z",
                              "prev_capture_ts": f"2026-10-{day - 1:02d}T21:00:00Z",
                              "meta_tuple": json.dumps(tup2),
                              "in_cf_managed_change": bool(st0.get("_cf")),
                              "source": "wayback"})
        if is_news:
            lvl_draw = rng.random()
            e1 = lvl_draw < 0.25
            e2 = rng.random() < 0.6
            e2b = rng.random() < 0.15
            e2g = (not e2) and rng.random() < 0.3
            e3 = rng.random() < 0.85
            level = ("E1" if e1 else "E2" if (e2 or e2b) else "E2-GTM" if e2g
                     else "E3" if e3 else "none")
            srows.append({
                "domain": r.domain, "e1_meta_tag": e1, "e1_dns_txt": e1 and rng.random() < 0.5,
                "e2_pixel": e2, "pixel_ids": json.dumps(["123456789"] if e2 else []),
                "e2_gtm": e2g, "e2b_adstxt": e2b, "e3_fb_link": e3,
                "e3_ig_link": e3 and rng.random() < 0.7, "e3_fb_group": False,
                "fb_pages_meta": "111" if rng.random() < 0.3 else None,
                "fb_app_id": "222" if rng.random() < 0.3 else None, "gtm_ids": "[]",
                "meta_linked_level": level, "homepage_source": "live",
                "homepage_fetch_id": f"{r.domain}-hp", "homepage_available": True,
            })
    verdicts = pd.DataFrame(vrows)
    verdicts.to_parquet(proc / "verdicts.parquet", index=False)
    pd.DataFrame(hrows).to_parquet(proc / "history.parquet", index=False)
    pd.DataFrame(srows).to_parquet(proc / "signals.parquet", index=False)
    pd.DataFrame([
        {"token": "meta-externalagent", "first_seen_capture": "20240815120000",
         "last_absent_capture": "20240801090000"},
        {"token": "meta-externalads", "first_seen_capture": "20260930101010",
         "last_absent_capture": "20260920080000"},
        {"token": "meta-webindexer", "first_seen_capture": None,
         "last_absent_capture": "20261018000000"},
    ]).to_parquet(proc / "meta_docs.parquet", index=False)
    return {"root": root, "panel_csv": panel_dir / "panel.csv", "processed_dir": proc,
            "reports_dir": root / "reports", "site_dir": root / "site"}


if __name__ == "__main__":
    print(make_synthetic(sys.argv[1] if len(sys.argv) > 1 else "synthetic_out"))
