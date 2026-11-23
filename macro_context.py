#!/usr/bin/env python3
"""
Macro Context Engine — economic calendar, trading sessions, news-risk gate.
Pure stdlib. Data: ForexFactory weekly JSON (faireconomy mirror).

Usage:
  python3 macro_context.py                 # full context (sessions + today's high-impact events)
  python3 macro_context.py --symbol XAUUSD # filter events by currencies that move this symbol
  python3 macro_context.py --json
"""
import sys, json, urllib.request, urllib.error, argparse, datetime, ssl, re, html, threading
import copy, math, tempfile
from zoneinfo import ZoneInfo

UTC = datetime.timezone.utc
ET = ZoneInfo("America/New_York")

UA={"User-Agent":"Mozilla/5.0"}
def _ctx():
    try:
        import certifi
        context=ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context=ssl.create_default_context()
    if sys.platform=="darwin" and not context.cert_store_stats().get("x509_ca"):
        import subprocess
        roots=subprocess.run(["security", "find-certificate", "-a", "-p",
            "/System/Library/Keychains/SystemRootCertificates.keychain"],
            capture_output=True, text=True, timeout=10, check=True)
        context.load_verify_locations(cadata=roots.stdout)
    if not context.cert_store_stats().get("x509_ca"):
        raise RuntimeError("ریشه‌های معتبرِ گواهیِ سیستم موجود نیست؛ اعتبارسنجیِ امن خاموش نمی‌شود")
    return context
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
_MEM={}                          # key -> [original fetched_at, isolated SourceRows]
_MEM_LOCK=threading.Lock()
_INFLIGHT: dict[str, "_Flight"]={}  # source key -> its exact running flight
_DOWN={}                         # source key -> retry deadline; never a data timestamp
DOWN_COOLDOWN=90
FETCH_TIMEOUT=12
CALENDAR_MAX_AGE=3*3600
ACTUALS_MAX_AGE=3600


class SourceRows(list):
    """List-compatible snapshot carrying source provenance, including on fallback.

    JSON consumers still receive ordinary arrays. Use calendar_quality/actuals_quality
    before treating a snapshot as confirmation; bool(rows) does not mean fresh.
    """
    def __init__(self, rows=(), metadata=None):
        super().__init__(copy.deepcopy(list(rows)))
        self.metadata=copy.deepcopy(metadata or {})


class _Flight(threading.Event):
    def __init__(self):
        super().__init__()
        self.result: SourceRows | None=None


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _age_limit(v, default):
    try:
        n=float(v)
        if isinstance(v, bool) or not math.isfinite(n): return default
        return max(0.0, n)
    except (TypeError, ValueError, OverflowError): return default


def _as_utc(now=None):
    """Decision time: epoch or datetime; explicit naive datetime means UTC."""
    if now is None:
        dt=now_et()
        if dt.tzinfo is None: dt=dt.replace(tzinfo=ET)  # legacy clock fixtures
        return dt.astimezone(UTC)
    if isinstance(now, datetime.datetime):
        return (now.replace(tzinfo=UTC) if now.tzinfo is None else now).astimezone(UTC)
    if _finite(now): return datetime.datetime.fromtimestamp(now, UTC)
    raise ValueError("زمانِ تصمیم باید تاریخ یا تایم‌استمپِ متناهی باشد")


def parse_event_time(value):
    """FF ISO timestamp -> UTC. Naive ET is accepted only when unambiguous.

    Date-only, nonexistent spring times and repeated autumn times without an
    explicit offset have no unique release instant and must not become GREEN.
    """
    try:
        if isinstance(value, datetime.datetime): dt=value
        elif isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", value):
            dt=datetime.datetime.fromisoformat(value)
        else: return None
        if dt.tzinfo is None:
            candidates=[]
            for fold in (0, 1):
                local=dt.replace(tzinfo=ET, fold=fold)
                utc=local.astimezone(UTC)
                if utc.astimezone(ET).replace(tzinfo=None)==dt:
                    candidates.append(utc)
            if not candidates or len(set(candidates))!=1: return None
            return candidates[0]
        return dt.astimezone(UTC)
    except (TypeError, ValueError, OverflowError): return None


