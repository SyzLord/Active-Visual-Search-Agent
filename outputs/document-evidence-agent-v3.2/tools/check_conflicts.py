"""Run the same genuine PDF/OCR requests under both candidate policies."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from search_agent.documents import ROOT, load_paths
from search_agent.reader import OCR, ReaderRuntime
from search_agent.scheduler import run
from search_agent.task import parse_task


def main(output):
    directory = ROOT / "data/conflicts"
    records = json.loads((directory / "manifest.json").read_text())
    results = []
    with OCR(ReaderRuntime()) as engine:
        for row in records:
            for scoped in (False, True):
                field = {"anchor": row["anchor"], "window": 2}
                if scoped:
                    field["pages"] = ["d01-p02"]
                task = parse_task({"op": "extract", "fields": [field], "unit": "kW"})
                pages = load_paths([directory / row["file"]], fields=task.fields)
                for strategy in ("hybrid", "audited"):
                    response = run(task, pages, 500_000, lambda p, s: p.observe(s, engine), strategy)
                    expected = "answered" if scoped else row["expected"]
                    actual = response["answer"]
                    correct = response["status"] == expected
                    if expected == "answered":
                        correct &= actual is not None and actual["value"] == row["values"][1]
                    else:
                        correct &= actual is None
                    results.append({"file": row["file"], "scoped": scoped, "strategy": strategy,
                                    "expected": expected, "correct": bool(correct), "result": response})
    summary = []
    for scoped in (False, True):
        for strategy in ("hybrid", "audited"):
            group = [r for r in results if r["scoped"] == scoped and r["strategy"] == strategy]
            summary.append({"scoped": scoped, "strategy": strategy, "correct": sum(r["correct"] for r in group),
                            "total": len(group),
                            "mean_pixels": round(sum(r["result"]["spent"] for r in group) / len(group))})
    output.parent.mkdir(exist_ok=True, parents=True)
    output.write_text(json.dumps({"seed": 61583, "summary": summary, "trials": results}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output)
