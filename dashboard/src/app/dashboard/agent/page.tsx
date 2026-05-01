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
  const pattern =
    /(\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\))/g;
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
    }
    lastIndex = pattern.lastIndex;
  }
  if (lastIndex < text.length) {
    tokens.push(text.slice(lastIndex));
  }
  return tokens;
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
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

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

  const handleSend = useCallback(async () => {
    const content = input.trim();
    if (!activeId || !content || sending) return;

    setSending(true);
    setError(null);
    try {
      const res = await api.post<TurnResponse>(
        `/agent/sessions/${activeId}/messages`,
        { content }
      );
      setMessages((prev) => [...prev, ...res.data.messages]);
      setSessions((prev) =>
        prev.map((s) => (s.id === activeId ? res.data.session : s))
      );
      setInput("");
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to send message."));
    } finally {
      setSending(false);
    }
  }, [activeId, input, sending]);

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
          <div className="flex items-end gap-2">
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
              disabled={!activeSession || sending || !input.trim()}
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
  memo: string;
  currency: string;
  network: string;
  platform_fee_gbp: number;
}

function FilingProgressPanel({ progress }: { progress: FilingProgress }) {
  const { connection } = useConnection();
  const wallet = useWallet();
  const [paying, setPaying] = useState(false);
  const [paymentTx, setPaymentTx] = useState<string | null>(null);
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
    if (!wallet.connected || !wallet.publicKey || !wallet.signTransaction) {
      setPaymentError("Connect your Solana wallet first.");
      return;
    }
    setPaying(true);
    try {
      const reqRes = await api.get<PaymentRequirements>(
        `/agent/filings/${progress.submission_id}/payment-requirements`
      );
      const req = reqRes.data;

      const transferIx = SystemProgram.transfer({
        fromPubkey: wallet.publicKey,
        toPubkey: new PublicKey(req.vault),
        lamports: req.lamports,
      });
      const memoIx = new TransactionInstruction({
        programId: MEMO_PROGRAM_ID,
        keys: [],
        data: Buffer.from(new TextEncoder().encode(req.memo)),
      });

      const latest = await connection.getLatestBlockhash("confirmed");
      const message = new TransactionMessage({
        payerKey: wallet.publicKey,
        recentBlockhash: latest.blockhash,
        instructions: [transferIx, memoIx],
      }).compileToV0Message();
      const tx = new VersionedTransaction(message);

      const signed = await wallet.signTransaction(tx);
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

      await api.post(
        `/agent/filings/${progress.submission_id}/confirm-payment`,
        {
          tx_signature: signature,
          payer_wallet: wallet.publicKey.toBase58(),
          lamports: req.lamports,
        }
      );
      setPaymentTx(signature);
    } catch (err) {
      setPaymentError(extractErrorMessage(err, "Payment failed."));
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
      {isAwaitingPayment && !paymentTx && (
        <div className="mt-2 flex items-center gap-3">
          <p className="flex-1 text-xs text-amber-800">
            The robot finished preparing the application. Approve the
            on-chain payment from your wallet to release the GBP fee.
          </p>
          <button
            type="button"
            onClick={handlePay}
            disabled={paying || !wallet.connected}
            className="rounded-md bg-[color:var(--color-bronze)] px-3 py-1.5 text-xs font-semibold text-[color:var(--color-cream)] hover:bg-[color:var(--color-bronze-dark)] disabled:bg-[color:var(--color-stone)] disabled:text-[color:var(--color-muted)]"
          >
            {paying ? "Confirming..." : "Pay"}
          </button>
        </div>
      )}
      {paymentTx && (
        <p className="mt-1 text-xs text-emerald-700">
          Payment recorded. Tx:{" "}
          <a
            href={`https://explorer.solana.com/tx/${paymentTx}?cluster=devnet`}
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono underline"
          >
            {paymentTx.slice(0, 10)}...{paymentTx.slice(-10)}
          </a>
        </p>
      )}
      {paymentError && (
        <p className="mt-1 text-xs text-red-700">{paymentError}</p>
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
    <li className="flex justify-start">
      <ToolCallBadge
        toolName={message.tool_name ?? "tool"}
        toolResult={message.tool_result}
        phase="result"
      />
    </li>
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
