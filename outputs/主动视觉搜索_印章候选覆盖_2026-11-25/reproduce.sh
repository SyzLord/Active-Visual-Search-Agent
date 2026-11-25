#!/bin/sh
set -eu
out=${1:-}
if [ -z "$out" ]; then
    out=$(mktemp -d)
fi
out=$(CDPATH= cd -- "$out" && pwd)
cd "$(dirname "$0")"
shasum -a 256 -c policy.sha256
shasum -a 256 -c holdout.sha256
sh run.sh replay regression.json
sh run.sh replay holdout-results.json
sh run.sh benchmark regression "$out/regression.json" --fresh-baseline
sh run.sh benchmark holdout "$out/holdout.json"
sh run.sh rows "$out/regression.json" > "$out/regression.tsv"
sh run.sh rows "$out/holdout.json" > "$out/holdout.tsv"
diff -u regression.tsv "$out/regression.tsv"
diff -u holdout.tsv "$out/holdout.tsv"
sh run.sh replay "$out/holdout.json"
printf '%s\n' "已重跑全部题目并逐行比对。输出目录 $out"
