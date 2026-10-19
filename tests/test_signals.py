import json

from mcs.signals import (
    combine_signals,
    extract_homepage_signals,
    gtm_has_meta_pixel,
    parse_ads_txt,
    parse_dns_txt,
)
from mcs.signals.homepage import classify_social_link

URL = "https://www.example-news.com/"

PIXEL_SINGLE = """<!doctype html><html><head>
<meta name="facebook-domain-verification" content="abc123xyz" />
<script>
!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){};t=b.createElement(e);
t.src=v;s.parentNode.insertBefore(t,s)}(window, document,'script',
'https://connect.facebook.net/en_US/fbevents.js');
fbq('init', '123456789012345');
fbq('track', 'PageView');
</script>
<noscript><img height="1" width="1" style="display:none"
src="https://www.facebook.com/tr?id=123456789012345&ev=PageView&noscript=1"/></noscript>
</head><body></body></html>"""

PIXEL_MINIFIED = (
    '<script>fbq("init","998877665544");fbq("init", "112233445566",{em:"x"});'
    'var u="https:\\/\\/connect.facebook.net\\/de_DE\\/fbevents.js";</script>'
)

NOSCRIPT_ONLY = (
    '<html><body><noscript><img src="https://www.facebook.com/tr?ev=PageView&amp;'
    'id=555444333222&amp;noscript=1"></noscript></body></html>'
)

LINKS = """<html><head>
<meta property="fb:pages" content="1111111111" />
<meta property="fb:app_id" content="2222222222" />
</head><body>
<a href="https://www.facebook.com/sharer/sharer.php?u=https://x">Share</a>
<a href="https://www.facebook.com/share.php?u=x">Share2</a>
<a href="https://www.facebook.com/dialog/share?app_id=1">Dialog</a>
<a href="https://www.facebook.com/plugins/like.php">Like</a>
<a href="https://www.facebook.com/policies/cookies/">Policy</a>
<a href="https://www.facebook.com/privacy/explanation">Privacy</a>
<a href="https://www.facebook.com/help/123">Help</a>
<a href="https://www.facebook.com/events/999/">Event</a>
<a href="https://www.facebook.com/login.php">Login</a>
<a href="https://www.facebook.com/groups/localreaders/">Group</a>
<a href="https://instagram.com/accounts/login/">IG login</a>
</body></html>"""


def test_pixel_single_quotes_and_meta_tag():
    s = extract_homepage_signals(PIXEL_SINGLE, URL)
    assert s["e1_meta_tag"] is True
    assert s["e1_meta_tag_values"] == ["abc123xyz"]
    assert s["e2_pixel"] is True
    assert s["fbevents_js"] is True
    assert s["pixel_ids"] == ["123456789012345"]


def test_pixel_double_quotes_minified_escaped_slashes():
    s = extract_homepage_signals(PIXEL_MINIFIED, URL)
    assert s["e2_pixel"] is True
    assert s["pixel_ids"] == ["998877665544", "112233445566"]
    assert s["fbevents_js"] is True


def test_pixel_noscript_img_id_not_first_param():
    s = extract_homepage_signals(NOSCRIPT_ONLY, URL)
    assert s["e2_pixel"] is True
    assert s["pixel_ids"] == ["555444333222"]


def test_fbevents_only_counts_as_pixel():
    html = '<script async src="//connect.facebook.net/en_GB/fbevents.js"></script>'
    s = extract_homepage_signals(html, URL)
    assert s["e2_pixel"] is True and s["pixel_ids"] == []


def test_no_pixel_on_plain_page():
    s = extract_homepage_signals("<html><body><p>facebook is a site</p></body></html>", URL)
    assert not s["e2_pixel"] and not s["e1_meta_tag"]
    assert not s["e3_fb_link"] and not s["e3_ig_link"]
    assert s["gtm_ids"] == []


def test_share_links_excluded_group_flag_and_meta_props():
    s = extract_homepage_signals(LINKS, URL)
    assert s["e3_fb_link"] is False
    assert s["e3_ig_link"] is False
    assert s["e3_fb_group"] is True
    assert s["fb_pages_meta"] == ["1111111111"]
    assert s["fb_app_id"] == ["2222222222"]


def test_profile_links_detected():
    html = """<footer>
    <a href="https://www.facebook.com/ExampleNews">FB</a>
    <a href='//instagram.com/examplenews/'>IG</a>
    <a href="https://m.facebook.com/profile.php?id=10001">FB2</a>
    </footer>"""
    s = extract_homepage_signals(html, URL)
    assert s["e3_fb_link"] and s["e3_ig_link"]
    assert len(s["fb_links"]) == 2


