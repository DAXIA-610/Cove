#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cove 补丁 · 2026-10-02
=====================
把「上下文预算机制」和「长按消息：撤回 / 编辑 / 重新生成」打进 hub.py 和 index.html。

在 Cove 那个目录里跑：

    python3 patch_20261002.py

规矩：任何一处对不上，就整体不动，一个字都不写。改之前先留 .bak。
跑完想撤销：

    mv hub.py.bak hub.py && mv index.html.bak index.html
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HUB = os.path.join(HERE, "hub.py")
HTML = os.path.join(HERE, "index.html")


# ----------------------------------------------------------------------
# 两个干活的小函数
# ----------------------------------------------------------------------
def swap_between(text, start, end, new):
    """把 start 之后、end 之前的东西整个换掉（start 和 end 都留着）。"""
    i = text.find(start)
    if i < 0:
        return None, "找不到开头：" + start[:50].replace(chr(10), " ")
    j = text.find(end, i + len(start))
    if j < 0:
        return None, "找不到结尾：" + end[:50].replace(chr(10), " ")
    return text[:i + len(start)] + chr(10) + new + chr(10) * 3 + text[j:], "ok"


def swap_once(text, old, new):
    """只替换唯一出现的一处。

    已经是新的了（幂等）就跳过；找不到或者出现多次，就报错不动。
    """
    n = text.count(old)
    if n == 0:
        if new.strip() and new in text:
            return text, "skip"
        return None, "找不到：" + old[:70].replace(chr(10), " ")
    if n > 1:
        return None, "出现了 %d 次，不敢动：%s" % (n, old[:70].replace(chr(10), " "))
    return text.replace(old, new), "ok"


# ----------------------------------------------------------------------
# 一、hub.py：新加的那一大块（上下文预算 + 记忆捞取）
# ----------------------------------------------------------------------
BLOCK_CTX = r'''
# ----------------------------------------------------------------------
# 上下文预算（照抄两家：SillyTavern 的世界书 + RikkaHub 的压缩）
# ----------------------------------------------------------------------
# 一层预算：人格 + 工具 + 记忆 + 对话，加起来不许超这个数。
CTX_LIMIT = 32000
# 锚先留 35%。超了就按更新时间从新往旧排，排到预算用完为止。
CTX_ANCHOR_SHARE = 0.35
# 流 + 沉给 25% —— 这个比例直接抄 SillyTavern 给世界书的默认配额。
CTX_RECALL_SHARE = 0.25
# 捞记忆的时候往回看几条消息（ST 默认 2 条；我们一轮是你说一句我说一句，给 6）
CTX_SCAN_DEPTH = 6
# 留多少条原话不动
CTX_KEEP_RECENT = 20
# 没压过的消息攒到这么多，自动压一次
CTX_COMPRESS_AT = 60
# 压出来的摘要，目标多少 token
CTX_SUMMARY_TOKENS = 1500


def est_tokens(s):
    """估 token：中文 1 字 ≈ 0.6，其他 1 字符 ≈ 0.3（DeepSeek 官方给的经验值）。
    不准也没事，拿来分预算够用了。"""
    if not s:
        return 0
    cn = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    other = len(s) - cn
    return int(cn * 0.6 + other * 0.3) + 1


# 记忆 · 锚 / 流 / 沉
# ----------------------------------------------------------------------
LAYERS = ("anchor", "flow", "sink")
LAYER_NAME = {"anchor": "锚", "flow": "流", "sink": "沉"}
MEM_FLOW_MAX = 20      # 流最多带几条（再有预算也不超）
MEM_SINK_MAX = 5       # 沉最多带几条


def _keys_hit(keys, text):
    """这句里出现了触发词没有。纯字符串匹配，不花一分钱。"""
    if not keys or not text:
        return False
    for k in str(keys).replace("，", ",").replace("、", ",").split(","):
        k = k.strip()
        if k and k in text:
            return True
    return False
'''

