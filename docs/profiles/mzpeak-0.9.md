# Profile reference — `mzpeak-0.9`

> **Generated** from the profile bundle by [`docs/gen_profile_page.py`](../gen_profile_page.py). Do not edit by hand — re-run the generator after changing the profile:
> `python docs/gen_profile_page.py mzpeak_validator/profiles/mzpeak-0.9 > docs/profiles/mzpeak-0.9.md`

- **Profile id:** `mzpeak-0.9`
- **mzPeak spec:** 0.9 (commit [`204af1698c4d`](https://github.com/HUPO-PSI/mzPeak-specification))
- **Rule-primitive catalog:** `1.18` (the cross-language contract the engine implements)
- **Rules:** 123 across 9 files
- **Note:** Keyed to the current spec (HUPO-PSI/mzPeak-specification; ref impl HUPO-PSI/mzPeak @ 29e59b24). Bundles the spec's JSON Schemas under schema/json/. Pre-1.0: the spec example still declares version 0.9.0.

## How validation works

Validation is driven by this *profile* — a versioned bundle of JSON Schemas, pinned controlled-vocabulary (CV) snapshots, and a declarative **rule set**. The engine implements a small **primitive catalog**; each rule is a data-only *instance* of a primitive, so any implementation that implements the catalog reproduces identical verdicts. Each rule self-gates (it no-ops when its target file/column is absent), so layout-independent checks apply everywhere while point-layout / imaging checks quietly skip where they do not apply.

## Conformance axes

Conformance is reported along independent axes: `well-formed`, `schema`, `numeric`, `index`, `cv`, `cv-placement`, `integrity`, `imaging`, `performance`.

## Severity & recovery

Two non-gameable severity tiers:

| Level | Meaning |
|---|---|
| `error` | structural / schema-type / numeric / index / integrity / required-CV — hard, never demotable |
| `warning` | SHOULD-level (e.g. CV completeness, auxiliary optical images, non-contiguous index) |

Every rule also declares a **recovery class** — how a paired repair mode could fix the finding (validation only reports; it never mutates):

| Class | Auto-applied? | Meaning |
|---|---|---|
| `rebuild` | yes (lossless) | reconstruct a derived structure (e.g. a lost index) from the authoritative data |
| `recompute` | yes (lossless) | recompute a recorded digest/aggregate |
| `rederive` | yes (lossless) | re-derive a missing/wrong derivable value or relabel a dtype tag |
| `reorder_pair` | yes (lossless) | re-sort an axis that MUST be sorted, moving its parallel arrays with it |
| `normalize` | opt-in (lossy) | alter values to satisfy a constraint (e.g. clamp negative intensity) |
| `drop` | opt-in (lossy) | remove an irreparable record |
| `none` | no → hard fail | not auto-recoverable |

## Pinned artifacts

| Role | Id | Version | Path |
|---|---|---|---|
| cv | MS | 4.1.257 | `cv/psi-ms.obo.gz` |
| cv | IMS | 1.1.0 | `cv/imagingMS.obo` |
| cv | UO | 2026-01-16 | `cv/uo.obo` |
| cv | MZP | 0.2.0 | `cv/mzpeak.obo` |
| json-schema | mzpeak_index |  | `schema/json/mzpeak_index.json` |
| json-schema | cv_list |  | `schema/json/cv_list.json` |
| json-schema | file_description |  | `schema/json/file_description.json` |
| json-schema | instrument_configuration |  | `schema/json/instrument_configuration.json` |
| json-schema | software |  | `schema/json/software.json` |
| json-schema | sample |  | `schema/json/sample.json` |
| json-schema | data_processing |  | `schema/json/data_processing.json` |
| json-schema | scan_settings_list |  | `schema/json/scan_settings_list.json` |
| json-schema | ms_run |  | `schema/json/ms_run.json` |
| json-schema | array_index |  | `schema/json/array_index.json` |
| json-schema | auxiliary_array |  | `schema/json/auxiliary_array.json` |
| json-schema | param |  | `schema/json/param.json` |
| columns | spectra_metadata |  | `schema/tables/spectra_metadata.columns.json` |
| columns | spectra_data |  | `schema/tables/spectra_data.columns.json` |
| columns | spectra_peaks |  | `schema/tables/spectra_peaks.columns.json` |
| columns | chromatograms_metadata |  | `schema/tables/chromatograms_metadata.columns.json` |
| columns | wavelength_spectra_metadata |  | `schema/tables/wavelength_spectra_metadata.columns.json` |
| columns | wavelength_spectra_data |  | `schema/tables/wavelength_spectra_data.columns.json` |
| rules |  |  | `rules/structural.rules.json` |
| rules |  |  | `rules/cv.rules.json` |
| rules |  |  | `rules/numeric.rules.json` |
| rules |  |  | `rules/metadata.rules.json` |
| rules |  |  | `rules/imaging.rules.json` |
| rules |  |  | `rules/perf.rules.json` |
| rules |  |  | `rules/semantic.rules.json` |
| rules |  |  | `rules/layout.rules.json` |
| rules |  |  | `rules/container.rules.json` |
| cv_mapping |  |  | `cv_mapping/table_rules.json` |
| cv_mapping |  |  | `cv_mapping/imaging_table_rules.json` |
| cv_mapping |  |  | `cv_mapping/semantic_rules.json` |

CV snapshots are pinned OBO files (no live ontology lookup at validate time). `sha256` content-addressing is filled by a future `--seal` step.

## Rule structure

Each rule is a JSON object. The engine reads **only** these keys:

```json
{
  "id": "mz_monotonic_data",          // unique rule id (appears in findings)
  "primitive": "grouped_monotonic",   // which catalog primitive to run
  "severity": "error",                // error | warning
  "recovery": "reorder_pair",         // recovery class (table above)
  "params": { ... },                  // primitive-specific parameters
  "doc": "..."                        // NON-NORMATIVE: documentation, ignored by the engine
}
```

Each `rules/*.rules.json` also has a top-level `about` block (purpose, gating, a per-primitive param contract, and a how-to-amend note). `about` and `doc` are documentation only. **To amend:** copy a rule and edit its `params`; to change which columns/types are required, edit the relevant `schema/tables/*.columns.json` (not a rule); to accept a new CV, add its OBO as a `cv` artifact in `profile.json`.

## Checks by rule file

### `structural.rules.json`

**Purpose.** The archive opens, every file the index lists is present and readable, a file that claims to hold signal actually carries a signal facet, and each table's columns/types match the pinned column schema.

**Applies to.** every mzPeak archive (no layout/imaging gating).

| Rule id | Primitive | Severity | Recovery | What it checks |
|---|---|---|---|---|
| `index_files_present` | `index_files_present` | error | rebuild | Every file named in mzpeak_index.json 'files[]' exists and opens as Parquet, EXCEPT members declared as optical images in metadata.imaging.images[] (existence-checked only; bytes validated by the image primitives). recovery=rebuild: a lost/garbled index can be reconstructed from the present files. |
| `data_kind_has_facet` | `data_kind_facet` | error | none | A file the index advertises as signal (data_kind 'data arrays'/'data_arrays' or 'peaks' for a spectrum entity) must actually carry a 'point' or 'chunk' top-level column. Accepts both spellings of data_arrays per spec e7f3447. |
| `data_kind_has_facet_chromatograms` | `data_kind_facet` | error | none | Same as data_kind_has_facet for the chromatogram entity: a file the index advertises as chromatogram 'data arrays'/'data_arrays' must carry a 'point' or 'chunk' top-level column. No-ops on archives without chromatograms. |
| `columns_spectra_metadata` | `columns_present` | error | none | Packed-layout only: spectra_metadata has the required nested facets/columns per schema/tables/spectra_metadata.columns.json. Skipped on split-layout archives (where facets are separate files). |
| `columns_spectra_metadata_split` | `columns_present` | error | none | Split-layout only: spectra_metadata has a non-null unique 'index' PK (spec metadata-tables.md MUST). Uses spectra_metadata_split column schema for the flat layout. |
| `columns_spectra_metadata_scans` | `columns_present` | error | none | Split-layout only: spectra_metadata_scans has a non-null 'source_index' FK (spec metadata-tables.md MUST). No-ops if the file is absent or the archive is packed-layout. |
| `columns_spectra_metadata_precursors` | `columns_present` | error | none | Split-layout only: spectra_metadata_precursors has a non-null 'source_index' FK. Zero-or-more rows per source_index is legal (timsTOF frames carry many precursors). No-ops if absent or packed-layout. |
| `columns_spectra_metadata_selected_ions` | `columns_present` | error | none | Split-layout only: spectra_metadata_selected_ions has a non-null 'source_index' FK. No-ops if absent or packed-layout. |
| `columns_spectra_data` | `columns_present` | error | none | spectra_data (profile/point layout) matches schema/tables/spectra_data.columns.json. point.mz/intensity accept both 32- and 64-bit floats or 32-bit integers (spec signal-data.md e7f3447). |
| `columns_spectra_peaks` | `columns_present` | error | none | spectra_peaks (centroided layout) matches schema/tables/spectra_peaks.columns.json. intensity accepts float, double, or integer (spec signal-data.md e7f3447). |
| `columns_chromatograms_metadata` | `columns_present` | error | none | Packed-layout only: chromatograms_metadata carries the required nested struct facets/columns per schema/tables/chromatograms_metadata.columns.json. Skipped on split-layout archives. |
| `columns_chromatograms_metadata_precursors` | `columns_present` | error | none | Split-layout only: chromatograms_metadata_precursors has a non-null 'source_index' FK. Commonly 0 rows (empty-but-present is legal). No-ops if absent or packed-layout. |
| `columns_chromatograms_metadata_selected_ions` | `columns_present` | error | none | Split-layout only: chromatograms_metadata_selected_ions has a non-null 'source_index' FK. No-ops if absent or packed-layout. |
| `data_kind_has_facet_wavelength` | `data_kind_facet` | error | none | A file the index advertises as wavelength spectrum 'data arrays'/'data_arrays' must carry a 'point' or 'chunk' top-level column. No-ops on archives without wavelength spectra. |
| `columns_wavelength_spectra_metadata` | `columns_present` | error | none | Packed-layout only: wavelength_spectra_metadata matches schema/tables/wavelength_spectra_metadata.columns.json. Skipped on split-layout archives. |
| `columns_wavelength_spectra_data` | `columns_present` | error | none | wavelength_spectra_data point layout matches schema/tables/wavelength_spectra_data.columns.json: entity index MUST be named wavelength_spectrum_index (not spectrum_index). No-ops when absent. |

### `cv.rules.json`

**Purpose.** Controlled-vocabulary discipline on inflected column names of the form ${CV}_${ACCESSION}_${name} (e.g. MS_1000511_ms_level): the CV code must be one the profile pins, and the accession should resolve inside that pinned OBO snapshot. The same existence check for the CURIEs an archive writes as values (index params, column mappings, array indexes, term-marker and grid_type columns).

**Applies to.** any table with inflected columns; rules below target the two metadata tables. cv_terms_exist applies to every archive.

| Rule id | Primitive | Severity | Recovery | What it checks |
|---|---|---|---|---|
| `cv_inflection_spectra_metadata` | `cv_inflection` | error | none | Inflected columns in spectra_metadata (spectrum/scan/precursor/selected_ion facets) use a pinned CV code and a resolvable accession, INCLUDING unit accessions (_unit_${CV}_${ACC}). severity=error is the code-unknown case; an unresolved accession is downgraded to warning inside the primitive. |
| `cv_inflection_chromatograms_metadata` | `cv_inflection` | error | none | Same check for chromatograms_metadata when present (the primitive no-ops if the file is absent, so this is harmless on archives without chromatograms). |
| `cv_list_declared` | `cv_list_consistency` | error | none | metadata.cv_list declares every CV code the archive uses (spec MUST). Absent cv_list on a file that uses CV codes is an error. Version policy: a declared CV version that is NEWER than the profile's pinned snapshot -> warning (the validator is behind; update its bundled CVs); a same-or-older declared version is fine and does NOT warn. This validates the FILE's own declaration (vs cv_inflection, which checks resolvability against the profile's pinned CVs). |
| `cv_terms_exist` | `cv_terms_exist` | warning | none | Written accessions exist in their vocabulary: cv_list pins each CV to a fixed release (conformance.md), so a CURIE should name a term of it. Review 2026-09-30 A7: the timsTOF grid_type values MS:9999001/MS:9999002 are invented, not PSI-MS terms, and the validator passed them. Warning, not error: readers ignore unrecognised CV terms (conformance.md), and the check runs against the profile's one pinned snapshot per CV, which stands in for the release the archive declares (a term added between the two releases passes; one obsoleted after the declared release warns). Term-marker and grid_type VALUES are read outside --quick only. |

### `numeric.rules.json`

**Purpose.** Value-level integrity of the signal arrays and the keys that tie tables together: counts agree, m/z is sorted and finite, intensity is non-negative, dtypes fit their role, foreign keys resolve, and the spectrum index is well-formed.

**Applies to.** point-layout archives. Rules that read point.* no-op on chunk/numpress layouts (the column is absent), so those layouts pass the layout-independent checks and skip the rest. Most rules here are DATA_SCAN rules, skipped under --quick (footer_count_equals_rows is cheap and still runs).

**Null semantics.** Arrow nulls are LEGITIMATE (sparse/null-marking): m/z and number_of_data_points may be null. Rules treat nulls as OK (counts as 0; skipped in monotonic/finite). Only genuine NaN/inf VALUES are flagged (see mz_finite_data). Do not 'fix' a rule to reject nulls.

| Rule id | Primitive | Severity | Recovery | What it checks |
|---|---|---|---|---|
| `spectrum_count_agreement` | `footer_count_equals_rows` | error | rederive | spectra_metadata footer 'spectrum_count' equals the number of spectra = non-null spectrum.index entries (count_column). NOT total rows: in the packed parallel-facet layout the table is as long as its longest facet, so a PASEF/TIMS run with many precursors per MS2 spectrum has far more rows than spectra (e.g. SBA415: 278942 rows, 44296 spectra). Counting non-null spectrum.index makes the footer agree for both plain LC-MS and packed layouts. recovery=rederive: the true count is derivable. |
| `data_points_sum` | `count_sum_equals_rows` | error | rederive | Point-layout integrity: sum of per-spectrum number_of_data_points equals the spectra_data row count. 'guard' point.intensity gates this to the point layout (skips chunk/numpress). Null counts (centroid spectra) count as 0. Preferred over a footer check because the writer's spectra_data footer is unreliable. |
| `mz_finite_data` | `column_predicate` | error | none | spectra_data point.mz has no NaN/inf VALUES (Arrow nulls are allowed -- see null_semantics). Distinct from monotonicity; a NaN both breaks sorting and is meaningless as a mass. |
| `intensity_nonneg_data` | `column_predicate` | error | normalize | spectra_data point.intensity >= 0. recovery=normalize (clamp to 0) is LOSSY, so it is opt-in only (repair --aggressive); validation just reports. To forbid the clamp entirely, set recovery to 'none'. |
| `intensity_nonneg_peaks` | `column_predicate` | error | normalize | Same non-negativity check on the centroided spectra_peaks table. |
| `mz_monotonic_data` | `grouped_monotonic` | error | reorder_pair | Within each spectrum (grouped by point.spectrum_index), spectra_data point.mz is non-decreasing -- but only when the array index declares point.mz sorted (non-null sorting_rank). A file that declares m/z unsorted is conformant as-is and is skipped (info). Uses a stable argsort, so it catches inversions even when a spectrum's rows are interleaved/non-contiguous (regression: 'interleaved_unsorted_mz'). recovery=reorder_pair re-sorts m/z and its parallel intensity together (lossless). |
| `mz_monotonic_peaks` | `grouped_monotonic` | error | reorder_pair | Same per-spectrum m/z ordering check on spectra_peaks, likewise gated on the declared sorting_rank of point.mz. |
| `intensity_dtype_data` | `dtype_role` | error | none | spectra_data point.intensity is a numeric type. Accepts float, double, or signed integer (spec signal-data.md e7f3447: '32-bit integers'). Unsigned integer is NOT permitted by the spec. m/z is still float-only. 'int' matches any signed integer width (int8/16/32/64); narrow to 'int32' is not yet enforced at the logical-type level. |
| `mz_dtype_data` | `dtype_role` | error | none | spectra_data point.mz is a floating type (double or float), never integer. Width-agnostic, matching the relaxed column schema; the hard guarantee here is 'must be float, not int'. Width acceptance is the HUPO-PSI #11 question, decided in spectra_data.columns.json. |
| `point_fk_data` | `foreign_key` | error | none | Every spectra_data point.spectrum_index points to an existing spectra_metadata spectrum.index (and is non-null). A dangling FK means orphaned signal with no metadata -- not auto-recoverable. |
| `chrom_point_fk_data` | `foreign_key` | error | none | Every chromatograms_data chunk.chromatogram_index references an existing chromatograms_metadata chromatogram.index. The chromatogram analog of point_fk_data; no-ops on archives without chromatograms. |
| `point_fk_peaks` | `foreign_key` | error | none | Same FK integrity from spectra_peaks back to spectrum.index. |
| `scan_source_index_fk` | `foreign_key` | error | rebuild | scan.source_index resolves to a spectrum.index (both in spectra_metadata). allow_null=true: in the packed parallel-facet layout the scan facet is null on rows owned by another facet (e.g. precursor-only PASEF rows), so child nulls are expected and not flagged. recovery=rebuild: the scan<->spectrum map is derivable. |
| `spectrum_index_contiguous` | `index_contiguous` | warning | none | spectrum.index is 0-based contiguous (0..k-1) over its non-null entries (packed-facet padding rows are ignored). Only a WARNING: a gapped index is unusual but still readable as long as the FKs resolve. Raise to severity 'error' if your profile requires dense indices. |
| `chromatogram_index_contiguous` | `index_contiguous` | warning | none | chromatogram.index is 0-based contiguous (0..k-1) over its non-null entries. The chromatogram analog of spectrum_index_contiguous; no-ops on archives without chromatograms_metadata. |
| `wavelength_spectrum_index_contiguous` | `index_contiguous` | warning | none | wavelength_spectra_metadata spectrum.index is 0-based contiguous over non-null entries. No-ops when absent. |
| `precursor_source_fk` | `foreign_key` | error | rebuild | precursor.source_index resolves to a spectrum.index. allow_null (packed layout). Ties each precursor back to the spectrum it was isolated from. |
| `selected_ion_source_fk` | `foreign_key` | error | rebuild | selected_ion.source_index resolves to a spectrum.index. allow_null (packed layout). |
| `per_spectrum_data_points` | `grouped_count_equals` | error | rederive | Per-spectrum integrity: each spectrum's profile-point rows in spectra_data equal its declared number_of_data_points (null counted as 0). Stronger than data_points_sum -- catches localized/swapped count corruption a global sum hides. Gated to the point layout via 'guard'. |
| `per_spectrum_peaks` | `grouped_count_equals` | error | rederive | Per-spectrum integrity for the centroided table: each spectrum's peak rows in spectra_peaks equal its declared number_of_peaks (null counted as 0). The missing peaks analog of per_spectrum_data_points. |
| `wavelength_point_fk_data` | `foreign_key` | error | none | wavelength_spectra_data point.wavelength_spectrum_index must resolve to wavelength_spectra_metadata spectrum.index. The wavelength-spectra analog of point_fk_data. No-ops when either table is absent. |
| `scan_source_fk_split` | `foreign_key` | error | rebuild | Split-layout analog of scan_source_index_fk: every spectra_metadata_scans row's source_index must resolve to spectra_metadata.index (flat PK). No-ops on packed archives because spectra_metadata_scans does not exist there. |
| `precursor_source_fk_split` | `foreign_key` | error | rebuild | Split-layout analog of precursor_source_fk: every spectra_metadata_precursors source_index must resolve to spectra_metadata.index. No-ops on packed archives. |
| `selected_ion_source_fk_split` | `foreign_key` | error | rebuild | Split-layout analog of selected_ion_source_fk: every spectra_metadata_selected_ions source_index must resolve to spectra_metadata.index. No-ops on packed archives. |
| `point_fk_data_split` | `foreign_key` | error | none | Split-layout analog of point_fk_data: every spectra_data point.spectrum_index must resolve to the flat spectra_metadata.index PK. No-ops on packed archives (spectra_metadata.index is absent in the packed struct layout; point_fk_data covers that case via spectrum.index). |
| `point_fk_peaks_split` | `foreign_key` | error | none | Split-layout analog of point_fk_peaks for the centroided table. |
| `spectrum_index_contiguous_split` | `index_contiguous` | warning | none | Split-layout analog of spectrum_index_contiguous: the flat spectra_metadata.index must be 0-based contiguous. No-ops on packed archives (spectrum.index covers that case). |
| `data_points_sum_split` | `count_sum_equals_rows` | error | rederive | Split-layout analog of data_points_sum: sum of per-spectrum number_of_data_points (plain flat column name) equals the spectra_data row count. Gated on point.intensity (skips chunk-layout archives). No-ops on packed archives because 'number_of_data_points' (flat) is absent there. |
| `per_spectrum_data_points_split` | `grouped_count_equals` | error | rederive | Split-layout analog of per_spectrum_data_points: per-spectrum count check using flat column names (number_of_data_points, index). Gated on point.intensity; no-ops on chunk-layout and on packed archives. |
| `per_spectrum_peaks_split` | `grouped_count_equals` | error | rederive | Split-layout analog of per_spectrum_peaks: per-spectrum peak count check using flat column names (number_of_peaks, index). Gated on point.intensity; no-ops on chunk-layout and on packed archives. |
| `chrom_point_fk_data_split` | `foreign_key` | error | none | Split-layout analog of chrom_point_fk_data: every chromatograms_data chunk.chromatogram_index must resolve to the flat chromatograms_metadata.index PK. No-ops on packed archives (packed column is chromatogram.index). |
| `chromatogram_index_contiguous_split` | `index_contiguous` | warning | none | Split-layout analog of chromatogram_index_contiguous: the flat chromatograms_metadata.index must be 0-based contiguous. No-ops on packed archives. |
| `chrom_precursor_source_fk_split` | `foreign_key` | error | rebuild | Split-layout: every chromatograms_metadata_precursors.source_index must resolve to chromatograms_metadata.index. No-ops on packed archives (flat 'index' column absent) and on archives without chromatogram precursors. |
| `chrom_selected_ion_source_fk_split` | `foreign_key` | error | rebuild | Split-layout: every chromatograms_metadata_selected_ions.source_index must resolve to chromatograms_metadata.index. No-ops on packed archives and on archives without chromatogram selected_ions. |
| `spectrum_representation_not_null` | `column_not_all_null` | error | recompute | Split-layout: spectra_metadata.spectrum_representation MUST NOT be entirely null. MS:1000525 (spectrum representation) is a MUST term per the CvMapping spec; an all-null column means every spectrum has unknown representation, which a conforming reader cannot use for read-planning. No-ops for packed-layout archives (column absent; cv_mapping covers those). |
| `data_points_imply_spectra_data_rows` | `count_implies_rows` | error | none | Split-layout: if any spectrum declares number_of_data_points > 0, spectra_data.parquet must have rows; and if spectra_data has rows, at least one spectrum must have number_of_data_points > 0. A mismatch means a conforming reader (which uses the count for read-planning) will either find nothing or ignore existing data. No-ops if number_of_data_points is absent. |
| `peaks_imply_spectra_peaks_rows` | `count_implies_rows` | error | none | Split-layout: if any spectrum declares number_of_peaks > 0, spectra_peaks.parquet must have rows; and if spectra_peaks has rows, at least one spectrum must have number_of_peaks > 0. No-ops if number_of_peaks is absent. |
| `spectra_data_footer_implies_rows` | `footer_count_implies_rows` | warning | rederive | Footer {keys} must be 0 when the facet has 0 rows and > 0 when it has rows. Before 0.11.2 the reference writer stamped the run-wide counters on every facet (mzPeakConverter#1: a centroid-only run declared the full spectrum count on an empty spectra_data and a footer-planned reader issued 893,769 queries against it). Advisory until HUPO-PSI defines the footer keys. |
| `spectra_peaks_footer_implies_rows` | `footer_count_implies_rows` | warning | rederive | Footer {keys} must be 0 when the facet has 0 rows and > 0 when it has rows. Before 0.11.2 the reference writer stamped the run-wide counters on every facet (mzPeakConverter#1: a centroid-only run declared the full spectrum count on an empty spectra_data and a footer-planned reader issued 893,769 queries against it). Advisory until HUPO-PSI defines the footer keys. |
| `chromatograms_data_footer_implies_rows` | `footer_count_implies_rows` | warning | rederive | Footer {keys} must be 0 when the facet has 0 rows and > 0 when it has rows. Before 0.11.2 the reference writer stamped the run-wide counters on every facet (mzPeakConverter#1: a centroid-only run declared the full spectrum count on an empty spectra_data and a footer-planned reader issued 893,769 queries against it). Advisory until HUPO-PSI defines the footer keys. |
| `wavelength_scans_footer_implies_rows` | `footer_count_implies_rows` | warning | rederive | Secondary facets carry no entity count (mzPeakConverter#1, decision D2), so writers omit {keys} here and an absent key is not a finding. A key that is present must not claim rows the file does not have, nor 0 on rows it has (a pre-0.11.2 writer declared 0 on a populated wavelength scans facet). Warning. |
| `spectra_scans_footer_implies_rows` | `footer_count_implies_rows` | warning | rederive | Secondary facets carry no entity count (mzPeakConverter#1, decision D2), so writers omit {keys} here and an absent key is not a finding. A key that is present must not claim rows the file does not have: mzPeakConverter 0.11.5 and earlier stamped the run total on every secondary, so an MS1-only run's empty precursors facet declared every spectrum. Warning. |
| `spectra_precursors_footer_implies_rows` | `footer_count_implies_rows` | warning | rederive | Secondary facets carry no entity count (mzPeakConverter#1, decision D2), so writers omit {keys} here and an absent key is not a finding. A key that is present must not claim rows the file does not have: mzPeakConverter 0.11.5 and earlier stamped the run total on every secondary, so an MS1-only run's empty precursors facet declared every spectrum. Warning. |
| `spectra_selected_ions_footer_implies_rows` | `footer_count_implies_rows` | warning | rederive | Secondary facets carry no entity count (mzPeakConverter#1, decision D2), so writers omit {keys} here and an absent key is not a finding. A key that is present must not claim rows the file does not have: mzPeakConverter 0.11.5 and earlier stamped the run total on every secondary, so an MS1-only run's empty precursors facet declared every spectrum. Warning. |
| `chromatogram_precursors_footer_implies_rows` | `footer_count_implies_rows` | warning | rederive | Secondary facets carry no entity count (mzPeakConverter#1, decision D2), so writers omit {keys} here and an absent key is not a finding. A key that is present must not claim rows the file does not have: mzPeakConverter 0.11.5 and earlier stamped the run total on every secondary, so an MS1-only run's empty precursors facet declared every spectrum. Warning. |
| `chromatogram_selected_ions_footer_implies_rows` | `footer_count_implies_rows` | warning | rederive | Secondary facets carry no entity count (mzPeakConverter#1, decision D2), so writers omit {keys} here and an absent key is not a finding. A key that is present must not claim rows the file does not have: mzPeakConverter 0.11.5 and earlier stamped the run total on every secondary, so an MS1-only run's empty precursors facet declared every spectrum. Warning. |
| `chromatogram_count_agreement` | `footer_count_equals_rows` | error | rederive | chromatograms_metadata footer chromatogram_count equals the chromatogram count (non-null chromatogram.index in the packed layout, rows in the split/flat layout). The missing twin of spectrum_count_agreement; the public corpus is 201/201 consistent. |
| `point_fk_data_chunk` | `foreign_key` | error | none | Chunk-layout data facet FK: every referenced entity index must exist in its metadata facet. Closes the gap where 182/201 public archives (chunk layout) had no FK on the data facets at all. |
| `point_fk_data_chunk_split` | `foreign_key` | error | none | Chunk-layout data facet FK: every referenced entity index must exist in its metadata facet. Closes the gap where 182/201 public archives (chunk layout) had no FK on the data facets at all. |
| `point_fk_peaks_chunk` | `foreign_key` | error | none | Chunk-layout data facet FK: every referenced entity index must exist in its metadata facet. Closes the gap where 182/201 public archives (chunk layout) had no FK on the data facets at all. |
| `point_fk_peaks_chunk_split` | `foreign_key` | error | none | Chunk-layout data facet FK: every referenced entity index must exist in its metadata facet. Closes the gap where 182/201 public archives (chunk layout) had no FK on the data facets at all. |
| `chrom_point_fk_data_point` | `foreign_key` | error | none | Chunk-layout data facet FK: every referenced entity index must exist in its metadata facet. Closes the gap where 182/201 public archives (chunk layout) had no FK on the data facets at all. |
| `chrom_point_fk_data_point_split` | `foreign_key` | error | none | Chunk-layout data facet FK: every referenced entity index must exist in its metadata facet. Closes the gap where 182/201 public archives (chunk layout) had no FK on the data facets at all. |
| `spectra_data_count_max_index_chunk` | `footer_count_equals_rows` | warning | rederive | Footer spectrum_count on spectra_data equals one past the largest spectrum_index with a row in THIS file, 0 when the file has no rows (mzPeakConverter#1, decision D1): an index bound a reader can iterate to although the indices in a data facet are sparse. A zero-point entity does not raise it. 0.11.2–0.11.5 stamped the number of entities with rows instead, which is not a bound and warns here on mixed, sparse or rewritten facets (090701-LTQVelos-unittest-01 spectra_data: 43 declared, max index 84); 0.11.1 and earlier stamped the run total. Warning until HUPO-PSI defines the footer keys. |
| `spectra_data_count_max_index_point` | `footer_count_equals_rows` | warning | rederive | Footer spectrum_count on spectra_data equals one past the largest spectrum_index with a row in THIS file, 0 when the file has no rows (mzPeakConverter#1, decision D1): an index bound a reader can iterate to although the indices in a data facet are sparse. A zero-point entity does not raise it. 0.11.2–0.11.5 stamped the number of entities with rows instead, which is not a bound and warns here on mixed, sparse or rewritten facets (090701-LTQVelos-unittest-01 spectra_data: 43 declared, max index 84); 0.11.1 and earlier stamped the run total. Warning until HUPO-PSI defines the footer keys. |
| `spectra_data_points_in_file` | `footer_equals_points_in_file` | warning | rederive | Footer point counter equals the points stored in THIS file (point layout: rows; chunk layout: sum of list lengths). The reference writer stamps the sum over BOTH data facets, so spectra_data over-declares whenever spectra_peaks holds points. Warning until the converter adopts per-file stamping. |
| `spectra_peaks_points_in_file` | `footer_equals_points_in_file` | warning | rederive | Footer point counter equals the points stored in THIS file (point layout: rows; chunk layout: sum of list lengths). The reference writer stamps the sum over BOTH data facets, so spectra_data over-declares whenever spectra_peaks holds points. Warning until the converter adopts per-file stamping. |
| `chromatograms_data_points_in_file` | `footer_equals_points_in_file` | warning | rederive | Footer point counter equals the points stored in THIS file (point layout: rows; chunk layout: sum of list lengths). The reference writer stamps the sum over BOTH data facets, so spectra_data over-declares whenever spectra_peaks holds points. Warning until the converter adopts per-file stamping. |
| `spectra_peaks_count_max_index_chunk` | `footer_count_equals_rows` | warning | rederive | Footer spectrum_count on spectra_peaks equals one past the largest spectrum_index with a row in THIS file, 0 when the file has no rows (mzPeakConverter#1, decision D1): an index bound a reader can iterate to although the indices in a data facet are sparse. A zero-point entity does not raise it. 0.11.2–0.11.5 stamped the number of entities with rows instead, which is not a bound and warns here on mixed, sparse or rewritten facets (090701-LTQVelos-unittest-01 spectra_data: 43 declared, max index 84); 0.11.1 and earlier stamped the run total. Warning until HUPO-PSI defines the footer keys. |
| `spectra_peaks_count_max_index_point` | `footer_count_equals_rows` | warning | rederive | Footer spectrum_count on spectra_peaks equals one past the largest spectrum_index with a row in THIS file, 0 when the file has no rows (mzPeakConverter#1, decision D1): an index bound a reader can iterate to although the indices in a data facet are sparse. A zero-point entity does not raise it. 0.11.2–0.11.5 stamped the number of entities with rows instead, which is not a bound and warns here on mixed, sparse or rewritten facets (090701-LTQVelos-unittest-01 spectra_data: 43 declared, max index 84); 0.11.1 and earlier stamped the run total. Warning until HUPO-PSI defines the footer keys. |
| `chromatograms_data_count_max_index_chunk` | `footer_count_equals_rows` | warning | rederive | Footer chromatogram_count on chromatograms_data equals one past the largest chromatogram_index with a row in THIS file, 0 when the file has no rows (mzPeakConverter#1, decision D1): an index bound a reader can iterate to although the indices in a data facet are sparse. A zero-point entity does not raise it. 0.11.2–0.11.5 stamped the number of entities with rows instead, which is not a bound and warns here on mixed, sparse or rewritten facets (090701-LTQVelos-unittest-01 spectra_data: 43 declared, max index 84); 0.11.1 and earlier stamped the run total. Warning until HUPO-PSI defines the footer keys. |
| `chromatograms_data_count_max_index_point` | `footer_count_equals_rows` | warning | rederive | Footer chromatogram_count on chromatograms_data equals one past the largest chromatogram_index with a row in THIS file, 0 when the file has no rows (mzPeakConverter#1, decision D1): an index bound a reader can iterate to although the indices in a data facet are sparse. A zero-point entity does not raise it. 0.11.2–0.11.5 stamped the number of entities with rows instead, which is not a bound and warns here on mixed, sparse or rewritten facets (090701-LTQVelos-unittest-01 spectra_data: 43 declared, max index 84); 0.11.1 and earlier stamped the run total. Warning until HUPO-PSI defines the footer keys. |
| `wavelength_spectra_data_count_max_index_chunk` | `footer_count_equals_rows` | warning | rederive | Footer wavelength_spectrum_count on wavelength_spectra_data equals one past the largest wavelength_spectrum_index with a row in THIS file, 0 when the file has no rows (mzPeakConverter#1, decision D1): an index bound a reader can iterate to although the indices in a data facet are sparse. A zero-point entity does not raise it. 0.11.2–0.11.5 stamped the number of entities with rows instead, which is not a bound and warns here on mixed, sparse or rewritten facets (090701-LTQVelos-unittest-01 spectra_data: 43 declared, max index 84); 0.11.1 and earlier stamped the run total. Warning until HUPO-PSI defines the footer keys. |
| `wavelength_spectra_data_count_max_index_point` | `footer_count_equals_rows` | warning | rederive | Footer wavelength_spectrum_count on wavelength_spectra_data equals one past the largest wavelength_spectrum_index with a row in THIS file, 0 when the file has no rows (mzPeakConverter#1, decision D1): an index bound a reader can iterate to although the indices in a data facet are sparse. A zero-point entity does not raise it. 0.11.2–0.11.5 stamped the number of entities with rows instead, which is not a bound and warns here on mixed, sparse or rewritten facets (090701-LTQVelos-unittest-01 spectra_data: 43 declared, max index 84); 0.11.1 and earlier stamped the run total. Warning until HUPO-PSI defines the footer keys. |

### `imaging.rules.json`

**Purpose.** Checks that apply only to MS-imaging archives: the imaging marker, the pixel position columns (integer, mapped to their terms, 1-based, paired, inside the declared grid), the pixel grid in the scan settings, the commit-pinned imaging vocabulary, and integrity of any embedded optical images (members described in metadata.imaging.images[] and listed in files[]).

**Applies to.** imaging archives only. An archive is 'imaging' when metadata.imaging.is_imaging is true OR a spectra_metadata / spectra_metadata_scans column is position_x (or an earlier draft's IMS_1000050_position_x / opt_IMS_1000050_position_x). A position column is one by its full name: a column that only ends the same way (stage_position_x) is not a pixel position and is left alone by every rule here. The coordinate, position and grid rules self-gate on that; imaging_marker runs on every archive (positions without the marker are its finding); the image rules self-gate on the presence of metadata.imaging.images[] (no images[] -> they no-op).

**Spec basis.** The imaging profile of HUPO-PSI/mzPeak-specification PR #25 (docs/profiles/imaging.md at 4861c9d), 'What a validator checks' 1-8; earlier imzML2mzPeak docs/mzpeak-imaging-spec-suggestions.md, Edits 6-8. Image problems stay WARNINGs (the profile: a mismatch is a warning; images are outside the fidelity levels), and so does a length written in a unit other than micrometre (a SHOULD). Not checked: mz_range against the data (check 7; whether it describes the source or the stored arrays is open on PR #25), metadata.imaging fields the profile does not define (pixel_size_um), and pixel_count_source — the profile defines the field but no check on it, and an archive filtered from an observed_max archive keeps the source grid, so counts above the largest position are valid under either value.

| Rule id | Primitive | Severity | Recovery | What it checks |
|---|---|---|---|---|
| `imaging_marker` | `imaging_marker` | error | rederive | Imaging profile check 1: an archive that carries pixel positions MUST set metadata.imaging.is_imaging to true, and coordinate_base, if present, is 1. The converse, a marker without position columns (review 2026-09-30 B9/B10), is imaging_coordinates_1based's finding. recovery=rederive: the marker follows from the position columns. |
| `imaging_coordinates_1based` | `imaging_coordinates` | error | none | Imaging archives carry both position_x and position_y, and every set position_x/_y/_z is >= 1 (profile checks 2-3: positions are indices into the pixel grid counted from 1). The deliberate offset from the 0-based spectrum.index is intentional. No params. |
| `imaging_positions_paired` | `imaging_position_pairs` | error | none | Imaging profile check 2: in each scan row position_x and position_y are both set (the scan belongs to a pixel) or both null (it belongs to none, e.g. a calibration scan), and at least one scan belongs to a pixel. Review 2026-09-30 B12: an unchecked UInt32 narrowing nulls one axis only. |
| `imaging_position_columns` | `imaging_position_columns` | error | rederive | Imaging profile checks 2-3: position_x, position_y and, when present, position_z are integer columns, each with a column mapping entry naming its term (IMS:1000050 / IMS:1000051 / IMS:1000052). A column under an earlier draft's name (IMS_1000050_position_x, opt_IMS_1000050_position_x; mzpeak-convert 0.15.0) is held to the same and gets a warning for the name: the profile's names are position_x / position_y / position_z, not opt_ names. The name stays a warning while archives written before the profile exist (catalog 1.16 accepted the names silently); whether it becomes an error is open. recovery=rederive: a missing mapping follows from the column (the type and name findings carry recovery none). Runs under --quick. |
| `imaging_positions_within_grid` | `imaging_position_bounds` | error | none | Imaging profile check 7 (pixel_count agrees with the data): no set position exceeds the declared pixel counts — IMS:1000042 / IMS:1000043 in the scan settings, metadata.imaging.pixel_count. A grid need not be fully sampled, so counts larger than the largest position are fine, also when pixel_count_source is 'observed_max': mzpeak-convert's filter lane (in.mzpeak --rt ...) keeps the source grid and that marker while the largest stored positions shrink. HUPO-PSI/mzPeak-specification#23 follow-up: counts lowered below the positions passed. |
| `imaging_ims_cv_pinned` | `cv_uri_form` | error | none | Imaging profile check 6: an imaging archive declares IMS in cv_list with a uri that names a commit, https://raw.githubusercontent.com/imzML/imzML/<40-character commit hash>/imagingMS.obo. The imaging vocabulary publishes no releases, so a uri on a branch (refs/heads/master, as mzpeak-convert 0.15.0 wrote) points at content that changes. recovery=none: the archive does not say which commit its writer used. |
| `imaging_grid_settings` | `imaging_grid` | error | none | Imaging profile checks 4, 5 and 7 (pixel_count against the scan settings): exactly one scan_settings_list entry carries IMS:1000042 and IMS:1000043, each an integer >= 1; pixel size, max dimension and absolute position offset carry a unit of length; metadata.imaging.pixel_count equals the scan settings. Review 2026-09-30 B13: a second grid-bearing scanSettings could pass through. |
| `imaging_length_unit_micrometre` | `imaging_preferred_unit` | warning | none | Imaging profile, Grid geometry: pixel size, max dimension and absolute position offset SHOULD use micrometre (UO:0000017). Any unit of length is valid (imaging_grid_settings requires one), so another length unit is a WARNING — e.g. the centimetre accession UO:0000015 that imzML writers attach to micrometre values (HUPO-PSI/mzPeak-specification#23). Narrow 'terms' to IMS:1000046/IMS:1000047 to warn on pixel sizes only. |
| `image_member_present` | `member_exists` | warning | none | Every optical image declared in metadata.imaging.images[].archive_path is actually present in the archive. WARNING, not error: optical images are auxiliary. Amend 'list'/'member' if image bookkeeping moves elsewhere in the index. |
| `image_blob_hash` | `blob_hash` | warning | recompute | A present image member's bytes match its declared sha256 and size_bytes. recovery=recompute: a stale digest is fixable without touching the image. Change 'algo' if a different hash is recorded; null/absent hash fields are skipped per entry. |
| `image_tiff_magic` | `tiff_magic` | warning | none | An image declared image/tiff really begins with a TIFF magic number (guards against a truncated/mislabelled blob). v0.5 optical images are TIFF-only; if other media types are later allowed, gate this rule by adjusting media_type or add sibling rules per type. |
| `image_files_entry` | `image_index_entry` | warning | rederive | Imaging profile check 8: every image in metadata.imaging.images is listed in files[] with entity_type 'image' and data_kind 'other'. Review 2026-09-30 A3: the converter listed auto-discovered optical images as data_kind 'proprietary'. WARNING, as the profile says for image problems; the member's Core checksum is member_checksum_sha512's concern. |

### `container.rules.json`

**Purpose.** Checks on the ZIP container and Parquet column layout that the spec mandates but that are below the table/metadata level: members stored uncompressed, each member's bytes matching its declared SHA-512 checksum, and the entity-index / foreign-key column placed first in each facet.

**Applies to.** the ZIP archive (zip_stored is skipped for directory archives), every files[] member that declares a checksum (ZIP or directory), and spectra_metadata column order.

| Rule id | Primitive | Severity | Recovery | What it checks |
|---|---|---|---|---|
| `members_stored` | `zip_stored` | error | none | mzPeak ZIP members MUST be stored uncompressed (the format relies on stored members for direct/remote range access; the engine also refuses high-inflation archives as a zip-bomb guard). Directory archives are skipped. |
| `member_checksum_sha512` | `member_checksum` | error | recompute | Core Basic Integrity (conformance.md): each member's SHA-512 matches the checksum its files[] entry declares. Review 2026-09-30 A1: the converter's mzPeak rewrite lane copied old digests onto re-encoded members and the validator passed it. recovery=recompute: the digest is re-derivable from the bytes, once the bytes are known to be the intended ones. --quick rehashes members up to 32 MB only (metadata facets and images); a full run rehashes all. |
| `facet_key_column_first` | `column_order` | error | none | The entity-index / foreign-key column MUST be the first column of its facet (spec MUST; promotes from advisory to error — 0 corpus violations confirmed). |
| `wavelength_facet_key_column_first` | `column_order` | error | none | wavelength_spectra_metadata: spectrum.index and scan.source_index MUST be the first columns of their facets (spec docs/schemas/wavelength-spectra.md). No-ops when the table is absent. |

### `layout.rules.json`

**Purpose.** Validate the CHUNKED signal layout (the dominant real-file layout: a `chunk` struct with ${axis}_chunk_start/end + a value list + numpress bytes) and the auxiliary-array bookkeeping. The point layout is covered by numeric.rules.json; these rules add the chunk dimension and the per-row auxiliary-array count.

**Applies to.** spectra_data / chromatograms_data chunk facets; spectra_metadata / chromatograms_metadata auxiliary_arrays. All self-gate when absent.

| Rule id | Primitive | Severity | Recovery | What it checks |
|---|---|---|---|---|
| `chunk_columns_spectra_data` | `chunk_columns` | error | none | A chunked spectra_data facet (declares chunk.mz_chunk_start) MUST carry its companion columns: mz_chunk_end, mz_chunk_values, chunk_encoding. intensity is omitted here because numpress archives store it as intensity_numpress_slof_bytes instead. Skips the scalar/point sublayout and absent files. |
| `chunk_bounds_spectra_data` | `chunk_bounds` | warning | reorder_pair | Within each spectrum, m/z chunks have mz_chunk_start <= mz_chunk_end and are non-overlapping & ascending by start (the chunked analog of m/z monotonicity). The ascending/non-overlap part is a spec MUST; shipped at WARNING (advisory) in Phase 1 because real numpress-linear files carry an occasional converter-side mz_chunk_end=0 glitch — promote to error once that is calibrated/fixed. |
| `chunk_columns_chromatograms_data` | `chunk_columns` | error | none | A chunked chromatograms_data facet (declares chunk.time_chunk_start) MUST carry time_chunk_end, time_chunk_values, chunk_encoding. intensity omitted for numpress compat (see chunk_columns_spectra_data). |
| `chunk_bounds_chromatograms_data` | `chunk_bounds` | warning | reorder_pair | Within each chromatogram, time chunks have time_chunk_start <= time_chunk_end and are non-overlapping & ascending by start. Advisory (warning) in Phase 1, mirroring chunk_bounds_spectra_data. |
| `aux_arrays_spectra_metadata` | `aux_arrays` | error | rederive | Each spectrum's declared number_of_auxiliary_arrays equals the length of its auxiliary_arrays list. No-ops when the columns are absent. |
| `aux_arrays_chromatograms_metadata` | `aux_arrays` | error | rederive | Each chromatogram's declared number_of_auxiliary_arrays equals the length of its auxiliary_arrays list. |

### `metadata.rules.json`

**Purpose.** Validate the JSON index and the footer key/value metadata blobs against the bundled mzPeak JSON Schemas (draft-07). Complements the Parquet column-schema checks: those cover the table columns, these cover the JSON metadata the spec governs with schema/*.json.

**Applies to.** every archive (index) + any present footer metadata blob. A blob that is absent is skipped (presence is SHOULD-level; required-presence, e.g. metadata.version / cv_list, is a separate concern).

| Rule id | Primitive | Severity | Recovery | What it checks |
|---|---|---|---|---|
| `index_schema_valid` | `json_schema` | error | none | mzpeak_index.json conforms to schema/json/mzpeak_index.json. Catches a malformed index and missing required fields (e.g. the spec now requires metadata.version). |
| `cv_list_schema_valid` | `json_schema` | error | none | metadata.cv_list (when present) conforms to schema/json/cv_list.json. Absent cv_list is not flagged here (cv_list presence/completeness is the cv-axis' job). |
| `meta_file_description_valid` | `json_schema` | error | none | spectra_metadata footer 'file_description' blob conforms to schema/json/file_description.json. |
| `meta_instrument_config_valid` | `json_schema` | error | none | spectra_metadata footer 'instrument_configuration_list' conforms to schema/json/instrument_configuration.json. |
| `meta_software_valid` | `json_schema` | error | none | spectra_metadata footer 'software_list' conforms to schema/json/software.json. |
| `meta_sample_valid` | `json_schema` | error | none | spectra_metadata footer 'sample_list' conforms to schema/json/sample.json. |
| `meta_data_processing_valid` | `json_schema` | error | none | spectra_metadata footer 'data_processing_method_list' conforms to schema/json/data_processing.json. |
| `meta_run_valid` | `json_schema` | error | none | spectra_metadata footer 'run' conforms to schema/json/ms_run.json. |
| `meta_scan_settings_valid` | `json_schema` | error | none | spectra_metadata footer 'scan_settings_list' (imaging/run geometry) conforms to schema/json/scan_settings_list.json when present. |
| `array_index_data_valid` | `json_schema` | error | none | spectra_data footer 'spectrum_array_index' conforms to schema/json/array_index.json; data_type must be MS:1000518 child, array_type must be MS:1000513 child; all entries must share one buffer_format (point layout is all-or-nothing). |
| `array_index_peaks_valid` | `json_schema` | error | none | spectra_peaks footer 'spectrum_array_index' conforms to schema/json/array_index.json; same ancestry and uniformity checks as array_index_data_valid. |
| `array_index_chromatograms_valid` | `json_schema` | error | none | chromatograms_data footer 'chromatogram_array_index' conforms to schema/json/array_index.json; same ancestry and uniformity checks. No-ops on archives without chromatograms_data. |
| `column_mapping_valid` | `column_mapping` | error | none | files[].column_mapping[] entries are consistent with the Parquet schemas: paths resolve, and term_marker=true mappings carry an accession and point at either a boolean presence-flag column or a string column of child-term CURIEs (spec docs/layouts/metadata-tables.md, commits 204af16 and d0c16b3). |

### `perf.rules.json`

**Purpose.** Advisory, NON-conformance checks on the PHYSICAL Parquet layout that affect random-access read performance. These never FAIL an archive (warning-only): the data is correct, but laid out so that single-spectrum / random reads are expensive. Mirrors the spec's reader-friendly row-group sizing guidance.

**Applies to.** chunked data facets (spectra_data / chromatograms_data carrying a `chunk` struct). The point/peaks per-peak layout is chunked correctly by the writer and is not flagged.

| Rule id | Primitive | Severity | Recovery | What it checks |
|---|---|---|---|---|
| `data_row_group_not_monolithic` | `parquet_row_group_health` | warning | normalize | Advisory (perf, not conformance): a chunked spectra_data / chromatograms_data facet should not be stored in a single oversized Parquet row group. Parquet reads/decodes at row-group granularity, so a lone monolithic group means every random single-spectrum read decodes the whole group (the converter's chunk path can emit one group because its row-group cap is a row count, and one chunk-row is a whole-spectrum list). Writers should bound row groups by uncompressed size or point count (e.g. <= ~64 MB / ~2 M points). Warning-only; never fails an archive. |

### `semantic.rules.json`

**Purpose.** CV term-PLACEMENT conformance via the PSI CvMapping model (mzPeak port). Where cv.rules.json's cv_inflection checks that each accession is known and resolves, these rules check that the RIGHT terms appear in the RIGHT facet, with the required combination logic (AND/OR/XOR), child-term inheritance (allow_children) and cardinality (is_repeatable). See docs/cv-mapping-design.md.

**Applies to.** the packed facets of spectra_metadata / chromatograms_metadata; imaging rule gated on is_imaging. The split layout (spectra_metadata_scans.parquet etc.) has no packed facets, so the two cv_mapping rules self-skip there; cv_term_placement_metadata reads the index and runs on either layout.

| Rule id | Primitive | Severity | Recovery | What it checks |
|---|---|---|---|---|
| `cv_term_placement_tables` | `cv_mapping` | warning | none | CV term placement for the spectra_metadata / chromatograms_metadata facets, from the spec's cv_mapping/table_rules.json. Shipped at WARNING in Phase 1 (advisory, non-regressing): some spec MUSTs were written against mzML's element model and do not yet map cleanly to mzPeak's packed facets (e.g. spectrum type wants a child of MS:1000559; scan 'spectra combination' MS:1000570 is not represented). Promote to error per-rule once the spec/converter reconcile (one-line severity change). data_arrays[] and products[] scopes are intentionally unmapped (Phase 2). |
| `cv_term_placement_metadata` | `cv_mapping_json` | warning | none | CV term placement over the JSON index metadata parameters — file_description.contents[], instrument_configuration_list[].components[] (ionization/analyzer/detector type), software_list[], data_processing_method_list[].methods[] — from the spec's cv_mapping/semantic_rules.json (bundled verbatim). The cv_mapping_json primitive resolves each rule's scope_path to its instance objects in mzpeak_index.json `metadata` and checks the accessions at cv_element_path. Advisory (warning) in Phase 1, like the table rules: several spec MUSTs use `use_term` on an abstract parent (e.g. ionization type MS:1000008, mass analyzer type MS:1000443) that real files satisfy with a concrete child, and empty parameter lists fail their MUST — these surface as advisory findings. MAY rules are not enforced. |
| `cv_term_placement_imaging` | `cv_mapping` | warning | none | Imaging-profile CV placement (cv_mapping/imaging_table_rules.json), gated on is_imaging, packed layout: the scan facet of spectra_metadata MUST carry the pixel coordinates IMS:1000050 (position x) AND IMS:1000051 (position y) — as the imaging profile's columns scan.position_x / scan.position_y, which carry their terms through column_mapping entries, or under an earlier draft's inflected names (scan.IMS_1000050_position_x). The mzPeak analogue of the mzML MALDI object rules. What it adds to the imaging rules is the facet: positions held in another facet (spectrum.position_x) satisfy imaging_coordinates_1based and imaging_position_columns and are reported only here. It looks at the set of terms in the facet, not at which column carries which, so two mappings with swapped accessions satisfy it (imaging_position_columns reports them). Split layout (positions in spectra_metadata_scans.parquet, as mzpeak-convert writes them): not evaluated — spectra_metadata has no scan facet there and the rule self-skips. This is deliberate: on that layout a missing position column is imaging_coordinates_1based's error and a missing or wrongly-termed column mapping is imaging_position_columns' error, so this rule would only repeat their findings as warnings. Until catalog 1.18 the rule read inflected column names only and warned on every packed archive that used the profile's names. |

## Primitive catalog (param contracts)

The 39 primitives used by this profile and the parameters each accepts:

- **`aux_arrays`** — params: file, count_column (number_of_auxiliary_arrays), list_column (auxiliary_arrays). Per row: declared count == actual list length (null treated as 0). DATA_SCAN.
- **`blob_hash`** — params: list, member, algo (e.g. sha256), hash_field, size_field. For each present member, recompute the digest and compare to hash_field; also compare byte length to size_field. Missing members are left to member_exists.
- **`chunk_bounds`** — params: file, group (chunk.<entity>_index), start_column, end_column. For each group: start<=end per chunk, and consecutive chunks non-overlapping & ascending by start. DATA_SCAN.
- **`chunk_columns`** — params: file, start_column (the chunk-start column whose presence flags the chunked sublayout), required ([companion columns that MUST then exist]). Schema-only; runs under --quick.
- **`column_mapping`** — params: none. Iterates mzpeak_index.json files[].column_mapping[]: each `path` must resolve to a column in that file's Parquet schema (unresolved -> warning); a mapping with term_marker=true MUST point at a boolean column (presence flag of the term) or a string/large-string column whose values are CURIEs of a child of the mapping's accession (spec d0c16b3); any other type is an error (rule severity), and it SHOULD carry an accession (warning). Outside --quick, string marker values are read: a non-CURIE or a CURIE that is not an is_a descendant of the accession is an error, a CURIE absent from the loaded CVs a warning (unverifiable). Self-gates on files without a column_mapping block.
- **`column_order`** — params: file, expected ({facet -> required first column}). The entity-index / FK key MUST be the first column of its facet. Cheap (reads the Parquet schema only).
- **`column_predicate`** — params: file, column, op (ge|gt|le|lt|finite), value (for the comparison ops), [severity]. 'finite' flags NaN/inf values (nulls OK); the comparison ops flag values failing the test. Reports count + first offending row/value.
- **`columns_present`** — params: file (logical table name), require_layout (optional: 'packed'|'split' — skips if the archive uses the other layout), schema_key (optional: use a different column schema than params.file). The engine injects the matching schema/tables/<schema_key_or_file>.columns.json; the rule checks required top_level_columns (flat split-layout tables) and/or facets/columns (nested packed-layout tables) and that each column's logical type matches the schema. A column's `type` may be a single logical type or a LIST of accepted types (e.g. ['double','float','integer']); type mismatch -> error, recovery rederive.
- **`count_sum_equals_rows`** — params: file, count_file, count_column, guard. If 'guard' column exists in file, asserts sum(count_file.count_column) == rows(file). Null counts treated as 0.
- **`cv_inflection`** — params: file (logical table name). The engine injects the set of pinned CV accessions. For each column whose leaf name matches ${CV}_${digits}_... (and any _unit_${CV}_${digits} suffix): unknown CV code -> error; known code but accession absent from the pinned OBO -> warning. The literal prefix 'ARROW_' is skipped (it is not a CV).
- **`cv_list_consistency`** — params: [files], [list]. The engine injects the profile's pinned CV versions. Gathers every CV code used in inflected columns (primary + unit accessions) across `files`; requires metadata.cv_list (at `list`) to declare each used code (spec: every referenced CV MUST be declared once in cv_list). Absent/empty cv_list, or a used-but-undeclared code -> error. Version policy: warn ONLY when a declared CV version is NEWER than the profile's pinned snapshot (the validator is behind -> update its bundled CVs); a same-or-older declared version does NOT warn (a plain version difference is not a problem).
- **`cv_mapping`** — params: mapping_file (bundled CvMapping path), path_map (scope_path -> {file,facet}), [require_imaging]. The engine injects the parsed mapping (_mapping) and the OBO is_a graph (_cv_isa). For each CvMappingRule: MUST -> finding at this rule's severity, SHOULD -> warning, MAY -> skipped (Phase 1). The accessions present in a facet are those its columns carry, in either of two ways: inflected into the column name (${CV}_${ACC}_${name}, plus a _unit_${UCV}_${UACC} suffix), or named by a column_mapping entry in the files[] entry of the table whose `path` starts with '<facet>.' and resolves to a column of the Parquet schema (a mapping to an absent column, to a column of another facet, or without an accession counts for nothing; a mapping in another table's files[] entry is not looked at). A term is satisfied by an accession that equals it (use_term) or is its is_a descendant (allow_children); non-repeatable terms matched by >1 accession are flagged. Unmapped scope_paths and absent files/facets are skipped. Schema + index only.
- **`cv_mapping_json`** — params: mapping_file (bundled CvMapping path). Same evaluation as cv_mapping but resolves scope_path/cv_element_path over the JSON index metadata (mzpeak_index.json `metadata`) instead of facet columns: a path walker follows key / key[] / key[field=value] segments to each scope INSTANCE, then gathers the accessions at the relative cv_element_path within it. A MUST is checked per scope instance; an absent scope (no instances) is vacuously conformant. No path_map (the spec paths are used directly).
- **`cv_terms_exist`** — no params. The engine injects the pinned CV accessions, the obsolete ones and the pinned versions. Gathers CURIEs from: every accession/unit key in mzpeak_index.json (column mappings, metadata params, files[].parameters); every JSON blob in a listed Parquet file's footer (array-index data_type/array_type/unit/transform, and accession/unit); outside --quick also the values of term_marker columns of string type and of every grid_type leaf in a Parquet schema (chunked-layout grid encoding). Each distinct CURIE whose prefix is a bundled CV (MS, UO, IMS, MZP) but which the pinned snapshot lacks or marks obsolete -> one finding naming the CV, the pinned version, the archive's declared version when different, and where it is written. Other prefixes are skipped. Inflected column names are cv_inflection's concern.
- **`cv_uri_form`** — params: cv (the cv_list id), pattern (regular expression the uri must match in full), form (the form as shown in messages), [list] (default metadata.cv_list), [require_imaging]. No entry with that id -> finding; each entry whose uri does not match -> finding, naming the branch when the uri contains /refs/heads/<name>/, /master/ or /main/, and saying so when the uri does contain a 40-character hash but in another form (http, a fork, github.com/blob). Index-only.
- **`data_kind_facet`** — params: data_kinds[], facets[], entity_types[]. For each index entry whose data_kind is in data_kinds AND entity_type is in entity_types, the Parquet must have a top-level column named in facets[]; otherwise error.
- **`dtype_role`** — params: file, column, role (label for messages), allowed[] (logical types: double|float|int|uint|string|bool|...). Errors if the stored logical type is not in allowed[].
- **`footer_count_equals_rows`** — params: file, footer_key, [count_column]. Compares the Parquet footer int to a count: total rows by default, or the NON-NULL entries of count_column when given (use the spectrum facet primary key, since the packed parallel-facet table has one row per longest facet -- e.g. per PASEF precursor -- not per spectrum). Absent footer -> warning; non-int -> error; mismatch -> error. Optional distinct_column (mutually exclusive with count_column): actual = number of DISTINCT non-null values — the per-file entity count of a data facet; gates on the column, skips under --quick. Optional max_index_column (exclusive with count_column and distinct_column): actual = one past the largest non-null value, 0 when there is none — the index bound mzPeakConverter stamps on a data facet (issue #1, decision D1); gates on the column, skips under --quick, silent on an absent key.
- **`footer_count_implies_rows`** — params: file + footer_keys[]. Footer-only (runs under --quick). For each PRESENT key: count>0 with 0 rows, or count==0 with rows>0 -> finding (no reader can use that state). Absent keys skip silently — writers legitimately omit these keys on some facets. Semantics-neutral: exact agreement is footer_count_equals_rows / footer_equals_points_in_file's job.
- **`footer_equals_points_in_file`** — params: file + footer_key (+ optional list_columns, default [chunk.intensity, chunk.mz_chunk_values]). Footer point counter must equal the points in THIS file: point layout -> num_rows (footer-only); chunk layout -> sum of list lengths over the first plain list column (data scan; skipped under --quick); numpress-only chunk facets -> info + skip. Absent key skips silently.
- **`foreign_key`** — params: file, column, ref_file, ref_column, [allow_null]. Every non-null child value must exist in the parent column; child nulls are flagged UNLESS allow_null=true (set it for a packed facet key that is legitimately null on other facets' rows).
- **`grouped_count_equals`** — params: file, group, count_file, count_column, key_column, [guard]. Groups the signal table by 'group' and checks each group's row count equals the declared count_column value (in count_file, keyed by key_column). Null declared count = 0. Per-spectrum analog of count_sum_equals_rows.
- **`grouped_monotonic`** — params: file, group, column, direction (nondecreasing). Within each group (stable argsort, so physical row order need not be contiguous) consecutive non-null values must not decrease. GATED on the declared order: enforced only when the column's array-index entry gives it a non-null sorting_rank; a column declared unsorted (sorting_rank null/absent) is skipped with an info finding (per schema/array_index.json). recovery reorder_pair = re-sort the axis carrying its parallel arrays.
- **`image_index_entry`** — params: list, member, entity_type, data_kind. Each declared image member present in the archive must be listed in mzpeak_index.json files[] with the given entity_type and data_kind; unlisted or listed differently -> finding. Absent members are member_exists' finding.
- **`imaging_coordinates`** — no params. If imaging, requires position_x AND position_y columns (or the older IMS_1000050_position_x / IMS_1000051_position_y) (checked independently) and that the minimum set value of position_x, position_y and, when present, position_z is >= 1 (1-based).
- **`imaging_grid`** — no params. The engine injects the CV is_a graph. If imaging, reads metadata.scan_settings_list (else the spectra_metadata footer copy): the number of entries carrying both IMS:1000042 and IMS:1000043 must be exactly 1, and in that entry each value must be an integer >= 1; every IMS:1000044/45/46/47/53/54 parameter of any entry must carry a unit descending from UO:0000001 (length unit); metadata.imaging.pixel_count.x/.y, when present, must equal the two counts. Index-only.
- **`imaging_marker`** — no params. Runs on every archive: a table carrying position columns while metadata.imaging.is_imaging is not true -> finding; metadata.imaging.coordinate_base present and not 1 -> finding. Index + schema only.
- **`imaging_position_bounds`** — no params. If imaging, streams every position column for its largest set value and compares per axis with the declared counts: IMS:1000042 (x) / IMS:1000043 (y) of the single scan-settings entry carrying both, and metadata.imaging.pixel_count.x/.y/.z; largest > count -> finding. largest < count is never a finding, whatever metadata.imaging.pixel_count_source says (a grid need not be fully sampled; a filtered archive keeps its source's counts). Counts that are absent or not integers >= 1 are skipped (imaging_grid reports them). DATA_SCAN.
- **`imaging_position_columns`** — params: terms ({axis: accession}, e.g. {x: IMS:1000050}). If imaging, for every position column of the scan table (axis matched by the full column name: position_<axis>, or an earlier draft's IMS_10000NN_position_<axis> / opt_IMS_10000NN_position_<axis>): its type must be an integer type; the table's files[] entry must carry a column_mapping entry whose path is the column (scan.position_x in the packed layout) and whose accession is the axis' term; a column not literally named position_<axis> (an earlier draft's IMS_1000050_position_x / opt_ name) additionally gets a WARNING, whatever the rule severity. Index + schema only.
- **`imaging_position_pairs`** — no params. If imaging, streams position_x and position_y together: a row that sets exactly one of them -> finding (first row named); no row that sets both -> finding. DATA_SCAN.
- **`imaging_preferred_unit`** — params: terms (accessions of scan-settings parameters), unit (the recommended unit, default UO:0000017). The engine injects the CV is_a graph. If imaging, each listed parameter of any scan-settings entry whose unit is a length unit (UO:0000001 descendant) other than `unit` -> finding. A missing or non-length unit is imaging_grid's. Index-only.
- **`index_contiguous`** — params: file, column, [severity]. The NON-NULL values of the column must equal 0,1,2,...,k-1 (nulls from packed-facet padding are ignored).
- **`index_files_present`** — no params. Walks mzpeak_index.json 'files[]'; errors if a listed member is missing. Every member must open as Parquet EXCEPT those declared as embedded optical images in metadata.imaging.images[] (matched by archive_path) — those are opaque blobs checked by the image primitives, not Parquet-parsed. Gating on the declared-image registry (not on data_kind/extension) keeps a mislabelled/corrupt member from dodging the parse check. Also reports a malformed 'files' list / entry.
- **`json_schema`** — params: schema (bundled schema id) + a source: {index:true} (the whole mzpeak_index.json), {index_path:'a.b'} (a dotted sub-path of the index), or {file, footer_key} (a JSON blob from a Parquet footer KV pair). Validates with jsonschema Draft7; each violation -> error at its JSON path. Present-but-unparseable -> error; absent -> skipped.
- **`member_checksum`** — params: quick_max_bytes. For every mzpeak_index.json files[] entry with a non-null `checksum`, streams the member's bytes (ZIP headers excluded) through SHA-512 and compares the lowercase hex digest (case-insensitive) with the declared value; a mismatch -> finding at the rule's severity. Entries without a checksum, and members absent from the archive (index_files_present's finding), are skipped. Under --quick only members of at most quick_max_bytes are rehashed, and one info finding counts the larger ones left unverified; without --quick every member is rehashed.
- **`member_exists`** — params: list (dotted path to an array in mzpeak_index.json), member (field holding the archive member name). Each entry's member must be a present archive member.
- **`parquet_row_group_health`** — params: [files], [facet], [min_bytes]. Footer-only (no column decode; runs under --quick). For each `files` entry that carries the `facet` top-level struct (default 'chunk'): if the Parquet file has exactly ONE row group whose uncompressed total_byte_size exceeds min_bytes (default 67108864 = 64 MB) -> warning. A multi-row-group file, a small single-group file, or a non-chunk (point/peaks) layout does NOT warn.
- **`tiff_magic`** — params: list, member, media_type_field, media_type. A member declared as media_type (default image/tiff), or named *.tif/*.tiff if no media_type, must start with a TIFF magic number (II*\0 little-endian or MM\0* big-endian).
- **`zip_stored`** — no params. mzPeak ZIP members MUST be stored uncompressed (compress_type STORED); a directory archive is skipped. Cheap.

## Column schemas

Required facets/columns and expected logical types per table (`columns_present` enforces these; edit these files to change what is required).

### `chromatograms_metadata`

_Packed parallel-facet layout (same shape as spectra_metadata): top-level struct columns 'chromatogram' / 'precursor' / 'selected_ion' (+ optional 'product' for SRM/MRM, per spec). CV-inflected columns (${CV}_${ACC}_${name}) are validated by cv_inflection, NOT declared here; only the stable structural keys are. 'chromatogram.index' is uint in the real corpus (spec doc says 'integer'); matches spectra_metadata.spectrum.index. Verified universal (required:true) across all 539 corpus archives carrying chromatograms_metadata.parquet._

| Facet | Facet required | Column | Type | Column required |
|---|---|---|---|---|
| `chromatogram` | yes | `index` | `uint` | yes |
| `chromatogram` | yes | `id` | `string` | yes |
| `chromatogram` | yes | `data_processing_ref` | `string` | no |
| `chromatogram` | yes | `MS_1003060_number_of_data_points` | `uint` | no |
| `chromatogram` | yes | `number_of_auxiliary_arrays` | `uint` | no |
| `precursor` | no | `source_index` | `uint` | yes |
| `precursor` | no | `precursor_index` | `uint` | no |
| `selected_ion` | no | `source_index` | `uint` | yes |
| `selected_ion` | no | `precursor_index` | `uint` | no |
| `product` | no | `source_index` | `uint` | yes |
| `product` | no | `product_index` | `uint` | no |

### `chromatograms_metadata_precursors`

_split-facet layout chromatogram precursor facet (mzPeak >= 0.7, spec e7f3447). Commonly 0 rows — an empty-but-present facet is explicitly legal per spec conformance.md._

| Facet | Facet required | Column | Type | Column required |
|---|---|---|---|---|

### `chromatograms_metadata_selected_ions`

_split-facet layout chromatogram selected-ion facet (mzPeak >= 0.7, spec e7f3447). Commonly 0 rows — an empty-but-present facet is explicitly legal._

| Facet | Facet required | Column | Type | Column required |
|---|---|---|---|---|

### `spectra_data`

_point layout. chunk/numpress layouts carry a `chunk` facet instead; point columns are optional so those layouts are not false-failed. mz/intensity accept both 32- and 64-bit floats or 32-bit integers (spec signal-data.md e7f3447: integers explicitly permitted; HUPO-PSI #11)._

| Facet | Facet required | Column | Type | Column required |
|---|---|---|---|---|
| `point` | no | `spectrum_index` | `uint` | no |
| `point` | no | `mz` | `['double', 'float']` | no |
| `point` | no | `intensity` | `['float', 'double', 'int']` | no |

### `spectra_metadata`

| Facet | Facet required | Column | Type | Column required |
|---|---|---|---|---|
| `spectrum` | yes | `index` | `uint` | yes |
| `spectrum` | yes | `MS_1000511_ms_level` | `integer` | no |
| `spectrum` | yes | `MS_1000525_spectrum_representation` | `string` | no |
| `spectrum` | yes | `MS_1003060_number_of_data_points` | `uint` | no |
| `spectrum` | yes | `MS_1003059_number_of_peaks` | `uint` | no |
| `scan` | yes | `source_index` | `uint` | yes |
| `precursor` | no | `source_index` | `uint` | yes |
| `selected_ion` | no | `source_index` | `uint` | yes |

### `spectra_metadata_precursors`

_split-facet layout precursor facet (mzPeak >= 0.7, spec e7f3447). Spec mandates non-null source_index FK. Zero-or-more rows per source_index; a timsTOF DDA-PASEF frame carries many precursors per spectrum._

| Facet | Facet required | Column | Type | Column required |
|---|---|---|---|---|

### `spectra_metadata_scans`

_split-facet layout scan facet (mzPeak >= 0.7, spec e7f3447). Spec mandates non-null source_index FK referencing spectra_metadata.index. Zero-or-more rows per source_index are legal._

| Facet | Facet required | Column | Type | Column required |
|---|---|---|---|---|

### `spectra_metadata_selected_ions`

_split-facet layout selected-ion facet (mzPeak >= 0.7, spec e7f3447). Spec mandates non-null source_index FK._

| Facet | Facet required | Column | Type | Column required |
|---|---|---|---|---|

### `spectra_metadata_split`

_split-facet layout primary table (mzPeak >= 0.7, spec e7f3447). Flat top-level columns; no nested struct facets. Spec mandates a unique non-null 'index' PK._

| Facet | Facet required | Column | Type | Column required |
|---|---|---|---|---|

### `spectra_peaks`

_centroided layout. mz/intensity accept both 32- and 64-bit floats or 32-bit integers (spec signal-data.md e7f3447: 'intensity arrays may be 32-bit float, 64-bit double, or even 32-bit integers')._

| Facet | Facet required | Column | Type | Column required |
|---|---|---|---|---|
| `point` | no | `spectrum_index` | `uint` | no |
| `point` | no | `mz` | `['double', 'float']` | no |
| `point` | no | `intensity` | `['float', 'double', 'int']` | no |

### `wavelength_spectra_data`

_Point or chunk layout for wavelength spectrum signal data. Key difference from spectra_data: the entity index column MUST be named 'wavelength_spectrum_index' (spec MUST: docs/schemas/wavelength-spectra.md). Signal columns (wavelength axis, intensity) follow the same point/chunk layout conventions as spectra_data but their names are CV-governed via the array_index footer. All point columns marked required:false so chunk-layout archives are not false-failed; data_kind_has_facet_wavelength separately checks that either point or chunk is present._

| Facet | Facet required | Column | Type | Column required |
|---|---|---|---|---|
| `point` | no | `wavelength_spectrum_index` | `['uint']` | no |

### `wavelength_spectra_metadata`

_Packed parallel-facet layout for wavelength (UV/DAD/EMR) spectrum metadata. Mirrors spectra_metadata but WITHOUT precursor/selected_ion facets (EMR spectra have no isolation or fragmentation). Required: spectrum.index primary key (uint) and scan.source_index FK (uint). Per spec docs/schemas/wavelength-spectra.md: 'spectrum.index and scan.source_index MUST be the first column of their respective facets.'_

| Facet | Facet required | Column | Type | Column required |
|---|---|---|---|---|
| `spectrum` | yes | `index` | `uint` | yes |
| `spectrum` | yes | `id` | `string` | no |
| `spectrum` | yes | `MS_1003060_number_of_data_points` | `uint` | no |
| `spectrum` | yes | `number_of_auxiliary_arrays` | `uint` | no |
| `scan` | no | `source_index` | `uint` | yes |

