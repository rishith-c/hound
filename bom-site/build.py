#!/usr/bin/env python3
"""Build the BOM site from bom.json: writes index.html and bom.csv.

Visual style is the ChatGPT-authored page this project shipped first (Vercel
deployment dpl_7Uxg94gpHed7fCG2Yc6mctUCd4LA): a document, not a dashboard.
System font, #202124 text, #165bc4 links, bordered tables with a grey header
row, an "I have this" checkbox column whose state persists in the browser and
tints the row green. Kept verbatim; only the content underneath changed.

    python3 build.py
"""

import csv
import html
import json

BOM = json.load(open("bom.json"))
sections = BOM["sections"]
owned = BOM["owned"]
meta = BOM["meta"]
prose = BOM["prose"]

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

# ── HTML helpers ────────────────────────────────────────────────────────────
def esc(x):
    return html.escape(str(x))

def link(asin, text):
    return (f'<a target="_blank" rel="noopener noreferrer" '
            f'href="https://www.amazon.com/dp/{esc(asin)}">{esc(text)}</a>')

def buy_table(items):
    rows = []
    for it in items:
        note = f'<div class="note">{esc(it["note"])}</div>' if it.get("note") else ""
        rows.append(
            f'<tr>\n<td class="have-cell"><input type="checkbox" data-item="{esc(it["asin"])}" '
            f'aria-label="I have all required quantities of {esc(it["item"])}"></td>'
            f'<td>{link(it["asin"], it["item"])}{note}</td>\n'
            f'<td align="right">{it["packs"]}</td>\n'
            f'<td align="right">${it["price"]:.2f}</td>\n'
            f'<td align="right">${it["packs"] * it["price"]:.2f}</td>\n</tr>')
    return f"""<div class="table-wrap"><table>
<thead>
<tr>
<th class="have-cell" scope="col">I have this</th><th>Item / exact Amazon listing</th>
<th align="right">Buy packs</th>
<th align="right">Per pack</th>
<th align="right">Line total</th>
</tr>
</thead>
<tbody>{"".join(rows)}
</tbody></table></div>"""

def paras(lines):
    return "\n".join(f"<p>{esc(p)}</p>" for p in lines)

def bullets(lines):
    return "<ul>\n" + "\n".join(f"<li>{esc(p)}</li>" for p in lines) + "\n</ul>"

# ── sections ────────────────────────────────────────────────────────────────
buy_sections = []
for s in sections:
    if s.get("optional"):
        continue
    why = f"<p>{esc(s['why'])}</p>" if s.get("why") else ""
    buy_sections.append(f"<h3>{esc(s['name'])} <span class=\"sub\">${total(s):.2f}</span></h3>\n{why}\n{buy_table(s['items'])}")

optional = [s for s in sections if s.get("optional")]
optional_html = "".join(
    (f"<p>{esc(s['why'])}</p>\n" if s.get("why") else "") + buy_table(s["items"]) for s in optional)

owned_rows = "".join(
    f'<tr>\n<td>{esc(o["item"])}</td>\n<td align="right">{esc(o["qty"])}</td>\n<td>{esc(o["note"])}</td>\n</tr>\n'
    for o in owned)

margin_rows = "".join(
    f'<tr>\n<td>{esc(r["name"])}</td>\n<td align="right">{r["t"]:.3f} N·m</td>\n'
    f'<td align="right">{r["b"]:.2f}</td>\n<td align="right">{r["d"]:.2f}</td>\n'
    f'<td align="right">{r["c"]:.2f}</td>\n<td>{esc(r["v"])}</td>\n</tr>\n'
    for r in meta["margins"])

