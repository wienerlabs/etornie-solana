"use client";

import { useState, useEffect, useCallback, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import api from "@/lib/api";

type Role = "admin" | "lawyer" | "client";

interface RoleOption {
  readonly key: Role;
  readonly label: string;
  readonly description: string;
  readonly color: string;
  readonly selectedBg: string;
  readonly selectedBorder: string;
  readonly icon: string;
}

const ROLE_OPTIONS: readonly RoleOption[] = [
  {
    key: "admin",
    label: "Admin",
    description: "Admin account",
    color: "text-red-700",
    selectedBg: "bg-red-50",
    selectedBorder: "border-red-500",
    icon: "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z",
  },
  {
    key: "lawyer",
    label: "Lawyer",
    description: "Lawyer account",
    color: "text-blue-700",
    selectedBg: "bg-blue-50",
    selectedBorder: "border-blue-500",
    icon: "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253",
  },
  {
    key: "client",
    label: "Client",
    description: "Client account",
    color: "text-green-700",
    selectedBg: "bg-green-50",
    selectedBorder: "border-green-500",
    icon: "M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z",
  },
] as const;

const CODE_EXPIRY_SECONDS = 10 * 60; // 10 minutes

export default function RegisterPage() {
  const router = useRouter();

  // Step tracking: "form" or "verify"
  const [step, setStep] = useState<"form" | "verify">("form");

  // Registration form state
  const [selectedRole, setSelectedRole] = useState<Role>("client");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Verification step state
  const [verificationCode, setVerificationCode] = useState("");
  const [countdown, setCountdown] = useState(CODE_EXPIRY_SECONDS);
  const [resending, setResending] = useState(false);

  const activeOption = ROLE_OPTIONS.find((r) => r.key === selectedRole)!;

  // Countdown timer for code expiry
  useEffect(() => {
    if (step !== "verify") return;

    if (countdown <= 0) return;

    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [step, countdown]);

  const formatCountdown = useCallback((seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  }, []);

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
      router.push("/?registered=true");
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

  // Step 2: Verification code input
  if (step === "verify") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="w-full max-w-md rounded-lg bg-white p-8 shadow-md">
          <h1 className="mb-2 text-center text-2xl font-bold text-gray-800">
            Email Verification
          </h1>

          <p className="mb-6 text-center text-sm text-gray-600">
            A verification code has been sent to{" "}
            <span className="font-medium text-gray-800">{email}</span>
          </p>

          {error && (
            <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <form onSubmit={handleVerify} className="space-y-6">
            <div>
              <label
                htmlFor="code"
                className="block text-center text-sm font-medium text-gray-700"
              >
                Verification Code
              </label>
              <input
                id="code"
                type="text"
                required
                maxLength={6}
                value={verificationCode}
                onChange={(e) => {
                  const val = e.target.value.replace(/\D/g, "");
                  setVerificationCode(val);
                }}
                className="mt-2 w-full rounded border border-gray-300 px-4 py-3 text-center font-mono text-2xl tracking-widest focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                placeholder="000000"
              />
            </div>

            <div className="text-center text-sm text-gray-500">
              {countdown > 0 ? (
                <span>
                  Code expires in:{" "}
                  <span className="font-medium text-gray-700">
                    {formatCountdown(countdown)}
                  </span>
                </span>
              ) : (
                <span className="text-red-600">
                  Code has expired. Please request a new code.
                </span>
              )}
            </div>

            <button
              type="submit"
              disabled={loading || verificationCode.length !== 6 || countdown <= 0}
              className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
            >
              {loading ? "Verifying..." : "Verify"}
            </button>
          </form>

          <div className="mt-4 text-center">
            <button
              type="button"
              onClick={handleResend}
              disabled={resending}
              className="text-sm text-blue-600 hover:underline disabled:opacity-50"
            >
              {resending ? "Sending..." : "Resend Code"}
            </button>
          </div>

          <div className="mt-4 text-center">
            <button
              type="button"
              onClick={() => {
                setStep("form");
                setVerificationCode("");
                setError("");
              }}
              className="text-sm text-gray-500 hover:underline"
            >
              Back to registration form
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Step 1: Registration form
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="w-full max-w-lg rounded-lg bg-white p-8 shadow-md">
        <h1 className="mb-6 text-center text-2xl font-bold text-gray-800">
          Etornie Platform
        </h1>

        <div className="mb-6 grid grid-cols-3 gap-3">
          {ROLE_OPTIONS.map((option) => {
            const isSelected = selectedRole === option.key;
            return (
              <button
                key={option.key}
                type="button"
                onClick={() => setSelectedRole(option.key)}
                className={`flex flex-col items-center rounded-lg border-2 p-4 transition-all ${
                  isSelected
                    ? `${option.selectedBorder} ${option.selectedBg}`
                    : "border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50"
                }`}
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className={`mb-2 h-8 w-8 ${isSelected ? option.color : "text-gray-400"}`}
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
                  className={`text-sm font-semibold ${isSelected ? option.color : "text-gray-600"}`}
                >
                  {option.label}
                </span>
                <span className="mt-1 text-xs text-gray-400">
                  {option.description}
                </span>
              </button>
            );
          })}
        </div>

        <h2
          className={`mb-4 text-center text-lg font-medium ${activeOption.color}`}
        >
          {activeOption.label} Registration
        </h2>

        {error && (
          <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleRegisterRequest} className="space-y-4">
          <div>
            <label
              htmlFor="fullName"
              className="block text-sm font-medium text-gray-700"
            >
              Full Name
            </label>
            <input
              id="fullName"
              type="text"
              required
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="Your full name"
            />
          </div>

          <div>
            <label
              htmlFor="email"
              className="block text-sm font-medium text-gray-700"
            >
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="example@email.com"
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="block text-sm font-medium text-gray-700"
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="At least 8 characters"
            />
          </div>

          <div>
            <label
              htmlFor="phone"
              className="block text-sm font-medium text-gray-700"
            >
              Phone (optional)
            </label>
            <input
              id="phone"
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="+90 555 123 4567"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
          >
            {loading ? "Registering..." : "Register"}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-gray-600">
          Already have an account?{" "}
          <Link href="/" className="text-blue-600 hover:underline">
            Sign In
          </Link>
        </p>
      </div>
    </div>
  );
}
