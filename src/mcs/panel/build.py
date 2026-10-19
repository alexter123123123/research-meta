"""Build the sample frame (SPEC §4): Tier A + Tier B news panel and the Tranco control.

Usage: ``python -m mcs.panel.build [--no-liveness]``
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from selectolax.lexbor import LexborHTMLParser

from mcs.panel import chains as chains_mod
from mcs.panel import pressgazette as pg
from mcs.panel import tranco as tranco_mod
from mcs.panel import wikidata as wd
from mcs.panel.http import REPO_ROOT, PoliteClient, load_config, safe_name
from mcs.panel.normalize import (
    ensure_psl, institutional_reason, merge_entries, platform_reason, registered, registered_domain,
)
from mcs.panel.sample import stratified_sample

OUT = REPO_ROOT / "data" / "panel"
PANEL_COLUMNS = ["domain", "panel", "tier", "country", "brands", "owner_group", "source_list",
                 "source_rank", "tranco_rank", "control_top1000", "is_news", "added_at", "source_url"]
UNKNOWN = chains_mod.UNKNOWN


CONTENT_FARM_GROUPS = {"VUGA"}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------------------------
# UK brand map verification (homepage <title>)
# ---------------------------------------------------------------------------------------------

def make_uk_verifier(client: PoliteClient):
    def verify(host: str, expect: str) -> str:
        url = f"https://{host}/"
        try:
            body, meta = client.get(url, f"pg_uk_verify/{safe_name(host)}.html", cache_errors=True)
        except Exception as e:
            return f"curated from knowledge; title check not possible ({type(e).__name__})"
        st = meta.get("status")
        if st != 200:
            return f"curated from knowledge; title check not possible (HTTP {st})"
        tree = LexborHTMLParser(body.decode("utf-8", "replace"))
        t = tree.css_first("title")
        title = re.sub(r"\s+", " ", t.text(strip=True)) if t else ""
        og = tree.css_first('meta[property="og:site_name"]')
        site = og.attributes.get("content", "") if og else ""
        final_dom = registered_domain(meta.get("final_url", url))
        exp_dom = registered_domain(host)
        hay = f"{title} {site}".lower()
        ok = any(x.lower() in hay or x.lower().replace(" ", "") in hay.replace(" ", "")
                 for x in expect.split("|"))
        redirect = "" if final_dom == exp_dom else f"; WARNING redirects to {final_dom}"
        if ok:
            return (f"curated; verified {meta.get('fetched_at', '')[:10]}: homepage title "
                    f"{title[:70]!r} matches {expect!r}{redirect}")
        return f"curated; WARNING homepage title {title[:70]!r} / site {site[:40]!r} does not contain {expect!r}{redirect}"
    return verify


# ---------------------------------------------------------------------------------------------
# Tier B from Wikidata
# ---------------------------------------------------------------------------------------------

def tier_b_candidates(rows: list[dict], tier_a: set[str], chain_res) -> tuple[dict, list[dict]]:
    excl: list[dict] = []
    items: dict[str, dict] = {}
    for r in rows:
        it = items.setdefault(r["item"], {"labels": set(), "countries": Counter(), "websites": set(),
                                          "owner": [], "parent": [], "ownerParent": []})
        if r["label"]:
            it["labels"].add(r["label"])
        it["countries"][r["country"]] += 1
        it["websites"].add(r["website"])
        for k, src in (("owner", "ownerLabel"), ("parent", "parentLabel"), ("ownerParent", "ownerParentLabel")):
            if r[src] and r[src] not in it[k]:
                it[k].append(r[src])
    per_domain: dict[str, dict] = {}
    for qid, it in items.items():
        owner = chains_mod.resolve_owner(sorted(it["owner"]) + sorted(it["parent"]) + sorted(it["ownerParent"]))
        country = it["countries"].most_common(1)[0][0]
        label = sorted(it["labels"])[0] if it["labels"] else qid.rsplit("/", 1)[-1]
        doms = set()
        for w in sorted(it["websites"]):
            reg = registered(w)
            reason = None
            if not reg.domain:
                reason = "unparseable official-website URL"
            else:
                reason = platform_reason(reg.domain) or institutional_reason(reg.domain, reg.suffix)
            if reason:
                excl.append({"domain": reg.domain or w, "source_list": "wikidata",
                             "reason": f"{reason} [{label}; {w}]"})
                continue
            if reg.domain in tier_a:
                excl.append({"domain": reg.domain, "source_list": "wikidata",
                             "reason": f"duplicate of Tier A domain (kept in Tier A) [{label}]"})
                continue
            doms.add(reg.domain)
        for d in doms:
            pd = per_domain.setdefault(d, {"brands": [], "countries": Counter(), "owners": Counter(),
                                           "items": []})
            if label not in pd["brands"]:
                pd["brands"].append(label)
            pd["countries"][country] += 1
            pd["owners"][owner] += 1
            pd["items"].append(qid.replace("http://www.wikidata.org/entity/", "https://www.wikidata.org/wiki/"))
    out = {}
    for d, pd in per_domain.items():
        known = [(n, g) for g, n in pd["owners"].items() if g != UNKNOWN]
        owner = sorted(known, key=lambda x: (-x[0], x[1]))[0][1] if known else UNKNOWN
        owner_src = "wikidata" if known else ""
        if owner == UNKNOWN:
            g = chain_res.by_domain.get(d) or next(
                (chain_res.by_title.get(chains_mod.norm_title(b)) for b in pd["brands"]
                 if chain_res.by_title.get(chains_mod.norm_title(b))), None)
            if g:
                owner, owner_src = g, "wikipedia_chain_list"
        cc = pd["countries"].most_common()
        country = cc[0][0] if len(cc) == 1 or cc[0][1] > cc[1][1] else sorted(c for c, n in cc if n == cc[0][1])[-1]
        out[d] = {"domain": d, "brands": sorted(pd["brands"]), "country": country, "owner_group": owner,
                  "owner_source": owner_src, "source_list": "wikidata", "source_rank": None,
                  "source_url": " ".join(sorted(set(pd["items"]))[:10])}
    return out, excl


# ---------------------------------------------------------------------------------------------

def build_panel(config_path: str = "config/study.yaml", liveness: bool = True) -> None:
    cfg = load_config(config_path)
    ua = cfg["identity"]["user_agent"]
    rl = cfg.get("rate_limits", {})
    seed = int(cfg.get("panel", {}).get("random_seed", cfg["study"]["random_seed"]))
    tier_b_target = int(cfg.get("panel", {}).get("tier_b_target", 1400))
    control_size = int(cfg.get("panel", {}).get("control_size", 10000))
    min_group = int(cfg.get("panel", {}).get("min_per_owner_group", 10))
    built_at = _now()
    OUT.mkdir(parents=True, exist_ok=True)
    client = PoliteClient(ua, min_interval=float(rl.get("per_host_min_interval_s", 2.0)),
                          connect_timeout=float(rl.get("connect_timeout_s", 10)),
                          read_timeout=float(rl.get("read_timeout_s", 20)),
                          max_retries=int(rl.get("max_retries", 2)),
                          max_redirects=int(rl.get("max_redirects", 5)))
    meta: dict = {"frame_version": cfg["study"].get("frame_version", "1.0"), "built_at": built_at,
                  "seed": seed, "user_agent": ua, "problems": []}
    print("[panel] PSL", flush=True)
    meta["psl"] = ensure_psl(client)

    # ---- Tier A -----------------------------------------------------------------------------
    print("[panel] Tier A (Press Gazette)", flush=True)
    pgr = pg.build_tier_a(client, verify_uk=make_uk_verifier(client))
    meta["tier_a_sources"] = pgr.lists
    meta["anylang_june_2026"] = pgr.anylang
    meta["problems"] += pgr.problems
    meta["country_corrections"] = {k: v[1] for k, v in pg.COUNTRY_CORRECTIONS.items()}
    with (OUT / "pg_uk_brand_map.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["brand", "domain", "note"])
        w.writeheader()
        w.writerows(pgr.uk_map)
    order = {"us": 0, "uk": 1, "world": 2}
    key_of = {l["source_list"]: l["key"] for l in pgr.lists if "source_list" in l}
    a_rows = sorted(pgr.rows, key=lambda r: (order.get(key_of.get(r.source_list), 9), r.source_rank))
    merged = merge_entries([(r.domain, r.brand, {"country": r.country, "source_list": r.source_list,
                                                 "source_rank": r.source_rank, "source_url": r.source_url})
                            for r in a_rows])
    tier_a = {d: {"domain": d, "brands": e.brands, **e.extra} for d, e in merged.items()}
    exclusions: list[dict] = [{k: e[k] for k in ("domain", "source_list")} |
                              {"reason": e["reason"] + (f" [brand {e['brand']}]" if e.get("brand") else "")}
                              for e in pgr.exclusions]

    # ---- Wikidata + chains --------------------------------------------------------------------
    print("[panel] Wikidata", flush=True)
    wd_rows, wd_prov = wd.run_query(client)
    wd.write_query_file(wd_prov)
    meta["wikidata"] = wd_prov
    print("[panel] chain lists", flush=True)
    chain_res = chains_mod.fetch_chains(client)
    meta["chain_lists"] = chain_res.log
    cands, b_excl = tier_b_candidates(wd_rows, set(tier_a), chain_res)
    exclusions += b_excl
    # Quality filters (lead review, 19 Oct): batch-created content-farm items and foreign-ccTLD
    # editions mislabelled as US/UK are not regional/local publishers.
    generic_cc = {"uk", "us", "io", "co", "tv", "fm", "me", "ai", "ly", "cc", "ws", "to", "gg"}
    for d in list(cands):
        last = d.rsplit(".", 1)[-1]
        reason = None
        if cands[d]["owner_group"] in CONTENT_FARM_GROUPS:
            reason = f"content-farm network (owner {cands[d]['owner_group']})"
        elif len(last) == 2 and last not in generic_cc:
            reason = f"foreign ccTLD .{last} despite Wikidata country {cands[d]['country']}"
        if reason:
            exclusions.append({"domain": d, "source_list": cands[d]["source_list"],
                               "reason": reason})
            del cands[d]
    # chain lists may add missing dailies (only when the list gives a domain)
    added = 0
    for d, (title, group) in chain_res.added_domains.items():
        if d in cands or d in tier_a or platform_reason(d):
            continue
        cands[d] = {"domain": d, "brands": [title] if title else [], "country": "US", "owner_group": group,
                    "owner_source": "wikipedia_chain_list", "source_list": f"wikipedia_chain:{group}",
                    "source_rank": None, "source_url": ""}
        added += 1
    meta["chain_added_domains"] = added

    # Tier A owner groups: curated > Wikidata > unknown
    wd_owner = {d: c["owner_group"] for d, c in cands.items()}
    full_b, _ = tier_b_candidates(wd_rows, set(), chain_res)
    for d, a in tier_a.items():
        a["owner_group"] = pg.TIER_A_OWNERS.get(d) or (full_b.get(d, {}).get("owner_group")) or UNKNOWN
    del wd_owner

    # ---- liveness -----------------------------------------------------------------------------
    b_domains = sorted(cands)
    meta["tier_b_candidates_pre_liveness"] = len(b_domains)
    live: dict[str, dict] = {}
    if liveness:
        from mcs.panel.liveness import check_domains, is_transient_failure, recheck_transient
        print(f"[panel] liveness pass 1 for {len(b_domains)} Tier B candidates", flush=True)
        pass1 = check_domains(b_domains, ua, rl)
        transient = [d for d in b_domains if is_transient_failure(pass1[d])]
        print(f"[panel] liveness pass 2 (concurrency 5) for {len(transient)} transient failures", flush=True)
        pass2 = recheck_transient(transient, ua, rl, concurrency=5) if transient else {}
        live = {}
        unverified = []
        for d in b_domains:
            rec = dict(pass2.get(d, pass1[d]))
            rec["pass"] = 2 if d in pass2 else 1
            rec["pass1_method"] = pass1[d].get("liveness_method")
            rec["pass1_error"] = (pass1[d].get("error") or "")[:200] if d in pass2 else ""
            if d in pass2 and is_transient_failure(rec):
                # still only transient/local failures: keep; T2 (GitHub Actions) classifies them
                rec.update(ok=True, liveness_method="unverified",
                           error="unverified after 2 passes (transient/local failures only): "
                                 + (rec.get("error") or ""))
                unverified.append(d)
            live[d] = rec
        with (OUT / "liveness.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["domain", "ok", "final_url", "status", "error",
                                               "liveness_method", "robots_status", "checked_at",
                                               "pass", "pass1_method", "pass1_error"],
                               extrasaction="ignore")
            w.writeheader()
            for d in b_domains:
                rec = dict(live[d])
                rec["ok"] = int(bool(rec.get("ok")))
                w.writerow(rec)
        dropped = [d for d in b_domains if not live[d].get("ok")]
        for d in dropped:
            r = live[d]
            why = {"dns": "does not resolve (NXDOMAIN/no address)",
                   "unreachable": "TLS certificate failure (https), no usable http",
                   "homepage": "404 at root"}.get(r.get("liveness_method"), r.get("liveness_method"))
            exclusions.append({"domain": d, "source_list": cands[d]["source_list"],
                               "reason": f"liveness: {why} ({r.get('error', '')[:120]})"})
        b_domains = [d for d in b_domains if live[d].get("ok")]
        meta["liveness"] = {"checked": len(live), "dropped": len(dropped),
                            "pass2_rechecked": len(transient),
                            "pass2_recovered": sum(1 for d in pass2 if pass2[d].get("ok")),
                            "unverified_kept": len(unverified),
                            "drop_rule": "drop only definitive outcomes: NXDOMAIN/no address, 404 at root, "
                                         "persistent TLS certificate failure; transient failures "
                                         "(pool/connect/read timeouts, temporary DNS, proxy errors) are "
                                         "rechecked at concurrency 5 and kept as 'unverified' if still failing",
                            "by_method": dict(Counter(r.get("liveness_method") for r in live.values())),
                            "dropped_by_method": dict(Counter(live[d].get("liveness_method") for d in dropped))}
    else:
        meta["liveness"] = {"skipped": True}

    # ---- stratified sample ---------------------------------------------------------------------
    sres = stratified_sample({d: cands[d]["country"] for d in b_domains},
                             {d: cands[d]["owner_group"] for d in b_domains},
                             n=tier_b_target, seed=seed, min_per_group=min_group)
    sel = set(sres.selected)
    for d in b_domains:
        if d not in sel:
            exclusions.append({"domain": d, "source_list": cands[d]["source_list"],
                               "reason": f"not selected by stratified sample (seed {seed}, target {tier_b_target})"})
    meta["tier_b_sampling"] = {"sampled": sres.sampled, "n_pre": sres.n_pre, "n_post": sres.n_post,
                               "target": tier_b_target, "min_per_owner_group": min_group,
                               "top_groups": sres.top_groups, "strata_pre": sres.strata_pre,
                               "strata_post": sres.strata_post}

    # ---- Tranco -------------------------------------------------------------------------------
    print("[panel] Tranco", flush=True)
    tl = tranco_mod.fetch_tranco(client)
    meta["tranco"] = {"list_id": tl.list_id, **tl.date_info, "n_raw": tl.n_raw,
                      "n_registered_domains": len(tl.ranks)}
    control = tl.ordered[:control_size]

    # ---- assemble -----------------------------------------------------------------------------
    rows = []
    news_domains = set(tier_a) | sel
    for d, a in tier_a.items():
        rows.append({"domain": d, "panel": "news", "tier": "A", "country": a["country"] or "XX",
                     "brands": json.dumps(a["brands"], ensure_ascii=False), "owner_group": a["owner_group"],
                     "source_list": a["source_list"], "source_rank": a["source_rank"],
                     "tranco_rank": tl.ranks.get(d), "control_top1000": 0, "is_news": 1,
                     "added_at": built_at, "source_url": a["source_url"]})
    for d in sorted(sel):
        c = cands[d]
        rows.append({"domain": d, "panel": "news", "tier": "B", "country": c["country"] or "XX",
                     "brands": json.dumps(c["brands"], ensure_ascii=False), "owner_group": c["owner_group"],
                     "source_list": c["source_list"], "source_rank": None,
                     "tranco_rank": tl.ranks.get(d), "control_top1000": 0, "is_news": 1,
                     "added_at": built_at, "source_url": c["source_url"]})
    for i, d in enumerate(control, start=1):
        rows.append({"domain": d, "panel": "control", "tier": "control", "country": "XX",
                     "brands": "[]", "owner_group": UNKNOWN, "source_list": f"tranco_{tl.list_id}",
                     "source_rank": i, "tranco_rank": tl.ranks[d], "control_top1000": int(i <= 1000),
                     "is_news": int(d in news_domains), "added_at": built_at,
                     "source_url": tl.date_info["permalink"]})
    with (OUT / "panel.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=PANEL_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r[k] is None else r[k]) for k in PANEL_COLUMNS})

    seen = set()
    with (OUT / "panel_exclusions.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["domain", "source_list", "reason"])
        w.writeheader()
        for e in exclusions:
            k = (e["domain"], e["source_list"], e["reason"])
            if k not in seen:
                seen.add(k)
                w.writerow(e)

    news = [r for r in rows if r["panel"] == "news"]
    meta["counts"] = {
        "tier": dict(Counter(r["tier"] for r in rows)),
        "tier_country": {f"{t}|{c}": n for (t, c), n in sorted(Counter((r["tier"], r["country"]) for r in news).items())},
        "tier_b_owner_groups": dict(Counter(r["owner_group"] for r in news if r["tier"] == "B").most_common()),
        "tier_a_owner_groups": dict(Counter(r["owner_group"] for r in news if r["tier"] == "A").most_common()),
        "control_is_news": sum(r["is_news"] for r in rows if r["panel"] == "control"),
        "news_with_tranco_rank": sum(1 for r in news if r["tranco_rank"] is not None),
        "exclusions": len(seen),
        "exclusions_by_reason_head": dict(Counter(re.sub(r"\s*[\[(].*$", "", e[2]) for e in seen).most_common()),
    }
    meta["conventions"] = {
        "country": "ISO-2 (UK = GB); XX unknown/control",
        "control_top1000": "1 for control rows ranked <=1000 in the reduced control ordering; 0 for news rows",
        "is_news": "1 for all news rows; for control rows 1 if the domain is also in the news panel",
        "owner_group_tier_a": "curated map (pressgazette.TIER_A_OWNERS) > Wikidata > independent/unknown",
        "tier_precedence": "Tier A lists in order US, UK, World; a Tier A domain is never Tier B",
    }
    meta["http_requests_this_run"] = len(client.log)
    (OUT / "panel_meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False, default=str))
    client.close()
    print(f"[panel] done: {meta['counts']['tier']}", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the study sample frame (panel.csv)")
    ap.add_argument("--config", default="config/study.yaml")
    ap.add_argument("--no-liveness", action="store_true")
    a = ap.parse_args(argv)
    build_panel(a.config, liveness=not a.no_liveness)


if __name__ == "__main__":
    main()
