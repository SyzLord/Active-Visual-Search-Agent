"""Run the schedulers on the same frozen Marshall Plan or historical scan fixture."""
import argparse
import json
from functools import partial
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
HOLDOUT = HERE.parent / "印章独立页评测_2026-11-18"
PRIOR = HERE.parent / "印章定位放大评测_2026-11-17"
REPAIR = HERE.parent / "印章日期修复_2026-11-18"
sys.path[:0] = [str(PRIOR), str(REPAIR)]

import run_scan
import stamp_scan
from date_repair import date_hits
from reserved import run_reserved

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("policy", choices=("baseline", "bands", "reserved", "cross-probe"))
parser.add_argument("fixture", choices=("marshall", "original"))
parser.add_argument("output", type=Path)
args = parser.parse_args()
runner = {
    "baseline": stamp_scan.run_stamp,
    "bands": partial(run_reserved, line_reread=False),
    "reserved": run_reserved,
    "cross-probe": partial(run_reserved, cross_probe=True),
}[args.policy]

with patch.object(stamp_scan, "date_hits", date_hits):
    if args.fixture == "marshall":
        # Pass the original runner through explicitly so nontargeted tasks retain the baseline.
        with patch.object(stamp_scan, "run_stamp", runner):
            sys.argv = [str(HOLDOUT / "run.py"), str(args.output)]
            runpy.run_path(sys.argv[0], run_name="__main__")
    else:
        with patch.object(run_scan, "run_stamp", runner):
            report = run_scan.evaluate(smoke=False)
        with args.output.open("x") as out:
            json.dump(report, out, ensure_ascii=False)
