"""End-to-end analysis/report/site test on synthetic data (no network)."""

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from mcs.analyze.changes import CHANGES_COLUMNS, pairs_for_snapshot
from mcs.analyze.metrics import compute_metrics
from mcs.analyze.timeline import build_change_events
from mcs.report.charts import make_charts
from mcs.report.factsheet import write_factsheet
from mcs.report.findings import FORBIDDEN_PHRASES, write_findings
from mcs.report.methodology import PREREGISTRATION, write_methodology
from mcs.site.build import build_site

_SPEC = importlib.util.spec_from_file_location(
    "make_synthetic", Path(__file__).parent / "fixtures" / "synthetic" / "make_synthetic.py")
make_synthetic_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(make_synthetic_mod)

ENTRY_KEYS = {"numerator", "denominator", "pct", "ci_low", "ci_high", "n_indeterminate",
              "suppressed"}


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    root = tmp_path_factory.mktemp("synth")
    paths = make_synthetic_mod.make_synthetic(root)
    m2 = compute_metrics("T2", paths["processed_dir"], paths["panel_csv"], paths["reports_dir"])
    md = compute_metrics("D20261021", paths["processed_dir"], paths["panel_csv"],
                         paths["reports_dir"])
    return paths, m2, md


def test_metrics_structure(synth):
    paths, m, _ = synth
    assert (paths["reports_dir"] / "metrics_T2.json").exists()
    for seg in ("all_news", "tier_A", "tier_B", "US", "GB", "other", "control",
                "control_ex_news", "control_top1000", "control_top5000", "owner:Gannett"):
        assert seg in m["segments"], seg
        e = m["M1"][seg]["meta-externalagent"]
        assert ENTRY_KEYS <= set(e)
        assert e["suppressed"] == (e["denominator"] < 20)
    for key in ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10", "M11", "M12",
                "M1_weighted", "hypotheses", "benchmarks"):
        assert key in m
    e = m["M1"]["all_news"]["meta-externalagent"]
    assert e["denominator"] + e["n_indeterminate"] == m["segments"]["all_news"]["n_domains"]
    assert e["ci_low"] <= e["pct"] <= e["ci_high"]
    # M6 denominator = news FULL_BLOCKing agent with determinate ads
    assert m["M6"]["all_news"]["denominator"] == e["numerator"]
    # M10 Newcombe diff present
    d = m["M10"]["M1"]["meta-externalagent"]
    assert d["diff_ci_low"] < d["diff_pp"] < d["diff_ci_high"]
    # M7/M8 only for news segments
    assert "all_news" in m["M7"] and "control" not in m["M7"]
    assert m["M8"]["all_news"]["meta-externalagent"]["E1_E2_E2b"]["of_linked"]["denominator"] > 0
    # M12
    assert m["M12"]["available"] and m["M12"]["rows"][1]["token"] == "meta-externalads"
    # hypotheses all evaluated
    assert set(m["hypotheses"]) == {f"H{i}" for i in range(1, 7)}
    for h in m["hypotheses"].values():
        assert h["outcome"] in {"supported", "not supported", "insufficient data"}
    assert {b["status"] for b in m["benchmarks"]} <= {"pass", "flag", "insufficient_data"}


def test_m4_changes(synth):
    paths, m, md = synth
    assert m["M4"]["pairs"] == ["T0->T2", "T1->T2"]
    s = m["M4"]["by_pair"]["T1->T2"]["all_news"]
    assert s["n_paired"] > 20
    assert s["any_meta_change"]["numerator"] > 0
    att = s["attribution"]
    assert att["cf_managed"] > 0 and att["authored"] > 0
    assert sum(att.values()) == s["any_meta_change"]["numerator"]
    mc = s["by_bot"]["meta-externalagent"]["mcnemar"]
    assert mc["c_newly_blocked"] > mc["b_blocked_then_not"]
    assert 0 <= mc["p_value"] <= 1
    cl = m["M4"]["clusters"]["T1->T2"]
    assert cl["clusters"] and cl["clusters"][0]["template_cluster"] == "tpl-gannett-v2"
    ch = pd.read_parquet(paths["processed_dir"] / "changes.parquet")
    assert list(ch.columns) == CHANGES_COLUMNS
    assert set(ch["attribution"].dropna()) <= {"authored", "cf_managed", "unknown"}
    assert ch.loc[ch["changed"], "change_date"].notna().any()
    assert set(md["M4"]["pairs"]) == {"T0->T2", "T1->T2", "T1->D20261021", "T2->D20261021"}


