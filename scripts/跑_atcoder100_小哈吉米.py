# -*- coding: utf-8 -*-
"""AtCoder 100 题判分：让本地克劳德写 Python3，真跑样例，失败回传重试。

用法：
  python 跑_atcoder100.py [--start N] [--end M] [--max-rounds 3]

依赖：llama-server 已在 127.0.0.1:8096 起来（脚本外部启动）
输出：D:\\大肥鱼专用\\实验\\atcoder100_results.jsonl（每题一行，可断点续跑）
"""
import argparse
import json
import io
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BENCH = r"C:\Users\11382\Desktop\小工具\AI\试题基准_完整.json"
OUT = r"D:\大肥鱼专用\实验\atcoder100_xiaohajimi.jsonl"
ENDPOINT = "http://127.0.0.1:8097/v1/chat/completions"


def ask(prompt: str, max_tokens=1200, temp=0.0, timeout=600) -> str:
    body = json.dumps({
        "model": "claude",
        "messages": [{"role":"system","content":"你是代码生成器，只输出代码本身，不输出任何解释、序号或英文思考。"},{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temp,
    }).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    msg = data["choices"][0]["message"]
    return (msg.get("content") or msg.get("reasoning_content") or "").strip()


def extract_code(text: str) -> str:
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.S | re.I)
    code = m.group(1) if m else text
    lines = code.splitlines()
    start = 0
    for i, ln in enumerate(lines):
        t = ln.strip()
        if (t.startswith(("import ", "from ", "def ", "#"))
                or re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", t)):
            start = i
            break
    return "\n".join(lines[start:]).strip()


def normalize(s: str) -> str:
    lines = [ln.rstrip() for ln in s.replace("\r\n", "\n").strip().split("\n")]
    return "\n".join(lines).strip()


def run_case(code: str, inp: str, timeout=10):
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, "sol.py")
        io.open(f, "w", encoding="utf-8").write(code)
        try:
            p = subprocess.run([sys.executable, f], input=inp.encode("utf-8"),
                               capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, "", "超时（>%ds）" % timeout
        out = p.stdout.decode("utf-8", errors="replace")
        err = p.stderr.decode("utf-8", errors="replace")
        return p.returncode == 0, out, err


def judge(code: str, samples):
    """返回 (是否全过, 第一条失败的说明)"""
    if not samples:
        return None, "无样例，无法验证"
    for i, s in enumerate(samples, 1):
        ok, out, err = run_case(code, s["input"])
        if not ok:
            return False, f"样例{i} 运行错误: {err.strip()[:300]}"
        if normalize(out) != normalize(s["output"]):
            return False, (f"样例{i} 输出不符\n输入:\n{s['input'][:200]}\n"
                           f"期望:\n{s['output'][:200]}\n实际:\n{out[:200]}")
    return True, ""


def build_prompt(p, feedback: str = "") -> str:
    samples_txt = "\n".join(
        f"输入:\n{s['input']}\n输出:\n{s['output']}\n---" for s in p.get("samples", [])[:3]
    )
    base = f"""你在做 AtCoder 编程题。用 Python3 写一个完整程序：从标准输入读，向标准输出写。

题目：{p['title']}（难度 {p['difficulty']}/5）

题干：
{p['statement'][:6000]}

样例：
{samples_txt}

要求：
1) 只输出一个 ```python 代码块，不要解释；
2) 程序必须能处理题目给的全部约束（注意大输入、多组数据）；
3) 用 sys.stdin 读入、print 输出。
"""
    if feedback:
        base += f"\n上一次提交失败了：\n{feedback}\n请修正后重新给出完整代码。\n"
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=100)
    ap.add_argument("--max-rounds", type=int, default=3)
    args = ap.parse_args()

    bench = json.load(io.open(BENCH, encoding="utf-8"))
    problems = bench["problems"]

    done = set()
    if os.path.exists(OUT):
        for line in io.open(OUT, encoding="utf-8"):
            try:
                done.add(json.loads(line)["id"])
            except Exception:
                pass
    print(f"已完成 {len(done)} 题，本次跑 {args.start}-{args.end}", flush=True)

    for i, p in enumerate(problems, 1):
        if i < args.start or i > args.end or p["id"] in done:
            continue
        t0 = time.time()
        feedback, passed, attempts = "", None, 0
        last_err = ""
        for r in range(1, args.max_rounds + 1):
            attempts = r
            try:
                reply = ask(build_prompt(p, feedback))
            except Exception as e:
                last_err = f"模型调用失败: {e}"
                break
            code = extract_code(reply)
            passed, err = judge(code, p.get("samples", []))
            if passed is None:
                last_err = err
                break
            if passed:
                break
            feedback = err
            last_err = err

        rec = {
            "id": p["id"], "title": p["title"], "difficulty": p["difficulty"], "tier": p["tier"],
            "passed": bool(passed), "attempts": attempts,
            "seconds": round(time.time() - t0, 1), "last_error": last_err[:500] if not passed else "",
        }
        io.open(OUT, "a", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False) + "\n")
        mark = "PASS" if passed else ("SKIP" if passed is None else "FAIL")
        print(f"[{i}/100] {p['id']} {mark} ｜ 轮次 {attempts} ｜ {rec['seconds']}s", flush=True)

    print("全部完成", flush=True)


if __name__ == "__main__":
    main()
