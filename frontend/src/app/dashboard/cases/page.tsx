"use client";

import { useEffect, useState, FormEvent } from "react";
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
  client_id: string;
  assigned_lawyer_id: string | null;
  jurisdiction: string | null;
  filing_date: string | null;
  created_at: string;
}

interface CaseListResponse {
  cases: CaseItem[];
  total: number;
}

const CASE_TYPES = ["trademark", "patent", "design", "copyright"];

export default function CasesPage() {
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  // Create form state
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
        client_id: createForm.client_id,
        assigned_lawyer_id: createForm.assigned_lawyer_id || null,
        jurisdiction: createForm.jurisdiction || null,
        filing_date: createForm.filing_date || null,
        deadline: createForm.deadline || null,
        deadline_time: createForm.deadline_time || null,
      };

      await api.post("/cases", payload);
      setCreateSuccess("Case created successfully.");
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

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      open: "bg-green-100 text-green-800",
      in_progress: "bg-blue-100 text-blue-800",
      under_review: "bg-yellow-100 text-yellow-800",
      closed: "bg-gray-100 text-gray-800",
    };
    return colors[status] ?? "bg-gray-100 text-gray-800";
  };

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
          {showCreate ? "Cancel" : "Create Case"}
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

      {/* Cases Table */}
      {loading ? (
        <p className="text-gray-500">Loading cases...</p>
      ) : cases.length === 0 ? (
        <p className="text-gray-500">No cases found.</p>
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
                  Type
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Deadline
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {cases.map((c) => (
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
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${statusBadge(c.status)}`}
                    >
                      {c.status.replace("_", " ")}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {c.deadline ?? "N/A"}
                    {c.deadline_time && ` ${c.deadline_time}`}
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
