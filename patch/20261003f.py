#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-03 · 第六发：日记

她说：把日记部分搓好，前端要有个"文件夹"，她写进去，只存，她要能真的用起来。

现在那页只是一排日期，能用但不像一本本子。这一发：
  · 顶上给它一张封面：多少篇、多少字、最近写的是哪天，还有那句"只存，我不读"
  · 按月分组（2026 年 10 月 · 3 篇），每篇一行：日期 + 星期 + 一句话 + 字数
  · 今天没写就第一行摆着"今天 · 还空着，点一下今天就有一页了"
  · 编辑页底下加一行：实时字数 + 「删掉这篇」（原来只有存，删不掉）
  · 日历上写过日记的日子，右上角点一个小点
  · 日历抽屉里那一行能直接点进那天的日记（上一发做的入口，这一发送到本子上）
"""
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

DIARY_DAYS = '''def diary_days(prefix=""):
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


'''

DIARY_CSS = '''  .dcover{margin:2px 0 16px;padding:20px 18px;border-radius:20px;
          background:linear-gradient(150deg,rgba(140,155,171,.30),rgba(154,168,143,.22));
          border:1px solid var(--line);}
  .dcover .dn{font-size:14px;letter-spacing:.3em;color:var(--ink);font-weight:600;}
  .dcover .ds{font-size:10.5px;color:var(--soft);margin-top:8px;line-height:1.75;
              letter-spacing:.02em;}
  .dcover .dt2{font-size:10.5px;color:var(--soft);margin-top:11px;letter-spacing:.1em;
               font-variant-numeric:tabular-nums;}
  .dmon{font-size:10.5px;letter-spacing:.18em;color:var(--soft);margin:16px 0 9px;}
  .ditem .day .wd{font-size:10.5px;opacity:.6;font-weight:400;letter-spacing:.06em;}
  .dfoot{display:flex;justify-content:space-between;align-items:center;
         padding:0 20px 90px;font-size:11px;color:var(--soft);letter-spacing:.06em;}
  .dfoot button{font-size:11px;color:var(--soft);letter-spacing:.06em;}

'''

DIARY_JS = '''var WD = ["日", "一", "二", "三", "四", "五", "六"];
function wdOf(day){
  try { return WD[new Date(day + "T00:00:00").getDay()]; } catch (e) { return ""; }
}

/* ─────────── 日记（只存，我不读） ─────────── */
var diaryDay = null;
var diaryListCache = [];

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
    var list = d.list || [];
    diaryListCache = list;
    var total = 0, months = {};
    list.forEach(function(it){
      total += (it.chars || 0);
      var m = it.day.slice(0, 7);
      months[m] = (months[m] || 0) + 1;
    });
    var hasToday = list.some(function(it){ return it.day === today; });
    var last = list.length ? list[0].day : "";

    var h = '<div class="dcover">' +
      '<div class="dn">我 的 日 记</div>' +
      '<div class="ds">只存，我不读。这句话写在 rooms.py 第一行。</div>' +
      '<div class="dt2">' + list.length + " 篇　" + total + " 字" +
      (last ? "　最近 " + last.slice(5) : "　还一篇都没有") + '</div></div>';

    h += '<div class="dlist">';
    if (!hasToday){
      h += '<div class="ditem" onclick="openDiary(\\'' + today + '\\')">' +
           '<div class="day">今天 <span class="wd">' + today.slice(5) +
           ' 星期' + wdOf(today) + '</span></div>' +
           '<div class="db">还空着。点一下，今天就有一页了。</div></div>';
    }
    var ym = "";
    list.forEach(function(it){
      var m = it.day.slice(0, 7);
      if (m !== ym){
        ym = m;
        h += '<div class="dmon">' + m.slice(0, 4) + " 年 " +
             parseInt(m.slice(5), 10) + " 月　" + months[m] + " 篇</div>";
      }
      h += '<div class="ditem" onclick="openDiary(\\'' + it.day + '\\')">' +
           '<div class="day">' + it.day.slice(5) +
           ' <span class="wd">星期' + wdOf(it.day) + (it.day === today ? "　今天" : "") +
           '</span></div>' +
           (it.brief ? '<div class="db">' + esc(it.brief) + '</div>' : '') +
           '<div class="dt">' + it.chars + " 字 · " + it.updated + '</div></div>';
    });
    h += '</div>';
    $("diaryList").innerHTML = h;
  });
}

function openDiary(day){
  diaryDay = day;
  $("diaryTitle").textContent = day.slice(0, 7) + " · " + day.slice(8) + " 日";
  $("diaryOk").style.display = "";
  $("diaryList").style.display = "none";
  $("diaryEdit").style.display = "";
  $("diaryText").value = "";
  diaryCount();
  get("/api/r/diary/" + day).then(function(d){
    if (d.ok) $("diaryText").value = d.text || "";
    diaryCount();
    try { $("diaryText").focus(); } catch (e) {}
  });
}

function diaryCount(){
  var el = $("diaryCount");
  if (el) el.textContent = ($("diaryText").value || "").length + " 字";
}

function diaryDel(){
  if (!diaryDay) return;
  showPop([
    {t: "删掉 " + diaryDay + " 这一页？", cls: "hd"},
    {t: "算了", f: closePop},
    {t: "删掉", cls: "warn", f: function(){
      closePop();
      post("/api/r/diary/delete", {day: diaryDay}).then(function(r){
        if (!r.ok){ toast(r.error || "删不掉"); return; }
        toast("删了");
        goDiary();
      });
    }}
  ], null, true);
}

'''

EDITS = {
    "rooms.py": [
        ("def diary_list(q):", DIARY_DAYS + "def diary_list(q):"),
    ],
    "hub.py": [
        ('''            days.setdefault(r["day"], 0)
        return {"ok": True, "year": y, "month": m, "marked": days}''',
         '''            days.setdefault(r["day"], 0)
    diary = []
    if rooms is not None and hasattr(rooms, "diary_days"):
        try:
            diary = rooms.diary_days("%04d-%02d-" % (y, m))
        except Exception:
            diary = []
    return {"ok": True, "year": y, "month": m, "marked": days, "diary": diary}'''),
    ],
    "index.html": [
        # 日记那些新样式
        ("  /* 日记 */\n  .ditem{", DIARY_CSS + "  /* 日记 */\n  .ditem{"),
        # 有日记的日子右上角点个小点
        ('''  .d.mark::after{content:"";position:absolute;bottom:8px;left:50%;margin-left:-1.5px;
                 width:3px;height:3px;border-radius:50%;background:currentColor;opacity:.5;}''',
         '''  .d.mark::after{content:"";position:absolute;bottom:8px;left:50%;margin-left:-1.5px;
                 width:3px;height:3px;border-radius:50%;background:currentColor;opacity:.5;}
  .d.dia::before{content:"";position:absolute;top:9px;right:9px;width:3px;height:3px;
                 border-radius:50%;background:var(--ink);opacity:.45;}'''),
        ('function loadCal(){\n  var mm = calM + 1;',
         'var diaryDays = [];\nfunction loadCal(){\n  var mm = calM + 1;'),
        ('    marks = (d && d.marked) || {};',
         '    marks = (d && d.marked) || {};\n    diaryDays = (d && d.diary) || [];'),
        ('    if (marks[k]) cls += " mark";\n    if (k === today) cls += " today";',
         '    if (marks[k]) cls += " mark";\n'
         '    if (diaryDays.indexOf(k) >= 0) cls += " dia";\n'
         '    if (k === today) cls += " today";'),
        # 编辑页：字数 + 删掉这篇
        ('''    <div class="scroll" id="diaryEdit" style="display:none">
      <textarea id="diaryText" placeholder="今天……" spellcheck="false"></textarea>
    </div>''',
         '''    <div class="scroll" id="diaryEdit" style="display:none">
      <textarea id="diaryText" placeholder="今天……" spellcheck="false" oninput="diaryCount()"></textarea>
      <div class="dfoot">
        <span id="diaryCount">0 字</span>
        <button onclick="diaryDel()">删掉这篇</button>
      </div>
    </div>'''),
        # 老的 goDiary / openDiary 换成新的本子
        ('''/* ─────────── 日记（只存，我不读） ─────────── */
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
      h += '<div class="ditem" onclick="openDiary(\\'' + today + '\\')">' +
           '<div class="day">今天 · ' + today.slice(5) + '</div>' +
           '<div class="db">写点什么</div></div>';
    }
    (d.list || []).forEach(function(it){
      h += '<div class="ditem" onclick="openDiary(\\'' + it.day + '\\')">' +
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
}''', DIARY_JS.rstrip("\n")),
    ],
    "test_cove.py": [
        ('chk("日历上有这一天", "2026-10-02" in json.dumps(d.get("marked", {})), d)',
         'chk("日历上有这一天", "2026-10-02" in json.dumps(d.get("marked", {})), d)\n'
         'chk("日历带着 diary 那份名单", isinstance(d.get("diary"), list), d.get("diary"))\n'
         'c, d = req(base, "/api/r/diary/save", {"day": "2026-10-02", "text": "体检·日记一页"})\n'
         'chk("日记存得进去", d.get("ok") and d.get("saved"), d)\n'
         'c, d = req(base, "/api/r/diary/2026-10-02")\n'
         'chk("日记读得回来", d.get("ok") and d.get("text") == "体检·日记一页", d)\n'
         'c, d = req(base, "/api/calendar?y=2026&m=10")\n'
         'chk("写过日记的日子会出现在名单里", "2026-10-02" in (d.get("diary") or []), d.get("diary"))\n'
         'c, d = req(base, "/api/r/diary")\n'
         'chk("日记列表里有那一篇", any(x.get("day") == "2026-10-02" for x in (d.get("list") or [])), d)\n'
         'c, d = req(base, "/api/r/diary/delete", {"day": "2026-10-02"})\n'
         'chk("日记删得掉", d.get("ok"), d)\n'
         'c, d = req(base, "/api/r/day/2026-10-02")\n'
         'chk("那天里带着那天的记忆", isinstance(d.get("memories"), list), str(d)[:120])'),
    ],
}

VER_FILES = {"VERSION": "2026-10-03f\n"}


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
    for name in ("hub.py", "llm.py", "rooms.py", "websearch.py", "test_cove.py"):
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
