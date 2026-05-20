"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useConnection, useWallet } from "@solana/wallet-adapter-react";
import {
  PublicKey,
  SystemProgram,
  TransactionInstruction,
  TransactionMessage,
  VersionedTransaction,
} from "@solana/web3.js";
import api, { extractErrorMessage } from "@/lib/api";
import type {
  AgentMessage,
  AgentSession,
  FilingProgress,
  MessageListResponse,
  SessionListResponse,
  TurnResponse,
} from "@/lib/agent/types";
import { STATUS_LABELS, STEP_LABELS } from "@/lib/agent/types";
import { prepareFileOwnershipInput } from "@/lib/zk/fileOwnership";
import { proveDocumentOwnershipOnChain } from "@/lib/zk/submitFileOwnership";
import { NftClaimPanel } from "@/components/NftClaimPanel";
import { StripeCheckoutButton } from "@/components/StripeCheckoutButton";
import {
  createUkipoStripeCheckoutSession,
  fetchCaseDraftPaymentStatus,
  type CaseDraftPaymentStatus,
} from "@/lib/payments/stripe";
import {
  bigintToBE32,
  computeCommitment,
  deriveDeterministicSecret,
  generateComplianceProof,
  splitQueryHash,
} from "@/lib/zk/compliance";
import bs58 from "bs58";

function bytesToHex(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += b.toString(16).padStart(2, "0");
  return s;
}

function bigintToHex32(value: bigint): string {
  const hex = value.toString(16);
  return hex.padStart(64, "0");
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  const now = Date.now();
  const diff = now - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return d.toLocaleDateString();
}

function formatTokens(value: number): string {
  if (value < 1000) return value.toString();
  return `${(value / 1000).toFixed(1)}k`;
}

const MEMO_PROGRAM_ID = new PublicKey(
  "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
);

// Render a small subset of Markdown inline: **bold**, *italic*, `code`,
// [text](url), and "- item" / "1. item" list lines. We avoid pulling
// in a heavy markdown library because the LLM's output is constrained
// by the system prompt to this subset already.
function renderMarkdown(text: string): ReactNode {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const bullet = line.match(/^[\s]*[-*]\s+(.*)$/);
    const number = line.match(/^[\s]*\d+\.\s+(.*)$/);
    if (bullet) {
      const items: string[] = [];
      while (i < lines.length) {
        const m = lines[i].match(/^[\s]*[-*]\s+(.*)$/);
        if (!m) break;
        items.push(m[1]);
        i++;
      }
      blocks.push(
        <ul key={blocks.length} className="my-1 list-disc pl-5">
          {items.map((it, idx) => (
            <li key={idx}>{renderInline(it)}</li>
          ))}
        </ul>
      );
      continue;
    }
    if (number) {
      const items: string[] = [];
      while (i < lines.length) {
        const m = lines[i].match(/^[\s]*\d+\.\s+(.*)$/);
        if (!m) break;
        items.push(m[1]);
        i++;
      }
      blocks.push(
        <ol key={blocks.length} className="my-1 list-decimal pl-5">
          {items.map((it, idx) => (
            <li key={idx}>{renderInline(it)}</li>
          ))}
        </ol>
      );
      continue;
    }
    if (!line.trim()) {
      blocks.push(<br key={blocks.length} />);
      i++;
      continue;
    }
    blocks.push(
      <p key={blocks.length} className="my-1">
        {renderInline(line)}
      </p>
    );
    i++;
  }
  return blocks;
}

function renderInline(text: string): ReactNode[] {
  const tokens: ReactNode[] = [];
  // Order matters: explicit [text](url) before bare https?://... so we
  // do not double-match. Trailing punctuation (.,;:!?) is excluded from
  // the bare URL so a sentence-ending period stays in the prose.
  const pattern =
    /(\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)|(https?:\/\/[^\s<>()]+[^\s<>().,;:!?]))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      tokens.push(text.slice(lastIndex, match.index));
    }
    if (match[2] !== undefined) {
      tokens.push(<strong key={key++}>{match[2]}</strong>);
    } else if (match[3] !== undefined) {
      tokens.push(<em key={key++}>{match[3]}</em>);
    } else if (match[4] !== undefined) {
      tokens.push(
        <code
          key={key++}
          className="rounded bg-[color:var(--color-sand)] px-1 py-0.5 text-[11px] font-mono"
        >
          {match[4]}
        </code>
      );
    } else if (match[5] !== undefined && match[6] !== undefined) {
      tokens.push(
        <a
          key={key++}
          href={match[6]}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[color:var(--color-bronze)] underline"
        >
          {match[5]}
        </a>
      );
    } else if (match[7] !== undefined) {
      tokens.push(
        <a
          key={key++}
          href={match[7]}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[color:var(--color-bronze)] underline break-all"
        >
          {match[7]}
        </a>
      );
    }
    lastIndex = pattern.lastIndex;
  }
  if (lastIndex < text.length) {
    tokens.push(text.slice(lastIndex));
  }
  return tokens;
}

interface AttachedUpload {
  id: string;
  filename: string;
  size_bytes: number;
  file_hash_hex?: string;
  ownership_commitment_hex?: string;
  ownership_status: "none" | "claim_pending" | "proving" | "verified" | "failed";
  ownership_error?: string;
  ownership_proof_pda?: string;
  ownership_tx_url?: string;
  ownership_pda_url?: string;
}

function shortHash(hex: string | undefined, head = 10, tail = 6): string {
  if (!hex) return "—";
  if (hex.length <= head + tail + 1) return hex;
  return `${hex.slice(0, head)}…${hex.slice(-tail)}`;
}

