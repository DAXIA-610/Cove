#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cove 补丁 · 2026-10-02 · 第三发
================================
1. 模型名改对：deepseek-flash（V4.1 Flash，自带视觉）+ deepseek-v4-pro
2. 视觉：图片按 image_url 真的进上下文（只带最近一张）
3. 文件：图片存 pics/，文本存 files/，文本内容会拼进上下文
4. 搜索：新开 websearch.py，Tavily / Brave / 博查 三家任选
5. 工具改成能外挂：以后往 websearch.py / rooms.py 加东西，hub 不用再动

跑：
    python3 patch_20261002d.py

规矩照旧：任何一处对不上，就整体不动，一个字都不写。
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NL = chr(10)


def swap_between(text, start, end, new):
    i = text.find(start)
    if i < 0:
        return None, "找不到开头：" + start[:50].replace(NL, " ")
    j = text.find(end, i + len(start))
    if j < 0:
        return None, "找不到结尾：" + end[:50].replace(NL, " ")
    return text[:i] + new + NL * 3 + text[j:], "ok"


def swap_once(text, old, new):
    n = text.count(old)
    if n == 0:
        if new.strip() and new in text:
            return text, "skip"
        return None, "找不到：" + old[:70].replace(NL, " ")
    if n > 1:
        return None, "出现了 %d 次，不敢动：%s" % (n, old[:70].replace(NL, " "))
    return text.replace(old, new), "ok"


# ======================================================================
BLOCK_WEBSEARCH = r'''#!/usr/bin/env python3
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
'''


