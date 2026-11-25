"""Adjudicate repeated numeric evidence before releasing an answer."""

from dataclasses import replace

from .core import ViewSpec, overlap
from .task import field_matches


def adjudicate(task, pages, ledger, reader, inset=False):
    from .scheduler import adaptive_run, line_spec
    from .pdf_index import MAX_MATCHES

    matches = {field.id: [] for field in task.fields}
    candidates = {}
    states = {}
    truncated = set()
    for field in task.fields:
        options = []
        for page in pages:
            if field.pages and page.key not in field.pages:
                continue
            boxes = page.text_hints.get(field.query, ())
            if len(boxes) > MAX_MATCHES:
                truncated.add(field.id)
            options.extend((page, box) for box in boxes)
        candidates[field.id] = options
        states[field.id] = ["unread"] * len(options)

    # Round-robin fields so one repeated label cannot consume the whole budget first.
    for variant in (0, 1):
        for index in range(max(map(len, candidates.values()), default=0)):
            for field in task.fields:
                options = candidates[field.id]
                if index >= len(options) or states[field.id][index] in ("read", "no_numeric") or ledger.remaining < 5000:
                    continue
                page, box = options[index]
                spec = line_spec(page, box, field, ledger.remaining, variant)
                spec = ViewSpec(f"audit:{field.id}:{index + 1}.{variant + 1}",
                                spec.tile, spec.scale, spec.box, spec.size)
                existing = ledger.seen.get((page.key, spec.box, spec.size))
                if existing is None:
                    observation = ledger.buy(page, spec, reader, f"核验字段 {field.id} 的第 {index + 1} 个候选", field.id)
                else:
                    spec, observation = existing
                found = [hit for hit in field_matches(observation["lines"], field, page.key, spec.key)
                         if overlap(hit["anchor_box"], box) > 0]
                if found:
                    matches[field.id].extend(found)
                    states[field.id][index] = "read"
                else:
                    states[field.id][index] = "unreadable"
                    if field.kind == "number" and any(
                        overlap(hit["anchor_box"], box) > 0
                        for hit in field_matches(observation["lines"], replace(field, kind="span"), page.key, spec.key)
                    ):
                        states[field.id][index] = "no_numeric"

    # Fields without PDF candidates follow the image path using the remaining budget.
    fallback_fields = tuple(f for f in task.fields if not candidates[f.id])
    if fallback_fields:
        from .task import Task
        fallback = adaptive_run(Task(task.op, fallback_fields, task.unit), pages, ledger, reader, inset=inset)
        for field, hit in fallback.items():
            matches[field].append(hit)
        # Check all already-paid views for contradictory numeric evidence.
        for (page, _, _), (spec, observation) in ledger.seen.items():
            for field in fallback_fields:
                matches[field.id].extend(field_matches(observation["lines"], field, page, spec.key))

    accepted, assessments = {}, {}
    for field in task.fields:
        unique = {}
        for hit in matches[field.id]:
            key = (hit["page"], tuple(hit["anchor_box"]), hit["value"])
            unique.setdefault(key, hit)
        evidence = list(unique.values())
        values = sorted({hit["value"] for hit in evidence if hit["value"] is not None})
        pending = states[field.id].count("unread")
        unreadable = states[field.id].count("unreadable")
        status = "missing"
        if field.kind == "number" and len(values) > 1:
            status = "conflict"
        elif evidence:
            status = "accepted"
            if field.kind == "number" and (pending or unreadable or field.id in truncated):
                status = "needs_review"
            if status == "accepted":
                accepted[field.id] = max(evidence, key=lambda hit: hit["confidence"])
        assessments[field.id] = {
            "status": status, "values": values, "evidence": evidence,
            "candidate_count": len(candidates[field.id]), "unread": pending,
            "unreadable": unreadable, "candidate_limit_reached": field.id in truncated,
            "scope": "indexed_candidates" if candidates[field.id] else "observed_image_regions",
        }
    return accepted, assessments
