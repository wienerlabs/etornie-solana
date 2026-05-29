"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import api, { extractErrorMessage } from "@/lib/api";

interface UpcomingRenewal {
  case_id: string;
  case_number: string;
  client_email: string | null;
  renewal_due_at: string;
  days_remaining: number;
  is_overdue: boolean;
}

interface AnalyticsSummary {
  cases_total: number;
  cases_open: number;
  cases_closed: number;
  filings_total: number;
  filings_successful: number;
  filings_failed: number;
  filing_success_rate: number | null;
  total_revenue_by_currency: Record<string, string>;
  total_refunded_by_currency: Record<string, string>;
  nft_states: Record<string, number>;
  upcoming_renewals: UpcomingRenewal[];
}

interface TimelineEvent {
  kind: string;
  case_id: string | null;
  case_number: string | null;
  client_email: string | null;
  occurred_at: string;
  summary: string;
  payload: Record<string, unknown>;
}

interface TimelineResponse {
  events: TimelineEvent[];
  total: number;
  page: number;
  page_size: number;
}

const KIND_LABEL: Record<string, string> = {
  case_created: "Case created",
  payment_confirmed: "Payment confirmed",
  payment_refunded: "Payment refunded",
  filing_submitted: "Filing submitted",
  filing_failed: "Filing failed",
  nft_minted: "NFT minted",
  renewal_completed: "Renewal completed",
  renewal_reminder_sent: "Renewal reminder",
};

const KIND_TONE: Record<string, string> = {
  case_created: "bg-gray-100 text-gray-700",
  payment_confirmed: "bg-emerald-100 text-emerald-700",
  payment_refunded: "bg-amber-100 text-amber-700",
  filing_submitted: "bg-emerald-100 text-emerald-700",
  filing_failed: "bg-red-100 text-red-700",
  nft_minted: "bg-indigo-100 text-indigo-700",
  renewal_completed: "bg-emerald-100 text-emerald-700",
  renewal_reminder_sent: "bg-amber-100 text-amber-700",
};

function StatCard({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "ok" | "warn" | "danger";
}) {
  const valueColor =
    tone === "ok"
      ? "text-emerald-700"
      : tone === "warn"
        ? "text-amber-700"
        : tone === "danger"
          ? "text-red-700"
          : "text-gray-900";
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
        {label}
      </p>
      <p className={`mt-1 text-2xl font-semibold ${valueColor}`}>{value}</p>
      {hint ? (
        <p className="mt-1 text-xs text-gray-500">{hint}</p>
      ) : null}
    </div>
  );
}

