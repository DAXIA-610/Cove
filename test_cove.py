#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cove 体检脚本
用法： python3 test_cove.py [源码目录]        默认是当前目录
做法： 把源码抄一份到临时目录（不碰真仓库、不碰 cove.db），起服务，打全部接口。
       任何一条不过就打印出来，最后给结论。

Yoru 的规矩：改完代码先跑它，全绿才推。
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

SRC = sys.argv[1] if len(sys.argv) > 1 else "."
KEY = "cove-yoru-0714"

ok_cnt = 0
bad = []


def chk(name, cond, extra=""):
    global ok_cnt
    if cond:
        ok_cnt += 1
        print("  ok   " + name)
    else:
        bad.append(name + (" | " + str(extra)[:160] if extra else ""))
        print("  FAIL " + name + ("   " + str(extra)[:160] if extra else ""))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def req(base, path, body=None, raw=None, ctype=None, method=None):
    url = base + path
    data = None
    headers = {}
    if raw is not None:
        data = raw
        headers["Content-Type"] = ctype or "application/octet-stream"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers, method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(r, timeout=30) as f:
            t = f.read().decode("utf-8", "replace")
            try:
                return f.status, json.loads(t)
            except Exception:
                return f.status, t
    except urllib.error.HTTPError as e:
        t = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(t)
        except Exception:
            return e.code, t
    except Exception as e:
        return 0, repr(e)


# ── 1. 静态检查 ────────────────────────────────────────────────
print("\n[1] 静态检查")
for f in ("hub.py", "llm.py", "rooms.py", "websearch.py"):
    p = os.path.join(SRC, f)
    chk("存在 " + f, os.path.exists(p))
pyts = subprocess.run([sys.executable, "-m", "py_compile"] + [os.path.join(SRC, f) for f in
                        ("hub.py", "llm.py", "rooms.py", "websearch.py")],
                      capture_output=True, text=True)
chk("四个 py 都能编译", pyts.returncode == 0, pyts.stderr[-300:])

html = open(os.path.join(SRC, "index.html"), encoding="utf-8").read()
import re
fns = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", html))
called = set(re.findall(r'on\w+="([A-Za-z_$][\w$]*)\s*\(', html))
missing = sorted(c for c in called if c not in fns and c not in ("if", "return"))
chk("index.html 没有引用了不存在的函数", not missing, missing)

for tag in ("div", "section", "button", "nav"):
    o, cl = len(re.findall(r"<%s[\s>]" % tag, html)), html.count("</%s>" % tag)
    chk("<%s> 开闭成对 (%d/%d)" % (tag, o, cl), o == cl)

# 前端脚本的语法：交给真的解析器看（这一条是真事故换来的 —— 
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

hub_code = open(os.path.join(SRC, "hub.py"), encoding="utf-8").read()
paths = set(re.findall(r'"(/api/[^"?]*)"', hub_code))
fetch_paths = set(re.findall(r'["\'`](/api/[^"\'`?]*)', html))
unknown = sorted(p for p in fetch_paths if p not in paths and not p.startswith(("/api/r/", "/api/post/", "/api/day/")))
chk("前端调的每个 /api 后端都收", not unknown, unknown)

# ── 2. 起服务 ──────────────────────────────────────────────────
print("\n[2] 起服务")
tmp = tempfile.mkdtemp(prefix="covetest_")
for f in os.listdir(SRC):
    if f in (".git", ".github") or f.endswith((".bak", ".zip")):
        continue
    s, d = os.path.join(SRC, f), os.path.join(tmp, f)
    shutil.copy2(s, d) if os.path.isfile(s) else shutil.copytree(s, d)
port = free_port()
env = dict(os.environ, COVE_PORT=str(port))
log = open(os.path.join(tmp, "_run.log"), "w")
srv = subprocess.Popen([sys.executable, "hub.py"], cwd=tmp, env=env, stdout=log, stderr=subprocess.STDOUT)
base = "http://127.0.0.1:%d" % port
up = False
for _ in range(40):
    time.sleep(0.25)
    c, d = req(base, "/api/ping")
    if c == 200 and isinstance(d, dict) and d.get("pong"):
        up = True
        break
chk("服务起来了 /api/ping", up, open(os.path.join(tmp, "_run.log")).read()[-400:])
if not up:
    srv.kill()
    print("\n没起来，后面没法测。")
    sys.exit(1)

