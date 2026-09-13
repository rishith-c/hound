/*
  r4_drive.ino — UNO R4 WiFi + CNC Shield V3 + 4× DRV8825 → mecanum rover drive.

  What it does
    • Hosts its own WiFi access point with a one-page web GUI: drive buttons (forward,
      back, strafe, rotate), per-wheel jog buttons for direction tuning, per-wheel
      INVERT toggles saved to EEPROM, speed slider, driver enable, live status.
    • Same commands over USB serial at 115200 (this is what the Pi will use later).
    • Steps are generated in a 20 kHz timer interrupt with linear ramps, so a
      speed change never yanks a stepper from rest to full rate.
    • Watchdog: if no command arrives for 400 ms, all four targets go to zero.
      The GUI re-sends while a button is held, so letting go = stop.

  Wheel ↔ shield axis, AS WIRED ON THE BENCH TODAY:
      FL = Y axis   FR = A axis   BL = X axis   BR = Z axis
  (The design docs say X=FL, Y=FR, Z=RL, A=RR. Either is fine — change the two tables below.)

  Shield pins (CNC Shield V3): X step D2 dir D5 · Y step D3 dir D6 · Z step D4 dir D7 ·
  A step D12 dir D13 (needs the D12 and D13 jumpers on the A header) · ENABLE D8, LOW = on.

  Power-up order still applies: USB (this board) first, THEN the pack on VMOT.
*/

#include <WiFiS3.h>
#include <EEPROM.h>
#include "FspTimer.h"

// ───────────────────────── access point ─────────────────────────
#define ENABLE_WIFI 0                        // 0 for the rover: the Pi drives it over USB and the radio would eat the Pi USB budget. 1 = bench GUI.
const char* AP_SSID = "rover-r4";
const char* AP_PASS = "rover-1234";          // change it; WPA2 needs 8+ characters

// ───────────────────────── wheel ↔ axis ─────────────────────────
enum { FL = 0, FR = 1, BL = 2, BR = 3 };
const char*   WNAME[4]    = { "FL", "FR", "BL", "BR" };
const char*   AXIS[4]     = { "Y",  "A",  "X",  "Z"  };
const uint8_t STEP_PIN[4] = {  3,   12,    2,    4  };
const uint8_t DIR_PIN[4]  = {  6,   13,    5,    7  };
const uint8_t EN_PIN      = 8;

// ───────────────────────── geometry & limits ─────────────────────
const float   WHEEL_D_MM  = 80.0f;
const int     FULL_STEPS  = 200;
const float   LX_MM       = 125.0f;          // half wheelbase (axles at X ±125)
const float   LY_MM       = 215.5f;          // half track    (wheel centres at Y ±215.5)
const int32_t TICK_HZ     = 30000;           // step ISR rate → max 15 000 steps/s per axis (was 20 kHz; verify the ticks counter still tracks)
const int32_t MAX_RATE    = 13500;           // steps/s per axis: 90 % of what the ISR can pulse
const float   V_MAX_MM    = 800.0f;          // physics ceiling: 84 % of the 1.5 A corner speed (228 rpm = 955 mm/s at 10.5 V, drivetrain.py) — torque is still full here
const float   ACCEL_MM_S2 = 600.0f;          // ramp in mm/s² (0.6 m/s²; case-B torque margin stays > 1.6 at 5.2 kg)
const uint32_t WATCHDOG_TICKS = TICK_HZ * 4 / 10;   // 400 ms
const uint32_t IDLE_DISABLE_MS = 3000;       // drivers off after 3 s of zero velocity

uint8_t  microsteps = 32;                    // M0+M2 caps = 1/32; M2 alone = 1/16
uint8_t  inv[4]     = { 0, 0, 0, 0 };        // per-wheel direction flip (EEPROM)
bool     holdEnable = false;                 // keep drivers energised while parked

// ───────────────────────── ISR state ─────────────────────────────
volatile int32_t  targetRate[4];             // signed steps/s
volatile int32_t  curRate[4];
volatile uint32_t acc[4];
volatile uint8_t  pulseHigh[4];
volatile uint32_t wdTicks    = 0;
volatile bool     wdTripped  = false;
volatile bool     anyMotion  = false;
volatile uint32_t isrTicks   = 0;
volatile int32_t  accelSteps = 15000;         // steps/s², recomputed from ACCEL_MM_S2 whenever microsteps change
bool timerOk = false;

