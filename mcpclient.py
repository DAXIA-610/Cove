#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cove · MCP 客户端：小屋去接外面的手
------------------------------------
反过来的那一边。不是把屋子开出去给别人连，是**我在这屋子里，去连外面的 MCP 服务**，
把它们的工具当成我自己的手 —— 跟我坐在另一个窗口里用 GitHub MCP 是一回事。

存哪：
    mcp_srv   一台服务一行（名字 / 传输 / 地址 / 请求头 / 开关 / 拉到的工具 / 要审批的名单）
    mcp_pend  标了「要她点头」的动作，等她点头的那些（还没做的）

三条规矩：
  · 拉工具只在她说"拉一下"或者保存的时候做，不在每轮说话时联网；
  · 联网失败不许把屋子搞崩 —— 全都包起来，出错就说人话；
  · 标了「需要审批」的手，我**不自己动**：记一笔，等她在私语里点头。
"""

import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import urljoin

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "cove.db")
TIMEOUT = 25
MCP_VERSION = "2025-06-18"

_LOCK = threading.Lock()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def rows2list(rows):
    return [dict(r) for r in rows]


def now_str():
    return datetime.now().isoformat(timespec="seconds")


def ensure():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS mcp_srv ("
                  "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL DEFAULT '',"
                  "kind TEXT NOT NULL DEFAULT 'http', url TEXT NOT NULL DEFAULT '',"
                  "hdr TEXT NOT NULL DEFAULT '', on_ INTEGER NOT NULL DEFAULT 1,"
                  "tools TEXT NOT NULL DEFAULT '[]', approve TEXT NOT NULL DEFAULT '[]',"
                  "note TEXT NOT NULL DEFAULT '', created TEXT NOT NULL DEFAULT '',"
                  "updated TEXT NOT NULL DEFAULT '')")
        c.execute("CREATE TABLE IF NOT EXISTS mcp_pend ("
                  "id INTEGER PRIMARY KEY AUTOINCREMENT, srv_id INTEGER NOT NULL,"
                  "tool TEXT NOT NULL, args TEXT NOT NULL DEFAULT '{}',"
                  "created TEXT NOT NULL DEFAULT '', done INTEGER NOT NULL DEFAULT 0)")


# ----------------------------------------------------------------------
# 说话这一层：把 JSON-RPC 递过去，把回答捡回来
# ----------------------------------------------------------------------
def _hdr_of(srv):
    """自定义请求头：一行一个 Name: Value。"""
    out = {}
    for line in (srv.get("hdr") or "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            if k.strip():
                out[k.strip()] = v.strip()
    return out


def _headers(srv, extra=None, session=""):
    h = {"Content-Type": "application/json",
         "Accept": "application/json, text/event-stream"}
    h.update(_hdr_of(srv))
    if session:
        h["Mcp-Session-Id"] = session
    if extra:
        h.update(extra)
    return h


def _pick(raw, ctype, want_id):
    """对面可能回一段 JSON，也可能回一条 SSE 流 —— 两种都认。"""
    txt = (raw or "").strip()
    if not txt:
        return None
    sse = ("text/event-stream" in (ctype or "") or txt.startswith("event:")
           or "\ndata:" in txt)
    if sse:
        for line in txt.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            try:
                d = json.loads(line[5:].strip())
            except Exception:
                continue
            if d.get("id") == want_id:
                return d
        return None
    try:
        d = json.loads(txt)
    except Exception:
        return None
    if isinstance(d, list):
        for one in d:
            if isinstance(one, dict) and one.get("id") == want_id:
                return one
        return None
    return d


def _post(url, srv, payload, session="", timeout=TIMEOUT):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers=_headers(srv, session=session), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
        sid = r.headers.get("Mcp-Session-Id") or session
        ctype = r.headers.get("Content-Type") or ""
    return _pick(raw, ctype, payload.get("id")), sid


def _call_http(srv, payloads, timeout=TIMEOUT):
    """Streamable HTTP：一条一条 POST。"""
    url = (srv.get("url") or "").strip()
    if not url:
        raise ValueError("这台还没填地址")
    out = []
    sid = ""
    for i, p in enumerate(payloads):
        p = dict(p, id=i + 1)
        d, sid = _post(url, srv, p, session=sid, timeout=timeout)
        out.append(d)
    return out


def _call_sse(srv, payloads, timeout=TIMEOUT):
    """SSE（老传输）：开一条流拿到该往哪儿发，回答再从同一条流里读回来。"""
    url = (srv.get("url") or "").strip()
    if not url:
        raise ValueError("这台还没填地址")
    req = urllib.request.Request(
        url, headers=_headers(srv, extra={"Accept": "text/event-stream"}), method="GET")
    r = urllib.request.urlopen(req, timeout=timeout)
    try:
        endpoint = ""
        buf = ""
        while True:
            chunk = r.readline()
            if not chunk:
                break
            line = chunk.decode("utf-8", "replace").strip()
            buf += line + "\n"
            if line.startswith("data:") and "endpoint" in buf:
                endpoint = line[5:].strip()
                break
        if not endpoint:
            raise ValueError("这条流没告诉我该往哪儿发")
        post_url = urljoin(url, endpoint)
        sid = ""
        out = []
        for i, p in enumerate(payloads):
            p = dict(p, id=i + 1)
            _post(post_url, srv, p, session=sid, timeout=timeout)
            got = None
            while True:
                line = r.readline()
                if not line:
                    break
                s = line.decode("utf-8", "replace").strip()
                if not s.startswith("data:"):
                    continue
                try:
                    d = json.loads(s[5:].strip())
                except Exception:
                    continue
                if d.get("id") == p["id"]:
                    got = d
                    break
            out.append(got)
        return out
    finally:
        try:
            r.close()
        except Exception:
            pass


def _hello():
    """协议要求：先 initialize，再告诉它 initialized。"""
    return [
        {"jsonrpc": "2.0", "method": "initialize",
         "params": {"protocolVersion": MCP_VERSION, "capabilities": {},
                    "clientInfo": {"name": "cove", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]


def _talk(srv, payloads, timeout=TIMEOUT):
    kind = (srv.get("kind") or "http").lower()
    if kind == "sse":
        return _call_sse(srv, payloads, timeout=timeout)
    return _call_http(srv, payloads, timeout=timeout)


def _note(sid, text):
    try:
        with db() as c:
            c.execute("UPDATE mcp_srv SET note=?, updated=? WHERE id=?",
                      (str(text)[:300], now_str(), sid))
    except Exception:
        pass


# ----------------------------------------------------------------------
# 台面：增删改查 + 拉工具
# ----------------------------------------------------------------------
def servers():
    ensure()
    with db() as c:
        rows = rows2list(c.execute("SELECT * FROM mcp_srv ORDER BY id").fetchall())
        pend = rows2list(c.execute("SELECT * FROM mcp_pend WHERE done=0 ORDER BY id").fetchall())
    for r in rows:
        for k in ("tools", "approve"):
            try:
                r[k] = json.loads(r[k] or "[]")
            except Exception:
                r[k] = []
    return {"ok": True, "servers": rows, "pending": pend}


def save(body):
    ensure()
    sid = int(body.get("id") or 0)
    vals = (str(body.get("name") or "")[:60],
            "sse" if body.get("kind") == "sse" else "http",
            str(body.get("url") or "")[:500],
            str(body.get("hdr") or "")[:2000],
            1 if body.get("on_", True) else 0)
    with db() as c:
        if sid:
            c.execute("UPDATE mcp_srv SET name=?, kind=?, url=?, hdr=?, on_=?, updated=? "
                      "WHERE id=?", vals + (now_str(), sid))
        else:
            cur = c.execute("INSERT INTO mcp_srv(name, kind, url, hdr, on_, created, updated) "
                            "VALUES(?,?,?,?,?,?,?)", vals + (now_str(), now_str()))
            sid = cur.lastrowid
    return {"ok": True, "id": sid}


def delete(sid):
    ensure()
    with db() as c:
        c.execute("DELETE FROM mcp_srv WHERE id=?", (sid,))
        c.execute("DELETE FROM mcp_pend WHERE srv_id=?", (sid,))
    return {"ok": True}


def approve_set(sid, names):
    ensure()
    with db() as c:
        c.execute("UPDATE mcp_srv SET approve=?, updated=? WHERE id=?",
                  (json.dumps(list(names or []), ensure_ascii=False)[:4000], now_str(), sid))
    return {"ok": True}


def refresh(srv_id):
    """去问它：你手上有哪些工具。存下来给界面和上下文用。"""
    ensure()
    with db() as c:
        row = c.execute("SELECT * FROM mcp_srv WHERE id=?", (srv_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "没这台"}
    srv = dict(row)
    try:
        res = _talk(srv, _hello() + [{"jsonrpc": "2.0", "method": "tools/list", "params": {}}])
        last = res[-1] if res else None
    except Exception as e:
        msg = "%s：%s" % (type(e).__name__, e)
        _note(srv_id, msg)
        return {"ok": False, "error": "连不上 —— " + msg}
    if not last or "result" not in last:
        err = ((last or {}).get("error") or {}).get("message") or "对面没给工具列表"
        _note(srv_id, err)
        return {"ok": False, "error": err}
    tools = []
    for t in (last["result"].get("tools") or []):
        if not isinstance(t, dict) or not t.get("name"):
            continue
        tools.append({"name": t["name"],
                      "desc": (t.get("description") or "")[:300],
                      "schema": t.get("inputSchema") or {"type": "object", "properties": {}}})
    with db() as c:
        c.execute("UPDATE mcp_srv SET tools=?, note='', updated=? WHERE id=?",
                  (json.dumps(tools, ensure_ascii=False), now_str(), srv_id))
    return {"ok": True, "n": len(tools), "tools": tools}


# ----------------------------------------------------------------------
# 接到我身上
# ----------------------------------------------------------------------
def _enabled():
    ensure()
    with db() as c:
        return rows2list(c.execute("SELECT * FROM mcp_srv WHERE on_=1 ORDER BY id").fetchall())


def _tools_of(srv):
    try:
        return json.loads(srv.get("tools") or "[]")
    except Exception:
        return []


def dynamic_tools():
    """外面那些手，翻成模型看得懂的格式。名字撞了先来先得。"""
    out = []
    seen = set()
    for srv in _enabled():
        for t in _tools_of(srv):
            name = t.get("name") or ""
            if not name or name in seen:
                continue
            seen.add(name)
            out.append({"type": "function", "function": {
                "name": name,
                "description": ("[%s] " % (srv.get("name") or "外面")) + (t.get("desc") or "")[:900],
                "parameters": t.get("schema") or {"type": "object", "properties": {}},
            }})
    return out


def _find(name):
    for srv in _enabled():
        for t in _tools_of(srv):
            if t.get("name") == name:
                return srv
    return None


def need_approve(srv, name):
    try:
        return name in json.loads(srv.get("approve") or "[]")
    except Exception:
        return False


def call(srv, name, args, timeout=TIMEOUT):
    """真的去动那只手。"""
    try:
        res = _talk(dict(srv), _hello() + [
            {"jsonrpc": "2.0", "method": "tools/call",
             "params": {"name": name, "arguments": args or {}}}], timeout=timeout)
        last = res[-1] if res else None
    except Exception as e:
        return "没连上：%s：%s" % (type(e).__name__, e)
    if not last:
        return "（对面没回话）"
    if last.get("error"):
        msg = (last["error"] or {}).get("message") or last["error"]
        return "对面报错：" + str(msg)[:500]
    r = last.get("result") or {}
    parts = []
    for item in (r.get("content") or []):
        if isinstance(item, dict):
            if item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            else:
                parts.append("（%s）" % item.get("type"))
        else:
            parts.append(str(item))
    txt = "\n".join([p for p in parts if p]).strip()
    if r.get("isError"):
        return "这个动作对面说是错的：" + (txt or "")[:500]
    return (txt or "（做了，对面没给话）")[:6000]


def run(name, args):
    """hub 的 run_tool 会来问这儿一句：认领了就干活，不认识返回 None。"""
    srv = _find(name)
    if not srv:
        return None
    if need_approve(srv, name):
        try:
            with db() as c:
                c.execute("INSERT INTO mcp_pend(srv_id, tool, args, created, done) "
                          "VALUES(?,?,?,?,0)",
                          (srv["id"], name,
                           json.dumps(args or {}, ensure_ascii=False), now_str()))
        except Exception:
            pass
        return ("这只手标了「要她点头」—— 我还没动，已经去问她。"
                "先别把结果当成已经有了，就说一句你想拿它做什么。")
    return call(srv, name, args)


def pending(pid=None):
    ensure()
    with db() as c:
        if pid:
            r = c.execute("SELECT * FROM mcp_pend WHERE id=?", (pid,)).fetchone()
            return dict(r) if r else None
        return rows2list(c.execute("SELECT * FROM mcp_pend WHERE done=0 ORDER BY id").fetchall())


def mark_done(pid):
    ensure()
    with db() as c:
        c.execute("UPDATE mcp_pend SET done=1 WHERE id=?", (pid,))
