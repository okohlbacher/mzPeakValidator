# Handoff — catch data-facet footer counts that disagree with the file (mzpeak-0.9 profile, catalog 1.12 → 1.13)

mzPeakValidator 0.9.19 passes 201/201 published archives with 0 warnings while **84** of them ship an
empty `spectra_data.parquet` whose footer declares `spectrum_count` up to 307,590 and
`spectrum_data_point_count` up to 3.7 G, **22** more over-declare on a non-empty `spectra_data`
(PXD076001: 255,623 declared, 2,521 present), and one PDA-UV archive declares
`wavelength_spectrum_count = 0` on a populated scans facet. This is
okohlbacher/mzPeakConverter#1 (pjones, 2026-09-04): his C++ reader planned reads from the footer
and issued 893,769 queries against an empty table. Full analysis, both adversarial reviews, the
corpus scan and the repro archives:
`~/Claude/mzPeak/data/issue1-footer-counts-2026-09-07/` (`ANALYSIS.md`, `scan-public.csv`,
`fixtures/`). Converter side: v0.11.1 (`365096c`); the writer fix is not landed yet.

## What happens (so the rules target the real thing)

The reference writer stamps the **archive-wide** spectrum ordinal as `spectrum_count` onto every
spectrum facet except `spectra_peaks` (`vendor/mzpeak_prototyping/src/writer.rs:1146-1151,
:1194, :1220, :1245, :1270`), and stamps `spectrum_data_point_count` on `spectra_data` as the
**sum of both data facets' points** (`:1151-1157`). `spectra_peaks` stamps its own counters, but
counts spectra *handed* to it including zero-peak spectra (`writer/mini_peak.rs:274-279`).
The wavelength scans facet takes its count from a builder that was drained one call earlier
(`writer.rs:1313-1319` vs `:1345-1348`), so it reads 0. Upstream `mobiusklein/mzpeak_prototyping`
is identical. The spec (checkout 9880070) never mentions either key; its read-planning source is
`spectra_metadata` `MS:1003060` / `MS:1003059` per spectrum (`docs/schemas/spectra.md:12-17`).

Footers of the two repro archives (`fixtures/FOOTERS.txt` has the full dump incl. the PDA-UV one):

| archive · facet | rows | distinct index present | `spectrum_count` | `spectrum_data_point_count` |
|---|---:|---:|---:|---:|
| repro-centroid · `spectra_data` | 0 | 0 | **201** | **296,228** |
| repro-centroid · `spectra_peaks` | 2,577 (chunk) | 201 | 201 | 296,228 |
| repro-mixed · `spectra_data` | 1 (chunk) | 1 (`{1}`) | **4** | **40** (file holds 10) |
| repro-mixed · `spectra_peaks` | 2 (chunk) | 2 (`{0, 3}`) | **3** (spectrum 2 has zero peaks) | 30 |
| waters-pda-uv · `wavelength_spectra_metadata_scans` | 8 | 8 | **`wavelength_spectrum_count` = 0** | — |

Corpus scan (`scan-public.csv`, 2,055 facets): `rows == 0 ∧ count > 0` on 84 `spectra_data`,
1 `spectra_peaks`, 67 + 67 spectrum secondaries, 201 + 198 chromatogram secondaries; declared ≠
distinct on 22 `spectra_data` and 18 `spectra_peaks` (the 18 are exactly the zero-peak spectra).

## Why the validator passes today (four stacked reasons, all verified)

1. **No rule reads the footer of any data facet.** `spectrum_count_agreement` targets
   `spectra_metadata` only (`profiles/mzpeak-0.9/rules/numeric.rules.json:22-31`). Nothing
   instantiates `footer_count_equals_rows` on `spectra_data` / `spectra_peaks` /
   `chromatograms_data`, and there is no `chromatogram_count_agreement` at all.
2. **The doc string knew.** `data_points_sum` (`:33-44`) says "the writer's spectra_data footer is
   unreliable" — a day-one observation (HANDOFF at f7048c5:58, June: point count copied from the
   peaks facet, `spectra_peaks` 34 vs 48) with the upstream issue planned and never filed
   (`CLAUDE.md:107`). Peter filed it three months later.
3. **The `*_imply_rows` rules cannot see it by construction.** `count_implies_rows`
   (`core.py:1859-1884`) compares a *metadata column sum* with `num_rows`; for a centroid-only run
   `number_of_data_points` is all null and `spectra_data` has 0 rows — consistent, and the footer
   is never read. These rules are correct for a metadata-planned reader and orthogonal to a
   footer-planned one; they need a sibling, not a tweak.
4. **On chunk-layout archives (182/201) 12 numeric rules no-op** because they are gated on
   `point.*` columns: no FK on `chunk.spectrum_index` (only the warning-level `chunk_bounds`),
   no count, monotonic, finite, non-negativity or dtype check reaches the data facets. The 19
   point-layout archives get 23 rules. Also `chrom_point_fk_data_split` is gated on
   `chunk.chromatogram_index` while `chromatograms_data` is point layout in 201/201 archives, and
   the `aux_arrays_*` rules gate on packed column names the split layout never has. "PASS" says
   little about data-facet integrity on this corpus.

