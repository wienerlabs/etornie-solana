/**
 * End-to-end integration test for the `verify_file_ownership_proof`
 * instruction on devnet (Faz 5.5).
 *
 * The program verifies a Groth16 proof that the caller knows a secret `s`
 * with `Poseidon(s, fh_hi, fh_lo) == commitment`, then writes an
 * `FileOwnershipRecord` PDA seeded on (b"file-ownership", user, file_hash).
 *
 * Each test generates a fresh proof at runtime via snarkjs + circomlibjs —
 * no fixture files — so the circuit pipeline stays exercised end-to-end.
 *
 * Covers:
 *   1. A valid proof + canonical file_hash halves → PDA created
 *   2. The same (user, file_hash) submitted twice → ReplayedProof
 *   3. fh_hi tampered with a bit above position 128 (still in field, but
 *      inconsistent with the `file_hash` arg) → MalformedFileHashInput
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

// snarkjs / circomlibjs do not ship first-class TS types; load as CJS.
// eslint-disable-next-line @typescript-eslint/no-var-requires
const snarkjs = require('snarkjs');
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { buildPoseidon } = require('circomlibjs');

const DEVNET_RPC = process.env.DEVNET_RPC_URL ?? 'https://api.devnet.solana.com';
const PROGRAM_ID = new PublicKey('GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5');

const KEYPAIR_PATH =
  process.env.SOLANA_KEYPAIR_PATH ??
  path.join(process.env.HOME ?? '', '.config/solana/id.json');

const WASM_PATH =
  'circuits/build/file_ownership/file_ownership_js/file_ownership.wasm';
const ZKEY_PATH = 'circuits/build/file_ownership/file_ownership_final.zkey';
const IDL_PATH = 'idl/etornie_zk_verifier.json';

const FILE_OWNERSHIP_SEED = Buffer.from('file-ownership');

function loadFunder(): Keypair {
  const secret = JSON.parse(fs.readFileSync(KEYPAIR_PATH, 'utf8')) as number[];
  return Keypair.fromSecretKey(Uint8Array.from(secret));
}

function derivePda(user: PublicKey, fileHash: Uint8Array): [PublicKey, number] {
  return PublicKey.findProgramAddressSync(
    [FILE_OWNERSHIP_SEED, user.toBuffer(), Buffer.from(fileHash)],
    PROGRAM_ID
  );
}

function splitFileHash(fileHash: Uint8Array): { fhHi: bigint; fhLo: bigint } {
  if (fileHash.length !== 32) {
    throw new Error(`file_hash must be 32 bytes, got ${fileHash.length}`);
  }
  let hi = 0n;
  let lo = 0n;
  for (let i = 0; i < 16; i++) hi = (hi << 8n) | BigInt(fileHash[i]);
  for (let i = 16; i < 32; i++) lo = (lo << 8n) | BigInt(fileHash[i]);
  return { fhHi: hi, fhLo: lo };
}

// Draw a secret uniformly from [1, 2^248) — always < BN254_P (~2^254), never 0.
function randomSecret(): bigint {
  const bytes = crypto.randomBytes(31);
  bytes[0] |= 0x01;
  let out = 0n;
  for (const b of bytes) out = (out << 8n) | BigInt(b);
  return out;
}

describe('file_ownership verifier on devnet (sponsored flow)', function () {
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

  // Shared between test 1 (happy path) and test 2 (replay).
  let happyFileHash: Uint8Array;
  let happyProof: OnChainProof;

  async function generateProof(opts: {
    secret: bigint;
    fhHi: bigint;
    fhLo: bigint;
  }): Promise<{ onchain: OnChainProof; commitment: bigint }> {
    // Circuit asserts `commitment == Poseidon(secret, fh_hi, fh_lo)` so the
    // caller must supply the matching commitment as a public input — we
    // compute it off-circuit with the same Poseidon parameters.
    const commitmentF = poseidon([opts.secret, opts.fhHi, opts.fhLo]);
    const commitment = F.toObject(commitmentF) as bigint;

    const input = {
      secret: opts.secret.toString(),
      file_hash_hi: opts.fhHi.toString(),
      file_hash_lo: opts.fhLo.toString(),
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
    fileHash: Uint8Array;
  }): Promise<{ signature: string; pda: PublicKey }> {
    const [pda] = derivePda(params.user.publicKey, params.fileHash);
    const computeIx = ComputeBudgetProgram.setComputeUnitLimit({
      units: 300_000,
    });

    const signature = await program.methods
      .verifyFileOwnershipProof(
        Array.from(params.onchain.proofA),
        Array.from(params.onchain.proofB),
        Array.from(params.onchain.proofC),
        params.onchain.publicInputs.map((b) => Array.from(b)),
        Array.from(params.fileHash)
      )
      .accounts({
        feePayer: funder.publicKey,
        user: params.user.publicKey,
        fileOwnershipRecord: pda,
        systemProgram: SystemProgram.programId,
      })
      .preInstructions([computeIx])
      .signers([params.user])
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

  it('accepts a valid file_ownership proof and writes the PDA', async function () {
    happyFileHash = crypto.randomBytes(32);
    const { fhHi, fhLo } = splitFileHash(happyFileHash);
    const secret = randomSecret();

    const { onchain, commitment } = await generateProof({ secret, fhHi, fhLo });
    happyProof = onchain;

    const { signature, pda } = await callVerify({
      user: happyUser,
      onchain,
      fileHash: happyFileHash,
    });
    console.log(`    file_hash:       ${Buffer.from(happyFileHash).toString('hex')}`);
    console.log(`    verify tx:       ${signature}`);
    console.log(`    ownership pda:   ${pda.toBase58()}`);
    console.log(`    explorer:        https://explorer.solana.com/tx/${signature}?cluster=devnet`);

    const record = await (program.account as any).fileOwnershipRecord.fetch(pda);
    expect(record.owner.toBase58()).to.equal(happyUser.publicKey.toBase58());
    expect(
      Buffer.from(record.fileHash).equals(Buffer.from(happyFileHash)),
      'stored file_hash must match the claimed one'
    ).to.equal(true);
    // The commitment field on the PDA should be the BE-32 encoding of the
    // off-chain-computed Poseidon output.
    const storedCommitment = BigInt('0x' + Buffer.from(record.commitment).toString('hex'));
    expect(storedCommitment).to.equal(commitment);
    expect(record.isInitialized).to.equal(true);
    expect(Number(record.verifiedAt)).to.be.greaterThan(0);
  });

  it('rejects the same (user, file_hash) submitted twice as ReplayedProof', async function () {
    let caught: any;
    try {
      await callVerify({
        user: happyUser,
        onchain: happyProof,
        fileHash: happyFileHash,
      });
    } catch (e) {
      caught = e;
    }
    expect(caught, 'expected second submission to throw').to.not.equal(undefined);
    const msg = String(caught.message ?? caught);
    expect(msg).to.match(/ReplayedProof|already been recorded|already in use/i);
  });

  it('rejects mismatched fh_hi vs file_hash arg as MalformedFileHashInput', async function () {
    // Real file_hash the user *claims* to own
    const realFileHash = crypto.randomBytes(32);
    const { fhHi: realFhHi, fhLo: realFhLo } = splitFileHash(realFileHash);

    // Tamper fh_hi: set a bit at position 200 — valid BN254 field element, but
    // no longer equals [0;16] ++ realFileHash[..16] when BE-serialised.
    const tamperedFhHi = realFhHi | (1n << 200n);
    const secret = randomSecret();

    // Generate a genuinely valid Groth16 proof for the *tampered* input:
    // circuit accepts any field element, so this succeeds.
    const { onchain } = await generateProof({
      secret,
      fhHi: tamperedFhHi,
      fhLo: realFhLo,
    });

    // Submit with file_hash = realFileHash (no high bits). The program should
    // detect the mismatch in the canonical-halves check and reject before
    // running the pairing.
    let caught: any;
    try {
      await callVerify({
        user: malformedHashUser,
        onchain,
        fileHash: realFileHash,
      });
    } catch (e) {
      caught = e;
    }
    expect(caught, 'expected canonical-halves mismatch to throw').to.not.equal(undefined);
    const msg = String(caught.message ?? caught);
    expect(msg).to.match(/MalformedFileHashInput|canonical/i);
  });

  it('rejects a byte-flipped proofA as InvalidProof (pairing fails)', async function () {
    const fileHash = crypto.randomBytes(32);
    const { fhHi, fhLo } = splitFileHash(fileHash);
    const secret = randomSecret();

    const { onchain } = await generateProof({ secret, fhHi, fhLo });
    const tamperedA = new Uint8Array(onchain.proofA);
    tamperedA[tamperedA.length - 1] ^= 0x01;

    let caught: any;
    try {
      await callVerify({
        user: tamperedProofUser,
        onchain: { ...onchain, proofA: tamperedA },
        fileHash,
      });
    } catch (e) {
      caught = e;
    }
    expect(caught, 'expected tampered proof to throw').to.not.equal(undefined);
    const msg = String(caught.message ?? caught);
    expect(msg).to.match(/InvalidProof|VerifierInternal|pairing/i);
  });

  it('rejects a commitment public input >= BN254_P as MalformedPublicInput', async function () {
    const fileHash = crypto.randomBytes(32);
    const { fhHi, fhLo } = splitFileHash(fileHash);
    const secret = randomSecret();

    const { onchain } = await generateProof({ secret, fhHi, fhLo });

    // Replace commitment (public_inputs[2]) with all-0xff — unambiguously
    // above the BN254 prime, so the verifier aborts before pairing.
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
        fileHash,
      });
    } catch (e) {
      caught = e;
    }
    expect(caught, 'expected oversized commitment to throw').to.not.equal(undefined);
    const msg = String(caught.message ?? caught);
    expect(msg).to.match(/MalformedPublicInput|BN254 field|field size/i);
  });

  after(async function () {
    // snarkjs pulls in fastfile workers that hold the event loop open for
    // a few seconds after prove() — release them so the mocha process exits
    // cleanly inside the CI timeout.
    try {
      const globalCurveBn128 = (globalThis as any).curve_bn128;
      if (globalCurveBn128?.terminate) {
        await globalCurveBn128.terminate();
      }
    } catch (_) {
      // ignore — best-effort cleanup
    }
  });
});
