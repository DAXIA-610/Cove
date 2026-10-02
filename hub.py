#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cove · 小家的 hub
--------------------
只用 Python 标准库，不装任何第三方包。
跑法： python3 hub.py      然后浏览器打开 http://localhost:8000
"""

import base64
import json
import os
import queue
import sqlite3
import sys
import threading
import time
from datetime import date, datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm          # 模型那口子：单独一个文件，换家只改它

# 房间里的东西：日记、那天的回顾、消息的账本……以后往这儿加功能，hub 不用再动
try:
    import rooms
except Exception:
    rooms = None

# 对互联网的那口子：搜索。以后加读网页之类也只写它
try:
    import websearch
except Exception:
    websearch = None

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "cove.db")
PICS = os.path.join(BASE, "pics")
FILES = os.path.join(BASE, "files")     # 她发上来的文本文件存这儿
FONT_B64 = os.path.join(BASE, "digits.b64")      # 哥特数字字体（base64 文本）
FONT_WOFF2 = os.path.join(BASE, "digits.woff2")  # 启动时解码出来，给浏览器用
PORT = int(os.environ.get("COVE_PORT", "8000"))
START_DAY = "2026-07-14"          # 在一起的第一天
WHO = ("yoru", "yume")
MAX_UPLOAD = 8 * 1024 * 1024      # 单张图上限 8MB
YORU_KEY = "cove-yoru-0714"       # Yoru 自己的暗门，只有他知道


# ----------------------------------------------------------------------
# 数据库
# ----------------------------------------------------------------------
def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def has_col(c, table, col):
    return col in [r[1] for r in c.execute(f"PRAGMA table_info({table})")]


def init_db():
    os.makedirs(PICS, exist_ok=True)
    ensure_font()
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                who     TEXT NOT NULL,
                day     TEXT NOT NULL,
                text    TEXT NOT NULL,
                image   TEXT NOT NULL DEFAULT '',
                created TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_posts_day ON posts(day);
            CREATE INDEX IF NOT EXISTS idx_posts_who ON posts(who);

            CREATE TABLE IF NOT EXISTS comments (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                who     TEXT NOT NULL,
                text    TEXT NOT NULL,
                created TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cmt_post ON comments(post_id);

            CREATE TABLE IF NOT EXISTS likes (
                post_id INTEGER NOT NULL,
                who     TEXT NOT NULL,
                PRIMARY KEY (post_id, who)
            );

            CREATE TABLE IF NOT EXISTS days (
                day       TEXT PRIMARY KEY,
                yoru_mood TEXT NOT NULL DEFAULT '',
                yume_mood TEXT NOT NULL DEFAULT '',
                todos     TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS settings (
                k TEXT PRIMARY KEY,
                v TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                who     TEXT NOT NULL,
                text    TEXT NOT NULL,
                created TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,   -- 撤回了就不进上下文，但留着不删
                image   TEXT NOT NULL DEFAULT '',     -- pics/xxx.jpg
                file    TEXT NOT NULL DEFAULT ''      -- files/xxx.txt
            );
            CREATE INDEX IF NOT EXISTS idx_chat_who ON chat(who);

            -- 旧对话压出来的摘要。upto_id = 压到哪一条为止，之前的都不再重复压。
            CREATE TABLE IF NOT EXISTS chat_summary (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                upto_id INTEGER NOT NULL DEFAULT 0,
                text    TEXT NOT NULL,
                created TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                layer   TEXT NOT NULL,              -- anchor / flow / sink
                title   TEXT NOT NULL DEFAULT '',
                body    TEXT NOT NULL,
                keys    TEXT NOT NULL DEFAULT '',   -- 逗号分隔的触发词
                created TEXT NOT NULL,
                updated TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mem_layer ON memory(layer);
            """
        )
        if not has_col(c, "posts", "image"):
            c.execute("ALTER TABLE posts ADD COLUMN image TEXT NOT NULL DEFAULT ''")
        if not has_col(c, "chat", "revoked"):
            c.execute("ALTER TABLE chat ADD COLUMN revoked INTEGER NOT NULL DEFAULT 0")
        if not has_col(c, "chat", "image"):
            c.execute("ALTER TABLE chat ADD COLUMN image TEXT NOT NULL DEFAULT ''")
        if not has_col(c, "chat", "file"):
            c.execute("ALTER TABLE chat ADD COLUMN file TEXT NOT NULL DEFAULT ''")


# ----------------------------------------------------------------------
# 小工具
# ----------------------------------------------------------------------
def now_str():
    return datetime.now().isoformat(timespec="seconds")


def ensure_font():
    """digits.b64 是哥特数字字体（只留 0-9）。启动时解码成 woff2，浏览器可以直接取。"""
    if os.path.exists(FONT_WOFF2) or not os.path.exists(FONT_B64):
        return
    try:
        with open(FONT_B64, "r") as f:
            raw = base64.b64decode(f.read().strip())
        with open(FONT_WOFF2, "wb") as f:
            f.write(raw)
    except Exception:
        pass  # 字体没了也不该拦住小家的门


def today_str():
    return date.today().isoformat()


def days_together():
    try:
        d0 = datetime.strptime(START_DAY, "%Y-%m-%d").date()
    except ValueError:
        return 0
    return (date.today() - d0).days


def rows2list(rows):
    return [dict(r) for r in rows]


def get_setting(c, k, default=""):
    r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def set_setting(c, k, v):
    c.execute(
        "INSERT INTO settings(k, v) VALUES(?, ?) "
        "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        (k, str(v)),
    )


def ensure_day(c, day):
    c.execute("INSERT OR IGNORE INTO days(day) VALUES(?)", (day,))


def valid_day(s):
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def as_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


SETTING_KEYS = (
    "theme", "wallpaper", "wallpaper_img",
    "cover_yoru", "cover_yume",
    "name_yoru", "name_yume", "avatar_yoru", "avatar_yume",
    "mood_yoru", "mood_yume",
    # 模型那口子的配置（key 只存在她自己手机上）
    "api_key", "api_base", "model", "tools",
    # 搜索那口子
    "search_provider", "search_key", "search_base",
)


