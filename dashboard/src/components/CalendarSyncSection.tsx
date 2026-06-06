"use client";

import { useCallback, useEffect, useState } from "react";
import api, { extractErrorMessage } from "@/lib/api";

interface FeedStatus {
  enabled: boolean;
  url: string | null;
}

export default function CalendarSyncSection() {
  const [status, setStatus] = useState<FeedStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.get<FeedStatus>("/calendar/feed");
      setStatus(res.data);
    } catch (err) {
      setError(extractErrorMessage(err, "Could not load calendar settings."));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function enable() {
    setError(null);
    setBusy(true);
    try {
      const res = await api.post<FeedStatus>("/calendar/feed");
      setStatus(res.data);
    } catch (err) {
      setError(extractErrorMessage(err, "Could not enable the calendar feed."));
    } finally {
      setBusy(false);
    }
  }

  async function rotate() {
    setError(null);
    setBusy(true);
    try {
      const res = await api.post<FeedStatus>("/calendar/feed/rotate");
      setStatus(res.data);
      setCopied(false);
    } catch (err) {
      setError(extractErrorMessage(err, "Could not regenerate the link."));
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    setError(null);
    setBusy(true);
    try {
      await api.delete("/calendar/feed");
      setStatus({ enabled: false, url: null });
    } catch (err) {
      setError(extractErrorMessage(err, "Could not disable the calendar feed."));
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!status?.url) return;
    try {
      await navigator.clipboard.writeText(status.url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Could not copy. Select the link and copy it manually.");
    }
  }

  return (
    <section className="rounded-xl border border-[color:var(--color-stone)] bg-white p-6">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-[color:var(--color-ink)]">
            Calendar sync
          </h3>
          {status?.enabled ? (
            <span className="rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-semibold text-green-800">
              Enabled
            </span>
          ) : (
            <span className="rounded-full bg-[color:var(--color-sand)] px-2.5 py-0.5 text-xs font-semibold text-[color:var(--color-muted)]">
              Disabled
            </span>
          )}
        </div>

        <p className="text-sm text-[color:var(--color-muted)]">
          Subscribe to a private calendar feed so your IP case deadlines and
          renewal dates show up automatically in Google Calendar, Outlook, or
          Apple Calendar. The link is read-only and private to you.
        </p>

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800"
          >
            {error}
          </div>
        )}

        {status?.enabled && status.url ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <input
                readOnly
                value={status.url}
                onFocus={(e) => e.currentTarget.select()}
                className="rwa-input w-full font-mono text-xs"
                aria-label="Calendar feed URL"
              />
              <button
                type="button"
                onClick={copy}
                className="shrink-0 rounded-lg border border-[color:var(--color-stone)] px-3 py-2 text-sm font-semibold text-[color:var(--color-ink)] hover:bg-[color:var(--color-sand)]"
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>

            <details className="rounded-lg border border-[color:var(--color-stone)] bg-[color:var(--color-elevated)] p-3 text-sm text-[color:var(--color-ink)]">
              <summary className="cursor-pointer font-medium text-[color:var(--color-muted)]">
                How to subscribe
              </summary>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-[color:var(--color-muted)]">
                <li>
                  <strong>Google Calendar:</strong> Other calendars → From URL →
                  paste the link.
                </li>
                <li>
                  <strong>Outlook:</strong> Add calendar → Subscribe from web →
                  paste the link.
                </li>
                <li>
                  <strong>Apple Calendar:</strong> File → New Calendar
                  Subscription → paste the link.
                </li>
              </ul>
              <p className="mt-2 text-xs text-[color:var(--color-muted)]">
                Calendar apps refresh subscribed feeds periodically (often
                hourly), so new deadlines may take a little while to appear.
              </p>
            </details>

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={rotate}
                className="rounded-lg border border-[color:var(--color-stone)] px-4 py-2 text-sm font-semibold text-[color:var(--color-ink)] hover:bg-[color:var(--color-sand)] disabled:opacity-50"
              >
                {busy ? "Working…" : "Regenerate link"}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={disable}
                className="rounded-lg border border-red-300 px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                Disable
              </button>
            </div>
            <p className="text-xs text-[color:var(--color-muted)]">
              Regenerating revokes the old link; update your calendar
              subscription with the new one.
            </p>
          </div>
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={enable}
            className="rwa-btn-primary"
          >
            {busy ? "Enabling…" : "Enable calendar feed"}
          </button>
        )}
      </div>
    </section>
  );
}