# ======================================================================
BLOCK_JS = r'''/* ── 私语 ── */
var chatMsgs = [];
var curMsg = null;
var holdTimer = null, holdMoved = false, holdOpen = false, lastHold = 0;

function loadChat(){
  return get("/api/chat?limit=200").then(function(d){
    if (!d.ok) return;
    var box = $("msgs");
    if (!d.chat || !d.chat.length){
      box.innerHTML = '<div class="empty">还没说过话。</div>';
      return;
    }
    chatMsgs = d.chat;
    box.innerHTML = d.chat.map(function(m){
      if (m.revoked){
        return '<div class="bub gone">' + (m.who === "yume" ? "你" : "我") +
               '撤回了一条消息</div>';
      }
      var inner = "";
      if (m.file) inner += '<div class="bfile">📄 附件</div>';
      if (m.image) inner += '<img class="bimg" src="' + esc(m.image) + '">';
      inner += esc(m.text);
      return '<div class="bub' + (m.who === "yume" ? " me" : "") +
             '" data-id="' + m.id + '" data-who="' + m.who + '">' + inner + '</div>';
    }).join("");
    holdBind(box);
    if (!holdOpen) box.scrollTop = box.scrollHeight;
  });
}

/* 长按一条消息 —— 微信那样；短按我说的 —— 拉开那条的账 */
function holdBind(box){
  var list = box.querySelectorAll(".bub[data-id]");
  for (var i = 0; i < list.length; i++) holdOne(list[i]);
}
function holdOne(el){
  var sx = 0, sy = 0;
  function start(ev){
    var p = ev.touches ? ev.touches[0] : ev;
    sx = p.clientX; sy = p.clientY;
    holdMoved = false;
    clearTimeout(holdTimer);
    el.classList.add("hold");
    holdTimer = setTimeout(function(){
      if (holdMoved) return;
      el.classList.remove("hold");
      holdOpen = true;
      lastHold = Date.now();
      openMsgMenu(el.getAttribute("data-id"), sx, sy);
    }, 420);
  }
  function move(ev){
    var p = ev.touches ? ev.touches[0] : ev;
    if (Math.abs(p.clientX - sx) > 10 || Math.abs(p.clientY - sy) > 10){
      holdMoved = true;
      clearTimeout(holdTimer);
      el.classList.remove("hold");
    }
  }
  function end(){ clearTimeout(holdTimer); el.classList.remove("hold"); }
  el.addEventListener("touchstart", start, {passive:true});
  el.addEventListener("touchmove", move, {passive:true});
  el.addEventListener("touchend", end);
  el.addEventListener("touchcancel", end);
  el.addEventListener("mousedown", start);
  el.addEventListener("mousemove", move);
  el.addEventListener("mouseup", end);
  el.addEventListener("mouseleave", end);
  el.addEventListener("contextmenu", function(e){ e.preventDefault(); });
  el.addEventListener("click", function(){
    if (Date.now() - lastHold < 700) return;
    if (el.getAttribute("data-who") !== "yoru") return;
    openMeta(el.getAttribute("data-id"));
  });
}

function openMsgMenu(id, x, y){
  id = parseInt(id, 10);
  curMsg = null;
  for (var i = 0; i < chatMsgs.length; i++) if (chatMsgs[i].id === id) curMsg = chatMsgs[i];
  if (!curMsg) return;
  try { if (navigator.vibrate) navigator.vibrate(12); } catch(e){}

  var isLast = (chatMsgs.length && chatMsgs[chatMsgs.length - 1].id === curMsg.id);
  var items = [];
  items.push({t:"复制", f:function(){ var m = curMsg; closePop(); copyMsg(m.text); }});
  if (curMsg.who === "yume"){
    items.push({t:"编辑", f:function(){ var m = curMsg; closePop(); openMsgEdit(m); }});
  }
  if (curMsg.who === "yoru" && isLast){
    items.push({t:"重新生成", f:function(){ var m = curMsg; closePop(); regenMsg(m.id); }});
  }
  items.push({t:"撤回", cls:"warn", f:function(){ var m = curMsg; closePop(); askRevoke(m.id); }});
  showPop(items, {clientX:x, clientY:y});
}

function askRevoke(id){
  showPop([
    {t:"撤回这一条？", cls:"hd"},
    {t:"算了", f:closePop},
    {t:"撤回", cls:"warn", f:function(){
      closePop();
      post("/api/chat/revoke", {id:id}).then(function(r){
        if (!r.ok){ toast(r.error || "撤不了"); return; }
        toast(r.also ? "撤了，我那条回复也一起撤了" : "撤了");
        loadChat();
      });
    }}
  ], null, true);
}

function openMsgEdit(m){
  curMsg = m;
  $("msgEditText").value = m.text;
  $("msgEditMask").classList.add("on");
  setTimeout(function(){ try { $("msgEditText").focus(); } catch(e){} }, 80);
}
function closeMsgEdit(){ $("msgEditMask").classList.remove("on"); }
function saveMsgEdit(){
  if (!curMsg) return;
  var t = $("msgEditText").value.trim();
  if (!t){ toast("空的"); return; }
  post("/api/chat/edit", {id:curMsg.id, text:t}).then(function(r){
    if (!r.ok){ toast(r.error || "改不了"); return; }
    closeMsgEdit();
    loadChat();
  });
}

function regenMsg(id){
  var box = $("msgs");
  box.insertAdjacentHTML("beforeend", '<div class="bub thinking" id="thinking">……</div>');
  box.scrollTop = box.scrollHeight;
  post("/api/chat/regen", {id:id}).then(function(r){
    var th = $("thinking"); if (th) th.remove();
    if (!r.ok){ toast(r.error || "重来不了"); loadChat(); return; }
    loadChat();
  }).catch(function(){
    var th = $("thinking"); if (th) th.remove();
    toast("没回上来"); loadChat();
  });
}

function copyMsg(t){
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(t).then(function(){ toast("抄下来了"); },
                                          function(){ fallbackCopy(t); });
  } else fallbackCopy(t);
}
function fallbackCopy(t){
  var ta = document.createElement("textarea");
  ta.value = t;
  ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); toast("抄下来了"); } catch(e){ toast("抄不动"); }
  document.body.removeChild(ta);
}

function doCompress(){
  $("plusPanel").classList.remove("on");
  toast("正在压…");
  post("/api/chat/compress", {}).then(function(r){
    if (!r.ok){ toast(r.error || "没压成"); return; }
    if (r.skipped){ toast(r.note || "还不够压，攒着吧"); return; }
    toast("压好了，收进去 " + (r.covered || 0) + " 条");
    loadChat();
  }).catch(function(){ toast("没压成"); });
}

function sendChat(){
  var el = $("chatInput");
  var t = el.value.trim();
  if (!t && !pendingImg){ toast("空的"); return; }
  if (!S.api_key){ openModel(); toast("先填一下 API key"); return; }
  el.value = "";
  $("plusPanel").classList.remove("on");
  var box = $("msgs");
  var old = box.querySelector(".empty");
  if (old) old.remove();
  var mine = "";
  if (pendingFileUrl) mine += '<div class="bfile">📄 附件</div>';
  if (pendingImg) mine += '<img class="bimg" src="' + esc(pendingImg) + '">';
  mine += esc(t);
  box.insertAdjacentHTML("beforeend",
    '<div class="bub me">' + mine + '</div>' +
    '<div class="bub thinking" id="thinking">……</div>');
  box.scrollTop = box.scrollHeight;
  var body = {text: t};
  if (pendingImg) body.image = pendingImg;
  if (pendingFileUrl) body.file = pendingFileUrl;
  clearPending();
  post("/api/chat/send", body).then(function(r){
    var th = $("thinking");
    if (th) th.remove();
    if (r.need_key){ toast(r.error || "还没填 key"); loadChat(); return; }
    if (!r.ok){ toast(r.error || "没回上来"); loadChat(); return; }
    loadChat();
  }).catch(function(){
    var th = $("thinking");
    if (th) th.remove();
    toast("没回上来");
  });
}

'''