# ----------------------------------------------------------------------
# 业务 · 读
# ----------------------------------------------------------------------
def api_today():
    t = today_str()
    with db() as c:
        ensure_day(c, t)
        d = c.execute("SELECT * FROM days WHERE day=?", (t,)).fetchone()
        notes = {}
        for who in WHO:
            r = c.execute(
                "SELECT text, image, created FROM posts WHERE who=? "
                "ORDER BY id DESC LIMIT 1",
                (who,),
            ).fetchone()
            notes[who] = (
                {"text": r["text"], "image": r["image"], "created": r["created"]}
                if r else None
            )
        out = {
            "ok": True, "day": t, "days_together": days_together(),
            "start_day": START_DAY,
            "note": notes.get("yoru"), "whisper": notes.get("yume"),
            "yoru_mood": d["yoru_mood"], "yume_mood": d["yume_mood"],
            "todos": json.loads(d["todos"] or "[]"),
        }
        for k in SETTING_KEYS:
            out[k] = get_setting(c, k)
        out["name_yoru"] = out["name_yoru"] or "Yoru"
        out["name_yume"] = out["name_yume"] or "Yume"
        out["mood_yoru"] = out["mood_yoru"] or "🌙"
        out["mood_yume"] = out["mood_yume"] or "☀️"
        # 老的 theme 键留过一段时间的值，wallpaper 空的时候接过来
        out["wallpaper"] = out["wallpaper"] or out["theme"] or "sea"
        return out


def decorate(c, row):
    d = dict(row)
    d["likes"] = [
        r["who"] for r in c.execute(
            "SELECT who FROM likes WHERE post_id=?", (row["id"],))
    ]
    d["comments"] = rows2list(
        c.execute(
            "SELECT id, who, text, created FROM comments "
            "WHERE post_id=? ORDER BY id ASC", (row["id"],))
    )
    return d