function MoneyList({
  title,
  values,
  tone,
}: {
  title: string;
  values: Record<string, string>;
  tone?: "ok" | "warn";
}) {
  const entries = Object.entries(values);
  const headColor = tone === "warn" ? "text-amber-700" : "text-gray-800";
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <p className={`mb-2 text-sm font-semibold ${headColor}`}>{title}</p>
      {entries.length === 0 ? (
        <p className="text-xs text-gray-400">None yet.</p>
      ) : (
        <ul className="space-y-1.5">
          {entries.map(([currency, amount]) => (
            <li
              key={currency}
              className="flex items-center justify-between text-sm text-gray-700"
            >
              <span>{currency.toUpperCase()}</span>
              <span className="font-mono text-sm">{amount}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function AdminAnalyticsPage() {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const pageSize = 25;

  const load = useCallback(async () => {
    setError(null);
    try {
      const [summaryRes, timelineRes] = await Promise.all([
        api.get<AnalyticsSummary>("/admin/analytics/summary"),
        api.get<TimelineResponse>("/admin/analytics/timeline", {
          params: { page, page_size: pageSize },
        }),
      ]);
      setSummary(summaryRes.data);
      setTimeline(timelineRes.data);
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  }, [page]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        {error}
      </div>
    );
  }
  if (!summary || !timeline) {
    return <div className="text-sm text-gray-500">Loading analytics…</div>;
  }

  const successRatePct =
    summary.filing_success_rate === null
      ? null
      : Math.round(summary.filing_success_rate * 100);

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Cases"
          value={summary.cases_total}
          hint={`${summary.cases_open} open · ${summary.cases_closed} closed`}
        />
        <StatCard
          label="Filings"
          value={summary.filings_total}
          hint={`${summary.filings_successful} ok · ${summary.filings_failed} failed`}
        />
        <StatCard
          label="Success rate"
          value={successRatePct === null ? "—" : `${successRatePct}%`}
          hint={
            successRatePct === null
              ? "No completed filings yet"
              : "submitted + accepted / completed"
          }
          tone={
            successRatePct === null
              ? undefined
              : successRatePct >= 80
                ? "ok"
                : successRatePct >= 50
                  ? "warn"
                  : "danger"
          }
        />
        <StatCard
          label="Upcoming renewals"
          value={summary.upcoming_renewals.length}
          hint="Within next 180 days"
          tone={
            summary.upcoming_renewals.some((r) => r.is_overdue)
              ? "danger"
              : summary.upcoming_renewals.length > 0
                ? "warn"
                : undefined
          }
        />
      </section>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <MoneyList
          title="Total revenue"
          values={summary.total_revenue_by_currency}
        />
        <MoneyList
          title="Total refunded"
          values={summary.total_refunded_by_currency}
          tone="warn"
        />
        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <p className="mb-2 text-sm font-semibold text-gray-800">
            NFT lifecycle
          </p>
          {Object.keys(summary.nft_states).length === 0 ? (
            <p className="text-xs text-gray-400">No NFTs yet.</p>
          ) : (
            <ul className="space-y-1.5">
              {Object.entries(summary.nft_states).map(([state, count]) => (
                <li
                  key={state}
                  className="flex items-center justify-between text-sm text-gray-700"
                >
                  <span className="capitalize">
                    {state.replace(/_/g, " ")}
                  </span>
                  <span className="font-mono text-xs">{count}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {summary.upcoming_renewals.length > 0 ? (
        <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold text-gray-800">
            Upcoming renewals
          </h2>
          <table className="min-w-full divide-y divide-gray-100 text-sm">
            <thead className="text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-2 py-1.5 text-left">Case</th>
                <th className="px-2 py-1.5 text-left">Client</th>
                <th className="px-2 py-1.5 text-left">Due</th>
                <th className="px-2 py-1.5 text-left">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {summary.upcoming_renewals.map((r) => (
                <tr key={r.case_id}>
                  <td className="px-2 py-1.5">
                    <Link
                      href={`/dashboard/cases/${r.case_id}`}
                      className="font-mono text-xs text-emerald-700 hover:underline"
                    >
                      {r.case_number}
                    </Link>
                  </td>
                  <td className="px-2 py-1.5 text-xs text-gray-700">
                    {r.client_email || "—"}
                  </td>
                  <td className="px-2 py-1.5 text-xs text-gray-700">
                    {new Date(r.renewal_due_at).toLocaleDateString()}
                  </td>
                  <td className="px-2 py-1.5 text-xs">
                    {r.is_overdue ? (
                      <span className="rounded-full bg-red-100 px-2 py-0.5 text-red-700">
                        Overdue
                      </span>
                    ) : r.days_remaining <= 30 ? (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-700">
                        {r.days_remaining}d
                      </span>
                    ) : (
                      <span className="rounded-full bg-gray-100 px-2 py-0.5 text-gray-700">
                        {r.days_remaining}d
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-800">
            Timeline
          </h2>
          <span className="text-xs text-gray-500">
            {timeline.total} events
          </span>
        </div>
        {timeline.events.length === 0 ? (
          <p className="py-8 text-center text-sm text-gray-400">
            No events yet.
          </p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {timeline.events.map((e, idx) => (
              <li
                key={`${e.kind}-${e.occurred_at}-${idx}`}
                className="flex items-start gap-3 py-2"
              >
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${KIND_TONE[e.kind] ?? "bg-gray-100 text-gray-700"}`}
                >
                  {KIND_LABEL[e.kind] ?? e.kind}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-gray-900">{e.summary}</p>
                  <p className="text-xs text-gray-500">
                    {new Date(e.occurred_at).toLocaleString()}
                    {e.client_email ? ` · ${e.client_email}` : ""}
                  </p>
                </div>
                {e.case_id ? (
                  <Link
                    href={`/dashboard/cases/${e.case_id}`}
                    className="shrink-0 text-xs text-emerald-700 hover:underline"
                  >
                    open case
                  </Link>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        {timeline.total > pageSize ? (
          <div className="mt-3 flex items-center justify-between text-xs text-gray-600">
            <span>
              Page {page + 1} of {Math.ceil(timeline.total / pageSize)}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPage(Math.max(0, page - 1))}
                disabled={page === 0}
                className="rounded border border-gray-200 px-2 py-1 hover:bg-gray-50 disabled:opacity-40"
              >
                Prev
              </button>
              <button
                type="button"
                onClick={() => setPage(page + 1)}
                disabled={(page + 1) * pageSize >= timeline.total}
                className="rounded border border-gray-200 px-2 py-1 hover:bg-gray-50 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
