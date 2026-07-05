"use client";

import { useState } from "react";
import { useWallet } from "@solana/wallet-adapter-react";
import { claimCaseNft } from "@/lib/nftClaim";
import { env } from "@/lib/env";

type NftState = "none" | "pending_claim" | "minted" | "burned";

interface NftCardProps {
  caseId: string;
  caseNumber: string;
  nftState: NftState;
  nftMint: string | null;
  nftSetupTx: string | null;
  nftMintTx: string | null;
  nftBurnTx: string | null;
  nftBurnedAt: string | null;
  clientWallet: string | null;
  cluster?: "devnet" | "mainnet-beta" | "testnet";
  onClaimed?: (updatedCase: Record<string, unknown>) => void;
}

const SHORTEN = (value: string, head = 6, tail = 6): string =>
  value.length <= head + tail + 1
    ? value
    : `${value.slice(0, head)}…${value.slice(-tail)}`;

const STATE_LABEL: Record<NftState, string> = {
  none: "Not attested yet",
  pending_claim: "Ready to claim",
  minted: "In client wallet (frozen)",
  burned: "Case closed — NFT burned",
};

const STATE_CHIP_CLASS: Record<NftState, string> = {
  none: "bg-gray-100 text-gray-500",
  pending_claim: "bg-amber-100 text-amber-700",
  minted: "bg-emerald-100 text-emerald-700",
  burned: "bg-red-100 text-red-700",
};

const SURFACE_CLASS: Record<NftState, string> = {
  none: "border-gray-200 bg-white",
  pending_claim: "border-amber-200 bg-amber-50/60",
  minted: "border-emerald-200 bg-emerald-50/50",
  burned: "border-red-200 bg-red-50/50",
};

export function NftCard({
  caseId,
  caseNumber,
  nftState,
  nftMint,
  nftSetupTx,
  nftMintTx,
  nftBurnTx,
  nftBurnedAt,
  clientWallet,
  cluster = env.solanaCluster,
  onClaimed,
}: NftCardProps) {
  const wallet = useWallet();
  const [claiming, setClaiming] = useState(false);
  const [claimError, setClaimError] = useState<string>("");
  const [claimSuccess, setClaimSuccess] = useState<string>("");

  const explorerAddr = (addr: string) =>
    `https://explorer.solana.com/address/${addr}?cluster=${cluster}`;
  const explorerTx = (sig: string) =>
    `https://explorer.solana.com/tx/${sig}?cluster=${cluster}`;

  const canClaim =
    nftState === "pending_claim" &&
    wallet.connected &&
    wallet.publicKey &&
    clientWallet &&
    wallet.publicKey.toBase58() === clientWallet;

  const handleClaim = async () => {
    if (!wallet.publicKey || !wallet.signTransaction) {
      setClaimError("Connect Phantom to claim this NFT.");
      return;
    }
    setClaiming(true);
    setClaimError("");
    setClaimSuccess("");
    try {
      const { case: updatedCase, mint_tx } = await claimCaseNft(caseId, {
        publicKey: wallet.publicKey,
        signTransaction: wallet.signTransaction,
      });
      setClaimSuccess(`NFT claimed. Tx: ${SHORTEN(mint_tx, 8, 8)}`);
      onClaimed?.(updatedCase);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setClaimError(msg);
    } finally {
      setClaiming(false);
    }
  };

  return (
    <div
      className={`mb-6 rounded-lg border p-6 shadow-sm ${SURFACE_CLASS[nftState]}`}
    >
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-800">
          Case NFT · {caseNumber}
        </h2>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATE_CHIP_CLASS[nftState]}`}
        >
          {STATE_LABEL[nftState]}
        </span>
      </div>

      {nftState === "none" && (
        <p className="mt-3 text-sm text-gray-500">
          Once the case attestation is confirmed on devnet, the backend will
          set up a soul-bound Token-2022 mint here. Refresh after a few
          seconds.
        </p>
      )}

      {nftState === "pending_claim" && (
        <div className="mt-3 space-y-3">
          <p className="text-sm text-amber-800">
            The Token-2022 mint is ready. Sign the mint tx in Phantom to move
            the soul-bound NFT into your wallet.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={handleClaim}
              disabled={!canClaim || claiming}
              className="rounded-md bg-amber-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {claiming ? "Waiting for Phantom..." : "Claim NFT"}
            </button>
            {!wallet.connected && (
              <span className="text-xs text-gray-500">
                Connect your wallet first.
              </span>
            )}
            {wallet.connected &&
              clientWallet &&
              wallet.publicKey?.toBase58() !== clientWallet && (
                <span className="text-xs text-red-600">
                  Connected wallet does not match the case client wallet.
                </span>
              )}
          </div>
          {claimError && (
            <p className="text-sm text-red-600">{claimError}</p>
          )}
          {claimSuccess && (
            <p className="text-sm text-emerald-700">{claimSuccess}</p>
          )}
        </div>
      )}

      {(nftState === "minted" || nftState === "burned") && nftMint && (
        <div className="mt-4 grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
          <Row label="Mint">
            <a
              href={explorerAddr(nftMint)}
              target="_blank"
              rel="noreferrer"
              className="font-mono text-emerald-700 hover:underline"
              title={nftMint}
            >
              {SHORTEN(nftMint, 8, 8)}
            </a>
          </Row>
          {nftState === "minted" && (
            <Row label="Soul-bound">
              <span className="text-emerald-700">
                Frozen (Token-2022 DefaultAccountState)
              </span>
            </Row>
          )}
          {nftMintTx && (
            <Row label="Mint tx">
              <a
                href={explorerTx(nftMintTx)}
                target="_blank"
                rel="noreferrer"
                className="font-mono text-emerald-700 hover:underline"
                title={nftMintTx}
              >
                {SHORTEN(nftMintTx, 8, 8)}
              </a>
            </Row>
          )}
          {nftSetupTx && (
            <Row label="Setup tx">
              <a
                href={explorerTx(nftSetupTx)}
                target="_blank"
                rel="noreferrer"
                className="font-mono text-gray-600 hover:underline"
                title={nftSetupTx}
              >
                {SHORTEN(nftSetupTx, 8, 8)}
              </a>
            </Row>
          )}
          {nftBurnTx && (
            <Row label="Burn tx">
              <a
                href={explorerTx(nftBurnTx)}
                target="_blank"
                rel="noreferrer"
                className="font-mono text-red-700 hover:underline"
                title={nftBurnTx}
              >
                {SHORTEN(nftBurnTx, 8, 8)}
              </a>
            </Row>
          )}
          {nftBurnedAt && (
            <Row label="Burned at">
              <span className="text-red-700">
                {new Date(nftBurnedAt).toLocaleString()}
              </span>
            </Row>
          )}
        </div>
      )}
    </div>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
        {label}
      </p>
      <div className="mt-1">{children}</div>
    </div>
  );
}

export default NftCard;
