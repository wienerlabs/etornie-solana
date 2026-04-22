/**
 * Backend-invoked subprocess that creates a soul-bound Case NFT mint
 * on devnet.
 *
 * Builds a single Token-2022 mint with:
 *   - MetadataPointer (→ self)
 *   - TokenMetadata (on-chain name/symbol/uri)
 *   - DefaultAccountState = Frozen (soul-bound enforcement)
 *   - PermanentDelegate = program PDA (allows program-only burn)
 *
 * Then transfers MintTokens + FreezeAccount authority to the program PDA
 * so only `mint_case_nft` / `burn_case_nft` instructions can mutate supply
 * or account state afterwards.
 *
 * Invocation:
 *   ts-node scripts/nft/setup_mint.ts '{"name":"...","symbol":"ETRN","uri":"..."}'
 *
 * Output (stdout, single line JSON):
 *   {"mint":"<base58>","setup_tx":"<signature>"}
 *
 * Errors are written to stderr; process exits non-zero.
 */
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
  createInitializeDefaultAccountStateInstruction,
  createInitializeMetadataPointerInstruction,
  createInitializeMint2Instruction,
  createInitializePermanentDelegateInstruction,
  createSetAuthorityInstruction,
  getMintLen,
} from "@solana/spl-token";
import {
  createInitializeInstruction as createInitializeTokenMetadataInstruction,
  pack,
} from "@solana/spl-token-metadata";
import type { TokenMetadata } from "@solana/spl-token-metadata";
import { readFileSync } from "fs";
import { resolve } from "path";

interface Input {
  name: string;
  symbol: string;
  uri: string;
  cluster_url?: string;
  operator_key_path?: string;
  program_id?: string;
}

interface Output {
  mint: string;
  setup_tx: string;
}

function parseInput(): Input {
  const raw = process.argv[2];
  if (!raw) {
    throw new Error("missing JSON arg");
  }
  const parsed = JSON.parse(raw);
  if (typeof parsed.name !== "string" || typeof parsed.symbol !== "string" || typeof parsed.uri !== "string") {
    throw new Error("input must contain name, symbol, uri as strings");
  }
  return parsed;
}

function loadOperator(path: string): Keypair {
  const secret = Uint8Array.from(JSON.parse(readFileSync(path, "utf-8")));
  return Keypair.fromSecretKey(secret);
}

async function main(): Promise<void> {
  const input = parseInput();
  const clusterUrl = input.cluster_url ?? "https://api.devnet.solana.com";
  const operatorKeyPath = resolve(
    input.operator_key_path ??
      resolve(process.cwd(), "services/api/keys/operator.json"),
  );
  const programIdStr =
    input.program_id ?? "6WrZ6NmuQtfpufrLbk5prQCKuF4isX1JwbrvxGFxT2gF";

  const programId = new PublicKey(programIdStr);
  const operator = loadOperator(operatorKeyPath);
  const connection = new Connection(clusterUrl, "confirmed");

  const [nftAuthority] = PublicKey.findProgramAddressSync(
    [Buffer.from("case_nft_authority")],
    programId,
  );

  const mintKp = Keypair.generate();

  const metadata: TokenMetadata = {
    mint: mintKp.publicKey,
    name: input.name,
    symbol: input.symbol,
    uri: input.uri,
    additionalMetadata: [],
  };

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

  const out: Output = {
    mint: mintKp.publicKey.toBase58(),
    setup_tx: sig,
  };
  process.stdout.write(JSON.stringify(out) + "\n");
}

main().catch((err) => {
  process.stderr.write(
    `nft_setup_error: ${err instanceof Error ? err.message : String(err)}\n`,
  );
  process.exit(1);
});
