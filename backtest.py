#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
موتورِ بک‌تستِ walk-forward برای pipfound.

اصلِ کار: **صفر تکرارِ منطق**. همان `score()`ِ تصحیح‌شده‌ی confluence.py و همان
`analyze_bars()`ِ smc_engine.py که در تحلیلِ زنده استفاده می‌شوند، اینجا هم روی
هر برشِ تاریخی صدا زده می‌شوند. پس وین‌ریتی که بیرون می‌آید، دقیقاً بازتابِ رفتارِ
همان چرخه‌ی ورودی است که اپ الان به کاربر پیشنهاد می‌دهد — نه یک منطقِ موازیِ جعلی.

مکانیزم:
  ۱) یک‌بار برای هر تایم‌فریم، بیشترین تعدادِ کندلِ تاریخی گرفته می‌شود (بدون API key).
  ۲) روی کندل‌های تایم‌فریمِ ورود (LTF) گام‌به‌گام جلو می‌رویم. در هر گام، «اکنون» = زمانِ
     آن کندل است؛ هر تایم‌فریم فقط تا آن لحظه بریده می‌شود (هیچ نگاهی به آینده — no look-ahead).
  ۳) با برشِ هر تایم‌فریم، دیکشنریِ d ساخته و به score() تزریق می‌شود → دقیقاً همان پلن/درجه.
  ۴) اگر پلنِ معتبر با درجه‌ی واجدِ شرایط ساخته شد: ورودِ بازار همان لحظه پر می‌شود؛ ورودِ
     لیمیتِ OTE تا سقفِ N کندلِ بعد منتظرِ لمسِ قیمت می‌ماند (وگرنه کنسل).
  ۵) بعد از پرشدن، کندل‌های بعدیِ LTF را دنبال می‌کنیم: اول به SL خورد → لاس؛ اول به TP خورد →
     وین. اگر در یک کندل هر دو لمس شد، محافظه‌کارانه SL اول فرض می‌شود.
  ۶) معاملاتِ هم‌پوشان مجاز نیست: تا بسته‌نشدنِ پوزیشنِ باز، سیگنالِ تازه نادیده گرفته می‌شود.
  ۷) خروجی: تعدادِ معامله، وین‌ریت، میانگینِ R، اکسپکتنسی، و لیستِ معاملات.

