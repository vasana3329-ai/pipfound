#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تستِ عددیِ طلاییِ موتور — قفلِ مقادیرِ دقیق روی دادهٔ ثابتِ دست‌ساز (D11).

چرا این تست لازم بود: همهٔ لایه‌های نگهبان «کلید/مسیر/سیم‌کشی» را می‌سنجیدند،
نه *عددِ* موتور. نتیجه این بود که جابه‌جا کردنِ یک آستانه (مثلاً `disp_mult`
از ۱.۵ به ۱.۴، یا ضریبِ ۱.۳ دیسپلیسمنتِ کندلِ میانیِ FVG) هیچ تستی را نمی‌شکست
ولی خروجیِ واقعیِ تحلیل — درجه، پلنِ ورود، POI — بی‌صدا عوض می‌شد. این فایل روی
یک سریِ ثابتِ ۳۸کندلی (با دست هندسی‌شده، بدونِ شبکه و بدونِ تصادف) مقادیرِ
سوئینگ / FVG / اُردربلاک / ساختار (BOS/CHoCH/MSS) / PD-OTE / لیکوئیدیتی /
سوئیپ / دیسپلیسمنت را **عددبه‌عدد** قفل می‌کند و بعد *مرزِ* عددیِ هر آستانه را
با جفت‌های لبهای می‌سنجد.

چهار بخش:
  ۱) سریِ ثابت + مقادیرِ طلایی — هر ادعا در کامنتِ خودش از هندسهٔ کندل‌ها
     بازتولید شده (مثلاً top/bottom یک FVG = سقفِ کندلِ a و کفِ کندلِ c).
  ۲) مرزهای عددیِ آستانه‌ها — دقیقاً همان چیزی که بازبینی صریح گفته بود:
     «تغییرِ disp_mult=1.5 به 1.4 هیچ تستی را نمی‌شکند». حالا می‌شکند.
  ۳) اتصالِ سرتاسری (`analyze_bars`) روی همان سری + مرزِ پنجرهٔ ۱۲کندلیِ
     سوئیپ و مرزِ توالیِ sweep→MSS.
  ۴) جهش‌آزماییِ خودِ تست: هر جهشِ واقعی روی کپیِ موقتِ `smc_engine.py` باید
     این فایل را قرمز کند و **نامِ همان بررسی** را بگوید؛ جهش‌های بی‌گناه
     (کامنت/ثابتِ بی‌اثر) باید سبز بمانند. اگر نشانهٔ یک جهش پیدا نشود،
     هارنس صریحاً شکست می‌خورد — تا جهشِ بی‌صدا (ناوَکوم) پاس نشود.

اجرا:  python3 engine_golden_test.py                        (خروجی ۰ = سالم)
        PF_GOLDEN_NO_MUT=1 python3 engine_golden_test.py     (بدونِ بخشِ ۴)
