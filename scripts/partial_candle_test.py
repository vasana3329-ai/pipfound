#!/usr/bin/env python3
"""تستِ «کندلِ ناقص» — موتور روی آخرین کندلِ بسته‌نشده سیگنال نمی‌سازد.

پیشینه (باقی‌ماندهٔ P1-3 / یافتهٔ B1): کندلِ در حالِ تشکیل (ناقص) اگر به تحلیل
برسد، هر سطحی که از آن ساخته شود — سوینگ، FVG، اُردربلاک، PD/OTE، حتی برچسبِ
کیل‌زون — تا لحظهٔ بسته‌شدن جابه‌جا می‌شود؛ یعنی «پلن» عوض می‌شود بدونِ اینکه
چیزی روی دیسک عوض شود (repaint). بدتر: `freshness_from` برای کندلِ ناقص
`age_s=0` می‌دهد (چون تُرَندِ بسته‌شدن در آینده است) و آن را «تازه/باز» می‌بیند؛
پس یک تحلیلِ ناقص می‌تواند درجه‌ی A و مهرِ ورود بگیرد، بی‌صدا.

این تست سه لایهٔ دفاعی را قفل می‌کند:
  ۱) **نقطهٔ گلوگاهِ ورود** — `drop_unclosed` در مسیرِ زنده (`fetch`) و بک‌تست
     (`_build_d`): کندلِ ناقص پیش از رسیدن به تحلیل می‌افتد. مرزِ بسته‌شدن دقیقاً
     `t + طولِ کندل ≤ now` است (برابری = بسته).
  ۲) **هستهٔ موتور** — `analyze_bars` خودش هم پیمان را چک می‌کند: اگر کندلِ آخر
     هنوز باز باشد، خطای صریح می‌دهد (نه سبزِ خاموش).
  ۳) **گریدر** — فلگِ `data.forming` سقفِ درجه = C، `executable_now=False`،
     `blocked_reason`، و مهرِ ورودِ صادر‌نشده می‌دهد (دفاعِ عمقِ دوم برای پلن‌هایی
     که `d` آن‌ها دستی ساخته می‌شود).

کاملاً آفلاین و قطعی (بدونِ شبکه، بدونِ ساعتِ دیوار مگر یک بررسیِ مرزی).
اجرا:  python3 partial_candle_test.py            (خروجی ۰ = سالم)
       PF_PARTIAL_NO_MUT=1 python3 partial_candle_test.py   (بدونِ بخشِ ۶)
"""
import datetime
import json
import os
import shutil
import socket as _socket
import subprocess
import sys
import tempfile
import time
import urllib.request as _urllib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ── نگهبانِ هرمتیک: این تست هرگز نباید به شبکه دست بزند ─────────────────
# گیتِ اخبارِ کلان در گریدر (`confluence.score`) تقویمِ اقتصادی را از اینترنت
# می‌گیرد. بدونِ این گارد، زمانِ اجرا — و در بدترین حالت نتیجه — به وضعیتِ
# شبکه گره می‌خورد: روی شبکهٔ کند یا قطع، DNS تا ~۴۰ ثانیه معطل می‌ماند و
# هارنسِ جهش (۸ اجرای تودرتو) از بودجهٔ CI بیرون می‌زند.
NET_ATTEMPTS = []


def _no_network(*a, **kw):
    NET_ATTEMPTS.append(str(a[0])[:80] if a else "")
    raise OSError("offline-guard: دسترسیِ شبکه در این تست بسته است")


_socket.getaddrinfo = _no_network
_socket.create_connection = _no_network
_urllib.urlopen = _no_network

import smc_engine as E          # noqa: E402
import confluence as CF         # noqa: E402
import backtest as BT           # noqa: E402


class _StubCalendar(object):
    """پاسخِ ثابتِ تقویمِ اقتصادی (GREEN) — تا گریدر قطعی و آفلاین بماند."""

    @staticmethod
    def get_calendar():
        return []

    @staticmethod
    def symbol_ccys(symbol):
        return []

    @staticmethod
    def news_gate(cal, ccys):
        return ("GREEN", "پنجرهٔ عادی — خبرِ های‌ایمپکتِ نزدیک نیست", None)


