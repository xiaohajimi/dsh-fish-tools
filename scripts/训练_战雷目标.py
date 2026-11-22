# -*- coding: utf-8 -*-
"""训练战雷目标检测器（YOLO）

按域过滤：只保留"目标"类框（自身/敌机/友机/导弹/锁定圈），其余类丢弃。
把类别重映射成 0..N，导出到数据集目录，再调用 ultralytics 训练。

用法：
  python 训练_战雷目标.py --dry-run        # 只统计，不训练
  python 训练_战雷目标.py --epochs 100 --imgsz 1280
"""
import argparse
import io
import json
import os
import random
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FRAMES_ROOT = r"D:\大肥鱼专用\数据集\战雷帧"
CLASSES_FILE = r"D:\大肥鱼专用\数据集\classes.json"
WORK = r"D:\大肥鱼专用\数据集\yolo_战雷"
TARGET_NAMES = ["自身", "敌机", "友机", "导弹", "锁定圈", "目标标记"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--min-frames", type=int, default=20)
    args = ap.parse_args()

    classes = json.load(open(CLASSES_FILE, encoding="utf-8"))
    keep = {}
    for i, name in enumerate(classes):
        if name in TARGET_NAMES:
            keep[i] = len(keep)
    print("  保留类别:", {classes[k]: v for k, v in keep.items()}, flush=True)

    # 收集已标帧（只取战雷目录，不含自选）
    samples = []
    for d, _, fs in os.walk(FRAMES_ROOT):
        if os.sep + "自选" in d:
            continue
        for f in fs:
            if not f.endswith(".txt"):
                continue
            txt = os.path.join(d, f)
            img = None
            for ext in (".png", ".jpg"):
                cand = txt[:-4] + ext
                if os.path.exists(cand):
                    img = cand
                    break
            if not img:
                continue
            boxes = []
            for line in io.open(txt, encoding="utf-8"):
                v = line.split()
                if len(v) == 5:
                    c = int(v[0])
                    if c in keep:
                        boxes.append((keep[c], v[1], v[2], v[3], v[4]))
            if boxes:
                samples.append((img, boxes))

    print(f"  含目标框的帧: {len(samples)}", flush=True)
    if len(samples) < args.min_frames:
        print(f"  数据不足（<{args.min_frames} 帧），先别训。请继续标注飞机/自身。", flush=True)
        return

    if args.dry_run:
        from collections import Counter
        c = Counter()
        for _, boxes in samples:
            for b in boxes:
                c[classes[[k for k, v in keep.items() if v == b[0]][0]]] += 1
        print("  目标框分布:", dict(c), flush=True)
        return

    # 导出
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        os.makedirs(os.path.join(WORK, sub), exist_ok=True)
    random.seed(0)
    random.shuffle(samples)
    n_val = max(1, int(len(samples) * 0.2))
    for idx, (img, boxes) in enumerate(samples):
        split = "val" if idx < n_val else "train"
        base = os.path.splitext(os.path.basename(img))[0]
        dst_img = os.path.join(WORK, "images", split, base + os.path.splitext(img)[1])
        shutil.copy2(img, dst_img)
        with io.open(os.path.join(WORK, "labels", split, base + ".txt"), "w", encoding="utf-8") as f:
            for c, x, y, w, h in boxes:
                f.write(f"{c} {x} {y} {w} {h}\n")

    names = [classes[[k for k, v in keep.items() if v == i][0]] for i in range(len(keep))]
    yaml_path = os.path.join(WORK, "data.yaml")
    io.open(yaml_path, "w", encoding="utf-8").write(
        f"path: {WORK}\ntrain: images/train\nval: images/val\nnames: {json.dumps(names, ensure_ascii=False)}\n")

    from ultralytics import YOLO
    model = YOLO(r"D:\大肥鱼专用\models\yolo26\yolo26s.pt")
    model.train(data=yaml_path, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                project=os.path.join(WORK, "runs"), name="战雷目标", exist_ok=True)


if __name__ == "__main__":
    main()
