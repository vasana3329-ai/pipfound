#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""بازپرسیِ شکافِ ارزشِ منصفانه (FVG) — «این آدرس تأیید دارد یا نه؟»

خواستهٔ کاربر: «تووی اپ روندی رو طراحی کنی که بتونه تشخیص بده کدوم شکاف ارزش منصفانه
تایید بیشتری داره و می‌شه بهش اتکا کرد؛ باید این به شکل پرسش باشه یعنی کاربر آدرس
شکاف رو می‌ده در تایم‌فریم مشخص و ازت می‌خواد تاییدیش رو بررسی کنی.»

این ماژول همان پرسش را جواب می‌دهد: (نماد، تایم‌فریم، آدرسِ گپ) → **حکمِ تأیید**.
مراحل:
  ۱) گپِ منطبق با آدرس پیدا می‌شود — سه‌کندلیِ خالص (بدونِ گیتِ دیسپلیسمنت) تا اگر
     آدرس، گپِ بی‌کیفیت بود «پیدا نشد» نگوییم؛ وگرنه کاربر از تفاوتِ «نیست» و
     «هست ولی ضعیف» بی‌خبر می‌مانْد.
  ۲) چرخهٔ عمرش سنجیده می‌شود: دست‌نخورده / لمس‌شده / میتیگن‌شده (بیش از نصف مصرف)
     / پُرشده (دیگر ایمبالانس نیست؛ کاندیدای IFVG).
  ۳) کاتالیزورهای تأییدِ استانداردِ ICT چک‌به‌چک و **نمره‌دار** می‌شوند: کیفیتِ
     دیسپلیسمنتِ کندلِ میانی، تازگی، هم‌جهتی با بایاسِ تایم‌فریمِ بالا، کانفلوئنسِ
     POIِ تایم‌فریمِ بالا روی همان آدرس، توالیِ سوئیپ→MSS، سوئیپِ لیکوئیدیتیِ پیش
     از تولدِ گپ، سمتِ پریمیوم/دیسکانت، کیل‌زونِ تولد، هم‌پوشانی با اردر بلاک،
     معقول‌بودنِ اندازهٔ گپ (گپِ غول‌آسا = void) و فاصلهٔ قیمت از ناحیه.
  ۴) درجه + حکم + گیت‌های سقف‌زننده + **ابطال‌ها** + سطوحِ عملی (ورود/ابطال/هدف)
     برگردانده می‌شود. اگر آدرس به هیچ گپی نخورد، نزدیک‌ترین گپ‌های واقعی با فاصله
     برمی‌گردند تا کاربر آدرس را درست کند.

