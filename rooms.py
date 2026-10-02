#!/usr/bin/env python3
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


def diary_days(prefix=""):
    """有哪几天写了日记。日历上点小点用的。"""
    os.makedirs(DIARY, exist_ok=True)
    out = []
    for name in os.listdir(DIARY):
        if not name.endswith(".md"):
            continue
        day = name[:-3]
        if not DAY_RE.match(day):
            continue
        if prefix and not day.startswith(prefix):
            continue
        try:
            if os.path.getsize(os.path.join(DIARY, name)) == 0:
                continue
        except OSError:
            continue
        out.append(day)
    return sorted(out)


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
