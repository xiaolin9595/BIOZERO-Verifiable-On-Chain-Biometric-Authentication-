#!/usr/bin/env python3
"""Replace only the data paths in the retained original TeX Fig. 3 vector.

The editable source of the historical figure was not archived.  The retained
PDF nevertheless contains all axes, text, fonts, legends, dash patterns,
markers, and panel geometry as vector operators.  This builder preserves those
operators verbatim and replaces only the four panels' plotted coordinates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable

import pikepdf


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/fresh-native-fig3-full-2026-10-28.json"
DEFAULT_TEMPLATE = ROOT / "figures/isc_groth16_cost.pdf"
DEFAULT_OUTPUT = ROOT / "figures/fig3_full_fresh_2026-10-28.pdf"
EXPECTED_DIMS = [2, 4, 8, 16, 32, 64, 128]
X_LEFT = [1965.31, 2143.84, 2322.35, 2500.85, 2679.35, 2857.86, 3036.38]
X_RIGHT = [3444.55, 3623.09, 3801.59, 3980.09, 4158.59, 4337.10, 4515.63]
ORANGE = "0.851563 0.325439 0.0981445 RG"
BLUE = "0 0.447021 0.740234 RG"
DARK = "0.125488 0.129395 0.141113 RG"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def path(points: Iterable[tuple[float, float]]) -> str:
    rows = []
    for index, (x, y) in enumerate(points):
        rows.append(f"{number(x)} {number(y)} {'m' if index == 0 else 'l'}")
    return "\n".join(rows) + "\nS\n"


def squares(xs: list[float], ys: list[float]) -> str:
    rows = []
    for x, y in zip(xs, ys):
        rows.append(
            f"{number(x - 20.42385)} {number(y - 20.42385)} "
            "40.8477 40.8477 re\nB\n"
        )
    return "\n".join(rows) + "\n"


def circle(x: float, y: float) -> str:
    radius = 20.42385
    control = 11.28
    return (
        f"{number(x + radius)} {number(y)} m\n"
        f"{number(x + radius)} {number(y + control)} {number(x + control)} {number(y + radius)} {number(x)} {number(y + radius)} c\n"
        f"{number(x - control)} {number(y + radius)} {number(x - radius)} {number(y + control)} {number(x - radius)} {number(y)} c\n"
        f"{number(x - radius)} {number(y - control)} {number(x - control)} {number(y - radius)} {number(x)} {number(y - radius)} c\n"
        f"{number(x + control)} {number(y - radius)} {number(x + radius)} {number(y - control)} {number(x + radius)} {number(y)} c\n"
        "h\n"
        f"{number(x)} {number(y)} m\nB\n\n"
    )


def circles(xs: list[float], ys: list[float]) -> str:
    return "".join(circle(x, y) for x, y in zip(xs, ys))


def replace_between(stream: str, start: str, end: str, replacement: str) -> str:
    start_index = stream.index(start)
    end_index = stream.index(end, start_index)
    return stream[:start_index] + replacement + stream[end_index:]


def linear_map(y0: float, y1: float, v0: float, v1: float) -> Callable[[float], float]:
    return lambda value: y0 + (float(value) - v0) * (y1 - y0) / (v1 - v0)


def log_map(y0: float, y1: float, v0: float, v1: float) -> Callable[[float], float]:
    low = math.log10(v0)
    high = math.log10(v1)
    return lambda value: y0 + (math.log10(float(value)) - low) * (y1 - y0) / (high - low)


def panel_block(
    xs: list[float],
    ys: list[float],
    fixed_y: float,
    *,
    fixed_color: str = DARK,
) -> str:
    return (
        path(zip(xs, ys))
        + "[ 29.8883 19.9255 ] 0 d\n"
        + fixed_color
        + "\n"
        + path([(xs[0], fixed_y), (xs[-1], fixed_y)])
        + "1 g\n[ ] 0 d\n"
        + ORANGE
        + "\n"
        + squares(xs, ys)
    )


def panel_d_block(
    proof_y: list[float],
    bytecode_y: list[float],
    fixed_proof_y: float,
    fixed_bytecode_y: float,
) -> str:
    return (
        path(zip(X_RIGHT, proof_y))
        + "[ 39.851 19.9255 ] 0 d\n"
        + ORANGE
        + "\n"
        + path(zip(X_RIGHT, bytecode_y))
        + "[ 29.8883 19.9255 ] 0 d\n"
        + BLUE
        + "\n"
        + path([(X_RIGHT[0], fixed_proof_y), (X_RIGHT[-1], fixed_proof_y)])
        + ORANGE
        + "\n"
        + path([(X_RIGHT[0], fixed_bytecode_y), (X_RIGHT[-1], fixed_bytecode_y)])
        + "1 g\n[ ] 0 d\n"
        + BLUE
        + "\n"
        + circles(X_RIGHT, proof_y)
        + ORANGE
        + "\n"
        + squares(X_RIGHT, bytecode_y)
    )


def build_figure(summary: dict[str, Any], template: Path, output: Path) -> None:
    fixed = next(row for row in summary["results"] if row["target"] == "biozero-fixed")
    vanilla = sorted(
        (row for row in summary["results"] if str(row["target"]).startswith("vanilla-")),
        key=lambda row: int(row["dimension"]),
    )
    if [int(row["dimension"]) for row in vanilla] != EXPECTED_DIMS:
        raise ValueError("fresh data do not contain the seven expected dimensions")

    gas_map = linear_map(4774.24, 5289.72, 200.0, 2500.0)
    deploy_map = linear_map(4774.26, 5289.71, 0.8, 8.2)
    prove_map = log_map(3776.90, 4292.36, 1.0, 1000.0)
    size_map = linear_map(3776.92, 4292.36, 0.0, 38.0)

    gas_y = [gas_map(row["verifier_gas"]["mean"] / 1000.0) for row in vanilla]
    deploy_y = [deploy_map(row["deployment_gas"] / 1_000_000.0) for row in vanilla]
    prove_y = [prove_map(row["proof_time"]["mean"] / 1000.0) for row in vanilla]
    proof_y = [size_map(row["proof_size"]["mean"] / 1024.0) for row in vanilla]
    bytecode_y = [size_map(row["verifier_creation_bytecode_bytes"] / 1024.0) for row in vanilla]

    with pikepdf.Pdf.open(template) as pdf:
        page = pdf.pages[0]
        form = page.Resources.XObject["/Fm1"].Resources.XObject["/Im1"]
        stream = form.read_bytes().decode("latin1")

        stream = replace_between(
            stream,
            "1965.31 4795.58 m",
            "0.125488 0.129395 0.141113 rg\nq\n10 0 0 10 0 0 cm BT\n/R23 7.3325 Tf\n1 0 0 1 227.944 453.619 Tm",
            panel_block(X_LEFT, gas_y, gas_map(fixed["verifier_gas"]["mean"] / 1000.0)),
        )
        stream = replace_between(
            stream,
            "3444.55 4795.37 m",
            "0.125488 0.129395 0.141113 rg\nq\n10 0 0 10 0 0 cm BT\n/R23 7.3325 Tf\n1 0 0 1 375.869 453.621 Tm",
            panel_block(X_RIGHT, deploy_y, deploy_map(fixed["deployment_gas"] / 1_000_000.0)),
        )
        stream = replace_between(
            stream,
            "1965.31 3956.06 m",
            "0.125488 0.129395 0.141113 rg\nq\n10 0 0 10 0 0 cm BT\n/R23 7.3325 Tf\n1 0 0 1 227.944 353.885 Tm",
            panel_block(X_LEFT, prove_y, prove_map(fixed["proof_time"]["mean"] / 1000.0)),
        )
        stream = replace_between(
            stream,
            "3444.55 3796.05 m",
            "0.125488 0.129395 0.141113 rg\nq\n10 0 0 10 0 0 cm BT\n/R23 7.3325 Tf\n1 0 0 1 375.869 353.887 Tm",
            panel_d_block(
                proof_y,
                bytecode_y,
                size_map(fixed["proof_size"]["mean"] / 1024.0),
                size_map(fixed["verifier_creation_bytecode_bytes"] / 1024.0),
            ),
        )

        form.write(stream.encode("latin1"))
        output.parent.mkdir(parents=True, exist_ok=True)
        pdf.save(output, compress_streams=True, deterministic_id=True)

    with pikepdf.Pdf.open(output) as check:
        box = [float(value) for value in check.pages[0].MediaBox]
        if box != [0.0, 0.0, 350.0, 215.0]:
            raise ValueError(f"unexpected output MediaBox: {box}")
    if output.read_bytes().count(b"/Subtype /Image") != 0:
        raise ValueError("output unexpectedly contains a raster image")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    summary = json.loads(args.input.read_text(encoding="utf-8"))
    build_figure(summary, args.template.resolve(), args.output.resolve())
    print(f"saved {args.output}")
    print(f"template_sha256={sha256(args.template)}")
    print(f"output_sha256={sha256(args.output)}")


if __name__ == "__main__":
    main()
