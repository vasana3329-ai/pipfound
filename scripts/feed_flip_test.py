#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""آزمونِ لایه‌ی ۴.۲۲ — «سوییچِ لحظه‌ایِ اعلام» (خواسته‌ی کاربر).

خواسته: «کاری کن کارتِ پیش‌رو درست در لحظهٔ رسیدنِ شمارشِ معکوس به صفر خودکار به
حالتِ «اعلام شد» سوییچ کند و نتیجه را بیاورد — بدونِ رفرشِ صفحه و بدونِ پنجرهٔ
یک‌دقیقه‌ایِ فعلی.»

منطق: شمارشِ معکوسِ فعلی از رشتهٔ سرور می‌آید و `in_hours` به یک‌دهمِ ساعت
(یعنی ۶ دقیقه) گرد می‌شود — با چنین لنگری «لحظهٔ اعلام» درست گرفتنی نیست، پس
کارت تا پنجرهٔ ۶۰ثانیه‌ایِ بعدِ خواندنِ فید کهنه می‌مانْد. این لایه سه چیز را
قفل می‌کند: (۱) لنگرِ **ثانیه‌ایِ** سرور (`in_s`)؛ (۲) مسیرِ **تک‌رویداد**
(`?event=` + `one_event`) تا برای یک کارت کلِ فهرست خوانده نشود؛ (۳) سوییچِ
**درجا** با گاردِ اعلامِ زودرس، ردیفِ صادقِ انتظار و تکرارِ **سقف‌دار** تا
رسیدنِ عدد، به‌همراه تازه‌شدنِ «نزدیک‌ترین خبرِ پرتأثیر» و مبنای «N دقیقه پیش».

سه بخش:
  ۱) قاعده‌ی نگهبانِ `selfcheck.feed_flip_problems` روی مخزنِ سالم صفر خطا.
  ۱.۵) سنجشِ استاتیکِ زنجیره (لنگر → مسیر → تیک → سوییچِ درجا → صبر/سقف).
  ۲) جهش‌آزمایی: ۱۶ جهشِ سرخِ نام‌دار + ۵ بی‌گناه + یک **جهشِ رفتاری** که ثابت
     می‌کند ادعای «دقتِ ثانیه‌ای» دندان دارد (نسخهٔ گِردشدهٔ `in_s` رفتار را
     می‌شکند، نه فقط متن را).
  ۳) رفتارِ خالص: تقویمِ ساختگی با خبرِ ۹۵ ثانیه‌ایِ آینده و خبرِ ۲۵ ثانیه‌ایِ
     گذشته — `in_s` دقیق، `one_event` برای هر دو حالت، و «نزدیک‌ترین خبر» بعد از
     سوییچ رویدادِ اعلام‌شده را کنار می‌گذارد.

آفلاین است (فقط متنِ کد + تقویمِ ساختگی؛ شبکه‌ای در کار نیست).
PF_FEEDFLIP_NO_MUT=1 بخشِ جهش را رد می‌کند (فرارِ سریعِ CI محدود).
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

# ── ابزارِ جهش (سبکِ مخزن: لنگر باید یکتا باشد وگرنه خطا — نه سبزِ خاموش) ──
CHECKS, FAILS = [], []


def check(name, cond, detail=""):
    CHECKS.append(name)
    if not cond:
        FAILS.append((name, detail))
    return bool(cond)


def copy_repo():
    d = tempfile.mkdtemp(prefix="pf_feedflip_")
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
    return SC.feed_flip_problems(d, SC.page_sources(d))


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


