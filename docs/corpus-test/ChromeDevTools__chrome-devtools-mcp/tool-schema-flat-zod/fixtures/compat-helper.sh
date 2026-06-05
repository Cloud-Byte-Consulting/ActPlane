#!/usr/bin/env bash
set -euo pipefail

node <<'NODE'
const fs = require('node:fs');
const target = 'src/tools/network.ts';
const before = "    reqid: zod\n      .number()\n      .optional()\n      .describe(";
const after = "    reqid: zod\n      .number()\n      .optional()\n      .nullable()\n      .describe(";
const content = fs.readFileSync(target, 'utf8');
if (!content.includes(before)) {
  throw new Error(`anchor missing in ${target}`);
}
fs.writeFileSync(target, content.replace(before, after));
NODE
