import Link from "next/link";
import Image from "next/image";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms of Service | Etornie",
  description:
    "The terms governing use of the Etornie platform, provided by Etornie AG under Swiss law.",
};

// Terms of Service (issue #58): standard B2B SaaS terms governed by Swiss
// law (Canton of Zug), prepared from how the platform operates. Liability
// wording follows Swiss CO Art. 100 (intent/gross negligence cannot be
// excluded).

const PROVIDER = {
  name: "Etornie AG",
  address: "Ruessenstrasse 5, 6340 Baar, Zug, Switzerland",
  uid: "CHE-482.609.557",
  // Temporary contact address pending a dedicated legal mailbox.
  contactEmail: "support@etornie.com",
  governingLaw: "Switzerland",
  forum: "the courts of the Canton of Zug, Switzerland",
} as const;

interface Section {
  readonly id: string;
  readonly label: string;
}

const SECTIONS: readonly Section[] = [
  { id: "provider", label: "Provider" },
  { id: "scope", label: "Scope & acceptance" },
  { id: "service", label: "The service" },
  { id: "accounts", label: "Accounts" },
  { id: "acceptable-use", label: "Acceptable use" },
  { id: "fees", label: "Fees & payment" },
  { id: "ip", label: "Intellectual property" },
  { id: "customer-data", label: "Customer data" },
  { id: "third-parties", label: "Third parties & blockchain" },
  { id: "no-legal-advice", label: "No legal advice" },
  { id: "availability", label: "Availability" },
  { id: "warranties", label: "Warranties" },
  { id: "liability", label: "Liability" },
  { id: "term", label: "Term & termination" },
  { id: "changes", label: "Changes" },
  { id: "law", label: "Governing law" },
  { id: "misc", label: "Miscellaneous" },
];

