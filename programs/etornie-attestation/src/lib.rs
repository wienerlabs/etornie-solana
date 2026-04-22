use anchor_lang::prelude::*;

declare_id!("CpLYWQn39xw1Qei1fqcDF8NkJGiJsME2dKpAfzkN1T2X");

#[program]
pub mod etornie_attestation {
    use super::*;

    pub fn create_case_attestation(
        ctx: Context<CreateCaseAttestation>,
        case_id: [u8; 16],
        metadata_hash: [u8; 32],
        client_wallet: Pubkey,
    ) -> Result<()> {
        let a = &mut ctx.accounts.attestation;
        a.case_id = case_id;
        a.metadata_hash = metadata_hash;
        a.creator = ctx.accounts.creator.key();
        a.client_wallet = client_wallet;
        a.operator = ctx.accounts.operator.key();
        a.created_at = Clock::get()?.unix_timestamp;
        a.bump = ctx.bumps.attestation;
        Ok(())
    }

    /// Record a lifecycle event against an existing case attestation.
    ///
    /// The main PDA's ``metadata_hash`` is overwritten with the fresh
    /// hash (current case state at event time) and a typed ``emit!``
    /// event is written to the tx log so historical timelines can be
    /// reconstructed from Solana tx history.
    pub fn update_case_attestation(
        ctx: Context<UpdateCaseAttestation>,
        metadata_hash: [u8; 32],
        event_type: u8,
    ) -> Result<()> {
        let a = &mut ctx.accounts.attestation;
        let old_hash = a.metadata_hash;
        a.metadata_hash = metadata_hash;

        emit!(CaseAttestationUpdated {
            case_id: a.case_id,
            old_metadata_hash: old_hash,
            new_metadata_hash: metadata_hash,
            event_type,
            actor: ctx.accounts.actor.key(),
            operator: ctx.accounts.operator.key(),
            timestamp: Clock::get()?.unix_timestamp,
        });

        Ok(())
    }
}

#[derive(Accounts)]
#[instruction(case_id: [u8; 16])]
pub struct CreateCaseAttestation<'info> {
    // init ensures a given case_id can only be attested once.
    // Any replay attempt fails with AccountAlreadyInUse.
    #[account(
        init,
        payer = operator,
        space = 8 + CaseAttestation::INIT_SPACE,
        seeds = [b"case", case_id.as_ref()],
        bump,
    )]
    pub attestation: Account<'info, CaseAttestation>,

    /// Backend operator — pays rent and acts as co-signer so users do
    /// not need SOL in their wallet.
    #[account(mut)]
    pub operator: Signer<'info>,

    /// The case creator (user wallet). Signing this instruction is a
    /// cryptographic proof that the wallet owner authorized the case
    /// attestation; the pubkey is recorded as `creator` on the PDA.
    pub creator: Signer<'info>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct UpdateCaseAttestation<'info> {
    #[account(
        mut,
        seeds = [b"case", attestation.case_id.as_ref()],
        bump = attestation.bump,
    )]
    pub attestation: Account<'info, CaseAttestation>,

    /// Backend operator — pays fees so users do not need SOL.
    #[account(mut)]
    pub operator: Signer<'info>,

    /// The actor triggering the event (case creator, lawyer, admin).
    /// Signing this instruction authorizes the on-chain update.
    pub actor: Signer<'info>,
}

#[account]
#[derive(InitSpace)]
pub struct CaseAttestation {
    pub case_id: [u8; 16],
    pub metadata_hash: [u8; 32],
    pub creator: Pubkey,
    pub client_wallet: Pubkey,
    pub operator: Pubkey,
    pub created_at: i64,
    pub bump: u8,
}

#[event]
pub struct CaseAttestationUpdated {
    pub case_id: [u8; 16],
    pub old_metadata_hash: [u8; 32],
    pub new_metadata_hash: [u8; 32],
    pub event_type: u8,
    pub actor: Pubkey,
    pub operator: Pubkey,
    pub timestamp: i64,
}

#[error_code]
pub enum AttestationError {
    #[msg("Attestation already exists for this case id")]
    AttestationAlreadyExists,
}
