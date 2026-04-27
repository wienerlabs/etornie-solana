import {
  ComputeBudgetProgram,
  PublicKey,
  SystemProgram,
  TransactionInstruction,
  TransactionMessage,
  VersionedTransaction,
  type AccountMeta,
} from "@solana/web3.js";
import api from "@/lib/api";
import {
  computeCommitment,
  deriveDeterministicSecret,
  generateFileOwnershipProof,
  splitFileHash,
  type WalletWithSignMessage,
} from "@/lib/zk/fileOwnership";

interface FileOwnershipPrepareResponse {
  program_id: string;
  fee_payer: string;
  user: string;
  file_ownership_record: string;
  ix_data_b64: string;
  recent_blockhash: string;
}

interface FileOwnershipSubmitResponse {
  signature: string;
  explorer_url: string;
  already_recorded?: boolean;
}

/**
 * The connected-wallet surface this flow needs. Matches what the
 * wallet-adapter exposes for Phantom/Solflare — ``signMessage`` to derive
 * the deterministic secret, ``signTransaction`` to sign the verify tx.
 */
export interface FileOwnershipWallet extends WalletWithSignMessage {
  signTransaction: (tx: VersionedTransaction) => Promise<VersionedTransaction>;
}

export interface FileOwnershipSubmitResult {
  signature: string;
  proofPda: string;
  explorerTxUrl: string;
  explorerPdaUrl: string;
  alreadyRecorded: boolean;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function base64ToBytes(b64: string): Uint8Array {
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) {
    out[i] = raw.charCodeAt(i);
  }
  return out;
}

function hexToBytes(hex: string): Uint8Array {
  const clean = hex.startsWith("0x") ? hex.slice(2) : hex;
  if (clean.length % 2 !== 0) {
    throw new Error(`hex string has odd length: ${clean.length}`);
  }
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i += 1) {
    const byte = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
    if (Number.isNaN(byte)) throw new Error(`invalid hex at offset ${i * 2}`);
    out[i] = byte;
  }
  return out;
}

function bigintToHex32(x: bigint): string {
  const hex = x.toString(16);
  if (hex.length > 64) {
    throw new Error(`bigint does not fit in 32 bytes: ${x}`);
  }
  return hex.padStart(64, "0");
}

/**
 * End-to-end "Prove ownership" flow for a previously-uploaded document.
 *
 *   1. Re-derive the secret deterministically from the user's wallet +
 *      the stored file_hash (no file upload needed at prove time).
 *   2. Recompute commitment; if it disagrees with the one stored at
 *      upload, bail — the current wallet isn't the uploader.
 *   3. Produce a Groth16 proof via snarkjs in the browser.
 *   4. Call ``/zk/file-ownership/prepare`` for ix_data + blockhash.
 *   5. Compose a v0 VersionedTransaction (fee_payer + user + PDA + system),
 *      have Phantom sign slot 1, ship the signed bytes.
 *   6. ``/zk/file-ownership/submit`` splices the backend operator signature
 *      and sends the tx to devnet.
 *
 * On success the caller is expected to ``POST /documents/{id}/attach-ownership-proof``
 * with the returned ``proofPda`` so the DB row gets the badge update.
 */
