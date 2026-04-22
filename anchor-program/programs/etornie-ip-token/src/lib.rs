use anchor_lang::prelude::*;

declare_id!("6WrZ6NmuQtfpufrLbk5prQCKuF4isX1JwbrvxGFxT2gF");

#[program]
pub mod etornie_ip_token {
    use super::*;

    pub fn initialize(_ctx: Context<Initialize>) -> Result<()> {
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Initialize {}
