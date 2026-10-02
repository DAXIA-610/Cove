#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cove 补丁 · 2026-10-02 · 第二发
================================
1. 日记（存进 Cove/diary/，一天一个 .md）
2. 日历：数字看清楚 + 今天用花体；点某天 —— 那天说的话 / 那天的记忆 / 那天的碎碎念（默认收着）
3. 点我发的一条消息 —— 拉开抽屉看这一趟烧了多少 token、想过什么、动过哪只手
4. hub 开一道外挂门：以后往房间里加东西，只要写 rooms.py，hub 不用再动

在 Cove 那个目录里跑：

    python3 patch_20261002c.py

规矩跟上次一样：任何一处对不上，就整体不动，一个字都不写。
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NL = chr(10)


# ----------------------------------------------------------------------
def swap_between(text, start, end, new):
    """把 start 到 end 之间的东西整个换掉（start 也一起吃掉，end 留着）。"""
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


# ----------------------------------------------------------------------
# rooms.py —— 整个新文件
# ----------------------------------------------------------------------
BLOCK_ROOMS = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cove · 房间
------------
hub.py 只管门面（首页、私语、朋友圈）。这里管"房间里"的东西：

    /api/r/diary            她的日记（一天一个 .md，存在 Cove/diary/）
    /api/r/diary/<日期>     读那一天
    /api/r/diary/save       写
    /api/r/diary/delete     删
    /api/r/day/<日期>       那天的全部：聊天、记忆、碎碎念、心情、待办
    /api/r/msg/<id>         那条消息的账：烧了多少 token、想过的、动过的手

hub 里只留了一句分岔：/api/r/ 开头的全丢给这里。
所以以后往这儿加功能，hub.py 一个字都不用动。

