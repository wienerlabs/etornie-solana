# etornie-zk-verifier

On-chain Groth16 verifier for Etornie's three circuits, running on
[Wiener Labs Mosaic](https://github.com/wienerlabs/mosaic) (`mosaic-groth16`).

| Instruction | Circuit | Public inputs | Record PDA |
|---|---|---|---|
| `verify_proof` | `hello_world` | 1 | `(proof, user, journal_digest)` |
| `verify_file_ownership_proof` | `file_ownership` | 3 `[fh_hi, fh_lo, commitment]` | `(file-ownership, user, file_hash)` |
| `verify_compliance_proof` | `compliance` (x402) | 3 `[qh_hi, qh_lo, commitment]` | `(compliance, user, query_hash)` |

All three route through `mosaic_groth16::Groth16Verifier` with the
`SolanaSyscallBackend` and big-endian field elements (`<_, false>`).

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

## Migration status

Part of the [Mosaic ZK Migration epic (#15)](https://github.com/wienerlabs/etornie-solana/issues/15).
The legacy `groth16-solana` dependency is retained only for its
`Groth16Verifyingkey` struct (the auto-generated VK modules type against it)
and is removed in M13 once M7 bakes canonical VK bytes at build time.
