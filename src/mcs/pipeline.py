"""Fetch logs -> processed tables (spec §9): fetches, groups, probes, verdicts, history."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from mcs.fetch.store import FetchLog, load_body
from mcs.parse.probes import BASE_PROBES, SYNTHETIC, build_probes
from mcs.parse.robots import parse
from mcs.parse.templates import body_hash
from mcs.parse.verdict import verdicts_for_body

PROC = Path("data/processed")
FETCH_DIR = Path("data/raw/fetches")
PROBES_FILE = PROC / "probes.json"


def load_bots(path="config/bots.yaml") -> tuple[list[str], dict]:
    b = yaml.safe_load(open(path))
    order = []
    for k in ("META_TOKENS", "LEGACY_META", "PEER_AI_TRAINING", "PEER_AI_SEARCH", "CLASSIC_SEARCH"):
        for t in b[k]:
            if t not in order:
                order.append(t)
    return order, b


def all_fetch_rows() -> pd.DataFrame:
    rows = []
    for p in sorted(FETCH_DIR.glob("*.jsonl")):
        rows.extend(FetchLog(p.stem).read())
    df = pd.DataFrame(rows)
    if not df.empty:
        df["redirect_chain"] = df["redirect_chain"].map(json.dumps)
    return df


def write_fetches() -> pd.DataFrame:
    df = all_fetch_rows()
    PROC.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PROC / "fetches.parquet", index=False)
    return df


# ---------------------------------------------------------------------------
# probes (built once, from T2 homepages; reused for every snapshot)

def build_probe_sets(df: pd.DataFrame, snapshot: str = "T2") -> dict:
    probes = json.loads(PROBES_FILE.read_text()) if PROBES_FILE.exists() else {}
    hp = df[(df.resource.isin(["homepage", "homepage_wayback", "homepage_rendered"]))
            & (df.snapshot.isin([snapshot, "WB_HOME", "RENDER"]))]
    by_dom = defaultdict(list)
    for r in hp.itertuples():
        if isinstance(r.body_path, str) and r.fetch_status == "OK":
            by_dom[r.domain].append(r)
    for dom, recs in by_dom.items():
        if dom in probes and not probes[dom]["synthetic"]:
            continue
        for r in recs:
            body = load_body(r.body_path)
            if not body:
                continue
            ps, synth = build_probes(body.decode("utf-8", "replace"),
                                     r.final_url or f"https://{r.host}/")
            if not synth or dom not in probes:
                probes[dom] = {"probes": ps, "synthetic": synth, "source": r.resource,
                               "built_at": datetime.now(UTC).isoformat(timespec="seconds")}
            if not synth:
                break
    PROBES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROBES_FILE.write_text(json.dumps(probes, indent=1, sort_keys=True))
    return probes


def probes_for(probes: dict, domain: str) -> tuple[list[str], bool]:
    p = probes.get(domain)
    if p:
        return p["probes"], p["synthetic"]
    return BASE_PROBES + [SYNTHETIC], True


# ---------------------------------------------------------------------------

def _robots_rows(df: pd.DataFrame) -> pd.DataFrame:
    return df[df.resource == "robots"].copy()


def write_groups(df: pd.DataFrame) -> None:
    out = []
    seen = set()
    for r in _robots_rows(df).itertuples():
        if not isinstance(r.body_path, str) or r.sha256 in seen:
            continue
        seen.add(r.sha256)
        body = load_body(r.body_path)
        if body is None:
            continue
        p = parse(body)
        from mcs.parse.tokens import norm_token
        for g in p.groups:
            for a in g.agents:
                out.append({
                    "fetch_id": r.fetch_id, "sha256": r.sha256, "group_idx": g.idx,
                    "ua_raw": a.raw, "ua_token_norm": norm_token(a.raw),
                    "rules": json.dumps([{"type": x.type, "path": x.path, "line_no": x.line_no}
                                         for x in g.rules], ensure_ascii=False),
                    "in_cf_managed_block": a.in_cf, "line_start": g.line_start,
                    "line_end": g.line_end,
                })
    pd.DataFrame(out).to_parquet(PROC / "groups.parquet", index=False)


def _wb_meta(r) -> dict:
    try:
        return json.loads(r.error) if isinstance(r.error, str) else {}
    except ValueError:
        return {}


def select_wayback_snapshot(wb: pd.DataFrame, cutoff: str, window_start: str) -> pd.DataFrame:
    """Per domain, the robots.txt version in force at `cutoff`, evidenced by a capture inside
    [window_start, cutoff]."""
    c = datetime.fromisoformat(cutoff.replace("Z", "+00:00")).strftime("%Y%m%d%H%M%S")
    w = datetime.fromisoformat(window_start.replace("Z", "+00:00")).strftime("%Y%m%d%H%M%S")
    picks = []
    for _dom, g in wb.groupby("domain"):
        g = g[g.wayback_ts.notna()].sort_values("wayback_ts")
        g = g[g.wayback_ts <= c]
        if g.empty:
            continue
        r = g.iloc[-1]
        meta = _wb_meta(r)
        last_ts = meta.get("last_ts") or r.wayback_ts
        evidence = min(last_ts, c)
        if evidence < w:
            continue
        age = (datetime.strptime(c, "%Y%m%d%H%M%S")
               - datetime.strptime(evidence, "%Y%m%d%H%M%S")).total_seconds() / 86400
        r = r.copy()
        r["age_days"] = round(age, 2)
        r["evidence_ts"] = evidence
        picks.append(r)
    return pd.DataFrame(picks)


def _verdict_rows(r, snapshot: str, bots: list[str], probes: dict, source: str,
                  snapshot_date: str, extra: dict | None = None) -> list[dict]:
    body = load_body(r.body_path) if isinstance(r.body_path, str) else None
    ps, synth = probes_for(probes, r.domain)
    parsed = parse(body) if body else None
    vs = verdicts_for_body(body, r.fetch_status, bots, ps, parsed)
    cluster = body_hash(body) if body and r.fetch_status == "OK" else None
    gen = parsed.generator_hint if parsed else None
    rows = []
    for v in vs:
        rows.append({
            "domain": r.domain, "snapshot": snapshot, "bot": v.bot, "verdict": v.verdict,
            "named": v.named, "named_raw": json.dumps(v.named_raw, ensure_ascii=False),
            "match_mode": v.match_mode,
            "nonstandard_raw": json.dumps(v.nonstandard_raw, ensure_ascii=False),
            "probes_total": v.probes_total, "probes_disallowed": v.probes_disallowed,
            "protego_agree": v.protego_agree,
            "protego_mismatch": json.dumps(v.protego_mismatch),
            "in_cf_managed_block": v.in_cf_managed_block, "fetch_id": r.fetch_id,
            "fetch_status": r.fetch_status, "template_cluster": cluster, "generator_hint": gen,
            "snapshot_date": snapshot_date, "wayback_ts": getattr(r, "wayback_ts", None),
            "prev_capture_ts": None, "source": source, "synthetic_probe": synth,
            "truncated": bool(getattr(r, "truncated", False)),
            **(extra or {}),
        })
    return rows


def write_verdicts(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    bots, _ = load_bots()
    probes = json.loads(PROBES_FILE.read_text()) if PROBES_FILE.exists() else {}
    rows: list[dict] = []
    robots = _robots_rows(df)
    live = robots[robots.source != "wayback"]
    for snap, g in live.groupby("snapshot"):
        if snap.startswith("SMOKE"):
            continue
        g = g.sort_values("fetched_at").drop_duplicates("domain", keep="last")
        date = g.fetched_at.min()[:10]
        for r in g.itertuples():
            rows.extend(_verdict_rows(r, snap, bots, probes, "live", date))
    wb = robots[robots.source == "wayback"]
    if not wb.empty:
        snaps = cfg["snapshots"]
        t0 = select_wayback_snapshot(wb, snaps["T0"]["cutoff"], snaps["T0"]["window_start"])
        t1 = select_wayback_snapshot(wb, snaps["T1"]["cutoff"], snaps["T1"]["window_start"])
        t1_domains = set(t1.domain) if not t1.empty else set()
        for label, sel, date in (("T0", t0, snaps["T0"]["cutoff"][:10]),
                                 ("T1", t1, snaps["T1"]["cutoff"][:10])):
            for r in sel.itertuples():
                rows.extend(_verdict_rows(r, label, bots, probes, "wayback", date,
                                          {"age_days": r.age_days, "t1_carried": False}))
        # T1 carry-forward from T0 (flagged)
        if not t0.empty:
            for r in t0[~t0.domain.isin(t1_domains)].itertuples():
                rows.extend(_verdict_rows(r, "T1", bots, probes, "wayback",
                                          snaps["T1"]["cutoff"][:10],
                                          {"age_days": r.age_days, "t1_carried": True}))
    out = pd.DataFrame(rows)
    out.to_parquet(PROC / "verdicts.parquet", index=False)
    return out


def write_history(df: pd.DataFrame) -> pd.DataFrame:
    """Every observed robots.txt version (Wayback versions + live daily snapshots) with the
    verdict tuple over META_TOKENS + LEGACY_META."""
    _, b = load_bots()
    meta_bots = b["META_TOKENS"] + b["LEGACY_META"]
    probes = json.loads(PROBES_FILE.read_text()) if PROBES_FILE.exists() else {}
    robots = _robots_rows(df)
    robots = robots[~robots.snapshot.str.startswith("SMOKE")]
    out = []
    for dom, g in robots.groupby("domain"):
        evs = []
        for r in g.itertuples():
            if r.source == "wayback":
                if not isinstance(r.wayback_ts, str):
                    continue
                meta = _wb_meta(r)
                ts = datetime.strptime(r.wayback_ts, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
                prev = meta.get("prev_capture_ts")
                prev = (datetime.strptime(prev, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
                        if prev else None)
            else:
                ts = datetime.fromisoformat(r.fetched_at.replace("Z", "+00:00"))
                prev = None
            evs.append((ts, prev, r))
        evs.sort(key=lambda e: e[0])
        prev_obs_ts = None
        for ts, prev, r in evs:
            body = load_body(r.body_path) if isinstance(r.body_path, str) else None
            ps, _ = probes_for(probes, dom)
            vs = verdicts_for_body(body, r.fetch_status, meta_bots, ps)
            out.append({
                "domain": dom, "version_ts": ts.isoformat(),
                "prev_capture_ts": (prev or prev_obs_ts).isoformat() if (prev or prev_obs_ts)
                else None,
                "meta_tuple": json.dumps({v.bot: v.verdict for v in vs}),
                "cf_tuple": json.dumps({v.bot: v.in_cf_managed_block for v in vs}),
                "in_cf_managed_change": None,
                "source": "wayback" if r.source == "wayback" else "live",
                "snapshot": r.snapshot, "fetch_status": r.fetch_status,
                "template_cluster": body_hash(body) if body else None,
            })
            prev_obs_ts = ts
    h = pd.DataFrame(out)
    if not h.empty:
        # A change is CF-managed if every Meta bot whose verdict changed is CF-managed on both sides.
        h = h.sort_values(["domain", "version_ts"]).reset_index(drop=True)
        flags = []
        prev_row = None
        for row in h.itertuples():
            flag = None
            if prev_row is not None and prev_row.domain == row.domain \
                    and prev_row.meta_tuple != row.meta_tuple:
                a, b2 = json.loads(prev_row.meta_tuple), json.loads(row.meta_tuple)
                ca, cb = json.loads(prev_row.cf_tuple), json.loads(row.cf_tuple)
                changed = [k for k in a if a[k] != b2.get(k)]
                flag = all((ca.get(k) or cb.get(k)) for k in changed)
            flags.append(flag)
            prev_row = row
        h["in_cf_managed_change"] = flags
    h.to_parquet(PROC / "history.parquet", index=False)
    return h


def parse_all(cfg: dict) -> dict:
    df = write_fetches()
    if df.empty:
        return {"fetches": 0}
    build_probe_sets(df)
    write_groups(df)
    v = write_verdicts(df, cfg)
    h = write_history(df)
    dis = v[v.protego_agree == False]
    dis.to_csv(PROC / "parser_disagreements.csv", index=False)
    return {"fetches": len(df), "verdict_rows": len(v), "history_rows": len(h),
            "protego_disagreements": len(dis)}
