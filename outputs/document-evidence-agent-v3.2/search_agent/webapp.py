"""Local workbench. Uploads, raster crops and results remain in the request."""

from base64 import b64decode, b64encode
from binascii import Error as DecodeError
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
import json
from time import perf_counter
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError

from .corpus import example, examples
from .documents import MAX_PAGES, MAX_TOTAL_FILE, ROOT, load_files, page_range
from .evaluation import MAIN_BUDGET
from .ranker import WEIGHTS, Ranker
from .reader import OCR, ReaderRuntime
from .scheduler import DEFAULT_STRATEGY, run
from .task import parse_task

STATIC = ROOT / "search_agent/static"
CONTENT = {"/": ("index.html", "text/html; charset=utf-8"),
           "/style.css": ("style.css", "text/css; charset=utf-8"),
           "/app.js": ("app.js", "text/javascript; charset=utf-8")}
MAX_BODY = MAX_TOTAL_FILE * 4 // 3 + 128 * 1024


def data_uri(data):
    return f"data:image/jpeg;base64,{b64encode(data).decode('ascii')}"


def preview(page):
    image = page.image.copy()
    image.thumbnail((930, 930))
    content = BytesIO()
    image.save(content, "JPEG", quality=83, optimize=True)
    return data_uri(content.getvalue())


def process(payload, runtime, ranker):
    if not isinstance(payload, dict):
        raise ValueError("请求需为 JSON 对象")
    begin = perf_counter()
    strategy = payload.get("strategy", DEFAULT_STRATEGY)
    if "example" in payload:
        pages, raw = example(payload["example"], strategy in ("hybrid", "audited", "scan-audit"), payload.get("task"))
    else:
        rows = payload.get("files")
        if not isinstance(rows, list) or not rows or len(rows) > MAX_PAGES:
            raise ValueError(f"请选择 1–{MAX_PAGES} 个文件")
        files = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("data"), str) or not isinstance(row.get("name"), str):
                raise ValueError("上传文件格式不正确")
            try:
                data = b64decode(row["data"], validate=True)
            except (DecodeError, ValueError) as error:
                raise ValueError("上传内容无法解码") from error
            files.append((row["name"], data))
        selection = payload.get("pages", "")
        if not isinstance(selection, str) or len(selection) > 160:
            raise ValueError("页码范围格式不正确")
        raw = payload.get("task")
        fields = parse_task(raw).fields if strategy in ("hybrid", "audited", "scan-audit") else ()
        pages = load_files(files, page_range(selection), fields)
    task = parse_task(raw)
    crops = []

    def capture(_, encoded):
        # Each retained image is the same raster sent to OCR for its ledger step.
        crops.append(data_uri(encoded))

    with OCR(runtime) as engine:
        result = run(task, pages, payload.get("budget", MAIN_BUDGET),
                     lambda page, spec: page.observe(spec, engine, capture=capture),
                     strategy, ranker)
    response = {"result": result, "previews": {page.key: preview(page) for page in pages},
                "views": crops, "task": raw}
    response["request_ms"] = round((perf_counter() - begin) * 1000, 1)
    return response


class Workbench(HTTPServer):
    def __init__(self, port):
        self.runtime = ReaderRuntime()
        self.ranker = Ranker.load(WEIGHTS)
        super().__init__(("127.0.0.1", port), Handler)
        self.hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def send_body(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                         "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_json(self, status, value):
        self.send_body(status, json.dumps(value, ensure_ascii=False, allow_nan=False).encode(), "application/json")

    def allowed(self):
        host = self.headers.get("Host")
        origin = self.headers.get("Origin")
        if host not in self.server.hosts or origin not in (None, f"http://{host}"):
            self.send_json(403, {"error": "工作台仅处理当前本机来源"})
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        route = urlsplit(self.path).path
        if route == "/api/examples":
            rows = [{key: row[key] for key in ("id", "label", "description")} for row in examples()]
            self.send_json(200, {"examples": rows, "budget": MAIN_BUDGET, "strategy": DEFAULT_STRATEGY})
        elif route in CONTENT:
            name, content_type = CONTENT[route]
            self.send_body(200, (STATIC / name).read_bytes(), content_type)
        elif route == "/favicon.ico":
            self.send_body(204, b"", "image/x-icon")
        else:
            self.send_json(404, {"error": "页面不存在"})

    def do_POST(self):
        if not self.allowed():
            return
        if urlsplit(self.path).path != "/api/search":
            self.send_json(404, {"error": "接口不存在"})
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json(415, {"error": "请提交 application/json"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                self.send_json(413, {"error": "请求体为空或超过体积上限"})
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("请求体不完整")
            payload = json.loads(raw)
            response = process(payload, self.server.runtime, self.server.ranker)
        except (ValueError, UnidentifiedImageError, Image.DecompressionBombError, OSError) as error:
            self.send_json(400, {"error": str(error)})
        except RuntimeError as error:
            self.send_json(500, {"error": str(error)})
        else:
            self.send_json(200, response)


def serve(port):
    if not 0 <= port <= 65535:
        raise ValueError("端口需在 0–65535 之间")
    with Workbench(port) as server:
        print(f"本机工作台 http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return
