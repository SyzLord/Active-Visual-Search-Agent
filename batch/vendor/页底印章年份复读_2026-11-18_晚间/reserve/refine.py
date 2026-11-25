"""Spend only the unused part of the original letter search on observed footer clues."""
from copy import deepcopy
from dataclasses import dataclass
import re

from audit import page_lines, pixel_cost
from evidence import source_checked
from imprint import combine, observed_years, prefixes
from receipt import clipped, line_roi, read_crop, year_roi
from search import InputMeter, requested_date, run_query
from search_agent.core import ViewSpec, area, fit_area, overlap
from search_agent.scheduler import Ledger
from search_agent.task import answer


# The suffix can propose a crop. Only a separately recognized word can establish the year.
YEAR_END = re.compile(r"[^A-Za-z0-9]*([0-9]{0,2})((?:1[6789]|20)[0-9]{2})[^A-Za-z0-9]*")
MIN_EXTRA_PIXELS = 4000


@dataclass
class Clue:
    page: str
    view: str
    text: str
    line: tuple
    year: tuple
    prefix: tuple
    height: float
    priority: int
    known_prefix: object = None


def footer_clues(trace, sizes, date, body_page):
    clues = []
    for step in trace["steps"]:
        key = step["page"]
        if body_page and key != body_page:
            continue
        if step["stage"] != "footer" and not step["view"].startswith("footer-date-line:"):
            continue
        size = sizes[key]
        for line in page_lines(step):
            for pref in prefixes(line, key, step["view"]):
                if (pref.month, pref.day) == (date.month, date.day):
                    height = pref.last_box[3] - pref.last_box[1]
                    clues.append(Clue(key, step["view"], pref.text, line_roi(pref, size),
                                      year_roi(pref, [line], size), clipped(pref.box, size), height, 2, pref))
            for word in line.get("raw_words", line["words"]):
                match = YEAR_END.fullmatch(word["text"])
                if not match:
                    continue
                left, top, right, bottom = word["box"]
                height = bottom - top
                if height < 2 or (top + bottom) / 2 < .67 * size[1]:
                    continue
                count = len(match[1]) + 4
                start = right - (right - left) * 4 / count
                line_left = left - 4.5 * height
                band = clipped((line_left, top-.33*height, right+.40*height, bottom+.22*height), size)
                year = clipped((start-.08*height, top-.22*height, right+.24*height, bottom+.22*height), size)
                prefix = clipped((line_left, top-.35*height, start-.08*height, bottom+.20*height), size)
                clues.append(Clue(key, step["view"], word["text"], band, year, prefix, height, 1))
    selected = []
    for clue in sorted(clues, key=lambda c: -c.priority):
        if area(clue.line) < 9:
            continue
        if any(old.page == clue.page and overlap(old.line, clue.line) >= .65*min(area(old.line),area(clue.line))
               for old in selected):
            continue
        selected.append(clue)
        if len(selected) == 2:
            break
    return selected


