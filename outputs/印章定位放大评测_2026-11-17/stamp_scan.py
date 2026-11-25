"""Rank side-margin windows by ink density before spending OCR pixels."""
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from edge_scan import date_hits, observe_edge
from search_agent.core import ViewSpec, fit_area, overlap, area
from search_agent.scheduler import Ledger, read_hits, run
from search_agent.task import answer

THUMB_HEIGHT = 240
SIDE_FRACTION = .15
OUTER_TRIM = .015
WINDOW_FRACTION = .16
STRIDE_FRACTION = .04
MAX_CANDIDATES = 4
ZOOM_SHARE = .65


def side_candidates(page):
    width, height = page.size
    margin, trim = round(width * SIDE_FRACTION), round(width * OUTER_TRIM)
    for side, start, end, angle in (
        ("left", trim, margin, -90), ("right", width - margin, width - trim, 90)
    ):
        source = (start, 0, end, height)
        thumb_width = max(1, round((end - start) * THUMB_HEIGHT / height))
        thumb = page.image.crop(source).convert("L").resize((thumb_width, THUMB_HEIGHT), Image.Resampling.BOX)
        gray = np.asarray(thumb, dtype=float)
        threshold = np.percentile(gray, 75) - 22
        ink = gray < threshold
        # Long vertical rules and dark borders otherwise dominate the ranking.
        ink[:, ink.mean(axis=0) > .30] = False
        window = round(THUMB_HEIGHT * WINDOW_FRACTION)
        stride = round(THUMB_HEIGHT * STRIDE_FRACTION)
        offsets = sorted(set(range(0, THUMB_HEIGHT - window + 1, stride)) | {THUMB_HEIGHT - window})
        candidates = []
        for top in offsets:
            block = ink[top:top + window]
            density = float(block.mean())
            coverage = float(block.any(axis=1).mean())
            score = density * coverage
            if score <= 0:
                continue
            box = (start, round(top * height / THUMB_HEIGHT), end, round((top + window) * height / THUMB_HEIGHT))
            candidates.append({"page": page.key, "side": side, "box": box, "angle": angle,
                               "score": score, "ink_density": density, "row_coverage": coverage})
        yield {"page": page.key, "side": side, "box": source, "size": thumb.size,
               "threshold": float(threshold), "pixels": thumb.width * thumb.height}, candidates


def rank_candidates(pages):
    previews, candidates = [], []
    for page in pages:
        for preview, options in side_candidates(page):
            previews.append(preview)
            candidates.extend(options)
    ranked = sorted(candidates, key=lambda c: (-c["score"], c["page"], c["side"], c["box"][1]))
    kept = []
    for i, candidate in enumerate(ranked, 1):
        box = candidate["box"]
        duplicate = any(c["page"] == candidate["page"] and c["side"] == candidate["side"]
                        and overlap(c["box"], box) / area(box) > .45 for c in kept)
        candidate["rank"] = i
        candidate["decision"] = "overlap" if duplicate else "below_limit"
        if not duplicate and len(kept) < MAX_CANDIDATES:
            candidate["decision"] = "selected"
            kept.append(candidate)
    return previews, ranked, kept


def run_stamp(task, pages, budget, engine):
    if any(field.kind != "span" for field in task.fields):
        raise ValueError("Only exact span and date anchors are supported")
    previews, ranking, selected = rank_candidates(pages)
    preview_pixels = sum(p["pixels"] for p in previews)
    ledger = Ledger(budget - preview_pixels)
    pages_by_key = {p.key: p for p in pages}
    hits, details = {}, []
    zoom_cap = int(ledger.limit * ZOOM_SHARE)
    for index, candidate in enumerate(selected):
        if len(hits) == len(task.fields):
            break
        # A candidate may use native-resolution pixels, but leave some for the rest.
        left = zoom_cap - ledger.spent
        quota = left // (len(selected) - index)
        box, angle = candidate["box"], candidate["angle"]
        size = fit_area(box, quota)[::-1]
        spec = ViewSpec(f"stamp:{candidate['rank']}", -1, "stamp", box, size)
        page = pages_by_key[candidate["page"]]
        observation = ledger.buy(page, spec, lambda p, s: observe_edge(p, s, angle, engine),
                                 "ranked side-window", None)
        ledger.steps[-1]["rotation_deg_ccw"] = angle
        details.append({"page": page.key, "view": spec.key, "lines": observation["lines"]})
        read_hits(page, spec, observation, task.fields, hits)
        date_hits(page, spec, observation["lines"], task.fields, hits)
    pending = tuple(field for field in task.fields if field.id not in hits)
    steps, spent = ledger.steps, ledger.spent
    if pending:
        partial = run(replace(task, fields=pending), pages, ledger.remaining,
                      lambda page, spec: page.observe(spec, engine), "scan-audit")
        hits.update((hit["field"], hit) for hit in partial["evidence"])
        for step in partial["steps"]:
            step["step"] += len(steps)
            step["spent"] += spent
        steps = steps + partial["steps"]
        spent += partial["spent"]
    evidence = [hits[field.id] for field in task.fields if field.id in hits]
    result = answer(task, evidence)
    return {"strategy": "stamp-locate", "budget": budget, "spent": spent,
            "preview_pixels": preview_pixels, "total_pixels": spent + preview_pixels,
            "status": "answered" if result else ("partial" if evidence else "unresolved"),
            "answer": result, "evidence": evidence, "ocr_calls": len(steps), "steps": steps,
            "preview_observations": previews, "candidates": ranking, "edge_ocr": details}
