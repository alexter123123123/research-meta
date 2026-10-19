# SPEC — "Who Locked the Door Before Oct 30?"
## A robots.txt study of news publishers and Meta's crawlers, around Meta's Oct 30, 2026 Commercial Terms

**Client:** HasData (scraping API provider) **Prepared for:** a coding agent
**Spec version:** 1.0 — 19 Oct 2026 **Timezone for all data:** UTC
**Hard deadlines:**

| When (UTC) | What |
|---|---|
| Thu 22 Oct, 18:00 | Data freeze for the launch report |
| Fri 23 Oct, 12:00 | Report package delivered |
| Thu 29 Oct, 06:00 | Deadline-eve snapshot (T3) |
| Fri 6 Nov, 06:00 | Post-deadline snapshot (T4) |

---

## 0. TL;DR for the agent

Build a reproducible Python pipeline. It must answer, with numbers and confidence intervals:

1. **How many news publishers block each of Meta's crawlers in robots.txt right now?** Focus on `meta-externalagent`, then `meta-externalads`, `meta-webindexer`, `meta-externalfetcher` and `facebookexternalhit`. Compare against:
   - a general top-sites control group;
   - publishers' treatment of other AI crawlers (GPTBot, ClaudeBot, Google-Extended, CCBot…).
2. **Did publishers change their robots.txt in response to the story?**
   - Baselines: before Meta's notice (≈2 Oct) and before Nieman Lab's report (15 Oct).
   - Afterwards: live today, then daily until the 30 Oct effective date and beyond.
3. **How many publishers show public signals of using Meta business products but do NOT block Meta's crawler?** This is the "exposed" number. It tests the press claim that virtually every news organization has a Meta business account.

You will deliver:
- raw evidence (every robots.txt body we analyzed, hashed and timestamped);
- a tidy dataset;
- a JSON of headline metrics;
- charts;
- a methodology document;
- a daily-updating static tracker page — this is the linkable asset.

Use **HasData's Web Scraping API** for fetching wherever it passes the validation gate in §6.3. The study is published as "powered by HasData", so dogfooding matters.

Do **not** draw legal conclusions. Do **not** spoof Meta's user agents. Do **not** probe WAFs or bypass paywalls. See §11.

---

## 1. Background (context only — do not hardcode as facts in outputs; cite sources in methodology)

- **The terms.** Meta's updated Commercial Terms take effect **30 Oct 2026**. They authorize crawling of websites "associated with" business accounts on Facebook, Instagram and WhatsApp.
  - Nieman Lab reported this on **15 Oct 2026**, with three legal experts saying the clause could cover nearly every news organization.
  - Nieman Lab said Meta had notified users in early October via a blog post and Business Suite notice.
- **Meta's response.** Meta says crawling is unchanged and that content owners can still manage access with robots.txt.
  - Late **Fri 16 Oct**, Meta removed "train" from the permitted uses. Use is now limited to advertising and business products.
  - Critics note the terms still don't commit Meta to honoring robots.txt.
- **Meta's current crawler documentation** (developers.facebook.com/documentation/sharing/webmasters/web-crawlers) lists five crawlers:

  | Crawler | Meta's stated purpose |
  |---|---|
  | `facebookexternalhit` | Link previews. May bypass robots.txt for security/integrity checks. |
  | `meta-webindexer` | Meta AI search and citations. |
  | `meta-externalads` | "Improving advertising and other business-related products and services." |
  | `meta-externalagent` | "Training foundation AI models or improving products by indexing content directly." |
  | `meta-externalfetcher` | User-initiated fetches. "May bypass robots.txt." |

  **Key analytical insight:** after the 16 Oct edit, the terms' permitted use (ads and business products) maps most closely to the documented purpose of **`meta-externalads`**, not `meta-externalagent`. Most robots.txt guides tell people to block only `meta-externalagent`, so a publisher could block that crawler and still leave the ads crawler open. Measuring this "ads gap" is a core goal.

  **Framing caution:** describe it as "the crawler Meta's documentation describes for advertising and business products". Do not claim Meta uses it for any specific purpose.
- **Existing numbers the press is reusing (all stale or not news-specific):**
  - knownagents.com reports about 19% of "top websites" (daily scans of the top 1,000) have rules for `meta-externalagent`.
  - A Sept 7, 2026 dev.to census of the Tranco top 5,000 found `meta-externalagent` blocked by 17.2%.
  - Axios (17 Oct) analyzed 102 US publishers, split by training vs. search crawlers. It is not Meta-specific and not a before/after comparison.

---

## 2. Research questions → metrics

Every metric must be computed for each panel segment: All-news, Tier A, Tier B, US, UK, Other, owner group (where known), and Control.

**Bot sets used in the metrics below:**
- `META_TOKENS` = `meta-externalagent`, `meta-externalads`, `meta-webindexer`, `meta-externalfetcher`, `facebookexternalhit`
- `LEGACY_META` = `facebookbot`, `facebot`, `facebookcatalog`
- `PEER_AI_TRAINING` = `gptbot`, `claudebot`, `anthropic-ai`, `google-extended`, `ccbot`, `bytespider`, `applebot-extended`, `cohere-ai`, `amazonbot`
- `PEER_AI_SEARCH` = `oai-searchbot`, `chatgpt-user`, `claude-searchbot`, `claude-user`, `perplexitybot`, `perplexity-user`
- `CLASSIC_SEARCH` = `googlebot`, `bingbot`

