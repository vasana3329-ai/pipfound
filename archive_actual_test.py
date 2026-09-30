#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""آزمونِ لایه‌ی ۴.۱۶ — «آرشیو: نتیجه‌ی قطعی، نه گزاره‌ی شرطی» (خواسته‌ی کاربر).

خواسته (دورِ اول): «می‌خوام فقط نتیجه‌ی اخبار فاندمنتال بیاد — مثلاً بالاتر از حد
انتظار با عدد و رقم و اینکه صعودی بود یا نزولی. گزاره‌ی شرطی نمی‌خوام؛ مطلق
باشه، چون بعد از اعلامِ خبر نتیجه را می‌بینیم و حدسی در کار نیست.»
خواسته (دورِ دوم — همان چیزی که این لایه حالا قفل می‌کند): «می‌خوام توو آرشیو
اقتصادی فقط نتیجه بیاد بعلاوهٔ تأثیرش، نه گزارهٔ شرطی» — یعنی دو سطرِ قدیمیِ
«⬆ اگر بالاتر از انتظار شد → … / ⬇ اگر پایین‌تر شد → …» از پنجرهٔ آرشیو رفتند و
جایشان **تأثیرِ محقَقِ همان نتیجه** روی جفت‌ارزها/طلا نشست.

سه بخش:
  ۱) قاعده‌ی نگهبانِ `selfcheck.archive_problems` روی مخزنِ سالم صفر خطا می‌دهد،
     و منطقهٔ خودِ آرشیو از گزارهٔ شرطی (beat/miss) پاک است.
  ۲) جهش‌آزمایی: شکستنِ هر حلقه‌ی زنجیره (گیرندهٔ Actual → حکمِ اثرساز → رندرِ
     «نتیجه + تأثیر») باید نام‌دار قرمز شود؛ جهش‌های بی‌گناه سبز بمانند.
  ۳) رفتارِ خالص: `_verdict` روی جدولِ ثابت — عددِ اعلام‌شده ⇒ حکمِ مطلقِ
     صعودی/نزولی/خنثی **+ تأثیرِ همان جهت**؛ بدونِ عدد یا بدونِ انتظارِ عددی ⇒
     «نامعلومِ صادق» با تأثیرِ خالی (حدس ممنوع).

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
check("قاعده: تأثیرِ نتیجه سبز", s0.get("effect") is True, str(s0))
check("قاعده: آرشیو بی‌گزارهٔ شرطی است", s0.get("conditional") is True, str(s0))
check("قاعده: رندرِ تأثیرِ نتیجه سبز", s0.get("impact") is True, str(s0))

# ═══ ۱.۵) سنجشِ استاتیکِ خودِ منطقهٔ آرشیو ═══
print("═══ ۱.۵) منطقهٔ آرشیو: نتیجه + تأثیر، بی‌گزارهٔ شرطی ═══")
_page = (SC.page_sources(HERE) or {}).get("HTML") or ""
_reg = SC._archive_region(_page)
check("استاتیک: منطقهٔ هندلرِ آرشیو پیدا شد", bool(_reg), "archiveBtn پیدا نشد")
# توجه: v.beat («بالاتر/پایین‌تر از انتظار») بخشی از *نتیجه* است و می‌مانَد؛
# آنچه نباید باشد شاخهٔ شرطیِ a.beat/a.miss و فلش‌های ⬆/⬇ است.
check("استاتیک: ردیفِ شرطیِ ⬆/⬇ از آرشیو رفته است",
      bool(_reg) and "a.beat" not in _reg and "a.miss" not in _reg
      and "arc-d" not in _reg, _reg[-200:])
check("استاتیک: خطِ «تأثیرِ همین نتیجه» در آرشیو رندر می‌شود",
      'arc-i">تأثیر' in _reg, _reg[-200:])
check("استاتیک: CSSِ خطِ تأثیر هست (‏.arc-i)", ".arc-i{" in _page, "")
check("استاتیک: CSSِ ردیفِ شرطیِ قدیمی حذف شده (‏.arc-d)", ".arc-d{" not in _page,
      "ردیفِ شرطیِ قدیمی هنوز استایل دارد")
check("قاعده: بارِ آرشیو بی‌شاخهٔ شرطی است", s0.get("lean") is True, str(s0))
check("قاعده: ردیفِ خبرِ بی‌عدد صادق است (نه سکوت)", s0.get("perrow") is True, str(s0))
check("استاتیک: متنِ ردیفِ بی‌عدد در منطقهٔ آرشیو هست",
      "عددِ اعلام‌شده ندارد" in _reg, _reg[-200:])
