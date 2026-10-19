"""Charts C1-C6 (SPEC §3.6): PNG (dpi 200) + SVG, neutral grayscale + one accent colour,
"Data: HasData" footer, n in every subtitle. Built only from a metrics JSON."""

from __future__ import annotations

import json
import logging
import textwrap
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

from mcs.analyze.common import OWNER_PREFIX, load_study

log = logging.getLogger(__name__)

INK = "#1F1F1F"
INK_2 = "#5C5C5C"
GRID = "#E3E3E3"
GRAY = "#A6A6A6"
DARK_GRAY = "#4D4D4D"
C1_PEERS = ["gptbot", "claudebot", "google-extended", "ccbot"]
SEG_LABELS = {
    "all_news": "All news", "tier_A": "Tier A (major brands)", "tier_B": "Tier B (regional)",
    "US": "US news", "GB": "UK news", "other": "Other news", "control": "Top-10k control",
    "control_ex_news": "Top-10k control", "control_top1000": "Control top-1k",
    "control_top5000": "Control top-5k",
}


def _style(config_dir=None) -> dict:
    b = load_study(config_dir).get("branding", {})
    return {"accent": b.get("accent", "#E4572E"), "footer": b.get("footer", "Data: HasData")}


def _rc():
    plt.rcParams.update({
        "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK_2,
        "xtick.color": INK_2, "ytick.color": INK, "axes.spines.top": False,
        "axes.spines.right": False, "axes.titlesize": 12, "svg.fonttype": "none",
        "axes.axisbelow": True,
    })


def _frame(fig, ax, title: str, subtitle: str, st: dict, snapshot_note: str = ""):
    width_in = fig.get_size_inches()[0]
    wrapped = textwrap.fill(subtitle, width=int(width_in * 15))
    fig.text(0.01, 0.975, title, ha="left", va="top", fontsize=12.5, weight="bold", color=INK)
    fig.text(0.01, 0.975 - 0.42 / fig.get_size_inches()[1], wrapped, ha="left", va="top",
             fontsize=8.5, color=INK_2, linespacing=1.3)
    foot = st["footer"] + (f"  ·  {snapshot_note}" if snapshot_note else "")
    fig.text(0.01, 0.012, foot, ha="left", va="bottom", fontsize=7.5, color=INK_2)


def _save(fig, out_dir: Path, name: str) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in ("png", "svg"):
        p = out_dir / f"{name}.{ext}"
        fig.savefig(p, dpi=200, facecolor="white")
        paths.append(str(p))
    plt.close(fig)
    return paths


def _ok(e: dict | None) -> bool:
    return bool(e) and e.get("pct") is not None and not e.get("suppressed")


def _fmt_pct(v: float) -> str:
    return f"{v:.0f}%"


def chart_c1(m: dict, out_dir: Path, st: dict) -> list[str]:
    """Grouped bar: % FULL_BLOCK per crawler, news vs control."""
    bots = m["bot_sets"]["META_TOKENS"] + [b for b in C1_PEERS if b not in
                                           m["bot_sets"]["META_TOKENS"]]
    news = m["M1"].get("all_news", {})
    ctrl = m["M1"].get("control_ex_news", {}) or m["M1"].get("control", {})
    fig, ax = plt.subplots(figsize=(8, 5.6))
    fig.subplots_adjust(left=0.24, right=0.96, top=0.84, bottom=0.1)
    h = 0.38
    ys = list(range(len(bots)))[::-1]
    for i, (series, color, label) in enumerate(((news, st["accent"], "News sites"),
                                                (ctrl, GRAY, "Top-10k control"))):
        for y, b in zip(ys, bots, strict=True):
            e = series.get(b)
            yy = y + (h / 2 if i == 0 else -h / 2)
            if not _ok(e):
                ax.text(1, yy, "n<20", va="center", fontsize=7, color=INK_2)
                continue
            ax.barh(yy, e["pct"], height=h - 0.04, color=color,
                    label=label if b == bots[0] else None)
            ax.errorbar(e["pct"], yy, xerr=[[e["pct"] - e["ci_low"]], [e["ci_high"] - e["pct"]]],
                        fmt="none", ecolor=INK_2, elinewidth=0.8, capsize=0)
            ax.text(e["ci_high"] + 1, yy, _fmt_pct(e["pct"]), va="center", fontsize=7,
                    color=INK)
    ax.set_yticks(ys, bots)
    ax.axhline(len(C1_PEERS) - 0.5, color=GRID, lw=1)
    ax.set_xlim(0, 100)
    ax.set_xlabel("% of sites that FULL_BLOCK the crawler in robots.txt (95% Wilson CI)")
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.legend(loc="lower right", frameon=False, fontsize=8)
    nn = news.get(bots[0], {}).get("denominator", 0)
    nc = ctrl.get(bots[0], {}).get("denominator", 0)
    _frame(fig, ax, "Which crawlers do sites block in robots.txt?",
           f"Meta's five documented crawlers vs peer AI-training crawlers. News n={nn}, "
           f"control n={nc} (determinate robots.txt only). Snapshot {m['snapshot']} "
           f"({m['snapshot_date']}).", st)
    return _save(fig, out_dir, "C1_block_rates")


