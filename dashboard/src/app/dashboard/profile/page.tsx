"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import api, { extractErrorMessage } from "@/lib/api";
import { env } from "@/lib/env";
import DataErasureSection from "@/components/DataErasureSection";
import TwoFactorSettings from "@/components/TwoFactorSettings";
import CalendarSyncSection from "@/components/CalendarSyncSection";

interface MeUser {
  id: string;
  email: string | null;
  full_name: string;
  role: "admin" | "client";
  phone: string | null;
  is_active: boolean;
  wallet_address: string | null;
  public_handle: string | null;
  auth_method: string;
  has_avatar?: boolean;
  avatar_mime?: string | null;
  notification_email: string | null;
  email_notifications_enabled: boolean;
}

interface NftBlock {
  state: "none" | "pending_claim" | "minted" | "burned";
  mint: string | null;
  setup_tx: string | null;
  mint_tx: string | null;
  burn_tx: string | null;
  burned_at: string | null;
}

interface LatestFiling {
  jurisdiction: string;
  submission_id: string;
  status: string;
  current_step: string | null;
  error_step: string | null;
  error_message: string | null;
  ipo_reference: string | null;
  ipo_application_url: string | null;
  mark_text: string | null;
  mark_type: string;
  owner_company_name: string;
  payment_tx: string | null;
  payment_lamports: number | null;
  payment_at: string | null;
  compliance_tx: string | null;
  compliance_pda: string | null;
  query_hash_hex: string | null;
  commitment_hex: string | null;
  started_at: string | null;
  finished_at: string | null;
}

interface TimelineItem {
  case_id: string;
  case_number: string;
  title: string;
  case_type: string;
  status: string;
  jurisdiction: string | null;
  nice_classes: string | null;
  created_at: string;
  updated_at: string;
  client_wallet: string | null;
  attestation_tx: string | null;
  attestation_pda: string | null;
  nft: NftBlock;
  latest_filing: LatestFiling | null;
}

interface TimelineResponse {
  user_id: string;
  count: number;
  items: TimelineItem[];
}

const explorerTx = (sig: string) =>
  `https://explorer.solana.com/tx/${sig}${env.explorerClusterSuffix}`;
const explorerAddr = (addr: string) =>
  `https://explorer.solana.com/address/${addr}${env.explorerClusterSuffix}`;

function shortHash(value: string | null | undefined, head = 8, tail = 6): string {
  if (!value) return "—";
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString();
}