Note on `spectrum_count_agreement`: on the split layout `spectrum.index` is absent, `has()` fails
and the primitive falls back to `num_rows` (`core.py:1099-1101`) — correct today, but it is the
fallback path, not the `count_column` path the doc describes.

## Rules to add (in landing order)

### R1 — `footer_count_implies_rows`  (NEW primitive, footer-only, **not** DATA_SCAN)

Semantics-neutral: it does not decide run-total vs per-file, it flags the one state no reader can
use — a declared count > 0 on a facet with `num_rows == 0`, and the converse (`rows > 0` with
count 0, the 0.9.1 chromatogram-counter class and the wavelength scans case). Because it is
footer-only it runs under `--quick`, in `smoke_test.py`'s > 50 MB path (`smoke_test.py:62-63`)
and in remote range-request mode.

```json
{"id":"spectra_data_footer_implies_rows","primitive":"footer_count_implies_rows","severity":"warning","recovery":"rederive",
 "doc":"spectra_data footer spectrum_count / spectrum_data_point_count must be 0 when the file has 0 rows and > 0 when it has rows. The reference writer stamps the run-wide counters on every facet, so a centroid-only run declares hundreds of thousands of spectra on an empty file and a footer-planned reader (mzPeakConverter#1) queries every one. Advisory until HUPO-PSI defines the keys.",
 "params":{"file":"spectra_data","footer_keys":["spectrum_count","spectrum_data_point_count"]}}
{"id":"spectra_peaks_footer_implies_rows", ... "params":{"file":"spectra_peaks","footer_keys":["spectrum_count","spectrum_data_point_count"]}}
{"id":"chromatograms_data_footer_implies_rows", ... "params":{"file":"chromatograms_data","footer_keys":["chromatogram_data_point_count"]}}
{"id":"wavelength_scans_footer_implies_rows", ... "params":{"file":"wavelength_spectra_metadata_scans","footer_keys":["wavelength_spectrum_count"]}}
```

Primitive sketch (~12 lines): for each key, `v = ar.footer(f, key)`; **absence policy must be
explicit** — `footer_count_equals_rows` reports an absent key as a warning (`core.py:1082-1083`);
R1 should *skip silently* on absence (the converter may stop stamping the key on some facets, and
.NET never stamps it on data facets), and say so in its doc. Non-int → error as in `:1085-1088`.
`rows = ar.num_rows(f)`; `iv > 0 and rows == 0` → finding "footer {key}={iv} but the file has 0
rows"; `rows > 0 and iv == 0` → finding. Fires today on 84 + 1 + 1 corpus facets and both repros.

### R4 — `chromatogram_count_agreement`  (existing primitive, error)

The missing twin of `spectrum_count_agreement`; corpus is 201/201 consistent, so no fallout.

```json
{"id":"chromatogram_count_agreement","primitive":"footer_count_equals_rows","severity":"error","recovery":"rederive",
 "params":{"file":"chromatograms_metadata","footer_key":"chromatogram_count","count_column":"chromatogram.index"}}
```

### FK entries for the chunk layout and the point chromatogram facet  (existing `foreign_key`)

Bigger integrity gap than the footer keys: add `chunk.spectrum_index → spectra_metadata.index`
for `spectra_data` and `spectra_peaks`, and `point.chromatogram_index → chromatograms_metadata.index`
(today only the never-satisfied `chunk.chromatogram_index` entry exists). `p_foreign_key`
already accumulates the distinct child set (`core.py:1229-1232`), which R2 reuses.

### R2 — distinct-index agreement  (extend `footer_count_equals_rows`, DATA_SCAN, warning)

Correct only under the **per-file** definition (distinct `spectrum_index` with ≥ 1 row in this
file) — land it with the converter release that adopts it, or land now at warning and accept 22
hits. Add an optional `distinct_column` param (mutually exclusive with `count_column`): `actual =
|∪ pc.unique(batch)|` over `ar.iter_batches(f, distinct_column)`; self-skip under `_quick` like
the `count_column` branch (`:1095-1096`). Two entries per facet so it is layout-agnostic (each
self-gates on `has()`): `chunk.spectrum_index` and `point.spectrum_index` for `spectra_data` and
`spectra_peaks`. Cost: one streaming pass over one integer column, 0.05–0.09 s on the 231 MB
agilent-qtof `spectra_data` (28,840 chunk rows, 181 M points; 1,442 distinct vs 1,502 declared).

**Caveat (skeptic finding):** on `spectra_peaks` R2 warns on 18 published archives *even after*
the writer fix unless zero-peak spectra are handled — today `mini_peak.rs` counts spectra handed
in, including those with zero peaks. Decide with the converter whether "spectra in this facet"
means "with rows" (recommended; then the writer changes and R2 is exact) or "routed here" (then
R2 needs `≥` on `spectra_peaks`). Do not ship R2 on `spectra_peaks` before that decision.