def test_pairs_for_snapshot():
    avail = ["T0", "T1", "T2", "T3"]
    assert pairs_for_snapshot("T2", avail) == [("T0", "T2"), ("T1", "T2")]
    assert pairs_for_snapshot("T3", avail) == [("T0", "T2"), ("T1", "T2"), ("T2", "T3"),
                                               ("T1", "T3")]
    assert pairs_for_snapshot("T2", ["T2"]) == []


def test_timeline_events():
    hist = pd.DataFrame([
        {"domain": "a.com", "version_ts": "2026-09-05T00:00:00Z", "prev_capture_ts": None,
         "meta_tuple": json.dumps({"meta-externalagent": "ALLOWED_DEFAULT"}),
         "in_cf_managed_change": False, "source": "wayback"},
        {"domain": "a.com", "version_ts": "2026-10-16T12:00:00Z",
         "prev_capture_ts": "2026-10-15T12:00:00Z",
         "meta_tuple": json.dumps({"meta-externalagent": "FULL_BLOCK"}),
         "in_cf_managed_change": True, "source": "wayback"},
        {"domain": "a.com", "version_ts": "2026-10-17T12:00:00Z",
         "prev_capture_ts": "2026-10-16T18:00:00Z",
         "meta_tuple": json.dumps({"meta-externalagent": "INDETERMINATE"}),
         "in_cf_managed_change": False, "source": "wayback"},
    ])
    ev = build_change_events(hist, None, ["meta-externalagent"])
    assert len(ev) == 1
    r = ev.iloc[0]
    assert r["bracket_hours"] == 24 and r["direction"] == "more_restrictive"
    assert bool(r["in_cf_managed_change"])


def test_domain_summary(synth):
    paths, _, _ = synth
    full = pd.read_csv(paths["processed_dir"] / "domain_summary.csv")
    pub = pd.read_csv(paths["processed_dir"] / "domain_summary_public.csv")
    assert set(full["snapshot"]) == {"T2", "D20261021"}
    assert set(pub["tier"]) == {"A"}
    for col in ("meta-externalagent", "ccbot", "meta_linked_level", "changed_since_T1",
                "attribution"):
        assert col in full.columns


def test_reports_and_site(synth):
    paths, m, md = synth
    rdir = paths["reports_dir"]
    res = make_charts(m, rdir / "charts")
    for c in ("C1", "C2", "C3", "C4", "C5"):
        assert all(Path(p).exists() for p in res["files"][c])
        assert {Path(p).suffix for p in res["files"][c]} == {".png", ".svg"}
    assert "C6" in res["files"] or "C6" in res["skipped"]

    f = write_findings(md, rdir / "findings.md")
    text = f.read_text()
    assert "## The 10 strongest statements" in text
    assert "## What this does not show" in text
    assert "## Change since T2" in text  # delta vs earlier metrics JSON
    assert "| H1 |" in text and "| H6 |" in text
    assert "the crawler Meta describes for advertising and business products" in text
    assert text.count("\n1. ") == 1 and "\n10. " in text
    for bad in FORBIDDEN_PHRASES:
        assert bad not in text.lower()

    fs = write_factsheet(m, rdir / "factsheet.md").read_text()
    assert "Meta was asked for comment on [date]" in fs
    assert "What we did NOT measure" in fs and "\n8. " in fs and "\n9. " not in fs
    assert "C1_block_rates" in fs

    meth = write_methodology(paths["root"] / "docs" / "methodology.md", metrics=m,
                             panel_meta_path=None).read_text()
    assert PREREGISTRATION in meth
    assert "Null results are still stories" in meth
    assert "not collected through HasData's Web Scraping API" in meth
    assert "GitHub Actions" in meth and "Chromium" in meth and "id_" in meth

    out = build_site(paths["site_dir"], rdir, paths["processed_dir"], paths["panel_csv"])
    html = out["index"].read_text()
    assert "cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js" in html
    assert "Data: HasData" in html and "prefers-color-scheme" in html
    assert "{{" not in html
    latest = json.loads(out["latest"].read_text())
    assert latest["snapshot"] == "D20261021"
    assert latest["counters"] and latest["c1"]["bots"] and latest["c2"]["dates"]
    panel = pd.read_csv(paths["panel_csv"])
    tier_a = set(panel.loc[panel["tier"] == "A", "domain"])
    tier_b = set(panel.loc[panel["tier"] == "B", "domain"])
    assert {r["domain"] for r in latest["table"]} == tier_a
    raw = out["latest"].read_text() + out["history"].read_text()
    assert not any(d in raw for d in tier_b)
    hist = json.loads(out["history"].read_text())["snapshots"]
    assert [h["snapshot"] for h in hist] == ["T0", "T1", "T2", "D20261021"]
