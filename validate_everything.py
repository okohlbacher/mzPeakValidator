#!/usr/bin/env python
"""
validate_everything.py — full-corpus mzPeak validation at maximum sensitivity.

WHAT IT DOES
  Scans  ~/Claude/mzPeak/data/**/*.mzpeak  (recursively), runs the validator
  on EVERY file at FULL sensitivity (never --quick — all DATA_SCAN primitives run),
  then writes two artifacts into  ~/Claude/mzPeak/data/validator_logs/ :

    1. run-<START>.log         — live progress log; tail -f it to monitor.
    2. validation-<END>.md     — the handover report, stamped with the date+time
                                 the analysis FINISHED (e.g. validation-2026-06-15-1120.md).

  The report carries: summary statistics, per-source breakdown, a classification of
  every error rule (the FAIL drivers) and every warning rule, distinct failure
  fingerprints, and the explicit lists of failing / engine-error / timeout files.

USAGE
    python validate_everything.py                 # the standard "validate everything" run
    python validate_everything.py --workers 4 --timeout 1800
    python validate_everything.py --data-root /some/dir --out-dir /some/logs

  Exit code: 0 if all PASS, 1 if any FAIL, 2 if any engine error / timeout.

DESIGN NOTES
  * MAX SENSITIVITY IS THE CONTRACT: --quick is never passed, for any file, at any
    size. Large files (multi-GB) are slow on purpose; per-file --timeout is the guard.
  * Each file is validated in its own subprocess (memory isolation for multi-GB files).
  * The progress log is line-buffered and flushed per file so it is monitorable live.
"""
import argparse, json, os, subprocess, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict, Counter
from datetime import datetime

DEFAULT_DATA_ROOT = os.path.expanduser("~/Claude/mzPeak/data")
DEFAULT_OUT_DIR   = os.path.expanduser("~/Claude/mzPeak/data/validator_logs")
VALIDATOR_REPO    = os.path.dirname(os.path.abspath(__file__))


def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024.0


def enumerate_corpus(data_root, out_dir=None):
    out_abs = os.path.abspath(out_dir or DEFAULT_OUT_DIR)
    files = []
    for dirpath, _, fnames in os.walk(data_root):
        if os.path.abspath(dirpath).startswith(out_abs):
            continue
        for fn in fnames:
            if fn.endswith(".mzpeak"):
                files.append(os.path.join(dirpath, fn))
    files.sort()
    return files


def validate_one(path, timeout):
    """Run the validator (FULL sensitivity — no --quick) on one file."""
    size = os.path.getsize(path)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        jp = tf.name
    t0 = time.time()
    try:
        cmd = [sys.executable, "-m", "mzpeak_validator", path, "--json", jp]  # NO --quick
        env = dict(os.environ); env["PYTHONWARNINGS"] = "ignore"
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=env, cwd=VALIDATOR_REPO)
        elapsed = time.time() - t0
        if r.returncode == 2:
            return {"path": path, "size": size, "elapsed": elapsed, "verdict": "ENGINE_ERROR",
                    "profile": None, "catalog": None, "findings": [],
                    "stderr": (r.stderr or r.stdout)[:600]}
        with open(jp) as jf:
            data = json.load(jf)
        findings = [{"ruleId": f.get("ruleId", "?"), "level": f.get("level", "?"),
                     "primitive": f.get("primitive", "?"), "message": f.get("message", ""),
                     "location": f.get("location", {})}
                    for f in data.get("findings", [])]
        return {"path": path, "size": size, "elapsed": elapsed,
                "verdict": data.get("verdict", "UNKNOWN"),
                "profile": data.get("profile"),
                "catalog": data.get("rule_primitive_catalog"),
                "findings": findings, "stderr": ""}
    except subprocess.TimeoutExpired:
        return {"path": path, "size": size, "elapsed": time.time() - t0, "verdict": "TIMEOUT",
                "profile": None, "catalog": None, "findings": [], "stderr": f"timeout after {timeout}s"}
    except Exception as e:
        return {"path": path, "size": size, "elapsed": time.time() - t0, "verdict": "ENGINE_ERROR",
                "profile": None, "catalog": None, "findings": [], "stderr": str(e)[:600]}
    finally:
        try: os.unlink(jp)
        except OSError: pass


def source_of(path, data_root):
    rel = os.path.relpath(path, data_root)
    return rel.split(os.sep)[0]


