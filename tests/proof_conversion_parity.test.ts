/**
 * Parity check between the two copies of the proof-conversion helper:
 *   - scripts/proof_conversion.ts (Node / ts-mocha)
 *   - dashboard/src/lib/zk/proofConversion.ts (browser)
 *
 * They must produce byte-identical output for the same inputs, otherwise
 * the sponsored flow silently goes out of sync with the on-chain verifier.
 * Drop this test when the helpers are hoisted into a shared workspace
 * package (tracked in Step 10 of the migration plan).
 */

import * as fs from 'fs';
import { expect } from 'chai';
import * as root from '../scripts/proof_conversion';
import * as dash from '../dashboard/src/lib/zk/proofConversion';

const PROOF_FIXTURE = 'circuits/build/hello_world/proof.json';
const PUBLIC_FIXTURE = 'circuits/build/hello_world/public.json';

function bufEq(a: Uint8Array, b: Uint8Array): boolean {
  return Buffer.from(a).equals(Buffer.from(b));
}

describe('proof_conversion parity (scripts/ vs dashboard/)', () => {
  it('exports the same public API surface', () => {
    const expected = [
      'BN254_P',
      'PUBLIC_INPUT_BYTES',
      'G1_BYTES',
      'G2_BYTES',
      'negateY',
      'computeJournalDigest',
      'convertSnarkjsProof',
    ];
    for (const k of expected) {
      expect((root as any)[k], `scripts missing export: ${k}`).to.not.equal(undefined);
      expect((dash as any)[k], `dashboard missing export: ${k}`).to.not.equal(undefined);
    }
  });

  it('agrees on constants', () => {
    expect(root.BN254_P).to.equal(dash.BN254_P);
    expect(root.G1_BYTES).to.equal(dash.G1_BYTES);
    expect(root.G2_BYTES).to.equal(dash.G2_BYTES);
    expect(root.PUBLIC_INPUT_BYTES).to.equal(dash.PUBLIC_INPUT_BYTES);
  });

  it('produces byte-identical OnChainProof for the hello_world fixture', () => {
    const proof = JSON.parse(fs.readFileSync(PROOF_FIXTURE, 'utf8')) as root.SnarkjsProof;
    const publicSignals = JSON.parse(fs.readFileSync(PUBLIC_FIXTURE, 'utf8')) as string[];

    const r = root.convertSnarkjsProof(proof, publicSignals);
    const d = dash.convertSnarkjsProof(proof as any, publicSignals);

    expect(bufEq(r.proofA, d.proofA), 'proofA differs').to.equal(true);
    expect(bufEq(r.proofB, d.proofB), 'proofB differs').to.equal(true);
    expect(bufEq(r.proofC, d.proofC), 'proofC differs').to.equal(true);
    expect(r.publicInputs.length).to.equal(d.publicInputs.length);
    for (let i = 0; i < r.publicInputs.length; i++) {
      expect(
        bufEq(r.publicInputs[i], d.publicInputs[i]),
        `publicInputs[${i}] differs`
      ).to.equal(true);
    }
    expect(bufEq(r.journalDigest, d.journalDigest), 'journalDigest differs').to.equal(true);
  });

  it('agrees on negateY (y + negateY(y) ≡ 0 mod p, both helpers)', () => {
    const samples = [1n, 33n, root.BN254_P / 2n, root.BN254_P - 1n];
    for (const y of samples) {
      expect(root.negateY(y)).to.equal(dash.negateY(y));
      expect((y + root.negateY(y)) % root.BN254_P).to.equal(0n);
    }
  });

  it('agrees on computeJournalDigest', () => {
    const inputs: Uint8Array[] = [
      new Uint8Array(32).fill(1),
      new Uint8Array(32).fill(2),
    ];
    expect(
      bufEq(root.computeJournalDigest(inputs), dash.computeJournalDigest(inputs))
    ).to.equal(true);
  });
});
