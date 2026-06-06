import Link from "next/link";
import Image from "next/image";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy Policy | Etornie",
  description:
    "How Etornie AG collects, uses, and protects personal data under the EU GDPR and the Swiss FADP.",
};

// NOTE FOR REVIEWERS: this is a DRAFT prepared from the platform's actual
// data-processing flows for review and finalisation by a Swiss + EU
// qualified lawyer (issue #57). It is not yet legally binding. Items that
// require legal confirmation are marked inline and listed at the foot of
// the page. The data controller's identity below is factual; the legal
// substance still requires sign-off.

const CONTROLLER = {
  name: "Etornie AG",
  address: "Ruessenstrasse 5, 6340 Baar, Zug, Switzerland",
  uid: "CHE-482.609.557",
  // Temporary contact address pending a dedicated privacy mailbox.
  contactEmail: "support@etornie.com",
} as const;

interface SubProcessor {
  readonly name: string;
  readonly purpose: string;
  readonly location: string;
}

// Sub-processors are derived from the services the platform actually
// integrates with. Self-hosted components (OCR, antivirus) involve no
// third-party transfer and are listed for transparency.
const SUB_PROCESSORS: readonly SubProcessor[] = [
  { name: "Stripe", purpose: "Payment processing & invoicing", location: "EU / USA" },
  { name: "Together AI", purpose: "LLM inference for the AI assistant", location: "USA" },
  { name: "Yousign", purpose: "Qualified electronic signatures", location: "EU (France)" },
  { name: "Solana RPC provider", purpose: "Blockchain reads/writes (public ledger)", location: "Global" },
  { name: "Sentry", purpose: "Error monitoring & diagnostics", location: "EU / USA" },
  { name: "Hosting provider", purpose: "Application & database hosting", location: "EU / USA" },
  { name: "Email/SMTP provider", purpose: "Transactional email delivery", location: "EU / USA" },
];

interface Section {
  readonly id: string;
  readonly label: string;
}

const SECTIONS: readonly Section[] = [
  { id: "controller", label: "Controller" },
  { id: "data", label: "Data we process" },
  { id: "purposes", label: "Purposes & legal bases" },
  { id: "blockchain", label: "Blockchain & AI" },
  { id: "sharing", label: "Sharing & sub-processors" },
  { id: "transfers", label: "International transfers" },
  { id: "retention", label: "Retention" },
  { id: "rights", label: "Your rights" },
  { id: "security", label: "Security" },
  { id: "cookies", label: "Cookies" },
  { id: "contact", label: "Contact" },
];

function PendingTag() {
  return (
    <span className="ml-1 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-800">
      pending legal confirmation
    </span>
  );
}

