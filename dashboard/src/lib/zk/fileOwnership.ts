/**
 * Browser-side helpers for the file_ownership circuit.
 *
 * Pipeline (all in the user's tab — the file never leaves the browser):
 *   1. sha256File(file)                       -> 32-byte file_hash
 *   2. splitFileHash(file_hash)               -> (fh_hi, fh_lo)   (128-bit halves)
 *   3. deriveDeterministicSecret(wallet, fh)  -> secret            (<BN254_P)
 *   4. computeCommitment(secret, fh_hi, fh_lo)-> Poseidon commitment
 *   5. generateFileOwnershipProof(input)      -> Groth16 proof + public signals
 *
 * The heavy deps (circomlibjs, snarkjs) are loaded via dynamic import so
 * they land in a separate chunk — the rest of the dashboard does not pay
 * for them unless a user actually runs the ownership flow.
 */

import type { PublicKey } from "@solana/web3.js";
import {
  BN254_P,
  convertSnarkjsProof,
  type OnChainProof,
  type SnarkjsProof,
} from "@/lib/zk/proofConversion";

/**
 * The subset of a Solana wallet this module needs. Matches the shape that
 * Phantom (and the wallet-adapter wrappers over it) exposes — the caller
 * is expected to have already connected the wallet.
 */
export interface WalletWithSignMessage {
  publicKey: PublicKey;
  signMessage: (message: Uint8Array) => Promise<Uint8Array>;
}

/** Namespace prefix included in the signMessage payload. Bumping this
 *  invalidates every previously derived secret — use for circuit/schema
 *  breaking changes, not for unrelated releases. */
export const DOMAIN_SEPARATOR = "etornie-file-ownership-v1";

export interface FileOwnershipInput {
  fileHash: Uint8Array;
  fhHi: bigint;
  fhLo: bigint;
  secret: bigint;
  commitment: bigint;
}

export interface FileOwnershipProof {
  /** Raw snarkjs Groth16 proof. */
  snarkjsProof: SnarkjsProof;
  /** Raw snarkjs public signals (decimal strings, in declaration order:
   *  fh_hi, fh_lo, commitment). */
  publicSignals: string[];
  /** The same proof reshaped for the on-chain verifier — byte layout that
   *  groth16-solana v0.2.0 expects. `journalDigest` is populated but NOT
   *  used by verify_file_ownership_proof (it has no digest arg) — kept
   *  only because OnChainProof always carries it. */
  onchain: OnChainProof;
}

/** Streaming-safe sha256 of the file's raw bytes using Web Crypto. */
export async function sha256File(file: File): Promise<Uint8Array> {
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return new Uint8Array(digest);
}

/** Split a 32-byte sha256 into two 128-bit BigInts (BE interpretation). */
export function splitFileHash(fileHash: Uint8Array): {
  fhHi: bigint;
  fhLo: bigint;
} {
  if (fileHash.length !== 32) {
    throw new Error(`file_hash must be 32 bytes, got ${fileHash.length}`);
  }
  let hi = 0n;
  let lo = 0n;
  for (let i = 0; i < 16; i++) hi = (hi << 8n) | BigInt(fileHash[i]);
  for (let i = 16; i < 32; i++) lo = (lo << 8n) | BigInt(fileHash[i]);
  return { fhHi: hi, fhLo: lo };
}

function toHex(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += b.toString(16).padStart(2, "0");
  return s;
}

/**
 * Derive a deterministic 248-bit secret from (wallet, file_hash):
 *
 *   payload    = `${DOMAIN_SEPARATOR}:${walletPubkey}:${fileHashHex}`
 *   signature  = wallet.signMessage(utf8(payload))   // ed25519, deterministic
 *   seed       = sha256(signature)
 *   secret     = seed & ((1 << 252) - 1) || 1        // always < BN254_P, != 0
 *
 * Why ed25519 determinism matters: we need the same (wallet, file) pair to
 * always regenerate the same secret so the user can re-prove ownership
 * after device/session loss as long as the wallet seed survives. Phantom
 * signMessage uses the underlying nacl.sign which is RFC 8032 compliant
 * and deterministic — this property is asserted at the UI layer before
 * the first real claim in Mikro-Adım 8.
 */
