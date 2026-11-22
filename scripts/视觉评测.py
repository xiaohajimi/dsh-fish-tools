# -*- coding: utf-8 -*-
"""视觉模型横向评测：同一批图片、同一个提示词，比"读得准"和"读得快"

用法：
  python 视觉评测.py --models <名字:模型:项目文件> ...
  python 视觉评测.py --all        # 跑内置清单里已下载的模型

判分：对每张图给出"必须读到的关键字符串"，按子串命中率算准确率。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXE = r"D:\大肥鱼专用\models\llama-b12556-cuda135\llama-server.exe"
VDIR = r"C:\Users\11382\models\vision"
PORT = 8100

# 图片 + 必须读到的关键内容（ground truth 来自人工读帧）
CASES = [
    {
        "name": "hud_15-15",
        "path": r"D:\大肥鱼专用\实验\obs_1939\t1509\f03.jpg",
        "crop": (20, 20, 620, 520),
        "expect": ["100%", "681", "694", "163", "6G", "8/2", "霹雳", "0:08", "200", "11:19", "92", "709"],
    },
    {
        "name": "hud_14-52",
        "path": r"D:\大肥鱼专用\实验\obs_1939\danger_001452.jpg",
        "crop": (20, 20, 620, 520),
        "expect": ["100", "307", "321", "653", "78", "23", "200", "12:17", "94", "767"],
    },
    {
        "name": "hud_29-00",
        "path": r"D:\大肥鱼专用\实验\obs_1939\t2900.jpg",
        "crop": (20, 20, 620, 520),
        "expect": ["1332", "238", "12:29", "144", "霹雳", "813", "604"],
    },
]

PROMPT = "请逐行读出图中所有可见的文字和数字，原样输出，不要解释、不要翻译。"

MODELS = [
    # (显示名, 模型文件, 项目文件, 设备)
    ("GLM-OCR", "GLM-OCR-Q8_0.gguf", "mmproj-GLM-OCR-Q8_0.gguf", "cpu"),
    ("GLM-4.6V-Flash", "GLM-4.6V-Flash-Q4_K_M.gguf", "mmproj-GLM-4.6V-Flash-F16.gguf", "gpu"),
    ("GLM-4.6V-Flash-Q6", "GLM-4.6V-Flash-Q6_K.gguf", "mmproj-GLM-4.6V-Flash-F16.gguf", "cpu"),
    ("Qwen3-VL-4B", "Qwen3VL-4B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf", "gpu"),
    ("Qwen3-VL-8B", "Qwen3VL-8B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf", "gpu"),
    ("PaddleOCR-VL-1.5", "PaddleOCR-VL-1.5-Q8_0.gguf", "mmproj-F16.gguf", "cpu"),
    ("InternVL3-2B", "InternVL3-2B-Instruct-Q8_0.gguf", "mmproj-InternVL3-2B-Instruct-Q8_0.gguf", "cpu"),
    ("InternVL3-1B", "InternVL3-1B-Instruct-Q8_0.gguf", "mmproj-InternVL3-1B-Instruct-Q8_0.gguf", "cpu"),
    ("InternVL3-1B-f16mm", "InternVL3-1B-Instruct-Q8_0.gguf", "mmproj-InternVL3-1B-Instruct-f16.gguf", "cpu"),
    ("SmolVLM2-2.2B", "SmolVLM2-2.2B-Instruct-Q4_K_M.gguf", "mmproj-SmolVLM2-2.2B-Instruct-Q8_0.gguf", "cpu"),
    ("MiniCPM-V-1B", "MiniCPM-V-4_7-1B-Q4_K_M.gguf", "mmproj-model-f16.gguf", "cpu"),
]


def crop_image(src, crop, dst):
    from PIL import Image
    im = Image.open(src).convert("RGB")
    if crop:
        x, y, w, h = crop
        im = im.crop((x, y, x + w, y + h))
        im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
    im.save(dst, quality=92)
    return dst


def start_server(model, mmproj, device, port):
    args = [EXE, "-m", os.path.join(VDIR, model), "--mmproj", os.path.join(VDIR, mmproj),
            "-c", "4096", "--host", "127.0.0.1", "--port", str(port)]
    args += ["-ngl", "99" if device == "gpu" else "0"]
    log = open(os.path.join(VDIR, "last_server.log"), "w", encoding="utf-8")
    p = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(120):
        time.sleep(2)
        if p.poll() is not None:
            return None
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
                if r.status == 200:
                    return p
        except Exception:
            pass
    return None


def ask(image_path, port, max_tokens=700):
    import base64
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    body = {
        "model": "vision",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ]}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1800) as r:
        data = json.loads(r.read().decode())
    msg = data["choices"][0]["message"]
    text = (msg.get("content") or msg.get("reasoning_content") or "").strip()
    return text, time.time() - t0


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只跑名字包含这个的模型")
    ap.add_argument("--out", default=r"D:\大肥鱼专用\实验\视觉评测结果.json")
    args = ap.parse_args()

    tmp = os.path.join(VDIR, "_eval_crop.jpg")
    results = []
    for name, model, mmproj, device in MODELS:
        if args.only and args.only not in name:
            continue
        if not (os.path.exists(os.path.join(VDIR, model)) and os.path.exists(os.path.join(VDIR, mmproj))):
            print(f"[跳过] {name}（文件不在）", flush=True)
            continue
        print(f"\n===== {name}（{device}）=====", flush=True)
        p = start_server(model, mmproj, device, PORT)
        if not p:
            print(f"[失败] {name} 起不来", flush=True)
            continue
        try:
            for case in CASES:
                img = crop_image(case["path"], case["crop"], tmp)
                try:
                    text, sec = ask(img, PORT)
                except Exception as e:
                    print(f"  {case['name']} 请求失败: {e}", flush=True)
                    continue
                nt = norm(text)
                hits = [e for e in case["expect"] if norm(e) in nt]
                acc = len(hits) / len(case["expect"])
                print(f"  {case['name']}: 命中 {len(hits)}/{len(case['expect'])} = {acc:.0%} ｜ {sec:.1f}s", flush=True)
                results.append({"model": name, "case": case["name"], "acc": round(acc, 3),
                                "seconds": round(sec, 1), "miss": [e for e in case["expect"] if e not in hits],
                                "text": text[:1500]})
        finally:
            p.terminate()
            try:
                p.wait(timeout=20)
            except Exception:
                p.kill()
            time.sleep(2)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"\n结果已写 {args.out}", flush=True)

    # 汇总
    print("\n===== 汇总（平均准确率 / 平均耗时）=====")
    by = {}
    for r in results:
        by.setdefault(r["model"], []).append(r)
    for m, rs in sorted(by.items(), key=lambda kv: -sum(x["acc"] for x in kv[1]) / len(kv[1])):
        acc = sum(x["acc"] for x in rs) / len(rs)
        sec = sum(x["seconds"] for x in rs) / len(rs)
        print(f"  {m:<20} 准确率 {acc:.0%} ｜ 平均 {sec:.1f}s", flush=True)


if __name__ == "__main__":
    main()
