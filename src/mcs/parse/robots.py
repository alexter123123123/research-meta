"""RFC 9309 robots.txt group extractor and path matcher.

We keep our own parser (rather than only Protego) because we need to know
*which* raw line named a bot, whether it sat inside a Cloudflare-managed
block, and how the user-agent line was spelled. Protego is used as a
cross-check in verdict.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote, unquote_to_bytes

from mcs.parse.cfmanaged import cf_block_ranges, detect_generator

MAX_BYTES = 500 * 1024

# Directive aliases mirror Protego's tolerance so that disagreements with it
# come only from deliberate differences (user-agent matching), not typos.
UA_FIELDS = {"user-agent", "useragent", "user agent"}
ALLOW_FIELDS = {"allow"}
DISALLOW_FIELDS = {"disallow", "dissallow", "dissalow", "disalow", "diasllow", "disallaw"}
SITEWIDE_FIELDS = {"sitemap", "sitemaps", "site-map", "host"}
OTHER_KNOWN = {
    "crawl-delay", "crawl delay", "request-rate", "request rate", "visit-time", "visit time",
    "clean-param", "content-signal", "noindex",
}
KNOWN_FIELDS = UA_FIELDS | ALLOW_FIELDS | DISALLOW_FIELDS | SITEWIDE_FIELDS | OTHER_KNOWN
_MAX_WORDS = max(len(f.split()) for f in KNOWN_FIELDS)

_HTML_RE = re.compile(rb"^\s*(<!doctype\s+html|<html|<head|<body|<\?xml)", re.IGNORECASE)
_HTML_ANY_RE = re.compile(rb"<(html|head|body|script|div|meta)\b", re.IGNORECASE)


@dataclass
class Rule:
    type: str  # "allow" | "disallow"
    path: str
    line_no: int
    in_cf: bool = False


@dataclass
class UALine:
    raw: str  # original value as written
    line_no: int
    in_cf: bool = False


@dataclass
class Group:
    idx: int
    agents: list[UALine] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    line_start: int = 0
    line_end: int = 0
    other: list[tuple[str, str, int]] = field(default_factory=list)  # crawl-delay, content-signal...


@dataclass
class ParsedRobots:
    groups: list[Group]
    sitemaps: list[str]
    content_signals: list[tuple[str, int]]
    unknown: list[tuple[str, str, int]]
    cf_ranges: list[tuple[int, int]]
    generator_hint: str | None
    truncated: bool
    looks_html: bool
    lines: list[str]  # decoded original lines (1-indexed via lines[n-1])

    @property
    def has_rules(self) -> bool:
        return any(g.rules for g in self.groups)


def decode_body(body: bytes) -> tuple[str, bool]:
    """Truncate at 500 KiB, strip BOM, decode UTF-8 with latin-1 fallback."""
    truncated = len(body) > MAX_BYTES
    if truncated:
        body = body[:MAX_BYTES]
    if body.startswith(b"\xef\xbb\xbf"):
        body = body[3:]
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        if truncated:
            # The cut may have split a multibyte char; retry without the tail.
            try:
                text = body.decode("utf-8", errors="ignore")
            except UnicodeDecodeError:  # pragma: no cover
                text = body.decode("latin-1")
        else:
            text = body.decode("latin-1")
    return text.lstrip("﻿"), truncated


def looks_like_html(body: bytes) -> bool:
    head = body[:2048]
    if _HTML_RE.match(head):
        return True
    return len(_HTML_ANY_RE.findall(body[:8192])) >= 3


def split_lines(text: str) -> list[str]:
    return re.split(r"\r\n|\r|\n", text)


def extract_directive(line: str) -> tuple[str, str] | None:
    """Split a comment-stripped line into (field, value). Mirrors Protego."""
    fld = None
    value = ""
    if ":" in line:
        fld, raw_value = line.split(":", 1)
        fld = fld.strip().lower()
        value = raw_value.strip()
        if fld in KNOWN_FIELDS:
            return fld, value
        if not raw_value or raw_value[0].isspace():
            return fld, value
    words = line.split()
    for n in range(1, _MAX_WORDS + 1):
        cand = " ".join(words[:n]).lower()
        if cand in KNOWN_FIELDS:
            return cand, " ".join(words[n:])
    if fld is None:
        return None
    return fld, value


def parse(body: bytes | str) -> ParsedRobots:
    if isinstance(body, str):
        body = body.encode("utf-8")
    html = looks_like_html(body)
    text, truncated = decode_body(body)
    lines = split_lines(text)
    cf_ranges = cf_block_ranges(lines)

    def in_cf(n: int) -> bool:
        return any(a <= n <= b for a, b in cf_ranges)

    groups: list[Group] = []
    current: Group | None = None
    prev_field: str | None = None
    sitemaps: list[str] = []
    signals: list[tuple[str, int]] = []
    unknown: list[tuple[str, str, int]] = []

    for n, raw in enumerate(lines, start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        d = extract_directive(line)
        if d is None:
            continue
        fld, value = d

        if fld in UA_FIELDS:
            if current is None or (prev_field is not None and prev_field not in UA_FIELDS):
                current = Group(idx=len(groups), line_start=n)
                groups.append(current)
            prev_field = fld
            current.line_end = n
            if value:
                current.agents.append(UALine(raw=value, line_no=n, in_cf=in_cf(n)))
            continue

        if fld in SITEWIDE_FIELDS:
            if fld.startswith("site") and value:
                sitemaps.append(value)
            continue

        prev_field = fld
        if fld == "content-signal":
            signals.append((value, n))
        if current is None:
            if fld not in KNOWN_FIELDS:
                unknown.append((fld, value, n))
            continue
        current.line_end = n
        if fld in ALLOW_FIELDS or fld in DISALLOW_FIELDS:
            if not value:  # empty Disallow/Allow = no restriction
                continue
            typ = "allow" if fld in ALLOW_FIELDS else "disallow"
            current.rules.append(Rule(type=typ, path=value, line_no=n, in_cf=in_cf(n)))
        elif fld in KNOWN_FIELDS:
            current.other.append((fld, value, n))
        else:
            unknown.append((fld, value, n))

    return ParsedRobots(
        groups=groups,
        sitemaps=sitemaps,
        content_signals=signals,
        unknown=unknown,
        cf_ranges=cf_ranges,
        generator_hint=detect_generator(text),
        truncated=truncated,
        looks_html=html,
        lines=lines,
    )


# ---------------------------------------------------------------------------
# Path matching (RFC 9309 §2.2.2 / §2.2.3)
# ---------------------------------------------------------------------------

_UNRESERVED = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_SAFE = "/?=&;:@!$'()*+,%-._~"


def normalize_path(p: str) -> str:
    """Percent-encode non-ASCII, uppercase escapes, decode escaped unreserved chars."""
    out = []
    raw = quote(p, safe=_SAFE + "#[]")
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == "%" and i + 2 < len(raw) and re.fullmatch(r"[0-9A-Fa-f]{2}", raw[i + 1:i + 3]):
            b = unquote_to_bytes(raw[i:i + 3])[0]
            if b in _UNRESERVED:
                out.append(chr(b))
            else:
                out.append("%" + raw[i + 1:i + 3].upper())
            i += 3
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _pattern_regex(pattern: str) -> re.Pattern:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    parts = [re.escape(x) for x in pattern.split("*")]
    rx = ".*".join(parts)
    return re.compile(rx + ("$" if anchored else ""), re.DOTALL)


def rule_matches(pattern: str, path: str) -> bool:
    if pattern.startswith(("http://", "https://")):
        pattern = "/" + pattern
    if not pattern.startswith(("/", "*")):
        pattern = "/" + pattern
    pat = normalize_path(pattern)
    if "*" not in pat and not pat.endswith("$"):
        return path.startswith(pat)
    return _pattern_regex(pat).match(path) is not None


def is_allowed(rules: list[Rule], path: str) -> tuple[bool, Rule | None]:
    """Longest match wins; on equal length, allow wins. No match => allowed."""
    if not path.startswith("/"):
        path = "/" + path
    path = normalize_path(path)
    best: Rule | None = None
    best_len = -1
    for r in rules:
        if rule_matches(r.path, path):
            ln = len(normalize_path(r.path))
            if ln > best_len or (ln == best_len and r.type == "allow" and best and best.type != "allow"):
                best, best_len = r, ln
    if best is None:
        return True, None
    return best.type == "allow", best
