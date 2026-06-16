# Roadmap — full mzPeak conformance coverage

**Status:** in progress · **Date:** 2026-06-09 · **Basis:** the synthesized adversarial review (codex + vibe + internal red-team) against the current spec at `HUPO-PSI/mzPeak-specification`.

> **Progress (2026-06-15): Phases 0, 1, 2 (CV depth + placement), and 5 (counts + FKs) DONE** — catalog `1.3 → 1.8`.
> - **1.4** — re-pinned to the current spec, bundled its JSON Schemas, fixed the `metadata.version` path bug, added
>   `json_schema` (index + footer-blob + array-index validation), `grouped_count_equals` (per-spectrum counts), and
>   the missing precursor/selected_ion FKs.
> - **1.5–1.6** — `cv_list_consistency` (cv_list completeness + CV-CURIE resolution; direction-aware version warning
>   that fires only when a file declares a CV *newer* than the pinned snapshot). Bundled CVs refreshed to PSI-MS 4.1.254.
> - **1.7** — `parquet_row_group_health` (advisory perf warning: a chunked data facet in one monolithic row group).
> - **1.8** — `cv_mapping` (CV term-**placement** via the PSI CvMapping model — the spec's own `table_rules.json` bundled
>   verbatim; MUST/SHOULD + AND/OR/XOR + `allow_children` + cardinality; Phase-1 maps `/spectrum` + selected-ions at
>   warning severity) + finding-level `fix` tips. See [cv-mapping-design.md](cv-mapping-design.md). (The planned name `cv_placement` shipped as `cv_mapping`.)
>
> The 539-file corpus re-validates with **zero false positives** (537 PASS; the 2 FAIL are pre-existing converter
> metadata gaps on newly-added/stale files).
> **Remaining:** Phase 2b (wire the bundled `semantic_rules.json` JSON-metadata-param placements + data-array terms +
> MAY inverse-check), Phase 3 (chunked/numpress + aux arrays), Phase 4 (chromatograms column schema + wavelength),
> Phase 5 aggregates (base-peak/TIC recompute), Phase 6 (container/page-index MUSTs), Phase 8 (auto-repair).

**Goal:** close the validator from "point-layout structural/numeric/FK + shallow CV resolvability" to **full mzPeak conformance** — every entity type, both signal layouts, the JSON index + footer metadata, and semantic CV validation.

## Principles (unchanged)

- **Rules are data.** New checks = new *primitive(s)* in `core.py` + rule instances in `profiles/<id>/rules/*.rules.json`. The engine stays a thin catalog.
- **Catalog versioning.** Each phase bumps `CATALOG_VERSION` **and** the profile's `rule_primitive_catalog` together. Currently **1.3**; phases below take it to **2.x**.
- **Every phase ships:** new primitive(s) + rules + `about`/`doc` + fixtures (a fail case per new rule, plus a pass case) + regenerated `docs/profiles/<id>.md`, with `smoke_test.py` green.
- **No network at validate time.** All schemas + CV snapshots are bundled in the profile.
- **Self-gating.** Every primitive no-ops when its target is absent, so partial archives validate cleanly.

## Phase overview

| Phase | Theme | New primitives | Gaps closed | Effort | Depends on |
|---|---|---|---|---|---|
| **0** | Foundation & spec re-pin | — | version-path bug; stale pin | S | — |
| **1** | JSON-Schema validation | `json_schema` | index + all footer metadata blobs; array-index structure | M | 0 |
| **2** | CV depth | `cv_list_consistency`, `cv_curies_resolve`, `cv_required`, `cv_placement` | the entire CV axis (Q3) | L | 0,1 |
| **3** | Layout completeness | `chunk_bounds`, `chunk_columns`, `aux_arrays` | chunked/numpress; auxiliary arrays | M | 0 |
| **4** | Entity coverage | (reuse + `data_kind_facet` params) | chromatograms; wavelength/EMR | M | 0,1 |
| **5** | Integrity & aggregates | `grouped_count_equals`, `aggregate_matches` | per-spectrum counts; missing FKs; declared aggregates | M | — |
| **6** | Container & Parquet MUSTs | `zip_stored`, `parquet_page_index`, `column_order` | uncompressed members; page index; index-first; index MUST | S–M | — |
| **7** | Definition-quality cleanup | — | rule/doc/severity/recovery misalignments | S | folds into 1–6 |
| **8** | Auto-repair (separate track) | — (`repair` mode) | the design-doc §4 promise | L | 1–6 |

Effort: S ≈ ½–1 day, M ≈ 2–4 days, L ≈ 1–2 weeks.

---

## Phase 0 — Foundation & spec re-pin (prerequisite)

The spec moved to `HUPO-PSI/mzPeak-specification`; `cv_list`/`version`/`scan_settings_list` are now normative; the schema files are byte-identical to `d1aaaf84` but the prose evolved.

