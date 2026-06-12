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

CATALOG_VERSION = "1.5"          # 1.1: image primitives; 1.2: list types + footer count_column; 1.3: grouped_monotonic gated on declared sorting_rank
PROFILES_ROOT = Path(__file__).parent / "profiles"
MAX_PER_RULE = 25                       # cap distinct findings per rule, then summarise the remainder

# ------------------------------------------------------------------------ archive
class Archive:
    """An mzPeak archive (zip or directory) exposing files, parquet schemas and columns."""
    def __init__(self, path):
        self.path = Path(path)
        self._tmp = None
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
        self.index = json.loads(idx.read_text()) if idx.exists() else None
        self._pf, self._col = {}, {}

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
        """Load a (<= 2-level) column as a flat pyarrow Array, cached."""
        if (name, dotted) not in self._col:
            top = dotted.split(".", 1)[0]
            col = pq.read_table(self.root / self._fname(name), columns=[top]).column(top).combine_chunks()
            if "." in dotted:
                col = col.field(dotted.split(".", 1)[1])
            self._col[(name, dotted)] = col
        return self._col[(name, dotted)]

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
        self.cv = self._load_cv()

    def _load_cv(self):
        cv = {}
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
                    elif line.startswith("is_obsolete:") and "true" in line:
                        obs = True
            if cur and not obs: accs.add(cur)
            cv[art["id"]] = accs
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

    def add(self, rule, level, message, location=None, recovery=None):
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
             "count": 1}
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
                "summary": {"errors": errs, "warnings": warns}, "findings": self.findings}

# ----------------------------------------------------------------------- primitives
INFLECT = re.compile(r"^([A-Za-z]+)_(\d+)_")

def _imaging(ar):
    if _dict(_dict((ar.index or {}).get("metadata")).get("imaging")).get("is_imaging"):
        return True
    return ar.has_file("spectra_metadata") and any("IMS_1000050" in k for k in ar.fields("spectra_metadata"))

def p_index_files_present(ar, rule, rep, params):
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
        validator = jsonschema.Draft7Validator(schema)
        errs = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    except Exception as e:                       # pragma: no cover - jsonschema absent/broken
        rep.add(rule, "warning", f"{where}: could not run JSON-Schema validation ({type(e).__name__}: {e})"); return
    sev = rule.get("severity", "error")
    for e in errs:
        loc = "/".join(str(p) for p in e.path) or "(root)"
        rep.add(rule, sev, f"{where}: schema violation at {loc}: {e.message}",
                {"file": params.get("file", ""), "column": loc})

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
    if col and has(ar, f, col):
        c = ar.column(f, col)
        actual, what = len(c) - c.null_count, f"non-null {col}"
    else:
        actual, what = ar.num_rows(f), "parquet rows"
    if iv != actual:
        rep.add(rule, "error", f"{f}: footer {key}={iv} != {what}={actual}",
                {"file": f}, recovery="rederive")

def p_column_predicate(ar, rule, rep, params):
    f, col = params["file"], params["column"]
    if not has(ar, f, col): return
    op, arr = params["op"], ar.column(f, col)
    if op == "finite":                                       # nulls (null-marking) are fine; NaN/inf VALUES are not
        ok, desc = pc.fill_null(pc.is_finite(arr), True), "non-finite (NaN/inf)"
    else:
        fn = {"ge": pc.greater_equal, "gt": pc.greater, "le": pc.less_equal, "lt": pc.less}[op]
        ok, desc = pc.fill_null(fn(arr, params.get("value")), True), f"fail {op} {params.get('value')}"
    badmask = pc.invert(ok)
    nbad = pc.sum(pc.cast(badmask, pa.int64())).as_py() or 0
    if nbad:
        i = int(np.argmax(badmask.to_numpy(zero_copy_only=False)))
        rep.add(rule, rule.get("severity", "error"),
                f"{f}.{col}: {nbad} of {len(arr)} value(s) {desc}; first at row {i} (value {arr[i].as_py()})",
                {"file": f, "column": col, "row": i})

