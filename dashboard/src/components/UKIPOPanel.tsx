"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useWallet } from "@solana/wallet-adapter-react";
import {
  Connection,
  PublicKey,
  SystemProgram,
  TransactionInstruction,
  TransactionMessage,
  VersionedTransaction,
} from "@solana/web3.js";
import api from "@/lib/api";

const SOLANA_CLUSTER_URL =
  process.env.NEXT_PUBLIC_SOLANA_CLUSTER_URL ?? "https://api.devnet.solana.com";

const MEMO_PROGRAM_ID = new PublicKey(
  "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
);

type MarkType = "word" | "figurative" | "combined" | "unusual";

type EntityType =
  | ""
  | "Registered Company or LLP"
  | "Individual(s)"
  | "Partnership"
  | "Trust"
  | "Other";

const ENTITY_TYPES: Exclude<EntityType, "">[] = [
  "Registered Company or LLP",
  "Individual(s)",
  "Partnership",
  "Trust",
  "Other",
];

type SubmissionStatus =
  | "pending"
  | "running"
  | "awaiting_payment"
  | "filed"
  | "failed";

interface NiceClassEntry {
  class_number: number;
  description: string;
}

interface BraidConflictDecision {
  id: string;
  capability_name: string;
  user_message: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
  started_at: string;
}

