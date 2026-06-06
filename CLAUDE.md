# CLAUDE.md — mzPeakValidator

A first, **language-independent-by-design** validator for the **mzPeak** mass-spectrometry
file format (HUPO-PSI's Parquet-in-ZIP successor to mzML). Validation is driven by a
versioned **profile** (JSON Schemas + pinned CV OBO snapshots + declarative rules); a small
Python engine implements a **rule-primitive catalog**. Rules are *data*, so any language can
reproduce identical verdicts.

- GitHub: `okohlbacher/mzPeakValidator` (public). User-facing intro: [README.md](README.md). Full design: [docs/validation-design.md](docs/validation-design.md).
- mzPeak is pre-1.0 WIP with no version tag; this profile is keyed to spec commit `d1aaaf84595202e2e7f622c576c1d6ba9154e379`.
- The Rust reference implementation lives on disk at `~/.cargo/git/checkouts/mzpeak-cd0ccbb7d90f04e9/d1aaaf8/` (src/, doc/index.md, schema/, example `.mzpeak` files).

## Commands

```bash
pip install -r requirements.txt                                   # pyarrow, numpy
python mzpeak_validator.py <archive.mzpeak|dir/> [--json out.json] [--log findings.log] [--quick] [--profile DIR]
python smoke_test.py                                              # MUST stay green before any commit
MZPEAK_CORPUS=/dir/of/mzpeak python smoke_test.py                 # point the real-file corpus elsewhere
python make_fixtures.py [out_dir]                                 # materialise fixtures to inspect them
```

- Exit codes: `0` no errors, `1` ≥1 error-level finding, `2` engine failure.
- `--quick` skips full-column data scans (the `DATA_SCAN` primitives); cheap footer/metadata checks still run. The smoke test auto-uses `--quick` for corpus files >50 MB.
- `--json FILE` writes the full JSON report; `--log FILE` writes the human-readable findings (errors/warnings/info), byte-identical to console output.
- `smoke_test.py` is the regression gate: 15 fixtures (10 fail + 5 pass, incl. 4 imaging) each must reach their expected verdict and trip the named rule, plus it validates whatever real `.mzpeak` corpus it finds.

## Architecture

- **`mzpeak_validator.py`** (~560 lines) — the engine: `Archive` (opens a `.mzpeak` ZIP or unpacked dir; exposes Parquet schemas/columns *and* raw ZIP members), `Profile` (loads manifest + rules + column schemas + CV snapshots), `Report` (collates findings), the `PRIMITIVES` dict (15 primitives), and `run()`/`main()`.
- **`profiles/mzpeak-0.9/`** — the profile bundle:
  - `profile.json` — manifest: spec/commit, `rule_primitive_catalog` version, and `artifacts[]` (CVs, schemas, rule files). `sha256` fields are `null` until a future `--seal` step fills them.
  - `cv/` — pinned OBO snapshots: `psi-ms.obo.gz`, `imagingMS.obo`, `uo.obo`.
  - `schema/` — `mzpeak_index.schema.json` + `tables/*.columns.json` (per-table column specs: which facets/columns are required and their expected logical types).
  - `rules/` — `{structural,cv,numeric,imaging}.rules.json`: the declarative rule instances.
- **`make_fixtures.py`** — builds tiny pass/fail conformance archives (point layout, 3 spectra) + imaging fixtures with embedded TIFF members; each carries an `expected.json`.
- **`smoke_test.py`** — runs fixtures then the corpus.

**How a validation runs:** `run()` opens the `Archive`, resolves a `Profile`, then for each rule calls `PRIMITIVES[rule.primitive](archive, rule, report, params)`. Each primitive self-gates (no-ops if its target file/column is absent), so layout-independent rules apply everywhere while point-layout / imaging rules quietly skip where they don't apply.

**Profile resolution** (in `resolve_profile`): `--profile` wins → else the archive's `mzpeak_index.json.metadata.format.version` selects `profiles/mzpeak-<version>/` → else the **latest** known profile is used **with a warning**. Pre-1.0 files have no version field, so the "defaulted to latest" warning is expected on every real file today — it is not a defect.

**Findings:** messages are "speaking" (example offending value + row, the actual columns found, role names). Identical messages collate to `(xN)`; per-rule volume caps at `MAX_PER_RULE = 25`, then one "+N suppressed" summary line (prevents log floods).

## Amending rules (the common case — no code change)

Each `rules/*.rules.json` opens with an `about` block (purpose, what gates it, a per-primitive **param contract**, and a `how_to_amend` note); every rule has a `doc` field. **These `about`/`doc` fields are documentation only — the engine ignores them**, reading just `id`, `primitive`, `severity` (`error|warning`), `recovery`, and `params`.

To add/adjust a check: copy a rule and edit its `params`. To change *which columns/types* are required, edit the relevant `schema/tables/*.columns.json` — **not** the rule. To accept a new CV code, add its OBO as a `cv` artifact in `profile.json`.

**Recovery classes** (each rule declares one; see design doc §4): lossless & auto — `rebuild`, `recompute`, `rederive`, `reorder_pair`; lossy & opt-in — `normalize`, `drop`; or `none`.

## Adding a primitive (catalog change)

1. Write `p_<name>(ar, rule, rep, params)` in `mzpeak_validator.py` and register it in `PRIMITIVES`.
2. If it does heavy full-column / full-member I/O, add its name to `DATA_SCAN` so `--quick` skips it.
3. Bump `CATALOG_VERSION` **and** the profile's `rule_primitive_catalog` together (engine warns on mismatch). Currently both are **`1.1`**.
4. Add a fixture in `make_fixtures.py` and keep `smoke_test.py` green. For warning-level rules, set `expected.json`'s `warn_rule` (the harness asserts warnings separately from the FAIL-verdict error rules).

The current 15 primitives: `index_files_present, columns_present, data_kind_facet, footer_count_equals_rows, column_predicate (ge/gt/le/lt/finite), dtype_role, grouped_monotonic, foreign_key, index_contiguous, cv_inflection, count_sum_equals_rows, imaging_coordinates` + the v1.1 **raw-member image** primitives `member_exists, blob_hash, tiff_magic` (operate on archive members, not Parquet).

## Hard-won facts about real mzPeak (don't re-learn these)

Verified against the reference `.mzpeak` files and the converted corpus.

- **Archive** = ZIP (or dir) of Parquet + `mzpeak_index.json` = `{files:[{name,entity_type,data_kind}], metadata:{}}`. `metadata` is open/extensible (imaging archives add a `metadata.imaging` block).
- **`spectra_metadata.parquet`** = packed parallel facets as *top-level struct columns* `spectrum`/`scan`/`precursor`/`selected_ion`. Inside them, CV columns are inflected `${CV}_${ACC}_${name}` (+ optional `_unit_${UCV}_${UACC}`). `scan` emits **`ion_mobility_value`** though the spec doc says `ion_mobility` — a real mismatch (PR #19).
- **`spectra_data`/`spectra_peaks.parquet`** = a **`point`** struct (`spectrum_index`, `mz`, `intensity`) **OR** a **`chunk`** struct (numpress/chunked — no `point.intensity`). v0.9 deep-checks the point layout only; chunk/numpress pass layout-independent rules and skip the rest.
- **Footer counts are UNRELIABLE in the reference writer.** Only **`spectrum_count` on `spectra_metadata`** is trusted — and even that disagrees for **ion-mobility (TIMS)** files (footer counts frames, rows are expanded scans; e.g. `bruker-timstof-pro` 44296 vs 278942). That is why per-point integrity uses `sum(number_of_data_points)==rows`, not a footer. Candidate upstream issue (no draft yet).
- **Null-marking is legitimate.** `mz` and `number_of_data_points` may carry real Arrow nulls (sparse reconstruction; centroid spectra have null counts). The validator treats **nulls as OK** and flags only genuine **NaN/inf VALUES** (`mz_finite_data`). Do not "fix" a rule to reject nulls.
- **dtype tension (HUPO-PSI #11).** `spectra_data.columns.json` pins `point.mz=double`, `point.intensity=float`. But an L1-faithful imzML conversion preserves the *source* binary types — 32-bit m/z or 64-bit intensity occur in real imzML — so several converted files fail `columns_spectra_data`. The numeric `*_dtype_data` rules are deliberately *permissive* (`double|float`) so the hard "float-not-int" check stays separate from the width debate. To accept 32-bit m/z, relax the type in the column schema.

## Conventions & gotchas

- **Keep `smoke_test.py` green** before committing; it is the cross-language verdict gate.
- **Commit/push only when asked.** `gh` is authenticated as `okohlbacher`; default branch `main`.
- Environment: macOS, anaconda **Python 3.7.4**, **pyarrow 12.0.1**, numpy present, pandas 0.25.1 (old → a harmless `UserWarning` on import; ignore).
- The example `.mzpeak` corpus is **git-ignored** (lives in the sibling repo, below). A fresh clone runs all 15 fixtures self-contained but finds no corpus unless `MZPEAK_CORPUS` is set.

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
6. **Rust reference port** — reuse the JSON profile verbatim; re-implement only the ~15 primitives.
7. When mzPeak gains a real `version` field (#17), files self-select their profile; until then profiles are keyed to the spec commit.
