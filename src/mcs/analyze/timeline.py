"""M11 timeline: Meta-related robots.txt changes per day (SPEC §2 M11, §6.5).

A "Meta-related change" is a robots.txt version whose verdict tuple over META_TOKENS +
LEGACY_META differs from the previous version for at least one bot (comparing only
determinate verdicts; an INDETERMINATE observation never creates or hides a change).
Sources: Wayback version history (history.parquet) plus our own live snapshots
(verdicts.parquet rows with source == "live").
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd

from mcs.parse.verdict import INDETERMINATE, RESTRICTIVENESS

LIVE_HOUR_UTC = 6  # live snapshots start 06:00 UTC (SPEC §5)

EVENT_COLUMNS = ["domain", "change_ts", "prev_capture_ts", "bracket_hours", "bots_changed",
                 "direction", "in_cf_managed_change", "source"]


def _ts(v) -> pd.Timestamp | None:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return None
    try:
        s = str(v)
        if s.isdigit() and len(s) == 14:  # Wayback yyyymmddhhmmss
            return pd.Timestamp(datetime.strptime(s, "%Y%m%d%H%M%S"), tz="UTC")
        t = pd.Timestamp(v)
        return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    except (ValueError, TypeError):
        return None


def _tuple(v) -> dict:
    if isinstance(v, dict):
        return {str(k).lower(): x for k, x in v.items()}
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return {}
    try:
        d = json.loads(v)
        return {str(k).lower(): x for k, x in d.items()} if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def _live_entries(verdicts: pd.DataFrame, bots: list[str]) -> list[dict]:
    if verdicts is None or verdicts.empty or "source" not in verdicts.columns:
        return []
    v = verdicts[(verdicts["source"] == "live") & verdicts["bot"].isin(bots)]
    if v.empty:
        return []
    out = []
    has_cf = "in_cf_managed_block" in v.columns
    for (dom, snap), g in v.groupby(["domain", "snapshot"], sort=False):
        sd = g["snapshot_date"].dropna()
        if sd.empty:
            continue
        ts = pd.Timestamp(pd.Timestamp(sd.iloc[0]).date(), tz="UTC") + pd.Timedelta(
            hours=LIVE_HOUR_UTC)
        tup = dict(zip(g["bot"], g["verdict"], strict=True))
        cf = dict(zip(g["bot"], g["in_cf_managed_block"].fillna(False), strict=True)) \
            if has_cf else {}
        out.append({"domain": dom, "ts": ts, "tuple": tup, "cf": cf, "prev": None,
                    "cf_change": None, "source": "live"})
    return out


def _history_entries(history: pd.DataFrame) -> list[dict]:
    if history is None or history.empty:
        return []
    out = []
    for r in history.itertuples(index=False):
        ts = _ts(getattr(r, "version_ts", None))
        if ts is None:
            continue
        cf_change = getattr(r, "in_cf_managed_change", None)
        out.append({"domain": r.domain, "ts": ts, "tuple": _tuple(getattr(r, "meta_tuple", None)),
                    "cf": {}, "prev": _ts(getattr(r, "prev_capture_ts", None)),
                    "cf_change": None if cf_change is None or pd.isna(cf_change)
                    else bool(cf_change),
                    "source": getattr(r, "source", "wayback") or "wayback"})
    return out


def build_change_events(history: pd.DataFrame | None, verdicts: pd.DataFrame | None,
                        bots: list[str]) -> pd.DataFrame:
    """One row per detected Meta-related change (domain, change_ts, bracket, ...)."""
    bots = [b.lower() for b in bots]
    entries = _history_entries(history) + _live_entries(verdicts, bots)
    if not entries:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    entries.sort(key=lambda e: (e["domain"], e["ts"]))
    rows = []
    cur_dom = None
    state: dict[str, str] = {}
    state_cf: dict[str, bool] = {}
    prev_ts = None
    for e in entries:
        if e["domain"] != cur_dom:
            cur_dom, state, state_cf, prev_ts = e["domain"], {}, {}, None
        changed = []
        up = down = False
        for b in bots:
            v = e["tuple"].get(b)
            if v is None or v == INDETERMINATE or v not in RESTRICTIVENESS:
                continue
            old = state.get(b)
            if old is not None and old != v:
                changed.append(b)
                if RESTRICTIVENESS[v] > RESTRICTIVENESS[old]:
                    up = True
                elif RESTRICTIVENESS[v] < RESTRICTIVENESS[old]:
                    down = True
        if changed:
            prev = e["prev"] or prev_ts
            bracket = (e["ts"] - prev).total_seconds() / 3600 if prev is not None else None
            cf_change = e["cf_change"]
            if cf_change is None and e["cf"]:
                cf_change = all(bool(e["cf"].get(b)) or bool(state_cf.get(b)) for b in changed)
            rows.append({
                "domain": cur_dom, "change_ts": e["ts"], "prev_capture_ts": prev,
                "bracket_hours": bracket, "bots_changed": json.dumps(changed),
                "direction": ("mixed" if up and down else "more_restrictive" if up
                              else "less_restrictive" if down else "same"),
                "in_cf_managed_change": bool(cf_change) if cf_change is not None else False,
                "source": e["source"],
            })
        for b in bots:
            v = e["tuple"].get(b)
            if v is not None and v != INDETERMINATE and v in RESTRICTIVENESS:
                state[b] = v
                if e["cf"]:
                    state_cf[b] = bool(e["cf"].get(b))
        prev_ts = e["ts"]
    return pd.DataFrame(rows, columns=EVENT_COLUMNS)


def daily_timeline(events: pd.DataFrame, domains_by_group: dict[str, set[str]],
                   start: date | str = "2026-09-01", end: date | str | None = None) -> dict:
    """Daily counts of domains with a Meta-related change, per group (e.g. news/control)."""
    start_d = date.fromisoformat(str(start))
    if end is None:
        end_d = (events["change_ts"].max().date() if len(events) else start_d)
    else:
        end_d = date.fromisoformat(str(end))
    end_d = max(end_d, start_d)
    days = [start_d + timedelta(days=i) for i in range((end_d - start_d).days + 1)]
    ev = events.copy()
    if len(ev):
        ev["day"] = pd.to_datetime(ev["change_ts"], utc=True).dt.date
        ev = ev[(ev["day"] >= start_d) & (ev["day"] <= end_d)]
    out: dict = {"start": start_d.isoformat(), "end": end_d.isoformat(),
                 "dates": [d.isoformat() for d in days], "groups": {}}
    for name, doms in domains_by_group.items():
        sub = ev[ev["domain"].isin(doms)] if len(ev) else ev
        counts = {d: 0 for d in days}
        cf = {d: 0 for d in days}
        more = {d: 0 for d in days}
        if len(sub):
            for day, g in sub.groupby("day"):
                counts[day] = int(g["domain"].nunique())
                cf[day] = int(g.loc[g["in_cf_managed_change"], "domain"].nunique())
                more[day] = int(g.loc[g["direction"] == "more_restrictive", "domain"].nunique())
        br = pd.to_numeric(sub["bracket_hours"], errors="coerce").dropna() if len(sub) else []
        out["groups"][name] = {
            "n_domains": len(doms),
            "daily_changes": [counts[d] for d in days],
            "daily_cf_managed": [cf[d] for d in days],
            "daily_more_restrictive": [more[d] for d in days],
            "n_change_events": int(len(sub)),
            "n_domains_changed": int(sub["domain"].nunique()) if len(sub) else 0,
            "median_bracket_hours": float(pd.Series(br).median()) if len(br) else None,
        }
    return out