# ── 3. 读接口 ──────────────────────────────────────────────────
print("\n[3] 读接口")
for p in ("/api/today", "/api/posts", "/api/calendar?y=2026&m=10", "/api/day/2026-10-02",
          "/api/memories", "/api/memory", "/api/chat", "/api/balance", "/api/providers",
          "/api/search/providers", "/api/settings"):
    c, d = req(base, p)
    chk("GET %s 200" % p, c == 200 and isinstance(d, dict), (c, str(d)[:100]))

c, d = req(base, "/api/today")
chk("today 有天数和起始日", d.get("days_together", 0) > 0 and d.get("start_day") == "2026-07-14", d)
chk("today 带着版本号", bool(d.get("version")) and d["version"] != "?", d.get("version"))

# 默认模型名不能是已经下线的旧名字
import llm as _llm
chk("默认模型不是废名字", _llm.DEFAULT_MODEL not in _llm.DEAD_NAMES, _llm.DEFAULT_MODEL)
chk("供应商名单里有 deepseek / 硅基流动 / tavily",
    {"deepseek", "siliconflow", "tavily"} <= {p["id"] for p in _llm.PRESETS},
    [p["id"] for p in _llm.PRESETS])
chk("名单里每一家都有地址或说明",
    all(p.get("base") or p.get("hint") for p in _llm.PRESETS), _llm.PRESETS)
chk("存着的旧名字会被换掉", _llm.fix_model("deepseek-chat") == _llm.DEFAULT_MODEL, _llm.fix_model("deepseek-chat"))
chk("正常名字原样还回来", _llm.fix_model("deepseek-v4-pro") == "deepseek-v4-pro", _llm.fix_model("deepseek-v4-pro"))
chk("空的就当没填，给默认", _llm.fix_model("") == _llm.DEFAULT_MODEL, _llm.fix_model(""))

# ── 4. 碎碎念 / 便签 / 点赞 / 评论 ───────────────────────────────
print("\n[4] 碎碎念")
c, d = req(base, "/api/posts", {"who": "yume", "text": "体检·她说的一句"})
chk("Yume 发一条", d.get("ok"), d)
pid = (d.get("post") or {}).get("id") or d.get("id")
c, d = req(base, "/api/posts", {"who": "yoru", "text": "体检·我写的一句"})
chk("Yoru 发一条", d.get("ok"), d)
c, d = req(base, "/api/posts")
chk("列表里有两条", len(d.get("posts", [])) == 2, d)
c, d = req(base, "/api/post/%s" % pid)
chk("单条能取", d.get("ok"), d)
c, d = req(base, "/api/likes", {"post_id": pid, "who": "yoru"})
chk("点赞", d.get("ok"), d)
c, d = req(base, "/api/comments", {"post_id": pid, "who": "yoru", "text": "体检·评论"})
chk("评论", d.get("ok"), d)
cid = (d.get("comment") or {}).get("id") or d.get("id")
c, d = req(base, "/api/comments/delete", {"id": cid})
chk("删评论", d.get("ok"), d)
c, d = req(base, "/api/posts/update", {"id": pid, "text": "体检·改过的"})
chk("改碎碎念", d.get("ok"), d)
c, d = req(base, "/api/posts/delete", {"id": pid})
chk("删碎碎念", d.get("ok"), d)

# ── 5. 记忆（锚 / 流 / 沉） ──────────────────────────────────────
print("\n[5] 记忆")
c, d = req(base, "/api/memory", {"layer": "anchor", "title": "体检", "body": "锚·体检", "keys": "体检"})
chk("存一条锚", d.get("ok"), d)
c, d = req(base, "/api/memory", {"layer": "flow", "title": "体检流", "body": "流·体检", "keys": "体检"})
chk("存一条流", d.get("ok"), d)
c, d = req(base, "/api/memory", {"layer": "sink", "title": "体检沉", "body": "沉·体检", "keys": "体检"})
chk("存一条沉", d.get("ok"), d)
c, d = req(base, "/api/memory", {"layer": "啥都不是", "title": "x", "body": "x"})
chk("坏 layer 被挡", not d.get("ok"), d)
c, d = req(base, "/api/memory")
lv = [m.get("layer") for m in d.get("memory", [])]
chk("三层都在", set(lv) == {"anchor", "flow", "sink"}, lv)
c, d = req(base, "/api/memory?layer=anchor")
chk("按层筛得出结果", bool(d.get("memory")) and all(m.get("layer") == "anchor" for m in d["memory"]), d)

