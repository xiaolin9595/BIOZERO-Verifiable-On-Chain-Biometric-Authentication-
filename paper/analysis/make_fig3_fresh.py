#!/usr/bin/env python3
"""Render and self-check the fresh 2026-10-28 full Fig. 3 campaign.

Only the fresh summary is plotted.  The recovered comparison is hashed and
recorded as non-plotted evidence, so it cannot enter the primary aggregates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
from pathlib import Path
from typing import Any

from build_fig3_from_original_vector import build_figure

# Fix PDF metadata time.  A verified, semantically identical PDF is retained on
# later runs because font-subsetting bytes can otherwise vary across versions.
os.environ.setdefault("SOURCE_DATE_EPOCH", "1793145600")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ARTIFACT_DATA = ROOT / "artifact/data"
DEFAULT_INPUT = DATA / "fresh-native-fig3-full-2026-10-28.json"
DEFAULT_SOURCE_VERIFICATION = DATA / "fresh-native-fig3-full-2026-10-28-verification.json"
DEFAULT_COMPARISON = DATA / "fresh-native-fig3-full-2026-10-28-comparison.json"
DEFAULT_CHAIN_CONTROL = DATA / "fresh-native-fig3-full-n128-chain-controls-2026-10-28.json"
DEFAULT_SOURCE_TRANSFORM_MANIFEST = DATA / "fresh-native-fig3-full-2026-10-28-source-transform-manifest.tsv"
DEFAULT_OUTPUT = ROOT / "figures/fig3_full_fresh_2026-10-28.pdf"
DEFAULT_FIGURE_VERIFICATION = DATA / "fresh-native-fig3-full-2026-10-28-figure-verification.json"
EXPECTED_DIMS = [2, 4, 8, 16, 32, 64, 128]
EIP170_LIMIT_BYTES = 24_576
FIGURE_SPEC_VERSION = "fresh-native-fig3-full-v4-original-vector-style"
ORIGINAL_VECTOR_TEMPLATE = ROOT / "figures/isc_groth16_cost.pdf"
VECTOR_BUILDER = Path(__file__).with_name("build_fig3_from_original_vector.py")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--source-verification", type=Path, default=DEFAULT_SOURCE_VERIFICATION)
    parser.add_argument("--comparison", type=Path, default=DEFAULT_COMPARISON)
    parser.add_argument("--chain-control", type=Path, default=DEFAULT_CHAIN_CONTROL)
    parser.add_argument("--source-transform-manifest", type=Path, default=DEFAULT_SOURCE_TRANSFORM_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--figure-verification", type=Path, default=DEFAULT_FIGURE_VERIFICATION)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError(f"{label}: {actual!r} != {expected!r}")


def inspect_vector_pdf(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"valid": False, "raster_image_objects": None}
    content = path.read_bytes()
    raster_image_objects = content.count(b"/Subtype /Image")
    return {
        "valid": content.startswith(b"%PDF-") and raster_image_objects == 0,
        "raster_image_objects": raster_image_objects,
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_row(row: dict[str, Any], *, fixed: bool) -> None:
    label = str(row["target"])
    proof = row["proof_time"]
    gas = row["verifier_gas"]
    proof_samples = [float(value) for value in proof["measured_runs"]]
    gas_samples = [int(value) for value in gas["measured_runs"]]
    expected_gas = 30 if fixed else 5
    expected_gas_warmups = 5 if fixed else 1

    if proof.get("unit") != "ms" or proof.get("warmup_runs") != 1:
        raise ValueError(f"{label}: proving unit or warm-up count is invalid")
    if proof.get("samples") != 5 or len(proof_samples) != 5:
        raise ValueError(f"{label}: proving must contain exactly five measured samples")
    if gas.get("samples") != expected_gas or len(gas_samples) != expected_gas:
        raise ValueError(f"{label}: gas must contain exactly {expected_gas} measured transactions")
    if gas.get("warmup_runs") != expected_gas_warmups:
        raise ValueError(f"{label}: gas warm-up count is invalid")
    if not all(value > 0 for value in proof_samples + gas_samples):
        raise ValueError(f"{label}: measured samples must be positive")

    assert_close(statistics.mean(proof_samples), float(proof["mean"]), f"{label} proof mean")
    assert_close(statistics.stdev(proof_samples), float(proof["sample_sd"]), f"{label} proof SD")
    assert_close(statistics.mean(gas_samples), float(gas["mean"]), f"{label} gas mean")
    assert_close(statistics.stdev(gas_samples), float(gas["sample_sd"]), f"{label} gas SD")

    controls = row["matching_and_controls"]
    required_controls = {
        "native_valid_proof_accepted",
        "native_invalid_public_input_rejected",
        "verifier_reexport_byte_exact_match",
        "chain_valid_static_true",
        "chain_invalid_static_false",
        "onchain_runtime_matches_compiler",
        "standard_eip170_behavior",
    }
    if set(controls) != required_controls or not all(controls.values()):
        raise ValueError(f"{label}: one or more native/chain controls did not pass")


def validate_csv(summary: dict[str, Any], input_path: Path) -> dict[str, Any]:
    csv_path = input_path.with_suffix(".csv")
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 8:
        raise ValueError("fresh CSV must contain BioZero fixed and seven Vanilla rows")
    by_target = {str(row["target"]): row for row in rows}
    for result in summary["results"]:
        label = str(result["target"])
        csv_row = by_target.get(label)
        if csv_row is None:
            raise ValueError(f"fresh CSV is missing {label}")
        assert_close(float(csv_row["proof_mean_ms"]), float(result["proof_time"]["mean"]), f"{label} CSV proof mean")
        assert_close(float(csv_row["proof_sample_sd_ms"]), float(result["proof_time"]["sample_sd"]), f"{label} CSV proof SD")
        assert_close(float(csv_row["verifier_gas_mean"]), float(result["verifier_gas"]["mean"]), f"{label} CSV gas mean")
        if int(csv_row["verifier_runtime_bytecode_bytes"]) != int(result["verifier_runtime_bytecode_bytes"]):
            raise ValueError(f"{label}: CSV runtime bytecode size differs from JSON")
        if int(csv_row["verifier_creation_bytecode_bytes"]) != int(result["verifier_creation_bytecode_bytes"]):
            raise ValueError(f"{label}: CSV creation bytecode size differs from JSON")
    return {"file": csv_path.name, "sha256": sha256(csv_path), "rows": len(rows)}


def validate_source_transform_manifest(manifest_path: Path) -> dict[str, Any]:
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if [int(row["dimension"]) for row in rows] != EXPECTED_DIMS:
        raise ValueError("source-transform manifest does not cover all seven dimensions")
    workspace_root = ROOT.parent
    for row in rows:
        dimension = int(row["dimension"])
        original = workspace_root / row["original_source_path"]
        repaired = workspace_root / row["repaired_source_path"]
        if sha256(original) != row["original_source_sha256"]:
            raise ValueError(f"N={dimension}: original source hash mismatch")
        if sha256(repaired) != row["repaired_source_sha256"]:
            raise ValueError(f"N={dimension}: repaired source hash mismatch")
        removed = row["removed_local_declaration"]
        original_nonblank = [line.strip() for line in original.read_text(encoding="utf-8").splitlines() if line.strip()]
        repaired_nonblank = [line.strip() for line in repaired.read_text(encoding="utf-8").splitlines() if line.strip()]
        matching_deletions = []
        for index, line in enumerate(original_nonblank):
            if line != removed:
                continue
            candidate = original_nonblank[:index] + original_nonblank[index + 1 :]
            if candidate == repaired_nonblank:
                matching_deletions.append(index)
        if len(matching_deletions) != 1:
            raise ValueError(f"N={dimension}: repair changes another nonblank source line")
        if row["nonblank_deletions"] != "1" or row["nonblank_additions"] != "0" or row["only_nonblank_change"] != "PASS":
            raise ValueError(f"N={dimension}: transform manifest does not record the one-line repair")
    return {"file": manifest_path.name, "sha256": sha256(manifest_path), "rows": len(rows), "all_exact_diff_checks": "PASS"}


def validate_inputs(
    summary: dict[str, Any],
    source_verification: dict[str, Any],
    comparison: dict[str, Any],
    chain_control: dict[str, Any],
    source_transform_manifest_path: Path,
    input_path: Path,
) -> dict[str, Any]:
    if summary.get("schema_version") != 1:
        raise ValueError("unexpected fresh summary schema")
    if not str(summary.get("experiment_label", "")).startswith("fresh full Fig. 3 reconstruction"):
        raise ValueError("input is not labeled as the fresh full Fig. 3 campaign")
    if summary.get("recovered_campaign_is_separate_evidence") is not True:
        raise ValueError("fresh summary must keep the recovered campaign separate")
    if summary.get("verification") != {"overall": "PASS", "passed": 43, "failed": 0}:
        raise ValueError("fresh summary does not carry the frozen 43/43 PASS result")
    if source_verification.get("overall") != "PASS" or source_verification.get("failed") != 0:
        raise ValueError("source verification is not PASS")
    if source_verification.get("passed") != 43 or len(source_verification.get("checks", [])) != 43:
        raise ValueError("source verification must contain all 43 passing checks")
    if not all(check.get("passed") is True for check in source_verification["checks"]):
        raise ValueError("a source verification check failed")

    results = list(summary.get("results", []))
    fixed_rows = [row for row in results if row.get("target") == "biozero-fixed"]
    vanilla = sorted(
        (row for row in results if str(row.get("target", "")).startswith("vanilla-")),
        key=lambda row: int(row["dimension"]),
    )
    if len(fixed_rows) != 1 or [int(row["dimension"]) for row in vanilla] != EXPECTED_DIMS:
        raise ValueError("fresh JSON must contain one BioZero fixed target and all seven Vanilla dimensions")
    fixed = fixed_rows[0]
    validate_row(fixed, fixed=True)
    for row in vanilla:
        validate_row(row, fixed=False)

    protocol = summary["environment"]["protocol"]
    if protocol.get("vanilla_dimensions") != EXPECTED_DIMS:
        raise ValueError("environment protocol dimension grid differs from the fresh data")
    if protocol.get("low_dimensions_rayon_num_threads") is not None:
        raise ValueError("Vanilla N=2..32 must retain the default Rayon configuration")
    if protocol.get("high_dimensions_rayon_num_threads") != 1 or protocol.get("biozero_fixed_rayon_num_threads") != 1:
        raise ValueError("the high-dimension/BioZero single-thread split is missing")
    if not str(protocol.get("setup_policy", "")).startswith("reuse circuit-specific"):
        raise ValueError("the run must identify reused compiled/setup/verifier artifacts")

    n128 = vanilla[-1]
    if n128["target"] != "vanilla-128":
        raise ValueError("the final Vanilla row is not N=128")
    if int(n128["verifier_runtime_bytecode_bytes"]) <= EIP170_LIMIT_BYTES:
        raise ValueError("N=128 runtime must exceed EIP-170")
    if n128.get("eip170_deployable") is not False:
        raise ValueError("N=128 must be marked non-deployable under standard EIP-170")

    standard = chain_control["standard_eip170_control"]
    deployment = chain_control["deployment"]
    config = chain_control["configuration"]
    if chain_control.get("target") != "vanilla-128" or chain_control.get("overall") != "PASS":
        raise ValueError("N=128 chain-control bundle is not PASS")
    if standard.get("attempted") is not True or standard.get("deployment_failed_as_expected") is not True:
        raise ValueError("fresh standard-limit negative control is missing")
    if standard.get("eip170_runtime_limit_bytes") != EIP170_LIMIT_BYTES:
        raise ValueError("unexpected EIP-170 runtime limit")
    if standard.get("compiled_runtime_bytecode_bytes") != n128["verifier_runtime_bytecode_bytes"]:
        raise ValueError("chain-control runtime size differs from the fresh summary")
    if standard.get("error_receipt", {}).get("receipt_status") != 0:
        raise ValueError("standard-limit deployment must retain a status-0 receipt")
    if config.get("allow_unlimited_contract_size") is not True or deployment.get("receipt_status") != 1:
        raise ValueError("explicit unlimited-chain deployment success is missing")
    if deployment.get("onchain_runtime_matches_compiled") is not True:
        raise ValueError("unlimited-chain runtime does not match compiler output")

    comparison_rows = comparison.get("comparison", [])
    if len(comparison_rows) != 8 or "separate comparison" not in str(comparison.get("interpretation", "")):
        raise ValueError("fresh-versus-recovered comparison metadata is incomplete")
    if [row.get("target") for row in comparison_rows] != [row.get("target") for row in results]:
        raise ValueError("comparison targets do not align with the fresh summary")

    csv_check = validate_csv(summary, input_path)
    source_transform_check = validate_source_transform_manifest(source_transform_manifest_path)
    panel_points = {
        "a_verifier_gas": 2 * len(EXPECTED_DIMS),
        "b_deployment_gas": 2 * len(EXPECTED_DIMS),
        "c_proving_time": 2 * len(EXPECTED_DIMS),
        "d_proof_and_creation_bytecode": 4 * len(EXPECTED_DIMS),
    }
    checks = {
        "dimensions": EXPECTED_DIMS,
        "fresh_series": 10,
        "fresh_logical_cells": sum(panel_points.values()),
        "plot_points_by_panel": panel_points,
        "recovered_series_plotted": 0,
        "proving_samples": {
            "biozero_fixed": len(fixed["proof_time"]["measured_runs"]),
            "vanilla_total": sum(len(row["proof_time"]["measured_runs"]) for row in vanilla),
        },
        "gas_transactions": {
            "biozero_fixed": len(fixed["verifier_gas"]["measured_runs"]),
            "vanilla_total": sum(len(row["verifier_gas"]["measured_runs"]) for row in vanilla),
        },
        "all_native_and_chain_controls_pass": True,
        "source_verification": {
            "overall": source_verification["overall"],
            "passed": source_verification["passed"],
            "failed": source_verification["failed"],
        },
        "eip170": {
            "limit_bytes": EIP170_LIMIT_BYTES,
            "n128_runtime_bytes": n128["verifier_runtime_bytecode_bytes"],
            "standard_limit_deployment_failed": True,
            "standard_limit_receipt_status": standard["error_receipt"]["receipt_status"],
            "unlimited_contract_size": True,
            "unlimited_deployment_receipt_status": deployment["receipt_status"],
        },
        "csv": csv_check,
        "source_transform_manifest": source_transform_check,
    }
    if checks["fresh_logical_cells"] != 70:
        raise ValueError("figure must contain exactly 70 fresh logical cells")
    if checks["proving_samples"] != {"biozero_fixed": 5, "vanilla_total": 35}:
        raise ValueError("fresh proving sample counts are invalid")
    if checks["gas_transactions"] != {"biozero_fixed": 30, "vanilla_total": 35}:
        raise ValueError("fresh gas transaction counts are invalid")
    return checks


def semantic_sha256(summary: dict[str, Any]) -> str:
    plotted_fields = (
        "deployment_gas",
        "verifier_creation_bytecode_bytes",
    )
    payload_rows: list[dict[str, Any]] = []
    for row in summary["results"]:
        payload_rows.append(
            {
                "target": row["target"],
                "dimension": row["dimension"],
                "proof_time": {
                    "mean": row["proof_time"]["mean"],
                    "sample_sd": row["proof_time"]["sample_sd"],
                },
                "verifier_gas_mean": row["verifier_gas"]["mean"],
                "proof_size_mean": row["proof_size"]["mean"],
                **{field: row[field] for field in plotted_fields},
            }
        )
    payload = {
        "figure_spec_version": FIGURE_SPEC_VERSION,
        "original_vector_template_sha256": sha256(ORIGINAL_VECTOR_TEMPLATE),
        "vector_builder_sha256": sha256(VECTOR_BUILDER),
        "data_class": "fresh 2026-10-28 primary measurements",
        "recovered_overlay": False,
        "dimensions": EXPECTED_DIMS,
        "rows": payload_rows,
        "panels": [
            "verifier gas, thousand gas",
            "deployment gas, million gas",
            "proving time, seconds, log scale, mean plus/minus sample SD",
            "proof and verifier creation bytecode, KiB",
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def render(summary: dict[str, Any], output_path: Path) -> None:
    build_figure(summary, ORIGINAL_VECTOR_TEMPLATE, output_path)


def reusable_figure(
    output_path: Path,
    verification_path: Path,
    input_sha256: str,
    semantic_hash: str,
) -> bool:
    if not output_path.is_file() or not verification_path.is_file():
        return False
    try:
        previous = load_json(verification_path)
    except (json.JSONDecodeError, OSError):
        return False
    figure = previous.get("figure", {})
    return bool(
        previous.get("status") == "PASS"
        and previous.get("inputs", {}).get("fresh_summary", {}).get("sha256") == input_sha256
        and figure.get("semantic_sha256") == semantic_hash
        and figure.get("sha256") == sha256(output_path)
        and figure.get("vector_pdf") is True
        and inspect_vector_pdf(output_path)["valid"]
    )


def render_if_needed(
    summary: dict[str, Any],
    output_path: Path,
    verification_path: Path,
    input_sha256: str,
    semantic_hash: str,
) -> bool:
    if reusable_figure(output_path, verification_path, input_sha256, semantic_hash):
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    try:
        render(summary, temporary)
        if not inspect_vector_pdf(temporary)["valid"]:
            raise ValueError("new figure is not a raster-free vector PDF")
        if output_path.is_file() and output_path.read_bytes() == temporary.read_bytes():
            temporary.unlink()
        else:
            os.replace(temporary, output_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return True


def write_if_changed(path: Path, content: str) -> bool:
    encoded = content.encode("utf-8")
    if path.is_file() and path.read_bytes() == encoded:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return True


def main() -> None:
    args = parse_args()
    input_path = args.input.resolve()
    source_verification_path = args.source_verification.resolve()
    comparison_path = args.comparison.resolve()
    chain_control_path = args.chain_control.resolve()
    source_transform_manifest_path = args.source_transform_manifest.resolve()
    output_path = args.output.resolve()
    figure_verification_path = args.figure_verification.resolve()

    summary = load_json(input_path)
    source_verification = load_json(source_verification_path)
    comparison = load_json(comparison_path)
    chain_control = load_json(chain_control_path)
    checks = validate_inputs(
        summary,
        source_verification,
        comparison,
        chain_control,
        source_transform_manifest_path,
        input_path,
    )
    input_hash = sha256(input_path)
    semantic_hash = semantic_sha256(summary)
    figure_changed = render_if_needed(
        summary, output_path, figure_verification_path, input_hash, semantic_hash
    )
    pdf_inspection = inspect_vector_pdf(output_path)
    if not pdf_inspection["valid"]:
        raise ValueError("output is not a raster-free vector PDF")

    verification = {
        "schema_version": 1,
        "status": "PASS",
        "data_policy": {
            "primary": "fresh 2026-10-28 measurements",
            "recovered_comparison_plotted": False,
            "setup": "reused compiled program, proving key, verification key, and matching verifier",
        },
        "inputs": {
            "fresh_summary": {"file": input_path.name, "sha256": input_hash, "plotted": True},
            "fresh_csv": checks["csv"],
            "source_verification": {
                "file": source_verification_path.name,
                "sha256": sha256(source_verification_path),
                "plotted": False,
            },
            "fresh_vs_recovered": {
                "file": comparison_path.name,
                "sha256": sha256(comparison_path),
                "plotted": False,
            },
            "n128_chain_controls": {
                "file": chain_control_path.name,
                "sha256": sha256(chain_control_path),
                "plotted": False,
            },
            "source_transform_manifest": {
                "file": source_transform_manifest_path.name,
                "sha256": sha256(source_transform_manifest_path),
                "plotted": False,
            },
        },
        "checks": checks,
        "figure": {
            "file": output_path.name,
            "sha256": sha256(output_path),
            "semantic_sha256": semantic_hash,
            "figure_spec_version": FIGURE_SPEC_VERSION,
            "renderer": "retained original TeX vector with data-path substitution",
            "renderer_sources": {
                "original_vector_template": {
                    "file": ORIGINAL_VECTOR_TEMPLATE.name,
                    "sha256": sha256(ORIGINAL_VECTOR_TEMPLATE),
                },
                "builder": {"file": VECTOR_BUILDER.name, "sha256": sha256(VECTOR_BUILDER)},
            },
            "style_equivalence": "all non-data vector operators, fonts, axes, legends, colors, line widths, dash arrays, markers, and panel geometry are inherited verbatim from the retained original TeX vector",
            "page_size_pt": [350, 215],
            "bytes": output_path.stat().st_size,
            "panels": [
                "(a) verifier gas",
                "(b) deployment gas",
                "(c) proving time",
                "(d) proof and verifier creation bytecode",
            ],
            "fresh_series": 10,
            "fresh_logical_cells": 70,
            "series_data_classes": [
                {"panel": "a", "series": "Vanilla verifier gas", "data_class": "fresh 2026-10-28"},
                {"panel": "a", "series": "BioZero fixed verifier gas", "data_class": "fresh 2026-10-28"},
                {"panel": "b", "series": "Vanilla deployment gas", "data_class": "fresh 2026-10-28"},
                {"panel": "b", "series": "BioZero fixed deployment gas", "data_class": "fresh 2026-10-28"},
                {"panel": "c", "series": "Vanilla proving time", "data_class": "fresh 2026-10-28"},
                {"panel": "c", "series": "BioZero fixed proving time", "data_class": "fresh 2026-10-28"},
                {"panel": "d", "series": "Vanilla proof size", "data_class": "fresh 2026-10-28"},
                {"panel": "d", "series": "Vanilla creation bytecode", "data_class": "fresh 2026-10-28"},
                {"panel": "d", "series": "BioZero fixed proof size", "data_class": "fresh 2026-10-28"},
                {"panel": "d", "series": "BioZero fixed creation bytecode", "data_class": "fresh 2026-10-28"},
            ],
            "proving_error_bars": "not drawn, matching the retained original TeX figure style; sample SD remains in the data and prose",
            "raster_image_objects": pdf_inspection["raster_image_objects"],
            "vector_pdf": True,
        },
    }
    content = json.dumps(verification, indent=2, sort_keys=True) + "\n"
    changed = write_if_changed(figure_verification_path, content)
    artifact_verification = ARTIFACT_DATA / figure_verification_path.name
    artifact_changed = write_if_changed(artifact_verification, content)
    if figure_verification_path.read_bytes() != artifact_verification.read_bytes():
        raise ValueError("figure verification mirrors differ")

    print(f"{'saved' if figure_changed else 'kept'} {output_path.relative_to(ROOT)}")
    print(
        f"{'saved' if changed or artifact_changed else 'kept'} "
        f"{figure_verification_path.relative_to(ROOT)}"
    )
    print(
        "verification PASS: 4 panels; 10 fresh series; 70 fresh logical cells; "
        "proving 5/target; gas BioZero=30 and Vanilla=5/target; controls and EIP-170 PASS"
    )


if __name__ == "__main__":
    main()
