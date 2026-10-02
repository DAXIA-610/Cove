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


SETTING_KEYS = (
    "theme", "wallpaper", "wallpaper_img",
    "name_yoru", "name_yume", "avatar_yoru", "avatar_yume",
    "mood_yoru", "mood_yume",
)


# ----------------------------------------------------------------------
# 业务
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
        out["theme"] = out["theme"] or "sea"
        out["wallpaper"] = out["wallpaper"] or "sea"
        return out


def api_posts(q):
    who = (q.get("who", [""])[0] or "").strip()
    limit = int((q.get("limit", ["20"])[0] or "20"))
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
        return {"ok": True, "posts": rows2list(rows)}


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
        c.execute(
            "INSERT INTO posts(who, day, text, image, created) VALUES(?,?,?,?,?)",
            (who, day, text, image, datetime.now().isoformat(timespec="seconds")),
        )
        return {"ok": True, "id": c.execute("SELECT last_insert_rowid()").fetchone()[0]}


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


def api_calendar(q):
    y = int((q.get("y", [date.today().year])[0]))
    m = int((q.get("m", [date.today().month])[0]))
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


def api_settings(body):
    with db() as c:
        if body:
            for k, v in body.items():
                if k in SETTING_KEYS:
                    set_setting(c, k, str(v)[:300])
        return {"ok": True, "settings": {k: get_setting(c, k) for k in SETTING_KEYS}}


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


def api_memories(q):
    day = (q.get("day", [""])[0] or "").strip()
    return {"ok": True, "day": day, "items": []}


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

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path.rstrip("/") or "/"
        try:
            if p == "/api/today":
                return self.send_json(api_today())
            if p == "/api/posts":
                return self.send_json(api_posts(q))
            if p == "/api/calendar":
                return self.send_json(api_calendar(q))
            if p == "/api/settings":
                return self.send_json(api_settings({}))
            if p == "/api/memories":
                return self.send_json(api_memories(q))
            if p.startswith("/api/day/"):
                return self.send_json(api_day(p[len("/api/day/"):]))
            if p == "/api/ping":
                return self.send_json({"ok": True, "pong": True})
        except Exception as e:
            return self.send_json({"ok": False, "error": repr(e)}, 500)
        return super().do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        p = u.path.rstrip("/") or "/"
        body = self.read_body()
        try:
            if p == "/api/posts":
                return self.send_json(api_post(body))
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
