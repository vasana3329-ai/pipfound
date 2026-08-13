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

def structure(bars, sw):
    """Determine trend + last BOS/CHoCH from alternating swings."""
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
    price=bars[-1]["c"]
    # اصلاحِ باگ: BOS = شکستِ نزدیک‌ترین سوینگ، نه هر سوینگِ کهنه.
    # قبلاً حلقه به عقب می‌رفت و اولین سقفِ قدیمی‌ای که قیمت از آن بالاتر بود را
    # bullish_BOS اعلام می‌کرد → در هر بازاری قیمت بالای یک سقفِ قدیمی هست، پس
    # همیشه بایاسِ صعودیِ ساختگی می‌ساخت و هیچ سیگنالِ نزولی تولید نمی‌شد.
    if highs and price>highs[-1][1]:
        bos=("bullish_BOS",highs[-1][1],highs[-1][0])
    if lows and price<lows[-1][1]:
        b2=("bearish_BOS",lows[-1][1],lows[-1][0])
        if not bos: bos=b2
    # CHoCH: trend flip signal (break against recent trend)
    if len(labeled)>=3:
        if trend=="up":
            for s in reversed(lows):
                if price<s[1]: choch=("bearish_CHoCH",s[1],s[0]); break
        elif trend=="down":
            for s in reversed(highs):
                if price>s[1]: choch=("bullish_CHoCH",s[1],s[0]); break
    return trend, labeled[-6:], bos, choch

def fvgs(bars, lookback=60):
    """Unfilled fair value gaps (3-candle imbalance)."""
    out=[]; n=len(bars); price=bars[-1]["c"]
    start=max(2,n-lookback)
    for i in range(start,n):
        a,b,c=bars[i-2],bars[i-1],bars[i]
        # bullish FVG: a.high < c.low
        if a["h"]<c["l"]:
            lo,hi=a["h"],c["l"]
            filled = any(x["l"]<=lo for x in bars[i+1:])
            if not filled and price>lo:
                out.append({"type":"bullish","top":hi,"bottom":lo,"idx":i})
        if a["l"]>c["h"]:
            lo,hi=c["h"],a["l"]
            filled = any(x["h"]>=hi for x in bars[i+1:])
            if not filled and price<hi:
                out.append({"type":"bearish","top":hi,"bottom":lo,"idx":i})
    return out[-6:]

def order_blocks(bars, lookback=80):
    """Last opposing candle before a displacement move."""
    out=[]; n=len(bars); start=max(3,n-lookback)
    avg_rng=sum(b["h"]-b["l"] for b in bars[start:])/max(1,n-start)
    for i in range(start,n-1):
        b=bars[i]; nxt=bars[i+1]
        disp=abs(nxt["c"]-nxt["o"])
        # bullish OB: down candle followed by strong up displacement
        if b["c"]<b["o"] and nxt["c"]>nxt["o"] and disp>1.3*avg_rng and nxt["c"]>b["h"]:
            out.append({"type":"bullish","top":b["h"],"bottom":b["l"],"idx":i})
        if b["c"]>b["o"] and nxt["c"]<nxt["o"] and disp>1.3*avg_rng and nxt["c"]<b["l"]:
            out.append({"type":"bearish","top":b["h"],"bottom":b["l"],"idx":i})
    return out[-5:]

def liquidity(bars, sw, tol=0.0007):
    """Equal highs/lows (liquidity pools) + range extremes."""
    highs=[s[1] for s in sw if s[2]=="H"][-8:]
    lows=[s[1] for s in sw if s[2]=="L"][-8:]
    eqh=[]; eql=[]
    for i in range(len(highs)):
        for j in range(i+1,len(highs)):
            if abs(highs[i]-highs[j])/highs[i]<tol: eqh.append(round((highs[i]+highs[j])/2,5))
    for i in range(len(lows)):
        for j in range(i+1,len(lows)):
            if abs(lows[i]-lows[j])/lows[i]<tol: eql.append(round((lows[i]+lows[j])/2,5))
    return {"buyside_eqh":sorted(set(eqh))[-3:],"sellside_eql":sorted(set(eql))[:3],
            "range_high":max(b["h"] for b in bars),"range_low":min(b["l"] for b in bars)}

