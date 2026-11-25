"""Extract the full native page-25 scan of the Tweed letter."""
import argparse
from pathlib import Path
import pypdfium2 as pdf
from pypdfium2 import raw


def extract(source, destination):
    with pdf.PdfDocument(source) as document:
        page = document[24]
        scan, = page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE])
        width,height = page.get_size()
        assert page.get_rotation() == 0 and scan.get_px_size() == (2550,3300)
        assert max(abs(a-b) for a,b in zip(scan.get_bounds(),(0,0,width,height))) < .01
        mat = scan.get_matrix()
        assert mat.a > 0 and mat.d > 0 and mat.b == mat.c == 0
        bitmap = scan.get_bitmap(render=False)
        try:
            with destination.open("xb") as handle:
                bitmap.to_pil().convert("RGB").save(handle,format="PNG")
        finally:
            bitmap.close()
            page.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    parser.add_argument("destination",type=Path)
    args=parser.parse_args()
    extract(args.source,args.destination)
