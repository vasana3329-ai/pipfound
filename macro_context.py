#!/usr/bin/env python3
"""
Macro Context Engine — economic calendar, trading sessions, news-risk gate.
Pure stdlib. Data: ForexFactory weekly JSON (faireconomy mirror).

Usage:
  python3 macro_context.py                 # full context (sessions + today's high-impact events)
  python3 macro_context.py --symbol XAUUSD # filter events by currencies that move this symbol
  python3 macro_context.py --json
"""
import sys, json, urllib.request, argparse, datetime, ssl

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

def get_calendar():
    # serve fresh cache (< 3h old) to avoid 429 rate-limits
    try:
        if os.path.exists(CACHE) and time.time()-os.path.getmtime(CACHE)<3*3600:
            with open(CACHE) as f: return json.load(f)
    except Exception: pass
    last=None
    for u in FF_URLS:
        for attempt in range(3):
            try:
                req=urllib.request.Request(u,headers=UA)
                with urllib.request.urlopen(req,timeout=20,context=CTX) as r:
                    data=json.loads(r.read().decode())
                try:
                    with open(CACHE,"w") as f: json.dump(data,f)
                except Exception: pass
                return data
            except urllib.error.HTTPError as e:
                last=e
                if e.code==429: time.sleep(2*(attempt+1)); continue
                break
            except Exception as e:
                last=e; break
    # last resort: stale cache
    try:
        with open(CACHE) as f: return json.load(f)
    except Exception: pass
    raise RuntimeError(f"calendar fetch failed: {last}")

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
