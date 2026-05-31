"use client";

// Shared error-state primitive used by route error boundaries.
export default function ErrorState({
  title = "Something went wrong",
  message = "An unexpected error occurred. Please try again.",
  onRetry,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 px-6 text-center">
      <p className="font-mono text-sm uppercase tracking-widest text-[color:var(--color-accent,#2520FE)]">
        Error
      </p>
      <h1 className="text-2xl font-semibold text-[color:var(--color-inkwell,#000)]">
        {title}
      </h1>
      <p className="max-w-md text-sm text-[color:var(--color-dusk-gray,#6B6B6B)]">
        {message}
      </p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded-md bg-[color:var(--color-accent,#2520FE)] px-5 py-2.5 text-sm font-medium text-white transition hover:opacity-90"
        >
          Try again
        </button>
      )}
    </div>
  );
}
