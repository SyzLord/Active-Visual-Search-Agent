#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
runtime_python="${VISUAL_SEARCH_PYTHON:-}"
if [ -z "$runtime_python" ]; then
    if command -v python3 >/dev/null 2>&1 && python3 -c 'import numpy, PIL, pypdfium2' >/dev/null 2>&1; then
        runtime_python=python3
    else
        runtime_python="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
    fi
fi
if ! command -v "$runtime_python" >/dev/null 2>&1; then
    printf '%s\n' '请指定 VISUAL_SEARCH_PYTHON，或安装项目 3.2 requirements.txt 中的依赖。' >&2
    exit 1
fi
exec "$runtime_python" -B "$project_dir/evidence.py" "$@"
