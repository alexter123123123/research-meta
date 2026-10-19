"""Registered-domain normalisation with a pinned Public Suffix List snapshot (SPEC §4.2)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import tldextract

from mcs.panel.http import SOURCES

PSL_URL = "https://publicsuffix.org/list/public_suffix_list.dat"
PSL_PATH = SOURCES / "public_suffix_list.dat"

# Hosting platforms, social networks, reference/archive sites and portals: never a news
# publisher's own registered domain. (reason, set)
PLATFORM_DOMAINS = {
    "social/video platform, not a publisher": {
        "facebook.com", "fb.com", "instagram.com", "twitter.com", "x.com", "t.co", "linkedin.com",
        "tiktok.com", "youtube.com", "youtu.be", "reddit.com", "flickr.com", "myspace.com",
        "pinterest.com", "threads.net", "bsky.app", "soundcloud.com", "vimeo.com",
    },
    "blog/newsletter hosting platform, not a publisher": {
        "wordpress.com", "blogspot.com", "blogger.com", "substack.com", "medium.com", "github.io",
        "tumblr.com", "wix.com", "wixsite.com", "weebly.com", "squarespace.com", "typepad.com",
        "livejournal.com", "ghost.io", "beehiiv.com", "patreon.com", "yolasite.com", "webs.com",
        "jimdo.com", "site123.me", "godaddysites.com", "mailchimp.com", "list-manage.com",
        "linktr.ee", "issuu.com", "squarespace-cdn.com",
    },
    "reference/archive/library database, not the publisher's site": {
        "wikipedia.org", "wikimedia.org", "wikidata.org", "archive.org", "archive.today",
        "archive.ph", "newsbank.com", "ebscohost.com", "epnet.com", "serialssolutions.com",
        "oclc.org", "worldcat.org", "lexis-nexis.com", "lexisnexis.com", "nexis.com",
        "proquest.com", "umi.com", "galegroup.com", "gale.com", "hathitrust.org",
        "newspaperarchive.com", "newspapers.com", "britishnewspaperarchive.co.uk",
        "pressdisplay.com", "pressreader.com", "europresse.com", "securities.com", "rdsinc.com",
        "hwwilsonweb.com", "jstor.org", "loc.gov", "findmypast.co.uk", "ancestry.com",
        "elephind.com", "fultonhistory.com", "nyshistoricnewspapers.org", "genealogybank.com",
        "curations.cc", "doi.org", "handle.net", "purl.org", "bl.uk",
    },
    "portal/search engine; registered-domain granularity cannot isolate news host": {
        "google.com", "yahoo.com", "msn.com", "aol.com", "bing.com", "apple.com", "amazon.com",
        "microsoft.com", "go.com", "sky.com", "google.co.uk",
    },
}

# Institutional suffixes: the registered domain is a university/government site, not the paper.
INSTITUTIONAL_SUFFIXES = ("edu", "gov", "mil", "ac.uk", "gov.uk", "sch.uk", "nhs.uk", "police.uk",
                          "k12.", "edu.", "gov.")


def platform_reason(domain: str) -> str | None:
    for reason, doms in PLATFORM_DOMAINS.items():
        if domain in doms:
            return reason
    return None


def institutional_reason(domain: str, suffix: str) -> str | None:
    s = suffix.lower()
    if s in ("edu", "gov", "mil", "ac.uk", "gov.uk", "sch.uk", "nhs.uk", "police.uk", "mod.uk",
             "parliament.uk") or s.startswith(("k12.", "edu.", "gov.")) or ".k12." in s \
            or s.endswith((".edu", ".gov")) or s.startswith("ac."):
        return "institutional domain (edu/gov/ac.uk); registered-domain granularity cannot isolate news site"
    return None


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def ensure_psl(client=None) -> dict:
    """Download the PSL once (pinned snapshot) and return its provenance."""
    meta_p = PSL_PATH.with_name(PSL_PATH.name + ".meta.json")
    if not PSL_PATH.exists():
        if client is None:
            raise FileNotFoundError(PSL_PATH)
        body, meta = client.get(PSL_URL, "public_suffix_list.dat")
        if meta.get("status") != 200:
            raise RuntimeError(f"PSL download failed: {meta}")
    info = {"path": str(PSL_PATH.relative_to(SOURCES.parents[2])), "url": PSL_URL,
            "sha256": sha256_file(PSL_PATH)}
    if meta_p.exists():
        m = json.loads(meta_p.read_text())
        info["fetched_at"] = m.get("fetched_at")
        info["last_modified"] = m.get("headers", {}).get("last-modified")
    txt = PSL_PATH.read_text(encoding="utf-8", errors="replace")
    mv = re.search(r"VERSION:\s*(\S+)", txt)
    cm = re.search(r"COMMIT:\s*(\S+)", txt)
    info["psl_version"] = mv.group(1) if mv else None
    info["psl_commit"] = cm.group(1) if cm else None
    info["include_psl_private_domains"] = False
    return info


_EXTRACTORS: dict[str, tldextract.TLDExtract] = {}


def extractor(psl_path: Path = PSL_PATH) -> tldextract.TLDExtract:
    key = str(psl_path)
    if key not in _EXTRACTORS:
        _EXTRACTORS[key] = tldextract.TLDExtract(
            suffix_list_urls=(Path(psl_path).resolve().as_uri(),),
            cache_dir=None, fallback_to_snapshot=False, include_psl_private_domains=False,
        )
    return _EXTRACTORS[key]


def host_of(url_or_host: str) -> str:
    s = (url_or_host or "").strip().strip("<>\"'")
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    try:
        h = urlsplit(s).hostname or ""
    except ValueError:
        return ""
    return h.strip(".").lower()


@dataclass
class Reg:
    domain: str  # registered domain ('' if none)
    suffix: str
    host: str


def registered(url_or_host: str, ext: tldextract.TLDExtract | None = None) -> Reg:
    ext = ext or extractor()
    h = host_of(url_or_host)
    if not h:
        return Reg("", "", "")
    r = ext(h)
    dom = r.top_domain_under_public_suffix if hasattr(r, "top_domain_under_public_suffix") else r.registered_domain
    return Reg((dom or "").lower(), (r.suffix or "").lower(), h)


def registered_domain(url_or_host: str, ext: tldextract.TLDExtract | None = None) -> str:
    return registered(url_or_host, ext).domain


_PAREN_RE = re.compile(r"\s*\(.*?\)\s*")


def split_newsbrand(cell: str) -> list[str]:
    """'bbc.com + bbc.co.uk' -> ['bbc.com', 'bbc.co.uk'];
    'abcnews.com (formerly abcnews.go.com)' -> ['abcnews.com']."""
    s = _PAREN_RE.sub(" ", cell or "").strip()
    parts = re.split(r"\s*(?:\+|,|/|&| and )\s*", s)
    return [p.strip().lower() for p in parts if p.strip()]


@dataclass
class Entry:
    domain: str
    brands: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


def merge_entries(items: list[tuple[str, str, dict]]) -> dict[str, Entry]:
    """Dedupe (domain, brand, extra) tuples by domain, preserving first-seen order and
    merging brand lists (case-insensitive unique, order-preserving). The first item's extra wins."""
    out: dict[str, Entry] = {}
    for dom, brand, extra in items:
        dom = (dom or "").lower().strip(".")
        if not dom:
            continue
        e = out.get(dom)
        if e is None:
            e = out[dom] = Entry(dom, [], dict(extra or {}))
        if brand and brand.strip() and brand.strip().lower() not in {b.lower() for b in e.brands}:
            e.brands.append(brand.strip())
    return out
