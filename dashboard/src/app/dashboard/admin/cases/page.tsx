"use client";

import { useCallback, useEffect, useState } from "react";

import api, { extractErrorMessage } from "@/lib/api";

interface CaseRow {
  id: string;
  case_number: string;
  title: string | null;
  case_type: string;
  jurisdiction: string | null;
  status: string;
  client_email: string | null;
  client_wallet: string | null;
  nft_state: string | null;
  nft_mint: string | null;
  attestation_tx: string | null;
  filing_date: string | null;
  deadline: string | null;
  created_at: string;
}

interface ListResponse {
  items: CaseRow[];
  total: number;
  page: number;
  page_size: number;
}

const STATUS_FILTERS: ReadonlyArray<{ label: string; value: string }> = [
  { label: "All", value: "" },
  { label: "Open", value: "open" },
  { label: "In progress", value: "in_progress" },
  { label: "Closed", value: "closed" },
];

const NFT_FILTERS: ReadonlyArray<{ label: string; value: string }> = [
  { label: "All NFT", value: "" },
  { label: "Pending claim", value: "pending_claim" },
  { label: "Minted", value: "minted" },
  { label: "Burned", value: "burned" },
];

function CaseStatusBadge({ value }: { value: string }) {
  const color =
    value === "open" || value === "in_progress"
      ? "bg-emerald-100 text-emerald-700"
      : value === "closed"
        ? "bg-gray-100 text-gray-600"
        : "bg-amber-100 text-amber-700";
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${color}`}
    >
      {value}
    </span>
  );
}

export default function AdminCasesPage() {
  const [data, setData] = useState<ListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [nftFilter, setNftFilter] = useState<string>("");
  const [page, setPage] = useState(0);
  const [pageSize] = useState(25);

  const load = useCallback(async () => {
    setError(null);
    try {
      const params: Record<string, string | number> = { page, page_size: pageSize };
      if (statusFilter) params.status = statusFilter;
      if (nftFilter) params.nft_state = nftFilter;
      const res = await api.get<ListResponse>("/admin/cases", { params });
      setData(res.data);
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  }, [page, pageSize, statusFilter, nftFilter]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {STATUS_FILTERS.map((f) => (
          <button
            key={`s-${f.label}`}
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
        <span className="ml-2 h-4 w-px bg-gray-200" />
        {NFT_FILTERS.map((f) => (
          <button
            key={`n-${f.label}`}
            type="button"
            onClick={() => {
              setPage(0);
              setNftFilter(f.value);
            }}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${
              nftFilter === f.value
                ? "bg-emerald-700 text-white"
                : "bg-white text-gray-700 hover:bg-gray-50 border border-gray-200"
            }`}
          >
            {f.label}
          </button>
        ))}
        <span className="ml-auto text-xs text-gray-500">
          {data ? `${data.total} cases` : "Loading…"}
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
              <th className="px-4 py-2 text-left">Case</th>
              <th className="px-4 py-2 text-left">Type</th>
              <th className="px-4 py-2 text-left">Status</th>
              <th className="px-4 py-2 text-left">Client</th>
              <th className="px-4 py-2 text-left">NFT</th>
              <th className="px-4 py-2 text-left">Filed</th>
              <th className="px-4 py-2 text-left">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data?.items.map((row) => (
              <tr key={row.id} className="hover:bg-gray-50">
                <td className="px-4 py-2">
                  <a
                    href={`/dashboard/cases/${row.id}`}
                    className="font-mono text-xs text-emerald-700 underline-offset-2 hover:underline"
                  >
                    {row.case_number}
                  </a>
                  {row.title ? (
                    <div className="text-xs text-gray-500">{row.title}</div>
                  ) : null}
                </td>
                <td className="px-4 py-2 text-xs text-gray-700">
                  {row.case_type}
                </td>
                <td className="px-4 py-2">
                  <CaseStatusBadge value={row.status} />
                </td>
                <td className="px-4 py-2 text-xs text-gray-700">
                  {row.client_email || "—"}
                </td>
                <td className="px-4 py-2 text-xs">
                  {row.nft_state ? (
                    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-700">
                      {row.nft_state}
                    </span>
                  ) : (
                    "—"
                  )}
                  {row.nft_mint ? (
                    <div className="mt-0.5 font-mono text-[10px] text-gray-500">
                      {row.nft_mint.slice(0, 8)}…
                    </div>
                  ) : null}
                </td>
                <td className="px-4 py-2 text-xs text-gray-500">
                  {row.filing_date
                    ? new Date(row.filing_date).toLocaleDateString()
                    : "—"}
                </td>
                <td className="px-4 py-2 text-xs text-gray-500">
                  {new Date(row.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
            {data && data.items.length === 0 ? (
              <tr>
                <td
                  colSpan={7}
                  className="px-4 py-8 text-center text-sm text-gray-400"
                >
                  No cases match this filter.
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
