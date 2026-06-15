#!/usr/bin/env python
"""Unit test for the cv_mapping primitive (catalog 1.8, PSI CvMapping port).

Drives p_cv_mapping directly with a tiny in-memory mapping + is_a graph + archive so the
combination logic (AND/OR/XOR), child inheritance (allow_children), use_term, cardinality
(is_repeatable) and the facet/imaging gating are pinned deterministically — independent of the
big bundled OBO or the corpus.

Run: python test_cv_mapping.py   (exit 0 = pass).
"""
import json, os, sys, tempfile
import pyarrow as pa, pyarrow.parquet as pq
from mzpeak_validator.core import Archive, p_cv_mapping

# numeric accessions (the inflection parser requires digit accessions). is_a graph:
# B,C are children of A; C2 is a child of C (grandchild of A); Z,Q unrelated.
A, B, C, C2, Z, Q = "MS:1000001", "MS:1000002", "MS:1000003", "MS:1000004", "MS:1000099", "MS:1000077"
ISA = {B: {A}, C: {A}, C2: {C}}

def term(acc, use_term=False, children=False, repeatable=True):
    return {"cv_identifier_ref": "MS", "term_accession": acc, "term_name": acc,
            "use_term": use_term, "allow_children": children, "is_repeatable": repeatable}

def mapping(rule_id, logic, terms, level="MUST", scope="/spectrum"):
    return {"cv_mapping_rule_list": [
        {"id": rule_id, "scope_path": scope, "cv_element_path": scope + "/parameters[]/accession",
         "requirement_level": level, "cv_terms_combination_logic": logic, "cv_terms": terms}]}

class _Rep:
    def __init__(self): self.msgs = []
    def add(self, rule, level, message, location=None, recovery=None, fix=None):
        self.msgs.append((level, message))

def _archive(d, spectrum_accs, imaging=False):
    """Build a 1-row spectra_metadata with the given CV accessions inflected into the spectrum facet."""
    os.makedirs(d, exist_ok=True)
    cols = [pa.array([0], pa.uint64())]
    names = ["index"]
    for a in spectrum_accs:                                   # a like "MS:B" -> column MS_B_x
        code, num = a.split(":")
        cols.append(pa.array([0], pa.uint8())); names.append(f"{code}_{num}_x")
    spectrum = pa.StructArray.from_arrays(cols, names=names)
    pq.write_table(pa.table({"spectrum": spectrum}), f"{d}/spectra_metadata.parquet")
    md = {"version": "0.9"}
    if imaging:
        md["imaging"] = {"is_imaging": True}
    json.dump({"files": [{"name": "spectra_metadata.parquet", "entity_type": "spectrum", "data_kind": "metadata"}],
               "metadata": md}, open(f"{d}/mzpeak_index.json", "w"))
    return Archive(d)

PMAP = {"/spectrum": {"file": "spectra_metadata", "facet": "spectrum"}}

def run(label, accs, mp, expect_violation, require_imaging=False, imaging=False):
    with tempfile.TemporaryDirectory() as tmp:
        ar = _archive(os.path.join(tmp, "a.mzpeak"), accs, imaging=imaging)
        rep = _Rep()
        params = {"_mapping": mp, "_cv_isa": ISA, "path_map": PMAP}
        if require_imaging:
            params["require_imaging"] = True
        p_cv_mapping(ar, {"id": "t", "primitive": "cv_mapping", "severity": "warning"}, rep, params)
        got = len(rep.msgs) > 0
        ok = got == expect_violation
        print(f"  [{'ok ' if ok else 'FAIL'}] {label}: findings={len(rep.msgs)} (expect {'violation' if expect_violation else 'clean'})")
        if rep.msgs and not expect_violation:
            print(f"        unexpected: {rep.msgs[0][1][:90]}")
        return ok

def main():
    print("== cv_mapping unit test ==")
    A_self  = term(A, use_term=True)
    A_child = term(A, use_term=False, children=True)
    Z_self  = term(Z, use_term=True)
    r = []
    # AND
    r.append(run("AND ok (both present)",      [A, Z], mapping("r", "AND", [A_self, Z_self]), False))
    r.append(run("AND violated (Z missing)",   [A],    mapping("r", "AND", [A_self, Z_self]), True))
    # OR
    r.append(run("OR ok (one present)",        [Z],    mapping("r", "OR",  [A_self, Z_self]), False))
    r.append(run("OR violated (none)",         [Q],    mapping("r", "OR",  [A_self, Z_self]), True))
    # XOR
    r.append(run("XOR ok (exactly one)",       [A],    mapping("r", "XOR", [A_self, Z_self]), False))
    r.append(run("XOR violated (both)",        [A, Z], mapping("r", "XOR", [A_self, Z_self]), True))
    # allow_children: a child satisfies; the parent itself does NOT when use_term=false
    r.append(run("children ok (B is child of A)",   [B],  mapping("r", "AND", [A_child]), False))
    r.append(run("children ok (grandchild C2)",     [C2], mapping("r", "AND", [A_child]), False))
    r.append(run("children violated (parent only, use_term=false)", [A], mapping("r", "AND", [A_child]), True))
    # use_term: exact term satisfies, a child does NOT when allow_children=false
    r.append(run("use_term violated (child not allowed)", [B], mapping("r", "AND", [A_self]), True))
    # cardinality: non-repeatable term matched by 2 columns
    r.append(run("cardinality violated (B and C2 both children of A)",
                 [B, C2], mapping("r", "AND", [term(A, children=True, repeatable=False)]), True))
    # imaging gate: require_imaging on a non-imaging archive -> skipped (no findings even though A missing)
    r.append(run("imaging gate skips non-imaging", [Q], mapping("r", "AND", [A_self]), False,
                 require_imaging=True, imaging=False))
    r.append(run("imaging gate fires on imaging",  [Q], mapping("r", "AND", [A_self]), True,
                 require_imaging=True, imaging=True))
    ok = all(r)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
