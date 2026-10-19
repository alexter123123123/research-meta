"""ads.txt Meta Audience Network check (SPEC §8, level E2b). Pure function."""

from __future__ import annotations

import re

_HTML_RE = re.compile(r"<\s*(!doctype|html|head|body|script|div|meta|title)\b", re.I)


def looks_like_html(text: str) -> bool:
    """Soft-404 / challenge detection: an HTML document served instead of ads.txt."""
    head = (text or "").lstrip("﻿ \t\r\n")[:2048]
    return bool(_HTML_RE.search(head))


def parse_ads_txt(text: str | None) -> dict:
    """e2b_adstxt is True if a non-comment line's first comma field equals 'facebook.com'."""
    out = {"e2b_adstxt": False, "adstxt_html": False, "adstxt_facebook_lines": 0,
           "adstxt_facebook_ids": []}
    if not text:
        return out
    if looks_like_html(text):
        out["adstxt_html"] = True
        return out
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.split("#", 1)[0].strip().lstrip("﻿")
        if not line or "," not in line:
            continue
        fields = [f.strip() for f in line.split(",")]
        if fields[0].lower() == "facebook.com":
            out["adstxt_facebook_lines"] += 1
            if len(fields) > 1 and fields[1] and fields[1] not in out["adstxt_facebook_ids"]:
                out["adstxt_facebook_ids"].append(fields[1])
    out["e2b_adstxt"] = out["adstxt_facebook_lines"] > 0
    return out
