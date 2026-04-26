"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import api from "@/lib/api";

interface DecisionRow {
  id: string;
  workspace_id: string;
  thread_id: number;
  agent_id: number;
  agent_name: string | null;
  capability_name: string;
  args: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  user_message: string | null;
  started_at: string;
  completed_at: string;
  duration_ms: number;
  created_at: string;
}

interface DecisionList {
  items: DecisionRow[];
  count: number;
}

type CapabilityFilter =
  | "all"
  | "ping"
  | "verify_x402_payment"
  | "triage_customer_message";

const CAPABILITY_TABS: ReadonlyArray<{
  key: CapabilityFilter;
  label: string;
}> = [
  { key: "all", label: "All" },
  { key: "ping", label: "ping" },
  { key: "verify_x402_payment", label: "verify_x402_payment" },
  { key: "triage_customer_message", label: "triage_customer_message" },
];

const URGENCY_PILL: Record<string, string> = {
  low: "bg-[color:var(--color-status-done-bg)] text-[color:var(--color-status-done-fg)]",
  medium:
    "bg-[color:var(--color-status-open-bg)] text-[color:var(--color-status-open-fg)]",
  high: "bg-[color:var(--color-linen)] text-[color:var(--color-bronze-dark)] border border-[color:var(--color-gold)]/50",
  critical: "bg-red-100 text-red-800 border border-red-300",
};

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function decisionStatus(d: DecisionRow): "ok" | "neg" | "err" {
  // Top-level error means infrastructure / runtime failure inside the agent.
  if (d.error) return "err";
  if (d.result && typeof d.result === "object") {
    // Compliance decision result first: verified=false means BRAID *decided*
    // and the answer was negative — not a system error. Audit semantics matter
    // here because BRAID does not escalate negative decisions.
    if ("verified" in d.result && d.result.verified === false) return "neg";
    // Plain {"error": "..."} payloads from capabilities that don't have a
    // verified/denied semantic (e.g. triage failed to reach Together AI)
    // signal a real infrastructure error.
    if ("error" in d.result && d.result.error) return "err";
  }
  return "ok";
}

function decisionSummary(d: DecisionRow): string {
  const r = d.result;
  if (d.error) return d.error;
  if (!r || typeof r !== "object") return "—";
  if (d.capability_name === "ping") {
    return `echo: ${String(r.echo ?? "")}`;
  }
  if (d.capability_name === "verify_x402_payment") {
    if (r.verified === true) return "payment verified ✓";
    if (r.verified === false) {
      return `denied: ${String(r.error ?? "unknown reason")}`;
    }
    if (r.error) return String(r.error);
    return "—";
  }
  if (d.capability_name === "triage_customer_message") {
    if (r.error) return String(r.error);
    const cls = String(r.classification ?? "?");
    const urg = String(r.urgency ?? "?");
    const esc = r.escalation_required ? " · escalate" : "";
    return `${cls} · ${urg}${esc}`;
  }
  return JSON.stringify(r).slice(0, 80);
}

