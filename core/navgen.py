"""生成可浏览的书签导航网页（单文件、离线可用、自带搜索与分类）。"""

from __future__ import annotations

import html
import json
import time
from typing import Iterable, List, Sequence

from .models import Bookmark

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --bg:#f7f7f5; --panel:#ffffff; --text:#2c2c2a; --muted:#5f5e5a; --faint:#888780;
  --line:rgba(0,0,0,.10); --line2:rgba(0,0,0,.06);
  --accent:#185fa5; --accent-soft:#e6f1fb;
  --ok:#3b6d11; --ok-bg:#eaf3de;
  --bad:#a32d2d; --bad-bg:#fcebeb;
  --warn:#854f0b; --warn-bg:#faeeda;
  --idle:#5f5e5a; --idle-bg:#f1efe8;
  --radius:10px;
}
html[data-theme="dark"]{
  --bg:#1c1c1a; --panel:#262624; --text:#f0efe9; --muted:#b4b2a9; --faint:#888780;
  --line:rgba(255,255,255,.12); --line2:rgba(255,255,255,.07);
  --accent:#85b7eb; --accent-soft:#12304d;
  --ok:#97c459; --ok-bg:#24350f;
  --bad:#f09595; --bad-bg:#4a1515;
  --warn:#ef9f27; --warn-bg:#412d08;
  --idle:#b4b2a9; --idle-bg:#33332f;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
  font-size:14px;line-height:1.6}
a{color:inherit;text-decoration:none}
button,input,select{font-family:inherit;font-size:13px;color:inherit}
.layout{display:grid;grid-template-columns:236px 1fr;min-height:100vh}

aside{background:var(--panel);border-right:1px solid var(--line);
  padding:18px 14px;position:sticky;top:0;height:100vh;overflow-y:auto}
.brand{display:flex;align-items:center;gap:9px;margin-bottom:16px}
.logo{width:26px;height:26px;border-radius:7px;background:var(--accent-soft);
  color:var(--accent);display:flex;align-items:center;justify-content:center;
  font-weight:600;font-size:13px;flex:none}
.brand h1{font-size:15px;font-weight:500;margin:0;letter-spacing:.2px}
.brand small{display:block;color:var(--faint);font-size:11px;font-weight:400}

.side-title{font-size:11px;color:var(--faint);margin:18px 6px 8px;
  text-transform:uppercase;letter-spacing:.8px}
.cat{display:flex;align-items:center;gap:8px;padding:6px 9px;border-radius:8px;
  cursor:pointer;color:var(--muted)}
.cat:hover{background:var(--line2);color:var(--text)}
.cat.on{background:var(--accent-soft);color:var(--accent);font-weight:500}
.cat span{margin-left:auto;font-size:11px;color:var(--faint)}
.cat.on span{color:var(--accent)}

main{padding:20px 26px 60px;min-width:0}
.topbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:16px}
#q{flex:1;min-width:200px;background:var(--panel);border:1px solid var(--line);
  border-radius:8px;padding:9px 12px;outline:none}
#q:focus{border-color:var(--accent)}
select,.btn{background:var(--panel);border:1px solid var(--line);
  border-radius:8px;padding:9px 11px;cursor:pointer}
.btn:hover,.select:hover{border-color:var(--faint)}
.stats{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);font-size:12px;
  margin-bottom:18px}
.stats b{color:var(--text);font-weight:500;font-size:13px}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));gap:10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  padding:11px 13px;display:flex;gap:10px;align-items:flex-start;
  transition:border-color .12s,transform .12s}
.card:hover{border-color:var(--accent);transform:translateY(-1px)}
.fav{width:26px;height:26px;border-radius:6px;flex:none;
  background:var(--line2) center/16px 16px no-repeat;
  display:flex;align-items:center;justify-content:center;
  font-size:11px;font-weight:600;color:var(--muted);overflow:hidden}
