# Changelog

Releases before 0.9.22 are recorded in the git history and in the catalog list in CLAUDE.md.

## Unreleased

### Fixed
- `imaging_coordinates` and imaging detection accept the pixel position columns under the names the imaging
  profile gives them, `position_x` / `position_y` (HUPO-PSI/mzPeak-specification#24, merged 2026-09-30). The rule
  looked only for the inflected `IMS_1000050_position_x`, so a conformant imaging archive — mzpeak-convert writes
  the spec names from its next release — failed with "missing position_x and/or position_y column". The older
  names (`IMS_1000050_position_x`, `opt_IMS_1000050_position_x`) are still accepted. The imaging fixtures now use
  the spec names.

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
