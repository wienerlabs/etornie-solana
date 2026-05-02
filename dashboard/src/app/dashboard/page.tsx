"use client";

import { useEffect, useState } from "react";
import api from "@/lib/api";

interface UserInfo {
  id: string;
  email: string;
  full_name: string;
  role: string;
  phone: string | null;
  is_active: boolean;
  created_at: string;
}

interface CaseListResponse {
  cases: Array<{
    id: string;
    title: string;
    deadline: string | null;
    status: string;
  }>;
  total: number;
}

interface StatusCounts {
  open: number;
  in_progress: number;
  under_review: number;
  closed: number;
}

const ZERO_STATUS: StatusCounts = {
  open: 0,
  in_progress: 0,
  under_review: 0,
  closed: 0,
};

export default function DashboardPage() {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [casesTotal, setCasesTotal] = useState<number>(0);
  const [statusCounts, setStatusCounts] = useState<StatusCounts>(ZERO_STATUS);
  const [upcomingDeadlines, setUpcomingDeadlines] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const [userRes, casesRes] = await Promise.all([
          api.get("/auth/me"),
          api.get("/cases", { params: { limit: 100 } }),
        ]);

        setUser(userRes.data);

        const casesData: CaseListResponse = casesRes.data;
        setCasesTotal(casesData.total);

        const counts: StatusCounts = { ...ZERO_STATUS };
        for (const c of casesData.cases) {
          if (c.status in counts) {
            counts[c.status as keyof StatusCounts] += 1;
          }
        }
        setStatusCounts(counts);

        const now = new Date();
        const thirtyDaysLater = new Date(
          now.getTime() + 30 * 24 * 60 * 60 * 1000
        );
        const deadlineCount = casesData.cases.filter((c) => {
          if (!c.deadline) return false;
          const d = new Date(c.deadline);
          return d >= now && d <= thirtyDaysLater;
        }).length;
        setUpcomingDeadlines(deadlineCount);
      } catch (err: unknown) {
        const message =
          (err as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail ?? "Could not load dashboard data. Please try again.";
        setError(message);
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, []);

  if (loading) {
    return <DashboardSkeleton />;
  }

  if (error) {
    return (
      <div className="rwa-card flex flex-col items-start gap-3 border-red-300 bg-red-50 p-6">
        <div className="flex items-center gap-2 text-red-800">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={1.75}
            stroke="currentColor"
            className="h-5 w-5"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
            />
          </svg>
          <p className="font-semibold">Dashboard could not load</p>
        </div>
        <p className="text-sm text-red-800/90">{error}</p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="rwa-btn-secondary text-sm"
        >
          Retry
        </button>
      </div>
    );
  }

  const statusCards: ReadonlyArray<{
    key: string;
    label: string;
    value: number;
    accent: string;
    sub: string;
  }> = [
    {
      key: "open",
      label: "Open",
      value: statusCounts.open,
      accent: "from-[color:var(--color-graphite)] to-[color:var(--color-inkwell)]",
      sub: "Awaiting action",
    },
    {
      key: "in_progress",
      label: "In Progress",
      value: statusCounts.in_progress,
      accent: "from-[color:var(--color-gold)] to-[color:var(--color-bronze)]",
      sub: "Under work",
    },
    {
      key: "under_review",
      label: "Under Review",
      value: statusCounts.under_review,
      accent: "from-[color:var(--color-bronze)] to-[color:var(--color-espresso)]",
      sub: "Pending validation",
    },
    {
      key: "closed",
      label: "Completed",
      value: statusCounts.closed,
      accent: "from-[color:var(--color-graphite)] to-[color:var(--color-inkwell)]",
      sub: "Attested on-chain",
    },
  ];

  const hasUrgentDeadlines = upcomingDeadlines > 0;

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[color:var(--color-espresso)]">
            {user ? `Welcome, ${user.full_name.split(" ")[0]}` : "Dashboard"}
          </h1>
          <p className="mt-1 text-sm text-[color:var(--color-muted)]">
            Portfolio overview of tokenized IP & RWA cases
          </p>
        </div>
        <span className="chain-badge">
          <span className="chain-dot" />
          Solana · Devnet
        </span>
      </div>

      {/* Highlight row: portfolio total + upcoming deadlines */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rwa-card relative overflow-hidden p-6">
          <div
            className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-[color:var(--color-bronze)] to-[color:var(--color-bronze-dark)]"
            aria-hidden="true"
          />
          <p className="text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
            Total Cases
          </p>
          <p className="mt-3 text-4xl font-semibold text-[color:var(--color-espresso)]">
            {casesTotal}
          </p>
          <p className="mt-1 text-xs text-[color:var(--color-muted)]">
            Portfolio size
          </p>
        </div>
        <div
          className={`rwa-card relative overflow-hidden p-6 ${
            hasUrgentDeadlines ? "ring-2 ring-[color:var(--color-bronze)]/40" : ""
          }`}
        >
          <div
            className={`absolute inset-x-0 top-0 h-1 bg-gradient-to-r ${
              hasUrgentDeadlines
                ? "from-red-500 to-[color:var(--color-bronze-dark)]"
                : "from-[color:var(--color-stone-deep)] to-[color:var(--color-stone)]"
            }`}
            aria-hidden="true"
          />
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
              Upcoming Deadlines (30d)
            </p>
            {hasUrgentDeadlines && (
              <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-red-800">
                Action needed
              </span>
            )}
          </div>
          <p className="mt-3 text-4xl font-semibold text-[color:var(--color-espresso)]">
            {upcomingDeadlines}
          </p>
          <p className="mt-1 text-xs text-[color:var(--color-muted)]">
            {hasUrgentDeadlines
              ? `${upcomingDeadlines === 1 ? "1 case needs" : `${upcomingDeadlines} cases need`} attention soon`
              : "Nothing urgent in the next 30 days"}
          </p>
        </div>
      </div>

      {/* Status breakdown */}
      <div>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
          Status breakdown
        </h2>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {statusCards.map((card) => (
            <div
              key={card.key}
              className="rwa-card relative overflow-hidden p-5"
            >
              <div
                className={`absolute inset-x-0 top-0 h-1 bg-gradient-to-r ${card.accent}`}
                aria-hidden="true"
              />
              <p className="text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                {card.label}
              </p>
              <p className="mt-3 text-3xl font-semibold text-[color:var(--color-espresso)]">
                {card.value}
              </p>
              <p className="mt-1 text-xs text-[color:var(--color-muted)]">
                {card.sub}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-8" aria-busy="true" aria-label="Loading dashboard">
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <div className="h-7 w-56 animate-pulse rounded bg-[color:var(--color-stone)]/60" />
          <div className="h-4 w-72 animate-pulse rounded bg-[color:var(--color-stone)]/40" />
        </div>
        <div className="h-6 w-32 animate-pulse rounded-full bg-[color:var(--color-stone)]/60" />
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {[0, 1].map((i) => (
          <div key={i} className="rwa-card p-6">
            <div className="h-3 w-24 animate-pulse rounded bg-[color:var(--color-stone)]/60" />
            <div className="mt-3 h-10 w-20 animate-pulse rounded bg-[color:var(--color-stone)]/60" />
            <div className="mt-2 h-3 w-32 animate-pulse rounded bg-[color:var(--color-stone)]/40" />
          </div>
        ))}
      </div>
      <div>
        <div className="mb-3 h-3 w-32 animate-pulse rounded bg-[color:var(--color-stone)]/60" />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="rwa-card p-5">
              <div className="h-3 w-20 animate-pulse rounded bg-[color:var(--color-stone)]/60" />
              <div className="mt-3 h-8 w-14 animate-pulse rounded bg-[color:var(--color-stone)]/60" />
              <div className="mt-1 h-3 w-24 animate-pulse rounded bg-[color:var(--color-stone)]/40" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
