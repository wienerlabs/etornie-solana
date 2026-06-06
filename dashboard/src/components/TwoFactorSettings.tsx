"use client";

import { useCallback, useEffect, useState } from "react";
import api, { extractErrorMessage } from "@/lib/api";

interface TwoFactorStatus {
  enabled: boolean;
  required: boolean;
  recovery_codes_remaining: number;
}

interface EnrollData {
  secret: string;
  otpauth_uri: string;
  qr_data_url: string;
}

interface TwoFactorSettingsProps {
  /** Called after enable/disable so the parent can refresh /auth/me. */
  onChanged?: () => void;
}

type Phase = "loading" | "idle" | "enrolling" | "showing_recovery";

export default function TwoFactorSettings({ onChanged }: TwoFactorSettingsProps) {
  const [status, setStatus] = useState<TwoFactorStatus | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [enroll, setEnroll] = useState<EnrollData | null>(null);
  const [code, setCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [disabling, setDisabling] = useState(false);
  const [disableCode, setDisableCode] = useState("");

  const loadStatus = useCallback(async () => {
    try {
      const res = await api.get<TwoFactorStatus>("/auth/2fa/status");
      setStatus(res.data);
      setPhase((prev) => (prev === "showing_recovery" ? prev : "idle"));
    } catch (err) {
      setError(extractErrorMessage(err, "Could not load two-factor status."));
      setPhase("idle");
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  async function startEnrollment() {
    setError(null);
    setBusy(true);
    try {
      const res = await api.post<EnrollData>("/auth/2fa/enroll");
      setEnroll(res.data);
      setCode("");
      setPhase("enrolling");
    } catch (err) {
      setError(extractErrorMessage(err, "Could not start enrollment."));
    } finally {
      setBusy(false);
    }
  }

  async function confirmEnable() {
    setError(null);
    setBusy(true);
    try {
      const res = await api.post<{ recovery_codes: string[] }>(
        "/auth/2fa/enable",
        { code: code.trim() }
      );
      setRecoveryCodes(res.data.recovery_codes);
      setEnroll(null);
      setCode("");
      setPhase("showing_recovery");
      await loadStatus();
      onChanged?.();
    } catch (err) {
      setError(extractErrorMessage(err, "Invalid code. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    setError(null);
    setBusy(true);
    try {
      await api.post("/auth/2fa/disable", { code: disableCode.trim() });
      setDisabling(false);
      setDisableCode("");
      await loadStatus();
      onChanged?.();
    } catch (err) {
      setError(extractErrorMessage(err, "Invalid code. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  function cancelEnrollment() {
    setEnroll(null);
    setCode("");
    setError(null);
    setPhase("idle");
  }

  function finishRecovery() {
    setRecoveryCodes([]);
    setPhase("idle");
  }

  const heading = (
    <div className="flex items-center justify-between">
      <h3 className="text-base font-semibold text-[color:var(--color-ink)]">
        Two-Factor Authentication
      </h3>
      {status?.enabled ? (
        <span className="rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-semibold text-green-800">
          Enabled
        </span>
      ) : (
        <span className="rounded-full bg-[color:var(--color-sand)] px-2.5 py-0.5 text-xs font-semibold text-[color:var(--color-muted)]">
          Disabled
        </span>
      )}
    </div>
  );

  return (
    <section className="rounded-xl border border-[color:var(--color-stone)] bg-white p-6">
      <div className="space-y-4">
        {heading}

        <p className="text-sm text-[color:var(--color-muted)]">
          Protect your account with a time-based one-time password (TOTP) from
          an authenticator app such as Google Authenticator, 1Password, or Authy.
        </p>

        {status?.required && !status.enabled && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            Two-factor authentication is required for admin accounts. Please set
            it up to secure your account.
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800"
          >
            {error}
          </div>
        )}

        {phase === "loading" && (
          <p className="text-sm text-[color:var(--color-muted)]">Loading…</p>
        )}

        {/* Already enabled — offer disable + recovery count */}
        {phase === "idle" && status?.enabled && (
          <div className="space-y-3">
            <p className="text-sm text-[color:var(--color-ink)]">
              {status.recovery_codes_remaining} recovery code
              {status.recovery_codes_remaining === 1 ? "" : "s"} remaining.
            </p>
            {!disabling ? (
              <button
                type="button"
                onClick={() => {
                  setDisabling(true);
                  setError(null);
                }}
                className="rounded-lg border border-red-300 px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-50"
              >
                Disable 2FA
              </button>
            ) : (
              <div className="space-y-2">
                <label
                  htmlFor="disable-code"
                  className="block text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]"
                >
                  Enter a current code or recovery code to confirm
                </label>
                <input
                  id="disable-code"
                  type="text"
                  inputMode="text"
                  autoComplete="one-time-code"
                  value={disableCode}
                  onChange={(e) => setDisableCode(e.target.value)}
                  className="rwa-input w-full"
                  placeholder="123 456"
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={busy || !disableCode.trim()}
                    onClick={disable}
                    className="rounded-lg border border-red-300 px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
                  >
                    {busy ? "Disabling…" : "Confirm Disable"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setDisabling(false);
                      setDisableCode("");
                      setError(null);
                    }}
                    className="rounded-lg border border-[color:var(--color-stone)] px-4 py-2 text-sm font-semibold text-[color:var(--color-muted)] hover:bg-[color:var(--color-sand)]"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Not enabled, not yet enrolling */}
        {phase === "idle" && !status?.enabled && (
          <button
            type="button"
            disabled={busy}
            onClick={startEnrollment}
            className="rwa-btn-primary"
          >
            {busy ? "Preparing…" : "Enable 2FA"}
          </button>
        )}

        {/* Enrollment: scan QR + confirm with a code */}
        {phase === "enrolling" && enroll && (
          <div className="space-y-4">
            <ol className="list-decimal space-y-2 pl-5 text-sm text-[color:var(--color-ink)]">
              <li>Scan this QR code with your authenticator app.</li>
              <li>Enter the 6-digit code it generates to confirm.</li>
            </ol>
            <div className="flex flex-col items-center gap-3">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={enroll.qr_data_url}
                alt="Two-factor QR code"
                width={180}
                height={180}
                className="rounded-lg border border-[color:var(--color-stone)] bg-white p-2"
              />
              <details className="w-full text-center">
                <summary className="cursor-pointer text-xs text-[color:var(--color-muted)]">
                  Can&apos;t scan? Enter this key manually
                </summary>
                <code className="mt-2 block break-all rounded bg-[color:var(--color-sand)] px-3 py-2 text-xs text-[color:var(--color-ink)]">
                  {enroll.secret}
                </code>
              </details>
            </div>
            <div>
              <label
                htmlFor="enable-code"
                className="block text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]"
              >
                Authentication code
              </label>
              <input
                id="enable-code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                className="rwa-input mt-1.5 w-full tracking-widest"
                placeholder="123 456"
              />
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={busy || !code.trim()}
                onClick={confirmEnable}
                className="rwa-btn-primary disabled:opacity-50"
              >
                {busy ? "Verifying…" : "Verify & Enable"}
              </button>
              <button
                type="button"
                onClick={cancelEnrollment}
                className="rounded-lg border border-[color:var(--color-stone)] px-4 py-2 text-sm font-semibold text-[color:var(--color-muted)] hover:bg-[color:var(--color-sand)]"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Recovery codes shown once */}
        {phase === "showing_recovery" && (
          <div className="space-y-3">
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              Save these recovery codes somewhere safe. Each can be used once if
              you lose access to your authenticator. They will not be shown again.
            </div>
            <ul className="grid grid-cols-2 gap-2">
              {recoveryCodes.map((rc) => (
                <li
                  key={rc}
                  className="rounded bg-[color:var(--color-sand)] px-3 py-2 text-center font-mono text-sm text-[color:var(--color-ink)]"
                >
                  {rc}
                </li>
              ))}
            </ul>
            <button
              type="button"
              onClick={finishRecovery}
              className="rwa-btn-primary"
            >
              I&apos;ve saved my recovery codes
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
