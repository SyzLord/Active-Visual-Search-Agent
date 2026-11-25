"""Reconstruct every score and pixel account from saved OCR, without running OCR again."""
import argparse
import csv
import json
from pathlib import Path
from statistics import mean
import sys

from audit import assess
import runtime
import evaluate as prior


def records(protocol_path, trace_path):
    protocol=json.loads(protocol_path.read_text())
    report=json.loads(trace_path.read_text())
    assert report["protocol_sha256"]==prior.digest(protocol_path)
    cases={case["id"]:case for case in protocol["cases"]}
    expected={(case["id"],key,policy) for case in cases.values() for key in case["sets"]
              for policy in ("receipt-year","horizontal-footer")}
    seen=set()
    for row in report["rows"]:
        key=(row["case"],row["collection"],row["policy"])
        assert key not in seen and key in expected
        seen.add(key)
        case=cases[row["case"]]
        assert row["pages"]==case["sets"][row["collection"]]
        sizes={key:protocol["sources"][key]["size"] for key in row["pages"]}
        recalculated=assess(row["trace"],case,sizes)
        assert all(value==row[name] for name,value in recalculated.items()), key
        candidate=row["reported_year"] or {}
        yield dict(page=row["page"],case=row["case"],collection=row["collection"],policy=row["policy"],
                   year=int(row["year_ok"]),date=int(row["date_ok"]),text=int(row["text_ok"]),joint=int(row["joint_ok"]),
                   reported=candidate.get("year_raw",""),prefix=candidate.get("prefix_text",""),
                   year_line=candidate.get("year_line",""),year_view=candidate.get("year_view",""),
                   year_box=json.dumps(candidate.get("year_box",[])),**row["cost"],
                   fallback=int(any(step["stage"]=="global" for step in row["trace"]["steps"])))
    assert seen==expected


def summaries(rows):
    for policy in ("horizontal-footer","receipt-year"):
        subset=[row for row in rows if row["policy"]==policy]
        for page in [*sorted({row["page"] for row in subset}),"ALL"]:
            group=[row for row in subset if page=="ALL" or row["page"]==page]
            docs={row["page"] for row in group}
            yield dict(policy=policy,page=page,conditions=len(group),documents=len(docs),
                       any_year_documents=sum(any(row["year"] for row in group if row["page"]==doc) for doc in docs),
                       any_joint_documents=sum(any(row["joint"] for row in group if row["page"]==doc) for doc in docs),
                       **{name:sum(row[name] for row in group) for name in ("year","date","text","joint","fallback")},
                       **{"mean_"+name:round(mean(row[name] for row in group)) for name in
                          ("preview","footer_preview","footer_ocr","footer_reread","year_only","footer_total","total")},
                       max_total=max(row["total"] for row in group))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol",type=Path)
    parser.add_argument("trace",type=Path)
    parser.add_argument("--summary",action="store_true")
    args=parser.parse_args()
    rows=list(records(args.protocol,args.trace))
    if args.summary:
        rows=list(summaries(rows))
    writer=csv.DictWriter(sys.stdout,fieldnames=list(rows[0]),delimiter="\t",lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
