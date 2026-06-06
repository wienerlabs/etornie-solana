"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import api from "@/lib/api";
import { removeToken, setToken } from "@/lib/auth";
import { WalletSignInButton } from "@/components/WalletSignInButton";

const ROLE_LABELS: Record<string, string> = {
  admin: "Admin",
  lawyer: "Lawyer",
  client: "Client",
};

type Role = "admin" | "client";

interface RoleOption {
  readonly key: Role;
  readonly label: string;
  readonly description: string;
  readonly icon: string;
}

const ROLE_OPTIONS: readonly RoleOption[] = [
  {
    key: "admin",
    label: "Admin",
    description: "Protocol control",
    icon: "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z",
  },
  {
    key: "client",
    label: "Client",
    description: "Asset owner",
    icon: "M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z",
  },
] as const;

export default function LoginPage() {
  const router = useRouter();
  const [selectedRole, setSelectedRole] = useState<Role>("client");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const activeOption = ROLE_OPTIONS.find((r) => r.key === selectedRole)!;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await api.post("/auth/login", { email, password });
      const token = res.data.access_token;

      const payload = JSON.parse(atob(token.split(".")[1]));
      if (payload.role !== selectedRole) {
        setError(
          `This account is registered as ${ROLE_LABELS[payload.role] || payload.role}. Please select the correct login type.`
        );
        return;
      }

      setToken(token, res.data.refresh_token);
      router.push("/dashboard");
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Login failed. Please try again.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex flex-col items-center gap-3">
          <Link
            href="/"
            className="text-xs font-medium uppercase tracking-widest text-[color:var(--color-muted)] hover:text-[color:var(--color-bronze)]"
          >
            ← Back to home
          </Link>
          <span className="chain-badge">
            <span className="chain-dot" />
            Powered by Solana · RWA
          </span>
          <Image
            src="/etornie-logo.png"
            alt="Etornie logo"
            width={64}
            height={64}
            priority
            className="h-16 w-16"
          />
          <h1 className="text-center text-3xl font-semibold tracking-tight text-[color:var(--color-espresso)]">
            Etornie
          </h1>
          <p className="text-center text-sm text-[color:var(--color-muted)]">
            Blockchain-backed IP & real-world-asset platform
          </p>
        </div>

        <div className="rwa-card p-7">
          <div className="mb-6 grid grid-cols-3 gap-2">
            {ROLE_OPTIONS.map((option) => {
              const isSelected = selectedRole === option.key;
              return (
                <button
                  key={option.key}
                  type="button"
                  onClick={() => setSelectedRole(option.key)}
                  className={`group flex flex-col items-center rounded-lg border p-3 transition-all ${
                    isSelected
                      ? "border-[color:var(--color-bronze)] bg-[color:var(--color-linen)] shadow-[0_6px_18px_-12px_rgba(139,106,63,0.5)]"
                      : "border-[color:var(--color-stone)] bg-[color:var(--color-cream)] hover:border-[color:var(--color-gold)] hover:bg-[color:var(--color-sand)]"
                  }`}
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    className={`mb-1.5 h-6 w-6 ${
                      isSelected
                        ? "text-[color:var(--color-bronze)]"
                        : "text-[color:var(--color-muted)]"
                    }`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={1.5}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d={option.icon}
                    />
                  </svg>
                  <span
                    className={`text-xs font-semibold ${
                      isSelected
                        ? "text-[color:var(--color-espresso)]"
                        : "text-[color:var(--color-muted)]"
                    }`}
                  >
                    {option.label}
                  </span>
                  <span className="mt-0.5 text-[10px] text-[color:var(--color-muted)]">
                    {option.description}
                  </span>
                </button>
              );
            })}
          </div>

          <h2 className="mb-4 text-center text-base font-medium text-[color:var(--color-espresso)]">
            {activeOption.label} Access
          </h2>

          {error && (
            <div
              role="alert"
              className="mb-4 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800"
            >
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="email"
                className="block text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]"
              >
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="rwa-input mt-1.5 w-full"
                placeholder="wallet@etornie.sol"
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="block text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]"
              >
                Password
              </label>
              <input
                id="password"
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="rwa-input mt-1.5 w-full"
                placeholder="••••••••"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="rwa-btn-primary w-full"
            >
              {loading ? "Signing in..." : "Sign In"}
            </button>
          </form>

          <div className="my-5 flex items-center gap-3">
            <span className="h-px flex-1 bg-[color:var(--color-stone)]" />
            <span className="text-[10px] font-semibold uppercase tracking-widest text-[color:var(--color-muted)]">
              or continue with Solana
            </span>
            <span className="h-px flex-1 bg-[color:var(--color-stone)]" />
          </div>

          {selectedRole === "admin" ? (
            <p className="text-center text-xs text-[color:var(--color-muted)]">
              Wallet sign-in is not available for Admin accounts.
            </p>
          ) : (
            <WalletSignInButton
              label="Sign in with Wallet"
              role={selectedRole}
              onSuccess={(user) => {
                if (user.role !== selectedRole) {
                  removeToken();
                  setError(
                    `This wallet is registered as ${ROLE_LABELS[user.role] || user.role}. Please select the correct login type.`
                  );
                  return;
                }
                router.push("/dashboard");
              }}
            />
          )}

          <p className="mt-5 text-center text-sm text-[color:var(--color-muted)]">
            Don&apos;t have an account?{" "}
            <Link
              href="/register"
              className="font-medium text-[color:var(--color-bronze)] hover:text-[color:var(--color-bronze-dark)] hover:underline"
            >
              Register
            </Link>
          </p>
        </div>

        <p className="mt-6 text-center text-[11px] text-[color:var(--color-muted)]">
          On-chain attestations · Tokenized IP · RWA custody
        </p>
        <p className="mt-2 text-center text-[11px] text-[color:var(--color-muted)]">
          <Link
            href="/legal/terms"
            className="hover:text-[color:var(--color-bronze)] hover:underline"
          >
            Terms of Service
          </Link>
        </p>
      </div>
    </div>
  );
}
