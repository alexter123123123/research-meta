"""reports/factsheet.md — one page for the PR team, generated from a metrics JSON."""

from __future__ import annotations

from pathlib import Path

from mcs.analyze.common import load_study
from mcs.report.findings import (
    FORBIDDEN_PHRASES,
    _load,
    nice_date,
    strongest_statements,
    template_sentences,
)

CHART_TITLES = {
    "C1_block_rates": "C1 — % FULL_BLOCK per crawler (Meta vs peers), news vs control",
    "C2_timeline": "C2 — daily Meta-related robots.txt changes, 1 Sep → today, with event "
                   "markers (per press reports)",
    "C3_exposure_funnel": "C3 — exposure funnel: panel → reachable → signals of Meta "
                          "business-tool use → not blocking",
    "C4_ads_gap": "C4 — the 'ads gap' (blocks meta-externalagent, not meta-externalads)",
    "C5_tier_country": "C5 — tier / country breakdown",
    "C6_owner_heatmap": "C6 — owner-group heatmap (Tier B, groups with n≥10)",
}


def render_factsheet(m: dict, charts_dir: str | Path | None = None,
                     config_dir: str | Path | None = None) -> str:
    study = load_study(config_dir)
    spokesperson = study.get("branding", {}).get("spokesperson", "[spokesperson]")
    footer = study.get("branding", {}).get("footer", "Data: HasData")
    title = (f"# Factsheet — Meta's crawlers and news publishers' robots.txt "
             f"({nice_date(m['snapshot_date'])})")
    L = [title, ""]
    L.append(f"Snapshot {m['snapshot']}. {m['panel']['n_news']} news domains, "
             f"{m['panel']['n_control']} top-10k control domains. All numbers generated from "
             f"`metrics_{m['snapshot']}.json`. {footer}.")
    L.append("")
    lead = template_sentences(m)
    if lead:
        L.append(f"**Lead:** {lead[0]}")
        L.append("")
    L.append("## Top 8 stats")
    L.append("")
    for i, s in enumerate(strongest_statements(m, 8), 1):
        L.append(f"{i}. **{s['text']}** (n = {s['numerator']}/{s['denominator']})  ")
        L.append(f"   _In plain English:_ {s['plain']}")
    L.append("")
    L.append("## Charts")
    L.append("")
    names = list(CHART_TITLES)
    if charts_dir and Path(charts_dir).exists():
        found = {p.stem for p in Path(charts_dir).glob("*.png")}
        names = [n for n in CHART_TITLES if n in found]
    for n in names:
        L.append(f"- {CHART_TITLES[n]} — `charts/{n}.png` / `.svg`")
    if not names:
        L.append("- (charts not rendered yet)")
    L.append("")
    L.append("## What we did NOT measure")
    L.append("")
    L.append("- Whether Meta (or anyone) actually obeys robots.txt — we read the rules, we did "
             "not test crawler behaviour or firewalls.")
    L.append("- Whether any site has a business relationship with Meta or is covered by its "
             "terms — we only see public signals of Meta business-tool use.")
    L.append("- Paywalls, logins, WAF/CDN bot rules or server-side blocking.")
    L.append("- Sites' robots.txt as seen from outside the US (one fetch location).")
    L.append("- Any legal question.")
    L.append("")
    L.append("## Right of reply")
    L.append("")
    L.append("Meta was asked for comment on [date]. [Response / no response by publication.]")
    L.append("")
    L.append("## Contact")
    L.append("")
    L.append(f"Spokesperson: {spokesperson}")
    L.append("")
    text = "\n".join(L)
    for bad in FORBIDDEN_PHRASES:
        if bad in text.lower():
            raise ValueError(f"factsheet violates language rules: {bad!r}")
    return text


def write_factsheet(metrics: dict | str | Path, out_path: str | Path = "reports/factsheet.md",
                    charts_dir: str | Path | None = None,
                    config_dir: str | Path | None = None) -> Path:
    m = _load(metrics)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_factsheet(m, charts_dir or out.parent / "charts", config_dir),
                   encoding="utf-8")
    return out
