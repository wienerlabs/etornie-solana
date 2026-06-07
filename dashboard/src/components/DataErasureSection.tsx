"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import api, { extractErrorMessage } from "@/lib/api";
import { removeToken } from "@/lib/auth";

interface BlockingCase {
  id: string;
  case_number: string | null;
  title: string | null;
  status: string;
}

interface ErasureSummary {
  deleted_rows: Record<string, number>;
  deleted_files: number;
  retained_tables: string[];
}

interface DataErasureSectionProps {
  /** Auth method of the current user — drives whether a password is required. */
  authMethod: string;
}

const CONFIRM_PHRASE = "DELETE MY DATA";

export default function DataErasureSection({ authMethod }: DataErasureSectionProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [phrase, setPhrase] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blockers, setBlockers] = useState<BlockingCase[] | null>(null);
  const [done, setDone] = useState<ErasureSummary | null>(null);

  const needsPassword = authMethod !== "wallet";
  const canSubmit =
    phrase.trim().toUpperCase() === CONFIRM_PHRASE &&
    (!needsPassword || password.length > 0) &&
    !busy;

  async function submit() {
    setError(null);
    setBlockers(null);
    setBusy(true);
    try {
      const res = await api.post<ErasureSummary>("/users/me/erase", {
        password: needsPassword ? password : null,
      });
      setDone(res.data);
      // The account no longer exists in a usable form — drop tokens and
      // send the user to the login page after they read the summary.
      removeToken();
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response
        ?.status;
      const detail = (
        err as { response?: { data?: { detail?: unknown } } }
      )?.response?.data?.detail;
      if (
        status === 409 &&
        detail &&
        typeof detail === "object" &&
        "blocking_cases" in detail
      ) {
        setBlockers(
          (detail as { blocking_cases: BlockingCase[] }).blocking_cases
        );
      } else {
        setError(extractErrorMessage(err, "Could not erase your data."));
      }
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    const total = Object.values(done.deleted_rows).reduce((a, b) => a + b, 0);
    return (
      <section className="rounded-xl border border-red-300 bg-red-50 p-6">
        <h3 className="text-base font-semibold text-red-900">
          Your data has been erased
        </h3>
        <p className="mt-2 text-sm text-red-800">
          {total} record{total === 1 ? "" : "s"} and {done.deleted_files} file
          {done.deleted_files === 1 ? "" : "s"} were deleted. Records kept under
          legal-retention obligations (financial, on-chain, audit) were
          anonymised. Your account is now closed.
        </p>
        <button
          type="button"
          onClick={() => router.replace("/login")}
          className="rwa-btn-primary mt-4"
        >
          Return to sign in
        </button>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-red-300 bg-white p-6">
      <h3 className="text-base font-semibold text-red-900">
        Erase my data (GDPR Article 17)
      </h3>
      <p className="mt-2 text-sm text-[color:var(--color-muted)]">
        Permanently delete your personal data and close your account. This is
        irreversible. Records we are legally required to keep (payment/financial
        records, on-chain attestations, audit logs) are anonymised rather than
        deleted. You cannot erase your data while you have cases in active legal
        proceedings.
      </p>

      {blockers && (
        <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          <p className="font-semibold">
            Erasure is blocked by {blockers.length} active case
            {blockers.length === 1 ? "" : "s"}:
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {blockers.map((c) => (
              <li key={c.id}>
                {c.case_number ? `${c.case_number} — ` : ""}
                {c.title ?? "Untitled case"}{" "}
                <span className="text-amber-700">({c.status})</span>
              </li>
            ))}
          </ul>
          <p className="mt-2">
            These must be closed before your data can be erased.
          </p>
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="mt-4 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </div>
      )}

      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="mt-4 rounded-lg border border-red-400 px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-50"
        >
          Erase my data…
        </button>
      ) : (
        <div className="mt-4 space-y-3">
          <div>
            <label
              htmlFor="erase-phrase"
              className="block text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]"
            >
              Type <span className="font-mono text-red-700">{CONFIRM_PHRASE}</span> to confirm
            </label>
            <input
              id="erase-phrase"
              type="text"
              autoComplete="off"
              value={phrase}
              onChange={(e) => setPhrase(e.target.value)}
              className="rwa-input mt-1.5 w-full"
              placeholder={CONFIRM_PHRASE}
            />
          </div>

          {needsPassword && (
            <div>
              <label
                htmlFor="erase-password"
                className="block text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]"
              >
                Confirm your password
              </label>
              <input
                id="erase-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="rwa-input mt-1.5 w-full"
                placeholder="••••••••"
              />
            </div>
          )}

          <div className="flex gap-2">
            <button
              type="button"
              disabled={!canSubmit}
              onClick={submit}
              className="rounded-lg border border-red-500 bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "Erasing…" : "Permanently erase my data"}
            </button>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setPhrase("");
                setPassword("");
                setError(null);
              }}
              className="rounded-lg border border-[color:var(--color-stone)] px-4 py-2 text-sm font-semibold text-[color:var(--color-muted)] hover:bg-[color:var(--color-sand)]"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
