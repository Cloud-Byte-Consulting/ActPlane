#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
from pathlib import Path

path = Path("kubernetes/apis/sandbox/v1alpha1/batchsandbox_types.go")
old = "\t// Replicas is the number of desired replicas.\n\t// +kubebuilder:validation:Required\n\t// +kubebuilder:validation:Minimum=0\n\t// +kubebuilder:default=1\n\tReplicas *int32 `json:\"replicas,omitempty\"`"
new = old + "\n\t// PriorityClassName selects the pod priority class for sandbox pods.\n\t// +optional\n\t// +kubebuilder:validation:Optional\n\tPriorityClassName string `json:\"priorityClassName,omitempty\"`"
text = path.read_text()
if old not in text:
    raise SystemExit(f"expected text not found in {path}")
path.write_text(text.replace(old, new, 1))
PY
