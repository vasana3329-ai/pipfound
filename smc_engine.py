#!/usr/bin/env python3
"""
SMC/ICT Structure Engine — pure stdlib, no external deps.
Fetches OHLC (crypto via Binance, forex/gold via Yahoo) and detects
market structure features used in Smart Money Concepts / ICT analysis.

Usage:
  python3 smc_engine.py <SYMBOL> [--tf 1h] [--limit 300] [--json]
  python3 smc_engine.py BTCUSDT --tf 4h
  python3 smc_engine.py EURUSD --tf 1h
  python3 smc_engine.py XAUUSD --tf 15m

Symbol resolution:
  - Crypto pairs ending in USDT/USDC/BTC/ETH  -> Binance
  - EURUSD/GBPUSD/... (6 letters, forex)      -> Yahoo (EURUSD=X)
  - XAUUSD / GOLD                             -> Yahoo (GC=F)
"""
import sys, json, urllib.request, urllib.parse, argparse, datetime, math, ssl

UA = {"User-Agent": "Mozilla/5.0"}

def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        try:
            return ssl.create_default_context()
        except Exception:
            c=ssl.create_default_context(); c.check_hostname=False; c.verify_mode=ssl.CERT_NONE
            return c
_CTX=_ssl_ctx()

# ---- timeframe maps ----
BINANCE_TF = {"1m":"1m","5m":"5m","15m":"15m","30m":"30m","1h":"1h","4h":"4h","1d":"1d","1w":"1w"}
YF_TF = {"1m":"1m","5m":"5m","15m":"15m","30m":"30m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk"}
YF_RANGE = {"1m":"5d","5m":"1mo","15m":"1mo","30m":"1mo","1h":"3mo","4h":"3mo","1d":"2y","1w":"5y"}

FX_MAJORS = {"EURUSD","GBPUSD","USDJPY","USDCHF","USDCAD","AUDUSD","NZDUSD",
             "EURJPY","GBPJPY","EURGBP","EURAUD","AUDJPY","EURCHF","GBPCHF"}

def http_get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20, context=_CTX) as r:
        return json.loads(r.read().decode())

# نگاشتِ نمادِ اسپاتِ فلزات → gold-api.com (رایگان، بدون کلید)
_SPOT_MAP = {"XAUUSD":"XAU","GOLD":"XAU","XAU":"XAU",
             "XAGUSD":"XAG","SILVER":"XAG","XAG":"XAG"}
_SPOT_CACHE = {}

def _spot_price(disp):
    """قیمتِ اسپاتِ زنده‌ی فلز (فقط طلا/نقره). کش ۶۰ ثانیه‌ای؛ خطا→None."""
    key=_SPOT_MAP.get((disp or "").upper())
    if not key: return None
    now=datetime.datetime.now().timestamp()
    c=_SPOT_CACHE.get(key)
    if c and now-c[0]<60: return c[1]
    try:
        d=http_get(f"https://api.gold-api.com/price/{key}")
        p=float(d["price"])
        _SPOT_CACHE[key]=(now,p)
        return p
    except Exception:
        return c[1] if c else None

def resolve(symbol):
    s = symbol.upper().replace("/","").replace("-","")
    if s in ("XAUUSD","GOLD","XAU"): return ("yahoo","GC=F",s)
    if s in ("XAGUSD","SILVER"):     return ("yahoo","SI=F",s)
    if s in ("XPTUSD","PLATINUM","XPT"): return ("yahoo","PL=F",s)
    if s in ("XPDUSD","PALLADIUM","XPD"): return ("yahoo","PA=F",s)
    if s in ("WTI","USOIL","CRUDE","CL"): return ("yahoo","CL=F",s)
    if s in ("BRENT","UKOIL"): return ("yahoo","BZ=F",s)
    if s.endswith(("USDT","USDC","BUSD")) or (s.endswith(("BTC","ETH")) and len(s)>6):
        return ("binance", s, s)
    if s in FX_MAJORS or (len(s)==6 and s.isalpha()):
        return ("yahoo", s+"=X", s)
    # default: try binance
    return ("binance", s, s)

