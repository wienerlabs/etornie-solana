use anchor_lang::prelude::*;
use anchor_lang::solana_program::hash::hashv;
use groth16_solana::groth16::Groth16Verifyingkey;

// Mosaic verifier (epic M0). All three verify paths now route through
// mosaic-groth16. groth16-solana is retained only for its `Groth16Verifyingkey`
// struct — the auto-generated VK modules (`groth16_vk`, `vk_file_ownership`,
// `vk_compliance`) type against it. Both the type and the dependency are
// removed in M13 once M7 bakes canonical VK bytes at build time.
use mosaic_core::error::OnChainError as MosaicError;
use mosaic_core::syscall::solana::SolanaSyscallBackend;
use mosaic_groth16::batch::batch_verify;
use mosaic_groth16::Groth16Verifier as MosaicGroth16Verifier;

pub mod groth16_vk;
pub mod vk_compliance;
pub mod vk_file_ownership;

use groth16_vk::VERIFYINGKEY;
use vk_compliance::VERIFYINGKEY as VK_COMPLIANCE;
use vk_file_ownership::VERIFYINGKEY as VK_FILE_OWNERSHIP;

declare_id!("GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5");

/// Number of public inputs for the hello_world Groth16 circuit.
/// When a new circuit is added this constant (and VERIFYINGKEY) must change
/// together - the on-chain verifier is circuit-specific.
pub const PUBLIC_INPUT_COUNT: usize = 1;

/// Number of public inputs for the file_ownership circuit:
/// [fh_hi, fh_lo, commitment]. The file_hash is sha256 of the file content,
/// split into two 128-bit halves so each fits in one BN254 field element.
pub const FILE_OWNERSHIP_PUBLIC_INPUT_COUNT: usize = 3;

/// Number of public inputs for the compliance circuit:
/// [qh_hi, qh_lo, commitment]. query_hash is sha256 of the AI query text,
/// split into two 128-bit halves so each fits in one BN254 field element.
pub const COMPLIANCE_PUBLIC_INPUT_COUNT: usize = 3;

/// Seed prefix for the ProofRecord PDA.
pub const PROOF_RECORD_SEED: &[u8] = b"proof";

/// Seed prefix for the BatchProofRecord PDA. PDA key =
/// (BATCH_RECORD_SEED, user, batch_digest) so a given batch is recorded once
/// per submitter.
pub const BATCH_RECORD_SEED: &[u8] = b"batch";

/// Maximum proofs in a single `verify_proof_batch` call. Bounded by the
/// 1232-byte Solana transaction: each entry is 288 bytes (256 proof + 32-byte
/// single public input), so up to 4 entries plus the batch_digest seed and
/// accounts fit one tx. Larger batches need address lookup tables or chunking.
pub const MAX_BATCH: usize = 4;

/// Seed prefix for the FileOwnershipRecord PDA. PDA key =
/// (FILE_OWNERSHIP_SEED, user, file_hash) so multiple users can register
/// independent ownership claims for the same file.
pub const FILE_OWNERSHIP_SEED: &[u8] = b"file-ownership";

