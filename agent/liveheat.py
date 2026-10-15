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
    ysym = dict(zip(df["Symbol"], df["Y"])) if "Y" in df.columns else {}
    data = []
    for t in tiles:
        d = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in t.items()}
        if t["sym"]:
            d["new"] = round(cur[t["sym"]], 3)
            d["old"] = round((prev or {}).get(t["sym"], cur[t["sym"]]), 3)
            d["px"] = round(price[t["sym"]], 2)
            if "Y" in df.columns:
                d["ys"] = ysym[t["sym"]]
                d["prev"] = round(price[t["sym"]] / (1 + cur[t["sym"]] / 100), 4) if cur[t["sym"]] > -99 else None
        data.append(d)
    payload = json.dumps({"tiles": data, "limit": float(limit)})
    return _TEMPLATE.replace("__DATA__", payload).replace("__H__", str(height)).replace(
        "__SUB__", html.escape(subtitle))


_TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:#0A0B0D;font-family:ui-monospace,Menlo,Consolas,monospace;color:#e8e8ea}
#top{display:flex;gap:14px;align-items:center;flex-wrap:wrap;font-size:11px;color:#9aa0aa;padding:4px 2px}
#dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#666;margin-right:5px}
#dot.on{background:#19d27a;animation:pulse 1.2s infinite}
@keyframes pulse{50%{opacity:.25}}
#top b{color:#e8e8ea}
#map{position:relative;width:100%;height:__H__px;overflow:hidden}
.sec{position:absolute;border:1px solid #0A0B0D;box-sizing:border-box;background:#121418}
.sl{position:absolute;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#9aa0aa;padding:2px 4px;white-space:nowrap;overflow:hidden;pointer-events:none}
.sl em{font-style:normal;margin-left:6px}
.t{position:absolute;box-sizing:border-box;border:1px solid #0A0B0D;display:flex;flex-direction:column;align-items:center;
   justify-content:center;overflow:hidden;transition:background-color .6s ease;cursor:default}
.t b{font-size:clamp(8px,1.15vw,14px);font-weight:600;white-space:nowrap}
.t i{font-style:normal;font-size:clamp(8px,1vw,12px);opacity:.95}
.t u{text-decoration:none;font-size:clamp(7px,.8vw,10px);opacity:.7}
#leg{display:flex;align-items:center;gap:6px;font-size:11px;color:#7d8490;padding:6px 2px}
#bar{flex:0 0 200px;height:8px;border-radius:4px;background:linear-gradient(90deg,#ff3b4e,#7a1f2a 30%,#1b1e24 50%,#14683e 70%,#19d27a)}
</style></head><body>
<div id="top"><span><span id="dot"></span><b id="st">connecting…</b></span><span id="tk"></span><span id="adv"></span><span id="avg"></span><span>__SUB__</span></div>
<div id="map"></div>
<div id="leg"><span>falling</span><div id="bar"></div><span>rising</span><span style="margin-left:12px">brighter = bigger move · each tick flashes the tile</span></div>
<script>
const D=__DATA__, LIM=D.limit||2, map=document.getElementById('map');
const N=[27,30,36], UP=[25,210,122], DN=[255,59,78];
function col(v){const a=Math.min(Math.abs(v)/LIM,1), c=v>=0?UP:DN, k=Math.pow(a,.75);
  return 'rgb('+[0,1,2].map(i=>Math.round(N[i]+(c[i]-N[i])*k)).join(',')+')';}
const fmt=v=>(v>=0?'+':'')+v.toFixed(2)+'%';
const bySym={}, secEls={}, secMembers={}, all=[];
for(const t of D.tiles){
  const e=document.createElement('div');
  e.style.left=t.x+'%';e.style.top=t.y+'%';e.style.width=t.w+'%';e.style.height=t.h+'%';
  if(t.sym===null){e.className='sec';const l=document.createElement('div');l.className='sl';
    l.innerHTML=t.sector+'<em></em>';e.appendChild(l);map.appendChild(e);secEls[t.sector]=l.querySelector('em');continue;}
  e.className='t';
  e.innerHTML='<b>'+t.sym+'</b><i></i><u></u>';
  const o={e,i:e.querySelector('i'),u:e.querySelector('u'),t,pct:t.old,px:t.px,prev:t.prev,ticks:0};
  o.i.textContent=fmt(t.old);o.u.textContent=t.px;e.style.backgroundColor=col(t.old);
  map.appendChild(e);all.push(o);(secMembers[t.sector]=secMembers[t.sector]||[]).push(o);
  if(t.ys)bySym[t.ys]=o;
}
// animate Python's previous snapshot -> current once
requestAnimationFrame(()=>requestAnimationFrame(()=>{for(const o of all){o.pct=o.t.new;o.e.style.backgroundColor=col(o.pct);o.i.textContent=fmt(o.pct);}summary();}));
function fit(){for(const o of all){const r=o.e.getBoundingClientRect();o.u.style.display=r.height<52?'none':'';o.i.style.display=r.height<30?'none':'';}}
function summary(){
  let up=0,dn=0,sum=0;for(const o of all){if(o.pct>0)up++;else if(o.pct<0)dn++;sum+=o.pct;}
  document.getElementById('adv').innerHTML='advancers <b>'+up+'</b> / decliners <b>'+dn+'</b>';
  document.getElementById('avg').innerHTML='market avg <b>'+fmt(sum/all.length)+'</b>';
  for(const s in secMembers){const m=secMembers[s],a=m.reduce((x,o)=>x+o.pct,0)/m.length,el=secEls[s];
    el.textContent=fmt(a);el.style.color=a>=0?'#19d27a':'#ff6b6b';}
}
fit();summary();addEventListener('resize',fit);
// ---- live ticks straight from Yahoo's websocket (runs in your browser, so it is real-time) ----
function b64(s){const bin=atob(s),u=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);return u;}
function decode(u){const dv=new DataView(u.buffer);let p=0;const r={};
  const vi=()=>{let x=0,sh=0,b;do{b=u[p++];x+=(b&127)*Math.pow(2,sh);sh+=7;}while(b&128);return x;};
  while(p<u.length){const tag=vi(),f=tag>>3,w=tag&7;
    if(w===0)vi();else if(w===1)p+=8;
    else if(w===2){const n=vi();if(f===1)r.id=new TextDecoder().decode(u.subarray(p,p+n));p+=n;}
    else if(w===5){const v=dv.getFloat32(p,true);p+=4;if(f===2)r.price=v;else if(f===8)r.chg=v;else if(f===16)r.prev=v;}
    else break;}
  return r;}
const pending={};let ticks=0,recent=[],ws,retry=0;
function setSt(t,on){document.getElementById('st').textContent=t;document.getElementById('dot').className=on?'on':'';}
function connect(){
  ws=new WebSocket('wss://streamer.finance.yahoo.com/?version=2');
  ws.onopen=()=>{retry=0;setSt('LIVE · waiting for ticks',true);
    ws.send(JSON.stringify({subscribe:Object.keys(bySym)}));};
  ws.onmessage=ev=>{try{const m=JSON.parse(ev.data);if(m.type!=='pricing')return;
    const r=decode(b64(m.message));if(r.id&&bySym[r.id]&&r.price>0){pending[r.id]=r;ticks++;recent.push(Date.now());}}catch(e){}};
  ws.onclose=()=>{setSt('reconnecting…',false);setTimeout(connect,Math.min(15000,1000*(++retry)));};
  ws.onerror=()=>{try{ws.close();}catch(e){}};
}
function flash(e,up){e.animate([{filter:'brightness(2.3)',boxShadow:'inset 0 0 0 2px '+(up?'#5dffa0':'#ff6b6b')},
  {filter:'brightness(1)',boxShadow:'inset 0 0 0 0 transparent'}],{duration:900,easing:'ease-out'});}
function frame(){
  const ks=Object.keys(pending);
  for(const k of ks){const r=pending[k],o=bySym[k];delete pending[k];
    const prev=r.prev>0?r.prev:o.prev;let pct=prev>0?(r.price/prev-1)*100:(r.chg!=null?r.chg:o.pct);
    if(r.prev>0)o.prev=r.prev;
    const oldpx=o.px,moved=r.price!==oldpx;
    o.px=r.price;o.pct=pct;o.ticks++;
    o.i.textContent=fmt(pct);o.u.textContent=r.price.toFixed(2);o.e.style.backgroundColor=col(pct);
    o.e.title=k+'  '+r.price.toFixed(2)+'  '+fmt(pct)+'  ('+o.ticks+' ticks)';
    if(moved)flash(o.e,r.price>oldpx);}
  if(ks.length){summary();document.getElementById('tk').innerHTML='last tick <b>'+new Date().toLocaleTimeString()+'</b>';}
  const now=Date.now();recent=recent.filter(t=>now-t<10000);
  if(ws&&ws.readyState===1&&ticks>0)setSt('LIVE · '+recent.length+' ticks / 10s',true);
  requestAnimationFrame(frame);
}
connect();requestAnimationFrame(frame);
</script></body></html>"""
