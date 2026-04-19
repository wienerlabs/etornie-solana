import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Docs | Etornie Solana",
  description:
    "Overview, roles, workflows, and technical reference for the Etornie Solana platform.",
};

interface Section {
  readonly id: string;
  readonly label: string;
}

const SECTIONS: readonly Section[] = [
  { id: "overview", label: "Overview" },
  { id: "roles", label: "Roles" },
  { id: "auth", label: "Authentication" },
  { id: "cases", label: "Case Lifecycle" },
  { id: "documents", label: "Documents" },
  { id: "ai", label: "AI Assistant" },
  { id: "notifications", label: "Notifications" },
  { id: "ip-agent", label: "IP Agent" },
  { id: "api", label: "API Reference" },
  { id: "stack", label: "Tech Stack" },
  { id: "roadmap", label: "Roadmap" },
  { id: "faq", label: "FAQ" },
];

export default function DocsPage() {
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
            <Link href="/#product" className="hover:text-[color:var(--color-bronze)]">
              Product
            </Link>
            <Link href="/#rwa" className="hover:text-[color:var(--color-bronze)]">
              RWA
            </Link>
            <Link
              href="/docs"
              className="font-semibold text-[color:var(--color-bronze)]"
            >
              Docs
            </Link>
          </div>
          <div className="flex items-center gap-3">
            <Link href="/login" className="rwa-btn-secondary text-sm">
              Sign In
            </Link>
            <Link href="/register" className="rwa-btn-primary">
              Get Started
            </Link>
          </div>
        </nav>
      </header>

      {/* HERO */}
      <section className="border-b border-[color:var(--color-stone)] bg-[color:var(--color-linen)]/40 px-6 py-16">
        <div className="mx-auto max-w-6xl">
          <span className="chain-badge">
            <span className="chain-dot" />
            Documentation
          </span>
          <h1 className="mt-4 text-4xl font-semibold tracking-tight text-[color:var(--color-espresso)] md:text-5xl">
            Etornie Solana Docs
          </h1>
          <p className="mt-3 max-w-2xl text-base text-[color:var(--color-muted)] md:text-lg">
            A concise tour of the platform. What it does, who it serves, and
            how its pieces fit together.
          </p>
        </div>
      </section>

      {/* BODY */}
      <section className="px-6 py-12">
        <div className="mx-auto grid max-w-6xl gap-10 md:grid-cols-[220px_1fr]">
          {/* TOC */}
          <aside className="md:sticky md:top-24 md:self-start">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
              Contents
            </p>
            <nav className="flex flex-col gap-1 text-sm">
              {SECTIONS.map((s) => (
                <a
                  key={s.id}
                  href={`#${s.id}`}
                  className="rounded-md px-2 py-1.5 text-[color:var(--color-ink)] transition-colors hover:bg-[color:var(--color-linen)] hover:text-[color:var(--color-bronze)]"
                >
                  {s.label}
                </a>
              ))}
            </nav>
          </aside>

          {/* CONTENT */}
          <article className="space-y-16 text-[color:var(--color-ink)]">
            <Article
              id="overview"
              title="Overview"
              intro="Etornie Solana is an end-to-end platform for intellectual property custody and case management, evolving toward a Real-World-Asset model on Solana."
            >
              <p>
                The product covers the full lifecycle of an IP case: intake,
                prosecution, registration, renewal, and transfer. Every
                touchpoint is captured with role-based access, audit-ready
                exports, and structured notifications.
              </p>
              <p>
                A web dashboard coordinates lawyers, clients, and platform
                admins. An AI assistant provides retrieval-augmented answers
                over your portfolio. Future iterations will anchor key events
                on Solana for verifiable provenance.
              </p>
            </Article>

            <Article
              id="roles"
              title="Roles"
              intro="Three roles drive the permission model. Pick the one that matches how your team works."
            >
              <RoleCard
                name="Admin"
                color="text-[color:var(--color-bronze-dark)]"
                items={[
                  "Manage users and roles.",
                  "Configure IP Agent intervals, scan deadlines.",
                  "Access every case and audit log.",
                  "Register privileged accounts via the admin endpoint.",
                ]}
              />
              <RoleCard
                name="Lawyer"
                color="text-[color:var(--color-solana-purple)]"
                items={[
                  "See cases assigned to them plus guest cases.",
                  "Create cases for registered or guest clients.",
                  "Update case status, add notes and documents.",
                  "Send scheduled or instant notifications.",
                ]}
              />
              <RoleCard
                name="Client"
                color="text-[color:var(--color-solana-green)]"
                items={[
                  "See only their own cases.",
                  "Read notes and documents shared with them.",
                  "Chat with the AI assistant on their matters.",
                ]}
              />
            </Article>

            <Article
              id="auth"
              title="Authentication"
              intro="Two paths into the platform: classic email sign-in and, upcoming, wallet-based sign-in for Solana-native users."
            >
              <SubHeading>Email + OTP</SubHeading>
              <ol className="list-decimal space-y-1.5 pl-5 text-[color:var(--color-ink)]">
                <li>
                  Request a verification code on the register page. A six
                  digit OTP is emailed through EmailJS.
                </li>
                <li>
                  Confirm the code to complete registration. An access token
                  and refresh token are issued.
                </li>
                <li>
                  Guest cases matching your email or phone are auto-linked to
                  the new account.
                </li>
              </ol>

              <SubHeading>Wallet sign-in (upcoming)</SubHeading>
              <p>
                Phantom and Solflare will be supported. The flow will mint a
                nonce, sign it with the wallet, and verify the signature
                server-side. Wallet-only users receive a short public handle
                such as <Code>etornie_5xK9aBcD</Code> they can share for case
                assignment.
              </p>

              <SubHeading>Sessions</SubHeading>
              <p>
                Access tokens default to 30 minutes. Refresh tokens extend to
                seven days and can be rotated at <Code>/auth/refresh</Code>.
              </p>
            </Article>

            <Article
              id="cases"
              title="Case Lifecycle"
              intro="IP cases follow a defined status flow that is reflected across the dashboard, notifications, and audit exports."
            >
              <ul className="space-y-2">
                {[
                  {
                    label: "Open",
                    desc: "Newly created, awaiting assignment or first filing.",
                  },
                  {
                    label: "In Progress",
                    desc: "Active prosecution or administrative work.",
                  },
                  {
                    label: "Under Review",
                    desc: "Awaiting validation, opposition, or client confirmation.",
                  },
                  {
                    label: "Completed",
                    desc: "Registered, closed, or otherwise finalized.",
                  },
                ].map((s) => (
                  <li key={s.label} className="flex gap-3">
                    <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-[color:var(--color-gold)]" />
                    <div>
                      <p className="font-semibold text-[color:var(--color-espresso)]">
                        {s.label}
                      </p>
                      <p className="text-sm text-[color:var(--color-muted)]">
                        {s.desc}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
              <p>
                Each case receives an auto-generated reference in the form{" "}
                <Code>ETR-YYYY-NNNN</Code>. Jurisdiction, filing date, and
                deadline are tracked for downstream reminders.
              </p>
            </Article>

            <Article
              id="documents"
              title="Documents"
              intro="Files live on the server filesystem, scoped to their parent case."
            >
              <ul className="list-disc space-y-1.5 pl-5">
                <li>
                  Uploads are accepted from admins, the assigned lawyer, and
                  the case client.
                </li>
                <li>
                  Downloads honor the same access list. Deletion is restricted
                  to admins or the original uploader.
                </li>
                <li>
                  Indexed documents feed the AI assistant through a
                  pgvector-backed similarity search.
                </li>
              </ul>
            </Article>

            <Article
              id="ai"
              title="AI Assistant (EtornieGPT)"
              intro="An IP-focused LLM assistant with optional retrieval over your case documents."
            >
              <p>
                Simple chat produces direct answers grounded in a specialized
                IP-law system prompt. RAG chat augments answers with passages
                retrieved from indexed documents, respecting your role-based
                visibility rules.
              </p>
              <p>
                Documents are chunked and embedded through Together AI. The
                vectors are stored in PostgreSQL via the pgvector extension.
              </p>
            </Article>

            <Article
              id="notifications"
              title="Notifications"
              intro="Three parallel rails keep stakeholders informed."
            >
              <ul className="list-disc space-y-1.5 pl-5">
                <li>
                  <strong>WhatsApp Business Cloud API:</strong> template and
                  text messages with scheduling and retry.
                </li>
                <li>
                  <strong>Email (EmailJS):</strong> OTP verification and case
                  creation alerts.
                </li>
                <li>
                  <strong>In-app bell:</strong> real-time portal notifications
                  with read state and deep links.
                </li>
              </ul>
              <p>
                Wallet-only users default to the in-app channel and can
                optionally link email or phone to enable the other rails.
              </p>
            </Article>

            <Article
              id="ip-agent"
              title="IP Agent"
              intro="A background agent that scans deadlines and drafts reminders without manual intervention."
            >
              <ul className="list-disc space-y-1.5 pl-5">
                <li>
                  Day-based reminders at configurable intervals. Defaults: 30,
                  7, and 1 days before a deadline.
                </li>
                <li>Minute-based reminders for same-day deadlines.</li>
                <li>
                  Auto-created WhatsApp notifications for the assigned lawyer
                  and client.
                </li>
                <li>Duplicate detection and an admin-controlled on/off switch.</li>
              </ul>
            </Article>

            <Article
              id="api"
              title="API Reference"
              intro="REST endpoints are grouped by domain. Full OpenAPI at /docs on the backend."
            >
              <EndpointGroup
                title="Auth"
                endpoints={[
                  ["POST", "/auth/register", "Direct registration (no OTP)"],
                  ["POST", "/auth/register/request", "Send OTP email"],
                  ["POST", "/auth/register/verify", "Verify OTP, create account"],
                  ["POST", "/auth/login", "Exchange credentials for JWT"],
                  ["POST", "/auth/refresh", "Rotate access token"],
                  ["GET", "/auth/me", "Current user"],
                ]}
              />
              <EndpointGroup
                title="Cases"
                endpoints={[
                  ["POST", "/cases", "Create case"],
                  ["GET", "/cases", "List cases (role-filtered)"],
                  ["GET", "/cases/{id}", "Case detail"],
                  ["PATCH", "/cases/{id}", "Update case"],
                  ["POST", "/cases/{id}/notes", "Add note"],
                  ["GET", "/cases/{id}/notes", "List notes"],
                ]}
              />
              <EndpointGroup
                title="Documents"
                endpoints={[
                  ["POST", "/cases/{id}/documents", "Upload document"],
                  ["GET", "/cases/{id}/documents", "List documents"],
                  ["GET", "/documents/{id}/download", "Download"],
                  ["DELETE", "/documents/{id}", "Delete"],
                ]}
              />
              <EndpointGroup
                title="AI"
                endpoints={[
                  ["POST", "/ai/chat", "Simple or RAG chat"],
                  ["POST", "/ai/search", "Similarity search"],
                  ["POST", "/ai/index/{document_id}", "Index document"],
                ]}
              />
              <EndpointGroup
                title="Notifications"
                endpoints={[
                  ["POST", "/notifications", "Create scheduled message"],
                  ["GET", "/notifications", "List"],
                  ["POST", "/notifications/send", "Send immediately"],
                  ["GET", "/notifications/templates/list", "List templates"],
                ]}
              />
              <EndpointGroup
                title="IP Agent"
                endpoints={[
                  ["POST", "/agents/ip/scan-deadlines", "Run scanner"],
                  ["GET", "/agents/ip/upcoming-deadlines", "Upcoming"],
                  ["POST", "/agents/ip/configure", "Configure intervals"],
                ]}
              />
            </Article>

            <Article
              id="stack"
              title="Tech Stack"
              intro="The platform favors mature, well-supported tools on both server and client."
            >
              <div className="grid gap-3 sm:grid-cols-2">
                {[
                  ["Backend", "FastAPI, Python 3.12+"],
                  ["Frontend", "Next.js 16, React 19, TypeScript"],
                  ["Styling", "Tailwind CSS v4"],
                  ["ORM", "SQLAlchemy 2.0 async"],
                  ["Database", "PostgreSQL 16, pgvector"],
                  ["Cache / Queue", "Redis 7"],
                  ["Migrations", "Alembic"],
                  ["Auth", "JWT, python-jose, passlib, bcrypt"],
                  ["LLM", "Groq Llama 3.3 70B"],
                  ["Embeddings", "Together AI multilingual-e5-large"],
                  ["Messaging", "WhatsApp Business Cloud, EmailJS"],
                  ["Blockchain", "Solana (integration in progress)"],
                ].map(([k, v]) => (
                  <div
                    key={k}
                    className="rwa-card px-4 py-3 text-sm"
                  >
                    <p className="text-xs font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                      {k}
                    </p>
                    <p className="mt-0.5 text-[color:var(--color-ink)]">{v}</p>
                  </div>
                ))}
              </div>
            </Article>

            <Article
              id="roadmap"
              title="Roadmap"
              intro="A rough timeline of what is done and what is next. Dates are targets, not guarantees."
            >
              <ul className="space-y-2">
                {[
                  ["Done", "Rebrand to etornie-solana namespace"],
                  ["Done", "Beige / RWA frontend theme"],
                  ["Done", "Landing page with hybrid positioning"],
                  ["In progress", "Phantom and Solflare wallet sign-in"],
                  ["Planned", "Wallet-based case assignment and public handles"],
                  ["Planned", "On-chain attestations for case milestones"],
                  ["Planned", "Programmable licensing and collateral primitives"],
                ].map(([status, text]) => (
                  <li key={text} className="flex items-start gap-3">
                    <span
                      className={`mt-1 inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                        status === "Done"
                          ? "bg-[color:var(--color-status-done-bg)] text-[color:var(--color-status-done-fg)]"
                          : status === "In progress"
                          ? "bg-[color:var(--color-status-progress-bg)] text-[color:var(--color-status-progress-fg)]"
                          : "bg-[color:var(--color-linen)] text-[color:var(--color-bronze-dark)]"
                      }`}
                    >
                      {status}
                    </span>
                    <span>{text}</span>
                  </li>
                ))}
              </ul>
            </Article>

            <Article
              id="faq"
              title="FAQ"
              intro="Short answers to common questions."
            >
              <Question q="Does Etornie Solana replace my legal counsel?">
                No. It is a custody and workflow platform. Your lawyers remain
                in charge of legal decisions. The system enforces role-based
                access so counsel can work with full visibility while clients
                only see their own cases.
              </Question>
              <Question q="Can I use Etornie Solana without a wallet?">
                Yes. Email and password works today. Wallet sign-in is
                optional, additive, and coming online soon.
              </Question>
              <Question q="How are documents protected?">
                Uploads are scoped to their case and gated by role. Only
                participants can read or download. Admins and the original
                uploader can delete.
              </Question>
              <Question q="Will my data live on-chain?">
                Not by default. Sensitive content never leaves the server.
                Planned on-chain work is limited to verifiable attestations:
                hashes and references, not raw documents or personal data.
              </Question>
            </Article>
          </article>
        </div>
      </section>

      <footer className="mt-auto border-t border-[color:var(--color-stone)] bg-[color:var(--color-cream)] px-6 py-8">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 text-xs text-[color:var(--color-muted)] md:flex-row">
          <p>
            © {new Date().getFullYear()} Etornie Solana. All rights reserved.
          </p>
          <p className="font-mono">etornie.sol · v0.1.0 · Devnet</p>
        </div>
      </footer>
    </div>
  );
}

function Article({
  id,
  title,
  intro,
  children,
}: {
  id: string;
  title: string;
  intro: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24 space-y-4">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight text-[color:var(--color-espresso)] md:text-3xl">
          {title}
        </h2>
        <p className="mt-2 text-[color:var(--color-muted)]">{intro}</p>
      </div>
      <div className="space-y-4 text-[color:var(--color-ink)]">{children}</div>
    </section>
  );
}

function SubHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="pt-2 text-sm font-semibold uppercase tracking-wider text-[color:var(--color-bronze)]">
      {children}
    </h3>
  );
}

