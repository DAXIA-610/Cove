#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-03 · 第三发：私语那条消息的账（照她给的写法）

她说：点我的消息，弹出抽屉，占半个屏幕，最上面是消耗的 token：

    T232.5K tokens (232.3K cached  759 tokens 46.7 tok/s 16.3s)

然后下面是思考链和调取工具的记录。

抽屉的骨架上一发已经有了，这一发只改格式和名字：
  · 高度 58% → 52%（她说半个屏幕）
  · 顶上那行照她的写法排：大号 T… tokens，括号里 cached / 回了多少 / tok/s / 秒数
  · 括号下面一行小字：未命中 / 模型 / 几轮 / 带了几张图
  · 「动过的手」→「调 取 的 工 具」，「想过什么」→「思 考 链」
"""
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

EDITS = {
    "index.html": [
        # 半个屏幕
        ('  .drawer{width:100%;height:58%;background:#fff;color:#0d3247;border-radius:24px 24px 0 0;',
         '  .drawer{width:100%;height:52%;background:#fff;color:#0d3247;border-radius:24px 24px 0 0;'),
        # 顶上那行，照她的写法
        ("""    $("metaTop").innerHTML =
      '<div class="big">T' + kfmt(pt) + ' tokens</div>' +
      '<div class="sub">命中 ' + kfmt(hit) + '　未命中 ' + kfmt(miss) + '</div>' +
      '<div class="sub">回了 ' + kfmt(ct) + ' tokens　' +
      tps.toFixed(1) + ' tok/s　' + sec + 's</div>' +
      '<div class="sub">' + esc(m.model || "") +
      (m.rounds ? '　' + m.rounds + ' 轮' : '') +
      (m.images ? '　带了 ' + m.images + ' 张图' : '') + '</div>';""",
         """    $("metaTop").innerHTML =
      '<div class="big">T' + kfmt(pt) + ' tokens</div>' +
      '<div class="sub">（' + kfmt(hit) + ' cached　' + kfmt(ct) + ' tokens　' +
      tps.toFixed(1) + ' tok/s　' + sec + 's）</div>' +
      '<div class="sub">未命中 ' + kfmt(miss) + '　' + esc(m.model || "") +
      (m.rounds ? '　' + m.rounds + ' 轮' : '') +
      (m.images ? '　带了 ' + m.images + ' 张图' : '') + '</div>';"""),
        # 名字照她说：调取工具的记录 + 思考链
        ("      b += '<div class=\"h\">动 过 的 手</div><div>' +",
         "      b += '<div class=\"h\">调 取 的 工 具</div><div>' +"),
        ("      b += '<div class=\"h\">想 过 什 么</div><div class=\"t\">' + esc(m.think) + '</div>';",
         "      b += '<div class=\"h\">思 考 链</div><div class=\"t\">' + esc(m.think) + '</div>';"),
        # 账里那几行小字，把"没记账"也说清楚点
        ("        '<div class=\"sub\">那会儿还没开始记。往后新说的每一句都会带上。</div>';",
         "        '<div class=\"sub\">那会儿还没开始记账。往后新说的每一句都会带上。</div>';"),
    ],
}

VER_FILES = {"VERSION": "2026-10-03c\n"}


def fail(msg):
    print("  ✗ " + msg)
    print("  整体不动，一个字都没改。")
    sys.exit(1)


def main():
    print("先在记忆里改一遍，全对上了才落盘")
    staged = {}
    for name, pairs in EDITS.items():
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            fail("找不到 " + name)
        text = open(path, encoding="utf-8").read()
        before = text
        for pair in pairs:
            old, new = pair[0], pair[1]
            want = pair[2] if len(pair) > 2 else 1
            n = text.count(old)
            if n != want:
                fail("%s 里这处对不上（该有 %d 次，找到 %d 次）：\n%s"
                     % (name, want, n, old[:160]))
            text = text.replace(old, new)
        if text == before:
            fail(name + " 一个字都没变，写错了")
        staged[name] = text
        print("  ok   %s  %d 处" % (name, len(pairs)))

    for name, text in staged.items():
        path = os.path.join(ROOT, name)
        shutil.copy2(path, path + ".bak")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    for name, text in VER_FILES.items():
        with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
            f.write(text)
    print("  写下去了")

    bad = []
    for name in ("hub.py", "llm.py", "rooms.py", "websearch.py", "test_cove.py"):
        path = os.path.join(ROOT, name)
        try:
            py_compile.compile(path, doraise=True, cfile=path + ".pyc")
        except Exception as e:
            bad.append("%s: %s" % (name, e))
        finally:
            if os.path.exists(path + ".pyc"):
                os.remove(path + ".pyc")
    if bad:
        for name in staged:
            p = os.path.join(ROOT, name)
            if os.path.exists(p + ".bak"):
                shutil.move(p + ".bak", p)
        fail("语法没过：\n" + "\n".join(bad))
    print("  语法过了")


if __name__ == "__main__":
    main()
