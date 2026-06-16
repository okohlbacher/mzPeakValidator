# mzPeakValidator

[![CI](https://github.com/okohlbacher/mzPeakValidator/actions/workflows/ci.yml/badge.svg)](https://github.com/okohlbacher/mzPeakValidator/actions/workflows/ci.yml)

A first, **language-independent-by-design** validator for the [mzPeak](https://github.com/HUPO-PSI/mzPeak) mass-spectrometry file format.

Validation is driven by a **versioned profile** (JSON Schemas + pinned controlled-vocabulary snapshots + a declarative rule set). A small engine implements the rule-*primitive* catalog; the rules themselves are data, so any language can reproduce the same verdicts. See [`docs/validation-design.md`](docs/validation-design.md).

## Install

```bash
pip install git+https://github.com/okohlbacher/mzPeakValidator.git   # from GitHub
# or, from a clone:
pip install .            # regular install
pip install -e .         # editable (development)
```

Dependencies (`pyarrow>=12`, `numpy`, `jsonschema>=3`) are pulled in automatically. The versioned
profile bundle (CV snapshots + CvMapping files + schemas + rules) ships **inside** the package, so a
plain `pip install` is fully self-contained — no separate data download. Installing
provides the `mzpeak-validate` console command.

## Use

```bash
mzpeak-validate <archive.mzpeak | unpacked_dir/> [options]
# equivalently, without the installed console script:
python -m mzpeak_validator <archive.mzpeak | unpacked_dir/> [options]
```

Arguments and options:

| Argument / option | Meaning |
|---|---|
| `<archive>` (required) | a `.mzpeak` ZIP file **or** an unpacked archive directory |
| `--quick` | skip full-column data scans (the heavy `DATA_SCAN` rules); cheap footer/metadata checks still run |
| `--json FILE` | write the full machine-readable JSON report to `FILE` |
| `--log FILE` | write the human-readable findings (the errors/warnings/info lines printed to the console) to `FILE` |
| `--profile DIR` | force a specific profile directory, overriding version resolution |
| `--profiles-dir DIR` | root directory holding the `mzpeak-<version>/` profiles (default: the bundled profiles) |

Exit codes: `0` = no errors, `1` = at least one error-level finding, `2` = engine failure.

Examples:

```bash
mzpeak-validate sample.mzpeak                          # validate, human-readable summary to stdout
mzpeak-validate sample.mzpeak --json report.json       # also write the full JSON report
mzpeak-validate big.mzpeak --quick --log findings.log  # metadata-only, save findings to a file
```

Programmatic use:

```python
from mzpeak_validator import run
report = run("archive.mzpeak")        # -> dict (verdict, summary, findings, ...)
```

**Profile selection.** `--profile` wins; else the archive's `mzpeak_index.json` →
`metadata.format.version` selects the bundled `mzpeak-<version>` profile; else the
**latest known profile** is used and a warning is emitted.

## Layout

```
mzpeak_validator/            # the installable package
  __init__.py                # public API (run, main, ...) + console entry point
  __main__.py                # `python -m mzpeak_validator`
  core.py                    # the engine (rule-primitive catalog)
  profiles/
    mzpeak-0.9/
      profile.json           # manifest: versions + artifacts + catalog version
      cv/                    # pinned OBO snapshots (psi-ms, imagingMS, uo)
      cv_mapping/            # bundled PSI CvMapping files (CV term-placement, from the spec)
      schema/                # JSON Schema (index) + JSON column schemas (Parquet facets)
      rules/                 # declarative rules: structural / cv / numeric / metadata / imaging / perf / semantic
pyproject.toml               # packaging metadata + console script
make_fixtures.py             # (dev) generate tiny pass/fail conformance fixtures
smoke_test.py                # (dev) fixtures + a real-.mzpeak corpus (env MZPEAK_CORPUS)
docs/validation-design.md    # the design (profiles, primitive catalog, auto-repair, formats)
docs/profiles/               # generated per-profile reference pages (checks + rule structure)
docs/gen_profile_page.py     # regenerates a profile reference page from its bundle
```

## What it checks (mzpeak-0.9)

> **Full per-profile reference:** [`docs/profiles/mzpeak-0.9.md`](docs/profiles/mzpeak-0.9.md) —
> every rule (id / primitive / severity / recovery / what it checks), the primitive param
> contracts, and the column schemas. Index of all profiles: [`docs/profiles/`](docs/profiles/README.md).

Across these axes:

- **Structural** — archive + index ↔ files, `data_kind` ⇒ a signal facet, column types and the metadata/index JSON blobs against the bundled JSON Schemas.
- **CV (controlled vocabulary)** — two complementary checks: *resolvability* — every CV code is one the profile pins and every accession resolves in the pinned OBO snapshot; and **term placement (semantic)** — terms appear only where the **PSI CvMapping** model permits, checked per facet for required terms with AND/OR/XOR combination logic, child-term inheritance (`allow_children`, via the OBO `is_a` graph) and cardinality. The placement rules are bundled from the mzPeak spec verbatim (`profiles/*/cv_mapping/`); they are advisory (warning-level) in v0.9 — see [`docs/cv-mapping-design.md`](docs/cv-mapping-design.md).
- **Numeric / integrity** — per-spectrum point-count agreement, m/z monotonic (when the array index declares it sorted) & finite, intensity ≥ 0, dtype-vs-role, foreign-key resolution.
- **Imaging** — 1-based pixel coordinates; required `position_x`/`position_y`; embedded optical images (declared `metadata.imaging.images[]` members exist, their `sha256`/`size_bytes` match the stored bytes, `image/tiff` members carry a TIFF magic number). Image checks are warning-level (optical images are auxiliary).
- **Performance (advisory)** — warning-only physical-layout checks that never fail an archive, e.g. a chunked data facet stored in a single monolithic Parquet row group (poor random single-spectrum access).

Findings carry an example offending value/row and an optional **fix** tip; identical messages are collated and per-rule volume is capped so a single rule can't flood the log.

## Test

```bash
python smoke_test.py
# point the real-file corpus elsewhere:
MZPEAK_CORPUS=/path/to/dir_of_mzpeak python smoke_test.py
```

## Status / scope

First cut for spec version **0.9** (pre-1.0, keyed to a spec commit). v0.9 deep-checks
the **point** layout; chunk/numpress layouts pass the layout-independent rules and skip
the per-point checks (a v1 item). CV term-placement is Phase 1 (the `/spectrum` and
selected-ion facets, at warning severity); the remaining spec scopes and the JSON-metadata
parameter placements are bundled but not yet wired (see [`docs/cv-mapping-design.md`](docs/cv-mapping-design.md) §6).
Auto-repair (`repair --safe` etc.) is specified in the design doc but not yet implemented.
