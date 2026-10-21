# QA log

## Process incidents

| When (UTC) | What | Impact | Action |
|---|---|---|---|
| 2026-10-19 ~17:45 | One request to `pressgazette.co.uk/?s=top+50+news+websites+us` was made before reading Press Gazette's robots.txt, which disallows `/?s=*`. | One page fetched; it was used only to discover the article URL. | All further discovery used Press Gazette's sitemaps, which robots.txt allows. The panel builder enforces robots.txt before every fetch. |
| 2026-10-19 ~18:10 | Panel liveness pass: ~36 domains failed with local transient errors (httpx PoolTimeout, container DNS "temporary failure"). | These sites risked being wrongly dropped. | They were re-checked at low concurrency; any still unresolved are kept and flagged `unverified`. T2 (GitHub Actions) classifies them. |

| 2026-10-20 06:00 | The scheduled T2 trigger did not fire. | T2 started 2 h 31 min late. | Started manually at 08:31 UTC and finished at 10:35, the same day. GitHub delivered the dropped 06:00 event 5 hours late (10:59); that run was cancelled before it started. The T2 schedule was then removed. |

## T2 coverage (20 Oct 2026)

A retry pass with a 40 s read timeout recovered almost nothing, so the remaining failures are persistent:
the sites drop or tarpit traffic from data-centre IPs, or serve bot challenges. Per §11 we do not
route around them; they are `INDETERMINATE` and excluded from headline denominators.

| Panel | Domains | Determinate | Bot challenge | Network error | 5xx / 429 |
|---|---|---|---|---|---|
| News | 1,496 | 93.9% | 44 | 41 | 6 |
| Control | 10,000 | 73.0% | 555 | 2,082 | 68 |

- **News:** just below the 95% exit criterion. The shortfall is entirely sites blocking our clearly
  identified research bot. That this happens (≈5.7% of news sites) is a small finding in itself.
  - Tier A indeterminate: politico.com, news18.com and ndtv.com served challenges; cbc.ca and itv.com refused connections.
- **Control:** the network errors are dominated by infrastructure domains with no web server,
  e.g. akamaiedge.net, root-servers.net, cloudfront.net, windowsupdate.com. This is expected for a
  Tranco list, which ranks DNS popularity.

## Benchmarks (§10.2), preliminary T2

- **Control top-1,000, any rule naming `meta-externalagent`:** 13.1% (n=681) vs knownagents ~19%. Within 10 pp.
- **Control top-5,000, `FULL_BLOCK` of `meta-externalagent`:** 8.4% (n=3,537) vs the 17.2% Tranco-5k census.
  - Within 10 pp but on the low side.
  - Likely reason: our denominator includes every reachable domain that has no robots.txt (4xx = allow-all), and the top-5k contains many such infrastructure and API domains.
  - The census probably counted only sites with a robots.txt. To be re-checked with "sites with an OK robots.txt" as the denominator.
- **Tier A US, `FULL_BLOCK` of any peer AI-training crawler:** 83.8% (n=37) vs Axios 42%. Flagged (> 10 pp).
  - The spec marks this comparison directional only. The populations differ: our Tier A US is the
    ~38 largest US news sites by traffic, while Axios covered 102 US publishers of all sizes.
    Larger publishers block AI crawlers far more often (also visible in our Tier A vs Tier B split).
  - Our peer set also has 9 crawlers (incl. Amazonbot, Bytespider, CCBot), so "any of" is broader.
  - Not a parser problem; manual checks of nytimes.com, bbc.co.uk and reuters.com confirm the verdicts.

## Parser cross-check (Protego), T2

There are 129 disagreements across 103 domains. All of them fall into deliberate, documented differences:

1. **Prefix families** (`applebot` vs `applebot-extended`, `claude` vs `claude-user`, `cohere`). Protego
   applies a group to any query token that contains the group's name; RFC 9309 matches the product token.
   We follow the RFC. Example: wsj.com names `Applebot`, so for `applebot-extended` we fall back to `*`.
2. **Versioned tokens** (`meta-externalagent/1.1`). The spec says to count them as named (`prefix`); Protego does not.
3. **Truncated or generic tokens** (`Meta-External`, `Meta`, `Facebook`). Protego treats them as matches;
   the spec says not to count them (`nonstandard`). As of this entry the parser also flags such
   truncated tokens as `nonstandard`, so they appear in the misconfiguration sub-finding.

All 12 Meta-token disagreements are on control domains (syosetu.com, flipboard.com, consumerreports.org …);
none are on news domains, so the headline Meta metrics are unaffected.

## Notable observations (to verify in manual QA)

- **Ads gap:** of 561 news sites that `FULL_BLOCK` `meta-externalagent`, 546 leave
  `meta-externalads` entirely unaddressed (`ALLOWED_DEFAULT`).
- **Who blocks the ads crawler:** all 11 news sites that do are US college newspapers
  (cavalierdaily.com, thedp.com, tuftsdaily.com …). This suggests one shared hosting or CMS template.
- **Cloudflare:** CF-managed blocks are only 5.5% of `meta-externalagent` `FULL_BLOCK`s among news sites.

## Manual verification (§10.3)

Reviewed on 20 Oct 2026, ~21:00 UTC, with `scripts/qa_view.py`. The script prints every UA group
naming `*`, Meta/Facebook or GPT tokens, with their rules, next to the parser's verdicts.

### Random samples (seed 20261030; domains with an `OK` robots.txt at T2)

