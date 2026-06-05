#!/usr/bin/env python3
"""Smoke test for the mzPeak validator.

1. Generates the conformance fixtures into a temp dir; each must get its expected
   verdict (and fail fixtures must trip the expected rule id).
2. Validates every real .mzpeak (zip or unpacked dir) found in the corpus dirs
   (env var MZPEAK_CORPUS, os.pathsep-separated; otherwise a sensible default).

Profiles are selected via version resolution (no explicit --profile).
Exit 0 if all fixture expectations hold, else 1.
"""
import glob, json, os, sys, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mzpeak_validator import run
import make_fixtures

def corpus_dirs():
    env = os.environ.get("MZPEAK_CORPUS")
    if env:
        return [p for p in env.split(os.pathsep) if p]
    # convenience default: example data from the sibling imzML2mzPeak project, if present
    base = os.path.expanduser("~/Claude/imzML2mzPeak/data")
    return [os.path.join(base, "imzml-examples"), os.path.join(base, "mzml-examples")]

def err_rules(rep):
    return [f["ruleId"] for f in rep["findings"] if f["level"] == "error"]

def warn_rules(rep):
    return [f["ruleId"] for f in rep["findings"] if f["level"] == "warning"]

def short(rep):
    s = rep["summary"]; return f"{rep['verdict']} ({s['errors']}E/{s['warnings']}W)"

def main():
    ok = True
    tmp = tempfile.mkdtemp(prefix="mzpeak_fixtures_")
    try:
        make_fixtures.build_all(tmp)
        print("== fixtures ==")
        for exp_path in sorted(glob.glob(f"{tmp}/*/*/expected.json")):
            d = os.path.dirname(exp_path)
            exp = json.load(open(exp_path))
            rep = run(d)
            name = os.path.relpath(d, tmp)
            passed = (rep["verdict"] == exp["verdict"]
                      and (exp["verdict"] != "FAIL" or exp.get("rule") in err_rules(rep))
                      and (not exp.get("warn_rule") or exp["warn_rule"] in warn_rules(rep)))
            ok = ok and passed
            want = exp.get("rule") or exp.get("warn_rule")
            extra = "" if passed else f"   <-- expected {exp['verdict']}/{want}, got {short(rep)} E{err_rules(rep)} W{warn_rules(rep)}"
            print(f"  [{'ok ' if passed else 'FAIL'}] {name:28} {short(rep)}{extra}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n== real .mzpeak corpus ==")
    found = []
    for r in corpus_dirs():
        found += sorted(glob.glob(os.path.join(r, "*.mzpeak")))
        found += [d for d in sorted(glob.glob(os.path.join(r, "*.mzpeak/"))) if os.path.isdir(d)]
    if not found:
        print("  (none found; set MZPEAK_CORPUS to a dir of .mzpeak files)")
    for a in found:
        big = os.path.isfile(a) and os.path.getsize(a) > 50_000_000
        rep = run(a, quick=big)
        print(f"  {short(rep):14} {a}{' [quick]' if big else ''}")
        for f in rep["findings"]:
            if f["level"] == "error":
                print(f"      ERROR {f['ruleId']}: {f['message']}")

    print("\nRESULT:", "PASS — all fixture expectations met" if ok else "FAIL — see mismatches above")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
