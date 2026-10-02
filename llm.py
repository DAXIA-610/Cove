#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cove · 大模型的那个口子
------------------------
单独一个文件，不跟 hub 缠在一起。
以后换家（换哪家的模型、换成本地、换协议），只改这里，hub 一行都不用动。

用法：
    import llm
    msg = llm.chat(messages, api_key, model, base, tools)   # 返回一整条 message
    bal = llm.balance(api_key, base)
"""

import json
import urllib.error
import urllib.request

DEFAULT_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
TIMEOUT = 180

# reasoner 这类"会先想一遍"的模型，不吃 function calling，别给它塞工具
NO_TOOLS_HINT = ("reasoner", "r1", "think")

# 想加新家，就在这里多写一行。hub 只认 base + model 两个字段。
PROVIDERS = [
    {"id": "deepseek", "name": "深度求索 DeepSeek",
     "base": "https://api.deepseek.com",
     "models": ["deepseek-chat", "deepseek-reasoner"]},
    {"id": "moonshot", "name": "月之暗面 Kimi",
     "base": "https://api.moonshot.cn/v1",
     "models": ["moonshot-v1-8k", "moonshot-v1-32k"]},
    {"id": "openai", "name": "OpenAI",
     "base": "https://api.openai.com/v1",
     "models": ["gpt-4o-mini", "gpt-4o"]},
]


class LLMError(Exception):
    """调不通的时候，把原因裹成人话抛出去。"""


def _url(base, path):
    return (base or DEFAULT_BASE).strip().rstrip("/") + path


def _headers(api_key):
    return {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + api_key,
    }


def supports_tools(model):
    m = (model or "").lower()
    return not any(h in m for h in NO_TOOLS_HINT)


def chat(messages, api_key, model=None, base=None, tools=None, timeout=TIMEOUT):
    """发一轮，返回一条完整的 message（可能带 tool_calls）。"""
    if not api_key:
        raise LLMError("还没填 key")
    model = (model or DEFAULT_MODEL).strip()

    payload = {"model": model, "messages": messages, "stream": False}
    if tools and supports_tools(model):
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    req = urllib.request.Request(
        _url(base, "/chat/completions"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=_headers(api_key),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        raise LLMError(f"对面回了 {e.code}：{detail}") from None
    except Exception as e:
        raise LLMError(f"没连上（{type(e).__name__}）") from None

    try:
        d = json.loads(raw)
        return d["choices"][0]["message"]
    except Exception:
        raise LLMError("对面回的看不懂：" + raw[:200]) from None


def balance(api_key, base=None, timeout=30):
    """问一句：账户里还剩多少。"""
    if not api_key:
        return {"ok": False, "error": "还没填 key"}
    req = urllib.request.Request(
        _url(base, "/user/balance"),
        headers=_headers(api_key),
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:200]
        except Exception:
            pass
        return {"ok": False, "error": f"对面回了 {e.code}：{detail}"}
    except Exception as e:
        return {"ok": False, "error": f"没连上（{type(e).__name__}）"}

    items = []
    for b in (d.get("balance_infos") or []):
        items.append({
            "currency": b.get("currency", ""),
            "total": b.get("total_balance", ""),
            "granted": b.get("granted_balance", ""),
            "topped": b.get("topped_up_balance", ""),
        })
    return {"ok": True, "available": d.get("is_available"), "items": items,
            "raw": None if items else d}