def p_dtype_role(ar, rule, rep, params):
    f, col, allowed = params["file"], params["column"], params["allowed"]
    if not has(ar, f, col): return
    role = params.get("role", col.split(".")[-1])
    actual = str(ar.column(f, col).type)
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
    # Gate on the declared order: the spec only asserts ascending m/z when the array index gives the
    # column a sorting_rank. A column explicitly declared unsorted is conformant as-is (don't flag).
    if declared_sorted(ar, f, col) is False:
        rep.add(rule, "info", f"{f}.{col}: array index declares it unsorted (sorting_rank null/absent); "
                f"monotonicity not enforced", {"file": f, "column": col})
        return
    vcol = ar.column(f, col)
    gcol = ar.column(f, grp)
    # Keep an integer group key exact: to_numpy() on a null-containing int column yields float64,
    # collapsing distinct ids near/above 2^53 into one group. Cast through Arrow instead.
    g = (pc.fill_null(gcol.cast(pa.int64(), safe=False), -1).to_numpy(zero_copy_only=False)
         if pa.types.is_integer(gcol.type) else gcol.to_numpy(zero_copy_only=False))
    v = vcol.to_numpy(zero_copy_only=False)
    null = pc.is_null(vcol).to_numpy(zero_copy_only=False)    # Arrow nulls are legitimate (null-marking) -> skip
    if len(v) < 2: return
    order = np.argsort(g, kind="stable")                     # group rows together regardless of physical order
    gs, vs, ns = g[order], v[order], null[order]
    both = ~ns[1:] & ~ns[:-1]                                # only compare consecutive non-null pairs
    bad = (gs[1:] == gs[:-1]) & both & (vs[1:] < vs[:-1])
    if bad.any():
        j = int(np.argmax(bad))
        row, prev, cur = int(order[j + 1]), vs[j], vs[j + 1]
        gid = gs[j]
        rep.add(rule, "error",
                f"{f}.{col} not {params['direction']} within {grp}: {int(bad.sum())} inversion(s); "
                f"in {grp}={gid}, value {cur} (row {row}) < previous {prev}", {"file": f, "row": row}, recovery="reorder_pair")

def p_foreign_key(ar, rule, rep, params):
    f, col, rf, rc = params["file"], params["column"], params["ref_file"], params["ref_column"]
    if not (has(ar, f, col) and has(ar, rf, rc)): return
    parent = {x for x in ar.column(rf, rc).to_pylist() if x is not None}
    child = ar.column(f, col)
    missing = [x for x in pc.unique(child).to_pylist() if x is not None and x not in parent]
    # allow_null: in the packed parallel-facet layout a facet key is legitimately null on rows
    # belonging to another facet (e.g. scan.source_index is null on precursor-only PASEF rows).
    flag_null = child.null_count and not params.get("allow_null", False)
    if missing or flag_null:
        parts = []
        if missing: parts.append(f"{len(missing)} value(s) with no {rf}.{rc} (e.g. {missing[:3]})")
        if flag_null: parts.append(f"{child.null_count} null")
        rep.add(rule, "error", f"{f}.{col}: " + "; ".join(parts), {"file": f, "column": col})

def p_index_contiguous(ar, rule, rep, params):
    f, col = params["file"], params["column"]
    if not has(ar, f, col): return
    # ignore nulls: in the packed parallel-facet layout the spectrum facet only populates a subset
    # of rows; its index over those non-null rows must still be 0-based contiguous.
    v = pc.drop_null(ar.column(f, col)).to_numpy(zero_copy_only=False)
    expect = np.arange(len(v), dtype=np.int64)
    if len(v) and not np.array_equal(v.astype(np.int64), expect):
        i = int(np.argmax(v.astype(np.int64) != expect))
        rep.add(rule, rule.get("severity", "warning"),
                f"{f}.{col} not 0-based contiguous (len {len(v)} non-null): position {i} is {v[i]}, expected {i}",
                {"file": f, "column": col, "row": i})

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
    for e in cvl:
        if isinstance(e, dict) and e.get("id") in pinned and e.get("version") \
                and str(e["version"]) != str(pinned[e["id"]]):
            rep.add(rule, "warning", f"cv_list declares {e['id']} version {e['version']}; "
                    f"profile pins {pinned[e['id']]} (CURIEs resolve against the pinned snapshot)")

def p_count_sum_equals_rows(ar, rule, rep, params):
    """Point-layout integrity: sum of per-spectrum point counts == data-file row count."""
    f, cnt_file, cnt_col = params["file"], params.get("count_file", "spectra_metadata"), params["count_column"]
    if not (has(ar, f, params.get("guard", "point.intensity")) and has(ar, cnt_file, cnt_col)):
        return
    # null counts are treated as 0: a centroid spectrum has no profile points (its data lives in spectra_peaks)
    total = pc.sum(ar.column(cnt_file, cnt_col)).as_py() or 0
    if int(total) != ar.num_rows(f):
        rep.add(rule, "error", f"{f}: sum({cnt_col})={total} != {f} rows={ar.num_rows(f)}",
                {"file": f}, recovery="rederive")

