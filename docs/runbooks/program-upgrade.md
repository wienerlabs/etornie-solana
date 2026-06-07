# Runbook: program upgrade authority via Squads multisig

**Goal:** move the BPF *upgrade authority* of Etornie's three on-chain
programs from a single deployer keypair to a **3-of-5 Squads multisig**,
and perform all future upgrades through that multisig. A single key
holding upgrade authority is a mainnet blocker (issue #17): one
compromised key could ship a malicious program.

Programs (devnet ids):

| Program | Program id |
|---------|-----------|
| `etornie_attestation` | `CpLYWQn39xw1Qei1fqcDF8NkJGiJsME2dKpAfzkN1T2X` |
| `etornie_ip_token` | `6WrZ6NmuQtfpufrLbk5prQCKuF4isX1JwbrvxGFxT2gF` |
| `etornie_zk_verifier` | `GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5` |

> Check the current authority any time: `solana program show <id> --url devnet`.
> As of writing, all three are owned by the deployer wallet
> `CBDjvUkZZ6ucrVGrU3vRraasTytha8oVg2NLCxAHE25b`.

> ⚠️ Transferring upgrade authority is **irreversible without the new
> authority**. If you set it to the wrong address you can no longer
> upgrade the program. Do devnet first, and double-check the vault PDA.

---

## Prerequisites

- **Squads CLI**: `cargo install squads-multisig-cli`
  (`squads-multisig-cli --help`).
- **Solana CLI** ≥ 2.x (`solana --version`).
- The keypair of the **current** upgrade authority (the deployer wallet
  above). On devnet this is the deployer wallet, **not** the backend
  operator key (`services/api/keys/operator.json`).
- **Five member public keys** for the multisig signers, and a funded
  fee-payer keypair.
- (Easy alternative to the CLI: the Squads web app —
  <https://devnet.squads.so> for devnet.)

---

## Step 1 — Create the 3-of-5 multisig

```bash
squads-multisig-cli multisig-create \
  --rpc-url https://api.devnet.solana.com \
  --keypair <FEE_PAYER_KEYPAIR.json> \
  --members <MEMBER_1_PUBKEY> <MEMBER_2_PUBKEY> <MEMBER_3_PUBKEY> <MEMBER_4_PUBKEY> <MEMBER_5_PUBKEY> \
  --threshold 3
```

> Member permission encoding (propose/vote/execute) is shown by
> `squads-multisig-cli multisig-create --help`; give each member full
> permissions unless you intend role separation.

Record the printed **multisig account address** — call it `<MULTISIG>`.

## Step 2 — Find the vault PDA

The upgrade authority must become the multisig's **vault PDA** (vault
index `0`), *not* the multisig account itself. The vault is the address
that actually holds assets/authorities.

- In the Squads web app the vault address is shown on the squad's home.
- Programmatically it is `getVaultPda({ multisigPda: <MULTISIG>, index: 0 })`
  from `@sqds/multisig`.

Record it as `<VAULT_PDA>`.

## Step 3 — Transfer upgrade authority of all three programs

Use the helper (prompts for confirmation, prints before/after):

```bash
scripts/transfer-upgrade-authority.sh <VAULT_PDA> <CURRENT_AUTHORITY_KEYPAIR.json> devnet
```

Equivalent manual command per program (the `--skip-...-signer-check`
flag is required because a PDA cannot sign):

```bash
solana program set-upgrade-authority <PROGRAM_ID> \
  --new-upgrade-authority <VAULT_PDA> \
  --skip-new-upgrade-authority-signer-check \
  --keypair <CURRENT_AUTHORITY_KEYPAIR.json> \
  --url https://api.devnet.solana.com
```

## Step 4 — Verify

```bash
for id in CpLYWQn39xw1Qei1fqcDF8NkJGiJsME2dKpAfzkN1T2X \
          6WrZ6NmuQtfpufrLbk5prQCKuF4isX1JwbrvxGFxT2gF \
          GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5; do
  solana program show "$id" --url https://api.devnet.solana.com | grep -i Authority
done
```

Every `Authority` must now equal `<VAULT_PDA>`. ✅ Issue #17 criteria 1 & 2.

---

## Performing a future upgrade (through the multisig)

Once the vault owns upgrade authority, a single key can no longer upgrade
a program — it takes 3 of 5 approvals.

1. **Build** the new program reproducibly — see
   [build-reproducibility.md](../build-reproducibility.md). You get
   `target/deploy/<program>.so`.
2. **Write a buffer** and hand it to the vault:
   ```bash
   solana program write-buffer target/deploy/<program>.so --url <rpc>
   # -> Buffer: <BUFFER>
   solana program set-buffer-authority <BUFFER> \
     --new-buffer-authority <VAULT_PDA> --url <rpc>
   ```
3. **Propose the upgrade** as a multisig transaction. Easiest: the Squads
   web app → the program → **Add upgrade** (enter the program id + buffer).
   Via CLI, create a vault transaction carrying the BPF Upgradeable Loader
   `Upgrade` instruction (program, buffer, vault as authority, spill):
   ```bash
   squads-multisig-cli vault-transaction-create \
     --rpc-url <rpc> --keypair <member.json> \
     --multisig-pubkey <MULTISIG> --transaction-message <...upgrade ix...>
   ```
4. **Approve** until the threshold (3) is met:
   ```bash
   squads-multisig-cli proposal-vote --action Approve \
     --rpc-url <rpc> --keypair <member.json> \
     --multisig-pubkey <MULTISIG> --transaction-index <N>
   ```
5. **Execute**:
   ```bash
   squads-multisig-cli vault-transaction-execute \
     --rpc-url <rpc> --keypair <member.json> \
     --multisig-pubkey <MULTISIG> --transaction-index <N>
   ```

## Safety & rollback

- **Verify `<VAULT_PDA>` before Step 3.** A wrong address permanently
  removes your ability to upgrade.
- Changing the authority back, the threshold, or the member set are all
  themselves multisig transactions (propose → approve → execute).
- Keep the member keys on separate machines/people; 3-of-5 means losing
  up to 2 keys is survivable, and no single key can act alone.
- Rehearse this entire runbook on **devnet** before mainnet. The mainnet
  flow is identical — swap `--rpc-url`/`--url` to `https://api.mainnet-beta.solana.com`
  and use the mainnet program ids.
