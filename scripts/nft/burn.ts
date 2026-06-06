/**
 * Backend-invoked subprocess that burns a Case NFT via the program's
 * burn_case_nft instruction.
 *
 * Operator signs alone. Program PDA is the freeze authority (thaw) and
 * permanent delegate (burn), so no client signature is required.
 *
 * Invocation:
 *   ts-node scripts/nft/burn.ts '{"case_id_hex":"...","mint":"<b58>","client_wallet":"<b58>"}'
 *
 * Output (stdout, single line JSON):
 *   {"burn_tx":"<signature>"}
 *
 * Errors are written to stderr; process exits non-zero.
 */
import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import {
  Connection,
  Keypair,
  PublicKey,
} from "@solana/web3.js";
import {
  TOKEN_2022_PROGRAM_ID,
  getAssociatedTokenAddressSync,
} from "@solana/spl-token";
import { readFileSync } from "fs";
import { resolve } from "path";

import type { EtornieIpToken } from "../../idl/etornie_ip_token";

interface Input {
  case_id_hex: string;
  mint: string;
  client_wallet: string;
  cluster_url?: string;
  operator_key_path?: string;
  program_id?: string;
}

interface Output {
  burn_tx: string;
}

function parseInput(): Input {
  const raw = process.argv[2];
  if (!raw) throw new Error("missing JSON arg");
  const parsed = JSON.parse(raw);
  for (const k of ["case_id_hex", "mint", "client_wallet"]) {
    if (typeof parsed[k] !== "string") {
      throw new Error(`missing or non-string field: ${k}`);
    }
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

  const caseId = Buffer.from(input.case_id_hex, "hex");
  if (caseId.length !== 16) {
    throw new Error(`case_id must be 16 bytes, got ${caseId.length}`);
  }
  const mint = new PublicKey(input.mint);
  const clientWallet = new PublicKey(input.client_wallet);

  const programId = new PublicKey(programIdStr);
  const operator = loadOperator(operatorKeyPath);
  const connection = new Connection(clusterUrl, "confirmed");
  const wallet = new anchor.Wallet(operator);
  const provider = new anchor.AnchorProvider(connection, wallet, {
    commitment: "confirmed",
  });
  anchor.setProvider(provider);

  const idlPath = resolve(
    process.cwd(),
    "idl/etornie_ip_token.json",
  );
  const idl = JSON.parse(readFileSync(idlPath, "utf-8"));
  const program = new Program<EtornieIpToken>(idl as any, provider);

  const [nftAuthority] = PublicKey.findProgramAddressSync(
    [Buffer.from("case_nft_authority")],
    programId,
  );
  const [recordPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("case_nft"), caseId],
    programId,
  );
  const clientAta = getAssociatedTokenAddressSync(
    mint,
    clientWallet,
    false,
    TOKEN_2022_PROGRAM_ID,
  );

  const burnTx = await program.methods
    .burnCaseNft([...caseId])
    .accounts({
      caseNftRecord: recordPda,
      nftAuthority,
      mint,
      clientTokenAccount: clientAta,
      operator: operator.publicKey,
      tokenProgram: TOKEN_2022_PROGRAM_ID,
    } as any)
    .rpc();

  const out: Output = { burn_tx: burnTx };
  process.stdout.write(JSON.stringify(out) + "\n");
}

main().catch((err) => {
  process.stderr.write(
    `nft_burn_error: ${err instanceof Error ? err.message : String(err)}\n`,
  );
  process.exit(1);
});
