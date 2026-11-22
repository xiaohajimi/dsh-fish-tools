# dsh-fish-tools

**Local LLMs on one 8 GB laptop GPU** — QLoRA fine-tuning, a hardware watchdog, an objective benchmark harness, DSH plugins, and the measured numbers behind them. Not estimates: real runs, and "it doesn't work" written down where it doesn't work.

---

## 三种语言 / Три языка / Three languages

### 中文

在**单张 8 GB 笔记本显卡**上跑本地大模型的工具与实测记录：QLoRA 微调、硬件看门狗、客观题库跑分、DSH 插件。
关键词：`8GB 显存` `QLoRA` `llama.cpp` `Gemma-4` `训练监控` `benchmark` `Windows`。
所有数字来自真实运行；跑不通的地方直接写「跑不通」。

### Русский

Локальные LLM на ноутбуке с **одной видеокартой на 8 ГБ**: QLoRA-дообучение, аппаратный сторож, объективный тест-набор, плагины DSH.
Ключевые слова: `8 ГБ видеопамяти` `QLoRA` `llama.cpp` `Gemma-4` `мониторинг обучения` `бенчмарк` `Windows`.
Все цифры получены на реальных запусках; там, где не работает, так и написано.

### English

Tools and measurements for running local LLMs on a **single 8 GB laptop GPU**: QLoRA fine-tuning, a hardware watchdog, an objective benchmark harness, DSH plugins.
Keywords: `8GB VRAM` `QLoRA` `llama.cpp` `Gemma-4` `training monitor` `benchmark` `Windows`.
Every number comes from a real run; where it does not work, the text says so.

---

## 这个仓库里有什么

| 目录 | 内容 | 状态 |
|---|---|---|
| `watchdog/` | 硬件看门狗：每分钟采 GPU/CPU/供电，越线写告警日志 | 可用 |
| `notifier/` | 存盘提醒：训练每 N 步存盘时，把指定窗口拉到前台给你操作 | 可用 |
| `trainer/` | QLoRA 训练脚本（Gemma-4 E4B，单卡 8 GB） | 可用 |
| `bench/` | 客观题库跑分（题目密文 + 判分清单） | 可用 |
| `dsh-update-guard/` | DSH 插件：锁版本、版本变了写告警、提醒别随手升级 | 可用 |
| `dsh-labor/` | DSH 插件：把机械活派给本地模型（起服务/派活/落盘一次调用） | 可用 |
| `docs/` | 实测记录（训练速度、显存频率、坑） | 持续更新 |

---

## 背景：这台机器

```
RTX 5070 Laptop 8 GB（GB206，GDDR7 三星，128-bit，384 GB/s）
Ryzen 9 7845HX（12 核 24 线程）
24 GB 内存
Windows 11 + 驱动 621.24
```

**目标**：8 GB 显存上把 Gemma-4 E4B 做 QLoRA 风格微调。

---

## 三条最值钱的实测结论

### ① 显存频率 9001 vs 12001，对训练速度几乎没影响

```
12001 MHz（标准，= 24 Gbps = 384 GB/s）：117–128 秒/步
9001 MHz（驱动省电档，掉 25%）           ：122–151 秒/步
```

**结论**：训练瓶颈不在显存带宽，别为训练去超显存。

### ② 占空比 97% 比 93% 更快，但 100% 会更慢

| duty | 实测速度 |
|---|---|
| 0.93 | 128.6 秒/步 |
| **0.97** | **117.2 秒/步** |
| 1.00（满载） | 105 → 150 秒/步（后段被 Reliability 节流拖慢） |

**原因**：满载会触发驱动的 `Reliability` 节流，把显存从 12001 压到 9001；留 3% 余量反而不降频。

### ③ 线程数不是越多越好

| 配置 | 速度 |
|---|---|
| **4 线程（默认）** | **128 秒/步** |
| 12 物理核 | 209 秒/步（慢 62%） |
| 4 核 + 预 tokenize 缓存 | 158 秒/步（慢 23%） |

**结论**：这台机器上 4 线程就是最优；tokenize 不是瓶颈。

---

## 快速开始

### 硬件看门狗

```bash
# 每 60 秒采一次，跑 12 小时
set FISH_HOME=D:\your\dir
python watchdog/hardware_watchdog.py --interval 60 --minutes 720
```

输出：`<FISH_HOME>/硬件监控.jsonl`（一行一个采样点）+ `<FISH_HOME>/硬件告警.log`（越线才写）

阈值在脚本顶部 `TH` 里改：

```python
TH = {
    "gpu_temp_max": 70,      # GPU 温度
    "mem_clock_low": 10000,  # 显存频率低于这个且利用率高 → 说明被节流
    "power_max": 45,
    "cpu_clock_low": 2000,
    "cpu_load_gate": 30,
    "cpu_temp_max": 70,
}
```

> **已知限制**：AMD 平台读不到 CPU 温度（WMI 热区为空、`Get-Counter` 无实例）。
> 装了 LibreHardwareMonitor 并开启 WMI 共享后，脚本会自动读到；否则该字段跳过。

### 存盘提醒

```bash
set FISH_TRAIN_OUT=D:\your\train\out\my-lora
set FISH_NOTIFY_LOG=D:\your\notify.log
python notifier/checkpoint_notifier.py
```

每出现新的 `checkpoint-*` 目录，就把标题含 `DeepSeek Harness` 的窗口拉到前台并静默 28 秒——给需要手动切配置的人留一个窗口。

---

## 2026-11-21 的新数字（当天实测，含一次真崩溃）

| 项目 | 实测值 |
|---|---|
| USB 链路（hdc，1 GB） | **110.9 MB/s**（并发时 137.1） |
| Wi-Fi 链路（热点，1 GB） | **30.9 MB/s**（并发时 41.3） |
| Wi-Fi RTT | 58 / 67 / 90 / 104 ms（4 包 0% 丢包） |
| 8 GB 卡训练崩溃点 | **step 78**，显存 7693 / 8151 MiB（余 458 MB） |
| 同一适配器功能评测 | 12/14（裸）→ 8/14 → 5/14 → **7/14** |

**结论一句话**：8 GB 上跑 QLoRA 必须给显存留 ≥15% 余量；不到 6% 时会被任何一次波形挤爆。
缓解是 `--seq 512→448` + `expandable_segments:True,garbage_collection_threshold:0.8` + 训练期间关掉别的显存占用。

细节与命令： [`docs/实测_20261121.md`](docs/实测_20261121.md)

---

## License

MIT。代码拿去随便用；`docs/` 里的实测数字请保留出处。

## 2026-11-23 新增

| 文件 | 内容 |
|---|---|
| `docs/鸿蒙平板算力节点_RPC与本地推理.md` | 平板当 RPC 节点 vs 本地推理的实测（0.22 / 0.40 / 0.47 tok/s），含 6 个编译与沙箱坑 |
| `docs/本地模型评测_口径与结果.md` | 20 题基础编程 / AtCoder 100 / 视觉读数 / 四问法 / 音频理解的分数与失败分类 |
| `scripts/` | 上述评测与标注工具的脚本（可直接跑） |

一句话结论：**格式污染能把模型的编程分判低 10 个点以上**（61/69 失败是 SyntaxError），
改脚本前后同一个模型从 31% 变成 42%。