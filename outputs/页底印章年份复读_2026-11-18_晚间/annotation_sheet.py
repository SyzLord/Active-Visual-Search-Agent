"""Show source-pixel boxes. The rectified verso tile is for independent human review."""
import argparse
import json
from pathlib import Path

import pypdfium2 as pdf
from PIL import Image, ImageDraw, ImageFont, ImageOps


def marked_crop(source, focus, overlays, margin, scale):
    left, top, right, bottom = focus
    region = (max(0, left-margin), max(0, top-margin), min(source.width, right+margin), min(source.height, bottom+margin))
    crop = source.crop(region).convert("RGB")
    drawing = ImageDraw.Draw(crop)
    for box, color in overlays:
        x0, y0, x1, y1 = box
        drawing.rectangle((x0-region[0]-1, y0-region[1]-1, x1-region[0], y1-region[1]), outline=color, width=1)
    return crop.resize((crop.width*scale, crop.height*scale), Image.Resampling.NEAREST)


def render(protocol_path, output_path):
    protocol = json.loads(protocol_path.read_text())
    canvas = Image.new("RGB", (1100, 870), "white")
    pen = ImageDraw.Draw(canvas)
    title = ImageFont.load_default(size=25)
    label = ImageFont.load_default(size=18)
    pen.text((26, 18), "Held-out scans  |  Human references", fill="#182e3c", font=title)
    pen.text((26, 58), "Blue: full stamped date    Red: year    Green: body phrase", fill="#2f4856", font=label)
    for index, case in enumerate(protocol["cases"]):
        source = protocol["sources"][case["page"]]
        with Image.open(protocol_path.parent / source["path"]) as scan:
            stamp = case["stamps"][0]
            tiles = [
                marked_crop(scan, stamp["date_box"], [(stamp["date_box"], "#0768ce"), (stamp["year_box"], "#cf2d3d")], 12, 3),
                marked_crop(scan, case["text_box"], [(case["text_box"], "#14764a")], 9, 2),
            ]
        y = 105 + index*240
        pen.text((26, y), f'{case["id"]}   {case["page"]}   /   PDF p.{source["pdf_page"]}   /   {case["date"]}', fill="#182e3c", font=label)
        for tile, x, maximum in zip(tiles, (26, 556), ((504,190), (518,190)), strict=True):
            tile.thumbnail(maximum, Image.Resampling.LANCZOS)
            canvas.paste(tile,(x,y+37))

    cowell = protocol["sources"]["cowell"]
    with pdf.PdfDocument(protocol_path.parent / cowell["original"]) as doc:
        page = doc[42]
        bitmap = page.render(scale=2.2)
        try:
            crop = bitmap.to_pil().convert("RGB").crop((30,1370,500,1665))
        finally:
            bitmap.close()
            page.close()
    tile = crop.rotate(211, Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    tile = ImageOps.autocontrast(tile.convert("L").crop((112,161,422,328)), cutoff=.2)
    tile.thumbnail((500,195))
    pen.text((26, 592), "C1  /  PDF p.43, direct ink on reverse, rotated for human reading", fill="#182e3c",font=label)
    canvas.paste(tile,(26,630))
    pen.text((550, 638),"Both algorithms receive the original recto only.",fill="#2f4856",font=label)
    pen.text((550, 671),"The reverse page confirms the stamped date.",fill="#2f4856",font=label)
    canvas.save(output_path, format="PNG")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    render(args.protocol, args.output)
