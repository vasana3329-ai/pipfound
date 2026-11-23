#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
موتورِ فاندمنتال — تقویمِ اقتصادی + تحلیلِ جهت‌گیریِ اثرِ هر خبر روی جفت‌ارزهای مهم و طلا/نقره.

تکیه بر macro_context.get_calendar() (دیتای ForexFactory، فقط stdlib، بدون API key).
این ماژول قضاوتِ تکنیکالِ اپ را دست نمی‌زند؛ فقط لایه‌ی «چرا این خبر مهم است و بازار
احتمالاً چه واکنشی نشان می‌دهد» را — با منطقِ استانداردِ یک تریدرِ فاندمنتال — اضافه می‌کند.

اصولِ به‌کاررفته (بدونِ حدس، طبقِ کتابِ ماکرو):
  • داده‌ی «بهتر از انتظار» روی رشد/تورم/اشتغال/PMI/نرخ  →  ارزِ مربوطه قوی‌تر (هاوکیش).
  • استثنا: نرخِ بیکاری و مدعیانِ بیکاری معکوس‌اند (بالاتر = ضعیف‌تر).
  • طلا و نقره به دلار قیمت می‌خورند و معکوسِ دلار/بازده‌های واقعی‌اند:
        دلارِ قوی‌تر (دیتای قویِ آمریکا)  →  طلا و نقره پایین‌تر، و برعکس.
  • تنها اخبارِ دلاری، طلا/نقره را مستقیم تکان می‌دهند؛ اخبارِ غیردلاری فقط از مسیرِ
    کراسِ دلاری اثرِ حاشیه‌ای دارند.
  • آنچه بازار تکان می‌دهد «انحراف از پیش‌بینی» است نه خودِ عدد؛ اگر خبر از پیش
    قیمت‌گذاری‌شده باشد واکنش خنثی می‌شود. دورِ ±۱۵ تا ۳۰ دقیقه‌ی خبرِ پرتأثیر ورودِ تازه ممنوع.
