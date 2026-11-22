#!/usr/bin/env python3
"""تستِ «هم‌ترازیِ ۴ساعته» — تجمیعِ تایم‌فریمِ H4 روی دادهٔ ثابت قفل می‌شود.

پیشینه (آخرین بخشِ D11/P1-3، و یافتهٔ D3/P0-3 در ممیزی):
«برشِ ۴ساعته بر پایه‌ی `t // 14400` (یا منبعِ درستِ ۴ساعته) تا PD/OTE با چارتِ
کارگزار یکی شود». Yahoo برای کندلِ ۴ساعته دادهٔ **۱ساعته** می‌دهد و `resample`
آن را جمع می‌زد؛ اما پیاده‌سازیِ قبلی آرایه را از **ابتدای خودش** دسته‌دسته می‌کرد
(`range(0, len(bars)-len(bars)%n, n)`). یعنی مرزِ سبدها به این گره می‌خورد که
منبع از کجا شروع کرده باشد:

    منبع: ۰۱:۰۰ ۰۲:۰۰ ۰۳:۰۰ ...  →  سبدهای «۴ساعته»: ۰۱–۰۵، ۰۵–۰۹، ...
    چارتِ کارگزار:                    سبدهای واقعی:    ۰۰–۰۴، ۰۴–۰۸، ...

آن یک‌ساعت جابه‌جایی، سوینگ/FVG/اُردربلاک و مهم‌تر از همه PD/OTE را روی رِنجِ
غلط می‌نشاند؛ پس پلنِ اپ و چارتِ کارگزار «بی‌صدا» فرق می‌کردند (ریشه‌ی همان
شکایتِ «سطوح روی چارتِ من نیست»). حالا هر کندل با `t // tf_sec * tf_sec` گره
می‌خورد و فقط سبدهای کامل منتشر می‌شوند.

این تست قفل می‌کند:
  ۱) قراردادِ طولِ تایم‌فریم (۱۴۴۰۰ = ۴×۳۶۰۰).
  ۲) تجمیعِ طلایی روی دادهٔ ثابتِ هم‌تراز — اعدادِ دستی‌محاسبه (o/h/l/c/v).
  ۳) هم‌ترازی وقتی منبع **روی مرز شروع نمی‌شود** + بی‌تفاوتیِ نسبت به یک
     تایم‌فریم جابه‌جاییِ کامل (لنگرِ UTC، نه «شروعِ آرایه»).
  ۴) مرزِ دقیق (کندلِ روی مرز، سبدِ تازه باز می‌کند)، سبدِ ناقصِ ابتدا/انتها،
     و حفرهٔ داده — هیچ پنجره‌ی ناقصی جای کندلِ بستهٔ کامل جا نمی‌زند.
  ۵) سازگاریِ عقب‌رو: حدسِ خودکارِ طولِ تایم‌فریم + برابری با پیاده‌سازیِ
     مستقل (مرجعِ سبدبندی).
  ۶) اثرِ ناه‌مراستایی بر PD/OTE — جهتِ پایِ ایمپالس و رِنج عوض می‌شود، یعنی
     ناهم‌خوانیِ چارت **بی‌صدا نمی‌ماند**.
  ۷) مسیرِ زندهٔ Yahoo (`fetch_yahoo`) با پاسخِ ثابت و بدونِ شبکه.

کاملاً آفلاین و قطعی (بدونِ شبکه؛ گاردِ آفلاین هم نصب می‌شود).
اجرا:  python3 h4_alignment_test.py            (خروجی ۰ = سالم)
       PF_H4_NO_MUT=1 python3 h4_alignment_test.py   (بدونِ بخشِ ۸)
"""
import datetime
import json
import math
import os
import shutil
import socket as _socket
import subprocess
import sys
import tempfile
import urllib.request as _urllib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ── نگهبانِ هرمتیک: این تست هرگز نباید به شبکه دست بزند ─────────────────
# تجمیعِ تایم‌فریم کاملاً حسابی است؛ اگر روزی کسی در مسیرِ آن fetch اضافه کند،
# نتیجه به وضعیتِ شبکه (و زمانِ DNS روی شبکهٔ کند/قطع) گره می‌خورد. گارد می‌گذریم
# تا آن اتفاق **بلند** شکست بخورد، نه خاموش.
NET_ATTEMPTS = []


def _no_network(*a, **kw):
    NET_ATTEMPTS.append(str(a[0])[:80] if a else "")
    raise OSError("offline-guard: دسترسیِ شبکه در این تست بسته است")


_socket.getaddrinfo = _no_network
_socket.create_connection = _no_network
_urllib.urlopen = _no_network

import smc_engine as E          # noqa: E402

TEST_NAME = os.path.basename(os.path.abspath(__file__))
CHECKS = []
FAILS = []
NOTES = []


def check(name, cond, detail=""):
    CHECKS.append(name)
    if not cond:
        FAILS.append((name, detail))
    return bool(cond)


