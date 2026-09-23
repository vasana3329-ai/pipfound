#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SMT دایورجنس (Smart Money Tool) — شکستِ همبستگی بین دو نمادِ همبسته.

منشأ: درخواستِ کاربر برای افزودنِ ستاپِ ویدیوی «The Ultimate Day Trading Plan»
(youtu.be/pCZ1I1EG_Zw). آن مدل سه شرط دارد: سوئیپِ لیکوئیدیتی در ساعتِ درستِ
سشن، دلیوریِ HTF، و دایورجنسِ SMT بین جفت‌های همبستهٔ *درست*. دو شرطِ اول را
موتورِ موجود (sweeps + killzone) می‌سنجد؛ این ماژول همان شرطِ سوم است.

چیستیِ SMT (تعریفِ خودِ ویدیو — دقیق پیاده شده، نه کمتر):
  خرسی: نمادِ اول سقفِ بالاتر (HH) می‌سازد و لیکوئیدیتیِ خرید را می‌گیرد،
        درحالی‌که نمادِ همبسته سقفِ پایین‌تر (LH) می‌سازد و لیکوئیدیتی‌اش
        دست‌نخورده می‌ماند → شکستِ همبستگی → برگشتِ نزولیِ محتمل.
  صعودی: برعکسش — کفِ پایین‌تر + سوئیپ در برابرِ کفِ بالاتر.

همه‌چیز **آفلاین و قطعی** است: دو آرایهٔ کندلِ ازپیش‌دانلودشده می‌گیرد و روی
سوئینگ‌های فرکتالی (همان `swings` موتور، پس دو جای مختلف دو جواب نمی‌دهد)
کار می‌کند. هیچ شبکه‌ای این‌جا نیست؛ دانلودِ نمادِ دوم وظیفهٔ صداکننده است.

نکتهٔ حرفه‌ای که در API هم برمی‌گردد (از خودِ ویدیو): بعد از SMT، ورود را روی
نمادی بگیر که **خودش سوئیپ را انجام داده** — سوئیپ‌کننده تأییدِ دستکاری را
دارد و مسیرِ تمیزتر به لیکوئیدیتیِ مقابل.

جدولِ جفت‌ها (JFIGURES): فقط جفت‌هایی که همبستگیِ ساختاریِ شناخته‌شده دارند:
  EURUSD↔GBPUSD (اروپایی‌های دلاری) · AUDUSD↔NZDUSD (کامودال‌های دلاری) ·
  SPX500↔NAS100 (شاخصِ آمریکا) · XAUUSD↔XAGUSD (فلزات) · US30↔SPX500.
