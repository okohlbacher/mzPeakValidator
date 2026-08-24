# Handoff → mzPeakValidator: three archives that should FAIL but PASS

**Date:** 2026-08-24
**From:** converter/corpus agent (`mzPeakConverter`, HEAD `b9c4602`)
**Validator under test:** 0.9.17 (source tree, not the 0.9.1 wheel in `dist/`)
**Spec reference:** HUPO-PSI/mzPeak-specification @ `8309056`

Short version: while debugging the converter I built an archive that violates a **MUST** and is
internally contradictory to the point that **100% of its signal is unreachable**. The validator
returns `PASS (0 errors, 0 warnings)`. Two rules would have caught it. A repro fixture is included.

Separately: two bundled schemas had drifted from the spec. **I already fixed those** — commit
`bbfd74b` in this repo, uncommitted-to-remote, no version bump (releasing is your call).

---

## 1. Missing MUST: `spectrum_representation` may be null (HIGH)

`schema/table_rules.json` → `spectrum_must` is `requirement_level: MUST`, combination logic `AND`,
over two terms:

| accession | term | repeatable |
|---|---|---|
| `MS:1000559` | spectrum type | false |
| `MS:1000525` | **spectrum representation** | false |

The included fixture has `spectrum_representation = null` on **600 / 600** spectra. The validator
reports no error.

The converter bug that produced it is fixed (an `Unknown` signal-continuity spectrum used to write
null). But a writer that emits null here is producing non-conformant archives, and right now nothing
tells it so. **This is the single highest-value rule to add.**

## 2. Counts may contradict the facet that actually holds the rows (HIGH)

The spec has readers do read-planning from `number_of_data_points` / `number_of_peaks`
(`docs/schemas/spectra.md:8-17`) — the counts are the authoritative statement of which facet to
read. Nothing checks that they match reality.

The fixture, exactly as shipped:

| | value |
|---|---|
| `number_of_data_points` non-null | **600 / 600** |
| `number_of_peaks` non-null | 0 / 600 |
| `spectra_data.parquet` rows | **0** |
| `spectra_peaks.parquet` rows | **1,044** |

Every spectrum says "I have profile points, read `spectra_data`". `spectra_data` is empty. The
signal is in `spectra_peaks`, which the counts say is empty. A conforming reader gets **nothing**.

Measured end-to-end through the converter's own reader: source mzML **17,965 points → 0** on
round-trip. Total silent data loss, in an archive the validator calls clean.

Proposed rule, cheap and purely structural — no CV knowledge needed:

- `sum(number_of_data_points)` > 0 **⟹** `spectra_data.parquet` has > 0 rows
- `sum(number_of_peaks)` > 0 **⟹** `spectra_peaks.parquet` has > 0 rows
- and the reverse: a facet with rows whose corresponding count column is all-null

A per-spectrum version (row-level counts vs. rows present per `spectrum_index`) would be stronger
but the aggregate form already catches this class outright.

## 3. `chromatogram_type` may be null (MEDIUM)

Same fixture, `chromatograms_metadata.parquet`: 1 row, `id = ""`, `chromatogram_type = null`.

This is the converter's deliberate "no chromatograms" placeholder, so it is arguably legitimate —
but it is worth a decision rather than silence, because it **crashed a downstream reader**: the
converter's own chromatogram visitor unwrapped the null and aborted the process
(`Option::unwrap` on `None`), which meant every Waters MRM archive died on export. Fixed on our
side; flagging in case the spec wants either an empty `chromatograms_metadata` or a required type.

## 4. The report does not say what it checked (MEDIUM, process)

`profiles/mzpeak-0.9/rules/*.json` defines **82 rules** across nine axes. The JSON report contains
only `findings` — for a clean archive that is 10 `archive_summary` INFO entries and nothing else.
There is no per-rule pass/skip list, so:

- `PASS (0 errors, 0 warnings)` cannot be distinguished from "the rules did not run"
- at minimum the 4 imaging rules are inapplicable to non-imaging archives, and callers can't tell
- when I updated the two schemas, I could only confirm they were live by deliberately corrupting an
  archive (below) — there was no way to read it off a normal run

A `summary.rules_evaluated` / `rules_skipped` count, or a `--verbose` per-rule listing, would make a
PASS mean what people already read it to mean. I'd treat this as a prerequisite for anyone citing
validator output as evidence.

**How I verified enforcement, in case it's a useful smoke test:** copy an archive, set
`metadata.version` to `"not-a-semver"`, re-validate. Correctly yields
`FAIL (1 errors) — index_schema_valid :metadata/version`. That negative control is the only reason I
can assert the updated schemas are actually in play.

## 5. Schema drift — already fixed here (`bbfd74b`)

Of the twelve schemas in `profiles/mzpeak-0.9/schema/json/`, ten matched the spec byte-for-byte;
two did not, so the validator was not enforcing current spec:

- **`array_index.json`** — the spec now **requires `entries`**, not just `prefix`, and tightens a
  nullable field. A real constraint, not a comment change.
- **`mzpeak_index.json`** — adds `scans` / `precursors` / `selected_ions` / `products` to the
  `data_kind` controlled values, extends recognised param names (`collision energy`,
  `scan window lower limit`), and uses the spec's named-group semver pattern for `metadata.version`.

`$ref` resolution is unaffected: `core.py` already maps the spec's `raw.githubusercontent.com` URLs
onto the local bundle, so validation stays offline.

Regression after the swap: **18 archives — 7 vendors, both peak-facet layouts, both chunk encodings,
dual and single representation — all PASS, 0 errors, 0 warnings.**

### Loose end

`profiles/mzpeak-0.9/schema/mzpeak_index.schema.json` (a re-authored draft-2020-12 copy) sits
*outside* `schema/json/` and is referenced by no code — the engine reads `schema/json/`. Your
`CLAUDE.md:37` documents it as part of the layout, so I left it alone rather than delete a file in
your repo, but it is a trap for the next person who greps for "the index schema" and edits the wrong
one.

---

## Repro fixtures

Both are small, self-contained, `ZIP_STORED` mzPeak archives built from
`pwiz-examples/Waters/Waters/Reader_Waters_Test.data/HDMRM_Short_noLM.mzML` with the
`MS:1000127`/`MS:1000128` continuity cvParams stripped (600 spectra):

| file | what it is | current verdict | should be |
|---|---|---|---|
| `fixtures/unknown-continuity-BAD.mzpeak` | null representation + counts/facet contradiction | **PASS** | **FAIL** (issues 1 and 2) |
| `fixtures/unknown-continuity-FIXED.mzpeak` | same input, converter fixed | PASS | PASS |

```bash
PYTHONPATH=$HOME/Claude/mzPeakValidator python3 -m mzpeak_validator \
  $HOME/Claude/mzPeakValidator/.planning/handoffs/fixtures/unknown-continuity-BAD.mzpeak
```

The FIXED one is the control: same source, same converter, same shape, differing only in that
`spectrum_representation` is `MS:1000128` and the 1,044 rows live in `spectra_data` where the counts
say they are. Any new rule must pass that one while failing the BAD one.

## Priority

1. **Issue 1** — a MUST term may be absent and nothing says so. Smallest rule, biggest correctness win.
2. **Issue 2** — counts contradicting facets is *silent total data loss* that survives validation.
3. **Issue 4** — without coverage output, a PASS is not evidence.
4. Issue 3 — needs a spec decision more than validator work.

Happy to take any of these on if you'd rather I sent a PR than a report — say which.
