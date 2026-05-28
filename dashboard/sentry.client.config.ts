/**
 * Sentry browser-side init.
 *
 * Captures unhandled exceptions, React error boundaries, and fetch
 * failures from the dashboard SPA. Stays inert when
 * NEXT_PUBLIC_SENTRY_DSN is empty so local dev does not require a
 * Sentry account.
 */
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENV ?? "development",
    // Tracing helps us see slow API calls + render bottlenecks. 10%
    // sample rate keeps the free-tier event budget healthy; bump it
    // when actively debugging a regression.
    tracesSampleRate: Number(
      process.env.NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE ?? "0.1",
    ),
    // Replays are heavyweight; off by default. Flip to capture user
    // sessions around an error reproduction.
    replaysOnErrorSampleRate: 0,
    replaysSessionSampleRate: 0,
    // Never send IP / form data / cookies — we keep PII off Sentry.
    sendDefaultPii: false,
  });
}
