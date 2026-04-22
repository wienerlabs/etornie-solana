import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { Connection, Keypair, PublicKey } from "@solana/web3.js";
import { readFileSync } from "fs";
import { resolve } from "path";
import * as crypto from "crypto";
import { assert } from "chai";

import type { EtornieAttestation } from "../target/types/etornie_attestation";

// Resolve paths from project root (process.cwd()) to work under both
// CJS (__dirname) and ESM (no __dirname) module resolution — ts-mocha
// on Node 25 loads tests via ESM even when tsconfig targets CJS.
const PROJECT_ROOT = process.cwd();
const idl = JSON.parse(
  readFileSync(
    resolve(PROJECT_ROOT, "target/idl/etornie_attestation.json"),
    "utf-8",
  ),
);

describe("etornie_attestation (devnet)", function () {
  this.timeout(60_000);

  const PROGRAM_ID = new PublicKey(
    "CpLYWQn39xw1Qei1fqcDF8NkJGiJsME2dKpAfzkN1T2X",
  );
  const DEVNET_URL = "https://api.devnet.solana.com";

  const operatorKeyFile = resolve(
    PROJECT_ROOT,
    "services/api/keys/operator.json",
  );
  const operatorSecret = Uint8Array.from(
    JSON.parse(readFileSync(operatorKeyFile, "utf-8")),
  );
  const operator = Keypair.fromSecretKey(operatorSecret);

  const connection = new Connection(DEVNET_URL, "confirmed");
  const wallet = new anchor.Wallet(operator);
  const provider = new anchor.AnchorProvider(connection, wallet, {
    commitment: "confirmed",
  });
  anchor.setProvider(provider);

  const program = new Program<EtornieAttestation>(idl as any, provider);

  const derivePda = (caseId: Buffer): PublicKey =>
    PublicKey.findProgramAddressSync(
      [Buffer.from("case"), caseId],
      PROGRAM_ID,
    )[0];

  it("creates a case attestation and persists it on-chain", async () => {
    const caseId = crypto.randomBytes(16);
    const metadataHash = crypto.randomBytes(32);
    const creator = Keypair.generate().publicKey;
    const clientWallet = Keypair.generate().publicKey;
    const pda = derivePda(caseId);

    const txSig = await program.methods
      .createCaseAttestation(
        [...caseId],
        [...metadataHash],
        creator,
        clientWallet,
      )
      .accounts({
        attestation: pda,
        operator: operator.publicKey,
      })
      .rpc();

    console.log(
      "    tx:      https://explorer.solana.com/tx/" +
        txSig +
        "?cluster=devnet",
    );
    console.log("    pda:     " + pda.toBase58());
    console.log("    case_id: " + caseId.toString("hex"));

    const a = await program.account.caseAttestation.fetch(pda);

    assert.equal(
      Buffer.from(a.caseId).toString("hex"),
      caseId.toString("hex"),
      "case_id round-trip",
    );
    assert.equal(
      Buffer.from(a.metadataHash).toString("hex"),
      metadataHash.toString("hex"),
      "metadata_hash round-trip",
    );
    assert.equal(a.creator.toBase58(), creator.toBase58(), "creator");
    assert.equal(
      a.clientWallet.toBase58(),
      clientWallet.toBase58(),
      "client_wallet",
    );
    assert.equal(
      a.operator.toBase58(),
      operator.publicKey.toBase58(),
      "operator",
    );
    assert.isAbove(a.createdAt.toNumber(), 0, "created_at set");
  });

  it("rejects a duplicate attestation for the same case_id", async () => {
    const caseId = crypto.randomBytes(16);
    const metadataHash = crypto.randomBytes(32);
    const creator = Keypair.generate().publicKey;
    const clientWallet = Keypair.generate().publicKey;
    const pda = derivePda(caseId);

    await program.methods
      .createCaseAttestation(
        [...caseId],
        [...metadataHash],
        creator,
        clientWallet,
      )
      .accounts({ attestation: pda, operator: operator.publicKey })
      .rpc();

    let replayErr: unknown = null;
    try {
      await program.methods
        .createCaseAttestation(
          [...caseId],
          [...metadataHash],
          creator,
          clientWallet,
        )
        .accounts({ attestation: pda, operator: operator.publicKey })
        .rpc();
    } catch (e) {
      replayErr = e;
    }

    assert.isNotNull(replayErr, "replay should fail");
  });
});