"""
import datetime
import math
import re
from zoneinfo import ZoneInfo
import macro_context as M
from macro_context import (calendar_quality as _calendar_quality,
                           actuals_quality as _actuals_quality,
                           parse_event_time as _parse_event_time, SourceRows)

ET = ZoneInfo("America/New_York")
TEHRAN = datetime.timezone(datetime.timedelta(hours=3, minutes=30))  # تهران

_FA_DAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]

# نامِ ارزها به فارسی
_CCY_FA = {
    "USD": "دلارِ آمریکا", "EUR": "یورو", "GBP": "پوند", "JPY": "ینِ ژاپن",
    "AUD": "دلارِ استرالیا", "NZD": "دلارِ نیوزیلند", "CAD": "دلارِ کانادا",
    "CHF": "فرانکِ سوئیس", "CNY": "یوانِ چین", "All": "جهانی",
}

# ترجمه‌ی عنوان‌های پرتکرارِ ForexFactory (برای RTL تمیز؛ عنوانِ انگلیسی هم کنارش می‌آید)
_TITLE_FA = {
    "Non-Farm Employment Change": "تغییرِ اشتغالِ غیرکشاورزی (NFP)",
    "Average Hourly Earnings m/m": "میانگینِ دستمزدِ ساعتی (ماهانه)",
    "Unemployment Rate": "نرخِ بیکاری",
    "Employment Change": "تغییرِ اشتغال",
    "Unemployment Claims": "مدعیانِ بیکاری (هفتگی)",
    "ADP Non-Farm Employment Change": "اشتغالِ بخشِ خصوصی (ADP)",
    "JOLTS Job Openings": "فرصت‌های شغلیِ باز (JOLTS)",
    "GDP q/q": "تولیدِ ناخالصِ داخلی (فصلی)",
    "GDP m/m": "تولیدِ ناخالصِ داخلی (ماهانه)",
    "Advance GDP q/q": "برآوردِ اولیه‌ی GDP (فصلی)",
    "ISM Manufacturing PMI": "شاخصِ مدیرانِ خریدِ تولید (ISM)",
    "ISM Services PMI": "شاخصِ مدیرانِ خریدِ خدمات (ISM)",
    "ISM Manufacturing Prices": "شاخصِ قیمت‌های تولید (ISM)",
    "Ivey PMI": "شاخصِ مدیرانِ خرید (Ivey)",
    "German Prelim CPI m/m": "تورمِ اولیه‌ی آلمان (ماهانه)",
    "CPI Flash Estimate y/y": "برآوردِ سریعِ تورمِ منطقه‌ی یورو (سالانه)",
    "Core CPI Flash Estimate y/y": "تورمِ هسته‌ی منطقه‌ی یورو (سالانه)",
    "CPI m/m": "تورمِ مصرف‌کننده (ماهانه)",
    "CPI y/y": "تورمِ مصرف‌کننده (سالانه)",
    "Core CPI m/m": "تورمِ هسته (ماهانه)",
    "Official Cash Rate": "نرخِ بهره‌ی رسمی",
    "Overnight Rate": "نرخِ بهره‌ی شبانه",
    "BOC Rate Statement": "بیانیه‌ی نرخِ بهره‌ی بانکِ کانادا",
    "BOC Press Conference": "نشستِ خبریِ بانکِ کانادا",
    "RBNZ Rate Statement": "بیانیه‌ی نرخِ بهره‌ی بانکِ نیوزیلند",
    "RBNZ Monetary Policy Statement": "بیانیه‌ی سیاستِ پولیِ بانکِ نیوزیلند",
    "RBNZ Press Conference": "نشستِ خبریِ بانکِ نیوزیلند",
    "BOE Gov Bailey Speaks": "سخنرانیِ رئیسِ بانکِ انگلستان (بِیلی)",
    "Fed Chair Powell Speaks": "سخنرانیِ رئیسِ فدرال‌رزرو (پاول)",
    "Retail Sales m/m": "خرده‌فروشی (ماهانه)",
    "Core Retail Sales m/m": "خرده‌فروشیِ هسته (ماهانه)",
    "G20 Meetings": "نشستِ گروهِ ۲۰",
}


def _ccy_fa(c):
    return _CCY_FA.get(c, c or "")


def _title_fa(t):
    return _TITLE_FA.get(t, "")


def _classify(title, country):
    """دسته‌بندیِ خبر + منطقِ جهت‌گیری. خروجی: دسته، آیکن، جهتِ همیشگی(نرمال/معکوس)، توضیح."""
    t = (title or "").lower()
    # بیانیه/لحن، عددِ نرخ نیست؛ بدونِ متن/واکنشِ بازار جهت ساخته نمی‌شود.
    if any(k in t for k in ("rate statement", "monetary policy", "press conference",
                            "speaks", "testimony", "statement")):
        return ("سخنرانیِ مقامِ پولی", "🎙️", "unknown",
                "بازار دنبالِ سرنخِ لحن است؛ بدونِ دادهٔ لحن و واکنشِ قیمت، جهت معلوم نیست.")
    if any(k in t for k in ("cash rate", "overnight rate", "rate decision",
                            "interest rate", "federal funds rate")):
        return ("نرخِ بهره", "🏦", "normal",
                "نرخ در برابرِ انتظار مقایسه می‌شود، نه صرفاً نرخِ قبلی. فشارِ استنباطیِ عدد، "
                "واکنشِ قطعیِ ارز یا طلا نیست؛ لحنِ سیاستی و بازده‌ها می‌توانند آن را تغییر دهند.")
    if "cpi" in t or "inflation" in t or "ppi" in t or "price" in t:
        return ("تورم", "📈", "normal",
                "تورمِ بالاتر از انتظار = فشار بر بانکِ مرکزی برای نرخِ بالاتر → ارز کوتاه‌مدت قوی‌تر. "
                "برای طلا: تورمِ داغ معمولاً بازده‌ی واقعی و دلار را بالا می‌برد → فشارِ نزولی بر طلا "
                "(برخلافِ تصورِ «طلا سپرِ تورم»؛ درجاِ کوتاه‌مدت، بازده‌ها حرف اول را می‌زنند).")
    if "gdp" in t:
        return ("رشدِ اقتصادی", "🏗️", "normal",
                "GDP بالاتر از انتظار = اقتصادِ قوی → احتمالِ سیاستِ پولیِ سخت‌گیرانه‌تر → ارز قوی‌تر.")
    if "unemployment rate" in t:
        return ("نرخِ بیکاری", "📉", "inverse",
                "شاخصِ معکوس: نرخِ بیکاریِ بالاتر = بازارِ کارِ ضعیف → ارز ضعیف‌تر (و برعکس).")
    if "unemployment claims" in t or "jobless" in t:
        return ("مدعیانِ بیکاری", "📄", "inverse",
                "شاخصِ معکوس: مدعیانِ بیشتر = بازارِ کارِ ضعیف → ارز ضعیف‌تر.")
    if any(k in t for k in ("non-farm", "nonfarm", "nfp", "employment change",
                            "payroll", "adp", "jolts", "earnings")):
        return ("اشتغال", "👷", "normal",
                "اشتغالِ بالاتر از انتظار = بازارِ کارِ قوی → ارز قوی‌تر. NFP و دستمزدِ ساعتیِ آمریکا "
                "از پرنوسان‌ترین اخبارِ ماه‌اند؛ اثرِ آنی روی دلار و طلا.")
    if "pmi" in t or "ism" in t:
        return ("شاخصِ مدیرانِ خرید (PMI)", "📊", "normal",
                "PMI بالای ۵۰ = انبساط. بالاتر از انتظار → ارز قوی‌تر. ISMِ آمریکا محرکِ مهمِ دلار و طلاست.")
    if "retail" in t:
        return ("خرده‌فروشی", "🛒", "normal",
                "خرده‌فروشیِ بالاتر از انتظار = مصرفِ قوی → ارز قوی‌تر.")
    return ("رویدادِ اقتصادی", "🗓️", "unknown",
            "نوع یا جهتِ تفسیرِ این شاخص معلوم نیست؛ از عدد یا نامِ ناقص، جهت نمی‌سازیم.")


def _pair_effect(ccy, strong):
    """اثرِ قوی/ضعیف‌شدنِ یک ارز روی جفت‌ارزهای مهمِ آن + طلا و نقره."""
    up = "↑ صعود"
    dn = "↓ نزول"
    pairs = []
    gold = None
    if ccy == "USD":
        if strong:
            pairs = [("EUR/USD", dn), ("GBP/USD", dn), ("AUD/USD", dn),
                     ("USD/JPY", up), ("USD/CAD", up), ("USD/CHF", up)]
            gold = ("طلا (XAU) و نقره (XAG)", dn,
                    "دلارِ قوی + بازده‌ی بالاتر → طلا و نقره تحتِ فشارِ فروش.")
        else:
            pairs = [("EUR/USD", up), ("GBP/USD", up), ("AUD/USD", up),
                     ("USD/JPY", dn), ("USD/CAD", dn), ("USD/CHF", dn)]
            gold = ("طلا (XAU) و نقره (XAG)", up,
                    "دلارِ ضعیف → طلا و نقره حمایت می‌شوند و صعود می‌کنند.")
        return pairs, gold
    # ارزهای غیردلاری: فقط کراسِ دلاریِ خودشان مستقیم حرکت می‌کند
    p = f"{ccy}/USD"
    inv = f"USD/{ccy}"
    if ccy in ("EUR", "GBP", "AUD", "NZD"):
        pairs = [(p, up if strong else dn)]
    elif ccy in ("JPY", "CAD", "CHF"):
        pairs = [(inv, dn if strong else up)]  # USD/JPY و … : قوی‌شدنِ ارزِ مخرج = نزولِ جفت
    else:
        pairs = [(p, up if strong else dn)]
    gold = ("طلا و نقره", "≈ خنثی",
            "طلا/نقره عمدتاً با دلار حرکت می‌کنند؛ خبرِ غیردلاری فقط از مسیرِ کراسِ دلاری اثرِ حاشیه‌ای دارد.")
    return pairs, gold


def _analysis(title, country):
    cat, icon, mode, why = _classify(title, country)
    ccy = country
    if mode not in ("normal", "inverse"):
        empty={"label":"تفسیرِ عدد/لحن نامعلوم است", "ccy_dir":"", "pairs":[], "gold":None}
        return {"cat":cat, "icon":icon, "why":why,
                "beat":dict(empty), "miss":dict(empty), "status":"UNKNOWN"}
    normal = (mode == "normal")
    # «بهتر از انتظار» → ارز قوی (نرمال) یا ضعیف (معکوس)
    beat_pairs, beat_gold = _pair_effect(ccy, strong=normal)
    miss_pairs, miss_gold = _pair_effect(ccy, strong=not normal)
    beat_word = "بالاتر از انتظار" if normal else "بالاتر از انتظار"
    return {
        "cat": cat, "icon": icon, "why": why,
        "beat": {
            "label": ("عددِ بهتر/بالاتر از انتظار" if normal
                      else "عددِ بالاتر از انتظار (شاخصِ معکوس → ارز ضعیف)"),
            "ccy_dir": (f"{_ccy_fa(ccy)} قوی‌تر" if normal else f"{_ccy_fa(ccy)} ضعیف‌تر"),
            "pairs": beat_pairs, "gold": beat_gold,
        },
        "miss": {
            "label": ("عددِ بدتر/پایین‌تر از انتظار" if normal
                      else "عددِ پایین‌تر از انتظار (شاخصِ معکوس → ارز قوی)"),
            "ccy_dir": (f"{_ccy_fa(ccy)} ضعیف‌تر" if normal else f"{_ccy_fa(ccy)} قوی‌تر"),
            "pairs": miss_pairs, "gold": miss_gold,
        },
    }


def _countdown_fa(td):
    total = int(td.total_seconds())
    if total < 0:
        return "گذشته"
    d, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    parts = []
    if d:
        parts.append(f"{d} روز")
    if h:
        parts.append(f"{h} ساعت")
    if not d and not h:
        parts.append(f"{m} دقیقه")
    elif not d:
        parts.append(f"{m} دقیقه")
    return " و ".join(parts[:2])


# پنجره‌های مجازِ «گذشتهٔ» فید (ساعت) — همان‌هایی که انتخابگرِ UI نشان می‌دهد.
PAST_WINDOWS = (6, 12, 24)


def past_window(v):
    """پنجرهٔ گذشته را به یکی از مقادیرِ مجازِ (۶/۱۲/۲۴) قطعی می‌کند.

    چرا: این مقدار از کوئریِ URL می‌آید (`?past=999`) و تقویمِ گذشته نباید با یک
    عددِ دلبخواهی تا بی‌نهایت بزرگ شود؛ نزدیک‌ترین پنجرهٔ مجاز انتخاب می‌شود.

    مرزِ عمدی: صفر (و منفی) یعنی **خاموش** — بدونِ رویدادِ گذشته، فقط پیشِ‌روها
    (قراردادِ دورِ ۷ که نباید بی‌صدا عوض شود). انتخابگرِ رابط فقط ۶/۱۲/۲۴
    می‌فرستد، پس این حالت فقط برای فراخوانیِ برنامه‌ای/تست است.
    """
    try:
        n = int(v)
    except Exception:
        return PAST_WINDOWS[0]
    if n <= 0:
        return 0
    if n in PAST_WINDOWS:
        return n
    return min(PAST_WINDOWS, key=lambda w: (abs(w - n), w))


def _calendar_snapshot():
    try: cal=M.get_calendar()
    except Exception as e:
        cal=SourceRows([], {"source":"forexfactory", "fetched_at":None,
                            "source_status":"unavailable", "error":str(e)})
    if not isinstance(cal, list):
        cal=SourceRows([], {"source":"forexfactory", "fetched_at":None,
                            "source_status":"unavailable", "error":"پاسخِ تقویم معتبر نیست"})
    return cal


def _event_datetime(value):
    utc=_parse_event_time(value)
    if utc is None: return None
    # Keep the existing ISO identity/offset; only naive ET needs localization.
    if isinstance(value, str):
        dt=datetime.datetime.fromisoformat(value)
        return utc.astimezone(ET) if dt.tzinfo is None else dt
    return utc


def _event_sort_key(ev):
    dt=_parse_event_time(ev.get("iso"))
    if dt is None: raise ValueError("زمانِ رویداد برای مرتب‌سازی معتبر نیست")
    return dt.timestamp()


def _feed_past_event(e, dt, now, ccy):
    """رویدادِ گذشتهٔ فید (عددش اعلام شده یا دارد می‌شود) — بی‌`analysis`ِ دوشاخه‌ای.

    چرا جدا: فید تا لحظهٔ اعلامِ خبر دو سناریوی شرطی («اگر بالاتر… / اگر پایین‌تر…»)
    نشان می‌دهد؛ از لحظهٔ اعلام باید خودکار به «نتیجهٔ قطعی + تأثیرِ همان نتیجه»
    سوییچ کند. با نساختنِ beat/miss در بار، رابط فیزیکاً نمی‌تواند گزارهٔ شرطی را
    برای این رویداد رندر کند (همان الگوی آرشیو). حکم (`verdict`) بعداً با
    `_attach_verdicts` تزریق می‌شود."""
    et = dt.astimezone(ET)
    teh = dt.astimezone(TEHRAN)
    cat, icon, _mode, _why = _classify(e.get("title"), ccy)
    return {
        "iso": dt.isoformat(),
        "title": e.get("title"),
        "title_fa": _title_fa(e.get("title")),
        "country": ccy,
        "country_fa": _ccy_fa(ccy),
        "icon": icon,
        "cat": cat,
        "impact": e.get("impact"),
        "forecast": (e.get("forecast") or "").strip(),
        "previous": (e.get("previous") or "").strip(),
        "et": f"{_FA_DAYS[et.weekday()]} {et.strftime('%H:%M')} به‌وقتِ نیویورک",
        "tehran": f"{_FA_DAYS[teh.weekday()]} {teh.strftime('%Y-%m-%d %H:%M')} به‌وقتِ تهران",
        "tehran_short": teh.strftime("%m-%d %H:%M"),
        "passed": True,
        "minutes_ago": round((now - dt).total_seconds() / 60),
    }


def build_feed(hours=180, min_impact="Medium", past_hours=6):
    """فهرستِ رویدادها از `past_hours` ساعتِ گذشته تا افقِ زمانی، مرتب بر زمان.

    رویدادهای **پیشِ رو**: دو سناریوی شرطی (`analysis`) — عدد هنوز اعلام نشده.
    رویدادهای **گذشته**: `passed=True` + حکمِ قطعی (`verdict`) با «نتیجه + تأثیرِ
    محقق» و **بی‌`analysis`** — فید بعد از اعلام، خودکار سوییچ می‌کند؛ نه دو
    سناریوی همیشگی."""
    cal = _calendar_snapshot()
    now = datetime.datetime.now(datetime.timezone.utc)
    cal_quality = _calendar_quality(cal, now=now)
    horizon = now + datetime.timedelta(hours=hours)
    floor = now - datetime.timedelta(hours=past_window(past_hours))
    want = {"High"} if min_impact == "High" else {"High", "Medium"}
    out, past = [], SourceRows()
    for e in cal:
        if not isinstance(e, dict): continue
        if e.get("impact") not in want:
            continue
        dt = _event_datetime(e.get("date"))
        if dt is None: continue
        if not (floor <= dt <= horizon):
            continue
        ccy = e.get("country")
        if dt < now:
            past.append(_feed_past_event(e, dt, now, ccy))
            past[-1]["calendar_quality"]=dict(cal_quality)
            continue
        et = dt.astimezone(ET)
        teh = dt.astimezone(TEHRAN)
        out.append({
            "iso": dt.isoformat(),
            "title": e.get("title"),
            "title_fa": _title_fa(e.get("title")),
            "country": ccy,
            "country_fa": _ccy_fa(ccy),
            "impact": e.get("impact"),
            "forecast": (e.get("forecast") or "").strip(),
            "previous": (e.get("previous") or "").strip(),
            "et": f"{_FA_DAYS[et.weekday()]} {et.strftime('%H:%M')} به‌وقتِ نیویورک",
            "tehran": f"{_FA_DAYS[teh.weekday()]} {teh.strftime('%Y-%m-%d %H:%M')} به‌وقتِ تهران",
            "tehran_short": teh.strftime("%m-%d %H:%M"),
            "in_hours": round((dt - now).total_seconds() / 3600, 1),
            # `in_s` ثانیه‌های **دقیق**ِ باقی‌مانده است (برخلافِ `in_hours` که
            # به یک‌دهمِ ساعت گرد می‌شود) — لنگرِ سوییچِ لحظه‌ایِ رابط: کارت
            # دقیقاً وقتی این به صفر رسید، از پیشِ‌رو به «اعلام‌شده» می‌رود.
            "in_s": int(max(0, (dt - now).total_seconds())),
            "countdown": _countdown_fa(dt - now),
            "passed": False,
            "calendar_quality": dict(cal_quality),
            "analysis": _analysis(e.get("title"), ccy),
        })
    if past:
        _attach_verdicts(past)  # «نتیجه + تأثیرِ محقق» برای رویدادهای اعلام‌شده
        out.extend(past)
    out.sort(key=_event_sort_key)
    return SourceRows(out, {"calendar_quality":cal_quality,
                            "source_quality":past.metadata.get("source_quality")})


# رقم‌های حرفی که «بهتر/بدتر» عددی معنا ندارند (کنترلِ صداقتِ حکم).
_VERDICT_SKIP_TOKENS = ("—", "-", "n/a", "na", "tbd")

# پسوندِ مقیاسِ عدد در منبعِ Actual/TE: «195K» · «1.2M» · «2.3B» · «1.4T».
_NUM_MULT = {"k": 1000.0, "m": 1000000.0, "b": 1000000000.0, "t": 1000000000000.0}


def _num(v):
    """Strict finite scalar, preserving scale suffixes and valid signed values."""
    if isinstance(v, bool): return None
    if isinstance(v, (int, float)):
        try: return float(v) if math.isfinite(v) else None
        except (ValueError, OverflowError): return None
    if not isinstance(v, str): return None
    s = v.strip().lower()
    if not s or s in _VERDICT_SKIP_TOKENS:
        return None
    if s.endswith("%"):
        s=s[:-1].strip()
    if "%" in s: return None
    mult = 1.0
    if s[-1:] in _NUM_MULT:
        mult = _NUM_MULT[s[-1:]]
        s = s[:-1].strip()
    if not s:
        return None
    # Commas are thousands separators, not an invitation to change "1,2" to 12.
    if not re.fullmatch(r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?", s):
        return None
    try:
        value=float(s.replace(",", ""))*mult
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError): return None


def _text(v):
    return v.strip() if isinstance(v, str) else str(v) if isinstance(v, (int, float)) else ""


def _quantity(v):
    """Finite scalar/interest-rate interval with an explicit comparable unit.

    No midpoint/upper-bound guess for a target range. A unitless TE number
    cannot silently inherit %/K from an FF forecast.
    """
    scalar=_num(v)
    if scalar is not None:
        s=_text(v).lower()
        unit="percent" if s.endswith("%") else "count" if s[-1:] in _NUM_MULT else "plain"
        if unit=="percent" and s[:-1].strip()[-1:] in _NUM_MULT: return None
        return {"low":scalar, "high":scalar, "unit":unit}
    if not isinstance(v, str): return None
    number=r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
    match=re.fullmatch(r"\s*("+number+r")\s*(%?)\s*[-–—]\s*("+number+r")\s*(%?)\s*", v)
    if not match: return None
    # A final % applies to the whole interval; a left-only % is ambiguous.
    if match.group(2) and not match.group(4): return None
    low, high=_num(match.group(1)), _num(match.group(3))
    if low is None or high is None or low>high: return None
    return {"low":low, "high":high, "unit":"percent" if match.group(4) else "plain"}


def _realized_effect(ccy, direction):
    """Compatibility name: inferred currency pressure, not measured price action."""
    if ccy not in _CCY_FA or ccy=="All" or direction not in ("قوی‌تر", "ضعیف‌تر"):
        return {"pairs": [], "gold": None}  # جهت نامعلوم ⇒ اثر نمی‌سازیم (حدس ممنوع)
    pairs, gold = _pair_effect(ccy, strong=(direction == "قوی‌تر"))
    return {"pairs": pairs, "gold": gold}


def _verdict(actual, forecast, previous, mode, ccy=None):
    """Actual vs forecast surprise and inferred pressure, NOT observed price action.

    Preserve the existing found/dir/outcome/effect contract, but leave direction
    empty for missing/ambiguous units, overlapping rate intervals or an unknown
    indicator. Previous values never substitute for a missing forecast.
    """
    a, f=_quantity(actual), _quantity(forecast)
    res={"found":a is not None, "actual":_text(actual) if a is not None else "",
         "forecast":_text(forecast), "previous":_text(previous),
         "outcome":"", "dir":"", "beat":"", "status":"UNKNOWN",
         "basis":"actual_vs_forecast", "market_reaction_observed":False,
         "effect":{"pairs":[], "gold":None}}
    if a is None:
        res["reason"]="عددِ متناهی و معتبرِ اعلام‌شده در دسترس نیست"
        return res
    if f is None:
        res["beat"]="انتظارِ عددی ثبت نشده بود"
        res["reason"]="بدونِ پیش‌بینیِ عددی، جهت نامعلوم است"
    elif a["unit"]!=f["unit"]:
        res["reason"]="واحد یا مقیاسِ اعلام‌شده و پیش‌بینی هم‌خوان نیست"
    elif mode not in ("normal", "inverse"):
        res["reason"]="تفسیرِ جهتِ شاخص یا لحنِ خبر معلوم نیست"
    elif a["low"]==f["low"] and a["high"]==f["high"]:
        res.update(beat="دقیقاً طبقِ انتظار", dir="طبقِ انتظار", outcome="خنثی", status="AS_EXPECTED")
    elif a["low"]>f["high"] or a["high"]<f["low"]:
        higher=a["low"]>f["high"]
        strong=higher if mode=="normal" else not higher
        res.update(beat="بالاتر از انتظار" if higher else "پایین‌تر از انتظار",
                   dir="قوی‌تر" if strong else "ضعیف‌تر",
                   outcome="صعودی" if strong else "نزولی", status="INFERRED")
    else:
        res["reason"]="بازهٔ نرخ با انتظار هم‌پوشانی دارد؛ جهت را از میانگین یا کران حدس نمی‌زنیم"
    res["effect"] = _realized_effect(ccy, res.get("dir") or "")
    return res


def _attach_verdicts(events):
    """Require a fresh source and unique currency/time/title identity for Actual.

    ±10m is only a scheduling tolerance, not permission to guess between core/
    headline, periods, regions, surveys or conflicting rows. Missing identity,
    stale data and ambiguous matches remain explicitly UNKNOWN.
    """
    try: rows = M.get_actuals()
    except Exception: rows = []
    quality=_actuals_quality(rows)
    src_ok=quality["ok"]
    rows=rows if isinstance(rows, list) else []
    if isinstance(events, SourceRows): events.metadata["source_quality"]=dict(quality)
    for ev in events:
        if not isinstance(ev, dict): continue
        v=_verdict("", ev.get("forecast"), ev.get("previous"), "unknown", ev.get("country"))
        v["source_quality"]=dict(quality)
        dt=_parse_event_time(ev.get("iso"))
        cal_quality=ev.get("calendar_quality")
        if not src_ok:
            v["reason"]=quality["reason"]
        elif isinstance(cal_quality, dict) and not cal_quality.get("ok"):
            v["reason"]=cal_quality.get("reason") or "تقویمِ تازه معتبر نیست"
        elif dt is None or not ev.get("title") or not ev.get("country"):
            v["reason"]="هویت یا زمانِ رویداد معلوم نیست"
        else:
            candidates={}
            for r in rows:
                if r.get("ccy")!=ev.get("country") or not _titles_match(r.get("event"), ev.get("title")):
                    continue
                release=datetime.datetime.combine(datetime.date.fromisoformat(r["date"]),
                                                   datetime.time(), datetime.timezone.utc)
                release+=datetime.timedelta(minutes=r["minute"])
                if abs((release-dt).total_seconds())>10*60: continue
                identity=(r["date"], r["minute"], tuple(sorted(_title_tokens(r["event"]))), _text(r.get("actual")))
                candidates[identity]=r
            if len(candidates)==1:
                r=next(iter(candidates.values()))
                _cat, _icon, mode, _why=_classify(ev.get("title"), ev.get("country"))
                # FF supplies the user's forecast; TE supplies only this unique Actual.
                v=_verdict(r.get("actual"), ev.get("forecast"), ev.get("previous"), mode, ev.get("country"))
                v["source_quality"]=dict(quality)
                v["match"]={"event":r.get("event"), "date":r["date"], "minute":r["minute"]}
            else:
                v["reason"]="تطبیقِ نتیجه مبهم است" if candidates else "نتیجهٔ همان رویداد از منبع نرسیده است"
        ev["verdict"]=v
    return src_ok


def _title_tokens(title):
    """Small explicit aliases, preserving period/core/survey/stage/geography."""
    if not isinstance(title, str): return set()
    t=title.lower().strip()
    if not t: return set()
    for pattern, replacement in (
        (r"\by\s*/\s*y\b|\byear[ -]over[ -]year\b", " yoy "),
        (r"\bm\s*/\s*m\b|\bmonth[ -]over[ -]month\b", " mom "),
        (r"\bq\s*/\s*q\b|\bquarter[ -]over[ -]quarter\b", " qoq "),
        (r"\bconsumer price index\b", "cpi"),
        (r"\bproducer price index\b", "ppi"),
        (r"\bfederal funds rate\b|\bfed interest rate decision\b", "fed policy rate"),
        (r"\bnon[ -]?farm (?:employment change|payrolls?)\b", "payrolls"),
        (r"\bism non[ -]manufacturing\b", "ism services"),
        (r"\bunemployment claims\b|\binitial jobless claims\b", "initial claims"),
    ):
        t=re.sub(pattern, replacement, t)
    tokens=set(re.findall(r"[a-z0-9]+", t))
    tokens.discard("index")
    # Legacy TE shorthand is explicitly supported, not general one-word overlap.
    if "ppi" in tokens: tokens.discard("manufacturing")
    return tokens


def _titles_match(te_name, ff_title):
    te, ff=_title_tokens(te_name), _title_tokens(ff_title)
    return bool(te and ff and te==ff)


def archive(hours=6):
    """آرشیوِ اخبارِ اعلام‌شده در `hours` ساعتِ گذشته — با **حکمِ قطعیِ نتیجه**.

    هر رویدادِ گذشته‌ای که عددِ اعلام‌شده‌اش (Actual) از منبعِ مکمل درآمده باشد،
    «عدد + بالاتر/پایین‌تر از انتظار + صعودی/نزولی (قوی/ضعیف‌شدنِ ارز) + تأثیرِ
    همین نتیجه روی جفت‌ارزها/طلا» می‌گیرد؛ چون خبر اعلام شده، دیگر حدس و گزاره‌ی
    شرطی در کار نیست (نه شاخهٔ «اگر بالاتر شد» و نه «اگر پایین‌تر شد»). اگر منبعِ
    اعلام‌شده در دسترس نباشد، همان حالتِ شفافِ «نامعلوم» برمی‌گردد (هرگز حدس نمی‌زنیم)."""
    cal = _calendar_snapshot()
    now = datetime.datetime.now(datetime.timezone.utc)
    cal_quality = _calendar_quality(cal, now=now)
    start = now - datetime.timedelta(hours=max(1, int(hours)))
    out = SourceRows()
    for e in cal:
        if not isinstance(e, dict): continue
        if e.get("impact") not in ("High", "Medium"):
            continue
        dt = _event_datetime(e.get("date"))
        if dt is None: continue
        if not (start <= dt <= now):
            continue
        teh = dt.astimezone(TEHRAN)
        ccy = e.get("country")
        # عمداً `analysis`ِ دو‌شاخه‌ای (beat/miss = «اگر بالا/پایین شد») اینجا نیست:
        # پنجرهٔ آرشیو بعد از اعلامِ خبر است، پس فقط آیکن/شاخهٔ دسته را می‌فرستیم و
        # «نتیجه + تأثیرِ محقق» از `verdict` می‌آید. خبرهای **پیش‌رو** (build_feed)
        # همچنان همان دو سناریو را دارند، چون عددشان هنوز اعلام نشده.
        _cat, icon, _mode, _why = _classify(e.get("title"), ccy)
        out.append({
            "iso": dt.isoformat(),
            "title": e.get("title"),
            "title_fa": _title_fa(e.get("title")),
            "country": ccy,
            "country_fa": _ccy_fa(ccy),
            "icon": icon,
            "impact": e.get("impact"),
            "forecast": (e.get("forecast") or "").strip(),
            "previous": (e.get("previous") or "").strip(),
            "when_fa": f"{_FA_DAYS[teh.weekday()]} {teh.strftime('%H:%M')} به‌وقتِ تهران",
            "calendar_quality": dict(cal_quality),
            "minutes_ago": round((now - dt).total_seconds() / 60),
        })
    out.sort(key=_event_sort_key, reverse=True)
    src_ok = _attach_verdicts(out)
    now_teh = datetime.datetime.now(TEHRAN)
    return {
        "ok": True,
        "hours": int(hours),
        "generated_tehran": f"{_FA_DAYS[now_teh.weekday()]} {now_teh.strftime('%Y-%m-%d %H:%M')} تهران",
        "count": len(out),
        "verdicts": sum(1 for e in out if (e.get("verdict") or {}).get("found")),
        "source_ok": src_ok,
        "source_quality": out.metadata.get("source_quality"),
        "calendar_quality": cal_quality,
        "events": out,
        "note": ("هر خبر فقط «نتیجه‌ی قطعیِ اعلام‌شده» + «تأثیرِ همان نتیجه» را دارد "
                 "(عددِ Actual + صعودی/نزولی + اثرش روی جفت‌ارزها/طلا)؛ چون خبر اعلام "
                 "شده، گزاره‌ی شرطی («اگر بالاتر شد → …») در این پنجره جایی ندارد. اگر "
                 "عددِ اعلام‌شده در دسترس نباشد، همان خبر نامعلوم اعلام می‌شود. "
                 "پنجرهٔ گذشته ۶/۱۲/۲۴ ساعت و از انتخابگرِ UI قابلِ تغییر است."),
    }


def build(hours=180, past_hours=6):
    past_hours = past_window(past_hours)
    feed = build_feed(hours=hours, past_hours=past_hours)
    # «نزدیک‌ترین خبرِ پرتأثیر» فقط از میانِ رویدادهای پیشِ‌رو است؛ رویدادِ
    # اعلام‌شده دیگر «نزدیک‌ترین» نیست — نتیجه‌اش گرفته شده و در فهرست می‌مانَد.
    highs = [e for e in feed if e["impact"] == "High" and not e.get("passed")]
    passed = [e for e in feed if e.get("passed")]
    source_quality = feed.metadata.get("source_quality")
    src_ok = bool(source_quality and source_quality.get("ok")) if passed else None
    now_teh = datetime.datetime.now(TEHRAN)
    return {
        "generated_tehran": f"{_FA_DAYS[now_teh.weekday()]} {now_teh.strftime('%Y-%m-%d %H:%M')} تهران",
        "count": len(feed),
        "count_past": len(passed),
        "past_hours": past_hours,
        "count_high": len(highs),
        "next_high": highs[0] if highs else None,
        "source_ok": src_ok,
        "source_quality": source_quality,
        "calendar_quality": feed.metadata.get("calendar_quality"),
        "events": feed,
        "note": ("آنچه بازار را تکان می‌دهد «انحراف از پیش‌بینی» است، نه خودِ عدد. دورِ "
                 "±۱۵ تا ۳۰ دقیقه‌ی هر خبرِ پرتأثیر، ورودِ تازه ممنوع؛ اجازه بده فِیک‌اوتِ اولیه پاک شود. "
                 "خبری که عددش اعلام شده، از دو سناریو به «نتیجه + تأثیرِ محقق» سوییچ می‌کند."),
    }


def one_event(iso, hours=180, past_hours=6):
    """بارِ تازهٔ یک رویداد + «نزدیک‌ترین خبرِ پرتأثیر» — برای سوییچِ لحظه‌ایِ فید.

    چرا: فید هر ۶۰ ثانیه یک‌بار کامل خوانده می‌شود؛ برای این‌که کارتِ پیشِ‌رو
    دقیقاً در لحظهٔ رسیدنِ شمارشِ معکوس به صفر سوییچ کند، رابط فقط همین یک
    رویداد را می‌پرسد (سبک، بدونِ بازخوانیِ کلِ فهرست و بدونِ رفرشِ صفحه).

    اگر ساعتِ مرورگر کمی جلوتر باشد، رویداد هنوز در فیدِ سرور «پیشِ‌رو» است و
    همان بارِ پیشِ‌رو (`passed=False`، با سناریوها) برمی‌گردد تا رابط ادعای
    اعلامِ زودرس نکند. رویدادِ بیرونِ پنجره ⇒ `event=None`.
    """
    iso = (iso or "").strip()
    past_hours = past_window(past_hours)
    feed = build_feed(hours=hours, past_hours=past_hours)
    ev = next((e for e in feed if e.get("iso") == iso), None)
    highs = [e for e in feed if e["impact"] == "High" and not e.get("passed")]
    return {
        "iso": iso,
        "event": ev,
        "next_high": highs[0] if highs else None,
        "past_hours": past_hours,
        "calendar_quality": feed.metadata.get("calendar_quality"),
        "source_quality": feed.metadata.get("source_quality"),
        "generated_tehran": f"{_FA_DAYS[datetime.datetime.now(TEHRAN).weekday()]} "
                            f"{datetime.datetime.now(TEHRAN).strftime('%Y-%m-%d %H:%M')} تهران",
    }


if __name__ == "__main__":
    import json, sys
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    print(json.dumps(build(hours), ensure_ascii=False, indent=2))
