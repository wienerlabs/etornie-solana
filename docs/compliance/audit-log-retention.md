# Audit Log Retention Policy

## Purpose

`audit_logs` (see `app/audit/models.py`) is the append-only record of
processing activities required by **GDPR Article 30**: who did what,
when, to which resource. This document states how long rows are kept
and what happens at the retention boundary, since Art. 30 requires the
record to exist — not that it be kept forever without a stated basis.

## What is recorded

Every case, document, and notification mutation (create, update,
status change, cancel) writes one row via `app.audit.service.log_audit_event`,
called from the service layer so background jobs and webhooks are
covered, not just HTTP requests. See the `AuditAction` enum in
`app/audit/models.py` for the full list of recorded actions.

## Retention period

Audit log rows are retained for **7 years** from `created_at`. This
matches the retention window already applied to filing and payment
records elsewhere in the compliance module (see
`app/compliance/retention.py`) and covers the longest statutory
limitation period relevant to trademark filing engagements across the
jurisdictions Etornie operates in.

## What happens at the boundary

Rows older than the retention period are eligible for deletion. Because
`audit_logs` is enforced append-only at the database level (see the
`audit_logs_no_update_delete` trigger added in migration
`b4e8d3a7f2c9`), routine deletion cannot go through the application —
the trigger rejects `DELETE` from any role. Purging expired rows
therefore requires an explicit, logged, out-of-band operation (e.g. a
migration or a one-off admin script run by an operator), not a
scheduled job silently deleting rows in the background. This is a
deliberate trade-off: it is safer for a retention purge to require a
manual, auditable step than for the append-only guarantee to have a
built-in exception a bug could accidentally trigger early.

No automated purge job exists yet — this is tracked as a follow-up.
Until one exists, rows simply accumulate past the 7-year mark rather
than being silently lost, which is the safer default for a compliance
record.

## GDPR Article 17 (erasure) interaction

A user's right-to-erasure request (see `app/compliance/erasure.py`)
does not delete their `audit_logs` rows — the append-only trigger
would reject it, and Article 30's own record-keeping purpose is a
separate legal basis from the data the erasure request is about.
`actor_id` and `target_id` on existing rows continue to reference the
now-erased user id; this is expected and consistent with how other
append-only compliance records (e.g. Stripe payment history) are
handled.

## Export

Audit log rows for a given user are included in that user's GDPR
export via `app.compliance.data_export`, regardless of retention age.
