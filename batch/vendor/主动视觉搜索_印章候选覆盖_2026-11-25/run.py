"""Run a local query, score paired experiments, or replay captured OCR."""
import argparse
import csv
import json
from pathlib import Path
import sys

from setup_paths import HERE, PREVIOUS
from audit import assess
from evidence import save_new, source_checked
from replay import RecordedReader
from reserve.refine import refine
from routing import route
from search import prior, requested_date, run_query
from search_agent.documents import load_paths, page_range


POLICIES = {"spare-stamp":refine,"month-routed-stamp":route}


def make_task(date,text):
    if not requested_date(date) or requested_date(text):
        raise ValueError("请输入完整英式月份日期与英文正文短语")
    return prior.grader.parse_task({"op":"verify","fields":[{"anchor":date},{"anchor":text}]})


def queries(split):
    root_lock = HERE/"policy.sha256"
    if root_lock.exists():
        prior.check_lock(root_lock)
    prior.check_lock(PREVIOUS/"policy.sha256")
    prior.check_lock(PREVIOUS/"reserve/policy.sha256")
    if split == "holdout":
        prior.check_lock(HERE/"holdout.sha256")
        path = HERE/"holdout.json"
        groups = [(path,None)]
    else:
        groups = [(PREVIOUS/(p+".json"),PREVIOUS/(f+".json")) for p,f in
                  (("development","development-results"),("holdout","heldout-results"),("negative","negative-results"))]
        groups.append((PREVIOUS/"reserve/holdout.json",PREVIOUS/"reserve/heldout-results.json"))
    for path,record in groups:
        prior.check_lock(path.with_suffix(".sha256"))
        manifest = json.loads(path.read_text())
        stamp = prior.digest(path)
        cached = json.loads(record.read_text()) if record else None
        if manifest["budget"] != 1_000_000:
            raise ValueError("Unexpected study budget")
        if not cached:
            assert manifest["policy_sha256"] == prior.digest(root_lock)
        pages = {}
        for key,source in manifest["sources"].items():
            image = prior.grader.open_image(key,path.parent/source["path"])
            assert image.size == tuple(source["size"])
            pages[key] = image
        for case in manifest["cases"]:
            task = make_task(case["date"],case["text"])
            for label,keys in case["sets"].items():
                base = None
                if cached:
                    if "protocol_sha256" in cached:
                        assert cached["protocol_sha256"] == stamp
                        row, = [r for r in cached["rows"] if (r["case"],r["collection"],r["policy"])==
                                 (case["id"],label,"horizontal-footer")]
                        base = row["trace"]
                    else:
                        row, = [r for r in cached["rows"] if (r["case"],r["collection"])==(case["id"],label)]
                        assert row["protocol_sha256"] == stamp
                        base = row["baseline_trace"]
                    assert row["pages"] == keys
                yield stamp,case,label,[pages[k] for k in keys],task,base


def compare(base,trace,case,sizes):
    n = len(base["steps"])
    assert trace["steps"][:n]==base["steps"]
    assert trace["preview_observations"]==base["preview_observations"]
    assert [h for h in trace["evidence"] if h["field"]=="B"] == [h for h in base["evidence"] if h["field"]=="B"]
    assert base["total_pixels"]+trace["extra_pixels"]==trace["total_pixels"]<=1_000_000
    return assess(trace,case,sizes)


def benchmark(split,fresh):
    config = prior.grader.ReaderRuntime()
    assert config.identifier == json.loads((PREVIOUS/"heldout-results.json").read_text())["ocr"]
    rows = []
    with prior.grader.OCR(config) as engine:
        for index,(digest,case,label,pages,task,cached) in enumerate(queries(split)):
            base = cached if cached and not fresh else run_query("horizontal-footer",task,pages,engine)
            row = dict(protocol_sha256=digest,case=case["id"],collection=label,pages=[p.key for p in pages],
                       baseline_origin="frozen_ocr" if cached and not fresh else "live_ocr",base=base,policies={})
            sizes = {p.key:p.size for p in pages}
            policies = list(POLICIES.items())
            if index%2:
                policies.reverse()
            for name,run in policies:
                trace = run(base,task,pages,engine)
                row["policies"][name] = dict(trace=trace,score=compare(base,trace,case,sizes))
            rows.append(row)
    return dict(split=split,ocr=config.identifier,rows=rows)


