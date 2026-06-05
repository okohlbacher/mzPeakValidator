#!/usr/bin/env python3
"""Generate tiny mzPeak conformance fixtures (one broken rule per fail case).

`build_all(out_root)` writes unpacked-directory archives under out_root/{pass,fail}/,
each with a sibling expected.json: {"verdict": "...", "rule": "..."}.
Point layout, 3 spectra x 4 points. Used by smoke_test.py (into a temp dir);
run directly to materialise them for inspection.
"""
import hashlib, json, os, shutil
import pyarrow as pa, pyarrow.parquet as pq

# base valid data: 3 spectra x 4 points, mz sorted ascending, intensity >= 0
S = [0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2]
MZ = [100., 200., 300., 400.] * 3
IN = [5., 4., 3., 2.] * 3

# a minimal "TIFF": only the first 4 bytes (the magic) are inspected by the validator
TIFF_BYTES = b"II*\x00" + bytes(12)
NOT_TIFF_BYTES = b"NOT-A-TIFF!!" + bytes(4)

def _meta(n=3, total=12, dp=(4, 4, 4), bogus_cv=False, coords=False):
    cols = [pa.array(range(n), pa.uint64()), pa.array([1] * n, pa.uint8()),
            pa.array(["MS:1000127"] * n, pa.large_string()), pa.array(list(dp), pa.uint64())]
    names = ["index", "MS_1000511_ms_level", "MS_1000525_spectrum_representation", "MS_1003060_number_of_data_points"]
    if bogus_cv:
        cols.append(pa.array([0] * n, pa.uint64())); names.append("XX_1234567_bogus")
    spectrum = pa.StructArray.from_arrays(cols, names=names)
    scols, snames = [pa.array(range(n), pa.uint64())], ["source_index"]
    if coords:                                            # promoted 1-based imaging coordinates on the scan facet
        scols += [pa.array(range(1, n + 1), pa.int64()), pa.array([1] * n, pa.int64())]
        snames += ["IMS_1000050_position_x", "IMS_1000051_position_y"]
    scan = pa.StructArray.from_arrays(scols, names=snames)
    return pa.table({"spectrum": spectrum, "scan": scan}).replace_schema_metadata(
        {b"spectrum_count": str(n).encode(), b"spectrum_data_point_count": str(total).encode()})

def _data(sidx, mz, inten, inten_type=pa.float32()):
    point = pa.StructArray.from_arrays(
        [pa.array(sidx, pa.uint64()), pa.array(mz, pa.float64()), pa.array(inten, inten_type)],
        names=["spectrum_index", "mz", "intensity"])
    return pa.table({"point": point}).replace_schema_metadata(
        {b"spectrum_data_point_count": str(len(sidx)).encode()})

