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

def _meta(n=3, total=12, dp=(4, 4, 4), bogus_cv=False, coords=False, extra_footer=None):
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
    kv = {b"spectrum_count": str(n).encode(), b"spectrum_data_point_count": str(total).encode()}
    for k, v in (extra_footer or {}).items():            # extra footer KV blobs (e.g. file_description JSON)
        kv[k.encode() if isinstance(k, str) else k] = v.encode() if isinstance(v, str) else v
    return pa.table({"spectrum": spectrum, "scan": scan}).replace_schema_metadata(kv)

def _data(sidx, mz, inten, inten_type=pa.float32(), mz_type=pa.float64(), mz_sorting_rank="omit", array_index=None):
    point = pa.StructArray.from_arrays(
        [pa.array(sidx, pa.uint64()), pa.array(mz, mz_type), pa.array(inten, inten_type)],
        names=["spectrum_index", "mz", "intensity"])
    kv = {b"spectrum_data_point_count": str(len(sidx)).encode()}
    if array_index is not None:        # full spectrum_array_index (adversarial fixtures)
        kv[b"spectrum_array_index"] = json.dumps(array_index).encode()
    elif mz_sorting_rank != "omit":    # convenience: declare just point.mz's sorting_rank
        kv[b"spectrum_array_index"] = json.dumps({"prefix": "point", "entries": [
            {"path": "point.mz", "array_type": "MS:1000514", "sorting_rank": mz_sorting_rank}]}).encode()
    return pa.table({"point": point}).replace_schema_metadata(kv)

def _chunk_data(n=3):
    """Chunked spectra_data facet (one whole-spectrum m/z chunk per spectrum, numpress-linear). The
    point-layout numeric/count rules self-skip (no `point` facet), so a chunk archive validates clean;
    used to pin that, and that parquet_row_group_health does not false-fire on a tiny single-group file."""
    chunk = pa.StructArray.from_arrays(
        [pa.array(range(n), pa.uint64()), pa.array([100.] * n, pa.float64()), pa.array([400.] * n, pa.float64()),
         pa.array([[100., 200., 300., 400.]] * n, pa.large_list(pa.float64())),
         pa.array(["numpress-linear"] * n, pa.large_string()),
         pa.array([[5., 4., 3., 2.]] * n, pa.large_list(pa.float64()))],
        names=["spectrum_index", "mz_chunk_start", "mz_chunk_end", "mz_chunk_values", "chunk_encoding", "intensity"])
    return pa.table({"chunk": chunk}).replace_schema_metadata({b"spectrum_data_point_count": str(n * 4).encode()})

def _meta_packed(n=3, pad=4, dp=(4, 4, 4)):
    """Packed parallel-facet metadata: n real spectra + `pad` extra rows where spectrum/scan are
    NULL (as a PASEF table padded by a longer precursor facet). footer spectrum_count = n."""
    total_rows = n + pad
    def pad_arr(vals, ty):                      # n real values then `pad` nulls
        return pa.array(list(vals) + [None] * pad, ty)
    spectrum = pa.StructArray.from_arrays(
        [pad_arr(range(n), pa.uint64()), pad_arr([1] * n, pa.uint8()),
         pad_arr(["MS:1000127"] * n, pa.large_string()), pad_arr(dp, pa.uint64())],
        names=["index", "MS_1000511_ms_level", "MS_1000525_spectrum_representation",
               "MS_1003060_number_of_data_points"],
        mask=pa.array([False] * n + [True] * pad))     # struct-level null on the padded rows
    scan = pa.StructArray.from_arrays([pad_arr(range(n), pa.uint64())], names=["source_index"],
                                      mask=pa.array([False] * n + [True] * pad))
    # precursor.source_index must reference a real spectrum (FK to spectrum.index): cycle 0..n-1
    precursor = pa.StructArray.from_arrays([pa.array([i % n for i in range(total_rows)], pa.uint64())], names=["source_index"])
    return pa.table({"spectrum": spectrum, "scan": scan, "precursor": precursor}).replace_schema_metadata(
        {b"spectrum_count": str(n).encode(), b"spectrum_data_point_count": str(sum(dp)).encode()})

_CV_LIST = [   # CVs the fixtures use; versions match the profile's pinned snapshots
    {"id": "MS",  "version": "4.1.254",    "uri": "http://purl.obolibrary.org/obo/ms.obo",        "full_name": "PSI-MS"},
    {"id": "IMS", "version": "1.1.0",      "uri": "http://purl.obolibrary.org/obo/imagingMS.obo", "full_name": "Imaging MS"},
    {"id": "UO",  "version": "2026-01-16", "uri": "http://purl.obolibrary.org/obo/uo.obo",        "full_name": "Unit Ontology"}]

