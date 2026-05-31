import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// env.ts captures process.env at module load, so each case stubs the env then
// re-imports the module via resetModules to read the stubbed value.
describe("env validation", () => {
  beforeEach(() => {
    vi.resetModules();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("flags NEXT_PUBLIC_API_URL as missing when unset", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "");
    const { missingEnv, assertClientEnv } = await import("./env");
    expect(missingEnv()).toContain("NEXT_PUBLIC_API_URL");
    expect(() => assertClientEnv()).toThrowError(/NEXT_PUBLIC_API_URL/);
  });

  it("reports nothing missing when the API URL is set", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.test");
    const { missingEnv, assertClientEnv, env } = await import("./env");
    expect(missingEnv()).toHaveLength(0);
    expect(() => assertClientEnv()).not.toThrow();
    expect(env.apiUrl).toBe("https://api.test");
  });

  it("defaults the solana cluster to devnet", async () => {
    const { env } = await import("./env");
    expect(env.solanaCluster).toBe("devnet");
  });
});
