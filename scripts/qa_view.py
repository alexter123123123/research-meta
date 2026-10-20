"""Print the robots.txt groups relevant to the QA check for a list of domains (snapshot T2)."""
import sys
import pandas as pd
from mcs.fetch.store import load_body
from mcs.parse.robots import parse

BOTS = ["meta-externalagent", "meta-externalads", "facebookexternalhit", "gptbot"]
v = pd.read_parquet("data/processed/verdicts.parquet")
f = pd.read_parquet("data/processed/fetches.parquet").set_index("fetch_id")
snap = sys.argv[1]
for d in sys.argv[2:]:
    rows = v[(v.domain == d) & (v.snapshot == snap) & (v.bot.isin(BOTS))].set_index("bot")
    if rows.empty:
        print(f"## {d}: no verdicts"); continue
    fr = f.loc[rows.iloc[0].fetch_id]
    verd = " ".join(f"{b.split('-')[-1][:8]}={rows.loc[b,'verdict'][:12]}" for b in BOTS if b in rows.index)
    print(f"## {d} [{fr.fetch_status}] probes={rows.iloc[0].probes_total} :: {verd}")
    body = load_body(fr.body_path) if isinstance(fr.body_path, str) else None
    if not body or fr.fetch_status != "OK":
        continue
    for g in parse(body).groups:
        uas = [a.raw for a in g.agents]
        if any(a.strip() == "*" or any(k in a.lower() for k in ("meta", "facebook", "gpt")) for a in uas):
            rules = [f"{r.type[0].upper()}:{r.path}" for r in g.rules]
            short = rules[:6] + (["…+%d" % (len(rules) - 6)] if len(rules) > 6 else [])
            print(f"   UA {uas[:6]}{'…' if len(uas) > 6 else ''} -> {short}")
