"""Freeze geometry-based phrase annotations, then compare raster-only strategies."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from search_agent.documents import ROOT, pdf_pages
from search_agent.evaluation import CachedReader, check
from search_agent.corpus import Case
from search_agent.reader import ReaderRuntime
from search_agent.scheduler import run

DATA = ROOT / "data/heldout"

def freeze():
    import pdfplumber
    docs = []
    for path in sorted(DATA.glob("*.pdf")):
        data = path.read_bytes()
        with pdfplumber.open(path) as doc:
            selected = list(range(1, min(4, len(doc.pages)) + 1))
            images = pdf_pages(data, selected, "p-")
            rows = []
            for number, image in zip(selected, images):
                page = doc.pages[number - 1]
                midpoint = page.width / 2
                lines = [
                    line for left, right in ((0, midpoint), (midpoint, page.width))
                    for line in page.crop((left, 0, right, page.height)).extract_text_lines()
                ]
                candidates = []
                for line in lines:
                    words = re.findall(r"[A-Za-z]{3,}", line["text"])
                    if (len(words) < 7 or not .15 < line["top"] / page.height < .88
                            or line["x1"] - line["x0"] > .49 * page.width):
                        continue
                    phrase = " ".join(words[2:6])
                    occurrence = [(p.page_number, hit) for p in doc.pages[:len(selected)]
                                  for hit in p.search(re.escape(phrase), case=False)]
                    if len(occurrence) != 1 or occurrence[0][0] != number:
                        continue
                    hit = occurrence[0][1]
                    box = [hit[k] / dim * px for k, dim, px in
                           zip(("x0", "top", "x1", "bottom"), (page.width, page.height)*2, image.size*2)]
                    candidates.append({"anchor": phrase, "page": image.key, "anchor_box": box, "value": None})
                if candidates:
                    stride = max(1, len(candidates)//4)
                    rows.extend(candidates[::stride][:4])
            docs.append({"file": path.name, "title": doc.metadata.get("Title", ""), "sha256": hashlib.sha256(data).hexdigest(),
                         "pages": selected, "fields": rows})
    (DATA / "manifest.json").write_text(json.dumps(docs, indent=2) + "\n")

def evaluate(output, cache):
    docs = json.loads((DATA / "manifest.json").read_text())
    rows = []
    with CachedReader(cache, ReaderRuntime()) as reader:
        for doc in docs:
            data = (DATA / doc["file"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == doc["sha256"]
            pages = pdf_pages(data, doc["pages"], "p-")
            assert all(not page.text_hints for page in pages)
            pairs = [(a, b) for a, b in zip(doc["fields"][:len(doc["fields"])//2], reversed(doc["fields"]))
                     if a["page"] != b["page"]][:6]
            queries = [(a,) for a in doc["fields"]] + pairs
            for i, fields in enumerate(queries):
                raw = {"op": "verify" if len(fields) == 2 else "locate",
                       "fields": [{"anchor": f["anchor"]} for f in fields]}
                case = Case(f'{doc["file"]}-{i}', raw, dict(zip("AB", fields)))
                for budget in (1_600_000, 2_600_000):
                    for strategy in ("audited", "scan-audit"):
                        reply = run(case.task, pages, budget, reader, strategy)
                        reply.pop("elapsed_ms")
                        assert sum(s["pixels"] for s in reply["steps"]) == reply["spent"] <= budget
                        rows.append({"case": case.key, "task": raw, "gold": case.gold,
                                     **check(case, case.task, reply), **reply})
            print(doc["file"], len(queries), flush=True)
    output.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "results/heldout.json")
    parser.add_argument("--cache", type=Path, default=ROOT / "local/scan.sqlite")
    args = parser.parse_args()
    if args.freeze:
        freeze()
    else:
        evaluate(args.output, args.cache)