| ID | Question | Metric definition |
|---|---|---|
| M1 | Current blocking | % of domains with verdict `FULL_BLOCK` for each token in `META_TOKENS` at snapshot T2. Also for the peer sets and classic search. Wilson 95% CI. |
| M2 | Named mentions | % of domains whose robots.txt names each token in any group, whatever the verdict. |
| M3 | Effective blocking | % with `FULL_BLOCK` or `WILDCARD_BLOCK`. A wildcard block means `*` disallows everything and the bot is not named. |
| M4 | Reaction to the story | Domains whose `meta-externalagent` / `meta-externalads` verdict became more restrictive between T0→T2 and T1→T2 (later also T2→T3 and T3→T4). Also domains that newly named any `META_TOKENS`. Report counts and %, plus **attribution**: author-written vs inside a Cloudflare-managed block (§7.6) vs a shared template cluster (§7.7). |
| M5 | "Meta gap" | Among domains that `FULL_BLOCK` ≥1 of {gptbot, claudebot, google-extended, ccbot}, the % that do NOT `FULL_BLOCK` `meta-externalagent`. |
| M6 | "Ads gap" | Among domains that `FULL_BLOCK` `meta-externalagent`, the % that do NOT `FULL_BLOCK` `meta-externalads`. **Probably the headline.** |
| M7 | Meta-linked | % of news domains with Meta business-tool signals, by evidence level E1/E2/E3 (§8). |
| M8 | Exposed | % of news domains that are META_LINKED (by level) AND not `FULL_BLOCK`ing `meta-externalagent`. Repeat for `meta-externalads`. |
| M9 | Preview collateral | % that `FULL_BLOCK` `facebookexternalhit`, which breaks Facebook/Instagram link previews. Also % naming only legacy tokens with no current Meta token (a stale configuration). |
| M10 | News vs control | Difference in M1/M3 between All-news and Control. Report the difference with a CI using the Newcombe method. Also report the control's top-1,000 subset for a sanity comparison with knownagents' 19%. |
| M11 | Timeline | Daily count of domains that made a Meta-related robots.txt change, from 1 Sep 2026 → T4. Built from Wayback version history (§6.5) plus our daily live snapshots. Annotate the event dates in §5. |
| M12 | Docs history | First Wayback capture date at which each of `meta-externalads` and `meta-webindexer` appears on Meta's crawler docs page (§6.6). |

**Hypotheses** (each one is a potential headline; report the result whichever way it falls):

| ID | Hypothesis |
|---|---|
| H1 | Most news publishers (>50%) still do NOT block `meta-externalagent` days before 30 Oct. |
| H2 | Few publishers (<5%) changed their Meta rules after 15 Oct. If so, the outcry did not turn into action. |
| H3 | `meta-externalads` is blocked far less often than `meta-externalagent` (the ads gap). |
| H4 | Publishers block OpenAI/Anthropic/Google training bots more often than Meta's (the Meta gap). |
| H5 | A large share of Meta-linked publishers are exposed. |
| H6 | Changes cluster by owner group or platform template — chain-level decisions, not newsroom-level ones. |

**Null results are still stories.** Pre-register this rule in `docs/methodology.md` before analysis, and do not change it after seeing the data.

---

## 3. Deliverables (Definition of Done)

1. `data/panel/panel.csv` — the sample frame (§4) with provenance per row.
2. `data/raw/` — every fetched robots.txt, ads.txt, homepage HTML and DNS answer, plus Wayback captures. Each one is stored with its SHA-256 and a fetch-metadata JSON sidecar.
3. `data/processed/`:
   - `fetches.parquet`
   - `groups.parquet`
   - `verdicts.parquet`
   - `signals.parquet`
   - `changes.parquet`
   - `domain_summary.csv` — one row per domain per snapshot (schemas in §9)
4. `reports/metrics_T2.json`, plus `metrics_T3.json` and `metrics_T4.json` later. These hold all M-metrics with numerator, denominator, % and CI per segment.
5. `reports/findings.md` — generated from the JSON with no hand-typed numbers. It contains:
   - the 10 strongest statements, each with its exact numerator/denominator;
   - the hypothesis outcomes.
6. `reports/charts/` — PNG (2x) + SVG, in a neutral brand style with a "Data: HasData" footer:
   - C1: grouped bar — % FULL_BLOCK per crawler (Meta tokens vs peers), news vs control.
   - C2: timeline — daily Meta-related changes, 1 Sep → today, with event markers.
   - C3: exposure funnel — panel → reachable → META_LINKED (E1/E2/E3) → not blocking externalagent → not blocking externalads.
   - C4: "ads gap" stacked bar.
   - C5: tier/country breakdown.
   - C6: owner-group heatmap (Tier B), if n≥10 per group.
7. `docs/methodology.md` — publishable. Covers sampling, fetch method, parsing rules, verdict definitions, limitations, ethics, and the pre-registered hypotheses.
8. `site/` — the static tracker: `index.html` + `data/latest.json` + `data/history.json`, regenerated daily by `mcs site`.
   - No external JS except the allowed CDNs: Chart.js from cdnjs is fine.
   - Mobile-friendly.
   - Shows the headline counters, C1, C2, a searchable table of **Tier A** domains with their verdicts, and the methodology link.
9. `reports/qa_log.md` — results of the manual verification (§10.3).
10. `reports/factsheet.md` — one page for the PR team:
    - the top 8 stats, each with a one-sentence plain-English line;
    - a chart list;
    - "what we did NOT measure".
11. A scheduled daily monitor (cron or GitHub Actions) running through **6 Nov 2026**.
12. A `README.md` with one-command reproduction: `make all` or `mcs all --snapshot T2`.

---

## 4. Sample frame (the "panel")

Target is about 1,500 news domains plus a 10,000-domain control. Build it on Day 1 and **freeze it before any analysis.** Record frame version and date.

### 4.1 Tier A — major news brands (target ≈120–200 registered domains)
Sources: Press Gazette's monthly Similarweb rankings.
- Top 50 US news websites: the latest monthly edition (expect the September 2026 data, published October; else August).
- Top 50 UK news websites: the latest monthly edition.
- Top 50 English-language news websites in the world: the latest edition.
- World's biggest news websites in any language (June 2026 edition) — gives EU/other coverage relevant to the European Publishers Council angle.

