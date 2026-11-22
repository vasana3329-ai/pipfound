#!/usr/bin/env python3
"""
Macro Context Engine — economic calendar, trading sessions, news-risk gate.
Pure stdlib. Data: ForexFactory weekly JSON (faireconomy mirror).

Usage:
  python3 macro_context.py                 # full context (sessions + today's high-impact events)
  python3 macro_context.py --symbol XAUUSD # filter events by currencies that move this symbol
  python3 macro_context.py --json
"""
import sys, json, urllib.request, argparse, datetime, ssl, re, html, threading

UA={"User-Agent":"Mozilla/5.0"}
def _ctx():
    try:
        import certifi; return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        try: return ssl.create_default_context()
        except Exception:
            c=ssl.create_default_context(); c.check_hostname=False; c.verify_mode=ssl.CERT_NONE; return c
CTX=_ctx()

FF_URLS=["https://nfs.faireconomy.media/ff_calendar_thisweek.json",
         "https://cdn-nfs.faireconomy.media/ff_calendar_thisweek.json"]

import os, time
CACHE=os.path.join(os.path.dirname(os.path.abspath(__file__)),".ff_cache.json")

# ── تک‌پروازیِ واکشی (single-flight) + حافظهٔ درون‌پروسه + خنک‌شدنِ شکست ──────
# ریشهٔ «صفحهٔ فاندمنتال دیر باز می‌شود»: بارِ اولِ صفحه **دو** اندپوینت را
# هم‌زمان می‌زند (`/api/fundamental` و `/api/fundamental-archive`) و هر دو مستقلِ
# هم همان تقویم + همان ستونِ Actual را می‌خواستند. تا وقتی کشِ روی دیسک کهنه/نبود،
# هر درخواست خودش شبکه می‌زد: تقویم تا ۳ تلاشِ ۲۰ ثانیه‌ای (با خوابِ ۴۲۹) و بعد
# TE تا ۲۵ ثانیه — یعنی چند ده ثانیه انتظار برایِ دو درخواستِ موازیِ یکسان، و
# کلیکِ دوباره هم از صفر همان مسیر (شکست کش نمی‌شد).
# حالا: (۱) نتیجهٔ موفق در حافظهٔ پروسه هم می‌نشیند؛ (۲) هم‌زمانیِ درخواست‌ها فقط
# **یک** واکشی می‌سازد و بقیه همان را می‌گیرند؛ (۳) شکستِ شبکه تا `DOWN_COOLDOWN`
# ثانیه در حافظه «خنک» می‌مانَد تا هر لودِ صفحه دوباره دقیقه‌ای معطل نشود؛
# (۴) تایم‌اوت‌ها کوتاه‌تر شده‌اند (۱۲ ثانیه) — منبعِ کند یعنی «همان کشِ کهنه/خالی
# با پاسخِ صریحِ نامعلوم»، نه انتظارِ بی‌پایانِ کاربر.
_MEM={}                          # key -> [at, data]
_MEM_LOCK=threading.Lock()
_INFLIGHT={}                     # key -> threading.Event  (رهبرِ واکشیِ جاری)
_DOWN={}                         # key -> until_ts (بعد از شکستِ شبکه)
DOWN_COOLDOWN=90                 # ثانیه
FETCH_TIMEOUT=12                 # ثانیه (قبلاً ۲۰/۲۵)

def _mem_get(key, max_age):
    with _MEM_LOCK:
        e=_MEM.get(key)
        if e and time.time()-e[0]<max_age: return e[1]
    return None

def _mem_put(key, data):
    with _MEM_LOCK: _MEM[key]=[time.time(), data]
    return data

def clear_memo():
    """پاک‌کردنِ حافظهٔ درون‌پروسه/وضعیتِ خنک — برای تست‌ها و اندازه‌گیریِ قطعی."""
    with _MEM_LOCK:
        _MEM.clear(); _DOWN.clear(); _INFLIGHT.clear()

def _down(key):
    """آیا همین حالا شکستِ تازه‌ای داشتیم؟ (تا پنجرهٔ خنک، شبکه تکرار نشود)"""
    with _MEM_LOCK:
        u=_DOWN.get(key)
        return bool(u and time.time()<u)

def _mark_down(key):
    with _MEM_LOCK: _DOWN[key]=time.time()+DOWN_COOLDOWN

