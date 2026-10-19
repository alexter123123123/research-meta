"""Detect Cloudflare-managed robots.txt sections and generator fingerprints (spec §7.6)."""

from __future__ import annotations

import re

_CF_BEGIN = re.compile(r"#\s*begin\s+cloudflare\s+managed\s+content", re.IGNORECASE)
_CF_END = re.compile(r"#\s*end\s+cloudflare\s+managed\s+content", re.IGNORECASE)

GENERATORS = [
    ("cloudflare", re.compile(r"cloudflare\s+managed", re.IGNORECASE)),
    ("yoast", re.compile(r"yoast", re.IGNORECASE)),
    ("rank_math", re.compile(r"rank\s*math", re.IGNORECASE)),
    ("wordpress_vip", re.compile(r"wordpress\s*vip|wpvip", re.IGNORECASE)),
    ("wordpress", re.compile(r"wp-admin|wordpress", re.IGNORECASE)),
    ("arc_xp", re.compile(r"\barc\s*xp\b|arcpublishing|/pf/api/", re.IGNORECASE)),
    ("brightspot", re.compile(r"brightspot", re.IGNORECASE)),
    ("drupal", re.compile(r"drupal|/core/misc/|/node/add", re.IGNORECASE)),
    ("blox_townnews", re.compile(r"townnews|bloxcms|/tncms/", re.IGNORECASE)),
    ("gannett", re.compile(r"gannett|usatoday network", re.IGNORECASE)),
    ("lee", re.compile(r"lee enterprises", re.IGNORECASE)),
]


def cf_block_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """Return 1-indexed inclusive line ranges inside CF-managed blocks.

    An unterminated BEGIN runs to end of file.
    """
    ranges: list[tuple[int, int]] = []
    start = None
    for n, line in enumerate(lines, start=1):
        if start is None and _CF_BEGIN.search(line):
            start = n
        elif start is not None and _CF_END.search(line):
            ranges.append((start, n))
            start = None
    if start is not None:
        ranges.append((start, len(lines)))
    return ranges


def detect_generator(text: str) -> str | None:
    hits = [name for name, rx in GENERATORS if rx.search(text)]
    # "wordpress" is implied by more specific WP plugins
    if "wordpress" in hits and any(h in hits for h in ("yoast", "rank_math", "wordpress_vip")):
        hits.remove("wordpress")
    return ",".join(hits) or None
