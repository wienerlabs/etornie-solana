"use client";

import { useCallback, useEffect, useState } from "react";

import api, { extractErrorMessage } from "@/lib/api";

interface ReminderRow {
  window_days: number;
  target_due_at: string;
  sent_at: string;
  channels: string[];
}

interface RenewalStatus {
  case_id: string;
  renewal_due_at: string | null;
  last_renewed_at: string | null;
  days_remaining: number | null;
  open_window_days: number | null;
  is_overdue: boolean;
  reminders: ReminderRow[];
}

interface CheckoutResponse {
  checkout_url: string;
  amount: string;
  currency: string;
}

interface RenewalCardProps {
  caseId: string;
}

function statusTone(status: RenewalStatus): {
  border: string;
  badgeBg: string;
  badgeText: string;
  label: string;
} {
  if (status.renewal_due_at === null) {
    return {
      border: "border-gray-200",
      badgeBg: "bg-gray-100",
      badgeText: "text-gray-600",
      label: "No renewal date",
    };
  }
  if (status.is_overdue) {
    return {
      border: "border-red-300",
      badgeBg: "bg-red-100",
      badgeText: "text-red-700",
      label: "Overdue",
    };
  }
  if (status.open_window_days !== null && status.open_window_days <= 30) {
    return {
      border: "border-amber-300",
      badgeBg: "bg-amber-100",
      badgeText: "text-amber-700",
      label: `Renew within ${status.days_remaining ?? 0}d`,
    };
  }
  if (status.open_window_days !== null) {
    return {
      border: "border-emerald-200",
      badgeBg: "bg-emerald-100",
      badgeText: "text-emerald-700",
      label: `Window open · ${status.days_remaining ?? 0}d left`,
    };
  }
  return {
    border: "border-gray-200",
    badgeBg: "bg-gray-100",
    badgeText: "text-gray-600",
    label: `${status.days_remaining ?? 0}d until renewal`,
  };
}

export function RenewalCard({ caseId }: RenewalCardProps) {
  const [status, setStatus] = useState<RenewalStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [redirecting, setRedirecting] = useState(false);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const res = await api.get<RenewalStatus>(
        `/cases/${caseId}/renewal-status`
      );
      setStatus(res.data);
    } catch (err) {
      setLoadError(extractErrorMessage(err));
    }
  }, [caseId]);

  useEffect(() => {
    load();
  }, [load]);

  const onRenew = async () => {
    setActionError(null);
    setRedirecting(true);
    try {
      const res = await api.post<CheckoutResponse>(
        `/cases/${caseId}/renew/checkout`
      );
      window.location.href = res.data.checkout_url;
    } catch (err) {
      setActionError(extractErrorMessage(err));
      setRedirecting(false);
    }
  };

  if (loadError) {
    return (
      <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Renewal status unavailable: {loadError}
      </div>
    );
  }
  if (status === null) {
    return (
      <div className="mb-6 rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-500">
        Loading renewal status…
      </div>
    );
  }
  if (status.renewal_due_at === null) {
    // Case has no due date yet (typically pre-filing). Hide the card
    // so the page does not show a dead tile.
    return null;
  }

  const tone = statusTone(status);
  const showRenewButton =
    status.is_overdue ||
    (status.open_window_days !== null && status.open_window_days <= 90);

  return (
    <div
      className={`mb-6 rounded-lg border ${tone.border} bg-white p-6 shadow-sm`}
    >
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-800">
          Renewal
        </h2>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${tone.badgeBg} ${tone.badgeText}`}
        >
          {tone.label}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
            Protection until
          </p>
          <p className="mt-1 font-mono text-sm text-gray-900">
            {new Date(status.renewal_due_at).toLocaleDateString()}
          </p>
        </div>
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
            Days remaining
          </p>
          <p className="mt-1 font-mono text-sm text-gray-900">
            {status.days_remaining}
          </p>
        </div>
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
            Last renewed
          </p>
          <p className="mt-1 font-mono text-sm text-gray-900">
            {status.last_renewed_at
              ? new Date(status.last_renewed_at).toLocaleDateString()
              : "—"}
          </p>
        </div>
      </div>

      {showRenewButton ? (
        <div className="mt-4 flex flex-col gap-2">
          <button
            type="button"
            onClick={onRenew}
            disabled={redirecting}
            className="self-start rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            {redirecting
              ? "Redirecting to Stripe…"
              : status.is_overdue
                ? "Renew now (overdue)"
                : "Renew now"}
          </button>
          {actionError ? (
            <p className="text-xs text-red-700">{actionError}</p>
          ) : null}
        </div>
      ) : null}

      {status.reminders.length > 0 ? (
        <details className="mt-4 text-xs">
          <summary className="cursor-pointer text-gray-600">
            Reminder history ({status.reminders.length})
          </summary>
          <ul className="mt-2 space-y-1 text-gray-600">
            {status.reminders.map((r, idx) => (
              <li
                key={`${r.window_days}-${r.sent_at}-${idx}`}
                className="flex justify-between border-b border-gray-100 pb-1"
              >
                <span>
                  {r.window_days === 0
                    ? "Overdue alert"
                    : `${r.window_days}-day reminder`}{" "}
                  · {r.channels.join(", ")}
                </span>
                <span className="text-gray-500">
                  {new Date(r.sent_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

export default RenewalCard;