def chart_c2(m: dict, out_dir: Path, st: dict) -> list[str]:
    """Timeline of daily Meta-related robots.txt changes with event markers."""
    tl = m.get("M11", {})
    dates = [date.fromisoformat(d) for d in tl.get("dates", [])]
    g = tl.get("groups", {}).get("news", {})
    total = g.get("daily_changes", [0] * len(dates))
    cf = g.get("daily_cf_managed", [0] * len(dates))
    other = [t - c for t, c in zip(total, cf, strict=True)]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    fig.subplots_adjust(left=0.07, right=0.98, top=0.84, bottom=0.1)
    if dates:
        ax.bar(dates, other, width=0.8, color=st["accent"], label="Other changes")
        ax.bar(dates, cf, bottom=other, width=0.8, color=GRAY,
               label="Inside a Cloudflare-managed block")
    ymax = max(total + [1])
    ax.set_ylim(0, ymax * 1.35 + 0.5)
    shown = [e for e in tl.get("events", [])
             if dates and dates[0] <= date.fromisoformat(e["date"]) <= dates[-1]]
    for i, ev in enumerate(shown):
        d = date.fromisoformat(ev["date"])
        ax.axvline(d, color=INK_2, lw=0.8, ls=(0, (3, 2)))
        late = (d - dates[0]).days > len(dates) / 2
        ax.text(d, (ymax * 1.35 + 0.5) * (0.82 - 0.08 * i),
                f"{ev['label']} ({d:%d %b}, per press reports) ", fontsize=6.5, color=INK_2,
                ha="right" if late else "left", va="top",
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.5})
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_ylabel("News sites changing Meta rules")
    ax.legend(loc="upper left", frameon=False, fontsize=8, bbox_to_anchor=(0, 1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    br = g.get("median_bracket_hours")
    brs = f"; median bracket {br:.0f} h" if br is not None else ""
    _frame(fig, ax, "Daily Meta-related robots.txt changes, news sites",
           f"{g.get('n_change_events', 0)} changes on {g.get('n_domains_changed', 0)} of "
           f"n={g.get('n_domains', 0)} news domains, {tl.get('start')} to {tl.get('end')}. "
           f"Dated at first capture of the new version{brs}.", st,
           "Wayback Machine captures + daily live snapshots")
    return _save(fig, out_dir, "C2_timeline")


def chart_c3(m: dict, out_dir: Path, st: dict) -> list[str]:
    """Exposure funnel."""
    seg = m["segments"].get("all_news", {})
    m7 = m["M7"].get("all_news", {})
    m8a = m["M8"].get("all_news", {}).get("meta-externalagent", {}).get("E1_E2_E2b", {})
    m8d = m["M8"].get("all_news", {}).get("meta-externalads", {}).get("E1_E2_E2b", {})
    steps = [
        ("News panel", seg.get("n_domains", 0)),
        ("Determinate robots.txt", seg.get("n_determinate", 0)),
        ("Any signal of Meta business-tool use (E1-E3)", m7.get("any", {}).get("numerator", 0)),
        ("Stronger signals (E1, E2 or E2b)", m7.get("E1_E2_E2b", {}).get("numerator", 0)),
        ("Stronger signals, not blocking meta-externalagent",
         m8a.get("of_linked", {}).get("numerator", 0)),
        ("Stronger signals, not blocking meta-externalads",
         m8d.get("of_linked", {}).get("numerator", 0)),
    ]
    base = max(steps[0][1], 1)
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    fig.subplots_adjust(left=0.40, right=0.95, top=0.8, bottom=0.14)
    ys = list(range(len(steps)))[::-1]
    for i, ((_label, n), y) in enumerate(zip(steps, ys, strict=True)):
        color = st["accent"] if i >= 4 else (DARK_GRAY if i >= 2 else GRAY)
        ax.barh(y, n, color=color, height=0.68)
        ax.text(n + base * 0.01, y, f"{n}  ({100 * n / base:.0f}%)", va="center", fontsize=8,
                color=INK)
    ax.set_yticks(ys, [s[0] for s in steps])
    ax.set_xlim(0, base * 1.2)
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_xlabel("News domains")
    _frame(fig, ax, "From the news panel to 'exposed' sites",
           f"n={steps[0][1]} news domains; signals are public proxies, not proof of a Meta "
           f"business account. Snapshot {m['snapshot']}.", st)
    return _save(fig, out_dir, "C3_exposure_funnel")


def chart_c4(m: dict, out_dir: Path, st: dict) -> list[str]:
    """Ads gap: among sites that FULL_BLOCK meta-externalagent, share leaving externalads open."""
    segs = [s for s in ("all_news", "tier_A", "tier_B", "control_ex_news") if s in m["M6"]]
    fig, ax = plt.subplots(figsize=(8, 4.4))
    fig.subplots_adjust(left=0.24, right=0.96, top=0.7, bottom=0.14)
    ys = list(range(len(segs)))[::-1]
    labels = []
    for y, s in zip(ys, segs, strict=True):
        e = m["M6"][s]
        labels.append(f"{SEG_LABELS.get(s, s)}\n(n={e['denominator']})")
        if not _ok(e):
            ax.text(1, y, "n<20", va="center", fontsize=8, color=INK_2)
            continue
        gap = e["pct"]
        ax.barh(y, 100 - gap, color=DARK_GRAY, height=0.6,
                label="Also blocks meta-externalads" if s == segs[0] else None)
        ax.barh(y, gap, left=100 - gap, color=st["accent"], height=0.6,
                label="Leaves meta-externalads unblocked" if s == segs[0] else None)
        ax.text(100 - gap + 1, y, _fmt_pct(gap), va="center", fontsize=8, color="white",
                weight="bold")
    ax.set_yticks(ys, labels)
    ax.set_ylim(-0.6, len(segs) - 0.4)
    ax.set_xlim(0, 100)
    ax.set_xlabel("% of sites that FULL_BLOCK meta-externalagent")
    ax.legend(loc="lower left", bbox_to_anchor=(-0.02, 1.0), ncol=2, frameon=False,
              fontsize=8)
    _frame(fig, ax, "The 'ads gap'",
           "Sites blocking Meta's AI-training crawler that leave open the crawler Meta "
           "describes for advertising and business products.", st)
    return _save(fig, out_dir, "C4_ads_gap")


def chart_c5(m: dict, out_dir: Path, st: dict) -> list[str]:
    """Tier/country breakdown of FULL_BLOCK for externalagent and externalads."""
    segs = [s for s in ("tier_A", "tier_B", "US", "GB", "other", "control_ex_news")
            if s in m["M1"]]
    bots = [("meta-externalagent", st["accent"]), ("meta-externalads", DARK_GRAY)]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    fig.subplots_adjust(left=0.24, right=0.96, top=0.78, bottom=0.11)
    h = 0.38
    ys = list(range(len(segs)))[::-1]
    labels = []
    for y, s in zip(ys, segs, strict=True):
        n = m["M1"][s].get("meta-externalagent", {}).get("denominator", 0)
        labels.append(f"{SEG_LABELS.get(s, s)} (n={n})")
        for i, (b, color) in enumerate(bots):
            e = m["M1"][s].get(b)
            yy = y + (h / 2 if i == 0 else -h / 2)
            if not _ok(e):
                ax.text(1, yy, "n<20", va="center", fontsize=7, color=INK_2)
                continue
            ax.barh(yy, e["pct"], height=h - 0.04, color=color, label=b if s == segs[0] else None)
            ax.text(e["pct"] + 1, yy, _fmt_pct(e["pct"]), va="center", fontsize=7, color=INK)
    ax.set_yticks(ys, labels)
    ax.set_xlim(0, 100)
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_xlabel("% FULL_BLOCK in robots.txt")
    ax.legend(loc="lower right", frameon=False, fontsize=8)
    _frame(fig, ax, "Blocking by tier and country",
           f"Segments with n<20 are suppressed. Snapshot {m['snapshot']} ({m['snapshot_date']}).",
           st)
    return _save(fig, out_dir, "C5_tier_country")


def chart_c6(m: dict, out_dir: Path, st: dict, min_group_n: int = 10) -> tuple[list[str], str]:
    """Owner-group heatmap (Tier B). Groups with n<10 are dropped and logged."""
    bots = m["bot_sets"]["META_TOKENS"] + ["gptbot"]
    groups, dropped = [], []
    for seg, d in m["M1"].items():
        if not seg.startswith(OWNER_PREFIX) or seg == f"{OWNER_PREFIX}independent/unknown":
            continue
        n = d.get("meta-externalagent", {}).get("denominator", 0)
        (groups if n >= min_group_n else dropped).append((seg, n))
    if dropped:
        log.info("C6: dropped owner groups with n<%d: %s", min_group_n, dropped)
    if len(groups) < 2:
        msg = f"C6 skipped: fewer than 2 owner groups with n>={min_group_n} (dropped {dropped})"
        return [], msg
    groups.sort(key=lambda g: -g[1])
    groups = groups[:20]
    data = [[m["M1"][g][b]["pct"] or 0 for b in bots] for g, _ in groups]
    cmap = LinearSegmentedColormap.from_list("acc", ["#FFFFFF", st["accent"]])
    height = 2.6 + 0.38 * len(groups)
    fig, ax = plt.subplots(figsize=(8.5, height))
    fig.subplots_adjust(left=0.3, right=0.97, top=1 - 1.0 / height, bottom=1.25 / height)
    ax.imshow(data, cmap=cmap, vmin=0, vmax=100, aspect="auto")
    for i, row in enumerate(data):
        for j, v in enumerate(row):
            ax.text(j, i, _fmt_pct(v), ha="center", va="center", fontsize=7,
                    color="white" if v > 60 else INK)
    ax.set_xticks(range(len(bots)), bots, rotation=30, ha="right", fontsize=7.5)
    ax.set_yticks(range(len(groups)),
                  [f"{g.removeprefix(OWNER_PREFIX)} (n={n})" for g, n in groups])
    ax.spines[:].set_visible(False)
    _frame(fig, ax, "FULL_BLOCK by owner group (Tier B)",
           f"Owner groups with n>={min_group_n} determinate domains. "
           f"Snapshot {m['snapshot']}.", st)
    return _save(fig, out_dir, "C6_owner_heatmap"), ""


def make_charts(metrics: dict | str | Path, out_dir: str | Path = "reports/charts",
                config_dir: str | Path | None = None) -> dict:
    """Render C1-C6. Returns {"files": {chart: [paths]}, "skipped": {chart: reason}}."""
    m = metrics if isinstance(metrics, dict) else json.loads(Path(metrics).read_text())
    out = Path(out_dir)
    st = _style(config_dir)
    _rc()
    res: dict = {"files": {}, "skipped": {}}
    for name, fn in (("C1", chart_c1), ("C2", chart_c2), ("C3", chart_c3), ("C4", chart_c4),
                     ("C5", chart_c5)):
        res["files"][name] = fn(m, out, st)
    files, msg = chart_c6(m, out, st)
    if files:
        res["files"]["C6"] = files
    else:
        res["skipped"]["C6"] = msg
        log.warning(msg)
    return res
