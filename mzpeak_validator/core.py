#!/usr/bin/env python3
"""
mzPeakValidator — a first, language-independent-by-design validator for mzPeak.

Loads a versioned *validation profile* (schemas + pinned CV snapshots + a
declarative rule set) and runs it against an mzPeak archive (.mzpeak ZIP or an
unpacked directory). Rules are data; this engine implements the rule-primitive
catalog. See docs/mzpeak-validation-design.md.

Profile selection: --profile wins; else the archive's
`mzpeak_index.json.metadata.format.version` selects `profiles/mzpeak-<version>`;
else (no/unknown version) the latest known profile is used (with a warning).

Usage (installed console script, or `python -m mzpeak_validator`):
    mzpeak-validate <archive> [--profile DIR] [--profiles-dir DIR]
                    [--json report.json] [--log findings.log] [--quick]

Exit: 0 if no errors, 1 if any error-level finding, 2 on engine failure.
"""
import argparse, gzip, hashlib, json, re, sys, tempfile, zipfile
from pathlib import Path

try:
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyarrow.compute as pc
except Exception as e:                                          # pragma: no cover
    print("ERROR: pyarrow and numpy are required (pip install pyarrow numpy):", e, file=sys.stderr)
    sys.exit(2)

# Build an offline JSON-Schema validator with a $ref store and a CURIE format checker.
# jsonschema 4.18+ replaced RefResolver with the `referencing` library;
# support both so the code runs on jsonschema 3–4+.
_CURIE_FC = None
def _get_fc():
    global _CURIE_FC
    if _CURIE_FC is None:
        import jsonschema
        fc = jsonschema.FormatChecker()
        # The built-in "curie" checker uses the strict W3C CURIE spec and rejects valid mzPeak
        # CV terms like "MS:1000514" (numeric local part). Replace it with the permissive
        # namespace:local check that matches the spec's own pattern constraint.
        fc.checkers.pop("curie", None)
        @fc.checks("curie", raises=ValueError)
        def _(v):
            if isinstance(v, str) and not re.match(r"^\S+:\S+$", v):
                raise ValueError(v)
            return True
        _CURIE_FC = fc
    return _CURIE_FC

try:
    import referencing as _ref, referencing.jsonschema as _rjsc
    def _schema_validator(schema, store):
        resources = [(u, _rjsc.DRAFT7.create_resource(s)) for u, s in store.items()]
        return __import__("jsonschema").Draft7Validator(
            schema, registry=_ref.Registry().with_resources(resources),
            format_checker=_get_fc())
except ImportError:                                             # jsonschema < 4.18
    def _schema_validator(schema, store):
        import jsonschema
        return jsonschema.Draft7Validator(
            schema, resolver=jsonschema.RefResolver("", schema, store=store),
            format_checker=_get_fc())

CATALOG_VERSION = "1.10"         # 1.1: image primitives; 1.2: list types + footer count_column; 1.3: grouped_monotonic gated on declared sorting_rank; 1.4: json_schema + grouped_count_equals; 1.5: cv_list cv-CURIE resolution; 1.6: cv_list version warning fires only when declared CV is NEWER than the pinned snapshot (update-needed), not on any difference; 1.7: parquet_row_group_health (advisory perf warning: chunked data facet in one monolithic row group); 1.8: cv_mapping (PSI CvMapping term-placement, MUST/SHOULD/AND/OR/XOR + allow_children + cardinality; consumes the spec's table_rules.json; advisory severity in Phase 1) + finding 'fix' tips; 1.9: cv_mapping_json (CvMapping placement over the JSON index metadata — wires the spec's semantic_rules.json: file_description/instrument-config/software/data_processing params); 1.10: Phase 3 chunk layout (chunk_columns, chunk_bounds = start<=end + non-overlapping ascending chunks per group, aux_arrays count) + Phase 6 container MUSTs (zip_stored uncompressed members, column_order key-first) + Phase 4 chromatogram entity rules
PROFILES_ROOT = Path(__file__).parent / "profiles"
MAX_PER_RULE = 25                       # cap distinct findings per rule, then summarise the remainder
_SUMMARY_RULE = {"id": "archive_summary", "primitive": "archive_summary", "recovery": "none"}
BATCH_SIZE = 1 << 17                    # 131072 rows/batch for streaming reads; ~1 MB per scalar column per batch

# ------------------------------------------------------------------------ archive
class Archive:
    """An mzPeak archive (zip or directory) exposing files, parquet schemas and columns."""
    def __init__(self, path):
        self.path = Path(path)
        self._tmp = None
        self._pf, self._col = {}, {}
        try:                                          # any failure after mkdtemp must not leak the tempdir
            if self.path.is_dir():
                self.root = self.path
            else:
                self._tmp = tempfile.mkdtemp(prefix="mzpeak_val_")
                with zipfile.ZipFile(self.path) as z:
                    comp = sum(i.compress_size for i in z.infolist())
                    uncomp = sum(i.file_size for i in z.infolist())
                    # mzPeak MUST store members uncompressed (ratio ~1); a large, highly-inflating
                    # archive is a zip bomb, not a conformant file — refuse before extracting.
                    if uncomp > 100_000_000 and comp and uncomp / comp > 50:
                        raise ValueError(f"refusing to extract: {uncomp} bytes uncompressed vs {comp} "
                                         f"compressed ({uncomp / comp:.0f}x) — mzPeak members must be stored uncompressed")
                    z.extractall(self._tmp)
                self.root = Path(self._tmp)
            idx = self.root / "mzpeak_index.json"
            self._index_utf8_error = False
            if idx.exists():
                raw = idx.read_bytes()
                try:
                    self.index = json.loads(raw.decode("utf-8"))
                except UnicodeDecodeError:
                    self._index_utf8_error = True
                    self.index = json.loads(raw.decode("utf-8", errors="replace"))
            else:
                self.index = None
        except BaseException:
            self.cleanup()
            raise

    def cleanup(self):
        if self._tmp:
            import shutil; shutil.rmtree(self._tmp, ignore_errors=True)

    def _contained(self, rel):
        """Resolve an archive-relative path, refusing escapes (absolute, '..', symlink) — names come
        from the untrusted index, so a member must not be able to address files outside the archive."""
        if not rel:
            return None
        root = self.root.resolve()
        full = (self.root / rel).resolve()
        try:
            full.relative_to(root)
        except ValueError:
            return None
        return full

    def _is_file(self, rel):
        full = self._contained(rel)
        return full is not None and full.is_file()

    def _fname(self, name):
        """Resolve a logical table name to a contained file ('spectra_data' -> 'spectra_data.parquet')."""
        if name.endswith(".parquet") and self._is_file(name):
            return name
        if self._is_file(name + ".parquet"):
            return name + ".parquet"
        return name

    def has_file(self, name):
        return self._is_file(self._fname(name))

    def has_member(self, name):
        """Is `name` a present, archive-contained raw member (not parquet-resolved)?"""
        return self._is_file(name)

    def read_member(self, name, n=None):
        """Raw bytes of an archive-contained member (first `n` bytes if given)."""
        full = self._contained(name)
        if full is None:
            raise ValueError(f"refusing to read member outside the archive: {name!r}")
        with open(full, "rb") as fh:
            return fh.read() if n is None else fh.read(n)

    def pf(self, name):
        fn = self._fname(name)
        if fn not in self._pf:
            self._pf[fn] = pq.ParquetFile(self.root / fn)
        return self._pf[fn]

    def num_rows(self, name):
        return self.pf(name).metadata.num_rows

    def footer(self, name, key):
        v = (self.pf(name).metadata.metadata or {}).get(key.encode())
        return v.decode(errors="replace") if v is not None else None

    def fields(self, name):
        """Flat name -> arrow type string, walking two levels of struct."""
        out = {}
        for top in self.pf(name).schema_arrow:
            if pa.types.is_struct(top.type):
                for sub in top.type:
                    out[f"{top.name}.{sub.name}"] = str(sub.type)
            else:
                out[top.name] = str(top.type)
        return out

    def column(self, name, dotted):
        """Load a (<= 2-level) column as a flat pyarrow Array, cached.
        Top-level struct is cached under (name, top) so multiple sub-field accesses
        (e.g. chunk.mz_chunk_start then chunk.intensity_chunk_start) read the file once."""
        if (name, dotted) not in self._col:
            top = dotted.split(".", 1)[0]
            top_key = (name, top)
            if top_key not in self._col:
                self._col[top_key] = pq.read_table(
                    self.root / self._fname(name), columns=[top]
                ).column(top).combine_chunks()
            col = self._col[top_key]
            self._col[(name, dotted)] = col.field(dotted.split(".", 1)[1]) if "." in dotted else col
        return self._col[(name, dotted)]

    def iter_batches(self, name, *dotted_cols, batch_size=None):
        """Stream the requested columns as fixed-size row batches without caching.
        Each yield is a tuple of pyarrow Arrays, one per requested dotted column.
        Passes dotted paths directly to PyArrow so only the requested struct sub-fields
        are read — unused sub-fields (e.g. point.intensity, chunk.mz_chunk_list) are skipped."""
        if not dotted_cols:
            return
        for batch in self.pf(name).iter_batches(
                batch_size=batch_size or BATCH_SIZE, columns=list(dotted_cols)):
            yield tuple(
                batch.column(d.split(".", 1)[0]).field(d.split(".", 1)[1])
                if "." in d else batch.column(d)
                for d in dotted_cols
            )