BLOCK_ADD = r'''/* ── 加号面板 / 模型 ── */
function togglePlus(){ $("plusPanel").classList.toggle("on"); }

function pickAttach(kind){
  var el = $("chatFile");
  el.value = "";
  el.accept = (kind === "file") ? "*/*" : "image/*";
  if (kind === "camera") el.setAttribute("capture", "environment");
  else el.removeAttribute("capture");
  el.dataset.kind = kind;
  $("plusPanel").classList.remove("on");
  el.click();
}

var pendingImg = "", pendingFileUrl = "", pendingFileName = "";

function shrinkImage(file, cb){
  var img = new Image();
  var url = URL.createObjectURL(file);
  img.onload = function(){
    var max = 1024;
    var w = img.width, h = img.height;
    if (w > max || h > max){
      var k = Math.min(max / w, max / h);
      w = Math.round(w * k); h = Math.round(h * k);
    }
    var cv = document.createElement("canvas");
    cv.width = w; cv.height = h;
    cv.getContext("2d").drawImage(img, 0, 0, w, h);
    URL.revokeObjectURL(url);
    cb(cv.toDataURL("image/jpeg", 0.82));
  };
  img.onerror = function(){ URL.revokeObjectURL(url); toast("这张图读不出来"); };
  img.src = url;
}

function onChatFile(ev){
  var f = ev.target.files && ev.target.files[0];
  if (!f) return;
  var kind = ev.target.dataset.kind || "photo";
  if (kind === "file" && f.type.indexOf("image/") !== 0){
    var fr = new FileReader();
    fr.onload = function(){
      post("/api/upload", {name: f.name, text: String(fr.result)}).then(function(r){
        if (!r.ok){ toast(r.error || "传不上去"); return; }
        pendingFileUrl = r.url;
        pendingFileName = r.name || f.name;
        paintPending();
        toast("附上了 " + pendingFileName);
      });
    };
    fr.readAsText(f);
    return;
  }
  shrinkImage(f, function(dataUrl){
    post("/api/upload", {data: dataUrl}).then(function(r){
      if (!r.ok){ toast(r.error || "传不上去"); return; }
      pendingImg = r.url;
      paintPending();
      toast("图准备好了，说一句再发");
    });
  });
}

function paintPending(){
  var el = $("pendingBar");
  if (!pendingImg && !pendingFileUrl){ el.classList.remove("on"); el.innerHTML = ""; return; }
  el.classList.add("on");
  var h = "";
  if (pendingImg) h += '<span class="pchip"><img src="' + esc(pendingImg) + '">图</span>';
  if (pendingFileUrl) h += '<span class="pchip">📄 ' + esc(pendingFileName) + '</span>';
  h += '<button onclick="clearPending()">×</button>';
  el.innerHTML = h;
}
function clearPending(){
  pendingImg = ""; pendingFileUrl = ""; pendingFileName = "";
  paintPending();
}

'''

BLOCK_MODEL = r'''function openModel(){
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
}
function modelPicked(){
  $("mModel").style.display = ($("mModelSel").value === "__custom") ? "block" : "none";
}
function currentModel(){
  var v = $("mModelSel").value;
  return (v === "__custom") ? ($("mModel").value.trim() || "deepseek-flash") : v;
}
function closeModel(){ $("modelMask").classList.remove("on"); }
function saveModel(){
  var b = $("mBase").value.trim() || "https://api.deepseek.com";
  var m = currentModel();
  var k = $("mKey").value.trim();
  S.api_base = b; S.model = m; S.api_key = k;
  post("/api/settings", {api_base:b, model:m, api_key:k}).then(function(){
    paintModelChip(); closeModel(); toast("存好了");
  });
}

/* ── 搜索 ── */
var searchProviders = [];
function loadSearchProviders(){
  return get("/api/search/providers").then(function(d){
    if (!d.ok) return;
    searchProviders = d.providers || [];
    $("sProv").innerHTML = searchProviders.map(function(p){
      return '<option value="' + esc(p.id) + '">' + esc(p.name) + '</option>';
    }).join("");
  });
}
function paintSearchHint(){
  var id = $("sProv").value;
  for (var i = 0; i < searchProviders.length; i++){
    if (searchProviders[i].id === id){
      $("sKey").placeholder = searchProviders[i].hint || "key";
      $("sBase").placeholder = searchProviders[i].base || "";
      return;
    }
  }
}
function saveSearch(){
  var b = {
    search_provider: $("sProv").value,
    search_key: $("sKey").value.trim(),
    search_base: $("sBase").value.trim()
  };
  post("/api/settings", b).then(function(r){
    if (!r.ok){ toast("存不上"); return; }
    S.search_provider = b.search_provider;
    S.search_key = b.search_key;
    S.search_base = b.search_base;
    toast("搜索存好了");
  });
}
function probeSearch(){
  $("sLine").textContent = "搜索：正在试…";
  post("/api/search/probe", {
    key: $("sKey").value.trim(),
    provider: $("sProv").value,
    base: $("sBase").value.trim()
  }).then(function(r){
    if (!r.ok){ $("sLine").textContent = "搜索：" + (r.error || "没成"); return; }
    var t = (r.sample && r.sample[0] && r.sample[0].title) || "";
    $("sLine").textContent = "搜索：通了，回来 " + r.n + " 条" + (t ? "｜" + t.slice(0, 30) : "");
  }).catch(function(){ $("sLine").textContent = "搜索：没连上"; });
}
'''


