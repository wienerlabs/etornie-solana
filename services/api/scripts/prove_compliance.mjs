#!/usr/bin/env node
/**
 * Server-side Groth16 prover for the compliance circuit.
 *
 * Called from Python (app/compliance/service.py) as a subprocess so
 * the backend can produce on-chain-verifiable compliance proofs for
 * Stripe-paid filings — the x402 path runs this same computation in
 * the browser using the user's wallet secret, but Stripe customers
 * have no wallet to sign with, so the operator derives the secret
 * deterministically and ships the proof through this script.
 *
 * Input  (stdin, JSON line):
 *   { "secret_dec": "...", "query_hash_hex": "<64 hex chars>" }
 *
 * Output (stdout, JSON line):
 *   {
 *     "commitment_dec": "...",
 *     "qh_hi_dec": "...",
 *     "qh_lo_dec": "...",
 *     "proof": { ... raw snarkjs ... },
 *     "publicSignals": ["qh_hi", "qh_lo", "commitment"],
 *     "onchain": {
 *       "proof_a_b64": "<64 bytes>",
 *       "proof_b_b64": "<128 bytes>",
 *       "proof_c_b64": "<64 bytes>",
 *       "public_inputs_b64": ["<32>", "<32>", "<32>"],
 *       "journal_digest_b64": "<32>"
 *     }
 *   }
 *
 * Errors → stderr + non-zero exit. Stdout stays a single JSON line.
 */

import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
// services/api/scripts/prove_compliance.mjs → repo root = ../../..
const REPO_ROOT = resolve(HERE, "..", "..", "..");
const WASM_PATH = resolve(
  REPO_ROOT,
  "circuits/build/compliance/compliance_js/compliance.wasm",
);
const ZKEY_PATH = resolve(
  REPO_ROOT,
  "circuits/build/compliance/compliance_final.zkey",
);

// snarkjs and circomlibjs are installed under dashboard/node_modules
// (the frontend ZK pipeline already depends on them). Importing via
// absolute file URL bypasses Node's package resolution entirely.
const { buildPoseidon } = await import(
  resolve(REPO_ROOT, "dashboard/node_modules/circomlibjs/main.js")
);
const snarkjs = await import(
  resolve(REPO_ROOT, "dashboard/node_modules/snarkjs/main.js")
);

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
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

function snarkjsProofToOnchain(proof, publicSignals) {
  // Mirrors dashboard/src/lib/zk/proofConversion.ts:
  //   proof_a: 64 bytes  (x || y)
  //   proof_b: 128 bytes (x_c1 || x_c0 || y_c1 || y_c0)  — note c1 first
  //   proof_c: 64 bytes  (x || y)
  //   public_inputs: each 32 bytes BE
  //   journal_digest: sha256(concat(public_inputs))
  const aBytes = new Uint8Array(64);
  aBytes.set(bigintToBE32(BigInt(proof.pi_a[0])), 0);
  aBytes.set(bigintToBE32(BigInt(proof.pi_a[1])), 32);

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
  const raw = await readStdin();
  if (!raw.trim()) {
    process.stderr.write("empty stdin\n");
    process.exit(2);
  }
  const input = JSON.parse(raw);
  if (!input.secret_dec || !input.query_hash_hex) {
    process.stderr.write(
      "missing fields — required: secret_dec, query_hash_hex\n",
    );
    process.exit(2);
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

  process.stdout.write(
    JSON.stringify({
      commitment_dec: commitment.toString(),
      qh_hi_dec: hi.toString(),
      qh_lo_dec: lo.toString(),
      proof,
      publicSignals,
      onchain,
    }) + "\n",
  );
}

main().catch((err) => {
  process.stderr.write(`prove_compliance failed: ${err.stack || err}\n`);
  process.exit(1);
});
