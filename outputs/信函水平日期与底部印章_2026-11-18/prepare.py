"""Recover the single full-page scan at native resolution from each public PDF."""
from pathlib import Path
import sys

import pypdfium2 as pdf
import pypdfium2.raw as raw


def extract(directory, key):
    document = pdf.PdfDocument(directory / f"{key}-original.pdf")
    try:
        page = document[0]
        image, = page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE])
        width, height = page.get_size()
        assert page.get_rotation() == 0
        assert all(abs(a - b) < .01 for a, b in zip(image.get_bounds(), (0, 0, width, height)))
        original_size = image.get_px_size()
        matrix = image.get_matrix()
        assert matrix.a > 0 and matrix.d > 0 and matrix.b == matrix.c == 0
        bitmap = image.get_bitmap(render=False)
        try:
            raster = bitmap.to_pil().convert("RGB")
            assert raster.size == original_size
            raster.save(directory / f"{key}.png")
            print(key, original_size, len(document), "pages in original, first page selected")
        finally:
            bitmap.close()
    finally:
        document.close()


if __name__ == "__main__":
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "data"
    for document_key in ("nixon", "diggs"):
        extract(directory, document_key)
