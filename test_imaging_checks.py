#!/usr/bin/env python
"""Unit test for the catalog-1.17 imaging checks (spec PR #25 'What a validator checks' 2, 3, 6, 7 and
the micrometre SHOULD; HUPO-PSI/mzPeak-specification#23 follow-up), on the cases the fixture harness
cannot express: the split layout mzpeak-convert writes (positions and their column mappings in
spectra_metadata_scans), a ZIP archive, --quick, the shapes of an unpinned IMS uri, counts that live in
the footer or disagree between scan settings and pixel_count, null and null-padded positions, and the
gates that keep the rules off non-imaging archives. Validates through run().
Run: python test_imaging_checks.py  (exit 0 = pass).
"""
import json, os, sys, tempfile
import pyarrow as pa
from mzpeak_validator import run
import make_fixtures as mf
from test_conformance_checks import zip_dir, edit_index

R = []
def check(label, msgs, expect, contains=None):
    """expect True: some finding (containing `contains`, if given); False: none."""
    hit = [m for m in msgs if contains is None or contains in m]
    ok = bool(hit) == expect
    R.append(ok)
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}: {(hit or msgs or ['no findings'])[0][:150]}")

def found(path, rule, quick=False, level=None):
    return [f["message"] for f in run(path, quick=quick)["findings"]
            if f["ruleId"] == rule and f["level"] in ((level,) if level else ("error", "warning"))]

COLS, UNIT, BOUNDS, PIN = ("imaging_position_columns", "imaging_length_unit_micrometre",
                           "imaging_positions_within_grid", "imaging_ims_cv_pinned")
IMG = {"is_imaging": True, "coordinate_base": 1}
DATA = mf._data(mf.S, mf.MZ, mf.IN)

def split(d, pos, typ=pa.uint32(), mapped=None, mapped_on="spectra_metadata_scans.parquet", grid=None,
          imaging=IMG, cv_list=None):
    """A split-layout imaging archive as mzpeak-convert writes it: positions `pos` ({column: values}) in
    spectra_metadata_scans, their column mappings (`mapped`: {column: accession}, default each column's
    own term) in the files[] entry `mapped_on`, the pixel grid in metadata.scan_settings_list."""
    scans = pa.table({"source_index": pa.array(range(3), pa.uint64()),
                      **{c: pa.array(v, typ) for c, v in pos.items()}})
    mf._write_split(d, mf._split_meta_flat(), scans, DATA, "PASS")
    if mapped is None:
        mapped = {c: mf._POSITION_TERMS[c[-1]] for c in pos}
    def fn(idx):
        entry = next(fe for fe in idx["files"] if fe["name"] == mapped_on)
        entry["column_mapping"] = [{"name": c, "path": c, "accession": a} for c, a in mapped.items()]
        idx["metadata"].update(grid or mf._grid())
        if imaging is not None: idx["metadata"]["imaging"] = imaging
        if cv_list is not None: idx["metadata"]["cv_list"] = cv_list
    edit_index(d, fn)
    return d

def ims(uri):
    return [c if c["id"] != "IMS" else {**c, "uri": uri} for c in mf._CV_LIST]

