pragma circom 2.0.0;

include "circomlib/circuits/poseidon.circom";

// FileOwnership: proves knowledge of a `secret` such that
//   Poseidon(secret, file_hash_hi, file_hash_lo) == commitment
// without revealing the secret or the underlying file.
//
// `file_hash` is the sha256 of the file content (256 bits). BN254's scalar
// field is ~254 bits, so the hash is split big-endian into two 128-bit
// halves that each fit cleanly in one field element — no bits dropped.
//
//   file_hash_hi = top 128 bits of sha256(file)
//   file_hash_lo = bottom 128 bits of sha256(file)
//
// Public inputs (in declaration order, matches snarkjs public.json output):
//   1. file_hash_hi
//   2. file_hash_lo
//   3. commitment   (= Poseidon(secret, fh_hi, fh_lo))
//
// Private input:
//   - secret
template FileOwnership() {
    signal input secret;
    signal input file_hash_hi;
    signal input file_hash_lo;
    signal input commitment;

    component h = Poseidon(3);
    h.inputs[0] <== secret;
    h.inputs[1] <== file_hash_hi;
    h.inputs[2] <== file_hash_lo;

    commitment === h.out;
}

component main {public [file_hash_hi, file_hash_lo, commitment]} = FileOwnership();
