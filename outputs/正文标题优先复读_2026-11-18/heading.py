"""Switch from margin search to higher-resolution article bands after locating a date."""
from dataclasses import replace
from math import ceil, floor

import stamp_scan
from date_match import anchor_date
from date_repair import date_hits
from search_agent.core import ViewSpec, fit_area, overlap
from search_agent.scheduler import Ledger, best_hint, read_hits, run
from search_agent.task import answer


ORIGINAL_RUN_STAMP = stamp_scan.run_stamp


def article_windows(size):
    width, height = size
    left, top = round(.08 * width), round(.06 * height)
    right, bottom = width - left, height - top
    span = bottom - top
    # Three horizontal views with 15% overlap around each shared boundary.
    return [
        (left, top + round(max(0, (i - .225) / 3) * span),
         right, top + round(min(1, (i + 1.225) / 3) * span))
        for i in range(3)
    ]


def row_lines(lines):
    """Recombine nearby same-row fragments only for choosing a new OCR view."""
    rows = list(lines)
    for left in lines:
        x0, y0, x1, y1 = left["box"]
        height = y1 - y0
        for right in lines:
            xx0, yy0, _, yy1 = right["box"]
            if not 0 <= xx0 - x1 <= 2.5 * height:
                continue
            if min(y1, yy1) - max(y0, yy0) < .65 * min(height, yy1 - yy0):
                continue
            words = (left.get("raw_words") or left["words"]) + (right.get("raw_words") or right["words"])
            rows.append({"raw_words": words, "confidence": min(left["confidence"], right["confidence"])})
    return rows


def line_views(observations, pages, pending):
    candidates = []
    for row in observations:
        page = pages[row["page"]]
        if row["view"] == "article-alt-survey":
            continue
        source_lines = row_lines(row["lines"])
        for field in pending:
            hint = best_hint(source_lines, field)
            if not hint or hint.score < .46:
                continue
            left, top, right, bottom = hint.box
            height = bottom - top
            extra = max(2.2 * height, .25 * (right - left))
            box = (max(0, int(left - extra)), max(0, int(top - .33 * height)),
                   min(page.size[0], int(right + extra + 1)),
                   min(page.size[1], int(bottom + .33 * height + 1)))
            candidates.append((hint.score, hint.exact, hint.confidence, page, box, field, hint.text))
    return sorted(candidates, key=lambda item: item[:3], reverse=True)


def heading_views(observations, pages, pending):
    candidates = []
    for row in observations:
        if not row["view"].startswith("article-band:"):
            continue
        page = pages[row["page"]]
        width, height = page.size
        for line in row["lines"]:
            x0, y0, x1, y1 = line["box"]
            line_height, line_width = y1 - y0, x1 - x0
            center = abs((x0 + x1) / width - 1)
            if center > .10 or not .08 <= line_width / width <= .58 or line_height <= 0:
                continue
            words = [word for word in line["text"].split() if any(char.isalpha() for char in word)]
            if not words:
                continue
            upper = sum(char.isupper() for word in words for char in word)
            letters = sum(char.isalpha() for word in words for char in word)
            side = max(2.2 * line_height, .16 * line_width)
            box = (max(0, floor(x0 - side)), max(0, floor(y0 - .32 * line_height)),
                   min(width, ceil(x1 + side)), min(height, ceil(y1 + .32 * line_height)))
            for field in pending:
                if abs(len(words) - len(field.query)) > 2:
                    continue
                hint = best_hint([line], field)
                similarity = hint.score if hint else 0
                rank = similarity + .24 * (1 - center / .10) + .12 * upper / letters
                candidates.append((rank, similarity, line["confidence"], page, box, field, line["text"]))
    return sorted(candidates, key=lambda item: item[:3], reverse=True)