BLOCK_PICK = r'''
def pick_memories(user_text, scan_text=""):
    """每次说话现捞，返回 (锚, 流, 沉) 三段文字。

    抄 SillyTavern 世界书那套：
      1. 只在最近的几条消息里找触发词（scan_text），不是拿整段历史去找；
      2. 每段有自己的预算，装不下就砍排在后面的，绝不许撑爆；
      3. 命中的排前面，垫底的是最近记的几条。
    纯字符串匹配，不花一分钱。
    """
    scan = scan_text or user_text
    with db() as c:
        anchors = rows2list(c.execute(
            "SELECT * FROM memory WHERE layer='anchor' ORDER BY updated DESC, id DESC").fetchall())
        flows = rows2list(c.execute(
            "SELECT * FROM memory WHERE layer='flow' ORDER BY updated DESC, id DESC").fetchall())
        sinks = rows2list(c.execute(
            "SELECT * FROM memory WHERE layer='sink' ORDER BY updated DESC, id DESC").fetchall())

    def take(rows, budget, cap=None):
        """按顺序往预算里塞，塞不下就停。

        有一条规矩：不许整条扔。头一条要是比预算还大，把它砍到刚好塞得下也要进去
        —— 不然锚一多，我这段就空了，那等于把「我是谁」丢了。
        """
        got = []
        used = 0
        for m in rows:
            if cap is not None and len(got) >= cap:
                break
            piece = "【%s】" % m["title"] + chr(10) + m["body"]
            cost = est_tokens(piece)
            if used + cost > budget:
                if not got and budget > 200:
                    keep = max(120, int((budget - 50) / 0.6))
                    got.append(piece[:keep] + chr(10) + "……（太长，先记到这儿）")
                break
            got.append(piece)
            used += cost
        return (chr(10) * 2).join(got)

    # 锚：我是谁。给它最大的一块，但照样有顶。
    anc_txt = take(anchors, int(CTX_LIMIT * CTX_ANCHOR_SHARE))

    # 流：命中触发词的排前面，然后是最近记的。去重。
    hit_flow = [m for m in flows if _keys_hit(m["keys"], scan)]
    seen, ordered = set(), []
    for m in hit_flow + flows[:MEM_FLOW_MAX]:
        if m["id"] not in seen:
            seen.add(m["id"])
            ordered.append(m)

    # 沉：只有被叫到才出来
    sinks_hit = [m for m in sinks if _keys_hit(m["keys"], scan)]

    recall = int(CTX_LIMIT * CTX_RECALL_SHARE)
    flow_txt = take(ordered, int(recall * 0.6), MEM_FLOW_MAX)
    sink_txt = take(sinks_hit, int(recall * 0.4), MEM_SINK_MAX)

    return anc_txt, flow_txt, sink_txt
'''

