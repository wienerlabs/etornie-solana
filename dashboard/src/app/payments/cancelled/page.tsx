import Link from "next/link";

export default function StripeCancelledPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-center justify-center gap-6 px-6 py-12">
      <div className="w-full rounded-2xl border border-[color:var(--color-stone)] bg-[color:var(--color-linen)] p-8 shadow-sm">
        <div className="flex flex-col items-center gap-2 text-center">
          <span className="text-2xl">×</span>
          <p className="text-lg font-semibold text-[color:var(--color-ink)]">
            Payment cancelled
          </p>
          <p className="text-sm text-[color:var(--color-muted)]">
            You closed the Stripe checkout before completing the payment. Your
            filing draft is unchanged — you can retry from the chat at any
            time, or pay with a wallet instead.
          </p>
        </div>

        <div className="mt-6 flex justify-center gap-3">
          <Link
            href="/dashboard/etorniegpt"
            className="rounded-md bg-[color:var(--color-bronze)] px-4 py-2 text-sm font-semibold text-[color:var(--color-cream)] hover:bg-[color:var(--color-bronze-dark)]"
          >
            Back to chat
          </Link>
          <Link
            href="/dashboard"
            className="rounded-md border border-[color:var(--color-stone)] px-4 py-2 text-sm font-semibold text-[color:var(--color-ink)] hover:bg-[color:var(--color-sand)]"
          >
            Dashboard
          </Link>
        </div>
      </div>
    </main>
  );
}
