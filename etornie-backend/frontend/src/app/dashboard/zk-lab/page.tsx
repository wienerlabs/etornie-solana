"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

interface Groth16Proof {
  pi_a: [string, string, string];
  pi_b: [[string, string], [string, string], [string, string]];
  pi_c: [string, string, string];
  protocol: string;
  curve: string;
}

interface VerificationKey {
  protocol: string;
  curve: string;
  nPublic: number;
  vk_alpha_1: string[];
  vk_beta_2: string[][];
  vk_gamma_2: string[][];
  vk_delta_2: string[][];
  vk_alphabeta_12: string[][][];
  IC: string[][];
}

interface ProveResult {
  proof: Groth16Proof;
  publicSignals: string[];
  proveMs: number;
  verifyMs: number;
  verified: boolean;
  proofHash: string;
  vkHash: string;
  proofBytes: { pi_a: string; pi_b: string; pi_c: string };
}

const WASM_URL = "/zk/hello_world/hello_world.wasm";
const ZKEY_URL = "/zk/hello_world/hello_world_final.zkey";
const VK_URL = "/zk/hello_world/verification_key.json";

const FIELD_PRIME =
  21888242871839275222246405745257275088696311157297823662689037894645226208583n;

function normalizeFieldElement(decimal: string): bigint {
  const value = BigInt(decimal);
  return ((value % FIELD_PRIME) + FIELD_PRIME) % FIELD_PRIME;
}

function toHex(value: bigint, length = 32): string {
  const hex = value.toString(16).padStart(length * 2, "0");
  return `0x${hex}`;
}

function g1Bytes(point: readonly [string, string, string]): string {
  const x = normalizeFieldElement(point[0]);
  const y = normalizeFieldElement(point[1]);
  return toHex(x) + toHex(y).slice(2);
}

function g2Bytes(
  point: readonly [
    readonly [string, string],
    readonly [string, string],
    readonly [string, string],
  ],
): string {
  const x1 = normalizeFieldElement(point[0][1]);
  const x0 = normalizeFieldElement(point[0][0]);
  const y1 = normalizeFieldElement(point[1][1]);
  const y0 = normalizeFieldElement(point[1][0]);
  return toHex(x1) + toHex(x0).slice(2) + toHex(y1).slice(2) + toHex(y0).slice(2);
}

async function sha256Hex(data: string): Promise<string> {
  const bytes = new TextEncoder().encode(data);
  const hashBuffer = await crypto.subtle.digest("SHA-256", bytes);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
}

