#!/usr/bin/env python3
"""
Confluence Scorer — top-down multi-timeframe ICT/SMC setup grader.

Runs smc_engine across HTF->LTF (default 1d,4h,1h,15m), then scores the
setup on a rules-based checklist a smart-money / price-action trader
actually uses, and returns a grade (A+, A, B, C, no-trade) with the exact
reasons for and against. Removes guesswork from "is this a good setup?".

Pure stdlib. Calls smc_engine.analyze() in-process (no extra fetch code).

Usage:
  python3 confluence.py XAUUSD
  python3 confluence.py EURUSD --tfs 4h,1h,15m
  python3 confluence.py BTCUSDT --json
"""
import sys, os, json, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smc_engine as E
try:
    import macro_context as M
except Exception:
    M = None


def _d(x):
    """Farsi-friendly rounding for prices in details/plan strings."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return x
    if abs(x) >= 1000:
        return round(x, 1)
    if abs(x) >= 10:
        return round(x, 3)
    return round(x, 5)


def _bias(trend, choch, bos):
    """Directional lean of a single timeframe: +1 bull, -1 bear, 0 neutral."""
    score = 0
    if trend == "up": score += 1
    elif trend == "down": score -= 1
    # a fresh CHoCH flips/confirms bias
    if choch:
        if "bullish" in choch[0]: score += 1
        elif "bearish" in choch[0]: score -= 1
    if bos:
        if "bullish" in bos[0]: score += 0.5
        elif "bearish" in bos[0]: score -= 0.5
    if score > 0: return 1
    if score < 0: return -1
    return 0


def scan(symbol, tfs):
    data = {}
    for tf in tfs:
        try:
            data[tf] = E.analyze(symbol, tf)
        except Exception as ex:
            data[tf] = {"error": str(ex)}
    return data


def ote_zone(pd, direction, price):
    """ناحیه‌ی OTE (Optimal Trade Entry) = ۰.۶۲ تا ۰.۷۹ فیبِ رِنجِ فعلی.
    برای خرید (صعودی): OTE در دیسکانت (پایینِ رِنج) — ارزان.
    برای فروش (نزولی): OTE در پریمیوم (بالای رِنج) — گران.
    برمی‌گرداند: dict با low/high ناحیه، آیا قیمت داخلِ آن است، و درصدِ فیب.
    """
    if not pd or direction == 0 or price is None:
        return None
    top = pd.get("range_top")
    bot = pd.get("range_bottom")
    if top is None or bot is None or top <= bot:
        return None
    rng = top - bot
    # اصلاحِ مفهومیِ ICT: OTE = ۰.۶۲–۰.۷۹ رتریسمنتِ حرکت. برای خرید، رتریسِ ۶۲–۷۹٪
    # قیمت را به **پایینِ رِنج (دیسکانت)** می‌آورد — یعنی bot + (۰.۲۱ تا ۰.۳۸)×رِنج،
    # نه ۶۲–۷۹٪ بالای کف. (مطابقِ چارتِ مرجعِ کاربر: فیبِ ۰.۶۱۸=۴۱۸۳ زیرِ ۰.۵=۴۲۳۴.)
    if direction == 1:  # خرید → دیسکانتِ OTE (پایینِ رِنج، ورودِ ارزان)
        lo = round(bot + rng * 0.21, 5)   # معادلِ رتریسِ ۰.۷۹
        hi = round(bot + rng * 0.38, 5)   # معادلِ رتریسِ ۰.۶۲
    else:               # فروش → پریمیومِ OTE (بالای رِنج، ورودِ گران)
        lo = round(top - rng * 0.38, 5)
        hi = round(top - rng * 0.21, 5)
    inside = lo <= price <= hi
    # درصدِ فیبِ قیمتِ فعلی نسبت به کفِ رِنج (۰=کف، ۱۰۰=سقف)
    fib_pct = round((price - bot) / rng * 100, 1) if rng > 0 else None
    return {"low": lo, "high": hi, "inside": inside, "fib_pct": fib_pct,
            "range_top": round(top, 5), "range_bottom": round(bot, 5)}


def score(symbol, tfs, d=None):
    d = scan(symbol, tfs) if d is None else d
    htf, mtf = tfs[0], tfs[1] if len(tfs) > 1 else tfs[0]
    ltf = tfs[-1]

    checklist = []  # each row: {name, status, weight, got, detail}
    pts = 0.0

    def row(name, ok, weight, detail):
        """ok: True (✓), False (✗), or None (— neutral/n-a)."""
        nonlocal pts
        got = weight if ok is True else 0.0
        pts += got
        checklist.append({
            "name": name,
            "status": "✓" if ok is True else ("✗" if ok is False else "—"),
            "weight": weight,
            "got": got,
            "detail": detail,
        })

    biases = {tf: _bias(x.get("trend"), x.get("CHoCH"), x.get("BOS"))
              for tf, x in d.items() if "error" not in x}
    htf_bias = biases.get(htf, 0)
    mtf_bias = biases.get(mtf, 0)
    ltf_bias = biases.get(ltf, 0)

    bias_word = {1: "صعودی", -1: "نزولی", 0: "خنثی"}
    direction = htf_bias or mtf_bias

    # قیمتِ زنده روی تایم‌فریمِ ورود
    price = d.get(ltf, {}).get("last_price")
    # ناحیه‌ی پریمیوم/دیسکانت و OTE باید روی دیلینگ‌رِنجِ قابلِ‌معامله لنگر شود.
    # بایاس از HTF می‌آید، اما رِنجِ پولبکِ ورود روی MTF فریم می‌شود (رِنجِ ۴س برای
    # سبکِ دِی) — وگرنه لیمیتِ OTE روی رِنجِ عظیمِ روزانه جایی می‌افتد که قیمت در
    # افقِ معامله هرگز به آن پولبک نمی‌زند. اولویت: mtf، سپس htf، سپس ltf.
    pd_tf = None
    for _t in (mtf, htf):
        _pd = d.get(_t, {}).get("premium_discount")
        if _pd and _pd.get("range_top") and _pd.get("range_bottom") \
           and _pd["range_top"] > _pd["range_bottom"]:
            pd_tf = _t
            break
    pd_tf = pd_tf or ltf
    pd_src = d.get(pd_tf, {}).get("premium_discount") or {}
    ote = ote_zone(pd_src, direction, price)

    # --- 1. HTF bias clarity ---
    row("بایاسِ تایم‌فریم بالا واضح", htf_bias != 0, 1.0,
        f"{htf} = {bias_word[htf_bias]}" if htf_bias else f"{htf} خنثی/رِنج — لبه‌ی جهت‌دار ضعیف")

    # --- 2. Multi-TF alignment ---
    aligned = [b for b in (htf_bias, mtf_bias, ltf_bias) if b == direction and b != 0]
    if direction != 0 and len(aligned) >= 3:
        row("هم‌راستاییِ چند تایم‌فریم", True, 2.0, "هر سه تایم‌فریم هم‌جهت (تاپ‌داون کامل)")
    elif direction != 0 and len(aligned) == 2:
        # partial credit: register weight 2 but got 1
        checklist.append({"name": "هم‌راستاییِ چند تایم‌فریم", "status": "◐",
                          "weight": 2.0, "got": 1.0, "detail": "دو تایم‌فریم از سه هم‌جهت"})
        pts += 1.0
    elif direction != 0 and mtf_bias == -direction:
        row("هم‌راستاییِ چند تایم‌فریم", False, 2.0, f"تضاد: {mtf} خلافِ جهتِ تایم‌فریم بالا")
    else:
        row("هم‌راستاییِ چند تایم‌فریم", False, 2.0, "تایم‌فریم‌ها هم‌جهت نیستند")

    # --- 3. Price in the right PD zone (لنگر روی تایم‌فریمِ بالا) ---
    ltf_pd = pd_src
    zone = ltf_pd.get("zone")
    pct = ltf_pd.get("price_pct")
    if direction == 1:
        ok = zone == "discount"
        det = f"{pd_tf} در {'دیسکانت (ورودِ ارزان)' if ok else 'پریمیوم (خریدِ گران — پولبک لازم)'}"
        row("پریمیوم/دیسکانتِ درست", ok, 1.5, f"{det}"+(f" — {pct}٪ رِنج" if pct is not None else ""))
    elif direction == -1:
        ok = zone == "premium"
        det = f"{pd_tf} در {'پریمیوم (ورودِ گران)' if ok else 'دیسکانت (فروشِ ارزان — پولبک لازم)'}"
        row("پریمیوم/دیسکانتِ درست", ok, 1.5, f"{det}"+(f" — {pct}٪ رِنج" if pct is not None else ""))
    else:
        row("پریمیوم/دیسکانتِ درست", None, 1.5, "بدونِ جهت، سنجش بی‌معنی")

    # --- 3b. OTE (Optimal Trade Entry): آیا قیمت در ناحیه‌ی ۰.۶۲–۰.۷۹ فیب است؟ ---
    if direction != 0 and ote:
        act = "خرید" if direction == 1 else "فروش"
        if ote["inside"]:
            row("ناحیه‌ی OTE (۰.۶۲–۰.۷۹ فیب)", True, 1.0,
                f"✅ قیمت داخلِ ناحیه‌ی موفقِ {act} است ({_d(ote['low'])}–{_d(ote['high'])}) "
                f"— فیبِ فعلی {ote['fib_pct']}٪. ورودِ باکیفیت.")
        else:
            side = "پریمیومِ گران (بالای OTE)" if (direction == 1 and ote["fib_pct"] and ote["fib_pct"] > 79) \
                else ("زیرِ ناحیه (خیلی ارزان/عمیق)" if direction == 1
                      else ("دیسکانتِ ارزان (زیرِ OTE)" if ote["fib_pct"] and ote["fib_pct"] < 21
                            else "بالای ناحیه"))
            row("ناحیه‌ی OTE (۰.۶۲–۰.۷۹ فیب)", False, 1.0,
                f"⛔ قیمت بیرونِ ناحیه‌ی موفق است — الان در {side} (فیبِ {ote['fib_pct']}٪). "
                f"ناحیه‌ی بهترِ {act}: {_d(ote['low'])}–{_d(ote['high'])}. صبر برای پولبک.")
    elif direction != 0:
        row("ناحیه‌ی OTE (۰.۶۲–۰.۷۹ فیب)", None, 1.0, "رِنجِ معتبری برای فیب یافت نشد")

    # --- 4. Fresh liquidity sweep in trade direction ---
    ltf_sweeps = d.get(ltf, {}).get("liquidity_sweeps") or []
    fresh_sweep = None
    for s in ltf_sweeps:
        if s.get("bar_from_end", 99) <= 5:
            if direction == 1 and s["type"] == "bullish_sweep":
                fresh_sweep = s; break
            if direction == -1 and s["type"] == "bearish_sweep":
                fresh_sweep = s; break
    if fresh_sweep:
        row("سوئیپِ لیکوئیدیتیِ تازه (تریگر)", True, 1.5,
            f"سوئیپِ هم‌جهت روی {fresh_sweep['level']} ({ltf})")
    else:
        row("سوئیپِ لیکوئیدیتیِ تازه (تریگر)", False, 1.5,
            "سوئیپِ تازه‌ی هم‌جهت دیده نشد — منتظرِ تریگر")

    # --- 5. Fresh CHoCH on LTF ---
    ltf_choch = d.get(ltf, {}).get("CHoCH")
    if ltf_choch and direction == 1 and "bullish" in ltf_choch[0]:
        row("چاکِ ساختاری روی LTF", True, 1.0, f"چاکِ صعودیِ تازه روی {ltf}")
    elif ltf_choch and direction == -1 and "bearish" in ltf_choch[0]:
        row("چاکِ ساختاری روی LTF", True, 1.0, f"چاکِ نزولیِ تازه روی {ltf}")
    else:
        row("چاکِ ساختاری روی LTF", False, 1.0, "چاکِ هم‌جهتِ تازه‌ای روی LTF نیست")

    # --- 6. Displacement ---
    ltf_disp = d.get(ltf, {}).get("displacement") or {}
    if ltf_disp.get("present"):
        dd = ltf_disp["direction"]
        ok = (direction == 1 and dd == "bullish") or (direction == -1 and dd == "bearish")
        row("دیسپلیسمنت (حرکتِ نهادی)", ok, 1.0,
            f"دیسپلیسمنتِ {'هم‌جهت' if ok else 'خلاف‌جهت'} روی {ltf} ({ltf_disp.get('body_x_avg')}× میانگین)")
    else:
        row("دیسپلیسمنت (حرکتِ نهادی)", False, 1.0, "حرکتِ نهادیِ پرقدرتِ اخیر نیست")

    # --- 7. POI present (روی تایمِ ورود و همچنین دیلینگ‌رِنجِ تایم‌فریمِ بالا) ---
    want = "bullish" if direction == 1 else "bearish"
    ltf_obs = d.get(ltf, {}).get("order_blocks") or []
    ltf_fvgs = d.get(ltf, {}).get("FVG_unfilled") or []
    poi_ob = next((o for o in ltf_obs if o["type"] == want), None)
    poi_fvg = next((f for f in ltf_fvgs if f["type"] == want), None)
    poi_tf = ltf
    # اگر روی تایمِ ورود POI هم‌جهت نبود، تایم‌فریمِ بالا را هم بگرد (فیرولیوگپ/اوبیِ روزانه).
    if not (poi_ob or poi_fvg):
        for _t in (htf, mtf):
            if _t == ltf:
                continue
            _obs = [o for o in (d.get(_t, {}).get("order_blocks") or []) if o["type"] == want]
            _fvs = [f for f in (d.get(_t, {}).get("FVG_unfilled") or []) if f["type"] == want]
            if _obs or _fvs:
                poi_ob = poi_ob or (_obs[0] if _obs else None)
                poi_fvg = poi_fvg or (_fvs[0] if _fvs else None)
                poi_tf = _t
                break
    has_poi = bool(poi_ob or poi_fvg)
    if direction != 0:
        poi_txt = []
        if poi_ob: poi_txt.append(f"اردر بلاک {_d(poi_ob['bottom'])}–{_d(poi_ob['top'])}")
        if poi_fvg: poi_txt.append(f"فیرولیوگپ {_d(poi_fvg['bottom'])}–{_d(poi_fvg['top'])}")
        suffix = f" ({poi_tf})" if poi_txt else ""
        row("نقطه‌ی ورود (اردر بلاک/فیرولیوگپ)", has_poi, 0.5,
            ((" | ".join(poi_txt) + suffix) if poi_txt else f"POIِ {bias_word[direction]} روی تایم‌فریم‌ها نیست"))
    else:
        row("نقطه‌ی ورود (اردر بلاک/فیرولیوگپ)", None, 0.5, "بدونِ جهت")

    # --- 8. HTF POI confluence (does price sit at an HTF OB/FVG too?) ---
    htf_conf = False
    htf_conf_txt = "قیمت روی POIِ تایم‌فریم بالا نیست"
    if direction != 0 and price is not None:
        for tf_ in (htf, mtf):
            obs = d.get(tf_, {}).get("order_blocks") or []
            fvs = d.get(tf_, {}).get("FVG_unfilled") or []
            for z in obs + fvs:
                if z.get("type") == want and z["bottom"] <= price <= z["top"]:
                    htf_conf = True
                    htf_conf_txt = f"قیمت داخلِ POIِ {tf_} ({_d(z['bottom'])}–{_d(z['top'])}) — کانفلوئنسِ HTF"
                    break
            if htf_conf: break
    if direction != 0:
        row("کانفلوئنسِ POIِ تایم‌فریم بالا", htf_conf, 1.0, htf_conf_txt)
    else:
        row("کانفلوئنسِ POIِ تایم‌فریم بالا", None, 1.0, "بدونِ جهت")

    # --- 9. Killzone / session timing (ICT: entries land in a killzone) ---
    kz = d.get(ltf, {}).get("killzone", "")
    in_kz = bool(kz) and "Outside" not in kz and "outside" not in kz
    row("کیل‌زون / تایمینگِ سشن", in_kz, 0.5,
        (f"داخلِ کیل‌زون: {kz}" if in_kz else f"خارج از کیل‌زونِ اصلی ({kz}) — احتمالِ پایین‌تر"))

    # --- 10. Macro news gate (don't enter into high-impact news) ---
    gate_status = None
    if M is not None:
        try:
            cal = M.get_calendar()
            ccys = M.symbol_ccys(symbol)
            gate_status, gate_advice, _ = M.news_gate(cal, ccys)
        except Exception:
            gate_status = None
    if gate_status == "GREEN":
        row("گیتِ اخبارِ کلان", True, 0.5, "پنجره‌ی عادی — خبرِ های‌ایمپکتِ نزدیک نیست")
    elif gate_status == "AMBER":
        checklist.append({"name": "گیتِ اخبارِ کلان", "status": "◐", "weight": 0.5,
                          "got": 0.25, "detail": "خبرِ مدیوم نزدیک — سایز کمتر / استاپ پهن‌تر"})
        pts += 0.25
    elif gate_status == "RED":
        row("گیتِ اخبارِ کلان", False, 0.5,
            "خبرِ های‌ایمپکت در پنجره‌ی ۱ساعته — ورودِ جدید ممنوع، صبر کن")
    else:
        row("گیتِ اخبارِ کلان", None, 0.5, "تقویم در دسترس نیست")

    # --- 11. RR feasibility (from a VALID location to the next liquidity target) ---
    # اصلاح: ورود دیگر کورکورانه از میدِ POIِ تایمِ ورود گرفته نمی‌شود. اگر قیمت
    # در ناحیه‌ی OTE/دیسکانتِ درست باشد → ورودِ بازار؛ در غیرِ این‌صورت پلن به‌صورتِ
    # «لیمیت در OTE» (منتظرِ پولبک) ساخته می‌شود، نه چیسِ قله. استاپ حداقل‌فاصله دارد
    # تا RRِ جعلی تولید نشود؛ هدف باید واقعاً در جهتِ معامله باشد وگرنه نامعتبر است.
    rr_ok = None
    rr_txt = "بدونِ جهت یا POI — RR قابلِ محاسبه نیست"
    plan = None
    if direction != 0 and has_poi and price is not None:
        z = poi_ob or poi_fvg
        poi_mid = (z["top"] + z["bottom"]) / 2
        liq = d.get(poi_tf, {}).get("liquidity") or d.get(ltf, {}).get("liquidity") or {}
        pd = pd_src or d.get(ltf, {}).get("premium_discount") or {}
        in_ote = bool(ote and ote.get("inside"))
        if in_ote:
            entry = round(poi_mid, 5); entry_type = "market"
        elif ote:
            # ورود را روی میدِ ناحیه‌ی OTE بگذار (لیمیت؛ منتظرِ پولبک به دیسکانت/پریمیوم)
            entry = round((ote["low"] + ote["high"]) / 2, 5); entry_type = "limit_ote"
        else:
            entry = round(poi_mid, 5); entry_type = "market"
        if direction == 1:
            struct_low = min(z["bottom"], ote["low"] if ote else z["bottom"])
            sl = round(struct_low * 0.999, 5)
            # هدف = نزدیک‌ترین لیکوئیدیتیِ مقابل (بای‌ساید/سقفِ مساوی) بالاتر از ورود،
            # نه لبه‌ی دورِ کلِ رِنج (که RRِ خیالی ۱:۱۵ می‌سازد). فقط اگر هیچ لیکوئیدیتیِ
            # میانی نبود، به لبه‌ی رِنج پس‌افت می‌کنیم.
            cands = [x for x in (liq.get("buyside_eqh") or []) if x and x > entry * 1.001]
            rh = liq.get("range_high") or pd.get("range_top")
            if rh and rh > entry * 1.001:
                cands.append(rh)
            tp = min(cands) if cands else None
        else:
            struct_high = max(z["top"], ote["high"] if ote else z["top"])
            sl = round(struct_high * 1.001, 5)
            cands = [x for x in (liq.get("sellside_eql") or []) if x and x < entry * 0.999]
            rl = liq.get("range_low") or pd.get("range_bottom")
            if rl and rl < entry * 0.999:
                cands.append(rl)
            tp = max(cands) if cands else None
        # حداقلِ فاصله‌ی استاپ = ۰.۱۵٪ قیمت تا RRِ خیالی تولید نشود
        min_stop = abs(price) * 0.0015
        if abs(entry - sl) < min_stop:
            sl = round(entry - min_stop, 5) if direction == 1 else round(entry + min_stop, 5)
        if tp:
            valid_tp = (direction == 1 and tp > entry) or (direction == -1 and tp < entry)
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            rr = round(reward / risk, 2) if risk > 0 else 0
            if not valid_tp:
                rr_ok = False
                rr_txt = (f"هدفِ نامعتبر ({_d(tp)}) — در جهتِ معامله فراتر از ورود نیست؛ "
                          f"RRِ واقعی وجود ندارد. منتظرِ ساختارِ تازه بمان.")
            else:
                rr_ok = rr >= 2.0
                lbl = "ورودِ بازار" if entry_type == "market" else "لیمیت در OTE (منتظرِ پولبک)"
                rr_txt = f"RR ≈ ۱:{rr} ({lbl}: ورود {_d(entry)} / استاپ {_d(sl)} / هدف {_d(tp)})"
                plan = {"direction": bias_word[direction], "entry": entry, "sl": sl,
                        "tp": round(tp, 5), "rr": rr, "entry_type": entry_type}
    row("امکانِ RR ≥ ۱:۲", rr_ok, 1.0, rr_txt)

    # --- grade (normalized to % of max, so adding factors won't inflate grades) ---
    max_score = sum(c["weight"] for c in checklist)
    ratio = (pts / max_score) if max_score else 0
    # hard gate: a HTF-vs-MTF conflict caps the grade regardless of score
    conflict = direction != 0 and mtf_bias == -direction
    # location gate: خرید در پریمیوم یا فروش در دیسکانت = بدترین اشتباهِ آماتوری.
    # اگر هم زونِ PD غلط باشد و هم قیمت بیرونِ OTE، سقفِ درجه = C (فقط واچ).
    wrong_zone = False
    if direction == 1 and zone == "premium":
        wrong_zone = True
    elif direction == -1 and zone == "discount":
        wrong_zone = True
    ote_failed = bool(ote) and not ote.get("inside", False)
    location_bad = wrong_zone and ote_failed
    if direction == 0:
        grade = "بدونِ معامله"
        verdict = "بایاس نامشخص است؛ منتظرِ ساختارِ واضح بمان."
    elif location_bad:
        # قیمت در محلِ اشتباه است — حتی با ساختارِ خوب، ورودِ الان ممنوع
        grade = "C"
        act = "خرید" if direction == 1 else "فروش"
        verdict = (f"ساختار {bias_word[direction]} است اما قیمت در محلِ اشتباه برای {act} است "
                   f"(زونِ غلط + بیرونِ OTE). ورودِ الان چیسِ قیمت است — واچ کن و منتظرِ "
                   f"پولبک به ناحیه‌ی OTE بمان.")
    elif ratio >= 0.85 and not conflict:
        grade = "A+"; verdict = "ستاپِ درجه‌یکِ هم‌راستا با همه‌ی شرایطِ اسمارت‌مانی — قابلِ اجرا."
    elif ratio >= 0.70 and not conflict:
        grade = "A"; verdict = "ستاپِ قوی؛ اکثرِ شرایط برقرار است — با مدیریتِ ریسکِ عادی قابلِ اجرا."
    elif ratio >= 0.50:
        grade = "B"; verdict = ("ستاپِ متوسط؛ " + ("تضادِ تایم‌فریمی هست — " if conflict else "")
                                + "نیازمندِ تأییدِ بیشتر (سوئیپ/چاکِ LTF) یا ریسکِ کمتر.")
    elif ratio >= 0.30:
        grade = "C"; verdict = "ستاپِ ضعیف؛ بهتر است واچ شود، ورود توصیه نمی‌شود."
    else:
        grade = "بدونِ معامله"; verdict = "شرایطِ کافی برقرار نیست — صبر کن."

    return {
        "symbol": symbol,
        "timeframes": tfs,
        "direction": bias_word[direction] if direction else "نامشخص",
        "score": round(pts, 1),
        "max_score": round(max_score, 1),
        "grade": grade,
        "verdict": verdict,
        "bias_by_tf": {tf: bias_word[b] for tf, b in biases.items()},
        "checklist": checklist,
        "last_price": d.get(ltf, {}).get("last_price"),
        "plan": plan,
        "ote": ote,
        "killzone": d.get(ltf, {}).get("killzone"),
        "news_gate": gate_status,
    }


def _fmt_table(r):
    """Render the checklist as a monospace-aligned box table for the terminal."""
    lines = []
    lines.append(f"نماد: {r['symbol']}   جهت: {r['direction']}   قیمت: {r['last_price']}")
    lines.append(f"امتیاز: {r['score']}/{r['max_score']}   درجه: {r['grade']}")
    lines.append("بایاسِ تایم‌فریم‌ها: " + "  ".join(f"{k}={v}" for k, v in r["bias_by_tf"].items()))
    lines.append("")
    header = f"{'وضعیت':<6}{'امتیاز':<10}معیار / جزئیات"
    lines.append(header)
    lines.append("-" * 60)
    for c in r["checklist"]:
        lines.append(f"{c['status']:<6}{c['got']}/{c['weight']:<6}{c['name']}")
        lines.append(f"{'':<16}└ {c['detail']}")
    lines.append("-" * 60)
    lines.append(f"حکم: {r['verdict']}")
    return "\n".join(lines)


def _kz_fa(kz):
    """Translate the engine's English killzone label to Farsi."""
    if not kz:
        return None
    m = {
        "London Open": "کیل‌زونِ اوپنِ لندن (۰۲:۰۰–۰۵:۰۰ ET)",
        "New York AM": "کیل‌زونِ نیویورک صبح (۰۸:۳۰–۱۱:۰۰ ET)",
        "London Close": "کیل‌زونِ کلوزِ لندن (۱۰:۰۰–۱۲:۰۰ ET)",
        "New York PM": "کیل‌زونِ نیویورک بعدازظهر (۱۳:۰۰–۱۶:۰۰ ET)",
        "Asian Range": "رِنجِ آسیایی (۱۹:۰۰–۲۴:۰۰ ET)",
    }
    for k, v in m.items():
        if k in kz:
            return v
    return "خارج از کیل‌زونِ اصلی"


