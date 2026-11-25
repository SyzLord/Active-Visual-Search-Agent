"""Summarize the paired trials, both by condition and by physical source page."""
import argparse
import csv
import json
from pathlib import Path
from statistics import mean
import sys


def detail(row):
    return dict(page=row["document"], case=row["case"], collection=row["collection"], policy=row["policy"],
                date_ok=int(row["fields"][0]["strict"]), text_ok=int(row["fields"][1]["strict"]),
                joint_ok=int(row["strict"]), date_iou=round(row["fields"][0]["iou"], 4),
                text_iou=round(row["fields"][1]["iou"], 4), **row["triggers"], preview=row["trace"]["preview_pixels"],
                ocr=row["trace"]["spent"], total=row["trace"]["total_pixels"])


def aggregate(policy, page, group):
    docs = sorted({item["page"] for item in group})
    doc_joints = [[item["joint_ok"] for item in group if item["page"] == doc] for doc in docs]
    counters = ("date_ok", "text_ok", "joint_ok", "early_date", "footer_tried", "footer_date", "date_reread",
                "text_reread", "fallback", "fallback_added")
    return dict(policy=policy, page=page, conditions=len(group), documents=len(docs),
                any_joint=sum(map(any, doc_joints)), all_joint=sum(map(all, doc_joints)),
                **{key: sum(item[key] for item in group) for key in counters},
                mean_preview=round(mean(item["preview"] for item in group)),
                mean_reread=round(mean(item["reread_pixels"] for item in group)),
                mean_pixels=round(mean(item["total"] for item in group)), max_pixels=max(item["total"] for item in group))


def tabulate(records):
    writer = csv.DictWriter(sys.stdout, fieldnames=list(records[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--rows", action="store_true")
    args = parser.parse_args()
    rows = [detail(row) for row in json.loads(args.file.read_text())["rows"]]
    groups = {}
    for row in rows:
        groups.setdefault((row["page"], row["case"], row["collection"]), []).append(row["policy"])
    assert all(sorted(names) == ["heading-first", "horizontal-footer"] for names in groups.values())
    if args.rows:
        tabulate(rows)
    else:
        summaries = []
        for policy in ("heading-first", "horizontal-footer"):
            subset = [row for row in rows if row["policy"] == policy]
            for page in sorted({row["page"] for row in subset}):
                summaries.append(aggregate(policy, page, [row for row in subset if row["page"] == page]))
            summaries.append(aggregate(policy, "ALL", subset))
        tabulate(summaries)
