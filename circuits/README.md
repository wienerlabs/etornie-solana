# Etornie Solana ZK Stack

Zero-knowledge toolchain for Etornie Solana. Houses Circom circuits, the
snarkjs pipeline scripts, and (later) a Node-based prover service. Pairs
with the sibling `anchor-program/` folder which will host the on-chain
Groth16 verifier and Light Protocol compressed attestation logic.

## Status

Phase 1 of Track A is complete: the full Circom + snarkjs pipeline runs
end to end against a hello-world multiplier circuit. This is only a
smoke test for tooling. The real circuits for lawyer verification and
AI-agent policy compliance will be added in later phases.

## Requirements

- Node.js 20+
- circom 2.2.x (`brew install circom` or a prebuilt binary from the
  iden3 releases)
- snarkjs (installed as a local or global npm package)

Versions used while validating this repository:

| Tool      | Version |
|-----------|---------|
| circom    | 2.2.3   |
| snarkjs   | 0.7.6   |
| circomlib | 2.0.5   |

## Layout

```
zk/
├── circuits/
│   └── hello_world/
│       ├── hello_world.circom   # smoke-test circuit: a * b = c
│       └── input.json           # sample private inputs {a: 3, b: 11}
├── scripts/
│   └── build_hello_world.sh     # one-shot full pipeline
├── prover-service/              # (upcoming) Express API that runs snarkjs
├── package.json                 # pins circomlib
├── .gitignore                   # keeps build artifacts out of git
└── README.md
```

## Running the hello-world pipeline

```bash
cd zk
npm install
npm run build:hello
```

The script performs seven steps:

1. Compiles `hello_world.circom` to `.r1cs`, `.wasm`, `.sym`.
2. Runs a fresh Powers of Tau phase 1 ceremony at `2^12`.
3. Contributes to phase 2 and derives the final Groth16 zkey.
4. Exports the verification key as `verification_key.json`.
5. Generates the witness for `input.json` with the compiled wasm.
6. Produces a Groth16 proof (`proof.json`, `public.json`).
7. Verifies the proof and prints `OK`.

The circuit proves knowledge of two private factors `a` and `b` such
that their product equals the public signal `c`, without revealing `a`
or `b`. For `a = 3, b = 11`, `public.json` contains `["33"]`.

## Notes on the trusted setup

The `2^12` ceremony in the build script is **development only**. For
production circuits we will switch to the Hermez Powers of Tau
ceremony (`powersOfTau28_hez_final_14.ptau`, 54-participant public
ceremony) and do a proper multi-party phase 2. This migration is
scheduled for Track A Phase 3.

## Upcoming

- Compliance circuit for AI-agent policy proofs (Phase 2)
- Hermez ptau + multi-party phase 2 (Phase 3)
- Node prover service under `prover-service/` (Phase 4)
- Groth16 Solana verifier wired to `anchor-program/` (Phase 5)
- Light Protocol compressed attestation mint on successful verification
  (Phase 6)
