import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 px-6 text-center">
      <p className="font-mono text-sm uppercase tracking-widest text-[color:var(--color-accent,#2520FE)]">
        404
      </p>
      <h1 className="text-2xl font-semibold text-[color:var(--color-inkwell,#000)]">
        Page not found
      </h1>
      <p className="max-w-md text-sm text-[color:var(--color-dusk-gray,#6B6B6B)]">
        The page you are looking for does not exist or has moved.
      </p>
      <Link
        href="/"
        className="mt-2 rounded-md bg-[color:var(--color-accent,#2520FE)] px-5 py-2.5 text-sm font-medium text-white transition hover:opacity-90"
      >
        Back to home
      </Link>
    </div>
  );
}
