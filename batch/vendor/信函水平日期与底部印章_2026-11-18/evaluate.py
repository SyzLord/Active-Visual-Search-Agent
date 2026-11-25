"""Pair a frozen policy and its predecessor and independently meter every OCR call."""
import argparse
from copy import deepcopy
from hashlib import sha256
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys
from time import perf_counter

from PIL import Image

HERE = Path(__file__).resolve().parent
DEV = HERE.parent / "未见历史信函评测_2026-11-18"
module_spec = importlib.util.spec_from_file_location("frozen_grader", DEV / "run.py")
grader = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(grader)
from letter_search import run_letter


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def check_lock(path):
    for line in path.read_text().splitlines():
        expected, name = line.split("  ", 1)
        if digest(path.parent / name) != expected:
            raise ValueError(f"Hash mismatch: {name}")


class Meter:
    def __init__(self, engine):
        self.engine, self.calls = engine, []

    def recognize(self, encoded, size, mode):
        with Image.open(BytesIO(encoded)) as image:
            assert image.size == tuple(size)
        lines = self.engine.recognize(encoded, size, mode)
        self.calls.append({"size": list(size), "mode": mode, "raw_normalized": deepcopy(lines)})
        return lines


def stage(step):
    if "stage" in step:
        return step["stage"]
    name = step["view"]
    if name.startswith("stamp:"):
        return "side"
    if name.startswith("article-confirm:"):
        return "text-reread"
    if name.startswith("article-"):
        return "body"
    return "global"


def inspect_trace(trace, meter, date_id):
    steps = trace["steps"]
    paid = 0
    for number, (step, call) in enumerate(zip(steps, meter.calls, strict=True), 1):
        width, height = call["size"]
        assert step["size"] == call["size"] and step["pixels"] == width * height and step["step"] == number
        paid += step["pixels"]
        assert paid == step["spent"]
        step["stage"] = stage(step)
        step["engine_mode"] = call["mode"]
        step["raw_normalized"] = call["raw_normalized"]
    preview = 0
    for item in trace["preview_observations"]:
        width, height = item["size"]
        assert width * height == item["pixels"]
        preview += item["pixels"]
    assert paid == trace["spent"] and preview == trace["preview_pixels"]
    assert paid + preview == trace["total_pixels"] <= trace["budget"] == 1_000_000
    assert trace["ocr_calls"] == len(steps)
    stages = {step["stage"] for step in steps}
    hit_steps = {}
    for hit in trace["evidence"]:
        step, = [item for item in steps if item["view"] == hit["view"] and item["page"] == hit["page"]]
        hit_steps[hit["field"]] = step
    found = hit_steps.get(date_id, {})
    date_stage = found.get("stage")
    return {
        "early_date": bool(date_stage and date_stage != "global"), "date_stage": date_stage,
        "footer_tried": "footer" in stages, "footer_date": date_stage == "footer" or (
            date_stage == "date-reread" and found["view"].startswith("footer-")),
        "date_reread": "date-reread" in stages, "text_reread": "text-reread" in stages,
        "reread_pixels": sum(step["pixels"] for step in steps if step["stage"] in {"text-reread", "date-reread"}),
        "fallback": "global" in stages, "fallback_added": any(step["stage"] == "global" for step in hit_steps.values())
    }


def evaluate(split):
    protocol_path = DEV / "protocol.json" if split == "development" else HERE / "holdout.json"
    if split == "holdout" or (HERE / "policy.sha256").exists():
        check_lock(HERE / "policy.sha256")
    check_lock(DEV / "frozen.sha256" if split == "development" else HERE / "holdout.sha256")
    protocol = json.loads(protocol_path.read_text())
    pages = {key: grader.open_image(key, protocol_path.parent / source["path"])
             for key, source in protocol["sources"].items()}
    for key, page in pages.items():
        assert list(page.size) == protocol["sources"][key]["size"]
    policies = {"heading-first": lambda task, selected, budget, engine: grader.heading.run_reserved(
        task, selected, budget, engine, cross_probe=True), "horizontal-footer": run_letter}
    runtime, rows = grader.ReaderRuntime(), []
    with grader.OCR(runtime) as engine, grader.patch.object(grader.stamp_scan, "date_hits", grader.date_hits), (
        grader.patch.object(grader.stamp_scan, "MAX_CANDIDATES", 4)
    ):
        for index, case in enumerate(protocol["cases"]):
            gold = [protocol["fields"][key] for key in case["fields"]]
            task = grader.parse_task({"op": "verify", "fields": [{"anchor": field["anchor"]} for field in gold]})
            for group, label in enumerate(protocol["collections"]):
                document = gold[0]["page"]
                selected = [pages[document]] if label == "single" else list(pages.values())
                order = list(policies)[::(-1 if (index + group) % 2 else 1)]
                for name in order:
                    meter = Meter(engine)
                    start = perf_counter()
                    trace = policies[name](task, selected, protocol["budget"], meter)
                    elapsed = round((perf_counter() - start) * 1000, 2)
                    triggers = inspect_trace(trace, meter, task.fields[0].id)
                    checks = grader.score(task.fields, gold, trace, protocol)
                    strict = trace.get("answer") == {"result": "both_located"} and all(item["strict"] for item in checks)
                    rows.append(dict(document=document, case=case["id"], collection=label, policy=name,
                                     pages=[page.key for page in selected], fields=checks, strict=strict,
                                     triggers=triggers, trace=trace, wall_ms=elapsed))
    return {"split": split, "ocr": runtime.identifier, "protocol_sha256": digest(protocol_path), "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("split", choices=("development", "holdout"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output path")
    report = evaluate(args.split)
    with args.output.open("x") as handle:
        json.dump(report, handle, ensure_ascii=False, separators=(",", ":"))
