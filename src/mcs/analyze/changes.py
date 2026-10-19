"""M4 changes between snapshots (SPEC §2 M4, §7.6, §7.7, §9 `changes`).

Paired design: a (domain, bot) pair enters a comparison only if both endpoint verdicts are
determinate. Attribution of a changed rule:
  cf_managed  the named Meta rule sits inside a Cloudflare-managed block in every version in
              which it is named (i.e. the change happened only inside the CF block);
  authored    a named rule outside a CF block is involved in the change;
  unknown     neither version names the bot (a change of the `*` group), so we cannot tell.
A domain-level attribution is `authored` if any changed row is authored, `cf_managed` if all
changed rows are cf_managed, else `unknown`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from mcs.analyze.common import (
    STANDARD_PAIRS,
    STANDARD_SNAPSHOTS,
    UNKNOWN_OWNER,
    load_bots,
    read_parquet_safe,
    snapshot_sort_key,
)
from mcs.analyze.stats import mcnemar_exact, prop_entry
from mcs.analyze.timeline import build_change_events
from mcs.parse.verdict import FULL_BLOCK, INDETERMINATE, direction

CHANGES_COLUMNS = [
    "domain", "bot", "from_snapshot", "to_snapshot", "from_verdict", "to_verdict", "direction",
    "attribution", "template_cluster", "change_date", "prev_capture_ts", "bracket_hours",
    "changed", "from_named", "to_named", "newly_named", "from_in_cf", "to_in_cf",
]


def pairs_for_snapshot(snapshot: str, available: list[str]) -> list[tuple[str, str]]:
    """Comparisons relevant to a metrics run at `snapshot` (only those whose endpoints exist)."""
    avail = set(available)
    cut = snapshot_sort_key(snapshot)
    pairs = [(a, b) for a, b in STANDARD_PAIRS
             if a in avail and b in avail and snapshot_sort_key(b) <= cut]
    if snapshot in avail:
        # "since the Nieman Lab report" comparison for any later snapshot (used by H2)
        if "T1" in avail and snapshot_sort_key("T1") < cut and ("T1", snapshot) not in pairs:
            pairs.append(("T1", snapshot))
        # daily monitor snapshots are also compared with the launch snapshot
        if (snapshot not in STANDARD_SNAPSHOTS and "T2" in avail
                and snapshot_sort_key("T2") < cut):
            pairs.append(("T2", snapshot))
    return pairs


def _attribution(from_named: bool, to_named: bool, from_cf: bool, to_cf: bool) -> str:
    if not from_named and not to_named:
        return "unknown"
    involved = []
    if from_named:
        involved.append(from_cf)
    if to_named:
        involved.append(to_cf)
    return "cf_managed" if all(involved) else "authored"


def _endpoint_ts(row_ts, snap_date, end_of_day: bool) -> pd.Timestamp | None:
    for v in (row_ts,):
        if v is not None and not (isinstance(v, float) and pd.isna(v)) and str(v) != "":
            s = str(v)
            try:
                if s.isdigit() and len(s) == 14:
                    return pd.Timestamp(pd.to_datetime(s, format="%Y%m%d%H%M%S"), tz="UTC")
                t = pd.Timestamp(v)
                return t.tz_localize("UTC") if t.tzinfo is None else t
            except (ValueError, TypeError):
                pass
    if snap_date is None or (isinstance(snap_date, float) and pd.isna(snap_date)):
        return None
    t = pd.Timestamp(pd.Timestamp(snap_date).date(), tz="UTC")
    return t + pd.Timedelta(days=1) if end_of_day else t


def compute_changes(verdicts: pd.DataFrame, pairs: list[tuple[str, str]], bots: list[str],
                    events: pd.DataFrame | None = None) -> pd.DataFrame:
    """Build the `changes` table for the given snapshot pairs and bots."""
    if verdicts.empty or not pairs:
        return pd.DataFrame(columns=CHANGES_COLUMNS)
    v = verdicts[verdicts["bot"].isin(bots)].copy()
    for col, default in (("named", False), ("in_cf_managed_block", False),
                         ("template_cluster", None), ("wayback_ts", None),
                         ("snapshot_date", None)):
        if col not in v.columns:
            v[col] = default
    v["named"] = v["named"].fillna(False).astype(bool)
    v["in_cf_managed_block"] = v["in_cf_managed_block"].fillna(False).astype(bool)
    keep = ["domain", "bot", "verdict", "named", "in_cf_managed_block", "template_cluster",
            "wayback_ts", "snapshot_date"]
    frames = []
    ev_by_dom = {}
    if events is not None and len(events):
        ev = events.copy()
        ev["change_ts"] = pd.to_datetime(ev["change_ts"], utc=True)
        ev_by_dom = {d: g.sort_values("change_ts") for d, g in ev.groupby("domain")}
    for a, b in pairs:
        fa = v.loc[v["snapshot"] == a, keep]
        fb = v.loc[v["snapshot"] == b, keep]
        if fa.empty or fb.empty:
            continue
        m = fa.merge(fb, on=["domain", "bot"], suffixes=("_f", "_t"))
        m = m[(m["verdict_f"] != INDETERMINATE) & (m["verdict_t"] != INDETERMINATE)
              & m["verdict_f"].notna() & m["verdict_t"].notna()]
        if m.empty:
            continue
        out = pd.DataFrame({
            "domain": m["domain"], "bot": m["bot"], "from_snapshot": a, "to_snapshot": b,
            "from_verdict": m["verdict_f"], "to_verdict": m["verdict_t"],
            "from_named": m["named_f"], "to_named": m["named_t"],
            "from_in_cf": m["in_cf_managed_block_f"], "to_in_cf": m["in_cf_managed_block_t"],
            "template_cluster": m["template_cluster_t"],
        })
        out["direction"] = [direction(x, y) for x, y in zip(out["from_verdict"],
                                                             out["to_verdict"], strict=True)]
        out["newly_named"] = (~out["from_named"]) & out["to_named"]
        out["changed"] = (out["direction"] != "same") | (out["from_named"] != out["to_named"])
        out["attribution"] = [
            _attribution(fn, tn, fc, tc) if ch else None
            for fn, tn, fc, tc, ch in zip(out["from_named"], out["to_named"], out["from_in_cf"],
                                          out["to_in_cf"], out["changed"], strict=True)]
        # change date from the timeline: first event inside (from_ts, to_ts]
        cdates, prevs, brackets = [], [], []
        for row, fts_raw, fsd, tts_raw, tsd in zip(
                out.itertuples(index=False), m["wayback_ts_f"], m["snapshot_date_f"],
                m["wayback_ts_t"], m["snapshot_date_t"], strict=True):
            cd = pv = br = None
            if row.changed and row.domain in ev_by_dom:
                lo = _endpoint_ts(fts_raw, fsd, end_of_day=False)
                hi = _endpoint_ts(tts_raw, tsd, end_of_day=True)
                g = ev_by_dom[row.domain]
                sel = g
                if lo is not None:
                    sel = sel[sel["change_ts"] > lo]
                if hi is not None:
                    sel = sel[sel["change_ts"] <= hi]
                if len(sel):
                    e = sel.iloc[0]
                    cd, pv, br = e["change_ts"], e["prev_capture_ts"], e["bracket_hours"]
            cdates.append(cd)
            prevs.append(pv)
            brackets.append(br)
        out["change_date"] = pd.to_datetime(pd.Series(cdates, dtype="object"), utc=True)
        out["prev_capture_ts"] = pd.to_datetime(pd.Series(prevs, dtype="object"), utc=True)
        out["bracket_hours"] = pd.to_numeric(pd.Series(brackets, dtype="object"),
                                             errors="coerce")
        frames.append(out.reset_index(drop=True))
    if not frames:
        return pd.DataFrame(columns=CHANGES_COLUMNS)
    return pd.concat(frames, ignore_index=True)[CHANGES_COLUMNS]


def build_changes(processed_dir: str | Path = "data/processed",
                  pairs: list[tuple[str, str]] | None = None,
                  config_dir: str | Path | None = None, write: bool = True) -> pd.DataFrame:
    """Read verdicts/history from processed_dir, compute changes, write changes.parquet."""
    pdir = Path(processed_dir)
    bots_cfg = load_bots(config_dir)
    bots = bots_cfg["META_TOKENS"] + bots_cfg.get("LEGACY_META", [])
    verdicts = read_parquet_safe(pdir / "verdicts.parquet")
    if verdicts.empty:
        df = pd.DataFrame(columns=CHANGES_COLUMNS)
    else:
        if pairs is None:
            avail = sorted(verdicts["snapshot"].unique(), key=snapshot_sort_key)
            pairs = [(a, b) for a, b in STANDARD_PAIRS if a in avail and b in avail]
        events = build_change_events(read_parquet_safe(pdir / "history.parquet"), verdicts, bots)
        df = compute_changes(verdicts, pairs, bots, events)
    if write:
        pdir.mkdir(parents=True, exist_ok=True)
        df.to_parquet(pdir / "changes.parquet", index=False)
    return df


def domain_change_table(changes: pd.DataFrame, from_s: str, to_s: str) -> pd.DataFrame:
    """One row per paired domain: changed_any, more_restrictive_any, newly_named, attribution."""
    c = changes[(changes["from_snapshot"] == from_s) & (changes["to_snapshot"] == to_s)]
    if c.empty:
        return pd.DataFrame(columns=["domain", "changed_any", "more_restrictive_any",
                                     "newly_named_any", "attribution", "template_cluster"])

    def attr(s: pd.Series) -> str | None:
        vals = set(s.dropna())
        if not vals:
            return None
        if "authored" in vals:
            return "authored"
        if vals == {"cf_managed"}:
            return "cf_managed"
        return "unknown"

    g = c.groupby("domain")
    out = pd.DataFrame({
        "changed_any": g["changed"].any(),
        "more_restrictive_any": g["direction"].agg(lambda s: (s == "more_restrictive").any()),
        "newly_named_any": g["newly_named"].any(),
        "attribution": g["attribution"].agg(attr),
        "template_cluster": g["template_cluster"].agg(
            lambda s: s.dropna().iloc[0] if s.notna().any() else None),
    }).reset_index()
    return out


def summarize_pair(changes: pd.DataFrame, from_s: str, to_s: str, domains: set[str],
                   meta_tokens: list[str], min_n: int = 20,
                   mcnemar_bots: tuple[str, ...] = ("meta-externalagent", "meta-externalads"),
                   ) -> dict:
    """M4 summary for one pair and one segment."""
    c = changes[(changes["from_snapshot"] == from_s) & (changes["to_snapshot"] == to_s)
                & changes["domain"].isin(domains)]
    dt = domain_change_table(c, from_s, to_s)
    n = int(len(dt))
    meta_c = c[c["bot"].isin(meta_tokens)]
    newly = int(meta_c.groupby("domain")["newly_named"].any().sum()) if len(meta_c) else 0
    out = {
        "from": from_s, "to": to_s, "n_paired": n,
        "any_meta_change": prop_entry(int(dt["changed_any"].sum()) if n else 0, n,
                                      min_n=min_n),
        "any_meta_more_restrictive": prop_entry(
            int(dt["more_restrictive_any"].sum()) if n else 0, n, min_n=min_n),
        "newly_named_any_meta": prop_entry(newly, n, min_n=min_n),
        "attribution": {k: int((dt.loc[dt["changed_any"], "attribution"] == k).sum())
                        if n else 0 for k in ("authored", "cf_managed", "unknown")},
        "by_bot": {},
    }
    for bot in meta_tokens:
        cb = c[c["bot"] == bot]
        nb = int(len(cb))
        fb_from = cb["from_verdict"] == FULL_BLOCK
        fb_to = cb["to_verdict"] == FULL_BLOCK
        b = int((fb_from & ~fb_to).sum())
        cc = int((~fb_from & fb_to).sum())
        entry = {
            "n_paired": nb,
            "more_restrictive": prop_entry(int((cb["direction"] == "more_restrictive").sum()),
                                           nb, min_n=min_n),
            "less_restrictive": prop_entry(int((cb["direction"] == "less_restrictive").sum()),
                                           nb, min_n=min_n),
            "newly_named": prop_entry(int(cb["newly_named"].sum()), nb, min_n=min_n),
            "full_block_from": prop_entry(int(fb_from.sum()), nb, min_n=min_n),
            "full_block_to": prop_entry(int(fb_to.sum()), nb, min_n=min_n),
        }
        if bot in mcnemar_bots:
            entry["mcnemar"] = {"b_blocked_then_not": b, "c_newly_blocked": cc,
                                "p_value": mcnemar_exact(b, cc)}
        out["by_bot"][bot] = entry
    return out


def cluster_summary(changes: pd.DataFrame, verdicts_to: pd.DataFrame, panel: pd.DataFrame,
                    from_s: str, to_s: str, domains: set[str]) -> dict:
    """Per-cluster changes and cluster x owner_group join (H6)."""
    c = changes[(changes["from_snapshot"] == from_s) & (changes["to_snapshot"] == to_s)
                & changes["domain"].isin(domains)]
    dt = domain_change_table(c, from_s, to_s)
    changed = dt[dt["changed_any"]] if len(dt) else dt
    owners = panel.drop_duplicates("domain").set_index("domain")["owner_group"]
    sizes = {}
    if not verdicts_to.empty and "template_cluster" in verdicts_to.columns:
        vt = verdicts_to[verdicts_to["domain"].isin(domains)].drop_duplicates("domain")
        sizes = vt.groupby("template_cluster")["domain"].nunique().to_dict()
    clusters = []
    joins = []
    if len(changed):
        ch = changed.copy()
        ch["owner_group"] = ch["domain"].map(owners).fillna(UNKNOWN_OWNER)
        for cl, g in ch.dropna(subset=["template_cluster"]).groupby("template_cluster"):
            clusters.append({
                "template_cluster": str(cl), "n_changed": int(len(g)),
                "cluster_size": int(sizes.get(cl, len(g))),
                "owner_groups": sorted(set(g["owner_group"])),
                "attribution": json.dumps(g["attribution"].value_counts().to_dict()),
            })
        for (cl, og), g in ch.dropna(subset=["template_cluster"]).groupby(
                ["template_cluster", "owner_group"]):
            joins.append({"template_cluster": str(cl), "owner_group": og,
                          "n_changed": int(len(g))})
        # H6 clustering share
        cl_counts = ch["template_cluster"].value_counts()
        og_counts = ch.loc[ch["owner_group"] != UNKNOWN_OWNER, "owner_group"].value_counts()
        multi = [
            (pd.notna(r.template_cluster) and cl_counts.get(r.template_cluster, 0) >= 2)
            or (r.owner_group != UNKNOWN_OWNER and og_counts.get(r.owner_group, 0) >= 2)
            for r in ch.itertuples(index=False)]
        n_clustered = int(sum(multi))
    else:
        n_clustered = 0
    clusters.sort(key=lambda d: -d["n_changed"])
    joins.sort(key=lambda d: -d["n_changed"])
    return {
        "from": from_s, "to": to_s,
        "n_changed_domains": int(len(changed)),
        "n_changed_in_shared_cluster_or_owner": n_clustered,
        "clusters": clusters[:50],
        "cluster_owner_join": joins[:100],
    }