فقط stdlib؛ دیتای رایگانِ Binance/Yahoo از طریقِ smc_engine.fetch.
"""
import sys, json, argparse, datetime

import smc_engine as EG
import confluence as CF


def _slice_upto(bars, t_now):
    """برشِ کندل‌ها تا زمانِ t_now (شامل). خروجی مرجعِ تازه‌ی سبک است."""
    # bars مرتب بر اساسِ زمان است؛ آخرین ایندکسی که t <= t_now.
    out = []
    for b in bars:
        if b["t"] <= t_now:
            out.append(b)
        else:
            break
    return out


def _build_d(series, tfs, t_now, warm=40):
    """دیکشنریِ d که score() انتظار دارد: {tf: analyze_bars(برشِ آن تایم‌فریم)}.
    اگر یک تایم‌فریم کندلِ کافی تا این لحظه ندارد، آن گام skip می‌شود (None)."""
    d = {}
    for tf in tfs:
        sl = _slice_upto(series[tf], t_now)
        if len(sl) < warm:
            return None  # هنوز گرم نشده
        try:
            d[tf] = EG.analyze_bars(sl, tf, disp=series["_disp"], src="backtest")
        except Exception as ex:
            d[tf] = {"error": str(ex)}
    return d


def _simulate(entry_bars, start_idx, direction, entry, sl, tp,
              entry_type, fill_window=24, max_hold=400, confirm_window=3):
    """
    شبیه‌سازیِ نتیجه‌ی معامله روی کندل‌های تایم‌فریمِ ورود از start_idx به بعد.
    برمی‌گرداند: (result, exit_price, r, bars_held, filled_idx, fill_price, sl_used)  یا None اگر پر نشد.
    result ∈ {"win","loss"}.

    فیکس C8: ورودِ «market» روی **کلوزِ کندلِ سیگنال** پر می‌شود — همان قیمتی که در
    زمانِ واقعی در دسترس است. ریسک/هدف نسبت به همین قیمتِ واقعی سنجیده می‌شود.

    فیکس C17: ورودِ «limit_ote» دیگر کورکورانه با اولین لمسِ گلدن‌پاکت پر نمی‌شود.
    یک ترِیدرِ اسمارت‌مانی روی لمسِ صرف وارد نمی‌شود؛ منتظرِ **تأییدِ تایمِ پایین‌تر**
    می‌ماند: پس از لمسِ لیمیت، باید طیِ confirm_window کندل یک **کندلِ دیسپلیسمنتِ
    رجکشن** (بسته‌شدن در جهتِ معامله با بدنه‌ی ≥ میانگین) ظاهر شود. ورود روی کلوزِ
    همان کندلِ تأیید انجام می‌شود و **استاپ پشتِ فتیله‌ی سوئیپِ واقعی** (کف/سقفِ
    ثبت‌شده در فازِ پولبک) + بافر می‌نشیند — نه پشتِ سوینگِ ازپیش‌محاسبه‌شده که مدام
    خورده می‌شد (ریشه‌ی C17). اگر تأیید نیاید، معامله‌ای رخ نمی‌دهد.
    """
    n = len(entry_bars)
    filled_idx = None
    fill_price = entry
    sl_used = sl
    if entry_type == "market":
        filled_idx = start_idx
        fill_price = entry_bars[start_idx]["c"]   # فیکس C8: کلوزِ واقعیِ کندلِ سیگنال
    else:
        # limit_ote: ابتدا لمسِ قیمتِ لیمیت طیِ fill_window کندلِ بعد
        touch_idx = None
        for k in range(start_idx + 1, min(start_idx + 1 + fill_window, n)):
            b = entry_bars[k]
            if b["l"] <= entry <= b["h"]:
                touch_idx = k
                break
        if touch_idx is None:
            return None  # لیمیت اصلاً لمس نشد → معامله‌ای رخ نداد

        # آستانه‌ی دیسپلیسمنت = میانگینِ بدنه‌ی ۲۰ کندلِ اخیر (فیکس C17)
        lo = max(0, touch_idx - 20)
        seg = entry_bars[lo:touch_idx + 1]
        avg_body = sum(abs(x["c"] - x["o"]) for x in seg) / max(1, len(seg))
        # فیکس C20: ATRِ محلی (True Range میانگین) روی همان پنجره — برای بافرِ استاپ
        # که با نوسانِ واقعیِ بازار مقیاس بخورد، نه یک درصدِ خامِ ثابت.
        _trs = []
        for i in range(1, len(seg)):
            _pc = seg[i - 1]["c"]
            _tr = max(seg[i]["h"] - seg[i]["l"],
                      abs(seg[i]["h"] - _pc),
                      abs(seg[i]["l"] - _pc))
            _trs.append(_tr)
        atr = (sum(_trs) / len(_trs)) if _trs else abs(entry_bars[touch_idx]["c"]) * 0.001

        # فازِ تأیید: دنبالِ کندلِ رجکشنِ دیسپلیسمنت + ردگیریِ فتیله‌ی سوئیپ
        sweep_ext = entry_bars[touch_idx]["l"] if direction == 1 else entry_bars[touch_idx]["h"]
        confirm_idx = None
        for k in range(touch_idx, min(touch_idx + 1 + confirm_window, n)):
            b = entry_bars[k]
            if direction == 1:
                sweep_ext = min(sweep_ext, b["l"])
            else:
                sweep_ext = max(sweep_ext, b["h"])
            body = abs(b["c"] - b["o"])
            closed_dir = (b["c"] > b["o"]) if direction == 1 else (b["c"] < b["o"])
            if k > touch_idx and closed_dir and body >= avg_body:
                confirm_idx = k
                break
        if confirm_idx is None:
            return None  # تأییدِ LTF نیامد → صبر، نه ورود

        filled_idx = confirm_idx
        fill_price = entry_bars[confirm_idx]["c"]   # ورود روی کلوزِ کندلِ تأیید
        # فیکس C17+C20: استاپ پشتِ فتیله‌ی سوئیپِ واقعیِ فازِ پولبک + بافرِ ATR.
        # مشکلِ افشاشده در C19 (کلاهِ ترِیدر): بافرِ ثابتِ ۰.۰۳٪ استاپ را چنان تنگ
        # می‌کرد که نویزِ عادیِ بازار پیش از رسیدن به هدف آن را می‌زد (planRR تا ۱۰۹،
        # وین‌ریت ۲۲٪). بافر حالا با نوسانِ واقعی (۰.۵×ATR) مقیاس می‌خورد تا استاپ
        # پشتِ کلِ ساختارِ سوئیپ بنشیند، نه فقط نوکِ فتیله. این planRRِ توهمی را هم
        # واقعی می‌کند (مخرجِ ریسک دیگر بیمارگونه کوچک نیست).
        buf = max(abs(fill_price) * 0.0003, 0.5 * atr)
        dyn_sl = (sweep_ext - buf) if direction == 1 else (sweep_ext + buf)
        # فقط اگر استاپِ داینامیک سمتِ درست و با فاصله‌ی معنادار باشد از آن استفاده کن؛
        # وگرنه به استاپِ پلنِ ساختاری برگرد (نگهبان در برابرِ ریسکِ صفر/معکوس).
        min_gap = abs(fill_price) * 0.0005
        if ((direction == 1 and dyn_sl < fill_price - min_gap) or
                (direction == -1 and dyn_sl > fill_price + min_gap)):
            sl_used = round(dyn_sl, 5)

    risk = abs(fill_price - sl_used)
    if risk <= 0:
        return None

    # ── فیکس C18: مدیریتِ پله‌ایِ پوزیشن (اسکیل‌اوت + برگشت‌به‌سربه‌سر) ──────────
    # مشکلِ افشاشده (کلاهِ ترِیدر): استاپِ تنگِ فتیله‌ی سوئیپ + هدفِ لیکوئیدیتیِ دور
    # = RRِ زیبا اما وین‌ریتِ ۰٪، چون قیمت مسیرِ درست را می‌رود ولی قبل از هدفِ دور
    # به استاپ برمی‌گردد. یک ترِیدرِ واقعی all-or-nothing نمی‌گیرد؛ پله‌ای خارج می‌شود.
    #
    # مدل: TP1 روی ۱R (فاصله‌ی = ریسک) → tp1_frac از پوزیشن بسته می‌شود و استاپِ
    # مابقی به سربه‌سر (BE) می‌رود. مابقی تا هدفِ اصلی (tp) می‌دود. نتیجه در واحدِ R
    # وزنیِ کسری برگردانده می‌شود — نه صرفاً win/loss. این تورم نیست: یک ترِیدِ
    # «سوئیپ‌شده اما نرسیده به هدف» حالا به‌جای -۱R به +جزئی/سربه‌سر تبدیل می‌شود،
    # دقیقاً همان‌طور که در اجرای زنده رخ می‌دهد.
    tp1_R = 1.0
    tp1_frac = 0.5
    tp1 = fill_price + direction * risk * tp1_R
    # حالتِ نتیجه: 0=هنوز باز، به‌ترتیبِ رخداد پردازش می‌شود
    booked_R = 0.0            # R قفل‌شده از پله‌ی TP1
    remaining = 1.0           # کسرِ بازِ پوزیشن
    stop_now = sl_used        # استاپِ فعالِ مابقی (بعد از TP1 → BE=fill_price)
    tp1_done = False
    # ── ابزارِ تشخیصی (فقط اندازه‌گیری؛ منطقِ خروج را عوض نمی‌کند) ──────────
    # MFE/MAE در واحدِ R: بیشترین حرکتِ مساعد/نامساعد در کلِ پنجره‌ی نگه‌داری.
    # با این می‌فهمیم هدفِ دومِ واقع‌گرایانه کجاست و آیا رانر اصلاً شانسِ رسیدن دارد.
    mfe_R = 0.0
    mae_R = 0.0
    def _diag():
        return {"mfe_R": round(mfe_R, 2), "mae_R": round(mae_R, 2)}

    for k in range(filled_idx + 1, min(filled_idx + 1 + max_hold, n)):
        b = entry_bars[k]
        # به‌روزرسانیِ MFE/MAE پیش از هر تصمیمِ خروج
        fav = (b["h"] - fill_price) if direction == 1 else (fill_price - b["l"])
        adv = (fill_price - b["l"]) if direction == 1 else (b["h"] - fill_price)
        mfe_R = max(mfe_R, fav / risk)
        mae_R = max(mae_R, adv / risk)
        hit_stop = (b["l"] <= stop_now) if direction == 1 else (b["h"] >= stop_now)
        hit_tp1 = (not tp1_done) and (
            (b["h"] >= tp1) if direction == 1 else (b["l"] <= tp1))
        hit_final = (b["h"] >= tp) if direction == 1 else (b["l"] <= tp)

        # پیش از TP1: اگر استاپ و TP1 در یک کندل → محافظه‌کارانه استاپ اول
        if not tp1_done:
            if hit_stop and not hit_tp1:
                # کلِ پوزیشن با -۱R خورد
                total = round(-1.0, 2)
                res = "loss"
                return (res, stop_now, total, k - filled_idx, filled_idx, fill_price, sl_used, _diag())
            if hit_stop and hit_tp1:
                # هر دو در یک کندل، پیش از TP1 → محافظه‌کارانه: استاپ اول
                return ("loss", stop_now, round(-1.0, 2), k - filled_idx,
                        filled_idx, fill_price, sl_used, _diag())
            if hit_tp1:
                booked_R += tp1_frac * tp1_R      # قفلِ سودِ پله‌ی اول
                remaining -= tp1_frac
                stop_now = fill_price             # مابقی → سربه‌سر (BE)
                tp1_done = True
                # ممکن است هدفِ اصلی هم در همین کندل خورده باشد
                if hit_final:
                    r_final = abs(tp - fill_price) / risk
                    total = round(booked_R + remaining * r_final, 2)
                    return ("win", tp, total, k - filled_idx, filled_idx, fill_price, sl_used, _diag())
                continue

        # پس از TP1: مابقی با استاپِ BE مدیریت می‌شود
        hit_be = (b["l"] <= stop_now) if direction == 1 else (b["h"] >= stop_now)
        if hit_be and hit_final:
            # محافظه‌کارانه: BE اول (مابقی سربه‌سر بسته)
            total = round(booked_R, 2)
            res = "win" if total > 0 else ("loss" if total < 0 else "be")
            return (res, stop_now, total, k - filled_idx, filled_idx, fill_price, sl_used, _diag())
        if hit_be:
            total = round(booked_R, 2)            # مابقی سربه‌سر → فقط سودِ TP1 می‌ماند
            res = "win" if total > 0 else "be"
            return (res, stop_now, total, k - filled_idx, filled_idx, fill_price, sl_used, _diag())
        if hit_final:
            r_final = abs(tp - fill_price) / risk
            total = round(booked_R + remaining * r_final, 2)
            return ("win", tp, total, k - filled_idx, filled_idx, fill_price, sl_used, _diag())
    return None  # تا انتهای داده نه هدف نه استاپ — معامله‌ی ناتمام، حساب نمی‌شود


_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _parse_when(s):
    """رشته‌ی تاریخ/زمان کاربر → epoch ثانیه (UTC). None اگر خالی.
    قالب‌های مجاز و منعطف: 'YYYY-MM-DD'، 'YYYY-MM-DD HH:MM'، epochِ خام.
    ارقامِ فارسی/عربی، و جداکننده‌های / یا . یا فاصله هم پذیرفته می‌شوند."""
    if s is None or str(s).strip() == "":
        return None
    s = str(s).strip().translate(_FA_DIGITS)  # ۱۴۰۵ → 1405، ارقامِ عربی هم
    if s.isdigit() and len(s) >= 9:            # epochِ خام (۹+ رقم)
        return int(s)
    # یکدست‌سازیِ جداکننده‌های تاریخ: / و . و _ → -
    norm = s.replace("/", "-").replace(".", "-").replace("_", "-")
    # حذفِ خط‌تیره‌های تکراری
    while "--" in norm:
        norm = norm.replace("--", "-")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H",
                "%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            dt = datetime.datetime.strptime(norm, fmt).replace(tzinfo=datetime.timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    raise ValueError(
        f"قالبِ تاریخِ نامعتبر: «{s}». نمونه‌های درست: 2026-08-13 یا "
        f"2026-08-13 14:30 (سالِ میلادی، با خط‌تیره یا اسلش). "
        f"تاریخ را از کادرِ پیشنهادیِ زیرِ فرم کپی کن.")


def suggest_range(symbol, style="day", tfs=None, walk=600):
    """بر اساسِ عمقِ پیمایشِ walk و دیتای در دسترسِ تایم‌فریمِ ورود،
    یک بازه‌ی پیشنهادیِ معتبر (from/to به‌صورتِ 'YYYY-MM-DD HH:MM') برمی‌گرداند
    تا کاربر بداند حداقل از چه تاریخی می‌تواند بازه انتخاب کند."""
    tf_map = {
        "scalp": ["1h", "30m", "15m", "5m"],   # فیکس S1: هم‌راستا با اپِ زنده
        "day":   ["1d", "4h", "1h", "15m"],
        "swing": ["1w", "1d", "4h", "1h"],
    }
    if tfs:
        tfs = [t.strip() for t in tfs if str(t).strip()]
    else:
        tfs = tf_map.get(style, tf_map["day"])
    ltf = tfs[-1]
    limit_map = {"1m": 5000, "5m": 8000, "15m": 8000, "30m": 6000, "1h": 6000,
                 "4h": 3000, "1d": 1500, "1w": 400}
    lim = limit_map.get(ltf, 500)
    src, sym, dsp, bars = EG.fetch(symbol, ltf, lim)
    if not bars or len(bars) < 80:
        return {"error": f"دیتای کافی برای {ltf} نیست ({len(bars) if bars else 0} کندل)."}

    def _fa(ts, with_time=True):
        dt = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M" if with_time else "%Y-%m-%d")

    n = len(bars)
    data_from = bars[0]["t"]
    data_to = bars[-1]["t"]
    # حداقلِ شروعِ معتبر برای عمقِ walk: کندلِ (n-walk) اگر داده کافی باشد،
    # وگرنه ۶۰ کندلِ اولِ داده (به‌خاطرِ نیازِ ساختار به سابقه).
    walk = max(100, int(walk or 600))
    idx = max(60, n - walk)
    walk_from = bars[idx]["t"]
    return {
        "symbol": dsp, "ltf": ltf, "timeframes": tfs, "walk": walk,
        "bars": n,
        "data_from": _fa(data_from),          # کهن‌ترین کندلِ در دسترس
        "data_to": _fa(data_to),              # تازه‌ترین کندل (پیشنهادِ «تا»)
        "suggested_from": _fa(walk_from),     # پیشنهادِ «از» برای عمقِ walk
        "suggested_to": _fa(data_to),
    }


def backtest(symbol, style="day", grades=("A+", "A", "B"),
             walk=350, fill_window=24, max_hold=400, side="both",
             tfs=None, date_from=None, date_to=None, verbose=False,
             require_stamp=False):
    """
    بک‌تستِ کاملِ walk-forward.
    style تعیینِ تایم‌فریم‌ها (همان نگاشتِ اپ): scalp/day/swing.
    grades: کدام درجه‌ها را به‌عنوانِ سیگنالِ قابلِ‌اجرا بپذیریم.
    walk: چند کندلِ آخرِ تایم‌فریمِ ورود را پیمایش کنیم (اگر بازه‌ی تاریخی داده نشود).
    side: جهتِ مجاز — "both" | "long" (صعودی) | "short" (نزولی).

    انتخابِ محدوده توسطِ کاربر (فرکتالی):
      tfs: لیستِ دلخواهِ تایم‌فریم‌ها مثلِ ["4h","1h","15m","5m"] که نگاشتِ style را
           می‌شکند — هر ترکیبی از HTF→LTF مجاز است (چون روش‌ها فرکتال‌اند و روی
           هر مقیاسی یکسان کار می‌کنند). tfs[0]=HTF بایاس، tfs[-1]=تایم‌فریمِ ورود.
      date_from/date_to: epochِ ثانیه (UTC). فقط سیگنال‌هایی که «اکنون»شان داخلِ این
           بازه است شبیه‌سازی می‌شوند — یعنی کاربر همان پنجره‌ای را که روی چارت
           انتخاب کرده بک‌تست می‌گیرد.
    """
    tf_map = {
        # فیکس S1: استکِ اسکالپ با اپِ زنده (app.STYLES) یکسان شد تا وین‌ریتِ بک‌تست
        # دقیقاً همان استکی را بازتاب دهد که اپ به کاربر پیشنهاد می‌دهد.
        "scalp": ["1h", "30m", "15m", "5m"],
        "day":   ["1d", "4h", "1h", "15m"],
        "swing": ["1w", "1d", "4h", "1h"],
    }
    # tfs دلخواهِ کاربر بر نگاشتِ style اولویت دارد (تاییدِ فرکتال‌بودن).
    if tfs:
        tfs = [t.strip() for t in tfs if str(t).strip()]
    else:
        tfs = tf_map.get(style, tf_map["day"])
    ltf = tfs[-1]

    # حداکثر کندلِ ممکن برای هر تایم‌فریم.
    # برای منابعِ صفحه‌بندی‌شونده (Binance) می‌توان بسیار عمیق‌تر رفت.
    limit_map = {"1m": 5000, "5m": 8000, "15m": 8000, "30m": 6000, "1h": 6000,
                 "4h": 3000, "1d": 1500, "1w": 400}

    series = {}
    disp = symbol
    for tf in tfs:
        lim = limit_map.get(tf, 500)
        src, sym, dsp, bars = EG.fetch(symbol, tf, lim)
        disp = dsp
        series[tf] = bars
        if verbose:
            print(f"[data] {tf}: {len(bars)} کندل  (منبع {src}, {dsp})", file=sys.stderr)
    series["_disp"] = disp

    entry_bars = series[ltf]
    if len(entry_bars) < 80:
        return {"error": f"دیتای کافی برای {ltf} نیست ({len(entry_bars)} کندل)."}

    n = len(entry_bars)

    # --- انتخابِ محدوده‌ی بک‌تست ---
    # اگر کاربر بازه‌ی تاریخی داد، ایندکس‌های شروع/پایانِ پیمایش را از روی زمان
    # پیدا کن؛ وگرنه به رفتارِ walk (N کندلِ آخر) برگرد.
    if date_from is not None or date_to is not None:
        data_lo = entry_bars[0]["t"]
        data_hi = entry_bars[-1]["t"]
        lo_i, hi_i = 0, n
        if date_from is not None:
            lo_i = 0
            while lo_i < n and entry_bars[lo_i]["t"] < date_from:
                lo_i += 1
        if date_to is not None:
            hi_i = 0
            for j in range(n - 1, -1, -1):
                if entry_bars[j]["t"] <= date_to:
                    hi_i = j + 1
                    break
        start = max(60, lo_i)
        end = min(n - 2, hi_i)
        if start >= end:
            def _fa(ts):
                return datetime.datetime.fromtimestamp(
                    ts, datetime.timezone.utc).strftime("%Y-%m-%d")
            return {"error": (
                f"بازه‌ی درخواستی با دیتای موجودِ {ltf} تقاطع ندارد. "
                f"دیتای در دسترس: {_fa(data_lo)} تا {_fa(data_hi)}. "
                f"برای بازه‌های قدیمی‌تر باید تایم‌فریمِ ورودِ بزرگ‌تر انتخاب کنی "
                f"(مثلاً tfs بدونِ 1m/5m/15m).")}
    else:
        start = max(60, n - walk)  # از این ایندکسِ LTF شروع به پیمایش کن
        end = n - 2

    trades = []
    i = start
    while i < end:
        t_now = entry_bars[i]["t"]
        d = _build_d(series, tfs, t_now)
        if d is None:
            i += 1
            continue
        try:
            r = CF.score(symbol, tfs, d=d)
        except Exception:
            i += 1
            continue

        plan = r.get("plan")
        grade = r.get("grade")
        stamp = (r.get("entry_stamp") or {}).get("stamped", False)
        # اگر require_stamp روشن باشد، فقط سیگنال‌هایی که مهرِ تاییدِ ورود خورده‌اند
        # (نمره>۷۰٪ + نفوذِ ۳۰٪ + تاییدِ چرخشِ LTF) وارد می‌شوند — دقیقاً همان مدلِ
        # عرضه/تقاضای ویدیو. این راهِ سنجشِ لبه‌ی ستاپِ افزوده است.
        if require_stamp and not stamp:
            i += 1
            continue
        if plan and grade in grades and plan.get("rr", 0) >= 2.0:
            direction = 1 if plan["direction"] == "صعودی" else -1
            # فیلترِ جهت: side=long فقط صعودی، side=short فقط نزولی
            if (side == "long" and direction != 1) or (side == "short" and direction != -1):
                i += 1
                continue
            sim = _simulate(entry_bars, i, direction,
                            plan["entry"], plan["sl"], plan["tp"],
                            plan.get("entry_type", "market"),
                            fill_window=fill_window, max_hold=max_hold)
            if sim is not None:
                result, exitp, rr_real, held, filled_idx, fill_price, sl_used, diag = sim
                t_sig = datetime.datetime.fromtimestamp(
                    t_now, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
                trades.append({
                    "time": t_sig,
                    "grade": grade,
                    "dir": plan["direction"],
                    "entry_type": plan.get("entry_type"),
                    "entry": plan["entry"], "fill": round(fill_price, 5),
                    "sl": round(sl_used, 5), "tp": plan["tp"],
                    "planned_rr": plan["rr"],
                    "result": result,
                    "r": rr_real,
                    "bars_held": held,
                    "mfe_R": diag["mfe_R"],
                    "mae_R": diag["mae_R"],
                })
                # جلو بپر تا انتهای این معامله (بدونِ هم‌پوشانی)
                i = filled_idx + held + 1
                continue
        i += 1

    return _summarize(disp, style, tfs, trades)


def _summarize(disp, style, tfs, trades):
    n = len(trades)
    # فیکس C18: با اسکیل‌اوت، «برد» یعنی هر بستنِ با R مثبت (شاملِ پله‌ی TP1 که
    # مابقی سربه‌سر خورد). «باخت» = R منفی. سربه‌سرِ کامل (R≈0) جدا شمرده می‌شود.
    wins = sum(1 for t in trades if t["r"] > 0)
    losses = sum(1 for t in trades if t["r"] < 0)
    scratch = n - wins - losses          # سربه‌سرِ کامل
    winrate = round(wins / n * 100, 1) if n else 0.0
    total_r = round(sum(t["r"] for t in trades), 2)
    avg_r = round(total_r / n, 2) if n else 0.0
    avg_win_r = round(sum(t["r"] for t in trades if t["r"] > 0) / wins, 2) if wins else 0.0
    avg_loss_r = round(sum(t["r"] for t in trades if t["r"] < 0) / losses, 2) if losses else 0.0
    # اکسپکتنسیِ صادقانه = میانگینِ R واقعیِ هر معامله (total_R / n). این تنها عددی
    # است که در واحدِ ریسک می‌گوید «هر معامله به‌طورِ متوسط چقدر ساخت» — نه فرمولِ
    # تقریبیِ win/loss که با اسکیل‌اوتِ کسری دیگر دقیق نیست.
    expectancy = avg_r

    # --- تفکیکِ وین‌ریت بر اساسِ نوعِ ورود و جهت (مورد ۳) ---
    def _seg(key_fn):
        agg = {}
        for t in trades:
            k = key_fn(t)
            a = agg.setdefault(k, {"n": 0, "w": 0, "R": 0.0})
            a["n"] += 1
            a["R"] += t["r"]
            if t["r"] > 0:
                a["w"] += 1
        return {k: {"trades": v["n"], "wins": v["w"],
                    "winrate_pct": round(v["w"] / v["n"] * 100, 1) if v["n"] else 0.0,
                    "total_R": round(v["R"], 2)}
                for k, v in agg.items()}

    by_entry = _seg(lambda t: t.get("entry_type") or "market")
    by_dir = _seg(lambda t: t.get("dir") or "?")
    # فیکس C15: تفکیکِ وین‌ریت بر پایه‌ی درجه (A+/A/B جدا) تا کیفیتِ خالص دیده شود؛
    # قاطی‌کردنِ Bها با A+ می‌تواند لبه‌ی واقعیِ درجه‌های بالا را رقیق و پنهان کند.
    by_grade = _seg(lambda t: t.get("grade") or "?")

    # --- پرچمِ کفایتِ نمونه (مورد ۲) ---
    MIN_TRADES = 20
    if n == 0:
        sample = {"ok": False, "level": "empty", "trades": n, "min": MIN_TRADES,
                  "msg": "هیچ معامله‌ای در این بازه پیدا نشد — نمونه‌ی خالی؛ "
                         "بازه را بزرگ‌تر کن یا سبک/تایم‌فریمِ دیگری امتحان کن."}
    elif n < MIN_TRADES:
        sample = {"ok": False, "level": "low", "trades": n, "min": MIN_TRADES,
                  "msg": (f"نمونه کوچک است ({n} معامله < {MIN_TRADES}) — وین‌ریت آماری "
                          f"معتبر نیست و می‌تواند گمراه‌کننده باشد. برای قضاوتِ درست، "
                          f"بازه‌ی بک‌تست را بزرگ‌تر کن یا عمقِ پیمایش را افزایش بده.")}
    else:
        sample = {"ok": True, "level": "ok", "trades": n, "min": MIN_TRADES,
                  "msg": f"نمونه‌ی کافی ({n} معامله) — نتیجه آماری قابلِ‌اتکاست."}

    return {
        "symbol": disp,
        "style": style,
        "timeframes": tfs,
        "range_from": trades[0]["time"] if trades else None,
        "range_to": trades[-1]["time"] if trades else None,
        "trades": n,
        "wins": wins,
        "losses": losses,
        "scratch": scratch,
        "winrate_pct": winrate,
        "total_R": total_r,
        "avg_R_per_trade": avg_r,
        "avg_win_R": avg_win_r,
        "avg_loss_R": avg_loss_r,
        "expectancy_R": expectancy,
        "by_entry_type": by_entry,
        "by_direction": by_dir,
        "by_grade": by_grade,
        "sample": sample,
        "trade_log": trades,
    }


def _fmt_fa(res):
    if "error" in res:
        return "خطا: " + res["error"]
    L = []
    L.append(f"نتیجه‌ی بک‌تست — {res['symbol']}  ·  سبک {res['style']}  ·  "
             + " ".join(res["timeframes"]))
    L.append("-" * 56)
    L.append(f"تعدادِ معاملات:        {res['trades']}")
    L.append(f"برد / باخت:           {res['wins']} / {res['losses']}")
    L.append(f"وین‌ریت:              {res['winrate_pct']}٪")
    L.append(f"مجموعِ R:             {res['total_R']}")
    L.append(f"میانگینِ R هر معامله:  {res['avg_R_per_trade']}")
    L.append(f"میانگینِ R بردها:      {res['avg_win_R']}")
    L.append(f"اکسپکتنسی (R):        {res['expectancy_R']}")
    L.append("-" * 56)
    if res["trades"] == 0:
        L.append("هیچ سیگنالِ واجدِ شرایطی در این بازه پیدا نشد — "
                 "معیارها سخت‌گیرند (درجه‌ی خوب + RR≥۱:۲ + پرشدنِ ورود).")
    else:
        L.append("چند معامله‌ی آخر:")
        for t in res["trade_log"][-8:]:
            mark = "برد " if t["result"] == "win" else "باخت"
            L.append(f"  {t['time']}  {t['dir']:<5} {mark} "
                     f"R={t['r']:<5} (پلن {t['planned_rr']}, {t['entry_type']})")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="بک‌تستِ walk-forward با اسکیل‌های تصحیح‌شده‌ی pipfound")
    ap.add_argument("symbol")
    ap.add_argument("--style", default="day", choices=["scalp", "day", "swing"])
    ap.add_argument("--grades", default="A+,A,B",
                    help="درجه‌های قابلِ‌قبول، جداشده با ویرگول")
    ap.add_argument("--walk", type=int, default=350)
    ap.add_argument("--fill-window", type=int, default=24)
    ap.add_argument("--max-hold", type=int, default=400)
    ap.add_argument("--side", default="both", choices=["both", "long", "short"],
                    help="جهتِ معاملات: both/long(صعودی)/short(نزولی)")
    ap.add_argument("--tfs", default="",
                    help="تایم‌فریم‌های دلخواه با ویرگول، HTF→LTF (مثل 4h,1h,15m,5m). "
                         "نگاشتِ --style را می‌شکند؛ تاییدِ فرکتال‌بودن.")
    ap.add_argument("--from", dest="date_from", default="",
                    help="شروعِ بازه‌ی بک‌تست: YYYY-MM-DD یا 'YYYY-MM-DD HH:MM' (UTC)")
    ap.add_argument("--to", dest="date_to", default="",
                    help="پایانِ بازه‌ی بک‌تست: YYYY-MM-DD یا 'YYYY-MM-DD HH:MM' (UTC)")
    ap.add_argument("--require-stamp", action="store_true",
                    help="فقط سیگنال‌های مهرخورده (مدلِ عرضه/تقاضا: نمره>۷۰٪ + نفوذِ ۳۰٪ + تاییدِ چرخشِ LTF)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    grades = tuple(g.strip() for g in a.grades.split(",") if g.strip())
    tfs = [t.strip() for t in a.tfs.split(",") if t.strip()] or None
    try:
        date_from = _parse_when(a.date_from)
        date_to = _parse_when(a.date_to)
    except ValueError as ex:
        print(json.dumps({"error": str(ex)}, ensure_ascii=False) if a.json else f"خطا: {ex}")
        return
    res = backtest(a.symbol, style=a.style, grades=grades,
                   walk=a.walk, fill_window=a.fill_window,
                   max_hold=a.max_hold, side=a.side,
                   tfs=tfs, date_from=date_from, date_to=date_to,
                   verbose=a.verbose, require_stamp=a.require_stamp)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(_fmt_fa(res))


if __name__ == "__main__":
    main()