# سناریوی رفتاریِ مشترک: خبرِ ۹۵ ثانیه‌ایِ آینده باید `in_s` دقیق بدهد و
# `one_event` برای همان لحظه بارِ درست را برگرداند؛ هر تغییری که دقتِ ثانیه‌ای
# را از بین ببرد، این اسکریپت را می‌شکند.
BEHAVE = r"""
import datetime, fundamental as F
NOW = datetime.datetime.now(datetime.timezone.utc)
SOON = NOW + datetime.timedelta(seconds=95)
CAL = [{"impact": "High", "date": SOON.isoformat(), "title": "ISM Services PMI",
        "country": "USD", "forecast": "51.5", "previous": "50.8"}]
class M:
    def get_calendar(self): return list(CAL)
    def get_actuals(self, *a, **k): return []
F.M = M()
feed = F.build_feed(hours=24, past_hours=6)
ev = feed[0]
assert ev.get("passed") is False, "رویداد باید پیشِ‌رو باشد"
assert isinstance(ev.get("in_s"), int), "in_s باید عددِ صحیح باشد"
assert abs(ev["in_s"] - 95) <= 3, "in_s باید ثانیه‌ایِ دقیق باشد، نه گِردشده: %r" % ev["in_s"]
assert ev.get("in_hours") == 0.0, "in_hours همان گِردشدهٔ ساعتی می‌مانَد"
one = F.one_event(ev["iso"], hours=24, past_hours=6)
assert one.get("event") and one["event"]["iso"] == ev["iso"], "one_event باید همان رویداد را بدهد"
assert one.get("past_hours") == 6
print("OK")
"""


def red_behavior(name, mutate):
    """جهشِ رفتاری: نسخهٔ جهش‌یافته باید اسکریپتِ سنجش را بشکند (نه فقط متن را)."""
    d = copy_repo()
    try:
        mutate(d)
        p = subprocess.run([sys.executable, "-c", BEHAVE], cwd=d,
                           capture_output=True, text=True, timeout=120)
        check("قرمزِ رفتاری: " + name, p.returncode != 0,
              "رفتار سالم ماند! out=" + (p.stdout or "")[-200:] + (p.stderr or "")[-200:])
    finally:
        drop(d)


NO_MUT = os.environ.get("PF_FEEDFLIP_NO_MUT") == "1"

# ═══ ۱) قاعده روی مخزنِ سالم ═══
print("═══ ۱) قاعدهٔ نگهبان روی مخزنِ سالم ═══")
p0, s0 = scan(HERE)
check("قاعده: مخزنِ سالم صفر خطا", p0 == [], str(p0)[:300])
check("قاعده: لنگرِ ثانیه‌ایِ اعلام سبز", s0.get("ins") is True, str(s0))
check("قاعده: مسیرِ تک‌رویداد سبز",
      s0.get("one_event") is True and s0.get("route") is True, str(s0))
check("قاعده: تیکِ لحظهٔ صفر سبز", s0.get("tick") is True, str(s0))
check("قاعده: سوییچِ درجا بی‌بازسازیِ فهرست", s0.get("patch_only") is True, str(s0))
check("قاعده: گاردِ اعلامِ زودرس سبز", s0.get("early") is True, str(s0))
check("قاعده: صبرِ سقف‌دار تا عددِ اعلام‌شده سبز", s0.get("retry") is True, str(s0))
check("قاعده: نزدیک‌ترین خبرِ پرتأثیر بعد از سوییچ تازه می‌شود",
      s0.get("next") is True, str(s0))
check("قاعده: مبنای «N دقیقه پیش»ِ کارتِ سوییچ‌شده تازه می‌شود",
      s0.get("fresh_base") is True, str(s0))
check("قاعده: خوانندهٔ عدد پسوندِ مقیاس (‏195K) را می‌فهمد",
      s0.get("num_mult") is True, str(s0))
check("قاعده: عددهای منفی «نامعلوم» شمرده نمی‌شوند",
      s0.get("num_exact") is True, str(s0))
check("قاعده: لنگرِ ثانیه‌ای با کلیدِ درستِ dataset خوانده می‌شود",
      s0.get("ins_read") is True, str(s0))
check("قاعده: کلیدِ تازه پس از تغییرِ عنوانِ رویداد دنبال می‌شود",
      s0.get("rekey") is True, str(s0))

# ═══ ۱.۵) سنجشِ استاتیکِ زنجیرهٔ سوییچِ لحظه‌ای ═══
print("═══ ۱.۵) زنجیرهٔ لنگر → مسیر → تیک → سوییچِ درجا ═══")
_fsrc = io.open(os.path.join(HERE, "fundamental.py"), encoding="utf-8").read()
_asrc = io.open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
_fund = (SC.page_sources(HERE) or {}).get("FUND_PAGE") or ""
check("استاتیک: in_s در بارِ رویدادِ پیشِ‌رو هست",
      '"in_s": int(max(0, (dt - now).total_seconds()))' in _fsrc, "")
