#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""آزمونِ لایه‌ی ۴.۲۱ — «پنجرهٔ گذشتهٔ فید + بجِ زندهٔ اعلام» (خواسته‌ی کاربر).

خواسته: «بجِ «N دقیقه پیش» کارت‌های اعلام‌شده را بدونِ رفرشِ کلِ صفحه زنده کن و
پنجرهٔ رویدادهای گذشته را با یک انتخابگر مثل ۶/۱۲/۲۴ ساعت قابلِ تنظیم کن.»

منطق: فید دو نوع کارت دارد؛ کارتِ اعلام‌شده باید بگوید «چند دقیقه از اعلام
گذشته» و این عدد نباید پشتِ یک بازخوانیِ کاملِ صفحه بماند (کاربر باید بداند
عدد تازه است و صفحه هم نباید مثلِ رفرش تکان بخورد). پنجرهٔ گذشته هم نباید یک
عددِ سخت‌کدِ پنهان باشد: کاربر ۶/۱۲/۲۴ ساعت را انتخاب می‌کند و همان مقدار —
سقف‌دار و قطعی‌شده — باید به سرور برسد.

سه بخش:
  ۱) قاعده‌ی نگهبانِ `selfcheck.feed_window_problems` روی مخزنِ سالم صفر خطا
     می‌دهد و همه‌ی بندهایش سبز است.
  ۱.۵) سنجشِ استاتیکِ منطقه: قطعی‌سازیِ `past_window`، عبورِ `?past=` تا
     `build_feed`، انتخابگرِ ۶/۱۲/۲۴، تیکِ سبکِ بج (بی‌`load()`/`render()`)،
     مبنای `T0`/`data-m` و حفظِ کارتِ باز.
  ۲) جهش‌آزمایی: شکستنِ هر حلقه باید نام‌دار قرمز شود؛ ویرایش‌های بی‌گناه سبز.
  ۳) رفتارِ خالص: `past_window` روی ورودی‌های مرزی، و پنجرهٔ ۶/۱۲/۲۴ روی
     تقویمِ ساختگی (رویدادِ ۸ ساعتِ پیش در پنجرهٔ ۶ نمی‌آید، در ۱۲ می‌آید).

