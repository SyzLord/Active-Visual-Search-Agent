"""Read a year from an actual footer imprint, then search for its companion phrase."""
from dataclasses import replace
from difflib import SequenceMatcher
from io import BytesIO
from math import atan, ceil, cos, degrees, floor, radians, sin
import re

import numpy as np
from PIL import Image, ImageFilter, ImageOps

import runtime
from dates import NAMES, requested_date
from imprint import attached, combine, damaged_prefixes, observed_years, prefixes
from search_agent.core import ViewSpec, area, fit_area, overlap
from search_agent.scheduler import Ledger, best_hint, read_hits, run
from search_agent.task import answer


def clipped(box, size):
    return (max(0, floor(box[0])), max(0, floor(box[1])), min(size[0], ceil(box[2])), min(size[1], ceil(box[3])))


def back_project(box, crop, size, angle):
    width, height = size
    cx, cy = width / 2, height / 2
    cosine, sine = cos(radians(angle)), sin(radians(angle))
    points = []
    for hor in (box[0], box[2]):
        for ver in (box[1], box[3]):
            dx, dy = hor * width - cx, ver * height - cy
            x = min(width, max(0, cx + cosine*dx - sine*dy))
            y = min(height, max(0, cy + sine*dx + cosine*dy))
            points.append((crop[0] + x/width*(crop[2]-crop[0]), crop[1] + y/height*(crop[3]-crop[1])))
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]


def read_crop(page, spec, engine, angle, thin):
    gray = page.image.crop(spec.box).resize(spec.size, Image.Resampling.LANCZOS).convert("L")
    raster = ImageOps.autocontrast(gray, cutoff=(.35, .35))
    if thin:
        raster = Image.blend(raster, raster.filter(ImageFilter.MaxFilter(3)), .70)
    if angle:
        raster = raster.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=255)
    data = BytesIO()
    raster.save(data, "PNG")
    lines = engine.recognize(data.getvalue(), raster.size, "line" if spec.scale == "pdf-line" else "page")
    for line in lines:
        line["box"] = back_project(line["box"], spec.box, spec.size, angle)
        for word in line["words"] + line.get("raw_words", []):
            word["box"] = back_project(word["box"], spec.box, spec.size, angle)
    return {"box": list(spec.box), "size": list(spec.size), "lines": lines}


def preview(page, max_pixels):
    width, height = page.size
    box = (0, int(.67 * height), width, height)
    size = fit_area(box, max_pixels)
    gray = page.image.crop(box).resize(size, Image.Resampling.BOX).convert("L")
    background = np.asarray(gray.filter(ImageFilter.GaussianBlur(2.5)), dtype=np.int16)
    ink = (background - np.asarray(gray, dtype=np.int16)) > 13
    ink[:, ink.mean(axis=0) > .48] = False
    ink[ink.mean(axis=1) > .62, :] = False
    tiles = []
    for top in (0., .43):
        for left in (0., .24, .48):
            right, bottom = left + .52, top + .57
            sample = ink[round(top*size[1]):round(bottom*size[1]), round(left*size[0]):round(right*size[0])]
            tile_box = (round(left*width), box[1]+round(top*(height-box[1])),
                        round(right*width), box[1]+round(bottom*(height-box[1])))
            score = float(sample.mean() * (sample.mean(axis=1) > .015).mean()) if sample.size else 0.
            tiles.append(dict(box=tile_box, score=score))
    tiles.sort(key=lambda item: item["score"], reverse=True)
    return dict(page=page.key, scope="footer", box=box, size=size, pixels=size[0]*size[1],
                score=tiles[0]["score"], tiles=tiles)


def year_roi(prefix, lines, size):
    left, top, right, bottom = prefix.last_box
    height = bottom - top
    for line in lines:
        for word in line.get("raw_words") or line["words"]:
            candidate = word["box"]
            if re.fullmatch(r"[^A-Za-z0-9]*[0-9]{1,5}[^A-Za-z0-9]*", word["text"]) and attached(prefix, candidate):
                start, yt, end, yb = candidate
                return clipped((start-.33*height, min(top, yt)-.32*height,
                                max(end+.34*height, start+3.2*height), max(bottom, yb)+.32*height), size)
    center = (top+bottom)/2 + 2.2*height*prefix.slope
    return clipped((right+.03*height, center-.92*height, right+4.55*height, center+.92*height), size)


