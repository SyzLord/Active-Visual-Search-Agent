"""Manifest validation and adapters for the original document queries."""
from hashlib import sha256
import importlib.util
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import re
import stat
import sys


HERE = Path(__file__).resolve().parent
BUDGET = 1_000_000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024


def unique_object(pairs):
    result = {}
    for name,value in pairs:
        if name in result:
            raise ValueError(f"JSON 字段重复：{name}")
        result[name] = value
    return result


def invalid_constant(value):
    raise ValueError(f"JSON 不支持 {value}")


def manifest(path):
    with path.open("rb") as handle:
        encoded = handle.read(MAX_MANIFEST_BYTES+1)
    if len(encoded)>MAX_MANIFEST_BYTES:
        raise ValueError("任务清单最多 4 MiB")
    root = json.loads(encoded,object_pairs_hook=unique_object,parse_constant=invalid_constant)
    if not isinstance(root,dict) or set(root)!={"version","jobs"} or type(root["version"]) is not int or root["version"]!=1:
        raise ValueError("清单根对象须包含 version=1 和 jobs")
    jobs = root["jobs"]
    if not isinstance(jobs,list) or not jobs:
        raise ValueError("jobs 必须是非空列表")
    ids = set()
    for index,job in enumerate(jobs,1):
        key = job.get("id") if isinstance(job,dict) else None
        if not isinstance(key,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}",key) or key in ids:
            raise ValueError(f"第 {index} 项缺少有效的唯一 ID")
        ids.add(key)
    canonical = json.dumps(root,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False)
    return jobs,sha256(canonical.encode()).hexdigest()


def dependency_identity():
    lock = (HERE/"vendor.sha256").read_bytes()
    for line in lock.decode().splitlines():
        expected,name = line.split("  ",1)
        if sha256((HERE/name).read_bytes()).hexdigest()!=expected:
            raise ValueError(f"运行依赖的摘要发生变化：{name}")
    fingerprint = sha256(lock)
    for name in ("batch_engine.py","batch_state.py","batch.py"):
        fingerprint.update((HERE/name).read_bytes())
    return {"code":fingerprint.hexdigest(),"python":platform.python_version(),
            "python_dependencies":{name:version(name) for name in ("Pillow","numpy","pypdfium2")}}


