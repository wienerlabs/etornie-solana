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

export default function DashboardPage() {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [casesTotal, setCasesTotal] = useState<number>(0);
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
    return <p className="text-gray-500">Loading dashboard...</p>;
  }

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold text-gray-800">Dashboard</h1>

      {/* User info card */}
      {user && (
        <div className="mb-8 rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <h2 className="mb-4 text-lg font-semibold text-gray-700">
            Welcome, {user.full_name}
          </h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <p className="text-xs text-gray-500 uppercase">Email</p>
              <p className="text-sm font-medium">{user.email}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase">Role</p>
              <span className="inline-block mt-1 rounded-full bg-blue-100 text-blue-800 px-2.5 py-0.5 text-xs font-medium">
                {user.role}
              </span>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase">Phone</p>
              <p className="text-sm font-medium">{user.phone ?? "N/A"}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase">Status</p>
              <span
                className={`inline-block mt-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${
                  user.is_active
                    ? "bg-green-100 text-green-800"
                    : "bg-red-100 text-red-800"
                }`}
              >
                {user.is_active ? "Active" : "Inactive"}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Quick stats */}
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
        <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <p className="text-sm text-gray-500">Total Cases</p>
          <p className="mt-2 text-3xl font-bold text-gray-800">{casesTotal}</p>
        </div>
        <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <p className="text-sm text-gray-500">Upcoming Deadlines (30 days)</p>
          <p className="mt-2 text-3xl font-bold text-orange-600">
            {upcomingDeadlines}
          </p>
        </div>
        <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200">
          <p className="text-sm text-gray-500">Member Since</p>
          <p className="mt-2 text-lg font-semibold text-gray-800">
            {user
              ? new Date(user.created_at).toLocaleDateString()
              : "N/A"}
          </p>
        </div>
      </div>
    </div>
  );
}
