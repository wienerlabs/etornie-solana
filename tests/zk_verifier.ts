/**
 * End-to-end integration test for programs/etornie-zk-verifier on devnet.
 *
 * The program splits the VerifyProof accounts into:
 *   - fee_payer : covers tx fee and PDA rent   (backend wallet here)
 *   - user      : logical owner of the proof   (throwaway keypair per case)
 *
 * The user keypair never needs any SOL — this test asserts the sponsored
 * flow works end-to-end and covers:
 *   1. A valid hello_world Groth16 proof  → ProofRecord PDA is created
 *   2. The same proof submitted twice      → ReplayedProof
 *   3. A byte-flipped proof (new user)     → InvalidProof / pairing fail
 *   4. A journal digest that does not match → MismatchedDigest
 *   5. A public input above BN254_P         → MalformedPublicInput
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
  PublicKey,
  SystemProgram,
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

const KEYPAIR_PATH =
  process.env.SOLANA_KEYPAIR_PATH ??
  path.join(process.env.HOME ?? '', '.config/solana/id.json');

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

function derivePda(user: PublicKey, journalDigest: Uint8Array): [PublicKey, number] {
  return PublicKey.findProgramAddressSync(
    [Buffer.from('proof'), user.toBuffer(), Buffer.from(journalDigest)],
    PROGRAM_ID
  );
}

describe('etornie-zk-verifier on devnet (sponsored flow)', function () {
  this.timeout(120_000);

  let connection: Connection;
  let funder: Keypair;
  let provider: anchor.AnchorProvider;
  let program: Program<anchor.Idl>;

  let validUser: Keypair;
  let tamperUser: Keypair;
  let mismatchUser: Keypair;
  let overflowUser: Keypair;

  let validProof: OnChainProof;

  async function callVerifyProof(params: {
    user: Keypair;
    proofA: Uint8Array;
    proofB: Uint8Array;
    proofC: Uint8Array;
    publicInputs: Uint8Array[];
    journalDigest: Uint8Array;
  }): Promise<{ signature: string; pda: PublicKey }> {
    const { user, proofA, proofB, proofC, publicInputs, journalDigest } = params;
    const [pda] = derivePda(user.publicKey, journalDigest);

    const computeIx = ComputeBudgetProgram.setComputeUnitLimit({ units: 180_000 });

    const signature = await program.methods
      .verifyProof(
        Array.from(proofA),
        Array.from(proofB),
        Array.from(proofC),
        publicInputs.map((b) => Array.from(b)),
        Array.from(journalDigest)
      )
      .accounts({
        feePayer: funder.publicKey,
        user: user.publicKey,
        proofRecord: pda,
        systemProgram: SystemProgram.programId,
      })
      .preInstructions([computeIx])
      .signers([user])
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

    validUser = Keypair.generate();
    tamperUser = Keypair.generate();
    mismatchUser = Keypair.generate();
    overflowUser = Keypair.generate();

    console.log(`    [setup] feePayer = ${funder.publicKey.toBase58()}`);
    console.log(`    [setup] validUser    = ${validUser.publicKey.toBase58()}`);
    console.log(`    [setup] tamperUser   = ${tamperUser.publicKey.toBase58()}`);
    console.log(`    [setup] mismatchUser = ${mismatchUser.publicKey.toBase58()}`);
    console.log(`    [setup] overflowUser = ${overflowUser.publicKey.toBase58()}`);

    validProof = loadValidProof();
  });

  it('accepts a valid hello_world proof and writes the ProofRecord PDA', async function () {
    const { signature, pda } = await callVerifyProof({
      user: validUser,
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
    expect(record.operator.toBase58()).to.equal(validUser.publicKey.toBase58());
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
        user: validUser,
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
        user: tamperUser,
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
    expect(msg).to.match(/InvalidProof|VerifierInternal|pairing/i);
  });

  it('rejects a journal digest that does not match sha256(public_inputs)', async function () {
    const bogusDigest = new Uint8Array(32);
    bogusDigest[0] = 0xff;

    let caughtErr: any;
    try {
      await callVerifyProof({
        user: mismatchUser,
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
    oversize.fill(0xff);
    const digest = computeJournalDigest([oversize]);

    let caughtErr: any;
    try {
      await callVerifyProof({
        user: overflowUser,
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
    expect(BN254_P > 0n).to.equal(true);
  });
});
