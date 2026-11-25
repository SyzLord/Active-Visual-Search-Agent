"""Compare the deployed baseline with its suffix, retaining every paid observation."""
import argparse
import csv
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
sys.path.insert(0, str(PARENT))

from audit import assess
from evidence import save_new
from refine import refine
from replay import RecordedReader
from search import prior, run_query


def inputs(split):
    prior.check_lock(PARENT/"policy.sha256")
    prior.check_lock(HERE/"policy.sha256")
    if split == "regression":
        groups = [("development", "development", "development-results"),
                  ("former_holdout", "holdout", "heldout-results"), ("masked", "negative", "negative-results")]
        for label, case_file, result_file in groups:
            prior.check_lock(PARENT/(case_file+".sha256"))
            source = json.loads((PARENT/(result_file+".json")).read_text())
            path = PARENT/(case_file+".json")
            assert source["protocol_sha256"] == prior.digest(path)
            yield label, path, source
    else:
        prior.check_lock(HERE/"holdout.sha256")
        yield "new_holdout", HERE/"holdout.json", None


def registered(split):
    for label, path, source in inputs(split):
        protocol = json.loads(path.read_text())
        if label == "new_holdout":
            assert protocol["policy_sha256"] == prior.digest(HERE/"policy.sha256")
        pages = {}
        for key,info in protocol["sources"].items():
            image = prior.grader.open_image(key,path.parent/info["path"])
            assert list(image.size) == info["size"]
            pages[key] = image
        digest = prior.digest(path)
        for case in protocol["cases"]:
            task = prior.grader.parse_task({"op":"verify", "fields":[{"anchor":case["date"]},{"anchor":case["text"]}]})
            for group, keys in case["sets"].items():
                old = None
                if source:
                    old, = [row for row in source["rows"] if (row["case"],row["collection"],row["policy"]) ==
                            (case["id"],group,"horizontal-footer")]
                    assert old["pages"] == keys
                yield label, digest, case, group, [pages[key] for key in keys], task, old


def compare(base, extended, case, sizes):
    prefix = len(base["steps"])
    assert base["steps"] == extended["steps"][:prefix]
    assert base["preview_observations"] == extended["preview_observations"]
    baseline_body = [h for h in base["evidence"] if h["field"]=="B"]
    assert baseline_body == [h for h in extended["evidence"] if h["field"]=="B"]
    before, after = [assess(trace,case,sizes) for trace in (base,extended)]
    assert before["text_ok"] == after["text_ok"]
    assert extended["total_pixels"] - base["total_pixels"] == extended["extra_pixels"] <= 1_000_000 - base["total_pixels"]
    return {"baseline":before,"spare_stamp":after,"body_evidence_identical":True,
            "baseline_steps_preserved":prefix,"extra_ocr_calls":len(extended["steps"])-prefix}


def measure(split, fresh):
    config = prior.grader.ReaderRuntime()
    assert config.identifier == json.loads((PARENT/"heldout-results.json").read_text())["ocr"]
    rows = []
    with prior.grader.OCR(config) as engine:
        for label,digest,case,group,pages,task,old in registered(split):
            base = old["trace"] if old and not fresh else run_query("horizontal-footer",task,pages,engine)
            extended = refine(base,task,pages,engine)
            checks = compare(base,extended,case,{p.key:p.size for p in pages})
            rows.append(dict(sample=label, case=case["id"], collection=group, pages=[p.key for p in pages],
                protocol_sha256=digest, baseline_origin="frozen_ocr" if old and not fresh else "live_ocr",
                baseline_trace=base, refined_trace=extended, **checks))
    return dict(split=split,ocr=config.identifier,policy_sha256=prior.digest(HERE/"policy.sha256"),rows=rows)


def verify(report):
    assert report["policy_sha256"] == prior.digest(HERE/"policy.sha256")
    calls = byte_checks = 0
    for row,registration in zip(report["rows"],registered(report["split"]),strict=True):
        label,digest,case,group,pages,task,_ = registration
        assert (row["sample"],row["case"],row["collection"],row["pages"],row["protocol_sha256"]) == (
            label,case["id"],group,[p.key for p in pages],digest)
        base, extended = row["baseline_trace"], row["refined_trace"]
        reader = RecordedReader(base["steps"])
        rebuilt = run_query("horizontal-footer",task,pages,reader)
        for original, current in zip(base["steps"],rebuilt["steps"],strict=True):
            if "input_sha256" not in original:
                current.pop("input_sha256")
        assert reader.used == len(base["steps"]) and json.loads(json.dumps(rebuilt)) == base
        suffix = RecordedReader(extended["steps"][reader.used:])
        result = refine(rebuilt,task,pages,suffix)
        assert json.loads(json.dumps(result)) == extended
        assert suffix.used == row["extra_ocr_calls"]
        checks = compare(base,extended,case,{p.key:p.size for p in pages})
        assert all(row[key] == val for key,val in checks.items())
        calls += reader.used + suffix.used
        byte_checks += reader.hashed + suffix.hashed
    return dict(rows=len(report["rows"]),baseline_and_suffix_calls_replayed=calls,encoded_inputs_verified=byte_checks,
                all_scores_decisions_boxes_costs_identical=True,new_ocr_calls=0)


def table(report):
    writer = csv.writer(sys.stdout,delimiter="\t",lineterminator="\n")
    writer.writerow("sample case collection policy year date text joint observed_year pixels footer_pixels extra_pixels extra_calls trigger".split())
    for row in report["rows"]:
        for policy,trace_key in (("baseline","baseline_trace"),("spare_stamp","refined_trace")):
            score = row[policy]
            tr = row[trace_key]
            writer.writerow([row["sample"],row["case"],row["collection"],policy,
                *[int(score[k+"_ok"]) for k in ("year","date","text","joint")],
                (score["reported_year"] or {}).get("year_raw",""),score["cost"]["total"],score["cost"]["footer_total"],
                tr.get("extra_pixels",0),row["extra_ocr_calls"] if policy=="spare_stamp" else 0,tr.get("trigger","")])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command",required=True)
    run = commands.add_parser("run")
    run.add_argument("split",choices=("regression","holdout"))
    run.add_argument("output",type=Path)
    run.add_argument("--fresh-baseline",action="store_true")
    for name in ("verify","rows"):
        commands.add_parser(name).add_argument("report",type=Path)
    args = parser.parse_args()
    if args.command == "run":
        if args.output.exists():
            parser.error("Use a new output path")
        save_new(args.output,measure(args.split,args.fresh_baseline))
    else:
        report = json.loads(args.report.read_text())
        if args.command == "verify":
            print(json.dumps(verify(report)))
        else:
            table(report)
