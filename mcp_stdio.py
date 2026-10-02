#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cove · MCP 的第三条线：stdio
------------------------------
有些客户端（桌面上的那些）不给填网址，只让填一条命令 —— 它们靠标准输入输出说话。
这个文件就是那条线：一行一条 JSON-RPC 从 stdin 进来，交给 hub 里同一个 mcp_handle，
结果一行一条写到 stdout。

跑法：        python3 mcp_stdio.py
客户端里填：  命令 python3      参数 /你放小家的地方/Cove/mcp_stdio.py

两条规矩：
  · stdout 只许有 JSON-RPC（一行一条），别的都往 stderr 写 —— 不然客户端读不懂。
  · 手上的活跟 http / sse 完全一样：都是 hub.mcp_handle，九只手共用一套。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hub  # noqa: E402


def _out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    hub.init_db()
    sys.stderr.write("cove stdio MCP 起来了（小屋 %s）\n" % hub.VERSION)
    sys.stderr.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            _out({"jsonrpc": "2.0", "id": None,
                  "error": {"code": -32700, "message": "不是合法的 JSON-RPC"}})
            continue
        try:
            res = hub.mcp_handle(msg)
        except Exception as e:
            res = {"jsonrpc": "2.0", "id": (msg or {}).get("id"),
                   "error": {"code": -32603, "message": repr(e)}}
        if res is None:
            continue                     # 通知类，不用回
        _out(res)


if __name__ == "__main__":
    main()
