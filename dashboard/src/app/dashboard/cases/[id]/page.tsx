"use client";

import { useEffect, useState, FormEvent, useCallback } from "react";
import { use } from "react";
import Link from "next/link";
import { useWallet } from "@solana/wallet-adapter-react";
import {
  Connection,
  PublicKey,
  TransactionInstruction,
  TransactionMessage,
  VersionedTransaction,
} from "@solana/web3.js";
import api, { extractErrorMessage } from "@/lib/api";
import { AttestationCard } from "@/components/AttestationCard";
import { RenewalCard } from "@/components/RenewalCard";
import { NftCard } from "@/components/NftCard";
import { BRAIDInsightsPanel } from "@/components/BRAIDInsightsPanel";
import { UKIPOPanel } from "@/components/UKIPOPanel";
import { prepareFileOwnershipInput } from "@/lib/zk/fileOwnership";
import { proveDocumentOwnershipOnChain } from "@/lib/zk/submitFileOwnership";

const SOLANA_CLUSTER_URL =
  process.env.NEXT_PUBLIC_SOLANA_CLUSTER_URL ??
  "https://api.devnet.solana.com";

const EVENT_TYPE_LABELS: Record<number, string> = {
  1: "Status changed",
  2: "Document uploaded",
  3: "Proposal generated",
  4: "Proposal accepted",
  5: "Proposal rejected",
  6: "Note added",
  99: "Case closed",
};

interface PendingEventAttestation {
  program_id: string;
  operator: string;
  pda: string;
  ix_data_b64: string;
  recent_blockhash: string;
  event_type: number;
  metadata_hash_hex: string;
}

interface CaseEventItem {
  id: string;
  case_id: string;
  event_type: number;
  tx_signature: string;
  actor_wallet: string;
  metadata_hash: string;
  created_at: string;
}

function base64ToBytes(b64: string): Uint8Array {
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

function bytesToHex(bytes: Uint8Array): string {
  let out = "";
  for (let i = 0; i < bytes.length; i += 1) {
    out += bytes[i].toString(16).padStart(2, "0");
  }
  return out;
}

/** Render a BN254 field element as a 64-char hex string (32 bytes, BE). */
function bigintToHex32(x: bigint): string {
  let hex = x.toString(16);
  if (hex.length > 64) {
    throw new Error(`bigint does not fit in 32 bytes: ${x}`);
  }
  return hex.padStart(64, "0");
}

const SPECIAL_NOTES_CORRUPTION_ARTIFACTS = [
  "applicationlar",
  "andrilmek",
  "sonrasınalso",
  "alsorıca",
  "feene",
  "alsohil",
  "saalsoce",
  "registrationi",
  "için",
  "ayrıca",
  "kullanım",
  "ürettiği",
  "müşteri",
  "evrak",
  "traalsomark",
  "aleşik",
  "alsoğişmektedir",
  "alsoğil",
] as const;

const TURKISH_SUFFIX_PATTERN = /\b\w{3,}(?:nın|nin|nun|nün)\b/;

/**
 * countries_parsed.json carries ~22 special_notes entries that survived
 * the LLM cleanup with Turkish/English corruption still in them. We
 * skip rendering those rather than showing garbled text. Mirrors the
 * Python heuristic in services/api/scripts/clean_special_notes.py.
 */
function specialNotesLooksClean(text: string): boolean {
  if (!text) return true;
  const lower = text.toLowerCase();
  if (SPECIAL_NOTES_CORRUPTION_ARTIFACTS.some((a) => lower.includes(a))) {
    return false;
  }
  if (TURKISH_SUFFIX_PATTERN.test(lower)) return false;
  return true;
}

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
  nice_classes: string | null;
  filing_date: string | null;
  deadline: string | null;
  created_at: string;
  updated_at: string;
  attestation_tx: string | null;
  attestation_pda: string | null;
  client_wallet: string | null;
  guest_client_name: string | null;
  guest_client_email: string | null;
  guest_client_phone: string | null;
  nft_mint: string | null;
  nft_state: "none" | "pending_claim" | "minted" | "burned";
  nft_setup_tx: string | null;
  nft_mint_tx: string | null;
  nft_burn_tx: string | null;
  nft_burned_at: string | null;
}

interface ProposalItem {
  id: string;
  case_id: string;
  country_name: string;
  country_code: string | null;
  nice_classes: string;
  required_documents: string | null;
  registration_period: string | null;
  protection_period: string | null;
  madrid_system: string | null;
  national_application: string | null;
  opposition_period: string | null;
  special_notes: string | null;
  price: number | null;
  currency: string | null;
  status: string;
  created_by: string;
  rejection_reason: string | null;
  sent_at: string | null;
  responded_at: string | null;
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
  file_hash_hex: string | null;
  ownership_commitment_hex: string | null;
  ownership_proof_pda: string | null;
  ownership_verified_at: string | null;
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
  pending: { label: "Pending", color: "bg-yellow-100 text-yellow-800 border-yellow-300" },
  uploaded: { label: "Awaiting Review", color: "bg-blue-100 text-blue-800 border-blue-300" },
  approved: { label: "Approved", color: "bg-green-100 text-green-800 border-green-300" },
  rejected: { label: "Rejected", color: "bg-red-100 text-red-800 border-red-300" },
  cancelled: { label: "Cancelled", color: "bg-gray-100 text-gray-500 border-gray-300" },
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
  const [proposals, setProposals] = useState<ProposalItem[]>([]);
  const [userRole, setUserRole] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Proposal
  const [proposalLoading, setProposalLoading] = useState(false);
  const [proposalError, setProposalError] = useState("");
  const [proposalSuccess, setProposalSuccess] = useState("");
  const [showAllProposals, setShowAllProposals] = useState(false);

