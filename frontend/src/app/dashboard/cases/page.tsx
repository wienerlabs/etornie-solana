"use client";

import { useEffect, useState, useMemo, FormEvent } from "react";
import Link from "next/link";
import api from "@/lib/api";

interface CaseItem {
  id: string;
  case_number: string;
  title: string;
  case_type: string;
  status: string;
  deadline: string | null;
  deadline_time: string | null;
  client_id: string | null;
  assigned_lawyer_id: string | null;
  jurisdiction: string | null;
  filing_date: string | null;
  guest_client_name: string | null;
  guest_client_email: string | null;
  guest_client_phone: string | null;
  created_at: string;
}

interface CaseListResponse {
  cases: CaseItem[];
  total: number;
}

const CASE_TYPES = ["trademark", "patent", "design", "copyright"];

const STATUS_LABELS: Record<string, string> = {
  open: "Open",
  in_progress: "In Progress",
  under_review: "Under Review",
  closed: "Completed",
};

const STATUS_BADGE_COLORS: Record<string, string> = {
  open: "bg-green-100 text-green-800",
  in_progress: "bg-blue-100 text-blue-800",
  under_review: "bg-yellow-100 text-yellow-800",
  closed: "bg-gray-100 text-gray-800",
};

const STATUS_FILTER_COLORS: Record<string, { active: string; inactive: string }> = {
  all: {
    active: "bg-gray-800 text-white",
    inactive: "bg-gray-100 text-gray-700 hover:bg-gray-200",
  },
  open: {
    active: "bg-green-600 text-white",
    inactive: "bg-green-50 text-green-700 hover:bg-green-100",
  },
  in_progress: {
    active: "bg-blue-600 text-white",
    inactive: "bg-blue-50 text-blue-700 hover:bg-blue-100",
  },
  under_review: {
    active: "bg-yellow-500 text-white",
    inactive: "bg-yellow-50 text-yellow-700 hover:bg-yellow-100",
  },
  closed: {
    active: "bg-gray-500 text-white",
    inactive: "bg-gray-100 text-gray-600 hover:bg-gray-200",
  },
};

const FILTER_TABS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "in_progress", label: "In Progress" },
  { key: "under_review", label: "Under Review" },
  { key: "closed", label: "Completed" },
];

function openPrintView(caseItem: CaseItem, autoPrint: boolean) {
  const printWindow = window.open("", "_blank");
  if (!printWindow) return;

  const statusLabel = STATUS_LABELS[caseItem.status] || caseItem.status;

  printWindow.document.write(`
    <html>
    <head><title>${caseItem.case_number}</title>
    <style>
      body { font-family: Arial, sans-serif; padding: 40px; }
      h1 { font-size: 24px; margin-bottom: 20px; }
      table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
      td, th { padding: 8px 12px; border: 1px solid #ddd; text-align: left; }
      th { background: #f5f5f5; font-weight: 600; width: 200px; }
      .header { display: flex; justify-content: space-between; margin-bottom: 30px; }
      .logo { font-size: 28px; font-weight: bold; }
      .date { color: #666; }
      .pdf-note { margin-top: 20px; padding: 12px; background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 6px; color: #0369a1; font-size: 14px; }
      @media print { .pdf-note { display: none; } }
    </style>
    </head>
    <body>
      <div class="header">
        <div class="logo">Etornie</div>
        <div class="date">${new Date().toLocaleDateString("en-US")}</div>
      </div>
      <h1>Case Details: ${caseItem.case_number}</h1>
      <table>
        <tr><th>Case Number</th><td>${caseItem.case_number}</td></tr>
        <tr><th>Title</th><td>${caseItem.title}</td></tr>
        <tr><th>Type</th><td>${caseItem.case_type}</td></tr>
        <tr><th>Status</th><td>${statusLabel}</td></tr>
        <tr><th>Jurisdiction</th><td>${caseItem.jurisdiction || "-"}</td></tr>
        <tr><th>Filing Date</th><td>${caseItem.filing_date || "-"}</td></tr>
        <tr><th>Deadline</th><td>${caseItem.deadline || "-"}</td></tr>
        <tr><th>Created</th><td>${new Date(caseItem.created_at).toLocaleDateString("en-US")}</td></tr>
      </table>
      ${!autoPrint ? '<div class="pdf-note">To save as PDF, use the &quot;Save as PDF&quot; option in the print dialog.</div>' : ""}
    </body>
    </html>
  `);
  printWindow.document.close();

  if (autoPrint) {
    printWindow.onload = () => {
      printWindow.print();
    };
  }
}

