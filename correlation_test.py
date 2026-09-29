#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تستِ «هم‌بستگیِ عددی» — ضرایبِ مرجع + تذکرِ تخلفِ کاربر روی پوزیشن‌های باز.

چرا لازم است: مدلِ ریسک از قبل «فاکتور» داشت (هر دو روی دلار/فلزات/کریپتو
جمع شده‌اند) ولی **بدونِ عدد** بود. کاربر حرفه‌ای می‌داند که طلا و دلار منفی‌اند،
طلا و دلارِ کانادا مثبت، بیت‌کوین و اتریوم مثبت با ضریبِ بالا — و انتظار دارد اگر
این را رعایت نکرد (چند پوزیشنِ هم‌بسته در یک جهت، یا هجِ ناخواسته) اپ **تذکر
بدهد**. این تست همان جدولِ ضرایب + منطقِ تذکر را روی دادهٔ ثابت قفل می‌کند تا
تغییرِ ضریب یا شل‌کردنِ آستانه بی‌صدا از CI رد نشود.

کاملاً آفلاین و قطعی (هیچ شبکه‌ای، هیچ ساعتِ دیواری).

اجرا:  python3 correlation_test.py            (خروجی ۰ = سالم)
       PF_CORR_NO_MUT=1 python3 correlation_test.py   (بدونِ بخشِ جهش‌آزمایی)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import risk as RK          # noqa: E402

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
    return json.dumps(x, ensure_ascii=False, sort_keys=True)


def close(a, b, tol=0.011):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def msgs(c):
    """همه‌ی پیام‌های نمایشی در یک رشته (برای بررسیِ متن)."""
    return " || ".join(c.get("warnings") or [])


ST = {"balance": 10000.0, "account_ccy": "USD", "risk_pct": 1.0,
      "daily_loss_limit_pct": 3.0, "max_open_risk_pct": 5.0, "usd_per_quote": {}}


def op(sym, sign):
    return {"symbol": sym, "sign": sign}


# ═══════════════════════════════════════════════════════════════════
print("═══ ۱) جدولِ ضرایبِ طلایی: هر عدد و علامتش قفل است ═══")
GOLDEN = [
    ("BTCUSDT", "ETHUSDT", 0.85), ("BTCUSDT", "SOLUSDT", 0.78),
    ("ETHUSDT", "SOLUSDT", 0.80), ("BTCUSDT", "NAS100", 0.55),
    ("BTCUSDT", "XAUUSD", 0.20),
    ("XAUUSD", "XAGUSD", 0.82), ("XAUUSD", "DXY", -0.85),
    ("XAUUSD", "USDCAD", -0.55), ("XAUUSD", "AUDUSD", 0.45),
    ("WTI", "USDCAD", -0.45),
    ("EURUSD", "GBPUSD", 0.75), ("EURUSD", "AUDUSD", 0.65),
    ("AUDUSD", "NZDUSD", 0.88), ("EURUSD", "DXY", -0.96),
    ("USDCHF", "EURUSD", -0.90), ("USDJPY", "DXY", 0.90),
    ("SPX500", "NAS100", 0.94), ("US30", "SPX500", 0.92),
    ("GER40", "SPX500", 0.60),
]
check("جدولِ ضرایب دقیقاً ۱۹ ورودی دارد (افزودن/حذفِ بی‌صدا ممنوع)",
      len(RK.CORRELATION_COEFS) == len(GOLDEN),
      f"len={len(RK.CORRELATION_COEFS)} want={len(GOLDEN)}")
for a, b, c in GOLDEN:
    got = RK.pair_coef(a, b)
    check(f"ضریبِ {a}↔{b} = {c:+.2f}", got["known"] and close(got["coef"], c),
          f"got={got['coef']} known={got['known']}")
    rev = RK.pair_coef(b, a)
    check(f"تقارنِ {b}↔{a} (جابه‌جایی علامت را عوض نمی‌کند)",
          close(rev["coef"], c), f"got={rev['coef']}")
    check(f"یادداشتِ {a}↔{b} خالی نیست", bool((got.get("note") or "").strip()))