  // EUIPO Filing
  const [euipoLoading, setEuipoLoading] = useState(false);
  const [euipoError, setEuipoError] = useState("");
  const [euipoSuccess, setEuipoSuccess] = useState("");
  const [showEuipoForm, setShowEuipoForm] = useState(false);
  const [euipoForm, setEuipoForm] = useState({
    mark_text: "",
    applicant_name: "",
    applicant_address: "",
    applicant_country: "",
  });
  const [rejectProposalId, setRejectProposalId] = useState<string | null>(null);
  const [rejectProposalReason, setRejectProposalReason] = useState("");

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
  const [ownershipClaimEnabled, setOwnershipClaimEnabled] = useState(true);
  const [provingDocId, setProvingDocId] = useState<string | null>(null);
  const [proveResult, setProveResult] = useState<{
    signature: string;
    explorerTxUrl: string;
    proofPda: string;
    explorerPdaUrl: string;
    alreadyRecorded: boolean;
  } | null>(null);

  // Status update
  const [statusLoading, setStatusLoading] = useState(false);
  const [statusError, setStatusError] = useState("");
  const [statusSuccess, setStatusSuccess] = useState("");
  const [caseEvents, setCaseEvents] = useState<CaseEventItem[]>([]);
  const {
    publicKey: walletPubkey,
    signTransaction,
    signMessage: walletSignMessage,
  } = useWallet();

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

