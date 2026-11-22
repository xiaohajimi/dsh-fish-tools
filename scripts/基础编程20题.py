# -*- coding: utf-8 -*-
"""基础编程 20 题（写函数 + 跑断言）

测试格式统一为：(参数元组, 期望值)
"""
import argparse
import io
import json
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TASKS = [
    ("two_sum", "写函数 two_sum(nums, target)，返回和为 target 的两个下标（列表）。",
     [(([2, 7, 11, 15], 9), [0, 1]), (([3, 2, 4], 6), [1, 2])]),
    ("reverse_str", "写函数 reverse_str(s)，返回反转后的字符串。",
     [(("abc",), "cba"), (("",), "")]),
    ("is_palindrome", "写函数 is_palindrome(s)，忽略大小写和非字母数字，判断是否回文。",
     [(("A man, a plan, a canal: Panama",), True), (("abc",), False)]),
    ("fizzbuzz", "写函数 fizzbuzz(n)，返回 1..n 的列表，3 的倍数用 'Fizz'，5 的倍数用 'Buzz'，15 用 'FizzBuzz'。",
     [((5,), [1, 2, "Fizz", 4, "Buzz"])]),
    ("word_count", "写函数 word_count(text)，返回单词频次字典（按空格切分，小写）。",
     [(("a b a",), {"a": 2, "b": 1})]),
    ("binary_search", "写函数 binary_search(arr, x)，升序数组里找 x 的下标，找不到返回 -1。",
     [(([1, 3, 5, 7], 5), 2), (([1, 3], 2), -1)]),
    ("merge_sorted", "写函数 merge_sorted(a, b)，合并两个升序列表并保持升序。",
     [(([1, 3], [2, 4]), [1, 2, 3, 4])]),
    ("dedup_order", "写函数 dedup_order(lst)，去重并保持原顺序。",
     [(([1, 2, 1, 3],), [1, 2, 3])]),
    ("roman_to_int", "写函数 roman_to_int(s)，罗马数字转整数。",
     [(("III",), 3), (("IX",), 9), (("MCMXCIV",), 1994)]),
    ("max_subarray", "写函数 max_subarray(nums)，返回最大子数组和（允许负数）。",
     [(([-2, 1, -3, 4, -1, 2, 1, -5, 4],), 6)]),
    ("is_anagram", "写函数 is_anagram(a, b)，判断两个字符串是否字母异位。",
     [(("anagram", "nagaram"), True), (("rat", "car"), False)]),
    ("count_vowels", "写函数 count_vowels(s)，统计元音字母个数（aeiou，忽略大小写）。",
     [(("Hello World",), 3)]),
    ("second_largest", "写函数 second_largest(nums)，返回第二大（去重后），不足返回 None。",
     [(([1, 3, 3, 2],), 2), (([5],), None)]),
    ("flatten", "写函数 flatten(lst)，把嵌套列表拉平（一层）。",
     [(([1, [2, 3], 4],), [1, 2, 3, 4])]),
    ("caesar", "写函数 caesar(s, k)，字母右移 k 位（只处理字母，保留大小写）。",
     [(("abc", 1), "bcd"), (("xyz", 3), "abc")]),
    ("valid_brackets", "写函数 valid_brackets(s)，判断括号是否配对（()[]{}）。",
     [(("()[]{}",), True), (("(]",), False)]),
    ("gcd_list", "写函数 gcd_list(nums)，返回所有数的最大公约数。",
     [(([12, 18, 24],), 6)]),
    ("majority", "写函数 majority(nums)，返回出现次数超过一半的元素（保证存在）。",
     [(([2, 2, 1, 2],), 2)]),
    ("title_case", "写函数 title_case(s)，每个单词首字母大写、其余小写。",
     [(("hello world",), "Hello World")]),
    ("days_between", "写函数 days_between(d1, d2)，两个 'YYYY-MM-DD' 字符串相差天数（绝对值）。",
     [(("2024-01-01", "2024-01-11"), 10)]),
]


def ask(prompt, url, max_tokens=700):
    body = {"model": "coder", "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0.0}
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read().decode())
    m = d["choices"][0]["message"]
    return (m.get("content") or m.get("reasoning_content") or "").strip()


def extract_code(text):
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S | re.I)
    return (m.group(1) if m else text).strip()


def run_tests(code, fn, tests):
    ns = {}
    try:
        exec(code, ns)
    except Exception as e:
        return False, f"代码无法执行: {e}"
    if fn not in ns:
        return False, f"没有定义 {fn}"
    for args, expected in tests:
        try:
            got = ns[fn](*args)
        except Exception as e:
            return False, f"调用出错: {e}"
        if got != expected:
            return False, f"{args} → 期望 {expected}，实得 {got}"
    return True, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8096")
    ap.add_argument("--out", default=r"D:\大肥鱼专用\实验\基础编程20题.json")
    args = ap.parse_args()

    results = []
    for name, desc, tests in TASKS:
        t0 = time.time()
        base = f"""用 Python3 实现：{desc}
只输出一个 ```python 代码块，函数名必须是 {name}，不要解释、不要测试代码。"""
        ok, err = False, ""
        for attempt in (1, 2):
            try:
                text = ask(base if attempt == 1 else base + f"\n上一次失败原因：{err}", args.url)
            except Exception as e:
                err = f"模型调用失败: {e}"
                break
            ok, err = run_tests(extract_code(text), name, tests)
            if ok:
                break
        sec = round(time.time() - t0, 1)
        print(f"{'PASS' if ok else 'FAIL'} ｜ {name:<16} ｜ {sec}s" + ("" if ok else f" ｜ {err[:70]}"), flush=True)
        results.append({"name": name, "passed": ok, "seconds": sec, "error": err})

    n = len(results)
    p = sum(1 for r in results if r["passed"])
    print(f"\n合计 {p}/{n} = {p/n*100:.0f}%", flush=True)
    io.open(args.out, "w", encoding="utf-8").write(json.dumps(results, ensure_ascii=False, indent=1))
    print(f"结果写 {args.out}", flush=True)


if __name__ == "__main__":
    main()
