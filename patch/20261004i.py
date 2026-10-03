#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-04 · 第九发：让页面自己发现"我是旧的"

她说：有些是最新的，有些还是前几轮的 —— 日历字体没变、思考链加载不出来。

hub 那边其实已经发了 Cache-Control: no-store，所以**不是服务器的问题**。
是那个已经开着的标签页：页面还是它第一次打开时那一份（CSS/JS/抽屉都在里面），
而数据是每次现取的 —— 于是"数据新的、界面旧的"，看起来就像我漏推了几件。

这一发做两件事：
  ① 页面里写死一个自己的版本号；一进来就拿它跟服务端的版本比。
     不一样（说明手里这份是旧的）就**自己刷一次**，并且只刷一次（防死循环）。
     以后我每次推版本，她最多看到一句"页面是旧的，我刷一下…"，不用再自己发现。
  ② 顶栏那一行也顺手留个记号，方便我们对版本。
"""
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

VER = "2026-10-04i"

SELF_CHECK = '''    // 这一手是给"数据新的、界面旧的"准备的：
    // 页面里写着自己的版本，跟服务端一比就知道手里这份是不是旧的 —— 是就自己刷一次。
    if (S.version && S.version !== PAGE_VER){
      try {
        if (!sessionStorage.getItem("cove_reloaded")){
          sessionStorage.setItem("cove_reloaded", "1");
          toast("页面是旧的，我刷一下…");
          setTimeout(function(){ location.reload(); }, 900);
        } else {
          toast("页面还是旧的（页面 " + PAGE_VER + "，服务器 " + S.version + "）—— 手动刷新一下");
        }
      } catch (e) {
        toast("页面是旧的，手动刷新一下");
      }
      return;
    }
'''

EDITS = {
    "index.html": [
        ("var S = {};\n",
         "var S = {};\nvar PAGE_VER = \"%s\";     // 这一份页面自己的版本（服务端版本不一样就自己刷）\n" % VER),
        ('''    Object.keys(d).forEach(function(k){ S[k] = d[k]; });
    paint(); renderAvatars();''',
         '''    Object.keys(d).forEach(function(k){ S[k] = d[k]; });
''' + SELF_CHECK + '''    paint(); renderAvatars();'''),
    ],
}

VER_FILES = {"VERSION": VER + "\n"}


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
        print("  ok   %s（%d → %d 字节）" % (name, len(before), len(text)))
    for name, text in VER_FILES.items():
        with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
            f.write(text)
    print("  写下去了")

    html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    if "PAGE_VER" not in html:
        fail("版本自检没进去")
    js = html.split("<script>", 1)[1].split("</script>", 1)[0]
    import subprocess
    tmpps = os.path.join(ROOT, "_check_app.js")
    with open(tmpps, "w", encoding="utf-8") as f:
        f.write(js)
    r = subprocess.run(["node", "--check", tmpps], capture_output=True, text=True)
    os.remove(tmpps)
    if r.returncode != 0:
        for name in EDITS:
            p = os.path.join(ROOT, name)
            if os.path.exists(p + ".bak"):
                shutil.move(p + ".bak", p)
        fail("前端 JS 过不了：\n" + (r.stderr or "")[:400])
    print("  前端 JS 语法过了")


if __name__ == "__main__":
    main()
