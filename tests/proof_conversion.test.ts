import { expect } from 'chai';
import * as fs from 'fs';
import * as crypto from 'crypto';
import {
  convertSnarkjsProof,
  computeJournalDigest,
  negateY,
  BN254_P,
  G1_BYTES,
  G2_BYTES,
  PUBLIC_INPUT_BYTES,
  SnarkjsProof,
  __testing,
} from '../scripts/proof_conversion';

const { beBytes32ToBigInt, bigIntToBEBytes32 } = __testing;

const PROOF_PATH = 'circuits/build/hello_world/proof.json';
const PUBLIC_PATH = 'circuits/build/hello_world/public.json';

function loadFixtures(): { proof: SnarkjsProof; publicSignals: string[] } {
  const proof = JSON.parse(fs.readFileSync(PROOF_PATH, 'utf8')) as SnarkjsProof;
  const publicSignals = JSON.parse(fs.readFileSync(PUBLIC_PATH, 'utf8')) as string[];
  return { proof, publicSignals };
}

describe('proof_conversion (hello_world fixture)', () => {
  it('fixture files exist', () => {
    expect(fs.existsSync(PROOF_PATH), `missing ${PROOF_PATH}`).to.equal(true);
    expect(fs.existsSync(PUBLIC_PATH), `missing ${PUBLIC_PATH}`).to.equal(true);
  });

  it('produces the expected byte lengths', () => {
    const { proof, publicSignals } = loadFixtures();
    const result = convertSnarkjsProof(proof, publicSignals);

    expect(result.proofA.length).to.equal(G1_BYTES);
    expect(result.proofB.length).to.equal(G2_BYTES);
    expect(result.proofC.length).to.equal(G1_BYTES);
    expect(result.publicInputs).to.have.lengthOf(publicSignals.length);
    for (const inp of result.publicInputs) {
      expect(inp.length).to.equal(PUBLIC_INPUT_BYTES);
    }
    expect(result.journalDigest.length).to.equal(32);
  });

  it('public input "33" encodes to 32-byte BE ending in 0x21', () => {
    const { proof } = loadFixtures();
    const result = convertSnarkjsProof(proof, ['33']);
    const inp = result.publicInputs[0];
    for (let i = 0; i < 31; i++) {
      expect(inp[i]).to.equal(0, `byte ${i} should be zero`);
    }
    expect(inp[31]).to.equal(0x21);
    expect(beBytes32ToBigInt(inp)).to.equal(33n);
  });

  it('proofA encodes x unchanged and y negated (y + yNeg ≡ 0 mod p)', () => {
    const { proof, publicSignals } = loadFixtures();
    const result = convertSnarkjsProof(proof, publicSignals);

    const expectedX = BigInt(proof.pi_a[0]);
    const actualX = beBytes32ToBigInt(result.proofA.slice(0, 32));
    expect(actualX).to.equal(expectedX);

    const origY = BigInt(proof.pi_a[1]);
    const negY = beBytes32ToBigInt(result.proofA.slice(32, 64));
    expect(negY).to.equal(negateY(origY));
    expect((origY + negY) % BN254_P).to.equal(0n);
    expect(negY < BN254_P, `negY >= BN254_P: ${negY}`).to.equal(true);
  });

  it('proofB packs Fp2 coords as c1 || c0 || c1 || c0', () => {
    const { proof, publicSignals } = loadFixtures();
    const result = convertSnarkjsProof(proof, publicSignals);

    const xc0 = BigInt(proof.pi_b[0][0]);
    const xc1 = BigInt(proof.pi_b[0][1]);
    const yc0 = BigInt(proof.pi_b[1][0]);
    const yc1 = BigInt(proof.pi_b[1][1]);

    expect(beBytes32ToBigInt(result.proofB.slice(0, 32))).to.equal(xc1);
    expect(beBytes32ToBigInt(result.proofB.slice(32, 64))).to.equal(xc0);
    expect(beBytes32ToBigInt(result.proofB.slice(64, 96))).to.equal(yc1);
    expect(beBytes32ToBigInt(result.proofB.slice(96, 128))).to.equal(yc0);
  });

  it('proofC is straight x || y (no negation)', () => {
    const { proof, publicSignals } = loadFixtures();
    const result = convertSnarkjsProof(proof, publicSignals);

    expect(beBytes32ToBigInt(result.proofC.slice(0, 32))).to.equal(
      BigInt(proof.pi_c[0])
    );
    expect(beBytes32ToBigInt(result.proofC.slice(32, 64))).to.equal(
      BigInt(proof.pi_c[1])
    );
  });

  it('journalDigest == sha256(concat(publicInputs))', () => {
    const { proof, publicSignals } = loadFixtures();
    const result = convertSnarkjsProof(proof, publicSignals);

    const concat = Buffer.concat(result.publicInputs.map((u) => Buffer.from(u)));
    const expected = crypto.createHash('sha256').update(concat).digest();
    expect(Buffer.from(result.journalDigest).equals(expected)).to.equal(true);
  });

  it('computeJournalDigest is deterministic and matches node:crypto', () => {
    const inputs = [new Uint8Array(32).fill(1), new Uint8Array(32).fill(2)];
    const got = computeJournalDigest(inputs);
    const expected = crypto
      .createHash('sha256')
      .update(Buffer.concat(inputs.map((u) => Buffer.from(u))))
      .digest();
    expect(Buffer.from(got).equals(expected)).to.equal(true);
  });

  it('rejects public inputs >= BN254_P', () => {
    const { proof } = loadFixtures();
    const oversize = BN254_P.toString();
    expect(() => convertSnarkjsProof(proof, [oversize])).to.throw(/BN254 field size/);
  });

  it('rejects unsupported protocol / curve', () => {
    const { proof, publicSignals } = loadFixtures();
    const mutated = { ...proof, protocol: 'plonk' };
    expect(() => convertSnarkjsProof(mutated as SnarkjsProof, publicSignals)).to.throw(
      /unsupported protocol/
    );
  });

  it('bigIntToBEBytes32 round-trips through beBytes32ToBigInt', () => {
    const samples = [0n, 1n, 33n, BN254_P - 1n, (1n << 200n) - 1n];
    for (const x of samples) {
      expect(beBytes32ToBigInt(bigIntToBEBytes32(x))).to.equal(x);
    }
  });

  it('rejects bigints that overflow 32 bytes', () => {
    expect(() => bigIntToBEBytes32(1n << 256n)).to.throw(/does not fit/);
    expect(() => bigIntToBEBytes32(-1n)).to.throw(/negative/);
  });
});
