"""Shared helpers for analysis/reporting: config, panel loading, segments, snapshots."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"

STANDARD_SNAPSHOTS = ["T0", "T1", "T2", "T3", "T4"]
STANDARD_PAIRS = [("T0", "T2"), ("T1", "T2"), ("T2", "T3"), ("T3", "T4")]
SNAPSHOT_DEFAULT_DATES = {
    "T0": date(2026, 10, 1),
    "T1": date(2026, 10, 14),
    "T2": date(2026, 10, 20),
    "T3": date(2026, 10, 29),
    "T4": date(2026, 11, 6),
}
_D_LABEL = re.compile(r"^D(\d{8})$")

# Segment keys that describe news domains (signals only exist for news).
NEWS_SEGMENTS_FIXED = ["all_news", "tier_A", "tier_B", "US", "GB", "other", "tier_A_US"]
CONTROL_SEGMENTS = ["control", "control_ex_news", "control_top1000", "control_top5000"]
OWNER_PREFIX = "owner:"
UNKNOWN_OWNER = "independent/unknown"


def _cfg_dir(config_dir: str | Path | None) -> Path:
    return Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR


@lru_cache(maxsize=8)
def _load_yaml(path: str) -> object:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_bots(config_dir: str | Path | None = None) -> dict[str, list[str]]:
    data = _load_yaml(str(_cfg_dir(config_dir) / "bots.yaml"))
    return {k: [str(t).lower() for t in v] for k, v in dict(data).items()}


def load_study(config_dir: str | Path | None = None) -> dict:
    return dict(_load_yaml(str(_cfg_dir(config_dir) / "study.yaml")))


def load_events(config_dir: str | Path | None = None) -> list[dict]:
    path = _cfg_dir(config_dir) / "events.yaml"
    if not path.exists():
        return []
    out = []
    for e in _load_yaml(str(path)) or []:
        d = e["date"]
        out.append({"date": d if isinstance(d, date) else date.fromisoformat(str(d)),
                    "label": str(e["label"])})
    return out


def min_n(config_dir: str | Path | None = None) -> int:
    return int(load_study(config_dir).get("analysis", {}).get("min_n", 20))


def all_bots(bots: dict[str, list[str]]) -> list[str]:
    seen: list[str] = []
    for key in ("META_TOKENS", "LEGACY_META", "PEER_AI_TRAINING", "PEER_AI_SEARCH",
                "CLASSIC_SEARCH"):
        for b in bots.get(key, []):
            if b not in seen:
                seen.append(b)
    return seen


# --------------------------------------------------------------------------- snapshots

def snapshot_sort_key(label: str) -> date:
    """Chronological key for snapshot labels (T0..T4, Dyyyymmdd)."""
    if label in SNAPSHOT_DEFAULT_DATES:
        return SNAPSHOT_DEFAULT_DATES[label]
    m = _D_LABEL.match(label)
    if m:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    return date.max


def snapshot_date(label: str, verdicts: pd.DataFrame | None = None) -> date:
    """Best date for a snapshot label: from verdicts.snapshot_date (most common), else default."""
    if verdicts is not None and "snapshot_date" in verdicts.columns and len(verdicts):
        s = verdicts.loc[verdicts["snapshot"] == label, "snapshot_date"].dropna()
        if len(s):
            v = pd.to_datetime(s).dt.date.mode()
            if len(v):
                return v.iloc[0]
    return snapshot_sort_key(label)


# --------------------------------------------------------------------------- io

def read_parquet_safe(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(p)
    except Exception:  # noqa: BLE001 - corrupt/empty file is treated as absent
        return pd.DataFrame()


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return False
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y"}


def _brands(v) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "":
        return []
    try:
        out = json.loads(v)
        return [str(x) for x in out] if isinstance(out, list) else [str(out)]
    except (ValueError, TypeError):
        return [str(v)]


def load_panel(panel_csv: str | Path) -> pd.DataFrame:
    """Read panel.csv with normalized types."""
    df = pd.read_csv(panel_csv, dtype={"country": "object", "owner_group": "object"},
                     keep_default_na=False, na_values=[""])
    df["domain"] = df["domain"].astype(str).str.lower().str.strip()
    for col in ("control_top1000", "is_news"):
        df[col] = df[col].map(_to_bool) if col in df.columns else False
    df["country"] = df.get("country", pd.Series("XX", index=df.index)).fillna("XX")
    df["owner_group"] = df.get("owner_group", pd.Series(None, index=df.index)).fillna(
        UNKNOWN_OWNER).replace("", UNKNOWN_OWNER)
    df["tranco_rank"] = pd.to_numeric(df.get("tranco_rank"), errors="coerce")
    df["brands_list"] = df.get("brands", pd.Series("[]", index=df.index)).map(_brands)
    return df.drop_duplicates(subset=["domain", "panel"]).reset_index(drop=True)


def segment_domains(panel: pd.DataFrame, owner_min_domains: int = 5) -> dict[str, set[str]]:
    """Map segment key -> set of domains (see SPEC §2)."""
    news = panel[panel["panel"] == "news"]
    ctrl = panel[panel["panel"] == "control"]
    segs: dict[str, set[str]] = {
        "all_news": set(news["domain"]),
        "tier_A": set(news.loc[news["tier"] == "A", "domain"]),
        "tier_B": set(news.loc[news["tier"] == "B", "domain"]),
        "US": set(news.loc[news["country"] == "US", "domain"]),
        "GB": set(news.loc[news["country"] == "GB", "domain"]),
        "other": set(news.loc[~news["country"].isin(["US", "GB"]), "domain"]),
        "tier_A_US": set(news.loc[(news["tier"] == "A") & (news["country"] == "US"), "domain"]),
        "control": set(ctrl["domain"]),
        "control_ex_news": set(ctrl.loc[~ctrl["is_news"], "domain"]),
        "control_top1000": set(ctrl.loc[ctrl["control_top1000"]
                                        | (ctrl["tranco_rank"] <= 1000), "domain"]),
        "control_top5000": set(ctrl.loc[ctrl["tranco_rank"] <= 5000, "domain"]),
    }
    tb = news[news["tier"] == "B"]
    for grp, sub in tb.groupby("owner_group"):
        if len(sub) >= owner_min_domains:
            segs[f"{OWNER_PREFIX}{grp}"] = set(sub["domain"])
    return segs


def is_news_segment(seg: str) -> bool:
    return seg in NEWS_SEGMENTS_FIXED or seg.startswith(OWNER_PREFIX)


def nan_to_none(obj):
    """Recursively turn NaN/NaT/numpy scalars into JSON-safe values."""
    import math

    import numpy as np

    if isinstance(obj, dict):
        return {str(k): nan_to_none(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [nan_to_none(v) for v in obj]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat()
    return obj


def write_json(obj, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(nan_to_none(obj), indent=2, sort_keys=False, ensure_ascii=False),
                 encoding="utf-8")
    return p


def find_metrics_files(reports_dir: str | Path) -> list[Path]:
    """All reports/metrics_<snapshot>.json sorted chronologically."""
    files = list(Path(reports_dir).glob("metrics_*.json"))
    return sorted(files, key=lambda f: snapshot_sort_key(f.stem.removeprefix("metrics_")))
