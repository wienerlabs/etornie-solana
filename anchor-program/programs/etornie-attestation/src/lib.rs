use anchor_lang::prelude::*;

declare_id!("CpLYWQn39xw1Qei1fqcDF8NkJGiJsME2dKpAfzkN1T2X");

#[program]
pub mod etornie_attestation {
    use super::*;

    pub fn initialize(_ctx: Context<Initialize>) -> Result<()> {
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Initialize {}
