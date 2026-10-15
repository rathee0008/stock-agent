"""Animated treemap heatmap as a self-contained HTML block (for st.components.v1.html).

Layout is computed here (squarified treemap, equal weight per stock, grouped by sector).
Colour = direction (green/red) with brightness proportional to the size of the move, so
small moves are dim and big moves glow. On every refresh the block is drawn with the
*previous* values and then transitions to the new ones: tile colour fades, the number
counts to the new value, and tiles whose value changed flash briefly.
"""

from __future__ import annotations

import html
import json

import pandas as pd


def _worst(row: list[float], w: float) -> float:
    s = sum(row)
    return max(max(w * w * r / (s * s), s * s / (w * w * r)) for r in row)


def squarify(values: list[float], x: float, y: float, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """Squarified treemap. Returns one (x, y, w, h) rect per value, in the input order."""
    n = len(values)
    if n == 0:
        return []
    tot = sum(values) or 1.0
    scale = w * h / tot
    areas = [v * scale for v in values]
    order = sorted(range(n), key=lambda i: -areas[i])
    rects: dict[int, tuple[float, float, float, float]] = {}
    i = 0
    while i < n:
        side = min(w, h)
        row = [areas[order[i]]]
        j = i + 1
        while j < n and _worst(row + [areas[order[j]]], side) <= _worst(row, side):
            row.append(areas[order[j]])
            j += 1
        s = sum(row)
        if w >= h:                       # lay the row as a column on the left
            cw = s / h
            yy = y
            for k, a in zip(order[i:j], row):
                rects[k] = (x, yy, cw, a / cw)
                yy += a / cw
            x, w = x + cw, w - cw
        else:                            # lay the row along the top
            rh = s / w
            xx = x
            for k, a in zip(order[i:j], row):
                rects[k] = (xx, y, a / rh, rh)
                xx += a / rh
            y, h = y + rh, h - rh
        i = j
    return [rects[k] for k in range(n)]


def layout(df: pd.DataFrame) -> list[dict]:
    """Tiles with percent coordinates: [{sym, sector, x, y, w, h, hdr}], plus sector boxes (sym=None)."""
    groups = {s: g for s, g in df.groupby("Sector")}
    names = list(groups)
    boxes = squarify([float(len(groups[s])) for s in names], 0, 0, 100, 100)
    out: list[dict] = []
    for name, (bx, by, bw, bh) in zip(names, boxes):
        out.append({"sector": name, "sym": None, "x": bx, "y": by, "w": bw, "h": bh})
        g = groups[name]
        pad = 0.35
        ih = min(3.2, bh * 0.2)           # header strip for the sector label (percent of full height)
        rects = squarify([1.0] * len(g), bx + pad, by + ih, max(bw - 2 * pad, 0.1), max(bh - ih - pad, 0.1))
        for sym, (x, y, w, h) in zip(g["Symbol"], rects):
            out.append({"sector": name, "sym": sym, "x": x, "y": y, "w": w, "h": h})
    return out


def build_html(df: pd.DataFrame, prev: dict[str, float] | None, limit: float, height: int = 560,
               subtitle: str = "") -> str:
    """HTML for one frame. ``prev`` maps Symbol -> previous Change %, or None on the first draw."""
    tiles = layout(df)
    cur = dict(zip(df["Symbol"], df["Change %"].astype(float)))
    price = dict(zip(df["Symbol"], df["Price"].astype(float)))
    data = []
    for t in tiles:
        d = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in t.items()}
        if t["sym"]:
            d["new"] = round(cur[t["sym"]], 3)
            d["old"] = round((prev or {}).get(t["sym"], cur[t["sym"]]), 3)
            d["px"] = round(price[t["sym"]], 2)
        data.append(d)
    payload = json.dumps({"tiles": data, "limit": float(limit)})
    return _TEMPLATE.replace("__DATA__", payload).replace("__H__", str(height)).replace(
        "__SUB__", html.escape(subtitle))


