"""Local web UI: visual cull + pipeline actions. Stdlib only.

Grid cull (P pick / X reject / U unflag, Enter fullscreen), plus
Grade / Meta / Export buttons that run the CLI pipeline in a
background thread with polled progress. Same on-disk semantics as
the `photo` verbs (selects/, rejects/, session.yaml).
"""

from __future__ import annotations

import json
import mimetypes
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import UserConfig
from .session import SESSION_FILENAME, Session, load_session, save_session
from .status import build_status

# view name -> session subdir accessor
def _view_dir(session: Session, view: str) -> Path:
    return {
        "proofs": session.proof_neutral_dir(),
        "graded": session.graded_dir(),
        "print": session.export_print_dir(),
        "web": session.export_web_dir(),
    }.get(view, session.proof_neutral_dir())

# job store: session path -> {state, op, log, error, updated}
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>photo cull</title>
<style>
body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:0}
header{padding:12px 16px;background:#1a1a1a;position:sticky;top:0;z-index:5;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
select,button{background:#222;color:#eee;border:1px solid #444;border-radius:6px;padding:6px 10px;font-size:14px}
button{cursor:pointer}button:hover{background:#333}
#bar{font-size:13px;color:#aaa}
#help{font-size:12px;color:#777}
#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px;padding:12px}
.fig{position:relative;cursor:pointer;border:3px solid transparent;border-radius:8px;overflow:hidden;background:#000}
.fig img{width:100%;height:220px;object-fit:cover;display:block}
.fig.focus{border-color:#888}
.fig.kept{border-color:#4caf50}
.fig.kept.focus{border-color:#8bc34a}
.fig.rejected{border-color:#c62828;opacity:.55}
.fig.rejected.focus{border-color:#ef5350}
.fig .tag{position:absolute;left:6px;bottom:6px;background:rgba(0,0,0,.7);font-size:11px;padding:2px 6px;border-radius:4px;line-height:1.5}
.fig .tag .sub{display:block;font-size:10px;color:#bbb}
.fig.kept .tag{background:#2e7d32}
.fig.rejected .tag{background:#7f0000}
#light{position:fixed;inset:0;background:rgba(0,0,0,.95);display:none;z-index:20;flex-direction:column;align-items:center;justify-content:center}
#light.open{display:flex}
#light img{max-width:96vw;max-height:88vh;object-fit:contain;border:3px solid #333;border-radius:8px}
#light.kept img{border-color:#4caf50}
#light.rejected img{border-color:#c62828}
#lightcap{margin-top:8px;font-size:14px;color:#ccc}
header.sub{background:#141414;font-size:12px}
.pill{display:inline-block;padding:2px 8px;border-radius:10px;margin-right:6px;background:#222;color:#888;border:1px solid #333}
.pill.on{background:#1b3a1b;color:#9ccc9c;border-color:#2e7d32}
#job{color:#ffcc80}
#meta-cur{font-size:12px;color:#888}
button:disabled{opacity:.4;cursor:wait}
input{background:#222;color:#eee;border:1px solid #444;border-radius:6px;padding:6px 10px;font-size:14px}
</style></head><body>
<header>
<select id="sess"></select>
<select id="view">
<option value="proofs">proofs</option>
<option value="graded">graded</option>
<option value="print">print</option>
<option value="web">web</option>
</select>
<button id="b-grade" title="develop targets with ACROS (slow, ~6s/frame)">grade</button>
<button id="b-export" title="write print + web JPEGs">export</button>
<button id="none">clear flags</button>
</header>
<header class="sub">
<input id="gps" placeholder="paste Google Maps link or LAT,LON" size="34" title="shoot location — applied to graded files">
<input id="shift" placeholder="+2h / -90m" size="10" title="shift capture dates (camera clock fix)">
<input id="kw" placeholder="keywords, comma separated" size="22">
<button id="b-meta" title="apply location + date shift + keywords to graded files">tag</button>
<span id="meta-cur"></span>
</header>
<header class="sub">
<span id="pills"></span>
<span id="job"></span>
<span id="bar"></span>
<span id="help">←→↑↓/hjkl move · F fullscreen · P pick · X reject · U unflag · Enter tag · Esc back</span>
</header>
<div id="grid"></div>
<div id="light"><img id="lightimg"><div id="lightcap"></div></div>
<script>
let SESS=null, ITEMS=[], FOCUS=0, FULL=false, VIEW='proofs', POLL=null;
async function api(u,o){const r=await fetch(u,o);if(!r.ok)throw new Error(await r.text());return r.json();}
async function loadSessions(){
  const ss=await api('/api/sessions');
  const sel=document.getElementById('sess');
  sel.innerHTML=ss.map(s=>`<option value="${s.path}">${s.date} ${s.name} (${s.raw})</option>`).join('');
  if(ss.length){SESS=sel.value;sel.onchange=()=>{SESS=sel.value;FOCUS=0;load();};load();}
  else document.getElementById('bar').textContent='no sessions — run photo import first';
}
async function load(keepFocus=true){
  const d=await api('/api/session?path='+encodeURIComponent(SESS)+'&view='+VIEW);
  ITEMS=d.items;
  if(FOCUS>=ITEMS.length)FOCUS=Math.max(0,ITEMS.length-1);
  const k=ITEMS.filter(i=>i.state==='keep').length, x=ITEMS.filter(i=>i.state==='reject').length;
  document.getElementById('bar').textContent=`${k} kept · ${x} rejected · ${ITEMS.length} shown (${VIEW})`;
  const pills=Object.entries(d.stages).map(([s,v])=>`<span class="pill${v?' on':''}">${s}</span>`).join('');
  const c=d.counts;
  document.getElementById('pills').innerHTML=pills+` <span style="color:#666">targets=${c.grade_targets} graded=${c.graded} print=${c.export_print} web=${c.export_web}</span>`;
  document.getElementById('meta-cur').textContent=
    `gps: ${d.gps||'—'} · shift: ${d.time_shift||'—'} · kw: ${(d.keywords||[]).join(', ')||'—'}`;
  render();
}
function imgUrl(i){return '/img?path='+encodeURIComponent(SESS)+'&view='+VIEW+'&file='+encodeURIComponent(i.file);}
function subLine(i){
  const bits=[];
  if(i.dt)bits.push(i.dt);
  if(i.gps)bits.push('📍'+i.gps);
  return bits.length?`<span class="sub">${bits.join(' · ')}</span>`:'';
}
function render(){
  const g=document.getElementById('grid');
  g.innerHTML=ITEMS.map((i,n)=>`<div class="fig ${i.state}${n===FOCUS?' focus':''}" data-n="${n}">
    <img loading="lazy" src="${imgUrl(i)}">
    <span class="tag">${i.stem}${i.state==='keep'?' ✓':i.state==='reject'?' ✕':''}${subLine(i)}</span></div>`).join('');
  g.querySelectorAll('.fig').forEach(el=>{
    el.onclick=()=>{FOCUS=+el.dataset.n;render();openLight();};
  });
  const cur=g.querySelector('.fig.focus');
  if(cur)cur.scrollIntoView({block:'nearest'});
  if(FULL)showLight();
}
function openLight(){FULL=true;showLight();}
function closeLight(){FULL=false;document.getElementById('light').classList.remove('open');render();}
function showLight(){
  if(!FULL||!ITEMS.length)return;
  const i=ITEMS[FOCUS], L=document.getElementById('light');
  L.classList.add('open');L.classList.remove('kept','rejected');
  if(i.state)L.classList.add(i.state==='keep'?'kept':'rejected');
  document.getElementById('lightimg').src='/img?path='+encodeURIComponent(SESS)+'&view='+VIEW+'&file='+encodeURIComponent(i.file);
  const meta=[i.dt||'no date',(i.gps?'📍'+i.gps:'no location')].join(' · ');
  document.getElementById('lightcap').textContent=`${FOCUS+1}/${ITEMS.length} ${i.stem} [${i.state||'unflagged'}] · ${meta} — P pick · X reject · U unflag · F close`;
}
async function mark(n,mark){
  const it=ITEMS[n];if(!it)return;
  await api('/api/mark',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({path:SESS,stem:it.stem,mark})});
  it.state=mark==='clear'?'':mark;it.kept=mark==='keep';
  // advance to next after flagging, Lightroom-style
  if(mark!=='clear'&&n<ITEMS.length-1)FOCUS=n+1;
  render();
  // refresh counts from server without losing focus
  api('/api/session?path='+encodeURIComponent(SESS)+'&view='+VIEW).then(d=>{
    ITEMS=d.items;
    const k=ITEMS.filter(i=>i.state==='keep').length, x=ITEMS.filter(i=>i.state==='reject').length;
    document.getElementById('bar').textContent=`${k} kept · ${x} rejected · ${ITEMS.length} shown (${VIEW})`;
    render();});
}
async function run(op){
  const job=document.getElementById('job');
  const btns=[...document.querySelectorAll('header button')];
  btns.forEach(b=>b.disabled=true);
  try{
    const body={path:SESS,op};
    if(op==='meta'){body.keywords=document.getElementById('kw').value;
      body.gps=document.getElementById('gps').value;
      body.time_shift=document.getElementById('shift').value;}
    await api('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    job.textContent=`${op} running…`;
    POLL=setInterval(async()=>{
      try{
        const j=await api('/api/job?path='+encodeURIComponent(SESS));
        if(j.state==='running'){job.textContent=`${j.op} running…`;return;}
        clearInterval(POLL);POLL=null;
        job.textContent=j.state==='done'?`${j.op} done: ${j.log}`:`${j.op} FAILED: ${j.error}`;
        load();
      }catch(e){clearInterval(POLL);POLL=null;job.textContent='poll error: '+e.message;}
      btns.forEach(b=>b.disabled=false);
    },1000);
  }catch(e){job.textContent='start failed: '+e.message;btns.forEach(b=>b.disabled=false);}
}
document.getElementById('b-grade').onclick=()=>run('grade');
document.getElementById('b-export').onclick=()=>run('export');
document.getElementById('b-meta').onclick=()=>run('meta');
document.getElementById('view').onchange=e=>{VIEW=e.target.value;FOCUS=0;FULL=false;document.getElementById('light').classList.remove('open');load();};
function move(d){
  if(!ITEMS.length)return;
  const cols=Math.max(1,Math.floor(document.getElementById('grid').offsetWidth/250));
  if(d==='left')FOCUS=Math.max(0,FOCUS-1);
  if(d==='right')FOCUS=Math.min(ITEMS.length-1,FOCUS+1);
  if(d==='up')FOCUS=Math.max(0,FOCUS-cols);
  if(d==='down')FOCUS=Math.min(ITEMS.length-1,FOCUS+cols);
  render();
}
document.addEventListener('keydown',e=>{
  if(!ITEMS.length)return;
  if(e.target.tagName==='SELECT')return;
  const k=e.key;
  if(e.target.tagName==='INPUT'){
    if(k==='Enter'){run('meta');e.preventDefault();}
    return;
  }
  if(FULL&&k==='Escape'){closeLight();e.preventDefault();return;}
  if(k==='ArrowLeft'||k==='h'){move('left');e.preventDefault();}
  else if(k==='ArrowRight'||k==='l'){move('right');e.preventDefault();}
  else if(k==='ArrowUp'||k==='k'){move('up');e.preventDefault();}
  else if(k==='ArrowDown'||k==='j'){move('down');e.preventDefault();}
  else if(k==='f'||k==='F'){FULL?closeLight():openLight();e.preventDefault();}
  else if(k==='Enter'){run('meta');e.preventDefault();}
  else if(k==='p'||k==='P'||k==='1'){mark(FOCUS,'keep');}
  else if(k==='x'||k==='X'||k==='0'||k==='Delete'){mark(FOCUS,'reject');}
  else if(k==='u'||k==='U'||k==='Backspace'){mark(FOCUS,'clear');}
});
document.getElementById('light').onclick=e=>{if(e.target.id==='light')closeLight();};
document.getElementById('none').onclick=async()=>{await api('/api/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:SESS})});FOCUS=0;load();};
loadSessions();
</script></body></html>
"""


def _sessions(cfg: UserConfig) -> list[dict]:
    root = cfg.archive_path()
    out = []
    if not root.is_dir():
        return out
    for yml in sorted(root.rglob(SESSION_FILENAME)):
        try:
            s = load_session(yml.parent)
        except Exception:
            continue
        st = build_status(s)
        out.append(
            {
                "name": s.name,
                "date": s.date,
                "path": str(s.root()),
                "raw": st["counts"].get("raw", 0),
            }
        )
    return sorted(out, key=lambda d: (d["date"], d["name"]))


def _resolve_session(cfg: UserConfig, raw: str) -> Session:
    p = Path(raw).expanduser().resolve()
    # constrain to archive root to avoid path traversal serving arbitrary files
    try:
        p.relative_to(cfg.archive_path())
    except ValueError:
        raise PermissionError(f"session outside archive: {p}")
    return load_session(p)


def _match_any(stem: str, marks: set[str]) -> bool:
    return any(s == stem or stem.endswith(s) for s in marks)


# exif cache: (session path, view) -> (dir fingerprint, {filename: {dt, gps}})
_exif_cache: dict[tuple[str, str], tuple[tuple, dict[str, dict[str, str]]]] = {}
_exif_lock = threading.Lock()


def _exif_for_view(cfg: UserConfig, session: Session, view: str,
                   files: list[Path]) -> dict[str, dict[str, str]]:
    """One batched exiftool spawn for every visible file. Cached on dir mtime.

    Returns {filename: {"dt": "2025-11-28 17:45", "gps": "48.8566, 2.3522"}}.
    Missing tags -> "". Never raises (degrades to empty on failure).
    """
    import json as _json
    import shutil as _shutil
    import subprocess as _sp

    key = (str(session.root()), view)
    try:
        fp = tuple(sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files))
    except OSError:
        return {}
    with _exif_lock:
        hit = _exif_cache.get(key)
        if hit and hit[0] == fp:
            return hit[1]
    et = cfg.tools.get("exiftool") or _shutil.which("exiftool")
    data: dict[str, dict[str, str]] = {}
    if et and files:
        try:
            proc = _sp.run(
                [et, "-j", "-fast", "-n", "-d", "%Y-%m-%d %H:%M",
                 "-DateTimeOriginal", "-GPSLatitude", "-GPSLongitude",
                 *(str(p) for p in files)],
                capture_output=True, text=True, check=False, timeout=60,
            )
            arr = _json.loads(proc.stdout or "[]")
        except Exception:
            arr = []
        for entry in arr:
            try:
                name = Path(str(entry.get("SourceFile", ""))).name
                dt = str(entry.get("DateTimeOriginal", "") or "")
                lat, lon = entry.get("GPSLatitude"), entry.get("GPSLongitude")
                gps = ""
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    gps = f"{lat:.4f}, {lon:.4f}"
                data[name] = {"dt": dt, "gps": gps}
            except Exception:
                continue
    with _exif_lock:
        _exif_cache[key] = (fp, data)
    return data


def _items(cfg: UserConfig, session: Session, view: str = "proofs") -> list[dict]:
    d = _view_dir(session, view)
    proofs = sorted(d.glob("*.jpg")) + sorted(d.glob("*.JPG"))
    stems = session.select_stems()
    kept = set(stems) if stems is not None else set()
    rejected = session.reject_stems()
    exif = _exif_for_view(cfg, session, view, proofs)
    items = []
    for proof in proofs:
        stem = proof.stem
        # graded/export files carry _print/_web suffixes; strip to raw stem
        base = stem.removesuffix("_print").removesuffix("_web")
        state = ""
        if _match_any(base, rejected) or _match_any(stem, rejected):
            state = "reject"
        elif stems is not None and (_match_any(base, kept) or _match_any(stem, kept)):
            state = "keep"
        tag = exif.get(proof.name, {})
        items.append({"stem": base, "file": proof.name, "state": state,
                      "kept": state == "keep",
                      "dt": tag.get("dt", ""), "gps": tag.get("gps", "")})
    return items


def _set_mark(session: Session, stem: str, mark: str) -> None:
    """Tri-state mark: keep -> selects/, reject -> rejects/, clear -> neither."""
    stem = Path(stem).stem
    if not stem:
        raise ValueError("missing stem")
    sel, rej = session.selects_dir(), session.rejects_dir()
    sel.mkdir(parents=True, exist_ok=True)
    rej.mkdir(parents=True, exist_ok=True)
    for d in (sel, rej):
        for p in d.iterdir():
            if p.is_file() and Path(p.name).stem == stem:
                p.unlink()
    if mark == "keep":
        (sel / stem).touch(exist_ok=True)
    elif mark == "reject":
        (rej / stem).touch(exist_ok=True)
    elif mark == "clear":
        pass
    else:
        raise ValueError(f"bad mark {mark!r}; want keep|reject|clear")
    save_session(session)


def _do_job(cfg: UserConfig, path: str, op: str, extra: dict) -> None:
    """Background worker: run one pipeline op, record outcome in _jobs."""
    from .export import run_export
    from .grade import run_grade
    from .meta import run_meta
    from .proof import run_proof

    t0 = time.time()
    try:
        s = load_session(path)
        if op == "proof":
            s = run_proof(cfg, s)
            log = f"proofs={s.counts.get('proof_neutral')}"
        elif op == "grade":
            s = run_grade(cfg, s, stock=extra.get("stock"))
            log = f"graded={s.counts.get('graded')}/{s.counts.get('grade_targets')}"
        elif op == "meta":
            kws = [k.strip() for k in str(extra.get("keywords", "")).split(",") if k.strip()]
            gps_in = (extra.get("gps") or "").strip() or None
            shift_in = (extra.get("time_shift") or "").strip() or None
            s = run_meta(cfg, s, keywords=kws, gps=gps_in, time_shift=shift_in)
            log = f"tagged={s.counts.get('meta_tagged')} gps={s.gps} shift={s.time_shift} keywords={s.keywords}"
        elif op == "export":
            s = run_export(cfg, s)
            log = f"print={s.counts.get('export_print')} web={s.counts.get('export_web')}"
        else:
            raise ValueError(f"unknown op {op!r}")
        dt = time.time() - t0
        with _jobs_lock:
            _jobs[path] = {"state": "done", "op": op, "log": f"{log} ({dt:.0f}s)",
                           "error": "", "updated": time.time()}
    except Exception as e:  # noqa: BLE001 — surfaced to UI poll
        with _jobs_lock:
            _jobs[path] = {"state": "error", "op": op, "log": "",
                           "error": str(e), "updated": time.time()}


def run_web(cfg: UserConfig, port: int = 8000) -> None:
    archive = cfg.archive_path()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body: bytes, ctype: str = "application/json"):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            if u.path in ("/", "/index.html"):
                self._send(PAGE.encode(), "text/html; charset=utf-8")
            elif u.path == "/api/sessions":
                self._send(json.dumps(_sessions(cfg)).encode())
            elif u.path == "/api/session":
                try:
                    s = _resolve_session(cfg, q.get("path", [""])[0])
                except Exception as e:
                    self.send_error(400, str(e))
                    return
                view = q.get("view", ["proofs"])[0]
                st = build_status(s)
                self._send(json.dumps({
                    "items": _items(cfg, s, view),
                    "stages": st["stages"],
                    "counts": st["counts"],
                    "keywords": s.keywords,
                    "gps": s.gps,
                    "strip_gps": s.strip_gps,
                    "time_shift": s.time_shift,
                    "views": {v: len(list(_view_dir(s, v).glob("*.jpg")))
                              + len(list(_view_dir(s, v).glob("*.JPG")))
                              for v in ("proofs", "graded", "print", "web")},
                }).encode())
            elif u.path == "/api/job":
                path = q.get("path", [""])[0]
                with _jobs_lock:
                    job = dict(_jobs.get(path, {"state": "idle"}))
                self._send(json.dumps(job).encode())
            elif u.path == "/img":
                try:
                    s = _resolve_session(cfg, q.get("path", [""])[0])
                except Exception as e:
                    self.send_error(400, str(e))
                    return
                name = Path(q.get("file", [""])[0]).name  # strip dirs
                view = q.get("view", ["proofs"])[0]
                f = _view_dir(s, view) / name
                if not f.is_file():
                    # fall back to proofs for stale clients
                    f = s.proof_neutral_dir() / name
                    if not f.is_file():
                        self.send_error(404, "no such image")
                        return
                ctype = mimetypes.guess_type(str(f))[0] or "image/jpeg"
                self._send(f.read_bytes(), ctype)
            else:
                self.send_error(404)

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            n = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                self.send_error(400, "bad json")
                return
            try:
                s = _resolve_session(cfg, str(data.get("path", "")))
            except Exception as e:
                self.send_error(400, str(e))
                return
            if u.path == "/api/select":
                # backwards compat: {stem, keep: bool}
                stem = Path(str(data.get("stem", ""))).stem
                if not stem:
                    self.send_error(400, "missing stem")
                    return
                try:
                    _set_mark(s, stem, "keep" if data.get("keep") else "clear")
                except ValueError as e:
                    self.send_error(400, str(e))
                    return
                self._send(b'{"ok":true}')
            elif u.path == "/api/mark":
                stem = str(data.get("stem", ""))
                mark = str(data.get("mark", ""))
                try:
                    _set_mark(s, stem, mark)
                except ValueError as e:
                    self.send_error(400, str(e))
                    return
                self._send(b'{"ok":true}')
            elif u.path == "/api/clear":
                for d in (s.selects_dir(), s.rejects_dir()):
                    if d.is_dir():
                        for p in d.iterdir():
                            if p.is_file() and not p.name.startswith("."):
                                p.unlink()
                save_session(s)
                self._send(b'{"ok":true}')
            elif u.path == "/api/run":
                op = str(data.get("op", ""))
                if op not in ("proof", "grade", "meta", "export"):
                    self.send_error(400, f"bad op {op!r}")
                    return
                path = str(s.root())
                with _jobs_lock:
                    cur = _jobs.get(path, {}).get("state", "idle")
                    if cur == "running":
                        self.send_error(409, f"{cur} already running")
                        return
                    _jobs[path] = {"state": "running", "op": op, "log": "",
                                   "error": "", "updated": time.time()}
                extra = {"stock": data.get("stock"), "keywords": data.get("keywords", ""),
                         "gps": data.get("gps"), "time_shift": data.get("time_shift")}
                t = threading.Thread(target=_do_job, args=(cfg, path, op, extra),
                                     daemon=True)
                t.start()
                self._send(json.dumps({"ok": True, "op": op}).encode())
            else:
                self.send_error(404)

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"cull UI: http://127.0.0.1:{port}  (archive: {archive})")
    print("Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
