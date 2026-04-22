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
      } catch {
        // errors handled by interceptor
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, []);

  if (loading) {
    return (
      <p className="text-[color:var(--color-muted)]">Loading dashboard...</p>
    );
  }

  const statCards: ReadonlyArray<{
    key: string;
    label: string;
    value: number | string;
    accent: string;
    sub?: string;
  }> = [
    {
      key: "total",
      label: "Total Cases",
      value: casesTotal,
      accent: "from-[color:var(--color-bronze)] to-[color:var(--color-bronze-dark)]",
      sub: "Portfolio size",
    },
    {
      key: "open",
      label: "Open",
      value: statusCounts.open,
      accent: "from-[color:var(--color-solana-purple)] to-[#6b2dc4]",
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
      accent: "from-[color:var(--color-solana-green)] to-[#0e7a4f]",
      sub: "Attested on-chain",
    },
    {
      key: "deadlines",
      label: "Upcoming (30d)",
      value: upcomingDeadlines,
      accent: "from-[color:var(--color-bronze-dark)] to-[#3c2a18]",
      sub: "Deadlines",
    },
  ];

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[color:var(--color-espresso)]">
            Dashboard
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

      {/* User info card */}
      {user && (
        <div className="rwa-card mb-8 p-6">
          <h2 className="mb-4 text-lg font-semibold text-[color:var(--color-espresso)]">
            Welcome, {user.full_name}
          </h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <InfoField label="Email" value={user.email} mono />
            <InfoField
              label="Role"
              value={
                <span className="inline-block rounded-full border border-[color:var(--color-gold)]/50 bg-[color:var(--color-linen)] px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-[color:var(--color-bronze-dark)]">
                  {user.role}
                </span>
              }
            />
            <InfoField label="Phone" value={user.phone ?? "N/A"} />
            <InfoField
              label="Status"
              value={
                <span
                  className={`status-pill ${
                    user.is_active ? "status-done" : "status-review"
                  }`}
                >
                  {user.is_active ? "Active" : "Inactive"}
                </span>
              }
            />
          </div>
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {statCards.map((card) => (
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
            {card.sub && (
              <p className="mt-1 text-xs text-[color:var(--color-muted)]">
                {card.sub}
              </p>
            )}
          </div>
        ))}
      </div>

      {user && (
        <div className="rwa-card mt-8 flex items-center justify-between p-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
              Member since
            </p>
            <p className="mt-1 text-base font-medium text-[color:var(--color-espresso)]">
              {new Date(user.created_at).toLocaleDateString()}
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
              Protocol
            </p>
            <p className="mt-1 text-sm font-mono text-[color:var(--color-bronze-dark)]">
              etornie.sol / v0.1.0
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function InfoField({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
        {label}
      </p>
      <div
        className={`mt-1 text-sm font-medium text-[color:var(--color-ink)] ${
          mono ? "font-mono" : ""
        }`}
      >
        {value}
      </div>
    </div>
  );
}
