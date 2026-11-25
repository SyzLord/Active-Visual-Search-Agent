"""Generate visually varied multi-page packs and load immutable benchmark fixtures."""

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageFont

from .core import union_box
from .documents import ROOT, PageImage, open_image, pdf_pages
from .task import parse_task

COUNTS = {"train": 16, "dev": 6, "test": 10, "demo": 1}
PAGE_SIZE = (1520, 2060)
LAYOUTS = {"train": (0, 1, 2), "dev": (0, 1, 2), "test": (0, 1, 3), "demo": (0, 1, 2)}
SEEDS = {"train": 12000, "dev": 28000, "test": 47000, "demo": 98000}
NAMES = (
    ("Cedar", "Birch", "Aspen", "Spruce", "Willow", "Maple", "Cypress", "Alder", "Hazel", "Pine"),
    ("Granite", "Opal", "Slate", "Onyx", "Flint", "Quartz", "Jasper", "Marble", "Amber", "Basalt"),
)
EXTERNAL = ROOT / "data/external/manifest.json"
EXAMPLES = ROOT / "data/examples.json"
METRICS = ("relay output", "return flow", "inlet rate", "cooling loop", "standby draw", "reserve power",
           "panel supply", "intake demand", "circulation load", "auxiliary feed", "bypass level", "buffer capacity")
FILLER = (
    "Inspect the enclosure for dust before the next scheduled service.",
    "The reference values were recorded under the same load setting.",
    "Changes to the assembly must be recorded in the site log.",
    "Retain the original worksheet for the weekly equipment review.",
    "Record the observed level during the standard check sequence.",
    "The operating team shall review any unexplained variation.",
    "The maintenance file includes a separate record for each shift.",
    "Measurements are valid for the instrument and setup identified above.",
    "Follow the standard review process before restarting the equipment.",
    "The values in this register reflect the current site configuration.",
)
LAYOUT_TITLES = ("Equipment register", "Station review", "Shift records", "Field measurements")
PALETTES = (("#f8fbfa", "#13352f", "#e6f0eb"), ("#fffdf8", "#312937", "#efe9ed"),
            ("#f7f9fd", "#1b334c", "#e8edf6"), ("#faf9f2", "#393c2b", "#efedda"))


@dataclass(frozen=True)
class Case:
    key: str
    raw: dict
    gold: dict
    label: str = ""

    @property
    def task(self):
        return parse_task(self.raw)


@dataclass
class Pack:
    key: str
    pages: list
    cases: list


@lru_cache(maxsize=100)
def font(size, style="Regular"):
    return ImageFont.truetype(str(ROOT / "data/fonts" / f"LiberationSans-{style}.ttf"), size)


def case_for(key, op, items, label="", unit=""):
    count = 1 if op in ("locate", "extract") else 2
    if len(items) != count:
        raise ValueError("Incorrect number of fields in benchmark case")
    fields, gold = [], {}
    for name, item in zip(("A", "B"), items):
        field = {"anchor": item["anchor"]}
        evidence = {"page": item["page"], "anchor_box": item["anchor_box"], "value": None, "value_box": None}
        if op in ("extract", "compare", "difference"):
            field.update(direction=item.get("direction", "after"), window=item.get("window", 5),
                         ordinal=item.get("ordinal", 1))
            evidence.update(value=item["value"], value_box=item["value_box"])
        fields.append(field)
        gold[name] = evidence if item["page"] is not None else None
    return Case(key, {"op": op, "fields": fields, "unit": unit}, gold, label)


def absent(anchor, direction="after"):
    return {"anchor": anchor, "direction": direction, "page": None, "value": None,
            "anchor_box": None, "value_box": None}


