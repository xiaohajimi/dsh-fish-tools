# -*- coding: utf-8 -*-
"""用 Qwen2.5-Omni 听音频：llama.cpp input_audio 格式

用法：python 听歌_omni.py --audio ... [--url http://127.0.0.1:8095] [--start 0 --dur 30]
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def to_wav(path, dst, start=0, dur=30):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", str(start), "-t", str(dur), "-i", path,
                    "-ac", "1", "-ar", "16000", dst], check=False)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8095")
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--dur", type=float, default=30)
    ap.add_argument("--prompt", default="请描述这段音乐：风格、情绪、节奏、主要乐器与人声。用中文，不超过五句。")
    ap.add_argument("--max-new", type=int, default=300)
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="omni_")
    wav = os.path.join(tmp, "a.wav")
    to_wav(args.audio, wav, args.start, args.dur)
    size = os.path.getsize(wav)
    print(f"片段 {args.dur}s ｜ {size/1024**2:.1f} MB", flush=True)
    b64 = base64.b64encode(open(wav, "rb").read()).decode()

    body = {"model": "omni", "messages": [{"role": "user", "content": [
        {"type": "text", "text": args.prompt},
        {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}},
    ]}], "max_tokens": args.max_new, "temperature": 0.0}

    req = urllib.request.Request(args.url.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=3600) as r:
        d = json.loads(r.read().decode())
    m = d["choices"][0]["message"]
    txt = (m.get("content") or m.get("reasoning_content") or "").strip()
    print(f"\n===== 结果（{time.time()-t0:.0f}s）=====\n{txt}", flush=True)
    open(r"D:\大肥鱼专用\实验\听歌_omni.txt", "w", encoding="utf-8").write(txt)


if __name__ == "__main__":
    main()
