#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断包体检：检查 01~06 + 三张纸 是否齐全、关键字段是否缺失。

用法：
    python check_package.py <诊断包目录>

输出：PASS / WARN / FAIL 清单；有 FAIL 时退出码 1。
"""

import argparse
import glob
import os
import re
import sys

REQUIRED = {
    "01": ("方向", ["CBI", "基线", "目标", "口径", "责任"]),
    "02": ("现状图", ["触发", "终点"]),
    "03": ("断点", ["类型", "影响"]),
    "04": ("改造", ["消除", "简化", "合并", "并行"]),
    "05": ("指标链", ["M1", "M2", "M3"]),
    "06": ("治理", ["流程责任人", "评审|检视"]),
}

CJK = re.compile(r"[\u4e00-\u9fff]")


def find_file(directory, prefix):
    hits = sorted(glob.glob(os.path.join(directory, prefix + "_*.md")))
    return hits[0] if hits else None


def read(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def check_rows(text, min_rows=3):
    rows = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    rows = [r for r in rows if not re.match(r"^\|[\s:\-|]+\|?$", r.strip())]
    return max(0, len(rows) - 1)  # 去掉表头


# 六动作的标准写法，以及同义词归一化
ACTION_ALIASES = {
    "消除": "消除", "取消": "消除",
    "简化": "简化",
    "合并": "合并",
    "并行": "并行",
    "质量内置": "质量内置", "内置": "质量内置",
    "授权": "授权",
    "自动化": "自动化", "上系统": "自动化", "系统化": "自动化", "数字化": "自动化",
}


def action_column(text):
    """定位「动作」列的下标；认不出表头时默认第 2 列。"""
    for ln in text.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip().replace("*", "").strip() for c in s.strip("|").split("|")]
        for i, c in enumerate(cells):
            if c in ("动作", "改造动作", "动作类型", "类型", "六动作"):
                return i
    return 1


def action_words(text):
    """按出现顺序提取改造动作。

    只认表格的「动作」列（没有表格时退化为列表项开头），
    这样前言、引用块里提到的「自动化」不会影响顺序判断。
    """
    found = []
    col = action_column(text)

    for ln in text.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip().replace("*", "").strip() for c in s.strip("|").split("|")]
        if len(cells) <= col:
            continue
        cell = cells[col]
        for word, canon in ACTION_ALIASES.items():
            if cell.startswith(word):
                found.append(canon)
                break
    if found:
        return found

    # 退化：认 "- 消除 …" "1. 消除 …" 这类列表项
    for ln in text.splitlines():
        s = re.sub(r"^\s*(?:[-*+]|\d+[.)、])\s*", "", ln).replace("*", "")
        for word, canon in ACTION_ALIASES.items():
            if s.startswith(word):
                found.append(canon)
                break
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("package", help="诊断包目录")
    ap.add_argument("--min-disconnects", type=int, default=5)
    args = ap.parse_args()

    d = args.package
    fails, warns, oks = [], [], []

    if not os.path.isdir(d):
        print("FAIL 目录不存在: %s" % d)
        return 1

    texts = {}
    for prefix, (label, keywords) in REQUIRED.items():
        path = find_file(d, prefix)
        if not path:
            fails.append("%s_%s.md 缺失" % (prefix, label))
            continue
        text = read(path)
        texts[prefix] = text
        missing = [k for k in keywords if not re.search(k, text)]
        if missing:
            fails.append("%s_%s.md 缺关键词: %s" % (prefix, label, "、".join(missing)))
        else:
            oks.append("%s_%s.md 关键字段齐全" % (prefix, label))

    # 02 现状图：要有 mermaid
    if "02" in texts and "```mermaid" not in texts["02"]:
        warns.append("02_现状图.md 没有 mermaid 图块（用图片也可以，但要说明）")

    # 03 断点：条数与类型
    if "03" in texts:
        n = check_rows(texts["03"])
        if n < args.min_disconnects:
            fails.append("03_断点清单.md 只有 %d 条断点（要求 ≥%d）" % (n, args.min_disconnects))
        else:
            oks.append("03_断点清单.md 共 %d 条断点" % n)
        types = ["多余", "缺失", "顺序", "说不清", "指错"]
        if not any(t in texts["03"] for t in types):
            warns.append("03_断点清单.md 没有标注断点类型（五类之一）")
        if not re.search(r"年化|[0-9]+\s*万|元/年", texts["03"]):
            fails.append("03_断点清单.md 没有年化影响估算（没有数字的断点不算断点）")

    # 04 改造：自动化不得作为第一条（只看动作列的顺序，不看全文词出现位置）
    if "04" in texts:
        acts = action_words(texts["04"])
        if not acts:
            warns.append("04_改造清单.md 未识别到「动作」列，无法校验顺序（建议按模板写「| 序 | 动作 | … |」）")
        elif acts[0] == "自动化":
            fails.append("04_改造清单.md 第一条就是「自动化」（铁律：先消除，再自动化；上系统不得作为第一条）")
        elif "自动化" in acts:
            idx = acts.index("自动化") + 1
            oks.append("04_改造清单.md 六动作顺序合规（%d 条，自动化排第 %d）" % (len(acts), idx))
            if "消除" not in acts[:idx - 1]:
                warns.append("04_改造清单.md 的「自动化」之前没有「消除」条目——确认本期确实没有可消除的环节")
        else:
            warns.append("04_改造清单.md 没有「自动化」条目；若本期不上系统可忽略")

    # 05 指标链：M2 必须挂 M1
    if "05" in texts:
        t = texts["05"]
        rows = []
        for ln in t.splitlines():
            s = ln.strip()
            if not re.match(r"^\|\s*M2-\d", s):
                continue
            cells = [c for c in s.strip("|").split("|")]
            if len(cells) >= 7:          # 指标行（含编号/指标/挂M1/因果/数据源/频率/基线/目标）
                rows.append(s)
        unlinked = [ln for ln in rows if not re.search(r"M1-\d", ln)]
        if rows and unlinked:
            fails.append("05_指标链.md 有 %d 条 M2 没挂到具体 M1" % len(unlinked))
        elif rows:
            oks.append("05_指标链.md 的 %d 条 M2 均已挂到 M1" % len(rows))
        if not re.search(r"口径|定义", t):
            warns.append("05_指标链.md 缺口径/定义列，验收时容易吵")

    # 三张纸
    tp = None
    for cand in ("三张纸.md", "3papers.md", "三页纸.md"):
        p = os.path.join(d, cand)
        if os.path.exists(p):
            tp = p
            break
    if not tp:
        fails.append("三张纸.md 缺失")
    else:
        t = read(tp)
        for kw in ("诊断", "流程", "价值"):
            if kw not in t:
                fails.append("三张纸.md 缺少「%s」页" % kw)
        if len(t) > 8000:
            warns.append("三张纸.md 超过 8000 字（三页纸应一屏能讲完）")
        else:
            oks.append("三张纸.md 篇幅合适（%d 字）" % len(t))

    # 输出
    print("=" * 48)
    print("诊断包体检：%s" % os.path.abspath(d))
    print("=" * 48)
    for x in oks:
        print("[PASS] " + x)
    for x in warns:
        print("[WARN] " + x)
    for x in fails:
        print("[FAIL] " + x)
    print("-" * 48)
    print("PASS %d / WARN %d / FAIL %d" % (len(oks), len(warns), len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
