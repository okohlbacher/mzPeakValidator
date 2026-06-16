# T1 design — CV term-placement validation (PSI CvMapping, mzPeak port)

**Status:** Phase 1 implemented (catalog 1.8). **Source of rules:** the **mzPeak-specification repo's own
machine-checkable files** — `schema/cv_mapping_rule.json` (the rule schema), `schema/table_rules.json`
(Parquet-facet CV placement), `schema/semantic_rules.json` (JSON-metadata-param CV placement). We do **not**
invent rules: we bundle the spec's files verbatim and implement a Python evaluator for them.

## 1. The gap this closes

`docs/conformance.md` (mzPeak spec) states: *"CV placement is defined by a machine-checkable mapping-rule
set (PSI CvMappingRule model) — the normative source for which terms are allowed where."* The validator's
existing `cv_inflection` only checks (a) the CV code is one the profile pins and (b) the accession resolves
in the pinned OBO. It does **not** check **placement** (is this term legal in this facet?), **cardinality**
(at most one?), or **combination** (MUST have all/one/exactly-one of a set). The CvMapping model supplies all
three. The mzML validator (`HUPO-PSI/mzML/validator`, `ms-mapping.xml`) is the reference; mzPeak has already
ported it to JSON.

## 2. The spec's rule model (`cv_mapping_rule.json`)

Each `CvMappingRule` has: `id`, `scope_path`, `cv_element_path`, `requirement_level` (MUST/SHOULD/MAY),
`cv_terms_combination_logic` (AND/OR/XOR), and `cv_terms[]`. Each `CvTerm` has `term_accession`,
`cv_identifier_ref`, `use_term` (the term itself is allowed), `allow_children` (descendants allowed),
`is_repeatable` (cardinality), `use_term_name` (match by name not accession — unused by us).

Semantics we implement:
- **MUST** → finding at the engine rule's severity; **SHOULD** → warning; **MAY** → not enforced in Phase 1
  (MAY rules enumerate *permitted* terms; enforcing "term present but matched by no rule" is Phase 2).
- **AND**: every `cv_term` must be satisfied. **OR**: ≥1. **XOR**: exactly 1.
- A `cv_term` is satisfied by an accession `A` iff (`use_term` and `A == term`) or (`allow_children` and `A`
  is a proper is_a-descendant of `term`).
- **Cardinality**: a non-repeatable term matched by >1 column in scope is a violation (e.g. two
  spectrum-representation columns).

## 3. The mzPeak addressing problem (the only real engineering)

The spec's `scope_path`/`cv_element_path` are logical paths over an *element tree* (inherited from mzML's
XML model), e.g. `/spectrum/scan_list/scans[]/parameters[]/accession`. mzPeak stores the same information as
**packed parallel facets** — top-level Parquet struct columns (`spectrum`, `scan`, `precursor`,
`selected_ion`) whose CV params are **inflected into column names** `${CV}_${ACC}_${name}`. So "the set of
CV accessions at a scope" = the accessions parsed out of the column names under that facet.

The evaluator therefore needs a **path → facet map**. Phase-1 mapping (in the engine rule's `path_map`
param, so it is data-driven, not code):

The **`path_map` is the single source of truth** for what is active; only the scopes listed in it are
evaluated. Phase-1 `path_map` (in `rules/semantic.rules.json`) wires exactly two scopes:

| spec `scope_path` | mzPeak (file, facet) | rules | status |
|---|---|---|---|
| `/spectrum` | `spectra_metadata`, `spectrum` | `spectrum_must`, `spectrum_may` | **active** |
| `/spectrum/precursors[]/selected_ions[]` | `spectra_metadata`, `selected_ion` | `precursor_selectedion_must` | **active** |

Every other spec scope is **unmapped** (skipped, never a false error) and falls into one of:

| spec `scope_path` | skipped MUST rule(s) | why unmapped |
|---|---|---|
| `/spectrum/scan_list`, `…/scans[]`, `…/scan_windows[]` | `scan_must` (MS:1000570 spectra combination), `scanwindow_must` (MS:1000500/501) | not surfaced as `scan`-facet columns in mzPeak's packed model |
| `/spectrum/precursors[]/activation`, `…/isolation_window` | `precursor_activation_must` (MS:1000044) | not surfaced as `precursor`-facet columns |
| `/spectrum/data_arrays[]`, `/chromatogram/data_arrays[]` | `*_binarydataarray_must` (MS:1000513/518/572) | binary-data terms live in the `spectrum_array_index` footer + Arrow dtype, not a facet — §6 |
| `/chromatogram`, `/chromatogram/{precursor,product}/isolation_window` | `chromatogram_must`, … | no `chromatograms_metadata` column schema yet (no chromatogram corpus file to calibrate against) |
| `/spectrum/products[]/isolation_window` | `product_isolationwindow_may` | no `product` facet in mzPeak today |

