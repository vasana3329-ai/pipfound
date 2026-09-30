#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""آزمونِ لایه‌ی ۴.۱۸ — «کرکره‌ی پشتیبان: جمعِ پیش‌فرض» (خواسته‌ی کاربر).

شکایت: «می‌خوام اون بخش پشتیبان و انتقال داده فقط یه کلید باشه که روش کلیک بشه و
کرکره انتخاب گزینه‌هاش باز بشه؛ این‌جوری که الان می‌بینم خیلی صفحه اصلی اپ رو شلوغ و
بچه‌گونه نشون می‌ده.»
⇒ بخشِ «📦 پشتیبان و انتقالِ داده» نباید یک بلوکِ همیشه‌باز باشد؛ باید یک نوارِ
کلیدپذیر باشد که گزینه‌ها را باز/بسته می‌کند.

این لایه قاعده‌ی استاتیکِ `selfcheck.backup_dock_problems` و جهش‌آزمایی‌اش را قفل
می‌کند: بخشِ ۱ روی مخزنِ سالم، بخشِ ۲ با جهش‌های عمدی (قرمز باید **نام‌دار** شود و
پاک‌سازی‌های بی‌گناه سبز بمانند).

رفتارِ **واقعی** (بسته در بارگذاری، باز با یک کلیک، بستهٔ دوباره، و دیده‌نشدنِ
گزینه‌ها در حالتِ بسته) در لایه‌ی ۳ با مرورگرِ واقعی سنجیده می‌شود
(`ui_visual_check.cjs` بندِ ۶.۹) — پس این‌جا عمداً ادعای رفتاری تکرار نمی‌شود.

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
    return SC.backup_dock_problems(d, SC.page_sources(d))


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

# ═══ ۱) قاعده روی مخزنِ سالم ═══
print("═══ ۱) قاعده‌ی کرکره‌ی پشتیبان روی مخزنِ سالم ═══")
p0, s0 = scan(HERE)
check("قاعده: مخزنِ سالم صفر خطا", p0 == [], str(p0)[:300])
check("قاعده: کرکره شناخته می‌شود (bkDock/bk-dock)", s0.get("dock") is True, str(s0))
check("قاعده: بدنه پیش‌فرض بسته است", s0.get("collapsed") is True, str(s0))
check("قاعده: نوار کلیدپذیر است و aria به‌روز می‌شود", s0.get("wired") is True, str(s0))
check("قاعده: گزینه‌ها داخلِ بدنه‌ی کرکره‌اند", s0.get("options_inside") is True, str(s0))
check("قاعده: خلاصه‌ی وضعیت روی نوار دیده می‌شود", s0.get("state") is True, str(s0))

