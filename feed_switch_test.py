#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""آزمونِ لایه‌ی ۴.۲۰ — «سوییچِ خودکارِ فید بعد از اعلامِ عدد» (خواسته‌ی کاربر).

خواسته: «فیدِ خبرهای پیش‌رو را طوری کن که بعد از اعلامِ عدد، خودکار از گزارهٔ
شرطی به «نتیجه + تأثیرِ محقق» سوییچ کند — نه دو سناریوی همیشگی.»

منطق: فید تا لحظهٔ اعلامِ خبر دو سناریو دارد (هنوز عددی نیست؛ «اگر…» تنها
حرفِ درست است). از لحظهٔ اعلام، همان کارت باید به «نتیجه + تأثیرِ همان نتیجه»
سوییچ کند؛ ماندنِ «اگر بالاتر شد…» روی خبری که عددش آمده، همان شکایتِ قدیمیِ
کاربر است — فقط این بار در فید، نه آرشیو.

سه بخش:
  ۱) قاعده‌ی نگهبانِ `selfcheck.feed_switch_problems` روی مخزنِ سالم صفر خطا
     می‌دهد و منطقهٔ سنجش سبز است.
  ۲) جهش‌آزمایی: شکستنِ هر حلقه (سازندهٔ رویدادِ گذشته → تزریقِ حکم → رندرِ
     نتیجه به‌جای سناریو → صداقتِ انتظار) باید نام‌دار قرمز شود؛ بی‌گناه‌ها سبز.
  ۳) رفتارِ خالص: `build_feed`/`build` با تقویمِ ساختگی (بدونِ شبکه) —
     رویدادِ گذشته `passed` + `verdict` + **بی‌`analysis`**؛ رویدادِ پیشِ‌رو دو
     سناریو؛ «نزدیک‌ترین خبرِ پرتأثیر» فقط پیشِ‌رو؛ `past_hours=0` تمیز.

آفلاین است (فقط متنِ کد + تقویمِ ساختگی؛ شبکه‌ای در کار نیست).
PF_FEED_NO_MUT=1 بخشِ جهش را رد می‌کند (فرارِ سریعِ CI محدود).
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
    d = tempfile.mkdtemp(prefix="pf_feed_")
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
    return SC.feed_switch_problems(d, SC.page_sources(d))


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


NO_MUT = os.environ.get("PF_FEED_NO_MUT") == "1"

# ═══ ۱) قاعده روی مخزنِ سالم ═══
print("═══ ۱) قاعدهٔ نگهبان روی مخزنِ سالم ═══")
p0, s0 = scan(HERE)
check("قاعده: مخزنِ سالم صفر خطا", p0 == [], str(p0)[:300])
check("قاعده: سازندهٔ رویدادِ گذشته سبز", s0.get("past_fn") is True, str(s0))
check("قاعده: بارِ رویدادِ گذشته بی‌analysis است", s0.get("lean") is True, str(s0))
check("قاعده: تزریقِ حکمِ قطعی سبز", s0.get("verdict") is True, str(s0))
check("قاعده: نزدیک‌ترین فقط پیشِ‌رو سبز", s0.get("nexthigh") is True, str(s0))
check("قاعده: سوییچِ رابط سبز", s0.get("ui") is True, str(s0))
check("قاعده: تأثیرِ نتیجه در فید سبز", s0.get("impact") is True, str(s0))
check("قاعده: انتظارِ صادق سبز", s0.get("wait") is True, str(s0))
check("قاعده: سناریوی پیشِ‌رو حفظ شده", s0.get("scen_future") is True, str(s0))

# ═══ ۱.۵) سنجشِ استاتیکِ منطقهٔ سوییچ ═══
print("═══ ۱.۵) منطقهٔ سوییچ: نتیجه + تأثیر برای اعلام‌شده، سناریو برای پیشِ‌رو ═══")
_fsrc = io.open(os.path.join(HERE, "fundamental.py"), encoding="utf-8").read()
_pfn = SC._py_region(_fsrc, "def _feed_past_event", "\ndef build_feed")
check("استاتیک: سازندهٔ رویدادِ گذشته پیدا شد", bool(_pfn), "")
check("استاتیک: رویدادِ گذشته passed=True دارد", '"passed": True' in _pfn, _pfn[:200])
check("استاتیک: رویدادِ گذشته analysis (شاخهٔ شرطی) ندارد", '"analysis"' not in _pfn, _pfn[:200])
_bfreg = SC._py_region(_fsrc, "def build_feed", "_VERDICT_SKIP_TOKENS")
check("استاتیک: build_feed حکم را به گذشته تزریق می‌کند",
      "_attach_verdicts(past)" in _bfreg, _bfreg[:200])
check("استاتیک: پیشِ‌روها همچنان دو سناریو دارند",
      '"analysis": _analysis' in _fsrc, "")