Steps:
- Parse brand names and domains from the article tables. Respect pressgazette.co.uk's robots.txt; there are only a few pages, so fetch them politely.
- Store `source_list`, `source_rank` and `source_url`.
- Exclude non-publishers: aggregators/portals such as msn.com and news.google.com. Keep yahoo.com news only if the list shows a news-specific host. Write every exclusion to `panel_exclusions.csv` with a reason.

### 4.2 Tier B — regional & local news (target ≈1,200–1,400)

**Primary source: Wikidata SPARQL** (query.wikidata.org). It is reproducible and gives owner and country.
- Items that are instance-of / subclass-of: newspaper (Q11032), online newspaper (Q1153191), or news website (Q1193236)…
- …with country (P17) ∈ {US Q30, UK Q145}…
- …and an official website (P856)…
- …and **no** "dissolved/abolished" date (P576).
- Optional fields: owned by (P127) and parent organization (P749) → `owner_group`.
- Save the exact query text and the run timestamp in `data/panel/wikidata_query.sparql`.

**Supplement:** Wikipedia "List of assets owned by USA Today Co." and equivalent chain lists (Lee Enterprises, McClatchy, Hearst Newspapers, Advance Local, MediaNews Group / Tribune, CNHI, Adams, Ogden, Carpenter Media Group). Use them only to fill `owner_group` and add missing major dailies.

**Optional:** USNPL state lists. Before using them, check that site's robots.txt and terms. If allowed, add independents that are missing.

**Normalization:**
- Reduce every URL to its **registered domain** using `tldextract` with a **pinned** Public Suffix List snapshot.
- Deduplicate.
- Keep `brands` as a list when several brands share a domain.

**Liveness check:** a homepage HEAD/GET via the §6 fetcher. Drop domains that fail to resolve or 404 at root. Log the drops.

**Stratified sampling** if more than 1,400 domains remain:
- Strata: country × owner_group (top 10 groups + "independent/other").
- Use proportional allocation with a minimum of 10 per owner group.
- Fix `random_seed = 20261030`.

### 4.3 Control — general top sites (10,000)
- Use the **Tranco** top-10k list nearest to 19 Oct 2026. Record the list ID and date. Reduce to registered domains.
- Tag any domain that is also in the news panel (`is_news=1`). It stays in the control but is excluded from the "news vs control" comparison.
- Keep a `control_top1000` flag for the knownagents comparison.
- Wayback baselines for the control: a **random 2,000-domain subsample only**, with seed 20261030. Live snapshots cover all 10k.

### 4.4 Panel schema — `panel.csv`
| Column | Type | Notes |
|---|---|---|
| `domain` | str | Registered domain, lowercase |
| `panel` | enum | `news`, `control` |
| `tier` | enum | `A`, `B`, `control` |
| `country` | ISO-2 | From Wikidata or Press Gazette list; `XX` if unknown |
| `brands` | json list | |
| `owner_group` | str | Normalized; `independent/unknown` if missing |
| `source_list` | str | e.g. `pg_us_top50_2026-09`, `wikidata`, `tranco_<id>` |
| `source_rank` | int/null | |
| `tranco_rank` | int/null | Join every domain to Tranco for a size proxy |
| `control_top1000` | bool | |
| `is_news` | bool | |
| `added_at` | ts | |

---

## 5. Snapshots & event timeline

| Label | Definition | Source |
|---|---|---|
| **T0** | State as of **2026-10-01 23:59:59 UTC**, before Meta's early-October notice. Use the latest Wayback capture in [2026-09-01, 2026-10-01 23:59:59]. | Wayback |
| **T1** | State as of **2026-10-14 23:59:59 UTC**, before Nieman Lab's report. Use the latest capture in [2026-10-02, 2026-10-14 23:59:59]; if none, carry T0 forward and flag `t1_carried=1`. | Wayback |
| **T2** | Live fetch, **Tue 20 Oct 2026**, starting 06:00 UTC. Must finish within 12 h. | Live |
| **D(n)** | Daily live fetches, 21 Oct → 6 Nov, starting 06:00 UTC. | Live |
| **T3** | The daily fetch of **Thu 29 Oct**, the eve of the deadline. Run an extra pass on Fri 30 Oct at 06:00 UTC. | Live |
| **T4** | The daily fetch of **Fri 6 Nov**. | Live |

Event markers for chart C2 come from config (`config/events.yaml`). Label each "per press reports":

| Date | Event |
|---|---|
| 2026-10-02 | Meta notice in Business Suite (reported) |
| 2026-10-15 | Nieman Lab report |
| 2026-10-16 | Meta revises the clause and removes "train" |
| 2026-10-30 | Terms take effect |

---

## 6. Data collection

### 6.1 Identity & politeness (non-negotiable)
- **User-Agent** for every request:
  `HasDataResearchBot/1.0 (+https://hasdata.com/research/meta-crawler-study; research@hasdata.com)`
  This is a placeholder. **Ask HasData to confirm the URL and email and to publish a bot-info page before T2.** If they are not confirmed, block the run and ask.
- Request limits:
  - Max **1 concurrent request per host**.
  - Min **2 s** between requests to the same host.
  - Global concurrency ≤ 25.
- Timeouts: connect 10 s, read 20 s.
- Retries: max 2, with exponential backoff and jitter. A retry is only for network errors or 5xx/429. Honor `Retry-After`.
- Never send cookies. Never log in. Never run JS on robots/ads.txt.

### 6.2 What to fetch per domain per live snapshot
1. **Host resolution** (once per snapshot):
   - GET `https://{domain}/` and follow redirects (max 5).
   - Record the final URL, which gives the **canonical host**, e.g. `www.nytimes.com`.
   - Also note the apex host if it differs.
