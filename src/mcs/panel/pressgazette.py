"""Tier A: Press Gazette monthly Similarweb / Ipsos rankings (SPEC §4.1).

The ranking articles are evergreen URLs whose tables are Datawrapper iframes. The Datawrapper
IDs are discovered at runtime from the (cached) article HTML; each chart's data is read from
``https://datawrapper.dwcdn.net/<ID>/<ver>/dataset.csv`` (tab-separated).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date

from selectolax.lexbor import LexborHTMLParser

from mcs.panel.http import PoliteClient, RobotsDisallowed, safe_name
from mcs.panel.normalize import registered_domain, split_newsbrand

PG = "https://pressgazette.co.uk"
BASE = PG + "/media-audience-and-business-data/media_metrics/"

LISTS = [
    # key, slug, source_list prefix, list country (None = from flag column)
    ("us", "most-popular-websites-news-us-monthly-3", "pg_us_top50", "US"),
    ("uk", "most-popular-websites-news-uk-monthly-2", "pg_uk_top50", "GB"),
    ("world", "most-popular-websites-news-world-monthly-2", "pg_world_top50", None),
]

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
_MONTH_RE = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(20\d\d)\b", re.I)

# Tier A exclusions (registered domain -> reason). Every exclusion is written to
# panel_exclusions.csv; judgement calls are flagged in the reason text.
TIER_A_EXCLUDE = {
    "msn.com": "aggregator/portal (MSN)",
    "google.com": "aggregator (Google News); portal registered domain",
    "yahoo.com": "portal; registered-domain granularity cannot isolate news host",
    "aol.com": "portal; registered-domain granularity cannot isolate news host",
    "sky.com": "portal; registered-domain granularity cannot isolate news host (news.sky.com "
               "is Sky News, but sky.com is Sky's consumer/telecoms site)",
    "substack.com": "newsletter hosting platform, not a publisher",
    "newsbreak.com": "news aggregator app (judgement call)",
    "drudgereport.com": "headline aggregator linking to third-party reporting (judgement call)",
    "go.com": "portal; registered-domain granularity cannot isolate news host",
}

# Curated brand -> domain map for the UK list (brand names only in the source).
# note 'known' = curated from knowledge; verification by homepage <title> is added at build time.
UK_BRAND_MAP: dict[str, tuple[str, str]] = {
    "BBC": ("bbc.co.uk", "BBC"),
    "The Guardian": ("theguardian.com", "Guardian"),
    "The Sun": ("thesun.co.uk", "Sun"),
    "Mirror": ("mirror.co.uk", "Mirror"),
    "The Independent": ("independent.co.uk", "Independent"),
    "Sky News": ("news.sky.com", "Sky News"),
    "Yahoo!": ("uk.yahoo.com", "Yahoo"),
    "Daily Express": ("express.co.uk", "Express"),
    "Daily Mail": ("dailymail.co.uk", "Daily Mail"),
    "The Telegraph": ("telegraph.co.uk", "Telegraph"),
    "ITV": ("itv.com", "ITV"),
    "Money Saving Expert": ("moneysavingexpert.com", "MoneySavingExpert"),
    "Times & Sunday Times": ("thetimes.com", "Times"),
    "Metro": ("metro.co.uk", "Metro"),
    "Good Food (Previously BBC Good Food)": ("bbcgoodfood.com", "Good Food"),
    "Manchester Evening News": ("manchestereveningnews.co.uk", "Manchester Evening News"),
    "The Standard": ("standard.co.uk", "Standard"),
    "Daily Star": ("dailystar.co.uk", "Daily Star"),
    "Birmingham Live": ("birminghammail.co.uk", "Birmingham"),
    "New York Times": ("nytimes.com", "New York Times"),
    "Liverpool Echo": ("liverpoolecho.co.uk", "Liverpool Echo"),
    "Wales Online": ("walesonline.co.uk", "Wales"),
    "The i Paper": ("inews.co.uk", "i Paper"),
    "Oxfordmail": ("oxfordmail.co.uk", "Oxford Mail"),
    "Channel4": ("channel4.com", "Channel 4"),
    "Hello! Magazine": ("hellomagazine.com", "HELLO"),
    "Good Housekeeping": ("goodhousekeeping.com", "Good Housekeeping"),
    "Daily Record": ("dailyrecord.co.uk", "Daily Record"),
    "Radio Times": ("radiotimes.com", "Radio Times"),
    "GB News": ("gbnews.com", "GB News"),
    "Examiner Live": ("examinerlive.co.uk", "Examiner|YorkshireLive"),
    "People.com": ("people.com", "People"),
    "Digital Spy": ("digitalspy.com", "Digital Spy"),
    "Cosmopolitan": ("cosmopolitan.com", "Cosmopolitan"),
    "Which?": ("which.co.uk", "Which?"),
    "Substack": ("substack.com", "Substack"),
    "Healthline Media": ("healthline.com", "Healthline"),
    "Forbes": ("forbes.com", "Forbes"),
    "MyLondon": ("mylondon.news", "MyLondon"),
    "Irish Mirror": ("irishmirror.ie", "Irish Mirror"),
    "Reuters News": ("reuters.com", "Reuters"),
    "Chronicle Live": ("chroniclelive.co.uk", "Chronicle"),
    "Screenrant": ("screenrant.com", "Screen Rant"),
    "Herald Scotland": ("heraldscotland.com", "Herald"),
    "Financial Times": ("ft.com", "Financial Times"),
    "Indiatimes": ("indiatimes.com", "India Times"),
    "IGN": ("ign.com", "IGN"),
    "TechRadar": ("techradar.com", "TechRadar"),
    "The Scotsman": ("scotsman.com", "Scotsman"),
    "LBC": ("lbc.co.uk", "LBC"),
}

# UK-list brands that are not UK publishers (the list is "UK audience", not "UK publisher").
UK_COUNTRY_OVERRIDES = {"nytimes.com": "US", "people.com": "US", "forbes.com": "US",
                        "reuters.com": "GB", "indiatimes.com": "IN", "ign.com": "US",
                        "healthline.com": "US", "screenrant.com": "CA", "irishmirror.ie": "IE"}

# Source-data corrections (flag code in the source is wrong). Logged in panel_meta.json.
COUNTRY_CORRECTIONS = {"rediff.com": ("IN", "source flag :ru: is wrong; Rediff is Indian")}


@dataclass
class TierARow:
    domain: str
    brand: str
    country: str
    source_list: str
    source_rank: int
    source_url: str
    note: str = ""


@dataclass
class PGResult:
    rows: list[TierARow] = field(default_factory=list)
    exclusions: list[dict] = field(default_factory=list)
    lists: list[dict] = field(default_factory=list)
    uk_map: list[dict] = field(default_factory=list)
    anylang: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def article_url(slug: str) -> str:
    return BASE + slug + "/"


def fetch_article(client: PoliteClient, slug: str) -> tuple[str | None, dict]:
    try:
        body, meta = client.get(article_url(slug), f"pressgazette/{slug}.html")
    except RobotsDisallowed:
        return None, {"error": "robots disallow"}
    except Exception as e:  # network
        return None, {"error": repr(e)}
    if meta.get("status") != 200:
        return None, meta
    return body.decode("utf-8", errors="replace"), meta


def datawrapper_ids(html: str) -> list[tuple[str, str]]:
    """Ordered (id, version) pairs from iframe src attributes."""
    tree = LexborHTMLParser(html)
    out: list[tuple[str, str]] = []
    for node in tree.css("iframe"):
        src = node.attributes.get("src") or node.attributes.get("data-src") or ""
        m = re.search(r"datawrapper\.dwcdn\.net/([A-Za-z0-9]{5})/(\d+)", src)
        if m and (m.group(1), m.group(2)) not in out:
            out.append((m.group(1), m.group(2)))
    return out


def fetch_dataset(client: PoliteClient, dw_id: str, ver: str) -> list[dict]:
    url = f"https://datawrapper.dwcdn.net/{dw_id}/{ver}/dataset.csv"
    body, meta = client.get(url, f"datawrapper/{dw_id}_{ver}_dataset.csv")
    if meta.get("status") != 200:
        raise RuntimeError(f"datawrapper {url}: HTTP {meta.get('status')}")
    return parse_tsv(body.decode("utf-8-sig", errors="replace"))


def parse_tsv(text: str) -> list[dict]:
    rdr = csv.reader(io.StringIO(text), delimiter="\t")
    rows = list(rdr)
    if not rows:
        return []
    hdr = [h.strip() for h in rows[0]]
    return [{hdr[i]: (r[i].strip() if i < len(r) else "") for i in range(len(hdr)) if hdr[i]}
            for r in rows[1:] if any(c.strip() for c in r)]


def data_month_from_headers(headers: list[str]) -> str | None:
    for h in headers:
        m = _MONTH_RE.search(h)
        if m:
            return f"{m.group(2)}-{MONTHS.index(m.group(1).lower()) + 1:02d}"
    return None


def published_date(html: str) -> date | None:
    m = re.search(r'"datePublished"\s*:\s*"(\d{4})-(\d{2})-(\d{2})', html)
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def data_month_from_text(html: str) -> str | None:
    """Infer the data month from the article lead ('... in August, according to ...')."""
    pub = published_date(html)
    tree = LexborHTMLParser(html)
    for p in tree.css("article p, .entry-content p, main p, p"):
        t = p.text(strip=True)
        m = _MONTH_RE.search(t)
        if m:
            return f"{m.group(2)}-{MONTHS.index(m.group(1).lower()) + 1:02d}"
        m = re.search(r"\bin (" + "|".join(MONTHS) + r")\b", t, re.I)
        if m and pub:
            mon = MONTHS.index(m.group(1).lower()) + 1
            year = pub.year if mon <= pub.month else pub.year - 1
            return f"{year}-{mon:02d}"
    return None


def flag_country(code: str) -> str:
    c = (code or "").strip().strip(":").upper()
    if c == "UK":
        c = "GB"
    return c if re.fullmatch(r"[A-Z]{2}", c) else "XX"


def pick_ranked_table(client: PoliteClient, ids: list[tuple[str, str]],
                      want: tuple[str, ...]) -> tuple[tuple[str, str], list[dict]] | None:
    """First dataset with >=40 rows whose header contains all `want` columns."""
    for dw_id, ver in ids:
        try:
            data = fetch_dataset(client, dw_id, ver)
        except Exception:
            continue
        if not data:
            continue
        cols = {c.strip().lower() for c in data[0].keys()}
        if all(w.lower() in cols for w in want) and len(data) >= 40:
            return (dw_id, ver), data
    return None


def _excl(domain: str, source_list: str, reason: str, brand: str = "") -> dict:
    return {"domain": domain, "source_list": source_list, "reason": reason, "brand": brand}


def build_tier_a(client: PoliteClient, verify_uk=None) -> PGResult:
    """verify_uk: optional callable(domain, expect) -> note string (homepage title check)."""
    res = PGResult()
    for key, slug, prefix, list_country in LISTS:
        url = article_url(slug)
        html, meta = fetch_article(client, slug)
        if html is None:
            res.problems.append(f"{key}: article unavailable ({meta}); list skipped")
            res.lists.append({"key": key, "url": url, "error": str(meta)})
            continue
        ids = datawrapper_ids(html)
        if key == "uk":
            picked = pick_ranked_table(client, ids, ("Newsbrand", "Audience"))
        else:
            picked = pick_ranked_table(client, ids, ("Newsbrand", "Country"))
        if not picked:
            res.problems.append(f"{key}: no ranked Datawrapper table among {ids}")
            continue
        (dw_id, ver), data = picked
        month = data_month_from_headers(list(data[0].keys())) or data_month_from_text(html)
        if not month:
            res.problems.append(f"{key}: data month not found")
            month = "unknown"
        source_list = f"{prefix}_{month}"
        res.lists.append({"key": key, "url": url, "datawrapper": f"{dw_id}/{ver}",
                          "datawrapper_ids_on_page": [f"{a}/{b}" for a, b in ids],
                          "data_month": month, "source_list": source_list, "n_rows": len(data),
                          "article_published": str(published_date(html))})
        bcol = next(c for c in data[0] if c.strip().lower() == "newsbrand")
        for rank, row in enumerate(data, start=1):
            brand = row[bcol].strip()
            if key == "uk":
                if brand not in UK_BRAND_MAP:
                    res.problems.append(f"uk: brand not in curated map: {brand!r}")
                    res.uk_map.append({"brand": brand, "domain": "", "note": "UNMAPPED"})
                    continue
                host, expect = UK_BRAND_MAP[brand]
                note = verify_uk(host, expect) if verify_uk else "curated (known)"
                res.uk_map.append({"brand": brand, "domain": host, "note": note})
                hosts = [host]
                country = list_country
            else:
                hosts = split_newsbrand(brand)
                country = flag_country(row.get("Country", ""))
            for h in hosts:
                dom = registered_domain(h)
                if not dom:
                    res.exclusions.append(_excl(h, source_list, "no registered domain", brand))
                    continue
                c = country
                if key == "uk" and dom in UK_COUNTRY_OVERRIDES:
                    c = UK_COUNTRY_OVERRIDES[dom]
                if dom in COUNTRY_CORRECTIONS:
                    c = COUNTRY_CORRECTIONS[dom][0]
                if dom in TIER_A_EXCLUDE:
                    res.exclusions.append(_excl(dom, source_list, TIER_A_EXCLUDE[dom] + f" [host {h}]", brand))
                    continue
                res.rows.append(TierARow(dom, brand, c, source_list, rank, url))
    res.anylang = find_anylang(client)
    return res


# ---------------------------------------------------------------------------------------------
# "World's biggest news websites in any language" (June 2026 edition) via sitemaps
# ---------------------------------------------------------------------------------------------

ANYLANG_PATTERNS = [r"biggest-news-websites", r"any-language", r"top-50-news-websites-in-the-world",
                    r"world.*language", r"language.*world"]


def find_anylang(client: PoliteClient, max_post_sitemaps: int = 15) -> dict:
    """Search Press Gazette sitemaps (never its /?s= search, which robots.txt disallows)."""
    out: dict = {"searched": [], "found": False, "candidates": []}
    idx_url = PG + "/sitemap_index.xml"
    try:
        body, meta = client.get(idx_url, "pressgazette/sitemap_index.xml")
    except Exception as e:
        out["error"] = f"sitemap_index fetch failed: {e!r}"
        return out
    if meta.get("status") != 200:
        out["error"] = f"sitemap_index HTTP {meta.get('status')} (pressgazette.co.uk refuses our client)"
        return out
    out["searched"].append(idx_url)
    sitemaps = re.findall(r"<loc>\s*(.*?)\s*</loc>", body.decode("utf-8", "replace"))
    posts = [s for s in sitemaps if re.search(r"post-sitemap\d*\.xml", s)]
    posts.sort(key=lambda s: int(re.search(r"post-sitemap(\d*)", s).group(1) or 1), reverse=True)
    cands = [PG + "/news-sitemap.xml"] + posts[:max_post_sitemaps]
    for sm in cands:
        try:
            b, m = client.get(sm, "pressgazette/" + safe_name(sm.rsplit("/", 1)[-1]))
        except Exception as e:
            out.setdefault("errors", []).append(f"{sm}: {e!r}")
            continue
        if m.get("status") != 200:
            out.setdefault("errors", []).append(f"{sm}: HTTP {m.get('status')}")
            continue
        out["searched"].append(sm)
        for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", b.decode("utf-8", "replace")):
            if any(re.search(p, loc) for p in ANYLANG_PATTERNS):
                out["candidates"].append(loc)
    jun = [c for c in out["candidates"] if "june" in c or "2026" in c]
    if jun:
        out["found"] = True
        out["url"] = jun[0]
    return out


# Curated owner groups for Tier A brands (large brands whose ownership is well known).
# Precedence in build: this map > Wikidata P127/P749 > independent/unknown.
TIER_A_OWNERS = {
    # UK groups
    "mirror.co.uk": "Reach", "express.co.uk": "Reach", "dailystar.co.uk": "Reach",
    "manchestereveningnews.co.uk": "Reach", "liverpoolecho.co.uk": "Reach",
    "walesonline.co.uk": "Reach", "birminghammail.co.uk": "Reach", "dailyrecord.co.uk": "Reach",
    "examinerlive.co.uk": "Reach", "mylondon.news": "Reach", "irishmirror.ie": "Reach",
    "chroniclelive.co.uk": "Reach",
    "dailymail.co.uk": "DMG Media", "dailymail.com": "DMG Media", "metro.co.uk": "DMG Media",
    "inews.co.uk": "DMG Media", "newscientist.com": "DMG Media",
    "thesun.co.uk": "News UK", "the-sun.com": "News UK", "thetimes.com": "News UK",
    "thetimes.co.uk": "News UK",
    "oxfordmail.co.uk": "Newsquest", "heraldscotland.com": "Newsquest",
    "scotsman.com": "National World",
    "theguardian.com": "Guardian Media Group",
    "telegraph.co.uk": "Telegraph Media Group",
    "bbc.co.uk": "BBC", "bbc.com": "BBC",
    "lbc.co.uk": "Global", "gbnews.com": "GB News",
    "itv.com": "ITV", "channel4.com": "Channel 4",
    "radiotimes.com": "Immediate Media", "bbcgoodfood.com": "Immediate Media",
    "techradar.com": "Future", "digitalspy.com": "Hearst", "cosmopolitan.com": "Hearst",
    "goodhousekeeping.com": "Hearst", "hellomagazine.com": "Hello!",
    "moneysavingexpert.com": "MoneySupermarket Group", "which.co.uk": "Which?",
    "standard.co.uk": "Evening Standard Ltd", "independent.co.uk": "Independent Digital News & Media",
    "ft.com": "Nikkei",
    # US / international
    "nytimes.com": "New York Times Co.", "wsj.com": "News Corp", "nypost.com": "News Corp",
    "foxnews.com": "Fox Corporation", "cnn.com": "Warner Bros. Discovery",
    "usatoday.com": "Gannett/USA Today Co.", "people.com": "People Inc. (IAC)",
    "cnbc.com": "NBCUniversal", "nbcnews.com": "NBCUniversal", "abcnews.com": "Disney",
    "cbsnews.com": "Paramount", "washingtonpost.com": "Nash Holdings",
    "latimes.com": "California Times", "sfgate.com": "Hearst", "al.com": "Advance",
    "businessinsider.com": "Axel Springer", "politico.com": "Axel Springer",
    "huffpost.com": "BuzzFeed", "buzzfeed.com": "BuzzFeed", "variety.com": "Penske Media",
    "thehill.com": "Nexstar", "theatlantic.com": "Emerson Collective",
    "bloomberg.com": "Bloomberg L.P.", "reuters.com": "Thomson Reuters",
    "apnews.com": "Associated Press", "npr.org": "NPR",
    "ign.com": "Ziff Davis", "healthline.com": "RVO Health", "screenrant.com": "Valnet",
    "indiatimes.com": "Times Group", "aljazeera.com": "Al Jazeera Media Network",
    "ksl.com": "Deseret Management Corp.", "patch.com": "Patch Media",
    "mensjournal.com": "Arena Group", "usnews.com": "U.S. News & World Report",
    "newsweek.com": "Newsweek Digital", "forbes.com": "Forbes Media",
    "axios.com": "Cox", "breitbart.com": "Breitbart News Network",
    "newsmax.com": "Newsmax Media",
    # world list (non-US/UK)
    "ndtv.com": "NDTV (Adani Group)", "hindustantimes.com": "HT Media", "news18.com": "Network18",
    "indianexpress.com": "Indian Express Group", "thehindu.com": "The Hindu Group",
    "indiatoday.in": "India Today Group", "india.com": "Zee Media", "oneindia.com": "Greynium",
    "rediff.com": "Rediff.com India", "cbc.ca": "CBC/Radio-Canada",
    "abc.net.au": "Australian Broadcasting Corporation", "news.com.au": "News Corp",
    "euronews.com": "Euronews",
}
