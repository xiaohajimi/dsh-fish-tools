# 8 GB 显存 + 24 GB 内存的完整打法

> 一台游戏本（RTX 5070 Laptop 8 GB / Ryzen 9 7845HX / 24 GB DDR5）上，
> 跑 QLoRA 微调、跑 35B MoE 量化、搭检索与监控的**全部实测记录与避坑清单**。
>
> 所有数字来自真实运行（2026-11-19 ~ 11-20）。跑不通的地方我写"跑不通"。
> 不确定的结论我标「观察值，未验证」。

---

## 零、先说最重要的三条

### ① 真正的瓶颈不是显存，是内存

```
显存 8 GB 决定"模型能不能装下"
内存 24 GB 决定"能不能同时喂饱它"
```

实测：训练进程私有内存 **13~19 GB**；再叠加任何一次量化/加载（20 GB），
系统提交冲到 **42 GB / 上限 52 GB**，可用内存剩 **189 MB**——整机卡死。

**结论：这台机器上，任何两件吃内存的事不能同时做。**

### ② 顺序执行 > 加硬件

加内存要 4000~6000 元（2026 年行情，两条 32GB DDR5 已涨到 2000~3000 一条）。
而"训练、量化、评测一个做完再做下一个"，成本是 0。

### ③ 每条"更快"的结论都要能复现

速度类结论必须遵守测量协议（见 `docs/测量协议.md`）：
控制磁盘 I/O、后台进程、丢弃 warmup 步、同 seq/batch、记录温度功耗。
**没按协议测出来的数字，只能叫"观察值"。**

---

## 一、硬件基线

| 项目 | 值 |
|---|---|
| GPU | RTX 5070 Laptop 8 GB（GB206，GDDR7 三星，128-bit，384 GB/s） |
| 显存频率 | 12001 MHz（= 1500 MHz GPU-Z = 24 Gbps）；驱动省电档会掉到 9001 |
| CPU | Ryzen 9 7845HX，12 核 24 线程 |
| 内存 | 24 GB DDR5-4800（2 槽已满） |
| 系统 | Windows 11，驱动 621.24 |

---

## 二、训练：QLoRA 微调 4B 模型

### 能跑通的配置

```bash
python train_qlora_e4b.py \
  --model <HF格式模型目录> \
  --data  <messages格式 jsonl> \
  --out   <输出目录> \
  --steps 504 --bs 1 --seq 512 \
  --save-steps 3 --duty 0.97
```

| 项目 | 设置 |
|---|---|
| 量化 | 4bit NF4（bitsandbytes） |
| LoRA | r=16，target 显式列表（见坑 2） |
| 序列 | 512（768 会贴边） |
| batch | 1，梯度累积 8 |
| 梯度检查点 | 开 |
| 显存占用 | 约 7.6 GB / 8 GB |

### 实测速度

| 配置 | 秒/步 | 备注 |
|---|---|---|
| duty 0.97 | **117~155** | 当前配置，最快且稳定 |
| duty 0.93 | 128.6 | 稳 |
| duty 1.00（满载） | 105 → 150 | 后段被驱动节流拖慢 |
| 4 线程（默认） | 128 | 最优 |
| 12 物理核线程 | 209 | 慢 62%（观察值，与另一实验混跑，未完成对照） |
| 4 核 + 预 tokenize | 158 | 慢 23%（同上，未完成对照） |

**504 步全程约 17~18 小时**（按 120~130 秒/步）。

### 四个致命坑

#### 坑 1：`paged_adamw_8bit` 保存优化器状态会死锁

```
现象：存盘时卡死，GPU 0%、磁盘 0 MB/s，Kill 不掉，只能重启
解法：TrainingArguments(save_only_model=True)
     只存 adapter（约 170 MB），不存 optimizer
     续训用 --init-adapter 热启动（优化器重置）
```

#### 坑 2：4bit 之后 LoRA 挂错层，训练"成功"但没学到

```
现象：loss 正常下降，推理效果与裸模型一样
原因：bnb 把 nn.Linear 包成 ClippableLinear(linear=Linear4bit)
      PEFT 正则 .*\.linear$ 匹配不到 → target_modules 静默为空
检查：训完打印可训练张量数，必须 > 0
修法：先拆包装（把父模块 leaf 换成 mod.linear），再挂显式 target_modules：
      q_proj k_proj v_proj o_proj gate_proj up_proj down_proj
      per_layer_input_gate per_layer_projection
```