interface UKIPOSubmission {
  id: string;
  case_id: string;
  owner_company_name: string;
  owner_country: string;
  owner_address_line1: string;
  owner_address_line2: string | null;
  owner_city: string;
  owner_postcode: string | null;
  owner_email: string | null;
  owner_phone: string | null;
  owner_entity_type: EntityType;
  owner_company_registration_number: string | null;
  mark_type: MarkType;
  mark_text: string | null;
  mark_image_path: string | null;
  nice_classes_json: string;
  status: SubmissionStatus;
  current_step: string | null;
  error_step: string | null;
  error_message: string | null;
  ipo_reference: string | null;
  ipo_application_url: string | null;
  screenshot_path: string | null;
  solana_payment_tx: string | null;
  solana_payer_wallet: string | null;
  solana_payment_lamports: number | null;
  solana_payment_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

interface PaymentRequirements {
  network: string;
  asset: string;
  recipient: string;
  lamports: number;
  memo: string;
  cluster_url: string;
}

const STEP_LABELS: Record<string, string> = {
  open_form: "Forma giriş",
  choose_representative_role: "Temsilci rolü seçiliyor",
  fill_representative_details: "Temsilci bilgileri dolduruluyor",
  fill_owner_details: "Sahip bilgileri dolduruluyor",
  choose_mark_type: "Marka tipi seçiliyor",
  single_trade_mark: "Tek marka onayı",
  select_class_manually: "Nice sınıfı seçimi",
  enter_nice_classes: "Mal/hizmet açıklamaları giriliyor",
  confirm_bottom_option: "Bona-fide beyanı onaylanıyor",
  answer_no_questions: "Disclaimer / EU / öncelik soruları",
  choose_standard_mark: "Standart marka tipi",
  choose_examination_type: "İnceleme tipi seçiliyor",
  declaration: "Beyan & ödeme ekranı",
};

const STATUS_BADGE: Record<SubmissionStatus, string> = {
  pending: "bg-gray-100 text-gray-700 border-gray-200",
  running: "bg-blue-100 text-blue-700 border-blue-200",
  awaiting_payment: "bg-yellow-100 text-yellow-800 border-yellow-200",
  filed: "bg-green-100 text-green-700 border-green-200",
  failed: "bg-red-100 text-red-700 border-red-200",
};

const STATUS_LABEL: Record<SubmissionStatus, string> = {
  pending: "Beklemede",
  running: "Çalışıyor",
  awaiting_payment: "Ödeme bekleniyor",
  filed: "Dosyalandı",
  failed: "Hata",
};

interface UKIPOPanelProps {
  caseId: string;
  caseTitle: string;
  caseNiceClasses: string | null;
  caseJurisdiction: string | null;
  caseClientId: string | null;
  guestClientName: string | null;
  guestClientEmail: string | null;
  guestClientPhone: string | null;
  canManage: boolean;
}

interface ApplicantSeed {
  name: string;
  email: string;
  phone: string;
}

interface UserResponse {
  id: string;
  full_name: string;
  email: string | null;
  phone: string | null;
}

interface FormState {
  mark_type: MarkType;
  mark_text: string;
  mark_image_path: string;
  owner: {
    company_name: string;
    country: string;
    address_line1: string;
    address_line2: string;
    city: string;
    postcode: string;
    email: string;
    phone: string;
    entity_type: EntityType;
    company_registration_number: string;
  };
  classes: { class_number: number; description: string }[];
}

const UK_VALUES = new Set([
  "united kingdom",
  "uk",
  "gb",
  "great britain",
  "england",
  "scotland",
  "wales",
  "northern ireland",
]);

function isUK(country: string): boolean {
  return UK_VALUES.has(country.trim().toLowerCase());
}

/**
 * Build the initial form state from real case/client data.
 *
 * No hardcoded sample values — every pre-filled field traces back to a
 * known source:
 *   - mark_text:    case.title (the case the operator already named)
 *   - country:      case.jurisdiction (set when the case was filed)
 *   - applicant:    registered client user OR guest_client_* fields
 *   - nice_classes: case.nice_classes if present
 *
 * If a source is missing the field stays empty and the user types it.
 * mark_type defaults to "word" because radios require an initial
 * selection — it's the most common UK IPO mark type, not a sample
 * value that ends up in the DB.
 */
function buildInitialForm(opts: {
  caseTitle: string;
  caseNiceClasses: string | null;
  caseJurisdiction: string | null;
  applicant: ApplicantSeed | null;
}): FormState {
  const classes =
    opts.caseNiceClasses
      ?.split(",")
      .map((c) => c.trim())
      .filter(Boolean)
      .map((n) => ({ class_number: Number(n), description: "" }))
      .filter(
        (c) => Number.isFinite(c.class_number) && c.class_number > 0,
      ) ?? [];
  return {
    mark_type: "word",
    mark_text: opts.caseTitle,
    mark_image_path: "",
    owner: {
      company_name: opts.applicant?.name ?? "",
      country: opts.caseJurisdiction ?? "",
      address_line1: "",
      address_line2: "",
      city: "",
      postcode: "",
      email: opts.applicant?.email ?? "",
      phone: opts.applicant?.phone ?? "",
      entity_type: "",
      company_registration_number: "",
    },
    classes:
      classes.length > 0
        ? classes
        : [{ class_number: 0, description: "" }],
  };
}

export function UKIPOPanel({
  caseId,
  caseTitle,
  caseNiceClasses,
  caseJurisdiction,
  caseClientId,
  guestClientName,
  guestClientEmail,
  guestClientPhone,
  canManage,
}: UKIPOPanelProps) {
  // Guest fields are already on the case row; the registered-user
  // profile (full_name/email/phone) needs an extra fetch and only
  // happens when the operator actually opens the form.
  const guestSeed: ApplicantSeed | null = useMemo(() => {
    if (guestClientName || guestClientEmail || guestClientPhone) {
      return {
        name: guestClientName ?? "",
        email: guestClientEmail ?? "",
        phone: guestClientPhone ?? "",
      };
    }
    return null;
  }, [guestClientName, guestClientEmail, guestClientPhone]);

  const [submissions, setSubmissions] = useState<UKIPOSubmission[]>([]);
  const [braidConflictsBySubmission, setBraidConflictsBySubmission] = useState<
    Record<string, BraidConflictDecision>
  >({});
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [applicantSeed, setApplicantSeed] = useState<ApplicantSeed | null>(
    guestSeed,
  );
  const [seedingApplicant, setSeedingApplicant] = useState(false);
  const [form, setForm] = useState<FormState>(() =>
    buildInitialForm({
      caseTitle,
      caseNiceClasses,
      caseJurisdiction,
      applicant: guestSeed,
    }),
  );
  const [formError, setFormError] = useState("");
  const [formLoading, setFormLoading] = useState(false);
  const [actionError, setActionError] = useState("");
  const [actionSuccess, setActionSuccess] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [imageUploading, setImageUploading] = useState(false);

  const wallet = useWallet();

  async function openForm() {
    setShowForm(true);
    setFormError("");
    if (applicantSeed === null && caseClientId) {
      setSeedingApplicant(true);
      try {
        const res = await api.get<UserResponse>(`/users/${caseClientId}`);
        const seed: ApplicantSeed = {
          name: res.data.full_name ?? "",
          email: res.data.email ?? "",
          phone: res.data.phone ?? "",
        };
        setApplicantSeed(seed);
        setForm(
          buildInitialForm({
            caseTitle,
            caseNiceClasses,
            caseJurisdiction,
            applicant: seed,
          }),
        );
      } catch {
        // No client profile reachable — keep the form empty rather than
        // pasting in a guess. The operator just types it manually.
      } finally {
        setSeedingApplicant(false);
      }
    }
  }

  const fetchSubmissions = useCallback(async () => {
    try {
      const res = await api.get<{ submissions: UKIPOSubmission[]; total: number }>(
        `/ukipo/cases/${caseId}/submissions`,
      );
      setSubmissions(res.data.submissions);
    } catch {
      // silently fail — table just stays empty
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  const fetchBraidConflicts = useCallback(async () => {
    try {
      const res = await api.get<{
        items: BraidConflictDecision[];
        count: number;
      }>(
        `/admin/braid/cases/${caseId}/decisions`,
        { params: { capability_name: "check_trademark_conflict" } },
      );
      // Index by `submission:<id>` token so the row only renders the
      // BRAID outcome that was tagged for that exact submission.
      const indexed: Record<string, BraidConflictDecision> = {};
      for (const d of res.data.items) {
        const token = (d.user_message ?? "")
          .split(/\s+/)
          .find((s) => s.startsWith("submission:"));
        if (!token) continue;
        const subId = token.slice("submission:".length);
        if (!indexed[subId]) indexed[subId] = d;
      }
      setBraidConflictsBySubmission(indexed);
    } catch {
      // 403 / disabled BRAID → silently no chips. Don't surface as error.
    }
  }, [caseId]);

  useEffect(() => {
    fetchSubmissions();
    fetchBraidConflicts();
  }, [fetchSubmissions, fetchBraidConflicts]);

  const hasActiveRun = useMemo(
    () => submissions.some((s) => s.status === "pending" || s.status === "running"),
    [submissions],
  );

  // Live polling while a robot is in flight. 3s strikes a balance
  // between snappy step updates and not hammering the server. Stops
  // automatically when no submission is pending/running.
  const pollRef = useRef<NodeJS.Timeout | null>(null);
  useEffect(() => {
    if (!hasActiveRun) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    pollRef.current = setInterval(() => {
      fetchSubmissions();
    }, 3000);
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [hasActiveRun, fetchSubmissions]);

  function setOwner<K extends keyof FormState["owner"]>(
    key: K,
    value: FormState["owner"][K],
  ) {
    setForm((f) => ({ ...f, owner: { ...f.owner, [key]: value } }));
  }

  function updateClass(idx: number, patch: Partial<NiceClassEntry>) {
    setForm((f) => ({
      ...f,
      classes: f.classes.map((c, i) => (i === idx ? { ...c, ...patch } : c)),
    }));
  }

  function addClass() {
    setForm((f) => ({
      ...f,
      classes: [...f.classes, { class_number: 0, description: "" }],
    }));
  }

  function removeClass(idx: number) {
    setForm((f) => ({
      ...f,
      classes: f.classes.filter((_, i) => i !== idx),
    }));
  }

  async function handleImageUpload(file: File) {
    setImageUploading(true);
    setFormError("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.post<{ path: string }>(
        `/ukipo/cases/${caseId}/mark-image`,
        fd,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      setForm((f) => ({ ...f, mark_image_path: res.data.path }));
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Görsel yüklenemedi.";
      setFormError(message);
    } finally {
      setImageUploading(false);
    }
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setFormError("");
    if (form.owner.entity_type === "") {
      setFormError("Sahip tipi seçin.");
      return;
    }
    if (form.classes.some((c) => !c.class_number || c.class_number < 1 || c.class_number > 45)) {
      setFormError("Her Nice sınıfı için 1-45 arası bir numara girin.");
      return;
    }
    setFormLoading(true);
    try {
      const payload = {
        case_id: caseId,
        owner: {
          company_name: form.owner.company_name,
          country: form.owner.country,
          address_line1: form.owner.address_line1,
          address_line2: form.owner.address_line2 || null,
          city: form.owner.city,
          postcode: form.owner.postcode || null,
          email: form.owner.email || null,
          phone: form.owner.phone || null,
          entity_type: form.owner.entity_type,
          company_registration_number:
            form.owner.company_registration_number || null,
        },
        mark_type: form.mark_type,
        mark_text:
          form.mark_type === "word" || form.mark_type === "combined"
            ? form.mark_text
            : null,
        mark_image_path:
          form.mark_type !== "word" ? form.mark_image_path || null : null,
        nice_classes: form.classes,
      };
      await api.post<UKIPOSubmission>("/ukipo/submissions", payload);
      setShowForm(false);
      setForm(
        buildInitialForm({
          caseTitle,
          caseNiceClasses,
          caseJurisdiction,
          applicant: applicantSeed,
        }),
      );
      await fetchSubmissions();
      setActionSuccess("Başvuru oluşturuldu. 'Robotu Başlat' butonuna basın.");
      setTimeout(() => setActionSuccess(""), 4000);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail;
      setFormError(
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
          ? detail.map((d: { msg?: string }) => d.msg ?? "").join("; ")
          : "Başvuru oluşturulamadı.",
      );
    } finally {
      setFormLoading(false);
    }
  }

  async function handleStartRun(submissionId: string) {
    setBusyId(submissionId);
    setActionError("");
    setActionSuccess("");
    try {
      await api.post(`/ukipo/submissions/${submissionId}/run`);
      setActionSuccess(
        "Robot arka planda başlatıldı — sayfayı kapatabilirsiniz, ilerleme burada güncellenecek.",
      );
      setTimeout(() => setActionSuccess(""), 5000);
      await fetchSubmissions();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? "Robot başlatılamadı.";
      setActionError(detail);
    } finally {
      setBusyId(null);
    }
  }

  async function handlePay(submission: UKIPOSubmission) {
    if (!wallet.publicKey || !wallet.sendTransaction) {
      setActionError("Phantom/Solflare cüzdanını bağlayın.");
      return;
    }
    setBusyId(submission.id);
    setActionError("");
    setActionSuccess("");
    try {
      const reqRes = await api.get<PaymentRequirements>(
        `/ukipo/submissions/${submission.id}/payment-requirements`,
      );
      const requirements = reqRes.data;
      const connection = new Connection(SOLANA_CLUSTER_URL, "confirmed");
      const recipient = new PublicKey(requirements.recipient);
      const transferIx = SystemProgram.transfer({
        fromPubkey: wallet.publicKey,
        toPubkey: recipient,
        lamports: requirements.lamports,
      });
      const memoIx = new TransactionInstruction({
        programId: MEMO_PROGRAM_ID,
        keys: [],
        data: Buffer.from(new TextEncoder().encode(requirements.memo)),
      });
      const { blockhash } = await connection.getLatestBlockhash("confirmed");
      const message = new TransactionMessage({
        payerKey: wallet.publicKey,
        recentBlockhash: blockhash,
        instructions: [transferIx, memoIx],
      }).compileToV0Message();
      const tx = new VersionedTransaction(message);
      const signature = await wallet.sendTransaction(tx, connection, {
        skipPreflight: false,
        maxRetries: 3,
      });
      const latest = await connection.getLatestBlockhash("confirmed");
      await connection.confirmTransaction(
        {
          signature,
          blockhash: latest.blockhash,
          lastValidBlockHeight: latest.lastValidBlockHeight,
        },
        "confirmed",
      );
      await api.post(`/ukipo/submissions/${submission.id}/payment`, {
        payment_tx: signature,
        payer_wallet: wallet.publicKey.toBase58(),
      });
      setActionSuccess(`Ödeme onaylandı (${signature.slice(0, 12)}…).`);
      setTimeout(() => setActionSuccess(""), 6000);
      await fetchSubmissions();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? (err instanceof Error ? err.message : "Ödeme başarısız oldu.");
      setActionError(detail);
    } finally {
      setBusyId(null);
    }
  }

  if (!canManage) {
    return null;
  }

  return (
    <div className="mb-6 rounded-lg bg-white p-6 shadow-sm border border-gray-200">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-gray-700">UK IPO Filing</h2>
          <span className="inline-flex items-center rounded-full bg-purple-100 text-purple-800 px-2.5 py-0.5 text-xs font-medium border border-purple-200">
            UK Trademark
          </span>
        </div>
        {!showForm && (
          <button
            type="button"
            onClick={openForm}
            disabled={seedingApplicant}
            className="rounded bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          >
            {seedingApplicant ? "Yükleniyor…" : "Yeni Başvuru"}
          </button>
        )}
      </div>

      {actionSuccess && (
        <div className="mb-3 rounded bg-green-50 p-3 text-sm text-green-700 border border-green-200">
          {actionSuccess}
        </div>
      )}
      {actionError && (
        <div className="mb-3 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
          {actionError}
        </div>
      )}

      {showForm && (
        <UKIPOSubmissionForm
          form={form}
          setForm={setForm}
          setOwner={setOwner}
          updateClass={updateClass}
          addClass={addClass}
          removeClass={removeClass}
          onSubmit={handleCreate}
          onCancel={() => setShowForm(false)}
          onImageUpload={handleImageUpload}
          imageUploading={imageUploading}
          loading={formLoading}
          error={formError}
        />
      )}

      {!showForm && (
        <UKIPOSubmissionList
          submissions={submissions}
          braidConflictsBySubmission={braidConflictsBySubmission}
          loading={loading}
          busyId={busyId}
          onStart={handleStartRun}
          onPay={handlePay}
          walletConnected={wallet.connected}
        />
      )}
    </div>
  );
}

interface FormProps {
  form: FormState;
  setForm: React.Dispatch<React.SetStateAction<FormState>>;
  setOwner: <K extends keyof FormState["owner"]>(
    key: K,
    value: FormState["owner"][K],
  ) => void;
  updateClass: (idx: number, patch: Partial<NiceClassEntry>) => void;
  addClass: () => void;
  removeClass: (idx: number) => void;
  onSubmit: (e: FormEvent) => Promise<void>;
  onCancel: () => void;
  onImageUpload: (file: File) => Promise<void>;
  imageUploading: boolean;
  loading: boolean;
  error: string;
}

function UKIPOSubmissionForm({
  form,
  setForm,
  setOwner,
  updateClass,
  addClass,
  removeClass,
  onSubmit,
  onCancel,
  onImageUpload,
  imageUploading,
  loading,
  error,
}: FormProps) {
  const ownerIsUK = isUK(form.owner.country);
  const needsCompanyReg =
    form.owner.entity_type === "Registered Company or LLP" && ownerIsUK;
  const needsMarkText = form.mark_type === "word" || form.mark_type === "combined";
  const needsMarkImage = form.mark_type !== "word";

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      {error && (
        <div className="rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
          {error}
        </div>
      )}

      {/* Mark */}
      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold text-gray-700">Marka</legend>
        <div className="flex flex-wrap gap-3">
          {(["word", "figurative", "combined", "unusual"] as MarkType[]).map(
            (mt) => (
              <label key={mt} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="mark_type"
                  checked={form.mark_type === mt}
                  onChange={() => setForm((f) => ({ ...f, mark_type: mt }))}
                />
                <span>
                  {mt === "word"
                    ? "Sadece kelime"
                    : mt === "figurative"
                    ? "Sadece görsel"
                    : mt === "combined"
                    ? "Kelime + görsel"
                    : "Sıra dışı"}
                </span>
              </label>
            ),
          )}
        </div>
        {needsMarkText && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Marka metni *
            </label>
            <input
              value={form.mark_text}
              onChange={(e) => setForm((f) => ({ ...f, mark_text: e.target.value }))}
              required
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            />
          </div>
        )}
        {needsMarkImage && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Marka görseli *
            </label>
            <input
              type="file"
              accept=".png,.jpg,.jpeg,.gif,.svg"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) onImageUpload(file);
              }}
              className="text-sm"
            />
            {imageUploading && (
              <p className="text-xs text-gray-500 mt-1">Yükleniyor…</p>
            )}
            {form.mark_image_path && (
              <p className="text-xs text-green-700 mt-1">
                Yüklendi: <code className="text-[11px]">{form.mark_image_path}</code>
              </p>
            )}
          </div>
        )}
      </fieldset>

