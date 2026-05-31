"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { registerUnauthorizedHandler } from "@/lib/api";
import { missingEnv } from "@/lib/env";

/**
 * Registers a soft client-side redirect to /login when an API token refresh
 * fails, so api.ts performs a Next router navigation (preserving SPA state)
 * instead of a full-page reload. Renders nothing.
 */
export default function AuthRedirectListener() {
  const router = useRouter();

  useEffect(() => {
    const missing = missingEnv();
    if (missing.length > 0) {
      console.error(
        `[etornie] Missing public env var(s): ${missing.join(", ")}. ` +
          "API calls will fail until these are set."
      );
    }
  }, []);

  useEffect(() => {
    registerUnauthorizedHandler(() => {
      if (window.location.pathname !== "/login") {
        router.replace("/login");
      }
    });
    return () => registerUnauthorizedHandler(null);
  }, [router]);

  return null;
}