2. **robots.txt:**
   - GET `https://{canonical_host}/robots.txt`. If the apex host differs, also fetch `https://{apex}/robots.txt`.
   - Follow up to 5 redirects, recording the chain. A cross-host redirect is allowed per RFC 9309 — record `robots_redirected_cross_host`.
   - If HTTPS fails at the TLS/connection level, try `http://`.
   - **The analysis uses the canonical host's robots.txt.** The apex result is kept for QA.
3. **ads.txt** (T2 and T3 only): GET `https://{canonical_host}/ads.txt`, used for signal E2b.
4. **Homepage HTML** (T2 only, news panel only): see §8 for the method and the robots-compliance rule.
5. **DNS TXT** (T2 only, news panel only): TXT records of the registered domain apex.

### 6.3 Fetch engine & the HasData validation gate (Day 1, before T2)
**Primary engine:** HasData Web Scraping API.
- Endpoint: `POST https://api.hasdata.com/scrape/web`, header `x-api-key`. Docs: docs.hasdata.com/apis/web-scraping-api/api-params.md.
- Parameters for robots.txt and ads.txt:
  - `jsRendering: false`
  - `proxyType: "datacenter"`
  - `proxyCountry: "US"`
  - `headers: {"User-Agent": <our UA>}`
  - `outputFormat: ["html"]` (confirm which format returns the raw body untouched)
- Batch endpoint: `POST https://api.hasdata.com/scrape/batch/web`, up to 10,000 requests per job. Poll `GET /scrape/batch/web/{jobId}` and `/results?page=&limit=`. Failed URLs do not consume credits.
- **Gotcha:** batch requests are dispatched in parallel. Check the per-host rate rule in §6.1. Send at most one URL per host per batch; since there is only one robots.txt per host, this is naturally satisfied. Throttle submissions if the docs suggest burst behavior.

**Validation gate — must pass before using HasData as primary.** Take 60 domains: 20 Tier A, 20 Tier B, 20 control, including at least 5 known-quirky ones (Cloudflare-managed, huge file, redirecting, 404). Fetch robots.txt both via HasData and via a direct `httpx` client from the agent's machine. Then check:

1. **Body fidelity.** After normalizing line endings and stripping a BOM, the bytes must be identical for ≥58/60. HasData must not wrap the body in `<html><pre>` or alter it. If it does, write an unwrapping function and re-test.
2. **Status code exposure.** Confirm whether the HasData response exposes the **upstream HTTP status** and the **final URL** after redirects. Read docs.hasdata.com/apis/web-scraping-api/quickstart.md and inspect real responses.
   - **If the status is NOT exposed:** HasData cannot distinguish 404 (allow-all) from 5xx (disallow-all) as RFC 9309 requires. In that case use the **direct client as primary for robots.txt and ads.txt**. Use HasData for homepage rendering, and as a fallback when the direct client is blocked (403, 429 or a challenge page).
3. Log the gate result to `reports/validation_gate.md`. Engine choice is a config flag: `fetch.robots_engine: hasdata|direct`.

**Fallback ladder** for any fetch that fails or returns a bot challenge:
1. Direct `httpx`.
2. HasData datacenter.
3. HasData residential (`proxyType: residential`).
4. Mark `INDETERMINATE_BLOCKED`.

**Detect challenge pages:** a 200 response with an HTML body containing typical challenge markers such as `cf-chl`, `Just a moment`, `captcha`, `px-captcha` or `_Incapsula_`. Record `challenge_detected=1`.

**Credit estimate** (for the HasData team; verify current pricing):
- robots.txt: ~11.5k domains × ~19 live runs ≈ 220k basic requests at 1 credit each.
- Homepages: 1.5k at JS rendering, 10–15 credits each ≈ 22k credits.
- ads.txt: 2 × 1.5k.

Total ≈ 250k credits. Log actual credits in the run manifest.

### 6.4 robots.txt fetch outcome classification (RFC 9309 semantics)
| `fetch_status` | Condition | Analysis treatment |
|---|---|---|
| `OK` | 2xx, `text/*` or empty, parseable | Parse |
| `OK_EMPTY` | 2xx, empty body | Allow-all |
| `UNAVAILABLE_4XX` | 400–499 except 429, after redirects | Allow-all (RFC 9309 §2.3.1.3). Report separately. |
| `RATE_LIMITED_429` | 429 after retries | Indeterminate. (Google treats 429 like 5xx; note this in the methodology.) |
| `UNREACHABLE_5XX` | 500–599 after retries | RFC says assume full disallow. **For headline metrics, treat as INDETERMINATE.** Report the count. |
| `INVALID_HTML` | 2xx but body is HTML (soft-404), or a challenge page | Indeterminate (challenge) or allow-all (soft-404, no rules). Flag either way. |
| `NETWORK_ERROR` | DNS/TLS/timeout after retries | Indeterminate |

Rules:
- Store the body truncated at **500 KiB**, the RFC parsing limit. Set `truncated=1` if it was cut.
- Denominators for headline metrics = domains with a determinate outcome (`OK`, `OK_EMPTY`, `UNAVAILABLE_4XX`, soft-404). Always also publish the indeterminate count.

### 6.5 Wayback Machine baselines (T0, T1) and version history
- **CDX query** per host (both canonical and apex):
  ```
  https://web.archive.org/cdx/search/cdx?url={host}/robots.txt&matchType=exact
    &from=20260901&to=20261019235959&output=json
    &fl=timestamp,original,statuscode,mimetype,digest,length
    &collapse=digest
  ```
  Query with both `https://` and `http://` originals (CDX normalizes scheme, but verify). Keep **all** rows: 200s, redirects (3xx — resolve the target via a second CDX lookup), 404s.