for a, b, c, _note in RK.CORRELATION_COEFS:
    check(f"ضریبِ {a}↔{b} در بازهٔ معتبرِ ‎[-۱, ۱]", abs(c) <= 1.0, str(c))
    check(f"ضریبِ {a}↔{b} صفر نیست (ورودیِ بی‌اثر در جدول نگذار)", c != 0, str(c))
check("آستانهٔ هشدار = ۰٫۵", close(RK.CORRELATION_WARN_MIN, 0.5), str(RK.CORRELATION_WARN_MIN))
check("آستانهٔ یادداشت = ۰٫۳", close(RK.CORRELATION_NOTE_MIN, 0.3), str(RK.CORRELATION_NOTE_MIN))
check("نمادِ یکسان ⇒ هم‌بستگی صفر (خودبا)",
      RK.pair_coef("XAUUSD", "XAUUSD")["known"] is False)
check("نمادِ ناشناخته ⇒ known=False و نه کرش",
      RK.pair_coef("ZZZZZZZ", "EURUSD")["known"] is False)

# ═══════════════════════════════════════════════════════════════════
print("═══ ۲) نرمال‌سازی: نامِ جایگزین/اسلش/بزرگیِ حروف ═══")
check("GOLD = XAUUSD", RK.pair_coef("GOLD", "DXY")["known"] is True)
check("XAU/USD = XAUUSD", close(RK.pair_coef("XAU/USD", "USDX")["coef"], -0.85),
      str(RK.pair_coef("XAU/USD", "USDX")))
check("حروفِ کوچک بی‌اثر است", close(RK.pair_coef("btcusdt", "ethusdt")["coef"], 0.85),
      str(RK.pair_coef("btcusdt", "ethusdt")))
check("فاصله‌های اضافه پاک می‌شود", close(RK.pair_coef(" BTCUSDT ", " ethusdt ")["coef"], 0.85),
      str(RK.pair_coef(" BTCUSDT ", " ethusdt ")))
# «XAU/USD» را موتور می‌شناسد (بالا سنجیده شد)؛ «GOLD/USD» در فهرستِ نام‌های موتور
# نیست، پس عمداً جفت *نمی‌شود* — سکوت بهتر از هشدارِ کاذب روی نمادِ ناشناخته است.
check("«GOLD/USD» (املای ناشناخته) بی‌صدا جفت نمی‌شود، نه هشدارِ کاذب",
      RK.pair_coef("gold/usd", "DXY")["known"] is False,
      str(RK.pair_coef("gold/usd", "DXY")))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۳) منطقِ بازار: علامت‌ها همان چیزی است که کارشناس می‌گوید ═══")
check("کریپتو: BTC↔ETH مثبتِ قوی", RK.pair_coef("BTCUSDT", "ETHUSDT")["coef"] > 0.8)
check("فلزات: طلا↔نقره مثبتِ قوی", RK.pair_coef("XAUUSD", "XAGUSD")["coef"] > 0.8)
check("طلا↔دلار منفی (DXY)", RK.pair_coef("XAUUSD", "DXY")["coef"] < -0.8)
_xc = RK.pair_coef("XAUUSD", "USDCAD")
check("طلا↔USDCAD منفی — یعنی طلا با «دلارِ کانادا» مثبت است (نکتهٔ علامت)",
      _xc["coef"] < 0, str(_xc["coef"]))
check("...و یادداشتش همین را توضیح می‌دهد",
      "کانادا" in (_xc.get("note") or ""), str(_xc.get("note")))
check("نفت↔USDCAD منفی (کانادا صادرکنندهٔ نفت است)",
      RK.pair_coef("WTI", "USDCAD")["coef"] < 0)
check("یورو↔دلار این‌دکس منفیِ شدید", RK.pair_coef("EURUSD", "DXY")["coef"] < -0.9)
check("ین↔دلار این‌دکس مثبت", RK.pair_coef("USDJPY", "DXY")["coef"] > 0.8)
check("کامودال‌ها: AUD↔NZD مثبتِ قوی", RK.pair_coef("AUDUSD", "NZDUSD")["coef"] > 0.8)
check("کریپتو↔شاخصِ تکنولوژی مثبت (ریسک‌آنِ مشترک)",
      RK.pair_coef("BTCUSDT", "NAS100")["coef"] > 0)