def _write(d, meta, data, extra_files=None, write_data=True, imaging=None, members=None, cv_list=None):
    if os.path.isdir(d): shutil.rmtree(d)
    os.makedirs(d)
    pq.write_table(meta, f"{d}/spectra_metadata.parquet")
    if write_data: pq.write_table(data, f"{d}/spectra_data.parquet")
    for rel, payload in (members or {}).items():          # raw archive members (e.g. images/image_0000.tiff)
        p = os.path.join(d, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(payload)
    files = [{"name": "spectra_metadata.parquet", "entity_type": "spectrum", "data_kind": "metadata"},
             {"name": "spectra_data.parquet", "entity_type": "spectrum", "data_kind": "data arrays"}]
    metadata = {"version": "0.9",
                "cv_list": _CV_LIST if cv_list is None else cv_list,
                "format": {"version": "0.9", "writer": {"name": "make_fixtures", "version": "0"}}}
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

    # (A) packed parallel-facet layout: rows (7) > spectra (3); footer spectrum_count=3 must agree
    # with non-null spectrum.index, not the row count. Regression for the PASEF/TIMS false positive.
    case("pass", "packed_facets_multirow", _meta_packed(n=3, pad=4), _data(S, MZ, IN), "PASS")

    # chunk layout validates clean (point-only rules self-skip); parquet_row_group_health is advisory
    # and must NOT false-fire on this tiny single-row-group file (its 64 MB threshold is far above).
    case("pass", "chunk_layout", _meta(), _chunk_data(), "PASS")

    # (B) L1-faithful float widths now accepted by the relaxed column schema
    case("pass", "float32_mz", _meta(), _data(S, MZ, IN, mz_type=pa.float32()), "PASS")                 # 32-bit m/z (imzML)
    case("pass", "float64_intensity", _meta(), _data(S, MZ, IN, inten_type=pa.float64()), "PASS")       # 64-bit intensity

    # JSON-Schema validation: a footer metadata blob that isn't valid JSON -> error (json_schema primitive)
    case("fail", "bad_file_description_blob", _meta(extra_footer={"file_description": "{ not valid json"}),
         _data(S, MZ, IN), "FAIL", "meta_file_description_valid")

    # per-spectrum count: declared (2,6,4) sums to 12 (== rows, so data_points_sum passes) but spectrum 0
    # declares 2 and actually has 4 -> only the per-spectrum check catches it.
    case("fail", "per_spectrum_count_swapped", _meta(dp=(2, 6, 4)), _data(S, MZ, IN), "FAIL", "per_spectrum_data_points")

    # CV: the archive uses MS codes but metadata.cv_list declares only UO -> cv_list_declared error.
    case("fail", "cv_code_undeclared", _meta(), _data(S, MZ, IN), "FAIL", "cv_list_declared",
         cv_list=[{"id": "UO", "version": "2026-01-16", "uri": "http://purl.obolibrary.org/obo/uo.obo", "full_name": "Unit Ontology"}])

    # CV version policy: a declared CV version NEWER than the profile's pinned snapshot -> warning
    # (the validator is behind; update its bundled CVs), but the file still PASSES. A same-or-older
    # declared version must NOT warn — the default 'pass/valid' fixture (cv_list pinned-exact) covers that.
    case("pass", "cv_version_newer_than_pin", _meta(), _data(S, MZ, IN), "PASS", warn="cv_list_declared",
         cv_list=[{"id": "MS",  "version": "4.1.999",    "uri": "http://purl.obolibrary.org/obo/ms.obo",        "full_name": "PSI-MS"},
                  {"id": "IMS", "version": "1.1.0",      "uri": "http://purl.obolibrary.org/obo/imagingMS.obo", "full_name": "Imaging MS"},
                  {"id": "UO",  "version": "2026-01-16", "uri": "http://purl.obolibrary.org/obo/uo.obo",        "full_name": "Unit Ontology"}])

    # sorting_rank gate: monotonicity is enforced only when the array index declares m/z sorted.
    desc = MZ.copy(); desc[0:4] = [400., 300., 200., 100.]                                              # descending m/z in spectrum 0
    case("pass", "unsorted_mz_declared_unsorted", _meta(), _data(S, desc, IN, mz_sorting_rank=None),    # declared unsorted -> skipped
         "PASS")
    case("fail", "unsorted_mz_declared_sorted", _meta(), _data(S, desc, IN, mz_sorting_rank=0),         # declares sorted but isn't -> FAIL
         "FAIL", "mz_monotonic_data")
    # adversarial: a decoy MS:1000514 entry (for point.intensity, no rank) must NOT suppress the
    # m/z monotonicity gate — declared_sorted matches by path, not array_type (review C2).
    decoy = {"prefix": "point", "entries": [
        {"path": "point.intensity", "array_type": "MS:1000514"},
        {"path": "point.mz", "array_type": "MS:1000514", "sorting_rank": 0}]}
    case("fail", "decoy_array_index_entry", _meta(), _data(S, desc, IN, array_index=decoy), "FAIL", "mz_monotonic_data")

    # adversarial: an image member naming a path outside the archive must be treated as absent
    # (not read) — path containment (review C1). Warns image_member_present; never reads the host file.
    img = {"is_imaging": True, "coordinate_base": 1, "images": [_image_entry(archive_path="../escape.tiff")]}
    case("pass", "image_path_escape", _meta(coords=True), _data(S, MZ, IN), "PASS",
         warn="image_member_present", imaging=img)

    # an embedded optical image listed in files[] as other/other must NOT be Parquet-opened by
    # index_files_present (regression: imaging archives false-failed on the .tif member).
    case("pass", "indexed_optical_image", _meta(coords=True), _data(S, MZ, IN), "PASS",
         imaging={"is_imaging": True, "coordinate_base": 1, "images": [_image_entry()]},
         members={"images/image_0000.tiff": TIFF_BYTES},
         extra_files=[{"name": "images/image_0000.tiff", "entity_type": "other", "data_kind": "other"}])
    # general rule: an indexed non-Parquet member that is not a recognized '*.parquet' facet is an
    # opaque "Other" blob (here entity_type/data_kind "other") and is SKIPPED from the Parquet parse,
    # not opened. The archive validates clean; a declared digest (if any) is checked by the dedicated
    # blob_hash / sample-metadata primitives, not by trying to parse the blob as Parquet.
    case("pass", "indexed_other_blob_skipped", _meta(), _data(S, MZ, IN), "PASS",
         members={"extra.bin": b"not a parquet file"},
         extra_files=[{"name": "extra.bin", "entity_type": "other", "data_kind": "other"}])

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
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "mzpeak_validator", "profiles", "mzpeak-0.9", "fixtures")
    for c in build_all(out): print("wrote", c)
    print("->", out)
