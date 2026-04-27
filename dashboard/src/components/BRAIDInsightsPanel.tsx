"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import api from "@/lib/api";

/**
 * BRAID inline insights for a single case.
 *
 * Talks to ``GET /admin/braid/cases/{case_id}/decisions`` (lawyer +
 * client may call it for cases they're attached to; the backend does
 * the RBAC). Renders one badge per capability that has run for the
 * case (validate_nice_classification, score_document_completeness,
 * check_trademark_conflict, …) plus a feedback action that posts to
 * ``/admin/braid/decisions/{id}/feedback``.
 *
 * No hardcoded sample / mock data — every field is derived from a
 * live BraidDecision row.
 */

interface DecisionRow {
  id: string;
  capability_name: string;
  args: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  user_message: string | null;
  started_at: string;
  completed_at: string;
  duration_ms: number;
}

interface DecisionList {
  items: DecisionRow[];
  count: number;
}

interface BRAIDInsightsPanelProps {
  caseId: string;
  /** Hide the feedback action for clients (read-only). */
  canGiveFeedback: boolean;
}

const CAPABILITY_LABELS: Record<string, string> = {
  validate_nice_classification: "Nice classification check",
  score_document_completeness: "Document completeness",
  check_trademark_conflict: "Trademark conflict check",
  route_office_response: "Office response routing",
  triage_customer_message: "Customer message triage",
  verify_zk_file_ownership: "ZK file ownership",
  verify_x402_payment: "x402 payment verification",
};

function fmtPercent(value: unknown): string | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return `${Math.round(value * 100)}%`;
}

function describeResult(row: DecisionRow): string {
  if (row.error) return row.error.slice(0, 200);
  const r = row.result ?? {};
  const lines: string[] = [];
  if (typeof r.recommended_action === "string") lines.push(r.recommended_action);
  if (typeof r.reasoning === "string") lines.push(r.reasoning);
  if (typeof r.risk_level === "string")
    lines.push(`risk: ${r.risk_level}`);
  if (typeof r.confidence === "number")
    lines.push(`confidence: ${fmtPercent(r.confidence)}`);
  if (typeof r.completeness_pct === "number")
    lines.push(`completeness: ${fmtPercent(r.completeness_pct)}`);
  if (typeof r.match_count === "number")
    lines.push(`matches: ${r.match_count}`);
  if (typeof r.escalation_required === "boolean" && r.escalation_required)
    lines.push("⚠ escalation required");
  return lines.length === 0 ? "—" : lines.join(" · ");
}

function badgeClass(row: DecisionRow): string {
  if (row.error) return "bg-red-100 text-red-700 border-red-200";
  const r = row.result ?? {};
  if (typeof r.escalation_required === "boolean" && r.escalation_required)
    return "bg-yellow-100 text-yellow-800 border-yellow-200";
  if (typeof r.risk_level === "string") {
    if (r.risk_level === "high" || r.risk_level === "exact")
      return "bg-red-100 text-red-700 border-red-200";
    if (r.risk_level === "medium")
      return "bg-yellow-100 text-yellow-800 border-yellow-200";
  }
  return "bg-emerald-100 text-emerald-700 border-emerald-200";
}

