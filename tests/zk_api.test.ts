/**
 * HTTP smoke test for services/api /zk/* endpoints.
 *
 * This test asserts that the backend's hand-rolled Borsh-style ix_data
 * encoding matches the ix_data Anchor's TS SDK produces for the same
 * arguments. If they ever drift, the sponsored flow will silently go from
 * "works" to "mysterious InstructionData deserialization error" on devnet.
 *
 * It does NOT send a transaction — just calls /zk/verify-prepare,
 * /zk/proof-record, and diff-checks byte buffers.
 *
 * Requires the API service at http://127.0.0.1:8000 (use $API_URL to
 * override). The test skips itself if the backend is unreachable.
 */

import * as fs from 'fs';
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
} from '../scripts/proof_conversion';

const API_URL = process.env.API_URL ?? 'http://127.0.0.1:8000';
const DEVNET_RPC = process.env.DEVNET_RPC_URL ?? 'https://api.devnet.solana.com';
const PROGRAM_ID = new PublicKey('GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5');
const IDL_PATH = 'idl/etornie_zk_verifier.json';
const PROOF_FIXTURE = 'circuits/build/hello_world/proof.json';
const PUBLIC_FIXTURE = 'circuits/build/hello_world/public.json';

function b64(u: Uint8Array): string {
  return Buffer.from(u).toString('base64');
}

