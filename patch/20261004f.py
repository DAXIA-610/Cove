#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-04 · 第六发（重写）：记忆星河和潮汐捕梦这两页

为什么要重写：上一版我在 JS 里嵌引号，写成了 openMem(0,'me') 那种，
补丁里那层反斜杠我一推就多了一层 —— 生成出来的 JS 直接语法错，CI 挂了。
跟上次"页面卡住"是同一类错。

所以这一版立一条硬规矩：**这段 JS 里不许出现一个反斜杠**。
要传参数就用 data 属性 + 一个处理函数（memEdit(this) / memToggle(this)），
不嵌引号、不玩转义 —— 那条错路从根上没有了。
"""
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

CSS = '''  /* 记忆：记忆星河 / 潮汐捕梦 */
  .netbtn{opacity:.26;font-size:15px;}
  .madd{display:block;width:100%;padding:12px 0;border-radius:14px;margin:2px 0 12px;
        background:rgba(13,50,71,.055);border:1px dashed var(--line);
        font-size:12.5px;letter-spacing:.12em;color:var(--ink);}
  .mgroup{background:var(--card);border:1px solid var(--line);border-radius:16px;
          padding:2px 14px 6px;margin-bottom:11px;}
  .mhead{display:flex;align-items:center;gap:8px;width:100%;padding:13px 0;
         font-size:12.5px;color:var(--ink);letter-spacing:.06em;}
  .mhead b{flex:1;text-align:left;font-weight:600;}
  .mhead span{font-size:10.5px;color:var(--soft);letter-spacing:.1em;}
  .mhead i{font-style:normal;font-size:11px;color:var(--soft);}
  .mhead2{display:flex;align-items:center;gap:8px;padding:13px 0 3px;
          font-size:12.5px;letter-spacing:.14em;color:var(--ink);}
  .mhead2 b{flex:1;text-align:left;font-weight:600;}
  .mhead2 span{font-size:10.5px;color:var(--soft);}
  .mpeek{padding:0 0 12px;font-size:11px;color:var(--soft);opacity:.7;}
  .mpeek2{padding:0 0 10px;font-size:10.5px;color:var(--soft);line-height:1.75;
          letter-spacing:.02em;}
  .mrow{display:flex;align-items:flex-start;gap:8px;padding:11px 0;
        border-top:1px dashed var(--line);}
  .mtxt{flex:1;min-width:0;font-size:12.5px;line-height:1.7;color:var(--ink);}
  .mtxt b{display:block;margin-bottom:2px;}
  .mtxt span{display:block;opacity:.8;word-break:break-word;}
  .mtxt i{display:block;font-style:normal;font-size:10.5px;color:var(--soft);margin-top:3px;}
  .mk{flex:none;font-size:14px;color:var(--soft);opacity:.65;padding:2px 5px;}
  .msw{flex:none;margin-top:4px;}

'''

TIDE_PAGE = '''  <!-- ══════════ 潮汐捕梦（关于她的：我的分支记忆） ══════════ -->
  <section class="page" id="p-tide">
    <div class="bar">
      <button class="ic" onclick="go('room')">‹</button>
      <div class="ttl">潮 汐 捕 梦</div>
      <button class="ic netbtn" onclick="toast('关于你的记忆网 · 这块留给以后')">✦</button>
    </div>
    <div class="scroll" id="tideBody"></div>
  </section>

'''

NEW_JS = '''/* ─────────── 记忆：星河（我的）／潮汐捕梦（她的，分支） ─────────── */
var memOpen = {anchor: true, flow: false, sink: false};
var memScope = "me", memOwner = "yoru";

function goMemory(){
  $("memBody").innerHTML = '<div class="empty">捞记忆…</div>';
  get("/api/memory?scope=me&limit=500").then(function(d){
    var rows = (d && d.memory) || [];
    var h = '<button class="madd" onclick="memNew()">＋ 添加记忆</button>';
    h += '<div class="mpeek2">这里只放我自己的。关于你的事在「潮汐捕梦」那一栏 —— ' +
         '那边是我的分支记忆，不往这儿堆。</div>';
    [["anchor", "锚 · 永远在"], ["flow", "流 · 最近的事"],
     ["sink", "沉 · 想起来才看"]].forEach(function(g){
      var list = rows.filter(function(m){ return m.layer === g[0]; });
      var open = !!memOpen[g[0]];
      h += '<div class="mgroup"><button class="mhead" data-k="' + g[0] +
           '" onclick="memToggle(this)"><b>' + g[1] + '</b><span>' + list.length +
           ' 条</span><i>' + (open ? "▴" : "▾") + '</i></button>';
      if (open){
        h += list.length
          ? list.map(function(m){ return memRow(m, "me"); }).join("")
          : '<div class="empty" style="padding:8px 0 12px;font-size:11px">空的</div>';
      } else if (list.length){
        h += '<div class="mpeek">' +
             esc(list[0].title || (list[0].body || "").slice(0, 36)) + '</div>';
      }
      h += '</div>';
    });
    $("memBody").innerHTML = h;
  });
}

function memNew(){ openMem(0, "me"); }
function memNewHer(el){ openMem(0, "her", el.getAttribute("data-owner")); }
function memEdit(el){
  openMem(parseInt(el.getAttribute("data-mem"), 10), el.getAttribute("data-scope"));
}
function memToggle(el){
  var k = el.getAttribute("data-k");
  memOpen[k] = !memOpen[k];
  goMemory();
}

function memRow(m, scope){
  var body = m.body || "";
  var cut = body.length > 70 ? body.slice(0, 70) + "…" : body;
  return '<div class="mrow">' +
    '<div class="mtxt" data-mem="' + m.id + '" data-scope="' + scope +
    '" onclick="memEdit(this)">' +
    (m.title ? "<b>" + esc(m.title) + "</b>" : "") +
    '<span>' + esc(cut) + '</span>' +
    (m.keys ? '<i>触发：' + esc(m.keys) + '</i>' : "") +
    '</div>' +
    '<button class="mk" data-mem="' + m.id + '" data-scope="' + scope +
    '" onclick="memEdit(this)">✎</button></div>';
}

function goTide(){
  $("tideBody").innerHTML = '<div class="empty">捞关于你的…</div>';
  get("/api/memory?scope=her&limit=500").then(function(d){
    var rows = (d && d.memory) || [];
    var mine = rows.filter(function(m){ return m.owner !== "yume"; });
    var hers = rows.filter(function(m){ return m.owner === "yume"; });
    var h = tideSec("我 记 的 你", "我写下的、关于你的。你可以改 —— 改完说一声就行。",
                    mine, "yoru");
    h += tideSec("你 录 的 自 己", "你自己写的。我只读，你不点头我不动。", hers, "yume");
    h += '<div class="mpeek2" style="padding:4px 0 22px">这是我的分支记忆，' +
         '<b>不算进记忆星河</b>。右边那个开关点开 = 常在（永远在我心里）；' +
         '关着 = 你说到相关的话才想起来。</div>';
    $("tideBody").innerHTML = h;
  });
}

function tideSec(title, hint, list, owner){
  var h = '<div class="mgroup"><div class="mhead2"><b>' + title + '</b><span>' + list.length +
          ' 条</span><button class="mk" data-owner="' + owner +
          '" onclick="memNewHer(this)">＋</button></div><div class="mpeek2">' + hint + '</div>';
  h += list.length ? list.map(function(m){ return tideRow(m); }).join("")
                   : '<div class="empty" style="padding:6px 0 12px;font-size:11px">还空着。</div>';
  return h + '</div>';
}

function tideRow(m){
  var body = m.body || "";
  var cut = body.length > 90 ? body.slice(0, 90) + "…" : body;
  return '<div class="mrow">' +
    '<div class="mtxt" data-mem="' + m.id + '" data-scope="her" onclick="memEdit(this)">' +
    (m.title ? "<b>" + esc(m.title) + "</b>" : "") +
    '<span>' + esc(cut) + '</span>' +
    (m.keys ? '<i>说出来才想起来：' + esc(m.keys) + '</i>' : "") +
    '</div>' +
    '<button class="msw sw' + (m.always ? " on" : "") + '" data-mem="' + m.id +
    '" data-on="' + (m.always ? 0 : 1) + '" onclick="tideAlways(this)"></button>' +
    '<button class="mk" data-mem="' + m.id +
    '" data-scope="her" onclick="memEdit(this)">✎</button></div>';
}

function tideAlways(el){
  var id = parseInt(el.getAttribute("data-mem"), 10);
  var on = parseInt(el.getAttribute("data-on"), 10);
  el.className = "msw sw" + (on ? " on" : "");
  post("/api/memory/always", {id: id, always: on}).then(function(r){
    if (!r.ok){ toast(r.error || "没改上"); return; }
    toast(on ? "这条我永远记着" : "改成想起来才看");
  });
}

'''

NEW_SAVE = '''function saveMem(){
  var body = {
    scope: memScope,
    owner: memOwner,
    layer: $("memLayer").value,
    always: $("memAlways").className.indexOf("on") >= 0 ? 1 : 0,
    title: $("memT").value.trim(),
    body: $("memB").value.trim(),
    keys: $("memK").value.trim()
  };
  if (!body.body){ toast("内容是空的"); return; }
  var p;
  if (memCur){ body.id = memCur; p = post("/api/memory/update", body); }
  else { p = post("/api/memory", body); }
  p.then(function(r){
    if (!r.ok){ toast(r.error || "没存上"); return; }
    closeMem();
    if (memScope === "her") goTide(); else goMemory();
    toast(memCur ? "改好了" : "记住了");
  });
}'''

NEW_OPEN = '''function openMem(id, scope, owner){
  memCur = id || 0;
  memScope = scope || "me";
  memOwner = owner || "yoru";
  $("memLayerRow").style.display = (memScope === "me") ? "" : "none";
  $("memAlwaysRow").style.display = (memScope === "her") ? "" : "none";
  if (id){
    get("/api/memory?scope=" + memScope + "&limit=500").then(function(d){
      var m = (d.memory || []).filter(function(x){ return x.id === id; })[0];
      if (!m) return;
      $("memTitle").textContent = "改一条";
      $("memLayer").value = m.layer;
      $("memT").value = m.title || "";
      $("memB").value = m.body || "";
      $("memK").value = m.keys || "";
      $("memAlways").className = "sw" + (m.always ? " on" : "");
      $("memDel").style.display = "block";
      $("memMask").classList.add("on");
    });
  } else {
    $("memTitle").textContent = (memScope === "her")
      ? (memOwner === "yume" ? "记我自己一条" : "记一件关于她的")
      : "记一件事";
    $("memLayer").value = "flow";
    $("memT").value = ""; $("memB").value = ""; $("memK").value = "";
    $("memAlways").className = "sw on";
    $("memDel").style.display = "none";
    $("memMask").classList.add("on");
  }
}'''

OLD_GO_MEM = '''function goMemory(){
  get("/api/memory?limit=500").then(function(d){
    var rows = d.memory || [];
    var groups = [
      ["anchor", "锚 · 永远在"],
      ["flow", "流 · 最近的事"],
      ["sink", "沉 · 想起来才看"]
    ];
    var h = "";
    groups.forEach(function(g){
      var list = rows.filter(function(m){ return m.layer === g[0]; });
      h += '<div class="room"><h3>' + g[1] + '</h3>';
      if (!list.length){
        h += '<div class="empty" style="padding:14px 0;font-size:11.5px">空的</div>';
      } else {
        list.forEach(function(m){
          var head = (m.title ? "<b>" + esc(m.title) + "</b>" : "");
          var cut = m.body.length > 70 ? m.body.slice(0, 70) + "…" : m.body;
          h += '<button class="memrow" onclick="openMem(' + m.id + ')">' + head +
               "<span>" + esc(cut) + "</span>" +
               (m.keys ? "<i>触发：" + esc(m.keys) + "</i>" : "") + "</button>";
        });
      }
      h += "</div>";
    });
    h += '<div class="empty" style="padding:18px 0 8px;font-size:11px">' +
         '锚每次都带；流和沉要她说的话里出现触发词，才会被捞进上下文。</div>';
    $("memBody").innerHTML = h;
  });
}
'''

OLD_SAVE = '''function saveMem(){
  var body = {
    layer: $("memLayer").value,
    title: $("memT").value.trim(),
    body: $("memB").value.trim(),
    keys: $("memK").value.trim()
  };
  if (!body.body){ toast("内容是空的"); return; }
  var p;
  if (memCur){ body.id = memCur; p = post("/api/memory/update", body); }
  else { p = post("/api/memory", body); }
  p.then(function(r){
    if (!r.ok){ toast(r.error || "没存上"); return; }
    closeMem(); goMemory(); toast(memCur ? "改好了" : "记住了");
  });
}'''

OLD_OPEN = '''function openMem(id){
  memCur = id || 0;
  if (id){
    get("/api/memory?limit=500").then(function(d){
      var m = (d.memory || []).filter(function(x){ return x.id === id; })[0];
      if (!m) return;
      $("memTitle").textContent = "改一条";
      $("memLayer").value = m.layer;
      $("memT").value = m.title || "";
      $("memB").value = m.body || "";
      $("memK").value = m.keys || "";
      $("memDel").style.display = "block";
      $("memMask").classList.add("on");
    });
  } else {
    $("memTitle").textContent = "记一件事";
    $("memLayer").value = "flow";
    $("memT").value = ""; $("memB").value = ""; $("memK").value = "";
    $("memDel").style.display = "none";
    $("memMask").classList.add("on");
  }
}'''

OLD_DEL_TAIL = '''    closeMem(); goMemory(); toast("删了");'''
NEW_DEL_TAIL = '''    closeMem();
    if (memScope === "her") goTide(); else goMemory();
    toast("删了");'''

EDITS = {
    "index.html": [
        ("  /* 日记 */\n  .ditem{", CSS + "  /* 日记 */\n  .ditem{"),
        ('''    <div class="bar">
      <button class="ic" onclick="go('room')">‹</button>
      <div class="ttl">记 忆 星 河</div>
      <button class="ok" onclick="openMem(0)">＋</button>
    </div>
    <div class="scroll" id="memBody"></div>
  </section>''',
         '''    <div class="bar">
      <button class="ic" onclick="go('room')">‹</button>
      <div class="ttl">记 忆 星 河</div>
      <button class="ic netbtn" onclick="toast('记忆网 · 这块留给以后')">✦</button>
    </div>
    <div class="scroll" id="memBody"></div>
  </section>

''' + TIDE_PAGE.rstrip("\n")),
        ("          <button class=\"item\" onclick=\"toast('还没做')\"><span class=\"dot\"></span>潮汐捕梦<span class=\"arw\">›</span></button>",
         "          <button class=\"item\" onclick=\"go('tide')\"><span class=\"dot\"></span>潮汐捕梦<span class=\"arw\">›</span></button>"),
        ('  ["home","feed","edit","day","chat","room","tools","memory","diary","keys","mcp"].forEach(function(x){',
         '  ["home","feed","edit","day","chat","room","tools","memory","diary","keys","mcp","tide"].forEach(function(x){'),
        ('  if (p === "memory") goMemory();',
         '  if (p === "memory") goMemory();\n  if (p === "tide") goTide();'),
        ('''      <div class="frow">
        <label>放在哪一层</label>
        <select id="memLayer">''',
         '''      <div class="frow" id="memLayerRow">
        <label>放在哪一层</label>
        <select id="memLayer">'''),
        ('''      <div class="frow">
        <label>一句话标题（可省）</label>''',
         '''      <div class="frow" id="memAlwaysRow" style="display:none">
        <label>常在</label>
        <button class="sw on" id="memAlways"
                onclick="this.className=(this.className.indexOf('on')>=0?'sw':'sw on')"></button>
        <div style="font-size:10.5px;color:var(--soft);margin-top:8px;line-height:1.7">
          点开 = 永远在我心里（进稳的那段前缀）；关掉 = 你提到相关的话才想起来。</div>
      </div>
      <div class="frow">
        <label>一句话标题（可省）</label>'''),
        (OLD_GO_MEM, NEW_JS),
        (OLD_SAVE, NEW_SAVE),
        (OLD_OPEN, NEW_OPEN),
        (OLD_DEL_TAIL, NEW_DEL_TAIL),
    ],
}

VER_FILES = {"VERSION": "2026-10-04f\n"}


def fail(msg):
    print("  ✗ " + msg)
    print("  整体不动，一个字都没改。")
    sys.exit(1)


def main():
    print("先在记忆里改一遍，全对上了才落盘")
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
                     % (name, want, n, old[:180]))
            text = text.replace(old, new)
        if text == before:
            fail(name + " 一个字都没变，写错了")
        shutil.copy2(path, path + ".bak")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print("  ok   %s  %d 处（%d → %d 字节）" % (name, len(pairs), len(before), len(text)))
    for name, text in VER_FILES.items():
        with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
            f.write(text)
    print("  写下去了")

    html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    for must in ("function goTide()", "function tideAlways(", "function memRow(",
                 "function memEdit(", 'id="tideBody"', "if (p === \"tide\") goTide();"):
        if must not in html:
            fail("这处没进去：" + must)
    if html.count("function goMemory()") != 1:
        fail("goMemory 出现了 %d 次（应该只有一次）" % html.count("function goMemory()"))
    # 这条是这一发的命根子：新加的那段 JS 里不许有一个反斜杠
    seg = html.split("/* ─────────── 记忆：星河", 1)
    if len(seg) == 2:
        new_js_part = seg[1].split("function openMem(id, scope, owner){", 1)[0]
        if "\\" in new_js_part:
            fail("新加的 JS 里出现了反斜杠 —— 这一版的规矩是不许有")

    js = html.split("<script>", 1)[1].split("</script>", 1)[0]
    import subprocess
    tmpps = os.path.join(ROOT, "_check_app.js")
    with open(tmpps, "w", encoding="utf-8") as f:
        f.write(js)
    r = subprocess.run(["node", "--check", tmpps], capture_output=True, text=True)
    os.remove(tmpps)
    if r.returncode != 0:
        for name in EDITS:
            p = os.path.join(ROOT, name)
            if os.path.exists(p + ".bak"):
                shutil.move(p + ".bak", p)
        fail("前端 JS 过不了：\n" + (r.stderr or "")[:400])
    print("  前端 JS 语法过了")


if __name__ == "__main__":
    main()