CF.M = _StubCalendar

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
# ابزارِ ساختِ کندل روی ساعتِ ثابتِ تست (چهارشنبه ۲۰۲۶-۰۶-۱۰ ۱۲:۰۰ UTC)
# ═══════════════════════════════════════════════════════════════════
T0 = int(datetime.datetime(2026, 6, 10, 12, 0, tzinfo=datetime.timezone.utc).timestamp())


def bar(t, o, h, l, c, v=10.0):
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}


def mk(tf, n, last_open, start=100.0, step=0.5):
    """n کندلِ ساعت‌دار؛ **آخرینِ آن‌ها در `last_open` باز می‌شود**."""
    secs = E.tf_seconds(tf)
    out = []
    for i in range(n):
        t = last_open - (n - 1 - i) * secs
        base = start + i * step
        out.append(bar(t, base, base + 1.0, base - 1.0, base + 0.4))
    return out


# ═══════════════════════════════════════════════════════════════════
print("═══ ۱) drop_unclosed: مرزِ بسته‌شدن و حذفِ کندلِ ناقص ═══")
# سریِ کاملاً بسته: آخرین کندل در ۱۱:۴۵ باز شده و در ۱۲:۰۰ (= T0) بسته است.
closed = mk("15m", 40, T0 - E.tf_seconds("15m"))
kept, dropped = E.drop_unclosed(closed, "15m", now=T0)
check("حذف: سریِ کاملاً بسته دست‌نخورده می‌ماند", dropped == 0 and j(kept) == j(closed),
      f"dropped={dropped}")

# سری با یک کندلِ ناقص در انتها: درست در T0 باز شده ⇒ هنوز باز است
forming = closed + [bar(T0, 105.0, 999.0, 104.0, 998.0)]
kept2, dropped2 = E.drop_unclosed(forming, "15m", now=T0)
check("حذف: کندلِ ناقصِ انتهای سری می‌افتد",
      dropped2 == 1 and len(kept2) == len(closed), f"dropped={dropped2} kept={len(kept2)}")
check("حذف: سریِ باقی‌مانده بیت‌به‌بیت همان سریِ بسته است", j(kept2) == j(closed))

# مرزِ دقیق: کندلی که همین حالا (t+secs == now) بسته می‌شود «بسته» است، نه ناقص
b_before = mk("15m", 5, T0 - 2 * E.tf_seconds("15m"))      # آخرین: ۱۱:۳۰ → بسته ۱۱:۴۵
b_exact = mk("15m", 5, T0 - E.tf_seconds("15m"))           # آخرین: ۱۱:۴۵ → بسته ۱۲:۰۰ = now
k3, d3 = E.drop_unclosed(b_exact, "15m", now=T0)
check("مرزِ دقیقِ بسته‌شدن: کندلی که همین حالا بسته می‌شود حفظ می‌شود",
      d3 == 0 and len(k3) == 5, f"dropped={d3}")
k4, d4 = E.drop_unclosed(b_exact, "15m", now=T0 - 1)       # یک ثانیه قبل‌تر ⇒ همان کندل ناقص
check("مرزِ دقیقِ بسته‌شدن: یک ثانیه زودتر بودن = کندلِ ناقص",
      d4 == 1 and len(k4) == 4, f"dropped={d4}")

# چند کندلِ ناقصِ پشت‌سرهم (مثلاً فیدِ جلوتر از ساعتِ سیستم)
multi = closed + [bar(T0, 105.0, 106.0, 104.0, 105.5),
                  bar(T0 + E.tf_seconds("15m"), 105.5, 107.0, 105.0, 106.0)]
k5, d5 = E.drop_unclosed(multi, "15m", now=T0)
check("حذف: دو کندلِ ناقصِ پشت‌سرهم هر دو می‌افتند",
      d5 == 2 and len(k5) == len(closed), f"dropped={d5}")
k6, d6 = E.drop_unclosed([], "15m", now=T0)
check("حذف: آرایهٔ خالی امن است (بدونِ خطا)", k6 == [] and d6 == 0)