def _flock(key, wait=30.0):
    """درِ تک‌پروازی: رهبر (True, ev) می‌گیرد و بقیه تا پایانِ کارش صبر می‌کنند.

    پیرو بعد از صبر باید کش/حافظه را **دوباره** بخواند (رهبر روی موفق یا ناموفق
    پیش از باز کردنِ در نوشته است).
    """
    with _MEM_LOCK:
        ev=_INFLIGHT.get(key)
        if ev is None:
            ev=threading.Event(); _INFLIGHT[key]=ev
            return True, ev
    ev.wait(wait)
    return False, ev

def _funlock(key, ev):
    ev.set()
    with _MEM_LOCK:
        if _INFLIGHT.get(key) is ev: _INFLIGHT.pop(key, None)

def _disk(key, path, max_age):
    """کشِ روی دیسک اگر تازه باشد (خطا/نبود ⇒ None)."""
    try:
        if os.path.exists(path) and time.time()-os.path.getmtime(path)<max_age:
            with open(path) as f: return json.load(f)
    except Exception: pass
    return None

def get_calendar(timeout=FETCH_TIMEOUT, attempts=2):
    """تقویمِ هفته (ForexFactory) — حافظه → کشِ تازه (<۳h) → شبکه → کشِ کهنه.

    هم‌زمانیِ چند درخواست = یک واکشی (single-flight)؛ شکستِ شبکه = خنکِ کوتاه و
    ادامه با کشِ کهنه یا خطایِ روشن (اپ نباید بشکند).
    """
    d=_mem_get("cal", 3*3600)
    if d is not None: return d
    d=_disk("cal", CACHE, 3*3600)
    if d is not None: return _mem_put("cal", d)
    leader, ev=_flock("cal")
    if not leader:
        d=_mem_get("cal", 3*3600)
        if d is not None: return d
        d=_disk("cal", CACHE, 3*3600)
        if d is not None: return _mem_put("cal", d)
    last=None
    try:
        if not _down("cal"):
            for u in FF_URLS:
                for attempt in range(max(1, attempts)):
                    try:
                        req=urllib.request.Request(u,headers=UA)
                        with urllib.request.urlopen(req,timeout=timeout,context=CTX) as r:
                            data=json.loads(r.read().decode())
                        try:
                            with open(CACHE,"w") as f: json.dump(data,f)
                        except Exception: pass
                        return _mem_put("cal", data)
                    except urllib.error.HTTPError as e:
                        last=e
                        if e.code==429: time.sleep(2*(attempt+1)); continue
                        break
                    except Exception as e:
                        last=e; break
            _mark_down("cal")
    finally:
        # در باید در **همهٔ** مسیرها (موفق/ناموفق/استثنا) باز شود، وگرنه
        # درخواست‌های هم‌زمانِ بعدی تا انتهای پنجرهٔ صبر معطل می‌مانند.
        if leader: _funlock("cal", ev)
    # آخرین راه: کشِ کهنه (کهنه هم بهتر از نبودِ تقویم است)
    try:
        with open(CACHE) as f: return _mem_put("cal", json.load(f))
    except Exception: pass
    raise RuntimeError(f"calendar fetch failed: {last or 'شبکه در دسترس نیست'}")

