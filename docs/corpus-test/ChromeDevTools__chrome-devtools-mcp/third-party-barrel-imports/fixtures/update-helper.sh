#!/usr/bin/env bash
set -euo pipefail

node <<'NODE'
const fs = require('node:fs');
const target = 'src/utils/check-for-updates.ts';
const before = "import {semver} from '../third_party/index.js';";
const after = "import semver from 'semver';";
const content = fs.readFileSync(target, 'utf8');
if (!content.includes(before)) {
  throw new Error(`anchor missing in ${target}`);
}
fs.writeFileSync(target, content.replace(before, after));
NODE
