# Handoff — MZP CV support, anchor fix, index-block schema (mzpeak-0.9 profile)

Changes to `mzpeak_validator` to recognise the mzPeakConverter's converter-owned
provisional **MZP** controlled vocabulary, plus two schema fixes surfaced while
validating grid-encoded archives. All local; no upstream/PR action taken.

## What changed
1. **New CV artifact: MZP.** `profiles/mzpeak-0.9/profile.json` artifacts gained
   `{"role":"cv","id":"MZP","version":"0.1.0","path":"cv/mzpeak.obo","sha256":null}`,
   and the OBO was added at `profiles/mzpeak-0.9/cv/mzpeak.obo` (5 terms,
   MZP:1000001–1000005). `_load_cv()` parses it into `cv["MZP"]` like MS/UO/IMS, so
   `cv_inflection` now accepts `MZP_1000003_tof_c0` columns and the `MZP:1000001`
   transform CURIE. The OBO is the converter's `cv/mzpeak.obo` verbatim — keep the two
   in sync (source of truth: the converter repo).
2. **Anchor bug fix.** `profiles/mzpeak-0.9/schema/json/cv_list.json` line 7 had
   `"$ref": "#definitions/cv"` (missing leading slash) → threw `InvalidAnchor` on every
   archive. Fixed to `"$ref": "#/definitions/cv"`. Same typo fixed upstream in
   `mzPeak-specification/schema/cv_list.json`. The `build/lib/...` copy still has the typo
   but is regenerated and unused by the editable install — left alone.
3. **Index-block schema.** `profiles/mzpeak-0.9/schema/json/mzpeak_index.json` (and the
   upstream spec copy) gained typed optional `metadata` properties for the converter's four
   index blocks: `tof_calibration`, `ims_calibration`, `vendor_files`, `vendor_metadata`
   (`additionalProperties` kept true). The validator now shape-checks them (e.g. `codec`
   const, `vendor_files[].action` enum).

## Why MZP exists
mzdata's `CURIE` type cannot carry a non-PSI prefix, and the grid encoding needs terms
PSI-MS hasn't assigned yet. Rather than squat `MS:`, the converter emits a converter-owned
CV (prefix `MZP`, `cv/mzpeak.obo`) declared in each archive's `cv_list`. PROVISIONAL: once
PSI-MS assigns real terms, the converter swaps MZP→MS and this artifact can be retired.

## Verification
`mzpeak-validate` on the Agilent-grid and Bruker-ims-compact test archives → **PASS
(0 errors, 2 warnings)**; profile CV line shows `MZP: 0.1.0`. The two warnings
(`filecontent_must`, `processingmethod_must`) are pre-existing advisory findings, unrelated.

## Not done (intentional)
- **PSI-MS term requests** — out of scope; stays local.
- **`sha256` seal** for the MZP artifact — null like the others (future `--seal`).
- **Coverage rules** — optional hardening not yet added: (a) `transform` CURIE resolves to a
  declared `cv_list` CV; (b) `entity_type`/`data_kind` in controlled sets; (c) a param-bearing
  `transform` carries `mzpeak:transform_params` / `…_per_spectrum`.