export async function deriveDeterministicSecret(
  wallet: WalletWithSignMessage,
  fileHash: Uint8Array,
): Promise<bigint> {
  const payload = `${DOMAIN_SEPARATOR}:${wallet.publicKey.toBase58()}:${toHex(fileHash)}`;
  const signature = await wallet.signMessage(new TextEncoder().encode(payload));
  if (signature.length !== 64) {
    throw new Error(
      `unexpected signMessage length: ${signature.length} (wallet may not be ed25519)`,
    );
  }

  // Copy into an ArrayBuffer-backed Uint8Array: Phantom's signMessage may
  // return a Uint8Array whose underlying buffer is typed as
  // ArrayBufferLike, which TS 5 no longer accepts as BufferSource directly.
  const signatureCopy = new Uint8Array(signature.byteLength);
  signatureCopy.set(signature);
  const digest = await crypto.subtle.digest("SHA-256", signatureCopy);
  const digestBytes = new Uint8Array(digest);
  let secret = 0n;
  for (const b of digestBytes) secret = (secret << 8n) | BigInt(b);
  // Truncate to 252 bits — unambiguously < BN254_P (~2^254), uniform, never 0.
  secret &= (1n << 252n) - 1n;
  return secret === 0n ? 1n : secret;
}

/**
 * Compute commitment = Poseidon(secret, fh_hi, fh_lo) using the same
 * parameters as the circuit (circomlib BN254 Poseidon). The call is
 * lazy-imported to keep circomlibjs out of the main bundle.
 */
export async function computeCommitment(
  secret: bigint,
  fhHi: bigint,
  fhLo: bigint,
): Promise<bigint> {
  const { buildPoseidon } = await import("circomlibjs");
  const poseidon = await buildPoseidon();
  const out = poseidon([secret, fhHi, fhLo]);
  return poseidon.F.toObject(out) as bigint;
}

/**
 * One-shot helper: takes a File + connected wallet, runs the full
 * pre-proof derivation, and returns everything the commit step needs.
 * Throws if the file sha256 is not 32 bytes (can't happen in practice) or
 * if the wallet signs with something other than ed25519.
 */
export async function prepareFileOwnershipInput(
  file: File,
  wallet: WalletWithSignMessage,
): Promise<FileOwnershipInput> {
  const fileHash = await sha256File(file);
  const { fhHi, fhLo } = splitFileHash(fileHash);
  const secret = await deriveDeterministicSecret(wallet, fileHash);
  if (secret >= BN254_P) {
    // Defensive — truncation above guarantees this is unreachable.
    throw new Error("derived secret escaped the BN254 scalar field");
  }
  const commitment = await computeCommitment(secret, fhHi, fhLo);
  return { fileHash, fhHi, fhLo, secret, commitment };
}

/** Produce a Groth16 proof in the browser via snarkjs fullProve.
 *  `wasmUrl` / `zkeyUrl` default to the assets copied under
 *  dashboard/public/zk/file_ownership/ by the circuit build step. */
export async function generateFileOwnershipProof(
  input: FileOwnershipInput,
  {
    wasmUrl = "/zk/file_ownership/file_ownership.wasm",
    zkeyUrl = "/zk/file_ownership/file_ownership_final.zkey",
  }: { wasmUrl?: string; zkeyUrl?: string } = {},
): Promise<FileOwnershipProof> {
  const snarkjs = await import("snarkjs");

  const { proof, publicSignals } = await snarkjs.groth16.fullProve(
    {
      secret: input.secret.toString(),
      file_hash_hi: input.fhHi.toString(),
      file_hash_lo: input.fhLo.toString(),
      commitment: input.commitment.toString(),
    },
    wasmUrl,
    zkeyUrl,
  );

  const onchain = convertSnarkjsProof(proof as SnarkjsProof, publicSignals);
  return { snarkjsProof: proof as SnarkjsProof, publicSignals, onchain };
}
