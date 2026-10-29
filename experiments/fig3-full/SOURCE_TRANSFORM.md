# Vanilla source transform

All recovered Vanilla circuits N=2,4,8,16,32,64,128 declare public `res` and
then shadow it with a local all-zero array. Honest Pedersen commitments cannot
pass that recovered source unchanged. The fresh campaign therefore uses the
same minimal repair as the earlier reconstructed experiment: remove exactly
the single local declaration

```zokrates
u64[2 * N] mut res = [0; 2 * N];
```

inside `main`, preserving the public `res` argument and every remaining
statement. Remote `diff -u` checks found no other semantic change for any of
the seven dimensions. The original recovered source remains unchanged.

Every accepted target records both the original source hash and the generated
fixed-source hash. This is a reconstructed, bug-fixed execution of the old
experiment semantics; it is not a claim that the missing original Fig. 3 raw
data or keys were recovered from the 2024 repository.

