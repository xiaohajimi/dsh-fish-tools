# -*- coding: utf-8 -*-
"""从录像帧里挑"难题"：模糊、暗、杂乱三类各若干张

输出：D:\\大肥鱼专用\\实验\\难帧集\\  （图片 + manifest.json）
"""
import io
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
from PIL import Image

ROOT = r"D:\大肥鱼专用\数据集\战雷帧"
DST = r"D:\大肥鱼专用\实验\难帧集"
os.makedirs(DST, exist_ok=True)

files = []
for d, _, fs in os.walk(ROOT):
    if "自选" in d:
        continue
    for f in fs:
        if f.lower().endswith((".png", ".jpg")):
            files.append(os.path.join(d, f))

print(f"共 {len(files)} 帧，抽样评估中…", flush=True)
sample = files[::max(1, len(files) // 400)]  # 最多看 400 张

rows = []
for p in sample:
    try:
        im = Image.open(p).convert("L").resize((384, 240))
        a = np.asarray(im, dtype=np.float32)
        lap = (
            np.abs(np.diff(a, axis=0)).mean() + np.abs(np.diff(a, axis=1)).mean()
        )
        bright = float(a.mean())
        contrast = float(a.std())
        if bright < 20:  # 纯黑/加载帧，跳过
            continue
        rows.append({"path": p, "blur": float(lap), "bright": bright, "contrast": contrast})
    except Exception:
        pass

def has_hud(path):
    """用 OCR 只读左侧 HUD 区，确认这是战斗画面而不是菜单"""
    try:
        from rapidocr_onnxruntime import RapidOCR
        im = Image.open(path).convert("RGB")
        w, h = im.size
        crop = im.crop((0, 0, int(w * 0.28), int(h * 0.36)))
        tmp = os.path.join(DST, "_tmp_hud.png")
        crop.save(tmp)
        res, _ = RapidOCR()(tmp)
        os.remove(tmp)
        txt = "".join(r[1] for r in res) if res else ""
        return ("节流" in txt) or ("速度" in txt) or ("高度" in txt)
    except Exception:
        return False


rows.sort(key=lambda r: r["blur"])
used = set()


def pick(group, n=6):
    out = []
    for r in group:
        if r["path"] in used:
            continue
        if not has_hud(r["path"]):
            used.add(r["path"])
            continue
        out.append(r)
        used.add(r["path"])
        if len(out) >= n:
            break
    return out


blurriest = pick(rows, 6)
rows.sort(key=lambda r: r["bright"])
darkest = pick(rows, 6)
rows.sort(key=lambda r: -r["contrast"])
busiest = pick(rows, 6)

manifest = []
for kind, group in (("模糊", blurriest), ("暗", darkest), ("杂乱", busiest)):
    for i, r in enumerate(group, 1):
        ext = os.path.splitext(r["path"])[1].lower()
        name = f"{kind}{i:02d}{ext}"
        shutil.copy2(r["path"], os.path.join(DST, name))
        manifest.append({"kind": kind, "file": name, "src": r["path"],
                         "blur": round(float(r["blur"]), 2), "bright": round(float(r["bright"]), 1),
                         "contrast": round(float(r["contrast"]), 1)})

io.open(os.path.join(DST, "manifest.json"), "w", encoding="utf-8").write(
    json.dumps(manifest, ensure_ascii=False, indent=1))
print(f"已挑出 {len(manifest)} 张 → {DST}", flush=True)
for m in manifest:
    print(f"  {m['file']} ｜ 模糊度 {m['blur']} ｜ 亮度 {m['bright']} ｜ 对比 {m['contrast']}", flush=True)