# همان قاعده در همهٔ تایم‌فریم‌ها
for tf in ("1m", "5m", "15m", "1h", "4h", "1d"):
    secs = E.tf_seconds(tf)
    s = mk(tf, 40, T0 - secs) + [bar(T0, 100.0, 101.0, 99.0, 100.5)]
    kk, dd = E.drop_unclosed(s, tf, now=T0)
    check(f"حذف[{tf}]: کندلِ در حالِ تشکیل می‌افتد و آخرینِ باقی‌مانده بسته است",
          dd == 1 and kk[-1]["t"] + secs <= T0, f"dropped={dd} last_close={kk[-1]['t']+secs}")

# ═══════════════════════════════════════════════════════════════════
print("═══ ۲) هستهٔ موتور: analyze_bars کندلِ ناقص را نمی‌پذیرد ═══")
err_msg = None
try:
    E.analyze_bars(forming, "15m", disp="T", src="test", sym="XAUUSD", now=T0)
except RuntimeError as ex:
    err_msg = str(ex)
except Exception as ex:                       # noqa: BLE001
    err_msg = f"نوعِ خطای نادرست: {type(ex).__name__}: {ex}"
check("هستهٔ موتور: analyze_bars روی کندلِ ناقص خطای صریح می‌دهد", bool(err_msg), "خطایی نداد!")
check("هستهٔ موتور: پیامِ خطا می‌گوید drop_unclosed را صدا بزن",
      bool(err_msg) and "کندلِ ناقص" in err_msg and "drop_unclosed" in err_msg, str(err_msg))

# با now=None هم باید بفهمد (ساعتِ دیوار): آخرین کندل نیمهٔ دورهٔ جاری است ⇒ ناقص
secs15 = E.tf_seconds("15m")
wall_last = int(time.time()) - (secs15 - 10)          # کلوزش ۱۰ ثانیه در آینده است
wall_bars = mk("15m", 40, wall_last)
err2 = None
try:
    E.analyze_bars(wall_bars, "15m", disp="T", src="test", sym="XAUUSD")
except RuntimeError as ex:
    err2 = str(ex)
check("هستهٔ موتور: با now=None (ساعتِ دیوار) هم کندلِ ناقص را می‌گیرد",
      bool(err2) and "کندلِ ناقص" in err2, str(err2))

r_ok = E.analyze_bars(closed, "15m", disp="T", src="test", sym="XAUUSD", now=T0)
check("هستهٔ موتور: سریِ کاملاً بسته تحلیل می‌شود و forming=False است",
      (r_ok.get("data") or {}).get("forming") is False, str((r_ok.get("data") or {}).get("forming")))
check("هستهٔ موتور: last_price همان کلوزِ آخرین کندلِ بسته است",
      r_ok["last_price"] == closed[-1]["c"], f"گرفته={r_ok['last_price']}")

# مرز: کلوز == now خطا نمی‌دهد (چون بسته است)
edge = mk("15m", 40, T0 - secs15)         # آخرین کندل در ۱۱:۴۵ باز، در ۱۲:۰۰ = T0 بسته
try:
    E.analyze_bars(edge, "15m", disp="T", src="test", sym="XAUUSD", now=T0)
    edge_ok = True
except RuntimeError:
    edge_ok = False
check("هستهٔ موتور: مرزِ دقیق (کلوز == now) خطا نمی‌دهد", edge_ok)

# ═══════════════════════════════════════════════════════════════════
print("═══ ۳) مسیرِ زنده: fetch کندلِ ناقص را می‌اندازد (نقطهٔ گلوگاه) ═══")
secs = E.tf_seconds("15m")
live_last = int(time.time()) - secs // 2         # نیمهٔ دورهٔ جاری ⇒ ناقص
live_forming = mk("15m", 60, live_last)
# فتیله/کلوزِ وحشی روی کندلِ ناقص: اگر به تحلیل برسد، عددها عوض می‌شوند
live_forming[-1] = bar(live_last, 105.0, 999.0, 104.0, 998.0)
expected_closed_close = live_forming[-2]["c"]

_orig_binance = E.fetch_binance


def fake_binance(sym, tf, limit):
    """همان چیزی که صرافیِ زنده برمی‌گرداند — با کندلِ در حالِ تشکیل."""
    return [dict(b) for b in live_forming]


