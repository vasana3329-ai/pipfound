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
import re
import macro_context as M

ET = datetime.timezone(datetime.timedelta(hours=-4))          # New York (طبقِ macro_context)
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
    # نرخِ بهره / بیانیه‌ی بانکِ مرکزی — بالاترین تأثیر
    if any(k in t for k in ("rate statement", "cash rate", "overnight rate",
                            "monetary policy", "rate decision", "interest rate")):
        return ("نرخِ بهره", "🏦", "normal",
                "تصمیمِ نرخِ بهره و لحنِ بیانیه، پرتأثیرترین محرکِ ارز است. نرخِ بالاتر از "
                "انتظار یا لحنِ هاوکیش (نگرانِ تورم) ارز را قوی می‌کند؛ لحنِ داویش (نگرانِ رشد) ضعیف.")
    if any(k in t for k in ("press conference", "speaks", "testimony", "statement")):
        return ("سخنرانیِ مقامِ پولی", "🎙️", "normal",
                "بازار دنبالِ سرنخِ لحن است (هاوکیش/داویش). جمله‌های غیرمنتظره می‌تواند بیش از خودِ "
                "دیتا نوسان بسازد؛ زمان‌بندیِ دقیق و بی‌ثبات.")
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
    return ("رویدادِ اقتصادی", "🗓️", "normal",
            "رویدادِ تقویمِ اقتصادی؛ به انحراف از پیش‌بینی و لحنِ همراهش توجه کن.")


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


def build_feed(hours=180, min_impact="Medium"):
    """فهرستِ رویدادهای High (+ Medium) در افقِ زمانی، مرتب بر زمان، همراهِ تحلیل."""
    cal = M.get_calendar()
    now = datetime.datetime.now(datetime.timezone.utc)
    horizon = now + datetime.timedelta(hours=hours)
    want = {"High"} if min_impact == "High" else {"High", "Medium"}
    out = []
    for e in cal:
        if e.get("impact") not in want:
            continue
        try:
            dt = datetime.datetime.fromisoformat(e["date"])  # aware (offset در رشته)
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ET)
        if not (now <= dt <= horizon):
            continue
        et = dt.astimezone(ET)
        teh = dt.astimezone(TEHRAN)
        ccy = e.get("country")
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
            "countdown": _countdown_fa(dt - now),
            "analysis": _analysis(e.get("title"), ccy),
        })
    out.sort(key=lambda x: x["iso"])
    return out


# رقم‌های حرفی که «بهتر/بدتر» عددی معنا ندارند (کنترلِ صداقتِ حکم).
_VERDICT_SKIP_TOKENS = ("—", "-", "n/a", "na", "tbd")


def _num(v):
    """«3.6%»/«15.2%»/«1,234K» → شماره؛ نشدن → None (بدونِ حدس)."""
    s = (v or "").replace(",", "").replace("%", "").strip().lower()
    if not s or any(tok in s for tok in _VERDICT_SKIP_TOKENS):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _verdict(actual, forecast, previous, mode):
    """حکمِ قطعیِ «نتیجه» از عددِ اعلام‌شده — نه گزاره‌ی شرطی.

    برمی‌گرداند: found (عددِ اعلام‌شده در دسترس است)، dir (قوی‌تر/ضعیف‌ترِ ارز)،
    outcome (صعودی/نزولی برای همان ارز)، and beat (بالاتر/پایین‌تر از انتظار).
    مقایسه فقط با پیش‌بینیِ عددی است؛ اگر پیش‌بینی یا اعلام‌شده عدد نبود، حکمِ
    «نامعلوم» صادر می‌شود (هرگز حدس نمی‌زنیم)."""
    a, f, p = _num(actual), _num(forecast), _num(previous)
    if a is None:
        return {"found": False, "outcome": "", "dir": "", "beat": ""}
    res = {"found": True, "actual": (actual or "").strip()}
    if f is None:
        # عدد اعلام شده ولی انتظارِ عددی نبوده: جهت را نمی‌سازیم (حدس ممنوع).
        res["beat"] = "انتظارِ عددی ثبت نشده بود"
        res["dir"] = ""
        res["outcome"] = ""
    else:
        if a > f:
            res["beat"] = "بالاتر از انتظار"
            res["dir"] = "ضعیف‌تر" if mode == "inverse" else "قوی‌تر"
        elif a < f:
            res["beat"] = "پایین‌تر از انتظار"
            res["dir"] = "قوی‌تر" if mode == "inverse" else "ضعیف‌تر"
        else:
            res["beat"] = "دقیقاً طبقِ انتظار"
            res["dir"] = "طبقِ انتظار"
        res["outcome"] = ("صعودی" if res["dir"] == "قوی‌تر"
                          else "نزولی" if res["dir"] == "ضعیف‌تر" else "خنثی")
    res["forecast"] = (forecast or "").strip()
    res["previous"] = (previous or "").strip()
    return res


