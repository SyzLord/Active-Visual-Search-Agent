"""Command-line entry points for live reading, training, and evaluation."""

import argparse
from itertools import islice
import json
from pathlib import Path
import sys

from PIL import Image, UnidentifiedImageError

from .corpus import COUNTS, EXTERNAL, example, examples, manifest_packs, read_manifest, synthetic
from .documents import ROOT, load_paths, page_range
from .evaluation import BUDGETS, MAIN_BUDGET, CachedReader, evaluate, report
from .ranker import WEIGHTS, Ranker, fit, samples
from .reader import OCR, ReaderRuntime
from .scheduler import DEFAULT_STRATEGY, IMAGE_STRATEGIES, STRATEGIES, run
from .task import parse_task

def write_json(payload, path=None):
    body = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if path is None:
        print(body, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(body, encoding="utf-8")
    temporary.replace(path)


def feedback(pack, count):
    print(f"{pack} · 累计 {count}", file=sys.stderr, flush=True)


def read_query(args):
    if args.example:
        if args.task or args.files or args.pages:
            raise ValueError("使用样例时无需提供任务、页码或图片")
        pages, raw = example(args.example, args.strategy in ("hybrid", "audited", "scan-audit"))
    else:
        if not args.files or not args.task:
            raise ValueError("请指定 --example，或同时提供 --files 和 --task")
        raw = json.loads(args.task.read_text(encoding="utf-8"))
        fields = parse_task(raw).fields if args.strategy in ("hybrid", "audited", "scan-audit") else ()
        pages = load_paths(args.files, page_range(args.pages), fields)
    ranker = Ranker.load(args.weights) if args.strategy == "learned" else None
    with OCR(ReaderRuntime()) as engine:
        result = run(parse_task(raw), pages, args.budget, lambda page, spec: page.observe(spec, engine),
                     args.strategy, ranker)
    write_json(result, args.output)


def make_parser():
    cli = argparse.ArgumentParser(description="像素预算下的跨页文档取证 Agent")
    sub = cli.add_subparsers(dest="command", required=True)
    query = sub.add_parser("query", help="实时读取文件或内置样例")
    query.add_argument("--example")
    query.add_argument("--task", type=Path)
    query.add_argument("--files", type=Path, nargs="+", help="支持 PDF、JPG、PNG、WebP")
    query.add_argument("--pages", help="只在单个 PDF 时可用，例如 2,5-8")
    query.add_argument("--strategy", choices=STRATEGIES, default=DEFAULT_STRATEGY)
    query.add_argument("--budget", type=int, default=MAIN_BUDGET)
    query.add_argument("--weights", type=Path, default=WEIGHTS)
    query.add_argument("--output", type=Path)
    sub.add_parser("list-examples", help="显示可用样例")
    sub.add_parser("test", help="运行单元测试与离线 OCR 集成测试")
    serve = sub.add_parser("serve", help="启动本机工作台")
    serve.add_argument("--port", type=int, default=8769)
    train = sub.add_parser("train", help="用合成训练集拟合动作评分")
    train.add_argument("--cache", type=Path, default=ROOT / ".cache/ocr.sqlite")
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--train-limit", type=int)
    train.add_argument("--dev-limit", type=int)
    bench = sub.add_parser("benchmark", help="以同一预算和同一 OCR 对比策略")
    bench.add_argument("--split", choices=("dev", "test", "external"), required=True)
    bench.add_argument("--cache", type=Path, default=ROOT / ".cache/ocr.sqlite")
    bench.add_argument("--output", type=Path, required=True)
    bench.add_argument("--weights", type=Path, default=WEIGHTS)
    bench.add_argument("--budget", nargs="+", type=int, default=BUDGETS)
    bench.add_argument("--strategy", nargs="+", choices=STRATEGIES)
    bench.add_argument("--input", choices=("image", "pdf"), default="image")
    bench.add_argument("--pack-limit", type=int)
    return cli


def main():
    parser = make_parser()
    args = parser.parse_args()
    try:
        if args.command == "query":
            read_query(args)
        elif args.command == "list-examples":
            write_json(examples())
        elif args.command == "test":
            from unittest import TextTestRunner, defaultTestLoader
            suite = defaultTestLoader.discover(str(ROOT / "tests"))
            if not TextTestRunner(verbosity=2).run(suite).wasSuccessful():
                sys.exit(1)
        elif args.command == "serve":
            from .webapp import serve
            serve(args.port)
        elif args.command == "train":
            with CachedReader(args.cache, ReaderRuntime()) as reader:
                train = samples(synthetic("train", args.train_limit), reader, feedback)
                dev = samples(synthetic("dev", args.dev_limit), reader, feedback)
                ranker, metadata = fit(train, dev)
                metadata.update(ocr=reader.runtime.identifier,
                                packs={"train": min(args.train_limit or COUNTS["train"], COUNTS["train"]),
                                       "dev": min(args.dev_limit or COUNTS["dev"], COUNTS["dev"])})
                ranker.save(args.output, metadata)
                print(f"OCR 缓存命中 {reader.hits}，实际读取 {reader.misses}", file=sys.stderr)
        else:
            if args.input == "pdf" and args.split != "external":
                raise ValueError("仅公开文档集提供 PDF 原件")
            strategies = args.strategy or (STRATEGIES if args.input == "pdf" else IMAGE_STRATEGIES)
            ranker = Ranker.load(args.weights) if "learned" in strategies else None
            if args.split == "external":
                if args.input == "pdf":
                    reference = read_manifest(EXTERNAL)
                    fields = tuple(f for group in reference["packs"] for row in group["cases"]
                                   for f in parse_task(row["task"]).fields) if any(s in strategies for s in ("hybrid", "audited", "scan-audit")) else ()
                    packs = manifest_packs(EXTERNAL, from_pdf=True, fields=fields)
                else:
                    packs = manifest_packs(EXTERNAL)
                if args.pack_limit is not None:
                    packs = islice(packs, args.pack_limit)
            else:
                packs = synthetic(args.split, args.pack_limit)
            with CachedReader(args.cache, ReaderRuntime()) as reader:
                rows = evaluate(packs, args.budget, strategies, reader, ranker, feedback)
                if not rows:
                    raise ValueError("没有评测样例")
                write_json(report(rows, args.split, reader, args.input), args.output)
                print(f"OCR 缓存命中 {reader.hits}，实际读取 {reader.misses}", file=sys.stderr)
    except (ValueError, RuntimeError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        parser.exit(2, f"错误：{error}\n")


if __name__ == "__main__":
    main()