def build_report(results, data_root, start_dt, end_dt, wall_s, settings):
    total = len(results)
    vc = Counter(r["verdict"] for r in results)
    n_pass = vc.get("PASS", 0); n_fail = vc.get("FAIL", 0)
    n_eng  = vc.get("ENGINE_ERROR", 0); n_to = vc.get("TIMEOUT", 0)

    # profile / catalog (from first file that reported one)
    profile = catalog = None
    for r in results:
        if r.get("profile"): profile, catalog = r["profile"], r["catalog"]; break

    # per-source
    ss = defaultdict(Counter)
    for r in results:
        ss[source_of(r["path"], data_root)][r["verdict"]] += 1

    # classify findings
    err_files = defaultdict(set); err_prim = {}; err_msgs = defaultdict(list)
    warn_files = defaultdict(set); warn_prim = {}; warn_msgs = defaultdict(list)
    for r in results:
        for f in r["findings"]:
            if f["level"] == "error":
                err_files[f["ruleId"]].add(r["path"]); err_prim[f["ruleId"]] = f["primitive"]
                if len(err_msgs[f["ruleId"]]) < 3: err_msgs[f["ruleId"]].append(f["message"])
            elif f["level"] == "warning":
                warn_files[f["ruleId"]].add(r["path"]); warn_prim[f["ruleId"]] = f["primitive"]
                if len(warn_msgs[f["ruleId"]]) < 3: warn_msgs[f["ruleId"]].append(f["message"])

    # failure fingerprints
    fp = Counter()
    for r in results:
        if r["verdict"] == "FAIL":
            fp[tuple(sorted({f["ruleId"] for f in r["findings"] if f["level"] == "error"}))] += 1

    L = []
    w = L.append
    w(f"# mzPeak full-corpus validation — {end_dt:%Y-%m-%d %H:%M}")
    w("")
    w(f"**Generated:** {end_dt:%Y-%m-%d %H:%M:%S %Z} (analysis end) · "
      f"**Started:** {start_dt:%Y-%m-%d %H:%M:%S} · **Wall time:** {wall_s/60:.1f} min")
    w(f"**Validator:** profile `{profile}` · catalog `{catalog}` · "
      f"repo `{VALIDATOR_REPO}`")
    w(f"**Corpus root:** `{data_root}`  ·  **Files:** {total}")
    w(f"**Sensitivity:** MAXIMUM — full scan on every file, `--quick` never used "
      f"(per-file timeout {settings['timeout']}s, {settings['workers']} workers)")
    w("")
    w("## Summary")
    w("")
    w("| Verdict | Files | % |")
    w("|---|---:|---:|")
    for v in ("PASS", "FAIL", "ENGINE_ERROR", "TIMEOUT"):
        n = vc.get(v, 0)
        if n or v in ("PASS", "FAIL"):
            w(f"| {v} | {n} | {100*n/total:.1f}% |")
    w("")
    verdict_line = ("✅ **All files PASS.**" if n_fail == n_eng == n_to == 0
                    else f"⚠️ **{n_fail} FAIL"
                         + (f", {n_eng} engine-error" if n_eng else "")
                         + (f", {n_to} timeout" if n_to else "") + ".**")
    w(verdict_line)
    w("")
    # timing
    slowest = sorted(results, key=lambda r: -r["elapsed"])[:5]
    w(f"Largest/slowest scans: " + ", ".join(
        f"`{os.path.relpath(r['path'], data_root)}` ({human_bytes(r['size'])}, {r['elapsed']:.0f}s)"
        for r in slowest))
    w("")
    w("## Per-source breakdown")
    w("")
    w("| Source | Files | PASS | FAIL | ENGINE_ERROR | TIMEOUT |")
    w("|---|---:|---:|---:|---:|---:|")
    for s in sorted(ss):
        c = ss[s]
        w(f"| {s} | {sum(c.values())} | {c.get('PASS',0)} | {c.get('FAIL',0)} | "
          f"{c.get('ENGINE_ERROR',0)} | {c.get('TIMEOUT',0)} |")
    w("")

    # ── failure classification ──
    w("## Failure classification (error-level rules — drive the FAIL verdict)")
    w("")
    if not err_files:
        w("**None.** No error-level findings anywhere in the corpus.")
    else:
        w("| Error rule | Primitive | Files |")
        w("|---|---|---:|")
        for rule, fs in sorted(err_files.items(), key=lambda kv: -len(kv[1])):
            w(f"| `{rule}` | `{err_prim[rule]}` | {len(fs)} |")
        w("")
        for rule, fs in sorted(err_files.items(), key=lambda kv: -len(kv[1])):
            w(f"### `{rule}` — {len(fs)} files")
            w("")
            w("Example messages:")
            for m in err_msgs[rule]:
                w(f"- {m[:240]}")
            w("")
    w("")
    w("### Distinct failure fingerprints (set of error rules per failing file)")
    w("")
    if not fp:
        w("_(no failing files)_")
    else:
        w("| Count | Error-rule set |")
        w("|---:|---|")
        for rules, n in fp.most_common():
            w(f"| {n} | {', '.join('`'+r+'`' for r in rules) or '_(empty)_'} |")
    w("")

    # ── warning classification ──
    w("## Warning classification (do not affect verdict)")
    w("")
    if not warn_files:
        w("**None.**")
    else:
        w("| Warning rule | Primitive | Files |")
        w("|---|---|---:|")
        for rule, fs in sorted(warn_files.items(), key=lambda kv: -len(kv[1])):
            w(f"| `{rule}` | `{warn_prim[rule]}` | {len(fs)} |")
        w("")
        for rule, fs in sorted(warn_files.items(), key=lambda kv: -len(kv[1])):
            w(f"### `{rule}` — {len(fs)} files")
            w("")
            w("Example messages:")
            for m in warn_msgs[rule]:
                w(f"- {m[:240]}")
            w("")
    w("")

    # ── explicit lists ──
    fails = [r for r in results if r["verdict"] == "FAIL"]
    probs = [r for r in results if r["verdict"] in ("ENGINE_ERROR", "TIMEOUT")]
    if fails:
        w(f"## Failing files ({len(fails)})")
        w("")
        for r in fails:
            rel = os.path.relpath(r["path"], data_root)
            rules = sorted({f["ruleId"] for f in r["findings"] if f["level"] == "error"})
            w(f"- `{rel}` — errors: {', '.join(rules)}")
        w("")
    if probs:
        w(f"## Engine errors / timeouts ({len(probs)})")
        w("")
        for r in probs:
            rel = os.path.relpath(r["path"], data_root)
            w(f"- **{r['verdict']}** `{rel}` ({human_bytes(r['size'])}) — {r['stderr'][:200]}")
        w("")

    w("---")
    w(f"_Generated by `validate_everything.py` · {total} files · {wall_s/60:.1f} min wall · "
      f"PASS={n_pass} FAIL={n_fail} ENGINE_ERROR={n_eng} TIMEOUT={n_to}_")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Full-corpus mzPeak validation at maximum sensitivity.")
    ap.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    ap.add_argument("--out-dir",   default=DEFAULT_OUT_DIR)
    ap.add_argument("--workers",   type=int, default=4)
    ap.add_argument("--timeout",   type=int, default=1800, help="per-file timeout (s)")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    start_dt = datetime.now()
    start_stamp = start_dt.strftime("%Y-%m-%d-%H%M%S")
    log_path = os.path.join(args.out_dir, f"run-{start_stamp}.log")

    files = enumerate_corpus(args.data_root, args.out_dir)
    total = len(files)

    log_lock = threading.Lock()
    logf = open(log_path, "w", buffering=1)  # line-buffered

    def log(msg):
        line = f"{datetime.now():%H:%M:%S}  {msg}"
        with log_lock:
            logf.write(line + "\n"); logf.flush()
            print(line, flush=True)

    log(f"START full-corpus validation (MAX sensitivity, no --quick)")
    log(f"  data-root = {args.data_root}")
    log(f"  files     = {total}")
    log(f"  workers   = {args.workers}  timeout = {args.timeout}s")
    log(f"  log       = {log_path}")
    log("-" * 60)

    if total == 0:
        log("No .mzpeak files found — nothing to do.")
        logf.close(); return 0

    results = []; done = [0]; tally = Counter()
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(validate_one, p, args.timeout): p for p in files}
        for fut in as_completed(futs):
            r = fut.result(); results.append(r)
            tally[r["verdict"]] += 1
            with log_lock:
                done[0] += 1; n = done[0]
            rel = os.path.relpath(r["path"], args.data_root)
            nerr = sum(1 for f in r["findings"] if f["level"] == "error")
            nwarn = sum(1 for f in r["findings"] if f["level"] == "warning")
            log(f"[{n:>4}/{total}] {r['verdict']:<12} ({r['elapsed']:5.1f}s {human_bytes(r['size']):>8}) "
                f"e={nerr} w={nwarn}  {rel}")
            if n % 50 == 0 or n == total:
                log(f"    … running tally: " + " ".join(f"{k}={v}" for k, v in tally.most_common()))

    results.sort(key=lambda r: r["path"])
    wall_s = time.time() - t_start
    end_dt = datetime.now()

    log("-" * 60)
    log(f"DONE in {wall_s/60:.1f} min  ·  " + " ".join(f"{k}={v}" for k, v in tally.most_common()))

    # write handover, stamped with END time
    end_stamp = end_dt.strftime("%Y-%m-%d-%H%M")
    report_path = os.path.join(args.out_dir, f"validation-{end_stamp}.md")
    # avoid clobber if two runs finish in the same minute
    if os.path.exists(report_path):
        report_path = os.path.join(args.out_dir, f"validation-{end_dt:%Y-%m-%d-%H%M%S}.md")
    settings = {"workers": args.workers, "timeout": args.timeout}
    report = build_report(results, args.data_root, start_dt, end_dt, wall_s, settings)
    with open(report_path, "w") as fh:
        fh.write(report + "\n")
    # machine-readable sidecar
    json_path = report_path[:-3] + ".json"
    with open(json_path, "w") as fh:
        json.dump(results, fh)

    log(f"HANDOVER → {report_path}")
    log(f"JSON     → {json_path}")
    logf.close()

    if tally.get("ENGINE_ERROR", 0) or tally.get("TIMEOUT", 0):
        return 2
    return 1 if tally.get("FAIL", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