def write_row(draw, x, y, width, size, item, rng, ink, tint, shaded):
    body = font(size, rng.choice(("Regular", "Regular", "Bold", "Italic")))
    direction, label, number = item["direction"], item["anchor"], item["printed"]
    prefix, suffix = ("", "  kW") if direction == "after" else ("", "")
    left, right = (label, number) if direction == "after" else (number, label)
    separator = rng.choice((" : ", "   ", "  /  "))
    line = prefix + left + separator + right + suffix
    if shaded:
        draw.rounded_rectangle((x - 14, y - 4, x + width, y + size + 12), radius=5, fill=tint)
    draw.text((x, y), line, font=body, fill=ink)
    end_left = x + draw.textlength(prefix + left, font=body)
    start_right = x + draw.textlength(prefix + left + separator, font=body)
    end_right = x + draw.textlength(prefix + left + separator + right, font=body)
    # Horizontal bounds use advances, and vertical bounds use the exact glyphs.
    left_bbox = draw.textbbox((x, y), left, font=body)
    right_bbox = draw.textbbox((start_right, y), right, font=body)
    boxes = ([round(x), left_bbox[1], round(end_left), left_bbox[3]],
             [round(start_right), right_bbox[1], round(end_right), right_bbox[3]])
    item["anchor_box"], item["value_box"] = boxes if direction == "after" else boxes[::-1]


def render_page(rng, key, index, layout, rows, pack_number):
    width, height = PAGE_SIZE
    paper, ink, tint = PALETTES[layout]
    image = Image.new("RGB", PAGE_SIZE, paper)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 183), fill=ink)
    draw.text((88, 32), f"FACILITY OPERATIONS  /  {pack_number:02d}", font=font(30, "Bold"), fill="white")
    draw.text((86, 83), LAYOUT_TITLES[layout], font=font(65, "Bold"), fill="white")
    draw.text((94, 219), f"Inspection cycle  {rng.randint(10, 96)}   /   Group {index + 1}", font=font(34), fill=ink)
    draw.line((91, 290, 1424, 290), fill=ink, width=3)
    columns = 2 if layout in (1, 3) else 1
    col_width = 640 if columns == 2 else 1270
    col_items = len(rows) // columns
    for col in range(columns):
        x = 98 + col * 693
        draw.text((x, 332), ("Review notes" if col else "Observation log"), font=font(40, "Bold"), fill=ink)
        if layout == 3:
            draw.rectangle((x - 21, 413, x + col_width + 8, 1710), outline=ink, width=3)
        for j, item in enumerate(rows[col * col_items:(col + 1) * col_items]):
            y = 466 + j * (255 if columns == 2 else 156) + rng.randrange(-25, 40)
            size = rng.choice((31, 36, 42, 46, 54)) if layout != 3 else rng.choice((31, 35, 40, 44))
            if columns == 2:
                size = min(size, 39)
            write_row(draw, x, y, col_width, size, item, rng, ink, tint, (layout + j) % 2 == 0)
            words = rng.choice(FILLER).split()
            if columns == 2:
                halfway = len(words) // 2
                draw.text((x, y + size + 25), " ".join(words[:halfway]), font=font(26), fill=ink)
                draw.text((x, y + size + 63), " ".join(words[halfway:]), font=font(26), fill=ink)
            elif j % 2 or layout == 2:
                draw.text((x, y + size + 25), " ".join(words), font=font(29), fill=ink)
    for j in range(3):
        draw.text((95, 1750 + 50 * j), rng.choice(FILLER), font=font(28), fill=ink)
    draw.line((93, 1930, 1422, 1930), fill=ink, width=3)
    draw.text((95, 1960), f"Internal technical record  /  sheet {index + 1:02d}", font=font(26), fill=ink)
    digest = sha256(image.tobytes()).hexdigest()
    return PageImage(key, image, f"合成巡检记录 · 第 {index + 1} 页", digest)


