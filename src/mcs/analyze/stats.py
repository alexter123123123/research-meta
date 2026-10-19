"""Statistics (SPEC §10.1): Wilson CI, Newcombe hybrid-score difference CI, exact McNemar,
size-weighted share."""

from __future__ import annotations

import math
from collections.abc import Iterable

from scipy.stats import binomtest, norm

MISSING_RANK = 1_000_000


def _z(alpha: float) -> float:
    return float(norm.ppf(1 - alpha / 2))


def wilson_ci(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson score interval for k successes out of n. Returns (nan, nan) for n == 0."""
    if n <= 0:
        return (math.nan, math.nan)
    z = _z(alpha)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo = 0.0 if k <= 0 else max(0.0, centre - half)
    hi = 1.0 if k >= n else min(1.0, centre + half)
    return (lo, hi)


def newcombe_diff_ci(k1: int, n1: int, k2: int, n2: int,
                     alpha: float = 0.05) -> tuple[float, float, float]:
    """Difference p1 - p2 with Newcombe (1998) method 10 hybrid score interval.

    Returns (diff, low, high); NaNs if either n is 0.
    """
    if n1 <= 0 or n2 <= 0:
        return (math.nan, math.nan, math.nan)
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson_ci(k1, n1, alpha)
    l2, u2 = wilson_ci(k2, n2, alpha)
    d = p1 - p2
    low = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    high = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return (d, low, high)


def mcnemar_exact(b: int, c: int) -> float:
    """Exact two-sided McNemar p-value from discordant pair counts b and c."""
    if b + c == 0:
        return 1.0
    return float(binomtest(int(b), int(b + c), 0.5, alternative="two-sided").pvalue)


def size_weight(tranco_rank) -> float:
    """weight = 1 / log10(tranco_rank + 10); missing rank -> treated as rank 1e6."""
    try:
        r = float(tranco_rank)
        if math.isnan(r):
            r = MISSING_RANK
    except (TypeError, ValueError):
        r = MISSING_RANK
    return 1.0 / math.log10(r + 10)


def weighted_share(flags: Iterable[bool], ranks: Iterable) -> float:
    """Size-weighted share of True flags (secondary metric; a traffic proxy only)."""
    num = den = 0.0
    for f, r in zip(flags, ranks, strict=True):
        w = size_weight(r)
        den += w
        if bool(f):
            num += w
    return num / den if den else math.nan


def prop_entry(k: int, n: int, n_indeterminate: int = 0, min_n: int = 20,
               alpha: float = 0.05) -> dict:
    """Standard metric entry used throughout metrics_<snapshot>.json."""
    lo, hi = wilson_ci(k, n, alpha)
    return {
        "numerator": int(k),
        "denominator": int(n),
        "pct": (100.0 * k / n) if n else None,
        "ci_low": 100.0 * lo if n else None,
        "ci_high": 100.0 * hi if n else None,
        "n_indeterminate": int(n_indeterminate),
        "suppressed": bool(n < min_n),
    }
