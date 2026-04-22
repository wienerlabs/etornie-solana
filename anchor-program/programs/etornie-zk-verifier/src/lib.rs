use anchor_lang::prelude::*;

declare_id!("GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5");

#[program]
pub mod etornie_zk_verifier {
    use super::*;

    pub fn initialize(_ctx: Context<Initialize>) -> Result<()> {
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Initialize {}
