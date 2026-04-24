/**
 * x402 client for the EtornieGPT payment-gated chat flow (Faz 5.6).
 *
 * Per-query handshake:
 *   1. GET  /etorniegpt/chat/payment-requirements      (once per session)
 *   2. Derive compliance (secret, commitment) from wallet sig
 *   3. Build payment tx = SystemProgram.transfer(vault, lamports) + Memo(memo)
 *      where memo = base58(sha256(query_hash || commitment))
 *   4. wallet.signTransaction + sendRawTransaction + confirm  (1 Phantom popup)
 *   5. Generate Groth16 compliance proof in the browser
 *   6. POST /etorniegpt/chat with proof + payment_tx + payer_wallet
 *
 * The user signs exactly once per query (the payment tx). The on-chain
 * compliance proof tx is submitted by the backend operator with no user
 * signature because the proof itself binds the record to the wallet.
 */

import {
  Connection,
  PublicKey,
  SystemProgram,
  TransactionInstruction,
  TransactionMessage,
  VersionedTransaction,
  type SendOptions,
} from "@solana/web3.js";
import bs58 from "bs58";
import api from "@/lib/api";
import {
  bigintToBE32,
  generateComplianceProof,
  prepareComplianceInput,
  type WalletWithSignMessage,
} from "@/lib/zk/compliance";

/** Solana SPL Memo program (v2). */
export const MEMO_PROGRAM_ID = new PublicKey(
  "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
);

export interface ChatWallet extends WalletWithSignMessage {
  /**
   * Unified wallet-adapter send path. Delegates to the wallet's native
   * `signAndSendTransaction` when available (Phantom always does), otherwise
   * signs + forwards via the provided connection. Returns the tx signature.
   *
   * We use this instead of `signTransaction + sendRawTransaction` because
   * some wallets (Phantom included) broadcast inside their sign popup, and
   * an explicit second submit then fails with "this transaction has already
   * been processed". Letting wallet-adapter orchestrate avoids that race.
   */
  sendTransaction: (
    tx: VersionedTransaction,
    connection: Connection,
    options?: SendOptions,
  ) => Promise<string>;
}

export interface PaymentRequirements {
  network: string;
  asset: string;
  recipient: string;
  lamports: number;
  memo_scheme: string;
}

export interface ChatResult {
  answer: string;
  country_detected: string | null;
  model: string;
  query_hash_hex: string;
  commitment_hex: string;
  payment_tx: string;
  compliance_tx: string;
  compliance_pda: string;
  payment_explorer_url: string;
  compliance_explorer_url: string;
  compliance_record_explorer_url: string;
  /** True when the backend returned a cached answer and no new payment
   *  was required; the tx + PDA fields then refer to the earlier
   *  successful run. */
  cached?: boolean;
}

export interface CacheLookupHit {
  cached: true;
  answer: string;
  model: string;
  country_detected: string | null;
  payment_tx: string | null;
  compliance_tx: string | null;
  compliance_pda: string | null;
  payment_explorer_url: string | null;
  compliance_explorer_url: string | null;
  compliance_record_explorer_url: string | null;
}

export interface CacheLookupMiss {
  cached: false;
}

export type CacheLookup = CacheLookupHit | CacheLookupMiss;

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

async function sha256Concat(a: Uint8Array, b: Uint8Array): Promise<Uint8Array> {
  const joined = new Uint8Array(a.length + b.length);
  joined.set(a, 0);
  joined.set(b, a.length);
  const digest = await crypto.subtle.digest("SHA-256", joined);
  return new Uint8Array(digest);
}

/** Fetch the x402 payment requirements - recipient + lamports + memo scheme. */
export async function fetchPaymentRequirements(): Promise<PaymentRequirements> {
  const { data } = await api.get<PaymentRequirements>(
    "/etorniegpt/chat/payment-requirements",
  );
  return data;
}

function queryHashHex(queryHash: Uint8Array): string {
  let s = "";
  for (const b of queryHash) s += b.toString(16).padStart(2, "0");
  return s;
}

/** Check whether this (wallet, question) tuple already has a cached answer.
 *  Lets the UI skip the payment popup entirely for exact duplicates. */
export async function lookupCachedAnswer(opts: {
  payerWallet: string;
  queryHash: Uint8Array;
}): Promise<CacheLookup> {
  const { data } = await api.get<CacheLookup>("/etorniegpt/chat/cache-lookup", {
    params: {
      payer_wallet: opts.payerWallet,
      query_hash_hex: queryHashHex(opts.queryHash),
    },
  });
  return data;
}

