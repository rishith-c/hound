#!/usr/bin/env python3
"""Build the BOM site from bom.json: writes index.html and bom.csv.

Dead simple on purpose: black text on white, one table per section, every
row a link to its listing, a checkbox that persists in the browser, and a
plain static CSV link. No framework, no build step beyond this file.

    python3 build.py
"""

import csv
import html
import json
from datetime import date

BOM = json.load(open("bom.json"))
sections = BOM["sections"]
owned = BOM["owned"]
meta = BOM["meta"]

# ── CSV ─────────────────────────────────────────────────────────────────────
with open("bom.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["section", "status", "item", "qty", "unit_usd", "line_usd", "asin", "url", "note"])
    for o in owned:
        w.writerow(["Owned", "owned", o["item"], o["qty"], "", "", "", "", o["note"]])
    for s in sections:
        for it in s["items"]:
            w.writerow([s["name"], "optional" if s.get("optional") else "buy",
                        it["item"], it["packs"], f'{it["price"]:.2f}',
                        f'{it["packs"] * it["price"]:.2f}', it["asin"],
                        f'https://www.amazon.com/dp/{it["asin"]}', it.get("note", "")])

# ── totals ──────────────────────────────────────────────────────────────────
def total(sec):
    return sum(i["packs"] * i["price"] for i in sec["items"])

buy_total = sum(total(s) for s in sections if not s.get("optional"))
opt_total = sum(total(s) for s in sections if s.get("optional"))
buy_lines = sum(len(s["items"]) for s in sections if not s.get("optional"))

# ── HTML ────────────────────────────────────────────────────────────────────
def esc(x):
    return html.escape(str(x))

def row(it, sec_id):
    key = f"{sec_id}-{it['asin']}"
    line = it["packs"] * it["price"]
    note = f'<div class="note">{esc(it["note"])}</div>' if it.get("note") else ""
    return (
        f'<tr><td class="ck"><input type="checkbox" data-key="{esc(key)}"></td>'
        f'<td><a href="https://www.amazon.com/dp/{esc(it["asin"])}" target="_blank" rel="noopener">'
        f'{esc(it["item"])}</a>{note}</td>'
        f'<td class="n">{it["packs"]}</td><td class="n">${it["price"]:.2f}</td>'
        f'<td class="n">${line:.2f}</td></tr>'
    )

parts = []
for s in sections:
    sec_id = s["name"].lower().replace(" ", "-").replace("&", "and")
    hdr = esc(s["name"]) + (" <small>(optional)</small>" if s.get("optional") else "")
    rows = "\n".join(row(i, sec_id) for i in s["items"])
    parts.append(f"""
<h2 id="{sec_id}">{hdr} <span class="sub">${total(s):.2f}</span></h2>
{('<p class="lede">' + esc(s["why"]) + '</p>') if s.get("why") else ''}
<div class="tw"><table>
<thead><tr><th></th><th>Item</th><th class="n">Qty</th><th class="n">Each</th><th class="n">Line</th></tr></thead>
<tbody>
{rows}
</tbody></table></div>""")

owned_rows = "\n".join(
    f'<tr><td>{esc(o["item"])}</td><td class="n">{esc(o["qty"])}</td><td>{esc(o["note"])}</td></tr>'
    for o in owned)

page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rover BOM</title>
<style>
:root{{color-scheme:light}}
html,body{{background:#fff;color:#000;margin:0}}
body{{font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;max-width:920px;padding:32px 20px 64px;margin:0 auto}}
h1{{font-size:26px;margin:0 0 6px;font-weight:650}}
h2{{font-size:18px;margin:36px 0 8px;font-weight:650;display:flex;justify-content:space-between;align-items:baseline}}
h2 .sub{{font-weight:400;font-size:15px}}
h2 small{{font-weight:400;font-size:13px;margin-left:8px}}
p{{margin:8px 0}}
.lede{{font-size:15px}}
a{{color:#000;text-decoration:underline;text-underline-offset:2px}}
a:hover{{text-decoration-thickness:2px}}
.tw{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:8px 6px;border-bottom:1px solid #000;text-align:left;vertical-align:top;font-size:15px}}
th{{font-weight:600;border-bottom:2px solid #000}}
td.n,th.n{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}
td.ck{{width:26px;padding-right:0}}
input[type=checkbox]{{width:16px;height:16px;accent-color:#000;margin:2px 0 0}}
tr.done td{{opacity:.45}}
tr.done a{{text-decoration:line-through}}
.note{{font-size:13px;margin-top:3px}}
.bar{{display:flex;flex-wrap:wrap;gap:12px 24px;align-items:baseline;margin:14px 0 4px}}
.big{{font-size:20px;font-weight:650}}
.btn{{display:inline-block;border:1.5px solid #000;padding:6px 12px;text-decoration:none;font-size:15px}}
.btn:hover{{background:#000;color:#fff}}
.rule{{border:0;border-top:1px solid #000;margin:28px 0}}
pre{{font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;border:1px solid #000;padding:12px}}
.muted{{font-size:13px}}
@media(max-width:600px){{body{{padding:20px 12px 48px}} th,td{{padding:7px 4px;font-size:14px}}}}
</style></head><body>

<h1>Mecanum rover — bill of materials</h1>
<p>{esc(meta["subtitle"])}</p>

<div class="bar">
  <span class="big">Buy: ${buy_total:.2f}</span>
  <span>{buy_lines} lines · optional tools ${opt_total:.2f} more</span>
  <a class="btn" href="bom.csv" download>Download CSV</a>
  <a class="btn" href="drivetrain.txt">Drivetrain report</a>
</div>
<p class="muted">Prices observed {esc(meta["price_date"])} on Amazon US; check before checkout. Tick a box to mark it bought — it remembers on this device.</p>

<hr class="rule">

<h2>Can four motors carry it? <span class="sub">yes — with one condition</span></h2>
<p>{esc(meta["verdict"])}</p>
<div class="tw"><table>
<thead><tr><th>Driver / current</th><th class="n">Torque avail</th><th class="n">Level</th><th class="n">Strafe</th><th class="n">5° ramp</th><th>Verdict</th></tr></thead>
<tbody>
{"".join(f'<tr><td>{esc(r["name"])}</td><td class="n">{r["t"]:.3f} N·m</td><td class="n">{r["b"]:.2f}</td><td class="n">{r["d"]:.2f}</td><td class="n">{r["c"]:.2f}</td><td>{esc(r["v"])}</td></tr>' for r in meta["margins"])}
</tbody></table></div>
<p class="muted">Margin = available ÷ required; acceptance ≥ 1.25 on an unmeasured running torque. Design mass {meta["mass_kg"]} kg. The one number that retires the biggest assumption: measure pull-out torque at 24 rpm, 1.5 A, on the real battery.</p>

<hr class="rule">

<h2>Already owned <span class="sub">$0.00</span></h2>
<div class="tw"><table>
<thead><tr><th>Item</th><th class="n">Qty</th><th>Use</th></tr></thead>
<tbody>
{owned_rows}
</tbody></table></div>
{"".join(parts)}

<hr class="rule">
<h2>Not analysed</h2>
<p class="muted">{esc(meta["not_analysed"])}</p>
<p class="muted">Sources: <a href="https://static.jkongmotor.com/JK42HS40-1704-13A-aidlnBprKrkloSRilikkrllkn.pdf">motor drawing</a> · <a href="https://www.pololu.com/product/2133">DRV8825 current guidance</a> · <a href="https://www.pololu.com/product/1182">A4988 current guidance</a> · full arithmetic in <a href="drivetrain.txt">drivetrain.txt</a>.</p>

<script>
(function(){{
  var KEY='rover-bom-v2';
  var st={{}};try{{st=JSON.parse(localStorage.getItem(KEY)||'{{}}')}}catch(e){{}}
  document.querySelectorAll('input[type=checkbox]').forEach(function(cb){{
    var k=cb.dataset.key, tr=cb.closest('tr');
    if(st[k]){{cb.checked=true;tr.classList.add('done')}}
    cb.addEventListener('change',function(){{
      st[k]=cb.checked;tr.classList.toggle('done',cb.checked);
      try{{localStorage.setItem(KEY,JSON.stringify(st))}}catch(e){{}}
    }});
  }});
}})();
</script>
</body></html>
"""
open("index.html", "w").write(page)
print(f"index.html and bom.csv written — buy ${buy_total:.2f} over {buy_lines} lines, optional ${opt_total:.2f}")