def test_classify_social_link():
    assert classify_social_link("https://www.facebook.com/tr?id=1") is None
    assert classify_social_link("https://facebook.com/sharer.php?u=x") is None
    assert classify_social_link("https://www.facebook.com/pages/Example/123") == "fb"
    assert classify_social_link("https://www.facebook.com/groups/abc") == "fb_group"
    assert classify_social_link("https://notfacebook.com/page") is None
    assert classify_social_link("https://www.instagram.com/explore/tags/x") is None
    assert classify_social_link("https://www.instagram.com/thepaper") == "ig"
    assert classify_social_link("/facebook.com/page", URL) is None


def test_gtm_ids():
    html = ("<script>(function(w,d,s,l,i){})(window,document,'script','dataLayer',"
            "'GTM-ABC1234');</script><iframe src=\"https://www.googletagmanager.com/ns.html"
            "?id=GTM-ABC1234\"></iframe><script>gtm('GTM-ZZ99YY')</script>")
    s = extract_homepage_signals(html, URL)
    assert s["gtm_ids"] == ["GTM-ABC1234", "GTM-ZZ99YY"]


def test_dns_txt_quoted_and_split():
    r = parse_dns_txt(['"v=spf1 include:_spf.google.com ~all"',
                       '"facebook-domain-verification=" "q1w2e3r4t5"'])
    assert r["e1_dns_txt"] is True
    assert r["dns_verification_codes"] == ["q1w2e3r4t5"]
    r2 = parse_dns_txt(["facebook-domain-verification=zzz"])
    assert r2["dns_verification_codes"] == ["zzz"]
    assert parse_dns_txt(['"google-site-verification=abc"'])["e1_dns_txt"] is False
    assert parse_dns_txt([])["e1_dns_txt"] is False


def test_ads_txt():
    text = ("# ads.txt\r\ngoogle.com, pub-1, DIRECT, f08c47fec0942fa0\r\n"
            "  Facebook.com , 123456789, RESELLER # audience network\r\n")
    r = parse_ads_txt(text)
    assert r["e2b_adstxt"] is True
    assert r["adstxt_facebook_ids"] == ["123456789"]
    assert parse_ads_txt("# facebook.com, 1, DIRECT\n")["e2b_adstxt"] is False
    assert parse_ads_txt("ads.facebook.com, 1, DIRECT\n")["e2b_adstxt"] is False
    soft = parse_ads_txt("<!DOCTYPE html><html><body>facebook.com, 1, DIRECT</body></html>")
    assert soft["e2b_adstxt"] is False and soft["adstxt_html"] is True
    assert parse_ads_txt(None)["e2b_adstxt"] is False


def test_gtm_has_meta_pixel():
    assert gtm_has_meta_pixel('var a="https://connect.facebook.net/en_US/fbevents.js";')
    assert gtm_has_meta_pixel('img.src="https:\\/\\/www.facebook.com\\/tr?id=1"')
    assert not gtm_has_meta_pixel('var a="https://www.google-analytics.com/analytics.js";')
    assert not gtm_has_meta_pixel("")


def test_combine_levels():
    raw = extract_homepage_signals("<a href='https://facebook.com/paper'>f</a>", URL)
    rendered = extract_homepage_signals(PIXEL_MINIFIED, URL)
    row = combine_signals("example-news.com", raw, rendered, parse_dns_txt([]),
                          parse_ads_txt(""), {}, "live", "f1")
    assert row["meta_linked_level"] == "E2"
    assert row["e2_pixel"] and row["e3_fb_link"] and not row["e2_gtm"]
    assert json.loads(row["pixel_ids"]) == ["998877665544", "112233445566"]

    # GTM only counts when no direct pixel
    gtm_html = extract_homepage_signals("<script>'GTM-ABCD12'</script>", URL)
    row = combine_signals("a.com", gtm_html, None, None, None, {"GTM-ABCD12": True}, "live", "f")
    assert row["e2_gtm"] and row["meta_linked_level"] == "E2-GTM"
    row = combine_signals("a.com", rendered, None, None, None, {"GTM-ABCD12": True}, "live", "f")
    assert not row["e2_gtm"] and row["meta_linked_level"] == "E2"

    # ads.txt alone -> E2 level, flag kept separately
    row = combine_signals("a.com", None, None, None, parse_ads_txt("facebook.com, 1, DIRECT"),
                          None, None, None)
    assert row["meta_linked_level"] == "E2" and row["e2b_adstxt"] and not row["e2_pixel"]

    # DNS verification -> E1
    row = combine_signals("a.com", raw, None, parse_dns_txt(['"facebook-domain-verification=x"']),
                          None, None, "wayback", "f")
    assert row["meta_linked_level"] == "E1" and row["e1_dns_txt"]

    # fb:app_id only -> E3; nothing -> none
    meta_only = extract_homepage_signals('<meta property="fb:app_id" content="9">', URL)
    assert combine_signals("a.com", meta_only, None, None, None, None, "live",
                           "f")["meta_linked_level"] == "E3"
    assert combine_signals("a.com", None, None, None, None, None, None,
                           None)["meta_linked_level"] == "none"
