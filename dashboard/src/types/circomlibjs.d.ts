// Minimal type surface for circomlibjs — only the Poseidon helpers the
// fileOwnership module calls. Expand as more APIs are consumed.

declare module "circomlibjs" {
  /** BN254 scalar field helpers exposed on `Poseidon.F`. */
  export interface PoseidonField {
    toObject(value: unknown): bigint;
    e(value: bigint | string | number): unknown;
  }

  /**
   * Poseidon hasher. Callable as a function: `poseidon(inputs)` returns
   * an opaque field element that must be read back via `poseidon.F.toObject`.
   */
  export interface Poseidon {
    (inputs: Array<bigint | string | number>): unknown;
    F: PoseidonField;
  }

  export function buildPoseidon(): Promise<Poseidon>;
}