def line_roi(prefix, size):
    left, top, right, bottom = prefix.box
    height = prefix.last_box[3] - prefix.last_box[1]
    end_shift = 4.4*height*prefix.slope
    return clipped((left-.55*height, top-.45*height+min(0., end_shift),
                    right+4.7*height, bottom+.45*height+max(0., end_shift)), size)


def context_boxes(lines, day, month, size):
    clues = []
    for line in lines:
        words = line.get("raw_words") or line["words"]
        for word in words:
            token = re.sub("[^a-z0-9]", "", word["text"].lower())
            left, top, right, bottom = word["box"]
            height, width = bottom-top, right-left
            if height < 1:
                continue
            if token.startswith(("receiv", "recd", "filed")):
                cx = (left+right)/2
                half = max(4.8*height, 1.18*width)
                box = (cx-half, bottom-.35*height, cx+half, bottom+4.8*height)
                clues.append((3, clipped(box, size), word["text"]))
            elif token == str(day) or token in (month, month[:3]):
                box = (left-6.5*height, top-.7*height, right+6.5*height, bottom+.7*height)
                clues.append((2 if token==str(day) else 1, clipped(box, size), word["text"]))
    return sorted(clues, key=lambda item: -item[0])


def damaged_rows(lines, month, day, size):
    options = []
    for line in lines:
        words = line.get("raw_words") or line["words"]
        for index, word in enumerate(words[:-1]):
            letters = re.sub("[^a-z]", "", word["text"].lower())
            affinity = SequenceMatcher(None, month[:3], letters).ratio()
            if affinity < .60:
                continue
            digits = re.sub("[^0-9]", "", words[index+1]["text"])
            if not digits or not digits.startswith(str(day)):
                continue
            boxes = [word["box"], words[index+1]["box"]]
            height = min(box[3]-box[1] for box in boxes)
            if height < 1 or boxes[1][0]-boxes[0][2] > 3*height:
                continue
            fused = len(digits) >= len(str(day))+3
            if not fused and index+2 < len(words):
                following = words[index+2]
                if re.search(r"[0-9]", following["text"]) and following["box"][0]-boxes[-1][2] < 3*height:
                    boxes.append(following["box"])
            left = boxes[0][0] - 1.15*height
            right = boxes[-1][2] + (.55 if fused or len(boxes)==3 else 4.6)*height
            top = min(box[1] for box in boxes)-.28*height
            bottom = max(box[3] for box in boxes)+.32*height
            options.append((affinity,clipped((left,top,right,bottom),size),height,line["text"]))
    return sorted(options,key=lambda item:-item[0])


