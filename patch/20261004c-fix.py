#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-04 · 补丁 c 的修丁（c 本体里有一处转义我推的时候走样了）

推上去的 patch/20261004c.py 里，那一行生成测试代码的字符串多了一个反斜杠：

    推上去的：  print(mcpclient.run(\\'根本没这只手\\', {}))
    应该是：    print(mcpclient.run(\'根本没这只手\', {}))     ← 这里写的是它在补丁里的样子

多了那一层，patch c 自己就编不过（CI 直接语法错，所以什么都没提交）。

这个文件排在 c 前面跑（名字里那个横杠比点小），只做三件事：
  ① 把多出来的那一个反斜杠去掉
  ② 把 index.html 里 mcpLine2 那行折成两行（跟本地验过的那份一致）
  ③ 把 docstring 里"图二"那句补全

改完立刻把它编译一遍 —— 编不过就整体失败，绝不提交一个坏的补丁。
"""
import os
import py_compile
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
TARGET = os.path.join(BASE, "20261004c.py")

FIXES = [
    # ① 转义：多一层反斜杠 → 少一层
    ("print(mcpclient.run(\\\\'根本没这只手\\\\', {}))",
     "print(mcpclient.run(\\'根本没这只手\\', {}))"),
    # ② 那行折成两行
    ('  $("mcpLine2").textContent = mcpList.length ? ("接着 " + on.length + " 台。") : "";',
     '  $("mcpLine2").textContent = mcpList.length\n'
     '    ? ("接着 " + on.length + " 台。")\n'
     '    : "";'),
    # ③ 补一句
    ("    图二 编辑页：启用开关 / 名称 / 传输类型 / 服务器地址 / 自定义请求头 / 保存",
     "    图二 编辑页：启用开关 / 名称 / 传输类型（Streamable HTTP｜SSE）/ 服务器地址 / 自定义请求头 / 保存"),
]


def main():
    if not os.path.exists(TARGET):
        print("  ✗ 找不到 patch/20261004c.py —— 它已经被并进去了，这个修丁没用，跳过")
        return
    text = open(TARGET, encoding="utf-8").read()
    for old, new in FIXES:
        n = text.count(old)
        if n != 1:
            print("  ✗ 这一处对不上（该有 1 次，找到 %d 次）：%s" % (n, old[:80]))
            sys.exit(1)
        text = text.replace(old, new)
        print("  ok   修了一处")

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(text)

    # 修完必须编得过 —— 这就是刚才挂掉的原因，不许再犯
    try:
        py_compile.compile(TARGET, doraise=True, cfile=TARGET + ".pyc")
    except Exception as e:
        print("  ✗ 修完还是编不过：%s" % e)
        sys.exit(1)
    finally:
        if os.path.exists(TARGET + ".pyc"):
            os.remove(TARGET + ".pyc")
    print("  ok   patch/20261004c.py 修好了，编得过")


if __name__ == "__main__":
    main()
