"""Generate docs/methodology.md from a static template + config (+ panel/metrics data if present).

The pre-registration section (PREREGISTRATION) is static text fixed before any data was
analysed. It must never be built from metric values.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcs.analyze.common import find_metrics_files, load_bots, load_study

PREREGISTRATION = """\
## 2. Pre-registration (fixed 19 Oct 2026, before the T2 live snapshot of 20 Oct 2026)

This section was written before any T2 data existed and is not edited after seeing the data.
The decision rules below are applied mechanically by `mcs.analyze.metrics.evaluate_hypotheses`.
A hypothesis is reported as **supported**, **not supported**, or **insufficient data**
(denominator below 20, or for H6 fewer than 10 changed domains).

**Null results are still stories.** Every hypothesis is reported whichever way it falls. A
"not supported" outcome is a finding, published with the same prominence as a "supported" one,
and the rules are not changed after the data are seen.

| ID | Hypothesis | Pre-registered decision rule |
|---|---|---|
| H1 | Most news publishers (>50%) still do NOT block `meta-externalagent` days before 30 Oct. | Supported if the share of determinate news domains that do **not** `FULL_BLOCK` `meta-externalagent` is > 50%. |
| H2 | Few publishers (<5%) changed their Meta rules after 15 Oct. | Paired news domains (determinate at both T1 and the current snapshot; T0 if T1 is unavailable). Supported if the share whose verdict or naming changed for any `META_TOKENS` or `LEGACY_META` bot is < 5%. |
| H3 | `meta-externalads` is blocked far less often than `meta-externalagent` (the "ads gap"). | Supported if the `FULL_BLOCK` share for `meta-externalads` is lower than for `meta-externalagent` among news domains **and** either the two Wilson 95% CIs do not overlap or an exact McNemar test on the same domains gives p < 0.05 in that direction. |
| H4 | Publishers block OpenAI/Anthropic/Google training bots more often than Meta's (the "Meta gap"). | Supported if the share of news domains that `FULL_BLOCK` at least one of `gptbot`, `claudebot`, `google-extended` exceeds the `meta-externalagent` `FULL_BLOCK` share **and** the exact McNemar test on the same domains gives p < 0.05. |
| H5 | A large share of Meta-linked publishers are exposed. | "Large" means > 50%. Among news domains with E1, E2 or E2b signals, supported if > 50% do not `FULL_BLOCK` `meta-externalagent`. |
| H6 | Changes cluster by owner group or platform template. | Among news domains that changed any Meta rule (same comparison as H2), supported if > 50% share a template cluster (identical normalised robots.txt) or a known owner group with at least one other changed domain. Needs ≥ 10 changed domains. |

**Analysis plan.** Primary shares are unweighted, with Wilson 95% intervals; denominators are
domains with a determinate robots.txt outcome. News vs control differences use the Newcombe
hybrid score interval; paired before/after comparisons use the exact McNemar test with the
discordant counts b and c reported. A size-weighted share (weight = 1/log10(Tranco rank + 10))
is secondary and labelled as a traffic proxy. Segment metrics with a denominator below 20 are
suppressed ("n<20"). Every published number carries its n.
"""

RFC_TABLE = """\
| `fetch_status` | Condition | Treatment in headline metrics |
|---|---|---|
| `OK` | 2xx, text or empty, parseable | Parsed |
| `OK_EMPTY` | 2xx, empty body | Allow-all |
| `UNAVAILABLE_4XX` | 400–499 except 429, after redirects | Allow-all (RFC 9309 §2.3.1.3); counted separately |
| `RATE_LIMITED_429` | 429 after retries | Indeterminate (Google treats 429 like 5xx) |
| `UNREACHABLE_5XX` | 500–599 after retries | RFC 9309 says assume full disallow; we treat it as **indeterminate** and report the count |
| `INVALID_HTML` / soft-404 | 2xx but an HTML page | Soft-404 with no rules: allow-all (flagged). Challenge page: indeterminate |
| `NETWORK_ERROR` | DNS/TLS/timeout after retries | Indeterminate |
| `INDETERMINATE_BLOCKED` | Bot-challenge page served to our client | Indeterminate |
"""

VERDICT_TABLE = """\
| Verdict | Definition |
|---|---|
| `FULL_BLOCK` | The bot is named (exact or versioned/prefix token) and **all** probe URLs are disallowed for it. Called an "explicit block" in copy. |
| `PARTIAL_BLOCK` | Named; some but not all probes disallowed. |
| `ALLOWED_EXPLICIT` | Named; no probe disallowed. |
| `WILDCARD_BLOCK` | Not named; the `*` group disallows all probes. |
| `WILDCARD_PARTIAL` | Not named; `*` disallows some probes. |
| `ALLOWED_DEFAULT` | Not named; `*` allows all probes, or there are no rules. |
| `INDETERMINATE` | The robots.txt fetch outcome was indeterminate (table above). |

