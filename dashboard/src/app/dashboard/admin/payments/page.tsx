"use client";

import { useCallback, useEffect, useState } from "react";

import api, { extractErrorMessage } from "@/lib/api";

interface PaymentRow {
  id: string;
  user_email: string | null;
  user_full_name: string | null;
  provider: string;
  payment_type: string;
  status: string;
  amount: string;
  currency: string;
  gateway_payment_id: string | null;
  filing_external_reference: string | null;
  filing_status: string | null;
  filing_error: string | null;
  case_id: string | null;
  case_number: string | null;
  compliance_onchain_tx: string | null;
  refund_id: string | null;
  refund_amount: string | null;
  refund_status: string | null;
  auto_submit_committed_at: string | null;
  created_at: string;
  confirmed_at: string | null;
}

interface ListResponse {
  items: PaymentRow[];
  total: number;
  page: number;
  page_size: number;
}

const STATUS_FILTERS: ReadonlyArray<{ label: string; value: string }> = [
  { label: "All", value: "" },
  { label: "Created", value: "created" },
  { label: "Awaiting", value: "awaiting" },
  { label: "Confirmed", value: "confirmed" },
  { label: "Failed", value: "failed" },
  { label: "Expired", value: "expired" },
  { label: "Refunded", value: "refunded" },
];

function StatusBadge({ value }: { value: string }) {
  const color =
    value === "confirmed"
      ? "bg-emerald-100 text-emerald-700"
      : value === "refunded"
        ? "bg-amber-100 text-amber-700"
        : value === "failed" || value === "expired"
          ? "bg-red-100 text-red-700"
          : "bg-gray-100 text-gray-700";
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${color}`}
    >
      {value}
    </span>
  );
}

export default function AdminPaymentsPage() {
  const [data, setData] = useState<ListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [page, setPage] = useState(0);
  const [pageSize] = useState(25);
  const [refundingId, setRefundingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const params: Record<string, string | number> = { page, page_size: pageSize };
      if (statusFilter) params.status = statusFilter;
      const res = await api.get<ListResponse>("/admin/payments", { params });
      setData(res.data);
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  }, [page, pageSize, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const onRefund = async (intentId: string) => {
    const reason = window.prompt(
      "Refund reason (logged on Stripe + audit trail):",
      "Manual refund from admin panel"
    );
    if (!reason) return;
    setRefundingId(intentId);
    try {
      await api.post(`/admin/payments/${intentId}/refund`, { reason });
      await load();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setRefundingId(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.label}
            type="button"
            onClick={() => {
              setPage(0);
              setStatusFilter(f.value);
            }}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${
              statusFilter === f.value
                ? "bg-gray-900 text-white"
                : "bg-white text-gray-700 hover:bg-gray-50 border border-gray-200"
            }`}
          >
            {f.label}
          </button>
        ))}
        <span className="ml-auto text-xs text-gray-500">
          {data ? `${data.total} payments` : "Loading…"}
        </span>
      </div>

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-4 py-2 text-left">Status</th>
              <th className="px-4 py-2 text-left">User</th>
              <th className="px-4 py-2 text-left">Amount</th>
              <th className="px-4 py-2 text-left">Provider</th>
              <th className="px-4 py-2 text-left">Case</th>
              <th className="px-4 py-2 text-left">Filing</th>
              <th className="px-4 py-2 text-left">Created</th>
              <th className="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data?.items.map((row) => {
              const canRefund =
                row.status === "confirmed" && !row.refund_id;
              return (
                <tr key={row.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2">
                    <StatusBadge value={row.status} />
                    {row.refund_status ? (
                      <span className="ml-1 text-xs text-amber-700">
                        ({row.refund_status})
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-2">
                    <div className="text-gray-900">
                      {row.user_full_name || row.user_email || "—"}
                    </div>
                    {row.user_email ? (
                      <div className="text-xs text-gray-500">
                        {row.user_email}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-gray-700">
                    {row.amount} {row.currency.toUpperCase()}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-600">
                    {row.provider}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-700">
                    {row.case_id ? (
                      <a
                        href={`/dashboard/cases/${row.case_id}`}
                        className="text-emerald-700 underline-offset-2 hover:underline"
                      >
                        {row.case_number || row.case_id.slice(0, 8)}
                      </a>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-2 text-xs">
                    {row.filing_external_reference ? (
                      <span className="text-emerald-700">
                        {row.filing_external_reference}
                      </span>
                    ) : row.filing_error ? (
                      <span
                        className="text-red-700"
                        title={row.filing_error}
                      >
                        Failed
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-500">
                    {new Date(row.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {canRefund ? (
                      <button
                        type="button"
                        onClick={() => onRefund(row.id)}
                        disabled={refundingId === row.id}
                        className="rounded-md border border-amber-300 bg-white px-2.5 py-1 text-xs font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-50"
                      >
                        {refundingId === row.id ? "Refunding…" : "Refund"}
                      </button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
            {data && data.items.length === 0 ? (
              <tr>
                <td
                  colSpan={8}
                  className="px-4 py-8 text-center text-sm text-gray-400"
                >
                  No payments match this filter.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {data && data.total > pageSize ? (
        <div className="flex items-center justify-between text-xs text-gray-600">
          <span>
            Page {page + 1} of {Math.ceil(data.total / pageSize)}
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
              disabled={(page + 1) * pageSize >= data.total}
              className="rounded border border-gray-200 px-2 py-1 hover:bg-gray-50 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