- **Re-pin** `profile.json`: point `mzpeak_spec` at the spec-repo commit; refresh the now-stale `note`.
- **Bundle the spec's JSON Schemas** under `profiles/mzpeak-0.9/schema/json/`: `mzpeak_index`, `cv_list`, `file_description`, `instrument_configuration`, `software`, `sample`, `data_processing`, `scan_settings_list`, `ms_run`, `array_index`, `auxiliary_array`, `param`. Register each as a `json-schema` artifact.
- **Refresh CV snapshots** to the versions the spec example declares (MS 4.1.248, UO 2026-01-16) and record them.
- **Fix the version-path bug:** `declared_version()` reads `metadata.format.version`; the spec uses **`metadata.version`**. Read `metadata.version` (accept the legacy path as fallback). This stops the always-on "defaulted to latest" warning for compliant files and makes version→profile selection actually work.
- *No catalog bump* (no new primitive). Smoke stays green.

## Phase 1 — JSON-Schema validation  → catalog **1.4**

The largest single coverage win: the whole JSON/metadata axis is currently unenforced.

- **Dependency:** add `jsonschema` (pure-Python, offline) to `pyproject.toml`.
- **Primitive `json_schema`** — validate a JSON document against a bundled schema. Params: `source` (`index` | a footer KV key like `file_description`), `file` (for footer sources), `schema` (artifact id). DATA_SCAN: no (cheap).
- **Rules:**
  - `index_schema_valid` — `mzpeak_index.json` vs `mzpeak_index` schema.
  - `metadata_<blob>_valid` — each footer KV blob (`cv_list`, `file_description`, `instrument_configuration_list`, `software_list`, `sample_list`, `data_processing_method_list`, `scan_settings_list`, `run`) vs its schema, on `spectra_metadata` (and where present, `chromatograms_metadata`).
  - `array_index_valid` — `spectrum_array_index` / `chromatogram_array_index` vs `array_index` schema.
- **Fixtures:** malformed index; malformed `file_description`; malformed array index; valid passes.
- Closes review gaps **#1, #3 (structure), cv_list structural**.

## Phase 2 — CV depth  → catalog **1.5**

The weakest axis. Build it in sub-steps so value lands early.

