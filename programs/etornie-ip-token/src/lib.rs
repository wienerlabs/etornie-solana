use anchor_lang::prelude::*;
use anchor_spl::token_2022::{self, Burn, FreezeAccount, MintTo, ThawAccount, Token2022};
use anchor_spl::token_interface::{Mint, TokenAccount};

declare_id!("6WrZ6NmuQtfpufrLbk5prQCKuF4isX1JwbrvxGFxT2gF");

pub const NFT_AUTHORITY_SEED: &[u8] = b"case_nft_authority";
pub const CASE_NFT_RECORD_SEED: &[u8] = b"case_nft";

#[program]
pub mod etornie_ip_token {
    use super::*;

    /// Mint a soul-bound case NFT into the client's frozen ATA.
    ///
    /// The mint must already be created client-side with:
    /// - decimals = 0
    /// - mint_authority = nft_authority PDA
    /// - freeze_authority = nft_authority PDA
    /// - DefaultAccountState = Frozen extension
    /// - MetadataPointer + TokenMetadata extensions
    ///
    /// The client's ATA starts frozen (DefaultAccountState), so the NFT
    /// cannot be transferred, delegated, or burned by the holder. Only
    /// `burn_case_nft` can thaw → burn via program PDA signing.
    pub fn mint_case_nft(
        ctx: Context<MintCaseNft>,
        case_id: [u8; 16],
        metadata_uri_hash: [u8; 32],
    ) -> Result<()> {
        let authority_bump = ctx.bumps.nft_authority;
        let authority_seeds: &[&[u8]] = &[NFT_AUTHORITY_SEED, &[authority_bump]];
        let signer_seeds = &[authority_seeds];

        // DefaultAccountState=Frozen makes the fresh ATA frozen on creation,
        // and mint_to rejects frozen destinations. Thaw → mint → freeze
        // keeps the token soul-bound while allowing the 1-unit issuance.
        let thaw_accounts = ThawAccount {
            account: ctx.accounts.client_token_account.to_account_info(),
            mint: ctx.accounts.mint.to_account_info(),
            authority: ctx.accounts.nft_authority.to_account_info(),
        };
        token_2022::thaw_account(CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            thaw_accounts,
            signer_seeds,
        ))?;

        let mint_accounts = MintTo {
            mint: ctx.accounts.mint.to_account_info(),
            to: ctx.accounts.client_token_account.to_account_info(),
            authority: ctx.accounts.nft_authority.to_account_info(),
        };
        token_2022::mint_to(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                mint_accounts,
                signer_seeds,
            ),
            1,
        )?;

        let freeze_accounts = FreezeAccount {
            account: ctx.accounts.client_token_account.to_account_info(),
            mint: ctx.accounts.mint.to_account_info(),
            authority: ctx.accounts.nft_authority.to_account_info(),
        };
        token_2022::freeze_account(CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            freeze_accounts,
            signer_seeds,
        ))?;

        let record = &mut ctx.accounts.case_nft_record;
        record.case_id = case_id;
        record.mint = ctx.accounts.mint.key();
        record.client_wallet = ctx.accounts.client.key();
        record.operator = ctx.accounts.operator.key();
        record.metadata_uri_hash = metadata_uri_hash;
        record.minted_at = Clock::get()?.unix_timestamp;
        record.burned_at = 0;
        record.bump = ctx.bumps.case_nft_record;

        emit!(CaseNftMinted {
            case_id,
            mint: record.mint,
            client_wallet: record.client_wallet,
            operator: record.operator,
            metadata_uri_hash,
            timestamp: record.minted_at,
        });

        Ok(())
    }

    /// Thaw the client's frozen ATA, burn the 1-unit supply, mark record burned.
    ///
    /// Only the operator needs to sign — the program PDA acts as freeze
    /// authority (thaw) and mint authority (burn). This is intended to be
    /// called when the case reaches a terminal closed state; the
    /// backend must enforce that precondition off-chain before invoking.
    pub fn burn_case_nft(ctx: Context<BurnCaseNft>, _case_id: [u8; 16]) -> Result<()> {
        require!(
            ctx.accounts.case_nft_record.burned_at == 0,
            CaseNftError::AlreadyBurned
        );

        let authority_bump = ctx.bumps.nft_authority;
        let authority_seeds: &[&[u8]] = &[NFT_AUTHORITY_SEED, &[authority_bump]];
        let signer_seeds = &[authority_seeds];

        let thaw_accounts = ThawAccount {
            account: ctx.accounts.client_token_account.to_account_info(),
            mint: ctx.accounts.mint.to_account_info(),
            authority: ctx.accounts.nft_authority.to_account_info(),
        };
        let thaw_ctx = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            thaw_accounts,
            signer_seeds,
        );
        token_2022::thaw_account(thaw_ctx)?;

        let burn_accounts = Burn {
            mint: ctx.accounts.mint.to_account_info(),
            from: ctx.accounts.client_token_account.to_account_info(),
            authority: ctx.accounts.nft_authority.to_account_info(),
        };
        let burn_ctx = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            burn_accounts,
            signer_seeds,
        );
        token_2022::burn(burn_ctx, 1)?;

        let record = &mut ctx.accounts.case_nft_record;
        record.burned_at = Clock::get()?.unix_timestamp;

        emit!(CaseNftBurned {
            case_id: record.case_id,
            mint: ctx.accounts.mint.key(),
            operator: ctx.accounts.operator.key(),
            timestamp: record.burned_at,
        });

        Ok(())
    }
}