_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:#0A0B0D;font-family:ui-monospace,Menlo,Consolas,monospace;color:#e8e8ea}
#map{position:relative;width:100%;height:__H__px;overflow:hidden}
.sec{position:absolute;border:1px solid #0A0B0D;box-sizing:border-box;background:#121418}
.sl{position:absolute;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#9aa0aa;padding:2px 4px;white-space:nowrap;overflow:hidden;pointer-events:none}
.t{position:absolute;box-sizing:border-box;border:1px solid #0A0B0D;display:flex;flex-direction:column;align-items:center;
   justify-content:center;overflow:hidden;transition:background-color 1.1s ease,box-shadow .6s ease;cursor:default}
.t b{font-size:clamp(8px,1.15vw,14px);font-weight:600;white-space:nowrap}
.t i{font-style:normal;font-size:clamp(8px,1vw,12px);opacity:.92}
.t.flashup{animation:fu 1.4s ease-out}.t.flashdn{animation:fd 1.4s ease-out}
@keyframes fu{0%{filter:brightness(2.2);box-shadow:inset 0 0 0 2px #5dffa0}60%{filter:brightness(1.3)}100%{filter:brightness(1)}}
@keyframes fd{0%{filter:brightness(2.2);box-shadow:inset 0 0 0 2px #ff6b6b}60%{filter:brightness(1.3)}100%{filter:brightness(1)}}
#sub{font-size:11px;color:#7d8490;padding:4px 2px}
#leg{display:flex;align-items:center;gap:6px;font-size:11px;color:#7d8490;padding:6px 2px}
#bar{flex:0 0 200px;height:8px;border-radius:4px;background:linear-gradient(90deg,#ff3b4e,#7a1f2a 30%,#1b1e24 50%,#14683e 70%,#19d27a)}
</style></head><body>
<div id="sub">__SUB__</div><div id="map"></div>
<div id="leg"><span>falling</span><div id="bar"></div><span>rising</span><span style="margin-left:12px">brighter = bigger move</span></div>
<script>
const D=__DATA__, LIM=D.limit||2, map=document.getElementById('map');
const N=[27,30,36], UP=[25,210,122], DN=[255,59,78];
function col(v){const a=Math.min(Math.abs(v)/LIM,1), c=v>=0?UP:DN;
  // dim near zero, bright at the limit; keep a floor so tiny moves are still visible
  const k=Math.pow(a,.75);return 'rgb('+[0,1,2].map(i=>Math.round(N[i]+(c[i]-N[i])*k)).join(',')+')';}
function fmt(v){return (v>=0?'+':'')+v.toFixed(2)+'%';}
const els=[];
for(const t of D.tiles){
  const e=document.createElement('div');
  e.style.left=t.x+'%';e.style.top=t.y+'%';e.style.width=t.w+'%';e.style.height=t.h+'%';
  if(t.sym===null){e.className='sec';const l=document.createElement('div');l.className='sl';l.textContent=t.sector;e.appendChild(l);map.appendChild(e);continue;}
  e.className='t';e.title=t.sym+'  '+t.px+'  '+fmt(t.new);
  e.innerHTML='<b>'+t.sym+'</b><i></i>';
  const i=e.querySelector('i');i.textContent=fmt(t.old);
  e.style.backgroundColor=col(t.old);
  map.appendChild(e);els.push([e,i,t]);
}
// next frame: animate old -> new (colour fades via CSS, number counts up/down, changed tiles flash)
requestAnimationFrame(()=>requestAnimationFrame(()=>{
  const t0=performance.now(),dur=1100;
  for(const [e,i,t] of els){
    e.style.backgroundColor=col(t.new);
    if(Math.abs(t.new-t.old)>=0.005)e.classList.add(t.new>t.old?'flashup':'flashdn');
  }
  (function step(now){const p=Math.min((now-t0)/dur,1),q=1-Math.pow(1-p,3);
    for(const [e,i,t] of els)i.textContent=fmt(t.old+(t.new-t.old)*q);
    if(p<1)requestAnimationFrame(step);})(t0);
}));
</script></body></html>"""
