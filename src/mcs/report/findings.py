"""reports/findings.md, generated only from a metrics JSON (no hand-typed numbers).

Language rules (SPEC §11): "blocks in robots.txt" (never "protected"), "signals of Meta
business-tool use" (never "has a business account" / "bound by the terms"), and
`meta-externalads` is "the crawler Meta describes for advertising and business products".
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from mcs.analyze.common import find_metrics_files, snapshot_sort_key

AGENT = "meta-externalagent"
ADS = "meta-externalads"
ADS_DESC = "the crawler Meta describes for advertising and business products"
FORBIDDEN_PHRASES = ["is protected", "are protected", "has a business account",
                     "have a business account", "bound by the terms", "is bound by"]


# --------------------------------------------------------------------------- formatting

def pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f}%"


def ci(e: dict) -> str:
    if e.get("ci_low") is None:
        return "CI n/a"
    return f"95% CI {e['ci_low']:.1f}–{e['ci_high']:.1f}%"


def frac(e: dict) -> str:
    return f"{e['numerator']}/{e['denominator']}"


def nice_date(d: str | None) -> str:
    if not d:
        return "n/a"
    s = str(d)
    try:
        if s.isdigit() and len(s) >= 8:
            dt = datetime.strptime(s[:8], "%Y%m%d").date()
        else:
            dt = date.fromisoformat(s[:10])
        return f"{dt.day} {dt:%b %Y}"
    except ValueError:
        return s


def ok(e: dict | None, min_n: int = 20) -> bool:
    return bool(e) and e.get("pct") is not None and e.get("denominator", 0) >= min_n \
        and not e.get("suppressed")


def _load(m: dict | str | Path) -> dict:
    return m if isinstance(m, dict) else json.loads(Path(m).read_text(encoding="utf-8"))


def _get(m: dict, *path):
    cur = m
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _since_t1_pair(m: dict) -> str | None:
    snap = m["snapshot"]
    for p in (f"T1->{snap}", f"T0->{snap}"):
        if p in _get(m, "M4", "by_pair") or {}:
            return p
    return None


# --------------------------------------------------------------------------- statements

def template_sentences(m: dict) -> list[str]:
    """SPEC §14 opening sentences; any with n < min_n is dropped."""
    mn = m.get("min_n", 20)
    out = []
    sd = nice_date(m.get("snapshot_date"))
    e = _get(m, "M1", "all_news", AGENT)
    c = _get(m, "M1", "control_ex_news", AGENT)
    if ok(e, mn) and ok(c, mn):
        out.append(f"{pct(e['pct'])} of {e['denominator']} news sites ({ci(e)}) explicitly "
                   f"block `{AGENT}` in robots.txt as of {sd}, versus {pct(c['pct'])} of the "
                   f"top-10k general sites (n={c['denominator']}).")
    pair = _since_t1_pair(m)
    if pair:
        s = _get(m, "M4", "by_pair", pair, "all_news")
        a = s["any_meta_change"]
        if a["denominator"] >= mn:
            att = s["attribution"]
            lead = "Only " if (a["pct"] or 0) < 5 else ""
            frm = "14 Oct" if pair.startswith("T1") else "1 Oct"
            unk = (f"; {att['unknown']} changed only the wildcard (`*`) group, so attribution "
                   f"is unknown" if att.get("unknown") else "")
            out.append(f"{lead}{a['numerator']} of {a['denominator']} news sites with archived "
                       f"robots.txt changed any Meta crawler rule between {frm} and {sd}; "
                       f"{att['authored']} were publisher-authored, {att['cf_managed']} came via "
                       f"Cloudflare-managed rules{unk}.")
    e = _get(m, "M6", "all_news")
    if ok(e, mn):
        out.append(f"Of the {e['denominator']} news sites that block `{AGENT}` (the crawler "
                   f"Meta's documentation describes for AI training) in robots.txt, "
                   f"{pct(e['pct'])} ({frac(e)}) leave `{ADS}` — {ADS_DESC} — unblocked.")
    e = _get(m, "M5", "all_news")
    if ok(e, mn):
        out.append(f"{pct(e['pct'])} of the {e['denominator']} news sites that block at least "
                   f"one of OpenAI's, Anthropic's, Google's or Common Crawl's training crawlers "
                   f"in robots.txt do not block Meta's (`{AGENT}`) ({frac(e)}).")
    lk = _get(m, "M7", "all_news", "E1_E2_E2b")
    ex = _get(m, "M8", "all_news", AGENT, "E1_E2_E2b", "of_linked")
    if ok(lk, mn) and ok(ex, mn):
        out.append(f"{pct(lk['pct'])} of news sites ({frac(lk)}) show at least one public "
                   f"signal of Meta business-tool use (domain verification, Meta Pixel or "
                   f"Audience Network); {pct(ex['pct'])} of those ({frac(ex)}) do not block "
                   f"`{AGENT}` in robots.txt.")
    e = _get(m, "M9", "all_news", "fbhit_full_block")
    if ok(e, mn):
        out.append(f"{e['numerator']} of {e['denominator']} news sites block "
                   f"`facebookexternalhit` in robots.txt, which can break link previews on "
                   f"Facebook and Instagram.")
    rows = _get(m, "M12", "rows") or []
    for r in rows:
        if r["token"] == ADS and r.get("first_seen_capture"):
            extra = (f" (the latest earlier capture without it is dated "
                     f"{nice_date(r['last_absent_capture'])})" if r.get("last_absent_capture")
                     else "")
            out.append(f"Meta's crawler documentation first lists `{ADS}` in an archived "
                       f"capture dated {nice_date(r['first_seen_capture'])}{extra}.")
    return out


def strongest_statements(m: dict, k: int = 10) -> list[dict]:
    """Ranked statements (fixed priority order of the study's questions), n>=min_n only.

    Each item: {"id", "text", "plain", "numerator", "denominator", "metric"}.
    """
    mn = m.get("min_n", 20)
    cands: list[dict] = []

    def add(sid, e, text, plain, metric):
        if ok(e, mn):
            cands.append({"id": sid, "text": text, "plain": plain, "metric": metric,
                          "numerator": e["numerator"], "denominator": e["denominator"],
                          "pct": e["pct"]})

    e = _get(m, "M6", "all_news")
    if e:
        add("ads_gap", e, f"Ads gap: {pct(e['pct'])} ({frac(e)}; {ci(e)}) of news sites that "
            f"FULL_BLOCK `{AGENT}` in robots.txt do not block `{ADS}`, {ADS_DESC}.",
            "This share of publishers blocking Meta's AI-training crawler still leaves its "
            "advertising/business crawler open in robots.txt.", "M6.all_news")
    e = _get(m, "M1", "all_news", AGENT)
    if e:
        add("m1_agent", e, f"{pct(e['pct'])} ({frac(e)}; {ci(e)}) of news sites FULL_BLOCK "
            f"`{AGENT}` in robots.txt.",
            "This is the share of news sites whose robots.txt asks Meta's AI-training "
            "crawler to stay out entirely.", f"M1.all_news.{AGENT}")
    d = _get(m, "M10", "M1", AGENT)
    if d and not d.get("suppressed") and d.get("diff_pp") is not None:
        e = d["news"]
        add("m10_diff", e, f"News sites block `{AGENT}` in robots.txt "
            f"{abs(d['diff_pp']):.1f} percentage points "
            f"{'more' if d['diff_pp'] >= 0 else 'less'} often than top-10k general sites "
            f"({pct(e['pct'])}, {frac(e)} vs {pct(d['control']['pct'])}, "
            f"{frac(d['control'])}; difference 95% CI {d['diff_ci_low']:.1f} to "
            f"{d['diff_ci_high']:.1f} pp, Newcombe).",
            "News publishers differ from the general web in how often they block Meta's "
            "AI-training crawler.", f"M10.M1.{AGENT}")
    e = _get(m, "M5", "all_news")
    if e:
        add("meta_gap", e, f"Meta gap: {pct(e['pct'])} ({frac(e)}; {ci(e)}) of news sites that "
            f"FULL_BLOCK at least one of gptbot, claudebot, google-extended or ccbot do not "
            f"FULL_BLOCK `{AGENT}`.",
            "This share of publishers blocking other AI companies' training crawlers does not "
            "block Meta's.", "M5.all_news")
    e = _get(m, "M8", "all_news", AGENT, "E1_E2_E2b", "of_linked")
    if e:
        add("exposed_agent", e, f"{pct(e['pct'])} ({frac(e)}; {ci(e)}) of news sites with "
            f"signals of Meta business-tool use (E1/E2/E2b) do not block `{AGENT}` in "
            f"robots.txt.",
            "Among sites with public signs of using Meta's business tools, this share does "
            "not block Meta's AI-training crawler in robots.txt.",
            f"M8.all_news.{AGENT}.E1_E2_E2b.of_linked")
    e = _get(m, "M8", "all_news", ADS, "E1_E2_E2b", "of_linked")
    if e:
        add("exposed_ads", e, f"{pct(e['pct'])} ({frac(e)}; {ci(e)}) of news sites with "
            f"signals of Meta business-tool use (E1/E2/E2b) do not block `{ADS}`, {ADS_DESC}.",
            "Among sites with public signs of using Meta's business tools, this share leaves "
            "Meta's advertising/business crawler unblocked.",
            f"M8.all_news.{ADS}.E1_E2_E2b.of_linked")
    pair = _since_t1_pair(m)
    if pair:
        s = _get(m, "M4", "by_pair", pair, "all_news")
        e = s["any_meta_change"]
        add("m4_any", e, f"{pct(e['pct'])} ({frac(e)}) of news sites with robots.txt at both "
            f"{pair.replace('->', ' and ')} changed any Meta crawler rule "
            f"({s['attribution']['authored']} publisher-authored, "
            f"{s['attribution']['cf_managed']} via Cloudflare-managed rules).",
            "This is how many publishers changed their Meta rules since the story broke.",
            f"M4.{pair}.all_news.any_meta_change")
        bb = s["by_bot"].get(AGENT, {})
        e = bb.get("more_restrictive")
        mc = bb.get("mcnemar", {})
        if e:
            add("m4_agent", e, f"{pct(e['pct'])} ({frac(e)}) of paired news sites became more "
                f"restrictive toward `{AGENT}` between {pair.replace('->', ' and ')} "
                f"(newly FULL_BLOCK: {mc.get('c_newly_blocked', 'n/a')}, stopped: "
                f"{mc.get('b_blocked_then_not', 'n/a')}; exact McNemar p="
                f"{mc.get('p_value', float('nan')):.3g}).",
                "This is how many publishers tightened rules for Meta's AI-training crawler "
                "since the story broke.", f"M4.{pair}.all_news.by_bot.{AGENT}")
    e = _get(m, "M1", "all_news", ADS)
    if e:
        add("m1_ads", e, f"{pct(e['pct'])} ({frac(e)}; {ci(e)}) of news sites FULL_BLOCK "
            f"`{ADS}`, {ADS_DESC}, in robots.txt.",
            "This is the share of news sites asking Meta's advertising/business crawler to stay "
            "out entirely.",
            f"M1.all_news.{ADS}")
    e = _get(m, "M3", "all_news", AGENT)
    if e:
        add("m3_agent", e, f"Counting site-wide wildcard blocks too, {pct(e['pct'])} "
            f"({frac(e)}; {ci(e)}) of news sites block `{AGENT}` in robots.txt "
            f"(effective block).",
            "This also counts sites whose robots.txt blocks every bot it does not name.",
            f"M3.all_news.{AGENT}")
    e = _get(m, "M2", "all_news", "any_meta")
    if e:
        add("m2_any", e, f"{pct(e['pct'])} ({frac(e)}) of news sites name at least one of "
            f"Meta's five documented crawlers anywhere in robots.txt.",
            "This is how many publishers mention any Meta crawler at all.",
            "M2.all_news.any_meta")
    e = _get(m, "M9", "all_news", "fbhit_full_block")
    if e:
        add("m9_fbhit", e, f"{pct(e['pct'])} ({frac(e)}) of news sites block "
            f"`facebookexternalhit` in robots.txt, which can break Facebook/Instagram link "
            f"previews.",
            "These publishers block the crawler behind Facebook/Instagram link previews.",
            "M9.all_news.fbhit_full_block")
    e = _get(m, "M7", "all_news", "any")
    if e:
        add("m7_any", e, f"{pct(e['pct'])} ({frac(e)}) of news sites show at least one public "
            f"signal of Meta business-tool use (including Facebook/Instagram profile links).",
            "This is the share of news sites with any public sign of using Meta's business "
            "tools.",
            "M7.all_news.any")
    for seg, lab in (("tier_A", "major (Tier A)"), ("tier_B", "regional (Tier B)")):
        e = _get(m, "M1", seg, AGENT)
        if e:
            add(f"m1_{seg}", e, f"{pct(e['pct'])} ({frac(e)}; {ci(e)}) of {lab} news sites "
                f"FULL_BLOCK `{AGENT}` in robots.txt.",
                f"Blocking rate among {lab} publishers.", f"M1.{seg}.{AGENT}")
    e = _get(m, "M9", "all_news", "legacy_only")
    if e:
        add("m9_legacy", e, f"{pct(e['pct'])} ({frac(e)}) of news sites name only legacy Meta "
            f"tokens (facebookbot/facebot/facebookcatalog) and none of the current ones.",
            "These robots.txt files target only outdated Meta crawler names.",
            "M9.all_news.legacy_only")
    e = _get(m, "nonstandard_meta", "all_news")
    if e:
        add("nonstandard", e, f"{pct(e['pct'])} ({frac(e)}) of news sites use a non-standard "
            f"spelling for a Meta crawler (e.g. `Meta-External*`) that RFC 9309 parsers do not "
            f"match.",
            "These robots.txt files misspell Meta's crawler names, so the rule may not apply.",
            "nonstandard_meta.all_news")
    return cands[:k]


def _hyp_evidence(h: dict) -> str:
    if h["outcome"] == "insufficient data":
        n = h.get("denominator")
        return f"n={n}" if n is not None else "no data"
    if "value_pct" in h:
        s = f"{pct(h['value_pct'])} ({h['numerator']}/{h['denominator']})"
        if h.get("ci_low") is not None:
            s += f", 95% CI {h['ci_low']:.1f}–{h['ci_high']:.1f}%"
        return s
    if h["id"] == "H3":
        return (f"externalagent {pct(h['agent_pct'])} ({h['agent_numerator']}/"
                f"{h['denominator']}) vs externalads {pct(h['ads_pct'])} "
                f"({h['ads_numerator']}/{h['denominator']}); McNemar b={h['mcnemar_b']}, "
                f"c={h['mcnemar_c']}, p={h['mcnemar_p']:.3g}")
    if h["id"] == "H4":
        return (f"any of gptbot/claudebot/google-extended {pct(h['peer_pct'])} "
                f"({h['peer_numerator']}/{h['denominator']}) vs externalagent "
                f"{pct(h['agent_pct'])} ({h['agent_numerator']}/{h['denominator']}); McNemar "
                f"b={h['mcnemar_b']}, c={h['mcnemar_c']}, p={h['mcnemar_p']:.3g}")
    return ""


DELTA_KEYS = [
    ("M1 FULL_BLOCK meta-externalagent (news)", ("M1", "all_news", AGENT)),
    ("M1 FULL_BLOCK meta-externalads (news)", ("M1", "all_news", ADS)),
    ("M3 effective block meta-externalagent (news)", ("M3", "all_news", AGENT)),
    ("M5 Meta gap (news)", ("M5", "all_news")),
    ("M6 ads gap (news)", ("M6", "all_news")),
    ("M1 FULL_BLOCK meta-externalagent (control)", ("M1", "control_ex_news", AGENT)),
]


def previous_metrics(reports_dir: str | Path, snapshot: str) -> dict | None:
    cut = snapshot_sort_key(snapshot)
    prev = [f for f in find_metrics_files(reports_dir)
            if snapshot_sort_key(f.stem.removeprefix("metrics_")) < cut]
    return _load(prev[-1]) if prev else None


def render_findings(m: dict, previous: dict | None = None) -> str:
    mn = m.get("min_n", 20)
    L: list[str] = []
    L.append(f"# Findings — snapshot {m['snapshot']} ({nice_date(m['snapshot_date'])})")
    L.append("")
    L.append(f"_Generated automatically from `metrics_{m['snapshot']}.json` at "
             f"{m.get('generated_at', '')}. No number in this file is typed by hand. "
             f"Every share is of domains with a determinate robots.txt outcome; segments with "
             f"n<{mn} are suppressed._")
    L.append("")
    seg = m["segments"].get("all_news", {})
    L.append(f"Panel: {m['panel']['n_news']} news domains (Tier A {m['panel']['n_tier_A']}, "
             f"Tier B {m['panel']['n_tier_B']}) and {m['panel']['n_control']} control domains. "
             f"Determinate news robots.txt at {m['snapshot']}: {seg.get('n_determinate', 0)} "
             f"(indeterminate: {seg.get('n_indeterminate', 0)}).")
    L.append("")
    L.append("## Headline sentences")
    L.append("")
    for s in template_sentences(m) or [f"(No headline sentence has n≥{mn} yet.)"]:
        L.append(f"- {s}")
    L.append("")
    L.append("## The 10 strongest statements")
    L.append("")
    for i, s in enumerate(strongest_statements(m, 10), 1):
        L.append(f"{i}. {s['text']} — n = {s['numerator']}/{s['denominator']} "
                 f"(`{s['metric']}`)")
    L.append("")
    L.append("## Pre-registered hypotheses")
    L.append("")
    L.append("Decision rules were fixed in `docs/methodology.md` before analysis. Null results "
             "are reported as findings.")
    L.append("")
    L.append("| ID | Hypothesis | Outcome | Evidence |")
    L.append("|---|---|---|---|")
    for hid, h in m.get("hypotheses", {}).items():
        L.append(f"| {hid} | {h['text']} | **{h['outcome']}** | {_hyp_evidence(h)} |")
    L.append("")
    # secondary weighted share
    w = _get(m, "M1_weighted", "all_news", AGENT)
    if w and w.get("share_pct") is not None and not w.get("suppressed"):
        L.append(f"_Secondary (size-weighted, weight = 1/log10(Tranco rank + 10); a traffic "
                 f"proxy only): {pct(w['share_pct'])} of news sites (n={w['n']}) FULL_BLOCK "
                 f"`{AGENT}`._")
        L.append("")
    # benchmarks
    if m.get("benchmarks"):
        L.append("## Sanity benchmarks (SPEC §10.2)")
        L.append("")
        L.append("| Benchmark | Ours | Reference | Diff (pp) | Status |")
        L.append("|---|---|---|---|---|")
        for b in m["benchmarks"]:
            ours = (f"{pct(b['our_pct'])} (n={b['n']})" if b.get("our_pct") is not None
                    else f"n={b.get('n', 0)}")
            diff = f"{b['diff_pp']:+.1f}" if b.get("diff_pp") is not None else "–"
            L.append(f"| {b['name']} | {ours} | {b['reference_pct']}% | {diff} | "
                     f"{b['status']} |")
        L.append("")
    # delta
    if previous:
        L.append(f"## Change since {previous['snapshot']} "
                 f"({nice_date(previous.get('snapshot_date'))})")
        L.append("")
        L.append("Unpaired comparison of published shares (denominators may differ); see "
                 "M4 for the paired change counts.")
        L.append("")
        L.append(f"| Metric | {previous['snapshot']} | {m['snapshot']} | Change (pp) |")
        L.append("|---|---|---|---|")
        for label, path in DELTA_KEYS:
            a, b = _get(previous, *path), _get(m, *path)
            if ok(a, mn) and ok(b, mn):
                L.append(f"| {label} | {pct(a['pct'])} ({frac(a)}) | {pct(b['pct'])} "
                         f"({frac(b)}) | {b['pct'] - a['pct']:+.1f} |")
        L.append("")
    L.append("## What this does not show")
    L.append("")
    L.append("- **robots.txt is voluntary.** A block in robots.txt is a request, not an "
             "enforcement mechanism. Meta says `meta-externalfetcher` and `facebookexternalhit` "
             "may bypass robots.txt in some cases. We measure what sites ask for, not what "
             "crawlers do.")
    L.append("- **Signals are proxies.** Domain verification, the Meta Pixel, Audience Network "
             "lines in ads.txt and social links are public signals of Meta business-tool use. "
             "They do not show that a site has any particular agreement with Meta, and their "
             "absence does not show the opposite (verification by file upload is invisible "
             "to us).")
    L.append("- **Wayback coverage gaps.** Baselines come from Internet Archive captures. Not "
             "every site was captured in every window; before/after comparisons use only "
             "domains with both endpoints (paired design), and change dates are bracketed by "
             "capture times.")
    L.append("- **One fetch location.** Live fetches ran from US data-centre runners; sites "
             "may serve different robots.txt by region or to different clients.")
    L.append("- **No legal interpretation.** Nothing here says whether any site is or is not "
             "covered by Meta's terms or what Meta does with crawled content.")
    L.append("")
    text = "\n".join(L)
    low = text.lower()
    for bad in FORBIDDEN_PHRASES:
        if bad in low:
            raise ValueError(f"findings text violates language rules: {bad!r}")
    return text


def write_findings(metrics: dict | str | Path, out_path: str | Path = "reports/findings.md",
                   reports_dir: str | Path | None = None,
                   previous: dict | str | Path | None = None) -> Path:
    """Render findings.md. If `previous` is None, the latest earlier metrics_*.json in
    `reports_dir` (default: the output's folder) is used for the delta section."""
    m = _load(metrics)
    out = Path(out_path)
    if previous is None:
        previous = previous_metrics(reports_dir or out.parent, m["snapshot"])
    elif not isinstance(previous, dict):
        previous = _load(previous)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_findings(m, previous), encoding="utf-8")
    return out
