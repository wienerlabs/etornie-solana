import Link from "next/link";

interface Feature {
  readonly title: string;
  readonly body: string;
  readonly icon: string;
}

const FEATURES: readonly Feature[] = [
  {
    title: "Tokenized IP",
    body: "Mint trademarks, patents, designs, and copyrights as compliant SPL-based assets with verifiable lifecycle.",
    icon: "M13 2L3 14h9l-1 8 10-12h-9l1-8z",
  },
  {
    title: "On-Chain Custody",
    body: "Every case milestone, from filings to renewals and assignments, attested with an immutable audit trail.",
    icon: "M12 15v2m0 0v3m0-3h.01M9 12V7a3 3 0 016 0v5m-9 0h12a2 2 0 012 2v7a2 2 0 01-2 2H6a2 2 0 01-2-2v-7a2 2 0 012-2z",
  },
  {
    title: "EtornieGPT Agent",
    body: "LLM-powered IP assistant with RAG over your portfolio, deadlines, and jurisdiction-specific rules.",
    icon: "M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z",
  },
  {
    title: "RWA Ready",
    body: "Bridge real-world intellectual assets into programmable on-chain primitives. Collateralize, license, or fractionalize.",
    icon: "M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z",
  },
  {
    title: "Compliance-First",
    body: "Jurisdiction-aware workflows aligned with EUIPO, IP Australia, and national IP offices. Audit-ready exports.",
    icon: "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z",
  },
  {
    title: "Enterprise-Grade",
    body: "Role-based access for admins, lawyers, and clients. Secrets managed, encrypted transport, SOC-friendly.",
    icon: "M17 20h5v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2h5m7-8a4 4 0 11-8 0 4 4 0 018 0z",
  },
];

