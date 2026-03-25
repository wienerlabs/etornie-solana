"use client";

import { useEffect, useState, FormEvent, useCallback } from "react";
import { use } from "react";
import Link from "next/link";
import api from "@/lib/api";

interface CaseDetail {
  id: string;
  case_number: string;
  title: string;
  description: string | null;
  case_type: string;
  status: string;
  client_id: string;
  assigned_lawyer_id: string | null;
  jurisdiction: string | null;
  filing_date: string | null;
  deadline: string | null;
  created_at: string;
  updated_at: string;
}

interface CaseNote {
  id: string;
  case_id: string;
  author_id: string;
  content: string;
  created_at: string;
}

interface DocumentItem {
  id: string;
  case_id: string;
  uploaded_by: string;
  filename: string;
  file_type: string | null;
  file_size: number | null;
  created_at: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const STATUS_OPTIONS = ["open", "in_progress", "under_review", "closed"] as const;

const STATUS_LABELS: Record<string, string> = {
  open: "Open",
  in_progress: "In Progress",
  under_review: "Under Review",
  closed: "Completed",
};

export default function CaseDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [caseData, setCaseData] = useState<CaseDetail | null>(null);
  const [notes, setNotes] = useState<CaseNote[]>([]);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Note form
  const [noteContent, setNoteContent] = useState("");
  const [noteLoading, setNoteLoading] = useState(false);
  const [noteError, setNoteError] = useState("");
  const [noteSuccess, setNoteSuccess] = useState("");

  // Document upload
  const [docFile, setDocFile] = useState<File | null>(null);
  const [docLoading, setDocLoading] = useState(false);
  const [docError, setDocError] = useState("");
  const [docSuccess, setDocSuccess] = useState("");

  // Status update
  const [statusLoading, setStatusLoading] = useState(false);
  const [statusError, setStatusError] = useState("");
  const [statusSuccess, setStatusSuccess] = useState("");

  const fetchNotes = useCallback(async () => {
    try {
      const res = await api.get<CaseNote[]>(`/cases/${id}/notes`);
      setNotes(res.data);
    } catch {
      // silently fail
    }
  }, [id]);

  const fetchDocuments = useCallback(async () => {
    try {
      const res = await api.get<{ documents: DocumentItem[] }>(
        `/cases/${id}/documents`
      );
      setDocuments(res.data.documents);
    } catch {
      // silently fail
    }
  }, [id]);