- **Raw content:** `https://web.archive.org/web/{timestamp}id_/{original}`. The `id_` flag returns the original bytes with no Wayback banner.
- **T0/T1 selection:** the latest row with `timestamp ≤ cutoff` within the windows in §5. Store `wayback_ts` and `age_days` (cutoff − capture).
- **Version history for M11:**
  - Fetch every distinct digest between 2026-09-01 and today.
  - Parse each version.
  - A "Meta-related change" is when the verdict tuple over `META_TOKENS` + `LEGACY_META` differs from the previous version.
  - `change_date` = the first capture timestamp of the new version. **Bracket uncertainty:** record `prev_capture_ts` as well, since the true change lies between the two. Chart the change at `change_date` and publish the median bracket width.
- **Politeness:**
  - ≤1 request/second to web.archive.org, single connection.
  - Back off on 429/503 (start at 30 s, double each time, max 10 min).
  - Cache everything on disk keyed by URL. Never re-fetch a cached capture.
- **Coverage reporting:** % of domains with a T0 capture, with a T1 capture, and median capture age, per tier. Tier B coverage will be lower. **Comparisons over time use only domains with both endpoints** (a paired design); state this n explicitly.
- **Optional secondary baseline** (only if Wayback coverage of Tier B is under 40%): Common Crawl's robots.txt subset for the crawl nearest 1 Oct 2026. Do this only if time allows. Document it, and never mix sources within one comparison without flagging.

### 6.6 Meta docs history (M12)
- Run a CDX query for both `developers.facebook.com/docs/sharing/webmasters/web-crawlers` and `developers.facebook.com/documentation/sharing/webmasters/web-crawlers` (and their `/crawler` variants) from 2024-01-01 to today, `collapse=digest`.
- Fetch the versions and grep for each token.
- Output a table of `token`, `first_seen_capture`, `last_absent_capture`.
- This dates when `meta-externalads` was documented relative to the terms change. **Report only what the captures show.**

---

## 7. Parsing & verdicts

### 7.1 Parser requirements
Implement our own **RFC 9309-compliant group extractor**. It is needed to know whether a bot is *named* and which raw line named it. Cross-check every verdict with **Protego**, Scrapy's RFC-oriented parser.

Normalization:
- Decode UTF-8, then latin-1 as fallback. Strip the BOM.
- Accept CRLF, CR and LF line endings.
- Strip comments (`#` to end of line).
- Trim whitespace.
- Field names are case-insensitive (`User-Agent`, `user-agent`, `USER-AGENT`).
- Tolerate a missing space after the colon (`Disallow:/`).

Groups:
- One or more consecutive `user-agent` lines start a group.
- The group's rules continue until the next `user-agent` line that follows a rule line.
- **Merge** all groups that match the same token (RFC 9309 §2.2.1).

Rules:
- Only `allow` and `disallow` matter.
- Record but ignore `crawl-delay`, `sitemap`, `host`, `clean-param`, `content-signal` and unknown lines.
- An empty `Disallow:` means no restriction.

Path matching:
- Supports `*` and `$`.
- **Longest match wins.** On equal length, `allow` wins (RFC 9309 §2.2.2).
- Percent-encoding is normalized per the RFC.

### 7.2 User-agent token matching
- Normalize each UA line value: lowercase, trim, and strip a version suffix (`/1.1`) and anything after the first whitespace.
- **Exact token match:** `meta-externalagent` == `meta-externalagent` → `match_mode=exact`.
- **Versioned/prefix match:** `meta-externalagent/1.1`, `meta-externalagent*` → `match_mode=prefix`. Counts as named.
- **Fuzzy/broken lines:** e.g. `Meta-External*`, `meta external agent`, `MetaExternalAgent`, `facebook*`. Record as `match_mode=nonstandard` and **do not** count them as named in headline metrics. List them in the QA log; they become a small "misconfigured" sub-finding.
- `*` group → used only when no group names the bot.
- Keep a `named_raw` column with the exact original line(s).

### 7.3 Probe URLs (to turn rules into verdicts)
Per domain, build a probe set:
- `/`
- `/news/`
- Up to **3 article URLs** sampled from the T2 homepage:
  - same host;
  - path depth ≥2;
  - looks like an article (contains `/20\d\d/`, or a slug with ≥4 hyphens, or ends in `.html`/`.ece`/`.amp`);
  - excludes `/tag/`, `/author/`, `/search` and `/live`.
- If no articles can be found, use `/2026/10/example-article-slug/` as a synthetic probe and flag `synthetic_probe=1`.
- **The same probe set is reused for every snapshot of that domain** (T0–T4) for comparability.

### 7.4 Verdict enum (per domain × snapshot × bot)
| Verdict | Definition |
|---|---|
| `FULL_BLOCK` | Bot is named (exact/prefix), and **all** probes are disallowed for it. |
| `PARTIAL_BLOCK` | Bot is named, and some but not all probes are disallowed. |
| `ALLOWED_EXPLICIT` | Bot is named, and no probe is disallowed. |
| `WILDCARD_BLOCK` | Bot is not named, and the `*` group disallows all probes. |
| `WILDCARD_PARTIAL` | Bot is not named, and `*` disallows some probes. |
| `ALLOWED_DEFAULT` | Bot is not named, and `*` allows all probes (or there are no rules). |
| `INDETERMINATE` | Fetch outcome is indeterminate (§6.4). |

- "Explicit block" in copy = `FULL_BLOCK`.
- "Effective block" = `FULL_BLOCK` ∪ `WILDCARD_BLOCK`.
- **Protego cross-check:** for each probe, compare our allow/deny with `Protego.can_fetch(probe, token)`. On disagreement, write the row to `parser_disagreements.csv` and fix or explain every disagreement in the QA log before freeze. Expect disagreements mainly where we deliberately exclude non-standard UA lines.

### 7.5 Bots evaluated
Use `META_TOKENS` ∪ `LEGACY_META` ∪ `PEER_AI_TRAINING` ∪ `PEER_AI_SEARCH` ∪ `CLASSIC_SEARCH`, as defined in §2. Keep the list in `config/bots.yaml`.

