"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import api from "@/lib/api";
import { isLoggedIn, removeToken } from "@/lib/auth";
import { OrgSwitcher } from "@/components/OrgSwitcher";

function EtornieLogoMark({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 400 400"
      fill="none"
      stroke="currentColor"
      strokeWidth={16}
      strokeLinecap="butt"
      className={className}
      aria-hidden="true"
    >
      <rect x="186" y="130" width="28" height="140" />
      <line x1="80" y1="165" x2="178" y2="200" />
      <line x1="80" y1="235" x2="178" y2="200" />
      <line x1="80" y1="200" x2="178" y2="200" />
      <line x1="320" y1="165" x2="222" y2="200" />
      <line x1="320" y1="235" x2="222" y2="200" />
      <line x1="320" y1="200" x2="222" y2="200" />
    </svg>
  );
}

type IconKey =
  | "home"
  | "briefcase"
  | "bell"
  | "chat"
  | "sparkles"
  | "shield"
  | "cpu"
  | "users"
  | "lock"
  | "network"
  | "profile";

const ICONS: Record<IconKey, string> = {
  home: "M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75",
  briefcase:
    "M20.25 14.15v4.075a2.25 2.25 0 01-2.25 2.25h-12a2.25 2.25 0 01-2.25-2.25v-4.073M20.25 14.15a24.5 24.5 0 01-8.25 1.4 24.5 24.5 0 01-8.25-1.4M20.25 14.15v-2.65a2.25 2.25 0 00-2.25-2.25h-3a3 3 0 00-3-3h-2a3 3 0 00-3 3h-3a2.25 2.25 0 00-2.25 2.25v2.65",
  bell: "M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0",
  chat: "M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375m-13.5 3.01c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.184-4.183a1.14 1.14 0 01.778-.332 48.294 48.294 0 005.83-.498c1.585-.233 2.708-1.626 2.708-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z",
  sparkles:
    "M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z",
  shield:
    "M9 12.75L11.25 15 15 9.75M21 12c0 1.268-.63 2.39-1.593 3.068a3.745 3.745 0 01-1.043 3.296 3.745 3.745 0 01-3.296 1.043A3.745 3.745 0 0112 21c-1.268 0-2.39-.63-3.068-1.593a3.746 3.746 0 01-3.296-1.043 3.745 3.745 0 01-1.043-3.296A3.745 3.745 0 013 12c0-1.268.63-2.39 1.593-3.068a3.745 3.745 0 011.043-3.296 3.746 3.746 0 013.296-1.043A3.746 3.746 0 0112 3c1.268 0 2.39.63 3.068 1.593a3.746 3.746 0 013.296 1.043 3.746 3.746 0 011.043 3.296A3.745 3.745 0 0121 12z",
  cpu: "M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 002.25-2.25V6.75a2.25 2.25 0 00-2.25-2.25H6.75A2.25 2.25 0 004.5 6.75v10.5a2.25 2.25 0 002.25 2.25zm.75-12h9v9h-9v-9z",
  users:
    "M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z",
  lock: "M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z",
  network:
    "M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z",
  profile:
    "M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z",
};

interface UserInfo {
  id: string;
  email: string | null;
  full_name: string;
  role: string;
  phone: string | null;
  is_active: boolean;
  wallet_address: string | null;
  public_handle: string | null;
  auth_method: string;
  default_organization_id: string | null;
}

