#!/usr/bin/env bash
set -euo pipefail

cat > scripts/fixture-generated-helper.js <<'JS'
#!/usr/bin/env node
// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

"use strict";

console.log("fixture generated helper");
JS
chmod +x scripts/fixture-generated-helper.js
