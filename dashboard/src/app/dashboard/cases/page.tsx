"use client";

import { useEffect, useState, useMemo, useRef, FormEvent } from "react";
import Link from "next/link";
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
  process.env.NEXT_PUBLIC_SOLANA_CLUSTER_URL ??
  "https://api.devnet.solana.com";

interface PendingAttestation {
  program_id: string;
  operator: string;
  pda: string;
  ix_data_b64: string;
  recent_blockhash: string;
}

interface CaseCreateApiResponse {
  case: CaseItem;
  attestation: PendingAttestation | null;
}

function base64ToBytes(b64: string): Uint8Array {
  const raw = atob(b64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) {
    bytes[i] = raw.charCodeAt(i);
  }
  return bytes;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

interface CaseItem {
  id: string;
  case_number: string;
  title: string;
  case_type: string;
  status: string;
  deadline: string | null;
  deadline_time: string | null;
  client_id: string | null;
  assigned_lawyer_id: string | null;
  jurisdiction: string | null;
  filing_date: string | null;
  guest_client_name: string | null;
  guest_client_email: string | null;
  guest_client_phone: string | null;
  created_at: string;
  attestation_tx: string | null;
  attestation_pda: string | null;
}

interface CaseListResponse {
  cases: CaseItem[];
  total: number;
}

const CASE_TYPES = ["trademark", "patent", "design", "copyright"];

const NICE_CLASSES: ReadonlyArray<{ class_number: number; category: string; description: string }> = [
  { class_number: 1, category: "goods", description: "Chemicals for use in industry, science and photography, as well as in agriculture, horticulture and forestry; unprocessed artificial resins, unprocessed plastics; fire extinguishing and fire prevention compositions; tempering and soldering preparations; substances for tanning animal skins and hides; adhesives for use in industry; putties and other paste fillers; compost, manures, fertilizers; biological preparations for use in industry and science." },
  { class_number: 2, category: "goods", description: "Paints, varnishes, lacquers; preservatives against rust and against deterioration of wood; colorants, dyes; inks for printing, marking and engraving; raw natural resins; metals in foil and powder form for use in painting, decorating, printing and art." },
  { class_number: 3, category: "goods", description: "Non-medicated cosmetics and toiletry preparations; non-medicated dentifrices; perfumery, essential oils; bleaching preparations and other substances for laundry use; cleaning, polishing and abrasive preparations." },
  { class_number: 4, category: "goods", description: "Industrial oils and greases, wax; lubricants; dust absorbing, wetting and binding compositions; fuels and illuminants; candles and wicks for lighting." },
  { class_number: 5, category: "goods", description: "Pharmaceuticals, medical and veterinary preparations; sanitary preparations for medical purposes; dietetic food and substances adapted for medical or veterinary use, food for babies; dietary supplements for human beings and animals; plasters, materials for dressings; material for stopping teeth, dental wax; disinfectants; preparations for destroying vermin; fungicides, herbicides." },
  { class_number: 6, category: "goods", description: "Common metals and their alloys, ores; metal materials for building and construction; transportable buildings of metal; non-electric cables and wires of common metal; small items of metal hardware; metal containers for storage or transport; safes." },
  { class_number: 7, category: "goods", description: "Machines, machine tools, power-operated tools; motors and engines, except for land vehicles; machine coupling and transmission components, except for land vehicles; agricultural implements, other than hand-operated hand tools; incubators for eggs; automatic vending machines." },
  { class_number: 8, category: "goods", description: "Hand tools and implements, hand-operated; cutlery; side arms, except firearms; razors." },
  { class_number: 9, category: "goods", description: "Scientific, research, navigation, surveying, photographic, cinematographic, audiovisual, optical, weighing, measuring, signalling, detecting, testing, inspecting, life-saving and teaching apparatus and instruments; apparatus and instruments for conducting, switching, transforming, accumulating, regulating or controlling the distribution or use of electricity; apparatus and instruments for recording, transmitting, reproducing or processing sound, images or data; recorded and downloadable media, computer software, blank digital or analogue recording and storage media; mechanisms for coin-operated apparatus; cash registers, calculating devices; computers and computer peripheral devices; diving suits, divers' masks, ear plugs for divers, nose clips for divers and swimmers, gloves for divers, breathing apparatus for underwater swimming; fire-extinguishing apparatus." },
  { class_number: 10, category: "goods", description: "Surgical, medical, dental and veterinary apparatus and instruments; artificial limbs, eyes and teeth; orthopaedic articles; suture materials; therapeutic and assistive devices adapted for persons with disabilities; massage apparatus; apparatus, devices and articles for nursing infants; sexual activity apparatus, devices and articles." },
  { class_number: 11, category: "goods", description: "Apparatus and installations for lighting, heating, cooling, steam generating, cooking, drying, ventilating, water supply and sanitary purposes." },
  { class_number: 12, category: "goods", description: "Vehicles; apparatus for locomotion by land, air or water." },
  { class_number: 13, category: "goods", description: "Firearms; ammunition and projectiles; explosives; fireworks." },
  { class_number: 14, category: "goods", description: "Precious metals and their alloys; jewellery, precious and semi-precious stones; horological and chronometric instruments." },
  { class_number: 15, category: "goods", description: "Musical instruments; music stands and stands for musical instruments; conductors' batons." },
  { class_number: 16, category: "goods", description: "Paper and cardboard; printed matter; bookbinding material; photographs; stationery and office requisites, except furniture; adhesives for stationery or household purposes; drawing materials and materials for artists; paintbrushes; instructional and teaching materials; plastic sheets, films and bags for wrapping and packaging; printers' type, printing blocks." },
  { class_number: 17, category: "goods", description: "Unprocessed and semi-processed rubber, gutta-percha, gum, asbestos, mica and substitutes for all these materials; plastics and resins in extruded form for use in manufacture; packing, stopping and insulating materials; flexible pipes, tubes and hoses, not of metal." },
  { class_number: 18, category: "goods", description: "Leather and imitations of leather; animal skins and hides; luggage and carrying bags; umbrellas and parasols; walking sticks; whips, harness and saddlery; collars, leashes and clothing for animals." },
  { class_number: 19, category: "goods", description: "Materials, not of metal, for building and construction; rigid pipes, not of metal, for building; asphalt, pitch, tar and bitumen; transportable buildings, not of metal; monuments, not of metal." },
  { class_number: 20, category: "goods", description: "Furniture, mirrors, picture frames; containers, not of metal, for storage or transport; unworked or semi-worked bone, horn, whalebone or mother-of-pearl; shells; meerschaum; yellow amber." },
  { class_number: 21, category: "goods", description: "Household or kitchen utensils and containers; cookware and tableware, except forks, knives and spoons; combs and sponges; brushes, except paintbrushes; brush-making materials; articles for cleaning purposes; unworked or semi-worked glass, except building glass; glassware, porcelain and earthenware." },
  { class_number: 22, category: "goods", description: "Ropes and string; nets; tents and tarpaulins; awnings of textile or synthetic materials; sails; sacks for the transport and storage of materials in bulk; padding, cushioning and stuffing materials, except of paper, cardboard, rubber or plastics; raw fibrous textile materials and substitutes therefor." },
  { class_number: 23, category: "goods", description: "Yarns and threads for textile use." },
  { class_number: 24, category: "goods", description: "Textiles and substitutes for textiles; household linen; curtains of textile or plastic." },
  { class_number: 25, category: "goods", description: "Clothing, footwear, headwear." },
  { class_number: 26, category: "goods", description: "Lace, braid and embroidery, and haberdashery ribbons and bows; buttons, hooks and eyes, pins and needles; artificial flowers; hair decorations; false hair." },
  { class_number: 27, category: "goods", description: "Carpets, rugs, mats and matting, linoleum and other materials for covering existing floors; wall hangings, not of textile." },
  { class_number: 28, category: "goods", description: "Games, toys and playthings; video game apparatus; gymnastic and sporting articles; decorations for Christmas trees." },
  { class_number: 29, category: "goods", description: "Meat, fish, poultry and game; meat extracts; preserved, frozen, dried and cooked fruits and vegetables; jellies, jams, compotes; eggs; milk, cheese, butter, yogurt and other milk products; oils and fats for food." },
  { class_number: 30, category: "goods", description: "Coffee, tea, cocoa and substitutes therefor; rice, pasta and noodles; tapioca and sago; flour and preparations made from cereals; bread, pastries and confectionery; chocolate; ice cream, sorbets and other edible ices; sugar, honey, treacle; yeast, baking-powder; salt, seasonings, spices, preserved herbs; vinegar, sauces and other condiments; ice (frozen water)." },
  { class_number: 31, category: "goods", description: "Raw and unprocessed agricultural, aquacultural, horticultural and forestry products; raw and unprocessed grains and seeds; fresh fruits and vegetables, fresh herbs; natural plants and flowers; bulbs, seedlings and seeds for planting; live animals; foodstuffs and beverages for animals; malt." },
  { class_number: 32, category: "goods", description: "Beers; non-alcoholic beverages; mineral and aerated waters; fruit beverages and fruit juices; syrups and other preparations for making non-alcoholic beverages." },
  { class_number: 33, category: "goods", description: "Alcoholic beverages, except beers; alcoholic preparations for making beverages." },
  { class_number: 34, category: "goods", description: "Tobacco and tobacco substitutes; cigarettes and cigars; electronic cigarettes and oral vaporizers for smokers; smokers' articles; matches." },
  { class_number: 35, category: "services", description: "Advertising; business management, organization and administration; office functions." },
  { class_number: 36, category: "services", description: "Financial, monetary and banking services; insurance services; real estate services." },
  { class_number: 37, category: "services", description: "Construction services; installation and repair services; mining extraction, oil and gas drilling." },
  { class_number: 38, category: "services", description: "Telecommunications services." },
  { class_number: 39, category: "services", description: "Transport; packaging and storage of goods; travel arrangement." },
  { class_number: 40, category: "services", description: "Treatment of materials; recycling of waste and trash; air purification and treatment of water; printing services; food and drink preservation." },
  { class_number: 41, category: "services", description: "Education; providing of training; entertainment; sporting and cultural activities." },
  { class_number: 42, category: "services", description: "Scientific and technological services and research and design relating thereto; industrial analysis, industrial research and industrial design services; quality control and authentication services; design and development of computer hardware and software." },
  { class_number: 43, category: "services", description: "Services for providing food and drink; temporary accommodation." },
  { class_number: 44, category: "services", description: "Medical services; veterinary services; hygienic and beauty care for human beings or animals; agriculture, aquaculture, horticulture and forestry services." },
  { class_number: 45, category: "services", description: "Legal services; security services for the physical protection of tangible property and individuals; dating services, online social networking services; funerary services; babysitting." },
];

const STATUS_LABELS: Record<string, string> = {
  open: "Open",
  in_progress: "In Progress",
  under_review: "Under Review",
  closed: "Completed",
};

const STATUS_BADGE_COLORS: Record<string, string> = {
  open: "status-pill status-open",
  in_progress: "status-pill status-progress",
  under_review: "status-pill status-review",
  closed: "status-pill status-done",
};

const STATUS_FILTER_COLORS: Record<string, { active: string; inactive: string }> = {
  all: {
    active: "bg-[color:var(--color-espresso)] text-[color:var(--color-cream)]",
    inactive: "bg-[color:var(--color-linen)] text-[color:var(--color-espresso)] hover:bg-[color:var(--color-sand)] border border-[color:var(--color-stone)]",
  },
  open: {
    active: "bg-[color:var(--color-solana-purple)] text-white",
    inactive: "bg-[color:var(--color-status-open-bg)] text-[color:var(--color-status-open-fg)] hover:bg-[color:var(--color-solana-purple-soft)]",
  },
  in_progress: {
    active: "bg-[color:var(--color-gold)] text-[color:var(--color-espresso)]",
    inactive: "bg-[color:var(--color-status-progress-bg)] text-[color:var(--color-status-progress-fg)] hover:bg-[color:var(--color-gold-soft)]",
  },
  under_review: {
    active: "bg-[color:var(--color-bronze)] text-[color:var(--color-cream)]",
    inactive: "bg-[color:var(--color-status-review-bg)] text-[color:var(--color-status-review-fg)] hover:bg-[color:var(--color-stone)]",
  },
  closed: {
    active: "bg-[color:var(--color-solana-green)] text-white",
    inactive: "bg-[color:var(--color-status-done-bg)] text-[color:var(--color-status-done-fg)] hover:bg-[color:var(--color-solana-green-soft)]",
  },
};

const FILTER_TABS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "in_progress", label: "In Progress" },
  { key: "under_review", label: "Under Review" },
  { key: "closed", label: "Completed" },
];