_fsrc = io.open(os.path.join(HERE, "fundamental.py"), encoding="utf-8").read()
_areg = SC._py_region(_fsrc, "def archive(hours=6):", "\ndef build(hours=180):")
check("استاتیک: payloadِ آرشیو دیگر analysis (beat/miss) را نمی‌فرستد",
      bool(_areg) and '"analysis"' not in _areg, _areg[:160])
check("استاتیک: payloadِ آرشیو آیکن/دامنه را می‌فرستد (رابط نشکند)",
      '"icon": icon' in _areg, _areg[:160])
check("استاتیک: خبرهای پیش‌رو همچنان دو سناریو دارند (عمدی)",
      "\"analysis\": _analysis" in _fsrc, "")

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
        lambda d: edit(d, "fundamental.py", "def _verdict(actual, forecast, previous, mode, ccy=None):",
                       "def _verdict_gone(actual, forecast, previous, mode, ccy=None):"))
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
    red("گزارهٔ شرطی (beat/miss) به آرشیو برگشت",
        "گزارهٔ شرطی",
        lambda d: edit(d, "app.py",
                       "const v=e.verdict||{}, ef=v.effect||{};",
                       "const a=e.analysis||{}, b=a.beat||{}, v=e.verdict||{}, ef=v.effect||{};"))
    red("ردیفِ خبرِ بی‌عدد ساکت شد (پیامِ صادق برداشته شد)",
        "ردیفِ خالی",
        lambda d: edit(d, "app.py", "◇ این خبر عددِ اعلام‌شده ندارد",
                       "◇ این خبر عددی ندارد"))
    red("خطِ «تأثیرِ همین نتیجه» از رندر افتاد",
        "تأثیرِ همین نتیجه",
        lambda d: edit(d, "app.py", 'arc-i">تأثیرِ همین نتیجه:', 'arc-i">اثر:'))
    red("سازندهٔ تأثیرِ محقَق حذف شد",
        "سازندهٔ تأثیرِ محقَق",
        lambda d: edit(d, "fundamental.py", "def _realized_effect(ccy, direction):",
                       "def _realized_effect_gone(ccy, direction):"))
    red("بارِ آرشیو باز هم شاخهٔ شرطی (analysis) را می‌فرستد",
        "شاخهٔ شرطی (analysis)",
        lambda d: edit(d, "fundamental.py", '            "icon": icon,',
                       '            "icon": icon,\n            "analysis": _analysis(e.get("title"), ccy),'))
    red("حکم دیگر تأثیرِ خودش را نمی‌سازد",
        "تأثیرِ خودش را نمی‌سازد",
        lambda d: edit(d, "fundamental.py",
                       'res["effect"] = _realized_effect(ccy, res.get("dir") or "")',
                       'res["effect"] = {"pairs": [], "gold": None}'))

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
    d = copy_repo()
    try:
        edit(d, "app.py", "<div class=\"arc-i\">تأثیرِ همین نتیجه: ${imp}</div>",
             "<div class=\"arc-i\">تأثیرِ همین نتیجه: ${imp} (روی جفت‌ارزها و طلا)</div>")
        probs, st = scan(d)
        check("بی‌گناه: توضیحِ بیشتر روی خطِ تأثیر سبز می‌مانَد",
              probs == [] and st.get("impact") is True, str(probs)[:200])
    finally:
        drop(d)
    d = copy_repo()
    try:
        edit(d, "app.py", "if(imp){ vd +=", "if(imp && imp.length){ vd +=")
        probs, st = scan(d)
        check("بی‌گناه: نگهبانِ خالی‌نبودنِ متنِ تأثیر سبز می‌مانَد",
              probs == [] and st.get("impact") is True, str(probs)[:200])
    finally:
        drop(d)
    d = copy_repo()
    try:
        edit(d, "fundamental.py",
             'res["effect"] = _realized_effect(ccy, res.get("dir") or "")',
             'res["effect"] = _realized_effect(ccy, (res.get("dir") or ""))')
        probs, st = scan(d)
        check("بی‌گناه: پرانتزِ اضافه در ساختِ تأثیر سبز می‌مانَد",
              probs == [] and st.get("effect") is True, str(probs)[:200])
    finally:
        drop(d)
    d = copy_repo()
    try:
        edit(d, "fundamental.py", '            "minutes_ago": round((now - dt).total_seconds() / 60),',
             '            "minutes_ago": round((now - dt).total_seconds() / 60, 2),')
        probs, st = scan(d)
        check("بی‌گناه: دقتِ دقیقه‌ها در بارِ آرشیو سبز می‌مانَد",
              probs == [] and st.get("lean") is True, str(probs)[:200])
    finally:
        drop(d)
    d = copy_repo()
    try:
        edit(d, "app.py",
             "◇ این خبر عددِ اعلام‌شده ندارد — نتیجه و تأثیری برای گفتن نیست",
             "◇ این خبر عددِ اعلام‌شده ندارد (سخنرانی یا خبرِ بی‌عدد)")
        probs, st = scan(d)
        check("بی‌گناه: توضیحِ بیشتر روی پیامِ ردیفِ بی‌عدد سبز می‌مانَد",
              probs == [] and st.get("perrow") is True, str(probs)[:200])
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

