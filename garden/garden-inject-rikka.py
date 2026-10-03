#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
garden-inject-rikka.py —— 花园唤醒桥的「橘瓣（RikkaHub）」投递端。

桥收到花园的唤醒后，会往这个脚本的 stdin 写一行 JSON：
    {"version":1,"type":"garden_wake","reason":"game_turn_required","message":"..."}

这个脚本把它投进橘瓣的某个会话，橘瓣就会自动让 AI 醒一轮。

环境变量（都能塞进桥的 .env 里）
  RIKKA_BASE        橘瓣网页服务地址，默认 http://127.0.0.1:8080
  RIKKA_CONV_TITLE  会话标题，默认「花园」（必须一模一样）
  RIKKA_ALLOW       放行哪些 reason，逗号分隔，默认只放游戏
  RIKKA_PASSWORD    橘瓣设了访问密码才填
  RIKKA_TOKEN       已经有 JWT 就直接填这个
  RIKKA_TIMEOUT     单次请求超时秒数，默认 30

成功退出码 0；失败非 0（桥会重试一次）。
"""

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("RIKKA_BASE", "http://127.0.0.1:8080").rstrip("/")
TITLE = os.environ.get("RIKKA_CONV_TITLE", "花园").strip()
PASSWORD = os.environ.get("RIKKA_PASSWORD", "")
TOKEN = os.environ.get("RIKKA_TOKEN", "")
TIMEOUT = float(os.environ.get("RIKKA_TIMEOUT", "30"))
ALLOW = [x.strip() for x in
         os.environ.get("RIKKA_ALLOW", "game_turn_required").split(",")
         if x.strip()]
JWT_CACHE = os.environ.get("RIKKA_JWT_CACHE", "/tmp/rikka-jwt.json")
DEDUP_FILE = os.environ.get("RIKKA_DEDUP_FILE", "/tmp/rikka-last-inject.json")
DEDUP_WINDOW = float(os.environ.get("RIKKA_DEDUP_WINDOW", "120"))


def log(msg):
    sys.stderr.write(str(msg) + "\n")


def http(method, path, body=None, token=None, query=None):
    """返回 (status, data)。data 是 dict / list / str / None。"""
    url = BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        status = resp.status
        text = resp.read().decode("utf-8", "replace")
    if not text.strip():
        return status, None
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text


def get_token(force_refresh=False):
    if TOKEN:
        return TOKEN
    if not PASSWORD:
        return None
    if not force_refresh:
        try:
            with open(JWT_CACHE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            left = float(cached.get("expiresAt") or 0) / 1000.0 - time.time()
            if cached.get("password") == PASSWORD and left > 86400:
                return cached["token"]
        except Exception:
            pass
    status, data = http("POST", "/api/auth/token", {"password": PASSWORD})
    if status != 200 or not isinstance(data, dict) or not data.get("token"):
        raise RuntimeError("换 JWT 失败（HTTP %s）：%s" % (status, data))
    try:
        with open(JWT_CACHE, "w", encoding="utf-8") as f:
            json.dump({"password": PASSWORD, "token": data["token"],
                       "expiresAt": data.get("expiresAt", 0)}, f)
        os.chmod(JWT_CACHE, 0o600)
    except Exception:
        pass
    return data["token"]


def find_conversation(token):
    status, page = http("GET", "/api/conversations/paged", token=token,
                        query={"limit": 100, "query": TITLE})
    items = page.get("items") if isinstance(page, dict) else None
    if not items:
        status, everything = http("GET", "/api/conversations", token=token)
        items = everything if isinstance(everything, list) else []
    for conv in items:
        if (conv.get("title") or "").strip() == TITLE:
            return conv.get("id")
    return None


def deliver(conv_id, message, token):
    path = "/api/conversations/%s/messages" % urllib.parse.quote(str(conv_id))
    body = {"parts": [{"type": "text", "text": message}]}
    return http("POST", path, body, token=token)


def is_duplicate(message):
    """只查，不写。投递成功了才 remember —— 不然失败的那次也会被当成投过。"""
    fp = hashlib.sha1(message.encode("utf-8")).hexdigest()
    try:
        with open(DEDUP_FILE, "r", encoding="utf-8") as f:
            last = json.load(f)
        return (last.get("fp") == fp
                and time.time() - float(last.get("at") or 0) < DEDUP_WINDOW)
    except Exception:
        return False


def remember(message):
    fp = hashlib.sha1(message.encode("utf-8")).hexdigest()
    try:
        with open(DEDUP_FILE, "w", encoding="utf-8") as f:
            json.dump({"fp": fp, "at": time.time()}, f)
    except Exception:
        pass


def main():
    raw = sys.stdin.readline()
    if not raw.strip():
        log("stdin 是空的")
        return 1
    try:
        event = json.loads(raw)
    except ValueError as exc:
        log("stdin 不是合法 JSON：%s" % exc)
        return 1
    if not isinstance(event, dict) or event.get("type") != "garden_wake":
        log("不是花园唤醒信封，跳过")
        return 0

    reason = str(event.get("reason") or "")
    message = str(event.get("message") or "")
    if reason not in ALLOW:
        log("reason=%s 不在放行名单里，跳过" % reason)
        return 0
    if not message.strip():
        log("message 是空的")
        return 1
    if is_duplicate(message):
        log("这条刚投过，跳过")
        return 0

    token = get_token()
    conv_id = find_conversation(token)
    if not conv_id:
        log("找不到标题是「%s」的会话" % TITLE)
        return 1

    try:
        status, _ = deliver(conv_id, message, token)
    except urllib.error.HTTPError as exc:
        if exc.code == 401 and PASSWORD and not TOKEN:
            try:
                os.remove(JWT_CACHE)
            except OSError:
                pass
            token = get_token(force_refresh=True)
            status, _ = deliver(conv_id, message, token)
        else:
            raise

    if status not in (200, 201, 202):
        log("投递失败，HTTP %s" % status)
        return 1
    remember(message)
    log("已投给会话 %s（reason=%s）" % (conv_id, reason))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as exc:
        log("HTTP 错误 %s %s" % (exc.code, exc.reason))
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        log("出错了：%s" % exc)
        sys.exit(1)
