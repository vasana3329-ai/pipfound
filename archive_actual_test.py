#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""آزمونِ لایه‌ی ۴.۱۶ — «آرشیو: نتیجه‌ی قطعی، نه گزاره‌ی شرطی» (خواسته‌ی کاربر).

خواسته: «می‌خوام فقط نتیجه‌ی اخبار فاندمنتال بیاد — مثلاً بالاتر از حد انتظار با
عدد و رقم و اینکه صعودی بود یا نزولی. گزاره‌ی شرطی نمی‌خوام؛ مطلق باشه، چون بعد
از اعلامِ خبر نتیجه را می‌بینیم و حدسی در کار نیست.»

سه بخش:
  ۱) قاعده‌ی نگهبانِ `selfcheck.archive_problems` روی مخزنِ سالم صفر خطا می‌دهد.
  ۲) جهش‌آزمایی: شکستنِ هر حلقه‌ی زنجیره (گیرنده‌ی Actual → حکم → رندرِ مطلق)
     باید نام‌دار قرمز شود؛ جهش‌های بی‌گناه سبز بمانند.
  ۳) رفتارِ خالص: `_verdict` روی جدولِ ثابت — عددِ اعلام‌شده ⇒ حکمِ مطلقِ
     صعودی/نزولی/خنثی؛ بدونِ عدد یا بدونِ انتظارِ عددی ⇒ «نامعلومِ صادق» (حدس ممنوع).

