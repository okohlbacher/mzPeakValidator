# Session handoff — mzPeakValidator (and its mzPeak context)

**Read this first to resume.** Written 2026-06-05. This project (`~/Claude/mzPeakValidator`) is a standalone validator for the **mzPeak** mass-spectrometry file format, extracted from a larger effort in `~/Claude/imzML2mzPeak`. This file dumps the context needed to continue.

---

## 1. The big picture

- **mzPeak** = the HUPO-PSI Parquet-in-ZIP successor to mzML (repo: https://github.com/HUPO-PSI/mzPeak). Unstable WIP, no version tag. We pin to commit **`d1aaaf84595202e2e7f622c576c1d6ba9154e379`**.
- **`~/Claude/imzML2mzPeak`** = an all-Rust converter (imzML → imaging mzPeak) and the home of all the *design/spec* work (conformance review, imaging spec suggestions, issue drafts, an Obsidian knowledge vault, example datasets).
- **`~/Claude/mzPeakValidator`** (this dir) = a first, language-independent-by-design **validator**, born from validation research done in the larger project. It is now its own git repo (initial commit `ce775a0`).
- The mzPeak **reference implementation (Rust)** source is on disk at:
  `/Users/kohlbach/.cargo/git/checkouts/mzpeak-cd0ccbb7d90f04e9/d1aaaf8/` (src/, doc/index.md, schema/, example `.mzpeak` files).

## 2. What this validator is (and its state)

A versioned **validation profile** (JSON Schemas + pinned CV OBO snapshots + a declarative rule set) is run by a small engine that implements a **rule-primitive catalog**. Rules are *data*, so any language can reproduce the same verdicts. Full design: [`docs/validation-design.md`](docs/validation-design.md).

**Layout** (`README.md` has the user-facing version):
```
mzpeak_validator.py     # engine: ~470 lines, 12 primitives, version resolution, collation
make_fixtures.py        # builds tiny pass/fail conformance fixtures (point layout)
smoke_test.py           # fixtures + real-.mzpeak corpus (env MZPEAK_CORPUS)
profiles/mzpeak-0.9/    # profile.json, cv/{psi-ms.obo.gz,imagingMS.obo,uo.obo}, schema/, rules/
docs/validation-design.md
HANDOFF.md (this), README.md, requirements.txt, .gitignore
```

**Run / test:**
```bash
pip install -r requirements.txt                 # pyarrow, numpy
python mzpeak_validator.py <archive.mzpeak|dir/> [--json out.json] [--quick] [--profile DIR]
python smoke_test.py                            # green: 11 fail-fixtures + pass/valid + corpus
MZPEAK_CORPUS=/dir/of/mzpeak python smoke_test.py
```
**Status: green.** Smoke test passes (fixtures trip the right rule; the 4 reference `.mzpeak` files pass with one warning each — the "no version declared → defaulted to latest" notice).

**Profile selection logic** (the resolution the engine does): `--profile` wins → else archive's `mzpeak_index.json.metadata.format.version` → `profiles/mzpeak-<version>/` → else **latest known profile + a warning**.

## 3. The v0.9 rule set (what it actually checks)

~21 rules over the primitive catalog (**catalog v1.1**). Primitives: `index_files_present, data_kind_facet, columns_present, footer_count_equals_rows, column_predicate (ge/gt/le/lt/finite), dtype_role, grouped_monotonic, foreign_key, index_contiguous, cv_inflection, count_sum_equals_rows, imaging_coordinates`, plus the **v1.1 raw-member image primitives** `member_exists, blob_hash, tiff_magic` (operate on archive members, not Parquet).

- **structural**: archive opens; every indexed file exists/opens; a file whose `data_kind` is signal must carry a `point` or `chunk` facet; column names/types match the column schemas.
- **cv**: every inflected `${CV}_${ACC}_…` column's CV code is declared & the accession resolves in the pinned OBO (unknown code = error, unknown accession = warning).
- **numeric**: `spectrum_count` footer == metadata rows; `sum(number_of_data_points) == spectra_data rows` (point layout); m/z monotonic non-decreasing per spectrum; m/z finite (no NaN/inf *values*); intensity ≥ 0; dtype-vs-role (intensity⇒float, m/z⇒double); `point.spectrum_index`/`scan.source_index` FK resolve; spectrum.index 0-based contiguous (warning).
- **imaging** (only if archive is imaging): `IMS_1000050/51` present (X *and* Y independently) and 1-based.
- **imaging — embedded optical images** (catalog v1.1; warning-level per the imaging-spec V2, since optical images are auxiliary and outside the spectral L1 contract): each `metadata.imaging.images[]` entry's `archive_path` member exists (`member_exists`); its bytes match the declared `sha256` + `size_bytes` (`blob_hash`, recovery `recompute`); and an `image/tiff` member starts with a TIFF magic number `II*\0`/`MM\0*` (`tiff_magic`). Grounded in `imzML2mzPeak/docs/mzpeak-imaging-spec-suggestions.md` Edits 7–8 (TIFF-as-ZIP-member, `images/image_NNNN.tiff`). Fixtures: `imaging_with_optical_image` (pass) + `imaging_{missing_image,image_hash_mismatch,image_not_tiff}` (warn). `smoke_test.py`/`make_fixtures.py` gained a `warn_rule` assertion path for warning-level fixtures.

Messages are "speaking" (example offending value + row, the actual columns found, role names). Findings are **collated**: identical messages collapse to `(xN)`; per-rule volume caps at **25** then a single "+N suppressed" summary (prevents log floods).

## 4. Hard-won facts about real mzPeak (don't re-learn these)

Verified against `small.mzpeak`/`has_uv.mzpeak`/`small.chunked.mzpeak`/`small.numpress.mzpeak` in the cargo checkout:

- **Archive** = ZIP or dir of Parquet + `mzpeak_index.json` = `{files:[{name,entity_type,data_kind}], metadata:{}}`. `metadata` is currently empty/open.
- **`spectra_metadata.parquet`** = packed parallel facets as *top-level struct columns* `spectrum`/`scan`/`precursor`/`selected_ion`. Within them, CV columns are inflected `${CV}_${ACC}_${name}` (+ optional `_unit_${UCV}_${UACC}`). `scan` emits **`ion_mobility_value`** (the spec doc says `ion_mobility` — that's a real mismatch; see §6).
- **`spectra_data`/`spectra_peaks.parquet`** = a **`point`** struct (`spectrum_index`,`mz`:double,`intensity`:float32) **OR** a **`chunk`** struct (numpress/chunked layouts — no `point.intensity`). v0.9 deep-checks point layout only; chunk/numpress skip the point rules.
- **Footer counts are UNRELIABLE in the reference writer** — `spectra_data` reports `spectrum_data_point_count=25344` but has **217,710** rows (it copied the *peak* count); `spectra_peaks` reports `spectrum_count=34` vs metadata's 48. Only **`spectrum_count` on `spectra_metadata`** is trustworthy. That's why the data-point check is `sum(number_of_data_points)==rows`, not a footer check. **(Worth filing as an upstream issue — see §7.)**
- **Null-marking**: m/z and `number_of_data_points` *legitimately contain Arrow nulls* (sparse reconstruction; centroid spectra have null `number_of_data_points`). So the validator treats **nulls as legitimate** and only flags genuine **NaN/inf VALUES**. This was the key correction after the adversarial review.

## 5. The adversarial review (already applied)

An independent code-review pass found real bugs; all fixed and covered by regression fixtures:
- **C1 (false PASS):** `grouped_monotonic` only compared adjacent rows → unsorted m/z in non-contiguous spectra slipped through. Fixed with a stable argsort-by-group. Fixture: `interleaved_unsorted_mz`.
- **C2/C3:** NaN/null handling — corrected to the null-marking semantics above (nulls OK; NaN-value flagged by a separate `mz_finite` rule; null counts treated as 0). Fixtures: `nan_mz`.
- **C4:** imaging X/Y presence now checked independently.
- **M1:** added `data_kind_facet` (a signal file must have point/chunk). Fixture: `garbage_data_facet`.
- Minor: FK nulls flagged; `bool` given its own logical type; `_fname` prefers `.parquet`; footer non-numeric guarded.

## 6. Related artifacts in `~/Claude/imzML2mzPeak` (the broader context)

Tracked docs (very relevant if continuing spec/validator work):
- `docs/mzpeak-validation-design.md` — the validation design (copied here as `docs/validation-design.md`).
- `docs/mzpeak-spec-conformance-issues.md` — a 39-issue spec-vs-implementation review (the source of many rule ideas; Group A = schema-vs-emitted-bytes).
- `docs/mzpeak-imaging-spec-suggestions.md` (+ `.codex-review.md`) — V2 proposed spec edits for imaging (cv_list, scan_settings, pixel key, grid encoding, image entity), Codex-reviewed.
- `docs/issue-*.md`, `docs/pr-ion-mobility-naming.{md,diff}` — GitHub issue/PR drafts.
- `docs/imzml-examples.md` + `scripts/fetch-imzml-examples.sh` — how to rebuild the example datasets.
- **Obsidian knowledge vault** at `imzML2mzPeak/knowledge/` (git-ignored, local-only): a `validation/` cluster (`mzML validation`, `mzML validators (tools)`, `mzML validation - gaps and limits`, `mzPeak validator (plan)`), plus ingested CV OBOs + ~260 per-term notes, the whole imaging-MS map. Start at `knowledge/Imaging MS - Map of Content.md`.
- **Example `.mzpeak` corpus** (git-ignored): `data/mzml-examples/` (the 4 reference files — the smoke test's default corpus) and `data/imzml-examples/` (imzML source datasets).

## 7. GitHub state (HUPO-PSI/mzPeak)

- **#17 "Versioning and validation"** — the `metadata.format.version` + `writer` proposal (filed). This validator already reads it.
- **#18 "Declaring CVs for column name inflection"** — the `cv_list` proposal (filed; missing the deep-links we drafted).
- **PR #19** — `ion_mobility` → `ion_mobility_value` doc rename (open, from `okohlbacher` fork, branch `docs/ion-mobility-rename`).
- Related existing: #11 binary array data types, #12 shared grid (continuous mode), #14 simplify spectra_metadata.
- **Not yet filed (drafts exist):** the ion-mobility *issue* (`imzML2mzPeak/docs/issue-ion-mobility-naming.md`), and the **footer-count inconsistency** finding (§4) has no draft yet.

## 8. Open items / next steps (prioritised)

1. **Chunk/numpress layout validation** — v0.9 only deep-checks the point layout; add chunk-aware decoding/rules.
2. **Per-spectrum point-count matching** — stronger than `sum(...)==rows` (catches the reviewer's C3 edge case: a spectrum with null count but real points).
3. **Auto-repair** — designed in `docs/validation-design.md` §4 (lossless `rebuild`/`recompute`/`rederive`/`reorder_pair`; opt-in `normalize`/`drop`; record every repair) but **not implemented**.
4. **Profile content-addressing** — `profile.json` artifact `sha256` fields are `null`; add a `--seal` step that fills + verifies them.
5. **File upstream issues** — the footer-count inconsistency (§4/§7); land or follow up PR #19; file the ion-mobility issue draft.
6. **Eventual Rust reference port** — share types with `mzdata`/`mzpeak_prototyping`, embed the hard checks on-by-default in the reader/writer; the JSON profile is reused verbatim (only re-implement the ~12 primitives).
7. When mzPeak gains a real `version` field (#17), files self-select their profile; until then profiles are keyed to the spec commit.

## 9. Environment / gotchas

- macOS. `python3` is anaconda **3.7**, **pyarrow 12.0.1**, numpy present, pandas 0.25.1 (old → a harmless UserWarning on import; ignore).
- `gh` CLI authenticated as **okohlbacher**; `codex` CLI available (used earlier for an adversarial spec review).
- **`imzML2mzPeak` branch state:** the validator work + its removal live on branch **`validator-mzpeak-0.9`** (NOT merged to `main`). That branch also contains an unrelated commit `6e8247d` (a vendor reader fix) — be deliberate about what lands on `main`.
- This validator was *moved* out of imzML2mzPeak (its `validation/` dir is fully removed there, commit `33fb516`).
