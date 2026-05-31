"use client";

import { useEffect } from "react";
import ErrorState from "@/components/ErrorState";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <ErrorState
      title="This page hit an error"
      message="Something went wrong loading this view. Try again, or head back to your dashboard."
      onRetry={reset}
    />
  );
}
