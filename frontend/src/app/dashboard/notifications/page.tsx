"use client";

import { useEffect, useState, FormEvent } from "react";
import api from "@/lib/api";

interface NotificationItem {
  id: string;
  recipient_phone: string;
  recipient_name: string | null;
  message_type: string;
  template_name: string | null;
  template_language: string;
  message_body: string | null;
  status: string;
  scheduled_at: string;
  sent_at: string | null;
  error_message: string | null;
  retry_count: number;
  max_retries: number;
  whatsapp_message_id: string | null;
  created_by: string;
  case_id: string | null;
  created_at: string;
}

interface NotificationListResponse {
  notifications: NotificationItem[];
  total: number;
}

export default function NotificationsPage() {
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  // Create form
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState({
    recipient_phone: "",
    recipient_name: "",
    message_type: "text" as "text" | "template",
    template_name: "",
    template_language: "en_US",
    message_body: "",
    scheduled_at: "",
    case_id: "",
    max_retries: "3",
  });
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState("");

  // Send Now form
  const [showSend, setShowSend] = useState(false);
  const [sendForm, setSendForm] = useState({
    recipient_phone: "",
    message_type: "text" as "text" | "template",
    template_name: "",
    template_language: "en_US",
    message_body: "",
  });
  const [sendLoading, setSendLoading] = useState(false);
  const [sendError, setSendError] = useState("");

  // Templates
  const [templates, setTemplates] = useState<Record<string, unknown>[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);

  // Process pending
  const [processLoading, setProcessLoading] = useState(false);

  async function fetchNotifications() {
    setLoading(true);
    try {
      const res = await api.get<NotificationListResponse>("/notifications", {
        params: { limit: 100 },
      });
      setNotifications(res.data.notifications);
      setTotal(res.data.total);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to load notifications.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchNotifications();
  }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreateError("");
    setSuccessMsg("");
    setCreateLoading(true);

    try {
      const scheduledIso = createForm.scheduled_at
        ? new Date(createForm.scheduled_at).toISOString()
        : null;
      await api.post("/notifications", {
        recipient_phone: createForm.recipient_phone,
        recipient_name: createForm.recipient_name || null,
        message_type: createForm.message_type,
        template_name: createForm.template_name || null,
        template_language: createForm.template_language,
        message_body: createForm.message_body || null,
        scheduled_at: scheduledIso,
        case_id: createForm.case_id || null,
        max_retries: parseInt(createForm.max_retries, 10),
      });
      setSuccessMsg("Notification created successfully.");
      setShowCreate(false);
      setCreateForm({
        recipient_phone: "",
        recipient_name: "",
        message_type: "text",
        template_name: "",
        template_language: "en_US",
        message_body: "",
        scheduled_at: "",
        case_id: "",
        max_retries: "3",
      });
      fetchNotifications();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail;
      let message = "Failed to create notification.";
      if (typeof detail === "string") {
        message = detail;
      } else if (Array.isArray(detail)) {
        message = detail.map((d: { msg?: string; loc?: string[] }) =>
          `${(d.loc ?? []).join(".")}: ${d.msg ?? "invalid"}`
        ).join("; ");
      }
      setCreateError(message);
    } finally {
      setCreateLoading(false);
    }
  }

  async function handleSendNow(e: FormEvent) {
    e.preventDefault();
    setSendError("");
    setSuccessMsg("");
    setSendLoading(true);

    try {
      const res = await api.post("/notifications/send", {
        recipient_phone: sendForm.recipient_phone,
        message_type: sendForm.message_type,
        template_name: sendForm.template_name || null,
        template_language: sendForm.template_language,
        message_body: sendForm.message_body || null,
      });
      if (res.data.success) {
        setSuccessMsg(
          `Message sent! WhatsApp ID: ${res.data.whatsapp_message_id ?? "N/A"}`
        );
      } else {
        setSendError(res.data.error ?? "Send failed.");
      }
      setShowSend(false);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail;
      let message = "Failed to send message.";
      if (typeof detail === "string") {
        message = detail;
      } else if (Array.isArray(detail)) {
        message = detail.map((d: { msg?: string; loc?: string[] }) =>
          `${(d.loc ?? []).join(".")}: ${d.msg ?? "invalid"}`
        ).join("; ");
      }
      setSendError(message);
    } finally {
      setSendLoading(false);
    }
  }

  async function handleProcessPending() {
    setProcessLoading(true);
    setSuccessMsg("");
    setError("");

    try {
      const res = await api.post("/notifications/process");
      setSuccessMsg(
        `Processed: ${res.data.processed ?? 0} sent, ${res.data.failed ?? 0} failed.`
      );
      fetchNotifications();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to process pending notifications.";
      setError(message);
    } finally {
      setProcessLoading(false);
    }
  }

  async function handleListTemplates() {
    setTemplatesLoading(true);
    setShowTemplates(!showTemplates);

    if (!showTemplates) {
      try {
        const res = await api.get("/notifications/templates/list");
        setTemplates(res.data);
      } catch (err: unknown) {
        const message =
          (err as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail ?? "Failed to load templates.";
        setError(message);
      }
    }
    setTemplatesLoading(false);
  }

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending: "bg-yellow-100 text-yellow-800",
      sent: "bg-green-100 text-green-800",
      failed: "bg-red-100 text-red-800",
      cancelled: "bg-gray-100 text-gray-800",
    };
    return colors[status] ?? "bg-gray-100 text-gray-800";
  };

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold text-gray-800">
          Notifications ({total})
        </h1>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => {
              setShowCreate(!showCreate);
              setShowSend(false);
            }}
            className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            {showCreate ? "Cancel" : "Create Notification"}
          </button>
          <button
            onClick={() => {
              setShowSend(!showSend);
              setShowCreate(false);
            }}
            className="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700"
          >
            {showSend ? "Cancel" : "Send Now"}
          </button>
          <button
            onClick={handleProcessPending}
            disabled={processLoading}
            className="rounded bg-orange-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-orange-700 disabled:opacity-50"
          >
            {processLoading ? "Processing..." : "Process Pending"}
          </button>
          <button
            onClick={handleListTemplates}
            disabled={templatesLoading}
            className="rounded bg-gray-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
          >
            {showTemplates ? "Hide Templates" : "List Templates"}
          </button>
        </div>
      </div>

      {successMsg && (
        <div className="mb-4 rounded bg-green-50 p-3 text-sm text-green-700 border border-green-200">
          {successMsg}
        </div>
      )}
      {error && (
        <div className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
          {error}
        </div>
      )}
      {sendError && (
        <div className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
          {sendError}
        </div>
      )}

      {/* Templates list */}
      {showTemplates && (
        <div className="mb-6 rounded-lg bg-white p-4 shadow-sm border border-gray-200">
          <h2 className="mb-3 text-lg font-semibold text-gray-700">
            WhatsApp Templates
          </h2>
          {templates.length === 0 ? (
            <p className="text-sm text-gray-500">No templates found.</p>
          ) : (
            <pre className="text-xs text-gray-700 bg-gray-50 p-3 rounded overflow-x-auto max-h-60">
              {JSON.stringify(templates, null, 2)}
            </pre>
          )}
        </div>
      )}

      {/* Create Notification Form */}
      {showCreate && (
        <div className="mb-6 rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <h2 className="mb-4 text-lg font-semibold text-gray-700">
            Create Notification
          </h2>
          {createError && (
            <div className="mb-3 rounded bg-red-50 p-2 text-xs text-red-700 border border-red-200">
              {createError}
            </div>
          )}
          <form onSubmit={handleCreate} className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Recipient Phone *
              </label>
              <input
                required
                value={createForm.recipient_phone}
                onChange={(e) =>
                  setCreateForm({
                    ...createForm,
                    recipient_phone: e.target.value,
                  })
                }
                placeholder="e.g. 905551234567"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Recipient Name
              </label>
              <input
                value={createForm.recipient_name}
                onChange={(e) =>
                  setCreateForm({
                    ...createForm,
                    recipient_name: e.target.value,
                  })
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Message Type *
              </label>
              <select
                value={createForm.message_type}
                onChange={(e) =>
                  setCreateForm({
                    ...createForm,
                    message_type: e.target.value as "text" | "template",
                  })
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="text">Text</option>
                <option value="template">Template</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Template Name
              </label>
              <input
                value={createForm.template_name}
                onChange={(e) =>
                  setCreateForm({
                    ...createForm,
                    template_name: e.target.value,
                  })
                }
                placeholder="Required for template type"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="block text-sm font-medium text-gray-700">
                Message Body
              </label>
              <textarea
                value={createForm.message_body}
                onChange={(e) =>
                  setCreateForm({
                    ...createForm,
                    message_body: e.target.value,
                  })
                }
                rows={3}
                placeholder="Required for text type"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Scheduled At *
              </label>
              <input
                type="datetime-local"
                required
                value={createForm.scheduled_at}
                onChange={(e) =>
                  setCreateForm({
                    ...createForm,
                    scheduled_at: e.target.value,
                  })
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Case ID
              </label>
              <input
                value={createForm.case_id}
                onChange={(e) =>
                  setCreateForm({ ...createForm, case_id: e.target.value })
                }
                placeholder="UUID (optional)"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Max Retries
              </label>
              <input
                type="number"
                min="0"
                max="10"
                value={createForm.max_retries}
                onChange={(e) =>
                  setCreateForm({
                    ...createForm,
                    max_retries: e.target.value,
                  })
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div className="sm:col-span-2">
              <button
                type="submit"
                disabled={createLoading}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {createLoading ? "Creating..." : "Create Notification"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Send Now Form */}
      {showSend && (
        <div className="mb-6 rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <h2 className="mb-4 text-lg font-semibold text-gray-700">
            Send Message Now
          </h2>
          <form onSubmit={handleSendNow} className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Recipient Phone *
              </label>
              <input
                required
                value={sendForm.recipient_phone}
                onChange={(e) =>
                  setSendForm({
                    ...sendForm,
                    recipient_phone: e.target.value,
                  })
                }
                placeholder="e.g. 905551234567"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Message Type *
              </label>
              <select
                value={sendForm.message_type}
                onChange={(e) =>
                  setSendForm({
                    ...sendForm,
                    message_type: e.target.value as "text" | "template",
                  })
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="text">Text</option>
                <option value="template">Template</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Template Name
              </label>
              <input
                value={sendForm.template_name}
                onChange={(e) =>
                  setSendForm({ ...sendForm, template_name: e.target.value })
                }
                placeholder="Required for template type"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Template Language
              </label>
              <input
                value={sendForm.template_language}
                onChange={(e) =>
                  setSendForm({
                    ...sendForm,
                    template_language: e.target.value,
                  })
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="block text-sm font-medium text-gray-700">
                Message Body
              </label>
              <textarea
                value={sendForm.message_body}
                onChange={(e) =>
                  setSendForm({ ...sendForm, message_body: e.target.value })
                }
                rows={3}
                placeholder="Required for text type"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div className="sm:col-span-2">
              <button
                type="submit"
                disabled={sendLoading}
                className="rounded bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                {sendLoading ? "Sending..." : "Send Now"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Notifications Table */}
      {loading ? (
        <p className="text-gray-500">Loading notifications...</p>
      ) : notifications.length === 0 ? (
        <p className="text-gray-500">No notifications found.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg bg-white shadow-sm border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Recipient
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Type
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Scheduled At
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Message
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {notifications.map((n) => (
                <tr key={n.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm">
                    <div className="font-medium text-gray-700">
                      {n.recipient_phone}
                    </div>
                    {n.recipient_name && (
                      <div className="text-xs text-gray-400">
                        {n.recipient_name}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600 capitalize">
                    {n.message_type}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${statusBadge(n.status)}`}
                    >
                      {n.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {new Date(n.scheduled_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600 max-w-xs truncate">
                    {n.template_name ?? n.message_body ?? "N/A"}
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