export function BRAIDInsightsPanel({ caseId, canGiveFeedback }: BRAIDInsightsPanelProps) {
  const [decisions, setDecisions] = useState<DecisionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedbackBusy, setFeedbackBusy] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState("");
  const [feedbackOk, setFeedbackOk] = useState("");

  const fetchDecisions = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api.get<DecisionList>(
        `/admin/braid/cases/${caseId}/decisions`,
      );
      setDecisions(res.data.items);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 403) {
        // Read-only access denied — render nothing rather than a scary error.
        setDecisions([]);
      } else {
        setError(typeof detail === "string" ? detail : "Could not load BRAID decisions.");
      }
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    fetchDecisions();
  }, [fetchDecisions]);

  async function submitFeedback(decisionId: string, actualOutcome: boolean) {
    setFeedbackBusy(decisionId);
    setFeedbackError("");
    setFeedbackOk("");
    try {
      await api.post(`/admin/braid/decisions/${decisionId}/feedback`, {
        actual_outcome: actualOutcome,
        notes: null,
      });
      setFeedbackOk(
        actualOutcome
          ? "Marked as correct (added to BRAID calibration)."
          : "Marked as incorrect (BRAID weights updated).",
      );
      setTimeout(() => setFeedbackOk(""), 4000);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setFeedbackError(typeof detail === "string" ? detail : "Could not save feedback.");
    } finally {
      setFeedbackBusy(null);
    }
  }

  const grouped = useMemo(() => {
    const byCap: Record<string, DecisionRow[]> = {};
    for (const d of decisions) {
      (byCap[d.capability_name] ??= []).push(d);
    }
    return Object.entries(byCap).sort(([a], [b]) => a.localeCompare(b));
  }, [decisions]);

  if (loading) {
    return (
      <div className="mb-6 rounded-lg bg-white p-6 shadow-sm border border-gray-200">
        <h2 className="text-lg font-semibold text-gray-700 mb-2">
          BRAID Insights
        </h2>
        <p className="text-sm text-gray-400">Loading…</p>
      </div>
    );
  }

  if (decisions.length === 0 && !error) {
    // Don't render the box at all when there's nothing to show — keeps
    // the case detail page tidy for cases where BRAID hasn't run yet.
    return null;
  }

  return (
    <div className="mb-6 rounded-lg bg-white p-6 shadow-sm border border-gray-200">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-gray-700">BRAID Insights</h2>
          <span className="inline-flex items-center rounded-full bg-emerald-100 text-emerald-800 px-2.5 py-0.5 text-xs font-medium border border-emerald-200">
            Bounded reasoning
          </span>
        </div>
        <button
          type="button"
          onClick={fetchDecisions}
          className="text-xs text-gray-500 hover:text-gray-700"
        >
          Refresh
        </button>
      </div>

      {error && (
        <div className="mb-3 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
          {error}
        </div>
      )}
      {feedbackError && (
        <div className="mb-3 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
          {feedbackError}
        </div>
      )}
      {feedbackOk && (
        <div className="mb-3 rounded bg-emerald-50 p-3 text-sm text-emerald-700 border border-emerald-200">
          {feedbackOk}
        </div>
      )}

      <div className="space-y-3">
        {grouped.map(([capability, rows]) => (
          <div
            key={capability}
            className="rounded border border-gray-200 p-3"
          >
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-gray-700">
                {CAPABILITY_LABELS[capability] ?? capability}
              </h3>
              <span className="text-xs text-gray-400">{rows.length} records</span>
            </div>
            <ul className="space-y-2">
              {rows.slice(0, 5).map((row) => (
                <li
                  key={row.id}
                  className={`flex items-start justify-between gap-3 rounded border px-3 py-2 ${badgeClass(row)}`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium">
                      {new Date(row.started_at).toLocaleString()} ·{" "}
                      {row.duration_ms}ms
                    </p>
                    <p className="text-xs mt-0.5 break-words">{describeResult(row)}</p>
                  </div>
                  {canGiveFeedback && !row.error && (
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        type="button"
                        onClick={() => submitFeedback(row.id, true)}
                        disabled={feedbackBusy === row.id}
                        title="Decision was correct"
                        className="px-2 py-1 text-xs rounded border border-emerald-300 bg-white text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                      >
                        ✓
                      </button>
                      <button
                        type="button"
                        onClick={() => submitFeedback(row.id, false)}
                        disabled={feedbackBusy === row.id}
                        title="Decision was incorrect"
                        className="px-2 py-1 text-xs rounded border border-red-300 bg-white text-red-700 hover:bg-red-50 disabled:opacity-50"
                      >
                        ✗
                      </button>
                    </div>
                  )}
                </li>
              ))}
              {rows.length > 5 && (
                <li className="text-xs text-gray-400">
                  +{rows.length - 5} older records — see full list in the admin panel
                </li>
              )}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
