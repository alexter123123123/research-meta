"""Google Tag Manager container check (SPEC §8, level E2-GTM). Pure function."""

from __future__ import annotations

from mcs.signals.pixel import FB_TR_ANY_RE, FBEVENTS_ANY_RE

GTM_JS_URL = "https://www.googletagmanager.com/gtm.js?id={gtm_id}"


def gtm_url(gtm_id: str) -> str:
    return GTM_JS_URL.format(gtm_id=gtm_id)


def gtm_has_meta_pixel(js: str) -> bool:
    """True if a public GTM container JS references the Meta Pixel (fbevents or facebook.com/tr)."""
    if not js:
        return False
    return bool(FBEVENTS_ANY_RE.search(js) or FB_TR_ANY_RE.search(js))
