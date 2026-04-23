use anchor_lang::prelude::*;
use anchor_lang::solana_program::hash::hashv;
use groth16_solana::errors::Groth16Error;
use groth16_solana::groth16::Groth16Verifier;

pub mod groth16_vk;
use groth16_vk::VERIFYINGKEY;

declare_id!("GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5");

/// Number of public inputs for the hello_world Groth16 circuit.
/// When a new circuit is added this constant (and VERIFYINGKEY) must change
/// together — the on-chain verifier is circuit-specific.
pub const PUBLIC_INPUT_COUNT: usize = 1;

/// Seed prefix for the ProofRecord PDA.
pub const PROOF_RECORD_SEED: &[u8] = b"proof";

#[program]
pub mod etornie_zk_verifier {
    use super::*;

    pub fn initialize(_ctx: Context<Initialize>) -> Result<()> {
        Ok(())
    }

    /// Verifies a Groth16 proof on-chain using the BN254 pairing syscall,
    /// then records the result in a PDA keyed on (operator, journal_digest)
    /// so the same proof cannot be submitted twice under the same operator.
    ///
    /// The client is expected to prepend a `ComputeBudgetInstruction::set_compute_unit_limit(300_000)`
    /// — the pairing + PDA init typically consumes ~180k CU, well above Anchor's 200k default.
    pub fn verify_proof(
        ctx: Context<VerifyProof>,
        proof_a: [u8; 64],
        proof_b: [u8; 128],
        proof_c: [u8; 64],
        public_inputs: [[u8; 32]; PUBLIC_INPUT_COUNT],
        journal_digest: [u8; 32],
    ) -> Result<()> {
        // 1. Journal digest integrity: client-supplied digest must equal
        //    sha256(concat(public_inputs)). Without this check, a client
        //    could pick an arbitrary PDA seed and write to an unrelated slot.
        let mut concat = [0u8; 32 * PUBLIC_INPUT_COUNT];
        for (i, input) in public_inputs.iter().enumerate() {
            concat[i * 32..(i + 1) * 32].copy_from_slice(input);
        }
        let computed = hashv(&[&concat]).to_bytes();
        require!(computed == journal_digest, ZkError::MismatchedDigest);

        // 2. Replay protection. init_if_needed returns a zero-initialised
        //    account on first write; our explicit flag catches the second
        //    attempt before any work is done.
        let record = &mut ctx.accounts.proof_record;
        require!(!record.is_initialized, ZkError::ReplayedProof);

        // 3. Groth16 pairing verify on BN254 via alt_bn128 syscalls.
        let mut verifier = Groth16Verifier::<PUBLIC_INPUT_COUNT>::new(
            &proof_a,
            &proof_b,
            &proof_c,
            &public_inputs,
            &VERIFYINGKEY,
        )
        .map_err(map_groth16_error)?;

        verifier.verify().map_err(map_groth16_error)?;

        // 4. Persist the record.
        record.operator = ctx.accounts.operator.key();
        record.journal_digest = journal_digest;
        record.verified_at = Clock::get()?.unix_timestamp;
        record.bump = ctx.bumps.proof_record;
        record.is_initialized = true;

        msg!(
            "zk-verifier: proof recorded (operator={}, verified_at={})",
            record.operator,
            record.verified_at
        );

        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Accounts
// ---------------------------------------------------------------------------

#[derive(Accounts)]
pub struct Initialize {}

#[derive(Accounts)]
#[instruction(
    _proof_a: [u8; 64],
    _proof_b: [u8; 128],
    _proof_c: [u8; 64],
    _public_inputs: [[u8; 32]; PUBLIC_INPUT_COUNT],
    journal_digest: [u8; 32],
)]
pub struct VerifyProof<'info> {
    #[account(mut)]
    pub operator: Signer<'info>,

    #[account(
        init_if_needed,
        payer = operator,
        space = 8 + ProofRecord::INIT_SPACE,
        seeds = [PROOF_RECORD_SEED, operator.key().as_ref(), journal_digest.as_ref()],
        bump,
    )]
    pub proof_record: Account<'info, ProofRecord>,

    pub system_program: Program<'info, System>,
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

#[account]
#[derive(InitSpace)]
pub struct ProofRecord {
    pub operator: Pubkey,
    pub journal_digest: [u8; 32],
    pub verified_at: i64,
    pub bump: u8,
    pub is_initialized: bool,
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

#[error_code]
pub enum ZkError {
    #[msg("Proof failed BN254 pairing verification")]
    InvalidProof,
    #[msg("Public inputs outside BN254 field size or wrong length")]
    MalformedPublicInput,
    #[msg("Journal digest does not match sha256(public_inputs)")]
    MismatchedDigest,
    #[msg("This proof has already been recorded for this operator")]
    ReplayedProof,
    #[msg("Internal verifier error (G1/G2 serialization or syscall failure)")]
    VerifierInternal,
}

fn map_groth16_error(e: Groth16Error) -> Error {
    match e {
        Groth16Error::ProofVerificationFailed => ZkError::InvalidProof.into(),
        Groth16Error::PublicInputGreaterThanFieldSize
        | Groth16Error::InvalidPublicInputsLength => ZkError::MalformedPublicInput.into(),
        // The remaining variants are unreachable in our flow: fixed-size byte
        // arrays rule out G1/G2 length mismatches, we never feed compressed
        // points, and VERIFYINGKEY is compile-time matched to PUBLIC_INPUT_COUNT.
        _ => ZkError::VerifierInternal.into(),
    }
}
