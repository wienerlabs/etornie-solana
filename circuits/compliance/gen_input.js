// Generates a deterministic test vector for the compliance circuit.
//
// Writes `input.json` (consumed by snarkjs witness generation) with:
//   - secret         : private toy value
//   - query_hash_hi  : top 128 bits of sha256(TEST_QUERY)
//   - query_hash_lo  : bottom 128 bits of sha256(TEST_QUERY)
//   - commitment     : Poseidon(secret, qh_hi, qh_lo)
//
// Both secret and query text are fixed so the build pipeline is fully
// reproducible and the committed input.json always matches.

const fs = require("fs");
const path = require("path");
const { createHash } = require("crypto");
const { buildPoseidon } = require("circomlibjs");

const TEST_QUERY = "etornie-compliance-test-vector-v1";
const SECRET = 9876543210987654321n;

async function main() {
  const poseidon = await buildPoseidon();
  const F = poseidon.F;

  const queryHash = createHash("sha256").update(TEST_QUERY).digest();
  const qhHi = BigInt("0x" + queryHash.subarray(0, 16).toString("hex"));
  const qhLo = BigInt("0x" + queryHash.subarray(16, 32).toString("hex"));

  const hashElem = poseidon([SECRET, qhHi, qhLo]);
  const commitment = F.toObject(hashElem);

  const input = {
    secret: SECRET.toString(),
    query_hash_hi: qhHi.toString(),
    query_hash_lo: qhLo.toString(),
    commitment: commitment.toString(),
  };

  const outPath = path.join(__dirname, "input.json");
  fs.writeFileSync(outPath, JSON.stringify(input, null, 2) + "\n");

  console.log("wrote", outPath);
  console.log("sha256(query):", queryHash.toString("hex"));
  console.log("  qh_hi:", qhHi.toString());
  console.log("  qh_lo:", qhLo.toString());
  console.log("  commitment:", commitment.toString());
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