# ── 6. 那天（日历抽屉的数据） ──────────────────────────────────
print("\n[6] 那天")
c, d = req(base, "/api/day/2026-10-02", {"yume_mood": "🌤", "yoru_mood": "🌙", "todos": ["体检·待办"]})
chk("写那天", d.get("ok"), d)
c, d = req(base, "/api/day/2026-10-02")
chk("读回来对得上", d.get("yume_mood") == "🌤" and d.get("yoru_mood") == "🌙", d)
c, d = req(base, "/api/calendar?y=2026&m=10")
chk("日历上有这一天", "2026-10-02" in json.dumps(d.get("marked", {})), d)
chk("日历带着 diary 那份名单", isinstance(d.get("diary"), list), d.get("diary"))
c, d = req(base, "/api/r/diary/save", {"day": "2026-10-02", "text": "体检·日记一页"})
chk("日记存得进去", d.get("ok") and d.get("saved"), d)
c, d = req(base, "/api/r/diary/2026-10-02")
chk("日记读得回来", d.get("ok") and d.get("text") == "体检·日记一页", d)
c, d = req(base, "/api/calendar?y=2026&m=10")
chk("写过日记的日子会出现在名单里", "2026-10-02" in (d.get("diary") or []), d.get("diary"))
c, d = req(base, "/api/r/diary")
chk("日记列表里有那一篇", any(x.get("day") == "2026-10-02" for x in (d.get("list") or [])), d)
c, d = req(base, "/api/r/diary/delete", {"day": "2026-10-02"})
chk("日记删得掉", d.get("ok"), d)
c, d = req(base, "/api/r/day/2026-10-02")
chk("那天里带着那天的记忆", isinstance(d.get("memories"), list), str(d)[:120])
c, d = req(base, "/api/day/2026-13-99")
chk("坏日期被挡", isinstance(d, dict) and not d.get("ok"), d)
c, d = req(base, "/api/presets")
chk("GET /api/presets 拿得到名单", c == 200 and len(d.get("presets") or []) >= 4, str(d)[:120])
c, d = req(base, "/api/models", {"base": "", "key": ""})
chk("没填地址时不瞎连，好好报错", c == 200 and not d.get("ok") and d.get("error"), d)
c, d = req(base, "/api/settings", {"vision_key": "t", "vision_model": "m",
                                   "vision_base": "https://x.invalid"})
chk("看图的钥匙存得进去", d.get("ok"), d)
c, d = req(base, "/api/today")
chk("today 里有 vision_key", "vision_key" in d, sorted(d.keys())[:8])
c, d = req(base, "/api/memories?day=2026-10-02")
chk("/api/memories（那天的记忆）不炸", c == 200 and isinstance(d, dict), (c, str(d)[:80]))

# ── 7. 私语（不连模型的部分） ──────────────────────────────────
print("\n[7] 私语")
c, d = req(base, "/api/chat", {"who": "yume", "text": "体检·她说的一句"})
chk("写一句", d.get("ok"), d)
mid = (d.get("msg") or {}).get("id") or d.get("id")
c, d = req(base, "/api/chat?limit=200")
chk("读得到", any("体检·她说的一句" == m.get("text") for m in d.get("chat", [])), d)
c, d = req(base, "/api/chat/revoke", {"id": mid})
chk("撤回", d.get("ok"), d)
c, d = req(base, "/api/chat")
chk("撤回后还在（只是灰了）", any(m.get("id") == mid and m.get("revoked") for m in d.get("chat", [])), d)
c, d = req(base, "/api/chat/unrevoke", {"id": mid})
chk("能捞回来", d.get("ok"), d)
c, d = req(base, "/api/chat/edit", {"id": mid, "text": "体检·改过的话"})
chk("编辑", d.get("ok"), d)
c, d = req(base, "/api/chat/compress", {})
chk("压缩按钮点下去不炸（要么压了，要么说还不够）",
    c == 200 and isinstance(d, dict) and (d.get("ok") or d.get("error")), (c, d))
