#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تستِ «مدلِ ریسک»: سایزِ پوزیشن + سقفِ ضررِ روزانه + هشدارِ هم‌بستگی.

این تست کاملاً **آفلاین** است: هیچ درخواستِ شبکه‌ای (قیمت/تقویم) نمی‌زند و
تنظیمات را در یک فایلِ موقت می‌نویسد، پس در CI و روی هر ماشینی یکسان است.

چرا لازم است: پیش از این «۱:۳» تنها عددِ پلن بود و هیچ‌جا نمی‌گفت این ستاپ با
سرمایه‌ی تو چند لات است؛ سقفِ ضررِ روزانه و تمرکزِ هم‌بسته هم وجود نداشت. ریسکِ
صامتِ خاموش (نبودِ سایز) دقیقاً همان کلاسی از خرابی است که این تست قفلش می‌کند.

اجرا:  python3 risk_test.py        (خروجی ۰ = سالم)
"""
import datetime
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import risk as RK          # noqa: E402

CHECKS = []
FAILS = []


def check(name, cond, detail=""):
    CHECKS.append(name)
    if not cond:
        FAILS.append((name, detail))


def close(a, b, tol=0.011):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


ST = {"balance": 10000.0, "account_ccy": "USD", "risk_pct": 1.0,
      "daily_loss_limit_pct": 3.0, "max_open_risk_pct": 5.0, "usd_per_quote": {}}


def size(sym, entry, sl, st=None, rr=3.0, direction="long"):
    return RK.size_for(sym, {"entry": entry, "sl": sl, "rr": rr,
                             "direction": direction}, st or ST)


# ═══════════════════════════════════════════════════════════════════
print("═══ ۱) مشخصاتِ نماد: هر خانواده به مشخصاتِ درست تفکیک می‌شود ═══")
for sym, kind, contract, quote in [
        ("EURUSD", "fx", 100000.0, "USD"),
        ("GBPUSD", "fx", 100000.0, "USD"),
        ("USDJPY", "fx", 100000.0, "JPY"),
        ("EURJPY", "fx", 100000.0, "JPY"),      # قاعده‌ی عمومیِ ۶حرفی
        ("XAUUSD", "metal", 100.0, "USD"),
        ("XAGUSD", "metal", 5000.0, "USD"),
        ("WTI", "energy", 1000.0, "USD"),
        ("NATGAS", "energy", 10000.0, "USD"),
        ("COPPER", "energy", 25000.0, "USD"),
        ("SPX500", "index", 1.0, "USD"),
        ("NAS100", "index", 1.0, "USD"),
        ("GER40", "index", 1.0, "EUR"),
        ("JP225", "index", 1.0, "JPY"),
        ("DXY", "index", 1.0, "USD"),
        ("NVDA", "stock", 1.0, "USD"),
        ("BTCUSDT", "crypto", 1.0, "USD"),
        ("ETHUSDC", "crypto", 1.0, "USD"),
]:
    s = RK.instrument(sym)
    check(f"مشخصاتِ {sym}", s is not None, f"{sym} شناخته نشد")
    if s:
        check(f"{sym} نوع={kind}", s["kind"] == kind, str(s))
        check(f"{sym} اندازه‌ی قرارداد={contract}", close(s["contract"], contract), str(s))
        check(f"{sym} ارزِ مظنه={quote}", s["quote"] == quote, str(s))

# نام‌های جایگزین و ناشناخته
check("GOLD → XAUUSD", (RK.instrument("GOLD") or {}).get("symbol") == "XAUUSD")
check("USOIL → WTI", (RK.instrument("USOIL") or {}).get("symbol") == "WTI")
check("نمادِ ناشناخته → None", RK.instrument("ZZZZZZZ") is None)
check("نمادِ خالی → None", RK.instrument("") is None)
check("نقطهٔ پیپِ جفت‌ارزِ ین ۰.۰۱ است", close(RK.instrument("USDJPY")["point"], 0.01))
check("نقطهٔ پیپِ جفت‌ارزِ دلاری ۰.۰۰۰۱ است", close(RK.instrument("EURUSD")["point"], 0.0001))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۲) سایزِ پوزیشن: ریسکِ هر معامله دقیقاً درصدِ تعیین‌شده ═══")
# ۱۰٬۰۰۰ دلار سرمایه · ۱٪ ریسک ⇒ سقفِ ریسکِ هر معامله = ۱۰۰ دلار
cases = [
    # (نماد، ورود، استاپ، سایزِ درست، ریسکِ واقعی)
    ("EURUSD", 1.1000, 1.0950, 0.20, 100.0),      # ۵۰ پیپ × ۱۰ دلار = ۵۰۰/لات
    ("USDJPY", 150.00, 149.50, 0.30, 100.0),      # مظنه ین ⇒ تبدیل ارز لازم است
    ("XAUUSD", 4000.0, 3985.0, 0.06, 90.0),       # ۱۵ دلار × ۱۰۰ اونس = ۱۵۰۰/لات
    ("NAS100", 20000.0, 19900.0, 1.0, 100.0),     # ۱۰۰ پوینت × ۱ دلار
    ("NVDA", 180.0, 177.0, 33, 99.0),             # سهم: ۳ دلار × ۳۳ سهم
    ("BTCUSDT", 60000.0, 59500.0, 0.2, 100.0),
]
for sym, entry, sl, want_size, want_risk in cases:
    r = size(sym, entry, sl)
    check(f"سایزِ {sym} محاسبه شد", r.get("ok") is True, str(r.get("reason")))
    if not r.get("ok"):
        continue
    check(f"سایزِ {sym} = {want_size}", close(r["size"], want_size, 1e-6),
          f"{r.get('size')} ≠ {want_size}")
    check(f"ریسکِ {sym} = {want_risk}", close(r["actual_risk_amount"], want_risk, 0.02),
          f"{r.get('actual_risk_amount')} ≠ {want_risk}")
    # قاعده‌ی طلایی: هرگز بیشتر از ریسکِ هدف ریسک نشود
    check(f"ریسکِ {sym} از هدف بیشتر نشد",
          r["actual_risk_amount"] <= r["risk_amount"] + 0.01,
          f"{r['actual_risk_amount']} > {r['risk_amount']}")
    check(f"ریسکِ هدفِ {sym} = ۱۰۰", close(r["risk_amount"], 100.0), str(r.get("risk_amount")))

# ارزشِ هر پوینت/پیپ و شمارشِ پیپ
e = size("EURUSD", 1.1000, 1.0950)
check("ارزشِ هر پیپِ EURUSD = ۱۰ دلار برای یک لات", close(e["value_per_point"], 10.0), str(e))
check("فاصله‌ی استاپِ EURUSD = ۵۰ پیپ", close(e["stop_pips"], 50.0), str(e))
g = size("XAUUSD", 4000.0, 3985.0)
check("ارزشِ هر پوینتِ طلا = ۱ دلار برای یک لات", close(g["value_per_point"], 1.0), str(g))
check("طلا = ۱۵۰۰ پوینت استاپ", close(g["stop_pips"], 1500.0), str(g))

# گردکردن به کفِ پله (نه نزدیک‌ترین) — نمونه‌ی طلا: ۰.۰۶۶۷ ⇒ ۰.۰۶ نه ۰.۰۷
check("گردکردن به کف: طلا ۰.۰۶ شد نه ۰.۰۷", close(g["size"], 0.06, 1e-6), str(g.get("size")))
h = size("NAS100", 20000.0, 19900.0)
check("گردکردن به کف: NAS100 دقیقاً ۱.۰", close(h["size"], 1.0, 1e-6), str(h.get("size")))

# تبدیلِ نرخِ ارزِ مظنه برای نمادهای غیرِ دلاری
j = size("USDJPY", 150.0, 149.5)
check("USDJPY از جدولِ تبدیل استفاده کرد", j.get("approx") is True, str(j.get("approx")))
check("USDJPY ریسکِ هر لات ≈ ۳۳۳ دلار", close(j["risk_per_lot"], 333.33, 0.5),
      str(j.get("risk_per_lot")))
check("نرخِ دستیِ کاربر، تبدیل را دقیق می‌کند",
      size("USDJPY", 150.0, 149.5,
           {**ST, "usd_per_quote": {"JPY": 1 / 150.0}})["approx"] is False)
check("نمادِ دلاری هیچ‌وقت «تقریبی» علامت نمی‌خورد",
      size("EURUSD", 1.1, 1.095).get("approx") is False)
check("طلا (مظنهٔ دلار) تقریبی نیست", g.get("approx") is False)
check("NAS100 تقریبی است (قراردادِ CFD به کارگزار بستگی دارد)", h.get("approx") is True)

# ═══════════════════════════════════════════════════════════════════
print("═══ ۳) سرمایه/درصد: سایز با هر دو مقیاس خطی می‌شود ═══")
big = size("EURUSD", 1.1000, 1.0950, {**ST, "balance": 100000.0})
check("۱۰ برابر سرمایه ⇒ ۱۰ برابر سایز", close(big["size"], 2.0, 1e-6), str(big.get("size")))
check("۱۰ برابر سرمایه ⇒ ریسکِ ۱۰۰۰", close(big["actual_risk_amount"], 1000.0, 0.1),
      str(big.get("actual_risk_amount")))
half = size("EURUSD", 1.1000, 1.0950, {**ST, "risk_pct": 0.5})
check("نیم‌درصدِ ریسک ⇒ نصفِ سایز", close(half["size"], 0.1, 1e-6), str(half.get("size")))
check("نیم‌درصدِ ریسک ⇒ ریسکِ ۵۰", close(half["actual_risk_amount"], 50.0, 0.05),
      str(half.get("actual_risk_amount")))
eur_acc = size("EURUSD", 1.1000, 1.0950, {**ST, "account_ccy": "EUR"})
check("حسابِ یورویی: ریسکِ هر لات به یورو تبدیل می‌شود",
      close(eur_acc["risk_per_lot"], 500.0 / 1.09, 1.0), str(eur_acc.get("risk_per_lot")))
check("حسابِ یورویی تقریبی علامت می‌خورد", eur_acc.get("approx") is True)

# ── گاردها: هیچ‌کدام نباید بی‌صدا سایزِ غلط بدهند
for name, st, args in [
        ("سرمایه‌ی صفر", {**ST, "balance": 0.0}, ("EURUSD", 1.1, 1.095)),
        ("درصدِ ریسکِ صفر", {**ST, "risk_pct": 0.0}, ("EURUSD", 1.1, 1.095)),
]:
    r = RK.size_for(args[0], {"entry": args[1], "sl": args[2], "rr": 3}, st)
    check(f"{name} ⇒ سایز محاسبه نشود", r.get("ok") is False, str(r))
    check(f"{name} ⇒ دلیلِ فارسی دارد", bool(r.get("reason")), str(r))
r = RK.size_for("EURUSD", {"entry": 1.1, "sl": 1.1, "rr": 3}, ST)
check("ورود = استاپ ⇒ رد می‌شود", r.get("ok") is False, str(r))
r = RK.size_for("ZZZZZZZ", {"entry": 1.1, "sl": 1.09, "rr": 3}, ST)
check("نمادِ ناشناخته ⇒ سایز محاسبه نشود", r.get("ok") is False, str(r))
check("نمادِ ناشناخته ⇒ دلیل صریح", "نمی‌شناسم" in (r.get("reason") or ""), str(r))
r = RK.size_for("EURUSD", None, ST)
check("پلنِ خالی ⇒ رد می‌شود", r.get("ok") is False, str(r))
# ریسکِ هدف از کوچک‌ترین پله کمتر ⇒ سایزِ حداقلی با هشدارِ «بیش از هدف»
tiny = size("GER40", 18000.0, 17900.0, {**ST, "balance": 50.0})
check("سرمایه‌ی خیلی کوچک ⇒ سایزِ حداقلی با هشدار", tiny.get("over_risk") is True, str(tiny))
check("سرمایه‌ی خیلی کوچک ⇒ یادداشتِ «بیش از هدف»",
      any("بزرگ‌تر است" in n for n in (tiny.get("notes") or [])), str(tiny.get("notes")))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۴) سقفِ ضررِ روزانه و ریسکِ باز (از دفترِ معاملات) ═══")
today = datetime.datetime(2026, 9, 20, 13, 0)
yday = (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d 10:00")


def row(status, r_, risk_pct="1", dt="2026-09-20 10:00", sym="XAUUSD", direction="long"):
    return {"status": status, "realized_r": r_, "risk_pct": risk_pct,
            "datetime": dt, "symbol": sym, "direction": direction}


d = RK.daily_state([row("closed", "-1.0"), row("closed", "-1.5")], ST, now=today)
check("دو ضررِ ۱R و ۱.۵R ⇒ ‎-۲.۵R", close(d["realized_r"], -2.5), str(d))
check("...⇒ ‎-۲.۵٪ از سرمایه", close(d["realized_pct"], -2.5), str(d))
check("...⇒ ‎-۲۵۰ دلار", close(d["realized_amount"], -250.0), str(d))
check("...⇒ از سقفِ ۳٪ نگذشته", d["breached"] is False, str(d))
check("...⇒ باقی‌مانده ۰.۵٪ = ۵۰ دلار", close(d["remaining_pct"], 0.5) and close(d["remaining_amount"], 50.0), str(d))

d = RK.daily_state([row("closed", "-1.5"), row("closed", "-1.5")], ST, now=today)
check("دقیقاً روی سقفِ ۳٪ ⇒ breached=True", d["breached"] is True, str(d))
check("دقیقاً روی سقف ⇒ باقی‌مانده صفر", close(d["remaining_pct"], 0.0), str(d))

d = RK.daily_state([row("closed", "-2.0")], ST, now=today)
check("سود/زیانِ دیروز در سقفِ امروز حساب نمی‌شود",
      RK.daily_state([row("closed", "-9.0", dt=yday)], ST, now=today)["breached"] is False)
check("...⇒ امروز still صفر است",
      close(RK.daily_state([row("closed", "-9.0", dt=yday)], ST, now=today)["realized_pct"], 0.0))
check("معامله‌ی باز در ضررِ محقق‌شده حساب نمی‌شود",
      close(RK.daily_state([row("open", "-5.0")], ST, now=today)["realized_r"], 0.0))
# اگر ستونِ R خالی بود، از نتیجه استنتاج شود (win/+rr · loss/-1 · be/0)
check("loss بدونِ R ⇒ ‎-۱R",
      close(RK.daily_state([{"status": "closed", "result": "loss", "datetime": "2026-09-20 10:00"}],
                           ST, now=today)["realized_r"], -1.0))
check("win بدونِ R ⇒ +rr",
      close(RK.daily_state([{"status": "closed", "result": "win", "rr": "2.5",
                             "datetime": "2026-09-20 10:00"}], ST, now=today)["realized_r"], 2.5))
check("be بدونِ R ⇒ صفر",
      close(RK.daily_state([{"status": "closed", "result": "be",
                             "datetime": "2026-09-20 10:00"}], ST, now=today)["realized_r"], 0.0))
check("درصدِ ریسکِ خودِ ردیف رعایت می‌شود (۲٪ ⇒ ضررِ دوبرابر)",
      close(RK.daily_state([row("closed", "-1.0", risk_pct="2")], ST, now=today)["realized_pct"], -2.0))

opens = [row("open", "", sym="EURUSD"), row("open", "", sym="BTCUSDT", direction="short"),
         row("open", "", sym="XAUUSD")]
d = RK.daily_state(opens, ST, now=today)
check("ریسکِ باز = مجموعِ درصدهای پوزیشن‌های باز", close(d["open_risk_pct"], 3.0), str(d))
check("۳ پوزیشنِ باز شمرده شد", d["open_count"] == 3, str(d))
check("جهتِ پوزیشن‌های باز درست تجزیه شد",
      [p["sign"] for p in d["open_positions"]] == [1, -1, 1], str(d["open_positions"]))
check("ریسکِ باز از سقفِ ۵٪ نگذشته", d["open_breached"] is False, str(d))
d2 = RK.daily_state(opens + [row("open", "", sym="GBPUSD"), row("open", "", sym="NVDA"),
                             row("open", "", sym="WTI")], ST, now=today)
check("۶٪ ریسکِ باز ⇒ open_breached=True", d2["open_breached"] is True, str(d2))
check("بلوکِ روزانه شاملِ فهرستِ نمادهای باز است",
      len(d["open_positions"]) == 3 and d["open_positions"][0]["symbol"] == "EURUSD")

# ═══════════════════════════════════════════════════════════════════
print("═══ ۵) هم‌بستگی: ریسکِ تکراری گرفته می‌شود، مثبتِ کاذب نه ═══")
two_long_usd = [{"symbol": "EURUSD", "sign": 1}, {"symbol": "GBPUSD", "sign": 1}]
c = RK.correlation("XAUUSD", 1, two_long_usd)
check("طلا + دو خریدِ دلاری ⇒ هشدار داده شد", len(c["trade_warnings"]) >= 1, str(c))
check("هشدار روی فاکتورِ «دلار» است",
      any("دلار" in w for w in c["trade_warnings"]), str(c["trade_warnings"]))
c = RK.correlation("NAS100", 1, [{"symbol": "SPX500", "sign": 1}])
check("NAS100 + SPX500 ⇒ هشدارِ شاخصِ آمریکا",
      any("آمریکا" in w for w in c["trade_warnings"]), str(c["trade_warnings"]))
c = RK.correlation("NVDA", 1, [{"symbol": "NAS100", "sign": 1}])
check("NVDA + NAS100 ⇒ هشدارِ شاخصِ آمریکا",
      any("آمریکا" in w for w in c["trade_warnings"]), str(c["trade_warnings"]))
c = RK.correlation("XAUUSD", 1, [{"symbol": "XAUUSD", "sign": 1}])
check("دو خریدِ طلا ⇒ هشدارِ فلزات",
      any("فلزات" in w for w in c["trade_warnings"]), str(c["trade_warnings"]))
# خریدِ EURUSD (دلار ‎-۱) + فروشِ USDJPY (دلار هم ‎-۱) = هر دو یک شرط روی دلار ⇒ باید هشدار بدهد
c = RK.correlation("EURUSD", 1, [{"symbol": "USDJPY", "sign": -1}])
check("دو معامله با یک جهتِ دلاری (هر دو دلارِ منفی) ⇒ هشدار",
      len(c["trade_warnings"]) == 1, str(c["stacked"]))
c = RK.correlation("XAUUSD", 1, [{"symbol": "USDJPY", "sign": 1}])
check("طلا (دلار منفی) + USDJPY خرید (دلار مثبت) ⇒ هشدار نیست",
      c["trade_warnings"] == [], str(c["stacked"]))
c = RK.correlation("NAS100", -1, [{"symbol": "SPX500", "sign": 1}])
check("NAS100 فروش + SPX500 خرید ⇒ هشدار نیست", c["trade_warnings"] == [], str(c["stacked"]))
c = RK.correlation("EURUSD", 1, [])
check("بدونِ پوزیشنِ باز ⇒ هیچ هشداری", c["warnings"] == [], str(c))
# تمرکزِ از قبل موجود جدا گزارش می‌شود، نه به نامِ این معامله
c = RK.correlation("WTI", 1, two_long_usd)
check("نفت با تمرکزِ دلاریِ باز ⇒ هشدارِ معامله ندارد", c["trade_warnings"] == [], str(c))
check("...ولی تمرکزِ موجود جدا گزارش می‌شود", len(c["open_concentration"]) == 1, str(c))
check("...و در فهرستِ نمایش هم هست", any("توجه" in w for w in c["warnings"]), str(c["warnings"]))
c = RK.correlation("ZZZZZZZ", 1, two_long_usd)
check("نمادِ ناشناخته ⇒ نه هشدار، نه کرش", c["trade_warnings"] == [], str(c))
check("جهتِ نامشخص ⇒ تجزیه‌ی خالی", RK.exposures("EURUSD", 0) == {})
check("تجزیه‌ی EURUSD خرید = یورو مثبت، دلار منفی",
      RK.exposures("EURUSD", 1) == {"CCY:EUR": 1, "USD": -1}, str(RK.exposures("EURUSD", 1)))
check("تجزیه‌ی XAUUSD خرید = فلزات مثبت، دلار منفی",
      RK.exposures("XAUUSD", 1) == {"METALS": 1, "USD": -1}, str(RK.exposures("XAUUSD", 1)))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۶) evaluate: سقفِ ضررِ روزانه معامله را مسدود می‌کند ═══")
plan = {"entry": 4000.0, "sl": 3985.0, "rr": 3.0, "direction": "صعودی"}
ev = RK.evaluate("XAUUSD", plan, ST, [row("closed", "-1.0")], now=today)
check("زیرِ سقف ⇒ مسدود نیست", ev["blocked"] is False, str(ev.get("block_reason")))
check("زیرِ سقف ⇒ سایز محاسبه شده", (ev["size"] or {}).get("ok") is True, str(ev["size"]))
ev = RK.evaluate("XAUUSD", plan, ST, [row("closed", "-3.5")], now=today)
check("عبور از سقف ⇒ blocked=True", ev["blocked"] is True, str(ev))
check("...⇒ دلیلِ مسدودی پر است", bool(ev.get("block_reason")), str(ev))
check("...⇒ دلیل به سقفِ روزانه اشاره دارد", "سقفِ ضررِ روزانه" in (ev.get("block_reason") or ""), str(ev))
check("...⇒ در فهرستِ warnings هم می‌آید",
      any("سقفِ ضررِ روزانه" in w for w in ev["warnings"]), str(ev["warnings"]))
check("...⇒ سایز همچنان محاسبه می‌شود (برای آماده‌سازی)",
      (ev["size"] or {}).get("ok") is True, str(ev["size"]))
ev = RK.evaluate("XAUUSD", plan, ST,
                 opens + [row("open", "", sym="GBPUSD"), row("open", "", sym="NVDA"),
                          row("open", "", sym="WTI")], now=today)
check("عبور از سقفِ ریسکِ باز ⇒ مسدود", ev["blocked"] is True, str(ev))
check("...⇒ دلیل به ریسکِ باز اشاره دارد", "معاملاتِ باز" in (ev.get("block_reason") or ""), str(ev))
ev = RK.evaluate("XAUUSD", None, ST, [], now=today)
check("بدونِ پلن ⇒ evaluate کرش نمی‌کند", isinstance(ev, dict) and ev["blocked"] is False, str(ev))
check("بدونِ پلن ⇒ دلیلِ نبودِ سایز", (ev["size"] or {}).get("ok") is False, str(ev["size"]))
check("evaluate بلوکِ تنظیمات را برمی‌گرداند",
      (ev.get("settings") or {}).get("risk_pct") == 1.0, str(ev.get("settings")))
check("evaluate بلوکِ روزانه را برمی‌گرداند", isinstance(ev.get("daily"), dict), str(ev))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۷) تنظیمات: ذخیره/بازخوانیِ اتمیک در فایلِ موقت ═══")
tmpd = tempfile.mkdtemp(prefix="pf_risk_test_")
try:
    f = os.path.join(tmpd, "risk.json")
    RK.save_settings({"balance": 25000, "risk_pct": 0.5, "daily_loss_limit_pct": 2.5,
                      "max_open_risk_pct": 4, "account_ccy": "eur",
                      "usd_per_quote": {"JPY": 0.0068}}, path=f)
    st2 = RK.load_settings(path=f)
    check("سرمایه بازخوانی شد", close(st2["balance"], 25000), str(st2))
    check("درصدِ ریسک بازخوانی شد", close(st2["risk_pct"], 0.5), str(st2))
    check("سقفِ روزانه بازخوانی شد", close(st2["daily_loss_limit_pct"], 2.5), str(st2))
    check("ارزِ حساب نرمال شد (EUR)", st2["account_ccy"] == "EUR", str(st2))
    check("نرخِ دستیِ ارز ماند", close(st2["usd_per_quote"]["JPY"], 0.0068), str(st2))
    check("فایلِ تنظیمات بدونِ .tmpِ باقی‌مانده نوشته شد",
          os.path.exists(f) and not os.path.exists(f + ".tmp"), os.listdir(tmpd))
    # مقادیرِ نامعتبر نباید تنظیمات را خراب کنند
    RK.save_settings({"balance": "abc", "risk_pct": -5}, path=f)
    st3 = RK.load_settings(path=f)
    check("سرمایه‌ی نامعتبر ⇒ پیش‌فرض، نه صفر",
          close(st3["balance"], RK.DEFAULTS["balance"]), str(st3))
    check("درصدِ منفی ⇒ رد می‌شود",
          close(RK.load_settings(path=f)["risk_pct"], RK.DEFAULTS["risk_pct"]), str(st3))
    # فایلِ خراب/نبودِ فایل ⇒ پیش‌فرض‌ها (بدونِ کرش)
    bad = os.path.join(tmpd, "bad.json")
    with open(bad, "w") as fh:
        fh.write("{not json")
    check("فایلِ خراب ⇒ پیش‌فرض‌ها", close(RK.load_settings(path=bad)["balance"],
                                            RK.DEFAULTS["balance"]), str(RK.load_settings(path=bad)))
    check("فایلِ ناموجود ⇒ پیش‌فرض‌ها",
          close(RK.load_settings(path=os.path.join(tmpd, "nope.json"))["balance"],
                RK.DEFAULTS["balance"]))
    # مسیرِ پیش‌فرض باید بیرونِ Desktop/Documents باشد (محدودیتِ TCC مک)
    sp = RK.settings_path()
    check("مسیرِ پیش‌فرضِ تنظیمات بیرونِ Desktop/Documents است",
          "Desktop" not in sp and "Documents" not in sp, sp)
finally:
    shutil.rmtree(tmpd, ignore_errors=True)

# ═══════════════════════════════════════════════════════════════════
print("═══ ۸) تستِ دندان: مدلِ ریسک هیچ وابستگیِ شبکه‌ای ندارد ═══")
src = open(os.path.join(HERE, "risk.py"), encoding="utf-8").read()
check("risk.py هیچ urllib/socket/requests ای ندارد",
      not any(x in src for x in ("urllib", "socket", "requests", "http.client")),
      "ماژولِ ریسک باید صددرصد آفلاین باشد")
check("risk.py هیچ درخواستِ قیمت واقعی نمی‌کند", "http" not in src.replace("https://", ""))

# ─────────────────────────────────────────────────────────────
print()
if FAILS:
    print(f"❌ {len(FAILS)} بررسی از {len(CHECKS)} بررسی رد شد:")
    for n, det in FAILS:
        print(f"   • {n}" + (f"  →  {det}" if det else ""))
    sys.exit(1)
print(f"✅ همه‌ی {len(CHECKS)} بررسیِ مدلِ ریسک سبز شد.")
sys.exit(0)