def p_grouped_count_equals(ar, rule, rep, params):
    """Per-spectrum count integrity: the number of signal rows for each spectrum equals that
    spectrum's declared count. Stronger than count_sum_equals_rows (catches localized/swapped
    corruption that a global sum hides). Null declared count is treated as 0 (centroid spectra have
    no profile points; their data lives in spectra_peaks)."""
    f, grp = params["file"], params["group"]                      # signal table + its group column (point.spectrum_index)
    cf, cc = params.get("count_file", "spectra_metadata"), params["count_column"]
    key = params.get("key_column", "spectrum.index")
    if not (has(ar, f, params.get("guard", grp)) and has(ar, cf, cc) and has(ar, cf, key)):
        return
    g = ar.column(f, grp)
    gv = g.to_numpy(zero_copy_only=False)
    gv = gv[~pc.is_null(g).to_numpy(zero_copy_only=False)]        # signal rows have non-null group ids
    actual_ids, actual_cnt = np.unique(gv, return_counts=True)
    actual = dict(zip(actual_ids.tolist(), actual_cnt.tolist()))
    kcol = ar.column(cf, key); ccol = ar.column(cf, cc)
    kv = kcol.to_numpy(zero_copy_only=False)
    cvv = ccol.to_numpy(zero_copy_only=False)
    knull = pc.is_null(kcol).to_numpy(zero_copy_only=False)
    cnull = pc.is_null(ccol).to_numpy(zero_copy_only=False)
    bad = 0; first = None
    for i in range(len(kv)):
        if knull[i]:
            continue                                              # padding row of a packed facet
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
                rep.add(rule, "error",
                        f"{fe['name']}: index declares data_kind '{fe['data_kind']}' but the file has top-level "
                        f"columns {sorted(tops)} — none of the expected signal facets {sorted(need)}",
                        {"file": fe["name"]})

def p_imaging_coordinates(ar, rule, rep, params):
    if not _imaging(ar): return
    f = "spectra_metadata"; fields = ar.fields(f)
    has_x = any(k.endswith("IMS_1000050_position_x") for k in fields)
    has_y = any(k.endswith("IMS_1000051_position_y") for k in fields)
    if not (has_x and has_y):
        rep.add(rule, "error", "imaging archive missing position_x and/or position_y column", {"file": f}); return
    for path in [k for k in fields if k.endswith(("IMS_1000050_position_x", "IMS_1000051_position_y"))]:
        v = ar.column(f, path).to_numpy(zero_copy_only=False)
        if len(v) and np.nanmin(v) < 1:
            rep.add(rule, "error", f"{f}.{path}: minimum coordinate {np.nanmin(v):g} < 1 "
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

PRIMITIVES = {
    "index_files_present": p_index_files_present, "columns_present": p_columns_present,
    "data_kind_facet": p_data_kind_facet,
    "footer_count_equals_rows": p_footer_count_equals_rows, "column_predicate": p_column_predicate,
    "dtype_role": p_dtype_role, "grouped_monotonic": p_grouped_monotonic, "foreign_key": p_foreign_key,
    "index_contiguous": p_index_contiguous, "cv_inflection": p_cv_inflection,
    "count_sum_equals_rows": p_count_sum_equals_rows, "imaging_coordinates": p_imaging_coordinates,
    "member_exists": p_member_exists, "blob_hash": p_blob_hash, "tiff_magic": p_tiff_magic,
    "json_schema": p_json_schema, "grouped_count_equals": p_grouped_count_equals,
    "cv_list_consistency": p_cv_list_consistency,
}
# blob_hash reads whole image members -> treat as a data scan (skipped by --quick); member_exists/tiff_magic are cheap
DATA_SCAN = {"column_predicate", "grouped_monotonic", "foreign_key", "index_contiguous",
             "count_sum_equals_rows", "blob_hash", "grouped_count_equals"}

# -------------------------------------------------------------------------------- run
def run(archive_path, profile=None, profiles_root=PROFILES_ROOT, quick=False):
    ar = Archive(archive_path)
    try:
        prof_dir, note = resolve_profile(ar, profiles_root, explicit=profile)
        prof = Profile(prof_dir)
        rep = Report(prof, archive_path)
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
    print("\n".join(lines))
    if a.log:
        Path(a.log).write_text("\n".join(lines) + "\n")
    sys.exit(1 if s["errors"] else 0)

if __name__ == "__main__":
    main()
