#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""آزمونِ لایهٔ ۴.۲۴ — «گپ‌بان» (هشدارِ خودکارِ تولدِ گپِ قابلِ اتکا).

خواستهٔ کاربر: «هشدار بده وقتی روی نمادهای تحتِ نظارت یک گپِ تازه با نمرهٔ A+ یا A
ساخته می‌شود، بدونِ اینکه کاربر پرسشی بفرستد.» یعنی همان موتورِ پرسشِ گپ باید
خودش دوره‌ای بپرسد؛ این لایه چهار چیز را قفل می‌کند:

  ۱) **دورِ اول بی‌صدا** پایه‌گذاری می‌کند و پایه‌گذاری از *همهٔ* گپ‌های پویش‌شده
     است (نه فقط A+/A) — وگرنه لحظهٔ ثبتِ نظارت کاربر سیلیِ نوتیف می‌گیرد و گپِ B
     که بعداً A+ می‌شود «تولد» شمرده می‌شود و هشدارِ دروغ می‌رود.
  ۲) **فقط تولدِ گپِ A+/A** هشدار دارد؛ درجه‌ها از خودِ موتور (`RELIABLE_GRADES`)
     خوانده می‌شوند، نه یک فهرستِ موازی که روزی از حکمِ اپ جدا می‌افتد.
  ۳) **ذخیره پیش از نوتیف** است (هشدارِ گم‌شده بهتر از هشدارِ تکراریِ هر دور) و
     سقفِ تاریخچه نمی‌گذارد فایلِ آلارم‌ها بی‌مرز رشد کند.
  ۴) اندپوینت `mode:"gap"` را می‌پذیرد، تایم‌فریم را با نردبانِ موتور می‌سنجد و
     نظارتِ تکراری روی یک نماد/تایم‌فریم را رد می‌کند؛ رابط هم کنترلِ ثبت و
     رندرِ نظارت‌ها (با کلیدِ حذف) دارد.

سه بخش: (۱) قاعدهٔ نگهبان روی مخزنِ سالم + زنجیرهٔ استاتیک، (۲) جهش‌آزمایی
(سرخِ نام‌دار روی app.py + بی‌گناه‌ها + دو جهشِ رفتاری)، (۳) رفتارِ خالصِ تصمیمِ
گپ‌بان — کاملاً آفلاین و قطعی (هیچ شبکه‌ای زده نمی‌شود).

