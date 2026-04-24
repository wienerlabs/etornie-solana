// Generates a deterministic test vector for the file_ownership circuit.
//
// Writes `input.json` (consumed by snarkjs witness generation) with:
//   - secret        : private toy value
//   - file_hash_hi  : top 128 bits of sha256(TEST_FILE_CONTENT)
//   - file_hash_lo  : bottom 128 bits of sha256(TEST_FILE_CONTENT)
//   - commitment    : Poseidon(secret, fh_hi, fh_lo)
//
// Both secret and file content are fixed so the build pipeline is fully
// reproducible and the committed input.json always matches.

const fs = require("fs");
const path = require("path");
const { createHash } = require("crypto");
const { buildPoseidon } = require("circomlibjs");

const TEST_FILE_CONTENT = "etornie-file-ownership-test-vector-v1";
const SECRET = 1234567890123456789n;

async function main() {
  const poseidon = await buildPoseidon();
  const F = poseidon.F;

  const fileHash = createHash("sha256").update(TEST_FILE_CONTENT).digest();
  const fhHi = BigInt("0x" + fileHash.subarray(0, 16).toString("hex"));
  const fhLo = BigInt("0x" + fileHash.subarray(16, 32).toString("hex"));

  const hashElem = poseidon([SECRET, fhHi, fhLo]);
  const commitment = F.toObject(hashElem);

  const input = {
    secret: SECRET.toString(),
    file_hash_hi: fhHi.toString(),
    file_hash_lo: fhLo.toString(),
    commitment: commitment.toString(),
  };

  const outPath = path.join(__dirname, "input.json");
  fs.writeFileSync(outPath, JSON.stringify(input, null, 2) + "\n");

  console.log("wrote", outPath);
  console.log("sha256(file):", fileHash.toString("hex"));
  console.log("  fh_hi:", fhHi.toString());
  console.log("  fh_lo:", fhLo.toString());
  console.log("  commitment:", commitment.toString());
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
