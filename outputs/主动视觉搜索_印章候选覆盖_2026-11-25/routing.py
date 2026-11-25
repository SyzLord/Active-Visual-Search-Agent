"""Allocate the remaining pixel budget to footer regions supported by the query month."""
from copy import deepcopy
from dataclasses import dataclass
from difflib import SequenceMatcher
import re

import setup_paths
from audit import page_lines, pixel_cost
from dates import NAMES, NUMBERS
from evidence import source_checked
from imprint import combine, observed_years, prefixes
from receipt import clipped, read_crop
from reserve.refine import footer_clues
from search import InputMeter, requested_date
from search_agent.core import ViewSpec, area, fit_area, overlap, union_box
from search_agent.scheduler import Ledger
from search_agent.task import answer


MIN_PIXELS = 4_000
FOOTER_START = .67
MAX_CANDIDATES = 2
YEAR_TAIL = re.compile(r"[^A-Za-z0-9]*([0-9]{0,2})((?:1[6789]|20)[0-9]{2})[^A-Za-z0-9]*")


@dataclass(frozen=True)
class Candidate:
    page: str
    view: str
    text: str
    box: tuple
    year_box: tuple | None
    height: float
    rank: tuple


def approximate_month(token, month):
    word = re.sub("[^a-z]", "", token.lower())
    if word in NUMBERS:
        return 1.0 if NUMBERS[word] == month else 0.
    if not 2 <= len(word) <= 5:
        return 0.
    return SequenceMatcher(None, NAMES[month - 1][:3], word).ratio()


def bottom(box, size):
    return (box[1] + box[3]) / 2 >= FOOTER_START * size[1]


def trailing_box(word, size):
    match = YEAR_TAIL.fullmatch(word["text"])
    if not match:
        return None
    left, top, right, bottom_edge = word["box"]
    height = bottom_edge - top
    start = right - 4 * (right-left) / (4 + len(match[1]))
    return clipped((start-.10*height, top-.20*height, right+.17*height, bottom_edge+.20*height), size)


def month_candidates(step, size, date):
    for line in page_lines(step):
        words = line["raw_words"] or line["words"]
        for index, word in enumerate(words):
            score = approximate_month(word["text"], date.month)
            left, top, right, lower = word["box"]
            height = lower-top
            if score < .65 or height < 3 or not bottom(word["box"], size):
                continue
            neighbors = [w for w in words[index+1:index+4] if
                         0 <= w["box"][0]-right <= 7*height and
                         abs(w["box"][1]+w["box"][3]-top-lower) <= 1.8*height]
            numbers = [w for w in neighbors if re.search(r"[0-9]", w["text"])]
            day_seen = any(re.sub(r"\D","", w["text"]) == str(date.day) for w in numbers)
            if not numbers and score < 1.:
                continue
            row_box = union_box([word["box"], *[w["box"] for w in numbers]])
            rect = clipped((left-.60*height, row_box[1]-.46*height,
                            max(row_box[2]+.55*height, right+5.5*height), row_box[3]+.40*height), size)
            year_box = next((box for w in numbers if (box := trailing_box(w,size))), None)
            rank = (3 if day_seen else 2, score, line["confidence"])
            yield Candidate(step["page"],step["view"],line["text"],rect,year_box,height,rank)


def shortlist(base, sizes, date, body):
    allowed = {body["page"]} if body else set(sizes)
    candidates = []
    for step in base["steps"]:
        key = step["page"]
        if key in allowed and step.get("rotation_deg_ccw",0) == 0 and step["box"][3] >= FOOTER_START*sizes[key][1]:
            candidates.extend(month_candidates(step,sizes[key],date))
    for key in sorted(allowed):
        for clue in footer_clues(base,sizes,date,key):
            candidates.append(Candidate(key,clue.view,clue.text,clue.line,clue.year,
                                        clue.height,(1 if clue.known_prefix else 0,0.,0.)))
    selected = []
    for item in sorted(candidates,key=lambda c:c.rank,reverse=True):
        if area(item.box) < 9 or not bottom(item.box,sizes[item.page]):
            continue
        if any(old.page==item.page and overlap(old.box,item.box) >= .55*min(area(old.box),area(item.box))
               for old in selected):
            continue
        selected.append(item)
        if len(selected) == MAX_CANDIDATES:
            break
    return selected


