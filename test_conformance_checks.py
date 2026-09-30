#!/usr/bin/env python
"""Unit test for the catalog-1.16 conformance checks (review 2026-09-30): member_checksum,
cv_terms_exist and the imaging-profile primitives, on the cases the fixture harness cannot express —
a ZIP archive and a deflated member, the --quick size cap, grid_type values, obsolete terms, the
scan-settings footer fallback, value types of the pixel counts, and positions in the split layout or
under packed-layout null padding. Validates through run(), so the engine's param injection is covered.
Run: python test_conformance_checks.py  (exit 0 = pass).
"""
import hashlib, json, os, sys, tempfile, zipfile
import pyarrow as pa, pyarrow.parquet as pq
from mzpeak_validator import run
from mzpeak_validator.core import Archive, p_member_checksum
import make_fixtures as mf

R = []
def check(label, msgs, expect, contains=None):
    """expect True: some finding (containing `contains`, if given); False: none."""
    hit = [m for m in msgs if contains is None or contains in m]
    ok = bool(hit) == expect
    R.append(ok)
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}: {(hit or msgs or ['no findings'])[0][:150]}")

def found(path, rule, quick=False, level=None):
    return [f["message"] for f in run(path, quick=quick)["findings"]
            if f["ruleId"] == rule and (level is None or f["level"] == level)]

def zip_dir(d, deflate=()):
    out = d + ".mzpeak"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for root, _, fns in os.walk(d):
            for fn in sorted(fns):
                rel = os.path.relpath(os.path.join(root, fn), d)
                z.write(os.path.join(root, fn), rel,
                        compress_type=zipfile.ZIP_DEFLATED if rel in deflate else zipfile.ZIP_STORED)
    return out

def edit_index(d, fn):
    p = os.path.join(d, "mzpeak_index.json"); idx = json.load(open(p)); fn(idx); json.dump(idx, open(p, "w"))

def grid_data(grid_type):
    """Chunked spectra_data with a grid-encoded m/z group (chunked-layout.md, Grid encoding)."""
    grid = pa.StructArray.from_arrays(
        [pa.array([grid_type] * 3, pa.large_string()), pa.array([[0.0, 1.0]] * 3, pa.large_list(pa.float64())),
         pa.array([[1, 2, 3, 4]] * 3, pa.large_list(pa.uint32()))], names=["grid_type", "parameters", "indices"])
    chunk = pa.StructArray.from_arrays(
        [pa.array(range(3), pa.uint64()), pa.array([100.] * 3), pa.array([400.] * 3),
         pa.array([[]] * 3, pa.large_list(pa.float64())), pa.array(["MS:1003826"] * 3, pa.large_string()),
         pa.array([[5., 4., 3., 2.]] * 3, pa.large_list(pa.float64())), grid],
        names=["spectrum_index", "mz_chunk_start", "mz_chunk_end", "mz_chunk_values", "chunk_encoding", "intensity", "mz_grid"])
    return pa.table({"chunk": chunk}).replace_schema_metadata({b"spectrum_data_point_count": b"12"})

