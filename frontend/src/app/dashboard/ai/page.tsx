"use client";

import { useState, FormEvent, useRef, useEffect } from "react";
import api from "@/lib/api";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  country?: string | null;
  timestamp: Date;
}

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

interface EtornieGPTResponse {
  answer: string;
  country_detected: string | null;
  model: string;
}

export default function AIChatPage() {
  // EtornieGPT state
  const [gptMessages, setGptMessages] = useState<ChatMessage[]>([]);
  const [gptInput, setGptInput] = useState("");
  const [gptLoading, setGptLoading] = useState(false);
  const [gptError, setGptError] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Tab state
  const [activeTab, setActiveTab] = useState<"etorniegpt" | "rag" | "search" | "index">("etorniegpt");

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

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [gptMessages]);

  async function handleGptSend(e: FormEvent) {
    e.preventDefault();
    if (!gptInput.trim()) return;

    const question = gptInput.trim();
    setGptInput("");
    setGptError("");

    const userMsg: ChatMessage = {
      role: "user",
      content: question,
      timestamp: new Date(),
    };
    setGptMessages((prev) => [...prev, userMsg]);
    setGptLoading(true);

    try {
      const res = await api.post<EtornieGPTResponse>("/etorniegpt", {
        question,
        language: "tr",
      });

      const assistantMsg: ChatMessage = {
        role: "assistant",
        content: res.data.answer,
        country: res.data.country_detected,
        timestamp: new Date(),
      };
      setGptMessages((prev) => [...prev, assistantMsg]);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "EtornieGPT failed to respond.";
      setGptError(message);
    } finally {
      setGptLoading(false);
    }
  }

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
    { id: "etorniegpt" as const, label: "EtornieGPT" },
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

      {/* EtornieGPT Tab */}
      {activeTab === "etorniegpt" && (
        <div className="rounded-lg bg-white shadow-sm border border-gray-200 flex flex-col" style={{ height: "calc(100vh - 250px)" }}>
          {/* Header */}
          <div className="px-6 py-4 border-b border-gray-200">
            <div className="flex items-center gap-3">
              <div className="h-8 w-8 rounded-full bg-indigo-600 flex items-center justify-center">
                <span className="text-white text-sm font-bold">E</span>
              </div>
              <div>
                <h2 className="text-sm font-semibold text-gray-800">EtornieGPT</h2>
                <p className="text-xs text-gray-500">IP Expert Assistant</p>
              </div>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
            {gptMessages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <div className="h-16 w-16 rounded-full bg-indigo-100 flex items-center justify-center mb-4">
                  <span className="text-indigo-600 text-2xl font-bold">E</span>
                </div>
                <h3 className="text-lg font-semibold text-gray-700 mb-2">EtornieGPT</h3>
                <p className="text-sm text-gray-500 max-w-md">
                  Ask questions about trademark registration, patents, design registration, copyright, and country-specific application processes.
                </p>
                <div className="mt-4 flex flex-wrap gap-2 justify-center">
                  {[
                    "How long does trademark registration take in Germany?",
                    "What does Class 25 cover in the Nice Classification?",
                    "How to file a patent application in the USA?",
                  ].map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onClick={() => setGptInput(suggestion)}
                      className="rounded-full border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50 hover:border-gray-300 transition-colors"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {gptMessages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                    msg.role === "user"
                      ? "bg-indigo-600 text-white"
                      : "bg-gray-100 text-gray-800"
                  }`}
                >
                  {msg.role === "assistant" && msg.country && (
                    <div className="mb-2">
                      <span className="inline-flex items-center rounded-full bg-indigo-100 border border-indigo-200 px-2 py-0.5 text-xs font-medium text-indigo-700">
                        {msg.country}
                      </span>
                    </div>
                  )}
                  <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                  <p className={`text-xs mt-1 ${msg.role === "user" ? "text-indigo-200" : "text-gray-400"}`}>
                    {msg.timestamp.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}
                  </p>
                </div>
              </div>
            ))}

            {gptLoading && (
              <div className="flex justify-start">
                <div className="bg-gray-100 rounded-2xl px-4 py-3">
                  <div className="flex items-center gap-1">
                    <div className="h-2 w-2 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "0ms" }} />
                    <div className="h-2 w-2 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "150ms" }} />
                    <div className="h-2 w-2 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: "300ms" }} />
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Error */}
          {gptError && (
            <div className="mx-6 mb-2 rounded bg-red-50 p-2 text-xs text-red-700 border border-red-200">
              {gptError}
            </div>
          )}

          {/* Input */}
          <form onSubmit={handleGptSend} className="px-6 py-4 border-t border-gray-200">
            <div className="flex gap-3">
              <input
                value={gptInput}
                onChange={(e) => setGptInput(e.target.value)}
                placeholder="Ask your question..."
                disabled={gptLoading}
                className="flex-1 rounded-full border border-gray-300 px-4 py-2.5 text-sm focus:border-indigo-500 focus:outline-none disabled:opacity-50"
              />
              <button
                type="submit"
                disabled={gptLoading || !gptInput.trim()}
                className="rounded-full bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                Send
              </button>
            </div>
          </form>
        </div>
      )}

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
