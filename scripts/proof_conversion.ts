/**
 * Convert a snarkjs Groth16 proof (BN254/BN128) into the byte layout the
 * on-chain verifier in programs/etornie-zk-verifier expects.
 *
 * The same utility is consumed by both the TS integration tests and the
 * browser-side ZK Lab "Submit on-chain" flow, so it has no Node-only deps.
 *
 * Byte layout (matches groth16-solana v0.2.0 `verify()` inputs):
 *   proofA : 64 B  = x_be || (-y)_be     (y is negated in BN254's prime field)
 *   proofB : 128 B = x.c1_be || x.c0_be || y.c1_be || y.c0_be
 *   proofC : 64 B  = x_be || y_be
 *   publicInputs[i] : 32 B big-endian, each < BN254_P
 *   journalDigest   : sha256(concat(publicInputs))  (seed for ProofRecord PDA)
 */

import { sha256 } from '@noble/hashes/sha2.js';

/** BN254 scalar field prime (curve order for the alt_bn128 pairing). */
export const BN254_P =
  BigInt(
    '21888242871839275222246405745257275088696311157297823662689037894645226208583'
  );

export const PUBLIC_INPUT_BYTES = 32;
export const G1_BYTES = 64;
export const G2_BYTES = 128;

export interface SnarkjsProof {
  pi_a: [string, string, string];
  pi_b: [[string, string], [string, string], [string, string]];
  pi_c: [string, string, string];
  protocol: string;
  curve: string;
}

export interface OnChainProof {
  proofA: Uint8Array;
  proofB: Uint8Array;
  proofC: Uint8Array;
  publicInputs: Uint8Array[];
  journalDigest: Uint8Array;
}

function bigIntToBEBytes32(x: bigint): Uint8Array {
  if (x < 0n) {
    throw new Error(`negative bigint not allowed: ${x}`);
  }
  const out = new Uint8Array(PUBLIC_INPUT_BYTES);
  let remaining = x;
  for (let i = PUBLIC_INPUT_BYTES - 1; i >= 0; i--) {
    out[i] = Number(remaining & 0xffn);
    remaining >>= 8n;
  }
  if (remaining !== 0n) {
    throw new Error('bigint does not fit in 32 bytes');
  }
  return out;
}

function beBytes32ToBigInt(bytes: Uint8Array): bigint {
  if (bytes.length !== PUBLIC_INPUT_BYTES) {
    throw new Error(`expected 32 bytes, got ${bytes.length}`);
  }
  let result = 0n;
  for (const b of bytes) {
    result = (result << 8n) | BigInt(b);
  }
  return result;
}

function g1ToBytes(x: bigint, y: bigint): Uint8Array {
  const out = new Uint8Array(G1_BYTES);
  out.set(bigIntToBEBytes32(x), 0);
  out.set(bigIntToBEBytes32(y), 32);
  return out;
}

/**
 * G2 encoding expected on-chain puts the c1 component first within each Fp2
 * coordinate — see groth16-solana's `parse_vk_to_rust.js` / crate source.
 */
function g2ToBytes(
  xc0: bigint,
  xc1: bigint,
  yc0: bigint,
  yc1: bigint
): Uint8Array {
  const out = new Uint8Array(G2_BYTES);
  out.set(bigIntToBEBytes32(xc1), 0);
  out.set(bigIntToBEBytes32(xc0), 32);
  out.set(bigIntToBEBytes32(yc1), 64);
  out.set(bigIntToBEBytes32(yc0), 96);
  return out;
}

/**
 * Negate a y coordinate inside the BN254 field. The groth16-solana verifier
 * folds the pairing check into a single `e(-A,B) * e(α,β) * e(prep,γ) * e(C,δ) = 1`
 * form, so the client must submit `-A` instead of `A`.
 */
export function negateY(y: bigint): bigint {
  if (y < 0n || y >= BN254_P) {
    throw new Error(`y coordinate outside BN254 field: ${y}`);
  }
  if (y === 0n) {
    return 0n;
  }
  return BN254_P - y;
}

/**
 * Produce the PDA seed / replay key for a set of public inputs.
 * The on-chain program recomputes the same digest and rejects the tx if it
 * does not match the seed supplied by the client, so do not tamper with it.
 */
export function computeJournalDigest(publicInputs: Uint8Array[]): Uint8Array {
  let total = 0;
  for (const inp of publicInputs) {
    if (inp.length !== PUBLIC_INPUT_BYTES) {
      throw new Error(`public input must be 32 bytes, got ${inp.length}`);
    }
    total += inp.length;
  }
  const concat = new Uint8Array(total);
  let offset = 0;
  for (const inp of publicInputs) {
    concat.set(inp, offset);
    offset += inp.length;
  }
  return sha256(concat);
}

export function convertSnarkjsProof(
  proof: SnarkjsProof,
  publicSignals: string[]
): OnChainProof {
  if (proof.protocol !== 'groth16') {
    throw new Error(`unsupported protocol: ${proof.protocol}`);
  }
  if (proof.curve !== 'bn128') {
    throw new Error(`unsupported curve: ${proof.curve}`);
  }
  // snarkjs emits projective coordinates normalised to affine (z=1 for G1,
  // [1,0] for G2). Anything else means the fixture is corrupt.
  if (proof.pi_a[2] !== '1' || proof.pi_c[2] !== '1') {
    throw new Error('G1 proof points not in affine form (z != 1)');
  }
  if (proof.pi_b[2][0] !== '1' || proof.pi_b[2][1] !== '0') {
    throw new Error('G2 proof point not in affine form');
  }

  const ax = BigInt(proof.pi_a[0]);
  const ay = BigInt(proof.pi_a[1]);
  const proofA = g1ToBytes(ax, negateY(ay));

  const bxc0 = BigInt(proof.pi_b[0][0]);
  const bxc1 = BigInt(proof.pi_b[0][1]);
  const byc0 = BigInt(proof.pi_b[1][0]);
  const byc1 = BigInt(proof.pi_b[1][1]);
  const proofB = g2ToBytes(bxc0, bxc1, byc0, byc1);

  const cx = BigInt(proof.pi_c[0]);
  const cy = BigInt(proof.pi_c[1]);
  const proofC = g1ToBytes(cx, cy);

  const publicInputs = publicSignals.map((s) => {
    const v = BigInt(s);
    if (v < 0n || v >= BN254_P) {
      throw new Error(`public input ${s} outside BN254 field size`);
    }
    return bigIntToBEBytes32(v);
  });

  const journalDigest = computeJournalDigest(publicInputs);

  return { proofA, proofB, proofC, publicInputs, journalDigest };
}

/** Exposed for tests that need to round-trip bytes to BigInt. */
export const __testing = {
  bigIntToBEBytes32,
  beBytes32ToBigInt,
};
