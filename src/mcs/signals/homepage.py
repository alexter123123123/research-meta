"""Homepage / DNS signal extraction and combination into the `signals` row (SPEC §8, §9).

All functions are pure (no network). Language rule (§11): these are *signals of Meta
business-tool use*, never evidence that a site "has a business account".
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import pandas as pd
from selectolax.lexbor import LexborHTMLParser

from mcs.signals.pixel import find_gtm_ids, find_pixel_ids, has_fbevents, has_pixel

LEVELS = ["E1", "E2", "E2-GTM", "E3", "none"]  # strongest first

# First path segment values that are share/intent/plugin/meta-corporate URLs, not profiles.
FB_EXCLUDE = {
    "sharer", "sharer.php", "share", "share.php", "dialog", "plugins", "tr", "login",
    "login.php", "policies", "policy", "policy.php", "privacy", "help", "events", "legal",
    "terms", "terms.php", "hashtag", "home.php", "v2.0", "v3.0", "business", "about",
    "settings", "watch", "photo.php", "story.php", "permalink.php", "l.php", "ads",
    "fbml", "connect", "x", "",
}
IG_EXCLUDE = {
    "sharer", "share", "dialog", "plugins", "tr", "login", "accounts", "policies", "privacy",
    "help", "events", "legal", "about", "explore", "developer", "terms", "web", "direct", "",
}
_DNS_TOKEN = "facebook-domain-verification="
_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
_META_VERIF_RE = re.compile(
    r"""<meta[^>]+name\s*=\s*["']?facebook-domain-verification["']?[^>]*>""", re.I)
_CONTENT_RE = re.compile(r"""content\s*=\s*["']([^"']*)["']""", re.I)


def _host_kind(host: str) -> str | None:
    h = host.lower().rstrip(".")
    if h == "facebook.com" or h.endswith(".facebook.com") or h in {"fb.com", "www.fb.com"}:
        return "fb"
    if h == "instagram.com" or h.endswith(".instagram.com") or h == "instagr.am":
        return "ig"
    return None


def classify_social_link(href: str, page_url: str = "") -> str | None:
    """Return 'fb', 'fb_group', 'ig' for a profile/page link, else None (share links etc.)."""
    if not href:
        return None
    href = href.strip()
    if href.startswith(("javascript:", "mailto:", "#", "tel:")):
        return None
    try:
        url = urljoin(page_url or "https://example.invalid/", href)
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    kind = _host_kind(parts.hostname or "")
    if kind is None:
        return None
    host = (parts.hostname or "").lower()
    if kind == "fb" and (host.startswith("connect.") or host.startswith("developers.")):
        return None
    segs = [s for s in parts.path.split("/") if s]
    first = segs[0].lower() if segs else ""
    if kind == "fb":
        if first == "groups":
            return "fb_group" if len(segs) > 1 else None
        if first == "profile.php":
            return "fb" if "id=" in parts.query else None
        if first == "pages" and len(segs) > 1:
            return "fb"
        if first in FB_EXCLUDE or first.startswith(("sharer", "share")):
            return None
        return "fb"
    if first in IG_EXCLUDE or first.startswith("share"):
        return None
    return "ig"


def _meta_values(tree: LexborHTMLParser, attr: str, value: str) -> list[str]:
    out: list[str] = []
    for node in tree.css("meta"):
        attrs = node.attributes
        v = (attrs.get(attr) or "").strip().lower()
        if v == value:
            c = (attrs.get("content") or "").strip()
            if c and c not in out:
                out.append(c)
    return out


def extract_homepage_signals(html: str, page_url: str) -> dict:
    """Extract E1 (meta tag), E2 (pixel), GTM ids and E3 (FB/IG links, fb:pages, fb:app_id)."""
    html = html or ""
    tree = LexborHTMLParser(html) if html.strip() else None

    verif: list[str] = []
    fb_pages: list[str] = []
    fb_app: list[str] = []
    fb_links: list[str] = []
    ig_links: list[str] = []
    fb_groups: list[str] = []
    if tree is not None:
        verif = _meta_values(tree, "name", "facebook-domain-verification")
        fb_pages = _meta_values(tree, "property", "fb:pages") + [
            v for v in _meta_values(tree, "name", "fb:pages")]
        fb_app = _meta_values(tree, "property", "fb:app_id") + [
            v for v in _meta_values(tree, "name", "fb:app_id")]
        for a in tree.css("a"):
            href = a.attributes.get("href") or ""
            kind = classify_social_link(href, page_url)
            target = {"fb": fb_links, "ig": ig_links, "fb_group": fb_groups}.get(kind or "")
            if target is not None and href not in target:
                target.append(href)
    # regex fallback for malformed markup the parser may drop
    if not verif:
        for m in _META_VERIF_RE.finditer(html):
            c = _CONTENT_RE.search(m.group(0))
            if c and c.group(1).strip():
                verif.append(c.group(1).strip())
    pixel_ids = find_pixel_ids(html)
    fbevents = has_fbevents(html)
    return {
        "e1_meta_tag": bool(verif),
        "e1_meta_tag_values": verif,
        "e2_pixel": has_pixel(html),
        "fbevents_js": fbevents,
        "pixel_ids": pixel_ids,
        "gtm_ids": find_gtm_ids(html),
        "e3_fb_link": bool(fb_links),
        "e3_ig_link": bool(ig_links),
        "e3_fb_group": bool(fb_groups),
        "fb_links": fb_links[:20],
        "ig_links": ig_links[:20],
        "fb_pages_meta": list(dict.fromkeys(fb_pages)),
        "fb_app_id": list(dict.fromkeys(fb_app)),
    }


def _txt_value(record: str) -> str:
    """Join a TXT record's character-strings ('"a" "b"' -> 'ab'); unquoted records pass through."""
    r = (record or "").strip()
    chunks = _QUOTED.findall(r)
    if chunks:
        return "".join(c.replace('\\"', '"') for c in chunks)
    return r


def parse_dns_txt(records: list[str] | None) -> dict:
    """E1(b): any apex TXT record containing facebook-domain-verification=<code>."""
    codes: list[str] = []
    for rec in records or []:
        if isinstance(rec, bytes):
            rec = rec.decode("utf-8", "replace")
        val = _txt_value(str(rec))
        low = val.lower()
        idx = low.find(_DNS_TOKEN)
        if idx >= 0:
            code = val[idx + len(_DNS_TOKEN):].strip().split()[0] if val[
                idx + len(_DNS_TOKEN):].strip() else ""
            if code not in codes:
                codes.append(code)
    return {"e1_dns_txt": bool(codes), "dns_verification_codes": codes}


def meta_linked_level(e1: bool, e2: bool, e2b: bool, e2_gtm: bool, e3: bool) -> str:
    """Highest evidence level: E1 > E2/E2b > E2-GTM > E3 > none."""
    if e1:
        return "E1"
    if e2 or e2b:
        return "E2"
    if e2_gtm:
        return "E2-GTM"
    if e3:
        return "E3"
    return "none"


def combine_signals(domain: str, raw_html_signals: dict | None,
                    rendered_html_signals: dict | None, dns: dict | None, ads: dict | None,
                    gtm_flags: dict[str, bool] | None, homepage_source: str | None,
                    homepage_fetch_id: str | None) -> dict:
    """Merge raw + rendered homepage signals, DNS, ads.txt and GTM checks into one `signals` row.

    gtm_flags maps GTM container id -> gtm_has_meta_pixel(container_js). e2_gtm is only True
    when no direct pixel was found but at least one container references the pixel.
    """
    pages = [s for s in (raw_html_signals, rendered_html_signals) if s]

    def any_flag(key: str) -> bool:
        return any(bool(s.get(key)) for s in pages)

    def union(key: str) -> list[str]:
        out: list[str] = []
        for s in pages:
            for v in s.get(key) or []:
                if v not in out:
                    out.append(v)
        return out

    dns = dns or {}
    ads = ads or {}
    e1_tag = any_flag("e1_meta_tag")
    e1_dns = bool(dns.get("e1_dns_txt"))
    e2_pixel = any_flag("e2_pixel")
    e2b = bool(ads.get("e2b_adstxt"))
    gtm_ids = union("gtm_ids")
    e2_gtm = (not e2_pixel) and any(bool(v) for v in (gtm_flags or {}).values())
    fb_pages = union("fb_pages_meta")
    fb_app = union("fb_app_id")
    e3_fb = any_flag("e3_fb_link")
    e3_ig = any_flag("e3_ig_link")
    e3 = e3_fb or e3_ig or bool(fb_pages) or bool(fb_app)
    return {
        "domain": domain,
        "e1_meta_tag": e1_tag,
        "e1_dns_txt": e1_dns,
        "e2_pixel": e2_pixel,
        "pixel_ids": json.dumps(union("pixel_ids")),
        "e2_gtm": e2_gtm,
        "e2b_adstxt": e2b,
        "e3_fb_link": e3_fb,
        "e3_ig_link": e3_ig,
        "e3_fb_group": any_flag("e3_fb_group"),
        "fb_pages_meta": ",".join(fb_pages) or None,
        "fb_app_id": ",".join(fb_app) or None,
        "gtm_ids": json.dumps(gtm_ids),
        "meta_linked_level": meta_linked_level(e1_tag or e1_dns, e2_pixel, e2b, e2_gtm, e3),
        "homepage_source": homepage_source,
        "homepage_fetch_id": homepage_fetch_id,
        "homepage_available": bool(pages),
    }


SIGNALS_COLUMNS = [
    "domain", "e1_meta_tag", "e1_dns_txt", "e2_pixel", "pixel_ids", "e2_gtm", "e2b_adstxt",
    "e3_fb_link", "e3_ig_link", "e3_fb_group", "fb_pages_meta", "fb_app_id", "gtm_ids",
    "meta_linked_level", "homepage_source", "homepage_fetch_id", "homepage_available",
]


def write_signals(rows: list[dict], processed_dir: str | Path = "data/processed") -> pd.DataFrame:
    """Write combine_signals() rows to <processed_dir>/signals.parquet and return the frame."""
    df = pd.DataFrame(rows, columns=SIGNALS_COLUMNS)
    out = Path(processed_dir)
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / "signals.parquet", index=False)
    return df
