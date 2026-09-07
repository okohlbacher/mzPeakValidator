# Handoff — catch self-consistent peak-pairing corruption (mzpeak-0.9 profile, catalog 1.12 → 1.13)

mzPeakValidator 0.9.18/0.9.19 passes an archive whose every centroid intensity is paired with the
wrong m/z. Nothing in the catalog reads m/z and intensity together, no chunk decoder exists, and the
archive's own TIC/BPI/base-peak aggregates were recomputed FROM the corrupt arrays — so a future
`aggregate_matches` rule would pass it too (verified). This handoff asks for the ledger that makes a
self-gating rule visible, a delta decoder with two structural chunk rules, and one physics-based
detector with honest thresholds. mzPeakConverter side: v0.9.1 (`64d335d`).

## What happened (so the rules target the real thing)
Shimadzu `.lcd` files that store **no profile signal** come back from the vendor API
(`Shimadzu.LabSolutions.IO`, the same DLL msconvert uses — its output is byte-identical) with the
centroid list's intensities shifted 1–7 positions early (`[s alien values] + truth[0:n-s]`, s=3 in
~94 % of spectra) and the last peak missing. The m/z axis is exact. Values are bit-exact once
shifted — only the pairing is wrong. Files that store profile signal are exact. Measured against
the vendor's own mzML exports with `tools/compare_lcd_native_mzml.py`:

| archive | spectra | bit-exact | rotation histogram |
|---|---|---|---|
| `DIA_Hela_20ng ….native.pre-fix-0.9.0.mzpeak` | 21,500 | 0 | {1: 923, 3: 20,139, 7: 438} |
| `DIA_Hela_100ng ….native.pre-fix-0.9.0.mzpeak` | 22,113 | 0 | {1: 2,645, 3: 19,024, 7: 444} |
| `Blind_P1_pos_012.mzpeak` (published corpus) | 13,200 | 13,200 | {} |

Physics that adjudicated it: polysiloxane 445.1188, M+1/M = 0.015 in the corrupt archive vs 0.436
in the export (Si₆ theory 0.41–0.44). The archives are preserved as **red fixtures** at
`~/Claude/mzPeak/mzPeakConverter/vendor-examples/Shimadzu-2026-08-21/*.native.pre-fix-0.9.0.mzpeak`
(SHA-256 in `PRE-FIX-0.9.0.sha256` alongside). All are MS:1003089 delta-chunked — no numpress needed.

## P0 — `rules_evaluated` / `skipped` ledger  (severity: infrastructure, blocks everything below)
**Invariant:** every rule instance in the profile ends a run in exactly one of
`passed | failed | skipped(reason)`, and the report lists them. Today a self-gating rule that
finds no applicable facet returns silently (only `p_grouped_monotonic` reports an info skip,
`core.py:1170`), and `--quick` drops every DATA_SCAN primitive before execution (`core.py:1951`)
with no trace. A chunk-aware detector that no-ops on a point-layout archive is then indistinguishable
from one that ran and passed. Add `Report.skip(rule_id, reason)` and call it on EVERY early return
and on the quick-mode exclusion; emit `rules_evaluated`, `rules_skipped[{id, reason}]` in JSON and
a one-line count in the text summary; batch mode (`validate_everything.py`) must preserve it.

## P0 — MS:1003089 delta decoder + two structural chunk rules  (error)
Decoder: `mz[0] = mz_chunk_start; mz[k] = start + cumsum(mz_chunk_values)[k-1]` — a cumsum, no
dependency. Register it so DATA_SCAN primitives can ask for decoded `(mz, intensity)` per chunk row.
Rules (self-skip with a ledger reason on non-chunk facets or other encodings):
- `chunk_value_lengths` — invariant: `len(intensity) == len(mz_chunk_values) + 1` for every chunk row.
- `chunk_delta_sum` — invariant: `mz_chunk_start + Σ mz_chunk_values == mz_chunk_end` within
  `rtol 1e-9` (the converter writes both; drift means a corrupted or re-encoded chunk).
Fixtures from `make_fixtures._chunk_data` (switch it to delta for these): BAD = one intensity
truncated / one delta perturbed; FIXED = untouched. New rule must pass FIXED while failing BAD.

## P1 — `isotope_ratio_sanity`  (warning; run-level)
The detector that would have caught this. Invariant, per run: among the top-K peaks of each
MS1 spectrum, for each peak with a +1.00335/z partner (z ∈ 1..3, 10 ppm), the fraction whose
intensity ratio M+1/M exceeds the carbon-count bound (≈ 0.011 × m/z /z × 1.5 slack) must stay
below a threshold; rotated pairing makes ratios random. **Thresholds must be fitted, not assumed**
— measured under the natural reading (top-20) the separation is too narrow to ship:

| K | corrupt 20ng | corrupt 100ng | clean 20ng mzML-lane |
|---|---|---|---|
| 20 | 17.8 % | 16.3 % | 12.8 % |
| 50 | 26.7 % | 25.8 % | 17.0 % |

Fit K, z-range, ppm and the run-level threshold so the rule **fires on both preserved DIA archives
and is silent on** `Blind_P1_pos_012.mzpeak`, `HEK_PosOAD1.mzpeak`, and the `.from-mzml` builds of
the same DIA runs. Self-skip (with reason) when < 200 usable pairs. Known FP risks to keep in the
doc string: saturation, chimeric DIA MS2 (restrict to MS1), isotope-labelled or Si/metal-rich samples.

## P1 — `dual_facet_consistency`  (warning; SECONDARY — cannot fire where the bug lives)
Only dual-facet archives have both; the affected class is centroid-ONLY, so this is a guard for
future dual defects, not the detector for this one. Measured calibration on genuine dual archives:
centroid m/z lands on a profile sample (< 0.01 Th) for **100 %** (Blind) / **95.9 %** (HEK) of
centroids — but the centroid intensity is an **integrated area, 3.3–3.6× the profile apex height**,
so compare **ranks** (Spearman per spectrum, median over the run) never magnitudes. Threshold from
the measured genuine distribution, not an assumed 0.95.

## Acceptance (converter side will assert this)
1. `validate_everything.py` only — `smoke_test.py` auto-quicks files > 50 MB and would silently skip
   every rule above on the 840 MB DIA archives.
2. Ledger shows the new rules as `evaluated` on the DIA archives and `skipped(no chunk facet)` /
   `skipped(no dual facets)` where appropriate.
3. `isotope_ratio_sanity` **fires** on both `*.native.pre-fix-0.9.0.mzpeak`, **silent** on Blind, HEK
   and the `.from-mzml` DIA builds.
4. Warnings never fail validation (`core.py:877`); the converter's gate will grep for the warning IDs
   explicitly, so keep the IDs stable: `isotope_ratio_sanity`, `dual_facet_consistency`,
   `chunk_value_lengths`, `chunk_delta_sum`.
5. Bump `CATALOG_VERSION` in `core.py:84` and `profile.json` `rule_primitive_catalog` together (1.13).

## Known, not yours
`meta_scan_settings_valid` fails on any mzML that declares `scanSettings` targets (the converter
serialises each target as a list of params, not an object). Pre-existing in v0.9.0, converter bug,
tracked there. Do not relax the rule.
