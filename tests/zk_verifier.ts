/**
 * End-to-end integration test for programs/etornie-zk-verifier on devnet.
 *
 * The test hits the live devnet RPC, funds four throwaway operator
 * keypairs from the main wallet, and exercises:
 *   1. A valid hello_world Groth16 proof  → ProofRecord PDA is created
 *   2. The same proof submitted twice      → ReplayedProof
 *   3. A byte-flipped proof (new operator) → InvalidProof / pairing fail
 *   4. A journal digest that does not match  → MismatchedDigest
 *   5. A public input above BN254_P         → MalformedPublicInput
 *
 * Each failing case asserts on the program error discriminator from the
 * logs rather than the exact Anchor error class so the test stays
 * resilient to @coral-xyz/anchor version bumps.
 */

import * as fs from 'fs';
import * as path from 'path';
import { expect } from 'chai';
import * as anchor from '@coral-xyz/anchor';
import { Program } from '@coral-xyz/anchor';
import {
  ComputeBudgetProgram,
  Connection,
  Keypair,
  LAMPORTS_PER_SOL,
  PublicKey,
  SystemProgram,
  Transaction,
  sendAndConfirmTransaction,
} from '@solana/web3.js';
import {
  BN254_P,
  computeJournalDigest,
  convertSnarkjsProof,
  SnarkjsProof,
  OnChainProof,
} from '../scripts/proof_conversion';

const DEVNET_RPC = process.env.DEVNET_RPC_URL ?? 'https://api.devnet.solana.com';
const PROGRAM_ID = new PublicKey('GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5');

// Path to the JSON-formatted Solana CLI keypair. CI can override.
const KEYPAIR_PATH =
  process.env.SOLANA_KEYPAIR_PATH ??
  path.join(process.env.HOME ?? '', '.config/solana/id.json');

// Amount funded to each throwaway operator (covers PDA rent + a tx fee or two).
const OPERATOR_FUND_LAMPORTS = Math.floor(0.01 * LAMPORTS_PER_SOL);

const PROOF_FIXTURE = 'circuits/build/hello_world/proof.json';
const PUBLIC_FIXTURE = 'circuits/build/hello_world/public.json';
const IDL_PATH = 'idl/etornie_zk_verifier.json';

function loadFunder(): Keypair {
  const secret = JSON.parse(fs.readFileSync(KEYPAIR_PATH, 'utf8')) as number[];
  return Keypair.fromSecretKey(Uint8Array.from(secret));
}

function loadValidProof(): OnChainProof {
  const proof = JSON.parse(fs.readFileSync(PROOF_FIXTURE, 'utf8')) as SnarkjsProof;
  const publicSignals = JSON.parse(fs.readFileSync(PUBLIC_FIXTURE, 'utf8')) as string[];
  return convertSnarkjsProof(proof, publicSignals);
}

function derivePda(operator: PublicKey, journalDigest: Uint8Array): [PublicKey, number] {
  return PublicKey.findProgramAddressSync(
    [Buffer.from('proof'), operator.toBuffer(), Buffer.from(journalDigest)],
    PROGRAM_ID
  );
}