def j(x):
    """نمایشِ متعارف برای مقایسهٔ عددی/ساختاری."""
    return json.dumps(x, ensure_ascii=False, sort_keys=True)


def safe(fn, *a, **kw):
    """فراخوانیِ محافظت‌شده: خروجی (نتیجه، خطا) — تا استثنا تست را کرش نکند،
    بلکه به‌شکلِ یک بررسیِ رد‌شدهٔ نام‌دار گزارش شود."""
    try:
        return fn(*a, **kw), None
    except Exception as ex:                      # noqa: BLE001
        return None, f"{type(ex).__name__}: {ex}"


# ═══════════════════════════════════════════════════════════════════
# ساعتِ ثابتِ تست + ابزارها
# ═══════════════════════════════════════════════════════════════════
# دوشنبه ۲۰۲۶-۰۹-۲۱ ۰۰:۰۰ UTC — خودش مضربِ ۱۴۴۰۰ است (لنگرِ مرزِ ۴ساعته).
BASE = int(datetime.datetime(2026, 9, 21, 0, 0, tzinfo=datetime.timezone.utc).timestamp())
H4 = 14400          # طولِ کندلِ ۴ساعته به ثانیه
H1 = 3600


def bar(t, o, h, l, c, v=10.0):
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}


def lin_1h(n, start_i=0):
    """سریِ ۱ساعتهٔ خطیِ قطعی: o=100+i … تا اعدادِ طلایی دستی قابلِ بازبینی باشند."""
    out = []
    for i in range(n):
        t = BASE + (start_i + i) * H1
        o = 100.0 + i
        c = o + 0.5
        out.append(bar(t, o, c + 0.25, o - 0.25, c, 10.0 + i))
    return out


def wave_1h(n):
    """سریِ ۱ساعتهٔ موجیِ قطعی — برای PD/OTE که سوینگ و پایِ ایمپالس لازم دارد."""
    out = []
    prev = 100.0
    for i in range(n):
        c = 100.0 + 5.0 * math.sin(i / 3.0) \
            + (4.0 if i % 24 == 5 else 0.0) - (4.0 if i % 24 == 17 else 0.0)
        o = prev
        prev = c
        out.append(bar(BASE + i * H1, round(o, 4), round(max(o, c) + 0.3, 4),
                       round(min(o, c) - 0.3, 4), round(c, 4), 10.0 + i))
    return out


