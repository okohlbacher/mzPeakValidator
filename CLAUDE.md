# CLAUDE.md — mzPeakValidator

A first, **language-independent-by-design** validator for the **mzPeak** mass-spectrometry
file format (HUPO-PSI's Parquet-in-ZIP successor to mzML). Validation is driven by a
versioned **profile** (JSON Schemas + pinned CV OBO snapshots + declarative rules); a small
Python engine implements a **rule-primitive catalog**. Rules are *data*, so any language can
reproduce identical verdicts.

- GitHub: `okohlbacher/mzPeakValidator` (public). User-facing intro: [README.md](README.md). Full design: [docs/validation-design.md](docs/validation-design.md).
- mzPeak is pre-1.0 WIP with no version tag; this profile is keyed to spec commit `29e59b24f0ae9447a7f5fcf5c0606dce697b7847` (`HUPO-PSI/mzPeak-specification`).
- The Rust reference implementation lives on disk at `~/.cargo/git/checkouts/mzpeak-cd0ccbb7d90f04e9/d1aaaf8/` (src/, doc/index.md, schema/, example `.mzpeak` files).

## Commands

```bash
pip install -e .                                                  # editable dev install (pulls pyarrow, numpy); gives the `mzpeak-validate` script
mzpeak-validate <archive.mzpeak|dir/> [--json out.json] [--log findings.log] [--quick] [--profile DIR]
python -m mzpeak_validator <archive.mzpeak|dir/> ...              # equivalent, no console script needed
python smoke_test.py                                              # MUST stay green before any commit
MZPEAK_CORPUS=/dir/of/mzpeak python smoke_test.py                 # point the real-file corpus elsewhere
python make_fixtures.py [out_dir]                                 # materialise fixtures to inspect them
```

- Exit codes: `0` no errors, `1` ≥1 error-level finding, `2` engine failure.
- `--quick` skips full-column data scans (the `DATA_SCAN` primitives); cheap footer/metadata checks still run. The smoke test auto-uses `--quick` for corpus files >50 MB.
- `--json FILE` writes the full JSON report; `--log FILE` writes the human-readable findings (errors/warnings/info), byte-identical to console output.
- `smoke_test.py` is the regression gate: 15 fixtures (10 fail + 5 pass, incl. 4 imaging) each must reach their expected verdict and trip the named rule, plus it validates whatever real `.mzpeak` corpus it finds.

## Architecture

- **`mzpeak_validator/`** — the installable package (packaging in `pyproject.toml`; `pip install .` ships the profiles as package data; console script `mzpeak-validate = mzpeak_validator.core:main`).
  - **`core.py`** (~950 lines) — the engine: `Archive` (opens a `.mzpeak` ZIP or unpacked dir; exposes Parquet schemas/columns *and* raw ZIP members), `Profile` (loads manifest + rules + column schemas + CV snapshots), `Report` (collates findings), the `PRIMITIVES` dict (26 primitives), and `run()`/`main()`. `PROFILES_ROOT = Path(__file__).parent / "profiles"` resolves the bundled profiles whether running from source or installed.
  - **`__init__.py`** re-exports the public API (`run`, `main`, …); **`__main__.py`** enables `python -m mzpeak_validator`.
- **`mzpeak_validator/profiles/mzpeak-0.9/`** — the profile bundle (shipped inside the package):
  - `profile.json` — manifest: spec/commit, `rule_primitive_catalog` version, and `artifacts[]` (CVs, schemas, rule files). `sha256` fields are `null` until a future `--seal` step fills them.
  - `cv/` — pinned OBO snapshots: `psi-ms.obo.gz`, `imagingMS.obo`, `uo.obo`.
  - `schema/` — `mzpeak_index.schema.json` + `tables/*.columns.json` (per-table column specs: which facets/columns are required and their expected logical types).
  - `rules/` — `{structural,cv,numeric,metadata,imaging,perf,semantic,layout,container}.rules.json`: the declarative rule instances (`perf` = advisory physical-layout checks that never FAIL; `semantic` = CV term-PLACEMENT rules binding the bundled CvMapping files to mzPeak facets; `layout` = chunked-signal + auxiliary-array integrity; `container` = ZIP/Parquet-level MUSTs).
  - `cv_mapping/` — bundled PSI **CvMapping** files from the spec repo, byte-for-byte (`table_rules.json`, `semantic_rules.json`, `cv_mapping_rule.schema.json`) + `imaging_table_rules.json`. The `cv_mapping` primitive evaluates these (term placement / cardinality / child inheritance). See [docs/cv-mapping-design.md](docs/cv-mapping-design.md).
- **`make_fixtures.py`** — builds tiny pass/fail conformance archives (point layout, 3 spectra) + imaging fixtures with embedded TIFF members; each carries an `expected.json`.
- **`smoke_test.py`** — runs fixtures then the corpus.

**How a validation runs:** `run()` opens the `Archive`, resolves a `Profile`, then for each rule calls `PRIMITIVES[rule.primitive](archive, rule, report, params)`. Each primitive self-gates (no-ops if its target file/column is absent), so layout-independent rules apply everywhere while point-layout / imaging rules quietly skip where they don't apply.

**Profile resolution** (in `resolve_profile`): `--profile` wins → else the archive's `mzpeak_index.json.metadata.format.version` selects `profiles/mzpeak-<version>/` → else the **latest** known profile is used **with a warning**. Pre-1.0 files have no version field, so the "defaulted to latest" warning is expected on every real file today — it is not a defect.

**Findings:** messages are "speaking" (example offending value + row, the actual columns found, role names). Identical messages collate to `(xN)`; per-rule volume caps at `MAX_PER_RULE = 25`, then one "+N suppressed" summary line (prevents log floods).

## Amending rules (the common case — no code change)

Each `rules/*.rules.json` opens with an `about` block (purpose, what gates it, a per-primitive **param contract**, and a `how_to_amend` note); every rule has a `doc` field. **These `about`/`doc` fields are documentation only — the engine ignores them**, reading just `id`, `primitive`, `severity` (`error|warning`), `recovery`, and `params`.

To add/adjust a check: copy a rule and edit its `params`. To change *which columns/types* are required, edit the relevant `schema/tables/*.columns.json` — **not** the rule. To accept a new CV code, add its OBO as a `cv` artifact in `profile.json`.

**After changing a profile, regenerate its reference page** (it is derived from the bundle, so it can't drift): `python docs/gen_profile_page.py mzpeak_validator/profiles/<id> > docs/profiles/<id>.md`. The page (`docs/profiles/<id>.md`) tabulates every rule, the primitive param contracts, and the column schemas — a good first thing to read when learning the rule set.

**Recovery classes** (each rule declares one; see design doc §4): lossless & auto — `rebuild`, `recompute`, `rederive`, `reorder_pair`; lossy & opt-in — `normalize`, `drop`; or `none`.

## Adding a primitive (catalog change)

1. Write `p_<name>(ar, rule, rep, params)` in `mzpeak_validator/core.py` and register it in `PRIMITIVES`.
2. If it does heavy full-column / full-member I/O, add its name to `DATA_SCAN` so `--quick` skips it.
3. Bump `CATALOG_VERSION` **and** the profile's `rule_primitive_catalog` together (engine warns on mismatch). Currently both are **`1.10`** (1.1 image primitives; 1.2 list types + footer `count_column`; 1.3 `grouped_monotonic` gated on declared `sorting_rank`; 1.4 `json_schema` + `grouped_count_equals`, profile re-pinned to the current spec `HUPO-PSI/mzPeak-specification`; 1.5 `cv_list` cv-CURIE resolution; 1.6 `cv_list` version warning fires only when the file declares a CV **newer** than the pinned snapshot — "update the validator's CVs" — not on any version difference; 1.7 `parquet_row_group_health` — advisory perf warning when a chunked data facet sits in one monolithic row group; 1.8 `cv_mapping` — PSI CvMapping term-placement on the packed facets (MUST/SHOULD + AND/OR/XOR + `allow_children` + cardinality), consuming the spec's bundled `cv_mapping/table_rules.json`; advisory severity in Phase 1; plus a finding-level `fix` tip field; 1.9 `cv_mapping_json` — the same CvMapping checks over the **JSON index metadata** params (the spec's `semantic_rules.json`: file_description / instrument-config components / software / data_processing), resolving `scope_path`/`cv_element_path` over `mzpeak_index.json` `metadata`; 1.10 Phase 3 chunk layout — `chunk_columns`, `chunk_bounds` (per-group `start<=end` + non-overlapping ascending chunks; advisory), `aux_arrays` count — + Phase 6 container MUSTs `zip_stored` / `column_order` + Phase 4 chromatogram entity rules).
4. Add a fixture in `make_fixtures.py` and keep `smoke_test.py` green. For warning-level rules, set `expected.json`'s `warn_rule` (the harness asserts warnings separately from the FAIL-verdict error rules).

The current 26 primitives: `index_files_present, columns_present, data_kind_facet, footer_count_equals_rows, column_predicate (ge/gt/le/lt/finite), dtype_role, grouped_monotonic, foreign_key, index_contiguous, cv_inflection, cv_list_consistency, count_sum_equals_rows, imaging_coordinates` + the v1.1 **raw-member image** primitives `member_exists, blob_hash, tiff_magic` + v1.4 `json_schema` (validate the index / footer metadata blobs against the bundled `schema/json/*.json` draft-07 schemas) and `grouped_count_equals` (per-spectrum count integrity) + v1.7 `parquet_row_group_health` (advisory, warning-only: a chunked `spectra_data`/`chromatograms_data` facet in a single >64 MB Parquet row group reads poorly for random single-spectrum access; footer-only so it runs under `--quick`; gated on the `chunk` facet) + v1.8 `cv_mapping` (CV term-PLACEMENT via the PSI CvMapping model over the packed facets — consumes the spec's bundled `cv_mapping/table_rules.json`; checks required terms per facet with AND/OR/XOR combination, `allow_children` via the OBO `is_a` graph, and cardinality; Phase-1 maps `/spectrum` + `/spectrum/precursors[]/selected_ions[]` at warning severity) + v1.9 `cv_mapping_json` (the same CvMapping checks over the **JSON index metadata** params — the spec's `semantic_rules.json`: file_description.contents, instrument-config components incl. ionization/analyzer/detector type, software, data_processing; resolves `scope_path`/`cv_element_path` over `mzpeak_index.json` `metadata`, advisory severity) + v1.10 the **layout** primitives `chunk_columns` (a chunked facet declaring `${axis}_chunk_start` must carry its companion columns) and `chunk_bounds` (per-group `start<=end` + non-overlapping ascending chunks; advisory, DATA_SCAN) and `aux_arrays` (`number_of_auxiliary_arrays` == list length; DATA_SCAN), plus the **container** primitives `zip_stored` (ZIP members stored uncompressed) and `column_order` (entity-index/FK column first in its facet; advisory). Bundled JSON schemas live under `profiles/mzpeak-0.9/schema/json/`. Full-scope roadmap: [docs/roadmap-full-conformance.md](docs/roadmap-full-conformance.md).

## Hard-won facts about real mzPeak (don't re-learn these)

Verified against the reference `.mzpeak` files and the converted corpus.

- **Archive** = ZIP (or dir) of Parquet + `mzpeak_index.json` = `{files:[{name,entity_type,data_kind}], metadata:{}}`. `metadata` is open/extensible (imaging archives add a `metadata.imaging` block).
- **`spectra_metadata.parquet`** = packed parallel facets as *top-level struct columns* `spectrum`/`scan`/`precursor`/`selected_ion`. Inside them, CV columns are inflected `${CV}_${ACC}_${name}` (+ optional `_unit_${UCV}_${UACC}`). `scan` emits **`ion_mobility_value`** though the spec doc says `ion_mobility` — a real mismatch (PR #19).
- **`spectra_data`/`spectra_peaks.parquet`** = a **`point`** struct (`spectrum_index`, `mz`, `intensity`) **OR** a **`chunk`** struct (numpress/chunked — no `point.intensity`). v0.9 deep-checks the point layout only; chunk/numpress pass layout-independent rules and skip the rest.
- **Packed parallel-facet layout ⇒ rows ≠ spectra.** `spectra_metadata` is as long as its *longest* facet. For PASEF/TIMS (many precursors per MS2 spectrum) the `precursor`/`selected_ion` facets inflate the row count far past the spectrum count, with `spectrum`/`scan` null on the extra rows (e.g. `bruker-timstof-pro`: 278942 rows, **44296 spectra**). The footer `spectrum_count` (44296) is **correct**; the earlier "TIMS counts frames vs scans" guess was wrong. Rules that are per-spectrum must therefore count **non-null `spectrum.index`**, not rows — `spectrum_count_agreement` uses `count_column`, `scan_source_index_fk` sets `allow_null`, `index_contiguous` ignores null padding.
- **Null-marking is legitimate.** `mz` and `number_of_data_points` may carry real Arrow nulls (sparse reconstruction; centroid spectra have null counts). The validator treats **nulls as OK** and flags only genuine **NaN/inf VALUES** (`mz_finite_data`). Do not "fix" a rule to reject nulls.
- **dtype widths (HUPO-PSI #11) — now accepted.** L1-faithful imzML conversion preserves the *source* binary types (32-bit m/z, 64-bit intensity). `spectra_data`/`spectra_peaks.columns.json` therefore declare `mz:[double,float]`, `intensity:[float,double]` (a column `type` may be a list), and the `*_dtype_data` rules stay width-agnostic (the hard guarantee is "float, not int"). Narrow the list if a single width is ever required.
- **m/z order is a *declared* property (`sorting_rank`).** The spec only asserts ascending m/z when the array index gives the column a non-null `sorting_rank` (schema/array_index.json). So `grouped_monotonic` is **gated**: it enforces only when `point.mz` declares itself sorted, and skips (info finding) when declared unsorted. A file that declares `sorting_rank:0` but isn't sorted still FAILs (true mislabel). `declared_sorted()` matches by **path** (not `array_type`, to avoid decoy suppression) and treats only a numeric rank as sorted.
- **Untrusted input is contained.** Archive member names come from the index, so `Archive._contained()` refuses absolute/`..`/escape paths (no arbitrary host-file reads via `archive_path` or `files[].name`), and `__init__` refuses high-inflation ZIPs (zip-bomb; mzPeak members must be stored uncompressed anyway). Don't reintroduce a raw `self.root / name`.

## Conventions & gotchas

- **Keep `smoke_test.py` green** before committing; it is the cross-language verdict gate.
- **Commit/push only when asked.** `gh` is authenticated as `okohlbacher`; default branch `main`.
- **PUSH ALLOWLIST — hard rule.** The ONLY remote you may `git push` to is **`github.com/okohlbacher/mzPeakValidator`**. **NEVER** push to any other remote (e.g. the sibling `okohlbacher/mzML2mzPeak`, or any fork/upstream) unless the user *explicitly and interactively authorizes that specific push in the moment* — and even then, **warn first** and get confirmation before pushing. A generic "commit and push" applies to **this repo only**; for any other repo, stop and ask. Local commits in another repo may be fine, but the push is gated.
- Environment: macOS, anaconda **Python 3.7.4**, **pyarrow 12.0.1**, numpy present, pandas 0.25.1 (old → a harmless `UserWarning` on import; ignore).
- The example `.mzpeak` corpus is **git-ignored** and lives at `~/Claude/mzPeak/data/` (the authoritative corpus root; only files under this path are validated). `smoke_test.py` and `validate_everything.py` both default to this root. A fresh clone runs all fixtures self-contained but finds no corpus unless the data directory is present or `MZPEAK_CORPUS` is set.

## Broader context — the sibling `~/Claude/imzML2mzPeak`

This validator was extracted from a larger all-Rust effort that converts imzML → imaging mzPeak and hosts the design/spec work. Most useful there:

- `docs/mzpeak-validation-design.md` (mirrored here as `docs/validation-design.md`) — the validation design.
- `docs/mzpeak-spec-conformance-issues.md` — a 39-issue spec-vs-implementation review (source of many rule ideas).
- `docs/mzpeak-imaging-spec-suggestions.md` — V2 imaging spec proposal (`cv_list`, `scan_settings`, `pixel` key, grid encoding, **optical images as `images/image_NNNN.tiff` ZIP members** described in `metadata.imaging.images[]`). This grounds the v1.1 image primitives.
- `data/{mzml-examples,imzml-examples}/` + `data/mzpeak/` — the example corpus (git-ignored).
- Obsidian knowledge vault at `imzML2mzPeak/knowledge/` (local-only).

**Relevant upstream issues (HUPO-PSI/mzPeak):** #17 versioning/`format.version` (this validator reads it), #18 `cv_list`, PR #19 `ion_mobility`→`ion_mobility_value`, #11 binary array data types, #12 shared grid, #14 simplify spectra_metadata.

## Roadmap / open items (prioritised)

1. **Chunk/numpress layout validation** — v0.9 deep-checks point layout only.
2. **Per-spectrum point-count matching** — stronger than `sum(...)==rows` (catches a null-count-but-real-points spectrum).
3. **Auto-repair** — designed (design doc §4) but not implemented: `repair --safe` applies the lossless classes and emits a new archive + change log.
4. **Profile content-addressing** — a `--seal` step to fill/verify the `null` `sha256` fields in `profile.json` (will hash the `about`/`doc` bytes too — correct, docs travel with the profile).
5. **File upstream issues** — the footer-count inconsistency (TIMS gives a clean reproducer).
6. **Rust reference port** — reuse the JSON profile verbatim; re-implement only the ~20 primitives.
7. When mzPeak gains a real `version` field (#17), files self-select their profile; until then profiles are keyed to the spec commit.