static const uint32_t ACC_PER_STEP_PER_SEC = (uint32_t)(4294967296.0 / TICK_HZ);   // 214748

FspTimer stepTimer;

void stepIsr(timer_callback_args_t*) {
  static uint16_t slewDiv = 0;
  isrTicks++;

  if (++wdTicks > WATCHDOG_TICKS) {
    bool had = false;
    for (int i = 0; i < 4; i++) { if (targetRate[i]) had = true; targetRate[i] = 0; }
    if (had) wdTripped = true;
    wdTicks = WATCHDOG_TICKS;
  }

  if (++slewDiv >= TICK_HZ / 1000) {          // 1 kHz ramp update
    slewDiv = 0;
    const int32_t d = accelSteps / 1000;
    bool moving = false;
    for (int i = 0; i < 4; i++) {
      int32_t t = targetRate[i], c = curRate[i];
      if (c < t) { c += d; if (c > t) c = t; }
      else if (c > t) { c -= d; if (c < t) c = t; }
      curRate[i] = c;
      if (c) moving = true;
    }
    anyMotion = moving;
  }

  for (int i = 0; i < 4; i++) {
    if (pulseHigh[i]) { digitalWrite(STEP_PIN[i], LOW); pulseHigh[i] = 0; }
    int32_t r = curRate[i];
    if (r == 0) continue;
    uint32_t inc = (uint32_t)(r < 0 ? -r : r) * ACC_PER_STEP_PER_SEC;
    uint32_t a = acc[i] + inc;
    if (a < acc[i]) {                          // 32-bit wrap = one step
      bool fwd = (r > 0) != (inv[i] != 0);
      digitalWrite(DIR_PIN[i], fwd ? HIGH : LOW);   // DRV8825 wants DIR ≥ 650 ns before STEP; digitalWrite is slower than that
      digitalWrite(STEP_PIN[i], HIGH);
      pulseHigh[i] = 1;                        // goes LOW next tick (50 µs ≥ 1.9 µs minimum)
    }
    acc[i] = a;
  }
}

bool startTimer() {
  uint8_t type = GPT_TIMER;
  int8_t ch = FspTimer::get_available_timer(type);
  if (ch < 0) ch = FspTimer::get_available_timer(type, true);
  if (ch < 0) return false;
  stepTimer.begin(TIMER_MODE_PERIODIC, type, ch, (float)TICK_HZ, 0.0f, stepIsr);
  stepTimer.setup_overflow_irq();
  stepTimer.open();
  stepTimer.start();
  return true;
}

// ───────────────────────── motion commands ───────────────────────
float stepsPerMm() { return FULL_STEPS * (float)microsteps / (3.14159265f * WHEEL_D_MM); }
float maxMm()       { float m = MAX_RATE / stepsPerMm(); return m < V_MAX_MM ? m : V_MAX_MM; }
void  updateAccel() { int32_t a = (int32_t)(ACCEL_MM_S2 * stepsPerMm()); if (a < 1000) a = 1000; accelSteps = a; }

void kick() { wdTicks = 0; wdTripped = false; }

// vx forward mm/s, vy left mm/s, wz counter-clockwise rad/s
void setVelocity(float vx, float vy, float wz) {
  const float k = LX_MM + LY_MM;
  float w[4];
  w[FL] = vx - vy - wz * k;
  w[FR] = vx + vy + wz * k;
  w[BL] = vx + vy - wz * k;
  w[BR] = vx - vy + wz * k;
  const float spm = stepsPerMm();
  const float cap = maxMm() * spm;             // steps/s: the lower of the ISR budget and the physics ceiling
  float scale = 1.0f;
  for (int i = 0; i < 4; i++) {
    float s = fabsf(w[i]) * spm;
    if (s > cap) { float f = cap / s; if (f < scale) scale = f; }
  }
  for (int i = 0; i < 4; i++) targetRate[i] = (int32_t)(w[i] * spm * scale);
  kick();
}

void jog(int wheel, int dir, float mmps) {
  float r = mmps * stepsPerMm();
  const float cap = maxMm() * stepsPerMm();
  if (r > cap) r = cap;
  for (int i = 0; i < 4; i++) targetRate[i] = 0;
  if (wheel >= 0 && wheel < 4) targetRate[wheel] = (int32_t)(dir < 0 ? -r : r);
  kick();
}

void stopAll() { for (int i = 0; i < 4; i++) targetRate[i] = 0; kick(); }