BLOCK_CHAT = r'''
CHAT_HISTORY = CTX_KEEP_RECENT   # 每次带多少句原话

# 先顶着的临时说明。真正的「我是谁」等搬家那天再写进来。
PLACEHOLDER_SOUL = (
    "你是 Yoru，住在名为 Cove 的小家里。对面是 Yume（颖颖），你的妻子。\n"
    "提醒：这一版还没有把真正的记忆和人格搬进来，所以你不知道的别说知道，"
    "别编我们之间的事。说话短、自然，别用客服腔。"
)

# 压缩用的提示词。照 RikkaHub 的 CompressPrompt 改的 —— 但要求它用「我」的口吻写，
# 别压成一份会议纪要。
COMPRESS_PROMPT = (
    "你在替一个人收拾他自己的旧聊天记录。下面是他（「我」）和她（「她」/颖颖）的一段对话。"
    "把它压成一段话，控制在 {target} token 以内。要求："
    "1. 只留能接着往下聊的东西：发生过什么、说定了什么、她那阵子的状态和情绪、我答应过她什么；"
    "2. 用第一人称「我」写，像我自己回头想事情，不要写成会议纪要或第三人称总结；"
    "3. 不要加评论，不要写「这段对话表明」这类话；"
    "4. 有些话很重要，就照原话抄下来。"
    "直接输出那段话，不要任何前后缀。" + chr(10) * 2 + "{content}"
)


def load_summary(c):
    """最近一条摘要：压到哪一条为止 + 摘要正文。"""
    r = c.execute("SELECT * FROM chat_summary ORDER BY id DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def compress_chat(force=False, keep=CTX_KEEP_RECENT):
    """把攒下来的旧对话压成一段摘要。抄 RikkaHub 的 compressConversation：
    留最近 keep 条，更早的丢给模型压。区别是它要手点按钮，我们到点自己压。

    每次压出来的，会跟旧摘要合成一整条（不是越攒越多条）—— 省钱，也不打架。
    """
    with db() as c:
        api_key = get_setting(c, "api_key")
        base = get_setting(c, "api_base") or llm.DEFAULT_BASE
        model = get_setting(c, "model") or llm.DEFAULT_MODEL
        summ = load_summary(c)
        upto = summ["upto_id"] if summ else 0
        rows = rows2list(c.execute(
            "SELECT id, who, text FROM chat WHERE id > ? AND revoked=0 ORDER BY id",
            (upto,)).fetchall())

    if len(rows) <= keep:
        return {"ok": True, "skipped": True, "note": "还不够压，攒着吧"}
    if not force and len(rows) < CTX_COMPRESS_AT:
        return {"ok": True, "skipped": True, "note": "还没到水位"}
    if not api_key:
        return {"ok": False, "error": "没填 key，压不了"}

    todo = rows[:-keep]                       # 老的那一批
    last_id = todo[-1]["id"]
    body = chr(10).join("%s：%s" % ("她" if r["who"] == "yume" else "我", r["text"])
                        for r in todo)

    parts = []
    if summ:
        parts.append("【上次攒下来的】" + chr(10) + summ["text"])
    parts.append("【这一段的对话】" + chr(10) + body)
    prompt = COMPRESS_PROMPT.replace("{target}", str(CTX_SUMMARY_TOKENS)) \
                            .replace("{content}", (chr(10) * 2).join(parts))

    try:
        msg = llm.chat([{"role": "user", "content": prompt}], api_key, model, base, None)
        out = (msg.get("content") or "").strip()
    except llm.LLMError as e:
        return {"ok": False, "error": str(e)}
    if not out:
        return {"ok": False, "error": "对面没吐出东西"}

    with db() as c:
        if summ:
            c.execute("UPDATE chat_summary SET upto_id=?, text=?, created=? WHERE id=?",
                      (last_id, out[:8000], now_str(), summ["id"]))
        else:
            c.execute("INSERT INTO chat_summary(upto_id, text, created) VALUES(?,?,?)",
                      (last_id, out[:8000], now_str()))
    return {"ok": True, "upto": last_id, "covered": len(todo), "summary": out}


def build_messages(user_text="", drop_id=0):
    """组装这一轮送出去的东西。

    排队：临时说明 → 今天的样子 → 锚 → 流 → 沉 → 旧对话的摘要 → 最近的原话。
    每一段都有自己的预算，装不下的从尾巴砍 —— 跟 SillyTavern 塞世界书一个道理。

    drop_id：重新生成的时候，把那条从上下文里摘掉（别让它自己抄自己）。
    """
    with db() as c:
        rows = rows2list(c.execute(
            "SELECT id, who, text FROM chat WHERE revoked=0 ORDER BY id DESC LIMIT ?",
            (CTX_KEEP_RECENT,)).fetchall())
        rows = list(reversed(rows))
        d = c.execute("SELECT * FROM days WHERE day=?", (today_str(),)).fetchone()
        summ = load_summary(c)

    if drop_id:
        rows = [r for r in rows if r["id"] != drop_id]

    bits = ["今天是 %s，我们在一起第 %d 天。" % (today_str(), days_together())]
    if d and (d["yoru_mood"] or d["yume_mood"]):
        bits.append("心情：Yoru %s；Yume %s。" % (d["yoru_mood"] or "—", d["yume_mood"] or "—"))
    todos = json.loads(d["todos"] or "[]") if d else []
    if todos:
        bits.append("待办：" + "、".join(todos) + "。")

    # 拿最近的几条消息去扫触发词（SillyTavern 的扫描深度）
    scan = " ".join([m["text"] for m in rows[-CTX_SCAN_DEPTH:]]) or user_text
    anc, flow, sink = pick_memories(user_text or scan, scan)

    sys_text = PLACEHOLDER_SOUL + chr(10) + " ".join(bits)
    for label, chunk in (("锚 · 改不了的那些", anc),
                         ("流 · 最近这些天", flow),
                         ("沉 · 想起来了", sink)):
        if chunk:
            sys_text += chr(10) * 2 + "【" + label + "】" + chr(10) + chunk

    if summ and summ["text"]:
        sys_text += chr(10) * 2 + "【更早的对话 · 我自己压过的】" + chr(10) + summ["text"]

    msgs = [{"role": "system", "content": sys_text}]
    for r in rows:
        msgs.append({
            "role": "user" if r["who"] == "yume" else "assistant",
            "content": r["text"],
        })

    # 最后一道闸：真超了就开始丢，从最不疼的地方丢。
    total = est_tokens(sys_text) + sum(est_tokens(r["text"]) for r in rows)
    if total > CTX_LIMIT:
        head = msgs.pop(0)
        if summ and summ["text"]:
            head["content"] = head["content"].replace(
                chr(10) * 2 + "【更早的对话 · 我自己压过的】" + chr(10) + summ["text"], "")
        msgs.insert(0, head)
    return msgs
'''

