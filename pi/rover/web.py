#!/usr/bin/env python3
"""
web.py — remote control for the rover, served from the Pi, reachable through a Cloudflare tunnel.

    venv/bin/python web.py                 # http://<pi>:8080/?k=<key>   (key printed at start, also in ~/rover/web.key)

Controls: hold-to-drive buttons (8 directions + rotate), keyboard (W A S D strafe, Q E rotate, arrows = diagonals,
space = stop), speed slider, crab-circle button, microstep selector (must match the caps under the drivers).
Safety: every drive command needs the key; if the browser stops sending for 0.6 s the rover stops; the R4 itself
stops 400 ms after the Pi goes quiet.
"""
import json
import math
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from r4 import R4

PORT = int(os.environ.get("ROVER_PORT", "8080"))
KEY_FILE = os.path.expanduser("~/rover/web.key")
K_MM = 125.0 + 215.5                 # half wheelbase + half track: wz = v / K_MM spins each wheel at v

if os.path.exists(KEY_FILE):
    KEY = open(KEY_FILE).read().strip()
else:
    KEY = secrets.token_urlsafe(9)
    open(KEY_FILE, "w").write(KEY)

r4 = R4()
state = {"last_cmd": 0.0, "mode": "idle", "cmd": "stop", "circle": None, "t0": time.time()}
lock = threading.Lock()


def drive(vx, vy, wz, label):
    with lock:
        state["mode"] = "drive"; state["cmd"] = label; state["last_cmd"] = time.time()
    r4.velocity(vx, vy, wz)


def stop():
    with lock:
        state["mode"] = "idle"; state["cmd"] = "stop"; state["circle"] = None
    r4.stop()


def circle_thread(radius, v, laps, ccw):
    period = 2 * math.pi * radius / v
    t0 = time.time()
    with lock:
        state["mode"] = "circle"; state["cmd"] = f"crab circle r={radius:.0f} v={v:.0f}"; state["circle"] = t0
    while True:
        with lock:
            if state["circle"] != t0:
                return
        t = time.time() - t0
        if t >= period * laps:
            break
        th = 2 * math.pi * t / period * (1 if ccw else -1)
        r4.velocity(v * math.cos(th), v * math.sin(th), 0.0)
        time.sleep(0.05)
    stop()


def watchdog():
    while True:
        time.sleep(0.1)
        with lock:
            stale = state["mode"] == "drive" and time.time() - state["last_cmd"] > 0.6
        if stale:
            stop()


threading.Thread(target=watchdog, daemon=True).start()


def status():
    s = dict(r4.status)
    with lock:
        s.update(mode=state["mode"], cmd=state["cmd"], uptime=round(time.time() - state["t0"]), port=r4.port)
    return s