### 7.6 Cloudflare-managed and other auto-generated content
Detect the Cloudflare-managed section markers. These are case-insensitive and the exact wording varies, so match loosely: `# BEGIN Cloudflare Managed content` … `# END Cloudflare Managed Content`. Also detect `Content-Signal:` lines.

- For every named Meta rule, record `in_cf_managed_block` (bool).
- **M4 attribution:** if a change is only inside a CF-managed block, label it `cf_managed`, otherwise `authored`.
- If many unrelated domains change identically on the same day inside CF blocks, that is a Cloudflare default change, not publisher intent. **Never** report those as "publishers reacted" without this split.
- Also detect common generator fingerprints in comments: Yoast, Rank Math, WordPress VIP, Arc XP, Brightspot, and similar. Record them in a `generator_hint` column.

### 7.7 Template clusters
- Compute `body_hash` after normalization (strip comments and the `Sitemap:` lines, which differ per site).
- Domains sharing an identical `body_hash` form a **template cluster**.
- For M4 and H6, report changes both per domain and **per cluster**.
- Join clusters with `owner_group` to show chain-level decisions.

---

## 8. Meta business-tool signals (for M7/M8 "exposed")

**Purpose:** test the claim that virtually every news org has a Meta business account using **public** signals only. These are proxies. Never claim a site "is bound by" the terms.

| Level | Signal | How |
|---|---|---|
| **E1** (strong) | Meta domain verification | (a) `<meta name="facebook-domain-verification" content="…">` in homepage HTML; (b) a DNS TXT record on the apex containing `facebook-domain-verification=`. Meta also allows verification by HTML file upload, which is not discoverable, so E1 is a **lower bound**. |
| **E2** (medium) | Meta Pixel on the homepage | In raw or rendered HTML: `connect.facebook.net/<locale>/fbevents.js`, `fbq('init','<id>')` (extract the pixel IDs), or `facebook.com/tr?id=`. |
| **E2-GTM** (weak) | Pixel only via Google Tag Manager | If no direct pixel is found but a GTM container ID is present, fetch `https://www.googletagmanager.com/gtm.js?id=GTM-XXXX` (public JS) and grep for `fbevents` or `facebook.com/tr`. |
| **E2b** (medium) | Meta Audience Network in ads.txt | A line whose first field is `facebook.com`. |
| **E3** (weak) | Facebook or Instagram profile links | `<a href>` to `facebook.com/<page>` or `instagram.com/<handle>`. Also `<meta property="fb:pages">` or `fb:app_id`. |

E3 exclusions: share/intent/plugin URLs such as `sharer`, `share.php`, `dialog`, `plugins`, `tr`, `login`, `policies`, `privacy`, `help`, `groups/` (keep `groups` as its own flag), `events/`.

**Derived:** `meta_linked_level` = highest level present (E1 > E2/E2b > E2-GTM > E3 > none). Report **cumulative** shares:
- E1 only;
- E1 ∪ E2 ∪ E2b;
- E1 ∪ E2 ∪ E2b ∪ E2-GTM;
- any (including E3).

**Homepage fetch method & compliance rule:**
1. Before fetching the homepage, evaluate the T2 robots.txt for **our own UA** (falling back to `*`).
2. If `/` is allowed: fetch the live homepage via HasData with `jsRendering: true`, `wait: 3000`, `blockResources: true`. Do **not** set `blockAds`, because that may strip the pixel. Also fetch raw (non-JS) HTML. Scan both, so the pixel is caught whether it is static or injected.
3. If `/` is disallowed for us: **do not fetch live.** Use the latest Wayback capture of the homepage within 30 days (`id_` raw), mark `homepage_source=wayback`, and keep the DNS and ads.txt checks.
4. One homepage fetch per domain for the whole study. A second fetch at T3 is allowed only for the Tier A tracker table.
5. Store raw HTML compressed. Do not store screenshots.

---

## 9. Data model (Parquet/DuckDB)

### `fetches`
`fetch_id`, `domain`, `host`, `snapshot` (T0/T1/T2/Dyyyymmdd/T3/T4), `resource` (robots/ads/homepage/dns/meta_docs), `source` (live_direct/live_hasdata_dc/live_hasdata_res/wayback), `requested_url`, `final_url`, `redirect_chain` (json), `http_status`, `fetch_status` (enum §6.4), `content_type`, `bytes`, `truncated`, `sha256`, `body_path`, `wayback_ts`, `age_days`, `challenge_detected`, `fetched_at`, `engine_credits`, `error`.

### `groups`
`fetch_id`, `group_idx`, `ua_raw`, `ua_token_norm`, `match_mode`, `rules` (json list of `{type, path, line_no}`), `in_cf_managed_block`, `line_start`, `line_end`.

### `verdicts`
`domain`, `snapshot`, `bot`, `verdict` (enum §7.4), `named`, `named_raw`, `match_mode`, `probes_total`, `probes_disallowed`, `protego_agree` (bool), `in_cf_managed_block`, `fetch_id`.

### `signals`
`domain`, `e1_meta_tag`, `e1_dns_txt`, `e2_pixel`, `pixel_ids` (json), `e2_gtm`, `e2b_adstxt`, `e3_fb_link`, `e3_ig_link`, `fb_pages_meta`, `fb_app_id`, `meta_linked_level`, `homepage_source`, `homepage_fetch_id`.

### `changes`
`domain`, `bot`, `from_snapshot`, `to_snapshot`, `from_verdict`, `to_verdict`, `direction` (more_restrictive/less_restrictive/same), `attribution` (authored/cf_managed/unknown), `template_cluster`, `change_date`, `prev_capture_ts`, `bracket_hours`.

