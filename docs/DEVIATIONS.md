# Deviations from SPEC.md (decided with the study owner, 19 Oct 2026)

1. **Fetch engine.** No HasData API access is available, so all fetches use our own direct
   `httpx` client (spec §6.3 already allows `fetch.robots_engine: direct`; it also exposes the
   upstream status and final URL that RFC 9309 semantics need). Homepages are rendered with
   headless Chromium (Playwright). The methodology must say this; outputs must not claim the
   data was fetched with HasData's API. Third-party fallback is off (`fetch.fallback_engine: none`);
   challenge pages are recorded as `INDETERMINATE_BLOCKED`.
2. **Bot identity.** `MetaCrawlerStudy/1.0 (+https://github.com/alexter123123123/research-meta)`.
   The repo README is the bot-info page (purpose, contact via GitHub issues, opt-out). No email.
3. **Runner.** Long jobs and the daily monitor run in GitHub Actions; the dev container cannot
   reach web.archive.org.
4. **Press Gazette UK list** publishes brand names, not domains; a curated brand→domain map is
   used (`source_list=pg_uk_top50_*`, mapping recorded in `data/panel/pg_uk_brand_map.csv`).
5. **Politeness incident.** On 19 Oct 2026 ~17:45 UTC one request was made to
   `pressgazette.co.uk/?s=...` before its robots.txt (`Disallow: /?s=*`) was read. Sitemaps are
   used since. Logged in `reports/qa_log.md`.