# ═══════════════════════════════════════════════════════════════════
print("═══ ۴) تخلفِ کاربر: سه حالت، هر کدام با عددِ ضریب ═══")
# ۴.الف) هم‌جهت روی ضریبِ مثبت = ریسکِ تکراری
c = RK.correlation("ETHUSDT", 1, [op("BTCUSDT", 1)])
check("BTC+ETH هم‌جهت ⇒ هشدارِ عددی داده شد", len(c["coef_warnings"]) == 1, msgs(c))
check("...با ذکرِ ضریبِ ‎+۰٫۸۵ در متن", "+0.85" in msgs(c), msgs(c))
check("...و با برچسبِ «ریسکِ هم‌بسته»", "ریسکِ هم‌بسته" in msgs(c), msgs(c))
check("ریسکِ مؤثر = ۱٫۸۵ برابرِ یک پوزیشن", close(c["effective"]["multiple"], 1.85),
      str(c["effective"]))
check("...شمارشِ پوزیشن‌های هم‌بسته = ۱", c["effective"]["stacked_count"] == 1, str(c["effective"]))
c = RK.correlation("BTCUSDT", 1, [op("ETHUSDT", 1), op("SOLUSDT", 1)])
check("BTC + ETH + SOL ⇒ ریسکِ مؤثر ۲٫۶۳ (۱ + ۰٫۸۵ + ۰٫۷۸)",
      close(c["effective"]["multiple"], 2.63) and c["effective"]["stacked_count"] == 2,
      str(c["effective"]))
check("...و هر دو ضریب در متن گفته می‌شود",
      "+0.85" in msgs(c) and "+0.78" in msgs(c), msgs(c))
c = RK.correlation("XAUUSD", 1, [op("XAGUSD", 1)])
check("طلا + نقره هم‌جهت ⇒ ریسکِ مؤثر ۱٫۸۲", close(c["effective"]["multiple"], 1.82),
      str(c["effective"]))

# ۴.ب) هم‌جهت روی ضریبِ منفی = دو سناریوی متضاد
c = RK.correlation("XAUUSD", 1, [op("USDCAD", 1)])
check("طلا خرید + USDCAD خرید ⇒ «تضادِ هم‌بستگی»", "تضادِ هم‌بستگی" in msgs(c), msgs(c))
check("...با ضریبِ ‎−۰٫۵۵", "-0.55" in msgs(c), msgs(c))
check("...و هشدارِ هج شمرده نمی‌شود (ریسکِ مؤثر ۱٫۰۰)",
      close(c["effective"]["multiple"], 1.0) and c["effective"]["hedged_count"] == 1,
      str(c["effective"]))
c = RK.correlation("EURUSD", 1, [op("DXY", 1)])
check("یورو خرید + دلار این‌دکس خرید ⇒ تضادِ ‎−۰٫۹۶", "تضادِ هم‌بستگی" in msgs(c) and "-0.96" in msgs(c),
      msgs(c))

# ۴.ج) خلافِ‌جهت روی ضریبِ مثبت = هجِ ناخواسته
c = RK.correlation("NAS100", -1, [op("SPX500", 1)])
check("NAS فروش + SPX خرید ⇒ «هجِ ناخواسته»", "هجِ ناخواسته" in msgs(c), msgs(c))
check("...با ضریبِ ‎+۰٫۹۴", "+0.94" in msgs(c), msgs(c))
check("...و مقدارِ هدررفته ۰٫۹۴", close(c["effective"]["offset"], 0.94), str(c["effective"]))
c = RK.correlation("ETHUSDT", -1, [op("BTCUSDT", 1)])
check("ETH فروش + BTC خرید ⇒ هجِ ناخواسته", "هجِ ناخواسته" in msgs(c), msgs(c))

