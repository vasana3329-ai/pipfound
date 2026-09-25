#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""جهش‌آزماییِ لایه‌ی ۱ نگهبان: «تابعِ صدا زده شده ولی هیچ‌جا تعریف نشده».

چرا لازم است (یافتهٔ S2): `node --check` فقط **سینتکس** را می‌بیند. اگر تعریفِ یک
تابع پاک شود ولی فراخوانی‌هایش بمانند، سینتکس سالم است و گیتِ لایه‌ی ۱ سبز
می‌مانَد؛ صفحه هم بالا می‌آید و فقط سرِ اجرا (وقتی کاربر همان دکمه را می‌زند) با
ReferenceError بی‌صدا می‌میرد. این دقیقاً همان حالتی بود که یک‌بار مسیرهای
بستنِ کرکره‌ی نمادها را بی‌اثر کرد و چند نوبت پنهان ماند.

این تست خودِ آن چک را می‌سنجد (تستِ تست):
  ۱) روی همین مخزنِ سالم: صفر گزارش، و در عین حال واقعاً فراخوانی‌ها را شمرده
     است (ضدِ ناوَکوم بودن — چکِ بی‌اثر نباید «سبز» شمرده شود).
  ۲) جهش‌ها (حذفِ تعریف، افزودنِ فراخوانیِ ناموجود) گیتِ لایه‌ی ۱ را **قرمز**
     می‌کنند و نامِ همان تابع را گزارش می‌کنند — در هر دو صفحه (HTML و FUND_PAGE).
  ۳) جهش‌های «ظاهراً مشکوک ولی بی‌گناه» — نامِ تابع داخلِ رشته/کامنت/regex،
     متدِ شیءِ تعریف‌شده، تعریفِ بعد از استفاده (hoisting)، و تعریف در بلوکِ دیگر
     — گیت را قرمز نمی‌کنند (اخطارِ دروغ = بازگردانیِ ناخواستهٔ کدِ سالم).

کاملاً آفلاین و قطعی: هر جهش روی کپیِ موقتِ `app.py` اجرا می‌شود و به سرورِ 8787
دست نمی‌زند.

