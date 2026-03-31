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
  is_cancelled: boolean;
  cancelled_at: string | null;
  cancelled_by: string | null;
  created_at: string;
}

interface DocumentItem {
  id: string;
  case_id: string;
  uploaded_by: string;
  filename: string;
  file_type: string | null;
  file_size: number | null;
  status: string;
  document_type: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
  created_at: string;
}

interface RequiredDocument {
  id: string;
  case_id: string;
  document_name: string;
  status: string;
  document_id: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

const STATUS_OPTIONS = ["open", "in_progress", "under_review", "closed"] as const;

const STATUS_LABELS: Record<string, string> = {
  open: "Open",
  in_progress: "In Progress",
  under_review: "Under Review",
  closed: "Completed",
};

const DOC_STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  pending: { label: "Bekleniyor", color: "bg-yellow-100 text-yellow-800 border-yellow-300" },
  uploaded: { label: "İnceleme Bekliyor", color: "bg-blue-100 text-blue-800 border-blue-300" },
  approved: { label: "Onaylandı", color: "bg-green-100 text-green-800 border-green-300" },
  rejected: { label: "Reddedildi", color: "bg-red-100 text-red-800 border-red-300" },
  cancelled: { label: "İptal Edildi", color: "bg-gray-100 text-gray-500 border-gray-300" },
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
  const [requiredDocs, setRequiredDocs] = useState<RequiredDocument[]>([]);
  const [userRole, setUserRole] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Note form
  const [noteContent, setNoteContent] = useState("");
  const [noteLoading, setNoteLoading] = useState(false);
  const [noteError, setNoteError] = useState("");
  const [noteSuccess, setNoteSuccess] = useState("");

  // Document upload
  const [docFile, setDocFile] = useState<File | null>(null);
  const [docType, setDocType] = useState("");
  const [docLoading, setDocLoading] = useState(false);
  const [docError, setDocError] = useState("");
  const [docSuccess, setDocSuccess] = useState("");

  // Status update
  const [statusLoading, setStatusLoading] = useState(false);
  const [statusError, setStatusError] = useState("");
  const [statusSuccess, setStatusSuccess] = useState("");