export default function AgentPage() {
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [filingProgress, setFilingProgress] = useState<FilingProgress | null>(null);
  const [attachedFiles, setAttachedFiles] = useState<AttachedUpload[]>([]);
  const [uploading, setUploading] = useState(false);
  const [zkClaim, setZkClaim] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const wallet = useWallet();
  const walletPubkey = wallet.publicKey;
  const walletSignMessage = wallet.signMessage;
  const walletSignTransaction = wallet.signTransaction;

  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeId) ?? null,
    [sessions, activeId]
  );

  // Initial load.
  useEffect(() => {
    let cancelled = false;
    api
      .get<SessionListResponse>("/agent/sessions")
      .then((res) => {
        if (cancelled) return;
        setSessions(res.data.sessions);
        if (res.data.sessions.length > 0) {
          setActiveId(res.data.sessions[0].id);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(extractErrorMessage(err, "Failed to load sessions."));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Fetch messages whenever the active session changes.
  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    api
      .get<MessageListResponse>(`/agent/sessions/${activeId}/messages`)
      .then((res) => {
        if (!cancelled) setMessages(res.data.messages);
      })
      .catch((err) => {
        if (!cancelled) setError(extractErrorMessage(err, "Failed to load messages."));
      });
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  // Auto-scroll to the newest message.
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  // Detect the latest start_ukipo_filing tool-result and pick up its
  // submission_id so the panel can poll progress.
  const submissionId = useMemo<string | null>(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.role === "tool" && m.tool_name === "start_ukipo_filing") {
        const sid = (m.tool_result as { submission_id?: unknown } | null)
          ?.submission_id;
        if (typeof sid === "string") return sid;
      }
    }
    return null;
  }, [messages]);

  // Poll the robot's progress while it's running.
  useEffect(() => {
    if (!submissionId) {
      setFilingProgress(null);
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const fetchOnce = async () => {
      try {
        const res = await api.get<FilingProgress>(
          `/agent/filings/${submissionId}/progress`
        );
        if (cancelled) return;
        setFilingProgress(res.data);

        const terminal: FilingProgress["status"][] = [
          "awaiting_payment",
          "filed",
          "failed",
        ];
        if (!terminal.includes(res.data.status)) {
          timer = setTimeout(fetchOnce, 2000);
        }
      } catch {
        if (!cancelled) {
          // Back off on error, keep retrying every 5s.
          timer = setTimeout(fetchOnce, 5000);
        }
      }
    };

    fetchOnce();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [submissionId]);

  const handleNewSession = useCallback(async () => {
    setError(null);
    try {
      const res = await api.post<AgentSession>("/agent/sessions", {});
      setSessions((prev) => [res.data, ...prev]);
      setActiveId(res.data.id);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to create session."));
    }
  }, []);

  const handleAttachClick = useCallback(() => {
    if (!activeId || uploading || sending) return;
    fileInputRef.current?.click();
  }, [activeId, uploading, sending]);

  const handleFilesSelected = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? []);
      e.target.value = "";
      if (!activeId || files.length === 0) return;

      const wantZk = zkClaim;
      const canZk =
        wantZk &&
        !!walletPubkey &&
        typeof walletSignMessage === "function" &&
        typeof walletSignTransaction === "function";
      if (wantZk && !canZk) {
        setError(
          "Connect a Phantom/Solflare wallet to register a ZK ownership claim."
        );
        return;
      }

      setUploading(true);
      setError(null);
      try {
        for (const file of files) {
          const fd = new FormData();
          fd.append("file", file);
          let commitmentHex: string | undefined;
          let fileHashHex: string | undefined;
          if (canZk && walletPubkey && walletSignMessage) {
            const input = await prepareFileOwnershipInput(file, {
              publicKey: walletPubkey,
              signMessage: walletSignMessage,
            });
            fileHashHex = bytesToHex(input.fileHash);
            commitmentHex = bigintToHex32(input.commitment);
            fd.append("file_hash_hex", fileHashHex);
            fd.append("ownership_commitment_hex", commitmentHex);
          }

          const res = await api.post<{
            id: string;
            original_filename: string;
            size_bytes: number;
          }>(`/agent/sessions/${activeId}/uploads`, fd, {
            headers: { "Content-Type": "multipart/form-data" },
          });

          const initialEntry: AttachedUpload = {
            id: res.data.id,
            filename: res.data.original_filename,
            size_bytes: res.data.size_bytes,
            file_hash_hex: fileHashHex,
            ownership_commitment_hex: commitmentHex,
            ownership_status: canZk ? "claim_pending" : "none",
          };
          setAttachedFiles((prev) => [...prev, initialEntry]);

          // Fire-and-forget on-chain proof submit so the user does not
          // have to wait on Phantom + devnet to finish typing the next
          // message. Status updates flow back into the chip via setState.
          if (canZk && fileHashHex && commitmentHex) {
            (async () => {
              try {
                setAttachedFiles((prev) =>
                  prev.map((f) =>
                    f.id === res.data.id
                      ? { ...f, ownership_status: "proving" as const }
                      : f
                  )
                );
                const proof = await proveDocumentOwnershipOnChain({
                  fileHashHex: fileHashHex!,
                  expectedCommitmentHex: commitmentHex!,
                  wallet: {
                    publicKey: walletPubkey!,
                    signMessage: walletSignMessage!,
                    signTransaction: walletSignTransaction!,
                  },
                });
                await api.post(
                  `/agent/uploads/${res.data.id}/attach-ownership-proof`,
                  { proof_pda: proof.proofPda }
                );
                setAttachedFiles((prev) =>
                  prev.map((f) =>
                    f.id === res.data.id
                      ? {
                          ...f,
                          ownership_status: "verified" as const,
                          ownership_proof_pda: proof.proofPda,
                          ownership_tx_url: proof.explorerTxUrl || undefined,
                          ownership_pda_url: proof.explorerPdaUrl || undefined,
                        }
                      : f
                  )
                );
              } catch (err) {
                setAttachedFiles((prev) =>
                  prev.map((f) =>
                    f.id === res.data.id
                      ? {
                          ...f,
                          ownership_status: "failed" as const,
                          ownership_error: extractErrorMessage(
                            err,
                            "Ownership proof failed."
                          ),
                        }
                      : f
                  )
                );
              }
            })();
          }
        }
      } catch (err) {
        setError(extractErrorMessage(err, "File upload failed."));
      } finally {
        setUploading(false);
      }
    },
    [activeId, zkClaim, walletPubkey, walletSignMessage, walletSignTransaction]
  );

  const handleRemoveAttached = useCallback(
    async (uploadId: string) => {
      try {
        await api.delete(`/agent/uploads/${uploadId}`);
      } catch {
        // Best effort: drop the chip even if cancel fails so the UI is
        // not stuck. The orphan upload row is harmless.
      }
      setAttachedFiles((prev) => prev.filter((f) => f.id !== uploadId));
    },
    []
  );

  const handleSend = useCallback(async () => {
    const content = input.trim();
    const hasAttachments = attachedFiles.length > 0;
    if (!activeId || sending) return;
    if (!content && !hasAttachments) return;

    // When the user attaches files, prepend a machine-readable cue so
    // the agent reaches for list_session_uploads and validate_uploaded_document
    // without us having to invent a chat-side workflow.
    let payload = content;
    if (hasAttachments) {
      const ids = attachedFiles.map((f) => f.id).join(", ");
      const names = attachedFiles.map((f) => f.filename).join(", ");
      const cue =
        `[Attached upload_ids: ${ids} (${names})]` +
        " Please call list_session_uploads, then validate_uploaded_document for each new upload before continuing.";
      payload = content ? `${cue}\n\n${content}` : cue;
    }

    setSending(true);
    setError(null);
    try {
      const res = await api.post<TurnResponse>(
        `/agent/sessions/${activeId}/messages`,
        { content: payload }
      );
      setMessages((prev) => [...prev, ...res.data.messages]);
      setSessions((prev) =>
        prev.map((s) => (s.id === activeId ? res.data.session : s))
      );
      setInput("");
      setAttachedFiles([]);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to send message."));
    } finally {
      setSending(false);
    }
  }, [activeId, input, sending, attachedFiles]);

  const handleDelete = useCallback(
    async (id: string) => {
      const confirmed = window.confirm(
        "Delete this session? Messages will be removed unless a payment or filing was made."
      );
      if (!confirmed) return;
      try {
        await api.delete(`/agent/sessions/${id}`);
        setSessions((prev) => prev.filter((s) => s.id !== id));
        if (activeId === id) {
          setActiveId(null);
          setMessages([]);
        }
      } catch (err) {
        setError(extractErrorMessage(err, "Failed to delete session."));
      }
    },
    [activeId]
  );

  const handleStartRename = (session: AgentSession) => {
    setRenameId(session.id);
    setRenameValue(session.title ?? "");
  };

  const handleSaveRename = async (id: string) => {
    const title = renameValue.trim();
    if (!title) {
      setRenameId(null);
      return;
    }
    try {
      const res = await api.patch<AgentSession>(`/agent/sessions/${id}`, {
        title,
      });
      setSessions((prev) =>
        prev.map((s) => (s.id === id ? res.data : s))
      );
      setRenameId(null);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to rename session."));
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex h-[calc(100vh-7rem)] gap-4">
      {/* Session sidebar */}
      <aside className="flex w-72 flex-col rounded-xl border border-[color:var(--color-stone)] bg-[color:var(--color-linen)]">
        <div className="flex items-center justify-between border-b border-[color:var(--color-stone)] px-4 py-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-[color:var(--color-espresso)]">
            Sessions
          </h2>
          <button
            type="button"
            onClick={handleNewSession}
            className="rounded-md bg-[color:var(--color-bronze)] px-3 py-1 text-xs font-semibold text-[color:var(--color-cream)] hover:bg-[color:var(--color-bronze-dark)]"
          >
            + New
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {sessions.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs text-[color:var(--color-muted)]">
              No sessions yet. Start one to chat with EtornieGPT.
            </p>
          ) : (
            <ul className="space-y-1">
              {sessions.map((session) => {
                const isActive = session.id === activeId;
                const isRenaming = renameId === session.id;
                return (
                  <li
                    key={session.id}
                    className={`group rounded-lg px-3 py-2 text-sm transition-colors ${
                      isActive
                        ? "bg-[color:var(--color-bronze)]/10 text-[color:var(--color-espresso)]"
                        : "text-[color:var(--color-ink)] hover:bg-[color:var(--color-sand)]"
                    }`}
                  >
                    {isRenaming ? (
                      <div className="flex items-center gap-2">
                        <input
                          autoFocus
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleSaveRename(session.id);
                            if (e.key === "Escape") setRenameId(null);
                          }}
                          className="flex-1 rounded border border-[color:var(--color-stone)] bg-white px-2 py-1 text-sm text-[color:var(--color-ink)]"
                        />
                        <button
                          type="button"
                          onClick={() => handleSaveRename(session.id)}
                          className="text-xs font-semibold text-[color:var(--color-bronze)]"
                        >
                          Save
                        </button>
                        <button
                          type="button"
                          onClick={() => setRenameId(null)}
                          className="text-xs text-[color:var(--color-muted)]"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center justify-between gap-2">
                        <button
                          type="button"
                          onClick={() => setActiveId(session.id)}
                          className="flex-1 truncate text-left"
                          title={session.title ?? "Untitled session"}
                        >
                          <span className="block truncate font-medium">
                            {session.title ?? "Untitled session"}
                          </span>
                          <span className="block text-[10px] uppercase tracking-wider text-[color:var(--color-muted)]">
                            {formatTime(session.last_activity_at)} · in{" "}
                            {formatTokens(session.total_input_tokens)} / out{" "}
                            {formatTokens(session.total_output_tokens)}
                          </span>
                        </button>
                        <div className="flex shrink-0 items-center gap-1 opacity-0 group-hover:opacity-100">
                          <button
                            type="button"
                            onClick={() => handleStartRename(session)}
                            title="Rename"
                            className="rounded p-1 text-[color:var(--color-muted)] hover:bg-[color:var(--color-sand)] hover:text-[color:var(--color-espresso)]"
                          >
                            <svg
                              xmlns="http://www.w3.org/2000/svg"
                              fill="none"
                              viewBox="0 0 24 24"
                              strokeWidth={1.75}
                              stroke="currentColor"
                              className="h-4 w-4"
                            >
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487zm0 0L19.5 7.125"
                              />
                            </svg>
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDelete(session.id)}
                            title="Delete"
                            className="rounded p-1 text-[color:var(--color-muted)] hover:bg-[color:var(--color-sand)] hover:text-red-600"
                          >
                            <svg
                              xmlns="http://www.w3.org/2000/svg"
                              fill="none"
                              viewBox="0 0 24 24"
                              strokeWidth={1.75}
                              stroke="currentColor"
                              className="h-4 w-4"
                            >
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"
                              />
                            </svg>
                          </button>
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </aside>

      {/* Chat pane */}
      <section className="flex flex-1 flex-col rounded-xl border border-[color:var(--color-stone)] bg-[color:var(--color-cream)]">
        {activeSession ? (
          <header className="border-b border-[color:var(--color-stone)] px-5 py-3">
            <h1 className="truncate text-base font-semibold text-[color:var(--color-espresso)]">
              {activeSession.title ?? "Untitled session"}
            </h1>
            <p className="text-[11px] uppercase tracking-widest text-[color:var(--color-muted)]">
              {activeSession.model} · in{" "}
              {formatTokens(activeSession.total_input_tokens)} / out{" "}
              {formatTokens(activeSession.total_output_tokens)}
            </p>
          </header>
        ) : (
          <header className="border-b border-[color:var(--color-stone)] px-5 py-3">
            <h1 className="text-base font-semibold text-[color:var(--color-espresso)]">
              EtornieGPT
            </h1>
            <p className="text-[11px] uppercase tracking-widest text-[color:var(--color-muted)]">
              Pick a session on the left, or start a new one.
            </p>
          </header>
        )}

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {!activeSession ? (
            <p className="mt-12 text-center text-sm text-[color:var(--color-muted)]">
              No session selected.
            </p>
          ) : messages.length === 0 ? (
            <p className="mt-12 text-center text-sm text-[color:var(--color-muted)]">
              Send your first message to begin.
            </p>
          ) : (
            <ul className="space-y-3">
              {messages.map((m) => (
                <MessageRow key={m.id} message={m} />
              ))}
            </ul>
          )}
          <div ref={messagesEndRef} />
        </div>

        {filingProgress && <FilingProgressPanel progress={filingProgress} />}

        {error && (
          <div className="border-t border-red-200 bg-red-50 px-5 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="border-t border-[color:var(--color-stone)] px-5 py-3">
          {attachedFiles.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2">
              {attachedFiles.map((f) => {
                const zkBadge =
                  f.ownership_status === "verified"
                    ? "ZK ok"
                    : f.ownership_status === "proving"
                      ? "ZK proving"
                      : f.ownership_status === "claim_pending"
                        ? "ZK pending"
                        : f.ownership_status === "failed"
                          ? "ZK failed"
                          : null;
                const zkColor =
                  f.ownership_status === "verified"
                    ? "text-emerald-700"
                    : f.ownership_status === "failed"
                      ? "text-red-700"
                      : "text-[color:var(--color-muted)]";
                const showZkDetails =
                  f.ownership_status !== "none" &&
                  (f.file_hash_hex ||
                    f.ownership_commitment_hex ||
                    f.ownership_proof_pda);
                return (
                  <div
                    key={f.id}
                    className="flex flex-col gap-1 rounded-xl border border-[color:var(--color-stone)] bg-[color:var(--color-sand)] px-3 py-2"
                  >
                    <span className="inline-flex items-center gap-2 text-xs text-[color:var(--color-ink)]">
                      <span
                        className="truncate max-w-[16rem]"
                        title={`${(f.size_bytes / 1024).toFixed(1)} KB`}
                      >
                        {f.filename}
                      </span>
                      {zkBadge && (
                        <span className={`text-[10px] font-semibold ${zkColor}`}>
                          {zkBadge}
                        </span>
                      )}
                      {f.ownership_tx_url && (
                        <a
                          href={f.ownership_tx_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[10px] text-[color:var(--color-bronze)] underline"
                          title="Open verify tx on Solscan"
                        >
                          tx
                        </a>
                      )}
                      {f.ownership_pda_url && (
                        <a
                          href={f.ownership_pda_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[10px] text-[color:var(--color-bronze)] underline"
                          title="Open FileOwnershipRecord PDA on Solscan"
                        >
                          pda
                        </a>
                      )}
                      <button
                        type="button"
                        aria-label={`Remove ${f.filename}`}
                        onClick={() => handleRemoveAttached(f.id)}
                        className="ml-1 text-[color:var(--color-muted)] hover:text-[color:var(--color-ink)]"
                      >
                        ×
                      </button>
                    </span>
                    {showZkDetails && (
                      <div className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 font-mono text-[10px] leading-tight text-[color:var(--color-muted)]">
                        {f.file_hash_hex && (
                          <>
                            <span>sha256</span>
                            <span title={f.file_hash_hex} className="break-all">
                              {shortHash(f.file_hash_hex)}
                            </span>
                          </>
                        )}
                        {f.ownership_commitment_hex && (
                          <>
                            <span>commit</span>
                            <span
                              title={f.ownership_commitment_hex}
                              className="break-all"
                            >
                              {shortHash(f.ownership_commitment_hex)}
                            </span>
                          </>
                        )}
                        {f.ownership_proof_pda && (
                          <>
                            <span>pda</span>
                            <span
                              title={f.ownership_proof_pda}
                              className="break-all"
                            >
                              {shortHash(f.ownership_proof_pda)}
                            </span>
                          </>
                        )}
                        {f.ownership_error && (
                          <>
                            <span className="text-red-700">error</span>
                            <span className="break-all text-red-700">
                              {f.ownership_error}
                            </span>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
          <div className="mb-2 flex items-center gap-2 text-xs text-[color:var(--color-muted)]">
            <input
              id="zk-claim-toggle"
              type="checkbox"
              checked={zkClaim}
              onChange={(e) => setZkClaim(e.target.checked)}
              disabled={!walletPubkey || sending}
              className="h-3 w-3"
            />
            <label htmlFor="zk-claim-toggle" className="select-none">
              Register on-chain ZK ownership proof for uploads
              {!walletPubkey && (
                <span className="ml-1 italic">(wallet required)</span>
              )}
            </label>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={handleFilesSelected}
            accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,.tiff,.bmp"
          />
          <div className="flex items-end gap-2">
            <button
              type="button"
              onClick={handleAttachClick}
              disabled={!activeSession || sending || uploading}
              title="Attach files (PDF or image). The agent will validate them automatically."
              className="rounded-lg border border-[color:var(--color-stone)] bg-white px-3 py-2 text-sm font-medium text-[color:var(--color-ink)] hover:bg-[color:var(--color-sand)] disabled:bg-[color:var(--color-stone)] disabled:text-[color:var(--color-muted)]"
            >
              {uploading ? "Uploading…" : "Attach"}
            </button>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={!activeSession || sending}
              placeholder={
                activeSession
                  ? "Type your message…  (Enter to send, Shift+Enter for newline)"
                  : "Start or pick a session first."
              }
              rows={2}
              className="flex-1 resize-none rounded-lg border border-[color:var(--color-stone)] bg-white px-3 py-2 text-sm text-[color:var(--color-ink)] focus:border-[color:var(--color-bronze)] focus:outline-none disabled:bg-[color:var(--color-sand)]/50"
            />
            <button
              type="button"
              onClick={handleSend}
              disabled={
                !activeSession ||
                sending ||
                uploading ||
                (!input.trim() && attachedFiles.length === 0)
              }
              className="rounded-lg bg-[color:var(--color-bronze)] px-4 py-2 text-sm font-semibold text-[color:var(--color-cream)] hover:bg-[color:var(--color-bronze-dark)] disabled:bg-[color:var(--color-stone)] disabled:text-[color:var(--color-muted)]"
            >
              {sending ? "Sending…" : "Send"}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

interface PaymentRequirements {
  submission_id: string;
  vault: string;
  lamports: number;
  currency: string;
  network: string;
  memo_scheme: string;
  query_hash_hex: string;
  query_hash_payload: string;
  platform_fee_gbp: number;
}

interface PaymentConfirmResult {
  submission_id: string;
  case_id: string;
  case_number: string;
  status: string;
  payer_wallet: string;
  payment_tx: string;
  payment_lamports: number;
  query_hash_hex: string;
  commitment_hex: string;
  compliance_tx: string;
  compliance_pda: string;
  payment_explorer_url: string;
  compliance_explorer_url: string;
  compliance_record_explorer_url: string;
}

function hexToBytes(hex: string): Uint8Array {
  const clean = hex.startsWith("0x") ? hex.slice(2) : hex;
  if (clean.length % 2 !== 0) throw new Error("hex has odd length");
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

function bytesToBase64(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

async function sha256Concat(a: Uint8Array, b: Uint8Array): Promise<Uint8Array> {
  const joined = new Uint8Array(a.length + b.length);
  joined.set(a, 0);
  joined.set(b, a.length);
  const digest = await crypto.subtle.digest("SHA-256", joined);
  return new Uint8Array(digest);
}

function FilingProgressPanel({ progress }: { progress: FilingProgress }) {
  const { connection } = useConnection();
  const wallet = useWallet();
  const [paying, setPaying] = useState(false);
  const [payStage, setPayStage] = useState<string | null>(null);
  const [paymentResult, setPaymentResult] = useState<PaymentConfirmResult | null>(null);
  const [paymentError, setPaymentError] = useState<string | null>(null);

  const stepLabel = progress.current_step
    ? STEP_LABELS[progress.current_step] ?? progress.current_step
    : null;
  const statusLabel = STATUS_LABELS[progress.status];
  const isRunning = progress.status === "running" || progress.status === "pending";
  const isAwaitingPayment = progress.status === "awaiting_payment";
  const isFailed = progress.status === "failed";

  let tone = "bg-[color:var(--color-sand)] border-[color:var(--color-stone)]";
  if (isAwaitingPayment) tone = "bg-amber-50 border-amber-300";
  if (isFailed) tone = "bg-red-50 border-red-300";

  const handlePay = useCallback(async () => {
    setPaymentError(null);
    setPayStage(null);
    if (
      !wallet.connected ||
      !wallet.publicKey ||
      !wallet.signTransaction ||
      typeof wallet.signMessage !== "function"
    ) {
      setPaymentError(
        "Connect a Solana wallet that exposes signMessage and signTransaction (Phantom/Solflare)."
      );
      return;
    }
    setPaying(true);
    try {
      // 1. Pull the canonical filing-context query hash + payment vault
      //    from the backend. This is the same hash the backend will
      //    re-derive at confirm time, so binding the proof to it is
      //    enough to commit on-chain to this exact submission.
      setPayStage("Loading payment requirements…");
      const reqRes = await api.get<PaymentRequirements>(
        `/agent/filings/${progress.submission_id}/payment-requirements`
      );
      const req = reqRes.data;
      const queryHash = hexToBytes(req.query_hash_hex);
      if (queryHash.length !== 32) {
        throw new Error("Backend returned a malformed query_hash_hex.");
      }

      // 2. Derive secret + commitment locally — single signMessage popup.
      setPayStage("Approve signature for compliance commitment…");
      const { qhHi, qhLo } = splitQueryHash(queryHash);
      const secret = await deriveDeterministicSecret(
        { publicKey: wallet.publicKey, signMessage: wallet.signMessage! },
        queryHash
      );
      const commitment = await computeCommitment(secret, qhHi, qhLo);
      const commitmentBytes = bigintToBE32(commitment);

      // 3. Memo = base58(sha256(query_hash || commitment)) — backend
      //    will recompute and assert the on-chain payment tx carries
      //    exactly this memo before accepting the proof.
      const memoDigest = await sha256Concat(queryHash, commitmentBytes);
      const memo = bs58.encode(memoDigest);

      // 4. Build + sign + send the SOL transfer with the memo binding.
      setPayStage("Building payment transaction…");
      const transferIx = SystemProgram.transfer({
        fromPubkey: wallet.publicKey,
        toPubkey: new PublicKey(req.vault),
        lamports: req.lamports,
      });
      const memoIx = new TransactionInstruction({
        programId: MEMO_PROGRAM_ID,
        keys: [],
        data: Buffer.from(new TextEncoder().encode(memo)),
      });
      const latest = await connection.getLatestBlockhash("confirmed");
      const message = new TransactionMessage({
        payerKey: wallet.publicKey,
        recentBlockhash: latest.blockhash,
        instructions: [transferIx, memoIx],
      }).compileToV0Message();
      const tx = new VersionedTransaction(message);

      setPayStage("Approve payment in your wallet…");
      const signed = await wallet.signTransaction(tx);
      setPayStage("Broadcasting payment to devnet…");
      const signature = await connection.sendRawTransaction(signed.serialize(), {
        skipPreflight: false,
        maxRetries: 5,
      });
      const confirmation = await connection.confirmTransaction(
        {
          signature,
          blockhash: latest.blockhash,
          lastValidBlockHeight: latest.lastValidBlockHeight,
        },
        "confirmed"
      );
      if (confirmation.value.err) {
        throw new Error(
          `Transaction failed on-chain: ${JSON.stringify(confirmation.value.err)}`
        );
      }

      // 5. Generate the Groth16 compliance proof in the browser. No
      //    wallet interaction; the proof binds (secret, query_hash) to
      //    the same commitment baked into the payment memo.
      setPayStage("Generating Groth16 compliance proof…");
      const proofBundle = await generateComplianceProof({
        queryHash,
        qhHi,
        qhLo,
        secret,
        commitment,
      });

      // 6. Send proof + payment tx; backend verifies the payment on
      //    chain, submits the verify_compliance_proof tx via the
      //    operator, and flips the submission to filed.
      setPayStage("Submitting proof to backend…");
      const confirmRes = await api.post<PaymentConfirmResult>(
        `/agent/filings/${progress.submission_id}/confirm-payment`,
        {
          payer_wallet: wallet.publicKey.toBase58(),
          payment_tx: signature,
          compliance_proof: {
            proof_a_b64: bytesToBase64(proofBundle.onchain.proofA),
            proof_b_b64: bytesToBase64(proofBundle.onchain.proofB),
            proof_c_b64: bytesToBase64(proofBundle.onchain.proofC),
            public_inputs_b64: proofBundle.onchain.publicInputs.map(bytesToBase64),
            query_hash_b64: bytesToBase64(queryHash),
          },
        }
      );
      setPaymentResult(confirmRes.data);
      setPayStage(null);
    } catch (err) {
      setPaymentError(extractErrorMessage(err, "Payment failed."));
      setPayStage(null);
    } finally {
      setPaying(false);
    }
  }, [connection, wallet, progress.submission_id]);

  return (
    <div className={`border-t ${tone} px-5 py-3`}>
      <div className="flex items-center gap-3">
        {isRunning && (
          <span className="inline-block h-2.5 w-2.5 animate-pulse rounded-full bg-[color:var(--color-bronze)]" />
        )}
        {isAwaitingPayment && (
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-amber-500" />
        )}
        {isFailed && (
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-500" />
        )}
        <span className="text-xs font-semibold uppercase tracking-wider text-[color:var(--color-espresso)]">
          UK IPO Robot
        </span>
        <span className="text-xs text-[color:var(--color-muted)]">
          {progress.mark_text} · {progress.owner_company_name}
        </span>
      </div>
      <div className="mt-1.5 text-sm text-[color:var(--color-ink)]">
        <span className="font-semibold">{statusLabel}</span>
        {stepLabel && (
          <>
            {", "}
            <span>Step: {stepLabel}</span>
          </>
        )}
      </div>
      {isFailed && progress.error_message && (
        <p className="mt-1 text-xs text-red-700">
          {progress.error_step ? `${progress.error_step}: ` : ""}
          {progress.error_message}
        </p>
      )}
      {isAwaitingPayment && !paymentResult && (
        <div className="mt-2 flex flex-col gap-2">
          <p className="text-xs text-amber-800">
            The robot finished preparing the application. Choose a
            payment method below — backend verifies the on-chain
            attestation and a Groth16 compliance proof before filing
            in either lane.
          </p>
          <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center">
            <button
              type="button"
              onClick={handlePay}
              disabled={paying || !wallet.connected}
              className="rounded-md bg-[color:var(--color-bronze)] px-3 py-1.5 text-xs font-semibold text-[color:var(--color-cream)] hover:bg-[color:var(--color-bronze-dark)] disabled:bg-[color:var(--color-stone)] disabled:text-[color:var(--color-muted)]"
              title={
                wallet.connected
                  ? "Pay via Phantom / Solflare with USDC on Solana"
                  : "Connect a Solana wallet to pay with x402"
              }
            >
              {paying ? "Confirming…" : "Pay with wallet (x402)"}
            </button>
            <UkipoStripePayButton submissionId={progress.submission_id} />
          </div>
        </div>
      )}
      {paying && payStage && (
        <p className="mt-1 text-xs text-amber-800">{payStage}</p>
      )}
      {paymentResult && (
        <div className="mt-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
          <p className="font-semibold">
            Payment + compliance proof verified on-chain.
          </p>
          <div className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 font-mono text-[10px] leading-tight">
            <span>payment</span>
            <a
              href={paymentResult.payment_explorer_url}
              target="_blank"
              rel="noopener noreferrer"
              className="break-all underline"
              title={paymentResult.payment_tx}
            >
              {shortHash(paymentResult.payment_tx, 12, 8)}
            </a>
            <span>compliance</span>
            <a
              href={paymentResult.compliance_explorer_url}
              target="_blank"
              rel="noopener noreferrer"
              className="break-all underline"
              title={paymentResult.compliance_tx}
            >
              {shortHash(paymentResult.compliance_tx, 12, 8)}
            </a>
            <span>pda</span>
            <a
              href={paymentResult.compliance_record_explorer_url}
              target="_blank"
              rel="noopener noreferrer"
              className="break-all underline"
              title={paymentResult.compliance_pda}
            >
              {shortHash(paymentResult.compliance_pda, 12, 8)}
            </a>
            <span>query</span>
            <span title={paymentResult.query_hash_hex} className="break-all">
              {shortHash(paymentResult.query_hash_hex)}
            </span>
            <span>commit</span>
            <span title={paymentResult.commitment_hex} className="break-all">
              {shortHash(paymentResult.commitment_hex)}
            </span>
            <span>lamports</span>
            <span>{paymentResult.payment_lamports}</span>
            <span>status</span>
            <span>{paymentResult.status}</span>
          </div>
        </div>
      )}
      {paymentError && (
        <p className="mt-1 text-xs text-red-700">{paymentError}</p>
      )}
      {(paymentResult || progress.status === "filed") && progress.case_id && (
        <NftClaimPanel
          caseId={progress.case_id}
          caseNumber={progress.case_number}
        />
      )}
      {progress.ipo_application_url && (
        <p className="mt-1 text-xs">
          <a
            href={progress.ipo_application_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[color:var(--color-bronze)] underline"
          >
            UK IPO application page
          </a>
        </p>
      )}
    </div>
  );
}


function MessageRow({ message }: { message: AgentMessage }) {
  if (message.role === "user") {
    return (
      <li className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-md bg-[color:var(--color-bronze)] px-4 py-2 text-sm text-[color:var(--color-cream)] whitespace-pre-wrap">
          {message.content}
        </div>
      </li>
    );
  }

  if (message.role === "assistant") {
    if (message.tool_name) {
      return (
        <li className="flex justify-start">
          <ToolCallBadge
            toolName={message.tool_name}
            toolArguments={message.tool_arguments}
            phase="call"
          />
        </li>
      );
    }
    return (
      <li className="flex justify-start">
        <div className="max-w-[80%] rounded-2xl rounded-bl-md bg-[color:var(--color-linen)] px-4 py-2 text-sm text-[color:var(--color-ink)]">
          {message.content ? (
            renderMarkdown(message.content)
          ) : (
            <span className="text-[color:var(--color-muted)] italic">
              (empty assistant message)
            </span>
          )}
        </div>
      </li>
    );
  }

  // role === "tool"
  return (
    <li className="flex flex-col items-start gap-2">
      <ToolCallBadge
        toolName={message.tool_name ?? "tool"}
        toolResult={message.tool_result}
        phase="result"
      />
      {message.tool_name === "prepare_payment" && (
        <PreparePaymentPanel result={message.tool_result} />
      )}
    </li>
  );
}

interface PreparePaymentResult {
  case_draft_id?: string;
  platform?: string;
  amount?: number | string;
  currency?: string;
  draft_status?: string;
  intent_status?: string;
}

const STRIPE_SUPPORTED_PLATFORMS = ["EUIPO", "WIPO", "USPTO", "UKIPO"] as const;
type StripePlatform = (typeof STRIPE_SUPPORTED_PLATFORMS)[number];

function PreparePaymentPanel({
  result,
}: {
  result?: Record<string, unknown> | null;
}) {
  const parsed = (result && typeof result === "object"
    ? (result as PreparePaymentResult)
    : null);
  const caseDraftId = parsed?.case_draft_id;
  const platform = parsed?.platform;
  const amount = parsed?.amount;
  const currency = parsed?.currency;

  const eligible =
    typeof caseDraftId === "string" &&
    typeof platform === "string" &&
    typeof currency === "string" &&
    (typeof amount === "number" || typeof amount === "string") &&
    STRIPE_SUPPORTED_PLATFORMS.includes(platform as StripePlatform);

  // Live aggregate status across every PaymentIntent for this draft
  // (x402 + Stripe). Without it, the stale tool_result snapshot would
  // keep prompting the user to pay after Stripe Checkout has already
  // settled the fee on a separate PaymentIntent.
  const [status, setStatus] = useState<CaseDraftPaymentStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  useEffect(() => {
    if (!eligible || typeof caseDraftId !== "string") return;
    let cancelled = false;
    fetchCaseDraftPaymentStatus(caseDraftId)
      .then((s) => {
        if (!cancelled) setStatus(s);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setStatusError(
          extractErrorMessage(err, "Could not check payment status.")
        );
      });
    return () => {
      cancelled = true;
    };
  }, [caseDraftId, eligible]);

  if (!eligible || typeof caseDraftId !== "string" || typeof platform !== "string" ||
      typeof currency !== "string" || (typeof amount !== "number" && typeof amount !== "string")) {
    return null;
  }

  if (status?.paid) {
    const paidAmount = status.confirmed_amount ?? String(amount);
    const paidCurrency = status.confirmed_currency ?? currency;
    const formatted = (() => {
      const n = Number(paidAmount);
      if (!Number.isFinite(n)) return `${paidAmount} ${paidCurrency}`;
      try {
        return new Intl.NumberFormat(undefined, {
          style: "currency",
          currency: paidCurrency.toUpperCase(),
        }).format(n);
      } catch {
        return `${n.toFixed(2)} ${paidCurrency.toUpperCase()}`;
      }
    })();
    const providerLabel =
      status.confirmed_provider === "stripe"
        ? "card via Stripe"
        : status.confirmed_provider === "x402"
          ? "x402 wallet"
          : status.confirmed_provider ?? "the configured provider";

    const filingRef = status.filing_external_reference;
    const filingError = status.filing_error;
    const filingStatus = status.filing_status;
    const onchainTx = status.compliance_onchain_tx;
    const caseId = status.case_id;
    const caseNumber = status.case_number;

    return (
      <div className="flex max-w-[80%] flex-col gap-2">
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2">
          <p className="text-xs font-semibold text-emerald-900">
            ✓ Paid {formatted} with {providerLabel}.
          </p>
          {filingRef ? (
            <p className="mt-1 text-[11px] text-emerald-900">
              Submitted to {platform}: application{" "}
              <span className="font-mono font-semibold">{filingRef}</span>
            </p>
          ) : filingError ? (
            <p className="mt-1 text-[11px] text-amber-900">
              Payment captured but {platform} submission failed: {filingError}.
              Ask the agent to retry with submit_filing.
            </p>
          ) : filingStatus === "pending" ? (
            <p className="mt-1 text-[11px] text-emerald-800">
              Submitting to {platform} now…
            </p>
          ) : (
            <p className="mt-0.5 text-[10px] text-emerald-800">
              Filing draft is now ready to be submitted.
            </p>
          )}
          {onchainTx && (
            <p className="mt-1 text-[10px] text-emerald-800">
              Compliance proof verified on-chain:{" "}
              <a
                href={`https://explorer.solana.com/tx/${onchainTx}?cluster=devnet`}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono underline"
              >
                {onchainTx.slice(0, 12)}…
              </a>
            </p>
          )}
        </div>
        {caseId && caseNumber && (
          <NftClaimPanel caseId={caseId} caseNumber={caseNumber} />
        )}
      </div>
    );
  }

  return (
    <div className="max-w-[80%] rounded-lg border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] px-3 py-2">
      <p className="text-xs text-[color:var(--color-muted)]">
        Payment options — pick one to settle this filing fee:
      </p>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
        <StripeCheckoutButton
          caseDraftId={caseDraftId}
          platform={platform as StripePlatform}
          amount={amount}
          currency={currency}
        />
        <span className="text-[10px] text-[color:var(--color-muted)] sm:ml-2">
          Or approve the existing x402 wallet challenge above.
        </span>
      </div>
      {statusError && (
        <p className="mt-1 text-[10px] text-red-700">{statusError}</p>
      )}
    </div>
  );
}

function UkipoStripePayButton({ submissionId }: { submissionId: string }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    setError(null);
    setLoading(true);
    try {
      const session = await createUkipoStripeCheckoutSession(submissionId);
      try {
        sessionStorage.setItem(
          `stripe_ukipo:${session.checkout_session_id}`,
          submissionId,
        );
      } catch {
        // sessionStorage may be unavailable; not critical.
      }
      window.location.assign(session.checkout_url);
    } catch (err: unknown) {
      setError(
        extractErrorMessage(err, "Could not open the Stripe checkout."),
      );
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={handleClick}
        disabled={loading}
        className="rounded-md bg-[color:var(--color-ink)] px-3 py-1.5 text-xs font-semibold text-[color:var(--color-cream)] hover:bg-[color:var(--color-espresso)] disabled:bg-[color:var(--color-stone)] disabled:text-[color:var(--color-muted)]"
        title="Pay £265 GBP via Stripe (card / Apple Pay / Google Pay)"
      >
        {loading ? "Opening checkout…" : "Pay £265 with card (Stripe)"}
      </button>
      {error && (
        <p className="text-[10px] text-red-700" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}


interface ToolCallBadgeProps {
  toolName: string;
  toolArguments?: Record<string, unknown> | null;
  toolResult?: Record<string, unknown> | null;
  phase: "call" | "result";
}

function ToolCallBadge({
  toolName,
  toolArguments,
  toolResult,
  phase,
}: ToolCallBadgeProps) {
  const [open, setOpen] = useState(false);
  const label =
    phase === "call"
      ? `→ called ${toolName}`
      : `← ${toolName} result`;
  const payload = phase === "call" ? toolArguments : toolResult;
  return (
    <div className="max-w-[80%] rounded-lg border border-[color:var(--color-stone)] bg-[color:var(--color-sand)]/40 px-3 py-1.5 text-xs">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="font-mono text-[color:var(--color-espresso)] hover:underline"
      >
        {open ? "▾" : "▸"} {label}
      </button>
      {open && payload && (
        <pre className="mt-2 max-h-64 overflow-auto rounded bg-white p-2 text-[10px] leading-snug text-[color:var(--color-ink)]">
          {JSON.stringify(payload, null, 2)}
        </pre>
      )}
    </div>
  );
}
