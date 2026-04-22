import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import {
  Connection,
  Keypair,
  PublicKey,
  SystemProgram,
  Transaction,
  TransactionInstruction,
  sendAndConfirmTransaction,
} from "@solana/web3.js";
import {
  AccountState,
  AuthorityType,
  ExtensionType,
  TOKEN_2022_PROGRAM_ID,
  createAssociatedTokenAccountIdempotentInstruction,
  createInitializeDefaultAccountStateInstruction,
  createInitializeMetadataPointerInstruction,
  createInitializeMint2Instruction,
  createInitializePermanentDelegateInstruction,
  createSetAuthorityInstruction,
  createTransferCheckedInstruction,
  getAccount,
  getAssociatedTokenAddressSync,
  getMintLen,
} from "@solana/spl-token";
import {
  createInitializeInstruction as createInitializeTokenMetadataInstruction,
  pack,
} from "@solana/spl-token-metadata";
import type { TokenMetadata } from "@solana/spl-token-metadata";
import { readFileSync } from "fs";
import { resolve } from "path";
import * as crypto from "crypto";
import { assert } from "chai";

import type { EtornieIpToken } from "../target/types/etornie_ip_token";

const PROJECT_ROOT = process.cwd();
const PROGRAM_ID = new PublicKey(
  "6WrZ6NmuQtfpufrLbk5prQCKuF4isX1JwbrvxGFxT2gF",
);
const DEVNET_URL = "https://api.devnet.solana.com";

const idl = JSON.parse(
  readFileSync(
    resolve(PROJECT_ROOT, "target/idl/etornie_ip_token.json"),
    "utf-8",
  ),
);

const explorerTx = (sig: string) =>
  `https://explorer.solana.com/tx/${sig}?cluster=devnet`;
const explorerAddr = (addr: string) =>
  `https://explorer.solana.com/address/${addr}?cluster=devnet`;

