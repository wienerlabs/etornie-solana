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
import { env } from "@/lib/env";
import {
  convertSnarkjsProof,
  type SnarkjsProof,
} from "@/lib/zk/proofConversion";

interface VerifyPrepareResponse {
  program_id: string;
  fee_payer: string;
  user: string;
  proof_record: string;
  ix_data_b64: string;
  recent_blockhash: string;
}

interface VerifySubmitResponse {
  signature: string;
  explorer_url: string;
  already_recorded?: boolean;
}

interface WalletLike {
  publicKey: PublicKey | null;
  signTransaction?: (tx: VersionedTransaction) => Promise<VersionedTransaction>;
}

export interface SubmitResult {
  signature: string;
  proofRecord: string;
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

/**
 * Prepare → sign with Phantom → submit the sponsored verify_proof tx.
 *
 * The backend returns the ix_data the on-chain program expects plus the
 * accounts metadata. We compose a v0 VersionedTransaction locally, have
 * the wallet sign as the `user` slot, then hand the serialised tx back
 * so the backend can splice its operator signature into the fee_payer
 * slot and submit.
 */
export async function submitProofOnChain(
  proof: SnarkjsProof,
  publicSignals: string[],
  wallet: WalletLike,
  opts: { computeUnitLimit?: number } = {},
): Promise<SubmitResult> {
  if (!wallet.publicKey || !wallet.signTransaction) {
    throw new Error(
      "Wallet is not connected or does not support signTransaction.",
    );
  }

  const converted = convertSnarkjsProof(proof, publicSignals);

  const { data: prep } = await api.post<VerifyPrepareResponse>(
    "/zk/verify-prepare",
    {
      user_wallet: wallet.publicKey.toBase58(),
      proof_a_b64: bytesToBase64(converted.proofA),
      proof_b_b64: bytesToBase64(converted.proofB),
      proof_c_b64: bytesToBase64(converted.proofC),
      public_inputs_b64: converted.publicInputs.map(bytesToBase64),
      journal_digest_b64: bytesToBase64(converted.journalDigest),
    },
  );

  const feePayer = new PublicKey(prep.fee_payer);
  const user = new PublicKey(prep.user);
  const proofRecord = new PublicKey(prep.proof_record);
  const programId = new PublicKey(prep.program_id);

  if (user.toBase58() !== wallet.publicKey.toBase58()) {
    throw new Error(
      "Backend returned a user pubkey that does not match the connected wallet.",
    );
  }

  const keys: AccountMeta[] = [
    { pubkey: feePayer, isSigner: true, isWritable: true },
    { pubkey: user, isSigner: true, isWritable: false },
    { pubkey: proofRecord, isSigner: false, isWritable: true },
    { pubkey: SystemProgram.programId, isSigner: false, isWritable: false },
  ];

  const verifyIx = new TransactionInstruction({
    programId,
    keys,
    data: Buffer.from(base64ToBytes(prep.ix_data_b64)),
  });

  const computeIx = ComputeBudgetProgram.setComputeUnitLimit({
    units: opts.computeUnitLimit ?? 180_000,
  });

  const msg = new TransactionMessage({
    payerKey: feePayer,
    recentBlockhash: prep.recent_blockhash,
    instructions: [computeIx, verifyIx],
  }).compileToV0Message();

  const tx = new VersionedTransaction(msg);
  const signedTx = await wallet.signTransaction(tx);

  const signedB64 = bytesToBase64(signedTx.serialize());
  const { data: submitRes } = await api.post<VerifySubmitResponse>(
    "/zk/verify-submit",
    { signed_tx_b64: signedB64 },
  );

  const alreadyRecorded = submitRes.already_recorded === true;
  return {
    signature: submitRes.signature,
    proofRecord: proofRecord.toBase58(),
    explorerTxUrl: alreadyRecorded
      ? ""
      : `https://explorer.solana.com/tx/${submitRes.signature}${env.explorerClusterSuffix}`,
    explorerPdaUrl: `https://explorer.solana.com/address/${proofRecord.toBase58()}${env.explorerClusterSuffix}`,
    alreadyRecorded,
  };
}
