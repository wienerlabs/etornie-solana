"use client";

import { useMemo } from "react";
import {
  ConnectionProvider,
  WalletProvider,
} from "@solana/wallet-adapter-react";
import { WalletModalProvider } from "@solana/wallet-adapter-react-ui";
import { PhantomWalletAdapter } from "@solana/wallet-adapter-phantom";
import { SolflareWalletAdapter } from "@solana/wallet-adapter-solflare";
import { clusterApiUrl, type Cluster } from "@solana/web3.js";

import "@solana/wallet-adapter-react-ui/styles.css";

type SolanaCluster = Cluster;

function resolveEndpoint(): string {
  const explicit = process.env.NEXT_PUBLIC_SOLANA_RPC_URL;
  if (explicit && explicit.length > 0) {
    return explicit;
  }
  const networkRaw = (
    process.env.NEXT_PUBLIC_SOLANA_CLUSTER ?? "devnet"
  ).toLowerCase();
  const allowed: readonly SolanaCluster[] = ["devnet", "testnet", "mainnet-beta"];
  const network = (allowed as readonly string[]).includes(networkRaw)
    ? (networkRaw as SolanaCluster)
    : "devnet";
  return clusterApiUrl(network);
}

interface WalletContextProviderProps {
  children: React.ReactNode;
}

export function WalletContextProvider({ children }: WalletContextProviderProps) {
  const endpoint = useMemo(resolveEndpoint, []);
  const wallets = useMemo(
    () => [new PhantomWalletAdapter(), new SolflareWalletAdapter()],
    []
  );

  return (
    <ConnectionProvider endpoint={endpoint}>
      <WalletProvider wallets={wallets} autoConnect>
        <WalletModalProvider>{children}</WalletModalProvider>
      </WalletProvider>
    </ConnectionProvider>
  );
}