"Effective block" = `FULL_BLOCK` ∪ `WILDCARD_BLOCK`. Restrictiveness order (least → most):
`ALLOWED_DEFAULT` < `ALLOWED_EXPLICIT` < `WILDCARD_PARTIAL` < `PARTIAL_BLOCK` <
`WILDCARD_BLOCK` < `FULL_BLOCK`.
"""


def _panel_meta(path: Path | None) -> dict:
    if path and path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def render_methodology(metrics: dict | None = None, panel_meta: dict | None = None,
                       config_dir: str | Path | None = None) -> str:
    study = load_study(config_dir)
    bots = load_bots(config_dir)
    ua = study.get("identity", {}).get("user_agent", "")
    rl = study.get("rate_limits", {})
    wb = study.get("wayback", {})
    pm = panel_meta or {}
    L: list[str] = []
    L.append("# Methodology — Meta's crawlers and news publishers' robots.txt")
    L.append("")
    L.append("_This document is generated by `mcs.report.methodology` from a fixed template, "
             "`config/*.yaml` and (where available) the frozen panel metadata. Section 2 is "
             "the pre-registration and does not depend on any measured value._")
    L.append("")
    L.append("## 1. What we measured")
    L.append("")
    L.append("For news publishers and a general top-sites control group we read each site's "
             "robots.txt and recorded, for every crawler token below, whether the file blocks "
             "it. We compare Meta's five documented crawlers with other AI and search "
             "crawlers, track changes around Meta's updated Commercial Terms (effective 30 Oct "
             "2026), and count publishers that show public signals of Meta business-tool use "
             "but do not block Meta's crawlers in robots.txt.")
    L.append("")
    L.append("Crawler tokens evaluated (`config/bots.yaml`):")
    L.append("")
    for k in ("META_TOKENS", "LEGACY_META", "PEER_AI_TRAINING", "PEER_AI_SEARCH",
              "CLASSIC_SEARCH"):
        L.append(f"- **{k}**: " + ", ".join(f"`{b}`" for b in bots.get(k, [])))
    L.append("")
    L.append("Meta's documentation describes `meta-externalads` as the crawler for "
             "\"improving advertising and other business-related products and services\". We "
             "call it *the crawler Meta describes for advertising and business products* and "
             "make no claim about how Meta actually uses it.")
    L.append("")
    L.append(PREREGISTRATION)
    L.append("## 3. Sample frame (panel)")
    L.append("")
    L.append("- **Tier A — major news brands:** Press Gazette's monthly Similarweb rankings "
             "(top 50 US, top 50 UK, top 50 English-language worldwide; world's biggest news "
             "websites in any language). The UK list publishes brand names rather than "
             "domains; a curated brand→domain map is used and published "
             "(`data/panel/pg_uk_brand_map.csv`). Aggregators and portals are excluded "
             "(`panel_exclusions.csv`).")
    L.append("- **Tier B — regional and local news:** Wikidata (newspapers, online newspapers "
             "and news websites in the US and UK with an official website and no dissolution "
             "date), supplemented by chain ownership lists to fill `owner_group`. The exact "
             "SPARQL query and run time are in `data/panel/wikidata_query.sparql`. Stratified "
             f"sampling by country × owner group, seed {study.get('study', {}).get('random_seed')}"
             ".")
    L.append("- **Control:** the Tranco top-10k list nearest to 19 Oct 2026, reduced to "
             "registered domains. Domains also in the news panel are flagged and excluded "
             "from news-vs-control comparisons. Wayback baselines cover a random "
             f"{wb.get('control_sample', 2000)}-domain subsample of the control.")
    L.append("- All URLs are reduced to registered domains with `tldextract` and a pinned "
             "Public Suffix List. The panel was frozen before analysis "
             f"(frame version {study.get('study', {}).get('frame_version', 'n/a')}).")
    if pm:
        L.append("")
        L.append("Frozen panel metadata (`data/panel/panel_meta.json`):")
        L.append("")
        for k, v in pm.items():
            L.append(f"- `{k}`: {json.dumps(v) if isinstance(v, (dict, list)) else v}")
    if metrics:
        p = metrics.get("panel", {})
        L.append("")
        L.append(f"Panel size used in `metrics_{metrics['snapshot']}.json`: "
                 f"{p.get('n_news')} news domains (Tier A {p.get('n_tier_A')}, Tier B "
                 f"{p.get('n_tier_B')}), {p.get('n_control')} control domains "
                 f"({p.get('n_control_is_news')} of which are also news domains).")
    L.append("")
    L.append("## 4. How the data were fetched")
    L.append("")
    L.append("All robots.txt and ads.txt files were fetched with **our own direct HTTP client** "
             "(Python `httpx`), run from **GitHub Actions runners (Microsoft Azure data "
             "centres in the US)**. It exposes the upstream HTTP status and the final URL after "
             "redirects, which RFC 9309 semantics require. **No third-party scraping API was "
             "used — in particular, the data were not collected through HasData's Web Scraping "
             "API.** HasData publishes the study; the \"Data: HasData\" credit on charts refers "
             "to the publisher, not to the collection method. Challenge pages were not "
             "retried through any proxy service; they are recorded as "
             "`INDETERMINATE_BLOCKED`.")
    L.append("")
    L.append(f"- **User-Agent:** `{ua}`. The repository README is the bot information page "
             "(purpose, contact via GitHub issues, opt-out).")
    L.append(f"- **Politeness:** at most {rl.get('per_host_concurrency', 1)} concurrent request "
             f"per host, at least {rl.get('per_host_min_interval_s', 2.0)} s between requests "
             f"to the same host, global concurrency ≤ {rl.get('global_concurrency', 25)}; "
             f"timeouts {rl.get('connect_timeout_s', 10)} s connect / "
             f"{rl.get('read_timeout_s', 20)} s read; at most {rl.get('max_retries', 2)} "
             "retries (network errors, 5xx, 429 only, honouring `Retry-After`); no cookies, "
             "no logins, no JavaScript for robots.txt/ads.txt.")
    L.append(f"- **robots.txt:** `https://{{canonical host}}/robots.txt` after following up to "
             f"{rl.get('max_redirects', 5)} redirects from the homepage; the apex host's file "
             "is also fetched for QA. Bodies are truncated at "
             f"{rl.get('robots_max_bytes', 512000)} bytes (500 KiB, the RFC 9309 parsing "
             "limit). Every body is stored with its SHA-256 and a metadata sidecar.")
    L.append("- **Homepages (news panel, once):** only if our own robots.txt rules allow `/`; "
             "rendered with **headless Chromium (Playwright)** and also fetched as raw HTML, "
             "and both are scanned. If `/` is disallowed for us, we use the latest Wayback "
             "capture within 30 days instead.")
    L.append("- **DNS:** public TXT records of the registered domain. **GTM:** the public "
             "`gtm.js` container for any GTM ID on the homepage.")
    L.append("- **Baselines and history:** Internet Archive Wayback Machine CDX queries and "
             "raw `id_` captures (original bytes, no Wayback banner), at most "
             f"{1 / float(wb.get('min_interval_s', 1.0)):.0f} request/second, single "
             f"connection, back-off from {wb.get('backoff_start_s', 30)} s doubling to "
             f"{wb.get('backoff_max_s', 600)} s, cached on disk.")
    L.append("- **Snapshots:** T0 = latest capture in [1 Sep, 1 Oct 2026 23:59:59 UTC]; T1 = "
             "latest capture in [2 Oct, 14 Oct 2026 23:59:59 UTC] (T0 carried forward and "
             "flagged if none); T2 = live, 20 Oct 2026 from 06:00 UTC; daily live snapshots "
             "to 20 Nov 2026 (extended from 6 Nov); T3 = 29 Oct; T4 = 6 Nov. All times UTC.")
    L.append("")
    L.append("### Fetch-outcome treatment (RFC 9309)")
    L.append("")
    L.append(RFC_TABLE)
    L.append("Denominators for headline metrics contain only determinate outcomes; the number "
             "of indeterminate domains is always published alongside.")
    if metrics and metrics.get("fetch_status_counts"):
        L.append("")
        L.append(f"Fetch outcomes at {metrics['snapshot']}:")
        L.append("")
        for seg, counts in metrics["fetch_status_counts"].items():
            L.append(f"- {seg}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    L.append("")
    L.append("## 5. Parsing rules")
    L.append("")
    L.append("- Our own RFC 9309 group extractor; every verdict is cross-checked with Protego "
             "and disagreements are reviewed by hand.")
    L.append("- UTF-8 decoding with latin-1 fallback; BOM stripped; CRLF/CR/LF accepted; "
             "comments stripped; field names case-insensitive; a missing space after the colon "
             "is tolerated.")
    L.append("- Consecutive `user-agent` lines share a group; groups naming the same token are "
             "merged (RFC 9309 §2.2.1). Only `allow`/`disallow` are evaluated; an empty "
             "`Disallow:` means no restriction.")
    L.append("- Path matching supports `*` and `$`; the longest match wins, and `allow` wins a "
             "tie (RFC 9309 §2.2.2).")
    L.append("- **Token matching:** exact (`meta-externalagent`) and versioned/prefix "
             "(`meta-externalagent/1.1`, `meta-externalagent*`) count as *named*. Non-standard "
             "spellings (`Meta-External*`, `MetaExternalAgent`, `facebook*`) are recorded as "
             "`nonstandard`, are **not** counted as named, and are reported as a "
             "misconfiguration sub-finding. The `*` group applies only when no group names the "
             "bot.")
    L.append("- **Probe URLs:** `/`, `/news/` and up to three article URLs sampled from the T2 "
             "homepage (a synthetic `/2026/10/example-article-slug/` if none is found). The "
             "same probes are reused for every snapshot of a domain.")
    L.append("- **Cloudflare-managed blocks** (`# BEGIN Cloudflare Managed content` … `# END`) "
             "and `Content-Signal:` lines are detected; generator fingerprints (Yoast, Rank "
             "Math, WordPress VIP, Arc XP, Brightspot …) are recorded.")
    L.append("")
    L.append("## 6. Verdict definitions")
    L.append("")
    L.append(VERDICT_TABLE)
    L.append("## 7. Changes, attribution and timeline")
    L.append("")
    L.append("- Comparisons over time use only domains with a determinate verdict at both "
             "endpoints (paired design); the paired n is always stated.")
    L.append("- **Attribution:** a change whose named Meta rule sits inside a Cloudflare-managed "
             "block in every version that names it is labelled `cf_managed`; a change "
             "involving a named rule outside such a block is `authored`; a change only to the "
             "`*` group is `unknown`. Identical same-day changes inside Cloudflare blocks "
             "across unrelated domains are treated as a Cloudflare default change, never as "
             "publisher reaction.")
    L.append("- **Template clusters:** domains whose normalised robots.txt (comments and "
             "`Sitemap:` lines removed) hashes identically form a cluster; changes are reported "
             "per domain and per cluster, joined with owner group.")
    L.append("- **Timeline (M11):** a Meta-related change is a robots.txt version whose verdict "
             "tuple over `META_TOKENS` + `LEGACY_META` differs from the previous version. It is "
             "dated at the first capture of the new version; the previous capture bounds the "
             "true change time, and the median bracket width is published. Event markers are "
             "labelled \"per press reports\".")
    L.append("")
    L.append("## 8. Signals of Meta business-tool use")
    L.append("")
    L.append("| Level | Signal |")
    L.append("|---|---|")
    L.append("| E1 (strong) | `facebook-domain-verification` meta tag on the homepage or DNS TXT "
             "record on the apex. A lower bound: verification by file upload is not "
             "discoverable. |")
    L.append("| E2 (medium) | Meta Pixel on the homepage (`fbevents.js`, `fbq('init', …)` or "
             "`facebook.com/tr?id=`), raw or rendered HTML. |")
    L.append("| E2b (medium) | A `facebook.com` line (Meta Audience Network) in ads.txt. |")
    L.append("| E2-GTM (weak) | No direct pixel, but the public GTM container references the "
             "pixel. |")
    L.append("| E3 (weak) | Links to Facebook pages / Instagram profiles (share, dialog, plugin, "
             "login, policy, help and event URLs excluded; group links flagged separately), "
             "`fb:pages` or `fb:app_id` meta tags. |")
    L.append("")
    L.append("Shares are reported cumulatively (E1; E1∪E2∪E2b; …∪E2-GTM; any). These are "
             "public proxies only; they never show that a site is covered by Meta's terms.")
    L.append("")
    L.append("## 9. Statistics")
    L.append("")
    L.append("Wilson 95% intervals for proportions; Newcombe hybrid score interval (method 10) "
             "for news-vs-control differences; exact McNemar test (two-sided binomial on the "
             "discordant pairs b, c) for paired changes; size-weighted shares (weight = "
             "1/log10(Tranco rank + 10), missing rank treated as 1,000,000) as a secondary, "
             "clearly labelled proxy. Segments with n < 20 are suppressed.")
    L.append("")
    L.append("Sanity benchmarks: control top-1,000 naming of `meta-externalagent` vs "
             "knownagents.com (~19%); control top-5,000 `FULL_BLOCK` vs the 7 Sep 2026 "
             "Tranco-5k census (17.2%); Tier A US peer training-crawler blocking vs Axios's "
             "102 publishers (~42%, directional). Deviations > 10 pp are investigated in "
             "`reports/qa_log.md` before data freeze.")
    if metrics and metrics.get("benchmarks"):
        L.append("")
        for b in metrics["benchmarks"]:
            our = f"{b['our_pct']:.1f}%" if b.get("our_pct") is not None else "n/a"
            L.append(f"- {b['id']} {b['name']}: ours {our} (n={b.get('n')}), reference "
                     f"{b['reference_pct']}% → {b['status']}")
    L.append("")
    L.append("## 10. Limitations")
    L.append("")
    L.append("- robots.txt is a voluntary convention. Blocking in robots.txt is a request; Meta "
             "says `meta-externalfetcher` and `facebookexternalhit` may bypass it in some "
             "cases. We do not observe crawler behaviour.")
    L.append("- One fetch location (US data centres). Sites may serve different content by "
             "region, client or IP reputation; bot-challenge pages are counted as "
             "indeterminate.")
    L.append("- Wayback coverage is incomplete, especially for regional sites; baselines may "
             "be days old at the cutoff, and change dates are bracketed by capture times.")
    L.append("- Signals of Meta business-tool use are proxies (E1 is a lower bound; E3 is "
             "weak).")
    L.append("- Probe URLs approximate a site's content; a site that blocks only some sections "
             "is classed as a partial block.")
    L.append("- Panel sources (Press Gazette, Wikidata, Tranco) have their own coverage "
             "biases.")
    L.append("")
    L.append("## 11. Ethics")
    L.append("")
    L.append("- Only public, unauthenticated resources: robots.txt, ads.txt, homepages, public "
             "DNS, public GTM JavaScript and the Wayback Machine.")
    L.append("- We honour robots.txt for our own user-agent on homepage fetches. We never send "
             "Meta's, OpenAI's or any third party's crawler user-agent, never test whether "
             "firewalls block Meta's crawler, and never bypass paywalls, logins or forms.")
    L.append("- The public domain-level table covers Tier A (large brands) only; regional "
             "outlets appear as aggregates and owner groups unless the publisher decides "
             "otherwise.")
    L.append("- No legal conclusions are drawn.")
    L.append("")
    L.append("## 12. Sources for context")
    L.append("")
    L.append("- Meta, \"Web crawlers\" documentation, developers.facebook.com "
             "(`/documentation/sharing/webmasters/web-crawlers`).")
    L.append("- Nieman Lab report on Meta's updated Commercial Terms, 15 Oct 2026.")
    L.append("- knownagents.com crawler statistics (top 1,000 websites).")
    L.append("- dev.to census of the Tranco top 5,000, 7 Sep 2026.")
    L.append("- Axios analysis of 102 US publishers, 17 Oct 2026.")
    L.append("")
    return "\n".join(L)


def write_methodology(out_path: str | Path = "docs/methodology.md",
                      metrics: dict | str | Path | None = None,
                      reports_dir: str | Path | None = "reports",
                      panel_meta_path: str | Path | None = "data/panel/panel_meta.json",
                      config_dir: str | Path | None = None) -> Path:
    """Write docs/methodology.md. If `metrics` is None the latest reports/metrics_*.json (if
    any) supplies descriptive counts; the pre-registration text never changes."""
    m = None
    if isinstance(metrics, dict):
        m = metrics
    elif metrics is not None:
        m = json.loads(Path(metrics).read_text(encoding="utf-8"))
    elif reports_dir is not None:
        files = find_metrics_files(reports_dir)
        m = json.loads(files[-1].read_text(encoding="utf-8")) if files else None
    pm = _panel_meta(Path(panel_meta_path) if panel_meta_path else None)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = render_methodology(m, pm, config_dir)
    dev = out.parent / "DEVIATIONS.md"
    if dev.exists():
        body = dev.read_text(encoding="utf-8").split("\n", 1)[-1].strip()
        text += ("\n\n## 13. Deviations from the study plan\n\n"
                 "Decided with the study owner during fieldwork; recorded as they happened.\n\n"
                 + body + "\n")
    text += ANALYSIS_DECISIONS
    out.write_text(text, encoding="utf-8")
    return out


ANALYSIS_DECISIONS = """
## 14. Data-quality decisions made during QA (before data freeze)

