/**
 * Next.js instrumentation entry point.
 *
 * Next.js calls ``register`` once when the Node / Edge runtime
 * boots. We hand off to the matching Sentry config so the SDK is
 * wired before any user request hits a server component / route
 * handler.
 *
 * The client (browser) bundle initialises through
 * ``sentry.client.config.ts`` via Next.js' built-in handling — no
 * manual import needed.
 */
import { captureRequestError } from "@sentry/nextjs";

export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./sentry.server.config");
  }
  if (process.env.NEXT_RUNTIME === "edge") {
    await import("./sentry.edge.config");
  }
}

// Next.js >= 15 looks up a top-level ``onRequestError`` export on
// the instrumentation module and forwards request-scoped server
// errors there. ``@sentry/nextjs`` ships the matching capture as
// ``captureRequestError`` (renamed in v8+), so we re-export it
// under the name Next.js expects.
export const onRequestError = captureRequestError;

