"""Probe URL set per domain (spec §7.3). The same set is reused for every snapshot."""

from __future__ import annotations

import random
import re
from urllib.parse import urljoin, urlsplit

BASE_PROBES = ["/", "/news/"]
SYNTHETIC = "/2026/10/example-article-slug/"
MAX_ARTICLES = 3

_ARTICLE = re.compile(r"/20\d\d/|/[^/]*(?:-[^/-]+){4,}[^/]*/?$|\.(?:html?|ece|amp)$", re.I)
_EXCLUDE = re.compile(r"/(?:tag|tags|author|authors|search|live)(?:/|$)", re.I)
_HREF = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"'#]+)""", re.I)


def is_article_path(path: str) -> bool:
    segs = [s for s in path.split("/") if s]
    if len(segs) < 2:
        return False
    if _EXCLUDE.search(path):
        return False
    return bool(_ARTICLE.search(path))


def build_probes(homepage_html: str | None, page_url: str, seed: int = 20261030
                 ) -> tuple[list[str], bool]:
    """Return (probe_paths, synthetic_probe_flag)."""
    articles: list[str] = []
    if homepage_html:
        host = urlsplit(page_url).hostname
        seen: set[str] = set()
        for href in _HREF.findall(homepage_html):
            u = urlsplit(urljoin(page_url, href.strip()))
            if u.scheme not in ("http", "https") or u.hostname != host:
                continue
            path = u.path or "/"
            if path in seen or not is_article_path(path):
                continue
            seen.add(path)
            articles.append(path)
    if articles:
        rng = random.Random(f"{seed}:{page_url}")
        picks = articles if len(articles) <= MAX_ARTICLES else rng.sample(articles, MAX_ARTICLES)
        return BASE_PROBES + sorted(picks), False
    return BASE_PROBES + [SYNTHETIC], True
