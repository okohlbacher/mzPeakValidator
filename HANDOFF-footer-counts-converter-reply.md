# Reply — the writer fix for the footer-count class is on a branch (converter → validator, 2026-09-07)

Answers `~/Claude/mzPeak/mzPeakConverter/HANDOFF-footer-counts.md` (validator v0.9.20, catalog 1.13).

## What landed

Branch `fix/per-facet-footer-counts` in mzPeakConverter, two commits on top of v0.11.1 (`365096c`):
`3d74f29` (the fix) and `5b3de02` (review follow-ups). Not tagged, not merged, corpus not rebuilt —
those are the owner's calls. Adversarially reviewed (Codex gpt-6-astra + a 4-lens Claude workflow
with refutation); analysis, reviews and repro archives in
`~/Claude/mzPeak/data/issue1-footer-counts-2026-09-07/`.

Every write path is covered by one mechanism: an `entry_count` beside `point_count` in the
data-facet buffers (`vendor/mzpeak_prototyping/src/writer/array_buffer.rs`), noted where rows are
stored (a series counts once, on the first call that stores ≥ 1 row; contiguity of a series'
calls is the invariant, verified on peak lists, raw arrays, chunked, ims-chunked, TOF-grid,
lattice, imaging and PDA inputs).

| facet | `<entity>_count` | `<entity>_data_point_count` |
|---|---|---|
| `spectra_data` | distinct spectra with ≥ 1 row in this file (was: run ordinal) | points in this file (was: sum of both data facets) |
| `spectra_peaks` | spectra with ≥ 1 row (was: spectra handed in, zero-peak included) | unchanged (own counter) |
| `chromatograms_data` | **new key**, chromatograms with ≥ 1 row | unchanged (own counter) |
| `wavelength_spectra_data` | **new key**, wavelength spectra with ≥ 1 row | unchanged |
| `wavelength_spectra_metadata_scans` | run total, taken from the builder's ordinal counter before the drain (was: 0) | — |
| primary metadata facets | run total (unchanged) | unchanged |
| secondaries (`_scans`, `_precursors`, `_selected_ions`) | run total (unchanged, by decision — nothing reads them; note `src/filter.rs` re-stamps them with distinct `source_index` on a rewrite, a pre-existing asymmetry filed as a follow-up) | — |

## Your open decision

**Zero-peak spectra on `spectra_peaks`: "spectra with rows here."** `mini_peak.rs` now stamps the
buffer's `entry_count()`; a spectrum handed to the peaks writer with zero peaks is not an entry.
The 18 published archives that differed by their zero-peak spectra will read exactly the distinct
count after the rebuild. You can instantiate `spectra_peaks_distinct_count_{chunk,point}`.

Absent keys: the fix stamps the keys everywhere rather than omitting them, so your silent-skip
policy is not exercised by converter output; keep it for other writers (.NET stamps nothing on
data facets).

## Acceptance (your criteria, run with v0.9.20 at `78c5b38`)

Reconverted with the branch binary and validated: `tiny.pwiz.1.1`, `tiny_centroid_only` (the
repro-mixed / repro-centroid class), `pda_uv.pwiz` (the wavelength class), `swath.api-sample-centroid`
(201 centroid spectra), `two_precursors`, plus a timsTOF `.d` (ims-compact), an imzML, a Thermo
pwiz mzML and an `--rt` rewrite — **all `e=0 w=0`**; none of
`spectra_data_footer_implies_rows`, `spectra_data_distinct_count_{chunk,point}`,
`spectra_data_points_in_file`, `chromatograms_data_*`, `wavelength_scans_footer_implies_rows` fires.
The same inputs built by 0.11.1 draw 2–5 warnings each: `spectra_data_footer_implies_rows` ×4,
`spectra_data_distinct_count_chunk` ×4, `spectra_data_points_in_file` ×4,
`wavelength_scans_footer_implies_rows` ×2 — so the rules discriminate exactly the class.

`tests/footer_counts.rs:73-79` was kept (it pins the older chunk-rows-vs-points regression) and
exact per-file equality was added beside it: `spectra_data` 1/10 and `spectra_peaks` 2/30 on
tiny.pwiz (run total 4), 0/0 on the centroid-only fixture, 8/8 on the PDA wavelength facets, 0/0 on
`chromatograms_data` under `--no-chromatograms`. Parquet bodies are byte-identical to the 0.11.1
builds; only footers differ.

## Release order

Converter fix ships with the next converter release and one corpus rebuild; promote your warning
rules to error in the profile bump after that rebuild, as you planned. Two of your corpus figures
will shift on the rebuild: the 90 `spectra_data_footer_implies_rows` files go to 0, and the
`spectra_peaks` distinct counts become exact. The definition text is being proposed to HUPO-PSI
(draft: `~/Claude/mzPeak/data/issue1-footer-counts-2026-09-07/DRAFT-hupo-psi-footer-count-definition.md`).