def _write(d, meta, data, extra_files=None, write_data=True, imaging=None, members=None):
    if os.path.isdir(d): shutil.rmtree(d)
    os.makedirs(d)
    pq.write_table(meta, f"{d}/spectra_metadata.parquet")
    if write_data: pq.write_table(data, f"{d}/spectra_data.parquet")
    for rel, payload in (members or {}).items():          # raw archive members (e.g. images/image_0000.tiff)
        p = os.path.join(d, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(payload)
    files = [{"name": "spectra_metadata.parquet", "entity_type": "spectrum", "data_kind": "metadata"},
             {"name": "spectra_data.parquet", "entity_type": "spectrum", "data_kind": "data arrays"}]
    metadata = {"format": {"version": "0.9", "writer": {"name": "make_fixtures", "version": "0"}}}
    if imaging is not None: metadata["imaging"] = imaging
    json.dump({"files": files + (extra_files or []), "metadata": metadata},
              open(f"{d}/mzpeak_index.json", "w"), indent=1)

def _image_entry(archive_path="images/image_0000.tiff", payload=TIFF_BYTES, sha256=None,
                 size_bytes=None, media_type="image/tiff"):
    return {"archive_path": archive_path, "source_name": os.path.basename(archive_path),
            "media_type": media_type, "width": 1, "height": 1,
            "sha256": sha256 if sha256 is not None else hashlib.sha256(payload).hexdigest(),
            "size_bytes": size_bytes if size_bytes is not None else len(payload)}

def build_all(out_root):
    cases = []
    def case(group, name, meta, data, verdict, rule=None, warn=None, **kw):
        d = os.path.join(out_root, group, name); _write(d, meta, data, **kw)
        json.dump({"verdict": verdict, "rule": rule, "warn_rule": warn}, open(f"{d}/expected.json", "w"))
        cases.append(f"{group}/{name}")

    case("pass", "valid", _meta(), _data(S, MZ, IN), "PASS")

    neg = IN.copy(); neg[5] = -1.0
    case("fail", "negative_intensity", _meta(), _data(S, MZ, neg), "FAIL", "intensity_nonneg_data")
    uns = MZ.copy(); uns[0:4] = [400., 300., 200., 100.]
    case("fail", "unsorted_mz", _meta(), _data(S, uns, IN), "FAIL", "mz_monotonic_data")
    case("fail", "bad_point_count", _meta(dp=(4, 4, 99)), _data(S, MZ, IN), "FAIL", "data_points_sum")
    fk = S.copy(); fk[0] = 99
    case("fail", "dangling_fk", _meta(), _data(fk, MZ, IN), "FAIL", "point_fk_data")
    case("fail", "int_intensity", _meta(), _data(S, MZ, [5, 4, 3, 2] * 3, inten_type=pa.int32()), "FAIL", "intensity_dtype_data")
    case("fail", "unknown_cv_code", _meta(bogus_cv=True), _data(S, MZ, IN), "FAIL", "cv_inflection_spectra_metadata")
    case("fail", "missing_indexed_file", _meta(), _data(S, MZ, IN), "FAIL", "index_files_present",
         extra_files=[{"name": "spectra_peaks.parquet", "entity_type": "spectrum", "data_kind": "peaks"}])

    # regression fixtures for the adversarial-review findings
    case("fail", "interleaved_unsorted_mz", _meta(n=2, total=4, dp=(2, 2)),
         _data([0, 1, 0, 1], [100., 500., 90., 600.], [5., 5., 5., 5.]), "FAIL", "mz_monotonic_data")  # C1: non-contiguous group
    nan = MZ.copy(); nan[2] = float("nan")
    case("fail", "nan_mz", _meta(), _data(S, nan, IN), "FAIL", "mz_finite_data")                        # C2: NaN VALUE invalid (null is fine)
    blob = pa.table({"blob": pa.array([1, 2, 3], pa.int64())}).replace_schema_metadata({b"spectrum_data_point_count": b"3"})
    case("fail", "garbage_data_facet", _meta(), blob, "FAIL", "data_kind_has_facet")                    # M1: no point/chunk facet

    # imaging archive with an embedded optical TIFF — exercises the image-member primitives (warning-level)
    imeta, idata = _meta(coords=True), _data(S, MZ, IN)
    img = {"is_imaging": True, "coordinate_base": 1}
    case("pass", "imaging_with_optical_image", imeta, idata, "PASS",
         imaging={**img, "images": [_image_entry()]}, members={"images/image_0000.tiff": TIFF_BYTES})
    case("pass", "imaging_missing_image", imeta, idata, "PASS", warn="image_member_present",
         imaging={**img, "images": [_image_entry()]})                                                   # declared, not written
    case("pass", "imaging_image_hash_mismatch", imeta, idata, "PASS", warn="image_blob_hash",
         imaging={**img, "images": [_image_entry(sha256="0" * 64)]}, members={"images/image_0000.tiff": TIFF_BYTES})
    case("pass", "imaging_image_not_tiff", imeta, idata, "PASS", warn="image_tiff_magic",
         imaging={**img, "images": [_image_entry(payload=NOT_TIFF_BYTES)]},
         members={"images/image_0000.tiff": NOT_TIFF_BYTES})                                            # bytes match hash; only magic trips
    return cases

if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "profiles", "mzpeak-0.9", "fixtures")
    for c in build_all(out): print("wrote", c)
    print("->", out)
