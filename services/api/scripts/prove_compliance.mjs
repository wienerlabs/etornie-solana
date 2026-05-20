#!/usr/bin/env node
/**
 * Server-side Groth16 prover for the compliance circuit.
 *
 * Reads input JSON from a file path passed as argv[2], writes the
 * resulting proof JSON to argv[3]. We avoid stdin/stdout pipes
 * entirely so the Python subprocess wrapper does not race against
 * pipe-buffer / EOF semantics — which the previous stdin-driven
 * shape did, intermittently hanging at 0% CPU.
 *
 * Invocation:
 *   node prove_compliance.mjs <input.json> <output.json>
 *
 * Input  JSON: { "secret_dec": "<dec>", "query_hash_hex": "<64 hex chars>" }
 * Output JSON: {
 *   commitment_dec, qh_hi_dec, qh_lo_dec, proof, publicSignals,
 *   onchain: { proof_a_b64, proof_b_b64, proof_c_b64,
 *              public_inputs_b64[3], journal_digest_b64 }
 * }
 *
 * Errors → stderr + non-zero exit, never partial writes to the
 * output file.
 */

import { readFileSync, writeFileSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..", "..", "..");
const WASM_PATH = resolve(
  REPO_ROOT,
  "circuits/build/compliance/compliance_js/compliance.wasm",
);
const ZKEY_PATH = resolve(
  REPO_ROOT,
  "circuits/build/compliance/compliance_final.zkey",
);

const { buildPoseidon } = await import(
  resolve(REPO_ROOT, "dashboard/node_modules/circomlibjs/main.js")
);
const snarkjs = await import(
  resolve(REPO_ROOT, "dashboard/node_modules/snarkjs/main.js")
);

function die(msg, code = 1) {
  process.stderr.write(`${msg}\n`);
  process.exit(code);
}

function hexToBytes(hex) {
  if (hex.length % 2 !== 0) throw new Error("hex length must be even");
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(hex.substr(i * 2, 2), 16);
  }
  return out;
}

function splitQueryHash(qh) {
  if (qh.length !== 32) {
    throw new Error(`query_hash must be 32 bytes, got ${qh.length}`);
  }
  let hi = 0n;
  let lo = 0n;
  for (let i = 0; i < 16; i++) hi = (hi << 8n) | BigInt(qh[i]);
  for (let i = 16; i < 32; i++) lo = (lo << 8n) | BigInt(qh[i]);
  return { hi, lo };
}

function bigintToBE32(x) {
  if (x < 0n) throw new Error("negative bigint");
  const out = new Uint8Array(32);
  let v = x;
  for (let i = 31; i >= 0; i--) {
    out[i] = Number(v & 0xffn);
    v >>= 8n;
  }
  if (v !== 0n) throw new Error("bigint does not fit in 32 bytes");
  return out;
}

const toB64 = (bytes) => Buffer.from(bytes).toString("base64");

// BN254 scalar field — must match lib/zk/proofConversion.ts. Used to
// negate proof_a's y coordinate, which is the pairing-equation
// convention the on-chain verifier expects.
const BN254_P =
  21888242871839275222246405745257275088696311157297823662689037894645226208583n;

function negateY(y) {
  if (y < 0n || y >= BN254_P) {
    throw new Error(`y coordinate outside BN254 field: ${y}`);
  }
  return y === 0n ? 0n : BN254_P - y;
}

function snarkjsProofToOnchain(proof, publicSignals) {
  const aBytes = new Uint8Array(64);
  // negate y of A so the on-chain pairing equation balances.
  // Mirrors dashboard/src/lib/zk/proofConversion.ts convertSnarkjsProof.
  aBytes.set(bigintToBE32(BigInt(proof.pi_a[0])), 0);
  aBytes.set(bigintToBE32(negateY(BigInt(proof.pi_a[1]))), 32);

  const bBytes = new Uint8Array(128);
  bBytes.set(bigintToBE32(BigInt(proof.pi_b[0][1])), 0);
  bBytes.set(bigintToBE32(BigInt(proof.pi_b[0][0])), 32);
  bBytes.set(bigintToBE32(BigInt(proof.pi_b[1][1])), 64);
  bBytes.set(bigintToBE32(BigInt(proof.pi_b[1][0])), 96);

  const cBytes = new Uint8Array(64);
  cBytes.set(bigintToBE32(BigInt(proof.pi_c[0])), 0);
  cBytes.set(bigintToBE32(BigInt(proof.pi_c[1])), 32);

  const publicInputsB64 = publicSignals.map((s) =>
    toB64(bigintToBE32(BigInt(s))),
  );

  const journalInput = Buffer.concat(
    publicSignals.map((s) => Buffer.from(bigintToBE32(BigInt(s)))),
  );
  const journalDigest = createHash("sha256").update(journalInput).digest();

  return {
    proof_a_b64: toB64(aBytes),
    proof_b_b64: toB64(bBytes),
    proof_c_b64: toB64(cBytes),
    public_inputs_b64: publicInputsB64,
    journal_digest_b64: toB64(journalDigest),
  };
}

async function main() {
  const inputPath = process.argv[2];
  const outputPath = process.argv[3];
  if (!inputPath || !outputPath) {
    die("usage: prove_compliance.mjs <input.json> <output.json>", 2);
  }
  try {
    statSync(inputPath);
  } catch {
    die(`input file not found: ${inputPath}`, 2);
  }

  let raw;
  try {
    raw = readFileSync(inputPath, "utf8");
  } catch (err) {
    die(`failed to read ${inputPath}: ${err.message}`, 2);
  }
  if (!raw.trim()) die(`empty input file: ${inputPath}`, 2);

  const input = JSON.parse(raw);
  if (!input.secret_dec || !input.query_hash_hex) {
    die("missing fields — required: secret_dec, query_hash_hex", 2);
  }

  const queryHash = hexToBytes(input.query_hash_hex);
  const { hi, lo } = splitQueryHash(queryHash);
  const secret = BigInt(input.secret_dec);

  const poseidon = await buildPoseidon();
  const commitmentField = poseidon([secret, hi, lo]);
  const commitment = poseidon.F.toObject(commitmentField);

  const { proof, publicSignals } = await snarkjs.groth16.fullProve(
    {
      secret: secret.toString(),
      query_hash_hi: hi.toString(),
      query_hash_lo: lo.toString(),
      commitment: commitment.toString(),
    },
    WASM_PATH,
    ZKEY_PATH,
  );

  const onchain = snarkjsProofToOnchain(proof, publicSignals);

  writeFileSync(
    outputPath,
    JSON.stringify({
      commitment_dec: commitment.toString(),
      qh_hi_dec: hi.toString(),
      qh_lo_dec: lo.toString(),
      proof,
      publicSignals,
      onchain,
    }),
    "utf8",
  );

  // Force a clean exit so any lingering worker pool from snarkjs
  // does not keep the event loop alive.
  process.exit(0);
}

main().catch((err) => {
  die(`prove_compliance failed: ${err.stack || err}`);
});
