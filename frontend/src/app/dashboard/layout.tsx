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
  { href: "/dashboard/euipo", label: "EUIPO", icon: "E", roles: ["admin", "lawyer"] },
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
      router.push("/login");
      return;
    }

    api
      .get("/auth/me")
      .then((res) => setUser(res.data))
      .catch(() => {
        removeToken();
        router.push("/login");
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
    router.push("/login");
  }

  const allNavItems = NAV_ITEMS.filter((item) =>
    item.roles.includes(user?.role ?? "")
  );

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-[color:var(--color-muted)]">Loading...</p>
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
        className={`${sidebarOpen ? "w-64" : "w-16"} flex flex-col bg-[color:var(--color-espresso)] text-[color:var(--color-linen)] transition-all duration-200`}
      >
        <div className="flex items-center justify-between p-4 border-b border-[color:var(--color-espresso-soft)]">
          {sidebarOpen && (
            <div className="flex flex-col">
              <span className="text-base font-semibold tracking-tight">
                Etornie <span className="text-[color:var(--color-gold)]">Solana</span>
              </span>
              <span className="mt-0.5 flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-[color:var(--color-gold)]/70">
                <span className="chain-dot" />
                RWA Protocol
              </span>
            </div>
          )}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="rounded p-1 text-[color:var(--color-linen)]/70 hover:bg-[color:var(--color-espresso-soft)] hover:text-[color:var(--color-gold)]"
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
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-[color:var(--color-bronze)] text-[color:var(--color-cream)] shadow-[0_4px_12px_-6px_rgba(201,168,106,0.6)]"
                    : "text-[color:var(--color-linen)]/75 hover:bg-[color:var(--color-espresso-soft)] hover:text-[color:var(--color-gold)]"
                }`}
              >
                <span
                  className={`flex h-6 w-6 items-center justify-center rounded text-xs font-bold ${
                    isActive
                      ? "bg-[color:var(--color-cream)]/20 text-[color:var(--color-cream)]"
                      : "bg-[color:var(--color-espresso-soft)] text-[color:var(--color-gold)]"
                  }`}
                >
                  {item.icon}
                </span>
                {sidebarOpen && <span>{item.label}</span>}
              </Link>
            );
          })}
        </nav>

        {/* User info */}
        <div className="border-t border-[color:var(--color-espresso-soft)] p-4">
          {sidebarOpen && (
            <div className="mb-2">
              <p className="text-sm font-medium truncate text-[color:var(--color-cream)]">
                {user.full_name}
              </p>
              <p className="text-xs text-[color:var(--color-linen)]/60 truncate">
                {user.email}
              </p>
              <span className="mt-1.5 inline-block rounded-full border border-[color:var(--color-gold)]/40 bg-[color:var(--color-gold)]/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-gold)]">
                {user.role}
              </span>
            </div>
          )}
          <button
            onClick={handleLogout}
            className="w-full rounded-lg border border-[color:var(--color-espresso-soft)] bg-[color:var(--color-espresso-soft)] px-3 py-1.5 text-sm text-[color:var(--color-linen)]/80 hover:border-[color:var(--color-gold)]/40 hover:text-[color:var(--color-gold)]"
          >
            {sidebarOpen ? "Logout" : "X"}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        {/* Top bar with notification bell */}
        <div className="sticky top-0 z-30 flex items-center justify-between border-b border-[color:var(--color-stone)] bg-[color:var(--color-cream)]/90 px-6 py-3 backdrop-blur">
          <span className="chain-badge">
            <span className="chain-dot" />
            Solana · Devnet
          </span>
          <div className="relative">
            <button
              type="button"
              onClick={() => setBellOpen(!bellOpen)}
              className="relative rounded-full p-2 text-[color:var(--color-espresso)] hover:bg-[color:var(--color-sand)] transition-colors"
              title="Notifications"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
              </svg>
              {unreadCount > 0 && (
                <span className="absolute -top-0.5 -right-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-[color:var(--color-bronze)] text-[10px] font-bold text-[color:var(--color-cream)]">
                  {unreadCount > 99 ? "99+" : unreadCount}
                </span>
              )}
            </button>

            {bellOpen && (
              <>
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setBellOpen(false)}
                />
                <div className="absolute right-0 z-50 mt-2 w-96 overflow-hidden rounded-lg border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] shadow-xl">
                  <div className="flex items-center justify-between border-b border-[color:var(--color-stone)] bg-[color:var(--color-linen)] px-4 py-3">
                    <h3 className="text-sm font-semibold text-[color:var(--color-espresso)]">
                      Notifications
                    </h3>
                    {unreadCount > 0 && (
                      <button
                        type="button"
                        onClick={handleMarkAllRead}
                        className="text-xs font-medium text-[color:var(--color-bronze)] hover:text-[color:var(--color-bronze-dark)]"
                      >
                        Mark all as read
                      </button>
                    )}
                  </div>

                  <div className="max-h-96 overflow-y-auto">
                    {notifLoading ? (
                      <p className="p-4 text-center text-sm text-[color:var(--color-muted)]">
                        Loading...
                      </p>
                    ) : notifications.length === 0 ? (
                      <p className="p-4 text-center text-sm text-[color:var(--color-muted)]">
                        No notifications
                      </p>
                    ) : (
                      notifications.map((notif) => (
                        <button
                          key={notif.id}
                          type="button"
                          onClick={() => handleNotifClick(notif)}
                          className={`w-full border-b border-[color:var(--color-stone)]/60 px-4 py-3 text-left transition-colors hover:bg-[color:var(--color-sand)] ${
                            !notif.is_read ? "bg-[color:var(--color-linen)]" : ""
                          }`}
                        >
                          <div className="flex items-start gap-3">
                            <span className="mt-0.5 shrink-0 text-lg">
                              {NOTIF_TYPE_ICONS[notif.notification_type] ?? "🔔"}
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <p
                                  className={`truncate text-sm ${
                                    !notif.is_read
                                      ? "font-semibold text-[color:var(--color-espresso)]"
                                      : "text-[color:var(--color-ink)]/75"
                                  }`}
                                >
                                  {notif.title}
                                </p>
                                {!notif.is_read && (
                                  <span className="h-2 w-2 shrink-0 rounded-full bg-[color:var(--color-bronze)]" />
                                )}
                              </div>
                              <p className="mt-0.5 line-clamp-2 text-xs text-[color:var(--color-muted)]">
                                {notif.message}
                              </p>
                              <p className="mt-1 text-xs text-[color:var(--color-muted)]/80">
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
