pragma circom 2.0.0;

include "circomlib/circuits/poseidon.circom";

// ComplianceProof: proves knowledge of a `secret` such that
//   Poseidon(secret, query_hash_hi, query_hash_lo) == commitment
// without revealing the secret or the plaintext query.
//
// Used by the EtornieGPT x402 flow to bind an on-chain payment to an AI
// query. The query_hash is sha256 of the query text (256 bits). BN254's
// scalar field is ~254 bits, so the hash is split big-endian into two
// 128-bit halves that each fit cleanly in one field element.
//
//   query_hash_hi = top 128 bits of sha256(query)
//   query_hash_lo = bottom 128 bits of sha256(query)
//
// Public inputs (in declaration order, matches snarkjs public.json output):
//   1. query_hash_hi
//   2. query_hash_lo
//   3. commitment    (= Poseidon(secret, qh_hi, qh_lo))
//
// Private input:
//   - secret
template ComplianceProof() {
    signal input secret;
    signal input query_hash_hi;
    signal input query_hash_lo;
    signal input commitment;

    component h = Poseidon(3);
    h.inputs[0] <== secret;
    h.inputs[1] <== query_hash_hi;
    h.inputs[2] <== query_hash_lo;

    commitment === h.out;
}

component main {public [query_hash_hi, query_hash_lo, commitment]} = ComplianceProof();