# ۴.د) جهتِ درست ⇒ هیچ هشدارِ عددی
c = RK.correlation("ETHUSDT", -1, [op("BTCUSDT", -1)])
check("BTC فروش + ETH فروش (هم‌جهتِ درست) ⇒ هشدارِ عددی باز هم درست است (ریسکِ تکراری)",
      len(c["coef_warnings"]) == 1 and "ریسکِ هم‌بسته" in msgs(c), msgs(c))
c = RK.correlation("XAUUSD", -1, [op("DXY", 1)])
check("طلا فروش + دلار خرید (منفی، هم‌جهتِ منطقی) ⇒ ریسکِ هم‌بسته",
      "ریسکِ هم‌بسته" in msgs(c), msgs(c))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۵) مرزها: ملایم ⇒ یادداشت، ضعیف ⇒ سکوت ═══")
c = RK.correlation("XAUUSD", 1, [op("AUDUSD", 1)])
check("ضریبِ ۰٫۴۵ (کمتر از آستانه) ⇒ هشدارِ صریح نیست", c["coef_warnings"] == [], msgs(c))
check("...ولی یادداشتِ ملایم دارد", len(c["coef_notes"]) == 1, str(c["coef_notes"]))
check("...و عددِ ضریب در یادداشت هست", "+0.45" in " ".join(c["coef_notes"]),
      str(c["coef_notes"]))
c = RK.correlation("BTCUSDT", 1, [op("XAUUSD", 1)])
check("ضریبِ ۰٫۲۰ (کمتر از آستانهٔ یادداشت) ⇒ نه هشدار، نه یادداشت",
      c["coef_warnings"] == [] and c["coef_notes"] == [], msgs(c))
check("...ولی خودِ جدول آن را می‌شناسد (۰٫۲۰)", close(RK.pair_coef("BTCUSDT", "XAUUSD")["coef"], 0.20))
c = RK.correlation("XAUUSD", 1, [op("USDCAD", 1)])
check("ضریبِ ۰٫۵۵ (بالای آستانه) ⇒ هشدارِ صریح", len(c["coef_warnings"]) == 1, msgs(c))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۶) دو لایه: فاکتوری (کیفی) و عددی (کمّی) ═══")
c = RK.correlation("ETHUSDT", 1, [op("BTCUSDT", 1)])
check("لایهٔ فاکتوری هم BTC+ETH را می‌گیرد (فاکتورِ کریپتو)",
      len(c["trade_warnings"]) == 1, str(c["trade_warnings"]))
check("...ولی در فهرستِ نمایشی یک بار گفته می‌شود (حذفِ تکرار)",
      len(c["warnings"]) == 1 and "ریسکِ هم‌بسته" in c["warnings"][0], msgs(c))
check("فیلدهای خام دست‌نخورده‌اند (coef و factor جدا)",
      len(c["coef_warnings"]) == 1 and len(c["trade_warnings"]) == 1)
c = RK.correlation("XAUUSD", 1, [op("EURUSD", 1), op("GBPUSD", 1)])
check("جفت‌های بیرونِ جدول ⇒ هشدارِ عددی نیست", c["coef_warnings"] == [], msgs(c))
check("...ولی لایهٔ فاکتوری دلار را می‌گیرد (پس هر دو لایه لازم‌اند)",
      len(c["trade_warnings"]) >= 1, msgs(c))
c = RK.correlation("XAUUSD", 1, [op("USDJPY", 1)])
check("طلا + USDJPY (جدول ندارد) ⇒ تذکرِ فاکتوری می‌ماند",
      len(c["coef_warnings"]) == 0 and len(c["warnings"]) == 1, msgs(c))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۷) سطحِ API: evaluate همان هشدارها را می‌دهد ═══")
plan = {"entry": 4000.0, "sl": 3985.0, "rr": 3.0, "direction": "صعودی"}
rows = [{"status": "open", "realized_r": "", "risk_pct": "1",
         "datetime": "2026-09-20 10:00", "symbol": "USDCAD", "direction": "long"}]
ev = RK.evaluate("XAUUSD", plan, ST, rows)
check("evaluate: هشدارِ هم‌بستگیِ عددی در warnings هست",
      "تضادِ هم‌بستگی" in " ".join(ev["warnings"]), str(ev["warnings"])[:200])
