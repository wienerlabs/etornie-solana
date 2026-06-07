import { describe, it, expect, beforeAll } from "vitest";
import { EtornieClient, EtornieApiError, EtornieAuthError } from "../src/index.js";

// Integration tests run against a real, running Etornie API. They are
// credential-gated: set the env vars below to enable them. Without
// credentials they are skipped (never mocked) so the suite stays green
// in environments that cannot reach the API.
const API_URL = process.env.ETORNIE_API_URL;
const EMAIL = process.env.ETORNIE_TEST_EMAIL;
const PASSWORD = process.env.ETORNIE_TEST_PASSWORD;
const live = Boolean(API_URL && EMAIL && PASSWORD);

describe("EtornieClient (unit)", () => {
  it("requires a baseUrl", () => {
    expect(() => new EtornieClient({ baseUrl: "" })).toThrow();
  });

  it("throws EtornieAuthError when calling an authed endpoint without a token", async () => {
    const client = new EtornieClient({ baseUrl: "https://example.invalid" });
    await expect(client.auth.me()).rejects.toBeInstanceOf(EtornieAuthError);
  });

  it("strips a trailing slash from baseUrl", () => {
    const client = new EtornieClient({ baseUrl: "https://api.etornie.com/" });
    expect(client.baseUrl).toBe("https://api.etornie.com");
  });
});

describe.skipIf(!live)("EtornieClient (integration)", () => {
  let client: EtornieClient;

  beforeAll(async () => {
    client = new EtornieClient({ baseUrl: API_URL! });
    await client.auth.login(EMAIL!, PASSWORD!);
  });

  it("logs in and returns the current user", async () => {
    const me = await client.auth.me();
    expect(me.email).toBe(EMAIL);
    expect(me.id).toBeTruthy();
  });

  it("lists cases", async () => {
    const res = await client.cases.list({ limit: 5 });
    expect(Array.isArray(res.cases)).toBe(true);
    expect(typeof res.total).toBe("number");
  });

  it("manages the calendar feed", async (ctx) => {
    let enabled;
    try {
      enabled = await client.calendar.enable();
    } catch (err) {
      if (err instanceof EtornieApiError && err.status === 404) {
        ctx.skip(); // calendar feature not available on target API
        return;
      }
      throw err;
    }
    expect(enabled.enabled).toBe(true);
    expect(enabled.url).toContain("/calendar/feed/");
    await client.calendar.disable();
    const status = await client.calendar.status();
    expect(status.enabled).toBe(false);
  });
});