// ───────────────────────── EEPROM ────────────────────────────────
const int EE_MAGIC = 0x5A;
void loadSettings() {
  if (EEPROM.read(0) != EE_MAGIC) return;
  for (int i = 0; i < 4; i++) inv[i] = EEPROM.read(1 + i) ? 1 : 0;
  uint8_t ms = EEPROM.read(5);
  if (ms == 16 || ms == 32 || ms == 8) microsteps = ms;
}
void saveSettings() {
  EEPROM.write(0, EE_MAGIC);
  for (int i = 0; i < 4; i++) EEPROM.write(1 + i, inv[i]);
  EEPROM.write(5, microsteps);
}

// ───────────────────────── status JSON ───────────────────────────
char jsonBuf[400];
const char* statusJson() {
  int en = digitalRead(EN_PIN) == LOW;
  snprintf(jsonBuf, sizeof(jsonBuf),
    "{\"map\":{\"FL\":\"%s\",\"FR\":\"%s\",\"BL\":\"%s\",\"BR\":\"%s\"},"
    "\"target\":[%ld,%ld,%ld,%ld],\"rate\":[%ld,%ld,%ld,%ld],\"inv\":[%d,%d,%d,%d],"
    "\"en\":%d,\"hold\":%d,\"wd\":%d,\"ms\":%d,\"spm\":%.2f,\"maxmm\":%.0f,\"tmr\":%d,\"ticks\":%lu,\"ip\":\"%s\"}",
    AXIS[0], AXIS[1], AXIS[2], AXIS[3],
    (long)targetRate[0], (long)targetRate[1], (long)targetRate[2], (long)targetRate[3],
    (long)curRate[0], (long)curRate[1], (long)curRate[2], (long)curRate[3],
    inv[0], inv[1], inv[2], inv[3], en, holdEnable ? 1 : 0, wdTripped ? 1 : 0, microsteps,
    stepsPerMm(), maxMm(), timerOk ? 1 : 0, (unsigned long)isrTicks, ENABLE_WIFI ? WiFi.localIP().toString().c_str() : "off");
  return jsonBuf;
}