def ref_4h(bars, n, tf_sec):
    """پیاده‌سازیِ **مستقلِ** مرجع — سبدبندی با دیکشنری و کلیدِ مرز (برای مقایسهٔ
    برابری با `E.resample`؛ عمداً الگوریتمِ جداگانه، نه همان کدِ موتور)."""
    buckets = {}
    for b in bars:
        buckets.setdefault((b["t"] // tf_sec) * tf_sec, []).append(b)
    out = []
    for k in sorted(buckets):
        g = buckets[k]
        if len(g) == n:                      # فقط سبدِ کامل
            out.append({"t": k, "o": g[0]["o"], "h": max(x["h"] for x in g),
                        "l": min(x["l"] for x in g), "c": g[-1]["c"],
                        "v": sum(x["v"] for x in g)})
    return out


def legacy_chunk(bars, n):
    """پیاده‌سازیِ **قبل از فیکس** (دسته‌بندی از ابتدای آرایه) — برای مستندسازیِ
    اینکه ریشهٔ باگ دقیقاً همین بود و تست همان را می‌گیرد."""
    out = []
    for i in range(0, len(bars) - len(bars) % n, n):
        g = bars[i:i + n]
        if len(g) < n:
            break
        out.append({"t": g[0]["t"], "o": g[0]["o"], "h": max(x["h"] for x in g),
                    "l": min(x["l"] for x in g), "c": g[-1]["c"],
                    "v": sum(x["v"] for x in g)})
    return out


# ═══════════════════════════════════════════════════════════════════
print("═══ ۱) قراردادِ طولِ تایم‌فریم و مرزِ ۴ساعته ═══")
check("طولِ ۴ساعته = ۱۴۴۰۰ ثانیه است", E.TF_SECONDS.get("4h") == 14400,
      str(E.TF_SECONDS.get("4h")))
check("۱۴۴۰۰ = ۴ × ۳۶۰۰ (تجمیعِ چهار ۱ساعته)", H4 == 4 * H1 and E.TF_SECONDS["4h"] == 4 * E.TF_SECONDS["1h"],
      f"4h={E.TF_SECONDS['4h']} 1h={E.TF_SECONDS['1h']}")
check("`tf_seconds(\"4h\")` همان ۱۴۴۰۰ می‌دهد", E.tf_seconds("4h") == H4, str(E.tf_seconds("4h")))
check("لنگرِ ساعتِ تست روی مرزِ ۴ساعته است (BASE % 14400 == 0)", BASE % H4 == 0, str(BASE % H4))
check("لنگرِ تست روی مرزِ روز هم هست (BASE % 86400 == 0)", BASE % 86400 == 0, str(BASE % 86400))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۲) تجمیعِ طلایی روی دادهٔ ثابتِ هم‌تراز (۲۴ کندلِ ۱ساعته → ۶ کندلِ ۴ساعته) ═══")
src = lin_1h(24)
got = E.resample(src, 4, tf_sec=H4)
check("۲۴ کندلِ ۱ساعته ⇒ ۶ کندلِ ۴ساعته", len(got) == 6, str(len(got)))
if len(got) == 6:
    g0 = got[0]
    check("کندلِ اول: زمانِ بازشدن = مرزِ سبد (`t` = مرزِ ۴ساعته، نه زمانِ دلخواه)",
          g0["t"] == BASE, str(g0["t"]))
    check("کندلِ اول: open = openِ اولین ۱ساعته", g0["o"] == 100.0, str(g0["o"]))
    check("کندلِ اول: close = closeِ آخرین ۱ساعته", g0["c"] == 103.5, str(g0["c"]))
    check("کندلِ اول: high = بیشینهٔ highها (۱۰۳.۷۵)", g0["h"] == 103.75, str(g0["h"]))
    check("کندلِ اول: low = کمینهٔ lowها (۹۹.۷۵)", g0["l"] == 99.75, str(g0["l"]))
    check("کندلِ اول: volume = مجموع (۴۶.۰)", g0["v"] == 46.0, str(g0["v"]))
    gl = got[-1]
    check("کندلِ آخر: زمانِ بازشدن = BASE + ۲۰ ساعت", gl["t"] == BASE + 20 * H1, str(gl["t"]))
    check("کندلِ آخر: OHLCV کاملِ دستی‌محاسبه (۱۲۰ / ۱۲۳.۷۵ / ۱۱۹.۷۵ / ۱۲۳.۵ / ۱۲۶)",
          (gl["o"], gl["h"], gl["l"], gl["c"], gl["v"]) == (120.0, 123.75, 119.75, 123.5, 126.0),
          j(gl))
    check("زمان‌ها اکیداً صعودی و یکتا هستند",
          all(got[i + 1]["t"] - got[i]["t"] == H4 for i in range(len(got) - 1)),
          str([x["t"] for x in got]))
    check("ترتیبِ سبدها دقیقاً ۶ مرزِ پشت‌سرهم است",
          [x["t"] for x in got] == [BASE + k * H4 for k in range(6)],
          str([x["t"] for x in got]))
    check("برابری با پیاده‌سازیِ مستقلِ مرجع (سبدبندیِ دیکشنری)", got == ref_4h(src, 4, H4),
          j(ref_4h(src, 4, H4))[:200])
    check("مجموعِ حجمِ خروجی = مجموعِ حجمِ ورودی (هیچ کندلی گم نمی‌شود)",
          sum(x["v"] for x in got) == sum(x["v"] for x in src),
          f"{sum(x['v'] for x in got)} vs {sum(x['v'] for x in src)}")
    check("سریِ هم‌تراز: خروجیِ جدید با الگوریتمِ قدیم یکسان است (بدونِ رگرسیون)",
          got == legacy_chunk(src, 4), "اختلاف در سریِ هم‌ترازِ بدونِ حفره")
# این بررسی بیرون از بلوکِ بالا می‌ماند تا اگر تجمیع به‌کل خالی شد هم **نام‌دار**
# شکست بخورد (نه اینکه با سرصفحهٔ بخش اشتباه گرفته شود).
check("همهٔ زمان‌های خروجی مضربِ ۱۴۴۰۰‌اند",
      bool(got) and all(x["t"] % H4 == 0 for x in got),
      str([x["t"] % H4 for x in got]))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۳) قلبِ D3/P0-3: منبع روی مرز شروع نمی‌شود (شروع از ۰۱:۰۰) ═══")
off = lin_1h(24, start_i=1)              # اولین کندل: BASE + ۰۱:۰۰
got_off = E.resample(off, 4, tf_sec=H4)
check("سریِ آفست‌شده: سبدِ ناقصِ ابتدا می‌افتد ⇒ ۵ کندلِ کامل",
      len(got_off) == 5, str(len(got_off)))
check("سریِ آفست‌شده: **همهٔ** زمان‌ها باز هم مضربِ ۱۴۴۰۰‌اند",
      bool(got_off) and all(x["t"] % H4 == 0 for x in got_off),
      str([x["t"] % H4 for x in got_off]))
if got_off:
    check("سریِ آفست‌شده: اولین کندل روی مرزِ ۰۴:۰۰ می‌نشیند (نه ۰۱:۰۰)",
          got_off[0]["t"] == BASE + H4, str(got_off[0]["t"]))
    check("سریِ آفست‌شده: OHLCV کندلِ اول از کندل‌های ۰۴:۰۰–۰۷:۰۰ است",
          (got_off[0]["o"], got_off[0]["h"], got_off[0]["l"], got_off[0]["c"], got_off[0]["v"])
          == (103.0, 106.75, 102.75, 106.5, 58.0), j(got_off[0]))
    check("سریِ آفست‌شده: برابری با مرجعِ مستقل", got_off == ref_4h(off, 4, H4),
          j(ref_4h(off, 4, H4))[:200])
