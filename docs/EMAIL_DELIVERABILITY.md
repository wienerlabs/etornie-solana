# Email deliverability (SPF / DKIM / DMARC)

Etornie sends transactional email — the registration OTP and case /
payment / filing / NFT notifications — server-side over SMTP
(`app/notifications/email_transport.py`, introduced in #29, replacing the
old EmailJS front-end key flow).

SMTP only moves the message to a relay. Whether it lands in the inbox
instead of spam — or is accepted at all — depends on three DNS records
on the **From** domain (`SMTP_FROM_EMAIL`). Configure all three before
sending production mail.

## 1. SMTP configuration

Set these on the backend (`services/api/.env`; see `.env.example`):

| Variable          | Example                          | Notes |
|-------------------|----------------------------------|-------|
| `SMTP_HOST`       | `email-smtp.eu-central-1.amazonaws.com` | Empty disables email (local dev). |
| `SMTP_PORT`       | `587`                            | `587` = STARTTLS, `465` = implicit TLS. |
| `SMTP_USERNAME`   | SES SMTP user / API key id       | |
| `SMTP_PASSWORD`   | SES SMTP password / API key      | Secret — never commit. |
| `SMTP_STARTTLS`   | `true`                           | Use on port 587. |
| `SMTP_USE_TLS`    | `false`                          | Set `true` (and `SMTP_STARTTLS=false`) for port 465. |
| `SMTP_FROM_EMAIL` | `no-reply@etornie.ch`            | Must be on a domain you control the DNS for. |
| `SMTP_FROM_NAME`  | `Etornie`                        | Display name. |

Any standards-compliant relay works (Amazon SES, Postmark, Mailgun,
SendGrid, Google Workspace). The DNS records below are what each relay's
dashboard asks you to publish; the exact values come from that provider.

## 2. SPF — authorise the sending hosts

Publish **one** `TXT` record at the apex of the From domain listing the
relay that sends on your behalf. Example for Amazon SES:

```
etornie.ch.   TXT   "v=spf1 include:amazonses.com -all"
```

- `include:` — the provider's SPF domain (SES: `amazonses.com`,
  Postmark: `spf.mtasv.net`, Mailgun: `mailgun.org`).
- `-all` — hard-fail anything not listed. Use `~all` (soft-fail) only
  while testing.
- Exactly one SPF record per domain; merge multiple senders into a
  single record with several `include:` tokens.

## 3. DKIM — cryptographically sign the mail

The relay signs each message; the public key lives in DNS so receivers
can verify the signature. Providers give you the records to publish —
usually three CNAMEs (SES) or a `TXT` key.

Amazon SES (Easy DKIM) publishes three CNAMEs:

```
<token1>._domainkey.etornie.ch.   CNAME   <token1>.dkim.amazonses.com.
<token2>._domainkey.etornie.ch.   CNAME   <token2>.dkim.amazonses.com.
<token3>._domainkey.etornie.ch.   CNAME   <token3>.dkim.amazonses.com.
```

Generic `TXT` form (e.g. self-managed or Postmark):

```
<selector>._domainkey.etornie.ch.   TXT   "v=DKIM1; k=rsa; p=<base64 public key>"
```

Wait for the provider console to report the domain as **verified**
before relying on DKIM.

## 4. DMARC — policy + reporting

Tells receivers what to do when SPF/DKIM fail and where to send reports.
Publish a `TXT` record at `_dmarc`:

```
_dmarc.etornie.ch.   TXT   "v=DMARC1; p=quarantine; rua=mailto:dmarc@etornie.ch; adkim=s; aspf=s; pct=100"
```

- `p=` — policy: roll out `none` → `quarantine` → `reject` as confidence
  grows. Start at `none` (monitor only), end at `reject` for production.
- `rua=` — mailbox that receives aggregate reports.
- `adkim=s` / `aspf=s` — strict alignment: the DKIM/SPF domain must match
  the visible From domain exactly.

DMARC passes when **either** SPF or DKIM passes *and* is aligned with the
From domain, so `SMTP_FROM_EMAIL` must be on the domain whose SPF/DKIM you
published above.

## 5. Verify before launch

1. Send a test (e.g. trigger a registration OTP) to a Gmail account.
2. Open the message → **Show original**: SPF, DKIM, and DMARC should all
   read **PASS**.
3. Or use a checker such as <https://www.mail-tester.com>.
4. Watch the `rua` DMARC reports for a few days before tightening
   `p=none` → `quarantine` → `reject`.

## Local development

Leave `SMTP_HOST` empty. The transport logs and returns `False` instead
of sending, so the app runs without an email account. Registration will
report that the verification email could not be sent — set up a relay (or
a local catcher like MailHog: `SMTP_HOST=localhost`, `SMTP_PORT=1025`,
`SMTP_STARTTLS=false`) to exercise the OTP flow end to end.
