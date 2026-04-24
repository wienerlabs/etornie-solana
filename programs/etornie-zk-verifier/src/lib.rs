use anchor_lang::prelude::*;
use anchor_lang::solana_program::hash::hashv;
use groth16_solana::errors::Groth16Error;
use groth16_solana::groth16::Groth16Verifier;

pub mod groth16_vk;
pub mod vk_file_ownership;

use groth16_vk::VERIFYINGKEY;
use vk_file_ownership::VERIFYINGKEY as VK_FILE_OWNERSHIP;

declare_id!("GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5");

/// Number of public inputs for the hello_world Groth16 circuit.
/// When a new circuit is added this constant (and VERIFYINGKEY) must change
/// together — the on-chain verifier is circuit-specific.
pub const PUBLIC_INPUT_COUNT: usize = 1;

/// Number of public inputs for the file_ownership circuit:
/// [fh_hi, fh_lo, commitment]. The file_hash is sha256 of the file content,
/// split into two 128-bit halves so each fits in one BN254 field element.
pub const FILE_OWNERSHIP_PUBLIC_INPUT_COUNT: usize = 3;

/// Seed prefix for the ProofRecord PDA.
pub const PROOF_RECORD_SEED: &[u8] = b"proof";

/// Seed prefix for the FileOwnershipRecord PDA. PDA key =
/// (FILE_OWNERSHIP_SEED, user, file_hash) so multiple users can register
/// independent ownership claims for the same file.
pub const FILE_OWNERSHIP_SEED: &[u8] = b"file-ownership";

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

        // 4. Persist the record. The `operator` field name is kept for
        // storage-layout continuity but semantically stores the user key
        // (the PDA seed is derived from `user`, not `fee_payer`).
        record.operator = ctx.accounts.user.key();
        record.journal_digest = journal_digest;
        record.verified_at = Clock::get()?.unix_timestamp;
        record.bump = ctx.bumps.proof_record;
        record.is_initialized = true;

        msg!(
            "zk-verifier: proof recorded (user={}, fee_payer={}, verified_at={})",
            record.operator,
            ctx.accounts.fee_payer.key(),
            record.verified_at
        );

        Ok(())
    }

    /// Verifies a Groth16 proof that the caller knows a secret `s` such that
    /// `Poseidon(s, fh_hi, fh_lo) == commitment`, without revealing `s` or the
    /// underlying file. Records the ownership claim in a per-(user, file_hash)
    /// PDA so the same user cannot double-register ownership of the same file.
    ///
    /// `file_hash` is passed explicitly (not reconstructed from public inputs)
    /// so the PDA seed expression stays a single `&[u8]`. The body then pins
    /// the (fh_hi, fh_lo) halves to `file_hash` with a zero-padded equality
    /// check — closing the grief vector where unused high bits of the 254-bit
    /// field elements could map unrelated files to the same PDA.
    ///
    /// Same CU budget expectation as `verify_proof`: client should prepend
    /// `ComputeBudgetInstruction::set_compute_unit_limit(300_000)`.
    pub fn verify_file_ownership_proof(
        ctx: Context<VerifyFileOwnership>,
        proof_a: [u8; 64],
        proof_b: [u8; 128],
        proof_c: [u8; 64],
        public_inputs: [[u8; 32]; FILE_OWNERSHIP_PUBLIC_INPUT_COUNT],
        file_hash: [u8; 32],
    ) -> Result<()> {
        // 1. Pin the canonical encoding of (fh_hi, fh_lo).
        //    Each public input is a 32-byte BE field element; fh_hi carries
        //    the top 16 bytes of file_hash zero-padded in the low half, and
        //    fh_lo carries the bottom 16 bytes the same way. Without this,
        //    a caller could pick arbitrary high bits and land on a PDA
        //    keyed on a file_hash that does not match `public_inputs`.
        let mut expected_fh_hi = [0u8; 32];
        expected_fh_hi[16..].copy_from_slice(&file_hash[..16]);
        let mut expected_fh_lo = [0u8; 32];
        expected_fh_lo[16..].copy_from_slice(&file_hash[16..]);
        require!(
            public_inputs[0] == expected_fh_hi && public_inputs[1] == expected_fh_lo,
            ZkError::MalformedFileHashInput
        );

        // 2. Replay protection. PDA seeds already enforce per-(user, file_hash)
        //    uniqueness; the flag catches the second init in the same account.
        let record = &mut ctx.accounts.file_ownership_record;
        require!(!record.is_initialized, ZkError::ReplayedProof);

        // 3. Groth16 pairing verify on BN254.
        let mut verifier =
            Groth16Verifier::<FILE_OWNERSHIP_PUBLIC_INPUT_COUNT>::new(
                &proof_a,
                &proof_b,
                &proof_c,
                &public_inputs,
                &VK_FILE_OWNERSHIP,
            )
            .map_err(map_groth16_error)?;

        verifier.verify().map_err(map_groth16_error)?;

        // 4. Persist the ownership record.
        record.owner = ctx.accounts.user.key();
        record.file_hash = file_hash;
        record.commitment = public_inputs[2];
        record.verified_at = Clock::get()?.unix_timestamp;
        record.bump = ctx.bumps.file_ownership_record;
        record.is_initialized = true;

        msg!(
            "zk-verifier: file ownership recorded (user={}, verified_at={})",
            record.owner,
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
    /// Covers the tx fee and the PDA rent. In the sponsored flow this is
    /// the backend operator; the user-pays flow sets it equal to `user`.
    #[account(mut)]
    pub fee_payer: Signer<'info>,

    /// Logical owner of the proof — PDA is keyed to this pubkey so the
    /// replay check is scoped per-user, not per-fee-payer.
    pub user: Signer<'info>,

    #[account(
        init_if_needed,
        payer = fee_payer,
        space = 8 + ProofRecord::INIT_SPACE,
        seeds = [PROOF_RECORD_SEED, user.key().as_ref(), journal_digest.as_ref()],
        bump,
    )]
    pub proof_record: Account<'info, ProofRecord>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(
    _proof_a: [u8; 64],
    _proof_b: [u8; 128],
    _proof_c: [u8; 64],
    _public_inputs: [[u8; 32]; FILE_OWNERSHIP_PUBLIC_INPUT_COUNT],
    file_hash: [u8; 32],
)]
pub struct VerifyFileOwnership<'info> {
    /// Covers tx fee and PDA rent. In the sponsored flow this is the backend
    /// operator; in the user-pays flow it is set equal to `user`.
    #[account(mut)]
    pub fee_payer: Signer<'info>,

    /// Logical owner of the claim. PDA is keyed on (user, file_hash) so two
    /// different users can independently claim ownership of the same file.
    pub user: Signer<'info>,

    #[account(
        init_if_needed,
        payer = fee_payer,
        space = 8 + FileOwnershipRecord::INIT_SPACE,
        seeds = [FILE_OWNERSHIP_SEED, user.key().as_ref(), file_hash.as_ref()],
        bump,
    )]
    pub file_ownership_record: Account<'info, FileOwnershipRecord>,

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

#[account]
#[derive(InitSpace)]
pub struct FileOwnershipRecord {
    /// Claim owner (pubkey of the signer that submitted the proof).
    pub owner: Pubkey,
    /// sha256 of the file whose ownership is claimed.
    pub file_hash: [u8; 32],
    /// Poseidon commitment = Poseidon(secret, fh_hi, fh_lo).
    pub commitment: [u8; 32],
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
    #[msg("file_hash argument does not match the canonical zero-padded halves in public inputs")]
    MalformedFileHashInput,
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