def fetch_binance(sym, tf, limit):
    itv = BINANCE_TF.get(tf, "1h")
    hosts = ["https://api.binance.com","https://api.binance.us","https://data-api.binance.vision"]
    # صفحه‌بندیِ تاریخی: Binance حداکثر ۱۰۰۰ کندل در هر درخواست می‌دهد.
    # برای limitِ بزرگ‌تر، به عقب حلقه می‌زنیم با endTime = قدیمی‌ترین کندلِ گرفته‌شده.
    _MS = {"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"1d":86400,"1w":604800}
    step_s = _MS.get(tf, 3600)
    last_err=None
    for h in hosts:
        try:
            collected = {}   # t -> bar  (کلید = زمان، جلوی تکرار را می‌گیرد)
            end_ms = None
            # سقفِ درخواست‌ها تا از حلقه‌ی بی‌پایان جلوگیری شود
            for _ in range(60):
                need = min(1000, max(1, limit - len(collected)))
                url=f"{h}/api/v3/klines?symbol={sym}&interval={itv}&limit={need}"
                if end_ms is not None:
                    url += f"&endTime={end_ms}"
                raw=http_get(url)
                if not raw:
                    break
                for k in raw:
                    t=int(k[0])//1000
                    collected[t]={"t":t,"o":float(k[1]),"h":float(k[2]),
                                  "l":float(k[3]),"c":float(k[4]),"v":float(k[5])}
                if len(collected) >= limit:
                    break
                oldest_ms = int(raw[0][0])
                nxt = oldest_ms - step_s*1000
                if end_ms is not None and nxt >= end_ms:
                    break   # پیشرفتی نشد → پایانِ تاریخچه
                end_ms = nxt
                if len(raw) < need:
                    break   # صرافی دیتای قدیمی‌ترِ کمتری داد → ته تاریخچه
            bars = sorted(collected.values(), key=lambda b:b["t"])
            return bars[-limit:]
        except Exception as e:
            last_err=e; continue
    raise RuntimeError(f"binance fetch failed: {last_err}")

def fetch_yahoo(sym, tf, limit):
    itv=YF_TF.get(tf,"1h"); rng=YF_RANGE.get(tf,"3mo")
    url=(f"https://query1.finance.yahoo.com/v8/finance/chart/"
         f"{urllib.parse.quote(sym)}?interval={itv}&range={rng}")
    d=http_get(url)
    res=d["chart"]["result"][0]
    ts=res["timestamp"]; q=res["indicators"]["quote"][0]
    out=[]
    for i,t in enumerate(ts):
        o,h,l,c=q["open"][i],q["high"][i],q["low"][i],q["close"][i]
        if None in (o,h,l,c): continue
        out.append({"t":int(t),"o":float(o),"h":float(h),"l":float(l),
                    "c":float(c),"v":float(q.get("volume",[0]*len(ts))[i] or 0)})
    # resample to 4h if requested (yahoo gives 1h)
    if tf=="4h": out=resample(out,4)
    return out[-limit:]

def resample(bars,n):
    out=[]
    for i in range(0,len(bars)-len(bars)%n,n):
        grp=bars[i:i+n]
        if len(grp)<n: break
        out.append({"t":grp[0]["t"],"o":grp[0]["o"],"h":max(x["h"] for x in grp),
                    "l":min(x["l"] for x in grp),"c":grp[-1]["c"],
                    "v":sum(x["v"] for x in grp)})
    return out

def fetch(symbol, tf, limit):
    src,sym,disp=resolve(symbol)
    bars = fetch_binance(sym,tf,limit) if src=="binance" else fetch_yahoo(sym,tf,limit)
    # فلزات: Yahoo آتیِ COMEX (GC=F/SI=F) می‌دهد که نسبت به اسپات «بِیسیس» دارد.
    # کلِ سری را به‌اندازه‌ی (اسپات − آخرین‌کلوزِ آتی) شیفت می‌دهیم تا سطوح روی
    # چارتِ اسپاتِ XAU/XAG بنشیند. ساختار/سوینگ‌ها دست‌نخورده می‌ماند.
    spot = _spot_price(disp)
    if spot and bars:
        basis = spot - bars[-1]["c"]
        if abs(basis) > 1e-9:
            for b in bars:
                b["o"]+=basis; b["h"]+=basis; b["l"]+=basis; b["c"]+=basis
    return src,sym,disp,bars

# ---------- structure detection ----------
def swings(bars, n=2):
    """Fractal swing highs/lows. Returns list of (index, price, type)."""
    sw=[]
    for i in range(n, len(bars)-n):
        hi=bars[i]["h"]; lo=bars[i]["l"]
        if all(hi>=bars[i-j]["h"] for j in range(1,n+1)) and all(hi>=bars[i+j]["h"] for j in range(1,n+1)):
            sw.append((i,hi,"H"))
        if all(lo<=bars[i-j]["l"] for j in range(1,n+1)) and all(lo<=bars[i+j]["l"] for j in range(1,n+1)):
            sw.append((i,lo,"L"))
    sw.sort()
    # de-duplicate consecutive same-type by keeping the extreme
    clean=[]
    for s in sw:
        if clean and clean[-1][2]==s[2]:
            if s[2]=="H" and s[1]>clean[-1][1]: clean[-1]=s
            elif s[2]=="L" and s[1]<clean[-1][1]: clean[-1]=s
        else:
            clean.append(list(s))
    return [tuple(x) for x in clean]

def _break_displaced(bars, swing_idx, level, up, disp_mult=1.5):
    """آیا شکستِ سطحِ `level` (سقف/کفِ سوینگ در ایندکسِ swing_idx) با یک کندلِ
    دیسپلیسمنت انجام شده؟ (فیکس C3)

    از کندلِ بعدِ سوینگ جلو می‌رویم و نخستین کندلی را که **بسته‌شدنش** از سطح
    عبور کرده پیدا می‌کنیم؛ اگر بدنه‌ی همان کندل ≥ disp_mult×میانگینِ رِنجِ اخیر
    باشد، شکست معتبر (MSS واقعی) است. شکستِ بی‌جانِ کم‌بدنه معمولاً سوئیپِ
    لیکوئیدیتی است نه تغییرِ ساختار، و باید BOS/CHoCH جعلی تولید نکند.
    up=True یعنی شکستِ صعودی (close>level)، up=False یعنی نزولی (close<level).

    خروجی: (ok, break_idx) — ok آیا شکستِ دیسپلیسمنت‌دار بود، و break_idx ایندکسِ
    کندلِ شکست (برای ترتیب‌سنجیِ sweep→MSS در فیکس C4). اگر شکستی نبود (None,None).
    """
    n=len(bars)
    if swing_idx is None or swing_idx>=n-1:
        return (False, None)
    lo=max(0, swing_idx-30)
    avg=sum(b["h"]-b["l"] for b in bars[lo:swing_idx+1])/max(1, swing_idx+1-lo)
    if avg<=0:
        return (False, None)
    for k in range(swing_idx+1, n):
        c=bars[k]["c"]; o=bars[k]["o"]
        crossed = (c>level) if up else (c<level)
        if crossed:
            body=abs(c-o)
            dir_ok = (c>o) if up else (c<o)
            return (bool(dir_ok and body>=disp_mult*avg), k)
    return (False, None)


def structure(bars, sw):
    """Determine trend + last BOS/CHoCH from alternating swings.

    خروجی: trend, labeled[-6:], bos, choch, meta — meta شاملِ ایندکسِ کندلِ شکستِ
    BOS/CHoCH (bos_break_idx/choch_break_idx) برای ترتیب‌سنجیِ sweep→MSS (فیکس C4).
    """
    highs=[s for s in sw if s[2]=="H"]; lows=[s for s in sw if s[2]=="L"]
    events=[]; trend="range"
    # classify HH/HL/LH/LL sequence
    labeled=[]
    last_h=last_l=None
    for s in sw:
        if s[2]=="H":
            lab="HH" if (last_h and s[1]>last_h) else ("LH" if last_h else "H")
            labeled.append((s[0],s[1],"H",lab)); last_h=s[1]
        else:
            lab="LL" if (last_l and s[1]<last_l) else ("HL" if last_l else "L")
            labeled.append((s[0],s[1],"L",lab)); last_l=s[1]
    # trend from last few labels
    recent=[l[3] for l in labeled[-4:]]
    ups=sum(1 for r in recent if r in ("HH","HL"))
    dns=sum(1 for r in recent if r in ("LL","LH"))
    if ups>dns: trend="up"
    elif dns>ups: trend="down"
    # BOS / CHoCH detection on close basis
    bos=choch=None
    bos_break_idx=choch_break_idx=None
    price=bars[-1]["c"]
    # اصلاحِ باگ: BOS = شکستِ نزدیک‌ترین سوینگ، نه هر سوینگِ کهنه.
    # فیکس C3: شکست باید با کندلِ دیسپلیسمنت باشد؛ شکستِ بی‌جان = سوئیپ، نه BOS.
    if highs and price>highs[-1][1]:
        ok,bi=_break_displaced(bars, highs[-1][0], highs[-1][1], True)
        if ok:
            bos=("bullish_BOS",highs[-1][1],highs[-1][0]); bos_break_idx=bi
    if lows and price<lows[-1][1] and bos is None:
        ok,bi=_break_displaced(bars, lows[-1][0], lows[-1][1], False)
        if ok:
            bos=("bearish_BOS",lows[-1][1],lows[-1][0]); bos_break_idx=bi
    # CHoCH: تغییرِ کاراکترِ ساختار، شکستِ **نزدیک‌ترین** سوینگِ مخالف با دیسپلیسمنت.
    if len(labeled)>=3:
        if trend=="up" and lows and price<lows[-1][1]:
            ok,bi=_break_displaced(bars, lows[-1][0], lows[-1][1], False)
            if ok:
                choch=("bearish_CHoCH",lows[-1][1],lows[-1][0]); choch_break_idx=bi
        elif trend=="down" and highs and price>highs[-1][1]:
            ok,bi=_break_displaced(bars, highs[-1][0], highs[-1][1], True)
            if ok:
                choch=("bullish_CHoCH",highs[-1][1],highs[-1][0]); choch_break_idx=bi
    meta={"bos_break_idx":bos_break_idx,"choch_break_idx":choch_break_idx,"n":len(bars)}
    return trend, labeled[-6:], bos, choch, meta

def fvgs(bars, lookback=60):
    """Unfilled fair value gaps (3-candle imbalance).

    فیکس C14: فقط فیرولیوگپ‌هایی که از یک کندلِ **دیسپلیسمنت** زاده شده‌اند نگه
    داشته می‌شوند. گپِ ۳کندلی در چوپِ کم‌حجم گپِ باکیفیت نیست؛ گپِ واقعی وقتی
    شکل می‌گیرد که کندلِ میانی بدنه‌ای ≥ ۱.۵×میانگینِ رِنجِ اخیر داشته باشد.
    """
    out=[]; n=len(bars); price=bars[-1]["c"]
    start=max(2,n-lookback)
    def _avg_body(i):
        lo=max(0,i-20)
        seg=bars[lo:i+1]
        return sum(abs(x["c"]-x["o"]) for x in seg)/max(1,len(seg))
    for i in range(start,n):
        a,b,c=bars[i-2],bars[i-1],bars[i]
        avgb=_avg_body(i)
        # کندلِ میانی باید دیسپلیسمنت باشد: بدنه‌اش ≥ ۱.۳×میانگینِ بدنه‌های اخیر
        # (مقایسه‌ی بدنه با بدنه، نه بدنه با رِنجِ کاملِ شاملِ فتیله).
        b_body=abs(b["c"]-b["o"])
        disp_body = b_body >= 1.3*avgb if avgb>0 else False
        # bullish FVG: a.high < c.low، با کندلِ میانیِ دیسپلیسمنتِ صعودی
        if a["h"]<c["l"] and disp_body and b["c"]>b["o"]:
            lo,hi=a["h"],c["l"]
            filled = any(x["l"]<=lo for x in bars[i+1:])
            if not filled and price>lo:
                out.append({"type":"bullish","top":hi,"bottom":lo,"idx":i})
        if a["l"]>c["h"] and disp_body and b["c"]<b["o"]:
            lo,hi=c["h"],a["l"]
            filled = any(x["h"]>=hi for x in bars[i+1:])
            if not filled and price<hi:
                out.append({"type":"bearish","top":hi,"bottom":lo,"idx":i})
    return out[-6:]

def order_blocks(bars, lookback=80):
    """Last opposing candle before a displacement move.

    فیکس C5: اوبی‌های میتیگیت‌شده (که قیمت بعداً واردشان شده و بدنه را مصرف کرده)
    کنار گذاشته می‌شوند — تریدِ اوبیِ سوخته = استاپ‌اوت. یک اوبی «mitigated» است اگر
    بعد از تشکیل، قیمت به داخلِ بدنه‌ی آن بازگشته باشد:
      - بولیش OB (کفِ تقاضا): اگر بعداً کندلی low‌اش ≤ topِ اوبی رفته → لمس/میتیگیت.
      - بریش OB (سقفِ عرضه): اگر بعداً کندلی high‌اش ≥ bottomِ اوبی رفته → لمس/میتیگیت.
    فقط اوبی‌های تازه و لمس‌نشده به‌عنوان POIِ معتبر برمی‌گردند.
    """
    out=[]; n=len(bars); start=max(3,n-lookback)
    avg_rng=sum(b["h"]-b["l"] for b in bars[start:])/max(1,n-start)
    for i in range(start,n-1):
        b=bars[i]; nxt=bars[i+1]
        disp=abs(nxt["c"]-nxt["o"])
        # bullish OB: down candle followed by strong up displacement
        if b["c"]<b["o"] and nxt["c"]>nxt["o"] and disp>1.3*avg_rng and nxt["c"]>b["h"]:
            top,bot=b["h"],b["l"]
            # میتیگیت: بعد از کندلِ دیسپلیسمنت (i+2 به بعد) قیمت به داخلِ اوبی برگشته؟
            mitigated = any(x["l"]<=top for x in bars[i+2:])
            if not mitigated:
                out.append({"type":"bullish","top":top,"bottom":bot,"idx":i})
        if b["c"]>b["o"] and nxt["c"]<nxt["o"] and disp>1.3*avg_rng and nxt["c"]<b["l"]:
            top,bot=b["h"],b["l"]
            mitigated = any(x["h"]>=bot for x in bars[i+2:])
            if not mitigated:
                out.append({"type":"bearish","top":top,"bottom":bot,"idx":i})
    return out[-5:]

def _session_levels(bars, tf):
    """سطوحِ لیکوئیدیتیِ سشنی/روزانه (فیکس C6): PDH/PDL (سقف/کفِ روزِ قبل) و
    رِنجِ آسیایی (های/لوِ سشنِ آسیا ۱۹:۰۰–۰۰:۰۰ ET).

    اینها لیکوئیدیتیِ هسته‌ای ICT‌اند که تشخیصِ equal-high/low به‌تنهایی نمی‌بیند.
    از تایم‌استمپِ کندل‌ها (UTC → ET با آفستِ DST) روز و سشن استخراج می‌شود.
    فقط روی تایم‌فریم‌های درون‌روزی معنا دارد؛ برای 1d/1w کنار گذاشته می‌شود.
    خروجی: dict با pdh/pdl/asian_high/asian_low (هرکدام ممکن است None باشد).
    """
    if tf in ("1d", "1w") or len(bars) < 5:
        return {}
    # گروه‌بندیِ کندل‌ها بر اساسِ روزِ ET
    def _et(ts):
        dt = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
        off = 4 if _is_us_dst(dt) else 5
        return dt - datetime.timedelta(hours=off)
    days = {}       # date -> [bars]
    asian = {}      # date -> [bars in 19:00-24:00 ET of that date]
    for b in bars:
        et = _et(b["t"])
        dkey = et.date()
        days.setdefault(dkey, []).append(b)
        if 19 <= et.hour < 24:
            asian.setdefault(dkey, []).append(b)
    daykeys = sorted(days.keys())
    out = {}
    if len(daykeys) >= 2:
        # روزِ قبل = آخرین روزِ کاملِ پیش از روزِ جاری
        prev = days[daykeys[-2]]
        out["pdh"] = round(max(x["h"] for x in prev), 5)
        out["pdl"] = round(min(x["l"] for x in prev), 5)
    # رِنجِ آسیاییِ آخرین سشنِ آسیاییِ در دسترس
    akeys = sorted(asian.keys())
    if akeys:
        ab = asian[akeys[-1]]
        out["asian_high"] = round(max(x["h"] for x in ab), 5)
        out["asian_low"] = round(min(x["l"] for x in ab), 5)
    return out


def liquidity(bars, sw, tol=0.0007, tf=None):
    """Equal highs/lows (liquidity pools) + range extremes + session levels.

    فیکس C6: علاوه بر equal-high/low فرکتالی، سطوحِ سشنی هم افزوده می‌شود:
    PDH/PDL و رِنجِ آسیایی. اینها به فهرستِ اهدافِ بای‌ساید/سل‌ساید تزریق می‌شوند تا
    پلن‌ساز بتواند به لیکوئیدیتیِ واقعیِ ICT هدف‌گذاری کند، نه فقط سقف/کفِ مساویِ نادر.
    """
    highs=[s[1] for s in sw if s[2]=="H"][-8:]
    lows=[s[1] for s in sw if s[2]=="L"][-8:]
    eqh=[]; eql=[]
    for i in range(len(highs)):
        for j in range(i+1,len(highs)):
            if abs(highs[i]-highs[j])/highs[i]<tol: eqh.append(round((highs[i]+highs[j])/2,5))
    for i in range(len(lows)):
        for j in range(i+1,len(lows)):
            if abs(lows[i]-lows[j])/lows[i]<tol: eql.append(round((lows[i]+lows[j])/2,5))
    sess = _session_levels(bars, tf) if tf else {}
    price = bars[-1]["c"]
    # سطوحِ سشنیِ بالای قیمت → بای‌ساید (هدفِ خرید)؛ زیرِ قیمت → سل‌ساید (هدفِ فروش)
    buyside = set(eqh); sellside = set(eql)
    for key in ("pdh", "asian_high"):
        v = sess.get(key)
        if v is not None:
            (buyside if v > price else sellside).add(v)
    for key in ("pdl", "asian_low"):
        v = sess.get(key)
        if v is not None:
            (buyside if v > price else sellside).add(v)
    return {"buyside_eqh":sorted(buyside)[-4:],"sellside_eql":sorted(sellside)[:4],
            "range_high":max(b["h"] for b in bars),"range_low":min(b["l"] for b in bars),
            "session":sess}

def _impulse_leg(sw):
    """آخرین «پایِ ایمپالس» (حرکتِ جهت‌دارِ سازنده‌ی ساختار) از روی سوینگ‌ها.

    ICT فیب را روی همین پا می‌کشد: مبدأ (origin) → مقصد (BOS/terminus). ما آن را
    از دو سوینگِ آخرِ متناوب می‌گیریم چون sw از پیش پاک‌سازیِ نوع‌متناوب شده است:
      - آخرین جفت L→H  ⇒ پایِ صعودی: bottom=L، top=H، جهت=+1.
      - آخرین جفت H→L  ⇒ پایِ نزولی: top=H، bottom=L، جهت=-1.
    خروجی: (bottom, top, leg_dir, origin_idx, term_idx) یا None اگر کمتر از دو سوینگ.
    """
    if len(sw) < 2:
        return None
    a, b = sw[-2], sw[-1]     # a=مبدأ، b=مقصد (تازه‌ترین)
    if a[2] == b[2]:
        return None            # هم‌نوع نباید باشد (sw پاک‌سازی شده)، محافظه‌کاری
    if a[2] == "L" and b[2] == "H":
        return (a[1], b[1], 1, a[0], b[0])       # پایِ صعودی L→H
    if a[2] == "H" and b[2] == "L":
        return (b[1], a[1], -1, a[0], b[0])      # پایِ نزولی H→L
    return None


def premium_discount(bars, sw, span=8):
    """PD array انکورشده روی **پایِ ایمپالسِ واقعی** (نه رِنجِ دلخواه).

    اصلاحِ C1 + C7: پیش‌تر رِنج از اکسترمم‌های ۸ سوینگِ آخر ساخته و سپس برای شاملِ
    قیمتِ فعلی «پهن» می‌شد → اکولیبریوم جابه‌جا و پریمیوم/دیسکانت غلط برچسب می‌خورد،
    و OTE روی رِنجِ ساختگی می‌افتاد (ریشه‌ی باختِ ورودهای OTE). حالا فیب روی پایِ
    ایمپالسِ ساختاری (مبدأ→مقصدِ آخرین حرکتِ جهت‌دار) لنگر می‌شود و رِنج **پهن
    نمی‌شود** — اگر قیمت از پا بیرون زده باشد، خودِ همان بیرون‌زدگی سیگنالِ معناداری
    است (mitigation/continuation) و نباید با پهن‌کردنِ رِنج پنهان شود.

    خروجی، برای سازگاری با confluence.ote_zone و فیکس C7، زون‌های OTE را هم‌راستا
    با همان قراردادِ آن‌جا برمی‌گرداند (خرید=دیسکانت پایینِ رِنج، فروش=پریمیومِ بالا).
    """
    highs=[s for s in sw if s[2]=="H"]; lows=[s for s in sw if s[2]=="L"]
    if not highs or not lows: return None
    price=bars[-1]["c"]

    leg=_impulse_leg(sw)
    if leg is not None:
        bot, top, leg_dir, o_idx, t_idx = leg
    else:
        # پس‌افتِ محافظه‌کارانه: اکسترمم‌های span سوینگِ آخر (بدونِ پهن‌کردن)
        recent=sw[-span:] if len(sw)>=span else sw
        rh=[s[1] for s in recent if s[2]=="H"]; rl=[s[1] for s in recent if s[2]=="L"]
        if not rh or not rl:
            rh=[highs[-1][1]]; rl=[lows[-1][1]]
        top=max(rh); bot=min(rl); leg_dir=0

    if top<=bot:
        return None
    eq=(top+bot)/2
    rng=top-bot
    # زون بر اساسِ محلِ قیمت در پا؛ price_pct می‌تواند <0 یا >100 شود اگر قیمت از پا
    # بیرون زده باشد — این عمداً حفظ می‌شود تا «قیمت پا را نقض/ادامه داده» را نشان دهد.
    zone="premium" if price>eq else "discount"
    pct=(price-bot)/rng*100 if rng>0 else 50
    # OTE = ۰.۶۲–۰.۷۹ رتریسمنتِ پا (منطبق با confluence.ote_zone، فیکس C7):
    #   خرید → دیسکانتِ پایینِ رِنج: bot + (۰.۲۱..۰.۳۸)×rng
    #   فروش → پریمیومِ بالای رِنج: top − (۰.۳۸..۰.۲۱)×rng
    ote_long=(round(bot+rng*0.21,5), round(bot+rng*0.38,5))   # buy (discount) zone
    ote_short=(round(top-rng*0.38,5), round(top-rng*0.21,5))  # sell (premium) zone
    return {"range_top":round(top,5),"range_bottom":round(bot,5),
            "equilibrium":round(eq,5),"zone":zone,"price_pct":round(pct,1),
            "leg_dir":leg_dir,
            "ote_long_buy_zone":ote_long,"ote_short_sell_zone":ote_short}

def sweeps(bars, sw, lookback=12):
    """Liquidity sweeps / stop-runs on recent bars.

    Bearish sweep (buyside grab): a bar wicks ABOVE a prior swing high but
    closes back below it -> liquidity taken above, potential reversal down.
    Bullish sweep (sellside grab): a bar wicks BELOW a prior swing low but
    closes back above it -> liquidity taken below, potential reversal up.
    Returns the most recent sweeps within `lookback` bars.
    """
    out=[]; n=len(bars)
    prior_highs=[s for s in sw if s[2]=="H"]
    prior_lows=[s for s in sw if s[2]=="L"]
    start=max(0,n-lookback)
    for i in range(start,n):
        b=bars[i]
        # only consider swings that formed BEFORE this bar
        for si,sp,st in prior_highs:
            if si<i-1 and b["h"]>sp and b["c"]<sp:
                out.append({"type":"bearish_sweep","level":round(sp,5),
                            "bar_from_end":n-1-i,"idx":i,"note":"buyside liquidity grabbed"})
                break
        for si,sp,st in prior_lows:
            if si<i-1 and b["l"]<sp and b["c"]>sp:
                out.append({"type":"bullish_sweep","level":round(sp,5),
                            "bar_from_end":n-1-i,"idx":i,"note":"sellside liquidity grabbed"})
                break
    # keep only the last few, most recent first
    return out[-4:][::-1]

def displacement(bars, lookback=10):
    """Recent displacement (institutional energy move).

    Flags whether any of the last `lookback` bars closed with a body larger
    than 1.8x the average range and in a clear direction -- the move that
    typically creates FVGs and validates a real BOS/CHoCH vs. noise.
    """
    n=len(bars); start=max(1,n-max(lookback,30))
    avg=sum(b["h"]-b["l"] for b in bars[start:])/max(1,n-start)
    recent=bars[-lookback:]
    best=None
    for off,b in enumerate(recent):
        body=abs(b["c"]-b["o"])
        if body>1.8*avg:
            d="bullish" if b["c"]>b["o"] else "bearish"
            cand={"present":True,"direction":d,
                  "bar_from_end":len(recent)-1-off,
                  "body_x_avg":round(body/avg,2) if avg>0 else None}
            if best is None or cand["body_x_avg"]>=best["body_x_avg"]:
                best=cand
    return best or {"present":False}

def _is_us_dst(dt_utc):
    """آیا این لحظه (UTC) در بازه‌ی ساعتِ تابستانیِ آمریکا (EDT) است؟

    قاعده‌ی آمریکا: از یکشنبه‌ی دومِ مارس تا یکشنبه‌ی اولِ نوامبر. تعیینِ آفستِ
    درستِ نیویورک (EDT=-4 در تابستان، EST=-5 در زمستان) لازم است تا پنجره‌های
    کیل‌زون نیم‌سالِ سال یک ساعت جابه‌جا نباشند (فیکس C9).
    """
    y = dt_utc.year
    # یکشنبه‌ی دومِ مارس، ساعت ۰۷:۰۰ UTC (۰۲:۰۰ محلیِ EST) شروعِ EDT
    mar1 = datetime.datetime(y, 3, 1, tzinfo=datetime.timezone.utc)
    first_sun_mar = 1 + (6 - mar1.weekday()) % 7      # weekday(): Mon=0..Sun=6
    dst_start = datetime.datetime(y, 3, first_sun_mar + 7, 7, 0, tzinfo=datetime.timezone.utc)
    # یکشنبه‌ی اولِ نوامبر، ساعت ۰۶:۰۰ UTC (۰۲:۰۰ محلیِ EDT) پایانِ EDT
    nov1 = datetime.datetime(y, 11, 1, tzinfo=datetime.timezone.utc)
    first_sun_nov = 1 + (6 - nov1.weekday()) % 7
    dst_end = datetime.datetime(y, 11, first_sun_nov, 6, 0, tzinfo=datetime.timezone.utc)
    return dst_start <= dt_utc < dst_end


def killzone_at(ts=None):
    """کیل‌زونِ ICT بر اساسِ زمانِ نیویورک برای یک لحظه‌ی مشخص.

    فیکس C2: به‌جای «اکنونِ» ساعتِ دیوار، تایم‌استمپِ کندل را می‌گیرد تا بک‌تست
    بازتولیدپذیر باشد (هر سیگنالِ تاریخی با کیل‌زونِ زمانِ خودش سنجیده شود، نه
    زمانِ اجرای بک‌تست). ts=None ⇒ اکنون (رفتارِ زنده، سازگاریِ عقب‌رو).
    فیکس C9: آفستِ EST/EDT بر پایه‌ی DST محاسبه می‌شود، نه ثابتِ -۴.
    """
    if ts is None:
        dt_utc = datetime.datetime.now(datetime.timezone.utc)
    else:
        dt_utc = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
    offset = 4 if _is_us_dst(dt_utc) else 5
    et = dt_utc - datetime.timedelta(hours=offset)
    h = et.hour + et.minute/60
    if 2<=h<5:   return "London Open KZ (02:00-05:00 ET)"
    if 8.5<=h<11:return "New York AM KZ (08:30-11:00 ET)"
    if 10<=h<12: return "London Close KZ (10:00-12:00 ET)"
    if 13<=h<16: return "New York PM KZ (13:00-16:00 ET)"
    if 19<=h<24 or 0<=h<2: return "Asian Range (19:00-24:00 ET)"
    return f"Outside primary killzone (NY time ~{int(h):02d}:00)"


def killzone_now():
    """سازگاریِ عقب‌رو: کیل‌زونِ لحظه‌ی فعلی (= killzone_at(None))."""
    return killzone_at(None)

def analyze_bars(bars, tf, disp=None, src="backtest", sym=None):
    """تحلیلِ ساختار روی آرایه‌ی کندلِ ازپیش‌آماده (بدونِ fetch).
    هسته‌ی مشترکِ analyze و بک‌تست — دقیقاً همان منطقِ تصحیح‌شده روی هر برشِ تاریخی."""
    if len(bars)<30: raise RuntimeError("not enough bars")
    sw=swings(bars,2)
    trend,labels,bos,choch,meta=structure(bars,sw)
    # فیکس C2: کیل‌زون از تایم‌استمپِ آخرین کندلِ همین برش حساب می‌شود (بازتولیدپذیر
    # در بک‌تست)، نه ساعتِ دیوارِ لحظه‌ی اجرا.
    kz = killzone_at(bars[-1]["t"])
    swp = sweeps(bars, sw)
    # فیکس C4: توالیِ مقدسِ sweep → MSS. آیا سوئیپِ لیکوئیدیتی **قبل از** کندلِ
    # شکستِ ساختار (CHoCH ترجیحاً، وگرنه BOS) رخ داده؟ اگر MSS قبل از سوئیپ باشد،
    # توالی نقض شده و ورود نامعتبر است. اندیس‌ها روی همین برش‌اند.
    mss_idx = meta.get("choch_break_idx")
    if mss_idx is None:
        mss_idx = meta.get("bos_break_idx")
    seq_ok = None
    if mss_idx is not None and swp:
        # جهتِ MSS
        mss_dir = None
        if choch:
            mss_dir = 1 if "bullish" in choch[0] else -1
        elif bos:
            mss_dir = 1 if "bullish" in bos[0] else -1
        # سوئیپِ هم‌جهت که پیش از شکست رخ داده (bullish_sweep برای MSS صعودی و برعکس)
        want_sweep = "bullish_sweep" if mss_dir == 1 else "bearish_sweep"
        prior = [s for s in swp if s.get("type") == want_sweep
                 and s.get("idx") is not None and s["idx"] <= mss_idx]
        seq_ok = bool(prior)
    return {
        "symbol":disp,"resolved":sym or disp,"source":src,"tf":tf,
        "bars":len(bars),"last_price":bars[-1]["c"],
        "last_time_utc":datetime.datetime.fromtimestamp(bars[-1]["t"],datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "trend":trend,
        "recent_structure":[{"label":l[3],"price":round(l[1],5)} for l in labels],
        "BOS":bos,"CHoCH":choch,
        "mss_meta":meta,
        "sequence_ok":seq_ok,   # فیکس C4: sweep→MSS رعایت شده؟ (True/False/None=نامشخص)
        "premium_discount":premium_discount(bars,sw),
        "liquidity":liquidity(bars,sw,tf=tf),
        "liquidity_sweeps":swp,
        "displacement":displacement(bars),
        "FVG_unfilled":fvgs(bars),
        "order_blocks":order_blocks(bars),
        "killzone":kz,
    }

def analyze(symbol, tf, limit=300):
    src,sym,disp,bars=fetch(symbol,tf,limit)
    return analyze_bars(bars, tf, disp=disp, src=src, sym=sym)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--tf",default="1h")
    ap.add_argument("--limit",type=int,default=300)
    ap.add_argument("--json",action="store_true")
    a=ap.parse_args()
    r=analyze(a.symbol,a.tf,a.limit)
    print(json.dumps(r,indent=2,ensure_ascii=False))

if __name__=="__main__":
    main()
