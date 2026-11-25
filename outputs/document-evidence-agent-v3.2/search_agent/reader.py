"""Only the environment holds the original image. OCR receives one raster at a time."""

from base64 import b64encode
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryFile
from threading import Event, Timer

import numpy as np
from PIL import Image, ImageOps

from .core import observation_specs


SOURCE = Path(__file__).with_name("ocr.cjs")
ROOT = SOURCE.parent.parent
MODEL = ROOT / "data" / "ocr" / "eng.traineddata"


class ReaderRuntime:
    def __init__(self):
        bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
        self.node = os.environ.get("VISUAL_SEARCH_NODE") or shutil.which("node")
        if not self.node and (bundled / "bin/node").is_file():
            self.node = str(bundled / "bin/node")
        if not self.node:
            raise RuntimeError("请安装 Node.js 18 或以上，或设置 VISUAL_SEARCH_NODE。")
        self.env = os.environ.copy()
        modules = [p for p in [self.env.get("NODE_PATH"), str(bundled / "node_modules")] if p]
        self.env["NODE_PATH"] = os.pathsep.join(modules)
        version = subprocess.run(
            [self.node, "-p", "require('tesseract.js/package.json').version + '/' + require('tesseract.js-core/package.json').version"],
            cwd=ROOT, env=self.env, text=True, capture_output=True, timeout=15,
        )
        if version.returncode:
            raise RuntimeError("缺少 Tesseract.js。请在项目目录执行 npm install。")
        if not MODEL.is_file():
            raise RuntimeError(f"缺少离线英文 OCR 权重 {MODEL}")
        self.version = version.stdout.strip()
        self.model_hash = sha256(MODEL.read_bytes()).hexdigest()
        self.identifier = f"tesseract-js-{self.version}-{self.model_hash[:12]}-{sha256(SOURCE.read_bytes()).hexdigest()[:12]}"


class OCR:
    def __init__(self, runtime, timeout=45):
        if timeout <= 0:
            raise ValueError("OCR timeout must be positive")
        self.timeout = timeout
        self.closed = False
        self.log = TemporaryFile()
        try:
            self.process = subprocess.Popen(
                [runtime.node, str(SOURCE), str(MODEL)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.log, text=True, encoding="utf-8", bufsize=1, env=runtime.env, cwd=ROOT,
            )
        except OSError:
            self.log.close()
            raise

    def diagnostics(self):
        end = self.log.seek(0, os.SEEK_END)
        self.log.seek(max(0, end - 1600))
        return self.log.read().decode("utf-8", errors="replace").strip()

    def recognize(self, encoded, size, mode="page"):
        if self.closed or self.process.poll() is not None:
            raise RuntimeError("OCR 进程已退出，请重新开始请求")
        payload = {"image": b64encode(encoded).decode("ascii"), "size": size, "mode": mode}
        expired = Event()

        def abort():
            expired.set()
            try:
                self.process.kill()
            except ProcessLookupError:
                pass

        timer = Timer(self.timeout, abort)
        timer.daemon = True
        timer.start()
        try:
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline()
        except BrokenPipeError as exc:
            if expired.is_set():
                raise RuntimeError("OCR 超时，进程已终止，可重新提交任务") from exc
            raise RuntimeError(f"OCR 进程提前退出。{self.diagnostics()}") from exc
        finally:
            timer.cancel()
            timer.join()
        if expired.is_set():
            raise RuntimeError("OCR 超时，进程已终止，可重新提交任务")
        if not line:
            raise RuntimeError(f"OCR 进程退出，未返回识别结果。{self.diagnostics()}")
        reply = json.loads(line)
        if "error" in reply:
            raise RuntimeError(f"OCR 识别失败：{reply['error']}")
        return reply["lines"]

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            try:
                self.process.stdin.close()
            except BrokenPipeError:
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        finally:
            self.process.stdout.close()
            self.log.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def raster_bytes(image, spec):
    raster = image.crop(spec.box)
    if raster.size != spec.size:
        raster = raster.resize(spec.size, Image.Resampling.LANCZOS)
    if spec.scale == "pdf-line":
        gray = raster.convert("L")
        histogram = gray.histogram()
        if sum(histogram[:128]) > .58 * raster.width * raster.height:
            raster = ImageOps.invert(gray)
    payload = BytesIO()
    raster.save(payload, "JPEG", quality=91)
    return payload.getvalue()


def pixel_features(image):
    gray = np.asarray(image.convert("L").resize((32, 32), Image.Resampling.BILINEAR), dtype=np.float32) / 255
    return [
        float(gray.std()),
        float(np.mean(np.abs(np.diff(gray, axis=0)))),
        float(np.mean(gray < 0.72)),
    ]


def project(box, original):
    x, y, right, bottom = original
    return [
        x + box[0] * (right - x), y + box[1] * (bottom - y),
        x + box[2] * (right - x), y + box[3] * (bottom - y),
    ]


class ImageScene:
    def __init__(self, path):
        with Image.open(path) as original:
            self.image = ImageOps.exif_transpose(original).convert("RGB")
        self.size = self.image.size
        if min(self.size) < 16:
            raise ValueError("图像的宽和高均需至少 16 像素")

    def observe(self, spec, ocr, save_to=None, capture=None):
        encoded = raster_bytes(self.image, spec)
        if save_to is not None:
            save_to.write_bytes(encoded)
        if capture is not None:
            capture(spec, encoded)
        lines = ocr.recognize(encoded, spec.size, "line" if spec.scale == "pdf-line" else "page")
        for line in lines:
            line["box"] = project(line["box"], spec.box)
            for word in line["words"] + line.get("raw_words", []):
                word["box"] = project(word["box"], spec.box)
        observation = {"box": list(spec.box), "size": list(spec.size), "lines": lines}
        if spec.key == "thumb":
            with Image.open(BytesIO(encoded)) as thumb:
                width, height = self.size
                observation["tile_pixels"] = {
                    str(tile.tile): pixel_features(thumb.crop((
                        round(tile.box[0] * thumb.width / width),
                        round(tile.box[1] * thumb.height / height),
                        max(1, round(tile.box[2] * thumb.width / width)),
                        max(1, round(tile.box[3] * thumb.height / height)),
                    )))
                    for tile in observation_specs(self.size).values() if tile.scale == "detail"
                }
        return observation