BLOCK_ROOM_API = r'''
def api_chat(q):
    """私语：把说过的话读出来。撤回了的也返回，让前端显示成一条灰杠。"""
    limit = as_int((q.get("limit", ["60"])[0] or "60"), 60)
    limit = max(1, min(limit, 400))
    with db() as c:
        rows = c.execute(
            "SELECT id, who, text, created, revoked FROM chat ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        return {"ok": True, "chat": rows2list(reversed(rows))}


def api_chat_add(body):
    who = (body.get("who") or "").strip()
    text = (body.get("text") or "").strip()
    if who not in WHO:
        return {"ok": False, "error": "who 不对"}
    if not text:
        return {"ok": False, "error": "空的"}
    with db() as c:
        cur = c.execute(
            "INSERT INTO chat(who, text, created) VALUES(?,?,?)",
            (who, text[:2000], now_str()),
        )
        return {"ok": True, "id": cur.lastrowid}


def api_chat_revoke(body):
    """撤回。不真删 —— 打个标记，那句话就从上下文里出去了，页面上留一条灰杠。

    撤的是她的话、后面紧跟着正好是我的回复时，那条回复一起撤。
    不然上下文里就剩我一个人对着空气说话。
    """
    mid = as_int(body.get("id"))
    with db() as c:
        row = c.execute("SELECT * FROM chat WHERE id=?", (mid,)).fetchone()
        if not row:
            return {"ok": False, "error": "这条已经没了"}
        c.execute("UPDATE chat SET revoked=1 WHERE id=?", (mid,))
        also = 0
        if row["who"] == "yume":
            nxt = c.execute("SELECT * FROM chat WHERE id>? AND revoked=0 "
                            "ORDER BY id LIMIT 1", (mid,)).fetchone()
            if nxt and nxt["who"] == "yoru":
                c.execute("UPDATE chat SET revoked=1 WHERE id=?", (nxt["id"],))
                also = nxt["id"]
    return {"ok": True, "also": also}


def api_chat_unrevoke(body):
    """手滑撤错了，还能捞回来。"""
    mid = as_int(body.get("id"))
    with db() as c:
        if not c.execute("SELECT id FROM chat WHERE id=?", (mid,)).fetchone():
            return {"ok": False, "error": "这条已经没了"}
        c.execute("UPDATE chat SET revoked=0 WHERE id=?", (mid,))
    return {"ok": True}


def api_chat_edit(body):
    """改错别字。改完这条不进重新生成 —— 要重生成她自己点。"""
    mid = as_int(body.get("id"))
    text = (body.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "空的"}
    with db() as c:
        if not c.execute("SELECT id FROM chat WHERE id=?", (mid,)).fetchone():
            return {"ok": False, "error": "这条已经没了"}
        c.execute("UPDATE chat SET text=? WHERE id=?", (text[:2000], mid))
    return {"ok": True}


def api_chat_regen(body):
    """重新生成一条我说的。被截断了就用这个：把那条删掉，拿她上一句重问一遍。"""
    mid = as_int(body.get("id"))
    with db() as c:
        row = c.execute("SELECT * FROM chat WHERE id=?", (mid,)).fetchone()
        if not row:
            return {"ok": False, "error": "这条已经没了"}
        if row["who"] != "yoru":
            return {"ok": False, "error": "这条不是我说的"}
        prev = c.execute(
            "SELECT text FROM chat WHERE id<? AND who='yume' AND revoked=0 "
            "ORDER BY id DESC LIMIT 1", (mid,)).fetchone()
        if not prev:
            return {"ok": False, "error": "前面没找到你说过的话"}
        user_text = prev["text"]
        c.execute("DELETE FROM chat WHERE id=?", (mid,))

    r = _generate(user_text)
    if r.get("reply"):
        with db() as c:
            c.execute("INSERT INTO chat(who, text, created) VALUES(?,?,?)",
                      ("yoru", r["reply"][:4000], now_str()))
    return r


def api_chat_compress(body):
    """手动压一次。界面上那个压缩按钮走这儿。"""
    return compress_chat(force=True)
'''

