# QA log

## Process incidents

| When (UTC) | What | Impact | Action |
|---|---|---|---|
| 2026-10-19 ~17:45 | One request to `pressgazette.co.uk/?s=top+50+news+websites+us` was made before reading Press Gazette's robots.txt, which disallows `/?s=*`. | One page fetched; it was used only to discover the article URL. | All further discovery used Press Gazette's sitemaps, which robots.txt allows. The panel builder enforces robots.txt before every fetch. |
| 2026-10-19 ~18:10 | Panel liveness pass: ~36 domains failed with local transient errors (httpx PoolTimeout, container DNS "temporary failure"). | These sites risked being wrongly dropped. | They were re-checked at low concurrency; any still unresolved are kept and flagged `unverified`. T2 (GitHub Actions) classifies them. |

## Manual verification (§10.3)

_To be completed before the data freeze (Thu 22 Oct 18:00 UTC)._
