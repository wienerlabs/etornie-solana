# ADR-0003: Two-tier role model (retire the lawyer layer)

- **Status:** Accepted
- **Date:** 2026-05-02
- **Deciders:** Etornie engineering
- **Reference:** [docs/REMOVED_LAWYER_LAYER.md](../REMOVED_LAWYER_LAYER.md)

## Context

The system originally carried three system-level roles: `admin`,
`lawyer`, and `client`. In practice the `lawyer` tier added permission
complexity (a parallel authorization path on nearly every case route)
without a distinct product need — operators were acting as admins and
the lawyer capabilities had collapsed into the operator role.

## Decision

We will run a **two-tier system role model**: `admin` (the platform
operator) and `client` (the case owner). The historical `lawyer` value
still exists in the Postgres `user_role` enum for legacy rows, but
nothing in the runtime path emits or accepts it; legacy `lawyer` rows
are treated as `client`.

Per-case access is therefore simple (`app/cases/router.py:_can_access_case`):
an `admin` can reach any case; every other user can reach only the case
they are bound to as `client_id`. Multi-tenant scoping lives separately
in the `organization_membership` role (`owner`/`admin`/`member`), which
is independent of the system role.

## Consequences

- Authorization checks across case, document, and note routes collapse
  to "admin or owner", which is far easier to reason about and audit.
- Organisation-level roles (owner/admin/member) handle team permissions,
  keeping system roles minimal.
- The retired `lawyer` enum value is intentionally left in the database
  to avoid a destructive enum migration; code must keep tolerating it on
  read. New 2FA/MFA work (issue #56) targets the `admin` role.
