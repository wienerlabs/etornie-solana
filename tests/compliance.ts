/**
 * End-to-end integration test for the `verify_compliance_proof`
 * instruction on devnet (Faz 5.6).
 *
 * The program verifies a Groth16 proof that the caller knows a secret `s`
 * with `Poseidon(s, qh_hi, qh_lo) == commitment`, then writes a
 * `ComplianceRecord` PDA seeded on (b"compliance", user, query_hash).
 *
 * Each test generates a fresh proof at runtime via snarkjs + circomlibjs -
 * no fixture files - so the circuit pipeline stays exercised end-to-end.
 *
 * Covers:
 *   1. A valid proof + canonical query_hash halves → PDA created
 *   2. The same (user, query_hash) submitted twice → ReplayedProof
 *   3. qh_hi tampered with a bit above position 128 (still in field, but
 *      inconsistent with the `query_hash` arg) → MalformedQueryHashInput
 *   4. A byte-flipped proofA → InvalidProof (pairing fails)
 *   5. A commitment public input >= BN254_P → MalformedPublicInput
 */

import * as fs from 'fs';
import * as path from 'path';
import * as crypto from 'crypto';
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
  convertSnarkjsProof,
  SnarkjsProof,
  OnChainProof,
} from '../scripts/proof_conversion';

// eslint-disable-next-line @typescript-eslint/no-var-requires
const snarkjs = require('snarkjs');
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { buildPoseidon } = require('circomlibjs');

const DEVNET_RPC = process.env.DEVNET_RPC_URL ?? 'https://api.devnet.solana.com';
const PROGRAM_ID = new PublicKey('GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5');

const KEYPAIR_PATH =
  process.env.SOLANA_KEYPAIR_PATH ??
  path.join(process.env.HOME ?? '', '.config/solana/id.json');

const WASM_PATH = 'circuits/build/compliance/compliance_js/compliance.wasm';
const ZKEY_PATH = 'circuits/build/compliance/compliance_final.zkey';
const IDL_PATH = 'idl/etornie_zk_verifier.json';

const COMPLIANCE_SEED = Buffer.from('compliance');

function loadFunder(): Keypair {
  const secret = JSON.parse(fs.readFileSync(KEYPAIR_PATH, 'utf8')) as number[];
  return Keypair.fromSecretKey(Uint8Array.from(secret));
}

function derivePda(user: PublicKey, queryHash: Uint8Array): [PublicKey, number] {
  return PublicKey.findProgramAddressSync(
    [COMPLIANCE_SEED, user.toBuffer(), Buffer.from(queryHash)],
    PROGRAM_ID
  );
}

function splitQueryHash(queryHash: Uint8Array): { qhHi: bigint; qhLo: bigint } {
  if (queryHash.length !== 32) {
    throw new Error(`query_hash must be 32 bytes, got ${queryHash.length}`);
  }
  let hi = 0n;
  let lo = 0n;
  for (let i = 0; i < 16; i++) hi = (hi << 8n) | BigInt(queryHash[i]);
  for (let i = 16; i < 32; i++) lo = (lo << 8n) | BigInt(queryHash[i]);
  return { qhHi: hi, qhLo: lo };
}

function randomSecret(): bigint {
  const bytes = crypto.randomBytes(31);
  bytes[0] |= 0x01;
  let out = 0n;
  for (const b of bytes) out = (out << 8n) | BigInt(b);
  return out;
}

