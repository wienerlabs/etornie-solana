"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import api from "@/lib/api";

interface MeResponse {
  id: string;
  role: string;
  email?: string | null;
}

const NAV: ReadonlyArray<{ href: string; label: string }> = [
  { href: "/dashboard/admin", label: "Overview" },
  { href: "/dashboard/admin/payments", label: "Payments" },
  { href: "/dashboard/admin/filings", label: "Filings" },
  { href: "/dashboard/admin/cases", label: "Cases" },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [status, setStatus] = useState<"checking" | "ok" | "denied">(
    "checking"
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<MeResponse>("/auth/me");
        if (cancelled) return;
        if (res.data?.role === "admin") {
          setStatus("ok");
        } else {
          setStatus("denied");
          router.replace("/dashboard");
        }
      } catch {
        if (cancelled) return;
        setStatus("denied");
        router.replace("/dashboard");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (status !== "ok") {
    return (
      <div className="flex h-full items-center justify-center p-12 text-sm text-gray-500">
        {status === "checking" ? "Checking admin access…" : "Access denied."}
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Admin</h1>
          <p className="text-sm text-gray-500">
            Operator panel — observability + manual recovery actions.
          </p>
        </div>
      </header>
      <nav className="mb-6 flex flex-wrap gap-2 border-b border-gray-200 pb-2">
        {NAV.map((n) => {
          const active =
            pathname === n.href ||
            (n.href !== "/dashboard/admin" && pathname?.startsWith(n.href));
          return (
            <Link
              key={n.href}
              href={n.href}
              className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                active
                  ? "bg-emerald-600 text-white"
                  : "text-gray-700 hover:bg-gray-100"
              }`}
            >
              {n.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}
