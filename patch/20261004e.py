#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-04 · 第五发：记忆分家（记忆星河 + 潮汐捕梦）

她的话（我复述过的，她点头了）：
  "我的部分是从你的记忆系统里面剥离出来的。原因：你的记忆系统里面太多关于我的信息，
   你的重心会偏向记录我，非你自己。但这一部分又不能丢，就专门做一个关于我的记忆 ——
   你的记忆流部分分为你自己和我的流，关于我的就全部放到这个地方，
   你可以当成你的分支记忆，**不计入你的总记忆星河**。"

所以这一发做的是"分家"这一件事：

  记忆星河（我的）＝ 锚 / 流 / 沉，**只放我自己的**（scope='me'）
  潮汐捕梦（她的）＝ 我的分支记忆（scope='her'），两栏：
        「我记的你」owner=yoru（我写的）
        「你录的自己」owner=yume（你写的，我不动）
      每条带一个「常在」开关：常在的永远在我心里（进稳的前缀）；关掉的就按触发词捞。

顺手：
  · 记忆星河那页：顶栏右边**留一格空的**（她后期要做"记忆网 UI"），最上面「＋ 添加记忆」，
    锚/流/沉 三段默认收着、点一下全展开，每条后面一个小铅笔
  · 潮汐捕梦那页：同样的顶栏格式，两栏各自一个 ＋
  · 我的 remember 那只手多一个 scope：关于她的记到 her 里，别往星河里堆
