"""Generate every table and number in the report from the raw measurement files.

Usage (from BioZERO_TR_v3/):  python -I analysis/make_tables.py
Inputs : data/*.json measurement and aggregate FEI result files.
Outputs: analysis/out/*.tex  (included by the report)  and analysis/out/numbers.json

Nothing here is measured; the script only reads recorded measurements and
evaluates closed-form expressions (hypergeometric acceptance probabilities).
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "analysis", "out")
os.makedirs(OUT, exist_ok=True)

ped = json.load(open(os.path.join(ROOT, "data", "pedersen-bn254-gas.json"), encoding="utf-8"))
ra = json.load(open(os.path.join(ROOT, "data", "routea-verifier-gas.json"), encoding="utf-8"))

N = ped["dimension"]
assert N == 128
rows = {r["label"]: r for r in ped["results"]}
recon = rows["reconstruction-only"]
base_gas = recon["medianGasUsed"]


def fmt(x):
    return f"{x:,}".replace(",", "{,}")


def blue(value):
    """Mark values updated or reconfirmed by the dated reproduction evidence."""
    return r"\textcolor{blue}{" + str(value) + "}"


# ---------------------------------------------------------------- acceptance
def pass_prob(n, t, w):
    """Probability that t distinct uniformly sampled indices avoid all w falsified ones."""
    if w == 0:
        return 1.0
    if t > n - w:
        return 0.0
    return math.comb(n - w, t) / math.comb(n, t)


T_OF = {"lambda-1": 7, "lambda-2": 14, "lambda-4": 28, "lambda-8": 56, "full-check": 128}
for k, t in T_OF.items():
    assert rows[k]["samples"] == t, (k, rows[k]["samples"], t)
    # cross-check the stored one-bad-coordinate detection value against the closed form
    assert abs(rows[k]["oneBadCoordinateDetection"] - (1 - pass_prob(N, t, 1))) < 1e-12

W_LIST = [1, 2, 6, 13]
lines = [
    r"\begin{tabular}{lrrrrr}", r"\toprule",
    r"Strategy & $t$ & $w{=}1$ & $w{=}2$ & $w{=}6$ & $w{=}13$ \\", r"\midrule",
]
names = {"lambda-1": r"\textsc{SpotCheck}, $\eta{=}1$", "lambda-2": r"\textsc{SpotCheck}, $\eta{=}2$",
         "lambda-4": r"\textsc{SpotCheck}, $\eta{=}4$", "lambda-8": r"\textsc{SpotCheck}, $\eta{=}8$",
         "full-check": r"\textsc{FullCheck}"}
numbers = {"accept_prob": {}}
for k, t in T_OF.items():
    ps = [pass_prob(N, t, w) for w in W_LIST]
    numbers["accept_prob"][k] = {str(w): p for w, p in zip(W_LIST, ps)}
    cells = " & ".join(f"{100*p:.2f}\\%" for p in ps)
    lines.append(f"{names[k]} & {t} & {cells} \\\\")
lines += [r"\bottomrule", r"\end{tabular}"]
open(os.path.join(OUT, "tab_accept.tex"), "w", encoding="utf-8").write("\n".join(lines) + "\n")

# attempts: success within k independent attempts, w = 1 and w = 6
attempt_lines = [r"\begin{tabular}{lrrrr}", r"\toprule",
                 r"Strategy & $k{=}1$ & $k{=}2$ & $k{=}5$ & $k{=}10$ \\", r"\midrule"]
numbers["attempts"] = {}
for k, w in (("lambda-8", 1), ("lambda-8", 6), ("lambda-4", 6), ("lambda-1", 6)):
    p = pass_prob(N, T_OF[k], w)
    vals = [1 - (1 - p) ** a for a in (1, 2, 5, 10)]
    numbers["attempts"][f"{k}_w{w}"] = vals
    attempt_lines.append(f"{names[k]}, $w{{=}}{w}$ & " + " & ".join(f"{100*v:.1f}\\%" for v in vals) + r" \\")
attempt_lines += [r"\bottomrule", r"\end{tabular}"]
open(os.path.join(OUT, "tab_attempts.tex"), "w", encoding="utf-8").write("\n".join(attempt_lines) + "\n")

# ---------------------------------------------------------------- gas, N = 128
def per_sample(k):
    return (rows[k]["medianGasUsed"] - base_gas) / rows[k]["samples"]

gas_lines = [
    r"\begin{tabular}{lrrrr}", r"\toprule",
    r"Strategy & $t$ & Tx gas & Calldata (B) & Gas/coord. \\", r"\midrule",
]
numbers["gas"] = {}
gas_lines.append(f"Reconstruction only & 0 & {fmt(base_gas)} & {fmt(recon['calldata']['bytes'])} & -- \\\\")
numbers["gas"]["reconstruction-only"] = base_gas
for k in ("lambda-1", "lambda-2", "lambda-4", "lambda-8", "full-check"):
    r = rows[k]
    ps = per_sample(k)
    numbers["gas"][k] = {"gas": r["medianGasUsed"], "calldata": r["calldata"]["bytes"], "per_sample": ps}
    gas_lines.append(f"{names[k]} & {r['samples']} & {fmt(r['medianGasUsed'])} & {fmt(r['calldata']['bytes'])} & {fmt(round(ps))} \\\\")
gas_lines += [r"\bottomrule", r"\end{tabular}"]
open(os.path.join(OUT, "tab_gas_pedersen.tex"), "w", encoding="utf-8").write("\n".join(gas_lines) + "\n")

# ---------------------------------------------------------------- Route A verifier
rv = {r["dimension"]: r for r in ra["results"]}
assert rv[128]["verification"]["medianGasUsed"] == rv[512]["verification"]["medianGasUsed"]
numbers["routea"] = {
    "verify_gas": rv[128]["verification"]["medianGasUsed"],
    "verify_exec_gas": rv[128]["verification"]["medianExecutionGasAfterIntrinsic"],
    "calldata_bytes": rv[128]["calldata"]["bytes"],
    "public_inputs": rv[128]["publicInputs"],
    "deploy_gas": rv[128]["deployment"]["gasUsed"],
}

# ---------------------------------------------------------------- complete verifiers, N = 128
# Spot rows come from the dedicated enine sweep; Full comes from the earlier
# enine COMPLETE campaign. CircuitCheck and packed/ablation measurements come
# from the later enine r4 campaign. Only the dated enine inputs are read here.
hom = json.load(open(os.path.join(
    ROOT, "data", "hom-complete-enine-2026-10-28.json"), encoding="utf-8"))
spot = json.load(open(os.path.join(
    ROOT, "data", "spotcheck-n-sweep-enine-2026-10-28.json"), encoding="utf-8"))
circ = json.load(open(os.path.join(
    ROOT, "data", "circuit-complete-enine-2026-10-28.json"), encoding="utf-8"))
prv = json.load(open(os.path.join(
    ROOT, "data", "packed-proving-enine-2026-10-28.json"), encoding="utf-8"))
abl = json.load(open(os.path.join(
    ROOT, "data", "reconstructed-unpacked-ablation-enine-2026-10-28.json"), encoding="utf-8"))
assert hom["dimension"] == N
full = next(r for r in hom["results"] if r["samples"] == N)
spot128 = [r for r in spot["results"] if r["dimension"] == N]
assert {r["eta"] for r in spot128} == {1, 2, 4, 8}
hrows = {
    r["samples"]: {
        "medianGasUsed": r["medianGasUsed"],
        "calldata": {"bytes": r["medianCalldataBytes"]},
        "controls": r["controls"],
        "enrollmentGas": r["enrollmentGas"],
    }
    for r in spot128
}
hrows[N] = full
crows = {r["dimension"]: r for r in circ["results"]}
for c in crows.values():
    assert c["controls"]["replayRejected"] is True
    assert c["controls"]["wrongNonceProofRejected"] is True
c128 = crows[128]["medianGasUsed"]
KEY_OF_T = {7: "lambda-1", 14: "lambda-2", 28: "lambda-4", 56: "lambda-8", 128: "full-check"}
complete_lines = [
    r"\begin{tabular}{lrrrrr}", r"\toprule",
    r"Strategy & $t$ & Complete tx gas & Calldata (B) & Kernel gas & ${}\div{}$\textsc{Circ} \\", r"\midrule",
]
numbers["complete"] = {}
for t, k in KEY_OF_T.items():
    h = hrows[t]
    assert all(h["controls"][c] is True for c in
               ("replayRejected", "staleProofRejected", "wrongEnrollmentRejected"))
    # The dedicated sweep actively exercised tampering for sampled rows.
    assert h["controls"]["tamperedResponseRejected"] is True
    numbers["complete"][k] = {"gas": h["medianGasUsed"], "calldata": h["calldata"]["bytes"],
                              "kernel": rows[k]["medianGasUsed"], "ratio_circ": h["medianGasUsed"] / c128}
    ratio = f"{h['medianGasUsed'] / c128:.1f}" + r"$\times$"
    complete_lines.append(
        f"{names[k]} & {blue(t)} & {blue(fmt(h['medianGasUsed']))} & "
        f"{blue(fmt(h['calldata']['bytes']))} & {blue(fmt(rows[k]['medianGasUsed']))} & "
        f"{blue(ratio)} \\\\")
circuit_ratio = r"1.0$\times$"
complete_lines.append(
    f"\\textsc{{CircuitCheck}} & -- & {blue(fmt(c128))} & "
    f"{blue(fmt(crows[128]['calldata']['bytes']))} & -- & {blue(circuit_ratio)} \\\\")
complete_lines += [r"\bottomrule", r"\end{tabular}"]
open(os.path.join(OUT, "tab_gas_complete.tex"), "w", encoding="utf-8").write("\n".join(complete_lines) + "\n")
numbers["complete"]["circuit"] = {d: {"gas": crows[d]["medianGasUsed"], "calldata": crows[d]["calldata"]["bytes"],
                                      "enroll": crows[d]["enrollmentGas"]} for d in (128, 512)}
numbers["complete"]["hom_enroll"] = hrows[128]["enrollmentGas"]
marg = (hrows[128]["medianGasUsed"] - hrows[7]["medianGasUsed"]) / (128 - 7)
numbers["complete"]["marginal_per_coordinate"] = marg

# CircuitCheck table: complete transaction, proving, and reconstructed-unpacked
# ablation from the dated enine r4 campaign.
pr = {r["circuit"]: r for r in prv["results"]}
p128, p512 = pr["auth_distance_128"], pr["auth_distance_512"]
ar = {r["dimension"]: r for r in abl["results"]}
for d, p in ((128, p128), (512, p512)):
    assert ar[d]["packedConstraints"] == p["constraints"]
    assert ar[d]["witnessChecked"] is True
mib = lambda r: r["proof"]["medianProcessMaxRssMiB"]


def pct(x: float) -> str:
    return format(x, ".1f") + r"\%"
circ_lines = [
    r"\begin{tabular}{lrr}", r"\toprule", r" & $N{=}128$ & $N{=}512$ \\", r"\midrule",
    f"Constraints (packed) & {blue(fmt(p128['constraints']))} & {blue(fmt(p512['constraints']))} \\\\",
    f"Authentication, tx gas & {blue(fmt(crows[128]['medianGasUsed']))} & {blue(fmt(crows[512]['medianGasUsed']))} \\\\",
    f"\\quad Groth16 verifier alone & {blue(fmt(rv[128]['verification']['medianGasUsed']))} & {blue(fmt(rv[512]['verification']['medianGasUsed']))} \\\\",
    f"Enrollment, tx gas & {blue(fmt(crows[128]['enrollmentGas']))} & {blue(fmt(crows[512]['enrollmentGas']))} \\\\",
    f"Calldata (B) & {blue(fmt(crows[128]['calldata']['bytes']))} & {blue(fmt(crows[512]['calldata']['bytes']))} \\\\",
    f"Witness, median (ms) & {blue(format(p128['witness']['medianElapsedMs'], '.2f'))} & {blue(format(p512['witness']['medianElapsedMs'], '.2f'))} \\\\",
    f"Prove, median (ms) & {blue(format(p128['proof']['medianElapsedMs'], '.2f'))} & {blue(format(p512['proof']['medianElapsedMs'], '.2f'))} \\\\",
    f"Verify, median (ms) & {blue(format(p128['verification']['medianElapsedMs'], '.2f'))} & {blue(format(p512['verification']['medianElapsedMs'], '.2f'))} \\\\",
    f"Prove max-RSS, median (MiB) & {blue(format(mib(p128), '.2f'))} & {blue(format(mib(p512), '.2f'))} \\\\",
    f"Constraints (reconstructed unpacked) & {blue(fmt(ar[128]['constraints']))} & {blue(fmt(ar[512]['constraints']))} \\\\",
    f"Packed constraint reduction & {blue(pct(ar[128]['packedReductionPercent']))} & {blue(pct(ar[512]['packedReductionPercent']))} \\\\",
    r"\bottomrule", r"\end{tabular}",
]
open(os.path.join(OUT, "tab_circ.tex"), "w", encoding="utf-8").write("\n".join(circ_lines) + "\n")
numbers["ratio_full_vs_circuit"] = hrows[128]["medianGasUsed"] / c128
numbers["ratio_spot1_vs_circuit"] = hrows[7]["medianGasUsed"] / c128

json.dump(numbers, open(os.path.join(OUT, "numbers.json"), "w", encoding="utf-8"), indent=1)
sys.stdout.reconfigure(encoding="utf-8")
print(json.dumps(numbers, indent=1))

# ---------------------------------------------------------------- quantization (identity-disjoint FEI and LFW)
FEI_FILES = (
    "fei-mobilefacenet128-shared512.json",
    "fei-inceptionresnetv1-vggface2-512.json",
)
LFW_SPECS = (
    {
        "filename": "lfw-mobilefacenet128-harmonized.json",
        "settings": ("float", "4-bit", "6-bit", "8-bit", "12-bit"),
        "primes": {"4-bit": 13, "6-bit": 61, "8-bit": 251, "12-bit": 4093},
        "dimension": 128,
        "coverage": (13233, 13185),
        "validation_pairs": (5980, 2996, 2984),
        "test_pairs": (5949, 2975, 2974),
        "eligible_hashes": (
            "3087241fca9eb51beccfa97e0c592974dd47d80c4e82c8f817d88af854235680",
            "3ed297016b0ddae9b94d30bf849604bfd1cd9608f098b4c792a37fbfbaa9a465",
        ),
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
        "eligible_hashes": (
            "8e05053ab7478bf0f5fa2c35e2a36564b1ab25f17dfb0409d04ceb123c430e34",
            "50d025627b238f3db3dcbd6cbb8ff100299937b17339517204b6883049c7efbe",
        ),
        "source_sha256": "0129e9d1cf1e12a54d8708a1cb7b710465196210a891852cce5117117eef4eae",
        "verification_sha256": "74a9c0d0b093451a24e8a9becdee72788a93e20361443473327cb7e6a986ecb0",
    },
)
LFW_ARCHIVE_SHA256 = "b47c8422c8cded889dc5a13418c4bc2abbda121092b3533a83306f90d900100a"
LFW_IMAGE_MANIFEST_SHA256 = "05ce4d46b8abe25b3000abc2aaf70255b034df49999cda2d6f9d768147aa9e6e"
LFW_IDENTITY_SPLIT_SHA256 = "b11b53178b1b906d4ff909c3657369489cdfd9c9d6fd8fb5b676f2374aa25ca8"
LFW_VALIDATION_MANIFEST_SHA256 = "acaaf51de15e80b7c427ca98a407bdc8006669b1401702f453c53859fef457da"
LFW_TEST_MANIFEST_SHA256 = "0fd863e32ae59f19baa8b3bd00092f7a0887f38f6fa05700d2843540278bcef2"


def validate_lfw_result(data, spec):
    """Validate the publication aggregate independently of its source verifier."""
    assert data["schema_version"] == "biozero-lfw-harmonized-aggregate-v1"
    assert data["source_result_sha256"] == spec["source_sha256"]
    assert data["verification_sha256"] == spec["verification_sha256"]
    assert data["verification"] == {
        "status": "PASS",
        "all_metric_and_paired_delta_ci95_recomputed": True,
    }
    assert data["qualification"] == (
        "Harmonized identity-disjoint LFW evaluation; not official LFW 10-fold "
        "and not historical-number reproduction."
    )
    dataset = data["dataset"]
    assert dataset["name"] == "LFW Funneled"
    assert dataset["acquisition_condition"] == "unconstrained"
    assert dataset["archive_sha256"] == LFW_ARCHIVE_SHA256
    assert dataset["image_manifest_sha256"] == LFW_IMAGE_MANIFEST_SHA256
    assert data["model"]["embedding_dimension"] == spec["dimension"]
    coverage = data["model"]["coverage"]
    assert (coverage["attempted"], coverage["successful"]) == spec["coverage"]
    assert math.isclose(
        coverage["rate"], coverage["successful"] / coverage["attempted"],
        rel_tol=0.0, abs_tol=1e-15,
    )

    split = data["split"]
    assert split["identity_counts"] == {"all": 5749, "test": 4600, "validation": 1149}
    assert split["identity_intersection_count"] == 0
    assert split["identity_split_sha256"] == LFW_IDENTITY_SPLIT_SHA256
    assert split["policy"] == (
        "SHA256 domain order; floor(0.2*N) validation, remainder test; all identities retained"
    )
    for part in ("validation", "test"):
        assert split["pair_sampling"][part]["sampling_estimand"] == (
            "global-uniform unordered image-pair; image-pair weighted, not identity-balanced"
        )

    pairs = data["pair_protocol"]
    assert pairs["predetection_fixed"] is True
    assert pairs["no_replacement_after_failure"] is True
    assert pairs["same_eligible_pairs_all_settings"] is True
    assert pairs["validation_manifest_sha256"] == LFW_VALIDATION_MANIFEST_SHA256
    assert pairs["test_manifest_sha256"] == LFW_TEST_MANIFEST_SHA256
    for part, expected, expected_hash in (
        ("validation", spec["validation_pairs"], spec["eligible_hashes"][0]),
        ("test", spec["test_pairs"], spec["eligible_hashes"][1]),
    ):
        availability = pairs[f"{part}_availability"]
        assert availability["requested"] == 6000
        assert availability["requested_genuine"] == 3000
        assert availability["requested_impostor"] == 3000
        assert (
            availability["available"], availability["available_genuine"],
            availability["available_impostor"],
        ) == expected
        assert availability["available_genuine"] + availability["available_impostor"] == availability["available"]
        assert math.isclose(availability["rate"], availability["available"] / 6000,
                            rel_tol=0.0, abs_tol=1e-15)
        assert availability["ordered_eligible_pair_ids_sha256"] == expected_hash

    threshold = data["threshold"]
    assert threshold["policy"] == (
        "float validation maximum balanced accuracy; frozen unchanged for every bit width"
    )
    assert threshold["test_used_for_selection"] is False
    assert threshold["comparison"] == "distance < threshold"
    assert data["bootstrap"]["replicates_requested"] == 2000
    assert data["bootstrap"]["replicates_accepted"] == 2000
    assert data["bootstrap"]["replicates_discarded_single_class"] == 0
    assert data["bootstrap"]["paired_delta"] == (
        "setting minus float within each accepted replicate"
    )

    settings = data["settings"]
    assert [row["setting"] for row in settings] == list(spec["settings"])
    float_metrics = settings[0]["metrics"]
    eligible = pairs["test_availability"]["available"]
    genuine = pairs["test_availability"]["available_genuine"]
    impostor = pairs["test_availability"]["available_impostor"]
    for row in settings:
        setting = row["setting"]
        expected_prime = None if setting == "float" else spec["primes"][setting]
        assert row["prime"] == expected_prime
        assert data["quantizer"]["primes"].get(setting) == expected_prime or setting == "float"
        assert math.isclose(row["threshold_normalized_distance"], threshold["float_threshold"],
                            rel_tol=0.0, abs_tol=1e-15)
        counts = row["counts"]
        metrics = row["metrics"]
        assert counts["tp"] + counts["fn"] == genuine
        assert counts["tn"] + counts["fp"] == impostor
        recomputed = {
            "accuracy": (counts["tp"] + counts["tn"]) / eligible,
            "recall": counts["tp"] / genuine,
            "far": counts["fp"] / impostor,
            "frr": counts["fn"] / genuine,
        }
        for metric, value in recomputed.items():
            assert math.isclose(metrics[metric], value, rel_tol=0.0, abs_tol=1e-15)
        assert math.isclose(metrics["frr"], 1.0 - metrics["recall"],
                            rel_tol=0.0, abs_tol=1e-15)
        assert 0.0 <= metrics["auc"] <= 1.0
        ci = row["ci95_identity_cluster"]
        assert set(ci) == {"accuracy", "auc", "far", "frr", "recall"}
        for interval in ci.values():
            assert interval["low"] <= interval["high"]
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


fei_results = [
    json.load(open(os.path.join(ROOT, "data", name), encoding="utf-8"))
    for name in FEI_FILES
]
lfw_results = []
for spec in LFW_SPECS:
    with open(os.path.join(ROOT, "data", spec["filename"]), encoding="utf-8") as handle:
        result = json.load(handle)
    validate_lfw_result(result, spec)
    lfw_results.append(result)


def table_rows(result, dataset_kind):
    if dataset_kind == "FEI":
        settings = result["settings"]
        pairs_n = result["protocol"]["test_pairs"]["eligible"]
    else:
        settings = result["settings"]
        pairs_n = result["pair_protocol"]["test_availability"]["available"]
    float_accuracy = settings[0]["metrics"]["accuracy"]
    for row in settings:
        metrics = row["metrics"]
        delta = metrics["accuracy"] - float_accuracy
        delta_cell = "--" if row["setting"] == "float" else f"{100 * delta:+.2f}"
        yield [
            result["model"]["display_name"],
            row["setting"],
            fmt(pairs_n),
            f"{100 * metrics['accuracy']:.2f}",
            delta_cell,
            f"{100 * metrics['recall']:.2f}",
            f"{100 * metrics['far']:.2f}",
            f"{100 * metrics['frr']:.2f}",
            f"{metrics['auc']:.5f}",
        ]


ql = [
    r"\begin{tabular}{@{}llrrrrrrr@{}}",
    r"\toprule",
    " & ".join(blue(cell) for cell in
               ("Model", "Setting", "Pairs", "Acc.", "$\\Delta$ Acc.", "Rec.", "FAR", "FRR", "AUC")) + r" \\",
    r"\midrule",
    r"\multicolumn{9}{l}{\textcolor{blue}{FEI Face Database --- controlled acquisition}} \\",
]
for result in fei_results:
    for cells in table_rows(result, "FEI"):
        ql.append(" & ".join(blue(cell) for cell in cells) + r" \\")
ql += [
    r"\midrule",
    r"\multicolumn{9}{l}{\textcolor{blue}{LFW Funneled --- unconstrained acquisition}} \\",
]
for result in lfw_results:
    for cells in table_rows(result, "LFW"):
        ql.append(" & ".join(blue(cell) for cell in cells) + r" \\")
ql += [r"\bottomrule", r"\end{tabular}"]
open(os.path.join(OUT, "tab_quant.tex"), "w", encoding="utf-8").write("\n".join(ql) + "\n")
print("\n".join(ql))
