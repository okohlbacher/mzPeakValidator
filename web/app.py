"""mzPeak Validator web service — FastAPI frontend for mzpeak_validator.run()."""
import asyncio
import json
import logging
import os
import sys
import tempfile
import threading
import time
from html import escape
from pathlib import Path
from urllib.parse import urlparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
    force=True,
)
log = logging.getLogger("mzpeak.web")

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse

try:
    from mzpeak_validator import run, __version__
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from mzpeak_validator import run, __version__

MAX_BYTES = 250 << 20  # 250 MiB
CHUNK     = 1 << 20

app = FastAPI(title="mzPeak Validator")


class _TooLarge(Exception):
    pass


# ── I/O helpers ────────────────────────────────────────────────────────────────

async def _save_upload(request: Request, upload: UploadFile) -> str:
    cl = request.headers.get("content-length")
    if cl and int(cl) > MAX_BYTES:
        raise _TooLarge
    fd, path = tempfile.mkstemp(suffix=".mzpeak")
    try:
        written = 0
        with os.fdopen(fd, "wb") as f:
            while True:
                chunk = await upload.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_BYTES:
                    raise _TooLarge
                f.write(chunk)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise
    return path


# ── HTML rendering ─────────────────────────────────────────────────────────────

def _fmtb(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}" if u != "B" else f"{n} B"
        n /= 1024


