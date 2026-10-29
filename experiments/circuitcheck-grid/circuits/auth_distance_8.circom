pragma circom 2.2.3;

include "./auth_distance.circom";

component main {public [cEnroll, cProbe, policyDigest, ctxHash, epsilon]} =
    AuthDistance(8, 16, 65535, 15, 1, 2, 48);
