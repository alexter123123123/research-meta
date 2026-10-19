"""Headline metrics M1-M12, hypotheses H1-H6 and benchmarks (SPEC §2, §10).

All shares are expressed in percent (0-100). Every entry carries numerator, denominator,
Wilson 95% CI, the number of indeterminate domains and a `suppressed` flag (denominator <
analysis.min_n). Denominators contain determinate verdicts only.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from mcs.analyze.benchmarks import run_benchmarks
from mcs.analyze.changes import (
    CHANGES_COLUMNS,
    STANDARD_PAIRS,
    cluster_summary,
    compute_changes,
    domain_change_table,
    pairs_for_snapshot,
    summarize_pair,
)
from mcs.analyze.common import (
    CONTROL_SEGMENTS,
    is_news_segment,
    load_bots,
    load_events,
    load_panel,
    load_study,
    read_parquet_safe,
    segment_domains,
    snapshot_date,
    snapshot_sort_key,
    write_json,
)
from mcs.analyze.stats import mcnemar_exact, newcombe_diff_ci, prop_entry, weighted_share
from mcs.analyze.timeline import build_change_events, daily_timeline
from mcs.parse.verdict import FULL_BLOCK, INDETERMINATE, WILDCARD_BLOCK

log = logging.getLogger(__name__)

AGENT = "meta-externalagent"
ADS = "meta-externalads"
FBHIT = "facebookexternalhit"
H4_PEERS = ["gptbot", "claudebot", "google-extended"]
SUMMARY_BOTS = ["meta-externalagent", "meta-externalads", "meta-webindexer",
                "meta-externalfetcher", "facebookexternalhit", "gptbot", "claudebot",
                "google-extended", "ccbot"]
LEVEL_SETS = {
    "E1": {"E1"},
    "E1_E2_E2b": {"E1", "E2"},
    "E1_E2_E2b_GTM": {"E1", "E2", "E2-GTM"},
    "any": {"E1", "E2", "E2-GTM", "E3"},
}
SIGNAL_FLAGS = ["e1_meta_tag", "e1_dns_txt", "e2_pixel", "e2_gtm", "e2b_adstxt", "e3_fb_link",
                "e3_ig_link"]

HYPOTHESES = {
    "H1": "Most news publishers (>50%) still do NOT block meta-externalagent days before "
          "30 Oct.",
    "H2": "Few publishers (<5%) changed their Meta rules after 15 Oct.",
    "H3": "meta-externalads is blocked far less often than meta-externalagent (the ads gap).",
    "H4": "Publishers block OpenAI/Anthropic/Google training bots more often than Meta's "
          "(the Meta gap).",
    "H5": "A large share (>50%) of Meta-linked publishers are exposed.",
    "H6": "Changes cluster by owner group or platform template (chain-level decisions).",
}
H6_MIN_CHANGED = 10


class _Snap:
    """Wide boolean views of one snapshot's verdicts."""

    def __init__(self, v: pd.DataFrame, domains: list[str], bots: list[str]):
        v = v.drop_duplicates(subset=["domain", "bot"], keep="last")
        idx = pd.Index(sorted(set(domains)), name="domain")
        self.W = v.pivot(index="domain", columns="bot", values="verdict").reindex(
            index=idx, columns=bots)
        named = v.pivot(index="domain", columns="bot", values="named").reindex(
            index=idx, columns=bots)
        self.NAMED = named.fillna(False).astype(bool)
        self.DET = self.W.notna() & (self.W != INDETERMINATE)
        self.FB = (self.W == FULL_BLOCK) & self.DET
        self.EFF = self.W.isin([FULL_BLOCK, WILDCARD_BLOCK]) & self.DET
        if "match_mode" in v.columns:
            mm = v.pivot(index="domain", columns="bot", values="match_mode").reindex(
                index=idx, columns=bots)
            self.NONSTD = (mm == "nonstandard") & ~self.NAMED & self.DET
        else:
            self.NONSTD = pd.DataFrame(False, index=idx, columns=bots)