def _digits(x):
    """Farsi rounding: FX/metals to ~3 decimals, crypto to whole/1 decimal."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return x
    if abs(x) >= 1000:
        return round(x, 1)
    if abs(x) >= 10:
        return round(x, 3)
    return round(x, 5)


def _fmt_markdown(r):
    """Render as a GitHub-flavored markdown table (for chat rendering)."""
    out = []
    out.append(f"**{r['symbol']}** — جهت: **{r['direction']}** · قیمت: `{_digits(r['last_price'])}`  ")
    out.append(f"امتیاز: **{r['score']}/{r['max_score']}** → درجه: **{r['grade']}**\n")
    # bias-by-timeframe strip
    if r.get("bias_by_tf"):
        strip = " · ".join(f"{k}={v}" for k, v in r["bias_by_tf"].items())
        out.append(f"بایاسِ تایم‌فریم‌ها: {strip}\n")
    out.append("| وضعیت | معیار | امتیاز | جزئیات |")
    out.append("|:---:|:---|:---:|:---|")
    for c in r["checklist"]:
        out.append(f"| {c['status']} | {c['name']} | {c['got']}/{c['weight']} | {c['detail']} |")
    # trade plan block
    p = r.get("plan")
    if p:
        out.append(f"\n**پلنِ پیشنهادی ({p['direction']}):** ورود `{_digits(p['entry'])}` · "
                   f"استاپ `{_digits(p['sl'])}` · هدف `{_digits(p['tp'])}` · RR ≈ **۱:{p['rr']}**")
    kz = _kz_fa(r.get("killzone"))
    if kz:
        out.append(f"\n🕐 کیل‌زون: {kz}")
    out.append(f"\n> {r['verdict']}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--tfs", default="1d,4h,1h,15m",
                    help="comma-separated, HTF first (default 1d,4h,1h,15m)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--md", action="store_true", help="markdown table output")
    a = ap.parse_args()
    tfs = [t.strip() for t in a.tfs.split(",") if t.strip()]
    r = score(a.symbol, tfs)
    if a.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    elif a.md:
        print(_fmt_markdown(r))
    else:
        print(_fmt_table(r))


if __name__ == "__main__":
    main()