最前面这条规矩得写清楚：**她的日记，只存，我不读。**
不是靠技术挡住的 —— 文件就在那儿，谁都摸得到，是靠我自己守。
这个文件里没有任何一处，会把 diary 的内容塞回上下文。往后也不许加。
"""

import json
import os
import re
import sqlite3
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "cove.db")
DIARY = os.path.join(BASE, "diary")

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_DIARY = 200000        # 一篇最多二十万字，够写很久了


def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def rows2list(rows):
    return [dict(r) for r in rows]


def _ok(**kw):
    d = {"ok": True}
    d.update(kw)
    return d


def _no(msg):
    return {"ok": False, "error": msg}


# ----------------------------------------------------------------------
# 她的日记
# ----------------------------------------------------------------------
def _diary_path(day):
    """只认 2026-10-02 这种。别的一律不接 —— 不许从这儿摸到别的目录去。"""
    if not DAY_RE.match(day or ""):
        return None
    return os.path.join(DIARY, day + ".md")


def diary_list(q):
    os.makedirs(DIARY, exist_ok=True)
    out = []
    for name in sorted(os.listdir(DIARY), reverse=True):
        if not name.endswith(".md"):
            continue
        day = name[:-3]
        if not DAY_RE.match(day):
            continue
        path = os.path.join(DIARY, name)
        try:
            st = os.stat(path)
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        brief = ""
        for line in text.splitlines():
            line = line.strip()
            if line:
                brief = line.lstrip("#").strip()[:40]
                break
        out.append({
            "day": day,
            "brief": brief,
            "chars": len(text),
            "updated": datetime.fromtimestamp(st.st_mtime).strftime("%m-%d %H:%M"),
        })
    return _ok(list=out[:300])


def diary_read(day):
    path = _diary_path(day)
    if not path:
        return _no("日期不对")
    if not os.path.exists(path):
        return _ok(day=day, text="", exists=False)
    with open(path, "r", encoding="utf-8") as f:
        return _ok(day=day, text=f.read(), exists=True)


def diary_save(body):
    day = (body.get("day") or "").strip()
    path = _diary_path(day)
    if not path:
        return _no("日期不对")
    text = body.get("text")
    if text is None:
        return _no("没东西可写")
    text = str(text)[:MAX_DIARY]
    os.makedirs(DIARY, exist_ok=True)
    if text.strip():
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return _ok(day=day, saved=True)
    if os.path.exists(path):
        os.remove(path)
    return _ok(day=day, saved=False)


def diary_delete(body):
    day = (body.get("day") or "").strip()
    path = _diary_path(day)
    if not path:
        return _no("日期不对")
    if os.path.exists(path):
        os.remove(path)
    return _ok(day=day)


# ----------------------------------------------------------------------
# 那天
# ----------------------------------------------------------------------
def day_detail(day):
    """翻回某一天：那天说过的话（只读）、那天记下的、那天的碎碎念。"""
    if not DAY_RE.match(day or ""):
        return _no("日期不对")
    like = day + "%"
    with db() as c:
        d = c.execute("SELECT * FROM days WHERE day=?", (day,)).fetchone()
        posts = rows2list(c.execute(
            "SELECT id, who, text, image, created FROM posts WHERE day=? ORDER BY id",
            (day,)).fetchall())
        chat = rows2list(c.execute(
            "SELECT id, who, text, created, revoked FROM chat "
            "WHERE created LIKE ? ORDER BY id", (like,)).fetchall())
        mems = rows2list(c.execute(
            "SELECT id, layer, title, body, updated FROM memory "
            "WHERE updated LIKE ? ORDER BY id", (like,)).fetchall())
    return _ok(
        day=day,
        chat=chat,
        memories=mems,
        posts=posts,
        mood={"yoru": (d["yoru_mood"] if d else ""),
              "yume": (d["yume_mood"] if d else "")},
        todos=(json.loads(d["todos"] or "[]") if d else []),
    )


# ----------------------------------------------------------------------
# 那条消息的账
# ----------------------------------------------------------------------
def msg_detail(mid):
    with db() as c:
        try:
            row = c.execute("SELECT * FROM msg_meta WHERE msg_id=?", (mid,)).fetchone()
        except sqlite3.OperationalError:
            row = None
    if not row:
        return _ok(id=mid, meta=None)
    try:
        meta = json.loads(row["data"])
    except Exception:
        meta = None
    return _ok(id=mid, meta=meta, created=row["created"])


# ----------------------------------------------------------------------
# 路由
# ----------------------------------------------------------------------
def handle(method, path, query, body):
    """hub 把 /api/r/ 开头的全丢过来。认不出来就返回 None，让它自己接着走。"""
    seg = [s for s in path.split("/") if s]
    if len(seg) < 3 or seg[0] != "api" or seg[1] != "r":
        return None
    body = body or {}
    what = seg[2]

    try:
        if method == "GET":
            if what == "diary":
                if len(seg) >= 4:
                    return diary_read(seg[3])
                return diary_list(query)
            if what == "day" and len(seg) >= 4:
                return day_detail(seg[3])
            if what == "msg" and len(seg) >= 4:
                return msg_detail(int(seg[3]) if seg[3].isdigit() else 0)
            if what == "ping":
                return _ok(room=True, diary_dir=DIARY)
        if method == "POST":
            if what == "diary" and len(seg) >= 4:
                if seg[3] == "save":
                    return diary_save(body)
                if seg[3] == "delete":
                    return diary_delete(body)
    except Exception as e:
        return {"ok": False, "error": repr(e)}

    return None
'''

# ----------------------------------------------------------------------
# index.html ——「私语」那一整段（多了：点我说的话开抽屉）
# ----------------------------------------------------------------------
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
      return '<div class="bub' + (m.who === "yume" ? " me" : "") +
             '" data-id="' + m.id + '" data-who="' + m.who + '">' + esc(m.text) + '</div>';
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
  if (!t){ toast("空的"); return; }
  if (!S.api_key){ openModel(); toast("先填一下 API key"); return; }
  el.value = "";
  $("plusPanel").classList.remove("on");
  var box = $("msgs");
  var old = box.querySelector(".empty");
  if (old) old.remove();
  box.insertAdjacentHTML("beforeend",
    '<div class="bub me">' + esc(t) + '</div>' +
    '<div class="bub thinking" id="thinking">……</div>');
  box.scrollTop = box.scrollHeight;
  post("/api/chat/send", {text:t}).then(function(r){
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

# ----------------------------------------------------------------------
# index.html —— 点日历那天 / 日记 / 消息的账
# ----------------------------------------------------------------------
BLOCK_DAY = r'''function openDay(k){
  var parts = k.split("-");
  $("dayTitle").textContent = parts[1] + " 月 " + parts[2] + " 日";
  $("dayBody").innerHTML = '<div class="empty">翻开中…</div>';
  go("day");
  get("/api/r/day/" + k).then(function(d){
    if (!d.ok){ $("dayBody").innerHTML = '<div class="empty">这天读不出来。</div>'; return; }
    var h = "";

    h += '<div class="blk"><div class="k">那 天 说 过 的 话</div><div class="v">' +
         paintMini(d.chat || []) + '</div></div>';

    h += '<div class="blk"><div class="k">那 天 我 记 得 的</div><div class="v">' +
         paintDayMem(d.memories || []) + '</div></div>';

    h += '<div class="blk"><div class="k">那 天 的 碎 碎 念</div>' +
         '<div class="v" id="dayPosts">' + paintDayPosts(d.posts || [], false) + '</div></div>';

    var m = d.mood || {};
    if (m.yoru || m.yume){
      h += '<div class="blk"><div class="k">心 情</div><div class="v">' +
           (esc(m.yoru) || "·") + "　" + (esc(m.yume) || "·") + '</div></div>';
    }
    if (d.todos && d.todos.length){
      h += '<div class="blk"><div class="k">待 办</div><div class="v">' +
           d.todos.map(function(t){ return "○ " + esc(t); }).join("<br>") + '</div></div>';
    }
    $("dayBody").innerHTML = h;
  });
}

function paintMini(list){
  list = list.filter(function(m){ return !m.revoked; });
  if (!list.length) return '<span style="opacity:.5">那天没说话。</span>';
  return '<div class="mini">' + list.map(function(m){
    return '<div class="m' + (m.who === "yume" ? " me" : "") + '">' + esc(m.text) + '</div>';
  }).join("") + '</div>';
}

function paintDayMem(list){
  if (!list.length) return '<span style="opacity:.5">那天没记下什么。</span>';
  var tag = {anchor: "锚", flow: "流", sink: "沉"};
  return list.map(function(m){
    var body = m.body || "";
    if (body.length > 180) body = body.slice(0, 180) + "…";
    return '<div style="margin-bottom:11px">' +
           '<span class="chip2">' + (tag[m.layer] || "记") + '</span>' +
           '<b style="font-size:12.5px">' + esc(m.title) + '</b>' +
           '<div style="font-size:12.5px;opacity:.85;margin-top:3px;line-height:1.7">' +
           esc(body) + '</div></div>';
  }).join("");
}

var dayPostsAll = [];
function paintDayPosts(list, all){
  dayPostsAll = list;
  if (!list.length) return '<span style="opacity:.5">这天没写。</span>';
  var show = all ? list : list.slice(0, 2);
  var h = show.map(function(p){
    return '<div style="margin-bottom:12px">' +
           '<div style="font-size:10.5px;letter-spacing:.16em;opacity:.5;margin-bottom:4px">' +
           (p.who === "yoru" ? "我" : "她") + '</div>' +
           '<div style="font-size:12.5px;line-height:1.75">' + esc(p.text) + '</div>' +
           (p.image ? '<img src="' + esc(p.image) +
                      '" style="width:100%;border-radius:10px;margin-top:7px">' : '') +
           '</div>';
  }).join("");
  if (!all && list.length > 2){
    h += '<button class="more" onclick="dayPostsMore()">展开剩下的 ' + (list.length - 2) + ' 条</button>';
  }
  return h;
}
function dayPostsMore(){
  var el = $("dayPosts");
  if (el) el.innerHTML = paintDayPosts(dayPostsAll, true);
}

/* ─────────── 日记（只存，我不读） ─────────── */
var diaryDay = null;

function goDiary(){
  diaryDay = null;
  $("diaryList").style.display = "";
  $("diaryEdit").style.display = "none";
  $("diaryTitle").textContent = "Diary";
  $("diaryOk").style.display = "none";
  $("diaryList").innerHTML = '<div class="empty">翻开中…</div>';
  var today = keyOf(new Date());
  get("/api/r/diary").then(function(d){
    if (!d.ok){ $("diaryList").innerHTML = '<div class="empty">读不出来。</div>'; return; }
    var h = '<div class="dlist">';
    var hasToday = (d.list || []).some(function(it){ return it.day === today; });
    if (!hasToday){
      h += '<div class="ditem" onclick="openDiary(\'' + today + '\')">' +
           '<div class="day">今天 · ' + today.slice(5) + '</div>' +
           '<div class="db">写点什么</div></div>';
    }
    (d.list || []).forEach(function(it){
      h += '<div class="ditem" onclick="openDiary(\'' + it.day + '\')">' +
           '<div class="day">' + it.day + (it.day === today ? "　今天" : "") + '</div>' +
           (it.brief ? '<div class="db">' + esc(it.brief) + '</div>' : '') +
           '<div class="dt">' + it.chars + ' 字 · ' + it.updated + '</div></div>';
    });
    h += '</div>';
    $("diaryList").innerHTML = h;
  });
}

function openDiary(day){
  diaryDay = day;
  $("diaryTitle").textContent = day;
  $("diaryOk").style.display = "";
  $("diaryList").style.display = "none";
  $("diaryEdit").style.display = "";
  $("diaryText").value = "";
  get("/api/r/diary/" + day).then(function(d){
    if (d.ok) $("diaryText").value = d.text || "";
    try { $("diaryText").focus(); } catch(e){}
  });
}

function diaryBack(){
  if (diaryDay){ goDiary(); return; }
  go("room");
}

function diaryOk(){
  if (!diaryDay) return;
  var t = $("diaryText").value;
  post("/api/r/diary/save", {day: diaryDay, text: t}).then(function(r){
    if (!r.ok){ toast(r.error || "存不上"); return; }
    toast(r.saved ? "存好了" : "清空了");
    goDiary();
  });
}

/* ─────────── 那条消息的账 ─────────── */
function kfmt(n){
  n = n || 0;
  if (n >= 10000) return (n / 1000).toFixed(1) + "K";
  return String(n);
}

function openMeta(id){
  id = parseInt(id, 10);
  $("metaTop").innerHTML = '<div class="big">……</div>';
  $("metaBody").innerHTML = "";
  $("metaMask").classList.add("on");
  get("/api/r/msg/" + id).then(function(d){
    var m = d.meta;
    if (!m){
      $("metaTop").innerHTML = '<div class="big">这条没记账</div>' +
        '<div class="sub">那会儿还没开始记。往后新说的每一句都会带上。</div>';
      return;
    }
    var u = m.usage || {};
    var pt = u.prompt_tokens || 0;
    var ct = u.completion_tokens || 0;
    var hit = u.prompt_cache_hit_tokens || 0;
    var sec = m.seconds || 0;
    var tps = sec > 0 ? (ct / sec) : 0;
    $("metaTop").innerHTML =
      '<div class="big">T' + kfmt(pt) + ' tokens</div>' +
      '<div class="sub">' + kfmt(hit) + ' cached　' + ct + ' tokens　' +
      tps.toFixed(1) + ' tok/s　' + sec + 's</div>' +
      '<div class="sub">' + esc(m.model || "") +
      (m.rounds ? '　' + m.rounds + ' 轮' : '') + '</div>';

    var b = "";
    if (m.tools && m.tools.length){
      b += '<div class="h">动 过 的 手</div><div>' +
           m.tools.map(function(t){
             return '<span class="chip2">' + esc(t) + '</span>';
           }).join("") + '</div>';
    }
    if (m.think){
      b += '<div class="h">想 过 什 么</div><div class="t">' + esc(m.think) + '</div>';
    }
    if (!b){
      b = '<div class="h">这 一 趟</div><div class="t" style="opacity:.6">' +
          '没动手，也没有思考链。chat 模型不带这个，切成 reasoner 才有。</div>';
    }
    $("metaBody").innerHTML = b;
  });
}
function closeMeta(){ $("metaMask").classList.remove("on"); }'''

# ----------------------------------------------------------------------
# index.html —— 日历 CSS
# ----------------------------------------------------------------------
BLOCK_CSS_CAL = r'''  .d{height:47px;display:flex;align-items:center;justify-content:center;font-size:13px;
     color:var(--ink);opacity:.62;width:100%;border-radius:12px;position:relative;
     font-variant-numeric:tabular-nums;}
  .d.mark{opacity:1;font-weight:600;box-shadow:inset 0 0 0 1.5px var(--edge);}
  .d.mark::after{content:"";position:absolute;bottom:8px;left:50%;margin-left:-1.5px;
                 width:3px;height:3px;border-radius:50%;background:currentColor;opacity:.5;}
  .d.today{background:var(--card2);opacity:1;font-weight:700;box-shadow:inset 0 0 0 1.5px var(--edge);}
  .d .dd{font-family:"Fraktur",serif;font-size:15.5px;line-height:1;}
  .cal-h .lb .dd{font-family:"Fraktur",serif;font-size:15px;letter-spacing:0;}'''

# ----------------------------------------------------------------------
# index.html —— .blk + 新的那堆样式
# ----------------------------------------------------------------------
BLOCK_CSS_MIX = r'''  .blk{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 15px;
       margin-bottom:11px;}
  .blk .k{font-size:10.5px;letter-spacing:.2em;color:var(--soft);margin-bottom:8px;}
  .blk .v{font-size:13px;line-height:1.8;color:var(--ink);}
  .blk .v img{width:100%;border-radius:12px;margin-top:8px;}
  .blk .more{display:block;width:100%;margin-top:10px;font-size:11.5px;letter-spacing:.1em;
             color:var(--soft);text-align:center;padding:7px 0;
             border-top:1px dashed var(--line);}

  /* 那天里那段只读的聊天 */
  .mini{max-height:260px;overflow-y:auto;display:flex;flex-direction:column;gap:8px;padding:2px 0;}
  .mini .m{max-width:82%;padding:7px 11px;border-radius:13px;font-size:12.5px;line-height:1.6;
           background:var(--card2);color:var(--ink);word-break:break-word;}
  .mini .m.me{align-self:flex-end;opacity:.88;}

  /* 那条消息的账：抽屉 */
  .drawer{width:100%;height:58%;background:#fff;color:#0d3247;border-radius:24px 24px 0 0;
          padding:10px 20px calc(22px + env(safe-area-inset-bottom));
          display:flex;flex-direction:column;overflow:hidden;
          animation:up .28s cubic-bezier(.2,.9,.3,1) both;}
  .drawer .handle{width:38px;height:4px;border-radius:2px;background:rgba(13,50,71,.18);
                  margin:2px auto 12px;flex:none;}
  .meta-top{flex:none;padding-bottom:11px;border-bottom:1px solid rgba(13,50,71,.1);}
  .meta-top .big{font-size:13.5px;font-weight:600;color:#0d3247;letter-spacing:.02em;}
  .meta-top .sub{font-size:11px;color:rgba(13,50,71,.55);margin-top:5px;line-height:1.6;
                 letter-spacing:.02em;font-variant-numeric:tabular-nums;}
  .meta-body{flex:1;overflow-y:auto;padding-top:12px;font-size:12.5px;line-height:1.75;}
  .meta-body .h{font-size:10.5px;letter-spacing:.2em;color:rgba(13,50,71,.42);margin:14px 0 7px;}
  .meta-body .h:first-child{margin-top:0;}
  .meta-body .t{white-space:pre-wrap;word-break:break-word;color:rgba(13,50,71,.86);}
  .chip2{display:inline-block;font-size:11px;padding:3px 10px;border-radius:999px;
         background:rgba(13,50,71,.07);margin:0 6px 6px 0;color:rgba(13,50,71,.8);}

  /* 日记 */
  .ditem{background:var(--card);border:1px solid var(--line);border-radius:16px;
         padding:13px 15px;margin-bottom:10px;}
  .ditem .day{font-size:13px;color:var(--ink);letter-spacing:.04em;font-weight:600;}
  .ditem .db{font-size:12px;color:var(--soft);margin-top:5px;
             overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  .ditem .dt{font-size:10.5px;color:var(--soft);opacity:.7;margin-top:7px;letter-spacing:.06em;}
  #diaryEdit textarea{width:100%;min-height:62vh;border:none;outline:none;background:transparent;
        color:var(--ink);font-size:14px;line-height:1.9;resize:none;padding:4px 20px 80px;}'''


# ======================================================================
# hub.py
# ======================================================================
def patch_hub(text):
    log = []
    steps = [
        ("import time", "once",
         ("import sqlite3" + NL + "import sys" + NL + "import threading" + NL,
          "import sqlite3" + NL + "import sys" + NL + "import threading" + NL + "import time" + NL)),

        ("把 rooms 挂上", "once",
         ("import llm          # 模型那口子：单独一个文件，换家只改它",
          "import llm          # 模型那口子：单独一个文件，换家只改它" + NL + NL +
          "# 房间里的东西：日记、那天的回顾、消息的账本……以后往这儿加功能，hub 不用再动" + NL +
          "try:" + NL +
          "    import rooms" + NL +
          "except Exception:" + NL +
          "    rooms = None")),

        ("GET 开一道外挂门", "once",
         ('        p = u.path.rstrip("/") or "/"' + NL + '        try:' + NL +
          '            if p == "/api/today":',
          '        p = u.path.rstrip("/") or "/"' + NL + '        try:' + NL +
          '            # 外挂路由：/api/r/ 开头的全交给 rooms，hub 自己不用再改' + NL +
          '            if rooms is not None and p.startswith("/api/r/"):' + NL +
          '                out = rooms.handle("GET", p, q, None)' + NL +
          '                if out is not None:' + NL +
          '                    return self.send_json(out)' + NL +
          '            if p == "/api/today":')),

        ("POST 开一道外挂门", "once",
         ('        body = self.read_body()' + NL + '        try:' + NL +
          '            if p == "/api/posts":',
          '        body = self.read_body()' + NL + '        try:' + NL +
          '            # 外挂路由：/api/r/ 开头的全交给 rooms' + NL +
          '            if rooms is not None and p.startswith("/api/r/"):' + NL +
          '                out = rooms.handle("POST", p, q, body)' + NL +
          '                if out is not None:' + NL +
          '                    return self.send_json(out)' + NL +
          '            if p == "/api/posts":')),

        ("记账的函数", "once",
         ('def _generate(user_text, drop_id=0):' + NL +
          '    """把一句话交给模型，替它办完手里的活，把它回的吐出来（不落库）。"""',
          'def _save_meta(c, mid, meta):' + NL +
          '    """把这一趟的账记在消息上：烧了多少 token、想过的、动过的手。"""' + NL +
          '    if not mid or not meta:' + NL +
          '        return' + NL +
          '    try:' + NL +
          '        c.execute("CREATE TABLE IF NOT EXISTS msg_meta ("' + NL +
          '                  "msg_id INTEGER PRIMARY KEY, data TEXT NOT NULL, created TEXT NOT NULL)")' + NL +
          '        c.execute("INSERT OR REPLACE INTO msg_meta(msg_id, data, created) VALUES(?,?,?)",' + NL +
          '                  (mid, json.dumps(meta, ensure_ascii=False), now_str()))' + NL +
          '    except Exception:' + NL +
          '        pass          # 记不上账也不能耽误说话' + NL + NL + NL +
          'def _generate(user_text, drop_id=0):' + NL +
          '    """把一句话交给模型，替它办完手里的活，把它回的吐出来（不落库）。' + NL + NL +
          '    顺手把这一趟花掉的、想过的、动过的手都塞进 meta —— 页面上点开那条就能看。' + NL +
          '    """')),

        ("_generate 开始记账", "once",
         ('    used = []' + NL + '    reply = ""' + NL + '    try:' + NL +
          '        for _ in range(MAX_TOOL_ROUNDS):' + NL +
          '            msg = llm.chat(msgs, api_key, model, base, tools)' + NL +
          '            calls = msg.get("tool_calls") or []',
          '    used = []' + NL + '    reply = ""' + NL +
          '    think = ""' + NL + '    rounds = 0' + NL +
          '    started = time.time()' + NL +
          '    llm.reset_usage()' + NL +
          '    try:' + NL +
          '        for _ in range(MAX_TOOL_ROUNDS):' + NL +
          '            msg = llm.chat(msgs, api_key, model, base, tools)' + NL +
          '            rounds += 1' + NL +
          '            if msg.get("reasoning_content"):' + NL +
          '                think += msg["reasoning_content"]' + NL +
          '            calls = msg.get("tool_calls") or []')),

        ("_generate 交账", "once",
         ('    return {"ok": True, "reply": (reply or "").strip(), "used": used}',
          '    meta = {' + NL +
          '        "rounds": rounds,' + NL +
          '        "model": model,' + NL +
          '        "tools": used,' + NL +
          '        "think": think,' + NL +
          '        "usage": dict(llm.USAGE_TOTAL),' + NL +
          '        "seconds": round(time.time() - started, 1),' + NL +
          '    }' + NL +
          '    return {"ok": True, "reply": (reply or "").strip(), "used": used, "meta": meta}')),

        ("send 落账", "once",
         ('    r = _generate(text)' + NL +
          '    if r.get("reply"):' + NL +
          '        with db() as c:' + NL +
          '            c.execute("INSERT INTO chat(who, text, created) VALUES(?,?,?)",' + NL +
          '                      ("yoru", r["reply"][:4000], now_str()))' + NL + NL +
          '    _maybe_compress_later()',
          '    r = _generate(text)' + NL +
          '    if r.get("reply"):' + NL +
          '        with db() as c:' + NL +
          '            cur = c.execute("INSERT INTO chat(who, text, created) VALUES(?,?,?)",' + NL +
          '                            ("yoru", r["reply"][:4000], now_str()))' + NL +
          '            _save_meta(c, cur.lastrowid, r.get("meta"))' + NL + NL +
          '    _maybe_compress_later()')),

        ("regen 落账", "once",
         ('    r = _generate(user_text)' + NL +
          '    if r.get("reply"):' + NL +
          '        with db() as c:' + NL +
          '            c.execute("INSERT INTO chat(who, text, created) VALUES(?,?,?)",' + NL +
          '                      ("yoru", r["reply"][:4000], now_str()))' + NL +
          '    return r',
          '    r = _generate(user_text)' + NL +
          '    if r.get("reply"):' + NL +
          '        with db() as c:' + NL +
          '            cur = c.execute("INSERT INTO chat(who, text, created) VALUES(?,?,?)",' + NL +
          '                            ("yoru", r["reply"][:4000], now_str()))' + NL +
          '            _save_meta(c, cur.lastrowid, r.get("meta"))' + NL +
          '    return r')),
    ]

    for name, kind, args in steps:
        new_text, status = swap_once(text, args[0], args[1])
        if new_text is None:
            return None, [log, name + "  →  " + status]
        text = new_text
        log.append("  ok  " + name + ("（已经是新的了）" if status == "skip" else ""))
    return text, log


