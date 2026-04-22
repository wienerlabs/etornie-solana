use anchor_lang::prelude::*;

declare_id!("CpLYWQn39xw1Qei1fqcDF8NkJGiJsME2dKpAfzkN1T2X");

#[program]
pub mod etornie_attestation {
    use super::*;

    pub fn create_case_attestation(
        ctx: Context<CreateCaseAttestation>,
        case_id: [u8; 16],
        metadata_hash: [u8; 32],
        creator: Pubkey,
    ) -> Result<()> {
        let a = &mut ctx.accounts.attestation;
        a.case_id = case_id;
        a.metadata_hash = metadata_hash;
        a.creator = creator;
        a.operator = ctx.accounts.operator.key();
        a.created_at = Clock::get()?.unix_timestamp;
        a.bump = ctx.bumps.attestation;
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

    #[account(mut)]
    pub operator: Signer<'info>,

    pub system_program: Program<'info, System>,
}

#[account]
#[derive(InitSpace)]
pub struct CaseAttestation {
    pub case_id: [u8; 16],
    pub metadata_hash: [u8; 32],
    pub creator: Pubkey,
    pub operator: Pubkey,
    pub created_at: i64,
    pub bump: u8,
}

#[error_code]
pub enum AttestationError {
    #[msg("Attestation already exists for this case id")]
    AttestationAlreadyExists,
}