# ═══ ۲) جهش‌آزماییِ قاعده ═══
if not NO_MUT:
    print("═══ ۲) جهش‌آزماییِ قاعده (قرمز/بی‌گناه) ═══")
    red("کلاسِ کرکره از بخشِ پشتیبان برداشته شده (دوباره بلوکِ همیشه‌باز)",
        "کرکره‌ی «پشتیبان و انتقالِ داده»",
        lambda d: edit(d, "app.py", 'class="alarms-dock bk-dock" id="bkDock"',
                       'class="alarms-dock" id="bkDock"'))
    red("نوارِ کلیدپذیر بی‌شناسه شده (bkToggle)",
        "حذف شده",
        lambda d: edit(d, "app.py", 'id="bkToggle" class="bk-toggle"',
                       'id="bkToggleX" class="bk-toggle"'))
    red("حالتِ اولیه‌ی نوار از «بسته» به «باز» تغییر کرده (aria-expanded)",
        "حالتِ اولیه‌ی درست ندارد",
        lambda d: edit(d, "app.py", 'aria-expanded="false" aria-controls="bkBody"',
                       'aria-expanded="true" aria-controls="bkBody"'))
    red("بدنه پیش‌فرض پنهان نیست (CSS) — صفحه دوباره شلوغ می‌شود",
        "پیش‌فرض پنهان نیست",
        lambda d: edit(d, "app.py", ".bk-body{display:none;", ".bk-body{display:block;"))
    red("قاعده‌ی بازشدنِ کرکره خراب شده (کلاسِ open بی‌اثر)",
        "قاعده‌ی بازشدنِ کرکره نیست",
        lambda d: edit(d, "app.py", ".bk-dock.open .bk-body{display:block}",
                       ".bk-dock.open .bk-body{display:none}"))
    red("سیم‌کشیِ کلیکِ نوار برداشته شده — کلید بی‌اثر می‌مانَد",
        "سیم‌کشی نشده",
        lambda d: edit(d, "app.py", "bkToggle.onclick=", "bkToggleX.onclick="))
    red("نوار وضعیتش را به صفحه‌خوان نمی‌گوید (aria-expanded به‌روز نمی‌شود)",
        "به صفحه‌خوان نمی‌گوید",
        lambda d: edit(d, "app.py",
                       'bkToggle.setAttribute("aria-expanded", open?"true":"false");',
                       'bkToggle.setAttribute("aria-expandedX", open?"true":"false");'))
    red("گزینه‌ها بیرونِ بدنه‌ی کرکره رها شده‌اند (جمع نمی‌شوند)",
        "بیرونِ بدنه‌ی کرکره",
        lambda d: edit(d, "app.py", '    <div class="bk-body" id="bkBody">',
                       '    <div id="abList"></div>\n    <div class="bk-body" id="bkBody">'))
    red("خلاصه‌ی وضعیتِ پشتیبان در نوار پر نمی‌شود (JS)",
        "خلاصه‌ی وضعیتِ پشتیبان",
        lambda d: edit(d, "app.py", 'document.getElementById("bkState")',
                       'document.getElementById("bkStateX")', expect=2))
    red("جایِ خلاصه‌ی وضعیت از نوار برداشته شده (مارک‌آپ)",
        "خلاصه‌ی وضعیتِ پشتیبان",
        lambda d: edit(d, "app.py", 'id="bkState"', 'id="bkStateX"'))

    # بی‌گناه‌ها: نباید قرمز شوند
    green("عوض‌کردنِ گلیفِ فلشِ کرکره سبز می‌مانَد",
          lambda d: edit(d, "app.py", '<span class="arr" aria-hidden="true">▾</span>',
                         '<span class="arr" aria-hidden="true">⌄</span>'),
          "wired")
    green("افزودنِ یک کلاسِ نمایشیِ اضافه به بدنه سبز می‌مانَد",
          lambda d: edit(d, "app.py", '<div class="bk-body" id="bkBody">',
                         '<div class="bk-body bk-body-lead" id="bkBody">'),
          "options_inside")
    green("تنظیمِ فاصله‌ی داخلیِ بدنه سبز می‌مانَد",
          lambda d: edit(d, "app.py", ".bk-body{display:none;padding:0 18px 16px;",
                         ".bk-body{display:none;padding:0 22px 18px;"),
          "collapsed")
    green("ویرایشِ متنِ توضیحِ داخلِ بدنه سبز می‌مانَد",
          lambda d: edit(d, "app.py", "در پس‌زمینه کار می‌کند.</p>",
                         "در پس‌زمینه کار می‌کند (بی‌سروصدا).</p>"),
          "state")

# ── جمع‌بندی ──
print("\n• بررسی‌ها: %d" % len(CHECKS))
if FAILS:
    for name, detail in FAILS:
        print("::error::❌ %s — %s" % (name, detail[:220]))
    print("\n❌ آزمونِ «کرکره‌ی پشتیبان» رد شد — %d از %d بررسی شکست خورد"
          % (len(FAILS), len(CHECKS)))
    sys.exit(1)
print("✅ آزمونِ «کرکره‌ی پشتیبان: جمعِ پیش‌فرض» پاس شد — بدنه پیش‌فرض بسته، نوار "
      "کلیدپذیر با aria، گزینه‌ها داخلِ بدنه، و خلاصه‌ی وضعیت روی نوار همه قفل‌اند")
