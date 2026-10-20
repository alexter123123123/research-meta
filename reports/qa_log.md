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

_To be completed before the data freeze (Thu 22 Oct 18:00 UTC)._

## Wayback coverage (news history job, 20 Oct 2026)

- **Captures in 1 Sep–20 Oct 2026:** about 77% of Tier A and about 14% of Tier B domains have at least one robots.txt capture.
- **The empty results are genuine.** The CDX answered 200 with no rows; e.g. liverpoolecho.co.uk and oxfordmail.co.uk were last captured in April–May 2026. Wayback captures robots.txt only when it crawls a site, so it rarely does so for small local sites.
- **24 domains are restricted by the Archive** (CDX returns 403 "requires authorization"), e.g. theguardian.com.
  - These were first mislabelled `NO_CAPTURE`. They are now labelled `WAYBACK_RESTRICTED` and re-run.
- **Consequence:** the T0/T1→T2 comparison (H2) is effectively a Tier A analysis with a small paired n. The deadline-reaction analysis (T2→T3→T4) rests on our own daily live snapshots of all 1,496 news domains, which do not depend on Wayback.
- **Common Crawl fallback (§6.5):** not feasible in the time available. Its robots.txt captures sit in a separate subset that is not URL-indexed, so using it means scanning bulk WARC files.
