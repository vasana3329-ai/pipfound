#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""آزمونِ لایه‌ی ۴.۲۳ — «پرسشِ تأییدِ شکافِ ارزش منصفانه» (خواسته‌ی کاربر).

خواسته: «روندی در اپ طراحی کن که تشخیص بدهد کدام شکافِ ارزش منصفانه تأییدِ بیشتری
دارد و می‌شود به آن اتکا کرد؛ باید به شکلِ پرسش باشد — کاربر آدرسِ شکاف را در یک
تایم‌فریمِ مشخص می‌دهد و اپ تأییدش را بررسی می‌کند.»

منطق (تاکسونومیِ استانداردِ ICT، مطابقِ آن‌چه در آموزش‌های ICT/SMC معیارِ
«گپِ قابلِ اتکا» شمرده می‌شود): یک FVG وقتی «تأییدِ بالا» دارد که (۱) از
دیسپلیسمنت زاده شده باشد (بدنهٔ کندلِ میانی به‌قدرِ معنادار بزرگ‌تر از میانگین)،
(۲) دست‌نخورده/تازه باشد (ایمبالانسِ مصرف‌نشده)، (۳) هم‌جهت با بایاسِ تایم‌فریمِ
بالا باشد، (۴) با POIِ تایم‌فریمِ بالا هم‌پوشانی داشته باشد، (۵) پیش از تولدش
سوئیپِ لیکوئیدیتی و سپس شکستِ ساختار (MSS) رخ داده باشد، (۶) در سمتِ درستِ
رِنج (دیسکانت برای خرید، پریمیوم برای فروش) باشد، (۷) داخلِ کیل‌زونِ سشن باشد،
(۸) با اردر بلاکِ هم‌جهت هم‌پوشانی داشته باشد، (۹) اندازهٔ معقول داشته باشد
(نه void) و (۱۰) در فاصلهٔ اجراییِ قیمت باشد. این لایه چهار چیز را قفل می‌کند:

  ۱) **پویشِ بی‌گیت**: `gap_scan` عمداً گیتِ دیسپلیسمنت ندارد — وگرنه گپِ
     کم‌جان پیش از تطبیق حذف می‌شود و آدرسِ درستِ کاربر «پیدا نشد» می‌گیرد.
  ۲) **تطبیقِ آدرس با آستانهٔ ۵۰٪** و انتخابِ بیشترین هم‌پوشانی.
  ۳) **چرخهٔ عمر و سقف‌ها**: گپِ میتیگیت/پرشده هرگز «قابلِ اتکا» نمی‌شود
     (پرشده ⇒ فقط کاندیدای IFVG)؛ بازارِ بسته سقف C و دادهٔ عقب‌افتاده/نازک سقف B.
  ۴) **دوازده بندِ امتیازِ تأیید** و «قابلِ اتکا = فقط A+/A».

سه بخش:
  ۱) قاعده‌ی نگهبانِ `selfcheck.gap_query_problems` روی مخزنِ سالم صفر خطا.
  ۱.۵) سنجشِ استاتیکِ زنجیره (ثابت‌ها → پویشِ بی‌گیت → دوازده بند → درجه‌ها →
     اندپوینت → پنلِ کرکره‌ای).
  ۲) جهش‌آزمایی: جهش‌های سرخِ نام‌دار روی `gap_query.py` و `app.py` + چهار
     بی‌گناه + یک **جهشِ رفتاری** که ثابت می‌کند سقفِ «گپِ پرشده» دندان دارد
     (برداشتنِ سقف، حکمِ «قابلِ اتکا» روی گپِ مُرده می‌دهد، نه فقط متن را عوض).
  ۳) رفتارِ خالص (بدونِ شبکه): کندلِ ساختگی + تحلیلِ تزریقی ⇒ شمارشِ ۱۲ بند،
     سقفِ ۱۳٫۵، گپِ تازه A+/قابلِ اتکا، گپِ پرشده C/غیرقابلِ اتکا، و آدرسِ
     بی‌ربط «نمی‌خورد» با فهرستِ نزدیک‌ترین‌ها.

