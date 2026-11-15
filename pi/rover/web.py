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
import subprocess
import sys
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
TRIM_FILE = os.path.expanduser("~/rover/pan_trim")   # the pan's stop-pulse trim: the R4 forgets it on reset, so it lives here
if os.path.exists(TRIM_FILE):
    r4._send(f"T {int(open(TRIM_FILE).read().strip() or 0)}")
state ={"last_cmd": 0.0, "mode": "idle", "cmd": "stop", "circle": None, "t0": time.time()}
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


# ── turret motion recorder: tilt and pan commands from the page are logged with their time and replayed here on the Pi
MOTIONS_FILE = os.path.expanduser("~/rover/motions.json")   # {label: [[t_s, kind, a, b], ...]}
try:
    motions = json.load(open(MOTIONS_FILE))
except (OSError, ValueError):
    motions = {}
rec = {"on": False, "t0": 0.0, "ev": []}
play = {"id": 0, "name": None}


def turret(kind, a=0, b=0):
    if kind == "tilt":
        r4.tilt(int(a))
    elif kind == "nudge":
        r4.nudge_pan(int(a), int(b))
    elif kind == "pan":
        r4.pan_stop()


def turret_cmd(kind, a=0, b=0):
    """A turret command from the page: do it, and log it while recording."""
    turret(kind, a, b)
    with lock:
        if rec["on"]:
            rec["ev"].append([round(time.time() - rec["t0"], 3), kind, a, b])


_save_lock = threading.Lock()


def save_motions():
    with _save_lock:                                  # snapshot and write in one piece, so an older snapshot never lands last
        with lock:
            text = json.dumps(motions)
        with open(MOTIONS_FILE, "w") as fh:
            fh.write(text)


def rec_start():
    with lock:
        rec.update(on=True, t0=time.time(), ev=[])
        if r4.status.get("tilton"):   # a held tilt is part of the pose: replay starts there. A limp tilt stays wherever it was put.
            rec["ev"].append([0.0, "tilt", int(r4.status.get("tilt", 92)), 0])
        rec["base"] = len(rec["ev"])  # a recording with nothing past the start pose is not saved


def rec_stop(name):
    with lock:
        if not rec["on"]:
            return
        rec["on"] = False
        ev = rec["ev"] if len(rec["ev"]) > rec["base"] else []
        name = (name or "").strip()[:40]
        if not name:
            n = 1
            while f"motion {n}" in motions:
                n += 1
            name = f"motion {n}"
        if ev:
            motions[name] = ev
    if ev:
        save_motions()


def play_thread(name, pid):
    t0 = time.time()
    for t, kind, a, b in motions.get(name, []):
        while time.time() - t0 < t:
            if play["id"] != pid:
                return
            time.sleep(0.01)
        if play["id"] != pid:
            return
        turret(kind, a, b)
    with lock:
        if play["id"] == pid:
            play["name"] = None


def play_start(name):
    with lock:
        play["id"] += 1; play["name"] = name; pid = play["id"]
    threading.Thread(target=play_thread, args=(name, pid), daemon=True).start()


def play_stop():
    with lock:
        play["id"] += 1; play["name"] = None
    r4.pan_stop()


# ── senses check: sensing/bringup.py in its own process (GPIO, I2C and the camera are let go when it exits, and a
#    crash there cannot take the remote down). The motors are not touched. ────────────────────────────────────────────
SENSING = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sensing")     # deploy.sh puts sensing/ here
SENSES_TIMEOUT = 120
senses = {"running": False, "lines": []}


