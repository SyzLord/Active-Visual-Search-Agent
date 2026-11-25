"""Run the frozen benchmark with the new matcher in the original stamp scheduler."""
import argparse
from functools import partial
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
HOLDOUT = HERE.parent / "印章独立页评测_2026-11-18"
PRIOR = HERE.parent / "印章定位放大评测_2026-11-17"
sys.path.insert(0, str(PRIOR))

from run_scan import evaluate
import stamp_scan
from date_repair import date_hits

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("fixture", choices=("marshall", "original"))
parser.add_argument("output", type=Path)
parser.add_argument("--hyphen-only", action="store_true")
args = parser.parse_args()
matcher = partial(date_hits, allow_cross_line=not args.hyphen_only)

with patch.object(stamp_scan, "date_hits", matcher):
    if args.fixture == "marshall":
        sys.argv = [str(HOLDOUT / "run.py"), str(args.output)]
        runpy.run_path(sys.argv[0], run_name="__main__")
    else:
        import json
        report = evaluate(smoke=False)
        with args.output.open("x") as out:
            json.dump(report, out, ensure_ascii=False)
