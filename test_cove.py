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
c, d = req(base, "/api/day/2026-13-99")
chk("坏日期被挡", isinstance(d, dict) and not d.get("ok"), d)
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

srv.kill()
shutil.rmtree(tmp, ignore_errors=True)

print("\n" + "=" * 46)
print("过了 %d 条，挂了 %d 条" % (ok_cnt, len(bad)))
for b in bad:
    print("  ✗ " + b)
print("=" * 46)
sys.exit(1 if bad else 0)