function RoleCard({
  name,
  color,
  items,
}: {
  name: string;
  color: string;
  items: readonly string[];
}) {
  return (
    <div className="rwa-card p-5">
      <h3 className={`text-lg font-semibold ${color}`}>{name}</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-[color:var(--color-ink)]">
        {items.map((i) => (
          <li key={i}>{i}</li>
        ))}
      </ul>
    </div>
  );
}

function EndpointGroup({
  title,
  endpoints,
}: {
  title: string;
  endpoints: readonly (readonly [string, string, string])[];
}) {
  return (
    <div>
      <SubHeading>{title}</SubHeading>
      <div className="mt-2 overflow-hidden rounded-lg border border-[color:var(--color-stone)] bg-[color:var(--color-linen)]">
        {endpoints.map(([method, path, desc], idx) => (
          <div
            key={`${method}-${path}`}
            className={`grid grid-cols-[70px_1fr_auto] items-center gap-3 px-4 py-2.5 text-sm ${
              idx > 0
                ? "border-t border-[color:var(--color-stone)]/60"
                : ""
            }`}
          >
            <span
              className={`rounded px-2 py-0.5 text-center text-[10px] font-bold tracking-wider ${
                method === "GET"
                  ? "bg-[color:var(--color-status-done-bg)] text-[color:var(--color-status-done-fg)]"
                  : method === "POST"
                  ? "bg-[color:var(--color-status-open-bg)] text-[color:var(--color-status-open-fg)]"
                  : method === "PATCH"
                  ? "bg-[color:var(--color-status-progress-bg)] text-[color:var(--color-status-progress-fg)]"
                  : "bg-[color:var(--color-status-review-bg)] text-[color:var(--color-status-review-fg)]"
              }`}
            >
              {method}
            </span>
            <Code>{path}</Code>
            <span className="text-xs text-[color:var(--color-muted)]">
              {desc}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-[color:var(--color-linen)] px-1.5 py-0.5 font-mono text-sm text-[color:var(--color-bronze-dark)]">
      {children}
    </code>
  );
}

function Question({
  q,
  children,
}: {
  q: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rwa-card p-5">
      <p className="font-semibold text-[color:var(--color-espresso)]">{q}</p>
      <p className="mt-2 text-sm text-[color:var(--color-ink)]">{children}</p>
    </div>
  );
}