_leg = legacy_chunk(off, 4)
check("الگوریتمِ قدیم روی همین داده، سبدها را **ناهم‌تراز** می‌بست (ریشهٔ باگ)",
      bool(_leg) and _leg[0]["t"] % H4 != 0, f"legacy[0].t % 14400 = {_leg[0]['t'] % H4}")
check("الگوریتمِ قدیم و جدید روی دادهٔ آفست‌شده واقعاً متفاوت‌اند (باگ رفع شده)",
      bool(_leg) and _leg != got_off, f"legacy_n={len(_leg)} new_n={len(got_off)}")
# بی‌تفاوتیِ نسبت به جابه‌جاییِ یک تایم‌فریمِ کامل: شبکه فقط یک کندل جلو می‌رود.
sh4 = [dict(b, t=b["t"] + H4) for b in src]
got_sh4 = E.resample(sh4, 4, tf_sec=H4)
check("جابه‌جاییِ منبع به‌اندازهٔ یک ۴ساعته: شبکه دقیقاً یک کندل جابه‌جا می‌شود",
      got_sh4 == [dict(x, t=x["t"] + H4) for x in got],
      f"new={len(got_sh4)} base={len(got)} · {j(got_sh4)[:200]}")
check("هم‌ترازی به «مرزِ UTC» گره خورده، نه به «شروعِ آرایه»: خروجیِ جابه‌جاییِ کامل هم‌تراز است",
      bool(got_sh4) and all(x["t"] % H4 == 0 for x in got_sh4),
      str([x["t"] % H4 for x in got_sh4]))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۴) مرزِ دقیق، سبدِ ناقص و حفرهٔ داده ═══")
six = lin_1h(6)                          # ۰۰:۰۰ … ۰۵:۰۰
g6 = E.resample(six, 4, tf_sec=H4)
check("کندلِ دقیقاً روی مرز (۰۴:۰۰) سبدِ **تازه** باز می‌کند، با قبلی جمع نمی‌شود",
      len(g6) == 1 and g6[0]["t"] == BASE, f"n={len(g6)} t={[x['t'] for x in g6]}")
check("سبدِ ناقصِ انتها (کندلِ ۴ساعتهٔ هنوز-باز) منتشر نمی‌شود",
      all(x["t"] + H4 <= BASE + 6 * H1 for x in g6), str([x["t"] for x in g6]))
check("ورودیِ خالی ⇒ خروجیِ خالی", E.resample([], 4, tf_sec=H4) == [],
      j(E.resample([], 4, tf_sec=H4)))
check("ورودیِ کم‌تر از n کندل ⇒ هیچ سبدی (سبدِ ناقص ساخته نمی‌شود)",
      E.resample(lin_1h(3), 4, tf_sec=H4) == [], j(E.resample(lin_1h(3), 4, tf_sec=H4)))
gap = [b for i, b in enumerate(lin_1h(24)) if i != 5]      # ۱ساعت حفره در سبدِ ۰۴:۰۰
gg = E.resample(gap, 4, tf_sec=H4)
check("حفرهٔ داده: سبدِ ناقص (۳ کندل) حذف می‌شود — کندلِ «کاملِ ساختگی» ساخته نمی‌شود",
      len(gg) == 5 and all(x["t"] != BASE + H4 for x in gg),
      f"n={len(gg)} t={[x['t'] for x in gg]}")
check("حفرهٔ داده: بقیهٔ سبدها دست‌نخورده و هم‌تراز می‌مانند",
      all(x["t"] % H4 == 0 for x in gg) and gg == ref_4h(gap, 4, H4),
      j([x["t"] for x in gg]))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۵) سازگاریِ عقب‌رو: حدسِ خودکارِ طولِ تایم‌فریم ═══")
check("فراخوانِ بدونِ tf_sec هم همان نتیجه را می‌دهد (حدس: میانهٔ فاصله‌ها × n)",
      E.resample(src, 4) == got, "تفاوت در حالتِ بدونِ tf_sec")
check("فراخوانِ بدونِ tf_sec روی دادهٔ آفست‌شده هم همان نتیجه را می‌دهد",
      E.resample(off, 4) == got_off, "تفاوت در حالتِ بدونِ tf_sec/آفست")
check("tf_sec صریحِ غلط نتیجهٔ متفاوت می‌دهد (آرگومان واقعاً اثر دارد)",
      E.resample(src, 4, tf_sec=H1) == [], j(E.resample(src, 4, tf_sec=H1)))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۶) اثرِ ناه‌مراستایی بر PD/OTE — ناهم‌خوانیِ چارت بی‌صدا نمی‌ماند ═══")
