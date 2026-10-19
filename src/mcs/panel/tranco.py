"""Control group: Tranco list (SPEC §4.3).

tranco-list.eu's robots.txt disallows ``/api``, ``/list/`` and ``/daily_list_id`` for ``*``, so
the dated-list API is not used. The site's documented, allowed endpoints are used instead:
``/top-1m-id`` (permanent ID of the latest daily list) and ``/top-1m.csv.zip`` (that list).
The ID is read before and after the download to make sure they match.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field

from mcs.panel.http import SOURCES, PoliteClient
from mcs.panel.normalize import registered_domain

TRANCO = "https://tranco-list.eu"


@dataclass
class TrancoList:
    list_id: str
    date_info: dict
    ranks: dict[str, int] = field(default_factory=dict)  # registered domain -> best rank
    ordered: list[str] = field(default_factory=list)  # registered domains by best rank
    n_raw: int = 0


def _latest_id(client: PoliteClient, cache_name: str) -> str:
    body, meta = client.get(TRANCO + "/top-1m-id", cache_name)
    if meta.get("status") != 200:
        raise RuntimeError(f"tranco top-1m-id HTTP {meta.get('status')}")
    return body.decode().strip()


def fetch_tranco(client: PoliteClient) -> TrancoList:
    pinned = sorted((SOURCES / "tranco").glob("tranco_*_top-1m.csv.zip"))
    if pinned:
        zpath = pinned[-1]
        list_id = zpath.name.split("_")[1]
    else:
        list_id = _latest_id(client, "tranco/top-1m-id.before.txt")
        body, meta = client.get(TRANCO + "/top-1m.csv.zip", f"tranco/tranco_{list_id}_top-1m.csv.zip",
                                timeout=300)
        if meta.get("status") != 200:
            raise RuntimeError(f"tranco download HTTP {meta.get('status')}")
        after = _latest_id(client, "tranco/top-1m-id.after.txt")
        if after != list_id:
            raise RuntimeError(f"Tranco list changed during download ({list_id} -> {after}); rerun")
        zpath = SOURCES / "tranco" / f"tranco_{list_id}_top-1m.csv.zip"
    import json
    meta_p = zpath.with_name(zpath.name + ".meta.json")
    m = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    date_info = {
        "download_url": TRANCO + "/top-1m.csv.zip",
        "permalink": f"{TRANCO}/list/{list_id}/1000000",
        "fetched_at": m.get("fetched_at"),
        "last_modified": m.get("headers", {}).get("last-modified"),
        "sha256": m.get("sha256"),
        "note": "latest daily list at fetch time (dated-list API disallowed by robots.txt); "
                "list date = Last-Modified of the download",
    }
    tl = TrancoList(list_id, date_info)
    with zipfile.ZipFile(zpath) as zf:
        name = zf.namelist()[0]
        text = zf.read(name).decode("utf-8", "replace")
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2:
            continue
        try:
            rank = int(row[0])
        except ValueError:
            continue
        tl.n_raw += 1
        d = registered_domain(row[1])
        if d and (d not in tl.ranks or rank < tl.ranks[d]):
            tl.ranks[d] = rank
    tl.ordered = sorted(tl.ranks, key=lambda d: (tl.ranks[d], d))
    return tl