check("evaluate: بلوکِ correlation عددی را هم می‌دهد",
      (ev["correlation"].get("effective") or {}).get("hedged_count") == 1,
      str(ev["correlation"].get("effective")))
check("evaluate: پوزیشنِ بازِ USDCAD درست تجزیه شد",
      [p["symbol"] for p in ev["daily"]["open_positions"]] == ["USDCAD"],
      str(ev["daily"]["open_positions"]))
ev2 = RK.evaluate("ETHUSDT", {"entry": 3000.0, "sl": 2900.0, "rr": 2.0,
                              "direction": "صعودی"}, ST,
                  [{"status": "open", "realized_r": "", "risk_pct": "1",
                    "datetime": "2026-09-20 10:00", "symbol": "BTCUSDT",
                    "direction": "long"}])
check("evaluate: BTC+ETH ⇒ ریسکِ مؤثرِ ۱٫۸۵ در بلوکِ API",
      close((ev2["correlation"].get("effective") or {}).get("multiple"), 1.85),
      str(ev2["correlation"].get("effective")))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۸) سیم‌کشیِ اپ: همین هشدار به کاربر نشان داده می‌شود ═══")
try:
    import io
    with io.open(os.path.join(HERE, "app.py"), encoding="utf-8") as f:
        APP = f.read()
except OSError as ex:
    APP = ""
    check("app.py خوانده می‌شود", False, str(ex))
check("ثبتِ ژورنال، هم‌بستگی را به رابط برمی‌گرداند",
      'out["correlation"] = corr_before' in APP)
check("...و پیش از افزودن حساب می‌شود (پوزیشن با خودش مقایسه نشود)",
      'corr_before = RK.correlation' in APP)
check("رابط، تذکرِ ثبت را نشان می‌دهد",
      "j.correlation && j.correlation.warnings" in APP)
check("رابط، ضرایبِ به‌کاررفته را زیرِ هشدار چاپ می‌کند",
      "coef_pairs" in APP and "ضرایبِ هم" in APP)

# ═══════════════════════════════════════════════════════════════════
print("═══ ۹) ورودی‌های ناسالم: هیچ کرشی، هیچ هشدارِ کاذب ═══")
check("جهتِ نامشخص ⇒ بدونِ لایهٔ عددی",
      RK.coef_layer("BTCUSDT", 0, [op("ETHUSDT", 1)])["warnings"] == [])
check("بدونِ پوزیشنِ باز ⇒ بدونِ هشدار", RK.correlation("EURUSD", 1, [])["warnings"] == [])
check("نمادِ ناشناخته ⇒ بدونِ کرش",
      RK.correlation("ZZZZZZZ", 1, [op("BTCUSDT", 1)])["warnings"] == [])
check("پوزیشنِ بازِ ناشناخته ⇒ نادیده گرفته می‌شود",
      RK.correlation("BTCUSDT", 1, [op("QQQQQQQ", 1)])["coef_warnings"] == [])
check("ورودیِ غیردیکشنری در فهرستِ باز ⇒ کرش نمی‌کند",
      RK.coef_layer("BTCUSDT", 1, [None, "x", 5])["warnings"] == [])
check("پوزیشنِ باز بدونِ جهت ⇒ نادیده گرفته می‌شود",
      RK.coef_layer("BTCUSDT", 1, [{"symbol": "ETHUSDT"}])["warnings"] == [])

# ═══════════════════════════════════════════════════════════════════
print("═══ ۱۰) جهش‌آزمایی: تست باید دندان داشته باشد ═══")
ANCHORS = {
    "btc_eth": ('("BTCUSDT", "ETHUSDT", 0.85,', "risk.py"),
    "xau_usdcad": ('("XAUUSD", "USDCAD", -0.55,', "risk.py"),
    "warn_min": ("CORRELATION_WARN_MIN = 0.5", "risk.py"),
    "note_min": ("CORRELATION_NOTE_MIN = 0.3", "risk.py"),
    "aligned": ('"aligned": bool(sign * psgn * c > 0)}', "risk.py"),
    "multiple": ('out["effective"]["multiple"] = round(1.0 + add, 2)', "risk.py"),
    "display": ('"warnings": cl["warnings"] + opp_msgs + shown_trade + cl["notes"] + conc,',
                "risk.py"),
    "note_gate": ('if not info["known"] or abs(info["coef"]) < CORRELATION_NOTE_MIN:',
                  "risk.py"),
    "green_a": ("_COEF_MAP = {}", "risk.py"),
    "green_b": ("CORRELATION_NOTE_MIN = 0.3", "risk.py"),
}


