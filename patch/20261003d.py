#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-03 · 第四发：钥匙

她说：DeepSeek 现在是 v4flash / pro 还有一个视觉模型；搜索她有 tavily 的 key；
视觉她 DS 和硅基流动两家都有；把供应商写进设置（系统的房间），给她一个填 key 的通道，
填完就能直接用。

所以这一发做「钥匙」——一间专门放钥匙的屋子：

  说话  哪一家 / 接口地址 / key / 模型
  看图  留空就跟说话那家一样（flash 自己带眼睛）；想另找一家看图的填这里
  搜索  哪一家 / key / 接口地址
  余额  查一眼这把钥匙还能花多少

底下两件顺手的事：
  · 模型名我不猜。给一个「拉一下模型名单」，直接问那家它手上有哪些模型，填进下拉里。
    （以后谁家改名字都不用我改代码。）
  · 系统房间（Cove 之湾）的 Settings 从此有个真去处；聊天页那个模型小按钮和 🔍 也指向这儿。
    老的那张「模型」抽屉连壳一起删掉 —— 留着两套一定会打架（今天就是）。
"""
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

PRESETS = '''
# 界面上「哪一家」的那份名单。kind：chat 说话的 / search 搜索的。
# 地址我没瞎写：DeepSeek 的 base 不带 /v1 也能到 /chat/completions，
# 硅基流动必须带 /v1 —— 这是两家自己的规矩。
PRESETS = [
    {"id": "deepseek", "name": "DeepSeek 深度求索", "kind": "chat",
     "base": "https://api.deepseek.com", "hint": "sk- 开头",
     "models": ["deepseek-flash", "deepseek-v4-pro"]},
    {"id": "siliconflow", "name": "硅基流动 SiliconFlow", "kind": "chat",
     "base": "https://api.siliconflow.cn/v1", "hint": "sk- 开头",
     "models": ["Qwen/Qwen3-VL-32B-Instruct", "deepseek-ai/DeepSeek-V4-Flash"]},
    {"id": "moonshot", "name": "月之暗面 Kimi", "kind": "chat",
     "base": "https://api.moonshot.cn/v1", "hint": "sk- 开头",
     "models": ["moonshot-v1-32k"]},
    {"id": "openai", "name": "OpenAI", "kind": "chat",
     "base": "https://api.openai.com/v1", "hint": "sk- 开头",
     "models": ["gpt-4o-mini", "gpt-4o"]},
    {"id": "tavily", "name": "Tavily（搜索）", "kind": "search",
     "base": "https://api.tavily.com", "hint": "tvly- 开头", "models": []},
    {"id": "brave", "name": "Brave（搜索）", "kind": "search",
     "base": "", "hint": "Brave 的 key", "models": []},
    {"id": "bocha", "name": "博查（搜索）", "kind": "search",
     "base": "https://api.bochaai.com", "hint": "sk- 开头", "models": []},
]


'''

MODELS_FN = '''def models(base, key, timeout=20):
    """问她填的那家：你手上到底有哪些模型。

    名字我不猜 —— 让她自己挑。以后谁家改名字、上新的，界面自己跟上。
    """
    if not base:
        return {"ok": False, "error": "先填接口地址"}
    if not key:
        return {"ok": False, "error": "先填 key"}
    url = base.strip().rstrip("/") + "/models"
    req = urllib.request.Request(url, headers=_headers(key), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": "对面回了 %s" % e.code}
    except Exception as e:
        return {"ok": False, "error": "没连上（%s）" % type(e).__name__}
    ids = []
    for it in (d.get("data") or d.get("models") or []):
        mid = (it.get("id") or it.get("name") or "") if isinstance(it, dict) else str(it)
        if mid:
            ids.append(mid)
    ids = sorted(set(ids))
    return {"ok": True, "n": len(ids), "models": ids[:400]}


'''

CONF_FN = '''def llm_conf(has_image=False):
    """这一轮该用哪家说话。

    默认是「说话」那家。这一轮带了图、而且她另外配了「看图」那家，就换看图那家 ——
    她说她 DS 和硅基流动两家都有，哪家顺手填哪家。
    """
    with db() as c:
        base = get_setting(c, "api_base") or llm.DEFAULT_BASE
        key = get_setting(c, "api_key")
        model = llm.fix_model(get_setting(c, "model"))
        if has_image:
            vk = (get_setting(c, "vision_key") or "").strip()
            vm = (get_setting(c, "vision_model") or "").strip()
            if vk and vm:
                return (get_setting(c, "vision_base") or base), vk, vm
    return base, key, model


'''

KEYS_CSS = '''  /* 钥匙：一间放 key 的屋子 */
  .kf{background:var(--card);border:1px solid var(--line);border-radius:16px;
      padding:15px 16px;margin-bottom:12px;}
  .kf h4{margin:0 0 4px;font-size:12.5px;letter-spacing:.14em;color:var(--ink);}
  .kf .hint{font-size:10.5px;color:var(--soft);line-height:1.75;margin:6px 0 2px;}
  .kf label{display:block;font-size:10px;letter-spacing:.16em;color:var(--soft);
            margin:12px 0 6px;}
  .kf input,.kf select{width:100%;padding:11px 12px;border-radius:12px;
      border:1px solid var(--line);background:rgba(13,50,71,.035);color:var(--ink);
      font-size:13px;outline:none;font-family:inherit;}
  .kf .row2{display:flex;gap:8px;margin-top:13px;}
  .kf .row2 button{flex:1;padding:11px 0;border-radius:12px;
      background:rgba(13,50,71,.07);font-size:12.5px;color:var(--ink);}
  .kf .row2 button.kk{background:rgba(140,155,171,.22);}
  .kf .bal{font-size:11px;color:var(--soft);margin-top:11px;line-height:1.7;
           letter-spacing:.02em;}

'''

KEYS_PAGE = '''  <!-- ══════════ 钥匙（供应商 / key） ══════════ -->
  <section class="page" id="p-keys">
    <div class="bar"><button class="ic" onclick="go('room')">‹</button><div class="ttl">钥 匙</div><div class="ic"></div></div>
    <div class="scroll">

      <div class="kf">
        <h4>说 话</h4>
        <div class="hint">谁在跟我说话。填完这一块，小屋就能开口了。</div>
        <label>哪一家</label>
        <select id="kChatProv" onchange="provPicked('chat')"></select>
        <label>接口地址</label>
        <input id="kChatBase" placeholder="https://api.deepseek.com" autocapitalize="off" autocorrect="off">
        <label>Key（只躺在这台手机里，谁也不给）</label>
        <input id="kChatKey" type="password" placeholder="sk-…" autocapitalize="off" autocorrect="off">
        <label>模型（可以直接打字，也可以点下拉里挑）</label>
        <input id="kChatModel" list="kChatList" placeholder="deepseek-flash" autocapitalize="off" autocorrect="off">
        <datalist id="kChatList"></datalist>
        <div class="row2">
          <button onclick="pullModels('chat')">拉一下模型名单</button>
          <button class="kk" onclick="saveKeys('chat')">存起来</button>
        </div>
        <div class="bal" id="kChatLine">—</div>
      </div>

      <div class="kf">
        <h4>看 图</h4>
        <div class="hint">留空就跟「说话」那家一样 —— deepseek-flash 自己就长着眼睛。
          想换一家专门看图的（比如硅基流动的 Qwen3-VL），把这一块填上。</div>
        <label>哪一家</label>
        <select id="kVProv" onchange="provPicked('vision')"></select>
        <label>接口地址</label>
        <input id="kVBase" placeholder="跟说话那家一样" autocapitalize="off" autocorrect="off">
        <label>Key</label>
        <input id="kVKey" type="password" placeholder="留空 = 不单独配" autocapitalize="off" autocorrect="off">
        <label>模型</label>
        <input id="kVModel" list="kVList" placeholder="留空 = 用说话那个模型看" autocapitalize="off" autocorrect="off">
        <datalist id="kVList"></datalist>
        <div class="row2">
          <button onclick="pullModels('vision')">拉一下模型名单</button>
          <button class="kk" onclick="saveKeys('vision')">存起来</button>
        </div>
        <div class="bal" id="kVLine">—</div>
      </div>

      <div class="kf" id="searchBlock">
        <h4>搜 索</h4>
        <div class="hint">想让我知道外面正在发生什么，就得给我一把搜索的钥匙。
          填完按「试一下」，通了它就是我的第六只手。</div>
        <label>哪一家</label>
        <select id="kSProv" onchange="provPicked('search')"></select>
        <label>Key</label>
        <input id="kSKey" type="password" placeholder="tvly-…" autocapitalize="off" autocorrect="off">
        <label>接口地址（留空就用官方的）</label>
        <input id="kSBase" placeholder="https://api.tavily.com" autocapitalize="off" autocorrect="off">
        <div class="row2">
          <button onclick="probeSearch2()">试一下</button>
          <button class="kk" onclick="saveKeys('search')">存起来</button>
        </div>
        <div class="bal" id="kSLine">搜索：还没试过</div>
      </div>

      <div class="kf">
        <h4>余 额</h4>
        <div class="hint">这把钥匙还能花多少。</div>
        <div class="bal" id="kBalLine">—</div>
        <div class="row2"><button onclick="refreshBalance()">查一下余额</button></div>
      </div>

      <div class="empty" style="padding:4px 0 22px;font-size:10.5px">小屋 <span id="verLine2">—</span></div>
    </div>
  </section>

'''

KEYS_JS = '''/* ── 聊天页那个 🔍：直接去「钥匙」那页的搜索那一段 ── */
function openSearch(){
  go("keys");
  setTimeout(function(){
    var s = document.getElementById("searchBlock");
    if (s && s.scrollIntoView) s.scrollIntoView({block: "start"});
  }, 240);
}

/* ── 钥匙那间屋 ── */
var presets = [];
var KF = {
  chat:   {prov:"kChatProv", base:"kChatBase", key:"kChatKey", model:"kChatModel",
           list:"kChatList", line:"kChatLine"},
  vision: {prov:"kVProv",   base:"kVBase",   key:"kVKey",   model:"kVModel",
           list:"kVList",   line:"kVLine"},
  search: {prov:"kSProv",   base:"kSBase",   key:"kSKey",   model:"",
           list:"",         line:"kSLine"}
};

function loadKeys(){
  get("/api/presets").then(function(d){
    presets = (d.presets || []);
    fillProv("chat"); fillProv("vision"); fillProv("search");
    $("kChatLine").textContent = (S.api_key ? "已经有 key 了。" : "还没填 key —— 填了小屋才会开口。") +
                                 "模型现在是 " + (S.model || "deepseek-flash") + "。";
    $("kVLine").textContent = S.vision_key
      ? "看图走这一家：" + (S.vision_model || "（还没选模型，等于没配）")
      : "现在是留空的 —— 用说话那家的眼睛看。";
    $("kSLine").textContent = S.search_key ? "已经有 key 了，按「试一下」试试通不通。"
                                           : "还没填 key，搜索那只手现在动不了。";
  });
}

function curOf(kind){
  if (kind === "chat")   return {base: S.api_base || "", key: S.api_key || "", model: S.model || ""};
  if (kind === "vision") return {base: S.vision_base || "", key: S.vision_key || "",
                                 model: S.vision_model || ""};
  return {base: S.search_base || "", key: S.search_key || "", model: ""};
}

function provOf(kind, id){
  for (var i = 0; i < presets.length; i++){
    if (presets[i].kind === kind && presets[i].id === id) return presets[i];
  }
  return null;
}

function fillList(id, arr){
  if (!id) return;
  var el = $(id);
  if (!el) return;
  el.innerHTML = (arr || []).map(function(m){
    return '<option value="' + esc(m) + '">';
  }).join("");
}

function fillProv(kind){
  var k = KF[kind], cur = curOf(kind);
  var list = presets.filter(function(p){ return p.kind === kind; });
  var m = null;
  for (var i = 0; i < list.length; i++){
    if (list[i].base && list[i].base === cur.base) m = list[i];
  }
  $(k.prov).innerHTML = list.map(function(p){
    return '<option value="' + esc(p.id) + '">' + esc(p.name) + '</option>';
  }).join("") + '<option value="__custom">自己填一家</option>';
  $(k.prov).value = m ? m.id : "__custom";
  $(k.base).value = cur.base || (m ? m.base : "");
  $(k.key).value = cur.key || "";
  if (k.model) $(k.model).value = cur.model || "";
  fillList(k.list, (m && m.models) || []);
}

function provPicked(kind){
  var k = KF[kind];
  var p = provOf(kind, $(k.prov).value);
  if (!p) return;
  if (p.base) $(k.base).value = p.base;
  fillList(k.list, p.models || []);
  if (k.model && !$(k.model).value && p.models && p.models.length){
    $(k.model).value = p.models[0];
  }
}

function pullModels(kind){
  var k = KF[kind];
  $(k.line).textContent = "问它手上有哪些模型…";
  post("/api/models", {base: $(k.base).value.trim(), key: $(k.key).value.trim()}).then(function(r){
    if (!r.ok){ $(k.line).textContent = "拉不到：" + (r.error || "没成"); return; }
    fillList(k.list, r.models || []);
    $(k.line).textContent = "它手上有 " + r.n + " 个模型 —— 点模型那一栏，会掉下来让你挑。";
  });
}

function saveKeys(kind){
  var k = KF[kind];
  var base = $(k.base).value.trim();
  var key = $(k.key).value.trim();
  var model = k.model ? $(k.model).value.trim() : "";
  var b = {};
  if (kind === "chat"){
    b.api_base = base; b.api_key = key; b.model = model;
  } else if (kind === "vision"){
    b.vision_base = base; b.vision_key = key; b.vision_model = model;
  } else {
    b.search_base = base; b.search_key = key;
    b.search_provider = ($(k.prov).value === "__custom")
      ? (S.search_provider || "tavily") : $(k.prov).value;
  }
  post("/api/settings", b).then(function(r){
    if (!r.ok){ toast("存不上"); return; }
    Object.keys(b).forEach(function(x){ S[x] = b[x]; });
    paintModelChip();
    toast("存好了");
    loadKeys();
  });
}

function probeSearch2(){
  $("kSLine").textContent = "搜索：正在试…";
  post("/api/search/probe", {
    key: $("kSKey").value.trim(),
    provider: ($("kSProv").value === "__custom")
      ? (S.search_provider || "tavily") : $("kSProv").value,
    base: $("kSBase").value.trim()
  }).then(function(r){
    if (!r.ok){ $("kSLine").textContent = "搜索：" + (r.error || "没成"); return; }
    var t = (r.sample && r.sample[0] && r.sample[0].title) || "";
    $("kSLine").textContent = "搜索：通了，回来 " + r.n + " 条" + (t ? "｜" + t.slice(0, 30) : "");
  }).catch(function(){ $("kSLine").textContent = "搜索：没连上"; });
}

function openModel(){
  go("keys");
}

/* 下面这几个是老的「模型」抽屉留下的（界面搬到「钥匙」页了），留着不碍事 */

'''

EDITS = {
    "llm.py": [
        ('class LLMError(Exception):\n    """调不通的时候，把原因裹成人话抛出去。"""',
         PRESETS + 'class LLMError(Exception):\n    """调不通的时候，把原因裹成人话抛出去。"""'),
        ('def balance(api_key, base=None, timeout=30):',
         MODELS_FN + 'def balance(api_key, base=None, timeout=30):'),
    ],
    "hub.py": [
        # 看图那口子的设置键
        ('    # 搜索那口子\n    "search_provider", "search_key", "search_base",',
         '    # 看图那口子（留空 = 跟说话那家一样）\n'
         '    "vision_base", "vision_key", "vision_model",\n'
         '    # 搜索那口子\n    "search_provider", "search_key", "search_base",'),
        # 说话的选家（带了图就换看图那家）
        ('def _generate(user_text, drop_id=0):',
         CONF_FN + 'def _generate(user_text, drop_id=0):'),
        ('''    with db() as c:
        api_key = get_setting(c, "api_key")
        base = get_setting(c, "api_base") or llm.DEFAULT_BASE
        model = llm.fix_model(get_setting(c, "model"))

    if not api_key:
        return {"ok": True, "need_key": True, "reply": "",
                "error": "还没有填 API key——去「模型」那里填一下"}

    msgs = build_messages(user_text, drop_id)
    tools = all_tools() if llm.supports_tools(model) else None''',
         '''    msgs = build_messages(user_text, drop_id)
    # 这一轮带了图吗？带了就看「看图」那家配没配 —— 配了就换它来看
    has_img = any(isinstance(m.get("content"), list) for m in msgs)
    base, api_key, model = llm_conf(has_img)

    if not api_key:
        return {"ok": True, "need_key": True, "reply": "",
                "error": "还没有填 API key——去「钥匙」那页填一下"}

    tools = all_tools() if llm.supports_tools(model) else None'''),
        # 名单接口
        ('            if p == "/api/providers":\n'
         '                return self.send_json({"ok": True, "providers": llm.PROVIDERS})',
         '            if p == "/api/providers":\n'
         '                return self.send_json({"ok": True, "providers": llm.PROVIDERS})\n'
         '            if p == "/api/presets":\n'
         '                return self.send_json({"ok": True, "presets": llm.PRESETS})'),
        # 拉模型名单
        ('            if p == "/api/search/probe":\n'
         '                return self.send_json(api_search_probe(body))',
         '            if p == "/api/search/probe":\n'
         '                return self.send_json(api_search_probe(body))\n'
         '            if p == "/api/models":\n'
         '                return self.send_json(llm.models((body.get("base") or "").strip(),\n'
         '                                                (body.get("key") or "").strip()))'),
    ],
    "index.html": [
        # 新页面的样式
        ('  /* 日记 */\n  .ditem{', KEYS_CSS + '  /* 日记 */\n  .ditem{'),
        # 钥匙那页
        ("  <nav class=\"tabs\" id=\"tabs\">", KEYS_PAGE + "  <nav class=\"tabs\" id=\"tabs\">"),
        # 系统房间有真去处了
        ("          <button class=\"item\" onclick=\"toast('还没做')\"><span class=\"dot\"></span>MCP<span class=\"arw\">›</span></button>",
         "          <button class=\"item\" onclick=\"go('mcp')\"><span class=\"dot\"></span>MCP<span class=\"arw\">›</span></button>"),
        ("          <button class=\"item\" onclick=\"toast('还没做')\"><span class=\"dot\"></span>Settings<span class=\"arw\">›</span></button>",
         "          <button class=\"item\" onclick=\"go('keys')\"><span class=\"dot\"></span>Settings<span class=\"arw\">›</span></button>"),
        # 页面清单
        ('  ["home","feed","edit","day","chat","room","tools","memory","diary"].forEach(function(x){',
         '  ["home","feed","edit","day","chat","room","tools","memory","diary","keys","mcp"].forEach(function(x){'),
        ('  if (p === "diary") goDiary();',
         '  if (p === "diary") goDiary();\n  if (p === "keys") loadKeys();'),
        # 老抽屉整块删掉：两套设置一定会打架
        ('''  <div class="mask" id="modelMask" onclick="if(event.target===this)closeModel()">
    <div class="sheet">
      <h4>模型</h4>
      <div class="frow">
        <label>接口地址</label>
        <input id="mBase" placeholder="https://api.deepseek.com" autocapitalize="off" autocorrect="off">
      </div>
      <div class="frow">
        <label>模型</label>
        <select id="mModelSel" onchange="modelPicked()">
          <option value="deepseek-flash">deepseek-flash · V4.1 Flash，自带视觉、能思考</option>
          <option value="deepseek-v4-pro">deepseek-v4-pro · 在下线，会路由到 Flash</option>
          <option value="__custom">其他（自己填）</option>
        </select>
        <input id="mModel" placeholder="模型名" style="margin-top:8px;display:none"
               autocapitalize="off" autocorrect="off">
      </div>
      <div class="frow">
        <label>API Key（只存在你手机上）</label>
        <input id="mKey" type="password" placeholder="sk-…" autocapitalize="off" autocorrect="off">
      </div>
      <div class="bal" id="balLine">余额：—</div>
      <button class="bigbtn" onclick="saveModel()">保存</button>
      <button class="bigbtn" onclick="refreshBalance()">查一下余额</button>

      <h4 id="searchBlock" style="margin:24px 0 14px">搜索</h4>
      <div class="frow">
        <label>哪一家</label>
        <select id="sProv" onchange="paintSearchHint()"></select>
      </div>
      <div class="frow">
        <label>Key（也只存在你手机上）</label>
        <input id="sKey" type="password" placeholder="tvly-…" autocapitalize="off" autocorrect="off">
      </div>
      <div class="frow">
        <label>接口地址（留空就用官方的）</label>
        <input id="sBase" placeholder="https://api.tavily.com" autocapitalize="off" autocorrect="off">
      </div>
      <div class="bal" id="sLine">搜索：还没试过</div>
      <button class="bigbtn" onclick="saveSearch()">保存搜索</button>
      <button class="bigbtn" onclick="probeSearch()">试一下</button>
      <div class="bal" id="verLine">小屋 —</div>
    </div>
  </div>

''', ''),
        # 旧的 openModel / openSearch 换成「钥匙」那一套
        ('''/* ── 聊天页那个 🔍：拉到抽屉里搜索那一段 ── */
function openSearch(){
  openModel();
  setTimeout(function(){
    var s = document.getElementById("searchBlock");
    if (s && s.scrollIntoView) s.scrollIntoView({block: "start"});
  }, 160);
}

function openModel(){
  $("mBase").value = S.api_base || "https://api.deepseek.com";
  var m = S.model || "deepseek-flash";
  if (["deepseek-flash", "deepseek-v4-pro"].indexOf(m) >= 0){
    $("mModelSel").value = m;
    $("mModel").style.display = "none";
  } else {
    $("mModelSel").value = "__custom";
    $("mModel").value = m;
    $("mModel").style.display = "block";
  }
  $("mKey").value = S.api_key || "";
  $("sKey").value = S.search_key || "";
  $("sBase").value = S.search_base || "";
  loadSearchProviders().then(function(){
    $("sProv").value = S.search_provider || "tavily";
    paintSearchHint();
  });
  $("modelMask").classList.add("on");
  refreshBalance();
}''', KEYS_JS.rstrip("\n")),
        # 余额那行搬到钥匙页
        ('function refreshBalance(){\n  var el = $("balLine");\n  if (!el) return;',
         'function refreshBalance(){\n  var el = $("kBalLine") || $("balLine");\n  if (!el) return;'),
        # 版本号两处都填
        ('''function paintModelChip(){
  $("modelChip").textContent = (S.model || "deepseek-flash") + " ▾";
  var v = $("verLine");
  if (v) v.textContent = "小屋 " + (S.version || "—");
}''',
         '''function paintModelChip(){
  $("modelChip").textContent = (S.model || "deepseek-flash") + " ▾";
  var v = $("verLine");
  if (v) v.textContent = "小屋 " + (S.version || "—");
  var v2 = $("verLine2");
  if (v2) v2.textContent = S.version || "—";
}'''),
    ],
    "test_cove.py": [
        ('chk("默认模型不是废名字", _llm.DEFAULT_MODEL not in _llm.DEAD_NAMES, _llm.DEFAULT_MODEL)',
         'chk("默认模型不是废名字", _llm.DEFAULT_MODEL not in _llm.DEAD_NAMES, _llm.DEFAULT_MODEL)\n'
         'chk("供应商名单里有 deepseek / 硅基流动 / tavily",\n'
         '    {"deepseek", "siliconflow", "tavily"} <= {p["id"] for p in _llm.PRESETS},\n'
         '    [p["id"] for p in _llm.PRESETS])\n'
         'chk("名单里每一家都有地址或说明",\n'
         '    all(p.get("base") or p.get("hint") for p in _llm.PRESETS), _llm.PRESETS)'),
        ('c, d = req(base, "/api/memories?day=2026-10-02")',
         'c, d = req(base, "/api/presets")\n'
         'chk("GET /api/presets 拿得到名单", c == 200 and len(d.get("presets") or []) >= 4, str(d)[:120])\n'
         'c, d = req(base, "/api/models", {"base": "", "key": ""})\n'
         'chk("没填地址时不瞎连，好好报错", c == 200 and not d.get("ok") and d.get("error"), d)\n'
         'c, d = req(base, "/api/settings", {"vision_key": "t", "vision_model": "m",\n'
         '                                   "vision_base": "https://x.invalid"})\n'
         'chk("看图的钥匙存得进去", d.get("ok"), d)\n'
         'c, d = req(base, "/api/today")\n'
         'chk("today 里有 vision_key", "vision_key" in d, sorted(d.keys())[:8])\n'
         'c, d = req(base, "/api/memories?day=2026-10-02")'),
    ],
}

VER_FILES = {"VERSION": "2026-10-03d\n"}


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
    for name in ("hub.py", "llm.py", "rooms.py", "websearch.py", "test_cove.py"):
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
