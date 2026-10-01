# Changelog

Releases before 0.9.22 are recorded in the git history and in the catalog list in CLAUDE.md.

## Unreleased (rule-primitive catalog 1.18)

### Fixed (catalog 1.18)
- **`cv_term_placement_imaging` no longer warns on imaging archives that name their position columns as the
  imaging profile does.** The `cv_mapping` primitive built the set of terms in a facet from inflected column
  names alone (`scan.IMS_1000050_position_x`). The profile's columns are `scan.position_x` / `scan.position_y`,
  which carry `IMS:1000050` / `IMS:1000051` through `column_mapping` entries in the `files[]` entry of their
  table, so every packed-layout imaging archive with those names got "requires all of [position x, position y];
  missing: position x, position y" — as did all 31 packed imaging fixtures, which have used those names since
  0.9.23. A term now counts when a column of the facet carries it either way. A mapping counts only if its
  `path` names a column of the facet itself (`scan.position_x` — the columns the name route reads) that exists
  in the Parquet schema, and it names an accession; a mapping to an absent column, to a child of a nested list
  or struct (`scan.pix.position_x`), in another facet, or in another table's `files[]` entry counts for nothing,
  and neither does a term that appears only as a mapping's `unit`. The rule still warns on a packed imaging
  archive whose scan facet has neither, and when both columns are mapped to the same term. Catalog 1.18,
  because the behaviour of an existing primitive changed.
