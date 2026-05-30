#!/usr/bin/env bash
# Clone all corpus repos into docs/corpus-evaluated/{owner}__{name}/repo/
# Uses --depth=1 for minimal disk usage (~4-5 GB total).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CORPUS="$ROOT/docs/corpus"
EVALUATED="$ROOT/docs/corpus-evaluated"

cloned=0
skipped=0
failed=0

for meta in "$CORPUS"/*/meta.json; do
    dir="$(dirname "$meta")"
    repo_dir_name="$(basename "$dir")"
    repo=$(python3 -c "import json; print(json.load(open('$meta'))['repo'])")
    target="$EVALUATED/$repo_dir_name/repo"

    if [ -d "$target/.git" ]; then
        echo "SKIP $repo (already cloned)"
        skipped=$((skipped + 1))
        continue
    fi

    echo "CLONE $repo -> $target"
    mkdir -p "$target"
    if git clone --depth=1 "https://github.com/$repo.git" "$target" 2>/dev/null; then
        cloned=$((cloned + 1))
    else
        echo "FAIL $repo"
        rm -rf "$target"
        failed=$((failed + 1))
    fi
done

echo "---"
echo "Cloned: $cloned  Skipped: $skipped  Failed: $failed"