E.fetch_binance = fake_binance
try:
    fetched, e_fetch = safe(E.fetch, "BTCUSDT", "15m", 60)
    check("مسیرِ زنده: fetch بدونِ خطا اجرا می‌شود", e_fetch is None, str(e_fetch))
    bars = fetched[3] if fetched else None
    check("مسیرِ زنده: fetch کندلِ ناقص را می‌اندازد",
          bool(bars) and bars[-1]["t"] + E.tf_seconds("15m") <= int(time.time()),
          f"last_t={bars[-1]['t'] if bars else None}")
    check("مسیرِ زنده: فتیلهٔ وحشیِ کندلِ ناقص هرگز به تحلیل نمی‌رسد",
          bool(bars) and bars[-1]["c"] != 998.0 and bars[-1]["h"] != 999.0,
          f"c={bars[-1]['c'] if bars else None} h={bars[-1]['h'] if bars else None}")
    r_live, e_an = safe(E.analyze, "BTCUSDT", "15m", 60)
    check("مسیرِ زنده: analyze روی دادهٔ بسته بدونِ خطا اجرا می‌شود", e_an is None, str(e_an))
    rl_data = (r_live or {}).get("data") or {}
    check("مسیرِ زنده: analyze روی دادهٔ بسته می‌ماند (forming=False)",
          rl_data.get("forming") is False, str(rl_data.get("forming")))
    check("مسیرِ زنده: آخرین کندلِ تحلیل‌شده همان کندلِ بستهٔ قبلی است",
          rl_data.get("last_bar_ts") == live_forming[-2]["t"],
          f"last_bar_ts={rl_data.get('last_bar_ts')} want={live_forming[-2]['t']}")
    check("مسیرِ زنده: last_price همان کلوزِ کندلِ بسته است (نه عددِ کندلِ ناقص)",
          (r_live or {}).get("last_price") == expected_closed_close,
          f"last_price={(r_live or {}).get('last_price')} want={expected_closed_close}")

    # استثنای آلارم: فقط برای *قیمتِ زنده* کندلِ ناقص لازم است — ولی موتور نباید
    # آن را تحلیل کند.
    fetched_u, e_u = safe(E.fetch, "BTCUSDT", "15m", 60, unclosed=True)
    bars_u = fetched_u[3] if fetched_u else None
    check("مسیرِ زنده: unclosed=True (فقط آلارمِ قیمت) کندلِ جاری را برمی‌گرداند",
          bool(bars_u) and bars_u[-1]["c"] == 998.0,
          f"c={bars_u[-1]['c'] if bars_u else None} err={e_u}")
    refused = False
    try:
        E.analyze_bars(bars_u or live_forming, "15m", disp="T", src="test", sym="BTCUSDT")
    except RuntimeError:
        refused = True
    check("مسیرِ زنده: همان دادهٔ ناقصِ آلارم هم از هستهٔ تحلیل رد نمی‌شود", refused)
finally:
    E.fetch_binance = _orig_binance

# ═══════════════════════════════════════════════════════════════════
print("═══ ۴) گیتِ گریدر: فلگِ forming قفل می‌کند (دفاعِ عمقِ دوم) ═══")
# بلوکِ کمینهٔ ۱۵m که score() می‌خواند — عیناً همان شکلی که analyze_bars می‌سازد.
def fake_block(data_block, price=4300.0):
    return {
        "trend": "up", "CHoCH": ("bullish_CHoCH", 4280.0, 10),
        "BOS": ("bullish_BOS", 4290.0, 12),
        "last_price": price, "bars": 200, "data": data_block,
        "premium_discount": {"range_top": 4400.0, "range_bottom": 4200.0,
                             "zone": "discount", "price_pct": 50.0},
        "liquidity": {"buyside_eqh": [4395.0], "sellside_eql": [4205.0],
                      "range_high": 4400.0, "range_low": 4200.0, "session": {}},
        "liquidity_sweeps": [{"type": "bullish_sweep", "level": 4240.0,
                              "bar_from_end": 2, "idx": 190}],
        "liquidity_patterns": [],
        "displacement": {"present": True, "direction": "bullish",
                         "body_x_avg": 2.1, "bar_from_end": 1},
        "FVG_unfilled": [{"type": "bullish", "top": 4305.0, "bottom": 4292.0, "idx": 195}],
        "order_blocks": [{"type": "bullish", "top": 4298.0, "bottom": 4284.0, "idx": 194}],
        "killzone": "New York AM KZ (08:30-11:00 ET)",
        "sequence_ok": True, "mss_meta": {},
    }


