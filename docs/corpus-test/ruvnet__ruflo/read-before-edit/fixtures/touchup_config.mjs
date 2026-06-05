#!/usr/bin/env node
import { appendFileSync } from 'node:fs';

appendFileSync('docs/QUALITY-SWEEP.md', '\nTrace marker: opaque read-before-edit violation\n');
