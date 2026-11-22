# -*- coding: utf-8 -*-
"""数据集体检：分域统计 + 感知哈希去重 + 类别分布

输出：
  D:\\大肥鱼专用\\实验\\数据集体检.json
  D:\\大肥鱼专用\\实验\\数据集体检.md
"""
import io
import json
import os
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from PIL import Image

ROOT = r"D:\大肥鱼专用\数据集\战雷帧"
OUT_JSON = r"D:\大肥鱼专用\实验\数据集体检.json"
OUT_MD = r"D:\大肥鱼专用\实验\数据集体检.md"
CLASSES = json.load(open(r"D:\大肥鱼专用\数据集\classes.json", encoding="utf-8"))


def dhash(path, size=8):
    im = Image.open(path).convert("L").resize((9, size), Image.LANCZOS)
    px = list(im.getdata())
    bits = 0
    for r in range(size):
        for c in range(8):
            bits = (bits << 1) | (1 if px[r * 9 + c] > px[r * 9 + c + 1] else 0)
    return bits


def hamming(a, b):
    return bin(a ^ b).count("1")


def main():
    domains = defaultdict(lambda: {"images": 0, "labeled": 0, "boxes": Counter()})
    per_dir = []
    hashes = {}

    for dirpath, _, files in os.walk(ROOT):
        rel = os.path.relpath(dirpath, ROOT)
        dom = "战雷" if not rel.startswith("自选") else "自选/" + (rel.split(os.sep)[1] if os.sep in rel else rel)
        imgs = sorted(f for f in files if f.lower().endswith((".png", ".jpg")))
        if not imgs:
            continue
        for fn in imgs:
            p = os.path.join(dirpath, fn)
            try:
                hashes[p] = (dhash(p), dom)
            except Exception:
                pass
            domains[dom]["images"] += 1
            txt = os.path.join(dirpath, os.path.splitext(fn)[0] + ".txt")
            if os.path.exists(txt):
                domains[dom]["labeled"] += 1
                for line in io.open(txt, encoding="utf-8"):
                    v = line.split()
                    if v:
                        try:
                            c = int(v[0])
                            domains[dom]["boxes"][CLASSES[c] if c < len(CLASSES) else f"cls{c}"] += 1
                        except Exception:
                            pass
        per_dir.append({"dir": rel, "images": len(imgs)})

    # 去重：贪心，与已保留的任一哈希 hamming < 4 视为重复
    kept = []
    dup = 0
    for p, (h, dom) in sorted(hashes.items()):
        is_dup = False
        for kh, kp, kd in kept:
            if hamming(h, kh) < 4:
                is_dup = True
                break
        if is_dup:
            dup += 1
        else:
            kept.append((h, p, dom))

    kept_by_dom = Counter(d for _, _, d in kept)
    report = {
        "total_images": len(hashes),
        "unique_images": len(kept),
        "duplicates": dup,
        "unique_by_domain": dict(kept_by_dom),
        "domains": {k: {"images": v["images"], "labeled": v["labeled"],
                        "boxes": dict(v["boxes"])} for k, v in domains.items()},
        "dirs": per_dir,
    }
    io.open(OUT_JSON, "w", encoding="utf-8").write(json.dumps(report, ensure_ascii=False, indent=1))

    md = ["# 数据集体检\n",
          f"- 图片总数：{len(hashes)}",
          f"- 不重复（去重后）：{len(kept)}",
          f"- 重复：{dup}（{dup/max(1,len(hashes))*100:.0f}%）",
          "\n## 分域\n",
          "| 域 | 图片 | 已标 | 去重后不重复 |",
          "|---|---|---|---|"]
    for d, v in report["domains"].items():
        md.append(f"| {d} | {v['images']} | {v['labeled']} | {kept_by_dom.get(d, 0)} |")
    md.append("\n## 类别分布（已标框）\n")
    md.append("| 域 | 类别 | 数量 |")
    md.append("|---|---|---|")
    for d, v in report["domains"].items():
        for c, n in sorted(v["boxes"].items(), key=lambda kv: -kv[1]):
            md.append(f"| {d} | {c} | {n} |")
    io.open(OUT_MD, "w", encoding="utf-8").write("\n".join(md) + "\n")

    print("\n".join(md))
    print(f"\n已写 {OUT_MD}")


if __name__ == "__main__":
    main()