def read_one(candidate, box, kind, quota, pages, ledger, meter, *, thin=False):
    if quota < MIN_PIXELS or area(box) < 9:
        return "", []
    scale = min(2.8, 57/max(1.,candidate.height))
    width,height = box[2]-box[0],box[3]-box[1]
    size = fit_area((0,0,round(scale*width),round(scale*height)),quota)
    # A changed filter is a real new observation and must still be metered.
    if (candidate.page,box,size) in ledger.seen:
        if not thin or size[0] < 3:
            return "", []
        size = (size[0]-1,size[1])
        if (candidate.page,box,size) in ledger.seen:
            return "", []
    view = f"routed-{kind}:{len(ledger.steps)+1}"
    spec = ViewSpec(view,-1,"pdf-line",box,size)
    obs = ledger.buy(pages[candidate.page],spec,lambda p,s:read_crop(p,s,meter,0.,thin),
                     f"Observed in {candidate.view}: {candidate.text}","A")
    call = meter.calls[-1]
    ledger.steps[-1].update(stage=f"receipt-{kind}",scope="footer",rotation_deg_ccw=0.,
                           light_stroke_filter=thin,engine_mode=call["mode"],
                           input_sha256=call["input_sha256"],raw_normalized=call["raw_normalized"])
    return view,obs["lines"]


def try_candidate(candidate,date,pages,ledger,meter,budget):
    limit = ledger.spent + budget
    page = pages[candidate.page]
    beginning = []
    endings = []
    year_box = candidate.year_box
    for kind,cap,thin in (("line",34_000,False),("year",16_000,False),("line",23_000,True)):
        box = year_box if kind=="year" else candidate.box
        if box is None:
            continue
        view,lines = read_one(candidate,box,kind,min(limit-ledger.spent,cap),pages,ledger,meter,thin=thin)
        for line in lines:
            beginning.extend(p for p in prefixes(line,candidate.page,view)
                             if (p.month,p.day)==(date.month,date.day))
            endings.extend((year,raw,box,view,line) for year,raw,box in observed_years(line))
            if kind=="line":
                observed = [trailing_box(w,page.size) for w in line["raw_words"] or line["words"]]
                if any(observed):
                    year_box = next(item for item in observed if item)
        for start in beginning:
            for year,raw,box,view,line in endings:
                if year != str(date.year) or not bottom(start.box,page.size) or not bottom(box,page.size):
                    continue
                proof = combine(start,year,raw,box,candidate.page,view,line)
                if proof:
                    return proof
    return None


def route(base,task,pages,engine):
    trace = deepcopy(base)
    by_key = {p.key:p for p in pages}
    sizes = {p.key:p.size for p in pages}
    field = task.fields[0]
    date = requested_date(field.anchor)
    decision = source_checked(base,sizes,date)
    body = decision["phrase_evidence"]
    existing = next((h for h in base["evidence"] if h["field"]=="A"),None)
    date_hit = existing if decision["receipt_date_evidence"] else None
    trace.update(strategy="month-routed-stamp",extra_clues=[],stamp_readings=[],baseline_total_pixels=base["total_pixels"])
    ledger = Ledger(base["budget"]-base["total_pixels"])
    meter = InputMeter(engine)
    if date_hit:
        trace["trigger"] = "already_verified"
    elif ledger.remaining < MIN_PIXELS:
        trace["trigger"] = "insufficient_remaining_budget"
    else:
        candidates = shortlist(base,sizes,date,body)
        trace["trigger"] = "ranked_footer_clue" if candidates else "no_paid_footer_clue"
        for index,c in enumerate(candidates):
            allowance = int(.65*ledger.remaining) if index+1<len(candidates) else ledger.remaining
            if allowance < MIN_PIXELS:
                break
            trace["extra_clues"].append({"page":c.page,"view":c.view,"text":c.text,"box":list(c.box),
                                         "score":list(c.rank),"allowance":allowance})
            proof = try_candidate(c,date,by_key,ledger,meter,allowance)
            if proof:
                trace["stamp_readings"].append(proof)
                date_hit = dict(field="A",anchor=field.anchor,page=c.page,view=proof["year_view"],
                                box=proof["anchor_box"],anchor_box=proof["anchor_box"],canonical_date=proof["canonical_date"],
                                line=proof["year_line"],matched_text=proof["prefix_text"]+" "+proof["year_raw"],
                                confidence=proof["confidence"],value=None,value_box=None,
                                match_type="observed_stamp_year",year_evidence=proof)
                break
    for step in ledger.steps:
        trace["steps"].append(dict(step,step=len(trace["steps"])+1,spent=base["spent"]+step["spent"]))
    trace["ocr_calls"] = len(trace["steps"])
    trace["spent"] += ledger.spent
    trace["total_pixels"] += ledger.spent
    trace["extra_pixels"] = ledger.spent
    trace["evidence"] = [hit for hit in (date_hit,body) if hit]
    trace["answer"] = answer(task,trace["evidence"]) if date_hit and body and date_hit["page"]==body["page"] else None
    trace["status"] = "answered" if trace["answer"] else "partial" if trace["evidence"] else "unresolved"
    pixel_cost(trace)
    return trace
