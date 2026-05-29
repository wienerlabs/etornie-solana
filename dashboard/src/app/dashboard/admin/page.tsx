"use client";

import { useEffect, useState } from "react";

import api, { extractErrorMessage } from "@/lib/api";

interface OverviewResponse {
  users_total: number;
  users_active: number;
  cases_total: number;
  cases_by_status: Record<string, number>;
  payments_total: number;
  payments_by_status: Record<string, number>;
  payments_confirmed_amount: Record<string, string>;
  filings_total: number;
  filings_by_status: Record<string, number>;
  nft_states: Record<string, number>;
}

function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
        {label}
      </p>
      <p className="mt-1 text-2xl font-semibold text-gray-900">{value}</p>
      {hint ? (
        <p className="mt-1 text-xs text-gray-500">{hint}</p>
      ) : null}
    </div>
  );
}

function Breakdown({
  title,
  values,
}: {
  title: string;
  values: Record<string, number | string>;
}) {
  const entries = Object.entries(values);
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <p className="mb-3 text-sm font-semibold text-gray-800">{title}</p>
      {entries.length === 0 ? (
        <p className="text-xs text-gray-400">No data.</p>
      ) : (
        <ul className="space-y-1.5">
          {entries.map(([k, v]) => (
            <li
              key={k}
              className="flex items-center justify-between text-sm text-gray-700"
            >
              <span className="capitalize">{k.replace(/_/g, " ")}</span>
              <span className="font-mono text-xs">{String(v)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function AdminOverviewPage() {
  const [data, setData] = useState<OverviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<OverviewResponse>("/admin/overview");
        if (!cancelled) setData(res.data);
      } catch (err) {
        if (!cancelled) setError(extractErrorMessage(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        {error}
      </div>
    );
  }
  if (!data) {
    return <div className="text-sm text-gray-500">Loading overview…</div>;
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Users"
          value={data.users_total}
          hint={`${data.users_active} active`}
        />
        <StatCard label="Cases" value={data.cases_total} />
        <StatCard label="Payments" value={data.payments_total} />
        <StatCard label="Filings" value={data.filings_total} />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Breakdown
          title="Payments by status"
          values={data.payments_by_status}
        />
        <Breakdown
          title="Confirmed revenue by currency"
          values={Object.fromEntries(
            Object.entries(data.payments_confirmed_amount).map(([c, v]) => [
              c,
              `${c} ${v}`,
            ])
          )}
        />
        <Breakdown
          title="Filings by status"
          values={data.filings_by_status}
        />
        <Breakdown title="Cases by status" values={data.cases_by_status} />
        <Breakdown title="NFT lifecycle" values={data.nft_states} />
      </div>
    </div>
  );
}