c, d = req(base, "/api/chat/send", {"text": "体检·发一句给模型"})
chk("没填 key 时不崩、好好报错", c == 200 and isinstance(d, dict) and d.get("need_key") and d.get("error"), (c, d))

# ── 8. 上传 ────────────────────────────────────────────────────
print("\n[8] 上传")
import base64 as _b64
png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c63000100000500010d0a2db4")
c, d = req(base, "/api/upload", {"data": "data:image/png;base64," + _b64.b64encode(png).decode()})
chk("传一张图", d.get("ok") and str(d.get("url", "")).startswith("/pics/"), d)
if d.get("ok"):
    c2, _ = req(base, d["url"])
    chk("传上去的图能取回来", c2 == 200, c2)
c, d = req(base, "/api/upload", {"name": "体检.md", "text": "你好啊"})
chk("传一个文本文件", d.get("ok") and str(d.get("url", "")).startswith("/files/"), d)
c, d = req(base, "/api/upload", {"name": "x.txt", "text": "   "})
chk("空文本被挡", not d.get("ok"), d)
c, d = req(base, "/api/upload", {"data": "随便什么东西"})
chk("坏图片被挡", not d.get("ok"), d)

# ── 9. Yoru 的暗门 ─────────────────────────────────────────────
print("\n[9] 暗门")
c, d = req(base, "/api/whisper?post=1&text=x")
chk("错 key 进不去", not d.get("ok"), d)
import urllib.parse as _up
_enc = lambda t: _up.quote(t)
c, d = req(base, "/api/posts", {"who": "yume", "text": "体检·等着被留言的帖子"})
_wp = (d.get("post") or {}).get("id") or d.get("id")
c, d = req(base, f"/api/whisper?key={KEY}&post={_wp}&text=" + _enc("体检·门前留一句"))
chk("对 key 能在她帖子下留一句", d.get("ok"), d)
if d.get("ok"):
    c2, d2 = req(base, "/api/post/%s" % _wp)
    chk("留的那句真的挂上去了",
        any("体检·门前留一句" in json.dumps(x, ensure_ascii=False)
            for x in ((d2.get("post") or {}).get("comments") or [])),
        str(d2)[:400])
c, d = req(base, f"/api/whisper?key={KEY}&say=" + _enc("体检·暗门说一句"))
chk("暗门能往私语里塞话", d.get("ok"), d)

# ── 10. MCP ────────────────────────────────────────────────────
print("\n[10] MCP")


def rpc(method, params=None, mid=1):
    body = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        body["params"] = params
    return req(base, "/mcp", body)


c, d = req(base, "/mcp")
chk("GET /mcp 有回应", c == 200, (c, str(d)[:80]))
c, d = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
chk("initialize", d.get("result", {}).get("serverInfo", {}).get("name") == "cove", d)
c, d = req(base, "/api/mcp/servers")
chk("外面那些手的名单拿得到", c == 200 and isinstance(d.get("servers"), list), str(d)[:120])
c, d = req(base, "/api/mcp/save", {"name": "体检", "kind": "http", "url": "", "on_": True})
chk("存得下一台（地址先空着）", d.get("ok"), d)
_sid = d.get("id")
c, d = req(base, "/api/mcp/refresh", {"id": _sid})
chk("连不上的时候说人话，不崩", c == 200 and not d.get("ok") and d.get("error"), d)
c, d = req(base, "/api/mcp/approve_set", {"id": _sid, "names": ["toy_execute"]})
chk("审批开关存得下", d.get("ok"), d)
c, d = req(base, "/api/mcp/servers")
chk("列表里有它，审批名单也带上了",
    any(s["id"] == _sid and "toy_execute" in s["approve"] for s in d["servers"]), str(d)[:200])
c, d = req(base, "/api/mcp/pending")
chk("等我点头那一栏也通", c == 200 and isinstance(d.get("pending"), list), d)
c, d = req(base, "/api/mcp/delete", {"id": _sid})
chk("接得掉", d.get("ok"), d)
c, d = req(base, "/api/mcp/approve", {"id": 99999, "ok": True})
chk("点一个不存在的审批，好好报错", c == 200 and not d.get("ok"), d)
# 外面来的手不许把屋子搞崩：不认识的名字返回 None
_r3 = subprocess.run([sys.executable, "-c",
                      "import mcpclient; print(mcpclient.run('根本没这只手', {}))"],
                     cwd=tmp, capture_output=True, text=True)