hr = wave_1h(168)
for _jj, _px in enumerate([96.0, 98.0, 100.0, 104.0]):     # پایِ ایمپالسِ انتهایی
    _i = 164 + _jj
    hr[_i] = bar(BASE + _i * H1, _px - 1.0, _px + (2.5 if _jj == 3 else 0.4),
                 _px - 1.2, _px, 10.0 + _i)
h4a = E.resample(hr, 4, tf_sec=H4)
check("سریِ موجیِ ۱۶۸ کندلِ ۱ساعته ⇒ ۴۲ کندلِ ۴ساعته", len(h4a) == 42, str(len(h4a)))
now_a = (h4a[-1]["t"] + H4) if h4a else 0
ra = safe(E.analyze_bars, h4a, "4h", now=now_a)
check("تحلیلِ ۴ساعتهٔ هم‌تراز بدونِ خطا اجرا می‌شود", ra[1] is None, str(ra[1]))
pda = (ra[0] or {}).get("premium_discount") if ra[1] is None else None
check("PD روی سریِ هم‌تراز ساخته می‌شود (نه None)", bool(pda), j(pda))
top = (pda or {}).get("range_top")
bot = (pda or {}).get("range_bottom")
rng = (top - bot) if (top is not None and bot is not None) else 0.0
check("PD طلاییِ هم‌تراز: رِنج/اکولیبریوم مطابقِ اعدادِ ثابت",
      (top, bot, (pda or {}).get("equilibrium")) == (105.1797, 94.702, 99.94085),
      f"top={top} bot={bot} eq={(pda or {}).get('equilibrium')}")
check("PD طلایی: جهتِ پایِ ایمپالس و درصدِ محلِ قیمت مطابقِ ثابت",
      ((pda or {}).get("leg_dir"), (pda or {}).get("price_pct")) == (-1, 88.7),
      f"leg_dir={(pda or {}).get('leg_dir')} pct={(pda or {}).get('price_pct')}")
check("OTE طلاییِ خرید = bot + (۰.۲۱ … ۰.۳۸)×rng",
      bool(pda) and pda["ote_long_buy_zone"]
      == (round(bot + rng * 0.21, 5), round(bot + rng * 0.38, 5)),
      j((pda or {}).get("ote_long_buy_zone")))
check("OTE طلاییِ فروش = top − (۰.۳۸ … ۰.۲۱)×rng",
      bool(pda) and pda["ote_short_sell_zone"]
      == (round(top - rng * 0.38, 5), round(top - rng * 0.21, 5)),
      j((pda or {}).get("ote_short_sell_zone")))
check("OTE طلاییِ خرید مطابقِ عددِ ثابتِ تست",
      (pda or {}).get("ote_long_buy_zone") == (96.90232, 98.68353),
      j((pda or {}).get("ote_long_buy_zone")))
check("OTE طلاییِ فروش مطابقِ عددِ ثابتِ تست",
      (pda or {}).get("ote_short_sell_zone") == (101.19817, 102.97938),
      j((pda or {}).get("ote_short_sell_zone")))
hr_m = [dict(b, t=b["t"] + H1) for b in hr]            # منبعِ ناهم‌تراز: شروع از ۰۱:۰۰
h4m = E.resample(hr_m, 4, tf_sec=H4)
check("ناهم‌ترازی: شبکهٔ کندل‌های ۴ساعته واقعاً متفاوت است", h4m != h4a,
      f"len {len(h4m)} vs {len(h4a)}")
rm = safe(E.analyze_bars, h4m, "4h", now=(h4m[-1]["t"] + H4) if h4m else 0)
pdm = (rm[0] or {}).get("premium_discount") if rm[1] is None else None
check("تحلیلِ ۴ساعتهٔ ناهم‌تراز هم بدونِ خطا اجرا می‌شود", rm[1] is None, str(rm[1]))
check("ناهم‌ترازی: رِنجِ PD عوض می‌شود (رِنجِ غلط ⇒ پلنِ غلط)",
      bool(pdm) and (pdm["range_top"], pdm["range_bottom"]) != (top, bot),
      j(pdm))
check("ناهم‌ترازی: **جهتِ پایِ ایمپالس** برمی‌گردد (اثرِ درجه‌یک بر پلن)",
      bool(pdm) and pdm["leg_dir"] != (pda or {}).get("leg_dir"),
      f"aligned={(pda or {}).get('leg_dir')} misaligned={(pdm or {}).get('leg_dir')}")
check("ناهم‌ترازی: پلن عوض می‌شود، یعنی ناهم‌خوانیِ چارت بی‌صدا نیست",
      bool(pdm) and bool(pda) and pdm != pda, j(pdm))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۷) مسیرِ زندهٔ Yahoo: `fetch_yahoo` کندلِ ۴ساعتهٔ هم‌تراز می‌دهد ═══")
CALLED = []


