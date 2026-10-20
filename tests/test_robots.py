from pathlib import Path

import pytest

from mcs.parse.robots import is_allowed, parse
from mcs.parse.templates import body_hash
from mcs.parse.tokens import EXACT, NONSTANDARD, PREFIX, match_mode, norm_token
from mcs.parse.verdict import (
    ALLOWED_DEFAULT,
    ALLOWED_EXPLICIT,
    FULL_BLOCK,
    INDETERMINATE,
    PARTIAL_BLOCK,
    WILDCARD_BLOCK,
    WILDCARD_PARTIAL,
    direction,
    verdicts_for_body,
)

FX = Path(__file__).parent / "fixtures" / "robots"
PROBES = ["/", "/news/", "/2026/10/some-article-slug-here/"]


def load(name: str) -> bytes:
    return (FX / name).read_bytes()


def v(name: str, bot: str, probes=PROBES, status="OK"):
    (res,) = verdicts_for_body(load(name), status, [bot], probes)
    return res


def test_01_multi_ua_group():
    for bot in ("gptbot", "meta-externalagent", "ccbot"):
        assert v("01_multi_ua_group.txt", bot).verdict == FULL_BLOCK
    assert v("01_multi_ua_group.txt", "claudebot").verdict == ALLOWED_DEFAULT


def test_02_same_ua_groups_merge():
    r = v("02_same_ua_two_groups.txt", "meta-externalagent")
    assert r.verdict == FULL_BLOCK
    assert len(r.named_raw) == 2


def test_03_allow_overrides_wildcard_disallow():
    assert v("03_allow_overrides_wildcard.txt", "facebookexternalhit").verdict == ALLOWED_EXPLICIT
    assert v("03_allow_overrides_wildcard.txt", "meta-externalagent").verdict == WILDCARD_BLOCK


def test_04_longest_match_and_tie():
    p = parse(load("04_longest_match_tie.txt"))
    rules = p.groups[0].rules
    assert is_allowed(rules, "/news/")[0] is True  # tie -> allow
    assert is_allowed(rules, "/2026/x")[0] is True  # longer allow beats "/"
    assert is_allowed(rules, "/sport/")[0] is False
    r = v("04_longest_match_tie.txt", "meta-externalagent")
    assert r.verdict == PARTIAL_BLOCK


def test_05_wildcards():
    rules = parse(load("05_wildcards.txt")).groups[0].rules
    assert not is_allowed(rules, "/a/b/story.html")[0]
    assert is_allowed(rules, "/a/b/story.html?x=1")[0]  # $ anchors
    assert not is_allowed(rules, "/2026/print")[0]
    assert not is_allowed(rules, "/news")[0]
    assert is_allowed(rules, "/news/")[0]


def test_06_empty_disallow_means_allow():
    assert v("06_empty_disallow.txt", "meta-externalagent").verdict == ALLOWED_EXPLICIT
    assert v("06_empty_disallow.txt", "gptbot").verdict == WILDCARD_BLOCK


def test_07_bom_crlf_tabs_nospace():
    p = parse(load("07_bom_crlf_tabs.txt"))
    assert p.groups[0].agents[0].raw == "meta-externalagent"
    assert v("07_bom_crlf_tabs.txt", "meta-externalagent").verdict == FULL_BLOCK
    assert v("07_bom_crlf_tabs.txt", "gptbot").verdict == ALLOWED_DEFAULT


def test_08_versioned_prefix():
    r = v("08_versioned_prefix.txt", "meta-externalagent")
    assert r.verdict == FULL_BLOCK and r.match_mode == PREFIX
    assert r.protego_agree is False  # Protego does not strip versions; expected disagreement


def test_09_nonstandard_not_counted():
    r = v("09_nonstandard.txt", "meta-externalagent")
    assert r.verdict == ALLOWED_DEFAULT
    assert not r.named and r.match_mode == NONSTANDARD
    assert set(r.nonstandard_raw) == {"meta-external*", "Meta External Agent"}


def test_10_cf_managed_vs_authored():
    p = parse(load("10_cf_managed.txt"))
    assert len(p.cf_ranges) == 1
    a = v("10_cf_managed.txt", "meta-externalagent")
    b = v("10_cf_managed.txt", "meta-externalads")
    assert a.verdict == FULL_BLOCK and a.in_cf_managed_block
    assert b.verdict == FULL_BLOCK and not b.in_cf_managed_block
    assert "cloudflare" in p.generator_hint


def test_11_soft404_detected():
    p = parse(load("11_soft404.txt"))
    assert p.looks_html
    assert v("11_soft404.txt", "meta-externalagent", status="SOFT_404").verdict == ALLOWED_DEFAULT


def test_12_truncation():
    p = parse(load("12_huge.txt"))
    assert p.truncated
    # the Meta group sits after the 500 KiB cut, so it is not seen
    assert v("12_huge.txt", "meta-externalagent").verdict == ALLOWED_DEFAULT


