#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python="${VISUAL_SEARCH_PYTHON:-}"
if [ -z "$python" ]; then
    if command -v python3 >/dev/null 2>&1 && python3 -c 'import numpy, PIL, pypdfium2' >/dev/null 2>&1; then
        python=python3
    else
        python="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
    fi
fi
if ! command -v "$python" >/dev/null 2>&1; then
    printf '%s\n' '请设置 VISUAL_SEARCH_PYTHON，或安装移植包内 3.2 的 Python 依赖。' >&2
    exit 2
fi
exec "$python" -B "$root/batch.py" "$@"
