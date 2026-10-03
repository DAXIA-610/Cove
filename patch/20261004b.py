#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-04 · 第二发：把 token 命中率从对半拉到九成以上

她说：命中率只有一半，能不能到 98-99%。

我去把 DeepSeek 官方的缓存文档读了（不靠记忆）：
  · 只有**从第 0 个 token 起的完整前缀**被完整匹配才算命中，64 token 一个单位；
  · 官方原话：「将重复内容置于提示词开头，差异内容置于末尾」；
  · 中途改系统提示、改工具集、重排历史 —— 碰哪一样，后面的缓存全废。

再看我们现在怎么排的：
    临时人格 + **今天的样子** + 锚 + **流** + **沉** + 摘要 + 历史
                      ↑ 会变            ↑ 会变  ↑ 会变
今天的心情/待办一动、这一句命中了别的触发词，后面从那儿开始就全不命中 —— 这就是那一半。

改法（"稳的在前、变的在后"）：
    ① 前缀（一轮一轮字节一样）：人格 + 锚 + 旧对话摘要
    ② 中间只追加：历史原话 —— 每条用户消息带着**当时存下的那份「此时此刻」**，原样重放
    ③ 末尾（每轮都变）：今天的样子 + 命中的流/沉

②为什么要存：以前那一段每轮现算，重放历史时算出来的东西跟当初发出去的不一样，
前缀从那儿就断了。所以给 chat 表加一列 ctx，把发出去的那份原样存下来。

