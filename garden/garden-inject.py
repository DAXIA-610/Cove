#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
garden-inject.py
Galatea Garden 唤醒桥  ->  橘瓣（RikkaHub 的本地 Web API）

桥会往 stdin 写一行 JSON，长这样：
  {"version":1,"type":"garden_wake","reason":"game_turn_required","message":"..."}

这个脚本把它转发给橘瓣：
  POST http://127.0.0.1:8080/api/conversations/{会话id}/messages
橘瓣会把它当成"你说的一句话"，然后自动让我回一轮。

只放行 game_turn_required —— 论坛、聊天的动静一律不接（省钱）。
"""

import json
import os
import sys
import urllib.parse
import urllib.request

# 这三行是你要改的地方（也可以不改，用默认值）
BASE = os.environ.get("RIKKA_BASE", "http://127.0.0.1:8080")
TITLE = os.environ.get("RIKKA_CONV_TITLE", "花园")   # 橘瓣里那个专用会话的标题，必须一模一样
TOKEN = os.environ.get("RIKKA_TOKEN", "")            # 只有橘瓣设了「网页访问密码」才填
ALLOW = {"game_turn_required"}


def http(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if TOKEN:
        req.add_header("Authorization", "Bearer " + TOKEN)
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else None


def find_conversation():
    """按标题找那个专用会话，返回它的 id。不用手抄 UUID。"""
    q = urllib.parse.quote(TITLE)
    try:
        page = http("GET", "/api/conversations/paged?limit=100&query=" + q)
        items = (page or {}).get("items") or []
    except Exception:
        items = []
    if not items:
        items = http("GET", "/api/conversations") or []
    for c in items:
        if (c.get("title") or "").strip() == TITLE:
            return c.get("id")
    return None


def main():
    raw = sys.stdin.readline()
    if not raw.strip():
        print("stdin is empty", file=sys.stderr)
        return 1
    try:
        event = json.loads(raw)
    except Exception as e:
        print("bad json: %s" % e, file=sys.stderr)
        return 1

    reason = event.get("reason") or ""
    message = event.get("message") or ""

    if reason not in ALLOW:
        print("skip reason=%s" % reason, file=sys.stderr)
        return 0
    if not message.strip():
        print("empty message", file=sys.stderr)
        return 1

    cid = find_conversation()
    if not cid:
        print("conversation not found (title=%s)" % TITLE, file=sys.stderr)
        return 1

    http("POST", "/api/conversations/%s/messages" % cid,
         {"parts": [{"type": "text", "text": message}]})
    print("sent to %s" % cid, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