def _validate_data(key, rows):
    if not isinstance(rows, list): raise ValueError("شکلِ پاسخِ منبع معتبر نیست")
    # Also reject NaN/Infinity buried in optional fields before publication/write.
    json.dumps(rows, allow_nan=False)
    for r in rows:
        if not isinstance(r, dict): raise ValueError("ردیفِ منبع معتبر نیست")
        if key=="cal":
            if (not isinstance(r.get("title"), str) or not r["title"].strip()
                    or not isinstance(r.get("country"), str) or not r["country"].strip()
                    or r.get("impact") not in ("High", "Medium", "Low", "Holiday", "Non-Economic")
                    or parse_event_time(r.get("date")) is None):
                raise ValueError("هویت یا زمانِ خبر معتبر نیست")
            fields=("forecast", "previous", "actual")
        else:
            minute=r.get("minute")
            try:
                if not isinstance(r.get("date"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["date"]):
                    raise ValueError
                datetime.date.fromisoformat(r["date"])
            except (KeyError, TypeError, ValueError): raise ValueError("تاریخِ نتیجه معتبر نیست")
            if (not isinstance(r.get("ccy"), str) or not r["ccy"].strip()
                    or not isinstance(minute, int) or isinstance(minute, bool) or not 0<=minute<1440
                    or not isinstance(r.get("event", ""), str)):
                raise ValueError("هویت یا ساعتِ نتیجه معتبر نیست")
            fields=("actual", "forecast")
        if any(r.get(f) is not None and not isinstance(r.get(f), str) for f in fields):
            raise ValueError("واحد یا متنِ عددِ منبع معتبر نیست")
    return rows


def _week_start(day):
    return day-datetime.timedelta(days=(day.weekday()+1)%7)


def _source_quality(rows, now=None, max_age=None, calendar=False):
    meta=copy.deepcopy(getattr(rows, "metadata", {}))
    q={"ok":False, "status":"UNKNOWN", "source":meta.get("source", "provided"),
       "fetched_at":meta.get("fetched_at"), "age_s":None, "fresh":False,
       "stale":False, "available":False, "coverage_ok":False,
       "coverage_start":None, "coverage_end":None, "reason":"منبع در دسترس نیست"}
    try:
        current=_as_utc(now)
        _validate_data("cal" if calendar else "te", rows)
        if not rows: return q
        q["available"]=True
        if calendar:
            dates=[parse_event_time(r["date"]) for r in rows]
            weeks={_week_start(dt.astimezone(ET).date()) for dt in dates if dt is not None}
            q["coverage_start"]=min(weeks).isoformat()
            q["coverage_end"]=(max(weeks)+datetime.timedelta(days=7)).isoformat()
            q["coverage_ok"]=_week_start(current.astimezone(ET).date()) in weeks
        else:
            days=[datetime.date.fromisoformat(r["date"]) for r in rows]
            q["coverage_start"]=min(days).isoformat()
            q["coverage_end"]=max(days).isoformat()
            q["coverage_ok"]=True  # matching still requires this event's date/time/title
        fetched=meta.get("fetched_at")
        if meta and not _finite(fetched):
            q["reason"]="زمانِ دریافتِ منبع معلوم نیست"; return q
        if fetched is not None:
            age=current.timestamp()-fetched
            q["age_s"]=round(age, 3)
            limit=_age_limit(max_age if max_age is not None else meta.get("max_age"),
                             CALENDAR_MAX_AGE if calendar else ACTUALS_MAX_AGE)
            if age<0:
                q["reason"]="منبع پس از زمانِ تصمیم دریافت شده؛ تأییدِ تاریخی نیست"; return q
            if age>=limit:
                q["stale"]=True; q["reason"]="دادهٔ منبع کهنه است"; return q
        if meta.get("source_status", "ok")!="ok":
            q["stale"]=bool(rows)
            q["reason"]=meta.get("error") or "منبعِ تازه در دسترس نیست"; return q
        if not q["coverage_ok"]:
            q["reason"]="تقویم، هفتهٔ زمانِ تصمیم را پوشش نمی‌دهد"; return q
        q.update(ok=True, status="OK", fresh=True,
                 reason="دادهٔ ارائه‌شده معتبر است" if not meta else "منبع تازه و پوششِ زمانی معتبر است")
    except (TypeError, ValueError, OverflowError, KeyError, OSError) as e:
        q["reason"]=str(e) or "دادهٔ منبع معتبر نیست"
    return q


def calendar_quality(cal, now=None):
    """Return {ok,status,source,fetched_at,age_s,coverage_ok,reason,...}.

    Plain nonempty lists remain compatible with supplied/offline fixtures;
    their event week must cover `now`. An empty/uncovered/stale/live-future
    snapshot is UNKNOWN, never proof of an absence of economic news.
    """
    return _source_quality(cal, now=now, calendar=True)


def actuals_quality(rows, now=None, max_age=None):
    return _source_quality(rows, now=now, max_age=max_age)


def _usable(key, data, max_age):
    return data is not None and _source_quality(data, max_age=max_age, calendar=key=="cal")["ok"]


def _mem_get(key, max_age):
    with _MEM_LOCK:
        entry=_MEM.get(key)
        data=copy.deepcopy(entry[1]) if entry else None
    return data if _usable(key, data, max_age) else None


def _mem_put(key, data, at=None):
    snap=copy.deepcopy(data)
    original=getattr(snap, "metadata", {}).get("fetched_at", at)
    if original is None and at is not None: original=at
    with _MEM_LOCK: _MEM[key]=[original, snap]
    return copy.deepcopy(snap)


def clear_memo():
    """Clear memo/cooldown, not ownership of a still-running fetch."""
    with _MEM_LOCK:
        _MEM.clear(); _DOWN.clear()


def _down(key):
    with _MEM_LOCK:
        until=_DOWN.get(key)
        return bool(until is not None and time.time()<until)


def _mark_down(key):
    with _MEM_LOCK: _DOWN[key]=time.time()+DOWN_COOLDOWN


def _flock(key, wait=30.0):
    with _MEM_LOCK:
        ev=_INFLIGHT.get(key)
        if ev is None:
            ev=_Flight()
            _INFLIGHT[key]=ev
            return True, ev
    ev.wait(wait)
    return False, ev  # timeout is NOT a grant of ownership


def _publish(key, ev, data):
    snap=copy.deepcopy(data)
    with _MEM_LOCK:
        _MEM[key]=[snap.metadata.get("fetched_at"), snap]
        ev.result=copy.deepcopy(snap)
        if snap.metadata.get("source_status")=="ok": _DOWN.pop(key, None)


def _funlock(key, ev):
    # Publish first, then release ownership and wake the exact flight's waiters.
    with _MEM_LOCK:
        if _INFLIGHT.get(key) is ev: _INFLIGHT.pop(key, None)
        ev.set()


def _reject_json_constant(value):
    raise ValueError("عددِ نامتناهی در کش: "+value)


def _disk(key, path, max_age=None):
    """Read legacy arrays/envelopes, keeping their original capture time."""
    try:
        with open(path, encoding="utf-8") as f:
            payload=json.load(f, parse_constant=_reject_json_constant)
            mtime=os.fstat(f.fileno()).st_mtime
        if key=="cal" and isinstance(payload, list):
            rows, at, meta=payload, mtime, {}
        elif isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            rows=payload["rows"]
            at=payload.get("at", mtime)
            meta=payload.get("metadata") or {}
            if not isinstance(meta, dict): return None
        else: return None
        if not _finite(at): return None
        _validate_data(key, rows)
        meta=dict(meta, source="forexfactory" if key=="cal" else "tradingeconomics",
                  fetched_at=at, max_age=CALENDAR_MAX_AGE if key=="cal" else ACTUALS_MAX_AGE)
        meta.setdefault("source_status", "ok")
        data=SourceRows(rows, meta)
        return data if max_age is None or _usable(key, data, max_age) else None
    except (OSError, TypeError, ValueError, OverflowError): return None


def _cached_source(key, path):
    with _MEM_LOCK:
        entry=_MEM.get(key)
        mem=copy.deepcopy(entry[1]) if entry else None
    disk=_disk(key, path)
    if mem is None: return disk
    if disk is None: return mem
    a=getattr(mem, "metadata", {}).get("fetched_at")
    b=disk.metadata.get("fetched_at")
    return mem if (_finite(a) and (not _finite(b) or a>=b)) else disk


def _atomic_write(path, payload):
    """Same-directory unique temp + fsync + replace; failed writes preserve old JSON."""
    path=os.fspath(path)
    fd, tmp=tempfile.mkstemp(prefix="."+os.path.basename(path)+"-", suffix=".tmp",
                             dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, allow_nan=False)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass


def _fallback(key, candidate, error, status="stale"):
    meta=copy.deepcopy(getattr(candidate, "metadata", {}))
    meta.setdefault("source", "forexfactory" if key=="cal" else "tradingeconomics")
    meta.setdefault("fetched_at", None)
    meta.update(source_status=status if candidate else "unavailable", error=str(error),
                max_age=CALENDAR_MAX_AGE if key=="cal" else ACTUALS_MAX_AGE)
    return SourceRows(candidate or [], meta)


def _return_rows(key, data, max_age) -> SourceRows:
    result=copy.deepcopy(data)
    result.metadata["max_age"]=max_age
    if key=="cal" and not result:
        raise RuntimeError("calendar fetch failed: "+str(result.metadata.get("error") or "منبع در دسترس نیست"))
    return result


def _get_rows(key, path, max_age, fetch) -> SourceRows:
    ready=_mem_get(key, max_age)
    if ready is not None: return _return_rows(key, ready, max_age)
    cached=_cached_source(key, path)
    if _usable(key, cached, max_age):
        return _return_rows(key, _mem_put(key, cached), max_age)
    leader, ev=_flock(key)
    if not leader:
        if ev.result is not None:
            # Even max_age=0 callers share this exact completed network attempt.
            return _return_rows(key, ev.result, max_age)
        result=_fallback(key, _cached_source(key, path), "واکشیِ منبع هنوز تمام نشده", "waiting")
        return _return_rows(key, result, max_age)  # no fetch, cooldown or ownership change
    result=None
    try:
        # A prior leader may have published between our cache read and acquisition.
        cached=_cached_source(key, path)
        if _usable(key, cached, max_age):
            result=cached
            _publish(key, ev, result)
        elif _down(key):
            result=_fallback(key, cached, getattr(cached, "metadata", {}).get("error") or "منبع در دورهٔ خنک‌شدن است")
            _publish(key, ev, result)
        else:
            try:
                rows=_validate_data(key, fetch())
                if not rows: raise ValueError("منبع، ردیفِ معتبرِ تقویم برنگرداند")
                result=SourceRows(rows, {"source":"forexfactory" if key=="cal" else "tradingeconomics",
                                        "fetched_at":time.time(), "source_status":"ok", "max_age":max_age})
                if key=="cal" and not calendar_quality(result)["coverage_ok"]:
                    raise ValueError("منبع، تقویمِ هفتهٔ کنونی را برنگرداند")
            except Exception as e:
                _mark_down(key)
                result=_fallback(key, cached, e)
                _publish(key, ev, result)
            else:
                # Memory/flight publication never depends on writable disk.
                _publish(key, ev, result)
                try:
                    _atomic_write(path, {"version":1, "at":result.metadata["fetched_at"],
                                         "rows":list(result), "metadata":result.metadata})
                except (OSError, TypeError, ValueError): pass
    finally:
        if result is None:
            result=_fallback(key, cached, "واکشیِ منبع کامل نشد")
            _mark_down(key); _publish(key, ev, result)
        _funlock(key, ev)
    return _return_rows(key, result, max_age)


def _fetch_calendar(timeout, attempts):
    last=None
    for url in FF_URLS:
        for attempt in range(max(1, int(attempts))):
            try:
                req=urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                    rows=json.loads(r.read().decode("utf-8"), parse_constant=_reject_json_constant)
                _validate_data("cal", rows)
                if not rows or not calendar_quality(rows)["coverage_ok"]:
                    raise ValueError("تقویمِ هفتهٔ کنونی در پاسخِ منبع نبود")
                return rows
            except urllib.error.HTTPError as e:
                last=e
                if e.code==429:
                    time.sleep(2*(attempt+1)); continue
                break
            except Exception as e:
                last=e; break
    raise RuntimeError(str(last or "منبعِ تقویم در دسترس نیست"))


def get_calendar(timeout=FETCH_TIMEOUT, attempts=2):
    """List-compatible FF snapshot; stale fallback retains capture time/UNKNOWN.

    Recovery is retried after DOWN_COOLDOWN, not after a freshly stamped 3h TTL.
    An unfinished follower returns stale/unknown (or raises without any rows),
    and can never start a second download while the leader still owns the source.
    """
    return _get_rows("cal", CACHE, CALENDAR_MAX_AGE, lambda: _fetch_calendar(timeout, attempts))

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
    """Strict 12-hour GMT time; malformed source times have no release instant."""
    if not isinstance(hhmm, str) or not re.fullmatch(r"\d{1,2}:\d{2}", hhmm): return None
    if ampm not in ("AM", "PM"): return None
    h, m=map(int, hhmm.split(":"))
    if not 1<=h<=12 or not 0<=m<60: return None
    return (h%12+(12 if ampm=="PM" else 0))*60+m


def _te_cell(seg, field):
    match=re.search(r'<(?P<tag>td|span|a|div)\b[^>]*(?:id|class)=[\'\"][^\'\"]*\b'
                    +field+r'\b[^\'\"]*[\'\"][^>]*>(?P<text>.*?)</(?P=tag)>',
                    seg, re.I|re.S)
    if not match: return ""
    return html.unescape(re.sub(r"<[^>]*>", "", match.group("text"))).strip()


def _parse_te_calendar(page):
    """TE event rows, validated UTC date/minute; never infer missing row identity.

    The published TE calendar's time basis is GMT. A changed/missing time,
    currency or date yields no matched Actual rather than a guessed release.
    Legacy actual markup: <span id='actual'>; double quotes/nested text also work.
    """
    rows=[]
    for match in re.finditer(r"<tr\b[^>]*>.*?</tr\s*>", page or "", re.I|re.S):
        seg=match.group()
        opening=seg[:seg.find(">")+1]
        if not re.search(r"\bdata-url\s*=", opening, re.I): continue
        d=re.search(r"\bclass=[\'\"][^\'\"]*\b(\d{4}-\d{2}-\d{2})\b[^\'\"]*[\'\"]", seg, re.I)
        t=re.fullmatch(r"(\d{1,2}:\d{2})\s*(AM|PM)", _te_cell(seg, r"calendar-date-\d+"), re.I)
        iso=_te_cell(seg, "calendar-iso").upper()
        ev=re.search(r"\bdata-event=[\'\"]([^\'\"]*)[\'\"]", opening, re.I)
        if not (d and t and re.fullmatch(r"[A-Z]{2}", iso)): continue
        try: datetime.date.fromisoformat(d.group(1))
        except ValueError: continue
        minute=_te_minutes(t.group(1), t.group(2).upper())
        if minute is None: continue
        rows.append({"ccy":ISO2CCY.get(iso, iso), "date":d.group(1), "minute":minute,
                     "event":html.unescape(ev.group(1)).strip() if ev else "",
                     "actual":_te_cell(seg, "actual"), "forecast":_te_cell(seg, "forecast")})
    return rows


def get_actuals(max_age=3600, timeout=FETCH_TIMEOUT):
    """List-compatible Actual rows, or [] with explicit unavailable provenance.

    All max_age policies share the one TE source flight. Empty/challenge HTML
    is a source failure; stale rows are retained without resetting capture time.
    """
    max_age=_age_limit(max_age, ACTUALS_MAX_AGE)
    def fetch():
        req=urllib.request.Request(TE_URL, headers=TE_UA)
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return _parse_te_calendar(r.read().decode("utf-8", "replace"))
    return _get_rows("te", TE_CACHE, max_age, fetch)


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

def now_et(now=None):
    return (datetime.datetime.now(UTC) if now is None else _as_utc(now)).astimezone(ET)


def active_sessions():
    et=now_et(); hm=et.hour*60+et.minute; out=[]
    for name,s,e,note in SESSIONS:
        sh,sm=map(int,s.split(":")); eh,em=map(int,e.split(":"))
        smin=sh*60+sm; emin=eh*60+em
        active=(smin<=hm<emin) if smin<emin else (hm>=smin or hm<emin)
        if active: out.append(f"{name} ({s}-{e} ET) — {note}")
    return out or ["No primary killzone active — lower-probability window, be selective"]


def today_events(cal, ccys=None):
    today=now_et().date(); out=[]
    for e in cal or []:
        if not isinstance(e, dict): continue
        dt=parse_event_time(e.get("date"))
        if dt is None: continue
        local=dt.astimezone(ET)
        if local.date()!=today: continue
        if ccys and "ALL" not in ccys and e.get("country") not in ccys: continue
        out.append((dt, {"time":local.strftime("%H:%M ET"), "ccy":e.get("country"),
                         "impact":e.get("impact"), "title":e.get("title"),
                         "forecast":e.get("forecast"), "previous":e.get("previous")}))
    return [row for _, row in sorted(out, key=lambda item:item[0])]


def upcoming_high_impact(cal, ccys=None, hours=48):
    current=_as_utc(); horizon=current+datetime.timedelta(hours=hours); out=[]
    for e in cal or []:
        if not isinstance(e, dict) or e.get("impact")!="High": continue
        dt=parse_event_time(e.get("date"))
        if dt is None or not current<=dt<=horizon: continue
        if ccys and "ALL" not in ccys and e.get("country") not in ccys: continue
        out.append((dt, {"when":dt.astimezone(ET).strftime("%a %H:%M ET"), "ccy":e.get("country"),
                         "title":e.get("title"), "forecast":e.get("forecast"), "previous":e.get("previous")}))
    return [row for _, row in sorted(out, key=lambda item:item[0])][:12]


def news_gate(cal, ccys, now=None):
    """(status, advice, nearby): 60m before through 30m after a release.

    `now` is optional epoch/aware datetime (explicit naive datetime means UTC).
    Ordinary two-argument fixtures remain supported. Missing/stale/uncovered
    calendars or ambiguous times are UNKNOWN, not a false no-news GREEN.
    All elapsed-time comparisons are in UTC, including both DST boundaries.
    """
    try: current=_as_utc(now)
    except (TypeError, ValueError, OverflowError, OSError):
        return ("UNKNOWN", "زمانِ تصمیم معتبر نیست؛ اجازهٔ خبری معلوم نیست.", [])
    quality=calendar_quality(cal, now=current)
    if not quality["ok"]:
        return ("UNKNOWN", "تأییدِ خبری نامعلوم است: "+quality["reason"], [])
    soon=[]
    for e in cal:
        if e.get("impact") not in ("High", "Medium"): continue
        if ccys and "ALL" not in ccys and e.get("country") not in ccys: continue
        dt=parse_event_time(e.get("date"))
        if dt is None:
            return ("UNKNOWN", "زمانِ خبر معتبر نیست؛ اجازهٔ خبری معلوم نیست.", [])
        mins=(dt-current).total_seconds()/60
        if -30<=mins<=60:
            soon.append((mins, e.get("impact"), e.get("country"), e.get("title")))
    soon.sort(key=lambda item:item[0])
    if any(s[1]=="High" for s in soon):
        return ("RED", "خبرِ پرتأثیر نزدیک است؛ ورودِ تازه ممنوع. پس از اعلام، برای پاک‌شدنِ فیک‌اوت ۱۵ تا ۳۰ دقیقه صبر کن.", soon)
    if soon:
        return ("AMBER", "خبرِ با تأثیرِ متوسط نزدیک است؛ نوسان و نویز محتمل است و ریسک را کاهش بده.", soon)
    return ("GREEN", "در تقویمِ معتبر، خبرِ مهمی در پنجرهٔ نزدیک نیست.", soon)

# static geopolitical risk-off checklist (can't be auto-scraped reliably; reminder)
RISK_OFF_NOTE=("Check headline risk BEFORE trading: war/geopolitical escalation, central-bank "
 "surprises, elections. Risk-off flows = USD/CHF/JPY & GOLD bid, risk assets (BTC, AUD, indices) sold. "
 "During live geopolitical shocks, technicals get overridden — trade smaller or stand aside.")

def build(symbol=None):
    try: cal=get_calendar()
    except Exception as e: cal=_fallback("cal", None, e)
    ccys=symbol_ccys(symbol) if symbol else None
    gate=news_gate(cal,ccys)
    return {
        "calendar_quality": calendar_quality(cal),
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