_STYLE = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#f8fafc;color:#0f172a;padding:2rem 1rem}
.wrap{max-width:900px;margin:0 auto}
h1{font-size:1.6rem;font-weight:700;margin-bottom:.25rem}
.sub{color:#64748b;margin-bottom:1.5rem;font-size:.95rem}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1.5rem;margin-bottom:1.5rem;box-shadow:0 1px 3px rgba(0,0,0,.05)}
label{display:block;font-weight:600;margin-bottom:.4rem;font-size:.875rem;color:#374151}
input[type=text]{width:100%;padding:.5rem .75rem;border:1px solid #d1d5db;border-radius:6px;font-size:.95rem;font-family:monospace}
input[type=file]{width:100%;padding:.4rem 0;font-size:.9rem}
.tabs{display:flex;gap:.5rem;margin-bottom:1.25rem}
.tab{padding:.35rem 1rem;border:1px solid #d1d5db;border-radius:6px;cursor:pointer;font-size:.875rem;background:#fff;color:#374151}
.tab:hover{background:#f1f5f9}
.tab.active{background:#2563eb;color:#fff;border-color:#2563eb}
.pane{display:none}.pane.active{display:block}
.hint{font-size:.8rem;color:#6b7280;margin-top:.35rem}
.check-row{display:flex;align-items:center;gap:.5rem;font-weight:400;margin-top:1rem;cursor:pointer;font-size:.9rem;color:#374151}
.check-row input{width:auto;accent-color:#2563eb}
.hint-inline{color:#6b7280;font-size:.8rem}
button[type=submit]{margin-top:1rem;padding:.5rem 1.5rem;background:#2563eb;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:.95rem;font-weight:600}
button[type=submit]:hover{background:#1d4ed8}
button[type=submit]:disabled{background:#93c5fd;cursor:not-allowed}
.verdict{font-size:1.4rem;font-weight:800;margin-bottom:.5rem}
.pass{color:#16a34a}.fail{color:#dc2626}
.counts{color:#64748b;font-size:.9rem}
/* info box */
.info-box{background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;padding:1.25rem 1.5rem;margin-bottom:1.5rem}
.info-title{font-weight:700;font-size:.78rem;color:#0369a1;text-transform:uppercase;letter-spacing:.06em;margin-bottom:.75rem}
.pf-row{margin-bottom:.7rem;padding-bottom:.7rem;border-bottom:1px solid #bae6fd}
.pf-row:last-child{margin-bottom:0;padding-bottom:0;border-bottom:none}
.pf-name{font-family:monospace;font-weight:600;font-size:.9rem;color:#0c4a6e}
.pf-tag{font-family:system-ui;font-weight:400;font-size:.75rem;color:#0369a1;margin-left:.4rem}
.pf-stats{color:#475569;font-size:.8rem;margin:.15rem 0 .4rem}
.pf-facets{display:flex;flex-wrap:wrap;gap:.3rem}
.fac{background:#e0f2fe;color:#0c4a6e;font-size:.73rem;padding:.15rem .45rem;border-radius:4px;font-family:monospace;white-space:nowrap}
.info-other{margin-top:.75rem;padding-top:.5rem;border-top:1px solid #bae6fd;font-size:.82rem;color:#0369a1}
/* findings tables */
.sect-head{font-size:.9rem;font-weight:700;margin-bottom:.75rem}
.err-head{color:#991b1b}
table{width:100%;border-collapse:collapse;font-size:.82rem}
th{background:#f1f5f9;text-align:left;padding:.45rem .7rem;border-bottom:2px solid #e2e8f0;white-space:nowrap}
td{padding:.4rem .7rem;border-bottom:1px solid #f1f5f9;vertical-align:top;word-break:break-word}
.pill{display:inline-block;padding:.1rem .45rem;border-radius:999px;font-size:.73rem;font-weight:600}
.e{background:#fee2e2;color:#991b1b}.w{background:#fef3c7;color:#92400e}
.fix{color:#6b7280;font-size:.78rem}
/* warning accordion */
details.warn-acc{background:#fff;border:1px solid #fde68a;border-radius:10px;margin-bottom:1.5rem;box-shadow:0 1px 3px rgba(0,0,0,.05)}
details.warn-acc summary{padding:1rem 1.5rem;font-weight:600;font-size:.9rem;color:#92400e;cursor:pointer;list-style:none;display:flex;justify-content:space-between;align-items:center}
details.warn-acc summary::after{content:"▸";font-size:.85rem}
details.warn-acc[open] summary::after{content:"▾"}
details.warn-acc summary::-webkit-details-marker{display:none}
.warn-body{padding:0 1.5rem 1.25rem}
/* progress */
.prog-label{font-size:.9rem;color:#374151;margin-bottom:.6rem}
.prog-count{font-weight:600;color:#2563eb}
.prog-bar-outer{height:8px;background:#e2e8f0;border-radius:4px;overflow:hidden;margin:.4rem 0 .5rem}
.prog-bar-inner{height:100%;background:#2563eb;border-radius:4px;transition:width .15s ease}
.prog-rule-name{font-family:monospace;font-size:.78rem;color:#64748b;min-height:1.2em;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
/* util */
.err-box{background:#fef2f2;border:1px solid #fca5a5;border-radius:8px;padding:1rem;color:#991b1b;margin-bottom:1rem}
.big-box{background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;padding:1rem;margin-bottom:1rem}
.big-box code{background:#f1f5f9;padding:.1rem .35rem;border-radius:4px;font-size:.85rem}
a{color:#2563eb}footer{margin-top:2rem;color:#94a3b8;font-size:.8rem}
"""

_FORM = """
<div class="card">
  <div class="tabs">
    <button type="button" class="tab active" onclick="switchTab(0)">URL</button>
    <button type="button" class="tab"        onclick="switchTab(1)">Upload file</button>
  </div>
  <form id="val-form" onsubmit="return doValidate(this)">
    <div class="pane active" id="p0">
      <label for="url">HTTPS or S3 URL</label>
      <input type="text" name="url" id="url"
             placeholder="https://example.com/run.mzpeak   or   s3://bucket/key.mzpeak">
      <p class="hint">Accepts <code>https://</code> and <code>s3://bucket/key</code>.
         AWS credentials are read from the server environment (IAM role or env vars).</p>
    </div>
    <div class="pane" id="p1">
      <label for="file">Archive file</label>
      <input type="file" name="file" id="file" accept=".mzpeak,.zip">
      <p class="hint">Max 250 MB. Larger files: use the
         <a href="https://github.com/okohlbacher/mzPeakValidator" target="_blank">CLI tool</a>.</p>
    </div>
    <label class="check-row" title="Full data-column scans; slower but finds value-level issues">
      <input type="checkbox" id="deep" name="deep" value="1">
      <span>Deep validation <span class="hint-inline">(includes full data-column scans — significantly slower!)</span></span>
    </label>
    <button type="submit" id="btn">Validate</button>
  </form>
</div>
"""

_SCRIPT = """
<script>
var activeTab = 0;
function switchTab(n) {
  activeTab = n;
  document.querySelectorAll('.tab').forEach(function(t,i){t.classList.toggle('active',i===n);});
  document.querySelectorAll('.pane').forEach(function(p,i){p.classList.toggle('active',i===n);});
}

function progressHTML(n, total, rule) {
  var pct = total ? Math.round(n / total * 100) : 0;
  var label = total ? (n + ' / ' + total + ' checks') : 'Starting…';
  return '<div class="card">' +
    '<div class="prog-label">Validating… <span class="prog-count">' + label + '</span></div>' +
    '<div class="prog-bar-outer"><div class="prog-bar-inner" style="width:' + pct + '%"></div></div>' +
    '<div class="prog-rule-name">' + (rule ? rule.replace(/&/g,'&amp;').replace(/</g,'&lt;') : '&nbsp;') + '</div>' +
    '</div>';
}

function doValidate(form) {
  var url  = (document.getElementById('url').value || '').trim();
  var fi   = document.getElementById('file');
  var deep = document.getElementById('deep').checked;
  if (activeTab === 0 && !url)        { alert('Please enter a URL.'); return false; }
  if (activeTab === 1 && !fi.files[0]){ alert('Please choose a file.'); return false; }

  var btn = document.getElementById('btn');
  btn.disabled = true; btn.textContent = 'Validating…';

  var rs = document.getElementById('result-section');
  rs.innerHTML = progressHTML(0, null, '');
  rs.scrollIntoView({behavior:'smooth', block:'nearest'});

  var fd = new FormData();
  if (deep) fd.append('deep', '1');
  if (activeTab === 0) {
    fd.append('url', url);
  } else {
    fd.append('file', fi.files[0], fi.files[0].name);
  }

  function done(html) {
    rs.innerHTML = html;
    btn.disabled = false; btn.textContent = 'Validate';
    rs.scrollIntoView({behavior:'smooth', block:'nearest'});
  }

  fetch('/validate', {method:'POST', body:fd})
    .then(function(resp) {
      var reader = resp.body.getReader();
      var dec    = new TextDecoder();
      var buf    = '';
      function pump() {
        return reader.read().then(function(chunk) {
          if (chunk.done) return;
          buf += dec.decode(chunk.value, {stream:true});
          var pos;
          while ((pos = buf.indexOf('\\n\\n')) !== -1) {
            var block = buf.slice(0, pos);
            buf = buf.slice(pos + 2);
            var evType = 'message', data = '';
            block.split('\\n').forEach(function(line) {
              if (line.slice(0,7) === 'event: ') evType = line.slice(7).trim();
              if (line.slice(0,6) === 'data: ') data  = line.slice(6);
            });
            if (!data) continue;
            try {
              var ev = JSON.parse(data);
              if (evType === 'progress') {
                rs.innerHTML = progressHTML(ev.n, ev.total, ev.rule || '');
              } else if (evType === 'result') {
                done(ev.html); return;
              }
            } catch(e) {}
          }
          return pump();
        });
      }
      return pump();
    })
    .catch(function(e) {
      done('<div class="err-box"><strong>Error:</strong> ' +
           e.message.replace(/&/g,'&amp;').replace(/</g,'&lt;') + '</div>');
    });

  return false;
}
</script>
"""


def _page(body: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>mzPeak Validator</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="wrap">
<h1>mzPeak Validator</h1>
<p class="sub">Check a <code>.mzpeak</code> archive against the HUPO-PSI specification.</p>
<div id="form-section">{_FORM}</div>
<div id="result-section">{body}</div>
<footer>
  <a href="https://github.com/okohlbacher/mzPeakValidator" target="_blank">mzPeakValidator</a>
  &nbsp;·&nbsp; v{__version__}
  &nbsp;·&nbsp; profile mzpeak-0.9
  &nbsp;·&nbsp; <a href="https://mzpeak.org" target="_blank">mzpeak.org</a>
</footer>
</div>
{_SCRIPT}
</body></html>"""


def _render_table(findings: list) -> str:
    rows = []
    for f in findings:
        loc   = f.get("location") or {}
        loc_s = escape(", ".join(f"{k}={v}" for k, v in loc.items())) if loc else "—"
        cnt   = f.get("count", 1)
        msg   = escape(f["message"])
        if cnt > 1:
            msg += f" <span style='color:#6b7280'>×{cnt}</span>"
        fix = f.get("fix") or ""
        if fix:
            msg += f'<br><span class="fix">fix: {escape(fix)}</span>'
        rows.append(
            f"<tr>"
            f"<td style='font-family:monospace;font-size:.78rem'>{escape(f.get('ruleId',''))}</td>"
            f"<td>{msg}</td>"
            f"<td style='color:#6b7280;font-family:monospace;font-size:.78rem'>{loc_s}</td>"
            f"<td style='color:#6b7280'>{escape(f.get('recovery','none'))}</td>"
            f"</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Rule</th><th>Message</th><th>Location</th><th>Recovery</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_info_box(result: dict) -> str:
    archive_info = result.get("archive_info") or []
    other_info   = [f for f in result.get("findings", [])
                    if f.get("level") == "info" and f.get("ruleId") != "archive_summary"]
    if not archive_info and not other_info:
        return ""

    pf_rows = []
    for fi in archive_info:
        et = fi.get("entity_type") or ""
        dk = fi.get("data_kind") or ""
        tag = (f'<span class="pf-tag">[{escape(et)}/{escape(dk)}]</span>'
               if et or dk else "")
        stats = (f'{fi["rows"]:,} rows &nbsp;·&nbsp; '
                 f'{fi["row_groups"]} row-group{"s" if fi["row_groups"] != 1 else ""}'
                 f' &nbsp;·&nbsp; {_fmtb(fi["file_bytes"])}')
        chips = "".join(
            f'<span class="fac">{escape(fac["name"])}: {fac["leaf_columns"]}c '
            f'{escape(fac["compression"])} {escape(" ".join(fac["encodings"]))}</span>'
            for fac in fi.get("facets", [])
        )
        pf_rows.append(
            f'<div class="pf-row">'
            f'<div class="pf-name">{escape(fi["name"])}{tag}</div>'
            f'<div class="pf-stats">{stats}</div>'
            + (f'<div class="pf-facets">{chips}</div>' if chips else "")
            + f'</div>'
        )

    other_html = ""
    if other_info:
        msgs = "".join(f"<div>{escape(f['message'])}</div>" for f in other_info)
        other_html = f'<div class="info-other">{msgs}</div>'

    return (
        f'<div class="info-box">'
        f'<div class="info-title">Archive</div>'
        + "".join(pf_rows)
        + other_html
        + f'</div>'
    )


def _result_html(result: dict) -> str:
    v  = result["verdict"]
    s  = result["summary"]
    vc = "pass" if v == "PASS" else "fail"
    prof = escape(result.get("profile") or "—")

    errors   = [f for f in result.get("findings", []) if f.get("level") == "error"]
    warnings = [f for f in result.get("findings", []) if f.get("level") == "warning"]

    verdict_html = (
        f'<div class="card">'
        f'<p class="verdict {vc}">{v}</p>'
        f'<p class="counts">'
        f'{s["errors"]} error(s) &nbsp;·&nbsp; {s["warnings"]} warning(s)'
        f' &nbsp;·&nbsp; profile {prof}'
        f'</p></div>'
    )

    err_html = ""
    if errors:
        err_html = (
            f'<div class="card">'
            f'<p class="sect-head err-head">Errors ({len(errors)})</p>'
            + _render_table(errors)
            + f'</div>'
        )

    warn_html = ""
    if warnings:
        warn_html = (
            f'<details class="warn-acc">'
            f'<summary>Warnings ({len(warnings)})</summary>'
            f'<div class="warn-body">'
            + _render_table(warnings)
            + f'</div></details>'
        )

    return (
        _render_info_box(result)
        + verdict_html
        + err_html
        + warn_html
    )


def _err_html(msg: str) -> str:
    return f'<div class="err-box"><strong>Error:</strong> {escape(msg)}</div>'


_TOO_LARGE_HTML = (
    '<div class="big-box">'
    '<strong>File exceeds the 250 MB web limit.</strong><br>'
    'For large archives use the <a href="https://github.com/okohlbacher/mzPeakValidator"'
    ' target="_blank">mzPeak Validator CLI</a>:<br>'
    '<code>pip install mzpeak-validator &amp;&amp; mzpeak-validate archive.mzpeak</code>'
    '</div>'
)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return _page()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/validate")
async def validate(
    request: Request,
    url:  str        = Form(default=""),
    file: UploadFile = File(default=None),
    deep: str        = Form(default=""),
):
    quick = not bool(deep)   # deep="" → quick mode (default); deep="1" → full scan

    path = None
    try:
        url = (url or "").strip()
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in ("s3", "http", "https"):
                return HTMLResponse(
                    _page(_err_html(f"Unsupported URL scheme '{parsed.scheme}'. Use https:// or s3://")),
                    status_code=400,
                )
            target = url
        elif file and file.filename:
            path = await _save_upload(request, file)
            target = path
        else:
            return HTMLResponse(_page(_err_html("Please provide a URL or upload a file.")), status_code=400)
    except _TooLarge:
        return HTMLResponse(_page(_TOO_LARGE_HTML), status_code=413)

    # Stream SSE: progress events while the validator runs, then a final result event.
    req_id = os.urandom(4).hex()
    t0 = time.monotonic()
    log.info("[%s] START target=%r quick=%s", req_id, str(target)[:120], quick)

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    result_holder: list = [None]
    error_holder:  list = [None]

    def _cb(event: dict) -> None:
        log.info("[%s] +%.2fs cb %s", req_id, time.monotonic() - t0, json.dumps(event))
        loop.call_soon_threadsafe(q.put_nowait, event)

    def _worker() -> None:
        log.info("[%s] +%.2fs worker thread start", req_id, time.monotonic() - t0)
        try:
            result_holder[0] = run(target, quick=quick, progress_cb=_cb)
            log.info("[%s] +%.2fs worker done", req_id, time.monotonic() - t0)
        except Exception as e:
            log.exception("[%s] +%.2fs worker error: %s", req_id, time.monotonic() - t0, e)
            error_holder[0] = e
        finally:
            log.info("[%s] +%.2fs worker sentinel", req_id, time.monotonic() - t0)
            loop.call_soon_threadsafe(q.put_nowait, None)  # sentinel

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    async def _generate():
        ka = 0
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    ka += 1
                    if ka == 1 or ka % 10 == 0:
                        log.info("[%s] +%.2fs keepalive #%d", req_id, time.monotonic() - t0, ka)
                    yield ": keepalive\n\n"  # flushes nginx proxy buffer; ignored by JS
                    continue
                if ev is None:
                    log.info("[%s] +%.2fs sentinel → building result", req_id, time.monotonic() - t0)
                    break
                yield f"event: progress\ndata: {json.dumps(ev)}\n\n"

            t.join(timeout=10)

            if error_holder[0] is not None:
                e = error_holder[0]
                log.info("[%s] +%.2fs sending error result", req_id, time.monotonic() - t0)
                html = _TOO_LARGE_HTML if isinstance(e, _TooLarge) else _err_html(str(e))
            else:
                log.info("[%s] +%.2fs sending pass/fail result", req_id, time.monotonic() - t0)
                html = _result_html(result_holder[0])

            yield f"event: result\ndata: {json.dumps({'html': html})}\n\n"
        finally:
            if path:
                Path(path).unlink(missing_ok=True)
                log.info("[%s] +%.2fs temp file removed", req_id, time.monotonic() - t0)
            log.info("[%s] +%.2fs request done", req_id, time.monotonic() - t0)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