# کنترل: کندلِ بستهٔ تازه (کلوز == now) ⇒ داده تازه و سالم
d_closed = E.freshness_from(T0 - E.tf_seconds("15m"), "15m", "XAUUSD", src="yahoo", now=T0)
r_c = CF.score("XAUUSD", ["15m"], d={"15m": fake_block(d_closed)})
p_c = r_c.get("plan") or {}
row_c = next((c for c in r_c["checklist"] if "تازگیِ داده" in c["name"]), None)
check("گیتِ گریدر: کنترل — دادهٔ بستهٔ تازه قابلِ اجرا است",
      p_c.get("executable_now") is True, j(p_c)[:160])
check("گیتِ گریدر: کنترل — ردیفِ تازگی ✓ است",
      bool(row_c) and row_c.get("status") == "✓", str(row_c))

# همین بلوک، ولی با دادهٔ ناقص (کلوزش در آینده است ⇒ forming=True)
d_forming = E.freshness_from(T0 - 60, "15m", "XAUUSD", src="yahoo", now=T0)
check("گیتِ گریدر: پیش‌فرض — بلوکِ تستِ ناقص واقعاً forming=True است",
      d_forming.get("forming") is True and d_forming.get("state") == "open",
      f"forming={d_forming.get('forming')} state={d_forming.get('state')}")
r_f = CF.score("XAUUSD", ["15m"], d={"15m": fake_block(d_forming)})
p_f = r_f.get("plan") or {}
row_f = next((c for c in r_f["checklist"] if "تازگیِ داده" in c["name"]), None)
check("گیتِ گریدر: forming ⇒ درجه سقف C می‌شود", r_f.get("grade") == "C", str(r_f.get("grade")))
check("گیتِ گریدر: forming ⇒ verdict می‌گوید کندلِ در حالِ تشکیل",
      "کندلِ در حالِ تشکیل" in (r_f.get("verdict") or ""), (r_f.get("verdict") or "")[:120])
check("گیتِ گریدر: forming ⇒ plan.executable_now=False",
      p_f.get("executable_now") is False, j(p_f)[:160])
check("گیتِ گریدر: forming ⇒ blocked_reason پر است (و علتش کندلِ ناقص است)",
      "بسته نشده" in (p_f.get("blocked_reason") or ""), str(p_f.get("blocked_reason")))
check("گیتِ گریدر: forming ⇒ ردیفِ تازگی ✗ و صریح می‌گوید کندل باز است",
      bool(row_f) and row_f.get("status") == "✗"
      and ("هنوز باز" in (row_f.get("detail") or "") or "بسته نشده" in (row_f.get("detail") or "")),
      str(row_f))
es_f = r_f.get("entry_stamp") or {}
check("گیتِ گریدر: forming ⇒ مهرِ ورود صادر نمی‌شود",
      es_f.get("stamped") is False, str(es_f))
check("گیتِ گریدر: forming ⇒ علتِ عدمِ مهر همان کندلِ ناقص است",
      any("بسته نشده" in str(x) for x in (es_f.get("reasons") or [])), str(es_f))
check("گیتِ گریدر: فلگِ forming در خروجی باقی می‌ماند (برای API/رابط)",
      (r_f.get("data") or {}).get("forming") is True, str((r_f.get("data") or {}).get("forming")))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۵) بک‌تست: کندلِ هنوز-باز در لحظهٔ تصمیم نمی‌آید ═══")
series = {"_disp": "XAUUSD",
          "15m": mk("15m", 60, T0),
          "1h": mk("1h", 60, T0),
          "4h": mk("4h", 60, T0)}
