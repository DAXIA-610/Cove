#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-04 · 第四发：把页面救回来（一行 JS 少了转义，整个脚本崩了）

她来说：网页卡住了，进入页面和初始页面打架，还点不动。

这不是玄学，是**一处语法错**：前端那个 <script> 里有一行，我写补丁的时候写成了

        ... + esc(t.name) + "',this)"></button></div>";

里面的引号没转义，字符串提前结束了，后面那些 `<` `/` 就成了语法错。
脚本一崩：门牌那一层（.splash）永远收不掉 → 它盖在首页上 → 看起来就是"两层打架"，
而且整页都点不动（事件全绑在那些没跑起来的函数上）。

我是拿 node --check 把它揪出来的（不是猜）：
    app.js:1153  SyntaxError: Unexpected token '<'

这一发做两件：
  ① 把那行改写成不需要转义的形式（拼接，不玩反斜杠）
  ② **给体检脚本加一条**：把前端 JS 抠出来交给 node --check —— 以后这种错在推之前就会被拦住

顺便记住教训：补丁脚本里凡是往 JS/CSS 里写反斜杠，都要过 node --check，
因为"补丁自己编译得过"跟"生成出来的前端是对的"是两件事。
"""
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

BAD = """      '" onclick="mcpToggleApprove(' + "'" + esc(t.name) + "',this)"></button></div>";"""

GOOD = """      '" onclick="mcpToggleApprove(' + "'" + esc(t.name) + "',this)" +
      '></button></div>';"""

JS_CHECK = '''# 前端脚本的语法：交给真的解析器看（这一条是真事故换来的 —— 
# 有一行 JS 少了转义，整个脚本崩了，门牌那层收不掉，页面点不动还点不了）
import tempfile as _tf
_m = re.search(r"<script>(.*)</script>", html, re.S)
chk("前端能抠出 <script>", bool(_m), "")
if _m:
    _jsp = os.path.join(_tf.gettempdir(), "cove_app_check.js")
    with open(_jsp, "w", encoding="utf-8") as _f:
        _f.write(_m.group(1))
    if shutil.which("node"):
        _r = subprocess.run(["node", "--check", _jsp], capture_output=True, text=True)
        chk("前端 JS 语法没错（node --check）", _r.returncode == 0,
            (_r.stderr or "").strip()[:300])
    else:
        print("  skip 这台机器上没 node，前端 JS 语法这条跳过")

'''

EDITS = {
    "index.html": [
        (BAD, GOOD),
    ],
    "test_cove.py": [
        ('''for tag in ("div", "section", "button", "nav"):
    o, cl = len(re.findall(r"<%s[\\s>]" % tag, html)), html.count("</%s>" % tag)
    chk("<%s> 开闭成对 (%d/%d)" % (tag, o, cl), o == cl)''',
         '''for tag in ("div", "section", "button", "nav"):
    o, cl = len(re.findall(r"<%s[\\s>]" % tag, html)), html.count("</%s>" % tag)
    chk("<%s> 开闭成对 (%d/%d)" % (tag, o, cl), o == cl)

''' + JS_CHECK.rstrip("\n")),
    ],
}

VER_FILES = {"VERSION": "2026-10-04d\n"}


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
                     % (name, want, n, old[:200]))
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

    # 生成出来的前端，必须自己先过一遍解析器
    html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    js = html.split("<script>", 1)[1].split("</script>", 1)[0]
    tmpps = os.path.join(ROOT, "_check_app.js")
    with open(tmpps, "w", encoding="utf-8") as f:
        f.write(js)
    import subprocess
    r = subprocess.run(["node", "--check", tmpps], capture_output=True, text=True)
    os.remove(tmpps)
    if r.returncode != 0:
        for name in staged:
            p = os.path.join(ROOT, name)
            if os.path.exists(p + ".bak"):
                shutil.move(p + ".bak", p)
        fail("前端 JS 还是过不了：\n" + (r.stderr or "")[:500])
    print("  前端 JS 语法过了（node --check）")

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