export default function PrivacyPolicyPage() {
  return (
    <div className="flex min-h-screen flex-col bg-[color:var(--color-paper-white)]">
      {/* NAV */}
      <header className="sticky top-0 z-30 border-b border-[color:var(--color-stone)]/70 bg-[color:var(--color-cream)]/85 backdrop-blur">
        <nav className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
          <Link
            href="/"
            className="flex items-center gap-2 font-semibold tracking-tight text-[color:var(--color-espresso)]"
          >
            <Image
              src="/etornie-logo.png"
              alt="Etornie logo"
              width={32}
              height={32}
              priority
              className="h-8 w-8"
            />
            Etornie
          </Link>
          <Link
            href="/legal/terms"
            className="text-sm font-medium text-[color:var(--color-muted)] hover:text-[color:var(--color-accent)]"
          >
            Terms of Service →
          </Link>
        </nav>
      </header>

      <main className="mx-auto w-full max-w-4xl px-6 py-10">
        {/* DRAFT banner */}
        <div className="mb-8 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
          <p className="font-semibold">Draft: pending legal review</p>
          <p className="mt-1">
            This Privacy Policy is a working draft prepared from the
            platform&apos;s actual data-processing activities. The final,
            binding text must be reviewed and issued by a qualified Swiss and
            EU data-protection lawyer before publication. Items still requiring
            legal confirmation are tagged inline.
          </p>
        </div>

        <h1 className="text-3xl font-semibold tracking-tight text-[color:var(--color-espresso)]">
          Privacy Policy
        </h1>
        <p className="mt-2 text-sm text-[color:var(--color-muted)]">
          Applicable law: EU General Data Protection Regulation (GDPR) and the
          Swiss Federal Act on Data Protection (FADP). · Version: Draft 1.0
        </p>

        {/* TOC */}
        <nav className="mt-6 flex flex-wrap gap-2">
          {SECTIONS.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className="rounded-full border border-[color:var(--color-stone)] px-3 py-1 text-xs font-medium text-[color:var(--color-muted)] hover:border-[color:var(--color-accent)] hover:text-[color:var(--color-accent)]"
            >
              {s.label}
            </a>
          ))}
        </nav>

        <div className="prose-legal mt-8 space-y-8 text-sm leading-relaxed text-[color:var(--color-ink)]">
          <section id="controller" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              1. Data controller
            </h2>
            <p>
              The controller responsible for processing your personal data is:
            </p>
            <address className="not-italic rounded-lg border border-[color:var(--color-stone)] bg-[color:var(--color-elevated)] p-4">
              <strong>{CONTROLLER.name}</strong>
              <br />
              {CONTROLLER.address}
              <br />
              Company identification number (UID): {CONTROLLER.uid}
              <br />
              Contact:{" "}
              <a
                href={`mailto:${CONTROLLER.contactEmail}`}
                className="text-[color:var(--color-accent)] hover:underline"
              >
                {CONTROLLER.contactEmail}
              </a>
            </address>
            <p>
              Etornie has not appointed a statutory Data Protection Officer
              (DPO)
              <PendingTag />; data-protection enquiries are handled via the
              contact address above. Etornie has not appointed an EU/Swiss
              representative
              <PendingTag />.
            </p>
          </section>

          <section id="data" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              2. Personal data we process
            </h2>
            <ul className="list-disc space-y-1 pl-5">
              <li>
                <strong>Account data:</strong> email address, full name, phone
                number (optional), hashed password, and account role.
              </li>
              <li>
                <strong>Wallet identity:</strong> your Solana wallet address and
                a derived public handle, when you sign in with a wallet.
              </li>
              <li>
                <strong>Profile data:</strong> profile picture (optional) and
                notification preferences.
              </li>
              <li>
                <strong>Case & IP data:</strong> intellectual-property cases,
                trademark/patent/design details, applicant information, uploaded
                documents and any personal data they contain.
              </li>
              <li>
                <strong>Payment data:</strong> subscription and filing payment
                records, amounts and status. Card details are processed directly
                by Stripe; Etornie does not store full card numbers.
              </li>
              <li>
                <strong>AI assistant data:</strong> the questions, messages and
                files you submit to EtornieGPT and the IP agent.
              </li>
              <li>
                <strong>E-signature data:</strong> signer name and email when a
                document is sent for electronic signature.
              </li>
              <li>
                <strong>Technical data:</strong> log data, device/IP information,
                and error diagnostics necessary to operate and secure the
                service.
              </li>
            </ul>
          </section>

          <section id="purposes" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              3. Purposes & legal bases
            </h2>
            <p>We process personal data on the following GDPR Art. 6 bases:</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>
                <strong>Performance of a contract</strong> (Art. 6(1)(b)):
                creating and operating your account, managing IP cases, filing
                with IP offices, processing payments and signatures.
              </li>
              <li>
                <strong>Legal obligation</strong> (Art. 6(1)(c)): retaining
                financial and tax records and meeting regulatory duties.
              </li>
              <li>
                <strong>Legitimate interests</strong> (Art. 6(1)(f)): securing
                the platform, preventing fraud and abuse, and improving the
                service, balanced against your rights.
              </li>
              <li>
                <strong>Consent</strong> (Art. 6(1)(a)): optional notification
                emails and any non-essential processing; withdrawable at any
                time.
              </li>
            </ul>
            <p>
              Under the Swiss FADP, processing is carried out in good faith,
              proportionately, and for the purposes stated at collection.
            </p>
          </section>

          <section id="blockchain" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              4. Blockchain &amp; AI processing
            </h2>
            <p>
              <strong>Blockchain (Solana).</strong> Etornie records IP
              attestations, compliance proofs and token mints on the public
              Solana blockchain. Data written on-chain, including wallet
              addresses, transaction signatures and cryptographic commitments,
              is <strong>public and immutable</strong> and{" "}
              <strong>cannot be modified or deleted</strong>, including in
              response to an erasure request. Off-chain personal data linking
              you to on-chain records is erased on request; the on-chain
              artefacts themselves remain by design. We use commitments and
              zero-knowledge proofs to minimise the personal data exposed
              on-chain.
            </p>
            <p>
              <strong>AI assistant.</strong> Prompts and documents you submit to
              the AI features are sent to our inference sub-processor (Together
              AI) to generate responses. We do not use your content to train
              third-party foundation models
              <PendingTag />.
            </p>
          </section>

          <section id="sharing" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              5. Sharing &amp; sub-processors
            </h2>
            <p>
              We share personal data with the processors below, each bound by a
              data-processing agreement, and with intellectual-property offices
              (e.g. EUIPO, UKIPO) where you instruct us to make a filing. We do
              not sell personal data.
            </p>
            <div className="overflow-x-auto">
              <table className="mt-2 w-full border-collapse text-left text-xs">
                <thead>
                  <tr className="border-b border-[color:var(--color-stone)] text-[color:var(--color-muted)]">
                    <th className="py-2 pr-4 font-semibold">Sub-processor</th>
                    <th className="py-2 pr-4 font-semibold">Purpose</th>
                    <th className="py-2 font-semibold">Location</th>
                  </tr>
                </thead>
                <tbody>
                  {SUB_PROCESSORS.map((p) => (
                    <tr
                      key={p.name}
                      className="border-b border-[color:var(--color-stone)]/50"
                    >
                      <td className="py-2 pr-4 font-medium">{p.name}</td>
                      <td className="py-2 pr-4">{p.purpose}</td>
                      <td className="py-2">{p.location}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-[color:var(--color-muted)]">
              The exact list of sub-processors and their locations is subject to
              legal confirmation.
              <PendingTag />
            </p>
          </section>

          <section id="transfers" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              6. International transfers
            </h2>
            <p>
              Where personal data is transferred outside Switzerland or the
              EU/EEA (e.g. to US-based sub-processors), we rely on appropriate
              safeguards such as the European Commission&apos;s Standard
              Contractual Clauses together with the Swiss addendum recognised by
              the Federal Data Protection and Information Commissioner (FDPIC),
              or an applicable adequacy decision.
              <PendingTag />
            </p>
          </section>

          <section id="retention" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              7. Retention
            </h2>
            <p>
              We keep personal data only as long as necessary for the purposes
              above. Account and case data are retained for the life of your
              account; financial records are retained for the statutory period
              (approximately ten years under Swiss law)
              <PendingTag />; immutable on-chain data persists indefinitely by
              the nature of the blockchain. On erasure, data without a retention
              basis is deleted and the remaining records are anonymised.
            </p>
          </section>

          <section id="rights" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              8. Your rights
            </h2>
            <p>
              Subject to the GDPR and FADP, you have the right to access,
              rectify, erase, restrict and object to processing, to data
              portability, and to withdraw consent. Etornie provides
              self-service tools to{" "}
              <strong>export your data</strong> (right to portability) and to{" "}
              <strong>erase your account</strong> (right to erasure) from your
              profile page, subject to legal retention obligations.
            </p>
            <p>
              You may lodge a complaint with a supervisory authority: in
              Switzerland, the Federal Data Protection and Information
              Commissioner (FDPIC); in the EU, your local data-protection
              authority.
            </p>
          </section>

          <section id="security" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              9. Security
            </h2>
            <p>
              We apply technical and organisational measures appropriate to the
              risk, including encryption of credentials and sensitive secrets,
              optional two-factor authentication, antivirus scanning of uploads,
              access controls, and audit logging. No method of transmission or
              storage is completely secure, and we cannot guarantee absolute
              security.
            </p>
          </section>

          <section id="cookies" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              10. Cookies
            </h2>
            <p>
              Etornie uses strictly necessary cookies to keep you signed in
              (authentication tokens). We do not use advertising cookies. Any
              future analytics cookies will be subject to your consent.
              <PendingTag />
            </p>
          </section>

          <section id="contact" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              11. Contact &amp; changes
            </h2>
            <p>
              For any privacy enquiry or to exercise your rights, contact{" "}
              <a
                href={`mailto:${CONTROLLER.contactEmail}`}
                className="text-[color:var(--color-accent)] hover:underline"
              >
                {CONTROLLER.contactEmail}
              </a>
              . We will update this policy as our processing evolves and will
              indicate the effective date on publication.
            </p>
          </section>

          <section className="rounded-lg border border-[color:var(--color-stone)] bg-[color:var(--color-elevated)] p-4">
            <h2 className="text-base font-semibold text-[color:var(--color-espresso)]">
              Open items for legal review
            </h2>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-[color:var(--color-muted)]">
              <li>Confirm DPO / EU &amp; Swiss representative appointment (or documented exemption).</li>
              <li>Confirm the definitive sub-processor list, locations and DPAs.</li>
              <li>Confirm international-transfer mechanism (SCCs + Swiss addendum / adequacy).</li>
              <li>Confirm statutory retention periods and their legal basis.</li>
              <li>Confirm AI sub-processor data-use / training terms.</li>
              <li>Confirm cookie and analytics consent approach.</li>
              <li>Set the effective date on legal sign-off.</li>
            </ul>
          </section>
        </div>
      </main>

      <footer className="mt-auto border-t border-[color:var(--color-stone)]/70 px-6 py-6 text-center text-xs text-[color:var(--color-muted)]">
        © {CONTROLLER.name} ·{" "}
        <Link href="/legal/terms" className="hover:text-[color:var(--color-accent)]">
          Terms of Service
        </Link>{" "}
        ·{" "}
        <Link href="/" className="hover:text-[color:var(--color-accent)]">
          Home
        </Link>
      </footer>
    </div>
  );
}
