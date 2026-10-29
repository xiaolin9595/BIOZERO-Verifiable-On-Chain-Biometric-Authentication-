// RECONSTRUCTED, not recovered original source.
// The generic AuthDistance signature and generate-inputs.mjs unambiguously specify
// packSize=1, one block per coordinate, and an even padded block count.
pragma circom 2.2.3;

include "../auth_distance.circom";

component main {public [cEnroll, cProbe, policyDigest, ctxHash, epsilon]} =
    AuthDistance(128, 16, 65535, 1, 128, 128, 48);