اجرا:  python3 undefined_call_test.py        (خروجی ۰ = سالم)
"""
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import selfcheck as SC          # noqa: E402

CHECKS, FAILS = [], []


def check(name, cond, detail=""):
    CHECKS.append(name)
    if not cond:
        FAILS.append((name, detail))


APP = os.path.join(HERE, "app.py")
SOURCE = open(APP, encoding="utf-8").read()

# لنگرهای جهش — اگر روزی ساختارِ app.py عوض شود، تست باید **بلند** بشکند، نه بی‌صدا سبز شود.
ANCHORS = {
    "def_closePick": "function closePick(",
    "def_bootWarn": "function pipfoundBootWarn(){",
    "def_dirClass": "function dirClass(",
    "html_head": "// نمایشِ هر خطای JS روی خودِ صفحه",
    "html_mid": 'chips.addEventListener("mouseleave", closePickSoon);',
}


# فایل‌های همراهی که اپِ واقعی در همین پوشه دارد (سرویس‌ورکر، مانیفست، آیکون‌ها).
# محیطِ جهش باید مثلِ مخزن باشد: نگهبان حالا وعده‌های سرویس‌ورکر/مانیفست را با
# فایل‌های واقعی مقابله می‌کند و در sandboxِ بره «وعدهی بی‌فایل» خطای کاذب می‌دهد.
COMPANION_ASSETS = ("sw.js", "manifest.webmanifest",
                    "icon-180.png", "icon-192.png", "icon-192-mask.png",
                    "icon-512.png", "icon-512-mask.png")


def run_mutation(text):
    """جهش را در پوشه‌ای موقت می‌گذارد و از خودِ گیتِ لایه‌ی ۱ می‌پرسد."""
    d = tempfile.mkdtemp(prefix="pf_undef_")
    try:
        for nm in COMPANION_ASSETS:
            src = os.path.join(HERE, nm)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(d, nm))
        with open(os.path.join(d, "app.py"), "w", encoding="utf-8") as f:
            f.write(text)
        pages = SC.page_sources(d)
        _, stats = SC.undefined_calls(pages)
        rep = SC.run_checks(d)
        names = sorted({m.group(1) for p in rep.get("problems") or []
                        for m in [re.search(r"«([^»]+)»", p)] if m
                        and "تعریف نشده" in p})
        return {"ok": rep["ok"], "problems": rep.get("problems") or [],
                "names": names, "stats": stats}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def mutate(**subs):
    out = SOURCE
    for needle, repl in subs.items():
        if ANCHORS[needle] not in out:
            raise SystemExit(f"❌ لنگرِ جهش پیدا نشد: {needle} → {ANCHORS[needle]!r}")
        out = out.replace(ANCHORS[needle], repl, 1)
    return out


# ═══════════════════════════════════════════════════════════════════
print("═══ ۰) لنگرهای جهش در app.py موجودند (تست نباید بی‌صدا سبز شود) ═══")
for k, v in ANCHORS.items():
    check(f"لنگرِ «{k}» در app.py هست", v in SOURCE, v)

# ═══════════════════════════════════════════════════════════════════
print("═══ ۱) مخزنِ سالم: صفر گزارش، ولی با شمردنِ واقعیِ فراخوانی‌ها ═══")
base = run_mutation(SOURCE)
check("گیتِ لایه‌ی ۱ روی کدِ سالم سبز است", base["ok"], str(base["problems"][:3]))
check("هیچ تابعِ تعریف‌نشده‌ای گزارش نمی‌شود", base["names"] == [], str(base["names"]))
check("چک واقعاً توابعِ صفحه را می‌بیند (ضدِ ناوَکوم)",
      base["stats"].get("called", 0) >= 20 and base["stats"].get("defined", 0) >= 100,
      f"defined={base['stats'].get('defined')} called={base['stats'].get('called')}")
check("دو صفحه پوشش داده شده‌اند (HTML و FUND_PAGE)",
      set(SC.page_sources(HERE)) == {"HTML", "FUND_PAGE"},
      str(sorted(SC.page_sources(HERE))))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۲) جهش‌های واقعی: گیت باید قرمز شود و نامِ همان تابع را بگوید ═══")
MUTATIONS = [
    ("حذفِ تعریفِ یک تابعِ صفحه (رگرسیونِ تاریخیِ closePick)",
     mutate(def_closePick="function closePickRenamed("), ["closePick"]),
    ("حذفِ تعریفِ یک تابعِ صفحه‌ی دوم (FUND_PAGE)",
     mutate(def_dirClass="function dirClassRenamed("), ["dirClass"]),
    ("فراخوانیِ یک نامِ ناموجود",
     mutate(def_bootWarn='function pipfoundBootWarn(){\n  undefinedGhostFn();'),
     ["undefinedGhostFn"]),
]
for label, text, expect in MUTATIONS:
    r = run_mutation(text)
    check(f"{label} → گیت قرمز می‌شود", r["ok"] is False, "گیت سبز ماند!")
    check(f"{label} → نامِ «{expect[0]}» گزارش می‌شود", r["names"] == expect,
          f"گزارش‌شده: {r['names']}")
    check(f"{label} → خودِ صفحه سالم پارس شده (جهشِ معتبر)",
          r["stats"].get("defined", 0) >= 100, str(r["stats"]))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۳) جهش‌های بی‌گناه: گیت نباید قرمز شود (اخطارِ دروغ = بازگردانیِ بی‌دلیل) ═══")
INNOCENT = [
    ("نامِ تابع داخلِ رشته، کامنت و regexِ ادبی",
     mutate(def_bootWarn='function pipfoundBootWarn(){\n'
                         '  const s="ghostInStr()"; /* ghostInComment() */\n'
                         '  const rx=/ghostInRegex\\(/; const px=s.length+rx.source.length;')),
    ("متدِ شیء و متدِ نمونه (x.foo())",
     mutate(def_bootWarn='function pipfoundBootWarn(){\n'
                         '  const o={ghostMethod(){return 1;}}; o.ghostMethod();\n'
                         '  document.querySelector("body");')),
    ("نوعِ متغیرِ خانگی: const/let/var + انتسابِ تابع و فلش",
     mutate(def_bootWarn='function pipfoundBootWarn(){\n'
                         '  const ghostA=()=>1; let ghostB=function(){return 2;};\n'
                         '  var ghostC=(a,b)=>a+b; ghostA(); ghostB(); ghostC(1,2);')),
    ("تعریفِ بعد از استفاده (hoisting) و تعریف در بلوکِ دیگرِ همان صفحه",
     mutate(html_head='deferredLater();\n' + ANCHORS["html_head"],
            html_mid='function deferredLater(){ return 1; }\n' + ANCHORS["html_mid"])),
]
for label, text in INNOCENT:
    r = run_mutation(text)
    check(f"{label} → گیت سبز می‌مانَد", r["ok"], str(r["problems"][:2]))
    check(f"{label} → هیچ نامی گزارش نمی‌شود", r["names"] == [], str(r["names"]))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۴) خودِ چک روی نسخه‌ی سالمِ اسنپ‌شات هم بی‌صدا نیست ═══")
# چک باید مستقل از مبنا کار کند: با یک پوشه‌ی خالی، خطا بدهد نه اینکه «سبز» بماند.
empty = tempfile.mkdtemp(prefix="pf_undef_empty_")
try:
    inv = SC.page_sources(empty)
    probs, stats = SC.undefined_calls(inv)
    check("پوشه‌ی بدونِ app.py → چیزی برای تحلیل نیست (نه سبزِ دروغ)",
          probs == [] and stats.get("called") == 0, str(stats))
finally:
    shutil.rmtree(empty, ignore_errors=True)

# ─────────────────────────────────────────────────────────────
print()
if FAILS:
    print(f"❌ {len(FAILS)} بررسی از {len(CHECKS)} بررسی رد شد:")
    for n, det in FAILS:
        print(f"   • {n}" + (f"  →  {det}" if det else ""))
    sys.exit(1)
print(f"✅ همه‌ی {len(CHECKS)} بررسیِ جهش‌آزماییِ «تابعِ تعریف‌نشده» سبز شد.")
sys.exit(0)
