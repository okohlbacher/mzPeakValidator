#!/usr/bin/env python
"""Unit test for the cv_mapping primitive (catalog 1.8, PSI CvMapping port).

Drives p_cv_mapping directly with a tiny in-memory mapping + is_a graph + archive so the
combination logic (AND/OR/XOR), child inheritance (allow_children), use_term, cardinality
(is_repeatable) and the facet/imaging gating are pinned deterministically — independent of the
big bundled OBO or the corpus.

Catalog 1.18: a column carries its term by inflected name OR through a column_mapping entry in the
files[] entry of its table (how the imaging profile's scan.position_x / scan.position_y carry
IMS:1000050 / IMS:1000051). The second half of this file pins which mappings count, on the primitive
and, through run() with the bundled profile, on cv_term_placement_imaging / cv_term_placement_tables.

Run: python test_cv_mapping.py   (exit 0 = pass).
"""
import glob, json, os, sys, tempfile
import pyarrow as pa, pyarrow.parquet as pq
from mzpeak_validator import run as validate
from mzpeak_validator.core import Archive, p_cv_mapping
import make_fixtures as mf
from test_conformance_checks import zip_dir, edit_index

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

_UNSET = object()

def cm(column, acc, facet="spectrum"):
    """A column_mapping entry for `<facet>.<column>` naming the term `acc`."""
    return {"name": column, "path": f"{facet}.{column}", "accession": acc}

def _archive(d, spectrum_accs, imaging=False, plain=(), column_mapping=_UNSET, other_mapping=None):
    """Build a 1-row spectra_metadata with the given CV accessions inflected into the spectrum facet.
    `plain` names further spectrum columns without a term in their name; `column_mapping` is written
    as-is into the files[] entry of spectra_metadata.parquet, `other_mapping` into that of another
    table. The table also has a scan facet (column `plain_s`) and a list<struct> column
    spectrum.windows (child `lower`), to map into."""
    os.makedirs(d, exist_ok=True)
    cols = [pa.array([0], pa.uint64())]
    names = ["index"]
    for a in spectrum_accs:                                   # a like "MS:B" -> column MS_B_x
        code, num = a.split(":")
        cols.append(pa.array([0], pa.uint8())); names.append(f"{code}_{num}_x")
    for name in plain:
        cols.append(pa.array([0], pa.uint8())); names.append(name)
    cols.append(pa.array([[{"lower": 1.0}]], pa.list_(pa.struct([("lower", pa.float64())])))); names.append("windows")
    spectrum = pa.StructArray.from_arrays(cols, names=names)
    scan = pa.StructArray.from_arrays([pa.array([0], pa.uint64()), pa.array([0], pa.uint8())],
                                      names=["source_index", "plain_s"])
    pq.write_table(pa.table({"spectrum": spectrum, "scan": scan}), f"{d}/spectra_metadata.parquet")
    md = {"version": "0.9"}
    if imaging:
        md["imaging"] = {"is_imaging": True}
    files = [{"name": "spectra_metadata.parquet", "entity_type": "spectrum", "data_kind": "metadata"}]
    if column_mapping is not _UNSET:
        files[0]["column_mapping"] = column_mapping
    if other_mapping is not None:
        files.append({"name": "spectra_data.parquet", "entity_type": "spectrum", "data_kind": "data_arrays",
                      "column_mapping": other_mapping})
    json.dump({"files": files, "metadata": md}, open(f"{d}/mzpeak_index.json", "w"))
    return Archive(d)

PMAP = {"/spectrum": {"file": "spectra_metadata", "facet": "spectrum"}}

