# mzPeak validation — design (language-independent)

**Status:** draft · **Date:** 2026-06-05
**Scope:** a portable, version-pinned conformance model for mzPeak, defined so any implementation (Rust, Python, C++, JS) validates — and recovers — identically. Companion: vault notes `mzML validation`, `mzML validation - gaps and limits`, `mzPeak validator (plan)`.

**Principle (lesson of mzML):** mzML split a permissive schema from an optional, drift-prone, rarely-run validator. mzPeak instead ships **everything the validator needs pinned with each spec version**, defines rules as **data, not code**, makes the strong checks **mandatory**, and — where a file is broken but salvageable — supports **explicit, recorded recovery** instead of mzML's silent reader-side repairs.

---

## 1. Versioned validation profile (core idea)

One content-addressed bundle per mzPeak version contains all inputs; profiles **compose** (base + imaging extension, which may tighten but not loosen):

```
profiles/<id>/
  profile.json    # versions + every artifact's sha256 + required rule-catalog version + extends
  schema/         # JSON Schema (footer/index) + JSON column schemas (Parquet facets)
  cv/             # pinned OBO snapshots (psi-ms, imagingMS, uo)
  rules/          # declarative rule instances (structural, cv-mapping, numeric, integrity, imaging)
  fixtures/       # pass/** and fail/** (each fail names the rule id it must trip) — the conformance corpus
```

A file selects its profile from a declared `mzpeak_version` + its `cv_list`; pre-1.0 (no version tag yet) profiles are keyed to the spec commit SHA. Term *resolvability* is checked against the file's declared CV; term *placement* against the profile's rules. No network at validate time.

## 2. Conformance axes & severity

Conformance is several **independent axes**, each reported separately: `well-formed · schema · numeric · index · cv · integrity · imaging · lossless(L0/L1/L2)`.

Two non-gameable tiers: **error** (structural / schema-type / numeric / index / integrity / required-CV — hard, never demotable) and **warning** (SHOULD-level, CV completeness). A profile may raise warning→error, never the reverse.

## 3. Rule model (data, not code)

Rules are declarative **instances** of a small, separately-versioned **primitive catalog** (the cross-language contract). Implementations implement the catalog; profiles ship JSON. Addressing is columnar (`{file, facet, column}` / footer JSON-pointer), not XPath.

Catalog v1 (illustrative): `present`, `dtype_role`, `column_predicate`, `grouped_monotonic`, `count_equals`, `foreign_key`, `index_resolves`, `cardinality`, `term_resolvable`, `term_allowed_at`, `unit_in`, `content_hash`, `crossfield` (a JSONLogic expression — the only escape hatch). Example:

```json
{ "id":"mz_monotonic", "primitive":"grouped_monotonic", "severity":"error",
  "params":{ "file":"spectra_data", "group":"spectrum_index", "column":"mz", "direction":"nondecreasing" },
  "recovery":"reorder_pair" }
```

CV-mapping rules reuse PSI `CvMapping` *semantics* (MUST/SHOULD/MAY, `allow_children`, combination logic, cardinality scope) over columnar addresses — not its XML/XPath.

## 4. Auto-repair / recovery (first-class)

Validation does **not** stop at the first error: it runs to completion, and every finding carries a **recovery classification** so a paired repair mode can fix what is safely fixable. The governing rule — learned directly from mzML, where readers silently rebuilt bad indexes and tolerated wrong checksums — is: **recover generously, but never silently; record every change.**

**Recovery classes** (each rule declares one):

