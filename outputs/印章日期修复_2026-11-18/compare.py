"""Summarize paired scan results and confirm the pixel ledger."""
from pathlib import Path
import json
import sys

base, updated = (json.loads(Path(path).read_text())["rows"] for path in sys.argv[1:3])
key_fields = ("collection", "case", "mode") if "collection" in base[0] else ("id", "strategy")
def key(row):
    return tuple(row[k] for k in key_fields) + ((row.get("trace") or row)["budget"],)

before, after = ({key(row): row for row in rows} for rows in (base, updated))
assert len(before) == len(base) and len(after) == len(updated) and before.keys() == after.keys()
for name in sorted({k[0] for k in before} if len(key_fields)==3 else {"previous"}):
    for budget in sorted({k[-1] for k in before}):
        for strategy in sorted({k[-2] for k in before}):
            pairs = [(before[k], after[k]) for k in before
                     if k[-2:] == (strategy,budget) and (len(key_fields)==2 or name==k[0])]
            successes_before = sum(row["strict"] for row, _ in pairs)
            successes_after = sum(row["strict"] for _, row in pairs)
            changes = [(a.get("case",a.get("id")), bool(b["strict"])) for a,b in pairs
                       if a["strict"] != b["strict"]]
            for _,row in pairs:
                trace = row.get("trace") or row
                assert sum(step["pixels"] for step in trace["steps"]) == trace["spent"]
                assert trace["spent"] + trace.get("preview_pixels",0) <= trace["budget"]
            print(name, budget, strategy, len(pairs), successes_before, successes_after, changes)
