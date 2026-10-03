#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-04 · 第七发：把"记忆分家"那几条体检补上

上一发（e）我推上去的那份，功能是全的，但我在本地给记忆分家写的那几条体检没跟着上去。
体检少了几条，门就松了 —— 这一发只干这一件事：把那几条钉回去。

（这一发里一个反斜杠都没有：SQL 用参数 ? 传，不拼字符串。今天已经在转义上栽两回了。）
"""
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

MEM_TEST = '''c, d = req(base, "/api/memory", {"scope": "her", "owner": "yume", "always": 1,
                                       "title": "她", "body": "体检·关于她的·常在"})
chk("关于她的记忆存得进", d.get("ok"), d)
c, d = req(base, "/api/memory?scope=her")
chk("潮汐捕梦那一栏读得到",
    any("关于她的" in (m.get("body") or "") for m in d.get("memory", [])), str(d)[:150])
c, d = req(base, "/api/memory?scope=me")
chk("星河那一栏里没有她的（分家了）",
    not any("关于她的" in (m.get("body") or "") for m in d.get("memory", [])), str(d)[:150])
c, d = req(base, "/api/memory")
lv = [m.get("layer") for m in d.get("memory", [])]'''

PREFIX_TEST = '''_ck = _c.execute("SELECT COUNT(*) FROM chat WHERE who=? AND ctx<>?", ("yume",)).fetchone()[0]
# 关于她"常在"的那条，得在稳的前缀里（不在前缀里就等于白记）
_h = _c.execute("SELECT COUNT(*) FROM memory WHERE scope=? AND always=1", ("her",)).fetchone()[0]
chk("关于她·常在 的条数读得到", _h >= 1, _h)
_c.close()
_code3 = ("import json, hub; ms = hub.build_messages(%s); "
          "print(json.dumps(ms[0][chr(99)+chr(111)+chr(110)+chr(116)+chr(101)+chr(110)+chr(116)], "
          "ensure_ascii=False))" % json.dumps("体检"))
_r4 = subprocess.run([sys.executable, "-c", _code3], cwd=tmp, capture_output=True, text=True)
chk("「关于她·常在」进了最前面那条 system",
    "关于她" in (_r4.stdout or ""), (_r4.returncode, (_r4.stdout or "")[:120]))
_c = _sq.connect(os.path.join(tmp, "cove.db"))'''

EDITS = {
    "test_cove.py": [
        ('c, d = req(base, "/api/memory")\nlv = [m.get("layer") for m in d.get("memory", [])]',
         MEM_TEST),
        ("_ck = _c.execute(\"SELECT COUNT(*) FROM chat WHERE who='yume' AND ctx<>''\").fetchone()[0]",
         PREFIX_TEST),
    ],
}

VER_FILES = {"VERSION": "2026-10-04f\n"}


def fail(msg):
    print("  ✗ " + msg)
    print("  整体不动，一个字都没改。")
    sys.exit(1)


def main():
    print("先在记忆里改一遍，全对上了才落盘")
    for name, pairs in EDITS.items():
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            fail("找不到 " + name)
        text = open(path, encoding="utf-8").read()
        before = text
        for pair in pairs:
            old, new = pair[0], pair[1]
            n = text.count(old)
            if n != 1:
                fail("%s 里这处对不上（该有 1 次，找到 %d 次）：\n%s" % (name, n, old[:160]))
            text = text.replace(old, new)
        if text == before:
            fail(name + " 一个字都没变")
        shutil.copy2(path, path + ".bak")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print("  ok   %s  补上了（%d → %d 字节）" % (name, len(before), len(text)))
    for name, text in VER_FILES.items():
        with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
            f.write(text)
    print("  写下去了")

    bad = []
    for name in ("hub.py", "llm.py", "rooms.py", "websearch.py", "test_cove.py",
                 "mcp_stdio.py", "mcpclient.py"):
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
    print("  python 语法过了")


if __name__ == "__main__":
    main()
