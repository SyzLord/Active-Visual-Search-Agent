"""Re-OCR the right window chosen by the old policy, independently of the left stamp."""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / "印章定位放大评测_2026-11-17"
HOLDOUT = HERE.parent / "印章独立页评测_2026-11-18"
sys.path.insert(0, str(PRIOR))
from run_scan import area, overlap, open_image, OCR, ReaderRuntime, parse_task
from search_agent.core import ViewSpec
from edge_scan import date_hits as original_hits, observe_edge
from date_repair import date_hits

protocol = json.loads((HOLDOUT / "protocol.json").read_text())
before = json.loads((HOLDOUT / "results.json").read_text())["rows"]
frozen = next(row["trace"] for row in before if row["collection"] == "single"
              and row["mode"] == "two-windows" and row["case"] == "date"
              and row["trace"]["budget"] == 1_000_000)
step = next(s for s in frozen["steps"] if s.get("rotation_deg_ccw") == 90)
page = open_image("marsh01", HOLDOUT / protocol["pages"]["marsh01"])
target = protocol["fields"]["date"]
field = parse_task({"op": "locate", "fields": [{"anchor": target["anchor"]}]}).fields[0]
spec = ViewSpec(step["view"], -1, "stamp", tuple(step["box"]), tuple(step["size"]))
with OCR(ReaderRuntime()) as engine:
    observation = observe_edge(page, spec, step["rotation_deg_ccw"], engine)
runs = {}
for mode, matcher in (("original", original_hits), ("hyphen_only", lambda *a: date_hits(*a, allow_cross_line=False)),
                      ("hyphen_and_cross_line", date_hits)):
    hit = {}
    matcher(page, spec, observation["lines"], [field], hit)
    evidence = hit.get(field.id)
    checks = []
    if evidence:
        box = evidence["anchor_box"]
        for expected in target["boxes"]:
            intersect = overlap(box, expected)
            checks.append((intersect / (area(box) + area(expected) - intersect), intersect/area(expected)))
    runs[mode] = {"evidence": evidence, "iou": max((a for a,b in checks), default=0),
                  "pass_box": any(a >= .30 and b >= .48 for a,b in checks)}
with Path(sys.argv[1]).open("x") as f:
    json.dump({"crop": step, "observation": observation, "runs": runs}, f, indent=2, ensure_ascii=False)