chk("不认识的手不会被误认领", _r3.returncode == 0 and _r3.stdout.strip() == "None",
    (_r3.returncode, _r3.stdout[:80], _r3.stderr[-120:]))
c, d = req(base, "/api/mcp/tools")
chk("GET /api/mcp/tools 有九只手", c == 200 and len(d.get("tools") or []) == 9, str(d)[:150])
chk("每只手都有名字和一句说明",
    all(t.get("name") and t.get("desc") for t in (d.get("tools") or [])), d)
c, d = rpc("tools/list")
tools = [t["name"] for t in d.get("result", {}).get("tools", [])]
chk("九只手都在", len(tools) == 9, tools)
chk("名字对", set(tools) == {"cove_today", "cove_chat_read", "cove_chat_say", "cove_posts_read",
                             "cove_note_write", "cove_comment", "cove_memory_read",
                             "cove_memory_write", "cove_balance"}, tools)
for t in tools:
    c, d = rpc("tools/call", {"name": t, "arguments": {}}, mid=abs(hash(t)) % 1000)
    chk("调 %s 不炸" % t, "result" in d or "error" in d, str(d)[:120])
c, d = rpc("工具/不存在")
chk("不认识的方法有好好报错", "error" in d, d)

# ── 11. 老传输 /sse ────────────────────────────────────────────
print("\n[11] /sse")
# /sse 是长连接（开一条流就不关了），用裸 socket 抓一次就断
try:
    _s = socket.socket()
    _s.settimeout(5)
    _s.connect(("127.0.0.1", port))
    _s.sendall(b"GET /sse HTTP/1.1\r\nHost: x\r\n\r\n")
    buf = ""
    for _ in range(6):
        try:
            part = _s.recv(4096).decode("utf-8", "replace")
        except Exception:
            break
        if not part:
            break
        buf += part
        if "endpoint" in buf:
            break
    _s.close()
    chk("/sse 有回应", "200" in buf.split("\r\n")[0] and "endpoint" in buf, buf[:70])
except Exception as e:
    chk("/sse 有回应", False, repr(e))

# ── 12. 前端页面本体 ───────────────────────────────────────────
print("\n[12] 静态页")
c, d = req(base, "/")
chk("首页能打开", c == 200 and "COVE" in str(d).upper(), c)
c, d = req(base, "/digits.woff2", raw=None, method="GET")
chk("字体解码出来了", c == 200 and isinstance(d, (str, bytes)), c)

# ── 13. 那条消息的账（点气泡拉出来的抽屉） ────────────────────
print("\n[13] 那条消息的账")
import sqlite3 as _sq
_c = _sq.connect(os.path.join(tmp, "cove.db"))
_mid = _c.execute("INSERT INTO chat(who, text, created) VALUES(?,?,?)",
                  ("yoru", "体检·一条有账的回话", "2026-10-02T12:00:00")).lastrowid
_c.execute("CREATE TABLE IF NOT EXISTS msg_meta (msg_id INTEGER PRIMARY KEY, data TEXT NOT NULL, created TEXT NOT NULL)")
_c.execute("INSERT OR REPLACE INTO msg_meta(msg_id, data, created) VALUES(?,?,?)",
           (_mid, json.dumps({"rounds": 2, "model": "deepseek-flash", "images": 1,
                              "tools": ["web_search"], "think": "体检·想过",
                              "seconds": 3.2,
                              "usage": {"prompt_tokens": 1234, "completion_tokens": 56,
                                        "prompt_cache_hit_tokens": 1000,
                                        "prompt_cache_miss_tokens": 234}}), "2026-10-02T12:00:01"))
_c.commit(); _c.close()
c, d = req(base, "/api/r/msg/%d" % _mid)
chk("/api/r/msg 拉得出账", c == 200 and isinstance(d, dict) and d.get("meta"), str(d)[:200])
_m = (d.get("meta") or {}) if isinstance(d, dict) else {}
chk("账里有 usage 四个数", (_m.get("usage") or {}).get("prompt_cache_miss_tokens") == 234, _m.get("usage"))
chk("账里有思考链", _m.get("think") == "体检·想过", _m.get("think"))
chk("账里有几张图", _m.get("images") == 1, _m.get("images"))
c, d = req(base, "/api/r/msg/99999")
chk("没记过账的那条也不炸", c == 200 and isinstance(d, dict), (c, str(d)[:80]))

