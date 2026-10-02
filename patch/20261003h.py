#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-03 · 第八发：收尾（相机 / 照片 / 文件 / 压缩 / 搜索那几件）

她说：再搓相机、照片、文件、上下文压缩、搜索引擎，让它们能够真的用起来。

挨个查过一遍，实情是这样：
  · 相机 / 照片 —— 路是通的（拍完压到 1024px 再传，我这边读成 base64 塞进上下文）。
    它之前"用不了"，坏在上一发修的那个 400 上（思考模式 + tools 不回传 reasoning_content）。
  · 文件 —— 真有个洞：只要是"文件"就 readAsText，你扔个 PDF 进来会读成一堆乱码塞进上下文。
    这一发加上判断：只认纯文本，别的当场告诉你读不了。
  · 压缩 —— 能压，但压完只说"收进去 N 条"，看不出压出了什么。改成连摘要多少字一起说。
  · 搜索 —— 通道上一发建好了。这里补一个小提示：没配 key 的时候，聊天页那个 🔍 会变淡，
    写清楚"还没配"，免得再出现"用不了"而不知道卡在哪。
  · 加号面板里的 🔌 MCP 以前是个 toast，现在直接去那页。
"""
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

LOOKS_TEXT = '''function looksText(f){
  var t = (f.type || ""), n = (f.name || "").toLowerCase();
  if (t.indexOf("text/") === 0 || t.indexOf("json") >= 0 || t.indexOf("xml") >= 0){
    return true;
  }
  var ok = [".txt", ".md", ".markdown", ".json", ".csv", ".log", ".py", ".js",
            ".html", ".css", ".yml", ".yaml", ".toml", ".ini", ".srt"];
  for (var i = 0; i < ok.length; i++){
    if (n.slice(-ok[i].length) === ok[i]) return true;
  }
  return false;
}

'''

EDITS = {
    "index.html": [
        # 文件：只认纯文本，别把乱码塞进上下文
        ("function onChatFile(ev){", LOOKS_TEXT + "function onChatFile(ev){"),
        ('''  if (kind === "file" && f.type.indexOf("image/") !== 0){
    var fr = new FileReader();''',
         '''  if (kind === "file" && f.type.indexOf("image/") !== 0){
    if (!looksText(f)){
      toast("这个我读不了 —— 只认纯文本（txt / md / json / csv 这些）");
      return;
    }
    var fr = new FileReader();'''),
        # 压缩：说清楚压出了什么
        ('''    toast("压好了，收进去 " + (r.covered || 0) + " 条");''',
         '''    toast("压好了：收进去 " + (r.covered || 0) + " 条，摘要 " +
          ((r.summary || "").length) + " 字");'''),
        # 🔍 给个名字，没配 key 就变淡
        ('      <button class="chip" onclick="openSearch()">🔍 搜索</button>',
         '      <button class="chip" id="searchChip" onclick="openSearch()">🔍 搜索</button>'),
        ('''  var v2 = $("verLine2");
  if (v2) v2.textContent = S.version || "—";
}''',
         '''  var v2 = $("verLine2");
  if (v2) v2.textContent = S.version || "—";
  var sc = $("searchChip");
  if (sc){
    sc.textContent = S.search_key ? "🔍 搜索" : "🔍 搜索（还没配）";
    sc.style.opacity = S.search_key ? "1" : ".55";
  }
}'''),
        # 加号面板里的 MCP 不再是 toast
        ('''      <button onclick="toast('MCP 开关下一步接')"><b>🔌</b>MCP</button>''',
         '''      <button onclick="togglePlus();go('mcp')"><b>🔌</b>MCP</button>'''),
    ],
    "test_cove.py": [
        ('c, d = req(base, "/api/chat/send", {"text": "体检·发一句给模型"})',
         'c, d = req(base, "/api/chat/compress", {})\n'
         'chk("压缩按钮点下去不炸（要么压了，要么说还不够）",\n'
         '    c == 200 and isinstance(d, dict) and (d.get("ok") or d.get("error")), (c, d))\n'
         'c, d = req(base, "/api/chat/send", {"text": "体检·发一句给模型"})'),
    ],
}

VER_FILES = {"VERSION": "2026-10-03h\n"}


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
