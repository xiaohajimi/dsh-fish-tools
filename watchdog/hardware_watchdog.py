# -*- coding: utf-8 -*-
"""硬件看门狗：每分钟采一次 GPU/CPU/供电，写日志；越线就写告警（供 job-watch 唤醒）。

采集项（都是能真读到的）：
  GPU ：利用率、SM 频率、显存频率、功耗、温度、节流原因位
  CPU ：当前频率、负载
  供电：是否接电、充电状态、充电速率、电池电压、电量
  进程：训练进程数（掉了是大事）

越线规则（可在 THRESHOLDS 里改）：
  GPU 温度 > 85°C
  显存频率 < 10000 MHz 且利用率 > 80%（说明被节流压了）
  功耗 > 45 W（超过设定的功耗墙太多）
  CPU 频率 < 2000 MHz 且负载 > 30%（又被限频）
  掉电源（PowerOnline=False）
  训练进程数从 >0 变成 0（训练挂了）

用法：
  python 硬件看门狗.py                  # 每 60 秒，跑 12 小时
  python 硬件看门狗.py --minutes 30 --interval 30
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT_DIR = os.environ.get("FISH_HOME", os.path.expanduser("~/.dsh-fish"))
DATA = os.path.join(OUT_DIR, "硬件监控.jsonl")
ALERT = os.path.join(OUT_DIR, "硬件告警.log")

TH = {
    "gpu_temp_max": 70,
    "mem_clock_low": 10000,
    "mem_clock_util": 80,
    "power_max": 45,
    "cpu_clock_low": 2000,
    "cpu_load_gate": 30,
    "cpu_temp_max": 70,
}


def sh(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def gpu_sample():
    fields = ("utilization.gpu,clocks.sm,clocks.mem,power.draw,temperature.gpu,"
              "memory.used,clocks_throttle_reasons.active")
    q = sh(["nvidia-smi", "--query-gpu=" + fields, "--format=csv,noheader,nounits"])
    if not q:
        return {}
    parts = [p.strip() for p in q.split(",")]
    try:
        return {
            "gpu_util": int(float(parts[0])),
            "sm_mhz": int(float(parts[1])),
            "mem_mhz": int(float(parts[2])),
            "power_w": float(parts[3]),
            "gpu_temp": int(float(parts[4])),
            "vram_mb": int(float(parts[5])),
            "throttle_bits": parts[6],
        }
    except Exception:
        return {}


def cpu_sample():
    q = sh(["powershell", "-NoProfile", "-Command",
            "(Get-CimInstance Win32_Processor | Select-Object CurrentClockSpeed,LoadPercentage | "
            "ConvertTo-Json -Compress)"])
    try:
        d = json.loads(q)
        return {"cpu_mhz": int(d.get("CurrentClockSpeed", 0)),
                "cpu_load": int(d.get("LoadPercentage", 0))}
    except Exception:
        return {}


def power_sample():
    q = sh(["powershell", "-NoProfile", "-Command",
            "(Get-CimInstance -Namespace root/wmi -ClassName BatteryStatus | "
            "Select-Object -First 1 PowerOnline,Charging,ChargeRate,Voltage | ConvertTo-Json -Compress)"])
    try:
        d = json.loads(q)
        return {"ac_online": bool(d.get("PowerOnline")),
                "charging": bool(d.get("Charging")),
                "charge_rate": d.get("ChargeRate"),
                "batt_mv": d.get("Voltage")}
    except Exception:
        return {}


def cpu_temp():
    """CPU 温度：优先 LibreHardwareMonitor 的 WMI；没有就返回 None（这台机器 WMI 热区是空的）"""
    q = sh(["powershell", "-NoProfile", "-Command",
            "try { (Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor "
            "-ErrorAction Stop | Where-Object { $_.SensorType -eq 'Temperature' -and $_.Name -match 'CPU' } "
            "| Sort-Object Value -Descending | Select-Object -First 1).Value } catch { '' }"])
    try:
        v = float(q.strip())
        return int(v)
    except Exception:
        return None


def train_procs():
    q = sh(["powershell", "-NoProfile", "-Command",
            "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -match 'qlora_coding' } | Measure-Object).Count"])
    try:
        return int(q.strip() or 0)
    except Exception:
        return -1


def check(rec, last):
    alerts = []
    if rec.get("gpu_temp", 0) > TH["gpu_temp_max"]:
        alerts.append("GPU 温度 %d°C 超过 %d°C" % (rec["gpu_temp"], TH["gpu_temp_max"]))
    if rec.get("gpu_util", 0) > TH["mem_clock_util"] and rec.get("mem_mhz", 99999) < TH["mem_clock_low"]:
        alerts.append("显存频率 %d MHz 偏低（利用率 %d%%），可能被节流" % (rec["mem_mhz"], rec["gpu_util"]))
    if rec.get("power_w", 0) > TH["power_max"]:
        alerts.append("功耗 %.1f W 超过 %d W" % (rec["power_w"], TH["power_max"]))
    if rec.get("cpu_temp") is not None and rec["cpu_temp"] > TH["cpu_temp_max"]:
        alerts.append("CPU 温度 %d°C 超过 %d°C" % (rec["cpu_temp"], TH["cpu_temp_max"]))
    if rec.get("cpu_load", 0) > TH["cpu_load_gate"] and rec.get("cpu_mhz", 9999) < TH["cpu_clock_low"]:
        alerts.append("CPU 频率 %d MHz 偏低（负载 %d%%）" % (rec["cpu_mhz"], rec["cpu_load"]))
    if rec.get("ac_online") is False:
        alerts.append("电源掉了（未接电）")
    if last.get("train", 0) > 0 and rec.get("train", 0) == 0:
        alerts.append("训练进程消失了（之前 %d 个）" % last.get("train", 0))
    return alerts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--minutes", type=int, default=720)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    end = time.time() + a.minutes * 60
    last = {"train": 0}
    n = 0
    while time.time() < end:
        rec = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        rec.update(gpu_sample())
        rec.update(cpu_sample())
        ct = cpu_temp()
        if ct is not None:
            rec['cpu_temp'] = ct
        rec.update(power_sample())
        rec["train"] = train_procs()
        alerts = check(rec, last)
        rec["alerts"] = alerts
        last["train"] = rec.get("train", 0)

        with open(DATA, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if alerts:
            with open(ALERT, "a", encoding="utf-8") as f:
                f.write("[%s] %s | %s\n" % (rec["ts"], "；".join(alerts), json.dumps(rec, ensure_ascii=False)))
        if not a.quiet and (n % 10 == 0 or alerts):
            print("[%s] GPU %d%% %dMHz(mem %d) %.1fW %d°C | CPU %dMHz %d%% | 训练%d | %s"
                  % (rec["ts"], rec.get("gpu_util", -1), rec.get("sm_mhz", -1), rec.get("mem_mhz", -1),
                     rec.get("power_w", -1), rec.get("gpu_temp", -1), rec.get("cpu_mhz", -1),
                     rec.get("cpu_load", -1), rec.get("train", -1),
                     ("⚠ " + "；".join(alerts)) if alerts else "正常"), flush=True)
        n += 1
        time.sleep(max(10, a.interval))


if __name__ == "__main__":
    main()
