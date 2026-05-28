/**
 * Sentry edge-runtime init.
 *
 * Covers middleware and edge route handlers — separate from the
 * Node server runtime so the edge bundle does not pull in unsupported
 * APIs.
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
