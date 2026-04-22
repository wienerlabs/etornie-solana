#!/usr/bin/env bash
# Full snarkjs + circom pipeline for the hello_world circuit.
#
# Steps:
#   1. compile hello_world.circom to r1cs + wasm + sym
#   2. run a fresh powers-of-tau phase 1 ceremony (small, dev-only)
#   3. contribute to phase 2 and derive the final zkey
#   4. export the verification key
#   5. generate the witness for the provided input.json
#   6. produce a Groth16 proof
#   7. verify the proof
#
# This is a dev-only ceremony. Production circuits must use the Hermez
# pot14 ptau and a multi-party phase 2.

set -euo pipefail

ZK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CIRCUIT_NAME="hello_world"
CIRCUIT_DIR="${ZK_ROOT}/circuits/${CIRCUIT_NAME}"
BUILD_DIR="${ZK_ROOT}/build/${CIRCUIT_NAME}"
PTAU_POWER=12

mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

echo "[1/7] compile circom"
circom "${CIRCUIT_DIR}/${CIRCUIT_NAME}.circom" \
  --r1cs --wasm --sym \
  -o "${BUILD_DIR}" \
  -l "${ZK_ROOT}/node_modules"

echo "[2/7] powers of tau phase 1 (bn128, 2^${PTAU_POWER})"
snarkjs powersoftau new bn128 ${PTAU_POWER} pot${PTAU_POWER}_0000.ptau -v

CONTRIB_ENTROPY="etornie-solana-dev-$(date +%s)"
snarkjs powersoftau contribute \
  pot${PTAU_POWER}_0000.ptau \
  pot${PTAU_POWER}_0001.ptau \
  --name="dev" \
  -v -e="${CONTRIB_ENTROPY}"

snarkjs powersoftau prepare phase2 \
  pot${PTAU_POWER}_0001.ptau \
  pot${PTAU_POWER}_final.ptau -v

echo "[3/7] groth16 phase 2 (zkey)"
snarkjs groth16 setup \
  "${CIRCUIT_NAME}.r1cs" \
  pot${PTAU_POWER}_final.ptau \
  "${CIRCUIT_NAME}_0.zkey"

snarkjs zkey contribute \
  "${CIRCUIT_NAME}_0.zkey" \
  "${CIRCUIT_NAME}_final.zkey" \
  --name="dev-phase2" \
  -v -e="${CONTRIB_ENTROPY}-phase2"

echo "[4/7] export verification key"
snarkjs zkey export verificationkey \
  "${CIRCUIT_NAME}_final.zkey" \
  verification_key.json

echo "[5/7] compute witness from input.json"
node "${CIRCUIT_NAME}_js/generate_witness.js" \
  "${CIRCUIT_NAME}_js/${CIRCUIT_NAME}.wasm" \
  "${CIRCUIT_DIR}/input.json" \
  witness.wtns

echo "[6/7] produce groth16 proof"
snarkjs groth16 prove \
  "${CIRCUIT_NAME}_final.zkey" \
  witness.wtns \
  proof.json \
  public.json

echo "[7/7] verify"
snarkjs groth16 verify \
  verification_key.json \
  public.json \
  proof.json

echo
echo "public outputs: $(cat public.json)"
echo "proof file:     ${BUILD_DIR}/proof.json"
echo "verify key:     ${BUILD_DIR}/verification_key.json"
echo "OK"
