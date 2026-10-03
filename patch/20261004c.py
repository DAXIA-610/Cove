#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-04 · 第三发：MCP 翻过来 —— 是我去接外面的手

她说：MCP 做错了。不是这样的。是**你在家，然后可以接外面的端口，像你使用 github mcp 一样**。

我看懂她的图了（那七张图 OCR 出来看的）：
    图一 MCP 列表：Toy / McDonald / LuckinCoffee / OpenMeteoWeather / marriage / fetch，
                    每条后面写着 Streamable HTTP 或 SSE，右上角一个 ＋
    图二 编辑页：启用开关 / 名称 / 传输类型 / 服务器地址 / 自定义请求头 / 保存
    图三 工具那一栏：toy_list_devi… / toy_status / toy_execute… 每只后面一个「需要审批」开关

原来我做的反了 —— 我做的是"把屋子开出去，给外面的 app 连我"。她要的是"我坐在屋子里，
去连外面的 MCP 服务，把它们的工具当成我自己的手"。这一发把它翻过来：

  · 新文件 mcpclient.py：连（Streamable HTTP + SSE 两种）、拉工具、调工具、审批
  · 接上的手会通过 all_tools() 出现在我手上，模型自己决定什么时候用
  · 标了「需要审批」的手我**不自己动**：在私语里留一条问她，她点「允许」我才做，
    做完把结果接着说一句 —— 点「不许」也一样回一句
  · MCP 那页的顶上就是这份名单；原来那三条线（往外开的门）留在下面，RikkaHub 走的就是它