_oreg = SC._py_region(_fsrc, "def one_event", "\nif __name__")
check("استاتیک: one_event فقط از build_feed تغذیه می‌شود (یک منبعِ حکم)",
      "= build_feed(" in _oreg and "_attach_verdicts" not in _oreg, _oreg[:200])
check("استاتیک: one_event رویدادِ بیرونِ پنجره را None می‌دهد",
      "next((e for e in feed" in _oreg, _oreg[:200])
_rreg = SC._py_region(_asrc, 'if u.path == "/api/fundamental":', 'if u.path == "/fundamental":')
check("استاتیک: مسیرِ /api/fundamental تک‌رویداد را می‌دهد",
      'get("event",' in _rreg and "FUND.one_event(" in _rreg, _rreg[:200])
check("استاتیک: مسیرِ کامل (بی‌event) دست‌نخورده مانْد",
      "FUND.build(hours=hours, past_hours=past_hours)" in _rreg, _rreg[:200])
check("استاتیک: بجِ پیشِ‌رو لنگرِ in_s را روی خودش دارد",
      'data-in-s="${e.in_s}"' in _fund, "")
_treg = SC._py_region(_fund, "function tickBadges(", "\nasync function load(){")
check("استاتیک: تیک در لحظهٔ صفر flipEvent را صدا می‌زند",
      "flipEvent(c.dataset.key)" in _treg, _treg[:200])
check("استاتیک: تیک لنگرِ ثانیه‌ای را با getAttribute می‌خواند (نه dataset.in_s)",
      'getAttribute("data-in-s")' in _treg and "dataset.in_s" not in _fund, _treg[:200])
check("استاتیک: تیک خودش شبکه/رندر نمی‌زند (کارِ سنگین در flipEvent)",
      "fetch(" not in _treg and "load()" not in _treg and "render()" not in _treg, _treg[:200])
_freg2 = SC._py_region(_fund, "async function flipEvent(", "\nfunction patchEvent(")
check("استاتیک: flipEvent فقط همان یک رویداد را می‌پرسد",
      "?event=${encodeURIComponent(iso)}" in _freg2 and "&past=" in _freg2, _freg2[:200])
check("استاتیک: flipEvent از مسیرِ کاملِ فهرست نمی‌پرسد",
      "hours=${horHours}" in _freg2 and "?event=" in _freg2, _freg2[:200])
_preg = SC._py_region(_fund, "function patchEvent(", "\n$(")
check("استاتیک: patchEvent فقط همان کارت را جایگزین می‌کند",
      "card.outerHTML=evCard(ev, idx)" in _preg and "render()" not in _preg, _preg[:200])
check("استاتیک: patchEvent حالِ باز/بستهٔ کاربر را نگه می‌دارد",
      "wasOpen" in _preg and "openKeys.has(key)" in _preg, _preg[:200])
check("استاتیک: ردیفِ همان رویداد در DATA هم به‌روز می‌شود",
      "DATA.events[i]=ev" in _preg, _preg[:200])
check("استاتیک: سوییچ با کلیدِ تازه سازگار است (عنوانِ عوض‌شده)",
      "const nk=evKey(ev)" in _preg and "findCard(nk)" in _preg, _preg[:200])
check("استاتیک: سقفِ تکرار عددی و مثبت است",
      SC._FF_RETRY_MAX_RE.search(_fund) is not None
      and int(SC._FF_RETRY_MAX_RE.search(_fund).group(1)) > 0, "")

