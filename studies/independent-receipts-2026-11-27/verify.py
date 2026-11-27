"""Recreate the scheduler and results from stored OCR, without calling recognition."""
import argparse
import json
from pathlib import Path

from score import Engine, HERE, base_steps, load_saved, manifest, scores


def verify(paths,results):
    raw,runtime = load_saved(paths)
    stored = json.loads((results/"raw-evidence.json").read_text())
    assert scores(raw.copy(),runtime)==stored
    engine=Engine()
    from replay import RecordedReader
    all_calls=0
    for path,_ in paths:
        jobs,_ = manifest(path)
        for job in jobs:
            record = raw[job["id"]]
            trace = record["trace"]
            task,policy,pages,sources = engine.check(job,path.parent)
            assert sources==record["sources"]
            prefix = base_steps(trace)
            base_reader = RecordedReader(prefix)
            base = engine.query.run_query("horizontal-footer",task,pages,base_reader)
            assert base_reader.used==base_reader.hashed==len(prefix)
            suffix = trace["steps"][len(prefix):]
            after = RecordedReader(suffix)
            rerun = engine.query.POLICIES[policy](base,task,pages,after)
            assert after.used==after.hashed==len(suffix)
            assert json.loads(json.dumps(rerun))==trace
            decision=engine.query.source_checked(rerun,{page.key:page.size for page in pages},
                                                      engine.query.requested_date(job["date"]))
            assert json.loads(json.dumps(decision))==record["decision"]
            all_calls+=len(prefix)+len(suffix)
    return {"conditions":len(raw)//2,"trajectories":len(raw),"ocr_input_hashes_verified":all_calls,
            "new_ocr_calls":0,"all_decisions_scores_boxes_pixels_equal":True}


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--batch",type=Path,nargs=2,action="append",required=True,metavar=("MANIFEST","DATABASE"))
    cli.add_argument("--results",type=Path,default=HERE/"results")
    args=cli.parse_args()
    print(json.dumps(verify(args.batch,args.results),indent=2))