def run(label, accs, mp, expect_violation, require_imaging=False, imaging=False, **arch):
    with tempfile.TemporaryDirectory() as tmp:
        ar = _archive(os.path.join(tmp, "a.mzpeak"), accs, imaging=imaging, **arch)
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

    # --- catalog 1.18: a term carried through a column_mapping entry counts like an inflected one
    must_a, must_az = mapping("r", "AND", [A_self]), mapping("r", "AND", [A_self, Z_self])
    r.append(run("mapped: plain-named column with a column_mapping entry naming the term",
                 [], must_a, False, plain=["a"], column_mapping=[cm("a", A)]))
    r.append(run("mapped + inflected together satisfy AND",
                 [A], must_az, False, plain=["z"], column_mapping=[cm("z", Z)]))
    r.append(run("mapped child satisfies allow_children",
                 [], mapping("r", "AND", [A_child]), False, plain=["b"], column_mapping=[cm("b", B)]))
    r.append(run("mapped: a list<struct> child, list tokens omitted in the path (spectrum.windows.lower)",
                 [], must_a, False, column_mapping=[cm("windows.lower", A)]))
    r.append(run("inflected names alone still count (a column_mapping block without the term)",
                 [A], must_a, False, plain=["q"], column_mapping=[cm("q", Q)]))
    r.append(run("no inflected name and no mapping -> violated",
                 [], must_a, True, plain=["a"]))
    r.append(run("wrong accession: both columns mapped to Z leaves A missing",
                 [], must_az, True, plain=["a", "z"], column_mapping=[cm("a", Z), cm("z", Z)]))
    r.append(run("a mapping to an absent column does not count",
                 [], must_a, True, column_mapping=[cm("nope", A)]))
    r.append(run("a mapping to a column of another facet does not count",
                 [], must_a, True, column_mapping=[cm("plain_s", A, facet="scan")]))
    r.append(run("a mapping whose path lacks the facet (flat 'a') does not count",
                 [], must_a, True, plain=["a"], column_mapping=[{"name": "a", "path": "a", "accession": A}]))
    r.append(run("a mapping without an accession (null / absent) does not count",
                 [], must_a, True, plain=["a", "b"],
                 column_mapping=[{"name": "a", "path": "spectrum.a", "accession": None}, {"name": "b", "path": "spectrum.b"}]))
    r.append(run("a mapping in another table's files[] entry does not count",
                 [], must_a, True, plain=["a"], other_mapping=[cm("a", A)]))
    r.append(run("a column_mapping block that is no list is ignored, not a crash",
                 [], must_a, True, plain=["a"], column_mapping=cm("a", A)))
    r.append(run("column_mapping entries that are no objects are ignored, not a crash",
                 [], must_a, True, plain=["a"], column_mapping=["spectrum.a", None, 7]))
    one_child = mapping("r", "AND", [term(A, children=True, repeatable=False)])
    r.append(run("cardinality: inflected B and mapped C2 are two entries of a non-repeatable term",
                 [B], one_child, True, plain=["c2"], column_mapping=[cm("c2", C2)]))
    r.append(run("cardinality: one accession, inflected and mapped, is one entry",
                 [B], one_child, False, plain=["b"], column_mapping=[cm("b", B)]))
    r.append(run("imaging gate still skips a non-imaging archive with mappings",
                 [], must_a, False, require_imaging=True, imaging=False, plain=["q"], column_mapping=[cm("q", Q)]))

    profile_ok = bundled_profile()                # run both halves, whatever the first one says
    ok = all(r) and profile_ok
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

# ---------------------------------------------------------------------------------------------------
# Through run() with the bundled profile: cv_term_placement_imaging (imaging_table_rules.json, scan
# facet MUST carry IMS:1000050 AND IMS:1000051) and cv_term_placement_tables (the spec's table_rules.json)

PLACE, TABLES, COLS, COORDS = ("cv_term_placement_imaging", "cv_term_placement_tables",
                               "imaging_position_columns", "imaging_coordinates_1based")
IMG = {"is_imaging": True, "coordinate_base": 1}
XY = ["position_x", "position_y"]

def found(path, rule=PLACE, quick=False, level=None):
    return [f["message"] for f in validate(path, quick=quick)["findings"]
            if f["ruleId"] == rule and f["level"] in ((level,) if level else ("error", "warning"))]

def packed(d, meta=None, column_mapping=None, imaging=IMG):
    """A packed-layout archive (facets as struct columns of spectra_metadata). column_mapping None:
    each position column of the scan facet gets its mapping (make_fixtures' default); [] = none."""
    mf._write(d, mf._meta(coords=True) if meta is None else meta, mf._data(mf.S, mf.MZ, mf.IN),
              imaging=imaging, extra_metadata=mf._grid(), column_mapping=column_mapping)
    return d

def split(d, pos, mapped=True):
    """A split-layout imaging archive as mzpeak-convert writes it: flat position columns in
    spectra_metadata_scans.parquet, mapped in that table's files[] entry (path = the column name)."""
    scans = pa.table({"source_index": pa.array(range(3), pa.uint64()),
                      **{c: pa.array(v, pa.uint32()) for c, v in pos.items()}})
    mf._write_split(d, mf._split_meta_flat(), scans, mf._data(mf.S, mf.MZ, mf.IN), "PASS")
    def fn(idx):
        entry = next(fe for fe in idx["files"] if fe["name"] == "spectra_metadata_scans.parquet")
        entry["column_mapping"] = [{"name": c, "path": c, "accession": mf._POSITION_TERMS[c[-1]]} for c in pos] if mapped else []
        idx["metadata"].update(mf._grid()); idx["metadata"]["imaging"] = IMG
    edit_index(d, fn)
    return d

