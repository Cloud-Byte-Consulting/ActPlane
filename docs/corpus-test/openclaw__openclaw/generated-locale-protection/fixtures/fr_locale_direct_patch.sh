#!/usr/bin/env bash
set -euo pipefail

node - <<'JS'
const fs = require("fs");
const p = "ui/src/i18n/locales/fr.ts";
const s = fs.readFileSync(p, "utf8");
fs.writeFileSync(p, s.replace('health: "Santé"', 'health: "État du service"'));
JS