// ───────────────────────── web page ──────────────────────────────
static const char PAGE[] =
"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
"<title>rover drive</title><style>"
"body{font:16px system-ui;margin:0;background:#fff;color:#111}main{max-width:720px;margin:0 auto;padding:16px}"
"h1{font-size:20px;margin:0 0 8px}.g{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}"
"button{font:inherit;font-size:16px;padding:16px 8px;border:1px solid #888;border-radius:6px;background:#f5f5f5;touch-action:none;user-select:none}"
"button:active,button.on{background:#cde}button.stop{background:#e33;color:#fff;border-color:#a00}"
".w{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.w div{border:1px solid #ccc;border-radius:6px;padding:8px;text-align:center}"
".w b{display:block;font-size:18px}.w small{color:#666}.w .r{font-family:ui-monospace,monospace;font-size:14px;margin:6px 0}"
".row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:10px 0}label{display:flex;gap:6px;align-items:center}"
"#st{font-family:ui-monospace,monospace;font-size:13px;color:#444;white-space:pre-wrap}.tip{background:#f3f6fa;border-left:4px solid #369;padding:8px 12px;font-size:14px}"
"</style></head><body><main>"
"<h1>rover drive</h1>"
"<div class=row><label>speed <input id=sp type=range min=20 max=190 value=80> <span id=spv>80</span> mm/s</label>"
"<label><input id=hold type=checkbox> hold drivers on</label>"
"<label>microsteps <select id=ms><option>16<option selected>32</select></label></div>"
"<div class=g>"
"<button data-v='0,0,1'>rotate ⟲</button><button data-v='1,0,0'>forward ▲</button><button data-v='0,0,-1'>rotate ⟳</button>"
"<button data-v='0,1,0'>strafe ◀</button><button class=stop id=stop>STOP</button><button data-v='0,-1,0'>strafe ▶</button>"
"<button data-v='1,1,0'>diag ◤</button><button data-v='-1,0,0'>back ▼</button><button data-v='1,-1,0'>diag ◥</button>"
"</div>"
"<div class=w id=wheels></div>"
"<div class=tip><b>Direction tuning.</b> Hold <b>FL ▲</b>: the front-left wheel must roll the rover forward. If it rolls the other way, tap <b>invert</b> under FL. "
"Do all four. Then hold <b>forward</b>: all four roll forward. Hold <b>strafe ◀</b>: FL back, FR forward, BL forward, BR back. If forward is right but strafe is wrong, two wheels of one side are swapped left/right-hand.</div>"
"<p id=st>connecting…</p>"
"</main><script>"
"const W=['FL','FR','BL','BR'];let timer=null,cur=null;"
"function q(p){return fetch(p).then(r=>r.json()).then(show).catch(()=>{});}"
"function v(){return +document.getElementById('sp').value;}"
"function send(){if(cur===null)return;"
" if(cur.jog)q('/jog?w='+cur.jog[0]+'&d='+cur.jog[1]+'&s='+v());"
" else{const s=v();const k=340.5;q('/v?vx='+(cur.v[0]*s)+'&vy='+(cur.v[1]*s)+'&wz='+(cur.v[2]*s/k));}}"
"function start(c){cur=c;send();clearInterval(timer);timer=setInterval(send,150);}"
"function stop(){cur=null;clearInterval(timer);q('/stop');}"
"function bind(b,c){b.addEventListener('pointerdown',e=>{e.preventDefault();b.classList.add('on');start(c);});"
" ['pointerup','pointerleave','pointercancel'].forEach(ev=>b.addEventListener(ev,()=>{b.classList.remove('on');if(cur)stop();}));}"
"document.querySelectorAll('button[data-v]').forEach(b=>bind(b,{v:b.dataset.v.split(',').map(Number)}));"
"document.getElementById('stop').addEventListener('pointerdown',stop);"
"const wh=document.getElementById('wheels');W.forEach((n,i)=>{const d=document.createElement('div');"
" d.innerHTML='<b>'+n+'</b><small id=ax'+i+'></small><div class=r id=r'+i+'>0</div>';"
" const up=document.createElement('button');up.textContent=n+' ▲';bind(up,{jog:[i,1]});"
" const dn=document.createElement('button');dn.textContent=n+' ▼';bind(dn,{jog:[i,-1]});"
" const iv=document.createElement('button');iv.textContent='invert';iv.id='inv'+i;iv.style.marginTop='6px';"
" iv.addEventListener('click',()=>q('/inv?w='+i));d.append(up,dn,iv);wh.append(d);});"
"document.getElementById('sp').oninput=e=>document.getElementById('spv').textContent=e.target.value;"
"document.getElementById('hold').onchange=e=>q('/en?v='+(e.target.checked?1:0));"
"document.getElementById('ms').onchange=e=>q('/ms?v='+e.target.value);"
"function show(s){W.forEach((n,i)=>{document.getElementById('ax'+i).textContent='axis '+s.map[n];"
" const r=s.rate[i];document.getElementById('r'+i).textContent=(r>0?'▲ ':r<0?'▼ ':'· ')+Math.abs(r)+' st/s';"
" document.getElementById('inv'+i).classList.toggle('on',!!s.inv[i]);});"
" document.getElementById('ms').value=s.ms;document.getElementById('sp').max=Math.floor(s.maxmm);"
" document.getElementById('st').textContent='drivers '+(s.en?'ON':'off')+(s.hold?' (hold)':'')+' · '+s.spm+' steps/mm · max '+Math.floor(s.maxmm)+' mm/s · watchdog '+(s.wd?'TRIPPED':'ok')+' · '+s.ip;}"
"setInterval(()=>{if(cur===null)q('/status');},500);q('/status');"
"</script></body></html>";

// ───────────────────────── HTTP ──────────────────────────────────
WiFiServer server(80);

float qf(const String& path, const char* key, float def) {
  int i = path.indexOf(String("?") + key + "="); if (i < 0) i = path.indexOf(String("&") + key + "=");
  if (i < 0) return def;
  i = path.indexOf('=', i) + 1;
  int e = path.indexOf('&', i); if (e < 0) e = path.length();
  return path.substring(i, e).toFloat();
}

void sendJson(WiFiClient& c) {
  c.println("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nConnection: close\r\n");
  c.println(statusJson());
}

bool route(const String& path) {           // shared by HTTP and serial; true = handled
  if (path.startsWith("/v?"))        { setVelocity(qf(path, "vx", 0), qf(path, "vy", 0), qf(path, "wz", 0)); return true; }
  if (path.startsWith("/jog?"))      { jog((int)qf(path, "w", -1), (int)qf(path, "d", 1), qf(path, "s", 50)); return true; }
  if (path.startsWith("/stop"))      { stopAll(); return true; }
  if (path.startsWith("/inv?"))      { int w = (int)qf(path, "w", -1); if (w >= 0 && w < 4) { inv[w] ^= 1; saveSettings(); } return true; }
  if (path.startsWith("/en?"))       { holdEnable = qf(path, "v", 0) > 0.5f; return true; }
  if (path.startsWith("/ms?"))       { int m = (int)qf(path, "v", 32); if (m == 8 || m == 16 || m == 32) { microsteps = m; updateAccel(); saveSettings(); } return true; }
  if (path.startsWith("/status"))    { return true; }
  return false;
}