def main():
    print("== catalog 1.17 imaging checks ==")
    XY = {"position_x": [1, 2, 3], "position_y": [1, 1, 1]}
    OLD = {"opt_IMS_1000050_position_x": [1, 2, 3], "opt_IMS_1000051_position_y": [1, 1, 1]}
    with tempfile.TemporaryDirectory() as tmp:
        # --- imaging_position_columns: the mapping lives in the files[] entry of the table that has the column
        ok = split(f"{tmp}/ok", {**XY, "position_z": [1, 1, 1]})
        rep = run(zip_dir(ok))
        check("split layout, ZIP, uint32 x/y/z mapped to IMS:1000050/51/52 -> no finding of the four rules",
              [f["message"] for f in rep["findings"] if f["ruleId"] in (COLS, UNIT, BOUNDS, PIN)], False)
        check("... and the archive passes", [rep["verdict"]], True, "PASS")
        d = split(f"{tmp}/nomap", XY, mapped={})
        check("split layout, no mapping -> error per column, naming the term", found(d, COLS, level="error"), True,
              "spectra_metadata_scans.position_y: no column_mapping entry in the files[] entry of "
              "spectra_metadata_scans.parquet — each position column MUST have one naming its term, IMS:1000051")
        check("schema-only: reported under --quick too", found(d, COLS, quick=True, level="error"), True)
        d = split(f"{tmp}/elsewhere", XY, mapped_on="spectra_metadata.parquet")
        check("mapping on another table's files[] entry does not count", found(d, COLS, level="error"), True,
              "spectra_metadata_scans.position_x: no column_mapping entry")
        d = split(f"{tmp}/z_unmapped", {**XY, "position_z": [1, 1, 1]},
                  mapped={"position_x": "IMS:1000050", "position_y": "IMS:1000051"})
        msgs = found(d, COLS)
        check("position_z present but unmapped -> error naming IMS:1000052", msgs, True, "position_z: no column_mapping entry")
        check("... x and y are not flagged", msgs, False, "position_x")
        d = split(f"{tmp}/no_acc", XY, mapped={"position_x": None, "position_y": "MS:1000511"})
        msgs = found(d, COLS, level="error")
        check("mapping without an accession -> error", msgs, True, "position_x: its column_mapping entry names None")
        check("mapping to a term of another vocabulary -> error", msgs, True,
              "position_y: its column_mapping entry names 'MS:1000511', not the column's term IMS:1000051")
        d = split(f"{tmp}/twice", XY)
        edit_index(d, lambda idx: idx["files"][1]["column_mapping"].insert(
            0, {"name": "x", "path": "position_x", "accession": "IMS:1000051"}))
        check("two entries for one column, one naming its term -> accepted", found(d, COLS), False)
        d = split(f"{tmp}/old", OLD, mapped={c: mf._POSITION_TERMS[c[-1]] for c in OLD})
        check("earlier draft's names, mapped (mzpeak-convert 0.15.0) -> warning for the name", found(d, COLS, level="warning"),
              True, "opt_IMS_1000050_position_x: an earlier draft's column name — the imaging profile names the column position_x")
        check("... and no error", found(d, COLS, level="error"), False)
        d = split(f"{tmp}/old_nomap", OLD, mapped={})
        check("earlier draft's names, unmapped -> the mapping error as well", found(d, COLS, level="error"), True,
              "opt_IMS_1000051_position_y: no column_mapping entry")
        d = split(f"{tmp}/float", XY, typ=pa.float32())
        check("float positions in the split layout -> error", found(d, COLS, level="error"), True,
              "spectra_metadata_scans.position_x: position column is float, not an integer column")
        for t in (pa.int32(), pa.int64(), pa.uint64()):
            check(f"{t} positions -> accepted", found(split(f"{tmp}/t_{t}", XY, typ=t), COLS), False)

        # --- imaging_ims_cv_pinned: the shapes of a uri that names no commit
        sha = mf.IMS_URI.split("/")[5]
        for label, uri, expect, contains in [
                ("upper-case commit hash", mf.IMS_URI.replace(sha, sha.upper()), False, None),
                ("refs/heads/master (mzpeak-convert 0.15.0)", mf.IMS_URI.replace(sha, "refs/heads/master"), True,
                 "names the branch 'refs/heads/master', not a commit"),
                (".../master/...", mf.IMS_URI.replace(sha, "master"), True, "names the branch 'master', not a commit"),
                ("39-character hash", mf.IMS_URI.replace(sha, sha[:39]), True, "does not name a commit"),
                ("abbreviated hash", mf.IMS_URI.replace(sha, sha[:7]), True, "does not name a commit"),
                ("a tag", mf.IMS_URI.replace(sha, "v1.1.0"), True, "does not name a commit"),
                ("the commit on github.com/blob, not the raw form", f"https://github.com/imzML/imzML/blob/{sha}/imagingMS.obo",
                 True, "does not name a commit — it MUST have the form https://raw.githubusercontent.com/imzML/imzML/<commit hash>/imagingMS.obo"),
                ("the OBO purl", "http://purl.obolibrary.org/obo/imagingMS.obo", True, "does not name a commit"),
                ("text after the form", mf.IMS_URI + "?raw=1", True, "does not name a commit"),
                ("no uri", None, True, "the IMS uri None does not name a commit")]:
            d = split(f"{tmp}/uri_{len(R)}", XY, cv_list=ims(uri))
            check(f"IMS uri: {label} -> {'error' if expect else 'accepted'}", found(d, PIN, level="error"), expect, contains)
        d = split(f"{tmp}/uri_quick", XY, cv_list=ims(mf.IMS_URI.replace(sha, "refs/heads/master")))
        check("index-only: reported under --quick too", found(d, PIN, quick=True, level="error"), True)
        two = mf._CV_LIST + [{**mf._CV_LIST[1], "uri": mf.IMS_URI.replace(sha, "master")}]
        check("two IMS entries, one on a branch -> one error", found(split(f"{tmp}/uri_two", XY, cv_list=two), PIN), True, "'master'")
        d = f"{tmp}/not_imaging"; mf._write(d, mf._meta(), DATA, cv_list=ims(mf.IMS_URI.replace(sha, "refs/heads/master")),
                                            extra_metadata=mf._grid(pixel_unit="UO:0000015"))
        rep = run(d)
        check("not an imaging archive: none of the four rules applies",
              [f["message"] for f in rep["findings"] if f["ruleId"] in (COLS, UNIT, BOUNDS, PIN)], False)

        # --- imaging_positions_within_grid
        d = split(f"{tmp}/at_count", {"position_x": [1, 2, 3], "position_y": [1, 2, 2]}, grid=mf._grid(ny=2))
        check("largest positions equal to the counts -> clean", found(d, BOUNDS), False)
        d = split(f"{tmp}/y_beyond", {"position_x": [1, 2, 3], "position_y": [1, 2, 2]})
        check("split layout: y beyond IMS:1000043", found(zip_dir(d), BOUNDS, level="error"), True,
              "spectra_metadata_scans.position_y: largest position 2 lies beyond IMS:1000043 (max count of pixels y) "
              "of scan settings 'scansettings1' = 1")
        check("a data scan: not run under --quick", found(d, BOUNDS, quick=True), False)
        img = {**IMG, "pixel_count": {"x": 2, "y": 1}}
        d = split(f"{tmp}/block_only", XY, imaging=img,
                  grid={"scan_settings_list": mf._grid()["scan_settings_list"] * 2})
        check("no single grid entry: positions still checked against pixel_count", found(d, BOUNDS, level="error"), True,
              "position_x: largest position 3 lies beyond metadata.imaging.pixel_count.x = 2")
        d = split(f"{tmp}/both", XY, imaging={**IMG, "pixel_count": {"x": 1, "y": 1}}, grid=mf._grid(nx=2))
        msgs = found(d, BOUNDS, level="error")
        check("scan settings and pixel_count disagree, both exceeded -> named separately", msgs, True, "pixel_count.x = 1")
        check("... the scan-settings count too", msgs, True, "IMS:1000042 (max count of pixels x) of scan settings 'scansettings1' = 2")
        d = split(f"{tmp}/same", XY, imaging=img, grid=mf._grid(nx=2))
        check("scan settings and pixel_count agree -> one finding, not two", [str(len(found(d, BOUNDS)))], True, "1")
        g = mf._grid(nx=2); d = f"{tmp}/footer"
        mf._write(d, mf._meta(coords=True, extra_footer={"scan_settings_list": json.dumps(g["scan_settings_list"])}),
                  DATA, imaging=IMG)
        check("counts only in the spectra_metadata footer -> used", found(d, BOUNDS, level="error"), True,
              "spectra_metadata.scan.position_x: largest position 3 lies beyond IMS:1000042")
        g = mf._grid(); g["scan_settings_list"][0]["parameters"][0]["value"] = "2"
        check("a count that is not an integer is imaging_grid_settings' finding, not a bound",
              found(split(f"{tmp}/strcount", XY, grid=g), BOUNDS), False)
        d = split(f"{tmp}/nullpos", {"position_x": [1, 2, None], "position_y": [1, 1, None]}, grid=mf._grid(nx=2))
        check("an unpositioned scan (both null) is not a position", found(d, BOUNDS), False)
        # a padded row's null scan struct reads back with null children, whatever the writer's buffers held
        scan = pa.StructArray.from_arrays(
            [pa.array([0, 1, 2, 0, 0], pa.uint64()), pa.array([1, 2, 3, 99, 99], pa.int64()), pa.array([1, 1, 1, 99, 99], pa.int64())],
            names=["source_index", "position_x", "position_y"], mask=pa.array([False] * 3 + [True] * 2))
        packed = mf._meta_packed(n=3, pad=2)
        packed = packed.set_column(packed.schema.get_field_index("scan"), "scan", scan)
        d = f"{tmp}/packed_pad"; mf._write(d, packed, DATA, imaging=IMG, extra_metadata=mf._grid())
        rep = run(d)
        check("packed layout: null-padded scan rows carry no position (and the columns are mapped)",
              [f["message"] for f in rep["findings"] if f["ruleId"] in (BOUNDS, COLS)], False)
        obs = {**IMG, "pixel_count_source": "observed_max"}
        d = split(f"{tmp}/obs_eq", XY, imaging={**obs, "pixel_count": {"x": 3, "y": 1}})
        check("observed_max counts equal to the largest positions -> clean", found(d, BOUNDS), False)
        d = split(f"{tmp}/obs_gt", XY, imaging={**obs, "pixel_count": {"x": 4, "y": 1}}, grid=mf._grid(nx=4))
        check("observed_max count above the largest position -> error", found(d, BOUNDS, level="error"), True,
              "metadata.imaging.pixel_count.x = 4 with pixel_count_source 'observed_max', but the largest position_x "
              "in spectra_metadata_scans is 3")
        check("observed_max without a pixel_count block: nothing to compare",
              found(split(f"{tmp}/obs_none", XY, imaging=obs, grid=mf._grid(nx=4)), BOUNDS), False)

        # --- imaging_length_unit_micrometre: a warning, for a length unit other than micrometre
        def units(d, **by_acc):
            g = mf._grid(pixel_unit=None)
            g["scan_settings_list"][0]["parameters"] += [
                {"accession": a.replace("_", ":"), "name": a, "value": 1.0, **({"unit": u} if u else {})} for a, u in by_acc.items()]
            return split(d, XY, grid=g)
        d = units(f"{tmp}/mm", IMS_1000044="UO:0000016", IMS_1000047="UO:0000017", IMS_1000053="UO:0000015")
        msgs = found(d, UNIT, level="warning")
        check("max dimension in millimetre -> warning", msgs, True, "IMS:1000044 (IMS_1000044) = 1.0 is written in UO:0000016")
        check("absolute position offset in centimetre -> warning", msgs, True, "IMS:1000053")
        check("pixel size y in micrometre -> quiet", msgs, False, "IMS:1000047")
        check("a warning, never an error", found(d, UNIT, level="error"), False)
        check("... index-only: reported under --quick too", found(d, UNIT, quick=True, level="warning"), True)
        d = units(f"{tmp}/sec", IMS_1000047="UO:0000010", IMS_1000045=None)
        check("a non-length unit or no unit is imaging_grid_settings' error, not this warning", found(d, UNIT), False)
        check("... which reports them (and the unit-less pixel size x)",
              [str(len(found(d, "imaging_grid_settings", level="error")))], True, "3")

    print("RESULT:", "PASS" if all(R) else "FAIL", f"({sum(R)}/{len(R)})")
    sys.exit(0 if all(R) else 1)

if __name__ == "__main__":
    main()
