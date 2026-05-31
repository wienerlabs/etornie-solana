"use client";

import { useEffect } from "react";
import ErrorState from "@/components/ErrorState";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface to the console (and any monitoring) so it is not swallowed.
    console.error(error);
  }, [error]);

  return (
    <ErrorState
      message="An unexpected error occurred. You can try again, and if it persists, please contact support."
      onRetry={reset}
    />
  );
}