آفلاین است (فقط متنِ کد سنجیده می‌شود؛ شبکه‌ای در کار نیست). PF_ARCHIVE_NO_MUT=1
بخشِ جهش را رد می‌کند (فرارِ سریعِ CI محدود).
"""
import io
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import selfcheck as SC  # noqa: E402

# ── ابزارِ جهش (سبکِ مخزن: لنگر باید یکتا باشد وگرنه خطا — نه سبزِ خاموش) ──
CHECKS, FAILS = [], []


def check(name, cond, detail=""):
    CHECKS.append(name)
    if not cond:
        FAILS.append((name, detail))
    return bool(cond)


def copy_repo():
    d = tempfile.mkdtemp(prefix="pf_archive_")
    dst = os.path.join(d, "app")
    shutil.copytree(HERE, dst, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", ".ff_cache.json", ".te_actuals.json",
        "*.log", ".DS_Store", "fundamental_report.md"))
    return dst


def drop(d):
    shutil.rmtree(os.path.dirname(d), ignore_errors=True)


def edit(d, name, old, new):
    p = os.path.join(d, name)
    txt = io.open(p, encoding="utf-8").read()
    n = txt.count(old)
    if n != 1:
        raise AssertionError("لنگرِ جهش در %s %d بار پیدا شد (باید ۱ باشد): %r"
                             % (name, n, old[:60]))
    io.open(p, "w", encoding="utf-8").write(txt.replace(old, new, 1))


def scan(d):
    return SC.archive_problems(d, SC.page_sources(d))


def run_guard(mutate=None):
    d = copy_repo()
    try:
        if mutate:
            mutate(d)
        return scan(d)
    finally:
        drop(d)


def red(name, needle, mutate):
    """جهش باید قاعده را قرمز کند و پیام باید «سوزن» را داشته باشد (نام‌دار)."""
    d = copy_repo()
    try:
        mutate(d)
        probs, _ = scan(d)
        hit = any(needle in p for p in probs)
        check("قرمز: " + name, hit,
              "قاعده سبز ماند یا پیامِ نام‌دار نداشت! probs=" + str(probs)[:300])
    finally:
        drop(d)


NO_MUT = os.environ.get("PF_ARCHIVE_NO_MUT") == "1"

# ═══ ۱) قاعده روی مخزنِ سالم ═══
print("═══ ۱) قاعدهٔ نگهبان روی مخزنِ سالم ═══")
p0, s0 = scan(HERE)
check("قاعده: مخزنِ سالم صفر خطا", p0 == [], str(p0)[:300])
check("قاعده: گیرندهٔ Actual سبز", s0.get("actuals") is True, str(s0))
check("قاعده: حکمِ قطعی سبز", s0.get("verdict") is True, str(s0))
check("قاعده: رندرِ مطلق سبز", s0.get("render") is True, str(s0))
check("قاعده: صعودی/نزولی در رندر هست", (s0.get("outcomes") or 0) >= 2, str(s0))

# ═══ ۲) جهش‌آزماییِ قاعده ═══
if not NO_MUT:
    print("═══ ۲) جهش‌آزماییِ قاعده (قرمز/بی‌گناه) ═══")
    red("گیرنده‌ی Actual (get_actuals) حذف شده",
        "گیرنده‌ی Actual",
        lambda d: edit(d, "macro_context.py", "def get_actuals(max_age=3600):",
                       "def get_actuals_gone(max_age=3600):"))
    red("الگوی ستونِ Actual در پارسر نیست",
        "الگوی ستونِ Actual",
        lambda d: edit(d, "macro_context.py", "<span id='actual'>",
                       "<span id='aktual'>"))
    red("archive دیگر _attach_verdicts را صدا نمی‌زند",
        "_attach_verdicts را صدا نمی‌زند",
        lambda d: edit(d, "fundamental.py", "src_ok = _attach_verdicts(out)",
                       "src_ok = True"))
    red("تابعِ حکم (_verdict) حذف شده",
        "تابعِ حکم",
        lambda d: edit(d, "fundamental.py", "def _verdict(actual, forecast, previous, mode):",
                       "def _verdict_gone(actual, forecast, previous, mode):"))
    red("آرشیو v.found را نمی‌سنجد",
        "v.found را نمی‌سنجد",
        lambda d: edit(d, "app.py", "if(v.found){", "if(false){"))
    red("آرشیو صعودی/نزولی را نشان نمی‌دهد",
        "صعودی/نزولی را نشان نمی‌دهد",
        lambda d: edit(d, "app.py",
                       'const cls = v.outcome==="صعودی"?"v-up":(v.outcome==="نزولی"?"v-dn":"v-fl");\n'
                       '          const arr = v.outcome==="صعودی"?"▲":(v.outcome==="نزولی"?"▼":"◆");\n'
                       '          const dd = v.outcome==="صعودی"?"صعودی":(v.outcome==="نزولی"?"نزولی":"خنثی");',
                       'const cls = "v-fl";\n          const arr = "◆";\n          const dd = "—";'))
    red("عددِ اعلام‌شده (v.actual) در رندر نیست",
        "عددِ اعلام‌شده",
        lambda d: edit(d, "app.py", 'class="arc-num">${v.actual}',
                       'class="arc-num">—'))
    red("پیامِ شفافِ «منبع در دسترس نبود» حذف شده",
        "منبع در دسترس نبود",
        lambda d: edit(d, "app.py", "منبعِ پاسخ نداد", "منبعِ پاسخ داد"))

    # بی‌گناه‌ها: نباید قرمز شوند
    d = copy_repo()
    try:
        edit(d, "fundamental.py", '_VERDICT_SKIP_TOKENS = ("—", "-", "n/a", "na", "tbd")',
             '_VERDICT_SKIP_TOKENS = ("—", "-", "n/a", "na", "tbd", "nah")')
        probs, st = scan(d)
        check("بی‌گناه: افزودنِ توکنِ رد به فهرستِ _num سبز می‌مانَد",
              probs == [] and st.get("actuals") is True, str(probs)[:200])
    finally:
        drop(d)
    d = copy_repo()
    try:
        edit(d, "app.py", 'class="arc-v ${cls}"', 'class="arc-v ${cls} extra"')
        probs, st = scan(d)
        check("بی‌گناه: کلاسِ نمایشیِ تازه در رندر سبز می‌مانَد",
              probs == [] and st.get("render") is True, str(probs)[:200])
    finally:
        drop(d)

# ═══ ۳) رفتارِ خالصِ _verdict (جدولِ ثابت — بدونِ شبکه) ═══
print("═══ ۳) رفتارِ خالصِ حکم (بدونِ شبکه) ═══")
import fundamental as F  # noqa: E402

# (a) خبرِ اعلام‌شده با عدد: حکمِ مطلق
v = F._verdict("81.9", "89.2", "86.3", "normal")
check("حکم: پایین‌تر از انتظار ⇒ نزولی (نرمال)",
      v["found"] and v["beat"] == "پایین‌تر از انتظار" and v["outcome"] == "نزولی", str(v))
v = F._verdict("3.9%", "3.6%", "3.6%", "normal")
check("حکم: بالاتر از انتظار ⇒ صعودی (نرمال)",
      v["found"] and v["beat"] == "بالاتر از انتظار" and v["outcome"] == "صعودی", str(v))
v = F._verdict("0.0%", "0.0%", "0.1%", "normal")
check("حکم: طبقِ انتظار ⇒ خنثی",
      v["found"] and v["outcome"] == "خنثی" and v["beat"] == "دقیقاً طبقِ انتظار", str(v))
v = F._verdict("4.3%", "4.6%", "4.35%", "normal")
check("حکم: عدد + رقم (درصد) کنار هم می‌آید",
      v["found"] and v["actual"] == "4.3%" and v["forecast"] == "4.6%", str(v))

# (b) شاخصِ معکوس (بیکاری): بالاتر ⇒ ضعیف‌تر ⇒ نزولی
v = F._verdict("4.3%", "4.1%", "4.2%", "inverse")
check("حکم: شاخصِ معکوس — بالاتر از انتظار ⇒ نزولی",
      v["found"] and v["outcome"] == "نزولی" and v["dir"] == "ضعیف‌تر", str(v))

# (c) صداقت: بدونِ عددِ اعلام‌شده یا بدونِ انتظارِ عددی ⇒ نامعلوم (حدس ممنوع)
v = F._verdict("", "5.0%", "4.0%", "normal")
check("صداقت: بدونِ عددِ اعلام‌شده ⇒ found=False",
      v["found"] is False and v["outcome"] == "", str(v))
v = F._verdict("—", "5.0%", "4.0%", "normal")
check("صداقت: جای‌نگهدارِ «—» عدد نیست ⇒ found=False", v["found"] is False, str(v))
v = F._verdict("81.9", "", "80.0", "normal")
check("صداقت: انتظارِ عددی نبود ⇒ جهت ساخته نمی‌شود (نه صعودی نه نزولی)",
      v["found"] is True and v["outcome"] == "" and v["beat"] == "انتظارِ عددی ثبت نشده بود", str(v))
v = F._verdict("بالاتر از انتظار", "5.0%", "4.0%", "normal")
check("صداقت: متنِ غیرعددیِ اعلام‌شده ⇒ found=False", v["found"] is False, str(v))

# (d) تطبیقِ نامِ TE×FF واژه‌محور است و نامشابه را رد نمی‌کند
check("تطبیقِ نام: «ppi yoy» با «Manufacturing PPI y/y» می‌نشیند",
      F._titles_match("ppi yoy", "Manufacturing PPI y/y") is True, "")
check("تطبیقِ نام: خبرِ بی‌ربط رد می‌شود",
      F._titles_match("cpi yoy", "Retail Sales m/m") is False, "")

# ── جمع‌بندی ──
print("\n• بررسی‌ها: %d" % len(CHECKS))
if FAILS:
    for name, detail in FAILS:
        print("::error::❌ %s — %s" % (name, detail[:220]))
    print("\n❌ آزمونِ «نتیجهٔ قطعیِ آرشیو» رد شد — %d از %d بررسی شکست خورد"
          % (len(FAILS), len(CHECKS)))
    sys.exit(1)
print("✅ آزمونِ «نتیجهٔ قطعیِ آرشیو» پاس شد — گیرندهٔ Actual، حکمِ مطلقِ "
      "صعودی/نزولی با عدد و رقم، صداقتِ «نامعلوم» و رندرِ آرشیو همه قفل‌اند")