آفلاین است (فقط متنِ کد + کندلِ ساختگی؛ شبکه‌ای در کار نیست).
PF_GAPQUERY_NO_MUT=1 بخشِ جهش را رد می‌کند (فرارِ سریعِ CI محدود).
"""
import io
import os
import re
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
    d = tempfile.mkdtemp(prefix="pf_gapq_")
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


def edit_span(d, name, start, end, new=""):
    """پاک‌کردنِ یک بازهٔ پیوسته (برای جهشِ «حذفِ گروهیِ بندهای امتیاز»)."""
    p = os.path.join(d, name)
    txt = io.open(p, encoding="utf-8").read()
    i = txt.find(start)
    if i < 0:
        raise AssertionError("سرآغازِ بازه پیدا نشد: %r" % start[:60])
    j = txt.find(end, i)
    if j <= i:
        raise AssertionError("پایانِ بازه پیدا نشد: %r" % end[:60])
    io.open(p, "w", encoding="utf-8").write(txt[:i] + new + txt[j:])


def scan(d):
    return SC.gap_query_problems(d, SC.page_sources(d))


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
    """بی‌گناه: تغییرِ مجاز نباید قاعده را قرمز کند."""
    d = copy_repo()
    try:
        mutate(d)
        probs, st = scan(d)
        ok = probs == [] and (expect is None or expect(st))
        check("بی‌گناه: " + name, ok,
              "probs=" + str(probs)[:250] + " stats=" + str(st)[:150])
    finally:
        drop(d)


# ══════════════════════════════════════════════════════════════════════════
# سناریوی رفتاریِ مشترک: کندلِ ساختگی با یک گپِ صعودیِ سه‌کندلیِ تازه (و نسخهٔ
# «مصرف‌شده»‌اش). هر تغییری که سقفِ چرخهٔ عمر یا شمارشِ بندها را خراب کند، این
# اسکریپت را می‌شکند — نه فقط متن را.
# ══════════════════════════════════════════════════════════════════════════
BEHAVE = r'''
import gap_query as GQ

T0 = 1_700_000_000.0
TF_S = 900.0
Q_LO, Q_HI = 99.95, 100.05


def _flat(k):
    return {'t': T0 + k * TF_S, 'o': 100.0, 'h': 100.02, 'l': 99.98, 'c': 100.0}


def series(consume=False):
    n = 60
    bars = [_flat(k) for k in range(n - 3)]
    a = {'t': T0 + (n - 3) * TF_S, 'o': 99.92, 'h': 99.95, 'l': 99.90, 'c': 99.92}
    b = {'t': T0 + (n - 2) * TF_S, 'o': 99.95, 'h': 104.10, 'l': 99.94, 'c': 104.00}
    c = {'t': T0 + (n - 1) * TF_S, 'o': 100.08, 'h': 100.10, 'l': 100.05, 'c': 100.05}
    bars += [a, b, c]
    if consume:
        bars.append({'t': T0 + n * TF_S, 'o': 100.08, 'h': 100.10,
                     'l': 99.90, 'c': 100.05})
    return bars


def ana(gap_idx=59):
    return {
        'data': {'state': 'live'},
        'trend': 'bullish',
        'sequence_ok': True,
        'liquidity_sweeps': [{'type': 'bullish_sweep', 'idx': gap_idx - 3, 'level': 99.90}],
        'premium_discount': {'equilibrium': 200.0},
        'order_blocks': [{'type': 'bullish', 'bottom': 99.90, 'top': 100.10}],
        'liquidity': {},
        'FVG_unfilled': [],
    }


def htf_d():
    return {'trend': 'bullish', 'order_blocks': [{'type': 'bullish',
                                                   'bottom': 99.90, 'top': 100.10}],
            'FVG_unfilled': []}


# ── الف) گپِ تازه: دوازده بند، سقفِ ۱۳٫۵، درجهٔ قابلِ اتکا ──
bars = series()
v = GQ.gap_verdict(bars, '15m', Q_LO, Q_HI, d=ana(), d_htf=htf_d(), htf='1h',
                   now=T0 + TF_S * 70)
assert v['ok'] is True and v['found'] is True, v
assert v['state'] == 'fresh', v['state']
assert len(v['checks']) == 12, ('شمارِ بندها', len(v['checks']))
assert abs(v['score']['max'] - 13.5) < 1e-6, v['score']
assert v['grade'] in ('A+', 'A'), ('درجهٔ گپِ تازه', v['grade'], v['score'])
assert v['reliable'] is True, v['score']
assert v['cap'] is None and v['capped'] is False, (v['cap'], v['capped'])
assert v['levels']['invalidate'] is not None and v['levels']['side'] == 'buy', v['levels']

# ── ب) گپِ پُرشده: هرگز «قابلِ اتکا» نیست و فقط کاندیدای IFVG است ──
b2 = series(True)
v2 = GQ.gap_verdict(b2, '15m', Q_LO, Q_HI, d=ana(), d_htf=htf_d(), htf='1h',
                    now=T0 + TF_S * 70)
assert v2['found'] is True and v2['state'] == 'filled', ('وضعیت', v2['state'])
assert len(v2['checks']) == 12 and abs(v2['score']['max'] - 13.5) < 1e-6, v2['score']
assert v2['cap'] == 'C', ('سقفِ گپِ پرشده', v2['cap'])
assert v2['capped'] is True, v2['score']
assert v2['reliable'] is False, ('اتکا به گپِ پرشده!', v2['grade'], v2['score'])
assert 'IFVG' in v2['verdict'], v2['verdict'][:160]

# ── ج) آدرسِ بی‌ربط: بی‌استثنا «نمی‌خورد» + نزدیک‌ترین گپ‌های واقعی ──
v3 = GQ.gap_verdict(bars, '15m', 500.0, 501.0, d=ana(), d_htf=htf_d(), htf='1h',
                    now=T0 + TF_S * 70)
assert v3['ok'] is True and v3['found'] is False, v3
assert v3['checks'] == [], v3['checks']
assert v3['nearest'], v3['nearest']
assert v3['state'] == 'absent', v3['state']

# ── د) تایم‌فریمِ نامعتبر و نمادِ خالی: خطاِ روشن، بی‌شبکه ──
bad = GQ.query('BTCUSDT', '3m')
assert bad['ok'] is False and bad.get('mode') == 'query', bad
assert len(bad['tfs']) == 8, bad.get('tfs')
assert GQ.query('', '15m')['ok'] is False, 'نمادِ خالی باید خطا بدهد'
assert GQ.tf_above('15m') == '1h' and GQ.tf_above('1w') is None, GQ.TF_LADDER
print('OK')
'''


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


NO_MUT = os.environ.get("PF_GAPQUERY_NO_MUT") == "1"
GQ_PATH = os.path.join(HERE, "gap_query.py")
APP_PATH = os.path.join(HERE, "app.py")

# ═══ ۱) قاعده روی مخزنِ سالم ═══
print("═══ ۱) قاعدهٔ نگهبان روی مخزنِ سالم ═══")
p0, s0 = scan(HERE)
check("قاعده: مخزنِ سالم صفر خطا", p0 == [], str(p0)[:300])
check("قاعده: موتورِ gap_query.py سرجایش است", s0.get("file") is True, str(s0))
check("قاعده: پویشِ گپ بی‌گیتِ دیسپلیسمنت است", s0.get("no_scan_gate") is True, str(s0))
check("قاعده: آستانه‌های تأیید معقول‌اند", s0.get("consts") is True, str(s0))
check("قاعده: هر دوازده بندِ امتیاز حاضرند", s0.get("criteria") == 12, str(s0))
check("قاعده: «قابلِ اتکا» فقط A+/A است", s0.get("reliable") is True, str(s0))
check("قاعده: موتور در app.py وارد شده", s0.get("import") is True, str(s0))
check("قاعده: اندپوینتِ /api/gap موتور را صدا می‌زند", s0.get("route") is True, str(s0))
check("قاعده: هر ده شناسهٔ پنلِ پرسش حاضرند", s0.get("ids") == 10, str(s0))
check("قاعده: پنل به مکانیکِ کرکره وصل است", s0.get("fold") is True, str(s0))
check("قاعده: هر دو حالتِ پرسش سیم‌کشی شده‌اند", s0.get("modes") == 2, str(s0))
check("قاعده: آدرس (lo/hi) به سرور می‌رود", s0.get("ask_addr") is True, str(s0))
check("قاعده: حکمِ «قابلِ اتکا» در پنل رندر می‌شود",
      s0.get("reliable_ui") is True, str(s0))

# ═══ ۱.۵) سنجشِ استاتیکِ زنجیرهٔ پرسش ═══
print("═══ ۱.۵) زنجیرهٔ ثابت‌ها → پویشِ بی‌گیت → دوازده بند → درجه‌ها → اندپوینت → پنل ═══")
_gq = io.open(GQ_PATH, encoding="utf-8").read()
_app = io.open(APP_PATH, encoding="utf-8").read()
_page = (SC.page_sources(HERE) or {}).get("HTML") or ""

check("استاتیک: نردبانِ تایم‌فریم کامل است (۸ پله)",
      'TF_LADDER = {"1m"' in _gq and '"1w": None' in _gq, "")
check("استاتیک: گیتِ دیسپلیسمنت با مقدارِ معقول هست",
      SC._GQ_DISP_GATE_RE.search(_gq) is not None
      and 1.0 <= float(SC._GQ_DISP_GATE_RE.search(_gq).group(1)) <= 2.0, "")
check("استاتیک: آستانهٔ دیسپلیسمنتِ قوی از گیتِ پایه بزرگ‌تر است",
      float(SC._GQ_DISP_STRONG_RE.search(_gq).group(1))
      > float(SC._GQ_DISP_GATE_RE.search(_gq).group(1)), "")
check("استاتیک: آستانهٔ هم‌پوشانیِ تطبیق در بازهٔ (۰،۱] است",
      0 < float(SC._GQ_MATCH_MIN_RE.search(_gq).group(1)) <= 1, "")
_scan = SC._py_region(_gq, "def gap_scan(", "def _overlap(")
check("استاتیک: پویشِ gap_scan هیچ اشاره‌ای به گیتِ دیسپلیسمنت ندارد",
      _scan and SC._GQ_SCAN_GATE_RE.search(_scan) is None, _scan[:120])
check("استاتیک: تطبیق با نسبتِ هم‌پوشانی و آستانه انجام می‌شود",
      "MATCH_MIN_OVERLAP" in _gq and "def match_zone(" in _gq, "")
_verdict = SC._py_region(_gq, "def gap_verdict(", "def load(")
check("استاتیک: حکمِ gap_verdict همهٔ دوازده بندِ امتیاز را دارد",
      all(a in _verdict for a in SC._GQ_CRITERIA)
      and len(SC._GQ_ROW_RE.findall(_verdict)) >= len(SC._GQ_CRITERIA), "")
check("استاتیک: چهار حالتِ چرخهٔ عمر در حکم حاضرند",
      set(SC._GQ_STATE_RE.findall(_gq)) >= {"fresh", "touched", "mitigated", "filled"},
      "")
check("استاتیک: گپِ مصرف‌شده سقفِ درجه می‌خورد",
      'if gap["state"] in ("mitigated", "filled"):' in _verdict
      and 'state in ("delayed", "thin")' in _gq, "")
check("استاتیک: فهرستِ درجه‌های قابلِ اتکا فقط A+/A است",
      sorted(re.findall(r'"([^"]+)"', SC._GQ_RELIABLE_RE.search(_gq).group(1)))
      == ["A", "A+"], "")
check("استاتیک: اندپوینتِ /api/gap در app.py هست", 
      'if u.path == "/api/gap":' in _app, "")
_route = SC._py_region(_app, 'if u.path == "/api/gap":', 'if u.path == "/api/health":')
check("استاتیک: اندپوینتِ پرسش از موتورِ گپ (G.query) می‌پرسد",
      "G.query(" in _route, _route[:150])
check("استاتیک: پنلِ پرسش هر ده شناسه را دارد",
      all(('id="%s"' % i) in _page for i in SC._GQ_PANEL_IDS), "")
check("استاتیک: پنل با مکانیکِ کرکره جمع می‌شود",
      SC._GQ_FOLD_CALL_RE.search(_page) is not None, "")
check("استاتیک: هر دو حالتِ پرسش به یک تابع وصل‌اند",
      SC._GQ_MODE_FALSE_RE.search(_page) is not None
      and SC._GQ_MODE_TRUE_RE.search(_page) is not None, "")
check("استاتیک: پنل آدرس (lo/hi) را در درخواست می‌فرستد",
      SC._GQ_SEND_LO_RE.search(_page) is not None
      and SC._GQ_SEND_HI_RE.search(_page) is not None, "")
check("استاتیک: پنل حکمِ «قابلِ اتکا» (g.reliable) را نشان می‌دهد",
      SC._GQ_RELIABLE_UI_RE.search(_page) is not None, "")
_gq_card = SC._py_region(_page, SC._GQ_CARD_START, SC._GQ_CARD_END)
check("استاتیک: کارتِ گپ هیچ `v.` جا نگذاشته (پیشوند `g.` است)",
      bool(_gq_card) and SC._GQ_BARE_V_RE.search(_gq_card) is None,
      str(sorted(set(SC._GQ_BARE_V_RE.findall(_gq_card)))) if _gq_card else "منطقهٔ کارت پیدا نشد")

# ═══ ۲) جهش‌آزماییِ قاعده ═══
if not NO_MUT:
    print("═══ ۲) جهش‌آزماییِ قاعده (قرمز/بی‌گناه/رفتاری) ═══")

    # ── موتورِ گپ (gap_query.py) ──
    red("پویشِ گپ گیتِ دیسپلیسمنت گرفته (آدرسِ درستِ کاربر «پیدا نشد» می‌گیرد)",
        "گیتِ دیسپلیسمنت گرفت",
        lambda d: edit(d, "gap_query.py", "    start = max(2, n - max(lookback, 3))",
                       "    start = max(2, n - max(lookback, 3))\n    _g = DISP_GATE"))
    red("تابعِ گپ‌یابی (gap_scan) حذف شده",
        "تابعِ gap_scan پیدا نشد",
        lambda d: edit(d, "gap_query.py", "def gap_scan(bars, lookback=LOOKBACK):",
                       "def gap_scan_gone(bars, lookback=LOOKBACK):"))
    red("حکمِ تأیید (gap_verdict) حذف شده",
        "حکمِ gap_verdict پیدا نشد",
        lambda d: edit(d, "gap_query.py", "def gap_verdict(bars, tf, lo, hi",
                       "def gap_verdict_gone(bars, tf, lo, hi"))
    red("بندِ امتیازِ کیل‌زون از حکم افتاده",
        "از حکم افتاده",
        lambda d: edit(d, "gap_query.py",
                       'row("%s", in_kz, 0.5,' % SC._GQ_CRITERIA[8],
                       'row("کیل زون بدون معیار", in_kz, 0.5,'))
    red("گروهی از بندهای امتیاز (۷ تا ۱۲) از حکم حذف شده‌اند",
        "لازم است",
        lambda d: edit_span(d, "gap_query.py", "    # ۷) سمتِ بازار",
                            '    got = sum(c["got"] for c in checks)'))
    red("درجهٔ A+ از فهرستِ «قابلِ اتکا» افتاده",
        "شامل نمی‌شوند",
        lambda d: edit(d, "gap_query.py", 'RELIABLE_GRADES = ("A+", "A")',
                       'RELIABLE_GRADES = ("A",)'))
    red("درجه‌های میانی (B) «قابلِ اتکا» شده‌اند",
        "راه پیدا کردند",
        lambda d: edit(d, "gap_query.py", 'RELIABLE_GRADES = ("A+", "A")',
                       'RELIABLE_GRADES = ("A+", "A", "B")'))
    red("آستانهٔ هم‌پوشانیِ تطبیق از بازه بیرون رفته (۱٫۵)",
        "بیرونِ بازهٔ (۰،۱]",
        lambda d: edit(d, "gap_query.py", "MATCH_MIN_OVERLAP = 0.5",
                       "MATCH_MIN_OVERLAP = 1.5"))
    red("آستانهٔ دیسپلیسمنتِ قوی زیرِ گیتِ پایه رفته",
        "بزرگ‌تر از گیتِ پایه",
        lambda d: edit(d, "gap_query.py", "DISP_STRONG = 2.3", "DISP_STRONG = 1.2"))
    red("گیتِ دیسپلیسمنت از بازهٔ معقول بیرون رفته (۳٫۰)",
        "از بازهٔ معقول بیرون",
        lambda d: edit(d, "gap_query.py", "DISP_GATE = 1.3", "DISP_GATE = 3.0"))
    red("ثابتِ گیتِ دیسپلیسمنت ناقص/گم شده",
        "ناقص‌اند",
        lambda d: edit(d, "gap_query.py", "DISP_GATE = 1.3", "DISP_GATE_BASE = 1.3"))

    # ── رابط (app.py) ──
    red("موتورِ گپ در app.py وارد نشده",
        "وارد نشده",
        lambda d: edit(d, "app.py", "    import gap_query as G",
                       "    import gap_query_off as G"))
    red("مسیرِ /api/gap حذف شده",
        "پیدا نشد",
        lambda d: edit(d, "app.py", 'if u.path == "/api/gap":',
                       'if u.path == "/api/gapx":'))
    red("مسیرِ /api/gap موتورِ گپ را صدا نمی‌زند",
        "صدا نمی‌زند",
        lambda d: edit(d, "app.py", "G.query(sym, tf, lo, hi)", "{}"))
    red("پنلِ پرسش به مکانیکِ کرکره وصل نیست",
        "به مکانیکِ کرکره وصل نیست",
        lambda d: edit(d, "app.py", 'pfFold("gapDock","gapToggle","gapBody");', "void 0;"))
    red("شناسهٔ خروجیِ پنلِ پرسش (gapRes) گم شده",
        "غایب‌اند",
        lambda d: edit(d, "app.py", 'id="gapRes"', 'id="gapResBox"'))
    red("پنل آدرس (lo/hi) را به سرور نمی‌فرستد",
        "به سرور نمی‌فرستد",
        lambda d: edit(d, "app.py", 'if(!listMode){ qs.set("lo", lo); qs.set("hi", hi); }',
                       "if(!listMode){ }"))
    red("حکمِ «قابلِ اتکا» در پنل رندر نمی‌شود",
        "رندر نمی‌شود",
        lambda d: edit(d, "app.py", "${g.reliable?", "${false?"))
    red("کارتِ گپ به متغیرِ `v` برمی‌گردد (هم نشانگرِ آرشیو کور می‌شود، هم در مرورگر خطای زمانِ اجرا)",
        "به متغیرِ `v` برمی‌گردد",
        lambda d: edit(d, "app.py", "${g.invalidations.map(", "${v.invalidations.map("))
    red("حالتِ «گپ‌های همین تایم‌فریم» سیم‌کشی نشده",
        "یکی از دو مسیرِ پرسش مرده است",
        lambda d: edit(d, "app.py", "pfGapAsk(false)", "pfGapAskOff(false)"))

    # ── بی‌گناه‌ها: نباید قرمز شوند ──
    green("گشادکردنِ گیتِ دیسپلیسمنت در بازهٔ معقول (۱٫۳ → ۱٫۴)",
          lambda d: edit(d, "gap_query.py", "DISP_GATE = 1.3", "DISP_GATE = 1.4"),
          lambda st: st.get("consts") is True)
    green("کامنتِ تازه کنارِ آستانهٔ هم‌پوشانی",
          lambda d: edit(d, "gap_query.py", "MATCH_MIN_OVERLAP = 0.5",
                         "MATCH_MIN_OVERLAP = 0.5   # نیمِ کوچک‌ترینِ دو ناحیه"),
          lambda st: st.get("consts") is True)
    green("افزودنِ یک ردیفِ امتیازِ خنثی (وزنِ صفر)",
          lambda d: edit(d, "gap_query.py", '    got = sum(c["got"] for c in checks)',
                         '    row("یادداشتِ سنجش", True, 0.0, "بدون اثر بر امتیاز")\n'
                         '    got = sum(c["got"] for c in checks)'),
          lambda st: st.get("criteria") == 12)
    green("افزودنِ ویژگیِ نمایشیِ تازه روی خروجیِ پنل",
          lambda d: edit(d, "app.py", 'id="gapRes"', 'id="gapRes" data-live="1"'),
          lambda st: st.get("ids") == 10)

    # جهشِ رفتاری: سقفِ «گپِ پرشده/میتیگیت» هیچ‌وقت نباید بی‌اثر شود — برداشتنش
    # باید سناریوی ب/ب را بشکند (اتکا به گپِ مُرده)، نه فقط متن را قرمز کند.
    red_behavior("سقفِ چرخهٔ عمر (گپِ پرشده ⇒ درجهٔ C) برداشته شود",
                 lambda d: edit(d, "gap_query.py",
                                'cap = "C" if cap is None else _cap(cap, "C")',
                                'cap = cap'))

# ═══ ۳) رفتارِ خالص (کندلِ ساختگی — بدونِ شبکه) ═══
print("═══ ۳) رفتارِ خالصِ پرسشِ تأیید (بدونِ شبکه) ═══")
_p = subprocess.run([sys.executable, "-c", BEHAVE], cwd=HERE,
                    capture_output=True, text=True, timeout=120)
check("رفتار: سناریوی گپِ تازه/پرشده/آدرسِ بی‌ربط/خطاها درست است",
      _p.returncode == 0 and "OK" in (_p.stdout or ""),
      ("rc=%s out=%s err=%s" % (_p.returncode, (_p.stdout or "")[-300:],
                                (_p.stderr or "")[-400:])))

# ── جمع‌بندی ──
print("\n• بررسی‌ها: %d" % len(CHECKS))
if FAILS:
    for name, detail in FAILS:
        print("::error::❌ %s — %s" % (name, detail[:220]))
    print("\n❌ آزمونِ «پرسشِ تأییدِ شکافِ ارزش منصفانه» رد شد — %d از %d بررسی شکست خورد"
          % (len(FAILS), len(CHECKS)))
    sys.exit(1)
print("✅ آزمونِ «پرسشِ تأییدِ شکافِ ارزش منصفانه» پاس شد — کاربر آدرسِ گپ را در یک "
      "تایم‌فریم می‌دهد و اپ همان گپِ واقعی را با دوازده بندِ تأییدِ ICT نمره می‌دهد، "
      "چرخهٔ عمرش را می‌گوید و صریح می‌گوید می‌شود به آن اتکا کرد یا نه")