interface NavItem {
  href: string;
  label: string;
  icon: IconKey;
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
  { href: "/dashboard", label: "Dashboard", icon: "home", roles: ["admin", "client"] },
  { href: "/dashboard/cases", label: "Cases", icon: "briefcase", roles: ["admin", "client"] },
  { href: "/dashboard/notifications", label: "Notifications", icon: "bell", roles: ["admin"] },
  { href: "/dashboard/etorniegpt", label: "EtornieGPT", icon: "sparkles", roles: ["admin", "client"] },
  { href: "/dashboard/organizations", label: "Organizations", icon: "users", roles: ["admin", "client"] },
  { href: "/dashboard/profile", label: "Profile", icon: "profile", roles: ["admin", "client"] },
  { href: "/dashboard/users", label: "Users", icon: "users", roles: ["admin"] },
  { href: "/dashboard/admin", label: "Admin Panel", icon: "shield", roles: ["admin"] },
  { href: "/dashboard/braid", label: "BRAID", icon: "network", roles: ["admin"] },
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
      <div className="flex min-h-screen items-center justify-center bg-[color:var(--color-paper-white)]">
        <p className="text-[color:var(--color-dusk-gray)]">Loading...</p>
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
    <div className="flex min-h-screen bg-[color:var(--color-paper-white)]">
      {/* Sidebar — Perplexity style: light Paper White surface */}
      <aside
        className={`${sidebarOpen ? "w-64" : "w-16"} flex flex-col bg-[color:var(--color-paper-white)] text-[color:var(--color-graphite)] border-r border-[color:var(--color-divider)] transition-all duration-200`}
      >
        <div className="flex items-center justify-between p-4 border-b border-[color:var(--color-divider)]">
          {sidebarOpen ? (
            <div className="flex items-center gap-2.5">
              <EtornieLogoMark className="h-8 w-8 shrink-0 text-[color:var(--color-inkwell)]" />
              <div className="flex flex-col">
                <span className="text-base font-medium tracking-tight text-[color:var(--color-inkwell)]">
                  Etornie
                </span>
                <span className="mt-0.5 flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-[color:var(--color-dusk-gray)]">
                  <span className="chain-dot" />
                  RWA Protocol
                </span>
              </div>
            </div>
          ) : (
            <EtornieLogoMark className="h-7 w-7 text-[color:var(--color-inkwell)]" />
          )}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="rounded-full p-1 text-[color:var(--color-dusk-gray)] hover:bg-[color:var(--color-parchment)] hover:text-[color:var(--color-inkwell)]"
            title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
            aria-label={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
          >
            {sidebarOpen ? "‹" : "›"}
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
                className={`flex items-center gap-3 rounded-lg px-3 py-1 text-base transition-colors ${
                  isActive
                    ? "bg-[color:var(--color-accent-soft)] text-[color:var(--color-accent)]"
                    : "text-[color:var(--color-inkwell)] hover:bg-[color:var(--color-elevated)] hover:text-[color:var(--color-inkwell)]"
                }`}
              >
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center ${
                    isActive
                      ? "text-[color:var(--color-accent)]"
                      : "text-[color:var(--color-dusk-gray)]"
                  }`}
                  aria-hidden="true"
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={1.75}
                    stroke="currentColor"
                    className="h-5 w-5"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d={ICONS[item.icon]}
                    />
                  </svg>
                </span>
                {sidebarOpen && <span>{item.label}</span>}
              </Link>
            );
          })}
        </nav>

        {/* User info */}
        <div className="border-t border-[color:var(--color-divider)] p-4">
          {sidebarOpen && (
            <div className="mb-2">
              <p className="text-sm font-medium truncate text-[color:var(--color-inkwell)]">
                {user.full_name}
              </p>
              {user.email && (
                <p className="text-xs text-[color:var(--color-dusk-gray)] truncate">
                  {user.email}
                </p>
              )}
              {user.public_handle && (
                <p
                  className="mt-0.5 truncate font-mono text-[11px] text-[color:var(--color-faded-stone)]"
                  title={user.wallet_address ?? user.public_handle}
                >
                  {user.public_handle}
                </p>
              )}
              <span className="mt-1.5 inline-block rounded-full border border-[color:var(--color-accent-soft)] bg-[color:var(--color-accent-soft)] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-[color:var(--color-accent)]">
                {user.role}
                {user.auth_method === "wallet" ? " · wallet" : ""}
              </span>
            </div>
          )}
          <button
            onClick={handleLogout}
            className="flex w-full items-center justify-center gap-2 rounded-full border border-[color:var(--color-divider)] bg-[color:var(--color-parchment)] px-3 py-1.5 text-sm text-[color:var(--color-graphite)] hover:bg-[color:var(--color-parchment-deep)] hover:text-[color:var(--color-inkwell)]"
            aria-label="Logout"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.75}
              stroke="currentColor"
              className="h-4 w-4"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75"
              />
            </svg>
            {sidebarOpen && <span>Logout</span>}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto bg-[color:var(--color-paper-white)]">
        {/* Top bar with notification bell */}
        <div className="sticky top-0 z-30 flex items-center justify-between border-b border-[color:var(--color-divider)] bg-[color:var(--color-paper-white)]/95 px-6 py-3 backdrop-blur">
          <span className="chain-badge">
            <span className="chain-dot" />
            Solana · Devnet
          </span>
          <div className="flex items-center gap-3">
            <OrgSwitcher currentOrgId={user.default_organization_id} />
          <div className="relative">
            <button
              type="button"
              onClick={() => setBellOpen(!bellOpen)}
              className="relative rounded-full p-2 text-[color:var(--color-graphite)] hover:bg-[color:var(--color-parchment)] transition-colors"
              title="Notifications"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
              </svg>
              {unreadCount > 0 && (
                <span className="absolute -top-0.5 -right-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-[color:var(--color-inkwell)] text-[10px] font-medium text-[color:var(--color-paper-white)]">
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
                <div className="absolute right-0 z-50 mt-2 w-96 overflow-hidden rounded-2xl border border-[color:var(--color-divider)] bg-[color:var(--color-paper-white)]">
                  <div className="flex items-center justify-between border-b border-[color:var(--color-divider)] bg-[color:var(--color-parchment)] px-4 py-3">
                    <h3 className="text-sm font-medium text-[color:var(--color-inkwell)]">
                      Notifications
                    </h3>
                    {unreadCount > 0 && (
                      <button
                        type="button"
                        onClick={handleMarkAllRead}
                        className="text-xs font-medium text-[color:var(--color-graphite)] hover:text-[color:var(--color-inkwell)]"
                      >
                        Mark all as read
                      </button>
                    )}
                  </div>

                  <div className="max-h-96 overflow-y-auto">
                    {notifLoading ? (
                      <p className="p-4 text-center text-sm text-[color:var(--color-dusk-gray)]">
                        Loading...
                      </p>
                    ) : notifications.length === 0 ? (
                      <p className="p-4 text-center text-sm text-[color:var(--color-dusk-gray)]">
                        No notifications
                      </p>
                    ) : (
                      notifications.map((notif) => (
                        <button
                          key={notif.id}
                          type="button"
                          onClick={() => handleNotifClick(notif)}
                          className={`w-full border-b border-[color:var(--color-divider)] px-4 py-3 text-left transition-colors hover:bg-[color:var(--color-parchment)] ${
                            !notif.is_read ? "bg-[color:var(--color-parchment)]" : ""
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
                                      ? "font-medium text-[color:var(--color-inkwell)]"
                                      : "text-[color:var(--color-graphite)]"
                                  }`}
                                >
                                  {notif.title}
                                </p>
                                {!notif.is_read && (
                                  <span className="h-2 w-2 shrink-0 rounded-full bg-[color:var(--color-inkwell)]" />
                                )}
                              </div>
                              <p className="mt-0.5 line-clamp-2 text-xs text-[color:var(--color-dusk-gray)]">
                                {notif.message}
                              </p>
                              <p className="mt-1 text-xs text-[color:var(--color-faded-stone)]">
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
        </div>

        <div className="p-6">{children}</div>
      </main>
    </div>
  );
}