آفلاین است (فقط متنِ کد + تقویمِ ساختگی؛ شبکه‌ای در کار نیست).
PF_FEEDWIN_NO_MUT=1 بخشِ جهش را رد می‌کند (فرارِ سریعِ CI محدود).
"""
import datetime
import io
import os
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
    d = tempfile.mkdtemp(prefix="pf_feedwin_")
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
    return SC.feed_window_problems(d, SC.page_sources(d))


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


NO_MUT = os.environ.get("PF_FEEDWIN_NO_MUT") == "1"

# ═══ ۱) قاعده روی مخزنِ سالم ═══
print("═══ ۱) قاعدهٔ نگهبان روی مخزنِ سالم ═══")
p0, s0 = scan(HERE)
check("قاعده: مخزنِ سالم صفر خطا", p0 == [], str(p0)[:300])
check("قاعده: پنجره‌های مجازِ گذشته سبز", s0.get("windows") is True, str(s0))
check("قاعده: قطعی‌سازیِ past_window سبز",
      s0.get("fn") is True and s0.get("norm") is True, str(s0))
check("قاعده: مرزِ خاموشِ صفر (قراردادِ دورِ ۷) سبز", s0.get("off") is True, str(s0))
check("قاعده: build_feed پنجره را از past_window می‌گیرد", s0.get("feed") is True, str(s0))
check("قاعده: build پنجره را قطعی می‌کند و در پاسخ بازمی‌گرداند",
      s0.get("build") is True and s0.get("echo") is True, str(s0))
check("قاعده: مسیرِ API پارامترِ past را می‌خواند", s0.get("route") is True, str(s0))
check("قاعده: انتخابگرِ ۶/۱۲/۲۴ در رابط هست",
      s0.get("seg") is True and s0.get("seg_btns") == 3, str(s0))
check("قاعده: حالتِ pastHours به درخواست وصل است",
      s0.get("state") is True and s0.get("fetch") is True, str(s0))
check("قاعده: تیکِ زندهٔ بج هست و سبک است",
      s0.get("tick") is True and s0.get("tick_lean") is True, str(s0))
check("قاعده: مبنای دقیقه‌ها (‏data-m + زمان‌بند + T0) سبز",
      s0.get("datam") is True and s0.get("loop") is True and s0.get("t0") is True, str(s0))
check("قاعده: بارِ اول بی‌خالیِ فهرست سبز", s0.get("firstload") is True, str(s0))
check("قاعده: حفظِ کارتِ بازِ کاربر سبز", s0.get("keep") is True, str(s0))

# ═══ ۱.۵) سنجشِ استاتیکِ منطقهٔ پنجره/بج ═══
print("═══ ۱.۵) منطقهٔ پنجرهٔ گذشته و بجِ زنده ═══")
_fsrc = io.open(os.path.join(HERE, "fundamental.py"), encoding="utf-8").read()
_asrc = io.open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
_fund = (SC.page_sources(HERE) or {}).get("FUND_PAGE") or ""
check("استاتیک: پنجره‌ها ۶/۱۲/۲۴ اعلام شده", "PAST_WINDOWS = (6, 12, 24)" in _fsrc, "")
_wreg = SC._py_region(_fsrc, "def past_window", "\ndef _feed_past_event")
check("استاتیک: past_window ورودیِ ناخوانا را به مجازِ اول برمی‌گرداند",
      "return PAST_WINDOWS[0]" in _wreg and "except Exception" in _wreg, _wreg[:200])
check("استاتیک: مرزِ خاموشِ صفر در past_window هست",
      "if n <= 0:" in _wreg and "return 0" in _wreg, _wreg[:200])
_bfreg = SC._py_region(_fsrc, "def build_feed", "_VERDICT_SKIP_TOKENS")
check("استاتیک: کفِ پنجره با past_window ساخته می‌شود",
      "hours=past_window(past_hours)" in _bfreg, _bfreg[:200])
_breg = SC._py_region(_fsrc, "def build(", "\nif __name__")
check("استاتیک: build پنجرهٔ مؤثر را در پاسخ می‌فرستد",
      '"past_hours": past_hours' in _breg, _breg[:200])
_rreg = SC._py_region(_asrc, 'if u.path == "/api/fundamental":', 'if u.path == "/fundamental":')
check("استاتیک: مسیرِ فاندمنتال پارامترِ past را به build می‌دهد",
      'get("past",' in _rreg and "past_hours=past_hours" in _rreg, _rreg[:200])
check("استاتیک: انتخابگرِ گذشته در نمای فید هست", 'id="pastSeg"' in _fund, "")
check("استاتیک: سه گزینهٔ ۶/۱۲/۲۴ در انتخابگر هست",
      len(set(SC._FW_SEG_BTN_RE.findall(_fund))) == 3, "")
check("استاتیک: درخواستِ فید پارامترِ گذشته را می‌فرستد",
      '"&past="+pastHours' in _fund, "")
_treg = SC._py_region(_fund, "function tickBadges(", "\nasync function load(){")
check("استاتیک: بدنهٔ tickBadges پیدا شد", bool(_treg), "")
check("استاتیک: تیکِ بج فهرست را دوباره نمی‌سازد/نمی‌خواند",
      bool(_treg) and "load()" not in _treg and "render()" not in _treg
      and "fetch(" not in _treg, _treg[:200])
check("استاتیک: تیک فقط کارت‌های اعلام‌شدهٔ عدددار را می‌گیرد",
      '#list .cd-badge.past[data-m]' in _treg, _treg[:200])
check("استاتیک: دقیقه‌ها از T0 (لحظهٔ خواندنِ فید) شمرده می‌شود",
      "Date.now()-T0" in _treg, _treg[:200])
check("استاتیک: minutes_ago سرور روی بج می‌نشیند", 'data-m="${e.minutes_ago}"' in _fund, "")
check("استاتیک: زمان‌بندِ تیکِ بج هست", "setInterval(tickBadges," in _fund, "")
check("استاتیک: T0 در خواندنِ فید به‌روز می‌شود",
      "T0=Date.now();" in _fund and "let pastHours=6, T0=Date.now()" in _fund, "")
check("استاتیک: کارتِ بازِ کاربر در رندرِ دوره‌ای حفظ می‌شود",
      "openKeys.has(evKey(e))" in _fund and "openKeys.add(" in _fund, "")
check("استاتیک: فهرست فقط در بارِ اول جای‌گیرِ بارگذاری می‌گیرد",
      "if(!DATA) $(\"#list\")" in _fund, "")

# ═══ ۲) جهش‌آزماییِ قاعده ═══
if not NO_MUT:
    print("═══ ۲) جهش‌آزماییِ قاعده (قرمز/بی‌گناه) ═══")
    red("پنجره‌های مجازِ گذشته حذف شده",
        "بی‌سقف",
        lambda d: edit(d, "fundamental.py", "PAST_WINDOWS = (6, 12, 24)",
                       "PAST_WINDOWS = (6,)"))
    red("past_window از کد رفته",
        "حذف شده",
        lambda d: edit(d, "fundamental.py", "def past_window(v):",
                       "def past_window_gone(v):"))
    red("پنجرهٔ نامعتبر قطعی نمی‌شود",
        "نزدیک‌ترین پنجرهٔ مجاز",
        lambda d: edit(d, "fundamental.py",
                       "    return min(PAST_WINDOWS, key=lambda w: (abs(w - n), w))",
                       "    return n"))
    red("صفر دیگر «خاموش» نیست (قراردادِ پنجرهٔ صفر عوض شده)",
        "«خاموش» نیست",
        lambda d: edit(d, "fundamental.py",
                       "    if n <= 0:\n        return 0\n", ""))
    red("build_feed پنجره را از past_window نمی‌گیرد",
        "نمی‌گیرد",
        lambda d: edit(d, "fundamental.py", "hours=past_window(past_hours)",
                       "hours=max(0, int(past_hours))"))
    red("build پنجره را قطعی نمی‌کند",
        "قطعی نمی‌کند",
        # لنگر عمداً سرِ `build` را هم دارد؛ در `one_event` هم همین خط هست.
        lambda d: edit(d, "fundamental.py",
                       "def build(hours=180, past_hours=6):\n    past_hours = past_window(past_hours)\n",
                       "def build(hours=180, past_hours=6):\n"))
    red("پنجرهٔ مؤثر در پاسخ نمی‌آید",
        "نمی‌آید",
        # لنگر باید مخصوصِ `build` باشد؛ در پاسخِ تک‌رویداد هم همین کلید هست.
        lambda d: edit(d, "fundamental.py",
                       '        "count_past": len(passed),\n        "past_hours": past_hours,\n',
                       '        "count_past": len(passed),\n'))
    red("مسیرِ API پارامترِ past را نمی‌خواند",
        "را نمی‌خواند",
        lambda d: edit(d, "app.py", "FUND.build(hours=hours, past_hours=past_hours)",
                       "FUND.build(hours=hours)"))
    red("انتخابگرِ گذشته از رابط حذف شده",
        "انتخابگرِ «گذشته»",
        lambda d: edit(d, "app.py", 'id="pastSeg"', 'id="pastSegGone"'))
    red("حالتِ pastHours از رابط حذف شده",
        "حالتِ `pastHours`",
        lambda d: edit(d, "app.py", "let pastHours=6,", "let pastHours=24,"))
    red("انتخابگرِ گذشته به درخواست وصل نیست",
        "نمی‌فرستد",
        lambda d: edit(d, "app.py", '+"&past="+pastHours', '+""'))
    red("تابعِ تیکِ زندهٔ بج حذف شده",
        "زنده‌سازیِ بج",
        lambda d: edit(d, "app.py", "function tickBadges(){",
                       "function tickBadgesGone(){"))
    red("تیکِ بج به بازخوانیِ کامل برگشته",
        "دوباره می‌سازد",
        lambda d: edit(d, "app.py", "function tickBadges(){\n  const ms=",
                       "function tickBadges(){\n  load();\n  const ms="))
    red("تیکِ بج کارت‌های عدددار را هدف نمی‌گیرد",
        "هدف نمی‌گیرد",
        lambda d: edit(d, "app.py", '"#list .cd-badge.past[data-m]"',
                       '"#list .cd-badge"'))
    red("تیکِ بج به زمانِ خواندنِ فید گره نخورده",
        "گره",
        lambda d: edit(d, "app.py", "const ms=Date.now()-T0, mins=Math.floor(ms/60000);",
                       "const ms=0, mins=Math.floor(ms/60000);"))
    red("minutes_ago سرور روی بج نمی‌نشیند",
        "نمی‌نشیند",
        lambda d: edit(d, "app.py", ' data-m="${e.minutes_ago}"', ' data-mx="${e.minutes_ago}"'))
    red("زمان‌بندِ تیکِ بج برداشته شده",
        "زمان‌بندِ تیکِ بج",
        lambda d: edit(d, "app.py", "setInterval(tickBadges, 30000);",
                       "setInterval(()=>0, 30000);"))
    red("T0 در خواندنِ فید به‌روز نمی‌شود",
        "به‌روز نمی‌شود",
        lambda d: edit(d, "app.py", "    T0=Date.now();\n    render();", "    render();"))
    red("کارتِ بازِ کاربر در رندرِ دوره‌ای حفظ نمی‌شود",
        "حفظ نمی‌شود",
        lambda d: edit(d, "app.py", "openKeys.has(evKey(e))", "false"))
    red("جای‌گیرِ بارگذاری در هر بازخوانی فهرست را خالی می‌کند",
        "بازخوانی فهرست را خالی",
        lambda d: edit(d, "app.py",
                       'if(!DATA) $("#list").innerHTML=\'<div class="empty">در حالِ بارگذاریِ تقویم…</div>\';',
                       '$("#list").innerHTML=\'<div class="empty">در حالِ بارگذاریِ تقویم…</div>\';'))

    # بی‌گناه‌ها: نباید قرمز شوند
    d = copy_repo()
    try:
        edit(d, "fundamental.py", "    if n in PAST_WINDOWS:",
             "    if n == 6 or n == 12 or n == 24:")
        probs, st = scan(d)
        check("بی‌گناه: هم‌معنیِ شرطِ مجاز سبز می‌مانَد",
              probs == [] and st.get("norm") is True, str(probs)[:200])
    finally:
        drop(d)
    d = copy_repo()
    try:
        edit(d, "app.py", ' data-m="${e.minutes_ago}"',
             ' data-m="${e.minutes_ago}" data-live="1"')
        probs, st = scan(d)
        check("بی‌گناه: ویژگیِ نمایشیِ تازه روی بج سبز می‌مانَد",
              probs == [] and st.get("datam") is True, str(probs)[:200])
    finally:
        drop(d)
    d = copy_repo()
    try:
        edit(d, "app.py", "setInterval(tickBadges, 30000);", "setInterval(tickBadges, 20000);")
        probs, st = scan(d)
        check("بی‌گناه: کوتاه‌کردنِ فاصلهٔ تیک سبز می‌مانَد",
              probs == [] and st.get("loop") is True, str(probs)[:200])
    finally:
        drop(d)
    d = copy_repo()
    try:
        edit(d, "app.py", 'title="چند ساعت از خبرهای اعلام‌شده در فید بماند"',
             'title="پنجرهٔ گذشتهٔ فید" style="margin-inline-start:4px"')
        probs, st = scan(d)
        check("بی‌گناه: تغییرِ عنوانِ انتخابگر سبز می‌مانَد",
              probs == [] and st.get("seg") is True, str(probs)[:200])
    finally:
        drop(d)

# ═══ ۳) رفتارِ خالص (بندِ پنجره — بدونِ شبکه) ═══
print("═══ ۳) رفتارِ خالصِ پنجرهٔ گذشته (بدونِ شبکه) ═══")
import fundamental as F  # noqa: E402

TAB = [(6, 6), (12, 12), (24, 24), (8, 6), (18, 12), (30, 24), (999, 24), (6.7, 6),
       ("abc", 6), (None, 6), ("12", 12)]
# صفر/منفی = «خاموش» (قراردادِ دورِ ۷، دست‌نخورده): بدونِ رویدادِ گذشته.
OFF = [(0, 0), (-3, 0)]
bad = [v for v, want in TAB + OFF if F.past_window(v) != want]
check("رفتار: past_window جدولِ مرزی را درست قطعی می‌کند", bad == [], str(bad))
check("رفتار: صفر/منفی = خاموش (پنجرهٔ گذشتهٔ صفر، نه کمینهٔ ۶)",
      F.past_window(0) == 0 and F.past_window(-3) == 0,
      str((F.past_window(0), F.past_window(-3))))
check("رفتار: پنجره‌های مجاز همان ۶/۱۲/۲۴ است", tuple(F.PAST_WINDOWS) == (6, 12, 24),
      str(F.PAST_WINDOWS))

NOW = datetime.datetime.now(datetime.timezone.utc)
_OLD_DT = NOW - datetime.timedelta(hours=8)     # فقط در پنجرهٔ ۱۲/۲۴ دیده می‌شود
_ONE_DT = NOW - datetime.timedelta(hours=1)     # در همهٔ پنجره‌ها
_NEXT_DT = NOW + datetime.timedelta(hours=3)

CAL = [
    {"impact": "High", "date": _OLD_DT.isoformat(), "title": "ISM Manufacturing PMI",
     "country": "USD", "forecast": "50.0", "previous": "49.5"},
    {"impact": "High", "date": _ONE_DT.isoformat(), "title": "Non-Farm Payrolls",
     "country": "USD", "forecast": "180K", "previous": "175K"},
    {"impact": "High", "date": _NEXT_DT.isoformat(), "title": "ECB Press Conference",
     "country": "EUR", "forecast": "", "previous": ""},
]
ROWS = [{"ccy": "USD", "date": _ONE_DT.astimezone(datetime.timezone.utc).date().isoformat(),
         "minute": _ONE_DT.hour * 60 + _ONE_DT.minute, "event": "non-farm payrolls",
         "actual": "195K"}]


class _FakeM:
    def __init__(self, rows):
        self.rows = rows

    def get_calendar(self):
        return list(CAL)

    def get_actuals(self, *a, **k):
        return list(self.rows)


_orig = F.M
F.M = _FakeM(ROWS)
try:
    feed6 = F.build_feed(hours=24, past_hours=6)
    past6 = [e for e in feed6 if e.get("passed")]
    check("رفتار: پنجرهٔ ۶ ساعته رویدادِ ۸ ساعتِ پیش را نمی‌آورد",
          len(past6) == 1 and all("ISM" not in (e.get("title") or "") for e in past6),
          str([e.get("title") for e in past6]))

    feed12 = F.build_feed(hours=24, past_hours=12)
    past12 = [e for e in feed12 if e.get("passed")]
    check("رفتار: پنجرهٔ ۱۲ ساعته رویدادِ ۸ ساعتِ پیش را می‌آورد",
          len(past12) == 2, str([e.get("title") for e in past12]))
    old = next((e for e in past12 if "ISM" in (e.get("title") or "")), {})
    check("رفتار: رویدادِ پنجرهٔ بزرگ‌تر باز هم passed + بی‌analysis است",
          old.get("passed") is True and "analysis" not in old, str(old)[:200])
    check("رفتار: «دقیقه‌ها از اعلام» برای رویدادِ ۸ ساعته بزرگ است",
          isinstance(old.get("minutes_ago"), int) and old["minutes_ago"] >= 470,
          str(old.get("minutes_ago")))

    rep12 = F.build(hours=24, past_hours=12)
    check("رفتار: پاسخِ build پنجرهٔ مؤثر را می‌گوید", rep12.get("past_hours") == 12,
          str(rep12.get("past_hours")))
    check("رفتار: count_past با پنجرهٔ ۱۲ دو رویداد است", rep12.get("count_past") == 2,
          str(rep12.get("count_past")))
    check("رفتار: منبعِ Actual سالم ⇒ source_ok=True", rep12.get("source_ok") is True,
          str(rep12.get("source_ok")))

    rep24 = F.build(hours=24, past_hours=999)
    check("رفتار: پنجرهٔ ۹۹۹ به سقفِ ۲۴ قطعی می‌شود", rep24.get("past_hours") == 24,
          str(rep24.get("past_hours")))

    repbad = F.build(hours=24, past_hours="abc")
    check("رفتار: ورودیِ ناخوانا ⇒ پنجرهٔ پیش‌فرضِ ۶",
          repbad.get("past_hours") == 6, str(repbad.get("past_hours")))
    check("رفتار: در پنجرهٔ ۶ رویدادِ ۸ ساعته در فید نیست",
          all("ISM" not in (e.get("title") or "") for e in repbad.get("events") or []), "")

    rep0 = F.build(hours=24, past_hours=0)
    check("رفتار: پنجرهٔ ۰ (خاموش) در پاسخ هم ۰ می‌مانَد و گذشته‌ای ندارد",
          rep0.get("past_hours") == 0 and rep0.get("count_past") == 0,
          str((rep0.get("past_hours"), rep0.get("count_past"))))
    check("رفتار: در حالتِ خاموش، رویدادِ پیشِ‌رو و سناریوهایش سرِ جایشان‌اند",
          any(not e.get("passed") and "analysis" in e for e in rep0.get("events") or []),
          str([e.get("title") for e in rep0.get("events") or []]))
finally:
    F.M = _orig

# ── جمع‌بندی ──
print("\n• بررسی‌ها: %d" % len(CHECKS))
if FAILS:
    for name, detail in FAILS:
        print("::error::❌ %s — %s" % (name, detail[:220]))
    print("\n❌ آزمونِ «پنجرهٔ گذشتهٔ فید + بجِ زندهٔ اعلام» رد شد — %d از %d بررسی "
          "شکست خورد" % (len(FAILS), len(CHECKS)))
    sys.exit(1)
print("✅ آزمونِ «پنجرهٔ گذشتهٔ فید + بجِ زندهٔ اعلام» پاس شد — پنجرهٔ ۶/۱۲/۲۴ از "
      "انتخابگر تا سرور قطعی می‌شود و «N دقیقه پیش» با تیکِ سبکِ سمتِ کاربر زنده "
      "می‌مانَد (بی‌رفرشِ فهرست، بی‌کارتِ بسته‌شده)")
