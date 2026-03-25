"use client";

import { useEffect, useState } from "react";
import api from "@/lib/api";

interface UserItem {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface UserListResponse {
  users: UserItem[];
  total: number;
}

export default function UsersPage() {
  const [users, setUsers] = useState<UserItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Detail/Edit modal
  const [selectedUser, setSelectedUser] = useState<UserItem | null>(null);
  const [editForm, setEditForm] = useState({
    full_name: "",
    email: "",
    phone: "",
    role: "",
    is_active: true,
  });
  const [editLoading, setEditLoading] = useState(false);
  const [editError, setEditError] = useState("");
  const [editSuccess, setEditSuccess] = useState("");

  async function fetchUsers() {
    setLoading(true);
    try {
      const res = await api.get<UserListResponse>("/users", {
        params: { limit: 100 },
      });
      setUsers(res.data.users);
      setTotal(res.data.total);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to load users. Admin access required.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchUsers();
  }, []);

  function handleSelectUser(user: UserItem) {
    setSelectedUser(user);
    setEditForm({
      full_name: user.full_name,
      email: user.email,
      phone: user.phone ?? "",
      role: user.role,
      is_active: user.is_active,
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
        email: editForm.email,
        phone: editForm.phone || null,
        role: editForm.role,
        is_active: editForm.is_active,
      });
      setEditSuccess("User updated successfully.");
      fetchUsers();
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to update user.";
      setEditError(message);
    } finally {
      setEditLoading(false);
    }
  }

  const roleBadge = (role: string) => {
    const colors: Record<string, string> = {
      admin: "bg-purple-100 text-purple-800",
      lawyer: "bg-blue-100 text-blue-800",
      client: "bg-gray-100 text-gray-800",
    };
    return colors[role] ?? "bg-gray-100 text-gray-800";
  };

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold text-gray-800">
        Users ({total})
      </h1>

      {error && (
        <div className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700 border border-red-200">
          {error}
        </div>
      )}

      <div className="flex gap-6">
        {/* Users Table */}
        <div className="flex-1">
          {loading ? (
            <p className="text-gray-500">Loading users...</p>
          ) : users.length === 0 ? (
            <p className="text-gray-500">No users found.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg bg-white shadow-sm border border-gray-200">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                      Name
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                      Email
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                      Phone
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                      Role
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                      Active
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {users.map((u) => (
                    <tr
                      key={u.id}
                      className="hover:bg-gray-50 cursor-pointer"
                      onClick={() => handleSelectUser(u)}
                    >
                      <td className="px-4 py-3 text-sm font-medium text-blue-600">
                        {u.full_name}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700">
                        {u.email}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {u.phone ?? "N/A"}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        <span
                          className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${roleBadge(u.role)}`}
                        >
                          {u.role}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm">
                        <span
                          className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                            u.is_active
                              ? "bg-green-100 text-green-800"
                              : "bg-red-100 text-red-800"
                          }`}
                        >
                          {u.is_active ? "Yes" : "No"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Edit Panel */}
        {selectedUser && (
          <div className="w-80 rounded-lg bg-white p-6 shadow-sm border border-gray-200 h-fit">
            <h2 className="mb-4 text-lg font-semibold text-gray-700">
              Edit User
            </h2>

            {editSuccess && (
              <div className="mb-3 rounded bg-green-50 p-2 text-xs text-green-700 border border-green-200">
                {editSuccess}
              </div>
            )}
            {editError && (
              <div className="mb-3 rounded bg-red-50 p-2 text-xs text-red-700 border border-red-200">
                {editError}
              </div>
            )}

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-gray-600">
                  Full Name
                </label>
                <input
                  value={editForm.full_name}
                  onChange={(e) =>
                    setEditForm({ ...editForm, full_name: e.target.value })
                  }
                  className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600">
                  Email
                </label>
                <input
                  value={editForm.email}
                  onChange={(e) =>
                    setEditForm({ ...editForm, email: e.target.value })
                  }
                  className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600">
                  Phone
                </label>
                <input
                  value={editForm.phone}
                  onChange={(e) =>
                    setEditForm({ ...editForm, phone: e.target.value })
                  }
                  className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600">
                  Role
                </label>
                <select
                  value={editForm.role}
                  onChange={(e) =>
                    setEditForm({ ...editForm, role: e.target.value })
                  }
                  className="mt-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
                >
                  <option value="admin">Admin</option>
                  <option value="lawyer">Lawyer</option>
                  <option value="client">Client</option>
                </select>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="is-active"
                  checked={editForm.is_active}
                  onChange={(e) =>
                    setEditForm({ ...editForm, is_active: e.target.checked })
                  }
                  className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <label
                  htmlFor="is-active"
                  className="text-sm text-gray-700"
                >
                  Active
                </label>
              </div>

              <div className="flex gap-2 pt-2">
                <button
                  onClick={handleEditUser}
                  disabled={editLoading}
                  className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {editLoading ? "Saving..." : "Save"}
                </button>
                <button
                  onClick={() => setSelectedUser(null)}
                  className="rounded bg-gray-200 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-300"
                >
                  Close
                </button>
              </div>

              <p className="text-xs text-gray-400 mt-2">
                ID: {selectedUser.id}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
