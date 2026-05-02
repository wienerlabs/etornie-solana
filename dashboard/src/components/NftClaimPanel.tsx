"use client";

/**
 * NftClaimPanel — three-step on-chain NFT lifecycle for an EtornieGPT
 * filing.
 *
 *   step 1  Attest       client signs the case attestation tx
 *           ─────────►   backend records attestation_tx + kicks off
 *                        Token-2022 mint setup in the background
 *
 *   step 2  Setup        operator-only, autonomous; we poll the case
 *           ─────────►   row until nft_state flips from `none` to
 *                        `pending_claim`
 *
 *   step 3  Claim        client signs the mint tx; backend operator
 *           ─────────►   co-signs and submits → nft_state = `minted`
 *
 * Renders nothing until a case_id is supplied (i.e. the parent has
 * already wired up a Pay flow that returned case_id).
 */

import { useCallback, useEffect, useState } from "react";
import { useWallet } from "@solana/wallet-adapter-react";
import {
  PublicKey,
  TransactionInstruction,
  TransactionMessage,
  VersionedTransaction,
  type AccountMeta,
} from "@solana/web3.js";
import api, { extractErrorMessage } from "@/lib/api";
import { claimCaseNft } from "@/lib/nftClaim";

type NftState = "none" | "pending_claim" | "minted" | "burned";

interface PendingAttestation {
  program_id: string;
  operator: string;
  pda: string;
  ix_data_b64: string;
  recent_blockhash: string;
}

interface CaseDetail {
  id: string;
  case_number: string;
  client_wallet: string | null;
  attestation_tx: string | null;
  attestation_pda: string | null;
  nft_state: NftState;
  nft_mint: string | null;
  nft_setup_tx: string | null;
  nft_mint_tx: string | null;
  nft_burn_tx: string | null;
  nft_burned_at: string | null;
}

interface NftClaimPanelProps {
  caseId: string;
  caseNumber: string;
  cluster?: "devnet" | "mainnet-beta" | "testnet";
}

