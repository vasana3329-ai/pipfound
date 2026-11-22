#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""آزمونِ لایه‌ی ۴.۱۸ — «کرکره‌های جمعِ پیش‌فرض» (خواسته‌ی کاربر).

شکایت/خواسته: «اون بخش پشتیبان و انتقال داده فقط یه کلید باشه که روش کلیک بشه و
کرکره انتخاب گزینه‌هاش باز بشه؛ این‌جوری که الان می‌بینم خیلی صفحه اصلی اپ رو شلوغ و
بچه‌گونه نشون می‌ده» و بعد: «پنل‌های همیشه‌بازِ دیگرِ نمای اصلی (آلارم‌های فعال،
بازه‌ی بک‌تست و مدیریتِ ریسک) را هم جمع‌شدنی کن».
⇒ هیچ‌کدام از این چهار بخشِ «نگهداری» نباید در نمای اصلی همیشه‌باز باشد.

این لایه قاعده‌ی استاتیکِ `selfcheck.fold_panels_problems` و جهش‌آزمایی‌اش را قفل
می‌کند: بخشِ ۱ روی مخزنِ سالم، بخشِ ۲ با جهش‌های عمدی (قرمز باید **نام‌دار** شود و
پاک‌سازی‌های بی‌گناه سبز بمانند).

یک تلهٔ واقعیِ همین دور هم قفل است: هر قاعدهٔ CSSی که *بعدتر* روی خودِ بدنه
`display` بگذارد (هم‌وزنِ انتخاب‌گر + ترتیبِ متن) پنهان‌بودنِ پیش‌فرض را بی‌اثر
می‌کند — `display:flex`ِ `.bt-body` زنده دقیقاً همین کار را کرد و پنل در بارگذاری
باز ماند؛ حالا هم قاعده (`_fold_display_overrides`) و هم جهشِ سرخِ نام‌دارش شاهدند.

رفتارِ **واقعی** (بسته در بارگذاری و دیده‌نشدنِ گزینه‌ها، باز شدن با یک کلیک،
کلیک‌پذیریِ واقعیِ گزینه، و بسته‌شدنِ دوباره برای هر چهار بخش) در لایه‌ی ۳ با
مرورگرِ واقعی سنجیده می‌شود (`ui_visual_check.cjs` بندِ ۶.۹) — پس این‌جا عمداً ادعای
رفتاری تکرار نمی‌شود.

