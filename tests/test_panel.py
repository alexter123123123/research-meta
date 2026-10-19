"""Unit tests for the panel builder (no network)."""

from __future__ import annotations

from collections import Counter

import pytest

from mcs.panel import chains, pressgazette as pg
from mcs.panel.normalize import (
    PSL_PATH, institutional_reason, merge_entries, platform_reason, registered, split_newsbrand,
)
from mcs.panel.sample import OTHER, allocate, collapse_groups, stratified_sample

needs_psl = pytest.mark.skipif(not PSL_PATH.exists(), reason="pinned PSL snapshot not downloaded")


# ---------------------------------------------------------------- normalisation
@needs_psl
@pytest.mark.parametrize("inp,exp", [
    ("https://www.bbc.co.uk/news", "bbc.co.uk"),
    ("http://WWW.NYTimes.com/", "nytimes.com"),
    ("news.sky.com", "sky.com"),
    ("finance.yahoo.com", "yahoo.com"),
    ("https://eu.usatoday.com/x?y=1", "usatoday.com"),
    ("mylondon.news", "mylondon.news"),
    ("news.com.au", "news.com.au"),
    ("https://foo.blogspot.com/", "blogspot.com"),  # private PSL section excluded
    ("abcnews.go.com", "go.com"),
    ("", ""),
])
def test_registered_domain(inp, exp):
    assert registered(inp).domain == exp


def test_split_newsbrand():
    assert split_newsbrand("bbc.com + bbc.co.uk") == ["bbc.com", "bbc.co.uk"]
    assert split_newsbrand("abcnews.com (formerly abcnews.go.com)") == ["abcnews.com"]
    assert split_newsbrand("dailymail.com (formerly dailymail.co.uk)") == ["dailymail.com"]
    assert split_newsbrand(" NYTimes.com ") == ["nytimes.com"]


def test_merge_entries_dedupes_and_merges_brands():
    m = merge_entries([
        ("bbc.com", "bbc.com + bbc.co.uk", {"rank": 1}),
        ("BBC.com", "BBC", {"rank": 10}),
        ("bbc.co.uk", "bbc.com + bbc.co.uk", {"rank": 1}),
        ("bbc.co.uk", "bbc.com + bbc.co.uk", {"rank": 99}),
        ("", "nothing", {}),
    ])
    assert list(m) == ["bbc.com", "bbc.co.uk"]
    assert m["bbc.com"].brands == ["bbc.com + bbc.co.uk", "BBC"]
    assert m["bbc.com"].extra == {"rank": 1}  # first seen wins
    assert m["bbc.co.uk"].brands == ["bbc.com + bbc.co.uk"]


# ---------------------------------------------------------------- exclusion rules
def test_platform_exclusions():
    for d in ("facebook.com", "twitter.com", "wordpress.com", "blogspot.com", "substack.com",
              "google.com", "wikipedia.org", "archive.org", "youtube.com", "medium.com", "github.io"):
        assert platform_reason(d), d
    assert "portal" in platform_reason("yahoo.com")
    assert platform_reason("nytimes.com") is None
    assert platform_reason("weather.com") is None  # kept: arguably news


def test_institutional_exclusions():
    assert institutional_reason("arizona.edu", "edu")
    assert institutional_reason("loc.gov", "gov")
    assert institutional_reason("warwick.ac.uk", "ac.uk")
    assert institutional_reason("thetimes.com", "com") is None
    assert institutional_reason("bbc.co.uk", "co.uk") is None


def test_tier_a_exclusion_table():
    for d in ("msn.com", "google.com", "yahoo.com", "aol.com", "substack.com"):
        assert d in pg.TIER_A_EXCLUDE
    assert pg.TIER_A_EXCLUDE["yahoo.com"] == "portal; registered-domain granularity cannot isolate news host"
    for keep in ("people.com", "ign.com", "weather.com", "nytimes.com"):
        assert keep not in pg.TIER_A_EXCLUDE


def test_flag_country():
    assert pg.flag_country(":us:") == "US"
    assert pg.flag_country(":gb:") == "GB"
    assert pg.flag_country(":uk:") == "GB"
    assert pg.flag_country("") == "XX"


def test_datawrapper_ids_and_month():
    html = ('<html><body><p>Oxford Mail grew in August, according to Ipsos.</p>'
            '<iframe src="https://datawrapper.dwcdn.net/AbC12/3/"></iframe>'
            '<iframe src="https://datawrapper.dwcdn.net/AbC12/3/"></iframe>'
            '<iframe data-src="https://datawrapper.dwcdn.net/Zz9yX/2/"></iframe>'
            '<script>{"datePublished":"2026-09-28T15:52:00+00:00"}</script></body></html>')
    assert pg.datawrapper_ids(html) == [("AbC12", "3"), ("Zz9yX", "2")]
    assert pg.data_month_from_text(html) == "2026-08"
    assert pg.data_month_from_headers(["Newsbrand", "September 2026 visits "]) == "2026-09"
    rows = pg.parse_tsv("Newsbrand\tCountry\tx\nnytimes.com\t:us:\t1\n\n")
    assert rows == [{"Newsbrand": "nytimes.com", "Country": ":us:", "x": "1"}]


