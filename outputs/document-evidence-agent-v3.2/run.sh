#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ -n "${VISUAL_SEARCH_PYTHON:-}" ]; then
    exec "$VISUAL_SEARCH_PYTHON" -B -m search_agent "$@"
fi
if command -v python3 >/dev/null 2>&1 && python3 -c 'import numpy, PIL, pypdfium2' >/dev/null 2>&1; then
    exec python3 -B -m search_agent "$@"
fi
bundled_python="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3.12"
if [ -x "$bundled_python" ]; then
    exec "$bundled_python" -B -m search_agent "$@"
fi
printf '%s\n' '请在 Python 3.11+ 环境安装 requirements.txt 中的依赖，或设置 VISUAL_SEARCH_PYTHON。' >&2
exit 1
