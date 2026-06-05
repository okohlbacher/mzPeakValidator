# mzPeakValidator

A first, **language-independent-by-design** validator for the [mzPeak](https://github.com/HUPO-PSI/mzPeak) mass-spectrometry file format.

Validation is driven by a **versioned profile** (JSON Schemas + pinned controlled-vocabulary snapshots + a declarative rule set). A small engine implements the rule-*primitive* catalog; the rules themselves are data, so any language can reproduce the same verdicts. See [`docs/validation-design.md`](docs/validation-design.md).

## Install

```bash
pip install -r requirements.txt        # pyarrow, numpy
```

## Use

```bash
python mzpeak_validator.py <archive.mzpeak | unpacked_dir/> [--json report.json] [--quick]
```

- Exit code `0` = no errors, `1` = at least one error-level finding, `2` = engine failure.
- `--quick` skips full-column data scans (metadata-only mode).
- `--profile DIR` forces a profile; otherwise it is resolved automatically (below).

**Profile selection.** `--profile` wins; else the archive's `mzpeak_index.json` →
`metadata.format.version` selects `profiles/mzpeak-<version>/`; else the **latest
known profile** is used and a warning is emitted.

## Layout

```
mzpeak_validator.py          # the engine (rule-primitive catalog)
make_fixtures.py             # generate tiny pass/fail conformance fixtures
smoke_test.py                # fixtures + a real-.mzpeak corpus (env MZPEAK_CORPUS)
profiles/
  mzpeak-0.9/
    profile.json             # manifest: versions + artifacts + catalog version
    cv/                      # pinned OBO snapshots (psi-ms, imagingMS, uo)
    schema/                  # JSON Schema (index) + JSON column schemas (Parquet facets)
    rules/                   # declarative rules: structural / cv / numeric / imaging
docs/validation-design.md    # the design (profiles, primitive catalog, auto-repair, formats)
```

## What it checks (mzpeak-0.9)

Structural (archive + index ↔ files, `data_kind` ⇒ signal facet, column types), CV
(codes declared & resolvable in the pinned OBOs, inflection well-formed), numeric
(per-spectrum point-count agreement, m/z monotonic & finite, intensity ≥ 0,
dtype-vs-role, FK resolution), and imaging (1-based coordinates). Findings carry an
example offending value/row; identical messages are collated and per-rule volume is
capped so a single rule can't flood the log.

## Test

```bash
python smoke_test.py
# point the real-file corpus elsewhere:
MZPEAK_CORPUS=/path/to/dir_of_mzpeak python smoke_test.py
```

## Status / scope

First cut for spec version **0.9** (pre-1.0, keyed to a spec commit). v0.9 deep-checks
the **point** layout; chunk/numpress layouts pass the layout-independent rules and skip
the rest (a v1 item), as does per-spectrum point-count matching. Auto-repair (`repair
--safe` etc.) is specified in the design doc but not yet implemented.
