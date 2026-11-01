"""Browser-side live ticker tape.

Streamlit re-renders on every refresh, so a Python-only page can only "tick" once per poll. This tape runs in
the browser instead, as a self-contained HTML component, so it keeps moving between polls without a page refresh:

* It scrolls continuously. The scroll position comes from the wall clock, not from page state, so when
  Streamlit swaps in fresh data the tape carries on from the same spot instead of restarting.
* When a price changes, the number rolls smoothly from its previous value (remembered in localStorage) to the
  new one and flashes green or red.
* Bitcoin additionally ticks in real time from Binance's public trade stream (BTCUSDT, a few updates a second).
  Nothing is simulated: every other price changes only when the data source reports a new value.
"""

from __future__ import annotations

import html as _html
import json
import math

from . import theme as T

C = T.C

_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:%(bg)s;font-family:ui-monospace,'JetBrains Mono','SF Mono',Menlo,Consolas,monospace}
.wrap{position:relative;overflow:hidden;white-space:nowrap;border:1px solid %(line)s;border-radius:3px;
background:%(panel)s;height:40px}
.track{display:inline-block;will-change:transform;line-height:40px}
.it{display:inline-block;padding:0 1.15rem;border-right:1px solid %(line)s;font-size:12px}
.n{color:%(faint)s;letter-spacing:.12em;font-size:10px;font-weight:700;margin-right:.55rem;text-transform:uppercase}
.p{color:%(text)s;font-weight:700;font-variant-numeric:tabular-nums;padding:2px 3px;border-radius:2px}
.c{margin-left:.45rem;font-weight:700;font-variant-numeric:tabular-nums}
.up{color:%(up)s}.dn{color:%(down)s}.fl{color:%(dim)s}
.d{display:inline-block;width:5px;height:5px;border-radius:50%%;background:%(up)s;margin-left:.45rem;vertical-align:middle}
.fu{animation:fu .9s ease-out}.fd{animation:fd .9s ease-out}
@keyframes fu{0%%{background:rgba(14,203,129,.40)}100%%{background:transparent}}
@keyframes fd{0%%{background:rgba(246,70,93,.40)}100%%{background:transparent}}
.tag{position:absolute;left:0;top:0;bottom:0;z-index:2;display:flex;align-items:center;gap:.45rem;padding:0 .8rem;
background:%(panel)s;border-right:1px solid %(line)s;color:%(up)s;font-size:10px;font-weight:700;letter-spacing:.14em}
.tag i{width:7px;height:7px;border-radius:50%%;background:%(up)s;animation:pl 1.4s ease-out infinite}
@keyframes pl{0%%{box-shadow:0 0 0 0 rgba(14,203,129,.6)}100%%{box-shadow:0 0 0 7px rgba(14,203,129,0)}}
@media (prefers-reduced-motion:reduce){.wrap{overflow-x:auto}.fu,.fd,.tag i{animation:none}}
</style></head><body><div class="wrap"><div class="tag"><i></i>LIVE</div><div class="track" id="t"></div></div>
<script>
(function(){
var D=%(data)s, SPEED=42, BTC="BTC-USD";
var reduce=window.matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches;
var track=document.getElementById("t");
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function fmt(v,dp){return Number(v).toLocaleString("en-US",{minimumFractionDigits:dp,maximumFractionDigits:dp})}
function mvTxt(m,u){if(m==null||isNaN(m))return "n/a";var b=u==="bps";return (m>=0?"+":"")+m.toFixed(b?1:2)+(b?" bps":"%%")}
function tone(m){return m==null||isNaN(m)||m===0?"fl":(m>0?"up":"dn")}
function arrow(m){return m==null||isNaN(m)||m===0?"\\u2022":(m>0?"\\u25B2":"\\u25BC")}
function cell(it){
  return '<span class="it" data-s="'+esc(it.s)+'"><span class="n">'+esc(it.l)+'</span><span class="p">'+fmt(it.p,it.dp)+
    '</span><span class="c '+tone(it.m)+'">'+arrow(it.m)+" "+mvTxt(it.m,it.u)+"</span>"+(it.live?'<i class="d"></i>':"")+"</span>";
}
var one=D.map(cell).join(""); track.innerHTML=one+one;   // two copies = seamless loop
function els(sym){return track.querySelectorAll('[data-s="'+sym.replace(/"/g,'\\\\"')+'"]')}
function flash(el,up){el.classList.remove("fu","fd");void el.offsetWidth;el.classList.add(up?"fu":"fd")}
var byS={};D.forEach(function(it){byS[it.s]=it});
function paint(sym,price,doFlash,prevPrice){
  var it=byS[sym]; if(!it)return;
  var m=it.m; if(it.k!=="yield"&&it.pv){m=(price/it.pv-1)*100}
  els(sym).forEach(function(e){
    var p=e.querySelector(".p"),c=e.querySelector(".c");
    p.textContent=fmt(price,it.dp);
    c.className="c "+tone(m); c.textContent=arrow(m)+" "+mvTxt(m,it.u);
    if(doFlash&&prevPrice!=null&&price!==prevPrice)flash(p,price>prevPrice);
  });
}
// 1) roll from the previous poll's price to the new one
var store={}; try{store=JSON.parse(localStorage.getItem("tape_prev")||"{}")}catch(e){}
var now={};
D.forEach(function(it){
  now[it.s]=it.p; var from=store[it.s];
  if(from==null||from===it.p||reduce)return;
  var t0=performance.now(), dur=900;
  (function step(t){
    var k=Math.min(1,(t-t0)/dur), v=from+(it.p-from)*(1-Math.pow(1-k,3));
    paint(it.s,v,false); if(k<1)requestAnimationFrame(step); else{paint(it.s,it.p,true,from)}
  })(t0);
});
try{localStorage.setItem("tape_prev",JSON.stringify(Object.assign(store,now)))}catch(e){}
// 2) continuous scroll from the wall clock (survives data refreshes)
if(!reduce){
  var W=0;
  (function frame(){
    if(!W)W=track.scrollWidth/2;
    if(W>0){track.style.transform="translateX("+(-((Date.now()/1000*SPEED)%%W))+"px)"}
    requestAnimationFrame(frame);
  })();
}
// 3) Bitcoin streams real trades between polls
if(byS[BTC]){
  (function connect(){
    try{
      var w=new WebSocket("wss://stream.binance.com:9443/ws/btcusdt@trade"),last=0,prev=byS[BTC].p;
      w.onmessage=function(ev){
        var t=performance.now(); if(t-last<300)return; last=t;
        var p=parseFloat(JSON.parse(ev.data).p); if(!(p>0))return;
        paint(BTC,p,true,prev); prev=p;
      };
      w.onclose=function(){setTimeout(connect,4000)}; w.onerror=function(){try{w.close()}catch(e){}};
    }catch(e){}
  })();
}
})();
</script></body></html>"""


# Yahoo symbol -> Binance spot trade stream. These are the only instruments with a public browser-readable
# real-time feed; Yahoo itself blocks cross-origin browser requests, so everything else updates per poll.
BINANCE_STREAMS = {"BTC-USD": "btcusdt", "ETH-USD": "ethusdt", "SOL-USD": "solusdt",
                   "BNB-USD": "bnbusdt", "XRP-USD": "xrpusdt"}

_DRIVER = """<!doctype html><html><body style="margin:0"><script>
(function(){
var MAP=%(map)s, UP="%(up)s", DN="%(down)s", DIM="%(dim)s";
var P; try{P=window.parent.document}catch(e){return}          // cards live in the page; update them in place
var reduce=window.matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches;
var state={}, bySream={}, scheduled=false;
Object.keys(MAP).forEach(function(s){bySream[MAP[s]+"@trade"]=s});
function fmt(v,dp){return Number(v).toLocaleString("en-US",{minimumFractionDigits:dp,maximumFractionDigits:dp})}
function sgn(v,dp){return (v>=0?"+":"-")+Math.abs(v).toLocaleString("en-US",{minimumFractionDigits:dp,maximumFractionDigits:dp})}
function pts(a){var lo=Math.min.apply(null,a),hi=Math.max.apply(null,a),sp=(hi-lo)||1;
  return a.map(function(v,i){return (i*120/(a.length-1)).toFixed(1)+","+(28-(v-lo)/sp*26).toFixed(1)}).join(" ")}
function card(sym){return P.querySelector('.lm-card[data-sym="'+sym+'"]')}
function apply(sym,flash,from){
  var c=card(sym),s=state[sym]; if(!c||!s)return;
  var prev=parseFloat(c.getAttribute("data-prev")),dp=parseInt(c.getAttribute("data-dp")||"2",10);
  var m=prev>0?(s.p/prev-1)*100:null, col=m==null||m===0?DIM:(m>0?UP:DN);
  var px=c.querySelector(".lm-px"),chg=c.querySelector(".lm-chg"),st=c.querySelector(".lm-st"),poly=c.querySelector(".lm-spark polyline");
  if(px)px.textContent=fmt(s.p,dp);
  if(chg&&m!=null){chg.textContent=(m>0?"\u25B2 ":m<0?"\u25BC ":"\u2022 ")+sgn(s.p-prev,dp)+" ("+sgn(m,2)+"%%)";chg.style.color=col}
  c.classList.remove("up","down"); if(m!=null&&m!==0)c.classList.add(m>0?"up":"down");
  if(st){st.className="lm-st live";st.textContent="\u25CF STREAMING"}
  if(poly&&s.series.length>1){poly.setAttribute("points",pts(s.series));poly.setAttribute("stroke",col)}
  c.setAttribute("data-live","1");
  if(flash&&!reduce&&from!=null&&s.p!==from){c.classList.remove("flash-up","flash-down");void c.offsetWidth;c.classList.add(s.p>from?"flash-up":"flash-down")}
}
function seed(sym){
  var c=card(sym); if(!c||state[sym].series.length)return;
  try{state[sym].series=JSON.parse(c.getAttribute("data-spark")||"[]")}catch(e){}
}
function onTrade(sym,p){
  var s=state[sym]||(state[sym]={p:p,series:[],t:0}); var from=s.p; s.p=p; seed(sym);
  var now=Date.now(); if(now-s.t>2500){s.t=now;s.series.push(p);if(s.series.length>60)s.series.shift()}
  else if(s.series.length){s.series[s.series.length-1]=p}
  apply(sym,true,from);
}
// cards are rebuilt on every Streamlit poll: re-apply the streamed state to any fresh card
new MutationObserver(function(){
  if(scheduled)return; scheduled=true;
  requestAnimationFrame(function(){scheduled=false;
    P.querySelectorAll('.lm-card[data-sym]').forEach(function(c){
      var sym=c.getAttribute("data-sym"); if(state[sym]&&c.getAttribute("data-live")!=="1"){seed(sym);apply(sym,false)}})})
}).observe(P.body,{childList:true,subtree:true});
(function connect(){
  try{
    var q=Object.keys(MAP).map(function(s){return MAP[s]+"@trade"}).join("/");
    var w=new WebSocket("wss://stream.binance.com:9443/stream?streams="+q), last={};
    w.onmessage=function(ev){
      var m=JSON.parse(ev.data),sym=bySream[m.stream]; if(!sym)return;
      var t=performance.now(); if(last[sym]&&t-last[sym]<250)return; last[sym]=t;
      var p=parseFloat(m.data.p); if(p>0)onTrade(sym,p);
    };
    w.onclose=function(){setTimeout(connect,4000)}; w.onerror=function(){try{w.close()}catch(e){}};
  }catch(e){}
})();
})();
</script></body></html>"""


def tile_driver_html() -> str:
    """Static (data-free) HTML for a zero-height component that streams live trades into the Live Markets cards.

    It carries no per-poll data, so the HTML never changes and Streamlit keeps the same iframe (and socket) alive
    across refreshes."""
    return _DRIVER % {"map": json.dumps(BINANCE_STREAMS), "up": C["up"], "down": C["down"], "dim": C["dim"]}


def render_tile_driver() -> None:
    import streamlit.components.v1 as components

    components.html(tile_driver_html(), height=0)


def _clean(v):
    """JSON-safe number: NaN/inf become null."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def items_from_rows(rows: list[dict]) -> list[dict]:
    """Compact per-instrument records for the tape from livemarkets snapshot rows."""
    out = []
    for r in rows:
        p = _clean(r.get("price"))
        if p is None:
            continue
        out.append({"s": str(r["symbol"]), "l": str(r["label"]), "p": p, "pv": _clean(r.get("prev")),
                    "m": _clean(r.get("move")), "u": str(r.get("unit", "%")), "dp": int(r.get("dp", 2)),
                    "k": str(r.get("kind", "price")), "live": bool(r.get("live"))})
    return out


def build_html(rows: list[dict]) -> str:
    """Self-contained HTML for ``st.components.v1.html(..., height=44)``."""
    data = json.dumps(items_from_rows(rows), allow_nan=False).replace("</", "<\\/")
    return _TEMPLATE % {**{k: C[k] for k in ("bg", "panel", "line", "text", "dim", "faint", "up", "down")},
                        "data": data}


def render(rows: list[dict]) -> None:
    """Render the tape (no-op when there is nothing to show)."""
    import streamlit.components.v1 as components

    if not rows:
        return
    components.html(build_html(rows), height=44)


__all__ = ["build_html", "items_from_rows", "render", "render_tile_driver", "tile_driver_html", "_html"]
