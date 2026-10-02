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
from datetime import date, datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "cove.db")
PICS = os.path.join(BASE, "pics")
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
    conn = sqlite3.connect(DB_PATH)
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
                created TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chat_who ON chat(who);
            """
        )
        if not has_col(c, "posts", "image"):
            c.execute("ALTER TABLE posts ADD COLUMN image TEXT NOT NULL DEFAULT ''")


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
                    set_setting(c, k, str(v)[:300])
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
    """私语：把说过的话读出来。"""
    limit = as_int((q.get("limit", ["60"])[0] or "60"), 60)
    limit = max(1, min(limit, 300))
    with db() as c:
        rows = c.execute(
            "SELECT id, who, text, created FROM chat ORDER BY id DESC LIMIT ?",
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
            (who, text[:1000], now_str()),
        )
        return {"ok": True, "id": cur.lastrowid}


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
    """把前端传来的 dataURL 存成文件，返回路径"""
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
            if p == "/api/settings":
                return self.send_json(api_settings(body))
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