def arrow_logical(tystr):
    s = tystr.lower()
    if "list" in s: return "list"          # containers first: a list<double>/struct<…> is not a scalar
    if "struct" in s: return "struct"
    if "double" in s: return "double"
    if "float" in s: return "float"
    if "string" in s: return "string"
    if s == "bool": return "bool"
    if s.startswith("uint"): return "uint"
    if s.startswith("int"): return "int"
    return s

def type_ok(got, want):
    return want == got or (want == "integer" and got in ("int", "uint"))

def type_matches(got, want):
    """`want` is a single logical type or a list of accepted ones (e.g. ['double','float'])."""
    wants = want if isinstance(want, list) else [want]
    return any(type_ok(got, w) for w in wants)

def has(ar, name, dotted):
    return ar.has_file(name) and dotted in ar.fields(name)

def _fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024

def _archive_info(ar):
    """Collect Parquet footer metadata (rows, sizes, encodings). Footer-only — always fast."""
    idx_files = {}
    for f in ((ar.index or {}).get("files") or []):
        n = f.get("name", "")
        idx_files[n] = f
        if n.endswith(".parquet"):
            idx_files[n[:-8]] = f

    candidates = ["spectra_metadata", "spectra_data", "spectra_peaks",
                  "chromatograms_metadata", "chromatograms_data"]
    for n in list(idx_files):
        base = n[:-8] if n.endswith(".parquet") else n
        if base not in candidates:
            candidates.append(base)

    result = []
    for name in candidates:
        if not ar.has_file(name):
            continue
        try:
            meta = ar.pf(name).metadata
        except Exception:
            continue
        idx_entry = idx_files.get(name) or {}

        # Leaf-column counts from row group 0 (schema is static across row groups)
        leaf_counts = {}
        if meta.num_row_groups > 0:
            rg0 = meta.row_group(0)
            for ci in range(rg0.num_columns):
                top = rg0.column(ci).path_in_schema.split(".")[0]
                leaf_counts[top] = leaf_counts.get(top, 0) + 1

        # Aggregate encodings and sizes across all row groups
        facet_data = {}
        for rgi in range(meta.num_row_groups):
            rg = meta.row_group(rgi)
            for ci in range(rg.num_columns):
                cc = rg.column(ci)
                top = cc.path_in_schema.split(".")[0]
                if top not in facet_data:
                    facet_data[top] = {"encodings": set(), "compression": cc.compression,
                                       "compressed_bytes": 0, "uncompressed_bytes": 0}
                for e in (cc.encodings or []):
                    s = str(e)
                    facet_data[top]["encodings"].add(s.split(".")[-1] if "." in s else s)
                facet_data[top]["compressed_bytes"] += cc.total_compressed_size
                facet_data[top]["uncompressed_bytes"] += cc.total_uncompressed_size

        file_size = (ar.root / ar._fname(name)).stat().st_size
        result.append({
            "name": name,
            "entity_type": idx_entry.get("entity_type"),
            "data_kind": idx_entry.get("data_kind"),
            "rows": meta.num_rows,
            "row_groups": meta.num_row_groups,
            "file_bytes": file_size,
            "compressed_bytes": sum(v["compressed_bytes"] for v in facet_data.values()),
            "uncompressed_bytes": sum(v["uncompressed_bytes"] for v in facet_data.values()),
            "facets": [
                {"name": top,
                 "leaf_columns": leaf_counts.get(top, 0),
                 "compression": d["compression"],
                 "encodings": sorted(d["encodings"]),
                 "compressed_bytes": d["compressed_bytes"],
                 "uncompressed_bytes": d["uncompressed_bytes"]}
                for top, d in facet_data.items()
            ],
        })
    return result

# --------------------------------------------------------------- profile resolution
def _vkey(v):
    return [int(x) for x in re.findall(r"\d+", str(v))] or [0]

def discover_profiles(root):
    return {d.name[len("mzpeak-"):]: d for d in Path(root).glob("mzpeak-*")
            if d.is_dir() and (d / "profile.json").is_file()}

def _dict(v):
    return v if isinstance(v, dict) else {}

def declared_version(archive):
    md = _dict((archive.index or {}).get("metadata"))
    # current spec puts the archive version at metadata.version; accept the legacy
    # metadata.format.version too (the field moved when the spec formalised it).
    v = md.get("version")
    if v is None:
        v = _dict(md.get("format")).get("version")
    return str(v) if v is not None else None

def resolve_profile(archive, root, explicit=None):
    """Return (profile_dir, note). explicit > declared version > latest known."""
    if explicit:
        return Path(explicit), None
    profs = discover_profiles(root)
    if not profs:
        raise FileNotFoundError(f"no profiles found under {root}")
    latest = profs[max(profs, key=_vkey)]
    v = declared_version(archive)
    if v is None:
        return latest, f"no mzpeak version declared; defaulted to latest profile (mzpeak-{latest.name[len('mzpeak-'):]})"
    if v in profs:
        return profs[v], None
    # Semver-tolerant match: a declared patch version (e.g. "0.9.0") resolves to the profile keyed
    # on its major.minor ("mzpeak-0.9"). The converter declares the spec's full "0.9.0" while
    # profiles are keyed major.minor — without this an exact-key miss spuriously warned + defaulted.
    vk = _vkey(v)[:2]
    for key, prof_dir in profs.items():
        if _vkey(key)[:2] == vk:
            return prof_dir, None
    return latest, f"declared version {v!r} has no profile; defaulted to latest (mzpeak-{latest.name[len('mzpeak-'):]})"

