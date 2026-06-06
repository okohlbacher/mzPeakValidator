#!/usr/bin/env python3
"""Generate a Markdown reference page for a validation profile.

Reads a profile bundle (profile.json + rules/*.rules.json + schema/tables/*.columns.json)
and emits a self-describing reference: conformance axes, pinned artifacts, the rule
structure, every rule (id / primitive / severity / recovery / what it checks, drawn from
the rules' own `doc` fields), the primitive param contracts (from each file's `about`),
and the column schemas. Because it reads the profile's own data, the page stays correct
when rules change -- just re-run it.

Usage:
    python docs/gen_profile_page.py <profile_dir> > docs/profiles/<id>.md
    # e.g.
    python docs/gen_profile_page.py mzpeak_validator/profiles/mzpeak-0.9 > docs/profiles/mzpeak-0.9.md
"""
import json, sys
from pathlib import Path

# Logical (not alphabetical) order for the rule-file sections.
FILE_ORDER = ["structural.rules.json", "cv.rules.json", "numeric.rules.json", "imaging.rules.json"]


def esc(s):
    """Escape a string for use inside a Markdown table cell."""
    return str(s).replace("|", "\\|").replace("\n", " ").strip()


def load(profile_dir):
    p = Path(profile_dir)
    manifest = json.loads((p / "profile.json").read_text())
    rule_files = {}
    for rf in (p / "rules").glob("*.rules.json"):
        rule_files[rf.name] = json.loads(rf.read_text())
    columns = {}
    tdir = p / "schema" / "tables"
    if tdir.is_dir():
        for cf in sorted(tdir.glob("*.columns.json")):
            spec = json.loads(cf.read_text())
            columns[spec["file"]] = spec
    return manifest, rule_files, columns


def ordered_files(rule_files):
    keys = list(rule_files)
    head = [k for k in FILE_ORDER if k in rule_files]
    return head + sorted(k for k in keys if k not in head)