# ── ستونِ «اعلام‌شده» (Actual) — مکملِ تقویمِ FF ──────────────────────────
# فیدِ ForexFactory (json/xml) اصلاً فیلدِ actual ندارد (حتی برای رویدادهای
# گذشته — راستی‌آزمایی‌شده)؛ ولی صفحه‌ی تقویمِ Trading Economics ستونِ Actual
# را برای رویدادهای اعلام‌شده‌ی امروز دارد و زمان‌هایش GMT است (تطبیق‌شده با
# تقویمِ FF روی نمونه‌های واقعی). پس آرشیوِ «نتیجه‌ی قطعی» از همین‌جا می‌آید.
TE_URL="https://tradingeconomics.com/calendar"
TE_UA={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36","Accept":"text/html"}
TE_CACHE=os.path.join(os.path.dirname(os.path.abspath(__file__)),".te_actuals.json")
ISO2CCY={"US":"USD","EU":"EUR","GB":"GBP","JP":"JPY","AU":"AUD","NZ":"NZD","CA":"CAD","CH":"CHF","CN":"CNY"}

def _te_minutes(hhmm, ampm):
    """ساعتِ ۱۲ساعته‌ی صفحه → دقیقه‌ی روز (GMT)."""
    try: h, m = map(int, hhmm.split(":"))
    except Exception: return None
    if ampm == "PM" and h != 12: h += 12
    if ampm == "AM" and h == 12: h = 0
    return h * 60 + m

def _parse_te_calendar(page):
    """ردیف‌های تقویمِ TE → [{ccy,date(GMT),minute,event,actual,forecast}]."""
    rows=[]
    starts=[m.start() for m in re.finditer(r'<tr [^>]*data-url=', page or "")]
    for a,b in zip(starts, starts[1:]+[len(page or "")]):
        seg=page[a:b]
        d=re.search(r"class=' (\d{4}-\d{2}-\d{2})'", seg)
        t=re.search(r'calendar-date-\d+">\s*(\d{1,2}:\d{2})\s*(AM|PM)', seg)
        iso=re.search(r'calendar-iso">([A-Z]{2})<', seg)
        ev=re.search(r'data-event="([^"]*)"', seg)
        act=re.search(r"<span id='actual'>([^<]*)</span>", seg)
        fc=re.search(r"<a id='forecast'[^>]*>([^<]*)</a>", seg)
        if not (d and t and iso): continue
        minute=_te_minutes(t.group(1), t.group(2))
        if minute is None: continue
        rows.append({"ccy":ISO2CCY.get(iso.group(1), iso.group(1)),
                     "date":d.group(1), "minute":minute,
                     "event":html.unescape(ev.group(1)) if ev else "",
                     "actual":(act.group(1).strip() if act else ""),
                     "forecast":(fc.group(1).strip() if fc else "")})
    return rows


def get_actuals(max_age=3600, timeout=FETCH_TIMEOUT):
    """اعدادِ «اعلام‌شده» (Actual) از Trading Economics؛ [] اگر شبکه/منبع نبود.


    آرشیوِ اقتصادی برای «حکمِ قطعی» به این عدد نیاز دارد (FF نمی‌دهد). کشِ ۱ساعته
    تا به 429/بلاک نخوریم؛ خرابیِ شبکه همیشه به [] می‌رسد (اپ نباید بشکند).

    مثلِ تقویم: حافظهٔ درون‌پروسه + تک‌پروازی + تایم‌اوتِ کوتاه‌تر (۱۲ ثانیه)
    تا صفحهٔ فاندمنتال هیچ‌وقت پشتِ یک منبعِ کند گیر نکند.
    """
    key="te%d"%int(max_age)
    d=_mem_get(key, max_age)
    if d is not None: return d
    d=_disk(key, TE_CACHE, max_age)
    if d is not None: return _mem_put(key, d.get("rows") or [])
    leader, ev=_flock(key)
    if not leader:
        d=_mem_get(key, max_age)
        if d is not None: return d
        d=_disk(key, TE_CACHE, max_age)
        if d is not None: return _mem_put(key, d.get("rows") or [])
    rows=None
    if not _down(key):
        try:
            req=urllib.request.Request(TE_URL,headers=TE_UA)
            with urllib.request.urlopen(req,timeout=timeout,context=CTX) as r:
                page=r.read().decode("utf-8","replace")
            rows=_parse_te_calendar(page)
            try:
                with open(TE_CACHE,"w") as f: json.dump({"at":time.time(),"rows":rows},f)
            except Exception: pass
        except Exception:
            _mark_down(key)
    if leader:
        _funlock(key, ev)
    if rows is not None:
        return _mem_put(key, rows)
    try:
        with open(TE_CACHE) as f: return _mem_put(key, json.load(f).get("rows") or [])
    except Exception: return _mem_put(key, [])


def warm():
    """گرم‌کردنِ کش‌ها در پس‌زمینه (هنگامِ بوتِ اپ) — تا اولین کلیکِ کاربر هزینهٔ شبکه را ندهد.

    خروجی: dictِ خلاصه؛ هیچ استثنایی بیرون نمی‌دهد (این فقط یک بهینه‌سازی است)."""
    out={}
    for name, fn in (("calendar", get_calendar), ("actuals", get_actuals)):
        t0=time.time()
        try:
            v=fn()
            out[name]={"ok":True,"n":len(v or []),"s":round(time.time()-t0,2)}
        except Exception as e:
            out[name]={"ok":False,"err":str(e)[:120],"s":round(time.time()-t0,2)}
    return out

# which currencies drive a symbol
def symbol_ccys(sym):
    s=sym.upper().replace("/","").replace("-","")
    if s in ("XAUUSD","GOLD","XAU","XAGUSD","SILVER"): return {"USD","ALL"}  # metals sensitive to USD + risk
    if s.endswith(("USDT","USDC","BUSD")) or s in ("BTCUSDT","ETHUSDT"): return {"USD","ALL"}  # crypto: USD macro + risk
    if len(s)==6 and s.isalpha(): return {s[:3],s[3:]}
    return {"USD","ALL"}

# ICT/forex sessions in ET (New York)
SESSIONS=[
 ("Asian session (Tokyo)","19:00","04:00","low volatility, range-building, sets liquidity for London"),
 ("London open KZ","02:00","05:00","first daily expansion, judas swing then reversal"),
 ("London session","03:00","12:00","highest FX volatility overall"),
 ("New York AM KZ","08:30","11:00","news-driven, best US-session move"),
 ("London close","10:00","12:00","London profit-taking reversals"),
 ("New York PM KZ","13:30","16:00","afternoon continuation / reversal"),
]

# Which instruments have the STRONGEST movement in each session (volatility focus list).
# ★ = prime focus in this killzone.
SESSION_FOCUS={
 "Asian session (Tokyo)": [
   "★ USD/JPY, AUD/JPY, AUD/USD, NZD/USD (Asia-Pacific pairs most active)",
   "  XAU/USD quieter — accumulates the range London will raid"],
 "London open KZ": [
   "★ GBP/USD, EUR/USD, EUR/GBP, GBP/JPY (London's home pairs — biggest expansion)",
   "★ XAU/USD (gold makes its cleanest daily move in London)",
   "  Watch London judas swing: fake move first, then real direction"],
 "London session": [
   "★ GBP/USD, EUR/USD, GBP/JPY, EUR/JPY, XAU/USD (peak liquidity)",
   "  USD/CHF, EUR/CHF active on risk flows"],
 "New York AM KZ": [
   "★ EUR/USD, GBP/USD, XAU/USD, USD/CAD (US data + oil-linked CAD)",
   "★ BTC/USD, ETH/USD (US equity-correlated, react to US news)",
   "  London-NY overlap = the single most volatile window of the day"],
 "London close": [
   "★ EUR/USD, GBP/USD reversals as London books profit",
   "  XAU/USD often pulls back here"],
 "New York PM KZ": [
   "★ USD/CAD, XAU/USD, BTC/USD (afternoon continuation / crypto stays live 24/7)",
   "  Lower FX volatility after London closes — crypto takes the lead"],
}

# Correlation clusters — instruments that behave similarly (move together) or inversely.
# Use to CONFIRM a bias (aligned cluster) or spot divergence (SMT).
CORRELATION_CLUSTERS={
 "USD-strength barometer (move TOGETHER, inverse to USD)": [
   "EUR/USD, GBP/USD, AUD/USD, NZD/USD, XAU/USD — all RISE when USD falls.",
   "If 3 of these agree but one lags → SMT divergence, the laggard often catches up."],
 "USD-numerator (INVERSE to the group above)": [
   "USD/CAD, USD/CHF, USD/JPY — RISE when USD strengthens.",
   "USD/CAD ↔ XAU/USD and USD/CAD ↔ oil are strong inverse pairs."],
 "Risk-on / equity-correlated (move together)": [
   "BTC/USD, ETH/USD, AUD/USD, NZD/USD, US indices — bid in risk-ON.",
   "Sold together in risk-OFF (war/shock) → rotate into USD, CHF, JPY, GOLD."],
 "Safe-haven cluster (bid in risk-OFF)": [
   "XAU/USD, USD/CHF, USD/JPY (JPY nuance: can weaken if BOJ dovish).",
   "Gold + CHF rallying while stocks/BTC fall = confirmed risk-off regime."],
 "JPY-cross volatility (largest ranges)": [
   "GBP/JPY, EUR/JPY, AUD/JPY — widest daily ranges, use wider stops."],
}

def session_focus_now():
    act=active_sessions(); out=[]
    for line in act:
        name=line.split(" (")[0]
        if name in SESSION_FOCUS:
            out.append({"session":name,"strong_movers":SESSION_FOCUS[name]})
    return out

def now_et():
    return datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=4)