_breg = SC._py_region(_fsrc, "def build(", "\nif __name__")
check("استاتیک: next_high رویدادهای گذشته را کنار می‌گذارد",
      'not e.get("passed")' in _breg, _breg[:200])
_fund = (SC.page_sources(HERE) or {}).get("FUND_PAGE") or ""
_evreg = SC._feed_evcard_region(_fund)
check("استاتیک: سازندهٔ کارتِ رویداد (evCard) پیدا شد", bool(_evreg), "")
check("استاتیک: رابط وضعیتِ اعلام را می‌سنجد", "e.passed" in _evreg, "")
check("استاتیک: کارتِ نتیجه قبل از سناریوهاست (شاخهٔ past)",
      "resCard(e, v)" in _evreg
      and _evreg.find("resCard(e, v)") < _evreg.find('scenCard("beat"'), "")
check("استاتیک: خطِ «تأثیرِ همین نتیجه» در فید هست",
      "تأثیرِ همین نتیجه" in _fund, "")
check("استاتیک: نشانِ «اعلام شد» در فید هست", "✅ اعلام شد" in _fund, "")
check("استاتیک: ردیفِ صادقِ انتظار در فید هست",
      "هنوز از منبع نرسیده" in _fund, "")
check("استاتیک: پیامِ صادقِ شکستِ منبع در فید هست",
      "منبعِ نتیجه پاسخ نداد" in _fund, "")
check("استاتیک: CSSِ کارتِ نتیجه هست (‏.scard.res)", ".scard.res{" in _fund, "")

# ═══ ۲) جهش‌آزماییِ قاعده ═══
if not NO_MUT:
    print("═══ ۲) جهش‌آزماییِ قاعده (قرمز/بی‌گناه) ═══")
    red("سازندهٔ رویدادِ گذشتهٔ فید حذف شده",
        "سازندهٔ رویدادِ گذشتهٔ فید",
        lambda d: edit(d, "fundamental.py", "def _feed_past_event(e, dt, now, ccy):",
                       "def _feed_past_event_gone(e, dt, now, ccy):"))
    red("رویدادِ گذشته `passed=True` نمی‌گیرد",
        "`passed=True` نمی‌گیرد",
        lambda d: edit(d, "fundamental.py", '        "passed": True,',
                       '        "passed": False,'))
    red("بارِ رویدادِ گذشته باز هم analysis می‌فرستد",
        "دوشاخه‌ای می‌فرستد",
        lambda d: edit(d, "fundamental.py",
                       '        "passed": True,\n        "minutes_ago": round((now - dt).total_seconds() / 60),',
                       '        "passed": True,\n        "minutes_ago": round((now - dt).total_seconds() / 60),\n        "analysis": _analysis(e.get("title"), ccy),'))
    red("build_feed حکمِ قطعی را تزریق نمی‌کند",
        "تزریق نمی‌کند",
        lambda d: edit(d, "fundamental.py",
                       "        _attach_verdicts(past)  # «نتیجه + تأثیرِ محقق» برای رویدادهای اعلام‌شده",
                       "        pass  # حکم تزریق نشد (جهش)"))
    red("next_high رویدادهای گذشته را کنار نمی‌گذارد",
        "کنار نمی‌گذارد",
        lambda d: edit(d, "fundamental.py",
                       'and not e.get("passed")', ''))
    red("رابط وضعیتِ اعلام (e.passed) را نمی‌سنجد",
        "وضعیتِ اعلام",
        lambda d: edit(d, "app.py", "  const past=!!e.passed;", "  const past=false;"))
    red("شاخهٔ فید برعکس سوییچ می‌کند (!past)",
        "برعکس سوییچ",
        lambda d: edit(d, "app.py", "const body = past", "const body = !past"))
    red("کارتِ نتیجه (resCard) از مسیرِ گذشته رفت",
        "نیمه‌کاره",
        lambda d: edit(d, "app.py", "    ? resCard(e, v)", '    ? ""'))
    red("خطِ «تأثیرِ همین نتیجه» از فید افتاد",
        "در فید رندر نمی‌شود",
        lambda d: edit(d, "app.py", 'res-imp">تأثیرِ همین نتیجه', 'res-imp">اثر'))
    red("ردیفِ صادقِ انتظار از فید رفت",
        "حالتِ صادقِ انتظار",
        lambda d: edit(d, "app.py", "عددِ اعلام‌شده هنوز از منبع نرسیده",
                       "عددِ اعلام‌شده در راه است"))
    red("پیامِ صادقِ شکستِ منبع از فید رفت",
        "حالتِ صادقِ انتظار",
        lambda d: edit(d, "app.py", "منبعِ نتیجه پاسخ نداد", "منبع پر است"))
    red("سناریوهای پیشِ‌رو (scenCard) از فید حذف شدند",
        "از فید حذف شدند",
        lambda d: edit(d, "app.py",
                       '        ${scenCard("beat", a.beat)}\n        ${scenCard("miss", a.miss)}',
                       '        ${""}'))

    # بی‌گناه‌ها: نباید قرمز شوند
    d = copy_repo()
    try:
        edit(d, "fundamental.py",
             '    cat, icon, _mode, _why = _classify(e.get("title"), ccy)',
             '    cat, icon, _mode, _why = _classify(e.get("title"), ccy)\n    # آیکن/دسته برای هدرِ کارتِ اعلام‌شده')
        probs, st = scan(d)
        check("بی‌گناه: کامنتِ تازه در سازندهٔ گذشته سبز می‌مانَد",
              probs == [] and st.get("past_fn") is True, str(probs)[:200])
    finally:
        drop(d)
    d = copy_repo()
    try:
        # دورِ ۴.۲۱: کفِ پنجره از `past_window` می‌آید (پنجرهٔ ۶/۱۲/۲۴)؛ این جهشِ
        # بی‌گناه فقط یک کامنت روی همان خط می‌گذارد تا لنگرِ تازه هم سنجیده شود.
        edit(d, "fundamental.py",
             "    floor = now - datetime.timedelta(hours=past_window(past_hours))",
             "    floor = now - datetime.timedelta(hours=past_window(past_hours))  # کفِ پنجره")
        probs, st = scan(d)
        check("بی‌گناه: کامنتِ تازه روی خطِ کفِ پنجره سبز می‌مانَد",
              probs == [] and st.get("lean") is True, str(probs)[:200])
    finally:
        drop(d)
    d = copy_repo()
    try:
        edit(d, "app.py", 'return `<div class="scard res"><div class="sh">نتیجه</div>',
             'return `<div class="scard res wide"><div class="sh">نتیجه</div>')
        probs, st = scan(d)
        check("بی‌گناه: کلاسِ نمایشیِ تازه روی کارتِ نتیجه سبز می‌مانَد",
              probs == [] and st.get("ui") is True, str(probs)[:200])
    finally:
        drop(d)
    d = copy_repo()
    try:
        edit(d, "app.py", '"⏳ نتیجه به‌زودی"', '"⏳ نتیجه به‌زودی — بروزرسانی می‌شود"')
        probs, st = scan(d)
        check("بی‌گناه: توضیحِ بیشتر روی نشانِ انتظار سبز می‌مانَد",
              probs == [] and st.get("wait") is True, str(probs)[:200])
    finally:
        drop(d)

