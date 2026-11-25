"""Recover the single photographed sheet at native resolution from each registered PDF."""
import argparse
from hashlib import sha256
from pathlib import Path

import pypdfium2 as pdf
from pypdfium2 import raw


SCANS = {"griffith": 32, "cowell": 42}


def extract(source_dir, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    for key, number in SCANS.items():
        with pdf.PdfDocument(source_dir / f"{key}-original.pdf") as document:
            page = document[number - 1]
            images = list(page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE]))
            if len(images) != 1 or page.get_rotation() != 0:
                raise ValueError(f"Expected one upright archival scan on page {number} of {key}")
            scan = images[0]
            matrix = scan.get_matrix()
            if matrix.a <= 0 or matrix.d <= 0 or matrix.b != 0 or matrix.c != 0:
                raise ValueError(f"Unexpected scan orientation on {key}")
            bitmap = scan.get_bitmap(render=False)
            try:
                raster = bitmap.to_pil().convert("RGB")
                if raster.size != scan.get_px_size():
                    raise ValueError("Native image dimensions changed")
                destination = output_dir / f"{key}.png"
                with destination.open("xb") as output:
                    raster.save(output, format="PNG")
                print(key, number, *raster.size, sha256(destination.read_bytes()).hexdigest())
            finally:
                bitmap.close()
                page.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    extract(args.source_dir, args.output_dir)
