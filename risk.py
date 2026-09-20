#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""مدلِ ریسکِ pipfound — سایزِ پوزیشن، سقفِ ضررِ روزانه، و هشدارِ هم‌بستگی.

چرا این ماژول لازم بود: تا پیش از این، پلن فقط «۱:۳» می‌گفت و هیچ‌جا نمی‌گفت
این ستاپ با سرمایه‌ی تو **چند لات/کانترکت/سهم** است. بدونِ سایز، عددِ RR تزئینی
است — دو نفر با سرمایه‌های ۱۰۰۰ و ۱۰۰۰۰۰ دلار یک RR می‌گیرند ولی ریسکِ دلاری‌شان
۱۰۰ برابر فرق دارد. این ماژول همان حلقه‌ی گم‌شده را می‌بندد.

سه چیز می‌دهد (همه **آفلاین و قطعی** — هیچ درخواستِ شبکه‌ای این‌جا نیست):
  ۱) سایزِ پوزیشن: از سرمایه/درصدِ ریسک/فاصله‌ی استاپ → لات یا کانترکت یا سهم.
  ۲) سقفِ ضررِ روزانه: از ردیف‌های بستهٔ **امروزِ** ژورنال → درصدِ ضررِ محقق‌شده،
     باقی‌مانده تا سقف، و ریسکِ بازِ فعلی (مجموعِ ریسکِ معاملاتِ باز).
  ۳) هم‌بستگی: هر نماد به چند «فاکتورِ ریسک» با علامت تجزیه می‌شود (دلار، فلزات،
     شاخصِ آمریکا، نفت، کریپتو، و ارزهای پایه/مظنه). اگر پوزیشن‌های بازِ تو روی
     همان فاکتور با جهتِ یکسان جمع شوند، این معامله ریسکِ تکراری است، نه یک
     معامله‌ی مستقل — و همان چیزی است که «سه شرطِ هم‌جهت روی EUR/GBP/XAU» را
     به یک شرطِ بزرگ روی دلار تبدیل می‌کند.

صداقتِ مدل (مهم): مشخصاتِ قرارداد (اندازه‌ی لات، ارزشِ هر پوینت) در کارگزارهای
مختلف فرق دارد. مقادیرِ پیش‌فرض این‌جا رایج‌ترین‌هاست و هر جا **حدسی** باشد
`approx: True` علامت می‌خورد تا در رابط «تنظیم‌پذیر» دیده شود. برای نمادهایی که
مظنه‌شان دلار نیست (USDJPY، EURJPY، GER40، JP225) یک جدولِ نرخِ تقریبی به کار
می‌رود که با `usd_per_quote` در تنظیمات قابلِ جایگزینی است.

اجرای مستقیم (خودآزمون):
    python3 risk.py --balance 10000 --risk 1 --symbol XAUUSD --entry 4000 --sl 3985
