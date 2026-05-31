//! Parity test: every snarkjs-verified Etornie circuit proof must also verify
//! under mosaic-groth16 (host backend). This proves the migration is sound —
//! the proofs that snarkjs accepts (circuits/build step 7 = OK) are byte-for-byte
//! accepted by the same verifier the on-chain program runs.
//!
//! Fixtures live in `tests/zk_fixtures/<circuit>/` (committed in M9 part 1).
//! Run from anywhere: `cargo test --manifest-path tests/zk-parity/Cargo.toml`.

use mosaic_core::error::OnChainError;
use mosaic_core::syscall::host::HostBackend;
use mosaic_groth16::Groth16Verifier;
use mosaic_serde::snarkjs::SnarkjsCodec;

/// Load a circuit's snarkjs bundle and decode it to mosaic canonical bytes.
fn fixture(circuit: &str) -> (Vec<u8>, Vec<u8>, Vec<u8>) {
    let base = format!(
        "{}/../zk_fixtures/{}",
        env!("CARGO_MANIFEST_DIR"),
        circuit
    );
    let proof = std::fs::read(format!("{base}/proof.json")).expect("proof.json");
    let vk = std::fs::read(format!("{base}/verification_key.json")).expect("verification_key.json");
    let public = std::fs::read(format!("{base}/public.json")).expect("public.json");
    let d = SnarkjsCodec::decode_bundle(&proof, &vk, &public).expect("decode_bundle");
    (d.vk, d.proof, d.public_inputs)
}

/// Verify a circuit's proof through mosaic's host backend (big-endian inputs,
/// matching the on-chain program's `Groth16Verifier::<_, false>`).
fn verify(circuit: &str) -> Result<(), OnChainError> {
    let (vk, proof, public) = fixture(circuit);
    let backend = HostBackend::new();
    let verifier = Groth16Verifier::<_, false>::new(&backend);
    verifier.verify(&vk, &proof, &public)
}

#[test]
fn hello_world_proof_verifies_on_mosaic() {
    verify("hello_world").expect("mosaic must accept the snarkjs-verified hello_world proof");
}

#[test]
fn file_ownership_proof_verifies_on_mosaic() {
    verify("file_ownership").expect("mosaic must accept the snarkjs-verified file_ownership proof");
}

#[test]
fn compliance_proof_verifies_on_mosaic() {
    verify("compliance").expect("mosaic must accept the snarkjs-verified compliance proof");
}

#[test]
fn tampered_proof_is_rejected() {
    let (vk, mut proof, public) = fixture("hello_world");
    // Flip one byte of the proof's A point; the pairing check must now fail.
    proof[0] ^= 0x01;
    let backend = HostBackend::new();
    let verifier = Groth16Verifier::<_, false>::new(&backend);
    assert!(
        verifier.verify(&vk, &proof, &public).is_err(),
        "a tampered proof must be rejected"
    );
}
