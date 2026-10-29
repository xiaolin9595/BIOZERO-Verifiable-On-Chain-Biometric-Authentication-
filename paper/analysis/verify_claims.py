"""Check, on synthetic data, three technical claims made in the report.

C1  Shared response masks (single shared mask across coordinates) leak pairwise
    coordinate differences from public transcript values; independent masks (ISC
    specification, adopted here) do not.
C2  Reduced prototype group parameters give no binding: the discrete logarithm of h
    to base g is found with a few thousand group operations.
C3  A falsified, unsampled coordinate shifts the reconstructed distance commitment
    by an arbitrary amount, and the shift is known to the prover (toy group).

Everything is local and synthetic (researcher-owned prototype parameters only).
Usage: python -I analysis/verify_claims.py
"""
import hashlib
import json
import math
import os
import random
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "analysis", "out")
os.makedirs(OUT, exist_ok=True)
res = {}
rng = random.Random(20261027)  # fixed seed: results are reproducible

# --------------------------------------------------------------------- C1
# Example ranges (prove.js): m in [0,1000), b < 10000, e = SHA256(...) mod 5000.
BN254_R = 21888242871839275222246405745257275088548364400416034343698204186575808495617


def trial_shared(n=128):
    m = [rng.randrange(1000) for _ in range(n)]
    b = rng.randrange(10000)
    e = 0
    while e == 0:
        e = int.from_bytes(hashlib.sha256(str(rng.random()).encode()).digest(), "big") % 5000
    z = [b + e * mi for mi in m]                          # z_i = b + e m_i, one b for all i
    diffs = [(z[i] - z[0]) // e for i in range(n)]         # public z, e  ->  m_i - m_0
    ok = all(diffs[i] == m[i] - m[0] for i in range(n))
    lo, hi = min(diffs), max(diffs)
    offsets = [c for c in range(1000) if 0 <= lo + c and hi + c < 1000]  # values of m_0 consistent with range
    return ok, len(offsets), (m[0] in offsets)


def trial_fresh(n=128):
    m = [rng.randrange(1000) for _ in range(n)]
    e = rng.randrange(1, 2 ** 64)
    z = [(rng.randrange(BN254_R) + e * mi) % BN254_R for mi in m]   # independent uniform masks
    inv = pow(e, -1, BN254_R)
    guess = [((z[i] - z[0]) * inv) % BN254_R for i in range(n)]
    truth = [(m[i] - m[0]) % BN254_R for i in range(n)]
    return sum(g == t for g, t in zip(guess, truth)) / n


T = 1000
shared = [trial_shared() for _ in range(T)]
res["C1"] = {
    "trials": T, "N": 128,
    "shared_mask_all_differences_recovered": sum(s[0] for s in shared) / T,
    "shared_mask_candidate_offsets_median": sorted(s[1] for s in shared)[T // 2],
    "shared_mask_true_offset_in_candidates": sum(s[2] for s in shared) / T,
    "independent_masks_fraction_of_differences_recovered_mean": sum(trial_fresh() for _ in range(T)) / T,
}

# --------------------------------------------------------------------- C2
p, g, h_raw = 67108859, 56544564, 237684576
h = h_raw % p


def is_prime(n):
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True


def factor(n):
    f, d = {}, 2
    while d * d <= n:
        while n % d == 0:
            f[d] = f.get(d, 0) + 1
            n //= d
        d += 1
    if n > 1:
        f[n] = f.get(n, 0) + 1
    return f


def mul_order(a, p):
    n = p - 1
    o = n
    for q in factor(n):
        while o % q == 0 and pow(a, o // q, p) == 1:
            o //= q
    return o


def bsgs(g, h, p, order):
    m = math.isqrt(order) + 1
    table = {}
    cur = 1
    for j in range(m):
        table.setdefault(cur, j)
        cur = cur * g % p
    factor_ = pow(g, -m, p)
    gamma = h
    for i in range(m + 1):
        if gamma in table:
            return i * m + table[gamma], m
        gamma = gamma * factor_ % p
    return None, m


og = mul_order(g, p)
s, steps = bsgs(g, h, p, og)
assert s is not None and pow(g, s, p) == h
# equivocation: open c = g^m h^r also as (m', r')
mm, rr = 123, 4567
c = pow(g, mm, p) * pow(h, rr, p) % p
m2 = 456
r2 = (rr + (mm - m2) * pow(s, -1, og)) % og
assert pow(g, m2, p) * pow(h, r2, p) % p == c
res["C2"] = {
    "p": p, "p_bits": p.bit_length(), "p_is_prime": is_prime(p), "p_minus_1_factorization": factor(p - 1),
    "g": g, "h_mod_p": h, "order_of_g": og, "order_g_is_prime": is_prime(og) if og < 10**12 else None,
    "bsgs_table_size": steps, "log_g_h_found": True,
    "equivocation_opening_verified": True,
}

# --------------------------------------------------------------------- C3 (toy Schnorr group)
# subgroup of prime order q=1019 in Z_2039^*
P, Q = 2039, 1019
G = pow(2, (P - 1) // Q, P)
Hh = pow(G, 77, P)  # toy: known dlog; only the homomorphic algebra matters here


def com(x, r):
    return pow(G, x % Q, P) * pow(Hh, r % Q, P) % P


N3 = 8
m0 = [rng.randrange(20) for _ in range(N3)]
m1 = [rng.randrange(20) for _ in range(N3)]
r00 = [rng.randrange(Q) for _ in range(N3)]
r11 = [rng.randrange(Q) for _ in range(N3)]
r01 = [rng.randrange(Q) for _ in range(N3)]
c00 = [com(a * a, r) for a, r in zip(m0, r00)]
c11 = [com(b * b, r) for b, r in zip(m1, r11)]
c01 = [com(a * b, r) for a, b, r in zip(m0, m1, r01)]


def recon(c00, c11, c01):
    acc = 1
    for a, b, c in zip(c00, c11, c01):
        acc = acc * a % P * b % P * pow(c, -2 % Q, P) % P
    return acc


d = sum((a - b) ** 2 for a, b in zip(m0, m1))
rd = sum(a + b - 2 * c for a, b, c in zip(r00, r11, r01))
assert recon(c00, c11, c01) == com(d, rd)
# falsify coordinate j: multiply c01_j by g^delta h^rho; prover chooses delta so that d' = d - 2*delta
j, delta, rho = 3, 5, 11
c01_f = list(c01)
c01_f[j] = c01[j] * com(delta, rho) % P
cd_new = recon(c00, c11, c01_f)
assert cd_new == com(d - 2 * delta, rd - 2 * rho)   # opens to a value the prover knows
res["C3"] = {"toy_group": [P, Q], "single_coordinate_shift_verified": True, "shift": -2 * delta}

# ------------------------------------------------------- FEI aggregate results
FEI_SPECS = (
    ("fei-mobilefacenet128-shared512.json", ("float", "4-bit", "6-bit", "8-bit", "12-bit"), 5935),
    ("fei-inceptionresnetv1-vggface2-512.json", ("float", "4-bit", "6-bit", "7-bit", "9-bit"), 5921),
)
SHARED_SPLIT_SHA256 = "0ee30180179be78cba85f2a5a38835fd1de6c7306925cff1fcf39d6dc76b1271"
SHARED_VALIDATION_PAIRS_SHA256 = "7fa08349c23a822d8d79c06c8e6fd8d46d6eae3136bb74e919cea7bdffbb0446"
SHARED_TEST_PAIRS_SHA256 = "50690dd559119c51563f083f1b515ed20e26ca3c6ca03858f2fa8954f9899a23"


def verify_fei_result(data: dict, expected_settings: tuple, expected_test_pairs: int) -> dict:
    protocol = data["protocol"]
    assert data["dataset"] == "FEI Face Database"
    assert protocol["identity_split"] == {
        "validation_identities": 40,
        "test_identities": 160,
        "sha256": SHARED_SPLIT_SHA256,
    }
    assert protocol["validation_pairs"]["manifest_sha256"] == SHARED_VALIDATION_PAIRS_SHA256
    assert protocol["test_pairs"]["manifest_sha256"] == SHARED_TEST_PAIRS_SHA256
    assert protocol["validation_pairs"]["eligible"] == 5857
    assert protocol["test_pairs"]["eligible"] == expected_test_pairs
    assert "float-validation" in protocol["threshold_policy"]
    assert [row["setting"] for row in data["settings"]] == list(expected_settings)
    assert len(data["source"]["results_sha256"]) == 64
    assert len(data["source"]["embeddings_sha256"]) == 64

    genuine = protocol["test_pairs"]["eligible_genuine"]
    impostor = protocol["test_pairs"]["eligible_impostor"]
    assert genuine + impostor == expected_test_pairs
    for row in data["settings"]:
        counts = row["counts"]
        metrics = row["metrics"]
        assert counts["tp"] + counts["fn"] == genuine
        assert counts["tn"] + counts["fp"] == impostor
        recomputed = {
            "accuracy": (counts["tp"] + counts["tn"]) / expected_test_pairs,
            "recall": counts["tp"] / genuine,
            "far": counts["fp"] / impostor,
            "frr": counts["fn"] / genuine,
        }
        for name, value in recomputed.items():
            assert math.isclose(value, metrics[name], rel_tol=0.0, abs_tol=1e-15), (
                data["model"]["source_name"], row["setting"], name, value, metrics[name]
            )
        assert 0.0 <= metrics["auc"] <= 1.0

    return {
        "model": data["model"]["source_name"],
        "float_validation_threshold": protocol["float_validation_threshold"],
        "validation_eligible_pairs": protocol["validation_pairs"]["eligible"],
        "test_eligible_pairs": expected_test_pairs,
        "settings": list(expected_settings),
        "counts_and_metrics_recomputed": True,
    }


res["FEI"] = {}
for filename, expected_settings, expected_test_pairs in FEI_SPECS:
    with open(os.path.join(ROOT, "data", filename), encoding="utf-8") as handle:
        fei_data = json.load(handle)
    res["FEI"][filename] = verify_fei_result(fei_data, expected_settings, expected_test_pairs)

# ----------------------------------------- harmonized LFW aggregate results
LFW_SPECS = (
    {
        "filename": "lfw-mobilefacenet128-harmonized.json",
        "settings": ("float", "4-bit", "6-bit", "8-bit", "12-bit"),
        "primes": {"4-bit": 13, "6-bit": 61, "8-bit": 251, "12-bit": 4093},
        "dimension": 128,
        "coverage": (13233, 13185),
        "validation_pairs": (5980, 2996, 2984),
        "test_pairs": (5949, 2975, 2974),
        "eligible_hashes": {
            "validation": "3087241fca9eb51beccfa97e0c592974dd47d80c4e82c8f817d88af854235680",
            "test": "3ed297016b0ddae9b94d30bf849604bfd1cd9608f098b4c792a37fbfbaa9a465",
        },
        "source_sha256": "2b44226846939f24c90eff50ae9bb781d761238d3f24e6d18e39811304546a24",
        "verification_sha256": "0ae94b8628a379eb552bfa1110735c65424be97660d4a1413d9bb08312ebca05",
    },
    {
        "filename": "lfw-inceptionresnetv1-vggface2-harmonized.json",
        "settings": ("float", "4-bit", "6-bit", "7-bit", "9-bit"),
        "primes": {"4-bit": 13, "6-bit": 61, "7-bit": 127, "9-bit": 509},
        "dimension": 512,
        "coverage": (13233, 13233),
        "validation_pairs": (6000, 3000, 3000),
        "test_pairs": (6000, 3000, 3000),
        "eligible_hashes": {
            "validation": "8e05053ab7478bf0f5fa2c35e2a36564b1ab25f17dfb0409d04ceb123c430e34",
            "test": "50d025627b238f3db3dcbd6cbb8ff100299937b17339517204b6883049c7efbe",
        },
        "source_sha256": "0129e9d1cf1e12a54d8708a1cb7b710465196210a891852cce5117117eef4eae",
        "verification_sha256": "74a9c0d0b093451a24e8a9becdee72788a93e20361443473327cb7e6a986ecb0",
    },
)
LFW_HASHES = {
    "archive": "b47c8422c8cded889dc5a13418c4bc2abbda121092b3533a83306f90d900100a",
    "images": "05ce4d46b8abe25b3000abc2aaf70255b034df49999cda2d6f9d768147aa9e6e",
    "split": "b11b53178b1b906d4ff909c3657369489cdfd9c9d6fd8fb5b676f2374aa25ca8",
    "validation_pairs": "acaaf51de15e80b7c427ca98a407bdc8006669b1401702f453c53859fef457da",
    "test_pairs": "0fd863e32ae59f19baa8b3bd00092f7a0887f38f6fa05700d2843540278bcef2",
}


def verify_lfw_result(data: dict, spec: dict) -> dict:
    """Recompute the LFW aggregate invariants without importing the table code."""
    assert data["schema_version"] == "biozero-lfw-harmonized-aggregate-v1"
    assert data["source_result_sha256"] == spec["source_sha256"]
    assert data["verification_sha256"] == spec["verification_sha256"]
    assert data["verification"]["status"] == "PASS"
    assert data["verification"]["all_metric_and_paired_delta_ci95_recomputed"] is True
    assert data["qualification"] == (
        "Harmonized identity-disjoint LFW evaluation; not official LFW 10-fold "
        "and not historical-number reproduction."
    )
    dataset = data["dataset"]
    assert dataset["name"] == "LFW Funneled"
    assert dataset["acquisition_condition"] == "unconstrained"
    assert dataset["archive_sha256"] == LFW_HASHES["archive"]
    assert dataset["image_manifest_sha256"] == LFW_HASHES["images"]

    model = data["model"]
    assert model["embedding_dimension"] == spec["dimension"]
    coverage = model["coverage"]
    assert (coverage["attempted"], coverage["successful"]) == spec["coverage"]
    assert math.isclose(coverage["rate"], coverage["successful"] / coverage["attempted"],
                        rel_tol=0.0, abs_tol=1e-15)

    split = data["split"]
    assert split["identity_counts"] == {"all": 5749, "test": 4600, "validation": 1149}
    assert split["identity_intersection_count"] == 0
    assert split["identity_split_sha256"] == LFW_HASHES["split"]
    assert split["policy"] == (
        "SHA256 domain order; floor(0.2*N) validation, remainder test; all identities retained"
    )
    for part in ("validation", "test"):
        assert split["pair_sampling"][part]["sampling_estimand"] == (
            "global-uniform unordered image-pair; image-pair weighted, not identity-balanced"
        )

    protocol = data["pair_protocol"]
    assert protocol["predetection_fixed"] is True
    assert protocol["no_replacement_after_failure"] is True
    assert protocol["same_eligible_pairs_all_settings"] is True
    assert protocol["validation_manifest_sha256"] == LFW_HASHES["validation_pairs"]
    assert protocol["test_manifest_sha256"] == LFW_HASHES["test_pairs"]
    for part, expected in (("validation", spec["validation_pairs"]), ("test", spec["test_pairs"])):
        availability = protocol[f"{part}_availability"]
        assert availability["requested"] == 6000
        assert availability["requested_genuine"] == 3000
        assert availability["requested_impostor"] == 3000
        assert (
            availability["available"], availability["available_genuine"],
            availability["available_impostor"],
        ) == expected
        assert availability["available"] == (
            availability["available_genuine"] + availability["available_impostor"]
        )
        assert math.isclose(availability["rate"], availability["available"] / 6000,
                            rel_tol=0.0, abs_tol=1e-15)
        assert availability["ordered_eligible_pair_ids_sha256"] == spec["eligible_hashes"][part]

    threshold = data["threshold"]
    assert threshold["comparison"] == "distance < threshold"
    assert threshold["test_used_for_selection"] is False
    assert threshold["policy"] == (
        "float validation maximum balanced accuracy; frozen unchanged for every bit width"
    )
    bootstrap = data["bootstrap"]
    assert bootstrap["replicates_requested"] == 2000
    assert bootstrap["replicates_accepted"] == 2000
    assert bootstrap["replicates_discarded_single_class"] == 0
    assert bootstrap["paired_delta"] == "setting minus float within each accepted replicate"

    rows = data["settings"]
    assert [row["setting"] for row in rows] == list(spec["settings"])
    float_metrics = rows[0]["metrics"]
    eligible, genuine, impostor = spec["test_pairs"]
    for row in rows:
        setting = row["setting"]
        expected_prime = None if setting == "float" else spec["primes"][setting]
        assert row["prime"] == expected_prime
        if setting != "float":
            assert data["quantizer"]["primes"][setting] == expected_prime
        assert math.isclose(row["threshold_normalized_distance"], threshold["float_threshold"],
                            rel_tol=0.0, abs_tol=1e-15)
        counts = row["counts"]
        metrics = row["metrics"]
        assert counts["tp"] + counts["fn"] == genuine
        assert counts["tn"] + counts["fp"] == impostor
        expected_metrics = {
            "accuracy": (counts["tp"] + counts["tn"]) / eligible,
            "recall": counts["tp"] / genuine,
            "far": counts["fp"] / impostor,
            "frr": counts["fn"] / genuine,
        }
        for metric, expected_value in expected_metrics.items():
            assert math.isclose(metrics[metric], expected_value, rel_tol=0.0, abs_tol=1e-15)
        assert math.isclose(metrics["frr"], 1.0 - metrics["recall"],
                            rel_tol=0.0, abs_tol=1e-15)
        assert 0.0 <= metrics["auc"] <= 1.0
        metric_ci = row["ci95_identity_cluster"]
        assert set(metric_ci) == {"accuracy", "auc", "far", "frr", "recall"}
        assert all(interval["low"] <= interval["high"] for interval in metric_ci.values())
        if setting == "float":
            assert row["delta_vs_float"] is None
            assert row["delta_vs_float_ci95_identity_cluster"] is None
        else:
            delta = row["delta_vs_float"]
            delta_ci = row["delta_vs_float_ci95_identity_cluster"]
            assert set(delta) == set(float_metrics)
            assert set(delta_ci) == set(float_metrics)
            for metric, float_value in float_metrics.items():
                assert math.isclose(delta[metric], metrics[metric] - float_value,
                                    rel_tol=0.0, abs_tol=2e-15)
                assert delta_ci[metric]["low"] <= delta_ci[metric]["high"]

    return {
        "model": model["source_name"],
        "source_result_sha256": data["source_result_sha256"],
        "verification_sha256": data["verification_sha256"],
        "float_validation_threshold": threshold["float_threshold"],
        "image_coverage": coverage,
        "validation_eligible_pairs": spec["validation_pairs"][0],
        "test_eligible_pairs": eligible,
        "settings": list(spec["settings"]),
        "bootstrap_replicates": bootstrap["replicates_accepted"],
        "counts_metrics_deltas_and_ci_recomputed": True,
    }


res["LFW"] = {}
for spec in LFW_SPECS:
    with open(os.path.join(ROOT, "data", spec["filename"]), encoding="utf-8") as handle:
        lfw_data = json.load(handle)
    res["LFW"][spec["filename"]] = verify_lfw_result(lfw_data, spec)

json.dump(res, open(os.path.join(OUT, "verify_claims.json"), "w", encoding="utf-8"), indent=1)
print(json.dumps(res, indent=1))