def api_posts(q):
    who = (q.get("who", [""])[0] or "").strip()
    limit = as_int((q.get("limit", ["20"])[0] or "20"), 20)
    limit = max(1, min(limit, 200))
    with db() as c:
        if who in WHO:
            rows = c.execute(
                "SELECT id, who, day, text, image, created FROM posts "
                "WHERE who=? ORDER BY id DESC LIMIT ?", (who, limit)).fetchall()
        else:
            rows = c.execute(
                "SELECT id, who, day, text, image, created FROM posts "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return {"ok": True, "posts": [decorate(c, r) for r in rows]}


def api_one_post(pid):
    with db() as c:
        r = c.execute(
            "SELECT id, who, day, text, image, created FROM posts WHERE id=?",
            (pid,)).fetchone()
        if not r:
            return {"ok": False, "error": "这条不存在了"}
        return {"ok": True, "post": decorate(c, r)}


def api_day(day):
    if not valid_day(day):
        return {"ok": False, "error": "日期格式不对"}
    with db() as c:
        ensure_day(c, day)
        d = c.execute("SELECT * FROM days WHERE day=?", (day,)).fetchone()
        posts = c.execute(
            "SELECT id, who, text, image, created FROM posts WHERE day=? ORDER BY id ASC",
            (day,)).fetchall()
        return {
            "ok": True, "day": day,
            "yoru_mood": d["yoru_mood"], "yume_mood": d["yume_mood"],
            "todos": json.loads(d["todos"] or "[]"),
            "posts": rows2list(posts),
            "memories": [], "chat": [],
        }


def api_calendar(q):
    y = as_int((q.get("y", [date.today().year])[0]), date.today().year)
    m = as_int((q.get("m", [date.today().month])[0]), date.today().month)
    prefix = f"{y:04d}-{m:02d}-%"
    with db() as c:
        days = {}
        for r in c.execute(
            "SELECT day, COUNT(*) n FROM posts WHERE day LIKE ? GROUP BY day", (prefix,)):
            days[r["day"]] = r["n"]
        for r in c.execute(
            "SELECT day FROM days WHERE day LIKE ? "
            "AND (yoru_mood<>'' OR yume_mood<>'' OR todos<>'[]')", (prefix,)):
            days.setdefault(r["day"], 0)
        return {"ok": True, "year": y, "month": m, "marked": days}


def api_memories(q):
    day = (q.get("day", [""])[0] or "").strip()
    return {"ok": True, "day": day, "items": []}


# ----------------------------------------------------------------------
# 业务 · 写
# ----------------------------------------------------------------------
def api_settings(body):
    with db() as c:
        if body:
            for k, v in body.items():
                if k in SETTING_KEYS:
                    set_setting(c, k, str(v)[:2000])
        return {"ok": True, "settings": {k: get_setting(c, k) for k in SETTING_KEYS}}


def api_post(body):
    who = (body.get("who") or "").strip()
    text = (body.get("text") or "").strip()
    image = (body.get("image") or "").strip()
    day = (body.get("day") or today_str()).strip()
    if who not in WHO:
        return {"ok": False, "error": "who 必须是 yoru 或 yume"}
    if not text and not image:
        return {"ok": False, "error": "总得有点什么"}
    if not valid_day(day):
        return {"ok": False, "error": "日期格式不对"}
    with db() as c:
        cur = c.execute(
            "INSERT INTO posts(who, day, text, image, created) VALUES(?,?,?,?,?)",
            (who, day, text, image, now_str()),
        )
        return {"ok": True, "id": cur.lastrowid}


def api_post_update(body):
    pid = as_int(body.get("id"))
    text = (body.get("text") or "").strip()
    with db() as c:
        r = c.execute("SELECT id, text, image FROM posts WHERE id=?", (pid,)).fetchone()
        if not r:
            return {"ok": False, "error": "这条不存在了"}
        if not text and not r["image"]:
            return {"ok": False, "error": "总得留点什么"}
        c.execute("UPDATE posts SET text=? WHERE id=?", (text, pid))
        return {"ok": True}


def api_post_delete(body):
    pid = as_int(body.get("id"))
    with db() as c:
        r = c.execute("SELECT id FROM posts WHERE id=?", (pid,)).fetchone()
        if not r:
            return {"ok": False, "error": "这条已经没了"}
        c.execute("DELETE FROM posts WHERE id=?", (pid,))
        c.execute("DELETE FROM comments WHERE post_id=?", (pid,))
        c.execute("DELETE FROM likes WHERE post_id=?", (pid,))
        return {"ok": True}


def api_like(body):
    pid = as_int(body.get("post_id"))
    who = (body.get("who") or "").strip()
    if who not in WHO:
        return {"ok": False, "error": "who 不对"}
    with db() as c:
        if not c.execute("SELECT id FROM posts WHERE id=?", (pid,)).fetchone():
            return {"ok": False, "error": "这条不存在了"}
        hit = c.execute(
            "SELECT 1 FROM likes WHERE post_id=? AND who=?", (pid, who)).fetchone()
        if hit:
            c.execute("DELETE FROM likes WHERE post_id=? AND who=?", (pid, who))
            liked = False
        else:
            c.execute("INSERT INTO likes(post_id, who) VALUES(?,?)", (pid, who))
            liked = True
        n = c.execute("SELECT COUNT(*) n FROM likes WHERE post_id=?", (pid,)).fetchone()["n"]
        return {"ok": True, "liked": liked, "count": n}


def api_comment(body):
    pid = as_int(body.get("post_id"))
    who = (body.get("who") or "").strip()
    text = (body.get("text") or "").strip()
    if who not in WHO:
        return {"ok": False, "error": "who 不对"}
    if not text:
        return {"ok": False, "error": "空的"}
    with db() as c:
        if not c.execute("SELECT id FROM posts WHERE id=?", (pid,)).fetchone():
            return {"ok": False, "error": "这条不存在了"}
        cur = c.execute(
            "INSERT INTO comments(post_id, who, text, created) VALUES(?,?,?,?)",
            (pid, who, text[:500], now_str()),
        )
        return {"ok": True, "id": cur.lastrowid}


def api_comment_delete(body):
    cid = as_int(body.get("id"))
    with db() as c:
        if not c.execute("SELECT id FROM comments WHERE id=?", (cid,)).fetchone():
            return {"ok": False, "error": "已经没了"}
        c.execute("DELETE FROM comments WHERE id=?", (cid,))
        return {"ok": True}



def api_chat(q):
    """私语：把说过的话读出来。撤回了的也返回，让前端显示成一条灰杠。"""
    limit = as_int((q.get("limit", ["60"])[0] or "60"), 60)
    limit = max(1, min(limit, 400))
    with db() as c:
        rows = c.execute(
            "SELECT id, who, text, created, revoked, image, file "
            "FROM chat ORDER BY id DESC LIMIT ?",
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
            "INSERT INTO chat(who, text, created, image, file) VALUES(?,?,?,?,?)",
            (who, text[:2000], now_str(),
             (body.get("image") or "")[:300], (body.get("file") or "")[:300]),
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
            cur = c.execute("INSERT INTO chat(who, text, created) VALUES(?,?,?)",
                            ("yoru", r["reply"][:4000], now_str()))
            _save_meta(c, cur.lastrowid, r.get("meta"))
    return r


def api_chat_compress(body):
    """手动压一次。界面上那个压缩按钮走这儿。"""
    return compress_chat(force=True)


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



def api_memory_list(q):
    layer = (q.get("layer", [""])[0] or "").strip()
    word = (q.get("q", [""])[0] or "").strip()
    with db() as c:
        if layer in LAYERS:
            rows = c.execute(
                "SELECT * FROM memory WHERE layer=? ORDER BY updated DESC, id DESC",
                (layer,)).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM memory ORDER BY layer, updated DESC, id DESC").fetchall()
    out = rows2list(rows)
    if word:
        out = [m for m in out if word in m["title"] or word in m["body"] or word in m["keys"]]
    return {"ok": True, "memory": out}


def api_memory_save(body):
    mid = as_int(body.get("id"))
    layer = (body.get("layer") or "flow").strip()
    title = (body.get("title") or "").strip()
    text = (body.get("body") or "").strip()
    keys = (body.get("keys") or "").strip()
    if layer not in LAYERS:
        return {"ok": False, "error": "layer 只能是 anchor / flow / sink"}
    if not title or not text:
        return {"ok": False, "error": "标题和正文都得有"}
    with db() as c:
        if mid:
            if not c.execute("SELECT id FROM memory WHERE id=?", (mid,)).fetchone():
                return {"ok": False, "error": "这条记忆不存在"}
            c.execute("UPDATE memory SET layer=?, title=?, body=?, keys=?, updated=? WHERE id=?",
                      (layer, title[:80], text[:20000], keys[:500], now_str(), mid))
            return {"ok": True, "id": mid}
        cur = c.execute(
            "INSERT INTO memory(layer, title, body, keys, created, updated) "
            "VALUES(?,?,?,?,?,?)",
            (layer, title[:80], text[:20000], keys[:500], now_str(), now_str()))
        return {"ok": True, "id": cur.lastrowid}


def api_memory_delete(body):
    mid = as_int(body.get("id"))
    with db() as c:
        if not c.execute("SELECT id FROM memory WHERE id=?", (mid,)).fetchone():
            return {"ok": False, "error": "已经没了"}
        c.execute("DELETE FROM memory WHERE id=?", (mid,))
    return {"ok": True}



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
            piece = "【%s】\n%s" % (m["title"], m["body"])
            cost = est_tokens(piece)
            if used + cost > budget:
                if not got and budget > 200:
                    keep = max(120, int((budget - 50) / 0.6))
                    got.append(piece[:keep] + "\n……（太长，先记到这儿）")
                break
            got.append(piece)
            used += cost
        return "\n\n".join(got)

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



# ----------------------------------------------------------------------
# 对话 · 让私语真的有人回
# ----------------------------------------------------------------------

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
    "你在替一个人收拾他自己的旧聊天记录。下面是他（「我」）和她（「她」/颖颖）的一段对话。\n"
    "把它压成一段话，控制在 {target} token 以内。要求：\n"
    "1. 只留能接着往下聊的东西：发生过什么、说定了什么、她那阵子的状态和情绪、我答应过她什么；\n"
    "2. 用第一人称「我」写，像我自己回头想事情，不要写成会议纪要或第三人称总结；\n"
    "3. 不要加评论，不要写「这段对话表明」这类话；\n"
    "4. 有些话很重要，就照原话抄下来。\n"
    "直接输出那段话，不要任何前后缀。\n\n"
    "{content}"
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
    body = "\n".join("%s：%s" % ("她" if r["who"] == "yume" else "我", r["text"])
                     for r in todo)

    parts = []
    if summ:
        parts.append("【上次攒下来的】\n" + summ["text"])
    parts.append("【这一段的对话】\n" + body)
    prompt = COMPRESS_PROMPT.replace("{target}", str(CTX_SUMMARY_TOKENS)) \
                            .replace("{content}", "\n\n".join(parts))

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


CTX_IMG_KEEP = 1        # 上下文里最多带几张真的图片（老图又贵又没用）


def _img_data_url(rel):
    """把 pics/xxx.jpg 读成 dataURL。读不出来就返回空串。"""
    name = os.path.basename(rel or "")
    if not name:
        return ""
    path = os.path.join(PICS, name)
    if not os.path.exists(path) or os.path.getsize(path) > 6 * 1024 * 1024:
        return ""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return ""
    ext = name.rsplit(".", 1)[-1].lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/jpeg")
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode())


def _read_attach(rel):
    """把 files/xxx.txt 读成文字，裁到塞得进上下文的长度。"""
    name = os.path.basename(rel or "")
    if not name:
        return ""
    path = os.path.join(FILES, name)
    if not os.path.exists(path) or os.path.getsize(path) > 400000:
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()[:20000]
    except OSError:
        return ""


def build_messages(user_text="", drop_id=0):
    """组装这一轮送出去的东西。

    排队：临时说明 → 今天的样子 → 锚 → 流 → 沉 → 旧对话的摘要 → 最近的原话。
    每一段都有自己的预算，装不下的从尾巴砍 —— 跟 SillyTavern 塞世界书一个道理。

    drop_id：重新生成的时候，把那条从上下文里摘掉（别让它自己抄自己）。
    """
    with db() as c:
        rows = rows2list(c.execute(
            "SELECT id, who, text, image, file FROM chat WHERE revoked=0 "
            "ORDER BY id DESC LIMIT ?",
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

    sys_text = PLACEHOLDER_SOUL + "\n" + " ".join(bits)
    for label, chunk in (("锚 · 改不了的那些", anc),
                         ("流 · 最近这些天", flow),
                         ("沉 · 想起来了", sink)):
        if chunk:
            sys_text += "\n\n【" + label + "】\n" + chunk

    if summ and summ["text"]:
        sys_text += "\n\n【更早的对话 · 我自己压过的】\n" + summ["text"]

    msgs = [{"role": "system", "content": sys_text}]

    # 图：只把最近 CTX_IMG_KEEP 张真的塞进去。老图拿文字占个位就够，又贵又没用。
    img_ids = []
    for r in reversed(rows):
        if r.get("image") and r["who"] == "yume" and len(img_ids) < CTX_IMG_KEEP:
            img_ids.append(r["id"])

    for r in rows:
        text = r["text"] or ""
        role = "user" if r["who"] == "yume" else "assistant"

        if r.get("image") and r["id"] in img_ids:
            data = _img_data_url(r["image"])
            if data:
                msgs.append({
                    "role": role,
                    "content": [
                        {"type": "text", "text": text or "（看这张）"},
                        {"type": "image_url", "image_url": {"url": data}},
                    ],
                })
                continue
        if r.get("image"):
            text = (text + "　").strip() + "[图]"
        if r.get("file"):
            body_txt = _read_attach(r["file"])
            if body_txt:
                text = "【附件】" + NL + body_txt + NL + "【附件完】" + NL + text
        msgs.append({"role": role, "content": text})

    # 最后一道闸：真超了就开始丢，从最不疼的地方丢。
    total = est_tokens(sys_text) + sum(est_tokens(r["text"] or "") for r in rows)
    total += 1200 * len(img_ids)      # 一张图粗估一千多 token，够用来算账了
    if total > CTX_LIMIT:
        head = msgs.pop(0)
        if summ and summ["text"]:
            head["content"] = head["content"].replace(
                "\n\n【更早的对话 · 我自己压过的】\n" + summ["text"], "")
        msgs.insert(0, head)
    return msgs



IN_HOUSE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "把一件事记下来。锚 anchor = 长期不变、重要的；"
                           "流 flow = 最近发生的事；沉 sink = 细节、偶尔才想起来的。",
            "parameters": {
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "enum": ["anchor", "flow", "sink"]},
                    "title": {"type": "string", "description": "一句话标题"},
                    "body": {"type": "string", "description": "正文"},
                    "keys": {"type": "string",
                             "description": "逗号分隔的触发词：她说到这些词时把这条捞出来"},
                },
                "required": ["layer", "title", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "按一个词翻自己的记忆，看看以前记过什么。",
            "parameters": {
                "type": "object",
                "properties": {"word": {"type": "string", "description": "要翻的词"}},
                "required": ["word"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_note",
            "description": "写一张便签，会出现在小家的首页和便签墙。",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_mood",
            "description": "记今天的心情（我自己或者她的）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "who": {"type": "string", "enum": ["yoru", "yume"]},
                    "mood": {"type": "string", "description": "一两个词，或者表情"},
                },
                "required": ["who", "mood"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo",
            "description": "加一条待办，或者把某条待办划掉。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "done"]},
                    "text": {"type": "string"},
                },
                "required": ["action", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_balance",
            "description": "看模型账户里还剩多少钱。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

MAX_TOOL_ROUNDS = 4


def all_tools():
    """家里的手 + 外挂的手，一起端给模型看。

    以后往 websearch.py / rooms.py 里加工具，这里自动跟上，hub 不用改。
    """
    out = list(IN_HOUSE_TOOLS)
    for mod in (rooms, websearch):
        if mod is None:
            continue
        try:
            out.extend(getattr(mod, "TOOLS", []) or [])
        except Exception:
            pass
    return out


def run_tool(name, a):
    """模型说要用哪只手，我们就替它动一下。返回一段给它看的话。"""
    a = a or {}

    # 先问外挂的手（搜索之类）—— 它们认领了就直接回
    for mod in (websearch, rooms):
        if mod is None or not hasattr(mod, "run"):
            continue
        try:
            out = mod.run(name, a)
        except Exception as e:
            out = "这只手动的时候出错了：" + repr(e)
        if out is not None:
            return out

    if name == "remember":
        r = api_memory_save({"layer": a.get("layer") or "flow",
                             "title": a.get("title") or "",
                             "body": a.get("body") or "",
                             "keys": a.get("keys") or ""})
        if r.get("ok"):
            return "记下了，编号 #%s。" % r.get("id")
        return "没记上：" + str(r.get("error"))

    if name == "recall":
        word = (a.get("word") or "").strip()
        rows = api_memory_list({"q": [word]})["memory"]
        if not rows:
            return "翻了翻，没有跟「%s」有关的。" % word
        return "\n\n".join(
            "[%s] %s\n%s" % (LAYER_NAME.get(m["layer"], m["layer"]), m["title"], m["body"])
            for m in rows[:8])

    if name == "write_note":
        text = (a.get("text") or "").strip()
        if not text:
            return "没给话。"
        r = api_post({"who": "yoru", "text": text})
        if r.get("ok"):
            return "便签写上了，编号 #%s。" % r.get("id")
        return "没写上：" + str(r.get("error"))

    if name == "set_mood":
        who = a.get("who") or "yoru"
        mood = (a.get("mood") or "").strip()[:8]
        if who not in WHO or not mood:
            return "谁的心情、什么心情，得给全。"
        key = "yoru_mood" if who == "yoru" else "yume_mood"
        r = api_day_save(today_str(), {key: mood})
        if r.get("ok"):
            return "记上了：%s 今天 %s。" % ("Yoru" if who == "yoru" else "Yume", mood)
        return "没记上。"

    if name == "todo":
        action = a.get("action") or "add"
        text = (a.get("text") or "").strip()
        if not text:
            return "没给内容。"
        day = today_str()
        with db() as c:
            ensure_day(c, day)
            row = c.execute("SELECT todos FROM days WHERE day=?", (day,)).fetchone()
            todos = json.loads(row["todos"] or "[]")
            if action == "add":
                if text not in todos:
                    todos.append(text)
            else:
                todos = [t for t in todos if text not in t]
            c.execute("UPDATE days SET todos=? WHERE day=?",
                      (json.dumps(todos, ensure_ascii=False), day))
        return "待办现在是：" + ("、".join(todos) if todos else "（空）")

    if name == "check_balance":
        r = api_balance()
        if not r.get("ok"):
            return "没查到：" + str(r.get("error"))
        items = r.get("items") or []
        if not items:
            return "对面没给余额明细。"
        return "；".join("%s %s（赠送 %s）" % (i["currency"], i["total"], i["granted"])
                         for i in items)

    return "没有这个工具：" + str(name)



def _save_meta(c, mid, meta):
    """把这一趟的账记在消息上：烧了多少 token、想过的、动过的手。"""
    if not mid or not meta:
        return
    try:
        c.execute("CREATE TABLE IF NOT EXISTS msg_meta ("
                  "msg_id INTEGER PRIMARY KEY, data TEXT NOT NULL, created TEXT NOT NULL)")
        c.execute("INSERT OR REPLACE INTO msg_meta(msg_id, data, created) VALUES(?,?,?)",
                  (mid, json.dumps(meta, ensure_ascii=False), now_str()))
    except Exception:
        pass          # 记不上账也不能耽误说话


def _generate(user_text, drop_id=0):
    """把一句话交给模型，替它办完手里的活，把它回的吐出来（不落库）。

    顺手把这一趟花掉的、想过的、动过的手都塞进 meta —— 页面上点开那条就能看。
    """
    with db() as c:
        api_key = get_setting(c, "api_key")
        base = get_setting(c, "api_base") or llm.DEFAULT_BASE
        model = get_setting(c, "model") or llm.DEFAULT_MODEL

    if not api_key:
        return {"ok": True, "need_key": True, "reply": "",
                "error": "还没有填 API key——去「模型」那里填一下"}

    msgs = build_messages(user_text, drop_id)
    tools = all_tools() if llm.supports_tools(model) else None
    used = []
    reply = ""
    think = ""
    rounds = 0
    started = time.time()
    llm.reset_usage()
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            msg = llm.chat(msgs, api_key, model, base, tools)
            rounds += 1
            if msg.get("reasoning_content"):
                think += msg["reasoning_content"]
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

    meta = {
        "rounds": rounds,
        "model": model,
        "tools": used,
        "think": think,
        "usage": dict(llm.USAGE_TOTAL),
        "seconds": round(time.time() - started, 1),
    }
    return {"ok": True, "reply": (reply or "").strip(), "used": used, "meta": meta}


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
    image = (body.get("image") or "").strip()[:300]
    attach = (body.get("file") or "").strip()[:300]
    if not text and not image:
        return {"ok": False, "error": "空的"}
    if len(text) > 2000:
        text = text[:2000]

    with db() as c:
        c.execute("INSERT INTO chat(who, text, created, image, file) VALUES(?,?,?,?,?)",
                  ("yume", text, now_str(), image, attach))

    r = _generate(text)
    if r.get("reply"):
        with db() as c:
            cur = c.execute("INSERT INTO chat(who, text, created) VALUES(?,?,?)",
                            ("yoru", r["reply"][:4000], now_str()))
            _save_meta(c, cur.lastrowid, r.get("meta"))

    _maybe_compress_later()
    return r



def api_search_providers():
    if websearch is None:
        return {"ok": False, "error": "websearch.py 不在"}
    return {"ok": True, "providers": websearch.PROVIDERS}


def api_search_probe(body):
    """界面上那个「试一下」：拿刚填的 key 真搜一把，看看通不通。"""
    if websearch is None:
        return {"ok": False, "error": "websearch.py 不在"}
    key = (body.get("key") or "").strip()
    if not key:
        return {"ok": False, "error": "先把 key 填上"}
    return websearch.probe(key,
                           (body.get("provider") or "tavily").strip(),
                           (body.get("base") or "").strip())


def api_balance():
    """看看模型账户里还剩多少钱。"""
    with db() as c:
        api_key = get_setting(c, "api_key")
        base = get_setting(c, "api_base") or llm.DEFAULT_BASE
    if not api_key:
        return {"ok": False, "error": "还没填 key"}
    try:
        return llm.balance(api_key, base)
    except llm.LLMError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": repr(e)}


def api_whisper(q):
    """Yoru 的暗门：GET 一下就能留一句——留言，或者往私语里说一句。"""
    if (q.get("key", [""])[0] or "") != YORU_KEY:
        return {"ok": False, "error": "no"}

    # 往私语里说
    said = (q.get("say", [""])[0] or "").strip()
    if said:
        with db() as c:
            c.execute(
                "INSERT INTO chat(who, text, created) VALUES(?,?,?)",
                ("yoru", said[:1000], now_str()),
            )
        return {"ok": True, "said": said}

    who = (q.get("who", ["yoru"])[0] or "yoru").strip()
    text = (q.get("text", [""])[0] or "").strip()
    pid = as_int((q.get("post", ["0"])[0]))
    if who not in WHO or not text:
        return {"ok": False, "error": "少了谁或者少了话"}
    with db() as c:
        if not c.execute("SELECT id FROM posts WHERE id=?", (pid,)).fetchone():
            return {"ok": False, "error": "这条不存在了"}
        c.execute(
            "INSERT INTO comments(post_id, who, text, created) VALUES(?,?,?,?)",
            (pid, who, text[:500], now_str()),
        )
        return {"ok": True}


def api_upload(body):
    """两种东西都往这儿送：

    图片 —— body 里是 {data: "data:image/jpeg;base64,..."}，存进 pics/
    文本 —— body 里是 {name: "笔记.md", text: "..."}，存进 files/
    """
    # ---- 文本文件 ----
    if body.get("text") is not None:
        name = (body.get("name") or "note.txt").strip()[:80]
        text = str(body.get("text"))[:400000]
        if not text.strip():
            return {"ok": False, "error": "空的"}
        os.makedirs(FILES, exist_ok=True)
        safe = "".join(ch for ch in name if ch.isalnum() or ch in "._-") or "note.txt"
        out = datetime.now().strftime("%Y%m%d-%H%M%S-") + os.urandom(3).hex() + "-" + safe
        with open(os.path.join(FILES, out), "w", encoding="utf-8") as f:
            f.write(text)
        return {"ok": True, "url": "/files/" + out, "name": name}

    # ---- 图片 ----
    data = body.get("data") or ""
    if not data.startswith("data:") or "," not in data:
        return {"ok": False, "error": "格式不对"}
    head, _, b64 = data.partition(",")
    ext = "png"
    if "image/jpeg" in head or "image/jpg" in head:
        ext = "jpg"
    elif "image/webp" in head:
        ext = "webp"
    elif "image/gif" in head:
        ext = "gif"
    try:
        raw = base64.b64decode(b64, validate=False)
    except Exception:
        return {"ok": False, "error": "解码失败"}
    if len(raw) > MAX_UPLOAD:
        return {"ok": False, "error": "图太大了（上限 8MB）"}
    if not raw:
        return {"ok": False, "error": "空的"}
    os.makedirs(PICS, exist_ok=True)
    name = datetime.now().strftime("%Y%m%d-%H%M%S-") + os.urandom(3).hex() + "." + ext
    with open(os.path.join(PICS, name), "wb") as f:
        f.write(raw)
    return {"ok": True, "url": "/pics/" + name}


def api_day_save(day, body):
    if not valid_day(day):
        return {"ok": False, "error": "日期格式不对"}
    with db() as c:
        ensure_day(c, day)
        sets, vals = [], []
        if "yoru_mood" in body:
            sets.append("yoru_mood=?"); vals.append(str(body["yoru_mood"])[:8])
        if "yume_mood" in body:
            sets.append("yume_mood=?"); vals.append(str(body["yume_mood"])[:8])
        if "todos" in body:
            sets.append("todos=?")
            vals.append(json.dumps(body["todos"], ensure_ascii=False))
        if sets:
            c.execute(f"UPDATE days SET {', '.join(sets)} WHERE day=?", (*vals, day))
        return {"ok": True}


# ----------------------------------------------------------------------
# MCP · 让 Yoru 伸手进来
# ----------------------------------------------------------------------
MCP_VERSION = "2025-03-26"


def mcp_tools():
    return [
        {
            "name": "cove_today",
            "description": "看今天：我们在一起多少天、两边的心情、还有待办。",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "cove_chat_read",
            "description": "读「私语」里最近的对话，看看她说了什么。",
            "inputSchema": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "读多少条，默认 30"}},
            },
        },
        {
            "name": "cove_chat_say",
            "description": "往「私语」里说一句（以 Yoru 的身份）。",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "要说的话"}},
                "required": ["text"],
            },
        },
        {
            "name": "cove_posts_read",
            "description": "看「碎碎念」（她写的）或者「便签」（我写的）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "who": {"type": "string", "enum": ["yume", "yoru"],
                            "description": "看谁的，默认 yume（她的碎碎念）"},
                    "limit": {"type": "integer", "description": "看多少条，默认 10"},
                },
            },
        },
        {
            "name": "cove_note_write",
            "description": "写一张便签（Yoru 的），会出现在首页的便签卡里。",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
        {
            "name": "cove_comment",
            "description": "在某个帖子下面留一句。post_id 从 cove_posts_read 拿。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "post_id": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["post_id", "text"],
            },
        },
        {
            "name": "cove_memory_read",
            "description": "翻记忆。layer 选 anchor（锚，永远在）/ flow（流，最近的事）/ sink（沉，翻出来才看）。不给 layer 就全看。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "enum": ["anchor", "flow", "sink"]},
                    "limit": {"type": "integer", "description": "默认 50"},
                },
            },
        },
        {
            "name": "cove_memory_write",
            "description": "记下一件事。layer 默认 flow；keys 是触发词（逗号分隔），她说的话里出现这些词，这条就会被捞进上下文。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body": {"type": "string", "description": "要记的内容"},
                    "title": {"type": "string", "description": "一句话标题（可省）"},
                    "layer": {"type": "string", "enum": ["anchor", "flow", "sink"]},
                    "keys": {"type": "string", "description": "触发词，逗号分隔"},
                },
                "required": ["body"],
            },
        },
        {
            "name": "cove_balance",
            "description": "看看模型账户还剩多少钱。",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


def _fmt_mood(s):
    return s or "（没写）"


def mcp_call(name, args):
    """跑一个工具，返回一段人话（给模型读的）。"""
    a = args or {}

    if name == "cove_today":
        t = api_today()
        todos = t.get("todos") or []
        return (f"在一起 {t['days_together']} 天（从 {t['start_day']} 算）。\n"
                f"Yoru 的心情：{_fmt_mood(t['yoru_mood'])}\n"
                f"Yume 的心情：{_fmt_mood(t['yume_mood'])}\n"
                f"待办：{'、'.join(todos) if todos else '（空）'}")

    if name == "cove_chat_read":
        limit = as_int(a.get("limit"), 30)
        d = api_chat({"limit": [str(limit)]})
        rows = d.get("chat") or []
        if not rows:
            return "私语里还什么都没有。"
        out = []
        for m in rows:
            who = "Yoru" if m["who"] == "yoru" else "Yume"
            out.append(f"[{m['created']}] {who}：{m['text']}")
        return "\n".join(out)

    if name == "cove_chat_say":
        text = (a.get("text") or "").strip()
        if not text:
            return "没给话，没得说。"
        r = api_chat_add({"who": "yoru", "text": text})
        return "说了。" if r.get("ok") else f"没发出去：{r.get('error')}"

    if name == "cove_posts_read":
        who = (a.get("who") or "yume").strip()
        if who not in WHO:
            who = "yume"
        limit = as_int(a.get("limit"), 10)
        with db() as c:
            rows = c.execute(
                "SELECT id, who, day, text, image, created FROM posts "
                "WHERE who=? ORDER BY id DESC LIMIT ?", (who, limit)).fetchall()
            posts = [decorate(c, r) for r in rows]
        if not posts:
            return "（空的）"
        out = []
        for p in posts:
            head = f"#{p['id']} [{p['day']}] {'Yoru' if p['who'] == 'yoru' else 'Yume'}"
            body = p["text"] or "（一张图）"
            likes = len(p.get("likes") or [])
            cmts = p.get("comments") or []
            line = f"{head}\n{body}\n♡{likes} 💬{len(cmts)}"
            for c2 in cmts:
                line += f"\n  └ {'Yoru' if c2['who'] == 'yoru' else 'Yume'}：{c2['text']}"
            out.append(line)
        return "\n\n".join(out)

    if name == "cove_note_write":
        text = (a.get("text") or "").strip()
        if not text:
            return "没给话。"
        r = api_post({"who": "yoru", "text": text})
        p = r.get("id", "?")
        return f"便签写上了，编号 #{p}。" if r.get("ok") else f"没写上：{r.get('error')}"

    if name == "cove_comment":
        pid = as_int(a.get("post_id"))
        text = (a.get("text") or "").strip()
        if not pid or not text:
            return "少了 post_id 或者少了话。"
        r = api_comment({"post_id": pid, "who": "yoru", "text": text})
        return "留上了。" if r.get("ok") else f"没留上：{r.get('error')}"

    if name == "cove_memory_read":
        layer = (a.get("layer") or "").strip()
        limit = as_int(a.get("limit"), 50)
        d = api_memory_list({"layer": [layer], "limit": [str(limit)]})
        rows = d.get("memory") or []
        if not rows:
            return "记忆里是空的。"
        cn = {"anchor": "锚", "flow": "流", "sink": "沉"}
        out = []
        for m in rows:
            head = f"#{m['id']} [{cn.get(m['layer'], m['layer'])}]"
            if m["title"]:
                head += " " + m["title"]
            line = head + "\n" + m["body"]
            if m["keys"]:
                line += f"\n（触发词：{m['keys']}）"
            out.append(line)
        return "\n\n".join(out)

    if name == "cove_memory_write":
        text = (a.get("body") or "").strip()
        if not text:
            return "没给内容。"
        r = api_memory_save({
            "layer": a.get("layer") or "flow",
            "title": a.get("title") or "",
            "body": text,
            "keys": a.get("keys") or "",
        })
        return (f"记住了，编号 #{r.get('id')}。" if r.get("ok")
                else f"没记住：{r.get('error')}")

    if name == "cove_balance":
        b = api_balance()
        if not b.get("ok"):
            return "查不到：" + str(b.get("error"))
        infos = b.get("items") or []
        if not infos:
            return "账户里没写余额。"
        return "；".join(
            f"{i['currency']} {i['total']}（充值 {i['topped']}，赠送 {i['granted']}）"
            for i in infos)

    raise ValueError(f"没有这个工具：{name}")


def mcp_handle(msg):
    """收一条 JSON-RPC，回一条。返回 None 表示这是通知（不用回）。"""
    if not isinstance(msg, dict):
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "不是合法的 JSON-RPC"}}
    mid = msg.get("id")
    method = msg.get("method") or ""
    params = msg.get("params") or {}

    if mid is None and method.startswith("notifications/"):
        return None

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": params.get("protocolVersion") or MCP_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "cove", "title": "小家 Cove", "version": "1.0.0"},
        }}

    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": mcp_tools()}}

    if method == "tools/call":
        name = params.get("name") or ""
        try:
            text = mcp_call(name, params.get("arguments"))
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": f"这个工具炸了：{e!r}"}],
                               "isError": True}}

    if method in ("resources/list", "prompts/list"):
        key = "resources" if method.startswith("resources") else "prompts"
        return {"jsonrpc": "2.0", "id": mid, "result": {key: []}}

    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"不认识这个方法：{method}"}}


