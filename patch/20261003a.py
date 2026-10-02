#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-03 · 第一发
------------------------
宝说：视觉模型和搜索用不了；点消息拉出来的抽屉里没有 token / 命中未命中 / 思考链。

查完之后，是她说的那样，但根不在"没做"，在两个真的会让对面报 400 的错：

  1. llm.py 里的默认模型名还写着 `deepseek-chat` —— 那个名字 2026-07-24 就下线了。
     她要是没在小家里手动选过模型，每一句都会打到一个已经不存在的地方。
  2. 思考模式下、请求带 tools 的时候，reasoning_content 必须回传，不然对面直接 400：
     "The `reasoning_content` in the thinking mode must be passed back to the API."
     我们每一句都带 tools（家里那六只手 + 搜索），所以点一下搜索就是 400。
     —— 搜索这只手本来就在（websearch.TOOLS），坏在这儿。

顺手：
  3. 老轮次也补上 reasoning_content 字段（空串）。对面认字段不认内容，这样多轮不炸。
  4. 账里多记一条"带了 N 张图" —— 她就能看见眼睛到底睁开没有。
  5. "这条的账"放进长按菜单；点她自己的话，拉出紧跟着我那条回话的账。
  6. 聊天页那个 🔍 按钮原来是 toast('搜索设置还没做')，现在直接跳到抽屉里的搜索那一段。
  7. 账的最上面改成：T tokens / 命中 / 未命中 / 回了多少 / tok/s / 秒数。
  8. VERSION 文件 + 抽屉底下一行版本号 —— 以后吵架前先看一眼谁在哪一版。