#### 坑 3：`save_only_model` 属于 TrainingArguments，不是 Trainer

```python
❌ Trainer(..., save_only_model=True)        # TypeError
✅ TrainingArguments(..., save_only_model=True)
```

#### 坑 4：transformers 5.x 没有 `warmup_ratio`

```
改用 warmup_steps（总步数 × 比例，自己算）
```

---

## 三、推理：35B MoE 在 8 GB 显存上跑

### 思路

MoE 模型（如 Qwen3.5-35B-A3B）总参 35B、每次只激活 3B。
用 `--n-cpu-moe N` 把 N 层专家放内存，其余层放显存：

```bash
llama-cli -m model-Q4_K_M.gguf -ngl 99 --n-cpu-moe 30 -p "你好" -n 64
```

`--n-cpu-moe` 越大 → 显存越省、速度越慢。

### 模型准备（Q4_K_M）

```bash
# ① HF 权重 → BF16 GGUF（需要在 llama.cpp 源码目录下运行，否则缺 conversion 模块）
cd llama.cpp-master
python convert_hf_to_gguf.py <模型目录> --outfile out-bf16.gguf --outtype bf16

# ② 量化
llama-quantize.exe out-bf16.gguf out-Q4_K_M.gguf Q4_K_M

# ③ 量化完删 BF16 中间件（71 GB）
```

实测：71.9 GB 权重 → BF16 GGUF 71.07 GB（23.7 分钟）→ Q4_K_M **20.22 GB**。

**注意：NVFP4 / NVFP8 用不了**——那是 TensorRT-LLM 生态，llama.cpp 只支持到 MXFP4。

### 冒烟测试的内存陷阱

```
加载 20 GB 模型时，如果训练还在跑（占 13~19 GB）
→ 内存必爆，llama-cli 返回码 -1（看起来像模型坏了，其实是 OOM）
→ 必须等训练结束再试
```

---

## 四、监控：别靠肉眼看

`watchdog/hardware_watchdog.py`：每 60 秒采一次，越线写告警日志。

```python
TH = {
    "gpu_temp_max": 70,
    "mem_clock_low": 10000,   # 利用率>80% 且显存<10000 → 被节流
    "power_max": 45,
    "cpu_clock_low": 2000,
    "cpu_load_gate": 30,
    "cpu_temp_max": 70,
}
```

**两个坑**：
- `temperature.gpu` 返回浮点（44.16），`int()` 会抛异常
- AMD 平台读不到 CPU 温度（WMI 热区为空、Get-Counter 无实例），需装 LibreHardwareMonitor

---

## 五、性能现象与解释（别误判）

| 现象 | 容易误判成 | 实际原因 |
|---|---|---|
| 训练突然变慢 30% | 超频不稳 | 后台在下载/量化，抢磁盘与内存 |
| 显存频率从 12001 掉到 9001 | 硬件故障 | 驱动满载时的省电/保护档 |
| 满载（duty 1.0）比 0.97 慢 | 玄学 | 满载触发驱动节流，反而降频 |
| llama-cli 返回 -1 | 模型损坏 | 内存不足 |

**记一条**：显存 9001 vs 12001 对训练速度影响 **< 10%**——瓶颈不在带宽。

---

## 六、可直接抄的清单

```
□ 训练用 save_only_model=True，save_steps 小（3~10），蓝屏最多丢几分钟
□ 训练前先跑 1 步丢弃，再测稳态速度
□ 任何"更快"的改动，一次只改一个变量
□ 量化/加载大模型前，先停训练（内存）
□ 温度、功耗、显存频率同时记录，只看一个指标会误判
□ 结论写进文件并标日期；不确定的标「观察值，未验证」
```

---

## 七、还没验证的（诚实标注）

- 12 核线程 / 预分词 的完整对照实验（当时两变量混跑，作废）
- 超频（+270 MHz / 1.05 V）对训练速度的真实影响（测时后台有下载）
- `--n-cpu-moe` 的最优值（待测，计划 10/20/30 扫描）
- 推测解码（EAGLE3 / MTP）在本机的收益

---

## 八、为什么写这个

因为绝大多数人手上的机器就是 **8 GB 显存 + 24 GB 内存**。
网上教程写的是"我有 4090 所以能跑"，而这里写的是"我只有这些，所以这么绕过去"。

**限制不是终点，是方法的起点。**