اجرا:  python3 gap_alert_test.py        (خروجی ۰ = سالم)
PF_GAPALERT_NO_MUT=1 بخشِ جهش را رد می‌کند (فرارِ سریعِ CI محدود).
"""
import io
import os
import shutil
import subprocess
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


APP_PATH = os.path.join(HERE, "app.py")
SOURCE = io.open(APP_PATH, encoding="utf-8").read()


def copy_repo():
    d = tempfile.mkdtemp(prefix="pf_gapalert_")
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
                             % (name, n, old[:70]))
    io.open(p, "w", encoding="utf-8").write(txt.replace(old, new, 1))


def scan(d):
    return SC.gap_alert_problems(d, SC.page_sources(d))


def red(name, needle, mutate):
    """جهش باید قاعده را قرمز کند و پیام باید «سوزن» را داشته باشد (نام‌دار)."""
    d = copy_repo()
    try:
        mutate(d)
        probs, _ = scan(d)
        check("قرمز: " + name, any(needle in p for p in probs),
              "قاعده سبز ماند یا پیامِ نام‌دار نداشت! probs=" + str(probs)[:300])
    finally:
        drop(d)


def green(name, mutate, expect=None):
    """بی‌گناه: تغییرِ مجاز نباید قاعده را قرمز کند (اخطارِ دروغ = بازگردانیِ بی‌دلیل)."""
    d = copy_repo()
    try:
        mutate(d)
        probs, st = scan(d)
        ok = probs == [] and (expect is None or expect(st))
        check("بی‌گناه: " + name, ok,
              "probs=" + str(probs)[:250] + " stats=" + str(st)[:150])
    finally:
        drop(d)


# ═══ ۱) قاعدهٔ نگهبان روی مخزنِ سالم ═══
print("═══ ۱) قاعدهٔ نگهبان روی مخزنِ سالم ═══")
p0, s0 = scan(HERE)
check("قاعده: مخزنِ سالم صفر خطا", p0 == [], str(p0)[:300])
check("قاعده: گامِ پویشِ معقول", s0.get("interval") is True, str(s0))
check("قاعده: سقفِ تاریخچهٔ هشدارها", s0.get("hits_cap") is True, str(s0))
check("قاعده: درجه‌ها از موتور می‌آیند", s0.get("grades_from_engine") is True, str(s0))
check("قاعده: دورِ اول بی‌صدا پایه‌گذاری می‌کند", s0.get("silent_seed") is True, str(s0))
check("قاعده: پایه‌گذاری از همهٔ گپ‌ها است", s0.get("seed_all") is True, str(s0))
check("قاعده: فقط تولدِ گپِ قابلِ اتکا هشدار دارد", s0.get("birth_only") is True, str(s0))
check("قاعده: ذخیره پیش از نوتیف", s0.get("save_first") is True, str(s0))
check("قاعده: کارگرِ گپ‌بان ثبت شده", s0.get("worker") is True, str(s0))
check("قاعده: اندپوینتِ نظارتِ گپ کامل است", s0.get("route") is True, str(s0))
check("قاعده: کنترل + رندرِ رابط", s0.get("ui") == 2, str(s0))

# ═══ ۱.۵) زنجیرهٔ استاتیک (ثابت‌ها → تصمیم → پویش → کارگر → اندپوینت → رابط) ═══
print("═══ ۱.۵) زنجیرهٔ استاتیکِ گپ‌بان ═══")
_page = (SC.page_sources(HERE) or {}).get("HTML") or ""
_decide = SC._py_region(SOURCE, "def gap_watch_decide(", "def _gap_watch_once(")
_once = SC._py_region(SOURCE, "def _gap_watch_once(", "def _gap_watch_worker(")
_worker = SC._py_region(SOURCE, "def _gap_watch_worker(", "def start_gap_watch_worker(")
_route = SC._py_region(SOURCE, 'if u.path == "/api/alarm":', 'if u.path != "/api/journal":')
_list_fn = SC._py_region(_page, "async function loadAlarms(", "loadAlarms();")

_iv = SC._GA_INTERVAL_RE.search(SOURCE)
check("ثابت: GAP_WATCH_INTERVAL در بازهٔ ۶۰..۳۶۰۰",
      _iv is not None and 60 <= int(_iv.group(1)) <= 3600, str(_iv.group(1) if _iv else None))
check("ثابت: سقفِ تاریخچه هم تعریف و هم استفاده شده",
      SC._GA_HITS_CAP_RE.search(SOURCE) is not None
      and SC._GA_HITS_USE_RE.search(SOURCE) is not None, "")
_gfn = SC._py_region(SOURCE, "def _gapwatch_grades(", "def _gap_key(")
check("موتور: درجه‌ها از G.RELIABLE_GRADES خوانده می‌شوند",
      SC._GA_GRADES_RE.search(_gfn) is not None, _gfn[:120])
i_seed = _decide.find("if not seeded")
_mret = SC._GA_SEED_RET_RE.search(_decide[i_seed:i_seed + 400] if i_seed >= 0 else "")
check("تصمیم: شاخهٔ پایه‌گذاریِ بی‌صدا وجود دارد و fresh خالی برمی‌گرداند",
      i_seed >= 0 and _mret is not None and "[]" in _mret.group(0),
      (_mret.group(0) if _mret else "—"))
_mc = SC._GA_DECIDE_CALL_RE.search(_once)
check("پویش: پایه‌گذاری با همهٔ کلیدها (all_keys) صدا زده می‌شود",
      _mc is not None and _mc.group(1) == "all_keys", str(_mc.group(1) if _mc else None))
check("پویش: فیلترِ درجه روی خروجیِ موتور است",
      SC._GA_FILTER_RE.search(_once) is not None, "")
check("کارگر: ذخیره پیش از نوتیف است",
      _worker.find("_save_alarms(cur)") < _worker.find("_notify_mac(")
      and _worker.find("_save_alarms(cur)") >= 0, "")
check("کارگر: رشته و ثبتِ راه‌اندازی هست",
      SC._GA_DEF_RE.search(SOURCE) is not None
      and SC._GA_THREAD_RE.search(SOURCE) is not None
      and SC._GA_START_RE.search(SOURCE) is not None, "")
check("اندپوینت: شاخهٔ gap + اعتبارسنجیِ نردبانِ تایم‌فریم + ردِ نظارتِ تکراری",
      'mode == "gap"' in _route and SC._GA_ROUTE_TF_RE.search(_route) is not None
      and SC._GA_ROUTE_DUP_RE.search(_route) is not None, "")
check("رابط: کنترلِ گپ‌بان و اتصالش هست",
      SC._GA_UI_BTN_RE.search(_page) is not None
      and SC._GA_UI_WIRE_RE.search(_page) is not None
      and SC._GA_UI_FN_RE.search(_page) is not None, "")
check("رابط: فهرستِ آلارم‌ها نظارت‌های گپ را با کلیدِ حذف رندر می‌کند",
      SC._GA_LIST_GAP_RE.search(_list_fn) is not None
      and all(x in _list_fn for x in SC._GA_LIST_MARKS)
      and 'class="adel"' in _list_fn, "")

# ═══ ۲) جهش‌آزمایی ═══
NO_MUT = os.environ.get("PF_GAPALERT_NO_MUT") == "1"

if NO_MUT:
    print("═══ ۲) جهش‌آزمایی: رد شد (PF_GAPALERT_NO_MUT=1) ═══")
else:
    print("═══ ۲) جهش‌های سرخِ نام‌دار ═══")
    red("گامِ پویش بی‌معقول (۵ ثانیه)", "گامِ پویشِ گپ‌بان",
        lambda d: edit(d, "app.py", "GAP_WATCH_INTERVAL = 300", "GAP_WATCH_INTERVAL = 5"))
    red("سقفِ تاریخچهٔ هشدارها بی‌اثر شد", "سقفِ تاریخچه",
        lambda d: edit(d, "app.py", "[-GAP_WATCH_HITS_MAX:]", "[:20]"))
    red("درجه‌ها به فهرستِ موازی تبدیل شدند", "درجه‌های هشدارِ گپ‌بان",
        lambda d: edit(d, "app.py", "return tuple(G.RELIABLE_GRADES)", 'return ("A+", "A")'))
    red("دورِ اول دیگر بی‌صدا نیست", "بی‌صدا پایه‌گذاری نمی‌کند",
        lambda d: edit(d, "app.py", "return (sorted(set(cur)), [], True)",
                       "return (sorted(set(cur)), cur, True)"))
    red("پایه‌گذاری فقط از گپ‌های A+/A", "از همهٔ گپ‌های پویش‌شده نیست",
        lambda d: edit(d, "app.py",
                       "alarm.get(\"seen\"), alarm.get(\"seeded\"), all_keys, [k for k, _ in reliable])",
                       "alarm.get(\"seen\"), alarm.get(\"seeded\"), [k for k, _ in reliable], [k for k, _ in reliable])"))
    red("فیلترِ درجه از پویش افتاد (برای هر گپی هشدار)", "فیلترِ «فقط گپِ قابلِ اتکا»",
        lambda d: edit(d, "app.py", 'if v.get("grade") in grades:', "if True:"))
    red("نوتیف پیش از ذخیره رفت", "پیش از ذخیره نوتیف می‌فرستد",
        lambda d: edit(d, "app.py",
                       "                    _save_alarms(cur)\n                for h in hits:\n                    _notify_mac(",
                       "                for h in hits:\n                    _notify_mac("))
    red("کارگرِ گپ‌بان راه‌اندازی نشد", "کارگرِ گپ‌بان تعریف/رشته/ثبت نشده",
        lambda d: edit(d, "app.py", "    start_gap_watch_worker()\n", ""))
    red("تایم‌فریم بی‌اعتبارسنجی (هر رشته‌ای پذیرفته می‌شود)", "تایم‌فریم را با نردبانِ موتور",
        lambda d: edit(d, "app.py", "if tf not in G.TF_LADDER:", "if False:"))
    red("نظارتِ تکراری رد نمی‌شود (هر گپ دو نوتیف)", "نظارتِ تکراری",
        lambda d: edit(d, "app.py", '{"error": "%s %s از قبل زیرِ نظارتِ گپ است"',
                       '{"error": "%s %s ثبت شد"'))
    red("کنترلِ گپ‌بان از پنل حذف شد", "کنترلِ گپ‌بان در پنلِ گپ نیست",
        lambda d: edit(d, "app.py", '<button id="gapWatch" class="btsug"', '<button id="gapWatchX" class="btsug"'))
    red("شاخهٔ رندرِ گپ‌بان از فهرست حذف شد", "نظارت‌های گپ در فهرستِ آلارم‌ها",
        lambda d: edit(d, "app.py", 'if(a.mode==="gap"){', "if(false){"))
    red("اتصالِ دکمه به تابع برداشته شد", "کنترلِ گپ‌بان در پنلِ گپ نیست",
        lambda d: edit(d, "app.py", "if(wb) wb.onclick=pfGapWatch;", "if(wb) wb.onclick=null;"))

    print("═══ ۲.۵) جهش‌های بی‌گناه (نباید قرمز کنند) ═══")
    green("گامِ پویش ۳۰۰ → ۶۰۰ ثانیه", lambda d: edit(
        d, "app.py", "GAP_WATCH_INTERVAL = 300", "GAP_WATCH_INTERVAL = 600"))
    green("سقفِ تاریخچه ۲۰ → ۵", lambda d: edit(
        d, "app.py", "GAP_WATCH_HITS_MAX = 20", "GAP_WATCH_HITS_MAX = 5"))
    green("متنِ نوتیف عوض شد", lambda d: edit(
        d, "app.py", '"🧩 گپِ قابلِ اتکا — %s %s"', '"🔔 گپِ تازه — %s %s"'))
    green("یک کلیدِ اضافه به وصلهٔ آلارم", lambda d: edit(
        d, "app.py", '"alerts": int(alarm.get("alerts") or 0) + len(hits),',
        '"alerts": int(alarm.get("alerts") or 0) + len(hits), "note": "x",'))

    print("═══ ۲.۶) جهش‌های رفتاری (تصمیم باید بشکند، نه فقط متن) ═══")

    def red_behavior(name, mutate, script):
        d = copy_repo()
        try:
            mutate(d)
            pr = subprocess.run([sys.executable, "-c", script], cwd=d,
                                capture_output=True, text=True, timeout=120)
            check("قرمزِ رفتاری: " + name, pr.returncode != 0,
                  "رفتار سالم ماند! out=" + (pr.stdout or "")[-200:] + (pr.stderr or "")[-200:])
        finally:
            drop(d)

    SEED_SCRIPT = ("import app; s,f,se=app.gap_watch_decide([],False,['a'],['a']);"
                   "assert f==[], f")
    DEDUP_SCRIPT = ("import app;a=['a|bullish|1|2'];"
                    "s1,f1,_=app.gap_watch_decide([],False,a,a);"
                    "s2,f2,_=app.gap_watch_decide(s1,True,a,a);"
                    "assert f1==[] and f2==[], f2")

    # کنترل: همان اسکریپت‌ها روی مخزنِ سالم باید *سبز* باشند — وگرنه «قرمزِ
    # رفتاری» می‌تواند از خرابیِ خودِ زیرفرایند بیاید، نه از جهش (سبزِ دروغ).
    for _nm, _sc in (("پایه‌گذاریِ بی‌صدا", SEED_SCRIPT), ("ضدِ تکرارِ هشدار", DEDUP_SCRIPT)):
        _pr = subprocess.run([sys.executable, "-c", _sc], cwd=HERE,
                             capture_output=True, text=True, timeout=120)
        check("کنترلِ رفتاری (مخزنِ سالم): " + _nm, _pr.returncode == 0,
              ("out=" + (_pr.stdout or "")[-150:] + " err=" + (_pr.stderr or "")[-150:]))
    red_behavior("دورِ اول بی‌صدا نیست", lambda d: edit(
        d, "app.py", "return (sorted(set(cur)), [], True)",
        "return (sorted(set(cur)), cur, True)"), SEED_SCRIPT)
    red_behavior("هشدارِ تکراری در دورهای بعد", lambda d: edit(
        d, "app.py", "fresh = [k for k in rel if k not in set(seen)]",
        "fresh = list(rel)"), DEDUP_SCRIPT)

# ═══ ۳) رفتارِ خالصِ تصمیمِ گپ‌بان (بی‌شبکه) ═══
print("═══ ۳) رفتارِ خالصِ تصمیمِ گپ‌بان ═══")
import app as APP           # noqa: E402  (import امن است — شبکه فقط در analyze صدا می‌شود)
import gap_query as GQ      # noqa: E402

A, B, C = "a|bullish|1|2", "b|bearish|3|4", "c|bearish|5|6"
ALL = [A, B, C]

seen, fresh, seeded = APP.gap_watch_decide([], False, ALL, [A])
check("دورِ اول: هشدار نمی‌دهد", fresh == [], str(fresh))
check("دورِ اول: همهٔ گپ‌ها (نه فقط A+/A) پایه‌گذاری می‌شوند", sorted(seen) == sorted(ALL), str(seen))
check("دورِ اول: seeded برمی‌گردد", seeded is True, str(seeded))

D = "d|bullish|7|8"
seen2, fresh2, _ = APP.gap_watch_decide(seen, True, ALL + [D], [D])
check("تولدِ گپِ A+/A: دقیقاً همان کلید هشدار می‌گیرد", fresh2 == [D], str(fresh2))
check("تولد: کلیدِ تازه به seen اضافه می‌شود", D in seen2, str(seen2))

seen3, fresh3, _ = APP.gap_watch_decide(seen2, True, ALL + [D], [D])
check("دورِ بعد: همان گپ دوباره هشدار نمی‌گیرد", fresh3 == [], str(fresh3))
check("seen پایدار می‌مانَد (بی‌نوسان)", sorted(seen3) == sorted(seen2), str(seen3))

seen4, fresh4, _ = APP.gap_watch_decide(ALL, True, ALL, [C])
check("ارتقای درجهٔ گپِ قدیمی «تولد» نیست", fresh4 == [], str(fresh4))

seen5, _, _ = APP.gap_watch_decide(ALL, True, [A], [])
check("گپِ ناپدیدشده از seen هرس می‌شود", seen5 == [A], str(seen5))

seen6, fresh6, _ = APP.gap_watch_decide(ALL, True, [], [])
check("پویشِ خالیِ گذرا seen را پاک نمی‌کند", sorted(seen6) == sorted(ALL), str(seen6))
check("پویشِ خالی هشدار نمی‌دهد", fresh6 == [], str(fresh6))

check("درجه‌های هشدار = RELIABLE_GRADESِ موتور",
      tuple(APP._gapwatch_grades()) == tuple(GQ.RELIABLE_GRADES), str(APP._gapwatch_grades()))
check("قابلِ اتکا فقط A+/A (هرچه موتور بگوید)",
      set(APP._gapwatch_grades()) == {"A+", "A"}, str(APP._gapwatch_grades()))

g1 = {"born_ts": 111, "type": "bullish", "bottom": 1.0, "top": 2.0}
g2 = {"born_ts": 111, "type": "bullish", "bottom": 1.0, "top": 2.0}
g3 = {"born_ts": 112, "type": "bullish", "bottom": 1.0, "top": 2.0}
check("کلیدِ هویت پایدار است", APP._gap_key(g1) == APP._gap_key(g2), APP._gap_key(g1))
check("گپِ نو روی همان قیمت کلیدِ متفاوت دارد", APP._gap_key(g1) != APP._gap_key(g3),
      APP._gap_key(g3))

check("نمادِ خالی → پویش نمی‌کند (بی‌شبکه)",
      APP._gap_watch_once({"symbol": "", "tf": "15m"}) == (None, []), "")
check("تایم‌فریمِ نامعتبر → پویش نمی‌کند (بی‌شبکه)",
      APP._gap_watch_once({"symbol": "XAUUSD", "tf": "3m"}) == (None, []), "")

# ═══ جمع‌بندی ═══
print("\n═══ جمع‌بندی: %d بررسی، %d خطا ═══" % (len(CHECKS), len(FAILS)))
if FAILS:
    for name, detail in FAILS:
        print("  ✗ %s  %s" % (name, detail))
    sys.exit(1)
print("✅ همه‌ی %d بررسیِ گپ‌بان پاس شد." % len(CHECKS))
