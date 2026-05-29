"use client";

import { useCallback, useEffect, useState } from "react";

import api, { extractErrorMessage } from "@/lib/api";

interface OrgRow {
  id: string;
  slug: string;
  name: string;
  plan: string;
  created_at: string;
}

interface OrgSwitcherProps {
  currentOrgId: string | null;
  onSwitched?: (org: OrgRow) => void;
}

export function OrgSwitcher({
  currentOrgId,
  onSwitched,
}: OrgSwitcherProps) {
  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await api.get<OrgRow[]>("/organizations/me");
      setOrgs(res.data);
    } catch (err) {
      setError(extractErrorMessage(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const current = orgs.find((o) => o.id === currentOrgId) ?? orgs[0];

  const onPick = async (org: OrgRow) => {
    if (org.id === current?.id) {
      setOpen(false);
      return;
    }
    setSwitching(true);
    setError(null);
    try {
      await api.post(`/organizations/me/switch/${org.id}`);
      setOpen(false);
      onSwitched?.(org);
      // Reload so every page reads the new default_organization_id
      // from /auth/me without hand-rolling cache invalidation.
      window.location.reload();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setSwitching(false);
    }
  };

  if (orgs.length === 0) {
    return null;
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
      >
        <span className="max-w-[180px] truncate">
          {current ? current.name : "Pick organization"}
        </span>
        <svg
          width="10"
          height="10"
          viewBox="0 0 10 10"
          fill="none"
          aria-hidden
        >
          <path d="M2 4l3 3 3-3" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>
      {open ? (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 z-50 mt-2 w-72 overflow-hidden rounded-lg border border-gray-200 bg-white shadow-lg">
            <div className="border-b border-gray-100 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              Switch organization
            </div>
            {error ? (
              <p className="px-3 py-2 text-xs text-red-700">{error}</p>
            ) : null}
            <ul className="max-h-80 overflow-y-auto">
              {orgs.map((o) => {
                const active = o.id === current?.id;
                return (
                  <li key={o.id}>
                    <button
                      type="button"
                      onClick={() => onPick(o)}
                      disabled={switching}
                      className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-gray-50 disabled:opacity-50 ${
                        active ? "bg-emerald-50" : ""
                      }`}
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium text-gray-900">
                          {o.name}
                        </p>
                        <p className="truncate text-xs text-gray-500">
                          {o.slug} · {o.plan}
                        </p>
                      </div>
                      {active ? (
                        <span className="text-xs text-emerald-700">
                          current
                        </span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className="border-t border-gray-100 px-3 py-2">
              <a
                href="/dashboard/organizations"
                className="text-xs text-emerald-700 hover:underline"
              >
                Manage organizations →
              </a>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

export default OrgSwitcher;
