"use client";

import {
  requestEvmSignature,
  type EthereumProvider,
  type EvmSignedChallenge,
} from "./providers";

const PROJECT_ID = process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID;

// Moca Chain testnet — mirrors services/api/app/config.py (moca_chain_id).
const MOCA_CHAIN_ID = Number(process.env.NEXT_PUBLIC_MOCA_CHAIN_ID ?? 222888);

/**
 * WalletConnect v2 needs a WalletConnect Cloud project id to reach the
 * relay; without one the QR pairing cannot work at all. The option is
 * therefore hidden when it is not configured rather than shown as a
 * dead button.
 */
export function walletConnectConfigured(): boolean {
  return Boolean(PROJECT_ID);
}

/**
 * Open a WalletConnect v2 session (QR modal — for mobile wallets such as
 * MetaMask mobile, Rainbow, Trust, and any WalletConnect-capable wallet)
 * and return a provider that speaks the same `request()` interface as the
 * injected EIP-6963 providers, so the rest of the sign/link flow is shared.
 *
 * The package is imported dynamically so its relay + modal dependency tree
 * is code-split into its own chunk and never ships in the main bundle — it
 * loads only when the user actually picks WalletConnect.
 */
async function createWalletConnectProvider(): Promise<{
  provider: EthereumProvider;
  disconnect: () => Promise<void>;
}> {
  if (!PROJECT_ID) {
    throw new Error("WalletConnect is not configured.");
  }

  const { EthereumProvider } = await import("@walletconnect/ethereum-provider");
  const origin =
    typeof window !== "undefined" ? window.location.origin : "https://etornie.com";

  const wc = await EthereumProvider.init({
    projectId: PROJECT_ID,
    // Mainnet is required because every EVM wallet supports it and the
    // challenge we sign is off-chain (EIP-191), so the active chain is
    // irrelevant; Moca testnet is offered as an optional chain for wallets
    // that have it.
    chains: [1],
    optionalChains: [1, MOCA_CHAIN_ID],
    showQrModal: true,
    metadata: {
      name: "Etornie",
      description: "Blockchain-backed IP & real-world-asset platform",
      url: origin,
      icons: [`${origin}/etornie-logo.png`],
    },
  });

  if (!wc.session) {
    // Opens the QR modal and resolves once a wallet pairs over the relay.
    await wc.connect();
  }

  return {
    provider: wc as unknown as EthereumProvider,
    disconnect: async () => {
      try {
        await wc.disconnect();
      } catch {
        // A failed teardown must never mask an already-obtained signature.
      }
    },
  };
}

/**
 * Full WalletConnect challenge flow: pair over the relay, sign the
 * server-issued nonce (EIP-191), then tear the session down — we only need
 * the one-shot off-chain signature, not a standing connection.
 */
export async function requestWalletConnectSignature(): Promise<EvmSignedChallenge> {
  const { provider, disconnect } = await createWalletConnectProvider();
  try {
    return await requestEvmSignature(provider);
  } finally {
    await disconnect();
  }
}
