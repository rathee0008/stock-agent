"""Live re-ranking of the Top-20 list from streaming prices (HTML block for st.components.v1.html).

The slow, expensive part (technical + fundamental + news score) is computed once in Python and
shipped here as ``Base``. In the browser, Yahoo's price websocket then updates every stock's
intraday move and the list is re-scored and re-ranked on each tick:

    live score = base score + live tilt

    live tilt  = clamp(2.5 x day %, -10, +10)          # confirms / contradicts the base view
                 - 8 if day % > +6                       # overextended spike: don't chase
                 - 6 if day % < -6                       # falling knife: wait for it to settle

Rows glide to their new rank, flash on price ticks, and show rank movement since you opened the page.
It is a rule-based screen, not advice.
"""

from __future__ import annotations

import json

import pandas as pd


def build_html(pool: pd.DataFrame, n: int = 20, balanced: bool = False, height: int = 0) -> str:
    rows = []
    for _, r in pool.iterrows():
        price = float(r["Price"])
        day = float(r["Day %"]) if pd.notna(r["Day %"]) else 0.0
        rows.append({
            "y": r["Symbol"], "sym": str(r["Symbol"]).replace(".NS", ""), "name": str(r.get("Name") or r["Symbol"])[:28],
            "mkt": r["Market"], "px": round(price, 2), "day": round(day, 3),
            "prev": round(price / (1 + day / 100), 4) if day > -99 else price,
            "base": float(r["Score"]), "rsi": None if pd.isna(r.get("RSI")) else round(float(r["RSI"]), 1),
            "sector": str(r.get("Sector") or ""),
        })
    h = height or (n * 46 + 90)
    return (_TEMPLATE.replace("__DATA__", json.dumps({"rows": rows, "n": n, "balanced": balanced}))
            .replace("__H__", str(n * 46)).replace("__PAGEH__", str(h)))


_TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:#0A0B0D;font-family:ui-monospace,Menlo,Consolas,monospace;color:#e8e8ea;font-size:12px}
#top{display:flex;gap:16px;align-items:center;flex-wrap:wrap;color:#9aa0aa;padding:6px 2px}
#dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#666;margin-right:5px}
#dot.on{background:#19d27a;animation:pulse 1.2s infinite}@keyframes pulse{50%{opacity:.25}}
#top b{color:#e8e8ea}
.hd,.r{display:grid;grid-template-columns:38px 54px minmax(120px,2.2fr) 84px 70px 56px 56px minmax(120px,1.6fr) minmax(110px,1.6fr);
  align-items:center;gap:8px;padding:0 10px;box-sizing:border-box}
