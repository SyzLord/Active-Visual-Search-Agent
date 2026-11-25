"""Remove the two known Diggs stamp years but leave the letter and its issue date intact."""
from copy import deepcopy
import json
from pathlib import Path

from PIL import Image, ImageDraw


def make(directory):
    development=json.loads((directory/"development.json").read_text())
    case=deepcopy(development["cases"][0])
    source=development["sources"]["diggs"]
    with Image.open(directory/source["path"]) as scan:
        image=scan.convert("RGB")
    draw=ImageDraw.Draw(image)
    erased=[]
    for stamp in case["stamps"]:
        left,top,right,bottom=stamp["year_box"]
        box=(left-3,top-3,right+3,bottom+3)
        draw.rectangle(box,fill="white")
        erased.append(box)
    (directory/"control").mkdir(exist_ok=True)
    image.save(directory/"control/diggs-masked.png")
    case.update(id="D3-masked",page="diggs-masked",sets={"single":["diggs-masked"]})
    case.pop("baseline_cache")
    protocol=dict(split="negative",budget=1_000_000,
                  sources={"diggs-masked":dict(source,path="control/diggs-masked.png")},
                  cases=[case],erased_boxes=erased,expected="no year proof at either erased impression")
    (directory/"negative.json").write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+"\n")


if __name__=="__main__":
    make(Path(__file__).resolve().parent)
