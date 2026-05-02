# Lawyer Role — Removed (2026-05-02)

This document is the archive of the `lawyer` user role and the
"assigned lawyer" layer that was removed from the system on
**2026-05-02**. Etornie was originally designed as a traditional
attorney-client management platform; that scope changed: every filing
now goes directly through the official IP offices (UKIPO, EUIPO, WIPO,
IP Australia, …) via the EtornieGPT agent, so a separate lawyer
identity is no longer meaningful.

Use this file as the reference if the role ever has to be reinstated
or audited later — every column, code path, and data point we removed
is listed here.

## Snapshot of users with role=lawyer at removal time

```
4 lawyer users
  id=9d93c4b7-69ed-40ed-9602-0d6c2b488b91 email=None        full_name='Ayse Yilmaz'        wallet=4e54LeG4n1fD1yaCwTAbtV8vB2QaodFCAPfFAGFJ4j9B
  id=b33506d1-e8fa-43da-8ec6-3eae1c780ba7 email=makinci473@gmail.com full_name='Muhammed Akıncı'  wallet=None
  id=fd20eb92-de97-42a6-8a9e-9b20316d12b1 email=None        full_name='Muhammed Akıncı'    wallet=HQgVTSHrBRRQ9TwYSv7gZF3vmTMa6u2yNwZM7b2zFcnq
  id=7caa5644-3839-427b-aac2-cfb04e7c358d email=None        full_name='etornie_5TbWe9Pr'   wallet=5TbWe9PrnwzrET366uMVLDKJVQ9YEZ9kW5H3ccmkRaY9
```

## Snapshot of cases with assigned_lawyer_id at removal time

```
11 cases with assigned lawyer (all assigned to fd20eb92-de97-42a6-8a9e-9b20316d12b1)
  ETR-2026-0006 client_id=94433ac3-2bff-46f6-acec-72ff96bdaa59 jurisdiction=Anguilla (United Kingdom) status=in_progress
  ETR-2026-0001 client_id=a327089f-4682-48bd-84ad-6a5ea98d0fa4 jurisdiction=Anguilla (United Kingdom) status=open
  ETR-2026-0002 client_id=94433ac3-2bff-46f6-acec-72ff96bdaa59 jurisdiction=Anguilla (United Kingdom) status=open
  ETR-2026-0003 client_id=94433ac3-2bff-46f6-acec-72ff96bdaa59 jurisdiction=Anguilla (United Kingdom) status=open
  ETR-2026-0007 client_id=94433ac3-2bff-46f6-acec-72ff96bdaa59 jurisdiction=Anguilla (United Kingdom) status=open
  ETR-2026-0004 client_id=94433ac3-2bff-46f6-acec-72ff96bdaa59 jurisdiction=Bermuda  (United Kingdom) status=in_progress
  ETR-2026-0005 client_id=94433ac3-2bff-46f6-acec-72ff96bdaa59 jurisdiction=Anguilla (United Kingdom) status=in_progress
  ETR-2026-0008 client_id=94433ac3-2bff-46f6-acec-72ff96bdaa59 jurisdiction=Anguilla (United Kingdom) status=open
  ETR-2026-0010 client_id=94433ac3-2bff-46f6-acec-72ff96bdaa59 jurisdiction=Anguilla (United Kingdom) status=open
  ETR-2026-0009 client_id=94433ac3-2bff-46f6-acec-72ff96bdaa59 jurisdiction=Anguilla (United Kingdom) status=open
  ETR-2026-0011 client_id=94433ac3-2bff-46f6-acec-72ff96bdaa59 jurisdiction=Anguilla (United Kingdom) status=in_progress
```

## Migration that was applied

Alembic revision `c1d2e3f4a5b6_remove_lawyer_layer.py`:

1. Per-user role rewrite (data only):
   - `b33506d1-e8fa-43da-8ec6-3eae1c780ba7` (`makinci473@gmail.com`)
     → role becomes `admin` so the platform owner keeps administrative
     access after the role collapse.
   - The other three lawyer rows (wallet-only, no email) → role
     becomes `client`. They keep every case they were the *client_id*
     for; they just lose the `assigned_lawyer_id` lever.
2. `cases.assigned_lawyer_id` is set to `NULL` for every row that
   referenced the removed lawyers (all 11 above). The column itself
   stays for now — dropping the FK + column is a follow-up migration
   once all consumers have been retired.
3. Python `UserRole` enum no longer exposes `lawyer`. The Postgres
   enum value `'lawyer'` is left in place to keep historical
   migrations replayable; nothing in the runtime path emits it.

## Code path that was deleted / collapsed

- `app.users.models.UserRole.lawyer` enum member
- All `require_role(UserRole.lawyer, ...)` checks → either dropped or
  collapsed to `require_role(UserRole.admin)` depending on whether the
  endpoint should still exist for clients
- `Case.assigned_lawyer_id` references in `_can_access_case`
  helpers (cases router, documents router) — replaced by
  `client_id == user.id` plus admin override
- Frontend nav items + role-gated UI:
  - `dashboard/src/app/dashboard/layout.tsx` NAV_ITEMS no longer
    branch on `lawyer`
  - login / register / wallet sign-in flows no longer let the user
    pick a `lawyer` role
- Pages that were lawyer-only got moved or removed in adjacent steps:
  - `/dashboard/ai`, `/dashboard/euipo`, `/dashboard/zk-lab`,
    `/dashboard/ip-agent` were deleted (their functionality is now
    inside EtornieGPT as agent tools)
  - `/dashboard/cases` is now admin-only

## How to reinstate (if ever needed)

1. `UPDATE users SET role='lawyer' WHERE id IN (...)` for the four
   IDs above; pick a fresh `assigned_lawyer_id` mapping for the 11
   cases above (or restore from backup).
2. Re-add `lawyer` to `app.users.models.UserRole` and put back the
   `require_role(UserRole.lawyer, ...)` checks.
3. Restore the deleted dashboard pages from git history (commit prior
   to `c1d2e3f4a5b6`).
4. Re-add the lawyer entry to `dashboard/src/app/dashboard/layout.tsx::NAV_ITEMS`.

The fix-forward path is intentionally additive — nothing about how
clients use EtornieGPT changes, so reinstating the lawyer role does
not require any migration of agent sessions, filings, attestations,
or NFTs.
