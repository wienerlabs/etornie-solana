"use client";

import * as React from "react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useConnection, useWallet } from "@solana/wallet-adapter-react";
import { WalletMultiButton } from "@solana/wallet-adapter-react-ui";
import type { VersionedTransaction, Connection, SendOptions } from "@solana/web3.js";
import api, { extractErrorMessage } from "@/lib/api";
import {
  askEtornieGPTOverX402,
  fetchPaymentRequirements,
  lookupCachedAnswer,
  type ChatStage,
  type ChatResult,
  type PaymentRequirements,
} from "@/lib/x402/client";
import { sha256Query } from "@/lib/zk/compliance";

const STAGE_LABELS: Record<ChatStage, string> = {
  "deriving-secret": "Deriving compliance secret from wallet signature",
  "building-payment": "Building payment transaction",
  "signing-payment": "Waiting for wallet approval",
  "sending-payment": "Confirming payment on devnet",
  proving: "Generating zero-knowledge compliance proof",
  submitting: "Submitting to EtornieGPT backend",
  done: "Done",
};

interface ChatTurn {
  id: string;
  question: string;
  language: string;
  answer?: string;
  countryDetected?: string | null;
  paymentTx?: string;
  complianceTx?: string;
  compliancePda?: string;
  paymentExplorerUrl?: string;
  complianceExplorerUrl?: string;
  complianceRecordExplorerUrl?: string;
  stage?: ChatStage;
  error?: string;
  createdAt: Date;
  /** True when the reply was served from a prior paid run - no new
   *  payment or on-chain proof was needed. */
  fromCache?: boolean;
}

interface HistoryItem {
  id: string;
  question: string;
  answer: string;
  model: string;
  country_detected: string | null;
  language: string;
  query_hash_hex: string | null;
  payment_tx: string | null;
  compliance_tx: string | null;
  compliance_pda: string | null;
  created_at: string;
}

function short(s: string | null | undefined, n = 10): string {
  if (!s) return "-";
  if (s.length <= n * 2 + 1) return s;
  return `${s.slice(0, n)}…${s.slice(-n)}`;
}

function formatSol(lamports: number): string {
  return `${(lamports / 1_000_000_000).toFixed(6)} SOL`;
}

/** Render a minimal subset of markdown inline: **bold**, *italic*, and
 *  preserve line breaks. Lists ("- item") are kept as plain lines. This
 *  avoids pulling in a full markdown library while handling the common
 *  shapes the LLM emits. */
function renderMarkdown(text: string): ReactNode {
  const lines = text.split("\n");
  return lines.map((line, lineIdx) => (
    <span key={lineIdx}>
      {renderInlineMarkdown(line)}
      {lineIdx < lines.length - 1 ? <br /> : null}
    </span>
  ));
}

function renderInlineMarkdown(line: string): ReactNode[] {
  const tokens: ReactNode[] = [];
  // Match **bold**, *italic*, `code` (in that priority order).
  const pattern = /(\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = pattern.exec(line)) !== null) {
    if (match.index > lastIndex) {
      tokens.push(line.slice(lastIndex, match.index));
    }
    if (match[2] !== undefined) {
      tokens.push(<strong key={key++}>{match[2]}</strong>);
    } else if (match[3] !== undefined) {
      tokens.push(<em key={key++}>{match[3]}</em>);
    } else if (match[4] !== undefined) {
      tokens.push(
        <code
          key={key++}
          className="rounded bg-[color:var(--color-sand)] px-1 py-0.5 font-mono text-[11px]"
        >
          {match[4]}
        </code>,
      );
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < line.length) {
    tokens.push(line.slice(lastIndex));
  }
  return tokens;
}

