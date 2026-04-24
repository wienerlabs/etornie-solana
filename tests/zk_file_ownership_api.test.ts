/**
 * HTTP smoke test for services/api /zk/file-ownership/* endpoints.
 *
 * Mirrors tests/zk_api.test.ts (hello_world) but for the file_ownership
 * circuit: 3 public inputs, explicit file_hash arg, PDA seed
 * [b"file-ownership", user, file_hash].
 *
 * Regenerates a fresh proof on setup so the circuit build is exercised at
 * the same cadence as the other tests. Asserts:
 *   - POST /zk/file-ownership/prepare returns well-formed payload
 *   - Backend ix_data matches what Anchor TS SDK encodes for the same args
 *   - GET /zk/file-ownership/record/{user}/{hash} matches TS PDA derivation
 *   - Malformed base64 -> 400
 *
 * Requires the API service at http://127.0.0.1:8000 (set $API_URL to override).
 * Skips when the backend is unreachable.
 */

import * as fs from 'fs';
import * as crypto from 'crypto';
import { expect } from 'chai';
import * as anchor from '@coral-xyz/anchor';
import { Program } from '@coral-xyz/anchor';
import {
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

const API_URL = process.env.API_URL ?? 'http://127.0.0.1:8000';
const DEVNET_RPC = process.env.DEVNET_RPC_URL ?? 'https://api.devnet.solana.com';
const PROGRAM_ID = new PublicKey('GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5');
const IDL_PATH = 'idl/etornie_zk_verifier.json';

const WASM_PATH =
  'circuits/build/file_ownership/file_ownership_js/file_ownership.wasm';
const ZKEY_PATH = 'circuits/build/file_ownership/file_ownership_final.zkey';

const FILE_OWNERSHIP_SEED = Buffer.from('file-ownership');

function b64(u: Uint8Array): string {
  return Buffer.from(u).toString('base64');
}

function splitFileHash(fileHash: Uint8Array): { fhHi: bigint; fhLo: bigint } {
  let hi = 0n;
  let lo = 0n;
  for (let i = 0; i < 16; i++) hi = (hi << 8n) | BigInt(fileHash[i]);
  for (let i = 16; i < 32; i++) lo = (lo << 8n) | BigInt(fileHash[i]);
  return { fhHi: hi, fhLo: lo };
}

function randomSecret(): bigint {
  const bytes = crypto.randomBytes(31);
  bytes[0] |= 0x01;
  let out = 0n;
  for (const b of bytes) out = (out << 8n) | BigInt(b);
  return out;
}

async function backendReachable(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/docs`);
    return res.ok;
  } catch {
    return false;
  }
}

describe('/zk/file-ownership/* HTTP smoke (backend must be up)', function () {
  this.timeout(120_000);

  let proof: OnChainProof;
  let fileHash: Uint8Array;
  let dummyUser: Keypair;
  let backendUp: boolean;

  before(async function () {
    fileHash = crypto.randomBytes(32);
    const { fhHi, fhLo } = splitFileHash(fileHash);
    const secret = randomSecret();

    const poseidon = await buildPoseidon();
    const commitment = poseidon.F.toObject(
      poseidon([secret, fhHi, fhLo])
    ) as bigint;

    const { proof: rawProof, publicSignals } = await snarkjs.groth16.fullProve(
      {
        secret: secret.toString(),
        file_hash_hi: fhHi.toString(),
        file_hash_lo: fhLo.toString(),
        commitment: commitment.toString(),
      },
      WASM_PATH,
      ZKEY_PATH
    );

    proof = convertSnarkjsProof(rawProof as SnarkjsProof, publicSignals);
    dummyUser = Keypair.generate();
    backendUp = await backendReachable();
    if (!backendUp) {
      console.log(`    [skip] API not reachable at ${API_URL}`);
    }
  });

  it('POST /zk/file-ownership/prepare returns well-formed payload', async function () {
    if (!backendUp) this.skip();

    const body = {
      user_wallet: dummyUser.publicKey.toBase58(),
      proof_a_b64: b64(proof.proofA),
      proof_b_b64: b64(proof.proofB),
      proof_c_b64: b64(proof.proofC),
      public_inputs_b64: proof.publicInputs.map(b64),
      file_hash_b64: b64(fileHash),
    };
    const res = await fetch(`${API_URL}/zk/file-ownership/prepare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    expect(res.ok, `status=${res.status}`).to.equal(true);
    const payload = (await res.json()) as {
      program_id: string;
      fee_payer: string;
      user: string;
      file_ownership_record: string;
      ix_data_b64: string;
      recent_blockhash: string;
    };

    expect(payload.program_id).to.equal(PROGRAM_ID.toBase58());
    expect(payload.user).to.equal(dummyUser.publicKey.toBase58());
    expect(payload.recent_blockhash.length).to.be.greaterThan(30);

    // Expected ix_data layout:
    //   8 (disc) + 64 + 128 + 64 + 96 (3 × 32B inputs) + 32 (file_hash) = 392
    const ixBytes = Buffer.from(payload.ix_data_b64, 'base64');
    expect(ixBytes.length).to.equal(392);
    expect(ixBytes.slice(8, 72).equals(Buffer.from(proof.proofA))).to.equal(true);
    expect(ixBytes.slice(72, 200).equals(Buffer.from(proof.proofB))).to.equal(true);
    expect(ixBytes.slice(200, 264).equals(Buffer.from(proof.proofC))).to.equal(true);
    for (let i = 0; i < 3; i++) {
      const offset = 264 + i * 32;
      expect(
        ixBytes.slice(offset, offset + 32).equals(Buffer.from(proof.publicInputs[i])),
        `public_inputs[${i}] mismatch`
      ).to.equal(true);
    }
    expect(ixBytes.slice(360, 392).equals(Buffer.from(fileHash))).to.equal(true);

    // PDA parity: backend and client should agree on the derived address.
    const [expectedPda] = PublicKey.findProgramAddressSync(
      [FILE_OWNERSHIP_SEED, dummyUser.publicKey.toBuffer(), Buffer.from(fileHash)],
      PROGRAM_ID
    );
    expect(payload.file_ownership_record).to.equal(expectedPda.toBase58());
  });

  it('backend ix_data matches what Anchor TS SDK encodes for the same args', async function () {
    if (!backendUp) this.skip();

    const body = {
      user_wallet: dummyUser.publicKey.toBase58(),
      proof_a_b64: b64(proof.proofA),
      proof_b_b64: b64(proof.proofB),
      proof_c_b64: b64(proof.proofC),
      public_inputs_b64: proof.publicInputs.map(b64),
      file_hash_b64: b64(fileHash),
    };
    const res = await fetch(`${API_URL}/zk/file-ownership/prepare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const backendPayload = (await res.json()) as {
      ix_data_b64: string;
      fee_payer: string;
    };
    const backendIx = Buffer.from(backendPayload.ix_data_b64, 'base64');

    const connection = new Connection(DEVNET_RPC, 'confirmed');
    const wallet = new anchor.Wallet(Keypair.generate());
    const provider = new anchor.AnchorProvider(connection, wallet, {
      commitment: 'confirmed',
    });
    const idl = JSON.parse(fs.readFileSync(IDL_PATH, 'utf8')) as anchor.Idl;
    const program = new Program(idl, provider);

    const [pda] = PublicKey.findProgramAddressSync(
      [FILE_OWNERSHIP_SEED, dummyUser.publicKey.toBuffer(), Buffer.from(fileHash)],
      PROGRAM_ID
    );
    const feePayer = new PublicKey(backendPayload.fee_payer);

    const anchorIx = await program.methods
      .verifyFileOwnershipProof(
        Array.from(proof.proofA),
        Array.from(proof.proofB),
        Array.from(proof.proofC),
        proof.publicInputs.map((b) => Array.from(b)),
        Array.from(fileHash)
      )
      .accounts({
        feePayer,
        user: dummyUser.publicKey,
        fileOwnershipRecord: pda,
        systemProgram: SystemProgram.programId,
      })
      .instruction();

    expect(
      Buffer.from(anchorIx.data).equals(backendIx),
      `anchor data len=${anchorIx.data.length}, backend len=${backendIx.length}`
    ).to.equal(true);
  });

  it('GET /zk/file-ownership/record/{user}/{file_hash_hex} matches client-side derivation', async function () {
    if (!backendUp) this.skip();

    const hashHex = Buffer.from(fileHash).toString('hex');
    const res = await fetch(
      `${API_URL}/zk/file-ownership/record/${dummyUser.publicKey.toBase58()}/${hashHex}`
    );
    expect(res.ok, `status=${res.status}`).to.equal(true);
    const { file_ownership_record, bump } = (await res.json()) as {
      file_ownership_record: string;
      bump: string;
    };

    const [expectedPda, expectedBump] = PublicKey.findProgramAddressSync(
      [FILE_OWNERSHIP_SEED, dummyUser.publicKey.toBuffer(), Buffer.from(fileHash)],
      PROGRAM_ID
    );
    expect(file_ownership_record).to.equal(expectedPda.toBase58());
    expect(Number(bump)).to.equal(expectedBump);
  });

  it('rejects malformed base64 with 400', async function () {
    if (!backendUp) this.skip();

    const res = await fetch(`${API_URL}/zk/file-ownership/prepare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_wallet: dummyUser.publicKey.toBase58(),
        proof_a_b64: '!!!not base64!!!',
        proof_b_b64: b64(proof.proofB),
        proof_c_b64: b64(proof.proofC),
        public_inputs_b64: proof.publicInputs.map(b64),
        file_hash_b64: b64(fileHash),
      }),
    });
    expect(res.status).to.equal(400);
  });

  after(async function () {
    try {
      const globalCurveBn128 = (globalThis as any).curve_bn128;
      if (globalCurveBn128?.terminate) {
        await globalCurveBn128.terminate();
      }
    } catch {
      // best-effort
    }
  });
});