interface BuildPaymentTxOpts {
  connection: Connection;
  payer: PublicKey;
  vault: PublicKey;
  lamports: number;
  memo: string;
}

/** Build the unsigned payment tx - one SystemProgram.transfer + one Memo. */
async function buildPaymentTx(
  opts: BuildPaymentTxOpts,
): Promise<VersionedTransaction> {
  const transferIx = SystemProgram.transfer({
    fromPubkey: opts.payer,
    toPubkey: opts.vault,
    lamports: opts.lamports,
  });
  const memoIx = new TransactionInstruction({
    programId: MEMO_PROGRAM_ID,
    keys: [],
    data: Buffer.from(new TextEncoder().encode(opts.memo)),
  });

  const { blockhash } = await opts.connection.getLatestBlockhash("confirmed");
  const message = new TransactionMessage({
    payerKey: opts.payer,
    recentBlockhash: blockhash,
    instructions: [transferIx, memoIx],
  }).compileToV0Message();

  return new VersionedTransaction(message);
}

/**
 * Run the full x402 chat handshake for a single query.
 *
 * @param question      The user's plaintext question.
 * @param language      Response language code (e.g. "tr", "en").
 * @param wallet        Connected Phantom/Solflare wallet.
 * @param connection    Existing Solana connection (pulled from useConnection).
 * @param requirements  Payment requirements (cached from fetchPaymentRequirements()).
 * @param onStage       Optional callback invoked with each stage name for UI progress.
 */
export async function askEtornieGPTOverX402(opts: {
  question: string;
  language: string;
  wallet: ChatWallet;
  connection: Connection;
  requirements: PaymentRequirements;
  onStage?: (stage: ChatStage) => void;
}): Promise<ChatResult> {
  const { question, language, wallet, connection, requirements, onStage } = opts;
  const notify = (s: ChatStage) => {
    if (onStage) onStage(s);
  };

  if (!wallet.publicKey) {
    throw new Error("Wallet is not connected.");
  }
  if (typeof wallet.signMessage !== "function") {
    throw new Error("Wallet does not expose signMessage (Phantom/Solflare required).");
  }
  if (typeof wallet.sendTransaction !== "function") {
    throw new Error("Wallet does not expose sendTransaction.");
  }

  // 1. Derive secret + commitment (triggers a signMessage popup).
  notify("deriving-secret");
  const prep = await prepareComplianceInput(question, wallet);

  // 2. Compute the memo = base58(sha256(query_hash || commitment)).
  const commitmentBytes = bigintToBE32(prep.commitment);
  const memoDigest = await sha256Concat(prep.queryHash, commitmentBytes);
  const memo = bs58.encode(memoDigest);

  // 3. Build + send the payment tx via wallet-adapter's unified path
  //    (single Phantom popup). sendTransaction resolves once the wallet
  //    has broadcast the tx; we then wait for confirmation.
  notify("building-payment");
  const vault = new PublicKey(requirements.recipient);
  const paymentTx = await buildPaymentTx({
    connection,
    payer: wallet.publicKey,
    vault,
    lamports: requirements.lamports,
    memo,
  });
  notify("signing-payment");
  const paymentSig = await wallet.sendTransaction(paymentTx, connection, {
    skipPreflight: false,
    maxRetries: 3,
  });
  notify("sending-payment");
  const latest = await connection.getLatestBlockhash("confirmed");
  await connection.confirmTransaction(
    {
      signature: paymentSig,
      blockhash: latest.blockhash,
      lastValidBlockHeight: latest.lastValidBlockHeight,
    },
    "confirmed",
  );

  // 4. Generate Groth16 compliance proof (no wallet interaction).
  notify("proving");
  const proofBundle = await generateComplianceProof(prep);

  // 5. Send the chat request with proof + payment reference.
  notify("submitting");
  const { data } = await api.post<ChatResult>("/etorniegpt/chat", {
    question,
    language,
    payer_wallet: wallet.publicKey.toBase58(),
    payment_tx: paymentSig,
    compliance_proof: {
      proof_a_b64: bytesToBase64(proofBundle.onchain.proofA),
      proof_b_b64: bytesToBase64(proofBundle.onchain.proofB),
      proof_c_b64: bytesToBase64(proofBundle.onchain.proofC),
      public_inputs_b64: proofBundle.onchain.publicInputs.map(bytesToBase64),
      query_hash_b64: bytesToBase64(prep.queryHash),
    },
  });

  notify("done");
  return data;
}

export type ChatStage =
  | "deriving-secret"
  | "building-payment"
  | "signing-payment"
  | "sending-payment"
  | "proving"
  | "submitting"
  | "done";