      {/* Owner */}
      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold text-gray-700">Sahip (applicant)</legend>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Sahip tipi *
            </label>
            <select
              value={form.owner.entity_type}
              onChange={(e) => setOwner("entity_type", e.target.value as EntityType)}
              required
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="" disabled>
                Seçiniz…
              </option>
              {ENTITY_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {form.owner.entity_type === "Individual(s)"
                ? "Tam ad *"
                : form.owner.entity_type === "Partnership"
                ? "Ortak adı *"
                : form.owner.entity_type === "Trust"
                ? "Tröst adı *"
                : "Şirket adı *"}
            </label>
            <input
              required
              value={form.owner.company_name}
              onChange={(e) => setOwner("company_name", e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Ülke *
            </label>
            <input
              required
              value={form.owner.country}
              onChange={(e) => setOwner("country", e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {ownerIsUK ? "Postcode *" : "Posta kodu"}
            </label>
            <input
              required={ownerIsUK}
              value={form.owner.postcode}
              onChange={(e) => setOwner("postcode", e.target.value)}
              placeholder={ownerIsUK ? "örn. NW1 6XE" : "opsiyonel"}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Adres satırı 1 *
            </label>
            <input
              required
              value={form.owner.address_line1}
              onChange={(e) => setOwner("address_line1", e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Adres satırı 2
            </label>
            <input
              value={form.owner.address_line2}
              onChange={(e) => setOwner("address_line2", e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Şehir *
            </label>
            <input
              required
              value={form.owner.city}
              onChange={(e) => setOwner("city", e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Telefon
            </label>
            <input
              value={form.owner.phone}
              onChange={(e) => setOwner("phone", e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              E-posta
            </label>
            <input
              type="email"
              value={form.owner.email}
              onChange={(e) => setOwner("email", e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          {needsCompanyReg && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                UK Şirket Tescil No *
              </label>
              <input
                required={needsCompanyReg}
                value={form.owner.company_registration_number}
                onChange={(e) =>
                  setOwner("company_registration_number", e.target.value)
                }
                placeholder="8 hane"
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
          )}
        </div>
      </fieldset>

      {/* Nice classes */}
      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold text-gray-700">
          Nice sınıfları (mal/hizmet)
        </legend>
        <div className="space-y-2">
          {form.classes.map((c, idx) => (
            <div key={idx} className="grid grid-cols-12 gap-2">
              <input
                type="number"
                min={1}
                max={45}
                value={c.class_number === 0 ? "" : c.class_number}
                onChange={(e) =>
                  updateClass(idx, {
                    class_number: e.target.value === "" ? 0 : Number(e.target.value),
                  })
                }
                placeholder="1-45"
                required
                className="col-span-2 rounded border border-gray-300 px-3 py-2 text-sm"
              />
              <textarea
                value={c.description}
                onChange={(e) => updateClass(idx, { description: e.target.value })}
                placeholder="Mallar/hizmetler — bu sınıf için liste"
                required
                rows={2}
                className="col-span-9 rounded border border-gray-300 px-3 py-2 text-sm"
              />
              <button
                type="button"
                onClick={() => removeClass(idx)}
                disabled={form.classes.length === 1}
                className="col-span-1 rounded border border-gray-300 text-sm text-gray-500 hover:bg-gray-50 disabled:opacity-30"
              >
                −
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={addClass}
          className="text-sm text-purple-600 hover:text-purple-700"
        >
          + Sınıf ekle
        </button>
      </fieldset>

      <div className="flex items-center gap-3 pt-2">
        <button
          type="submit"
          disabled={loading || imageUploading}
          className="rounded bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
        >
          {loading ? "Oluşturuluyor…" : "Başvuruyu Oluştur"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          İptal
        </button>
      </div>
    </form>
  );
}

interface ListProps {
  submissions: UKIPOSubmission[];
  braidConflictsBySubmission: Record<string, BraidConflictDecision>;
  loading: boolean;
  busyId: string | null;
  onStart: (id: string) => Promise<void>;
  onPay: (s: UKIPOSubmission) => Promise<void>;
  walletConnected: boolean;
}

function UKIPOSubmissionList({
  submissions,
  braidConflictsBySubmission,
  loading,
  busyId,
  onStart,
  onPay,
  walletConnected,
}: ListProps) {
  if (loading) {
    return <p className="text-sm text-gray-400">Yükleniyor…</p>;
  }
  if (submissions.length === 0) {
    return (
      <p className="text-sm text-gray-400">
        Bu dava için henüz UK IPO başvurusu yok.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {submissions.map((s) => (
        <SubmissionRow
          key={s.id}
          submission={s}
          braidConflict={braidConflictsBySubmission[s.id] ?? null}
          busy={busyId === s.id}
          onStart={onStart}
          onPay={onPay}
          walletConnected={walletConnected}
        />
      ))}
    </div>
  );
}

interface RowProps {
  submission: UKIPOSubmission;
  braidConflict: BraidConflictDecision | null;
  busy: boolean;
  onStart: (id: string) => Promise<void>;
  onPay: (s: UKIPOSubmission) => Promise<void>;
  walletConnected: boolean;
}

function braidRiskBadgeClass(level: string | null): string {
  switch (level) {
    case "exact":
    case "high":
      return "bg-red-100 text-red-700 border-red-200";
    case "medium":
      return "bg-yellow-100 text-yellow-800 border-yellow-200";
    case "low":
      return "bg-blue-100 text-blue-700 border-blue-200";
    case "none":
      return "bg-emerald-100 text-emerald-700 border-emerald-200";
    default:
      return "bg-gray-100 text-gray-700 border-gray-200";
  }
}

function SubmissionRow({ submission, braidConflict, busy, onStart, onPay, walletConnected }: RowProps) {
  const stepLabel = submission.current_step
    ? STEP_LABELS[submission.current_step] ?? submission.current_step
    : null;
  const startedAt = submission.started_at
    ? new Date(submission.started_at).toLocaleString()
    : null;
  const finishedAt = submission.finished_at
    ? new Date(submission.finished_at).toLocaleString()
    : null;

  return (
    <div className="rounded border border-gray-200 p-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium border ${
                STATUS_BADGE[submission.status]
              }`}
            >
              {STATUS_LABEL[submission.status]}
            </span>
            <span className="text-sm font-medium text-gray-800">
              {submission.mark_text ?? `(${submission.mark_type})`}
            </span>
            <span className="text-xs text-gray-400">{submission.id.slice(0, 8)}</span>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            Sahip: {submission.owner_company_name} · {submission.owner_country}
          </p>
          {startedAt && (
            <p className="text-xs text-gray-500">
              Başladı: {startedAt}
              {finishedAt && ` · Bitti: ${finishedAt}`}
            </p>
          )}
          {submission.status === "running" && stepLabel && (
            <p className="text-xs text-blue-700 mt-1">
              <span className="inline-block w-2 h-2 rounded-full bg-blue-500 animate-pulse mr-1.5" />
              Adım: {stepLabel}
            </p>
          )}
          {braidConflict && (() => {
            const result = braidConflict.result ?? {};
            const risk = typeof result.risk_level === "string" ? result.risk_level : null;
            const matchCount =
              typeof result.match_count === "number" ? result.match_count : null;
            const reasoning =
              typeof result.reasoning === "string" ? result.reasoning : null;
            return (
              <div className="mt-2 rounded border bg-gray-50 px-2 py-1.5 text-xs">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-gray-700">BRAID conflict:</span>
                  {risk && (
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium border ${braidRiskBadgeClass(risk)}`}
                    >
                      {risk}
                    </span>
                  )}
                  {matchCount !== null && (
                    <span className="text-gray-500">{matchCount} eşleşme</span>
                  )}
                  {braidConflict.error && (
                    <span className="text-red-600">{braidConflict.error.slice(0, 80)}</span>
                  )}
                </div>
                {reasoning && (
                  <p className="text-gray-500 mt-0.5">{reasoning}</p>
                )}
              </div>
            );
          })()}
          {submission.status === "failed" && (
            <div className="mt-2 rounded bg-red-50 border border-red-200 p-2 text-xs text-red-700">
              <p>
                <strong>Hata adımı:</strong> {submission.error_step ?? "?"}
              </p>
              {submission.error_message && (
                <p className="mt-1">
                  <strong>Mesaj:</strong> {submission.error_message}
                </p>
              )}
              {submission.screenshot_path && (
                <p className="mt-1 text-[11px] opacity-70">
                  Ekran görüntüsü: {submission.screenshot_path}
                </p>
              )}
            </div>
          )}
          {submission.status === "awaiting_payment" && (
            <div className="mt-2 rounded bg-yellow-50 border border-yellow-200 p-2 text-xs text-yellow-800">
              Robot ödeme ekranına ulaştı. Müşteri Solana üzerinden ödemeyi yapsın
              — Etornie sonra £265 IPO ücretini banka kartıyla tamamlar.
            </div>
          )}
          {submission.solana_payment_tx && (
            <p className="text-xs text-green-700 mt-1">
              Solana ödemesi alındı: {submission.solana_payment_tx.slice(0, 24)}…
            </p>
          )}
        </div>
        <div className="flex flex-col gap-2 items-end">
          {submission.status === "pending" && (
            <button
              type="button"
              onClick={() => onStart(submission.id)}
              disabled={busy}
              className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {busy ? "Başlatılıyor…" : "Robotu Başlat"}
            </button>
          )}
          {submission.status === "failed" && (
            <button
              type="button"
              onClick={() => onStart(submission.id)}
              disabled={busy}
              className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {busy ? "Yeniden başlatılıyor…" : "Tekrar Dene"}
            </button>
          )}
          {submission.status === "awaiting_payment" && !submission.solana_payment_tx && (
            <button
              type="button"
              onClick={() => onPay(submission)}
              disabled={busy || !walletConnected}
              title={!walletConnected ? "Cüzdan bağlanmalı" : undefined}
              className="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
            >
              {busy ? "İşleniyor…" : "SOL ile Öde"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
