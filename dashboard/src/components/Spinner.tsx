// Shared loading spinner primitive.
export default function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={
        "inline-block h-8 w-8 animate-spin rounded-full border-2 " +
        "border-[color:var(--color-divider,#E8E8E8)] " +
        "border-t-[color:var(--color-accent,#2520FE)] " +
        className
      }
    />
  );
}