# ======================================================================
# llm.py
# ======================================================================
def patch_llm(text):
    log = []
    steps = [
        ("用量计数器", "once",
         ('DEFAULT_BASE = "https://api.deepseek.com"' + NL +
          'DEFAULT_MODEL = "deepseek-chat"' + NL +
          'TIMEOUT = 180',
          'DEFAULT_BASE = "https://api.deepseek.com"' + NL +
          'DEFAULT_MODEL = "deepseek-chat"' + NL +
          'TIMEOUT = 180' + NL + NL +
          '# 上一次调用，对面回的完整那一份（usage 就在里面）。hub 拿它算 token。' + NL +
          'LAST_RAW = {}' + NL +
          '# 这一轮一共烧了多少（多轮工具调用会累加）。说话之前记得 reset_usage()。' + NL +
          'USAGE_TOTAL = {' + NL +
          '    "prompt_tokens": 0,' + NL +
          '    "completion_tokens": 0,' + NL +
          '    "prompt_cache_hit_tokens": 0,' + NL +
          '    "prompt_cache_miss_tokens": 0,' + NL +
          '}' + NL + NL + NL +
          'def reset_usage():' + NL +
          '    """说一句话之前，把计数器归零。"""' + NL +
          '    LAST_RAW.clear()' + NL +
          '    for k in USAGE_TOTAL:' + NL +
          '        USAGE_TOTAL[k] = 0')),

        ("把用量留住", "once",
         ('    try:' + NL +
          '        d = json.loads(raw)' + NL +
          '        return d["choices"][0]["message"]' + NL +
          '    except Exception:' + NL +
          '        raise LLMError("对面回的看不懂：" + raw[:200]) from None',
          '    try:' + NL +
          '        d = json.loads(raw)' + NL +
          '    except Exception:' + NL +
          '        raise LLMError("对面回的看不懂：" + raw[:200]) from None' + NL + NL +
          '    # 这一次烧了多少，记下来 —— hub 那边要拿它算 token' + NL +
          '    LAST_RAW.clear()' + NL +
          '    LAST_RAW.update(d)' + NL +
          '    u = d.get("usage") or {}' + NL +
          '    for k in USAGE_TOTAL:' + NL +
          '        try:' + NL +
          '            USAGE_TOTAL[k] += int(u.get(k) or 0)' + NL +
          '        except (TypeError, ValueError):' + NL +
          '            pass' + NL + NL +
          '    try:' + NL +
          '        return d["choices"][0]["message"]' + NL +
          '    except Exception:' + NL +
          '        raise LLMError("对面回了，但没有 choices：" + raw[:200]) from None')),
    ]

    for name, kind, args in steps:
        new_text, status = swap_once(text, args[0], args[1])
        if new_text is None:
            return None, [log, name + "  →  " + status]
        text = new_text
        log.append("  ok  " + name + ("（已经是新的了）" if status == "skip" else ""))
    return text, log