  // Review
  const [reviewLoading, setReviewLoading] = useState<string | null>(null);
  const [rejectDocId, setRejectDocId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");

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

  const fetchRequiredDocs = useCallback(async () => {
    try {
      const res = await api.get<{ required_documents: RequiredDocument[] }>(
        `/cases/${id}/required-documents`
      );
      setRequiredDocs(res.data.required_documents);
    } catch {
      // silently fail
    }
  }, [id]);

  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      try {
        const [caseRes, meRes] = await Promise.all([
          api.get<CaseDetail>(`/cases/${id}`),
          api.get<{ role: string }>("/auth/me"),
        ]);
        if (cancelled) return;
        setCaseData(caseRes.data);
        setUserRole(meRes.data.role);

        const [notesRes, docsRes, reqDocsRes] = await Promise.all([
          api.get<CaseNote[]>(`/cases/${id}/notes`),
          api.get<{ documents: DocumentItem[] }>(`/cases/${id}/documents`),
          api.get<{ required_documents: RequiredDocument[] }>(`/cases/${id}/required-documents`),
        ]);
        if (cancelled) return;
        setNotes(notesRes.data);
        setDocuments(docsRes.data.documents);
        setRequiredDocs(reqDocsRes.data.required_documents);
      } catch {
        if (!cancelled) setError("Failed to load case details.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchData();
    return () => { cancelled = true; };
  }, [id]);

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

  async function handleCancelNote(noteId: string) {
    const confirmed = window.confirm(
      "Bu mesajı iptal etmek istediğinize emin misiniz? Bu işlem geri alınamaz."
    );
    if (!confirmed) return;

    setNoteError("");
    setNoteSuccess("");

    try {
      await api.patch(`/cases/${id}/notes/${noteId}/cancel`);
      setNoteSuccess("Mesaj iptal edildi.");
      await fetchNotes();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Mesaj iptal edilemedi.";
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
      if (docType) {
        formData.append("document_type", docType);
      }

      await api.post(`/cases/${id}/documents`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setDocSuccess("Document uploaded.");
      setDocFile(null);
      setDocType("");
      const fileInput = document.getElementById(
        "doc-upload"
      ) as HTMLInputElement;
      if (fileInput) fileInput.value = "";
      await Promise.all([fetchDocuments(), fetchRequiredDocs()]);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to upload document.";
      setDocError(message);
    } finally {
      setDocLoading(false);
    }
  }

  async function handleCancelDocument(documentId: string) {
    const confirmed = window.confirm(
      "Bu belgeyi iptal etmek istediğinize emin misiniz? Bu işlem geri alınamaz."
    );
    if (!confirmed) return;

    setDocError("");
    setDocSuccess("");

    try {
      await api.patch(`/documents/${documentId}/cancel`);
      setDocSuccess("Belge iptal edildi.");
      await Promise.all([fetchDocuments(), fetchRequiredDocs()]);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Belge iptal edilemedi.";
      setDocError(message);
    }
  }

  async function handleReview(documentId: string, action: "approve" | "reject", reason?: string) {
    setReviewLoading(documentId);
    setDocError("");

    try {
      const body: { action: string; rejection_reason?: string } = { action };
      if (action === "reject" && reason) {
        body.rejection_reason = reason;
      }
      await api.patch(`/documents/${documentId}/review`, body);
      setRejectDocId(null);
      setRejectReason("");
      await Promise.all([fetchDocuments(), fetchRequiredDocs()]);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to review document.";
      setDocError(message);
    } finally {
      setReviewLoading(null);
    }
  }

  async function handleGenerateRequiredDocs() {
    try {
      await api.post(`/cases/${id}/required-documents/generate`);
      await fetchRequiredDocs();
    } catch {
      // silently fail
    }
  }

  // Required docs that need upload (pending or rejected)
  const uploadableRequiredDocs = requiredDocs.filter((r) => r.status === "pending" || r.status === "rejected");

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

      {/* Required Documents Section */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow-sm border border-gray-200">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-700">
            Zorunlu Evraklar ({requiredDocs.length})
          </h2>
          {requiredDocs.length === 0 && caseData.jurisdiction && (
            <button
              type="button"
              onClick={handleGenerateRequiredDocs}
              className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
            >
              Zorunlu Evrakları Oluştur
            </button>
          )}
        </div>

        {requiredDocs.length === 0 ? (
          <p className="text-sm text-gray-400">
            {caseData.jurisdiction
              ? "Bu case için henüz zorunlu evrak tanımlanmamış. Yukarıdaki butona tıklayarak oluşturabilirsiniz."
              : "Zorunlu evrak oluşturmak için case'in jurisdiction alanı dolu olmalıdır."}
          </p>
        ) : (
          <div className="space-y-3">
            {/* Progress summary */}
            {(() => {
              const approved = requiredDocs.filter((r) => r.status === "approved").length;
              const total = requiredDocs.length;
              return (
                <div className="flex items-center gap-3 mb-2">
                  <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-green-500 rounded-full transition-all"
                      style={{ width: `${total > 0 ? (approved / total) * 100 : 0}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-500 font-medium whitespace-nowrap">
                    {approved}/{total} onaylandı
                  </span>
                </div>
              );
            })()}
            {requiredDocs.map((req) => {
              const statusConfig = DOC_STATUS_CONFIG[req.status] ?? DOC_STATUS_CONFIG.pending;
              const linkedDoc = documents.find((d) => d.id === req.document_id);
              const canUpload = req.status === "pending" || req.status === "rejected";
              return (
                <div
                  key={req.id}
                  className={`rounded-lg p-4 border ${req.status === "approved" ? "bg-green-50 border-green-200" : req.status === "rejected" ? "bg-red-50 border-red-200" : "bg-gray-50 border-gray-100"}`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3">
                        {req.status === "approved" && (
                          <svg className="h-4 w-4 text-green-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                        )}
                        <p className="text-sm font-medium text-gray-800">
                          {req.document_name}
                        </p>
                        <span
                          className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${statusConfig.color}`}
                        >
                          {statusConfig.label}
                        </span>
                      </div>
                      {linkedDoc && (
                        <p className="mt-1 text-xs text-gray-500 ml-7">
                          Dosya: {linkedDoc.filename}
                          {linkedDoc.reviewed_at && (
                            <> &middot; İnceleme: {new Date(linkedDoc.reviewed_at).toLocaleDateString()}</>
                          )}
                        </p>
                      )}
                      {req.status === "rejected" && linkedDoc?.rejection_reason && (
                        <p className="mt-1 text-xs text-red-600 ml-7">
                          Red sebebi: {linkedDoc.rejection_reason}
                        </p>
                      )}
                    </div>
                    <div className="ml-3 shrink-0">
                      {canUpload && (
                        <button
                          type="button"
                          onClick={() => {
                            setDocType(req.document_name);
                            const el = document.getElementById("doc-upload");
                            if (el) el.scrollIntoView({ behavior: "smooth" });
                            el?.click();
                          }}
                          className="rounded bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700"
                        >
                          {req.status === "rejected" ? "Tekrar Yükle" : "Yükle"}
                        </button>
                      )}
                      {req.status === "uploaded" && (
                        <span className="text-xs text-blue-600 font-medium">Avukat incelemesi bekleniyor</span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
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
                  className={`rounded p-3 border ${note.is_cancelled ? "bg-gray-100 border-gray-200" : "bg-gray-50 border-gray-100"}`}
                >
                  {note.is_cancelled ? (
                    <div>
                      {userRole === "admin" ? (
                        <div>
                          <div className="flex items-center gap-2 mb-1">
                            <span className="inline-flex items-center rounded-full bg-gray-200 border border-gray-300 px-2 py-0.5 text-xs font-medium text-gray-500">İptal Edildi</span>
                          </div>
                          <p className="text-sm text-gray-400 line-through whitespace-pre-wrap">{note.content}</p>
                        </div>
                      ) : (
                        <p className="text-sm text-gray-400 italic">Bu mesaj iptal edildi.</p>
                      )}
                    </div>
                  ) : (
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm text-gray-700 whitespace-pre-wrap flex-1">
                        {note.content}
                      </p>
                      <button
                        type="button"
                        onClick={() => handleCancelNote(note.id)}
                        className="shrink-0 rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600"
                        title="Mesajı iptal et"
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
                            d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"
                          />
                        </svg>
                      </button>
                    </div>
                  )}
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

          <form onSubmit={handleUploadDoc} className="mb-4 space-y-2">
            <input
              id="doc-upload"
              type="file"
              onChange={(e) => setDocFile(e.target.files?.[0] ?? null)}
              className="w-full text-sm text-gray-500 file:mr-4 file:rounded file:border-0 file:bg-blue-50 file:px-4 file:py-2 file:text-sm file:font-medium file:text-blue-700 hover:file:bg-blue-100"
            />
            {uploadableRequiredDocs.length > 0 && (
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="">Evrak türü seçin (opsiyonel)</option>
                {uploadableRequiredDocs.map((req) => (
                  <option key={req.id} value={req.document_name}>
                    {req.document_name}{req.status === "rejected" ? " (Reddedildi - Tekrar Yükle)" : ""}
                  </option>
                ))}
              </select>
            )}
            <button
              type="submit"
              disabled={docLoading || !docFile}
              className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {docLoading ? "Uploading..." : "Upload Document"}
            </button>
          </form>

          <div className="space-y-2 max-h-[500px] overflow-y-auto">
            {documents.length === 0 ? (
              <p className="text-sm text-gray-400">No documents yet.</p>
            ) : (
              documents.map((doc) => {
                const docStatusConfig = DOC_STATUS_CONFIG[doc.status] ?? DOC_STATUS_CONFIG.uploaded;
                return (
                  <div
                    key={doc.id}
                    className="rounded-lg bg-gray-50 p-3 border border-gray-100"
                  >
                    <div className="flex items-center justify-between">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium text-gray-700 truncate">
                            {doc.filename}
                          </p>
                          <span
                            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${docStatusConfig.color}`}
                          >
                            {docStatusConfig.label}
                          </span>
                        </div>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {doc.file_type ?? "unknown"} &middot;{" "}
                          {doc.file_size
                            ? `${(doc.file_size / 1024).toFixed(1)} KB`
                            : "N/A"}{" "}
                          &middot;{" "}
                          {new Date(doc.created_at).toLocaleDateString()}
                          {doc.document_type && (
                            <> &middot; Tür: {doc.document_type}</>
                          )}
                        </p>
                        {doc.rejection_reason && (
                          <p className="text-xs text-red-600 mt-1">
                            Red sebebi: {doc.rejection_reason}
                          </p>
                        )}
                      </div>
                      <div className="ml-3 flex items-center gap-2 shrink-0">
                        {doc.status !== "cancelled" && (
                          <>
                            <button
                              type="button"
                              onClick={async () => {
                                try {
                                  const res = await api.get(
                                    `/documents/${doc.id}/download`,
                                    { responseType: "blob" }
                                  );
                                  const url = window.URL.createObjectURL(res.data);
                                  const a = document.createElement("a");
                                  a.href = url;
                                  a.download = doc.filename;
                                  a.click();
                                  window.URL.revokeObjectURL(url);
                                } catch {
                                  alert("Failed to download document.");
                                }
                              }}
                              className="text-xs text-blue-600 hover:underline"
                            >
                              İndir
                            </button>
                            <button
                              type="button"
                              onClick={() => handleCancelDocument(doc.id)}
                              className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600"
                              title="Belgeyi iptal et"
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
                                  d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"
                                />
                              </svg>
                            </button>
                          </>
                        )}
                      </div>
                    </div>

                    {/* Review actions - only for admin/lawyer on uploaded docs */}
                    {doc.status === "uploaded" && (userRole === "admin" || userRole === "lawyer") && (
                      <div className="mt-2 pt-2 border-t border-gray-200">
                        {rejectDocId === doc.id ? (
                          <div className="flex items-center gap-2">
                            <input
                              type="text"
                              value={rejectReason}
                              onChange={(e) => setRejectReason(e.target.value)}
                              placeholder="Red sebebini yazın..."
                              className="flex-1 rounded border border-gray-300 px-2 py-1 text-xs focus:border-red-500 focus:outline-none"
                            />
                            <button
                              type="button"
                              onClick={() => {
                                if (rejectReason.trim()) {
                                  handleReview(doc.id, "reject", rejectReason);
                                }
                              }}
                              disabled={!rejectReason.trim() || reviewLoading === doc.id}
                              className="rounded bg-red-600 px-2 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
                            >
                              Reddet
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setRejectDocId(null);
                                setRejectReason("");
                              }}
                              className="text-xs text-gray-500 hover:text-gray-700"
                            >
                              İptal
                            </button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => handleReview(doc.id, "approve")}
                              disabled={reviewLoading === doc.id}
                              className="rounded bg-green-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                            >
                              {reviewLoading === doc.id ? "..." : "Onayla"}
                            </button>
                            <button
                              type="button"
                              onClick={() => setRejectDocId(doc.id)}
                              disabled={reviewLoading === doc.id}
                              className="rounded bg-red-50 px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-100 border border-red-200 disabled:opacity-50"
                            >
                              Reddet
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