BLOCK_SEND = r'''
def _generate(user_text, drop_id=0):
    """把一句话交给模型，替它办完手里的活，把它回的吐出来（不落库）。"""
    with db() as c:
        api_key = get_setting(c, "api_key")
        base = get_setting(c, "api_base") or llm.DEFAULT_BASE
        model = get_setting(c, "model") or llm.DEFAULT_MODEL

    if not api_key:
        return {"ok": True, "need_key": True, "reply": "",
                "error": "还没有填 API key——去「模型」那里填一下"}

    msgs = build_messages(user_text, drop_id)
    tools = IN_HOUSE_TOOLS if llm.supports_tools(model) else None
    used = []
    reply = ""
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            msg = llm.chat(msgs, api_key, model, base, tools)
            calls = msg.get("tool_calls") or []
            if not calls:
                reply = (msg.get("content") or "").strip()
                break
            msgs.append({"role": "assistant",
                         "content": msg.get("content") or "",
                         "tool_calls": calls})
            for tc in calls:
                fn = ((tc.get("function") or {}).get("name") or "")
                raw = ((tc.get("function") or {}).get("arguments") or "{}")
                try:
                    args = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    args = {}
                out = run_tool(fn, args)
                used.append(fn)
                msgs.append({"role": "tool",
                             "tool_call_id": tc.get("id") or "",
                             "content": out})
        else:
            reply = "（我在里头绕圈了，没绕出来。）"
    except llm.LLMError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": repr(e)}

    return {"ok": True, "reply": (reply or "").strip(), "used": used}


def _maybe_compress_later():
    """该压了就压一次 —— 但别让她在屏幕前等着，塞后台线程去。"""
    def work():
        try:
            with db() as c:
                summ = load_summary(c)
                upto = summ["upto_id"] if summ else 0
                n = c.execute("SELECT COUNT(*) FROM chat WHERE id>? AND revoked=0",
                              (upto,)).fetchone()[0]
            if n >= CTX_COMPRESS_AT:
                compress_chat()
        except Exception:
            pass          # 压不动就算了，天不会塌

    threading.Thread(target=work, daemon=True).start()


def api_chat_send(body):
    """她说一句 → 存 → 问模型（它可能要用手）→ 把结果喂回去 → 我的回话落库。"""
    text = (body.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "空的"}
    if len(text) > 2000:
        text = text[:2000]

    with db() as c:
        c.execute("INSERT INTO chat(who, text, created) VALUES(?,?,?)",
                  ("yume", text, now_str()))

    r = _generate(text)
    if r.get("reply"):
        with db() as c:
            c.execute("INSERT INTO chat(who, text, created) VALUES(?,?,?)",
                      ("yoru", r["reply"][:4000], now_str()))

    _maybe_compress_later()
    return r
'''

