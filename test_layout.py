#!/usr/bin/env python
"""Unit test for the Phase 3 / Phase 6 layout primitives (catalog 1.10): chunk_bounds, aux_arrays,
zip_stored, column_order. These are awkward to fixture through the dir-based harness (zip_stored needs
a real ZIP with a compressed member; chunk_bounds needs multi-chunk groups), so they are pinned here
with constructed archives. Run: python test_layout.py  (exit 0 = pass).
"""
import json, os, sys, tempfile, zipfile
import pyarrow as pa, pyarrow.parquet as pq
from mzpeak_validator.core import Archive, p_chunk_bounds, p_aux_arrays, p_zip_stored, p_column_order

class Rep:
    def __init__(self): self.msgs = []
    def add(self, rule, level, message, location=None, recovery=None, fix=None):
        self.msgs.append((level, message))

def _dir_archive(d, tables, extra_files=None):
    os.makedirs(d, exist_ok=True)
    files = []
    for name, tbl in tables.items():
        pq.write_table(tbl, f"{d}/{name}.parquet")
        files.append({"name": f"{name}.parquet", "entity_type": "spectrum", "data_kind": "data arrays"})
    json.dump({"files": files + (extra_files or []), "metadata": {"version": "0.9"}},
              open(f"{d}/mzpeak_index.json", "w"))
    return Archive(d)

def _chunk(spec_idx, starts, ends):
    return pa.table({"chunk": pa.StructArray.from_arrays(
        [pa.array(spec_idx, pa.uint64()), pa.array(starts, pa.float64()), pa.array(ends, pa.float64())],
        names=["spectrum_index", "mz_chunk_start", "mz_chunk_end"])})

R = []
def check(label, got, expect):
    ok = (got > 0) == expect
    R.append(ok)
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}: findings={got} (expect {'>=1' if expect else '0'})")

BOUNDS = {"file": "spectra_data", "group": "chunk.spectrum_index",
          "start_column": "chunk.mz_chunk_start", "end_column": "chunk.mz_chunk_end"}

def main():
    print("== layout primitives unit test ==")
    with tempfile.TemporaryDirectory() as tmp:
        # chunk_bounds — ok: two ascending non-overlapping chunks in spectrum 0
        ar = _dir_archive(f"{tmp}/ok", {"spectra_data": _chunk([0, 0], [100., 200.], [200., 300.])})
        rep = Rep(); p_chunk_bounds(ar, {"id": "t", "severity": "warning"}, rep, BOUNDS)
        check("chunk_bounds ascending non-overlapping -> clean", len(rep.msgs), False)
        # overlap: next start 150 < prev end 200
        ar = _dir_archive(f"{tmp}/ov", {"spectra_data": _chunk([0, 0], [100., 150.], [200., 300.])})
        rep = Rep(); p_chunk_bounds(ar, {"id": "t", "severity": "warning"}, rep, BOUNDS)
        check("chunk_bounds overlap -> finding", len(rep.msgs), True)
        # start > end
        ar = _dir_archive(f"{tmp}/se", {"spectra_data": _chunk([0], [300.], [100.])})
        rep = Rep(); p_chunk_bounds(ar, {"id": "t", "severity": "warning"}, rep, BOUNDS)
        check("chunk_bounds start>end -> finding", len(rep.msgs), True)
        # different spectra never overlap each other (group isolation)
        ar = _dir_archive(f"{tmp}/grp", {"spectra_data": _chunk([0, 1], [200., 100.], [300., 200.])})
        rep = Rep(); p_chunk_bounds(ar, {"id": "t", "severity": "warning"}, rep, BOUNDS)
        check("chunk_bounds cross-group not flagged -> clean", len(rep.msgs), False)

        # aux_arrays
        def aux_tbl(counts, lists):
            return pa.table({"spectrum": pa.StructArray.from_arrays(
                [pa.array(counts, pa.uint64()), pa.array(lists, pa.large_list(pa.int64()))],
                names=["number_of_auxiliary_arrays", "auxiliary_arrays"])})
        AUX = {"file": "spectra_metadata", "count_column": "spectrum.number_of_auxiliary_arrays",
               "list_column": "spectrum.auxiliary_arrays"}
        ar = _dir_archive(f"{tmp}/auxok", {"spectra_metadata": aux_tbl([2, 0], [[1, 2], []])})
        rep = Rep(); p_aux_arrays(ar, {"id": "t", "severity": "error"}, rep, AUX)
        check("aux_arrays count matches -> clean", len(rep.msgs), False)
        ar = _dir_archive(f"{tmp}/auxbad", {"spectra_metadata": aux_tbl([2, 0], [[1], []])})
        rep = Rep(); p_aux_arrays(ar, {"id": "t", "severity": "error"}, rep, AUX)
        check("aux_arrays count mismatch -> finding", len(rep.msgs), True)

        # column_order
        ORD = {"file": "spectra_metadata", "expected": {"spectrum": "index"}}
        good = pa.table({"spectrum": pa.StructArray.from_arrays(
            [pa.array([0], pa.uint64()), pa.array([1], pa.uint8())], names=["index", "x"])})
        bad = pa.table({"spectrum": pa.StructArray.from_arrays(
            [pa.array([1], pa.uint8()), pa.array([0], pa.uint64())], names=["x", "index"])})
        ar = _dir_archive(f"{tmp}/ordok", {"spectra_metadata": good})
        rep = Rep(); p_column_order(ar, {"id": "t", "severity": "warning"}, rep, ORD)
        check("column_order index-first -> clean", len(rep.msgs), False)
        ar = _dir_archive(f"{tmp}/ordbad", {"spectra_metadata": bad})
        rep = Rep(); p_column_order(ar, {"id": "t", "severity": "warning"}, rep, ORD)
        check("column_order index-not-first -> finding", len(rep.msgs), True)

        # zip_stored — build a .mzpeak zip with one STORED and one DEFLATE member
        tbl = _chunk([0], [100.], [200.])
        pq.write_table(tbl, f"{tmp}/sd.parquet")
        idx = json.dumps({"files": [{"name": "spectra_data.parquet", "entity_type": "spectrum", "data_kind": "data arrays"}],
                          "metadata": {"version": "0.9"}}).encode()
        zp = f"{tmp}/stored.mzpeak"
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("mzpeak_index.json", idx, compress_type=zipfile.ZIP_STORED)
            z.write(f"{tmp}/sd.parquet", "spectra_data.parquet", compress_type=zipfile.ZIP_STORED)
        ar = Archive(zp); rep = Rep(); p_zip_stored(ar, {"id": "t", "severity": "error"}, rep, {}); ar.cleanup()
        check("zip_stored all stored -> clean", len(rep.msgs), False)
        zp2 = f"{tmp}/deflated.mzpeak"
        with zipfile.ZipFile(zp2, "w") as z:
            z.writestr("mzpeak_index.json", idx, compress_type=zipfile.ZIP_STORED)
            z.write(f"{tmp}/sd.parquet", "spectra_data.parquet", compress_type=zipfile.ZIP_DEFLATED)
        ar = Archive(zp2); rep = Rep(); p_zip_stored(ar, {"id": "t", "severity": "error"}, rep, {}); ar.cleanup()
        check("zip_stored deflated member -> finding", len(rep.msgs), True)

    ok = all(R)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
