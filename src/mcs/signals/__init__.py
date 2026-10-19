"""Meta business-tool signals (SPEC §8). Pure functions; fetching lives in mcs.fetch."""

from mcs.signals.adstxt import parse_ads_txt
from mcs.signals.gtm import gtm_has_meta_pixel, gtm_url
from mcs.signals.homepage import (
    combine_signals,
    extract_homepage_signals,
    meta_linked_level,
    parse_dns_txt,
    write_signals,
)

__all__ = [
    "combine_signals",
    "extract_homepage_signals",
    "gtm_has_meta_pixel",
    "gtm_url",
    "meta_linked_level",
    "parse_ads_txt",
    "parse_dns_txt",
    "write_signals",
]