def test_13_sitemap_only():
    p = parse(load("13_sitemap_only.txt"))
    assert not p.groups and len(p.sitemaps) == 2
    assert v("13_sitemap_only.txt", "meta-externalagent").verdict == ALLOWED_DEFAULT


def test_14_comments_between_ua_and_rules():
    assert v("14_comment_between.txt", "meta-externalagent").verdict == FULL_BLOCK


def test_15_content_signal_recorded_not_a_rule():
    p = parse(load("15_content_signal.txt"))
    assert p.content_signals and "ai-train=no" in p.content_signals[0][0]
    assert v("15_content_signal.txt", "meta-externalagent").verdict == ALLOWED_DEFAULT


def test_16_unicode_paths():
    rules = parse(load("16_unicode_paths.txt")).groups[0].rules
    assert not is_allowed(rules, "/nachrichten/über-uns")[0]
    assert not is_allowed(rules, "/nachrichten/%C3%BCber-uns")[0]
    assert not is_allowed(rules, "/café/menu")[0]
    assert is_allowed(rules, "/cafe/")[0]


@pytest.mark.parametrize(
    "raw,mode",
    [
        ("meta-externalagent", EXACT),
        ("Meta-ExternalAgent", EXACT),
        ("meta-externalagent/1.1", PREFIX),
        ("meta-externalagent*", PREFIX),
        ("Meta-External*", NONSTANDARD),
        ("meta external agent", NONSTANDARD),
        ("MetaExternalAgent", NONSTANDARD),
        ("Mozilla/5.0 (compatible; meta-externalagent/1.1)", NONSTANDARD),
        ("meta-externalads", None),
        ("Meta-External", NONSTANDARD),
        ("Meta", NONSTANDARD),
        ("metabot", None),
        ("*", None),
        ("facebookexternalhit", None),
    ],
)
def test_match_mode(raw, mode):
    assert match_mode(raw, "meta-externalagent") == mode


def test_facebook_star_nonstandard():
    assert match_mode("facebook*", "facebookexternalhit") == NONSTANDARD


def test_norm_token():
    assert norm_token("  Meta-ExternalAgent/1.1 (+https://x)") == "meta-externalagent"


def test_wildcard_partial():
    body = b"User-agent: *\nDisallow: /news/\n"
    (r,) = verdicts_for_body(body, "OK", ["meta-externalagent"], PROBES)
    assert r.verdict == WILDCARD_PARTIAL


@pytest.mark.parametrize("status", ["UNREACHABLE_5XX", "RATE_LIMITED_429", "NETWORK_ERROR", "CHALLENGE"])
def test_indeterminate_statuses(status):
    (r,) = verdicts_for_body(b"", status, ["meta-externalagent"], PROBES)
    assert r.verdict == INDETERMINATE


def test_4xx_is_allow_all():
    (r,) = verdicts_for_body(None, "UNAVAILABLE_4XX", ["meta-externalagent"], PROBES)
    assert r.verdict == ALLOWED_DEFAULT


def test_direction():
    assert direction(ALLOWED_DEFAULT, FULL_BLOCK) == "more_restrictive"
    assert direction(FULL_BLOCK, WILDCARD_BLOCK) == "less_restrictive"
    assert direction(PARTIAL_BLOCK, PARTIAL_BLOCK) == "same"
    assert direction(INDETERMINATE, FULL_BLOCK) is None
    assert direction(WILDCARD_PARTIAL, PARTIAL_BLOCK) == "more_restrictive"


def test_body_hash_ignores_comments_and_sitemaps():
    a = b"# site A\nUser-agent: *\nDisallow: /x\nSitemap: https://a.com/s.xml\n"
    b = b"User-Agent:   *\r\nDisallow: /x  # note\r\nSitemap: https://b.com/s.xml\r\n"
    assert body_hash(a) == body_hash(b)


def test_protego_agrees_on_standard_files():
    for name in ["01_multi_ua_group.txt", "02_same_ua_two_groups.txt",
                 "03_allow_overrides_wildcard.txt", "05_wildcards.txt", "06_empty_disallow.txt",
                 "07_bom_crlf_tabs.txt", "10_cf_managed.txt", "14_comment_between.txt"]:
        for bot in ("meta-externalagent", "meta-externalads", "gptbot", "facebookexternalhit"):
            assert v(name, bot).protego_agree, (name, bot)


def test_challenge_markers_cover_device_verification_pages():
    from mcs.fetch.challenge import is_challenge
    page = b"<!DOCTYPE html><html><head><title>Verifying Device</title></head><body>" \
           b"<div class='text'>Verifying your device, please wait</div></body></html>"
    assert is_challenge(page, "text/html")
    assert not is_challenge(b"User-agent: *\nDisallow: /captcha/\n", "text/plain")