"""
import copy
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import smc_engine as E  # noqa: E402

TEST_NAME = os.path.basename(os.path.abspath(__file__))
ENGINE_NAME = "smc_engine.py"

CHECKS = []
FAILS = []
NOTES = []


def check(name, cond, detail=""):
    CHECKS.append(name)
    if not cond:
        FAILS.append((name, detail))
    return cond


def j(x):
    """نمایشِ متعارف برای مقایسهٔ عددی/ساختاری (تا float مقایسهٔ دقیق بدهد)."""
    return json.dumps(x, ensure_ascii=False, sort_keys=True)


def eq(name, got, want):
    return check(name, j(got) == j(want), f"گرفته={j(got)} انتظار={j(want)}")


# ═══════════════════════════════════════════════════════════════════
#  ۱) سریِ ثابتِ دست‌ساز (۳۸ کندلِ ۱ساعته) — چهار فازِ روایی
# ═══════════════════════════════════════════════════════════════════
#  (o, h, l, c) — همه اعداد انتخاب‌شده‌اند، هیچ‌جا تصادف/شبکه نیست.
RAW = [
    # فازِ A (۰–۱۲): پایه و رِنجِ اولیه، با کفِ ۹۸.۸ و سقفِ ۱۰۱.۶
    (100.2, 100.8, 100.0, 100.6),
    (100.6, 101.2, 100.4, 101.0),
    (101.0, 101.4, 100.2, 100.4),      # سقفِ سوینگ ۱۰۱.۴
    (100.4, 100.6,  99.6,  99.8),
    ( 99.8, 100.2,  99.0,  99.4),
    ( 99.4,  99.8,  98.8,  99.6),      # کفِ سوینگ ۹۸.۸
    ( 99.6, 100.6,  99.4, 100.4),
    (100.4, 101.6, 100.2, 101.4),      # سقفِ سوینگ ۱۰۱.۶
    (101.4, 101.6, 100.6, 100.8),
    (100.8, 101.0, 100.0, 100.2),
    (100.2, 100.4,  99.6,  99.8),      # کفِ سوینگ ۹۹.۶
    ( 99.8, 100.2,  99.7, 100.0),
    (100.0, 100.6,  99.9, 100.4),      # سقفِ همین کندل = کفِ FVGِ بعدی
    # فازِ B (۱۳–۱۹): شکستِ دیسپلیسمنت‌دار + FVG صعودی + دابل‌تاپ
    (100.4, 102.9, 100.3, 102.8),      # BOS: بسته‌شدن بالای ۱۰۱.۶، بدنهٔ ۲.۴
    (102.8, 103.0, 102.2, 102.9),      # کفِ همین کندل = سقفِ FVG (۱۰۲.۲)
    (102.9, 103.8, 102.7, 103.6),
    (103.6, 104.40, 103.4, 104.2),     # سقفِ ۱۰۴.۴۰ (پایهٔ دابل‌تاپ)
    (104.2, 104.30, 103.6, 103.8),
    (103.8, 103.9, 103.2, 103.4),      # کفِ سوینگ ۱۰۳.۲
    (103.4, 104.45, 103.3, 103.5),     # سوئیپِ بای‌ساید: فتیله ۱۰۴.۴۵، بسته ۱۰۳.۵
    # فازِ C (۲۰–۲۸): فلات/توزیع و سوئیپِ دوم پیش از چرخش
    (103.5, 103.7, 103.3, 103.5),
    (103.5, 103.6, 103.2, 103.4),      # کفِ ۱۰۳.۲ (برادرِکفِ ۱۸ — EQ-Low)
    (103.4, 103.6, 103.2, 103.5),
    (103.5, 103.7, 103.3, 103.6),
    (103.6, 103.8, 103.4, 103.7),
    (103.7, 103.9, 103.5, 103.8),
    (103.8, 104.0, 103.6, 103.9),
    (103.9, 104.1, 103.7, 104.0),
    (104.0, 104.60, 103.9, 104.05),    # سوئیپِ دوم: فتیله ۱۰۴.۶۰، بسته ۱۰۴.۰۵
    # فازِ D (۲۹–۳۷): چرخش (CHoCH/MSS) + FVG و OBِ نزولی + کفِ تازه
    (103.6, 104.2, 103.6, 104.1),      # کندلِ صعودیِ آخرین پیش از ریزش (OB)
    (103.8, 103.9, 102.0, 102.2),      # شکستِ دیسپلیسمنت‌دار (بدنهٔ ۱.۶)
    (102.2, 102.4, 101.4, 101.6),      # FVG نزولی #۱ (top ۱۰۳.۶ / bot ۱۰۲.۴)
    (101.6, 101.8, 101.2, 101.4),      # FVG نزولی #۲ (top ۱۰۲.۰ / bot ۱۰۱.۸)
    (101.4, 101.5, 100.8, 101.0),      # کفِ سوینگِ تازه ۱۰۰.۸
    (101.0, 101.2, 100.9, 101.1),
    (101.1, 101.3, 100.95, 101.2),
    (101.2, 101.4, 101.0, 101.3),
    (101.3, 101.4, 100.9, 101.1),
]

BASE = int(datetime.datetime(2026, 9, 21, tzinfo=datetime.timezone.utc).timestamp())


def mk(raw):
    """از (o,h,l,c) → کندل‌های کامل با زمانِ ثابت و حجمِ ثابتِ بی‌اثر."""
    return [{"t": BASE + i * 3600, "o": o, "h": h, "l": l, "c": c, "v": 1.0}
            for i, (o, h, l, c) in enumerate(raw)]


bars = mk(RAW)
sw = E.swings(bars, 2)

check("سریِ ثابت واقعاً ۳۸ کندل است و ورودی دست‌نخورده",
      len(bars) == 38 and bars[13]["c"] == 102.8 and bars[28]["h"] == 104.60,
      f"n={len(bars)}")

# ── سوینگ‌ها: هر پیوت با دست از هندسهٔ همان کندل‌ها درآمده (n=2 فرکتال) ──
eq("سوئینگ‌ها (n=2) دقیقاً همان ۱۰ پیوتِ هندسی",
   sw,
   [(2, 101.4, "H"), (5, 98.8, "L"), (7, 101.6, "H"), (10, 99.6, "L"),
    (16, 104.4, "H"), (18, 103.2, "L"), (19, 104.45, "H"), (21, 103.2, "L"),
    (28, 104.6, "H"), (33, 100.8, "L")])

sw3 = E.swings(bars, 3)
check("سوئینگ با n=3 سه پیوتِ ابتدایی را می‌اندازد (پارامترِ n واقعاً اثر دارد)",
      sw3 == [(5, 98.8, "L"), (7, 101.6, "H"), (10, 99.6, "L"), (19, 104.45, "H"),
              (21, 103.2, "L"), (28, 104.6, "H"), (33, 100.8, "L")]
      and (2, 101.4, "H") not in sw3,
      j(sw3))

# ── ساختار: ماشینِ حالت، نه رأی‌گیریِ برچسب‌ها ──
trend, labels, bos, choch, meta = E.structure(bars, sw)

check("پایِ ایمپالس = قلهٔ کندلِ ۲۸ تا کفِ کندلِ ۳۳، جهتِ نزولی",
      E._impulse_leg(sw) == (100.8, 104.6, -1, 28, 33), j(E._impulse_leg(sw)))

check("روندِ نهایی پس از چرخش = down", trend == "down", trend)

eq("BOS صعودی روی سقفِ ۱۰۱.۶ (سوئینگِ ۷) با شکستِ کندلِ ۱۳",
   [bos, meta["bos_break_idx"]], [["bullish_BOS", 101.6, 7], 13])

eq("CHoCH نزولی روی کفِ ۱۰۳.۲ (سوئینگِ ۲۱) با شکستِ کندلِ ۳۰",
   [choch, meta["choch_break_idx"]], [["bearish_CHoCH", 103.2, 21], 30])

eq("MSS = همان CHoCHِ دیسپلیسمنت‌دار (سطح/سوئینگ/کندلِ شکست)",
   meta["mss"],
   {"type": "bearish_MSS", "level": 103.2, "swing_idx": 21, "break_idx": 30})

eq("رخدادهای ساختار دقیقاً دو تا و به همین ترتیب (BOS سپس CHoCH)",
   meta["events"],
   [("bullish_BOS", 101.6, 7, 13, True), ("bearish_CHoCH", 103.2, 21, 30, True)])

eq("برچسبِ شش سوینگِ آخر (HH/HL/LL روی همان پیوت‌ها)",
   labels,
   [(16, 104.4, "H", "HH"), (18, 103.2, "L", "HL"), (19, 104.45, "H", "HH"),
    (21, 103.2, "L", "HL"), (28, 104.6, "H", "HH"), (33, 100.8, "L", "LL")])


# ═══════════════════════════════════════════════════════════════════
#  ۲) FVG — هندسه + قاعدهٔ دیسپلیسمنت + قاعدهٔ نیمه‌پرشدن
# ═══════════════════════════════════════════════════════════════════
# هندسه: top = سقفِ کندلِ a (i-2)، bottom = کفِ کندلِ c (i)، mid = میانِ آن دو.
pre = bars[:21]                       # پیش از ریزش (چرخش از کندلِ ۲۹ شروع می‌شود)
eq("FVG صعودیِ کندلِ ۱۴: top=سقفِ کندلِ ۱۲ (۱۰۰.۶) · bottom=کفِ کندلِ ۱۴ (۱۰۲.۲) · mid=۱۰۱.۴",
   E.fvgs(pre),
   [{"type": "bullish", "top": 102.2, "bottom": 100.6, "idx": 14, "mid": 101.4}])

full_fvg = E.fvgs(bars)
check("همان FVG بعد از ریزشِ سری پاک می‌شود (کفِ ۱۰۲.۰ < midِ ۱۰۱.۴ → نیمه‌پرشده)",
      not any(f["idx"] == 14 for f in full_fvg)
      and any(x["l"] <= 101.4 for x in bars[21:]),
      j(full_fvg))

eq("دو FVG نزولیِ تازه با هندسهٔ دقیق (کندلِ ۳۱ و ۳۲)",
   full_fvg,
   [{"type": "bearish", "top": 103.6, "bottom": 102.4, "idx": 31, "mid": 103.0},
    {"type": "bearish", "top": 102.0, "bottom": 101.8, "idx": 32, "mid": 101.9}])


# مرزِ قاعدهٔ C14: کندلِ میانی باید بدنه‌اش ≥ ۱.۳×میانگینِ بدنه‌ها باشد.
# سه کندلِ ۱.۰/۱.۵/۱.۰ ⇒ میانگینِ بدنه = ۱.۱۶۶۷ ⇒ ۱.۳×آن = ۱.۵۱۶۷ > ۱.۵ → گپ نیست.
# همان سه کندل با بدنهٔ میانیِ ۱.۶ ⇒ میانگین ۱.۲ ⇒ ۱.۳×آن = ۱.۵۶ ≤ ۱.۶ → گپ هست.
def gap_series(b_body):
    return mk([( 99.0, 100.0, 98.5, 100.0),
               (100.0, 100.05 + b_body, 99.9, 100.0 + b_body),
               (101.6, 102.65, 101.6, 102.6)])


eq("مرزِ ضریبِ ۱.۳ — بدنهٔ میانیِ ۱.۵ گپ نمی‌سازد", E.fvgs(gap_series(1.5)), [])
eq("مرزِ ضریبِ ۱.۳ — بدنهٔ میانیِ ۱.۶ گپ می‌سازد (top=۱۰۱.۶ · bottom=۱۰۰.۰ · mid=۱۰۰.۸)",
   E.fvgs(gap_series(1.6)),
   [{"type": "bullish", "top": 101.6, "bottom": 100.0, "idx": 2, "mid": 100.8}])


# ═══════════════════════════════════════════════════════════════════
#  ۳) اُردربلاک — هندسه + قاعدهٔ میتیگیت + نسبتِ دیسپلیسمنت
# ═══════════════════════════════════════════════════════════════════
eq("اُردربلاکِ نزولیِ کندلِ ۲۹ (top=سقفِ ۱۰۴.۲ · bottom=کفِ ۱۰۳.۶ · disp=۱.۹۹×میانگینِ رِنج)",
   E.order_blocks(bars),
   [{"type": "bearish", "top": 104.2, "bottom": 103.6, "idx": 29,
     "disp_x_avg": 1.99}])

check("اُردربلاک میتیگیت‌نشده است (هیچ سقفی بعد از کندلِ ۳۱ به کفِ ۱۰۳.۶ نرسیده)",
      all(x["h"] < 103.6 for x in bars[31:]), j([x["h"] for x in bars[31:]]))


# مرزِ ضریبِ ۱.۳ اُردربلاک: میانگینِ رِنجِ کندل‌های ۳..۵ = (۱.۰ + B + ۰.۹۵)/۳
# و شرط = بدنهٔ دیسپلیسمنت > ۱.۳×آن ⇒ B > ۱.۴۹۱۲. پس B=۱.۴۹ OB نمی‌سازد و
# B=۱.۵۰ می‌سازد؛ نرم‌کردن (۱.۳→۱.۲) یا سخت‌کردن (۱.۳→۳.۰) هر دو این جفت را می‌شکنند.
def ob_series(disp_body):
    return mk([(110.0, 110.5, 109.5, 110.0),
               (110.0, 110.5, 109.5, 110.0),
               (110.0, 110.5, 109.5, 110.0),
               (102.0, 102.0, 101.0, 101.0),
               (101.0, 101.0 + disp_body, 101.0, 101.0 + disp_body),
               (102.4, 103.0, 102.05, 102.9)])


eq("مرزِ ضریبِ اُردربلاک — بدنهٔ ۱.۴۹×رِنج OB نمی‌سازد", E.order_blocks(ob_series(1.49)), [])
eq("مرزِ ضریبِ اُردربلاک — بدنهٔ ۱.۵۰×رِنج OB می‌سازد (top=۱۰۲.۰ · bottom=۱۰۱.۰)",
   E.order_blocks(ob_series(1.50)),
   [{"type": "bullish", "top": 102.0, "bottom": 101.0, "idx": 3,
     "disp_x_avg": 1.3}])


# ═══════════════════════════════════════════════════════════════════
#  ۴) پریمیوم/دیسکانت و OTE — لنگر روی پایِ ایمپالسِ واقعی
# ═══════════════════════════════════════════════════════════════════
pd = E.premium_discount(bars, sw)
eq("PD روی پایِ ۱۰۴.۶→۱۰۰.۸: eq=۱۰۲.۷ · قیمت ۱۰۱.۱ در دیسکانت (۷.۹٪ پای)",
   pd,
   {"range_top": 104.6, "range_bottom": 100.8, "equilibrium": 102.7,
    "zone": "discount", "price_pct": 7.9, "leg_dir": -1,
    "ote_long_buy_zone": (101.598, 102.244),
    "ote_short_sell_zone": (103.156, 103.802)})

# بازتولیدِ فرمولِ OTE از خودِ اعدادِ PD (نه از مقدارِ یخ‌زده):
#   خرید = bot + (۰.۲۱..۰.۳۸)×rng ، فروش = top − (۰.۳۸..۰.۲۱)×rng
_rng = pd["range_top"] - pd["range_bottom"]
check("OTE از فرمولِ ۰.۲۱/۰.۳۸ روی همان رِنج بازتولید می‌شود",
      pd["ote_long_buy_zone"] == (round(pd["range_bottom"] + _rng * 0.21, 5),
                                  round(pd["range_bottom"] + _rng * 0.38, 5))
      and pd["ote_short_sell_zone"] == (round(pd["range_top"] - _rng * 0.38, 5),
                                        round(pd["range_top"] - _rng * 0.21, 5)),
      j(pd))

check("price_pct از نسبتِ دستی درمی‌آید ((۱۰۱.۱−۱۰۰.۸)/۳.۸×۱۰۰ = ۷.۹)",
      pd["price_pct"] == round((bars[-1]["c"] - 100.8) / 3.8 * 100, 1),
      str(pd["price_pct"]))


# ═══════════════════════════════════════════════════════════════════
#  ۵) لیکوئیدیتی · الگوها · سوئیپ‌ها · دیسپلیسمنت
# ═══════════════════════════════════════════════════════════════════
liq = E.liquidity(bars, sw)
eq("بای‌ساید: EQHِ ۱۰۴.۴۰/۱۰۴.۴۵ (=۱۰۴.۴۲۵) + نزدیک‌ترین سقف‌های سوینگِ بالای قیمت",
   liq["buyside_eqh"], [101.4, 101.6, 104.4, 104.425])
eq("سل‌ساید: کف‌های سوینگِ زیرِ قیمتِ ۱۰۱.۱",
   liq["sellside_eql"], [98.8, 99.6, 100.8, 103.2])
eq("رِنجِ سری همان سقفِ ۱۰۴.۶ و کفِ ۹۸.۸ است",
   [liq["range_high"], liq["range_low"]], [104.6, 98.8])

check("EQH از میانگینِ دو سقفِ هم‌سطح ساخته می‌شود (۱۰۴.۴۰ و ۱۰۴.۴۵ → ۱۰۴.۴۲۵)",
      104.425 == round((104.40 + 104.45) / 2, 5)
      and 104.425 in liq["buyside_eqh"], j(liq["buyside_eqh"]))

_liq_strict = E.liquidity(bars, sw, tol=1e-6)
check("مرزِ tol: با ۱e-۶ دو سقفِ هم‌سطح EQH نمی‌سازند و ۱۰۴.۴۵ جای ۱۰۴.۴۲۵ می‌نشیند",
      _liq_strict["buyside_eqh"] == [101.4, 101.6, 104.4, 104.45],
      j(_liq_strict["buyside_eqh"]))

_liq_sess = E.liquidity(bars, sw, tf="1h")["session"]
check("سطوحِ سشنی کلیدهای چهارگانه دارند (مقدار عمداً قفل نشده — D5/D6 باز است)",
      set(_liq_sess) == {"pdh", "pdl", "asian_high", "asian_low"}, j(_liq_sess))

# برای دابل‌تاپ باید کلِ دو سقف در برش باشد؛ با n=2 پیوتِ اندیسِ ۱۹ فقط در
# برشی دیده می‌شود که حداقل سه کندل بعدش را داشته باشد (۱۹ ≤ n−3 ⇒ n ≥ ۲۲).
pat_slice = bars[:22]
_sw_pre = E.swings(pat_slice, 2)
_pat_pre = E.patterns(pat_slice, _sw_pre)
check("دابل‌تاپ روی دو سقفِ ۱۰۴.۴۰/۱۰۴.۴۵ ساخته می‌شود (سطحِ میانگین ۱۰۴.۴۲۵)",
      _pat_pre and _pat_pre[0] == {"kind": "double_top", "level": 104.425,
                                   "side": "buyside", "idx": 19},
      j(_pat_pre[:1]))

_pat_strict = E.patterns(pat_slice, _sw_pre, tol=1e-9)
check("مرزِ tolِ الگو: با ۱e-۹ دابل‌تاپ (اختلافِ ۰.۰۰۰۴۸ نسبی) دیگر الگو نیست",
      not any(p["kind"] == "double_top" for p in _pat_strict), j(_pat_strict))

_pat_full = E.patterns(bars, sw)
check("فهرستِ الگوها سقفِ ۸ دارد و V-شکل‌ها دابل‌تاپ را از فهرست بیرون می‌اندازند",
      len(_pat_full) == 8 and all(p["kind"].startswith("v_") for p in _pat_full),
      j(_pat_full))
NOTES.append("• یافتهٔ کوچک: `patterns()` یک فهرستِ مشترکِ سقف‌ـ۸ دارد و V-شکل‌ها "
             "می‌توانند دابل‌تاپ را بیرون بیندازند (روی این سری همین اتفاق می‌افتد).")

_swp = E.sweeps(bars, sw)
eq("سوئیپ‌های پنجرهٔ ۱۲کندلیِ آخر: سه سوئیپِ بای‌ساید، تازه‌ترین اول",
   _swp,
   [{"type": "bearish_sweep", "level": 101.4, "bar_from_end": 4, "idx": 33,
     "note": "buyside liquidity grabbed"},
    {"type": "bearish_sweep", "level": 101.6, "bar_from_end": 5, "idx": 32,
     "note": "buyside liquidity grabbed"},
    {"type": "bearish_sweep", "level": 104.4, "bar_from_end": 9, "idx": 28,
     "note": "buyside liquidity grabbed"}])

_swp40 = E.sweeps(bars, sw, lookback=40)
check("مرزِ پنجرهٔ سوئیپ: سوئیپِ کندلِ ۱۹ بیرونِ ۱۲کندل است و با lookback=۴۰ برمی‌گردد",
      len(_swp) == 3 and len(_swp40) == 4
      and _swp40[-1] == {"type": "bearish_sweep", "level": 104.4,
                         "bar_from_end": 18, "idx": 19,
                         "note": "buyside liquidity grabbed"},
      j(_swp40))

eq("دیسپلیسمنتِ نزولیِ کندلِ ۳۰ (بدنهٔ ۱.۶ = ۲.۱۵×میانگینِ رِنج)",
   E.displacement(bars),
   {"present": True, "direction": "bearish", "bar_from_end": 7,
    "body_x_avg": 2.15})

eq("همان کندل وقتی آخرین کندلِ برش باشد عددِ دیگری می‌دهد (حساسیتِ مخرجِ میانگین)",
   E.displacement(bars[:31]),
   {"present": True, "direction": "bearish", "bar_from_end": 0,
    "body_x_avg": 1.83})

eq("برشِ صعودیِ ابتدای سری: بدنهٔ ۲.۴ = ۲.۴۴×میانگین",
   E.displacement(bars[:22]),
   {"present": True, "direction": "bullish", "bar_from_end": 8,
    "body_x_avg": 2.44})

# دنبالهٔ آرام (هیچ بدنه‌ای از ۱.۸×میانگین نمی‌گذرد) ⇒ present=False؛ نرم‌کردنِ
# همین آستانه این برش را بی‌صدا به True می‌برد، پس این بررسی جهتِ نرم‌شدن را قفل می‌کند.
eq("دنبالهٔ آرامِ سری: هیچ دیسپلیسمنتی نیست (present=False)",
   E.displacement(bars[33:]), {"present": False})


# ═══════════════════════════════════════════════════════════════════
#  ۶) اتصالِ سرتاسری + توالیِ sweep→MSS
# ═══════════════════════════════════════════════════════════════════
NOW = bars[-1]["t"] + 3600
st = E.analyze_bars(bars, "1h", disp="GOLDEN", src="backtest", sym="XAUUSD", now=NOW)

check("analyze_bars: روند/قیمت/شمارشِ POI روی همان سری",
      st["trend"] == "down" and st["last_price"] == 101.1
      and len(st["FVG_unfilled"]) == 2 and len(st["order_blocks"]) == 1,
      f"{st['trend']} {st['last_price']} {len(st['FVG_unfilled'])} {len(st['order_blocks'])}")

check("analyze_bars: BOS/CHoCH/MSS همان مقادیرِ ساختارِ مستقیم است",
      st["BOS"] == bos and st["CHoCH"] == choch and st["mss_meta"]["mss"] == meta["mss"],
      j([st["BOS"], st["CHoCH"], st["mss_meta"]["mss"]]))

check("توالیِ sweep→MSS برقرار است (سوئیپِ کندلِ ۲۸ پیش از شکستِ ساختارِ کندلِ ۳۰)",
      st["sequence_ok"] is True, str(st["sequence_ok"]))

check("کیل‌زون از تایم‌استمپِ آخرین کندل می‌آید (بازتولیدپذیر، نه ساعتِ دیوار)",
      st["killzone"] == "New York AM KZ (08:30-11:00 ET)", str(st["killzone"]))

check("وضعیتِ داده: آخرین کندلِ بسته + سنِ صفر نسبت به now",
      st["data"]["state"] == "open" and st["data"]["age_s"] == 0,
      j({k: st["data"].get(k) for k in ("state", "age_s")}))

# مرزِ رفتاری: اگر فتیلهٔ سوئیپ برداشته شود، همان MSS سرجایش می‌ماند ولی
# توالی باطل می‌شود ⇒ `sequence_ok` باید False شود (نه بی‌صدا سبز).
_v = copy.deepcopy(bars)
_v[28]["h"] = 104.1
_st_v = E.analyze_bars(_v, "1h", disp="GOLDEN", src="backtest", sym="XAUUSD", now=NOW)
check("برداشتنِ فتیلهٔ سوئیپ: MSS باقی می‌ماند ولی sequence_ok باطل می‌شود",
      _st_v["sequence_ok"] is False
      and _st_v["mss_meta"]["mss"] == {"type": "bearish_MSS", "level": 103.2,
                                       "swing_idx": 21, "break_idx": 30},
      j([_st_v["sequence_ok"], _st_v["mss_meta"]["mss"]]))


# ═══════════════════════════════════════════════════════════════════
#  ۷) مرزِ عددیِ آستانه‌ها — همان چیزی که بازبینی صریح خواسته بود
# ═══════════════════════════════════════════════════════════════════
# رِنجِ هر سه کندلِ مبنا دقیقاً ۱.۰ ⇒ میانگین = ۱.۰ و مرزِ ۱.۵× = ۱.۵.
# کندلِ شکست بدنهٔ ۱.۴۵ دارد ⇒ با disp_mult=۱.۵ «شکستِ دیسپلیسمنت‌دار» نیست،
# ولی با ۱.۴ هست. پس تغییرِ پنهانِ پیش‌فرض از ۱.۵ به ۱.۴ این تست را می‌شکند.
THR = mk([( 99.0, 100.0, 99.0, 99.5),
          ( 99.5, 100.4, 99.4, 99.6),
          ( 99.6, 100.0, 99.0, 99.8),
          (100.0, 100.05, 98.5, 98.55),
          ( 98.55, 98.6, 98.0, 98.2)])

check("مرزِ disp_mult: بدنهٔ ۱.۴۵×رِنج با پیش‌فرضِ ۱.۵ شکستِ دیسپلیسمنت‌دار نیست",
      E._break_displaced(THR, 2, 100.0, False) == (False, 3),
      j(E._break_displaced(THR, 2, 100.0, False)))
check("مرزِ disp_mult: همان کندل با ۱.۴ دیسپلیسمنت‌دار می‌شود (پس تغییرِ ۱.۵→۱.۴ قرمز می‌کند)",
      E._break_displaced(THR, 2, 100.0, False, disp_mult=1.4) == (True, 3),
      j(E._break_displaced(THR, 2, 100.0, False, disp_mult=1.4)))


# ═══════════════════════════════════════════════════════════════════
#  ۸) جهش‌آزماییِ خودِ تست — تست باید دندان داشته باشد
# ═══════════════════════════════════════════════════════════════════
def mutate(src, muts):
    """جهش‌ها را اعمال می‌کند؛ هر نشانه‌ای که پیدا نشود → خطای صریح (نه سبزِ بی‌صدا)."""
    out = src
    for needle, repl, count in muts:
        got = out.count(needle)
        if got != count:
            return None, f"نشانهٔ جهش {count} بار انتظار می‌رفت ولی {got} بار بود: {needle[:60]}"
        out = out.replace(needle, repl)
    return out, None


def run_engine(muts=None):
    """کپیِ موقت: موتورِ (جهش‌یافته) + همین فایل → اجرا و گرفتنِ (کدِ خروج، خروجی)."""
    src = open(os.path.join(HERE, ENGINE_NAME), encoding="utf-8").read()
    if muts is not None:
        src, err = mutate(src, muts)
        if err:
            return None, err
    d = tempfile.mkdtemp(prefix="pf_golden_mut_")
    try:
        with open(os.path.join(d, ENGINE_NAME), "w", encoding="utf-8") as f:
            f.write(src)
        shutil.copyfile(os.path.abspath(__file__), os.path.join(d, TEST_NAME))
        env = dict(os.environ)
        env["PF_GOLDEN_NO_MUT"] = "1"        # جلوگیری از بازگشتِ بی‌پایان
        env.pop("PYTHONPATH", None)
        p = subprocess.run([sys.executable, TEST_NAME], cwd=d, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        return p.returncode, p.stdout.decode("utf-8", errors="replace")
    finally:
        shutil.rmtree(d, ignore_errors=True)


if not os.environ.get("PF_GOLDEN_NO_MUT"):
    rc0, out0 = run_engine()
    check("جهش‌آزمایی: کپیِ سالمِ موتور هم سبز است (هارنس واقعاً همین تست را اجرا می‌کند)",
          rc0 == 0 and "• بررسی‌ها:" in out0,
          (out0 or "")[-300:] if rc0 is None else f"rc={rc0} " + out0[-300:])

    RED = [
        ("کاهشِ پنهانِ disp_mult از ۱.۵ به ۱.۴ (نمونهٔ صریحِ بازبینی)",
         [("disp_mult=1.5", "disp_mult=1.4", 1)], "مرزِ disp_mult"),
        ("نرم‌کردنِ دیسپلیسمنتِ کندلِ میانیِ FVG (۱.۳ → ۰.۵)",
         [("disp_body = b_body >= 1.3*avgb if avgb>0 else False",
           "disp_body = b_body >= 0.5*avgb if avgb>0 else False", 1)],
         "FVG صعودیِ کندلِ ۱۴"),
        ("نرم‌کردنِ ضریبِ دیسپلیسمنتِ اُردربلاک (۱.۳ → ۱.۲)",
         [("disp>1.3*avg_rng", "disp>1.2*avg_rng", 2)],
         "مرزِ ضریبِ اُردربلاک"),
        ("نرم‌کردنِ آستانهٔ دیسپلیسمنت (۱.۸ → ۰.۲)",
         [("if body>1.8*avg:", "if body>0.2*avg:", 1)],
         "دنبالهٔ آرامِ سری"),
        ("سخت‌کردنِ آستانهٔ دیسپلیسمنت (۱.۸ → ۳.۰)",
         [("if body>1.8*avg:", "if body>3.0*avg:", 1)],
         "دیسپلیسمنتِ نزولیِ کندلِ ۳۰"),
        ("خنثی‌کردنِ فیلترِ میتیگیتِ اُردربلاک (همیشه میتیگیت‌شده)",
         [('mitigated = any(x["h"]>=bot for x in bars[i+2:])',
           "mitigated = len(bars) > 0", 1)],
         "اُردربلاکِ نزولیِ کندلِ ۲۹"),
        ("برداشتنِ قاعدهٔ نیمه‌پرشدنِ FVG (mitigation)",
         [('half_mit = any(x["l"]<=mid for x in future)', "half_mit = False", 1),
          ('half_mit = any(x["h"]>=mid for x in future)', "half_mit = False", 1)],
         "پاک می‌شود"),
        ("معکوس‌کردنِ آستانهٔ EQH در لیکوئیدیتی",
         [("if abs(highs[i]-highs[j])/highs[i]<tol: eqh.append(round((highs[i]+highs[j])/2,5))",
           "if abs(highs[i]-highs[j])/highs[i]>tol: eqh.append(round((highs[i]+highs[j])/2,5))", 1)],
         "EQHِ ۱۰۴.۴۰/۱۰۴.۴۵"),
        ("خیانتِ زونِ OTE: ۰.۲۱ → ۰.۲۰",
         [("ote_long=(round(bot+rng*0.21,5), round(bot+rng*0.38,5))",
           "ote_long=(round(bot+rng*0.20,5), round(bot+rng*0.38,5))", 1)],
         "فرمولِ ۰.۲۱/۰.۳۸"),
        ("خنثی‌کردنِ CHoCH: ثبتش به‌جای تغییرِ کاراکتر، BOS حساب شود",
         [('events.append(("bearish_CHoCH", ll[1], ll[0], bidx, bool(disp)))',
           'events.append(("bearish_BOS", ll[1], ll[0], bidx, bool(disp)))', 1)],
         "CHoCH نزولی"),
    ]
    GREEN = [
        ("کامنتِ بی‌گناه بالای موتور",
         [("import sys, json, urllib.request",
           "# یادداشتِ بی‌گناه (بی‌اثر)\nimport sys, json, urllib.request", 1)]),
        ("ثابتِ ماژولیِ بی‌اثر",
         [('UA = {"User-Agent": "Mozilla/5.0"}',
           'UA = {"User-Agent": "Mozilla/5.0"}\n_UNUSED_LIMIT = 99  # بی‌اثر', 1)]),
    ]

    for label, muts, want in RED:
        rc, out = run_engine(muts)
        if rc is None:
            check("جهشِ سرخ | " + label, False, out)
        else:
            check("جهشِ سرخ | " + label, rc != 0 and want in out,
                  f"rc={rc} · «{want}» {'دیده شد' if want in out else 'دیده نشد'}")

    for label, muts in GREEN:
        rc, out = run_engine(muts)
        if rc is None:
            check("جهشِ سبز | " + label, False, out)
        else:
            check("جهشِ سبز | " + label, rc == 0, f"rc={rc} " + (out or "")[-300:])


# ── گزارش ──
for n in NOTES:
    print(n)
print(f"• بررسی‌ها: {len(CHECKS)}")
if FAILS:
    print("")
    for name, detail in FAILS:
        print(f"::error::❌ {name}" + (f" — {detail}" if detail else ""))
    print(f"\n❌ تستِ عددیِ طلاییِ موتور رد شد — {len(FAILS)} از {len(CHECKS)} بررسی شکست خورد")
    sys.exit(1)
print("✅ تستِ عددیِ طلاییِ موتور پاس شد — ساختار، FVG، اُردربلاک، PD/OTE، "
      "لیکوئیدیتی، سوئیپ، دیسپلیسمنت و مرزِ آستانه‌ها روی دادهٔ ثابت قفل شدند")
sys.exit(0)