def senses_thread():
    try:
        p = subprocess.Popen([sys.executable, "-u", os.path.join(SENSING, "bringup.py"), "--seconds", "3"], cwd=SENSING,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        killer = threading.Timer(SENSES_TIMEOUT, p.kill); killer.start()
        for line in p.stdout:
            with lock:
                senses["lines"].append(line.rstrip())
        p.wait(); killer.cancel()
        if p.returncode < 0:
            with lock:
                senses["lines"].append(f"FAIL  senses  stopped after {SENSES_TIMEOUT} s")
    except Exception as e:
        with lock:
            senses["lines"].append(f"FAIL  senses  {e.__class__.__name__}: {e}")
    with lock:
        senses["running"] = False


def senses_start():
    with lock:
        if senses["running"]:
            return
        senses.update(running=True, lines=[])
    radar_stop(wait=True)                      # bringup reads the LD2450's port too: two readers would split its frames
    threading.Thread(target=senses_thread, daemon=True).start()


# ── radar view: the LD2450's moving targets, live, only while the page asks for it (it holds the port meanwhile) ─────
RADARS_JSON = os.path.expanduser("~/rover/radars.json")
radar = {"on": False, "id": 0, "targets": [], "fps": 0.0, "err": ""}


def radar_port():
    try:
        return json.load(open(RADARS_JSON)).get("ld2450", "/dev/ttyAMA0")
    except (OSError, ValueError):
        return "/dev/ttyAMA0"


def radar_thread(rid, opener=None):
    try:
        if SENSING not in sys.path:
            sys.path.insert(0, SENSING)
        import ld2450
        if opener is None:
            import serial
            opener = lambda port: serial.Serial(port, 256000, timeout=0.1)
        ser = opener(radar_port())
    except Exception as e:
        with lock:
            if radar["id"] == rid:
                radar.update(on=False, err=f"{radar_port()}: {e.__class__.__name__}: {e} — wired, and enable_gpio_uart.sh run?")
        return
    rd, n, t0 = ld2450.FrameReader(), 0, time.time()
    try:
        while True:
            with lock:
                if radar["id"] != rid:
                    break
            frames = rd.feed(ser.read(256))
            n += len(frames)
            with lock:
                if frames:
                    radar["targets"] = [{k: t[k] for k in ("x_mm", "y_mm", "speed_cms")} for t in frames[-1]]
                if time.time() - t0 >= 1.0:
                    radar["fps"], n, t0 = round(n / (time.time() - t0), 1), 0, time.time()
    except Exception as e:
        with lock:
            radar["err"] = f"{e.__class__.__name__}: {e}"
    finally:
        ser.close()
        with lock:
            if radar["id"] == rid:
                radar.update(on=False, targets=[])


def radar_start(opener=None):
    with lock:
        if radar["on"] or senses["running"]:   # a senses check is reading that port: wait for it
            return
        radar["id"] += 1; radar.update(on=True, targets=[], fps=0.0, err=""); rid = radar["id"]
    threading.Thread(target=radar_thread, args=(rid, opener), daemon=True).start()


def radar_stop(wait=False):
    with lock:
        was = radar["on"]
        radar["id"] += 1; radar.update(on=False, targets=[])
    if was and wait:
        time.sleep(0.3)                        # the reader notices within one 0.1 s read and closes the port


def status():
    s = dict(r4.status)
    with lock:
        s.update(mode=state["mode"], cmd=state["cmd"], uptime=round(time.time() - state["t0"]), port=r4.port)
        s.update(rec=rec["on"], rec_n=len(rec["ev"]), playing=play["name"], motions={k: (v[-1][0] if v else 0) for k, v in motions.items()})
        if radar["on"] or radar["err"]:
            s["radar"] = {"on": radar["on"], "targets": list(radar["targets"]), "fps": radar["fps"], "err": radar["err"]}
    return s


PAGE = r"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Hound remote</title><style>
body{margin:0;background:#0f151b;color:#e6ebf0;font:16px system-ui,sans-serif}main{max-width:760px;margin:0 auto;padding:14px}
h1{font-size:18px;margin:0 0 10px;color:#93a1ae;font-weight:600}
.pad{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}
button{font:inherit;font-size:17px;padding:20px 6px;border:1px solid #2a3641;border-radius:8px;background:#172029;color:#e6ebf0;touch-action:none;user-select:none;cursor:pointer}
button:active,button.on{background:#2e5c8a;border-color:#7fb0e0}button.stop{background:#8a1f1f;border-color:#ff8a4c;font-weight:700}
.row{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:10px 0;font-size:14px}label{display:flex;gap:8px;align-items:center}
input[type=range]{width:200px;max-width:36vw}label small{white-space:nowrap}select,input[type=number]{font:inherit;background:#172029;color:#e6ebf0;border:1px solid #2a3641;border-radius:4px;padding:4px}
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
 <label>tilt <small style="color:#93a1ae">▼ down</small><input id=tilt type=range min=78 max=150 value=92><small style="color:#93a1ae">up ▲</small> <span id=tiltv>92</span>° <button id=tiltoff style="padding:4px 8px;font-size:12px">release</button></label>
 <label><button id=show style="padding:6px 12px">▶ Ceres show</button></label>
 <label>pan <button id=nudgeL style="padding:6px 12px">◀ left</button><button id=panStop style="padding:6px 12px">■</button><button id=nudgeR style="padding:6px 12px">right ▶</button> <span id=panv style="color:#93a1ae;font-size:12px">hold to keep turning · 300 ms nudges (Ceres)</span></label>
 <label>pan trim <button id=trm style="padding:4px 10px">−</button> <span id=ptv>0</span> µs <button id=trp style="padding:4px 10px">+</button> <button id=still style="padding:4px 8px;font-size:12px">test: hold still 3 s</button> <span style="color:#93a1ae;font-size:12px">creeps right → +, creeps left → −</span></label>
 <span id=lat></span>
</div>
<h1 style="margin-top:12px">Record motions</h1>
<div class=row>
 <button id=rec style="padding:6px 12px">● record</button>
 <input id=rname maxlength=40 placeholder="label, e.g. nod" style="font:inherit;background:#172029;color:#e6ebf0;border:1px solid #2a3641;border-radius:4px;padding:4px;width:160px">
 <span id=recst style="color:#93a1ae;font-size:12px">records the tilt slider and pan buttons, with timing</span>
</div>
<div class=row id=mlist></div>
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
<h1 style="margin-top:16px">Senses</h1>
<div class=row><button id=sns style="padding:6px 12px">▶ check senses</button><span style="color:#93a1ae;font-size:12px">radars, Wi-Fi CSI, thermal, ToFs, camera, I2C · about 20 s · motors not touched</span></div>
<pre id=snsout style="font:12px ui-monospace,monospace;white-space:pre-wrap;margin:4px 0"></pre>
<h1 style="margin-top:16px">Radar view</h1>
<div class=row><button id=rdr style="padding:6px 12px">▶ LD2450 live</button><span id=rdst style="color:#93a1ae;font-size:12px">up to 3 moving people, x/y from the rear radar · 6 m fan</span></div>
<canvas id=rdc width=320 height=180 style="width:320px;max-width:100%;background:#172029;border-radius:8px;display:none"></canvas>
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
let tiltT=0;document.getElementById('tilt').oninput=e=>{document.getElementById('tiltv').textContent=e.target.value;const t=performance.now();if(t-tiltT>80){tiltT=t;api('set?tilt='+e.target.value);}};   // follows the drag live (and gets recorded)
document.getElementById('tilt').onchange=e=>api('set?tilt='+e.target.value);
let recOn=false,mSig='';const recB=document.getElementById('rec'),ml=document.getElementById('mlist');
recB.onclick=()=>{if(!recOn)api('rec?on=1');else{api('rec?on=0&name='+encodeURIComponent(document.getElementById('rname').value));document.getElementById('rname').value='';}};
ml.onclick=e=>{const b=e.target.closest('button');if(!b)return;const n=b.dataset.n;
 if(b.dataset.a==='play')api('play?name='+encodeURIComponent(n));else if(b.dataset.a==='stop')api('play?stop=1');else if(b.dataset.a==='del'&&confirm('Delete "'+n+'"?'))api('motion?del='+encodeURIComponent(n));};
function showRec(s){recOn=!!s.rec;recB.textContent=recOn?'■ stop & save':'● record';recB.classList.toggle('on',recOn);
 document.getElementById('recst').textContent=recOn?'recording… '+(s.rec_n||0)+' moves':'records the tilt slider and pan buttons, with timing';
 const sig=JSON.stringify([s.motions,s.playing]);if(sig===mSig)return;mSig=sig;ml.textContent='';
 Object.entries(s.motions||{}).forEach(([n,d])=>{const w=document.createElement('span');w.style.cssText='display:inline-flex;gap:6px;align-items:center;background:#172029;border-radius:6px;padding:4px 8px';
  const b=document.createElement('b');b.textContent=n;const t=document.createElement('small');t.style.color='#93a1ae';t.textContent=(+d).toFixed(1)+' s';
  const on=s.playing===n,p=document.createElement('button');p.style.cssText='padding:4px 10px;font-size:13px';p.dataset.a=on?'stop':'play';p.dataset.n=n;p.textContent=on?'■ stop':'▶ play';
  const x=document.createElement('button');x.style.cssText='padding:4px 8px;font-size:12px;color:#93a1ae';x.dataset.a='del';x.dataset.n=n;x.textContent='✕';
  w.append(b,t,p,x);ml.append(w);});}
document.getElementById('tiltoff').onclick=()=>api('set?tilt=-1');
let panTimer=null;function panHold(b,dir){b.addEventListener('pointerdown',e=>{e.preventDefault();b.classList.add('on');api('set?nudge='+dir+'&ms=300');clearInterval(panTimer);panTimer=setInterval(()=>api('set?nudge='+dir+'&ms=300'),320);});
 ['pointerup','pointerleave','pointercancel'].forEach(ev=>b.addEventListener(ev,()=>{b.classList.remove('on');clearInterval(panTimer);panTimer=null;}));}
panHold(document.getElementById('nudgeL'),-1);panHold(document.getElementById('nudgeR'),1);
document.getElementById('panStop').onclick=()=>{clearInterval(panTimer);api('set?pan=0');};
let ptrim=0,ptrimSeen=false;const setTrim=v=>{ptrim=Math.max(-150,Math.min(150,v));document.getElementById('ptv').textContent=ptrim;api('set?ptrim='+ptrim);};
document.getElementById('trm').onclick=()=>setTrim(ptrim-5);document.getElementById('trp').onclick=()=>setTrim(ptrim+5);
document.getElementById('still').onclick=()=>api('set?still=3000');
let showOn=false,showT=-1e9;const showLabel=()=>{document.getElementById('show').textContent=showOn?'■ stop show':'▶ Ceres show';};
document.getElementById('show').onclick=()=>{showOn=!showOn;showT=performance.now();showLabel();api('set?show='+(showOn?1:0));};   // the R4 ignores K 1 while a show runs: the label follows its status, not the tap count
const keys={w:[1,0,0],s:[-1,0,0],a:[0,1,0],d:[0,-1,0],q:[0,0,1],e:[0,0,-1],arrowup:[1,1,0],arrowright:[1,-1,0],arrowdown:[-1,-1,0],arrowleft:[-1,1,0]};
let held=null;
window.addEventListener('keydown',e=>{const k=e.key.toLowerCase();if(k===' '){e.preventDefault();held=null;stop();return;}
 if(keys[k]&&held!==k){e.preventDefault();held=k;start(keys[k]);}});
window.addEventListener('keyup',e=>{const k=e.key.toLowerCase();if(held===k){held=null;stop();}});
const wh=document.getElementById('wheels');W.forEach((n,i)=>{const d=document.createElement('div');d.innerHTML='<b>'+n+' · '+DRV[i]+'</b><span id=r'+i+'>0</span>';wh.append(d);});
function show(s){if(!s||!s.rate)return;W.forEach((n,i)=>{const r=s.rate[i];document.getElementById('r'+i).textContent=(r>0?'▲ ':r<0?'▼ ':'· ')+Math.abs(r);document.getElementById('mi'+i).textContent=s.inv&&s.inv[i]?'· flipped':'';});
 document.getElementById('ms').value=s.ms;document.getElementById('sp').max=Math.floor(s.maxmm||190);
 if(s.show!=null&&performance.now()-showT>1500){showOn=!!s.show;showLabel();}   // resync from the R4 (after a reload, or from another phone)
 if(s.ptrim!=null&&!ptrimSeen){ptrimSeen=true;ptrim=s.ptrim;document.getElementById('ptv').textContent=ptrim;}
 document.getElementById('st').textContent=`${s.mode} · ${s.cmd} · pack ${s.vbat>5?s.vbat.toFixed(1)+' V'+(s.lv?' LOW — DRIVE LOCKED':''):'n/a'} · drivers ${s.en?'ON':'off'} · ${s.spm} steps/mm · max ${Math.floor(s.maxmm)} mm/s · R4 ${s.port||''} · pi up ${s.uptime}s`;
 document.getElementById('note').textContent=s.wd?'R4 watchdog tripped (link went quiet) — it stopped itself':'';
 showRec(s);drawRadar(s.radar);}
const sns=document.getElementById('sns'),snsout=document.getElementById('snsout');let snsT=null;
function showSns(j){const s=j.senses;if(!s)return;
 snsout.innerHTML=s.lines.map(l=>{const c=/^PASS/.test(l)?'#7fd18b':/^WARN/.test(l)?'#ffcf5c':/^FAIL/.test(l)?'#ff8a4c':'#93a1ae';
  return '<span style="color:'+c+'">'+l.replace(/&/g,'&amp;').replace(/</g,'&lt;')+'</span>';}).join('\n');
 sns.textContent=s.running?'… checking':'▶ check senses';sns.disabled=s.running;if(!s.running&&snsT){clearInterval(snsT);snsT=null;}}
const rdr=document.getElementById('rdr'),rdc=document.getElementById('rdc'),rdst=document.getElementById('rdst');let rdOn=false,rdT=-1e9;
function drawRadar(r){const on=!!(r&&r.on);if(performance.now()-rdT>1500){rdOn=on;rdr.textContent=on?'■ stop radar':'▶ LD2450 live';}
 rdc.style.display=rdOn?'':'none';if(r&&r.err){rdst.textContent=r.err;rdst.style.color='#ff8a4c';}
 if(!on)return;rdst.style.color='#93a1ae';rdst.textContent=(r.targets.length?r.targets.map(t=>(t.x_mm/1000).toFixed(1)+' m, '+(t.y_mm/1000).toFixed(1)+' m ahead, '+Math.abs(t.speed_cms)+' cm/s').join(' · '):'nothing moving')+' · '+r.fps+' frames/s';
 const g=rdc.getContext('2d'),W=rdc.width,H=rdc.height,cx=W/2,sc=(H-10)/6000;g.clearRect(0,0,W,H);g.strokeStyle='#2a3641';
 for(let m=2000;m<=6000;m+=2000){g.beginPath();g.arc(cx,H-4,m*sc,Math.PI*1.167,Math.PI*1.833);g.stroke();}
 [-60,60].forEach(a=>{const r=a*Math.PI/180;g.beginPath();g.moveTo(cx,H-4);g.lineTo(cx+Math.sin(r)*6000*sc,H-4-Math.cos(r)*6000*sc);g.stroke();});
 r.targets.forEach(t=>{g.fillStyle='#7fd18b';g.beginPath();g.arc(cx+t.x_mm*sc,H-4-t.y_mm*sc,6,0,7);g.fill();});}
rdr.onclick=()=>{rdOn=!rdOn;rdT=performance.now();rdr.textContent=rdOn?'■ stop radar':'▶ LD2450 live';rdc.style.display=rdOn?'':'none';api('radar?on='+(rdOn?1:0));};
const snsGet=(go)=>fetch('/api/senses?'+(go?'go=1&':'')+'k='+encodeURIComponent(K)).then(r=>r.json()).then(showSns).catch(()=>{});
sns.onclick=()=>{snsGet(true);if(!snsT)snsT=setInterval(()=>snsGet(false),1000);};
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
                    turret_cmd("tilt", int(float(q["tilt"])))
                if "pan" in q:
                    turret_cmd("pan")
                if "show" in q:
                    r4._send(f"K {1 if q['show'] == '1' else 0}")
                if "nudge" in q:
                    turret_cmd("nudge", int(q["nudge"]), int(float(q.get("ms", 300))))
                if "ptrim" in q:
                    v = max(-150, min(150, int(float(q["ptrim"]))))
                    r4._send(f"T {v}")
                    open(TRIM_FILE, "w").write(str(v))
                if "still" in q:
                    r4._send(f"H {int(float(q['still']))}")
                if q.get("inv") in ("0", "1", "2", "3"):
                    r4._send(f"i {q['inv']}")
            elif ep == "rec":
                if q.get("on") == "1":
                    rec_start()
                else:
                    rec_stop(q.get("name"))
            elif ep == "play":
                if q.get("name") in motions:
                    play_start(q["name"])
                else:
                    play_stop()
            elif ep == "motion":
                with lock:
                    motions.pop(q.get("del", ""), None)
                save_motions()
            elif ep == "radar":
                radar_start() if q.get("on") == "1" else radar_stop(wait=True)   # port closed before a quick re-start
            elif ep == "senses":
                if q.get("go") == "1":
                    senses_start()
                with lock:
                    snap = {"running": senses["running"], "lines": list(senses["lines"])}
                self._json({**status(), "senses": snap}); return
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