async function backendReachable(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/docs`);
    return res.ok;
  } catch {
    return false;
  }
}

describe('/zk/* HTTP smoke (backend must be up)', function () {
  this.timeout(30_000);

  let proof: ReturnType<typeof convertSnarkjsProof>;
  let dummyUser: Keypair;
  let backendUp: boolean;

  before(async function () {
    const proofJson = JSON.parse(fs.readFileSync(PROOF_FIXTURE, 'utf8')) as SnarkjsProof;
    const publicSignals = JSON.parse(fs.readFileSync(PUBLIC_FIXTURE, 'utf8')) as string[];
    proof = convertSnarkjsProof(proofJson, publicSignals);
    dummyUser = Keypair.generate();
    backendUp = await backendReachable();
    if (!backendUp) {
      console.log(`    [skip] API not reachable at ${API_URL}`);
    }
  });

  it('POST /zk/verify-prepare returns well-formed payload', async function () {
    if (!backendUp) this.skip();

    const body = {
      user_wallet: dummyUser.publicKey.toBase58(),
      proof_a_b64: b64(proof.proofA),
      proof_b_b64: b64(proof.proofB),
      proof_c_b64: b64(proof.proofC),
      public_inputs_b64: proof.publicInputs.map(b64),
      journal_digest_b64: b64(proof.journalDigest),
    };
    const res = await fetch(`${API_URL}/zk/verify-prepare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    expect(res.ok, `status=${res.status}`).to.equal(true);
    const payload = (await res.json()) as {
      program_id: string;
      fee_payer: string;
      user: string;
      proof_record: string;
      ix_data_b64: string;
      recent_blockhash: string;
    };

    expect(payload.program_id).to.equal(PROGRAM_ID.toBase58());
    expect(payload.user).to.equal(dummyUser.publicKey.toBase58());
    expect(payload.recent_blockhash.length).to.be.greaterThan(30);

    // Expected ix_data layout: 8 (disc) + 64 + 128 + 64 + 32 (1 * 32B input) + 32 (digest) = 328
    const ixBytes = Buffer.from(payload.ix_data_b64, 'base64');
    expect(ixBytes.length).to.equal(328);
    expect(ixBytes.slice(8, 72).equals(Buffer.from(proof.proofA))).to.equal(true);
    expect(ixBytes.slice(72, 200).equals(Buffer.from(proof.proofB))).to.equal(true);
    expect(ixBytes.slice(200, 264).equals(Buffer.from(proof.proofC))).to.equal(true);
    expect(ixBytes.slice(264, 296).equals(Buffer.from(proof.publicInputs[0]))).to.equal(true);
    expect(ixBytes.slice(296, 328).equals(Buffer.from(proof.journalDigest))).to.equal(true);
  });

  it('backend ix_data matches what Anchor TS SDK encodes for the same args', async function () {
    if (!backendUp) this.skip();

    // Fetch the backend's payload
    const body = {
      user_wallet: dummyUser.publicKey.toBase58(),
      proof_a_b64: b64(proof.proofA),
      proof_b_b64: b64(proof.proofB),
      proof_c_b64: b64(proof.proofC),
      public_inputs_b64: proof.publicInputs.map(b64),
      journal_digest_b64: b64(proof.journalDigest),
    };
    const res = await fetch(`${API_URL}/zk/verify-prepare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const backendPayload = (await res.json()) as { ix_data_b64: string };
    const backendIx = Buffer.from(backendPayload.ix_data_b64, 'base64');

    // Build the same ix via Anchor TS to compare bytes
    const connection = new Connection(DEVNET_RPC, 'confirmed');
    const wallet = new anchor.Wallet(Keypair.generate()); // unused — we only need ix bytes
    const provider = new anchor.AnchorProvider(connection, wallet, { commitment: 'confirmed' });
    const idl = JSON.parse(fs.readFileSync(IDL_PATH, 'utf8')) as anchor.Idl;
    const program = new Program(idl, provider);

    const [pda] = PublicKey.findProgramAddressSync(
      [Buffer.from('proof'), dummyUser.publicKey.toBuffer(), Buffer.from(proof.journalDigest)],
      PROGRAM_ID
    );
    const feePayer = new PublicKey(
      (await (await fetch(`${API_URL}/zk/verify-prepare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })).json() as any).fee_payer
    );
    const anchorIx = await program.methods
      .verifyProof(
        Array.from(proof.proofA),
        Array.from(proof.proofB),
        Array.from(proof.proofC),
        proof.publicInputs.map((b) => Array.from(b)),
        Array.from(proof.journalDigest)
      )
      .accounts({
        feePayer,
        user: dummyUser.publicKey,
        proofRecord: pda,
        systemProgram: SystemProgram.programId,
      })
      .instruction();

    expect(
      Buffer.from(anchorIx.data).equals(backendIx),
      `anchor data len=${anchorIx.data.length}, backend len=${backendIx.length}`
    ).to.equal(true);
  });

  it('GET /zk/proof-record/{user}/{digest_hex} matches client-side derivation', async function () {
    if (!backendUp) this.skip();

    const digestHex = Buffer.from(proof.journalDigest).toString('hex');
    const res = await fetch(
      `${API_URL}/zk/proof-record/${dummyUser.publicKey.toBase58()}/${digestHex}`
    );
    expect(res.ok, `status=${res.status}`).to.equal(true);
    const { proof_record, bump } = (await res.json()) as {
      proof_record: string;
      bump: string;
    };

    const [expectedPda, expectedBump] = PublicKey.findProgramAddressSync(
      [Buffer.from('proof'), dummyUser.publicKey.toBuffer(), Buffer.from(proof.journalDigest)],
      PROGRAM_ID
    );
    expect(proof_record).to.equal(expectedPda.toBase58());
    expect(Number(bump)).to.equal(expectedBump);
  });

  it('rejects malformed base64 with 400', async function () {
    if (!backendUp) this.skip();

    const res = await fetch(`${API_URL}/zk/verify-prepare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_wallet: dummyUser.publicKey.toBase58(),
        proof_a_b64: '!!!not base64!!!',
        proof_b_b64: b64(proof.proofB),
        proof_c_b64: b64(proof.proofC),
        public_inputs_b64: proof.publicInputs.map(b64),
        journal_digest_b64: b64(proof.journalDigest),
      }),
    });
    expect(res.status).to.equal(400);
  });
});
