#!/bin/sh
set -eu
cd "$(dirname "$0")"
study_dir="$PWD"
repo_dir=$(CDPATH= cd -- ../.. && pwd)
VISUAL_SEARCH_BATCH_DIR="$repo_dir/batch"
export VISUAL_SEARCH_BATCH_DIR
batch="$VISUAL_SEARCH_BATCH_DIR/batch.sh"
py="${VISUAL_SEARCH_PYTHON:-}"
if [ -z "$py" ]; then
    if command -v python3 >/dev/null 2>&1 && python3 -c 'import numpy,PIL,pypdfium2' >/dev/null 2>&1; then
        py=python3
    else
        py="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
    fi
fi
export VISUAL_SEARCH_PYTHON="$py"
(cd "$repo_dir" && shasum -a 256 -c "$study_dir/engine.sha256")
shasum -a 256 -c publication.sha256
case "${1:-replay}" in
    prepare)
        prepared_dir=$(mktemp -d)
        "$py" -B prepare.py compile human-labels.json "$prepared_dir"
        cmp holdout.json "$prepared_dir/holdout.json"
        cmp jobs.json "$prepared_dir/jobs.json"
        cmp labels.png "$prepared_dir/labels.png"
        printf '%s\n' "Source PDFs reproduced the frozen inputs."
        ;;
    replay)
        "$py" -B verify.py --batch pilot.jobs.json results/pilot.sqlite --batch remainder.jobs.json results/remainder.sqlite
        ;;
    live)
        out=$(mktemp -d)
        sh "$batch" validate jobs.json > "$out/validation.jsonl"
        sh "$batch" run jobs.json --state "$out/progress.sqlite" > "$out/run.jsonl"
        "$py" -B score.py --batch jobs.json "$out/progress.sqlite" --out "$out"
        diff -u results/rows.tsv "$out/rows.tsv"
        diff -u results/summary.tsv "$out/summary.tsv"
        "$py" -B verify.py --batch jobs.json "$out/progress.sqlite" --results "$out"
        printf '%s\n' "Fresh outputs: $out"
        ;;
    *)
        printf '%s\n' 'Usage: sh reproduce.sh [replay|live|prepare]' >&2
        exit 2
        ;;
esac
