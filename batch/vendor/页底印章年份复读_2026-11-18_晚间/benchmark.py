"""Run both policies against the registered cases. Reference boxes are used only for grading."""
import argparse
import json
from pathlib import Path
from time import perf_counter

from search import prior, run_query, runtime
from audit import assess


def load_case_pages(protocol):
    pages = {}
    for key, source in protocol["sources"].items():
        path = runtime.HERE / source["path"]
        image = prior.grader.open_image(key,path)
        if list(image.size) != source["size"]:
            raise ValueError(f"Input dimensions differ for {key}")
        pages[key] = image
    return pages


def old_trace(case, label, page_keys, identifier):
    report = json.loads((runtime.HERE / case["baseline_cache"]).read_text())
    assert report["ocr"]==identifier
    row, = [row for row in report["rows"] if row["case"]==case["id"] and row["collection"]==label
            and row["policy"]=="horizontal-footer"]
    assert row["pages"]==page_keys
    assert [field["anchor"] for field in row["fields"]]==[case["date"],case["text"]]
    return row["trace"]


def run_benchmark(protocol_path, fresh_baseline):
    protocol=json.loads(protocol_path.read_text())
    prior.check_lock(runtime.OLD/"policy.sha256")
    prior.check_lock(runtime.OLD/"holdout.sha256")
    prior.check_lock(prior.DEV/"frozen.sha256")
    for lock in ("policy.sha256",protocol_path.stem+".sha256"):
        if protocol["split"]=="holdout" or (runtime.HERE/lock).is_file():
            prior.check_lock(runtime.HERE/lock)
    if protocol["split"]=="holdout":
        assert protocol["policy_sha256"]==prior.digest(runtime.HERE/"policy.sha256")
    pages=load_case_pages(protocol)
    engine_config=prior.grader.ReaderRuntime()
    assert engine_config.identifier==json.loads((runtime.OLD/"heldout-results.json").read_text())["ocr"]
    rows=[]
    with prior.grader.OCR(engine_config) as engine:
        for index,case in enumerate(protocol["cases"]):
            task=prior.grader.parse_task({"op":"verify","fields":[{"anchor":case["date"]},{"anchor":case["text"]}]})
            for group,(label,page_keys) in enumerate(case["sets"].items()):
                subset=[pages[key] for key in page_keys]
                sizes={key:pages[key].size for key in page_keys}
                policies=["horizontal-footer","receipt-year"]
                if (index+group)%2:
                    policies.reverse()
                for policy in policies:
                    replay=(policy=="horizontal-footer" and protocol["split"]=="development" and
                            not fresh_baseline and "baseline_cache" in case)
                    start=perf_counter()
                    trace=old_trace(case,label,page_keys,engine_config.identifier) if replay else run_query(
                        policy,task,subset,engine)
                    elapsed=None if replay else round(1000*(perf_counter()-start),2)
                    rows.append(dict(case=case["id"],page=case["page"],collection=label,pages=page_keys,
                                policy=policy,origin="previous-frozen-trace" if replay else "live-local-ocr",
                                wall_ms=elapsed,**assess(trace,case,sizes),trace=trace))
    return dict(ocr=engine_config.identifier,protocol_sha256=prior.digest(protocol_path),rows=rows)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("split",choices=("development","holdout","negative"))
    parser.add_argument("output",type=Path)
    parser.add_argument("--fresh-baseline",action="store_true")
    args=parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output file")
    result=run_benchmark(runtime.HERE/(args.split+".json"), args.fresh_baseline)
    with args.output.open("x") as handle:
        json.dump(result,handle,ensure_ascii=False,separators=(",",":"))