# ======================================================================
def patch_llm(text):
    old = ('    {"id": "deepseek", "name": "深度求索 DeepSeek",' + NL +
           '     "base": "https://api.deepseek.com",' + NL +
           '     "models": ["deepseek-chat", "deepseek-reasoner"]},')
    new = ('    # 注意：deepseek-chat / deepseek-reasoner 这两个老名字 2026-07-24 就废了。' + NL +
           '    # 现在是 deepseek-flash（= V4.1-Flash，自带视觉、1M 上下文、能思考）' + NL +
           '    # 和 deepseek-v4-pro（在往下线，请求会路由到 Flash）。写死的旧名字要改。' + NL +
           '    {"id": "deepseek", "name": "深度求索 DeepSeek",' + NL +
           '     "base": "https://api.deepseek.com",' + NL +
           '     "models": ["deepseek-flash", "deepseek-v4-pro"]},')
    return swap_once(text, old, new)


def patch_hub(text):
    log = []
    steps = [
        ("把 websearch 挂上", "once",
         ("try:" + NL + "    import rooms" + NL + "except Exception:" + NL + "    rooms = None",
          "try:" + NL + "    import rooms" + NL + "except Exception:" + NL + "    rooms = None" + NL + NL +
          "# 对互联网的那口子：搜索。以后加读网页之类也只写它" + NL +
          "try:" + NL + "    import websearch" + NL + "except Exception:" + NL + "    websearch = None")),

        ("files 目录", "once",
         ('PICS = os.path.join(BASE, "pics")',
          'PICS = os.path.join(BASE, "pics")' + NL +
          'FILES = os.path.join(BASE, "files")     # 她发上来的文本文件存这儿')),

        ("设置项加搜索", "once",
         ('    "api_key", "api_base", "model", "tools",' + NL + ')',
          '    "api_key", "api_base", "model", "tools",' + NL +
          '    # 搜索那口子' + NL +
          '    "search_provider", "search_key", "search_base",' + NL + ')')),

        ("chat 表加 image / file", "once",
         ('                created TEXT NOT NULL,' + NL +
          '                revoked INTEGER NOT NULL DEFAULT 0' + NL +
          '            );',
          '                created TEXT NOT NULL,' + NL +
          '                revoked INTEGER NOT NULL DEFAULT 0,   -- 撤回了就不进上下文，但留着不删' + NL +
          '                image   TEXT NOT NULL DEFAULT \'\',     -- pics/xxx.jpg' + NL +
          '                file    TEXT NOT NULL DEFAULT \'\'      -- files/xxx.txt' + NL +
          '            );')),

        ("老库补 image / file", "once",
         ('        if not has_col(c, "chat", "revoked"):' + NL +
          '            c.execute("ALTER TABLE chat ADD COLUMN revoked INTEGER NOT NULL DEFAULT 0")',
          '        if not has_col(c, "chat", "revoked"):' + NL +
          '            c.execute("ALTER TABLE chat ADD COLUMN revoked INTEGER NOT NULL DEFAULT 0")' + NL +
          '        if not has_col(c, "chat", "image"):' + NL +
          '            c.execute("ALTER TABLE chat ADD COLUMN image TEXT NOT NULL DEFAULT \'\'")' + NL +
          '        if not has_col(c, "chat", "file"):' + NL +
          '            c.execute("ALTER TABLE chat ADD COLUMN file TEXT NOT NULL DEFAULT \'\'")')),

        ("上传支持文本文件", "once",
         ('def api_upload(body):' + NL +
          '    """把前端传来的 dataURL 存成文件，返回路径"""' + NL +
          '    data = body.get("data") or ""',
          'def api_upload(body):' + NL +
          '    """两种东西都往这儿送：' + NL + NL +
          '    图片 —— body 里是 {data: "data:image/jpeg;base64,..."}，存进 pics/' + NL +
          '    文本 —— body 里是 {name: "笔记.md", text: "..."}，存进 files/' + NL +
          '    """' + NL +
          '    # ---- 文本文件 ----' + NL +
          '    if body.get("text") is not None:' + NL +
          '        name = (body.get("name") or "note.txt").strip()[:80]' + NL +
          '        text = str(body.get("text"))[:400000]' + NL +
          '        if not text.strip():' + NL +
          '            return {"ok": False, "error": "空的"}' + NL +
          '        os.makedirs(FILES, exist_ok=True)' + NL +
          '        safe = "".join(ch for ch in name if ch.isalnum() or ch in "._-") or "note.txt"' + NL +
          '        out = datetime.now().strftime("%Y%m%d-%H%M%S-") + os.urandom(3).hex() + "-" + safe' + NL +
          '        with open(os.path.join(FILES, out), "w", encoding="utf-8") as f:' + NL +
          '            f.write(text)' + NL +
          '        return {"ok": True, "url": "/files/" + out, "name": name}' + NL + NL +
          '    # ---- 图片 ----' + NL +
          '    data = body.get("data") or ""')),

        ("聊天读写带上图/附件", "once",
         ('            "SELECT id, who, text, created, revoked FROM chat ORDER BY id DESC LIMIT ?",',
          '            "SELECT id, who, text, created, revoked, image, file "' + NL +
          '            "FROM chat ORDER BY id DESC LIMIT ?",')),

        ("add 也支持带图", "once",
         ('        cur = c.execute(' + NL +
          '            "INSERT INTO chat(who, text, created) VALUES(?,?,?)",' + NL +
          '            (who, text[:2000], now_str()),' + NL +
          '        )',
          '        cur = c.execute(' + NL +
          '            "INSERT INTO chat(who, text, created, image, file) VALUES(?,?,?,?,?)",' + NL +
          '            (who, text[:2000], now_str(),' + NL +
          '             (body.get("image") or "")[:300], (body.get("file") or "")[:300]),' + NL +
          '        )')),

        ("读图 / 读附件的两个小函数", "once",
         ('def build_messages(user_text="", drop_id=0):',
          'CTX_IMG_KEEP = 1        # 上下文里最多带几张真的图片（老图又贵又没用）' + NL + NL + NL +
          'def _img_data_url(rel):' + NL +
          '    """把 pics/xxx.jpg 读成 dataURL。读不出来就返回空串。"""' + NL +
          '    name = os.path.basename(rel or "")' + NL +
          '    if not name:' + NL +
          '        return ""' + NL +
          '    path = os.path.join(PICS, name)' + NL +
          '    if not os.path.exists(path) or os.path.getsize(path) > 6 * 1024 * 1024:' + NL +
          '        return ""' + NL +
          '    try:' + NL +
          '        with open(path, "rb") as f:' + NL +
          '            raw = f.read()' + NL +
          '    except OSError:' + NL +
          '        return ""' + NL +
          '    ext = name.rsplit(".", 1)[-1].lower()' + NL +
          '    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",' + NL +
          '            "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/jpeg")' + NL +
          '    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode())' + NL + NL + NL +
          'def _read_attach(rel):' + NL +
          '    """把 files/xxx.txt 读成文字，裁到塞得进上下文的长度。"""' + NL +
          '    name = os.path.basename(rel or "")' + NL +
          '    if not name:' + NL +
          '        return ""' + NL +
          '    path = os.path.join(FILES, name)' + NL +
          '    if not os.path.exists(path) or os.path.getsize(path) > 400000:' + NL +
          '        return ""' + NL +
          '    try:' + NL +
          '        with open(path, "r", encoding="utf-8", errors="replace") as f:' + NL +
          '            return f.read()[:20000]' + NL +
          '    except OSError:' + NL +
          '        return ""' + NL + NL + NL +
          'def build_messages(user_text="", drop_id=0):')),

        ("build_messages 查图/附件", "once",
         ('            "SELECT id, who, text FROM chat WHERE revoked=0 ORDER BY id DESC LIMIT ?",' + NL +
          '            (CTX_KEEP_RECENT,)).fetchall())',
          '            "SELECT id, who, text, image, file FROM chat WHERE revoked=0 "' + NL +
          '            "ORDER BY id DESC LIMIT ?",' + NL +
          '            (CTX_KEEP_RECENT,)).fetchall())')),

        ("build_messages 把图真的塞进去", "once",
         ('    msgs = [{"role": "system", "content": sys_text}]' + NL +
          '    for r in rows:' + NL +
          '        msgs.append({' + NL +
          '            "role": "user" if r["who"] == "yume" else "assistant",' + NL +
          '            "content": r["text"],' + NL +
          '        })',
          '    msgs = [{"role": "system", "content": sys_text}]' + NL + NL +
          '    # 图：只把最近 CTX_IMG_KEEP 张真的塞进去。老图拿文字占个位就够，又贵又没用。' + NL +
          '    img_ids = []' + NL +
          '    for r in reversed(rows):' + NL +
          '        if r.get("image") and r["who"] == "yume" and len(img_ids) < CTX_IMG_KEEP:' + NL +
          '            img_ids.append(r["id"])' + NL + NL +
          '    for r in rows:' + NL +
          '        text = r["text"] or ""' + NL +
          '        role = "user" if r["who"] == "yume" else "assistant"' + NL + NL +
          '        if r.get("image") and r["id"] in img_ids:' + NL +
          '            data = _img_data_url(r["image"])' + NL +
          '            if data:' + NL +
          '                msgs.append({' + NL +
          '                    "role": role,' + NL +
          '                    "content": [' + NL +
          '                        {"type": "text", "text": text or "（看这张）"},' + NL +
          '                        {"type": "image_url", "image_url": {"url": data}},' + NL +
          '                    ],' + NL +
          '                })' + NL +
          '                continue' + NL +
          '        if r.get("image"):' + NL +
          '            text = (text + "　").strip() + "[图]"' + NL +
          '        if r.get("file"):' + NL +
          '            body_txt = _read_attach(r["file"])' + NL +
          '            if body_txt:' + NL +
          '                text = "【附件】" + NL + body_txt + NL + "【附件完】" + NL + text' + NL +
          '        msgs.append({"role": role, "content": text})')),

        ("算账时给图留位", "once",
         ('    total = est_tokens(sys_text) + sum(est_tokens(r["text"]) for r in rows)',
          '    total = est_tokens(sys_text) + sum(est_tokens(r["text"] or "") for r in rows)' + NL +
          '    total += 1200 * len(img_ids)      # 一张图粗估一千多 token，够用来算账了')),

        ("工具能外挂", "once",
         ('MAX_TOOL_ROUNDS = 4' + NL + NL + NL +
          'def run_tool(name, a):' + NL +
          '    """模型说要用哪只手，我们就替它动一下。返回一段给它看的话。"""' + NL +
          '    a = a or {}' + NL + NL +
          '    if name == "remember":',
          'MAX_TOOL_ROUNDS = 4' + NL + NL + NL +
          'def all_tools():' + NL +
          '    """家里的手 + 外挂的手，一起端给模型看。' + NL + NL +
          '    以后往 websearch.py / rooms.py 里加工具，这里自动跟上，hub 不用改。' + NL +
          '    """' + NL +
          '    out = list(IN_HOUSE_TOOLS)' + NL +
          '    for mod in (rooms, websearch):' + NL +
          '        if mod is None:' + NL +
          '            continue' + NL +
          '        try:' + NL +
          '            out.extend(getattr(mod, "TOOLS", []) or [])' + NL +
          '        except Exception:' + NL +
          '            pass' + NL +
          '    return out' + NL + NL + NL +
          'def run_tool(name, a):' + NL +
          '    """模型说要用哪只手，我们就替它动一下。返回一段给它看的话。"""' + NL +
          '    a = a or {}' + NL + NL +
          '    # 先问外挂的手（搜索之类）—— 它们认领了就直接回' + NL +
          '    for mod in (websearch, rooms):' + NL +
          '        if mod is None or not hasattr(mod, "run"):' + NL +
          '            continue' + NL +
          '        try:' + NL +
          '            out = mod.run(name, a)' + NL +
          '        except Exception as e:' + NL +
          '            out = "这只手动的时候出错了：" + repr(e)' + NL +
          '        if out is not None:' + NL +
          '            return out' + NL + NL +
          '    if name == "remember":')),

        ("说话时用全部的手", "once",
         ('    tools = IN_HOUSE_TOOLS if llm.supports_tools(model) else None',
          '    tools = all_tools() if llm.supports_tools(model) else None')),

        ("两句搜索的小接口", "once",
         ('def api_balance():' + NL + '    """看看模型账户里还剩多少钱。"""',
          'def api_search_providers():' + NL +
          '    if websearch is None:' + NL +
          '        return {"ok": False, "error": "websearch.py 不在"}' + NL +
          '    return {"ok": True, "providers": websearch.PROVIDERS}' + NL + NL + NL +
          'def api_search_probe(body):' + NL +
          '    """界面上那个「试一下」：拿刚填的 key 真搜一把，看看通不通。"""' + NL +
          '    if websearch is None:' + NL +
          '        return {"ok": False, "error": "websearch.py 不在"}' + NL +
          '    key = (body.get("key") or "").strip()' + NL +
          '    if not key:' + NL +
          '        return {"ok": False, "error": "先把 key 填上"}' + NL +
          '    return websearch.probe(key,' + NL +
          '                           (body.get("provider") or "tavily").strip(),' + NL +
          '                           (body.get("base") or "").strip())' + NL + NL + NL +
          'def api_balance():' + NL + '    """看看模型账户里还剩多少钱。"""')),

        ("她带图说话", "once",
         ('    text = (body.get("text") or "").strip()' + NL +
          '    if not text:' + NL +
          '        return {"ok": False, "error": "空的"}' + NL +
          '    if len(text) > 2000:' + NL +
          '        text = text[:2000]' + NL + NL +
          '    with db() as c:' + NL +
          '        c.execute("INSERT INTO chat(who, text, created) VALUES(?,?,?)",' + NL +
          '                  ("yume", text, now_str()))',
          '    text = (body.get("text") or "").strip()' + NL +
          '    image = (body.get("image") or "").strip()[:300]' + NL +
          '    attach = (body.get("file") or "").strip()[:300]' + NL +
          '    if not text and not image:' + NL +
          '        return {"ok": False, "error": "空的"}' + NL +
          '    if len(text) > 2000:' + NL +
          '        text = text[:2000]' + NL + NL +
          '    with db() as c:' + NL +
          '        c.execute("INSERT INTO chat(who, text, created, image, file) VALUES(?,?,?,?,?)",' + NL +
          '                  ("yume", text, now_str(), image, attach))')),

        ("GET 搜索供应商", "once",
         ('            if p == "/api/providers":' + NL +
          '                return self.send_json({"ok": True, "providers": llm.PROVIDERS})',
          '            if p == "/api/providers":' + NL +
          '                return self.send_json({"ok": True, "providers": llm.PROVIDERS})' + NL +
          '            if p == "/api/search/providers":' + NL +
          '                return self.send_json(api_search_providers())')),

        ("POST 试搜索", "once",
         ('            if p == "/api/settings":' + NL +
          '                return self.send_json(api_settings(body))',
          '            if p == "/api/settings":' + NL +
          '                return self.send_json(api_settings(body))' + NL +
          '            if p == "/api/search/probe":' + NL +
          '                return self.send_json(api_search_probe(body))')),
    ]

    for name, kind, args in steps:
        new_text, status = swap_once(text, args[0], args[1])
        if new_text is None:
            return None, [log, name + "  →  " + status]
        text = new_text
        log.append("  ok  " + name + ("（已经是新的了）" if status == "skip" else ""))
    return text, log


