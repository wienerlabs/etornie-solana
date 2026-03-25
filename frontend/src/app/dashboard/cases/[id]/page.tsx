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
      setDocSuccess("Document uploaded successfully.");
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
          <span
            className={`rounded-full px-3 py-1 text-xs font-medium ${statusColors[caseData.status] ?? "bg-gray-100 text-gray-800"}`}
          >
            {caseData.status.replace("_", " ")}
          </span>
        </div>

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
                  <p className="text-sm text-gray-700 whitespace-pre-wrap">
                    {note.content}
                  </p>
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
                  <div>
                    <p className="text-sm font-medium text-gray-700">
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
                  <a
                    href={`http://localhost:8000/documents/${doc.id}/download`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-600 hover:underline"
                  >
                    Download
                  </a>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