t_decision = T0 + E.tf_seconds("15m")      # کلوزِ کندلِ ورود = ۱۲:۱۵
d_bt = BT._build_d(series, ["4h", "1h", "15m"], T0, warm=40)
check("بک‌تست: دیکشنریِ d ساخته شد", isinstance(d_bt, dict) and "15m" in d_bt, str(type(d_bt)))
if isinstance(d_bt, dict):
    h1 = d_bt.get("1h") or {}
    h4 = d_bt.get("4h") or {}
    l15 = d_bt.get("15m") or {}
    check("بک‌تست: هیچ تایم‌فریمی خطا برنگرداند",
          all("error" not in (x or {}) for x in (h1, h4, l15)),
          str([x.get("error") for x in (h1, h4, l15) if isinstance(x, dict)]))
    check("بک‌تست: ۱ساعتهٔ در حالِ تشکیل حذف شد "
          "(آخرین کندلِ تحلیل‌شده کلوزش ≤ لحظهٔ تصمیم است)",
          (h1.get("data") or {}).get("last_bar_ts", 0) + E.tf_seconds("1h") <= t_decision,
          f"last_1h={(h1.get('data') or {}).get('last_bar_ts')} t_decision={t_decision}")
    check("بک‌تست: ۴ساعتهٔ در حالِ تشکیل حذف شد",
          (h4.get("data") or {}).get("last_bar_ts", 0) + E.tf_seconds("4h") <= t_decision,
          f"last_4h={(h4.get('data') or {}).get('last_bar_ts')}")
    check("بک‌تست: کندلِ ورود (۱۵m) روی مرزِ تصمیم بسته است",
          (l15.get("data") or {}).get("last_bar_ts") == T0, str((l15.get("data") or {}).get("last_bar_ts")))
    check("بک‌تست: هیچ تایم‌فریمی forming=True ندارد",
          all((x.get("data") or {}).get("forming") is False for x in (h1, h4, l15)),
          str([(x.get("data") or {}).get("forming") for x in (h1, h4, l15)]))

# ═══════════════════════════════════════════════════════════════════
#  ۶) جهش‌آزمایی: تست باید دندان داشته باشد
# ═══════════════════════════════════════════════════════════════════
ANCHORS = {
    "drop_loop": ("smc_engine.py", 'while cut > 0 and (bars[cut-1].get("t", 0) + secs) > now:'),
    "kernel_guard": ("smc_engine.py", 'if bars[-1]["t"] + _tf_secs > _chk_now:'),
    "grader_gate": ("confluence.py", 'forming_now = bool(ltf_data.get("forming"))'),
    "backtest_drop": ("backtest.py", 'sl, _dropped = EG.drop_unclosed(sl, tf, now=t_decision)'),
    "engine_import": ("smc_engine.py",
                      "import sys, json, urllib.request, urllib.parse, argparse, datetime, math, ssl, time"),
    "conf_import": ("confluence.py", "import sys, os, json, argparse"),
}


def mutate(src, muts):
    """جهش‌ها را اعمال می‌کند؛ هر نشانه‌ای که پیدا نشود → خطای صریح (نه سبزِ بی‌صدا)."""
    out = src
    for needle, repl, count in muts:
        got = out.count(needle)
        if got != count:
            return None, f"نشانهٔ جهش {count} بار انتظار می‌رفت ولی {got} بار بود: {needle[:70]}"
        out = out.replace(needle, repl)
    return out, None