export default function EtornieGPTChatPage() {
  const { connection } = useConnection();
  const wallet = useWallet();

  const [requirements, setRequirements] =
    useState<PaymentRequirements | null>(null);
  const [reqError, setReqError] = useState<string>("");

  const [language, setLanguage] = useState<string>("tr");
  const [input, setInput] = useState<string>("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [sending, setSending] = useState(false);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetchPaymentRequirements()
      .then((r) => {
        if (!cancelled) setRequirements(r);
      })
      .catch((err) => {
        if (cancelled) return;
        setReqError(extractErrorMessage(err, String(err)));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const { data } = await api.get<HistoryItem[]>(
        "/etorniegpt/chat/history?limit=20",
      );
      setHistory(data);
    } catch {
      // silent; history is a nice-to-have
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [turns]);

  const canSend = useMemo(() => {
    return (
      !!wallet.publicKey &&
      typeof wallet.sendTransaction === "function" &&
      typeof wallet.signMessage === "function" &&
      !!requirements &&
      !sending &&
      input.trim().length > 0
    );
  }, [
    wallet.publicKey,
    wallet.sendTransaction,
    wallet.signMessage,
    requirements,
    sending,
    input,
  ]);

  async function handleSend() {
    if (!canSend || !requirements || !wallet.publicKey) return;
    const question = input.trim();
    const turnId = crypto.randomUUID();
    setTurns((prev) => [
      ...prev,
      {
        id: turnId,
        question,
        language,
        stage: "deriving-secret",
        createdAt: new Date(),
      },
    ]);
    setInput("");
    setSending(true);

    try {
      if (!wallet.sendTransaction || !wallet.signMessage) {
        throw new Error("Wallet missing required capabilities");
      }

      // Cache pre-check: if this (wallet, question) pair already has an
      // answer on record, skip the payment/proof flow entirely and just
      // re-render the cached response. This matches the on-chain anti-
      // replay behavior (the ComplianceRecord PDA is idempotent) and
      // avoids asking the user to pay again for an identical query.
      const queryHash = await sha256Query(question);
      const cache = await lookupCachedAnswer({
        payerWallet: wallet.publicKey.toBase58(),
        queryHash,
      });
      if (cache.cached) {
        setTurns((prev) =>
          prev.map((t) =>
            t.id === turnId
              ? {
                  ...t,
                  answer: cache.answer,
                  countryDetected: cache.country_detected,
                  paymentTx: cache.payment_tx ?? undefined,
                  complianceTx: cache.compliance_tx ?? undefined,
                  compliancePda: cache.compliance_pda ?? undefined,
                  paymentExplorerUrl: cache.payment_explorer_url ?? undefined,
                  complianceExplorerUrl:
                    cache.compliance_explorer_url ?? undefined,
                  complianceRecordExplorerUrl:
                    cache.compliance_record_explorer_url ?? undefined,
                  stage: "done",
                  fromCache: true,
                }
              : t,
          ),
        );
        loadHistory();
        return;
      }
      const sendTx = wallet.sendTransaction as unknown as (
        tx: VersionedTransaction,
        c: Connection,
        options?: SendOptions,
      ) => Promise<string>;
      const result: ChatResult = await askEtornieGPTOverX402({
        question,
        language,
        wallet: {
          publicKey: wallet.publicKey,
          signMessage: wallet.signMessage.bind(wallet),
          sendTransaction: sendTx,
        },
        connection,
        requirements,
        onStage: (stage) => {
          setTurns((prev) =>
            prev.map((t) => (t.id === turnId ? { ...t, stage } : t)),
          );
        },
      });

      setTurns((prev) =>
        prev.map((t) =>
          t.id === turnId
            ? {
                ...t,
                answer: result.answer,
                countryDetected: result.country_detected,
                paymentTx: result.payment_tx,
                complianceTx: result.compliance_tx,
                compliancePda: result.compliance_pda,
                paymentExplorerUrl: result.payment_explorer_url,
                complianceExplorerUrl: result.compliance_explorer_url,
                complianceRecordExplorerUrl:
                  result.compliance_record_explorer_url,
                stage: "done",
              }
            : t,
        ),
      );
      loadHistory();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ??
        (err instanceof Error ? err.message : "Unexpected error");
      setTurns((prev) =>
        prev.map((t) =>
          t.id === turnId ? { ...t, error: message, stage: undefined } : t,
        ),
      );
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-7rem)] max-w-5xl flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] px-5 py-4">
        <div className="max-w-2xl">
          <h1 className="text-lg font-semibold text-[color:var(--color-espresso)]">
            EtornieGPT <span className="text-[color:var(--color-gold)]">x402</span>
          </h1>
          <p className="mt-1 text-xs leading-relaxed text-[color:var(--color-muted)]">
            Every question settles with a real SOL micropayment on Solana
            devnet plus a zero-knowledge compliance proof bound to the
            query. The answer is returned only after both are confirmed
            on-chain.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {requirements ? (
            <span className="chain-badge">
              <span className="chain-dot" />
              {formatSol(requirements.lamports)} / query
            </span>
          ) : reqError ? (
            <span className="text-xs text-red-600">Config error: {reqError}</span>
          ) : (
            <span className="text-xs text-[color:var(--color-muted)]">
              Loading requirements...
            </span>
          )}
        </div>
      </header>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto rounded-lg border border-[color:var(--color-stone)] bg-[color:var(--color-cream)] p-4"
      >
        {turns.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-sm text-[color:var(--color-muted)]">
            <p>No conversation yet.</p>
            {!wallet.publicKey ? (
              <>
                <p className="max-w-md text-xs">
                  Connect a Phantom or Solflare wallet to begin. Every
                  question on devnet costs 0.0001 SOL plus a zero-knowledge
                  compliance proof.
                </p>
                <WalletMultiButton />
              </>
            ) : (
              <p className="text-xs">
                Type your first question below and press &quot;Pay &amp;
                Ask&quot;.
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            {turns.map((turn) => (
              <TurnBubble key={turn.id} turn={turn} />
            ))}
          </div>
        )}
      </div>

      <div className="rounded-lg border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] p-3">
        <div className="mb-2 flex items-center justify-between gap-3">
          <label className="text-xs font-medium text-[color:var(--color-muted)]">
            Language
            <select
              className="ml-2 rounded border border-[color:var(--color-stone)] bg-white px-2 py-1 text-xs"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              disabled={sending}
            >
              <option value="en">EN</option>
              <option value="tr">TR</option>
              <option value="de">DE</option>
              <option value="fr">FR</option>
            </select>
          </label>
          <span className="text-xs text-[color:var(--color-muted)]">
            {wallet.publicKey
              ? `Wallet ${short(wallet.publicKey.toBase58())}`
              : "Wallet not connected"}
          </span>
        </div>
        <div className="flex gap-2">
          <textarea
            className="min-h-[72px] flex-1 rounded-md border border-[color:var(--color-stone)] bg-white p-2 text-sm focus:outline-none focus:ring-2 focus:ring-[color:var(--color-gold)]/40"
            placeholder="Ask an IP law question..."
            value={input}
            disabled={sending}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && canSend) {
                e.preventDefault();
                handleSend();
              }
            }}
          />
          <button
            type="button"
            onClick={handleSend}
            disabled={!canSend}
            className="min-w-[140px] rounded-md bg-[color:var(--color-bronze)] px-4 py-2 text-sm font-semibold text-[color:var(--color-cream)] transition-colors hover:bg-[color:var(--color-bronze-dark)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {sending ? "Processing..." : "Pay & Ask"}
          </button>
        </div>
      </div>

      <details className="rounded-lg border border-[color:var(--color-stone)] bg-[color:var(--color-linen)]">
        <summary className="cursor-pointer px-4 py-2 text-sm font-medium text-[color:var(--color-espresso)]">
          Paid chat history {historyLoading ? "· loading..." : `(${history.length})`}
        </summary>
        <div className="max-h-60 overflow-y-auto border-t border-[color:var(--color-stone)]">
          {history.length === 0 ? (
            <p className="p-3 text-xs text-[color:var(--color-muted)]">
              No prior paid queries.
            </p>
          ) : (
            <ul className="divide-y divide-[color:var(--color-stone)]/60">
              {history.map((h) => (
                <li key={h.id} className="px-4 py-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="truncate font-medium text-[color:var(--color-espresso)]">
                      {h.question}
                    </span>
                    <span className="shrink-0 text-[color:var(--color-muted)]">
                      {new Date(h.created_at).toLocaleString()}
                    </span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {h.payment_tx && (
                      <ExplorerChip
                        label="Payment"
                        href={`https://explorer.solana.com/tx/${h.payment_tx}?cluster=devnet`}
                        hash={h.payment_tx}
                      />
                    )}
                    {h.compliance_tx && (
                      <ExplorerChip
                        label="Compliance"
                        href={`https://explorer.solana.com/tx/${h.compliance_tx}?cluster=devnet`}
                        hash={h.compliance_tx}
                      />
                    )}
                    {h.compliance_pda && (
                      <ExplorerChip
                        label="PDA"
                        href={`https://explorer.solana.com/address/${h.compliance_pda}?cluster=devnet`}
                        hash={h.compliance_pda}
                      />
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </details>
    </div>
  );
}

function TurnBubble({ turn }: { turn: ChatTurn }) {
  return (
    <div className="space-y-2">
      <div className="ml-auto max-w-[85%] rounded-2xl bg-[color:var(--color-espresso)] px-4 py-2 text-sm text-[color:var(--color-cream)]">
        <p>{turn.question}</p>
        <p className="mt-1 text-right text-[10px] uppercase tracking-wider text-[color:var(--color-linen)]/50">
          {turn.language.toUpperCase()} · {turn.createdAt.toLocaleTimeString()}
        </p>
      </div>

      {turn.stage && turn.stage !== "done" && !turn.error ? (
        <div className="max-w-[85%] rounded-2xl border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] px-4 py-2 text-sm text-[color:var(--color-muted)]">
          <span className="inline-flex items-center gap-2">
            <span className="h-2 w-2 animate-pulse rounded-full bg-[color:var(--color-bronze)]" />
            {STAGE_LABELS[turn.stage]}…
          </span>
        </div>
      ) : null}

      {turn.answer ? (
        <div className="max-w-[85%] rounded-2xl border border-[color:var(--color-stone)] bg-white px-4 py-3 text-sm text-[color:var(--color-ink)] shadow-sm">
          <div className="leading-relaxed">{renderMarkdown(turn.answer)}</div>
          {turn.countryDetected ? (
            <p className="mt-2 text-xs text-[color:var(--color-muted)]">
              Country: <strong>{turn.countryDetected}</strong>
            </p>
          ) : null}
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[color:var(--color-stone)]/60 pt-3">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[color:var(--color-sand)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-bronze-dark)]">
              <span className="chain-dot" />
              {turn.fromCache
                ? "previously paid + verified"
                : "on-chain paid + verified"}
            </span>
            {turn.paymentExplorerUrl ? (
              <ExplorerChip
                label="Payment"
                href={turn.paymentExplorerUrl}
                hash={turn.paymentTx}
              />
            ) : null}
            {turn.complianceExplorerUrl ? (
              <ExplorerChip
                label="Compliance"
                href={turn.complianceExplorerUrl}
                hash={turn.complianceTx}
              />
            ) : null}
            {turn.complianceRecordExplorerUrl ? (
              <ExplorerChip
                label="PDA"
                href={turn.complianceRecordExplorerUrl}
                hash={turn.compliancePda}
              />
            ) : null}
          </div>
        </div>
      ) : null}

      {turn.error ? (
        <div className="max-w-[85%] rounded-2xl border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-700">
          {turn.error}
        </div>
      ) : null}
    </div>
  );
}

function ExplorerChip({
  label,
  href,
  hash,
}: {
  label: string;
  href: string;
  hash: string | null | undefined;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="group inline-flex items-center gap-1.5 rounded-full border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] px-2.5 py-1 text-[11px] text-[color:var(--color-espresso)] transition-colors hover:border-[color:var(--color-gold)] hover:bg-[color:var(--color-sand)]"
    >
      <span className="font-semibold tracking-wide">{label}</span>
      <span className="font-mono text-[color:var(--color-muted)] group-hover:text-[color:var(--color-bronze-dark)]">
        {short(hash ?? "", 4)}
      </span>
      <svg
        xmlns="http://www.w3.org/2000/svg"
        className="h-3 w-3 text-[color:var(--color-muted)] group-hover:text-[color:var(--color-bronze-dark)]"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2.5}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
        />
      </svg>
    </a>
  );
}
