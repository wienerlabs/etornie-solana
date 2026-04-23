// Minimal type surface for the subset of snarkjs the ZK Lab page uses.
// snarkjs does not ship TS types. Expand this module as more APIs are
// consumed.

declare module "snarkjs" {
  export interface Groth16ProofOutput {
    proof: {
      pi_a: [string, string, string];
      pi_b: [[string, string], [string, string], [string, string]];
      pi_c: [string, string, string];
      protocol: string;
      curve: string;
    };
    publicSignals: string[];
  }

  export namespace groth16 {
    function fullProve(
      input: Record<string, string | number | bigint>,
      wasmPath: string,
      zkeyPath: string,
    ): Promise<Groth16ProofOutput>;

    function verify(
      vk: unknown,
      publicSignals: string[],
      proof: Groth16ProofOutput["proof"],
    ): Promise<boolean>;
  }
}