Absent files/facets are also skipped (self-gating). The `_unmapped_phase2` note in the engine rule mirrors
this list; promoting a scope is a one-line `path_map` addition (plus, for scan/activation, a spec/converter
decision on whether those terms become facet columns).

`allow_children` needs the OBO `is_a` graph. The CV loader (`Profile._load_cv`) previously kept only the
accession *set*; Phase 1 extends it to also build a merged `cv_isa` (child→parents) map, and
`_is_descendant()` walks it.

## 4. Implementation shape

- **One engine primitive** `cv_mapping(ar, rule, rep, params)` consumes a **whole bundled CvMapping file**
  (params `_mapping`) and iterates its `cv_mapping_rule_list`. This keeps the spec files **byte-for-byte
  verbatim** in the bundle (`profiles/mzpeak-0.9/cv_mapping/*.json`) — best provenance and the cleanest
  cross-language-parity story (a Rust port reuses the same JSON).
- **Engine rules** (in `rules/semantic.rules.json`) are thin: one rule per bundled mapping file, carrying the
  `path_map`, a `require_imaging` gate, and a `fix` tip. `cv_term_placement_tables` →
  `cv_mapping/table_rules.json`; `cv_term_placement_imaging` → `cv_mapping/imaging_table_rules.json`.
- Schema-only (reads column names, not row data) → **runs under `--quick`**, not in `DATA_SCAN`.

## 5. Severity decision — calibrated against the corpus, shipped advisory

Measured what real files carry per facet (10 diverse archives; uniform across the corpus):

- `spectrum` facet carries `MS:1000525` (representation ✓) and `MS:1000559` **itself** — but `spectrum_must`
  wants a *child* of `MS:1000559` (`use_term:false, allow_children:true`), e.g. `MS:1000294 mass spectrum`,
  which the corpus does **not** carry → `spectrum_must` is **violated corpus-wide**.
- `selected_ion` carries `MS:1000744/1000041/1000042`, all children of `MS:1000455` → `selectedion_must`
  **satisfied**.
- `scan_must` wants `MS:1000570` (spectra combination) — **not represented** in mzPeak's packed scan facet →
  violated corpus-wide.

Because the spec's MUSTs were written against mzML's element model and some don't yet map cleanly to mzPeak's
packed facets, Phase 1 ships **MUST → `warning`** (the engine rule's `severity` is the single knob).
This guarantees **no verdict regression** (the 523-file corpus stays PASS) while surfacing the placement gaps
as advisory findings — exactly the role of an advisory axis (cf. `parquet_row_group_health`). Promotion of
specific rules to `error` is a one-line `severity` change once the spec/converter reconcile the packed-facet
mapping (notably scan combination and the data-array terms).

## 6. Known limitations / phasing

- **Phase 2 — `semantic_rules.json` (JSON-metadata params).** The spec also governs CV terms in the index
  metadata blobs (`file_description.contents[]`, `run.parameters[]`, instrument-config components, software,
  data_processing). These need a JSON-pointer resolver over the index + footer blobs rather than facet column
  names. The file is bundled now (provenance); wiring is Phase 2.
- **Phase 2 — data-array terms.** `*_binarydataarray_must` (binary data array / type / compression) map to the
  `spectrum_array_index` footer (`array_type`) + Arrow dtype + `chunk_encoding`, not to facet columns. Needs an
  array-index resolver.
- **Phase 2 — MAY enforcement (the inverse check).** "A term present in a facet that matches *no* rule for that
  facet is not allowed here." High value, higher false-positive risk until the rule set is complete; deferred.
- **`use_term_name`** matching (by name not accession) is unused by the spec's mzPeak rules and not implemented.

## 7. (c) — imaging object rule + fix tips (shipped alongside)

- **Imaging CvMapping** (`cv_mapping/imaging_table_rules.json`, gated `require_imaging`): when the archive is
  imaging, the `scan` facet MUST carry `IMS:1000050` (position x) **and** `IMS:1000051` (position y). This is
  the mzPeak analogue of the mzML MALDI object rules (`LaserWavelengthObjectRule` etc.) and complements the
  existing `imaging_coordinates_1based` (which checks the *values* once the columns exist).
- **Fix tips** — adopting the mzML validator's `getHowToFixTips()` convention: rules may carry a `fix` string,
  surfaced on the finding (JSON + console). Applied to the new rules and a few high-traffic existing ones.
