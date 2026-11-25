"""Rebuild the frozen fixtures and audit the archived scores, counters and live repeat."""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from PIL import Image, ImageChops, ImageDraw

from evidence import source_checked
from prepare_inputs import extract
from recompute import records
from replay import check_replay
from search import prior, requested_date, runtime


def verify(rebuilt, repeat_path):
    here = runtime.HERE
    for prefix in ("policy","development","negative","holdout"):
        prior.check_lock(here/(prefix+".sha256"))
    with redirect_stdout(sys.stderr):
        extract(here/"data",rebuilt)
    for key in ("griffith","cowell"):
        assert prior.digest(here/"data"/(key+".png")) == prior.digest(rebuilt/(key+".png"))

    dev = json.loads((here/"development.json").read_text())
    negative = json.loads((here/"negative.json").read_text())
    with Image.open(here/dev["sources"]["diggs"]["path"]) as original:
        masked = original.convert("RGB")
    draw = ImageDraw.Draw(masked)
    for box in negative["erased_boxes"]:
        draw.rectangle(box,fill="white")
    with Image.open(here/"control/diggs-masked.png") as stored:
        assert masked.size==stored.size and ImageChops.difference(masked,stored.convert("RGB")).getbbox() is None
    with (rebuilt/"diggs-masked.png").open("xb") as out:
        masked.save(out,format="PNG")
    assert prior.digest(rebuilt/"diggs-masked.png")==prior.digest(here/"control/diggs-masked.png")

    summary = {"matching_locks":4,"native_scans_rebuilt":2,"masked_scan_rebuilt_byte_for_byte":True}
    for split,file in (("development","development-results.json"),("negative","negative-results.json"),
                       ("holdout","heldout-results.json")):
        protocol = here/(split+".json")
        rows = list(records(protocol,here/file))
        replay = check_replay(protocol,here/file)
        assert replay == json.loads((here/(split+"-replay.json")).read_text())
        summary[split] = {"recomputed_rows":len(rows),**replay}
        if split=="negative":
            assert all(not row["reported"] and not row["date"] for row in rows)
    example = json.loads((here/"wrong-year-query.json").read_text())
    check = source_checked(example["raw_trace"],{p["id"]:p["size"] for p in example["pages"]},
                           requested_date(example["query"]["date"]))
    assert check==example["decision"] and check["observed_year"]["year"]=="1958" and not check["receipt_date_evidence"]
    summary["wrong_year_query"]={"requested":check["requested_date"],"read":"1958","pixels":check["cost"]["total"]}
    if repeat_path:
        old,new = [json.loads(p.read_text()) for p in (here/"heldout-results.json",repeat_path)]
        assert old["protocol_sha256"]==new["protocol_sha256"] and old["ocr"]==new["ocr"]
        for left,right in zip(old["rows"],new["rows"],strict=True):
            assert {k:v for k,v in left.items() if k!="wall_ms"}=={k:v for k,v in right.items() if k!="wall_ms"}
        summary["independent_live_repeat"]={"rows":len(new["rows"]),"actual_calls":
            sum(r["trace"]["ocr_calls"] for r in new["rows"]),"all_except_time_equal":True}
    return summary


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh-repeat",type=Path)
    parser.add_argument("--rebuild-dir",type=Path,help="New directory for the three regenerated PNGs")
    args=parser.parse_args()
    with TemporaryDirectory() as temp:
        destination=Path(temp)
        if args.rebuild_dir:
            args.rebuild_dir.mkdir()
            destination=args.rebuild_dir
        print(json.dumps(verify(destination,args.fresh_repeat),indent=2))
