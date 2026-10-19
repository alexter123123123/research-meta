"""Static tracker site (SPEC §3.8): site/index.html, site/data/latest.json, site/data/history.json.

The public table contains Tier A domains only; Tier B never appears at domain level.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from mcs.analyze.common import (
    find_metrics_files,
    load_bots,
    load_panel,
    load_study,
    read_parquet_safe,
    snapshot_date,
    snapshot_sort_key,
    write_json,
)
from mcs.parse.verdict import FULL_BLOCK, INDETERMINATE

TEMPLATE = Path(__file__).parent / "templates" / "index.html"
TABLE_BOTS = ["meta-externalagent", "meta-externalads", "meta-webindexer",
              "meta-externalfetcher", "facebookexternalhit", "gptbot", "claudebot",
              "google-extended", "ccbot"]
C1_BOTS = ["meta-externalagent", "meta-externalads", "meta-webindexer", "meta-externalfetcher",
           "facebookexternalhit", "gptbot", "claudebot", "google-extended", "ccbot"]
AGENT, ADS = "meta-externalagent", "meta-externalads"


def _methodology_url(config_dir) -> str:
    ua = load_study(config_dir).get("identity", {}).get("user_agent", "")
    m = re.search(r"https://github\.com/[\w.-]+/[\w.-]+", ua)
    return (m.group(0) + "/blob/main/docs/methodology.md") if m else "methodology.md"


def _e(m: dict, *path):
    cur = m
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _counter(cid: str, label: str, e: dict | None, note_fmt: str, min_n: int) -> dict:
    if not e or e.get("pct") is None or e.get("denominator", 0) < min_n:
        return {"id": cid, "label": label, "value_pct": None, "display": "n<20",
                "numerator": e.get("numerator") if e else None,
                "denominator": e.get("denominator") if e else 0,
                "note": f"n={e.get('denominator', 0) if e else 0}"}
    return {"id": cid, "label": label, "value_pct": e["pct"], "display": f"{e['pct']:.0f}%",
            "numerator": e["numerator"], "denominator": e["denominator"],
            "note": note_fmt.format(**e)}


def _counters(m: dict) -> list[dict]:
    mn = m.get("min_n", 20)
    out = [
        _counter("agent", "of news sites block meta-externalagent in robots.txt",
                 _e(m, "M1", "all_news", AGENT), "{numerator} of {denominator} sites", mn),
        _counter("ads_gap", "of those leave meta-externalads (the crawler Meta describes for "
                 "advertising and business products) unblocked",
                 _e(m, "M6", "all_news"), "{numerator} of {denominator} sites", mn),
        _counter("exposed", "of news sites with signals of Meta business-tool use do not "
                 "block meta-externalagent",
                 _e(m, "M8", "all_news", AGENT, "E1_E2_E2b", "of_linked"),
                 "{numerator} of {denominator} sites", mn),
    ]
    pair = next((p for p in (f"T1->{m['snapshot']}", f"T0->{m['snapshot']}")
                 if p in (_e(m, "M4", "by_pair") or {})), None)
    if pair:
        e = _e(m, "M4", "by_pair", pair, "all_news", "any_meta_change")
        c = _counter("changed", "of news sites changed a Meta crawler rule since "
                     + ("14 Oct" if pair.startswith("T1") else "1 Oct"), e,
                     "{numerator} of {denominator} sites with archived robots.txt", mn)
        out.append(c)
    return out


def _c1(m: dict) -> dict:
    news = _e(m, "M1", "all_news") or {}
    ctrl = _e(m, "M1", "control_ex_news") or _e(m, "M1", "control") or {}

    def val(e):
        return None if not e or e.get("suppressed") else e.get("pct")

    def fr(e):
        return f"{e['numerator']}/{e['denominator']}" if e else "n/a"

    return {
        "bots": C1_BOTS,
        "news": [val(news.get(b)) for b in C1_BOTS],
        "control": [val(ctrl.get(b)) for b in C1_BOTS],
        "news_frac": [fr(news.get(b)) for b in C1_BOTS],
        "control_frac": [fr(ctrl.get(b)) for b in C1_BOTS],
        "news_n": (news.get(AGENT) or {}).get("denominator", 0),
        "control_n": (ctrl.get(AGENT) or {}).get("denominator", 0),
    }


def _c2(m: dict) -> dict:
    tl = m.get("M11", {})
    g = tl.get("groups", {}).get("news", {})
    total = g.get("daily_changes", [])
    cf = g.get("daily_cf_managed", [0] * len(total))
    return {
        "dates": tl.get("dates", []), "start": tl.get("start"), "end": tl.get("end"),
        "other": [t - c for t, c in zip(total, cf, strict=True)], "cf": cf,
        "events": tl.get("events", []), "n_events": g.get("n_change_events", 0),
        "n_domains_changed": g.get("n_domains_changed", 0), "n_domains": g.get("n_domains", 0),
        "median_bracket_hours": g.get("median_bracket_hours"),
    }


def _table(snapshot: str, verdicts: pd.DataFrame, panel: pd.DataFrame, meta_bots: list[str]
           ) -> list[dict]:
    tier_a = panel[(panel["panel"] == "news") & (panel["tier"] == "A")]
    if verdicts.empty:
        return []
    v = verdicts[verdicts["domain"].isin(set(tier_a["domain"]))]
    now = v[v["snapshot"] == snapshot].drop_duplicates(["domain", "bot"], keep="last")
    wide = now.pivot(index="domain", columns="bot", values="verdict")
    t1 = v[(v["snapshot"] == "T1") & v["bot"].isin(meta_bots)].drop_duplicates(
        ["domain", "bot"], keep="last")
    changed: dict[str, bool | None] = {}
    if len(t1) and snapshot != "T1":
        cur = now[now["bot"].isin(meta_bots)]
        mg = t1.merge(cur, on=["domain", "bot"], suffixes=("_a", "_b"))
        mg = mg[(mg["verdict_a"] != INDETERMINATE) & (mg["verdict_b"] != INDETERMINATE)]
        if "named_a" in mg.columns:
            diff = (mg["verdict_a"] != mg["verdict_b"]) | (
                mg["named_a"].fillna(False).astype(bool) != mg["named_b"].fillna(False)
                .astype(bool))
        else:
            diff = mg["verdict_a"] != mg["verdict_b"]
        changed = mg.assign(diff=diff).groupby("domain")["diff"].any().to_dict()
    rows = []
    for r in tier_a.sort_values("domain").itertuples(index=False):
        brands = r.brands_list if isinstance(r.brands_list, list) else []
        verd = {b: (wide.at[r.domain, b] if r.domain in wide.index and b in wide.columns
                    and pd.notna(wide.at[r.domain, b]) else None) for b in TABLE_BOTS}
        ch = changed.get(r.domain)
        rows.append({"domain": r.domain, "brand": ", ".join(brands), "country": r.country,
                     "verdicts": verd, "changed_since_T1": None if ch is None else bool(ch)})
    return rows


def _history(verdicts: pd.DataFrame, panel: pd.DataFrame, reports_dir: Path) -> list[dict]:
    """Headline counters for every snapshot in verdicts (news panel), oldest first."""
    news = set(panel.loc[panel["panel"] == "news", "domain"])
    metric_snaps = {f.stem.removeprefix("metrics_") for f in find_metrics_files(reports_dir)}
    out = []
    if verdicts.empty:
        return out
    v = verdicts[verdicts["domain"].isin(news) & verdicts["bot"].isin([AGENT, ADS])]
    for snap in sorted(v["snapshot"].dropna().unique(), key=snapshot_sort_key):
        sv = v[v["snapshot"] == snap].drop_duplicates(["domain", "bot"], keep="last")
        w = sv.pivot(index="domain", columns="bot", values="verdict")
        for b in (AGENT, ADS):
            if b not in w.columns:
                w[b] = None
        det = w[AGENT].notna() & (w[AGENT] != INDETERMINATE)
        n = int(det.sum())
        ka = int((det & (w[AGENT] == FULL_BLOCK)).sum())
        kd = int((det & (w[ADS] == FULL_BLOCK)).sum())
        gap_den = ka
        gap_num = int((det & (w[AGENT] == FULL_BLOCK) & (w[ADS] != FULL_BLOCK)).sum())
        src = sv["source"].dropna().iloc[0] if "source" in sv.columns and sv[
            "source"].notna().any() else None
        out.append({
            "snapshot": snap, "date": snapshot_date(snap, verdicts).isoformat(), "source": src,
            "has_metrics_report": snap in metric_snaps,
            "n_determinate": n, "n_indeterminate": int(len(w) - n),
            "agent_full_block": ka, "agent_pct": 100 * ka / n if n else None,
            "ads_full_block": kd, "ads_pct": 100 * kd / n if n else None,
            "ads_gap": gap_num, "ads_gap_den": gap_den,
            "ads_gap_pct": 100 * gap_num / gap_den if gap_den else None,
        })
    return out


def build_site(out_dir: str | Path = "site", reports_dir: str | Path = "reports",
               processed_dir: str | Path = "data/processed",
               panel_csv: str | Path = "data/panel/panel.csv",
               config_dir: str | Path | None = None,
               methodology_url: str | None = None) -> dict:
    """Build the tracker from the latest reports/metrics_*.json + verdicts.parquet."""
    out = Path(out_dir)
    rdir = Path(reports_dir)
    files = find_metrics_files(rdir)
    if not files:
        raise FileNotFoundError(f"no metrics_*.json in {rdir}; run compute_metrics first")
    m = json.loads(files[-1].read_text(encoding="utf-8"))
    study = load_study(config_dir)
    bots = load_bots(config_dir)
    meta_bots = bots["META_TOKENS"] + bots.get("LEGACY_META", [])
    panel = load_panel(panel_csv)
    verdicts = read_parquet_safe(Path(processed_dir) / "verdicts.parquet")
    footer = study.get("branding", {}).get("footer", "Data: HasData")
    murl = methodology_url or _methodology_url(config_dir)
    latest = {
        "snapshot": m["snapshot"], "snapshot_date": m["snapshot_date"],
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "metrics_generated_at": m.get("generated_at"),
        "methodology_url": murl, "footer": footer, "min_n": m.get("min_n", 20),
        "counters": _counters(m), "c1": _c1(m), "c2": _c2(m),
        "table_bots": TABLE_BOTS,
        "table": _table(m["snapshot"], verdicts, panel, meta_bots),
        "hypotheses": {k: {"text": h["text"], "outcome": h["outcome"]}
                       for k, h in m.get("hypotheses", {}).items()},
    }
    history = {"generated_at": latest["generated_at"],
               "snapshots": _history(verdicts, panel, rdir)}
    (out / "data").mkdir(parents=True, exist_ok=True)
    write_json(latest, out / "data" / "latest.json")
    write_json(history, out / "data" / "history.json")
    html = TEMPLATE.read_text(encoding="utf-8")
    accent = study.get("branding", {}).get("accent", "#E4572E")
    for k, v in {"{{ACCENT}}": accent, "{{FOOTER}}": footer, "{{METHODOLOGY_URL}}": murl}.items():
        html = html.replace(k, v)
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return {"index": out / "index.html", "latest": out / "data" / "latest.json",
            "history": out / "data" / "history.json"}