export default function ZkLabDashboardPage() {
  const [a, setA] = useState("3");
  const [b, setB] = useState("11");
  const [result, setResult] = useState<ProveResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [snarkjsReady, setSnarkjsReady] = useState(false);
  const [assetStatus, setAssetStatus] = useState<Record<string, boolean | null>>({
    wasm: null,
    zkey: null,
    vk: null,
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await import("snarkjs");
        if (!cancelled) setSnarkjsReady(true);
      } catch (err) {
        if (!cancelled) {
          setError(
            "snarkjs failed to load: " +
              (err instanceof Error ? err.message : String(err)),
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    async function probe(url: string): Promise<boolean> {
      const res = await fetch(url, { method: "HEAD" });
      return res.ok;
    }
    (async () => {
      const [wasm, zkey, vk] = await Promise.all([
        probe(WASM_URL).catch(() => false),
        probe(ZKEY_URL).catch(() => false),
        probe(VK_URL).catch(() => false),
      ]);
      setAssetStatus({ wasm, zkey, vk });
    })();
  }, []);

  const run = useCallback(async () => {
    setError(null);
    setResult(null);

    const aVal = a.trim();
    const bVal = b.trim();
    if (!/^\d+$/.test(aVal) || !/^\d+$/.test(bVal)) {
      setError("Inputs must be non-negative decimal integers.");
      return;
    }

    setRunning(true);
    try {
      const snarkjs = await import("snarkjs");

      const proveStart = performance.now();
      const { proof, publicSignals } = await snarkjs.groth16.fullProve(
        { a: aVal, b: bVal },
        WASM_URL,
        ZKEY_URL,
      );
      const proveMs = performance.now() - proveStart;

      const vkResponse = await fetch(VK_URL);
      const vk = (await vkResponse.json()) as VerificationKey;

      const verifyStart = performance.now();
      const verified = await snarkjs.groth16.verify(vk, publicSignals, proof);
      const verifyMs = performance.now() - verifyStart;

      const proofJson = JSON.stringify(proof);
      const vkJson = JSON.stringify(vk);
      const [proofHash, vkHash] = await Promise.all([
        sha256Hex(proofJson),
        sha256Hex(vkJson),
      ]);

      const proofBytes = {
        pi_a: g1Bytes(proof.pi_a),
        pi_b: g2Bytes(proof.pi_b),
        pi_c: g1Bytes(proof.pi_c),
      };

      setResult({
        proof,
        publicSignals,
        proveMs,
        verifyMs,
        verified,
        proofHash,
        vkHash,
        proofBytes,
      });
    } catch (err) {
      setError(
        "Proof pipeline failed: " +
          (err instanceof Error ? err.message : String(err)),
      );
    } finally {
      setRunning(false);
    }
  }, [a, b]);

  const canRun = useMemo(() => {
    return (
      snarkjsReady &&
      assetStatus.wasm === true &&
      assetStatus.zkey === true &&
      assetStatus.vk === true &&
      !running
    );
  }, [snarkjsReady, assetStatus, running]);

  return (
    <div>
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[color:var(--color-espresso)]">
            ZK Lab
          </h1>
          <p className="mt-1 text-sm text-[color:var(--color-muted)]">
            A live Circom + snarkjs Groth16 pipeline running entirely in your
            browser. No backend call, no precomputed proofs. Every byte below
            is produced on this device from your inputs.
          </p>
        </div>
        <span className="chain-badge">
          <span className="chain-dot" />
          Groth16 · bn128
        </span>
      </div>

      <div className="grid gap-6 md:grid-cols-[1fr_1.4fr]">
        <div className="rwa-card h-fit p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-[color:var(--color-bronze)]">
            Private inputs
          </h2>
          <p className="mt-2 text-xs text-[color:var(--color-muted)]">
            Typed below. They stay in your browser. The witness and Groth16
            proof are computed locally using the compiled WASM and the final
            zkey.
          </p>
          <div className="mt-5 space-y-4">
            <label className="block">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                a
              </span>
              <input
                value={a}
                onChange={(e) => setA(e.target.value)}
                className="rwa-input mt-1.5 w-full font-mono"
                inputMode="numeric"
                placeholder="3"
              />
            </label>
            <label className="block">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                b
              </span>
              <input
                value={b}
                onChange={(e) => setB(e.target.value)}
                className="rwa-input mt-1.5 w-full font-mono"
                inputMode="numeric"
                placeholder="11"
              />
            </label>
            <button
              type="button"
              onClick={run}
              disabled={!canRun}
              className="rwa-btn-primary w-full"
            >
              {running ? "Generating proof..." : "Generate and verify proof"}
            </button>
          </div>

          <div className="mt-6 space-y-1 text-xs">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
              Pipeline assets
            </p>
            <StatusRow
              label="WASM witness generator"
              ok={assetStatus.wasm}
              url={WASM_URL}
            />
            <StatusRow
              label="Groth16 proving key (.zkey)"
              ok={assetStatus.zkey}
              url={ZKEY_URL}
            />
            <StatusRow
              label="Verification key"
              ok={assetStatus.vk}
              url={VK_URL}
            />
            <StatusRow label="snarkjs runtime loaded" ok={snarkjsReady} />
          </div>

          {error && (
            <div
              role="alert"
              className="mt-4 rounded-lg border border-red-300 bg-red-50 p-3 text-xs text-red-800"
            >
              {error}
            </div>
          )}
        </div>

        <div className="space-y-4">
          {!result && !running && (
            <div className="rwa-card p-6">
              <p className="text-sm text-[color:var(--color-muted)]">
                Waiting for a proof run. Enter two integers on the left and
                press <strong>Generate and verify proof</strong>. The page will
                fetch the WASM and zkey on demand, produce a fresh Groth16
                proof bound to your inputs, then verify it against the embedded
                verification key.
              </p>
            </div>
          )}

          {running && (
            <div className="rwa-card p-6">
              <p className="text-sm text-[color:var(--color-muted)]">
                Generating proof. Large zkey downloads can add a few seconds on
                a cold load.
              </p>
            </div>
          )}

          {result && (
            <>
              <div
                className={`rwa-card p-5 ${
                  result.verified
                    ? "border-[color:var(--color-solana-green)]/60 bg-[color:var(--color-status-done-bg)]"
                    : "border-red-300 bg-red-50"
                }`}
              >
                <p className="text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  On-device verification
                </p>
                <p
                  className={`mt-1 text-xl font-semibold ${
                    result.verified
                      ? "text-[color:var(--color-status-done-fg)]"
                      : "text-red-800"
                  }`}
                >
                  {result.verified ? "verified ✓" : "rejected ✗"}
                </p>
                <p className="mt-1 text-xs text-[color:var(--color-muted)]">
                  snarkjs.groth16.verify ran against the embedded verification
                  key for the public signals produced by the circuit.
                </p>
              </div>

              <Row
                label="Public signals"
                mono
                value={JSON.stringify(result.publicSignals)}
              />
              <div className="grid grid-cols-2 gap-4">
                <Row label="Protocol" value={result.proof.protocol} />
                <Row label="Curve" value={result.proof.curve} />
              </div>

              <div className="rwa-card p-5">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Proof bytes (BN254 uncompressed, big-endian)
                </p>
                <ByteRow label="pi_a (G1, 64 bytes)" value={result.proofBytes.pi_a} />
                <ByteRow label="pi_b (G2, 128 bytes)" value={result.proofBytes.pi_b} />
                <ByteRow label="pi_c (G1, 64 bytes)" value={result.proofBytes.pi_c} />
              </div>

              <div className="rwa-card p-5">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Hashes
                </p>
                <ByteRow
                  label="SHA-256 of proof JSON"
                  value={"0x" + result.proofHash}
                />
                <ByteRow
                  label="SHA-256 of verification key"
                  value={"0x" + result.vkHash}
                />
              </div>

              <div className="rwa-card p-5">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Timing
                </p>
                <div className="mt-2 grid grid-cols-2 gap-4">
                  <TimingTile
                    label="Witness + prove"
                    value={`${result.proveMs.toFixed(0)} ms`}
                  />
                  <TimingTile
                    label="Verify"
                    value={`${result.verifyMs.toFixed(0)} ms`}
                  />
                </div>
              </div>

              <details className="rwa-card p-5 text-xs">
                <summary className="cursor-pointer text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
                  Raw proof JSON
                </summary>
                <pre className="mt-3 overflow-x-auto rounded bg-[color:var(--color-cream)] p-3 font-mono text-[11px] text-[color:var(--color-ink)]">
                  {JSON.stringify(result.proof, null, 2)}
                </pre>
              </details>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusRow({
  label,
  ok,
  url,
}: {
  label: string;
  ok: boolean | null;
  url?: string;
}) {
  const state = ok === null ? "..." : ok ? "loaded" : "failed";
  const color =
    ok === null
      ? "text-[color:var(--color-muted)]"
      : ok
        ? "text-[color:var(--color-status-done-fg)]"
        : "text-red-700";
  return (
    <div className="flex items-center justify-between border-b border-[color:var(--color-stone)]/60 py-1 last:border-b-0">
      <span className="text-[color:var(--color-ink)]">
        {label}
        {url && (
          <span className="ml-2 font-mono text-[10px] text-[color:var(--color-muted)]">
            {url}
          </span>
        )}
      </span>
      <span className={`font-semibold ${color}`}>{state}</span>
    </div>
  );
}

function Row({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="rwa-card p-4">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
        {label}
      </p>
      <p
        className={`mt-1 text-sm text-[color:var(--color-ink)] ${
          mono ? "font-mono" : ""
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function ByteRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="mt-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
        {label}
      </p>
      <p className="mt-1 break-all font-mono text-[11px] leading-snug text-[color:var(--color-bronze-dark)]">
        {value}
      </p>
    </div>
  );
}

function TimingTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-[color:var(--color-cream)] p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-[color:var(--color-muted)]">
        {label}
      </p>
      <p className="mt-0.5 font-mono text-sm text-[color:var(--color-espresso)]">
        {value}
      </p>
    </div>
  );
}