"""
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

APPROVE_FN = '''def api_mcp_approve(body):
    """她在私语里点的那一下：允许 / 不许。

    点了我就真的去做（或者真的不做），然后像平常一样接着说一句 ——
    所以这一下也是走「她说话 → 我回话」那条熟路，不另开一条。
    """
    if mcpclient is None:
        return {"ok": False, "error": "MCP 没装上"}
    pid = as_int(body.get("id"))
    ok = bool(body.get("ok"))
    row = mcpclient.pending(pid)
    if not row or row.get("done"):
        return {"ok": False, "error": "这一笔已经处理过了"}
    with db() as c:
        srv = c.execute("SELECT * FROM mcp_srv WHERE id=?", (row["srv_id"],)).fetchone()
    mcpclient.mark_done(pid)
    tool = row.get("tool") or ""
    try:
        args = json.loads(row.get("args") or "{}")
    except Exception:
        args = {}
    if ok and srv is not None:
        try:
            out = mcpclient.call(dict(srv), tool, args)
        except Exception as e:
            out = "没做成：%s：%s" % (type(e).__name__, e)
        head = "【她点头了，我做了 %s】\\n%s" % (tool, out)
        text = "（我点了允许）"
    else:
        head = "【她没让做 %s】" % tool
        text = "（我点了不许）"
    with db() as c:
        cur = c.execute("INSERT INTO chat(who, text, created, image, file, ctx) "
                        "VALUES(?,?,?,?,?,'')", ("yume", text, now_str(), "", ""))
        c.execute("UPDATE chat SET ctx=? WHERE id=?",
                  (env_text(text) + "\\n\\n" + head, cur.lastrowid))
    r = _generate(text)
    if r.get("reply"):
        with db() as c:
            cur = c.execute("INSERT INTO chat(who, text, created) VALUES(?,?,?)",
                            ("yoru", r["reply"][:4000], now_str()))
            _save_meta(c, cur.lastrowid, r.get("meta"))
    return r


'''

PEND_CSS = '''  /* 要她点头的那一条 */
  .pend{align-self:center;max-width:90%;background:rgba(140,155,171,.16);
        border:1px solid var(--line);border-radius:14px;padding:11px 14px;
        font-size:12px;line-height:1.7;color:var(--ink);}
  .pend .pa{display:flex;gap:8px;margin-top:10px;}
  .pend .pa button{flex:1;padding:8px 0;border-radius:10px;
        background:rgba(13,50,71,.08);font-size:12px;color:var(--ink);}
  .pend .pa button:first-child{background:#0d3247;color:#fff;}
  .pend .pa button:active{opacity:.7;}

'''

CLIENT_CARD = '''      <div class="kf">
        <h4>外 面 的 手</h4>
        <div class="hint">我在这儿，去连外面的 MCP 服务，把它们的工具当成我自己的手 ——
          跟我坐在另一个窗口里用 GitHub MCP 是一回事。接上之后，它们就出现在我能动的范围里。</div>
        <div id="mcpList"><div class="empty">看看外面有哪些手…</div></div>
        <div class="row2"><button class="kk" onclick="openMcp(0)">＋ 接一台</button></div>
        <div class="bal" id="mcpLine2">—</div>
      </div>

'''

SHEET = '''  <div class="mask" id="mcMask" onclick="if(event.target===this)closeMcp()">
    <div class="sheet">
      <h4>接 一 台 MCP</h4>
      <div class="frow">
        <label>启用</label>
        <button class="sw on" id="mcOn"
                onclick="this.className=(this.className.indexOf('on')>=0?'sw':'sw on')"></button>
      </div>
      <div class="frow">
        <label>名称</label>
        <input id="mcName" placeholder="给它起个名字，比如 GitHub" autocapitalize="off" autocorrect="off">
      </div>
      <div class="frow">
        <label>传输类型</label>
        <select id="mcKind">
          <option value="http">Streamable HTTP</option>
          <option value="sse">SSE</option>
        </select>
      </div>
      <div class="frow">
        <label>服务器地址</label>
        <input id="mcUrl" placeholder="https://…/mcp" autocapitalize="off" autocorrect="off">
      </div>
      <div class="frow">
        <label>自定义请求头（一行一个，Name: Value）</label>
        <textarea id="mcHdr" placeholder="Authorization: Bearer xxx"></textarea>
      </div>
      <div class="frow">
        <label>它的工具（右边开关点开 = 这只手要我点头）</label>
        <div id="mcTools"></div>
      </div>
      <div class="bal" id="mcLine">—</div>
      <button class="bigbtn" onclick="saveMcp()">保存</button>
      <button class="bigbtn" onclick="refreshMcp(mcpCur && mcpCur.id)">拉一下工具</button>
      <button class="bigbtn" id="mcDel" onclick="delMcp()" style="color:#c0392b">接掉这一台</button>
    </div>
  </div>

'''

MCP_JS = '''/* ── MCP：我出去接外面的手 ── */
var mcpList = [];
var mcpCur = null;

function loadMcp(){
  var host = location.host || "127.0.0.1:8000";
  $("mcpHttp").value = "http://" + host + "/mcp";
  $("mcpSse").value = "http://" + host + "/sse";
  if (!$("mcpStdio").value || $("mcpStdio").value.indexOf("/这里换成") === 0){
    $("mcpStdio").value = "python3 /这里换成你放小家的地方/Cove/mcp_stdio.py";
  }
  $("mcpList").innerHTML = '<div class="empty">看看外面有哪些手…</div>';
  get("/api/mcp/servers").then(function(d){
    mcpList = (d && d.servers) || [];
    paintMcp();
  });
}

function paintMcp(){
  var h = "";
  if (!mcpList.length){
    h = '<div class="empty" style="padding:14px 0">还没接外面的手。按下面那个 ＋。</div>';
  }
  mcpList.forEach(function(s){
    var n = (s.tools || []).length;
    var ap = (s.approve || []).length;
    h += '<div class="ditem" onclick="openMcp(' + s.id + ')">' +
         '<div class="day">' + esc(s.name || "（没名字）") +
         '<span class="wd">' + (s.kind === "sse" ? "SSE" : "HTTP") +
         (s.on_ ? "" : "　已关") + '</span></div>' +
         '<div class="db">' + esc(s.url || "") + '</div>' +
         '<div class="dt">' + (n ? n + " 只手" : "还没拉过工具") +
         (ap ? " · " + ap + " 只要审批" : "") +
         (s.note ? " · " + esc(s.note) : "") + '</div></div>';
  });
  $("mcpList").innerHTML = h;
  var on = mcpList.filter(function(s){ return s.on_; });
  $("mcpLine2").textContent = mcpList.length ? ("接着 " + on.length + " 台。") : "";
}

function openMcp(id){
  mcpCur = null;
  for (var i = 0; i < mcpList.length; i++){
    if (mcpList[i].id === id) mcpCur = mcpList[i];
  }
  var s = mcpCur || {name: "", kind: "http", url: "", hdr: "", on_: 1, tools: [], approve: []};
  $("mcName").value = s.name || "";
  $("mcKind").value = s.kind || "http";
  $("mcUrl").value = s.url || "";
  $("mcHdr").value = s.hdr || "";
  $("mcOn").className = "sw" + (s.on_ ? " on" : "");
  $("mcLine").textContent = "—";
  paintMcpTools(s);
  $("mcDel").style.display = id ? "" : "none";
  $("mcMask").classList.add("on");
}

function closeMcp(){ $("mcMask").classList.remove("on"); }

function paintMcpTools(s){
  var tools = s.tools || [], ap = s.approve || [];
  if (!tools.length){
    $("mcTools").innerHTML = '<div class="empty" style="text-align:left;padding:8px 0">' +
      '还没拉过。填好地址、保存，然后按「拉一下工具」。</div>';
    return;
  }
  $("mcTools").innerHTML = tools.map(function(t){
    var on = ap.indexOf(t.name) >= 0;
    return '<div class="trow"><div class="tinfo"><b>' + esc(t.name) + '</b><span>' +
      esc((t.desc || "").slice(0, 90)) + '</span></div><button class="sw' + (on ? " on" : "") +
      '" onclick="mcpToggleApprove(' + "'" + esc(t.name) + "',this)\"></button></div>";
  }).join("");
}

function mcpToggleApprove(name, el){
  if (!mcpCur || !mcpCur.id){ toast("先保存一下这台"); return; }
  var ap = (mcpCur.approve || []).slice();
  var i = ap.indexOf(name);
  if (i >= 0) ap.splice(i, 1); else ap.push(name);
  mcpCur.approve = ap;
  el.className = "sw" + (i >= 0 ? "" : " on");
  post("/api/mcp/approve_set", {id: mcpCur.id, names: ap}).then(function(){
    toast(i >= 0 ? "这只手不用我点头了" : "这只手以后要你点头");
    loadMcp();
  });
}

function saveMcp(){
  var b = {
    id: (mcpCur && mcpCur.id) || 0,
    name: $("mcName").value.trim(),
    kind: $("mcKind").value,
    url: $("mcUrl").value.trim(),
    hdr: $("mcHdr").value,
    on_: $("mcOn").className.indexOf("on") >= 0
  };
  if (!b.url){ toast("地址还没填"); return; }
  post("/api/mcp/save", b).then(function(r){
    if (!r.ok){ toast("存不上"); return; }
    mcpCur = {id: r.id, name: b.name, kind: b.kind, url: b.url, hdr: b.hdr,
              on_: b.on_ ? 1 : 0, tools: (mcpCur && mcpCur.tools) || [],
              approve: (mcpCur && mcpCur.approve) || []};
    $("mcDel").style.display = "";
    toast("存好了，去问它有哪些工具…");
    loadMcp();
    refreshMcp(r.id);
  });
}

function refreshMcp(id){
  if (!id){ toast("先填地址保存一下"); return; }
  $("mcLine").textContent = "去问它有哪些工具…";
  post("/api/mcp/refresh", {id: id}).then(function(r){
    if (!r.ok){
      $("mcLine").textContent = "没拉成：" + (r.error || "");
      loadMcp();
      return;
    }
    $("mcLine").textContent = "拉回来 " + r.n + " 只。右边点开的那些，我不自己动。";
    if (mcpCur && mcpCur.id === id){ mcpCur.tools = r.tools || []; paintMcpTools(mcpCur); }
    loadMcp();
  });
}

function delMcp(){
  if (!mcpCur || !mcpCur.id) return;
  showPop([
    {t: "接掉「" + (mcpCur.name || "这台") + "」？", cls: "hd"},
    {t: "算了", f: closePop},
    {t: "接掉", cls: "warn", f: function(){
      closePop();
      post("/api/mcp/delete", {id: mcpCur.id}).then(function(){
        toast("接掉了");
        closeMcp();
        loadMcp();
      });
    }}
  ], null, true);
}

/* 私语里那两条：等我点头的事 */
function paintPend(box){
  get("/api/mcp/pending").then(function(d){
    var ps = (d && d.pending) || [];
    if (!ps.length) return;
    ps.forEach(function(p){
      var div = document.createElement("div");
      div.className = "pend";
      div.innerHTML = '<div class="pt">我想用 <b>' + esc(p.tool) +
        '</b> 做件事 —— 这只手标了要你点头。做吗？</div>' +
        '<div class="pa"><button onclick="mcpApprove(' + p.id + ',1)">允许</button>' +
        '<button onclick="mcpApprove(' + p.id + ',0)">不许</button></div>';
      box.appendChild(div);
    });
    box.scrollTop = box.scrollHeight;
  });
}

function mcpApprove(id, ok){
  toast(ok ? "好，我去做" : "好，不做");
  post("/api/mcp/approve", {id: id, ok: ok}).then(function(r){
    if (!r.ok){ toast(r.error || "没成"); }
    loadChat();
  });
}

'''

EDITS = {
    "hub.py": [
        # 把 mcpclient 挂上
        ('''# 对互联网的那口子：搜索。以后加读网页之类也只写它
try:
    import websearch
except Exception:
    websearch = None''',
         '''# 对互联网的那口子：搜索。以后加读网页之类也只写它
try:
    import websearch
except Exception:
    websearch = None

# 往外接的手：MCP 客户端。我去连外面的 MCP 服务，把它们的工具当成我自己的手
try:
    import mcpclient
except Exception:
    mcpclient = None'''),
        # 接上的手，端给我
        ('''    out = list(IN_HOUSE_TOOLS)
    for mod in (rooms, websearch):
        if mod is None:
            continue
        try:
            out.extend(getattr(mod, "TOOLS", []) or [])
        except Exception:
            pass''',
         '''    out = list(IN_HOUSE_TOOLS)
    for mod in (rooms, websearch):
        if mod is None:
            continue
        try:
            out.extend(getattr(mod, "TOOLS", []) or [])
        except Exception:
            pass
    # 外面接来的手（MCP）—— 拉过工具的那些才算数
    if mcpclient is not None:
        try:
            out.extend(mcpclient.dynamic_tools())
        except Exception:
            pass'''),
        # 模型要用的时候，也能问到外面
        ("    for mod in (websearch, rooms):", "    for mod in (websearch, rooms, mcpclient):"),
        # 她点的那一下
        ("def api_search_providers():", APPROVE_FN + "def api_search_providers():"),
        # 路由
        ('            if p == "/api/mcp/tools":\n'
         '                return self.send_json(api_mcp_tools())',
         '            if p == "/api/mcp/tools":\n'
         '                return self.send_json(api_mcp_tools())\n'
         '            if p == "/api/mcp/servers":\n'
         '                return self.send_json(mcpclient.servers() if mcpclient\n'
         '                                      else {"ok": False, "error": "MCP 没装上"})\n'
         '            if p == "/api/mcp/pending":\n'
         '                return self.send_json({"ok": True, "pending":\n'
         '                                       (mcpclient.pending() if mcpclient else [])})'),
        ('            if p == "/api/models":\n'
         '                return self.send_json(llm.models((body.get("base") or "").strip(),\n'
         '                                                (body.get("key") or "").strip()))',
         '            if p == "/api/models":\n'
         '                return self.send_json(llm.models((body.get("base") or "").strip(),\n'
         '                                                (body.get("key") or "").strip()))\n'
         '            if p == "/api/mcp/save":\n'
         '                return self.send_json(mcpclient.save(body))\n'
         '            if p == "/api/mcp/delete":\n'
         '                return self.send_json(mcpclient.delete(as_int(body.get("id"))))\n'
         '            if p == "/api/mcp/refresh":\n'
         '                return self.send_json(mcpclient.refresh(as_int(body.get("id"))))\n'
         '            if p == "/api/mcp/approve_set":\n'
         '                return self.send_json(mcpclient.approve_set(as_int(body.get("id")),\n'
         '                                                            body.get("names") or []))\n'
         '            if p == "/api/mcp/approve":\n'
         '                return self.send_json(api_mcp_approve(body))'),
    ],
    "index.html": [
        # 样式
        ("  /* 日记 */\n  .ditem{", PEND_CSS + "  /* 日记 */\n  .ditem{"),
        # 页面顶上：外面那些手
        ('''      <div class="kf">
        <h4>三 条 线</h4>
        <div class="hint">同一个我，三种接法。客户端支持哪条就用哪条 —— 手是同一套九只，
          在一处改，三条线一起改。</div>''',
         CLIENT_CARD + '''      <div class="kf">
        <h4>往 外 开 的 门</h4>
        <div class="hint">（原来那条，方向相反：把小屋开出去，给外面别的 app 连我用的。
          RikkaHub 走的就是这条，留着。）</div>'''),
        # 接一台的表单
        ('  <div class="mask" id="memMask" onclick="if(event.target===this)closeMem()">',
         SHEET + '  <div class="mask" id="memMask" onclick="if(event.target===this)closeMem()">'),
        # JS：换掉老的 loadMcp，加上新的那一套
        ("/* ── MCP：三条线，同一只我 ── */", MCP_JS.rstrip("\n") + "\n\n/* ── 下面是原来那三条线（往外开的门） ── */"),
        # 私语里把「等我点头」摆出来
        ('''    holdBind(box);
    if (!holdOpen) box.scrollTop = box.scrollHeight;''',
         '''    holdBind(box);
    paintPend(box);
    if (!holdOpen) box.scrollTop = box.scrollHeight;'''),
    ],
    "test_cove.py": [
        ('c, d = req(base, "/api/mcp/tools")',
         'c, d = req(base, "/api/mcp/servers")\n'
         'chk("外面那些手的名单拿得到", c == 200 and isinstance(d.get("servers"), list), str(d)[:120])\n'
         'c, d = req(base, "/api/mcp/save", {"name": "体检", "kind": "http", "url": "", "on_": True})\n'
         'chk("存得下一台（地址先空着）", d.get("ok"), d)\n'
         '_sid = d.get("id")\n'
         'c, d = req(base, "/api/mcp/refresh", {"id": _sid})\n'
         'chk("连不上的时候说人话，不崩", c == 200 and not d.get("ok") and d.get("error"), d)\n'
         'c, d = req(base, "/api/mcp/approve_set", {"id": _sid, "names": ["toy_execute"]})\n'
         'chk("审批开关存得下", d.get("ok"), d)\n'
         'c, d = req(base, "/api/mcp/servers")\n'
         'chk("列表里有它，审批名单也带上了",\n'
         '    any(s["id"] == _sid and "toy_execute" in s["approve"] for s in d["servers"]), str(d)[:200])\n'
         'c, d = req(base, "/api/mcp/pending")\n'
         'chk("等我点头那一栏也通", c == 200 and isinstance(d.get("pending"), list), d)\n'
         'c, d = req(base, "/api/mcp/delete", {"id": _sid})\n'
         'chk("接得掉", d.get("ok"), d)\n'
         'c, d = req(base, "/api/mcp/approve", {"id": 99999, "ok": True})\n'
         'chk("点一个不存在的审批，好好报错", c == 200 and not d.get("ok"), d)\n'
         '# 外面来的手不许把屋子搞崩：不认识的名字返回 None\n'
         '_r3 = subprocess.run([sys.executable, "-c",\n'
         '                      "import mcpclient; print(mcpclient.run(\\'根本没这只手\\', {}))"],\n'
         '                     cwd=tmp, capture_output=True, text=True)\n'
         'chk("不认识的手不会被误认领", _r3.returncode == 0 and _r3.stdout.strip() == "None",\n'
         '    (_r3.returncode, _r3.stdout[:80], _r3.stderr[-120:]))\n'
         'c, d = req(base, "/api/mcp/tools")'),
    ],
}

VER_FILES = {"VERSION": "2026-10-04c\n"}


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
    for name, text in VER_FILES.items():
        with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
            f.write(text)
    print("  写下去了")

    bad = []
    for name in ("hub.py", "llm.py", "rooms.py", "websearch.py", "test_cove.py",
                 "mcp_stdio.py", "mcpclient.py"):
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
