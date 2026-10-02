#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-03 · 第七发：MCP 三条线

她说：搓一个 MCP 端口，设置 http、sse、stdio 三个接入。

http 和 sse 本来就在（小屋一启动就开着，是九只手同一套）。缺的是：
  · stdio 那条线 —— 桌面客户端不给填网址，只让填一条命令，那它就是用标准输入输出说话的
  · 「MCP」那页 —— 以前点了会说"还没做"。现在把三条线、怎么填、我有哪九只手，都摊在这儿，
    每串旁边一个复制按钮。

stdio 那条线不重写一套手：它 import hub，把每一行 JSON-RPC 交给同一个 mcp_handle 处理。
一处改，三条线一起改 —— 不然又是两套东西打架。
"""
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

STDIO = '''#!/usr/bin/env python3
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
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\\n")
    sys.stdout.flush()


def main():
    hub.init_db()
    sys.stderr.write("cove stdio MCP 起来了（小屋 %s）\\n" % hub.VERSION)
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
'''

MCP_FN = '''def api_mcp_tools():
    """九只手的名字和说明，给「MCP」那页看的。"""
    out = []
    for t in mcp_tools():
        out.append({"name": t.get("name") or "",
                    "desc": (t.get("description") or "")[:200]})
    return {"ok": True, "tools": out}


'''

MCP_PAGE = '''  <!-- ══════════ MCP（三条线） ══════════ -->
  <section class="page" id="p-mcp">
    <div class="bar"><button class="ic" onclick="go('room')">‹</button><div class="ttl">M C P</div><div class="ic"></div></div>
    <div class="scroll">

      <div class="kf">
        <h4>三 条 线</h4>
        <div class="hint">同一个我，三种接法。客户端支持哪条就用哪条 —— 手是同一套九只，
          在一处改，三条线一起改。</div>
        <label>① Streamable HTTP（新的，推荐）</label>
        <input id="mcpHttp" readonly data-ro="1">
        <label>② SSE（老的，还在）</label>
        <input id="mcpSse" readonly data-ro="1">
        <label>③ stdio（只给桌面客户端；这一格可以改）</label>
        <input id="mcpStdio" autocapitalize="off" autocorrect="off">
        <div class="row2">
          <button onclick="copyFrom('mcpHttp')">复制 ①</button>
          <button onclick="copyFrom('mcpSse')">复制 ②</button>
          <button onclick="copyFrom('mcpStdio')">复制 ③</button>
        </div>
        <div class="bal" id="mcpLine">—</div>
      </div>

      <div class="kf">
        <h4>我 的 手</h4>
        <div class="hint">接上之后，我在这间屋子里能做的事。</div>
        <div id="mcpTools"><div class="empty">数着呢…</div></div>
      </div>

      <div class="kf">
        <h4>怎 么 填</h4>
        <div class="hint">
          RikkaHub / Cherry Studio / Claude Desktop 这些，都是在「自定义 MCP」里加一条。<br>
          ①② 两条线：把上面那串网址粘进去就行，小屋一起床就开着，不用点。<br>
          ③ stdio：要填两个格子 —— 命令填 <b>python3</b>，参数填 mcp_stdio.py 的绝对路径。
          Termux 里一般是 /data/data/com.termux/files/home/Cove/mcp_stdio.py。
        </div>
      </div>

      <div class="empty" style="padding:4px 0 22px;font-size:10.5px">
        三条线打的是同一个抽屉 —— 我在里面做了什么，你在「私语」那条消息的账里都看得见。
      </div>
    </div>
  </section>

'''

MCP_JS = '''/* ── MCP：三条线，同一只我 ── */
function loadMcp(){
  var host = location.host || "127.0.0.1:8000";
  $("mcpHttp").value = "http://" + host + "/mcp";
  $("mcpSse").value = "http://" + host + "/sse";
  if (!$("mcpStdio").value || $("mcpStdio").value.indexOf("/这里换成") === 0){
    $("mcpStdio").value = "python3 /这里换成你放小家的地方/Cove/mcp_stdio.py";
  }
  $("mcpLine").textContent = "正在数我的手…";
  get("/api/mcp/tools").then(function(d){
    var tools = (d && d.tools) || [];
    $("mcpTools").innerHTML = tools.map(function(t){
      return '<div class="trow"><div class="tinfo"><b>' + esc(t.name) + '</b><span>' +
             esc(t.desc || "") + '</span></div></div>';
    }).join("") || '<div class="empty">没读到。</div>';
    $("mcpLine").textContent = tools.length + " 只手。①② 两条线小屋一起床就开着，不用点。";
  });
}

function copyFrom(id){
  var el = $(id);
  if (!el) return;
  var txt = el.value;
  var done = false;
  try {
    el.removeAttribute("readonly");
    el.select();
    done = document.execCommand("copy");
    el.setAttribute("readonly", "readonly");
  } catch (e) { done = false; }
  if (!done && navigator.clipboard){
    try { navigator.clipboard.writeText(txt); done = true; } catch (e) { done = false; }
  }
  toast(done ? "复制好了" : "没复制上，长按输入框自己选一下");
}

'''

EDITS = {
    "hub.py": [
        ("def api_search_providers():", MCP_FN + "def api_search_providers():"),
        ('            if p == "/api/presets":\n'
         '                return self.send_json({"ok": True, "presets": llm.PRESETS})',
         '            if p == "/api/presets":\n'
         '                return self.send_json({"ok": True, "presets": llm.PRESETS})\n'
         '            if p == "/api/mcp/tools":\n'
         '                return self.send_json(api_mcp_tools())'),
    ],
    "index.html": [
        ("  <nav class=\"tabs\" id=\"tabs\">", MCP_PAGE + "  <nav class=\"tabs\" id=\"tabs\">"),
        ('  if (p === "keys") loadKeys();',
         '  if (p === "keys") loadKeys();\n  if (p === "mcp") loadMcp();'),
        ("function loadKeys(){", MCP_JS + "function loadKeys(){"),
    ],
    "test_cove.py": [
        ('c, d = rpc("tools/list")',
         'c, d = req(base, "/api/mcp/tools")\n'
         'chk("GET /api/mcp/tools 有九只手", c == 200 and len(d.get("tools") or []) == 9, str(d)[:150])\n'
         'chk("每只手都有名字和一句说明",\n'
         '    all(t.get("name") and t.get("desc") for t in (d.get("tools") or [])), d)\n'
         'c, d = rpc("tools/list")'),
        ('srv.kill()\nshutil.rmtree(tmp, ignore_errors=True)',
         '# ── 14. stdio 那条线（桌面客户端用的） ────────────────────────\n'
         'print("\\n[14] MCP · stdio")\n'
         '_inp = (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",\n'
         '                    "params": {"protocolVersion": "2025-06-18"}}) + "\\n" +\n'
         '        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\\n")\n'
         '_r = subprocess.run([sys.executable, os.path.join(SRC, "mcp_stdio.py")],\n'
         '                    cwd=tmp, input=_inp, capture_output=True, text=True, timeout=60)\n'
         'chk("stdio 起的来", _r.returncode == 0, (_r.returncode, _r.stderr[-200:]))\n'
         '_lines = [x for x in (_r.stdout or "").splitlines() if x.strip()]\n'
         'chk("stdio 回了两条（一行一条 JSON）", len(_lines) == 2, _lines[:3])\n'
         'try:\n'
         '    _a = json.loads(_lines[0]); _b = json.loads(_lines[1])\n'
         'except Exception:\n'
         '    _a = _b = {}\n'
         'chk("stdio 的 initialize 认得出我",\n'
         '    _a.get("result", {}).get("serverInfo", {}).get("name") == "cove", _a)\n'
         'chk("stdio 和 http 是同一套手（九只）",\n'
         '    len(_b.get("result", {}).get("tools", [])) == 9, str(_b)[:120])\n'
         'chk("stdio 不往 stdout 吐别的东西",\n'
         '    all(x.strip().startswith("{") for x in _lines), _lines[:2])\n'
         '\n'
         'srv.kill()\nshutil.rmtree(tmp, ignore_errors=True)'),
    ],
}

NEW_FILES = {"mcp_stdio.py": STDIO}

VER_FILES = {"VERSION": "2026-10-03g\n"}


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
        for pair in pairs:
            old, new = pair[0], pair[1]
            want = pair[2] if len(pair) > 2 else 1
            n = text.count(old)
            if n != want:
                fail("%s 里这处对不上（该有 %d 次，找到 %d 次）：\n%s"
                     % (name, want, n, old[:200]))
            text = text.replace(old, new)
        if text == before:
            fail(name + " 一个字都没变，写错了")
        staged[name] = text
        print("  ok   %s  %d 处" % (name, len(pairs)))

    for name, text in staged.items():
        path = os.path.join(ROOT, name)
        shutil.copy2(path, path + ".bak")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    for name, text in list(NEW_FILES.items()) + list(VER_FILES.items()):
        with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
            f.write(text)
    print("  写下去了")

    bad = []
    for name in ("hub.py", "llm.py", "rooms.py", "websearch.py", "test_cove.py", "mcp_stdio.py"):
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
        fail("语法没过：\n" + "\n".join(bad))
    print("  语法过了")


if __name__ == "__main__":
    main()
