"use client";

import { useState, useEffect, useCallback, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import api from "@/lib/api";
import { WalletSignInButton } from "@/components/WalletSignInButton";

type Role = "lawyer" | "client";

interface RoleOption {
  readonly key: Role;
  readonly label: string;
  readonly description: string;
  readonly icon: string;
}

const ROLE_OPTIONS: readonly RoleOption[] = [
  {
    key: "lawyer",
    label: "Lawyer",
    description: "Represent clients and manage IP cases. Requires verification.",
    icon: "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253",
  },
  {
    key: "client",
    label: "Client",
    description: "Own and follow your IP portfolio.",
    icon: "M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z",
  },
] as const;

const CODE_EXPIRY_SECONDS = 10 * 60;

function formatCountdown(secs: number): string {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

export default function RegisterPage() {
  const router = useRouter();

  const [step, setStep] = useState<"form" | "verify">("form");

  const [selectedRole, setSelectedRole] = useState<Role>("client");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [barAssociation, setBarAssociation] = useState("");
  const [barNumber, setBarNumber] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const [verificationCode, setVerificationCode] = useState("");
  const [countdown, setCountdown] = useState(CODE_EXPIRY_SECONDS);
  const [resending, setResending] = useState(false);

  const activeOption = ROLE_OPTIONS.find((r) => r.key === selectedRole)!;
  const showBarFields = selectedRole === "lawyer";

  useEffect(() => {
    if (step !== "verify") return;
    if (countdown <= 0) return;
    const t = setInterval(() => setCountdown((c) => c - 1), 1000);
    return () => clearInterval(t);
  }, [step, countdown]);

  const buildLawyerFields = useCallback(
    () =>
      showBarFields
        ? {
            bar_association: barAssociation || null,
            bar_number: barNumber || null,
          }
        : {},
    [showBarFields, barAssociation, barNumber]
  );

  async function handleRegisterRequest(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      await api.post("/auth/register/request", {
        email,
        password,
        full_name: fullName,
        phone: phone || null,
        role: selectedRole,
        ...buildLawyerFields(),
      });
      setStep("verify");
      setCountdown(CODE_EXPIRY_SECONDS);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Registration failed. Please try again.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  async function handleVerify(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      await api.post("/auth/register/verify", {
        email,
        code: verificationCode,
      });
      router.push("/login?registered=true");
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Verification failed. Please try again.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  async function handleResend() {
    setError("");
    setResending(true);
    try {
      await api.post("/auth/register/request", {
        email,
        password,
        full_name: fullName,
        phone: phone || null,
        role: selectedRole,
        ...buildLawyerFields(),
      });
      setCountdown(CODE_EXPIRY_SECONDS);
      setVerificationCode("");
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to send code. Please try again.";
      setError(message);
    } finally {
      setResending(false);
    }
  }

  if (step === "verify") {
    return (
      <div className="flex min-h-screen items-center justify-center px-4 py-10">
        <div className="rwa-card w-full max-w-md p-7">
          <h1 className="mb-2 text-center text-2xl font-semibold tracking-tight text-[color:var(--color-espresso)]">
            Email Verification
          </h1>
          <p className="mb-6 text-center text-sm text-[color:var(--color-muted)]">
            A verification code has been sent to{" "}
            <span className="font-medium text-[color:var(--color-espresso)]">
              {email}
            </span>
          </p>

          {error && (
            <div
              role="alert"
              className="mb-4 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800"
            >
              {error}
            </div>
          )}

          <form onSubmit={handleVerify} className="space-y-5">
            <div>
              <label
                htmlFor="code"
                className="block text-center text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]"
              >
                Verification Code
              </label>
              <input
                id="code"
                type="text"
                required
                maxLength={6}
                value={verificationCode}
                onChange={(e) =>
                  setVerificationCode(e.target.value.replace(/\D/g, ""))
                }
                className="rwa-input mt-2 w-full text-center font-mono text-2xl tracking-widest"
                placeholder="000000"
              />
            </div>

            <div className="text-center text-sm text-[color:var(--color-muted)]">
              {countdown > 0 ? (
                <span>
                  Code expires in:{" "}
                  <span className="font-medium text-[color:var(--color-espresso)]">
                    {formatCountdown(countdown)}
                  </span>
                </span>
              ) : (
                <button
                  type="button"
                  onClick={handleResend}
                  disabled={resending}
                  className="text-[color:var(--color-bronze)] hover:text-[color:var(--color-bronze-dark)] hover:underline disabled:opacity-50"
                >
                  {resending ? "Resending..." : "Resend code"}
                </button>
              )}
            </div>

            <button
              type="submit"
              disabled={loading || verificationCode.length !== 6}
              className="rwa-btn-primary w-full"
            >
              {loading ? "Verifying..." : "Verify and Register"}
            </button>
          </form>

          <p className="mt-5 text-center text-sm text-[color:var(--color-muted)]">
            <button
              type="button"
              onClick={() => {
                setStep("form");
                setVerificationCode("");
                setError("");
              }}
              className="text-[color:var(--color-bronze)] hover:underline"
            >
              Back to form
            </button>
          </p>
        </div>
      </div>
    );
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
            Create an account
          </span>
          <h1 className="text-center text-3xl font-semibold tracking-tight text-[color:var(--color-espresso)]">
            Register on <span className="text-[color:var(--color-bronze)]">Etornie Solana</span>
          </h1>
          <p className="text-center text-sm text-[color:var(--color-muted)]">
            Pick your role, then continue with email or a Solana wallet.
          </p>
        </div>

        <div className="rwa-card p-7">
          <div className="mb-5 grid grid-cols-2 gap-3">
            {ROLE_OPTIONS.map((option) => {
              const isSelected = selectedRole === option.key;
              return (
                <button
                  key={option.key}
                  type="button"
                  onClick={() => setSelectedRole(option.key)}
                  className={`flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-all ${
                    isSelected
                      ? "border-[color:var(--color-bronze)] bg-[color:var(--color-linen)] shadow-[0_6px_18px_-12px_rgba(139,106,63,0.5)]"
                      : "border-[color:var(--color-stone)] bg-[color:var(--color-cream)] hover:border-[color:var(--color-gold)] hover:bg-[color:var(--color-sand)]"
                  }`}
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    className={`mb-1 h-5 w-5 ${
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
                    className={`text-sm font-semibold ${
                      isSelected
                        ? "text-[color:var(--color-espresso)]"
                        : "text-[color:var(--color-muted)]"
                    }`}
                  >
                    {option.label}
                  </span>
                  <span className="text-[11px] text-[color:var(--color-muted)]">
                    {option.description}
                  </span>
                </button>
              );
            })}
          </div>

          {showBarFields && (
            <div className="mb-5 rounded-lg border border-[color:var(--color-gold)]/40 bg-[color:var(--color-sand)]/60 p-3 text-[11px] text-[color:var(--color-bronze-dark)]">
              Lawyer accounts are created in a pending state until an admin
              reviews the bar credentials below. You can sign in immediately,
              but full lawyer privileges unlock after verification.
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="mb-4 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800"
            >
              {error}
            </div>
          )}

          <form onSubmit={handleRegisterRequest} className="space-y-4">
            <div>
              <label
                htmlFor="fullName"
                className="block text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]"
              >
                Full Name
              </label>
              <input
                id="fullName"
                type="text"
                required
                autoComplete="name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="rwa-input mt-1.5 w-full"
                placeholder="Jane Doe"
              />
            </div>

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
                placeholder="name@example.com"
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
                minLength={8}
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="rwa-input mt-1.5 w-full"
                placeholder="At least 8 characters"
              />
            </div>

            <div>
              <label
                htmlFor="phone"
                className="block text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]"
              >
                Phone (optional)
              </label>
              <input
                id="phone"
                type="tel"
                autoComplete="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className="rwa-input mt-1.5 w-full"
                placeholder="+90 555 123 4567"
              />
            </div>

            {showBarFields && (
              <>
                <div>
                  <label
                    htmlFor="barAssociation"
                    className="block text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]"
                  >
                    Bar Association
                  </label>
                  <input
                    id="barAssociation"
                    type="text"
                    required
                    value={barAssociation}
                    onChange={(e) => setBarAssociation(e.target.value)}
                    className="rwa-input mt-1.5 w-full"
                    placeholder="Istanbul Barosu"
                  />
                </div>
                <div>
                  <label
                    htmlFor="barNumber"
                    className="block text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]"
                  >
                    Bar Number
                  </label>
                  <input
                    id="barNumber"
                    type="text"
                    required
                    value={barNumber}
                    onChange={(e) => setBarNumber(e.target.value)}
                    className="rwa-input mt-1.5 w-full"
                    placeholder="IST-12345"
                  />
                </div>
              </>
            )}

            <button
              type="submit"
              disabled={loading}
              className="rwa-btn-primary w-full"
            >
              {loading
                ? "Sending verification code..."
                : `Register as ${activeOption.label}`}
            </button>
          </form>

          <div className="my-5 flex items-center gap-3">
            <span className="h-px flex-1 bg-[color:var(--color-stone)]" />
            <span className="text-[10px] font-semibold uppercase tracking-widest text-[color:var(--color-muted)]">
              or register with Solana
            </span>
            <span className="h-px flex-1 bg-[color:var(--color-stone)]" />
          </div>

          <WalletSignInButton
            label={`Register with Wallet as ${activeOption.label}`}
            role={selectedRole}
            fullName={fullName || undefined}
            barAssociation={showBarFields ? barAssociation || undefined : undefined}
            barNumber={showBarFields ? barNumber || undefined : undefined}
          />

          {showBarFields && (
            <p className="mt-2 text-[11px] text-[color:var(--color-muted)]">
              Bar association and bar number must be filled above before
              registering with a wallet. Admin verification is required after
              sign-up.
            </p>
          )}

          <p className="mt-5 text-center text-sm text-[color:var(--color-muted)]">
            Already have an account?{" "}
            <Link
              href="/login"
              className="font-medium text-[color:var(--color-bronze)] hover:text-[color:var(--color-bronze-dark)] hover:underline"
            >
              Sign In
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