These were made after manual verification (see `reports/qa_log.md`) and before the data freeze.
None of them changes a pre-registered hypothesis or its decision rule.

1. **Archived error pages are not robots.txt files.** A Wayback capture that is an HTML page or a
   401/403 response shows the Internet Archive's crawler being turned away, not the site's rules.
   Such captures are treated as indeterminate (`WAYBACK_HTML` / `WAYBACK_BLOCKED`). Baseline
   selection takes the latest *valid* capture in the window. Two false "changes" found in
   manual QA (washingtonpost.com, thetimes.com) were caused by such captures.
2. **Bot-challenge detection** was extended (e.g. "Verifying your device", "Checking your
   browser") and applied to every stored body at parse time.
3. **Carried-forward baselines are excluded from "after 15 Oct" comparisons.** Where a site had no
   Wayback capture between 2 and 14 Oct, its 1 Oct state is carried forward as T1
   (`t1_carried`), as the plan specifies. A change against a carried baseline may predate the
   15 Oct story, so carried rows are excluded from all T1→later change counts (M4, H2). The
   change against the 1 Oct baseline is still reported separately (T0→T2).
4. **Archive-restricted domains.** Some domains (e.g. theguardian.com) cannot be queried in the
   Wayback CDX API (HTTP 403). They are labelled `WAYBACK_RESTRICTED` and have no baseline.
5. **Persistent fetch failures.** A second fetch pass with a longer timeout was made for transient
   failures. Sites that keep refusing data-centre traffic or serve bot challenges stay
   indeterminate; we do not route around them.
"""