Restrictiveness order, least to most: `ALLOWED_DEFAULT` < `ALLOWED_EXPLICIT` < `WILDCARD_PARTIAL` < `PARTIAL_BLOCK` < `WILDCARD_BLOCK` < `FULL_BLOCK`. `INDETERMINATE` is excluded.

### `domain_summary.csv` (flat, publishable)
One row per domain for a given snapshot: panel fields + verdicts for the 5 Meta tokens + gptbot / claudebot / google-extended / ccbot + `meta_linked_level` + `changed_since_T1` + `attribution`.

---

## 10. Analysis, statistics & QA

### 10.1 Statistics
- Proportions use the **Wilson 95% CI**.
- Differences between independent groups (news vs control) use the **Newcombe hybrid score interval**.
- Paired before/after on the same domains uses an **exact McNemar test**. Report discordant pairs, b and c.
- Report **unweighted** shares as primary. Secondary: a **size-weighted** share using weight = 1/log10(tranco_rank+10). Label it clearly; it is only a proxy for traffic.
- **Every published number carries n.** Suppress segment metrics when the denominator is under 20, and show "n<20".

### 10.2 Sanity benchmarks (must run; investigate if off)
- **Control top-1,000:** share with any rule for `meta-externalagent` should land in the same ballpark as knownagents' ~19% for top-1,000 sites. Rules-for ≈ our M2 "named".
- **Control top-5k subset:** `meta-externalagent` FULL_BLOCK should be near the Sept 7 Tranco-5k census figure of 17.2%. Differences of ±5 pp are plausible given different dates and definitions.
- **Tier A US vs Axios's 102 publishers:** "blocks training" should be in the neighborhood of 42% when using our peer training set. Definitions differ, so this is directional only.

If any benchmark is off by more than 10 pp, stop and write an explanation in `qa_log.md` before freeze.

### 10.3 Manual QA (before data freeze)
Open each robots.txt by hand and check the parsed verdicts for:
- **all Tier A domains** where any Meta verdict changed between T0/T1 and T2;
- **a random 50** from Tier B;
- **a random 30** from control;
- **all** `nonstandard` match_mode rows;
- **all** Protego disagreements.

Record the domain, what you saw, the verdict, and agree/disagree. The accuracy target is ≥98% agreement on the random samples. If it falls below that, fix the parser and re-run.

### 10.4 Unit tests (pytest; fixtures in `tests/fixtures/robots/`)
Must include fixture robots.txt files covering:
1. Multiple UA lines sharing a group.
2. The same UA in two separate groups (must merge).
3. `Allow: /` overriding `*` disallow for a named bot.
4. Longest-match precedence, `Allow` vs `Disallow` tie.
5. `*` and `$` wildcards.
6. An empty `Disallow:`.
7. BOM + CRLF + tabs + no space after the colon.
8. `User-agent: Meta-ExternalAgent/1.1` (prefix).
9. `User-agent: meta-external*` (nonstandard).
10. A Cloudflare-managed block with a Meta rule inside, and an authored rule outside.
11. An HTML soft-404.
12. A >500 KiB file (truncation).
13. A file with only `Sitemap:` lines.
14. Comment-only lines between UA and rules.
15. A `Content-Signal:` line.
16. Unicode in paths.

Also required: tests for the probe builder, the verdict ladder, change direction, Wilson CI, and signal regexes (pixel, domain-verification meta, DNS TXT parsing, FB-link exclusions).

---

## 11. Ethics, legal & reputational guardrails

1. Fetch only public, conventional, unauthenticated resources: robots.txt, ads.txt, homepages, public DNS, public GTM JS, Wayback.
2. Honor robots.txt for our own UA on homepage fetches. Fetching robots.txt and ads.txt themselves is permitted by convention.
3. **Never** send Meta, OpenAI or any other third-party crawler UA. **Never** test whether WAFs block Meta's crawler; Cloudflare verifies crawlers by IP anyway, so the results would be invalid as well as improper.
4. No paywall bypass, no login, no forms, no cookies.
5. Rate limits per §6.1 and §6.5.
6. **Language in outputs:**
   - Say "signals of Meta business-tool use", not "has a business account" or "is bound by the terms".
   - Say "blocks in robots.txt", not "is protected". Robots.txt is a request, and Meta says `meta-externalfetcher` and `facebookexternalhit` may bypass it in some cases.
   - Say "the crawler Meta describes for advertising and business products" for `meta-externalads`.
7. The domain-level public table is **Tier A only** (large brands). Tier B appears in the public dataset as aggregates and owner groups. The PR team decides whether to release the Tier B rows, so default `release.tier_b_rows: false`.
8. Include a right-of-reply placeholder in `factsheet.md`: "Meta was asked for comment on [date]". The PR team handles the outreach.

---

## 12. Repo layout & CLI

```
meta-crawler-study/
  README.md
  Makefile
  pyproject.toml            # python>=3.11
  config/
    study.yaml              # snapshots, cutoffs, seeds, UA, rate limits, engine flags, release flags
    bots.yaml
    events.yaml
  src/mcs/
    cli.py                  # typer
    panel/{pressgazette.py, wikidata.py, chains.py, tranco.py, normalize.py, sample.py}
    fetch/{client.py, hasdata.py, direct.py, wayback.py, dns.py, ratelimit.py, cache.py, challenge.py}
    parse/{robots.py, tokens.py, probes.py, verdict.py, cfmanaged.py, templates.py}
    signals/{homepage.py, pixel.py, adstxt.py, gtm.py}
    analyze/{metrics.py, stats.py, changes.py, timeline.py, benchmarks.py}
    report/{charts.py, findings.py, factsheet.py, methodology.py}
    site/{build.py, templates/index.html}
  data/{panel, raw, processed}/
  reports/{charts}/
  site/
  tests/{fixtures/robots/, test_*.py}
  docs/methodology.md
```

**Commands** (each one is idempotent and resumable using the on-disk cache):