.meta{min-width:0;flex:1}
.t{font-size:13.5px;font-weight:500;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.u{font-size:11.5px;color:var(--faint);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;margin-top:1px}
.tags{display:flex;gap:5px;margin-top:6px;flex-wrap:wrap}
.tag{font-size:10.5px;padding:1px 6px;border-radius:5px;background:var(--line2);
  color:var(--muted)}
.tag.st-ok{background:var(--ok-bg);color:var(--ok)}
.tag.st-bad{background:var(--bad-bg);color:var(--bad)}
.tag.st-warn{background:var(--warn-bg);color:var(--warn)}
.tag.st-info{background:var(--accent-soft);color:var(--accent)}
.tag.st-idle{background:var(--idle-bg);color:var(--idle)}

.list .card{border-radius:8px;padding:8px 11px}
.empty{color:var(--faint);text-align:center;padding:70px 0}
footer{color:var(--faint);font-size:11.5px;text-align:center;padding:26px 0 0}
@media(max-width:820px){.layout{grid-template-columns:1fr}
  aside{position:static;height:auto;border-right:none;border-bottom:1px solid var(--line)}}
</style>
</head>
<body>
<div class="layout">
<aside>
  <div class="brand">
    <div class="logo">BM</div>
    <div><h1>__TITLE__</h1><small>__SUBTITLE__</small></div>
  </div>
  <div class="side-title">分类</div>
  <div id="cats"></div>
  <div class="side-title">筛选</div>
  <div id="status-filter"></div>
</aside>
<main>
  <div class="topbar">
    <input id="q" placeholder="搜索标题、网址或文件夹…" autocomplete="off">
    <select id="sort">
      <option value="default">默认排序</option>
      <option value="domain">按域名</option>
      <option value="status">按状态</option>
      <option value="title">按标题</option>
    </select>
    <select id="view">
      <option value="grid">卡片</option>
      <option value="list">列表</option>
    </select>
    <button class="btn" id="theme">深色</button>
  </div>
  <div class="stats" id="stats"></div>
  <div class="grid" id="grid"></div>
  <footer>本地书签导航 · 共 __COUNT__ 条 · 生成于 __DATE__</footer>
</main>
</div>

<script type="application/json" id="data">__DATA__</script>
<script>
(function(){
  var DATA = JSON.parse(document.getElementById('data').textContent);
  var STATE = {cat:'__all__', status:'__all__', q:'', sort:'default', dead:false};

  var ST_CLASS = {'可访问':'st-ok','已失效':'st-bad',
    '存疑':'st-warn','跳过':'st-idle','未检测':'st-idle'};

  function esc(s){return (s==null?'':String(s)).replace(/[&<>"']/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}

  var counts={}, statusCounts={};
  DATA.forEach(function(b){
    var c=b.cat||'未分类'; counts[c]=(counts[c]||0)+1;
    var s=b.status||'未检测'; statusCounts[s]=(statusCounts[s]||0)+1;
  });
  var catNames=Object.keys(counts).sort(function(a,b){return counts[b]-counts[a];});
  var stNames=Object.keys(statusCounts).sort(function(a,b){
    return statusCounts[b]-statusCounts[a];});

  function renderCats(){
    var h='<div class="cat'+(STATE.cat==='__all__'?' on':'')+'" data-c="__all__">'
      +'全部书签<span>'+DATA.length+'</span></div>';
    catNames.forEach(function(c){
      h+='<div class="cat'+(STATE.cat===c?' on':'')+'" data-c="'+esc(c)+'">'
        +esc(c)+'<span>'+counts[c]+'</span></div>';
    });
    document.getElementById('cats').innerHTML=h;
    var s='';
    stNames.forEach(function(k){
      s+='<div class="cat'+(STATE.status===k?' on':'')+'" data-s="'+esc(k)+'">'
        +esc(k)+'<span>'+statusCounts[k]+'</span></div>';
    });
    if(stNames.length) s+='<div class="cat'+(STATE.status==='__all__'?' on':'')
      +'" data-s="__all__">不限状态<span>'+DATA.length+'</span></div>';
    document.getElementById('status-filter').innerHTML=s;
    bindCats();
  }

  function bindCats(){
    var cs=document.getElementById('cats').querySelectorAll('.cat');
    for(var i=0;i<cs.length;i++) cs[i].onclick=function(){
      STATE.cat=this.getAttribute('data-c'); renderCats(); render();};
    var ss=document.getElementById('status-filter').querySelectorAll('.cat');
    for(var j=0;j<ss.length;j++) ss[j].onclick=function(){
      STATE.status=this.getAttribute('data-s'); renderCats(); render();};
  }

  function match(b){
    if(STATE.cat!=='__all__' && (b.cat||'未分类')!==STATE.cat) return false;
    if(STATE.status!=='__all__' && (b.status||'未检测')!==STATE.status) return false;
    if(STATE.dead && !(b.status==='已失效'||b.status==='无法连接')) return false;
    if(STATE.q){
      var q=STATE.q.toLowerCase();
      var hay=((b.title||'')+' '+(b.url||'')+' '+(b.folder||'')+' '+(b.cat||'')).toLowerCase();
      if(hay.indexOf(q)<0) return false;
    }
    return true;
  }

  function sortList(arr){
    var a=arr.slice();
    if(STATE.sort==='domain') a.sort(function(x,y){
      return (x.domain||'').localeCompare(y.domain||'');});
    else if(STATE.sort==='title') a.sort(function(x,y){
      return (x.title||'').localeCompare(y.title||'','zh');});
    else if(STATE.sort==='status') a.sort(function(x,y){
      return (x.status||'').localeCompare(y.status||'','zh');});
    return a;
  }

  function loadFavs(){
    var els=document.getElementById('grid').querySelectorAll('.fav');
    for(var i=0;i<els.length;i++){(function(el){
      var src=el.getAttribute('data-fav'); if(!src) return;
      var img=new Image();
      img.onload=function(){
        el.textContent=''; el.style.backgroundImage='url("'+src+'")';
        el.style.backgroundSize='16px 16px';};
      img.src=src;
    })(els[i]);}
  }

  function render(){
    var arr=DATA.filter(match); arr=sortList(arr);
    var h='';
    for(var i=0;i<arr.length;i++){
      var b=arr[i];
      var cls=ST_CLASS[b.status]||'st-idle';
      var letter=((b.title||b.domain||'?').trim()[0]||'?').toUpperCase();
      var sub=(b.subtype)?esc(b.subtype):'';
      h+='<a class="card" href="'+esc(b.url)+'" target="_blank" rel="noopener">'
        +'<span class="fav" data-fav="https://'+esc(b.domain)+'/favicon.ico">'
        +esc(letter)+'</span>'
        +'<div class="meta"><div class="t" title="'+esc(b.title)+'">'+esc(b.title)+'</div>'
        +'<div class="u" title="'+esc(b.url)+'">'+esc(b.url)+'</div>'
        +'<div class="tags"><span class="tag st-idle">'+esc(b.cat||'未分类')+'</span>'
        +(b.status&&b.status!=='未检测'?'<span class="tag '+cls+'">'+esc(b.status)
          +(sub?' · '+sub:'')+'</span>':'')
        +(b.folder?'<span class="tag">'+esc(b.folder)+'</span>':'')
        +(b.dup?'<span class="tag st-warn">重复</span>':'')
        +'</div></div></a>';
    }
    document.getElementById('grid').innerHTML=h||'<div class="empty">没有匹配的书签</div>';
    loadFavs();
    document.getElementById('stats').innerHTML=
      '<div>当前显示 <b>'+arr.length+'</b> 条</div>'
      +'<div>总计 <b>'+DATA.length+'</b> 条</div>'
      +'<div>分类 <b>'+catNames.length+'</b> 个</div>'
      +'<div>存疑 <b>'+(statusCounts['存疑']||0)+'</b> 条</div>'
      +'<div>失效 <b>'+(statusCounts['已失效']||0)+'</b> 条</div>';
  }

  document.getElementById('q').addEventListener('input',function(e){
    STATE.q=e.target.value.trim(); render();});
  document.getElementById('sort').addEventListener('change',function(e){
    STATE.sort=e.target.value; render();});
  document.getElementById('view').addEventListener('change',function(e){
    document.getElementById('grid').className=e.target.value==='list'?'list':'grid';});
  document.getElementById('theme').addEventListener('click',function(){
    var d=document.documentElement;
    var next=d.getAttribute('data-theme')==='dark'?'light':'dark';
    d.setAttribute('data-theme',next);
    this.textContent=next==='dark'?'浅色':'深色';
    try{localStorage.setItem('bm-theme',next);}catch(err){}
  });
  try{var t=localStorage.getItem('bm-theme');
    if(t){document.documentElement.setAttribute('data-theme',t);
      document.getElementById('theme').textContent=t==='dark'?'浅色':'深色';}}catch(err){}

  renderCats(); render();
})();
</script>
</body>
</html>
"""


def build_payload(bookmarks: Iterable[Bookmark], include_dropped: bool = False) -> List[dict]:
    out = []
    for bm in bookmarks:
        if not include_dropped and not bm.keep:
            continue
        out.append({
            "title": bm.title or bm.url,
            "url": bm.url,
            "domain": bm.domain,
            "cat": bm.category or "未分类",
            "folder": bm.folder,
            "status": bm.effective_verdict,
            "subtype": bm.effective_subtype,
            "dup": (not bm.is_primary) if bm.dup_group >= 0 else False,
        })
    return out


def generate_nav(
    bookmarks: Sequence[Bookmark],
    out_path: str,
    title: str = "我的书签导航",
    include_dropped: bool = False,
) -> int:
    payload = build_payload(bookmarks, include_dropped=include_dropped)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")
    html_out = (TEMPLATE
                .replace("__DATA__", data)
                .replace("__TITLE__", html.escape(title))
                .replace("__SUBTITLE__", f"{len(payload)} 条书签")
                .replace("__COUNT__", str(len(payload)))
                .replace("__DATE__", time.strftime("%Y-%m-%d %H:%M")))
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html_out)
    return len(payload)
