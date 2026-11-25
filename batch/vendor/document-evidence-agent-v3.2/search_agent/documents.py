"""Image and PDF input. Text-layer coordinates are opt-in for candidate routing."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re

import pypdfium2
from PIL import Image, ImageOps

from .pdf_index import index_page
from .reader import ImageScene

ROOT = Path(__file__).resolve().parents[1]
MAX_PAGES = 24
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL_FILE = 32 * 1024 * 1024
MAX_TOTAL_PIXELS = 116_000_000
RASTER_EDGE = 2520


class PageImage(ImageScene):
    def __init__(self, key, image, name, digest=None, text_hints=None):
        self.key, self.name, self.digest = key, name, digest
        self.image, self.size = image, image.size
        self.text_hints = text_hints or {}
        if min(self.size) < 16 or max(self.size) > 6500 or self.size[0] * self.size[1] > 12_000_000:
            raise ValueError("图像短边需至少 16 像素，长边最多 6500，总像素不超过 1200 万")


def rgb_image(image):
    fixed = ImageOps.exif_transpose(image)
    if "A" in fixed.getbands() or "transparency" in fixed.info:
        fixed = fixed.convert("RGBA")
        white = Image.new("RGBA", fixed.size, "white")
        return Image.alpha_composite(white, fixed).convert("RGB")
    return fixed.convert("RGB")


def open_image(key, path, name=None):
    if path.stat().st_size > MAX_FILE:
        raise ValueError("单个文件最多 16 MiB")
    return image_bytes(key, path.read_bytes(), name or path.name)


def image_bytes(key, data, name):
    if len(data) > MAX_FILE:
        raise ValueError("单个文件最多 16 MiB")
    with Image.open(BytesIO(data)) as image:
        if image.format not in ("JPEG", "PNG", "WEBP"):
            raise ValueError("请使用 JPG、PNG、WebP 或 PDF")
        if min(image.size) < 16 or max(image.size) > 6500 or image.width * image.height > 12_000_000:
            raise ValueError("图片尺寸超出工作台限制")
        return PageImage(key, rgb_image(image), name, sha256(data).hexdigest())


def pdf_pages(source, numbers=None, prefix="", fields=(), name=None):
    try:
        document = pypdfium2.PdfDocument(source)
    except pypdfium2.PdfiumError as exc:
        raise ValueError("无法打开 PDF，可能已加密或文件损坏") from exc
    try:
        if numbers is None:
            if len(document) > MAX_PAGES:
                raise ValueError(f"PDF 共有 {len(document)} 页，请指定不超过 {MAX_PAGES} 页的范围")
            numbers = tuple(range(1, len(document) + 1))
        if not numbers or len(numbers) > MAX_PAGES or min(numbers) < 1 or max(numbers) > len(document):
            raise ValueError("PDF 页码超出范围")
        result = []
        pixels = 0
        source_hash = sha256(source).hexdigest() if isinstance(source, bytes) else None
        for n in numbers:
            page = document[n - 1]
            try:
                width, height = page.get_size()
                if min(width, height) <= 0:
                    raise ValueError(f"第 {n} 页尺寸无效")
                pixels += int(width * height * (RASTER_EDGE / max(width, height)) ** 2)
                if pixels > MAX_TOTAL_PIXELS:
                    raise ValueError("页面总像素超过内存限额，请缩小选页范围")
                bitmap = page.render(scale=RASTER_EDGE / max(width, height), may_draw_forms=False)
                try:
                    image = bitmap.to_pil().convert("RGB")
                    hints = index_page(page, bitmap, fields)
                finally:
                    bitmap.close()
            finally:
                page.close()
            digest = f"{source_hash}:{n}:{RASTER_EDGE}:{pypdfium2.PDFIUM_INFO.build}" if source_hash else None
            page_name = f"{name} · PDF 第 {n} 页" if name else f"PDF 第 {n} 页"
            result.append(PageImage(f"{prefix}p{n:02d}", image, page_name, digest, hints))
        return result
    except pypdfium2.PdfiumError as exc:
        raise ValueError("PDF 页面无法渲染，请检查页码或原文件") from exc
    finally:
        document.close()


def page_range(raw):
    if not raw:
        return None
    numbers = []
    for part in raw.split(","):
        if not re.fullmatch(r"[1-9]\d{0,4}(?:-[1-9]\d{0,4})?", part.strip()):
            raise ValueError("页码用 2,5-8 格式填写")
        first, _, last = part.strip().partition("-")
        a, b = int(first), int(last or first)
        if b < a or len(numbers) + b - a + 1 > MAX_PAGES:
            raise ValueError(f"页码范围需递增，最多选 {MAX_PAGES} 页")
        numbers.extend(range(a, b + 1))
    if len(set(numbers)) != len(numbers):
        raise ValueError("页码不能重复")
    return tuple(numbers)


def load_files(items, numbers=None, fields=()):
    """Expand named PDF or image byte streams without writing user input to disk."""
    if not items or len(items) > MAX_PAGES:
        raise ValueError(f"需提供 1–{MAX_PAGES} 个文件")
    if numbers is not None and (len(items) != 1 or not items[0][1].startswith(b"%PDF-")):
        raise ValueError("指定页码时，请只提供一个 PDF")
    if sum(len(data) for _, data in items) > MAX_TOTAL_FILE or any(len(data) > MAX_FILE for _, data in items):
        raise ValueError("单个文件最多 16 MiB，单次合计最多 32 MiB")
    result = []
    pixels = 0
    for index, (name, data) in enumerate(items, start=1):
        name = re.split(r"[/\\]", name)[-1][:100]
        if data.startswith(b"%PDF-"):
            pages = pdf_pages(data, numbers, f"d{index:02d}-", fields, name)
        else:
            pages = [image_bytes(f"i{index:02d}", data, name)]
        pixels += sum(page.size[0] * page.size[1] for page in pages)
        if len(result) + len(pages) > MAX_PAGES or pixels > MAX_TOTAL_PIXELS:
            raise ValueError("总页数或像素超出工作台上限，请减少文件或指定页码")
        result.extend(pages)
    return result


def load_paths(paths, numbers=None, fields=()):
    if len(paths) > MAX_PAGES or sum(path.stat().st_size for path in paths) > MAX_TOTAL_FILE:
        raise ValueError("文件数量或体积超出工作台上限")
    if any(path.stat().st_size > MAX_FILE for path in paths):
        raise ValueError("单个文件最多 16 MiB")
    return load_files([(path.name, path.read_bytes()) for path in paths], numbers, fields)