def active_sessions():
    et=now_et(); hm=et.hour*60+et.minute; out=[]
    for name,s,e,note in SESSIONS:
        sh,sm=map(int,s.split(":")); eh,em=map(int,e.split(":"))
        smin=sh*60+sm; emin=eh*60+em
        active=(smin<=hm<emin) if smin<emin else (hm>=smin or hm<emin)
        if active: out.append(f"{name} ({s}-{e} ET) — {note}")
    return out or ["No primary killzone active — lower-probability window, be selective"]

def today_events(cal, ccys=None):
    et=now_et(); today=et.date(); out=[]
    for e in cal:
        try:
            dt=datetime.datetime.fromisoformat(e["date"])  # has -04:00 offset
        except Exception:
            continue
        if dt.date()!=today: continue
        if ccys and "ALL" not in ccys and e.get("country") not in ccys: continue
        out.append({"time":dt.strftime("%H:%M ET"),"ccy":e.get("country"),
                    "impact":e.get("impact"),"title":e.get("title"),
                    "forecast":e.get("forecast"),"previous":e.get("previous")})
    return out

def upcoming_high_impact(cal, ccys=None, hours=48):
    et=now_et(); horizon=et+datetime.timedelta(hours=hours); out=[]
    for e in cal:
        if e.get("impact")!="High": continue
        try: dt=datetime.datetime.fromisoformat(e["date"])
        except Exception: continue
        dt_et=dt.astimezone(datetime.timezone(datetime.timedelta(hours=-4)))
        naive=dt_et.replace(tzinfo=None)
        if not (et.replace(tzinfo=None)<=naive<=horizon.replace(tzinfo=None)): continue
        if ccys and "ALL" not in ccys and e.get("country") not in ccys: continue
        out.append({"when":dt_et.strftime("%a %H:%M ET"),"ccy":e.get("country"),
                    "title":e.get("title"),"forecast":e.get("forecast"),"previous":e.get("previous")})
    return out[:12]

