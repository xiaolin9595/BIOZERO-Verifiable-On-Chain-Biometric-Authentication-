#!/usr/bin/env python3
"""Plot Fig. 3 from frozen enine samples; optionally import the grid evidence.

No benchmark is run. Existing Vanilla/BioZero and SpotCheck files are read only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics as st
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
DIMS = [2, 4, 8, 16, 32, 64, 128]
GRID = DATA / 'circuitcheck-grid-enine-2026-10-28.json'
BASE = DATA / 'fresh-native-fig3-full-2026-10-28.json'
SPOT = DATA / 'spotcheck-n-sweep-enine-2026-10-28.json'


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2) + '\n')


def import_grid(source: Path) -> None:
    proving = read(source / 'results/proving.json')
    gas = read(source / 'results/verifier-gas.json')
    verification = read(source / 'results/verification.json')
    manifest = read(source / 'results/manifest.json')
    assert verification['overall'] == 'PASS'
    assert len(verification['checks']) == 168 and all(c['pass'] for c in verification['checks'])
    assert 'enine' in (source / 'metadata/environment.before.txt').read_text()
    checked = []
    for entry in manifest['files']:
        path = source / entry['path']
        if path.is_file():
            assert sha(path) == entry['sha256'], entry['path']
            checked.append(entry['path'])
    assert proving['dimensions'] == gas['dimensions'] == DIMS
    rows = []
    for p, g in zip(proving['results'], gas['results']):
        n = p['dimension']
        assert n == g['dimension'] and p['verification']['allVerified']
        assert g['overall'] == 'PASS' and g['eip170Compliant']
        # ZoKrates writes proof and public inputs together; snarkjs separates
        # them. Sum both original JSON file lengths, preserving serialization.
        sizes = []
        for i in range(1, 11):
            stem = f'auth_distance_{n}-measured-{i:02}'
            paths = [source / f'results/proving/raw/{stem}-{suffix}.json'
                     for suffix in ('proof', 'public')]
            assert all(str(path.relative_to(source)) in checked for path in paths)
            sizes.append(sum(path.stat().st_size for path in paths))
        rows.append({'dimension': n, 'proof_ms': p['provingPipeline']['endToEndMs']['values'],
                     'proof_public_json_bytes': sizes, 'gas': g['validVerifyGas'],
                     'deployment_gas': g['deploymentGas'],
                     'creation_bytes': g['creationBytecodeBytes'],
                     'runtime_bytes': g['runtimeBytecodeBytes'],
                     'constraints': p['constraints'], 'public_inputs': p['publicInputs']})
    save(GRID, {'hostname': 'enine', 'source_run': 'circuitcheck-only-resume-20261028T125516Z',
                'source_verification': verification, 'manifest_checked_files': len(checked),
                'protocol': proving['protocol'], 'gas_protocol': gas['protocol'],
                'timing_scope': 'cold Node child, witness calculation through proof/public JSON writes; excludes child startup',
                'size_scope': 'sum of original pretty-printed proof and public JSON file sizes; not binary Groth16 proof size',
                'source_hashes': {name: sha(source / name) for name in (
                    'results/proving.json', 'results/verifier-gas.json', 'results/manifest.json',
                    'results/verification.json', 'metadata/environment.before.txt')},
                'results': rows})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--import-source', type=Path)
    args = parser.parse_args()
    if args.import_source:
        import_grid(args.import_source)
    grid, base, spot = read(GRID), read(BASE), read(SPOT)
    assert grid['hostname'] == base['environment']['hostname'] == 'enine'
    assert grid['source_verification']['overall'] == 'PASS'
    assert read(DATA / 'spotcheck-n-sweep-enine-2026-10-28-verification.json')['overall'] == 'PASS'
    assert [r['dimension'] for r in grid['results']] == DIMS
    vanilla = sorted([r for r in base['results'] if r['target'].startswith('vanilla-')], key=lambda r: r['dimension'])
    assert [r['dimension'] for r in vanilla] == DIMS
    fixed = next(r for r in base['results'] if r['target'] == 'biozero-fixed')
    series = {}
    for name, rows in [('Vanilla', vanilla), ('BioZero fixed', [fixed] * 7)]:
        series[name] = [{'dimension': n, 'proof_ms': r['proof_time']['measured_runs'],
                         'proof_public_json_bytes': r['proof_size']['measured_runs'],
                         'gas': r['verifier_gas']['measured_runs'], 'deployment_gas': r['deployment_gas'],
                         'creation_bytes': r['verifier_creation_bytecode_bytes']} for n, r in zip(DIMS, rows)]
    series['CircuitCheck'] = grid['results']
    for rows in series.values():
        for row in rows:
            assert all(math.isfinite(x) and x > 0 for key in ('proof_ms', 'gas', 'proof_public_json_bytes') for x in row[key])
    for r in grid['results']:
        assert len(r['proof_ms']) == len(r['proof_public_json_bytes']) == 10
        assert len(r['gas']) == 5 and r['runtime_bytes'] <= 24576

    plt.rcParams.update({'font.family': 'sans-serif', 'font.size': 8,
                         'axes.labelsize': 8, 'axes.titlesize': 9,
                         'xtick.labelsize': 7, 'ytick.labelsize': 7,
                         'legend.fontsize': 6.5, 'pdf.fonttype': 42,
                         'axes.spines.top': False, 'axes.spines.right': False})
    fig, axs = plt.subplots(2, 2, figsize=(7.16, 5.4))
    a, b, c, d = axs.flat
    styles = {'Vanilla': ('#D55E00', 's', '--'), 'BioZero fixed': ('#333333', None, ':'),
              'CircuitCheck': ('#0072B2', '^', '-')}
    x = list(range(7))
    for name, rows in series.items():
        color, marker, ls = styles[name]
        kw = dict(color=color, marker=marker, linestyle=ls, markersize=4, linewidth=1.2, markerfacecolor='white')
        a.plot(x, [st.mean(r['gas']) / 1e6 for r in rows], label=name, **kw)
        b.plot(x, [r['deployment_gas'] / 1e6 for r in rows], **kw)
        c.errorbar(x, [st.mean(r['proof_ms']) / 1000 for r in rows],
                   yerr=[st.stdev(r['proof_ms']) / 1000 for r in rows], capsize=2, **kw)
        d.plot(x, [r['creation_bytes'] / 1024 for r in rows], label=f'{name}: code', **kw)
        d.plot(x, [st.mean(r['proof_public_json_bytes']) / 1024 for r in rows],
               color=color, marker='o', markersize=3, markerfacecolor='white',
               linestyle=':', linewidth=0.9, label=f'{name}: JSON')
    spot_colors = ['#009E73', '#CC79A7', '#E69F00', '#56B4E9']
    spot_markers = ['o', 'v', 'D', 'x']
    for eta, color, marker in zip([1, 2, 4, 8], spot_colors, spot_markers):
        rows = sorted([r for r in spot['results'] if r['eta'] == eta], key=lambda r: r['dimension'])
        assert [r['dimension'] for r in rows] == DIMS
        assert all(r['medianGasUsed'] == st.median(r['gasUsed']) for r in rows)
        a.plot(x, [r['medianGasUsed'] / 1e6 for r in rows], color=color, marker=marker,
               markersize=3, linewidth=0.9, linestyle='-.',
               label=rf'SpotCheck $\eta={eta}$ (full tx)')
    for ax, title, ylabel in zip(axs.flat,
        ['(a) Verification / authentication gas', '(b) Bare-verifier deployment',
         '(c) Witness + proof generation', '(d) Creation code / proof + inputs JSON'],
        ['Gas (million)', 'Gas (million)', 'Time (s)', 'Size (KiB)']):
        ax.set_title(title, fontweight='bold')
        ax.set_xticks(x, [str(n) for n in DIMS])
        ax.set_xlabel('Template dimension $N$')
        ax.set_ylabel(ylabel)
        ax.grid(axis='y', color='#dddddd', linewidth=0.5)
    a.set_yscale('log'); a.set_ylim(0.19, 220)
    a.set_yticks([0.25, 1, 4, 16]); a.yaxis.set_major_formatter(ScalarFormatter())
    a.legend(loc='upper left', ncol=2, columnspacing=0.5, handlelength=1.5, frameon=False)
    b.set_ylim(0, 9)
    c.set_yscale('log'); c.set_ylim(1, 1300)
    c.set_yticks([1, 3, 10, 30, 100, 300, 1000]); c.yaxis.set_major_formatter(ScalarFormatter())
    d.set_ylim(0, 48); d.legend(loc='upper left', ncol=2, frameon=False, columnspacing=0.6, handlelength=1.5)
    fig.tight_layout(pad=0.7, h_pad=1.1, w_pad=1.0)
    output = ROOT / 'figures/fig3_with_circuitcheck.pdf'
    # Exclude wall-clock timestamps so independently regenerated PDFs hash identically.
    fig.savefig(output, metadata={'CreationDate': None, 'ModDate': None})
    fig.savefig(output.with_suffix('.png'), dpi=180)
    plt.close(fig)
    report = {'overall': 'PASS', 'dimensions': DIMS, 'series': series,
              'spotcheck': spot['results'], 'preservation': 'Vanilla/BioZero raw samples and all 28 SpotCheck settings unchanged',
              'scope': 'bare verifiers for three base series; full benchmark authentication for SpotCheck in panel (a) only',
              'source_hashes': {p.name: sha(p) for p in (BASE, SPOT, GRID)}, 'figure_sha256': sha(output)}
    save(DATA / 'fig3-with-circuitcheck-verification.json', report)
    with (DATA / 'fig3-with-circuitcheck.csv').open('w', newline='') as f:
        w = csv.writer(f); w.writerow(['series', 'N', 'gas_mean', 'deployment_gas', 'witness_proof_mean_ms', 'sample_sd_ms', 'creation_bytes', 'proof_public_json_mean_bytes'])
        for name, rows in series.items():
            for r in rows:
                w.writerow([name, r['dimension'], st.mean(r['gas']), r['deployment_gas'], st.mean(r['proof_ms']), st.stdev(r['proof_ms']), r['creation_bytes'], st.mean(r['proof_public_json_bytes'])])
    print(f'PASS: {output}; CircuitCheck 7/7 dimensions, SpotCheck 28/28 settings retained')


if __name__ == '__main__':
    main()
