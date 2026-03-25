"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import api from "@/lib/api";
import { isLoggedIn, removeToken } from "@/lib/auth";

interface UserInfo {
  id: string;
  email: string;
  full_name: string;
  role: string;
  phone: string | null;
  is_active: boolean;
}

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: "H" },
  { href: "/dashboard/cases", label: "Cases", icon: "C" },
  { href: "/dashboard/notifications", label: "Notifications", icon: "N" },
  { href: "/dashboard/ai", label: "AI Chat", icon: "A" },
  { href: "/dashboard/ip-agent", label: "IP Agent", icon: "I" },
];

const ADMIN_NAV_ITEMS = [
  { href: "/dashboard/users", label: "Users", icon: "U" },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<UserInfo | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  useEffect(() => {
    if (!isLoggedIn()) {
      router.push("/");
      return;
    }

    api
      .get("/auth/me")
      .then((res) => setUser(res.data))
      .catch(() => {
        removeToken();
        router.push("/");
      });
  }, [router]);

  function handleLogout() {
    removeToken();
    router.push("/");
  }

  const allNavItems =
    user?.role === "admin" ? [...NAV_ITEMS, ...ADMIN_NAV_ITEMS] : NAV_ITEMS;

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-gray-500">Loading...</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside
        className={`${sidebarOpen ? "w-60" : "w-16"} flex flex-col bg-gray-800 text-white transition-all duration-200`}
      >
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          {sidebarOpen && (
            <span className="text-lg font-bold">Etornie</span>
          )}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="rounded p-1 hover:bg-gray-700 text-gray-300"
            title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
          >
            {sidebarOpen ? "<" : ">"}
          </button>
        </div>

        <nav className="flex-1 p-2 space-y-1">
          {allNavItems.map((item) => {
            const isActive =
              item.href === "/dashboard"
                ? pathname === "/dashboard"
                : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 rounded px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-blue-600 text-white"
                    : "text-gray-300 hover:bg-gray-700 hover:text-white"
                }`}
              >
                <span className="flex h-6 w-6 items-center justify-center rounded bg-gray-600 text-xs font-bold">
                  {item.icon}
                </span>
                {sidebarOpen && <span>{item.label}</span>}
              </Link>
            );
          })}
        </nav>

        {/* User info */}
        <div className="border-t border-gray-700 p-4">
          {sidebarOpen && (
            <div className="mb-2">
              <p className="text-sm font-medium truncate">{user.full_name}</p>
              <p className="text-xs text-gray-400 truncate">{user.email}</p>
              <span className="mt-1 inline-block rounded-full bg-blue-500 px-2 py-0.5 text-xs font-medium">
                {user.role}
              </span>
            </div>
          )}
          <button
            onClick={handleLogout}
            className="w-full rounded bg-gray-700 px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-600 hover:text-white"
          >
            {sidebarOpen ? "Logout" : "X"}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <div className="p-6">{children}</div>
      </main>
    </div>
  );
}
