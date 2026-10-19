"""Stratified sampling of Tier B (SPEC §4.2).

Strata = country x owner_group, where owner_group is collapsed to the top-10 groups (by
domain count, excluding the unknown bucket) plus "independent/other". Proportional allocation
(largest remainder) with a minimum of ``min_per_group`` domains per owner group (or all of
its domains if it has fewer). Within a stratum, a seeded simple random sample of the sorted
domain list is drawn, so the result is deterministic for a given seed.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field

OTHER = "independent/other"


@dataclass
class SampleResult:
    selected: list[str]
    strata_pre: dict[str, int] = field(default_factory=dict)
    strata_post: dict[str, int] = field(default_factory=dict)
    top_groups: list[str] = field(default_factory=list)
    n_pre: int = 0
    n_post: int = 0
    sampled: bool = False


def collapse_groups(owner: dict[str, str], top_k: int = 10,
                    unknown_labels: tuple[str, ...] = ("independent/unknown",)) -> tuple[dict[str, str], list[str]]:
    cnt = Counter(g for g in owner.values() if g not in unknown_labels)
    top = [g for g, _ in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]]
    return {d: (g if g in top else OTHER) for d, g in owner.items()}, top


def _largest_remainder(sizes: dict, n: int) -> dict:
    N = sum(sizes.values())
    if N == 0 or n <= 0:
        return {k: 0 for k in sizes}
    quotas = {k: n * v / N for k, v in sizes.items()}
    alloc = {k: min(int(q), sizes[k]) for k, q in quotas.items()}
    rem = n - sum(alloc.values())
    order = sorted(sizes, key=lambda k: (-(quotas[k] - int(quotas[k])), str(k)))
    i = 0
    while rem > 0 and any(alloc[k] < sizes[k] for k in sizes):
        k = order[i % len(order)]
        if alloc[k] < sizes[k]:
            alloc[k] += 1
            rem -= 1
        i += 1
    return alloc


def allocate(strata_sizes: dict[tuple[str, str], int], n: int, min_per_group: int = 10) -> dict:
    """strata_sizes: {(country, group): N_h}. Returns {(country, group): n_h} summing to
    min(n, N). Every group other than OTHER gets >= min(min_per_group, N_group)."""
    N = sum(strata_sizes.values())
    if n >= N:
        return dict(strata_sizes)
    alloc = _largest_remainder(strata_sizes, n)
    groups = defaultdict(list)
    for k in strata_sizes:
        groups[k[1]].append(k)
    floor_g = {g: (0 if g == OTHER else min(min_per_group, sum(strata_sizes[k] for k in ks)))
               for g, ks in groups.items()}
    # raise groups below their floor (spread within the group proportionally)
    for g, ks in sorted(groups.items()):
        have = sum(alloc[k] for k in ks)
        if have < floor_g[g]:
            sub = _largest_remainder({k: strata_sizes[k] for k in ks}, floor_g[g])
            for k in ks:
                alloc[k] = max(alloc[k], sub[k])
            # fix up if per-stratum max() overshot or undershot
            while sum(alloc[k] for k in ks) < floor_g[g]:
                k = max((k for k in ks if alloc[k] < strata_sizes[k]), key=lambda k: (strata_sizes[k] - alloc[k], str(k)))
                alloc[k] += 1
    # remove the excess from the largest strata whose group stays above its floor
    excess = sum(alloc.values()) - n
    while excess > 0:
        cands = [k for k in alloc if alloc[k] > 0 and
                 sum(alloc[j] for j in groups[k[1]]) > floor_g[k[1]]]
        if not cands:
            break
        k = max(cands, key=lambda k: (alloc[k] / strata_sizes[k], alloc[k], str(k)))
        alloc[k] -= 1
        excess -= 1
    return alloc


def stratified_sample(country: dict[str, str], owner: dict[str, str], n: int, seed: int,
                      min_per_group: int = 10, top_k: int = 10) -> SampleResult:
    domains = sorted(country)
    grp, top = collapse_groups({d: owner.get(d, "independent/unknown") for d in domains}, top_k)
    strata: dict[tuple[str, str], list[str]] = defaultdict(list)
    for d in domains:
        strata[(country[d], grp[d])].append(d)
    sizes = {k: len(v) for k, v in strata.items()}
    res = SampleResult(selected=[], top_groups=top, n_pre=len(domains),
                       strata_pre={f"{k[0]}|{k[1]}": v for k, v in sorted(sizes.items())})
    if len(domains) <= n:
        res.selected = domains
        res.n_post = len(domains)
        res.strata_post = dict(res.strata_pre)
        return res
    alloc = allocate(sizes, n, min_per_group)
    sel: list[str] = []
    for k in sorted(strata):
        rng = random.Random(f"{seed}|{k[0]}|{k[1]}")
        sel.extend(rng.sample(sorted(strata[k]), alloc[k]))
    res.selected = sorted(sel)
    res.n_post = len(sel)
    res.sampled = True
    res.strata_post = {f"{k[0]}|{k[1]}": alloc[k] for k in sorted(alloc)}
    return res
