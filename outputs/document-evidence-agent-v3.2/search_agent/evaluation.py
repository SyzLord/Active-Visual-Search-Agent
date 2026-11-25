"""Check reference boxes, account for all paid observations, and aggregate by pack."""

from collections import defaultdict
import json
from pathlib import Path
import sqlite3
import zlib

import numpy as np

from .core import area, overlap
from .reader import OCR
from .scheduler import run, STRATEGIES
from .task import answer

BUDGETS = (1_600_000, 2_600_000, 4_000_000)
MAIN_BUDGET = BUDGETS[1]


def box_ok(pred, gold):
    if not pred or not gold or min(area(pred), area(gold)) <= 0:
        return False
    intersection = overlap(pred, gold)
    union = area(pred) + area(gold) - intersection
    return intersection / union >= .30 and intersection / area(gold) >= .48


def hit_ok(hit, gold):
    return (
        hit is not None and gold is not None and hit["page"] == gold["page"]
        and box_ok(hit["anchor_box"], gold["anchor_box"])
        and (gold["value"] is None or (
            hit["value"] == gold["value"] and box_ok(hit["value_box"], gold["value_box"])
        ))
    )


def check(case, task, response):
    found = {row["field"]: row for row in response["evidence"]}
    all_present = all(case.gold.values())
    hits = sum(hit_ok(found.get(field), gold) for field, gold in case.gold.items())
    false_cites = sum(not hit_ok(hit, case.gold[field]) for field, hit in found.items())
    expected = answer(task, list(case.gold.values())) if all_present else None
    answer_ok = response["answer"] == expected
    strict = answer_ok and false_cites == 0 and (not all_present or hits == len(case.gold))
    return {"positive": all_present, "evidence_hits": hits, "evidence_total": sum(v is not None for v in case.gold.values()),
            "false_cites": false_cites, "answer_ok": answer_ok, "strict": strict,
            "false_answer": not all_present and response["answer"] is not None}


class CachedReader:
    """Reuse identical renders across queries while keeping their simulated cost."""
    def __init__(self, path, runtime):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY, data BLOB NOT NULL)")
        self.engine = None
        self.runtime = runtime
        # The Python render/projection code and Pillow version also affect cached OCR.
        import PIL
        render_contract = "jpeg91-lanczos-pdfline-invert-v1"
        self.namespace = f"{runtime.identifier}-{PIL.__version__}-{render_contract}"
        self.hits = self.misses = 0

    def __call__(self, page, spec):
        if page.digest is None:
            raise ValueError("Benchmark pages require content hashes")
        key = json.dumps((self.namespace, page.digest, spec.box, spec.size, spec.scale == "pdf-line"), separators=(",", ":"))
        saved = self.db.execute("SELECT data FROM observations WHERE id = ?", (key,)).fetchone()
        if saved is not None:
            self.hits += 1
            return json.loads(zlib.decompress(saved[0]))
        if self.engine is None:
            self.engine = OCR(self.runtime)
        value = page.observe(spec, self.engine)
        data = zlib.compress(json.dumps(value, separators=(",", ":")).encode())
        self.db.execute("INSERT OR IGNORE INTO observations VALUES (?, ?)", (key, data))
        self.misses += 1
        return value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            if self.engine is not None:
                self.engine.close()
        finally:
            self.db.close()


def evaluate(packs, budgets, strategies, reader, ranker, progress=None):
    results = []
    for pack in packs:
        for case in pack.cases:
            task = case.task
            for budget in budgets:
                for strategy in strategies:
                    response = run(task, pack.pages, budget, reader, strategy, ranker)
                    row = check(case, task, response)
                    row.update(case=case.key, pack=pack.key, op=task.op, strategy=strategy, budget=budget,
                               answer=response["answer"], spent=response["spent"], status=response["status"],
                               calls=response["ocr_calls"], evidence=response["evidence"], steps=response["steps"],
                               pdf_candidates=response["pdf_candidates"],
                               possible_ambiguities=response["possible_ambiguities"],
                               field_assessments=response["field_assessments"])
                    results.append(row)
        if progress:
            progress(pack.key, len(results))
    return results


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["budget"], row["strategy"])].append(row)
    summary = []
    for (budget, strategy), all_rows in sorted(groups.items()):
        positive = [r for r in all_rows if r["positive"]]
        dual = [r for r in positive if r["op"] in ("compare", "difference", "verify")]
        negative = [r for r in all_rows if not r["positive"]]
        summary.append({
            "budget": budget, "strategy": strategy, "tasks": len(all_rows),
            "packs": len({r["pack"] for r in all_rows}), "positive": len(positive),
            "strict_positive": sum(r["strict"] for r in positive),
            "answer_only_positive": sum(r["answer_ok"] for r in positive),
            "dual": len(dual), "strict_dual": sum(r["strict"] for r in dual),
            "negative": len(negative), "false_answer": sum(r["false_answer"] for r in negative),
            "negative_no_false_cite": sum(r["false_cites"] == 0 for r in negative),
            "evidence_hits": sum(r["evidence_hits"] for r in all_rows),
            "evidence_total": sum(r["evidence_total"] for r in all_rows),
            "mean_pixels": round(sum(r["spent"] for r in all_rows) / len(all_rows)),
            "mean_calls": round(sum(r["calls"] for r in all_rows) / len(all_rows), 3),
            "max_pixels": max(r["spent"] for r in all_rows),
        })
    return summary


def paired(rows, policy, baseline):
    """Bootstrap entire synthetic packs to keep dependent tasks together."""
    keyed = {(r["case"], r["budget"], r["strategy"]): r for r in rows}
    output = []
    for budget in sorted({r["budget"] for r in rows}):
        packs = defaultdict(list)
        for r in rows:
            if r["budget"] == budget and r["positive"] and r["strategy"] == policy:
                other = keyed.get((r["case"], budget, baseline))
                if other is not None:
                    packs[r["pack"]].append(int(r["strict"]) - int(other["strict"]))
        if not packs:
            continue
        rng = np.random.default_rng(47)
        means = np.asarray([[sum(group), len(group)] for group in packs.values()])
        sampled = means[rng.integers(0, len(means), size=(4000, len(means)))].sum(axis=1)
        interval = np.quantile(sampled[:, 0] / sampled[:, 1], [.025, .975])
        output.append({"budget": budget, "policy": policy, "baseline": baseline, "packs": len(packs),
                       "delta_pp": round(100 * means[:, 0].sum() / means[:, 1].sum(), 3),
                       "pack_bootstrap_pp": [round(float(n) * 100, 3) for n in interval]})
    return output


def report(rows, split, reader, input_mode):
    comparisons = []
    if split in ("test", "dev"):
        for policy, baseline in (("adaptive", "uniform"), ("learned", "greedy"), ("greedy", "route-whole")):
            comparisons.extend(paired(rows, policy, baseline))
    return {"split": split, "input": input_mode, "ocr": reader.runtime.identifier, "summary": summarize(rows),
            "paired": comparisons, "rows": rows}