class ReceiptSearch:
    def __init__(self, task, pages, budget, engine):
        self.task, self.pages, self.engine, self.budget = task, pages, engine, budget
        self.field, = [field for field in task.fields if requested_date(field.anchor)]
        self.text_fields = tuple(field for field in task.fields if field != self.field)
        self.target = requested_date(self.field.anchor)
        if not pages or budget < 6 * len(pages):
            raise ValueError("The budget must cover at least one preview pixel per page and an OCR reserve")
        preview_quota = min(24_000, budget // (6 * len(pages)))
        self.previews = [preview(page, preview_quota) for page in pages]
        self.preview_pixels = sum(item["pixels"] for item in self.previews)
        self.ledger = Ledger(budget-self.preview_pixels)
        self.footer_cap = int(.66 * self.ledger.limit)
        self.page_cap = self.footer_cap
        self.by_key = {page.key: page for page in pages}
        self.hits, self.observations, self.proofs = {}, [], []
        self.tried_prefixes = []
        self.rechecked_months = []

    def buy(self, page, box, quota, label, reason, *, line=False, angle=0., thin=False, char_height=None):
        receipt = label.startswith("receipt-")
        available = min(self.ledger.remaining, self.page_cap-self.ledger.spent) if receipt else self.ledger.remaining
        quota = min(available, quota)
        if quota < 600 or area(box) < 9:
            return None
        width, height = box[2]-box[0], box[3]-box[1]
        scale = min(3., 46/max(1., char_height)) if line and char_height else 1.
        size = fit_area((0, 0, max(1, round(width*scale)), max(1, round(height*scale))), quota)
        if (page.key, tuple(box), size) in self.ledger.seen:
            return None
        name = f"{label}:{len(self.ledger.steps)+1}"
        spec = ViewSpec(name, -1, "pdf-line" if line else label, tuple(box), size)
        obs = self.ledger.buy(page, spec, lambda p,s: read_crop(p,s,self.engine,angle,thin), reason)
        self.ledger.steps[-1].update(stage=label, scope="footer" if receipt else "body",
                                     rotation_deg_ccw=angle, light_stroke_filter=thin)
        read_hits(page, spec, obs, self.text_fields, self.hits)
        row = dict(page=page.key, view=name, stage=label, lines=obs["lines"])
        self.observations.append(row)
        return row

    def match(self, row, previous=()):
        if not row:
            return []
        local = [item for line in row["lines"] for item in prefixes(line, row["page"], row["view"])
                 if (item.month, item.day) == (self.target.month, self.target.day)]
        for prefix in [*local, *previous]:
            for line in row["lines"]:
                for token, raw, box in observed_years(line):
                    proof = combine(prefix, token, raw, box, row["page"], row["view"], line)
                    if not proof:
                        continue
                    self.proofs.append(proof)
                    if proof["canonical_date"] == self.target.isoformat() and self.field.id not in self.hits:
                        self.hits[self.field.id] = dict(field=self.field.id, anchor=self.field.anchor,
                            page=row["page"], view=row["view"], anchor_box=proof["anchor_box"], box=proof["anchor_box"],
                            canonical_date=proof["canonical_date"], matched_text=prefix.text+" "+raw,
                            confidence=proof["confidence"], line=proof["year_line"], value=None, value_box=None,
                            match_type="observed_stamp_year", year_evidence=proof)
        return local

    def confirm(self, page, row):
        local = self.match(row)
        if not row or self.field.id in self.hits:
            return
        self.verify_month(page,row)
        for prefix in local:
            if self.field.id in self.hits or len(self.tried_prefixes) >= 5:
                break
            if any(old.page == prefix.page and overlap(old.box,prefix.box) > .62*min(area(old.box),area(prefix.box))
                   for old in self.tried_prefixes):
                continue
            self.tried_prefixes.append(prefix)
            char_height = prefix.last_box[3]-prefix.last_box[1]
            angle = round(degrees(atan(prefix.slope)), 2)
            year = self.buy(page, year_roi(prefix,row["lines"],page.size), 26_000, "receipt-year",
                            f"digits beside {prefix.text} from {prefix.view}", line=True, angle=angle,
                            char_height=char_height, thin=True)
            self.match(year, [prefix])
            if self.field.id not in self.hits:
                full = self.buy(page, line_roi(prefix,page.size), 54_000, "receipt-line",
                                f"whole stamp line from {prefix.view}", line=True, angle=angle, char_height=char_height)
                self.match(full, [prefix])
                if full and self.field.id not in self.hits:
                    self.verify_month(page,full)

    def verify_month(self,page,row):
        for line in row["lines"]:
            for clue in damaged_prefixes(line,page.key,row["view"],NAMES[self.target.month-1],self.target.day):
                years = [item for item in observed_years(line) if attached(clue,item[2])]
                if not years or self.field.id in self.hits or len(self.rechecked_months)>=3:
                    continue
                if any(key==page.key and overlap(old,clue.box)>.60*min(area(old),area(clue.box))
                       for key,old in self.rechecked_months):
                    continue
                self.rechecked_months.append((page.key,clue.box))
                left,top,right,bottom=clue.box
                height=bottom-top
                region=clipped((left-.28*height,top-.36*height,right+.34*height,bottom+.36*height),page.size)
                check=self.buy(page,region,25_000,"receipt-prefix","confirm uncertain printed month and day",
                               line=True,angle=round(degrees(atan(clue.slope)),2),char_height=height*46/34)
                if check:
                    exact=self.match(check)
                    if exact:
                        self.match(row,exact)

    def find_stamp(self):
        eligible = [item for item in self.previews if not self.field.pages or item["page"] in self.field.pages]
        ordered = sorted(eligible, key=lambda item: -item["score"])
        for index, thumb in enumerate(ordered):
            if self.field.id in self.hits:
                break
            page = self.by_key[thumb["page"]]
            per_page = (self.footer_cap-self.ledger.spent)//(len(ordered)-index)
            self.page_cap = self.ledger.spent + per_page
            spent_before_survey = self.ledger.spent
            survey = self.buy(page, thumb["box"], min(300_000,int(.63*per_page)), "receipt-survey",
                              "bottom third, ordered by preview ink")
            if not survey:
                continue
            survey_pixels = self.ledger.spent - spent_before_survey
            self.confirm(page, survey)
            for _, box, height, clue in damaged_rows(survey["lines"],NAMES[self.target.month-1],
                                                    self.target.day,page.size)[:2]:
                if self.field.id in self.hits:
                    break
                row = self.buy(page,box,42_000,"receipt-line",f"partial stamp OCR: {clue}",
                               line=True,char_height=height)
                self.confirm(page,row)
            contexts = context_boxes(survey["lines"], self.target.day, NAMES[self.target.month-1], page.size)
            contexts += [(0,item["box"],"thumbnail ink") for item in thumb["tiles"][:2]]
            tried = []
            for priority, box, clue in contexts:
                if self.field.id in self.hits or len(tried) == 3:
                    break
                if any(overlap(box,other) > .68*min(area(box),area(other)) for other in tried):
                    continue
                tried.append(box)
                quota = min(70_000, max(0, per_page - survey_pixels)//2)
                row = self.buy(page, box, quota, "receipt-context", f"stamp context: {clue}", thin=priority>0)
                self.confirm(page, row)

    def text_lines(self, tried):
        candidates = []
        for row in self.observations:
            if row["stage"] not in {"receipt-survey","receipt-context","body-survey"}:
                continue
            for field in self.text_fields:
                if field.id in self.hits or (field.pages and row["page"] not in field.pages):
                    continue
                hint = best_hint(row["lines"], field)
                if hint and hint.score >= .45:
                    candidates.append((hint.score, hint, self.by_key[row["page"]]))
        for _, hint, page in sorted(candidates, key=lambda item: -item[0]):
            if all(field.id in self.hits for field in self.text_fields) or len(tried)>=3:
                break
            left,top,right,bottom=hint.box
            height=bottom-top
            box=clipped((left-2*height,top-.36*height,right+2*height,bottom+.36*height),page.size)
            if any(key==page.key and overlap(box,old)>.6*min(area(box),area(old)) for key,old in tried):
                continue
            tried.append((page.key,box))
            source_words=[]
            for row in self.observations:
                if row["page"]==page.key and row["stage"] in {"receipt-survey","receipt-context","body-survey"}:
                    for line in row["lines"]:
                        if overlap(line["box"],hint.box)>.70*area(hint.box):
                            words=[word["box"] for word in line.get("raw_words",[]) if overlap(word["box"],hint.box)]
                            if len(words)>len(source_words):
                                source_words=words
            slopes=[(b[1]+b[3]-a[1]-a[3])/(b[0]+b[2]-a[0]-a[2])
                    for a in source_words for b in source_words if b[0]-a[2]>3*height]
            slope=float(np.clip(np.median(slopes),-.17,.17)) if slopes else 0.
            char_height=float(np.median([b[3]-b[1] for b in source_words])) if source_words else height
            self.buy(page,box,min(48_000,self.ledger.remaining//3),"body-line",f"phrase clue: {hint.text}",
                     line=True,thin=True,angle=round(degrees(atan(slope)),2),char_height=char_height)

    def finish(self):
        self.find_stamp()
        tried = []
        self.text_lines(tried)
        ordered = sorted(self.pages, key=lambda p:p.key != self.hits.get(self.field.id,{}).get("page"))
        for index,page in enumerate(ordered):
            if all(field.id in self.hits for field in self.text_fields):
                break
            width,height=page.size
            region=clipped((.035*width,.06*height,.965*width,.95*height),page.size)
            quota=min(425_000,int(.66*self.ledger.remaining/(len(ordered)-index)))
            self.buy(page,region,quota,"body-survey","search for the requested text")
            self.text_lines(tried)
        steps,spent = list(self.ledger.steps),self.ledger.spent
        pending = tuple(field for field in self.text_fields if field.id not in self.hits)
        if pending and self.ledger.remaining >= 100_000:
            partial=run(replace(self.task,fields=pending), self.pages,self.ledger.remaining,
                        lambda p,s:p.observe(s,self.engine),"scan-audit")
            self.hits.update((hit["field"],hit) for hit in partial["evidence"])
            steps.extend(dict(step,step=step["step"]+len(self.ledger.steps),spent=step["spent"]+spent,
                              stage="global",scope="body") for step in partial["steps"])
            spent+=partial["spent"]
        evidence=[self.hits[field.id] for field in self.task.fields if field.id in self.hits]
        result=answer(self.task,evidence)
        return dict(strategy="receipt-year",budget=self.budget,preview_pixels=self.preview_pixels,spent=spent,
                    total_pixels=spent+self.preview_pixels,ocr_calls=len(steps),steps=steps,
                    preview_observations=self.previews,evidence=evidence,answer=result,
                    status="answered" if result else ("partial" if evidence else "unresolved"),stamp_readings=self.proofs)


def run_receipt(task,pages,budget,engine):
    return ReceiptSearch(task,pages,budget,engine).finish()
