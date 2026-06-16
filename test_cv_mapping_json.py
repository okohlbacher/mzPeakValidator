#!/usr/bin/env python
"""Unit test for the cv_mapping_json primitive (catalog 1.9) — CV term placement over the JSON index
metadata (the spec's semantic_rules.json). Drives p_cv_mapping_json with a tiny mapping + a stub
archive (only `.index` is read) so the JSON path walker (key / key[] / key[field=value] / leaf),
per-scope-instance evaluation, combination logic and the vacuous-when-absent behavior are pinned
deterministically. Run: python test_cv_mapping_json.py  (exit 0 = pass).
"""
import sys
from mzpeak_validator.core import p_cv_mapping_json

# numeric accessions; B is a child of A (is_a graph)
A, B, Z = "MS:1000001", "MS:1000002", "MS:1000099"
ISA = {B: {A}}

class FakeAr:
    def __init__(self, metadata): self.index = {"files": [], "metadata": metadata}

class Rep:
    def __init__(self): self.msgs = []
    def add(self, rule, level, message, location=None, recovery=None, fix=None):
        self.msgs.append((level, message))

def term(acc, use_term=False, children=False):
    return {"cv_identifier_ref": "MS", "term_accession": acc, "term_name": acc,
            "use_term": use_term, "allow_children": children, "is_repeatable": True}

def mapping(scope, elem, terms, logic="AND", level="MUST"):
    return {"cv_mapping_rule_list": [
        {"id": "r", "scope_path": scope, "cv_element_path": elem,
         "requirement_level": level, "cv_terms_combination_logic": logic, "cv_terms": terms}]}

def run(label, metadata, mp, expect_findings):
    ar = FakeAr(metadata); rep = Rep()
    p_cv_mapping_json(ar, {"id": "t", "primitive": "cv_mapping_json", "severity": "warning"},
                      rep, {"_mapping": mp, "_cv_isa": ISA})
    ok = len(rep.msgs) == expect_findings
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}: findings={len(rep.msgs)} (expect {expect_findings})")
    if not ok and rep.msgs:
        print(f"        got: {rep.msgs[0][1][:90]}")
    return ok

def main():
    print("== cv_mapping_json unit test ==")
    # contents[]/accession: MUST a child of A
    fd_must = mapping("/metadata/file_description",
                      "/metadata/file_description/contents[]/accession", [term(A, children=True)])
    r = []
    r.append(run("contents has child B -> ok",
                 {"file_description": {"contents": [{"accession": B}]}}, fd_must, 0))
    r.append(run("contents has only unrelated Z -> violation",
                 {"file_description": {"contents": [{"accession": Z}]}}, fd_must, 1))
    r.append(run("file_description absent -> vacuous (no instance)",
                 {}, fd_must, 0))
    r.append(run("null accession ignored -> violation (no real term)",
                 {"file_description": {"contents": [{"accession": None}]}}, fd_must, 1))

    # component filter [component_type=ionsource]: MUST the exact term A (use_term)
    ion_must = mapping("/metadata/instrument_configuration_list[]/components[component_type=ionsource]",
                       "/metadata/instrument_configuration_list[]/components[component_type=ionsource]/parameters[]/accession",
                       [term(A, use_term=True)])
    ic = lambda accs, ctype="ionsource": {"instrument_configuration_list": [
        {"components": [{"component_type": ctype, "parameters": [{"accession": a} for a in accs]}]}]}
    r.append(run("ionsource has exact A -> ok", ic([A]), ion_must, 0))
    r.append(run("ionsource has only child B (use_term wants A) -> violation", ic([B]), ion_must, 1))
    r.append(run("filter excludes analyzer component -> vacuous", ic([A], ctype="analyzer"), ion_must, 0))

    # per-instance: two software entries, one missing the required term -> exactly one finding
    sw_must = mapping("/metadata/software_list[]",
                      "/metadata/software_list[]/parameters[]/accession", [term(A, children=True)])
    r.append(run("two software, one missing -> 1 finding",
                 {"software_list": [{"parameters": [{"accession": B}]}, {"parameters": []}]}, sw_must, 1))

    ok = all(r)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