- **2a `cv_list_consistency`** — read `metadata.cv_list`; require it present; every CV **code** used in any inflected column ∈ `cv_list`; each entry has `id`/`uri`/`version`; **warn** if a declared version ≠ the pinned snapshot. (Decouples CV checking from the *profile's* CVs → checks the *file's* declaration.)
- **2b `cv_curies_resolve`** — resolve **all** CURIEs, not just inflected column *names*: the `_unit_${UCV}_${UACC}` unit suffixes, accessions inside `parameters` lists, `array_index` entries, and footer-metadata param accessions. Unknown code → error; unresolved/obsolete accession → warning (with `replaced_by` when the OBO provides it).
- **2c `cv_required`** — required CV terms per entity (e.g. a spectrum MUST carry `ms_level`, `spectrum_representation`), driven by a declarative `required-terms` table in the profile. Cheap, high value.
- **2d `cv_placement`** — PSI-CvMapping-style: each inflected accession must be allowed in its context (facet/column), with cardinality. Driven by a `cv_mapping.json` table in the profile (authored from the spec's per-facet term lists). The deepest item; can ship after 2a–2c.
- *(Deferred to a 2.x point release):* value-type (`has_value_type`) and unit-appropriateness, which need parsing OBO `relationship`/`xref` — heavier OBO modelling.
- **Fixtures:** code-not-in-cv_list; unresolved unit; missing required term; mis-placed term.
- Closes the whole **Q3** list.

## Phase 3 — Layout completeness (chunked/numpress + auxiliary)  → catalog **1.6**

- **`chunk_columns`** — a chunked signal file has `chunk_start`/`chunk_end`/`chunk_encoding`/`mz_chunk_values` (+ numpress byte columns) **exactly once**, entity-index column first, correct logical types.
- **`chunk_bounds`** — within each `chunk.spectrum_index`: `chunk_start ≤ chunk_end`, chunks **non-overlapping and ascending** (the chunked analog of `grouped_monotonic`). DATA_SCAN.
- **`aux_arrays`** — `*.auxiliary_arrays` structure vs `auxiliary_array` schema; `number_of_auxiliary_arrays` matches the list length; declared compression/data-type are recognised.
- **Fixtures:** overlapping chunks; missing `chunk_end`; wrong aux-array count.
- Closes gaps **#2, #8(aux)**. Removes the numpress/chunked blind spot (a large fraction of real files).

## Phase 4 — Entity coverage (chromatograms + wavelength/EMR)  → catalog **1.7**

Mostly *new rule instances over existing primitives* + column schemas.

- **Column schemas:** `chromatograms_metadata/.data`, `wavelength_spectra_metadata/.data` under `schema/tables/`.
- **Extend `data_kind_facet`** params to also gate `chromatogram` and `wavelength spectrum` entity types (fixes the over-narrow scope).
- **New rule instances** (reusing `columns_present`, `foreign_key`, `index_contiguous`, `grouped_monotonic`, `cv_inflection`): chromatogram `index` contiguity, `point.chromatogram_index → chromatogram.index` FK, time monotonic; wavelength equivalents.
- **Fixtures:** broken chromatogram FK; non-monotonic chromatogram time.
- Closes **#4, #5(entities)** and the `data_kind_facet` definition issue.

## Phase 5 — Integrity & aggregates (silent-corruption catchers)  → catalog **1.8**

The checks the validator is uniquely positioned to provide.

- **`grouped_count_equals`** — group the signal table by `spectrum_index`; each group's row count must equal that spectrum's declared `number_of_data_points` (point/`spectra_data`) / `number_of_peaks` (`spectra_peaks`). Stronger than the global `data_points_sum`; adds the missing peaks analog.
- **`aggregate_matches`** — recompute per-spectrum aggregates from the data and compare to declared, within tolerance: base-peak m/z (`MS:1000504`) & intensity (`MS:1000505`), TIC (`MS:1000285`), lowest/highest observed m/z (`MS:1000528`/`MS:1000527`). recovery `recompute`.
- **Missing FKs** (rule instances on `foreign_key`): `precursor.precursor_index`, `selected_ion.precursor_index` → `spectrum.index`; imaging `spectrum.pixel_index → pixel.index`.
- **Fixtures:** per-spectrum count off-by-one; fabricated TIC; dangling `precursor_index`.
- Closes **#5(FKs), #6, #7**.

## Phase 6 — Container & Parquet-level MUSTs  → catalog **1.9**

- **`zip_stored`** — ZIP members **MUST** be stored uncompressed (read `ZipInfo.compress_type`); currently only a zip-bomb ratio guard exists.
- **`parquet_page_index`** — writers **MUST** write the Parquet page index (inspect column-chunk offset/column index presence).
- **`column_order`** — entity-index / FK columns **MUST** be the first column of their facet.
- **Promote `spectrum_index_contiguous` to `error`** (spec: `index` MUST increment by 1) — or make severity profile-configurable.
- **Fixtures:** a deflate-compressed member; index column not first.
- Closes **#8(container/page/order)** and the severity-vs-MUST issue.

## Phase 7 — Definition-quality cleanups (fold into 1–6)

Small, do alongside the relevant phase: `columns_present` rule-level `recovery` vs the per-finding `rederive` it emits; `columns_spectra_data` optionality overclaim (require the point columns when a `point` facet exists); `index_files_present` recovery class for missing/unopenable files; `imaging_coordinates` integer-type check (a `1.5` coordinate currently passes); make every `severity` declaration match the level the primitive actually emits.

## Phase 8 — Auto-repair (`repair --safe`) — separate track

The design-doc §4 promise: a paired repair mode that applies the **lossless** recovery classes (`rebuild`/`recompute`/`rederive`/`reorder_pair`), emits a new archive + change log, and records each repair as a CV-described `data_processing` step. Orthogonal to validation coverage; do after the rule set is broad enough to drive it.

---

## New-primitive summary (catalog 1.3 → 2.0)

`json_schema` · `cv_list_consistency` · `cv_curies_resolve` · `cv_required` · `cv_placement` · `chunk_columns` · `chunk_bounds` · `aux_arrays` · `grouped_count_equals` · `aggregate_matches` · `zip_stored` · `parquet_page_index` · `column_order` (13 new → ~28 total). Declare **catalog 2.0** once all land.

## Dependencies, risks, decisions

- **New runtime dep:** `jsonschema` (Phase 1). Pure-Python, offline — acceptable. Everything else is stdlib + pyarrow/numpy.
- **CvMapping authoring (2d):** the per-context allowed-term tables must be authored from the spec's facet term lists; this is content work, not just code. Front-load 2a–2c (cheap, high value) and treat 2d as its own deliverable.
- **Tolerances (Phase 5):** floating aggregates need declared per-axis tolerances (mirror the converter's `tolerance.rs` / the design's L2 bounds) to avoid false positives.
- **Profile strategy:** keep the profile id `mzpeak-0.9` (spec example still says `"version": "0.9.0"`) but re-pin its source and bundle the new schemas. If the spec cuts a numbered release, fork `mzpeak-1.0`.
- **Corpus:** the 207-file pwiz/zenodo corpus already gives breadth; each new rule still needs a *deliberately-broken* fixture (the cross-language verdict gate).

## Suggested sequencing (value-first)

**0 → 1 → 5 → 2 → 3 → 4 → 6 → 8.** Phase 0 unblocks; Phase 1 buys the whole metadata axis cheaply; Phase 5 adds the high-value corruption catchers with no new deps; Phase 2 is the deepest (CV) and benefits from 1's schema plumbing; 3/4/6 fill remaining breadth; 8 is the separate repair track.