export default function BraidDecisionsPage() {
  const [decisions, setDecisions] = useState<DecisionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeFilter, setActiveFilter] = useState<CapabilityFilter>("all");
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [selected, setSelected] = useState<DecisionRow | null>(null);

  const fetchDecisions = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params: Record<string, string | number | boolean> = { limit: 100 };
      if (activeFilter !== "all") params.capability_name = activeFilter;
      if (onlyErrors) params.only_errors = true;
      const res = await api.get<DecisionList>("/admin/braid/decisions", {
        params,
      });
      setDecisions(res.data.items);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to load decisions. Admin access required.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [activeFilter, onlyErrors]);

  useEffect(() => {
    fetchDecisions();
  }, [fetchDecisions]);

  const counts = useMemo(() => {
    const ok = decisions.filter((d) => decisionStatus(d) === "ok").length;
    const neg = decisions.filter((d) => decisionStatus(d) === "neg").length;
    const err = decisions.filter((d) => decisionStatus(d) === "err").length;
    return { ok, neg, err };
  }, [decisions]);

  return (
    <div>
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[color:var(--color-espresso)]">
            BRAID Decisions
          </h1>
          <p className="mt-1 text-sm text-[color:var(--color-muted)]">
            Audit trail of every reasoning step taken by the OpenServ BRAID
            agent. Each row is one capability invocation.
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs text-[color:var(--color-muted)]">
          <span>
            <span className="font-semibold text-[color:var(--color-espresso)]">
              {decisions.length}
            </span>{" "}
            total
          </span>
          <span className="rounded-full bg-[color:var(--color-status-done-bg)] px-2 py-0.5 text-[color:var(--color-status-done-fg)]">
            {counts.ok} ok
          </span>
          <span className="rounded-full bg-[color:var(--color-status-open-bg)] px-2 py-0.5 text-[color:var(--color-status-open-fg)]">
            {counts.neg} negative
          </span>
          <span className="rounded-full bg-red-100 px-2 py-0.5 text-red-800">
            {counts.err} error
          </span>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {CAPABILITY_TABS.map((tab) => {
          const active = activeFilter === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveFilter(tab.key)}
              className={`rounded-full px-3 py-1.5 text-xs font-semibold transition-all ${
                active
                  ? "bg-[color:var(--color-espresso)] text-[color:var(--color-cream)]"
                  : "border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] text-[color:var(--color-espresso)] hover:border-[color:var(--color-gold)] hover:bg-[color:var(--color-sand)]"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
        <label className="ml-3 flex items-center gap-2 text-xs text-[color:var(--color-ink)]">
          <input
            type="checkbox"
            checked={onlyErrors}
            onChange={(e) => setOnlyErrors(e.target.checked)}
            className="h-4 w-4"
          />
          Errors only
        </label>
        <button
          type="button"
          onClick={fetchDecisions}
          className="ml-auto rounded-full border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] px-3 py-1.5 text-xs font-semibold text-[color:var(--color-espresso)] hover:border-[color:var(--color-gold)] hover:bg-[color:var(--color-sand)]"
        >
          Refresh
        </button>
      </div>

      <div className="flex gap-6">
        <div className="flex-1">
          {loading ? (
            <p className="text-[color:var(--color-muted)]">Loading...</p>
          ) : decisions.length === 0 ? (
            <p className="text-[color:var(--color-muted)]">No decisions yet.</p>
          ) : (
            <div className="rwa-card overflow-x-auto p-0">
              <table className="min-w-full">
                <thead className="border-b border-[color:var(--color-stone)] bg-[color:var(--color-sand)]/50">
                  <tr>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                      When
                    </th>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                      Capability
                    </th>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                      Status
                    </th>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                      Summary
                    </th>
                    <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                      Duration
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[color:var(--color-stone)]/60">
                  {decisions.map((d) => {
                    const status = decisionStatus(d);
                    const isTriage =
                      d.capability_name === "triage_customer_message";
                    const urgency =
                      isTriage && d.result && typeof d.result === "object"
                        ? (d.result.urgency as string | undefined)
                        : undefined;
                    return (
                      <tr
                        key={d.id}
                        onClick={() => setSelected(d)}
                        className={`cursor-pointer hover:bg-[color:var(--color-sand)]/40 ${
                          selected?.id === d.id
                            ? "bg-[color:var(--color-sand)]/60"
                            : ""
                        }`}
                      >
                        <td className="px-4 py-3 text-xs text-[color:var(--color-muted)] whitespace-nowrap">
                          {timeAgo(d.started_at)}
                        </td>
                        <td className="px-4 py-3 text-sm font-mono text-[color:var(--color-espresso)] whitespace-nowrap">
                          {d.capability_name}
                          {urgency && (
                            <span
                              className={`ml-2 inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${
                                URGENCY_PILL[urgency] ??
                                "bg-[color:var(--color-linen)] text-[color:var(--color-espresso)]"
                              }`}
                            >
                              {urgency}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-sm whitespace-nowrap">
                          <span
                            className={`status-pill ${
                              status === "ok"
                                ? "status-done"
                                : status === "neg"
                                ? "status-review"
                                : "status-blocked"
                            }`}
                          >
                            {status === "ok"
                              ? "OK"
                              : status === "neg"
                              ? "Negative"
                              : "Error"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-[color:var(--color-ink)]/80 max-w-md truncate">
                          {decisionSummary(d)}
                        </td>
                        <td className="px-4 py-3 text-xs text-[color:var(--color-muted)] text-right whitespace-nowrap">
                          {d.duration_ms}ms
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {selected && (
          <div className="rwa-card h-fit w-[28rem] p-6">
            <div className="mb-4 flex items-start justify-between">
              <div>
                <h2 className="font-mono text-lg font-semibold text-[color:var(--color-espresso)]">
                  {selected.capability_name}
                </h2>
                <p className="mt-0.5 text-xs text-[color:var(--color-muted)]">
                  {new Date(selected.started_at).toLocaleString()} ·{" "}
                  {selected.duration_ms}ms
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="rwa-btn-secondary text-xs"
              >
                Close
              </button>
            </div>

            <div className="space-y-4 text-sm">
              {selected.user_message && (
                <Section label="User message">
                  <p className="whitespace-pre-wrap text-[color:var(--color-ink)]">
                    {selected.user_message}
                  </p>
                </Section>
              )}

              <Section label="Inputs (args)">
                <pre className="overflow-x-auto rounded-md bg-[color:var(--color-sand)]/40 p-3 text-xs leading-relaxed text-[color:var(--color-ink)]">
                  {JSON.stringify(selected.args, null, 2)}
                </pre>
              </Section>

              {selected.result && (
                <Section label="Result">
                  <pre className="overflow-x-auto rounded-md bg-[color:var(--color-sand)]/40 p-3 text-xs leading-relaxed text-[color:var(--color-ink)]">
                    {JSON.stringify(selected.result, null, 2)}
                  </pre>
                </Section>
              )}

              {selected.error && (
                <Section label="Error">
                  <pre className="overflow-x-auto rounded-md border border-red-200 bg-red-50 p-3 text-xs leading-relaxed text-red-900">
                    {selected.error}
                  </pre>
                </Section>
              )}

              <Section label="Context">
                <dl className="grid grid-cols-[7rem_1fr] gap-y-1 text-xs text-[color:var(--color-muted)]">
                  <dt>workspace</dt>
                  <dd className="truncate font-mono text-[color:var(--color-ink)]">
                    {selected.workspace_id}
                  </dd>
                  <dt>thread</dt>
                  <dd className="font-mono text-[color:var(--color-ink)]">
                    {selected.thread_id}
                  </dd>
                  <dt>agent</dt>
                  <dd className="text-[color:var(--color-ink)]">
                    {selected.agent_name ?? "?"} (#{selected.agent_id})
                  </dd>
                  <dt>id</dt>
                  <dd className="truncate font-mono text-[color:var(--color-ink)]">
                    {selected.id}
                  </dd>
                </dl>
              </Section>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
        {label}
      </p>
      {children}
    </div>
  );
}