  const fetchProposals = useCallback(async () => {
    try {
      const res = await api.get<{ proposals: ProposalItem[]; total: number }>(
        `/cases/${id}/proposals`
      );
      setProposals(res.data.proposals);
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

        const [notesRes, docsRes, reqDocsRes, proposalsRes] = await Promise.all([
          api.get<CaseNote[]>(`/cases/${id}/notes`),
          api.get<{ documents: DocumentItem[] }>(`/cases/${id}/documents`),
          api.get<{ required_documents: RequiredDocument[] }>(`/cases/${id}/required-documents`),
          api.get<{ proposals: ProposalItem[]; total: number }>(`/cases/${id}/proposals`),
        ]);
        if (cancelled) return;
        setNotes(notesRes.data);
        setDocuments(docsRes.data.documents);
        setRequiredDocs(reqDocsRes.data.required_documents);
        setProposals(proposalsRes.data.proposals);
      } catch {
        if (!cancelled) setError("Failed to load case details.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchData();
    return () => { cancelled = true; };
  }, [id]);

  const fetchCaseEvents = useCallback(async () => {
    try {
      const res = await api.get<CaseEventItem[]>(`/cases/${id}/events`);
      setCaseEvents(res.data);
    } catch {
      // non-fatal; keep previous timeline
    }
  }, [id]);

  useEffect(() => {
    if (id) fetchCaseEvents();
  }, [id, fetchCaseEvents]);

  async function recordOnChainEvent(
    caseData: CaseDetail,
    eventType: number,
  ): Promise<void> {
    if (!caseData.attestation_tx) {
      // case was never attested — nothing to update on-chain
      return;
    }
    if (!signTransaction || !walletPubkey) {
      setStatusSuccess(
        "Status updated. Connect a wallet to sign the on-chain event.",
      );
      return;
    }

    setStatusSuccess("Waiting for wallet signature...");

    const prepResp = await api.post<PendingEventAttestation>(
      `/cases/${caseData.id}/attestation/event-prepare`,
      { event_type: eventType },
    );
    const p = prepResp.data;

    const programId = new PublicKey(p.program_id);
    const operator = new PublicKey(p.operator);
    const pda = new PublicKey(p.pda);
    const ixData = base64ToBytes(p.ix_data_b64);

    const ix = new TransactionInstruction({
      programId,
      keys: [
        { pubkey: pda, isSigner: false, isWritable: true },
        { pubkey: operator, isSigner: true, isWritable: true },
        { pubkey: walletPubkey, isSigner: true, isWritable: false },
      ],
      data: Buffer.from(ixData),
    });

    const msg = new TransactionMessage({
      payerKey: operator,
      recentBlockhash: p.recent_blockhash,
      instructions: [ix],
    }).compileToV0Message();

    const tx = new VersionedTransaction(msg);
    const signedTx = await signTransaction(tx);

    setStatusSuccess("Submitting on-chain event to devnet...");
    const signedB64 = bytesToBase64(signedTx.serialize());
    const submitResp = await api.post<CaseEventItem>(
      `/cases/${caseData.id}/attestation/event-submit`,
      {
        signed_tx_b64: signedB64,
        event_type: eventType,
        metadata_hash_hex: p.metadata_hash_hex,
        actor_wallet: walletPubkey.toBase58(),
      },
    );
    setStatusSuccess(
      "Status updated + on-chain event recorded. See timeline below for the explorer link.",
    );
    await fetchCaseEvents();
  }

  async function handleStatusChange(newStatus: string) {
    setStatusError("");
    setStatusSuccess("");
    setStatusLoading(true);

    try {
      const res = await api.patch<CaseDetail>(`/cases/${id}`, {
        status: newStatus,
      });
      setCaseData(res.data);

      try {
        const eventType = newStatus === "closed" ? 99 : 1;
        await recordOnChainEvent(res.data, eventType);
      } catch (chainErr) {
        console.error("on-chain event failed", chainErr);
        setStatusSuccess(
          "Status updated. On-chain event was cancelled or failed.",
        );
      }
      setTimeout(() => setStatusSuccess(""), 6000);
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
      "Are you sure you want to cancel this message? This action cannot be undone."
    );
    if (!confirmed) return;

    setNoteError("");
    setNoteSuccess("");

    try {
      await api.patch(`/cases/${id}/notes/${noteId}/cancel`);
      setNoteSuccess("Message cancelled.");
      await fetchNotes();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to cancel message.";
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

      // Optional: compute the ZK ownership commitment in the browser and
      // attach it to the upload. Only runs when the user has opted in AND
      // the connected wallet exposes signMessage (Phantom/Solflare do).
      if (
        ownershipClaimEnabled &&
        walletPubkey &&
        typeof walletSignMessage === "function"
      ) {
        setDocSuccess("Computing ownership claim — approve the signature in your wallet...");
        const input = await prepareFileOwnershipInput(docFile, {
          publicKey: walletPubkey,
          signMessage: walletSignMessage,
        });
        formData.append("file_hash_hex", bytesToHex(input.fileHash));
        formData.append(
          "ownership_commitment_hex",
          bigintToHex32(input.commitment),
        );
        setDocSuccess("");
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
          ?.detail ??
        (err instanceof Error ? err.message : "Failed to upload document.");
      setDocError(message);
    } finally {
      setDocLoading(false);
    }
  }

  async function handleProveOwnership(doc: DocumentItem) {
    if (!doc.file_hash_hex || !doc.ownership_commitment_hex) {
      setDocError("This document has no ownership commitment to prove.");
      return;
    }
    if (!walletPubkey || typeof walletSignMessage !== "function" || !signTransaction) {
      setDocError(
        "Connect a wallet that supports signMessage + signTransaction (Phantom/Solflare) to prove ownership.",
      );
      return;
    }

    setDocError("");
    setDocSuccess("Generating zero-knowledge proof — this takes a second...");
    setProveResult(null);
    setProvingDocId(doc.id);

    try {
      const result = await proveDocumentOwnershipOnChain({
        fileHashHex: doc.file_hash_hex,
        expectedCommitmentHex: doc.ownership_commitment_hex,
        wallet: {
          publicKey: walletPubkey,
          signMessage: walletSignMessage,
          signTransaction,
        },
      });

      setDocSuccess(
        result.alreadyRecorded
          ? "This file is already proven on devnet — linking the existing record to the case..."
          : "Proof verified on devnet. Writing record to the case..."
      );

      await api.post(`/documents/${doc.id}/attach-ownership-proof`, {
        proof_pda: result.proofPda,
      });

      setDocSuccess("");
      setProveResult(result);
      await fetchDocuments();
    } catch (err: unknown) {
      const fallback =
        err instanceof Error ? err.message : "Failed to prove ownership.";
      setDocError(extractErrorMessage(err, fallback));
      setDocSuccess("");
    } finally {
      setProvingDocId(null);
    }
  }

  async function handleCancelDocument(documentId: string) {
    const confirmed = window.confirm(
      "Are you sure you want to cancel this document? This action cannot be undone."
    );
    if (!confirmed) return;

    setDocError("");
    setDocSuccess("");

    try {
      await api.patch(`/documents/${documentId}/cancel`);
      setDocSuccess("Document cancelled.");
      await Promise.all([fetchDocuments(), fetchRequiredDocs()]);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to cancel document.";
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
    setDocError("");
    setDocSuccess("");
    try {
      const res = await api.post<{ required_documents: unknown[]; total: number }>(
        `/cases/${id}/required-documents/generate`
      );
      if (res.data.total === 0) {
        const jurisdiction = caseData?.jurisdiction || "this jurisdiction";
        setDocError(
          `No required-document templates are configured for ${jurisdiction}. The case was processed but no documents were generated. Update the case jurisdiction to a supported country (US, DE, IT, ES, etc.) or contact an admin to add templates for ${jurisdiction}.`
        );
      } else {
        await fetchRequiredDocs();
        setDocSuccess(`${res.data.total} required document(s) generated.`);
        setTimeout(() => setDocSuccess(""), 3000);
      }
    } catch (err: unknown) {
      setDocError(
        extractErrorMessage(err, "Failed to generate required documents.")
      );
    }
  }

  async function handleGenerateProposal() {
    setProposalError("");
    setProposalSuccess("");
    setProposalLoading(true);

    try {
      await api.post(`/cases/${id}/proposal/generate`);
      setProposalSuccess("Proposal generated successfully.");
      await fetchProposals();
      setTimeout(() => setProposalSuccess(""), 3000);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to generate proposal.";
      setProposalError(message);
    } finally {
      setProposalLoading(false);
    }
  }

  async function handleSendProposal(proposalId: string) {
    setProposalError("");
    setProposalSuccess("");
    setProposalLoading(true);

    try {
      await api.patch(`/proposals/${proposalId}/send`);
      setProposalSuccess("Proposal sent to client.");
      await fetchProposals();
      setTimeout(() => setProposalSuccess(""), 3000);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to send proposal.";
      setProposalError(message);
    } finally {
      setProposalLoading(false);
    }
  }

  async function handleRespondProposal(proposalId: string, accepted: boolean, rejectionReason?: string) {
    if (accepted) {
      const confirmed = window.confirm(
        "Accept this proposal? You'll be asked to sign with your wallet first — the proposal is only marked accepted after the signature.",
      );
      if (!confirmed) return;
    }

    setProposalError("");
    setProposalSuccess("");
    setProposalLoading(true);

    try {
      // Step 1: sign the on-chain event BEFORE touching the DB so the
      // two states stay atomic. If the user cancels the Phantom popup
      // or the tx fails, the proposal stays in its current state.
      if (caseData && caseData.attestation_tx) {
        try {
          await recordOnChainEvent(caseData, accepted ? 4 : 5);
        } catch (chainErr) {
          console.error("proposal on-chain sign failed", chainErr);
          setProposalError(
            `On-chain signature was cancelled or failed. Proposal was NOT marked as ${
              accepted ? "accepted" : "rejected"
            }.`,
          );
          setProposalLoading(false);
          return;
        }
      }

      // Step 2: persist the response in the DB. Only runs after the
      // wallet signature succeeded (or if the case has no attestation
      // yet, in which case there is no chain step to gate on).
      await api.patch(`/proposals/${proposalId}/respond`, {
        accepted,
        rejection_reason: rejectionReason || null,
      });
      setProposalSuccess(`Proposal ${accepted ? "accepted" : "rejected"}.`);
      setRejectProposalId(null);
      setRejectProposalReason("");
      await fetchProposals();

      setTimeout(() => setProposalSuccess(""), 6000);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? `Failed to ${accepted ? "accept" : "reject"} proposal.`;
      setProposalError(message);
    } finally {
      setProposalLoading(false);
    }
  }

  const latestProposal = proposals.length > 0 ? proposals[0] : null;

  const PROPOSAL_STATUS_CONFIG: Record<string, { label: string; color: string }> = {
    draft: { label: "Draft", color: "bg-gray-100 text-gray-800 border-gray-300" },
    sent: { label: "Sent", color: "bg-blue-100 text-blue-800 border-blue-300" },
    accepted: { label: "Accepted", color: "bg-green-100 text-green-800 border-green-300" },
    rejected: { label: "Rejected", color: "bg-red-100 text-red-800 border-red-300" },
  };

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
            <p className="text-xs text-gray-500 uppercase">Nice Classes</p>
            <p className="text-sm font-medium">
              {caseData.nice_classes ?? "N/A"}
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

      {/* Renewal lifecycle */}
      <RenewalCard caseId={caseData.id} />

      {/* On-Chain Attestation */}
      <AttestationCard
        txSignature={caseData.attestation_tx}
        pda={caseData.attestation_pda}
        clientWallet={caseData.client_wallet}
      />

      {/* Soul-bound Case NFT */}
      <NftCard
        caseId={caseData.id}
        caseNumber={caseData.case_number}
        nftState={caseData.nft_state}
        nftMint={caseData.nft_mint}
        nftSetupTx={caseData.nft_setup_tx}
        nftMintTx={caseData.nft_mint_tx}
        nftBurnTx={caseData.nft_burn_tx}
        nftBurnedAt={caseData.nft_burned_at}
        clientWallet={caseData.client_wallet}
        onClaimed={(updated) =>
          setCaseData((prev) =>
            prev ? ({ ...prev, ...updated } as CaseDetail) : prev,
          )
        }
      />

      {/* On-Chain Event Timeline */}
      {caseEvents.length > 0 && (
        <div className="mb-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="mb-3 text-lg font-semibold text-gray-700">
            On-Chain Event Timeline
          </h2>
          <ul className="space-y-2">
            {caseEvents.map((ev) => (
              <li
                key={ev.id}
                className="flex items-center justify-between rounded border border-gray-100 bg-gray-50 px-3 py-2"
              >
                <div>
                  <p className="text-sm font-medium text-gray-800">
                    {EVENT_TYPE_LABELS[ev.event_type] ??
                      `Event type ${ev.event_type}`}
                  </p>
                  <p className="text-xs text-gray-500">
                    {new Date(ev.created_at).toLocaleString()} &middot; actor{" "}
                    <span className="font-mono">
                      {ev.actor_wallet.slice(0, 6)}…{ev.actor_wallet.slice(-6)}
                    </span>
                  </p>
                </div>
                <a
                  href={`https://explorer.solana.com/tx/${ev.tx_signature}?cluster=devnet`}
                  target="_blank"
                  rel="noreferrer"
                  className="font-mono text-xs text-emerald-700 underline-offset-2 hover:underline"
                >
                  {ev.tx_signature.slice(0, 8)}…{ev.tx_signature.slice(-6)}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Required Documents Section */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow-sm border border-gray-200">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-700">
            Required Documents ({requiredDocs.length})
          </h2>
          {requiredDocs.length === 0 && caseData.jurisdiction && userRole !== "client" && (
            <button
              type="button"
              onClick={handleGenerateRequiredDocs}
              className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
            >
              Generate Required Documents
            </button>
          )}
        </div>

        {requiredDocs.length === 0 ? (
          <p className="text-sm text-gray-400">
            {caseData.jurisdiction
              ? "No required documents defined yet. Click the button above to generate."
              : "Jurisdiction must be set to generate required documents."}
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
                    {approved}/{total} approved
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
                          File: {linkedDoc.filename}
                          {linkedDoc.reviewed_at && (
                            <> &middot; Reviewed: {new Date(linkedDoc.reviewed_at).toLocaleDateString()}</>
                          )}
                        </p>
                      )}
                      {req.status === "rejected" && linkedDoc?.rejection_reason && (
                        <p className="mt-1 text-xs text-red-600 ml-7">
                          Rejection reason: {linkedDoc.rejection_reason}
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
                          {req.status === "rejected" ? "Re-upload" : "Upload"}
                        </button>
                      )}
                      {req.status === "uploaded" && (
                        <span className="text-xs text-blue-600 font-medium">Awaiting lawyer review</span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Proposal Section */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow-sm border border-gray-200">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-700">
            Proposal {proposals.length > 0 && `(${proposals.length})`}
          </h2>
          <div className="flex items-center gap-2">
            {proposals.length > 1 && (
              <button
                type="button"
                onClick={() => setShowAllProposals(!showAllProposals)}
                className="text-xs text-blue-600 hover:underline"
              >
                {showAllProposals ? "Show Latest Only" : `View All (${proposals.length})`}
              </button>
            )}
            {(userRole === "admin") &&
              caseData.jurisdiction &&
              caseData.nice_classes && (
                <button
                  type="button"
                  onClick={handleGenerateProposal}
                  disabled={proposalLoading}
                  className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {proposalLoading ? "Generating..." : latestProposal ? "Generate New" : "Generate Proposal"}
                </button>
              )}
          </div>
        </div>

        {proposalSuccess && (
          <div className="mb-3 rounded bg-green-50 p-2 text-xs text-green-700 border border-green-200">
            {proposalSuccess}
          </div>
        )}
        {proposalError && (
          <div className="mb-3 rounded bg-red-50 p-2 text-xs text-red-700 border border-red-200">
            {proposalError}
          </div>
        )}

        {!latestProposal ? (
          <p className="text-sm text-gray-400">
            {!caseData.jurisdiction
              ? "Set jurisdiction on the case to generate a proposal."
              : !caseData.nice_classes
                ? "Set Nice classes on the case to generate a proposal."
                : "No proposal generated yet."}
          </p>
        ) : (
          <div className="space-y-4">
            {(showAllProposals ? proposals : [latestProposal]).map((proposal) => {
              const statusConfig = PROPOSAL_STATUS_CONFIG[proposal.status] ?? PROPOSAL_STATUS_CONFIG.draft;
              return (
                <div
                  key={proposal.id}
                  className={`rounded-lg border p-5 ${
                    proposal.status === "accepted"
                      ? "bg-green-50 border-green-200"
                      : proposal.status === "rejected"
                        ? "bg-red-50 border-red-200"
                        : proposal.status === "sent"
                          ? "bg-blue-50 border-blue-200"
                          : "bg-gray-50 border-gray-100"
                  }`}
                >
                  {/* Header */}
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-3">
                      <h3 className="text-base font-semibold text-gray-800">
                        {proposal.country_name}
                        {proposal.country_code && (
                          <span className="ml-2 text-sm font-normal text-gray-500">
                            ({proposal.country_code})
                          </span>
                        )}
                      </h3>
                      <span
                        className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${statusConfig.color}`}
                      >
                        {statusConfig.label}
                      </span>
                    </div>
                    <p className="text-xs text-gray-400">
                      {new Date(proposal.created_at).toLocaleDateString()}
                    </p>
                  </div>

                  {/* Info Grid */}
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 mb-4">
                    <div>
                      <p className="text-xs text-gray-500 uppercase">Nice Classes</p>
                      <p className="text-sm font-medium">{proposal.nice_classes}</p>
                    </div>
                    {proposal.registration_period && (
                      <div>
                        <p className="text-xs text-gray-500 uppercase">Registration Period</p>
                        <p className="text-sm font-medium">{proposal.registration_period}</p>
                      </div>
                    )}
                    {proposal.protection_period && (
                      <div>
                        <p className="text-xs text-gray-500 uppercase">Protection Period</p>
                        <p className="text-sm font-medium">{proposal.protection_period}</p>
                      </div>
                    )}
                    {proposal.madrid_system && (
                      <div>
                        <p className="text-xs text-gray-500 uppercase">Madrid System</p>
                        <p className="text-sm font-medium">{proposal.madrid_system}</p>
                      </div>
                    )}
                    {proposal.national_application && (
                      <div>
                        <p className="text-xs text-gray-500 uppercase">National Application</p>
                        <p className="text-sm font-medium">{proposal.national_application}</p>
                      </div>
                    )}
                    {proposal.opposition_period && (
                      <div>
                        <p className="text-xs text-gray-500 uppercase">Opposition Period</p>
                        <p className="text-sm font-medium">{proposal.opposition_period}</p>
                      </div>
                    )}
                    {proposal.price != null && (
                      <div>
                        <p className="text-xs text-gray-500 uppercase">Price</p>
                        <p className="text-sm font-semibold text-green-700">
                          {proposal.price} {proposal.currency ?? ""}
                        </p>
                      </div>
                    )}
                  </div>

                  {/* Required Documents from Country DB */}
                  {proposal.required_documents && (
                    <div className="mb-4">
                      <p className="text-xs text-gray-500 uppercase mb-1">Required Documents (Country)</p>
                      <p className="text-sm text-gray-700 whitespace-pre-wrap bg-white/60 rounded p-2 border border-gray-100">
                        {proposal.required_documents}
                      </p>
                    </div>
                  )}

                  {/* Special Notes — only render when the source text looks
                      like clean English. ~22 jurisdictions still ship the
                      corrupted Turkish/English mix from countries_parsed.json
                      that the LLM cleanup pass could not recover; for those
                      we silently hide rather than show garbled output. */}
                  {proposal.special_notes &&
                    specialNotesLooksClean(proposal.special_notes) && (
                      <div className="mb-4">
                        <p className="text-xs text-gray-500 uppercase mb-1">
                          Special Notes
                        </p>
                        <p className="text-sm text-gray-700 whitespace-pre-wrap bg-yellow-50 rounded p-2 border border-yellow-100">
                          {proposal.special_notes}
                        </p>
                      </div>
                    )}

                  {/* Timestamps */}
                  <div className="flex items-center gap-4 text-xs text-gray-400 mb-3">
                    {proposal.sent_at && (
                      <span>Sent: {new Date(proposal.sent_at).toLocaleString()}</span>
                    )}
                    {proposal.responded_at && (
                      <span>Responded: {new Date(proposal.responded_at).toLocaleString()}</span>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 pt-2 border-t border-gray-200">
                    {/* Draft: lawyer/admin can send */}
                    {proposal.status === "draft" && (userRole === "admin") && (
                      <button
                        type="button"
                        onClick={() => handleSendProposal(proposal.id)}
                        disabled={proposalLoading}
                        className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                      >
                        {proposalLoading ? "Sending..." : "Send to Client"}
                      </button>
                    )}
                    {proposal.status === "draft" && userRole === "client" && (
                      <span className="text-sm text-gray-500 italic">Draft - not yet sent</span>
                    )}

                    {/* Sent: client can accept/reject */}
                    {proposal.status === "sent" && userRole === "client" && (
                      <>
                        {rejectProposalId === proposal.id ? (
                          <div className="w-full mt-2 rounded-lg border border-red-200 bg-red-50 p-3">
                            <p className="text-sm font-medium text-red-800 mb-2">Rejection Reason *</p>
                            <textarea
                              value={rejectProposalReason}
                              onChange={(e) => setRejectProposalReason(e.target.value)}
                              placeholder="Please explain why you are rejecting this proposal..."
                              rows={3}
                              className="w-full rounded border border-red-300 px-3 py-2 text-sm focus:border-red-500 focus:outline-none bg-white"
                            />
                            <div className="mt-2 flex gap-2">
                              <button
                                type="button"
                                onClick={() => {
                                  if (rejectProposalReason.trim()) {
                                    handleRespondProposal(proposal.id, false, rejectProposalReason);
                                  }
                                }}
                                disabled={!rejectProposalReason.trim() || proposalLoading}
                                className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                              >
                                {proposalLoading ? "Rejecting..." : "Confirm Reject"}
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setRejectProposalId(null);
                                  setRejectProposalReason("");
                                }}
                                className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <button
                              type="button"
                              onClick={() => handleRespondProposal(proposal.id, true)}
                              disabled={proposalLoading}
                              className="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
                            >
                              Accept
                            </button>
                            <button
                              type="button"
                              onClick={() => setRejectProposalId(proposal.id)}
                              disabled={proposalLoading}
                              className="rounded bg-red-50 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-100 border border-red-200 disabled:opacity-50"
                            >
                              Reject
                            </button>
                          </>
                        )}
                      </>
                    )}
                    {proposal.status === "sent" && userRole !== "client" && (
                      <span className="text-sm text-blue-600 italic">Awaiting client response</span>
                    )}

                    {/* Accepted */}
                    {proposal.status === "accepted" && (
                      <div className="flex items-center gap-2">
                        <svg className="h-4 w-4 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                        <span className="text-sm font-medium text-green-700">Client accepted this proposal</span>
                      </div>
                    )}

                    {/* Rejected */}
                    {proposal.status === "rejected" && (
                      <div>
                        <span className="text-sm font-medium text-red-600">Client rejected this proposal</span>
                        {proposal.rejection_reason && (
                          <div className="mt-2 rounded-lg border border-red-200 bg-red-50 p-3">
                            <p className="text-xs font-medium text-red-700 mb-1">Rejection Reason:</p>
                            <p className="text-sm text-red-800">{proposal.rejection_reason}</p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* EUIPO Filing Section - admin/lawyer only, trademark cases */}
      {(userRole === "admin") && caseData.case_type === "trademark" && (
        <div className="mb-6 rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-semibold text-gray-700">EUIPO Filing</h2>
              <span className="inline-flex items-center rounded-full bg-indigo-100 text-indigo-800 px-2.5 py-0.5 text-xs font-medium border border-indigo-200">
                EU Trademark
              </span>
            </div>
            {!showEuipoForm && (
              <button
                type="button"
                onClick={() => {
                  setShowEuipoForm(true);
                  setEuipoForm({
                    mark_text: caseData.title,
                    applicant_name: "",
                    applicant_address: "",
                    applicant_country: "",
                  });
                }}
                className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
              >
                File to EUIPO
              </button>
            )}
          </div>

          {euipoSuccess && (
            <div className="mb-3 rounded bg-green-50 p-3 text-sm text-green-700 border border-green-200">
              {euipoSuccess}
            </div>
          )}
          {euipoError && (
            <div className="mb-3 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
              {euipoError}
            </div>
          )}

          {!showEuipoForm ? (
            <p className="text-sm text-gray-400">
              Submit this trademark application to EUIPO for EU-wide protection.
              {!caseData.nice_classes && " Set Nice classes first."}
            </p>
          ) : (
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                setEuipoLoading(true);
                setEuipoError("");
                setEuipoSuccess("");
                try {
                  await api.post("/euipo/eutm/file", {
                    case_id: id,
                    mark_text: euipoForm.mark_text,
                    mark_type: "WORD",
                    applicant_name: euipoForm.applicant_name,
                    applicant_address: euipoForm.applicant_address,
                    applicant_country: euipoForm.applicant_country,
                  });
                  setEuipoSuccess("EUTM application created as draft at EUIPO.");
                  setShowEuipoForm(false);
                  setTimeout(() => setEuipoSuccess(""), 5000);
                } catch (err: unknown) {
                  setEuipoError(
                    extractErrorMessage(err, "Failed to file to EUIPO.")
                  );
                } finally {
                  setEuipoLoading(false);
                }
              }}
              className="space-y-4"
            >
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="sm:col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Trademark Text *
                  </label>
                  <input
                    value={euipoForm.mark_text}
                    onChange={(e) =>
                      setEuipoForm({ ...euipoForm, mark_text: e.target.value })
                    }
                    required
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Applicant Name *
                  </label>
                  <input
                    value={euipoForm.applicant_name}
                    onChange={(e) =>
                      setEuipoForm({ ...euipoForm, applicant_name: e.target.value })
                    }
                    required
                    placeholder="Company or person name"
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Applicant Country *
                  </label>
                  <input
                    value={euipoForm.applicant_country}
                    onChange={(e) =>
                      setEuipoForm({ ...euipoForm, applicant_country: e.target.value })
                    }
                    required
                    placeholder="e.g. TR, DE, US"
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>
                <div className="sm:col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Applicant Address *
                  </label>
                  <input
                    value={euipoForm.applicant_address}
                    onChange={(e) =>
                      setEuipoForm({ ...euipoForm, applicant_address: e.target.value })
                    }
                    required
                    placeholder="Full address"
                    className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>
              </div>

              {caseData.nice_classes && (
                <div className="rounded bg-indigo-50 p-3 border border-indigo-100">
                  <p className="text-xs text-indigo-600 font-medium">
                    Nice Classes from case: {caseData.nice_classes}
                  </p>
                </div>
              )}

              <div className="flex items-center gap-3">
                <button
                  type="submit"
                  disabled={euipoLoading}
                  className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {euipoLoading ? "Filing..." : "Create Draft at EUIPO"}
                </button>
                <button
                  type="button"
                  onClick={() => setShowEuipoForm(false)}
                  className="text-sm text-gray-500 hover:text-gray-700"
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* BRAID inline insights — visible to admin/lawyer/client when
          BRAID hooks have produced any decisions for this case. */}
      <BRAIDInsightsPanel
        caseId={id}
        canGiveFeedback={userRole === "admin"}
      />

      {/* UK IPO Filing Section — admin/lawyer only, trademark cases */}
      {caseData.case_type === "trademark" && (
        <UKIPOPanel
          caseId={id}
          caseTitle={caseData.title}
          caseNiceClasses={caseData.nice_classes}
          caseJurisdiction={caseData.jurisdiction}
          caseClientId={caseData.client_id}
          guestClientName={caseData.guest_client_name}
          guestClientEmail={caseData.guest_client_email}
          guestClientPhone={caseData.guest_client_phone}
          canManage={userRole === "admin"}
        />
      )}

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
                            <span className="inline-flex items-center rounded-full bg-gray-200 border border-gray-300 px-2 py-0.5 text-xs font-medium text-gray-500">Cancelled</span>
                          </div>
                          <p className="text-sm text-gray-400 line-through whitespace-pre-wrap">{note.content}</p>
                        </div>
                      ) : (
                        <p className="text-sm text-gray-400 italic">This message has been cancelled.</p>
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
                        title="Cancel message"
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
          {proveResult && (
            <div className="mb-3 rounded bg-green-50 p-2 text-xs text-green-700 border border-green-200">
              <div>
                {proveResult.alreadyRecorded
                  ? "This file is already proven on devnet — linked to the case."
                  : "Ownership verified on devnet."}
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                {proveResult.explorerTxUrl && (
                  <a
                    href={proveResult.explorerTxUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline hover:text-green-900"
                  >
                    View transaction on Solscan
                  </a>
                )}
                <a
                  href={proveResult.explorerPdaUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline hover:text-green-900"
                >
                  View PDA on Solscan
                </a>
                <button
                  type="button"
                  onClick={() => setProveResult(null)}
                  className="text-green-600 hover:text-green-900"
                >
                  Dismiss
                </button>
              </div>
            </div>
          )}
          {docError && (
            <div
              role="alert"
              className="mb-3 flex items-start gap-2 rounded bg-red-50 p-2 text-xs text-red-700 border border-red-200"
            >
              <span className="flex-1">{docError}</span>
              <button
                type="button"
                onClick={() => setDocError("")}
                aria-label="Dismiss"
                className="text-red-700 hover:text-red-900"
              >
                &times;
              </button>
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
                <option value="">Select document type (optional)</option>
                {uploadableRequiredDocs.map((req) => (
                  <option key={req.id} value={req.document_name}>
                    {req.document_name}{req.status === "rejected" ? " (Rejected - Re-upload)" : ""}
                  </option>
                ))}
              </select>
            )}
            {walletPubkey && typeof walletSignMessage === "function" && (
              <label className="flex items-start gap-2 text-xs text-gray-600">
                <input
                  type="checkbox"
                  checked={ownershipClaimEnabled}
                  onChange={(e) => setOwnershipClaimEnabled(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  <span className="font-medium text-gray-700">
                    Register zero-knowledge ownership claim
                  </span>
                  <span className="block text-gray-500">
                    Your wallet will sign a short message. The file itself
                    never leaves the browser; only a 32-byte Poseidon
                    commitment is stored with the upload. You can prove
                    ownership on-chain later without re-uploading.
                  </span>
                </span>
              </label>
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
                        <div className="flex items-center gap-2 flex-wrap">
                          <p className="text-sm font-medium text-gray-700 truncate">
                            {doc.filename}
                          </p>
                          <span
                            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${docStatusConfig.color}`}
                          >
                            {docStatusConfig.label}
                          </span>
                          {doc.ownership_verified_at ? (
                            doc.ownership_proof_pda ? (
                              <a
                                href={`https://solscan.io/account/${doc.ownership_proof_pda}?cluster=devnet`}
                                target="_blank"
                                rel="noopener noreferrer"
                                title={`Verified on-chain at ${new Date(doc.ownership_verified_at).toLocaleString()}\nPDA: ${doc.ownership_proof_pda}`}
                                className="inline-flex items-center rounded-full border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-800 hover:bg-emerald-100"
                              >
                                Ownership verified
                              </a>
                            ) : (
                              <span
                                title={`Verified on-chain at ${new Date(doc.ownership_verified_at).toLocaleString()}`}
                                className="inline-flex items-center rounded-full border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-800"
                              >
                                Ownership verified
                              </span>
                            )
                          ) : doc.ownership_commitment_hex ? (
                            <span
                              title={`Ownership commitment recorded at upload.\nfile_hash: ${doc.file_hash_hex ?? "?"}\ncommitment: ${doc.ownership_commitment_hex}`}
                              className="inline-flex items-center rounded-full border border-purple-300 bg-purple-50 px-2 py-0.5 text-xs font-medium text-purple-800"
                            >
                              ZK committed
                            </span>
                          ) : null}
                        </div>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {doc.file_type ?? "unknown"} &middot;{" "}
                          {doc.file_size
                            ? `${(doc.file_size / 1024).toFixed(1)} KB`
                            : "N/A"}{" "}
                          &middot;{" "}
                          {new Date(doc.created_at).toLocaleDateString()}
                          {doc.document_type && (
                            <> &middot; Type: {doc.document_type}</>
                          )}
                        </p>
                        {doc.rejection_reason && (
                          <p className="text-xs text-red-600 mt-1">
                            Rejection reason: {doc.rejection_reason}
                          </p>
                        )}
                      </div>
                      <div className="ml-3 flex items-center gap-2 shrink-0">
                        {doc.status !== "cancelled" && (
                          <>
                            {doc.ownership_commitment_hex &&
                              !doc.ownership_verified_at &&
                              doc.uploaded_by && (
                                <button
                                  type="button"
                                  onClick={() => handleProveOwnership(doc)}
                                  disabled={
                                    provingDocId === doc.id || !walletPubkey
                                  }
                                  className="rounded bg-purple-600 px-2 py-1 text-xs font-medium text-white hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
                                  title={
                                    walletPubkey
                                      ? "Generate a ZK proof of ownership and record it on-chain"
                                      : "Connect a wallet to prove ownership"
                                  }
                                >
                                  {provingDocId === doc.id
                                    ? "Proving…"
                                    : "Prove ownership"}
                                </button>
                              )}
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
                              Download
                            </button>
                            <button
                              type="button"
                              onClick={() => handleCancelDocument(doc.id)}
                              className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600"
                              title="Cancel document"
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
                    {doc.status === "uploaded" && (userRole === "admin") && (
                      <div className="mt-2 pt-2 border-t border-gray-200">
                        {rejectDocId === doc.id ? (
                          <div className="flex items-center gap-2">
                            <input
                              type="text"
                              value={rejectReason}
                              onChange={(e) => setRejectReason(e.target.value)}
                              placeholder="Enter rejection reason..."
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
                              Reject
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setRejectDocId(null);
                                setRejectReason("");
                              }}
                              className="text-xs text-gray-500 hover:text-gray-700"
                            >
                              Cancel
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
                              {reviewLoading === doc.id ? "..." : "Approve"}
                            </button>
                            <button
                              type="button"
                              onClick={() => setRejectDocId(doc.id)}
                              disabled={reviewLoading === doc.id}
                              className="rounded bg-red-50 px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-100 border border-red-200 disabled:opacity-50"
                            >
                              Reject
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