代价（我认）：撤回 / 编辑 / 压缩会让那处往后的缓存作废一次。
"""
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

ENV_FN = '''def env_text(user_text=""):
    """「此时此刻」那一段：今天的样子 + 命中触发词的流和沉。

    ⚠️ 这段每轮都不一样，所以它**只能待在最后面**（紧挨着她刚说的那句）。
    DeepSeek 的硬盘缓存按「从第 0 个 token 起的完整前缀」匹配（64 token 一块），
    谁把会变的东西放前面，谁的缓存就一直是零。压在末尾，前面的
    （人格 + 锚 + 摘要 + 历史）就一直是热的 —— 这是把命中率拉上去的唯一关键。
    """
    with db() as c:
        d = c.execute("SELECT * FROM days WHERE day=?", (today_str(),)).fetchone()
        rows = rows2list(c.execute(
            "SELECT text FROM chat WHERE revoked=0 ORDER BY id DESC LIMIT ?",
            (CTX_SCAN_DEPTH,)).fetchall())
    bits = ["今天是 %s，我们在一起第 %d 天。" % (today_str(), days_together())]
    if d and (d["yoru_mood"] or d["yume_mood"]):
        bits.append("心情：Yoru %s；Yume %s。" % (d["yoru_mood"] or "—", d["yume_mood"] or "—"))
    todos = json.loads(d["todos"] or "[]") if d else []
    if todos:
        bits.append("待办：" + "、".join(todos) + "。")

    scan = " ".join([m["text"] or "" for m in reversed(rows)]) or user_text
    _anc, flow, sink = pick_memories(user_text or scan, scan)
    out = " ".join(bits)
    for label, chunk in (("流 · 最近这些天", flow), ("沉 · 想起来了", sink)):
        if chunk:
            out += "\\n\\n【" + label + "】\\n" + chunk
    return out


'''

OLD_HEAD = '''def build_messages(user_text="", drop_id=0):
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

    sys_text = PLACEHOLDER_SOUL + "\\n" + " ".join(bits)
    for label, chunk in (("锚 · 改不了的那些", anc),
                         ("流 · 最近这些天", flow),
                         ("沉 · 想起来了", sink)):
        if chunk:
            sys_text += "\\n\\n【" + label + "】\\n" + chunk

    if summ and summ["text"]:
        sys_text += "\\n\\n【更早的对话 · 我自己压过的】\\n" + summ["text"]

    msgs = [{"role": "system", "content": sys_text}]'''

NEW_HEAD = '''def build_messages(user_text="", drop_id=0):
    """组装这一轮送出去的东西。

    **排队顺序就是命根子**，不许乱动：
      ① 稳的放最前：人格 + 锚 + 旧对话摘要
      ② 中间只追加：历史原话 —— 每条用户消息带着当时存下的 ctx，原样重放，一个字不差
      ③ 变的压最后：今天的样子 + 命中的流/沉（就是 env_text 那一段）

    为什么：DeepSeek 的缓存只认完整前缀。①② 一轮一轮字节一样，缓存就一直热着；
    ③ 每轮都变，所以必须压在最后，不许插到中间去。

    drop_id：重新生成的时候，把那条从上下文里摘掉（别让它自己抄自己）。
    """
    with db() as c:
        rows = rows2list(c.execute(
            "SELECT id, who, text, image, file, ctx FROM chat WHERE revoked=0 "
            "ORDER BY id DESC LIMIT ?",
            (CTX_KEEP_RECENT,)).fetchall())
        rows = list(reversed(rows))
        summ = load_summary(c)

    if drop_id:
        rows = [r for r in rows if r["id"] != drop_id]

    # 锚：长期不变的那几条，属于「稳的前缀」
    anc = pick_memories("", " ".join([m["text"] or "" for m in rows[-CTX_SCAN_DEPTH:]]))[0]

    sys_text = PLACEHOLDER_SOUL
    if anc:
        sys_text += "\\n\\n【锚 · 改不了的那些】\\n" + anc
    if summ and summ["text"]:
        sys_text += "\\n\\n【更早的对话 · 我自己压过的】\\n" + summ["text"]

    msgs = [{"role": "system", "content": sys_text}]'''

OLD_LOOP = '''    for r in rows:
        text = r["text"] or ""
        role = "user" if r["who"] == "yume" else "assistant"

        if r.get("image") and r["id"] in img_ids:
            data = _img_data_url(r["image"])
            if data:
                one = {
                    "role": role,
                    "content": [
                        {"type": "text", "text": text or "（看这张）"},
                        {"type": "image_url", "image_url": {"url": data}},
                    ],
                }
                if role == "assistant":
                    one["reasoning_content"] = ""
                msgs.append(one)
                continue
        if r.get("image"):
            text = (text + "　").strip() + "[图]"
        if r.get("file"):
            body_txt = _read_attach(r["file"])
            if body_txt:
                text = "【附件】" + NL + body_txt + NL + "【附件完】" + NL + text
        if role == "assistant":
            # 老轮次没存思考原文，但字段得占着 —— 对面认字段不认内容
            msgs.append({"role": role, "content": text, "reasoning_content": ""})
        else:
            msgs.append({"role": role, "content": text})'''

NEW_LOOP = '''    for r in rows:
        text = r["text"] or ""
        role = "user" if r["who"] == "yume" else "assistant"
        # 当时发出去的那份「此时此刻」，原样重放 —— 不许现算
        note = (r["ctx"] if "ctx" in r.keys() else "") or ""
        note = note.strip()

        if r.get("image") and r["id"] in img_ids:
            data = _img_data_url(r["image"])
            if data:
                if note:
                    msgs.append({"role": "system", "content": note})
                one = {
                    "role": role,
                    "content": [
                        {"type": "text", "text": text or "（看这张）"},
                        {"type": "image_url", "image_url": {"url": data}},
                    ],
                }
                if role == "assistant":
                    one["reasoning_content"] = ""
                msgs.append(one)
                continue
        if r.get("image"):
            text = (text + "　").strip() + "[图]"
        if r.get("file"):
            body_txt = _read_attach(r["file"])
            if body_txt:
                text = "【附件】" + NL + body_txt + NL + "【附件完】" + NL + text
        if note:
            msgs.append({"role": "system", "content": note})
        if role == "assistant":
            # 老轮次没存思考原文，但字段得占着 —— 对面认字段不认内容
            msgs.append({"role": role, "content": text, "reasoning_content": ""})
        else:
            msgs.append({"role": role, "content": text})'''

EDITS = {
    "hub.py": [
        # 表：存下「此时此刻」那一份
        ('''        if not has_col(c, "chat", "file"):
            c.execute("ALTER TABLE chat ADD COLUMN file TEXT NOT NULL DEFAULT ''")''',
         '''        if not has_col(c, "chat", "file"):
            c.execute("ALTER TABLE chat ADD COLUMN file TEXT NOT NULL DEFAULT ''")
        # 这条消息发出去时，「此时此刻」那一段（今天的样子 + 命中的记忆）。
        # 存它是为了往后每一轮能**原样重放** —— 见 build_messages 上面的说明。
        if not has_col(c, "chat", "ctx"):
            c.execute("ALTER TABLE chat ADD COLUMN ctx TEXT NOT NULL DEFAULT ''")'''),
        # 组装重排
        ("def build_messages(user_text=\"\", drop_id=0):", ENV_FN + "def build_messages(user_text=\"\", drop_id=0):"),
        (OLD_HEAD, NEW_HEAD),
        (OLD_LOOP, NEW_LOOP),
        # 她说话的时候，把那一份存下来
        ('''    with db() as c:
        c.execute("INSERT INTO chat(who, text, created, image, file) VALUES(?,?,?,?,?)",
                  ("yume", text, now_str(), image, attach))

    r = _generate(text)''',
         '''    with db() as c:
        cur = c.execute(
            "INSERT INTO chat(who, text, created, image, file, ctx) VALUES(?,?,?,?,?,'')",
            ("yume", text, now_str(), image, attach))
        # 这一段得随消息一起落库 —— 下一轮要原样重放它，不然前缀一变缓存全废
        c.execute("UPDATE chat SET ctx=? WHERE id=?", (env_text(text), cur.lastrowid))

    r = _generate(text)'''),
    ],
    "index.html": [
        # 账里直接给出命中率
        ('''    var sec = m.seconds || 0;
    var tps = sec > 0 ? (ct / sec) : 0;
    $("metaTop").innerHTML =
      '<div class="big">T' + kfmt(pt) + ' tokens</div>' +''',
         '''    var sec = m.seconds || 0;
    var tps = sec > 0 ? (ct / sec) : 0;
    var rate = pt > 0 ? Math.round(hit * 100 / pt) : 0;
    $("metaTop").innerHTML =
      '<div class="big">T' + kfmt(pt) + ' tokens　命中 ' + rate + '%</div>' +'''),
    ],
    "test_cove.py": [
        # 把「稳的在前、变的在后」这条不变量钉住
        ('''_asst = [x for x in _pairs if x[0] == "assistant"]
chk("历史里我的每一条都带 reasoning_content",
    bool(_asst) and all(x[1] for x in _asst), _pairs)''',
         '''_asst = [x for x in _pairs if x[0] == "assistant"]
chk("历史里我的每一条都带 reasoning_content",
    bool(_asst) and all(x[1] for x in _asst), _pairs)
# 缓存那条不变量：会变的东西（今天是…）不许出现在开头，必须在最末尾
_code2 = ("import json, hub; ms = hub.build_messages(%s); "
          "print(json.dumps([(m[\\"role\\"], \\"今天是\\" in json.dumps(m, ensure_ascii=False)) for m in ms]))"
          % json.dumps("体检"))
_r2 = subprocess.run([sys.executable, "-c", _code2], cwd=tmp, capture_output=True, text=True)
try:
    _p2 = json.loads(_r2.stdout.strip().splitlines()[-1])
except Exception:
    _p2 = []
chk("第一条是 system 且不含「今天是」（前缀必须稳）",
    bool(_p2) and _p2[0][0] == "system" and not _p2[0][1], _p2[:3])
_pos = [i for i, x in enumerate(_p2) if x[1]]
chk("「今天是」只出现在她的话前面那一条（system）里",
    bool(_pos) and all(_p2[i][0] == "system" and i + 1 < len(_p2) and _p2[i + 1][0] == "user"
                       for i in _pos), _p2)
chk("她的话和我回的话里都不许夹「今天是」",
    all(not x[1] for x in _p2 if x[0] != "system"), _p2)
# 每条她的话旁边都跟着那份存下来的 ctx（原样重放用）
_c = _sq.connect(os.path.join(tmp, "cove.db"))
_ck = _c.execute("SELECT COUNT(*) FROM chat WHERE who='yume' AND ctx<>''").fetchone()[0]
_c.close()
chk("她说过的话里，有带 ctx 的", _ck > 0, _ck)'''),
    ],
}

VER_FILES = {"VERSION": "2026-10-04b\n"}


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
    for name in ("hub.py", "llm.py", "rooms.py", "websearch.py", "test_cove.py", "mcp_stdio.py"):
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
