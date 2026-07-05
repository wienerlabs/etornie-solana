"use client";

import { useMemo } from "react";
import {
  ConnectionProvider,
  WalletProvider,
} from "@solana/wallet-adapter-react";
import { WalletModalProvider } from "@solana/wallet-adapter-react-ui";
import type { Adapter } from "@solana/wallet-adapter-base";
import { clusterApiUrl } from "@solana/web3.js";

import "@solana/wallet-adapter-react-ui/styles.css";

import { env } from "@/lib/env";

function resolveEndpoint(): string {
  const explicit = process.env.NEXT_PUBLIC_SOLANA_RPC_URL;
  if (explicit && explicit.length > 0) {
    return explicit;
  }
  return clusterApiUrl(env.solanaCluster);
}

interface WalletContextProviderProps {
  children: React.ReactNode;
}

// Modern wallets (Phantom, Solflare, Backpack, Glow, Coinbase, Trust, etc.)
// register themselves through the Wallet Standard protocol when their browser
// extension is installed. WalletProvider auto-discovers them, so we keep the
// explicit adapter array empty — that silences the "can be removed from your
// app" warnings and keeps the bundle tree-shaken.
//
// If you ever need to support a wallet that does NOT speak Wallet Standard,
// add its adapter here, e.g.
//   import { LedgerWalletAdapter } from "@solana/wallet-adapter-wallets";
//   const wallets = useMemo<Adapter[]>(() => [new LedgerWalletAdapter()], []);
export function WalletContextProvider({ children }: WalletContextProviderProps) {
  const endpoint = useMemo(() => resolveEndpoint(), []);
  const wallets = useMemo<Adapter[]>(() => [], []);

  return (
    <ConnectionProvider endpoint={endpoint}>
      <WalletProvider wallets={wallets} autoConnect>
        <WalletModalProvider>{children}</WalletModalProvider>
      </WalletProvider>
    </ConnectionProvider>
  );
}
