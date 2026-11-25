"""Batch document evidence CLI with durable resume."""
import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from batch_engine import Engine, manifest
from batch_state import connect, exclusive, finish, interrupted, metadata, register, start, summary


def event(name,**fields):
    print(json.dumps({"event":name,**fields},ensure_ascii=False),flush=True)


def execute(args,state):
    source = args.manifest.resolve()
    jobs,digest = manifest(source)
    if source==state:
        raise ValueError("任务清单与进度文件需要使用不同路径")
    with exclusive(state):
        with connect(state,writable=True) as db:
            engine = Engine()
            runtime = engine.configure()
            from PIL import Image
            from pypdfium2 import PdfiumError
            from struct import error as StructError
            from zlib import error as ZlibError
            task_errors = (OSError,ValueError,RuntimeError,Image.DecompressionBombError,PdfiumError,EOFError,SyntaxError,
                           StructError,ZlibError)
            register(db,digest,runtime,jobs)
            for key in interrupted(db):
                event("interrupted",id=key)
            states = dict(db.execute("SELECT id,state FROM jobs"))
            for job in jobs:
                key = job["id"]
                if states[key]=="done" or (states[key]=="failed" and not args.retry_failed):
                    event("skipped",id=key,state=states[key])
                    continue
                number = start(db,key)
                event("started",id=key,attempt=number)
                try:
                    result = engine.execute(job,engine.check(job,source.parent))
                except task_errors as exc:
                    error = f"{type(exc).__name__}: {exc}"[:2400]
                    finish(db,key,number,error=error)
                    event("failed",id=key,attempt=number,error=error)
                    continue
                finish(db,key,number,result=result)
                event("done",id=key,attempt=number,decision=result["decision"]["status"],
                      pixels=result["decision"]["cost"]["total"],ocr_calls=result["trace"]["ocr_calls"])
            counts = summary(db)["counts"]
            event("batch_finished",**counts)
            return int(counts["failed"]>0)


def validate(args):
    source = args.manifest.resolve()
    jobs,_ = manifest(source)
    engine = Engine()
    from PIL import Image
    failed = False
    for job in jobs:
        try:
            _,_,pages,inputs = engine.check(job,source.parent)
        except (OSError,ValueError,RuntimeError,Image.DecompressionBombError,SyntaxError,EOFError) as exc:
            failed = True
            event("invalid",id=job["id"],error=str(exc)[:2400])
        else:
            event("valid",id=job["id"],pages=len(pages),inputs=inputs)
    return int(failed)


def dump(value):
    print(json.dumps(value,ensure_ascii=True,indent=2))


def inspect(args,state):
    with connect(state) as db:
        if args.command=="status":
            report = summary(db)
            if args.json:
                dump(report)
            else:
                counts = report["counts"]
                print(f"完成 {counts['done']}，失败 {counts['failed']}，未开始 {counts['pending']}，进行中 {counts['running']}")
                print("ID\t任务\t状态\t尝试\t结论\t像素\tOCR 次数\t错误")
                for row in report["jobs"]:
                    values = [row[k] for k in ("id","kind","state","attempts","decision","pixels","ocr_calls","error")]
                    print("\t".join("-" if value is None else str(value).replace("\n"," ").replace("\r"," ").replace("\t"," ")
                                    for value in values))
        elif args.command=="attempts":
            metadata(db)
            dump([dict(row) for row in db.execute("SELECT * FROM attempts ORDER BY rowid")])
        else:
            row = db.execute("SELECT result,error,state,attempt FROM jobs WHERE id=?",(args.id,)).fetchone()
            if row is None:
                raise ValueError("进度文件中无此任务 ID")
            dump({"id":args.id,"state":row["state"],"attempts":row["attempt"],"error":row["error"],
                  "result":json.loads(row["result"]) if row["result"] is not None else None})
    return 0


def main():
    parser = argparse.ArgumentParser(description="批量文档取证与断点续跑")
    sub = parser.add_subparsers(dest="command",required=True)
    check = sub.add_parser("validate",help="检查任务和输入，不运行 OCR")
    check.add_argument("manifest",type=Path)
    run = sub.add_parser("run",help="执行或续跑")
    run.add_argument("manifest",type=Path)
    run.add_argument("--retry-failed",action="store_true",help="也重试先前失败的任务")
    status = sub.add_parser("status",help="读取任务汇总")
    status.add_argument("--json",action="store_true")
    show = sub.add_parser("show",help="导出单项结果和逐步证据")
    show.add_argument("id")
    sub.add_parser("attempts",help="读取完整尝试记录")
    for command in (run,status,show,sub.choices["attempts"]):
        command.add_argument("--state",required=True,type=Path,help="本地进度 SQLite 文件")
    args = parser.parse_args()
    try:
        if args.command=="validate":
            return validate(args)
        state = args.state.resolve()
        return execute(args,state) if args.command=="run" else inspect(args,state)
    except KeyboardInterrupt:
        print("已停止。再次运行相同清单和进度文件即可续跑。",file=sys.stderr)
        return 130
    except (ValueError,OSError,RuntimeError,ImportError,sqlite3.Error,subprocess.SubprocessError) as exc:
        print(f"批次无法执行：{exc}",file=sys.stderr)
        return 2


if __name__=="__main__":
    sys.exit(main())
