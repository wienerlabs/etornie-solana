"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import api, { extractErrorMessage } from "@/lib/api";

type Status =
  | { kind: "exchanging" }
  | { kind: "ok" }
  | { kind: "error"; message: string };

export default function EUIPOCallbackPage() {
  const router = useRouter();
  const [status, setStatus] = useState<Status>({ kind: "exchanging" });
  const ranRef = useRef(false);

  useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;

    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const errorParam = params.get("error");
    const errorDescription = params.get("error_description");

    if (errorParam) {
      const detail = errorDescription
        ? `${errorParam}: ${errorDescription}`
        : errorParam;
      setStatus({ kind: "error", message: detail });
      window.setTimeout(() => {
        router.replace(
          `/dashboard/euipo?euipo_error=${encodeURIComponent(detail)}`
        );
      }, 2500);
      return;
    }

    if (!code) {
      setStatus({
        kind: "error",
        message: "Missing authorization code in EUIPO redirect.",
      });
      return;
    }

    const redirectUri = `${window.location.origin}/dashboard/euipo/callback`;
    api
      .post("/euipo/auth/callback", null, {
        params: { code, redirect_uri: redirectUri },
      })
      .then(() => {
        setStatus({ kind: "ok" });
        window.setTimeout(() => {
          router.replace("/dashboard/euipo?euipo_connected=1");
        }, 1200);
      })
      .catch((err: unknown) => {
        setStatus({
          kind: "error",
          message: extractErrorMessage(err, "EUIPO authentication failed."),
        });
      });
  }, [router]);

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4">
      <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h1 className="text-lg font-semibold text-gray-800">
          EUIPO Authentication
        </h1>
        {status.kind === "exchanging" && (
          <p className="mt-3 text-sm text-gray-600">
            Exchanging authorization code with EUIPO...
          </p>
        )}
        {status.kind === "ok" && (
          <p className="mt-3 text-sm text-green-700">
            Connected. Returning to EUIPO services...
          </p>
        )}
        {status.kind === "error" && (
          <>
            <p className="mt-3 text-sm text-red-700" role="alert">
              {status.message}
            </p>
            <button
              type="button"
              onClick={() => router.replace("/dashboard/euipo")}
              className="mt-4 rounded-md bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700"
            >
              Back to EUIPO
            </button>
          </>
        )}
      </div>
    </div>
  );
}
