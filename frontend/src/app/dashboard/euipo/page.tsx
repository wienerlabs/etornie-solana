"use client";

import { useState, FormEvent } from "react";
import api from "@/lib/api";

// ── Types ──

interface TrademarkResult {
  applicationNumber?: string;
  wordMarkSpecification?: { verbalElement?: string };
  status?: string;
  applicants?: { name?: string }[];
  niceClasses?: number[];
  applicationDate?: string;
  registrationDate?: string;
  office?: string;
}

interface GoodsServicesTerm {
  termText?: string;
  text?: string;
  classNumber?: number;
  language?: string;
  conceptId?: string;
}

const TABS = [
  { key: "trademark-search", label: "Trademark Search" },
  { key: "goods-services", label: "Goods & Services" },
  { key: "design-search", label: "Design Search" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function EUIPOPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("trademark-search");

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-800 mb-6">EUIPO Services</h1>

      {/* Tabs */}
      <div className="flex border-b border-gray-200 mb-6">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-5 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.key
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "trademark-search" && <TrademarkSearchTab />}
      {activeTab === "goods-services" && <GoodsServicesTab />}
      {activeTab === "design-search" && <DesignSearchTab />}
    </div>
  );
}

// ── Trademark Search Tab ──

function TrademarkSearchTab() {
  const [markText, setMarkText] = useState("");
  const [niceClasses, setNiceClasses] = useState("");
  const [offices, setOffices] = useState("EM");
  const [results, setResults] = useState<TrademarkResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searched, setSearched] = useState(false);

  async function handleSearch(e: FormEvent) {
    e.preventDefault();
    if (!markText.trim()) return;

    setError("");
    setLoading(true);
    setSearched(true);

    try {
      const payload: Record<string, unknown> = {
        query: markText.trim(),
      };
      if (niceClasses.trim()) {
        payload.nice_classes = niceClasses
          .split(",")
          .map((s) => parseInt(s.trim(), 10))
          .filter((n) => !isNaN(n));
      }
      if (offices.trim()) {
        payload.offices = offices.split(",").map((s) => s.trim());
      }

      const res = await api.post("/euipo/trademark-search", payload);
      const data = res.data;
      setResults(data.trademarks || data.results || data.content || []);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Search failed. Check your connection.";
      setError(message);
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200 mb-6">
        <h2 className="text-lg font-semibold text-gray-700 mb-4">
          Search EU Trademark Database
        </h2>
        <p className="text-sm text-gray-500 mb-4">
          Check for similar or identical trademarks before filing. Uses EUIPO's
          official database.
        </p>

        <form onSubmit={handleSearch} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="sm:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Trademark Name *
              </label>
              <input
                value={markText}
                onChange={(e) => setMarkText(e.target.value)}
                required
                placeholder='e.g. "Etornie"'
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Office
              </label>
              <input
                value={offices}
                onChange={(e) => setOffices(e.target.value)}
                placeholder="EM, DE, FR..."
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
              <p className="mt-1 text-xs text-gray-400">
                EM = EU, or country codes
              </p>
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Nice Classes (optional)
            </label>
            <input
              value={niceClasses}
              onChange={(e) => setNiceClasses(e.target.value)}
              placeholder="e.g. 9,35,42"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="rounded bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? "Searching..." : "Search EUIPO"}
          </button>
        </form>
      </div>

      {/* Results */}
      {error && (
        <div className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
          {error}
        </div>
      )}

      {searched && !loading && results.length === 0 && !error && (
        <div className="rounded bg-green-50 p-4 border border-green-200">
          <p className="text-sm text-green-800 font-medium">
            No similar trademarks found. The name appears to be available.
          </p>
        </div>
      )}

      {results.length > 0 && (
        <div className="rounded-lg bg-white shadow-sm border border-gray-200">
          <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-gray-700">
              {results.length} result{results.length > 1 ? "s" : ""} found
            </h3>
          </div>
          <div className="divide-y divide-gray-100">
            {results.map((tm, i) => (
              <div key={tm.applicationNumber || i} className="px-4 py-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold text-gray-800">
                      {tm.wordMarkSpecification?.verbalElement || "Figurative Mark"}
                    </p>
                    <p className="text-xs text-gray-500">
                      {tm.applicationNumber}
                      {tm.applicants?.[0]?.name &&
                        ` — ${tm.applicants[0].name}`}
                    </p>
                  </div>
                  <div className="text-right">
                    <span
                      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                        tm.status === "REGISTERED"
                          ? "bg-green-100 text-green-800"
                          : tm.status === "FILED"
                            ? "bg-blue-100 text-blue-800"
                            : "bg-gray-100 text-gray-700"
                      }`}
                    >
                      {tm.status || "Unknown"}
                    </span>
                  </div>
                </div>
                <div className="mt-1 flex items-center gap-3 text-xs text-gray-400">
                  {tm.niceClasses && tm.niceClasses.length > 0 && (
                    <span>
                      Classes: {tm.niceClasses.join(", ")}
                    </span>
                  )}
                  {tm.applicationDate && (
                    <span>Filed: {tm.applicationDate}</span>
                  )}
                  {tm.registrationDate && (
                    <span>Reg: {tm.registrationDate}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Goods & Services Tab ──

function GoodsServicesTab() {
  const [query, setQuery] = useState("");
  const [niceClass, setNiceClass] = useState("");
  const [terms, setTerms] = useState<GoodsServicesTerm[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Validation
  const [validateInput, setValidateInput] = useState("");
  const [validateClass, setValidateClass] = useState("9");
  const [validateResult, setValidateResult] = useState<Record<string, unknown> | null>(null);
  const [validateLoading, setValidateLoading] = useState(false);

  async function handleSearch(e: FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;

    setError("");
    setLoading(true);

    try {
      const payload: Record<string, unknown> = { query: query.trim() };
      if (niceClass.trim()) {
        payload.nice_class = parseInt(niceClass, 10);
      }

      const res = await api.post("/euipo/goods-services/search", payload);
      setTerms(res.data.terms || res.data.content || []);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Search failed.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  async function handleValidate(e: FormEvent) {
    e.preventDefault();
    if (!validateInput.trim()) return;

    setValidateLoading(true);
    setValidateResult(null);

    try {
      const termsToValidate = validateInput
        .split("\n")
        .map((t) => t.trim())
        .filter(Boolean);

      const res = await api.post("/euipo/goods-services/validate", {
        terms: [
          {
            classNumber: parseInt(validateClass, 10),
            terms: termsToValidate,
          },
        ],
      });
      setValidateResult(res.data);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Validation failed.";
      setValidateResult({ error: message });
    } finally {
      setValidateLoading(false);
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Search Panel */}
      <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200">
        <h2 className="text-lg font-semibold text-gray-700 mb-3">
          Search Terms
        </h2>
        <p className="text-sm text-gray-500 mb-4">
          Find approved goods/services terms from the EUIPO TMClass taxonomy.
        </p>

        <form onSubmit={handleSearch} className="space-y-3">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            required
            placeholder='e.g. "software", "clothing"'
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
          <div className="flex gap-3">
            <input
              value={niceClass}
              onChange={(e) => setNiceClass(e.target.value)}
              placeholder="Nice class (optional)"
              className="w-32 rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
            <button
              type="submit"
              disabled={loading}
              className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? "..." : "Search"}
            </button>
          </div>
        </form>

        {error && (
          <p className="mt-3 text-sm text-red-600">{error}</p>
        )}

        {terms.length > 0 && (
          <div className="mt-4 max-h-72 overflow-y-auto space-y-1">
            {terms.map((term, i) => (
              <div
                key={i}
                className="flex items-center justify-between rounded bg-gray-50 px-3 py-2 border border-gray-100"
              >
                <span className="text-sm text-gray-800">
                  {term.text || term.termText}
                </span>
                <span className="text-xs text-gray-500 shrink-0 ml-2">
                  Class {term.classNumber}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Validation Panel */}
      <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200">
        <h2 className="text-lg font-semibold text-gray-700 mb-3">
          Validate Classification
        </h2>
        <p className="text-sm text-gray-500 mb-4">
          Check if your goods/services terms are accepted by EUIPO.
        </p>

        <form onSubmit={handleValidate} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Nice Class
            </label>
            <input
              value={validateClass}
              onChange={(e) => setValidateClass(e.target.value)}
              placeholder="e.g. 9"
              className="w-24 rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Terms (one per line)
            </label>
            <textarea
              value={validateInput}
              onChange={(e) => setValidateInput(e.target.value)}
              rows={4}
              placeholder={"Computer software\nMobile applications\nCloud computing"}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <button
            type="submit"
            disabled={validateLoading}
            className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {validateLoading ? "Validating..." : "Validate"}
          </button>
        </form>

        {validateResult && (
          <div className="mt-4 rounded bg-gray-50 p-3 border border-gray-200">
            <pre className="text-xs text-gray-700 whitespace-pre-wrap overflow-auto max-h-48">
              {JSON.stringify(validateResult, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Design Search Tab ──

function DesignSearchTab() {
  const [query, setQuery] = useState("");
  const [locarnoClasses, setLocarnoClasses] = useState("");
  const [results, setResults] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searched, setSearched] = useState(false);

  async function handleSearch(e: FormEvent) {
    e.preventDefault();

    setError("");
    setLoading(true);
    setSearched(true);

    try {
      const payload: Record<string, unknown> = {};
      if (query.trim()) payload.query = query.trim();
      if (locarnoClasses.trim()) {
        payload.locarno_classes = locarnoClasses.split(",").map((s) => s.trim());
      }

      const res = await api.post("/euipo/design-search", payload);
      setResults(res.data.designs || res.data.results || res.data.content || []);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Search failed.";
      setError(message);
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200 mb-6">
        <h2 className="text-lg font-semibold text-gray-700 mb-4">
          Search EU Design Database
        </h2>

        <form onSubmit={handleSearch} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Applicant / Holder Name
              </label>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder='e.g. "Apple", "Samsung"'
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Locarno Classes
              </label>
              <input
                value={locarnoClasses}
                onChange={(e) => setLocarnoClasses(e.target.value)}
                placeholder="e.g. 06.01, 12.08"
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
              <p className="mt-1 text-xs text-gray-400">06.01 = Furniture, 12.08 = Vehicles, etc.</p>
            </div>
          </div>
          <button
            type="submit"
            disabled={loading}
            className="rounded bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? "Searching..." : "Search Designs"}
          </button>
        </form>
      </div>

      {error && (
        <div className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
          {error}
        </div>
      )}

      {searched && !loading && results.length === 0 && !error && (
        <div className="rounded bg-green-50 p-4 border border-green-200">
          <p className="text-sm text-green-800 font-medium">
            No similar designs found.
          </p>
        </div>
      )}

      {results.length > 0 && (
        <div className="rounded-lg bg-white shadow-sm border border-gray-200">
          <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-gray-700">
              {results.length} result{results.length > 1 ? "s" : ""}
            </h3>
          </div>
          <div className="divide-y divide-gray-100">
            {results.map((d, i) => (
              <div key={i} className="px-4 py-3">
                <pre className="text-xs text-gray-700 whitespace-pre-wrap">
                  {JSON.stringify(d, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