function openPrintView(caseItem: CaseItem, autoPrint: boolean) {
  const printWindow = window.open("", "_blank");
  if (!printWindow) return;

  const statusLabel = STATUS_LABELS[caseItem.status] || caseItem.status;

  printWindow.document.write(`
    <html>
    <head><title>${caseItem.case_number}</title>
    <style>
      body { font-family: Arial, sans-serif; padding: 40px; }
      h1 { font-size: 24px; margin-bottom: 20px; }
      table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
      td, th { padding: 8px 12px; border: 1px solid #ddd; text-align: left; }
      th { background: #f5f5f5; font-weight: 600; width: 200px; }
      .header { display: flex; justify-content: space-between; margin-bottom: 30px; }
      .logo { font-size: 28px; font-weight: bold; }
      .date { color: #666; }
      .pdf-note { margin-top: 20px; padding: 12px; background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 6px; color: #0369a1; font-size: 14px; }
      @media print { .pdf-note { display: none; } }
    </style>
    </head>
    <body>
      <div class="header">
        <div class="logo">Etornie</div>
        <div class="date">${new Date().toLocaleDateString("en-US")}</div>
      </div>
      <h1>Case Details: ${caseItem.case_number}</h1>
      <table>
        <tr><th>Case Number</th><td>${caseItem.case_number}</td></tr>
        <tr><th>Title</th><td>${caseItem.title}</td></tr>
        <tr><th>Type</th><td>${caseItem.case_type}</td></tr>
        <tr><th>Status</th><td>${statusLabel}</td></tr>
        <tr><th>Jurisdiction</th><td>${caseItem.jurisdiction || "-"}</td></tr>
        <tr><th>Filing Date</th><td>${caseItem.filing_date || "-"}</td></tr>
        <tr><th>Deadline</th><td>${caseItem.deadline || "-"}</td></tr>
        <tr><th>Created</th><td>${new Date(caseItem.created_at).toLocaleDateString("en-US")}</td></tr>
      </table>
      ${!autoPrint ? '<div class="pdf-note">To save as PDF, use the &quot;Save as PDF&quot; option in the print dialog.</div>' : ""}
    </body>
    </html>
  `);
  printWindow.document.close();

  if (autoPrint) {
    printWindow.onload = () => {
      printWindow.print();
    };
  }
}

