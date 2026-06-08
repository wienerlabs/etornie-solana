"use client";

import { useEffect, useState } from "react";
import api from "@/lib/api";

export interface EthereumProvider {
  request(args: { method: string; params?: unknown[] }): Promise<unknown>;
}

export interface Eip6963ProviderInfo {
  uuid: string;
  name: string;
  icon: string;
  rdns: string;
}

export interface Eip6963ProviderDetail {
  info: Eip6963ProviderInfo;
  provider: EthereumProvider;
}

/**
 * Discover injected EVM wallets via EIP-6963 (MetaMask, Rabby, Phantom's
 * EVM provider, etc.). Falls back to a single generic entry for
 * `window.ethereum` when no wallet announces itself.
 */
export function useEvmProviders(): Eip6963ProviderDetail[] {
  const [providers, setProviders] = useState<Eip6963ProviderDetail[]>([]);

  useEffect(() => {
    const onAnnounce = (event: Event) => {
      const detail = (event as CustomEvent<Eip6963ProviderDetail>).detail;
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

    // Fallback: if nothing announced shortly, surface window.ethereum.
    const timer = window.setTimeout(() => {
      setProviders((prev) => {
        if (prev.length > 0) return prev;
        const eth = (window as unknown as { ethereum?: EthereumProvider })
          .ethereum;
        if (!eth) return prev;
        return [
          {
            info: {
              uuid: "injected",
              name: "Injected wallet",
              icon: "",
              rdns: "injected",
            },
            provider: eth,
          },
        ];
      });
    }, 400);

    return () => {
      window.removeEventListener(
        "eip6963:announceProvider",
        onAnnounce as EventListener
      );
      window.clearTimeout(timer);
    };
  }, []);

  return providers;
}

export interface EvmSignedChallenge {
  address: string;
  message: string;
  signature: string;
}

/**
 * Request an account from a specific provider, fetch a server nonce, and
 * have the wallet sign it (EIP-191). Returns the address/message/signature
 * the link/login endpoints expect.
 */
export async function requestEvmSignature(
  provider: EthereumProvider
): Promise<EvmSignedChallenge> {
  const accounts = (await provider.request({
    method: "eth_requestAccounts",
  })) as string[];
  const address = accounts?.[0];
  if (!address) throw new Error("No account selected.");

  const nonceRes = await api.post<{ message: string }>("/auth/evm/nonce", {
    address,
  });
  const message = nonceRes.data.message;
  const signature = (await provider.request({
    method: "personal_sign",
    params: [message, address],
  })) as string;

  return { address, message, signature };
}
