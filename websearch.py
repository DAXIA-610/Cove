#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cove · 对互联网的那口子
------------------------
llm.py 是"对模型说话"，这里是"对互联网说话"。一个层级，一个职责。

它往外亮两样东西，hub 自己会来拿：
    TOOLS   交给模型看的工具说明书（function calling）
    run()   模型说要用这只手，hub 就把活儿交给这儿

现在只有一只手：web_search。以后加"读网页""看图"之类，往这儿加就行，hub 不用动。
key 躺在她手机上的 cove.db 里（settings 表），跟模型的 key 挨着。
"""

import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "cove.db")

# 想加新家，在这儿加一行就行。base 能自己填（走代理或者自建的时候用）。
PROVIDERS = [
    {"id": "tavily", "name": "Tavily",
     "base": "https://api.tavily.com", "hint": "tvly- 开头"},
    {"id": "brave", "name": "Brave Search",
     "base": "https://api.search.brave.com", "hint": "BSA 开头"},
    {"id": "bocha", "name": "博查 Bocha",
     "base": "https://api.bochaai.com", "hint": "sk- 开头"},
]

TIMEOUT = 25
MAX_N = 8

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "上网搜一下。什么时候该用：她问的事我不知道、事情是刚发生的、"
                "需要具体的事实（价格、地址、新闻、别人怎么说、有没有这回事）。"
                "什么时候别用：我本来就知道的、我们俩之间的事、纯聊天。"
                "搜完把结果当地上的东西用，别整段抄给她——挑她要的那点说。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要搜的词，短一点准一点"},
                    "n": {"type": "integer", "description": "要几条，默认 5，最多 8"},
                },
                "required": ["query"],
            },
        },
    },
]


class SearchError(Exception):
    pass


# ----------------------------------------------------------------------
# 配置：跟她填模型 key 的地方在同一张表里
# ----------------------------------------------------------------------
def _conf():
    """返回 (key, provider, base)。读不出来就当没填。"""
    try:
        c = sqlite3.connect(DB_PATH, timeout=10)
        c.row_factory = sqlite3.Row

        def g(k, d=""):
            r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
            return (r["v"] if r else d) or d

        out = (g("search_key"), g("search_provider", "tavily"), g("search_base"))
        c.close()
        return out
    except Exception:
        return ("", "tavily", "")


def _post(url, payload, headers, timeout=TIMEOUT):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        raise SearchError("对面回了 %s：%s" % (e.code, detail)) from None
    except Exception as e:
        raise SearchError("没连上（%s）" % type(e).__name__) from None


def _get(url, headers, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        raise SearchError("对面回了 %s：%s" % (e.code, detail)) from None
    except Exception as e:
        raise SearchError("没连上（%s）" % type(e).__name__) from None


# ----------------------------------------------------------------------
# 三家各一张嘴
# ----------------------------------------------------------------------
def _tavily(query, key, base, n):
    url = (base or "https://api.tavily.com").rstrip("/") + "/search"
    payload = {
        "query": query,
        "max_results": n,
        "search_depth": "basic",
        "include_answer": False,
        "api_key": key,              # 老版把 key 放 body
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,   # 新版走头。两边都带上，认哪个都行
    }
    d = _post(url, payload, headers)
    out = []
    for it in (d.get("results") or [])[:n]:
        out.append({
            "title": it.get("title") or "",
            "url": it.get("url") or "",
            "text": (it.get("content") or "")[:800],
        })
    if not out and d.get("answer"):
        out.append({"title": "Tavily 的说法", "url": "", "text": str(d["answer"])[:800]})
    return out


def _brave(query, key, base, n):
    root = (base or "https://api.search.brave.com").rstrip("/")
    url = root + "/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": query, "count": n})
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": key,
    }
    d = _get(url, headers)
    out = []
    for it in ((d.get("web") or {}).get("results") or [])[:n]:
        out.append({
            "title": it.get("title") or "",
            "url": it.get("url") or "",
            "text": (it.get("description") or "")[:800],
        })
    return out


def _bocha(query, key, base, n):
    root = (base or "https://api.bochaai.com").rstrip("/")
    url = root + "/v1/web-search"
    payload = {"query": query, "count": n, "summary": True}
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,
    }
    d = _post(url, payload, headers)
    pages = (((d.get("data") or {}).get("webPages") or {}).get("value") or [])
    out = []
    for it in pages[:n]:
        out.append({
            "title": it.get("name") or "",
            "url": it.get("url") or "",
            "text": (it.get("summary") or it.get("snippet") or "")[:800],
        })
    return out


_ROUTES = {"tavily": _tavily, "brave": _brave, "bocha": _bocha}


def search(query, key, provider="tavily", base="", n=5):
    """搜一把，返回 [{title,url,text}, ...]。出错抛 SearchError。"""
    if not key:
        raise SearchError("没填搜索的 key")
    fn = _ROUTES.get((provider or "tavily").strip().lower())
    if not fn:
        raise SearchError("不认识这家的名字：" + str(provider))
    return fn(query, key, base, max(1, min(int(n or 5), MAX_N)))


def render(items):
    """把结果捏成模型看得懂的一段话。"""
    if not items:
        return "搜了，没搜到东西。"
    lines = []
    for i, it in enumerate(items, 1):
        lines.append("【%d】%s" % (i, it.get("title") or "(没标题)"))
        if it.get("url"):
            lines.append(it["url"])
        if it.get("text"):
            lines.append(it["text"])
        lines.append("")
    return "\n".join(lines).strip()


# ----------------------------------------------------------------------
# hub 会来叫这只手
# ----------------------------------------------------------------------
def run(name, args):
    """认得出就干活并返回一段文字；认不出返回 None，让 hub 自己接着找。"""
    if name != "web_search":
        return None
    args = args or {}
    q = (args.get("query") or "").strip()
    if not q:
        return "没给要搜的词。"
    key, provider, base = _conf()
    try:
        items = search(q, key, provider, base, args.get("n") or 5)
    except SearchError as e:
        return "搜索没成：" + str(e)
    except Exception as e:
        return "搜索出错了：" + repr(e)
    return render(items)


def probe(key, provider="tavily", base=""):
    """界面上那个"试一下"按钮走这儿。"""
    try:
        items = search("DeepSeek", key, provider, base, 2)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "n": len(items), "sample": items[:1]}