def mutate(src, muts):
    """هر نشانه‌ای که پیدا نشود ⇒ خطای صریح (نه سبزِ بی‌صدا)."""
    out = src
    for needle, repl, count in muts:
        got = out.count(needle)
        if got != count:
            return None, f"نشانهٔ جهش {count} بار انتظار می‌رفت ولی {got} بار بود: {needle[:60]}"
        out = out.replace(needle, repl)
    return out, None


def run_sandbox(muts=None):
    d = tempfile.mkdtemp(prefix="pf_corr_mut_")
    try:
        for fn in sorted(os.listdir(HERE)):
            if fn.endswith(".py"):
                shutil.copyfile(os.path.join(HERE, fn), os.path.join(d, fn))
        if muts is not None:
            path = os.path.join(d, "risk.py")
            with open(path, encoding="utf-8") as f:
                src = f.read()
            src, err = mutate(src, muts)
            if err:
                return None, err
            with open(path, "w", encoding="utf-8") as f:
                f.write(src)
        env = dict(os.environ)
        env["PF_CORR_NO_MUT"] = "1"          # جلوگیری از بازگشتِ بی‌پایان
        env.pop("PYTHONPATH", None)
        p = subprocess.run([sys.executable, TEST_NAME], cwd=d, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        return p.returncode, p.stdout.decode("utf-8", errors="replace")
    finally:
        shutil.rmtree(d, ignore_errors=True)


if not os.environ.get("PF_CORR_NO_MUT"):
    for k, (needle, fn) in ANCHORS.items():
        try:
            with open(os.path.join(HERE, fn), encoding="utf-8") as f:
                txt = f.read()
            check(f"لنگرِ جهشِ «{k}» در {fn} هست", txt.count(needle) == 1,
                  f"count={txt.count(needle)}")
        except OSError as ex:
            check(f"لنگرِ جهشِ «{k}» فایلش خوانده می‌شود", False, str(ex))

    rc0, out0 = run_sandbox()
    check("جهش‌آزمایی: کپیِ سالم هم سبز است (هارنس واقعاً همین تست را اجرا می‌کند)",
          rc0 == 0 and "• بررسی‌ها:" in (out0 or ""),
          (out0 or "")[-300:] if rc0 is None else f"rc={rc0} " + (out0 or "")[-300:])

    RED = [
        ("کم‌کردنِ ضریبِ BTC↔ETH به ۰٫۰۵", "ضریبِ BTCUSDT↔ETHUSDT",
         [('("BTCUSDT", "ETHUSDT", 0.85,', '("BTCUSDT", "ETHUSDT", 0.05,', 1)]),
        ("برعکس‌کردنِ علامتِ طلا↔USDCAD (و از دست دادنِ منطقِ دلارِ کانادا)",
         "طلا↔USDCAD منفی",
         [('("XAUUSD", "USDCAD", -0.55,', '("XAUUSD", "USDCAD", 0.55,', 1)]),
        ("بالا بردنِ آستانهٔ هشدار تا هیچ‌چیز هشدار نشود", "هشدارِ عددی داده شد",
         [("CORRELATION_WARN_MIN = 0.5", "CORRELATION_WARN_MIN = 9.9", 1)]),
        ("صفر کردنِ آستانهٔ یادداشت (۰٫۲۰ هم یادداشت بگیرد)", "ضریبِ ۰٫۲۰",
         [("CORRELATION_NOTE_MIN = 0.3", "CORRELATION_NOTE_MIN = 0.0", 1)]),
        ("وارونه‌کردنِ معنای «هم‌جهت»", "ریسکِ هم‌بسته",
         [('"aligned": bool(sign * psgn * c > 0)}', '"aligned": bool(sign * psgn * c < 0)}', 1)]),
        ("عددِ ریسکِ مؤثر با فرمولِ دیگر", "ریسکِ مؤثر = ۱٫۸۵",
         [('out["effective"]["multiple"] = round(1.0 + add, 2)',
           'out["effective"]["multiple"] = round(2.0 + add, 2)', 1)]),
        ("حذفِ هشدارِ عددی از فهرستِ نمایشی (رابط ساکت می‌شود)", "حذفِ تکرار",
         [('"warnings": cl["warnings"] + opp_msgs + shown_trade + cl["notes"] + conc,',
           '"warnings": opp_msgs + shown_trade + cl["notes"] + conc,', 1)]),
        ("نادیده‌گرفتنِ آستانهٔ یادداشت در حلقه", "ضریبِ ۰٫۲۰",
         [('if not info["known"] or abs(info["coef"]) < CORRELATION_NOTE_MIN:',
           'if not info["known"]:', 1)]),
    ]
    GREEN = [
        ("کامنتِ بی‌گناه بالای _COEF_MAP", "risk.py",
         [("_COEF_MAP = {}", "_COEF_MAP = {}  # PF-GREEN", 1)]),
        ("متغیرِ بلااستفاده در risk.py", "risk.py",
         [("CORRELATION_NOTE_MIN = 0.3",
           "CORRELATION_NOTE_MIN = 0.3\n_UNUSED_CORR_LIMIT = 99", 1)]),
    ]

    for label, want, muts in RED:
        rc, out = run_sandbox(muts)
        if rc is None:
            check("جهشِ سرخ | " + label, False, out)
        else:
            check("جهشِ سرخ | " + label,
                  rc != 0 and "::error::" in out and want in out,
                  f"rc={rc} · «{want}» {'دیده شد' if want in (out or '') else 'دیده نشد'}")

    for label, fn, muts in GREEN:
        rc, out = run_sandbox(muts)
        if rc is None:
            check("جهشِ سبز | " + label, False, out)
        else:
            check("جهشِ سبز | " + label, rc == 0, f"rc={rc} " + (out or "")[-300:])

NOTES.append("• نکتهٔ علامت که در اپ هم توضیح داده می‌شود: طلا و دلارِ کانادا "
             "هم‌بستگیِ *مثبت* دارند (کانادا صادرکنندهٔ طلا/نفت است)، ولی نمادِ "
             "قابلِ‌معامله USDCAD وارونهٔ CAD است؛ پس در جدول ضریبِ XAUUSD↔USDCAD "
             "منفی (‎-۰٫۵۵) است و همان برای کاربر به‌صورتِ «تضادِ هم‌بستگی» هشدار داده می‌شود.")
NOTES.append("• جدولِ ضرایب عمداً ثابت است (میانگینِ ~۹۰ روزهٔ ۲۰۲۳–۲۰۲۶): محاسبهٔ "
             "هم‌بستگیِ زنده به دادهٔ تاریخیِ چند نماد نیاز دارد و اپ باید آفلاین و "
             "قطعی بماند. مقدارِ هر ضریب با تستِ طلایی قفل شده تا تغییرش بی‌صدا نماند.")

# ── گزارش ──
for n in NOTES:
    print(n)
print(f"• بررسی‌ها: {len(CHECKS)}")
if FAILS:
    print("")
    for name, detail in FAILS:
        print(f"::error::❌ {name}" + (f" — {detail}" if detail else ""))
    print(f"\n❌ تستِ «هم‌بستگیِ عددی» رد شد — {len(FAILS)} از {len(CHECKS)} بررسی شکست خورد")
    sys.exit(1)
print("✅ تستِ «هم‌بستگیِ عددی» پاس شد — ضرایبِ مرجع قفل‌اند و تخلفِ کاربر "
      "(ریسکِ تکراری · تضادِ منطقی · هجِ ناخواسته) با عدد تذکر داده می‌شود")