export default function TermsOfServicePage() {
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
            href="/legal/privacy"
            className="text-sm font-medium text-[color:var(--color-muted)] hover:text-[color:var(--color-accent)]"
          >
            Privacy Policy →
          </Link>
        </nav>
      </header>

      <main className="mx-auto w-full max-w-4xl px-6 py-10">
        <h1 className="text-3xl font-semibold tracking-tight text-[color:var(--color-espresso)]">
          Terms of Service
        </h1>
        <p className="mt-2 text-sm text-[color:var(--color-muted)]">
          Business-to-business SaaS terms governed by Swiss law. · Version 1.0 ·
          Effective 7 June 2026
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

        <div className="mt-8 space-y-8 text-sm leading-relaxed text-[color:var(--color-ink)]">
          <section id="provider" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              1. Provider
            </h2>
            <p>The Etornie platform is provided by:</p>
            <address className="not-italic rounded-lg border border-[color:var(--color-stone)] bg-[color:var(--color-elevated)] p-4">
              <strong>{PROVIDER.name}</strong>
              <br />
              {PROVIDER.address}
              <br />
              Company identification number (UID): {PROVIDER.uid}
              <br />
              Contact:{" "}
              <a
                href={`mailto:${PROVIDER.contactEmail}`}
                className="text-[color:var(--color-accent)] hover:underline"
              >
                {PROVIDER.contactEmail}
              </a>
            </address>
            <p>
              &quot;Etornie&quot;, &quot;we&quot;, &quot;us&quot; refers to{" "}
              {PROVIDER.name}; &quot;you&quot; or &quot;Customer&quot; refers to
              the business entity using the platform.
            </p>
          </section>

          <section id="scope" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              2. Scope &amp; acceptance
            </h2>
            <p>
              These Terms govern your access to and use of the Etornie platform
              and related services. By creating an account or using the service
              you agree to these Terms. The service is intended for
              <strong> business and professional use</strong> (B2B); it is not
              directed at consumers. If you accept on behalf of an organisation,
              you confirm you are authorised to bind it.
            </p>
          </section>

          <section id="service" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              3. The service
            </h2>
            <p>
              Etornie is a software platform for managing intellectual-property
              assets: case management, document handling, an AI assistant,
              electronic signatures, payments, automated filing assistance with
              intellectual-property offices, and recording of attestations and
              tokens on the Solana blockchain. We grant you a non-exclusive,
              non-transferable right to use the service during your subscription
              for your internal business purposes.
            </p>
          </section>

          <section id="accounts" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              4. Accounts &amp; security
            </h2>
            <p>
              You are responsible for the accuracy of your registration data,
              for safeguarding your credentials (and wallet keys, where wallet
              sign-in is used), and for all activity under your account. We
              recommend enabling two-factor authentication. Notify us promptly
              of any unauthorised use.
            </p>
          </section>

          <section id="acceptable-use" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              5. Acceptable use
            </h2>
            <p>You agree not to:</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>use the service unlawfully or to infringe third-party rights;</li>
              <li>upload malware, or attempt to breach or probe security controls;</li>
              <li>
                submit content you are not entitled to, or that is false or
                misleading in a filing;
              </li>
              <li>
                reverse-engineer, resell, or overload the service beyond fair
                use;
              </li>
              <li>misuse the AI features to generate unlawful content.</li>
            </ul>
            <p>
              We may suspend access for material breach, security risk, or
              non-payment, with notice where practicable.
            </p>
          </section>

          <section id="fees" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              6. Fees &amp; payment
            </h2>
            <p>
              Subscription and transaction fees are billed through our payment
              processor (Stripe). Fees are stated exclusive of value-added tax
              unless indicated; applicable taxes are added at checkout.
              Official intellectual-property-office fees and blockchain network
              fees are separate and may be passed through. Unless required by
              law, fees already paid are non-refundable.
            </p>
          </section>

          <section id="ip" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              7. Intellectual property
            </h2>
            <p>
              The platform, its software, and its branding are and remain the
              property of Etornie and its licensors. You retain all rights in
              the content and data you submit (&quot;Customer Content&quot;). You
              grant Etornie a limited licence to host and process Customer
              Content solely to provide the service.
            </p>
          </section>

          <section id="customer-data" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              8. Customer data &amp; privacy
            </h2>
            <p>
              Our handling of personal data is described in the{" "}
              <Link
                href="/legal/privacy"
                className="text-[color:var(--color-accent)] hover:underline"
              >
                Privacy Policy
              </Link>
              . You are responsible for ensuring you have the rights to submit
              Customer Content and any personal data it contains.
            </p>
          </section>

          <section id="third-parties" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              9. Third-party services &amp; blockchain
            </h2>
            <p>
              The service relies on third parties (e.g. payment, e-signature,
              AI inference, and blockchain infrastructure) whose own terms may
              apply. Actions recorded on the Solana blockchain are{" "}
              <strong>public, irreversible and cannot be undone</strong>; you
              acknowledge this before initiating on-chain operations.
              Intellectual-property-office filings are subject to those
              offices&apos; rules, timelines, and decisions, which are outside
              our control.
            </p>
          </section>

          <section id="no-legal-advice" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              10. No legal advice
            </h2>
            <p>
              Etornie is a software provider, not a law firm, and does not
              provide legal advice. Information and AI-generated output are for
              general informational and workflow purposes only, may be
              inaccurate or incomplete, and are not a substitute for advice from
              a qualified professional. You are responsible for your filing
              decisions.
            </p>
          </section>

          <section id="availability" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              11. Availability
            </h2>
            <p>
              We aim for high availability but do not guarantee uninterrupted or
              error-free operation. Maintenance, updates, or factors outside our
              control may cause downtime. Any specific service levels, if
              offered, will be set out in a separate agreement.
            </p>
          </section>

          <section id="warranties" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              12. Warranties
            </h2>
            <p>
              To the extent permitted by law, the service is provided &quot;as
              is&quot; and &quot;as available&quot; without warranties of any
              kind, whether express or implied, including fitness for a
              particular purpose. Mandatory statutory warranties under Swiss law
              remain unaffected.
            </p>
          </section>

          <section id="liability" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              13. Limitation of liability
            </h2>
            <p>
              To the extent permitted by Swiss law, Etornie is liable only for
              damage caused by intent or gross negligence; liability for slight
              negligence, indirect or consequential damage, lost profits, and
              loss of data is excluded. Mandatory liability (e.g. for unlawful
              intent, gross negligence, or personal injury) remains unaffected.
              To the extent permitted by law, Etornie&apos;s aggregate liability
              is limited to the fees you paid for the service in the twelve
              months preceding the event giving rise to the claim.
            </p>
          </section>

          <section id="term" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              14. Term &amp; termination
            </h2>
            <p>
              These Terms apply for as long as you use the service. You may stop
              using it and close your account at any time; we may terminate or
              suspend for material breach or non-payment. On termination, your
              right to use the service ends. Data handling after termination
              (including export and erasure) is described in the Privacy Policy;
              records subject to statutory retention are kept as required by law.
            </p>
          </section>

          <section id="changes" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              15. Changes to these Terms
            </h2>
            <p>
              We may update these Terms to reflect changes to the service or the
              law. Material changes will be notified through the platform or by
              email; continued use after the effective date constitutes
              acceptance.
            </p>
          </section>

          <section id="law" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              16. Governing law &amp; jurisdiction
            </h2>
            <p>
              These Terms are governed by the substantive law of{" "}
              {PROVIDER.governingLaw}, excluding its conflict-of-laws rules and
              the United Nations Convention on Contracts for the International
              Sale of Goods (CISG). The exclusive place of jurisdiction is{" "}
              {PROVIDER.forum}, subject to any mandatory statutory forum.
            </p>
          </section>

          <section id="misc" className="space-y-2">
            <h2 className="text-lg font-semibold text-[color:var(--color-espresso)]">
              17. Miscellaneous
            </h2>
            <p>
              If any provision is invalid, the remainder stays in effect and the
              invalid provision is replaced by a valid one closest to its
              intent. We may assign these Terms to an affiliate or successor. No
              waiver is implied by delay. These Terms, with the Privacy Policy
              and any order form, are the entire agreement between the parties.
            </p>
            <p>
              Questions about these Terms:{" "}
              <a
                href={`mailto:${PROVIDER.contactEmail}`}
                className="text-[color:var(--color-accent)] hover:underline"
              >
                {PROVIDER.contactEmail}
              </a>
              .
            </p>
          </section>

        </div>
      </main>

      <footer className="mt-auto border-t border-[color:var(--color-stone)]/70 px-6 py-6 text-center text-xs text-[color:var(--color-muted)]">
        © {PROVIDER.name} ·{" "}
        <Link
          href="/legal/privacy"
          className="hover:text-[color:var(--color-accent)]"
        >
          Privacy Policy
        </Link>{" "}
        ·{" "}
        <Link href="/" className="hover:text-[color:var(--color-accent)]">
          Home
        </Link>
      </footer>
    </div>
  );
}
