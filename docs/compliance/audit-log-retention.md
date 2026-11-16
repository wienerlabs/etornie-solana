# Audit Log Retention Policy

> **Status: DRAFT, pending legal review.**
> The retention period below is a proposal. It must be confirmed by
> legal counsel before it is treated as policy.

## Purpose

`audit_logs` (see `app/audit/models.py`) is the append-only record of
processing activities required by **GDPR Article 30**: who did what,
when, to which resource. This document states how long rows are kept
and what happens at the retention boundary, since Art. 30 requires the
record to exist, not that it be kept forever without a stated basis.

## What is recorded

Every case, document, notification and in-app notification mutation
(create, update, status change, cancel, send, fail) writes one row via
`app.audit.service.log_audit_event`. It is called from the service
layer, so background jobs, the agent and webhooks are covered, not just
HTTP requests. See the `AuditAction` enum in `app/audit/models.py` for
the full list of recorded actions.

Each row records the actor as `actor_type` plus `actor_id`:

| `actor_type` | Meaning | `actor_id` |
|--------------|---------|------------|
| `user` | A person acting through the API | the user |
| `agent` | The EtornieGPT agent | the user it acted for, if any |
| `system` | A scheduled job or internal process | the account it ran on behalf of, if any |
| `webhook` | A payment or provider webhook | the account concerned, if any |

`actor_id` is therefore nullable. A mutation with no logged-in user is
recorded with an explicit non-user actor instead of being skipped.

## Retention period (proposed)

**Proposal: 10 years from `created_at`.**

This aligns with the financial-record retention already documented in
`docs/compliance/data-retention-and-erasure.md` (CH CO 958f / EU VAT,
about 10 years). Audit rows for cases, documents and notifications can
be needed to reconstruct the history of the same filings and payments,
so a shorter period than the records they describe would leave gaps.

Open points for legal review:

- Confirm 10 years (an earlier draft proposed 7 years).
- Confirm the legal basis for keeping audit rows for that long
  (Art. 30 record-keeping, Art. 17(3)(e) legal claims).
- Confirm whether the period differs by jurisdiction.

## What happens at the boundary

Rows older than the retention period are eligible for deletion. Because
`audit_logs` is enforced append-only at the database level (see the
`audit_logs_no_update_delete` trigger added in migration
`b4e8d3a7f2c9`), routine deletion cannot go through the application:
the trigger rejects `UPDATE` and `DELETE` from any role. Purging
expired rows therefore requires an explicit, logged, out-of-band
operation (for example a migration or a one-off admin script run by an
operator), not a scheduled job silently deleting rows in the
background. This is a deliberate trade-off: it is safer for a retention
purge to require a manual, auditable step than for the append-only
guarantee to have a built-in exception that a bug could trigger early.

No automated purge job exists yet; this is tracked as a follow-up.
Until one exists, rows simply accumulate past the retention period
rather than being silently lost, which is the safer default for a
compliance record.

## Consequence for deleting cases

`audit_logs.case_id` is a plain foreign key to `cases.id` with no
`ON DELETE` action. `ON DELETE SET NULL` would be an `UPDATE` of an
audit row, which the append-only trigger rejects. As a result, a case
that has audit rows cannot be hard-deleted. This is consistent with
`docs/compliance/data-retention-and-erasure.md`, where cases are
retained as legal records. Cases are never hard-deleted by the
application today.

## GDPR Article 17 (erasure) interaction

A user's right-to-erasure request (see `app/compliance/erasure.py`)
does not delete their `audit_logs` rows. The append-only trigger would
reject it, and Article 30's record-keeping purpose is a separate legal
basis from the data the erasure request is about. `actor_id` and
`target_id` on existing rows continue to reference the now-anonymised
user id, so no identifying data survives in them. This is consistent
with how other append-only compliance records (for example payment
history) are handled.

## Export

Audit log rows for a given user are included in that user's GDPR
export via `app.compliance.data_export`, regardless of retention age.
Rows written by a non-user actor on behalf of that user (for example a
system job) have no `actor_id` match for the user and are not exported
as the user's own actions.