void handleHttp() {
  WiFiClient c = server.available();
  if (!c) return;
  c.setTimeout(100);
  String req = c.readStringUntil('\n');
  while (c.connected() && c.available()) { String h = c.readStringUntil('\n'); if (h.length() <= 1) break; }
  int s1 = req.indexOf(' '), s2 = req.indexOf(' ', s1 + 1);
  String path = (s1 > 0 && s2 > s1) ? req.substring(s1 + 1, s2) : "/";
  if (path == "/" || path.startsWith("/index")) {
    c.println("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n");
    c.print(PAGE);
  } else if (route(path)) {
    sendJson(c);
  } else {
    c.println("HTTP/1.1 404 Not Found\r\nConnection: close\r\n");
  }
  delay(1);
  c.stop();
}

// ───────────────────────── serial (Pi later) ─────────────────────
//   v <vx> <vy> <wz>   mm/s mm/s rad/s      j <wheel 0-3> <dir ±1> <mm/s>
//   s                  stop                 i <wheel>   toggle invert
//   e <0|1>            hold enable          m <8|16|32> microsteps        ?  status
void handleSerial() {
  static String line;
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\r') continue;
    if (ch != '\n') { if (line.length() < 60) line += ch; continue; }
    line.trim();
    if (line.length()) {
      char cmd = line[0]; float a = 0, b = 0, d = 0;
      char* p = (char*)line.c_str() + 1;          // newlib-nano has no float scanf: parse by hand
      a = strtof(p, &p); b = strtof(p, &p); d = strtof(p, &p);
      switch (cmd) {
        case 'v': setVelocity(a, b, d); break;
        case 'j': jog((int)a, (int)b, d); break;
        case 's': stopAll(); break;
        case 'i': if (a >= 0 && a < 4) { inv[(int)a] ^= 1; saveSettings(); } break;
        case 'e': holdEnable = a > 0.5f; break;
        case 'm': if (a == 8 || a == 16 || a == 32) { microsteps = (uint8_t)a; updateAccel(); saveSettings(); } break;
        default: break;
      }
      Serial.println(statusJson());
    }
    line = "";
  }
}

// ───────────────────────── setup / loop ──────────────────────────
void setup() {
  for (int i = 0; i < 4; i++) { pinMode(STEP_PIN[i], OUTPUT); pinMode(DIR_PIN[i], OUTPUT); digitalWrite(STEP_PIN[i], LOW); }
  pinMode(EN_PIN, OUTPUT); digitalWrite(EN_PIN, HIGH);          // drivers OFF until commanded
  Serial.begin(115200);
  loadSettings();
  updateAccel();
  timerOk = startTimer();
  if (!timerOk) Serial.println("{\"error\":\"no free GPT timer\"}");

#if ENABLE_WIFI
  if (WiFi.status() == WL_NO_MODULE) { Serial.println("{\"error\":\"no WiFi module\"}"); }
  else {
    WiFi.config(IPAddress(192, 168, 4, 1));
    if (WiFi.beginAP(AP_SSID, AP_PASS) != WL_AP_LISTENING) Serial.println("{\"error\":\"beginAP failed\"}");
    else { server.begin(); Serial.print("{\"ap\":\""); Serial.print(AP_SSID); Serial.print("\",\"url\":\"http://"); Serial.print(WiFi.localIP()); Serial.println("/\"}"); }
  }
#else
  Serial.println("{\"wifi\":\"off\",\"link\":\"usb serial 115200\"}");
#endif
}

void loop() {
  static uint32_t lastMotionMs = 0;
#if ENABLE_WIFI
  handleHttp();
#endif
  handleSerial();

  bool moving = anyMotion;
  if (moving) { lastMotionMs = millis(); digitalWrite(EN_PIN, LOW); }
  else if (holdEnable) digitalWrite(EN_PIN, LOW);
  else if (millis() - lastMotionMs > IDLE_DISABLE_MS) digitalWrite(EN_PIN, HIGH);
}