# ═══ ۳) رفتارِ خالص (تقویمِ ساختگی — بدونِ شبکه) ═══
print("═══ ۳) رفتارِ خالصِ سوییچ (بدونِ شبکه) ═══")
import fundamental as F  # noqa: E402

NOW = datetime.datetime.now(datetime.timezone.utc)
_ISM_DT = NOW - datetime.timedelta(hours=1.5)
_GBP_DT = NOW - datetime.timedelta(hours=1.2)
_NFP_DT = NOW + datetime.timedelta(hours=3)


def _iso(dt):
    return dt.isoformat()


CAL = [
    {"impact": "High", "date": _iso(_ISM_DT), "title": "ISM Services PMI", "country": "USD",
     "forecast": "51.5", "previous": "50.8"},
    {"impact": "High", "date": _iso(_GBP_DT), "title": "Industrial Production m/m", "country": "GBP",
     "forecast": "0.3%", "previous": "0.2%"},
    {"impact": "High", "date": _iso(_NFP_DT), "title": "Non-Farm Payrolls", "country": "USD",
     "forecast": "180K", "previous": "175K"},
    {"impact": "Medium", "date": _iso(NOW + datetime.timedelta(hours=5)), "title": "Retail Sales m/m",
     "country": "EUR", "forecast": "0.4%", "previous": "0.3%"},
]
ROWS = [{"ccy": "USD", "date": _ISM_DT.astimezone(datetime.timezone.utc).date().isoformat(),
         "minute": _ISM_DT.hour * 60 + _ISM_DT.minute, "event": "ism services pmi", "actual": "52.3"}]


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
    feed = F.build_feed(hours=24, past_hours=6)
    past = [e for e in feed if e.get("passed")]
    future = [e for e in feed if not e.get("passed")]
    ism = next((e for e in past if "ISM" in (e.get("title") or "")), {})
    gbp = next((e for e in past if (e.get("country") == "GBP")), {})
    nfp = next((e for e in future if "Payrolls" in (e.get("title") or "")), {})
    check("رفتار: رویدادِ گذشته در فید می‌مانَد (passed)", len(past) == 2, str(len(past)))
    check("رفتار: دو رویدادِ پیشِ‌رو در فید اند", len(future) == 2, str(len(future)))
    check("رفتار: گذشته‌ها اولِ فهرست (مرتب بر زمان) اند",
          feed and feed[0].get("passed") is True and feed[-1].get("passed") is False,
          str(feed[0].get("iso")) if feed else "")
    check("رفتار: گذشته بی‌`analysis` است (رندرِ شرطی ممکن نیست)",
          "analysis" not in ism and "analysis" not in gbp, str(list(ism.keys()))[:200])
    check("رفتار: گذشته `verdict` گرفته", isinstance(ism.get("verdict"), dict), str(ism.get("verdict"))[:200])
    check("رفتار: عددِ اعلام‌شده به حکمِ فید رسیده",
          ism.get("verdict", {}).get("actual") == "52.3", str(ism.get("verdict"))[:200])
    check("رفتار: بالاتر از انتظار ⇒ دلارِ قوی‌تر",
          ism.get("verdict", {}).get("beat") == "بالاتر از انتظار"
          and ism.get("verdict", {}).get("dir") == "قوی‌تر", str(ism.get("verdict"))[:200])
    ef = ism.get("verdict", {}).get("effect") or {}
    check("رفتار: تأثیرِ محقق همراهِ حکم است (طلا/نقره نزولی برای دلارِ قوی)",
          bool(ef.get("pairs")) and str((ef.get("gold") or ["", ""])[1]).startswith("↓"), str(ef)[:200])
    check("رفتار: «دقیقه‌ها از اعلام» در بارِ گذشته هست",
          isinstance(ism.get("minutes_ago"), int) and ism.get("minutes_ago") >= 89, str(ism.get("minutes_ago")))
    check("رفتار: رویدادِ گذشتهٔ بی‌عدد، صادقِ انتظار است (found=False)",
          gbp.get("verdict", {}).get("found") is False, str(gbp.get("verdict"))[:200])
    check("رفتار: پیشِ‌رو دو سناریوی شرطی دارد",
          "analysis" in nfp and "beat" in nfp["analysis"] and "miss" in nfp["analysis"], str(list(nfp.keys())))
    check("رفتار: پیشِ‌رو حکمِ قطعی ندارد", "verdict" not in nfp, str(list(nfp.keys())))
    check("رفتار: پیشِ‌رو `passed=False` است", nfp.get("passed") is False, "")

    rep = F.build(hours=24, past_hours=6)
    check("رفتار: next_high رویدادِ پیشِ‌روست، نه گذشته",
          (rep.get("next_high") or {}).get("iso") == _iso(_NFP_DT),
          str((rep.get("next_high") or {}).get("iso")))
    check("رفتار: count_past گذشته‌ها را می‌شمارد", rep.get("count_past") == 2, str(rep.get("count_past")))
    check("رفتار: source_ok از گیرندهٔ Actual می‌آید", rep.get("source_ok") is True, str(rep.get("source_ok")))
    check("رفتار: count همهٔ رویدادها (گذشته + پیشِ‌رو)", rep.get("count") == 4, str(rep.get("count")))

    feed0 = F.build_feed(hours=24, past_hours=0)
    check("رفتار: past_hours=0 ⇒ گذشته‌ای در فید نیست",
          [e for e in feed0 if e.get("passed")] == [], str(len(feed0)))

    F.M = _FakeM([])
    rep2 = F.build(hours=24, past_hours=6)
    past2 = [e for e in rep2.get("events") or [] if e.get("passed")]
    check("رفتار: منبعِ خالی ⇒ source_ok=False (صداقت)",
          rep2.get("source_ok") is False, str(rep2.get("source_ok")))
    check("رفتار: منبعِ خالی ⇒ حکمِ found=False، ولی باز هم بی‌analysis",
          bool(past2) and all((e.get("verdict") or {}).get("found") is False
                              and "analysis" not in e for e in past2), str(past2)[:200])
finally:
    F.M = _orig

# ── جمع‌بندی ──
print("\n• بررسی‌ها: %d" % len(CHECKS))
if FAILS:
    for name, detail in FAILS:
        print("::error::❌ %s — %s" % (name, detail[:220]))
    print("\n❌ آزمونِ «سوییچِ خودکارِ فید» رد شد — %d از %d بررسی شکست خورد"
          % (len(FAILS), len(CHECKS)))
    sys.exit(1)
print("✅ آزمونِ «سوییچِ خودکارِ فید بعد از اعلام» پاس شد — رویدادِ گذشته پس از "
      "اعلامِ عدد «نتیجه + تأثیرِ محقق» می‌گیرد و بی‌گزارهٔ شرطی می‌مانَد، "
      "رویدادِ پیشِ‌رو دو سناریوی صادق دارد، و «نزدیک‌ترین خبر» فقط پیشِ‌روست")