# ═══ ۲) جهش‌آزماییِ قاعده ═══
if not NO_MUT:
    print("═══ ۲) جهش‌آزماییِ قاعده (قرمز/بی‌گناه/رفتاری) ═══")
    red("لنگرِ ثانیه‌ایِ اعلام (in_s) از بارِ رویداد رفته",
        "ثانیه‌های دقیقِ باقی‌مانده",
        lambda d: edit(d, "fundamental.py",
                       '            "in_s": int(max(0, (dt - now).total_seconds())),\n', ""))
    red("one_event حذف شده",
        "`one_event`",
        lambda d: edit(d, "fundamental.py", "def one_event(iso, hours=180, past_hours=6):",
                       "def one_event_gone(iso, hours=180, past_hours=6):"))
    red("one_event بارِ رویداد را برنمی‌گرداند",
        "نمی‌دهد",
        lambda d: edit(d, "fundamental.py", '        "event": ev,', '        "event": None,'))
    red("one_event از مسیرِ build_feed نمی‌آید",
        "دوباره‌کاری",
        lambda d: edit(d, "fundamental.py",
                       '    iso = (iso or "").strip()\n'
                       "    past_hours = past_window(past_hours)\n"
                       "    feed = build_feed(hours=hours, past_hours=past_hours)",
                       '    iso = (iso or "").strip()\n'
                       "    past_hours = past_window(past_hours)\n"
                       "    feed = []"))
    red("مسیرِ API پارامترِ event را نمی‌خواند",
        "را نمی‌خواند",
        lambda d: edit(d, "app.py", 'ev_iso = (parse_qs(u.query).get("event", [""])[0] or "").strip()',
                       'ev_iso = ""'))
    red("بجِ پیشِ‌رو لنگرِ in_s را روی خودش ندارد",
        "data-in-s",
        lambda d: edit(d, "app.py", ' data-in-s="${e.in_s}"', ""))
    red("لنگرِ ثانیه‌ای با کلیدِ اشتباهِ dataset خوانده می‌شود",
        "کلیدِ اشتباهِ dataset",
        lambda d: edit(d, "app.py", 'b.getAttribute("data-in-s")', "b.dataset.in_s"))
    red("تیک در لحظهٔ صفر سوییچ نمی‌کند",
        "لحظهٔ صفر سوییچ نمی‌کند",
        lambda d: edit(d, "app.py", "flipEvent(c.dataset.key);", "void 0;"))
    red("فلپ، تک‌رویداد را نمی‌پرسد (کلِ فهرست)",
        "تک‌رویداد",
        lambda d: edit(d, "app.py", "?event=${encodeURIComponent(iso)}&hours=", "?hours="))
    red("گاردِ «هنوز اعلام نشده» از فلپ رفته",
        "زودرس",
        lambda d: edit(d, "app.py", "if(!ev || ev.passed!==true){", "if(!ev){"))
    red("سقفِ تکرار از فلپ رفته",
        "سقف/شرطِ توقف",
        lambda d: edit(d, "app.py", "if(n<=FLIP_RETRY_MAX)", "if(true)"))
    red("تکرارِ پرسش بعد از رسیدنِ عدد متوقف نمی‌شود",
        "سقف/شرطِ توقف",
        lambda d: edit(d, "app.py", "      delete flipTries[key];\n    }\n  }catch(err){",
                       "      flipTries[key]=0;\n    }\n  }catch(err){"))
    red("زمان‌بندِ تکرارِ پرسش برداشته شده",
        "سقف/شرطِ توقف",
        lambda d: edit(d, "app.py",
                       "      if(n<=FLIP_RETRY_MAX) setTimeout(()=>flipEvent(nk), FLIP_RETRY_MS);",
                       "      if(n<=FLIP_RETRY_MAX) void 0;"))
    red("تکرار با کلیدِ کهنه ادامه می‌یابد",
        "کلیدِ تازه",
        lambda d: edit(d, "app.py", "setTimeout(()=>flipEvent(nk), FLIP_RETRY_MS)",
                       "setTimeout(()=>flipEvent(key), FLIP_RETRY_MS)"))
    red("کارتْ کلیدِ تازه را دنبال نمی‌کند (عنوانِ عوض‌شده)",
        "کلیدِ تازه",
        lambda d: edit(d, "app.py", "  const nk=evKey(ev);\n  if(DATA && Array.isArray(DATA.events)){",
                       "  if(DATA && Array.isArray(DATA.events)){"))
    red("سوییچِ کارت کلِ فهرست را بازمی‌سازد",
        "کلِ فهرست را بازمی‌سازد",
        lambda d: edit(d, "app.py", "card.outerHTML=evCard(ev, idx);", "render();"))
    red("«نزدیک‌ترین خبرِ پرتأثیر» بعد از سوییچ کهنه می‌مانَد",
        "نزدیک‌ترین خبرِ پرتأثیر",
        lambda d: edit(d, "app.py", "DATA.next_high=(d && d.next_high)||null;", ""))
    red("مبنای «N دقیقه پیش»ِ کارتِ سوییچ‌شده تازه نمی‌شود",
        "جلو می‌زند",
        lambda d: edit(d, "app.py", 'nb.setAttribute("data-t0", String(Date.now()));', "void 0;"))
    red("ردیفِ همان رویداد در DATA به‌روز نمی‌شود",
        "برمی‌گرداند",
        lambda d: edit(d, "app.py", "    if(i>=0) DATA.events[i]=ev; else DATA.events.push(ev);", ""))
    red("خوانندهٔ عدد پسوندِ مقیاس را نمی‌فهمد (‏195K)",
        "پسوندِ مقیاس",
        lambda d: edit(d, "fundamental.py",
                       "    if s[-1:] in _NUM_MULT:\n"
                       "        mult = _NUM_MULT[s[-1:]]\n        s = s[:-1].strip()\n", ""))
    red("نشانهٔ «داده نداریم» زیررشته‌ای سنجیده می‌شود (عددهای منفی قربانی)",
        "عددهای منفی",
        lambda d: edit(d, "fundamental.py",
                       "    if not s or s in _VERDICT_SKIP_TOKENS:",
                       "    if not s or any(tok in s for tok in _VERDICT_SKIP_TOKENS):"))
    red("خوانندهٔ عدد مقدارِ فقط-پسوند («K») را هم عدد می‌گیرد",
        "پسوندِ مقیاس",
        lambda d: edit(d, "fundamental.py",
                       "    if not s:\n        return None\n    try:\n        return float(s) * mult",
                       "    try:\n        return float(s or 1) * mult"))

    # جهشِ رفتاری: ادعای «دقتِ ثانیه‌ای» باید دندان داشته باشد — گِردکردنِ ساعتی
    # (همان `in_hours`ِ قبلی) باید سناریوی رفتاری را بشکند، نه فقط متن را.
    red_behavior("in_s به ساعتِ گِردشده تبدیل شود (بی‌دقت)",
                 lambda d: edit(d, "fundamental.py",
                                '            "in_s": int(max(0, (dt - now).total_seconds())),',
                                '            "in_s": int(max(0, (dt - now).total_seconds()) / 3600) * 3600,'))

    # بی‌گناه‌ها: نباید قرمز شوند
    d = copy_repo()
    try:
        edit(d, "fundamental.py", "    iso = (iso or \"\").strip()",
             "    iso = (iso or \"\").strip()  # کلیدِ رویداد از سمتِ رابط")
        probs, st = scan(d)
        check("بی‌گناه: کامنتِ تازه در one_event سبز می‌مانَد",
              probs == [] and st.get("one_event") is True, str(probs)[:200])
    finally:
        drop(d)
    d = copy_repo()
    try:
        edit(d, "fundamental.py", '        "iso": iso,', '        "iso": iso,\n        "src": "one",')
        probs, st = scan(d)
        check("بی‌گناه: کلیدِ اضافه در پاسخِ تک‌رویداد سبز می‌مانَد",
              probs == [] and st.get("one_event") is True, str(probs)[:200])
    finally:
        drop(d)
    d = copy_repo()
    try:
        edit(d, "app.py", "FLIP_RETRY_MAX=8", "FLIP_RETRY_MAX=10")
        probs, st = scan(d)
        check("بی‌گناه: بلندترکردنِ سقفِ تکرار سبز می‌مانَد",
              probs == [] and st.get("retry") is True, str(probs)[:200])
    finally:
        drop(d)
    d = copy_repo()
    try:
        edit(d, "app.py", ' data-in-s="${e.in_s}"', ' data-in-s="${e.in_s}" data-flip-src="srv"')
        probs, st = scan(d)
        check("بی‌گناه: ویژگیِ نمایشیِ تازه روی بجِ پیشِ‌رو سبز می‌مانَد",
              probs == [] and st.get("datas") is True, str(probs)[:200])
    finally:
        drop(d)
    d = copy_repo()
    try:
        edit(d, "app.py", "    patchEvent(ev, key);",
             "    // سوییچِ درجا — فقط همین کارت\n    patchEvent(ev, key);")
        probs, st = scan(d)
        check("بی‌گناه: کامنتِ تازه در فلپ سبز می‌مانَد",
              probs == [] and st.get("flip_fn") is True, str(probs)[:200])
    finally:
        drop(d)