DXY هم به‌عنوانِ مرجعِ بایاسِ دلار برای همهٔ جفت‌های اصلیِ دلاری سرو می‌شود
(فقط به‌عنوانِ زمینه، نه نیمِ یک جفتِ SMT).
"""
import datetime

# جفت‌های همبستهٔ معتبر — ترتیبِ مهم نیست؛ سفارشِ خروجیِ map با آرایهٔ زیر حفظ می‌شود.
SMT_PAIRS = [
    ("EURUSD", "GBPUSD"),
    ("AUDUSD", "NZDUSD"),
    ("USDCAD", "USDCHF"),          # هر دو «دلار در مقابلِ ارزِ امن/نفت» — همبستگیِ منفیِ شناخته‌شده به همدیگرِ آینه‌ایِ دلاری
    ("SPX500", "NAS100"),
    ("US30", "SPX500"),
    ("XAUUSD", "XAGUSD"),
    ("WTI", "BRENT"),
]

# نمادِ مرجعِ بایاسِ دلار — برای جفت‌های دلاریِ خارج از جدولِ بالا پیشنهاد می‌شود.
DXY_REF = "DXY"

_PAIR_MAP = {}
for _a, _b in SMT_PAIRS:
    _PAIR_MAP.setdefault(_a, []).append(_b)
    _PAIR_MAP.setdefault(_b, []).append(_a)


def partners(symbol):
    """جفت(های) همبستهٔ یک نماد از جدول؛ خالی = جفتِ ساختاریِ شناخته‌شده ندارد."""
    return list(_PAIR_MAP.get((symbol or "").upper().strip(), []))


def _last_two_swings_of_kind(sw, kind):
    """دو سوئینگِ آخر از یک نوع (H یا L) — به‌ترتیبِ زمانی."""
    sel = [(i, p) for i, p, t in sw if t == kind]
    return sel[-2:]


def smt_divergence(symbol, symbol_bars, partner, partner_bars, direction):
    """دایورجنسِ SMT را روی *آخرین* دو سوئینگِ هم‌نوع می‌سنجد.

    direction: ‎+1 برای سناریوی صعودی (کف‌ها را مقایسه می‌کند: نمادِ اول کفِ
    پایین‌تر/سوئیپِ فروش، نمادِ دوم کفِ بالاتر)؛ ‎-1 برای سناریوی خرسی
    (سقف‌ها: نمادِ اول سقفِ بالاتر/سوئیپِ خرید، نمادِ دوم سقفِ پایین‌تر).

    هر دو آرایه باید لیستی از dict با کلیدهای t/h/l/c باشند (همان خروجیِ
    fetch موتور) و فقط کندلِ بسته داشته باشند. `swings` با n=2 یعنی هر سوئینگ
    دو کندلِ تأیید از هر طرف می‌خواهد — پس خروجی «تأییدشده» است، نه لحظه‌ای.

    برمی‌گرداند dict با: diverged (bool)، highs/lowsِ هر دو، و توضیحِ فارسی.
    هیچ استثنایی بیرون نمی‌دهد — دادهٔ ناکافی = diverged=False با دلیل.
    """
    sym = (symbol or "").upper().strip()
    prt = (partner or "").upper().strip()
    if direction not in (1, -1):
        return {"diverged": False, "reason": "جهتِ نامعتبر"}
    if not symbol_bars or not partner_bars:
        return {"diverged": False, "reason": "دادهٔ یکی از دو نماد خالی است"}

    def sw_of(bars):
        # واردکردنِ دیرهنگام برای شکستنِ چرخهٔ import با smc_engine در تست‌ها
        from smc_engine import swings
        return swings(bars, 2)

    try:
        sw_a = sw_of(symbol_bars)
        sw_b = sw_of(partner_bars)
    except Exception as e:  # دادهٔ خیلی کوتاه (< ۵ کندل) → بدونِ SMT
        return {"diverged": False, "reason": f"سوئینگِ کافی نیست ({e})"}

    kind = "L" if direction == 1 else "H"
    a = _last_two_swings_of_kind(sw_a, kind)
    b = _last_two_swings_of_kind(sw_b, kind)
    base = {
        "symbol": sym, "partner": prt,
        "direction": "bullish" if direction == 1 else "bearish",
    }
    if len(a) < 2 or len(b) < 2:
        return {**base, "diverged": False,
                "reason": "هر نماد باید حداقل دو سوئینگِ تأییدشده داشته باشد"}

    # «هم‌دوره» یعنی *هم‌فازیِ بازار*، نه timestampِ مطلق: آخرین سوئینگِ هر
    # نماد باید نسبت به انتهای دادهٔ *خودش* به همان اندازه تازه باشد (تأییدِ
    # سوئینگِ فرکتالی n=2 خودش ≥۲ کندل از انتها فاصله می‌گذارد). مقایسهٔ
    # مطلقِ زمان اینجا می‌شکند چون دو فید سالم می‌توانند طولِ متفاوتی داشته
    # باشند (کندلِ جامانده) درحالی‌که همان فاز را توصیف می‌کنند؛ و زمانِ
    # نزدیک با فازِ متفاوت را هم به‌اشتباه می‌پذیرفت. تلورانس: ۴ کندلِ
    # پایه، یا نصفِ فاصلهٔ سوئینگ‌های خودشان — هر کدام بزرگ‌تر است.
    gap_a = a[1][0] - a[0][0]
    gap_b = b[1][0] - b[0][0]
    recency_a = (len(symbol_bars) - 1) - a[1][0]
    recency_b = (len(partner_bars) - 1) - b[1][0]
    tol_bars = max(4, int(0.5 * max(gap_a, gap_b)))
    if abs(recency_a - recency_b) > tol_bars:
        return {**base, "diverged": False,
                "reason": "آخرین سوئینگ‌های دو نماد هم‌فاز نیستند — مقایسه معتبر نیست"}

    a_prev, a_last = a[0][1], a[1][1]
    b_prev, b_last = b[0][1], b[1][1]

    if direction == 1:
        # صعودی: نمادِ اول کفِ پایین‌تر (سوئیپِ فروش)، نمادِ دوم کفِ بالاتر
        a_extreme = a_last < a_prev
        b_hold = b_last > b_prev
        # «سوئیپ» فقط وقتی معنا دارد که اکسترممِ جدید از سوئینگِ *قبل‌تر* هم رد
        # شود (در ویدیو: لیکوئیدیتیِ زیرِ کفِ قبلی گرفته شد) — نه فقط یک LL.
        all_a = [p for _i, p in a]
        a_sweep = (a_extreme and len(all_a) >= 2 and a_last < min(all_a[:-1]))
        all_b = [p for _i, p in b]
        b_sweep = (b_hold and len(all_b) >= 2 and b_last < min(all_b[:-1]))
    else:
        # خرسی: نمادِ اول سقفِ بالاتر (سوئیپِ خرید)، نمادِ دوم سقفِ پایین‌تر
        a_extreme = a_last > a_prev
        b_hold = b_last < b_prev
        all_a = [p for _i, p in a]
        a_sweep = (a_extreme and len(all_a) >= 2 and a_last > max(all_a[:-1]))
        # سوئیپِ نمادِ دوم فقط اگر خودش لیکوئیدیتیِ *خرید* را برده باشد؛
        # در حالتِ LH (نگه‌داشتنِ سقف) این ممکن نیست → other_sweep = False.
        all_b = [p for _i, p in b]
        b_sweep = (b_hold and len(all_b) >= 2 and b_last > max(all_b[:-1]))

    # جهتِ حرکتِ هر سوئینگ باید در *هر دو* نمادِ هم‌نوع بررسی شود؛ شرطِ SMT:
    # یکی اکسترممِ جدید می‌زند و دیگری رهایش می‌کند.
    diverged = a_extreme and b_hold
    a_txt = ("HH" if a_last > a_prev else "LL") if kind == "H" else \
            ("HL" if a_last > a_prev else "LL")
    b_txt = ("HH" if b_last > b_prev else "LH") if kind == "H" else \
            ("HL" if b_last > b_prev else "LL")
    why = (
        f"SMTِ {'صعودی' if direction == 1 else 'خرسی'} بین {sym} و {prt}: "
        f"{sym} {'سقفِ بالاتر' if a_last>a_prev and kind=='H' else 'کفِ پایین‌تر' if a_last<a_prev and kind=='L' else 'هم‌سطحِ سوئینگِ قبل'} "
        f"({a_txt}{' — سوئیپِ لیکوئیدیتی' if a_sweep else ''}) و {prt} "
        f"{'سقفِ پایین‌تر (LH)' if kind=='H' and b_last<b_prev else 'کفِ بالاتر (HL)' if kind=='L' and b_last>b_prev else 'هم‌سطحِ سوئینگِ قبل'} "
        f"— شکستِ همبستگی"
    )
    return {**base, "diverged": bool(diverged),
            "sweep": bool(a_sweep), "other_sweep": bool(b_sweep),
            "reason": why if diverged else
            ("همبستگی سالم است — هیچ شکافی در آخرین دو سوئینگ نیست"
             if (a_extreme == b_hold) else
             "شرطِ SMT ناقص: فقط یک نماد اکسترممِ جدید زده"),
            "last_two": {
                sym: {"prev": round(a_prev, 5), "last": round(a_last, 5), "label": a_txt},
                prt: {"prev": round(b_prev, 5), "last": round(b_last, 5), "label": b_txt},
            }}


def check_for(symbol, direction, fetch_fn=None):
    """جفتِ همبستهٔ نماد را پیدا و SMT را روی دادهٔ زنده می‌سنجد.

    fetch_fn(symbol, tf, limit) باید آرایهٔ کندلِ بسته بدهد؛ پیش‌فرض همان
    `smc_engine.fetch` است (تایم‌فریم/محدودیت را صداکننده انتخاب می‌کند).
    اگر نمادِ جفت همبسته نداشته باشد، برای جفت‌های دلاریِ اصلی به DXY به‌عنوانِ
    مرجعِ زمینه اشاره می‌شود (بدونِ ادعای دایورجنس).
    خروجی همیشه dict است؛ خطایِ شبکه/داده = diverged=False با دلیلِ روشن.
    """
    sym = (symbol or "").upper().strip()
    out = {"available": bool(partners(sym)), "partners": partners(sym),
           "dxy_ref": bool(partners(sym)) is False and sym.endswith("USD") and sym[:3] != "USD",
           "checked": None}
    if not partners(sym):
        return out
    p = partners(sym)[0]
    if fetch_fn is None:
        import smc_engine as E
        fetch_fn = E.fetch
    try:
        sb = fetch_fn(sym)
        pb = fetch_fn(p)
        out["checked"] = smt_divergence(sym, sb, p, pb, direction)
    except Exception as e:
        out["checked"] = {"diverged": False, "reason": f"دادهٔ {p} نیامد: {e}",
                          "symbol": sym, "partner": p}
    return out
