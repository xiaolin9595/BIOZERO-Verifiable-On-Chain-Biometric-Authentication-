"""Figures for the report, drawn only from data/*.json and closed-form expressions.
Usage (from BioZERO_TR_v3/):  python -I analysis/make_figures.py
"""
import json
import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ped = json.load(open(os.path.join(ROOT, "data", "pedersen-bn254-gas.json"), encoding="utf-8"))
N = ped["dimension"]
rows = {r["label"]: r for r in ped["results"]}

plt.rcParams.update({"font.size": 8, "axes.linewidth": 0.6, "font.family": "sans-serif",
                     "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
                     "mathtext.fontset": "cm", "pdf.fonttype": 42,
                     "legend.frameon": True, "legend.edgecolor": "#bbbbbb", "legend.fancybox": False,
                     "legend.framealpha": 1.0, "xtick.direction": "out", "ytick.direction": "out"})
# palette and markers shared with the Groth16 cost figure (Fig. 3)
ORANGE, BLUE, GOLD, GREEN, BLACK = "#D95319", "#0072BD", "#EDB120", "#77AC30", "#000000"


def pass_prob(n, t, w):
    return 0.0 if t > n - w else math.comb(n - w, t) / math.comb(n, t)


def title(ax, text):
    ax.set_title(text, fontsize=8, fontweight="bold")


fig, (a, b) = plt.subplots(1, 2, figsize=(7.16, 2.6))

# (a) probability that w falsified coordinates all escape a t-sample
ts = list(range(0, N + 1))
for w, ls, mk in ((1, "-", "o"), (2, "--", "s"), (6, "-.", "^"), (13, ":", "D")):
    a.plot(ts, [pass_prob(N, t, w) for t in ts], color=BLUE, ls=ls, lw=1.2, marker=mk, ms=5,
           mfc="white", mew=1.0, markevery=16, label=f"$w={w}$")
for lab, t in (("$\\eta{=}1$", 7), ("$\\eta{=}4$", 28), ("$\\eta{=}8$", 56)):
    a.axvline(t, color=BLACK, lw=0.6, ls=":")
    a.text(t + 1.5, 1.03, lab, fontsize=6.5)
a.set_xlabel("Checked coordinates $t$ (out of $N{=}128$)")
a.set_ylabel("Acceptance probability")
a.set_ylim(0, 1.12)
a.set_xlim(0, N)
a.legend(loc="upper right", ncol=2, fontsize=6.5)
title(a, "(a) Sparse falsification under sampling")

# (b) transaction gas vs t: complete verifier, kernel, and the complete in-circuit verifier.
# The four Spot points are the N=128 rows of the dedicated enine sweep; Full is
# the N=128 endpoint of the earlier enine COMPLETE campaign. The kernel stays
# on its original recorded file by design.
hom = json.load(open(os.path.join(
    ROOT, "data", "hom-complete-enine-2026-10-28.json"), encoding="utf-8"))
spot = json.load(open(os.path.join(
    ROOT, "data", "spotcheck-n-sweep-enine-2026-10-28.json"), encoding="utf-8"))
circ = json.load(open(os.path.join(
    ROOT, "data", "circuit-complete-enine-2026-10-28.json"), encoding="utf-8"))
spot128 = [r for r in spot["results"] if r["dimension"] == N]
assert {r["eta"] for r in spot128} == {1, 2, 4, 8}
assert all(all(r["controls"][c] is True for c in
               ("replayRejected", "staleProofRejected", "wrongEnrollmentRejected",
                "tamperedResponseRejected")) for r in spot128)
full = next(r for r in hom["results"] if r["samples"] == N)
assert all(full["controls"][c] is True for c in
           ("replayRejected", "staleProofRejected", "wrongEnrollmentRejected",
            "tamperedResponseRejected"))
cpts = sorted(
    [(r["samples"], r["medianGasUsed"]) for r in spot128]
    + [(full["samples"], full["medianGasUsed"])]
)
b.plot([p[0] for p in cpts], [p[1] for p in cpts], ls="-", color=ORANGE, lw=1.2, marker="s", ms=5,
       mfc="white", mew=1.0, label="Homomorphic, complete verifier")
kpts = [(rows[k]["samples"], rows[k]["medianGasUsed"]) for k in ("lambda-1", "lambda-2", "lambda-4", "lambda-8", "full-check")]
b.plot([p[0] for p in kpts], [p[1] for p in kpts], ls="--", color=BLUE, lw=1.0, marker="o", ms=5,
       mfc="white", mew=1.0, label="Homomorphic, equations only (kernel)")
cg = next(r["medianGasUsed"] for r in circ["results"] if r["dimension"] == N)
b.axhline(cg, color=BLACK, lw=1.2, ls="--", label="In-circuit, complete verifier")
b.text(4, cg * 1.35, f"{cg:,} gas, independent of $N$", fontsize=6.5)
b.set_yscale("log")
b.set_xlabel("Checked coordinates $t$ (out of $N{=}128$)")
b.set_ylabel("Transaction gas")
b.set_xlim(-2, N + 2)
b.set_ylim(1.5e5, 4e7)
b.legend(loc="lower left", bbox_to_anchor=(0.35, 0.28), fontsize=6.5)
title(b, "(b) Cost of the homomorphic checks")

fig.tight_layout(pad=0.6)
os.makedirs(os.path.join(ROOT, "figures"), exist_ok=True)
fig.savefig(os.path.join(ROOT, "figures", "fig_sampling_cost.pdf"))
print("saved figures/fig_sampling_cost.pdf")