describe("etornie_ip_token (devnet smoke)", function () {
  this.timeout(120_000);

  const operatorSecret = Uint8Array.from(
    JSON.parse(
      readFileSync(
        resolve(PROJECT_ROOT, "services/api/keys/operator.json"),
        "utf-8",
      ),
    ),
  );
  const operator = Keypair.fromSecretKey(operatorSecret);

  const connection = new Connection(DEVNET_URL, "confirmed");
  const wallet = new anchor.Wallet(operator);
  const provider = new anchor.AnchorProvider(connection, wallet, {
    commitment: "confirmed",
  });
  anchor.setProvider(provider);

  const program = new Program<EtornieIpToken>(idl as any, provider);

  const [nftAuthority] = PublicKey.findProgramAddressSync(
    [Buffer.from("case_nft_authority")],
    PROGRAM_ID,
  );

  const deriveRecordPda = (caseId: Buffer): PublicKey =>
    PublicKey.findProgramAddressSync(
      [Buffer.from("case_nft"), caseId],
      PROGRAM_ID,
    )[0];

  const caseId = crypto.randomBytes(16);
  const metadataUriHash = crypto.randomBytes(32);
  const mintKp = Keypair.generate();
  const client = Keypair.generate();
  const attacker = Keypair.generate();

  const metadata: TokenMetadata = {
    mint: mintKp.publicKey,
    name: `Etornie Case #${caseId.toString("hex").slice(0, 8).toUpperCase()}`,
    symbol: "ETRN",
    uri: `https://etornie.local/case-metadata/${caseId.toString("hex")}.json`,
    additionalMetadata: [],
  };

  let clientAta: PublicKey;

  it("creates a soul-bound Token-2022 mint with operator → PDA authority handoff", async () => {
    const extensions = [
      ExtensionType.MetadataPointer,
      ExtensionType.DefaultAccountState,
      ExtensionType.PermanentDelegate,
    ];
    const mintLen = getMintLen(extensions);
    const metadataLen = pack(metadata).length + 4;
    const rent = await connection.getMinimumBalanceForRentExemption(
      mintLen + metadataLen,
    );

    const ixs: TransactionInstruction[] = [
      SystemProgram.createAccount({
        fromPubkey: operator.publicKey,
        newAccountPubkey: mintKp.publicKey,
        space: mintLen,
        lamports: rent,
        programId: TOKEN_2022_PROGRAM_ID,
      }),
      createInitializeMetadataPointerInstruction(
        mintKp.publicKey,
        operator.publicKey,
        mintKp.publicKey,
        TOKEN_2022_PROGRAM_ID,
      ),
      createInitializeDefaultAccountStateInstruction(
        mintKp.publicKey,
        AccountState.Frozen,
        TOKEN_2022_PROGRAM_ID,
      ),
      createInitializePermanentDelegateInstruction(
        mintKp.publicKey,
        nftAuthority,
        TOKEN_2022_PROGRAM_ID,
      ),
      createInitializeMint2Instruction(
        mintKp.publicKey,
        0,
        operator.publicKey,
        operator.publicKey,
        TOKEN_2022_PROGRAM_ID,
      ),
      createInitializeTokenMetadataInstruction({
        programId: TOKEN_2022_PROGRAM_ID,
        mint: mintKp.publicKey,
        metadata: mintKp.publicKey,
        mintAuthority: operator.publicKey,
        name: metadata.name,
        symbol: metadata.symbol,
        uri: metadata.uri,
        updateAuthority: operator.publicKey,
      }),
      createSetAuthorityInstruction(
        mintKp.publicKey,
        operator.publicKey,
        AuthorityType.MintTokens,
        nftAuthority,
        [],
        TOKEN_2022_PROGRAM_ID,
      ),
      createSetAuthorityInstruction(
        mintKp.publicKey,
        operator.publicKey,
        AuthorityType.FreezeAccount,
        nftAuthority,
        [],
        TOKEN_2022_PROGRAM_ID,
      ),
    ];

    const tx = new Transaction().add(...ixs);
    const sig = await sendAndConfirmTransaction(connection, tx, [
      operator,
      mintKp,
    ]);

    console.log("    mint:      " + mintKp.publicKey.toBase58());
    console.log("    setup tx:  " + explorerTx(sig));
    console.log("    mint view: " + explorerAddr(mintKp.publicKey.toBase58()));
  });

  it("mints a frozen case NFT via mint_case_nft CPI", async () => {
    clientAta = getAssociatedTokenAddressSync(
      mintKp.publicKey,
      client.publicKey,
      false,
      TOKEN_2022_PROGRAM_ID,
    );

    const ataIx = createAssociatedTokenAccountIdempotentInstruction(
      operator.publicKey,
      clientAta,
      client.publicKey,
      mintKp.publicKey,
      TOKEN_2022_PROGRAM_ID,
    );

    const recordPda = deriveRecordPda(caseId);

    const mintTxSig = await program.methods
      .mintCaseNft([...caseId], [...metadataUriHash])
      .accounts({
        caseNftRecord: recordPda,
        nftAuthority,
        mint: mintKp.publicKey,
        clientTokenAccount: clientAta,
        client: client.publicKey,
        operator: operator.publicKey,
        tokenProgram: TOKEN_2022_PROGRAM_ID,
      } as any)
      .preInstructions([ataIx])
      .signers([client])
      .rpc();

    console.log("    mint tx:     " + explorerTx(mintTxSig));
    console.log("    record pda:  " + recordPda.toBase58());
    console.log("    client ata:  " + clientAta.toBase58());

    const ataState = await getAccount(
      connection,
      clientAta,
      "confirmed",
      TOKEN_2022_PROGRAM_ID,
    );

    assert.equal(ataState.amount.toString(), "1", "balance = 1");
    assert.isTrue(ataState.isFrozen, "client ATA must be frozen");

    const record = await program.account.caseNftRecord.fetch(recordPda);
    assert.equal(
      Buffer.from(record.caseId).toString("hex"),
      caseId.toString("hex"),
      "case_id round-trip",
    );
    assert.equal(
      record.mint.toBase58(),
      mintKp.publicKey.toBase58(),
      "mint recorded",
    );
    assert.equal(
      record.clientWallet.toBase58(),
      client.publicKey.toBase58(),
      "client recorded",
    );
    assert.equal(record.burnedAt.toNumber(), 0, "not burned");
  });

  it("rejects transfer attempt with AccountFrozen error", async () => {
    const attackerAta = getAssociatedTokenAddressSync(
      mintKp.publicKey,
      attacker.publicKey,
      false,
      TOKEN_2022_PROGRAM_ID,
    );

    const ataIx = createAssociatedTokenAccountIdempotentInstruction(
      operator.publicKey,
      attackerAta,
      attacker.publicKey,
      mintKp.publicKey,
      TOKEN_2022_PROGRAM_ID,
    );

    const transferIx = createTransferCheckedInstruction(
      clientAta,
      mintKp.publicKey,
      attackerAta,
      client.publicKey,
      1,
      0,
      [],
      TOKEN_2022_PROGRAM_ID,
    );

    const tx = new Transaction().add(ataIx, transferIx);

    let err: unknown = null;
    try {
      await sendAndConfirmTransaction(connection, tx, [operator, client]);
    } catch (e) {
      err = e;
    }

    assert.isNotNull(err, "transfer of frozen token must fail");
    const msg = String(err);
    const isFrozen =
      msg.includes("0x11") ||
      msg.toLowerCase().includes("frozen") ||
      msg.toLowerCase().includes("account is frozen");
    assert.isTrue(
      isFrozen,
      `expected AccountFrozen error, got: ${msg.slice(0, 200)}`,
    );
    console.log("    transfer blocked ✓ (soul-bound enforced)");
  });

  it("burns the NFT via burn_case_nft (no client signature, permanent delegate)", async () => {
    const recordPda = deriveRecordPda(caseId);

    const burnTxSig = await program.methods
      .burnCaseNft([...caseId])
      .accounts({
        caseNftRecord: recordPda,
        nftAuthority,
        mint: mintKp.publicKey,
        clientTokenAccount: clientAta,
        operator: operator.publicKey,
        tokenProgram: TOKEN_2022_PROGRAM_ID,
      } as any)
      .rpc();

    console.log("    burn tx:     " + explorerTx(burnTxSig));

    const ataAfter = await getAccount(
      connection,
      clientAta,
      "confirmed",
      TOKEN_2022_PROGRAM_ID,
    );
    assert.equal(ataAfter.amount.toString(), "0", "balance = 0 after burn");

    const record = await program.account.caseNftRecord.fetch(recordPda);
    assert.isAbove(record.burnedAt.toNumber(), 0, "burned_at recorded");
    console.log("    burned ✓ (client signature not required)");
  });
});