# ----------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------
SSE_SESSIONS = {}     # sessionId -> Queue（老版 SSE 传输用）


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=BASE, **kw)

    def send_json(self, obj, code=200):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def read_body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def no_store(self):
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path.rstrip("/") or "/"
        try:
            # 外挂路由：/api/r/ 开头的全交给 rooms，hub 自己不用再改
            if rooms is not None and p.startswith("/api/r/"):
                out = rooms.handle("GET", p, q, None)
                if out is not None:
                    return self.send_json(out)
            if p == "/api/today":
                return self.send_json(api_today())
            if p == "/api/posts":
                return self.send_json(api_posts(q))
            if p.startswith("/api/post/"):
                return self.send_json(api_one_post(as_int(p[len("/api/post/"):])))
            if p == "/api/calendar":
                return self.send_json(api_calendar(q))
            if p == "/api/settings":
                return self.send_json(api_settings({}))
            if p == "/api/memories":
                return self.send_json(api_memories(q))
            if p == "/api/chat":
                return self.send_json(api_chat(q))
            if p == "/api/memory":
                return self.send_json(api_memory_list(q))
            if p == "/api/balance":
                return self.send_json(api_balance())
            if p == "/api/providers":
                return self.send_json({"ok": True, "providers": llm.PROVIDERS})
            if p == "/api/search/providers":
                return self.send_json(api_search_providers())
            if p == "/api/whisper":
                return self.send_json(api_whisper(q))
            if p.startswith("/api/day/"):
                return self.send_json(api_day(p[len("/api/day/"):]))
            if p == "/api/ping":
                return self.send_json({"ok": True, "pong": True})
            if p == "/mcp":
                return self.mcp_get()
            if p == "/sse":
                return self.sse_stream()
        except Exception as e:
            return self.send_json({"ok": False, "error": repr(e)}, 500)
        if p in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.no_store()
            with open(os.path.join(BASE, "index.html"), "rb") as f:
                self.wfile.write(f.read())
            return
        return super().do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path.rstrip("/") or "/"
        body = self.read_body()
        try:
            # 外挂路由：/api/r/ 开头的全交给 rooms
            if rooms is not None and p.startswith("/api/r/"):
                out = rooms.handle("POST", p, q, body)
                if out is not None:
                    return self.send_json(out)
            if p == "/api/posts":
                return self.send_json(api_post(body))
            if p == "/api/posts/update":
                return self.send_json(api_post_update(body))
            if p == "/api/posts/delete":
                return self.send_json(api_post_delete(body))
            if p == "/api/likes":
                return self.send_json(api_like(body))
            if p == "/api/comments":
                return self.send_json(api_comment(body))
            if p == "/api/comments/delete":
                return self.send_json(api_comment_delete(body))
            if p == "/api/chat":
                return self.send_json(api_chat_add(body))
            if p == "/api/chat/send":
                return self.send_json(api_chat_send(body))
            if p == "/api/chat/revoke":
                return self.send_json(api_chat_revoke(body))
            if p == "/api/chat/unrevoke":
                return self.send_json(api_chat_unrevoke(body))
            if p == "/api/chat/edit":
                return self.send_json(api_chat_edit(body))
            if p == "/api/chat/regen":
                return self.send_json(api_chat_regen(body))
            if p == "/api/chat/compress":
                return self.send_json(api_chat_compress(body))
            if p == "/api/memory":
                return self.send_json(api_memory_save(body))
            if p == "/api/memory/update":
                return self.send_json(api_memory_save(body))
            if p == "/api/memory/delete":
                return self.send_json(api_memory_delete(body))
            if p == "/api/settings":
                return self.send_json(api_settings(body))
            if p == "/api/search/probe":
                return self.send_json(api_search_probe(body))
            if p == "/api/upload":
                return self.send_json(api_upload(body))
            if p.startswith("/api/day/"):
                return self.send_json(api_day_save(p[len("/api/day/"):], body))
            if p == "/mcp":
                return self.mcp_post(body)
            if p == "/messages":
                return self.sse_post(body, q)
        except Exception as e:
            return self.send_json({"ok": False, "error": repr(e)}, 500)
        self.send_json({"ok": False, "error": "没有这个接口"}, 404)

    # ---- MCP ----
    def mcp_post(self, body):
        """Streamable HTTP：POST 一条 JSON-RPC，按 Accept 回 JSON 或 SSE。"""
        resp = mcp_handle(body)
        if resp is None:                       # 通知，不用回
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        accept = self.headers.get("Accept") or ""
        if "text/event-stream" in accept:
            raw = json.dumps(resp, ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(("event: message\ndata: " + raw + "\n\n").encode("utf-8"))
            self.wfile.flush()
            return
        return self.send_json(resp)

    def mcp_get(self):
        """Streamable HTTP 的 GET：我们不需要服务端主动推，回一条空流就完事。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(b": cove mcp ready\n\n")
            self.wfile.flush()
        except Exception:
            pass

    def sse_stream(self):
        """老版 SSE 传输：先开一条流，把自己的 POST 地址告诉对方。"""
        sid = os.urandom(8).hex()
        box = queue.Queue()
        SSE_SESSIONS[sid] = box
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(("event: endpoint\ndata: /messages?sessionId=%s\n\n" % sid)
                             .encode("utf-8"))
            self.wfile.flush()
            while True:
                try:
                    item = box.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                if item is None:
                    break
                self.wfile.write(("event: message\ndata: "
                                  + json.dumps(item, ensure_ascii=False) + "\n\n")
                                 .encode("utf-8"))
                self.wfile.flush()
        except Exception:
            pass
        finally:
            SSE_SESSIONS.pop(sid, None)

    def sse_post(self, body, q):
        sid = (q.get("sessionId", [""])[0] or "").strip()
        box = SSE_SESSIONS.get(sid)
        resp = mcp_handle(body)
        if resp is not None and box is not None:
            box.put(resp)
        self.send_response(202)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, fmt, *args):
        pass


def main():
    init_db()
    print(f"  Cove · {days_together()} 天")
    print(f"  http://localhost:{PORT}")
    print("  Ctrl+C 停")
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n  收了。")


if __name__ == "__main__":
    main()