| Command | What it does |
|---|---|
| `mcs build-panel` | §4. Writes `panel.csv` and `panel_exclusions.csv`. |
| `mcs validate-engine` | §6.3 gate. Writes `reports/validation_gate.md`. |
| `mcs fetch-live --label T2` | Hosts, robots, ads.txt. Homepage and DNS when `--with-signals`. |
| `mcs fetch-wayback --label T0 --cutoff 2026-10-01T23:59:59Z` | One baseline snapshot. |
| `mcs fetch-wayback --label T1 --cutoff 2026-10-14T23:59:59Z` | The second baseline snapshot. |
| `mcs fetch-wayback-history --from 2026-09-01` | M11 version history. |
| `mcs meta-docs-history` | §6.6. |
| `mcs parse` | All bodies. |
| `mcs verdicts` | All verdicts. |
| `mcs signals` | §8 signals. |
| `mcs analyze --snapshot T2` | Writes `metrics_T2.json`. |
| `mcs report --snapshot T2` | Charts, `findings.md`, `factsheet.md`. |
| `mcs site` | Builds the tracker. |
| `mcs monitor` | Daily: fetch-live (robots + ads only) → parse → verdicts → changes → analyze(latest) → site. Exits nonzero on more than 5% new INDETERMINATE. |
| `mcs all --snapshot T2` | Full launch run. |

**Stack:**
- Data: `httpx[http2]` (async), `tenacity`, `dnspython`, `tldextract` (pinned PSL), `protego`, `selectolax`, `polars` or `pandas`, `duckdb`, `pyarrow`.
- Stats & charts: `statsmodels` (proportion CIs), `scipy` (McNemar exact), `matplotlib`.
- App: `pydantic`, `typer`, `pytest`, `ruff`.
- Secrets: `HASDATA_API_KEY` from env only; never commit it.

**Run manifest** — every command appends to `data/manifest.jsonl`: `command`, `git sha`, `config hash`, `start`/`end`, `counts`, `credits used`, `errors`.

---

## 13. Schedule (agent work plan)

| Day (2026) | Tasks | Exit criteria |
|---|---|---|
| **Mon 19 Oct (eve)** | Scaffold repo, config, parser + unit tests (§10.4). Request the UA/bot-page and API key from HasData. | Tests green. UA confirmed. |
| **Tue 20 Oct** | `build-panel` (freeze by 10:00 UTC). `validate-engine`. **T2 live fetch** of robots/ads/hosts for news + control. Homepage/DNS signals for news. Start `fetch-wayback` T0/T1 for news (long-running, polite). | ≥95% of panel with a determinate T2 outcome. Gate report written. |
| **Wed 21 Oct** | Finish the Wayback T0/T1 + history (news + 2k control sample). `meta-docs-history`. Parse, verdicts, signals. Run the first `monitor` (D21). Set up the daily scheduler. | Coverage table. Protego disagreements listed. |
| **Thu 22 Oct** | Analyze, run benchmarks, manual QA (§10.3), fix, re-run. Charts. **Data freeze at 18:00 UTC.** | QA ≥98%. Benchmarks explained. `metrics_T2.json` final. |
| **Fri 23 Oct** | `findings.md`, `factsheet.md`, `methodology.md`, tracker site build. Hand-off package (§3) by **12:00 UTC**. | All §3 items 1–10 present. |
| **Sat 24 → Fri 6 Nov** | Daily monitor at 06:00 UTC. **Thu 29 Oct:** T3 report (`metrics_T3.json` + updated charts + a delta section in `findings.md`) by 12:00 UTC. **Fri 30 Oct:** extra pass. **Fri 6 Nov:** T4 report. | Tracker updated daily. Alerts on failures. |

**Alerting:** if the monitor fails or more than 5% of fetches are indeterminate, write `reports/ALERT_<date>.md` and stop publishing tracker updates until it is resolved. Do not publish partial data silently.

---

## 14. Output templates (numbers auto-filled from the metrics JSON; never hand-typed)

`findings.md` should open with these, filling `{}` from JSON and dropping any whose n<20:

- "{pct} of {n} news sites ({ci}) explicitly block `meta-externalagent` in robots.txt as of {T2 date}, versus {pct_c} of the top-10k general sites."
- "Only {k} of {n_paired} news sites with archived robots.txt changed any Meta crawler rule between 14 Oct and {T2 date}; {k_authored} were publisher-authored, {k_cf} came via Cloudflare-managed rules."
- "Of the {n_x} news sites that block Meta's AI training crawler, {pct} leave `meta-externalads` — the crawler Meta documents for advertising and business products — unblocked."
- "{pct} of news sites that block at least one of OpenAI's, Anthropic's, Google's or Common Crawl's training crawlers do not block Meta's."
- "{pct} of news sites show at least one public signal of Meta business-tool use (domain verification, Meta Pixel or Audience Network); {pct_exposed} of those do not block Meta's crawler."
- "{k_fbhit} news sites block `facebookexternalhit`, which can break link previews on Facebook and Instagram."
- (from M12) "Meta's crawler documentation first lists `meta-externalads` in an archived capture dated {date}." Include only if the captures support it.

Close with a **"What this does not show"** section:
- robots.txt is voluntary;
- the signals are proxies;
- Wayback coverage gaps;
- one fetch location (US);
- no legal interpretation.

---

## 15. Open items to confirm with HasData before T2

1. The bot UA string, the info-page URL and the contact email (§6.1).
2. API key and credit budget (~250k credits; §6.3).
3. Hosting for `site/`, e.g. `hasdata.com/research/meta-crawler-tracker`, and who deploys the daily updates.
4. Whether to release Tier B domain-level rows (`release.tier_b_rows`).
5. A spokesperson name for quotes in `factsheet.md`.
6. Brand colors and fonts for the charts (default: neutral grayscale + one accent).