def refine(base, task, pages, engine):
    trace = deepcopy(base)
    by_key = {p.key: p for p in pages}
    sizes = {p.key: p.size for p in pages}
    date_field, body_field = task.fields
    date = requested_date(date_field.anchor)
    if not date or date_field.id != "A" or body_field.id != "B":
        raise ValueError("This policy expects a receipt date followed by a phrase")
    original = source_checked(base, sizes, date)
    body = original["phrase_evidence"]
    date_hit = next((hit for hit in base["evidence"] if hit["field"] == date_field.id), None)
    trace["strategy"] = "spare-stamp"
    trace["baseline_total_pixels"] = original["cost"]["total"]
    trace["baseline_date_hit"] = deepcopy(date_hit)
    trace["stamp_readings"] = []
    trace["extra_clues"] = []
    free = trace["budget"] - trace["baseline_total_pixels"]
    ledger = Ledger(free)
    meter = InputMeter(engine)

    def observe(clue, box, kind, cap):
        if ledger.remaining < MIN_EXTRA_PIXELS or area(box) < 9:
            return "", []
        scale = min(3., 46 / max(1., clue.height))
        size = fit_area((0, 0, max(1, round((box[2]-box[0])*scale)),
                        max(1, round((box[3]-box[1])*scale))), min(ledger.remaining, cap))
        if (clue.page, box, size) in ledger.seen:
            return "", []
        view = f"spare-{kind}:{len(ledger.steps)+1}"
        spec = ViewSpec(view, -1, "pdf-line", box, size)
        obs = ledger.buy(by_key[clue.page], spec, lambda p,s: read_crop(p,s,meter,0.,False),
                         f"paid {clue.view} clue: {clue.text}", date_field.id)
        call = meter.calls[-1]
        ledger.steps[-1].update(stage=f"receipt-{kind}", scope="footer", rotation_deg_ccw=0.,
                               light_stroke_filter=False, engine_mode=call["mode"],
                               input_sha256=call["input_sha256"], raw_normalized=call["raw_normalized"])
        return view, obs["lines"]

    if original["receipt_date_evidence"]:
        trace["trigger"] = "already_verified"
    elif free < MIN_EXTRA_PIXELS:
        trace["trigger"] = "insufficient_remaining_budget"
        date_hit = None
    else:
        date_hit = None
        clues = footer_clues(base, sizes, date, body["page"] if body else None)
        trace["trigger"] = "paid_footer_clue" if clues else "no_paid_footer_clue"
        for clue in clues:
            if date_hit or ledger.remaining < MIN_EXTRA_PIXELS:
                break
            trace["extra_clues"].append({"page":clue.page, "view":clue.view, "text":clue.text, "box":list(clue.line)})
            month_days = [clue.known_prefix] if clue.known_prefix else []
            years = []
            for kind,box,cap in (("line",clue.line,32_000), ("year",clue.year,16_000), ("prefix",clue.prefix,20_000)):
                view, lines = observe(clue, box, kind, cap)
                for line in lines:
                    month_days.extend(p for p in prefixes(line, clue.page, view)
                                      if (p.month,p.day) == (date.month,date.day))
                    years.extend((y,raw,b,view,line) for y,raw,b in observed_years(line))
                for prefix in month_days:
                    for year,raw,year_box,year_view,line in years:
                        proof = combine(prefix,year,raw,year_box,clue.page,year_view,line)
                        if not proof or proof in trace["stamp_readings"]:
                            continue
                        trace["stamp_readings"].append(proof)
                        if proof["canonical_date"] == date.isoformat() and date_hit is None:
                            date_hit = dict(field=date_field.id, anchor=date_field.anchor, page=clue.page, view=year_view,
                                anchor_box=proof["anchor_box"], box=proof["anchor_box"], canonical_date=proof["canonical_date"],
                                matched_text=prefix.text+" "+raw, confidence=proof["confidence"], line=proof["year_line"],
                                value=None, value_box=None, match_type="observed_stamp_year", year_evidence=proof)
                if date_hit:
                    break

    for step in ledger.steps:
        trace["steps"].append(dict(step, step=len(trace["steps"])+1, spent=base["spent"]+step["spent"]))
    trace["ocr_calls"] = len(trace["steps"])
    trace["spent"] += ledger.spent
    trace["total_pixels"] += ledger.spent
    trace["extra_pixels"] = ledger.spent
    trace["evidence"] = [hit for hit in (date_hit, body) if hit]
    trace["answer"] = answer(task, trace["evidence"]) if date_hit and body and date_hit["page"] == body["page"] else None
    trace["status"] = "answered" if trace["answer"] else ("partial" if trace["evidence"] else "unresolved")
    pixel_cost(trace)
    return trace


def run_live(task, pages, engine):
    return refine(run_query("horizontal-footer", task, pages, engine), task, pages, engine)
