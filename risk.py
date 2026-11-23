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
from decimal import Decimal, DecimalException, localcontext, ROUND_FLOOR
import json
import math
import os
import re
import sys
from typing import Any

from autobackup import _write_json

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
DEFAULTS: dict[str, Any] = {
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


MAX_SETTINGS_ERRORS = 12
MAX_RATES = 256
_NUM_SETTINGS = ("balance", "risk_pct", "daily_loss_limit_pct", "max_open_risk_pct")
# Three finite-float factors can span roughly 1900 decimal places. This also
# prevents a large profit/loss cancellation from erasing a small booked loss.
_DECIMAL_PRECISION = 2048


def _currency(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z]{3}", value) is None:
        return None
    return value.upper()


def _normalized_settings(d) -> tuple[dict[str, Any], list[str]]:
    """Defaults for missing fields; diagnostics, not silent permission, for bad ones."""
    out: dict[str, Any] = dict(DEFAULTS, usd_per_quote={})
    errors = []
    if d is None:
        return out, errors
    if not isinstance(d, dict):
        return out, ["تنظیماتِ ریسک باید شیء باشد"]
    inherited = d.get("validation_errors")
    if inherited:
        if (isinstance(inherited, list) and len(inherited) <= MAX_SETTINGS_ERRORS + 1
                and all(isinstance(e, str) and len(e) <= 1024 for e in inherited)):
            errors.extend(inherited)
        else:
            errors.append("وضعیتِ اعتبارِ تنظیماتِ ریسک خراب است")
    for k in _NUM_SETTINGS:
        if k in d:
            v = _num(d[k])
            if v is None or v < 0:
                errors.append(f"مقدارِ {k} باید عددِ متناهیِ نامنفی باشد")
            else:
                out[k] = v
    if "account_ccy" in d:
        c = _currency(d["account_ccy"])
        if c is None:
            errors.append("ارزِ حساب (account_ccy) باید کدِ سه‌حرفیِ معتبر باشد")
        else:
            out["account_ccy"] = c
    if "usd_per_quote" in d:
        rates = d["usd_per_quote"]
        if not isinstance(rates, dict) or len(rates) > MAX_RATES:
            errors.append("نرخ‌های usd_per_quote باید نگاشتِ محدودِ ارز به عددِ مثبت باشند")
        else:
            for raw, value in rates.items():
                c, rate = _currency(raw), _num(value)
                if c is None or rate is None or rate <= 0 or (c == "USD" and rate != 1):
                    errors.append("کد/نرخِ usd_per_quote نامعتبر است؛ نرخِ دلار باید ۱ باشد")
                elif c in out["usd_per_quote"]:
                    errors.append("نرخِ ارزِ تکراری در usd_per_quote")
                else:
                    out["usd_per_quote"][c] = rate
    c = out["account_ccy"]
    if c not in USD_PER_QUOTE and c not in out["usd_per_quote"]:
        errors.append(f"نرخِ تبدیلِ ارزِ حساب (account_ccy={c}) موجود نیست؛ usd_per_quote لازم است")
    if len(errors) > MAX_SETTINGS_ERRORS:
        errors = errors[:MAX_SETTINGS_ERRORS] + ["خطاهای بیشتری در تنظیماتِ ریسک وجود دارد"]
    if errors:
        out["validation_errors"] = list(errors)
    return out, errors


def validate_settings(d):
    """Partial updates are allowed; present invalid values must be rejected by API/import."""
    if not isinstance(d, dict):
        return ["تنظیماتِ ریسک باید شیء باشد"]
    return _normalized_settings(d)[1]


def load_settings(path=None):
    """Safe display defaults on corrupt files, with persistent fail-closed diagnostics."""
    p = path or settings_path()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return _normalized_settings(None)[0]
    except (OSError, ValueError, RecursionError):
        data = {"validation_errors": ["فایلِ تنظیماتِ ریسک خوانده نشد یا خراب است"]}
    return _normalized_settings(data)[0]


def save_settings(d, path=None):
    """Atomic unique-temp write. Legacy normalization retains a blocking diagnostic."""
    data, _ = _normalized_settings(d)
    data["updated_utc"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    _write_json(path or settings_path(), data)
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
    if not isinstance(symbol, str):
        return None
    s = symbol.upper().replace("/", "").replace("-", "").strip()
    if not s.isascii():
        return None
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
    if (len(s) == 6 and s.isalpha() and s[:3] in _FX_CCY and s[3:] in _FX_CCY
            and s[:3] != s[3:]):
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
    """Finite JSON/CSV scalar only; bool, nonfinite and underflow are not zero."""
    if isinstance(x, bool) or not isinstance(x, (int, float, str)):
        return None
    if isinstance(x, str):
        if len(x) > 1024:
            return None
        x = x.strip().replace(",", "").replace("٬", "")
        if not x:
            return None
    try:
        f = float(x)
        if not math.isfinite(f):
            return None
        if f == 0 and isinstance(x, str) and Decimal(x) != 0:
            return None
        return f
    except (TypeError, ValueError, OverflowError, DecimalException):
        return None


def _missing(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _dec(value):
    if isinstance(value, str):
        value = value.strip().replace(",", "").replace("٬", "")
    return Decimal(str(value))


def _finite_float(value):
    f = float(value)
    if not math.isfinite(f) or (f == 0 and value != 0):
        raise ArithmeticError("نتیجهٔ محاسبه در محدودهٔ عددِ متناهی نیست")
    return f


def dir_sign(direction):
    """جهت → +۱ خرید / -۱ فروش / ۰ نامشخص (هم فارسیِ گریدر، هم long/short)."""
    if type(direction) is int and direction in (-1, 1):
        return direction
    if not isinstance(direction, str):
        return 0
    t = direction.strip().lower()
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
    c = _currency(ccy)
    if c is None:
        return None, False
    if c == "USD":
        return 1.0, False
    ov = (settings or {}).get("usd_per_quote") or {}
    if not isinstance(ov, dict):
        return None, False
    if c in ov:
        rate = _num(ov[c])
        return (rate if rate is not None and rate > 0 else None), False
    return USD_PER_QUOTE.get(c), True


def size_for(symbol, plan, settings):
    """Finite position sizing; floor to the lot step without exceeding its budget."""
    out = {"ok": False, "reason": "", "approx": False, "notes": []}
    spec = instrument(symbol)
    st, errors = _normalized_settings(settings)
    if spec is None:
        out["reason"] = "مشخصاتِ قراردادِ نماد را نمی‌شناسم"
        return out
    if errors:
        out["reason"] = " · ".join(errors)
        return out
    if not isinstance(plan, dict) or not plan:
        out["reason"] = "پلنِ معتبر برای سایزکردن نیست"
        return out
    entry, sl = _num(plan.get("entry")), _num(plan.get("sl"))
    if entry is None or sl is None:
        out["reason"] = "ورود یا استاپ باید عددِ متناهی باشد"
        return out
    rr_value = plan.get("rr")
    rr = 0.0 if _missing(rr_value) else _num(rr_value)
    if rr is None or rr < 0:
        out["reason"] = "نسبتِ ریسک به ریوارد معتبر نیست"
        return out
    if st["balance"] <= 0 or st["risk_pct"] <= 0:
        out["reason"] = "سرمایه و درصدِ ریسک باید مثبت باشند"
        return out
    acc = st["account_ccy"]
    q_rate, q_assumed = _usd_per_quote(spec["quote"], st)
    a_rate, a_assumed = _usd_per_quote(acc, st)
    if q_rate is None or a_rate is None:
        out["reason"] = "نرخِ تبدیلِ ارزِ حساب یا مظنه معلوم نیست"
        return out
    try:
        with localcontext() as ctx:
            ctx.prec = _DECIMAL_PRECISION
            stop_d = abs(_dec(entry) - _dec(sl))
            if stop_d <= 0:
                raise ValueError("فاصلهٔ استاپ صفر است")
            risk_d = _dec(st["balance"]) * _dec(st["risk_pct"]) / Decimal(100)
            def ratio(currency, rate):
                # Preserve explicit user rates. Default reciprocal quotes retain
                # their original ratio so binary 1/150 cannot shave a lot step.
                inverse = {"JPY": "150", "CHF": "0.88", "CAD": "1.36"}
                if currency not in st["usd_per_quote"] and currency in inverse:
                    return Decimal(1), Decimal(inverse[currency])
                return _dec(rate), Decimal(1)
            q_num, q_den = ratio(spec["quote"], q_rate)
            a_num, a_den = ratio(acc, a_rate)
            num, den = (Decimal(1), Decimal(1)) if acc == spec["quote"] else (q_num * a_den, q_den * a_num)
            value_d = _dec(spec["contract"]) * num / den
            per_lot_d = stop_d * value_d
            step_d = Decimal(1) if spec["kind"] == "stock" else (Decimal("0.000001") if spec["kind"] == "crypto" else Decimal("0.01"))
            count = (risk_d * den / (stop_d * _dec(spec["contract"]) * num * step_d)).to_integral_value(rounding=ROUND_FLOOR)
            over_risk = count < 1
            lots_d = max(Decimal(1), count) * step_d
            actual_d = lots_d * per_lot_d
            # Every public numeric quantity must fit a finite JSON float.
            stop = _finite_float(stop_d)
            risk_amount = _finite_float(risk_d)
            value_per_unit = _finite_float(value_d)
            risk_per_lot = _finite_float(per_lot_d)
            size_lots = _finite_float(lots_d)
            actual_risk = _finite_float(actual_d)
            size_units = _finite_float(lots_d * _dec(spec["contract"]))
            stop_pips = _finite_float(stop_d / _dec(spec["point"])) if spec["point"] else None
            point_value = _finite_float(_dec(spec["point"]) * value_d)
            reward = _finite_float(actual_d * _dec(rr)) if rr else None
    except (ArithmeticError, ValueError, OverflowError, DecimalException) as exc:
        out["reason"] = "محاسبهٔ ریسک معتبر یا متناهی نیست: " + str(exc)
        return out
    size_disp = int(size_lots) if spec["kind"] == "stock" else round(size_lots, 6 if spec["kind"] == "crypto" else 2)
    out.update({"ok": True, "symbol": spec["symbol"], "kind": spec["kind"],
                "unit_fa": spec["unit_fa"], "size": size_disp, "size_lots": size_lots,
                "size_units": size_units, "balance": st["balance"], "account_ccy": acc,
                "risk_pct": st["risk_pct"], "risk_amount": round(risk_amount, 2),
                "actual_risk_amount": round(actual_risk, 2),
                "reward_amount": round(reward, 2) if reward is not None else None,
                "stop_distance": round(stop, 6), "stop_pips": round(stop_pips, 1) if stop_pips is not None else None,
                "point": spec["point"], "value_per_point": round(point_value, 4),
                "risk_per_lot": round(risk_per_lot, 2), "contract": spec["contract"],
                "quote": spec["quote"], "approx": bool(spec["approx"] or q_assumed or a_assumed),
                "over_risk": over_risk})
    if over_risk:
        out["notes"].append("کوچک‌ترین پلهٔ قابلِ معامله از سقفِ ریسکِ هدف بزرگ‌تر است؛ از این ستاپ بگذر یا مشخصاتِ قرارداد را بررسی کن")
    elif actual_d < risk_d:
        out["notes"].append("به کفِ پله گرد شد تا از ریسکِ هدف بیشتر نشود")
    if spec["note"]:
        out["notes"].append(spec["note"])
    if q_assumed and spec["quote"] != "USD":
        out["notes"].append("نرخِ تبدیلِ ارزِ مظنه تقریبی است؛ برای سایزِ دقیق نرخِ کارگزار را وارد کن")
    return out


# ═══════════════════════════════════════════════════════════════════
#  سقفِ ضررِ روزانه + ریسکِ باز
# ═══════════════════════════════════════════════════════════════════
def _row_realized_r(r):
    """Blank legacy results have documented fallbacks; bad present values do not."""
    value = r.get("realized_r")
    if not _missing(value):
        number = _num(value)
        if number is None:
            raise ValueError("آرِ محقق‌شدهٔ دفتر عددِ معتبر نیست")
        return number
    result = str(r.get("result") or "").strip().lower()
    if result in ("win", "برد", "سود"):
        raw = r.get("rr")
        number = 1.0 if _missing(raw) else _num(raw)
        if number is None or number <= 0:
            raise ValueError("نسبتِ ریسک به ریواردِ بردِ دفتر معتبر نیست")
        return number
    if result in ("loss", "باخت", "ضرر"):
        return -1.0
    if result in ("be", "breakeven", "سربه‌سر"):
        return 0.0
    raise ValueError("نتیجهٔ معاملهٔ بسته معلوم نیست")


def daily_state(rows, settings, now=None):
    """Account-money, realized R and raw risk-percent stay distinct and finite."""
    st, errors = _normalized_settings(settings)
    clock = datetime.datetime.now() if now is None else now
    if not isinstance(clock, (datetime.datetime, datetime.date)):
        errors.append("زمانِ محاسبهٔ ریسک معتبر نیست")
        clock = datetime.datetime.now()
    today = clock.strftime("%Y-%m-%d")
    balance, limit_pct, open_limit = st["balance"], st["daily_loss_limit_pct"], st["max_open_risk_pct"]
    out = {"date": today, "balance": balance, "limit_pct": limit_pct, "limit_amount": 0.0,
           "realized_r": 0.0, "realized_pct": 0.0, "realized_amount": 0.0,
           "closed_today": 0, "remaining_pct": None, "remaining_amount": None,
           "breached": False, "open_count": 0, "open_risk_pct": 0.0,
           "open_risk_limit_pct": open_limit, "open_breached": False,
           "open_risk_amount": 0.0, "open_positions": [], "open_risk_pct_raw": 0.0}
    if rows is None:
        rows = []
    if not isinstance(rows, (list, tuple)):
        errors.append("شکلِ ردیف‌های دفتر معتبر نیست")
        rows = []
    try:
        with localcontext() as ctx:
            ctx.prec = _DECIMAL_PRECISION
            realized, percent, open_percent = Decimal(0), Decimal(0), Decimal(0)
            for row in rows:
                if not isinstance(row, dict):
                    errors.append("ردیفِ دفتر باید شیء باشد")
                    continue
                status = str(row.get("status") or "").strip().lower()
                if status not in ("closed", "open"):
                    errors.append("وضعیتِ معاملهٔ دفتر معلوم نیست")
                    continue
                raw_risk = row.get("risk_pct")
                risk = st["risk_pct"] if _missing(raw_risk) else _num(raw_risk)
                if risk is None or risk < 0:
                    errors.append("درصدِ ریسکِ ردیفِ دفتر معتبر نیست")
                    continue
                if status == "open":
                    open_percent += _dec(risk)
                    out["open_count"] += 1
                    if row.get("symbol"):
                        out["open_positions"].append({"symbol": str(row["symbol"]).upper(),
                            "direction": row.get("direction") if isinstance(row.get("direction"), (str, int)) else "",
                            "sign": dir_sign(row.get("direction")), "risk_pct": risk})
                    continue
                stamp = row.get("datetime")
                try:
                    if not isinstance(stamp, str):
                        raise ValueError
                    date = datetime.datetime.fromisoformat(stamp).date().isoformat()
                except (ValueError, TypeError):
                    errors.append("تاریخِ معاملهٔ بسته معتبر نیست")
                    continue
                if date != today:
                    continue
                try:
                    r_value = _row_realized_r(row)
                except ValueError as exc:
                    errors.append(str(exc))
                    continue
                realized += _dec(r_value)
                percent += _dec(r_value) * _dec(risk)
                out["closed_today"] += 1
            pnl_d = _dec(balance) * percent / Decimal(100)
            limit_d = _dec(balance) * _dec(limit_pct) / Decimal(100)
            open_amount_d = _dec(balance) * open_percent / Decimal(100)
            raw_open = _finite_float(open_percent)
            raw_percent = _finite_float(percent)
            out.update(realized_r=round(_finite_float(realized), 2), realized_pct=round(raw_percent, 2),
                       realized_amount=round(_finite_float(pnl_d), 2), limit_amount=round(_finite_float(limit_d), 2),
                       open_risk_pct=round(raw_open, 2), open_risk_pct_raw=raw_open,
                       open_risk_amount=round(_finite_float(open_amount_d), 2),
                       breached=bool(limit_pct > 0 and -percent >= _dec(limit_pct)),
                       open_breached=bool(open_limit > 0 and open_percent >= _dec(open_limit)))
            if limit_pct > 0:
                out["remaining_pct"] = round(_finite_float(max(Decimal(0), _dec(limit_pct) + percent)), 2)
                out["remaining_amount"] = round(_finite_float(max(Decimal(0), limit_d + pnl_d)), 2)
    except (ArithmeticError, ValueError, OverflowError, DecimalException) as exc:
        errors.append("حاصلِ محاسبهٔ دفتر معتبر یا متناهی نیست: " + str(exc))
    out["validation_errors"] = list(dict.fromkeys(errors))[:MAX_SETTINGS_ERRORS]
    out["valid"] = not bool(out["validation_errors"])
    return out


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


# ═══════════════════════════════════════════════════════════════════
#  ضرایبِ هم‌بستگیِ مرجع — لایهٔ *عددی* (روی لایهٔ فاکتوریِ بالا)
# ═══════════════════════════════════════════════════════════════════
# لایهٔ فاکتوری می‌گوید «هر دو روی دلار جمع شده‌اند» (هم‌ارزیِ ارزی)؛ این لایه
# می‌گوید «این دو نماد با ضریبِ ‎+۰٫۸۵ هم‌بسته‌اند، پس ریسکِ مؤثرِ تو ۱٫۸۵ برابرِ
# یک پوزیشن است» — عددی که کاربر می‌بیند و بر اساسش سایز را کم می‌کند.
#
# علامت = هم‌بستگیِ *قیمتِ* دو نمادِ قابلِ‌معامله؛ مقدار = ضریبِ تقریبیِ بازار
# (میانگینِ ~۹۰ روزهٔ ۲۰۲۳–۲۰۲۶، گردشده به دو رقم). عمداً ثابت و آفلاین است
# (محاسبهٔ زندهٔ هم‌بستگی بدونِ شبکه/دادهٔ تاریخی ممکن نیست) و فقط برای *هشدارِ
# ریسک* به کار می‌رود، نه برای پیش‌بینیِ قیمت.
#
# نکتهٔ علامت — همان‌جایی که در بازار هم اشتباه می‌شود:
#   • طلا و دلارِ کانادا (CAD) هم‌بستگیِ **مثبت** دارند (کانادا صادرکنندهٔ طلا و
#     نفت است)؛ ولی نمادِ قابلِ‌معامله «USDCAD» است که وارونهٔ CAD تعریف می‌شود،
#     پس ضریبِ جدول برای XAUUSD↔USDCAD **منفی** درمی‌آید. همین منطق برای AUD
#     (صادرکنندهٔ طلا) و برای نفت↔CAD هم برقرار است.
#   • طلا↔دلار منفی (DXY)، یورو↔دلار این‌دکس به‌شدت منفی، ین↔دلار مثبت.
CORRELATION_WARN_MIN = 0.5      # ‎|ضریب| ≥ این ⇒ هشدارِ صریح
CORRELATION_NOTE_MIN = 0.3      # ‎۰٫۳ تا ۰٫۵ ⇒ فقط یادداشتِ ملایم (هشدار بی‌اثر نشود)

CORRELATION_COEFS = [
    # (الف، ب، ضریب، توضیحِ فارسیِ منطقِ بازار)
    ("BTCUSDT", "ETHUSDT", 0.85, "کریپتوی بزرگ — آلت‌کوین‌ها با «ریسک‌آن» مشترک هم‌جهتند"),
    ("BTCUSDT", "SOLUSDT", 0.78, "آلت‌کوینِ بتا-بالا: هم‌جهت با بیت‌کوین، با نوسانِ بیشتر"),
    ("ETHUSDT", "SOLUSDT", 0.80, "دو آلت‌کوینِ شاخص — عملاً یک شرط روی کریپتو"),
    ("BTCUSDT", "NAS100", 0.55, "کریپتو و شاخصِ تکنولوژی هر دو داراییِ ریسک‌آن‌اند"),
    ("BTCUSDT", "XAUUSD", 0.20, "هر دو در برابرِ دلار ضعیف بالا می‌روند، ولی پیوندشان ضعیف است"),
    ("XAUUSD", "XAGUSD", 0.82, "طلا و نقره — یک فاکتورِ فلزاتِ گران‌بها"),
    ("XAUUSD", "DXY", -0.85, "طلا وارونهٔ دلار است (دلارِ قوی‌تر = طلای گران‌تر برای بقیهٔ دنیا)"),
    ("XAUUSD", "USDCAD", -0.55, "طلا با دلارِ کانادا مثبت است (صادرکنندهٔ طلا/نفت)؛ USDCAD وارونه ⇒ منفی"),
    ("XAUUSD", "AUDUSD", 0.45, "استرالیا صادرکنندهٔ طلاست — اثرِ ملایم"),
    ("WTI", "USDCAD", -0.45, "نفت و دلارِ کانادا مثبت‌اند؛ USDCAD وارونه ⇒ منفی"),
    ("EURUSD", "GBPUSD", 0.75, "دو ارزِ اصلیِ اروپایی در برابرِ دلار"),
    ("EURUSD", "AUDUSD", 0.65, "هر دو «دلارِ ضعیف» را معامله می‌کنند"),
    ("AUDUSD", "NZDUSD", 0.88, "کامودال‌های آینه‌ای — نزدیک‌ترین جفتِ هم‌بستهٔ فارکس"),
    ("EURUSD", "DXY", -0.96, "یورو ~۵۷٪ سبدِ دلار است — تقریباً وارونهٔ یکدیگر"),
    ("USDCHF", "EURUSD", -0.90, "فرانکِ سوئیس جفتِ آینه‌ایِ یورو در بازارِ ارز"),
    ("USDJPY", "DXY", 0.90, "ین ارزِ فاندینگ است — USDJPY و شاخصِ دلار هم‌جهت‌اند"),
    ("SPX500", "NAS100", 0.94, "دو شاخصِ آمریکا — عملاً یک شرط روی وال‌استریت"),
    ("US30", "SPX500", 0.92, "شاخص‌های آمریکا با هم بالا/پایین می‌روند"),
    ("GER40", "SPX500", 0.60, "هم‌بستگیِ متوسطِ شاخصِ اروپا با آمریکا"),
]

_COEF_MAP = {}
for _ca, _cb, _cc, _cn in CORRELATION_COEFS:
    _COEF_MAP[frozenset((_ca, _cb))] = (_cc, _cn)


def _sym_key(symbol):
    """نمادِ کانونیک: از همان `instrument` (نام‌های جایگزین/حذفِ اسلش)، با پشتوانهٔ متنِ خام."""
    spec = instrument(symbol)
    if spec:
        return spec["symbol"]
    return (symbol or "").upper().replace("/", "").replace("-", "").strip()


def pair_coef(a, b):
    """ضریبِ هم‌بستگیِ مرجعِ دو نماد (متقارن؛ `known=False` = در جدول نیست).

    هم‌بستگیِ قیمت-قیمت متقارن است، پس جای دو آرگومان علامت را عوض نمی‌کند
    (برخلافِ بتا که جهت‌دار است). نمادِ ناشناخته/یکسان ⇒ صفر و بی‌هشدار.
    """
    na, nb = _sym_key(a), _sym_key(b)
    out = {"coef": 0.0, "known": False, "a": na, "b": nb, "note": ""}
    if not na or not nb or na == nb:
        return out
    hit = _COEF_MAP.get(frozenset((na, nb)))
    if not hit:
        return out
    out["coef"], out["note"] = hit[0], hit[1]
    out["known"] = True
    return out


def _stack_msgs(rows):
    """پیام‌های فارسیِ «ریسکِ تکراری روی یک فاکتور» برای یک فهرستِ (برچسب، خالص، جهت).

    جدا شد تا فهرستِ خام (فاکتوری) و فهرستِ نمایشی (بعد از حذفِ تکرارِ لایهٔ
    عددی) یک متنِ واحد داشته باشند، نه دو جای متفاوت.
    """
    out = []
    for lbl, v, same in rows[:2]:
        out.append(
            f"هشدارِ هم‌بستگی: این معامله در فاکتورِ «{lbl}» {same} با پوزیشن‌های "
            f"بازِ تو جمع می‌شود (خالصِ فاکتور {v:+d}) — ریسکِ تکراری است، "
            f"نه یک معامله‌ی مستقل")
    if len(rows) > 2:
        extra = "، ".join(f"{lbl} {v:+d}" for lbl, v, _ in rows[2:])
        out.append(
            f"و در {len(rows) - 2} فاکتورِ دیگر هم همین تمرکز تکرار می‌شود ({extra})")
    return out


def coef_layer(symbol, sign, open_positions):
    """لایهٔ عددیِ هم‌بستگی: تک‌تکِ پوزیشن‌های باز را با *ضریب* می‌سنجد.

    سه حالت (همه با عددِ ضریب در متنِ هشدار):
      ۱) هم‌جهت روی ضریبِ مثبت  → ریسکِ تکراری: ریسکِ مؤثر > یک پوزیشن.
      ۲) هم‌جهت روی ضریبِ منفی  → تضادِ منطقی: دو سناریوی متضاد روی یک سرمایه.
      ۳) خلافِ‌جهت روی ضریبِ مثبت → هجِ ناخواسته: خنثی‌سازی + سوزاندنِ هزینه.
    """
    out = {"pairs": [], "warnings": [], "notes": [],
           "effective": {"multiple": 1.0, "offset": 0.0,
                         "stacked_count": 0, "hedged_count": 0, "count": 0}}
    if sign not in (1, -1):
        return out
    ca = _sym_key(symbol)
    if not ca:
        return out
    add, off = 0.0, 0.0
    for p in (open_positions or []):
        if not isinstance(p, dict):
            continue
        psym, psgn = p.get("symbol"), p.get("sign")
        if psgn not in (1, -1) or not psym:
            continue
        info = pair_coef(ca, psym)
        if not info["known"] or abs(info["coef"]) < CORRELATION_NOTE_MIN:
            continue
        c = info["coef"]
        b = info["b"]
        pos_fa = "خرید" if psgn == 1 else "فروش"
        rec = {"a": ca, "b": b, "coef": c, "note": info["note"],
               "open_sign": psgn, "aligned": bool(sign * psgn * c > 0)}
        out["pairs"].append(rec)
        if abs(c) < CORRELATION_WARN_MIN:
            out["notes"].append(
                f"هم‌بستگیِ ملایم (ضریبِ {c:+.2f}): «{ca}» و «{b}» در جدولِ ما هم‌جهتِ "
                f"ملایم‌اند ({info['note']}) — به‌تنهایی دلیلِ ردکردنِ معامله نیست، "
                f"فقط سایز را به همان نسبت (≈{abs(c):.2f}) در نظر بگیر")
            continue
        if rec["aligned"]:
            add += abs(c)
            out["effective"]["stacked_count"] += 1
            out["warnings"].append(
                f"ریسکِ هم‌بسته (ضریبِ {c:+.2f}): این معامله روی «{ca}» با پوزیشنِ "
                f"بازِ «{b}» ({pos_fa}) هم‌جهتِ همان شرط است — {info['note']}. "
                f"دو معامله در عمل یک شرط‌اند، نه دو شرطِ مستقل؛ ریسکِ مؤثر ≈{1.0 + add:.2f}"
                f"× یک پوزیشن می‌شود. سایزِ این ورود را به همان نسبت کم کن یا یکی را انتخاب کن")
        elif sign == psgn:
            out["effective"]["hedged_count"] += 1
            out["warnings"].append(
                f"تضادِ هم‌بستگی (ضریبِ {c:+.2f}): «{ca}» و «{b}» هم‌بستگیِ **منفی** "
                f"دارند ({info['note']}) ولی هر دو در یک جهت معامله شده‌اند — دو سناریوی "
                f"متضاد روی یک سرمایه. نتیجه تقریباً یکدیگر را می‌خورند و تو دو بار هزینه "
                f"می‌دهی؛ یکی را انتخاب کن")
        else:
            off += abs(c)
            out["effective"]["hedged_count"] += 1
            out["warnings"].append(
                f"هجِ ناخواسته (ضریبِ {c:+.2f}): پوزیشنِ بازِ «{b}» ({pos_fa}) با این "
                f"معامله روی «{ca}» خلافِ جهت است، در حالی که این دو با ضریبِ {c:+.2f} "
                f"هم‌جهت حرکت می‌کنند ({info['note']}) — یعنی ~{abs(c):.0%} از ریسکِ هم را "
                f"خنثی می‌کنی و فقط اسپرد/کمیسیون می‌سوزد. اگر عمداً هج نیست، یکی را ببند")
    out["effective"]["multiple"] = round(1.0 + add, 2)
    out["effective"]["offset"] = round(off, 2)
    out["effective"]["count"] = len(out["pairs"])
    return out


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
    # لایهٔ عددیِ هم‌بستگی (ضرایبِ مرجع) — همین‌جا حساب می‌شود تا هم dedupe و
    # هم فهرستِ نمایشی از آن استفاده کنند.
    cl = coef_layer(symbol, sign, open_positions)
    covered = {r["b"] for r in cl["pairs"] if abs(r["coef"]) >= CORRELATION_WARN_MIN}

    def _factor_covered(k, same_sign=True):
        """آیا همهٔ پوزیشن‌های بازِ سازندهٔ این فاکتور را لایهٔ عددی هم صدا زده است؟

        اگر بله، پیامِ کیفیِ فاکتور تکرارِ همان واقعیت است (مثلِ BTC+ETH: هم
        فاکتورِ «کریپتو» و هم ضریبِ ‎+۰٫۸۵). برای پیامِ «خلافِ‌جهت» عکسِ این
        سنجیده می‌شود: پوزیشن‌های هم‌راستا با این معامله گفته می‌شوند، پوزیشن‌های
        مخالف (که همین‌ها ریسک را خنثی می‌کنند).
        """
        cv = cand.get(k, 0)
        if not cv or not covered:
            return False
        hits = []
        for p in (open_positions or []):
            if not isinstance(p, dict):
                continue
            psym, psgn = p.get("symbol"), p.get("sign")
            if psgn not in (1, -1) or not psym:
                continue
            pv = exposures(psym, psgn).get(k, 0)
            if pv and ((pv > 0) == (cv > 0)) == bool(same_sign):
                hits.append(_sym_key(psym))
        return bool(hits) and all(h in covered for h in hits)

    stacked = {k: v for k, v in net.items() if abs(v) >= 2}
    # هم‌جمعی (|خالص| ≥ ۲) = ریسکِ تکراری؛ اما وقتی معامله‌ی جدید روی یک فاکتور
    # **خلافِ** پوزیشن‌های بازِ موجود جمع شود (مثلِ خریدِ USDJPY در حالی که
    # EURUSDِ خریدِ باز داری: USD −۱+۱ = ۰، یا فروشِ XAUUSD در حالی که طلا خریدی)،
    # هشدارِ «تمرکز» معنا ندارد — چیزی که واقعاً باید گفته شود این است که دو
    # ستاپِ هم‌زمانِ تو خواسته‌ی متضاد از بازار دارند (جنگِ داخلیِ ریسک). خواسته‌ی
    # کاربر: «برای جفت‌های همبسته تریدِ خلافِ جهتِ هم هشدار بده».
    # شرطِ درست: سهمِ **بقیه‌ی** پوزیشن‌ها (خالص منفیِ سهمِ خودمان) باید خلافِ
    # سهمِ خودمان و غیرصفر باشد.
    stacked_against = {}
    for k, cv in cand.items():
        rest = net.get(k, 0) - cv
        if rest and (cv > 0) != (rest > 0):
            stacked_against[k] = net.get(k, 0)
    ordered = sorted(stacked.items(), key=lambda kv: -abs(kv[1]))
    against = sorted(stacked_against.items(), key=lambda kv: -abs(kv[1]))
    mine, mine_k, pre, opp = [], [], [], []
    for k, v in ordered:
        lbl = _factor_label(k)
        # جهت را از سهمِ **خودِ این معامله** روی همان فاکتور می‌سنجیم، نه از جهتِ
        # نماد: طلا در فاکتورِ دلار منفی است، پس مقایسه با جهتِ نماد گمراه می‌شد.
        own = cand.get(k, 0)
        if own:
            same = "هم‌راستا" if (own > 0) == (v > 0) else "در جهتِ مخالف"
            mine.append((lbl, v, same))
            mine_k.append(k)
        else:
            # این معامله به این فاکتور دست نمی‌زند؛ تمرکز از خودِ پوزیشن‌های باز است.
            # جدا گزارش می‌شود تا به‌اشتباه به این ستاپ نسبت داده نشود.
            pre.append((lbl, v))
    for k, _v in against:
        opp.append(_factor_label(k))
    # یک معاملهٔ تکراری (مثلِ طلا) هم روی «فلزات» و هم روی «دلار» جمع می‌شود؛
    # دو موردِ نخست را می‌گوییم و بقیه را در یک سطر جمع می‌کنیم تا بنر خوانا بماند.
    # فهرستِ خام (فاکتوری) برای API می‌ماند؛ فهرستِ *نمایشی* تکرارِ لایهٔ عددی را
    # حذف می‌کند تا یک واقعیت دو بار به کاربر گفته نشود.
    mine_shown = [(lbl, v, same) for (lbl, v, same), k in zip(mine, mine_k)
                  if not _factor_covered(k)]
    trade_msgs = _stack_msgs(mine)
    shown_trade = _stack_msgs(mine_shown)
    # هشدارِ «خلافِ جهت روی جفتِ همبسته» — اولویتش بالاتر از تمرکز است چون خطای
    # منطقی است نه فقط تکرارِ ریسک: دو ستاپِ تو خواسته‌ی متضاد از بازار دارند.
    # صداقت: اگر خالصِ فاکتور صفر شده باشد می‌گوییم «خنثی می‌کند»؛ اگر فقط کم
    # شده باشد می‌گوییم «ریسکِ هم را کم می‌کند» (هج ناخواسته).
    opp_msgs = []
    # فقط یکی از فاکتورهای متضاد را می‌گوییم: برای هجِ همان نماد (مثلِ فروشِ طلا
    # در حالی که طلا خریدی) هم «فلزات» و هم «دلار» متضاد می‌شوند و هر دو یک
    # واقعیت را توصیف می‌کنند — دو سطرِ تکراریِ هشدار، شلوغیِ بی‌دلیل است.
    # همان حذفِ تکرارِ نمایشی برای پیامِ «تریدِ خلافِ جهت روی فاکتورِ مشترک»:
    # اگر لایهٔ عددی همین پوزیشن‌ها را با ضریبِ منفی صدا زده باشد، همین واقعیت
    # دو بار گفته می‌شود.
    if against and not _factor_covered(against[0][0], same_sign=False):
        k = against[0][0]
        lbl = _factor_label(k)
        own_v = cand.get(k, 0)
        rest_v = net.get(k, 0) - own_v
        if rest_v == 0 or (own_v > 0) != (rest_v > 0):
            opp_msgs.append(
                f"تریدِ خلافِ جهت: این معامله روی فاکتورِ «{lbl}» دقیقاً خلافِ "
                f"پوزیشن(های) بازِ توست و آن‌ها را خنثی می‌کند — دو ستاپِ هم‌زمانِ "
                f"تو دو سناریوی متضاد را معامله می‌کنند؛ یکی را انتخاب کن")
        else:
            opp_msgs.append(
                f"تریدِ خلافِ جهت: این معامله روی فاکتورِ «{lbl}» خلافِ پوزیشن(های) "
                f"بازِ توست — اگر عمداً هج نیست، یک سناریوی متضاد را بیهوده هم‌زمان معامله می‌کنی")

    conc = [f"توجه: پوزیشن‌های بازِ تو خودشان روی «{lbl}» تمرکز دارند "
            f"(خالصِ فاکتور {v:+d}) — پیش از ورودِ بعدی این تمرکز را در نظر بگیر"
            for lbl, v in pre[:2]]
    return {
        # `warnings` همان چیزی که رابط نشان می‌دهد — ترتیب: هشدارِ خلافِ جهتِ
        # هم (خطایِ منطقی، مهم‌تر)، بعد تکرارِ ریسکِ هم‌راستا، بعد تمرکزِ موجود.
        # ترتیب: هشدارِ عددیِ هم‌بستگی (با ضریب) → خلافِ‌جهت روی فاکتورِ مشترک →
        # تکرارِ ریسکِ هم‌راستا → یادداشت‌های ملایم → تمرکزِ موجود.
        "warnings": cl["warnings"] + opp_msgs + shown_trade + cl["notes"] + conc,
        "trade_warnings": trade_msgs,
        "opposite_warnings": opp_msgs,
        "open_concentration": conc,
        # لایهٔ عددیِ هم‌بستگی — جدا از لایهٔ فاکتوری نگه داشته می‌شود تا
        # `trade_warnings` (فاکتورِ مشترک) معنای قبلی‌اش را از دست ندهد.
        "coef_warnings": cl["warnings"],
        "coef_notes": cl["notes"],
        "coef_pairs": cl["pairs"],
        "effective": cl["effective"],
        "stacked": {k: v for k, v in stacked.items()},
        "stacked_opposite": {k: v for k, v in stacked_against.items()},
        "net": {k: v for k, v in net.items() if v},
        "candidate_exposures": cand,
        "open_count": len([p for p in (open_positions or []) if isinstance(p, dict)]),
    }


# ═══════════════════════════════════════════════════════════════════
#  بلوکِ نهایی برای API/رابط
# ═══════════════════════════════════════════════════════════════════
def evaluate(symbol, plan, settings, rows, now=None):
    """All invalid evidence blocks permission; rounded display cannot bypass caps."""
    st, errors = _normalized_settings(settings)
    day = daily_state(rows, st, now=now)
    errors += day.get("validation_errors") or []
    present = plan is not None
    sign = dir_sign(plan.get("direction")) if isinstance(plan, dict) else 0
    size = size_for(symbol, plan, st) if present else {"ok": False, "reason": "پلنی برای سایزکردن نیست", "approx": False, "notes": []}
    corr = correlation(symbol, sign, day.get("open_positions")) if sign else {
        "warnings": [], "trade_warnings": [], "open_concentration": [], "stacked": {}, "net": {}, "candidate_exposures": {}, "open_count": 0}
    reasons = list(dict.fromkeys(errors))
    if present and not size.get("ok"):
        reasons.append(size.get("reason") or "سایزِ معتبر تأیید نشده")
    if present and size.get("over_risk"):
        reasons.append("کوچک‌ترین سایز از سقفِ ریسکِ این معامله بزرگ‌تر است")
    if day["breached"]:
        reasons.append("سقفِ ضررِ روزانه پر شده است؛ امروز معاملهٔ جدید نکن")
    if day["open_breached"]:
        reasons.append("مجموعِ ریسکِ معاملاتِ باز به سقف رسیده است؛ ورودِ جدید مجاز نیست")
    if present and not errors and st["max_open_risk_pct"] > 0:
        with localcontext() as ctx:
            ctx.prec = _DECIMAL_PRECISION
            projected = _dec(day["open_risk_pct_raw"]) + _dec(st["risk_pct"])
            if projected > _dec(st["max_open_risk_pct"]):
                reasons.append("ریسکِ باز به‌اضافهٔ ورودِ پیشنهادی از سقفِ ریسکِ باز بیشتر می‌شود")
    reasons = list(dict.fromkeys(reasons))
    return {"settings": {k: st[k] for k in ("balance", "account_ccy", "risk_pct", "daily_loss_limit_pct", "max_open_risk_pct")},
            "size": size, "daily": day, "correlation": corr, "blocked": bool(reasons),
            "block_reason": " · ".join(reasons) if reasons else None,
            "warnings": list(corr.get("warnings") or []) + reasons,
            "trade_warnings": list(corr.get("trade_warnings") or [])}


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
