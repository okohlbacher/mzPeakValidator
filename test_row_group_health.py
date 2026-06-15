#!/usr/bin/env python
"""Unit test for the parquet_row_group_health advisory primitive (catalog 1.7).

The bundled rule's threshold is 64 MB, so a tiny fixture can't trip it through the smoke-test
harness. This test drives the primitive directly with a low `min_bytes` to pin the firing logic:
  - chunk layout, ONE row group, size > threshold      -> 1 warning
  - chunk layout, MULTIPLE row groups                  -> no warning (already partitioned)
  - chunk layout, ONE row group, size <= threshold     -> no warning (size gate)
  - point layout (no `chunk` facet)                    -> no warning (facet gate)

Run: python test_row_group_health.py   (exit 0 = pass). Kept out of smoke_test.py because it
needs row-group control that the fixture harness doesn't expose.
"""
import json, os, sys, tempfile
import pyarrow as pa, pyarrow.parquet as pq
from mzpeak_validator.core import Archive, p_parquet_row_group_health

RULE = {"id": "data_row_group_not_monolithic", "primitive": "parquet_row_group_health"}


class _Rep:
    def __init__(self): self.warns = []
    def add(self, rule, level, msg, loc=None, recovery=None):
        if level == "warning":
            self.warns.append(msg)


def _chunk_table(n):
    chunk = pa.StructArray.from_arrays(
        [pa.array(range(n), pa.uint64()),
         pa.array([100.] * n, pa.float64()), pa.array([400.] * n, pa.float64()),
         pa.array([[100., 200., 300., 400.]] * n, pa.large_list(pa.float64())),
         pa.array(["numpress-linear"] * n, pa.large_string()),
         pa.array([[5., 4., 3., 2.]] * n, pa.large_list(pa.float64()))],
        names=["spectrum_index", "mz_chunk_start", "mz_chunk_end", "mz_chunk_values", "chunk_encoding", "intensity"])
    return pa.table({"chunk": chunk})


def _point_table(n):
    point = pa.StructArray.from_arrays(
        [pa.array(range(n), pa.uint64()), pa.array([100.] * n, pa.float64()), pa.array([1.] * n, pa.float32())],
        names=["spectrum_index", "mz", "intensity"])
    return pa.table({"point": point})


def _archive(d, data_table, rg_size=None):
    os.makedirs(d, exist_ok=True)
    meta = pa.table({"spectrum": pa.StructArray.from_arrays([pa.array([0], pa.uint64())], names=["index"])})
    pq.write_table(meta, f"{d}/spectra_metadata.parquet")
    pq.write_table(data_table, f"{d}/spectra_data.parquet", row_group_size=rg_size)
    json.dump({"files": [{"name": "spectra_metadata.parquet", "entity_type": "spectrum", "data_kind": "metadata"},
                         {"name": "spectra_data.parquet", "entity_type": "spectrum", "data_kind": "data arrays"}],
               "metadata": {"version": "0.9"}}, open(f"{d}/mzpeak_index.json", "w"))
    return Archive(d)


def _run(label, data_table, params, rg_size, expect_warn):
    with tempfile.TemporaryDirectory() as tmp:
        ar = _archive(os.path.join(tmp, "a.mzpeak"), data_table, rg_size=rg_size)
        nrg = ar.pf("spectra_data").metadata.num_row_groups
        rep = _Rep()
        p_parquet_row_group_health(ar, RULE, rep, params)
        got = len(rep.warns)
        ok = (got > 0) == expect_warn
        print(f"  [{'ok ' if ok else 'FAIL'}] {label}: row_groups={nrg} warns={got} (expected {'>=1' if expect_warn else '0'})")
        if got and ok and expect_warn:
            print(f"         msg: {rep.warns[0][:110]}")
        return ok


def main():
    print("== parquet_row_group_health unit test ==")
    results = [
        _run("chunk / 1 group / over threshold",  _chunk_table(40), {"min_bytes": 10},        rg_size=None, expect_warn=True),
        _run("chunk / multi group",               _chunk_table(40), {"min_bytes": 10},        rg_size=5,    expect_warn=False),
        _run("chunk / 1 group / under threshold",  _chunk_table(40), {"min_bytes": 10**12},    rg_size=None, expect_warn=False),
        _run("point layout (facet gate)",          _point_table(40), {"min_bytes": 10},        rg_size=None, expect_warn=False),
    ]
    ok = all(results)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