def synthetic(split, limit=None):
    for pack_index in range(min(COUNTS[split], limit) if limit is not None else COUNTS[split]):
        rng = random.Random(SEEDS[split] + pack_index)
        key = f"{split}-{pack_index + 1:02d}"
        pages, all_rows = [], []
        vocabulary = NAMES[int(split == "test")]
        names = [f"{name} {metric}" for name in vocabulary for metric in METRICS]
        rng.shuffle(names)
        page_count = 5 if split == "train" else 6
        for i in range(page_count):
            page = f"{key}-p{i + 1:02d}"
            rows = []
            for j in range(8):
                value = rng.randrange(80, 7800)
                printed = f"{value / 100:.2f}" if j % 3 == 1 else f"{value:,}"
                if rng.random() < .11:
                    printed = "-" + printed
                number = printed.replace(",", "").rstrip("0").rstrip(".") if "." in printed else printed.replace(",", "")
                rows.append({"anchor": names[i * 8 + j], "page": page, "printed": printed, "value": number,
                             "direction": rng.choice(("before", "after")), "window": 4})
            layout = rng.choice(LAYOUTS[split])
            pages.append(render_page(rng, page, i, layout, rows, pack_index))
            all_rows.append(rows)
        cases = []
        for j, op in enumerate(("difference", "compare", "verify", "extract", "locate", "verify", "difference", "compare")):
            a, b = rng.sample(range(page_count), 2)
            items = [rng.choice(all_rows[a])]
            if op in ("verify", "difference", "compare"):
                items.append(absent("Mercury bypass reserve") if j == 5 else rng.choice(all_rows[b]))
            cases.append(case_for(f"{key}-{j + 1:02d}", op, items, "合成巡检记录",
                                  unit="kW" if op in ("difference", "compare", "extract") else ""))
        cases.append(case_for(f"{key}-09", "locate", [absent("Mercury bypass reserve")], "无匹配证据"))
        yield Pack(key, pages, cases)


def read_manifest(path):
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_packs(path, key=None, from_pdf=False, fields=(), index_case=None):
    raw = read_manifest(path)
    for group in raw["packs"]:
        if key is not None and group["id"] != key:
            continue
        cases = [Case(row["id"], row["task"], row["gold"], row["label"]) for row in group["cases"]]
        if from_pdf:
            if index_case is not None:
                fields = next(case.task.fields for case in cases if case.key == index_case)
            pages = indexed_pages(raw["sources"], group["pages"], path.parent, fields)
            yield Pack(group["id"], pages, cases)
            continue
        pages = []
        for row in group["pages"]:
            page = open_image(row["id"], path.parent / row["file"], row["name"])
            if page.digest != row["sha256"]:
                raise ValueError(f"输入样例校验失败：{row['file']}")
            pages.append(page)
        yield Pack(group["id"], pages, cases)


def indexed_pages(sources, rows, directory, fields):
    by_source = {}
    for row in rows:
        by_source.setdefault(row["source"], []).append(row["pdf_page"])
    pages = {}
    for name, nums in by_source.items():
        source = sources[name]
        data = (directory / source["file"]).read_bytes()
        if sha256(data).hexdigest() != source["sha256"]:
            raise ValueError(f"源文件校验失败：{source['file']}")
        for page in pdf_pages(data, nums, f"{name}-", fields):
            pages[page.key] = page
    for row in rows:
        page = pages[row["id"]]
        if list(page.size) != row["size"]:
            raise ValueError("评测 PDF 的渲染尺寸与标注不一致")
        page.name = row["name"]
    return [pages[row["id"]] for row in rows]


def examples():
    return read_manifest(EXAMPLES)


def example(key, index=False, override=None):
    fixture = next((row for row in examples() if row["id"] == key), None)
    if fixture is None:
        raise ValueError("没有这个样例。请运行 list-examples 查看可用样例")
    manifest = ROOT / "data" / fixture["manifest"]
    from_pdf = fixture.get("input") == "pdf"
    fields = parse_task(override).fields if from_pdf and index and override is not None else ()
    index_case = fixture["case"] if from_pdf and index and override is None else None
    pack = next(manifest_packs(manifest, fixture["pack"], from_pdf, fields, index_case))
    case = next(row for row in pack.cases if row.key == fixture["case"])
    return pack.pages, case.raw if override is None else override