PAGE = r"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Hound remote</title><style>
body{margin:0;background:#0f151b;color:#e6ebf0;font:16px system-ui,sans-serif}main{max-width:760px;margin:0 auto;padding:14px}
h1{font-size:18px;margin:0 0 10px;color:#93a1ae;font-weight:600}
.pad{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}
button{font:inherit;font-size:17px;padding:20px 6px;border:1px solid #2a3641;border-radius:8px;background:#172029;color:#e6ebf0;touch-action:none;user-select:none;cursor:pointer}
button:active,button.on{background:#2e5c8a;border-color:#7fb0e0}button.stop{background:#8a1f1f;border-color:#ff8a4c;font-weight:700}
.row{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:10px 0;font-size:14px}label{display:flex;gap:8px;align-items:center}
input[type=range]{width:200px}select,input[type=number]{font:inherit;background:#172029;color:#e6ebf0;border:1px solid #2a3641;border-radius:4px;padding:4px}
.w{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:8px 0}.w div{background:#172029;border-radius:6px;padding:6px;text-align:center;font-family:ui-monospace,monospace;font-size:13px}
.w b{display:block;font-size:15px;color:#93a1ae}#st{font-family:ui-monospace,monospace;font-size:12px;color:#93a1ae;white-space:pre-wrap}
.mt{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:8px 0}.mt div{background:#172029;border-radius:6px;padding:6px;text-align:center}.mt b{display:block;font-size:15px;color:#93a1ae;margin-bottom:6px}.mt small{display:block;color:#93a1ae;font-size:12px;font-family:ui-monospace,monospace}.mt button{width:100%;padding:12px 4px;font-size:15px;margin:2px 0}.mt button.inv{font-size:12px;padding:6px 4px;color:#93a1ae}
#tall{padding:8px 14px;font-size:14px}#tst{font-size:13px;color:#93a1ae}
.warn{color:#ff8a4c;font-size:13px}kbd{background:#2a3641;border-radius:3px;padding:0 5px;font-family:ui-monospace,monospace}
</style></head><body><main>
<h1>Hound remote</h1>
<div class=row>
 <label>speed <input id=sp type=range min=20 max=530 value=415> <span id=spv>415</span> mm/s</label>
 <label>microsteps <select id=ms><option>16<option selected>32</select></label>
 <label><input id=hold type=checkbox> hold drivers</label>
 <label>tilt <input id=tilt type=range min=78 max=150 value=92> <span id=tiltv>90</span>° <button id=tiltoff style="padding:4px 8px;font-size:12px">release</button></label>
 <label><button id=show style="padding:6px 12px">▶ Ceres show</button></label>
 <label>pan <button id=nudgeL style="padding:6px 12px">◀ left</button><button id=panStop style="padding:6px 12px">■</button><button id=nudgeR style="padding:6px 12px">right ▶</button> <span id=panv style="color:#93a1ae;font-size:12px">hold to keep turning · 300 ms nudges (Ceres)</span></label>
 <span id=lat></span>
</div>
<div class=pad>
 <button data-v="1,1,0">◤ fwd-left</button><button data-v="1,0,0">▲ forward</button><button data-v="1,-1,0">◥ fwd-right</button>
 <button data-v="0,1,0">◀ strafe L</button><button class=stop id=stop>STOP</button><button data-v="0,-1,0">strafe R ▶</button>
 <button data-v="-1,1,0">◣ back-left</button><button data-v="-1,0,0">▼ back</button><button data-v="-1,-1,0">◢ back-right</button>
 <button data-v="0,0,1">⟲ rotate L</button><button id=circle>◯ crab circle</button><button data-v="0,0,-1">rotate R ⟳</button>
</div>
<div class=row>
 <label>circle radius <input id=cr type=number value=150 min=50 max=600 step=10> mm</label>
 <label>laps <input id=cl type=number value=1 min=1 max=10 step=1></label>
 <label><input id=ccw type=checkbox checked> counter-clockwise</label>
</div>
<div class=w id=wheels></div>
<h1 style="margin-top:16px">Motor test</h1>
<div class=row><label>test speed <input id=js type=number value=120 min=20 max=530 step=10> mm/s</label><button id=tall>▶ run all four (fwd 1.5 s each)</button><span id=tst></span></div>
<div class=mt id=motors></div>
<p id=st>connecting…</p>
<p class=warn id=note></p>
<p style="font-size:13px;color:#93a1ae">Keys: <kbd>W</kbd><kbd>S</kbd> forward/back · <kbd>A</kbd><kbd>D</kbd> strafe · <kbd>Q</kbd><kbd>E</kbd> rotate · arrows = diagonals · <kbd>space</kbd> stop. Hold to move; release stops. Going faster than the slider allows means moving the caps under the drivers to M2 only (1/16) and picking 16 above.</p>
</main><script>
const K=new URLSearchParams(location.search).get('k')||'';const W=['FL','FR','BL','BR'];const DRV=['Y','A','X','Z'];
let cur=null,curJ=null,timer=null,lastT=0;
const api=(p)=>fetch('/api/'+p+(p.includes('?')?'&':'?')+'k='+encodeURIComponent(K)).then(r=>r.json()).then(show).catch(()=>{document.getElementById('st').textContent='no link';});
const v=()=>+document.getElementById('sp').value;
function send(){if(!cur)return;const s=v();const t=performance.now();
 api(`v?vx=${cur[0]*s}&vy=${cur[1]*s}&wz=${cur[2]*s/340.5}`).then(()=>{document.getElementById('lat').textContent='round trip '+Math.round(performance.now()-t)+' ms';});}
function start(c){cur=c;send();clearInterval(timer);timer=setInterval(send,120);}
function stop(){cur=null;curJ=null;clearInterval(timer);api('stop');}
const js=()=>+document.getElementById('js').value;
function sendJ(){if(!curJ)return;api(`jog?w=${curJ[0]}&d=${curJ[1]}&s=${js()}`);}
function startJ(j){cur=null;curJ=j;sendJ();clearInterval(timer);timer=setInterval(sendJ,120);}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function testAll(){const b=document.getElementById('tall'),o=document.getElementById('tst');b.disabled=true;
 for(let i=0;i<4;i++){o.textContent='running '+W[i]+' (driver '+DRV[i]+') forward…';const t0=performance.now();
  while(performance.now()-t0<1500){await api(`jog?w=${i}&d=1&s=${js()}`);await sleep(120);}await api('stop');await sleep(500);}
 o.textContent='done — order was FL, FR, BL, BR; each should have rolled forward';b.disabled=false;}
function bind(b,c){b.addEventListener('pointerdown',e=>{e.preventDefault();b.classList.add('on');start(c);});
 ['pointerup','pointerleave','pointercancel'].forEach(ev=>b.addEventListener(ev,()=>{b.classList.remove('on');if(cur)stop();}));}
document.querySelectorAll('button[data-v]').forEach(b=>bind(b,b.dataset.v.split(',').map(Number)));
document.getElementById('stop').addEventListener('pointerdown',stop);
const mo=document.getElementById('motors');W.forEach((n,i)=>{const d=document.createElement('div');
 d.innerHTML='<b>'+n+'</b><small>driver '+DRV[i]+' <span id=mi'+i+'></span></small><button data-j="'+i+',1">▲ fwd</button><button data-j="'+i+',-1">▼ back</button><button class=inv data-i='+i+'>flip direction</button>';mo.append(d);});
document.querySelectorAll('button[data-j]').forEach(b=>{const j=b.dataset.j.split(',').map(Number);
 b.addEventListener('pointerdown',e=>{e.preventDefault();b.classList.add('on');startJ(j);});
 ['pointerup','pointerleave','pointercancel'].forEach(ev=>b.addEventListener(ev,()=>{b.classList.remove('on');if(curJ)stop();}));});
document.querySelectorAll('button.inv').forEach(b=>b.addEventListener('click',()=>{const i=+b.dataset.i;if(confirm('Flip '+W[i]+' (driver '+DRV[i]+') direction? Saved on the R4.'))api('set?inv='+i);}));
document.getElementById('tall').addEventListener('click',testAll);
document.getElementById('circle').addEventListener('click',()=>api(`circle?r=${document.getElementById('cr').value}&v=${v()}&laps=${document.getElementById('cl').value}&ccw=${document.getElementById('ccw').checked?1:0}`));
document.getElementById('sp').oninput=e=>document.getElementById('spv').textContent=e.target.value;
document.getElementById('ms').onchange=e=>api('set?ms='+e.target.value);
document.getElementById('hold').onchange=e=>api('set?hold='+(e.target.checked?1:0));
document.getElementById('tilt').oninput=e=>{document.getElementById('tiltv').textContent=e.target.value;};
document.getElementById('tilt').onchange=e=>api('set?tilt='+e.target.value);
document.getElementById('tiltoff').onclick=()=>api('set?tilt=-1');
let panTimer=null;function panHold(b,dir){b.addEventListener('pointerdown',e=>{e.preventDefault();b.classList.add('on');api('set?nudge='+dir+'&ms=300');clearInterval(panTimer);panTimer=setInterval(()=>api('set?nudge='+dir+'&ms=300'),320);});
 ['pointerup','pointerleave','pointercancel'].forEach(ev=>b.addEventListener(ev,()=>{b.classList.remove('on');clearInterval(panTimer);panTimer=null;}));}
panHold(document.getElementById('nudgeL'),-1);panHold(document.getElementById('nudgeR'),1);
document.getElementById('panStop').onclick=()=>{clearInterval(panTimer);api('set?pan=0');};
let showOn=false;document.getElementById('show').onclick=()=>{showOn=!showOn;document.getElementById('show').textContent=showOn?'■ stop show':'▶ Ceres show';api('set?show='+(showOn?1:0));};
const keys={w:[1,0,0],s:[-1,0,0],a:[0,1,0],d:[0,-1,0],q:[0,0,1],e:[0,0,-1],arrowup:[1,1,0],arrowright:[1,-1,0],arrowdown:[-1,-1,0],arrowleft:[-1,1,0]};
let held=null;
window.addEventListener('keydown',e=>{const k=e.key.toLowerCase();if(k===' '){e.preventDefault();held=null;stop();return;}
 if(keys[k]&&held!==k){e.preventDefault();held=k;start(keys[k]);}});
window.addEventListener('keyup',e=>{const k=e.key.toLowerCase();if(held===k){held=null;stop();}});
const wh=document.getElementById('wheels');W.forEach((n,i)=>{const d=document.createElement('div');d.innerHTML='<b>'+n+' · '+DRV[i]+'</b><span id=r'+i+'>0</span>';wh.append(d);});
function show(s){if(!s||!s.rate)return;W.forEach((n,i)=>{const r=s.rate[i];document.getElementById('r'+i).textContent=(r>0?'▲ ':r<0?'▼ ':'· ')+Math.abs(r);document.getElementById('mi'+i).textContent=s.inv&&s.inv[i]?'· flipped':'';});
 document.getElementById('ms').value=s.ms;document.getElementById('sp').max=Math.floor(s.maxmm||190);
 document.getElementById('st').textContent=`${s.mode} · ${s.cmd} · pack ${s.vbat>5?s.vbat.toFixed(1)+' V'+(s.lv?' LOW — DRIVE LOCKED':''):'n/a'} · drivers ${s.en?'ON':'off'} · ${s.spm} steps/mm · max ${Math.floor(s.maxmm)} mm/s · R4 ${s.port||''} · pi up ${s.uptime}s`;
 document.getElementById('note').textContent=s.wd?'R4 watchdog tripped (link went quiet) — it stopped itself':'';}
setInterval(()=>{if(!cur&&!curJ)api('status');},700);api('status');
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            b = PAGE.encode(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        if not u.path.startswith("/api/"):
            self._json({"error": "not found"}, 404); return
        if q.get("k") != KEY:
            self._json({"error": "bad key"}, 403); return
        f = lambda k, d=0.0: float(q.get(k, d))
        ep = u.path[5:]
        try:
            if ep == "status":
                pass
            elif ep == "v":
                drive(f("vx"), f("vy"), f("wz"), f"v {f('vx'):.0f} {f('vy'):.0f} {f('wz'):.3f}")
            elif ep == "stop":
                stop()
            elif ep == "circle":
                stop()
                threading.Thread(target=circle_thread, args=(max(50.0, f("r", 150)), max(20.0, f("v", 80)), max(1, int(f("laps", 1))), q.get("ccw", "1") == "1"), daemon=True).start()
            elif ep == "set":
                if "ms" in q and q["ms"] in ("8", "16", "32"):
                    r4._send(f"m {q['ms']}")
                if "hold" in q:
                    r4.hold_enable(q["hold"] == "1")
                if "tilt" in q:
                    r4.tilt(int(float(q["tilt"])))
                if "pan" in q:
                    r4.pan_stop()
                if "show" in q:
                    r4._send(f"K {1 if q['show'] == '1' else 0}")
                if "nudge" in q:
                    r4.nudge_pan(int(q["nudge"]), int(float(q.get("ms", 300))))
                if q.get("inv") in ("0", "1", "2", "3"):
                    r4._send(f"i {q['inv']}")
            elif ep == "jog":
                r4.jog(int(f("w")), int(f("d", 1)), f("s", 60))
                with lock:
                    state["mode"] = "drive"; state["cmd"] = "jog"; state["last_cmd"] = time.time()
            else:
                self._json({"error": "unknown"}, 404); return
        except Exception as e:  # never let a bad request take the server down
            self._json({"error": str(e)}, 500); return
        self._json(status())


if __name__ == "__main__":
    print(f"Hound remote on port {PORT}, key {KEY}  →  http://<host>:{PORT}/?k={KEY}", flush=True)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    try:
        srv.serve_forever()
    finally:
        r4.close()