def main():
    if len(sys.argv) != 2:
        print(__doc__.strip()); sys.exit(2)
    profile_dir = sys.argv[1]
    manifest, rule_files, columns = load(profile_dir)

    pid = manifest.get("profile_id", Path(profile_dir).name)
    spec = manifest.get("mzpeak_spec", {})
    catalog = manifest.get("rule_primitive_catalog", "?")
    n_rules = sum(len(rf.get("rules", [])) for rf in rule_files.values())

    o = []
    A = o.append

    A(f"# Profile reference — `{pid}`")
    A("")
    A(f"> **Generated** from the profile bundle by [`docs/gen_profile_page.py`](../gen_profile_page.py). "
      f"Do not edit by hand — re-run the generator after changing the profile:")
    A(f"> `python docs/gen_profile_page.py {profile_dir} > docs/profiles/{pid}.md`")
    A("")
    A(f"- **Profile id:** `{pid}`")
    if spec:
        A(f"- **mzPeak spec:** {spec.get('version','?')} "
          + (f"(commit [`{spec['commit'][:12]}`]({spec.get('url','')}))" if spec.get("commit") else ""))
    A(f"- **Rule-primitive catalog:** `{catalog}` (the cross-language contract the engine implements)")
    A(f"- **Rules:** {n_rules} across {len(rule_files)} files")
    if spec.get("note"):
        A(f"- **Note:** {spec['note']}")
    A("")

    A("## How validation works")
    A("")
    A("Validation is driven by this *profile* — a versioned bundle of JSON Schemas, pinned "
      "controlled-vocabulary (CV) snapshots, and a declarative **rule set**. The engine implements a "
      "small **primitive catalog**; each rule is a data-only *instance* of a primitive, so any "
      "implementation that implements the catalog reproduces identical verdicts. Each rule self-gates "
      "(it no-ops when its target file/column is absent), so layout-independent checks apply everywhere "
      "while point-layout / imaging checks quietly skip where they do not apply.")
    A("")

    axes = manifest.get("conformance_axes")
    if axes:
        A("## Conformance axes")
        A("")
        A("Conformance is reported along independent axes: " + ", ".join(f"`{a}`" for a in axes) + ".")
        A("")

    A("## Severity & recovery")
    A("")
    A("Two non-gameable severity tiers:")
    A("")
    A("| Level | Meaning |")
    A("|---|---|")
    A("| `error` | structural / schema-type / numeric / index / integrity / required-CV — hard, never demotable |")
    A("| `warning` | SHOULD-level (e.g. CV completeness, auxiliary optical images, non-contiguous index) |")
    A("")
    A("Every rule also declares a **recovery class** — how a paired repair mode could fix the finding "
      "(validation only reports; it never mutates):")
    A("")
    A("| Class | Auto-applied? | Meaning |")
    A("|---|---|---|")
    A("| `rebuild` | yes (lossless) | reconstruct a derived structure (e.g. a lost index) from the authoritative data |")
    A("| `recompute` | yes (lossless) | recompute a recorded digest/aggregate |")
    A("| `rederive` | yes (lossless) | re-derive a missing/wrong derivable value or relabel a dtype tag |")
    A("| `reorder_pair` | yes (lossless) | re-sort an axis that MUST be sorted, moving its parallel arrays with it |")
    A("| `normalize` | opt-in (lossy) | alter values to satisfy a constraint (e.g. clamp negative intensity) |")
    A("| `drop` | opt-in (lossy) | remove an irreparable record |")
    A("| `none` | no → hard fail | not auto-recoverable |")
    A("")

    arts = manifest.get("artifacts", [])
    if arts:
        A("## Pinned artifacts")
        A("")
        A("| Role | Id | Version | Path |")
        A("|---|---|---|---|")
        for a in arts:
            A(f"| {esc(a.get('role',''))} | {esc(a.get('id',''))} | {esc(a.get('version',''))} | `{esc(a.get('path',''))}` |")
        A("")
        A("CV snapshots are pinned OBO files (no live ontology lookup at validate time). "
          "`sha256` content-addressing is filled by a future `--seal` step.")
        A("")

    A("## Rule structure")
    A("")
    A("Each rule is a JSON object. The engine reads **only** these keys:")
    A("")
    A("```json")
    A("{")
    A('  "id": "mz_monotonic_data",          // unique rule id (appears in findings)')
    A('  "primitive": "grouped_monotonic",   // which catalog primitive to run')
    A('  "severity": "error",                // error | warning')
    A('  "recovery": "reorder_pair",         // recovery class (table above)')
    A('  "params": { ... },                  // primitive-specific parameters')
    A('  "doc": "..."                        // NON-NORMATIVE: documentation, ignored by the engine')
    A("}")
    A("```")
    A("")
    A("Each `rules/*.rules.json` also has a top-level `about` block (purpose, gating, a per-primitive "
      "param contract, and a how-to-amend note). `about` and `doc` are documentation only. "
      "**To amend:** copy a rule and edit its `params`; to change which columns/types are required, edit "
      "the relevant `schema/tables/*.columns.json` (not a rule); to accept a new CV, add its OBO as a "
      "`cv` artifact in `profile.json`.")
    A("")

    A("## Checks by rule file")
    A("")
    for fname in ordered_files(rule_files):
        data = rule_files[fname]
        about = data.get("about", {})
        A(f"### `{fname}`")
        A("")
        if about.get("purpose"):
            A(f"**Purpose.** {about['purpose']}")
            A("")
        if about.get("applies_to"):
            A(f"**Applies to.** {about['applies_to']}")
            A("")
        for extra_key, label in [("null_semantics", "Null semantics"), ("spec_basis", "Spec basis")]:
            if about.get(extra_key):
                A(f"**{label}.** {about[extra_key]}")
                A("")
        A("| Rule id | Primitive | Severity | Recovery | What it checks |")
        A("|---|---|---|---|---|")
        for r in data.get("rules", []):
            A(f"| `{esc(r.get('id',''))}` | `{esc(r.get('primitive',''))}` | {esc(r.get('severity',''))} "
              f"| {esc(r.get('recovery','none'))} | {esc(r.get('doc',''))} |")
        A("")

    # Merge per-file primitive contracts.
    contracts = {}
    for fname in ordered_files(rule_files):
        for prim, contract in (rule_files[fname].get("about", {}).get("primitives", {})).items():
            contracts.setdefault(prim, contract)
    if contracts:
        A("## Primitive catalog (param contracts)")
        A("")
        A(f"The {len(contracts)} primitives used by this profile and the parameters each accepts:")
        A("")
        for prim in sorted(contracts):
            A(f"- **`{prim}`** — {contracts[prim]}")
        A("")

    if columns:
        A("## Column schemas")
        A("")
        A("Required facets/columns and expected logical types per table "
          "(`columns_present` enforces these; edit these files to change what is required).")
        A("")
        for tbl, spec in columns.items():
            A(f"### `{tbl}`")
            A("")
            if spec.get("note"):
                A(f"_{spec['note']}_")
                A("")
            A("| Facet | Facet required | Column | Type | Column required |")
            A("|---|---|---|---|---|")
            for facet, fs in spec.get("facets", {}).items():
                freq = "yes" if fs.get("required") else "no"
                cols = fs.get("columns", {})
                if not cols:
                    A(f"| `{facet}` | {freq} | — | — | — |")
                for col, cs in cols.items():
                    A(f"| `{facet}` | {freq} | `{esc(col)}` | `{esc(cs.get('type',''))}` "
                      f"| {'yes' if cs.get('required') else 'no'} |")
            A("")

    sys.stdout.write("\n".join(o) + "\n")


if __name__ == "__main__":
    main()
