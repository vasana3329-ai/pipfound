#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تستِ «SMT دایورجنس + هشدارِ تریدِ خلافِ جهت روی جفت‌های همبسته».

کاملاً **آفلاین و قطعی**: کندل‌های سینتیکِ ساختِ خودِ تست را می‌سازد (الگوهای
زیگزاگِ کنترل‌شده) و هیچ شبکه‌ای نمی‌زند — در CI و روی هر ماشینی یکسان است.

چه چیزی را قفل می‌کند:
  ۱. جدولِ جفت‌های همبسته: هر جفتِ معروف شریکِ درست دارد؛ نمادِ ناشناس ندارد.
  ۲. تشخیصِ SMT: خرسی (HH در برابر LH) و صعودی (LL در برابر HL) — و
     «همبستگیِ سالم» (هر دو هم‌شکل) دایورجنسِ کاذب نمی‌سازد.
  ۳. پرچمِ «سوئیپ»: اکسترممِ جدید فقط وقتی سوئیپ است که از سوئینگِ قبل‌تر رد شود.
  ۴. هشدارِ «تریدِ خلافِ جهت» در risk.correlation: خریدِ USDJPY در حالی که
     EURUSDِ خریدِ باز است = خنثی‌سازیِ دلار؛ فروشِ XAUUSD در حالی که طلا خریدی =
     هجِ همان نماد — هر دو باید هشدارِ صریحِ «خلافِ جهت» بدهند، نه هشدارِ «تمرکز».
  ۵. هم‌راستا مثلِ قبل هشدارِ «ریسکِ تکراری» می‌دهد (رفتارِ قدیمی نشکند).
  ۶. سیم‌کشیِ اپ: چراغِ ستاپِ چهارم از بلوکِ smt می‌خواند (سبز/زرد/قرمز).
  ۷. هیچ وابستگیِ شبکه‌ای در smt.py نیست.

اجرا:  python3 smt_test.py        (خروجی ۰ = سالم)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import smt as SMT          # noqa: E402
import risk as RK          # noqa: E402
import app as APP          # noqa: E402

CHECKS = []
FAILS = []


def check(name, cond, detail=""):
    CHECKS.append(name)
    if not cond:
        FAILS.append((name, detail))


T0 = 1_700_000_000


def mk(closes, tf=3600):
    return [{"t": T0 + i * tf, "o": c, "h": c + 0.4, "l": c - 0.4, "c": c}
            for i, c in enumerate(closes)]


def zigzag(lvl, moves):
    out = []
    for amp, n in moves:
        step = amp / n
        for _ in range(n):
            lvl += step
            out.append(round(lvl, 3))
    return out


# الگوهای کنترل‌شده (روی سوئینگِ فرکتالیِ n=2 تأیید شده‌اند):
# خرسی: A آخرین up-leg قوی‌تر → HH + سوئیپ؛ B: بالا‌های قوی + پولبکِ ضعیف → LH
BEAR_SWEEP = [(-6, 6), (3, 4), (-4, 4), (6, 6), (-5, 5), (4, 4), (-3, 4), (8, 6), (-3, 4)]
BEAR_HOLD  = [(-6, 6), (3, 4), (-4, 4), (6, 6), (-5, 5), (4, 4), (-3, 4), (12, 6), (-6, 6), (2, 4), (-3, 4)]
# صعودی: آینه‌ی دقیق (علامتِ همه‌ی پاها برعکس)
BULL_SWEEP = [(6, 6), (-3, 4), (4, 4), (-6, 6), (5, 5), (-4, 4), (3, 4), (-8, 6), (3, 4)]
BULL_HOLD  = [(6, 6), (-3, 4), (4, 4), (-6, 6), (5, 5), (-4, 4), (3, 4), (-12, 6), (6, 6), (-2, 4), (3, 4)]


# ═══════════════════════════════════════════════════════════════════
print("═══ ۱) جدولِ جفت‌های همبسته ═══")
check("EURUSD↔GBPUSD", SMT.partners("EURUSD") == ["GBPUSD"])
check("GBPUSD↔EURUSD (متقارن)", SMT.partners("GBPUSD") == ["EURUSD"])
check("SPX500↔NAS100 (اولینِ شریک‌ها)", SMT.partners("SPX500")[0] == "NAS100")
check("SPX500↔US30 هم جفتِ معتبر است", "US30" in SMT.partners("SPX500"))
check("XAUUSD↔XAGUSD", SMT.partners("XAUUSD") == ["XAGUSD"])
check("BTCUSDT جفتِ ساختاری ندارد", SMT.partners("BTCUSDT") == [])
check("نمادِ خالی جفت ندارد", SMT.partners("") == [])
check("جزئیاتِ DXY: جفتِ دلاریِ بیرونِ جدول علامتِ مرجع می‌گیرد",
      SMT.check_for("EURJPY", -1, fetch_fn=None)["available"] is False)