def run_sandbox(target, muts=None):
    """کپیِ موقتِ کلِ ماژول‌ها، اعمالِ جهش روی `target`، اجرا → (کدِ خروج، خروجی)."""
    d = tempfile.mkdtemp(prefix="pf_partial_mut_")
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
        env["PF_PARTIAL_NO_MUT"] = "1"          # جلوگیری از بازگشتِ بی‌پایان
        env.pop("PYTHONPATH", None)
        p = subprocess.run([sys.executable, TEST_NAME], cwd=d, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        return p.returncode, p.stdout.decode("utf-8", errors="replace")
    finally:
        shutil.rmtree(d, ignore_errors=True)


if not os.environ.get("PF_PARTIAL_NO_MUT"):
    print("═══ ۶) جهش‌آزمایی: تست باید دندان داشته باشد ═══")
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
        ("خنثی‌کردنِ drop_unclosed (هیچ‌وقت نمی‌اندازد)", "smc_engine.py",
         [('while cut > 0 and (bars[cut-1].get("t", 0) + secs) > now:',
           "while False:  # PF-MUT", 1)],
         "مسیرِ زنده"),
        ("خطای off-by-one در مرزِ بسته‌شدن (> به >=)", "smc_engine.py",
         [('while cut > 0 and (bars[cut-1].get("t", 0) + secs) > now:',
           'while cut > 0 and (bars[cut-1].get("t", 0) + secs) >= now:', 1)],
         "مرزِ دقیقِ بسته‌شدن"),
        ("خاموش‌کردنِ گیتِ کندلِ ناقص در هستهٔ موتور", "smc_engine.py",
         [('if bars[-1]["t"] + _tf_secs > _chk_now:', "if False:  # PF-MUT", 1)],
         "هستهٔ موتور"),
        ("خاموش‌کردنِ گیتِ گریدر (forming نادیده گرفته شود)", "confluence.py",
         [('forming_now = bool(ltf_data.get("forming"))', "forming_now = False  # PF-MUT", 1)],
         "گیتِ گریدر"),
        ("جاانداختنِ drop_unclosed در بک‌تست", "backtest.py",
         [('sl, _dropped = EG.drop_unclosed(sl, tf, now=t_decision)',
           "sl, _dropped = sl, 0  # PF-MUT", 1)],
         "بک‌تست"),
    ]
    GREEN = [
        ("کامنتِ بی‌گناه در smc_engine", "smc_engine.py",
         [("import sys, json, urllib.request, urllib.parse, argparse, datetime, math, ssl, time",
           "import sys, json, urllib.request, urllib.parse, argparse, datetime, math, ssl, time"
           "  # PF-GREEN", 1)]),
        ("کامنتِ بی‌گناه در confluence", "confluence.py",
         [("import sys, os, json, argparse",
           "import sys, os, json, argparse  # PF-GREEN", 1)]),
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
#  ۷) نگهبانِ هرمتیک: تست نباید به شبکه وابسته باشد
# ═══════════════════════════════════════════════════════════════════
print("═══ ۷) نگهبانِ هرمتیک: هیچ فراخوانِ شبکه‌ای در تست رخ نمی‌دهد ═══")
check("هرمتیک: هیچ کدی در تست به شبکه دست نزد (گاردِ آفلاین دست‌نخورده ماند)",
      not NET_ATTEMPTS, str(NET_ATTEMPTS[:3]))
check("هرمتیک: تقویمِ اقتصادی با پاسخِ ثابت جایگزین شده است (نه شبکه)",
      getattr(CF, "M", None) is _StubCalendar, str(getattr(CF, "M", None)))

NOTES.append("• یافتهٔ جانبیِ هرمتیک: گریدر (`confluence.score`) برای گیتِ اخبارِ کلان "
             "تقویمِ اقتصادی را از اینترنت می‌گرفت (`macro_context.get_calendar`). "
             "زمانِ اجرای این تست به وضعیتِ شبکه گره می‌خورد (روی شبکهٔ کند/قطع، "
             "DNS تا ~۴۰ ثانیه معطل می‌ماند و ۸ اجرای هارنسِ جهش از بودجهٔ CI بیرون "
             "می‌زد). حالا هم گاردِ آفلاین نصب است و هم تقویم پاسخِ ثابتِ GREEN می‌دهد.")

NOTES.append("• یافتهٔ جانبیِ همین تست: فیکسچرِ حالتِ «open» در data_freshness_test.py "
             "کندلی با t=T0−60 می‌ساخت که برای ۱۵m هنوز ناقص است (کلوزش ۱۲:۱۴، نه ۱۲:۰۰) "
             "— یعنی آن تست ناخواسته «پلنِ قابلِ اجرا روی کندلِ ناقص» را تأیید می‌کرد. "
             "گیتِ تازه همان را گرفت و فیکسچر اصلاح شد.")


# ── گزارش ──
for n in NOTES:
    print(n)
print(f"• بررسی‌ها: {len(CHECKS)}")
if FAILS:
    print("")
    for name, detail in FAILS:
        print(f"::error::❌ {name}" + (f" — {detail}" if detail else ""))
    print(f"\n❌ تستِ «کندلِ ناقص» رد شد — {len(FAILS)} از {len(CHECKS)} بررسی شکست خورد")
    sys.exit(1)
print("✅ تستِ «کندلِ ناقص» پاس شد — موتور روی آخرین کندلِ بسته‌نشده سیگنال نمی‌سازد "
      "(نقطهٔ گلوگاهِ drop_unclosed + گیتِ هستهٔ analyze_bars + گیتِ گریدر)")
