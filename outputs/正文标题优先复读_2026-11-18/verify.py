"""Check paired budgets and report both historical joint queries."""
import argparse
from pathlib import Path
import sys


PRIOR = Path(__file__).resolve().parent.parent / "印章正文预算复验_2026-11-18"
sys.path.insert(0, str(PRIOR))
from compare import compare, indexed


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("marshall", type=Path)
parser.add_argument("original", type=Path)
args = parser.parse_args()
marshall_base = PRIOR / "cross-probe-marshall.json"
original_base = PRIOR / "cross-probe-original.json"
compare(marshall_base, args.marshall)
compare(original_base, args.original)

before, after = indexed(original_base), indexed(args.original)
assert len(before) == len(after) == 66
for key, (old, old_trace, old_pixels) in before.items():
    new, trace, pixels = after[key]
    assert (old["strict"], old["checks"], old_trace["answer"], old_pixels) == (
        new["strict"], new["checks"], trace["answer"], pixels
    ), key
    if key[1] == "stamp-locate" and key[2] in {"scan17-10", "scan17-11"}:
        print(f"Historical joint {key[2]} @ {key[3]}: {int(old['strict'])}→{int(new['strict'])}; "
              f"pixels {old_pixels}→{pixels}; evidence "
              f"{[(item['field'], item['page'], item['anchor']) for item in trace['evidence']]}")

before, after = indexed(marshall_base), indexed(args.marshall)
assert len(before) == len(after) == 36
for key, (old, _, _) in before.items():
    new, trace, _ = after[key]
    targeted = key[1] in {"two-windows", "four-windows"} and key[2:] == ("joint", 1_000_000)
    if targeted:
        assert not old["strict"] and new["strict"], key
        assert trace["answer"] == {"result": "both_located"}, key
        assert trace["evidence"][1]["view"].startswith("article-confirm:"), key
    else:
        assert old["strict"] == new["strict"] and old["checks"] == new["checks"], key