def fake_http_get(url):
    """پاسخِ ثابتِ Yahoo (۱ساعته، شروع از ۰۱:۰۰) — بدونِ ذره‌ای شبکه."""
    CALLED.append(url)
    ts = [BASE + H1 + i * H1 for i in range(24)]
    return {"chart": {"result": [{
        "timestamp": ts,
        "indicators": {"quote": [{
            "open": [100.0 + i for i in range(24)],
            "high": [100.75 + i for i in range(24)],
            "low": [99.75 + i for i in range(24)],
            "close": [100.5 + i for i in range(24)],
            "volume": [10.0 + i for i in range(24)],
        }]},
    }]}}


_real_http = E.http_get
E.http_get = fake_http_get
try:
    live = safe(E.fetch_yahoo, "EURUSD=X", "4h", 100)[0]
finally:
    E.http_get = _real_http
check("مسیرِ زنده: درخواستِ Yahoo از نقطهٔ درست رفت (بدونِ شبکه)",
      bool(CALLED) and "finance.yahoo.com" in CALLED[0], str(CALLED[:1]))
check("مسیرِ زنده: ۲۴ کندلِ ۱ساعته ⇒ ۵ کندلِ ۴ساعته (سبدِ ناقصِ ابتدا می‌افتد)",
      isinstance(live, list) and len(live) == 5, str(len(live) if isinstance(live, list) else live))
if isinstance(live, list) and live:
    check("مسیرِ زنده: همهٔ کندل‌های ۴ساعته روی مرزِ ۱۴۴۰۰ نشسته‌اند",
          all(x["t"] % H4 == 0 for x in live), str([x["t"] % H4 for x in live]))
    check("مسیرِ زنده: اولین کندل = مرزِ ۰۴:۰۰ با OHLCV درست",
          (live[0]["t"], live[0]["o"], live[0]["h"], live[0]["l"], live[0]["c"], live[0]["v"])
          == (BASE + H4, 103.0, 106.75, 102.75, 106.5, 58.0), j(live[0]))
    check("مسیرِ زنده: برابری با aggregatorِ مستقیم روی همان داده",
          live == E.resample([bar(t, 100.0 + i, 100.75 + i, 99.75 + i, 100.5 + i, 10.0 + i)
                              for i, t in enumerate([BASE + H1 + k * H1 for k in range(24)])],
                             4, tf_sec=H4), j(live)[:200])
_leg_live = legacy_chunk([bar(t, 100.0 + i, 100.75 + i, 99.75 + i, 100.5 + i, 10.0 + i)
                          for i, t in enumerate([BASE + H1 + k * H1 for k in range(24)])], 4)
check("مسیرِ زنده: الگوریتمِ قدیم روی همین داده کندلِ ۰۱:۰۰–۰۵:۰۰ می‌ساخت (باگِ رفع‌شده)",
      bool(_leg_live) and _leg_live[0]["t"] % H4 != 0, f"legacy[0].t%14400={_leg_live[0]['t'] % H4}")

# ═══════════════════════════════════════════════════════════════════
#  ۸) جهش‌آزمایی: تست باید دندان داشته باشد
# ═══════════════════════════════════════════════════════════════════
ANCHORS = {
    "align_key": ("smc_engine.py", '        k=(b["t"]//tf_sec)*tf_sec'),
    "mid_full": ("smc_engine.py", "            if len(grp)==n: out.append(_fold_group(grp,key))"),
    "tail_full": ("smc_engine.py", "    if key is not None and len(grp)==n: out.append(_fold_group(grp,key))"),
    "call_sec": ("smc_engine.py", '    if tf=="4h": out=resample(out,4,tf_sec=TF_SECONDS["4h"])'),
    "ote_const": ("smc_engine.py", "(round(bot+rng*0.21,5), round(bot+rng*0.38,5))"),
    "engine_import": ("smc_engine.py",
                      "import sys, json, urllib.request, urllib.parse, argparse, datetime, math, ssl, time"),
}


def mutate(src, muts):
    """جهش‌ها را اعمال می‌کند؛ هر نشانه‌ای که پیدا نشود → خطای صریح (نه سبزِ بی‌صدا)."""
    out = src
    for needle, repl, count in muts:
        got_n = out.count(needle)
        if got_n != count:
            return None, f"نشانهٔ جهش {count} بار انتظار می‌رفت ولی {got_n} بار بود: {needle[:70]}"
        out = out.replace(needle, repl)
    return out, None