const TRUST_STATS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "100%", label: "On-chain attested" },
  { value: "< 2s", label: "Settlement" },
  { value: "$0.0005", label: "Cost per attestation" },
  { value: "24/7", label: "Protocol uptime" },
];

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col">
      {/* NAV */}
      <header className="sticky top-0 z-30 border-b border-[color:var(--color-stone)]/70 bg-[color:var(--color-cream)]/85 backdrop-blur">
        <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link
            href="/"
            className="flex items-center gap-2 font-semibold tracking-tight text-[color:var(--color-espresso)]"
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-[color:var(--color-bronze)] to-[color:var(--color-espresso)] text-[color:var(--color-cream)] text-sm font-bold">
              E
            </span>
            Etornie <span className="text-[color:var(--color-bronze)]">Solana</span>
          </Link>
          <div className="hidden items-center gap-8 text-sm text-[color:var(--color-muted)] md:flex">
            <a
              href="#product"
              className="hover:text-[color:var(--color-bronze)]"
            >
              Product
            </a>
            <a
              href="#rwa"
              className="hover:text-[color:var(--color-bronze)]"
            >
              RWA
            </a>
            <a
              href="#enterprise"
              className="hover:text-[color:var(--color-bronze)]"
            >
              Enterprise
            </a>
            <Link
              href="/docs"
              className="hover:text-[color:var(--color-bronze)]"
            >
              Docs
            </Link>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/login"
              className="rwa-btn-secondary text-sm"
            >
              Sign In
            </Link>
            <Link href="/register" className="rwa-btn-primary">
              Get Started
            </Link>
          </div>
        </nav>
      </header>

      {/* HERO */}
      <section className="relative overflow-hidden">
        <div
          className="pointer-events-none absolute inset-0 -z-10 opacity-60"
          aria-hidden="true"
          style={{
            background:
              "radial-gradient(circle at 70% 20%, rgba(153, 69, 255, 0.12), transparent 40%), radial-gradient(circle at 20% 80%, rgba(20, 241, 149, 0.10), transparent 45%)",
          }}
        />
        <div className="mx-auto max-w-6xl px-6 pt-16 pb-24 md:pt-24 md:pb-32">
          <div className="mx-auto max-w-3xl text-center">
            <span className="chain-badge">
              <span className="chain-dot" />
              Live on Solana · Devnet
            </span>
            <h1 className="mt-6 text-4xl font-semibold leading-[1.1] tracking-tight text-[color:var(--color-espresso)] md:text-6xl">
              Modern intellectual<br />property custody.<br />
              <span className="bg-gradient-to-r from-[color:var(--color-bronze)] via-[color:var(--color-gold)] to-[color:var(--color-bronze-dark)] bg-clip-text text-transparent">
                Built for the next era of assets.
              </span>
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-base text-[color:var(--color-muted)] md:text-lg">
              Etornie Solana is an institutional-grade platform for managing
              trademarks, patents, designs, and copyrights. Governed by your
              counsel, structured for audit, and ready to evolve with the next
              generation of asset infrastructure.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link href="/register" className="rwa-btn-primary px-6 py-3">
                Start Free Trial
              </Link>
              <Link href="/login" className="rwa-btn-secondary px-6 py-3">
                Sign in to Dashboard
              </Link>
            </div>
            <div className="mt-10 flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-xs font-medium uppercase tracking-wider text-[color:var(--color-muted)]">
              <span>EUIPO-aware</span>
              <span>·</span>
              <span>IP Australia-aware</span>
              <span>·</span>
              <span>SOC-friendly</span>
              <span>·</span>
              <span>SPL Compliant</span>
            </div>
          </div>
        </div>
      </section>

      {/* WHAT IS / CRYPTO-NATIVE */}
      <section id="product" className="px-6 py-16 md:py-24">
        <div className="mx-auto grid max-w-6xl gap-10 md:grid-cols-2 md:gap-16">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-[color:var(--color-bronze)]">
              What is Etornie Solana?
            </p>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-[color:var(--color-espresso)] md:text-4xl">
              IP custody, rewritten as on-chain RWA.
            </h2>
            <p className="mt-5 text-[color:var(--color-muted)]">
              Traditional IP portfolios live inside PDFs, emails, and siloed
              dockets. Etornie Solana turns each IP asset into a programmable
              primitive: every filing, renewal, or assignment is a signed,
              timestamped on-chain event.
            </p>
            <p className="mt-3 text-[color:var(--color-muted)]">
              The result is an IP estate that is composable with DeFi, auditable
              by regulators, and effortless to transfer, license, or collateralize.
            </p>
          </div>
          <div className="rwa-card p-6">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
              On-chain IP lifecycle
            </h3>
            <ol className="mt-5 space-y-4">
              {[
                { t: "Intake", d: "Case opened. Metadata hashed, attestation minted." },
                { t: "Prosecution", d: "Filings anchored on-chain with jurisdiction tag." },
                { t: "Registration", d: "Granted rights tokenized as SPL asset." },
                { t: "Renewal", d: "Automatic reminders; renewals signed on-chain." },
                { t: "Transfer", d: "Assignment, license, or collateralization on-chain." },
              ].map((step, i) => (
                <li
                  key={step.t}
                  className="flex items-start gap-4 border-l-2 border-[color:var(--color-gold)] pl-4"
                >
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[color:var(--color-linen)] text-xs font-bold text-[color:var(--color-bronze-dark)]">
                    {i + 1}
                  </span>
                  <div>
                    <p className="font-semibold text-[color:var(--color-espresso)]">
                      {step.t}
                    </p>
                    <p className="text-sm text-[color:var(--color-muted)]">
                      {step.d}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      {/* FEATURES GRID */}
      <section id="rwa" className="bg-[color:var(--color-linen)]/60 px-6 py-16 md:py-24">
        <div className="mx-auto max-w-6xl">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-xs font-semibold uppercase tracking-widest text-[color:var(--color-bronze)]">
              Platform capabilities
            </p>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-[color:var(--color-espresso)] md:text-4xl">
              Built for law firms. Native to Solana.
            </h2>
          </div>
          <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <div key={f.title} className="rwa-card p-6">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-[color:var(--color-bronze)] to-[color:var(--color-espresso)] text-[color:var(--color-cream)]">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    className="h-5 w-5"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={1.75}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d={f.icon}
                    />
                  </svg>
                </div>
                <h3 className="mt-4 text-lg font-semibold text-[color:var(--color-espresso)]">
                  {f.title}
                </h3>
                <p className="mt-2 text-sm text-[color:var(--color-muted)]">
                  {f.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ENTERPRISE / TRUST */}
      <section id="enterprise" className="px-6 py-16 md:py-24">
        <div className="mx-auto max-w-6xl rounded-2xl bg-gradient-to-br from-[color:var(--color-espresso)] to-[#160f08] p-10 text-[color:var(--color-cream)] md:p-16">
          <div className="grid gap-10 md:grid-cols-2 md:gap-16">
            <div>
              <p className="text-xs font-semibold uppercase tracking-widest text-[color:var(--color-gold)]">
                Enterprise-grade trust
              </p>
              <h2 className="mt-3 text-3xl font-semibold tracking-tight md:text-4xl">
                Institutional controls, retail-grade speed.
              </h2>
              <p className="mt-5 text-[color:var(--color-linen)]/80">
                Role-based access, OTP-verified onboarding, audit logs, WhatsApp
                and email notification rails, and a compliance model that fits
                law-firm workflows, delivered with the settlement speed and
                cost profile of a modern asset infrastructure.
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <Link
                  href="/register"
                  className="rounded-lg bg-[color:var(--color-gold)] px-6 py-3 text-sm font-semibold text-[color:var(--color-espresso)] transition-all hover:bg-[color:var(--color-gold-soft)]"
                >
                  Book a Demo
                </Link>
                <Link
                  href="/login"
                  className="rounded-lg border border-[color:var(--color-gold)]/40 px-6 py-3 text-sm font-semibold text-[color:var(--color-linen)] transition-all hover:bg-[color:var(--color-espresso-soft)]"
                >
                  Access Dashboard →
                </Link>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-6">
              {TRUST_STATS.map((stat) => (
                <div
                  key={stat.label}
                  className="rounded-xl border border-[color:var(--color-gold)]/25 bg-[color:var(--color-espresso-soft)]/60 p-5"
                >
                  <p className="text-2xl font-semibold text-[color:var(--color-gold)] md:text-3xl">
                    {stat.value}
                  </p>
                  <p className="mt-1 text-xs uppercase tracking-wider text-[color:var(--color-linen)]/70">
                    {stat.label}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="mt-auto border-t border-[color:var(--color-stone)] bg-[color:var(--color-cream)] px-6 py-8">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 text-xs text-[color:var(--color-muted)] md:flex-row">
          <p>
            © {new Date().getFullYear()} Etornie Solana · All rights reserved.
          </p>
          <p className="font-mono">
            etornie.sol · v0.1.0 · Devnet
          </p>
        </div>
      </footer>
    </div>
  );
}
