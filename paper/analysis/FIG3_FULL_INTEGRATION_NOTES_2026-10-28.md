# Fig. 3 full-campaign integration notes (2026-10-28)

Status: figure and data are prepared, but the paper sections are intentionally
unchanged pending the final fresh run. The packaged measurements are the
recovered native campaign from 2026-06-05, not fresh 2026-10-28 measurements
and not the missing original-paper raw data.

## Prepared artifacts

- Data: `data/recovered-native-fig3-full-2026-10-28.{json,csv}`.
- Figure: `figures/fig3_full_recovered_native_2026-10-28.pdf`.
- Verification: `data/recovered-native-fig3-full-verification-2026-10-28.json`.
- Generator: `analysis/make_fig3_full.py`.

Run from `BioZERO_TR_v3/` with `python3 analysis/make_fig3_full.py`. The
generator fixes `SOURCE_DATE_EPOCH`, records a semantic hash of every plotted
value and the versioned figure specification, and preserves an existing PDF
only when its input hash, semantic hash, byte hash, and raster-free structural
check all match. This avoids Matplotlib-version-specific font-subset rewrites.
For a first render in a controlled build environment,
`PYTHONHASHSEED=0 SOURCE_DATE_EPOCH=1793145600 python3 analysis/make_fig3_full.py`
is also supported.

The Vanilla series uses the native 2026-06-05 campaign with the single
shadowing `res` declaration removed at each dimension. Setup/key/verifier
artifacts were reused/recovered from that campaign. The seven Vanilla points
each retain five proving samples and five gas transactions. BioZero is one
fixed circuit, not seven dimension-specific reruns: its horizontal series uses
five proving samples and all 30 measured gas transactions after the five
warm-ups recorded by the source campaign.

## Paper locations to update only after the final-data decision

1. `sections/06-cost.tex`, subsection `Local proof-processing overhead`:
   replace the current partial inline table inside the `figure*` labelled
   `fig:isc` with the selected final PDF. Do not overwrite the recovered PDF
   if a fresh run arrives; package fresh data and its figure under a new dated
   filename.
2. The `fig:isc` caption must identify the exact data class. For this prepared
   figure it must say: recovered 2026-06-05 native campaign; Vanilla
   shadow-line repair; reused/recovered setup artifacts; BioZero fixed across
   N; proving bars are sample SD with n=5; BioZero gas n=30 and Vanilla gas
   n=5; N=128 uses a local unlimited-contract-size chain and exceeds EIP-170.
3. The two paragraphs immediately following `fig:isc` currently describe the
   superseded 2026-10-27 partial reconstruction. Replace them only when the paper
   adopts a final dataset; do not silently reinterpret them as describing this
   recovered-native campaign.
4. `sections/08-discussion.tex` currently says the separate reconstruction
   completed only BioZero and Vanilla N=2/4. Update that statement only if the
   recovered-native or fresh full campaign is formally adopted.
5. `sections/C-provenance.tex` currently points to the partial 2026-10-27 Fig. 3
   files and hashes. Add the selected final dated JSON/CSV/verification hashes
   and its environment limitations when the paper is switched.
6. Synchronize the explanatory snapshots in `README.md`, `OPEN_ITEMS.md`, and
   `artifact/README.md` at the same time as the paper change. Until then, the
   existing partial narrative remains untouched.

## Suggested caption if this recovered snapshot is selected

> Recovered native comparison from the 2026-06-05 reconstruction campaign,
> not the missing original Fig. 3 raw data and not a fresh 2026-10-28 run.
> Vanilla ZKBio uses the minimal public-`res` shadow-line repair and
> reused/recovered campaign setup artifacts; BioZero is a fixed threshold
> circuit independent of N. Proving points show mean and sample SD over five
> runs. Gas uses five transactions per Vanilla dimension and 30 measured
> BioZero transactions after five warm-ups. The N=128 Vanilla verifier exceeds
> EIP-170 and was measured only on a local unlimited-contract-size chain.

