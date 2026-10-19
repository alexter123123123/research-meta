import math

import pytest

from mcs.analyze.stats import (
    mcnemar_exact,
    newcombe_diff_ci,
    prop_entry,
    size_weight,
    weighted_share,
    wilson_ci,
)


def test_wilson_known_value():
    lo, hi = wilson_ci(81, 263)
    assert lo == pytest.approx(0.2553, abs=5e-4)
    assert hi == pytest.approx(0.3662, abs=5e-4)


def test_wilson_edges():
    lo, hi = wilson_ci(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=5e-4)
    lo, hi = wilson_ci(10, 10)
    assert hi == 1.0 and lo == pytest.approx(0.7225, abs=5e-4)
    assert all(math.isnan(x) for x in wilson_ci(0, 0))


def test_newcombe_paper_example():
    # Newcombe (1998), Stat Med 17:873-890, example (a): 56/70 vs 48/80 -> 0.0524 to 0.3339
    d, lo, hi = newcombe_diff_ci(56, 70, 48, 80)
    assert d == pytest.approx(0.2)
    assert lo == pytest.approx(0.0524, abs=5e-4)
    assert hi == pytest.approx(0.3339, abs=5e-4)


def test_newcombe_example_b():
    # Newcombe (1998) example (b): 9/10 vs 3/10 -> 0.1705 to 0.8090
    _, lo, hi = newcombe_diff_ci(9, 10, 3, 10)
    assert lo == pytest.approx(0.1705, abs=5e-4)
    assert hi == pytest.approx(0.8090, abs=5e-4)


def test_mcnemar_exact():
    assert mcnemar_exact(0, 0) == 1.0
    # b=1, c=9 -> two-sided exact binomial p = 2 * P(X<=1 | n=10, .5) = 0.02148
    assert mcnemar_exact(1, 9) == pytest.approx(0.021484375)
    assert mcnemar_exact(5, 5) == pytest.approx(1.0)


def test_weighted_share():
    assert size_weight(None) == pytest.approx(1 / math.log10(1_000_010))
    assert size_weight(90) == pytest.approx(0.5)
    # rank 90 weight 0.5, rank 990 weight 1/3
    assert weighted_share([True, False], [90, 990]) == pytest.approx(0.5 / (0.5 + 1 / 3))
    assert math.isnan(weighted_share([], []))


def test_prop_entry():
    e = prop_entry(5, 10, n_indeterminate=2, min_n=20)
    assert e["pct"] == 50.0 and e["suppressed"] and e["n_indeterminate"] == 2
    assert prop_entry(0, 0)["pct"] is None