آفلاین و چندثانیه‌ای است. PF_DOCK_NO_MUT=1 بخشِ جهش را رد می‌کند.
"""
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import selfcheck as SC  # noqa: E402

CHECKS, FAILS = [], []


def check(name, cond, detail=""):
    CHECKS.append(name)
    if not cond:
        FAILS.append((name, detail))
    return bool(cond)


def copy_repo():
    d = tempfile.mkdtemp(prefix="pf_dock_")
    dst = os.path.join(d, "app")
    shutil.copytree(HERE, dst, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", ".ff_cache.json", ".te_actuals.json",
        "*.log", ".DS_Store", "fundamental_report.md"))
    return dst


def drop(d):
    shutil.rmtree(os.path.dirname(d), ignore_errors=True)


def _read(d, name):
    return io.open(os.path.join(d, name), encoding="utf-8").read()


def _write(d, name, txt):
    io.open(os.path.join(d, name), "w", encoding="utf-8").write(txt)


def edit(d, name, old, new, expect=1):
    """جهش با لنگرِ یکتا — اگر لنگر پیدا نشود، **خطا** می‌دهد نه سبزِ خاموش."""
    txt = _read(d, name)
    n = txt.count(old)
    if n != expect:
        raise AssertionError("لنگرِ جهش در %s %d بار پیدا شد (باید %d باشد): %r"
                             % (name, n, expect, old[:60]))
    _write(d, name, txt.replace(old, new))


def scan(d):
    return SC.fold_panels_problems(d, SC.page_sources(d))


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


def green(name, mutate, key):
    """جهشِ بی‌گناه نباید قرمز شود و شاخصِ مربوطه باید سبز بماند."""
    d = copy_repo()
    try:
        mutate(d)
        probs, st = scan(d)
        check("بی‌گناه: " + name, probs == [] and st.get(key) is True,
              "probs=" + str(probs)[:200] + " stats=" + str(st))
    finally:
        drop(d)


NO_MUT = os.environ.get("PF_DOCK_NO_MUT") == "1"
N_PANELS = len(SC._FOLD_PANELS)

# ═══ ۱) قاعده روی مخزنِ سالم ═══
print("═══ ۱) قاعده‌ی کرکره‌های نمای اصلی روی مخزنِ سالم ═══")
p0, s0 = scan(HERE)
check("قاعده: مخزنِ سالم صفر خطا", p0 == [], str(p0)[:300])
check("قاعده: هر چهار بخشِ نگهداری جمعِ پیش‌فرض‌اند", s0.get("panels") == N_PANELS, str(s0))
check("قاعده: مکانیکِ مشترکِ بسته‌بودن سرِ جایش است", s0.get("collapsed") is True, str(s0))
check("قاعده: هر چهار نوار کلیدپذیرند و aria به‌روز می‌شود", s0.get("wired") is True, str(s0))
check("قاعده: گزینه‌های پشتیبان داخلِ بدنه‌اند", s0.get("options_inside") is True, str(s0))
check("قاعده: خلاصه‌ی وضعیت روی نوار دیده می‌شود", s0.get("state") is True, str(s0))

# ═══ ۲) جهش‌آزماییِ قاعده ═══
if not NO_MUT:
    print("═══ ۲) جهش‌آزماییِ قاعده (قرمز/بی‌گناه) ═══")
    # (الف) هر بخش باید کلاسِ کرکره داشته باشد
    red("کلاسِ کرکره از بخشِ آلارم‌ها برداشته شده (همیشه‌باز می‌شود)",
        "alarmsDock کلاسِ کرکره (fold) ندارد",
        lambda d: edit(d, "app.py", 'class="alarms-dock fold" id="alarmsDock"',
                       'class="alarms-dock" id="alarmsDock"'))
    red("کلاسِ کرکره از تنظیماتِ بک‌تست برداشته شده",
        "btPanel کلاسِ کرکره (fold) ندارد",
        lambda d: edit(d, "app.py", 'class="fold btpanel"', 'class="btpanel"'))
    red("کلاسِ کرکره از مدیریتِ ریسک برداشته شده",
        "riskPanel کلاسِ کرکره (fold) ندارد",
        lambda d: edit(d, "app.py", 'class="riskpanel fold"', 'class="riskpanel"'))
    # (ب) نوارِ هر بخش باید کلیدپذیر و در حالتِ «بسته» باشد
    red("حالتِ اولیه‌ی نوارِ ریسک از «بسته» به «باز» رفته (aria-expanded)",
        "riskPanel کلیدپذیر نیست",
        lambda d: edit(d, "app.py", 'aria-expanded="false" aria-controls="rkBody"',
                       'aria-expanded="true" aria-controls="rkBody"'))
    red("نوارِ آلارم‌ها به بدنهٔ اشتباه وصل شده (aria-controls)",
        "alarmsDock کلیدپذیر نیست",
        lambda d: edit(d, "app.py", 'aria-expanded="false" aria-controls="alarmsBody"',
                       'aria-expanded="false" aria-controls="alarmsBodyX"'))
    # (ج) مکانیکِ مشترک: پنهان‌بودنِ پیش‌فرض و قاعده‌ی بازشدن
    red("بدنه‌ها پیش‌فرض پنهان نیستند (CSS) — صفحه دوباره شلوغ می‌شود",
        "پیش‌فرض پنهان نیست",
        lambda d: edit(d, "app.py", ".fold-body{display:none}", ".fold-body{display:block}"))
    red("قاعده‌ی بازشدنِ کرکره‌ها خراب شده (کلاسِ open بی‌اثر)",
        "قاعدهٔ بازشدنِ کرکره‌ها نیست",
        lambda d: edit(d, "app.py", ".fold.open .fold-body{display:block}",
                       ".fold.open .fold-body{display:none}"))
    red("قاعدهٔ نمایشیِ تازه روی خودِ بدنه، پنهان‌بودن را بی‌اثر کرده "
        "(همان باگِ واقعیِ همان دور: display روی بدنهٔ بک‌تست)",
        "بی‌اثر می‌کند",
        lambda d: edit(d, "app.py",
                       ".bt-body{padding-top:12px;border-top:1px dashed var(--line)}",
                       ".bt-body{padding-top:12px;border-top:1px dashed var(--line);display:flex}"))
    # (د) سیم‌کشیِ عمومی و aria
    red("سازندهٔ کرکره (pfFold) حذف/تغییرنام شده — هیچ نواری سیم‌کشی نمی‌شود",
        "سازندهٔ کرکره (pfFold) حذف شده",
        lambda d: edit(d, "app.py", "function pfFold(boxId, toggleId, bodyId){",
                       "function pfFoldX(boxId, toggleId, bodyId){"))
    red("سیم‌کشیِ یک بخش (آلارم‌ها) از فهرستِ pfFold برداشته شده",
        "کرکرهٔ alarmsDock سیم‌کشی نشده",
        lambda d: edit(d, "app.py", 'pfFold("alarmsDock","alarmsToggle","alarmsBody");',
                       "", expect=1))
    red("نوارها وضعیتِ خودشان را به صفحه‌خوان نمی‌گویند (aria-expanded به‌روز نمی‌شود)",
        "به صفحه‌خوان نمی‌گویند",
        lambda d: edit(d, "app.py",
                       'tgl.setAttribute("aria-expanded", open?"true":"false");',
                       'tgl.setAttribute("aria-expandedX", open?"true":"false");'))
    # (ه) بخشِ پشتیبان: گزینه‌ها باید داخلِ بدنه بمانند
    red("گزینه‌ها بیرونِ بدنه‌ی کرکرهٔ پشتیبان رها شده‌اند (جمع نمی‌شوند)",
        "بیرونِ بدنهٔ کرکرهٔ پشتیبان",
        lambda d: edit(d, "app.py", '    <div class="fold-body bk-body" id="bkBody">',
                       '    <div id="abList"></div>\n    <div class="fold-body bk-body" id="bkBody">'))
    red("خلاصه‌ی وضعیتِ پشتیبان در نوار پر نمی‌شود (JS)",
        "خلاصهٔ وضعیتِ پشتیبان",
        lambda d: edit(d, "app.py", 'document.getElementById("bkState")',
                       'document.getElementById("bkStateX")', expect=2))
    red("جایِ خلاصه‌ی وضعیت از نوار برداشته شده (مارک‌آپ)",
        "خلاصهٔ وضعیتِ پشتیبان",
        lambda d: edit(d, "app.py", 'id="bkState"', 'id="bkStateX"'))

    # بی‌گناه‌ها: نباید قرمز شوند
    green("عوض‌کردنِ گلیفِ فلشِ یک کرکره سبز می‌مانَد",
          lambda d: edit(d, "app.py",
                         '<span class="arr" aria-hidden="true">▾</span>',
                         '<span class="arr" aria-hidden="true">⌄</span>', expect=N_PANELS),
          "wired")
    green("افزودنِ یک کلاسِ نمایشیِ اضافه به بدنهٔ بک‌تست سبز می‌مانَد",
          lambda d: edit(d, "app.py", '<div class="fold-body bt-body" id="btBody">',
                         '<div class="fold-body bt-body bt-lead" id="btBody">'),
          "collapsed")
    green("تنظیمِ فاصله‌ی داخلیِ بدنه سبز می‌مانَد",
          lambda d: edit(d, "app.py", ".alarms-body{padding:0 18px 18px}",
                         ".alarms-body{padding:0 22px 18px}"),
          "collapsed")
    green("ویرایشِ متنِ توضیحِ داخلِ بدنه‌ی ریسک سبز می‌مانَد",
          lambda d: edit(d, "app.py", "و سقفِ ضررِ روزانه/تمرکزِ معاملات را هم بپاید.</div>",
                         "و سقفِ ضررِ روزانه/تمرکزِ معاملات را هم بپاید (پیش‌فرض ۱٪).</div>"),
          "wired")
    green("قاعدهٔ اختصاصیِ «باز شدن» برای یک بدنه سبز می‌مانَد (استثنای عمدی)",
          lambda d: edit(d, "app.py",
                         ".bt-body{padding-top:12px;border-top:1px dashed var(--line)}",
                         ".bt-body{padding-top:12px;border-top:1px dashed var(--line)}\n"
                         ".fold.open .bt-body{display:block}"),
          "collapsed")

# ── جمع‌بندی ──
print("\n• بررسی‌ها: %d" % len(CHECKS))
if FAILS:
    for name, detail in FAILS:
        print("::error::❌ %s — %s" % (name, detail[:220]))
    print("\n❌ آزمونِ «کرکره‌های جمعِ پیش‌فرض» رد شد — %d از %d بررسی شکست خورد"
          % (len(FAILS), len(CHECKS)))
    sys.exit(1)
print("✅ آزمونِ «کرکره‌های جمعِ پیش‌فرض» پاس شد — هر چهار بخشِ نگهداری (آلارم‌ها، "
      "بک‌تست، ریسک و پشتیبانِ داده) نوارِ کلیدپذیر دارند، بدنه‌شان پیش‌فرض بسته است "
      "و خلاصه‌ی وضعیت روی نوار دیده می‌شود")
