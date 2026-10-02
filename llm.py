#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cove · 大模型的那个口子
------------------------
单独一个文件，不跟 hub 缠在一起。
以后换家（换哪家的模型、换成本地、换协议），只改这里，hub 一行都不用动。

用法：
    import llm
    text = llm.chat(messages, api_key, model, base)
"""

import json
import urllib.error
import urllib.request

DEFAULT_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
TIMEOUT = 180

# 想加新家，就在这里多写一行。hub 只认 base + model 两个字段。
PROVIDERS = {
    "deepseek": {"base": "https://api.deepseek.com", "models": ["deepseek-chat", "deepseek-reasoner"]},
    "openai":   {"base": "https://api.openai.com/v1", "models": ["gpt-4o-mini"]},
    "moonshot": {"base": "https://api.moonshot.cn/v1", "models": ["moonshot-v1-8k"]},
}


class LLMError(Exception):
    """调不通的时候，把原因裹成人话抛出去。"""


def chat(messages, api_key, model=None, base=None, timeout=TIMEOUT):
    """发一轮对话，拿回一段文本。"""
    if not api_key:
        raise LLMError("还没填 key")
    base = (base or DEFAULT_BASE).strip().rstrip("/")
    model = (model or DEFAULT_MODEL).strip()

    payload = {"model": model, "messages": messages, "stream": False}
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
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
        return d["choices"][0]["message"]["content"]
    except Exception:
        raise LLMError("对面回的看不懂：" + raw[:200]) from None