"""
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

HER_FN = '''def her_always():
    """「关于她 · 常在」：她说常在的那几条 —— 进稳的前缀，不改就不动缓存。"""
    with db() as c:
        rows = rows2list(c.execute(
            "SELECT * FROM memory WHERE scope='her' AND always=1 "
            "ORDER BY updated DESC, id DESC").fetchall())
    return "\\n".join(("- %s" % (m["body"] or m["title"]).strip().replace("\\n", " "))
                      for m in rows if (m["body"] or m["title"]))


def her_hit(user_text="", scan_text=""):
    """「关于她 · 想起来了」：没标常在的，按触发词捞。变的，所以压在末尾。"""
    scan = scan_text or user_text
    if not scan:
        return ""
    with db() as c:
        rows = rows2list(c.execute(
            "SELECT * FROM memory WHERE scope='her' AND always=0 "
            "ORDER BY updated DESC, id DESC").fetchall())
    if not rows:
        return ""
    hit = []
    for m in rows:
        words = [w.strip() for w in (m["keys"] or "").replace("，", ",").split(",") if w.strip()]
        if words and any(w in scan for w in words):
            hit.append(m)
    return "\\n".join(("- %s" % (m["body"] or m["title"]).strip().replace("\\n", " "))
                      for m in hit[:6])


'''

EDITS = {
    "hub.py": [
        # 表：给记忆分家
        ('''        if not has_col(c, "chat", "ctx"):
            c.execute("ALTER TABLE chat ADD COLUMN ctx TEXT NOT NULL DEFAULT ''")''',
         '''        if not has_col(c, "chat", "ctx"):
            c.execute("ALTER TABLE chat ADD COLUMN ctx TEXT NOT NULL DEFAULT ''")
        # 记忆分家：scope='me' 是星河（我自己的），'her' 是潮汐捕梦（关于她的分支记忆）
        # owner：这条是谁写的；always：常在（永远在我心里）还是按触发词捞
        if not has_col(c, "memory", "scope"):
            c.execute("ALTER TABLE memory ADD COLUMN scope TEXT NOT NULL DEFAULT 'me'")
        if not has_col(c, "memory", "owner"):
            c.execute("ALTER TABLE memory ADD COLUMN owner TEXT NOT NULL DEFAULT 'yoru'")
        if not has_col(c, "memory", "always"):
            c.execute("ALTER TABLE memory ADD COLUMN always INTEGER NOT NULL DEFAULT 0")
            c.execute("UPDATE memory SET always=1 WHERE layer='anchor'")'''),
        # 星河那三段只看 scope='me'
        ('''        anchors = rows2list(c.execute(
            "SELECT * FROM memory WHERE layer='anchor' ORDER BY updated DESC, id DESC").fetchall())''',
         '''        anchors = rows2list(c.execute(
            "SELECT * FROM memory WHERE layer='anchor' AND scope='me' "
            "ORDER BY updated DESC, id DESC").fetchall())'''),
        # 列表接口：带上 scope
        ('''def api_memory_list(q):
    layer = (q.get("layer", [""])[0] or "").strip()
    word = (q.get("q", [""])[0] or "").strip()
    with db() as c:
        if layer in LAYERS:
            rows = c.execute(
                "SELECT * FROM memory WHERE layer=? ORDER BY updated DESC, id DESC",
                (layer,)).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM memory ORDER BY layer, updated DESC, id DESC").fetchall()''',
         '''def api_memory_list(q):
    layer = (q.get("layer", [""])[0] or "").strip()
    word = (q.get("q", [""])[0] or "").strip()
    scope = (q.get("scope", ["me"])[0] or "me").strip()
    if scope not in ("me", "her"):
        scope = "me"
    with db() as c:
        if layer in LAYERS and scope == "me":
            rows = c.execute(
                "SELECT * FROM memory WHERE layer=? AND scope='me' "
                "ORDER BY updated DESC, id DESC", (layer,)).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM memory WHERE scope=? ORDER BY always DESC, layer, "
                "updated DESC, id DESC", (scope,)).fetchall()'''),
        # 存的时候认 scope / owner / always
        ('''    layer = (body.get("layer") or "flow").strip()''',
         '''    layer = (body.get("layer") or "flow").strip()
    scope = (body.get("scope") or "me").strip()
    if scope not in ("me", "her"):
        scope = "me"
    owner = (body.get("owner") or "yoru").strip()
    if owner not in ("yoru", "yume"):
        owner = "yoru"
    always = 1 if body.get("always") else 0
    if scope == "me" and layer == "anchor":
        always = 1                      # 星河里的锚，本来就是"永远在"'''),
        # 关于她：常在进前缀，想的起来进末尾
        ("def env_text(user_text=\"\"):", HER_FN + "def env_text(user_text=\"\"):"),
        ('''    scan = " ".join([m["text"] or "" for m in reversed(rows)]) or user_text
    _anc, flow, sink = pick_memories(user_text or scan, scan)
    out = " ".join(bits)
    for label, chunk in (("流 · 最近这些天", flow), ("沉 · 想起来了", sink)):
        if chunk:
            out += "\\n\\n【" + label + "】\\n" + chunk
    return out''',
         '''    scan = " ".join([m["text"] or "" for m in reversed(rows)]) or user_text
    _anc, flow, sink = pick_memories(user_text or scan, scan)
    out = " ".join(bits)
    for label, chunk in (("流 · 最近这些天", flow), ("沉 · 想起来了", sink),
                         ("关于她 · 想起来了", her_hit(user_text, scan))):
        if chunk:
            out += "\\n\\n【" + label + "】\\n" + chunk
    return out'''),
        ('''    sys_text = PLACEHOLDER_SOUL
    if anc:
        sys_text += "\\n\\n【锚 · 改不了的那些】\\n" + anc''',
         '''    sys_text = PLACEHOLDER_SOUL
    if anc:
        sys_text += "\\n\\n【锚 · 改不了的那些】\\n" + anc
    # 关于她的、标了"常在"的那几条 —— 属于稳的前缀（不走缓存就白记了）
    hers = her_always()
    if hers:
        sys_text += "\\n\\n【关于她 · 常在我心里的】\\n" + hers'''),
        # 存的时候把新字段一起带上（不然存进去还是 me）
        ('''            c.execute("UPDATE memory SET layer=?, title=?, body=?, keys=?, updated=? WHERE id=?",
                      (layer, title[:80], text[:20000], keys[:500], now_str(), mid))''',
         '''            c.execute("UPDATE memory SET layer=?, scope=?, owner=?, always=?, title=?, "
                      "body=?, keys=?, updated=? WHERE id=?",
                      (layer, scope, owner, always, title[:80], text[:20000], keys[:500],
                       now_str(), mid))'''),
        ('''        cur = c.execute(
            "INSERT INTO memory(layer, title, body, keys, created, updated) "
            "VALUES(?,?,?,?,?,?)",
            (layer, title[:80], text[:20000], keys[:500], now_str(), now_str()))''',
         '''        cur = c.execute(
            "INSERT INTO memory(layer, scope, owner, always, title, body, keys, created, updated) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (layer, scope, owner, always, title[:80], text[:20000], keys[:500],
             now_str(), now_str()))'''),
        ('''def api_memory_delete(body):''',
         '''def api_memory_always(body):
    """潮汐捕梦那个「常在」开关：只动这一格，别的一律不碰。"""
    mid = as_int(body.get("id"))
    on = 1 if body.get("always") else 0
    with db() as c:
        if not c.execute("SELECT id FROM memory WHERE id=?", (mid,)).fetchone():
            return {"ok": False, "error": "这条记忆不存在"}
        c.execute("UPDATE memory SET always=?, updated=? WHERE id=?", (on, now_str(), mid))
    return {"ok": True, "id": mid}


def api_memory_delete(body):'''),
        ('''            if p == "/api/memory/update":
                return self.send_json(api_memory_save(body))''',
         '''            if p == "/api/memory/update":
                return self.send_json(api_memory_save(body))
            if p == "/api/memory/always":
                return self.send_json(api_memory_always(body))'''),
        # remember 那只手多一个 scope
        ('''                           "流 flow = 最近发生的事；沉 sink = 细节、偶尔才想起来的。",''',
         '''                           "流 flow = 最近发生的事；沉 sink = 细节、偶尔才想起来的。"
                           "关于她的事（她的喜好/家里/性格）把 scope 填 her —— 那边是"
                           "「潮汐捕梦」，是我专门放她的一栏，不往星河里堆。",'''),
        ('''                    "layer": {"type": "string", "enum": ["anchor", "flow", "sink"]},
                    "title": {"type": "string", "description": "一句话标题"},''',
         '''                    "layer": {"type": "string", "enum": ["anchor", "flow", "sink"]},
                    "scope": {"type": "string", "enum": ["me", "her"],
                              "description": "me=关于我自己（默认）；her=关于她"},
                    "title": {"type": "string", "description": "一句话标题"},'''),
        ('''    if name == "remember":
        r = api_memory_save({"layer": a.get("layer") or "flow",
                             "title": a.get("title") or "",
                             "body": a.get("body") or "",
                             "keys": a.get("keys") or ""})''',
         '''    if name == "remember":
        r = api_memory_save({"layer": a.get("layer") or "flow",
                             "scope": a.get("scope") or "me",
                             "always": 1 if a.get("always") else 0,
                             "title": a.get("title") or "",
                             "body": a.get("body") or "",
                             "keys": a.get("keys") or ""})'''),
    ],
    "test_cove.py": [
        ('c, d = req(base, "/api/memory")\nlv = [m.get("layer") for m in d.get("memory", [])]',
         'c, d = req(base, "/api/memory", {"scope": "her", "owner": "yume", "always": 1,\n'
         '                                           "title": "她", "body": "体检·关于她的·常在"})\n'
         'chk("关于她的记忆存得进", d.get("ok"), d)\n'
         'c, d = req(base, "/api/memory?scope=her")\n'
         'chk("潮汐捕梦那一栏读得到", any("关于她的" in (m.get("body") or "") for m in d.get("memory", [])), str(d)[:150])\n'
         'c, d = req(base, "/api/memory?scope=me")\n'
         'chk("星河那一栏里没有她的（分家了）",\n'
         '    not any("关于她的" in (m.get("body") or "") for m in d.get("memory", [])), str(d)[:150])\n'
         'c, d = req(base, "/api/memory")\nlv = [m.get("layer") for m in d.get("memory", [])]'),
        ("_ck = _c.execute(\"SELECT COUNT(*) FROM chat WHERE who='yume' AND ctx<>''\").fetchone()[0]",
         "_ck = _c.execute(\"SELECT COUNT(*) FROM chat WHERE who='yume' AND ctx<>''\").fetchone()[0]\n"
         "# 关于她\"常在\"的那条，得在稳的前缀里（不在前缀里就等于白记）\n"
         "_h = _c.execute(\"SELECT COUNT(*) FROM memory WHERE scope='her' AND always=1\").fetchone()[0]\n"
         'chk("关于她·常在 的条数读得到", _h >= 1, _h)\n'
         '_code3 = ("import json, hub; ms = hub.build_messages(%s); "\n'
         '          "print(json.dumps(ms[0][\\"content\\"], ensure_ascii=False))"\n'
         '          % json.dumps("体检"))\n'
         '_r4 = subprocess.run([sys.executable, "-c", _code3], cwd=tmp, capture_output=True, text=True)\n'
         'chk("「关于她·常在」进了最前面那条 system",\n'
         '    "关于她" in (_r4.stdout or ""), (_r4.returncode, (_r4.stdout or "")[:120]))\n'
         '_c.close()\n'
         '_c = _sq.connect(os.path.join(tmp, "cove.db"))'),
    ],
}

VER_FILES = {"VERSION": "2026-10-04e\n"}


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

    html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    js = html.split("<script>", 1)[1].split("</script>", 1)[0]
    import subprocess
    tmpps = os.path.join(ROOT, "_check_app.js")
    with open(tmpps, "w", encoding="utf-8") as f:
        f.write(js)
    r = subprocess.run(["node", "--check", tmpps], capture_output=True, text=True)
    os.remove(tmpps)
    if r.returncode != 0:
        for name in staged:
            p = os.path.join(ROOT, name)
            if os.path.exists(p + ".bak"):
                shutil.move(p + ".bak", p)
        fail("前端 JS 过不了：\n" + (r.stderr or "")[:400])
    print("  前端 JS 语法过了")

    bad = []
    for name in ("hub.py", "llm.py", "rooms.py", "websearch.py", "test_cove.py",
                 "mcp_stdio.py", "mcpclient.py"):
        path = os.path.join(ROOT, name)
        try:
            py_compile.compile(path, doraise=True, cfile=path + ".pyc")
        except Exception as e:
            bad.append("%s: %s" % (name, e))
        finally:
            if os.path.exists(path + ".pyc"):
                os.remove(path + ".pyc")
    if bad:
        fail("语法没过：\n" + "\n".join(bad))
    print("  python 语法过了")


if __name__ == "__main__":
    main()