### R3 — per-facet point count  (NEW primitive `footer_equals_points_in_file`)

Point layout (`point.mz` or `point.intensity` present): `actual = num_rows`, footer-only.
Chunk layout: `actual = Σ pc.list_value_length` over the first present of `[chunk.intensity,
chunk.mz_chunk_values]` (DATA_SCAN; 0.99 s for 181 M points; verified 296,228 / 10 / 30 /
181,196,503 against the facets' own data). If both are numpress byte columns → info "not
derivable without decoding" and skip. Entries: `spectra_data` / `spectrum_data_point_count`,
`spectra_peaks` / `spectrum_data_point_count`, `chromatograms_data` /
`chromatogram_data_point_count`. Fails today on `spectra_data` of both repros (296,228 vs 0;
40 vs 10); passes on `spectra_peaks`. This replaces the converter's ad-hoc regression pin
(`tests/footer_counts.rs:73-79`, which only asserts `points > chunk rows` and so accepts 40 > 1).
Cheaper cross-check variant using only a metadata column: `footer_equals_column_sum`
(`spectra_data` vs `Σ number_of_data_points`, `spectra_peaks` vs `Σ number_of_peaks`, null = 0 —
the same assumption `count_implies_rows` already makes).

### Secondaries — recommend **no** count rule

On `spectra_metadata_scans/_precursors/_selected_ions` and `chromatograms_metadata_precursors/
_selected_ions` neither "rows", "distinct source_index" nor the run total is *the* count (a
precursors table has 0 rows for MS1-only and > 1 row per spectrum for PASEF), and `rows == 0 ∧
count > 0` would flag 67 + 67 + 201 + 198 perfectly readable facets. Whether the key belongs there
at all is a writer/spec question. Keep the existing `*_source_fk_split` rules as the integrity check.

## Severity policy

Warning for R1–R3 in mzpeak-0.9; error for R4 and the FK entries. The keys are absent from the
spec, so FAILing 85+ published archives on them asserts a semantics the spec does not have; the
profile's precedent for spec-silent checks is advisory (`cv_mapping` Phase 1, perf rules) — note
`spectrum_count_agreement` at error is the outlier and `chunk_bounds` is a spec MUST *demoted* to
warning, so the precedent is not clean either way. Detection is the goal: `validate_everything.py`
classifies warning rules per file and `smoke_test.py` pins `warn_rule`, so a warning would have
surfaced 161 facets in the first corpus run. Promote to error in the profile bump that ships with
the converter's per-file stamping and/or HUPO-PSI text, adding the corresponding `fail/` fixtures.

## Fixtures (`make_fixtures.py`, `expected.json` `warn_rule` per `CLAUDE.md:64`)

- `fail/empty_data_facet_declared` — `spectra_data` 0 rows, footer `spectrum_count = 3`,
  `spectrum_data_point_count = 12` → R1.
- `fail/populated_facet_declares_zero` — 8 rows, footer count 0 → R1 converse (wavelength case).
- `fail/data_facet_count_over_declared` — 3 distinct spectra present, footer 5 → R2.
- `fail/data_facet_point_sum_of_facets` — chunk file whose intensity lists sum to 10, footer 40 → R3.
- pass variants in both layouts. Note `_meta()` (`make_fixtures.py:37`) and `_data()` (`:46`) have
  always stamped the **per-file** point count on `spectra_data` — the generator already encodes the
  reading R3 enforces.
- Real-archive gates: R1 must fire on `fixtures/repro-centroid.mzpeak` (`spectra_data`) and on the
  corpus PDA-UV archive's wavelength scans facet; R2 on `repro-mixed.mzpeak` (`spectra_data` 4 vs
  1) and on `general-ms/agilent-qtof` (1,502 vs 1,442); R3 on both repros' `spectra_data`. After
  the converter fix, all four must be **silent** on a reconverted repro-centroid / repro-mixed.

## Order and cost

R1 + R4 + FK entries first (cheap, layout-agnostic, no semantics decision, R1 fires under
`--quick`); then R2/R3 with — or at warning ahead of — the converter release that fixes the
writer. Bump `CATALOG_VERSION` (`core.py:84`) and `profile.json:9` together (1.12 → 1.13).
Add the `rules_evaluated / skipped` ledger asked for in `HANDOFF-shimadzu-rotation-rules.md` if it
is still open: reason 4 above is exactly the silent-no-op class it makes visible.

## Open decisions for the validator author

1. R1 absence policy: silent skip (recommended) vs the warning `footer_count_equals_rows` emits.
2. Zero-peak spectra on `spectra_peaks` (R2): "with rows" vs "routed here" — align with the
   converter before shipping R2 there.
3. Whether to demote `spectrum_count_agreement` to warning for consistency, or accept the
   reference-writer convention as normative and put R1–R3 at error.