function bytesToBase64(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

function base64ToBytes(b64: string): Uint8Array {
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function shortHash(value: string | null | undefined, head = 8, tail = 8): string {
  if (!value) return "—";
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

export function NftClaimPanel({
  caseId,
  caseNumber,
  cluster = "devnet",
}: NftClaimPanelProps) {
  const wallet = useWallet();
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await api.get<CaseDetail>(`/cases/${caseId}`);
      setCaseDetail(res.data);
    } catch (err) {
      setError(extractErrorMessage(err, "Could not load case detail."));
    }
  }, [caseId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Auto-poll while NFT setup is running so the panel reacts when the
  // operator finishes creating the mint without the user having to
  // refresh anything.
  useEffect(() => {
    if (!caseDetail) return;
    if (caseDetail.attestation_tx && caseDetail.nft_state === "none") {
      const t = setInterval(refresh, 4000);
      return () => clearInterval(t);
    }
    return undefined;
  }, [caseDetail, refresh]);

  const explorerTx = (sig: string) =>
    `https://explorer.solana.com/tx/${sig}?cluster=${cluster}`;
  const explorerAddr = (addr: string) =>
    `https://explorer.solana.com/address/${addr}?cluster=${cluster}`;

  const handleAttest = useCallback(async () => {
    setError(null);
    setStage(null);
    if (
      !wallet.connected ||
      !wallet.publicKey ||
      !wallet.signTransaction
    ) {
      setError("Connect Phantom/Solflare to sign the attestation.");
      return;
    }
    setBusy(true);
    try {
      setStage("Loading attestation payload…");
      const prepRes = await api.get<PendingAttestation>(
        `/cases/${caseId}/attestation/prepare`
      );
      const p = prepRes.data;

      const operator = new PublicKey(p.operator);
      const user = wallet.publicKey;
      const pda = new PublicKey(p.pda);
      const programId = new PublicKey(p.program_id);

      // Account order MUST match the on-chain CreateCaseAttestation
      // accounts struct exactly: pda → operator → creator → system.
      // Cases page uses this ordering (and it's been working there).
      const keys: AccountMeta[] = [
        { pubkey: pda, isSigner: false, isWritable: true },
        { pubkey: operator, isSigner: true, isWritable: true },
        { pubkey: user, isSigner: true, isWritable: false },
        {
          pubkey: new PublicKey("11111111111111111111111111111111"),
          isSigner: false,
          isWritable: false,
        },
      ];
      const ix = new TransactionInstruction({
        programId,
        keys,
        data: Buffer.from(base64ToBytes(p.ix_data_b64)),
      });
      const msg = new TransactionMessage({
        payerKey: operator,
        recentBlockhash: p.recent_blockhash,
        instructions: [ix],
      }).compileToV0Message();
      const tx = new VersionedTransaction(msg);

      setStage("Approve attestation in your wallet…");
      const signed = await wallet.signTransaction(tx);

      setStage("Submitting attestation to devnet…");
      await api.post(`/cases/${caseId}/attestation/submit`, {
        signed_tx_b64: bytesToBase64(signed.serialize()),
      });
      setStage("Waiting for NFT setup (operator)…");
      await refresh();
    } catch (err) {
      setError(extractErrorMessage(err, "Attestation failed."));
    } finally {
      setBusy(false);
      setStage(null);
    }
  }, [caseId, wallet, refresh]);

  const handleClaim = useCallback(async () => {
    setError(null);
    setStage(null);
    if (
      !wallet.connected ||
      !wallet.publicKey ||
      !wallet.signTransaction
    ) {
      setError("Connect Phantom/Solflare to claim the NFT.");
      return;
    }
    setBusy(true);
    try {
      setStage("Approve mint tx in your wallet…");
      await claimCaseNft(caseId, {
        publicKey: wallet.publicKey,
        signTransaction: wallet.signTransaction,
      });
      await refresh();
    } catch (err) {
      setError(extractErrorMessage(err, "Claim failed."));
    } finally {
      setBusy(false);
      setStage(null);
    }
  }, [caseId, wallet, refresh]);

  if (!caseDetail) {
    return (
      <div className="mt-2 rounded-lg border border-[color:var(--color-stone)] bg-white px-3 py-2 text-xs text-[color:var(--color-muted)]">
        Loading case NFT panel…
      </div>
    );
  }

  const noAttest = !caseDetail.attestation_tx;
  const setupRunning =
    !!caseDetail.attestation_tx && caseDetail.nft_state === "none";
  const readyToClaim = caseDetail.nft_state === "pending_claim";
  const minted = caseDetail.nft_state === "minted";
  const burned = caseDetail.nft_state === "burned";

  const walletMatches =
    !!wallet.publicKey &&
    !!caseDetail.client_wallet &&
    wallet.publicKey.toBase58() === caseDetail.client_wallet;

  let tone = "border-[color:var(--color-stone)] bg-white";
  if (noAttest) tone = "border-amber-200 bg-amber-50";
  if (setupRunning) tone = "border-blue-200 bg-blue-50";
  if (readyToClaim) tone = "border-amber-300 bg-amber-50";
  if (minted) tone = "border-emerald-200 bg-emerald-50";
  if (burned) tone = "border-red-200 bg-red-50";

  return (
    <div className={`mt-2 rounded-lg border ${tone} px-3 py-3`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-[color:var(--color-espresso)]">
          Case NFT · {caseNumber}
        </span>
        <span className="text-[10px] uppercase tracking-wide text-[color:var(--color-muted)]">
          {caseDetail.nft_state.replace("_", " ")}
        </span>
      </div>

      {noAttest && (
        <div className="mt-2 flex items-center gap-3">
          <p className="flex-1 text-xs text-amber-900">
            Step 1 of 3: Sign the on-chain attestation so we can mint the
            soul-bound NFT.
          </p>
          <button
            type="button"
            onClick={handleAttest}
            disabled={busy || !wallet.connected}
            className="rounded-md bg-[color:var(--color-bronze)] px-3 py-1.5 text-xs font-semibold text-[color:var(--color-cream)] hover:bg-[color:var(--color-bronze-dark)] disabled:bg-[color:var(--color-stone)] disabled:text-[color:var(--color-muted)]"
          >
            {busy ? "Signing…" : "Attest"}
          </button>
        </div>
      )}

      {setupRunning && (
        <p className="mt-2 text-xs text-blue-900">
          Step 2 of 3: Operator is initialising the Token-2022 mint. This
          panel refreshes itself when setup is complete (typically 5-15
          seconds).
        </p>
      )}

      {readyToClaim && (
        <div className="mt-2 flex items-center gap-3">
          <p className="flex-1 text-xs text-amber-900">
            Step 3 of 3: The mint is ready. Sign the claim tx in your
            wallet to move the soul-bound NFT into your account.
          </p>
          <button
            type="button"
            onClick={handleClaim}
            disabled={busy || !wallet.connected || !walletMatches}
            className="rounded-md bg-[color:var(--color-bronze)] px-3 py-1.5 text-xs font-semibold text-[color:var(--color-cream)] hover:bg-[color:var(--color-bronze-dark)] disabled:bg-[color:var(--color-stone)] disabled:text-[color:var(--color-muted)]"
          >
            {busy ? "Signing…" : "Claim NFT"}
          </button>
        </div>
      )}

      {readyToClaim && !walletMatches && wallet.connected && (
        <p className="mt-1 text-xs text-red-700">
          Connected wallet does not match the case client wallet
          ({shortHash(caseDetail.client_wallet, 6, 6)}).
        </p>
      )}

      {(minted || burned) && caseDetail.nft_mint && (
        <div className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 font-mono text-[10px] leading-tight text-[color:var(--color-muted)]">
          <span>mint</span>
          <a
            href={explorerAddr(caseDetail.nft_mint)}
            target="_blank"
            rel="noopener noreferrer"
            className="break-all text-emerald-700 underline"
            title={caseDetail.nft_mint}
          >
            {shortHash(caseDetail.nft_mint)}
          </a>
          {caseDetail.nft_mint_tx && (
            <>
              <span>mint tx</span>
              <a
                href={explorerTx(caseDetail.nft_mint_tx)}
                target="_blank"
                rel="noopener noreferrer"
                className="break-all text-emerald-700 underline"
                title={caseDetail.nft_mint_tx}
              >
                {shortHash(caseDetail.nft_mint_tx)}
              </a>
            </>
          )}
          {caseDetail.attestation_tx && (
            <>
              <span>attest tx</span>
              <a
                href={explorerTx(caseDetail.attestation_tx)}
                target="_blank"
                rel="noopener noreferrer"
                className="break-all underline"
                title={caseDetail.attestation_tx}
              >
                {shortHash(caseDetail.attestation_tx)}
              </a>
            </>
          )}
          {caseDetail.attestation_pda && (
            <>
              <span>attest pda</span>
              <a
                href={explorerAddr(caseDetail.attestation_pda)}
                target="_blank"
                rel="noopener noreferrer"
                className="break-all underline"
                title={caseDetail.attestation_pda}
              >
                {shortHash(caseDetail.attestation_pda)}
              </a>
            </>
          )}
          {caseDetail.nft_burn_tx && (
            <>
              <span>burn tx</span>
              <a
                href={explorerTx(caseDetail.nft_burn_tx)}
                target="_blank"
                rel="noopener noreferrer"
                className="break-all text-red-700 underline"
                title={caseDetail.nft_burn_tx}
              >
                {shortHash(caseDetail.nft_burn_tx)}
              </a>
            </>
          )}
        </div>
      )}

      {stage && (
        <p className="mt-2 text-xs text-[color:var(--color-muted)]">{stage}</p>
      )}
      {error && <p className="mt-1 text-xs text-red-700">{error}</p>}
    </div>
  );
}

export default NftClaimPanel;