export default function ProfilePage() {
  const [me, setMe] = useState<MeUser | null>(null);
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // edit state
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ full_name: "", email: "", phone: "" });
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  // Opt-in notification toggle — separate state so changes save
  // independently of the main profile fields (avoids forcing the user
  // into "edit mode" just to flip the toggle).
  const [notifEmail, setNotifEmail] = useState("");
  const [notifOptIn, setNotifOptIn] = useState(false);
  const [notifSaving, setNotifSaving] = useState(false);
  const [notifMessage, setNotifMessage] = useState<string | null>(null);

  // avatar
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // GDPR Article 20 data export
  const [dataExporting, setDataExporting] = useState(false);
  const [dataExportMessage, setDataExportMessage] = useState<string | null>(
    null
  );

  const refreshAvatar = useCallback(async (user: MeUser) => {
    if (!user.has_avatar) {
      setAvatarUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
      return;
    }
    try {
      const res = await api.get(`/users/${user.id}/avatar`, {
        responseType: "blob",
      });
      const blob = res.data as Blob;
      const url = URL.createObjectURL(blob);
      setAvatarUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return url;
      });
    } catch {
      setAvatarUrl(null);
    }
  }, []);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [meRes, timelineRes] = await Promise.all([
        api.get<MeUser>("/auth/me"),
        api.get<TimelineResponse>("/users/me/timeline"),
      ]);
      setMe(meRes.data);
      setItems(timelineRes.data.items);
      setForm({
        full_name: meRes.data.full_name ?? "",
        email: meRes.data.email ?? "",
        phone: meRes.data.phone ?? "",
      });
      setNotifEmail(meRes.data.notification_email ?? "");
      setNotifOptIn(meRes.data.email_notifications_enabled ?? false);
      await refreshAvatar(meRes.data);
    } catch (err) {
      setError(extractErrorMessage(err, "Could not load profile."));
    } finally {
      setLoading(false);
    }
  }, [refreshAvatar]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const handleSave = useCallback(async () => {
    if (!me) return;
    setSaving(true);
    setSaveMessage(null);
    try {
      const res = await api.patch<MeUser>(`/users/${me.id}`, {
        full_name: form.full_name || null,
        email: form.email || null,
        phone: form.phone || null,
      });
      setMe(res.data);
      setEditing(false);
      setSaveMessage("Profile updated.");
    } catch (err) {
      setSaveMessage(extractErrorMessage(err, "Could not update profile."));
    } finally {
      setSaving(false);
    }
  }, [me, form]);

  const handleAvatarPick = useCallback(() => {
    if (!avatarBusy) fileInputRef.current?.click();
  }, [avatarBusy]);

  const handleAvatarChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file) return;
      setAvatarBusy(true);
      setSaveMessage(null);
      try {
        const fd = new FormData();
        fd.append("file", file);
        const res = await api.post<MeUser>("/users/me/avatar", fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        setMe(res.data);
        await refreshAvatar(res.data);
      } catch (err) {
        setSaveMessage(extractErrorMessage(err, "Avatar upload failed."));
      } finally {
        setAvatarBusy(false);
      }
    },
    [refreshAvatar]
  );

  const handleAvatarDelete = useCallback(async () => {
    if (avatarBusy) return;
    setAvatarBusy(true);
    setSaveMessage(null);
    try {
      const res = await api.delete<MeUser>("/users/me/avatar");
      setMe(res.data);
      await refreshAvatar(res.data);
    } catch (err) {
      setSaveMessage(extractErrorMessage(err, "Could not remove avatar."));
    } finally {
      setAvatarBusy(false);
    }
  }, [avatarBusy, refreshAvatar]);

  const handleDataExport = useCallback(
    async (fmt: "json" | "pdf" | "docx" | "xlsx") => {
      if (!me || dataExporting) return;
      setDataExporting(true);
      setDataExportMessage(null);
      try {
        const res = await api.get("/users/me/export", {
          params: { format: fmt },
          responseType: "blob",
        });
        const blob = res.data as Blob;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `etornie-data-export-${me.id}.${fmt}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        setDataExportMessage("Your data export downloaded.");
      } catch (err) {
        setDataExportMessage(extractErrorMessage(err, "Data export failed."));
      } finally {
        setDataExporting(false);
      }
    },
    [me, dataExporting]
  );

  const handleExport = useCallback(
    async (caseId: string, fmt: "pdf" | "docx" | "xlsx") => {
      try {
        const res = await api.get(`/cases/${caseId}/export`, {
          params: { format: fmt },
          responseType: "blob",
        });
        const blob = res.data as Blob;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `etornie-case-${caseId}.${fmt}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } catch (err) {
        setError(extractErrorMessage(err, "Export failed."));
      }
    },
    []
  );

  if (loading) {
    return (
      <div className="p-6 text-sm text-[color:var(--color-muted)]">
        Loading profile…
      </div>
    );
  }

  if (error && !me) {
    return <div className="p-6 text-sm text-red-700">{error}</div>;
  }

  if (!me) return null;

  const initials = (me.full_name || me.email || "?")
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <div className="space-y-6 p-6">
      {/* Profile card */}
      <section className="rounded-xl border border-[color:var(--color-stone)] bg-white p-6">
        <input
          ref={fileInputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          className="hidden"
          onChange={handleAvatarChange}
        />
        <div className="flex items-start gap-4">
          <div className="flex flex-col items-center gap-1">
            <button
              type="button"
              onClick={handleAvatarPick}
              disabled={avatarBusy}
              title={avatarUrl ? "Change avatar" : "Upload avatar"}
              className="relative flex h-20 w-20 items-center justify-center overflow-hidden rounded-full bg-[color:var(--color-bronze)] text-2xl font-semibold text-[color:var(--color-cream)] hover:opacity-90 disabled:opacity-60"
            >
              {avatarUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={avatarUrl}
                  alt="avatar"
                  className="h-full w-full object-cover"
                />
              ) : (
                initials
              )}
              <span className="absolute inset-x-0 bottom-0 bg-black/40 py-0.5 text-center text-[10px] font-normal uppercase tracking-wider text-white">
                {avatarBusy ? "…" : "Edit"}
              </span>
            </button>
            {avatarUrl && (
              <button
                type="button"
                onClick={handleAvatarDelete}
                disabled={avatarBusy}
                className="text-[10px] uppercase tracking-wider text-[color:var(--color-muted)] hover:text-red-700"
              >
                Remove
              </button>
            )}
          </div>
          <div className="flex-1">
            {!editing ? (
              <>
                <h1 className="text-xl font-semibold text-[color:var(--color-ink)]">
                  {me.full_name || "(unnamed)"}
                </h1>
                <p className="text-sm text-[color:var(--color-muted)]">
                  {me.email ?? "no email"} · role{" "}
                  <span className="font-medium uppercase">{me.role}</span>
                  {me.public_handle && <> · @{me.public_handle}</>}
                </p>
              </>
            ) : (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                <label className="text-sm">
                  <span className="block text-xs text-[color:var(--color-muted)]">
                    Full name
                  </span>
                  <input
                    value={form.full_name}
                    onChange={(e) =>
                      setForm({ ...form, full_name: e.target.value })
                    }
                    className="mt-1 w-full rounded-md border border-[color:var(--color-stone)] px-2 py-1 text-sm"
                  />
                </label>
                <label className="text-sm">
                  <span className="block text-xs text-[color:var(--color-muted)]">
                    Email
                  </span>
                  <input
                    value={form.email}
                    onChange={(e) =>
                      setForm({ ...form, email: e.target.value })
                    }
                    className="mt-1 w-full rounded-md border border-[color:var(--color-stone)] px-2 py-1 text-sm"
                    type="email"
                  />
                </label>
                <label className="text-sm">
                  <span className="block text-xs text-[color:var(--color-muted)]">
                    Phone
                  </span>
                  <input
                    value={form.phone}
                    onChange={(e) =>
                      setForm({ ...form, phone: e.target.value })
                    }
                    className="mt-1 w-full rounded-md border border-[color:var(--color-stone)] px-2 py-1 text-sm"
                  />
                </label>
              </div>
            )}
          </div>
          <div className="flex gap-2">
            {!editing ? (
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="rounded-md border border-[color:var(--color-stone)] bg-white px-3 py-1.5 text-xs hover:bg-[color:var(--color-sand)]"
              >
                Edit
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saving}
                  className="rounded-md bg-[color:var(--color-bronze)] px-3 py-1.5 text-xs font-semibold text-[color:var(--color-cream)] hover:bg-[color:var(--color-bronze-dark)] disabled:bg-[color:var(--color-stone)]"
                >
                  {saving ? "Saving…" : "Save"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditing(false);
                    setForm({
                      full_name: me.full_name ?? "",
                      email: me.email ?? "",
                      phone: me.phone ?? "",
                    });
                  }}
                  className="rounded-md border border-[color:var(--color-stone)] bg-white px-3 py-1.5 text-xs hover:bg-[color:var(--color-sand)]"
                >
                  Cancel
                </button>
              </>
            )}
          </div>
        </div>
        {saveMessage && (
          <p className="mt-3 text-xs text-[color:var(--color-muted)]">{saveMessage}</p>
        )}

        {/* Wallet block */}
        <div className="mt-5 grid grid-cols-1 gap-4 border-t border-[color:var(--color-stone)] pt-5 md:grid-cols-2">
          <div>
            <p className="text-xs uppercase tracking-wider text-[color:var(--color-muted)]">
              Wallet
            </p>
            <p className="mt-1 font-mono text-xs">
              {me.wallet_address ? (
                <a
                  href={explorerAddr(me.wallet_address)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[color:var(--color-bronze)] underline break-all"
                  title={me.wallet_address}
                >
                  {me.wallet_address}
                </a>
              ) : (
                "Not connected"
              )}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wider text-[color:var(--color-muted)]">
              Auth method
            </p>
            <p className="mt-1 text-sm">{me.auth_method}</p>
          </div>
        </div>

        {/* Notification settings block */}
        <div className="mt-5 border-t border-[color:var(--color-stone)] pt-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-wider text-[color:var(--color-muted)]">
                Email notifications
              </p>
              <p className="mt-1 text-xs text-[color:var(--color-muted)]">
                Opt in to receive Stripe receipts, EUIPO submission
                updates, refund confirmations, and NFT-ready alerts.
                Off by default for privacy — toggle on whenever you
                want to start receiving email.
              </p>
            </div>
            <label className="relative inline-flex cursor-pointer items-center">
              <input
                type="checkbox"
                className="peer sr-only"
                checked={notifOptIn}
                onChange={(e) => setNotifOptIn(e.target.checked)}
              />
              <div className="h-6 w-11 rounded-full bg-[color:var(--color-stone)] peer-checked:bg-[color:var(--color-bronze)] peer-focus:ring-2 peer-focus:ring-[color:var(--color-bronze)]/30 transition-colors">
                <div className="h-5 w-5 translate-x-0.5 translate-y-0.5 rounded-full bg-white shadow transition-transform peer-checked:translate-x-[22px]" />
              </div>
            </label>
          </div>
          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-[1fr_auto]">
            <input
              type="email"
              value={notifEmail}
              onChange={(e) => setNotifEmail(e.target.value)}
              placeholder={
                me.email ?? "you@example.com — required for wallet-only accounts"
              }
              disabled={!notifOptIn || notifSaving}
              className="w-full rounded-md border border-[color:var(--color-stone)] bg-white px-3 py-2 text-sm disabled:opacity-50"
            />
            <button
              type="button"
              onClick={async () => {
                if (!me) return;
                setNotifSaving(true);
                setNotifMessage(null);
                try {
                  const res = await api.patch<MeUser>(`/users/${me.id}`, {
                    notification_email: notifEmail || null,
                    email_notifications_enabled: notifOptIn,
                  });
                  setMe(res.data);
                  setNotifMessage("Notification preferences saved.");
                } catch (err) {
                  setNotifMessage(
                    extractErrorMessage(
                      err,
                      "Could not save notification preferences.",
                    ),
                  );
                } finally {
                  setNotifSaving(false);
                }
              }}
              disabled={notifSaving}
              className="rounded-md bg-[color:var(--color-bronze)] px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              {notifSaving ? "Saving…" : "Save"}
            </button>
          </div>
          {notifMessage && (
            <p className="mt-2 text-xs text-[color:var(--color-muted)]">
              {notifMessage}
            </p>
          )}
        </div>

        {/* Data export block (GDPR Article 20 — right to data portability) */}
        <div className="mt-5 border-t border-[color:var(--color-stone)] pt-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-wider text-[color:var(--color-muted)]">
                Your data
              </p>
              <p className="mt-1 text-xs text-[color:var(--color-muted)]">
                Download a complete, machine-readable copy of all personal
                data we hold about you — profile, cases, documents, chat
                history, payments, and notifications — as a single JSON file.
                This is your GDPR Article 20 right to data portability.
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              {(
                [
                  ["json", "JSON"],
                  ["pdf", "PDF"],
                  ["docx", "Word"],
                  ["xlsx", "Excel"],
                ] as const
              ).map(([fmt, label]) => (
                <button
                  key={fmt}
                  type="button"
                  onClick={() => handleDataExport(fmt)}
                  disabled={dataExporting}
                  className="rounded-md border border-[color:var(--color-stone)] bg-white px-3 py-2 text-sm font-semibold text-[color:var(--color-ink)] hover:bg-[color:var(--color-sand)] disabled:opacity-50"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          {dataExportMessage && (
            <p className="mt-2 text-xs text-[color:var(--color-muted)]">
              {dataExportMessage}
            </p>
          )}
        </div>
      </section>

      {/* Two-factor authentication */}
      <TwoFactorSettings onChanged={fetchAll} />
      {/* Calendar (ICS) subscription feed */}
      <CalendarSyncSection />

      {/* Filings timeline */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[color:var(--color-ink)]">
            Filings &amp; Cases
          </h2>
          <span className="text-xs text-[color:var(--color-muted)]">
            {items.length} item{items.length === 1 ? "" : "s"}
          </span>
        </div>

        {error && <p className="mb-3 text-xs text-red-700">{error}</p>}

        {items.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[color:var(--color-stone)] bg-white p-6 text-center text-sm text-[color:var(--color-muted)]">
            No filings yet. Start one in EtornieGPT.
          </div>
        ) : (
          <ul className="space-y-3">
            {items.map((item) => (
              <li
                key={item.case_id}
                className="rounded-xl border border-[color:var(--color-stone)] bg-white p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-wider text-[color:var(--color-muted)]">
                      {item.jurisdiction || "—"} · {item.case_type}
                    </p>
                    <h3 className="text-base font-semibold text-[color:var(--color-ink)]">
                      {item.case_number} — {item.title}
                    </h3>
                    <p className="mt-0.5 text-xs text-[color:var(--color-muted)]">
                      Created {fmtDate(item.created_at)} · status{" "}
                      <span className="font-medium">{item.status}</span>
                      {item.nice_classes && <> · classes {item.nice_classes}</>}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => handleExport(item.case_id, "pdf")}
                      className="rounded-md border border-[color:var(--color-stone)] bg-white px-2 py-1 text-xs hover:bg-[color:var(--color-sand)]"
                    >
                      PDF
                    </button>
                    <button
                      type="button"
                      onClick={() => handleExport(item.case_id, "docx")}
                      className="rounded-md border border-[color:var(--color-stone)] bg-white px-2 py-1 text-xs hover:bg-[color:var(--color-sand)]"
                    >
                      Word
                    </button>
                    <button
                      type="button"
                      onClick={() => handleExport(item.case_id, "xlsx")}
                      className="rounded-md border border-[color:var(--color-stone)] bg-white px-2 py-1 text-xs hover:bg-[color:var(--color-sand)]"
                    >
                      Excel
                    </button>
                  </div>
                </div>

                {/* On-chain trail */}
                <div className="mt-3 grid grid-cols-1 gap-x-4 gap-y-1 font-mono text-[11px] leading-tight text-[color:var(--color-muted)] md:grid-cols-2">
                  {item.attestation_tx && (
                    <Row
                      label="attest tx"
                      href={explorerTx(item.attestation_tx)}
                      value={item.attestation_tx}
                    />
                  )}
                  {item.attestation_pda && (
                    <Row
                      label="attest pda"
                      href={explorerAddr(item.attestation_pda)}
                      value={item.attestation_pda}
                    />
                  )}
                  {item.nft.mint && (
                    <Row
                      label={`nft (${item.nft.state})`}
                      href={explorerAddr(item.nft.mint)}
                      value={item.nft.mint}
                    />
                  )}
                  {item.nft.mint_tx && (
                    <Row
                      label="mint tx"
                      href={explorerTx(item.nft.mint_tx)}
                      value={item.nft.mint_tx}
                    />
                  )}
                  {item.nft.burn_tx && (
                    <Row
                      label="burn tx"
                      href={explorerTx(item.nft.burn_tx)}
                      value={item.nft.burn_tx}
                    />
                  )}
                </div>

                {/* Latest filing block */}
                {item.latest_filing && (
                  <div className="mt-3 rounded-lg border border-[color:var(--color-stone)] bg-[color:var(--color-sand)]/40 px-3 py-2 text-xs">
                    <div className="flex flex-wrap items-baseline justify-between gap-3">
                      <span className="font-semibold uppercase tracking-wider text-[color:var(--color-espresso)]">
                        {item.latest_filing.jurisdiction} ·{" "}
                        {item.latest_filing.status}
                      </span>
                      {item.latest_filing.ipo_application_url && (
                        <a
                          href={item.latest_filing.ipo_application_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[color:var(--color-bronze)] underline"
                        >
                          IPO application page
                        </a>
                      )}
                    </div>
                    <p className="mt-0.5 text-[color:var(--color-muted)]">
                      Mark: {item.latest_filing.mark_text || "—"} · Owner:{" "}
                      {item.latest_filing.owner_company_name}
                      {item.latest_filing.ipo_reference && (
                        <> · ref {item.latest_filing.ipo_reference}</>
                      )}
                    </p>
                    <div className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 font-mono text-[11px] leading-tight md:grid-cols-2">
                      {item.latest_filing.payment_tx && (
                        <Row
                          label="payment tx"
                          href={explorerTx(item.latest_filing.payment_tx)}
                          value={item.latest_filing.payment_tx}
                        />
                      )}
                      {item.latest_filing.compliance_tx && (
                        <Row
                          label="compliance tx"
                          href={explorerTx(item.latest_filing.compliance_tx)}
                          value={item.latest_filing.compliance_tx}
                        />
                      )}
                      {item.latest_filing.compliance_pda && (
                        <Row
                          label="compliance pda"
                          href={explorerAddr(item.latest_filing.compliance_pda)}
                          value={item.latest_filing.compliance_pda}
                        />
                      )}
                      {item.latest_filing.query_hash_hex && (
                        <PlainRow
                          label="query hash"
                          value={item.latest_filing.query_hash_hex}
                        />
                      )}
                      {item.latest_filing.commitment_hex && (
                        <PlainRow
                          label="commitment"
                          value={item.latest_filing.commitment_hex}
                        />
                      )}
                      {item.latest_filing.error_message && (
                        <p className="col-span-full text-red-700">
                          {item.latest_filing.error_step
                            ? `${item.latest_filing.error_step}: `
                            : ""}
                          {item.latest_filing.error_message}
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Right to erasure (GDPR Article 17) — danger zone, kept last */}
      <DataErasureSection authMethod={me.auth_method} />
    </div>
  );
}

function Row({
  label,
  href,
  value,
}: {
  label: string;
  href: string;
  value: string;
}) {
  return (
    <div className="flex gap-2">
      <span className="w-28 shrink-0 text-[10px] uppercase tracking-wider">
        {label}
      </span>
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="break-all text-[color:var(--color-bronze)] underline"
        title={value}
      >
        {shortHash(value)}
      </a>
    </div>
  );
}

function PlainRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <span className="w-28 shrink-0 text-[10px] uppercase tracking-wider">
        {label}
      </span>
      <span className="break-all" title={value}>
        {shortHash(value)}
      </span>
    </div>
  );
}
