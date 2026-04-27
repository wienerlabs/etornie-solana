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
  | "verify_zk_file_ownership"
  | "triage_customer_message"
  | "validate_nice_classification"
  | "check_trademark_conflict"
  | "score_document_completeness"
  | "route_office_response";

const CAPABILITY_TABS: ReadonlyArray<{
  key: CapabilityFilter;
  label: string;
}> = [
  { key: "all", label: "All" },
  { key: "ping", label: "ping" },
  { key: "verify_x402_payment", label: "verify_x402_payment" },
  { key: "verify_zk_file_ownership", label: "verify_zk_file_ownership" },
  { key: "triage_customer_message", label: "triage_customer_message" },
  { key: "validate_nice_classification", label: "validate_nice_classification" },
  { key: "check_trademark_conflict", label: "check_trademark_conflict" },
  { key: "score_document_completeness", label: "score_document_completeness" },
  { key: "route_office_response", label: "route_office_response" },
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

type ViewTab = "decisions" | "weights" | "calibration" | "disagreement" | "budget";

const VIEW_TABS: ReadonlyArray<{ key: ViewTab; label: string }> = [
  { key: "decisions", label: "Decisions" },
  { key: "weights", label: "Weights" },
  { key: "calibration", label: "Calibration" },
  { key: "disagreement", label: "Disagreement" },
  { key: "budget", label: "Budget" },
];

export default function BraidDecisionsPage() {
  const [viewTab, setViewTab] = useState<ViewTab>("decisions");
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

      <div className="mb-4 flex items-center gap-2 border-b border-[color:var(--color-stone)]">
        {VIEW_TABS.map((tab) => {
          const active = viewTab === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => setViewTab(tab.key)}
              className={`px-4 py-2 text-sm font-semibold border-b-2 -mb-px transition-colors ${
                active
                  ? "border-[color:var(--color-espresso)] text-[color:var(--color-espresso)]"
                  : "border-transparent text-[color:var(--color-muted)] hover:text-[color:var(--color-espresso)]"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {viewTab === "weights" && <WeightsTab />}
      {viewTab === "calibration" && <CalibrationTab />}
      {viewTab === "disagreement" && <DisagreementTab />}
      {viewTab === "budget" && <BudgetTab />}

      {viewTab === "decisions" && (
      <>
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
      </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Bounded-learning tabs
// ─────────────────────────────────────────────────────────────────────

interface CapabilityWeight {
  capability_name: string;
  weight: number;
  weight_floor: number;
  weight_ceiling: number;
  successes: number;
  failures: number;
  last_decision_at: string | null;
  updated_at: string;
}

function WeightsTab() {
  const [items, setItems] = useState<CapabilityWeight[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    api
      .get<{ items: CapabilityWeight[]; count: number }>(
        "/admin/braid/weights",
      )
      .then((res) => setItems(res.data.items))
      .catch((err) => {
        const detail = (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? "Could not load weights.";
        setError(detail);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-[color:var(--color-muted)]">Loading…</p>;
  if (error)
    return (
      <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {error}
      </div>
    );
  if (items.length === 0)
    return (
      <p className="text-sm text-[color:var(--color-muted)]">
        No capability weights yet. A weight row is created the first time a
        capability runs (default 0.5).
      </p>
    );

  return (
    <div className="rwa-card overflow-x-auto p-0">
      <table className="min-w-full">
        <thead className="border-b border-[color:var(--color-stone)] bg-[color:var(--color-sand)]/50">
          <tr>
            <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
              Capability
            </th>
            <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
              Weight
            </th>
            <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
              Floor / Ceiling
            </th>
            <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
              Successes
            </th>
            <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
              Failures
            </th>
            <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
              Last call
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[color:var(--color-stone)]/60">
          {items.map((row) => (
            <tr key={row.capability_name}>
              <td className="px-4 py-3 text-sm font-mono text-[color:var(--color-espresso)]">
                {row.capability_name}
              </td>
              <td className="px-4 py-3 text-sm text-right">
                <span className="inline-block w-20">
                  <span
                    className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                      row.weight >= 0.7
                        ? "bg-emerald-100 text-emerald-700"
                        : row.weight >= 0.4
                        ? "bg-yellow-100 text-yellow-800"
                        : "bg-red-100 text-red-700"
                    }`}
                  >
                    {row.weight.toFixed(3)}
                  </span>
                </span>
              </td>
              <td className="px-4 py-3 text-xs text-right text-[color:var(--color-muted)] font-mono">
                {row.weight_floor.toFixed(2)} / {row.weight_ceiling.toFixed(2)}
              </td>
              <td className="px-4 py-3 text-sm text-right">{row.successes}</td>
              <td className="px-4 py-3 text-sm text-right">{row.failures}</td>
              <td className="px-4 py-3 text-xs text-right text-[color:var(--color-muted)]">
                {row.last_decision_at ? timeAgo(row.last_decision_at) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface CalibrationEvent {
  id: string;
  decision_id: string;
  capability_name: string;
  stated_confidence: number | null;
  actual_outcome: boolean;
  log_update: number | null;
  reward: number | null;
  feedback_source: string;
  feedback_user_id: string | null;
  notes: string | null;
  created_at: string;
}

interface CalibrationCapability {
  capability_name: string;
  events: number;
  correct: number;
  accuracy: number;
  mean_stated_confidence: number | null;
  calibration_error: number | null;
}

function CalibrationTab() {
  const [items, setItems] = useState<CalibrationEvent[]>([]);
  const [summary, setSummary] = useState<CalibrationCapability[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    api
      .get<{ items: CalibrationEvent[]; summary: CalibrationCapability[]; count: number }>(
        "/admin/braid/calibration",
      )
      .then((res) => {
        setItems(res.data.items);
        setSummary(res.data.summary);
      })
      .catch((err) => {
        const detail = (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? "Could not load calibration.";
        setError(detail);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-[color:var(--color-muted)]">Loading…</p>;
  if (error)
    return (
      <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {error}
      </div>
    );
  if (items.length === 0)
    return (
      <p className="text-sm text-[color:var(--color-muted)]">
        No feedback yet. A calibration event is created when a lawyer or admin
        marks a BRAID decision with ✓/✗.
      </p>
    );

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-semibold mb-2">
          Calibration by capability
        </h3>
        <div className="rwa-card overflow-x-auto p-0">
          <table className="min-w-full">
            <thead className="border-b border-[color:var(--color-stone)] bg-[color:var(--color-sand)]/50">
              <tr>
                <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Capability
                </th>
                <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Events
                </th>
                <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Accuracy
                </th>
                <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Mean stated
                </th>
                <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Calibration error
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[color:var(--color-stone)]/60">
              {summary.map((s) => (
                <tr key={s.capability_name}>
                  <td className="px-4 py-3 text-sm font-mono">{s.capability_name}</td>
                  <td className="px-4 py-3 text-sm text-right">{s.events}</td>
                  <td className="px-4 py-3 text-sm text-right">
                    {(s.accuracy * 100).toFixed(1)}%
                  </td>
                  <td className="px-4 py-3 text-sm text-right">
                    {s.mean_stated_confidence !== null
                      ? `${(s.mean_stated_confidence * 100).toFixed(1)}%`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-sm text-right">
                    {s.calibration_error !== null
                      ? `${(s.calibration_error * 100).toFixed(1)}pp`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold mb-2">
          Recent feedback events ({items.length})
        </h3>
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
                  Outcome
                </th>
                <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Stated
                </th>
                <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Source
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[color:var(--color-stone)]/60">
              {items.slice(0, 50).map((ev) => (
                <tr key={ev.id}>
                  <td className="px-4 py-3 text-xs text-[color:var(--color-muted)]">
                    {timeAgo(ev.created_at)}
                  </td>
                  <td className="px-4 py-3 text-sm font-mono">{ev.capability_name}</td>
                  <td className="px-4 py-3 text-sm">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                        ev.actual_outcome
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-red-100 text-red-700"
                      }`}
                    >
                      {ev.actual_outcome ? "correct" : "incorrect"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-right">
                    {ev.stated_confidence !== null
                      ? `${(ev.stated_confidence * 100).toFixed(0)}%`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-sm">{ev.feedback_source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

interface DisagreementRow {
  id: string;
  capability_name: string;
  grouping_key: string;
  sample_count: number;
  mean: number;
  std_dev: number;
  coefficient_of_variation: number;
  escalation_triggered: boolean;
  escalation_threshold: number;
  decision_ids: string[];
  created_at: string;
}

function DisagreementTab() {
  const [items, setItems] = useState<DisagreementRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [onlyEscalated, setOnlyEscalated] = useState(false);

  const fetch = useCallback(() => {
    setLoading(true);
    api
      .get<{ items: DisagreementRow[]; count: number }>(
        "/admin/braid/disagreement",
        { params: { only_escalated: onlyEscalated } },
      )
      .then((res) => setItems(res.data.items))
      .catch((err) => {
        const detail = (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? "Could not load disagreement data.";
        setError(detail);
      })
      .finally(() => setLoading(false));
  }, [onlyEscalated]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  if (error)
    return (
      <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {error}
      </div>
    );

  return (
    <div>
      <div className="mb-3 flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={onlyEscalated}
            onChange={(e) => setOnlyEscalated(e.target.checked)}
            className="h-4 w-4"
          />
          Only escalation-triggered
        </label>
        <button
          type="button"
          onClick={fetch}
          className="text-xs text-[color:var(--color-muted)] hover:underline ml-auto"
        >
          Refresh
        </button>
      </div>
      {loading ? (
        <p className="text-[color:var(--color-muted)]">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-[color:var(--color-muted)]">
          No disagreement observations yet. CV is computed and surfaced here when
          the same capability runs 2+ times for the same case with different results.
        </p>
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
                  Grouping key
                </th>
                <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  N
                </th>
                <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Mean
                </th>
                <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  CV
                </th>
                <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Escalate?
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[color:var(--color-stone)]/60">
              {items.map((row) => (
                <tr
                  key={row.id}
                  className={row.escalation_triggered ? "bg-red-50/40" : ""}
                >
                  <td className="px-4 py-3 text-xs text-[color:var(--color-muted)]">
                    {timeAgo(row.created_at)}
                  </td>
                  <td className="px-4 py-3 text-sm font-mono">{row.capability_name}</td>
                  <td className="px-4 py-3 text-xs font-mono truncate max-w-[200px]">
                    {row.grouping_key}
                  </td>
                  <td className="px-4 py-3 text-sm text-right">{row.sample_count}</td>
                  <td className="px-4 py-3 text-sm text-right font-mono">
                    {row.mean.toFixed(3)}
                  </td>
                  <td className="px-4 py-3 text-sm text-right font-mono">
                    {row.coefficient_of_variation.toFixed(3)}
                  </td>
                  <td className="px-4 py-3 text-sm text-right">
                    {row.escalation_triggered ? (
                      <span className="rounded-full bg-red-100 text-red-700 px-2 py-0.5 text-[11px] font-semibold">
                        YES
                      </span>
                    ) : (
                      <span className="text-[color:var(--color-muted)]">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

interface BudgetSnapshot {
  window_start: string;
  window_end: string;
  daily_call_budget: number;
  calls_used: number;
  calls_skipped_under_pressure: number;
  skip_threshold: number;
  pressure_threshold: number;
  pressure: number;
  updated_at: string;
}

function BudgetTab() {
  const [state, setState] = useState<BudgetSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(() => {
    setLoading(true);
    api
      .get<BudgetSnapshot>("/admin/braid/budget")
      .then((res) => setState(res.data))
      .catch((err) => {
        const detail = (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail ?? "Could not load budget.";
        setError(detail);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (loading) return <p className="text-[color:var(--color-muted)]">Loading…</p>;
  if (error)
    return (
      <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {error}
      </div>
    );
  if (!state) return null;

  const pct = (state.pressure * 100).toFixed(1);
  const pressureBar = Math.min(state.pressure, 1) * 100;
  const overPressure = state.pressure >= state.pressure_threshold;

  return (
    <div className="rwa-card p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Daily call budget</h3>
        <button
          type="button"
          onClick={refresh}
          className="text-xs text-[color:var(--color-muted)] hover:underline"
        >
          Refresh
        </button>
      </div>

      <div>
        <div className="flex justify-between text-xs mb-1">
          <span>
            {state.calls_used} / {state.daily_call_budget} calls
          </span>
          <span>{pct}% pressure</span>
        </div>
        <div className="h-3 rounded-full bg-[color:var(--color-stone)]/40 overflow-hidden">
          <div
            className={`h-full ${
              overPressure
                ? "bg-red-500"
                : state.pressure >= 0.5
                ? "bg-yellow-500"
                : "bg-emerald-500"
            }`}
            style={{ width: `${pressureBar}%` }}
          />
        </div>
      </div>

      <dl className="grid grid-cols-[10rem_1fr] gap-y-1 text-sm">
        <dt className="text-[color:var(--color-muted)]">Window start</dt>
        <dd>{new Date(state.window_start).toLocaleString()}</dd>
        <dt className="text-[color:var(--color-muted)]">Window end</dt>
        <dd>{new Date(state.window_end).toLocaleString()}</dd>
        <dt className="text-[color:var(--color-muted)]">Skip threshold</dt>
        <dd>{state.skip_threshold.toFixed(2)} (capabilities below this are skipped under pressure)</dd>
        <dt className="text-[color:var(--color-muted)]">Pressure threshold</dt>
        <dd>{state.pressure_threshold.toFixed(2)} (gate activates above this)</dd>
        <dt className="text-[color:var(--color-muted)]">Skipped</dt>
        <dd>{state.calls_skipped_under_pressure}</dd>
      </dl>

      {overPressure && (
        <div className="rounded bg-red-50 border border-red-200 p-3 text-xs text-red-700">
          Pressure ≥ threshold — low-weight capabilities are being skipped during
          this window. They appear in the audit log as <code>error: skipped: budget gate</code>.
        </div>
      )}
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
