"use client";

import { useCallback, useEffect, useState } from "react";

import api, { extractErrorMessage } from "@/lib/api";

interface KeyAccessRow {
  id: string;
  accessed_at: string;
  caller_context: string;
  op_kind: string;
  success: boolean;
  note: string | null;
}

interface KeyAccessResponse {
  items: KeyAccessRow[];
  total: number;
  page: number;
  page_size: number;
}

interface ModelUsageRow {
  model: string;
  sessions: number;
  input_tokens: number;
  output_tokens: number;
  input_rate_per_1m_usd: string;
  output_rate_per_1m_usd: string;
  estimated_cost_usd: string;
}

interface AiUsageResponse {
  totals: {
    input_tokens: number;
    output_tokens: number;
    estimated_cost_usd: string;
  };
  per_model: ModelUsageRow[];
}

const OP_FILTERS: ReadonlyArray<{ label: string; value: string }> = [
  { label: "All", value: "" },
  { label: "Sign", value: "sign" },
  { label: "Verify", value: "verify" },
  { label: "Inspect", value: "inspect" },
];

function StatusBadge({ value }: { value: boolean }) {
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
        value
          ? "bg-emerald-100 text-emerald-700"
          : "bg-red-100 text-red-700"
      }`}
    >
      {value ? "ok" : "failed"}
    </span>
  );
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export default function AdminSecurityPage() {
  const [keyLog, setKeyLog] = useState<KeyAccessResponse | null>(null);
  const [usage, setUsage] = useState<AiUsageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [opFilter, setOpFilter] = useState("");
  const [successFilter, setSuccessFilter] = useState<"" | "true" | "false">(
    ""
  );
  const [page, setPage] = useState(0);
  const pageSize = 25;

  const load = useCallback(async () => {
    setError(null);
    try {
      const params: Record<string, string | number> = {
        page,
        page_size: pageSize,
      };
      if (opFilter) params.op_kind = opFilter;
      if (successFilter) params.success = successFilter;
      const [k, u] = await Promise.all([
        api.get<KeyAccessResponse>("/admin/operator-keys/audit", { params }),
        api.get<AiUsageResponse>("/admin/ai-usage"),
      ]);
      setKeyLog(k.data);
      setUsage(u.data);
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  }, [page, opFilter, successFilter]);

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
  if (!keyLog || !usage) {
    return <div className="text-sm text-gray-500">Loading security…</div>;
  }

  return (
    <div className="space-y-8">
      <section>
        <header className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-800">
            AI cost (estimated, USD)
          </h2>
          <span className="text-xs text-gray-500">
            input {formatTokens(usage.totals.input_tokens)} · output{" "}
            {formatTokens(usage.totals.output_tokens)} · total $
            {usage.totals.estimated_cost_usd}
          </span>
        </header>
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-4 py-2 text-left">Model</th>
                <th className="px-4 py-2 text-left">Sessions</th>
                <th className="px-4 py-2 text-left">Input tokens</th>
                <th className="px-4 py-2 text-left">Output tokens</th>
                <th className="px-4 py-2 text-left">Rates (in / out per 1M)</th>
                <th className="px-4 py-2 text-right">Est. cost (USD)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {usage.per_model.map((row) => (
                <tr key={row.model} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-xs font-mono text-gray-700">
                    {row.model}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-700">
                    {row.sessions}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-700">
                    {formatTokens(row.input_tokens)}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-700">
                    {formatTokens(row.output_tokens)}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-500">
                    ${row.input_rate_per_1m_usd} / $
                    {row.output_rate_per_1m_usd}
                  </td>
                  <td className="px-4 py-2 text-right text-sm font-semibold text-gray-900">
                    ${row.estimated_cost_usd}
                  </td>
                </tr>
              ))}
              {usage.per_model.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-8 text-center text-sm text-gray-400"
                  >
                    No agent sessions recorded yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <header className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-800">
            Operator key audit log
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            {OP_FILTERS.map((f) => (
              <button
                key={f.label}
                type="button"
                onClick={() => {
                  setPage(0);
                  setOpFilter(f.value);
                }}
                className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                  opFilter === f.value
                    ? "bg-gray-900 text-white"
                    : "bg-white text-gray-700 hover:bg-gray-50 border border-gray-200"
                }`}
              >
                {f.label}
              </button>
            ))}
            <span className="ml-2 h-4 w-px bg-gray-200" />
            <button
              type="button"
              onClick={() => {
                setPage(0);
                setSuccessFilter("");
              }}
              className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                successFilter === ""
                  ? "bg-gray-900 text-white"
                  : "bg-white text-gray-700 hover:bg-gray-50 border border-gray-200"
              }`}
            >
              Any
            </button>
            <button
              type="button"
              onClick={() => {
                setPage(0);
                setSuccessFilter("true");
              }}
              className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                successFilter === "true"
                  ? "bg-emerald-700 text-white"
                  : "bg-white text-gray-700 hover:bg-gray-50 border border-gray-200"
              }`}
            >
              Success
            </button>
            <button
              type="button"
              onClick={() => {
                setPage(0);
                setSuccessFilter("false");
              }}
              className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                successFilter === "false"
                  ? "bg-red-700 text-white"
                  : "bg-white text-gray-700 hover:bg-gray-50 border border-gray-200"
              }`}
            >
              Failed
            </button>
          </div>
        </header>

        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-4 py-2 text-left">Accessed</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-left">Op</th>
                <th className="px-4 py-2 text-left">Caller</th>
                <th className="px-4 py-2 text-left">Note</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {keyLog.items.map((row) => (
                <tr key={row.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-xs text-gray-500">
                    {new Date(row.accessed_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2">
                    <StatusBadge value={row.success} />
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-700">
                    {row.op_kind}
                  </td>
                  <td className="px-4 py-2 text-xs font-mono text-gray-700">
                    {row.caller_context}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-600">
                    {row.note || "—"}
                  </td>
                </tr>
              ))}
              {keyLog.items.length === 0 ? (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-8 text-center text-sm text-gray-400"
                  >
                    No key reads recorded for this filter.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        {keyLog.total > pageSize ? (
          <div className="mt-3 flex items-center justify-between text-xs text-gray-600">
            <span>
              Page {page + 1} of {Math.ceil(keyLog.total / pageSize)}
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
                disabled={(page + 1) * pageSize >= keyLog.total}
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