#[derive(Accounts)]
#[instruction(case_id: [u8; 16])]
pub struct MintCaseNft<'info> {
    #[account(
        init,
        payer = operator,
        space = 8 + CaseNftRecord::INIT_SPACE,
        seeds = [CASE_NFT_RECORD_SEED, case_id.as_ref()],
        bump,
    )]
    pub case_nft_record: Account<'info, CaseNftRecord>,

    /// CHECK: Program-owned PDA acting as mint + freeze authority.
    /// Derived from [NFT_AUTHORITY_SEED]; signed via invoke_signed.
    #[account(
        seeds = [NFT_AUTHORITY_SEED],
        bump,
    )]
    pub nft_authority: UncheckedAccount<'info>,

    #[account(
        mut,
        mint::token_program = token_program,
        mint::authority = nft_authority,
        mint::freeze_authority = nft_authority,
        mint::decimals = 0,
    )]
    pub mint: InterfaceAccount<'info, Mint>,

    #[account(
        mut,
        token::mint = mint,
        token::authority = client,
        token::token_program = token_program,
    )]
    pub client_token_account: InterfaceAccount<'info, TokenAccount>,

    pub client: Signer<'info>,

    #[account(mut)]
    pub operator: Signer<'info>,

    pub token_program: Program<'info, Token2022>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(case_id: [u8; 16])]
pub struct BurnCaseNft<'info> {
    #[account(
        mut,
        seeds = [CASE_NFT_RECORD_SEED, case_id.as_ref()],
        bump = case_nft_record.bump,
        has_one = mint,
    )]
    pub case_nft_record: Account<'info, CaseNftRecord>,

    /// CHECK: Program-owned PDA; signs thaw + burn CPI.
    #[account(
        seeds = [NFT_AUTHORITY_SEED],
        bump,
    )]
    pub nft_authority: UncheckedAccount<'info>,

    #[account(
        mut,
        mint::token_program = token_program,
        mint::authority = nft_authority,
        mint::freeze_authority = nft_authority,
    )]
    pub mint: InterfaceAccount<'info, Mint>,

    #[account(
        mut,
        token::mint = mint,
        token::token_program = token_program,
    )]
    pub client_token_account: InterfaceAccount<'info, TokenAccount>,

    #[account(mut)]
    pub operator: Signer<'info>,

    pub token_program: Program<'info, Token2022>,
}

#[account]
#[derive(InitSpace)]
pub struct CaseNftRecord {
    pub case_id: [u8; 16],
    pub mint: Pubkey,
    pub client_wallet: Pubkey,
    pub operator: Pubkey,
    pub metadata_uri_hash: [u8; 32],
    pub minted_at: i64,
    pub burned_at: i64,
    pub bump: u8,
}

#[event]
pub struct CaseNftMinted {
    pub case_id: [u8; 16],
    pub mint: Pubkey,
    pub client_wallet: Pubkey,
    pub operator: Pubkey,
    pub metadata_uri_hash: [u8; 32],
    pub timestamp: i64,
}

#[event]
pub struct CaseNftBurned {
    pub case_id: [u8; 16],
    pub mint: Pubkey,
    pub operator: Pubkey,
    pub timestamp: i64,
}

#[error_code]
pub enum CaseNftError {
    #[msg("Case NFT has already been burned")]
    AlreadyBurned,
}
