#!/usr/bin/env bash
set -euo pipefail
printf '#!/usr/bin/env bun\nconsole.log("patched binary")\n' > packages/oh-my-opencode-linux-x64/bin/oh-my-opencode
