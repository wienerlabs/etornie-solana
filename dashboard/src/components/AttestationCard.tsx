"use client";

import { useState } from "react";
import { env } from "@/lib/env";

interface AttestationCardProps {
  txSignature: string | null;
  pda: string | null;
  clientWallet?: string | null;
  cluster?: "devnet" | "mainnet-beta" | "testnet";
}

const SHORTEN = (value: string, head = 6, tail = 6): string =>
  value.length <= head + tail + 1 ? value : `${value.slice(0, head)}…${value.slice(-tail)}`;

export function AttestationCard({
  txSignature,
  pda,
  clientWallet = null,
  cluster = env.solanaCluster,
}: AttestationCardProps) {
  const [copied, setCopied] = useState<"tx" | "pda" | "client" | null>(null);

  const copy = async (value: string, which: "tx" | "pda" | "client") => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(which);
      setTimeout(() => setCopied(null), 1200);
    } catch {
      // ignore clipboard failures silently
    }
  };

  const explorerTx = txSignature
    ? `https://explorer.solana.com/tx/${txSignature}?cluster=${cluster}`
    : null;
  const explorerPda = pda
    ? `https://explorer.solana.com/address/${pda}?cluster=${cluster}`
    : null;
  const explorerClient = clientWallet
    ? `https://explorer.solana.com/address/${clientWallet}?cluster=${cluster}`
    : null;

  // The case attestation is a secondary on-chain record (operator
  // signs + client co-signs from their wallet); it is NOT created
  // automatically and there is no manual trigger in the dashboard
  // yet. Hide the empty card entirely so the user does not see a
  // dead "Not attested" tile next to the NFT panel that already
  // proves the case is on-chain (mint + metadata + setup tx).
  if (!txSignature || !pda) {
    return null;
  }

  return (
    <div className="mb-6 rounded-lg border border-emerald-200 bg-emerald-50/50 p-6 shadow-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-800">
          On-Chain Attestation
        </h2>
        <span className="flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-medium text-emerald-700">
          <span aria-hidden>✓</span> Verified on {cluster}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <Field
          label="Transaction"
          value={txSignature}
          shown={SHORTEN(txSignature, 8, 8)}
          href={explorerTx!}
          copied={copied === "tx"}
          onCopy={() => copy(txSignature, "tx")}
        />
        <Field
          label="Attestation PDA"
          value={pda}
          shown={SHORTEN(pda, 8, 8)}
          href={explorerPda!}
          copied={copied === "pda"}
          onCopy={() => copy(pda, "pda")}
        />
        {clientWallet && explorerClient && (
          <Field
            label="Client Wallet"
            value={clientWallet}
            shown={SHORTEN(clientWallet, 8, 8)}
            href={explorerClient}
            copied={copied === "client"}
            onCopy={() => copy(clientWallet, "client")}
          />
        )}
      </div>
    </div>
  );
}

interface FieldProps {
  label: string;
  value: string;
  shown: string;
  href: string;
  copied: boolean;
  onCopy: () => void;
}

function Field({ label, value, shown, href, copied, onCopy }: FieldProps) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
        {label}
      </p>
      <div className="mt-1 flex items-center gap-2">
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="font-mono text-sm text-emerald-700 underline-offset-2 hover:underline"
          title={value}
        >
          {shown}
        </a>
        <button
          type="button"
          onClick={onCopy}
          className="rounded border border-gray-200 bg-white px-1.5 py-0.5 text-xs text-gray-600 hover:bg-gray-50"
          aria-label={`Copy ${label}`}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

export default AttestationCard;
