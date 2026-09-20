#!/usr/bin/env python3
"""تستِ «تحلیل هرگز روی کندلِ ناقص» + «سنِ داده و باز/بسته بودنِ بازار».

این تست کاملاً **آفلاین** است: به هیچ شبکه‌ای (Yahoo/Binance) دست نمی‌زند و روی
کندل‌های ساختگی کار می‌کند، پس در CI و روی هر ماشینی یکسان است.

چرا لازم است: پیش از این، مسیرِ زنده کندلِ در حالِ تشکیل را هم تحلیل می‌کرد
(repaint) و اپ روی بازارِ بسته هم پلنِ «قابلِ اجرا» می‌داد — دو خطایی که هیچ‌کدام
تست نداشتند. این تست هر دو را قفل می‌کند.

اجرا:  python3 data_freshness_test.py        (خروجی ۰ = سالم)
"""
import datetime
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import smc_engine as E          # noqa: E402
import confluence as CF         # noqa: E402
import backtest as BT           # noqa: E402

CHECKS = []
FAILS = []


def check(name, cond, detail=""):
    CHECKS.append(name)
    if not cond:
        FAILS.append((name, detail))


# ─────────────────────────────────────────────────────────────
# ابزار: ساختِ کندل‌های ساختگی با تایم‌استمپِ واقعی (بر پایه‌ی زمانِ ثابتِ تست)
# ─────────────────────────────────────────────────────────────
T0 = int(datetime.datetime(2026, 6, 10, 12, 0,
                           tzinfo=datetime.timezone.utc).timestamp())  # چهارشنبه، بازار باز


def mk_bars(tf, n, end_open_ts, start_price=100.0, step=0.5):
    """n کندلِ ساعت‌دار که **آخرینِ آن‌ها در `end_open_ts` باز می‌شود**."""
    secs = E.tf_seconds(tf)
    out = []
    for i in range(n):
        t = end_open_ts - (n - 1 - i) * secs
        base = start_price + i * step
        out.append({"t": t, "o": base, "h": base + 1.0, "l": base - 1.0,
                    "c": base + 0.4, "v": 10.0})
    return out


print("═══ ۱) drop_unclosed: کندلِ در حالِ تشکیل هرگز در تحلیل نمی‌ماند ═══")
for tf in ("1m", "5m", "15m", "1h", "4h", "1d"):
    secs = E.tf_seconds(tf)
    now = T0
    # آخرین کندل در «وسطِ» دوره است ⇒ ناقص ⇒ باید حذف شود
    forming_start = now - secs // 3
    bars = mk_bars(tf, 40, forming_start)
    kept, dropped = E.drop_unclosed(bars, tf, now=now)
    check(f"drop_unclosed[{tf}] کندلِ ناقص حذف شد", dropped == 1 and len(kept) == 39,
          f"dropped={dropped} kept={len(kept)}")
    check(f"drop_unclosed[{tf}] آخرین کندلِ باقی‌مانده بسته است",
          kept[-1]["t"] + secs <= now,
          f"t+secs={kept[-1]['t']+secs} > now={now}")
    # مرز: کندلی که **دقیقاً** در لحظه‌ی now بسته می‌شود، بسته حساب می‌شود
    closed_start = now - secs
    bars2 = mk_bars(tf, 5, closed_start)
    kept2, dropped2 = E.drop_unclosed(bars2, tf, now=now)
    check(f"drop_unclosed[{tf}] مرز دقیق (t+secs == now) بسته حساب می‌شود",
          dropped2 == 0 and len(kept2) == 5, f"dropped={dropped2}")

print("═══ ۲) مسیرِ زنده (analyze) کندلِ ناقص را حذف می‌کند ═══")
# fetch را جعل می‌کنیم تا تست آفلاین بماند: ۲۰۰ کندلِ ۱۵m که ۱ تای آخرشان ناقص است.
FAKE_N = 200
_orig_fetch = E.fetch


def fake_fetch(symbol, tf, limit, unclosed=False):
    secs = E.tf_seconds(tf)
    now_ms = int(time.time())
    # آخرین کندل با ۱/۳ اختلاف تا لحظه‌ی حالا شروع شده ⇒ ناقص
    last_open = now_ms - secs // 3
    bars = mk_bars(tf, FAKE_N, last_open, start_price=2000.0, step=0.1)
    if unclosed:
        return "yahoo", "GC=F", "XAUUSD", bars
    bars, _d = E.drop_unclosed(bars, tf)
    return "yahoo", "GC=F", "XAUUSD", bars


E.fetch = fake_fetch
try:
    r = E.analyze("XAUUSD", "15m", limit=FAKE_N)
finally:
    E.fetch = _orig_fetch

dd = r.get("data") or {}
check("analyze بلوکِ data برمی‌گرداند", bool(dd), f"data={dd}")
check("analyze کندلِ ناقص را تحلیل نکرده",
      dd.get("last_bar_ts") is not None and not dd.get("forming"),
      f"forming={dd.get('forming')} last={dd.get('last_bar_ts')}")
