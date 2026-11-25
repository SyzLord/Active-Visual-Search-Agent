"""Extract the selected original full-page rasters and draw the registered evidence sheet."""
import argparse
import json
from pathlib import Path

import pypdfium2 as pdf
from pypdfium2 import raw
from PIL import Image, ImageDraw, ImageFont


PAGES = {"segal":24,"younger":4}


def extract(source,dest):
    for name,number in PAGES.items():
        with pdf.PdfDocument(source/f"{name}-original.pdf") as document:
            page = document[number-1]
            scan, = page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE])
            matrix = scan.get_matrix()
            if page.get_rotation()!=0 or matrix.a<=0 or matrix.d<=0 or matrix.b!=0 or matrix.c!=0:
                raise ValueError(f"Unexpected scan orientation: {name}")
            bitmap = scan.get_bitmap(render=False)
            try:
                image = bitmap.to_pil().convert("RGB")
                assert image.size==scan.get_px_size()
                with (dest/f"{name}.png").open("xb") as handle:
                    image.save(handle,format="PNG")
                print(name,number,*image.size)
            finally:
                bitmap.close()
                page.close()


def annotation(protocol,output):
    manifest = json.loads(protocol.read_text())
    board = Image.new("RGB",(1100,620),"white")
    label = ImageDraw.Draw(board)
    header = ImageFont.load_default(size=24)
    caption = ImageFont.load_default(size=17)
    label.text((25,12),"Frozen human annotations on the source scans",font=header,fill="#1f3344")
    for i,case in enumerate(manifest["cases"]):
        source = manifest["sources"][case["page"]]
        with Image.open(protocol.parent/source["path"]) as image:
            y = 64+i*265
            label.text((25,y),f'{case["id"]}  /  {case["page"]}, PDF p.{source["pdf_page"]}  /  {case["date"]}',font=caption,fill="#172d3e")
            stamp, = case["stamps"]
            groups = ((stamp["date_box"],[(stamp["date_box"],"#1273bd"),(stamp["year_box"],"#cc293f")]),
                      (case["text_box"],[(case["text_box"],"#167448")]))
            for x,(focus,boxes) in zip((25,545),groups,strict=True):
                a,b,c,d = focus
                x0,y0 = max(0,a-20),max(0,b-20)
                tile = image.crop((x0,y0,min(image.width,c+20),min(image.height,d+20))).convert("RGB")
                draw = ImageDraw.Draw(tile)
                for (left,top,right,bottom),color in boxes:
                    draw.rectangle((left-x0,top-y0,right-x0,bottom-y0),outline=color,width=2)
                scale = min(2.,510/tile.width,185/tile.height)
                board.paste(tile.resize((round(tile.width*scale),round(tile.height*scale))),(x,y+37))
    label.text((25,587),"Blue  date mark    Red  year word    Green  body phrase",font=caption,fill="#42515e")
    board.save(output,format="PNG")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    extract_cmd=sub.add_parser("extract")
    extract_cmd.add_argument("source",type=Path)
    extract_cmd.add_argument("dest",type=Path)
    labels=sub.add_parser("labels")
    labels.add_argument("protocol",type=Path)
    labels.add_argument("output",type=Path)
    args=parser.parse_args()
    if args.command=="extract":
        extract(args.source,args.dest)
    else:
        annotation(args.protocol,args.output)