def run_sandbox(target, muts=None):
    """کپیِ موقتِ کلِ ماژول‌ها، اعمالِ جهش روی `target`، اجرا → (کدِ خروج، خروجی)."""
    d = tempfile.mkdtemp(prefix="pf_h4_mut_")
    try:
        for fn in sorted(os.listdir(HERE)):
            if fn.endswith(".py"):
                shutil.copyfile(os.path.join(HERE, fn), os.path.join(d, fn))
        if muts is not None:
            path = os.path.join(d, target)
            with open(path, encoding="utf-8") as f:
                src = f.read()
            src, err = mutate(src, muts)
            if err:
                return None, err
            with open(path, "w", encoding="utf-8") as f:
                f.write(src)
        env = dict(os.environ)
        env["PF_H4_NO_MUT"] = "1"              # جلوگیری از بازگشتِ بی‌پایان
        env.pop("PYTHONPATH", None)
        p = subprocess.run([sys.executable, TEST_NAME], cwd=d, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        return p.returncode, p.stdout.decode("utf-8", errors="replace")
    finally:
        shutil.rmtree(d, ignore_errors=True)


if not os.environ.get("PF_H4_NO_MUT"):
    print("═══ ۸) جهش‌آزمایی: تست باید دندان داشته باشد ═══")
    for k, (fn, needle) in ANCHORS.items():
        try:
            with open(os.path.join(HERE, fn), encoding="utf-8") as f:
                txt = f.read()
        except OSError as ex:
            txt = ""
            check(f"لنگرِ جهشِ «{k}» فایلش خوانده می‌شود", False, str(ex))
            continue
        check(f"لنگرِ جهشِ «{k}» در {fn} هست", txt.count(needle) == 1,
              f"count={txt.count(needle)} in {fn}")

    rc0, out0 = run_sandbox("smc_engine.py")
    check("جهش‌آزمایی: کپیِ سالم هم سبز است (هارنس واقعاً همین تست را اجرا می‌کند)",
          rc0 == 0 and "• بررسی‌ها:" in (out0 or ""),
          (out0 or "")[-300:] if rc0 is None else f"rc={rc0} " + (out0 or "")[-300:])

    RED = [
        ("برداشتنِ هم‌ترازیِ مرز (کلید = خودِ زمانِ کندل)", "smc_engine.py",
         [('        k=(b["t"]//tf_sec)*tf_sec', '        k=b["t"]  # PF-MUT', 1)],
         "همهٔ زمان‌های خروجی مضربِ ۱۴۴۰۰‌اند"),
        ("انتشارِ سبدِ ناقصِ میانه (حفرهٔ داده پنهان شود)", "smc_engine.py",
         [("            if len(grp)==n: out.append(_fold_group(grp,key))",
           "            if len(grp)>0: out.append(_fold_group(grp,key))  # PF-MUT", 1)],
         "حفرهٔ داده: سبدِ ناقص (۳ کندل) حذف می‌شود"),
        ("انتشارِ سبدِ ناقصِ انتها (کندلِ ۴ساعتهٔ هنوز-باز به تحلیل برود)", "smc_engine.py",
         [("    if key is not None and len(grp)==n: out.append(_fold_group(grp,key))",
           "    if key is not None and len(grp)>0: out.append(_fold_group(grp,key))  # PF-MUT", 1)],
         "سبدِ ناقصِ انتها (کندلِ ۴ساعتهٔ هنوز-باز) منتشر نمی‌شود"),
        ("کوتاه‌کردنِ طولِ سبد در مسیرِ زندهٔ Yahoo", "smc_engine.py",
         [('    if tf=="4h": out=resample(out,4,tf_sec=TF_SECONDS["4h"])',
           '    if tf=="4h": out=resample(out,4,tf_sec=TF_SECONDS["4h"]//4)  # PF-MUT', 1)],
         "مسیرِ زنده: ۲۴ کندلِ ۱ساعته ⇒ ۵ کندلِ ۴ساعته"),
        ("دست‌کاریِ ثابتِ OTE در PD (۰.۲۱ → ۰.۳۰)", "smc_engine.py",
         [("(round(bot+rng*0.21,5), round(bot+rng*0.38,5))",
           "(round(bot+rng*0.30,5), round(bot+rng*0.38,5))  # PF-MUT", 1)],
         "OTE طلاییِ خرید = bot + (۰.۲۱ … ۰.۳۸)×rng"),
    ]
    GREEN = [
        # «زمانِ سبدِ کامل» ذاتاً با «زمانِ اولین کندلِ سبد» یکی است (هر سبدِ کامل
        # هر چهار ساعتِ پنجره را دارد) → پیاده‌سازیِ جایگزین باید سبز بماند.
        ("گرفتنِ زمان از اولین کندلِ سبد به‌جای مرز (هم‌ارزِ رفتاری)", "smc_engine.py",
         [('    return {"t":t,"o":grp[0]["o"],"h":max(x["h"] for x in grp),',
           '    return {"t":grp[0]["t"],"o":grp[0]["o"],"h":max(x["h"] for x in grp),  # PF-GREEN', 1)]),
        ("کامنتِ بی‌گناه در smc_engine", "smc_engine.py",
         [("import sys, json, urllib.request, urllib.parse, argparse, datetime, math, ssl, time",
           "import sys, json, urllib.request, urllib.parse, argparse, datetime, math, ssl, time"
           "  # PF-GREEN", 1)]),
    ]

    for label, target, muts, want in RED:
        rc, out = run_sandbox(target, muts)
        if rc is None:
            check("جهشِ سرخ | " + label, False, out)
        else:
            # شکست باید **تمیز و نام‌دار** باشد (خطِ ::error::❌ با نامِ همان بررسی)،
            # نه کرشِ اتفاقی — وگرنه ادعا با نامِ سرصفحه هم می‌خواند.
            tag = f"❌ {want}"
            check("جهشِ سرخ | " + label, rc != 0 and "::error::" in out and tag in out,
                  f"rc={rc} · «{tag}» {'دیده شد' if tag in (out or '') else 'دیده نشد'}")

    for label, target, muts in GREEN:
        rc, out = run_sandbox(target, muts)
        if rc is None:
            check("جهشِ سبز | " + label, False, out)
        else:
            check("جهشِ سبز | " + label, rc == 0, f"rc={rc} " + (out or "")[-300:])

# ═══════════════════════════════════════════════════════════════════
#  ۹) نگهبانِ هرمتیک
# ═══════════════════════════════════════════════════════════════════
print("═══ ۹) نگهبانِ هرمتیک: هیچ فراخوانِ شبکه‌ای در تست رخ نمی‌دهد ═══")
check("هرمتیک: هیچ کدی در تست به شبکه دست نزد (گاردِ آفلاین دست‌نخورده ماند)",
      not NET_ATTEMPTS, str(NET_ATTEMPTS[:3]))
check("هرمتیک: مسیرِ Yahoo با پاسخِ ثابت جایگزین شد (نه شبکه)",
      len(CALLED) == 1, str(len(CALLED)))

NOTES.append("• باگِ رفع‌شده (D3/P0-3): `resample` سبدها را از **ابتدای آرایه** می‌بست "
             "(`range(0, len(bars)-len(bars)%n, n)`). Yahoo برای ۴ساعته دادهٔ ۱ساعته "
             "می‌دهد و اولین کندلش روی مرز نیست؛ پس سبدهای «۴ساعته» روی ۰۱:۰۰–۰۵:۰۰ و "
             "… می‌نشستند، در حالی که کارگزار سبدِ ۰۰:۰۰–۰۴:۰۰ را نشان می‌دهد.")
NOTES.append("• فیکس: گره‌زدنِ هر کندل با `t // tf_sec * tf_sec` (مرزِ UTC) + انتشارِ "
             "فقط سبدهای کامل. مسیرِ زنده (`fetch_yahoo`) و بک‌تست هردو از همین تابع "
             "می‌گذرند، پس هر دو یک‌بار رفع شدند.")
NOTES.append("• معاملهِ آگاهانه: «فقط سبدِ کامل» یعنی یک حفرهٔ یک‌ساعته کلِ سبدِ ۴ساعته را "
             "حذف می‌کند. این عمدی است: ترجیح می‌دهیم یک کندلِ کاملِ واقعی نداشته باشیم تا "
             "اینکه یک پنجرهٔ سه‌ساعته خودش را جای کندلِ بستهٔ چهارساعته جا بزند و "
             "سوینگ/PD را روی داده‌ی ناقص بسازد (هم‌راستا با `drop_unclosed`).")
NOTES.append("• یافتهٔ جانبی: با قاعدهٔ «سبدِ کامل»، «زمانِ سبد» ذاتاً با «زمانِ اولین "
             "کندلِ سبد» یکی می‌شود (هر سبدِ کامل چهار ساعتِ پنجره را دارد)؛ جهشِ سبزِ "
             "این هم‌ارزی را مستند می‌کند تا کسی آن را تغییرِ رفتاری نپندارد.")
NOTES.append("• ریشهٔ شکایتِ «سطوحِ اپ روی چارتِ من نیست» همین بود: ناهم‌ترازی با "
             "جهتِ پایِ ایمپالس هم بازی می‌کرد — در بخشِ ۶ می‌بینی که یک ساعت آفست، "
             "`leg_dir` را از −۱ به +۱ برمی‌گرداند و رِنجِ PD و OTE را جابه‌جا می‌کند.")

# ── گزارش ──
for n in NOTES:
    print(n)
print(f"• بررسی‌ها: {len(CHECKS)}")
if FAILS:
    print("")
    for name, detail in FAILS:
        print(f"::error::❌ {name}" + (f" — {detail}" if detail else ""))
    print(f"\n❌ تستِ «هم‌ترازیِ ۴ساعته» رد شد — {len(FAILS)} از {len(CHECKS)} بررسی شکست خورد")
    sys.exit(1)
print("✅ تستِ «هم‌ترازیِ ۴ساعته» پاس شد — کندلِ H4 روی مرزهای واقعیِ UTC "
      "(`t // 14400`) تجمیع می‌شود و با چارتِ کارگزار یکی است (D3/P0-3 و باقی‌ماندهٔ D11 بسته شد)")