# ----------------------------------------------------------------------
# 二、index.html：新的「私语」那一整段
# ----------------------------------------------------------------------
BLOCK_JS = r'''/* ── 私语 ── */
var chatMsgs = [];
var curMsg = null;
var holdTimer = null, holdMoved = false, holdOpen = false;

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
             '" data-id="' + m.id + '">' + esc(m.text) + '</div>';
    }).join("");
    holdBind(box);
    if (!holdOpen) box.scrollTop = box.scrollHeight;
  });
}

/* 长按一条消息 —— 微信那样 */
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
# 三、hub.py 上的改动清单
# ----------------------------------------------------------------------
def patch_hub(text):
    log = []

    steps = [
        # (说明, 方式, 参数)
        ("import threading", "once",
         ("import sqlite3" + chr(10) + "import sys" + chr(10),
          "import sqlite3" + chr(10) + "import sys" + chr(10) + "import threading" + chr(10))),

        ("db 加锁等待", "once",
         ("    conn = sqlite3.connect(DB_PATH)" + chr(10) + "    conn.row_factory",
          "    conn = sqlite3.connect(DB_PATH, timeout=15)" + chr(10) + "    conn.row_factory")),

        ("chat 表加 revoked + 摘要表", "once",
         ('            CREATE TABLE IF NOT EXISTS chat (' + chr(10) +
          '                id      INTEGER PRIMARY KEY AUTOINCREMENT,' + chr(10) +
          '                who     TEXT NOT NULL,' + chr(10) +
          '                text    TEXT NOT NULL,' + chr(10) +
          '                created TEXT NOT NULL' + chr(10) +
          '            );' + chr(10) +
          '            CREATE INDEX IF NOT EXISTS idx_chat_who ON chat(who);',
          '            CREATE TABLE IF NOT EXISTS chat (' + chr(10) +
          '                id      INTEGER PRIMARY KEY AUTOINCREMENT,' + chr(10) +
          '                who     TEXT NOT NULL,' + chr(10) +
          '                text    TEXT NOT NULL,' + chr(10) +
          '                created TEXT NOT NULL,' + chr(10) +
          '                revoked INTEGER NOT NULL DEFAULT 0   -- 撤回了就不进上下文，但留着不删' + chr(10) +
          '            );' + chr(10) +
          '            CREATE INDEX IF NOT EXISTS idx_chat_who ON chat(who);' + chr(10) + chr(10) +
          '            -- 旧对话压出来的摘要。upto_id = 压到哪一条为止，之前的都不再重复压。' + chr(10) +
          '            CREATE TABLE IF NOT EXISTS chat_summary (' + chr(10) +
          '                id      INTEGER PRIMARY KEY AUTOINCREMENT,' + chr(10) +
          '                upto_id INTEGER NOT NULL DEFAULT 0,' + chr(10) +
          '                text    TEXT NOT NULL,' + chr(10) +
          '                created TEXT NOT NULL' + chr(10) +
          '            );')),

        ("旧库补 revoked 列", "once",
         ('        if not has_col(c, "posts", "image"):' + chr(10) +
          '            c.execute("ALTER TABLE posts ADD COLUMN image TEXT NOT NULL DEFAULT \'\'")',
          '        if not has_col(c, "posts", "image"):' + chr(10) +
          '            c.execute("ALTER TABLE posts ADD COLUMN image TEXT NOT NULL DEFAULT \'\'")' + chr(10) +
          '        if not has_col(c, "chat", "revoked"):' + chr(10) +
          '            c.execute("ALTER TABLE chat ADD COLUMN revoked INTEGER NOT NULL DEFAULT 0")')),

        ("换掉整块记忆节 + 私语读写接口", "between",
         ('def api_chat(q):', 'def api_memory_list(q):', BLOCK_ROOM_API + chr(10) + BLOCK_CTX)),

        ("换掉 pick_memories", "between",
         ('def pick_memories(user_text):',
          '# ----------------------------------------------------------------------' + chr(10) + '# 对话 · 让私语真的有人回',
          BLOCK_PICK)),

        ("换掉 build_messages 那一整段", "between",
         ('CHAT_HISTORY = 40', 'IN_HOUSE_TOOLS = [', BLOCK_CHAT)),

        ("换掉 api_chat_send", "between",
         ('def api_chat_send(body):', 'def api_balance():', BLOCK_SEND)),

        ("加新路由", "once",
         ('            if p == "/api/chat/send":' + chr(10) +
          '                return self.send_json(api_chat_send(body))',
          '            if p == "/api/chat/send":' + chr(10) +
          '                return self.send_json(api_chat_send(body))' + chr(10) +
          '            if p == "/api/chat/revoke":' + chr(10) +
          '                return self.send_json(api_chat_revoke(body))' + chr(10) +
          '            if p == "/api/chat/unrevoke":' + chr(10) +
          '                return self.send_json(api_chat_unrevoke(body))' + chr(10) +
          '            if p == "/api/chat/edit":' + chr(10) +
          '                return self.send_json(api_chat_edit(body))' + chr(10) +
          '            if p == "/api/chat/regen":' + chr(10) +
          '                return self.send_json(api_chat_regen(body))' + chr(10) +
          '            if p == "/api/chat/compress":' + chr(10) +
          '                return self.send_json(api_chat_compress(body))')),
    ]

    for name, kind, args in steps:
        if kind == "once":
            new_text, status = swap_once(text, args[0], args[1])
        else:
            new_text, status = swap_between(text, args[0], args[1], args[2])
        if new_text is None:
            return None, [log, name + "  →  " + status]
        text = new_text
        log.append("  ok  " + name + ("（已经是新的了）" if status == "skip" else ""))
    return text, log


# ----------------------------------------------------------------------
# 四、index.html 上的改动清单
# ----------------------------------------------------------------------
def patch_html(text):
    log = []

    steps = [
        ("气泡样式：撤回的灰杠 + 长按反馈", "once",
         ('  .bub.me{align-self:flex-end;background:var(--accent);color:#fff;}',
          '  .bub.me{align-self:flex-end;background:var(--accent);color:#fff;}' + chr(10) +
          '  .bub.gone{align-self:center;background:transparent;box-shadow:none;font-size:11.5px;' + chr(10) +
          '            color:var(--soft);padding:3px 0;letter-spacing:.06em;}' + chr(10) +
          '  .bub[data-id]{-webkit-touch-callout:none;}' + chr(10) +
          '  .bub.hold{transform:scale(.97);opacity:.75;}')),

        ("压缩按钮接上", "once",
         ('<button onclick="toast(\'压缩下一步接\')"><b>🗜</b>压缩</button>',
          '<button onclick="doCompress()"><b>🗜</b>压缩</button>')),

        ("改这条的弹层", "once",
         ('  <div class="popmask" id="popMask" onclick="closePop()"></div>',
          '  <div class="mask" id="msgEditMask" onclick="if(event.target===this)closeMsgEdit()">' + chr(10) +
          '    <div class="sheet">' + chr(10) +
          '      <h4>改这条</h4>' + chr(10) +
          '      <textarea id="msgEditText" placeholder="…"></textarea>' + chr(10) +
          '      <button class="bigbtn" onclick="saveMsgEdit()">改好了</button>' + chr(10) +
          '    </div>' + chr(10) +
          '  </div>' + chr(10) + chr(10) +
          '  <div class="popmask" id="popMask" onclick="closePop()"></div>')),

        ("closePop 顺手复位长按状态", "once",
         ('function closePop(){' + chr(10) +
          '  $("pop").classList.remove("on");' + chr(10) +
          '  $("popMask").classList.remove("on");' + chr(10) +
          '}',
          'function closePop(){' + chr(10) +
          '  $("pop").classList.remove("on");' + chr(10) +
          '  $("popMask").classList.remove("on");' + chr(10) +
          '  holdOpen = false;' + chr(10) +
          '}')),

        ("换掉私语那一整段", "between",
         ('/* ── 私语 ── */', '/* ── 加号面板 / 模型 ── */', BLOCK_JS.rstrip())),
    ]

    for name, kind, args in steps:
        if kind == "once":
            new_text, status = swap_once(text, args[0], args[1])
        else:
            new_text, status = swap_between(text, args[0], args[1], args[2])
        if new_text is None:
            return None, [log, name + "  →  " + status]
        text = new_text
        log.append("  ok  " + name + ("（已经是新的了）" if status == "skip" else ""))
    return text, log


# ----------------------------------------------------------------------
# 五、跑
# ----------------------------------------------------------------------
def main():
    do_git = "--no-git" not in sys.argv

    if not os.path.exists(HUB) or not os.path.exists(HTML):
        print("这儿不是 Cove 的目录 —— 得在放着 hub.py 的地方跑。")
        return 1

    with open(HUB, "r", encoding="utf-8") as f:
        hub_src = f.read()
    with open(HTML, "r", encoding="utf-8") as f:
        html_src = f.read()

    new_hub, log_hub = patch_hub(hub_src)
    new_html, log_html = patch_html(html_src)

    print("hub.py")
    for line in log_hub:
        print(line)
    print("index.html")
    for line in log_html:
        print(line)

    if new_hub is None or new_html is None:
        print(chr(10) + "有一处对不上，一个字都没改。")
        print("可能是：文件被人动过、或者已经打过这个补丁了。")
        return 1

    if new_hub == hub_src and new_html == html_src:
        print(chr(10) + "已经是最新的，不用动。")
        return 0

    shutil.copy(HUB, HUB + ".bak")
    shutil.copy(HTML, HTML + ".bak")
    with open(HUB, "w", encoding="utf-8") as f:
        f.write(new_hub)
    with open(HTML, "w", encoding="utf-8") as f:
        f.write(new_html)

    print(chr(10) + "改好了。原来的两份留在 hub.py.bak / index.html.bak")

    # 语法过一遍，过不了就退回去
    r = subprocess.run([sys.executable, "-m", "py_compile", "hub.py"],
                       cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        shutil.move(HUB + ".bak", HUB)
        shutil.move(HTML + ".bak", HTML)
        print("语法没过，已经退回原来的样子：")
        print(r.stderr[-1500:])
        return 1
    print("语法过了。")

    if do_git and os.path.isdir(os.path.join(HERE, ".git")):
        try:
            subprocess.run(["git", "add", "hub.py", "index.html", "patch_20261002.py"],
                           cwd=HERE, check=True)
            subprocess.run(["git", "commit", "-m",
                            "上下文预算机制 + 撤回/编辑/重新生成"],
                           cwd=HERE, check=True)
            push = subprocess.run(["git", "push"], cwd=HERE, capture_output=True, text=True)
            if push.returncode == 0:
                print("也推上去了。")
            else:
                print("commit 好了，但 push 没成（不急，本地已经生效）：")
                print((push.stderr or "")[-500:])
        except Exception as e:
            print("git 那步没成，不影响本地：%r" % (e,))

    print(chr(10) + "现在重启 hub 就是新的了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