describe('compliance verifier on devnet (sponsored flow)', function () {
  this.timeout(300_000);

  let connection: Connection;
  let funder: Keypair;
  let provider: anchor.AnchorProvider;
  let program: Program<anchor.Idl>;

  let poseidon: any;
  let F: any;

  let happyUser: Keypair;
  let malformedHashUser: Keypair;
  let tamperedProofUser: Keypair;
  let fieldOverflowUser: Keypair;

  let happyQueryHash: Uint8Array;
  let happyProof: OnChainProof;

  async function generateProof(opts: {
    secret: bigint;
    qhHi: bigint;
    qhLo: bigint;
  }): Promise<{ onchain: OnChainProof; commitment: bigint }> {
    const commitmentF = poseidon([opts.secret, opts.qhHi, opts.qhLo]);
    const commitment = F.toObject(commitmentF) as bigint;

    const input = {
      secret: opts.secret.toString(),
      query_hash_hi: opts.qhHi.toString(),
      query_hash_lo: opts.qhLo.toString(),
      commitment: commitment.toString(),
    };
    const { proof, publicSignals } = await snarkjs.groth16.fullProve(
      input,
      WASM_PATH,
      ZKEY_PATH
    );
    const onchain = convertSnarkjsProof(
      proof as SnarkjsProof,
      publicSignals as string[]
    );
    return { onchain, commitment };
  }

  async function callVerify(params: {
    user: Keypair;
    onchain: OnChainProof;
    queryHash: Uint8Array;
  }): Promise<{ signature: string; pda: PublicKey }> {
    const [pda] = derivePda(params.user.publicKey, params.queryHash);
    const computeIx = ComputeBudgetProgram.setComputeUnitLimit({
      units: 180_000,
    });

    // user is an UncheckedAccount - only funder (operator) signs. The ZK
    // proof itself binds the record to the user's wallet via the
    // off-chain-derived secret, so no second wallet signature is needed.
    const signature = await program.methods
      .verifyComplianceProof(
        Array.from(params.onchain.proofA),
        Array.from(params.onchain.proofB),
        Array.from(params.onchain.proofC),
        params.onchain.publicInputs.map((b) => Array.from(b)),
        Array.from(params.queryHash)
      )
      .accounts({
        feePayer: funder.publicKey,
        user: params.user.publicKey,
        complianceRecord: pda,
        systemProgram: SystemProgram.programId,
      })
      .preInstructions([computeIx])
      .rpc({ commitment: 'confirmed' });

    return { signature, pda };
  }

  before(async function () {
    connection = new Connection(DEVNET_RPC, 'confirmed');
    funder = loadFunder();
    const wallet = new anchor.Wallet(funder);
    provider = new anchor.AnchorProvider(connection, wallet, {
      commitment: 'confirmed',
    });
    anchor.setProvider(provider);

    const idl = JSON.parse(fs.readFileSync(IDL_PATH, 'utf8')) as anchor.Idl;
    program = new Program(idl, provider);

    poseidon = await buildPoseidon();
    F = poseidon.F;

    happyUser = Keypair.generate();
    malformedHashUser = Keypair.generate();
    tamperedProofUser = Keypair.generate();
    fieldOverflowUser = Keypair.generate();

    console.log(`    [setup] feePayer          = ${funder.publicKey.toBase58()}`);
    console.log(`    [setup] happyUser         = ${happyUser.publicKey.toBase58()}`);
    console.log(`    [setup] malformedHashUser = ${malformedHashUser.publicKey.toBase58()}`);
    console.log(`    [setup] tamperedProofUser = ${tamperedProofUser.publicKey.toBase58()}`);
    console.log(`    [setup] fieldOverflowUser = ${fieldOverflowUser.publicKey.toBase58()}`);
  });

  it('accepts a valid compliance proof and writes the PDA', async function () {
    happyQueryHash = crypto.randomBytes(32);
    const { qhHi, qhLo } = splitQueryHash(happyQueryHash);
    const secret = randomSecret();

    const { onchain, commitment } = await generateProof({ secret, qhHi, qhLo });
    happyProof = onchain;

    const { signature, pda } = await callVerify({
      user: happyUser,
      onchain,
      queryHash: happyQueryHash,
    });
    console.log(`    query_hash:      ${Buffer.from(happyQueryHash).toString('hex')}`);
    console.log(`    verify tx:       ${signature}`);
    console.log(`    compliance pda:  ${pda.toBase58()}`);
    console.log(`    explorer:        https://explorer.solana.com/tx/${signature}?cluster=devnet`);

    const record = await (program.account as any).complianceRecord.fetch(pda);
    expect(record.payer.toBase58()).to.equal(happyUser.publicKey.toBase58());
    expect(
      Buffer.from(record.queryHash).equals(Buffer.from(happyQueryHash)),
      'stored query_hash must match the claimed one'
    ).to.equal(true);
    const storedCommitment = BigInt('0x' + Buffer.from(record.commitment).toString('hex'));
    expect(storedCommitment).to.equal(commitment);
    expect(record.isInitialized).to.equal(true);
    expect(Number(record.verifiedAt)).to.be.greaterThan(0);
  });

  it('rejects the same (user, query_hash) submitted twice as ReplayedProof', async function () {
    let caught: any;
    try {
      await callVerify({
        user: happyUser,
        onchain: happyProof,
        queryHash: happyQueryHash,
      });
    } catch (e) {
      caught = e;
    }
    expect(caught, 'expected second submission to throw').to.not.equal(undefined);
    const msg = String(caught.message ?? caught);
    expect(msg).to.match(/ReplayedProof|already been recorded|already in use/i);
  });

  it('rejects mismatched qh_hi vs query_hash arg as MalformedQueryHashInput', async function () {
    const realQueryHash = crypto.randomBytes(32);
    const { qhHi: realQhHi, qhLo: realQhLo } = splitQueryHash(realQueryHash);

    const tamperedQhHi = realQhHi | (1n << 200n);
    const secret = randomSecret();

    const { onchain } = await generateProof({
      secret,
      qhHi: tamperedQhHi,
      qhLo: realQhLo,
    });

    let caught: any;
    try {
      await callVerify({
        user: malformedHashUser,
        onchain,
        queryHash: realQueryHash,
      });
    } catch (e) {
      caught = e;
    }
    expect(caught, 'expected canonical-halves mismatch to throw').to.not.equal(undefined);
    const msg = String(caught.message ?? caught);
    expect(msg).to.match(/MalformedQueryHashInput|canonical/i);
  });

  it('rejects a byte-flipped proofA as InvalidProof (pairing fails)', async function () {
    const queryHash = crypto.randomBytes(32);
    const { qhHi, qhLo } = splitQueryHash(queryHash);
    const secret = randomSecret();

    const { onchain } = await generateProof({ secret, qhHi, qhLo });
    const tamperedA = new Uint8Array(onchain.proofA);
    tamperedA[tamperedA.length - 1] ^= 0x01;

    let caught: any;
    try {
      await callVerify({
        user: tamperedProofUser,
        onchain: { ...onchain, proofA: tamperedA },
        queryHash,
      });
    } catch (e) {
      caught = e;
    }
    expect(caught, 'expected tampered proof to throw').to.not.equal(undefined);
    const msg = String(caught.message ?? caught);
    expect(msg).to.match(/InvalidProof|VerifierInternal|pairing/i);
  });

  it('rejects a commitment public input >= BN254_P as MalformedPublicInput', async function () {
    const queryHash = crypto.randomBytes(32);
    const { qhHi, qhLo } = splitQueryHash(queryHash);
    const secret = randomSecret();

    const { onchain } = await generateProof({ secret, qhHi, qhLo });

    const overflow = new Uint8Array(32).fill(0xff);
    const tamperedInputs = [
      onchain.publicInputs[0],
      onchain.publicInputs[1],
      overflow,
    ];

    let caught: any;
    try {
      await callVerify({
        user: fieldOverflowUser,
        onchain: { ...onchain, publicInputs: tamperedInputs },
        queryHash,
      });
    } catch (e) {
      caught = e;
    }
    expect(caught, 'expected oversized commitment to throw').to.not.equal(undefined);
    const msg = String(caught.message ?? caught);
    expect(msg).to.match(/MalformedPublicInput|BN254 field|field size/i);
  });

  after(async function () {
    try {
      const globalCurveBn128 = (globalThis as any).curve_bn128;
      if (globalCurveBn128?.terminate) {
        await globalCurveBn128.terminate();
      }
    } catch (_) {
      // ignore
    }
  });
});
