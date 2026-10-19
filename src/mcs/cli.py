"""`mcs` command line (spec §12). Every command is idempotent/resumable and appends to
data/manifest.jsonl."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import typer
import yaml

app = typer.Typer(add_completion=False, no_args_is_help=True)
CONFIG = Path("config/study.yaml")
PANEL = Path("data/panel/panel.csv")
MANIFEST = Path("data/manifest.jsonl")


def cfg() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return None


def manifest(command: str, start: float, counts: dict, errors: list | None = None) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "command": command, "git_sha": _git_sha(),
        "config_hash": hashlib.sha256(CONFIG.read_bytes()).hexdigest()[:16],
        "start": datetime.fromtimestamp(start, UTC).isoformat(timespec="seconds"),
        "end": datetime.now(UTC).isoformat(timespec="seconds"),
        "counts": counts, "credits_used": 0, "errors": errors or [],
    }
    with MANIFEST.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    print(json.dumps(entry, indent=1))


def panel_df() -> pd.DataFrame:
    if not PANEL.exists():
        typer.echo("panel.csv missing — run `mcs build-panel` first", err=True)
        raise typer.Exit(2)
    return pd.read_csv(PANEL)


def _require_identity(c: dict) -> None:
    if not c["identity"].get("confirmed"):
        typer.echo("Bot identity not confirmed in config/study.yaml — refusing live fetch.",
                   err=True)
        raise typer.Exit(3)


@app.command("build-panel")
def build_panel(no_liveness: bool = False):
    t = time.time()
    from mcs.panel.build import build_panel as bp
    bp(str(CONFIG), liveness=not no_liveness)
    df = panel_df()
    manifest("build-panel", t, df.groupby("tier").size().to_dict())


@app.command("fetch-live")
def fetch_live(label: str = typer.Option(..., help="T2, T3, T4 or Dyyyymmdd"),
               with_signals: bool = False, with_ads: bool | None = None,
               panel: str = "all", limit: int = 0):
    """Hosts + robots.txt (+ ads.txt on T2/T3) for the panel; homepage + DNS with --with-signals."""
    c = cfg()
    _require_identity(c)
    from mcs.fetch.live import run_live
    t = time.time()
    df = panel_df()
    if panel != "all":
        df = df[df.panel == panel]
    # news first so the most important part finishes earliest
    df = df.sort_values(["panel", "tier"], key=lambda s: s.map(
        {"news": 0, "control": 1, "A": 0, "B": 1}).fillna(2))
    domains = list(dict.fromkeys(df.domain))
    if limit:
        domains = domains[:limit]
    news = set(df[df.panel == "news"].domain)
    if with_ads is None:
        with_ads = label in ("T2", "T3")
    res = asyncio.run(run_live(domains, label, c, with_ads=with_ads,
                               signals_domains=news if with_signals else set()))
    manifest(f"fetch-live --label {label}", t, res)


@app.command("render")
def render(label: str = "T2", limit: int = 0):
    """Rendered homepage (headless Chromium) for news domains whose T2 robots allow us."""
    c = cfg()
    _require_identity(c)
    from mcs.fetch.render import render_domains
    from mcs.fetch.store import FetchLog
    t = time.time()
    rows = FetchLog(label).read()
    allowed = [(r["domain"], f"https://{r['host']}/") for r in rows
               if r["resource"] == "homepage" and r["fetch_status"] != "DISALLOWED_FOR_US"]
    if limit:
        allowed = allowed[:limit]
    res = asyncio.run(render_domains(allowed, c["identity"]["user_agent"]))
    manifest("render", t, res)


@app.command("fetch-wayback-history")
def fetch_wayback_history(frm: str = typer.Option("2026-09-01", "--from"),
                          to: str = typer.Option("", "--to"), panel: str = "news",
                          deadline_min: int = 0, limit: int = 0):
    """All distinct robots.txt versions since --from (T0/T1 are derived from these)."""
    c = cfg()
    from mcs.fetch.wayback import run_history
    t = time.time()
    df = panel_df()
    if panel == "control":
        ctrl = df[(df.panel == "control")]
        domains = list(ctrl.sample(n=min(c["wayback"]["control_sample"], len(ctrl)),
                                   random_state=c["study"]["random_seed"]).domain)
        Path("data/panel/control_wayback_sample.csv").write_text("domain\n" + "\n".join(domains))
    else:
        domains = list(df[df.panel == "news"].sort_values("tier").domain.drop_duplicates())
    if limit:
        domains = domains[:limit]
    hosts_f = Path("data/processed/hosts.json")
    hosts = json.loads(hosts_f.read_text()) if hosts_f.exists() else {}
    to_ts = (to or datetime.now(UTC).strftime("%Y-%m-%d")).replace("-", "") + "235959"
    res = asyncio.run(run_history(domains, hosts, c, frm.replace("-", ""), to_ts,
                                  deadline_s=deadline_min * 60 or None))
    manifest(f"fetch-wayback-history --panel {panel}", t, res)


@app.command("fetch-wayback")
def fetch_wayback(label: str, cutoff: str = ""):
    """Compatibility alias: T0/T1 are selected from the version history at parse time."""
    typer.echo(f"{label}: baselines are derived from `fetch-wayback-history` during `mcs parse` "
               f"(cutoff from config: {cfg()['snapshots'][label]['cutoff']}).")


@app.command("fetch-wayback-homepages")
def fetch_wayback_homepages():
    """§8.3 homepage fallback for news domains that disallow us or block the live fetch."""
    c = cfg()
    from mcs.fetch.store import FetchLog
    from mcs.fetch.wayback import run_wayback_homepages
    t = time.time()
    rows = FetchLog("T2").read()
    rendered = {r["domain"] for r in FetchLog("RENDER").read() if r["fetch_status"] == "OK"
                and not r["challenge_detected"]}
    targets = []
    for r in rows:
        if r["resource"] != "homepage":
            continue
        bad = r["fetch_status"] != "OK" or r["challenge_detected"]
        if bad and r["domain"] not in rendered:
            targets.append((r["domain"], r["host"]))
    t2 = datetime.fromisoformat(c["snapshots"]["T2"]["date"])
    frm = (t2 - pd.Timedelta(days=30)).strftime("%Y%m%d")
    res = asyncio.run(run_wayback_homepages(targets, c, frm, t2.strftime("%Y%m%d") + "235959"))
    manifest("fetch-wayback-homepages", t, res)


@app.command("meta-docs-history")
def meta_docs_history():
    c = cfg()
    from mcs.fetch.wayback import run_meta_docs
    t = time.time()
    out = asyncio.run(run_meta_docs(c, datetime.now(UTC).strftime("%Y%m%d%H%M%S")))
    p = Path("data/processed/meta_docs.parquet")
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(out).to_parquet(p, index=False)
    print(pd.DataFrame(out).to_string())
    manifest("meta-docs-history", t, {"tokens": len(out)})


@app.command("parse")
def parse_cmd():
    """Parse all bodies -> fetches/groups/verdicts/history parquet (+ probes, disagreements)."""
    from mcs.pipeline import parse_all
    t = time.time()
    manifest("parse", t, parse_all(cfg()))


@app.command("verdicts")
def verdicts_cmd():
    """Alias of parse (verdicts are produced in the same pass)."""
    parse_cmd()


@app.command("signals")
def signals_cmd():
    from mcs.signals_run import build_signals
    t = time.time()
    manifest("signals", t, asyncio.run(build_signals(cfg())))


@app.command("analyze")
def analyze(snapshot: str = "T2"):
    from mcs.analyze.metrics import compute_metrics
    t = time.time()
    m = compute_metrics(snapshot)
    manifest(f"analyze --snapshot {snapshot}", t, {"keys": len(m)})


@app.command("report")
def report(snapshot: str = "T2"):
    from mcs.report import charts, factsheet, findings, methodology
    t = time.time()
    mpath = Path(f"reports/metrics_{snapshot}.json")
    metrics = json.loads(mpath.read_text())
    charts.make_charts(metrics)
    findings.write_findings(metrics)
    factsheet.write_factsheet(metrics)
    methodology.write_methodology(metrics=metrics)
    manifest(f"report --snapshot {snapshot}", t, {})


@app.command("site")
def site():
    from mcs.site.build import build_site
    t = time.time()
    build_site(methodology_url="https://github.com/alexter123123123/research-meta/blob/HEAD/docs/methodology.md")
    manifest("site", t, {})


def _latest_snapshot() -> str:
    v = pd.read_parquet("data/processed/verdicts.parquet", columns=["snapshot", "snapshot_date"])
    live = v[~v.snapshot.isin(["T0", "T1"])]
    return live.sort_values("snapshot_date").snapshot.iloc[-1]


@app.command("monitor")
def monitor(label: str = ""):
    """Daily: fetch-live (robots only) -> parse -> analyze(latest) -> site.
    Exits nonzero (and writes reports/ALERT_<date>.md) on >5% new INDETERMINATE."""
    today = datetime.now(UTC)
    label = label or {"2026-10-29": "T3", "2026-11-06": "T4"}.get(
        today.strftime("%Y-%m-%d"), "D" + today.strftime("%Y%m%d"))
    fetch_live(label=label, with_signals=False, with_ads=None, panel="all", limit=0)
    parse_cmd()
    v = pd.read_parquet("data/processed/verdicts.parquet")
    cur = v[(v.snapshot == label) & (v.bot == "meta-externalagent")]
    share = (cur.verdict == "INDETERMINATE").mean() if len(cur) else 1.0
    base = v[(v.snapshot == "T2") & (v.bot == "meta-externalagent")]
    base_share = (base.verdict == "INDETERMINATE").mean() if len(base) else 0.0
    if share - base_share > 0.05 or not len(cur):
        p = Path(f"reports/ALERT_{today:%Y-%m-%d}.md")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# ALERT {today:%Y-%m-%d}\n\nSnapshot {label}: indeterminate share "
                     f"{share:.1%} vs T2 {base_share:.1%} (n={len(cur)}). Tracker not updated.\n")
        typer.echo(p.read_text(), err=True)
        raise typer.Exit(1)
    analyze(snapshot=label)
    site()


@app.command("all")
def all_cmd(snapshot: str = "T2"):
    """Full launch run (expects panel + fetches already present or fetchable)."""
    c = cfg()
    _require_identity(c)
    if not PANEL.exists():
        build_panel()
    fetch_live(label=snapshot, with_signals=True, with_ads=True, panel="all", limit=0)
    parse_cmd()
    signals_cmd()
    analyze(snapshot=snapshot)
    report(snapshot=snapshot)
    site()


if __name__ == "__main__":
    app()
    sys.exit(0)