/// Seed prefix for the ComplianceRecord PDA. PDA key =
/// (COMPLIANCE_SEED, user, query_hash) so the same user cannot pay twice
/// for the same query, but different users can independently query the
/// same text without colliding.
pub const COMPLIANCE_SEED: &[u8] = b"compliance";

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
    /// The client is expected to prepend a `ComputeBudgetInstruction::set_compute_unit_limit(180_000)`.
    /// On mosaic-groth16 a single BN254 verify is ~83.5k CU; with PDA init and
    /// Anchor overhead the instruction lands well under 180k (down from the 300k
    /// requested under groth16-solana). Exact figure is calibrated by the
    /// on-chain benchmark in CI (#48) and the SBF integration tests (M9).
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

        // 3. Groth16 pairing verify on BN254 via Mosaic (mosaic-groth16).
        //    Mosaic takes the proof as a single 256-byte `A || B || C` blob,
        //    the VK in canonical byte layout, and the public inputs
        //    concatenated big-endian. The `concat` buffer built in step 1
        //    already holds the inputs in exactly that form, so we reuse it.
        let mut proof_bytes = [0u8; 256];
        proof_bytes[..64].copy_from_slice(&proof_a);
        proof_bytes[64..192].copy_from_slice(&proof_b);
        proof_bytes[192..].copy_from_slice(&proof_c);

        let backend = SolanaSyscallBackend::new();
        let verifier = MosaicGroth16Verifier::<_, false>::new(&backend);
        verifier
            .verify(&vk_canonical(&VERIFYINGKEY), &proof_bytes, &concat)
            .map_err(map_mosaic_error)?;

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

    /// Batched HelloWorld verification: verify `N` proofs (`2..=MAX_BATCH`)
    /// sharing the hello_world VK in a single BN254 pairing via mosaic's
    /// Bowe-Gabizon batch verifier (~52k CU/proof vs ~83k single). One
    /// `BatchProofRecord` PDA keyed on `(user, batch_digest)` gives the whole
    /// batch replay protection.
    ///
    /// `batch_digest` MUST equal `sha256(concat(per-entry journal digests))`,
    /// where each journal digest is `sha256(concat(entry.public_inputs))`. The
    /// handler recomputes and checks it so the PDA seed cannot be spoofed.
    ///
    /// The client should prepend a larger compute budget than the single-proof
    /// path (a batch of 4 is roughly 400k CU). See the program README.
    pub fn verify_proof_batch(
        ctx: Context<VerifyProofBatch>,
        batch_digest: [u8; 32],
        entries: Vec<BatchEntry>,
    ) -> Result<()> {
        let n = entries.len();
        require!((2..=MAX_BATCH).contains(&n), ZkError::InvalidBatchSize);

        // 1. Recompute the batch digest from the entries' public inputs and pin
        //    it to the client-supplied value used as the PDA seed.
        let mut digest_concat = Vec::with_capacity(n * 32);
        for entry in entries.iter() {
            let mut pi_concat = [0u8; 32 * PUBLIC_INPUT_COUNT];
            for (i, input) in entry.public_inputs.iter().enumerate() {
                pi_concat[i * 32..(i + 1) * 32].copy_from_slice(input);
            }
            let jd = hashv(&[&pi_concat]).to_bytes();
            digest_concat.extend_from_slice(&jd);
        }
        let computed = hashv(&[&digest_concat]).to_bytes();
        require!(computed == batch_digest, ZkError::MismatchedDigest);

        // 2. Replay protection at the batch level.
        let record = &mut ctx.accounts.batch_record;
        require!(!record.is_initialized, ZkError::ReplayedProof);

        // 3. Pack proofs + public inputs into the slice-of-slices mosaic wants.
        let mut proof_blobs: Vec<[u8; 256]> = Vec::with_capacity(n);
        let mut pi_blobs: Vec<[u8; 32 * PUBLIC_INPUT_COUNT]> = Vec::with_capacity(n);
        for entry in entries.iter() {
            let mut pb = [0u8; 256];
            pb[..64].copy_from_slice(&entry.proof_a);
            pb[64..192].copy_from_slice(&entry.proof_b);
            pb[192..].copy_from_slice(&entry.proof_c);
            proof_blobs.push(pb);

            let mut pi = [0u8; 32 * PUBLIC_INPUT_COUNT];
            for (i, input) in entry.public_inputs.iter().enumerate() {
                pi[i * 32..(i + 1) * 32].copy_from_slice(input);
            }
            pi_blobs.push(pi);
        }
        let proof_refs: Vec<&[u8]> = proof_blobs.iter().map(|b| b.as_slice()).collect();
        let pi_refs: Vec<&[u8]> = pi_blobs.iter().map(|b| b.as_slice()).collect();

        // 4. Single batched pairing check over all N proofs.
        let backend = SolanaSyscallBackend::new();
        batch_verify::<_, false>(&backend, &vk_canonical(&VERIFYINGKEY), &proof_refs, &pi_refs)
            .map_err(map_mosaic_error)?;

        // 5. Persist the batch record.
        record.submitter = ctx.accounts.user.key();
        record.batch_digest = batch_digest;
        record.count = n as u8;
        record.verified_at = Clock::get()?.unix_timestamp;
        record.bump = ctx.bumps.batch_record;
        record.is_initialized = true;

        msg!(
            "zk-verifier: batch recorded (user={}, count={}, verified_at={})",
            record.submitter,
            record.count,
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
    /// check - closing the grief vector where unused high bits of the 254-bit
    /// field elements could map unrelated files to the same PDA.
    ///
    /// Same CU budget expectation as `verify_proof`: client should prepend
    /// `ComputeBudgetInstruction::set_compute_unit_limit(180_000)`.
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
        let (expected_fh_hi, expected_fh_lo) = hash_to_field_halves(&file_hash);
        require!(
            public_inputs[0] == expected_fh_hi && public_inputs[1] == expected_fh_lo,
            ZkError::MalformedFileHashInput
        );

        // 2. Replay protection. PDA seeds already enforce per-(user, file_hash)
        //    uniqueness; the flag catches the second init in the same account.
        let record = &mut ctx.accounts.file_ownership_record;
        require!(!record.is_initialized, ZkError::ReplayedProof);

        // 3. Groth16 pairing verify on BN254 via Mosaic (mosaic-groth16).
        let mut proof_bytes = [0u8; 256];
        proof_bytes[..64].copy_from_slice(&proof_a);
        proof_bytes[64..192].copy_from_slice(&proof_b);
        proof_bytes[192..].copy_from_slice(&proof_c);

        let mut pi_bytes = [0u8; 32 * FILE_OWNERSHIP_PUBLIC_INPUT_COUNT];
        for (i, input) in public_inputs.iter().enumerate() {
            pi_bytes[i * 32..(i + 1) * 32].copy_from_slice(input);
        }

        let backend = SolanaSyscallBackend::new();
        let verifier = MosaicGroth16Verifier::<_, false>::new(&backend);
        verifier
            .verify(&vk_canonical(&VK_FILE_OWNERSHIP), &proof_bytes, &pi_bytes)
            .map_err(map_mosaic_error)?;

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

    /// Verifies a Groth16 proof that the caller knows a secret `s` such that
    /// `Poseidon(s, qh_hi, qh_lo) == commitment`, without revealing `s` or the
    /// plaintext query. Records the compliance attestation in a per-(user,
    /// query_hash) PDA so the same user cannot be charged twice for an
    /// already-attested query. Used by the EtornieGPT x402 payment flow -
    /// binds the off-chain payment tx (memo = sha256(qh || commitment)) to
    /// an on-chain ZK authorization record.
    ///
    /// `query_hash` is passed explicitly (same pattern as file_ownership) and
    /// pinned to the (qh_hi, qh_lo) halves via a zero-padded equality check,
    /// closing the grief vector where unused high bits of the 254-bit field
    /// elements could map unrelated queries to the same PDA.
    ///
    /// Same CU budget expectation as `verify_proof`: client should prepend
    /// `ComputeBudgetInstruction::set_compute_unit_limit(180_000)`.
    pub fn verify_compliance_proof(
        ctx: Context<VerifyCompliance>,
        proof_a: [u8; 64],
        proof_b: [u8; 128],
        proof_c: [u8; 64],
        public_inputs: [[u8; 32]; COMPLIANCE_PUBLIC_INPUT_COUNT],
        query_hash: [u8; 32],
    ) -> Result<()> {
        // 1. Pin the canonical encoding of (qh_hi, qh_lo).
        let (expected_qh_hi, expected_qh_lo) = hash_to_field_halves(&query_hash);
        require!(
            public_inputs[0] == expected_qh_hi && public_inputs[1] == expected_qh_lo,
            ZkError::MalformedQueryHashInput
        );

        // 2. Replay protection. PDA seeds already enforce per-(user, query_hash)
        //    uniqueness; the flag catches the second init in the same account.
        let record = &mut ctx.accounts.compliance_record;
        require!(!record.is_initialized, ZkError::ReplayedProof);

        // 3. Groth16 pairing verify on BN254 via Mosaic (mosaic-groth16).
        let mut proof_bytes = [0u8; 256];
        proof_bytes[..64].copy_from_slice(&proof_a);
        proof_bytes[64..192].copy_from_slice(&proof_b);
        proof_bytes[192..].copy_from_slice(&proof_c);

        let mut pi_bytes = [0u8; 32 * COMPLIANCE_PUBLIC_INPUT_COUNT];
        for (i, input) in public_inputs.iter().enumerate() {
            pi_bytes[i * 32..(i + 1) * 32].copy_from_slice(input);
        }

        let backend = SolanaSyscallBackend::new();
        let verifier = MosaicGroth16Verifier::<_, false>::new(&backend);
        verifier
            .verify(&vk_canonical(&VK_COMPLIANCE), &proof_bytes, &pi_bytes)
            .map_err(map_mosaic_error)?;

        // 4. Persist the compliance record.
        record.payer = ctx.accounts.user.key();
        record.query_hash = query_hash;
        record.commitment = public_inputs[2];
        record.verified_at = Clock::get()?.unix_timestamp;
        record.bump = ctx.bumps.compliance_record;
        record.is_initialized = true;

        msg!(
            "zk-verifier: compliance recorded (user={}, verified_at={})",
            record.payer,
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

    /// Logical owner of the proof - PDA is keyed to this pubkey so the
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

/// A single proof in a `verify_proof_batch` call. `journal_digest` is omitted
/// (recomputed on-chain from `public_inputs`) to keep the entry small so more
/// fit under the transaction size limit.
#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct BatchEntry {
    pub proof_a: [u8; 64],
    pub proof_b: [u8; 128],
    pub proof_c: [u8; 64],
    pub public_inputs: [[u8; 32]; PUBLIC_INPUT_COUNT],
}

#[derive(Accounts)]
#[instruction(batch_digest: [u8; 32])]
pub struct VerifyProofBatch<'info> {
    /// Covers the tx fee and the PDA rent.
    #[account(mut)]
    pub fee_payer: Signer<'info>,

    /// Logical owner of the batch - PDA is keyed to this pubkey.
    pub user: Signer<'info>,

    #[account(
        init,
        payer = fee_payer,
        space = 8 + BatchProofRecord::INIT_SPACE,
        seeds = [BATCH_RECORD_SEED, user.key().as_ref(), batch_digest.as_ref()],
        bump,
    )]
    pub batch_record: Account<'info, BatchProofRecord>,

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

#[derive(Accounts)]
#[instruction(
    _proof_a: [u8; 64],
    _proof_b: [u8; 128],
    _proof_c: [u8; 64],
    _public_inputs: [[u8; 32]; COMPLIANCE_PUBLIC_INPUT_COUNT],
    query_hash: [u8; 32],
)]
pub struct VerifyCompliance<'info> {
    /// Covers tx fee and PDA rent. The backend operator pays both so the
    /// end-user only signs the off-chain USDC/SOL micro-payment tx - no
    /// second Phantom popup for the on-chain compliance record.
    #[account(mut)]
    pub fee_payer: Signer<'info>,

    /// Wallet that paid for the AI query. Not a signer: the ZK proof's
    /// commitment is derived from a secret computed off-chain from this
    /// wallet's signature (see frontend compliance lib), so the proof
    /// itself binds the record to this wallet - an additional on-chain
    /// signature would be redundant and double the wallet popup count.
    /// PDA is still keyed on (user, query_hash) so per-user scoping holds.
    /// CHECK: consumed only as a PDA seed; no data is read or mutated.
    pub user: UncheckedAccount<'info>,

    #[account(
        init_if_needed,
        payer = fee_payer,
        space = 8 + ComplianceRecord::INIT_SPACE,
        seeds = [COMPLIANCE_SEED, user.key().as_ref(), query_hash.as_ref()],
        bump,
    )]
    pub compliance_record: Account<'info, ComplianceRecord>,

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
pub struct BatchProofRecord {
    /// Submitter (the `user` signer the PDA is keyed on).
    pub submitter: Pubkey,
    /// sha256(concat(per-entry journal digests)) — also the PDA seed.
    pub batch_digest: [u8; 32],
    /// Number of proofs verified in the batch (2..=MAX_BATCH).
    pub count: u8,
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

#[account]
#[derive(InitSpace)]
pub struct ComplianceRecord {
    /// Pubkey of the wallet that paid for this query.
    pub payer: Pubkey,
    /// sha256 of the plaintext AI query.
    pub query_hash: [u8; 32],
    /// Poseidon commitment = Poseidon(secret, qh_hi, qh_lo).
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
    #[msg("query_hash argument does not match the canonical zero-padded halves in public inputs")]
    MalformedQueryHashInput,
    #[msg("Batch size must be between 2 and MAX_BATCH proofs")]
    InvalidBatchSize,
}

/// Encode a groth16-solana `Groth16Verifyingkey` into Mosaic canonical VK
/// bytes. The byte layout is identical between the two libraries, so this is a
/// pure concatenation:
///
/// ```text
/// alpha_g1 (64) || beta_g2 (128) || gamma_g2 (128) || delta_g2 (128) || ic[] (64 each)
/// ```
///
/// `ic.len()` == `nr_pubinputs` == `N_public_inputs + 1` (ic[0] is the constant
/// term). Recomputed per call (~700 B heap); M7 replaces this with a build-time
/// baked constant once the `mosaic-serde` snarkjs adapter lands.
fn vk_canonical(vk: &Groth16Verifyingkey) -> Vec<u8> {
    let mut out = Vec::with_capacity(64 + 128 * 3 + 64 * vk.vk_ic.len());
    out.extend_from_slice(&vk.vk_alpha_g1);
    out.extend_from_slice(&vk.vk_beta_g2);
    out.extend_from_slice(&vk.vk_gamme_g2);
    out.extend_from_slice(&vk.vk_delta_g2);
    for ic in vk.vk_ic.iter() {
        out.extend_from_slice(ic);
    }
    out
}

/// Split a 32-byte hash into two BN254 field elements: the top 16 bytes and the
/// bottom 16 bytes, each zero-padded into the low half of a 32-byte big-endian
/// field element. Mirrors the `(hi, lo)` canonical encoding the file-ownership
/// and compliance circuits expect, and pins the unused high bits to zero so a
/// caller cannot land on a PDA keyed on a hash that differs from the public
/// inputs (the grief vector documented inline at each call site).
fn hash_to_field_halves(hash: &[u8; 32]) -> ([u8; 32], [u8; 32]) {
    let mut hi = [0u8; 32];
    hi[16..].copy_from_slice(&hash[..16]);
    let mut lo = [0u8; 32];
    lo[16..].copy_from_slice(&hash[16..]);
    (hi, lo)
}

/// Map a Mosaic `OnChainError` onto the program's existing `ZkError` surface so
/// clients keep seeing the same error codes after the migration.
fn map_mosaic_error(e: MosaicError) -> Error {
    match e {
        MosaicError::PairingCheckFailed | MosaicError::VerificationFailed => {
            ZkError::InvalidProof.into()
        }
        MosaicError::PublicInputOutOfRange | MosaicError::PublicInputCountMismatch => {
            ZkError::MalformedPublicInput.into()
        }
        MosaicError::ProofLengthMismatch
        | MosaicError::VerifyingKeyLengthMismatch
        | MosaicError::InvalidPointEncoding
        | MosaicError::PointNotOnCurve => ZkError::MalformedPublicInput.into(),
        // Syscall failures and internal invariants collapse to the program's
        // generic verifier-internal code.
        _ => ZkError::VerifierInternal.into(),
    }
}
