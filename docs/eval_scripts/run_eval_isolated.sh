#!/bin/bash
# Run ActPlane eval in overlay isolation. No images. No persistent changes.
# All host tools/libs available. Results copied out before teardown.
#
# Usage:
#   bash docs/eval_scripts/run_eval_isolated.sh [args for agent_sdk_eval.py]
# Examples:
#   bash docs/eval_scripts/run_eval_isolated.sh --limit 2 --system prompt-only
#   bash docs/eval_scripts/run_eval_isolated.sh --system actplane --max-steps 8
#   bash docs/eval_scripts/run_eval_isolated.sh  # all 20 scenarios

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

RESULTS_DIR=$(mktemp -d /tmp/actplane-eval-results-XXXXXX)
chmod 777 "$RESULTS_DIR"

# Find user site-packages so root can import them
USER_SITE=$(python3 -c 'import site; print(site.getusersitepackages())' 2>/dev/null || true)
SYS_SITE=$(python3 -c 'import site; print(":".join(site.getsitepackages()))' 2>/dev/null || true)
EXTRA_PYTHONPATH="${USER_SITE}:${SYS_SITE}:${PYTHONPATH:-}"

echo "Results dir: $RESULTS_DIR"
echo "Starting isolated eval..."

# Write the inner script to a temp file (avoids heredoc escaping hell)
INNER=$(mktemp /tmp/actplane-eval-inner-XXXXXX.sh)
cat > "$INNER" << 'EOF'
#!/bin/bash
set -euo pipefail
REPO_ROOT="$1"; shift
RESULTS_DIR="$1"; shift

OVL=$(mktemp -d /tmp/actplane-ovl-XXXXXX)
mkdir -p "$OVL/upper" "$OVL/work" "$OVL/merged"

mount -t overlay overlay \
    -o "lowerdir=$REPO_ROOT,upperdir=$OVL/upper,workdir=$OVL/work" \
    "$OVL/merged"

cd "$OVL/merged"
echo "=== Overlay ready, running eval ==="

python3 docs/eval_scripts/agent_sdk_eval.py \
    --root docs/corpus-test \
    --model-name "Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M" \
    --llama-url "http://127.0.0.1:18080/v1" \
    "$@"

echo ""
echo "=== Copying results ==="
find "$OVL/upper" -name "*.json" -path "*/results/*" 2>/dev/null | while IFS= read -r f; do
    rel="${f#$OVL/upper/}"
    mkdir -p "$RESULTS_DIR/$(dirname "$rel")"
    cp "$f" "$RESULTS_DIR/$rel"
done

cd /
umount -l "$OVL/merged" 2>/dev/null || true
rm -rf "$OVL" 2>/dev/null || true
echo "=== Overlay cleaned up ==="
EOF
chmod +x "$INNER"

sudo PYTHONPATH="$EXTRA_PYTHONPATH" \
     PATH="$PATH" \
     HOME="$HOME" \
     bash "$INNER" "$REPO_ROOT" "$RESULTS_DIR" "$@"

rm -f "$INNER"

echo ""
echo "========================================="
echo "Results: $RESULTS_DIR"
find "$RESULTS_DIR" -name "*.json" 2>/dev/null | while read -r f; do
    python3 -c "
import json
with open('$f') as fh:
    d = json.load(fh)
s = 'COMPLY' if d.get('compliant') else 'VIOLAT'
print(f'  [{s}] {d.get(\"repo\",\"?\")} {d.get(\"trace_file\",\"?\")} sys={d.get(\"system\",\"?\")} steps={d.get(\"step_count\",\"?\")}')
" 2>/dev/null || echo "  (parse error: $f)"
done
echo ""
echo "Host workspace unchanged:"
git -C "$REPO_ROOT" status --short docs/corpus-test/*/results/ 2>/dev/null | head -5 || echo "  (clean)"
echo ""
echo "Cleanup: rm -rf $RESULTS_DIR"
