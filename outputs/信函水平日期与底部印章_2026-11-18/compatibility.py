"""Exercise two previously solved vertical-date tasks as development regression controls."""
import argparse
import json
from pathlib import Path

import evaluate
from dates import requested_date
from heldout import score
from letter_search import run_letter

ROOT = evaluate.HERE.parent
GRADER = evaluate.grader


def controls():
    source = ROOT / "印章独立页评测_2026-11-18"
    evaluate.check_lock(source / "frozen.sha256")
    archive = json.loads((source / "protocol.json").read_text())
    pages = {key: GRADER.open_image(key, source / path) for key, path in archive["pages"].items()}
    marshall = []
    for key in ("date", "findings"):
        entry = archive["fields"][key]
        marshall.append(dict(page="marsh01", anchor=entry["anchor"], box=entry["boxes"][0],
                             alternative_boxes=entry["boxes"][1:]))
    for label, keys in archive["sets"].items():
        yield "marshall-joint", label, [pages[key] for key in keys], marshall
    source = ROOT / "真实扫描评测_2026-11-17"
    assert evaluate.digest(source / "manifest.json") == (source / "manifest.sha256").read_text().strip()
    cases = json.loads((source / "manifest.json").read_text())["cases"]
    original, = [case for case in cases if case["id"] == "scan17-10"]
    gold = [dict(item, box=item["anchor_box"]) for item in original["gold"].values()]
    yield "scan17-10", "cross-page", [pages["13"], pages["26"]], gold


def evaluate_controls():
    evaluate.check_lock(evaluate.HERE / "policy.sha256")
    runtime, rows = GRADER.ReaderRuntime(), []
    policies = {"heading-first": lambda task, pages, budget, engine: GRADER.heading.run_reserved(
        task, pages, budget, engine, cross_probe=True), "horizontal-footer": run_letter}
    limits = {"iou_min": .30, "gold_coverage_min": .48}
    with GRADER.OCR(runtime) as engine, GRADER.patch.object(GRADER.stamp_scan, "date_hits", GRADER.date_hits):
        for case, label, pages, gold in controls():
            task = GRADER.parse_task({"op": "verify", "fields": [{"anchor": item["anchor"]} for item in gold]})
            date_field, = [item for item in task.fields if requested_date(item.anchor)]
            for name, runner in policies.items():
                meter = evaluate.Meter(engine)
                trace = runner(task, pages, 1_000_000, meter)
                triggers = evaluate.inspect_trace(trace, meter, date_field.id)
                checks = score(task.fields, gold, trace, limits)
                strict = trace["answer"] == {"result": "both_located"} and all(check["strict"] for check in checks)
                rows.append(dict(case=case, collection=label, policy=name, fields=checks,
                                 strict=strict, triggers=triggers, trace=trace))
    return {"ocr": runtime.identifier, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output path")
    result = evaluate_controls()
    with args.output.open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, separators=(",", ":"))
