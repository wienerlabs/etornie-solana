"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import api, { extractErrorMessage } from "@/lib/api";

interface OrgRow {
  id: string;
  slug: string;
  name: string;
  plan: string;
  created_at: string;
}

interface OrgMember {
  user_id: string;
  email: string | null;
  full_name: string;
  role: string;
  joined_at: string;
}

interface OrgDetail extends OrgRow {
  members: OrgMember[];
}

interface InviteRow {
  id: string;
  organization_id: string;
  email: string;
  role: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  invited_by_user_id: string | null;
  created_at: string;
}

interface InviteCreateResponse extends InviteRow {
  token: string;
}

function RoleBadge({ role }: { role: string }) {
  const color =
    role === "owner"
      ? "bg-emerald-100 text-emerald-700"
      : role === "admin"
        ? "bg-amber-100 text-amber-700"
        : "bg-gray-100 text-gray-700";
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${color}`}
    >
      {role}
    </span>
  );
}

export default function OrganizationsPage() {
  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<OrgDetail | null>(null);
  const [invites, setInvites] = useState<InviteRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [createName, setCreateName] = useState("");
  const [creating, setCreating] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"member" | "admin">(
    "member"
  );
  const [inviting, setInviting] = useState(false);
  const [lastInviteToken, setLastInviteToken] = useState<string | null>(
    null
  );

  const loadOrgs = useCallback(async () => {
    setError(null);
    try {
      const res = await api.get<OrgRow[]>("/organizations/me");
      setOrgs(res.data);
      if (res.data.length > 0 && selectedId === null) {
        setSelectedId(res.data[0].id);
      }
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  }, [selectedId]);

  const loadDetail = useCallback(async () => {
    if (selectedId === null) return;
    setError(null);
    try {
      const [d, i] = await Promise.all([
        api.get<OrgDetail>(`/organizations/${selectedId}`),
        api
          .get<InviteRow[]>(`/organizations/${selectedId}/invites`)
          .catch(() => ({ data: [] as InviteRow[] })),
      ]);
      setDetail(d.data);
      setInvites(i.data);
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  }, [selectedId]);

  useEffect(() => {
    loadOrgs();
  }, [loadOrgs]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  const onCreate = async (e: FormEvent) => {
    e.preventDefault();
    if (!createName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const res = await api.post<OrgRow>("/organizations", {
        name: createName.trim(),
      });
      setCreateName("");
      setSelectedId(res.data.id);
      await loadOrgs();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setCreating(false);
    }
  };

  const onInvite = async (e: FormEvent) => {
    e.preventDefault();
    if (selectedId === null || !inviteEmail.trim()) return;
    setInviting(true);
    setError(null);
    setLastInviteToken(null);
    try {
      const res = await api.post<InviteCreateResponse>(
        `/organizations/${selectedId}/invites`,
        {
          email: inviteEmail.trim(),
          role: inviteRole,
        }
      );
      setInviteEmail("");
      setLastInviteToken(res.data.token);
      await loadDetail();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setInviting(false);
    }
  };

  const onRevoke = async (inviteId: string) => {
    if (selectedId === null) return;
    if (!window.confirm("Revoke this invite?")) return;
    setError(null);
    try {
      await api.delete(
        `/organizations/${selectedId}/invites/${inviteId}`
      );
      await loadDetail();
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  };

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6">
      <header>
        <h1 className="text-2xl font-semibold text-gray-900">
          Organizations
        </h1>
        <p className="text-sm text-gray-500">
          Manage the workspaces you belong to and invite teammates.
        </p>
      </header>

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm md:col-span-1">
          <h2 className="mb-3 text-sm font-semibold text-gray-800">
            Your organizations
          </h2>
          <ul className="space-y-1">
            {orgs.map((o) => {
              const active = o.id === selectedId;
              return (
                <li key={o.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(o.id)}
                    className={`w-full rounded-md px-2.5 py-1.5 text-left text-sm ${
                      active
                        ? "bg-emerald-50 text-emerald-800"
                        : "text-gray-700 hover:bg-gray-50"
                    }`}
                  >
                    <div className="truncate font-medium">{o.name}</div>
                    <div className="truncate text-xs text-gray-500">
                      {o.slug} · {o.plan}
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>

          <form onSubmit={onCreate} className="mt-4 space-y-2">
            <input
              type="text"
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              placeholder="New organization name"
              className="w-full rounded-md border border-gray-200 px-2 py-1.5 text-sm focus:border-emerald-400 focus:outline-none"
            />
            <button
              type="submit"
              disabled={creating || !createName.trim()}
              className="w-full rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              {creating ? "Creating…" : "Create organization"}
            </button>
          </form>
        </div>

        <div className="space-y-4 md:col-span-2">
          {detail === null ? (
            <div className="rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-500 shadow-sm">
              Select an organization to view members.
            </div>
          ) : (
            <>
              <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-gray-800">
                    {detail.name}
                  </h2>
                  <span className="text-xs text-gray-500">
                    {detail.slug} · {detail.plan}
                  </span>
                </div>
                <table className="min-w-full divide-y divide-gray-100 text-sm">
                  <thead className="text-xs uppercase tracking-wide text-gray-500">
                    <tr>
                      <th className="px-2 py-1.5 text-left">Member</th>
                      <th className="px-2 py-1.5 text-left">Email</th>
                      <th className="px-2 py-1.5 text-left">Role</th>
                      <th className="px-2 py-1.5 text-left">Joined</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {detail.members.map((m) => (
                      <tr key={m.user_id}>
                        <td className="px-2 py-1.5 text-gray-900">
                          {m.full_name}
                        </td>
                        <td className="px-2 py-1.5 text-xs text-gray-600">
                          {m.email || "—"}
                        </td>
                        <td className="px-2 py-1.5">
                          <RoleBadge role={m.role} />
                        </td>
                        <td className="px-2 py-1.5 text-xs text-gray-500">
                          {new Date(m.joined_at).toLocaleDateString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
                <h2 className="mb-3 text-sm font-semibold text-gray-800">
                  Invite a teammate
                </h2>
                <form onSubmit={onInvite} className="flex flex-wrap gap-2">
                  <input
                    type="email"
                    required
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    placeholder="email@example.com"
                    className="flex-1 min-w-[200px] rounded-md border border-gray-200 px-2 py-1.5 text-sm focus:border-emerald-400 focus:outline-none"
                  />
                  <select
                    value={inviteRole}
                    onChange={(e) =>
                      setInviteRole(e.target.value as "member" | "admin")
                    }
                    className="rounded-md border border-gray-200 px-2 py-1.5 text-sm focus:border-emerald-400 focus:outline-none"
                  >
                    <option value="member">Member</option>
                    <option value="admin">Admin</option>
                  </select>
                  <button
                    type="submit"
                    disabled={inviting || !inviteEmail.trim()}
                    className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                  >
                    {inviting ? "Sending…" : "Send invite"}
                  </button>
                </form>

                {lastInviteToken ? (
                  <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-xs">
                    <p className="font-medium text-emerald-800">
                      Invite created. Share this link with the invitee:
                    </p>
                    <code className="mt-1 block break-all rounded bg-white px-2 py-1 text-emerald-900">
                      {`${typeof window !== "undefined" ? window.location.origin : ""}/invite/${lastInviteToken}`}
                    </code>
                    <p className="mt-1 text-emerald-700">
                      The token is shown only once.
                    </p>
                  </div>
                ) : null}

                {invites.length > 0 ? (
                  <ul className="mt-4 divide-y divide-gray-100 text-sm">
                    {invites.map((inv) => {
                      const status =
                        inv.revoked_at !== null
                          ? "Revoked"
                          : inv.accepted_at !== null
                            ? "Accepted"
                            : new Date(inv.expires_at) <= new Date()
                              ? "Expired"
                              : "Pending";
                      return (
                        <li
                          key={inv.id}
                          className="flex items-center justify-between py-2"
                        >
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm text-gray-900">
                              {inv.email}
                            </p>
                            <p className="text-xs text-gray-500">
                              {inv.role} · expires{" "}
                              {new Date(inv.expires_at).toLocaleDateString()}
                            </p>
                          </div>
                          <span className="text-xs text-gray-700">
                            {status}
                          </span>
                          {status === "Pending" ? (
                            <button
                              type="button"
                              onClick={() => onRevoke(inv.id)}
                              className="ml-3 rounded border border-amber-300 bg-white px-2 py-0.5 text-xs text-amber-700 hover:bg-amber-50"
                            >
                              Revoke
                            </button>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                ) : null}
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
