# etornie-zk-verifier

On-chain Groth16 verifier for Etornie's three circuits, running on
[Wiener Labs Mosaic](https://github.com/wienerlabs/mosaic) (`mosaic-groth16`).

| Instruction | Circuit | Public inputs | Record PDA |
|---|---|---|---|
| `verify_proof` | `hello_world` | 1 | `(proof, user, journal_digest)` |
| `verify_proof_batch` | `hello_world` × N | 1 each | `(batch, user, batch_digest)` |
| `verify_file_ownership_proof` | `file_ownership` | 3 `[fh_hi, fh_lo, commitment]` | `(file-ownership, user, file_hash)` |
| `verify_compliance_proof` | `compliance` (x402) | 3 `[qh_hi, qh_lo, commitment]` | `(compliance, user, query_hash)` |

The single-proof paths route through `mosaic_groth16::Groth16Verifier`; the
batch path uses `mosaic_groth16::batch::batch_verify` (Bowe-Gabizon). All use
the `SolanaSyscallBackend` and big-endian field elements (`<_, false>`).

### Batch verification

`verify_proof_batch` verifies `N` proofs (`2..=MAX_BATCH`, MAX_BATCH = 4)
sharing the hello_world VK in a **single BN254 pairing**. mosaic's batch
verifier costs ~52k CU/proof versus ~83k single, a ~38% saving. A single
`BatchProofRecord` PDA keyed on `(user, batch_digest)` covers the whole batch.

The batch size is bounded by the 1232-byte Solana transaction limit: each
`BatchEntry` is 288 bytes (256 proof + one 32-byte public input), so 4 entries
plus the seed and accounts fit one tx. Larger batches would need address
lookup tables or chunking. `batch_digest = sha256(concat(per-entry journal
digests))` and is recomputed on-chain so the PDA seed cannot be spoofed.

## Compute-unit budget

Clients prepend `ComputeBudgetInstruction::set_compute_unit_limit(180_000)`
(down from `300_000` under the previous `groth16-solana` verifier).

| Cost component | Approx CU | Source |
|---|---|---|
| BN254 Groth16 single verify | ~83,500 | mosaic-groth16 published baseline |
| PDA `init_if_needed` + rent | ~15,000 | Anchor account init |
| sha256 journal digest + input checks | ~5,000 | per circuit |
| Anchor dispatch + account writes | ~15,000 | framework overhead |
| **Estimated total** | **~120,000** | |
| **Requested limit (1.5x margin)** | **180,000** | conservative |

> These are conservative estimates anchored on mosaic's published 83,574 CU
> single-verify figure. The exact per-instruction CU is calibrated by the
> on-chain benchmark in CI (#48) and the SBF integration tests (M9), and the
> `180_000` limit should be tightened once those land.

### Why mosaic is cheaper

`mosaic-groth16` negates `A` internally and batches all four pairings into a
single `sol_alt_bn128_group_op(Pairing, …)` call (768 B input), versus the
multi-call path in `groth16-solana`. The linear combination
`L = IC[0] + Σ pi[i]·IC[i+1]` is the only per-input cost (~3,300 CU each).

## Client compute-budget call sites

The `180_000` limit is set in:

- `tests/zk_verifier.ts`, `tests/file_ownership.ts`, `tests/compliance.ts`
- `services/api/app/solana/client.py`
- `dashboard/src/lib/zk/verifyProof.ts`, `dashboard/src/lib/zk/submitFileOwnership.ts`

All are overridable per call (the frontend helpers accept `opts.computeUnitLimit`).

## Building (SBF)

Mosaic's MSRV is **rustc 1.85.0**, but Solana's default platform-tools
(`v1.51`, shipped with solana-cli 3.0.x) provides only rustc 1.84.1. Build the
program with a newer toolchain:

```bash
RUSTC_BOOTSTRAP=1 cargo build-sbf \
  --tools-version v1.54 \
  --manifest-path programs/etornie-zk-verifier/Cargo.toml
```

- `--tools-version v1.54` pulls a platform-tools build whose rustc satisfies
  mosaic's 1.85 MSRV.
- `RUSTC_BOOTSTRAP=1` is currently set defensively; remove once the pinned deps
  below are confirmed sufficient on a clean checkout.

### Pinned dependencies

Several transitive crates moved to `edition2024` or raised their MSRV past what
the platform-tools cargo can parse. `Cargo.lock` pins them to the last
compatible versions:

| Crate | Pinned to | Reason |
|---|---|---|
| `blake3` | `1.5.5` | newer pulls `constant_time_eq 0.4.2` (edition2024) |
| `indexmap` | `2.13.0` | `2.14` requires edition2024 |
| `proc-macro-crate` | `3.2.0` | `3.5` pulls `toml_edit 0.25` (edition2024) |
| `unicode-segmentation` | `1.12.0` | `1.13` MSRV is 1.85 and breaks tooling parse |

If you bump any of these, re-run `cargo build-sbf` to confirm the platform-tools
cargo still parses the lockfile.

The build produces `target/deploy/etornie_zk_verifier.so` (~262 KB, well under
the 1 MB program cap).

## Migration status

Part of the [Mosaic ZK Migration epic (#15)](https://github.com/wienerlabs/etornie-solana/issues/15).
The legacy `groth16-solana` dependency is retained only for its
`Groth16Verifyingkey` struct (the auto-generated VK modules type against it)
and is removed in M13 once M7 bakes canonical VK bytes at build time.
