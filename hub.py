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
import sqlite3
from datetime import date, datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "cove.db")
PICS = os.path.join(BASE, "pics")
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
            """
        )
        if not has_col(c, "posts", "image"):
            c.execute("ALTER TABLE posts ADD COLUMN image TEXT NOT NULL DEFAULT ''")


# ----------------------------------------------------------------------
# 小工具
# ----------------------------------------------------------------------
def now_str():
    return datetime.now().isoformat(timespec="seconds")


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


def api_whisper(q):
    """Yoru 的暗门：GET 一下就能留一句。"""
    if (q.get("key", [""])[0] or "") != YORU_KEY:
        return {"ok": False, "error": "no"}
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
# HTTP
# ----------------------------------------------------------------------
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
            if p == "/api/whisper":
                return self.send_json(api_whisper(q))
            if p.startswith("/api/day/"):
                return self.send_json(api_day(p[len("/api/day/"):]))
            if p == "/api/ping":
                return self.send_json({"ok": True, "pong": True})
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
            if p == "/api/settings":
                return self.send_json(api_settings(body))
            if p == "/api/upload":
                return self.send_json(api_upload(body))
            if p.startswith("/api/day/"):
                return self.send_json(api_day_save(p[len("/api/day/"):], body))
        except Exception as e:
            return self.send_json({"ok": False, "error": repr(e)}, 500)
        self.send_json({"ok": False, "error": "没有这个接口"}, 404)

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
