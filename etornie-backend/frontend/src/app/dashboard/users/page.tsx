"use client";

import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";

interface UserItem {
  id: string;
  email: string | null;
  full_name: string;
  phone: string | null;
  role: string;
  is_active: boolean;
  is_verified: boolean;
  bar_association: string | null;
  bar_number: string | null;
  wallet_address: string | null;
  public_handle: string | null;
  auth_method: string;
  created_at: string;
  updated_at: string;
}

interface UserListResponse {
  users: UserItem[];
  total: number;
}

type FilterKey = "all" | "admin" | "lawyer" | "client" | "pending";

const FILTER_TABS: ReadonlyArray<{ key: FilterKey; label: string }> = [
  { key: "all", label: "All" },
  { key: "admin", label: "Admins" },
  { key: "lawyer", label: "Lawyers" },
  { key: "client", label: "Clients" },
  { key: "pending", label: "Pending" },
];

const ROLE_PILL: Record<string, string> = {
  admin: "bg-[color:var(--color-linen)] text-[color:var(--color-bronze-dark)] border border-[color:var(--color-gold)]/50",
  lawyer: "bg-[color:var(--color-status-open-bg)] text-[color:var(--color-status-open-fg)]",
  client: "bg-[color:var(--color-status-done-bg)] text-[color:var(--color-status-done-fg)]",
};

