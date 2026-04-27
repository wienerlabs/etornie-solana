"use client";

import { useState, FormEvent } from "react";
import api from "@/lib/api";

interface SearchResult {
  content: string;
  score: number;
  document_id: string;
}

interface ChatResponse {
  answer: string;
  sources: SearchResult[];
}

interface SearchResponse {
  results: SearchResult[];
}

export default function AIChatPage() {
  // Tab state
  const [activeTab, setActiveTab] = useState<"rag" | "search" | "index">("rag");

  // Case Assistant state
  const [chatQuestion, setChatQuestion] = useState("");
  const [chatCaseId, setChatCaseId] = useState("");
  const [chatAnswer, setChatAnswer] = useState("");
  const [chatSources, setChatSources] = useState<SearchResult[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState("");

  // Search state
  const [searchQuery, setSearchQuery] = useState("");
  const [searchCaseId, setSearchCaseId] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState("");

  // Index state
  const [indexDocId, setIndexDocId] = useState("");
  const [indexLoading, setIndexLoading] = useState(false);
  const [indexError, setIndexError] = useState("");
  const [indexSuccess, setIndexSuccess] = useState("");

  async function handleChat(e: FormEvent) {
    e.preventDefault();
    setChatError("");
    setChatAnswer("");
    setChatSources([]);
    setChatLoading(true);

    try {
      const res = await api.post<ChatResponse>("/ai/rag/chat", {
        question: chatQuestion,
        case_id: chatCaseId || null,
      });
      setChatAnswer(res.data.answer);
      setChatSources(res.data.sources);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Chat request failed.";
      setChatError(message);
    } finally {
      setChatLoading(false);
    }
  }

  async function handleSearch(e: FormEvent) {
    e.preventDefault();
    setSearchError("");
    setSearchResults([]);
    setSearchLoading(true);

    try {
      const res = await api.post<SearchResponse>("/ai/search", {
        query: searchQuery,
        case_id: searchCaseId || null,
      });
      setSearchResults(res.data.results);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Search request failed.";
      setSearchError(message);
    } finally {
      setSearchLoading(false);
    }
  }

  async function handleIndex(e: FormEvent) {
    e.preventDefault();
    setIndexError("");
    setIndexSuccess("");
    setIndexLoading(true);

    try {
      const res = await api.post(`/ai/index/${indexDocId}`);
      setIndexSuccess(
        `Document indexed successfully. Chunks created: ${res.data.chunks_created}`
      );
      setIndexDocId("");
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Index request failed.";
      setIndexError(message);
    } finally {
      setIndexLoading(false);
    }
  }

  const tabs = [
    { id: "rag" as const, label: "Case Assistant" },
    { id: "search" as const, label: "Document Search" },
    { id: "index" as const, label: "Index Document" },
  ];

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold text-gray-800">AI Assistant</h1>

      {/* Tabs */}
      <div className="mb-6 flex gap-1 rounded-lg bg-gray-100 p-1">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? "bg-white text-gray-800 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Case Assistant Tab */}
      {activeTab === "rag" && (
        <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <h2 className="mb-4 text-lg font-semibold text-gray-700">Case Assistant</h2>

          <form onSubmit={handleChat} className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-700">Question *</label>
              <textarea
                required
                value={chatQuestion}
                onChange={(e) => setChatQuestion(e.target.value)}
                rows={3}
                placeholder="Ask a question about your cases..."
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Case ID (optional)</label>
              <input
                value={chatCaseId}
                onChange={(e) => setChatCaseId(e.target.value)}
                placeholder="UUID to scope chat to a case"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <button
              type="submit"
              disabled={chatLoading}
              className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {chatLoading ? "Thinking..." : "Send"}
            </button>
          </form>

          {chatError && (
            <div className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
              {chatError}
            </div>
          )}

          {chatAnswer && (
            <div className="mt-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-2">Answer</h3>
              <div className="rounded bg-blue-50 p-4 text-sm text-gray-800 whitespace-pre-wrap border border-blue-100">
                {chatAnswer}
              </div>

              {chatSources.length > 0 && (
                <div className="mt-3">
                  <h4 className="text-xs font-semibold text-gray-500 uppercase mb-2">
                    Sources ({chatSources.length})
                  </h4>
                  <div className="space-y-2 max-h-48 overflow-y-auto">
                    {chatSources.map((s, i) => (
                      <div key={i} className="rounded bg-gray-50 p-2 text-xs border border-gray-100">
                        <p className="text-gray-700 line-clamp-3">{s.content}</p>
                        <p className="mt-1 text-gray-400">
                          Score: {s.score.toFixed(3)} | Doc: {s.document_id.slice(0, 8)}...
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Search Tab */}
      {activeTab === "search" && (
        <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <h2 className="mb-4 text-lg font-semibold text-gray-700">Document Search</h2>

          <form onSubmit={handleSearch} className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-700">Query *</label>
              <input
                required
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search for similar content..."
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Case ID (optional)</label>
              <input
                value={searchCaseId}
                onChange={(e) => setSearchCaseId(e.target.value)}
                placeholder="UUID to scope search"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <button
              type="submit"
              disabled={searchLoading}
              className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {searchLoading ? "Searching..." : "Search"}
            </button>
          </form>

          {searchError && (
            <div className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
              {searchError}
            </div>
          )}

          {searchResults.length > 0 && (
            <div className="mt-4 space-y-2 max-h-64 overflow-y-auto">
              <h3 className="text-sm font-semibold text-gray-700">Results ({searchResults.length})</h3>
              {searchResults.map((r, i) => (
                <div key={i} className="rounded bg-gray-50 p-3 text-sm border border-gray-100">
                  <p className="text-gray-700">{r.content}</p>
                  <p className="mt-1 text-xs text-gray-400">
                    Score: {r.score.toFixed(3)} | Doc: {r.document_id.slice(0, 8)}...
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Index Tab */}
      {activeTab === "index" && (
        <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <h2 className="mb-4 text-lg font-semibold text-gray-700">Index Document</h2>

          <form onSubmit={handleIndex} className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-700">Document ID *</label>
              <input
                required
                value={indexDocId}
                onChange={(e) => setIndexDocId(e.target.value)}
                placeholder="UUID of document to index"
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <button
              type="submit"
              disabled={indexLoading}
              className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {indexLoading ? "Indexing..." : "Index Document"}
            </button>
          </form>

          {indexError && (
            <div className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
              {indexError}
            </div>
          )}
          {indexSuccess && (
            <div className="mt-4 rounded bg-green-50 p-3 text-sm text-green-700 border border-green-200">
              {indexSuccess}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