def run_reserved(task, pages, budget, engine, *, line_reread=True, cross_probe=False):
    date_fields = tuple(field for field in task.fields if anchor_date(field.anchor) is not None)
    if not 0 < len(date_fields) < len(task.fields):
        return ORIGINAL_RUN_STAMP(task, pages, budget, engine)

    previews, ranking, candidates = stamp_scan.rank_candidates(pages)
    preview_pixels = sum(preview["pixels"] for preview in previews)
    ledger = Ledger(budget - preview_pixels)
    # Leave at least forty percent for article OCR even when no date window succeeds.
    margin_cap = int(.60 * ledger.limit)
    by_key = {page.key: page for page in pages}
    hits, margin_reads, article_reads = {}, [], []
    for index, candidate in enumerate(candidates):
        if all(field.id in hits for field in date_fields):
            break
        quota = (margin_cap - ledger.spent) // (len(candidates) - index)
        if quota < 1:
            break
        box, angle = candidate["box"], candidate["angle"]
        page = by_key[candidate["page"]]
        spec = ViewSpec(f"stamp:{candidate['rank']}", -1, "stamp", box, fit_area(box, quota)[::-1])
        observation = ledger.buy(page, spec, lambda p, s: stamp_scan.observe_edge(p, s, angle, engine),
                                 "ranked date window", None)
        ledger.steps[-1]["rotation_deg_ccw"] = angle
        margin_reads.append({"page": page.key, "view": spec.key, "lines": observation["lines"]})
        read_hits(page, spec, observation, task.fields, hits)
        date_hits(page, spec, observation["lines"], date_fields, hits)

    stamp_keys = list(dict.fromkeys(hits[field.id]["page"] for field in date_fields if field.id in hits))
    body_fields = tuple(field for field in task.fields if field not in date_fields)
    if cross_probe and stamp_keys:
        other_keys = list(dict.fromkeys(row["page"] for row in margin_reads if row["page"] not in stamp_keys))
        if other_keys:
            quota = min(235_000, int(.29 * ledger.remaining) // len(other_keys))
            for key in other_keys:
                if all(field.id in hits for field in body_fields) or quota < 100_000:
                    break
                page = by_key[key]
                width, height = page.size
                x, y = round(.08 * width), round(.06 * height)
                box = (x, y, width - x, height - y)
                spec = ViewSpec("article-alt-survey", -1, "survey", box, fit_area(box, quota))
                observed = ledger.buy(page, spec, lambda p, s: p.observe(s, engine),
                                      "non-date page already seen during margin search", None)
                article_reads.append({"page": page.key, "view": spec.key, "lines": observed["lines"]})
                read_hits(page, spec, observed, body_fields, hits)

    if stamp_keys:
        chosen = [by_key[key] for key in stamp_keys]
        windows = [(page, box) for page in chosen for box in article_windows(page.size)]
        # Give the observed date pages the first look, retaining a cross-page fallback.
        scan_share = 1 if len(chosen) == len(pages) else .80
        body_cap = int(ledger.remaining * scan_share)
        body_spent_before = ledger.spent
        band_cap = int(.84 * body_cap) if line_reread else body_cap
        for index, (page, box) in enumerate(windows):
            if len(hits) == len(task.fields):
                break
            quota = (band_cap - (ledger.spent - body_spent_before)) // (len(windows) - index)
            if quota < 1:
                break
            spec = ViewSpec(f"article-band:{index + 1}", -1, "article-band", box, fit_area(box, quota))
            observation = ledger.buy(page, spec, lambda p, s: p.observe(s, engine),
                                     "article band on recognized date page", None)
            article_reads.append({"page": page.key, "view": spec.key, "lines": observation["lines"]})
            read_hits(page, spec, observation, task.fields, hits)
            date_hits(page, spec, observation["lines"], date_fields, hits)


        pending_body = [field for field in task.fields if line_reread and field.id not in hits and field not in date_fields]
        tried = []
        prioritize_heading = budget <= 1_000_000
        proposals = heading_views(article_reads, by_key, pending_body) if prioritize_heading else []
        proposals += line_views(article_reads, by_key, pending_body)
        for score, _, _, page, box, field, clue in proposals:
            if len(tried) == (4 if prioritize_heading else 2) or not ledger.remaining:
                break
            if field.id in hits or any(key == page.key and overlap(box, prior) for key, prior in tried):
                continue
            quota = min(ledger.remaining, body_cap - (ledger.spent - body_spent_before))
            if quota < 1:
                break
            tried.append((page.key, box))
            spec = ViewSpec(f"article-confirm:{field.id}:{len(tried)}", -1, "pdf-line", box, fit_area(box, quota))
            observed = ledger.buy(page, spec, lambda p, s: p.observe(s, engine),
                                  f"single line from article clue {clue} ({score:.2f})", field.id)
            article_reads.append({"page": page.key, "view": spec.key, "lines": observed["lines"]})
            read_hits(page, spec, observed, task.fields, hits)

    pending = tuple(field for field in task.fields if field.id not in hits)
    steps, spent = ledger.steps, ledger.spent
    if pending and ledger.remaining >= 100_000:
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
    return {"strategy": "date-then-article", "budget": budget, "spent": spent, "preview_pixels": preview_pixels,
            "total_pixels": spent + preview_pixels, "status": "answered" if result is not None else
            ("partial" if evidence else "unresolved"), "answer": result, "evidence": evidence,
            "ocr_calls": len(steps), "steps": steps, "preview_observations": previews,
            "candidates": ranking, "edge_ocr": margin_reads, "article_ocr": article_reads,
            "date_pages": stamp_keys}
