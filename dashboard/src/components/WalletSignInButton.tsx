"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import bs58 from "bs58";
import { useWallet } from "@solana/wallet-adapter-react";
import { useWalletModal } from "@solana/wallet-adapter-react-ui";
import api from "@/lib/api";
import { setToken } from "@/lib/auth";

interface NonceResponse {
  wallet_address: string;
  nonce: string;
  message: string;
  expires_at: string;
}

interface VerifyResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: {
    id: string;
    wallet_address: string | null;
    public_handle: string | null;
    role: string;
    auth_method: string;
    email: string | null;
    full_name: string;
  };
}

type Status =
  | { kind: "idle" }
  | { kind: "connecting" }
  | { kind: "requesting_nonce" }
  | { kind: "awaiting_signature" }
  | { kind: "verifying" }
  | { kind: "error"; message: string };

interface WalletSignInButtonProps {
  label?: string;
  role?: "client";
  fullName?: string;
  onSuccess?: (user: VerifyResponse["user"]) => void;
  className?: string;
}

export function WalletSignInButton({
  label = "Sign in with Wallet",
  role,
  fullName,
  onSuccess,
  className,
}: WalletSignInButtonProps) {
  const router = useRouter();
  const { publicKey, connected, connecting, signMessage, wallet, disconnect } =
    useWallet();
  const { setVisible } = useWalletModal();
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [mounted, setMounted] = useState(false);
  const inFlightRef = useRef(false);
  const initiatedRef = useRef(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const runSignInFlow = useCallback(async () => {
    if (inFlightRef.current) return;
    if (!publicKey) {
      setStatus({
        kind: "error",
        message: "Wallet disconnected before signing could start.",
      });
      return;
    }
    if (!signMessage) {
      setStatus({
        kind: "error",
        message:
          "This wallet does not expose signMessage. Try Phantom, Solflare, Backpack, or Glow.",
      });
      return;
    }

    inFlightRef.current = true;
    const walletAddress = publicKey.toBase58();

    try {
      setStatus({ kind: "requesting_nonce" });
      const nonceRes = await api.post<NonceResponse>("/auth/wallet/nonce", {
        wallet_address: walletAddress,
      });

      setStatus({ kind: "awaiting_signature" });
      const messageBytes = new TextEncoder().encode(nonceRes.data.message);
      const signatureBytes = await signMessage(messageBytes);
      const signatureB58 = bs58.encode(signatureBytes);

      setStatus({ kind: "verifying" });
      const verifyPayload: Record<string, unknown> = {
        wallet_address: walletAddress,
        message: nonceRes.data.message,
        signature: signatureB58,
      };
      if (role) verifyPayload.role = role;
      if (fullName) verifyPayload.full_name = fullName;
      const verifyRes = await api.post<VerifyResponse>(
        "/auth/wallet/verify",
        verifyPayload
      );

      setToken(verifyRes.data.access_token, verifyRes.data.refresh_token);
      setStatus({ kind: "idle" });

      if (onSuccess) {
        onSuccess(verifyRes.data.user);
        return;
      }
      router.push("/dashboard");
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ??
        (err as { message?: string })?.message ??
        "Wallet sign-in failed. Please try again.";
      setStatus({ kind: "error", message: detail });
    } finally {
      inFlightRef.current = false;
    }
  }, [publicKey, signMessage, router, onSuccess, role, fullName]);

  useEffect(() => {
    if (!connected || !publicKey || !initiatedRef.current) return;
    initiatedRef.current = false;
    void runSignInFlow();
  }, [connected, publicKey, runSignInFlow]);

  async function handleClick() {
    if (status.kind !== "idle" && status.kind !== "error") return;

    if (connected && publicKey) {
      await runSignInFlow();
      return;
    }

    initiatedRef.current = true;
    setStatus({ kind: "connecting" });
    setVisible(true);
  }

  const busy =
    (mounted && connecting) ||
    status.kind === "connecting" ||
    status.kind === "requesting_nonce" ||
    status.kind === "awaiting_signature" ||
    status.kind === "verifying";

  const walletName = mounted ? wallet?.adapter.name : undefined;
  const isConnected = mounted && connected;

  // Surface a "Continue with X" CTA once a wallet is selected.
  let buttonLabel: string;
  if (status.kind === "connecting" || (mounted && connecting)) {
    buttonLabel = walletName ? `Opening ${walletName}…` : "Opening wallet…";
  } else if (status.kind === "requesting_nonce") {
    buttonLabel = "Requesting nonce…";
  } else if (status.kind === "awaiting_signature") {
    buttonLabel = walletName
      ? `Sign request in ${walletName}…`
      : "Waiting for signature…";
  } else if (status.kind === "verifying") {
    buttonLabel = "Verifying signature…";
  } else if (isConnected && walletName) {
    buttonLabel = `Continue with ${walletName}`;
  } else {
    buttonLabel = label;
  }

  const errorMessage =
    status.kind === "error" ? status.message : undefined;

  async function handleCancel() {
    initiatedRef.current = false;
    if (connected) {
      try {
        await disconnect();
      } catch {
        // best-effort; ignore disconnect errors
      }
    }
    setStatus({ kind: "idle" });
  }

  return (
    <div className="w-full">
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className={
          className ??
          "flex w-full items-center justify-center gap-2 rounded-full border border-[color:var(--color-accent)] bg-[color:var(--color-accent)] px-4 py-2.5 text-sm font-medium text-[color:var(--color-paper-white)] transition-all hover:bg-[color:var(--color-accent-hover)] hover:border-[color:var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-70"
        }
      >
        <span
          className="inline-block h-2 w-2 rounded-full bg-current opacity-90"
          aria-hidden="true"
        />
        {buttonLabel}
      </button>
      {errorMessage && (
        <div
          role="alert"
          className="mt-2 rounded-lg border border-[color:var(--color-divider)] bg-[color:var(--color-paper-white)] p-2 text-xs text-[color:var(--color-inkwell)]"
        >
          {errorMessage}
        </div>
      )}
      {isConnected && (status.kind === "idle" || status.kind === "error") && (
        <button
          type="button"
          onClick={handleCancel}
          className="mt-1.5 text-xs text-[color:var(--color-dusk-gray)] hover:text-[color:var(--color-accent)] hover:underline"
        >
          Disconnect wallet
        </button>
      )}
    </div>
  );
}
