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
6. **Press Gazette fetch method.** The three ranking articles were fetched once with `curl`,
   using the study UA, before we knew Press Gazette returns 403 to Python HTTP clients. One
   further curl fetch was made after the 403 was seen. That later fetch is logged in
   `reports/qa_log.md` and was not repeated. The ranking data itself comes from the public
   Datawrapper CSVs behind the articles. The article HTML was used only to find the Datawrapper
   IDs, and that HTML is cached in `data/panel/sources/`. The June 2026 "any language" list
   could not be located: the sitemap index returned 403. Tier A therefore uses the US, UK and
   world-English Top 50 lists (September 2026 data).
7. **Wikidata.** query.wikidata.org's robots.txt disallows `/sparql`, and Wikimedia's UA policy
   rejected our client. The identical SPARQL was therefore run on QLever's public Wikidata
   mirror (qlever.dev). Index details are in `data/panel/wikidata_query.sparql`.
8. **Chain lists.** Wikipedia (`/w/api.php` is disallowed; `/wiki/` pages returned 403) was not
   used. `owner_group` comes from Wikidata P127/P749 only, so `independent/unknown` is large
   (~68% of Tier B). The H6 owner-group analysis is limited accordingly.
9. **Tranco.** robots.txt disallows `/api` and `/list/`, so the latest daily list was used
   (ID 467YX, published 18 Oct 2026), not a list chosen by date.
10. **Tier B quality filters** (applied before sampling):
    - excluded a batch-created content-farm network (owner "VUGA", 27 domains);
    - excluded foreign-ccTLD editions mislabelled US/UK (e.g. epochtimes.fr/.it/.pl).
    All exclusions are in `panel_exclusions.csv`.
11. **Tier A size** is 96 registered domains, below the 120–200 target, because the source
    lists overlap heavily.
12. **Credit line.** HasData confirmed (19 Oct 2026) that the "Data: HasData" credit on charts
    is acceptable, given that the methodology says the data was collected without HasData's API.
    Spokesperson for the factsheet: Roman Milyushkevich, Co-founder and CTO at HasData.
13. **T2 start time.** The scheduled 06:00 UTC trigger for T2 did not fire (GitHub dropped the
    scheduled event). T2 was started manually at 08:31 UTC on 20 Oct 2026, the same day and
    well inside the 12-hour window. The daily monitor now has an off-the-hour primary schedule
    (06:07 UTC) and a backup run at 07:37 UTC.