- **`cv_term_placement_tables` binds the same primitive and gains the same route.** A spectrum type declared
  through a boolean term-marker column that names a child term (`term_marker: true`, accession `MS:1000294`)
  is now seen. A term marker is a per-row flag, so it satisfies a required term but is not counted as an entry:
  an inflected spectrum type next to a boolean marker of a sibling type (`opt_calibration_spectrum`,
  `MS:1000928`) is not "matched by 2 entries", and the same holds for an inflected spectrum representation
  next to boolean centroid / profile markers. The primitive reads schema and index only, so a marker that is
  false on every row still counts as declaring its term, as an all-null inflected column does. Still not seen:
  a string term marker mapped to the parent `MS:1000559` (the spec's own form, child CURIEs as values) — the
  warning "missing: spectrum type" stays on such an archive.
- **The split layout is left to the imaging rules.** `cv_term_placement_imaging` evaluates the scan facet of
  `spectra_metadata`; mzpeak-convert writes positions to `spectra_metadata_scans.parquet`, where the rule does
  not run. On that layout `imaging_coordinates_1based` (no position columns) and `imaging_position_columns` (no
  mapping, or a mapping naming another term) already report these cases as errors, so the rule would only
  repeat them as warnings. Its `doc` says so. No finding on real converter output changes.
- 3 new fixtures (84 in total) and 74 new checks in `test_cv_mapping.py`.

### Added (catalog 1.17)
- **The remaining imaging profile checks** (spec PR #25, "What a validator checks" 2, 3, 6 and 7; catalog 1.17).
  A re-test for HUPO-PSI/mzPeak-specification#23 found three kinds of broken imaging archive that passed:
  - `imaging_position_columns` (error): `position_x`, `position_y` and, when present, `position_z` are integer
    columns, each with a `column_mapping` entry naming its term (`IMS:1000050` / `IMS:1000051` / `IMS:1000052`) in
    the `files[]` entry of the table that holds them. A column under an earlier draft's name
    (`opt_IMS_1000050_position_x`, as mzpeak-convert 0.15.0 wrote it) is held to the same and gets a warning
    for the name. Schema-only, so it runs under `--quick`.
  - `imaging_ims_cv_pinned` (error): an imaging archive declares `IMS` in `cv_list` with a uri of the form
    `https://raw.githubusercontent.com/imzML/imzML/<commit hash>/imagingMS.obo`, with a 40-character hash. A uri
    on a branch (`refs/heads/master`, `/master/`) is reported as such, and so is a uri that names the commit
    in another form (http, a fork, `github.com/.../blob/`). The corpus archives written by mzpeak-convert 0.15.0
    carry the branch uri and now fail.
  - `imaging_positions_within_grid` (error): no position exceeds the declared pixel counts (`IMS:1000042` /
    `IMS:1000043` in the scan settings, `metadata.imaging.pixel_count`, `z` included). A grid that is not fully
    sampled passes, whether its counts are `declared` or `observed_max`: an archive that mzpeak-convert filters
    from an `observed_max` archive (`in.mzpeak --rt ...`) keeps the source grid and the marker while its largest
    positions shrink. A data scan, skipped by `--quick`.
- **Length units other than micrometre (`imaging_length_unit_micrometre`, warning).** The profile accepts any unit
  of length for pixel size, max dimension and absolute position offset and recommends micrometre; another length
  unit, such as the centimetre accession some imzML writers attach to micrometre values, is now a warning. A
  missing or non-length unit stays the error of `imaging_grid_settings`.
- 13 new fixtures (81 in total) and `test_imaging_checks.py`.

### Changed (catalog 1.17)
- The imaging fixtures carry what the profile requires of them: column mappings for their position columns and
  the commit-pinned IMS uri.
- **A pixel position column is one by its full name**: `position_x` / `position_y` / `position_z`, or an earlier
  draft's `IMS_1000050_position_x` / `opt_IMS_1000050_position_x`. Until now any scan column whose name ended in
  `position_x` counted, so a column such as `stage_position_x` marked the archive as imaging and was held to the
  position rules (counted from 1, paired, and with 1.17 mapped, integer and inside the grid). No archive in the
  corpus has such a column.

### Added (catalog 1.16)
- **Member checksums (`member_checksum_sha512`, error).** Every `files[]` entry that declares a `checksum` has its
  member's bytes rehashed with SHA-512 (streamed) and compared (conformance.md, Basic Integrity). The adversarial
  review of 2026-09-30 found the converter's rewrite lane writing stale digests that the validator passed.
  `--quick` rehashes members up to 32 MB only and reports how many larger ones it skipped.
- **Imaging profile checks** (spec PR #25, "What a validator checks" 1–5, 7, 8): `imaging_marker` (position
  columns without `metadata.imaging.is_imaging: true`, or a `coordinate_base` other than 1);
  `imaging_positions_paired` (`position_x`/`position_y` both set or both null in every row, at least one positioned
  scan); `imaging_coordinates_1based` now also requires `position_z >= 1`; `imaging_grid_settings` (exactly one
  scan-settings entry with integer `IMS:1000042`/`IMS:1000043` >= 1, a length unit on pixel size, max dimension
  and absolute position offset, `metadata.imaging.pixel_count` equal to the scan settings); `image_files_entry`
  (warning: embedded images listed in `files[]` as `image`/`other`).
- **Written CV terms exist (`cv_terms_exist`, warning).** Accessions and units in `mzpeak_index.json`, array-index
  CURIEs in Parquet footers and, outside `--quick`, the values of string term-marker and `grid_type` columns are
  checked against the pinned MS/UO/IMS/MZP snapshots; each missing or obsolete term is reported once with the CV,
  the pinned and the declared version. On converter v0.16.0 output it flags the timsTOF `grid_type` values
  `MS:9999001`/`MS:9999002` and the obsolete `MS:1000843` carried over from the imzML example files.
- Imaging fixtures carry the pixel-grid scan settings the profile requires; 15 new fixtures and
  `test_conformance_checks.py`.

## 0.9.23 — 2026-09-30 (rule-primitive catalog 1.15)

### Fixed
- `imaging_coordinates` and imaging detection accept the pixel position columns under the names the imaging
  profile gives them, `position_x` / `position_y` (HUPO-PSI/mzPeak-specification#24, merged 2026-09-30). The rule
  looked only for the inflected `IMS_1000050_position_x`, so a conformant imaging archive — mzpeak-convert writes
  the spec names from its next release — failed with "missing position_x and/or position_y column". The older
  names (`IMS_1000050_position_x`, `opt_IMS_1000050_position_x`) are still accepted. The imaging fixtures now use
  the spec names.

### Changed
- The bundled MZP vocabulary snapshot is 0.2.0 (10 terms, the converter's `cv/mzpeak.obo` at tag
  `mzp-cv-0.2.0`); 0.1.0 had MZP:1000001–5 only, while timsTOF archives use MZP:1000008–10.

## 0.9.22 — 2026-09-26 (rule-primitive catalog 1.15)

### Fixed
- `column_mapping_valid` no longer rejects string term-marker columns. The spec (HUPO-PSI/mzPeak-specification
  `d0c16b3`, docs/layouts/metadata-tables.md and the `term_marker` description in schema/mzpeak_index.json) defines
  two kinds: a boolean column marking presence of a value-less term (e.g. `opt_calibration_spectrum`, MS:1000928),
  and a string or large-string column whose values are CURIEs of a child of the mapping's accession
  (e.g. `spectrum_representation`, MS:1000525). The rule used to accept only the first, so every archive written by
  mzpeak-convert 0.14.0 failed with three errors (`spectrum_representation`, `spectrum_type`, `chromatogram_type`)
  although it is conformant. Those archives now pass.

### Changed
- A string term-marker column's values are now checked outside `--quick`: a value that is not CURIE-shaped, or a
  CURIE that is not an `is_a` descendant of the mapping's accession, is an error. A value or accession absent from
  the pinned CV snapshots is a warning, since it cannot be verified.
- A term marker of any other type (e.g. an integer column) is still an error.
- New fixtures `pass/term_marker_string_child` and `fail/term_marker_string_nonchild`.
