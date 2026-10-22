# Findings — snapshot T2 (20 Oct 2026)

_Generated automatically from `metrics_T2.json` at 2026-10-22T15:14:53+00:00. No number in this file is typed by hand. Every share is of domains with a determinate robots.txt outcome; segments with n<20 are suppressed._

Panel: 1496 news domains (Tier A 96, Tier B 1400) and 10000 control domains. Determinate news robots.txt at T2: 1384 (indeterminate: 112).

## Headline sentences

- 40.5% of 1384 news sites (95% CI 38.0–43.1%) explicitly block `meta-externalagent` in robots.txt as of 20 Oct 2026, versus 6.9% of the top-10k general sites (n=7169).
- 15 of 131 news sites with archived robots.txt changed any Meta crawler rule between 14 Oct and 20 Oct 2026; 12 were publisher-authored, 2 came via Cloudflare-managed rules; 1 changed only the wildcard (`*`) group, so attribution is unknown.
- Of the 561 news sites that block `meta-externalagent` (the crawler Meta's documentation describes for AI training) in robots.txt, 98.0% (550/561) leave `meta-externalads` — the crawler Meta describes for advertising and business products — unblocked.
- 15.2% of the 650 news sites that block at least one of OpenAI's, Anthropic's, Google's or Common Crawl's training crawlers in robots.txt do not block Meta's (`meta-externalagent`) (99/650).
- 40.2% of news sites (602/1496) show at least one public signal of Meta business-tool use (domain verification, Meta Pixel or Audience Network); 50.2% of those (294/586) do not block `meta-externalagent` in robots.txt.
- 0 of 1384 news sites block `facebookexternalhit` in robots.txt, which can break link previews on Facebook and Instagram.
- Meta's crawler documentation first lists `meta-externalads` in an archived capture dated 27 Jun 2025 (the latest earlier capture without it is dated 21 Jun 2025).

## The 10 strongest statements

1. Ads gap: 98.0% (550/561; 95% CI 96.5–98.9%) of news sites that FULL_BLOCK `meta-externalagent` in robots.txt do not block `meta-externalads`, the crawler Meta describes for advertising and business products. — n = 550/561 (`M6.all_news`)
2. Among major (Tier A) news brands that FULL_BLOCK `meta-externalagent` in robots.txt, 100.0% (48/48; 95% CI 92.6–100.0%) do not block `meta-externalads`, the crawler Meta describes for advertising and business products. — n = 48/48 (`M6.tier_A`)
3. 40.5% (561/1384; 95% CI 38.0–43.1%) of news sites FULL_BLOCK `meta-externalagent` in robots.txt. — n = 561/1384 (`M1.all_news.meta-externalagent`)
4. News sites block `meta-externalagent` in robots.txt 33.6 percentage points more often than top-10k general sites (40.5%, 561/1384 vs 6.9%, 498/7169; difference 95% CI 31.0 to 36.3 pp, Newcombe). — n = 561/1384 (`M10.M1.meta-externalagent`)
5. Meta gap: 15.2% (99/650; 95% CI 12.7–18.2%) of news sites that FULL_BLOCK at least one of gptbot, claudebot, google-extended or ccbot do not FULL_BLOCK `meta-externalagent`. — n = 99/650 (`M5.all_news`)
6. 50.2% (294/586; 95% CI 46.1–54.2%) of news sites with signals of Meta business-tool use (E1/E2/E2b) do not block `meta-externalagent` in robots.txt. — n = 294/586 (`M8.all_news.meta-externalagent.E1_E2_E2b.of_linked`)
7. 100.0% (586/586; 95% CI 99.3–100.0%) of news sites with signals of Meta business-tool use (E1/E2/E2b) do not block `meta-externalads`, the crawler Meta describes for advertising and business products. — n = 586/586 (`M8.all_news.meta-externalads.E1_E2_E2b.of_linked`)
8. 11.5% (15/131) of news sites with robots.txt at both T1 and T2 changed any Meta crawler rule (12 publisher-authored, 2 via Cloudflare-managed rules). — n = 15/131 (`M4.T1->T2.all_news.any_meta_change`)
9. 3.1% (4/131) of paired news sites became more restrictive toward `meta-externalagent` between T1 and T2 (newly FULL_BLOCK: 4, stopped: 7; exact McNemar p=0.549). — n = 4/131 (`M4.T1->T2.all_news.by_bot.meta-externalagent`)
10. 0.8% (11/1384; 95% CI 0.4–1.4%) of news sites FULL_BLOCK `meta-externalads`, the crawler Meta describes for advertising and business products, in robots.txt. — n = 11/1384 (`M1.all_news.meta-externalads`)

## Pre-registered hypotheses

Decision rules were fixed in `docs/methodology.md` before analysis. Null results are reported as findings.

| ID | Hypothesis | Outcome | Evidence |
|---|---|---|---|
| H1 | Most news publishers (>50%) still do NOT block meta-externalagent days before 30 Oct. | **supported** | 59.5% (823/1384), 95% CI 56.9–62.0% |
| H2 | Few publishers (<5%) changed their Meta rules after 15 Oct. | **not supported** | 11.5% (15/131), 95% CI 7.1–18.0% |
| H3 | meta-externalads is blocked far less often than meta-externalagent (the ads gap). | **supported** | externalagent 40.5% (561/1384) vs externalads 0.8% (11/1384); McNemar b=550, c=0, p=5.43e-166 |
| H4 | Publishers block OpenAI/Anthropic/Google training bots more often than Meta's (the Meta gap). | **supported** | any of gptbot/claudebot/google-extended 46.2% (639/1384) vs externalagent 40.5% (561/1384); McNemar b=91, c=13, p=1.4e-15 |
| H5 | A large share (>50%) of Meta-linked publishers are exposed. | **supported** | 50.2% (294/586), 95% CI 46.1–54.2% |
| H6 | Changes cluster by owner group or platform template (chain-level decisions). | **not supported** | 20.0% (3/15), 95% CI 7.0–45.2% |

_Secondary (size-weighted, weight = 1/log10(Tranco rank + 10); a traffic proxy only): 41.8% of news sites (n=1384) FULL_BLOCK `meta-externalagent`._

## Sanity benchmarks (SPEC §10.2)

| Benchmark | Ours | Reference | Diff (pp) | Status |
|---|---|---|---|---|
| Control top-1,000: any rule naming meta-externalagent (M2) vs knownagents.com | 13.2% (n=683) | 19.0% | -5.8 | pass |
| Control top-5,000: meta-externalagent FULL_BLOCK (M1) vs 7 Sep 2026 Tranco-5k census | 8.4% (n=3533) | 17.2% | -8.8 | pass |
| Tier A US: FULL_BLOCK of any peer AI-training crawler vs Axios 102 publishers (directional only) | 83.8% (n=37) | 42.0% | +41.8 | flag |

## What this does not show

- **robots.txt is voluntary.** A block in robots.txt is a request, not an enforcement mechanism. Meta says `meta-externalfetcher` and `facebookexternalhit` may bypass robots.txt in some cases. We measure what sites ask for, not what crawlers do.
- **Signals are proxies.** Domain verification, the Meta Pixel, Audience Network lines in ads.txt and social links are public signals of Meta business-tool use. They do not show that a site has any particular agreement with Meta, and their absence does not show the opposite (verification by file upload is invisible to us).
- **Wayback coverage gaps.** Baselines come from Internet Archive captures. Not every site was captured in every window; before/after comparisons use only domains with both endpoints (paired design), and change dates are bracketed by capture times.
- **One fetch location.** Live fetches ran from US data-centre runners; sites may serve different robots.txt by region or to different clients.
- **No legal interpretation.** Nothing here says whether any site is or is not covered by Meta's terms or what Meta does with crawled content.
