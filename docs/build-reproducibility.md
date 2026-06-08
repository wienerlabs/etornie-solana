# Build reproducibility & verifiable Anchor builds

A deployed Solana program is just an ELF (`.so`). To trust a deployment
we must be able to rebuild the **byte-identical** ELF from a known commit
and toolchain, and check it against what is on-chain. This document
captures the verifiable-build recipe for Etornie's three programs:

- `etornie_attestation` — `CpLYWQn39xw1Qei1fqcDF8NkJGiJsME2dKpAfzkN1T2X`
- `etornie_ip_token` — `6WrZ6NmuQtfpufrLbk5prQCKuF4isX1JwbrvxGFxT2gF`
- `etornie_zk_verifier` — `GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5`

(devnet ids today; see `Anchor.toml`).

## TL;DR

```bash
cargo install solana-verify --version 0.5.0 --locked   # one-time

for lib in etornie_attestation etornie_ip_token etornie_zk_verifier; do
  solana-verify build --library-name "$lib" \
    --base-image solanafoundation/solana-verifiable-build:3.0.14 \
    --cargo-build-sbf-args="--tools-version v1.54"
done

# Deterministic on-chain identity of each program:
solana-verify get-executable-hash target/deploy/etornie_attestation.so
```

## Why solana-verify (and not `anchor build --verifiable`)

`anchor build --verifiable` runs inside `solanafoundation/anchor:v0.31.1`,
which ships **rustc 1.79** — far below what the dependency graph needs
(`indexmap` wants ≥1.82; the zk-verifier's `mosaic-*` crates want exactly
**1.85.0**). So the Anchor verifiable image cannot build these programs.

[`solana-verify`](https://github.com/Ellipsis-Labs/solana-verifiable-build)
(Solana Verify) builds in its own pinned image and lets us force the
platform-tools version. The recipe that builds all three deterministically:

| Knob | Value | Why |
|------|-------|-----|
| Builder | `solana-verify` | `0.5.0` |
| Base image | `solanafoundation/solana-verifiable-build:3.0.14` | the **tag pins** the toolchain → deterministic ELF |
| Platform-tools | `--tools-version v1.54` (rustc 1.85) | the image default is rustc 1.84; the zk-verifier's `mosaic-*` crates require 1.85 |
| Dependency graph | `Cargo.lock` (committed) | exact crate versions |
| Release profile | `Cargo.toml` `[profile.release]` | `lto = "fat"`, `codegen-units = 1`, `overflow-checks = true` |

`rust-toolchain.toml` pins the **host** Rust (`1.85.0`) for non-SBF cargo
invocations (lint, host-target unit tests); the on-chain ELF is built by
the platform-tools rustc inside the image, not the host. `Anchor.toml`
`[toolchain] anchor_version = "0.31.1"` pins the Anchor CLI for the build +
integration-test tier (`anchor.yml`), which is separate from this
verifiable pipeline.

## Verifying an on-chain program

Compare the on-chain executable hash to a locally reproduced build:

```bash
# Hash of the program currently deployed at an address:
solana-verify get-program-hash <PROGRAM_ID> --url devnet

# Hash of a locally built verifiable ELF:
solana-verify get-executable-hash target/deploy/etornie_attestation.so
```

The two must match. `solana-verify verify-from-repo` can verify directly
against this repository at a given commit.

## CI artifacts

The **anchor-verifiable-build** workflow
(`.github/workflows/anchor-build.yml`) runs on pushes to `main`, on `v*`
tags, and on demand (`workflow_dispatch`). It:

1. installs the pinned `solana-verify`,
2. runs the verifiable build above for each program,
3. writes `SHA256SUMS.txt`, `EXECUTABLE-HASHES.txt` (the on-chain
   identities), and `BUILD-INFO.txt` (commit, image, timestamp),
4. uploads the `.so` files + checksums as the `verifiable-elf-<commit>`
   artifact (90-day retention).

So every build on `main`/tag has a downloadable, checksummed ELF traceable
to its commit — closing the "which commit produced this deploy?" gap.

## Release / deploy checklist (mainnet)

1. Tag the release commit (`vX.Y.Z`) → the verifiable-build workflow runs.
2. Download the `verifiable-elf-<commit>` artifact; record each program's
   executable hash (`EXECUTABLE-HASHES.txt`) in the release notes.
3. Deploy that exact ELF (`solana program deploy target/deploy/<p>.so`).
4. After deploy, confirm `solana-verify get-program-hash <id>` matches the
   recorded hash.