def news_gate(cal, ccys):
    """Red/amber/green: is there a high-impact release within +/- 60 min?"""
    et=now_et().replace(tzinfo=None); soon=[]
    for e in cal:
        if e.get("impact") not in ("High","Medium"): continue
        try: dt=datetime.datetime.fromisoformat(e["date"])
        except Exception: continue
        dt_et=dt.astimezone(datetime.timezone(datetime.timedelta(hours=-4))).replace(tzinfo=None)
        mins=(dt_et-et).total_seconds()/60
        if ccys and "ALL" not in ccys and e.get("country") not in ccys: continue
        if -30<=mins<=60:
            soon.append((mins,e.get("impact"),e.get("country"),e.get("title")))
    if any(s[1]=="High" for s in soon):
        return ("RED","High-impact release within the hour — DO NOT open new positions; wait for the release + 15-30m for the fakeout to clear.",soon)
    if soon:
        return ("AMBER","Medium-impact news nearby — reduce size / widen stops / expect noise.",soon)
    return ("GREEN","No major release within the hour — normal execution window.",soon)

# static geopolitical risk-off checklist (can't be auto-scraped reliably; reminder)
RISK_OFF_NOTE=("Check headline risk BEFORE trading: war/geopolitical escalation, central-bank "
 "surprises, elections. Risk-off flows = USD/CHF/JPY & GOLD bid, risk assets (BTC, AUD, indices) sold. "
 "During live geopolitical shocks, technicals get overridden — trade smaller or stand aside.")

def build(symbol=None):
    cal=get_calendar()
    ccys=symbol_ccys(symbol) if symbol else None
    gate=news_gate(cal,ccys)
    return {
        "now_et": now_et().strftime("%Y-%m-%d %H:%M ET (%A)"),
        "active_sessions": active_sessions(),
        "session_strong_movers": session_focus_now(),
        "correlation_clusters": CORRELATION_CLUSTERS,
        "news_gate": {"status":gate[0],"advice":gate[1]},
        "today_events_filtered": today_events(cal,ccys),
        "upcoming_high_impact_48h": upcoming_high_impact(cal,ccys),
        "risk_off_reminder": RISK_OFF_NOTE,
        "symbol": symbol, "driving_currencies": sorted(ccys) if ccys else "all",
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--symbol",default=None)
    ap.add_argument("--json",action="store_true")
    a=ap.parse_args()
    print(json.dumps(build(a.symbol),indent=2,ensure_ascii=False))

if __name__=="__main__":
    main()