def test_uk_brand_map_covers_required_examples():
    m = pg.UK_BRAND_MAP
    assert m["BBC"][0] == "bbc.co.uk"
    assert m["The Guardian"][0] == "theguardian.com"
    assert m["Mirror"][0] == "mirror.co.uk"
    assert m["Daily Star"][0] == "dailystar.co.uk"
    assert m["LBC"][0] == "lbc.co.uk"
    assert m["Oxfordmail"][0] == "oxfordmail.co.uk"


# ---------------------------------------------------------------- owner normalisation
@pytest.mark.parametrize("label,exp", [
    ("USA Today Co.", "Gannett/USA Today Co."),
    ("GateHouse Media", "Gannett/USA Today Co."),
    ("Berkshire Hathaway", "Lee Enterprises"),
    ("The McClatchy Company", "McClatchy"),
    ("Digital First Media", "MediaNews/Alden"),
    ("Tribune Publishing", "MediaNews/Alden"),
    ("Retirement Systems of Alabama", "CNHI"),
    ("Archant", "Newsquest"),
    ("Trinity Mirror", "Reach"),
    ("Johnston Press", "National World"),
    ("Daily Mail and General Trust", "DMG Media"),
])
def test_canonical_owner(label, exp):
    assert chains.canonical_owner(label) == exp


def test_resolve_owner_priority_and_unknown():
    assert chains.resolve_owner([]) == chains.UNKNOWN
    assert chains.resolve_owner(["Smith Family Inc.", "Hearst Communications"]) == "Hearst"
    assert chains.resolve_owner(["Smith Family Inc."]) == "Smith Family"


# ---------------------------------------------------------------- sampler
def _frame(n_groups=14, seed=1):
    import random
    rng = random.Random(seed)
    country, owner = {}, {}
    i = 0
    sizes = [400, 200, 120, 80, 60, 40, 30, 25, 15, 12, 8, 5, 3, 2][:n_groups]
    for g, s in enumerate(sizes):
        for _ in range(s):
            d = f"d{i:05d}.com"
            country[d] = "US" if rng.random() < 0.85 else "GB"
            owner[d] = f"G{g:02d}"
            i += 1
    for _ in range(1500):
        d = f"d{i:05d}.com"
        country[d] = "US" if rng.random() < 0.8 else "GB"
        owner[d] = "independent/unknown"
        i += 1
    return country, owner


def test_sampler_deterministic_and_size():
    country, owner = _frame()
    a = stratified_sample(country, owner, n=1400, seed=20261030)
    b = stratified_sample(country, owner, n=1400, seed=20261030)
    c = stratified_sample(country, owner, n=1400, seed=7)
    assert a.selected == b.selected
    assert a.selected != c.selected
    assert len(a.selected) == 1400 and len(set(a.selected)) == 1400
    assert a.sampled and a.n_pre == len(country)


def test_sampler_min_10_per_owner_group():
    country, owner = _frame()
    res = stratified_sample(country, owner, n=300, seed=20261030, min_per_group=10)
    got = Counter(owner[d] for d in res.selected)
    for g in res.top_groups:
        n_g = sum(1 for d in owner if owner[d] == g)
        assert got[g] >= min(10, n_g), (g, got[g])
    assert len(res.selected) == 300
    # groups outside the top 10 collapse into independent/other
    grp, top = collapse_groups(owner)
    assert len(top) == 10 and "independent/unknown" not in top
    assert grp[next(d for d in owner if owner[d] == "G13")] == OTHER


def test_sampler_proportional_when_no_floor_binds():
    sizes = {("US", "A"): 600, ("GB", "A"): 200, ("US", OTHER): 150, ("GB", OTHER): 50}
    alloc = allocate(sizes, 100, min_per_group=10)
    assert alloc == {("US", "A"): 60, ("GB", "A"): 20, ("US", OTHER): 15, ("GB", OTHER): 5}


def test_sampler_no_sampling_below_target():
    country, owner = {"a.com": "US", "b.com": "GB"}, {"a.com": "X", "b.com": "Y"}
    res = stratified_sample(country, owner, n=1400, seed=1)
    assert res.selected == ["a.com", "b.com"] and not res.sampled
