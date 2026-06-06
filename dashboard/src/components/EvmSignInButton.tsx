"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import api, { extractErrorMessage } from "@/lib/api";
import { removeToken, setToken } from "@/lib/auth";
import {
  useEvmProviders,
  requestEvmSignature,
  type Eip6963ProviderDetail,
} from "@/lib/evm/providers";

const ROLE_LABELS: Record<string, string> = {
  admin: "Admin",
  client: "Client",
};

interface EvmSignInButtonProps {
  selectedRole: "admin" | "client";
  onError: (message: string) => void;
}

export function EvmSignInButton({ selectedRole, onError }: EvmSignInButtonProps) {
  const router = useRouter();
  const providers = useEvmProviders();
  const [busy, setBusy] = useState<string | null>(null);

  async function signIn(detail: Eip6963ProviderDetail) {
    onError("");
    setBusy(detail.info.uuid);
    try {
      const signed = await requestEvmSignature(detail.provider);
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
      onError(extractErrorMessage(err, "EVM sign-in failed."));
    } finally {
      setBusy(null);
    }
  }

  if (providers.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {providers.map((p) => (
        <button
          key={p.info.uuid}
          type="button"
          onClick={() => signIn(p)}
          disabled={busy !== null}
          className="flex w-full items-center justify-center gap-2 rounded-full border border-[color:var(--color-stone)] bg-white px-4 py-2.5 text-sm font-medium text-[color:var(--color-espresso)] transition-all hover:border-[color:var(--color-accent)] disabled:cursor-not-allowed disabled:opacity-70"
        >
          {p.info.icon ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={p.info.icon} alt="" width={18} height={18} className="h-4 w-4" />
          ) : (
            <span className="inline-block h-2 w-2 rounded-full bg-[color:var(--color-accent)]" aria-hidden="true" />
          )}
          {busy === p.info.uuid ? "Check your wallet…" : `Sign in with ${p.info.name}`}
        </button>
      ))}
    </div>
  );
}
