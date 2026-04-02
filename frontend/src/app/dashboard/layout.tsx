"use client";

import { useEffect, useState, useCallback } from "react";
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

interface NavItem {
  href: string;
  label: string;
  icon: string;
  roles: string[];
}

interface InAppNotification {
  id: string;
  notification_type: string;
  title: string;
  message: string;
  case_id: string | null;
  is_read: boolean;
  created_at: string;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: "H", roles: ["admin", "lawyer", "client"] },
  { href: "/dashboard/cases", label: "Cases", icon: "C", roles: ["admin", "lawyer", "client"] },
  { href: "/dashboard/notifications", label: "Notifications", icon: "N", roles: ["admin", "lawyer"] },
  { href: "/dashboard/ai", label: "AI Chat", icon: "A", roles: ["admin", "lawyer", "client"] },
  { href: "/dashboard/ip-agent", label: "IP Agent", icon: "I", roles: ["admin"] },
  { href: "/dashboard/users", label: "Users", icon: "U", roles: ["admin"] },
];

const NOTIF_TYPE_ICONS: Record<string, string> = {
  document_uploaded: "📄",
  document_approved: "✅",
  document_rejected: "❌",
  note_added: "📝",
  case_updated: "📋",
  case_created: "🆕",
};

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<UserInfo | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // Notification state
  const [unreadCount, setUnreadCount] = useState(0);
  const [notifications, setNotifications] = useState<InAppNotification[]>([]);
  const [bellOpen, setBellOpen] = useState(false);
  const [notifLoading, setNotifLoading] = useState(false);

  const fetchUnreadCount = useCallback(async () => {
    try {
      const res = await api.get<{ unread_count: number }>("/in-app-notifications/unread-count");
      setUnreadCount(res.data.unread_count);
    } catch {
      // silently fail
    }
  }, []);

  const fetchNotifications = useCallback(async () => {
    setNotifLoading(true);
    try {
      const res = await api.get<{ notifications: InAppNotification[]; unread_count: number }>(
        "/in-app-notifications?limit=20"
      );
      setNotifications(res.data.notifications);
      setUnreadCount(res.data.unread_count);
    } catch {
      // silently fail
    } finally {
      setNotifLoading(false);
    }
  }, []);

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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll unread count every 30 seconds
  useEffect(() => {
    if (!user) return;
    fetchUnreadCount();
    const interval = setInterval(fetchUnreadCount, 30000);
    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!user]);

  // Fetch full list when bell opened
  useEffect(() => {
    if (bellOpen) {
      fetchNotifications();
    }
  }, [bellOpen, fetchNotifications]);

  async function handleMarkAllRead() {
    try {
      await api.patch("/in-app-notifications/read-all");
      setUnreadCount(0);
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
    } catch {
      // silently fail
    }
  }

  async function handleMarkOneRead(notifId: string) {
    try {
      await api.patch(`/in-app-notifications/${notifId}/read`);
      setNotifications((prev) =>
        prev.map((n) => (n.id === notifId ? { ...n, is_read: true } : n))
      );
      setUnreadCount((prev) => Math.max(0, prev - 1));
    } catch {
      // silently fail
    }
  }

  function handleNotifClick(notif: InAppNotification) {
    if (!notif.is_read) {
      handleMarkOneRead(notif.id);
    }
    setBellOpen(false);
    if (notif.case_id) {
      router.push(`/dashboard/cases/${notif.case_id}`);
    }
  }

  function handleLogout() {
    removeToken();
    router.push("/");
  }

  const allNavItems = NAV_ITEMS.filter((item) =>
    item.roles.includes(user?.role ?? "")
  );

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-gray-500">Loading...</p>
      </div>
    );
  }

  function timeAgo(dateStr: string): string {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "Just now";
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
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
        {/* Top bar with notification bell */}
        <div className="sticky top-0 z-30 flex items-center justify-end bg-white border-b border-gray-200 px-6 py-3">
          <div className="relative">
            <button
              type="button"
              onClick={() => setBellOpen(!bellOpen)}
              className="relative rounded-full p-2 text-gray-600 hover:bg-gray-100 hover:text-gray-800 transition-colors"
              title="Notifications"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
              </svg>
              {unreadCount > 0 && (
                <span className="absolute -top-0.5 -right-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-red-500 text-xs font-bold text-white">
                  {unreadCount > 99 ? "99+" : unreadCount}
                </span>
              )}
            </button>

            {/* Notification dropdown */}
            {bellOpen && (
              <>
                {/* Backdrop */}
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setBellOpen(false)}
                />
                <div className="absolute right-0 z-50 mt-2 w-96 rounded-lg bg-white shadow-xl border border-gray-200 overflow-hidden">
                  <div className="flex items-center justify-between px-4 py-3 bg-gray-50 border-b border-gray-200">
                    <h3 className="text-sm font-semibold text-gray-700">Notifications</h3>
                    {unreadCount > 0 && (
                      <button
                        type="button"
                        onClick={handleMarkAllRead}
                        className="text-xs text-blue-600 hover:text-blue-800 font-medium"
                      >
                        Mark all as read
                      </button>
                    )}
                  </div>

                  <div className="max-h-96 overflow-y-auto">
                    {notifLoading ? (
                      <p className="p-4 text-sm text-gray-400 text-center">Loading...</p>
                    ) : notifications.length === 0 ? (
                      <p className="p-4 text-sm text-gray-400 text-center">No notifications</p>
                    ) : (
                      notifications.map((notif) => (
                        <button
                          key={notif.id}
                          type="button"
                          onClick={() => handleNotifClick(notif)}
                          className={`w-full text-left px-4 py-3 border-b border-gray-100 hover:bg-gray-50 transition-colors ${
                            !notif.is_read ? "bg-blue-50" : ""
                          }`}
                        >
                          <div className="flex items-start gap-3">
                            <span className="text-lg shrink-0 mt-0.5">
                              {NOTIF_TYPE_ICONS[notif.notification_type] ?? "🔔"}
                            </span>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <p className={`text-sm truncate ${!notif.is_read ? "font-semibold text-gray-800" : "text-gray-600"}`}>
                                  {notif.title}
                                </p>
                                {!notif.is_read && (
                                  <span className="h-2 w-2 rounded-full bg-blue-500 shrink-0" />
                                )}
                              </div>
                              <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">
                                {notif.message}
                              </p>
                              <p className="text-xs text-gray-400 mt-1">
                                {timeAgo(notif.created_at)}
                              </p>
                            </div>
                          </div>
                        </button>
                      ))
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        <div className="p-6">{children}</div>
      </main>
    </div>
  );
}
