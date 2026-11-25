"""Rebuild the public evaluation fixtures from local PDFs and pinned annotations."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import sys

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from search_agent.corpus import absent, case_for, synthetic
from search_agent.documents import ROOT, pdf_pages
from search_agent.task import numeric, scalar


GROUPS = {
    "nasa": (1, 2),
    "doe": (3, 12, 20, 24, 34, 37, 40, 47),
    "usgs": (1, 2, 3, 4),
    "census": (1, 2, 3, 5, 8),
}
SOURCES = {
    "nasa": ("NASA", "Hubble Space Telescope – An Overview",
             "https://assets.science.nasa.gov/content/dam/science/missions/hubble/multimedia/fact-sheets/hubble-fact-sheet-overview.pdf",
             "973075554b007dacb082a24f8aee191f737e967d73376ece75bc303fa4f1e404"),
    "doe": ("U.S. Department of Energy", "Energy Saver",
            "https://www.energy.gov/sites/default/files/2022-08/energy-saver-guide-2022.pdf",
            "416398e39c65d91687a287c6f82a8f63723a5f4e5027702f5d144ccbf1d1f504"),
    "usgs": ("U.S. Geological Survey", "Topographic Map Symbols",
             "https://pubs.usgs.gov/gip/TopographicMapSymbols/topomapsymbols.pdf",
             "edb97e137a1831e75f6fddb4971e5e46b9a68cd8ca17ef2c44480b453f49aa59"),
    "census": ("U.S. Census Bureau", "2020 Census sample questionnaire",
               "https://www2.census.gov/programs-surveys/decennial/2020/technical-documentation/questionnaires-and-instructions/questionnaires/2020-informational-questionnaire-english_DI-Q1.pdf",
               "b41386b605047638c3fc0804650ea36b8181f08a7ac935797f68169251dfb9ad"),
    "noaab": ("NOAA National Weather Service", "Sky Watcher Chart",
              "https://www.weather.gov/media/bmx/skywarn/cloudchart.pdf",
              "e86da493c307764702b7fce464501e5dab287414b837ae5136a52c0344b8af3d"),
}

# Pattern groups mark the anchor and numeral on the original publication.
# Direction, search window and ordinal become part of the user-visible task.
MARKS = {
    "nasa": {
        "resolution": (1, "from a distance of", r"(from a distance of) (86)", "after", 2, 1),
        "pointing": (2, "dime", r"(dime) (200)", "after", 2, 1),
        "orbit": (1, "orbits per day", r"(15) (orbits per day)", "before", 2, 1),
        "period": (1, "one every", r"(one every) (95)", "after", 2, 1),
        "mirror": (1, "diameter of a mere", r"(diameter of a mere) (0\.05)", "after", 2, 1),
        "length": (2, "Hubble is", r"(Hubble is) (43\.5)", "after", 2, 1),
        "width": (2, "Hubble is", r"(Hubble is) 43\.5 feet long and (14)", "after", 6, 2),
        "jitter": (2, "milliarcseconds", r"(7) (milliarcseconds)", "before", 2, 1),
        "shuttle": (1, "Space Shuttle"),
        "wheels": (2, "reaction wheels used"),
    },
    "doe": {
        "save": (3, "Save Money and Energy Today", r"(1) (Save Money and Energy Today)", "before", 2, 1),
        "weatherize": (3, "Weatherize Your Home", r"(6) (Weatherize Your Home)", "before", 2, 1),
        "refs": (3, "References and Resources"),
        "zones": (12, "Alaska climate zones"),
        "kenai": (12, "Kenai Peninsula", r"(7) - (Kenai Peninsula)", "before", 3, 1),
        "ketchikan": (12, "Ketchikan Gateway", r"(5) - (Ketchikan Gateway)", "before", 3, 1),
        "heat": (20, "compared to electric", r"(50%) (compared to electric)", "before", 2, 1),
        "limit": (24, "gallons or less", r"(41) (gallons or less)", "before", 2, 1),
        "credit": (24, "eligible for a", r"(eligible for a) (26%)", "after", 2, 1),
        "heater": (34, "water heater to", r"(water heater to) (120°F)", "after", 2, 1),
        "booster": (34, "boost water temperature to", r"(boost water temperature to) (140°F)", "after", 2, 1),
        "volume": (34, "gallons per year", r"(8,000) (gallons per year)", "before", 2, 1),
        "washer": (37, "more than conventional", r"(60%) (more than conventional)", "before", 2, 1),
        "watts": (40, "Energy Used", r"(Energy Used) (9)", "after", 2, 1),
        "lumens": (40, "Brightness", r"(Brightness) (450)", "after", 2, 1),
        "bill": (40, "Estimated Yearly Energy Cost", r"(Estimated Yearly Energy Cost) (\$1\.08)", "after", 2, 1),
        "plugin": (47, "plug-in hybrid electric"),
    },
    "usgs": {
        "reading": (1, "reading topographic maps"),
        "contour": (1, "contour interval of", r"(contour interval of) (10)", "after", 2, 1),
        "mountains": (1, "contour intervals of", r"(contour intervals of) (100)", "after", 2, 1),
        "control": (2, "control data and monuments"),
        "wreck": (2, "exposed wreck"),
        "spot": (3, "Spot elevation", r"(Spot elevation) (7523)", "after", 2, 1),
        "glacier": (3, "glaciers and permanent snowfields"),
        "roads": (4, "roads and related features"),
        "aqueduct": (4, "aqueduct tunnel"),
    },
    "census": {
        "official": (1, "official questionnaire for"),
        "privacy": (1, "protected by law"),
        "months": (2, "months Write", r"(months\. Write) (0)", "after", 2, 1),
        "adult": (2, "any adult living here"),
        "person2": (3, "Print name of Person 2"),
        "person4": (5, "Print name of Person 4"),
        "minutes": (8, "will take", r"(will take) (10)", "after", 2, 1),
        "estimate": (8, "burden estimate"),
    },
    "noaab": {
        "title": (1, "Sky Watcher Chart"),
        "high": (1, "High Clouds"),
        "middle": (1, "Middle Clouds"),
        "low": (1, "Low Clouds"),
    },
}
CASES = {
    "nasa": [
        ("distance", "difference", ("resolution", "pointing"), "分辨率说明和指向稳定性类比中的两处距离，计算 A−B", "mi"),
        ("distance-order", "compare", ("pointing", "resolution"), "比较两处类比的距离数值", "mi"),
        ("mechanisms", "verify", ("shuttle", "wheels"), "定位航天飞机和反作用轮的两处记载", ""),
        ("orbit", "extract", ("orbit",), "提取每天环绕地球的圈数", "orbits/day"),
        ("period", "extract", ("period",), "提取绕行周期", "min"),
        ("detail", "extract", ("mirror",), "提取角尺度", "arcsec"),
        ("length", "extract", ("length",), "提取望远镜长度", "ft"),
        ("width", "extract", ("width",), "从同一锚点读取第二个数字", "ft"),
        ("angular", "extract", ("jitter",), "提取指向抖动说明中的角尺度", "mas"),
        ("unconfirmed", "verify", ("shuttle", "?frequency calibration appendix"), "一处有证据，另一处缺失", ""),
    ],
    "doe": [
        ("electric", "difference", ("heat", "washer"), "比较两个章节中分别报道的百分数，计算 A−B", "pp"),
        ("percentage", "compare", ("credit", "washer"), "比较两个章节中出现的百分数", "%"),
        ("temperature", "difference", ("booster", "heater"), "计算两种热水设定说明里的温差", "°F"),
        ("power", "extract", ("watts",), "提取示例灯泡的功率", "W"),
        ("cost", "extract", ("bill",), "提取示例标签的年度能源成本", "USD"),
        ("lumens", "extract", ("lumens",), "读取标签中的亮度而非正文中的同名词", "lm"),
        ("contents", "compare", ("save", "weatherize"), "比较目录印刷页码", "page"),
        ("zone", "compare", ("kenai", "ketchikan"), "比较阿拉斯加两地的气候分区编号", "zone"),
        ("volume", "extract", ("volume",), "提取年用水量说明中的数值", "gal"),
        ("limited", "extract", ("limit",), "提取热水使用量阈值", "gal"),
        ("chapters", "verify", ("refs", "plugin"), "核对参考资料与插电混动车说明均有证据", ""),
        ("tables", "verify", ("zones", "bill"), "定位分区和标签两种不同版面", ""),
        ("none", "locate", ("?water consumption telemetry appendix",), "未收录的标题", ""),
    ],
    "usgs": [
        ("elevation", "compare", ("spot", "contour"), "比较符号图例与说明页中的两个英尺数值", "ft"),
        ("interval", "difference", ("mountains", "contour"), "计算两类地形的示例等高距差", "ft"),
        ("terrain", "verify", ("reading", "glacier"), "核对地图阅读标题与冰川图例", ""),
        ("symbols", "verify", ("control", "roads"), "定位控制点和道路章节", ""),
        ("water", "verify", ("wreck", "aqueduct"), "定位两页不同的水域图例", ""),
        ("none", "locate", ("?live satellite raster index",), "未收录的图例", ""),
    ],
    "census": [
        ("instructions", "verify", ("official", "adult"), "核对封面和第一个人的填写说明", ""),
        ("people", "verify", ("person2", "person4"), "区分版式相同但编号不同的两页", ""),
        ("privacy", "verify", ("privacy", "estimate"), "定位隐私与填写负担说明", ""),
        ("minutes", "extract", ("minutes",), "提取预计填写分钟数", "min"),
        ("age", "extract", ("months",), "提取小于一岁的填报年龄", "year"),
        ("none", "verify", ("official", "?optional attachment schedule"), "封面存在，另一条说明缺失", ""),
    ],
    "mixed": [
        ("cross-source", "verify", ("nasa.shuttle", "noaab.title"), "同时定位航天说明和气象图表，证据来自两份来源", ""),
        ("charts", "verify", ("noaab.high", "usgs.glacier"), "核对气象和地形图表中的标题", ""),
        ("separate", "verify", ("noaab.middle", "census.official"), "核对同批次中不同来源的两处证据", ""),
        ("missing", "locate", ("?historical sensor outage log",), "文档集合中不存在的记录", ""),
    ],
}


def one_match(page, pattern, group=0):
    matches = page.search(pattern, case=False, main_group=group, return_chars=False, return_groups=False)
    if len(matches) != 1:
        raise ValueError(f"标注不唯一：页 {page.page_number}，正则 {pattern}，命中 {len(matches)}")
    return matches[0]


def pixel_box(match, crop, size):
    x, y, x1, y1 = crop
    return [round((match["x0"] - x) * size[0] / (x1 - x), 2),
            round((match["top"] - y) * size[1] / (y1 - y), 2),
            round((match["x1"] - x) * size[0] / (x1 - x), 2),
            round((match["bottom"] - y) * size[1] / (y1 - y), 2)]


def build_mark(source, doc, images, rule):
    number, anchor, *detail = rule
    original = doc.pages[number - 1]
    crop = original.cropbox
    page = original.crop(crop)
    row = {"page": f"{source}-p{number:02d}", "anchor": anchor, "direction": "after"}
    pattern = r"\b" + re.escape(anchor) + r"\b"
    if detail:
        pattern, direction, window, ordinal = detail
        number_group = 2 if direction == "after" else 1
        value = one_match(page, pattern, number_group)
        row.update(value=scalar(numeric(value["text"])), value_box=pixel_box(value, crop, images[number].size),
                   direction=direction, window=window, ordinal=ordinal)
        group = 3 - number_group
    else:
        group = 0
    row["anchor_box"] = pixel_box(one_match(page, pattern, group), crop, images[number].size)
    return row


def case_row(case):
    return {"id": case.key, "label": case.label, "task": case.raw, "gold": case.gold}


def image_row(page, file, directory, name):
    path = directory / file
    page.image.save(path, "JPEG", quality=91, optimize=True)
    return {"id": page.key, "file": file, "name": name, "size": list(page.size),
            "sha256": sha256(path.read_bytes()).hexdigest()}


def dump(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build(sources):
    directory = ROOT / "data/external"
    group_ids = {**GROUPS, "noaab": (1,)}
    marks, pages, sources_meta = {}, {}, {}
    for source, nums in group_ids.items():
        publisher, title, url, digest = SOURCES[source]
        path = sources / f"{source}.pdf"
        data = path.read_bytes()
        if sha256(data).hexdigest() != digest:
            raise ValueError(f"源文件校验失败：{path.name}")
        filename = f"pdf/{path.name}"
        (directory / "pdf").mkdir(exist_ok=True)
        shutil.copyfile(path, directory / filename)
        sources_meta[source] = {"publisher": publisher, "title": title, "url": url, "sha256": digest,
                                "pages": list(nums), "bytes": len(data), "file": filename}
        images = dict(zip(nums, pdf_pages(data, nums, f"{source}-")))
        with pdfplumber.open(path) as doc:
            for key, rule in MARKS[source].items():
                marks[f"{source}.{key}"] = build_mark(source, doc, images, rule)
        for n in nums:
            image = images[n]
            pages[image.key] = {**image_row(image, f"{image.key}.jpg", directory, f"{publisher} · 第 {n} 页"),
                                "source": source, "pdf_page": n}
    packs = []
    for name, tasks in CASES.items():
        ids = ([f"{name}-p{n:02d}" for n in GROUPS[name]] if name in GROUPS
               else ["census-p03", "noaab-p01", "nasa-p02", "usgs-p03", "census-p01", "nasa-p01"])
        cases = []
        for key, op, inputs, label, unit in tasks:
            items = [absent(item[1:]) if item.startswith("?")
                     else marks[item if "." in item else f"{name}.{item}"] for item in inputs]
            if any(item["page"] not in [*ids, None] for item in items):
                raise ValueError(f"页未加入样例包：{name} {key}")
            cases.append(case_row(case_for(f"{name}-{key}", op, items, label, unit)))
        packs.append({"id": name, "pages": [pages[key] for key in ids], "cases": cases})
    dump(directory / "manifest.json", {"sources": sources_meta, "packs": packs})
    dump(directory / "annotations.json", marks)


def build_synthetic():
    directory = ROOT / "data/examples"
    # Keep the demonstration pack separate from every scored split.
    pack = next(synthetic("demo"))
    page_rows = [image_row(page, f"sample-{n:02d}.jpg", directory, f"合成巡检记录 · 第 {n} 页")
                 for n, page in enumerate(pack.pages, start=1)]
    dump(directory / "manifest.json", {"packs": [
        {"id": pack.key, "pages": page_rows, "cases": [case_row(case) for case in pack.cases]}
    ]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True, help="local original PDFs with the verified source hashes")
    options = parser.parse_args()
    build(options.source_dir)
    build_synthetic()
