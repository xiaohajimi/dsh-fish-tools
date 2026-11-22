# -*- coding: utf-8 -*-
"""态势理解 v5：分工版

  视觉模型（VLM）：只回答"画面里有什么、谁像敌方"
  规则引擎      ：只回答"谁在追谁"，依据三类可复现证据
  合 成         ：把两者写成一段解释（不参与判断）
"""
import argparse
import base64
import io
import json
import os
import re
import sys
import tempfile
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from PIL import Image

FRAMES_DIR = r"D:\大肥鱼专用\数据集\战雷帧\2026-11-22_19-39-57"
CENTERS = [305, 307, 309, 311]

ENTITY_PROMPT = """只看画面，回答两件事，简短：
1) 画面上真实可见的实体（玩家机、敌机、导弹、地面单位），各几个？
2) 哪个是玩家（画面中心偏下最大那架），你怎么判断的？
不要回答"谁在追谁"，那不是你的任务。"""


_ocr = None


def ocr(path):
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    res, _ = _ocr(path)
    return res or []


def region(path, box, tmp, tag):
    im = Image.open(path).convert("RGB")
    crop = im.crop(box)
    p = os.path.join(tmp, tag + ".png")
    crop.save(p)
    return [(it[1], sum(pt[0] for pt in it[0]) / 4 + box[0], sum(pt[1] for pt in it[0]) / 4 + box[1])
            for it in ocr(p)]


def collect(fid, tmp):
    cur = os.path.join(FRAMES_DIR, f"{fid:05d}.png")
    W, H = Image.open(cur).size
    boxes = {
        "hud": (0, 0, int(W * 0.26), int(H * 0.36)),
        "warn": (int(W * 0.28), int(H * 0.04), int(W * 0.75), int(H * 0.26)),
        "feed": (int(W * 0.60), int(H * 0.80), W, H),
        "labels": (int(W * 0.28), int(H * 0.10), W, int(H * 0.70)),
    }
    out = {}
    for k, b in boxes.items():
        out[k] = region(cur, b, tmp, k)
    return out, W, H, cur


def find_distances(items):
    """从标签文字里抽距离（形如 0.39km / 1.62 km）"""
    ds = []
    for t, x, y in items:
        m = re.search(r"(\d+(?:\.\d+)?)\s*k?m", t.replace(" ", ""))
        if m:
            try:
                ds.append(float(m.group(1)))
            except Exception:
                pass
    return ds


def rules(facts, prev_facts=None):
    """返回 (判断, 证据列表)"""
    ev = []
    warn_txt = " ".join(t for t, _, _ in facts["warn"])
    hud_txt = " ".join(t for t, _, _ in facts["hud"])
    feed_txt = " ".join(t for t, _, _ in facts["feed"])

    chased = False
    chasing = False

    if any(k in warn_txt for k in ("敌导弹", "规避导弹", "导弹告警", "被锁定")):
        chased = True
        ev.append(f"告警出现：{warn_txt[:40]}")
    if "导引头" in hud_txt and ("追踪" in hud_txt or "锁定" in hud_txt):
        chasing = True
        ev.append("HUD 显示导引头正在追踪（玩家在攻击）")

    ds = find_distances(facts["labels"])
    ds_prev = find_distances(prev_facts["labels"]) if prev_facts else []
    if ds and ds_prev:
        if min(ds) < min(ds_prev):
            ev.append(f"目标距离缩短（{min(ds_prev)}→{min(ds)}），对方在接近")
            if not chasing:
                chased = True
    if "热焰弹" in hud_txt and re.search(r"热焰弹\D{0,3}0:0[0-3]", hud_txt):
        ev.append("干扰弹接近耗尽（防守姿态）")

    if chased and not chasing:
        return "玩家被追（防守）", ev
    if chasing and not chased:
        return "玩家在追（进攻）", ev
    if chasing and chased:
        return "互相缠斗（双方都在锁）", ev
    return "看不出（证据不足）", ev


def ask_entity(path, url):
    im = Image.open(path).convert("RGB")
    if im.width > 1024:
        im = im.resize((1024, int(im.height * 1024 / im.width)), Image.LANCZOS)
    p = path + ".small.jpg"
    im.save(p, quality=90)
    with open(p, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    os.remove(p)
    body = {"model": "v", "messages": [{"role": "user", "content": [
        {"type": "text", "text": ENTITY_PROMPT},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}],
        "max_tokens": 300, "temperature": 0.0, "frequency_penalty": 0.8}
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read().decode())
    m = d["choices"][0]["message"]
    return (m.get("content") or m.get("reasoning_content") or "").strip(), round(time.time() - t0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vlm", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="v5_")
    results = []
    prev = None
    for fid in CENTERS:
        path = os.path.join(FRAMES_DIR, f"{fid:05d}.png")
        if not os.path.exists(path):
            continue
        facts, W, H, cur = collect(fid, tmp)
        decision, ev = rules(facts, prev)
        prev = facts
        print(f"\n===== 帧 {fid} =====", flush=True)
        print(f"  规则判断：{decision}", flush=True)
        for e in ev:
            print(f"    · {e}", flush=True)
        try:
            ent, sec = ask_entity(cur, args.vlm)
            print(f"  视觉（实体）：{ent[:300]}", flush=True)
            results.append({"frame": fid, "decision": decision, "evidence": ev,
                            "entities": ent, "seconds": sec})
        except Exception as e:
            print(f"  视觉失败: {e}", flush=True)
            results.append({"frame": fid, "decision": decision, "evidence": ev, "entities": ""})

    io.open(args.out, "w", encoding="utf-8").write(json.dumps(results, ensure_ascii=False, indent=1))
    print(f"\n结果写 {args.out}", flush=True)


if __name__ == "__main__":
    main()