| Sample | n | Agree | Disagree | Notes |
|---|---|---|---|---|
| Tier B | 50 | 50 | 0 | Includes the TownNews/BLOX template, the Gannett template, `Allow: /$` plus `Disallow: /` (brownwoodtx.com → `WILDCARD_PARTIAL`), and two separate `*` groups (michiganadvance.com) |
| Control | 30 | 30 | 0 | Includes naver.com, grok.com (`Allow: /$` exceptions), eatingwell.com and cnet.com (long multi-UA groups), and adweek.com (`MetaInspector`, correctly not treated as a Meta token) |
| **Total** | **80** | **80** | **0** | **100% agreement (target ≥ 98%)** |

Sample domains are listed in `reports/qa_samples_T2.txt`.

### All Tier A domains whose Meta verdict changed T0/T1 → T2

| Domain | Change | Raw file check | Verdict |
|---|---|---|---|
| ft.com | T1 `ALLOWED_DEFAULT` → T2 `FULL_BLOCK` | 14 Oct capture has no Meta groups; live file names `meta-externalagent` and `Meta-ExternalFetcher` | agree, real change after 15 Oct |
| screenrant.com | T0/T1 `ALLOWED_DEFAULT` → `FULL_BLOCK` | before: only `FacebookBot`; now adds `meta-externalagent` | agree |
| indianexpress.com | `FULL_BLOCK` → `ALLOWED_DEFAULT` | before: `Meta-ExternalAgent` and `Meta-ExternalFetcher` groups; now no Meta groups | agree, block removed |
| npr.org | T0 `FULL_BLOCK` → `ALLOWED_DEFAULT` | 1 Oct capture names Meta-ExternalAgent, Fetcher and WebIndexer; live file only `FacebookBot` and `facebookexternalhit` | agree, removed between 1 Oct and 9 Oct |
| washingtonpost.com | T0 `ALLOWED_DEFAULT` → `FULL_BLOCK` | **artifact:** the 1 Oct capture is an HTTP 403 served to the archive crawler | **disagree → fixed** (see below) |
| thetimes.com | T0 `ALLOWED_DEFAULT` → `WILDCARD_BLOCK` | **artifact:** the 19 Sep capture is a "Verifying your device" challenge page, stored as a soft-404; the live file is `User-agent: * / Disallow: /` | **disagree → fixed** |

Fixes applied before freeze:
1. Challenge markers were extended ("verifying your device", "checking your browser", toadmash/monocle …).
2. Stored HTML bodies are re-checked at parse time.
3. Archived captures that are HTML pages or 401/403 responses are treated as `INDETERMINATE` (`WAYBACK_HTML` / `WAYBACK_BLOCKED`): they show the archive's crawler being turned away, not the site's rules. Baseline selection skips such captures and takes the latest valid capture in the window.

After re-parsing, washingtonpost.com and thetimes.com no longer show a change. Other Tier B changes
checked on the raw files: the southernminn.com group (Southern Minn Media) removed its whole
AI-crawler block between 2 and 20 Oct.

### Nonstandard UA rows

18 at T2, e.g. `PerplexityUser`, `Perplexity‑User` (non-ASCII hyphen), `ChatGPTUser`,
`Perplexity Bot`, `GPTBot<br/>`. They are correctly not counted as named. Truncated forms such as
`Meta-External` and `Meta` are now also flagged.

### Protego disagreements

All fall into the three documented categories (prefix families, versioned tokens,
truncated/generic tokens). None involve a news domain and a Meta token.

## Wayback coverage (news history job, 20 Oct 2026)

- **Captures in 1 Sep–20 Oct 2026:** about 77% of Tier A and about 14% of Tier B domains have at least one robots.txt capture.
- **The empty results are genuine.** The CDX answered 200 with no rows; e.g. liverpoolecho.co.uk and oxfordmail.co.uk were last captured in April–May 2026. Wayback captures robots.txt only when it crawls a site, so it rarely does so for small local sites.
- **24 domains are restricted by the Archive** (CDX returns 403 "requires authorization"), e.g. theguardian.com.
  - These were first mislabelled `NO_CAPTURE`. They are now labelled `WAYBACK_RESTRICTED` and re-run.
- **Consequence:** the T0/T1→T2 comparison (H2) is effectively a Tier A analysis with a small paired n. The deadline-reaction analysis (T2→T3→T4) rests on our own daily live snapshots of all 1,496 news domains, which do not depend on Wayback.
- **Common Crawl fallback (§6.5):** not feasible in the time available. Its robots.txt captures sit in a separate subset that is not URL-indexed, so using it means scanning bulk WARC files.

## Analysis review (21 Oct 2026)

- **H2 / M4 and carried-forward baselines.**
  - T1 rows carried forward from T0 (no capture in 2–14 Oct) are now excluded from all T1→X change pairs. A change against a carried baseline may predate the 15 Oct story.
  - Before the fix: 20/231 = 8.7%. After: **15/136 = 11.0%**. H2 remains *not supported*.
  - The 5 dropped changes (amny.com, cornellsun.com, downtownexpress.com, hcnews.com, screenrant.com) remain visible in the T0→T2 comparison.
- **Tranco-5k benchmark, re-checked with "domains with an OK robots.txt" as the denominator.**
  - 9.2% (n=2,861) vs 17.2% in the 7 Sep census; with all determinate outcomes it is 7.5% (n=3,522).
  - Both are within the 10 pp tolerance but low. Likely reasons:
    1. Tranco ranks DNS popularity, so the top 5k contains many API/CDN/infrastructure hosts that serve a generic robots.txt.
    2. The census definition of "blocked" is not documented and may include partial disallows.
  - No parser issue found (manual QA 80/80).
- **Wayback control sample** complete: 2,000/2,000 domains processed.
