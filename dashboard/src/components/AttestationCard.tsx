"use client";

import { useState } from "react";

interface AttestationCardProps {
  txSignature: string | null;
  pda: string | null;
  cluster?: "devnet" | "mainnet-beta" | "testnet";
}

const SHORTEN = (value: string, head = 6, tail = 6): string =>
  value.length <= head + tail + 1 ? value : `${value.slice(0, head)}…${value.slice(-tail)}`;

export function AttestationCard({
  txSignature,
  pda,
  cluster = "devnet",
}: AttestationCardProps) {
  const [copied, setCopied] = useState<"tx" | "pda" | null>(null);

  const copy = async (value: string, which: "tx" | "pda") => {
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

  if (!txSignature || !pda) {
    return (
      <div className="mb-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-700">
            On-Chain Attestation
          </h2>
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500">
            Not attested
          </span>
        </div>
        <p className="mt-2 text-sm text-gray-500">
          This case has no Solana attestation yet. Attestations are created
          automatically for users who signed in with a wallet.
        </p>
      </div>
    );
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