def bounded_source(path,limit):
    descriptor = os.open(path,os.O_RDONLY|os.O_NONBLOCK)
    with os.fdopen(descriptor,"rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"只能读取普通文件：{path.name}")
        if info.st_size>limit:
            raise ValueError(f"输入超出单文件 16 MiB 或总计 32 MiB 的限制：{path.name}")
        data = handle.read(limit+1)
        if len(data)>limit:
            raise ValueError(f"输入读取时超出大小限制：{path.name}")
        return data


class Engine:
    def __init__(self):
        target = HERE/"vendor/主动视觉搜索_印章候选覆盖_2026-11-25/run.py"
        sys.path.insert(0,str(target.parent))
        spec = importlib.util.spec_from_file_location("nov25_query",target)
        self.query = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.query)
        from search_agent import documents, scheduler, task
        from search import InputMeter
        self.documents,self.scheduler,self.tasks = documents,scheduler,task
        self.meter = InputMeter

    def configure(self):
        self.config = self.query.prior.grader.ReaderRuntime()
        import subprocess
        node_version = subprocess.check_output([self.config.node,"--version"],text=True,timeout=15).strip()
        return {"ocr":self.config.identifier,"node":node_version,**dependency_identity()}

    def check(self,job,root):
        kind = job.get("kind")
        shared = {"id","kind","files","pages","pixel_budget"}
        if type(job.get("pixel_budget",BUDGET)) is not int or job.get("pixel_budget",BUDGET)!=BUDGET:
            raise ValueError("每项 pixel_budget 固定为 1000000")
        if kind=="stamp":
            if set(job)-shared-{"date","text","policy"}:
                raise ValueError("收件章任务含未知字段")
            policy = job.get("policy","month-routed-stamp")
            if not isinstance(policy,str) or policy not in self.query.POLICIES:
                raise ValueError("收件章 policy 应为 month-routed-stamp 或 spare-stamp")
            if not all(isinstance(job.get(key),str) for key in ("date","text")):
                raise ValueError("收件章任务需要 date 和 text")
            task = self.query.make_task(job["date"],job["text"])
        elif kind=="document":
            if set(job)-shared-{"task"}:
                raise ValueError("文档任务含未知字段")
            policy = "audited"
            raw_task = job.get("task")
            if not isinstance(raw_task,dict) or not isinstance(raw_task.get("op"),str):
                raise ValueError("文档任务需要 task 对象和 op")
            task = self.tasks.parse_task(raw_task)
        else:
            raise ValueError("kind 应为 stamp 或 document")
        paths = job.get("files")
        if not isinstance(paths,list) or not 1<=len(paths)<=self.documents.MAX_PAGES or not all(
                isinstance(path,str) and path.strip() and "\0" not in path and not Path(path).is_absolute()
                for path in paths):
            raise ValueError("files 须包含 1–24 个相对于任务清单的文件路径")
        selected = job.get("pages")
        if selected is not None and (not isinstance(selected,str) or not selected.strip()):
            raise ValueError("pages 使用 2,5-8 格式")
        numbers = self.documents.page_range(selected)
        items, sources = [], []
        left = self.documents.MAX_TOTAL_FILE
        for entry in paths:
            path = root/entry
            try:
                data = bounded_source(path,min(self.documents.MAX_FILE,left))
            except OSError as exc:
                raise ValueError(f"{entry}：{exc.strerror}") from exc
            left -= len(data)
            items.append((path.name,data))
            sources.append({"path":entry,"bytes":len(data),"sha256":sha256(data).hexdigest()})
        fields = task.fields if kind=="document" else ()
        pages = self.documents.load_files(items,numbers,fields)
        available = {page.key for page in pages}
        if any(set(field.pages)-available for field in task.fields):
            raise ValueError("字段 pages 包含不在输入中的页面 ID")
        return task,policy,pages,sources

    def execute(self,job,prepared):
        task,policy,pages,sources = prepared
        # A fresh reader per task isolates OCR exits and timeouts.
        with self.query.prior.grader.OCR(self.config) as reader:
            if job["kind"]=="stamp":
                base = self.query.run_query("horizontal-footer",task,pages,reader)
                trace = self.query.POLICIES[policy](base,task,pages,reader)
                decision = self.query.source_checked(trace,{p.key:p.size for p in pages},
                                                      self.query.requested_date(job["date"]))
            else:
                trace,decision = self.document_query(task,pages,policy,reader)
        return {"id":job["id"],"kind":job["kind"],"policy":policy,"ocr":self.config.identifier,
                "sources":sources,"pages":[{"id":p.key,"name":p.name,"size":list(p.size),"fingerprint":p.digest}
                                          for p in pages],"decision":decision,"trace":trace}

    def document_query(self,task,pages,policy,reader):
        meter = self.meter(reader)
        trace = self.scheduler.run(task,pages,BUDGET,lambda p,s:p.observe(s,meter),policy)
        pixels = 0
        for index,(step,call) in enumerate(zip(trace["steps"],meter.calls,strict=True),1):
            width,height = call["size"]
            cost = width*height
            pixels += cost
            if (step["step"],step["size"],step["pixels"],step["spent"],step["ocr_lines"])!=(
                    index,call["size"],cost,pixels,len(call["raw_normalized"])):
                raise RuntimeError("OCR 实际输入与账本不一致")
            step.update(engine_mode=call["mode"],input_sha256=call["input_sha256"],raw_normalized=call["raw_normalized"])
        if trace["spent"]!=pixels or pixels>BUDGET or trace["ocr_calls"]!=len(meter.calls):
            raise RuntimeError("文档检索超出像素预算或账本不一致")
        decision = {key:trace[key] for key in ("status","answer","evidence","field_assessments")}
        decision["cost"] = {"preview":0,"ocr":pixels,"total":pixels}
        return trace,decision
