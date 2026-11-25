"""Run the two unchanged policies on preregistered historical letters."""
import argparse
from functools import partial
import json
from pathlib import Path
import sys
from time import perf_counter
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
sys.path[:0] = [str(PARENT / name) for name in (
    "印章定位放大评测_2026-11-17", "印章日期修复_2026-11-18",
    "印章正文预算复验_2026-11-18", "正文标题优先复读_2026-11-18",
)]

from run_scan import area, overlap, open_image, OCR, ReaderRuntime, whole_spec, parse_task, digest
import stamp_scan
from date_match import anchor_date
from date_repair import date_hits
import heading
import reserved


def score(fields, gold, trace, protocol):
    selected = {hit["field"]: hit for hit in trace["evidence"]}
    results = []
    for field, expected in zip(fields, gold, strict=True):
        evidence = selected.get(field.id)
        correct_page = evidence is not None and evidence["page"] == expected["page"]
        target = expected["box"]
        pred = evidence["anchor_box"] if correct_page else None
        common = overlap(pred, target) if pred else 0
        coverage = common / area(target)
        iou = common / (area(pred) + area(target) - common) if pred else 0
        results.append({"field": field.id, "anchor": field.anchor, "found": evidence is not None,
                        "page_ok": correct_page, "iou": iou, "coverage": coverage,
                        "strict": iou >= protocol["iou_min"] and coverage >= protocol["gold_coverage_min"]})
    return results


def evaluate():
    for line in (HERE / "frozen.sha256").read_text().splitlines():
        expected, path = line.split("  ", 1)
        if digest(HERE / path) != expected:
            raise ValueError(f"Frozen input or code changed: {path}")
    protocol = json.loads((HERE / "protocol.json").read_text())
    pages = {key: open_image(key, HERE / item["path"]) for key, item in protocol["sources"].items()}
    for key, page in pages.items():
        assert list(page.size) == protocol["sources"][key]["size"], key
    runners = {"cross-probe": partial(reserved.run_reserved, cross_probe=True),
               "heading-first": partial(heading.run_reserved, cross_probe=True)}
    runtime = ReaderRuntime()
    rows = []
    budget = protocol["budget"]
    with OCR(runtime) as engine, patch.object(stamp_scan, "date_hits", date_hits), patch.object(
        stamp_scan, "MAX_CANDIDATES", protocol["window_cap"]
    ):
        first_page = next(iter(pages.values()))
        first_page.observe(whole_spec(first_page.size, 100_000), engine)
        for index, case in enumerate(protocol["cases"]):
            gold = [protocol["fields"][key] for key in case["fields"]]
            task = parse_task({"op": "verify", "fields": [{"anchor": item["anchor"]} for item in gold]})
            assert anchor_date(task.fields[0].anchor) and not anchor_date(task.fields[1].anchor)
            main = gold[0]["page"]
            other, = [key for key in pages if key != main]
            for set_index, label in enumerate(protocol["collections"]):
                collection = [pages[main]] if label == "single" else list(pages.values())
                assert label == "single" or {page.key for page in collection} == {main, other}
                names = protocol["policies"][::(-1 if (index + set_index) % 2 else 1)]
                for name in names:
                    start = perf_counter()
                    trace = runners[name](task, collection, budget, engine)
                    wall_ms = round(1000 * (perf_counter() - start), 2)
                    paid = 0
                    for number, step in enumerate(trace["steps"], 1):
                        width, height = step["size"]
                        assert step["pixels"] == width * height and step["step"] == number
                        paid += step["pixels"]
                        assert step["spent"] == paid
                    preview = sum(item["pixels"] for item in trace["preview_observations"])
                    assert preview == trace["preview_pixels"] and paid == trace["spent"]
                    assert trace["total_pixels"] == paid + preview <= budget
                    checks = score(task.fields, gold, trace, protocol)
                    rows.append({"case": case["id"], "collection": label, "policy": name,
                                 "pages": [page.key for page in collection], "wall_ms": wall_ms,
                                 "fields": checks, "strict": trace["answer"] == {"result": "both_located"}
                                 and all(item["strict"] for item in checks), "trace": trace})
    return {"protocol_sha256": digest(HERE / "protocol.json"), "ocr": runtime.identifier, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = evaluate()
    with args.output.open("x") as handle:
        json.dump(report, handle, ensure_ascii=False)
