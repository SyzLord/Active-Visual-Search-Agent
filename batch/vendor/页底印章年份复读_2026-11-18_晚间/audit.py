"""Recover reported year words from the OCR trace and score original-page geometry."""
from copy import deepcopy

import runtime
from dates import NAMES, requested_date
from edge_scan import source_box
from imprint import attached, combine, damaged_prefixes, observed_years, prefixes
from receipt import back_project
from search_agent.core import area, overlap


def page_lines(step):
    lines = deepcopy(step["raw_normalized"])
    angle = step.get("rotation_deg_ccw", 0)
    def project(box):
        if angle in (90, -90):
            return source_box(box, step["box"], angle)
        return back_project(box, step["box"], step["size"], angle)
    for line in lines:
        line["box"] = project(line["box"])
        for word in line.get("raw_words", []) + line["words"]:
            word["box"] = project(word["box"])
    return lines


def same_box(first, second):
    return max(abs(a-b) for a,b in zip(first,second,strict=True)) < .01


def provenance(trace, sizes, month, day):
    views = {(step["page"], step["view"]): (step, page_lines(step)) for step in trace["steps"]}
    found = []
    def collect(prefix, raw_year, raw_word, box, year_key, line, strong):
        if not attached(prefix,box):
            return
        height = sizes[prefix.page][1]
        if min((prefix.box[1]+prefix.box[3])/2, (box[1]+box[3])/2) < .67*height:
            return
        found.append(dict(page=prefix.page, prefix_view=prefix.view, prefix_text=prefix.text,
                          prefix_box=list(prefix.box), exact_prefix=strong, year_view=year_key,
                          year=raw_year,year_raw=raw_word,year_box=list(box),year_line=line["text"],
                          confidence=line["confidence"]))
    for (page,view), (_,lines) in views.items():
        for line in lines:
            exact = [item for item in prefixes(line,page,view) if (item.month,item.day)==(month,day)]
            weak = list(damaged_prefixes(line,page,view,NAMES[month-1],day))
            for prefix,strong in [(p,True) for p in exact] + [(p,False) for p in weak]:
                for raw_year,raw_word,box in observed_years(line):
                    collect(prefix,raw_year,raw_word,box,view,line,strong)
    for proof in trace.get("stamp_readings", []):
        page = proof["page"]
        prefix_key,year_key = proof["prefix_view"],proof["year_view"]
        prefix_lines = views[(page,prefix_key)][1]
        year_lines = views[(page,year_key)][1]
        possible = [p for line in prefix_lines for p in prefixes(line,page,prefix_key)
                    if (p.month,p.day)==(month,day) and p.text==proof["prefix_text"] and
                    same_box(p.box,proof["prefix_box"])]
        actual = [(line,year,raw,box) for line in year_lines for year,raw,box in observed_years(line)
                  if raw==proof["year_raw"] and same_box(box,proof["year_box"])]
        assert possible and actual, "Reported stamp evidence has no matching paid source words"
        line,year,raw,box=actual[0]
        reproduced = combine(possible[0],year,raw,box,page,year_key,line)
        assert reproduced and reproduced["canonical_date"] == proof["canonical_date"]
        collect(possible[0],year,raw,box,year_key,line,True)
    def ranking(item):
        step=views[(item["page"],item["year_view"])][0]
        focused=step["stage"] in {"receipt-year","receipt-line","date-reread","receipt-context"}
        return item["exact_prefix"], focused, item["confidence"]
    return max(found,key=ranking,default=None), found


def pixel_cost(trace):
    preview=0
    bottom_preview=0
    for item in trace["preview_observations"]:
        pixels=item["size"][0]*item["size"][1]
        assert pixels==item["pixels"]
        preview+=pixels
        if item.get("scope")=="footer":
            bottom_preview+=pixels
    spent=bottom_ocr=tight=year_only=0
    for index,step in enumerate(trace["steps"],1):
        pixels=step["size"][0]*step["size"][1]
        spent+=pixels
        assert step["step"]==index and step["pixels"]==pixels and step["spent"]==spent
        assert step["ocr_lines"]==len(step["raw_normalized"])
        if step.get("scope")=="footer" or step["stage"]=="footer" or step["view"].startswith("footer-date-line:"):
            bottom_ocr+=pixels
            if step["stage"] in {"date-reread","receipt-line","receipt-year","receipt-prefix"}:
                tight+=pixels
            if step["stage"]=="receipt-year":
                year_only+=pixels
    assert len(trace["steps"])==trace["ocr_calls"] and spent==trace["spent"] and preview==trace["preview_pixels"]
    total=preview+spent
    assert total==trace["total_pixels"]<=trace["budget"]==1_000_000
    return dict(preview=preview,ocr=spent,footer_preview=bottom_preview,footer_ocr=bottom_ocr,
                footer_reread=tight,year_only=year_only,footer_total=bottom_ocr+bottom_preview,total=total)


def geometry(box,gold):
    if box is None:
        return {"iou":0., "coverage":0., "pass":False}
    common=overlap(box,gold)
    iou=common/(area(box)+area(gold)-common)
    coverage=common/area(gold)
    return {"iou":iou,"coverage":coverage,"pass":iou>=.30 and coverage>=.48}


def assess(trace,case,sizes):
    target=requested_date(case["date"])
    winner,readings=provenance(trace,sizes,target.month,target.day)
    hits={item["field"]:item for item in trace["evidence"]}
    date_hit,text_hit=hits.get("A"),hits.get("B")
    def right_page(item):
        return item is not None and item["page"]==case["page"]
    body=geometry(text_hit["anchor_box"] if right_page(text_hit) else None,case["text_box"])
    yr=str(target.year)
    possible=[reading for reading in readings if right_page(reading) and reading["exact_prefix"]
              and reading["year"]==yr and right_page(date_hit) and reading["year_view"]==date_hit["view"]
              and (not date_hit.get("year_evidence") or reading["prefix_view"]==date_hit["year_evidence"]["prefix_view"])]
    checks=[]
    for stamp in case["stamps"]:
        stamp_year=geometry(winner["year_box"] if right_page(winner) and winner["year"]==yr else None,stamp["year_box"])
        full_date=geometry(date_hit["anchor_box"] if right_page(date_hit) else None,stamp["date_box"])
        source_year=any(geometry(reading["year_box"],stamp["year_box"])["pass"] for reading in possible)
        checks.append(dict(year=stamp_year,date=full_date,same_imprint_year=source_year))
    verified=any(check["date"]["pass"] and check["same_imprint_year"] for check in checks)
    return dict(reported_year=winner,raw_year_candidates=readings,stamp_checks=checks,text_check=body,
                year_ok=any(check["year"]["pass"] for check in checks),date_ok=verified,text_ok=body["pass"],
                joint_ok=verified and body["pass"] and trace["answer"]=={"result":"both_located"},
                raw_at_gold=any(right_page(item) and item["year"]==yr and
                                any(geometry(item["year_box"],stamp["year_box"])["pass"] for stamp in case["stamps"])
                                for item in readings),cost=pixel_cost(trace))
