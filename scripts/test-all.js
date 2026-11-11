#!/usr/bin/env node
'use strict';
// test-all — every notes-exporter test tier through the common ikt runner. The tiers live in
// ../ikt.project.js; the runner is @storizzi/ikt in the sibling repo apps/server/ikt
// (override with IKT_ROOT). Same as `ikt test notes-exporter`.
//
//   node scripts/test-all.js                 # everything available
//   node scripts/test-all.js unit service
//   node scripts/test-all.js --list

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const IKT = process.env.IKT_ROOT || path.resolve(ROOT, '..', 'ikt');
if (!fs.existsSync(path.join(IKT, 'runtime', 'tiers.js'))) {
  console.error(`✗ the shared ikt repo is not at ${IKT} — clone it there or set IKT_ROOT`);
  process.exit(1);
}
require(path.join(IKT, 'runtime', 'tiers.js')).main(ROOT);
