"""Meta Pixel / GTM regexes (SPEC §8, level E2 / E2-GTM). Pure functions, no network."""

from __future__ import annotations

import re

# Slashes inside JS strings are often escaped (connect.facebook.net\/en_US\/fbevents.js).
_SL = r"(?:\\?/)"

FBEVENTS_RE = re.compile(
    rf"connect\.facebook\.net{_SL}[A-Za-z_\-]+{_SL}fbevents\.js", re.IGNORECASE)
FBEVENTS_ANY_RE = re.compile(r"fbevents(?:\.plugins)?(?:\.js)?", re.IGNORECASE)
# fbq('init', '1234567890') / fbq("init","123", {...}) / fbq('init', 123)
FBQ_INIT_RE = re.compile(
    r"""fbq\s*\(\s*(?:\\?['"])init(?:\\?['"])\s*,\s*(?:\\?['"])?\s*(\d{5,20})""", re.IGNORECASE)
# https://www.facebook.com/tr?id=123&ev=PageView  (also &amp;, escaped slashes, id not first)
FB_TR_RE = re.compile(
    rf"facebook\.com{_SL}tr{_SL}?\?(?:[^\"'\s<>]*?(?:&|&amp;|\\u0026))?id=(\d{{5,20}})",
    re.IGNORECASE)
FB_TR_ANY_RE = re.compile(rf"facebook\.com{_SL}tr\b", re.IGNORECASE)
GTM_ID_RE = re.compile(r"\bGTM-[A-Z0-9]{4,10}\b")


def find_pixel_ids(text: str) -> list[str]:
    """Pixel IDs from fbq('init', ID) calls and facebook.com/tr?id=ID beacons, ordered, unique."""
    ids: list[str] = []
    for rx in (FBQ_INIT_RE, FB_TR_RE):
        for m in rx.finditer(text or ""):
            if m.group(1) not in ids:
                ids.append(m.group(1))
    return ids


def has_fbevents(text: str) -> bool:
    return bool(FBEVENTS_RE.search(text or ""))


def has_pixel(text: str) -> bool:
    """True if any direct Meta Pixel marker is present in HTML/JS text."""
    t = text or ""
    return bool(FBEVENTS_RE.search(t) or FBQ_INIT_RE.search(t) or FB_TR_RE.search(t))


def find_gtm_ids(text: str) -> list[str]:
    out: list[str] = []
    for m in GTM_ID_RE.finditer(text or ""):
        if m.group(0) not in out:
            out.append(m.group(0))
    return out
