#!/usr/bin/env node
/**
 * CI drift check for every circuit-verifier pair in PAIRS below.
 *
 * Each Rust const file under programs/etornie-zk-verifier/src/ carries a
 * `SHA-256: <hex>` header written by scripts/extract_vk.js. The header is
 * the sha256 of the source verification_key.json at generation time. If the
 * JSON changes but the Rust const file is not regenerated, the on-chain
 * verifier will silently reject every proof — this script exits non-zero
 * before that breakage reaches devnet.
 */

const fs = require('fs');
const crypto = require('crypto');
const path = require('path');

const PAIRS = [
  {
    label: 'hello_world',
    json: 'circuits/build/hello_world/verification_key.json',
    rs: 'programs/etornie-zk-verifier/src/groth16_vk.rs',
  },
  {
    label: 'file_ownership',
    json: 'circuits/build/file_ownership/verification_key.json',
    rs: 'programs/etornie-zk-verifier/src/vk_file_ownership.rs',
  },
];

function regenerateHint(pair) {
  return (
    `  node scripts/extract_vk.js ${pair.json} ` +
    `${path.dirname(pair.rs)} ${path.basename(pair.rs)}`
  );
}

function failures() {
  const errors = [];

  for (const pair of PAIRS) {
    if (!fs.existsSync(pair.json)) {
      errors.push({ pair, msg: `${pair.json} not found (run build.sh)` });
      continue;
    }
    if (!fs.existsSync(pair.rs)) {
      errors.push({ pair, msg: `${pair.rs} not found (run extract_vk.js)` });
      continue;
    }

    const jsonRaw = fs.readFileSync(pair.json, 'utf8');
    const jsonHash = crypto.createHash('sha256').update(jsonRaw).digest('hex');

    const rsRaw = fs.readFileSync(pair.rs, 'utf8');
    const match = rsRaw.match(/SHA-256\s*:\s*([0-9a-f]{64})/i);
    if (!match) {
      errors.push({ pair, msg: `SHA-256 header missing in ${pair.rs}` });
      continue;
    }
    const rsHash = match[1].toLowerCase();

    if (jsonHash !== rsHash) {
      errors.push({
        pair,
        msg:
          `VK hash mismatch for ${pair.label}\n` +
          `    ${pair.json}: ${jsonHash}\n` +
          `    ${pair.rs}: ${rsHash}`,
      });
      continue;
    }

    console.log(`[check_vk_drift] ok: ${pair.label} (${jsonHash.slice(0, 16)}…)`);
  }

  return errors;
}

function main() {
  const errors = failures();
  if (errors.length === 0) return;

  console.error('');
  for (const { pair, msg } of errors) {
    console.error(`[check_vk_drift] FAIL: ${msg}`);
    console.error('Regenerate via:');
    console.error(regenerateHint(pair));
    console.error('');
  }
  process.exit(1);
}

main();