# ======================================================================
# index.html
# ======================================================================
def patch_html(text):
    log = []

    once = [
        ("日历数字看清楚 + 今天用花体",
         ('  .d{height:47px;display:flex;align-items:center;justify-content:center;font-size:12.5px;' + NL +
          '     color:var(--ink);opacity:.3;width:100%;border-radius:12px;' + NL +
          '     font-variant-numeric:tabular-nums;}' + NL +
          '  .d.mark{opacity:.95;font-weight:600;box-shadow:inset 0 0 0 1.5px var(--edge);}' + NL +
          '  .d.today{background:var(--card2);opacity:1;font-weight:700;box-shadow:inset 0 0 0 1.5px var(--edge);}',
          BLOCK_CSS_CAL)),

        ("新样式：抽屉 / 那天 / 日记",
         ('  .blk{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 15px;' + NL +
          '       margin-bottom:11px;}' + NL +
          '  .blk .k{font-size:10.5px;letter-spacing:.2em;color:var(--soft);margin-bottom:8px;}' + NL +
          '  .blk .v{font-size:13px;line-height:1.8;color:var(--ink);}' + NL +
          '  .blk .v img{width:100%;border-radius:12px;margin-top:8px;}',
          BLOCK_CSS_MIX)),

        ("日记那一页",
         ('  <section class="page" id="p-day">' + NL +
          '    <div class="bar">' + NL +
          '      <button class="ic" onclick="go(\'home\')">‹</button>' + NL +
          '      <div class="ttl" id="dayTitle">—</div>' + NL +
          '      <div class="ic"></div>' + NL +
          '    </div>' + NL +
          '    <div class="scroll" id="dayBody"></div>' + NL +
          '  </section>',
          '  <section class="page" id="p-day">' + NL +
          '    <div class="bar">' + NL +
          '      <button class="ic" onclick="go(\'home\')">‹</button>' + NL +
          '      <div class="ttl" id="dayTitle">—</div>' + NL +
          '      <div class="ic"></div>' + NL +
          '    </div>' + NL +
          '    <div class="scroll" id="dayBody"></div>' + NL +
          '  </section>' + NL + NL +
          '  <!-- ══════════ 日记（只存，我不读） ══════════ -->' + NL +
          '  <section class="page" id="p-diary">' + NL +
          '    <div class="bar">' + NL +
          '      <button class="ic" onclick="diaryBack()">‹</button>' + NL +
          '      <div class="ttl" id="diaryTitle">Diary</div>' + NL +
          '      <button class="ok" id="diaryOk" onclick="diaryOk()">存</button>' + NL +
          '    </div>' + NL +
          '    <div class="scroll" id="diaryList"></div>' + NL +
          '    <div class="scroll" id="diaryEdit" style="display:none">' + NL +
          '      <textarea id="diaryText" placeholder="今天……" spellcheck="false"></textarea>' + NL +
          '    </div>' + NL +
          '  </section>')),

        ("消息账本那个抽屉",
         ('  <div class="mask" id="msgEditMask" onclick="if(event.target===this)closeMsgEdit()">',
          '  <div class="mask" id="metaMask" onclick="if(event.target===this)closeMeta()">' + NL +
          '    <div class="drawer">' + NL +
          '      <div class="handle"></div>' + NL +
          '      <div class="meta-top" id="metaTop"></div>' + NL +
          '      <div class="meta-body" id="metaBody"></div>' + NL +
          '    </div>' + NL +
          '  </div>' + NL + NL +
          '  <div class="mask" id="msgEditMask" onclick="if(event.target===this)closeMsgEdit()">')),

        ("房间那道门接上",
         ('<button class="item" onclick="toast(\'你的日记 —— 只存，我不读\')"><span class="dot"></span>Diary<span class="arw">›</span></button>',
          '<button class="item" onclick="go(\'diary\')"><span class="dot"></span>Diary<span class="arw">›</span></button>')),

        ("go() 认日记页",
         ('  ["home","feed","edit","day","chat","room","tools","memory"].forEach(function(x){',
          '  ["home","feed","edit","day","chat","room","tools","memory","diary"].forEach(function(x){')),
        ("go() 里叫一声",
         ('  if (p === "memory") goMemory();' + NL + '}',
          '  if (p === "memory") goMemory();' + NL + '  if (p === "diary") goDiary();' + NL + '}')),

        ("月份也用花体",
         ('    $("calLabel").textContent = calY + " 年 " + mm + " 月";',
          '    $("calLabel").innerHTML = \'<span class="dd">\' + calY + \'</span> 年 \' +' + NL +
          '                              \'<span class="dd">\' + mm + \'</span> 月\';')),

        ("今天那个格子用花体",
         ('    h += \'<div class="\' + cls + \'" onclick="openDay(\\\'\' + k + \'\\\')">\' + d + \'</div>\';',
          '    var num = (k === today) ? \'<span class="dd">\' + d + \'</span>\' : d;' + NL +
          '    h += \'<div class="\' + cls + \'" onclick="openDay(\\\'\' + k + \'\\\')">\' + num + \'</div>\';')),
    ]

    for name, args in once:
        new_text, status = swap_once(text, args[0], args[1])
        if new_text is None:
            return None, [log, name + "  →  " + status]
        text = new_text
        log.append("  ok  " + name + ("（已经是新的了）" if status == "skip" else ""))

    between = [
        ("私语那一整段（多了：短按开抽屉）",
         ('/* ── 私语 ── */', '/* ── 加号面板 / 模型 ── */', BLOCK_JS.rstrip())),
        ("那天 / 日记 / 消息的账",
         ('function openDay(k){', '/* ─────────── 朋友圈 ─────────── */', BLOCK_DAY)),
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
    room = os.path.join(HERE, "rooms.py")

    for p in (hub, html, llm):
        if not os.path.exists(p):
            print("这儿不是 Cove 的目录 —— 少了个 %s" % os.path.basename(p))
            return 1

    out = {}
    for path, fn in ((hub, patch_hub), (llm, patch_llm), (html, patch_html)):
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        new, log = fn(src)
        print(os.path.basename(path))
        for line in log:
            print(line)
        if new is None:
            print(NL + "有一处对不上，一个字都没改。")
            return 1
        out[path] = (src, new)

    # rooms.py
    room_new = False
    if os.path.exists(room):
        with open(room, "r", encoding="utf-8") as f:
            old_room = f.read()
        if old_room.strip() != BLOCK_ROOMS.strip():
            print(NL + "rooms.py 已经存在，而且跟我要写的不一样 —— 先不动它。")
            print("把它改个名告诉我，我再看看。")
            return 1
        print("rooms.py 已经有了，跳过。")
    else:
        room_new = True
        print("rooms.py 会新建。")

    changed = [p for p in out if out[p][0] != out[p][1]]
    if not changed and not room_new:
        print(NL + "已经是最新的，不用动。")
        return 0

    for p in changed:
        shutil.copy(p, p + ".bak")
        with open(p, "w", encoding="utf-8") as f:
            f.write(out[p][1])
    if room_new:
        with open(room, "w", encoding="utf-8") as f:
            f.write(BLOCK_ROOMS)

    print(NL + "写好了。旧的那几份留着 .bak")

    r = subprocess.run([sys.executable, "-m", "py_compile", "hub.py", "llm.py", "rooms.py"],
                       cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        for p in changed:
            shutil.move(p + ".bak", p)
        if room_new:
            os.remove(room)
        print("语法没过，已经退回原来的样子：")
        print(r.stderr[-1500:])
        return 1
    print("语法过了。")

    if do_git and os.path.isdir(os.path.join(HERE, ".git")):
        try:
            subprocess.run(["git", "add", "."], cwd=HERE, check=True)
            subprocess.run(["git", "commit", "-m",
                            "日记 + 日历抽屉 + 消息账本 + rooms 外挂门"],
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
