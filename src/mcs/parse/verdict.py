"""Turn parsed robots.txt + probe paths into per-bot verdicts (spec §7.4)."""

from __future__ import annotations

from dataclasses import dataclass, field

from protego import Protego

from mcs.parse.robots import ParsedRobots, Rule, is_allowed
from mcs.parse.tokens import EXACT, NONSTANDARD, PREFIX, is_wildcard, match_mode

FULL_BLOCK = "FULL_BLOCK"
PARTIAL_BLOCK = "PARTIAL_BLOCK"
ALLOWED_EXPLICIT = "ALLOWED_EXPLICIT"
WILDCARD_BLOCK = "WILDCARD_BLOCK"
WILDCARD_PARTIAL = "WILDCARD_PARTIAL"
ALLOWED_DEFAULT = "ALLOWED_DEFAULT"
INDETERMINATE = "INDETERMINATE"

RESTRICTIVENESS = {
    ALLOWED_DEFAULT: 0,
    ALLOWED_EXPLICIT: 1,
    WILDCARD_PARTIAL: 2,
    PARTIAL_BLOCK: 3,
    WILDCARD_BLOCK: 4,
    FULL_BLOCK: 5,
}

# fetch_status values (spec §6.4)
DETERMINATE_PARSE = {"OK", "OK_EMPTY"}
ALLOW_ALL_STATUSES = {"UNAVAILABLE_4XX", "SOFT_404"}
INDETERMINATE_STATUSES = {"RATE_LIMITED_429", "UNREACHABLE_5XX", "NETWORK_ERROR", "CHALLENGE",
                          "INDETERMINATE_BLOCKED", "WAYBACK_HTML", "WAYBACK_BLOCKED",
                          "WAYBACK_ERROR", "WAYBACK_RESTRICTED", "NO_CAPTURE",
                          "INCONSISTENT_HTML"}


@dataclass
class Verdict:
    bot: str
    verdict: str
    named: bool = False
    named_raw: list[str] = field(default_factory=list)
    match_mode: str | None = None
    nonstandard_raw: list[str] = field(default_factory=list)
    probes_total: int = 0
    probes_disallowed: int = 0
    protego_agree: bool | None = None
    protego_mismatch: list[str] = field(default_factory=list)
    in_cf_managed_block: bool = False
    named_lines: list[int] = field(default_factory=list)


def rules_for(parsed: ParsedRobots, token: str) -> tuple[list[Rule], dict]:
    """Merged rules of all groups naming `token` (exact/prefix), else the `*` groups."""
    named_rules: list[Rule] = []
    named_raw: list[str] = []
    named_lines: list[int] = []
    nonstd: list[str] = []
    modes: list[str] = []
    named_in_cf: list[bool] = []
    wildcard_rules: list[Rule] = []
    for g in parsed.groups:
        hit = False
        for a in g.agents:
            m = match_mode(a.raw, token)
            if m in (EXACT, PREFIX):
                hit = True
                named_raw.append(a.raw)
                named_lines.append(a.line_no)
                modes.append(m)
                named_in_cf.append(a.in_cf)
            elif m == NONSTANDARD:
                nonstd.append(a.raw)
        if hit:
            named_rules.extend(g.rules)
        if any(is_wildcard(a.raw) for a in g.agents):
            wildcard_rules.extend(g.rules)
    named = bool(named_raw)
    info = {
        "named": named,
        "named_raw": named_raw,
        "named_lines": named_lines,
        "match_mode": (EXACT if EXACT in modes else PREFIX) if named else (
            NONSTANDARD if nonstd else None),
        "nonstandard_raw": nonstd,
        # all naming lines inside a CF block => the rule is CF-managed
        "in_cf": named and all(named_in_cf),
    }
    return (named_rules if named else wildcard_rules), info


def verdict_for(parsed: ParsedRobots, token: str, probes: list[str],
                protego: Protego | None = None) -> Verdict:
    rules, info = rules_for(parsed, token)
    disallowed = 0
    mismatches: list[str] = []
    for p in probes:
        ok, _ = is_allowed(rules, p)
        if not ok:
            disallowed += 1
        if protego is not None:
            if protego.can_fetch("https://example.com" + p, token) != ok:
                mismatches.append(p)
    n = len(probes)
    if info["named"]:
        v = FULL_BLOCK if disallowed == n else PARTIAL_BLOCK if disallowed else ALLOWED_EXPLICIT
    else:
        v = WILDCARD_BLOCK if disallowed == n else WILDCARD_PARTIAL if disallowed else ALLOWED_DEFAULT
    return Verdict(
        bot=token,
        verdict=v,
        named=info["named"],
        named_raw=info["named_raw"],
        named_lines=info["named_lines"],
        match_mode=info["match_mode"],
        nonstandard_raw=info["nonstandard_raw"],
        probes_total=n,
        probes_disallowed=disallowed,
        protego_agree=(not mismatches) if protego is not None else None,
        protego_mismatch=mismatches,
        in_cf_managed_block=info["in_cf"],
    )


def verdicts_for_body(body: bytes | None, fetch_status: str, bots: list[str],
                      probes: list[str], parsed: ParsedRobots | None = None) -> list[Verdict]:
    """Apply RFC 9309 fetch-outcome semantics, then per-bot verdicts."""
    if fetch_status in INDETERMINATE_STATUSES:
        return [Verdict(bot=b, verdict=INDETERMINATE) for b in bots]
    if fetch_status in ALLOW_ALL_STATUSES or fetch_status == "OK_EMPTY" or not body:
        return [Verdict(bot=b, verdict=ALLOWED_DEFAULT, probes_total=len(probes),
                        protego_agree=True) for b in bots]
    from mcs.parse.robots import decode_body, parse

    parsed = parsed or parse(body)
    text, _ = decode_body(body)
    pg = Protego.parse(text)
    return [verdict_for(parsed, b, probes, pg) for b in bots]


def direction(from_v: str, to_v: str) -> str | None:
    if INDETERMINATE in (from_v, to_v) or from_v is None or to_v is None:
        return None
    a, b = RESTRICTIVENESS[from_v], RESTRICTIVENESS[to_v]
    return "more_restrictive" if b > a else "less_restrictive" if b < a else "same"
