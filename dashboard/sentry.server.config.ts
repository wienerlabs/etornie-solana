/**
 * Sentry server-side init for the Next.js runtime
 * (App Router server components, route handlers, RSC streaming).
 *
 * Backend errors caught here surface alongside the FastAPI ones in
 * the same Sentry project — useful for tying a UI 500 to the
 * upstream API exception that caused it.
 */
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.SENTRY_DSN ?? process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.SENTRY_ENV ?? "development",
    tracesSampleRate: Number(
      process.env.SENTRY_TRACES_SAMPLE_RATE ?? "0.1",
    ),
    sendDefaultPii: false,
  });
}
