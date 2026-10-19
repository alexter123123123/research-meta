"""Sanity benchmarks (SPEC §10.2). A benchmark is flagged when our figure is >10 pp off."""

from __future__ import annotations

FLAG_PP = 10.0

BENCHMARKS = [
    {
        "id": "B1",
        "name": "Control top-1,000: any rule naming meta-externalagent (M2) vs knownagents.com",
        "reference_pct": 19.0,
        "reference_source": "knownagents.com daily scans of the top 1,000 websites (~19%)",
        "path": ("M2", "control_top1000", "meta-externalagent"),
    },
    {
        "id": "B2",
        "name": "Control top-5,000: meta-externalagent FULL_BLOCK (M1) vs 7 Sep 2026 Tranco-5k "
                "census",
        "reference_pct": 17.2,
        "reference_source": "dev.to census of the Tranco top 5,000, 7 Sep 2026 (17.2%)",
        "path": ("M1", "control_top5000", "meta-externalagent"),
    },
    {
        "id": "B3",
        "name": "Tier A US: FULL_BLOCK of any peer AI-training crawler vs Axios 102 publishers "
                "(directional only)",
        "reference_pct": 42.0,
        "reference_source": "Axios analysis of 102 US publishers, 17 Oct 2026 (~42% block "
                            "training crawlers)",
        "path": ("M1_sets", "tier_A_US", "PEER_AI_TRAINING"),
    },
]


def run_benchmarks(metrics: dict, min_n: int = 20) -> list[dict]:
    """Return pass/flag/insufficient_data rows for each benchmark."""
    rows = []
    for b in BENCHMARKS:
        m, seg, key = b["path"]
        entry = (metrics.get(m) or {}).get(seg, {}).get(key)
        row = {k: v for k, v in b.items() if k != "path"}
        row["metric"] = f"{m}.{seg}.{key}"
        if not entry or entry.get("pct") is None or entry.get("denominator", 0) < min_n:
            row.update({"our_pct": entry.get("pct") if entry else None,
                        "n": entry.get("denominator") if entry else 0,
                        "diff_pp": None, "status": "insufficient_data"})
        else:
            diff = entry["pct"] - b["reference_pct"]
            row.update({"our_pct": entry["pct"], "n": entry["denominator"],
                        "numerator": entry["numerator"], "diff_pp": diff,
                        "status": "flag" if abs(diff) > FLAG_PP else "pass"})
        rows.append(row)
    return rows
