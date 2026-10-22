# Meta Crawler Study — robots.txt of news publishers around Meta's 30 Oct 2026 terms

A research study for HasData. It measures how news publishers treat Meta's crawlers
(`meta-externalagent`, `meta-externalads`, `meta-webindexer`, `meta-externalfetcher`,
`facebookexternalhit`) in robots.txt, before and after Meta's updated Commercial Terms take
effect on 30 October 2026. It also compares those rules with how publishers treat other AI
crawlers and with a general top-sites control group.

## About our crawler — `MetaCrawlerStudy/1.0`

If you saw this User-Agent in your logs:

```
MetaCrawlerStudy/1.0 (+https://github.com/alexter123123123/research-meta)
```

it came from this study.

**What it fetches**
- `/robots.txt` (and `/ads.txt`) once a day, 20 Oct – 20 Nov 2026.
- On news sites only: your homepage, once. We first check your robots.txt allows us, and we
  skip the homepage if it doesn't.

**How it behaves**
- At most one request at a time per host, with at least 2 seconds between requests.
- No cookies, no logins, no forms, no paywall circumvention.
- We never impersonate Meta's or anyone else's crawler.

**What it does not do**
- It does not test whether your firewall blocks Meta, and it does not crawl articles.

**Contact / opt out:** open an issue in this repository. To stop the homepage fetch, add this
to your robots.txt:

```
User-agent: MetaCrawlerStudy
Disallow: /
```

robots.txt itself is still read once a day, as the robots.txt convention allows.

**Archived copies:** historical robots.txt versions come from the Internet Archive's Wayback
Machine. We use a single connection at no more than 1 request per second.

## Reproduce

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
make all            # == mcs all --snapshot T2
pytest -q
```

| Command | What it does |
|---|---|
| `mcs build-panel` | Builds the sample frame → `data/panel/panel.csv` |
| `mcs fetch-live --label T2 --with-signals` | Live robots.txt / ads.txt / homepage / DNS |
| `mcs render` | Headless-Chromium homepage render (Meta Pixel detection) |
| `mcs fetch-wayback-history --from 2026-09-01` | Wayback versions (T0/T1 are derived from these) |
| `mcs fetch-wayback-homepages` | Homepage fallback for sites that disallow or block us |
| `mcs meta-docs-history` | When Meta's crawler docs first listed each token |
| `mcs parse` | Writes fetches / groups / verdicts / history parquet |
| `mcs signals` | Meta business-tool signals (E1/E2/E2b/E3) |
| `mcs analyze --snapshot T2` | Writes `reports/metrics_T2.json` |
| `mcs report --snapshot T2` | Charts, findings, factsheet, methodology |
| `mcs site` | Static tracker in `site/` |
| `mcs monitor` | Daily run (scheduled in GitHub Actions) |

Scheduled runs live in `.github/workflows/`:
- `t2-launch` — 20 Oct 06:00 UTC
- `wayback` — runs after T2
- `monitor` — daily 06:00 UTC until 20 Nov

Methodology: [`docs/methodology.md`](docs/methodology.md). Deviations from the original spec:
[`docs/DEVIATIONS.md`](docs/DEVIATIONS.md).

## Data
- Raw evidence: `data/raw/`
  - every robots.txt and ads.txt body, gzip, content-addressed by SHA-256;
  - one JSON metadata line per fetch in `data/raw/fetches/`.
- Homepage HTML: kept as workflow artifacts, not in git.
- Domain-level public data covers large news brands (Tier A) only. Regional and local
  publishers appear as aggregates.

robots.txt is a voluntary convention. This study draws no legal conclusions.