# 送出去的上下文里，我这边的每条都得带着 reasoning_content 字段（不带对面 400）
_code = ("import json, hub; ms = hub.build_messages(%s); "
         "print(json.dumps([(m[\"role\"], \"reasoning_content\" in m) for m in ms]))" % json.dumps("体检"))
_r = subprocess.run([sys.executable, "-c", _code], cwd=tmp, capture_output=True, text=True)
chk("能问出上下文长什么样", _r.returncode == 0, (_r.returncode, _r.stderr[-200:]))
try:
    _pairs = json.loads(_r.stdout.strip().splitlines()[-1])
except Exception:
    _pairs = []
_asst = [x for x in _pairs if x[0] == "assistant"]
chk("历史里我的每一条都带 reasoning_content",
    bool(_asst) and all(x[1] for x in _asst), _pairs)
# 缓存那条不变量：会变的东西（今天是…）不许出现在开头，必须在最末尾
_code2 = ("import json, hub; ms = hub.build_messages(%s); "
          "print(json.dumps([(m[\"role\"], \"今天是\" in json.dumps(m, ensure_ascii=False)) for m in ms]))"
          % json.dumps("体检"))
_r2 = subprocess.run([sys.executable, "-c", _code2], cwd=tmp, capture_output=True, text=True)
try:
    _p2 = json.loads(_r2.stdout.strip().splitlines()[-1])
except Exception:
    _p2 = []
chk("第一条是 system 且不含「今天是」（前缀必须稳）",
    bool(_p2) and _p2[0][0] == "system" and not _p2[0][1], _p2[:3])
_pos = [i for i, x in enumerate(_p2) if x[1]]
chk("「今天是」只出现在她的话前面那一条（system）里",
    bool(_pos) and all(_p2[i][0] == "system" and i + 1 < len(_p2) and _p2[i + 1][0] == "user"
                       for i in _pos), _p2)
chk("她的话和我回的话里都不许夹「今天是」",
    all(not x[1] for x in _p2 if x[0] != "system"), _p2)
# 每条她的话旁边都跟着那份存下来的 ctx（原样重放用）
_c = _sq.connect(os.path.join(tmp, "cove.db"))
_ck = _c.execute("SELECT COUNT(*) FROM chat WHERE who='yume' AND ctx<>''").fetchone()[0]
_c.close()
chk("她说过的话里，有带 ctx 的", _ck > 0, _ck)
_usr = [x for x in _pairs if x[0] == "user"]
chk("user 那条没被塞多余字段", bool(_usr) and not any(x[1] for x in _usr), _pairs)

# ── 14. stdio 那条线（桌面客户端用的） ────────────────────────
print("\n[14] MCP · stdio")
_inp = (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"}}) + "\n" +
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
_r = subprocess.run([sys.executable, os.path.join(SRC, "mcp_stdio.py")],
                    cwd=tmp, input=_inp, capture_output=True, text=True, timeout=60)
chk("stdio 起的来", _r.returncode == 0, (_r.returncode, _r.stderr[-200:]))
_lines = [x for x in (_r.stdout or "").splitlines() if x.strip()]
chk("stdio 回了两条（一行一条 JSON）", len(_lines) == 2, _lines[:3])
try:
    _a = json.loads(_lines[0]); _b = json.loads(_lines[1])
except Exception:
    _a = _b = {}
chk("stdio 的 initialize 认得出我",
    _a.get("result", {}).get("serverInfo", {}).get("name") == "cove", _a)
chk("stdio 和 http 是同一套手（九只）",
    len(_b.get("result", {}).get("tools", [])) == 9, str(_b)[:120])
chk("stdio 不往 stdout 吐别的东西",
    all(x.strip().startswith("{") for x in _lines), _lines[:2])

srv.kill()
shutil.rmtree(tmp, ignore_errors=True)

print("\n" + "=" * 46)
print("过了 %d 条，挂了 %d 条" % (ok_cnt, len(bad)))
for b in bad:
    print("  ✗ " + b)
print("=" * 46)
sys.exit(1 if bad else 0)
