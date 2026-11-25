"""Paired cold-cache evaluation of archival JPEGs. Uses a warmed OCR process."""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean, median
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
FIXTURE = HERE.parent / "真实扫描评测_2026-11-17"
STRATEGIES = ("scan-audit", "edge-date", "stamp-locate")
PROJECT = HERE.parent / "document-evidence-agent-v3.2"
sys.path.insert(0, str(PROJECT))
from search_agent.core import area, overlap
from search_agent.documents import open_image
from search_agent.reader import OCR, ReaderRuntime
from search_agent.scheduler import run, whole_spec
from search_agent.task import parse_task
from edge_scan import run_edges
from stamp_scan import run_stamp

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def evaluate(smoke, edge_only=False):
    manifest = FIXTURE / "manifest.json"
    if digest(manifest) != (FIXTURE / "manifest.sha256").read_text().strip():
        raise ValueError("Frozen manifest hash mismatch")
    data = json.loads(manifest.read_text())
    pages = []
    for source in data["sources"]:
        path = FIXTURE / "data" / source["file"]
        if digest(path) != source["sha256"]:
            raise ValueError(f"Input hash mismatch: {path.name}")
        pages.append(open_image(source["page"], path))
    runtime = ReaderRuntime()
    rows = []
    with OCR(runtime) as engine:
        def read(page, spec):
            return page.observe(spec, engine)
        read(pages[0], whole_spec(pages[0].size, 100_000))
        cases = [c for c in data["cases"] if c["region"] != "body"]
        if smoke:
            cases = [c for c in cases if c["id"] == "scan17-08"]
        elif not edge_only:
            cases += [c for c in data["cases"] if c["region"] == "body"]
        for index, case in enumerate(cases):
            gold = case["gold"]
            task = parse_task({"op":case["op"], "fields":[{"anchor": v["anchor"]} for v in gold.values()]})
            for budget in data["budgets"][:1] if smoke else data["budgets"]:
                strategies = STRATEGIES[index % len(STRATEGIES):] + STRATEGIES[:index % len(STRATEGIES)]
                for strategy in strategies:
                    start = perf_counter()
                    if strategy == "stamp-locate":
                        result = run_stamp(task, pages, budget, engine)
                    elif strategy.startswith("edge-"):
                        result = run_edges(task, pages, budget, engine, strategy)
                    else:
                        result = run(task, pages, budget, read, strategy)
                    wall = 1000 * (perf_counter() - start)
                    seen = {e["field"]: e for e in result["evidence"]}
                    checks = {}
                    for field, expected in gold.items():
                        hit = seen.get(field)
                        page_ok = bool(hit and hit["page"] == expected["page"])
                        pred = hit["anchor_box"] if page_ok else None
                        target = expected["anchor_box"]
                        intersection = overlap(pred,target) if pred else 0
                        iou = intersection / (area(pred)+area(target)-intersection) if pred else 0
                        checks[field] = {"page_ok":page_ok,"iou":iou,
                                         "box_ok":iou >= .30 and intersection/area(target) >= .48}
                    strict = result["answer"] is not None and all(c["box_ok"] for c in checks.values())
                    assert sum(step["pixels"] for step in result["steps"]) == result["spent"]
                    assert result["spent"] + result.get("preview_pixels", 0) <= budget
                    rows.append({"id":case["id"],"region":case["region"],"gold":gold,"checks":checks,"strict":strict,"wall_ms":wall,**result})
    summary = []
    for budget in sorted({r["budget"] for r in rows}):
        for strategy, region in ((s, reg) for s in STRATEGIES for reg in ("all", "body", "edge", "mixed")):
            group = [r for r in rows if r["budget"] == budget and r["strategy"] == strategy
                     and (region == "all" or r["region"] == region)]
            if not group:
                continue
            summary.append({"strategy":strategy,"region":region,"budget":budget,"n":len(group),
                            "strict":sum(r["strict"] for r in group),
                            "fields_page_correct":sum(c["page_ok"] for r in group for c in r["checks"].values()),
                            "fields_box_correct":sum(c["box_ok"] for r in group for c in r["checks"].values()),
                            "ocr_pixels":sum(r["spent"] for r in group),
                            "total_pixels":sum(r.get("total_pixels", r["spent"]) for r in group),
                            "mean_ms":round(mean(r["wall_ms"] for r in group),2),
                            "median_ms":round(median(r["wall_ms"] for r in group),2)})
    return {"ocr":runtime.identifier,"manifest_sha256":digest(manifest),"summary":summary,"rows":rows}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke",action="store_true")
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--edge-only", action="store_true")
    args = parser.parse_args()
    report = evaluate(args.smoke, args.edge_only)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report["summary"],ensure_ascii=False))