# ======================================================================
def patch_html(text):
    log = []

    once = [
        ("图/附件的样子",
         ('  .bub.gone{align-self:center;background:transparent;box-shadow:none;font-size:11.5px;' + NL +
          '            color:var(--soft);padding:3px 0;letter-spacing:.06em;}',
          '  .bub.gone{align-self:center;background:transparent;box-shadow:none;font-size:11.5px;' + NL +
          '            color:var(--soft);padding:3px 0;letter-spacing:.06em;}' + NL +
          '  .bub img.bimg{max-width:100%;border-radius:12px;display:block;margin-bottom:6px;}' + NL +
          '  .bub .bfile{font-size:11.5px;opacity:.85;margin-bottom:5px;}' + NL +
          '  .pending{display:none;gap:8px;align-items:center;padding:9px 16px 0;flex-wrap:wrap;}' + NL +
          '  .pending.on{display:flex;}' + NL +
          '  .pchip{font-size:11px;padding:5px 11px;border-radius:999px;background:var(--card2);' + NL +
          '         color:var(--ink);display:inline-flex;align-items:center;}' + NL +
          '  .pchip img{width:18px;height:18px;border-radius:4px;margin-right:6px;object-fit:cover;}' + NL +
          '  .pending button{font-size:16px;color:var(--soft);padding:0 8px;}')),

        ("模型下拉改对",
         ('        <select id="mModelSel" onchange="modelPicked()">' + NL +
          '          <option value="deepseek-chat">deepseek-chat · 快、便宜</option>' + NL +
          '          <option value="deepseek-reasoner">deepseek-reasoner · 会想、慢、贵</option>' + NL +
          '          <option value="__custom">其他（自己填）</option>' + NL +
          '        </select>',
          '        <select id="mModelSel" onchange="modelPicked()">' + NL +
          '          <option value="deepseek-flash">deepseek-flash · V4.1 Flash，自带视觉、能思考</option>' + NL +
          '          <option value="deepseek-v4-pro">deepseek-v4-pro · 在下线，会路由到 Flash</option>' + NL +
          '          <option value="__custom">其他（自己填）</option>' + NL +
          '        </select>')),

        ("搜索那一段表单",
         ('      <button class="bigbtn" onclick="refreshBalance()">查一下余额</button>' + NL +
          '    </div>' + NL + '  </div>',
          '      <button class="bigbtn" onclick="refreshBalance()">查一下余额</button>' + NL + NL +
          '      <h4 style="margin:24px 0 14px">搜索</h4>' + NL +
          '      <div class="frow">' + NL +
          '        <label>哪一家</label>' + NL +
          '        <select id="sProv" onchange="paintSearchHint()"></select>' + NL +
          '      </div>' + NL +
          '      <div class="frow">' + NL +
          '        <label>Key（也只存在你手机上）</label>' + NL +
          '        <input id="sKey" type="password" placeholder="tvly-…" autocapitalize="off" autocorrect="off">' + NL +
          '      </div>' + NL +
          '      <div class="frow">' + NL +
          '        <label>接口地址（留空就用官方的）</label>' + NL +
          '        <input id="sBase" placeholder="https://api.tavily.com" autocapitalize="off" autocorrect="off">' + NL +
          '      </div>' + NL +
          '      <div class="bal" id="sLine">搜索：还没试过</div>' + NL +
          '      <button class="bigbtn" onclick="saveSearch()">保存搜索</button>' + NL +
          '      <button class="bigbtn" onclick="probeSearch()">试一下</button>' + NL +
          '    </div>' + NL + '  </div>')),

        ("待发附件那一条",
         ('    <div class="inputbar">',
          '    <div class="pending" id="pendingBar"></div>' + NL +
          '    <div class="inputbar">')),

        ("多一个选文件的口",
         ('  <input type="file" id="filePick" accept="image/*" hidden>',
          '  <input type="file" id="filePick" accept="image/*" hidden>' + NL +
          '  <input type="file" id="chatFile" hidden onchange="onChatFile(event)">')),

        ("底下的模型名",
         ('<button class="chip" id="modelChip" onclick="openModel()">deepseek-chat ▾</button>',
          '<button class="chip" id="modelChip" onclick="openModel()">deepseek-flash ▾</button>')),

        ("chip 上的默认名",
         ('  $("modelChip").textContent = (S.model || "deepseek-chat") + " ▾";',
          '  $("modelChip").textContent = (S.model || "deepseek-flash") + " ▾";')),
    ]

    for name, args in once:
        new_text, status = swap_once(text, args[0], args[1])
        if new_text is None:
            return None, [log, name + "  →  " + status]
        text = new_text
        log.append("  ok  " + name + ("（已经是新的了）" if status == "skip" else ""))

    between = [
        ("私语那一整段（多了：图能显示、能带附件发）",
         ('/* ── 私语 ── */', '/* ── 加号面板 / 模型 ── */', BLOCK_JS.rstrip())),
        ("加号面板到 openModel 之间（多了：真选文件、缩图、待发条）",
         ('/* ── 加号面板 / 模型 ── */', 'function openModel(){', BLOCK_ADD.rstrip())),
        ("openModel 那一整段（多了：搜索的设置）",
         ('function openModel(){', 'function paintModelChip(){', BLOCK_MODEL)),
    ]
    for name, args in between:
        new_text, status = swap_between(text, args[0], args[1], args[2])
        if new_text is None:
            return None, [log, name + "  →  " + status]
        text = new_text
        log.append("  ok  " + name)

    return text, log


