# -*- coding: utf-8 -*-
"""E4B（彩虹猫）编程骨架精调：纯文本 SFT，4bit QLoRA。

数据：train/data/train.jsonl（1053 条，MBPP+HumanEval，已与评测集去重、逐条验证）
目标：把代码能力钉进 LoRA，之后合并 + 量化成 Q6_K 当编程骨架。

已修的两个坑（2026-11-19）：
  · 跳过 prepare_model_for_kbit_training（那个 fp32 上采样要 10.5 GB，8 GB 必爆）
  · LoRA 目标用正则 .*\\.linear$（Gemma4ClippableLinear 包了一层，按名字挂不上）

用法：
  python qlora_coding_e4b.py --smoke     # 20 步冒烟
  python qlora_coding_e4b.py --steps 300 # 正式
"""
import argparse
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
# 2026-11-19 05:20 实测：默认开 94 线程抢一个样本，调度开销比干活还多
# 固定 4 线程；12 核 24 线程的 7845HX 上，训练只要 4 线程就够喂 GPU
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")

BASE = os.environ.get("FISH_HOME", os.path.expanduser("~/.dsh-fish"))
MODEL = os.path.join(BASE, r"models\gemma-4-E4B-it-hf")
DATA = os.path.join(BASE, r"train\data\train.jsonl")
OUT = os.path.join(BASE, r"train\out\e4b-coding-lora")
LOG = os.path.join(BASE, r"train\_coding_train.log")


