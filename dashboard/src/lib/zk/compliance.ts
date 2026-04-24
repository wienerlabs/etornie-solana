/**
 * Browser-side helpers for the compliance circuit (Faz 5.6 - x402).
 *
 * Mirrors the file_ownership pipeline but for AI queries:
 *   1. sha256Query(question)                  -> 32-byte query_hash
 *   2. splitQueryHash(query_hash)             -> (qh_hi, qh_lo)
 *   3. deriveDeterministicSecret(wallet, qh)  -> secret (<BN254_P)
 *   4. computeCommitment(secret, qh_hi, qh_lo)-> Poseidon commitment
 *   5. generateComplianceProof(input)         -> Groth16 proof + public signals
 *
 * The secret is deterministic in (wallet, query_hash) so the same wallet
 * asking the same question always produces the same commitment and
 * therefore the same ComplianceRecord PDA - anti-replay is natural.
 */

import type { PublicKey } from "@solana/web3.js";
import {
  BN254_P,
  convertSnarkjsProof,
  type OnChainProof,
  type SnarkjsProof,
} from "@/lib/zk/proofConversion";

export interface WalletWithSignMessage {
  publicKey: PublicKey;
  signMessage: (message: Uint8Array) => Promise<Uint8Array>;
}

/** Namespace for the signMessage payload - bumping invalidates every
 *  previously-derived secret. Keep stable across dashboard releases. */
export const COMPLIANCE_DOMAIN_SEPARATOR = "etornie-compliance-v1";

export interface ComplianceInput {
  queryHash: Uint8Array;
  qhHi: bigint;
  qhLo: bigint;
  secret: bigint;
  commitment: bigint;
}

export interface ComplianceProofBundle {
  snarkjsProof: SnarkjsProof;
  publicSignals: string[];
  onchain: OnChainProof;
}

/** Canonical sha256 of the UTF-8 encoded query text. */
export async function sha256Query(question: string): Promise<Uint8Array> {
  const bytes = new TextEncoder().encode(question);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return new Uint8Array(digest);
}

/** Split a 32-byte sha256 into two 128-bit BigInts (BE interpretation). */
export function splitQueryHash(queryHash: Uint8Array): {
  qhHi: bigint;
  qhLo: bigint;
} {
  if (queryHash.length !== 32) {
    throw new Error(`query_hash must be 32 bytes, got ${queryHash.length}`);
  }
  let hi = 0n;
  let lo = 0n;
  for (let i = 0; i < 16; i++) hi = (hi << 8n) | BigInt(queryHash[i]);
  for (let i = 16; i < 32; i++) lo = (lo << 8n) | BigInt(queryHash[i]);
  return { qhHi: hi, qhLo: lo };
}

function toHex(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += b.toString(16).padStart(2, "0");
  return s;
}

/**
 * Derive a deterministic 248-bit secret from (wallet, query_hash):
 *
 *   payload    = `${DOMAIN}:${walletPubkey}:${queryHashHex}`
 *   signature  = wallet.signMessage(utf8(payload))    // ed25519, deterministic
 *   seed       = sha256(signature)
 *   secret     = seed & ((1 << 252) - 1) || 1         // always < BN254_P, != 0
 *
 * Triggers a single Phantom popup per unique query. Same popup for the
 * same (wallet, question) pair, so reattempting a query is silent.
 */
export async function deriveDeterministicSecret(
  wallet: WalletWithSignMessage,
  queryHash: Uint8Array,
): Promise<bigint> {
  const payload = `${COMPLIANCE_DOMAIN_SEPARATOR}:${wallet.publicKey.toBase58()}:${toHex(queryHash)}`;
  const signature = await wallet.signMessage(
    new TextEncoder().encode(payload),
  );
  if (signature.length !== 64) {
    throw new Error(
      `unexpected signMessage length: ${signature.length} (wallet may not be ed25519)`,
    );
  }
  const signatureCopy = new Uint8Array(signature.byteLength);
  signatureCopy.set(signature);
  const digest = await crypto.subtle.digest("SHA-256", signatureCopy);
  const digestBytes = new Uint8Array(digest);
  let secret = 0n;
  for (const b of digestBytes) secret = (secret << 8n) | BigInt(b);
  secret &= (1n << 252n) - 1n;
  return secret === 0n ? 1n : secret;
}

/** Compute commitment = Poseidon(secret, qh_hi, qh_lo). */
export async function computeCommitment(
  secret: bigint,
  qhHi: bigint,
  qhLo: bigint,
): Promise<bigint> {
  const { buildPoseidon } = await import("circomlibjs");
  const poseidon = await buildPoseidon();
  const out = poseidon([secret, qhHi, qhLo]);
  return poseidon.F.toObject(out) as bigint;
}

/** Full pre-proof derivation for a query. */
export async function prepareComplianceInput(
  question: string,
  wallet: WalletWithSignMessage,
): Promise<ComplianceInput> {
  const queryHash = await sha256Query(question);
  const { qhHi, qhLo } = splitQueryHash(queryHash);
  const secret = await deriveDeterministicSecret(wallet, queryHash);
  if (secret >= BN254_P) {
    throw new Error("derived secret escaped the BN254 scalar field");
  }
  const commitment = await computeCommitment(secret, qhHi, qhLo);
  return { queryHash, qhHi, qhLo, secret, commitment };
}

/** Produce a Groth16 proof in the browser via snarkjs fullProve. */
export async function generateComplianceProof(
  input: ComplianceInput,
  {
    wasmUrl = "/zk/compliance/compliance.wasm",
    zkeyUrl = "/zk/compliance/compliance_final.zkey",
  }: { wasmUrl?: string; zkeyUrl?: string } = {},
): Promise<ComplianceProofBundle> {
  const snarkjs = await import("snarkjs");

  const { proof, publicSignals } = await snarkjs.groth16.fullProve(
    {
      secret: input.secret.toString(),
      query_hash_hi: input.qhHi.toString(),
      query_hash_lo: input.qhLo.toString(),
      commitment: input.commitment.toString(),
    },
    wasmUrl,
    zkeyUrl,
  );

  const onchain = convertSnarkjsProof(proof as SnarkjsProof, publicSignals);
  return { snarkjsProof: proof as SnarkjsProof, publicSignals, onchain };
}

/** Serialize a 32-byte BE field element from a bigint. */
export function bigintToBE32(x: bigint): Uint8Array {
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