# ═══════════════════════════════════════════════════════════════════
print("═══ ۲) تشخیصِ دایورجنس ═══")
A = mk(zigzag(100.0, BEAR_SWEEP))
B = mk(zigzag(200.0, BEAR_HOLD))
r = SMT.smt_divergence("TESTA", A, "TESTB", B, -1)
check("خرسی: HH (سوئیپ‌کننده) در برابر LH شناسایی می‌شود", r["diverged"] is True, r.get("reason", ""))
check("خرسی: پرچمِ سوئیپ روی نمادِ اول", r.get("sweep") is True)
check("خرسی: سوئیپِ نمادِ دوم (LH) نیست", r.get("other_sweep") is False)
check("خرسی: توضیحِ فارسیِ HH/LH در reason", "HH" in r.get("reason", "") and "LH" in r.get("reason", ""))

C = mk(zigzag(100.0, BULL_SWEEP))
D = mk(zigzag(200.0, BULL_HOLD))
r2 = SMT.smt_divergence("TESTC", C, "TESTD", D, 1)
check("صعودی: LL (سوئیپ‌کننده) در برابر HL شناسایی می‌شود", r2["diverged"] is True, r2.get("reason", ""))
check("صعودی: پرچمِ سوئیپ", r2.get("sweep") is True)

E = mk(zigzag(100.0, BEAR_SWEEP))
F = mk(zigzag(500.0, BEAR_SWEEP))   # دقیقاً هم‌شکل → همبستگیِ سالم
r3 = SMT.smt_divergence("E", E, "F", F, -1)
check("همبستگیِ سالم: دایورجنسِ کاذب نمی‌سازد", r3["diverged"] is False, r3.get("reason", ""))

# سوئینگ‌های هم‌دوره نیستند → رد می‌شود (نه دایورجنسِ ساختاریِ جعلی)
G = mk(zigzag(100.0, BEAR_SWEEP))
H = mk(zigzag(200.0, BEAR_HOLD))
H = H[:40]                            # نمادِ دوم کوتاه‌تر → آخرین سوئینگ‌ها هم‌دوره نیستند
r4 = SMT.smt_divergence("G", G, "H", H, -1)
check("سوئینگِ غیرهم‌دوره رد می‌شود", r4["diverged"] is False, r4.get("reason", ""))

# دادهٔ ناکافی → بدونِ استثنا، فقط diverged=False با دلیل
r5 = SMT.smt_divergence("X", mk([100, 101, 102]), "Y", mk([200, 201, 202]), -1)
check("دادهٔ خیلی کوتاه بدونِ استثنا", r5["diverged"] is False and "سوئینگ" in r5.get("reason", ""))
r6 = SMT.smt_divergence("X", [], "Y", [], -1)
check("دادهٔ خالی بدونِ استثنا", r6["diverged"] is False)
r7 = SMT.smt_divergence("X", A, "Y", B, 0)
check("جهتِ نامعتبر رد می‌شود", r7["diverged"] is False)

# ═══════════════════════════════════════════════════════════════════
print("═══ ۳) هشدارِ «تریدِ خلافِ جهت» در مدلِ ریسک ═══")
# ۳.الف: خریدِ USDJPY در حالی که EURUSDِ خریدِ باز است — دلار دقیقاً خنثی می‌شود
c = RK.correlation("USDJPY", 1, [{"symbol": "EURUSD", "sign": 1}])
check("خلافِ جهت (EURUSD خرید ↔ USDJPY خرید): هشدار می‌دهد", len(c["opposite_warnings"]) == 1,
      str(c["opposite_warnings"]))
check("...و کلمه‌ی «خلافِ جهت» در پیام است", "خلافِ جهت" in (c["opposite_warnings"] or [""])[0])
check("...و «خنثی می‌کند» چون خالصِ دلار صفر شد", "خنثی" in (c["opposite_warnings"] or [""])[0])
check("...و هشدارِ تمرکزِ هم‌راستا نمی‌دهد (دو معامله هم‌جهت نیستند)",
      len(c["trade_warnings"]) == 0, str(c["trade_warnings"]))

# ۳.ب: فروشِ XAUUSD در حالی که XAUUSDِ خریدِ باز است — هجِ همان نماد
c2 = RK.correlation("XAUUSD", -1, [{"symbol": "XAUUSD", "sign": 1}])
check("هجِ همان نماد: هشدارِ خلافِ جهت", len(c2["opposite_warnings"]) == 1)
check("...فقط یک سطر (نه دو فاکتورِ تکراری)", len(c2["opposite_warnings"]) == 1 and
      len(set(c2["opposite_warnings"])) == 1)