check("سنِ داده = زمانِ بسته‌شدنِ کندلِ آخر (نه زمانِ بازشدن)",
      dd.get("age_s") is not None and dd.get("age_s") < E.tf_seconds("15m"),
      f"age_s={dd.get('age_s')}")
# کندلِ ناقص باید ۲/۳ دوره‌ی قبل + ۱ دوره‌ی قبل‌تر باز شده باشد ⇒ آخرین کندلِ تحلیل
# یکی مانده به آنِ ناقص است.
expected_last = (int(time.time()) - E.tf_seconds("15m") // 3) - E.tf_seconds("15m")
check("آخرین کندلِ تحلیل‌شده همان کندلِ بستهٔ قبلیِ کندلِ ناقص است",
      abs(dd.get("last_bar_ts", 0) - expected_last) <= 1,
      f"got={dd.get('last_bar_ts')} want≈{expected_last}")

print("═══ ۳) تازگی/باز-بسته (freshness_from) — بدونِ شبکه ═══")
cases = [
    # (نام, نماد, منبع, چند برابرِ دوره کهنه, حالتِ انتظاری)
    ("کریپتو تازه",            "BTCUSDT", "binance", 0.5, "open"),
    ("کریپتو یک دوره عقب",      "BTCUSDT", "binance", 2.0, "open"),
    ("کریپتو ۴ دوره عقب",       "BTCUSDT", "binance", 5.0, "closed"),
    ("فارکس وسطِ هفته تازه",    "EURUSD",  "yahoo",   0.5, "open"),
    ("فارکس وسطِ هفته عقب",     "EURUSD",  "yahoo",   2.0, "open"),
    ("فارکس وسطِ هفته کهنه",     "EURUSD",  "yahoo",   5.0, "closed"),
]
for name, sym, src, mult, want in cases:
    last = T0 - int(mult * E.tf_seconds("15m"))
    f = E.freshness_from(last, "15m", sym, src=src, now=T0)
    check(f"freshness[{name}] → {want}", f.get("state") == want,
          f"got={f.get('state')} reason={f.get('reason')}")

print("═══ ۴) آخرِ هفته (شنبه) برای غیرِکریپتو «بسته» است، کریپتو نه ═══")
sat = int(datetime.datetime(2026, 6, 13, 12, 0,
                            tzinfo=datetime.timezone.utc).timestamp())  # شنبه
last = sat - 60
check("شنبه: XAUUSD = closed",
      E.freshness_from(last, "15m", "XAUUSD", src="yahoo", now=sat).get("state") == "closed")
check("شنبه: NVDA = closed",
      E.freshness_from(last, "15m", "NVDA", src="yahoo", now=sat).get("state") == "closed")
check("شنبه: BTCUSDT = open (کریپتو ۲۴/۷)",
      E.freshness_from(last, "15m", "BTCUSDT", src="binance", now=sat).get("state") == "open")
fri_open = int(datetime.datetime(2026, 6, 12, 16, 0,
                                 tzinfo=datetime.timezone.utc).timestamp())  # جمعه ۱۲:۰۰ ET
check("جمعه پیش از ۱۷:۰۰ ET = باز",
      E.freshness_from(fri_open - 60, "15m", "EURUSD", src="yahoo",
                       now=fri_open).get("state") == "open")
fri_close = int(datetime.datetime(2026, 6, 12, 22, 0,
                                  tzinfo=datetime.timezone.utc).timestamp())  # جمعه ۱۸:۰۰ ET
check("جمعه بعد از ۱۷:۰۰ ET = بسته",
      E.freshness_from(fri_close - 60, "15m", "EURUSD", src="yahoo",
                       now=fri_close).get("state") == "closed")

print("═══ ۵) سشنِ سهام: خارج از ۰۹:۳۰–۱۶:۰۰ ET = «نازک»، نه فول‌بلاک ═══")
pre_rth = int(datetime.datetime(2026, 6, 10, 13, 0,
                                tzinfo=datetime.timezone.utc).timestamp())  # چهارشنبه ۰۹:۰۰ ET
f = E.freshness_from(pre_rth - 60, "15m", "NVDA", src="yahoo", now=pre_rth)
check("NVDA پیش از RTH = thin", f.get("state") == "thin", f"got={f.get('state')}")

print("═══ ۶) گریدر: بازارِ بسته درجه را می‌بندد و پلن را «غیرقابلِ اجرا» می‌کند ═══")
# دِیکشنریِ ساختگیِ کمینه‌ی d که score() می‌خواند (یک تایم‌فریم)
def fake_d(state, last_bar_ts, price=4300.0):
    data = E.freshness_from(last_bar_ts, "15m", "XAUUSD", src="yahoo",
                            now=(last_bar_ts + E.tf_seconds("15m")))
    data["state"] = state          # حالت را مستقیم تحمیل می‌کنیم تا تست قطعی باشد
    return {"15m": {
        "trend": "up", "CHoCH": ("bullish_CHoCH", 4280.0, 10),
        "BOS": ("bullish_BOS", 4290.0, 12),
        "last_price": price, "bars": 200, "data": data,
        "premium_discount": {"range_top": 4400.0, "range_bottom": 4200.0,
                             "zone": "discount", "price_pct": 50.0},
        "liquidity": {"buyside_eqh": [4395.0], "sellside_eql": [4205.0],
                      "range_high": 4400.0, "range_low": 4200.0, "session": {}},
        "liquidity_sweeps": [{"type": "bullish_sweep", "level": 4240.0,
                              "bar_from_end": 2, "idx": 190}],
        "liquidity_patterns": [], "displacement": {"present": True, "direction": "bullish",
                                                  "body_x_avg": 2.1, "bar_from_end": 1},
        "FVG_unfilled": [{"type": "bullish", "top": 4305.0, "bottom": 4292.0, "idx": 195}],
        "order_blocks": [{"type": "bullish", "top": 4298.0, "bottom": 4284.0, "idx": 194}],
        "killzone": "New York AM KZ (08:30-11:00 ET)",
        "sequence_ok": True, "mss_meta": {},
    }}


for state in ("open", "delayed", "closed"):
    d = fake_d(state, T0)
    if state == "open":
        d["15m"]["data"] = E.freshness_from(T0 - 60, "15m", "XAUUSD", src="yahoo", now=T0)
        d["15m"]["data"]["state"] = "open"
    row = None
    try:
        r = CF.score("XAUUSD", ["15m"], d=d)
        row = next((c for c in r["checklist"] if "تازگیِ داده" in c["name"]), None)
    except Exception as ex:
        r = {"error": str(ex)}
    check(f"score[{state}] بدونِ خطا اجرا شد", "error" not in r and row is not None,
          f"r={r if 'error' in r else row}")
    if row is None:
        continue
    if state == "open":
        check("score[open] ردیفِ تازگی ✓ است", row["status"] == "✓", str(row))
        check("score[open] پلن (اگر باشد) قابلِ اجرا است",
              (r.get("plan") or {}).get("executable_now", True) is True, str(r.get("plan")))
    elif state == "delayed":
        check("score[delayed] ردیفِ تازگی ◐ (نیم‌امتیاز) است", row["status"] == "◐", str(row))
        check("score[delayed] درجه از A بالاتر نمی‌رود", r.get("grade") not in ("A+", "A"),
              f"grade={r.get('grade')}")
    else:
        check("score[closed] ردیفِ تازگی ✗ است", row["status"] == "✗", str(row))
        check("score[closed] درجه به C محدود شد", r.get("grade") == "C", f"grade={r.get('grade')}")
        check("score[closed] verdict صریحاً می‌گوید بازار بسته است",
              "بسته" in (r.get("verdict") or ""), (r.get("verdict") or "")[:80])
        p = r.get("plan")
        if p:
            check("score[closed] plan.executable_now = False", p.get("executable_now") is False, str(p))
            check("score[closed] plan.blocked_reason پر است", bool(p.get("blocked_reason")), str(p))
        check("score[closed] مهرِ ورود صادر نشد",
              (r.get("entry_stamp") or {}).get("stamped") is False,
              str(r.get("entry_stamp")))

print("═══ ۷) بک‌تست: کندلِ HTFِ هنوز-باز در لحظه‌ی تصمیم دیده نمی‌شود (ضدِ look-ahead) ═══")
series = {"_disp": "XAUUSD"}
# کندلِ ۱۵m از ۱۰:۰۰ تا ۱۰:۱۵، کندلِ ۱ساعته از ۱۰:۰۰ (در ۱۰:۱۵ هنوز باز است)
t_1500 = T0
series["15m"] = mk_bars("15m", 60, t_1500, start_price=4300.0, step=0.2)
series["1h"] = mk_bars("1h", 60, t_1500, start_price=4300.0, step=0.5)
d = BT._build_d(series, ["1h", "15m"], t_1500, warm=40)
check("_build_d دیکشنریِ کامل برگرداند", isinstance(d, dict) and "15m" in d and "1h" in d, str(type(d)))
if isinstance(d, dict) and "1h" in d and "error" not in d["1h"]:
    h1_last = d["1h"]["data"].get("last_bar_ts")
    check("کندلِ ۱ساعتهٔ در حالِ تشکیل در بک‌تست حذف شده",
          h1_last is not None and h1_last <= t_1500 - E.tf_seconds("1h"),
          f"last_1h={h1_last} t_now={t_1500}")
    check("کندلِ ورود (۱۵m) در تحلیل باقی مانده",
          d["15m"]["data"].get("last_bar_ts") == t_1500,
          f"last_15m={d['15m']['data'].get('last_bar_ts')}")

# ─────────────────────────────────────────────────────────────
print()
if FAILS:
    print(f"❌ {len(FAILS)} بررسی از {len(CHECKS)} بررسی رد شد:")
    for n, det in FAILS:
        print(f"   • {n}" + (f"  →  {det}" if det else ""))
    sys.exit(1)
print(f"✅ همه‌ی {len(CHECKS)} بررسیِ تازگیِ داده/کندلِ بسته سبز شد.")
sys.exit(0)
