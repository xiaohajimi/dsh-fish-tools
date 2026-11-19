# -*- coding: utf-8 -*-
r"""存盘提醒：每出新的 checkpoint，就把 DSH 窗口拉到最前面，给 30 秒切配置的窗口。

用法：
  python 存盘提醒.py            # 常驻，每 2 秒扫一次
  python 存盘提醒.py --dry      # 只找窗口/报状态，不抢前台
  python 存盘提醒.py --once     # 立刻抢一次前台（测试用）

日志：<LOG_PATH>
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = os.environ.get("FISH_TRAIN_OUT", "")
LOG = os.environ.get("FISH_NOTIFY_LOG", "")
TITLE_KEY = "DeepSeek Harness"

u32 = ctypes.windll.user32
u32.SetForegroundWindow.argtypes = [wt.HWND]
u32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
u32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, ctypes.c_bool]
u32.BringWindowToTop.argtypes = [wt.HWND]


def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def find_dsh():
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if not u32.IsWindowVisible(hwnd):
            return True
        n = u32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hwnd, buf, n + 1)
        if TITLE_KEY in buf.value:
            found.append((hwnd, buf.value))
        return True

    u32.EnumWindows(cb, 0)
    return found


def force_foreground(hwnd):
    if u32.GetForegroundWindow() == hwnd:
        return True
    fg = u32.GetForegroundWindow()
    tid_fg = u32.GetWindowThreadProcessId(fg, None)
    tid_tg = u32.GetWindowThreadProcessId(hwnd, None)
    ok = False
    try:
        u32.AttachThreadInput(tid_fg, tid_tg, True)
        u32.ShowWindow(hwnd, 9)  # SW_RESTORE
        u32.BringWindowToTop(hwnd)
        ok = bool(u32.SetForegroundWindow(hwnd))
    finally:
        try:
            u32.AttachThreadInput(tid_fg, tid_tg, False)
        except Exception:
            pass
    return ok or u32.GetForegroundWindow() == hwnd


def checkpoints():
    if not os.path.isdir(OUT):
        return set()
    return {d for d in os.listdir(OUT) if d.startswith("checkpoint-")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()

    wins = find_dsh()
    if not wins:
        log("找不到 DSH 窗口（标题含 %s）" % TITLE_KEY)
        return 1
    hwnd, title = wins[0]
    log("找到 DSH 窗口：0x%X %s" % (hwnd, title))

    if a.dry:
        log("干跑：不抢前台，当前已有 checkpoint %d 个" % len(checkpoints()))
        return 0
    if a.once:
        ok = force_foreground(hwnd)
        log("测试抢前台：%s" % ("成功" if ok else "失败"))
        return 0

    seen = checkpoints()
    log("开始监听（已有 %d 个 checkpoint）：%s" % (len(seen), OUT))
    while True:
        time.sleep(2)
        cur = checkpoints()
        new = cur - seen
        if new:
            for name in sorted(new):
                log("新存盘：%s → 拉 DSH 到前台，30 秒切换窗口开始" % name)
            hwnd, title = (find_dsh() or [(hwnd, title)])[0]
            ok = force_foreground(hwnd)
            log("抢前台：%s；接下来 30 秒可以切配置" % ("成功" if ok else "失败"))
            seen = cur
            time.sleep(28)


if __name__ == "__main__":
    sys.exit(main())
