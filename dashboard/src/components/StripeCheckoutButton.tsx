"use client";

import { useState } from "react";

import { extractErrorMessage } from "@/lib/api";
import { createStripeCheckoutSession } from "@/lib/payments/stripe";

interface StripeCheckoutButtonProps {
  caseDraftId: string;
  platform: "EUIPO" | "WIPO" | "USPTO" | "UKIPO";
  amount: number | string;
  currency: string;
  className?: string;
}

function formatAmount(amount: number | string, currency: string): string {
  const numeric = typeof amount === "string" ? Number(amount) : amount;
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

export function StripeCheckoutButton({
  caseDraftId,
  platform,
  amount,
  currency,
  className,
}: StripeCheckoutButtonProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    setError(null);
    setLoading(true);
    try {
      const session = await createStripeCheckoutSession({
        caseDraftId,
        platform,
      });
      // Persist the payment_intent_id so the success page can refer to
      // it independently of the URL session_id (defence in depth).
      try {
        sessionStorage.setItem(
          `stripe_pi:${session.checkout_session_id}`,
          session.payment_intent_id
        );
      } catch {
        // sessionStorage may be unavailable (private mode); not critical.
      }
      window.location.assign(session.checkout_url);
    } catch (err: unknown) {
      setError(extractErrorMessage(err, "Could not start Stripe Checkout."));
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={handleClick}
        disabled={loading}
        className={
          className ??
          "rounded-md bg-[color:var(--color-ink)] px-3 py-1.5 text-xs font-semibold text-[color:var(--color-cream)] hover:bg-[color:var(--color-espresso)] disabled:bg-[color:var(--color-stone)] disabled:text-[color:var(--color-muted)]"
        }
      >
        {loading
          ? "Opening checkout…"
          : `Pay ${formatAmount(amount, currency)} with card`}
      </button>
      {error && (
        <p className="text-xs text-red-700" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