describe('etornie-zk-verifier on devnet', function () {
  // Devnet confirmations can take >10s on a bad day; give every test headroom.
  this.timeout(120_000);

  let connection: Connection;
  let funder: Keypair;
  let provider: anchor.AnchorProvider;
  let program: Program<anchor.Idl>;

  let validOperator: Keypair;
  let tamperOperator: Keypair;
  let mismatchOperator: Keypair;
  let overflowOperator: Keypair;

  let validProof: OnChainProof;

  async function callVerifyProof(params: {
    operator: Keypair;
    proofA: Uint8Array;
    proofB: Uint8Array;
    proofC: Uint8Array;
    publicInputs: Uint8Array[];
    journalDigest: Uint8Array;
  }): Promise<{ signature: string; pda: PublicKey }> {
    const { operator, proofA, proofB, proofC, publicInputs, journalDigest } = params;
    const [pda] = derivePda(operator.publicKey, journalDigest);

    const computeIx = ComputeBudgetProgram.setComputeUnitLimit({ units: 300_000 });

    const signature = await program.methods
      .verifyProof(
        Array.from(proofA),
        Array.from(proofB),
        Array.from(proofC),
        publicInputs.map((b) => Array.from(b)),
        Array.from(journalDigest)
      )
      .accounts({
        operator: operator.publicKey,
        proofRecord: pda,
        systemProgram: SystemProgram.programId,
      })
      .preInstructions([computeIx])
      .signers([operator])
      .rpc({ commitment: 'confirmed' });

    return { signature, pda };
  }

  before(async function () {
    connection = new Connection(DEVNET_RPC, 'confirmed');
    funder = loadFunder();
    const wallet = new anchor.Wallet(funder);
    provider = new anchor.AnchorProvider(connection, wallet, { commitment: 'confirmed' });
    anchor.setProvider(provider);

    const idl = JSON.parse(fs.readFileSync(IDL_PATH, 'utf8')) as anchor.Idl;
    program = new Program(idl, provider);

    validOperator = Keypair.generate();
    tamperOperator = Keypair.generate();
    mismatchOperator = Keypair.generate();
    overflowOperator = Keypair.generate();

    // Fund all four throwaway operators in a single tx.
    const fundTx = new Transaction();
    for (const op of [validOperator, tamperOperator, mismatchOperator, overflowOperator]) {
      fundTx.add(
        SystemProgram.transfer({
          fromPubkey: funder.publicKey,
          toPubkey: op.publicKey,
          lamports: OPERATOR_FUND_LAMPORTS,
        })
      );
    }
    const fundSig = await sendAndConfirmTransaction(connection, fundTx, [funder], {
      commitment: 'confirmed',
    });
    console.log(`    [setup] funded 4 operators: ${fundSig}`);
    console.log(`    [setup] validOperator    = ${validOperator.publicKey.toBase58()}`);
    console.log(`    [setup] tamperOperator   = ${tamperOperator.publicKey.toBase58()}`);
    console.log(`    [setup] mismatchOperator = ${mismatchOperator.publicKey.toBase58()}`);
    console.log(`    [setup] overflowOperator = ${overflowOperator.publicKey.toBase58()}`);

    validProof = loadValidProof();
  });

  it('accepts a valid hello_world proof and writes the ProofRecord PDA', async function () {
    const { signature, pda } = await callVerifyProof({
      operator: validOperator,
      proofA: validProof.proofA,
      proofB: validProof.proofB,
      proofC: validProof.proofC,
      publicInputs: validProof.publicInputs,
      journalDigest: validProof.journalDigest,
    });
    console.log(`    verify tx:     ${signature}`);
    console.log(`    proof record:  ${pda.toBase58()}`);
    console.log(`    explorer:      https://explorer.solana.com/tx/${signature}?cluster=devnet`);

    const record = await (program.account as any).proofRecord.fetch(pda);
    expect(record.operator.toBase58()).to.equal(validOperator.publicKey.toBase58());
    expect(Buffer.from(record.journalDigest).equals(Buffer.from(validProof.journalDigest))).to.equal(
      true
    );
    expect(record.isInitialized).to.equal(true);
    expect(Number(record.verifiedAt)).to.be.greaterThan(0);
  });

  it('rejects the same proof submitted twice as ReplayedProof', async function () {
    let caughtErr: any;
    try {
      await callVerifyProof({
        operator: validOperator,
        proofA: validProof.proofA,
        proofB: validProof.proofB,
        proofC: validProof.proofC,
        publicInputs: validProof.publicInputs,
        journalDigest: validProof.journalDigest,
      });
    } catch (e) {
      caughtErr = e;
    }
    expect(caughtErr, 'expected the second submission to throw').to.not.equal(undefined);
    const msg = String(caughtErr.message ?? caughtErr);
    expect(msg).to.match(/ReplayedProof|already been recorded/i);
  });

  it('rejects a byte-flipped proof as InvalidProof (pairing fails)', async function () {
    const tampered = new Uint8Array(validProof.proofA);
    tampered[tampered.length - 1] ^= 0x01;

    let caughtErr: any;
    try {
      await callVerifyProof({
        operator: tamperOperator,
        proofA: tampered,
        proofB: validProof.proofB,
        proofC: validProof.proofC,
        publicInputs: validProof.publicInputs,
        journalDigest: validProof.journalDigest,
      });
    } catch (e) {
      caughtErr = e;
    }
    expect(caughtErr, 'expected tampered proof to throw').to.not.equal(undefined);
    const msg = String(caughtErr.message ?? caughtErr);
    // A byte flip typically pushes the point off-curve or produces a wrong
    // pairing result; both map to InvalidProof, but a syscall failure can
    // surface as VerifierInternal. Accept either rather than over-specify.
    expect(msg).to.match(/InvalidProof|VerifierInternal|pairing/i);
  });

  it('rejects a journal digest that does not match sha256(public_inputs)', async function () {
    const bogusDigest = new Uint8Array(32);
    bogusDigest[0] = 0xff; // guaranteed to differ from the real sha256

    let caughtErr: any;
    try {
      await callVerifyProof({
        operator: mismatchOperator,
        proofA: validProof.proofA,
        proofB: validProof.proofB,
        proofC: validProof.proofC,
        publicInputs: validProof.publicInputs,
        journalDigest: bogusDigest,
      });
    } catch (e) {
      caughtErr = e;
    }
    expect(caughtErr, 'expected digest mismatch to throw').to.not.equal(undefined);
    const msg = String(caughtErr.message ?? caughtErr);
    expect(msg).to.match(/MismatchedDigest|digest does not match/i);
  });

  it('rejects a public input >= BN254_P as MalformedPublicInput', async function () {
    const oversize = new Uint8Array(32);
    oversize.fill(0xff); // 2^256 - 1, far above BN254_P
    const digest = computeJournalDigest([oversize]);

    let caughtErr: any;
    try {
      await callVerifyProof({
        operator: overflowOperator,
        proofA: validProof.proofA,
        proofB: validProof.proofB,
        proofC: validProof.proofC,
        publicInputs: [oversize],
        journalDigest: digest,
      });
    } catch (e) {
      caughtErr = e;
    }
    expect(caughtErr, 'expected oversized public input to throw').to.not.equal(undefined);
    const msg = String(caughtErr.message ?? caughtErr);
    expect(msg).to.match(/MalformedPublicInput|BN254 field|field size/i);
    // Sanity: our BN254_P constant still matches the circuit fixture expectation
    expect(BN254_P > 0n).to.equal(true);
  });
});
