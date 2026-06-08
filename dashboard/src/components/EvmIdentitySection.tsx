"use client";

import { useCallback, useEffect, useState } from "react";
import api, { extractErrorMessage } from "@/lib/api";
import {
  useEvmProviders,
  requestEvmSignature,
  type Eip6963ProviderDetail,
} from "@/lib/evm/providers";

function shortAddr(a: string): string {
  return `${a.slice(0, 6)}…${a.slice(-4)}`;
}

export default function EvmIdentitySection() {
  const providers = useEvmProviders();
  const [evmAddress, setEvmAddress] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const res = await api.get<{ evm_address: string | null }>("/auth/me");
      setEvmAddress(res.data.evm_address ?? null);
    } catch {
      // non-fatal
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  async function link(detail: Eip6963ProviderDetail) {
    setError(null);
    setBusy(detail.info.uuid);
    try {
      const signed = await requestEvmSignature(detail.provider);
      const res = await api.post<{ evm_address: string }>("/auth/evm/link", signed);
      setEvmAddress(res.data.evm_address);
    } catch (err) {
      setError(extractErrorMessage(err, "Could not link the EVM wallet."));
    } finally {
      setBusy(null);
    }
  }

  async function unlink() {
    setError(null);
    setBusy("unlink");
    try {
      await api.delete("/auth/evm/link");
      setEvmAddress(null);
    } catch (err) {
      setError(extractErrorMessage(err, "Could not unlink the EVM wallet."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="rounded-xl border border-[color:var(--color-stone)] bg-white p-6">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-[color:var(--color-ink)]">
            Linked EVM wallet
          </h3>
          {evmAddress ? (
            <span className="rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-semibold text-green-800">
              Linked
            </span>
          ) : (
            <span className="rounded-full bg-[color:var(--color-sand)] px-2.5 py-0.5 text-xs font-semibold text-[color:var(--color-muted)]">
              Not linked
            </span>
          )}
        </div>

        <p className="text-sm text-[color:var(--color-muted)]">
          Link an EVM wallet (MetaMask, Rabby, Phantom&apos;s EVM account) to
          this Etornie account so you keep one identity across Solana and EVM.
          Once linked, you can sign in with either wallet and reach the same
          account.
        </p>

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800"
          >
            {error}
          </div>
        )}

        {loading ? (
          <p className="text-sm text-[color:var(--color-muted)]">Loading…</p>
        ) : evmAddress ? (
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-mono text-sm text-[color:var(--color-ink)]">
              {shortAddr(evmAddress)}
            </span>
            <button
              type="button"
              disabled={busy !== null}
              onClick={unlink}
              className="rounded-lg border border-red-300 px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
            >
              {busy === "unlink" ? "Working…" : "Unlink"}
            </button>
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
                onClick={() => link(p)}
                className="inline-flex items-center gap-2 rounded-lg border border-[color:var(--color-accent)] px-4 py-2 text-sm font-semibold text-[color:var(--color-accent)] hover:bg-[color:var(--color-accent-soft)] disabled:opacity-50"
              >
                {p.info.icon && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={p.info.icon} alt="" width={18} height={18} className="h-4 w-4" />
                )}
                {busy === p.info.uuid ? "Check your wallet…" : `Link ${p.info.name}`}
              </button>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
