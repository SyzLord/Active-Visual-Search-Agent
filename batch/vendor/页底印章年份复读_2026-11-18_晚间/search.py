"""Search supplied images for a stamped date and an exact text anchor."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

import runtime
import evaluate as prior
from dates import requested_date
from receipt import run_receipt


class InputMeter(prior.Meter):
    def recognize(self, encoded, size, mode):
        lines = super().recognize(encoded, size, mode)
        self.calls[-1]["input_sha256"] = sha256(encoded).hexdigest()
        return lines


def run_query(policy, task, pages, engine):
    if policy == "receipt-year":
        runner = run_receipt
    elif policy == "horizontal-footer":
        runner = prior.run_letter
    elif policy == "heading-first":
        runner = lambda query, inputs, budget, reader: prior.grader.heading.run_reserved(
            query, inputs, budget, reader, cross_probe=True)
    else:
        raise ValueError(f"Unknown policy {policy}")
    meter = InputMeter(engine)
    with prior.grader.patch.object(prior.grader.stamp_scan, "date_hits", prior.grader.date_hits):
        trace = runner(task, pages, 1_000_000, meter)
    prior.inspect_trace(trace,meter,task.fields[0].id)
    for step,call in zip(trace["steps"],meter.calls,strict=True):
        step["input_sha256"] = call["input_sha256"]
    return trace


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images",type=Path,nargs="+")
    parser.add_argument("--date",required=True)
    parser.add_argument("--text",required=True)
    parser.add_argument("--policy",choices=("receipt-year","horizontal-footer","heading-first"),default="receipt-year")
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists() or not requested_date(args.date) or requested_date(args.text):
        parser.error("Use a new output path, one complete date and a non-date text anchor")
    task=prior.grader.parse_task({"op":"verify","fields":[{"anchor":args.date},{"anchor":args.text}]})
    pages=[prior.grader.open_image(f"p{index}",path) for index,path in enumerate(args.images,1)]
    engine_config=prior.grader.ReaderRuntime()
    with prior.grader.OCR(engine_config) as engine:
        trace=run_query(args.policy,task,pages,engine)
    trace.update(policy=args.policy,ocr=engine_config.identifier,input_files={p.key:str(path) for p,path in zip(pages,args.images)})
    from audit import provenance, pixel_cost
    date=requested_date(args.date)
    trace["reported_year"],_=provenance(trace,{page.key:page.size for page in pages},date.month,date.day)
    trace["cost"]=pixel_cost(trace)
    with args.output.open("x") as output:
        json.dump(trace,output,ensure_ascii=False,separators=(",",":"))