"""
import argparse
import datetime
import json
import math
import os
import sys

HOME = os.path.expanduser("~")

# ── محلِ تنظیمات: بیرونِ Desktop/Documents (جاب‌های launchd اجازه‌ی نوشتن ندارند) ──
def settings_path():
    f = os.environ.get("PIPFOUND_RISK_FILE")
    if f:
        return os.path.expanduser(f)
    return os.path.join(HOME, "pipfound", "risk.json")


# ═══════════════════════════════════════════════════════════════════
#  تنظیمات (قابلِ ذخیره در دیسک)
# ═══════════════════════════════════════════════════════════════════
DEFAULTS = {
    "balance": 10000.0,          # سرمایه‌ی حساب به ارزِ account_ccy
    "account_ccy": "USD",
    "risk_pct": 1.0,             # درصدِ ریسک در هر معامله
    "daily_loss_limit_pct": 3.0,  # سقفِ ضررِ روزانه (درصدِ سرمایه) — عبور از آن = توقفِ روز
    "max_open_risk_pct": 5.0,    # سقفِ مجموعِ ریسکِ معاملاتِ باز
    "usd_per_quote": {},         # بازنویسیِ نرخِ ارزِ مظنه → USD (مثلاً {"JPY": 0.0068})
}

# USD به ازایِ ۱ واحدِ ارزِ مظنه — جدولِ **تقریبیِ** پیش‌فرض. هر نمادی که مظنه‌اش
# USD نباشد با این جدول تبدیل می‌شود و `conversion_assumed` علامت می‌خورد.
USD_PER_QUOTE = {
    "USD": 1.0, "EUR": 1.09, "GBP": 1.27, "JPY": 1 / 150.0, "CHF": 1 / 0.88,
    "CAD": 1 / 1.36, "AUD": 0.66, "NZD": 0.60, "HKD": 0.128,
}

CCY_FA = {
    "USD": "دلار", "EUR": "یورو", "GBP": "پوند", "JPY": "ین", "CHF": "فرانک",
    "CAD": "دلارِ کانادا", "AUD": "دلارِ استرالیا", "NZD": "دلارِ نیوزیلند",
    "HKD": "دلارِ هنگ‌کنگ",
}


def load_settings(path=None):
    """تنظیماتِ ذخیره‌شده را با پیش‌فرض‌ها ادغام می‌کند (کلیدِ گم‌شده = پیش‌فرض)."""
    p = path or settings_path()
    out = dict(DEFAULTS)
    out["usd_per_quote"] = {}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            for k in ("balance", "risk_pct", "daily_loss_limit_pct", "max_open_risk_pct"):
                if d.get(k) is not None:
                    v = _num(d.get(k))
                    if v is not None and v >= 0:
                        out[k] = v
            if d.get("account_ccy"):
                out["account_ccy"] = str(d["account_ccy"]).upper()[:3]
            if isinstance(d.get("usd_per_quote"), dict):
                ov = {}
                for k, v in d["usd_per_quote"].items():
                    f_ = _num(v)
                    if f_ and f_ > 0:
                        ov[str(k).upper()[:3]] = f_
                out["usd_per_quote"] = ov
    except Exception:
        pass
    return out


def save_settings(d, path=None):
    """ذخیره‌ی اتمیک — همان الگوی `os.replace` که بقیه‌ی فایل‌های وضعیتِ اپ دارند."""
    p = path or settings_path()
    dd = os.path.dirname(p)
    if dd and not os.path.exists(dd):
        os.makedirs(dd, exist_ok=True)
    data = {
        "balance": _num(d.get("balance")) if _num(d.get("balance")) is not None
                   else DEFAULTS["balance"],
        "account_ccy": str(d.get("account_ccy") or "USD").upper()[:3],
        "risk_pct": _num(d.get("risk_pct")) if _num(d.get("risk_pct")) is not None
                    else DEFAULTS["risk_pct"],
        "daily_loss_limit_pct": _num(d.get("daily_loss_limit_pct"))
            if _num(d.get("daily_loss_limit_pct")) is not None else DEFAULTS["daily_loss_limit_pct"],
        "max_open_risk_pct": _num(d.get("max_open_risk_pct"))
            if _num(d.get("max_open_risk_pct")) is not None else DEFAULTS["max_open_risk_pct"],
        "usd_per_quote": {str(k).upper()[:3]: float(v)
                          for k, v in (d.get("usd_per_quote") or {}).items()
                          if _num(v) and _num(v) > 0},
        "updated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return data


# ═══════════════════════════════════════════════════════════════════
#  مشخصاتِ نماد
# ═══════════════════════════════════════════════════════════════════
# kind → (برچسبِ واحد، برچسبِ فارسی)
_KIND_UNIT = {
    "fx": ("lot", "لات"), "metal": ("lot", "لات"), "energy": ("lot", "لات"),
    "index": ("ctr", "کانترکت"), "stock": ("sh", "سهم"), "crypto": ("unit", "واحد"),
}

# نمادهای با مشخصاتِ صریح: نماد → (نوع، اندازه‌ی قرارداد، ارزِ مظنه، پوینت، حدسی؟، یادداشت)
_EXPLICIT = {
    # فلزات — طلا ۱۰۰ اونس در لات، نقره ۵۰۰۰ اونس (رایج‌ترین قراردادِ اسپات)
    "XAUUSD": ("metal", 100.0, "USD", 0.01, False, ""),
    "XAGUSD": ("metal", 5000.0, "USD", 0.001, False, ""),
    "XPTUSD": ("metal", 50.0, "USD", 0.01, True, "پلاتین — اندازه‌ی قرارداد به کارگزار بستگی دارد"),
    "XPDUSD": ("metal", 100.0, "USD", 0.01, True, "پالادیوم — اندازه‌ی قرارداد به کارگزار بستگی دارد"),
    # انرژی و کامودیتی (فیوچرزِ رایج)
    "WTI": ("energy", 1000.0, "USD", 0.01, True, "۱ قرارداد = ۱۰۰۰ بشکه"),
    "BRENT": ("energy", 1000.0, "USD", 0.01, True, "۱ قرارداد = ۱۰۰۰ بشکه"),
    "NATGAS": ("energy", 10000.0, "USD", 0.001, True, "۱ قرارداد = ۱۰٬۰۰۰ میلیون‌بی‌تی‌یو"),
    "COPPER": ("energy", 25000.0, "USD", 0.0005, True, "۱ قرارداد = ۲۵٬۰۰۰ پوند"),
    "COCOA": ("energy", 10.0, "USD", 1.0, True, "۱ قرارداد = ۱۰ تن"),
    "COFFEE": ("energy", 37500.0, "USD", 0.0005, True, "۱ قرارداد = ۳۷٬۵۰۰ پوند"),
    "SUGAR": ("energy", 112000.0, "USD", 0.0001, True, "۱ قرارداد = ۱۱۲٬۰۰۰ پوند"),
    "WHEAT": ("energy", 5000.0, "USD", 0.0025, True, "۱ قرارداد = ۵٬۰۰۰ بوشل"),
    "CORN": ("energy", 5000.0, "USD", 0.0025, True, "۱ قرارداد = ۵٬۰۰۰ بوشل"),
    # اندیکس‌ها — فرضِ رایجِ CFD: ۱ کانترکت = ۱ دلار به ازایِ هر پوینت
    "SPX500": ("index", 1.0, "USD", 0.1, True, "۱ کانترکت = ۱ دلار/پوینت (CFD)"),
    "NAS100": ("index", 1.0, "USD", 0.1, True, "۱ کانترکت = ۱ دلار/پوینت (CFD)"),
    "US30": ("index", 1.0, "USD", 0.1, True, "۱ کانترکت = ۱ دلار/پوینت (CFD)"),
    "GER40": ("index", 1.0, "EUR", 0.1, True, "۱ کانترکت = ۱ یورو/پوینت (CFD)"),
    "UK100": ("index", 1.0, "GBP", 0.1, True, "۱ کانترکت = ۱ پوند/پوینت (CFD)"),
    "JP225": ("index", 1.0, "JPY", 1.0, True, "۱ کانترکت = ۱ ین/پوینت (CFD)"),
    "HK50": ("index", 1.0, "HKD", 1.0, True, "۱ کانترکت = ۱ دلارِ هنگ‌کنگ/پوینت"),
    "RUT": ("index", 1.0, "USD", 0.1, True, "۱ کانترکت = ۱ دلار/پوینت (CFD)"),
    "VIX": ("index", 1.0, "USD", 0.01, True, "۱ کانترکت = ۱ دلار/پوینت (CFD)"),
    "DXY": ("index", 1.0, "USD", 0.01, True, "ایندکسِ دلار — کانترکت به کارگزار بستگی دارد"),
}

# نام‌های جایگزینِ فلزات (همان‌هایی که موتور هم می‌شناسد)
_ALIAS = {
    "GOLD": "XAUUSD", "XAU": "XAUUSD",
    "SILVER": "XAGUSD", "XAG": "XAGUSD",
    "PLATINUM": "XPTUSD", "XPT": "XPTUSD",
    "PALLADIUM": "XPDUSD", "XPD": "XPDUSD",
    "USOIL": "WTI", "CRUDE": "WTI", "CL": "WTI", "UKOIL": "BRENT",
    "SP500": "SPX500", "US500": "SPX500", "SPX": "SPX500",
    "US100": "NAS100", "USTEC": "NAS100", "NDX": "NAS100",
    "DOW30": "US30", "DOW": "US30", "WS30": "US30",
    "DE40": "GER40", "DAX": "GER40", "FTSE": "UK100", "NIKKEI": "JP225",
    "USDX": "DXY", "DX": "DXY", "NATURALGAS": "NATGAS",
}

_FX_CCY = {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"}
_CRYPTO_QUOTE = ("USDT", "USDC", "BUSD")


def instrument(symbol):
    """مشخصاتِ قراردادِ یک نماد؛ `None` اگر ناشناخته باشد (سایز محاسبه نمی‌شود).

    ترتیب: نامِ جایگزین → جدولِ صریح → کریپتو (پسوندِ استیبل) → جفت‌ارزِ ۶ حرفی →
    سهامِ ۱–۵ حرفی. همان قاعده‌ی موتور، پس دو جای مختلف دو جوابِ متفاوت نمی‌دهد.
    """
    s = (symbol or "").upper().replace("/", "").replace("-", "").strip()
    if not s:
        return None
    s = _ALIAS.get(s, s)
    if s in _EXPLICIT:
        kind, contract, quote, point, approx, note = _EXPLICIT[s]
        unit, unit_fa = _KIND_UNIT[kind]
        return {"symbol": s, "kind": kind, "contract": contract, "quote": quote,
                "point": point, "unit": unit, "unit_fa": unit_fa,
                "approx": approx, "note": note}
    # کریپتو: BTCUSDT، ETHUSDT، …
    for q in _CRYPTO_QUOTE:
        if s.endswith(q) and len(s) > len(q):
            return {"symbol": s, "kind": "crypto", "contract": 1.0, "quote": "USD",
                    "point": 0.01, "unit": "unit", "unit_fa": "واحد",
                    "approx": False, "note": "قرارداد = ۱ واحد از دارایی"}
    if s.endswith(("BTC", "ETH")) and len(s) > 6:      # مثلاً BTCPERP
        return {"symbol": s, "kind": "crypto", "contract": 1.0, "quote": "USD",
                "point": 0.01, "unit": "unit", "unit_fa": "واحد",
                "approx": False, "note": "قرارداد = ۱ واحد از دارایی"}
    # جفت‌ارزِ ۶ حرفی با هر دو طرفِ شناخته‌شده — قاعده‌ی عمومی (EURJPY، AUDJPY، …)
    if len(s) == 6 and s.isalpha() and s[:3] in _FX_CCY and s[3:] in _FX_CCY:
        quote = s[3:]
        point = 0.01 if quote == "JPY" else 0.0001
        return {"symbol": s, "kind": "fx", "contract": 100000.0, "quote": quote,
                "point": point, "unit": "lot", "unit_fa": "لات",
                "approx": False, "note": "۱ لات = ۱۰۰٬۰۰۰ واحدِ ارزِ پایه"}
    # سهام (قاعده‌ی موتور: ۱ تا ۵ حرفِ لاتین)
    if 1 <= len(s) <= 5 and s.isalpha():
        return {"symbol": s, "kind": "stock", "contract": 1.0, "quote": "USD",
                "point": 0.01, "unit": "sh", "unit_fa": "سهم",
                "approx": True, "note": "به فرضِ سهمِ دلاری — ۱ سهم"}
    return None


# ═══════════════════════════════════════════════════════════════════
#  سایزِ پوزیشن
# ═══════════════════════════════════════════════════════════════════
def _num(x):
    """عدد از هر چیزی که در JSON/CSV ممکن است بیاید؛ ناکارآمد → None (نه صفرِ خاموش)."""
    if x is None or x == "":
        return None
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        try:
            f = float(x)
        except Exception:
            return None
        return None if f != f else f          # NaN را رد کن
    s = str(x).strip().replace(",", "").replace("٬", "")
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def dir_sign(direction):
    """جهت → +۱ خرید / -۱ فروش / ۰ نامشخص (هم فارسیِ گریدر، هم long/short)."""
    t = str(direction or "").strip().lower()
    if "صعود" in t or "خرید" in t or t in ("long", "buy", "up", "bull"):
        return 1
    if "نزول" in t or "فروش" in t or t in ("short", "sell", "down", "bear"):
        return -1
    return 0


def _usd_per_quote(ccy, settings):
    """نرخِ تبدیل به USD: بازنویسیِ کاربر → جدولِ پیش‌فرض. `(rate, assumed)`.

    USD هیچ‌وقت «حدسی» نیست (نرخش دقیقاً ۱ است) — وگرنه هر نمادِ دلاری هم برچسبِ
    تقریبی می‌خورد و برچسب بی‌معنا می‌شد.
    """
    c = str(ccy or "USD").upper()
    if c == "USD":
        return 1.0, False
    ov = (settings or {}).get("usd_per_quote") or {}
    if c in ov:
        return float(ov[c]), False
    return float(USD_PER_QUOTE.get(c, 1.0)), True


def size_for(symbol, plan, settings):
    """سایزِ پوزیشنِ لازم برای اینکه فاصله‌ی استاپ = درصدِ ریسکِ تعیین‌شده باشد.

    فرمول (بدونِ ابداع): ریسکِ هر لات = فاصله‌ی استاپ × اندازه‌ی قرارداد × نرخِ مظنه
    (تبدیل به ارزِ حساب). سایز = (سرمایه × درصدِ ریسک) ÷ ریسکِ هر لات.
    """
    out = {"ok": False, "reason": "", "approx": False, "notes": []}
    spec = instrument(symbol)
    if spec is None:
        out["reason"] = f"مشخصاتِ قراردادِ «{symbol}» را نمی‌شناسم — سایز محاسبه نشد"
        return out
    if not plan:
        out["reason"] = "پلنی برای سایزکردن نیست"
        return out
    entry = _num(plan.get("entry"))
    sl = _num(plan.get("sl"))
    if entry is None or sl is None:
        out["reason"] = "ورود یا استاپ در پلن نیست"
        return out
    stop = abs(entry - sl)
    if stop <= 0:
        out["reason"] = "فاصله‌ی استاپ صفر است (ورود = استاپ)"
        return out

    st = settings or DEFAULTS
    balance = _num(st.get("balance")) or 0.0
    risk_pct = _num(st.get("risk_pct"))
    risk_pct = DEFAULTS["risk_pct"] if risk_pct is None else risk_pct
    if balance <= 0:
        out["reason"] = "سرمایه تنظیم نشده — سرمایه را در پنلِ ریسک وارد کن"
        return out
    if risk_pct <= 0:
        out["reason"] = "درصدِ ریسک صفر است — معامله‌ای مجاز نیست"
        return out

    acc = str(st.get("account_ccy") or "USD").upper()
    q_rate, q_assumed = _usd_per_quote(spec["quote"], st)
    a_rate, a_assumed = _usd_per_quote(acc, st)

    risk_amount = balance * risk_pct / 100.0
    # ارزشِ حرکتِ یک واحدِ قیمت برای یک قرارداد، به ارزِ حساب
    value_per_unit = spec["contract"] * q_rate / a_rate
    risk_per_lot = stop * value_per_unit
    lots_raw = risk_amount / risk_per_lot

    # کوچک‌ترین پله‌ی قابلِ معامله به تفکیک نوع (لات/کانترکت ۰.۰۱ · سهم ۱ · کریپتو ۰.۰۰۰۰۰۱)
    step = 1.0 if spec["kind"] == "stock" else (1e-6 if spec["kind"] == "crypto" else 0.01)
    over_risk = False
    # **به کفِ پله** گرد می‌شود، نه به نزدیک‌ترین: قاعده‌ی مدیریتِ ریسک این است که
    # هرگز از ریسکِ برنامه‌ریزی‌شده بیشتر نشود. گردکردن به نزدیک‌ترین می‌تواند
    # مثلاً ۱۰۹ دلار ریسک روی یک سقفِ ۱۰۰ دلاری بگذارد.
    steps = math.floor(lots_raw / step + 1e-9)
    if steps >= 1:
        size_lots = round(steps * step, 8)
    elif lots_raw > 0:
        # ریسکِ هدف از کوچک‌ترین پله هم کمتر است: یا معامله‌ی حداقلی (با ریسکِ
        # بیشتر از هدف، اعلام‌شده) یا هیچ. صفر دادن اشتباه است چون اپ فقط حدس
        # می‌زند — عدد را می‌دهد و هشدار می‌دهد.
        size_lots = step
        over_risk = True
    else:
        size_lots = 0.0
    if size_lots <= 0:
        out["reason"] = "سایزِ مجاز صفر می‌شود — سرمایه/درصدِ ریسک را بررسی کن"
        return out

    size_disp = (int(size_lots) if spec["kind"] == "stock"
                 else (round(size_lots, 6) if spec["kind"] == "crypto"
                       else round(size_lots, 2)))
    actual_risk = size_lots * risk_per_lot
    rr = _num(plan.get("rr")) or 0.0
    out.update({
        "ok": True,
        "symbol": spec["symbol"],
        "kind": spec["kind"],
        "unit_fa": spec["unit_fa"],
        "size": size_disp,
        "size_lots": size_lots,
        "size_units": size_lots * spec["contract"],
        "balance": balance,
        "account_ccy": acc,
        "risk_pct": risk_pct,
        "risk_amount": round(risk_amount, 2),
        "actual_risk_amount": round(actual_risk, 2),
        "reward_amount": round(actual_risk * rr, 2) if rr else None,
        "stop_distance": round(stop, 6),
        "stop_pips": round(stop / spec["point"], 1) if spec["point"] else None,
        "point": spec["point"],
        "value_per_point": round(spec["point"] * value_per_unit, 4),
        "risk_per_lot": round(risk_per_lot, 2),
        "contract": spec["contract"],
        "quote": spec["quote"],
        "approx": bool(spec["approx"] or q_assumed or a_assumed),
        "over_risk": over_risk,
        "notes": list(out["notes"]),
    })
    if over_risk:
        out["notes"].append(
            f"کوچک‌ترین سایزِ قابلِ معامله ({size_disp} {spec['unit_fa']}) از ریسکِ هدفِ "
            f"تو بزرگ‌تر است ({round(actual_risk, 2)} به‌جای {round(risk_amount, 2)}) — "
            f"یا سرمایه/درصد را کم کن یا از این ستاپ بگذر")
    elif size_lots * risk_per_lot < risk_amount - 1e-6:
        out["notes"].append(
            f"به کفِ پله گرد شد تا از ریسکِ هدف بیشتر نشود "
            f"({round(actual_risk, 2)} از {round(risk_amount, 2)})")
    if spec["note"]:
        out["notes"].append(spec["note"])
    if q_assumed and spec["quote"] != "USD":
        out["notes"].append(
            f"نرخِ تبدیلِ {spec['quote']}→USD تقریبی است "
            f"({CCY_FA.get(spec['quote'], spec['quote'])} مظنه‌ی این نماد است) — "
            f"برای سایزِ دقیق در تنظیماتِ ریسک نرخش را وارد کن")
    return out


# ═══════════════════════════════════════════════════════════════════
#  سقفِ ضررِ روزانه + ریسکِ باز
# ═══════════════════════════════════════════════════════════════════
def _row_realized_r(r):
    """R محقق‌شدهٔ یک ردیفِ بسته — اگر ستونش خالی بود، از نتیجه‌اش استنتاج می‌شود.

    قرارداد: win → +rr ، loss → -۱ ، be → ۰. اگر `rr` هم نبود، +۱ فرض می‌شود
    (کوچک‌ترین بردِ معنادار). هیچ‌وقت ۰ برنمی‌گرداند تا معامله‌ی بسته بی‌اثر نشود.
    """
    v = _num(r.get("realized_r"))
    if v is not None:
        return v
    res = str(r.get("result") or "").strip().lower()
    rr = _num(r.get("rr"))
    if res in ("win", "برد", "سود"):
        return rr if rr and rr > 0 else 1.0
    if res in ("loss", "باخت", "ضرر"):
        return -1.0
    if res in ("be", "breakeven", "سربه‌سر"):
        return 0.0
    return 0.0


def daily_state(rows, settings, now=None):
    """وضعیتِ ضررِ **امروز** + ریسکِ بازِ فعلی، از ردیف‌های ژورنال.

    یک فرضِ صریح: ردیف‌هایی که ستونِ `risk_pct`شان خالی است با **درصدِ ریسکِ
    فعلیِ تنظیمات** حساب می‌شوند (نه با صفر و نه با یکِ ثابت). نتیجه‌اش این است
    که تغییرِ درصدِ ریسک، عددِ «ریسکِ باز» را هم بازمحاسبه می‌کند — چون بهترین
    حدسِ موجود از قصدِ کاربر همان عدد است. برای معامله‌ای که درصدش را صریح
    ثبت کرده باشی، همان مقدارِ ثبت‌شده ملاک است.
    """
    st = settings or DEFAULTS
    now = now or datetime.datetime.now()
    today = now.strftime("%Y-%m-%d")
    balance = _num(st.get("balance")) or 0.0
    base_risk = _num(st.get("risk_pct"))
    base_risk = DEFAULTS["risk_pct"] if base_risk is None else base_risk
    limit_pct = _num(st.get("daily_loss_limit_pct"))
    limit_pct = DEFAULTS["daily_loss_limit_pct"] if limit_pct is None else limit_pct
    open_limit = _num(st.get("max_open_risk_pct"))
    open_limit = DEFAULTS["max_open_risk_pct"] if open_limit is None else open_limit

    realized_r = 0.0
    pnl = 0.0
    closed_n = 0
    for r in (rows or []):
        if str(r.get("status") or "").strip().lower() != "closed":
            continue
        if str(r.get("datetime") or "")[:10] != today:
            continue
        rp = _num(r.get("risk_pct"))
        rp = base_risk if rp is None else rp
        r_ = _row_realized_r(r)
        realized_r += r_
        pnl += r_ * balance * rp / 100.0
        closed_n += 1

    open_n = 0
    open_risk_pct = 0.0
    open_symbols = []
    for r in (rows or []):
        if str(r.get("status") or "").strip().lower() != "open":
            continue
        rp = _num(r.get("risk_pct"))
        rp = base_risk if rp is None else rp
        open_risk_pct += rp
        open_n += 1
        if r.get("symbol"):
            open_symbols.append({
                "symbol": str(r["symbol"]).upper(),
                "direction": r.get("direction") or "",
                "sign": dir_sign(r.get("direction")),
                "risk_pct": rp,
            })

    realized_pct = (pnl / balance * 100.0) if balance > 0 else 0.0
    limit_amount = balance * limit_pct / 100.0
    remaining = max(0.0, (-realized_pct) - limit_pct) if limit_pct > 0 else None
    remaining_pct = max(0.0, limit_pct + realized_pct) if limit_pct > 0 else None
    return {
        "date": today,
        "balance": balance,
        "limit_pct": limit_pct,
        "limit_amount": round(limit_amount, 2),
        "realized_r": round(realized_r, 2),
        "realized_pct": round(realized_pct, 2),
        "realized_amount": round(pnl, 2),
        "closed_today": closed_n,
        "remaining_pct": round(remaining_pct, 2) if remaining_pct is not None else None,
        "remaining_amount": (round(max(0.0, limit_amount + pnl), 2)
                             if limit_pct > 0 else None),
        "breached": bool(limit_pct > 0 and (-realized_pct) >= limit_pct),
        "open_count": open_n,
        "open_risk_pct": round(open_risk_pct, 2),
        "open_risk_limit_pct": open_limit,
        "open_breached": bool(open_limit > 0 and open_risk_pct >= open_limit),
        "open_risk_amount": round(balance * open_risk_pct / 100.0, 2),
        "open_positions": open_symbols,
    }


# ═══════════════════════════════════════════════════════════════════
#  مدلِ هم‌بستگی (فاکتورهای ریسک)
# ═══════════════════════════════════════════════════════════════════
# برچسبِ فارسیِ فاکتور → همان چیزی که در هشدار به کاربر گفته می‌شود
FACTOR_FA = {
    "USD": "دلار", "METALS": "فلزات", "XAU": "طلا", "XAG": "نقره",
    "OIL": "نفت", "ENERGY": "انرژی", "CRYPTO": "کریپتو",
    "EQ:US": "شاخص/سهامِ آمریکا", "EQ:EU": "شاخصِ آلمان", "EQ:UK": "شاخصِ انگلیس",
    "EQ:JP": "شاخصِ ژاپن", "EQ:HK": "شاخصِ هنگ‌کنگ", "DXY": "ایندکسِ دلار",
}

_EQ_FACTOR = {
    "SPX500": "EQ:US", "NAS100": "EQ:US", "US30": "EQ:US", "RUT": "EQ:US",
    "VIX": "EQ:US", "GER40": "EQ:EU", "UK100": "EQ:UK", "JP225": "EQ:JP",
    "HK50": "EQ:HK",
}


def exposures(symbol, sign):
    """نماد + جهت → فاکتورهای ریسک با علامت. مدلِ شفاف و قطعی (بدونِ شبکه).

    مثال‌ها: خریدِ XAUUSD = ‎USD: -۱، METALS/XAU: +۱ (طلا معکوسِ دلار است).
    خریدِ NAS100 = ‎EQ:US: +۱. خریدِ EURUSD = ‎FX:EUR: +۱، FX:USD: -۱، USD: -۱.
    خریدِ USDJPY = ‎USD: +۱، FX:JPY: -۱. همین‌طور خریدِ سهام = سهمِ خودش + EQ:US.
    """
    if sign not in (1, -1):
        return {}
    spec = instrument(symbol)
    if spec is None:
        return {}
    s = spec["symbol"]
    f = {}
    if spec["kind"] == "fx":
        # ارزِ پایه با علامتِ جهت، ارزِ مظنه برعکس. **USD یک نامِ واحد دارد** تا
        # خریدِ EURUSD + خریدِ GBPUSD یک هشدارِ «دلاری» بدهد، نه دو هشدارِ تکراری.
        base, quote = s[:3], s[3:]
        for ccy, sgn in ((base, sign), (quote, -sign)):
            key = "USD" if ccy == "USD" else f"CCY:{ccy}"
            f[key] = f.get(key, 0) + sgn
    elif spec["kind"] == "metal":
        # فقط «فلزات» کافی است — فاکتورِ خودِ نماد (XAU/XAG) همان را دو بار
        # می‌گفت و یک معامله‌ی تکراری سه سطرِ هشدار می‌ساخت.
        f["METALS"] = f.get("METALS", 0) + sign
        f["USD"] = f.get("USD", 0) - sign          # فلزات دلاری = معکوسِ دلار
    elif spec["kind"] == "energy":
        f["ENERGY"] = f.get("ENERGY", 0) + sign
        if s in ("WTI", "BRENT"):
            f["OIL"] = f.get("OIL", 0) + sign
    elif spec["kind"] == "index":
        if s == "DXY":
            f["USD"] = f.get("USD", 0) + sign
            f["DXY"] = f.get("DXY", 0) + sign
        else:
            k = _EQ_FACTOR.get(s, "EQ:US")
            f[k] = f.get(k, 0) + sign
    elif spec["kind"] == "stock":
        f["EQ:US"] = f.get("EQ:US", 0) + sign
        f[f"STK:{s}"] = f.get("STK:" + s, 0) + sign
    elif spec["kind"] == "crypto":
        base = s
        for q in ("USDT", "USDC", "BUSD"):
            if base.endswith(q):
                base = base[: -len(q)]
                break
        f["CRYPTO"] = f.get("CRYPTO", 0) + sign
        f["CRYPTO:" + base] = f.get("CRYPTO:" + base, 0) + sign
    return {k: v for k, v in f.items() if v}


def _factor_label(k):
    if k in FACTOR_FA:
        return FACTOR_FA[k]
    if k.startswith("CCY:"):
        c = k[4:]
        return f"{CCY_FA.get(c, c)} (ارز)"
    if k.startswith("STK:"):
        return f"سهامِ {k[4:]}"
    if k.startswith("CRYPTO:"):
        return f"کریپتو {k[7:]}"
    return k


def correlation(symbol, sign, open_positions):
    """هشدارِ تمرکز/هم‌بستگی: آیا این معامله با پوزیشن‌های باز روی یک فاکتور جمع می‌شود؟

    «هم‌جهت روی یک فاکتور» یعنی ریسکِ تکراری، نه دو معامله‌ی مستقل. مثالِ واقعیِ
    همان اشتباه: خریدِ هم‌زمانِ EURUSD و GBPUSD و XAUUSD — سه ورودی، یک شرط روی دلار.
    """
    cand = exposures(symbol, sign)
    net = dict(cand)
    for p in (open_positions or []):
        ps = p.get("sign") if isinstance(p, dict) else None
        psy = p.get("symbol") if isinstance(p, dict) else None
        if ps in (1, -1) and psy:
            for k, v in exposures(psy, ps).items():
                net[k] = net.get(k, 0) + v
    stacked = {k: v for k, v in net.items() if abs(v) >= 2}
    ordered = sorted(stacked.items(), key=lambda kv: -abs(kv[1]))
    mine, pre = [], []
    for k, v in ordered:
        lbl = _factor_label(k)
        # جهت را از سهمِ **خودِ این معامله** روی همان فاکتور می‌سنجیم، نه از جهتِ
        # نماد: طلا در فاکتورِ دلار منفی است، پس مقایسه با جهتِ نماد گمراه می‌شد.
        own = cand.get(k, 0)
        if own:
            same = "هم‌راستا" if (own > 0) == (v > 0) else "در جهتِ مخالف"
            mine.append((lbl, v, same))
        else:
            # این معامله به این فاکتور دست نمی‌زند؛ تمرکز از خودِ پوزیشن‌های باز است.
            # جدا گزارش می‌شود تا به‌اشتباه به این ستاپ نسبت داده نشود.
            pre.append((lbl, v))
    # یک معاملهٔ تکراری (مثلِ طلا) هم روی «فلزات» و هم روی «دلار» جمع می‌شود؛
    # دو موردِ نخست را می‌گوییم و بقیه را در یک سطر جمع می‌کنیم تا بنر خوانا بماند.
    trade_msgs = []
    for lbl, v, same in mine[:2]:
        trade_msgs.append(
            f"هشدارِ هم‌بستگی: این معامله در فاکتورِ «{lbl}» {same} با پوزیشن‌های "
            f"بازِ تو جمع می‌شود (خالصِ فاکتور {v:+d}) — ریسکِ تکراری است، "
            f"نه یک معامله‌ی مستقل")
    if len(mine) > 2:
        extra = "، ".join(f"{lbl} {v:+d}" for lbl, v, _ in mine[2:])
        trade_msgs.append(
            f"و در {len(mine) - 2} فاکتورِ دیگر هم همین تمرکز تکرار می‌شود ({extra})")
    conc = [f"توجه: پوزیشن‌های بازِ تو خودشان روی «{lbl}» تمرکز دارند "
            f"(خالصِ فاکتور {v:+d}) — پیش از ورودِ بعدی این تمرکز را در نظر بگیر"
            for lbl, v in pre[:2]]
    return {
        # `warnings` همان چیزی است که رابط نشان می‌دهد: اول هشدارِ همین معامله،
        # بعد تمرکزِ موجود در پوزیشن‌های باز.
        "warnings": trade_msgs + conc,
        "trade_warnings": trade_msgs,
        "open_concentration": conc,
        "stacked": {k: v for k, v in stacked.items()},
        "net": {k: v for k, v in net.items() if v},
        "candidate_exposures": cand,
        "open_count": len([p for p in (open_positions or []) if isinstance(p, dict)]),
    }


# ═══════════════════════════════════════════════════════════════════
#  بلوکِ نهایی برای API/رابط
# ═══════════════════════════════════════════════════════════════════
def evaluate(symbol, plan, settings, rows, now=None):
    """همه‌ی ریسک در یک دیکشنری — همان چیزی که `/api/analyze` و رابط می‌خوانند.

    `blocked` یعنی معامله‌ی **امروز** دیگر مجاز نیست (سقفِ ضرر پر شده) یا مجموعِ
    ریسکِ باز از سقف گذشته. در آن حالت لایه‌ی بالاتر (`app.analyze`) درجه را سقف
    می‌زند و مهرِ ورود صادر نمی‌شود — همان الگوی «گیتِ صداقت» که برای بازارِ بسته
    به کار رفت، نه یک قضاوتِ جدید.
    """
    st = settings or DEFAULTS
    day = daily_state(rows, st, now=now)
    sign = dir_sign((plan or {}).get("direction"))
    size = size_for(symbol, plan, st) if plan else {
        "ok": False, "reason": "پلنی برای سایزکردن نیست", "approx": False, "notes": []}
    corr = correlation(symbol, sign, day.get("open_positions")) if sign else {
        "warnings": [], "open_concentration": [], "stacked": {}, "net": {},
        "candidate_exposures": {}, "open_count": 0}

    blocked = False
    reasons = []
    if day["breached"]:
        blocked = True
        reasons.append(
            f"سقفِ ضررِ روزانه پر شده است: امروز {day['realized_pct']}٪ "
            f"(سقف {day['limit_pct']}٪ ≈ {day['limit_amount']}) — امروز معامله‌ی جدید نکن")
    if day["open_breached"]:
        blocked = True
        reasons.append(
            f"مجموعِ ریسکِ معاملاتِ باز ({day['open_risk_pct']}٪) از سقفِ "
            f"{day['open_risk_limit_pct']}٪ گذشته — اول یکی از پوزیشن‌های باز را ببند")

    return {
        "settings": {
            "balance": st.get("balance"),
            "account_ccy": st.get("account_ccy"),
            "risk_pct": st.get("risk_pct"),
            "daily_loss_limit_pct": st.get("daily_loss_limit_pct"),
            "max_open_risk_pct": st.get("max_open_risk_pct"),
        },
        "size": size,
        "daily": day,
        "correlation": corr,
        "blocked": blocked,
        "block_reason": " · ".join(reasons) if reasons else None,
        # ترتیبِ نمایش: اول هشدارِ هم‌بستگیِ همین معامله، بعد تمرکزِ موجود در
        # پوزیشن‌های باز (همین حالا داخلِ `corr["warnings"]` چیده شده‌اند)، و
        # آخر محدودیتِ سخت (سقفِ روزانه) — بدونِ تکرار.
        "warnings": list(corr["warnings"]) + reasons,
        "trade_warnings": list(corr.get("trade_warnings") or []),
    }


# ═══════════════════════════════════════════════════════════════════
#  اجرای مستقیم — خودآزمونِ سریع در ترمینال
# ═══════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="محاسبه‌ی سایزِ پوزیشن و وضعیتِ ریسک")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--entry", type=float, required=True)
    ap.add_argument("--sl", type=float, required=True)
    ap.add_argument("--rr", type=float, default=3.0)
    ap.add_argument("--direction", default="long")
    ap.add_argument("--balance", type=float, default=None)
    ap.add_argument("--risk", type=float, default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    st = load_settings()
    if a.balance is not None:
        st["balance"] = a.balance
    if a.risk is not None:
        st["risk_pct"] = a.risk
    plan = {"entry": a.entry, "sl": a.sl, "rr": a.rr, "direction": a.direction}
    sz = size_for(a.symbol, plan, st)
    if a.json:
        print(json.dumps(sz, ensure_ascii=False, indent=2))
        return 0 if sz.get("ok") else 1
    if not sz.get("ok"):
        print("✗ " + sz.get("reason", ""))
        return 1
    print(f"✅ {sz['symbol']} — {sz['size']} {sz['unit_fa']} "
          f"(ریسک {sz['actual_risk_amount']} {sz['account_ccy']} · "
          f"استاپ {sz['stop_pips']} پوینت · ارزشِ هر پوینت {sz['value_per_point']})")
    for n in sz.get("notes") or []:
        print("   ℹ " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
