# Profile reference — `mzpeak-0.9`

> **Generated** from the profile bundle by [`docs/gen_profile_page.py`](../gen_profile_page.py). Do not edit by hand — re-run the generator after changing the profile:
> `python docs/gen_profile_page.py mzpeak_validator/profiles/mzpeak-0.9 > docs/profiles/mzpeak-0.9.md`

- **Profile id:** `mzpeak-0.9`
- **mzPeak spec:** 0.9 (commit [`29e59b24f0ae`](https://github.com/HUPO-PSI/mzPeak-specification))
- **Rule-primitive catalog:** `1.7` (the cross-language contract the engine implements)
- **Rules:** 41 across 6 files
- **Note:** Keyed to the current spec (HUPO-PSI/mzPeak-specification; ref impl HUPO-PSI/mzPeak @ 29e59b24). Bundles the spec's JSON Schemas under schema/json/. Pre-1.0: the spec example still declares version 0.9.0.

## How validation works

Validation is driven by this *profile* — a versioned bundle of JSON Schemas, pinned controlled-vocabulary (CV) snapshots, and a declarative **rule set**. The engine implements a small **primitive catalog**; each rule is a data-only *instance* of a primitive, so any implementation that implements the catalog reproduces identical verdicts. Each rule self-gates (it no-ops when its target file/column is absent), so layout-independent checks apply everywhere while point-layout / imaging checks quietly skip where they do not apply.

## Conformance axes

Conformance is reported along independent axes: `well-formed`, `schema`, `numeric`, `index`, `cv`, `integrity`, `imaging`.

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
| cv | MS | 4.1.254 | `cv/psi-ms.obo.gz` |
| cv | IMS | 1.1.0 | `cv/imagingMS.obo` |
| cv | UO | 2026-01-16 | `cv/uo.obo` |
| json-schema | mzpeak_index_legacy |  | `schema/mzpeak_index.schema.json` |
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
| rules |  |  | `rules/structural.rules.json` |
| rules |  |  | `rules/cv.rules.json` |
| rules |  |  | `rules/numeric.rules.json` |
| rules |  |  | `rules/metadata.rules.json` |
| rules |  |  | `rules/imaging.rules.json` |
| rules |  |  | `rules/perf.rules.json` |

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
| `data_kind_has_facet` | `data_kind_facet` | error | none | A file the index advertises as signal (data_kind 'data arrays' or 'peaks' for a spectrum entity) must actually carry a 'point' or 'chunk' top-level column. Catches an index that promises signal over a file holding something else. Amend: widen data_kinds/entity_types to gate more files, or add a facet name (e.g. a future layout) to facets[]. |
| `columns_spectra_metadata` | `columns_present` | error | none | spectra_metadata has the required facets/columns and correct types per schema/tables/spectra_metadata.columns.json. To change WHICH columns are required or their expected type, edit that .columns.json file, not this rule. |
| `columns_spectra_data` | `columns_present` | error | none | spectra_data (profile/point layout) matches schema/tables/spectra_data.columns.json. point.mz/intensity accept both 32- and 64-bit floats: the reference writer emits mz=double/intensity=float, but L1-faithful imzML conversion keeps the source width, and both are valid pending HUPO-PSI #11 (binary array data types). To require a single width, narrow the type list in spectra_data.columns.json. |
| `columns_spectra_peaks` | `columns_present` | error | none | spectra_peaks (centroided layout) matches schema/tables/spectra_peaks.columns.json. Edit that schema to change required columns/types. |

### `cv.rules.json`

**Purpose.** Controlled-vocabulary discipline on inflected column names of the form ${CV}_${ACCESSION}_${name} (e.g. MS_1000511_ms_level): the CV code must be one the profile pins, and the accession should resolve inside that pinned OBO snapshot.

**Applies to.** any table with inflected columns; rules below target the two metadata tables.

| Rule id | Primitive | Severity | Recovery | What it checks |
|---|---|---|---|---|
| `cv_inflection_spectra_metadata` | `cv_inflection` | error | none | Inflected columns in spectra_metadata (spectrum/scan/precursor/selected_ion facets) use a pinned CV code and a resolvable accession, INCLUDING unit accessions (_unit_${CV}_${ACC}). severity=error is the code-unknown case; an unresolved accession is downgraded to warning inside the primitive. |
| `cv_inflection_chromatograms_metadata` | `cv_inflection` | error | none | Same check for chromatograms_metadata when present (the primitive no-ops if the file is absent, so this is harmless on archives without chromatograms). |
| `cv_list_declared` | `cv_list_consistency` | error | none | metadata.cv_list declares every CV code the archive uses (spec MUST). Absent cv_list on a file that uses CV codes is an error. Version policy: a declared CV version that is NEWER than the profile's pinned snapshot -> warning (the validator is behind; update its bundled CVs); a same-or-older declared version is fine and does NOT warn. This validates the FILE's own declaration (vs cv_inflection, which checks resolvability against the profile's pinned CVs). |

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
| `intensity_dtype_data` | `dtype_role` | error | none | spectra_data point.intensity is a floating type (float or double), never integer. Width-agnostic, matching the relaxed column schema (both 32- and 64-bit accepted). Edit allowed[] to broaden/narrow accepted types. |
| `mz_dtype_data` | `dtype_role` | error | none | spectra_data point.mz is a floating type (double or float), never integer. Width-agnostic, matching the relaxed column schema; the hard guarantee here is 'must be float, not int'. Width acceptance is the HUPO-PSI #11 question, decided in spectra_data.columns.json. |
| `point_fk_data` | `foreign_key` | error | none | Every spectra_data point.spectrum_index points to an existing spectra_metadata spectrum.index (and is non-null). A dangling FK means orphaned signal with no metadata -- not auto-recoverable. |
| `point_fk_peaks` | `foreign_key` | error | none | Same FK integrity from spectra_peaks back to spectrum.index. |
| `scan_source_index_fk` | `foreign_key` | error | rebuild | scan.source_index resolves to a spectrum.index (both in spectra_metadata). allow_null=true: in the packed parallel-facet layout the scan facet is null on rows owned by another facet (e.g. precursor-only PASEF rows), so child nulls are expected and not flagged. recovery=rebuild: the scan<->spectrum map is derivable. |
| `spectrum_index_contiguous` | `index_contiguous` | warning | none | spectrum.index is 0-based contiguous (0..k-1) over its non-null entries (packed-facet padding rows are ignored). Only a WARNING: a gapped index is unusual but still readable as long as the FKs resolve. Raise to severity 'error' if your profile requires dense indices. |
| `precursor_source_fk` | `foreign_key` | error | rebuild | precursor.source_index resolves to a spectrum.index. allow_null (packed layout). Ties each precursor back to the spectrum it was isolated from. |
| `selected_ion_source_fk` | `foreign_key` | error | rebuild | selected_ion.source_index resolves to a spectrum.index. allow_null (packed layout). |
| `per_spectrum_data_points` | `grouped_count_equals` | error | rederive | Per-spectrum integrity: each spectrum's profile-point rows in spectra_data equal its declared number_of_data_points (null counted as 0). Stronger than data_points_sum -- catches localized/swapped count corruption a global sum hides. Gated to the point layout via 'guard'. |
| `per_spectrum_peaks` | `grouped_count_equals` | error | rederive | Per-spectrum integrity for the centroided table: each spectrum's peak rows in spectra_peaks equal its declared number_of_peaks (null counted as 0). The missing peaks analog of per_spectrum_data_points. |

### `imaging.rules.json`

**Purpose.** Checks that apply only to MS-imaging archives: 1-based pixel coordinates, and integrity of any embedded optical images (TIFFs stored as ZIP members and described in metadata.imaging.images[]).

**Applies to.** imaging archives only. An archive is 'imaging' when metadata.imaging.is_imaging is true OR a spectra_metadata column matches IMS_1000050 (position x). The coordinate rule self-gates on that; the image rules self-gate on the presence of metadata.imaging.images[] (no images[] -> they no-op).

**Spec basis.** imzML2mzPeak docs/mzpeak-imaging-spec-suggestions.md, Edits 6-8: 1-based coordinates preserved from imzML; optical images embedded verbatim as images/image_NNNN.tiff and registered in metadata.imaging.images[]. Per that spec, a missing/mismatched optical image is a WARNING (auxiliary; outside the spectral L1 contract).

| Rule id | Primitive | Severity | Recovery | What it checks |
|---|---|---|---|---|
| `imaging_coordinates_1based` | `imaging_coordinates` | error | none | Imaging archives carry both position_x and position_y, 1-based (min coordinate >= 1). The deliberate offset from the 0-based spectrum.index is intentional (coordinates are preserved verbatim from imzML). No params. |
| `image_member_present` | `member_exists` | warning | none | Every optical image declared in metadata.imaging.images[].archive_path is actually present in the archive. WARNING, not error: optical images are auxiliary. Amend 'list'/'member' if image bookkeeping moves elsewhere in the index. |
| `image_blob_hash` | `blob_hash` | warning | recompute | A present image member's bytes match its declared sha256 and size_bytes. recovery=recompute: a stale digest is fixable without touching the image. Change 'algo' if a different hash is recorded; null/absent hash fields are skipped per entry. |
| `image_tiff_magic` | `tiff_magic` | warning | none | An image declared image/tiff really begins with a TIFF magic number (guards against a truncated/mislabelled blob). v0.5 optical images are TIFF-only; if other media types are later allowed, gate this rule by adjusting media_type or add sibling rules per type. |

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
| `array_index_data_valid` | `json_schema` | error | none | spectra_data footer 'spectrum_array_index' conforms to schema/json/array_index.json (entries, path, buffer_format, data/array types, sorting_rank, ...). |
| `array_index_peaks_valid` | `json_schema` | error | none | spectra_peaks footer 'spectrum_array_index' conforms to schema/json/array_index.json. |

### `perf.rules.json`

**Purpose.** Advisory, NON-conformance checks on the PHYSICAL Parquet layout that affect random-access read performance. These never FAIL an archive (warning-only): the data is correct, but laid out so that single-spectrum / random reads are expensive. Mirrors the spec's reader-friendly row-group sizing guidance.

**Applies to.** chunked data facets (spectra_data / chromatograms_data carrying a `chunk` struct). The point/peaks per-peak layout is chunked correctly by the writer and is not flagged.

| Rule id | Primitive | Severity | Recovery | What it checks |
|---|---|---|---|---|
| `data_row_group_not_monolithic` | `parquet_row_group_health` | warning | normalize | Advisory (perf, not conformance): a chunked spectra_data / chromatograms_data facet should not be stored in a single oversized Parquet row group. Parquet reads/decodes at row-group granularity, so a lone monolithic group means every random single-spectrum read decodes the whole group (the converter's chunk path can emit one group because its row-group cap is a row count, and one chunk-row is a whole-spectrum list). Writers should bound row groups by uncompressed size or point count (e.g. <= ~64 MB / ~2 M points). Warning-only; never fails an archive. |

## Primitive catalog (param contracts)

The 19 primitives used by this profile and the parameters each accepts:

- **`blob_hash`** — params: list, member, algo (e.g. sha256), hash_field, size_field. For each present member, recompute the digest and compare to hash_field; also compare byte length to size_field. Missing members are left to member_exists.
- **`column_predicate`** — params: file, column, op (ge|gt|le|lt|finite), value (for the comparison ops), [severity]. 'finite' flags NaN/inf values (nulls OK); the comparison ops flag values failing the test. Reports count + first offending row/value.
- **`columns_present`** — params: file (logical table name). The engine injects the matching schema/tables/<file>.columns.json; the rule checks required facets/columns are present and that each column's logical type matches the schema. A column's `type` may be a single logical type or a LIST of accepted types (e.g. ['double','float']); type mismatch -> error, recovery rederive.
- **`count_sum_equals_rows`** — params: file, count_file, count_column, guard. If 'guard' column exists in file, asserts sum(count_file.count_column) == rows(file). Null counts treated as 0.
- **`cv_inflection`** — params: file (logical table name). The engine injects the set of pinned CV accessions. For each column whose leaf name matches ${CV}_${digits}_... (and any _unit_${CV}_${digits} suffix): unknown CV code -> error; known code but accession absent from the pinned OBO -> warning. The literal prefix 'ARROW_' is skipped (it is not a CV).
- **`cv_list_consistency`** — params: [files], [list]. The engine injects the profile's pinned CV versions. Gathers every CV code used in inflected columns (primary + unit accessions) across `files`; requires metadata.cv_list (at `list`) to declare each used code (spec: every referenced CV MUST be declared once in cv_list). Absent/empty cv_list, or a used-but-undeclared code -> error. Version policy: warn ONLY when a declared CV version is NEWER than the profile's pinned snapshot (the validator is behind -> update its bundled CVs); a same-or-older declared version does NOT warn (a plain version difference is not a problem).
- **`data_kind_facet`** — params: data_kinds[], facets[], entity_types[]. For each index entry whose data_kind is in data_kinds AND entity_type is in entity_types, the Parquet must have a top-level column named in facets[]; otherwise error.
- **`dtype_role`** — params: file, column, role (label for messages), allowed[] (logical types: double|float|int|uint|string|bool|...). Errors if the stored logical type is not in allowed[].
- **`footer_count_equals_rows`** — params: file, footer_key, [count_column]. Compares the Parquet footer int to a count: total rows by default, or the NON-NULL entries of count_column when given (use the spectrum facet primary key, since the packed parallel-facet table has one row per longest facet -- e.g. per PASEF precursor -- not per spectrum). Absent footer -> warning; non-int -> error; mismatch -> error.
- **`foreign_key`** — params: file, column, ref_file, ref_column, [allow_null]. Every non-null child value must exist in the parent column; child nulls are flagged UNLESS allow_null=true (set it for a packed facet key that is legitimately null on other facets' rows).
- **`grouped_count_equals`** — params: file, group, count_file, count_column, key_column, [guard]. Groups the signal table by 'group' and checks each group's row count equals the declared count_column value (in count_file, keyed by key_column). Null declared count = 0. Per-spectrum analog of count_sum_equals_rows.
- **`grouped_monotonic`** — params: file, group, column, direction (nondecreasing). Within each group (stable argsort, so physical row order need not be contiguous) consecutive non-null values must not decrease. GATED on the declared order: enforced only when the column's array-index entry gives it a non-null sorting_rank; a column declared unsorted (sorting_rank null/absent) is skipped with an info finding (per schema/array_index.json). recovery reorder_pair = re-sort the axis carrying its parallel arrays.
- **`imaging_coordinates`** — no params. If imaging, requires IMS_1000050_position_x AND IMS_1000051_position_y columns (checked independently) and that their minimum value is >= 1 (1-based).
- **`index_contiguous`** — params: file, column, [severity]. The NON-NULL values of the column must equal 0,1,2,...,k-1 (nulls from packed-facet padding are ignored).
- **`index_files_present`** — no params. Walks mzpeak_index.json 'files[]'; errors if a listed member is missing. Every member must open as Parquet EXCEPT those declared as embedded optical images in metadata.imaging.images[] (matched by archive_path) — those are opaque blobs checked by the image primitives, not Parquet-parsed. Gating on the declared-image registry (not on data_kind/extension) keeps a mislabelled/corrupt member from dodging the parse check. Also reports a malformed 'files' list / entry.
- **`json_schema`** — params: schema (bundled schema id) + a source: {index:true} (the whole mzpeak_index.json), {index_path:'a.b'} (a dotted sub-path of the index), or {file, footer_key} (a JSON blob from a Parquet footer KV pair). Validates with jsonschema Draft7; each violation -> error at its JSON path. Present-but-unparseable -> error; absent -> skipped.
- **`member_exists`** — params: list (dotted path to an array in mzpeak_index.json), member (field holding the archive member name). Each entry's member must be a present archive member.
- **`parquet_row_group_health`** — params: [files], [facet], [min_bytes]. Footer-only (no column decode; runs under --quick). For each `files` entry that carries the `facet` top-level struct (default 'chunk'): if the Parquet file has exactly ONE row group whose uncompressed total_byte_size exceeds min_bytes (default 67108864 = 64 MB) -> warning. A multi-row-group file, a small single-group file, or a non-chunk (point/peaks) layout does NOT warn.
- **`tiff_magic`** — params: list, member, media_type_field, media_type. A member declared as media_type (default image/tiff), or named *.tif/*.tiff if no media_type, must start with a TIFF magic number (II*\0 little-endian or MM\0* big-endian).

## Column schemas

Required facets/columns and expected logical types per table (`columns_present` enforces these; edit these files to change what is required).

### `spectra_data`

_point layout. chunk/numpress layouts carry a `chunk` facet instead; point columns are optional so those layouts are not false-failed (their decoding is a v1 TODO). mz/intensity accept both 32- and 64-bit floats: the reference writer emits mz=double/intensity=float, but L1-faithful imzML conversion preserves the source width (32-bit m/z, 64-bit intensity) -- both are valid pending HUPO-PSI #11._

| Facet | Facet required | Column | Type | Column required |
|---|---|---|---|---|
| `point` | no | `spectrum_index` | `uint` | no |
| `point` | no | `mz` | `['double', 'float']` | no |
| `point` | no | `intensity` | `['float', 'double']` | no |

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

### `spectra_peaks`

_centroided layout. mz/intensity accept both 32- and 64-bit floats (see spectra_data note; HUPO-PSI #11)._

| Facet | Facet required | Column | Type | Column required |
|---|---|---|---|---|
| `point` | no | `spectrum_index` | `uint` | no |
| `point` | no | `mz` | `['double', 'float']` | no |
| `point` | no | `intensity` | `['float', 'double']` | no |

