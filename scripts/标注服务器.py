# -*- coding: utf-8 -*-
"""本地标注网页 v2（给 YOLO 训练用）

新增：撤销、最近 10 个标签、按类自动配色、手写备注、缩放/平移

启动：python 标注服务器.py
打开：http://127.0.0.1:5055
"""
import json
import os
import sys
import urllib.parse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = r"D:\大肥鱼专用\数据集\战雷帧"
PORT = 5055
CLASSES_FILE = r"D:\大肥鱼专用\数据集\classes.json"
DEFAULT_CLASSES = ["敌机", "友机", "自身", "文字块", "导弹", "雷达", "RWR告警", "地面目标",
                   "代码块", "参数表", "字幕", "幻灯片"]


def load_classes():
    if os.path.isfile(CLASSES_FILE):
        try:
            d = json.load(open(CLASSES_FILE, encoding="utf-8"))
            if isinstance(d, list) and d:
                return d
        except Exception:
            pass
    return list(DEFAULT_CLASSES)


def save_classes(lst):
    os.makedirs(os.path.dirname(CLASSES_FILE), exist_ok=True)
    json.dump(lst, open(CLASSES_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


CLASSES = load_classes()

HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>标记</title>
<style>
 html,body{margin:0;height:100%;background:#101214;color:#dde;font-family:system-ui,sans-serif;overflow:hidden}
 #app{display:flex;height:100%}
 #side{width:210px;overflow:auto;border-right:1px solid #2a2f35;flex-shrink:0}
 #side div{padding:3px 8px;font-size:12px;cursor:pointer;white-space:nowrap;overflow:hidden}
 #side div:hover{background:#1d2126} #side div.on{background:#1f6f43;color:#fff}
 #main{flex:1;display:flex;flex-direction:column;min-width:0}
 #top{padding:6px;background:#171b1f;display:flex;gap:6px;align-items:center;flex-wrap:wrap;font-size:13px}
 #clsbar{padding:4px 6px;background:#14181c;display:flex;gap:5px;flex-wrap:wrap}
 .chip{padding:2px 8px;border:1px solid #333;border-radius:10px;cursor:pointer;font-size:12px;user-select:none}
 .chip.on{outline:2px solid #4ea; color:#fff}
 .chip.recent{border-color:#5a4}
 #wrap{flex:1;position:relative;overflow:hidden;background:#0b0d0f}
 #cv{position:absolute;left:0;top:0;cursor:crosshair}
 #foot{padding:4px 8px;background:#14181c;font-size:12px;color:#8a94a0;display:flex;gap:12px;flex-wrap:wrap}
 button{background:#242a30;color:#dde;border:1px solid #3a424b;padding:4px 10px;border-radius:5px;cursor:pointer}
 button:hover{background:#2f373f}
 input[type=text]{background:#0f1316;color:#dde;border:1px solid #3a424b;border-radius:4px;padding:3px 6px;font-size:12px}
 #msg{color:#6c6}
</style></head><body><div id="app">
<div id="side"></div>
<div id="main">
 <div id="top">
  <span id="fname">-</span><span id="cc" style="color:#8a94a0"></span>
  <button onclick="prev()">← 上一张</button>
  <button onclick="next()">下一张 →</button>
  <button onclick="save()">保存(S)</button>
  <button onclick="undo()">撤销(Z)</button>
  <button onclick="autoText()">自动预标文字(O)</button>
  <button onclick="clearAll()">清空</button>
  <span>备注：</span><input id="note" type="text" placeholder="选中框后可写" style="width:150px" oninput="setNote(this.value)">
  <span>新类别：</span><input id="newcls" type="text" placeholder="如 桌面图标" style="width:110px"><button onclick="addCls()">加类</button>
  <span id="msg"></span>
 </div>
 <div id="clsbar"></div>
 <div id="wrap"><canvas id="cv"></canvas></div>
 <div id="foot">
  <span>拖拽画框</span><span>滚轮缩放</span><span>WASD/方向键 平移(Shift 加速)</span>
  <span>1-9 选类</span><span>0 第10类</span><span>Q/E 翻页</span>
  <span>Enter 保存</span><span>Del 删</span><span>Z 撤销</span><span>O 自动预标</span><span id="zoom"></span>
 </div>
</div></div>
<script>
let CLASSES = __CLASSES__;
const COLORS = ['#ff4d4d','#4dff88','#ffd24d','#35c8ff','#ff7bf0','#7bfff0','#ffa640','#c8c8c8','#9d7bff','#7bff9d','#ff6b9d','#c0ff4d'];
let frames=[], cur=-1, img=new Image(), boxes=[], cls=0, sel=-1;
let zoom=1, ox=0, oy=0, dragging=null, panning=null, undoStack=[], recent=[];
const cv=document.getElementById('cv'), ctx=cv.getContext('2d'), wrap=document.getElementById('wrap');

function fit(){
  const pad=20, w=wrap.clientWidth-pad, h=wrap.clientHeight-pad;
  zoom=Math.min(w/img.width,h/img.height,1); ox=(wrap.clientWidth-img.width*zoom)/2; oy=(wrap.clientHeight-img.height*zoom)/2;
}
function redraw(){
  cv.width=wrap.clientWidth; cv.height=wrap.clientHeight;
  ctx.setTransform(1,0,0,1,0,0); ctx.clearRect(0,0,cv.width,cv.height);
  ctx.setTransform(zoom,0,0,zoom,ox,oy);
  if(img.complete) ctx.drawImage(img,0,0);
  boxes.forEach((b,i)=>{
    ctx.lineWidth=(i===sel? 3:2)/zoom; ctx.strokeStyle=COLORS[b.c]||'#fff';
    ctx.strokeRect(b.x,b.y,b.w,b.h);
    ctx.fillStyle=COLORS[b.c]||'#fff'; ctx.font=(14/zoom)+'px sans-serif';
    const tag=(b.c+1)+'.'+CLASSES[b.c]+(b.note?('｜'+b.note):'');
    ctx.fillText(tag,b.x+2/zoom,b.y-4/zoom);
  });
  if(dragging){ctx.strokeStyle='#0f0';ctx.lineWidth=2/zoom;ctx.strokeRect(dragging.x,dragging.y,dragging.w,dragging.h);}
  document.getElementById('cc').textContent='共 '+boxes.length+' 框';
  document.getElementById('zoom').textContent='缩放 '+(zoom*100).toFixed(0)+'%';
}
function clsbar(){
  const bar=document.getElementById('clsbar'); bar.innerHTML='';
  CLASSES.forEach((c,i)=>{
    const s=document.createElement('span'); s.className='chip'+(i===cls?' on':''); s.textContent=(i+1)+'.'+c;
    s.style.color=COLORS[i]; s.onclick=()=>{setCls(i)};
    bar.appendChild(s);
  });
  if(recent.length){
    const sep=document.createElement('span'); sep.textContent='｜最近：'; sep.style.color='#667'; bar.appendChild(sep);
    recent.forEach(i=>{
      const s=document.createElement('span'); s.className='chip recent'; s.textContent=CLASSES[i]; s.style.color=COLORS[i];
      s.onclick=()=>{setCls(i)}; bar.appendChild(s);
    });
  }
}
function setCls(i){cls=i; recent=[i].concat(recent.filter(x=>x!==i)).slice(0,10); clsbar();}
function pushUndo(){undoStack.push(JSON.stringify(boxes)); if(undoStack.length>100)undoStack.shift();}
function undo(){if(!undoStack.length)return; boxes=JSON.parse(undoStack.pop()); sel=-1; redraw(); msg('已撤销');}
function msg(t){const m=document.getElementById('msg');m.textContent=t;setTimeout(()=>m.textContent='',1500);}

async function load(){
  frames=await (await fetch('/api/frames')).json();
  const s=document.getElementById('side'); s.innerHTML='';
  frames.forEach((f,i)=>{const d=document.createElement('div');d.textContent=f.rel;d.onclick=()=>goto(i);s.appendChild(d);});
  if(frames.length) goto(0);
}
function goto(i){
  if(i<0||i>=frames.length)return; cur=i;
  [...document.querySelectorAll('#side div')].forEach((d,k)=>d.classList.toggle('on',k===i));
  img=new Image();
  img.onload=()=>{
    fit(); redraw();
    document.getElementById('fname').textContent=frames[i].rel;
    fetch('/api/labels?img='+encodeURIComponent(frames[i].rel)).then(r=>r.json()).then(d=>{
      boxes=d.boxes||[]; undoStack=[]; sel=-1; redraw();
    });
  };
  img.src='/img?p='+encodeURIComponent(frames[i].rel);
}
function toImg(ev){
  const r=cv.getBoundingClientRect();
  return {x:(ev.clientX-r.left-ox)/zoom, y:(ev.clientY-r.top-oy)/zoom};
}
cv.addEventListener('contextmenu',e=>e.preventDefault());
cv.addEventListener('mousedown',e=>{
  if(e.button===2||e.shiftKey){panning={x:e.clientX,y:e.clientY,ox,oy};return;}
  if(e.button!==0)return;
  const p=toImg(e);
  sel=boxes.findIndex(b=>p.x>=b.x&&p.x<=b.x+b.w&&p.y>=b.y&&p.y<=b.y+b.h);
  if(sel>=0){document.getElementById('note').value=boxes[sel].note||'';}
  dragging={x:p.x,y:p.y,w:0,h:0}; redraw();
});
cv.addEventListener('mousemove',e=>{
  if(panning){ox=panning.ox+(e.clientX-panning.x);oy=panning.oy+(e.clientY-panning.y);redraw();return;}
  if(!dragging)return;
  const p=toImg(e); dragging.w=p.x-dragging.x; dragging.h=p.y-dragging.y; redraw();
});
window.addEventListener('mouseup',e=>{
  if(panning){panning=null;return;}
  if(!dragging)return;
  if(Math.abs(dragging.w)>6&&Math.abs(dragging.h)>6){
    pushUndo();
    boxes.push({c:cls,x:Math.min(dragging.x,dragging.x+dragging.w),y:Math.min(dragging.y,dragging.y+dragging.h),
                w:Math.abs(dragging.w),h:Math.abs(dragging.h),note:''});
  }
  dragging=null; redraw();
});
cv.addEventListener('wheel',e=>{
  e.preventDefault();
  const r=cv.getBoundingClientRect(), mx=e.clientX-r.left, my=e.clientY-r.top;
  const before={x:(mx-ox)/zoom,y:(my-oy)/zoom};
  zoom=Math.max(0.15,Math.min(8,zoom*(e.deltaY<0?1.15:0.87)));
  ox=mx-before.x*zoom; oy=my-before.y*zoom; redraw();
},{passive:false});

function setNote(v){if(sel>=0){boxes[sel].note=v; redraw();}}
async function save(){
  const rel=frames[cur].rel;
  await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({img:rel,boxes})});
  msg('已保存'); next();
}
async function autoText(){
  msg('预标中…');
  const d=await (await fetch('/api/auto?img='+encodeURIComponent(frames[cur].rel))).json();
  pushUndo(); boxes=boxes.concat((d.boxes||[]).map(b=>({...b,note:''})));
  redraw(); msg('预标 '+((d.boxes||[]).length)+' 个');
}
function clearAll(){pushUndo();boxes=[];sel=-1;redraw();}
function next(){goto(cur+1);} function prev(){goto(cur-1);}
function pan(dx,dy){ox+=dx;oy+=dy;redraw();}
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT')return;
  const k=e.key;
  const step=e.shiftKey?200:60;
  if(k==='w'||k==='W'||k==='ArrowUp'){pan(0,step);e.preventDefault();}
  else if(k==='s'||k==='S'||k==='ArrowDown'){pan(0,-step);e.preventDefault();}
  else if(k==='a'||k==='A'||k==='ArrowLeft'){pan(step,0);e.preventDefault();}
  else if(k==='d'||k==='D'||k==='ArrowRight'){pan(-step,0);e.preventDefault();}
  else if(k==='Enter'){save();}
  else if(k==='z'||k==='Z'){undo();}
  else if(k==='q'||k==='Q'){prev();}
  else if(k==='e'||k==='E'){next();}
  else if(k==='o'||k==='O'){autoText();}
  else if(k==='Delete'||k==='Backspace'){if(sel>=0){pushUndo();boxes.splice(sel,1);sel=-1;redraw();}}
  else if(/^[1-9]$/.test(k))setCls(parseInt(k)-1);
  else if(k==='0')setCls(9);
});
window.addEventListener('resize',()=>{redraw();});
async function pullClasses(){
  try { CLASSES = await (await fetch('/api/classes')).json(); } catch(e) {}
  clsbar();
}
function addCls(){
  const el=document.getElementById('newcls'); const v=(el.value||'').trim();
  if(!v) return;
  fetch('/api/classes',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:v})}).then(r=>r.json()).then(cs=>{
      CLASSES=cs; el.value=''; clsbar(); msg('已加类：'+v);
    });
}
pullClasses(); load();
</script></body></html>"""


class Handler(SimpleHTTPRequestHandler):
    def _send(self, obj, code=200, ctype="application/json; charset=utf-8"):
        data = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            return self._send(HTML.replace("__CLASSES__", json.dumps(CLASSES, ensure_ascii=False)).encode("utf-8"),
                              200, "text/html; charset=utf-8")
        if u.path == "/api/classes":
            return self._send(CLASSES)
        if u.path == "/api/frames":
            out = []
            for dirpath, _, files in os.walk(ROOT):
                for fn in sorted(files):
                    if fn.lower().endswith((".jpg", ".png")):
                        out.append({"rel": os.path.relpath(os.path.join(dirpath, fn), ROOT).replace("\\", "/")})
            return self._send(out)
        if u.path == "/img":
            p = os.path.join(ROOT, q.get("p", [""])[0].replace("/", os.sep))
            if not os.path.isfile(p):
                return self._send(b"not found", 404)
            with open(p, "rb") as f:
                return self._send(f.read(), 200, "image/jpeg")
        if u.path == "/api/labels":
            rel = q.get("img", [""])[0]
            img_path = os.path.join(ROOT, rel.replace("/", os.sep))
            txt = img_path.rsplit(".", 1)[0] + ".txt"
            js = img_path.rsplit(".", 1)[0] + ".notes.json"
            notes = {}
            if os.path.isfile(js):
                try:
                    notes = json.load(open(js, encoding="utf-8"))
                except Exception:
                    notes = {}
            boxes = []
            if os.path.isfile(txt):
                try:
                    from PIL import Image
                    W, H = Image.open(img_path).size
                except Exception:
                    W = H = 1280
                with open(txt) as f:
                    for idx, line in enumerate(f):
                        v = line.split()
                        if len(v) == 5:
                            c = int(v[0]); cx, cy, w, h = [float(x) for x in v[1:]]
                            boxes.append({"c": c, "x": (cx - w / 2) * W, "y": (cy - h / 2) * H,
                                          "w": w * W, "h": h * H, "note": notes.get(str(idx), "")})
            return self._send({"boxes": boxes})
        if u.path == "/api/auto":
            rel = q.get("img", [""])[0]
            p = os.path.join(ROOT, rel.replace("/", os.sep))
            try:
                from rapidocr_onnxruntime import RapidOCR
                res, _ = RapidOCR()(p)
                boxes = []
                if res:
                    for box, text, score in res:
                        xs = [pt[0] for pt in box]; ys = [pt[1] for pt in box]
                        boxes.append({"c": 3, "x": min(xs), "y": min(ys),
                                      "w": max(xs) - min(xs), "h": max(ys) - min(ys)})
                return self._send({"boxes": boxes})
            except Exception as e:
                return self._send({"boxes": [], "err": str(e)})
        return self._send(b"not found", 404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/classes":
            n = int(self.headers.get("Content-Length", 0))
            d = json.loads(self.rfile.read(n).decode("utf-8"))
            name = (d.get("name") or "").strip()
            if name and name not in CLASSES:
                CLASSES.append(name)
                save_classes(CLASSES)
            return self._send(CLASSES)
        if u.path == "/api/save":
            n = int(self.headers.get("Content-Length", 0))
            d = json.loads(self.rfile.read(n).decode("utf-8"))
            img_path = os.path.join(ROOT, d["img"].replace("/", os.sep))
            txt = img_path.rsplit(".", 1)[0] + ".txt"
            js = img_path.rsplit(".", 1)[0] + ".notes.json"
            try:
                from PIL import Image
                W, H = Image.open(img_path).size
            except Exception:
                W = H = 1280
            lines, notes = [], {}
            for i, b in enumerate(d.get("boxes", [])):
                lines.append(f"{b['c']} {(b['x']+b['w']/2)/W:.6f} {(b['y']+b['h']/2)/H:.6f} "
                             f"{b['w']/W:.6f} {b['h']/H:.6f}")
                if b.get("note"):
                    notes[str(i)] = b["note"]
            with open(txt, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            if notes:
                json.dump(notes, open(js, "w", encoding="utf-8"), ensure_ascii=False)
            elif os.path.exists(js):
                os.remove(js)
            return self._send({"ok": True, "n": len(lines)})
        return self._send({"ok": False}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    os.makedirs(ROOT, exist_ok=True)
    print(f"标注服务: http://127.0.0.1:{PORT}  数据集: {ROOT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
