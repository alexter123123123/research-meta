"""Tier B primary source: Wikidata SPARQL (SPEC §4.2).

query.wikidata.org's robots.txt (``User-agent: * / Disallow: /sparql``) disallows the SPARQL
endpoint for all automated agents, and our politeness rules require obeying robots.txt. The
same SPARQL query is therefore run against QLever's public Wikidata mirror
(https://qlever.dev/api/wikidata, robots.txt 404 => allowed), which answers the
``P31/P279*`` closure in a single query. Wikidata's ``wikibase:label`` SERVICE is not available
there, so labels come from ``rdfs:label`` filtered to English.
"""

from __future__ import annotations

import json
import time
from urllib.parse import urlencode

from mcs.panel.http import REPO_ROOT, PoliteClient

ENDPOINT = "https://qlever.dev/api/wikidata"
WDQS_ROBOTS = "https://query.wikidata.org/robots.txt"

QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?item ?itemLabel ?cls ?country ?website ?owner ?ownerLabel ?ownerParentLabel ?parent ?parentLabel WHERE {
  VALUES ?cls { wd:Q11032 wd:Q1153191 wd:Q1193236 }   # newspaper, online newspaper, news website
  VALUES ?country { wd:Q30 wd:Q145 }                  # United States, United Kingdom
  ?item wdt:P31/wdt:P279* ?cls .
  ?item wdt:P17 ?country .
  ?item wdt:P856 ?website .
  FILTER NOT EXISTS { ?item wdt:P576 ?dissolved }
  OPTIONAL { ?item rdfs:label ?itemLabel . FILTER(LANG(?itemLabel) = "en") }
  OPTIONAL { ?item wdt:P127 ?owner .
             OPTIONAL { ?owner rdfs:label ?ownerLabel . FILTER(LANG(?ownerLabel) = "en") }
             OPTIONAL { ?owner wdt:P749 ?ownerParent .
                        ?ownerParent rdfs:label ?ownerParentLabel . FILTER(LANG(?ownerParentLabel) = "en") } }
  OPTIONAL { ?item wdt:P749 ?parent .
             OPTIONAL { ?parent rdfs:label ?parentLabel . FILTER(LANG(?parentLabel) = "en") } }
}"""

COUNTRY = {"http://www.wikidata.org/entity/Q30": "US", "http://www.wikidata.org/entity/Q145": "GB"}


def _val(row: dict, k: str) -> str:
    v = row.get(k)
    return v["value"] if v else ""


def run_query(client: PoliteClient) -> tuple[list[dict], dict]:
    """Run (or load cached) query; returns (rows, provenance)."""
    cache = "wikidata/qlever_wikidata_result.json"
    url = ENDPOINT + "?" + urlencode({"query": QUERY})
    prov: dict = {"endpoint": ENDPOINT}
    # Record why WDQS is not used (its robots.txt is read; the /sparql path never is).
    try:
        rr = client.robots("https://query.wikidata.org/sparql")
        prov["wdqs_robots_status"] = rr.status
        prov["wdqs_robots_note"] = (
            "robots.txt body observed 2026-10-19: 'User-agent: * / Disallow: /sparql / Disallow: /bigdata'"
            + ("; at build time Wikimedia answered robots.txt with HTTP 403 to our client "
               "(robot-policy block), so WDQS is not usable either way" if rr.status == 403 else
               f"; at build time /sparql allowed for our UA: {rr.can_fetch('https://query.wikidata.org/sparql', client.token)}"))
    except Exception as e:  # pragma: no cover
        prov["wdqs_robots_error"] = repr(e)
    body, meta = client.get(url, cache, headers={"Accept": "application/sparql-results+json"},
                            timeout=600)
    if meta.get("status") != 200:
        raise RuntimeError(f"SPARQL failed: HTTP {meta.get('status')}: {body[:300]!r}")
    d = json.loads(body)
    prov["run_at"] = meta.get("fetched_at")
    prov["result_sha256"] = meta.get("sha256")
    prov["qlever_meta"] = d.get("meta")
    # index build info of the mirror (data freshness); one small request, cached
    try:
        sb, sm = client.get(ENDPOINT + "?cmd=stats", "wikidata/qlever_stats.json")
        if sm.get("status") == 200:
            st = json.loads(sb)
            prov["qlever_index"] = {k: st.get(k) for k in
                                    ("name-index", "git-hash-index", "git-hash-server",
                                     "num-triples-normal", "name-text-index") if k in st}
    except Exception as e:
        prov["qlever_stats_error"] = repr(e)
    rows = []
    for r in d["results"]["bindings"]:
        rows.append({
            "item": _val(r, "item"), "label": _val(r, "itemLabel"), "cls": _val(r, "cls"),
            "country": COUNTRY.get(_val(r, "country"), "XX"), "website": _val(r, "website"),
            "owner": _val(r, "owner"), "ownerLabel": _val(r, "ownerLabel"),
            "ownerParentLabel": _val(r, "ownerParentLabel"), "parent": _val(r, "parent"),
            "parentLabel": _val(r, "parentLabel"),
        })
    prov["n_rows"] = len(rows)
    prov["n_items"] = len({r["item"] for r in rows})
    return rows, prov


def write_query_file(prov: dict) -> None:
    p = REPO_ROOT / "data" / "panel" / "wikidata_query.sparql"
    p.parent.mkdir(parents=True, exist_ok=True)
    hdr = [
        "# Tier B sample-frame query (SPEC §4.2)",
        f"# run_at (UTC): {prov.get('run_at')}",
        f"# endpoint: {prov['endpoint']} (QLever public Wikidata mirror), GET, Accept: application/sparql-results+json",
        "# Why not query.wikidata.org: its robots.txt has 'User-agent: *  Disallow: /sparql'",
        f"#   ({prov.get('wdqs_robots_note')}); our politeness rules require obeying",
        "#   robots.txt, so the identical graph pattern is run on QLever.",
        "#   QLever evaluates the full wdt:P31/wdt:P279* closure in one query; no splitting/paging needed.",
        "#   Labels: rdfs:label filtered to English (QLever has no wikibase:label SERVICE).",
        f"# mirror index: {json.dumps(prov.get('qlever_index'))}",
        f"# result: {prov.get('n_rows')} rows / {prov.get('n_items')} items; sha256 {prov.get('result_sha256')}",
        f"# timestamp written: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "",
    ]
    p.write_text("\n".join(hdr) + QUERY + "\n")
