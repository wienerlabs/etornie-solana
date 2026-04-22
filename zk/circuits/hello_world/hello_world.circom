pragma circom 2.0.0;

// Hello-world circuit. Proves knowledge of two factors a and b such that
// their product equals the public signal c, without revealing a or b.
//
// Purpose: smoke-test the full Circom + snarkjs pipeline end-to-end.
// Compile -> powers of tau -> phase2 zkey -> witness -> prove -> verify.
template Multiplier2() {
    signal input a;
    signal input b;
    signal output c;

    c <== a * b;
}

// In circom, main component inputs are private by default unless listed
// under {public [...]}. Here a and b stay private; c is an output so it
// is always public.
component main = Multiplier2();
