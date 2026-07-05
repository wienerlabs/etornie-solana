# Etornie mainnet deploy runbook

Staged Solana mainnet cutover. On-chain registration, tokenization, and the
Solana fees go live. EUIPO, Yousign, and Stripe stay on sandbox/test until
their production credentials are provisioned separately.

This runbook assumes the mainnet code readiness work (env-derived cluster,
`solana_cluster` setting, explorer suffix) is already merged.

## 0. Why fresh program keypairs

The three programs currently target devnet, and the deploy keypairs are not
usable as-is:

- `etornie-zk-verifier`: the committed keypair resolves to a pubkey that does
  not match the declared program id, so it cannot deploy to that address.
- `etornie-attestation` and `etornie-ip-token`: no program-id keypair is in
  the repo.

So a mainnet deploy mints three new keypairs, which produce three new program
ids that must be propagated everywhere. The frontend and both SDKs read program
ids from API responses, so no frontend or SDK change is required.

## 1. Prerequisites (on your machine)

- Solana CLI, Anchor 0.31.1, and the SBF build toolchain (platform-tools
  v1.54 / rustc 1.85). The Anchor build uses `RUSTC_BOOTSTRAP=1` and
  `--tools-version v1.54`.
- A funded mainnet deployer keypair at a local path (for example
  `~/.config/solana/etornie-mainnet-deployer.json`). Never paste its secret
  into chat or commit it.
- A mainnet RPC endpoint (Helius or similar paid RPC recommended; public
  `api.mainnet-beta.solana.com` is rate limited and unreliable for deploys).
- A treasury pubkey to receive the registration and mint fees.
- A Squads multisig (devnet setup recorded in `docs/runbooks/program-upgrade.md`)
  to hold upgrade authority.

## 2. Generate fresh program keypairs

```
solana-keygen new --no-bip39-passphrase -o target/deploy/etornie_attestation-keypair.json
solana-keygen new --no-bip39-passphrase -o target/deploy/etornie_ip_token-keypair.json
solana-keygen new --no-bip39-passphrase -o target/deploy/etornie_zk_verifier-keypair.json
solana address -k target/deploy/etornie_attestation-keypair.json
solana address -k target/deploy/etornie_ip_token-keypair.json
solana address -k target/deploy/etornie_zk_verifier-keypair.json
```

Keep the three printed pubkeys. The keypair files are secrets and are already
gitignored under `target/`.

## 3. Propagate the new program ids

Set the three ids in every source of truth:

- `programs/etornie-attestation/src/lib.rs` `declare_id!(...)`
- `programs/etornie-ip-token/src/lib.rs` `declare_id!(...)`
- `programs/etornie-zk-verifier/src/lib.rs` `declare_id!(...)`
- `Anchor.toml` `[programs.mainnet]` block
- Regenerate or hand-edit `idl/*.json` and the `.ts` IDL mirrors `address`
- Backend env: `SOLANA_ATTESTATION_PROGRAM_ID`, `SOLANA_NFT_PROGRAM_ID`,
  `SOLANA_ZK_VERIFIER_PROGRAM_ID` (these override the config defaults)
- The seven `tests/*.ts` PROGRAM_ID constants (only needed if you run the TS
  integration suite against mainnet, which is not part of PR CI)

## 4. Build to SBF

```
RUSTC_BOOTSTRAP=1 anchor build --no-idl -- --tools-version v1.54
```

If a local build hits stack-offset or toolchain issues, use the pinned
container build (linux/amd64) and copy the resulting `.so` files out of
`target/deploy/`. Record the three `.so` byte sizes; they drive the deploy
rent cost in the next step.

## 5. Fund the deployer and estimate cost

Program deploy rent is roughly `.so_bytes * 2 * lamports_per_byte_year`, plus a
temporary buffer during upload. For three programs in the 400k to 800k byte
range, budget approximately 13 to 15 SOL total. Compute the exact figure from
the `.so` sizes with `solana rent <bytes>` before funding. Fund the deployer
keypair accordingly.

## 6. Deploy

```
solana config set --url <MAINNET_RPC_URL>
solana config set --keypair ~/.config/solana/etornie-mainnet-deployer.json
anchor deploy --provider.cluster mainnet
```

Or deploy each program individually with `solana program deploy
target/deploy/<program>.so --program-id target/deploy/<program>-keypair.json`.
Confirm each program id on a mainnet explorer after deploy.

## 7. Move upgrade authority to Squads

Do not leave upgrade authority on the hot deployer keypair. Transfer each
program's upgrade authority to the Squads multisig (see
`docs/runbooks/program-upgrade.md` for the recorded multisig and the transfer
script), then verify with `solana program show <program_id>`.

## 8. Backend and frontend env

Backend:

- `SOLANA_CLUSTER=mainnet-beta`
- `SOLANA_CLUSTER_URL=<MAINNET_RPC_URL>`
- the three `SOLANA_*_PROGRAM_ID` values from step 2
- operator keypair custody: `SOLANA_OPERATOR_KEY_JSON` (or key path), ideally
  encrypted at rest via `OPERATOR_KEY_MASTER_KEY`
- `FEE_TREASURY_VAULT=<treasury pubkey>`
- `REGISTRATION_FEE_LAMPORTS=10000000` (0.01 SOL) and `MINT_FEE_LAMPORTS=<amount>`
- retune `UKIPO_PAYMENT_LAMPORTS` and `ETORNIEGPT_PAYMENT_LAMPORTS` for mainnet
  SOL value before enabling those paths

Frontend:

- `NEXT_PUBLIC_SOLANA_CLUSTER=mainnet-beta`
- `NEXT_PUBLIC_SOLANA_RPC=<MAINNET_RPC_URL>`

## 9. Fees go live

Setting `FEE_TREASURY_VAULT` activates the enforced fees. Until it is set the
fee is a no-op (dev behavior). The finalize allowlist rejects any tx that is
not the expected program instruction(s) plus a single user to treasury
transfer, so the operator hot key cannot be drained by a crafted tx. Note:
ComputeBudget (priority fee) instructions are not yet allowlisted; if mainnet
tx landing needs priority fees, add a capped, validated ComputeBudget path
before the frontend starts attaching them.

## 10. Helius webhook

Re-register the Helius webhook against the mainnet program ids so on-chain
event reconciliation works. Set `HELIUS_WEBHOOK_AUTH`, `HELIUS_API_KEY`, and
`HELIUS_WEBHOOK_URL`, then run `scripts/register_helius_webhook.py`. See
`docs/HELIUS_WEBHOOK.md`.

## 11. Post-deploy verification

- `GET /health` returns ok on the deployed backend.
- Create one real case and complete the attestation on mainnet with a funded
  test wallet; confirm the tx on an explorer and that 0.01 SOL landed in the
  treasury.
- Mint one NFT and confirm the mint fee landed in the treasury.
- Confirm explorer links in the dashboard point at mainnet (no `?cluster=devnet`).
- Confirm the Helius webhook is delivering events.

## 12. Still on sandbox after this cutover (provision separately)

- EUIPO: switch `euipo_base_url` and `euipo_auth_url` to production and set the
  production `euipo_api_key` / `euipo_api_secret` plus the OIDC bootstrap.
- Yousign: switch `yousign_base_url` to production and set `yousign_api_key`.
- Stripe: switch to live keys.
- WIPO Global Brand Database: build the adapter once the B2B API contract is
  available, then set its credentials.
