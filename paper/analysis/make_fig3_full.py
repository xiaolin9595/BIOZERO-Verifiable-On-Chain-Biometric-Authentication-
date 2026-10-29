#!/usr/bin/env python3
"""Render the complete recovered-native Fig. 3 and verify its data grid.

The input is a dated packaging of the recovered 2026-06-05 campaign.  This
script does not read or synthesize fresh benchmark measurements.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import statistics
from pathlib import Path
from typing import Any

# Stabilize backend timestamps. Cross-version Matplotlib font subsetting can
# still differ, so main() also preserves a verified PDF by semantic fingerprint.
os.environ.setdefault("SOURCE_DATE_EPOCH", "1793145600")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, ScalarFormatter


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/recovered-native-fig3-full-2026-10-28.json"
DEFAULT_OUTPUT = ROOT / "figures/fig3_full_recovered_native_2026-10-28.pdf"
DEFAULT_VERIFICATION = ROOT / "data/recovered-native-fig3-full-verification-2026-10-28.json"
ARTIFACT_DATA = ROOT / "artifact/data"
EXPECTED_DIMS = [2, 4, 8, 16, 32, 64, 128]
BLUE = "#0072B2"
ORANGE = "#D55E00"
GRAY = "#666666"
FIGURE_SPEC_VERSION = "recovered-native-fig3-full-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verification", type=Path, default=DEFAULT_VERIFICATION)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def figure_semantic_sha256(data: dict[str, Any]) -> str:
    """Hash every plotted value plus a versioned rendering specification."""
    fields = (
        "gas_mean",
        "deployment_gas",
        "proving_mean_ms",
        "proving_sample_sd_ms",
        "proof_bytes",
        "verifier_bytecode_bytes",
    )
    fixed = data["biozero_fixed"]
    vanilla = sorted(data["vanilla"], key=lambda row: int(row["dimension"]))
    payload = {
        "figure_spec_version": FIGURE_SPEC_VERSION,
        "dimensions": EXPECTED_DIMS,
        "fixed": {field: fixed[field] for field in fields},
        "vanilla": [
            {"dimension": row["dimension"], **{field: row[field] for field in fields}}
            for row in vanilla
        ],
        "panels": [
            "verifier gas, linear, thousand gas",
            "deployment gas, linear, million gas",
            "proving time, log, mean plus/minus sample SD",
            "proof and verifier bytecode, linear, KiB, EIP-170 reference",
        ],
        "palette": {"vanilla": BLUE, "biozero": ORANGE, "reference": GRAY},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def inspect_vector_pdf(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"valid": False, "raster_image_objects": None}
    content = path.read_bytes()
    raster_image_objects = content.count(b"/Subtype /Image")
    return {
        "valid": content.startswith(b"%PDF-") and raster_image_objects == 0,
        "raster_image_objects": raster_image_objects,
    }


def reusable_figure(
    output_path: Path,
    verification_path: Path,
    input_sha256: str,
    semantic_sha256: str,
) -> bool:
    """Reuse only a byte-verified, raster-free PDF for the same plotted semantics."""
    if not output_path.is_file() or not verification_path.is_file():
        return False
    try:
        previous = json.loads(verification_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    figure = previous.get("figure", {})
    return bool(
        previous.get("status") == "PASS"
        and previous.get("input", {}).get("sha256") == input_sha256
        and figure.get("semantic_sha256") == semantic_sha256
        and figure.get("sha256") == sha256(output_path)
        and figure.get("vector_pdf") is True
        and inspect_vector_pdf(output_path)["valid"]
    )


def assert_close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError(f"{label}: {actual!r} != {expected!r}")


def validate_row(row: dict[str, Any], label: str, expected_gas_samples: int = 5) -> None:
    proving = [float(value) for value in row["proving_samples_ms"]]
    gas = [int(value) for value in row["gas_samples"]]
    hashes = list(row["gas_tx_hashes"])
    if len(proving) != 5 or len(gas) != expected_gas_samples or len(hashes) != expected_gas_samples:
        raise ValueError(
            f"{label}: expected five proving samples and {expected_gas_samples} gas transactions"
        )
    if not all(value > 0 for value in proving):
        raise ValueError(f"{label}: proving samples must be positive")
    if not all(value > 0 for value in gas):
        raise ValueError(f"{label}: gas samples must be positive")
    if len(set(hashes)) != expected_gas_samples or not all(
        value.startswith("0x") and len(value) == 66 for value in hashes
    ):
        raise ValueError(f"{label}: transaction hashes must be unique 32-byte hex strings")
    if not row["gas_all_pass"]:
        raise ValueError(f"{label}: a gas transaction is marked failed")
    assert_close(statistics.mean(proving), float(row["proving_mean_ms"]), f"{label} proving mean")
    assert_close(statistics.stdev(proving), float(row["proving_sample_sd_ms"]), f"{label} proving SD")
    assert_close(statistics.mean(gas), float(row["gas_mean"]), f"{label} gas mean")
    assert_close(statistics.stdev(gas), float(row["gas_sample_sd"]), f"{label} gas SD")


def validate_input(data: dict[str, Any], input_path: Path) -> dict[str, Any]:
    if data.get("source") != "recovered_native_campaign_2026-06-05":
        raise ValueError("unexpected source label")
    if data.get("packaged_on") != "2026-10-28":
        raise ValueError("unexpected packaging date")
    if data.get("dimensions") != EXPECTED_DIMS:
        raise ValueError("dimension grid is not exactly 2,4,8,16,32,64,128")
    provenance = data["provenance"]
    if provenance.get("fresh_2026_10_28_measurements") is not False:
        raise ValueError("input must explicitly reject a fresh-2026-10-28 claim")
    if provenance.get("vanilla_circuit_semantics") != "bug-fixed shadow line":
        raise ValueError("shadow-line repair provenance is missing")
    if not str(provenance.get("setup_artifacts", "")).startswith("reused/recovered"):
        raise ValueError("reused/recovered setup provenance is missing")

    fixed = data["biozero_fixed"]
    if fixed.get("fixed_across_dimensions") is not True:
        raise ValueError("BioZero must be identified as fixed across dimensions")
    validate_row(fixed, "BioZero fixed", expected_gas_samples=30)

    vanilla = sorted(data["vanilla"], key=lambda row: int(row["dimension"]))
    if [int(row["dimension"]) for row in vanilla] != EXPECTED_DIMS:
        raise ValueError("Vanilla rows do not cover the complete seven-dimension grid")
    for row in vanilla:
        validate_row(row, f"Vanilla N={row['dimension']}")

    vanilla_tx_hashes = [tx for row in vanilla for tx in row["gas_tx_hashes"]]
    if len(set(vanilla_tx_hashes)) != 35:
        raise ValueError("the 35 Vanilla gas transaction hashes are not globally unique")

    csv_path = input_path.with_suffix(".csv")
    with csv_path.open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    csv_dims = [int(row["dimension"]) for row in csv_rows if row["dimension"]]
    if len(csv_rows) != 8 or csv_dims != EXPECTED_DIMS:
        raise ValueError("CSV mirror must contain one fixed row plus seven Vanilla rows")

    artifact_json = ARTIFACT_DATA / input_path.name
    artifact_csv = ARTIFACT_DATA / csv_path.name
    mirror_json_identical = artifact_json.read_bytes() == input_path.read_bytes()
    mirror_csv_identical = artifact_csv.read_bytes() == csv_path.read_bytes()
    if not mirror_json_identical or not mirror_csv_identical:
        raise ValueError("data/ and artifact/data/ mirrors differ")

    panel_points = {
        "a_verifier_gas": 2 * len(EXPECTED_DIMS),
        "b_deployment_gas": 2 * len(EXPECTED_DIMS),
        "c_proving_time": 2 * len(EXPECTED_DIMS),
        "d_proof_and_bytecode": 4 * len(EXPECTED_DIMS),
    }
    return {
        "dimensions": len(EXPECTED_DIMS),
        "dimension_values": EXPECTED_DIMS,
        "plot_points_by_panel": panel_points,
        "plot_logical_cells": sum(panel_points.values()),
        "raw_counts": {
            "vanilla_proving_samples": sum(len(row["proving_samples_ms"]) for row in vanilla),
            "vanilla_gas_transactions": sum(len(row["gas_samples"]) for row in vanilla),
            "vanilla_raw_observations": sum(
                len(row["proving_samples_ms"]) + len(row["gas_samples"]) for row in vanilla
            ),
            "biozero_fixed_proving_samples": len(fixed["proving_samples_ms"]),
            "biozero_fixed_gas_transactions": len(fixed["gas_samples"]),
        },
        "all_gas_pass": fixed["gas_all_pass"] and all(row["gas_all_pass"] for row in vanilla),
        "unique_vanilla_tx_hashes": len(set(vanilla_tx_hashes)),
        "data_artifact_json_identical": mirror_json_identical,
        "data_artifact_csv_identical": mirror_csv_identical,
    }


def style_axes(axis: plt.Axes, title: str) -> None:
    axis.set_title(title, loc="left", fontsize=8, fontweight="bold", pad=4)
    axis.grid(axis="y", color="#D9D9D9", linewidth=0.45, alpha=0.8)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(length=3, width=0.6)


def render(data: dict[str, Any], output_path: Path) -> None:
    fixed = data["biozero_fixed"]
    vanilla = sorted(data["vanilla"], key=lambda row: int(row["dimension"]))
    x = list(range(len(EXPECTED_DIMS)))
    labels = [str(value) for value in EXPECTED_DIMS]
    fixed_gas = [fixed["gas_mean"] / 1000] * len(x)
    vanilla_gas = [row["gas_mean"] / 1000 for row in vanilla]
    fixed_deploy = [fixed["deployment_gas"] / 1_000_000] * len(x)
    vanilla_deploy = [row["deployment_gas"] / 1_000_000 for row in vanilla]
    fixed_prove = [fixed["proving_mean_ms"] / 1000] * len(x)
    fixed_prove_sd = [fixed["proving_sample_sd_ms"] / 1000] * len(x)
    vanilla_prove = [row["proving_mean_ms"] / 1000 for row in vanilla]
    vanilla_prove_sd = [row["proving_sample_sd_ms"] / 1000 for row in vanilla]

    plt.rcParams.update(
        {
            "font.size": 7.5,
            "axes.linewidth": 0.6,
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "legend.frameon": False,
            "xtick.direction": "out",
            "ytick.direction": "out",
        }
    )
    fig, axes = plt.subplots(2, 2, figsize=(7.16, 5.0), sharex=False, constrained_layout=True)
    ax_a, ax_b, ax_c, ax_d = axes.flat

    common = {"linewidth": 1.25, "markersize": 4.8, "markerfacecolor": "white", "markeredgewidth": 0.9}
    ax_a.plot(x, vanilla_gas, color=BLUE, marker="o", label="Vanilla ZKBio (shadow-fixed)", **common)
    ax_a.plot(x, fixed_gas, color=ORANGE, marker="s", linestyle="--", label="BioZero fixed", **common)
    ax_a.set_ylabel("Verifier gas (thousand)")
    ax_a.set_ylim(200, 2500)
    style_axes(ax_a, "(a) Verifier gas")
    ax_a.legend(loc="upper left", fontsize=6.4, handlelength=2.4)

    ax_b.plot(x, vanilla_deploy, color=BLUE, marker="o", label="Vanilla ZKBio (shadow-fixed)", **common)
    ax_b.plot(x, fixed_deploy, color=ORANGE, marker="s", linestyle="--", label="BioZero fixed", **common)
    ax_b.set_ylabel("Deployment gas (million)")
    ax_b.set_ylim(0.6, 8.1)
    style_axes(ax_b, "(b) Deployment gas")
    ax_b.legend(loc="upper left", fontsize=6.4, handlelength=2.4)

    ax_c.errorbar(
        x,
        vanilla_prove,
        yerr=vanilla_prove_sd,
        color=BLUE,
        marker="o",
        capsize=2.2,
        elinewidth=0.75,
        label="Vanilla ZKBio (mean ± SD)",
        **common,
    )
    ax_c.errorbar(
        x,
        fixed_prove,
        yerr=fixed_prove_sd,
        color=ORANGE,
        marker="s",
        linestyle="--",
        capsize=2.2,
        elinewidth=0.75,
        label="BioZero fixed (mean ± SD)",
        **common,
    )
    ax_c.set_yscale("log")
    ax_c.set_ylim(1, 1200)
    ax_c.yaxis.set_major_locator(FixedLocator([1, 3, 10, 30, 100, 300, 1000]))
    ax_c.yaxis.set_major_formatter(ScalarFormatter())
    ax_c.set_ylabel("Groth16 proving time (s)")
    style_axes(ax_c, "(c) Proving time (log scale)")
    ax_c.legend(loc="upper left", fontsize=6.4, handlelength=2.4)

    vanilla_proof = [row["proof_bytes"] / 1024 for row in vanilla]
    vanilla_bytecode = [row["verifier_bytecode_bytes"] / 1024 for row in vanilla]
    fixed_proof = [fixed["proof_bytes"] / 1024] * len(x)
    fixed_bytecode = [fixed["verifier_bytecode_bytes"] / 1024] * len(x)
    ax_d.plot(x, vanilla_proof, color=BLUE, marker="o", label="Vanilla proof", **common)
    ax_d.plot(x, vanilla_bytecode, color=BLUE, marker="^", linestyle=":", label="Vanilla verifier", **common)
    ax_d.plot(x, fixed_proof, color=ORANGE, marker="s", linestyle="--", label="BioZero proof", **common)
    ax_d.plot(x, fixed_bytecode, color=ORANGE, marker="D", linestyle="-.", label="BioZero verifier", **common)
    ax_d.axhline(24, color=GRAY, linewidth=0.7, linestyle=(0, (2, 2)), zorder=0)
    ax_d.text(0.08, 24.7, "EIP-170: 24 KiB", color=GRAY, fontsize=6.2)
    ax_d.set_ylim(0, 37)
    ax_d.set_ylabel("Size (KiB)")
    style_axes(ax_d, "(d) Proof and verifier bytecode")
    ax_d.legend(loc="upper left", ncol=2, fontsize=6.1, columnspacing=0.8, handlelength=2.1)

    for axis in axes.flat:
        axis.set_xticks(x, labels)
        axis.set_xlim(-0.25, len(x) - 0.75)
        axis.set_xlabel("Dimension $N$")
        axis.yaxis.set_major_formatter(axis.yaxis.get_major_formatter())
    ax_a.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
    ax_b.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}"))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime(2026, 10, 28, 0, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    fig.savefig(
        output_path,
        format="pdf",
        metadata={
            "Title": "Recovered-native complete Fig. 3 comparison",
            "Author": "BioZERO artifact packaging",
            "Subject": "Recovered 2026-06-05 campaign; not a fresh 2026-10-28 run",
            "Keywords": "BioZERO, recovered campaign, Groth16, Fig. 3",
            "CreationDate": timestamp,
            "ModDate": timestamp,
        },
    )
    plt.close(fig)


def render_if_needed(
    data: dict[str, Any],
    output_path: Path,
    verification_path: Path,
    input_sha256: str,
    semantic_sha256: str,
) -> bool:
    """Render atomically; leave an already verified equivalent PDF untouched."""
    if reusable_figure(output_path, verification_path, input_sha256, semantic_sha256):
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    try:
        render(data, temporary)
        if not inspect_vector_pdf(temporary)["valid"]:
            raise ValueError("new output is not a raster-free vector PDF")
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
    path.write_bytes(encoded)
    return True


def write_verification(
    verification: dict[str, Any], verification_path: Path, artifact_path: Path
) -> bool:
    content = json.dumps(verification, indent=2, sort_keys=True) + "\n"
    verification_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    changed = write_if_changed(verification_path, content)
    artifact_changed = write_if_changed(artifact_path, content)
    return changed or artifact_changed


def main() -> None:
    args = parse_args()
    input_path = args.input.resolve()
    output_path = args.output.resolve()
    verification_path = args.verification.resolve()
    data = json.loads(input_path.read_text(encoding="utf-8"))
    checks = validate_input(data, input_path)
    input_sha256 = sha256(input_path)
    semantic_sha256 = figure_semantic_sha256(data)
    figure_changed = render_if_needed(
        data,
        output_path,
        verification_path,
        input_sha256,
        semantic_sha256,
    )

    pdf_inspection = inspect_vector_pdf(output_path)
    if not pdf_inspection["valid"]:
        raise ValueError("output is not a raster-free vector PDF")
    if checks["plot_logical_cells"] != 70:
        raise ValueError("expected exactly 70 plotted logical cells")
    raw = checks["raw_counts"]
    if raw["vanilla_proving_samples"] != 35 or raw["vanilla_gas_transactions"] != 35:
        raise ValueError("expected 35 proving samples and 35 gas transactions for Vanilla")
    if raw["biozero_fixed_proving_samples"] != 5 or raw["biozero_fixed_gas_transactions"] != 30:
        raise ValueError("expected five BioZero proving samples and 30 measured gas transactions")

    verification = {
        "schema_version": 1,
        "status": "PASS",
        "source": data["source"],
        "fresh_2026_10_28_measurements": False,
        "input": {
            "file": input_path.name,
            "sha256": input_sha256,
        },
        "checks": checks,
        "figure": {
            "file": output_path.name,
            "sha256": sha256(output_path),
            "semantic_sha256": semantic_sha256,
            "figure_spec_version": FIGURE_SPEC_VERSION,
            "bytes": output_path.stat().st_size,
            "panels": ["(a) verifier gas", "(b) deployment gas", "(c) proving time", "(d) proof and verifier bytecode"],
            "proving_error_bars": "sample standard deviation, n=5",
            "raster_image_objects": pdf_inspection["raster_image_objects"],
            "vector_pdf": True,
        },
    }
    artifact_verification = ARTIFACT_DATA / verification_path.name
    verification_changed = write_verification(verification, verification_path, artifact_verification)
    figure_action = "saved" if figure_changed else "kept"
    verification_action = "saved" if verification_changed else "kept"
    print(f"{figure_action} {output_path.relative_to(ROOT)}")
    print(f"{verification_action} {verification_path.relative_to(ROOT)}")
    print(
        "verification PASS: 70 plotted cells; 7 dimensions; "
        "Vanilla raw 35 proving + 35 gas; BioZero fixed raw 5 proving + 30 gas"
    )


if __name__ == "__main__":
    main()
