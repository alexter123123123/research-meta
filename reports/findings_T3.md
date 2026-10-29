# Findings — snapshot T3 (29 Oct 2026)

_Generated automatically from `metrics_T3.json` at 2026-10-29T09:06:12+00:00. No number in this file is typed by hand. Every share is of domains with a determinate robots.txt outcome; segments with n<20 are suppressed._

Panel: 1496 news domains (Tier A 96, Tier B 1400) and 10000 control domains. Determinate news robots.txt at T3: 1388 (indeterminate: 108).

## Headline sentences

- 44.1% of 1388 news sites (95% CI 41.5–46.7%) explicitly block `meta-externalagent` in robots.txt as of 29 Oct 2026, versus 8.9% of the top-10k general sites (n=7122).
- 24 of 131 news sites with archived robots.txt changed any Meta crawler rule between 14 Oct and 29 Oct 2026; 15 were publisher-authored, 8 came via Cloudflare-managed rules; 1 changed only the wildcard (`*`) group, so attribution is unknown.
- Of the 612 news sites that block `meta-externalagent` (the crawler Meta's documentation describes for AI training) in robots.txt, 98.2% (601/612) leave `meta-externalads` — the crawler Meta describes for advertising and business products — unblocked.
- 12.3% of the 685 news sites that block at least one of OpenAI's, Anthropic's, Google's or Common Crawl's training crawlers in robots.txt do not block Meta's (`meta-externalagent`) (84/685).
- 40.2% of news sites (602/1496) show at least one public signal of Meta business-tool use (domain verification, Meta Pixel or Audience Network); 47.2% of those (274/581) do not block `meta-externalagent` in robots.txt.
- 0 of 1388 news sites block `facebookexternalhit` in robots.txt, which can break link previews on Facebook and Instagram.
- Meta's crawler documentation first lists `meta-externalads` in an archived capture dated 27 Jun 2025 (the latest earlier capture without it is dated 21 Jun 2025).

## The 10 strongest statements

1. Ads gap: 98.2% (601/612; 95% CI 96.8–99.0%) of news sites that FULL_BLOCK `meta-externalagent` in robots.txt do not block `meta-externalads`, the crawler Meta describes for advertising and business products. — n = 601/612 (`M6.all_news`)
2. Among major (Tier A) news brands that FULL_BLOCK `meta-externalagent` in robots.txt, 100.0% (50/50; 95% CI 92.9–100.0%) do not block `meta-externalads`, the crawler Meta describes for advertising and business products. — n = 50/50 (`M6.tier_A`)
3. 44.1% (612/1388; 95% CI 41.5–46.7%) of news sites FULL_BLOCK `meta-externalagent` in robots.txt. — n = 612/1388 (`M1.all_news.meta-externalagent`)
4. News sites block `meta-externalagent` in robots.txt 35.2 percentage points more often than top-10k general sites (44.1%, 612/1388 vs 8.9%, 631/7122; difference 95% CI 32.6 to 37.9 pp, Newcombe). — n = 612/1388 (`M10.M1.meta-externalagent`)
5. Meta gap: 12.3% (84/685; 95% CI 10.0–14.9%) of news sites that FULL_BLOCK at least one of gptbot, claudebot, google-extended or ccbot do not FULL_BLOCK `meta-externalagent`. — n = 84/685 (`M5.all_news`)
6. 47.2% (274/581; 95% CI 43.1–51.2%) of news sites with signals of Meta business-tool use (E1/E2/E2b) do not block `meta-externalagent` in robots.txt. — n = 274/581 (`M8.all_news.meta-externalagent.E1_E2_E2b.of_linked`)
7. 100.0% (581/581; 95% CI 99.3–100.0%) of news sites with signals of Meta business-tool use (E1/E2/E2b) do not block `meta-externalads`, the crawler Meta describes for advertising and business products. — n = 581/581 (`M8.all_news.meta-externalads.E1_E2_E2b.of_linked`)
8. 18.3% (24/131) of news sites with robots.txt at both T1 and T3 changed any Meta crawler rule (15 publisher-authored, 8 via Cloudflare-managed rules). — n = 24/131 (`M4.T1->T3.all_news.any_meta_change`)
9. 9.2% (12/131) of paired news sites became more restrictive toward `meta-externalagent` between T1 and T3 (newly FULL_BLOCK: 12, stopped: 7; exact McNemar p=0.359). — n = 12/131 (`M4.T1->T3.all_news.by_bot.meta-externalagent`)
10. 0.8% (11/1388; 95% CI 0.4–1.4%) of news sites FULL_BLOCK `meta-externalads`, the crawler Meta describes for advertising and business products, in robots.txt. — n = 11/1388 (`M1.all_news.meta-externalads`)

## Pre-registered hypotheses

Decision rules were fixed in `docs/methodology.md` before analysis. Null results are reported as findings.

| ID | Hypothesis | Outcome | Evidence |
|---|---|---|---|
| H1 | Most news publishers (>50%) still do NOT block meta-externalagent days before 30 Oct. | **supported** | 55.9% (776/1388), 95% CI 53.3–58.5% |
| H2 | Few publishers (<5%) changed their Meta rules after 15 Oct. | **not supported** | 18.3% (24/131), 95% CI 12.6–25.8% |
| H3 | meta-externalads is blocked far less often than meta-externalagent (the ads gap). | **supported** | externalagent 44.1% (612/1388) vs externalads 0.8% (11/1388); McNemar b=601, c=0, p=2.41e-181 |
| H4 | Publishers block OpenAI/Anthropic/Google training bots more often than Meta's (the Meta gap). | **supported** | any of gptbot/claudebot/google-extended 48.6% (674/1388) vs externalagent 44.1% (612/1388); McNemar b=76, c=14, p=1.78e-11 |
| H5 | A large share (>50%) of Meta-linked publishers are exposed. | **not supported** | 47.2% (274/581), 95% CI 43.1–51.2% |
| H6 | Changes cluster by owner group or platform template (chain-level decisions). | **not supported** | 20.8% (5/24), 95% CI 9.2–40.5% |

_Secondary (size-weighted, weight = 1/log10(Tranco rank + 10); a traffic proxy only): 45.2% of news sites (n=1388) FULL_BLOCK `meta-externalagent`._

## Sanity benchmarks (SPEC §10.2)

| Benchmark | Ours | Reference | Diff (pp) | Status |
|---|---|---|---|---|
| Control top-1,000: any rule naming meta-externalagent (M2) vs knownagents.com | 13.7% (n=685) | 19.0% | -5.3 | pass |
| Control top-5,000: meta-externalagent FULL_BLOCK (M1) vs 7 Sep 2026 Tranco-5k census | 9.7% (n=3526) | 17.2% | -7.5 | pass |
| Tier A US: FULL_BLOCK of any peer AI-training crawler vs Axios 102 publishers (directional only) | 83.8% (n=37) | 42.0% | +41.8 | flag |

## Change since T2 (20 Oct 2026)

Unpaired comparison of published shares (denominators may differ); see M4 for the paired change counts.

| Metric | T2 | T3 | Change (pp) |
|---|---|---|---|
| M1 FULL_BLOCK meta-externalagent (news) | 40.5% (561/1384) | 44.1% (612/1388) | +3.6 |
| M1 FULL_BLOCK meta-externalads (news) | 0.8% (11/1384) | 0.8% (11/1388) | -0.0 |
| M3 effective block meta-externalagent (news) | 41.8% (578/1384) | 45.2% (628/1388) | +3.5 |
| M5 Meta gap (news) | 15.2% (99/650) | 12.3% (84/685) | -3.0 |
| M6 ads gap (news) | 98.0% (550/561) | 98.2% (601/612) | +0.2 |
| M1 FULL_BLOCK meta-externalagent (control) | 6.9% (498/7169) | 8.9% (631/7122) | +1.9 |

## What this does not show

- **robots.txt is voluntary.** A block in robots.txt is a request, not an enforcement mechanism. Meta says `meta-externalfetcher` and `facebookexternalhit` may bypass robots.txt in some cases. We measure what sites ask for, not what crawlers do.
- **Signals are proxies.** Domain verification, the Meta Pixel, Audience Network lines in ads.txt and social links are public signals of Meta business-tool use. They do not show that a site has any particular agreement with Meta, and their absence does not show the opposite (verification by file upload is invisible to us).
- **Wayback coverage gaps.** Baselines come from Internet Archive captures. Not every site was captured in every window; before/after comparisons use only domains with both endpoints (paired design), and change dates are bracketed by capture times.
- **One fetch location.** Live fetches ran from US data-centre runners; sites may serve different robots.txt by region or to different clients.
- **No legal interpretation.** Nothing here says whether any site is or is not covered by Meta's terms or what Meta does with crawled content.