class Profile:
    def __init__(self, root):
        self.root = Path(root)
        self.manifest = json.loads((self.root / "profile.json").read_text())
        self.rules = []
        for rf in sorted((self.root / "rules").glob("*.rules.json")):
            self.rules += json.loads(rf.read_text())["rules"]
        self.columns = {}
        for cf in sorted((self.root / "schema" / "tables").glob("*.columns.json")):
            spec = json.loads(cf.read_text()); self.columns[spec["file"]] = spec
        self.json_schemas = {}
        jdir = self.root / "schema" / "json"
        if jdir.is_dir():
            for jf in sorted(jdir.glob("*.json")):
                self.json_schemas[jf.stem] = json.loads(jf.read_text())
        # Map remote HUPO-PSI schema URLs to local bundled copies so $ref resolution
        # works offline with any jsonschema version (see _schema_validator).
        _base = "https://raw.githubusercontent.com/HUPO-PSI/mzPeak-specification/refs/heads/main/schema/"
        self._json_schema_store = {_base + stem + ".json": s for stem, s in self.json_schemas.items()}
        self.cv = self._load_cv()                 # also sets self.cv_isa (is_a graph)
        self.mappings = {art["path"]: json.loads((self.root / art["path"]).read_text())
                         for art in self.manifest.get("artifacts", []) if art.get("role") == "cv_mapping"}

    def _load_cv(self):
        cv, isa = {}, {}                          # isa: merged child_acc -> {parent_acc} for allow_children
        for art in self.manifest.get("artifacts", []):
            if art.get("role") != "cv":
                continue
            p = self.root / art["path"]
            opener = gzip.open if str(p).endswith(".gz") else open
            accs, cur, obs = set(), None, False
            with opener(p, "rt", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.startswith("[Term]"):
                        if cur and not obs: accs.add(cur)
                        cur, obs = None, False
                    elif line.startswith("id:"):
                        cur = line[3:].strip()
                    elif line.startswith("is_a:") and cur:
                        toks = line[5:].split("!")[0].split()      # "is_a: MS:1000044 ! dissociation method"
                        if toks:
                            isa.setdefault(cur, set()).add(toks[0])
                    elif line.startswith("is_obsolete:") and "true" in line:
                        obs = True
            if cur and not obs: accs.add(cur)
            cv[art["id"]] = accs
        self.cv_isa = isa
        return cv

# --------------------------------------------------------------------------- report
class Report:
    """Collects findings, collating exact duplicates (count++) and capping per-rule volume."""
    def __init__(self, profile, archive_path):
        self.findings = []
        self._seen = {}            # (ruleId, level, message) -> finding (dedup identical messages)
        self._n = {}               # ruleId -> distinct findings kept
        self._dropped = {}         # ruleId -> distinct findings suppressed past the cap
        self.profile = profile.manifest.get("profile_id")
        self.cv_versions = {a["id"]: a.get("version") for a in profile.manifest.get("artifacts", [])
                            if a.get("role") == "cv"}
        self.archive = str(archive_path)
        self.archive_info = None   # filled by run() via _archive_info()

    def add(self, rule, level, message, location=None, recovery=None, fix=None):
        rid = rule.get("id")
        key = (rid, level, message)
        dup = self._seen.get(key)
        if dup is not None:                       # identical message already reported -> just count it
            dup["count"] += 1
            return
        if self._n.get(rid, 0) >= MAX_PER_RULE:   # too many distinct findings from one rule -> summarise later
            self._dropped[rid] = self._dropped.get(rid, 0) + 1
            return
        f = {"ruleId": rid, "primitive": rule.get("primitive"), "level": level, "message": message,
             "location": location or {}, "recovery": recovery if recovery is not None else rule.get("recovery", "none"),
             "fix": fix if fix is not None else rule.get("fix"), "count": 1}
        self.findings.append(f); self._seen[key] = f
        self._n[rid] = self._n.get(rid, 0) + 1

    def to_dict(self):
        for rid, n in self._dropped.items():
            self.findings.append({"ruleId": rid, "primitive": "collation", "level": "info", "count": 1,
                                  "message": f"+{n} further distinct finding(s) from rule '{rid}' suppressed "
                                             f"(cap {MAX_PER_RULE}); fix the reported ones and re-run", "location": {}, "recovery": "none"})
        errs = sum(f["level"] == "error" for f in self.findings)
        warns = sum(f["level"] == "warning" for f in self.findings)
        return {"verdict": "FAIL" if errs else "PASS", "archive": self.archive, "profile": self.profile,
                "rule_primitive_catalog": CATALOG_VERSION, "cv": self.cv_versions,
                "summary": {"errors": errs, "warnings": warns},
                "archive_info": self.archive_info, "findings": self.findings}

# ----------------------------------------------------------------------- primitives
INFLECT = re.compile(r"^([A-Za-z]+)_(\d+)_")

def _imaging(ar):
    if _dict(_dict((ar.index or {}).get("metadata")).get("imaging")).get("is_imaging"):
        return True
    return ar.has_file("spectra_metadata") and any("IMS_1000050" in k for k in ar.fields("spectra_metadata"))

def p_index_files_present(ar, rule, rep, params):
    if getattr(ar, "_index_utf8_error", False):
        rep.add(rule, "error", "mzpeak_index.json is not valid UTF-8 (spec requires UTF-8 serialisation)")
    if not ar.index:
        rep.add(rule, "error", "mzpeak_index.json missing or unreadable"); return
    files = ar.index.get("files")
    if not isinstance(files, list):
        rep.add(rule, "error", "mzpeak_index.json 'files' is missing or not a list"); return
    # GENERAL RULE: only Parquet facet members (the '*.parquet' data/peaks/metadata tables) are
    # parse-validated. Every OTHER member in the archive — optical images, embedded sample-metadata
    # (SDRF/ISA), and ANY other non-Parquet blob — is an opaque member and is SKIPPED from the Parquet
    # parse; it is not a parquet file and must not be opened as one. Opaque members that carry a writer-
    # declared digest are still positively verified by their dedicated checks (optical images via
    # metadata.imaging + the blob_hash primitive; sample-metadata via metadata.sample_metadata below) —
    # so skipping the parse is never a free pass for a declared blob.
    sm = _dict(_dict(ar.index.get("metadata")).get("sample_metadata"))
    sm_declared = {}                              # member name -> (declared sha256, declared size_bytes)
    if isinstance(sm.get("member"), str) and sm.get("member"):
        sm_declared[sm["member"]] = (sm.get("sha256"), sm.get("size_bytes"))
    for fe in files:
        if not isinstance(fe, dict):
            rep.add(rule, "error", f"index 'files' entry is not an object: {fe!r}"); continue
        name = fe.get("name") or ""
        if not isinstance(name, str) or not name:
            rep.add(rule, "error", f"index 'files' entry has no usable name: {fe!r}"); continue
        if not ar.has_member(name):
            rep.add(rule, "error", f"index lists missing file: {name}", {"file": name}); continue
        if not name.endswith(".parquet"):
            # opaque non-Parquet ("Other") member — skipped from the parse check.
            if name in sm_declared:               # positively verify a declared sample-metadata blob
                declared, size = sm_declared[name]
                data = ar.read_member(name)
                if size is not None and int(size) != len(data):
                    rep.add(rule, "error",
                            f"sample-metadata member '{name}': {len(data)} bytes on disk != declared "
                            f"size_bytes={size}", {"file": name}, recovery="recompute")
                if declared:
                    actual = hashlib.new("sha256", data).hexdigest()
                    if actual.lower() != str(declared).lower():
                        rep.add(rule, "error",
                                f"sample-metadata member '{name}': sha256 mismatch (declared {declared}, "
                                f"actual {actual})", {"file": name}, recovery="recompute")
            continue
        try:
            ar.pf(name)
        except Exception as e:
            rep.add(rule, "error", f"cannot open {name}: {e}", {"file": name})

def p_columns_present(ar, rule, rep, params):
    f, spec = params["file"], params.get("_columns")
    if not (ar.has_file(f) and spec):
        return
    fields = ar.fields(f)
    for facet, fs in spec.get("facets", {}).items():
        present = any(k == facet or k.startswith(facet + ".") for k in fields)
        if not present:
            if fs.get("required"):
                rep.add(rule, "error", f"{f}: required facet '{facet}' absent", {"file": f, "facet": facet})
            continue
        for col, cs in fs.get("columns", {}).items():
            path = f"{facet}.{col}"
            got = fields.get(path)
            if got is None:
                if cs.get("required"):
                    rep.add(rule, "error", f"{f}: required column '{path}' absent", {"file": f, "column": path})
                continue
            want = cs.get("type")
            if want and not type_matches(arrow_logical(got), want):
                exp = " or ".join(want) if isinstance(want, list) else want
                rep.add(rule, "error", f"{f}.{path}: type {arrow_logical(got)} != expected {exp}",
                        {"file": f, "column": path}, recovery="rederive")

_ABSENT = object()

def _json_source(ar, params):
    """Return (json_value, where) for a json_schema rule, or (_ABSENT, where) when not present.
    Sources: {index:true} -> whole index; {index_path:'a.b'} -> dotted path into the index;
    {file, footer_key} -> a JSON blob from a Parquet footer key/value pair."""
    if params.get("index"):
        return (ar.index, "mzpeak_index.json") if ar.index is not None else (_ABSENT, "mzpeak_index.json")
    ip = params.get("index_path")
    if ip:
        v = _dig(ar.index or {}, ip)
        return (v, f"mzpeak_index.json:{ip}") if v is not None else (_ABSENT, f"mzpeak_index.json:{ip}")
    f, key = params.get("file"), params.get("footer_key")
    where = f"{f}:{key}"
    if not (f and key and ar.has_file(f)):
        return _ABSENT, where
    raw = ar.footer(f, key)
    if raw is None:
        return _ABSENT, where
    try:
        return json.loads(raw), where
    except (ValueError, TypeError) as e:
        return ("__BADJSON__", e), where    # signal: present but unparseable

def p_json_schema(ar, rule, rep, params):
    """Validate a JSON document (the index, a sub-path of it, or a footer metadata blob) against a
    bundled JSON Schema. Self-gates: a footer blob that is absent is not flagged here (presence is a
    SHOULD; required-presence is enforced by dedicated rules)."""
    schema = params.get("_schema")
    if schema is None:
        return                                  # schema not bundled in this profile -> skip
    doc, where = _json_source(ar, params)
    if doc is _ABSENT:
        return
    if isinstance(doc, tuple) and doc[0] == "__BADJSON__":
        rep.add(rule, "error", f"{where}: not valid JSON ({doc[1]})", {"file": params.get('file', '')}); return
    try:
        import jsonschema
        store = params.get("_schema_store", {})
        validator = _schema_validator(schema, store)
        errs = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    except Exception as e:                       # broken profile bundle — treat as engine error
        rep.add(rule, "error", f"{where}: JSON-Schema validation failed ({type(e).__name__}: {e})",
                {"file": params.get('file', '')}); return
    sev = rule.get("severity", "error")
    for e in errs:
        loc = "/".join(str(p) for p in e.path) or "(root)"
        rep.add(rule, sev, f"{where}: schema violation at {loc}: {e.message}",
                {"file": params.get("file", ""), "column": loc})
    # buffer_format_uniform: point layout is all-or-nothing; chunk layout intentionally has
    # multiple buffer_format values (chunk_start, chunk_end, chunk_values, …) — only flag
    # when the mix is incoherent (e.g. point mixed with chunk, or unknown formats).
    if params.get("buffer_format_uniform") and isinstance(doc, dict):
        entries = doc.get("entries") or []
        fmts = {e.get("buffer_format") for e in entries if isinstance(e, dict) and e.get("buffer_format")}
        _chunk_fmts = {"chunk_encoding", "chunk_end", "chunk_secondary",
                       "chunk_start", "chunk_transform", "chunk_values"}
        if len(fmts) > 1 and not fmts.issubset(_chunk_fmts):
            rep.add(rule, sev, f"{where}: mixed buffer_format {sorted(fmts)} — point layout is all-or-nothing",
                    {"file": params.get("file", "")})
    # cv_parents: check entries[*].field values are OBO descendants of a required parent term
    isa = params.get("_cv_isa", {})
    for cp in params.get("cv_parents", []):
        m = re.match(r"^entries\[\*\]\.(\w+)$", cp.get("path", ""))
        if not m:
            continue
        field, parent = m.group(1), cp["parent"]
        for i, entry in enumerate((doc.get("entries") or []) if isinstance(doc, dict) else []):
            v = entry.get(field)
            if v and isinstance(v, str) and not _is_descendant(isa, v, parent):
                rep.add(rule, sev, f"{where}: entries/{i}/{field} {v!r} is not a descendant of {parent}",
                        {"file": params.get("file", "")})

def p_footer_count_equals_rows(ar, rule, rep, params):
    f, key = params["file"], params["footer_key"]
    if not ar.has_file(f): return
    v = ar.footer(f, key)
    if v is None:
        rep.add(rule, "warning", f"{f}: footer key '{key}' absent"); return
    try:
        iv = int(v)
    except (TypeError, ValueError):
        rep.add(rule, "error", f"{f}: footer {key}={v!r} is not an integer", {"file": f}); return
    # In the packed parallel-facet layout, table rows == the LONGEST facet (e.g. one row per
    # PASEF precursor), not the spectrum count. If count_column (a facet primary key) is given,
    # count its non-null entries; the spectrum count is one per populated spectrum facet row.
    col = params.get("count_column")
    if col and has(ar, f, col) and not params.get("_quick"):
        # Stream to count non-nulls; avoids loading the full column into RAM.
        nonnull = sum(len(arr) - arr.null_count for (arr,) in ar.iter_batches(f, col))
        actual, what = nonnull, f"non-null {col}"
    else:
        actual, what = ar.num_rows(f), "parquet rows"
    if iv != actual:
        rep.add(rule, "error", f"{f}: footer {key}={iv} != {what}={actual}",
                {"file": f}, recovery="rederive")

def p_column_predicate(ar, rule, rep, params):
    f, col = params["file"], params["column"]
    if not has(ar, f, col): return
    op = params["op"]
    if op == "finite":
        desc = "non-finite (NaN/inf)"
        check = lambda arr: pc.fill_null(pc.is_finite(arr), True)
    else:
        fn = {"ge": pc.greater_equal, "gt": pc.greater, "le": pc.less_equal, "lt": pc.less}[op]
        val = params.get("value")
        desc = f"fail {op} {val}"
        check = lambda arr: pc.fill_null(fn(arr, val), True)
    nbad = 0; first_i = None; first_v = None; offset = 0
    for (arr,) in ar.iter_batches(f, col):
        badmask = pc.invert(check(arr))
        nb = pc.sum(pc.cast(badmask, pa.int64())).as_py() or 0
        nbad += nb
        if nb and first_i is None:
            i = int(np.argmax(badmask.to_numpy(zero_copy_only=False)))
            first_i = offset + i; first_v = arr[i].as_py()
        offset += len(arr)
    if nbad:
        rep.add(rule, rule.get("severity", "error"),
                f"{f}.{col}: {nbad} of {offset} value(s) {desc}; first at row {first_i} (value {first_v})",
                {"file": f, "column": col, "row": first_i})

def p_dtype_role(ar, rule, rep, params):
    f, col, allowed = params["file"], params["column"], params["allowed"]
    if not has(ar, f, col): return
    role = params.get("role", col.split(".")[-1])
    actual = ar.fields(f)[col]              # type already in schema metadata; no column decode needed
    ty = arrow_logical(actual)
    if ty not in allowed:
        rep.add(rule, "error",
                f"{f}.{col}: stored as {actual} (logical '{ty}'), which is invalid for a '{role}' column "
                f"(expected one of {allowed})", {"file": f, "column": col})

def declared_sorted(ar, file, dotted_col):
    """Has the array index for `dotted_col` declared it sorted? Returns:
      True  — an array-index entry for the column declares a non-null sorting_rank (spec: sorted ascending),
      False — an entry exists but declares it unsorted (sorting_rank null/absent),
      None  — no array index / no matching entry (no declaration; caller decides).
    mzPeak ties m/z ordering to the declared sorting_rank (schema/array_index.json), so monotonicity
    is only a conformance requirement when the column declares itself sorted."""
    raw = ar.footer(file, "spectrum_array_index")
    if raw is None:
        return None
    try:
        idx = json.loads(raw)
    except (ValueError, TypeError):
        return None
    entries = idx.get("entries", []) if isinstance(idx, dict) else idx if isinstance(idx, list) else []
    for e in entries:
        # match THIS column by path only — an array_type fallback would let an entry for a
        # different column (or a decoy MS:1000514 entry) suppress the check on point.mz.
        if isinstance(e, dict) and e.get("path") == dotted_col:
            rank = e.get("sorting_rank")
            # spec: a (numeric) sorting_rank = sorted ascending; null/absent/non-numeric = not sorted.
            return isinstance(rank, (int, float)) and not isinstance(rank, bool)
    return None

def p_grouped_monotonic(ar, rule, rep, params):
    f, grp, col = params["file"], params["group"], params["column"]
    if not (has(ar, f, grp) and has(ar, f, col)): return
    if declared_sorted(ar, f, col) is False:
        rep.add(rule, "info", f"{f}.{col}: array index declares it unsorted (sorting_rank null/absent); "
                f"monotonicity not enforced", {"file": f, "column": col})
        return
    sev = rule.get("severity", "error")
    # Vectorised streaming.  Cross-batch boundary: last[g] dict, O(unique_groups) Python ops.
    # Within-batch: numpy consecutive-pair check after an optional lexsort.
    # Hybrid: skip sort when groups are already contiguous (typical real data — 500M rows/s);
    # fall through to lexsort only when interleaving is detected (adversarial files).
    last = {}; nbad = 0; first_bad = None; offset = 0
    for gcol, vcol in ar.iter_batches(f, grp, col):
        null_g = pc.is_null(gcol).to_numpy(zero_copy_only=False)
        null_v = pc.is_null(vcol).to_numpy(zero_copy_only=False)
        valid  = ~null_g & ~null_v
        if not np.any(valid):
            offset += len(gcol); continue
        gv = (gcol.cast(pa.int64(), safe=False).to_numpy(zero_copy_only=False)
              if pa.types.is_integer(gcol.type) else gcol.to_numpy(zero_copy_only=False))
        v  = vcol.to_numpy(zero_copy_only=False)
        vg = gv[valid]; vv = v[valid]; vidx = np.where(valid)[0]; n = len(vg)
        # Cross-batch: first physical row per group vs last batch's final value
        unique_g, first_phys = np.unique(vg, return_index=True)
        for fi, g in zip(first_phys.tolist(), unique_g.tolist()):
            prev = last.get(g)
            if prev is not None and vv[fi] < prev:
                nbad += 1
                if first_bad is None:
                    first_bad = (offset + int(vidx[fi]), g, float(prev), float(vv[fi]))
        # Within-batch: consecutive same-group pairs; sort only when groups interleave
        if n > 1:
            if np.any(np.diff(vg) < 0):       # interleaved → sort by (group, row_index)
                si = np.lexsort((vidx, vg)); sg = vg[si]; sv = vv[si]; svidx = vidx[si]
            else:                              # already contiguous — no sort needed
                sg = vg; sv = vv; svidx = vidx
            same = sg[1:] == sg[:-1]; inv = same & (sv[1:] < sv[:-1])
            if np.any(inv):
                nbad += int(np.sum(inv))
                if first_bad is None:
                    pi = int(np.argmax(inv))
                    first_bad = (offset + int(svidx[pi + 1]),
                                 int(sg[pi + 1]), float(sv[pi]), float(sv[pi + 1]))
        # Update last: last physical row value per group
        _, last_rev = np.unique(vg[::-1], return_index=True)
        for li in (n - 1 - last_rev).tolist():
            last[int(vg[li])] = float(vv[li])
        offset += len(gcol)
    if first_bad:
        row, gid, prev, cur = first_bad
        rep.add(rule, sev,
                f"{f}.{col} not {params['direction']} within {grp}: {nbad} inversion(s); "
                f"in {grp}={gid}, value {cur} (row {row}) < previous {prev}",
                {"file": f, "row": row}, recovery="reorder_pair")

def p_foreign_key(ar, rule, rep, params):
    f, col, rf, rc = params["file"], params["column"], params["ref_file"], params["ref_column"]
    if not (has(ar, f, col) and has(ar, rf, rc)): return
    # Ref (parent) is always a metadata file — small enough to load fully.
    parent = {x for x in ar.column(rf, rc).to_pylist() if x is not None}
    # Stream child (may be a large data file) to accumulate unique values and null presence.
    child_unique = set(); has_null = False
    for (arr,) in ar.iter_batches(f, col):
        for v in pc.unique(arr).to_pylist():
            if v is None: has_null = True
            else: child_unique.add(v)
    missing = [x for x in child_unique if x not in parent]
    flag_null = has_null and not params.get("allow_null", False)
    if missing or flag_null:
        parts = []
        if missing: parts.append(f"{len(missing)} value(s) with no {rf}.{rc} (e.g. {missing[:3]})")
        if flag_null: parts.append("null values present")
        rep.add(rule, rule.get("severity", "error"), f"{f}.{col}: " + "; ".join(parts), {"file": f, "column": col})

def p_index_contiguous(ar, rule, rep, params):
    f, col = params["file"], params["column"]
    if not has(ar, f, col): return
    # Ignore nulls: packed facet layout populates only a subset of rows per facet.
    # Stream batches tracking the running expected index.
    expected = 0; total_nonnull = 0
    for (arr,) in ar.iter_batches(f, col):
        v = pc.drop_null(arr).to_numpy(zero_copy_only=False).astype(np.int64)
        if len(v) == 0: continue
        exp = np.arange(expected, expected + len(v), dtype=np.int64)
        if not np.array_equal(v, exp):
            i = int(np.argmax(v != exp))
            abs_pos = expected + i
            rep.add(rule, rule.get("severity", "warning"),
                    f"{f}.{col} not 0-based contiguous (len {total_nonnull + len(v)} non-null): "
                    f"position {abs_pos} is {v[i]}, expected {abs_pos}",
                    {"file": f, "column": col, "row": abs_pos})
            return
        expected += len(v); total_nonnull += len(v)

UNIT = re.compile(r"_unit_([A-Za-z]+)_(\d+)")

def _cv_refs(leaf):
    """CV references in an inflected column leaf: the primary ${CV}_${ACC} plus any _unit_${UCV}_${UACC}."""
    m = INFLECT.match(leaf)
    if m and m.group(1) != "ARROW":
        yield m.group(1), m.group(2)
    for um in UNIT.finditer(leaf):
        yield um.group(1), um.group(2)

def _used_cv_codes(ar, files):
    used = set()
    for f in files:
        if ar.has_file(f):
            for path in ar.fields(f):
                for code, _ in _cv_refs(path.split(".")[-1]):
                    used.add(code)
    return used

def p_cv_inflection(ar, rule, rep, params):
    f, cv = params["file"], params.get("_cv", {})
    if not ar.has_file(f): return
    seen = set()
    for path in ar.fields(f):
        leaf = path.split(".")[-1]
        for code, num in _cv_refs(leaf):          # primary accession AND any unit accession
            if code not in cv:
                if (code, num) not in seen:
                    seen.add((code, num))
                    rep.add(rule, "error", f"{f}: column '{leaf}' uses CV code '{code}' not in profile CVs",
                            {"file": f, "column": path})
            elif f"{code}:{num}" not in cv[code]:
                rep.add(rule, "warning", f"{f}: '{leaf}' accession {code}:{num} not in pinned {code} CV",
                        {"file": f, "column": path})

def p_cv_list_consistency(ar, rule, rep, params):
    """The file's metadata.cv_list declares every CV code it actually uses (spec: every referenced CV
    MUST be declared once in the file-level cv_list), and the declared versions match the pinned snapshots."""
    used = _used_cv_codes(ar, params.get("files", ["spectra_metadata", "chromatograms_metadata"]))
    if not used:
        return                                    # no inflected CV columns -> nothing to declare
    sev = rule.get("severity", "error")
    cvl = _dig(ar.index or {}, params.get("list", "metadata.cv_list"))
    if not isinstance(cvl, list) or not cvl:
        rep.add(rule, sev, f"metadata.cv_list is absent/empty but the archive uses CV codes {sorted(used)}")
        return
    declared = {e.get("id") for e in cvl if isinstance(e, dict)}
    missing = sorted(used - declared)
    if missing:
        rep.add(rule, sev, f"CV code(s) used but not declared in metadata.cv_list: {missing} "
                f"(declared: {sorted(c for c in declared if c)})")
    pinned = params.get("_cv_versions", {})       # {id: pinned version} from the profile
    # Version policy: warn ONLY when the file declares a CV version NEWER than the validator's pinned
    # snapshot — that means the validator is behind and should refresh its bundled CV (its CURIE
    # resolution may be stale). A file pinned to the SAME or an OLDER version is expected and benign,
    # so it must NOT warn (a plain difference is not a problem). _vkey extracts numeric components,
    # _vkey extracts numeric components, so it orders dotted ("4.1.248") and date ("2026-01-16")
    # versions each consistently with ITSELF. It cannot compare across schemes (a date vs a dotted
    # release), so we only warn when declared and pinned share a scheme (same component count).
    for e in cvl:
        if not (isinstance(e, dict) and e.get("id") in pinned and e.get("version")):
            continue
        declared_v, pinned_v = str(e["version"]), str(pinned[e["id"]])
        dk, pk = _vkey(declared_v), _vkey(pinned_v)
        if len(dk) == len(pk) and dk > pk:
            rep.add(rule, "warning", f"cv_list declares {e['id']} version {declared_v}, newer than the "
                    f"profile's pinned {pinned_v} — update the validator's bundled {e['id']} CV snapshot "
                    f"(CURIEs currently resolve against the older pinned copy)")

def p_count_sum_equals_rows(ar, rule, rep, params):
    """Point-layout integrity: sum of per-spectrum point counts == data-file row count."""
    f, cnt_file, cnt_col = params["file"], params.get("count_file", "spectra_metadata"), params["count_column"]
    if not (has(ar, f, params.get("guard", "point.intensity")) and has(ar, cnt_file, cnt_col)):
        return
    # null counts are 0 (centroid spectra have no profile points; data lives in spectra_peaks).
    # Stream the count column to avoid holding it in RAM.
    total = sum((pc.sum(arr).as_py() or 0) for (arr,) in ar.iter_batches(cnt_file, cnt_col))
    if int(total) != ar.num_rows(f):
        rep.add(rule, rule.get("severity", "error"), f"{f}: sum({cnt_col})={total} != {f} rows={ar.num_rows(f)}",
                {"file": f}, recovery="rederive")

def p_grouped_count_equals(ar, rule, rep, params):
    """Per-spectrum count integrity: the number of signal rows for each spectrum equals that
    spectrum's declared count. Stronger than count_sum_equals_rows (catches localized/swapped
    corruption that a global sum hides). Null declared count is treated as 0 (centroid spectra have
    no profile points; their data lives in spectra_peaks)."""
    f, grp = params["file"], params["group"]
    cf, cc = params.get("count_file", "spectra_metadata"), params["count_column"]
    key = params.get("key_column", "spectrum.index")
    if not (has(ar, f, params.get("guard", grp)) and has(ar, cf, cc) and has(ar, cf, key)):
        return
    # Stream the (potentially large) data-file group column; build actual count dict per batch.
    actual = {}
    for (gcol,) in ar.iter_batches(f, grp):
        if pa.types.is_integer(gcol.type):
            gv = pc.fill_null(gcol.cast(pa.int64(), safe=False), -1).to_numpy(zero_copy_only=False)
        else:
            gv = gcol.to_numpy(zero_copy_only=False)
        null = pc.is_null(gcol).to_numpy(zero_copy_only=False)
        ids, cnts = np.unique(gv[~null], return_counts=True)
        for gid, cnt in zip(ids.tolist(), cnts.tolist()):
            actual[gid] = actual.get(gid, 0) + cnt
    # Metadata side (spectra_metadata) is small — load fully.
    kcol = ar.column(cf, key); ccol = ar.column(cf, cc)
    kv = (pc.fill_null(kcol.cast(pa.int64(), safe=False), -1).to_numpy(zero_copy_only=False)
          if pa.types.is_integer(kcol.type) else kcol.to_numpy(zero_copy_only=False))
    cvv = ccol.to_numpy(zero_copy_only=False)
    knull = pc.is_null(kcol).to_numpy(zero_copy_only=False)
    cnull = pc.is_null(ccol).to_numpy(zero_copy_only=False)
    bad = 0; first = None
    for i in range(len(kv)):
        if knull[i]: continue
        sid = int(kv[i])
        declared = 0 if cnull[i] else int(cvv[i])
        got = int(actual.get(sid, 0))
        if got != declared:
            bad += 1
            if first is None: first = (sid, declared, got)
    if bad:
        sid, declared, got = first
        rep.add(rule, rule.get("severity", "error"),
                f"{f}: per-spectrum count mismatch in {bad} spectrum/spectra; spectrum.index={sid} declares "
                f"{cc.split('.')[-1]}={declared} but {f} has {got} row(s)", {"file": f}, recovery="rederive")

def p_data_kind_facet(ar, rule, rep, params):
    """A file whose index data_kind promises signal must carry a recognized signal facet."""
    if not ar.index: return
    want = set(params.get("data_kinds", ["data arrays", "peaks"]))
    need = set(params.get("facets", ["point", "chunk"]))
    ent = set(params.get("entity_types", ["spectrum", "mass spectrum"]))
    for fe in ar.index.get("files", []):
        if fe.get("data_kind") in want and fe.get("entity_type") in ent and ar.has_file(fe.get("name", "")):
            tops = {k.split(".")[0] for k in ar.fields(fe["name"])}
            if not (tops & need):
                rep.add(rule, rule.get("severity", "error"),
                        f"{fe['name']}: index declares data_kind '{fe['data_kind']}' but the file has top-level "
                        f"columns {sorted(tops)} — none of the expected signal facets {sorted(need)}",
                        {"file": fe["name"]})

def p_imaging_coordinates(ar, rule, rep, params):
    if not _imaging(ar): return
    sev = rule.get("severity", "error")
    f = "spectra_metadata"; fields = ar.fields(f)
    has_x = any(k.endswith("IMS_1000050_position_x") for k in fields)
    has_y = any(k.endswith("IMS_1000051_position_y") for k in fields)
    if not (has_x and has_y):
        rep.add(rule, sev, "imaging archive missing position_x and/or position_y column", {"file": f}); return
    coord_cols = [k for k in fields if k.endswith(("IMS_1000050_position_x", "IMS_1000051_position_y"))]
    # Stream each coordinate column and track the running minimum finite value.
    for path in coord_cols:
        col_min = None
        for (arr,) in ar.iter_batches(f, path):
            v = arr.to_numpy(zero_copy_only=False)
            finite = v[np.isfinite(v)]
            if len(finite):
                b = float(finite.min())
                if col_min is None or b < col_min: col_min = b
        if col_min is not None and col_min < 1:
            rep.add(rule, sev, f"{f}.{path}: minimum coordinate {col_min:g} < 1 "
                    f"(imaging coordinates must be 1-based)", {"file": f, "column": path})

# --- raw archive-member primitives (embedded optical images: metadata.imaging.images[]) ---
TIFF_MAGIC = (b"II*\x00", b"MM\x00*")            # little/big-endian baseline TIFF (and BigTIFF shares II*/MM* prefixes)

def _dig(obj, dotted):
    """Walk a dotted path through nested dicts; None if any hop is absent/non-dict."""
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur

def _image_entries(ar, params):
    """The declared image list (default metadata.imaging.images) as [(i, entry, member_name), ...]."""
    if not ar.index:
        return []
    lst = _dig(ar.index, params.get("list", "metadata.imaging.images"))
    if not isinstance(lst, list):
        return []
    field = params.get("member", "archive_path")
    return [(i, e, e.get(field)) for i, e in enumerate(lst) if isinstance(e, dict)]

def p_member_exists(ar, rule, rep, params):
    """Each declared image references an archive member that is actually present."""
    sev = rule.get("severity", "warning")
    field = params.get("member", "archive_path")
    for i, e, name in _image_entries(ar, params):
        if not name:
            rep.add(rule, sev, f"images[{i}] declares no '{field}' member name")
        elif not ar.has_member(name):
            rep.add(rule, sev, f"declared image member '{name}' (images[{i}]) is not present in the archive",
                    {"file": name})

def p_blob_hash(ar, rule, rep, params):
    """A present image member's bytes match its declared digest (and size, if declared)."""
    sev = rule.get("severity", "warning")
    algo = params.get("algo", "sha256")
    hash_field, size_field = params.get("hash_field", "sha256"), params.get("size_field", "size_bytes")
    for i, e, name in _image_entries(ar, params):
        if not ar.has_member(name):                   # absence is p_member_exists' concern, not ours
            continue
        data = ar.read_member(name)
        size = e.get(size_field)
        if size is not None and int(size) != len(data):
            rep.add(rule, sev, f"image member '{name}': {len(data)} bytes on disk != declared {size_field}={size}",
                    {"file": name}, recovery="recompute")
        declared = e.get(hash_field)
        if declared:
            actual = hashlib.new(algo, data).hexdigest()
            if actual.lower() != str(declared).lower():
                rep.add(rule, sev, f"image member '{name}': {algo} mismatch (declared {declared}, actual {actual})",
                        {"file": name}, recovery="recompute")

def p_tiff_magic(ar, rule, rep, params):
    """A member declared image/tiff begins with a TIFF magic number."""
    sev = rule.get("severity", "warning")
    mt_field, want_mt = params.get("media_type_field", "media_type"), params.get("media_type", "image/tiff")
    for i, e, name in _image_entries(ar, params):
        if not ar.has_member(name):
            continue
        mt = e.get(mt_field)
        applies = (mt == want_mt) if mt is not None else str(name).lower().endswith((".tif", ".tiff"))
        if not applies:
            continue
        head = ar.read_member(name, 4)
        if head not in TIFF_MAGIC:
            rep.add(rule, sev, f"image member '{name}' declared {want_mt} but is not a TIFF "
                    f"(first 4 bytes {head!r}; expected b'II*\\x00' or b'MM\\x00*')", {"file": name})

def _is_descendant(isa, acc, ancestor):
    """True iff `acc` equals `ancestor` or is a transitive is_a child of it (walks the merged is_a graph)."""
    if acc == ancestor:
        return True
    seen, stack = set(), [acc]
    while stack:
        x = stack.pop()
        for par in isa.get(x, ()):
            if par == ancestor:
                return True
            if par and par not in seen:
                seen.add(par); stack.append(par)
    return False

def _term_matches(acc, term, isa):
    """Does accession `acc` satisfy CvTerm `term`? use_term -> the term itself; allow_children -> a
    proper is_a descendant. (use_term+allow_children -> self or descendant.)"""
    ta = term.get("term_accession")
    if acc == ta:
        return bool(term.get("use_term"))
    return bool(term.get("allow_children")) and _is_descendant(isa, acc, ta)

_CVMAP_LOGIC = {"AND": "all of", "OR": "one of", "XOR": "exactly one of"}

def _cvmap_eval(cr, present, isa, rule, rep, emit, where, loc):
    """Apply one CvMappingRule to the set of accessions `present` at scope `where`: combination logic
    (AND/OR/XOR) over its cv_terms, plus per-term cardinality (is_repeatable). Shared by the facet
    resolver (p_cv_mapping) and the JSON-metadata resolver (p_cv_mapping_json)."""
    terms = cr.get("cv_terms", [])
    logic = cr.get("cv_terms_combination_logic", "AND")
    sat = {i for i, t in enumerate(terms) if any(_term_matches(a, t, isa) for a in present)}
    ok = (len(sat) == len(terms)) if logic == "AND" else (len(sat) >= 1) if logic == "OR" else (len(sat) == 1)
    if not ok:
        want = ", ".join(f"{t.get('term_name')} ({t.get('term_accession')})" for t in terms)
        miss = ", ".join(terms[i].get("term_name") for i in range(len(terms)) if i not in sat) or "(combination unmet)"
        rep.add(rule, emit, f"{where}: CvMapping '{cr.get('id')}' ({cr.get('requirement_level')}/{logic}) "
                f"requires {_CVMAP_LOGIC.get(logic, logic)} [{want}]; missing: {miss}",
                loc, recovery="none", fix=rule.get("fix"))
    for t in terms:                               # non-repeatable term must match at most one entry in scope
        if t.get("is_repeatable", True):
            continue
        matched = sorted(a for a in present if _term_matches(a, t, isa))
        if len(matched) > 1:
            rep.add(rule, emit, f"{where}: CvMapping '{cr.get('id')}': non-repeatable term {t.get('term_name')} "
                    f"({t.get('term_accession')}) matched by {len(matched)} entries: {matched}",
                    loc, recovery="none", fix=rule.get("fix"))

def p_cv_mapping(ar, rule, rep, params):
    """CV term-placement over the packed Parquet facets (PSI CvMapping model, mzPeak port — see
    docs/cv-mapping-design.md). Consumes a bundled CvMapping file (params._mapping = the spec's
    table_rules.json / imaging rules); for each rule, maps scope_path -> an mzPeak facet (params.path_map),
    gathers the accessions inflected into that facet's column names, and checks them with _cvmap_eval.
    Schema-only (no row decode) -> runs under --quick. MUST emits at this rule's severity; SHOULD ->
    warning; MAY skipped (Phase 1). Self-gates on an unmapped scope_path or an absent file/facet."""
    mapping = params.get("_mapping")
    if not mapping:
        return
    if params.get("require_imaging") and not _imaging(ar):
        return
    isa = params.get("_cv_isa", {})
    pathmap = params.get("path_map", {})
    sev_must = rule.get("severity", "warning")
    for cr in mapping.get("cv_mapping_rule_list", []):
        if cr.get("requirement_level") == "MAY":  # Phase 1: MAY rules enumerate permitted terms; not enforced
            continue
        loc = pathmap.get(cr.get("scope_path"))
        if not loc:                               # scope_path has no mzPeak facet mapping -> skip
            continue
        f, facet = loc["file"], loc["facet"]
        if not ar.has_file(f):
            continue
        fields = ar.fields(f)
        if not any(k == facet or k.startswith(facet + ".") for k in fields):
            continue                              # facet absent in this archive -> skip
        present = {f"{code}:{num}" for path in fields if path.startswith(facet + ".")
                   for code, num in _cv_refs(path.split(".")[-1])}
        emit = sev_must if cr.get("requirement_level") == "MUST" else "warning"
        _cvmap_eval(cr, present, isa, rule, rep, emit, f"{f} [{facet}]", {"file": f, "facet": facet})

def _json_seg(seg):
    """Parse one path segment: 'components[component_type=ionsource]' -> ('components', True, ('component_type','ionsource'));
    'parameters[]' -> ('parameters', True, None); 'accession' -> ('accession', False, None)."""
    if "[" not in seg:
        return seg, False, None
    name, _, rest = seg.partition("[")
    inner = rest.rstrip("]")
    if "=" in inner:
        k, _, v = inner.partition("=")
        return name, True, (k.strip(), v.strip())
    return name, True, None

def _json_segs(path):
    return [s for s in path.strip("/").split("/") if s]

def _json_walk(node, segs):
    """Yield every value reached from `node` along `segs`, following list iteration (`key[]`) and
    `key[field=value]` filters. A leaf scalar segment (e.g. 'accession') yields the field's value."""
    if not segs:
        yield node
        return
    if not isinstance(node, dict):
        return
    name, listy, filt = _json_seg(segs[0])
    child = node.get(name)
    if child is None:
        return
    if isinstance(child, list) or listy:
        for x in (child if isinstance(child, list) else [child]):
            if filt and not (isinstance(x, dict) and str(x.get(filt[0])) == filt[1]):
                continue
            yield from _json_walk(x, segs[1:])
    else:
        yield from _json_walk(child, segs[1:])

def p_cv_mapping_json(ar, rule, rep, params):
    """CV term-placement over the JSON index metadata — the spec's semantic_rules.json (file_description
    contents, instrument-config components incl. ionization/analyzer/detector type, software,
    data_processing). For each CvMappingRule, resolves scope_path to its instance object(s) in
    mzpeak_index.json `metadata`, gathers the accessions at cv_element_path within each instance, and
    applies _cvmap_eval per instance. Reads only the already-loaded index (cheap; runs under --quick).
    Phase 1: advisory (MUST -> this rule's severity, SHOULD -> warning, MAY skipped). An absent
    scope (e.g. no contacts) yields no instances and is silently conformant."""
    mapping = params.get("_mapping")
    if not mapping or not isinstance(ar.index, dict):
        return
    isa = params.get("_cv_isa", {})
    sev_must = rule.get("severity", "warning")
    for cr in mapping.get("cv_mapping_rule_list", []):
        level = cr.get("requirement_level")
        if level == "MAY":
            continue
        scope, elem = cr.get("scope_path", ""), cr.get("cv_element_path", "")
        if not elem.startswith(scope):            # element must live inside the scope; skip malformed
            continue
        tail = _json_segs(elem[len(scope):])      # accession path relative to a scope instance
        emit = sev_must if level == "MUST" else "warning"
        for inst in _json_walk(ar.index, _json_segs(scope)):
            present = {v for v in _json_walk(inst, tail) if isinstance(v, str)}
            _cvmap_eval(cr, present, isa, rule, rep, emit, f"metadata {scope}", {"path": scope})

def p_parquet_row_group_health(ar, rule, rep, params):
    """Advisory (perf, NOT conformance): a chunked data facet stored in a single monolithic Parquet
    row group makes every random single-spectrum read decode the whole group. Warns when a chunk-layout
    data file has exactly ONE row group whose uncompressed size exceeds `min_bytes` (default 64 MB).
    Footer-only (no column decode) so it runs even under --quick. Gated on the `chunk` facet: the
    point/peaks (per-peak) layout is chunked correctly by the writer and is not flagged."""
    facet = params.get("facet", "chunk")
    min_bytes = int(params.get("min_bytes", 64 * 1024 * 1024))
    for fname in params.get("files", ["spectra_data", "chromatograms_data"]):
        if not ar.has_file(fname):
            continue
        if not any(k == facet or k.startswith(facet + ".") for k in ar.fields(fname)):
            continue                                  # only the chunk layout; point/peaks chunk fine
        md = ar.pf(fname).metadata
        if md.num_row_groups != 1:
            continue                                  # already partitioned for random access
        rg_bytes = md.row_group(0).total_byte_size
        if rg_bytes > min_bytes:
            rep.add(rule, "warning",
                    f"{fname}: chunked data facet in a single {rg_bytes/1e6:.0f} MB Parquet row group "
                    f"(> {min_bytes/1e6:.0f} MB threshold) — Parquet reads at row-group granularity, so "
                    f"every random single-spectrum read decodes the whole group; bound row groups by "
                    f"uncompressed size or point count so each spectrum touches one small group",
                    {"file": fname}, recovery="normalize")

def p_chunk_columns(ar, rule, rep, params):
    """Structural completeness of a chunked signal facet (Phase 3): when a data file declares the
    chunked sublayout (the `start_column`, e.g. chunk.mz_chunk_start / chunk.time_chunk_start is
    present), it MUST also carry its companion columns (chunk end, the value list, encoding, intensity).
    Schema-only -> runs under --quick. Self-gates: a file without `start_column` (point/scalar layout
    or absent file) is skipped."""
    f, start = params["file"], params["start_column"]
    if not has(ar, f, start):
        return
    sev = rule.get("severity", "error")
    for col in params.get("required", []):
        if not has(ar, f, col):
            rep.add(rule, sev, f"{f}: chunked layout declares '{start}' but is missing companion column '{col}'",
                    {"file": f, "column": col})

def p_chunk_bounds(ar, rule, rep, params):
    """Chunk ordering invariant (Phase 3, the chunked analog of grouped_monotonic): within each group
    (chunk.spectrum_index / chunk.chromatogram_index) every chunk has start <= end, and consecutive
    chunks are non-overlapping and ascending by start. Gates on `start_column`; DATA_SCAN."""
    f, grp, sc, ec = params["file"], params["group"], params["start_column"], params["end_column"]
    if not (has(ar, f, grp) and has(ar, f, sc) and has(ar, f, ec)):
        return
    sev = rule.get("severity", "error")
    # Stream batches; track last (end_val, row) per group for overlap detection.
    # last_end[g_id] = (end_value, absolute_row) for the most recent chunk in that group.
    last_end = {}; offset = 0
    start_gt_end = None; overlap_found = None
    for gcol, scol, ecol in ar.iter_batches(f, grp, sc, ec):
        gv = (pc.fill_null(gcol.cast(pa.int64(), safe=False), -1).to_numpy(zero_copy_only=False)
              if pa.types.is_integer(gcol.type) else gcol.to_numpy(zero_copy_only=False))
        sv   = scol.to_numpy(zero_copy_only=False)
        ev   = ecol.to_numpy(zero_copy_only=False)
        snull = pc.is_null(scol).to_numpy(zero_copy_only=False)
        enull = pc.is_null(ecol).to_numpy(zero_copy_only=False)
        for i in range(len(gv)):
            if snull[i] or enull[i]: continue
            g = int(gv[i]); s_val = float(sv[i]); e_val = float(ev[i])
            abs_row = offset + i
            # start > end check
            if start_gt_end is None and s_val > e_val:
                start_gt_end = (abs_row, s_val, e_val, g)
            # overlap check against previous chunk in same group
            prev = last_end.get(g)
            if prev is not None and overlap_found is None and s_val < prev[0]:
                overlap_found = (abs_row, g, s_val, prev[0])
            last_end[g] = (e_val, abs_row)
        offset += len(gv)
    if start_gt_end:
        row, s, e, g = start_gt_end
        grp_name = grp.split(".")[-1]
        rep.add(rule, sev, f"{f}: chunk start > end at row {row} ({s:g} > {e:g}) in {grp_name}={g}",
                {"file": f, "row": row})
    if overlap_found:
        row, g, s_val, prev_end = overlap_found
        grp_name = grp.split(".")[-1]
        rep.add(rule, sev, f"{f}: overlapping/non-ascending chunks in {grp_name}={g}: "
                f"chunk start {s_val:g} < previous end {prev_end:g}", {"file": f, "row": row},
                recovery="reorder_pair")

def p_aux_arrays(ar, rule, rep, params):
    """Auxiliary-array count integrity (Phase 3): each row's declared number_of_auxiliary_arrays equals
    the actual length of its auxiliary_arrays list (null count/list treated as 0). DATA_SCAN."""
    f, cc, lc = params["file"], params["count_column"], params["list_column"]
    if not (has(ar, f, cc) and has(ar, f, lc)):
        return
    sev = rule.get("severity", "error")
    bad = 0; first = None; offset = 0
    for cnt, lst in ar.iter_batches(f, cc, lc):
        cntv  = cnt.to_numpy(zero_copy_only=False)
        cnull = pc.is_null(cnt).to_numpy(zero_copy_only=False)
        lens  = pc.list_value_length(lst).to_numpy(zero_copy_only=False)
        lnull = pc.is_null(lst).to_numpy(zero_copy_only=False)
        for i in range(len(cntv)):
            declared = 0 if cnull[i] else int(cntv[i])
            actual   = 0 if lnull[i] else int(lens[i])
            if declared != actual:
                bad += 1
                if first is None: first = (offset + i, declared, actual)
        offset += len(cntv)
    if bad:
        i, d, a = first
        rep.add(rule, sev, f"{f}: number_of_auxiliary_arrays mismatch in {bad} row(s); row {i} declares "
                f"{d} but auxiliary_arrays has {a}", {"file": f, "row": i}, recovery="rederive")

def p_zip_stored(ar, rule, rep, params):
    """Container MUST (Phase 6): mzPeak ZIP members MUST be stored uncompressed (compress_type STORED).
    Directory archives have no ZIP and are skipped."""
    if ar._tmp is None or not ar.path.is_file():
        return
    sev = rule.get("severity", "error")
    try:
        with zipfile.ZipFile(ar.path) as z:
            bad = [i.filename for i in z.infolist() if i.compress_type != zipfile.ZIP_STORED]
    except Exception:
        return
    if bad:
        rep.add(rule, sev, f"{len(bad)} ZIP member(s) are compressed; mzPeak members MUST be stored "
                f"(uncompressed): {bad[:5]}", {"file": bad[0]})

def p_column_order(ar, rule, rep, params):
    """Container layout (Phase 6): the entity-index / foreign-key column MUST be the first column of its
    facet (params.expected maps facet -> required first column). Advisory by default."""
    f = params["file"]
    if not ar.has_file(f):
        return
    sev = rule.get("severity", "warning")
    expected = params.get("expected", {})
    for top in ar.pf(f).schema_arrow:
        if pa.types.is_struct(top.type) and top.name in expected and len(top.type) and top.type[0].name != expected[top.name]:
            rep.add(rule, sev, f"{f}: facet '{top.name}' first column is '{top.type[0].name}', "
                    f"expected the key '{expected[top.name]}' first", {"file": f, "facet": top.name})

PRIMITIVES = {
    "index_files_present": p_index_files_present, "columns_present": p_columns_present,
    "data_kind_facet": p_data_kind_facet, "parquet_row_group_health": p_parquet_row_group_health,
    "footer_count_equals_rows": p_footer_count_equals_rows, "column_predicate": p_column_predicate,
    "dtype_role": p_dtype_role, "grouped_monotonic": p_grouped_monotonic, "foreign_key": p_foreign_key,
    "index_contiguous": p_index_contiguous, "cv_inflection": p_cv_inflection,
    "count_sum_equals_rows": p_count_sum_equals_rows, "imaging_coordinates": p_imaging_coordinates,
    "member_exists": p_member_exists, "blob_hash": p_blob_hash, "tiff_magic": p_tiff_magic,
    "json_schema": p_json_schema, "grouped_count_equals": p_grouped_count_equals,
    "cv_list_consistency": p_cv_list_consistency, "cv_mapping": p_cv_mapping,
    "cv_mapping_json": p_cv_mapping_json,
    "chunk_columns": p_chunk_columns, "chunk_bounds": p_chunk_bounds, "aux_arrays": p_aux_arrays,
    "zip_stored": p_zip_stored, "column_order": p_column_order,
}
# blob_hash reads whole image members -> treat as a data scan (skipped by --quick); member_exists/tiff_magic are cheap
DATA_SCAN = {"column_predicate", "grouped_monotonic", "foreign_key", "index_contiguous",
             "count_sum_equals_rows", "blob_hash", "grouped_count_equals", "imaging_coordinates",
             "chunk_bounds", "aux_arrays"}

# -------------------------------------------------------------------------------- run
def run(archive_path, profile=None, profiles_root=PROFILES_ROOT, quick=False):
    ar = Archive(archive_path)
    try:
        prof_dir, note = resolve_profile(ar, profiles_root, explicit=profile)
        prof = Profile(prof_dir)
        rep = Report(prof, archive_path)
        rep.archive_info = _archive_info(ar)
        for fi in rep.archive_info:
            et = fi.get("entity_type") or ""
            dk = fi.get("data_kind") or ""
            tag = f" [{et}/{dk}]" if et or dk else ""
            facet_parts = [
                f"{fac['name']} {fac['leaf_columns']}c {fac['compression']} {'/'.join(fac['encodings'])}"
                for fac in fi.get("facets", [])
            ]
            msg = (f"{fi['name']}{tag}  {fi['rows']:,} rows  {fi['row_groups']} RG"
                   f"  {_fmt_bytes(fi['file_bytes'])}")
            if facet_parts:
                msg += "  |  " + "  |  ".join(facet_parts)
            rep.add(_SUMMARY_RULE, "info", msg, location={"file": fi["name"]})
        if note:
            rep.add({"id": "profile_resolution", "primitive": "profile_resolution"}, "warning", note)
        catalog = prof.manifest.get("rule_primitive_catalog")
        if catalog != CATALOG_VERSION:
            rep.add({"id": "catalog_version", "primitive": "catalog_version"}, "warning",
                    f"profile needs rule catalog {catalog}, engine implements {CATALOG_VERSION}")
        for rule in prof.rules:
            prim, fn = rule.get("primitive"), PRIMITIVES.get(rule.get("primitive"))
            if fn is None:
                rep.add(rule, "warning", f"unknown primitive '{prim}' (catalog mismatch?)"); continue
            if quick and prim in DATA_SCAN:
                continue
            params = dict(rule.get("params", {}))
            if prim == "cv_inflection":
                params["_cv"] = prof.cv
            elif prim == "columns_present":
                params["_columns"] = prof.columns.get(params.get("file"))
            elif prim == "json_schema":
                params["_schema"] = prof.json_schemas.get(params.get("schema"))
                params["_schema_store"] = prof._json_schema_store
                params["_cv_isa"] = getattr(prof, "cv_isa", {})
            elif prim == "footer_count_equals_rows":
                params["_quick"] = quick
            elif prim in ("cv_mapping", "cv_mapping_json"):
                params["_mapping"] = prof.mappings.get(params.get("mapping_file"))
                params["_cv_isa"] = getattr(prof, "cv_isa", {})
            elif prim == "cv_list_consistency":
                params["_cv_versions"] = {a["id"]: a.get("version") for a in prof.manifest.get("artifacts", [])
                                          if a.get("role") == "cv"}
            try:
                fn(ar, rule, rep, params)
            except Exception as e:
                rep.add(rule, "error", f"rule '{rule.get('id')}' raised {type(e).__name__}: {e}")
        return rep.to_dict()
    finally:
        ar.cleanup()

def main():
    ap = argparse.ArgumentParser(description="Validate an mzPeak archive against a versioned profile.")
    ap.add_argument("archive", help=".mzpeak file or unpacked directory")
    ap.add_argument("--profile", help="explicit profile directory (overrides version resolution)")
    ap.add_argument("--profiles-dir", default=str(PROFILES_ROOT), help="root holding mzpeak-<version> profiles")
    ap.add_argument("--json", help="write the full JSON report to this path")
    ap.add_argument("--log", help="write the human-readable findings (errors/warnings/info) to this file")
    ap.add_argument("--quick", action="store_true", help="skip full-column data scans (metadata mode)")
    a = ap.parse_args()
    try:
        report = run(a.archive, profile=a.profile, profiles_root=a.profiles_dir, quick=a.quick)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr); sys.exit(2)
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=2))
    s = report["summary"]
    lines = [f"mzPeak validation: {report['verdict']}  ({s['errors']} errors, {s['warnings']} warnings)",
             f"  archive: {report['archive']}",
             f"  profile: {report['profile']}  catalog {report['rule_primitive_catalog']}  CV {report['cv']}"]
    for f in report["findings"]:
        loc = f["location"]
        where = loc.get("file", "") + (f":{loc['column']}" if loc.get("column") else "")
        if loc.get("row") is not None: where += f"#row{loc['row']}"
        rec = f" [recover:{f['recovery']}]" if f.get("recovery") not in (None, "none") else ""
        cnt = f" (x{f['count']})" if f.get("count", 1) > 1 else ""
        lines.append(f"  {f['level'].upper():7} {f['ruleId'] or '-':28} {where}{rec}{cnt}\n           {f['message']}")
        if f.get("fix"):
            lines.append(f"           fix: {f['fix']}")
    print("\n".join(lines))
    if a.log:
        Path(a.log).write_text("\n".join(lines) + "\n")
    sys.exit(1 if s["errors"] else 0)

if __name__ == "__main__":
    main()
