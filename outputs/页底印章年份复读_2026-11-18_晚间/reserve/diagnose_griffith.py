"""After scoring only: measure what the original OCR can read at a manually known location."""
import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))

from evidence import save_new
from receipt import clipped, read_crop
from search import InputMeter, prior
from search_agent.core import area, fit_area, overlap, ViewSpec


def measure():
    prior.check_lock(HERE/"policy.sha256")
    prior.check_lock(HERE.parent/"holdout.sha256")
    registry = json.loads((HERE.parent/"holdout.json").read_text())
    case, = [r for r in registry["cases"] if r["id"]=="G1"]
    reg = json.loads((HERE/"regression-results.json").read_text())
    row, = [r for r in reg["rows"] if r["case"]=="G1" and r["collection"]=="single"]
    base = row["baseline_trace"]
    extended = row["refined_trace"]
    bottom, = [s for s in base["steps"] if s["stage"]=="footer"]
    extra = extended["steps"][row["baseline_steps_preserved"]:]
    page = prior.grader.open_image("griffith",HERE.parent/registry["sources"]["griffith"]["path"])
    config = prior.grader.ReaderRuntime()
    assert config.identifier==reg["ocr"]
    readings=[]
    used=extended["total_pixels"]
    with prior.grader.OCR(config) as engine:
        for field,kind in (("date_box","line"),("year_box","year")):
            automatic, = [s for s in extra if s["stage"]=="receipt-"+kind]
            target=case["stamps"][0][field]
            left,top,right,bottom_edge=target
            pad=round(.15*(bottom_edge-top))
            box=clipped((left-pad,top-pad,right+pad,bottom_edge+pad),page.size)
            factor=automatic["size"][0]/(automatic["box"][2]-automatic["box"][0])
            scaled=(0,0,round((box[2]-box[0])*factor),round((box[3]-box[1])*factor))
            size=fit_area(scaled,1_000_000-used)
            spec=ViewSpec("oracle-"+kind,-1,"pdf-line",box,size)
            meter=InputMeter(engine)
            observed=read_crop(page,spec,meter,0.,False)
            call,=meter.calls
            used+=size[0]*size[1]
            readings.append(dict(field=field,human_box=target,survey_box=bottom["box"],
                survey_gold_coverage=overlap(bottom["box"],target)/area(target),
                auto_box=automatic["box"],auto_gold_coverage=overlap(automatic["box"],target)/area(target),
                auto_raw_text=[l["text"] for l in automatic["raw_normalized"]],
                oracle_box=box,oracle_size=list(size),oracle_pixels=spec.pixels,oracle_call=call,
                oracle_page_lines=observed["lines"]))
    assert used <= 1_000_000
    return dict(case="G1/single",kind="posthoc_oracle_diagnostic",independent_score=False,ocr=config.identifier,
        automatic_total=extended["total_pixels"],oracle_pixels=used-extended["total_pixels"],
        combined_pixels=used,readings=readings)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output file")
    save_new(args.output,measure())