export default function UsersPage() {
  const [users, setUsers] = useState<UserItem[]>([]);
  const [total, setTotal] = useState(0);
  const [pendingCount, setPendingCount] = useState(0);
  const [activeFilter, setActiveFilter] = useState<FilterKey>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [selectedUser, setSelectedUser] = useState<UserItem | null>(null);
  const [editForm, setEditForm] = useState({
    full_name: "",
    email: "",
    phone: "",
    role: "",
    is_active: true,
  });
  const [editLoading, setEditLoading] = useState(false);
  const [verifyLoading, setVerifyLoading] = useState(false);
  const [editError, setEditError] = useState("");
  const [editSuccess, setEditSuccess] = useState("");

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params: Record<string, string | number> = { limit: 100 };
      if (activeFilter === "pending") {
        params.verification_status = "pending";
      }

      const res = await api.get<UserListResponse>("/users", { params });
      let list = res.data.users;
      if (
        activeFilter === "admin" ||
        activeFilter === "lawyer" ||
        activeFilter === "client"
      ) {
        list = list.filter((u) => u.role === activeFilter);
      }
      setUsers(list);
      setTotal(res.data.total);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to load users. Admin access required.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [activeFilter]);

  const fetchPendingCount = useCallback(async () => {
    try {
      const res = await api.get<UserListResponse>("/users", {
        params: { limit: 1, verification_status: "pending" },
      });
      setPendingCount(res.data.total);
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  useEffect(() => {
    fetchPendingCount();
  }, [fetchPendingCount, users]);

  function handleSelectUser(u: UserItem) {
    setSelectedUser(u);
    setEditForm({
      full_name: u.full_name,
      email: u.email ?? "",
      phone: u.phone ?? "",
      role: u.role,
      is_active: u.is_active,
    });
    setEditError("");
    setEditSuccess("");
  }

  async function handleEditUser() {
    if (!selectedUser) return;
    setEditLoading(true);
    setEditError("");
    setEditSuccess("");
    try {
      await api.patch(`/users/${selectedUser.id}`, {
        full_name: editForm.full_name,
        email: editForm.email || null,
        phone: editForm.phone || null,
        role: editForm.role,
        is_active: editForm.is_active,
      });
      setEditSuccess("User updated.");
      await fetchUsers();
      await fetchPendingCount();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to update user.";
      setEditError(message);
    } finally {
      setEditLoading(false);
    }
  }

  async function handleVerify(user: UserItem, verify: boolean) {
    setVerifyLoading(true);
    setEditError("");
    setEditSuccess("");
    try {
      const endpoint = verify ? "verify" : "reject";
      await api.post(`/users/${user.id}/${endpoint}`);
      setEditSuccess(verify ? "User verified." : "Verification revoked.");
      await fetchUsers();
      await fetchPendingCount();
      if (selectedUser?.id === user.id) {
        setSelectedUser((prev) =>
          prev ? { ...prev, is_verified: verify } : prev
        );
      }
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Action failed.";
      setEditError(message);
    } finally {
      setVerifyLoading(false);
    }
  }

  return (
    <div>
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[color:var(--color-espresso)]">
            Users
          </h1>
          <p className="mt-1 text-sm text-[color:var(--color-muted)]">
            Manage members, roles, and lawyer verification.
          </p>
        </div>
        <span className="text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
          Total {total}
        </span>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </div>
      )}

      <div className="mb-4 flex flex-wrap gap-2">
        {FILTER_TABS.map((tab) => {
          const active = activeFilter === tab.key;
          const showBadge = tab.key === "pending" && pendingCount > 0;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveFilter(tab.key)}
              className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold transition-all ${
                active
                  ? "bg-[color:var(--color-espresso)] text-[color:var(--color-cream)]"
                  : "border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] text-[color:var(--color-espresso)] hover:border-[color:var(--color-gold)] hover:bg-[color:var(--color-sand)]"
              }`}
            >
              {tab.label}
              {showBadge && (
                <span
                  className={`inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] ${
                    active
                      ? "bg-[color:var(--color-gold)] text-[color:var(--color-espresso)]"
                      : "bg-[color:var(--color-bronze)] text-[color:var(--color-cream)]"
                  }`}
                >
                  {pendingCount}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div className="flex gap-6">
        <div className="flex-1">
          {loading ? (
            <p className="text-[color:var(--color-muted)]">Loading users...</p>
          ) : users.length === 0 ? (
            <p className="text-[color:var(--color-muted)]">
              {activeFilter === "pending"
                ? "No pending verifications."
                : "No users found."}
            </p>
          ) : (
            <div className="rwa-card overflow-x-auto p-0">
              <table className="min-w-full">
                <thead className="border-b border-[color:var(--color-stone)] bg-[color:var(--color-sand)]/50">
                  <tr>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                      Name
                    </th>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                      Identity
                    </th>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                      Role
                    </th>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                      Verified
                    </th>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[color:var(--color-stone)]/60">
                  {users.map((u) => {
                    const isPendingLawyer =
                      u.role === "lawyer" && !u.is_verified;
                    return (
                      <tr
                        key={u.id}
                        className="hover:bg-[color:var(--color-sand)]/40"
                      >
                        <td
                          className="cursor-pointer px-4 py-3 text-sm font-medium text-[color:var(--color-espresso)]"
                          onClick={() => handleSelectUser(u)}
                        >
                          {u.full_name}
                          {u.auth_method === "wallet" && (
                            <span className="ml-2 text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-bronze)]">
                              wallet
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-xs text-[color:var(--color-muted)]">
                          {u.email && <div>{u.email}</div>}
                          {u.public_handle && (
                            <div className="font-mono text-[color:var(--color-bronze-dark)]">
                              {u.public_handle}
                            </div>
                          )}
                          {u.bar_association && (
                            <div className="mt-0.5 text-[11px]">
                              {u.bar_association}
                              {u.bar_number ? ` · ${u.bar_number}` : ""}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3 text-sm">
                          <span
                            className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold capitalize ${
                              ROLE_PILL[u.role] ??
                              "bg-[color:var(--color-linen)] text-[color:var(--color-espresso)]"
                            }`}
                          >
                            {u.role}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm">
                          {u.is_verified ? (
                            <span className="status-pill status-done">
                              Verified
                            </span>
                          ) : isPendingLawyer ? (
                            <span className="status-pill status-progress">
                              Pending
                            </span>
                          ) : (
                            <span className="status-pill status-review">
                              Unverified
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-xs">
                          {isPendingLawyer ? (
                            <div className="flex gap-2">
                              <button
                                type="button"
                                onClick={() => handleVerify(u, true)}
                                disabled={verifyLoading}
                                className="rounded-md border border-[color:var(--color-solana-green)]/60 bg-[color:var(--color-status-done-bg)] px-2.5 py-1 font-semibold text-[color:var(--color-status-done-fg)] hover:bg-[color:var(--color-solana-green-soft)] disabled:opacity-60"
                              >
                                Verify
                              </button>
                              <button
                                type="button"
                                onClick={() => handleSelectUser(u)}
                                className="rounded-md border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] px-2.5 py-1 font-semibold text-[color:var(--color-muted)] hover:border-[color:var(--color-bronze)]"
                              >
                                Review
                              </button>
                            </div>
                          ) : u.role === "lawyer" && u.is_verified ? (
                            <button
                              type="button"
                              onClick={() => handleVerify(u, false)}
                              disabled={verifyLoading}
                              className="rounded-md border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] px-2.5 py-1 font-semibold text-[color:var(--color-muted)] hover:border-[color:var(--color-bronze)] disabled:opacity-60"
                            >
                              Revoke
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => handleSelectUser(u)}
                              className="rounded-md border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] px-2.5 py-1 font-semibold text-[color:var(--color-muted)] hover:border-[color:var(--color-bronze)]"
                            >
                              Edit
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {selectedUser && (
          <div className="rwa-card h-fit w-80 p-6">
            <h2 className="mb-4 text-lg font-semibold text-[color:var(--color-espresso)]">
              Edit User
            </h2>

            {editSuccess && (
              <div className="mb-3 rounded-lg border border-[color:var(--color-solana-green)]/60 bg-[color:var(--color-status-done-bg)] p-2 text-xs text-[color:var(--color-status-done-fg)]">
                {editSuccess}
              </div>
            )}
            {editError && (
              <div
                role="alert"
                className="mb-3 rounded-lg border border-red-300 bg-red-50 p-2 text-xs text-red-800"
              >
                {editError}
              </div>
            )}

            {selectedUser.role === "lawyer" && (
              <div className="mb-3 rounded-lg border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] p-3 text-xs text-[color:var(--color-ink)]">
                <p className="mb-1 font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Bar Credentials
                </p>
                <p>{selectedUser.bar_association ?? "(none)"}</p>
                <p className="font-mono text-[11px]">
                  {selectedUser.bar_number ?? "(no number)"}
                </p>
                <div className="mt-2 flex gap-2">
                  {!selectedUser.is_verified ? (
                    <button
                      type="button"
                      onClick={() => handleVerify(selectedUser, true)}
                      disabled={verifyLoading}
                      className="flex-1 rounded-md bg-[color:var(--color-solana-green)] px-2.5 py-1.5 text-xs font-semibold text-white hover:brightness-95 disabled:opacity-60"
                    >
                      {verifyLoading ? "..." : "Verify Lawyer"}
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleVerify(selectedUser, false)}
                      disabled={verifyLoading}
                      className="flex-1 rounded-md border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] px-2.5 py-1.5 text-xs font-semibold text-[color:var(--color-bronze-dark)] hover:border-[color:var(--color-bronze)] disabled:opacity-60"
                    >
                      {verifyLoading ? "..." : "Revoke Verification"}
                    </button>
                  )}
                </div>
              </div>
            )}

            <div className="space-y-3">
              <div>
                <label className="block text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Full Name
                </label>
                <input
                  value={editForm.full_name}
                  onChange={(e) =>
                    setEditForm({ ...editForm, full_name: e.target.value })
                  }
                  className="rwa-input mt-1 w-full"
                />
              </div>
              <div>
                <label className="block text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Email
                </label>
                <input
                  value={editForm.email}
                  onChange={(e) =>
                    setEditForm({ ...editForm, email: e.target.value })
                  }
                  className="rwa-input mt-1 w-full"
                  placeholder={selectedUser.wallet_address ? "(wallet only)" : ""}
                />
              </div>
              <div>
                <label className="block text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Phone
                </label>
                <input
                  value={editForm.phone}
                  onChange={(e) =>
                    setEditForm({ ...editForm, phone: e.target.value })
                  }
                  className="rwa-input mt-1 w-full"
                />
              </div>
              <div>
                <label className="block text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Role
                </label>
                <select
                  value={editForm.role}
                  onChange={(e) =>
                    setEditForm({ ...editForm, role: e.target.value })
                  }
                  className="rwa-input mt-1 w-full"
                >
                  <option value="admin">Admin</option>
                  <option value="lawyer">Lawyer</option>
                  <option value="client">Client</option>
                </select>
              </div>
              <label className="flex items-center gap-2 text-sm text-[color:var(--color-ink)]">
                <input
                  type="checkbox"
                  checked={editForm.is_active}
                  onChange={(e) =>
                    setEditForm({ ...editForm, is_active: e.target.checked })
                  }
                  className="h-4 w-4"
                />
                Active
              </label>

              <div className="flex gap-2 pt-2">
                <button
                  type="button"
                  onClick={handleEditUser}
                  disabled={editLoading}
                  className="rwa-btn-primary flex-1 text-xs"
                >
                  {editLoading ? "Saving..." : "Save"}
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedUser(null)}
                  className="rwa-btn-secondary text-xs"
                >
                  Close
                </button>
              </div>

              <p className="truncate text-[10px] text-[color:var(--color-muted)]/80">
                ID: {selectedUser.id}
              </p>
              {selectedUser.wallet_address && (
                <p className="truncate font-mono text-[10px] text-[color:var(--color-bronze-dark)]">
                  {selectedUser.wallet_address}
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