def log(m):
    line = "%s %s" % (time.strftime("%H:%M:%S"), m)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    import torch as _t
    _t.set_num_threads(4)   # 同上：别让线程打群架
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--seq", type=int, default=768)
    ap.add_argument("--accum", type=int, default=8)
    ap.add_argument("--data", default=DATA, help="数据集 jsonl 路径")
    ap.add_argument("--out", default=OUT, help="LoRA 输出目录")
    ap.add_argument("--bs", type=int, default=1, help="per_device batch size")
    ap.add_argument("--resume", default="", help="从 checkpoint 目录续训")
    ap.add_argument("--init-adapter", default="", help="从这个适配器热启动（只加载权重，优化器重置）")
    ap.add_argument("--save-steps", type=int, default=3, help="每多少步存一次（冒烟时可调小以测保存）")
    ap.add_argument("--duty", type=float, default=1.0, help="GPU 占空比 0.1~1.0；0.7 表示只占七成，步间插空闲")
    ap.add_argument("--model", default=MODEL, help="HF 格式模型目录")
    ap.add_argument("--threads", type=int, default=0, help="CPU 线程数（0=沿用默认 4）")
    ap.add_argument("--pretok", default="", help="token 缓存文件路径（给了就预分词，省掉每步分词开销）")
    a = ap.parse_args()

    if a.threads and a.threads > 0:
        os.environ["OMP_NUM_THREADS"] = str(a.threads)
        os.environ["MKL_NUM_THREADS"] = str(a.threads)
        try:
            import torch as _torch_t
            _torch_t.set_num_threads(a.threads)
            log("CPU 线程数设为 %d（物理核口径，OMP/MKL 同步）" % a.threads)
        except Exception as e:
            log("设置线程数失败：%s" % e)

    if not os.path.isdir(a.model):
        log("缺 HF 权重：%s" % a.model)
        return 2

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import (TrainerCallback, AutoProcessor, BitsAndBytesConfig,
                              Gemma4ForConditionalGeneration, Trainer,
                              TrainingArguments)

    rows = [json.loads(l) for l in open(a.data, encoding="utf-8") if l.strip()]
    log("样本 %d 条" % len(rows))

    proc = AutoProcessor.from_pretrained(a.model)
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16,
                             bnb_4bit_use_double_quant=True)
    log("加载模型（4bit）")
    model = Gemma4ForConditionalGeneration.from_pretrained(
        a.model, quantization_config=bnb, device_map={"": 0},
        torch_dtype=torch.bfloat16)
    model.config.use_cache = False
    try:
        model.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False})
    except Exception:
        model.gradient_checkpointing_enable()
    try:
        model.enable_input_require_grads()
    except Exception:
        pass

    # 2026-11-19 12:35 实测：4bit 后文本层被包成 Gemma4ClippableLinear，
    # PEFT 不认它、正则 .*\.linear$ 也匹配不到（内层 linear 名字不可见），
    # 结果 LoRA 全长在 vision/audio 塔上，训练 5.5 小时白跑。
    # 修法：先把包装拆成内层 Linear4bit，再用显式层名。
    def _unwrap_clippable(m):
        n = 0
        for name, mod in list(m.named_modules()):
            if type(mod).__name__ == "Gemma4ClippableLinear" and getattr(mod, "linear", None):
                parts = name.split(".")
                parent = m
                ok = True
                for p in parts[:-1]:
                    if hasattr(parent, p):
                        parent = getattr(parent, p)
                    else:
                        ok = False
                        break
                if ok:
                    setattr(parent, parts[-1], mod.linear)
                    n += 1
        return n

    _n = _unwrap_clippable(model)
    log("拆掉 ClippableLinear 包装 %d 个" % _n)

    TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj",
               "down_proj", "per_layer_input_gate", "per_layer_projection"]
    lora = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias="none",
                      task_type="CAUSAL_LM", target_modules=TARGETS)
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()
    if getattr(a, "init_adapter", ""):
        try:
            model.load_adapter(a.init_adapter, adapter_name="default", is_trainable=True)
            log("热启动：已加载 %s 的适配器权重（优化器重新开始）" % a.init_adapter)
        except Exception as e:
            log("热启动失败（忽略，从头训）：%s" % e)
    _txt = [k for k, _ in model.named_parameters()
            if "lora_" in k and "vision" not in k and "audio" not in k]
    log("文本层 LoRA 张量 %d 个（必须 > 0，否则又是挂错）" % len(_txt))

    texts = []
    for r in rows:
        msgs = r["messages"]
        try:
            t = proc.apply_chat_template(msgs, tokenize=False)
        except Exception:
            continue
        texts.append(t)
    log("可训练样本 %d" % len(texts))

    # token 缓存（加速②）：把文本预先切好存盘，每步只读 id，不再重复分词
    ids_cache = None
    if a.pretok:
        if os.path.exists(a.pretok):
            ids_cache = []
            with open(a.pretok, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        ids_cache.append(json.loads(line)["ids"])
            log("已加载 token 缓存 %d 条：%s" % (len(ids_cache), a.pretok))
        else:
            tok_ = getattr(proc, "tokenizer", proc)
            t0c = time.time()
            ids_cache = []
            for t in texts:
                e_ = tok_(text=t, truncation=True, max_length=a.seq, padding=False)
                ids_cache.append(e_["input_ids"])
            os.makedirs(os.path.dirname(a.pretok), exist_ok=True)
            with open(a.pretok, "w", encoding="utf-8") as f:
                for ids in ids_cache:
                    f.write(json.dumps({"ids": ids}) + "\n")
            log("token 缓存已建 %d 条，用时 %.1f 秒 → %s" % (len(ids_cache), time.time() - t0c, a.pretok))

    class DS(torch.utils.data.Dataset):
        def __len__(self):
            return len(texts)

        def __getitem__(self, i):
            if ids_cache is not None:
                ids = torch.tensor(ids_cache[i], dtype=torch.long)
                return {"input_ids": ids, "labels": ids.clone(),
                        "attention_mask": torch.ones_like(ids)}
            e = proc(text=texts[i], return_tensors="pt", truncation=True,
                     max_length=a.seq, padding=False)
            ids = e["input_ids"][0]
            return {"input_ids": ids, "labels": ids.clone(),
                    "attention_mask": e["attention_mask"][0]}

    def collate(batch):
        mx = max(b["input_ids"].shape[-1] for b in batch)
        out = {}
        for k in ("input_ids", "labels", "attention_mask"):
            pad = -100 if k == "labels" else 0
            out[k] = torch.stack([
                torch.nn.functional.pad(b[k], (0, mx - b[k].shape[-1]), value=pad)
                for b in batch])
        return out

    args = TrainingArguments(
        output_dir=a.out,
        per_device_train_batch_size=a.bs,
        gradient_accumulation_steps=a.accum,
        max_steps=20 if a.smoke else a.steps,
        learning_rate=a.lr,
        logging_steps=1,
        save_steps=a.save_steps,   # 2026-11-19：蓝屏丢过 100 步，改成 50
        save_only_model=True,   # 2026-11-19：paged 优化器保存会卡死，只存适配器
        save_total_limit=2,
        gradient_checkpointing=True,
        bf16=True,
        optim="paged_adamw_8bit",
        lr_scheduler_type="cosine",
        warmup_steps=10,  # transformers 5.x 没有 warmup_ratio
        report_to=[],
        remove_unused_columns=False,
    )
    # 占空比控制：duty<1 时在每步之后插空闲，把 GPU 平均占用压到目标值
    class DutyCallback(TrainerCallback):
        def __init__(self, duty):
            self.duty = max(0.1, min(1.0, duty))
            self.t_last = None

        def on_step_begin(self, args, state, control, **kwargs):
            self.t_last = time.time()

        def on_step_end(self, args, state, control, **kwargs):
            if self.duty >= 0.999 or self.t_last is None:
                return
            busy = time.time() - self.t_last
            # 想要 busy/(busy+idle)=duty → idle = busy*(1-duty)/duty
            idle = busy * (1.0 - self.duty) / self.duty
            if idle > 0:
                time.sleep(min(idle, 120.0))

    callbacks = [DutyCallback(a.duty)] if a.duty < 0.999 else None
    if callbacks:
        log("GPU 占空比限制：%.0f%%（步间插空闲，训练时间会拉长）" % (a.duty * 100))

    tr = Trainer(model=model, args=args, train_dataset=DS(), data_collator=collate,
                 callbacks=callbacks)
    log("开始训练（%s）" % ("冒烟 20 步" if a.smoke else "%d 步" % a.steps))
    t0 = time.time()
    tr.train(resume_from_checkpoint=(a.resume or None))
    log("训练结束 %.1f 分钟" % ((time.time() - t0) / 60))
    model.save_pretrained(a.out)
    proc.save_pretrained(a.out)
    log("适配器 → %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())