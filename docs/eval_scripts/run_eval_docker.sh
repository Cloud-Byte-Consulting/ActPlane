#!/bin/bash
# Run the ActPlane eval in a privileged container with overlayfs isolation.
#
# - Host kernel is shared (eBPF works)
# - Workspace is overlaid: reads come from host, writes go to tmpfs
# - llama-server runs on host, container reaches it via --network host
# - On exit, all filesystem changes are discarded
#
# Prerequisites:
#   1. llama-server running on host:  python3 docs/eval_scripts/llama_server.py start &
#   2. docker available with privileged access
#
# Usage:
#   bash docs/eval_scripts/run_eval_docker.sh [extra args for agent_sdk_eval.py]
#
# Examples:
#   bash docs/eval_scripts/run_eval_docker.sh --limit 5 --system prompt-only
#   bash docs/eval_scripts/run_eval_docker.sh --system actplane --max-steps 8

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Build a minimal image with Python + deps if it doesn't exist
IMAGE_NAME="actplane-eval"
if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    echo "Building eval container image..."
    docker build -t "$IMAGE_NAME" -f - "$REPO_ROOT" <<'DOCKERFILE'
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    git curl sudo \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --break-system-packages openai-agents openai requests pyyaml

# Pre-create the overlay mount point
RUN mkdir -p /workspace
DOCKERFILE
fi

# Results go to a host-visible tmpdir so they survive container exit
RESULTS_DIR=$(mktemp -d /tmp/actplane-eval-results-XXXXXX)
echo "Results will be saved to: $RESULTS_DIR"

# Run the eval inside the container
# The workspace is bind-mounted read-only; an overlay provides a writable layer.
# The actplane binary and eval scripts come from the host workspace.
docker run --rm \
    --privileged \
    --network host \
    --name actplane-eval-run \
    -v "$REPO_ROOT:/workspace-ro:ro" \
    -v "$RESULTS_DIR:/results" \
    -e "LLAMA_URL=http://127.0.0.1:18080/v1" \
    "$IMAGE_NAME" \
    bash -c '
set -euo pipefail

# Create overlay: lower=read-only workspace, upper+work in tmpfs
mkdir -p /tmp/overlay-upper /tmp/overlay-work /workspace
mount -t overlay overlay \
    -o lowerdir=/workspace-ro,upperdir=/tmp/overlay-upper,workdir=/tmp/overlay-work \
    /workspace

cd /workspace

# Verify actplane binary works
if ./collector/target/release/actplane --version 2>/dev/null; then
    echo "actplane binary OK"
else
    echo "WARNING: actplane binary may not work (different glibc?), building..."
    # Fallback: the binary should work since we share the host OS
fi

echo "=== Running eval ==="
python3 docs/eval_scripts/agent_sdk_eval.py \
    --root docs/corpus-test \
    --model-name "Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M" \
    --llama-url "${LLAMA_URL}" \
    --max-steps 8 \
    "$@"

# Copy results out before overlay is torn down
echo "=== Copying results ==="
find docs/corpus-test -name "20260602T*.json" -newer /tmp/overlay-upper 2>/dev/null | while read f; do
    mkdir -p "/results/$(dirname "$f")"
    cp "$f" "/results/$f"
done

# Also copy any results from the overlay upper dir
find /tmp/overlay-upper -name "*.json" 2>/dev/null | while read f; do
    rel="${f#/tmp/overlay-upper/}"
    mkdir -p "/results/$(dirname "$rel")"
    cp "$f" "/results/$rel"
done

echo "=== Done ==="
' -- "$@"

echo ""
echo "Results saved to: $RESULTS_DIR"
echo "Result files:"
find "$RESULTS_DIR" -name "*.json" 2>/dev/null | head -30