def _attach_verdicts(events):
    """تزریقِ «حکمِ قطعی» به هر رویدادِ گذشته: تطبیقِ FF×TE روی (کشور، تاریخِ GMT،
    دقیقه‌ی GMT ±۱۰)؛ عددِ اعلام‌شده فقط از منبعِ ستونِ Actual می‌آید و اگر منبع
    در دسترس نبود، حکمِ «منبعِ اعلام‌شده در دسترس نبود» می‌مانَد — نه گزاره‌ی شرطی."""
    try:
        rows = M.get_actuals() or []
    except Exception:
        rows = []
    src_ok = bool(rows)
    for ev in events:
        try:
            dt = datetime.datetime.fromisoformat(ev["iso"])
        except Exception:
            continue
        utc = dt.astimezone(datetime.timezone.utc)
        minute = utc.hour * 60 + utc.minute
        v = {"found": False, "outcome": "", "dir": "", "beat": "",
             "actual": "", "forecast": "", "previous": ""}
        for r in rows:
            if (r.get("ccy") != ev.get("country") or r.get("date") != utc.date().isoformat()
                    or r.get("minute") is None or abs(r["minute"] - minute) > 10):
                continue
            if r.get("event") and ev.get("title") and not _titles_match(r["event"], ev["title"]):
                continue  # چند خبر در همان دقیقه؛ نام نزدیک‌ترین است
            an = _analysis(ev.get("title"), ev.get("country"))
            # مقایسه با پیش‌بینیِ «همان تقویمی که کاربر دیده» (FF)؛ TE فقط عددِ Actual.
            v = _verdict(r.get("actual"), (ev.get("forecast") or "").strip(),
                         (ev.get("previous") or "").strip(),
                         (an.get("cat") and an.get("mode")) or "normal")
            break
        ev["verdict"] = v
    return src_ok


def _titles_match(te_name, ff_title):
    """نامِ کوتاهِ TE («ppi yoy») با عنوانِ FF («Manufacturing PPI y/y») هم‌خوان شمرده شود.
    تطبیقِ واژه‌محور؛ فقط برای ردِّ نامشابه‌ها، نه برای ساختنِ حکم."""
    te = set(re.findall(r"[a-z0-9]+", (te_name or "").lower()))
    ff = set(re.findall(r"[a-z0-9]+", (ff_title or "").lower()))
    if not te or not ff:
        return True  # نبودِ نام ⇒ صرفِ زمان/کشور
    return bool(te & ff)


def archive(hours=6):
    """آرشیوِ اخبارِ اعلام‌شده در `hours` ساعتِ گذشته — با **حکمِ قطعیِ نتیجه**.

    هر رویدادِ گذشته‌ای که عددِ اعلام‌شده‌اش (Actual) از منبعِ مکمل درآمده باشد،
    «عدد + بالاتر/پایین‌تر از انتظار + صعودی/نزولی (قوی/ضعیف‌شدنِ ارز)» می‌گیرد؛
    چون خبر اعلام شده، دیگر حدس و گزاره‌ی شرطی در کار نیست. اگر منبعِ اعلام‌شده
    در دسترس نباشد، همان حالتِ شفافِ «نامعلوم» برمی‌گردد (هرگز حدس نمی‌زنیم)."""
    cal = M.get_calendar()
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(hours=max(1, int(hours)))
    out = []
    for e in cal:
        if e.get("impact") not in ("High", "Medium"):
            continue
        try:
            dt = datetime.datetime.fromisoformat(e["date"])
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ET)
        if not (start <= dt <= now):
            continue
        teh = dt.astimezone(TEHRAN)
        ccy = e.get("country")
        out.append({
            "iso": dt.isoformat(),
            "title": e.get("title"),
            "title_fa": _title_fa(e.get("title")),
            "country": ccy,
            "country_fa": _ccy_fa(ccy),
            "impact": e.get("impact"),
            "forecast": (e.get("forecast") or "").strip(),
            "previous": (e.get("previous") or "").strip(),
            "when_fa": f"{_FA_DAYS[teh.weekday()]} {teh.strftime('%H:%M')} به‌وقتِ تهران",
            "minutes_ago": round((now - dt).total_seconds() / 60),
            "analysis": _analysis(e.get("title"), ccy),
        })
    out.sort(key=lambda x: x["iso"], reverse=True)
    src_ok = _attach_verdicts(out)
    now_teh = datetime.datetime.now(TEHRAN)
    return {
        "ok": True,
        "hours": int(hours),
        "generated_tehran": f"{_FA_DAYS[now_teh.weekday()]} {now_teh.strftime('%Y-%m-%d %H:%M')} تهران",
        "count": len(out),
        "verdicts": sum(1 for e in out if (e.get("verdict") or {}).get("found")),
        "source_ok": src_ok,
        "events": out,
        "note": ("حکمِ هر خبر «نتیجه‌ی قطعیِ اعلام‌شده» است (عددِ Actual + صعودی/نزولی)، "
                 "نه گزاره‌ی شرطی؛ چون خبر اعلام شده. اگر عددِ اعلام‌شده در دسترس نباشد، "
                 "همان خبر نامعلوم اعلام می‌شود."),
    }


def build(hours=180):
    feed = build_feed(hours=hours)
    highs = [e for e in feed if e["impact"] == "High"]
    now_teh = datetime.datetime.now(TEHRAN)
    return {
        "generated_tehran": f"{_FA_DAYS[now_teh.weekday()]} {now_teh.strftime('%Y-%m-%d %H:%M')} تهران",
        "count": len(feed),
        "count_high": len(highs),
        "next_high": highs[0] if highs else None,
        "events": feed,
        "note": ("آنچه بازار را تکان می‌دهد «انحراف از پیش‌بینی» است، نه خودِ عدد. دورِ "
                 "±۱۵ تا ۳۰ دقیقه‌ی هر خبرِ پرتأثیر، ورودِ تازه ممنوع؛ اجازه بده فِیک‌اوتِ اولیه پاک شود."),
    }


if __name__ == "__main__":
    import json, sys
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    print(json.dumps(build(hours), ensure_ascii=False, indent=2))
