"""Template-cluster body hash (spec §7.7)."""

from __future__ import annotations

import hashlib
import re

from mcs.parse.robots import decode_body, split_lines

_SITEMAP = re.compile(r"^\s*(sitemaps?|site-map)\s*:", re.I)


def body_hash(body: bytes) -> str:
    """sha256 of the body with comments, Sitemap lines, blank lines and case of field names removed."""
    text, _ = decode_body(body)
    keep = []
    for line in split_lines(text):
        line = line.split("#", 1)[0].strip()
        if not line or _SITEMAP.match(line):
            continue
        if ":" in line:
            f, v = line.split(":", 1)
            line = f.strip().lower() + ":" + v.strip()
        keep.append(line)
    return hashlib.sha256("\n".join(keep).encode("utf-8")).hexdigest()
