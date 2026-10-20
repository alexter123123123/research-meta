"""Bot-challenge page detection (spec §6.3)."""

from __future__ import annotations

import re

_MARKERS = re.compile(
    rb"cf-chl|cf_chl_|challenge-platform|just a moment\.\.\.|attention required! \| cloudflare|"
    rb"px-captcha|_incapsula_|incapsula incident|captcha-delivery|geo\.captcha-delivery|"
    rb"datadome|perimeterx|g-recaptcha|h-captcha|hcaptcha\.com|"
    rb"access denied</title>|request unsuccessful\. incapsula|akamai.{0,40}reference #|"
    rb"verifying your device|verify you are (a )?human|checking your browser|are you a robot|"
    rb"enable javascript and cookies to continue|toadmash|monocle-enriched|"
    rb"<title>\s*(attention required|security check|bot verification|just a moment)",
    re.IGNORECASE,
)


def is_challenge(body: bytes, content_type: str | None = None) -> bool:
    head = body[:65536]
    if not head:
        return False
    # A plain-text robots.txt mentioning "captcha" in a path is not a challenge page.
    if isinstance(content_type, str) and content_type.startswith("text/plain") \
            and b"<" not in head[:512]:
        return False
    return bool(_MARKERS.search(head))
