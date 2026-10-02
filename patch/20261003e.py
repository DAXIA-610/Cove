#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-03 · 第五发：日历

她说：
  · 日历上的数字太透明，看不清，可以用 𝓐𝓑𝓒 那种美化一下
  · 点某一天，从上到下：回忆当天（那天的聊天，只读，不能发）→ 记忆星河里我当天的几条
    → 碎碎念和便签（收着，点开才看全）

数字那件我去查了字体本身：digits.woff2 是 UnifrakturMaguntia，**0-9 十个数字一个不少**，
所以整张月历都能用那套花体数字，不会有空心方块。透明度 .62 → .95，字号 13 → 16。
"""
import os
import py_compile
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

EDITS = {
    "index.html": [
        # 数字：看得清 + 花体
        ('''  .d{height:47px;display:flex;align-items:center;justify-content:center;font-size:13px;
     color:var(--ink);opacity:.62;width:100%;border-radius:12px;position:relative;
     font-variant-numeric:tabular-nums;}''',
         '''  /* 日历数字：她嫌太淡。透明度 .62 → .95，字号 13 → 16，换成那套花体数字
     （digits.woff2 = UnifrakturMaguntia，查过，0-9 十个都在）。 */
  .d{height:47px;display:flex;align-items:center;justify-content:center;font-size:16px;
     color:var(--ink);opacity:.95;width:100%;border-radius:12px;position:relative;
     font-family:"Fraktur",Georgia,serif;letter-spacing:.02em;}'''),
        ('  .d .dd{font-family:"Fraktur",serif;font-size:15.5px;line-height:1;}',
         '  .d .dd{font-size:20px;line-height:1;}'),
        # 卡片下面那句描述句的样式（学她在日记页说的那条规矩）
        ('''  .blk .more{display:block;width:100%;margin-top:10px;font-size:11.5px;letter-spacing:.1em;
             color:var(--soft);text-align:center;padding:7px 0;
             border-top:1px dashed var(--line);}''',
         '''  .blk .more{display:block;width:100%;margin-top:10px;font-size:11.5px;letter-spacing:.1em;
             color:var(--soft);text-align:center;padding:7px 0;
             border-top:1px dashed var(--line);}
  .blk .sub{font-size:10.5px;color:var(--soft);letter-spacing:.02em;line-height:1.7;
            margin:-3px 0 11px;}'''),
        # 抽屉：三段的名字 + 每段一句描述 + 那天的日记
        ('''    h += '<div class="blk"><div class="k">那 天 说 过 的 话</div><div class="v">' +
         paintMini(d.chat || []) + '</div></div>';

    h += '<div class="blk"><div class="k">那 天 我 记 得 的</div><div class="v">' +
         paintDayMem(d.memories || []) + '</div></div>';

    h += '<div class="blk"><div class="k">那 天 的 碎 碎 念</div>' +
         '<div class="v" id="dayPosts">' + paintDayPosts(d.posts || [], false) + '</div></div>';''',
         '''    h += '<div class="blk"><div class="k">回 忆 当 天</div>' +
         '<div class="sub">那天我们说过的话。只看，不能在这儿说。</div>' +
         '<div class="v">' + paintMini(d.chat || []) + '</div></div>';

    h += '<div class="blk"><div class="k">那 天 我 记 得 的</div>' +
         '<div class="sub">从记忆星河里捞出来的那几条。</div>' +
         '<div class="v">' + paintDayMem(d.memories || []) + '</div></div>';

    h += '<div class="blk" id="dayDiaryBlk" style="display:none"></div>';

    h += '<div class="blk"><div class="k">那 天 的 碎 碎 念 和 便 签</div>' +
         '<div class="sub">收着呢，点一下才全出来。</div>' +
         '<div class="v" id="dayPosts">' + paintDayPosts(d.posts || [], false) + '</div></div>';'''),
        # 那天有日记就露一行，点进去就能写
        ('''    $("dayBody").innerHTML = h;
  });
}

function paintMini(list){''',
         '''    $("dayBody").innerHTML = h;
    paintDayDiary(k);
  });
}

function paintDayDiary(day){
  get("/api/r/diary/" + day).then(function(d){
    var el = $("dayDiaryBlk");
    if (!el) return;
    var n = (d && d.text) ? d.text.length : 0;
    el.style.display = "";
    el.innerHTML = '<div class="k">我 的 日 记</div>' +
      '<div class="sub">这天的话。只存，我不读。</div>' +
      '<button class="more" onclick="goDiaryDay(\\'' + day + '\\')">' +
      (n ? "这天写了 " + n + " 字 · 翻开" : "这天还空着 · 写一句") + '</button>';
  });
}

function goDiaryDay(day){
  go("diary");
  openDiary(day);
}

function paintMini(list){'''),
        # 收 / 展
        ('''var dayPostsAll = [];
function paintDayPosts(list, all){
  dayPostsAll = list;
  if (!list.length) return '<span style="opacity:.5">这天没写。</span>';
  var show = all ? list : list.slice(0, 2);''',
         '''var dayPostsAll = [];
var dayPostsOpen = false;
function paintDayPosts(list, all){
  dayPostsAll = list;
  if (all !== undefined) dayPostsOpen = !!all;
  if (!list.length) return '<span style="opacity:.5">这天没写。</span>';
  var show = dayPostsOpen ? list : list.slice(0, 2);'''),
        ('''    h += '<button class="more" onclick="dayPostsMore()">展开剩下的 ' + (list.length - 2) + ' 条</button>';
  }
  return h;
}
function dayPostsMore(){
  var el = $("dayPosts");
  if (el) el.innerHTML = paintDayPosts(dayPostsAll, true);
}''',
         '''  }
  if (list.length > 2 && !dayPostsOpen){
    h += '<button class="more" onclick="dayPostsMore()">展开全部 ' + list.length + ' 条 ▾</button>';
  } else if (list.length > 2 && dayPostsOpen){
    h += '<button class="more" onclick="dayPostsMore()">收起来 ▴</button>';
  }
  return h;
}
function dayPostsMore(){
  var el = $("dayPosts");
  if (el) el.innerHTML = paintDayPosts(dayPostsAll, !dayPostsOpen);
}'''),
    ],
}

VER_FILES = {"VERSION": "2026-10-03e\n"}


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