export async function proveDocumentOwnershipOnChain(
  opts: {
    fileHashHex: string;
    expectedCommitmentHex: string;
    wallet: FileOwnershipWallet;
    computeUnitLimit?: number;
  },
): Promise<FileOwnershipSubmitResult> {
  const { fileHashHex, expectedCommitmentHex, wallet } = opts;

  if (!wallet.publicKey) {
    throw new Error("Wallet is not connected.");
  }
  if (typeof wallet.signMessage !== "function") {
    throw new Error("Wallet does not expose signMessage (Phantom/Solflare required).");
  }
  if (typeof wallet.signTransaction !== "function") {
    throw new Error("Wallet does not expose signTransaction.");
  }

  // 1. Rehydrate (file_hash, fh_hi, fh_lo) from DB hex.
  const fileHash = hexToBytes(fileHashHex);
  if (fileHash.length !== 32) {
    throw new Error(`file_hash_hex must decode to 32 bytes (got ${fileHash.length})`);
  }
  const { fhHi, fhLo } = splitFileHash(fileHash);

  // 2. Deterministically regenerate the secret and reconcile commitment.
  const secret = await deriveDeterministicSecret(wallet, fileHash);
  const commitment = await computeCommitment(secret, fhHi, fhLo);
  const commitmentHex = bigintToHex32(commitment);
  if (commitmentHex.toLowerCase() !== expectedCommitmentHex.toLowerCase()) {
    throw new Error(
      "Commitment mismatch — this wallet did not register this document's ownership claim.",
    );
  }

  // 3. Browser-side Groth16 proof.
  const proofBundle = await generateFileOwnershipProof({
    fileHash,
    fhHi,
    fhLo,
    secret,
    commitment,
  });

  // 4. Backend prepares the sponsored verify tx payload.
  const { data: prep } = await api.post<FileOwnershipPrepareResponse>(
    "/zk/file-ownership/prepare",
    {
      user_wallet: wallet.publicKey.toBase58(),
      proof_a_b64: bytesToBase64(proofBundle.onchain.proofA),
      proof_b_b64: bytesToBase64(proofBundle.onchain.proofB),
      proof_c_b64: bytesToBase64(proofBundle.onchain.proofC),
      public_inputs_b64: proofBundle.onchain.publicInputs.map(bytesToBase64),
      file_hash_b64: bytesToBase64(fileHash),
    },
  );

  const feePayer = new PublicKey(prep.fee_payer);
  const user = new PublicKey(prep.user);
  const proofPda = new PublicKey(prep.file_ownership_record);
  const programId = new PublicKey(prep.program_id);

  if (user.toBase58() !== wallet.publicKey.toBase58()) {
    throw new Error(
      "Backend returned a user pubkey that does not match the connected wallet.",
    );
  }

  // 5. Compose the VersionedTransaction locally — account layout matches
  //    VerifyFileOwnership<'info> in programs/etornie-zk-verifier/src/lib.rs.
  const keys: AccountMeta[] = [
    { pubkey: feePayer, isSigner: true, isWritable: true },
    { pubkey: user, isSigner: true, isWritable: false },
    { pubkey: proofPda, isSigner: false, isWritable: true },
    { pubkey: SystemProgram.programId, isSigner: false, isWritable: false },
  ];

  const verifyIx = new TransactionInstruction({
    programId,
    keys,
    data: Buffer.from(base64ToBytes(prep.ix_data_b64)),
  });

  const computeIx = ComputeBudgetProgram.setComputeUnitLimit({
    units: opts.computeUnitLimit ?? 300_000,
  });

  const msg = new TransactionMessage({
    payerKey: feePayer,
    recentBlockhash: prep.recent_blockhash,
    instructions: [computeIx, verifyIx],
  }).compileToV0Message();

  const tx = new VersionedTransaction(msg);
  const signedTx = await wallet.signTransaction(tx);

  // 6. Backend adds the operator sig and submits.
  const signedB64 = bytesToBase64(signedTx.serialize());
  const { data: submitRes } = await api.post<FileOwnershipSubmitResponse>(
    "/zk/file-ownership/submit",
    { signed_tx_b64: signedB64 },
  );

  const cluster = "devnet";
  const alreadyRecorded = submitRes.already_recorded === true;
  return {
    signature: submitRes.signature,
    proofPda: proofPda.toBase58(),
    explorerTxUrl: alreadyRecorded
      ? ""
      : `https://solscan.io/tx/${submitRes.signature}?cluster=${cluster}`,
    explorerPdaUrl: `https://solscan.io/account/${proofPda.toBase58()}?cluster=${cluster}`,
    alreadyRecorded,
  };
}
