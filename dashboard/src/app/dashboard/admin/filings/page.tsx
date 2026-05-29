"use client";

import { useCallback, useEffect, useState } from "react";

import api, { extractErrorMessage } from "@/lib/api";

interface FilingRow {
  id: string;
  case_draft_id: string;
  platform: string;
  status: string;
  attempt_number: number;
  external_reference: string | null;
  error_message: string | null;
  submitted_at: string | null;
  completed_at: string | null;
  created_at: string;
  case_draft_mark_text: string | null;
  case_draft_user_email: string | null;
}

interface ListResponse {
  items: FilingRow[];
  total: number;
  page: number;
  page_size: number;
}

const STATUS_FILTERS: ReadonlyArray<{ label: string; value: string }> = [
  { label: "All", value: "" },
  { label: "Pending", value: "pending" },
  { label: "Submitted", value: "submitted" },
  { label: "Accepted", value: "accepted" },
  { label: "Rejected", value: "rejected" },
  { label: "Error", value: "error" },
  { label: "Retrying", value: "retrying" },
];

function StatusBadge({ value }: { value: string }) {
  const color =
    value === "submitted" || value === "accepted"
      ? "bg-emerald-100 text-emerald-700"
      : value === "rejected" || value === "error"
        ? "bg-red-100 text-red-700"
        : value === "retrying"
          ? "bg-amber-100 text-amber-700"
          : "bg-gray-100 text-gray-700";
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${color}`}
    >
      {value}
    </span>
  );
}

export default function AdminFilingsPage() {
  const [data, setData] = useState<ListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [page, setPage] = useState(0);
  const [pageSize] = useState(25);
  const [retryingId, setRetryingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const params: Record<string, string | number> = { page, page_size: pageSize };
      if (statusFilter) params.status = statusFilter;
      const res = await api.get<ListResponse>("/admin/filings", { params });
      setData(res.data);
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  }, [page, pageSize, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const onRetry = async (attemptId: string) => {
    if (
      !window.confirm(
        "Re-submit this case to EUIPO? A new filing_attempt row will be created."
      )
    ) {
      return;
    }
    setRetryingId(attemptId);
    try {
      await api.post(`/admin/filings/${attemptId}/retry`);
      await load();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setRetryingId(null);
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
          {data ? `${data.total} filings` : "Loading…"}
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
              <th className="px-4 py-2 text-left">Platform</th>
              <th className="px-4 py-2 text-left">Mark</th>
              <th className="px-4 py-2 text-left">User</th>
              <th className="px-4 py-2 text-left">Attempt</th>
              <th className="px-4 py-2 text-left">External Ref</th>
              <th className="px-4 py-2 text-left">Error</th>
              <th className="px-4 py-2 text-left">Created</th>
              <th className="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data?.items.map((row) => {
              const canRetry =
                row.platform === "EUIPO" &&
                (row.status === "error" || row.status === "rejected");
              return (
                <tr key={row.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2">
                    <StatusBadge value={row.status} />
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-700">
                    {row.platform}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-900">
                    {row.case_draft_mark_text || "—"}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-600">
                    {row.case_draft_user_email || "—"}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-700">
                    #{row.attempt_number}
                  </td>
                  <td className="px-4 py-2 text-xs">
                    {row.external_reference ? (
                      <span className="font-mono text-emerald-700">
                        {row.external_reference}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-2 text-xs text-red-700">
                    {row.error_message ? (
                      <span title={row.error_message}>
                        {row.error_message.length > 60
                          ? `${row.error_message.slice(0, 60)}…`
                          : row.error_message}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-500">
                    {new Date(row.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {canRetry ? (
                      <button
                        type="button"
                        onClick={() => onRetry(row.id)}
                        disabled={retryingId === row.id}
                        className="rounded-md border border-emerald-300 bg-white px-2.5 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                      >
                        {retryingId === row.id ? "Retrying…" : "Retry"}
                      </button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
            {data && data.items.length === 0 ? (
              <tr>
                <td
                  colSpan={9}
                  className="px-4 py-8 text-center text-sm text-gray-400"
                >
                  No filings match this filter.
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
