"""Build reference rasters, portable batch manifest, and manual annotation tiles."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path

import pypdfium2 as pdf
from pypdfium2 import raw
from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
BATCH = Path(os.environ.get("VISUAL_SEARCH_BATCH_DIR", HERE.parents[1] / "batch")).resolve()
OLD_DISTRACTOR = BATCH/"examples/data/griffith.png"


def raster(path,number):
    with pdf.PdfDocument(path) as document:
        page = document[number-1]
        width,height = page.get_size()
        scans = list(page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE]))
        if len(scans)==1 and page.get_rotation()==0:
            meta = scans[0]
            x0,y0,x1,y1 = meta.get_bounds()
            matrix = meta.get_matrix()
            w,h = meta.get_px_size()
            if (matrix.a>0 and matrix.d>0 and matrix.b==matrix.c==0
                    and 16<=min(w,h) and max(w,h)<=6500 and w*h<=12_000_000
                    and abs(x0)<.025*width and abs(y0)<.025*height
                    and abs(x1-width)<.025*width and abs(y1-height)<.025*height):
                bmp = meta.get_bitmap(render=False)
                try:
                    return bmp.to_pil().convert("RGB"),"native_scan"
                finally:
                    bmp.close()
        native_scale = max((max(scan.get_px_size())/max(width,height) for scan in scans),default=2)
        bmp = page.render(scale=min(native_scale,3000/max(width,height)),may_draw_forms=False)
        try:
            return bmp.to_pil().convert("RGB"),"rendered_page"
        finally:
            bmp.close()


def sheets(out):
    for path in sorted((HERE/"data").glob("*.pdf")):
        with pdf.PdfDocument(path) as book:
            print(path.name,len(book))
            for start in range(0,len(book),30):
                canvas = Image.new("RGB",(1100,1260),"#cbd3d8")
                ink = ImageDraw.Draw(canvas)
                for n in range(start,min(start+30,len(book))):
                    page = book[n]
                    s = min(171/page.get_width(),220/page.get_height())
                    bmp = page.render(scale=s)
                    x,y = (n-start)%6*183,(n-start)//6*251
                    canvas.paste(bmp.to_pil().convert("RGB"),(x,y+21))
                    ink.text((x+4,y+4),str(n+1),fill="black")
                    bmp.close()
                    page.close()
                canvas.save(out/f"{path.stem}-{start+1}.jpg",quality=86)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def save_png(image,path):
    with path.open("xb") as handle:
        image.save(handle,format="PNG")


def annotate(manifest,path):
    cases = manifest["cases"]
    board = Image.new("RGB",(1130,92+len(cases)*166),"white")
    pen = ImageDraw.Draw(board)
    font = ImageFont.load_default(size=22)
    pen.text((25,16),"Human references registered before OCR",font=font,fill="#203040")
    pen.text((25,50),"Blue: stamp date  /  Red: year  /  Green: anchor phrase",fill="#32495a")
    for index,case in enumerate(cases):
        src = manifest["sources"][case["page"]]
        y = 86+166*index
        pen.text((25,y),f'{case["id"]}  {src["volume"]} p.{src["pdf_page"]}  /  {case["date"]}',font=font,fill="#203040")
        stamp, = case["stamps"]
        groups = ((stamp["date_box"],[(stamp["date_box"],"#106bbc"),(stamp["year_box"],"#c92236")]),
                  (case["text_box"],[(case["text_box"],"#167e45")]))
        with Image.open(HERE/src["path"]) as source:
            for left,(focus,boxes) in zip((25,490),groups,strict=True):
                x0,y0 = max(0,focus[0]-12),max(0,focus[1]-12)
                crop = source.crop((x0,y0,min(focus[2]+12,source.width),min(focus[3]+12,source.height))).convert("RGB")
                draw = ImageDraw.Draw(crop)
                for (a,b,c,d),colour in boxes:
                    draw.rectangle((a-x0,b-y0,c-x0,d-y0),outline=colour,width=2)
                scale = min(2.5,(425 if left==25 else 610)/crop.width,106/crop.height)
                board.paste(crop.resize((int(crop.width*scale),int(crop.height*scale))),(left,y+37))
    board.save(path)


def compile_manifest(labels,out):
    definitions = json.loads(labels.read_text())
    prior_path = HERE/"data/griffith.png"
    try:
        with prior_path.open("xb") as handle:
            handle.write(OLD_DISTRACTOR.read_bytes())
    except FileExistsError:
        pass
    assert digest(prior_path)==digest(OLD_DISTRACTOR)
    sources = {"griffith":{"path":"data/griffith.png","size":[1234,786],"sha256":digest(prior_path),
                           "role":"previously seen fixed distractor"}}
    cases,jobs = [],[]
    for row in definitions:
        tag = row["id"].lower()
        src = HERE/"data"/(row["volume"]+".pdf")
        png = HERE/"data"/(tag+".png")
        image,method = raster(src,row["pdf_page"])
        if not png.exists():
            save_png(image,png)
        else:
            with Image.open(png) as previous:
                assert previous.size==image.size and previous.tobytes()==image.tobytes()
        masks = [row["text_box"],row["date_box"],row["year_box"]]
        assert all(0<=l<r<=image.width and 0<=t<b<=image.height for l,t,r,b in masks),row["id"]
        source = {**{k:row[k] for k in ("volume","pdf_page","name","source")},"path":f"data/{tag}.png",
                  "size":list(image.size),"pdf_sha256":digest(src),"sha256":digest(png),"raster":method}
        sources[tag] = source
        sets = {"single":[tag],"distractor":["griffith",tag]}
        cases.append({"id":row["id"],"page":tag,"date":row["date"],"text":row["text"],"text_box":row["text_box"],
                      "stamps":[{k:row[k] for k in ("date_box","year_box")}],"sets":sets})
        for label,keys in sets.items():
            for slug,policy in (("old","spare-stamp"),("new","month-routed-stamp")):
                jobs.append({"id":f'{row["id"]}-{label}-{slug}',"kind":"stamp","date":row["date"],"text":row["text"],
                             "files":[sources[key]["path"] for key in keys],"policy":policy,"pixel_budget":1_000_000})
    out.mkdir(exist_ok=True)
    holdout = {"budget":1_000_000,"sources":sources,"cases":cases}
    for name,value in (("holdout.json",holdout),("jobs.json",{"version":1,"jobs":jobs})):
        with (out/name).open("x") as handle:
            json.dump(value,handle,indent=2,ensure_ascii=False)
            handle.write("\n")
    annotate(holdout,out/"labels.png")


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command",required=True)
    sub.add_parser("sheets").add_argument("out",type=Path)
    view = sub.add_parser("view")
    view.add_argument("volume")
    view.add_argument("page",type=int)
    view.add_argument("out",type=Path)
    build = sub.add_parser("compile")
    build.add_argument("labels",type=Path)
    build.add_argument("out",type=Path)
    args = parser.parse_args()
    if args.command=="sheets":
        sheets(args.out)
    elif args.command=="view":
        image,method = raster(HERE/"data"/(args.volume+".pdf"),args.page)
        print(image.size,method)
        image.save(args.out)
    else:
        compile_manifest(args.labels,args.out)