def _entry(num_mask: pd.Series, den_mask: pd.Series, seg_size: int, n_det: int,
           min_n: int) -> dict:
    return prop_entry(int((num_mask & den_mask).sum()), int(den_mask.sum()),
                      n_indeterminate=int(seg_size - n_det), min_n=min_n)


def _domains_present(seg: set[str], index: pd.Index) -> list[str]:
    return [d for d in seg if d in index]


def compute_metrics(snapshot: str, processed_dir: str | Path = "data/processed",
                    panel_csv: str | Path = "data/panel/panel.csv",
                    reports_dir: str | Path = "reports",
                    config_dir: str | Path | None = None,
                    write: bool = True) -> dict:
    """Compute all metrics for `snapshot`, write reports/metrics_<snapshot>.json,
    data/processed/changes.parquet and data/processed/domain_summary[_public].csv."""
    pdir = Path(processed_dir)
    bots_cfg = load_bots(config_dir)
    study = load_study(config_dir)
    min_n = int(study.get("analysis", {}).get("min_n", 20))
    meta = bots_cfg["META_TOKENS"]
    legacy = bots_cfg.get("LEGACY_META", [])
    peers5 = bots_cfg.get("M5_PEERS", ["gptbot", "claudebot", "google-extended", "ccbot"])
    sets = {k: bots_cfg.get(k, []) for k in ("META_TOKENS", "LEGACY_META", "PEER_AI_TRAINING",
                                              "PEER_AI_SEARCH", "CLASSIC_SEARCH")}
    all_b: list[str] = []
    for lst in sets.values():
        all_b += [b for b in lst if b not in all_b]

    panel = load_panel(panel_csv)
    segs = segment_domains(panel)
    verdicts = read_parquet_safe(pdir / "verdicts.parquet")
    if verdicts.empty:
        raise FileNotFoundError(f"no verdicts in {pdir / 'verdicts.parquet'}")
    verdicts = verdicts.copy()
    verdicts["bot"] = verdicts["bot"].str.lower()
    verdicts["domain"] = verdicts["domain"].str.lower()
    if "named" not in verdicts.columns:
        verdicts["named"] = False
    verdicts["named"] = verdicts["named"].fillna(False).astype(bool)
    available = sorted(verdicts["snapshot"].dropna().unique().tolist(), key=snapshot_sort_key)
    if snapshot not in available:
        raise ValueError(f"snapshot {snapshot!r} not in verdicts (have {available})")
    snap_date = snapshot_date(snapshot, verdicts)
    v_now = verdicts[verdicts["snapshot"] == snapshot]
    S = _Snap(v_now, panel["domain"].tolist(), all_b)

    signals = read_parquet_safe(pdir / "signals.parquet")
    if not signals.empty:
        signals = signals.drop_duplicates("domain", keep="last").set_index("domain")
    ranks = panel.drop_duplicates("domain").set_index("domain")["tranco_rank"]

    out: dict = {
        "snapshot": snapshot,
        "snapshot_date": snap_date.isoformat(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "min_n": min_n,
        "pct_scale": "percent",
        "bot_sets": {**sets, "M5_PEERS": peers5},
        "available_snapshots": available,
        "panel": {
            "n_news": int((panel["panel"] == "news").sum()),
            "n_tier_A": int(((panel["panel"] == "news") & (panel["tier"] == "A")).sum()),
            "n_tier_B": int(((panel["panel"] == "news") & (panel["tier"] == "B")).sum()),
            "n_control": int((panel["panel"] == "control").sum()),
            "n_control_is_news": int(((panel["panel"] == "control") & panel["is_news"]).sum()),
        },
        "segments": {},
    }
    for k in ("M1", "M1_sets", "M1_weighted", "M2", "M3", "M5", "M6", "M7", "M8", "M9",
              "nonstandard_meta"):
        out[k] = {}
    out["paired_same_snapshot"] = {}

    for seg, doms in segs.items():
        dl = sorted(doms)
        size = len(dl)
        det_agent = S.DET.loc[dl, AGENT] if dl else pd.Series(dtype=bool)
        n_det = int(det_agent.sum())
        out["segments"][seg] = {
            "n_domains": size,
            "n_with_verdicts": int(S.W.loc[dl, AGENT].notna().sum()) if dl else 0,
            "n_determinate": n_det,
            "n_indeterminate": size - n_det,
            "is_news": is_news_segment(seg),
        }
        if not dl:
            continue
        W_det = S.DET.loc[dl]
        FBs, EFFs, NMs = S.FB.loc[dl], S.EFF.loc[dl], S.NAMED.loc[dl]
        m1, m2, m3, mw = {}, {}, {}, {}
        for b in all_b:
            d = W_det[b]
            nd = int(d.sum())
            m1[b] = _entry(FBs[b], d, size, nd, min_n)
            m2[b] = _entry(NMs[b], d, size, nd, min_n)
            m3[b] = _entry(EFFs[b], d, size, nd, min_n)
            if b in meta or b in peers5:
                dd = d[d].index
                mw[b] = {"share_pct": 100 * weighted_share(FBs.loc[dd, b],
                                                           ranks.reindex(dd).tolist())
                         if len(dd) else None,
                         "n": len(dd), "suppressed": bool(len(dd) < min_n),
                         "weight": "1/log10(tranco_rank+10); missing rank = 1e6"}
        m2["any_meta"] = _entry(NMs[meta].any(axis=1), W_det[AGENT], size, n_det, min_n)
        out["M1"][seg], out["M2"][seg], out["M3"][seg] = m1, m2, m3
        out["M1_weighted"][seg] = mw
        out["M1_sets"][seg] = {}
        for sname, sb in sets.items():
            if not sb:
                continue
            d = W_det[sb].all(axis=1)
            out["M1_sets"][seg][sname] = _entry(FBs[sb].any(axis=1), d, size, int(d.sum()),
                                                min_n)
        # M5 Meta gap
        peer_block = FBs[peers5].any(axis=1)
        out["M5"][seg] = _entry(~FBs[AGENT], W_det[AGENT] & peer_block, size, n_det, min_n)
        # M6 ads gap
        out["M6"][seg] = _entry(~FBs[ADS], W_det[AGENT] & W_det[ADS] & FBs[AGENT], size,
                                n_det, min_n)
        # M9 preview collateral + legacy-only
        legacy_only = NMs[legacy].any(axis=1) & ~NMs[meta].any(axis=1) if legacy else \
            pd.Series(False, index=dl)
        out["M9"][seg] = {
            "fbhit_full_block": _entry(FBs[FBHIT], W_det[FBHIT], size, n_det, min_n),
            "legacy_only": _entry(legacy_only, W_det[AGENT], size, n_det, min_n),
        }
        out["nonstandard_meta"][seg] = _entry(S.NONSTD.loc[dl, meta].any(axis=1),
                                              W_det[AGENT], size, n_det, min_n)
        # paired same-snapshot comparisons used by H3/H4
        both = W_det[AGENT] & W_det[ADS]
        b3 = int((both & FBs[AGENT] & ~FBs[ADS]).sum())
        c3 = int((both & ~FBs[AGENT] & FBs[ADS]).sum())
        hp = [p for p in H4_PEERS if p in FBs.columns]
        dp = W_det[AGENT] & W_det[hp].all(axis=1)
        peer_any = FBs[hp].any(axis=1)
        b4 = int((dp & peer_any & ~FBs[AGENT]).sum())
        c4 = int((dp & ~peer_any & FBs[AGENT]).sum())
        out["paired_same_snapshot"][seg] = {
            "agent_vs_ads": {"n": int(both.sum()), "b_agent_only": b3, "c_ads_only": c3,
                             "p_value": mcnemar_exact(b3, c3)},
            "peers_vs_agent": {"n": int(dp.sum()), "peers": hp,
                               "peer_any_full_block": _entry(peer_any, dp, size, n_det, min_n),
                               "agent_full_block": _entry(FBs[AGENT], dp, size, n_det, min_n),
                               "b_peer_only": b4, "c_agent_only": c4,
                               "p_value": mcnemar_exact(b4, c4)},
        }
        # M7 / M8 (news segments only, signals required)
        if is_news_segment(seg) and not signals.empty:
            sd = [d for d in dl if d in signals.index]
            lvl = signals.loc[sd, "meta_linked_level"].fillna("none") if sd else pd.Series(
                dtype=object)
            n_sig = len(sd)
            all_true = pd.Series(True, index=sd)
            m7 = {"n_with_signals": n_sig}
            for key, lv in LEVEL_SETS.items():
                m7[key] = _entry(lvl.isin(lv), all_true, size, n_sig, min_n)
            m7["flags"] = {}
            for f in SIGNAL_FLAGS:
                if f in signals.columns:
                    m7["flags"][f] = _entry(signals.loc[sd, f].fillna(False).astype(bool),
                                            all_true, size, n_sig, min_n)
            for f in ("fb_pages_meta", "fb_app_id"):
                if f in signals.columns:
                    m7["flags"][f] = _entry(signals.loc[sd, f].notna()
                                            & (signals.loc[sd, f].astype(str) != ""),
                                            all_true, size, n_sig, min_n)
            out["M7"][seg] = m7
            m8 = {}
            for b in (AGENT, ADS):
                base = W_det.loc[sd, b] if sd else pd.Series(dtype=bool)
                notblock = ~FBs.loc[sd, b] if sd else pd.Series(dtype=bool)
                m8[b] = {}
                for key, lv in LEVEL_SETS.items():
                    linked = lvl.isin(lv)
                    m8[b][key] = {
                        "of_linked": _entry(notblock, base & linked, size, int(base.sum()),
                                            min_n),
                        "of_panel": _entry(notblock & linked, base, size, int(base.sum()),
                                           min_n),
                    }
            out["M8"][seg] = m8

    # M10 news vs control (control excludes is_news)
    out["M10"] = {"news_segment": "all_news", "control_segment": "control_ex_news"}
    for mk in ("M1", "M3"):
        out["M10"][mk] = {}
        for b in meta + [p for p in peers5 if p not in meta]:
            e1 = out[mk].get("all_news", {}).get(b)
            e2 = out[mk].get("control_ex_news", {}).get(b)
            if not e1 or not e2:
                continue
            d, lo, hi = newcombe_diff_ci(e1["numerator"], e1["denominator"],
                                         e2["numerator"], e2["denominator"])
            out["M10"][mk][b] = {
                "news": e1, "control": e2,
                "diff_pp": 100 * d if not np.isnan(d) else None,
                "diff_ci_low": 100 * lo if not np.isnan(lo) else None,
                "diff_ci_high": 100 * hi if not np.isnan(hi) else None,
                "method": "Newcombe hybrid score (method 10)",
                "suppressed": bool(e1["suppressed"] or e2["suppressed"]),
            }
    out["M10"]["control_top1000"] = {
        "M1": out["M1"].get("control_top1000", {}).get(AGENT),
        "M2": out["M2"].get("control_top1000", {}).get(AGENT),
    }

    # M4 changes
    pairs = pairs_for_snapshot(snapshot, available)
    all_pairs = [(a, b) for a, b in STANDARD_PAIRS if a in available and b in available]
    all_pairs += [p for p in pairs if p not in all_pairs]
    history = read_parquet_safe(pdir / "history.parquet")
    events = build_change_events(history, verdicts, meta + legacy)
    changes = compute_changes(verdicts, all_pairs, meta + legacy, events)
    if write:
        pdir.mkdir(parents=True, exist_ok=True)
        (changes if len(changes) else pd.DataFrame(columns=CHANGES_COLUMNS)).to_parquet(
            pdir / "changes.parquet", index=False)
    out["M4"] = {"pairs": [f"{a}->{b}" for a, b in pairs], "by_pair": {}, "clusters": {}}
    for a, b in pairs:
        key = f"{a}->{b}"
        out["M4"]["by_pair"][key] = {
            seg: summarize_pair(changes, a, b, doms, meta + legacy, min_n=min_n)
            for seg, doms in segs.items()}
        out["M4"]["clusters"][key] = cluster_summary(
            changes, verdicts[verdicts["snapshot"] == b], panel, a, b, segs["all_news"])
    out["coverage"] = _coverage(verdicts, segs, available)

    # M11 timeline
    hist_from = str(study.get("snapshots", {}).get("history_from", "2026-09-01"))
    out["M11"] = daily_timeline(events, {"news": segs["all_news"], "control": segs["control"]},
                                start=hist_from, end=snap_date.isoformat())
    out["M11"]["events"] = [{"date": e["date"].isoformat(), "label": e["label"],
                             "note": "per press reports"} for e in load_events(config_dir)]
    out["M11"]["sources"] = sorted(set(events["source"])) if len(events) else []

    # M12 docs history
    out["M12"] = _meta_docs(pdir)

    # fetch outcomes for transparency
    out["fetch_status_counts"] = {}
    if "fetch_status" in v_now.columns:
        vs = v_now[v_now["bot"] == AGENT]
        for seg in ("all_news", "tier_A", "tier_B", "control"):
            sub = vs[vs["domain"].isin(segs[seg])]
            out["fetch_status_counts"][seg] = {str(k): int(n) for k, n in
                                               sub["fetch_status"].value_counts().items()}

    out["hypotheses"] = evaluate_hypotheses(out, min_n)
    out["benchmarks"] = run_benchmarks(out, min_n)

    if write:
        write_json(out, Path(reports_dir) / f"metrics_{snapshot}.json")
        write_domain_summary(snapshot, panel, S, signals, changes, pdir,
                             tier_b_public=bool(study.get("release", {}).get("tier_b_rows",
                                                                                False)))
    return out


def _coverage(verdicts: pd.DataFrame, segs: dict[str, set[str]], available: list[str]) -> dict:
    cov: dict = {}
    for snap in available:
        v = verdicts[(verdicts["snapshot"] == snap) & (verdicts["bot"] == AGENT)]
        cov[snap] = {}
        age = None
        if "wayback_ts" in v.columns and v["wayback_ts"].notna().any():
            ts = pd.to_datetime(v["wayback_ts"].astype(str), format="%Y%m%d%H%M%S",
                                errors="coerce", utc=True)
            if ts.isna().all():
                ts = pd.to_datetime(v["wayback_ts"], errors="coerce", utc=True)
            age = ts
        for seg in ("all_news", "tier_A", "tier_B", "control"):
            m = v["domain"].isin(segs[seg])
            sub = v[m]
            entry = {"n_segment": len(segs[seg]), "n_present": len(sub),
                     "n_determinate": int((sub["verdict"] != INDETERMINATE).sum()),
                     "pct_present": 100 * len(sub) / len(segs[seg]) if segs[seg] else None}
            if age is not None and snap in ("T0", "T1"):
                cutoff = pd.Timestamp(snapshot_sort_key(snap), tz="UTC") + pd.Timedelta(
                    hours=23, minutes=59, seconds=59)
                a = (cutoff - age[m]).dt.total_seconds() / 86400
                entry["median_age_days"] = float(a.median()) if a.notna().any() else None
            cov[snap][seg] = entry
    return cov


def _meta_docs(pdir: Path) -> dict:
    md = read_parquet_safe(pdir / "meta_docs.parquet")
    if md.empty or "token" not in md.columns:
        return {"available": False, "rows": []}
    rows = []
    for r in md.itertuples(index=False):
        def s(v):
            return None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
        rows.append({"token": str(r.token),
                     "first_seen_capture": s(getattr(r, "first_seen_capture", None)),
                     "last_absent_capture": s(getattr(r, "last_absent_capture", None))})
    return {"available": True, "rows": rows}


def _h(hid: str, outcome: str, rule: str, **kw) -> dict:
    return {"id": hid, "text": HYPOTHESES[hid], "rule": rule, "outcome": outcome, **kw}


def evaluate_hypotheses(m: dict, min_n: int = 20) -> dict:
    """Apply the pre-registered decision rules (docs/methodology.md) to a metrics dict."""
    res: dict = {}
    snap = m["snapshot"]
    # H1
    e = m["M1"].get("all_news", {}).get(AGENT)
    rule = "share of determinate news domains NOT FULL_BLOCKing meta-externalagent > 50%"
    if not e or e["denominator"] < min_n:
        res["H1"] = _h("H1", "insufficient data", rule)
    else:
        nb = 100 - e["pct"]
        res["H1"] = _h("H1", "supported" if nb > 50 else "not supported", rule,
                       value_pct=nb, numerator=e["denominator"] - e["numerator"],
                       denominator=e["denominator"], ci_low=100 - e["ci_high"],
                       ci_high=100 - e["ci_low"])
    # H2
    rule = ("share of paired news domains (both endpoints determinate) whose verdict or naming "
            "for any META_TOKENS/LEGACY_META bot changed between T1 and the current snapshot "
            "< 5% (T0 used if T1 is unavailable)")
    pair = next((p for p in (f"T1->{snap}", f"T0->{snap}") if p in m["M4"]["by_pair"]), None)
    if pair is None:
        res["H2"] = _h("H2", "insufficient data", rule, note="no baseline pair available")
    else:
        e = m["M4"]["by_pair"][pair]["all_news"]["any_meta_change"]
        if e["denominator"] < min_n:
            res["H2"] = _h("H2", "insufficient data", rule, pair=pair,
                           denominator=e["denominator"])
        else:
            res["H2"] = _h("H2", "supported" if e["pct"] < 5 else "not supported", rule,
                           pair=pair, value_pct=e["pct"], numerator=e["numerator"],
                           denominator=e["denominator"], ci_low=e["ci_low"],
                           ci_high=e["ci_high"])
    # H3
    rule = ("meta-externalads FULL_BLOCK share < meta-externalagent FULL_BLOCK share among news "
            "domains, with non-overlapping Wilson CIs or an exact McNemar test p < 0.05 on the "
            "same domains")
    ea = m["M1"].get("all_news", {}).get(AGENT)
    ed = m["M1"].get("all_news", {}).get(ADS)
    pr = m["paired_same_snapshot"].get("all_news", {}).get("agent_vs_ads", {})
    if not ea or not ed or ea["denominator"] < min_n:
        res["H3"] = _h("H3", "insufficient data", rule)
    else:
        lower = ed["pct"] < ea["pct"]
        sep = ed["ci_high"] < ea["ci_low"]
        sig = pr.get("p_value", 1) < 0.05 and pr.get("b_agent_only", 0) > pr.get("c_ads_only", 0)
        res["H3"] = _h("H3", "supported" if lower and (sep or sig) else "not supported", rule,
                       agent_pct=ea["pct"], ads_pct=ed["pct"], denominator=ea["denominator"],
                       agent_numerator=ea["numerator"], ads_numerator=ed["numerator"],
                       mcnemar_b=pr.get("b_agent_only"), mcnemar_c=pr.get("c_ads_only"),
                       mcnemar_p=pr.get("p_value"), ci_non_overlapping=bool(sep))
    # H4
    rule = ("share of news domains FULL_BLOCKing at least one of gptbot, claudebot, "
            "google-extended > share FULL_BLOCKing meta-externalagent, exact McNemar p < 0.05")
    pp = m["paired_same_snapshot"].get("all_news", {}).get("peers_vs_agent")
    if not pp or pp["n"] < min_n:
        res["H4"] = _h("H4", "insufficient data", rule)
    else:
        pe, ae = pp["peer_any_full_block"], pp["agent_full_block"]
        ok = pe["pct"] > ae["pct"] and pp["p_value"] < 0.05
        res["H4"] = _h("H4", "supported" if ok else "not supported", rule,
                       peer_pct=pe["pct"], agent_pct=ae["pct"], denominator=pp["n"],
                       peer_numerator=pe["numerator"], agent_numerator=ae["numerator"],
                       mcnemar_b=pp["b_peer_only"], mcnemar_c=pp["c_agent_only"],
                       mcnemar_p=pp["p_value"])
    # H5
    rule = ("share of META_LINKED news domains (E1 or E2 or E2b) that do NOT FULL_BLOCK "
            "meta-externalagent > 50%")
    e = m["M8"].get("all_news", {}).get(AGENT, {}).get("E1_E2_E2b", {}).get("of_linked")
    if not e or e["denominator"] < min_n:
        res["H5"] = _h("H5", "insufficient data", rule)
    else:
        res["H5"] = _h("H5", "supported" if e["pct"] > 50 else "not supported", rule,
                       value_pct=e["pct"], numerator=e["numerator"],
                       denominator=e["denominator"], ci_low=e["ci_low"], ci_high=e["ci_high"])
    # H6
    rule = (f"among news domains that changed any Meta rule (same pair as H2), share that share "
            f"a template cluster or a known owner group with at least one other changed domain "
            f"> 50%; requires >= {H6_MIN_CHANGED} changed domains")
    cl = m["M4"]["clusters"].get(pair) if pair else None
    if not cl or cl["n_changed_domains"] < H6_MIN_CHANGED:
        res["H6"] = _h("H6", "insufficient data", rule, pair=pair,
                       denominator=cl["n_changed_domains"] if cl else 0)
    else:
        k, n = cl["n_changed_in_shared_cluster_or_owner"], cl["n_changed_domains"]
        e = prop_entry(k, n, min_n=min_n)
        res["H6"] = _h("H6", "supported" if e["pct"] > 50 else "not supported", rule,
                       pair=pair, value_pct=e["pct"], numerator=k, denominator=n,
                       ci_low=e["ci_low"], ci_high=e["ci_high"])
    return res


def write_domain_summary(snapshot: str, panel: pd.DataFrame, S: _Snap, signals: pd.DataFrame,
                         changes: pd.DataFrame, processed_dir: Path,
                         tier_b_public: bool = False) -> pd.DataFrame:
    """domain_summary.csv (all rows, local) and domain_summary_public.csv (Tier A only unless
    release.tier_b_rows). Rows of other snapshots already in the file are kept."""
    p = panel.drop_duplicates("domain", keep="first").copy()
    df = p[["domain", "panel", "tier", "country", "brands", "owner_group", "tranco_rank"]].copy()
    df.insert(1, "snapshot", snapshot)
    for b in SUMMARY_BOTS:
        df[b] = df["domain"].map(S.W[b]) if b in S.W.columns else None
    if not signals.empty:
        df["meta_linked_level"] = df["domain"].map(signals["meta_linked_level"])
    else:
        df["meta_linked_level"] = None
    df["changed_since_T1"] = None
    df["attribution"] = None
    if snapshot not in ("T0", "T1") and len(changes):
        dt = domain_change_table(changes, "T1", snapshot)
        if len(dt):
            dt = dt.set_index("domain")
            df["changed_since_T1"] = df["domain"].map(dt["changed_any"])
            df["attribution"] = df["domain"].map(dt["attribution"])
    pdir = Path(processed_dir)
    pdir.mkdir(parents=True, exist_ok=True)
    full_path = pdir / "domain_summary.csv"
    if full_path.exists():
        try:
            old = pd.read_csv(full_path, dtype=str)
            old = old[old["snapshot"] != snapshot]
            df = pd.concat([old, df.astype(object)], ignore_index=True)
        except (ValueError, KeyError, pd.errors.EmptyDataError):
            pass
    df.to_csv(full_path, index=False)
    keep_tiers = {"A", "B"} if tier_b_public else {"A"}
    pub = df[(df["panel"] == "news") & df["tier"].isin(keep_tiers)]
    pub.to_csv(pdir / "domain_summary_public.csv", index=False)
    return df


__all__ = ["CONTROL_SEGMENTS", "compute_metrics", "evaluate_hypotheses", "write_domain_summary"]
