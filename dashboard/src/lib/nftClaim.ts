import {
  Connection,
  PublicKey,
  TransactionInstruction,
  TransactionMessage,
  VersionedTransaction,
  type AccountMeta,
} from "@solana/web3.js";
import api from "@/lib/api";

export interface NftAccountMeta {
  pubkey: string;
  is_signer: boolean;
  is_writable: boolean;
}

export interface NftInstructionPayload {
  program_id: string;
  accounts: NftAccountMeta[];
  data_b64: string;
}

export interface MintClaimPrepareResponse {
  program_id: string;
  operator: string;
  client: string;
  mint: string;
  client_token_account: string;
  nft_authority: string;
  case_nft_record: string;
  ata_ix: NftInstructionPayload;
  mint_ix: NftInstructionPayload;
  recent_blockhash: string;
  metadata_uri: string;
  metadata_uri_hash_hex: string;
}

function base64ToBytes(b64: string): Uint8Array {
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

function toTransactionInstruction(
  payload: NftInstructionPayload,
): TransactionInstruction {
  const keys: AccountMeta[] = payload.accounts.map((a) => ({
    pubkey: new PublicKey(a.pubkey),
    isSigner: a.is_signer,
    isWritable: a.is_writable,
  }));
  return new TransactionInstruction({
    programId: new PublicKey(payload.program_id),
    keys,
    data: Buffer.from(base64ToBytes(payload.data_b64)),
  });
}

interface WalletLike {
  publicKey: PublicKey | null;
  signTransaction?: (tx: VersionedTransaction) => Promise<VersionedTransaction>;
}

interface CaseDetailLike {
  id: string;
  nft_mint: string | null;
  nft_state: string;
  nft_mint_tx: string | null;
}

export interface ClaimResult {
  /** Updated case row from the backend after finalize. */
  case: CaseDetailLike & Record<string, unknown>;
  /** mint_case_nft tx signature. */
  mint_tx: string;
}

/**
 * Prepare → sign via Phantom → finalize the mint_case_nft tx.
 *
 * The backend has already completed the Token-2022 mint setup
 * (nft_state = pending_claim). This function composes the ATA + mint
 * instructions returned by the backend, has the connected wallet sign,
 * and submits the signed bytes back for operator co-signing and
 * devnet confirmation.
 */
export async function claimCaseNft(
  caseId: string,
  wallet: WalletLike,
): Promise<ClaimResult> {
  if (!wallet.publicKey || !wallet.signTransaction) {
    throw new Error("Wallet is not connected or does not support signing.");
  }

  const prep = await api.post<MintClaimPrepareResponse>(
    `/cases/${caseId}/nft/prepare-claim`,
  );
  const p = prep.data;

  const operator = new PublicKey(p.operator);
  const ataIx = toTransactionInstruction(p.ata_ix);
  const mintIx = toTransactionInstruction(p.mint_ix);

  const msg = new TransactionMessage({
    payerKey: operator,
    recentBlockhash: p.recent_blockhash,
    instructions: [ataIx, mintIx],
  }).compileToV0Message();

  const tx = new VersionedTransaction(msg);
  const signedTx = await wallet.signTransaction(tx);

  const signedB64 = bytesToBase64(signedTx.serialize());
  const finalize = await api.post(
    `/cases/${caseId}/nft/finalize-claim`,
    { signed_tx_b64: signedB64 },
  );

  return {
    case: finalize.data,
    mint_tx: (finalize.data as Record<string, string>).nft_mint_tx ?? "",
  };
}
