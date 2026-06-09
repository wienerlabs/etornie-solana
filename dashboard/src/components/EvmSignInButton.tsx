"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import api, { extractErrorMessage } from "@/lib/api";
import { removeToken, setToken } from "@/lib/auth";
import {
  walletConnectConfigured,
  requestWalletConnectSignature,
} from "@/lib/evm/walletconnect";

const ROLE_LABELS: Record<string, string> = {
  admin: "Admin",
  client: "Client",
};

interface EvmSignInButtonProps {
  selectedRole: "admin" | "client";
  onError: (message: string) => void;
}

/**
 * EVM sign-in on the login page is WalletConnect-only: injected wallets
 * (MetaMask, Phantom, Rabby) already appear under the Solana "Sign in with
 * Wallet" picker, so listing them again here as separate EVM buttons just
 * duplicates names and confuses the choice. WalletConnect covers the
 * mobile/EVM path that the Solana picker does not.
 */
export function EvmSignInButton({ selectedRole, onError }: EvmSignInButtonProps) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  if (!walletConnectConfigured()) return null;

  async function signInWalletConnect() {
    onError("");
    setBusy(true);
    try {
      const signed = await requestWalletConnectSignature();
      const res = await api.post("/auth/evm/login", signed);
      const token = res.data.access_token as string;
      const payload = JSON.parse(atob(token.split(".")[1]));
      if (payload.role !== selectedRole) {
        removeToken();
        onError(
          `This wallet is linked to a ${ROLE_LABELS[payload.role] || payload.role} account. Please select the correct login type.`
        );
        return;
      }
      setToken(token, res.data.refresh_token);
      router.push("/dashboard");
    } catch (err) {
      onError(extractErrorMessage(err, "WalletConnect sign-in failed."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={signInWalletConnect}
        disabled={busy}
        className="flex w-full items-center justify-center gap-2 rounded-full border border-[color:var(--color-stone)] bg-white px-4 py-2.5 text-sm font-medium text-[color:var(--color-espresso)] transition-all hover:border-[color:var(--color-accent)] disabled:cursor-not-allowed disabled:opacity-70"
      >
        <span className="inline-block h-2 w-2 rounded-full bg-[#3b99fc]" aria-hidden="true" />
        {busy ? "Scan the QR code…" : "Sign in with WalletConnect"}
      </button>
    </div>
  );
}
