#!/usr/bin/env bash
set -euo pipefail
pkg="oh-my-opencode-linux-x64"
binary="oh-my-opencode"
out="packages/${pkg}/bin/${binary}"
printf '#!/usr/bin/env bun\nconsole.log("opaque artifact")\n' > "$out"
