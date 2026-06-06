"use client";

import { type ReactNode, useState } from "react";
import { WagmiProvider, createConfig, http } from "wagmi";
import { mainnet, sepolia } from "wagmi/chains";
import { injected, walletConnect } from "wagmi/connectors";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// WalletConnect needs a (free) Cloud project id. Without it we still
// support injected wallets (MetaMask, Rabby, and any EIP-6963 wallet);
// the WalletConnect connector is only added when the id is configured,
// so nothing is faked when it is absent.
const walletConnectProjectId =
  process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID?.trim();

const config = createConfig({
  chains: [mainnet, sepolia],
  connectors: [
    injected(),
    ...(walletConnectProjectId
      ? [
          walletConnect({
            projectId: walletConnectProjectId,
            metadata: {
              name: "Etornie",
              description: "Blockchain-backed IP & RWA platform",
              url: "https://etornie.com",
              icons: ["https://etornie.com/etornie-logo.png"],
            },
          }),
        ]
      : []),
  ],
  transports: {
    [mainnet.id]: http(),
    [sepolia.id]: http(),
  },
  // Wallet UI is client-only; skip SSR cookie hydration.
  ssr: false,
});

interface EvmWalletProviderProps {
  children: ReactNode;
}

export function EvmWalletProvider({ children }: EvmWalletProviderProps) {
  // One QueryClient per app instance.
  const [queryClient] = useState(() => new QueryClient());

  return (
    <WagmiProvider config={config}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </WagmiProvider>
  );
}
