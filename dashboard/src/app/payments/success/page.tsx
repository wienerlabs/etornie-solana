"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { extractErrorMessage } from "@/lib/api";
import { reconcileStripeSession, type PaymentIntent } from "@/lib/payments/stripe";

const POLL_INTERVAL_MS = 1500;
const POLL_TIMEOUT_MS = 30_000;

function formatAmount(amount: string, currency: string): string {
  const numeric = Number(amount);
  if (!Number.isFinite(numeric)) {
    return `${amount} ${currency}`;
  }
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: currency.toUpperCase(),
    }).format(numeric);
  } catch {
    return `${numeric.toFixed(2)} ${currency.toUpperCase()}`;
  }
}

export default function StripeSuccessPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [intent, setIntent] = useState<PaymentIntent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stillWaiting, setStillWaiting] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id = params.get("session_id");
    if (!id) {
      setError(
        "Stripe did not include a session_id in the redirect. Open the chat to verify payment status."
      );
      return;
    }
    setSessionId(id);
  }, []);

  useEffect(() => {
    if (!sessionId) return;

    let cancelled = false;
    let timeoutHandle: ReturnType<typeof setTimeout> | null = null;
    const started = Date.now();

    const poll = async (): Promise<void> => {
      if (cancelled) return;
      try {
        const next = await reconcileStripeSession(sessionId);
        if (cancelled) return;
        setIntent(next);
        if (
          next.status === "confirmed" ||
          next.status === "failed" ||
          next.status === "expired"
        ) {
          return;
        }
        if (Date.now() - started > POLL_TIMEOUT_MS) {
          setStillWaiting(true);
          return;
        }
        timeoutHandle = setTimeout(poll, POLL_INTERVAL_MS);
      } catch (err: unknown) {
        if (cancelled) return;
        setError(extractErrorMessage(err, "Could not load payment status."));
      }
    };

    void poll();

    return () => {
      cancelled = true;
      if (timeoutHandle) clearTimeout(timeoutHandle);
    };
  }, [sessionId]);

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-center justify-center gap-6 px-6 py-12">
      <div className="w-full rounded-2xl border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] p-8 shadow-sm">
        {error && (
          <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-800">
            <p className="font-semibold">Payment status check failed</p>
            <p className="mt-1">{error}</p>
          </div>
        )}

        {!error && !intent && (
          <div className="flex flex-col items-center gap-3 text-center">
            <span className="inline-block h-3 w-3 animate-pulse rounded-full bg-[color:var(--color-bronze)]" />
            <p className="text-sm text-[color:var(--color-ink)]">
              Confirming your payment with Stripe…
            </p>
          </div>
        )}

        {intent?.status === "confirmed" && (
          <div className="flex flex-col items-center gap-2 text-center">
            <span className="text-2xl">✓</span>
            <p className="text-lg font-semibold text-[color:var(--color-ink)]">
              Payment received
            </p>
            <p className="text-sm text-[color:var(--color-muted)]">
              {formatAmount(intent.amount, intent.currency)} captured. Your
              filing draft can now be submitted.
            </p>
          </div>
        )}

        {intent && intent.status !== "confirmed" && !stillWaiting && (
          <div className="flex flex-col items-center gap-2 text-center">
            <span className="inline-block h-3 w-3 animate-pulse rounded-full bg-amber-500" />
            <p className="text-sm text-[color:var(--color-ink)]">
              Payment is being processed (current status:{" "}
              <span className="font-mono">{intent.status}</span>).
            </p>
          </div>
        )}

        {stillWaiting && intent && intent.status !== "confirmed" && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
            <p className="font-semibold">Still waiting on Stripe</p>
            <p className="mt-1">
              Stripe has not finalized this charge yet. This can happen with
              delayed-settlement payment methods (SEPA, bank debit). You will
              see the status update in the chat once it clears — you can
              safely close this page.
            </p>
          </div>
        )}

        <div className="mt-6 flex justify-center gap-3">
          <Link
            href="/dashboard/etorniegpt"
            className="rounded-md bg-[color:var(--color-bronze)] px-4 py-2 text-sm font-semibold text-[color:var(--color-cream)] hover:bg-[color:var(--color-bronze-dark)]"
          >
            Back to chat
          </Link>
          <Link
            href="/dashboard"
            className="rounded-md border border-[color:var(--color-stone)] px-4 py-2 text-sm font-semibold text-[color:var(--color-ink)] hover:bg-[color:var(--color-sand)]"
          >
            Dashboard
          </Link>
        </div>
      </div>
    </main>
  );
}