  useEffect(() => {
    async function fetchData() {
      try {
        const [caseRes] = await Promise.all([
          api.get<CaseDetail>(`/cases/${id}`),
        ]);
        setCaseData(caseRes.data);
        await Promise.all([fetchNotes(), fetchDocuments()]);
      } catch {
        setError("Failed to load case details.");
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, [id, fetchNotes, fetchDocuments]);

  async function handleStatusChange(newStatus: string) {
    setStatusError("");
    setStatusSuccess("");
    setStatusLoading(true);

    try {
      const res = await api.patch<CaseDetail>(`/cases/${id}`, {
        status: newStatus,
      });
      setCaseData(res.data);
      setStatusSuccess("Status updated.");
      setTimeout(() => setStatusSuccess(""), 3000);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to update status.";
      setStatusError(message);
    } finally {
      setStatusLoading(false);
    }
  }

  async function handleAddNote(e: FormEvent) {
    e.preventDefault();
    setNoteError("");
    setNoteSuccess("");
    setNoteLoading(true);

    try {
      await api.post(`/cases/${id}/notes`, { content: noteContent });
      setNoteSuccess("Note added successfully.");
      setNoteContent("");
      await fetchNotes();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to add note.";
      setNoteError(message);
    } finally {
      setNoteLoading(false);
    }
  }

  async function handleDeleteNote(noteId: string) {
    const confirmed = window.confirm(
      "Are you sure you want to delete this note?"
    );
    if (!confirmed) return;

    setNoteError("");
    setNoteSuccess("");

    try {
      await api.delete(`/cases/${id}/notes/${noteId}`);
      setNoteSuccess("Note deleted.");
      await fetchNotes();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to delete note.";
      setNoteError(message);
    }
  }

  async function handleUploadDoc(e: FormEvent) {
    e.preventDefault();
    if (!docFile) return;

    setDocError("");
    setDocSuccess("");
    setDocLoading(true);

    try {
      const formData = new FormData();
      formData.append("file", docFile);

      await api.post(`/cases/${id}/documents`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setDocSuccess("Document uploaded.");
      setDocFile(null);
      // Reset file input
      const fileInput = document.getElementById(
        "doc-upload"
      ) as HTMLInputElement;
      if (fileInput) fileInput.value = "";
      await fetchDocuments();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to upload document.";
      setDocError(message);
    } finally {
      setDocLoading(false);
    }
  }

  async function handleDeleteDocument(documentId: string) {
    const confirmed = window.confirm(
      "Are you sure you want to delete this document?"
    );
    if (!confirmed) return;

    setDocError("");
    setDocSuccess("");

    try {
      await api.delete(`/documents/${documentId}`);
      setDocSuccess("Document deleted.");
      await fetchDocuments();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to delete document.";
      setDocError(message);
    }
  }

  if (loading) {
    return <p className="text-gray-500">Loading case details...</p>;
  }

  if (error) {
    return (
      <div>
        <div className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
          {error}
        </div>
        <Link
          href="/dashboard/cases"
          className="text-blue-600 hover:underline text-sm"
        >
          Back to cases
        </Link>
      </div>
    );
  }

  if (!caseData) return null;

  const statusColors: Record<string, string> = {
    open: "bg-green-100 text-green-800",
    in_progress: "bg-blue-100 text-blue-800",
    under_review: "bg-yellow-100 text-yellow-800",
    closed: "bg-gray-100 text-gray-800",
  };

  return (
    <div>
      <Link
        href="/dashboard/cases"
        className="mb-4 inline-block text-sm text-blue-600 hover:underline"
      >
        &larr; Back to Cases
      </Link>

      {/* Case Info */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow-sm border border-gray-200">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-800">
              {caseData.title}
            </h1>
            <p className="mt-1 text-sm text-gray-500">
              {caseData.case_number}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex flex-col items-end gap-1">
              <label
                htmlFor="status-select"
                className="text-xs text-gray-500 uppercase"
              >
                Status
              </label>
              <select
                id="status-select"
                value={caseData.status}
                onChange={(e) => handleStatusChange(e.target.value)}
                disabled={statusLoading}
                className={`rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium focus:border-blue-500 focus:outline-none disabled:opacity-50 ${statusColors[caseData.status] ?? "bg-gray-100 text-gray-800"}`}
              >
                {STATUS_OPTIONS.map((s) => (
                  <option key={s} value={s}>
                    {STATUS_LABELS[s]}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {statusSuccess && (
          <div className="mt-2 rounded bg-green-50 p-2 text-xs text-green-700 border border-green-200">
            {statusSuccess}
          </div>
        )}
        {statusError && (
          <div className="mt-2 rounded bg-red-50 p-2 text-xs text-red-700 border border-red-200">
            {statusError}
          </div>
        )}

        {caseData.description && (
          <p className="mt-4 text-sm text-gray-700">{caseData.description}</p>
        )}

        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div>
            <p className="text-xs text-gray-500 uppercase">Type</p>
            <p className="text-sm font-medium capitalize">
              {caseData.case_type}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase">Jurisdiction</p>
            <p className="text-sm font-medium">
              {caseData.jurisdiction ?? "N/A"}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase">Filing Date</p>
            <p className="text-sm font-medium">
              {caseData.filing_date ?? "N/A"}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase">Deadline</p>
            <p className="text-sm font-medium text-orange-600">
              {caseData.deadline ?? "N/A"}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase">Client ID</p>
            <p className="text-sm font-medium font-mono text-xs break-all">
              {caseData.client_id}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase">Lawyer ID</p>
            <p className="text-sm font-medium font-mono text-xs break-all">
              {caseData.assigned_lawyer_id ?? "N/A"}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase">Created</p>
            <p className="text-sm font-medium">
              {new Date(caseData.created_at).toLocaleDateString()}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase">Updated</p>
            <p className="text-sm font-medium">
              {new Date(caseData.updated_at).toLocaleDateString()}
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Notes Section */}
        <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <h2 className="mb-4 text-lg font-semibold text-gray-700">
            Notes ({notes.length})
          </h2>

          {noteSuccess && (
            <div className="mb-3 rounded bg-green-50 p-2 text-xs text-green-700 border border-green-200">
              {noteSuccess}
            </div>
          )}
          {noteError && (
            <div className="mb-3 rounded bg-red-50 p-2 text-xs text-red-700 border border-red-200">
              {noteError}
            </div>
          )}

          <form onSubmit={handleAddNote} className="mb-4">
            <textarea
              value={noteContent}
              onChange={(e) => setNoteContent(e.target.value)}
              required
              rows={3}
              placeholder="Add a note..."
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
            <button
              type="submit"
              disabled={noteLoading}
              className="mt-2 rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {noteLoading ? "Adding..." : "Add Note"}
            </button>
          </form>

          <div className="space-y-3 max-h-80 overflow-y-auto">
            {notes.length === 0 ? (
              <p className="text-sm text-gray-400">No notes yet.</p>
            ) : (
              notes.map((note) => (
                <div
                  key={note.id}
                  className="rounded bg-gray-50 p-3 border border-gray-100"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm text-gray-700 whitespace-pre-wrap flex-1">
                      {note.content}
                    </p>
                    <button
                      type="button"
                      onClick={() => handleDeleteNote(note.id)}
                      className="shrink-0 rounded p-1 text-red-400 hover:bg-red-50 hover:text-red-600"
                      title="Delete note"
                    >
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        className="h-4 w-4"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                        />
                      </svg>
                    </button>
                  </div>
                  <p className="mt-1 text-xs text-gray-400">
                    {new Date(note.created_at).toLocaleString()} &middot;
                    Author: {note.author_id.slice(0, 8)}...
                  </p>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Documents Section */}
        <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <h2 className="mb-4 text-lg font-semibold text-gray-700">
            Documents ({documents.length})
          </h2>

          {docSuccess && (
            <div className="mb-3 rounded bg-green-50 p-2 text-xs text-green-700 border border-green-200">
              {docSuccess}
            </div>
          )}
          {docError && (
            <div className="mb-3 rounded bg-red-50 p-2 text-xs text-red-700 border border-red-200">
              {docError}
            </div>
          )}

          <form onSubmit={handleUploadDoc} className="mb-4">
            <input
              id="doc-upload"
              type="file"
              onChange={(e) => setDocFile(e.target.files?.[0] ?? null)}
              className="w-full text-sm text-gray-500 file:mr-4 file:rounded file:border-0 file:bg-blue-50 file:px-4 file:py-2 file:text-sm file:font-medium file:text-blue-700 hover:file:bg-blue-100"
            />
            <button
              type="submit"
              disabled={docLoading || !docFile}
              className="mt-2 rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {docLoading ? "Uploading..." : "Upload Document"}
            </button>
          </form>

          <div className="space-y-2 max-h-80 overflow-y-auto">
            {documents.length === 0 ? (
              <p className="text-sm text-gray-400">No documents yet.</p>
            ) : (
              documents.map((doc) => (
                <div
                  key={doc.id}
                  className="flex items-center justify-between rounded bg-gray-50 p-3 border border-gray-100"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-700 truncate">
                      {doc.filename}
                    </p>
                    <p className="text-xs text-gray-400">
                      {doc.file_type ?? "unknown"} &middot;{" "}
                      {doc.file_size
                        ? `${(doc.file_size / 1024).toFixed(1)} KB`
                        : "N/A"}{" "}
                      &middot;{" "}
                      {new Date(doc.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="ml-3 flex items-center gap-2 shrink-0">
                    <a
                      href={`${API_URL}/documents/${doc.id}/download`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-blue-600 hover:underline"
                    >
                      Download
                    </a>
                    <button
                      type="button"
                      onClick={() => handleDeleteDocument(doc.id)}
                      className="rounded p-1 text-red-400 hover:bg-red-50 hover:text-red-600"
                      title="Delete document"
                    >
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        className="h-4 w-4"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                        />
                      </svg>
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
