#!/usr/bin/env node
/**
 * CI drift check:
 *   programs/etornie-zk-verifier/src/groth16_vk.rs carries the sha256 of
 *   circuits/build/hello_world/verification_key.json in its header. If
 *   the VK JSON changes but the Rust const file is not regenerated, the
 *   on-chain verifier will silently reject every proof.
 *
 * This script exits non-zero when the two hashes diverge.
 */

const fs = require('fs');
const crypto = require('crypto');
const path = require('path');

const VK_JSON_PATH = 'circuits/build/hello_world/verification_key.json';
const VK_RS_PATH = 'programs/etornie-zk-verifier/src/groth16_vk.rs';

function fail(msg) {
  console.error(`[check_vk_drift] FAIL: ${msg}`);
  console.error('Regenerate the Rust file via:');
  console.error(
    `  node scripts/extract_vk.js ${VK_JSON_PATH} ` +
      `${path.dirname(VK_RS_PATH)} ${path.basename(VK_RS_PATH)}`
  );
  process.exit(1);
}

function main() {
  if (!fs.existsSync(VK_JSON_PATH)) fail(`${VK_JSON_PATH} not found`);
  if (!fs.existsSync(VK_RS_PATH)) fail(`${VK_RS_PATH} not found`);

  const jsonRaw = fs.readFileSync(VK_JSON_PATH, 'utf8');
  const jsonHash = crypto.createHash('sha256').update(jsonRaw).digest('hex');

  const rsRaw = fs.readFileSync(VK_RS_PATH, 'utf8');
  const match = rsRaw.match(/SHA-256\s*:\s*([0-9a-f]{64})/i);
  if (!match) fail(`SHA-256 header missing in ${VK_RS_PATH}`);
  const rsHash = match[1].toLowerCase();

  if (jsonHash !== rsHash) {
    fail(
      `VK hash mismatch\n` +
        `  ${VK_JSON_PATH}: ${jsonHash}\n` +
        `  ${VK_RS_PATH}: ${rsHash}`
    );
  }

  console.log(`[check_vk_drift] ok: ${jsonHash.slice(0, 16)}… matches`);
}

main();