# ۳.ج: هشدارِ «خلافِ جهت» اولِ فهرستِ warnings می‌آید (چون خطایِ منطقی است)
c3 = RK.correlation("USDJPY", 1, [{"symbol": "EURUSD", "sign": 1}])
check("هشدارِ خلافِ جهت اولِ فهرستِ warnings است",
      c3["warnings"][0] == c3["opposite_warnings"][0])

# ۳.د: هم‌راستا مثلِ قبل: هشدارِ «ریسکِ تکراری» بدونِ هشدارِ خلافِ جهت
c4 = RK.correlation("EURUSD", 1, [{"symbol": "GBPUSD", "sign": 1}])
check("هم‌راستا: بدونِ هشدارِ خلافِ جهت", c4["opposite_warnings"] == [])
check("هم‌راستا: هشدارِ تمرکزِ دلاری مثلِ قبل", c4["stacked"] == {"USD": -2})

# ۳.ه: بدونِ پوزیشنِ باز هیچ هشداری نیست
c5 = RK.correlation("EURUSD", 1, [])
check("بدونِ پوزیشنِ باز: هیچ هشداری", c5["opposite_warnings"] == [] and c5["warnings"] == [])

# ۳.و: evaluate کل بلوک را با opposite_warnings عبور می‌دهد
blk = RK.evaluate("USDJPY", {"direction": "long", "entry": 150.0, "sl": 150.5, "rr": 2.0},
                  {"balance": 10000.0, "account_ccy": "USD", "risk_pct": 1.0,
                   "daily_loss_limit_pct": 3.0, "max_open_risk_pct": 5.0,
                   "usd_per_quote": {"JPY": 0.0067}},
                  [{"symbol": "EURUSD", "direction": "long", "status": "open", "risk_pct": 1.0}])
check("evaluate: opposite_warnings در بلوکِ نهایی هست",
      isinstance(blk.get("correlation", {}).get("opposite_warnings"), list))
check("evaluate: warningsِ رابط شاملِ پیامِ خلافِ جهت است",
      any("خلافِ جهت" in w for w in blk.get("warnings", [])))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۴) سیم‌کشیِ اپ: چراغِ ستاپِ چهارم ═══")
def st(name, status):
    return {"name": name, "status": status}

# حالتِ سبز: diverged + sweep
fake_g = {"checklist": [], "smt": {"available": True,
          "checked": {"diverged": True, "sweep": True, "reason": "SMTِ خرسی بین EURUSD و GBPUSD"}}}
out = APP._setup_statuses(fake_g)
check("ستاپِ چهارم وجود دارد (۴ چراغ)", len(out) == 4)
check("سبز: diverged+sweep", out[3]["state"] == "green")

# حالتِ زرد: diverged بدونِ سوئیپ
fake_y = {"checklist": [], "smt": {"available": True,
          "checked": {"diverged": True, "sweep": False, "reason": "SMT", "symbol": "A", "partner": "B"}}}
out = APP._setup_statuses(fake_y)
check("زرد: diverged بدونِ سوئیپ + راهنمای نمادِ سوئیپ‌کننده", out[3]["state"] == "yellow" and
      "سوئیپ‌کننده" in out[3]["why"])

# حالتِ قرمز: همبستگیِ سالم
fake_r = {"checklist": [], "smt": {"available": True,
          "checked": {"diverged": False, "reason": "همبستگی سالم است — هیچ شکافی در آخرین دو سوئینگ نیست"}}}
out = APP._setup_statuses(fake_r)
check("قرمز: همبستگیِ سالم", out[3]["state"] == "red")

# قرمزِ صادقانه: نمادِ بی‌جفت
fake_n = {"checklist": [], "smt": {"available": False, "partners": [], "checked": None}}
out = APP._setup_statuses(fake_n)
check("قرمز: نمادِ بی‌جفتِ همبسته", out[3]["state"] == "red" and "جفتِ همبسته" in out[3]["why"])

# ═══════════════════════════════════════════════════════════════════
print("═══ ۵) بدونِ وابستگیِ شبکه در smt.py ═══")
src = open(os.path.join(HERE, "smt.py"), encoding="utf-8").read()
for bad in ("urllib", "requests", "http_get", "fetch_binance", "fetch_yahoo"):
    check(f"smt.py بدونِ {bad}", bad not in src.replace("fetch_fn", "").replace("fetch سم", ""))

# ═══════════════════════════════════════════════════════════════════
print(f"\n═══ جمع‌بندی: {len(CHECKS)} بررسی، {len(FAILS)} خطا ═══")
if FAILS:
    for name, detail in FAILS:
        print(f"  ✗ {name}  {detail}")
    sys.exit(1)
print("✅ همه‌ی بررسی‌ها پاس شد")