# (c۲) تأثیرِ محقَق — نه دو گزارهٔ شرطیِ «اگر بالا/پایین شد»
v = F._verdict("81.9", "89.2", "86.3", "normal", "USD")
ef = v.get("effect") or {}
check("تأثیر: دلارِ ضعیف‌تر ⇒ EUR/USD صعود و طلا/نقره صعود",
      any("EUR/USD" in p[0] and "صعود" in p[1] for p in (ef.get("pairs") or []))
      and (ef.get("gold") or ["", ""])[1].startswith("↑"), str(ef)[:220])
v = F._verdict("3.9%", "3.6%", "3.6%", "normal", "USD")
ef = v.get("effect") or {}
check("تأثیر: دلارِ قوی‌تر ⇒ USD/JPY صعود و طلا/نقره نزول",
      any("USD/JPY" in p[0] and "صعود" in p[1] for p in (ef.get("pairs") or []))
      and (ef.get("gold") or ["", ""])[1].startswith("↓"), str(ef)[:220])
v = F._verdict("4.3%", "4.1%", "4.2%", "inverse", "USD")
check("تأثیر: شاخصِ معکوس ⇒ دلار ضعیف ⇒ طلا/نقره صعود",
      (v.get("effect") or {}).get("gold", ["", ""])[1].startswith("↑"), str(v.get("effect"))[:220])
v = F._verdict("0.1%", "0.2%", "0.1%", "normal", "JPY")
ef = v.get("effect") or {}
check("تأثیر: ارزِ غیردلاری فقط کراسِ خودش را می‌گیرد (USD/JPY)",
      len(ef.get("pairs") or []) == 1 and "JPY" in (ef["pairs"][0][0] or ""), str(ef)[:220])
v = F._verdict("81.9", "89.2", "86.3", "normal")
check("صداقت: بدونِ ارز ⇒ تأثیری ساخته نمی‌شود (نه «None/USD»)",
      v["found"] and (v.get("effect") or {}).get("pairs") == [], str(v.get("effect")))
v = F._verdict("—", "5.0%", "4.0%", "normal", "USD")
check("صداقت: بدونِ عددِ اعلام‌شده ⇒ تأثیرِ خالی (حدس ممنوع)",
      v["found"] is False and (v.get("effect") or {}).get("pairs") == [], str(v))
v = F._verdict("81.9", "", "80.0", "normal", "USD")
check("صداقت: انتظارِ عددی نبود ⇒ جهت و تأثیر هر دو خالی‌اند",
      v["found"] and v["outcome"] == "" and (v.get("effect") or {}).get("pairs") == [], str(v))

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
    print("\n❌ آزمونِ «نتیجه + تأثیرِ آرشیو» رد شد — %d از %d بررسی شکست خورد"
          % (len(FAILS), len(CHECKS)))
    sys.exit(1)
print("✅ آزمونِ «نتیجه + تأثیرِ آرشیو، بی‌گزارهٔ شرطی» پاس شد — گیرندهٔ Actual، "
      "حکمِ مطلقِ صعودی/نزولی با عدد و رقم، تأثیرِ محقَقِ همان نتیجه، صداقتِ "
      "«نامعلوم» و پاک‌بودنِ پنجرهٔ آرشیو از گزارهٔ شرطی همه قفل‌اند")