صداقتِ داده (قراردادِ مخزن): اگر بازار بسته یا داده کهنه باشد، درجه **سقف می‌خورد**
(closed → C، delayed/thin → B) و دلیلش هم در payload می‌آید — هیچ‌وقت سبزِ دروغِ
«همه‌چیز تأیید شد» روی دادهٔ کهنه ساخته نمی‌شود.
"""
import time

import smc_engine as E

# نردبانِ تایم‌فریم: برای هر تایم‌فریم، تایم‌فریمِ بالاتر (کانفلوئنسِ HTF).
TF_LADDER = {"1m": "5m", "5m": "15m", "15m": "1h", "30m": "4h",
             "1h": "4h", "4h": "1d", "1d": "1w", "1w": None}

# چرخهٔ عمرِ گپ → واژهٔ فارسی (رابط و حکم از همین استفاده می‌کنند).
STATE_FA = {"fresh": "دست‌نخورده (تازه)",
            "touched": "لمس‌شده، ولی زیرِ نصف مصرف",
            "mitigated": "میتیشن‌شده — بیش از نصف مصرف شده",
            "filled": "پُرشده — دیگر ایمبالانس نیست (کاندیدای IFVG)",
            "absent": "گپی در این آدرس نیست"}

# درجه‌ی نهایی از درصدِ امتیازِ ممکن. A+/A = «قابلِ اتکا».
GRADES = ((85, "A+"), (70, "A"), (55, "B"), (40, "C"), (0, "D"))
RELIABLE_GRADES = ("A+", "A")
_GRADE_ORDER = ("A+", "A", "B", "C", "D")

LOOKBACK = 200          # پنجرهٔ جست‌وجوی گپ (کندل)
DISP_GATE = 1.3         # گیتِ دیسپلیسمنتِ موتور (بدنه ≥ ۱.۳× میانگینِ بدنه)
# آستانه‌ها روی داده‌ی واقعی کالیبره شده‌اند (۳۶۰ گپ روی ۷ نماد/تایم‌فریم:
# XAUUSD 15m/1h، EURUSD 15m، GBPUSD 5m، XAGUSD 30m، NAS100 5m، BTCUSDT 1h):
#   نسبتِ بدنهٔ کندلِ میانی → p50=۱٫۵ · p75=۲٫۱ · p80=۲٫۳ · p90=۳٫۰
#   نسبتِ اندازهٔ گپ به میانگینِ رِنج → p50=۰٫۴ · p90=۱٫۲ · p95=۱٫۵ (تکِ outlier ۱۰٫۵ = void)
# پس «دیسپلیسمنتِ قوی» = بالای صدک ۸۰ و «void» = دنبالهٔ بالا (نه گپِ معمولی).
DISP_STRONG = 2.3       # دیسپلیسمنتِ قوی (≈ صدکِ ۸۰ داده‌ی واقعی)
VOID_X_AVG = 2.5        # بزرگ‌تر از این ⇒ گپِ غول‌آسا/void، نه FVGِ تمیز
NEAR_X_AVG = 1.5        # فاصلهٔ قیمت از گپ که «قابلِ اجرا» حساب می‌شود
SWEEP_GAP_BARS = 5      # سوئیپِ لیکوئیدیتی چند کندل پیش از تولدِ گپ «کاتالیزور» است
# آستانهٔ تطبیقِ آدرس: دست‌کم نصفِ کوچک‌ترینِ دو ناحیه هم‌پوشانی لازم است.
MATCH_MIN_OVERLAP = 0.5


def tf_above(tf):
    """تایم‌فریمِ بالاترِ همان نماد (None اگر بالاترین باشد)."""
    return TF_LADDER.get((tf or "").strip().lower())


def _avg_body(bars, i, n=20):
    lo = max(0, i - n + 1)
    seg = bars[lo:i + 1]
    return sum(abs(x["c"] - x["o"]) for x in seg) / max(1, len(seg))


def _avg_range(bars, i, n=20):
    lo = max(0, i - n + 1)
    seg = bars[lo:i + 1]
    return sum(x["h"] - x["l"] for x in seg) / max(1, len(seg))


def _zone_at(bars, i, kind):
    """ناحیهٔ گپِ سه‌کندلیِ کندلِ میانی `i-1` (None اگر الگو نباشد)."""
    a, b, c = bars[i - 2], bars[i - 1], bars[i]
    if kind == "bullish":
        if a["h"] < c["l"] and b["c"] > b["o"]:
            return a["h"], c["l"]
    else:
        if a["l"] > c["h"] and b["c"] < b["o"]:
            return c["h"], a["l"]
    return None


def _lifecycle(bars, i, kind, lo, hi):
    """مصرفِ گپ پس از تولد: عمقِ نفوذ ÷ اندازهٔ گپ → چرخهٔ عمر."""
    after = bars[i + 1:]
    gap = hi - lo
    if gap <= 0:
        return {"state": "filled", "consumed": 1.0, "penetration": None}
    if kind == "bullish":
        # قیمت برای پر کردن باید **پایین** بیاید؛ عمق = تا چه اندازه زیرِ سقفِ گپ.
        touch = min([x["l"] for x in after] + [hi])
        depth = max(0.0, hi - touch)
    else:
        touch = max([x["h"] for x in after] + [lo])
        depth = max(0.0, touch - lo)
    consumed = min(1.0, depth / gap)
    if depth <= 0:
        state = "fresh"
    elif consumed < 0.5:
        state = "touched"
    elif consumed < 1.0:
        state = "mitigated"
    else:
        state = "filled"
    return {"state": state, "consumed": round(consumed, 3), "penetration": round(depth, 5)}


def gap_scan(bars, lookback=LOOKBACK):
    """همهٔ گپ‌های سه‌کندلیِ پنجرهٔ اخیر + چرخهٔ عمر و کیفیتشان.

    عمداً **گیتِ دیسپلیسمنت اعمال نمی‌شود**: این تابع برای «بازپرسی» است، نه
    فهرستِ POI. گپِ بی‌کیفیت هم باید پیدا شود تا حکم بگوید «هست ولی ضعیف»؛
    فیلترکردن این‌جا یعنی کاربر برای آدرسِ درستِ خودش «پیدا نشد» بشنود.
    """
    n = len(bars)
    out = []
    start = max(2, n - max(lookback, 3))
    for i in range(start, n):
        avgb = _avg_body(bars, i)
        avgr = _avg_range(bars, i)
        body = abs(bars[i - 1]["c"] - bars[i - 1]["o"])
        for kind in ("bullish", "bearish"):
            z = _zone_at(bars, i, kind)
            if z is None:
                continue
            lo, hi = z
            if hi <= lo:
                continue
            life = _lifecycle(bars, i, kind, lo, hi)
            out.append({
                "type": kind, "bottom": round(lo, 5), "top": round(hi, 5),
                "mid": round(lo + (hi - lo) * 0.5, 5), "idx": i,
                "bars_since": n - 1 - i,
                "size": round(hi - lo, 5),
                "size_x_avg": round((hi - lo) / avgr, 2) if avgr > 0 else None,
                "disp_ratio": round(body / avgb, 2) if avgb > 0 else None,
                "state": life["state"], "consumed": life["consumed"],
                "born_ts": bars[i]["t"],
            })
    return out


def _overlap(a_lo, a_hi, b_lo, b_hi):
    return max(0.0, min(a_hi, b_hi) - max(a_lo, b_lo))


def match_zone(gaps, lo, hi):
    """بهترین گپِ منطبق با آدرسِ پرسیده‌شده → (گپ یا None، هم‌پوشانی، درصدِ هم‌پوشانی).

    دو شرط با هم:
      • نسبتِ هم‌پوشانی ÷ کوچک‌ترینِ دو ناحیه ≥ ۵۰٪ — یعنی «آدرس داخلِ گپ» و
        «گپ داخلِ آدرس» هر دو پذیرفتنی‌اند (کاربر ممکن است فقط بخشی از گپ را بدهد)،
        ولی یک ناحیهٔ ربط‌نداشته هم تطبیق نمی‌شود.
      • بینِ گزینه‌های پذیرفتنی، **بیشترین هم‌پوشانیِ مطلق** برنده است (تساوی →
        تازه‌ترین). چرا مهم است: اگر کاربر آدرسِ کلِ ایمبالانس را بدهد، گپِ
        سه‌کندلیِ خودِ ناحیه بیشترین هم‌پوشانی را دارد و یک گپِ ریزِ تودرتو
        جای آن را نمی‌گیرد.
    """
    qsize = max(hi - lo, 1e-9)
    best, best_ov, best_r = None, 0.0, 0.0
    for g in gaps:
        ov = _overlap(lo, hi, g["bottom"], g["top"])
        gsize = max(g["top"] - g["bottom"], 1e-9)
        r = ov / min(qsize, gsize)
        if r < MATCH_MIN_OVERLAP:
            continue
        if ov > best_ov or (ov == best_ov and best is not None and g["idx"] > best["idx"]):
            best, best_ov, best_r = g, ov, r
    if best is None:
        return None, 0.0, 0.0
    return best, round(best_ov, 5), round(best_r, 3)


def nearest_gaps(gaps, lo, hi, k=3):
    """نزدیک‌ترین گپ‌های واقعی به آدرس (فاصله از مرکزِ آدرس تا ناحیه؛ داخل = صفر)."""
    center = (lo + hi) / 2.0
    rows = []
    for g in gaps:
        if g["bottom"] <= center <= g["top"]:
            d = 0.0
        else:
            d = min(abs(center - g["bottom"]), abs(center - g["top"]))
        rows.append((d, -g["idx"], g))
    rows.sort(key=lambda t: (t[0], t[1]))
    return [{"type": g["type"], "bottom": g["bottom"], "top": g["top"],
             "state": g["state"], "state_fa": STATE_FA.get(g["state"], g["state"]),
             "bars_since": g["bars_since"], "distance": round(d, 5)}
            for d, _, g in rows[:max(1, k)]]


def _bias(d):
    """بایاسِ یک تایم‌فریم از trend/CHoCH/BOS همان دیکشنری (۱=صعودی، -۱=نزولی)."""
    if not d:
        return 0
    tr = (d.get("trend") or "").lower()
    if "bull" in tr or "صعود" in tr:
        return 1
    if "bear" in tr or "نزول" in tr:
        return -1
    for key in ("CHoCH", "BOS"):
        ev = d.get(key)
        if ev and "bullish" in str(ev[0]):
            return 1
        if ev and "bearish" in str(ev[0]):
            return -1
    return 0


def _data_gate(d):
    """گیتِ داده‌ی همان تایم‌فریم → (سقفِ درجه، یادداشت). قراردادِ مخزن:
    بازارِ بسته/داده‌ی کهنه هرگز نباید درجه‌ی بالا بگیرد."""
    data = (d or {}).get("data") or {}
    state = data.get("state")
    if state == "closed":
        return "C", ("بازار بسته/بی‌فید است (%s) — تأییدِ قطعی ممکن نیست؛ درجه سقف C خورد."
                     % data.get("reason", "دلیل نامعلوم"))
    if state in ("delayed", "thin"):
        return "B", ("داده‌ی %s (%s) — تأیید با احتیاط؛ درجه سقف B خورد."
                     % ("عقب‌افتاده" if state == "delayed" else "نازک",
                        data.get("reason", "دلیل نامعلوم")))
    return None, None


def grade_of(percent):
    for cut, g in GRADES:
        if percent >= cut:
            return g
    return "D"


def _cap(grade, cap):
    if cap is None:
        return grade
    return grade if _GRADE_ORDER.index(grade) >= _GRADE_ORDER.index(cap) else cap


def gap_verdict(bars, tf, lo, hi, d=None, d_htf=None, htf=None, now=None, lookback=LOOKBACK,
                sym=None):
    """حکمِ تأییدِ گپ در آدرسِ [lo, hi] روی تایم‌فریم `tf`.

    `d`/`d_htf`: خروجیِ analyze_bars برای همین تایم‌فریم و تایم‌فریمِ بالاتر (اختیاری —
    اگر ندهید خودش از همان کندل‌ها می‌سازد؛ `sym` آن‌وقت برای تشخیصِ کلاسِ نماد و
    باز/بسته‌بودنِ بازار لازم است تا گیتِ داده درست بزند). `bars` باید **فقط کندلِ
    بسته** باشد.
    """
    now = now if now is not None else time.time()
    tf = (tf or "").strip().lower()
    if tf not in E.TF_SECONDS:
        return {"ok": False, "error": "تایم‌فریمِ نامعتبر: %s — معتبرها: %s"
                % (tf or "(خالی)", "، ".join(E.TF_SECONDS.keys()))}
    lo, hi = (lo, hi) if lo <= hi else (hi, lo)
    if not (hi > lo):
        return {"ok": False, "error": "آدرسِ شکاف نامعتبر است (کف و سقف یکی/خالی‌اند)"}
    if not bars or len(bars) < 30:
        return {"ok": False, "error": "کندلِ کافی برای بازپرسی نیست (دست‌کم ۳۰ کندلِ بسته لازم است)"}

    if d is None:
        d = E.analyze_bars(bars, tf, disp=sym or tf, src="gap-query", sym=sym, now=now)
    if htf is None:
        htf = tf_above(tf)

    gaps = gap_scan(bars, lookback=lookback)
    gap, ov, ov_pct = match_zone(gaps, lo, hi)
    price = bars[-1]["c"]
    avgr_now = _avg_range(bars, len(bars) - 1)
    window = {"bars": len(bars), "lookback": lookback,
              "from_utc": _utc(bars[max(0, len(bars) - lookback)]["t"]),
              "to_utc": _utc(bars[-1]["t"]), "tf": tf}

    base = {"ok": True, "symbol": d.get("resolved") or d.get("symbol"), "tf": tf, "htf": htf,
            "query": {"bottom": round(lo, 5), "top": round(hi, 5), "mid": round((lo + hi) / 2, 5)},
            "price": price, "window": window, "data": d.get("data"),
            "nearest": [], "checks": [], "gates": [], "invalidations": [],
            "gap": None, "state": "absent", "state_fa": STATE_FA["absent"],
            "grade": None, "reliable": False, "score": {"got": 0.0, "max": 0.0, "percent": 0.0}}

    if gap is None:
        base["found"] = False
        base["nearest"] = nearest_gaps(gaps, lo, hi)
        if not gaps:
            base["verdict"] = ("⛔ در %s کندلِ اخیرِ %s هیچ گپِ سه‌کندلیِ خامی نیست — "
                               "آدرس را روی تایم‌فریمِ درست یا ناحیهٔ تازه‌تری بپرس."
                               % (len(bars), tf))
        else:
            near = "، ".join("%s %s–%s (%s، %d کندل پیش)"
                             % ("صعودی" if n["type"] == "bullish" else "نزولی",
                                _n(n["bottom"]), _n(n["top"]), n["state_fa"], n["bars_since"])
                             for n in base["nearest"])
            base["verdict"] = ("⛔ آدرسِ %s–%s به هیچ گپِ %s نمی‌خورد (بهترین هم‌پوشانی %.0f٪ — زیرِ آستانهٔ ۵۰٪). "
                               "نزدیک‌ترین گپ‌های واقعی: %s"
                               % (_n(lo), _n(hi), tf, ov_pct * 100, near))
        base["invalidations"].append("آدرسِ غلط = پرسشِ بی‌معنا؛ اول ناحیهٔ درستِ گپ را از "
                                     "فهرستِ «نزدیک‌ترین‌ها» بردار و دوباره بپرس.")
        return base

    base["found"] = True
    base["gap"] = gap
    base["state"] = gap["state"]
    base["state_fa"] = STATE_FA.get(gap["state"], gap["state"])
    base["overlap"] = ov
    base["overlap_pct"] = ov_pct
    direction = 1 if gap["type"] == "bullish" else -1
    want = gap["type"]
    cap, gate_note = _data_gate(d)
    if gate_note:
        base["gates"].append({"name": "دامنهٔ داده", "ok": False, "detail": gate_note})
    else:
        base["gates"].append({"name": "دامنهٔ داده", "ok": True,
                              "detail": "دادهٔ %s تازه است (%s)" % (tf, (d.get("data") or {}).get("state"))})

    checks = base["checks"]

    def row(name, ok, weight, detail):
        got = weight if ok is True else 0.0
        checks.append({"name": name,
                       "status": "✓" if ok is True else ("✗" if ok is False else "—"),
                       "weight": round(weight, 2), "got": round(got, 2), "detail": detail})

    # ۱) کیفیتِ دیسپلیسمنتِ کندلِ میانی — همان گیتی که موتور برای FVG می‌گذارد.
    dr = gap["disp_ratio"]
    ok_disp = dr is not None and dr >= DISP_GATE
    row("دیسپلیسمنتِ کندلِ میانی (≥%.1f× میانگینِ بدنه)" % DISP_GATE, ok_disp, 2.0,
        ("بدنهٔ کندلِ میانی %s× میانگین — گپ از حرکتِ نهادی زاده شده" % dr) if ok_disp
        else ("بدنهٔ کندلِ میانی فقط %s× میانگین است — گپِ ۳کندلیِ بی‌جان (چوپ) یا "
              "نبودِ داده‌ی کافی" % dr))
    row("دیسپلیسمنتِ قوی (≥%.1f× میانگین)" % DISP_STRONG, bool(dr and dr >= DISP_STRONG), 1.0,
        ("حرکتِ نهادیِ پرقدرت (%s×)" % dr) if (dr and dr >= DISP_STRONG)
        else ("قدرتِ حرکت متوسط است (%s×) — تأییدِ قوی نمی‌دهد" % dr))

    # ۲) تازگی: گپِ دست‌نخورده = ایمبالانسِ مصرف‌نشده.
    fresh = gap["state"] == "fresh"
    row("گپِ دست‌نخورده (تازه)", fresh, 2.0,
        ("قیمت بعد از تولد وارد گپ نشده — ایمبالانسِ کامل" if fresh else
         ("قیمت %s%% از گپ را مصرف کرده (%s) — %s"
          % (int(gap["consumed"] * 100), gap["state"],
             "زیرِ نصف است، ولی دیگر تازه نیست" if gap["state"] == "touched"
             else "طبقِ قاعدهٔ موتور دیگر POIِ تازه نیست"))))

    # ۳و۴) تایم‌فریمِ بالا: جهت + کانفلوئنسِ ناحیه.
    htf_bias = _bias(d_htf)
    if d_htf is None:
        row("هم‌جهتی با بایاسِ %s" % (htf or "تایم‌فریمِ بالا"), None, 1.5,
            "دادهٔ تایم‌فریمِ بالا در دسترس نیست — این بند سنجیده نشد")
    else:
        row("هم‌جهتی با بایاسِ %s" % htf, bool(htf_bias == direction), 1.5,
            ("بایاسِ %s هم‌جهت با گپ است" % htf) if htf_bias == direction
            else ("بایاسِ %s %s است و گپ %s — تریدِ خلافِ تایم‌فریمِ بالا"
                  % (htf, _bias_fa(htf_bias), _dir_fa(direction))))
    htf_poi = None
    if d_htf:
        pool = ([z for z in (d_htf.get("order_blocks") or []) if z.get("type") == want]
                + [z for z in (d_htf.get("FVG_unfilled") or []) if z.get("type") == want])
        hit = None
        for z in pool:
            if _overlap(lo, hi, z["bottom"], z["top"]) > 0:
                hit = z
                break
        htf_poi = bool(hit)
        row("کانفلوئنسِ POIِ %s روی همین آدرس" % htf, htf_poi, 1.5,
            ("%s %s–%s روی آدرسِ گپ است — کانفلوئنسِ تایم‌فریمِ بالا"
             % ("اردر بلاک" if hit in (d_htf.get("order_blocks") or []) else "فیرولیوگپ",
                _n(hit["bottom"]), _n(hit["top"]))) if hit
            else ("علاوه‌بر گپ، اردر بلاک/گپِ هم‌جهتِ %s هم روی این آدرس نیست" % htf))
    else:
        row("کانفلوئنسِ POIِ تایم‌فریمِ بالا", None, 1.5, "دادهٔ تایم‌فریمِ بالا در دسترس نیست")

    # ۵) توالیِ مقدسِ ICT: سوئیپِ لیکوئیدیتی → شکستِ ساختار (MSS).
    seq = d.get("sequence_ok")
    row("توالیِ سوئیپ→MSS روی %s" % tf, seq, 1.0,
        {True: "ترتیب درست: سوئیپِ لیکوئیدیتی پیش از شکستِ ساختار رخ داده",
         False: "توالیِ نقض‌شده: شکستِ ساختار پیش از سوئیپ — ورود پرریسک",
         None: "سوئیپ/شکستِ واضحی برای سنجشِ توالی نیست"}[seq])

    # ۶) سوئیپِ لیکوئیدیتیِ پیش از تولدِ گپ — رایدی که ایمبالانس را ساخت.
    want_sweep = "bullish_sweep" if direction == 1 else "bearish_sweep"
    swp = None
    for s in (d.get("liquidity_sweeps") or []):
        if s.get("type") != want_sweep or s.get("idx") is None:
            continue
        back = gap["idx"] - s["idx"]
        if 0 <= back <= SWEEP_GAP_BARS:
            swp = s
            break
    row("سوئیپِ لیکوئیدیتی پیش از تولدِ گپ", bool(swp), 1.0,
        ("سوئیپِ %s روی %s، %d کندل پیش از گپ — راید→ایمبالانس"
         % ("سل‌ساید" if direction == 1 else "بای‌ساید", _n(swp["level"]), gap["idx"] - swp["idx"]))
        if swp else "پیش از تولدِ گپ سوئیپِ هم‌جهتی دیده نشد")

    # ۷) سمتِ بازار: گپِ خرید در دیسکانت، گپِ فروش در پریمیوم.
    pd = d.get("premium_discount") or {}
    eq = pd.get("equilibrium")
    if eq is None:
        row("سمتِ پریمیوم/دیسکانت", None, 1.0, "رِنجِ دیلینگ (PD) در دسترس نیست")
    else:
        gm = gap["mid"]
        good = (gm < eq) if direction == 1 else (gm > eq)
        row("سمتِ پریمیوم/دیسکانت", good, 1.0,
            ("گپ در %s است (EQ=%s) — سمتِ درستِ ورود"
             % ("دیسکانت" if direction == 1 else "پریمیوم", _n(eq))) if good
            else ("گپ در %s است (EQ=%s) — سمتِ گرانِ رِنج برای %s"
                  % ("پریمیوم" if gm > eq else "دیسکانت", _n(eq), _dir_fa(direction))))

    # ۸) کیل‌زونِ تولدِ گپ — گپ‌های سشن‌های اصلی کیفیتِ بالاتری دارند.
    kz = E.killzone_at(gap["born_ts"])
    in_kz = "Outside" not in str(kz)
    row("تولدِ گپ داخلِ کیل‌زون", in_kz, 0.5,
        ("گپ داخلِ %s ساخته شده" % kz) if in_kz else ("گپ بیرونِ کیل‌زون‌های اصلی ساخته شده (%s)" % kz))

    # ۹) هم‌پوشانی با اردر بلاکِ هم‌جهت روی همین تایم‌فریم (ترکیبِ OB+FVG).
    ob_hit = None
    for o in (d.get("order_blocks") or []):
        if o.get("type") == want and _overlap(lo, hi, o["bottom"], o["top"]) > 0:
            ob_hit = o
            break
    row("هم‌پوشانی با اردر بلاکِ هم‌جهت", bool(ob_hit), 1.0,
        ("اردر بلاک %s–%s روی ناحیه است — ترکیبِ اوبی+گپ" % (_n(ob_hit["bottom"]), _n(ob_hit["top"])))
        if ob_hit else "اردر بلاکِ هم‌جهتی روی این ناحیه نیست (گپ تنهاست)")

    # ۱۰) اندازهٔ گپ: غول‌آسا = void/بی‌ساختار، نه FVGِ تمیز.
    sx = gap["size_x_avg"]
    sane = sx is not None and sx <= VOID_X_AVG
    row("اندازهٔ معقولِ گپ (≤%.1f× میانگینِ رِنج)" % VOID_X_AVG, sane, 0.5,
        ("اندازه %s× میانگینِ رِنج — گپِ ساختاری" % sx) if sane
        else ("اندازه %s× میانگینِ رِنج — بیشتر شبیهِ void/جهشِ تک‌کندلی است تا FVGِ تمیز" % sx))

    # ۱۱) فاصلهٔ قیمت از ناحیه: گپِ دور، «تأییدِ فعلی» نیست.
    if avgr_now <= 0:
        row("قابلِ اجرا بودن (فاصلهٔ قیمت)", None, 0.5, "میانگینِ رِنج صفر است — فاصله سنجیده نشد")
    else:
        dist = 0.0 if gap["bottom"] <= price <= gap["top"] else min(
            abs(price - gap["bottom"]), abs(price - gap["top"]))
        dx = dist / avgr_now
        near = dx <= NEAR_X_AVG
        row("قابلِ اجرا بودن (فاصلهٔ قیمت)", near, 0.5,
            ("قیمت %s× میانگینِ رِنج از ناحیه فاصله دارد — در دسترسِ پلنِ فعلی" % round(dx, 2))
            if near else
            ("قیمت %s× میانگینِ رِنج از ناحیه دور است — تا رسیدنِ قیمت، پرسش دوباره لازم است"
             % round(dx, 2)))

    got = sum(c["got"] for c in checks)
    maxw = sum(c["weight"] for c in checks if c["status"] != "—")
    percent = round(got / maxw * 100, 1) if maxw > 0 else 0.0
    grade = grade_of(percent)
    # سقف‌ها: گپِ مصرف‌شده هرگز «قابلِ اتکا» نمی‌شود — این قاعده‌ی موتور است، نه سلیقه.
    if gap["state"] in ("mitigated", "filled"):
        cap = "C" if cap is None else _cap(cap, "C")
        base["gates"].append({"name": "چرخهٔ عمر", "ok": False,
                              "detail": "گپ %s است — طبقِ قاعدهٔ موتور (میانگینِ ۵۰٪) "
                                        "دیگر POIِ تازه نیست؛ درجه سقف C خورد."
                                        % STATE_FA[gap["state"]]})
    raw_grade = grade
    if cap is not None:
        grade = _cap(grade, cap)
    base["cap"] = cap
    base["capped"] = bool(cap is not None and grade != raw_grade)
    base["score"] = {"got": round(got, 2), "max": round(maxw, 2), "percent": percent,
                     "grade_raw": raw_grade}
    base["grade"] = grade
    base["reliable"] = grade in RELIABLE_GRADES
    base["invalidations"] = _invalidations(gap, want, direction, price)
    base["levels"] = _levels(gap, d, want, direction, price)
    base["verdict"] = _verdict_text(gap, grade, percent, want, htf, tf, checks,
                                    cap=cap, capped=base["capped"], raw=raw_grade)
    return base


def load(symbol, tf, limit=300):
    """کندلِ بسته + تحلیلِ کاملِ یک تایم‌فریم روی همان مسیرِ زندهٔ موتور (fetch)."""
    src, sym, disp, bars = E.fetch(symbol, tf, limit)
    bars, dropped = E.drop_unclosed(bars, tf)
    d = E.analyze_bars(bars, tf, disp=disp, src=src, sym=sym)
    d["_dropped"] = dropped          # کندلِ ناقصی که حذف شد (برای شفافیتِ پاسخ)
    return bars, d


def query(symbol, tf, lo=None, hi=None, limit=300, lookback=LOOKBACK):
    """پرسشِ کاملِ رابط: (نماد، تایم‌فریم، آدرس) → حکمِ تأیید.

    `lo`/`hi` نده ⇒ حالتِ «کدام شکاف تأییدِ بیشتری دارد؟»: همان گپ‌های واقعیِ موتور
    (دیسپلیسمنت‌دار و تخطی‌نشده) هرکدام با حکمِ تأییدشان، مرتب بر اساسِ امتیاز —
    تا کاربر آدرسِ باکیفیت‌تر را ببیند و بعد دربارهٔ همان بپرسد.
    """
    sym = (symbol or "").strip().upper()
    tf = (tf or "").strip().lower()
    if tf not in E.TF_SECONDS:
        return {"ok": False, "mode": "query", "tfs": list(E.TF_SECONDS),
                "error": "تایم‌فریمِ نامعتبر: %s — معتبرها: %s"
                         % (tf or "(خالی)", "، ".join(E.TF_SECONDS.keys()))}
    if not sym:
        return {"ok": False, "mode": "query", "error": "نماد وارد نشده"}
    try:
        bars, d = load(sym, tf, limit)
    except Exception as e:
        return {"ok": False, "mode": "query", "symbol": sym, "tf": tf,
                "error": "دادهٔ %s %s خوانده نشد: %s" % (sym, tf, e)}
    htf = tf_above(tf)
    d_htf = None
    if htf:
        try:
            _, d_htf = load(sym, htf, limit)
        except Exception:
            d_htf = None

    def _one(l, h):
        v = gap_verdict(bars, tf, l, h, d=d, d_htf=d_htf, htf=htf, lookback=lookback, sym=sym)
        v["symbol"] = sym
        v["htf_missing"] = bool(htf and d_htf is None)
        if v["htf_missing"]:
            v.setdefault("gates", []).append({
                "name": "تایم‌فریمِ بالا", "ok": False,
                "detail": "دادهٔ %s خوانده نشد — دو بندِ کانفلوئنسِ تایم‌فریمِ بالا سنجیده نشد" % htf})
        return v

    if lo is None or hi is None:
        rows = [_one(f["bottom"], f["top"]) for f in (d.get("FVG_unfilled") or [])]
        rows.sort(key=lambda v: -((v.get("score") or {}).get("percent") or 0))
        return {"ok": True, "mode": "list", "symbol": sym, "tf": tf, "htf": htf,
                "count": len(rows), "gaps": rows, "data": d.get("data"),
                "price": bars[-1]["c"],
                "summary": (("%d گپِ تازهٔ مصرف‌نشده روی %s %s — مرتب بر اساسِ امتیازِ تأیید"
                             % (len(rows), sym, tf)) if rows else
                            ("روی %s %s گپِ تازهٔ مصرف‌نشده‌ای نیست — همه میتیگن/پر شده‌اند"
                             % (sym, tf)))}
    v = _one(lo, hi)
    v["mode"] = "query"
    return v


def _invalidations(gap, want, direction, price):
    """شرط‌های ابطالِ عملی — تا «تأیید» به‌معنای «بی‌شرط» خوانده نشود."""
    out = ["مصرفِ بیش از ۵۰٪ گپ (عبور از %s) = ابطالِ ایمبالانس." % _n(gap["mid"]),
           "پرشدنِ کاملِ گپ (%s) = بسته‌شدنِ پروندهٔ FVG." % _n(gap["bottom"] if direction == 1 else gap["top"])]
    if gap["state"] != "fresh":
        out.append("این گپ از قبل مصرف شده (%d%%) — فقط با تریگرِ تازه ارزشِ بررسی دارد."
                   % int(gap["consumed"] * 100))
    if direction == 1 and price > gap["top"]:
        out.append("قیمت بالای گپ است — ورودِ لیمیت یعنی انتظارِ پولبک؛ بی‌پولبک، پلن اجرا نمی‌شود.")
    if direction == -1 and price < gap["bottom"]:
        out.append("قیمت زیرِ گپ است — ورودِ لیمیت یعنی انتظارِ پولبک؛ بی‌پولبک، پلن اجرا نمی‌شود.")
    return out


def _levels(gap, d, want, direction, price):
    """سطوحِ عملی: ناحیهٔ ورود (نیمهٔ نزدیکِ گپ)، ابطال و اولین هدفِ لیکوئیدیتی + R:R."""
    lo, hi, mid = gap["bottom"], gap["top"], gap["mid"]
    if direction == 1:
        entry = (lo, mid)
        stop = lo
        pool = [v for v in ((d.get("liquidity") or {}).get("buyside_eqh") or []) if v > entry[1]]
        target = min(pool) if pool else None
    else:
        entry = (mid, hi)
        stop = hi
        pool = [v for v in ((d.get("liquidity") or {}).get("sellside_eql") or []) if v < entry[0]]
        target = max(pool) if pool else None
    emid = (entry[0] + entry[1]) / 2.0
    risk = abs(emid - stop)
    rr = None
    if target is not None and risk > 0:
        rr = round(abs(target - emid) / risk, 2)
    return {"entry_low": round(entry[0], 5), "entry_high": round(entry[1], 5),
            "invalidate": round(mid, 5), "stop": round(stop, 5),
            "target": (round(target, 5) if target is not None else None), "rr": rr,
            "side": "buy" if direction == 1 else "sell",
            "note": ("ورودِ لیمیت در نیمهٔ نزدیکِ گپ؛ ابطال با عبور از میانِ گپ"
                     + ("؛ اولین هدف %s (%sR)" % (_n(target), rr) if rr else
                        "؛ هدفِ لیکوئیدیتیِ هم‌جهت در داده نبود — حد ضرر/هدف را دستی بگذار"))}


def _verdict_text(gap, grade, percent, want, htf, tf, checks, cap=None, capped=False, raw=None):
    """حکمِ نهاییِ فارسی — صریح، درجه‌محور، بی‌وعدهٔ توخالی."""
    def _cap_note(txt):
        if not capped:
            return txt
        return txt + (" ⚠ درجه از %s به %s سقف خورد (سقف: %s)." % (raw, grade, cap))
    fails = [c["name"] for c in checks if c["status"] == "✗"]
    head = {("A+"): "✅ تأییدِ بالا", ("A"): "✅ تأییدِ خوب",
            ("B"): "🟡 تأییدِ متوسط", ("C"): "🟠 تأییدِ ضعیف",
            ("D"): "🔴 تأییدِ ناکافی"}.get(grade, "🔴 تأییدِ ناکافی")
    tail = ("کاتالیزورهای جامانده: " + "، ".join(fails[:4])) if fails else "همهٔ کاتالیزورها جمع‌اند."
    if gap["state"] == "filled":
        text = ("%s — گپِ %s روی %s کاملاً پر شده (%d%% مصرف)؛ به‌عنوانِ FVG اتکا نکن. "
                "تنها کاربردش IFVG است: اگر قیمت بعد از پرشدن از روی همین ناحیه شکستِ "
                "ساختاری بدهد، به‌عنوانِ حمایت/مقاومتِ برگشتی معامله می‌شود. (%s)"
                % (head, _dir_fa(1 if want == "bullish" else -1), tf, int(gap["consumed"] * 100), tail))
        return _cap_note(text)
    if gap["state"] == "mitigated":
        return _cap_note(
            "%s — بیش از نصفِ گپ مصرف شده؛ طبقِ قاعدهٔ موتور (%d%% مصرف) دیگر ایمبالانسِ "
            "تازه نیست. فقط با سوئیپِ تازهٔ لیکوئیدیتی + MSS روی همین ناحیه دوباره "
            "اعتبار می‌گیرد. (%s)" % (head, int(gap["consumed"] * 100), tail))
    verb = {("A+"): "این شکاف روی همین آدرس قابلِ اتکاست",
            ("A"): "این شکاف قابلِ اتکاست (با مدیریتِ ریسکِ استاندارد)",
            ("B"): "گپ معتبر است ولی تأییدش کامل نیست — با تریگرِ ورودی و سایزِ محافظه‌کارانه",
            ("C"): "اتکا نکن؛ فقط رصد کن تا کاتالیزورها کامل شوند",
            ("D"): "بی‌اعتبار برای ورود — اتکا نکن"}[grade]
    text = ("%s (%s٪ از امتیازِ ممکن) — گپِ %s روی %s %s؛ %s (%s)"
            % (head, percent, _dir_fa(1 if want == "bullish" else -1), htf or "-", verb,
               STATE_FA.get(gap["state"], gap["state"]), tail))
    return _cap_note(text)


def _dir_fa(direction):
    return "صعودی" if direction == 1 else ("نزولی" if direction == -1 else "خنثی")


def _bias_fa(bias):
    return {1: "صعودی", -1: "نزولی", 0: "خنثی"}.get(bias, "نامعلوم")


def _n(v):
    """عدد با گِردکردنِ نمایشی (۵ رقم) — فقط برای متنِ حکم."""
    if v is None:
        return "-"
    try:
        return ("%.5f" % float(v)).rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(v)


def _utc(ts):
    import datetime
    try:
        return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return None
