"""Recompute historical geometry scores from the completed batch database."""
import argparse
import csv
import json
import os
from pathlib import Path
import sqlite3
from statistics import mean
import sys


HERE = Path(__file__).resolve().parent
BATCH = Path(os.environ.get("VISUAL_SEARCH_BATCH_DIR",HERE.parents[1] / "batch")).resolve()
sys.path.insert(0,str(BATCH))
from batch_engine import Engine, manifest


def load_saved(paths):
    results,runtimes = {},[]
    for manifest_path,db_path in paths:
        jobs,digest = manifest(manifest_path)
        with sqlite3.connect(db_path.resolve().as_uri()+"?mode=ro",uri=True) as db:
            db.row_factory = sqlite3.Row
            assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
            control, = db.execute("SELECT manifest,runtime FROM batch")
            assert control["manifest"]==digest
            runtimes.append(json.loads(control["runtime"]))
            rows = db.execute("SELECT id,state,result FROM jobs ORDER BY position").fetchall()
            for job,row in zip(jobs,rows,strict=True):
                assert job["id"]==row["id"] and row["state"]=="done" and row["id"] not in results
                results[row["id"]] = json.loads(row["result"])
    assert all(r==runtimes[0] for r in runtimes)
    return results,runtimes[0]


def base_steps(trace):
    cost = trace["baseline_total_pixels"]-trace["preview_pixels"]
    last, = [step["step"] for step in trace["steps"] if step["spent"]==cost]
    return trace["steps"][:last]


def scores(raw,runtime):
    # The same implementation and dependencies that the batch CLI imports.
    Engine()
    from audit import assess
    registry = json.loads((HERE/"holdout.json").read_text())
    output = {"runtime":runtime,"rows":[]}
    for case in registry["cases"]:
        for label,keys in case["sets"].items():
            paired = []
            for slug,policy in (("old","spare-stamp"),("new","month-routed-stamp")):
                task_id = f'{case["id"]}-{label}-{slug}'
                result = raw.pop(task_id)
                trace = result["trace"]
                assert result["policy"] == policy and result["ocr"]==runtime["ocr"]
                assert len(keys)==len(result["pages"])==len(result["sources"])
                page_map = {}
                for key,page,ident in zip(keys,result["pages"],result["sources"],strict=True):
                    declared = registry["sources"][key]
                    assert page["size"]==declared["size"] and ident["sha256"]==declared["sha256"]
                    assert ident["path"]==declared["path"]
                    page_map[page["id"]] = key
                right = next(p for p,k in page_map.items() if k==case["page"])
                sizes = {page["id"]:page["size"] for page in result["pages"]}
                score = assess(trace,{**case,"page":right},sizes)
                assert score["cost"]==result["decision"]["cost"]
                initial = base_steps(trace)
                extra = trace["steps"][len(initial):]
                assert all(len(s["input_sha256"])==64 for s in trace["steps"])
                read_pages = list(dict.fromkeys(page_map[s["page"]] for s in extra))
                evidence_reading = score["reported_year"]
                row = {"case":case["id"],"volume":registry["sources"][case["page"]]["volume"],"condition":label,
                       "policy":policy,"year":int(score["year_ok"]),"date":int(score["date_ok"]),
                       "text":int(score["text_ok"]),"joint":int(score["joint_ok"]),
                       "reported_year":evidence_reading["year_raw"] if evidence_reading else "",
                       "total_pixels":score["cost"]["total"],"footer_pixels":score["cost"]["footer_total"],
                       "extra_pixels":trace["extra_pixels"],"ocr_calls":len(trace["steps"]),"extra_calls":len(extra),
                       "extra_pages":",".join(read_pages),"extra_read_target":int(case["page"] in read_pages),
                       "decision":result["decision"]["status"],"trigger":trace["trigger"]}
                output["rows"].append(row)
                output.setdefault("evidence",{})[task_id] = {"score":score,"page_map":page_map,"result":result}
                paired.append((initial,trace["preview_observations"],base_body(trace)))
            assert paired[0]==paired[1],(case["id"],label)
    assert not raw
    return output


def base_body(trace):
    return [h for h in trace["evidence"] if h["field"]=="B"]


def write_tsv(path,rows):
    with path.open("x") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter="\t",lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def aggregate(rows):
    for sl,key in (("ALL",None),("single","condition"),("distractor","condition"),
                   ("aba1","volume"),("ccr28","volume"),("rfk7","volume")):
        for policy in ("spare-stamp","month-routed-stamp"):
            subset=[r for r in rows if (not key or r[key]==sl) and r["policy"]==policy]
            result = dict(group=sl,policy=policy,conditions=len(subset),documents=len({r["case"] for r in subset}))
            result.update({k:sum(r[k] for r in subset) for k in ("year","date","text","joint")})
            result.update({k+"_docs":len({r["case"] for r in subset if r[k]}) for k in ("year","date","text","joint")})
            result.update(mean_pixels=round(mean(r["total_pixels"] for r in subset)),
                          mean_footer=round(mean(r["footer_pixels"] for r in subset)),
                          max_pixels=max(r["total_pixels"] for r in subset),
                          extra_calls=sum(r["extra_calls"] for r in subset),
                          extra_on_target=sum(r["extra_read_target"] for r in subset),
                          extra_non_target_only=sum(bool(r["extra_pages"]) and not r["extra_read_target"] for r in subset))
            yield result


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--batch",type=Path,nargs=2,action="append",required=True,metavar=("MANIFEST","DATABASE"))
    cli.add_argument("--out",type=Path,required=True)
    args=cli.parse_args()
    report=scores(*load_saved(args.batch))
    args.out.mkdir(exist_ok=True)
    write_tsv(args.out/"rows.tsv",report["rows"])
    summarized=list(aggregate(report["rows"]))
    write_tsv(args.out/"summary.tsv",summarized)
    with (args.out/"raw-evidence.json").open("x") as out:
        json.dump(report,out,ensure_ascii=False,separators=(",",":"))