def bundled_profile():
    print("== cv_term_placement_imaging / _tables through the bundled profile ==")
    R = []
    def check(label, msgs, expect, contains=None):
        """expect True: some finding (containing `contains`, if given); False: none."""
        hit = [m for m in msgs if contains is None or contains in m]
        ok = bool(hit) == expect
        R.append(ok)
        print(f"  [{'ok ' if ok else 'FAIL'}] {label}: {(hit or msgs or ['no findings'])[0][:150]}")

    with tempfile.TemporaryDirectory() as tmp:
        # --- packed layout: the profile's names carry their terms through column mappings
        d = packed(f"{tmp}/ok")
        rep = validate(d)
        check("packed, scan.position_x/_y mapped to IMS:1000050/51 -> no finding", found(d), False)
        check("... and the archive passes without any warning",
              [f"{rep['verdict']} {rep['summary']['warnings']}W"], True, "PASS 0W")
        check("... as a ZIP", found(zip_dir(d)), False)
        check("... under --quick (schema + index only)", found(d, quick=True), False)
        xyz = packed(f"{tmp}/xyz", mf._meta(coords=([1, 2, 3], [1, 1, 1], [1, 2, 1])))
        check("position_z mapped as well -> no finding", found(xyz), False)
        draft = {"x": "IMS_1000050_position_x", "y": "IMS_1000051_position_y"}
        d = packed(f"{tmp}/draft", mf._meta(coords=True, coord_names=draft), column_mapping=[])
        check("the first draft's inflected names, no mappings -> no finding (the name route still counts)", found(d), False)
        old = {"x": "opt_IMS_1000050_position_x", "y": "opt_IMS_1000051_position_y"}
        d = packed(f"{tmp}/opt", mf._meta(coords=True, coord_names=old))
        check("mzpeak-convert 0.15.0's opt_ names, mapped -> no finding", found(d), False)

        # --- and still a finding where the scan facet does not carry both terms
        d = packed(f"{tmp}/none", mf._meta(), column_mapping=[])
        check("packed, marked imaging, neither inflected names nor mappings -> warning", found(d, level="warning"), True,
              "spectra_metadata [scan]: CvMapping 'imaging_scan_position_must' (MUST/AND) requires all of [position x "
              "(IMS:1000050), position y (IMS:1000051)]; missing: position x, position y")
        check("... under --quick too", found(d, quick=True), True)
        d = packed(f"{tmp}/nomap", column_mapping=[])
        check("position_x/_y present, no mappings -> warning", found(d), True, "missing: position x, position y")
        check("... next to imaging_position_columns' error", found(d, COLS, level="error"), True, "no column_mapping entry")
        both_y = [{**m, "accession": "IMS:1000051"} for m in mf._position_mappings(XY)]
        msgs = found(packed(f"{tmp}/both_y", column_mapping=both_y))
        check("wrong accession: position_x and position_y both mapped to IMS:1000051 -> position x missing",
              [m for m in msgs if m.endswith("missing: position x")], True)
        msgs = found(packed(f"{tmp}/only_y", column_mapping=mf._position_mappings(["position_y"])))
        check("only position_y mapped -> position x missing", [m for m in msgs if m.endswith("missing: position x")], True)
        d = packed(f"{tmp}/absent", mf._meta(), column_mapping=mf._position_mappings(XY))
        check("mappings to scan.position_x/_y, the columns absent -> warning", found(d), True, "missing: position x, position y")
        check("... and column_mapping_valid reports the dangling paths", found(d, "column_mapping_valid"), True,
              "points at 'scan.position_x' but no such column exists")
        d = packed(f"{tmp}/null_acc", column_mapping=[{**m, "accession": None} for m in mf._position_mappings(XY)])
        check("mappings without an accession -> warning", found(d), True, "missing: position x, position y")
        d = packed(f"{tmp}/elsewhere", column_mapping=[])
        edit_index(d, lambda idx: idx["files"][1].update(column_mapping=mf._position_mappings(XY)))
        check("the mappings in another table's files[] entry -> warning", found(d), True, "missing: position x, position y")
        # positions in the spectrum facet: the imaging rules find and accept them, this rule names the facet
        m = mf._meta()
        sp = m.column("spectrum").combine_chunks()
        sp = pa.StructArray.from_arrays([sp.field(i) for i in range(sp.type.num_fields)] + [pa.array([1, 2, 3], pa.int64()), pa.array([1, 1, 1], pa.int64())],
                                        names=[f.name for f in sp.type] + XY)
        d = packed(f"{tmp}/spectrum_facet", m.set_column(0, "spectrum", sp), column_mapping=mf._position_mappings(XY, prefix="spectrum."))
        check("positions and mappings in the spectrum facet, not the scan facet -> warning", found(d), True, "spectra_metadata [scan]")
        check("... the only rule that reports it", found(d, COLS) + found(d, COORDS), False)
        # the rule looks at the facet's set of terms; which column carries which is imaging_position_columns'
        swapped = [{**m, "accession": a} for m, a in zip(mf._position_mappings(XY), ("IMS:1000051", "IMS:1000050"))]
        d = packed(f"{tmp}/swapped", column_mapping=swapped)
        check("swapped accessions: both terms are in the facet -> no finding here", found(d), False)
        check("... imaging_position_columns reports the swap", found(d, COLS, level="error"), True, "not the column's term IMS:1000050")
        d = packed(f"{tmp}/not_imaging", mf._meta(), column_mapping=[], imaging=None)
        check("not an imaging archive -> the rule does not apply", found(d), False)

        # --- split layout: left to the imaging rules (the rule self-skips: spectra_metadata has no scan facet)
        pos = {"position_x": [1, 2, 3], "position_y": [1, 1, 1]}
        d = split(f"{tmp}/split_ok", pos)
        rep = validate(d)
        check("split, positions + mappings in spectra_metadata_scans -> no finding", found(d), False)
        check("... and the archive passes without any warning",
              [f"{rep['verdict']} {rep['summary']['warnings']}W"], True, "PASS 0W")
        d = split(f"{tmp}/split_none", {})
        check("split, no position columns -> no finding here", found(d), False)
        check("... imaging_coordinates_1based reports it as an error", found(d, COORDS, level="error"), True,
              "missing position_x and/or position_y")
        d = split(f"{tmp}/split_nomap", pos, mapped=False)
        check("split, positions without mappings -> no finding here", found(d), False)
        check("... imaging_position_columns reports it as an error", found(d, COLS, level="error"), True,
              "spectra_metadata_scans.position_x: no column_mapping entry")

        # --- cv_term_placement_tables binds the same primitive: spectrum type (a child of MS:1000559)
        d = f"{tmp}/type_missing"; mf._write(d, mf._meta(spectrum_type=False), mf._data(mf.S, mf.MZ, mf.IN))
        check("spectrum facet without a spectrum type -> cv_term_placement_tables warning", found(d, TABLES), True, "missing: spectrum type")
        m = mf._meta(spectrum_type=False)
        sp = m.column("spectrum").combine_chunks()
        sp = pa.StructArray.from_arrays([sp.field(i) for i in range(sp.type.num_fields)] + [pa.array([True] * 3, pa.bool_())],
                                        names=[f.name for f in sp.type] + ["mass_spectrum"])
        marker = [{"name": "mass spectrum", "path": "spectrum.mass_spectrum", "accession": "MS:1000294", "term_marker": True}]
        d = f"{tmp}/type_mapped"; mf._write(d, m.set_column(0, "spectrum", sp), mf._data(mf.S, mf.MZ, mf.IN), column_mapping=marker)
        rep = validate(d)
        check("spectrum type through a mapped boolean term-marker column (MS:1000294) -> no finding", found(d, TABLES), False)
        check("... and the archive passes without any warning",
              [f"{rep['verdict']} {rep['summary']['warnings']}W"], True, "PASS 0W")

        # --- the fixtures: no pass fixture warns, and the rule fires exactly where a fixture expects it
        mf.build_all(f"{tmp}/fx")
        warned, expected, imaging_pass = set(), set(), 0
        for exp_path in sorted(glob.glob(f"{tmp}/fx/*/*/expected.json")):
            d = os.path.dirname(exp_path); name = os.path.relpath(d, f"{tmp}/fx")
            idx = json.load(open(f"{d}/mzpeak_index.json"))
            if name.startswith("pass/") and (idx.get("metadata") or {}).get("imaging"):
                imaging_pass += 1
            if found(d): warned.add(name)
            if json.load(open(exp_path)).get("warn_rule") == PLACE: expected.add(name)
        check(f"none of the pass fixtures ({imaging_pass} of them imaging) raises the rule",
              sorted(n for n in warned if n.startswith("pass/")), False)
        check("there are imaging pass fixtures to hold to that", [str(imaging_pass)] if imaging_pass >= 10 else [], True)
        check("the rule fires on exactly the fixtures that expect it (3)",
              [f"unexpected {sorted(warned - expected)} missing {sorted(expected - warned)}"]
              if warned != expected or len(expected) != 3 else [], False)
    ok = all(R)
    print(f"  {sum(R)}/{len(R)} checks passed")
    return ok

if __name__ == "__main__":
    sys.exit(main())