page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Rover Amazon BOM</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#fff;color:#202124;font:16px/1.65 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}main{{max-width:1040px;margin:48px auto;padding:0 24px 60px}}h1{{font-size:30px;line-height:1.25}}h2{{font-size:22px;margin-top:36px}}h3{{font-size:18px;margin:28px 0 4px}}h3 .sub{{font-weight:400;color:#555;font-size:15px;margin-left:8px}}a{{color:#165bc4;text-underline-offset:3px}}table{{border-collapse:collapse;width:100%;font-size:14px;margin:20px 0}}th,td{{padding:10px 12px;border:1px solid #ddd;text-align:left;vertical-align:top}}th{{background:#f5f6f7}}code{{background:#f3f4f5;padding:2px 4px;border-radius:3px}}.table-wrap{{overflow-x:auto}}p{{margin:16px 0}}.note{{font-size:13px;color:#555;margin-top:4px}}@media(max-width:600px){{main{{margin:28px auto;padding:0 16px 36px}}h1{{font-size:26px}}table{{min-width:620px}}}}@media print{{main{{max-width:none;margin:0;padding:0}}a{{color:inherit}}}}
input[type="checkbox"]{{width:20px;height:20px;accent-color:#165bc4;cursor:pointer}}.have-cell{{text-align:center;white-space:nowrap}}tr.owned td{{background:#eff8f0}}#checklist-note{{font-size:14px;color:#555}}
</style></head><body><main><h1>{esc(meta["title"])}</h1>
<p><strong>Recommended purchases: ${buy_total:.2f} USD before tax/shipping. Optional workshop tools: ${opt_total:.2f}.</strong> {esc(meta["intro"])}</p>
<p><a href="bom.csv" download>Download the BOM as CSV</a> · <a href="drivetrain.txt">Read the full drivetrain calculation</a></p>
<h2>The design I would build</h2>
{paras(prose["design"])}
<h2>Can four motors carry it?</h2>
<p>{esc(meta["verdict"])}</p>
<div class="table-wrap"><table>
<thead>
<tr>
<th>Driver / current setting</th>
<th align="right">Torque available</th>
<th align="right">Level floor</th>
<th align="right">Strafe</th>
<th align="right">5° ramp</th>
<th>Verdict</th>
</tr>
</thead>
<tbody>{margin_rows}</tbody></table></div>
<p>{esc(meta["margin_note"])}</p>
<h2>Already owned — no purchase required</h2>
<div class="table-wrap"><table>
<thead>
<tr>
<th>Item</th>
<th align="right">Quantity</th>
<th>Use</th>
</tr>
</thead>
<tbody>{owned_rows}</tbody></table></div>
<h2>Buy list</h2><p id="checklist-note" role="status">Selections are saved in this browser only.</p>
<p>Check items when you have the full listed quantity. The website saves selections in your browser. Parts are grouped by what they do on the rover.</p>
{"".join(buy_sections)}
<h2>Power and connections</h2>
{bullets(prose["power"])}
{paras(prose["power_after"])}
<h2>Motor and frame fit</h2>
{paras(prose["fit"])}
<h2>Compute before claiming it works</h2>
{paras(prose["compute"])}
<h2>Optional workshop tools — only if unavailable</h2>
{optional_html}
<h2>What I did NOT analyze</h2>
<p>{esc(meta["not_analysed"])}</p>
<p>Sources: <a target="_blank" rel="noopener noreferrer" href="https://static.jkongmotor.com/JK42HS40-1704-13A-aidlnBprKrkloSRilikkrllkn.pdf">motor drawing</a>, <a target="_blank" rel="noopener noreferrer" href="https://www.pololu.com/product/2133">DRV8825 current/cooling</a>, <a target="_blank" rel="noopener noreferrer" href="https://www.pololu.com/product/1182">A4988 current/cooling</a>, <a target="_blank" rel="noopener noreferrer" href="https://www.hlktech.com/en/Goods-239.html">LD2410C manufacturer</a>, <a target="_blank" rel="noopener noreferrer" href="https://docs.espressif.com/projects/esp-techpedia/en/latest/esp-friends/solution-introduction/esp-csi/esp-csi-solution.html">Espressif CSI</a>, <a target="_blank" rel="noopener noreferrer" href="https://www.skyrc.com/download/100200%20B6ACneo%20Instruction%20Manual%20V1.3.pdf">SKYRC B6AC Neo manual</a>, <a href="drivetrain.txt">drivetrain.txt</a> (all arithmetic).</p>
</main><script>
const note = document.getElementById('checklist-note');
const prefix = 'rover-bom-owned-v2:';
for (const checkbox of document.querySelectorAll('input[data-item]')) {{
  const key = prefix + checkbox.dataset.item;
  const paint = () => checkbox.closest('tr').classList.toggle('owned', checkbox.checked);
  try {{ checkbox.checked = localStorage.getItem(key) === 'true'; }}
  catch {{ note.textContent = 'Browser storage is unavailable; selections will last only until this page closes. Check items when you have the full quantity listed.'; }}
  paint();
  checkbox.addEventListener('change', () => {{
    paint();
    try {{ localStorage.setItem(key, String(checkbox.checked)); }}
    catch {{ note.textContent = 'Selections could not be saved in this browser. Keep this page open to retain them.'; }}
  }});
}}
</script></body></html>
"""
open("index.html", "w").write(page)
print(f"index.html and bom.csv written — buy ${buy_total:.2f}, optional ${opt_total:.2f}")