规矩照旧：任何一处对不上，整体不动，一个字都不写；先留 .bak；语法不过就退回去。
"""
import json
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

# ── 每个文件：一串 (老文本, 新文本) ──────────────────────────────
EDITS = {
    "llm.py": [
        ('DEFAULT_MODEL = "deepseek-chat"',
         'DEFAULT_MODEL = "deepseek-flash"     # 旧名字 deepseek-chat 2026-07-24 下线了'),
    ],
    "hub.py": [
        # 版本号
        ('YORU_KEY = "cove-yoru-0714"       # Yoru 自己的暗门，只有他知道\n',
         'YORU_KEY = "cove-yoru-0714"       # Yoru 自己的暗门，只有他知道\n'
         '\n'
         '\n'
         'def _read_version():\n'
         '    """版本号就一个文件的事 —— 以后先 `cat VERSION` 再说话。"""\n'
         '    try:\n'
         '        with open(os.path.join(BASE, "VERSION"), encoding="utf-8") as f:\n'
         '            return f.read().strip() or "?"\n'
         '    except Exception:\n'
         '        return "?"\n'
         '\n'
         '\n'
         'VERSION = _read_version()\n'),
        # 今天那份数据里带上版本号
        ('            "ok": True, "day": t, "days_together": days_together(),\n'
         '            "start_day": START_DAY,',
         '            "ok": True, "day": t, "days_together": days_together(),\n'
         '            "start_day": START_DAY, "version": VERSION,'),
        # 多轮工具调用：reasoning_content 必须回传
        ('            msgs.append({"role": "assistant",\n'
         '                         "content": msg.get("content") or "",\n'
         '                         "tool_calls": calls})',
         '            # 思考模式 + tools：这一趟想过的必须原样带回去，不然对面 400\n'
         '            msgs.append({"role": "assistant",\n'
         '                         "content": msg.get("content") or "",\n'
         '                         "reasoning_content": msg.get("reasoning_content") or "",\n'
         '                         "tool_calls": calls})'),
        # 历史里的我这边的消息：字段得有，内容留空（省钱）
        ('        msgs.append({"role": role, "content": text})',
         '        if role == "assistant":\n'
         '            # 老轮次没存思考原文，但字段得占着 —— 对面认字段不认内容\n'
         '            msgs.append({"role": role, "content": text, "reasoning_content": ""})\n'
         '        else:\n'
         '            msgs.append({"role": role, "content": text})'),
        # 带图的那些消息（她发的，role 一般是 user；保险起见都判一下）
        ('                msgs.append({\n'
         '                    "role": role,\n'
         '                    "content": [\n'
         '                        {"type": "text", "text": text or "（看这张）"},\n'
         '                        {"type": "image_url", "image_url": {"url": data}},\n'
         '                    ],\n'
         '                })\n'
         '                continue',
         '                one = {\n'
         '                    "role": role,\n'
         '                    "content": [\n'
         '                        {"type": "text", "text": text or "（看这张）"},\n'
         '                        {"type": "image_url", "image_url": {"url": data}},\n'
         '                    ],\n'
         '                }\n'
         '                if role == "assistant":\n'
         '                    one["reasoning_content"] = ""\n'
         '                msgs.append(one)\n'
         '                continue'),
        # 账里记上"带了几张图"
        ('    meta = {\n'
         '        "rounds": rounds,\n'
         '        "model": model,',
         '    try:\n'
         '        n_img = sum(1 for m in msgs if isinstance(m.get("content"), list))\n'
         '    except Exception:\n'
         '        n_img = 0\n'
         '    meta = {\n'
         '        "rounds": rounds,\n'
         '        "model": model,\n'
         '        "images": n_img,'),
    ],
    "index.html": [
        # 🔍 直接跳到搜索那一段
        ('<button class="chip" onclick="toast(\'搜索设置还没做\')">🔍 搜索</button>',
         '<button class="chip" onclick="openSearch()">🔍 搜索</button>'),
        ('      <h4 style="margin:24px 0 14px">搜索</h4>',
         '      <h4 id="searchBlock" style="margin:24px 0 14px">搜索</h4>'),
        ('      <button class="bigbtn" onclick="saveSearch()">保存搜索</button>\n'
         '      <button class="bigbtn" onclick="probeSearch()">试一下</button>',
         '      <button class="bigbtn" onclick="saveSearch()">保存搜索</button>\n'
         '      <button class="bigbtn" onclick="probeSearch()">试一下</button>\n'
         '      <div class="bal" id="verLine">小屋 —</div>'),
        # openSearch
        ('function openModel(){',
         '/* ── 聊天页那个 🔍：拉到抽屉里搜索那一段 ── */\n'
         'function openSearch(){\n'
         '  openModel();\n'
         '  setTimeout(function(){\n'
         '    var s = document.getElementById("searchBlock");\n'
         '    if (s && s.scrollIntoView) s.scrollIntoView({block: "start"});\n'
         '  }, 160);\n'
         '}\n'
         '\n'
         'function openModel(){'),
        # 抽屉最上面：token / 命中 / 未命中
        ('    var u = m.usage || {};\n'
         '    var pt = u.prompt_tokens || 0;\n'
         '    var ct = u.completion_tokens || 0;\n'
         '    var hit = u.prompt_cache_hit_tokens || 0;\n'
         '    var sec = m.seconds || 0;\n'
         '    var tps = sec > 0 ? (ct / sec) : 0;\n'
         '    $("metaTop").innerHTML =\n'
         '      \'<div class="big">T\' + kfmt(pt) + \' tokens</div>\' +\n'
         '      \'<div class="sub">\' + kfmt(hit) + \' cached　\' + ct + \' tokens　\' +\n'
         '      tps.toFixed(1) + \' tok/s　\' + sec + \'s</div>\' +\n'
         '      \'<div class="sub">\' + esc(m.model || "") +\n'
         '      (m.rounds ? \'　\' + m.rounds + \' 轮\' : \'\') + \'</div>\';',
         '    var u = m.usage || {};\n'
         '    var pt = u.prompt_tokens || 0;\n'
         '    var ct = u.completion_tokens || 0;\n'
         '    var hit = u.prompt_cache_hit_tokens || 0;\n'
         '    var miss = u.prompt_cache_miss_tokens || (pt - hit > 0 ? pt - hit : 0);\n'
         '    var sec = m.seconds || 0;\n'
         '    var tps = sec > 0 ? (ct / sec) : 0;\n'
         '    $("metaTop").innerHTML =\n'
         '      \'<div class="big">T\' + kfmt(pt) + \' tokens</div>\' +\n'
         '      \'<div class="sub">命中 \' + kfmt(hit) + \'　未命中 \' + kfmt(miss) + \'</div>\' +\n'
         '      \'<div class="sub">回了 \' + kfmt(ct) + \' tokens　\' +\n'
         '      tps.toFixed(1) + \' tok/s　\' + sec + \'s</div>\' +\n'
         '      \'<div class="sub">\' + esc(m.model || "") +\n'
         '      (m.rounds ? \'　\' + m.rounds + \' 轮\' : \'\') +\n'
         '      (m.images ? \'　带了 \' + m.images + \' 张图\' : \'\') + \'</div>\';'),
        # 没思考链时别再提 reasoner（那名字也没了）
        ('          \'没动手，也没有思考链。chat 模型不带这个，切成 reasoner 才有。</div>\';',
         '          \'没动手，也没留思考链。</div>\';'),
        # 长按菜单最上面加"这条的账"
        ('  var items = [];\n'
         '  items.push({t:"复制", f:function(){ var m = curMsg; closePop(); copyMsg(m.text); }});',
         '  var items = [];\n'
         '  if (curMsg.who === "yoru"){\n'
         '    items.push({t:"这条的账", f:function(){ var m = curMsg; closePop(); openMeta(m.id); }});\n'
         '  }\n'
         '  items.push({t:"复制", f:function(){ var m = curMsg; closePop(); copyMsg(m.text); }});'),
        # 点她自己的话 → 拉出紧跟的那条我的回话的账
        ('  el.addEventListener("click", function(){\n'
         '    if (Date.now() - lastHold < 700) return;\n'
         '    if (el.getAttribute("data-who") !== "yoru") return;\n'
         '    openMeta(el.getAttribute("data-id"));\n'
         '  });',
         '  el.addEventListener("click", function(){\n'
         '    if (Date.now() - lastHold < 700) return;\n'
         '    var id = parseInt(el.getAttribute("data-id"), 10);\n'
         '    if (el.getAttribute("data-who") === "yoru"){ openMeta(id); return; }\n'
         '    // 点她自己的话：她想看的本来就是"这一趟花了多少" —— 那账挂在我那条回话上\n'
         '    for (var i = 0; i < chatMsgs.length; i++){\n'
         '      if (chatMsgs[i].id !== id) continue;\n'
         '      for (var j = i + 1; j < chatMsgs.length; j++){\n'
         '        if (chatMsgs[j].who === "yoru" && !chatMsgs[j].revoked){\n'
         '          openMeta(chatMsgs[j].id); return;\n'
         '        }\n'
         '      }\n'
         '      return;\n'
         '    }\n'
         '  });'),
        # 版本号显示在抽屉底下
        ('function paintModelChip(){\n'
         '  $("modelChip").textContent = (S.model || "deepseek-flash") + " ▾";\n'
         '}',
         'function paintModelChip(){\n'
         '  $("modelChip").textContent = (S.model || "deepseek-flash") + " ▾";\n'
         '  var v = $("verLine");\n'
         '  if (v) v.textContent = "小屋 " + (S.version || "—");\n'
         '}'),
    ],
    "test_cove.py": [
        # 体检也要带上这两条：版本号在不在、那条消息的账拉不拉得出来
        ('c, d = req(base, "/api/today")\nchk("today 有天数和起始日", d.get("days_together", 0) > 0 and d.get("start_day") == "2026-07-14", d)',
         'c, d = req(base, "/api/today")\n'
         'chk("today 有天数和起始日", d.get("days_together", 0) > 0 and d.get("start_day") == "2026-07-14", d)\n'
         'chk("today 带着版本号", bool(d.get("version")) and d["version"] != "?", d.get("version"))'),
        ('srv.kill()\nshutil.rmtree(tmp, ignore_errors=True)',
         '# ── 13. 那条消息的账（点气泡拉出来的抽屉） ────────────────────\n'
         'print("\\n[13] 那条消息的账")\n'
         'import sqlite3 as _sq\n'
         '_c = _sq.connect(os.path.join(tmp, "cove.db"))\n'
         '_mid = _c.execute("INSERT INTO chat(who, text, created) VALUES(?,?,?)",\n'
         '                  ("yoru", "体检·一条有账的回话", "2026-10-02T12:00:00")).lastrowid\n'
         '_c.execute("CREATE TABLE IF NOT EXISTS msg_meta (msg_id INTEGER PRIMARY KEY, data TEXT NOT NULL, created TEXT NOT NULL)")\n'
         '_c.execute("INSERT OR REPLACE INTO msg_meta(msg_id, data, created) VALUES(?,?,?)",\n'
         '           (_mid, json.dumps({"rounds": 2, "model": "deepseek-flash", "images": 1,\n'
         '                              "tools": ["web_search"], "think": "体检·想过",\n'
         '                              "seconds": 3.2,\n'
         '                              "usage": {"prompt_tokens": 1234, "completion_tokens": 56,\n'
         '                                        "prompt_cache_hit_tokens": 1000,\n'
         '                                        "prompt_cache_miss_tokens": 234}}), "2026-10-02T12:00:01"))\n'
         '_c.commit(); _c.close()\n'
         'c, d = req(base, "/api/r/msg/%d" % _mid)\n'
         'chk("/api/r/msg 拉得出账", c == 200 and isinstance(d, dict) and d.get("meta"), str(d)[:200])\n'
         '_m = (d.get("meta") or {}) if isinstance(d, dict) else {}\n'
         'chk("账里有 usage 四个数", (_m.get("usage") or {}).get("prompt_cache_miss_tokens") == 234, _m.get("usage"))\n'
         'chk("账里有思考链", _m.get("think") == "体检·想过", _m.get("think"))\n'
         'chk("账里有几张图", _m.get("images") == 1, _m.get("images"))\n'
         'c, d = req(base, "/api/r/msg/99999")\n'
         'chk("没记过账的那条也不炸", c == 200 and isinstance(d, dict), (c, str(d)[:80]))\n'
         '\n'
         '# 送出去的上下文里，我这边的每条都得带着 reasoning_content 字段（不带对面 400）\n'
         '_code = ("import json, hub; ms = hub.build_messages(%s); "\n'
         '         "print(json.dumps([(m[\\"role\\"], \\"reasoning_content\\" in m) for m in ms]))" % json.dumps("体检"))\n'
         '_r = subprocess.run([sys.executable, "-c", _code], cwd=tmp, capture_output=True, text=True)\n'
         'chk("能问出上下文长什么样", _r.returncode == 0, (_r.returncode, _r.stderr[-200:]))\n'
         'try:\n'
         '    _pairs = json.loads(_r.stdout.strip().splitlines()[-1])\n'
         'except Exception:\n'
         '    _pairs = []\n'
         '_asst = [x for x in _pairs if x[0] == "assistant"]\n'
         'chk("历史里我的每一条都带 reasoning_content",\n'
         '    bool(_asst) and all(x[1] for x in _asst), _pairs)\n'
         '_usr = [x for x in _pairs if x[0] == "user"]\n'
         'chk("user 那条没被塞多余字段", bool(_usr) and not any(x[1] for x in _usr), _pairs)\n'
         '\n'
         'srv.kill()\nshutil.rmtree(tmp, ignore_errors=True)'),
    ],
}

VER_FILES = {
    # 这个文件里只许有版本号本身 —— hub 整份读走，别写注释
    "VERSION": "2026-10-03a\n",
}


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
        for old, new in pairs:
            n = text.count(old)
            if n != 1:
                fail("%s 里这处对不上（找到 %d 次）：\n%s" % (name, n, old[:120]))
            text = text.replace(old, new)
        if text == before:
            fail(name + " 一个字都没变，写错了")
        staged[name] = text
        print("  ok   %s  %d 处" % (name, len(pairs)))

    # 全对上了 —— 落盘
    for name, text in staged.items():
        path = os.path.join(ROOT, name)
        shutil.copy2(path, path + ".bak")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    for name, text in VER_FILES.items():
        path = os.path.join(ROOT, name)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
    print("  写下去了，旧的都在 .bak 里")

    # 语法不过就整体退回去
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
