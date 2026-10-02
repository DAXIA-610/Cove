#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-03 · 第二发
------------------------
上一发把默认模型名从 `deepseek-chat` 改成了 `deepseek-flash`。
但要是她早先在「模型」那张抽屉里点过保存，settings 表里就存着一个旧名字 ——
那个名字比默认值大，会把默认值盖掉，等于白改。

所以这一发：读出来的时候就把已经下线的两个名字换成现在的名字。
以后 DeepSeek 再改名字，这里加一行就行。

规矩照旧：任何一处对不上，整体不动。
"""
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

EDITS = {
    "llm.py": [
        ('# 想加新家，就在这里多写一行。hub 只认 base + model 两个字段。',
         '# 已经下线的旧名字：谁要是还存着它，我们替他换掉，不去撞那堵墙\n'
         'DEAD_NAMES = ("deepseek-chat", "deepseek-reasoner", "deepseek-v3", "deepseek-r1")\n'
         '\n'
         '\n'
         'def fix_model(name):\n'
         '    """存着的老名字换成现在的名字。认不出就原样还回去。"""\n'
         '    n = (name or "").strip()\n'
         '    if not n:\n'
         '        return DEFAULT_MODEL\n'
         '    return DEFAULT_MODEL if n.lower() in DEAD_NAMES else n\n'
         '\n'
         '\n'
         '# 想加新家，就在这里多写一行。hub 只认 base + model 两个字段。'),
        ('    model = (model or DEFAULT_MODEL).strip()',
         '    model = fix_model(model)'),
    ],
    "hub.py": [
        # 两处都读模型名：压上下文那处 + 说话那处。两处都得换，不然压的时候还是撞旧名字。
        ('        model = get_setting(c, "model") or llm.DEFAULT_MODEL',
         '        model = llm.fix_model(get_setting(c, "model"))', 2),
    ],
    "test_cove.py": [
        ('chk("today 带着版本号", bool(d.get("version")) and d["version"] != "?", d.get("version"))',
         'chk("today 带着版本号", bool(d.get("version")) and d["version"] != "?", d.get("version"))\n'
         '\n'
         '# 默认模型名不能是已经下线的旧名字\n'
         'import llm as _llm\n'
         'chk("默认模型不是废名字", _llm.DEFAULT_MODEL not in _llm.DEAD_NAMES, _llm.DEFAULT_MODEL)\n'
         'chk("存着的旧名字会被换掉", _llm.fix_model("deepseek-chat") == _llm.DEFAULT_MODEL, _llm.fix_model("deepseek-chat"))\n'
         'chk("正常名字原样还回来", _llm.fix_model("deepseek-v4-pro") == "deepseek-v4-pro", _llm.fix_model("deepseek-v4-pro"))\n'
         'chk("空的就当没填，给默认", _llm.fix_model("") == _llm.DEFAULT_MODEL, _llm.fix_model(""))'),
    ],
}

VER_FILES = {"VERSION": "2026-10-03b\n"}


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
                     % (name, want, n, old[:120]))
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
    print("  写下去了，旧的都在 .bak 里")

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
        fail("语法没过，退回去了：\n" + "\n".join(bad))
    print("  语法过了")


if __name__ == "__main__":
    main()
