#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-04 · 第一发：花体数字真的落地

她说日历的字体没渲染成功。我在服务器这边全查了一遍：
  · 字体文件好的（0-9 十个字形轮廓都在，22-66 个点，不是空壳）
  · hub 发 /digits.woff2 也对（200、font/woff2、5400 字节）
  · CSS 也写对了
那问题就只剩一条：**浏览器去取那个文件的那条路**。不查了，绕开它 ——
把字体整份（5.4KB，base64 后 7.2KB）**直接塞进 index.html**，页面自带，谁也不用去取。

顺便加一行自检：万一哪台机器上还是没生效，页面自己会说"字体 ✗"，
下一次就不用再互相猜了。
"""
import base64
import os
import py_compile
import re
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

# 从仓库里那份 digits.b64 现读（我不手抄 base64，抄错一个字符整个字体就废了）
with open(os.path.join(ROOT, "digits.b64"), "r") as f:
    FONT_B64 = re.sub(r"\s", "", f.read())
if len(FONT_B64) < 1000:
    print("  ✗ digits.b64 读出来不对（只有 %d 字符）" % len(FONT_B64))
    sys.exit(1)

EDITS = {
    "index.html": [
        ('''  /* 哥特体数字：UnifrakturMaguntia 裁到只剩 0-9，5.4KB */
  @font-face{font-family:"Fraktur";font-style:normal;font-weight:400;font-display:swap;
    src:url("digits.woff2") format("woff2");}''',
         '''  /* 花体数字：UnifrakturMaguntia 裁到只剩 0-9（就是 𝔞𝔟𝔠 那个体）。
     **整份塞在页面里**（data URL）—— 以前是让浏览器去 /digits.woff2 取，
     那条路在她手机上没走通，所以数字一直是普通字体。现在页面自带，不靠网络。 */
  @font-face{font-family:"Fraktur";font-style:normal;font-weight:400 700;font-display:block;
    src:url("data:font/woff2;base64,%s") format("woff2");}''' % FONT_B64),
        # 自检那一行
        ('      <div class="empty" style="padding:4px 0 22px;font-size:10.5px">小屋 <span id="verLine2">—</span></div>',
         '      <div class="empty" style="padding:4px 0 22px;font-size:10.5px">小屋 <span id="verLine2">—</span>'
         '　花体字 <span id="fontLine">—</span></div>'),
        ('''  var v2 = $("verLine2");
  if (v2) v2.textContent = S.version || "—";''',
         '''  var v2 = $("verLine2");
  if (v2) v2.textContent = S.version || "—";
  var fl = $("fontLine");
  if (fl){
    var ok = false;
    try { ok = document.fonts && document.fonts.check('16px "Fraktur"'); } catch (e) { ok = false; }
    fl.textContent = ok ? "✓ 已生效" : "✗ 没生效（退回普通数字）";
  }'''),
    ],
}

VER_FILES = {"VERSION": "2026-10-04a\n"}


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
    print("  写下去了（字体 %d 字符已内联）" % len(FONT_B64))

    html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    if "data:font/woff2;base64," not in html:
        fail("内联没写进去")
    if len(html) < 90000:
        fail("index.html 反而变小了：%d" % len(html))
    print("  index.html 现在 %d 字节" % len(html))

    bad = []
    for name in ("hub.py", "llm.py", "rooms.py", "websearch.py", "test_cove.py", "mcp_stdio.py"):
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