def replay(report):
    calls = digests = 0
    for row,(digest,case,label,pages,task,_) in zip(report["rows"],queries(report["split"]),strict=True):
        assert (row["protocol_sha256"],row["case"],row["collection"],row["pages"])==(
            digest,case["id"],label,[p.key for p in pages])
        base = row["base"]
        before = RecordedReader(base["steps"])
        restored = run_query("horizontal-footer",task,pages,before)
        for old,new in zip(base["steps"],restored["steps"],strict=True):
            if "input_sha256" not in old:
                new.pop("input_sha256")
        assert json.loads(json.dumps(restored))==base and before.used==len(base["steps"])
        calls += before.used
        digests += before.hashed
        for policy,result in row["policies"].items():
            steps = result["trace"]["steps"][before.used:]
            reader = RecordedReader(steps)
            rerun = POLICIES[policy](base,task,pages,reader)
            assert json.loads(json.dumps(rerun))==result["trace"] and reader.used==len(steps)
            assert compare(base,rerun,case,{p.key:p.size for p in pages})==result["score"]
            calls += reader.used
            digests += reader.hashed
    return dict(conditions=len(report["rows"]),calls_replayed=calls,input_digests_verified=digests,
                new_ocr_calls=0,decisions_scores_boxes_pixels_equal=True)


def table(report):
    output = csv.writer(sys.stdout,delimiter="\t",lineterminator="\n")
    output.writerow("case condition policy year date text joint raw_year pixels footer_pixels extra_pixels extra_calls candidate_pages".split())
    for row in report["rows"]:
        for policy in POLICIES:
            entry = row["policies"][policy]
            tr,score = entry["trace"],entry["score"]
            output.writerow([row["case"],row["collection"],policy,
                *[int(score[k+"_ok"]) for k in ("year","date","text","joint")],
                (score["reported_year"] or {}).get("year_raw",""),score["cost"]["total"],
                score["cost"]["footer_total"],tr["extra_pixels"],len(tr["steps"])-len(row["base"]["steps"]),
                ",".join(item["page"] for item in tr["extra_clues"])])


def query(args):
    task = make_task(args.date,args.text)
    pages = load_paths(args.files,page_range(args.pages),fields=())
    config = prior.grader.ReaderRuntime()
    with prior.grader.OCR(config) as engine:
        base = run_query("horizontal-footer",task,pages,engine)
        trace = POLICIES[args.policy](base,task,pages,engine)
    decision = source_checked(trace,{p.key:p.size for p in pages},requested_date(args.date))
    save_new(args.output,dict(query=dict(date=args.date,text=args.text),policy=args.policy,ocr=config.identifier,
        pages=[dict(id=p.key,name=p.name,size=p.size,input_fingerprint=p.digest) for p in pages],
        decision=decision,trace=trace))
    print(json.dumps(decision,ensure_ascii=False,indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command",required=True)
    live = sub.add_parser("query")
    live.add_argument("files",type=Path,nargs="+")
    live.add_argument("--pages")
    live.add_argument("--date",required=True)
    live.add_argument("--text",required=True)
    live.add_argument("--policy",choices=tuple(POLICIES),default="month-routed-stamp")
    live.add_argument("--output",type=Path,required=True)
    measure = sub.add_parser("benchmark")
    measure.add_argument("split",choices=("regression","holdout"))
    measure.add_argument("output",type=Path)
    measure.add_argument("--fresh-baseline",action="store_true")
    for name in ("replay","rows"):
        sub.add_parser(name).add_argument("file",type=Path)
    args = parser.parse_args()
    try:
        if args.command in ("query","benchmark") and (args.output.exists() or not args.output.parent.is_dir()):
            raise ValueError("请在已有目录下指定一个新的输出文件")
        if args.command=="query":
            query(args)
        elif args.command=="benchmark":
            save_new(args.output,benchmark(args.split,args.fresh_baseline))
        else:
            report = json.loads(args.file.read_text())
            if args.command=="replay":
                print(json.dumps(replay(report),indent=2))
            else:
                table(report)
    except (ValueError,OSError,RuntimeError) as error:
        parser.exit(2,f"{error}\n")


if __name__=="__main__":
    main()
