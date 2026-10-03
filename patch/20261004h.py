#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-04 · 第八发：修 g 里那一行 SQL（两个 ? 只给了一个值）

CI 挂了，我去 CI 的复现里跑了一遍，它自己指出了行号：

    File "test_cove.py", line 456
      _ck = _c.execute("SELECT COUNT(*) FROM chat WHERE who=? AND ctx<>?", ("yume",))
    sqlite3.ProgrammingError: Incorrect number of bindings supplied.
    The current statement uses 2, and there are 1 supplied.

两个占位符，只给了一个值 —— 补上第二个（空串）。

为什么本地没挂、CI 挂：我本地那份补丁 e 把这一条检查用另一种写法写过了，
g 是专门给 CI 补的，两边叠在一起就露了这个错。教训：
**"本地绿"跟"CI 绿"不是一回事 —— 要按 CI 的顺序在本地原样跑一遍才算验过。**
"""
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

OLD = '_ck = _c.execute("SELECT COUNT(*) FROM chat WHERE who=? AND ctx<>?", ("yume",)).fetchone()[0]'
NEW = '_ck = _c.execute("SELECT COUNT(*) FROM chat WHERE who=? AND ctx<>?", ("yume", "")).fetchone()[0]'

EDITS = {"test_cove.py": [(OLD, NEW)]}

VER_FILES = {"VERSION": "2026-10-04h\n"}


def fail(msg):
    print("  ✗ " + msg)
    print("  整体不动，一个字都没改。")
    sys.exit(1)


def main():
    for name, pairs in EDITS.items():
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            fail("找不到 " + name)
        text = open(path, encoding="utf-8").read()
        before = text
        for old, new in pairs:
            n = text.count(old)
            if n != 1:
                fail("%s 里这处对不上（该有 1 次，找到 %d 次）：\n%s" % (name, n, old[:140]))
            text = text.replace(old, new)
        if text == before:
            fail(name + " 一个字都没变")
        shutil.copy2(path, path + ".bak")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print("  ok   %s  修好了" % name)
    for name, text in VER_FILES.items():
        with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
            f.write(text)
    bad = []
    for name in ("test_cove.py",):
        path = os.path.join(ROOT, name)
        try:
            py_compile.compile(path, doraise=True, cfile=path + ".pyc")
        except Exception as e:
            bad.append("%s: %s" % (name, e))
        finally:
            if os.path.exists(path + ".pyc"):
                os.remove(path + ".pyc")
    if bad:
        fail("语法没过：\n" + "\n".join(bad))
    print("  语法过了")


if __name__ == "__main__":
    main()
