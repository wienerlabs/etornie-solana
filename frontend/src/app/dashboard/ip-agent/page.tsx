"use client";

import { useEffect, useState, FormEvent } from "react";
import api from "@/lib/api";

interface DeadlineAlert {
  case_id: string;
  case_number: string;
  case_title: string;
  deadline: string;
  days_remaining: number;
  lawyer_name: string | null;
  client_name: string | null;
  notifications_created: number;
}

interface ScanResult {
  scanned_cases: number;
  deadlines_found: number;
  notifications_created: number;
  alerts: DeadlineAlert[];
}

interface UpcomingDeadlineItem {
  case_id: string;
  case_number: string;
  case_title: string;
  deadline: string;
  days_remaining: number;
  status: string;
  lawyer_name: string | null;
  client_name: string | null;
}

interface UpcomingDeadlinesResponse {
  deadlines: UpcomingDeadlineItem[];
  total: number;
}

export default function IPAgentPage() {
  // Scan state
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [scanLoading, setScanLoading] = useState(false);
  const [scanError, setScanError] = useState("");

  // Upcoming deadlines
  const [deadlines, setDeadlines] = useState<UpcomingDeadlineItem[]>([]);
  const [deadlinesTotal, setDeadlinesTotal] = useState(0);
  const [deadlinesLoading, setDeadlinesLoading] = useState(true);
  const [deadlinesError, setDeadlinesError] = useState("");

  // Configure state
  const [reminderDays, setReminderDays] = useState("30,7,1");
  const [enabled, setEnabled] = useState(true);
  const [configLoading, setConfigLoading] = useState(false);
  const [configError, setConfigError] = useState("");
  const [configSuccess, setConfigSuccess] = useState("");

  async function fetchUpcomingDeadlines() {
    setDeadlinesLoading(true);
    try {
      const res = await api.get<UpcomingDeadlinesResponse>(
        "/agents/ip/upcoming-deadlines"
      );
      setDeadlines(res.data.deadlines);
      setDeadlinesTotal(res.data.total);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to load upcoming deadlines.";
      setDeadlinesError(message);
    } finally {
      setDeadlinesLoading(false);
    }
  }

  useEffect(() => {
    fetchUpcomingDeadlines();
  }, []);

  async function handleScan() {
    setScanError("");
    setScanResult(null);
    setScanLoading(true);

    try {
      const res = await api.post<ScanResult>("/agents/ip/scan-deadlines");
      setScanResult(res.data);
      fetchUpcomingDeadlines();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Scan failed. Admin access required.";
      setScanError(message);
    } finally {
      setScanLoading(false);
    }
  }

  async function handleConfigure(e: FormEvent) {
    e.preventDefault();
    setConfigError("");
    setConfigSuccess("");
    setConfigLoading(true);

    try {
      const days = reminderDays
        .split(",")
        .map((d) => parseInt(d.trim(), 10))
        .filter((d) => !isNaN(d));

      const res = await api.post("/agents/ip/configure", {
        reminder_days: days,
        enabled,
      });
      setConfigSuccess(
        `Configured: reminder_days=[${res.data.reminder_days.join(",")}], enabled=${res.data.is_enabled}`
      );
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Configuration failed. Admin access required.";
      setConfigError(message);
    } finally {
      setConfigLoading(false);
    }
  }

  const daysColor = (days: number) => {
    if (days <= 1) return "text-red-600 font-bold";
    if (days <= 7) return "text-orange-600 font-semibold";
    return "text-yellow-600";
  };

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold text-gray-800">IP Agent</h1>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Scan Section */}
        <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <h2 className="mb-4 text-lg font-semibold text-gray-700">
            Scan Deadlines
          </h2>
          <p className="mb-4 text-sm text-gray-500">
            Scan all active cases for upcoming deadlines and create WhatsApp
            notifications. Admin only.
          </p>
          <button
            onClick={handleScan}
            disabled={scanLoading}
            className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {scanLoading ? "Scanning..." : "Scan Deadlines"}
          </button>

          {scanError && (
            <div className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
              {scanError}
            </div>
          )}

          {scanResult && (
            <div className="mt-4 space-y-2">
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="rounded bg-gray-50 p-2">
                  <p className="text-lg font-bold text-gray-800">
                    {scanResult.scanned_cases}
                  </p>
                  <p className="text-xs text-gray-500">Scanned</p>
                </div>
                <div className="rounded bg-gray-50 p-2">
                  <p className="text-lg font-bold text-orange-600">
                    {scanResult.deadlines_found}
                  </p>
                  <p className="text-xs text-gray-500">Deadlines</p>
                </div>
                <div className="rounded bg-gray-50 p-2">
                  <p className="text-lg font-bold text-blue-600">
                    {scanResult.notifications_created}
                  </p>
                  <p className="text-xs text-gray-500">Notifications</p>
                </div>
              </div>

              {scanResult.alerts.length > 0 && (
                <div className="mt-3 max-h-48 overflow-y-auto space-y-2">
                  {scanResult.alerts.map((a, i) => (
                    <div
                      key={i}
                      className="rounded bg-orange-50 p-2 text-xs border border-orange-100"
                    >
                      <p className="font-medium text-gray-700">
                        {a.case_number} - {a.case_title}
                      </p>
                      <p className="text-gray-500">
                        Deadline: {a.deadline} ({a.days_remaining} days) |{" "}
                        {a.notifications_created} notifications
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Configure Section */}
        <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <h2 className="mb-4 text-lg font-semibold text-gray-700">
            Configure
          </h2>

          <form onSubmit={handleConfigure} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Reminder Days
              </label>
              <input
                value={reminderDays}
                onChange={(e) => setReminderDays(e.target.value)}
                placeholder="30,7,1"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
              <p className="mt-1 text-xs text-gray-400">
                Comma-separated days before deadline
              </p>
            </div>

            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="agent-enabled"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <label
                htmlFor="agent-enabled"
                className="text-sm text-gray-700"
              >
                Agent Enabled
              </label>
            </div>

            <button
              type="submit"
              disabled={configLoading}
              className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {configLoading ? "Saving..." : "Save Configuration"}
            </button>
          </form>

          {configError && (
            <div className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
              {configError}
            </div>
          )}
          {configSuccess && (
            <div className="mt-4 rounded bg-green-50 p-3 text-sm text-green-700 border border-green-200">
              {configSuccess}
            </div>
          )}
        </div>
      </div>

      {/* Upcoming Deadlines Table */}
      <div className="mt-8">
        <h2 className="mb-4 text-lg font-semibold text-gray-700">
          Upcoming Deadlines ({deadlinesTotal})
        </h2>

        {deadlinesError && (
          <div className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
            {deadlinesError}
          </div>
        )}

        {deadlinesLoading ? (
          <p className="text-gray-500">Loading deadlines...</p>
        ) : deadlines.length === 0 ? (
          <p className="text-gray-500">
            No upcoming deadlines in the next 30 days.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg bg-white shadow-sm border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                    Case Number
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                    Title
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                    Deadline
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                    Days Left
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                    Lawyer
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                    Client
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {deadlines.map((d) => (
                  <tr key={d.case_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm font-medium text-gray-700">
                      {d.case_number}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700 max-w-xs truncate">
                      {d.case_title}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {d.deadline}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <span className={daysColor(d.days_remaining)}>
                        {d.days_remaining}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 capitalize">
                      {d.status.replace("_", " ")}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {d.lawyer_name ?? "N/A"}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {d.client_name ?? "N/A"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