function downloadCSV(caseItem: CaseItem) {
  const headers = [
    "Case Number",
    "Title",
    "Type",
    "Status",
    "Jurisdiction",
    "Filing Date",
    "Deadline",
  ];
  const values = [
    caseItem.case_number,
    caseItem.title,
    caseItem.case_type,
    STATUS_LABELS[caseItem.status] || caseItem.status,
    caseItem.jurisdiction || "",
    caseItem.filing_date || "",
    caseItem.deadline || "",
  ];
  const csv = [headers.join(","), values.map((v) => `"${v}"`).join(",")].join(
    "\n"
  );
  const blob = new Blob(["\uFEFF" + csv], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${caseItem.case_number}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function CasesPage() {
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [activeFilter, setActiveFilter] = useState("all");

  // Create form state
  const [clientMode, setClientMode] = useState<"registered" | "guest">("registered");
  const [createForm, setCreateForm] = useState({
    title: "",
    description: "",
    case_type: "trademark",
    client_id: "",
    assigned_lawyer_id: "",
    jurisdiction: "",
    filing_date: "",
    deadline: "",
    deadline_time: "",
    guest_client_name: "",
    guest_client_email: "",
    guest_client_phone: "",
  });
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState("");
  const [createSuccess, setCreateSuccess] = useState("");

  async function fetchCases() {
    setLoading(true);
    try {
      const res = await api.get<CaseListResponse>("/cases", {
        params: { limit: 100 },
      });
      setCases(res.data.cases);
      setTotal(res.data.total);
    } catch {
      setError("Failed to load cases.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchCases();
  }, []);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {
      all: cases.length,
      open: 0,
      in_progress: 0,
      under_review: 0,
      closed: 0,
    };
    for (const c of cases) {
      if (counts[c.status] !== undefined) {
        counts[c.status] += 1;
      }
    }
    return counts;
  }, [cases]);

  const filteredCases = useMemo(() => {
    if (activeFilter === "all") return cases;
    return cases.filter((c) => c.status === activeFilter);
  }, [cases, activeFilter]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreateError("");
    setCreateSuccess("");
    setCreateLoading(true);

    try {
      const payload: Record<string, unknown> = {
        title: createForm.title,
        description: createForm.description || null,
        case_type: createForm.case_type,
        assigned_lawyer_id: createForm.assigned_lawyer_id || null,
        jurisdiction: createForm.jurisdiction || null,
        filing_date: createForm.filing_date || null,
        deadline: createForm.deadline || null,
        deadline_time: createForm.deadline_time || null,
      };

      if (clientMode === "registered") {
        payload.client_id = createForm.client_id;
      } else {
        payload.guest_client_name = createForm.guest_client_name;
        payload.guest_client_email = createForm.guest_client_email || null;
        payload.guest_client_phone = createForm.guest_client_phone || null;
      }

      await api.post("/cases", payload);
      setCreateSuccess("Case created successfully.");
      setClientMode("registered");
      setCreateForm({
        title: "",
        description: "",
        case_type: "trademark",
        client_id: "",
        assigned_lawyer_id: "",
        jurisdiction: "",
        filing_date: "",
        deadline: "",
        deadline_time: "",
        guest_client_name: "",
        guest_client_email: "",
        guest_client_phone: "",
      });
      setShowCreate(false);
      fetchCases();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to create case.";
      setCreateError(message);
    } finally {
      setCreateLoading(false);
    }
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-800">
          Cases ({total})
        </h1>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          {showCreate ? "Cancel" : "New Case"}
        </button>
      </div>

      {createSuccess && (
        <div className="mb-4 rounded bg-green-50 p-3 text-sm text-green-700 border border-green-200">
          {createSuccess}
        </div>
      )}

      {error && (
        <div className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
          {error}
        </div>
      )}

      {/* Create Case Form */}
      {showCreate && (
        <div className="mb-6 rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <h2 className="mb-4 text-lg font-semibold text-gray-700">
            New Case
          </h2>
          {createError && (
            <div className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
              {createError}
            </div>
          )}
          <form onSubmit={handleCreate} className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label className="block text-sm font-medium text-gray-700">
                Title *
              </label>
              <input
                required
                value={createForm.title}
                onChange={(e) =>
                  setCreateForm({ ...createForm, title: e.target.value })
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="block text-sm font-medium text-gray-700">
                Description
              </label>
              <textarea
                value={createForm.description}
                onChange={(e) =>
                  setCreateForm({
                    ...createForm,
                    description: e.target.value,
                  })
                }
                rows={3}
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Case Type *
              </label>
              <select
                value={createForm.case_type}
                onChange={(e) =>
                  setCreateForm({ ...createForm, case_type: e.target.value })
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                {CASE_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </option>
                ))}
              </select>
            </div>
            <div className="sm:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Client Type *
              </label>
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="clientMode"
                    checked={clientMode === "registered"}
                    onChange={() => setClientMode("registered")}
                    className="accent-blue-600"
                  />
                  <span className="text-sm text-gray-700">Registered Client</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="clientMode"
                    checked={clientMode === "guest"}
                    onChange={() => setClientMode("guest")}
                    className="accent-blue-600"
                  />
                  <span className="text-sm text-gray-700">Guest Client</span>
                </label>
              </div>
            </div>

            {clientMode === "registered" ? (
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Client ID *
                </label>
                <input
                  required
                  value={createForm.client_id}
                  onChange={(e) =>
                    setCreateForm({ ...createForm, client_id: e.target.value })
                  }
                  placeholder="UUID"
                  className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
            ) : (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700">
                    Client Name *
                  </label>
                  <input
                    required
                    value={createForm.guest_client_name}
                    onChange={(e) =>
                      setCreateForm({ ...createForm, guest_client_name: e.target.value })
                    }
                    placeholder="Full name"
                    className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700">
                    Client Email
                  </label>
                  <input
                    type="email"
                    value={createForm.guest_client_email}
                    onChange={(e) =>
                      setCreateForm({ ...createForm, guest_client_email: e.target.value })
                    }
                    placeholder="client@example.com"
                    className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  />
                  <p className="mt-1 text-xs text-gray-400">e.g. client@example.com</p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700">
                    Client Phone
                  </label>
                  <input
                    type="tel"
                    value={createForm.guest_client_phone}
                    onChange={(e) =>
                      setCreateForm({ ...createForm, guest_client_phone: e.target.value })
                    }
                    placeholder="905551234567"
                    className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  />
                  <p className="mt-1 text-xs text-gray-400">Country code required, e.g. 905551234567</p>
                </div>
              </>
            )}
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Assigned Lawyer ID
              </label>
              <input
                value={createForm.assigned_lawyer_id}
                onChange={(e) =>
                  setCreateForm({
                    ...createForm,
                    assigned_lawyer_id: e.target.value,
                  })
                }
                placeholder="UUID (optional)"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Jurisdiction
              </label>
              <input
                value={createForm.jurisdiction}
                onChange={(e) =>
                  setCreateForm({
                    ...createForm,
                    jurisdiction: e.target.value,
                  })
                }
                placeholder="e.g. US, EU, TR"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Filing Date
              </label>
              <input
                type="date"
                value={createForm.filing_date}
                onChange={(e) =>
                  setCreateForm({
                    ...createForm,
                    filing_date: e.target.value,
                  })
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Deadline Date
              </label>
              <input
                type="date"
                value={createForm.deadline}
                onChange={(e) =>
                  setCreateForm({ ...createForm, deadline: e.target.value })
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Deadline Time
              </label>
              <input
                type="time"
                value={createForm.deadline_time}
                onChange={(e) =>
                  setCreateForm({ ...createForm, deadline_time: e.target.value })
                }
                placeholder="HH:MM (optional)"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div className="sm:col-span-2">
              <button
                type="submit"
                disabled={createLoading}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {createLoading ? "Creating..." : "Create Case"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Status Filter Tabs */}
      {!loading && (
        <div className="mb-4 flex flex-wrap gap-2">
          {FILTER_TABS.map((tab) => {
            const isActive = activeFilter === tab.key;
            const colors = STATUS_FILTER_COLORS[tab.key];
            const colorClass = isActive ? colors.active : colors.inactive;
            const count = statusCounts[tab.key] ?? 0;
            return (
              <button
                key={tab.key}
                onClick={() => setActiveFilter(tab.key)}
                className={`rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${colorClass}`}
              >
                {tab.label} ({count})
              </button>
            );
          })}
        </div>
      )}

      {/* Cases Table */}
      {loading ? (
        <p className="text-gray-500">Loading cases...</p>
      ) : filteredCases.length === 0 ? (
        <p className="text-gray-500">
          {activeFilter === "all"
            ? "No cases found."
            : `No cases found with status: ${STATUS_LABELS[activeFilter] || activeFilter}.`}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg bg-white shadow-sm border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Case No
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Title
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Type
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Deadline
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {filteredCases.map((c) => (
                <tr key={c.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm">
                    <Link
                      href={`/dashboard/cases/${c.id}`}
                      className="text-blue-600 hover:underline font-medium"
                    >
                      {c.case_number}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-700 max-w-xs truncate">
                    {c.title}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600 capitalize">
                    {c.case_type}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGE_COLORS[c.status] ?? "bg-gray-100 text-gray-800"}`}
                    >
                      {STATUS_LABELS[c.status] || c.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {c.deadline ?? "N/A"}
                    {c.deadline_time && ` ${c.deadline_time}`}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => openPrintView(c, true)}
                        className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-100 transition-colors"
                        title="Print"
                      >
                        Print
                      </button>
                      <button
                        onClick={() => openPrintView(c, false)}
                        className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-100 transition-colors"
                        title="Save as PDF"
                      >
                        PDF
                      </button>
                      <button
                        onClick={() => downloadCSV(c)}
                        className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-100 transition-colors"
                        title="Download as Excel/CSV"
                      >
                        Excel
                      </button>
                    </div>
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
