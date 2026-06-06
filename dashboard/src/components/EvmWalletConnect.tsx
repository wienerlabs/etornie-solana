"use client";

import { useEffect, useState } from "react";
import {
  useAccount,
  useChainId,
  useChains,
  useConnect,
  useDisconnect,
  useSignMessage,
} from "wagmi";

function shortAddress(addr: string): string {
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
}

export default function EvmWalletConnect() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const { address, isConnected, connector: activeConnector } = useAccount();
  const { connectors, connect, isPending, error: connectError } = useConnect();
  const { disconnect } = useDisconnect();
  const chainId = useChainId();
  const chains = useChains();
  const { signMessageAsync, isPending: signing } = useSignMessage();

  const [signature, setSignature] = useState<string | null>(null);
  const [signError, setSignError] = useState<string | null>(null);

  const chainName =
    chains.find((c) => c.id === chainId)?.name ?? `Chain ${chainId}`;

  async function handleSign() {
    setSignError(null);
    setSignature(null);
    try {
      const message = `Etornie EVM ownership check\nAddress: ${address}\nIssued: ${new Date().toISOString()}`;
      const sig = await signMessageAsync({ message });
      setSignature(sig);
    } catch (err) {
      setSignError(
        (err as { shortMessage?: string; message?: string })?.shortMessage ??
          (err as { message?: string })?.message ??
          "Signature rejected."
      );
    }
  }

  // De-duplicate connectors by name (EIP-6963 discovery can surface the
  // same wallet more than once across runtimes).
  const uniqueConnectors = mounted
    ? connectors.filter(
        (c, i, arr) => arr.findIndex((o) => o.name === c.name) === i
      )
    : [];

  return (
    <section className="rounded-xl border border-[color:var(--color-stone)] bg-white p-6">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-[color:var(--color-ink)]">
            Cross-chain wallet (EVM)
          </h3>
          {mounted && isConnected ? (
            <span className="rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-semibold text-green-800">
              Connected
            </span>
          ) : (
            <span className="rounded-full bg-[color:var(--color-sand)] px-2.5 py-0.5 text-xs font-semibold text-[color:var(--color-muted)]">
              Not connected
            </span>
          )}
        </div>

        <p className="text-sm text-[color:var(--color-muted)]">
          Connect an EVM wallet (MetaMask, Rabby, WalletConnect) alongside your
          Solana wallet. Used for cross-chain signing required by the Moca
          integration.
        </p>

        {!mounted ? (
          <p className="text-sm text-[color:var(--color-muted)]">Loading…</p>
        ) : isConnected && address ? (
          <div className="space-y-3">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <dt className="text-[color:var(--color-muted)]">Wallet</dt>
              <dd className="text-[color:var(--color-ink)]">
                {activeConnector?.name ?? "Unknown"}
              </dd>
              <dt className="text-[color:var(--color-muted)]">Address</dt>
              <dd className="font-mono text-[color:var(--color-ink)]">
                {shortAddress(address)}
              </dd>
              <dt className="text-[color:var(--color-muted)]">Network</dt>
              <dd className="text-[color:var(--color-ink)]">{chainName}</dd>
            </dl>

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={handleSign}
                disabled={signing}
                className="rwa-btn-primary disabled:opacity-50"
              >
                {signing ? "Check your wallet…" : "Sign test message"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setSignature(null);
                  setSignError(null);
                  disconnect();
                }}
                className="rounded-lg border border-[color:var(--color-stone)] px-4 py-2 text-sm font-semibold text-[color:var(--color-muted)] hover:bg-[color:var(--color-sand)]"
              >
                Disconnect
              </button>
            </div>

            {signature && (
              <div className="rounded-lg border border-[color:var(--color-stone)] bg-[color:var(--color-elevated)] p-3">
                <p className="text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Signature
                </p>
                <p className="mt-1 break-all font-mono text-xs text-[color:var(--color-ink)]">
                  {signature}
                </p>
              </div>
            )}
            {signError && (
              <p className="text-sm text-red-700">{signError}</p>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            {uniqueConnectors.length === 0 ? (
              <p className="text-sm text-[color:var(--color-muted)]">
                No EVM wallet detected. Install MetaMask or Rabby, or configure
                WalletConnect.
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {uniqueConnectors.map((c) => (
                  <button
                    key={c.uid}
                    type="button"
                    disabled={isPending}
                    onClick={() => connect({ connector: c })}
                    className="rounded-lg border border-[color:var(--color-accent)] px-4 py-2 text-sm font-semibold text-[color:var(--color-accent)] hover:bg-[color:var(--color-accent-soft)] disabled:opacity-50"
                  >
                    {isPending ? "Connecting…" : `Connect ${c.name}`}
                  </button>
                ))}
              </div>
            )}
            {connectError && (
              <p className="text-sm text-red-700">
                {(connectError as { shortMessage?: string }).shortMessage ??
                  connectError.message}
              </p>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
