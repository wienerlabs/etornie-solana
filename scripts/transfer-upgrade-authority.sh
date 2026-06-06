#!/usr/bin/env bash
# Transfer the BPF upgrade authority of all three Etornie programs to a new
# authority — typically a Squads multisig **vault PDA** (issue #17).
#
# This is IRREVERSIBLE without the new authority: once the multisig vault
# owns upgrade authority, only a multisig transaction can change it back.
# Read docs/runbooks/program-upgrade.md before running.
#
# Usage:
#   scripts/transfer-upgrade-authority.sh <NEW_AUTHORITY> [AUTHORITY_KEYPAIR] [CLUSTER]
#
#   NEW_AUTHORITY      Squads vault PDA to receive upgrade authority (required)
#   AUTHORITY_KEYPAIR  keypair of the CURRENT upgrade authority (default: the
#                      keypair configured in `solana config`). NOTE: on devnet
#                      the current authority is the deployer wallet, not the
#                      backend operator key.
#   CLUSTER            devnet | mainnet-beta | <rpc-url>  (default: devnet)
set -euo pipefail

NEW_AUTHORITY="${1:-}"
AUTHORITY_KEYPAIR="${2:-}"
CLUSTER="${3:-devnet}"

# program label + program id
PROGRAMS=(
  "etornie_attestation:CpLYWQn39xw1Qei1fqcDF8NkJGiJsME2dKpAfzkN1T2X"
  "etornie_ip_token:6WrZ6NmuQtfpufrLbk5prQCKuF4isX1JwbrvxGFxT2gF"
  "etornie_zk_verifier:GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5"
)

if [ -z "$NEW_AUTHORITY" ]; then
  echo "usage: $0 <NEW_AUTHORITY_VAULT_PDA> [AUTHORITY_KEYPAIR] [CLUSTER]" >&2
  exit 1
fi

case "$CLUSTER" in
  devnet)       URL="https://api.devnet.solana.com" ;;
  mainnet-beta) URL="https://api.mainnet-beta.solana.com" ;;
  *)            URL="$CLUSTER" ;;
esac

KEYPAIR_ARGS=()
[ -n "$AUTHORITY_KEYPAIR" ] && KEYPAIR_ARGS=(--keypair "$AUTHORITY_KEYPAIR")

echo "Cluster:        $URL"
echo "New authority:  $NEW_AUTHORITY  (must be the Squads vault PDA)"
echo "Programs:"
for entry in "${PROGRAMS[@]}"; do echo "  - ${entry%%:*} (${entry##*:})"; done
echo
echo "This transfers upgrade authority of ALL three programs and is"
echo "IRREVERSIBLE without the new (multisig) authority. Type 'yes' to proceed:"
read -r confirm
[ "$confirm" = "yes" ] || { echo "Aborted."; exit 1; }

for entry in "${PROGRAMS[@]}"; do
  name="${entry%%:*}"
  id="${entry##*:}"
  echo
  echo "==== $name ($id) ===="
  echo "before: $(solana program show "$id" --url "$URL" 2>/dev/null | grep -i Authority || echo '?')"
  solana program set-upgrade-authority "$id" \
    --new-upgrade-authority "$NEW_AUTHORITY" \
    --skip-new-upgrade-authority-signer-check \
    --url "$URL" \
    "${KEYPAIR_ARGS[@]}"
  echo "after:  $(solana program show "$id" --url "$URL" 2>/dev/null | grep -i Authority || echo '?')"
done

echo
echo "Done. Verify every program's Authority now equals $NEW_AUTHORITY."
