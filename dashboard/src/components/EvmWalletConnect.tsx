"use client";

import { useEffect, useState } from "react";

// Lightweight EVM wallet adapter via EIP-6963 multi-injected-provider
// discovery. No wagmi/viem dependency: discovery + personal_sign cover
// MetaMask, Rabby, Phantom's EVM provider, and any EIP-6963 wallet, which
// is what the Moca cross-chain signer needs. (WalletConnect's QR transport
// would pull the heavy Reown/WalletConnect/Coinbase dependency tree and is
// intentionally left out of this adapter.)

interface EthereumProvider {
  request(args: { method: string; params?: unknown[] }): Promise<unknown>;
}

interface Eip6963Detail {
  info: { uuid: string; name: string; icon: string; rdns: string };
  provider: EthereumProvider;
}

const CHAIN_NAMES: Record<string, string> = {
  "0x1": "Ethereum",
  "0xaa36a7": "Sepolia",
  "0x2105": "Base",
  "0x36a8": "Moca Chain Testnet",
};

function shortAddress(addr: string): string {
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
}

function useEvmProviders(): Eip6963Detail[] {
  const [providers, setProviders] = useState<Eip6963Detail[]>([]);
  useEffect(() => {
    const onAnnounce = (event: Event) => {
      const detail = (event as CustomEvent<Eip6963Detail>).detail;
      if (!detail?.info?.uuid) return;
      setProviders((prev) =>
        prev.some((p) => p.info.uuid === detail.info.uuid)
          ? prev
          : [...prev, detail]
      );
    };
    window.addEventListener(
      "eip6963:announceProvider",
      onAnnounce as EventListener
    );
    window.dispatchEvent(new Event("eip6963:requestProvider"));
    return () =>
      window.removeEventListener(
        "eip6963:announceProvider",
        onAnnounce as EventListener
      );
  }, []);
  return providers;
}

export default function EvmWalletConnect() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const providers = useEvmProviders();

  const [connected, setConnected] = useState<{
    name: string;
    address: string;
    chainId: string;
    provider: EthereumProvider;
  } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [signature, setSignature] = useState<string | null>(null);

  function readError(err: unknown, fallback: string): string {
    return (
      (err as { shortMessage?: string })?.shortMessage ??
      (err as { message?: string })?.message ??
      fallback
    );
  }

  async function connect(detail: Eip6963Detail) {
    setError(null);
    setSignature(null);
    setBusy(detail.info.uuid);
    try {
      const accounts = (await detail.provider.request({
        method: "eth_requestAccounts",
      })) as string[];
      const address = accounts?.[0];
      if (!address) throw new Error("No account selected.");
      const chainId = (await detail.provider.request({
        method: "eth_chainId",
      })) as string;
      setConnected({
        name: detail.info.name,
        address,
        chainId,
        provider: detail.provider,
      });
    } catch (err) {
      setError(readError(err, "Could not connect."));
    } finally {
      setBusy(null);
    }
  }

  async function signTestMessage() {
    if (!connected) return;
    setError(null);
    setSignature(null);
    setBusy("sign");
    try {
      const message = `Etornie EVM ownership check\nAddress: ${connected.address}\nIssued: ${new Date().toISOString()}`;
      const sig = (await connected.provider.request({
        method: "personal_sign",
        params: [message, connected.address],
      })) as string;
      setSignature(sig);
    } catch (err) {
      setError(readError(err, "Signature rejected."));
    } finally {
      setBusy(null);
    }
  }

  function disconnect() {
    setConnected(null);
    setSignature(null);
    setError(null);
  }

  const chainName =
    connected &&
    (CHAIN_NAMES[connected.chainId] ??
      `Chain ${parseInt(connected.chainId, 16)}`);

  return (
    <section className="rounded-xl border border-[color:var(--color-stone)] bg-white p-6">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-[color:var(--color-ink)]">
            Cross-chain wallet (EVM)
          </h3>
          {mounted && connected ? (
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
          Connect an EVM wallet (MetaMask, Rabby, Phantom&apos;s EVM account)
          alongside your Solana wallet. Used for cross-chain signing required by
          the Moca integration.
        </p>

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800"
          >
            {error}
          </div>
        )}

        {!mounted ? (
          <p className="text-sm text-[color:var(--color-muted)]">Loading…</p>
        ) : connected ? (
          <div className="space-y-3">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <dt className="text-[color:var(--color-muted)]">Wallet</dt>
              <dd className="text-[color:var(--color-ink)]">{connected.name}</dd>
              <dt className="text-[color:var(--color-muted)]">Address</dt>
              <dd className="font-mono text-[color:var(--color-ink)]">
                {shortAddress(connected.address)}
              </dd>
              <dt className="text-[color:var(--color-muted)]">Network</dt>
              <dd className="text-[color:var(--color-ink)]">{chainName}</dd>
            </dl>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={signTestMessage}
                disabled={busy !== null}
                className="rwa-btn-primary disabled:opacity-50"
              >
                {busy === "sign" ? "Check your wallet…" : "Sign test message"}
              </button>
              <button
                type="button"
                onClick={disconnect}
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
          </div>
        ) : providers.length === 0 ? (
          <p className="text-sm text-[color:var(--color-muted)]">
            No EVM wallet detected. Install MetaMask or Rabby.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {providers.map((p) => (
              <button
                key={p.info.uuid}
                type="button"
                disabled={busy !== null}
                onClick={() => connect(p)}
                className="inline-flex items-center gap-2 rounded-lg border border-[color:var(--color-accent)] px-4 py-2 text-sm font-semibold text-[color:var(--color-accent)] hover:bg-[color:var(--color-accent-soft)] disabled:opacity-50"
              >
                {p.info.icon && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={p.info.icon}
                    alt=""
                    width={18}
                    height={18}
                    className="h-4 w-4"
                  />
                )}
                {busy === p.info.uuid ? "Connecting…" : `Connect ${p.info.name}`}
              </button>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