def main():
    print("== catalog 1.16 conformance checks ==")
    meta, data = mf._meta(), mf._data(mf.S, mf.MZ, mf.IN)
    both = {"spectra_metadata.parquet": None, "spectra_data.parquet": None}
    with tempfile.TemporaryDirectory() as tmp:
        # --- member_checksum: ZIP mode streams the member out of the archive
        d = f"{tmp}/ck_ok"; mf._write(d, meta, data, checksums=both)
        check("checksum, stored ZIP, true digests -> clean", found(zip_dir(d), "member_checksum_sha512"), False)
        d = f"{tmp}/ck_bad"; mf._write(d, meta, data, checksums={**both, "spectra_data.parquet": "ab" * 64})
        z = zip_dir(d)
        check("checksum, stored ZIP, stale digest -> error", found(z, "member_checksum_sha512", level="error"), True,
              "spectra_data.parquet: SHA-512")
        check("checksum under --quick, member below the cap -> still rehashed",
              found(z, "member_checksum_sha512", quick=True, level="error"), True)
        d = f"{tmp}/ck_upper"; mf._write(d, meta, data, checksums=both)
        edit_index(d, lambda idx: [fe.update(checksum=fe["checksum"].upper()) for fe in idx["files"]])
        check("checksum declared in upper case -> matches", found(d, "member_checksum_sha512"), False)
        check("checksum of a deflated member = digest of its content -> clean",
              found(zip_dir(f"{tmp}/ck_ok", deflate=("spectra_data.parquet",)), "member_checksum_sha512"), False)
        # the --quick cap, driven directly with a cap below the member sizes
        class Rep:
            def __init__(self): self.out = []
            def add(self, rule, level, message, location=None, recovery=None, fix=None): self.out.append((level, message))
        ar = Archive(z)
        try:
            rep = Rep(); p_member_checksum(ar, {"id": "t"}, rep, {"_quick": True, "quick_max_bytes": 10})
            check("--quick cap: large members skipped, not flagged", [m for l, m in rep.out if l == "error"], False)
            check("--quick cap: one info counts the skipped members", [m for l, m in rep.out if l == "info"], True,
                  "2 member(s) larger than 10 B")
            rep = Rep(); p_member_checksum(ar, {"id": "t"}, rep, {"_quick": False, "quick_max_bytes": 10})
            check("no --quick: the cap does not apply", [m for l, m in rep.out if l == "error"], True)
        finally:
            ar.cleanup()

        # --- cv_terms_exist
        d = f"{tmp}/grid_bad"; mf._write(d, meta, grid_data("MS:9999002"))
        check("grid_type MS:9999002 -> warning naming CV + versions + column",
              found(d, "cv_terms_exist"), True, "MS:9999002 is not a term of the pinned MS 4.1.257 snapshot "
              "(the archive declares MS 4.1.254); written at spectra_data.parquet:chunk.mz_grid.grid_type")
        check("grid_type values are not read under --quick", found(d, "cv_terms_exist", quick=True), False)
        d = f"{tmp}/grid_ok"; mf._write(d, meta, grid_data("MS:1003824"))
        check("grid_type MS:1003824 (linear grid interpolation) -> clean", found(d, "cv_terms_exist"), False)
        d = f"{tmp}/obsolete"; mf._write(d, meta, data, column_mapping=[
            {"name": "x", "path": "spectrum.MS_1000511_ms_level", "accession": "MS:1000009", "unit": "UO:9999999"},
            {"name": "y", "path": "spectrum.MS_1000511_ms_level", "accession": "BTO:0000001"}])
        msgs = found(d, "cv_terms_exist")
        check("obsolete accession -> 'obsolete in'", msgs, True, "MS:1000009 is obsolete in the pinned MS")
        check("column-mapping unit checked too", msgs, True, "UO:9999999 is not a term of the pinned UO 2026-01-16 snapshot")
        check("a CV the validator does not bundle is skipped", msgs, False, "BTO:")
        d = f"{tmp}/arrayidx"; mf._write(d, meta, mf._data(mf.S, mf.MZ, mf.IN, array_index={"prefix": "point", "entries": [
            {"array_name": "m/z array", "buffer_format": "point", "context": "spectrum", "path": "point.mz",
             "data_type": "MS:1000523", "array_type": "MS:1000514", "unit": "MS:9999040"}]}))
        check("array-index unit in a Parquet footer", found(d, "cv_terms_exist"), True,
              "written at spectra_data.parquet:spectrum_array_index.entries[0].unit")
        spec = meta.column("spectrum").combine_chunks()
        marked = pa.table({"spectrum": pa.StructArray.from_arrays(
            spec.flatten() + [pa.array(["MS:1000294", "MS:9999003", None], pa.large_string())],
            names=[f.name for f in spec.type] + ["spectrum_type"]), "scan": meta.column("scan")}
        ).replace_schema_metadata(meta.schema.metadata)
        d = f"{tmp}/marker"; mf._write(d, marked, data, column_mapping=[
            {"name": "spectrum type", "path": "spectrum.spectrum_type", "accession": "MS:1000559", "term_marker": True}])
        check("string term-marker value absent from MS -> warning", found(d, "cv_terms_exist"), True,
              "MS:9999003 is not a term of the pinned MS 4.1.257 snapshot")
        check("term-marker values are not read under --quick", found(d, "cv_terms_exist", quick=True), False)

        # --- imaging_grid: footer fallback and the value type of the pixel counts
        img = {"is_imaging": True, "coordinate_base": 1}
        ssl = mf._grid()["scan_settings_list"]
        d = f"{tmp}/grid_footer"
        mf._write(d, mf._meta(coords=True, extra_footer={"scan_settings_list": json.dumps(ssl)}), data, imaging=img)
        check("scan settings only in the spectra_metadata footer -> used", found(d, "imaging_grid_settings"), False)
        for label, value, expect in [("3.0", 3.0, False), ('"3"', "3", True), ("true", True, True)]:
            g = mf._grid(); g["scan_settings_list"][0]["parameters"][0]["value"] = value
            d = f"{tmp}/count_{len(R)}"; mf._write(d, mf._meta(coords=True), data, imaging=img, extra_metadata=g)
            check(f"IMS:1000042 value {label} -> {'finding' if expect else 'accepted'}",
                  found(d, "imaging_grid_settings"), expect, "not an integer >= 1" if expect else None)

        # --- imaging_position_pairs: split layout, and packed-layout null padding
        scans = pa.table({"source_index": pa.array(range(3), pa.uint64()),
                          "position_x": pa.array([1, 2, 3], pa.int32()), "position_y": pa.array([1, 1, None], pa.int32())})
        d = f"{tmp}/split_half"; mf._write_split(d, mf._split_meta_flat(), scans, data, "FAIL")
        check("split layout: half-set row in spectra_metadata_scans", found(d, "imaging_positions_paired"), True,
              "spectra_metadata_scans: 1 row(s) set only one of position_x / position_y, first at row 2")
        # a padded row's null scan struct reads back with null children, whatever the writer's buffers held
        scan = pa.StructArray.from_arrays(
            [pa.array([0, 1, 2, 0, 0], pa.uint64()), pa.array([1, 2, 3, 0, 0], pa.int64()), pa.array([1, 1, 1, 0, 0], pa.int64())],
            names=["source_index", "position_x", "position_y"], mask=pa.array([False] * 3 + [True] * 2))
        packed = mf._meta_packed(n=3, pad=2)
        packed = packed.set_column(packed.schema.get_field_index("scan"), "scan", scan)
        d = f"{tmp}/packed_pad"; mf._write(d, packed, data, imaging=img, extra_metadata=mf._grid())
        rep = run(d)
        check("packed layout: null-padded scan rows are unpositioned, not half-set or 0",
              [f["message"] for f in rep["findings"] if f["ruleId"] in ("imaging_positions_paired", "imaging_coordinates_1based")], False)

    print("RESULT:", "PASS" if all(R) else "FAIL", f"({sum(R)}/{len(R)})")
    sys.exit(0 if all(R) else 1)

if __name__ == "__main__":
    main()