function downloadCSV(caseItem: CaseItem) {
  const headers = [
    "Case Number",
    "Title",
    "Type",
    "Status",
    "Jurisdiction",
    "Filing Date",
    "Deadline",
  ];
  const values = [
    caseItem.case_number,
    caseItem.title,
    caseItem.case_type,
    STATUS_LABELS[caseItem.status] || caseItem.status,
    caseItem.jurisdiction || "",
    caseItem.filing_date || "",
    caseItem.deadline || "",
  ];
  const csv = [headers.join(","), values.map((v) => `"${v}"`).join(",")].join(
    "\n"
  );
  const blob = new Blob(["\uFEFF" + csv], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${caseItem.case_number}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function CasesPage() {
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [activeFilter, setActiveFilter] = useState("all");

  // Country list for jurisdiction dropdown
  const [countryList, setCountryList] = useState<{ country: string; country_code: string | null }[]>([]);
  const [jurisdictionOpen, setJurisdictionOpen] = useState(false);
  const [jurisdictionSearch, setJurisdictionSearch] = useState("");
  const jurisdictionRef = useRef<HTMLDivElement>(null);

  // Close jurisdiction dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (jurisdictionRef.current && !jurisdictionRef.current.contains(e.target as Node)) {
        setJurisdictionOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Create form state
  const [clientMode, setClientMode] = useState<"registered" | "wallet">("registered");
  const [selectedNiceClasses, setSelectedNiceClasses] = useState<number[]>([]);
  const [niceClassDropdownOpen, setNiceClassDropdownOpen] = useState(false);
  const [niceClassSearch, setNiceClassSearch] = useState("");
  const [createForm, setCreateForm] = useState({
    title: "",
    description: "",
    case_type: "trademark",
    client_id: "",
    assigned_lawyer_id: "",
    jurisdiction: "",
    filing_date: "",
    deadline: "",
    deadline_time: "",
    client_wallet: "",
  });
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState("");
  const [createSuccess, setCreateSuccess] = useState("");
  const { publicKey: walletPubkey, signTransaction } = useWallet();

  async function fetchCases() {
    setLoading(true);
    try {
      const res = await api.get<CaseListResponse>("/cases", {
        params: { limit: 100 },
      });
      setCases(res.data.cases);
      setTotal(res.data.total);
    } catch {
      setError("Failed to load cases.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchCases();
    api
      .get<{ country: string; country_code: string | null }[]>("/countries")
      .then((res) => setCountryList(res.data))
      .catch(() => {});
  }, []);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {
      all: cases.length,
      open: 0,
      in_progress: 0,
      under_review: 0,
      closed: 0,
    };
    for (const c of cases) {
      if (counts[c.status] !== undefined) {
        counts[c.status] += 1;
      }
    }
    return counts;
  }, [cases]);

  const filteredCases = useMemo(() => {
    if (activeFilter === "all") return cases;
    return cases.filter((c) => c.status === activeFilter);
  }, [cases, activeFilter]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreateError("");
    setCreateSuccess("");
    setCreateLoading(true);

    try {
      const payload: Record<string, unknown> = {
        title: createForm.title,
        description: createForm.description || null,
        case_type: createForm.case_type,
        assigned_lawyer_id: createForm.assigned_lawyer_id.trim() || null,
        jurisdiction: createForm.jurisdiction || null,
        nice_classes: selectedNiceClasses.length > 0 ? selectedNiceClasses.join(",") : null,
        filing_date: createForm.filing_date || null,
        deadline: createForm.deadline || null,
        deadline_time: createForm.deadline_time || null,
      };

      if (clientMode === "registered") {
        payload.client_id = createForm.client_id.trim() || null;
      } else {
        const wallet = createForm.client_wallet.trim();
        if (!wallet) {
          setCreateError("Client wallet address is required.");
          setCreateLoading(false);
          return;
        }
        // Solana pubkeys are base58 and ~32-44 chars long.
        if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(wallet)) {
          setCreateError("Client wallet must be a valid Solana pubkey.");
          setCreateLoading(false);
          return;
        }
        payload.client_wallet = wallet;
      }

      const res = await api.post<CaseCreateApiResponse>("/cases", payload);
      const { case: newCase, attestation } = res.data;

      if (attestation) {
        if (!signTransaction || !walletPubkey) {
          setCreateSuccess(
            "Case created. Connect a wallet to sign the on-chain attestation.",
          );
        } else {
          try {
            setCreateSuccess("Waiting for wallet signature...");

            // Build the create_case_attestation instruction using the
            // payload the backend prepared. Accounts must follow the
            // exact order declared by the program:
            //   0) attestation PDA (writable)
            //   1) operator (signer, writable, fee payer)
            //   2) creator (signer, readonly) — connected wallet
            //   3) system program
            const programId = new PublicKey(attestation.program_id);
            const operator = new PublicKey(attestation.operator);
            const pda = new PublicKey(attestation.pda);
            const ixData = base64ToBytes(attestation.ix_data_b64);

            const ix = new TransactionInstruction({
              programId,
              keys: [
                { pubkey: pda, isSigner: false, isWritable: true },
                { pubkey: operator, isSigner: true, isWritable: true },
                { pubkey: walletPubkey, isSigner: true, isWritable: false },
                {
                  pubkey: SystemProgram.programId,
                  isSigner: false,
                  isWritable: false,
                },
              ],
              data: Buffer.from(ixData),
            });

            const message = new TransactionMessage({
              payerKey: operator,
              recentBlockhash: attestation.recent_blockhash,
              instructions: [ix],
            }).compileToV0Message();

            const tx = new VersionedTransaction(message);
            const signedTx = await signTransaction(tx);

            setCreateSuccess("Submitting attestation to Solana devnet...");
            const signedB64 = bytesToBase64(signedTx.serialize());
            const submitResp = await api.post<{
              attestation_tx: string;
            }>(`/cases/${newCase.id}/attestation/submit`, {
              signed_tx_b64: signedB64,
            });

            const sig = submitResp.data.attestation_tx;
            setCreateSuccess(
              `Case created and attested on-chain. Tx: ${sig.slice(0, 12)}...`,
            );
          } catch (err) {
            console.error("attestation signing failed", err);
            setCreateSuccess(
              "Case created. On-chain attestation was cancelled or failed — you can retry from the case detail page.",
            );
          }
        }
      } else {
        setCreateSuccess("Case created successfully.");
      }
      setClientMode("registered");
      setSelectedNiceClasses([]);
      setNiceClassSearch("");
      setCreateForm({
        title: "",
        description: "",
        case_type: "trademark",
        client_id: "",
        assigned_lawyer_id: "",
        jurisdiction: "",
        filing_date: "",
        deadline: "",
        deadline_time: "",
        client_wallet: "",
      });
      setShowCreate(false);
      fetchCases();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to create case.";
      setCreateError(message);
    } finally {
      setCreateLoading(false);
    }
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-800">
          Cases ({total})
        </h1>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          {showCreate ? "Cancel" : "New Case"}
        </button>
      </div>

      {createSuccess && (
        <div className="mb-4 rounded bg-green-50 p-3 text-sm text-green-700 border border-green-200">
          {createSuccess}
        </div>
      )}

      {error && (
        <div className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
          {error}
        </div>
      )}

      {/* Create Case Form */}
      {showCreate && (
        <div className="mb-6 rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <h2 className="mb-4 text-lg font-semibold text-gray-700">
            New Case
          </h2>
          {createError && (
            <div className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
              {createError}
            </div>
          )}
          <form onSubmit={handleCreate} className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label className="block text-sm font-medium text-gray-700">
                Title *
              </label>
              <input
                required
                value={createForm.title}
                onChange={(e) =>
                  setCreateForm({ ...createForm, title: e.target.value })
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="block text-sm font-medium text-gray-700">
                Description
              </label>
              <textarea
                value={createForm.description}
                onChange={(e) =>
                  setCreateForm({
                    ...createForm,
                    description: e.target.value,
                  })
                }
                rows={3}
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Case Type *
              </label>
              <select
                value={createForm.case_type}
                onChange={(e) =>
                  setCreateForm({ ...createForm, case_type: e.target.value })
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                {CASE_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </option>
                ))}
              </select>
            </div>
            <div className="sm:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Client Type *
              </label>
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="clientMode"
                    checked={clientMode === "registered"}
                    onChange={() => setClientMode("registered")}
                    className="accent-blue-600"
                  />
                  <span className="text-sm text-gray-700">Registered Client</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="clientMode"
                    checked={clientMode === "wallet"}
                    onChange={() => setClientMode("wallet")}
                    className="accent-blue-600"
                  />
                  <span className="text-sm text-gray-700">New Client (by Wallet)</span>
                </label>
              </div>
            </div>

            {clientMode === "registered" ? (
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Client ID *
                </label>
                <input
                  required
                  value={createForm.client_id}
                  onChange={(e) =>
                    setCreateForm({ ...createForm, client_id: e.target.value })
                  }
                  placeholder="UUID"
                  className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
            ) : (
              <div className="sm:col-span-2">
                <label className="block text-sm font-medium text-gray-700">
                  Client Wallet Address *
                </label>
                <input
                  required
                  value={createForm.client_wallet}
                  onChange={(e) =>
                    setCreateForm({ ...createForm, client_wallet: e.target.value })
                  }
                  placeholder="e.g. 7xKXtg2CW..."
                  className="mt-1 w-full rounded border border-gray-300 px-3 py-2 font-mono text-sm focus:border-blue-500 focus:outline-none"
                />
                <p className="mt-1 text-xs text-gray-400">
                  Solana pubkey (base58). The case will be anchored on-chain to
                  this wallet. The holder can later register and automatically
                  inherit ownership.
                </p>
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Assigned Lawyer ID
              </label>
              <input
                value={createForm.assigned_lawyer_id}
                onChange={(e) =>
                  setCreateForm({
                    ...createForm,
                    assigned_lawyer_id: e.target.value,
                  })
                }
                placeholder="UUID (optional)"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div className="relative" ref={jurisdictionRef}>
              <label className="block text-sm font-medium text-gray-700">
                Jurisdiction
              </label>
              <div className="relative mt-1">
                <input
                  value={jurisdictionOpen ? jurisdictionSearch : createForm.jurisdiction}
                  onChange={(e) => {
                    setJurisdictionSearch(e.target.value);
                    if (!jurisdictionOpen) setJurisdictionOpen(true);
                  }}
                  onFocus={() => {
                    setJurisdictionOpen(true);
                    setJurisdictionSearch(createForm.jurisdiction);
                  }}
                  placeholder="Search country..."
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
                {createForm.jurisdiction && !jurisdictionOpen && (
                  <button
                    type="button"
                    onClick={() => {
                      setCreateForm({ ...createForm, jurisdiction: "" });
                      setJurisdictionSearch("");
                    }}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    &times;
                  </button>
                )}
              </div>
              {jurisdictionOpen && (
                <div className="absolute z-20 mt-1 w-full max-h-52 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg">
                  {countryList
                    .filter((c) => {
                      const q = jurisdictionSearch.toLowerCase();
                      return (
                        !q ||
                        c.country.toLowerCase().includes(q) ||
                        (c.country_code && c.country_code.toLowerCase().includes(q))
                      );
                    })
                    .slice(0, 50)
                    .map((c) => (
                      <button
                        key={c.country}
                        type="button"
                        onClick={() => {
                          setCreateForm({ ...createForm, jurisdiction: c.country });
                          setJurisdictionSearch("");
                          setJurisdictionOpen(false);
                        }}
                        className={`w-full px-3 py-2 text-left text-sm hover:bg-blue-50 transition-colors ${
                          createForm.jurisdiction === c.country ? "bg-blue-50 font-medium" : ""
                        }`}
                      >
                        <span className="text-gray-800">{c.country}</span>
                        {c.country_code && (
                          <span className="ml-2 text-xs text-gray-400">({c.country_code})</span>
                        )}
                      </button>
                    ))}
                  {countryList.filter((c) => {
                    const q = jurisdictionSearch.toLowerCase();
                    return !q || c.country.toLowerCase().includes(q) || (c.country_code && c.country_code.toLowerCase().includes(q));
                  }).length === 0 && (
                    <p className="px-3 py-2 text-sm text-gray-400">No country found</p>
                  )}
                </div>
              )}
            </div>

            {/* Nice Classes Multi-Select Dropdown */}
            <div className="sm:col-span-2 relative">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Nice Classes
              </label>
              {selectedNiceClasses.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {selectedNiceClasses
                    .slice()
                    .sort((a, b) => a - b)
                    .map((cls) => {
                      const nc = NICE_CLASSES.find((n) => n.class_number === cls);
                      return (
                        <span
                          key={cls}
                          className="inline-flex items-center gap-1 rounded-full bg-blue-100 text-blue-800 px-2.5 py-0.5 text-xs font-medium"
                        >
                          Class {cls}
                          <button
                            type="button"
                            onClick={() =>
                              setSelectedNiceClasses(selectedNiceClasses.filter((c) => c !== cls))
                            }
                            className="ml-0.5 text-blue-600 hover:text-blue-900"
                          >
                            &times;
                          </button>
                        </span>
                      );
                    })}
                  <button
                    type="button"
                    onClick={() => setSelectedNiceClasses([])}
                    className="text-xs text-red-500 hover:text-red-700 ml-1"
                  >
                    Clear all
                  </button>
                </div>
              )}
              <button
                type="button"
                onClick={() => setNiceClassDropdownOpen(!niceClassDropdownOpen)}
                className="w-full flex items-center justify-between rounded border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 hover:border-gray-400 focus:border-blue-500 focus:outline-none"
              >
                <span className="text-gray-500">
                  {selectedNiceClasses.length === 0
                    ? "Select Nice Classes..."
                    : `${selectedNiceClasses.length} class${selectedNiceClasses.length > 1 ? "es" : ""} selected`}
                </span>
                <svg className={`w-4 h-4 text-gray-400 transition-transform ${niceClassDropdownOpen ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {niceClassDropdownOpen && (
                <div className="absolute z-20 mt-1 w-full rounded-lg border border-gray-200 bg-white shadow-lg">
                  <div className="p-2 border-b border-gray-100">
                    <input
                      type="text"
                      value={niceClassSearch}
                      onChange={(e) => setNiceClassSearch(e.target.value)}
                      placeholder="Search classes..."
                      className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
                    />
                  </div>
                  <div className="max-h-60 overflow-y-auto">
                    {["goods", "services"].map((category) => {
                      const filtered = NICE_CLASSES.filter(
                        (nc) =>
                          nc.category === category &&
                          (niceClassSearch === "" ||
                            `Class ${nc.class_number}`.toLowerCase().includes(niceClassSearch.toLowerCase()) ||
                            nc.description.toLowerCase().includes(niceClassSearch.toLowerCase()))
                      );
                      if (filtered.length === 0) return null;
                      return (
                        <div key={category}>
                          <div className="sticky top-0 bg-gray-50 px-3 py-1.5 text-xs font-semibold uppercase text-gray-500 border-b border-gray-100">
                            {category === "goods" ? "Goods (Classes 1-34)" : "Services (Classes 35-45)"}
                          </div>
                          {filtered.map((nc) => {
                            const isSelected = selectedNiceClasses.includes(nc.class_number);
                            return (
                              <label
                                key={nc.class_number}
                                className={`flex items-start gap-2.5 px-3 py-2 cursor-pointer hover:bg-blue-50 transition-colors ${isSelected ? "bg-blue-50" : ""}`}
                              >
                                <input
                                  type="checkbox"
                                  checked={isSelected}
                                  onChange={() => {
                                    if (isSelected) {
                                      setSelectedNiceClasses(selectedNiceClasses.filter((c) => c !== nc.class_number));
                                    } else {
                                      setSelectedNiceClasses([...selectedNiceClasses, nc.class_number]);
                                    }
                                  }}
                                  className="mt-0.5 accent-blue-600 shrink-0"
                                />
                                <div className="min-w-0">
                                  <span className="text-sm font-medium text-gray-800">Class {nc.class_number}</span>
                                  <p className="text-xs text-gray-500 line-clamp-2">{nc.description}</p>
                                </div>
                              </label>
                            );
                          })}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700">
                Filing Date
              </label>
              <input
                type="date"
                value={createForm.filing_date}
                onChange={(e) =>
                  setCreateForm({
                    ...createForm,
                    filing_date: e.target.value,
                  })
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Deadline Date
              </label>
              <input
                type="date"
                value={createForm.deadline}
                onChange={(e) =>
                  setCreateForm({ ...createForm, deadline: e.target.value })
                }
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Deadline Time
              </label>
              <input
                type="time"
                value={createForm.deadline_time}
                onChange={(e) =>
                  setCreateForm({ ...createForm, deadline_time: e.target.value })
                }
                placeholder="HH:MM (optional)"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div className="sm:col-span-2">
              <button
                type="submit"
                disabled={createLoading}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {createLoading ? "Creating..." : "Create Case"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Status Filter Tabs */}
      {!loading && (
        <div className="mb-4 flex flex-wrap gap-2">
          {FILTER_TABS.map((tab) => {
            const isActive = activeFilter === tab.key;
            const colors = STATUS_FILTER_COLORS[tab.key];
            const colorClass = isActive ? colors.active : colors.inactive;
            const count = statusCounts[tab.key] ?? 0;
            return (
              <button
                key={tab.key}
                onClick={() => setActiveFilter(tab.key)}
                className={`rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${colorClass}`}
              >
                {tab.label} ({count})
              </button>
            );
          })}
        </div>
      )}

      {/* Cases Table */}
      {loading ? (
        <p className="text-gray-500">Loading cases...</p>
      ) : filteredCases.length === 0 ? (
        <p className="text-gray-500">
          {activeFilter === "all"
            ? "No cases found."
            : `No cases found with status: ${STATUS_LABELS[activeFilter] || activeFilter}.`}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg bg-white shadow-sm border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Case No
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Title
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Type
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Deadline
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {filteredCases.map((c) => (
                <tr key={c.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm">
                    <div className="flex items-center gap-1.5">
                      <Link
                        href={`/dashboard/cases/${c.id}`}
                        className="text-blue-600 hover:underline font-medium"
                      >
                        {c.case_number}
                      </Link>
                      {c.attestation_tx && (
                        <a
                          href={`https://explorer.solana.com/tx/${c.attestation_tx}?cluster=devnet`}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          title="Verified on-chain — view transaction on Solana Explorer"
                          className="text-emerald-600 hover:text-emerald-700"
                          aria-label="On-chain attestation"
                        >
                          ⛓
                        </a>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-700 max-w-xs truncate">
                    {c.title}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600 capitalize">
                    {c.case_type}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGE_COLORS[c.status] ?? "bg-gray-100 text-gray-800"}`}
                    >
                      {STATUS_LABELS[c.status] || c.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {c.deadline ?? "N/A"}
                    {c.deadline_time && ` ${c.deadline_time}`}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => openPrintView(c, true)}
                        className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-100 transition-colors"
                        title="Print"
                      >
                        Print
                      </button>
                      <button
                        onClick={() => openPrintView(c, false)}
                        className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-100 transition-colors"
                        title="Save as PDF"
                      >
                        PDF
                      </button>
                      <button
                        onClick={() => downloadCSV(c)}
                        className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-100 transition-colors"
                        title="Download as Excel/CSV"
                      >
                        Excel
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