| Class | Meaning | Auto-applied? | Examples |
|---|---|---|---|
| `rebuild` | reconstruct derived structure from the authoritative data | yes (lossless) | rebuild `array_index` / page offsets / row maps; rebuild `pixel`↔`spectrum` map |
| `recompute` | recompute a recorded digest/aggregate | yes (lossless) | per-column/page `content_hash`; index offsets; `mz_range` |
| `rederive` | re-derive a missing/wrong derivable value | yes (lossless) | `number_of_data_points`/`number_of_peaks`; `pixel_count: observed_max`; relabel a dtype tag to the actual physical type |
| `reorder_pair` | re-sort an axis that MUST be sorted, moving its parallel arrays together | yes (lossless — pairing preserved) | unsorted m/z + parallel intensity |
| `normalize` | alter values to satisfy a constraint | **opt-in only** (lossy) | clamp negative intensity to 0 |
| `drop` | remove an irreparable record | **opt-in only** (lossy) | a spectrum whose binary is truncated |
| `none` | not auto-recoverable | no → hard fail | corrupt/truncated archive; FK with no resolvable source |

**Modes:**
- `validate` — report only; nothing changes.
- `repair --safe` (default repair) — apply only **lossless** classes (`rebuild`/`recompute`/`rederive`/`reorder_pair`), emit a **new** archive plus a change log; the spectral data is provably unchanged (an L1 bit-for-bit check gates it).
- `repair --aggressive` — also apply `normalize`/`drop`, each requiring explicit opt-in.

**Every repair is recorded** as a `data_processing` step in the output archive (CV-described) **and** itemized in the report → auditable and reversible-in-intent. Repairs never touch the input in place. Reader-side: the reference reader may recover *in memory* to keep reading a defective file (e.g. rebuild a bad index), but it must surface the defect in the report rather than hide it.

Lossless repairs close most of the worst mzML failure modes outright (bad/absent index, wrong checksum, missing derivable counts, dtype-label mismatch, unsorted axis); the lossy ones stay opt-in because they alter the science.

## 5. Which formats

| Artifact | Recommended | Why |
|---|---|---|
| Manifest, schemas, rules, report | **JSON** (content-addressed) | one serialization → uniform hashing/diffing/tooling |
| Footer/index schema | **JSON Schema 2020-12** | mzPeak already uses it |
| Parquet column schema | small **JSON** column spec | facets are nested; readable, fits |
| CV snapshots | **OBO** (pinned + sha256) | canonical, offline (no live OLS) |
| CV-mapping rules | **JSON**, PSI `CvMapping` *semantics* | proven semantics; drop XML/XPath (don't fit columns) |
| Numeric/cross-field rules | **JSON** primitive catalog + **JSONLogic** | declarative, portable, no embedded code |
| Authoring | **YAML** → compiled to normative JSON | ergonomic; JSON stays the hashed artifact |
| Report | **JSON**, optional **SARIF** projection | SARIF = standard tool-findings format (CI/IDE) |

(Considered and rejected: PSI CvMapping XML — XPath assumes an XML tree; SHACL/ShEx — RDF-only; CUE/Rego — niche/language-tied; embedded Lua/JS — not portable/safe.)

## 6. Gaps & open questions

1. **No `mzpeak_version` field yet** — the model needs one in the footer (pre-1.0: key profiles to the spec commit). Prerequisite spec change, paired with `cv_list`.
2. **Three-way versioning** (file→profile→catalog→validator) — more moving parts than mzML's single mapping file, but it's what makes cross-language verdicts deterministic; all of it is stamped in the report.
3. **`metadata` vs `deep` modes** — footer-only cheap checks vs full-column scans (monotonicity, hashes); same split applies to repair cost.
4. **L1 roundtrip is two-input** — it compares against the source imzML, so it's an acceptance mode, not single-file validation; it also *gates* `repair --safe`.
5. **Lossy repair provenance** must be machine-readable and standardized, or "repaired" files become untrustworthy — define the `data_processing` CV terms for each repair action.
6. **Catalog ownership** — for it to be *the* mzPeak validator (not ours), the primitive catalog + repair-action vocabulary should be a HUPO-PSI artifact, proposed upstream.

## 7. Ties to the project
Implements the vault `mzPeak validator (plan)`; the schema layer operationalizes `docs/mzpeak-spec-conformance-issues.md` (Group A); the CV layer uses the OBOs under `knowledge/cv/obo/`; the L1 mode is the lossless contract from `docs/mzpeak-imaging-spec-suggestions.md`, tested on `docs/imzml-examples.md` data (esp. PXD001283).