.hd{height:26px;color:#7d8490;font-size:10px;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid #22252c}
#list{position:relative;height:__H__px}
.r{position:absolute;left:0;right:0;height:42px;border:1px solid #1b1e24;background:#111317;border-radius:6px;
   transition:transform .7s cubic-bezier(.2,.8,.2,1),opacity .5s,background-color .4s}
.r.out{opacity:0;pointer-events:none}
.num{font-weight:700;color:#9aa0aa}.mv{font-size:10px;margin-left:3px}
.chip{font-size:10px;padding:1px 5px;border-radius:3px;text-align:center}
.IN{background:#3a2a10;color:#ffb347}.US{background:#10283f;color:#6db7ff}
.nm small{display:block;color:#7d8490;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nm b{font-size:13px}
.up{color:#19d27a}.dn{color:#ff6b6b}.fl{color:#9aa0aa}
.bar{height:6px;border-radius:3px;background:#1b1e24;position:relative;overflow:hidden}
.bar i{position:absolute;top:0;bottom:0;transition:all .5s}
.sc{display:flex;align-items:center;gap:8px}.sc b{width:42px;text-align:right}
.sig{font-size:11px;color:#9aa0aa;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.new{font-size:9px;background:#19d27a;color:#04210f;padding:0 4px;border-radius:3px;margin-left:5px}
#note{color:#7d8490;font-size:11px;padding:8px 2px;line-height:1.5}
@media(max-width:760px){.hd,.r{grid-template-columns:30px 40px 1.6fr 70px 60px 90px}
  .hd>:nth-child(6),.hd>:nth-child(7),.hd>:nth-child(9),.r>:nth-child(6),.r>:nth-child(7),.r>:nth-child(9){display:none}}
</style></head><body>
<div id="top"><span><span id="dot"></span><b id="st">connecting…</b></span><span id="tk"></span><span id="ch"></span></div>
<div class="hd"><span>#</span><span>Mkt</span><span>Stock</span><span>Price</span><span>Day</span><span>Base</span><span>Live</span><span>Live score</span><span>Signal</span></div>
<div id="list"></div>
<div id="note">Live score = base score (technicals + fundamentals + news, computed when the page loaded) + a live tilt from today's move:
 +2.5 × day % (capped ±10), −8 if up more than 6% (overextended, don't chase), −6 if down more than 6% (falling knife).
 Rows re-rank on every price tick and flash when a price changes. ▲▼ = places gained/lost since you opened the page. Rule-based screen, not advice.</div>
<script>
const D=__DATA__, N=D.n, RH=46, list=document.getElementById('list');
const rows=D.rows.map(r=>({...r,price:r.px,pday:r.day,prev:r.prev,ticks:0}));
function tilt(r){let d=r.pday,a=Math.max(-10,Math.min(10,2.5*d));if(d>6)a-=8;if(d<-6)a-=6;return a;}
function sig(r){const d=r.pday;
  if(d>6)return 'Overextended: wait for a pullback';if(d<-6)return 'Falling knife: wait to settle';
  if(d>1.5)return 'Strengthening today';if(d<-1.5)return 'Weakening today';
  if(r.rsi&&r.rsi>70)return 'Strong but stretched (RSI '+r.rsi+')';return 'Steady';}
const cls=v=>v>0.005?'up':v<-0.005?'dn':'fl', f2=(v,s)=>(s&&v>=0?'+':'')+v.toFixed(2);
for(const r of rows){const e=document.createElement('div');e.className='r out';
  e.innerHTML='<span class="num"></span><span><span class="chip '+r.mkt+'">'+(r.mkt==='IN'?'IN':'US')+'</span></span>'+
   '<span class="nm"><b>'+r.sym+'</b><span class="newtag"></span><small>'+r.name+'</small></span><span class="px"></span><span class="dy"></span>'+
   '<span class="bs fl"></span><span class="lv"></span><span class="sc"><span class="bar" style="flex:1"><i></i></span><b></b></span><span class="sig"></span>';
  r.e=e;r.q={num:e.querySelector('.num'),px:e.querySelector('.px'),dy:e.querySelector('.dy'),bs:e.querySelector('.bs'),
   lv:e.querySelector('.lv'),bar:e.querySelector('.bar i'),sc:e.querySelector('.sc b'),sig:e.querySelector('.sig'),tag:e.querySelector('.newtag')};
  list.appendChild(e);}
let order=null,initial=null,shown=new Set();
function pick(){
  const sc=rows.map(r=>({r,s:r.base+tilt(r)})).sort((a,b)=>b.s-a.s);
  if(!D.balanced)return sc.slice(0,N).map(x=>x.r);
  const half=N/2,by=m=>sc.filter(x=>x.r.mkt===m).slice(0,half);
  return by('IN').concat(by('US')).sort((a,b)=>b.s-a.s).map(x=>x.r);}
function render(first){
  const top=pick(),inTop=new Set(top);
  top.forEach((r,i)=>{
    const live=r.base+tilt(r);r.live=live;
    r.e.classList.remove('out');r.e.style.transform='translateY('+(i*RH)+'px)';
    r.q.num.textContent=i+1;
    r.q.px.textContent=r.price.toFixed(2);r.q.dy.textContent=f2(r.pday,1)+'%';r.q.dy.className='dy '+cls(r.pday);
    r.q.bs.textContent=r.base.toFixed(0);const t=tilt(r);r.q.lv.textContent=(t>=0?'+':'')+t.toFixed(1);r.q.lv.className='lv '+cls(t);
    const w=Math.min(Math.abs(live),100)/2;r.q.bar.style.left=live>=0?'50%':(50-w)+'%';r.q.bar.style.width=w+'%';
    r.q.bar.style.background=live>=0?'#19d27a':'#ff6b6b';r.q.sc.textContent=(live>=0?'+':'')+live.toFixed(1);
    r.q.sig.textContent=sig(r);
    if(first){if(!initial)initial={};initial[r.y]=i;}
    const mv=initial&&initial[r.y]!==undefined?initial[r.y]-i:null;
    let m='';if(mv&&mv>0)m='<span class="mv up">▲'+mv+'</span>';else if(mv&&mv<0)m='<span class="mv dn">▼'+(-mv)+'</span>';
    if(!first&&!shown.has(r)){shown.add(r);r.q.tag.innerHTML='<span class="new">NEW</span>';
      r.e.animate([{backgroundColor:'#1d4d33'},{backgroundColor:'#111317'}],{duration:1600});}
    r.q.num.innerHTML=(i+1)+m;
  });
  for(const r of rows)if(!inTop.has(r)){r.e.classList.add('out');r.e.style.transform='translateY('+(N*RH+10)+'px)';shown.delete(r);r.q.tag.innerHTML='';}
  if(first)top.forEach(r=>shown.add(r));
  const orderNow=top.map(r=>r.y).join();if(order&&orderNow!==order){const c=document.getElementById('ch');c.innerHTML='ranking updated <b>'+new Date().toLocaleTimeString()+'</b>';}
  order=orderNow;
}
render(true);
function b64(s){const bin=atob(s),u=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);return u;}
function decode(u){const dv=new DataView(u.buffer);let p=0;const r={};
  const vi=()=>{let x=0,sh=0,b;do{b=u[p++];x+=(b&127)*Math.pow(2,sh);sh+=7;}while(b&128);return x;};
  while(p<u.length){const tag=vi(),f=tag>>3,w=tag&7;
    if(w===0)vi();else if(w===1)p+=8;
    else if(w===2){const n=vi();if(f===1)r.id=new TextDecoder().decode(u.subarray(p,p+n));p+=n;}
    else if(w===5){const v=dv.getFloat32(p,true);p+=4;if(f===2)r.price=v;else if(f===8)r.chg=v;else if(f===16)r.prev=v;}
    else break;}
  return r;}
const by={};rows.forEach(r=>by[r.y]=r);
const pending={};let ticks=0,recent=[],ws,retry=0;
function setSt(t,on){document.getElementById('st').textContent=t;document.getElementById('dot').className=on?'on':'';}
function connect(){
  ws=new WebSocket('wss://streamer.finance.yahoo.com/?version=2');
  ws.onopen=()=>{retry=0;setSt('LIVE · waiting for ticks',true);ws.send(JSON.stringify({subscribe:Object.keys(by)}));};
  ws.onmessage=ev=>{try{const m=JSON.parse(ev.data);if(m.type!=='pricing')return;const r=decode(b64(m.message));
    if(r.id&&by[r.id]&&r.price>0){pending[r.id]=r;ticks++;recent.push(Date.now());}}catch(e){}};
  ws.onclose=()=>{setSt('reconnecting…',false);setTimeout(connect,Math.min(15000,1000*(++retry)));};
  ws.onerror=()=>{try{ws.close();}catch(e){}};}
let lastRender=0;
function frame(now){
  const ks=Object.keys(pending);
  for(const k of ks){const t=pending[k],r=by[k];delete pending[k];
    if(t.prev>0)r.prev=t.prev;const old=r.price;r.price=t.price;
    r.pday=r.prev>0?(t.price/r.prev-1)*100:(t.chg!=null?t.chg:r.pday);r.ticks++;
    if(r.price!==old&&!r.e.classList.contains('out'))r.q.px.animate([{color:r.price>old?'#5dffa0':'#ff6b6b',fontWeight:700},{color:'#e8e8ea'}],{duration:900});}
  if(ks.length&&now-lastRender>400){lastRender=now;render(false);document.getElementById('tk').innerHTML='last tick <b>'+new Date().toLocaleTimeString()+'</b>';}
  const t=Date.now();recent=recent.filter(x=>t-x<10000);
  if(ws&&ws.readyState===1&&ticks>0)setSt('LIVE · '+recent.length+' ticks / 10s',true);
  requestAnimationFrame(frame);}
connect();requestAnimationFrame(frame);
</script></body></html>"""
