"""核对同页的收件章和指定文字，保留每条结论对应的原始观察。"""
import argparse
import json
import os
from pathlib import Path
import tempfile

from audit import pixel_cost, provenance
from search import prior, requested_date, run_query, runtime
from search_agent.documents import load_paths, page_range


DEFAULT_POLICY = "horizontal-footer"
POLICIES = (DEFAULT_POLICY, "receipt-year", "heading-first", "spare-stamp")
RESULT_FILES = {"development": "development-results.json", "holdout": "heldout-results.json",
                "negative": "negative-results.json"}


def encloses(outer, inner):
    # The two independent coordinate projections can differ by floating-point rounding.
    epsilon = .01
    return (outer[0] <= inner[0] + epsilon and outer[1] <= inner[1] + epsilon
            and outer[2] >= inner[2] - epsilon and outer[3] >= inner[3] - epsilon)


def source_checked(trace, sizes, date):
    observed, candidates = provenance(trace, sizes, date.month, date.day)
    hits = {hit["field"]: hit for hit in trace["evidence"]}
    date_hit = hits.get("A")
    body = hits.get("B")
    stamp = None
    if date_hit and date_hit.get("canonical_date") == date.isoformat():
        for proof in candidates:
            if (proof["exact_prefix"] and proof["year"] == str(date.year)
                    and proof["page"] == date_hit["page"] and proof["year_view"] == date_hit["view"]
                    and encloses(date_hit["anchor_box"], proof["prefix_box"])
                    and encloses(date_hit["anchor_box"], proof["year_box"])):
                stamp = proof
                break

    same_page = bool(stamp and body and stamp["page"] == body["page"])
    status = "verified" if same_page else "partial" if body or stamp or observed else "unresolved"
    reasons = []
    if not stamp:
        reasons.append("date_hit_has_no_footer_proof" if date_hit else "receipt_date_unread")
    if not body:
        reasons.append("phrase_unread")
    if stamp and body and not same_page:
        reasons.append("different_pages")
    return {"status": status, "reasons": reasons, "requested_date": date.isoformat(),
            "observed_year": observed, "receipt_date_evidence": stamp, "phrase_evidence": body,
            "same_page_verified": same_page, "cost": pixel_cost(trace)}


def recorded(split, case_id, collection, policy):
    directory = runtime.HERE
    protocol_path = directory / f"{split}.json"
    protocol = json.loads(protocol_path.read_text())
    report = json.loads((directory / RESULT_FILES[split]).read_text())
    if report["protocol_sha256"] != prior.digest(protocol_path):
        raise ValueError("登记与轨迹的文件摘要不一致")
    case = next((item for item in protocol["cases"] if item["id"] == case_id), None)
    row = next((item for item in report["rows"] if
                (item["case"], item["collection"], item["policy"]) == (case_id, collection, policy)), None)
    if not case or not row:
        raise ValueError("这组工单、页集和策略没有对应的实测记录")
    sizes = {key: protocol["sources"][key]["size"] for key in row["pages"]}
    return source_checked(row["trace"], sizes, requested_date(case["date"]))


def save_new(path, report):
    # Publish the finished file atomically; a concurrent query cannot overwrite it.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent) as staged:
        json.dump(report, staged, ensure_ascii=False, separators=(",", ":"))
        staged.flush()
        os.link(staged.name, path)


def query(args):
    if args.output.exists():
        raise ValueError("输出文件已存在，请使用新路径")
    if not args.output.parent.is_dir():
        raise ValueError("输出文件的父目录不存在")
    date = requested_date(args.date)
    if date is None or requested_date(args.text):
        raise ValueError("请输入一项完整日期和一项正文短语")
    task = prior.grader.parse_task({"op": "verify", "fields": [{"anchor": args.date}, {"anchor": args.text}]})
    pages = load_paths(args.files, page_range(args.pages), fields=())
    config = prior.grader.ReaderRuntime()
    with prior.grader.OCR(config) as engine:
        if args.policy == "spare-stamp":
            from reserve.refine import run_live
            trace = run_live(task, pages, engine)
        else:
            trace = run_query(args.policy, task, pages, engine)
    sizes = {page.key: page.size for page in pages}
    decision = source_checked(trace, sizes, date)
    report = {"schema": 1, "query": {"date": args.date, "text": args.text}, "policy": args.policy,
              "ocr": config.identifier, "pages": [{"id": p.key, "name": p.name, "size": p.size,
                  "input_fingerprint": p.digest} for p in pages], "decision": decision, "raw_trace": trace}
    save_new(args.output, report)
    return decision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    live = commands.add_parser("query", help="对本机图片或 PDF 实际运行")
    live.add_argument("files", type=Path, nargs="+")
    live.add_argument("--pages", help="单个 PDF 的页码，例如 2,5-7")
    live.add_argument("--date", required=True)
    live.add_argument("--text", required=True)
    live.add_argument("--policy", choices=POLICIES, default=DEFAULT_POLICY)
    live.add_argument("--output", required=True, type=Path)
    view = commands.add_parser("inspect", help="从已保存的原始 OCR 核验一个工单")
    view.add_argument("split", choices=tuple(RESULT_FILES))
    view.add_argument("case")
    view.add_argument("--collection", choices=("single", "with_other_letter"), default="single")
    view.add_argument("--policy", choices=POLICIES[:2], default=DEFAULT_POLICY)
    args = parser.parse_args()
    try:
        if args.command == "query":
            result = query(args)
        else:
            result = recorded(args.split, args.case, args.collection, args.policy)
    except (ValueError, OSError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
