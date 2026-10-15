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
    trend = dict(zip(df["Symbol"], df["Trend"])) if "Trend" in df.columns else {}
    data = []
    for t in tiles:
        d = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in t.items()}
        if t["sym"]:
            d["new"] = round(cur[t["sym"]], 3)
            d["old"] = round((prev or {}).get(t["sym"], cur[t["sym"]]), 3)
            d["px"] = round(price[t["sym"]], 2)
            if "Trend" in df.columns:
                trd = trend[t["sym"]]
                d["tr"] = [round(float(v), 2) for v in trd][-30:] if trd is not None and len(trd) else []
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
#srh{display:grid;grid-template-columns:34px minmax(110px,1.6fr) 70px 90px minmax(120px,2fr) 80px;gap:8px;padding:14px 10px 6px;color:#7d8490;font-size:10px;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid #22252c}
#sr{position:relative}
.sr{position:absolute;left:0;right:0;height:32px;display:grid;grid-template-columns:34px minmax(110px,1.6fr) 70px 90px minmax(120px,2fr) 80px;gap:8px;align-items:center;padding:0 10px;
  box-sizing:border-box;border:1px solid #1b1e24;background:#111317;border-radius:6px;transition:transform .7s cubic-bezier(.2,.8,.2,1)}
.sr .n{color:#9aa0aa;font-weight:700}.sr .mv{font-size:10px;margin-left:3px}.sr b{font-size:12px}
.sr .trk{height:8px;background:#1b1e24;border-radius:4px;position:relative;overflow:hidden}
.sr .trk i{position:absolute;top:0;bottom:0;transition:left .5s,width .5s,background-color .5s}
.sr .v{text-align:right;font-weight:700}.up{color:#19d27a}.dn{color:#ff6b6b}
#dh{display:flex;align-items:center;gap:12px;padding:18px 2px 8px;color:#7d8490;font-size:11px;letter-spacing:.1em;text-transform:uppercase}
#dsel{background:#111317;color:#e8e8ea;border:1px solid #2a2e36;border-radius:6px;padding:6px 10px;font-family:inherit;font-size:12px}
#dhd,.dr{display:grid;grid-template-columns:34px minmax(90px,1.2fr) 90px minmax(120px,2fr) 80px 110px;gap:8px;align-items:center;padding:0 10px;box-sizing:border-box}
#dhd{height:24px;color:#7d8490;font-size:10px;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid #22252c}
#dl{position:relative}
.dr{position:absolute;left:0;right:0;height:32px;border:1px solid #1b1e24;background:#111317;border-radius:6px;transition:transform .7s cubic-bezier(.2,.8,.2,1),opacity .4s}
.dr.out{opacity:0;pointer-events:none}.dr .n{color:#9aa0aa;font-weight:700}.dr b{font-size:12px}.dr .mv{font-size:10px;margin-left:3px}
.dr .trk{height:8px;background:#1b1e24;border-radius:4px;position:relative;overflow:hidden}
.dr .trk i{position:absolute;top:0;bottom:0;transition:left .5s,width .5s,background-color .5s}
.dr .v{text-align:right;font-weight:700}.dr svg{display:block}
#leg{display:flex;align-items:center;gap:6px;font-size:11px;color:#7d8490;padding:6px 2px}
#bar{flex:0 0 200px;height:8px;border-radius:4px;background:linear-gradient(90deg,#ff3b4e,#7a1f2a 30%,#1b1e24 50%,#14683e 70%,#19d27a)}
</style></head><body>
<div id="top"><span><span id="dot"></span><b id="st">connecting…</b></span><span id="tk"></span><span id="adv"></span><span id="avg"></span><span>__SUB__</span></div>
<div id="map"></div>
<div id="leg"><span>falling</span><div id="bar"></div><span>rising</span><span style="margin-left:12px">brighter = bigger move · each tick flashes the tile</span></div>
<div id="srh"><span>#</span><span>Sector (live ranking)</span><span>Stocks</span><span>Up / down</span><span>Average move today</span><span style="text-align:right">Avg</span></div>
<div id="sr"></div>
<div id="dh"><span>Drill into a sector</span><select id="dsel"></select><span id="dnote"></span></div>
<div id="dhd"><span>#</span><span>Stock</span><span>Price</span><span>Move today</span><span style="text-align:right">Change</span><span>30-day trend + live</span></div>
<div id="dl"></div>
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
const SRH=36,srEl=document.getElementById('sr'),srRows={};let srInit=null;
srEl.style.height=(Object.keys(secMembers).length*SRH+6)+'px';
for(const s of Object.keys(secMembers)){const e=document.createElement('div');e.className='sr';
  e.innerHTML='<span class="n"></span><b>'+s+'</b><span class="c"></span><span class="ud"></span><span class="trk"><i></i></span><span class="v"></span>';
  srEl.appendChild(e);srRows[s]={e,n:e.querySelector('.n'),ud:e.querySelector('.ud'),bar:e.querySelector('.trk i'),v:e.querySelector('.v'),c:e.querySelector('.c'),last:null};
  srRows[s].c.textContent=secMembers[s].length;}
function srUpdate(first){
  const list=Object.keys(secMembers).map(s=>{const m=secMembers[s];return {s,a:m.reduce((x,o)=>x+o.pct,0)/m.length,up:m.filter(o=>o.pct>0).length,dn:m.filter(o=>o.pct<0).length};}).sort((x,y)=>y.a-x.a);
  const mx=Math.max(1,...list.map(x=>Math.abs(x.a)));
  if(!srInit){srInit={};list.forEach((x,i)=>srInit[x.s]=i);}
  list.forEach((x,i)=>{const r=srRows[x.s];r.e.style.transform='translateY('+(i*SRH)+'px)';
    const mv=srInit[x.s]-i;r.n.innerHTML=(i+1)+(mv>0?'<span class="mv up">▲'+mv+'</span>':mv<0?'<span class="mv dn">▼'+(-mv)+'</span>':'');
    r.ud.innerHTML='<span class="up">'+x.up+'↑</span> <span class="dn">'+x.dn+'↓</span>';
    const w=Math.min(Math.abs(x.a)/mx,1)*50;r.bar.style.left=x.a>=0?'50%':(50-w)+'%';r.bar.style.width=w+'%';
    r.bar.style.backgroundColor=x.a>=0?'#19d27a':'#ff6b6b';
    r.v.textContent=fmt(x.a);r.v.className='v '+(x.a>=0?'up':'dn');
    if(r.last!==null&&Math.abs(x.a-r.last)>=0.005&&!first)r.e.animate([{backgroundColor:x.a>r.last?'#17472f':'#4a1c24'},{backgroundColor:'#111317'}],{duration:900});
    r.last=x.a;});
}
const DRH=36,dl=document.getElementById('dl'),dsel=document.getElementById('dsel');let dInit=null,dSector=null;
const maxN=Math.max(...Object.values(secMembers).map(m=>m.length));dl.style.height=(maxN*DRH+6)+'px';
for(const o of all){const e=document.createElement('div');e.className='dr out';
  e.innerHTML='<span class="n"></span><b>'+o.t.sym+'</b><span class="p"></span><span class="trk"><i></i></span><span class="v"></span><span class="sp"></span>';
  dl.appendChild(e);o.dr={e,n:e.querySelector('.n'),p:e.querySelector('.p'),bar:e.querySelector('.trk i'),v:e.querySelector('.v'),sp:e.querySelector('.sp'),last:null};}
function spark(o){const tr=(o.t.tr||[]).slice();if(!tr.length)return '';tr[tr.length-1]=o.px;
  const mn=Math.min(...tr),mx=Math.max(...tr),w=100,h=22,rg=(mx-mn)||1;
  const pts=tr.map((v,i)=>(i/(tr.length-1||1)*w).toFixed(1)+','+(h-2-(v-mn)/rg*(h-4)).toFixed(1)).join(' ');
  const up=tr[tr.length-1]>=tr[0];
  return '<svg width="'+w+'" height="'+h+'"><polyline fill="none" stroke="'+(up?'#19d27a':'#ff6b6b')+'" stroke-width="1.5" points="'+pts+'"/></svg>';}
function drUpdate(first,reset){
  const sec=dsel.value;if(sec!==dSector||reset){dSector=sec;dInit=null;}
  const m=secMembers[sec].slice().sort((a,b)=>b.pct-a.pct);
  if(!dInit){dInit={};m.forEach((o,i)=>dInit[o.t.sym]=i);}
  const mx=Math.max(1,...m.map(o=>Math.abs(o.pct))),inSec=new Set(m);
  for(const o of all)if(!inSec.has(o)){o.dr.e.classList.add('out');}
  m.forEach((o,i)=>{const d=o.dr;d.e.classList.remove('out');d.e.style.transform='translateY('+(i*DRH)+'px)';
    const mv=dInit[o.t.sym]-i;d.n.innerHTML=(i+1)+(mv>0?'<span class="mv up">▲'+mv+'</span>':mv<0?'<span class="mv dn">▼'+(-mv)+'</span>':'');
    d.p.textContent=Number(o.px).toFixed(2);const w=Math.min(Math.abs(o.pct)/mx,1)*50;
    d.bar.style.left=o.pct>=0?'50%':(50-w)+'%';d.bar.style.width=w+'%';d.bar.style.backgroundColor=o.pct>=0?'#19d27a':'#ff6b6b';
    d.v.textContent=fmt(o.pct);d.v.className='v '+(o.pct>=0?'up':'dn');d.sp.innerHTML=spark(o);
    if(d.last!==null&&d.lastpx!==o.px&&!first)d.e.animate([{backgroundColor:o.px>d.lastpx?'#17472f':'#4a1c24'},{backgroundColor:'#111317'}],{duration:900});
    d.last=o.pct;d.lastpx=o.px;});
}
const avgNew=k=>secMembers[k].reduce((x,o)=>x+o.t.new,0)/secMembers[k].length;
for(const s of Object.keys(secMembers).sort((a,b)=>avgNew(b)-avgNew(a))){const op=document.createElement('option');op.value=s;op.textContent=s;dsel.appendChild(op);}
dsel.addEventListener('change',()=>drUpdate(true,true));
function fit(){for(const o of all){const r=o.e.getBoundingClientRect();o.u.style.display=r.height<52?'none':'';o.i.style.display=r.height<30?'none':'';}}
function summary(){
  let up=0,dn=0,sum=0;for(const o of all){if(o.pct>0)up++;else if(o.pct<0)dn++;sum+=o.pct;}
  document.getElementById('adv').innerHTML='advancers <b>'+up+'</b> / decliners <b>'+dn+'</b>';
  document.getElementById('avg').innerHTML='market avg <b>'+fmt(sum/all.length)+'</b>';
  srUpdate(false);drUpdate(false,false);
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