def premium_discount(bars, sw, span=8):
    """PD array on the current dealing range.

    Fix: instead of the last two swings (which can form a tiny, meaningless
    range), use the extremes (highest swing high, lowest swing low) among the
    last `span` swings that price is currently trading within. This is the
    'dealing range' ICT/SMC actually price against. Falls back gracefully.
    """
    highs=[s for s in sw if s[2]=="H"]; lows=[s for s in sw if s[2]=="L"]
    if not highs or not lows: return None
    recent=sw[-span:] if len(sw)>=span else sw
    rh=[s[1] for s in recent if s[2]=="H"]; rl=[s[1] for s in recent if s[2]=="L"]
    if not rh or not rl:
        rh=[highs[-1][1]]; rl=[lows[-1][1]]
    top=max(rh); bot=min(rl)
    price=bars[-1]["c"]
    # if price has run outside the swing range, widen to include it so pct stays sane
    top=max(top, price); bot=min(bot, price)
    eq=(top+bot)/2
    zone="premium" if price>eq else "discount"
    rng=top-bot
    pct=(price-bot)/rng*100 if rng>0 else 50
    # OTE (optimal trade entry) zone: 0.62-0.79 retrace of the range.
    # For a long the discount OTE sits low; for a short the premium OTE sits high.
    ote_long=(round(bot+rng*0.62,5), round(bot+rng*0.79,5))   # buy zone
    ote_short=(round(top-rng*0.79,5), round(top-rng*0.62,5))  # sell zone
    return {"range_top":round(top,5),"range_bottom":round(bot,5),
            "equilibrium":round(eq,5),"zone":zone,"price_pct":round(pct,1),
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
                            "bar_from_end":n-1-i,"note":"buyside liquidity grabbed"})
                break
        for si,sp,st in prior_lows:
            if si<i-1 and b["l"]<sp and b["c"]>sp:
                out.append({"type":"bullish_sweep","level":round(sp,5),
                            "bar_from_end":n-1-i,"note":"sellside liquidity grabbed"})
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

def killzone_now():
    """Current ICT killzone based on New York time."""
    et=datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=4)  # approx EDT
    h=et.hour+et.minute/60
    if 2<=h<5:   return "London Open KZ (02:00-05:00 ET)"
    if 8.5<=h<11:return "New York AM KZ (08:30-11:00 ET)"
    if 10<=h<12: return "London Close KZ (10:00-12:00 ET)"
    if 13<=h<16: return "New York PM KZ (13:00-16:00 ET)"
    if 19<=h<24 or 0<=h<2: return "Asian Range (19:00-24:00 ET)"
    return f"Outside primary killzone (NY time ~{int(h):02d}:00)"

def analyze_bars(bars, tf, disp=None, src="backtest", sym=None):
    """تحلیلِ ساختار روی آرایه‌ی کندلِ ازپیش‌آماده (بدونِ fetch).
    هسته‌ی مشترکِ analyze و بک‌تست — دقیقاً همان منطقِ تصحیح‌شده روی هر برشِ تاریخی."""
    if len(bars)<30: raise RuntimeError("not enough bars")
    sw=swings(bars,2)
    trend,labels,bos,choch=structure(bars,sw)
    return {
        "symbol":disp,"resolved":sym or disp,"source":src,"tf":tf,
        "bars":len(bars),"last_price":bars[-1]["c"],
        "last_time_utc":datetime.datetime.fromtimestamp(bars[-1]["t"],datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "trend":trend,
        "recent_structure":[{"label":l[3],"price":round(l[1],5)} for l in labels],
        "BOS":bos,"CHoCH":choch,
        "premium_discount":premium_discount(bars,sw),
        "liquidity":liquidity(bars,sw),
        "liquidity_sweeps":sweeps(bars,sw),
        "displacement":displacement(bars),
        "FVG_unfilled":fvgs(bars),
        "order_blocks":order_blocks(bars),
        "killzone":killzone_now(),
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
