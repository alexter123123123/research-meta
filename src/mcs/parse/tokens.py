"""User-agent token matching (spec §7.2)."""

from __future__ import annotations

import re

EXACT, PREFIX, NONSTANDARD, NONE = "exact", "prefix", "nonstandard", None

_ALNUM = re.compile(r"[^a-z0-9]")


def norm_token(raw: str) -> str:
    """Lowercase, trim, cut at first whitespace, strip a /version suffix."""
    t = raw.strip().lower()
    t = t.split()[0] if t.split() else ""
    return t.split("/", 1)[0]


def _alnum(s: str) -> str:
    return _ALNUM.sub("", s.lower())


def match_mode(raw: str, token: str) -> str | None:
    """How a robots.txt user-agent value refers to `token`.

    exact        meta-externalagent
    prefix       meta-externalagent/1.1, meta-externalagent*
    nonstandard  Meta-External*, meta external agent, MetaExternalAgent,
                 facebook*, a full browser-style UA string containing the token
    None         unrelated (including the bare "*" wildcard)
    """
    token = token.lower()
    s = raw.strip().lower()
    if not s or s == "*":
        return NONE
    first = s.split()[0]
    if first == token:
        return EXACT
    if first.startswith(token):
        rest = first[len(token):]
        if rest.startswith("/") or set(rest) <= {"*"}:
            return PREFIX
    # Nonstandard spellings
    if "*" in s:
        pre = _alnum(s.split("*", 1)[0])
        if pre and _alnum(token).startswith(pre):
            return NONSTANDARD
    if _alnum(s) == _alnum(token):
        return NONSTANDARD
    # Truncated token at a word boundary, e.g. "Meta-External", "Meta", "Facebook" — a
    # substring matcher (Protego) would apply these; RFC 9309 product-token matching would not.
    a = _alnum(s)
    if len(a) >= 4 and _alnum(token).startswith(a) and " " not in s.strip():
        return NONSTANDARD
    if token in s and len(s) > len(token):
        # token embedded in a longer string, e.g. a full UA header
        idx = s.find(token)
        before = s[idx - 1] if idx > 0 else " "
        after = s[idx + len(token)] if idx + len(token) < len(s) else " "
        if not (before.isalnum() or before == "-") and not (after.isalnum() or after == "-"):
            return NONSTANDARD
    return NONE


def is_wildcard(raw: str) -> bool:
    return raw.strip() == "*"