# ======================================================================
def main():
    do_git = "--no-git" not in sys.argv
    hub = os.path.join(HERE, "hub.py")
    html = os.path.join(HERE, "index.html")
    llm = os.path.join(HERE, "llm.py")
    web = os.path.join(HERE, "websearch.py")

    for p in (hub, html, llm):
        if not os.path.exists(p):
            print("这儿不是 Cove 的目录 —— 少了个 %s" % os.path.basename(p))
            return 1

    out = {}
    for path, fn in ((hub, patch_hub), (llm, patch_llm), (html, patch_html)):
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        res = fn(src)
        if isinstance(res[1], list):
            new, log = res[0], res[1]
        else:
            new, log = res[0], [res[1]]
        print(os.path.basename(path))
        for line in log:
            print(line if str(line).startswith("  ") else "  " + str(line))
        if new is None:
            print(NL + "有一处对不上，一个字都没改。")
            return 1
        out[path] = (src, new)

    web_new = False
    if os.path.exists(web):
        with open(web, "r", encoding="utf-8") as f:
            old_web = f.read()
        if old_web.strip() != BLOCK_WEBSEARCH.strip():
            print(NL + "websearch.py 已经存在，而且跟我要写的不一样 —— 先不动它。")
            print("把它改个名告诉我，我再看看。")
            return 1
        print("websearch.py 已经有了，跳过。")
    else:
        web_new = True
        print("websearch.py 会新建。")

    changed = [p for p in out if out[p][0] != out[p][1]]
    if not changed and not web_new:
        print(NL + "已经是最新的，不用动。")
        return 0

    for p in changed:
        shutil.copy(p, p + ".bak")
        with open(p, "w", encoding="utf-8") as f:
            f.write(out[p][1])
    if web_new:
        with open(web, "w", encoding="utf-8") as f:
            f.write(BLOCK_WEBSEARCH)

    print(NL + "写好了。旧的那几份留着 .bak")

    r = subprocess.run([sys.executable, "-m", "py_compile",
                        "hub.py", "llm.py", "rooms.py", "websearch.py"],
                       cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        for p in changed:
            shutil.move(p + ".bak", p)
        if web_new:
            os.remove(web)
        print("语法没过，已经退回原来的样子：")
        print(r.stderr[-1500:])
        return 1
    print("语法过了。")

    if do_git and os.path.isdir(os.path.join(HERE, ".git")):
        try:
            subprocess.run(["git", "add", "."], cwd=HERE, check=True)
            subprocess.run(["git", "commit", "-m",
                            "模型名改对 + 视觉 + 上传 + 搜索 + 工具外挂"],
                           cwd=HERE, check=True)
            push = subprocess.run(["git", "push"], cwd=HERE, capture_output=True, text=True)
            if push.returncode == 0:
                print("也推上去了。")
            else:
                print("commit 好了，但 push 没成（不急，本地已经生效）：")
                print((push.stderr or "")[-500:])
        except Exception as e:
            print("git 那步没成，不影响本地：%r" % (e,))

    print(NL + "重启 hub 就是新的了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
