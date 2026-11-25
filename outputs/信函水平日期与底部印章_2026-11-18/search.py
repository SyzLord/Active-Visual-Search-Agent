"""Locate a date and a phrase in supplied scans using the published letter policy."""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / name) for name in (
    "document-evidence-agent-v3.2", "印章定位放大评测_2026-11-17",
    "印章日期修复_2026-11-18", "正文标题优先复读_2026-11-18",
)]
from dates import requested_date
from date_repair import date_hits
import heading
import stamp_scan
from letter_search import run_letter
from search_agent.documents import open_image
from search_agent.reader import OCR, ReaderRuntime
from search_agent.task import parse_task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", type=Path, nargs="+")
    parser.add_argument("--date", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--policy", choices=("horizontal-footer", "heading-first"), default="horizontal-footer")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not requested_date(args.date) or requested_date(args.text):
        parser.error("Expected one complete date and one non-date text anchor")
    if args.output and args.output.exists():
        parser.error("Use a fresh output path")
    task = parse_task({"op": "verify", "fields": [{"anchor": args.date}, {"anchor": args.text}]})
    pages = [open_image(f"p{index:02d}", path) for index, path in enumerate(args.images, 1)]
    runtime = ReaderRuntime()
    with OCR(runtime) as engine, patch.object(stamp_scan, "date_hits", date_hits):
        if args.policy == "heading-first":
            result = heading.run_reserved(task, pages, 1_000_000, engine, cross_probe=True)
        else:
            result = run_letter(task, pages, 1_000_000, engine)
    result["policy"] = args.policy
    result["input_files"] = {page.key: path.name for page, path in zip(pages, args.images, strict=True)}
    result["ocr"] = runtime.identifier
    if args.output:
        with args.output.open("x") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
