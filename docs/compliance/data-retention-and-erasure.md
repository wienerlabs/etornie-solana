# Data Retention & Right to Erasure (GDPR Article 17)

This document is the human-readable companion to the code in
`services/api/app/compliance/retention.py` (policy) and
`erasure.py` (execution). It is intended for legal review
(this is a `needs-lawyer` deliverable). The code is the source of
truth; this page explains the reasoning.

## Scope

A data subject (or an admin on their behalf) can request erasure of
their personal data. Etornie processes the request by **anonymising the
subject's account and selectively deleting personal data**, while
**retaining records covered by a GDPR Art. 17(3) exception**.

Erasure is **irreversible**.

## Erasure blockers — active legal proceedings (Art. 17(3)(e))

Erasure is **refused** while the subject has any case in an active
legal proceeding. A case is "active" when its status is one of:

- `open`
- `in_progress`
- `under_review`

(`closed` is the only non-blocking status.)

The API returns **HTTP 409** with the list of blocking cases. The
subject can re-request erasure once those cases are closed. This
implements Art. 17(3)(e) — retention for the establishment, exercise,
or defence of legal claims.

## What is deleted vs retained

Every user-scoped table in the Article-20 data export
(`app/compliance/data_export.py`) is classified. The two modules are
kept in lock-step.

### Deleted (physical removal, including on-disk files)

Pure personal data with no overriding retention basis:

| Data | Reason |
|------|--------|
| EtornieGPT chat messages | Conversational personal data |
| AI agent messages | Assistant conversation content |
| Agent uploads (+ files on disk) | User working files |
| Case notes authored by the subject | Free-text personal data |
| In-app notifications | Delivered to the subject |
| Notifications created by the subject | — |
| Proposals authored by the subject | — |
| BRAID calibration feedback | Tied to the subject |
| Organisation memberships | Severs org links |

The subject's avatar bytes (in-DB) and any legacy avatar file on disk
are also removed.

### Anonymised (the subject's `users` row)

The row is **tombstoned**: `email`, `full_name`, `phone`,
`wallet_address`, `public_handle`, `notification_email`, and avatar
fields are overwritten; `is_active` is set to `false`; `erased_at` and
`erasure_reason` are stamped.

To satisfy the `ck_users_authenticatable` CHECK constraint without
storing personal data, `email` becomes a synthetic
`erased-<uuid>@deleted.etornie.invalid` and the password is replaced
with a fresh, unknowable random hash. The account can never
authenticate (it is also deactivated).

Every retained row keeps pointing at this anonymised user id, so no
identifying data survives in them.

### Retained (Art. 17(3) exception)

| Data | Basis |
|------|-------|
| Payment intents | **Financial record** — statutory retention (CH CO 958f / EU VAT, ~10 years) |
| Case drafts, filing attempts | Backing financial / official IP-office filing records |
| Cases, case events | IP legal records, frequently **on-chain attested** (immutable) |
| Documents | Evidence attached to retained IP cases (Art. 17(3)(e)) |
| Audit logs | Security/compliance audit trail — legal obligation |
| Organisation invites | Invite history retained; the subject's FKs are nulled |

> **On-chain data.** Solana attestations, NFT mints and compliance
> records are immutable and cannot be deleted. Erasure removes the
> off-chain personal data that links a human to those records; the
> on-chain artefacts themselves remain by design.

## Triggers

- **Self-service** — `POST /users/me/erase`. Accounts with a password
  must re-authenticate (password in the request body); wallet-only
  accounts confirm via the typed confirmation in the UI. The subject
  can only erase themselves.
- **Admin** — `POST /users/{user_id}/erase` with a `reason`. For
  processing GDPR requests received out-of-band.

Both paths run the identical retention policy and return a summary of
deleted-row counts, deleted files, and retained tables, or a 409 with
blocking cases.

## Open items for legal review

- Confirm the financial-record retention period and jurisdiction basis
  (currently documented as CH CO 958f / EU VAT ~10y).
- Confirm whether documents attached to **closed** cases should be
  deleted or retained (currently retained as case evidence).
- Confirm the active-proceeding status set is complete.
