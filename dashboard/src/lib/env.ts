// Centralised, validated access to public (NEXT_PUBLIC_*) runtime config.
// Avoids the "silent break when a var is missing" failure mode by exposing a
// check that callers can surface loudly.

const RAW = {
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  NEXT_PUBLIC_SOLANA_CLUSTER: process.env.NEXT_PUBLIC_SOLANA_CLUSTER,
  NEXT_PUBLIC_SOLANA_RPC_URL: process.env.NEXT_PUBLIC_SOLANA_RPC_URL,
  NEXT_PUBLIC_SOLANA_CLUSTER_URL: process.env.NEXT_PUBLIC_SOLANA_CLUSTER_URL,
} as const;

const REQUIRED: ReadonlyArray<keyof typeof RAW> = ["NEXT_PUBLIC_API_URL"];

/** Returns the names of required public env vars that are unset/empty. */
export function missingEnv(): string[] {
  return REQUIRED.filter((key) => !RAW[key]);
}

/** Throws a descriptive error if any required public env var is missing. */
export function assertClientEnv(): void {
  const missing = missingEnv();
  if (missing.length > 0) {
    throw new Error(
      `Missing required public environment variable(s): ${missing.join(
        ", "
      )}. Set them in your .env or deployment config.`
    );
  }
}

export const env = {
  apiUrl: RAW.NEXT_PUBLIC_API_URL ?? "",
  solanaCluster: RAW.NEXT_PUBLIC_SOLANA_CLUSTER ?? "devnet",
  solanaRpcUrl:
    RAW.NEXT_PUBLIC_SOLANA_RPC_URL ??
    RAW.NEXT_PUBLIC_SOLANA_CLUSTER_URL ??
    "https://api.devnet.solana.com",
} as const;