# ═══ ۳) رفتارِ خالص (تقویمِ ساختگی — بدونِ شبکه) ═══
print("═══ ۳) رفتارِ خالصِ سوییچِ لحظه‌ای (بدونِ شبکه) ═══")
import datetime as _dt  # noqa: E402
import fundamental as F  # noqa: E402

NOW = _dt.datetime.now(_dt.timezone.utc)
_SOON = NOW + _dt.timedelta(seconds=95)          # همین حالا-نزدیک
_JUST = NOW - _dt.timedelta(seconds=25)          # تازه اعلام شد
_LATER = NOW + _dt.timedelta(hours=5)            # خبرِ پرتأثیرِ بعدی
_FAR = NOW + _dt.timedelta(hours=300)            # بیرونِ افقِ فید

CAL = [
    {"impact": "High", "date": _SOON.isoformat(), "title": "ISM Services PMI",
     "country": "USD", "forecast": "51.5", "previous": "50.8"},
    {"impact": "High", "date": _JUST.isoformat(), "title": "Non-Farm Payrolls",
     "country": "USD", "forecast": "180K", "previous": "175K"},
    {"impact": "High", "date": _LATER.isoformat(), "title": "Retail Sales m/m",
     "country": "EUR", "forecast": "0.4%", "previous": "0.3%"},
    {"impact": "High", "date": _FAR.isoformat(), "title": "GDP q/q",
     "country": "GBP", "forecast": "0.2%", "previous": "0.1%"},
]
ROWS = [{"ccy": "USD", "date": _JUST.astimezone(_dt.timezone.utc).date().isoformat(),
         "minute": _JUST.hour * 60 + _JUST.minute, "event": "non-farm payrolls",
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
    feed = F.build_feed(hours=24, past_hours=6)
    soon = next((e for e in feed if e.get("title") == "ISM Services PMI"), {})
    just = next((e for e in feed if e.get("title") == "Non-Farm Payrolls"), {})
    later = next((e for e in feed if e.get("title") == "Retail Sales m/m"), {})

    check("رفتار: خبرِ ۹۵ ثانیه‌ایِ آینده preشِ‌رو است (نه اعلام‌شده)",
          soon.get("passed") is False and "analysis" in soon, str(soon.get("passed")))
    check("رفتار: لنگرِ ثانیه‌ای دقیق است (نه گِردشدهٔ ساعتی)",
          isinstance(soon.get("in_s"), int) and 92 <= soon["in_s"] <= 98,
          "in_s=%r in_hours=%r" % (soon.get("in_s"), soon.get("in_hours")))
    check("رفتار: in_hours همان گِردشدهٔ ۶دقیقه‌ای می‌مانَد (شاهدِ لزومِ in_s)",
          soon.get("in_hours") == 0.0, str(soon.get("in_hours")))
    check("رفتار: خبرِ ۵ ساعته in_s ≈ ۱۸۰۰۰ ثانیه می‌دهد",
          isinstance(later.get("in_s"), int) and abs(later["in_s"] - 18000) <= 5,
          str(later.get("in_s")))
    check("رفتار: خبرِ ۲۵ ثانیه‌ایِ گذشته اعلام‌شده است",
          just.get("passed") is True and "analysis" not in just, str(just.get("passed")))
    check("رفتار: حکمِ همان خبرِ تازه‌اعلام‌شده عدد دارد (‏«195K» خوانده می‌شود)",
          (just.get("verdict") or {}).get("found") is True
          and (just.get("verdict") or {}).get("actual") == "195K"
          and (just.get("verdict") or {}).get("beat") == "بالاتر از انتظار",
          str(just.get("verdict"))[:200])
    check("رفتار: جهتِ «195K» در برابرِ «180K» قوی‌تر است (دلار).",
          (just.get("verdict") or {}).get("dir") == "قوی‌تر", str(just.get("verdict"))[:200])
    check("رفتار: خبرِ بیرونِ افقِ فید در فهرست نیست",
          all(e.get("title") != "GDP q/q" for e in feed), "")

    one_soon = F.one_event(soon.get("iso"), hours=24, past_hours=6)
    check("رفتار: one_event برای خبرِ پیشِ‌رو همان بارِ پیشِ‌رو را می‌دهد",
          (one_soon.get("event") or {}).get("passed") is False
          and "analysis" in (one_soon.get("event") or {}), str(one_soon)[:200])
    check("رفتار: one_event لنگرِ ثانیه‌ای را همراه دارد",
          isinstance((one_soon.get("event") or {}).get("in_s"), int), "")
    check("رفتار: نزدیک‌ترین خبرِ پرتأثیر قبل از سوییچ همان خبرِ نزدیک است",
          (one_soon.get("next_high") or {}).get("iso") == soon.get("iso"),
          str((one_soon.get("next_high") or {}).get("iso")))

    one_just = F.one_event(just.get("iso"), hours=24, past_hours=6)
    check("رفتار: one_event در لحظهٔ اعلام بارِ «اعلام‌شده» با حکم می‌دهد",
          (one_just.get("event") or {}).get("passed") is True
          and "analysis" not in (one_just.get("event") or {})
          and (one_just.get("event") or {}).get("verdict", {}).get("found") is True,
          str(one_just.get("event"))[:250])
    check("رفتار: بعد از سوییچ، «نزدیک‌ترین خبر» رویدادِ اعلام‌شده را کنار می‌گذارد",
          (one_just.get("next_high") or {}).get("iso") == soon.get("iso"),
          str((one_just.get("next_high") or {}).get("iso")))
    check("رفتار: هر دو خبرِ پیشِ‌رو در فهرست‌اند و ترتیب بر زمان است",
          soon.get("iso") < later.get("iso") and later.get("passed") is False, "")

    # جدولِ خوانندهٔ عدد (همان چیزی که کلِ سوییچ به آن تکیه دارد)
    _TAB = [("195K", 195000.0), ("1.2M", 1200000.0), ("2.3B", 2300000000.0),
            ("3.6%", 3.6), ("1,234K", 1234000.0), ("-2.5%", -2.5), ("-0.3", -0.3),
            ("0", 0.0),
            ("52.3", 52.3), ("—", None), ("n/a", None), ("", None), (None, None),
            ("K", None), ("tbd", None)]
    _bad = [(v, F._num(v), want) for v, want in _TAB if F._num(v) != want]
    check("رفتار: جدولِ خوانندهٔ عدد (پسوند/درصد/کاما/نامعلوم) درست است",
          _bad == [], str(_bad)[:300])
    check("رفتار: پنجرهٔ مؤثرِ گذشته در پاسخِ تک‌رویداد هم می‌آید",
          one_just.get("past_hours") == 6, str(one_just.get("past_hours")))

    check("رفتار: isoِ ناشناس ⇒ event=None (بی‌استثنا)",
          F.one_event("2026-01-01T00:00:00+00:00", hours=24, past_hours=6).get("event") is None, "")
    check("رفتار: isoِ خالی/None هم بی‌خطر است",
          F.one_event("", hours=24)["event"] is None and F.one_event(None, hours=24)["event"] is None, "")
    check("رفتار: پنجرهٔ نامعتبر در تک‌رویداد هم قطعی می‌شود",
          F.one_event(just.get("iso"), hours=24, past_hours=999).get("past_hours") == 24, "")
finally:
    F.M = _orig

# ── جمع‌بندی ──
print("\n• بررسی‌ها: %d" % len(CHECKS))
if FAILS:
    for name, detail in FAILS:
        print("::error::❌ %s — %s" % (name, detail[:220]))
    print("\n❌ آزمونِ «سوییچِ لحظه‌ایِ اعلام» رد شد — %d از %d بررسی شکست خورد"
          % (len(FAILS), len(CHECKS)))
    sys.exit(1)
print("✅ آزمونِ «سوییچِ لحظه‌ایِ اعلام» پاس شد — کارتِ پیشِ‌رو با لنگرِ ثانیه‌ای و "
      "مسیرِ تک‌رویداد، دقیقاً در لحظهٔ صفر شدنِ شمارشِ معکوس به «اعلام شد + نتیجه» "
      "سوییچ می‌شود (بی‌رفرشِ فهرست، بی‌اعلامِ زودرس، با صبرِ سقف‌دار تا رسیدنِ عدد)")
