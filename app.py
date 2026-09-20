#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اپلیکیشنِ تحلیلِ SMC/ICT — محیطِ ساده‌ی وب (لوکال، فقط stdlib، بدونِ API key).

اجرا:
    python3 app.py                # روی http://127.0.0.1:8787
    python3 app.py --port 9000

فقط نامِ نماد را بنویس (XAUUSD, EURUSD, BTCUSDT, XAGUSD, ...) و سبک را انتخاب کن؛
کارتِ کاملِ معامله را با امتیاز، تایم‌فریمِ ورود، پلنِ عددی و درجه می‌دهد.

هستهٔ تحلیل همان confluence.py + smc_engine.py + macro_context.py است.
"""
import sys, os, json, argparse, traceback, threading, time, datetime, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HOME = os.path.expanduser("~")
ALARMS_FILE = os.path.join(HOME, "pipfound", "alarms.json")
# وضعیتِ داده‌ی آخرین تحلیل‌ها — روی دیسک نگه داشته می‌شود چون خودِ اپ با هر تغییرِ
# کد ری‌استارتِ درجا می‌کند و اگر در حافظه بماند، چیپِ «سنِ داده» بعد از هر ادغام خالی می‌شود.
DATA_SEEN_FILE = os.path.join(HOME, "pipfound", "data_seen.json")
SHOTS_DIR = os.path.join(HOME, "pipfound", "screenshots")
_ALLOWED_IMG = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp", "gif": "image/gif"}
_MAX_UPLOAD = 12 * 1024 * 1024  # 12MB

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import confluence as C
import smc_engine as E
try:
    import backtest as BT
except Exception:
    BT = None
try:
    import macro_context as M
except Exception:
    M = None
try:
    import fundamental as FUND
except Exception:
    FUND = None
try:
    import risk as RK          # مدلِ ریسک: سایزِ پوزیشن، سقفِ روزانه، هم‌بستگی
except Exception:
    RK = None

# ماژولِ ژورنال از پوشه‌ی همسایه‌ی trade-journal
_JRN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "trade-journal", "scripts")
sys.path.insert(0, _JRN_DIR)
try:
    import journal as J
except Exception:
    J = None

# ── مسیرِ دفترِ معاملات (ژورنال): قابلِ تنظیم و بی‌نیاز از پوشه‌های محافظت‌شده ──
# ترتیبِ انتخاب: PIPFOUND_JOURNAL_CSV → PIPFOUND_JOURNAL_DIR/journal.csv → ~/pipfound/journal.csv
# چرا: جاب‌های launchd (مثلِ پیش‌نمایش) اجازه‌ی نوشتن در ~/Desktop و ~/Documents را
# ندارند (محدودیتِ TCC مک). مسیرِ پیش‌فرض بیرونِ آن‌هاست و دفترهای قدیمی هم یک‌بار،
# فقط با افزودنِ ردیف‌های غایب (بدونِ تغییر یا پاک‌کردنِ فایلِ قدیمی)، منتقل می‌شوند.
def _journal_path():
    f = os.environ.get("PIPFOUND_JOURNAL_CSV")
    if f:
        return os.path.expanduser(f)
    d = os.environ.get("PIPFOUND_JOURNAL_DIR")
    if d:
        return os.path.join(os.path.expanduser(d), "journal.csv")
    return os.path.join(HOME, "pipfound", "journal.csv")


_JR_FILE = _journal_path()
_JR_LEGACY = [os.path.join(HOME, "Desktop", "trading-journal", "journal.csv")]


# ستون‌های دفتر — همان‌های `trade-journal/scripts/journal.py` (در نوشتارگرِ داخلی به کار می‌روند)
_JR_FIELDS = ["id", "datetime", "symbol", "direction", "session", "tf", "htf_bias",
              "entry", "sl", "tp", "rr", "risk_pct", "setup", "poi", "reason",
              "status", "result", "exit", "realized_r", "mistake", "lesson", "notes"]


class _JournalFallback:
    """نوشتارگرِ داخلیِ ژورنال — فقط وقتی ماژولِ sibling پیدا نشود.

    قبلاً در آن حالت، ثبت در ژورنال بی‌صدا از کار می‌افتاد (پوشهٔ مهارت جابه‌جا شده بود،
    یا روی ماشینی دیگر). ستون‌ها و رفتارِ افزودن همان ماژولِ اصلی است تا رفت‌وبرگشت
    در هر دو حالت یکسان باشد و CI هم بتواند همین مسیر را واقعاً تست کند.
    """

    name = "fallback"
    FIELDS = _JR_FIELDS

    def _read(self, path):
        return _journal_rows(path) or []

    def cmd_add(self, a):
        import csv as _csv
        import datetime as _dt
        rows = self._read(a.file)
        ids = [int(r["id"]) for r in rows if str(r.get("id", "")).isdigit()]
        nid = str(max(ids) + 1) if ids else "1"
        row = {f: "" for f in _JR_FIELDS}
        row.update({
            "id": nid,
            "datetime": getattr(a, "datetime", None) or _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "symbol": str(getattr(a, "symbol", "") or "").upper(),
            "direction": getattr(a, "direction", "") or "",
            "session": getattr(a, "session", "") or "",
            "tf": getattr(a, "tf", "") or "",
            "htf_bias": getattr(a, "htf_bias", "") or "",
            "entry": getattr(a, "entry", "") or "",
            "sl": getattr(a, "sl", "") or "",
            "tp": getattr(a, "tp", "") or "",
            "rr": getattr(a, "rr", "") or "",
            "risk_pct": getattr(a, "risk_pct", "") or "",
            "setup": getattr(a, "setup", "") or "",
            "poi": getattr(a, "poi", "") or "",
            "reason": getattr(a, "reason", "") or "",
            "status": getattr(a, "status", "") or "open",
            "result": getattr(a, "result", None) or "",
            "exit": getattr(a, "exit", None) or "",
            "realized_r": getattr(a, "realized_r", None) or "",
            "mistake": getattr(a, "mistake", None) or "",
            "lesson": getattr(a, "lesson", None) or "",
            "notes": getattr(a, "notes", "") or "",
        })
        d = os.path.dirname(a.file)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
        with open(a.file, "w", newline="", encoding="utf-8") as fh:
            w = _csv.DictWriter(fh, fieldnames=_JR_FIELDS)
            w.writeheader()
            for r in rows:
                w.writerow({f: r.get(f, "") for f in _JR_FIELDS})
            w.writerow(row)
        print(json.dumps({"added": row["id"], "symbol": row["symbol"], "file": a.file},
                         ensure_ascii=False))


_JR = J if J is not None else _JournalFallback()
_JR_IMPL = "ماژولِ trade-journal" if J is not None else "نوشتارگرِ داخلی"


def _journal_fields():
    return list(getattr(_JR, "FIELDS", None) or _JR_FIELDS)


def _journal_rows(path):
    """ردیف‌های یک دفترِ CSV — None اگر فایل نبود یا خوانده نشد."""
    import csv as _csv
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return [r for r in _csv.DictReader(fh) if (r.get("symbol") or "").strip()]
    except Exception:
        return None


def _journal_migrate(path):
    """ردیف‌های دفترهای قدیمی (Desktop/Documents) را یک‌بار به فایلِ فعلی می‌آورد.

    بی‌خطر و تکرارپذیر: فایلِ قدیمی هیچ‌وقت پاک/عوض نمی‌شود، ردیفِ تکراری اضافه نمی‌شود
    و شناسه‌ی تازه با یادداشتِ شماره‌ی قبلی داده می‌شود. با env صریح، دست به هیچ فایلی نمی‌زند.
    """
    import csv as _csv
    if os.environ.get("PIPFOUND_JOURNAL_CSV"):
        return 0
    fields = _journal_fields()
    rows = _journal_rows(path) or []

    def key(r):
        return (r.get("datetime", ""), r.get("symbol", ""),
                r.get("direction", ""), str(r.get("entry", "")))

    have = {key(r) for r in rows}
    ids = [int(r["id"]) for r in rows if str(r.get("id", "")).isdigit()]
    nid = (max(ids) + 1) if ids else 1
    added = 0
    for lp in _JR_LEGACY:
        lp = os.path.expanduser(lp)
        if not os.path.exists(lp) or os.path.abspath(lp) == os.path.abspath(path):
            continue
        for r in (_journal_rows(lp) or []):
            k = key(r)
            if k in have:
                continue
            nr = {f: r.get(f, "") for f in fields}
            nr["id"] = str(nid)
            nid += 1
            nr["notes"] = (str(nr.get("notes", "")) +
                           f" · از دفترِ قدیمیِ {lp} (شماره‌ی قبلی {r.get('id', '?')})").strip(" ·")
            rows.append(nr)
            have.add(k)
            added += 1
    if added:
        d = os.path.dirname(path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = _csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow({f: r.get(f, "") for f in fields})
    return added


try:
    _JR_MOVED = _journal_migrate(_JR_FILE)
except Exception as _e:
    _JR_MOVED = 0
    print(f"📓 ژورنال: انتقالِ ردیف‌های قدیمی انجام نشد ({_e})")

# سبکِ معامله → تایم‌فریم‌ها (HTF اول). engine از این‌ها پشتیبانی می‌کند:
# 1m 5m 15m 30m 1h 4h 1d 1w
STYLES = {
    "scalp": {"label": "اسکالپ",   "tfs": ["1h", "30m", "15m", "5m"],  "entry_tf": "5m"},
    "day":   {"label": "روزانه",    "tfs": ["1d", "4h", "1h", "15m"],   "entry_tf": "15m"},
    "swing": {"label": "سوینگ",     "tfs": ["1w", "1d", "4h", "1h"],    "entry_tf": "1h"},
    # Silver Bullet نیویورک: اسکلپِ ۱ دقیقه‌ای که فقط در پنجره‌ی ۰۹:۰۰–۱۱:۰۰ ET
    # (اوجِ فعالیتِ اندازه‌گیری‌شده‌ی روز) معنا دارد. استکِ بایاسِ ۱۵m/۵m، ورود ۱m.
    "sb_ny": {"label": "سیلوربولت نیویورک", "tfs": ["15m", "5m", "1m"], "entry_tf": "1m"},
}

# انتخابِ سریعِ نماد — دسته‌بندیِ کارآمد در همان کادرِ جستجو.
# هر گروه = یک ردیفِ چیپ با برچسبِ فارسی؛ همین فهرست اتوکامپلیت را هم می‌سازد.
# عمداً فقط نمادهایی که مسیرِ دانلودشان تست شده: جفت‌ارزهای مهم، کامودیتی،
# اندیکس، و استاک (تکر‌های مگاکپ). کریپتو چیپ ندارد ولی با تایپ کار می‌کند.
SYMBOL_GROUPS = [
    ("جفت‌ارزهای مهم", ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
                          "USDCHF", "NZDUSD", "EURJPY", "GBPJPY"]),
    ("کامودیتی", ["XAUUSD", "XAGUSD", "WTI", "BRENT", "NATGAS", "COPPER"]),
    ("اندیکس", ["SPX500", "NAS100", "US30", "GER40", "UK100", "JP225"]),
    ("استاک", ["NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "GOOGL", "META"]),
]

# نمادهای پیشنهادی برای اتوکامپلیت = همه‌ی چیپ‌ها + کریپتو (که چیپ ندارد)
SUGGESTIONS = ([s for _, syms in SYMBOL_GROUPS for s in syms]
               + ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"])


def _setup_statuses(r):
    """ارزیابیِ زنده‌ی سه ستاپِ اسکلپ از روی چک‌لیستِ گریدر — چراغِ سبز/زرد/قرمز.

      🟢 سبز  = تأییدِ قوی: شرط‌های کلیدیِ ستاپ همین حالا برقرارند.
      🟡 زرد  = انتظار: بایاس هست ولی قیمت هنوز به محل/تریگر نرسیده.
      🔴 قرمز = شرایطِ ستاپ نیست.

    این تابع قضاوت جدیدی نمی‌سازد؛ فقط همان ردیف‌های چک‌لیستِ confluence را
    به سه ستاپِ منوی اسکلپ ترجمه می‌کند (صفر تکرارِ منطق).
    """
    rows = {c["name"]: c["status"] for c in (r.get("checklist") or [])}
    bias   = rows.get("بایاسِ تایم‌فریم بالا واضح") == "✓"
    align  = rows.get("هم‌راستاییِ چند تایم‌فریم", "✗") in ("✓", "◐")
    zone   = rows.get("پریمیوم/دیسکانتِ درست") == "✓"
    ote_in = rows.get("ناحیه‌ی OTE (۰.۶۲–۰.۷۹ فیب)") == "✓"
    sweep  = rows.get("سوئیپِ لیکوئیدیتیِ تازه (تریگر)") == "✓"
    choch  = rows.get("چاکِ ساختاری روی LTF") == "✓"
    seqok  = rows.get("توالیِ سوئیپ→ام‌اس‌اس") != "✗"
    disp   = rows.get("دیسپلیسمنت (حرکتِ نهادی)") == "✓"
    poi    = rows.get("نقطه‌ی ورود (اردر بلاک/فیرولیوگپ)") == "✓"
    htconf = rows.get("کانفلوئنسِ POIِ تایم‌فریم بالا") == "✓"
    rr_ok  = rows.get("امکانِ RR ≥ ۱:۲") == "✓"

    out = []
    # ستاپ ۱ — پولبک به OTE در امتداد روند
    if bias and zone and ote_in and (sweep or choch) and disp and seqok and rr_ok:
        out.append({"state": "green", "why": "قیمت در OTE + تریگرِ سوئیپ/چاک + دیسپلیسمنت — همه‌ی شرط‌ها برقرار"})
    elif bias and (zone or ote_in):
        out.append({"state": "yellow",
                    "why": "روند هست ولی قیمت هنوز در OTE نیست یا تریگر نیامده — منتظرِ پولبک/سوئیپ بمان"})
    else:
        out.append({"state": "red", "why": "بایاسِ واضح یا موقعیتِ درستِ قیمت نیست — ستاپ فعلاً منتفی"})

    # ستاپ ۲ — سوئیپِ سشن → برگشت از زون HTF
    if htconf and (choch or disp) and sweep:
        out.append({"state": "green", "why": "قیمت در زونِ تایمِ بالا + سوئیپ و برگشتِ تأییدشده"})
    elif htconf or (bias and poi):
        out.append({"state": "yellow",
                    "why": "قیمت نزدیک/داخلِ زونِ HTF است — صبر برای میتیگیتِ ۳۰٪ و MSS"})
    else:
        out.append({"state": "red", "why": "قیمت به هیچ زونِ عرضه/تقاضای تایمِ بالا نچسبیده"})

    # ستاپ ۳ — ادامه‌دهنده پس از BOS
    if align and disp and poi:
        out.append({"state": "green", "why": "BOS هم‌جهت + دیسپلیسمنت + POIِ مبدأ آماده‌ی پولبک"})
    elif align and disp:
        out.append({"state": "yellow",
                    "why": "شکستِ ساختار انجام شد — منتظرِ پولبک به مبدأِ حرکت (اردربلاک/FVG)"})
    else:
        out.append({"state": "red", "why": "BOS دیسپلیسمنت‌دارِ تازه‌ای در جهتِ روند نیست"})
    return out


def _risk_settings():
    """تنظیماتِ ریسکِ کاربر؛ اگر ماژول بار نشده باشد، پیش‌فرض‌های همان ماژول.

    مرجعِ واحدِ مسیر/پیش‌فرض‌ها خودِ `risk.py` است (نه یک کپیِ دوم در app) تا دو
    جای مختلف دو جوابِ متفاوت ندهند. مسیر با `PIPFOUND_RISK_FILE` قابلِ جابه‌جایی است.
    """
    if RK is None:
        return {"balance": 10000.0, "account_ccy": "USD", "risk_pct": 1.0,
                "daily_loss_limit_pct": 3.0, "max_open_risk_pct": 5.0,
                "usd_per_quote": {}}
    try:
        return RK.load_settings()
    except Exception:
        return RK.DEFAULTS


def _risk_block(symbol, r):
    """بلوکِ ریسک برای یک تحلیل + اعمالِ «گیتِ سقفِ ضررِ روزانه».

    عمداً در همین حلقه (app) و نه در `confluence.py` محاسبه می‌شود: این بلوک به
    تنظیماتِ کاربر و دفترِ معاملات نیاز دارد؛ اگر داخلِ گریدر برود، نتیجه‌ی
    بک‌تست هم عوض می‌شود در حالی که بک‌تست اصلاً سرمایه/دفتر ندارد.

    گیت: وقتی سقفِ ضررِ روزانه پر شده یا مجموعِ ریسکِ باز از سقف گذشته باشد،
    پلن دیگر «سیگنالِ ورود» نیست — مثلِ حالتِ «بازار بسته» درجه سقف می‌خورد و
    مهرِ ورود صادر نمی‌شود، ولی خودِ پلن برای آماده‌سازی می‌ماند.
    """
    if RK is None:
        return None
    try:
        st = RK.load_settings()
        rows = _journal_rows(_JR_FILE) or []
        blk = RK.evaluate(symbol, (r or {}).get("plan"), st, rows)
    except Exception:
        traceback.print_exc()
        return None
    plan = (r or {}).get("plan")
    if blk.get("blocked") and plan:
        reason = blk.get("block_reason") or "محدودیتِ ریسک"
        plan["executable_now"] = False
        plan["blocked_reason"] = reason
        plan["risk_blocked"] = True
        if r.get("grade") in ("A+", "A", "B"):
            r["grade"] = "C"
        r["verdict"] = ("⛔ " + reason +
                        " — طبقِ همین سقف، ورودِ جدید مجاز نیست. " +
                        (r.get("verdict") or ""))
        es = r.get("entry_stamp")
        if isinstance(es, dict):
            es["stamped"] = False
            rs = es.setdefault("reasons", [])
            if reason not in rs:
                rs.insert(0, reason)
    return blk


def analyze(symbol, style):
    """اجرای اسکنر برای یک نماد + سبک و برگرداندنِ دیکشنریِ کامل."""
    sty = STYLES.get(style, STYLES["day"])
    tfs = sty["tfs"]
    r = C.score(symbol.strip().upper(), tfs)
    r["style"] = sty["label"]
    r["style_key"] = style if style in STYLES else "day"
    r["entry_tf"] = sty["entry_tf"]
    # گیتِ زمانیِ سیلوربولت: در حالتِ sb_ny اگر خارج از پنجره‌ی ۰۹:۰۰–۱۱:۰۰ ET باشیم،
    # هیچ پلنِ ورودی نباید نمایش داده شود (استراتژی فقط در این پنجره معتبر است).
    # این گیت جدا از منطقِ نمره است — فقط اجرای زنده را قفلِ زمانی می‌کند.
    if style == "sb_ny":
        try:
            _w = E.silver_bullet_window()
            if not _w.get("in_window"):
                r["plan"] = None
                if r.get("entry_stamp"):
                    r["entry_stamp"]["stamped"] = False
                    r["entry_stamp"].setdefault("reasons", []).insert(
                        0, "خارج از پنجره‌ی ۰۹:۰۰–۱۱:۰۰ ET — سیلوربولت فقط در این پنجره ورود می‌دهد")
                # verdict هم باید صادقانه بگوید چرا ورود ممنوع است، نه فقط درباره‌ی زون حرف بزند
                _h, _m = _w.get("et_hour", 0), _w.get("et_minute", 0)
                r["verdict"] = (
                    f"⏳ سیلوربولتِ نیویورک فقط بینِ ۰۹:۰۰ تا ۱۱:۰۰ به‌وقتِ نیویورک ورود می‌دهد. "
                    f"الان {_h:02d}:{_m:02d} ET است — خارج از پنجره؛ تحلیلِ ساختاری بالا فقط برای "
                    f"بایاس‌گیریِ قبل از پنجره است (روندِ روز + لیکوئیدیتی‌های هدف را علامت بزن) "
                    f"و نزدیکِ ۰۹:۰۰ برگرد و مراحلِ سوئیپ→ام‌اس‌اس→فیرولیوگپ را روی چارتِ ۱ دقیقه دنبال کن.")
        except Exception:
            pass
    # macro gate (اختیاری)
    macro = None
    if M is not None:
        try:
            b = M.build(symbol) if hasattr(M, "build") else None
            if isinstance(b, dict):
                macro = {}
                g = b.get("news_gate") or {}
                macro["gate"] = g.get("status")
                macro["advice"] = g.get("advice")
                up = b.get("upcoming_high_impact_48h") or []
                titles = []
                for e in up[:5]:
                    if isinstance(e, dict):
                        t = e.get("title") or e.get("event")
                        if t:
                            titles.append(t)
                    elif isinstance(e, str):
                        titles.append(e)
                if titles:
                    macro["upcoming"] = titles
                sess = b.get("active_sessions")
                if sess:
                    macro["sessions"] = sess
        except Exception:
            macro = None
    r["macro"] = macro
    # چراغِ زنده‌ی سه ستاپِ اسکلپ (سبز/زرد/قرمز) — از روی چک‌لیستِ همان تحلیل
    try:
        r["setup_statuses"] = _setup_statuses(r)
    except Exception:
        r["setup_statuses"] = None
    # پنجره‌ی Silver Bullet نیویورک (۰۹:۰۰–۱۱:۰۰ ET) — برای گیتِ زمانیِ استراتژیِ sb_ny
    # و نمایشِ تایمرِ آلارمِ ساعتِ ۹ در UI.
    try:
        r["sb_window"] = E.silver_bullet_window()
    except Exception:
        r["sb_window"] = None
    # ── مدلِ ریسک: سایزِ پوزیشن + سقفِ ضررِ روزانه + هشدارِ هم‌بستگی ──
    # بعد از همه‌ی گیت‌ها می‌آید تا پلنِ نهایی (و درجه‌ای که ممکن است سقف خورده
    # باشد) را ببیند؛ خودش هم می‌تواند درجه را سقف بزند.
    r["risk"] = _risk_block(symbol, r)
    r["is_sb_mode"] = (style == "sb_ny")
    return r


# آخرین وضعیتِ داده‌ی هر نماد (از آخرین تحلیل) → برای اندپوینتِ /api/data_status.
# چرا: چیپِ «سنِ داده» باید ارزشپیش از هر تحلیلی هم چیزی بگوید، و نمی‌خواهیم برای
# هر بارِ لودِ صفحه چند تایم‌فریم را از نو دانلود کنیم (محدودیتِ نرخ).
_last_seen_lock = threading.Lock()


def _load_seen():
    """آخرین وضعیتِ داده‌ی تحلیل‌ها را از دیسک می‌خواند (خرابی/نبود ⇒ دیکشنریِ خالی)."""
    try:
        with open(DATA_SEEN_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


_LAST_SEEN = _load_seen()


def _save_seen():
    """نوشتنِ اتمیک؛ خطا نباید تحلیل را بشکند (این فقط یک نشانگر است)."""
    try:
        os.makedirs(os.path.dirname(DATA_SEEN_FILE), exist_ok=True)
        tmp = DATA_SEEN_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_LAST_SEEN, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_SEEN_FILE)
    except Exception:
        pass


def _remember_analysis(symbol, style, r):
    """خلاصه‌ی بلوکِ داده‌ی یک تحلیلِ تازه را نگه می‌دارد (فقط برای /api/data_status)."""
    try:
        d = (r or {}).get("data") or {}
        if not d:
            return
        key = (symbol or "").strip().upper()
        with _last_seen_lock:
            _LAST_SEEN[key] = {
                "symbol": key, "style": style,
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "state": d.get("state"), "reason": d.get("reason"),
                "tf": d.get("tf"), "last_bar_ts": d.get("last_bar_ts"),
                "tf_seconds": d.get("bar_seconds"),
                "symbol_class": d.get("symbol_class"), "source": d.get("source"),
            }
            if len(_LAST_SEEN) > 40:
                for k in sorted(_LAST_SEEN, key=lambda k: _LAST_SEEN[k].get("at", ""))[:10]:
                    _LAST_SEEN.pop(k, None)
            _save_seen()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
#  سیستمِ آلارمِ زنده روی ناحیه‌ی OTE
# ═══════════════════════════════════════════════════════════════════
# نمادهای پشتیبانی‌شده برای آلارم (نقره/طلا/EURUSD/BTC + چند تای دیگر)
ALARM_SYMBOLS = ["XAUUSD", "XAGUSD", "EURUSD", "BTCUSDT", "GBPUSD", "ETHUSDT"]

_alarms_lock = threading.Lock()


def _load_alarms():
    try:
        with open(ALARMS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_alarms(alarms):
    os.makedirs(os.path.dirname(ALARMS_FILE), exist_ok=True)
    tmp = ALARMS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(alarms, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ALARMS_FILE)


def _live_price(symbol):
    """قیمتِ زنده‌ی نماد را از موتور می‌گیرد (آخرین کندلِ ۵m).

    `unclosed=True` مهم است: این‌جا برخلافِ تحلیل، **خودِ کندلِ در حالِ تشکیل**
    همان قیمتِ زنده است (آلارم باید ببیند «الان» قیمت کجاست، نه کلوزِ ۵ دقیقه پیش).
    """
    try:
        src, sym, disp, bars = E.fetch(symbol.strip().upper(), "5m", 3, unclosed=True)
        if bars:
            return float(bars[-1]["c"])
    except Exception:
        pass
    return None


def compute_ote_for(symbol, style):
    """ناحیه‌ی OTE + جهت + قیمتِ فعلی را برای یک نماد برمی‌گرداند (برای آلارم)."""
    sty = STYLES.get(style, STYLES["day"])
    r = C.score(symbol.strip().upper(), sty["tfs"])
    return {
        "symbol": symbol.strip().upper(),
        "direction": r.get("direction"),
        "grade": r.get("grade"),
        "last_price": r.get("last_price"),
        "ote": r.get("ote"),
    }


def _notify_mac(title, message):
    """نوتیفیکیشنِ نیتیوِ مک (بدونِ وابستگی)."""
    try:
        import subprocess
        t = title.replace('"', "'")
        m = message.replace('"', "'")
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{m}" with title "{t}" sound name "Glass"'],
            capture_output=True, timeout=5)
    except Exception:
        pass


def _alarm_worker():
    """هر ۹۰ ثانیه آلارم‌های فعال را بررسی می‌کند؛ اگر قیمتِ زنده داخلِ OTE بیفتد
    یا از حدِ تعیین‌شده رد شود، آن آلارم را triggered علامت می‌زند."""
    while True:
        try:
            with _alarms_lock:
                alarms = _load_alarms()
            changed = False
            for a in alarms:
                if a.get("triggered") or not a.get("active", True):
                    continue
                sym = a["symbol"]
                px = _live_price(sym)
                if px is None:
                    continue
                a["last_price"] = round(px, 5)
                a["last_check"] = time.strftime("%Y-%m-%d %H:%M:%S")
                hit = False
                if a["mode"] == "ote":
                    lo, hi = a.get("low"), a.get("high")
                    if lo is not None and hi is not None and lo <= px <= hi:
                        hit = True
                        a["hit_reason"] = f"قیمت {round(px,5)} واردِ ناحیه‌ی OTE ({lo}–{hi}) شد"
                elif a["mode"] == "price":
                    tgt = a.get("target")
                    d = a.get("cross", "any")
                    if tgt is not None:
                        if (d == "above" and px >= tgt) or (d == "below" and px <= tgt) \
                           or (d == "any" and abs(px - tgt) <= abs(tgt) * 0.0003):
                            hit = True
                            a["hit_reason"] = f"قیمت {round(px,5)} به هدفِ {tgt} رسید"
                if hit:
                    a["triggered"] = True
                    a["triggered_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    changed = True
                    _notify_mac(
                        f"pipfound — {sym} به ناحیه‌ی OTE رسید",
                        a.get("hit_reason", f"قیمت {round(px,5)}"))
                else:
                    changed = True
            if changed:
                with _alarms_lock:
                    _save_alarms(alarms)
        except Exception:
            traceback.print_exc()
        time.sleep(90)


# ═══════════════════════════════════════════════════════════════════
#  اسکرین‌شاتِ چارت — آپلود، فهرست، نمایش
# ═══════════════════════════════════════════════════════════════════
_shots_lock = threading.Lock()


def _shots_meta_file():
    return os.path.join(SHOTS_DIR, "index.json")


def _load_shots():
    try:
        with open(_shots_meta_file(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_shots(shots):
    os.makedirs(SHOTS_DIR, exist_ok=True)
    tmp = _shots_meta_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(shots, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _shots_meta_file())


def _tv_symbol(symbol):
    """نگاشتِ نمادِ داخلی به نمادِ ویجتِ TradingView."""
    s = (symbol or "").strip().upper()
    crypto = {"BTCUSDT": "BINANCE:BTCUSDT", "ETHUSDT": "BINANCE:ETHUSDT",
              "SOLUSDT": "BINANCE:SOLUSDT", "BNBUSDT": "BINANCE:BNBUSDT",
              "XRPUSDT": "BINANCE:XRPUSDT", "DOGEUSDT": "BINANCE:DOGEUSDT"}
    metals = {"XAUUSD": "OANDA:XAUUSD", "XAGUSD": "OANDA:XAGUSD",
              "XPTUSD": "OANDA:XPTUSD", "XPDUSD": "OANDA:XPDUSD",
              "GOLD": "OANDA:XAUUSD"}
    oil = {"WTI": "TVC:USOIL", "BRENT": "TVC:UKOIL"}
    if s in crypto:
        return crypto[s]
    if s in metals:
        return metals[s]
    if s in oil:
        return oil[s]
    # فارکسِ استاندارد ۶ حرفی → FX_IDC
    if len(s) == 6 and s.isalpha():
        return "FX_IDC:" + s
    return s


def start_alarm_worker():
    t = threading.Thread(target=_alarm_worker, daemon=True)
    t.start()
    return t


# ═══════════════════════════════════════════════════════════════════
#  آلارمِ فاندمنتال — نوتیفیکیشنِ نیتیو ~۲۴ ساعت پیش از هر خبرِ پرتأثیر (یک‌بار)
# ═══════════════════════════════════════════════════════════════════
_FUND_FIRED_FILE = os.path.join(HOME, "pipfound", "fund_alarms_fired.json")
_fund_lock = threading.Lock()


def _load_fired():
    try:
        with open(_FUND_FIRED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def _save_fired(fired):
    try:
        os.makedirs(os.path.dirname(_FUND_FIRED_FILE), exist_ok=True)
        tmp = _FUND_FIRED_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sorted(fired), f)
        os.replace(tmp, _FUND_FIRED_FILE)
    except Exception:
        pass


def _fund_alarm_worker():
    """هر ۱۰ دقیقه اخبارِ پرتأثیر را می‌سنجد؛ برای خبری که بینِ ۲۳ تا ۲۵ ساعتِ آینده
    است، یک‌بار نوتیفیکیشنِ نیتیوِ مک می‌فرستد (ساعتِ اعلام به‌وقتِ تهران + جهتِ اثر)."""
    if FUND is None:
        return
    while True:
        try:
            with _fund_lock:
                fired = _load_fired()
            data = FUND.build(hours=48)
            changed = False
            for e in (data.get("events") or []):
                if e.get("impact") != "High":
                    continue
                h = e.get("in_hours", 999)
                key = e.get("iso", "") + "|" + (e.get("title") or "")
                if key in fired:
                    continue
                # پنجره‌ی ~۲۴ ساعت پیش از خبر (۲۳–۲۵ ساعت مانده)
                if 23 <= h <= 25:
                    a = e.get("analysis") or {}
                    ttl = e.get("title_fa") or e.get("title") or "خبرِ اقتصادی"
                    ccy = e.get("country_fa") or e.get("country") or ""
                    beat = (a.get("beat") or {})
                    gold = (beat.get("gold") or ["", "", ""])
                    msg = (f"{e.get('tehran','')} — {ccy}. "
                           f"عددِ قوی‌تر → {beat.get('ccy_dir','')}، "
                           f"طلا/نقره {gold[1]}. برای تحلیلِ کامل کلیدِ 📰 فاندمنتال را بزن.")
                    _notify_mac(f"📰 فردا: {ttl}", msg)
                    fired.add(key)
                    changed = True
            # پاک‌سازیِ کلیدهای قدیمی (خبرهایی که گذشته‌اند) تا فایل بی‌نهایت رشد نکند
            if changed:
                live = {e.get("iso", "") + "|" + (e.get("title") or "")
                        for e in (data.get("events") or [])}
                fired = {k for k in fired if k in live}
                with _fund_lock:
                    _save_fired(fired)
        except Exception:
            traceback.print_exc()
        time.sleep(600)


def start_fund_alarm_worker():
    t = threading.Thread(target=_fund_alarm_worker, daemon=True)
    t.start()
    return t


# ── بازنگریِ کدِ در حالِ اجرا (revision) ──────────────────────────────────────
# چرا: پایتون کد را *لحظهٔ استارت* می‌خواند. اگر بعد از ادغام، همان پروسهٔ قدیمی
# سرو کند، رابطِ کهنه دیده می‌شود و دقیقاً شبیهِ «کلیدها گم شدند» به‌نظر می‌رسد،
# در حالی که کد سالم است. اینجا ثبت می‌کنیم چه کدی در حافظه بار شده و دیسک
# الان چه چیزی دارد تا «کهنه سرو شدن» بی‌درنگ قابلِ دیدن باشد.
REV_ROOT = os.path.dirname(os.path.abspath(__file__))
# فایل‌هایی که تعیین می‌کنند کدام رابط سرو می‌شود (نه داده‌های زمانِ اجرا)
REV_TRACKED = [
    "app.py", "selfcheck.py", "confluence.py", "smc_engine.py", "backtest.py",
    "macro_context.py", "fundamental.py", "sw.js", "manifest.webmanifest",
]


def _rev_track_imported():
    """هر ماژولِ هم‌پوشه‌ای که واقعاً import شده را به فهرستِ ردیابی اضافه می‌کند.

    چرا لازم شد: همین فهرستِ دستی یک بار ماژولِ تازه (`risk.py`) را از قلم
    انداخته بود؛ نتیجه‌اش این بود که ویرایشِ آن ماژول هیچ‌وقت ری‌استارتِ خودکار را
    تریگر نمی‌کرد و پروسه تا ابد نسخهٔ قدیمیِ آن ماژول را سرو می‌کرد — بی‌صدا،
    دقیقاً همان «کهنه سرو شدن»ی که این مکانیزم برای بستنش ساخته شد.
    """
    for mod in (C, E, BT, M, FUND, RK):
        try:
            p = getattr(mod, "__file__", None)
            if not p:
                continue
            p = os.path.abspath(p)
            if os.path.dirname(p) != REV_ROOT:
                continue          # ماژولِ همسایه (مثلِ ژورنال) مسیرِ دیگری دارد
            name = os.path.basename(p)
            if name not in REV_TRACKED:
                REV_TRACKED.append(name)
        except Exception:
            pass


_rev_track_imported()
_BOOT_TS = time.time()
_BOOT_MONO = time.monotonic()
_PROC_PID = os.getpid()


def _rev_git(root):
    """SHA/شاخه/dirty را با git می‌خواند؛ بدونِ git یا بیرونِ ریپو → None."""
    import subprocess
    out = {"sha": None, "sha_full": None, "branch": None, "dirty": None}

    def _git(*args):
        try:
            r = subprocess.run(["git", "-C", root, *args],
                               capture_output=True, text=True, timeout=4)
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:
            return None

    full = _git("rev-parse", "HEAD")
    if full:
        out["sha_full"] = full
        out["sha"] = full[:7]
        out["branch"] = _git("rev-parse", "--abbrev-ref", "HEAD")
        st = _git("status", "--porcelain")
        out["dirty"] = bool(st) if st is not None else None
    return out


def _rev_mtimes():
    files = {}
    for name in REV_TRACKED:
        try:
            files[name] = os.path.getmtime(os.path.join(REV_ROOT, name))
        except OSError:
            files[name] = None
    return files


def _fmt_ts(ts):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


# ── ری‌استارتِ خودکارِ «کهنه» ─────────────────────────────────────────────
# چرا: حتی با نشانگرِ بازنگری، کاربر باید خودش دخالت کند. اینجا سرور خودش می‌فهمد
# کدِ روی دیسک تازه‌تر از پروسهٔ خودش است، کدِ تازه را اول **اعتبارسنجی** می‌کند
# (تا هرگز پروسهٔ سالم را برای یک ویرایشِ خراب نکشد)، صبر می‌کند هیچ درخواستی
# در جریان نباشد، و بعد با `os.execv` خود را در همان PID از نو اجرا می‌کند.
# همان PID مهم است: جابِ launchd و ثبتِ پیش‌نمایش با همان شناسه معتبر می‌مانند.
def _env_float(name, default):
    try:
        return float(os.environ.get(name, "") or default)
    except Exception:
        return default


_REV_WATCH = {
    "enabled": (os.environ.get("PIPFOUND_AUTORESTART", "1").strip().lower()
                not in ("0", "false", "no", "off")),
    "interval": max(1.0, _env_float("PIPFOUND_AUTORESTART_INTERVAL", 5.0)),
    "settle": max(0.0, _env_float("PIPFOUND_AUTORESTART_SETTLE", 3.0)),
    "max_wait_idle": max(0.0, _env_float("PIPFOUND_AUTORESTART_MAXWAIT", 180.0)),
    "restarts": 0,
    "waiting": False,
    "blocked": None,        # کدِ تازه روی دیسک سالم نبود / exec نشد
    "blocked_mtime": None,
    "drift_pair": None,     # «loaded>disk» که در حالِ دیده‌شدن است (برای آرامشِ SHA)
    "drift_since": None,
}
_REV_LOCK = threading.Lock()

_REV_BOOT = {
    "boot_ts": _BOOT_TS,
    "boot_iso": _fmt_ts(_BOOT_TS),
    "pid": _PROC_PID,
    "files": _rev_mtimes(),
    "git": _rev_git(REV_ROOT),
}


def _rev_state_file():
    return os.path.join(HOME, "pipfound", "autorestart.json")


def _rev_state_read():
    """آخرین ری‌استارتِ خودکار — از فایل می‌خواند تا بعد از exec هم باقی بماند."""
    try:
        with open(_rev_state_file(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _rev_state_write(rec):
    fp = _rev_state_file()
    try:
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        tmp = fp + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        os.replace(tmp, fp)
    except Exception as e:
        print("⚠️ ثبتِ وضعیتِ ری‌استارت ناموفق: %s" % e, flush=True)


def code_rev():
    """بازنگریِ کدِ بارشده در برابرِ دیسک + وضعیتِ ری‌استارتِ خودکار.

    stale=True یعنی چیزی روی دیسک تازه‌تر از استارتِ این پروسه است (یا SHA عوض
    شده)، پس نسخه‌ای که سرو می‌شود کهنه است.
    """
    now_files = _rev_mtimes()
    changed = []
    for name, mt in now_files.items():
        base = _REV_BOOT["files"].get(name)
        if mt is None:
            continue
        if base is None or mt > base + 1e-6:
            changed.append({"file": name, "mtime": _fmt_ts(mt), "mtime_epoch": mt})
    disk_git = _rev_git(REV_ROOT)
    loaded = _REV_BOOT["git"]
    sha_drift = (disk_git.get("sha") or None) != (loaded.get("sha") or None)
    stale = bool(changed) or sha_drift
    with _REV_LOCK:
        ar = {"enabled": _REV_WATCH["enabled"],
              "interval_s": _REV_WATCH["interval"],
              "settle_s": _REV_WATCH["settle"],
              "restarts": _REV_WATCH["restarts"],
              "waiting": _REV_WATCH["waiting"],
              "blocked": _REV_WATCH["blocked"]}
    ar["last"] = _rev_state_read()
    if not stale:
        note = "کدِ سروشده با دیسک یکی است"
    elif ar["blocked"]:
        note = "نسخه‌ی کهنه سرو می‌شود و کدِ تازه سالم نیست — ری‌استارت انجام نمی‌شود"
    elif ar["enabled"]:
        note = "نسخه‌ی کهنه سرو می‌شود — ری‌استارتِ خودکار به‌زودی انجام می‌شود"
    else:
        note = "نسخه‌ی کهنه سرو می‌شود — ری‌استارتِ خودکار خاموش است؛ اپ را از نو بالا بیاور"
    return {
        "ok": True,
        "stale": stale,
        "pid": _PROC_PID,
        "uptime_s": round(time.monotonic() - _BOOT_MONO, 1),
        "boot_ts": _REV_BOOT["boot_ts"],
        "boot_local": _REV_BOOT["boot_iso"],
        "loaded": loaded,
        "disk": disk_git,
        "sha_drift": sha_drift,
        "changed_files": changed,
        "tracked_files": [{"file": n, "mtime_epoch": m} for n, m in now_files.items()],
        "autorestart": ar,
        "note": note,
    }


def _rev_argv():
    """دستورِ خودِ همین پروسه برای اجرای دوباره (orig_argv پرچم‌هایی مثلِ -u را نگه می‌دارد)."""
    argv = getattr(sys, "orig_argv", None)
    if argv:
        return list(argv)
    return [sys.executable, "-u"] + list(sys.argv)


def _rev_validate():
    """کدِ تازه روی دیسک قبل از ری‌استارت اعتبارسنجی می‌شود.

    بدونِ این مرحله، یک ویرایشِ نیمه‌کاره/خراب سرورِ سالم را می‌کشت.
    """
    try:
        import selfcheck as SC
        rep = SC.run_checks(REV_ROOT)
        if rep.get("ok"):
            return True, "selfcheck ✅"
        return False, " | ".join(rep.get("problems") or [])[:400] or "selfcheck ❌"
    except Exception as e:
        return False, "selfcheck در دسترس نیست: %s" % e


def _rev_restart(rev, detail, guard_key=None):
    files = [c["file"] for c in (rev.get("changed_files") or [])]
    from_sha = (rev.get("loaded") or {}).get("sha")
    to_sha = (rev.get("disk") or {}).get("sha")
    if guard_key is None:
        guard_key = max([c["mtime_epoch"] for c in (rev.get("changed_files") or [])]
                        or [None])
    with _REV_LOCK:
        _REV_WATCH["restarts"] += 1
        _REV_WATCH["drift_pair"] = None
        _REV_WATCH["drift_since"] = None
    _rev_state_write({"at": _fmt_ts(time.time()), "from": from_sha, "to": to_sha,
                      "files": files, "detail": detail, "pid": _PROC_PID})
    print("♻️ کدِ تازه روی دیسک دیده شد (%s) — ری‌استارتِ خودکار [%s] · %s → %s"
          % (", ".join(files) or "فقط SHA عوض شده", detail,
             from_sha or "?", to_sha or "?"), flush=True)
    try:
        for h in (sys.stdout, sys.stderr):
            try:
                h.flush()
            except Exception:
                pass
        os.execv(sys.executable, _rev_argv())
    except Exception as e:
        with _REV_LOCK:
            _REV_WATCH["blocked"] = {"at": _fmt_ts(time.time()),
                                     "detail": "ری‌استارت انجام نشد: %s" % e}
            _REV_WATCH["blocked_mtime"] = guard_key
        print("⚠️ ری‌استارتِ خودکار ممکن نشد (%s) — روی همین نسخه ادامه می‌دهم."
              % e, flush=True)


def _rev_watch_once():
    """یک دورِ بررسی: کهنه است؟ کدِ تازه سالم است؟ درخواستی در جریان نیست؟ → ری‌استارت.

    دو نشانه‌ی مستقلِ «کهنه» هر دو باید محرک باشند:
      · mtimeِ فایل‌های تعیین‌کننده‌ی رابط تازه‌تر از استارتِ پروسه شده باشد؛
      · SHAِ HEAD روی دیسک با SHAِ بارشده فرق کند — کامیتی که هیچ‌کدام از آن
        فایل‌های فهرست‌شده را لمس نکرده (مستندات/CI/ابزار) هم پروسه را کهنه
        می‌کند. اگر این شاخه نادیده گرفته شود، چیپ تا ابد قرمز می‌ماند و می‌گوید
        «ری‌استارت در راه است» ولی هیچ‌وقت نمی‌آید — بی‌صدا نسخه‌ی کهنه سرو می‌شود.
    """
    if not _REV_WATCH["enabled"]:
        return False
    rev = code_rev()
    changed = rev.get("changed_files") or []
    drift = bool(rev.get("sha_drift"))
    if not changed and not drift:
        with _REV_LOCK:
            _REV_WATCH["blocked"] = None
            _REV_WATCH["blocked_mtime"] = None
            _REV_WATCH["drift_pair"] = None
            _REV_WATCH["drift_since"] = None
        return False

    if changed:
        settle_from = max(c["mtime_epoch"] for c in changed)
    else:
        # هیچ mtimeی برای مقایسه نداریم، پس خودِ «دیده‌شدنِ دریفت» مرجعِ آرامش است
        # تا وسطِ یک checkout/pullِ نیمه‌کاره ری‌استارت نکنیم.
        pair = "%s>%s" % ((rev.get("loaded") or {}).get("sha"),
                           (rev.get("disk") or {}).get("sha"))
        with _REV_LOCK:
            if _REV_WATCH["drift_pair"] != pair or _REV_WATCH["drift_since"] is None:
                _REV_WATCH["drift_pair"] = pair
                _REV_WATCH["drift_since"] = time.time()
            settle_from = _REV_WATCH["drift_since"]
    newest = settle_from
    # شاید همین حالا مشغولِ نوشتنِ فایل/گیت هستیم → کمی صبر کن
    if time.time() - settle_from < _REV_WATCH["settle"]:
        return False
    # همان فایلِ خرابی که قبلاً رد شده بود را دوباره اعتبارسنجی نکن (بی‌فایده و گران)
    with _REV_LOCK:
        if _REV_WATCH["blocked"] and _REV_WATCH["blocked_mtime"] == newest:
            return False
    ok, detail = _rev_validate()
    if not ok:
        with _REV_LOCK:
            fresh = _REV_WATCH["blocked"] is None
            _REV_WATCH["blocked"] = {"at": _fmt_ts(time.time()), "detail": detail}
            _REV_WATCH["blocked_mtime"] = newest
        if fresh:
            print("⚠️ کدِ تازه روی دیسک هست ولی سالم نیست (%s) — روی نسخه‌ی فعلی می‌مانم."
                  % detail, flush=True)
        return False
    # تمیز: تا هیچ درخواستی در جریان نباشد صبر کن (تا وسطِ یک تحلیل قطع نشود)
    with _REV_LOCK:
        _REV_WATCH["waiting"] = True
    try:
        waited = 0.0
        while not _REQ_IDLE.is_set() and waited < _REV_WATCH["max_wait_idle"]:
            time.sleep(0.2)
            waited += 0.2
    finally:
        with _REV_LOCK:
            _REV_WATCH["waiting"] = False
    _rev_restart(rev, detail, guard_key=newest)
    return True


def _rev_watch_worker():
    time.sleep(min(4.0, max(1.0, _REV_WATCH["interval"])))
    while True:
        time.sleep(max(1.0, _REV_WATCH["interval"]))
        try:
            _rev_watch_once()
        except Exception:
            traceback.print_exc()


HTML = r"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pipfound — تحلیلگرِ اسمارت‌مانی (SMC / ICT)</title>
<meta name="theme-color" content="#0b0f17">
<link rel="icon" href="/icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="pipfound">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icon-180.png">
<script>
/* نگهبانِ بوت: اگر اسکریپتِ اصلی به هر دلیلی از کار بیفتد، به‌جای صفحه‌ی مرده هشدار بده */
window.__pipfoundBooted = false;
function pipfoundBootWarn(){
  if(document.getElementById("bootWarn")) return;
  var b=document.body; if(!b){ setTimeout(pipfoundBootWarn, 120); return; }
  var d=document.createElement("div"); d.id="bootWarn";
  d.setAttribute("style","position:fixed;top:0;left:0;right:0;z-index:2147483647;background:#7f1d1d;"+
    "color:#fff;padding:10px 14px;font:13px/1.8 system-ui,Tahoma,sans-serif;text-align:center;"+
    "box-shadow:0 6px 24px rgba(0,0,0,.5)");
  d.textContent="⚠️ بخشی از کدِ این صفحه خطای نحوی دارد (دکمه‌ها بی‌اثر می‌شوند). اپ را ببند و دوباره باز کن؛ "+
    "نگهبانِ سلامت خودش نسخه‌ی سالمِ قبلی را برمی‌گرداند. بررسیِ دستی: python3 selfcheck.py";
  b.appendChild(d);
}
window.addEventListener("error", function(e){
  if(window.__pipfoundBooted) return;
  if(e && e.message && String(e.message).indexOf("Script error")>=0) return;
  pipfoundBootWarn();
});
setTimeout(function(){ if(!window.__pipfoundBooted) pipfoundBootWarn(); }, 3000);
</script>
<style>
:root{
  --bg:#0b0f17; --panel:#141a26; --panel2:#1b2333; --line:#28324a;
  --txt:#e8eefc; --muted:#8a97b3; --accent:#4da3ff; --accent2:#22d3a5;
  --good:#22c55e; --bad:#ef4444; --warn:#f59e0b; --half:#eab308;
  --grade-ap:#22d3a5; --grade-a:#4ade80; --grade-b:#facc15; --grade-c:#fb923c; --grade-no:#64748b;
}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 80% -10%,#16223b 0%,var(--bg) 55%);
  color:var(--txt);font-family:-apple-system,BlinkMacSystemFont,"Vazirmatn","Segoe UI",Tahoma,sans-serif;
  min-height:100vh;padding:28px 16px}
.wrap{max-width:920px;margin:0 auto}
.header{display:flex;align-items:center;gap:12px;margin-bottom:6px}
h1{font-size:22px;margin:0;font-weight:700;letter-spacing:.2px;
  background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent}
.sub{color:var(--muted);font-size:13px;margin:2px 0 22px}
.revchip{font-size:11px;color:var(--muted);border:1px solid var(--line);
  background:var(--panel2);border-radius:999px;padding:4px 10px;white-space:nowrap;cursor:default;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;direction:ltr;transition:.15s}
.revchip.warn{color:var(--warn);border-color:#a16207;background:#2a1f05}
.revchip.bad{color:#fca5a5;border-color:#7f1d1d;background:#2a0a0a}
.chiprow{margin-left:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
/* بنرِ تازگیِ داده/بازار در کارتِ نتیجه — قبل از پلن خوانده می‌شود */
.datanote{margin:10px 0 4px;padding:9px 12px;border-radius:12px;font-size:12.5px;line-height:1.8;
  border:1px solid var(--line);background:var(--panel2);direction:rtl}
.datanote b{font-weight:700}
.datanote-why{margin-top:3px;font-size:12px;opacity:.92}
.datanote.data-ok{color:#4ade80;border-color:rgba(74,222,128,.35)}
.datanote.data-warn{color:var(--warn);border-color:#a16207;background:#2a1f05}
.datanote.data-closed{color:#fca5a5;border-color:#7f1d1d;background:#2a0a0a}
/* پنلِ ریسک — سرمایه/درصد/سقف‌ها + وضعیتِ امروز (ژورنال) */
.riskpanel{margin-top:12px;padding:12px 12px 10px;border:1px solid var(--line);border-radius:14px;
  background:var(--panel2)}
.risktitle{font-size:12.5px;color:var(--muted);font-weight:700;margin-bottom:9px;line-height:1.8}
.riskrow{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.rinp{background:var(--panel);border:1px solid var(--line);border-radius:10px;color:var(--txt);
  font-size:14px;padding:8px 10px;outline:none;width:104px;direction:ltr;text-align:center;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;transition:.15s}
.rinp:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(77,163,255,.18)}
.rinp.wide{width:132px}
.riskbtn{background:var(--accent);color:#04241b;border:0;border-radius:10px;padding:9px 16px;
  font-family:inherit;font-size:13px;font-weight:700;cursor:pointer}
.riskbtn:disabled{opacity:.5;cursor:default}
.riskstat{margin-top:9px;font-size:12px;color:var(--muted);line-height:1.9}
.riskstat b{color:var(--txt)}
.riskstat .bad{color:#fca5a5}
.riskstat .good{color:var(--good)}
.riskstat .warn{color:var(--warn)}
/* بنرِ هشدار/وضعیتِ ریسک در کارتِ نتیجه */
.riskwarn{margin:10px 0 4px;padding:9px 12px;border-radius:12px;font-size:12.5px;line-height:1.9;
  border:1px solid #7f1d1d;background:#2a0a0a;color:#fca5a5;direction:rtl}
.riskwarn.caution{border-color:#a16207;background:#2a1f05;color:var(--warn)}
.riskwarn.quiet{border-color:var(--line);background:var(--panel2);color:var(--muted)}
.riskwarn ul{margin:4px 0 0;padding-inline-start:18px}
/* سلول‌های سایزِ پوزیشن در کارتِ پلن */
.pcell.size{background:rgba(34,211,165,.10);border-color:rgba(34,211,165,.35)}
.pcell.size .v{color:var(--accent2)}
.sizenote{margin-top:8px;font-size:11.5px;color:var(--muted);line-height:1.85}
.card{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:20px;
  box-shadow:0 20px 50px rgba(0,0,0,.35)}
.searchrow{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.inp{flex:1;min-width:200px;background:var(--panel2);border:1px solid var(--line);border-radius:12px;
  color:var(--txt);font-size:16px;padding:14px 16px;outline:none;transition:.15s}
.inp:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(77,163,255,.18)}
.styles{display:flex;gap:6px;background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:4px}
.styles button{background:transparent;border:0;color:var(--muted);padding:10px 14px;border-radius:9px;
  cursor:pointer;font-size:14px;font-weight:600;transition:.15s}
.styles button.active{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#04121f}
.go{background:linear-gradient(135deg,var(--accent),var(--accent2));border:0;color:#04121f;font-weight:800;
  font-size:16px;padding:14px 26px;border-radius:12px;cursor:pointer;transition:.15s}
.go:hover{filter:brightness(1.08)}
.go:disabled{opacity:.55;cursor:not-allowed}
/* دکمه‌ی خاصِ سیلوربولت — رنگِ متمایزِ بنفش/طلایی */
.sb-btn{background:linear-gradient(135deg,#a855f7,#f59e0b);border:0;color:#0b0f17;font-weight:800;
  font-size:15px;padding:14px 20px;border-radius:12px;cursor:pointer;transition:.15s;
  box-shadow:0 0 0 1px rgba(168,85,247,.4),0 4px 18px rgba(168,85,247,.25)}
.sb-btn:hover{filter:brightness(1.08)}
.sb-btn.active{outline:2px solid #f59e0b;outline-offset:2px}
/* کارتِ پنجره‌ی سیلوربولت */
.sbwin{margin-top:16px;background:linear-gradient(135deg,rgba(168,85,247,.10),rgba(245,158,11,.08));
  border:1px solid rgba(168,85,247,.4);border-radius:14px;padding:16px}
.sbwin h3{margin:0 0 10px;font-size:15px;color:#e8eefc}
.sbwin .sb-state{font-size:15px;font-weight:800;margin-bottom:8px}
.sbwin .sb-open{color:#22d3a5}
.sbwin .sb-shut{color:#f59e0b}
.sbwin .sb-timer{font-variant-numeric:tabular-nums;font-size:22px;font-weight:900;color:#f59e0b}
.sbwin .sb-steps{margin:12px 0 0;padding:0;list-style:none;font-size:13px;line-height:1.9;color:#c8d2ea}
.sbwin .sb-steps li{padding-right:20px;position:relative}
.sbwin .sb-steps li::before{content:"◆";position:absolute;right:0;color:#a855f7;font-size:11px;top:3px}
/* انتخابِ سریعِ نماد: در نمای اصلیِ صفحه **هیچ کلیدی** دیده نمی‌شود؛ این پنل فقط
   وقتی نشانگر یا فوکوس داخلِ کادرِ نماد می‌رود باز می‌شود (مثلِ یک کشویی زیرِ کادر). */
.chips{position:absolute;top:calc(100% + 6px);inset-inline:0;z-index:60;display:none;
  flex-direction:column;gap:9px;background:var(--panel);border:1px solid var(--line);
  border-radius:14px;padding:12px;box-shadow:0 18px 40px rgba(0,0,0,.55);
  max-height:min(430px,64vh);overflow:auto}
.chips.open{display:flex}
.chipgroup{display:flex;gap:7px;flex-wrap:wrap;align-items:center}
.chiplbl{color:var(--accent);font-size:11px;font-weight:700;background:var(--panel2);
  border:1px solid var(--line);border-radius:8px;padding:4px 9px;white-space:nowrap}
.chiphint{color:var(--muted);font-size:11px;opacity:.85;margin-top:-2px}
.symwrap{position:relative;flex:1;min-width:200px;display:flex}
/* پنلِ تنظیماتِ بک‌تست */
.btpanel{margin-top:14px;border-top:1px dashed var(--line);padding-top:14px;display:flex;
  flex-direction:column;gap:10px}
.btrow{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.btlbl{color:var(--muted);font-size:13px;font-weight:600;white-space:nowrap}
.btinp{background:var(--panel2);border:1px solid var(--line);border-radius:10px;color:var(--txt);
  padding:9px 12px;font-size:14px;font-family:inherit;min-width:150px;direction:ltr;text-align:right}
.btinp:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(77,163,255,.18);outline:none}
.btinp.wide{min-width:260px;flex:1}
.btinp.narrow{min-width:90px;width:90px}
.bthint{color:var(--muted);font-size:11px;opacity:.8}
.sideseg{display:flex;gap:5px;background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:4px}
.sideseg button{background:transparent;border:0;color:var(--muted);padding:8px 14px;border-radius:8px;
  cursor:pointer;font-size:13px;font-weight:600;font-family:inherit;transition:.15s}
.sideseg button.active{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#04121f}
/* راهنمای تقدم‌وتأخر: بعد از انتخابِ نماد، سبک و دکمه‌ی تحلیل چشمک بزنند */
.styles.awaiting{box-shadow:0 0 0 2px rgba(77,163,255,.35);border-radius:12px}
@keyframes gopulse{0%,100%{box-shadow:0 0 0 0 rgba(77,163,255,.0)}50%{box-shadow:0 0 0 4px rgba(77,163,255,.28)}}
.go.pulse{animation:gopulse 1.6s ease-in-out infinite}
.stephint{color:var(--muted);font-size:12px;margin-top:10px;line-height:1.7;
  border-inline-start:3px solid var(--accent);padding-inline-start:10px;opacity:.9}
.btsug{background:var(--panel2);border:1px solid var(--accent);color:var(--accent);
  padding:7px 12px;border-radius:9px;cursor:pointer;font-size:12px;font-weight:600;
  font-family:inherit;transition:.15s;white-space:nowrap}
.btsug:hover{background:var(--accent);color:#04121f}
.btsug:disabled{opacity:.5;cursor:default}
.btsughint{color:var(--muted);font-size:12px;line-height:1.7;margin:2px 0 4px;
  padding-inline-start:2px}
.btsughint.ok{color:var(--txt)}
.btsughint b{color:var(--accent)}
.sugpick{color:var(--accent);cursor:pointer;text-decoration:underline;font-weight:700}
.chip{background:var(--panel2);border:1px solid var(--line);color:var(--muted);font-size:12px;
  padding:6px 11px;border-radius:20px;cursor:pointer;transition:.15s}
.chip:hover{border-color:var(--accent);color:var(--txt)}
#result{margin-top:22px}
.hidden{display:none}
.status{color:var(--muted);text-align:center;padding:26px 0;font-size:15px}
/* نشانگرِ «در حالِ کار» در متنِ وضعیت: حلقه‌ی گرادیانی با دُمِ محو (نه کمانِ بریده‌ی
   border-top) و چرخشِ نرم — همان زبانِ بصریِ دکمه‌ی بروزرسانی. */
.spin{display:inline-block;width:15px;height:15px;border-radius:50%;vertical-align:-3px;
  margin-inline-start:8px;
  background-image:conic-gradient(from 0turn,rgba(77,163,255,0),rgba(77,163,255,.3) .42turn,
    var(--accent) .92turn,rgba(77,163,255,.9) 1turn),
    linear-gradient(rgba(77,163,255,.16),rgba(77,163,255,.16));
  -webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 2px),#000 calc(100% - 2px));
  mask:radial-gradient(farthest-side,transparent calc(100% - 2px),#000 calc(100% - 2px));
  animation:sp .95s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
.err{color:var(--bad);text-align:center;padding:20px;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.3);border-radius:12px}
.warn{color:#eab308;padding:10px 14px;background:rgba(234,179,8,.08);border:1px solid rgba(234,179,8,.35);border-radius:10px;font-size:13px;line-height:1.7}
.btbreak{display:flex;flex-wrap:wrap;gap:16px;margin-top:12px}
.btbcol{flex:1;min-width:220px}
.btbtitle{color:var(--muted);font-size:12px;font-weight:600;margin-bottom:4px}
.bttable.small{margin-top:0;font-size:11.5px}
/* result head */
.rhead{display:flex;flex-wrap:wrap;align-items:center;gap:14px;margin-bottom:16px}
.sym{font-size:26px;font-weight:800}
.dir{padding:5px 12px;border-radius:9px;font-weight:700;font-size:14px}
.dir.up{background:rgba(34,197,94,.15);color:var(--good);border:1px solid rgba(34,197,94,.35)}
.dir.down{background:rgba(239,68,68,.15);color:var(--bad);border:1px solid rgba(239,68,68,.35)}
.dir.flat{background:rgba(100,116,139,.15);color:var(--muted);border:1px solid rgba(100,116,139,.35)}
.price{color:var(--muted);font-size:15px}
.spacer{flex:1}
.grade{font-size:30px;font-weight:900;padding:8px 18px;border-radius:14px;color:#04121f;min-width:64px;text-align:center}
.metaline{color:var(--muted);font-size:13px;margin:-6px 0 14px;display:flex;flex-wrap:wrap;gap:14px}
.metaline b{color:var(--txt)}
/* score bar */
.scorebar{height:12px;background:var(--panel2);border-radius:10px;overflow:hidden;margin:6px 0 4px;border:1px solid var(--line)}
.scorefill{height:100%;border-radius:10px;transition:width .6s cubic-bezier(.2,.8,.2,1)}
.scoretxt{font-size:13px;color:var(--muted);margin-bottom:16px}
/* table */
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:11px 10px;text-align:right;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;background:var(--panel2)}
th:first-child,td:first-child{text-align:center;width:44px}
td.st{font-size:18px;font-weight:800}
td.pts{font-variant-numeric:tabular-nums;color:var(--muted);white-space:nowrap;text-align:center;width:74px}
.det{color:var(--muted);font-size:12.5px}
tr.on td{background:rgba(34,197,94,.05)}
/* plan */
.plan{margin-top:18px;background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:16px}
.plan h3{margin:0 0 12px;font-size:15px}
.pgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.pcell{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:11px 12px}
.bttable{width:100%;border-collapse:collapse;margin-top:14px;font-size:12.5px}
.bttable th,.bttable td{border:1px solid var(--line);padding:6px 8px;text-align:center}
.bttable th{background:var(--panel);color:var(--muted);font-weight:600}
.pcell .k{color:var(--muted);font-size:11px;margin-bottom:4px}
.pcell .v{font-size:17px;font-weight:800;font-variant-numeric:tabular-nums}
.pcell.rr .v{color:var(--accent2)}
.stamp{margin:0 0 12px;padding:10px 14px;border-radius:10px;font-size:14px;font-weight:700}
.stamp .stamp-why{font-size:11px;font-weight:400;color:var(--muted);margin-top:6px;line-height:1.6}
.stamp-ok{background:rgba(34,211,165,.12);border:1px solid rgba(34,211,165,.4);color:var(--grade-ap)}
.stamp-no{background:rgba(100,116,139,.12);border:1px solid rgba(100,116,139,.35);color:var(--muted)}
.verdict{margin-top:16px;background:rgba(77,163,255,.08);border-right:3px solid var(--accent);
  padding:12px 14px;border-radius:8px;font-size:14px;line-height:1.7}
/* منوی کرکره‌ایِ ستاپ‌های اسکلپ (آکاردئون) */
.acc{margin-top:16px;display:flex;flex-direction:column;gap:8px}
.acc-item{background:var(--panel2);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.acc-head{width:100%;display:flex;align-items:center;gap:10px;padding:12px 14px;background:transparent;
  border:none;color:var(--txt);font-family:inherit;font-size:14px;font-weight:700;cursor:pointer;text-align:right}
.acc-head:hover{background:rgba(77,163,255,.06)}
.acc-head .arr{margin-right:auto;color:var(--muted);transition:.2s;font-size:12px}
.acc-item.open .acc-head .arr{transform:rotate(180deg)}
.acc-body{display:none;padding:0 14px 14px;font-size:13px;line-height:1.9;color:#c8d2ea;border-top:1px dashed var(--line)}
.acc-item.open .acc-body{display:block}
.acc-path{margin:10px 0;padding:10px 12px;background:rgba(168,85,247,.08);
  border-right:3px solid #a855f7;border-radius:8px;font-size:12.5px;line-height:2}
.acc-path b{color:#d8b4fe}
.acc-stats{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;font-size:12px;color:var(--muted)}
.acc-stats b{color:var(--accent2)}
/* چراغِ وضعیتِ زنده‌ی هر ستاپ */
/* دکمه و پنلِ ستاپ‌ها — همیشه بالای صفحه، مستقل از کارتِ نتیجه */
.setups-btn{background:linear-gradient(135deg,#059669,#65a30d);border:0;color:#04120b;font-weight:800;
  font-size:15px;padding:14px 18px;border-radius:12px;cursor:pointer;transition:.15s}
.setups-btn:hover{filter:brightness(1.08)}
.setups-btn.active{outline:2px solid #34d399;outline-offset:2px}
/* دکمه‌ی فاندمنتال — رنگِ متمایزِ آبیِ نفتی/فیروزه‌ای */
.fund-btn{background:linear-gradient(135deg,#0ea5e9,#6366f1);border:0;color:#04121f;font-weight:800;
  font-size:15px;padding:14px 20px;border-radius:12px;cursor:pointer;transition:.15s;
  box-shadow:0 0 0 1px rgba(14,165,233,.4),0 4px 18px rgba(99,102,241,.22)}
.fund-btn:hover{filter:brightness(1.08)}
/* دکمه‌های کم‌رنگِ نوارِ ابزار: ↻ بروزرسانی و 📁 آرشیو اقتصادی */
.rf-btn,.ab-btn{background:var(--panel2);border:1px solid var(--line);color:var(--txt);
  font-weight:700;font-size:14px;padding:12px 16px;border-radius:11px;cursor:pointer;
  font-family:inherit;transition:.15s;white-space:nowrap}
.rf-btn:hover,.ab-btn:hover{border-color:var(--accent);color:var(--accent)}
/* حالتِ «آمادهٔ نصبِ مستقیم»: دو تپشِ نرم روی حاشیه — همان زبانِ آرامِ بقیهٔ حالت‌ها */
@keyframes instpulse{0%,100%{box-shadow:0 0 0 0 rgba(77,163,255,0)}45%{box-shadow:0 0 0 6px rgba(77,163,255,.22)}}
.ab-btn.pulsing{border-color:var(--accent);color:var(--accent);animation:instpulse 1.6s ease-in-out 3}
/* پنلِ نصب (داخلِ مودالِ عمومی) */
.inst-h{font-size:13px;font-weight:800;color:var(--accent);margin:16px 0 8px}
.inst-h:first-child{margin-top:0}
.inst-url{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px 14px;
  font-size:14px;font-weight:700;color:var(--txt);direction:ltr;text-align:left;
  user-select:all;overflow-x:auto;white-space:nowrap}
.inst-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:10px}
.inst-cp{background:linear-gradient(135deg,var(--accent),var(--accent2));border:0;color:#04121f;
  font-weight:800;font-size:13px;padding:9px 16px;border-radius:10px;cursor:pointer;font-family:inherit}
.inst-note{color:var(--muted);font-size:12px;line-height:1.7;flex:1;min-width:200px}
.inst-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media(max-width:560px){.inst-grid{grid-template-columns:1fr}}
.inst-card{background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.inst-card .t{font-weight:800;font-size:13px;margin-bottom:8px}
.inst-card ol{margin:0;padding-inline-start:18px;color:var(--muted);font-size:12.5px;line-height:2}
.inst-status{margin-top:14px;font-size:12.5px;color:var(--good);font-weight:700}
.inst-warn{margin-top:10px;background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.3);
  border-radius:10px;padding:10px 12px;font-size:12px;line-height:1.8;color:#f6d99a}
.rf-btn:disabled,.ab-btn:disabled{opacity:.5;cursor:default}
/* ── دکمه‌ی بروزرسانی: حالتِ «در حالِ انجام» به‌جای گلیفِ چرخانِ متنی ──
   همه‌ی سه حالت (گلیفِ آماده / نشانگرِ چرخان / تیکِ تأیید) در یک اسلاتِ ثابتِ ۱۸px
   روی هم می‌نشینند تا نه اندازه‌ی دکمه بتپد و نه متن جابه‌جا شود. */
/* ── دکمهی بروزرسانی: حالتِ «در حالِ انجام» ──
   همهی سه حالت (گلیفِ آماده / نشانگرِ چرخان / تیکِ تأیید) در یک اسلاتِ ثابتِ ۱۶px روی
   هم مینشینند تا نه اندازهی دکمه بتپد و نه متن جابهجا شود.
   اصلِ طراحی: حرکتِ کم و دقیق. حلقه با سرعتِ *ثابت* میچرخد و فقط دُمش نفس میکشد
   (چرخش با easing در هر دور تند-و-کند میشود و حسِ آماتوری میدهد).
   حالتِ کار با «وضعیتِ» خودِ دکمه دیده میشود (پسزمینه، حاشیه، هاله)، نه با افکت. */
.rf-btn{position:relative;overflow:hidden;display:inline-flex;align-items:center;gap:8px;
  transition:border-color .22s ease,background .22s ease,color .22s ease,box-shadow .3s ease}
.rf-btn.loading{cursor:progress}
.rf-slot{position:relative;width:16px;height:16px;flex:0 0 16px;display:inline-block}
.rf-ico,.rf-spin,.rf-check{position:absolute;inset:0;display:flex;align-items:center;
  justify-content:center;transition:opacity .2s ease,transform .2s ease}
.rf-ico svg,.rf-spin svg,.rf-check svg{width:16px;height:16px;display:block;overflow:visible}
.rf-ico svg path{fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}
.rf-spin,.rf-check{opacity:0;transform:scale(.72)}
.rf-spin svg circle{fill:none;stroke-width:2;stroke-linecap:round}
.rf-track{stroke:var(--accent);stroke-opacity:.16}
.rf-arc{stroke:var(--accent);transform-origin:50% 50%}
.rf-check svg path{fill:none;stroke:var(--good);stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round}
.rf-live{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
  clip:rect(0 0 0 0);white-space:nowrap;border:0}
/* هنگامِ کار: گلیف کنار می‌رود، حلقه‌ی بدونِ‌سر ظاهر می‌شود و نوارِ نازکِ پایین می‌خزد */
/* هنگامِ کار: گلیف کنار میرود و حلقه ظاهر میشود — چرخشِ خطی، دُمِ نفسکش.
   دکمه در این حالت disabled است؛ عمداً محو نمیشود تا وضعیتِ کار *روشن* دیده شود. */
.rf-btn.loading:disabled,.rf-btn.ok:disabled{opacity:1}
.rf-btn.loading{color:var(--txt);border-color:var(--accent);
  background:linear-gradient(180deg,rgba(77,163,255,.14),rgba(77,163,255,.05));
  box-shadow:0 0 0 1px rgba(77,163,255,.18),0 6px 20px rgba(77,163,255,.14)}
.rf-btn.loading .rf-ico{opacity:0;transform:scale(.72)}
.rf-btn.loading .rf-spin{opacity:1;transform:none}
.rf-btn.loading .rf-spin svg{animation:rfrot .9s linear infinite}
.rf-btn.loading .rf-arc{stroke-dasharray:8 49;animation:rfdash 1.5s ease-in-out infinite}
.rf-btn.loading .rf-lbl{opacity:.9}
/* تأییدِ پایان: تیک «کشیده» می‌شود (بدونِ پرشِ رنگ) */
/* تأییدِ پایان: تیک «کشیده» میشود و دکمه بهآرامی به رنگِ سالم میگراید */
.rf-btn.ok{border-color:var(--good);color:var(--good);
  background:linear-gradient(180deg,rgba(52,211,153,.16),rgba(52,211,153,.05));
  box-shadow:0 0 0 1px rgba(52,211,153,.2),0 6px 20px rgba(52,211,153,.16)}
.rf-btn.ok .rf-ico{opacity:0;transform:scale(.72)}
.rf-btn.ok .rf-spin{opacity:0;transform:scale(.72)}
.rf-btn.ok .rf-check{opacity:1;transform:none}
.rf-btn.ok .rf-check svg path{stroke-dasharray:24;stroke-dashoffset:24;animation:rfdraw .36s cubic-bezier(.2,.9,.3,1) .04s forwards}
@keyframes rfrot{to{transform:rotate(360deg)}}
@keyframes rfdash{0%{stroke-dasharray:8 49;stroke-dashoffset:8}
  50%{stroke-dasharray:30 27;stroke-dashoffset:-8}
  100%{stroke-dasharray:8 49;stroke-dashoffset:-49}}
@keyframes rfdraw{to{stroke-dashoffset:0}}
/* احترام به کاهشِ حرکت (دسترسی‌پذیری): فقط یک تپشِ نرم، بدونِ چرخش و نور */
@media (prefers-reduced-motion: reduce){
  .rf-btn.loading .rf-spin svg,.rf-btn.loading .rf-arc{animation:none}
  .rf-btn.loading .rf-arc{stroke-dasharray:30 27}
  .spin,.rf-btn.loading .rf-spin{animation:rfsoft 1.6s ease-in-out infinite}
}
@keyframes rfsoft{0%,100%{opacity:.45}50%{opacity:1}}
/* مودالِ عمومی (پنجره‌ی آرشیو و …) */
.modal-overlay{position:fixed;inset:0;background:rgba(2,6,14,.72);display:flex;
  align-items:center;justify-content:center;z-index:120;padding:20px}
.modal-box{background:var(--panel);border:1px solid var(--line);border-radius:16px;
  width:100%;max-width:660px;max-height:82vh;overflow:auto;box-shadow:0 30px 80px rgba(0,0,0,.55)}
.modal-head{display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:14px 18px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--panel)}
.modal-head h3{margin:0;font-size:16px}
.modal-close{background:transparent;border:1px solid var(--line);color:var(--muted);width:30px;height:30px;
  border-radius:8px;cursor:pointer;font-family:inherit;font-size:16px;line-height:1}
.modal-close:hover{border-color:var(--bad);color:var(--bad)}
.modal-content{padding:14px 18px;font-size:13.5px;line-height:1.9}
.arc-ev{background:var(--panel2);border:1px solid var(--line);border-radius:12px;
  padding:12px 14px;margin-bottom:10px}
.arc-t{font-weight:800;font-size:14.5px}
.arc-t .arc-en{color:var(--muted);font-size:12px;font-weight:600;margin-inline-start:6px}
.arc-m{color:var(--muted);font-size:12.5px;margin-top:4px}
.arc-d{margin-top:6px;color:var(--accent2);font-size:13px}
.arc-note{color:var(--muted);font-size:12px;border-top:1px dashed var(--line);
  padding-top:10px;margin-top:8px;line-height:1.9}
.arc-empty{color:var(--muted);text-align:center;padding:18px;font-size:13px}
.setups-panel{display:none;margin-top:12px;background:var(--panel);border:1px solid var(--line);
  border-radius:14px;padding:14px}
.setups-panel.open{display:block}
.sp-head{font-size:14px;font-weight:800;margin-bottom:10px}
.lamp{font-size:12px;font-weight:700;padding:4px 10px;border-radius:8px;white-space:nowrap}
.lamp.g{background:rgba(34,197,94,.15);color:var(--good);border:1px solid rgba(34,197,94,.35)}
.lamp.y{background:rgba(245,158,11,.13);color:var(--warn);border:1px solid rgba(245,158,11,.32)}
.lamp.r{background:rgba(239,68,68,.12);color:var(--bad);border:1px solid rgba(239,68,68,.3)}
.acc-why{margin-top:10px;padding:8px 12px;background:rgba(77,163,255,.07);border-right:3px solid var(--accent);
  border-radius:6px;font-size:12.5px;color:#dbe6ff}
.badge{display:inline-block;font-size:12px;padding:4px 10px;border-radius:8px;margin:2px 4px 2px 0}
.badge.kz{background:rgba(245,158,11,.12);color:var(--warn);border:1px solid rgba(245,158,11,.3)}
.badge.g-green{background:rgba(34,197,94,.12);color:var(--good);border:1px solid rgba(34,197,94,.3)}
.badge.g-amber{background:rgba(245,158,11,.12);color:var(--warn);border:1px solid rgba(245,158,11,.3)}
.badge.g-red{background:rgba(239,68,68,.12);color:var(--bad);border:1px solid rgba(239,68,68,.3)}
.upcoming{color:var(--muted);font-size:12px;margin-top:8px}
.jrnrow{margin-top:16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.jbtn{background:var(--accent2);color:#04241b;border:none;border-radius:10px;
  padding:10px 18px;font-size:14px;font-weight:700;cursor:pointer;font-family:inherit}
.jbtn:hover{filter:brightness(1.08)}
.jbtn:disabled{opacity:.5;cursor:default}
.jmsg{font-size:13px;color:var(--muted)}
.jmsg.good{color:var(--accent2)}
.jmsg.bad{color:#ff6b6b}
/* OTE panel */
.ote{margin-top:16px;border-radius:14px;padding:16px}
.ote.ote-in{background:rgba(34,197,94,.10);border:1px solid rgba(34,197,94,.4)}
.ote.ote-out{background:rgba(245,158,11,.10);border:1px solid rgba(245,158,11,.4)}
.ote-head{font-size:15px;font-weight:800;margin-bottom:6px}
.ote-body{font-size:14px;line-height:1.7;margin-bottom:10px}
.ote-nums{display:flex;gap:20px;flex-wrap:wrap;font-size:14px;margin-bottom:12px}
.ote-nums b{color:var(--txt);font-variant-numeric:tabular-nums}
.alarm-btn{background:var(--warn);color:#231600;border:none;border-radius:10px;
  padding:10px 18px;font-size:14px;font-weight:700;cursor:pointer;font-family:inherit}
.alarm-btn:hover{filter:brightness(1.08)}
.alarm-btn:disabled{opacity:.5;cursor:default}
/* alarms dock */
.alarms-dock{margin-top:22px;background:var(--panel);border:1px solid var(--line);
  border-radius:18px;padding:18px}
.alarms-dock h2{font-size:16px;margin:0 0 12px;display:flex;align-items:center;gap:8px}
.alarm-item{display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:var(--panel2);
  border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:8px;font-size:13px}
.alarm-item.trig{border-color:rgba(34,197,94,.5);background:rgba(34,197,94,.08)}
.alarm-item .asym{font-weight:800;font-size:15px}
.alarm-item .arng{color:var(--muted);font-variant-numeric:tabular-nums}
.alarm-item .astat{margin-right:auto}
.alarm-item .apx{color:var(--muted);font-variant-numeric:tabular-nums}
.pill{font-size:11px;padding:3px 9px;border-radius:20px;font-weight:700}
.pill.waiting{background:rgba(245,158,11,.15);color:var(--warn)}
.pill.hit{background:rgba(34,197,94,.18);color:var(--good)}
.adel{background:transparent;border:1px solid var(--line);color:var(--muted);
  border-radius:8px;padding:5px 10px;cursor:pointer;font-family:inherit;font-size:12px}
.adel:hover{border-color:var(--bad);color:var(--bad)}
.aempty{color:var(--muted);font-size:13px;text-align:center;padding:14px}
/* live chart + screenshots */
.livewrap{margin-top:22px;background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:18px}
.livewrap h2{font-size:16px;margin:0 0 12px;display:flex;align-items:center;gap:8px}
.tv-box{position:relative;border-radius:12px;overflow:hidden;border:1px solid var(--line);height:420px;background:var(--panel2)}
.tv-box iframe{width:100%;height:100%;border:0;display:block}
.uprow{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:14px}
.upbtn{background:var(--accent);color:#04121f;border:none;border-radius:10px;padding:11px 18px;
  font-size:14px;font-weight:700;cursor:pointer;font-family:inherit}
.upbtn:hover{filter:brightness(1.08)}
.upbtn:disabled{opacity:.5;cursor:default}
.upnote{flex:1;min-width:180px;background:var(--panel2);border:1px solid var(--line);border-radius:10px;
  color:var(--txt);font-size:14px;padding:11px 14px;outline:none}
.shotgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin-top:14px}
.shot{background:var(--panel2);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.shot img{width:100%;height:150px;object-fit:cover;cursor:pointer;display:block;background:#000}
.shot .meta{padding:8px 10px;font-size:12px;color:var(--muted)}
.shot .meta b{color:var(--txt)}
.shot .sdel{background:transparent;border:1px solid var(--line);color:var(--muted);border-radius:7px;
  padding:4px 9px;cursor:pointer;font-family:inherit;font-size:11px;margin-top:6px}
.shot .sdel:hover{border-color:var(--bad);color:var(--bad)}
.lightbox{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;align-items:center;justify-content:center;
  z-index:100;padding:24px;cursor:zoom-out}
.lightbox.on{display:flex}
.lightbox img{max-width:95%;max-height:95%;border-radius:10px;box-shadow:0 20px 60px rgba(0,0,0,.6)}
.foot{color:var(--muted);font-size:11px;text-align:center;margin-top:22px;line-height:1.8}
@media(max-width:560px){.pgrid{grid-template-columns:repeat(2,1fr)}.styles{width:100%}.styles button{flex:1}}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <div>
      <h1>pipfound</h1>
    </div>
    <div class="chiprow">
      <span id="dataChip" class="revchip" title="تازگیِ داده و باز/بسته بودنِ بازار — اگر آخرین کندلِ بسته کهنه باشد یا بازار بسته باشد، تحلیل «آماده‌سازی» است نه سیگنالِ ورود.">داده …</span>
      <span id="revChip" class="revchip" title="بازنگریِ کدِ در حالِ اجرا — SHA بارشده، زمانِ استارتِ پروسه، و اینکه کدِ سروشده با فایل‌های روی دیسک یکی است یا نه.">rev …</span>
    </div>
  </div>

  <div class="card">
    <div class="searchrow">
      <div class="symwrap">
        <input id="sym" class="inp" placeholder="نامِ نماد… مثل XAUUSD، EURUSD، WTI، SPX500، NVDA"
               title="نامِ نماد را این‌جا بنویس (طلا/نقره، جفت‌ارزهای مهم، کامودیتی، اندیکس، استاک و کریپتو). نشانگر را داخلِ همین کادر ببر (یا روی آن کلیک کن) تا فهرستِ نمادها زیرِ کادر باز شود و یکی را انتخاب کنی. با انتخاب/تایپِ نماد، سبک و دکمه‌ی تحلیل چشمک می‌زنند؛ هیچ‌چیز خودکار اجرا نمی‌شود."
               list="syms" autocomplete="off">
        <datalist id="syms"></datalist>
        <div class="chips" id="chips"></div>
      </div>
      <div class="styles" id="styles">
        <button data-k="scalp" title="سبکِ اسکالپ — تایم‌فریمِ پایین. فقط سبک را عوض می‌کند؛ تحلیل را خودکار اجرا نمی‌کند.">اسکالپ</button>
        <button data-k="day" class="active" title="سبکِ روزانه (پیش‌فرض). فقط سبک را عوض می‌کند؛ تحلیل را خودکار اجرا نمی‌کند.">روزانه</button>
        <button data-k="swing" title="سبکِ سوینگ — تایم‌فریمِ بالا. فقط سبک را عوض می‌کند؛ تحلیل را خودکار اجرا نمی‌کند.">سوینگ</button>
      </div>
      <button id="go" class="go" title="تحلیلِ زنده‌ی همین لحظه: امتیاز، تایم‌فریمِ ورود، پلنِ عددی و درجه را می‌دهد.">تحلیل کن</button>
      <button id="bt" class="go" style="background:#334155" title="بک‌تستِ walk-forward روی داده‌ی تاریخی؛ پنلِ تنظیماتِ بازه/تایم‌فریم/جهت را باز می‌کند.">بک‌تست</button>
      <button id="sbBtn" class="sb-btn" title="استراتژیِ سیلوربولتِ نیویورک روی تایمِ ۱ دقیقه — فقط در پنجره‌ی ۰۹:۰۰ تا ۱۱:۰۰ به‌وقتِ نیویورک معتبر است (اوجِ فعالیتِ روز). با کلیک، سبک روی این استراتژی می‌رود، تحلیلِ ۱m اجرا می‌شود و تایمرِ ساعتِ ۹ نمایش داده می‌شود.">🎯 سیلوربولت نیویورک</button>
      <button id="setupsBtn" class="setups-btn" title="سه ستاپِ پیشنهادیِ اسکلپ با وضعیتِ زنده: 🟢 تأییدِ قوی · 🟡 منتظرِ شرایط · 🔴 شرایط نیست. چراغ‌ها از آخرین تحلیل به‌روز می‌شوند؛ با کلیک روی هر ردیف مسیرِ ستاپ باز می‌شود.">📚 ستاپ‌ها</button>
      <button id="fundBtn" class="fund-btn" title="اخبارِ اقتصادیِ پرتأثیر (GDP، تورم، اشتغال، نرخِ بهره) یک روز پیش از اعلام — ساعتِ دقیقِ اعلام به‌وقتِ نیویورک و تهران، به‌همراهِ تحلیلِ اثرِ هر خبر روی جفت‌ارزهای مهم و طلا/نقره. با کلیک، صفحه‌ی جداگانه‌ی فاندمنتال در تبِ نو باز می‌شود.">📰 فاندمنتال</button>
      <button id="refreshBtn" class="rf-btn" title="همان نمادِ آخرین تحلیل را دوباره با دیتای زنده می‌گیرد — بدونِ رفرشِ کلِ صفحه. از همان بارگذاری فعال است: اگر در این صفحه تحلیلی باشد همان را با دیتای زنده بازتازه می‌کند، وگرنه آخرین تحلیلِ ثبت‌شده را می‌گیرد؛ اگر چیزی نباشد فقط پیام می‌دهد — پنجره‌ای باز نمی‌کند.">
        <span class="rf-slot" aria-hidden="true">
          <span class="rf-ico"><svg viewBox="0 0 24 24"><path d="M23 4v6h-6"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg></span>
          <span class="rf-spin"><svg viewBox="0 0 24 24"><circle class="rf-track" cx="12" cy="12" r="9"/><circle class="rf-arc" cx="12" cy="12" r="9"/></svg></span>
          <span class="rf-check"><svg viewBox="0 0 24 24"><path d="M5 12.8l4.3 4.3L19 7.4"/></svg></span>
        </span>
        <span class="rf-lbl">بروزرسانی</span>
        <span class="rf-live" role="status" aria-live="polite"></span>
      </button>
      <button id="archiveBtn" class="ab-btn" title="اخبارِ اقتصادیِ پرتأثیرِ ۶ ساعتِ گذشته — هر خبر با ارز، ساعتِ اعلام و جهتِ موردانتظارش روی جفت‌ارزها و طلا/نقره؛ در همین صفحه به‌شکلِ پنجره باز می‌شود.">📁 آرشیو اقتصادی</button>
      <button id="installBtn" class="ab-btn" title="همین اپ را به‌شکلِ آیکونِ مستقل روی گوشی/تبلت/کامپیوتر نصب کن — آدرسِ قابل‌اشتراک و راهنمای هر دستگاه.">📲 نصب روی دستگاه</button>
    </div>
    <div id="setupsPanel" class="setups-panel">
      <div class="sp-head">📚 سه ستاپِ پیشنهادی <span class="jmsg" id="spState">— اول یک تحلیل بگیر تا چراغ‌ها روشن شوند</span></div>
      <div id="spList"></div>
    </div>
    <div id="btPanel" class="btpanel">
      <div class="btrow">
        <span class="btlbl">بازه‌ی بک‌تست (تاریخِ روی چارت):</span>
        <input id="btFrom" class="btinp" type="text" placeholder="از — مثل 2026-06-01" autocomplete="off"
               title="تاریخِ شروعِ بازه‌ی بک‌تست (روی چارت). خالی = خودکار (کندل‌های اخیر). قالب: 2026-06-01">
        <input id="btTo" class="btinp" type="text" placeholder="تا — مثل 2026-08-13" autocomplete="off"
               title="تاریخِ پایانِ بازه‌ی بک‌تست (روی چارت). خالی = خودکار (کندل‌های اخیر). قالب: 2026-08-13">
        <button id="btSuggest" class="btsug" type="button"
                title="بر اساسِ عمقِ پیمایش و دیتای در دسترس، حداقلِ تاریخِ معتبر را در کادرها پیشنهاد می‌دهد. اول نماد و سبک را انتخاب کن.">بازه‌ی پیشنهادی ↧</button>
      </div>
      <div class="btsughint" id="btSugHint"></div>
      <div class="btrow">
        <span class="btlbl">تایم‌فریمِ دلخواه (فرکتالی):</span>
        <input id="btTfs" class="btinp wide" type="text" placeholder="مثلاً 4h,1h,15m,5m — خالی = طبقِ سبک"
               title="تایم‌فریم‌های دلخواهِ فرکتالی، با کاما جدا: «4h,1h,15m,5m». اولی = بایاسِ بالا، آخری = ورود. بر سبک اولویت دارد؛ خالی = طبقِ سبک.">
      </div>
      <div class="btrow">
        <span class="btlbl">جهتِ مجاز:</span>
        <div class="sideseg" id="btSide">
          <button data-s="both" class="active" title="هر دو جهتِ خرید و فروش را بک‌تست کن (پیش‌فرض).">هر دو</button>
          <button data-s="long" title="فقط سیگنال‌های خرید (long) را بک‌تست کن.">فقط خرید</button>
          <button data-s="short" title="فقط سیگنال‌های فروش (short) را بک‌تست کن.">فقط فروش</button>
        </div>
        <span class="btlbl" style="margin-inline-start:14px">عمقِ پیمایش:</span>
        <input id="btWalk" class="btinp narrow" type="number" min="100" max="8000" step="100" value="2000"
               title="عمقِ پیمایشِ walk-forward = تعدادِ کندلِ ورودی که ماشین روی آن قدم‌به‌قدم جلو می‌رود. برای نمونه‌ی آماریِ معتبر ≥ ۲۰۰۰ توصیه می‌شود.">
      </div>
    </div>
    <div class="riskpanel" id="riskPanel">
      <div class="risktitle">💰 مدیریتِ ریسک — سرمایه و درصدِ ریسکت را بده تا کنارِ هر پلن «سایزِ پوزیشن» و ریسکِ دلاری‌اش را بدهد، و سقفِ ضررِ روزانه/تمرکزِ معاملات را هم بپاید</div>
      <div class="riskrow">
        <span class="btlbl">سرمایه</span>
        <input id="rkBalance" class="rinp wide" type="number" min="0" step="100" autocomplete="off"
               title="سرمایه‌ی حساب (به ارزِ حساب، پیش‌فرض دلار). سایزِ پوزیشن از همین عدد و درصدِ ریسک حساب می‌شود.">
        <span class="btlbl">ریسکِ هر معامله (٪)</span>
        <input id="rkRisk" class="rinp" type="number" min="0" max="100" step="0.1" autocomplete="off"
               title="درصدی از سرمایه که در هر معامله ریسک می‌کنی (پیش‌فرض ۱٪). سایز = (سرمایه × این درصد) ÷ فاصله‌ی استاپ.">
        <span class="btlbl">سقفِ ضررِ روزانه (٪)</span>
        <input id="rkDaily" class="rinp" type="number" min="0" max="100" step="0.5" autocomplete="off"
               title="اگر ضررِ محقق‌شده‌ی امروز به این درصد برسد، اپ ورودِ جدید را مسدود می‌کند، درجه را سقف C می‌زند و مهرِ ورود صادر نمی‌کند.">
        <span class="btlbl">سقفِ ریسکِ باز (٪)</span>
        <input id="rkOpen" class="rinp" type="number" min="0" max="100" step="0.5" autocomplete="off"
               title="مجموعِ ریسکِ معاملاتِ بازِ تو (از ژورنال). عبور از این سقف = تمرکزِ زیاد؛ اپ ورودِ جدید را مسدود می‌کند.">
        <button id="rkSave" class="riskbtn" title="تنظیماتِ ریسک را ذخیره کن. در ~/pipfound/risk.json می‌ماند و بعد از ری‌استارتِ خودکارِ اپ هم حفظ می‌شود.">ذخیره</button>
        <span id="rkMsg" class="jmsg"></span>
      </div>
      <div class="riskstat" id="rkStat">در حالِ خواندنِ وضعیتِ ریسک…</div>
    </div>
  </div>

  <div id="result"></div>
  <div id="btresult"></div>

  <div class="alarms-dock" id="alarmsDock">
    <h2>🔔 آلارم‌های فعال <span class="jmsg" id="alarmsHint">(هر ۹۰ ثانیه بررسی می‌شوند)</span></h2>
    <div id="alarmsList"><div class="aempty">هنوز آلارمی نگذاشته‌ای.</div></div>
  </div>

  <div class="livewrap">
    <h2>📊 چارتِ زنده <span class="jmsg" id="tvSymLbl"></span></h2>
    <div class="tv-box" id="tvBox">
    <div class="aempty" style="padding:40px">یک نماد را تحلیل کن تا چارتِ زنده‌اش این‌جا بیاید.</div>
    </div>
  </div>

  <div class="livewrap">
    <h2>🖼️ اسکرین‌شاتِ چارت <span class="jmsg">(آپلود برای بایگانی و مرور)</span></h2>
    <div class="uprow">
      <input type="file" id="shotFile" accept="image/png,image/jpeg,image/webp,image/gif" style="display:none">
      <button class="upbtn" id="shotPick" title="یک تصویرِ چارت را از دستگاهت انتخاب کن (PNG/JPG/WebP/GIF) تا برای بایگانی و مرور آپلود شود.">📤 انتخابِ تصویر</button>
      <input class="upnote" id="shotNote" placeholder="یادداشت (اختیاری) — مثلاً «سوئیپِ لو + چاک روی ۱h»"
             title="یادداشتِ اختیاری روی این اسکرین‌شات؛ کنارِ تصویر ذخیره و نمایش داده می‌شود.">
      <span id="shotMsg" class="jmsg"></span>
    </div>
    <div class="shotgrid" id="shotGrid"></div>
  </div>

  <div class="lightbox" id="lightbox"><img id="lightboxImg" src="" alt=""></div>
</div>

<script>
// نمایشِ هر خطای JS روی خودِ صفحه — خطاها دیگر بی‌صدا گم نمی‌شوند
window.addEventListener("error", e=>{
  const r=document.getElementById("result");
  if(r && !r.innerHTML.trim()){
    r.innerHTML='<div class="err">خطای جاوااسکریپت: '+ (e.message||"نامشخص") +'</div>';
  }
});
const SUGGESTIONS = __SUGGESTIONS__;
const SYMBOL_GROUPS = __SYMBOL_GROUPS__;
let style = "day";

const $ = s => document.querySelector(s);
const symIn = $("#sym"), goBtn = $("#go"), res = $("#result");

// datalist + chips
const dl = $("#syms");
SUGGESTIONS.forEach(s=>{const o=document.createElement("option");o.value=s;dl.appendChild(o);});
const chips = $("#chips");
// انتخابِ سریعِ گروه‌بندی‌شده — جفت‌ارزهای مهم · کامودیتی · اندیکس · استاک.
// این‌ها در نمای اصلیِ صفحه دیده **نمی‌شوند**: پنل تا وقتی نشانگر/فوکوس داخلِ کادرِ
// نماد نیامده بسته است، پس صفحه تمیز می‌ماند و انتخاب همیشه در دسترس است.
const symWrap = symIn.closest(".symwrap") || symIn.parentElement;
SYMBOL_GROUPS.forEach(([label, syms])=>{
  const row=document.createElement("div"); row.className="chipgroup";
  const lb=document.createElement("span"); lb.className="chiplbl"; lb.textContent=label;
  row.appendChild(lb);
  syms.forEach(s=>{
    const c=document.createElement("button");c.type="button";c.className="chip";c.textContent=s;
    c.setAttribute("data-sym",s);   // تستِ بصریِ CI روی همین می‌چسبد (نباید بی‌صدا حذف شود)
    c.title="انتخابِ "+s+" — فقط کادرِ نماد را پُر می‌کند؛ اول سبک/بازه را انتخاب کن.";
    // فقط نماد را پُر کن؛ اجرا نکن. کاربر اول سبک و بازه را انتخاب می‌کند.
    c.onclick=()=>{ symIn.focus(); symIn.value=s; markReady(); closePick(); };
    row.appendChild(c);
  });
  chips.appendChild(row);
});
const hint=document.createElement("div");
 hint.className="chiphint"; hint.textContent="با تایپ هم می‌توانی نماد را بنویسی؛ این فهرست فقط انتخاب را سریع می‌کند.";
chips.appendChild(hint);

// باز/بسته شدنِ پنل: با ورودِ نشانگر یا فوکوس؛ بستن با خروجِ نشانگر، کلیکِ بیرون، Esc یا انتخاب
let pickTimer=null;
function openPick(){ clearTimeout(pickTimer); chips.classList.add("open"); }
function closePick(){ clearTimeout(pickTimer); chips.classList.remove("open"); }
function closePickSoon(){ clearTimeout(pickTimer); pickTimer=setTimeout(closePick, 200); }
symIn.addEventListener("focus", openPick);
symIn.addEventListener("click", openPick);
symWrap.addEventListener("mouseenter", openPick);
symWrap.addEventListener("mouseleave", closePickSoon);
symIn.addEventListener("keydown", (e)=>{ if(e.key==="Escape") closePick(); });
document.addEventListener("click", (e)=>{ if(!symWrap.contains(e.target)) closePick(); });

// وقتی نمادی انتخاب/تایپ شد، کاربر را به انتخابِ سبک/بازه هدایت کن (بدونِ اجرای خودکار)
function markReady(){
  const has = symIn.value.trim().length>0;
  $("#styles").classList.toggle("awaiting", has);
  goBtn.classList.toggle("pulse", has);
}
symIn.addEventListener("input", ()=>{ markReady();
  // وقتی کاربر دارد تایپ می‌کند، اتوکامپلیتِ خودِ مرورگر کار می‌کند و پنل بسته می‌شود؛
  // با خالی شدنِ کادر، پنل برمی‌گردد تا انتخابِ فهرستی همیشه یک قدم فاصله داشته باشد.
  if(symIn.value.trim()) closePick(); else openPick();
});

// style toggle — فقط سبک را عوض کن؛ تحلیل را خودکار اجرا نکن
$("#styles").addEventListener("click",e=>{
  const b=e.target.closest("button");if(!b)return;
  document.querySelectorAll("#styles button").forEach(x=>x.classList.remove("active"));
  $("#sbBtn").classList.remove("active");
  b.classList.add("active");style=b.dataset.k;
});

// دکمه‌ی خاصِ سیلوربولت نیویورک — سبک را روی sb_ny می‌گذارد و بلافاصله تحلیل می‌کند
$("#sbBtn").addEventListener("click",()=>{
  document.querySelectorAll("#styles button").forEach(x=>x.classList.remove("active"));
  $("#sbBtn").classList.add("active");
  style="sb_ny";
  if(symIn.value.trim()) run(); else symIn.focus();
});

// تایمرِ زنده‌ی پنجره‌ی سیلوربولت (شمارشِ معکوس تا ۰۹:۰۰ ET یا تا بسته‌شدن)
let _sbTimer=null;
function fmtDur(sec){
  sec=Math.max(0,sec|0);
  const h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=sec%60;
  const p=n=>String(n).padStart(2,"0");
  return (h>0? p(h)+":":"")+p(m)+":"+p(s);
}
function startSbTimer(win){
  if(_sbTimer){clearInterval(_sbTimer);_sbTimer=null;}
  if(!win) return;
  let toOpen=win.seconds_to_open|0, toClose=win.in_window?(win.seconds_to_close|0):0;
  const el=()=>document.getElementById("sbTimer");
  const stEl=()=>document.getElementById("sbState");
  const tick=()=>{
    const t=el(); if(!t){clearInterval(_sbTimer);_sbTimer=null;return;}
    if(win.in_window){
      toClose--; if(toClose<0)toClose=0;
      t.textContent=fmtDur(toClose);
      const s=stEl(); if(s){s.textContent="🟢 پنجره باز است — تا بسته‌شدن:";s.className="sb-state sb-open";}
    }else{
      toOpen--; if(toOpen<0)toOpen=0;
      t.textContent=fmtDur(toOpen);
      const s=stEl(); if(s){s.textContent="🟠 پنجره بسته است — تا بازشدنِ ۰۹:۰۰ ET:";s.className="sb-state sb-shut";}
    }
  };
  tick(); _sbTimer=setInterval(tick,1000);
}

goBtn.onclick=run;
symIn.addEventListener("keydown",e=>{if(e.key==="Enter")run();});

// دکمه‌ی بروزرسانی — همان تحلیلِ آخر را با دیتای تازه دوباره می‌گیرد (بدونِ رفرشِ صفحه).
// وضعیتِ کار با کلاسِ `.loading` روی خودِ دکمه نشان داده می‌شود (حلقه‌ی بدونِ‌سر +
// هالهٔ ملایم — بدونِ افکتِ تصویری) — متن و اندازه‌ی دکمه ثابت می‌ماند تا چیزی نپرد.
const refreshBtn=document.getElementById("refreshBtn");
if(refreshBtn){
  const rfLive=refreshBtn.querySelector(".rf-live");
  const rfIdleTitle=refreshBtn.getAttribute("title")||"";
  const rfSay=s=>{ if(rfLive) rfLive.textContent=s||""; };
  // دکمه از همان بارگذاری فعال می‌ماند: کلیکِ بی‌نماد باید پاسخِ روشن بدهد، نه سکوت.
  // (قبلاً دکمه disabled بود و کلیک هیچ واکنشی نداشت — به‌نظرِ «دکمهٔ خراب» می‌آمد.)
  // هیچ پنجره/فوکوسی را نمی‌قاپد: فقط پیام می‌دهد. (بازکردنِ فهرستِ نمادها روی کلیکِ
  // «بروزرسانی» خودِ تجربه را خراب می‌کرد — خواستهٔ کاربر: دکمه باید خودش کار کند.)
  const rfTell=()=>{
    if(res && !res.innerHTML.trim())
      res.innerHTML='<div class="status">چیزی برای بروزرسانی نیست: در این صفحه هنوز تحلیلی ثبت نشده و کادرِ نماد هم خالی است. یک نماد را در کادرِ بالا بنویس (یا از فهرست انتخاب کن) و بعد همین دکمه را بزن.</div>';
    rfSay("چیزی برای بروزرسانی نیست — اول یک نماد را انتخاب یا تحلیل کن.");
    refreshBtn.title="هنوز چیزی برای بروزرسانی نیست؛ اول یک نماد را تحلیل کن.";
  };
  // اگر این صفحه تحلیلی ندارد، از حافظه‌ی سرور استفاده کن: آخرین تحلیلِ ثبت‌شده (حتی
  // از نشستِ قبلی) — پس «بروزرسانی» روی اپِ تازه‌باز هم کاری برای انجام دارد.
  const rfRemembered=async ()=>{
    let a=window._lastSeen||null;
    if(!a){
      try{ const r=await fetch("/api/data_status",{cache:"no-store"});
           a=((await r.json())||{}).analyzed||null; }catch(e){ a=null; }
    }
    return (a&&a.symbol)?a:null;
  };
  const rfSetStyle=k=>{
    if(!k) return;
    style=k;
    const b=document.querySelector('#styles button[data-k="'+k+'"]');
    if(b){
      document.querySelectorAll("#styles button").forEach(x=>x.classList.remove("active"));
      const sb=document.getElementById("sbBtn"); if(sb) sb.classList.remove("active");
      b.classList.add("active");
    }
  };
  refreshBtn.onclick=async ()=>{
    if(refreshBtn.classList.contains("loading")) return;       // یک درخواست در هر لحظه
    let sym=(window._last&&window._last.symbol)||symIn.value.trim();
    if(!sym){
      const a=await rfRemembered();
      if(a){ sym=a.symbol; rfSetStyle(a.style||a.style_key); }
    }
    if(!sym){ rfTell(); return; }
    symIn.value=sym;
    refreshBtn.disabled=true;
    refreshBtn.classList.remove("ok");
    refreshBtn.classList.add("loading");
    refreshBtn.setAttribute("aria-busy","true");
    refreshBtn.title="در حالِ بروزرسانیِ «"+sym+"» با دیتای زنده…";
    rfSay("در حالِ بروزرسانی…");
    let ok=false;
    try{
      await run();
      ok=true;
      refreshBtn.classList.add("ok");
      refreshBtn.title="بروزرسانی شد — «"+sym+"» با دیتای تازه دوباره تحلیل شد.";
      rfSay("بروزرسانی شد");
      setTimeout(()=>refreshBtn.classList.remove("ok"), 1900);
    }catch(e){
      rfSay("بروزرسانی ناموفق بود");
    }finally{
      refreshBtn.classList.remove("loading");
      refreshBtn.disabled=false;
      refreshBtn.removeAttribute("aria-busy");
      if(!ok) refreshBtn.title=rfIdleTitle;
    }
  };
}

const btBtn = $("#bt"), btRes = $("#btresult");
btBtn.onclick = runBacktest;

// جهتِ مجاز (both/long/short)
let btSide = "both";
$("#btSide").addEventListener("click", e=>{
  const b=e.target.closest("button"); if(!b) return;
  document.querySelectorAll("#btSide button").forEach(x=>x.classList.remove("active"));
  b.classList.add("active"); btSide=b.dataset.s;
});

// دکمه‌ی «بازه‌ی پیشنهادی»: بر اساسِ عمقِ walk و دیتای در دسترس،
// حداقلِ تاریخِ معتبر را به کاربر پیشنهاد می‌دهد.
const btSug = $("#btSuggest"), btSugHint = $("#btSugHint");
btSug.onclick = async ()=>{
  const sym=symIn.value.trim();
  if(!sym){ symIn.focus(); btSugHint.textContent="اول یک نماد انتخاب کن."; return; }
  const tfs=$("#btTfs").value.trim();
  let walk=parseInt($("#btWalk").value,10); if(!walk||walk<100) walk=600;
  btSug.disabled=true; const old=btSug.textContent; btSug.textContent="در حالِ محاسبه…";
  try{
    const qs=new URLSearchParams({symbol:sym, style, walk:String(walk)});
    if(tfs) qs.set("tfs", tfs);
    const r=await fetch(`/api/suggest-range?${qs.toString()}`);
    const d=await r.json();
    if(d.error){ btSugHint.className="btsughint"; btSugHint.textContent="خطا: "+d.error; return; }
    // پیشنهاد را داخلِ کادرها بگذار + راهنمای قابلِ‌کلیک
    $("#btFrom").value=d.suggested_from;
    $("#btTo").value=d.suggested_to;
    btSugHint.className="btsughint ok";
    btSugHint.innerHTML=
      `برای عمقِ پیمایشِ <b>${d.walk}</b> کندلِ <b>${d.ltf}</b> (${d.timeframes.join(" ")})، `+
      `حداقلِ تاریخِ معتبر <b>${d.suggested_from}</b> است و تا <b>${d.suggested_to}</b> داده هست. `+
      `کهن‌ترین دیتای در دسترس: ${d.data_from}. `+
      `<span class="sugpick" id="pickFull">استفاده از کلِ دیتا (${d.data_from} → ${d.data_to})</span>`;
    const pf=document.getElementById("pickFull");
    if(pf) pf.onclick=()=>{ $("#btFrom").value=d.data_from; $("#btTo").value=d.data_to; };
  }catch(err){ btSugHint.className="btsughint"; btSugHint.textContent="ارتباط با سرور ناموفق بود: "+err; }
  finally{ btSug.disabled=false; btSug.textContent=old; }
};

async function runBacktest(){
  const sym=symIn.value.trim();
  if(!sym){symIn.focus();return;}
  // خواندنِ انتخاب‌های کاربر
  const from=$("#btFrom").value.trim();
  const to=$("#btTo").value.trim();
  const tfs=$("#btTfs").value.trim();
  let walk=parseInt($("#btWalk").value,10); if(!walk||walk<100) walk=600;
  btBtn.disabled=true;
  const scope = (from||to) ? `بازه‌ی ${from||"…"} تا ${to||"…"}` : "کندل‌های اخیر";
  const sideLbl = btSide==="long"?"فقط خرید":btSide==="short"?"فقط فروش":"هر دو جهت";
  btRes.innerHTML=`<div class="status">در حالِ بک‌تستِ walk-forward — ${scope} · ${sideLbl}${tfs?` · تایم‌فریم ${tfs}`:""}… <span class="spin"></span></div>`;
  try{
    const qs=new URLSearchParams({symbol:sym, style, walk:String(walk), side:btSide});
    if(from) qs.set("from", from);
    if(to)   qs.set("to", to);
    if(tfs)  qs.set("tfs", tfs);
    const r=await fetch(`/api/backtest?${qs.toString()}`);
    const d=await r.json();
    if(d.error){btRes.innerHTML=`<div class="err">خطا در بک‌تستِ «${sym}»: ${d.error}</div>`;return;}
    renderBacktest(d);
  }catch(err){
    btRes.innerHTML=`<div class="err">ارتباط با سرور ناموفق بود: ${err}</div>`;
  }finally{btBtn.disabled=false;}
}

function renderBacktest(d){
  const wr = d.winrate_pct;
  const wrColor = wr>=55?"var(--good)":wr>=45?"var(--half)":"var(--bad)";
  const expColor = d.expectancy_R>0?"var(--good)":"var(--bad)";
  let rows="";
  (d.trade_log||[]).slice(-15).reverse().forEach(t=>{
    const win = t.result==="win";
    rows+=`<tr>
      <td>${t.time}</td>
      <td>${t.dir}</td>
      <td>${t.entry_type==="market"?"بازار":"لیمیت OTE"}</td>
      <td>${t.entry}</td><td>${t.sl}</td><td>${t.tp}</td>
      <td style="color:${win?'var(--good)':'var(--bad)'}">${win?"برد":"باخت"}</td>
      <td style="color:${win?'var(--good)':'var(--bad)'}">${t.r>0?"+":""}${t.r}R</td>
    </tr>`;
  });
  const empty = d.trades===0
    ? `<div class="err" style="margin-top:8px">هیچ سیگنالِ واجدِ شرایطی در این بازه پیدا نشد — معیارها سخت‌گیرند (درجه‌ی خوب + RR≥۱:۲ + پرشدنِ ورود). این خودش یعنی اپ کورکورانه ورود نمی‌سازد.</div>`
    : "";
  // برچسبِ تنظیماتِ به‌کاررفته
  const sideMap={both:"هر دو جهت",long:"فقط خرید",short:"فقط فروش"};
  const sideTxt=sideMap[d.side_used]||"هر دو جهت";
  const rangeTxt=(d.range_from||d.range_to)
    ? `بازه: ${d.range_from||"ابتدای داده"} تا ${d.range_to||"انتهای داده"}`
    : "بازه: کندل‌های اخیر (خودکار)";
  // بنرِ کفایتِ نمونه (مورد ۲) — وقتی معامله کم است هشدار بده
  let sampleBanner="";
  if(d.sample && !d.sample.ok){
    const cls = d.sample.level==="empty" ? "err" : "warn";
    sampleBanner=`<div class="${cls}" style="margin:8px 0">⚠️ ${d.sample.msg}</div>`;
  } else if(d.sample && d.sample.ok){
    sampleBanner=`<div style="color:var(--good);font-size:12px;margin:6px 0">✔️ ${d.sample.msg}</div>`;
  }
  // هشدارِ سبکِ کم‌سیگنال برای این نماد (مورد ۴)
  let styleWarn="";
  if(d.style_advice){
    styleWarn=`<div class="warn" style="margin:8px 0">💡 ${d.style_advice}</div>`;
  }
  // تفکیکِ وین‌ریت بر اساسِ نوعِ ورود و جهت (مورد ۳)
  function segTable(obj, labelMap){
    if(!obj||!Object.keys(obj).length) return "";
    let r="";
    for(const k of Object.keys(obj)){
      const s=obj[k];
      const c=s.winrate_pct>=55?"var(--good)":s.winrate_pct>=45?"var(--half)":"var(--bad)";
      r+=`<tr><td>${labelMap[k]||k}</td><td>${s.trades}</td>
        <td style="color:${c}">${s.winrate_pct}٪</td>
        <td>${s.total_R>0?"+":""}${s.total_R}R</td></tr>`;
    }
    return r;
  }
  const entLbl={market:"ورودِ بازار",limit_ote:"لیمیت OTE"};
  const dirLbl={"صعودی":"خرید (صعودی)","نزولی":"فروش (نزولی)"};
  const entRows=segTable(d.by_entry_type, entLbl);
  const dirRows=segTable(d.by_direction, dirLbl);
  const breakdown = d.trades>0 ? `
    <div class="btbreak">
      <div class="btbcol">
        <div class="btbtitle">تفکیک بر اساسِ نوعِ ورود</div>
        <table class="bttable small"><thead><tr><th>نوع</th><th>تعداد</th><th>وین‌ریت</th><th>مجموع R</th></tr></thead>
        <tbody>${entRows}</tbody></table>
      </div>
      <div class="btbcol">
        <div class="btbtitle">تفکیک بر اساسِ جهت</div>
        <table class="bttable small"><thead><tr><th>جهت</th><th>تعداد</th><th>وین‌ریت</th><th>مجموع R</th></tr></thead>
        <tbody>${dirRows}</tbody></table>
      </div>
    </div>` : "";
  btRes.innerHTML=`
  <div class="plan" style="margin-top:14px">
    <h3>🔬 نتیجه‌ی بک‌تست — ${d.symbol} · سبک ${d.style} · ${(d.timeframes||[]).join(" ")}</h3>
    <p style="color:var(--muted);font-size:13px;margin:4px 0 4px">
      این وین‌ریت از همان منطقِ ورودی‌ای می‌آید که اپ الان زنده پیشنهاد می‌دهد
      (walk-forward، بدونِ نگاه به آینده). سیگنال‌های هم‌پوشان حذف شده‌اند.</p>
    <p style="color:var(--muted);font-size:12px;margin:0 0 8px">🎯 ${sideTxt} · 📅 ${rangeTxt}</p>
    ${sampleBanner}
    ${styleWarn}
    <div class="pgrid">
      <div class="pcell"><span>تعدادِ معاملات</span><b>${d.trades}</b></div>
      <div class="pcell"><span>برد / باخت</span><b>${d.wins} / ${d.losses}</b></div>
      <div class="pcell"><span>وین‌ریت</span><b style="color:${wrColor}">${wr}٪</b></div>
      <div class="pcell"><span>مجموعِ R</span><b>${d.total_R>0?"+":""}${d.total_R}</b></div>
      <div class="pcell"><span>میانگینِ R</span><b>${d.avg_R_per_trade}</b></div>
      <div class="pcell"><span>اکسپکتنسی</span><b style="color:${expColor}">${d.expectancy_R}R</b></div>
    </div>
    ${breakdown}
    ${empty}
    ${d.trades>0?`<table class="bttable"><thead><tr>
      <th>زمانِ سیگنال</th><th>جهت</th><th>نوعِ ورود</th><th>ورود</th><th>استاپ</th><th>هدف</th><th>نتیجه</th><th>R</th>
    </tr></thead><tbody>${rows}</tbody></table>`:""}
  </div>`;
}

const dirClass = d => d==="صعودی"?"up":d==="نزولی"?"down":"flat";
const gradeColor = g => ({"A+":"var(--grade-ap)","A":"var(--grade-a)","B":"var(--grade-b)","C":"var(--grade-c)"}[g]||"var(--grade-no)");
const stColor = s => s==="✓"?"var(--good)":s==="◐"?"var(--half)":s==="✗"?"var(--bad)":"var(--muted)";

async function run(){
  const sym=symIn.value.trim();
  if(!sym){symIn.focus();return;}
  goBtn.disabled=true;
  res.innerHTML='<div class="status">در حالِ تحلیلِ دیتای زنده… <span class="spin"></span></div>';
  try{
    const r=await fetch(`/api/analyze?symbol=${encodeURIComponent(sym)}&style=${style}`);
    const d=await r.json();
    if(d.error){res.innerHTML=`<div class="err">خطا در تحلیلِ «${sym}»: ${d.error}</div>`;return;}
    render(d);
    showLiveChart(d.symbol);
  }catch(err){
    res.innerHTML=`<div class="err">ارتباط با سرور ناموفق بود: ${err}</div>`;
  }finally{goBtn.disabled=false;}
}

function render(d){
  const pct = d.max_score ? Math.round(d.score/d.max_score*100) : 0;
  const rows = d.checklist.map(c=>{
    const on = (c.status==="✓"||c.status==="◐");
    return `<tr class="${on?'on':''}">
      <td class="st" style="color:${stColor(c.status)}">${c.status}</td>
      <td><div>${c.name}</div><div class="det">${c.detail||""}</div></td>
      <td class="pts">${c.got}/${c.weight}</td>
    </tr>`;
  }).join("");

  // بلوکِ تازگیِ داده + باز/بسته بودنِ بازار — پیش از پلن خوانده می‌شود تا پلنِ
  // بازارِ بسته اشتباه به‌شکلِ سیگنالِ ورود دیده نشود.
  let dataHtml="";
  const dd = d.data||{};
  if(dd.last_bar_utc){
    const st=dd.state;
    const cls = st==="open"?"data-ok" : st==="closed"?"data-closed" : "data-warn";
    const head = st==="open"?"🟢 داده تازه" : st==="closed"?"🔴 بازار بسته است" : "🟡 داده عقب‌تر از حدِ معمول";
    dataHtml=`<div class="datanote ${cls}">
      <b>${head}</b> — آخرین کندلِ بسته: <b>${dd.last_bar_utc} UTC</b> (${dd.tf}) · سنِ داده: <b>${dd.age_human}</b> · نیویورک: ${dd.et_now}
      ${st!=="open"?`<div class="datanote-why">${dd.reason||""} — پس این تحلیل «آماده‌سازی» است، نه سیگنالِ ورود؛ پلنِ زیر برای سشنِ بعدی است.</div>`:""}
    </div>`;
  }

  // بلوکِ ریسک: سقفِ ضررِ روزانه + هشدارِ تمرکز/هم‌بستگی — پیش از پلن خوانده
  // می‌شود تا پلنی که با سقفِ روزانه مسدود شده اشتباه به‌شکلِ سیگنالِ ورود دیده نشود.
  const rk = d.risk || null;
  let riskHtml="";
  if(rk){
    const warns = rk.warnings || [];
    const day = rk.daily || {};
    if(warns.length){
      riskHtml = `<div class="riskwarn${rk.blocked?"":" caution"}">
        <b>${rk.blocked?"⛔ محدودیتِ ریسک — ورودِ جدید مجاز نیست":"⚠ هشدارِ ریسک"}</b>
        <ul>${warns.map(w=>`<li>${w}</li>`).join("")}</ul>
      </div>`;
    } else if(day.closed_today || day.open_count){
      riskHtml = `<div class="riskwarn quiet">
        <b>💰 وضعیتِ ریسکِ امروز</b> — ضررِ محقق‌شده: <b>${day.realized_pct}٪</b>
        (${day.realized_r}R · ${day.closed_today} معامله) · باقی‌مانده تا سقف: <b>${day.remaining_pct}٪</b>
        · ریسکِ باز: <b>${day.open_risk_pct}٪</b> از سقفِ ${day.open_risk_limit_pct}٪ (${day.open_count} پوزیشن)
      </div>`;
    }
  }

  let planHtml="";
  if(d.plan){
    const p=d.plan;
    const closed = (p.executable_now===false);
    const et = p.entry_type==="market"
      ? (closed
          ? `<span class="badge g-red">ورودِ بازار — ولی الان قابلِ اجرا نیست (بازار بسته/داده کهنه)</span>`
          : `<span class="badge g-green">ورودِ بازار (الان)</span>`)
      : (closed
          ? `<span class="badge g-amber">لیمیت در OTE — منتظرِ پولبک</span><span class="badge g-red">الان قابلِ اجرا نیست (بازار بسته)</span>`
          : `<span class="badge g-amber">لیمیت در OTE — منتظرِ پولبک</span>`);
    // مهرِ تاییدِ ورودِ اختیاری (مدلِ عرضه/تقاضا: نمره>۷۰٪ + نفوذِ ۳۰٪ + تاییدِ چرخشِ LTF)
    const es = d.entry_stamp || {};
    let stampHtml = "";
    if(es.stamped){
      stampHtml = `<div class="stamp stamp-ok" title="همه‌ی شرایطِ مدلِ عرضه/تقاضا برقرار است — مهرِ تاییدِ ورودِ اختیاری.">
        ✅ مهرِ تاییدِ ورود (نمره ${es.score_pct}٪ · نفوذِ زون ${es.penetration_pct}٪)
        <div class="stamp-why">${(es.reasons||[]).join(" · ")}</div></div>`;
    } else {
      stampHtml = `<div class="stamp stamp-no" title="یک یا چند شرطِ مدلِ عرضه/تقاضا برقرار نیست — ورود توصیه نمی‌شود.">
        ⛔ بدونِ مهرِ تایید — شرایطِ ورود کامل نیست
        <div class="stamp-why">${(es.reasons||[]).join(" · ")}</div></div>`;
    }
    // سایزِ پوزیشن برای همین پلن — از سرمایه/درصدِ ریسکِ پنلِ بالای صفحه
    const sz = (d.risk && d.risk.size) || {};
    let sizeHtml = "";
    if(sz.ok){
      const ccy = sz.account_ccy || "USD";
      const szNotes = (sz.notes||[]).length
        ? `<div class="sizenote">ℹ ${(sz.notes||[]).join(" · ")}</div>` : "";
      sizeHtml = `
      <div class="pgrid" style="margin-top:10px">
        <div class="pcell size"><div class="k">سایزِ پوزیشن${sz.approx?" (تقریبی — تنظیم‌پذیر)":""}</div><div class="v">${sz.size} ${sz.unit_fa}</div></div>
        <div class="pcell"><div class="k">ریسکِ این معامله</div><div class="v">${sz.actual_risk_amount} ${ccy}</div></div>
        <div class="pcell"><div class="k">سود در هدف (۱:${p.rr})</div><div class="v">${sz.reward_amount!=null?sz.reward_amount:"—"} ${ccy}</div></div>
        <div class="pcell"><div class="k">ارزشِ هر پوینت / فاصله‌ی استاپ</div><div class="v">${sz.value_per_point} ${ccy} · ${sz.stop_pips}p</div></div>
      </div>${szNotes}`;
    } else if(sz.reason){
      sizeHtml = `<div class="sizenote">💰 سایزِ پوزیشن محاسبه نشد: ${sz.reason}</div>`;
    }
    planHtml=`<div class="plan">
      <h3>📌 پلنِ پیشنهادی — تایم‌فریمِ ورود: <b>${d.entry_tf}</b> · سبک: ${d.style} &nbsp; ${et}</h3>
      ${stampHtml}
      <div class="pgrid">
        <div class="pcell"><div class="k">جهت</div><div class="v">${p.direction}</div></div>
        <div class="pcell"><div class="k">ورود</div><div class="v">${fmt(p.entry)}</div></div>
        <div class="pcell"><div class="k">حدِ ضرر</div><div class="v">${fmt(p.sl)}</div></div>
        <div class="pcell rr"><div class="k">ریسک به ریوارد</div><div class="v">۱:${p.rr}</div></div>
      </div>
      <div class="pgrid" style="margin-top:10px">
        <div class="pcell"><div class="k">هدف (حدِ سود · ۲ تا ۳R)</div><div class="v">${fmt(p.tp)}</div></div>
        ${p.liq_target && p.rr_to_liq && p.rr_to_liq>p.rr ? `<div class="pcell"><div class="k">کششِ رانر (لیکوئیدیتیِ بعدی)</div><div class="v">${fmt(p.liq_target)} <span style="color:var(--muted);font-size:12px">۱:${p.rr_to_liq}</span></div></div>` : ""}
      </div>
      ${sizeHtml}
    </div>`;
  }

  // بلوکِ ناحیه‌ی OTE (۰.۶۲–۰.۷۹ فیب)
  let oteHtml="";
  if(d.ote){
    const o=d.ote;
    const inside=o.inside;
    const cls=inside?"ote-in":"ote-out";
    const icon=inside?"✅":"⛔";
    const head=inside
      ? "قیمت داخلِ ناحیه‌ی موفقِ ورود (OTE) است — ورودِ باکیفیت"
      : "قیمت بیرونِ ناحیه‌ی موفق است — بهتر است منتظرِ پولبک بمانی";
    oteHtml=`<div class="ote ${cls}">
      <div class="ote-head">${icon} ناحیه‌ی OTE (۰.۶۲ تا ۰.۷۹ فیب)</div>
      <div class="ote-body">${head}</div>
      <div class="ote-nums">
        <span>محدوده‌ی موفقِ ورود: <b>${fmt(o.low)} – ${fmt(o.high)}</b></span>
        <span>قیمتِ فعلی: <b>${fmt(d.last_price)}</b> (فیبِ ${o.fib_pct}٪)</span>
      </div>
      <button class="alarm-btn" id="alarmBtn" title="روی این ناحیه‌ی OTE آلارم بگذار؛ هر ۹۰ ثانیه بررسی می‌شود و وقتی قیمت واردِ ناحیه شد خبر می‌دهد.">🔔 آلارم روی این ناحیه بگذار</button>
      <span id="alarmMsg" class="jmsg"></span>
    </div>`;
  }

  let badges="";
  if(d.killzone){badges+=`<span class="badge kz">🕐 ${kzFa(d.killzone)}</span>`;}
  if(d.macro && d.macro.gate){
    const g=d.macro.gate.toLowerCase();
    const cls=g.includes("red")?"g-red":g.includes("amber")?"g-amber":"g-green";
    badges+=`<span class="badge ${cls}">گیتِ خبر: ${gateFa(d.macro.gate)}</span>`;
  }

  let upcoming="";
  if(d.macro && d.macro.upcoming && d.macro.upcoming.length){
    upcoming=`<div class="upcoming">⚠️ اخبارِ مهمِ پیشِ رو (۴۸س): ${d.macro.upcoming.join(" · ")}</div>`;
  }

  const biasStrip = d.bias_by_tf ? Object.entries(d.bias_by_tf).map(([k,v])=>`${k}=${v}`).join(" · ") : "";

  // کارتِ پنجره‌ی سیلوربولت نیویورک — فقط در حالتِ sb_ny نمایش داده می‌شود
  let sbHtml="";
  if(d.is_sb_mode){
    const w=d.sb_window||{};
    const open=w.in_window;
    const stateTxt = open ? "🟢 پنجره باز است — تا بسته‌شدن:" : "🟠 پنجره بسته است — تا بازشدنِ ۰۹:۰۰ ET:";
    const stateCls = open ? "sb-open" : "sb-shut";
    const nowEt = (w.et_hour!=null) ? `${String(w.et_hour).padStart(2,"0")}:${String(w.et_minute||0).padStart(2,"0")} ET` : "—";
    const gate = open
      ? `<div style="color:#22d3a5;font-size:13px;margin-top:6px">✅ الان داخلِ پنجره‌ای — شرایطِ ورودِ زیر را روی چارتِ ۱ دقیقه دنبال کن.</div>`
      : `<div style="color:#f59e0b;font-size:13px;margin-top:6px">⏳ خارج از پنجره — سیگنالِ ورود فقط بینِ ۰۹:۰۰ تا ۱۱:۰۰ ET معتبر است. تایمرِ بالا تا بازشدن می‌شمارد.</div>`;
    sbHtml=`<div class="sbwin">
      <h3>🎯 سیلوربولت نیویورک — استراتژیِ ۱ دقیقه (پنجره‌ی ۰۹:۰۰–۱۱:۰۰ ET)</h3>
      <div id="sbState" class="sb-state ${stateCls}">${stateTxt}</div>
      <div class="sb-timer" id="sbTimer">—</div>
      <div style="color:var(--muted);font-size:12px;margin-top:4px">ساعتِ فعلیِ نیویورک: <b>${nowEt}</b></div>
      ${gate}
      <ol class="sb-steps">
        <li><b>بایاس (قبل از ۰۹:۰۰):</b> جهتِ روزت را از ۱۵m/۵m بگیر؛ فقط هم‌جهت معامله کن. سقف/کفِ سشنِ آسیا و لندن را به‌عنوانِ لیکوئیدیتیِ هدف علامت بزن.</li>
        <li><b>سوئیپ (جوداس):</b> صبر کن قیمت یک لیکوئیدیتیِ نزدیک را بزند (کفِ ساعتِ قبل برای خرید، سقف برای فروش) — تله‌ی استاپِ خردها.</li>
        <li><b>ام‌اس‌اس + دیسپلیسمنت:</b> بلافاصله بعدِ سوئیپ، یک کندلِ پرقدرت باید ساختارِ ۱m را خلافِ سوئیپ با <b>کلوز</b> بشکند (نه فتیله).</li>
        <li><b>فیرولیوگپ:</b> همان کندلِ دیسپلیسمنت یک FVGِ ۳کندلی می‌سازد — ناحیه‌ی ورودِ تو.</li>
        <li><b>ورود/استاپ/هدف:</b> لیمیت روی لبه‌ی FVG · استاپ پشتِ فتیله‌ی سوئیپ · هدف لیکوئیدیتیِ مقابل (سقف/کفِ آسیا/لندن)، با RR ۱:۲ تا ۱:۳.</li>
      </ol>
    </div>`;
  }

  res.innerHTML=`<div class="card">
    <div class="rhead">
      <div class="sym">${d.symbol}</div>
      <span class="dir ${dirClass(d.direction)}">${d.direction}</span>
      <span class="price" title="کلوزِ آخرین کندلِ بستهٔ تایم‌فریمِ ورود (نه قیمتِ لحظه‌ایِ کندلِ ناقص).">قیمت: ${fmt(d.last_price)}</span>
      <div class="spacer"></div>
      <div class="grade" style="background:${gradeColor(d.grade)}">${d.grade}</div>
    </div>
    <div class="metaline">
      <span>سبک: <b>${d.style}</b></span>
      <span>تایم‌فریم‌ها: <b>${(d.timeframes||[]).join(" ، ")}</b></span>
      ${biasStrip?`<span>بایاس: <b>${biasStrip}</b></span>`:""}
    </div>
    ${dataHtml}
    ${riskHtml}
    <div class="scorebar"><div class="scorefill" style="width:${pct}%;background:${gradeColor(d.grade)}"></div></div>
    <div class="scoretxt">امتیاز: <b style="color:var(--txt)">${d.score}</b> از ${d.max_score} (${pct}٪)</div>
    <table>
      <thead><tr><th>وضعیت</th><th>معیار / جزئیات</th><th>امتیاز</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    ${planHtml}
    ${sbHtml}
    ${oteHtml}
    <div style="margin-top:14px">${badges}</div>
    ${upcoming}
    <div class="verdict">${d.verdict||""}</div>
    <div class="jrnrow">
      <button id="jbtn" class="jbtn" ${d.plan?"":"disabled"} title="این ستاپ را با پلنِ عددی‌اش در ژورنالِ معاملات ثبت کن. تا وقتی پلنِ معتبری نباشد غیرفعال است.">💾 ثبت در ژورنال</button>
      <span id="jmsg" class="jmsg"></span>
    </div>
  </div>`;
  window._last = d;
  if(refreshBtn) refreshBtn.disabled = false;
  const jb = document.getElementById("jbtn");
  if(jb) jb.onclick = saveJournal;
  const ab = document.getElementById("alarmBtn");
  if(ab) ab.onclick = setOteAlarm;
  // تایمرِ زنده‌ی سیلوربولت را استارت بزن (اگر در این حالت هستیم)
  if(d.is_sb_mode && d.sb_window){ startSbTimer(d.sb_window); }
  else if(_sbTimer){ clearInterval(_sbTimer); _sbTimer=null; }
  // چراغ‌های ستاپ‌ها بعد از هر تحلیل تازه شوند (اگر پنل باز است)
  renderSetups(d.setup_statuses);
  // چیپِ سنِ داده فوراً تازه شود (بدونِ انتظارِ ۳۰ ثانیه‌ی تایمر)
  loadData();
}

// ── پنلِ ستاپ‌ها: همیشه بالای صفحه، مستقل از کارتِ نتیجه ──────────────
// سه ستاپِ بک‌تست‌شده (walk=1200–1500، جمعِ ۲۴ معامله: WR~۶۶٪، totalR +6.49)
const scalpSetups=[
  {t:"۱) پولبک به OTE در امتداد روند (ستاپِ اصلی)",
   wr:"۶۲–۷۰٪", r:"+4.5R (ETH · ۱۰ معامله)",
   path:["بایاس: روندِ 1h را بخوان (HH/HL صعودی یا LH/LL نزولی) — فقط هم‌جهت معامله کن",
         "صبر کن قیمت به ناحیه‌ی OTE (۰.۶۲–۰.۷۹ فیبِ آخرین پای ایمپالس) پولبک بزند",
         "روی 5m منتظر سوئیپِ لیکوئیدیتی بمان (فتیله زیرِ کف/بالای سقفِ قبلی + کلوزِ برگشتی)",
         "چاک/MSS هم‌جهت روی 15m تأیید شود + کندلِ دیسپلیسمنت (بدنه ≥ ۱.۵× میانگین)",
         "ورود: لیمیت روی لبه‌ی FVG یا گلدن‌پاکتِ ۰.۷۰۵ · استاپ پشتِ فتیله‌ی سوئیپ",
         "هدف: لیکوئیدیتیِ مقابل با RR حداقل ۱:۲ (سقفِ ۳R)"],
   note:"بیشترین تعداد سیگنال و پایدارترین آمار — ستاپِ پیش‌فرضِ اسکلپ."},
  {t:"۲) سوئیپِ سشن → برگشت از زونِ HTF (سبکِ طلای Smart Risk)",
   wr:"۶۷٪ (XAU)", r:"+1.6R (طلا · ۶ معامله)",
   path:["روی 30m زونِ عرضه/تقاضا (اردربلاک/FVGِ مبدأِ حرکتِ ایمپالسی) را علامت بزن — حداکثر ۳ کندل",
         "صبر کن قیمت وارد زون شود و حداقل ۳۰٪ آن را میتیگیت کند (اولین لمسِ سطحی = نه)",
         "برو روی 5m؛ سوئیپِ لیکوئیدیتیِ خلافِ جهتِ موردنظرت را تماشا کن (جوداس)",
         "MSS خلافِ سوئیپ با کلوزِ کندل تأیید شود",
         "ورود: لبه‌ی FVG یا اردربلاکِ 5m · استاپ پشتِ فتیله‌ی سوئیپ",
         "هدف: لیکوئیدیتیِ مقابل (EQH/EQL یا سقف/کفِ سشن) با RR ۱:۲ تا ۱:۳"],
   note:"بهترین ستاپ برای طلا و جفت‌های پرنوسانِ سشنِ نیویورک."},
  {t:"۳) ادامه‌دهنده پس از BOS (هم‌جهت با روندِ تازه‌شکسته)",
   wr:"۸۰٪ گریدِ B (BTC)", r:"+1.8R (BTC · ۵ معامله)",
   path:["روی 15m یک BOS تازه با کندلِ دیسپلیسمنت‌دار شناسایی کن (نه شکستِ بی‌جان)",
         "منتظر پولبکِ قیمت به مبدأِ حرکتِ شکست بمان (اردربلاکِ سازنده‌ی BOS)",
         "روی 5m ساختارِ کوچک هم‌جهت بسازد: HL بالاتر برای خرید / LH پایین‌تر برای فروش",
         "FVGِ داخلِ حرکتِ شکست پر نشده باشد = هدف و ورودِ هم‌زمان",
         "ورود: لیمیت در اردربلاک/FVG · استاپ زیرِ مبدأِ حرکت (پشتِ ساختار، نه درصدِ ثابت)",
         "هدف: اولین لیکوئیدیتیِ مقابل با کفِ RR ۱:۲"],
   note:"وین‌ریتِ بالا اما سیگنالِ کمتر — صبورانه، فقط BOSهای دیسپلیسمنت‌دار."}
];
function renderSetups(statuses){
  const list=document.getElementById("spList");
  const state=document.getElementById("spState");
  if(!list) return;
  const st = statuses || [null,null,null];
  if(state){
    if(statuses){
      state.textContent=`— آخرین تحلیل: ${(window._last&&window._last.symbol)||""} · ${new Date().toLocaleTimeString("fa-IR")}`;
    }else{
      state.textContent="— اول یک تحلیل بگیر تا چراغ‌ها روشن شوند";
    }
  }
  const lamp = s => s==="green" ? `<span class="lamp g">🟢 تأییدِ قوی</span>`
                : s==="yellow" ? `<span class="lamp y">🟡 منتظرِ شرایط</span>`
                : s==="red" ? `<span class="lamp r">🔴 شرایط نیست</span>`
                : `<span class="lamp y">⚪ بی‌داده — تحلیل بگیر</span>`;
  list.innerHTML = scalpSetups.map((s,i)=>`
    <div class="acc-item${st[i]&&st[i].state==="green"?" open":""}">
      <button class="acc-head" data-i="${i}">
        <span>${s.t}</span>${lamp(st[i]&&st[i].state)}<span class="arr">▼</span>
      </button>
      <div class="acc-body">
        ${st[i] ? `<div class="acc-why">${st[i].why||""}</div>` : ""}
        <div class="acc-path"><b>مسیرِ ستاپ:</b><br>${s.path.map((p,j)=>`${j+1}. ${p}`).join("<br>")}</div>
        <div class="acc-stats"><span>📊 وین‌ریتِ بک‌تست: <b>${s.wr}</b></span><span>💰 بازده: <b>${s.r}</b></span></div>
        <div style="margin-top:8px;color:var(--muted);font-size:12px">💡 ${s.note}</div>
      </div>
    </div>`).join("");
  list.querySelectorAll(".acc-head").forEach(h=>{
    h.onclick=()=>{
      h.closest(".acc-item").classList.toggle("open");
    };
  });
}
// دکمه‌ی تاگلِ پنلِ ستاپ‌ها
const setupsBtn=document.getElementById("setupsBtn"), setupsPanel=document.getElementById("setupsPanel");
if(setupsBtn && setupsPanel){
  setupsBtn.onclick=()=>{
    const open=setupsPanel.classList.toggle("open");
    setupsBtn.classList.toggle("active",open);
    if(open) renderSetups(window._last && window._last.setup_statuses);
  };
}
// رندرِ اولیه: سه ستاپ با چراغِ «بی‌داده» از همان ابتدا دیده شوند
renderSetups(null);

// دکمه‌ی فاندمنتال — صفحه‌ی جداگانه‌ی اخبارِ اقتصادی را در تبِ نو باز می‌کند
const fundBtn=document.getElementById("fundBtn");
if(fundBtn){ fundBtn.onclick=()=>window.open("/fundamental","_blank","noopener"); }

// دکمه‌ی 📲 نصب روی دستگاه — آدرسِ قابل‌اشتراک + راهنمای هر پلتفرم + رویدادِ نصب
(function(){
  const ib=document.getElementById("installBtn");
  if(!ib) return;
  let deferredPrompt=null, installed=false;
  window.addEventListener("beforeinstallprompt", (e)=>{
    e.preventDefault(); deferredPrompt=e;
    if(installed) return;
    ib.classList.add("pulsing");
    ib.title="✅ مرورگرِ این دستگاه نصبِ مستقیم را پیشنهاد می‌دهد — کلیک کن و «نصب» را بزن.";
  });
  window.addEventListener("appinstalled", ()=>{
    installed=true; deferredPrompt=null; ib.classList.remove("pulsing");
  });
  ib.onclick=async ()=>{
    if(deferredPrompt && !installed){
      try{
        deferredPrompt.prompt();
        const res=await deferredPrompt.userChoice;
        if(res && res.outcome==="accepted"){ installed=true; ib.classList.remove("pulsing"); return; }
        // رد کرد → پنجرهٔ راهنما را نشان بده (کاربر شاید توضیح می‌خواهد)
      }catch(e){}
    }
    let base="";
    try{
      const r=await fetch("/api/install",{cache:"no-store"});
      const j=await r.json();
      if(j && j.lan && j.lan.url) base=j.lan.url;
    }catch(e){}
    const own=base || location.origin;
    const open=own.replace(/\/$/, "") + "/";
    const sw=("serviceWorker" in navigator);
    const swTxt=sw ? "✅ سرویس‌ورکر ثبت شده — آفلاین هم باز می‌شود" : "⚠ سرویس‌ورکر در این مرورگر نیست — نصبِ PWA ممکن نیست";
    openModal("📲 نصبِ pipfound روی دستگاه", `
      <div class="inst-h">آدرسِ این اپ</div>
      <div class="inst-url" id="instUrl">${open}</div>
      <div class="inst-row">
        <button class="inst-cp" id="instCopy">📋 کپیِ آدرس</button>
        <span class="inst-note">این آدرس را در مرورگرِ هر دستگاهی که به همین شبکه است باز کن — روی گوشی از طریقِ Wi-Fiِ خانه.</span>
      </div>
      <div class="inst-h">راهنمای هر دستگاه</div>
      <div class="inst-grid">
        <div class="inst-card"><div class="t">🤖 اندروید (کروم)</div><ol><li>آدرس را باز کن</li><li>منوی ⋮ → «Add to Home screen / نصب برنامه»</li><li>«Install / نصب» را بزن</li></ol></div>
        <div class="inst-card"><div class="t">🍎 آیفون/آیپد (سافاری)</div><ol><li>آدرس را در سافاری باز کن</li><li>دکمهٔ اشتراک ⬆ → «Add to Home Screen»</li><li>«Add» را بزن</li></ol></div>
        <div class="inst-card"><div class="t">💻 ویندوز (کروم/اج)</div><ol><li>آدرس را باز کن</li><li>آیکونِ ⊕ در نوارِ آدرس (یا منوی ⋯ → Apps)</li><li>«Install» را بزن</li></ol></div>
        <div class="inst-card"><div class="t">💻 مک (کروم/اج)</div><ol><li>آدرس را باز کن</li><li>آیکونِ ⊕ در نوارِ آدرس</li><li>«Install» — اپ جدا از مرورگر باز می‌شود</li></ol></div>
      </div>
      <div class="inst-status">${swTxt}${(deferredPrompt||installed)?" · وضعیتِ نصبِ این مرورگر: "+(installed?"نصب شده":"آمادهٔ نصبِ مستقیم"):""}</div>
      <div class="inst-warn">نکتهٔ سافاریِ آیفون: اگر این سرور با HTTPSِ خودگواهی‌شده باز شده، اول یک بار هشدارِ گواهی را بپذیر و صفحه را کامل باز کن — بعد «Add to Home Screen» کار می‌کند.</div>
    `);
    const cp=document.getElementById("instCopy");
    if(cp){ cp.onclick=async ()=>{
      try{ await navigator.clipboard.writeText(open); cp.textContent="✅ کپی شد"; }
      catch(e){
        // فالبک بدونِ HTTPS: انتخابِ متن برای کپیِ دستی
        const u=document.getElementById("instUrl");
        if(u){ const rg=document.createRange(); rg.selectNodeContents(u);
               const s=getSelection(); s.removeAllRanges(); s.addRange(rg); }
        cp.textContent="متن انتخاب شد — ⌘C بزن";
      }
      setTimeout(()=>{ cp.textContent="📋 کپیِ آدرس"; }, 1800);
    }; }
  };
})();

// بنرِ «نسخهٔ تازهٔ اپ آماده است» — وقتی سرویس‌ورکرِ جدید فعال می‌شود
if("serviceWorker" in navigator){
  navigator.serviceWorker.addEventListener("controllerchange", ()=>{
    // فقط اگر صفحه از قبل کامل بار شده (نصبِ اول نیست)
    if(!window.__pfReady) return;
    const old=document.getElementById("pfSwBanner"); if(old) return;
    const b=document.createElement("div"); b.id="pfSwBanner";
    b.setAttribute("style","position:fixed;bottom:14px;inset-inline-start:14px;z-index:2147483646;"+
      "background:linear-gradient(135deg,#0ea5e9,#6366f1);color:#04121f;padding:10px 16px;border-radius:12px;"+
      "font:700 13px/1.6 inherit,system-ui,sans-serif;box-shadow:0 8px 28px rgba(0,0,0,.45);cursor:pointer;display:flex;gap:10px;align-items:center");
    b.innerHTML="🔄 نسخهٔ تازهٔ اپ آماده است — برای فعال‌شدن، رفرش کن";
    b.onclick=()=>location.reload();
    document.body.appendChild(b);
  });
}

// پنجره‌ی عمومی (مودال) — بدونِ وابستگیِ بیرونی
function openModal(title, html){
  const old=document.getElementById("pipModal");
  if(old) old.remove();
  const ov=document.createElement("div");
  ov.className="modal-overlay"; ov.id="pipModal";
  ov.innerHTML=`<div class="modal-box">
    <div class="modal-head"><h3>${title}</h3>
      <button class="modal-close" title="بستن">×</button></div>
    <div class="modal-content">${html}</div>
  </div>`;
  ov.addEventListener("click", e=>{ if(e.target===ov) ov.remove(); });
  ov.querySelector(".modal-close").onclick=()=>ov.remove();
  document.body.appendChild(ov);
}

// دکمه‌ی 📁 آرشیو اقتصادی — اخبارِ ۶ ساعتِ گذشته + جهتِ موردانتظار، بدونِ رفرشِ صفحه
const archiveBtn=document.getElementById("archiveBtn");
if(archiveBtn){
  archiveBtn.onclick=async ()=>{
    archiveBtn.disabled=true;
    try{
      const r=await fetch("/api/fundamental-archive?hours=6");
      const data=await r.json();
      if(data.error){
        openModal("📁 آرشیو اقتصادی", `<div class="arc-empty">خطا: ${data.error}</div>`);
        return;
      }
      const evs=data.events||[];
      const gold=x=>(x&&x[0]?` · ${x[0]}: ${x[1]}`:"");
      const rows = evs.length ? evs.map(e=>{
        const a=e.analysis||{}, b=a.beat||{}, m=a.miss||{};
        return `<div class="arc-ev">
          <div class="arc-t">${a.icon||""} ${e.title_fa||e.title||""}<span class="arc-en">${e.title||""}</span></div>
          <div class="arc-m">${e.country_fa||e.country||""} · ${e.when_fa||""}${e.minutes_ago!=null?` · ${e.minutes_ago} دقیقه پیش`:""} · ${e.impact==="High"?"پرتأثیر":"متوسط"}</div>
          <div class="arc-d">⬆ ${b.label||""}: ${b.ccy_dir||""}${gold(b.gold)}</div>
          <div class="arc-d">⬇ ${m.label||""}: ${m.ccy_dir||""}${gold(m.gold)}</div>
        </div>`;
      }).join("") : `<div class="arc-empty">در ۶ ساعتِ گذشته خبرِ پرتأثیری در تقویم نبود.</div>`;
      openModal(`📁 آرشیو اقتصادی — ۶ ساعتِ اخیر (${data.count||0} خبر)`,
        rows + `<div class="arc-note">این جهت‌ها «اثرِ موردانتظار»اند (عددِ بهتر یا بدتر از پیش‌بینی)؛ تقویمِ ForexFactory عددِ اعلام‌شدهٔ واقعی را در این خروجی نمی‌دهد و محرکِ واقعیِ بازار انحرافِ عدد از پیش‌بینی است.</div>`);
    }catch(err){
      openModal("📁 آرشیو اقتصادی", `<div class="arc-empty">ارتباط ناموفق: ${err}</div>`);
    }finally{
      archiveBtn.disabled=false;
    }
  };
}

async function setOteAlarm(){
  const d = window._last;
  if(!d || !d.ote){return;}
  const ab = document.getElementById("alarmBtn");
  const am = document.getElementById("alarmMsg");
  ab.disabled = true; am.textContent = "در حالِ ثبتِ آلارم…"; am.className="jmsg";
  try{
    const r = await fetch("/api/alarm", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({
        symbol: d.symbol, mode:"ote",
        low: d.ote.low, high: d.ote.high,
        direction: d.direction, style: d.style_key||"day"
      })
    });
    const j = await r.json();
    if(j.error){am.textContent="خطا: "+j.error; am.className="jmsg bad"; ab.disabled=false;}
    else{am.textContent=`🔔 آلارم فعال شد — با رسیدنِ ${d.symbol} به ناحیه‌ی OTE هشدار می‌گیری`; am.className="jmsg good";}
  }catch(err){
    am.textContent="ارتباط ناموفق: "+err; am.className="jmsg bad"; ab.disabled=false;
  }
}

async function saveJournal(){
  const d = window._last;
  if(!d || !d.plan){return;}
  const jb = document.getElementById("jbtn");
  const jmsg = document.getElementById("jmsg");
  jb.disabled = true; jmsg.textContent = "در حالِ ثبت…"; jmsg.className = "jmsg";
  try{
    const r = await fetch("/api/journal", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify(d)
    });
    const j = await r.json();
    if(j.error){jmsg.textContent = "خطا: "+j.error; jmsg.className="jmsg bad"; jb.disabled=false;}
    else{jmsg.textContent = `✅ ثبت شد — معامله‌ی #${j.added} (${j.symbol})`; jmsg.className="jmsg good";}
  }catch(err){
    jmsg.textContent = "ارتباط ناموفق: "+err; jmsg.className="jmsg bad"; jb.disabled=false;
  }
}

function fmt(x){
  if(x==null)return "—";
  const a=Math.abs(x);
  if(a>=1000)return (+x).toFixed(1);
  if(a>=10)return (+x).toFixed(3);
  return (+x).toFixed(5);
}
function kzFa(k){
  if(!k)return "";
  const m={"London Open":"اوپنِ لندن","New York AM":"نیویورک صبح","London Close":"کلوزِ لندن",
    "New York PM":"نیویورک بعدازظهر","Asian Range":"رِنجِ آسیایی"};
  for(const [en,fa] of Object.entries(m))if(k.includes(en))return "کیل‌زونِ "+fa;
  return "خارج از کیل‌زونِ اصلی";
}
function gateFa(g){
  const s=(g||"").toUpperCase();
  if(s.includes("RED"))return "قرمز (ورود ممنوع)";
  if(s.includes("AMBER"))return "کهربایی (احتیاط)";
  return "سبز (عادی)";
}

// ── چارتِ زندهٔ TradingView ──
const TV_MAP = __TVMAP__;
function tvSymbol(sym){
  const s=(sym||"").trim().toUpperCase();
  if(TV_MAP[s]) return TV_MAP[s];
  if(s.length===6 && /^[A-Z]+$/.test(s)) return "FX_IDC:"+s;
  return s;
}
function tvInterval(){
  return ({scalp:"15",day:"60",swing:"240"})[style] || "60";
}
function showLiveChart(sym){
  const box=document.getElementById("tvBox");
  const lbl=document.getElementById("tvSymLbl");
  const tv=tvSymbol(sym);
  lbl.textContent = "— "+sym;
  const url="https://s.tradingview.com/widgetembed/?symbol="+encodeURIComponent(tv)
    +"&interval="+tvInterval()
    +"&theme=dark&style=1&timezone=Etc/UTC&hide_side_toolbar=0&withdateranges=1&hideideas=1&locale=fa";
  box.innerHTML=`<iframe src="${url}" allowtransparency="true" scrolling="no" allowfullscreen></iframe>`;
}

// ── آپلود و مرورِ اسکرین‌شات ──
const shotFile=document.getElementById("shotFile");
const shotPick=document.getElementById("shotPick");
const shotNote=document.getElementById("shotNote");
const shotMsg=document.getElementById("shotMsg");
shotPick.onclick=()=>shotFile.click();
shotFile.onchange=async()=>{
  const f=shotFile.files[0];
  if(!f)return;
  if(f.size>12*1024*1024){shotMsg.textContent="فایل بیش از ۱۲ مگابایت است.";shotMsg.className="jmsg bad";return;}
  shotMsg.textContent="در حالِ آپلود…";shotMsg.className="jmsg";shotPick.disabled=true;
  try{
    const dataurl=await new Promise((res,rej)=>{
      const rd=new FileReader();rd.onload=()=>res(rd.result);rd.onerror=rej;rd.readAsDataURL(f);
    });
    const r=await fetch("/api/screenshot",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({symbol:symIn.value.trim(),note:shotNote.value.trim(),dataurl})
    });
    const j=await r.json();
    if(j.error){shotMsg.textContent="خطا: "+j.error;shotMsg.className="jmsg bad";}
    else{shotMsg.textContent="✅ آپلود شد.";shotMsg.className="jmsg good";shotNote.value="";loadShots();}
  }catch(err){shotMsg.textContent="آپلود ناموفق: "+err;shotMsg.className="jmsg bad";}
  finally{shotPick.disabled=false;shotFile.value="";}
};

async function loadShots(){
  try{
    const r=await fetch("/api/screenshots");
    const list=await r.json();
    const grid=document.getElementById("shotGrid");
    if(!list.length){grid.innerHTML='<div class="aempty">هنوز اسکرین‌شاتی آپلود نکرده‌ای.</div>';return;}
    grid.innerHTML=list.map(s=>{
      const src="/api/screenshot?id="+encodeURIComponent(s.id);
      const sym=s.symbol?`<b>${s.symbol}</b> · `:"";
      const note=s.note?`${s.note}`:"بدونِ یادداشت";
      return `<div class="shot">
        <img src="${src}" data-full="${src}" alt="chart">
        <div class="meta">${sym}${note}<br>${s.created||""}
          <br><button class="sdel" data-id="${s.id}" title="این اسکرین‌شات را برای همیشه حذف کن.">حذف</button></div>
      </div>`;
    }).join("");
    grid.querySelectorAll("img").forEach(im=>{
      im.onclick=()=>{const lb=document.getElementById("lightbox");
        document.getElementById("lightboxImg").src=im.dataset.full;lb.classList.add("on");};
    });
    grid.querySelectorAll(".sdel").forEach(b=>{
      b.onclick=async()=>{await fetch("/api/screenshot?id="+encodeURIComponent(b.dataset.id),{method:"DELETE"});loadShots();};
    });
  }catch(e){}
}
document.getElementById("lightbox").onclick=function(){this.classList.remove("on");};
loadShots();

// ── رِندرِ آلارم‌ها + پولینگِ زنده ──
async function loadAlarms(){
  try{
    const r = await fetch("/api/alarms");
    const list = await r.json();
    const box = document.getElementById("alarmsList");
    if(!list.length){box.innerHTML='<div class="aempty">هنوز آلارمی نگذاشته‌ای.</div>';return;}
    box.innerHTML = list.map(a=>{
      const trig = a.triggered;
      const dirFa = (a.direction==="صعودی"||a.direction===1)?"خرید":((a.direction==="نزولی"||a.direction===-1)?"فروش":"—");
      const pill = trig
        ? `<span class="pill hit">✅ رسید!</span>`
        : `<span class="pill waiting">⏳ در انتظار</span>`;
      const reason = trig && a.hit_reason ? `<div class="arng" style="width:100%">${a.hit_reason} · ${a.triggered_at||""}</div>` : "";
      const px = a.last_price!=null ? `<span class="apx">فعلی: ${fmt(a.last_price)}</span>` : "";
      return `<div class="alarm-item ${trig?'trig':''}">
        <span class="asym">${a.symbol}</span>
        <span class="arng">${dirFa} · OTE ${fmt(a.low)}–${fmt(a.high)}</span>
        ${px}
        <span class="astat">${pill}</span>
        <button class="adel" data-id="${a.id}" title="این آلارم را حذف کن؛ دیگر بررسی نمی‌شود.">حذف</button>
        ${reason}
      </div>`;
    }).join("");
    box.querySelectorAll(".adel").forEach(b=>{
      b.onclick = async ()=>{
        await fetch("/api/alarm?id="+encodeURIComponent(b.dataset.id), {method:"DELETE"});
        loadAlarms();
      };
    });
  }catch(e){}
}
loadAlarms();
setInterval(loadAlarms, 30000);

// ثبتِ service worker تا اپ مثلِ یک اپِ نصب‌پذیر بالا بیاید (فقط روی http/https)
if("serviceWorker" in navigator && (location.protocol==="http:" || location.protocol==="https:")){
  window.addEventListener("load", ()=>{ navigator.serviceWorker.register("/sw.js").catch(()=>{}); });
}

// نشانگرِ بازنگریِ کد + وضعیتِ ری‌استارتِ خودکارِ «کهنه»
let revFirst=null, revRetry=null;
async function loadRev(){
  const el=document.getElementById("revChip"); if(!el) return;
  try{
    const r=await fetch("/api/revision",{cache:"no-store"});
    const j=await r.json();
    if(revRetry){ clearTimeout(revRetry); revRetry=null; }
    const ar=j.autorestart||{}, blocked=ar.blocked;
    const sha=(j.loaded&&j.loaded.sha)||"?";
    const up=Math.round(j.uptime_s||0);
    const upTxt=up<90 ? up+"s" : (up<5400 ? Math.round(up/60)+"m" : Math.round(up/3600)+"h");
    const extra=[];
    if(j.loaded&&j.loaded.dirty) extra.push("±dirty");
    if(j.sha_drift) extra.push("disk:"+((j.disk&&j.disk.sha)||"?"));
    if(revFirst===null) revFirst=sha;
    const pageOld=(revFirst!==sha);
    let cls="revchip", head="";
    if(pageOld){ cls+=" warn"; head="⟳ صفحه قدیمی است — رفرش کن · "; }
    else if(j.stale && blocked){ cls+=" bad"; head="⚠ کدِ تازه خراب است · "; }
    else if(j.stale && ar.enabled){ cls+=" warn"; head="♻ در حالِ ری‌استارت · "; }
    else if(j.stale){ cls+=" bad"; head="⚠ کهنه · "; }
    el.textContent=head+sha+" · "+upTxt+(extra.length ? " · "+extra.join(" ") : "");
    el.className=cls;
    const p=[];
    p.push(pageOld
      ? "این صفحه با بازنگریِ "+revFirst+" بار شده و سرور الان "+sha+" را سرو می‌کند — برای دیدنِ رابطِ تازه صفحه را رفرش کن."
      : "کدِ سروشده با دیسک یکی است.");
    p.push("ری‌استارتِ خودکارِ کهنه: "+(ar.enabled ? "روشن (هر "+(ar.interval_s||5)+" ثانیه بررسی می‌شود)" : "خاموش"));
    if(ar.last && ar.last.at) p.push("آخرین ری‌استارت: "+ar.last.at+" (از "+(ar.last.from||"?")+" به "+(ar.last.to||"?")+") · فایل‌ها: "+((ar.last.files||[]).join(", ")||"—"));
    if(blocked) p.push("⚠ کدِ تازه روی دیسک سالم نیست، پس ری‌استارت انجام نمی‌شود: "+blocked.detail);
    const chg=(j.changed_files||[]).map(c=>c.file).join(", ");
    if(j.stale && chg) p.push("فایل‌های تازه‌تر از استارتِ پروسه: "+chg);
    p.push("pid "+(j.pid||"")+" · استارتِ پروسه: "+(j.boot_local||""));
    el.title=p.join(" · ");
  }catch(e){
    // سرور ممکن است همین الان خودش را از نو اجرا کرده باشد → زودتر دوباره بپرس
    el.textContent="♻ در حالِ ری‌استارت…";
    el.className="revchip warn";
    el.title="ارتباط با سرور قطع بود (ری‌استارتِ خودکار؟): "+e;
    if(!revRetry) revRetry=setTimeout(loadRev, 3000);
  }
}
loadRev();
setInterval(loadRev, 30000);
window.__pfReady = true;   // بعد از این، controllerchange یعنی «به‌روزرسانی»، نه نصبِ اول

// چیپِ «سنِ داده / باز-بستهٔ بازار» — مستقل از چیپِ کد و بدونِ هزینه‌ی شبکه‌ی سنگین:
// اندپوینت فقط وضعیتِ آخرین تحلیل را می‌خواند و سنِ داده را همین‌حالا بازمحاسبه می‌کند.
async function loadData(){
  const el=document.getElementById("dataChip"); if(!el) return;
  try{
    const r=await fetch("/api/data_status",{cache:"no-store"});
    const j=await r.json();
    const f=j.fresh||{}, a=j.analyzed||{};
    window._lastSeen=(a&&a.symbol)?a:null;   // حافظهٔ آخرین تحلیل (برای دکمه‌ی بروزرسانی)
    const st=f.state||a.state;
    const icon = st==="open"?"🟢" : st==="closed"?"🔴" : st?"🟡":"⚪";
    const label = st==="open"?"داده زنده" : st==="closed"?"بازار بسته" : st==="thin"?"سشنِ نازک" : st==="delayed"?"داده عقب" : "داده؟";
    const shortAge = f.age_human && st==="open" ? " · "+f.age_human : "";
    el.textContent = icon+" "+label+shortAge;
    el.className = "revchip"+(st==="closed"?" bad" : (st&&st!=="open"?" warn" : ""));
    const p=[];
    if(!st) p.push("هنوز هیچ تحلیلی ثبت نشده — بعد از اولین تحلیل، سنِ داده همین‌جا می‌آید.");
    else p.push((f.reason||a.reason||"")+(!f.reason&&a.reason?" (واحد در زمانِ تحلیل)":""));
    if(a.symbol) p.push("آخرین تحلیل: "+a.symbol+(a.tf?" · "+a.tf:"")+(a.style?" · سبکِ "+a.style:"")+(a.at?" · "+a.at:""));
    if(f.last_bar_ts) p.push("آخرین کندلِ بسته: "+(f.last_bar_utc||"?")+" UTC · سنِ داده: "+(f.age_human||"—"));
    p.push("ساعتِ نیویورک: "+(f.et_now||j.et_now||"—"));
    if(j.killzone) p.push("کیل‌زون: "+j.killzone);
    if(st && st!=="open") p.push("⚠ در این حالت پلن «الان قابلِ اجرا» نیست — فقط آماده‌سازیِ سناریو.");
    el.title=p.join(" · ");
  }catch(e){
    el.textContent="⚪ داده؟";
    el.className="revchip";
    el.title="وضعیتِ داده در دسترس نیست: "+e;
  }
}
loadData();
setInterval(loadData, 30000);

// ── پنلِ ریسک: سرمایه/درصد/سقف‌ها + وضعیتِ امروز (از ژورنال) ──────────
// عناصر با `getElementById` صریح گرفته می‌شوند (نه هِلپِرِ غیرمستقیم) تا نگهبانِ
// سلامت هم بتواند سیم‌کشی‌شان را ببیند و اگر روزی قطع شد، کامیت/CI رد شود.
const rkBalanceEl = document.getElementById("rkBalance");
const rkRiskEl    = document.getElementById("rkRisk");
const rkDailyEl   = document.getElementById("rkDaily");
const rkOpenEl    = document.getElementById("rkOpen");
const rkStatEl    = document.getElementById("rkStat");
const rkSaveEl    = document.getElementById("rkSave");
const rkMsgEl     = document.getElementById("rkMsg");
// مقدار را فقط وقتی می‌گذاریم که کاربر در حالِ تایپ در همان کادر نباشد
function _rkSet(el, v){ if(!el) return; if(document.activeElement===el) return; el.value=(v==null?"":v); }
function rkRenderStat(j){
  const el=rkStatEl; if(!el) return;
  const s=(j&&j.settings)||{}, d=(j&&j.daily)||{};
  const ccy=s.account_ccy||"USD";
  const bal=Number(s.balance||0), rp=Number(s.risk_pct||0), rpct=Number(d.realized_pct||0);
  const perTrade=(bal>0&&rp>0)?(bal*rp/100):0;
  const cls = d.breached ? "bad" : (rpct<0 ? "warn" : "good");
  const parts=[];
  parts.push("سرمایه: <b>"+(s.balance!=null?Number(s.balance).toLocaleString():"—")+" "+ccy+"</b>");
  parts.push("ریسکِ هر معامله: <b>"+(s.risk_pct!=null?s.risk_pct:"—")+"٪</b>"+(perTrade?" (= <b>"+perTrade.toFixed(2)+" "+ccy+"</b>)":""));
  parts.push("امروز: <b class=\""+cls+"\">"+(rpct>0?"+":"")+rpct+"٪</b> ("+Number(d.realized_r||0)+"R · "+(d.closed_today||0)+" معاملهٔ بسته)");
  if(d.remaining_pct!=null) parts.push("باقی‌مانده تا سقفِ "+d.limit_pct+"٪: <b>"+d.remaining_pct+"٪</b>"+(d.remaining_amount!=null?" ("+d.remaining_amount+" "+ccy+")":""));
  parts.push("ریسکِ باز: <b class=\""+(d.open_breached?"bad":"")+"\">"+Number(d.open_risk_pct||0)+"٪</b> از سقفِ "+d.open_risk_limit_pct+"٪ ("+(d.open_count||0)+" پوزیشن)");
  if(d.breached) parts.push("<span class=\"bad\">⛔ سقفِ ضررِ روزانه پر شده — امروز ورودِ جدید مجاز نیست.</span>");
  else if(d.open_breached) parts.push("<span class=\"bad\">⛔ سقفِ ریسکِ باز پر شده — اول یک پوزیشنِ باز را ببند.</span>");
  el.innerHTML = parts.join(" · ");
}
async function loadRisk(){
  try{
    const r = await fetch("/api/risk",{cache:"no-store"});
    const j = await r.json();
    if(!j || j.ok===false){
      if(rkStatEl) rkStatEl.textContent = "ماژولِ ریسک در دسترس نیست: "+((j&&j.error)||"؟");
      return;
    }
    const s=j.settings||{};
    _rkSet(rkBalanceEl, s.balance);
    _rkSet(rkRiskEl,    s.risk_pct);
    _rkSet(rkDailyEl,   s.daily_loss_limit_pct);
    _rkSet(rkOpenEl,    s.max_open_risk_pct);
    rkRenderStat(j);
  }catch(e){
    if(rkStatEl) rkStatEl.textContent = "وضعیتِ ریسک در دسترس نیست: "+e;
  }
}
async function saveRisk(){
  const btn=rkSaveEl, msg=rkMsgEl;
  const num = (el) => { const v=((el||{}).value||"").trim(); return v===""?null:Number(v); };
  btn.disabled=true; msg.textContent="در حالِ ذخیره…"; msg.className="jmsg";
  try{
    const r = await fetch("/api/risk",{
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({balance:num(rkBalanceEl), risk_pct:num(rkRiskEl),
                            daily_loss_limit_pct:num(rkDailyEl), max_open_risk_pct:num(rkOpenEl)})
    });
    const j = await r.json();
    if(j.error){ msg.textContent="خطا: "+j.error; msg.className="jmsg bad"; return; }
    msg.textContent="✅ ذخیره شد"; msg.className="jmsg good";
    rkRenderStat(j);
    // اگر تحلیلی روی صفحه است، سایزِ پوزیشن را فوراً با تنظیماتِ تازه دوباره بگیر
    const l = window._last;
    if(l && l.symbol){
      const rr = await fetch("/api/analyze?symbol="+encodeURIComponent(l.symbol)+"&style="+(l.style_key||"day"));
      const nd = await rr.json();
      if(!nd.error) render(nd);
    }
  }catch(e){
    msg.textContent="ارتباط ناموفق: "+e; msg.className="jmsg bad";
  }finally{
    btn.disabled=false;
    setTimeout(()=>{ if(msg.textContent==="✅ ذخیره شد") msg.textContent=""; }, 4000);
  }
}
if(rkSaveEl) rkSaveEl.onclick = saveRisk;
[rkBalanceEl, rkRiskEl, rkDailyEl, rkOpenEl].forEach(el=>{
  if(el) el.addEventListener("keydown", e=>{ if(e.key==="Enter") saveRisk(); });
});
loadRisk();

// علامتِ پایانِ بوت — اگر این خط اجرا نشود، هشدارِ قرمزِ نگهبانِ بوت بالای صفحه می‌آید
window.__pipfoundBooted = true;
</script>
</body>
</html>
"""


# ═══════════════════════════════════════════════════════════════════
#  صفحه‌ی جداگانه‌ی فاندمنتال — تقویمِ اقتصادی + تحلیلِ اثرِ خبرها
# ═══════════════════════════════════════════════════════════════════
FUND_PAGE = r"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pipfound — فاندمنتال (اخبارِ اقتصادی)</title>
<style>
:root{
  --bg:#0b0f17; --panel:#141a26; --panel2:#1b2333; --line:#28324a;
  --txt:#e8eefc; --muted:#8a97b3; --accent:#0ea5e9; --accent2:#6366f1;
  --good:#22c55e; --bad:#ef4444; --warn:#f59e0b;
}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 80% -10%,#16223b 0%,var(--bg) 55%);
  color:var(--txt);font-family:-apple-system,BlinkMacSystemFont,"Vazirmatn","Segoe UI",Tahoma,sans-serif;
  min-height:100vh;padding:28px 16px}
.wrap{max-width:960px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px;font-weight:800;
  background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent}
.sub{color:var(--muted);font-size:13px;margin:0 0 18px}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:16px}
.toolbar .seg{display:flex;gap:4px;background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:4px}
.toolbar .seg button{background:transparent;border:0;color:var(--muted);padding:9px 14px;border-radius:9px;
  cursor:pointer;font-size:13px;font-weight:700;font-family:inherit;transition:.15s}
.toolbar .seg button.active{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#04121f}
.toolbar .refresh{margin-inline-start:auto;background:var(--panel2);border:1px solid var(--line);color:var(--txt);
  border-radius:10px;padding:9px 16px;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit}
.toolbar .refresh:hover{border-color:var(--accent)}
.gen{color:var(--muted);font-size:12px;margin-bottom:14px}
.note{background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.3);border-radius:12px;
  padding:12px 16px;font-size:13px;line-height:1.8;color:#f6d99a;margin-bottom:18px}
.next{background:linear-gradient(135deg,rgba(14,165,233,.12),rgba(99,102,241,.10));
  border:1px solid rgba(14,165,233,.4);border-radius:14px;padding:16px;margin-bottom:20px}
.next .lbl{font-size:12px;color:var(--muted);margin-bottom:4px}
.next .ttl{font-size:17px;font-weight:800}
.next .cd{font-variant-numeric:tabular-nums;color:var(--accent);font-weight:800}
.ev{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:0;margin-bottom:14px;overflow:hidden}
.ev-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:16px 18px;cursor:pointer}
.ev-head:hover{background:var(--panel2)}
.ev-icon{font-size:22px}
.ev-main{flex:1;min-width:200px}
.ev-title{font-size:15.5px;font-weight:800;line-height:1.4}
.ev-title .en{color:var(--muted);font-size:12.5px;font-weight:600}
.ev-meta{color:var(--muted);font-size:12.5px;margin-top:4px;line-height:1.7}
.imp{font-size:11px;padding:4px 10px;border-radius:8px;font-weight:800;white-space:nowrap}
.imp.High{background:rgba(239,68,68,.14);color:#fca5a5;border:1px solid rgba(239,68,68,.4)}
.imp.Medium{background:rgba(245,158,11,.13);color:#fcd34d;border:1px solid rgba(245,158,11,.35)}
.ccy{font-size:12px;padding:4px 10px;border-radius:8px;background:var(--panel2);border:1px solid var(--line);
  font-weight:800;white-space:nowrap}
.cd-badge{font-size:12px;padding:4px 10px;border-radius:8px;background:rgba(14,165,233,.12);
  color:#7dd3fc;border:1px solid rgba(14,165,233,.35);font-weight:800;white-space:nowrap}
.chev{color:var(--muted);font-size:13px;transition:.2s}
.ev.open .chev{transform:rotate(180deg)}
.ev-body{display:none;padding:0 18px 18px;border-top:1px solid var(--line)}
.ev.open .ev-body{display:block}
.times{display:flex;gap:20px;flex-wrap:wrap;font-size:13px;margin:14px 0;color:#cdd8ef}
.times b{color:var(--txt)}
.fc{display:flex;gap:20px;flex-wrap:wrap;font-size:13px;margin-bottom:14px}
.fc .box{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:8px 14px}
.fc .box .k{color:var(--muted);font-size:11px}
.fc .box .v{font-weight:800;font-variant-numeric:tabular-nums}
.why{background:rgba(99,102,241,.08);border-right:3px solid var(--accent2);border-radius:8px;
  padding:10px 14px;font-size:13px;line-height:1.85;color:#dbe0ff;margin-bottom:14px}
.scen{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:640px){.scen{grid-template-columns:1fr}}
.scard{border-radius:12px;padding:14px}
.scard.beat{background:rgba(34,197,94,.07);border:1px solid rgba(34,197,94,.3)}
.scard.miss{background:rgba(239,68,68,.06);border:1px solid rgba(239,68,68,.28)}
.scard .sh{font-size:13px;font-weight:800;margin-bottom:6px}
.scard.beat .sh{color:#86efac}
.scard.miss .sh{color:#fca5a5}
.scard .cd-dir{font-size:13px;font-weight:800;margin-bottom:10px;color:var(--txt)}
.pairtbl{width:100%;border-collapse:collapse;font-size:13px}
.pairtbl td{padding:5px 4px;border-bottom:1px dashed var(--line)}
.pairtbl td:first-child{font-weight:700;font-variant-numeric:tabular-nums}
.pairtbl td:last-child{text-align:left;font-weight:800}
.dir-up{color:var(--good)}
.dir-dn{color:var(--bad)}
.dir-neu{color:var(--muted)}
.gold{margin-top:10px;font-size:12.5px;line-height:1.75;color:#e9d9a6;
  background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.25);border-radius:8px;padding:9px 12px}
.gold .g-dir{font-weight:800}
.empty{text-align:center;color:var(--muted);padding:40px;font-size:14px}
.err{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.35);color:#fca5a5;
  border-radius:12px;padding:16px;font-size:14px}
.back{display:inline-block;margin-bottom:16px;color:var(--accent);text-decoration:none;font-size:13px;font-weight:700}
.back:hover{text-decoration:underline}
</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="/">← بازگشت به تحلیلگر</a>
  <h1>📰 فاندمنتال — اخبارِ اقتصادی</h1>
  <p class="sub">اخبارِ پرتأثیرِ پیشِ‌رو (GDP، تورم، اشتغال، نرخِ بهره) با ساعتِ دقیقِ اعلام و تحلیلِ اثر روی جفت‌ارزهای مهم و طلا/نقره.</p>

  <div class="toolbar">
    <div class="seg" id="impSeg">
      <button data-imp="high" class="active">فقط پرتأثیر (High)</button>
      <button data-imp="all">همه (High + Medium)</button>
    </div>
    <div class="seg" id="horSeg">
      <button data-h="48">۴۸ ساعت</button>
      <button data-h="120" class="active">۵ روز</button>
      <button data-h="180">هفتگی</button>
    </div>
    <button class="refresh" id="refresh">↻ به‌روزرسانی</button>
  </div>

  <div class="gen" id="gen"></div>
  <div class="note" id="note"></div>
  <div id="nextWrap"></div>
  <div id="list"><div class="empty">در حالِ بارگذاریِ تقویم…</div></div>
</div>

<script>
let impMode="high", horHours=120, DATA=null;
const $=s=>document.querySelector(s);

function dirClass(d){ if(d.includes("صعود"))return "dir-up"; if(d.includes("نزول"))return "dir-dn"; return "dir-neu"; }

function pairRows(pairs){
  return pairs.map(p=>`<tr><td>${p[0]}</td><td class="${dirClass(p[1])}">${p[1]}</td></tr>`).join("");
}

function scenCard(cls, s){
  const g=s.gold;
  return `<div class="scard ${cls}">
    <div class="sh">${s.label}</div>
    <div class="cd-dir">${s.ccy_dir}</div>
    <table class="pairtbl"><tbody>${pairRows(s.pairs)}</tbody></table>
    <div class="gold">🥇 <span class="g-dir ${dirClass(g[1])}">${g[0]}: ${g[1]}</span><br>${g[2]}</div>
  </div>`;
}

function evCard(e,idx){
  const a=e.analysis;
  const fcBox = e.forecast?`<div class="box"><div class="k">پیش‌بینی</div><div class="v">${e.forecast}</div></div>`:"";
  const prBox = e.previous?`<div class="box"><div class="k">قبلی</div><div class="v">${e.previous}</div></div>`:"";
  const enTtl = e.title_fa? `<div class="en">${e.title}</div>` : "";
  const faTtl = e.title_fa || e.title;
  return `<div class="ev" data-i="${idx}">
    <div class="ev-head">
      <span class="ev-icon">${a.icon}</span>
      <div class="ev-main">
        <div class="ev-title">${faTtl}${enTtl}</div>
        <div class="ev-meta">${a.cat} · ${e.et}<br>${e.tehran}</div>
      </div>
      <span class="ccy">${e.country_fa} (${e.country})</span>
      <span class="imp ${e.impact}">${e.impact==="High"?"پرتأثیر":"متوسط"}</span>
      <span class="cd-badge">⏳ ${e.countdown}</span>
      <span class="chev">▾</span>
    </div>
    <div class="ev-body">
      <div class="times">
        <span>🗽 <b>${e.et}</b></span>
        <span>🇮🇷 <b>${e.tehran}</b></span>
      </div>
      <div class="fc">${fcBox}${prBox}</div>
      <div class="why">💡 ${a.why}</div>
      <div class="scen">
        ${scenCard("beat", a.beat)}
        ${scenCard("miss", a.miss)}
      </div>
    </div>
  </div>`;
}

function render(){
  if(!DATA) return;
  if(DATA.error){ $("#list").innerHTML=`<div class="err">خطا: ${DATA.error}</div>`; return; }
  $("#gen").textContent="تولیدِ گزارش: "+(DATA.generated_tehran||"");
  $("#note").textContent="⚠️ "+(DATA.note||"");
  let evs=DATA.events||[];
  if(impMode==="high") evs=evs.filter(e=>e.impact==="High");
  // next high
  const nh=DATA.next_high;
  $("#nextWrap").innerHTML = nh ? `<div class="next">
    <div class="lbl">نزدیک‌ترین خبرِ پرتأثیر</div>
    <div class="ttl">${nh.analysis.icon} ${nh.title_fa||nh.title} — ${nh.country_fa}</div>
    <div class="ev-meta" style="margin-top:6px">${nh.et} · 🇮🇷 ${nh.tehran}</div>
    <div style="margin-top:6px">تا اعلام: <span class="cd">${nh.countdown}</span></div>
  </div>` : "";
  if(!evs.length){ $("#list").innerHTML='<div class="empty">در این بازه خبری با این سطحِ تأثیر پیدا نشد.</div>'; return; }
  $("#list").innerHTML=evs.map((e,i)=>evCard(e,i)).join("");
  $("#list").querySelectorAll(".ev-head").forEach(h=>{
    h.onclick=()=>h.closest(".ev").classList.toggle("open");
  });
}

async function load(){
  $("#list").innerHTML='<div class="empty">در حالِ بارگذاریِ تقویم…</div>';
  try{
    const r=await fetch("/api/fundamental?hours="+horHours);
    DATA=await r.json();
    render();
  }catch(err){
    $("#list").innerHTML=`<div class="err">ارتباط ناموفق: ${err}</div>`;
  }
}

$("#impSeg").addEventListener("click",e=>{
  const b=e.target.closest("button"); if(!b)return;
  document.querySelectorAll("#impSeg button").forEach(x=>x.classList.remove("active"));
  b.classList.add("active"); impMode=b.dataset.imp; render();
});
$("#horSeg").addEventListener("click",e=>{
  const b=e.target.closest("button"); if(!b)return;
  document.querySelectorAll("#horSeg button").forEach(x=>x.classList.remove("active"));
  b.classList.add("active"); horHours=parseInt(b.dataset.h,10); load();
});
$("#refresh").onclick=load;
load();
// شمارشِ معکوسِ زنده هر ۶۰ ثانیه بازخوانی می‌شود
setInterval(load, 60000);
</script>
</body>
</html>
"""


# شمارشِ درخواست‌های در جریان — ری‌استارتِ خودکار فقط وقتی انجام می‌شود که
# هیچ درخواستی وسطِ کار نباشد (مثلاً وسطِ یک بک‌تستِ چنددقیقه‌ای قطع نشود).
_REQ_ACTIVE = [0]
_REQ_LOCK = threading.Lock()
_REQ_IDLE = threading.Event()
_REQ_IDLE.set()


def _req_enter():
    with _REQ_LOCK:
        _REQ_ACTIVE[0] += 1
        _REQ_IDLE.clear()


def _req_leave():
    with _REQ_LOCK:
        _REQ_ACTIVE[0] = max(0, _REQ_ACTIVE[0] - 1)
        if _REQ_ACTIVE[0] == 0:
            _REQ_IDLE.set()


# ── نصب روی دستگاه (PWA روی LAN) ─────────────────────────────────
# host=0.0.0.0 یعنی «باز برای شبکه»؛ در آن حالت بدونِ گیتِ توکن، هر دستگاهی
# داخلِ شبکه هم می‌تواند ببیند و هم در ژورنال بنویسد. --lan خودش یک توکنِ
# تصادفی می‌سازد و HTTPSِ خودگواهی‌شده می‌آورد (نصبِ PWA روی سافاری فقط روی
# https کار می‌کند) و یک پورتِ HTTPِ محلی برای «راه‌اندازیِ اولیه» باز می‌کند.
_ACCESS_TOKEN = ""      # خالی = بدونِ گیت (فقط host 127.0.0.1)
_ACCESS_COOKIE = "pf_tok"
_TLS_CERT = None        # مسیرِ گواهیِ موقت در حالتِ --lan
_TLS_KEY = None
_TLS_PORT = None        # پورتِ HTTPS واقعی (وقتی بوت‌استرپِ HTTP فعال است)
lan_open = False        # host=0.0.0.0 بدونِ TLS (فقط برای گزارشِ /api/install)
CURRENT_PORT = 8787     # در main() ست می‌شود؛ برای گزارشِ /api/install


def _install_info():
    """اطلاعاتِ اتصال برای پنلِ نصب: آدرسِ LAN و آدرس‌های هر اینترفیس."""
    import socket
    addrs = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in addrs and not ip.startswith("127."):
                addrs.append(ip)
    except Exception:
        pass
    lan_port = _TLS_PORT or CURRENT_PORT
    scheme = "https" if _TLS_PORT else "http"
    lan_url = f"{scheme}://<ip-of-this-mac>:{lan_port}" if not addrs else \
              f"{scheme}://{addrs[0]}:{lan_port}"
    return {
        "ok": True,
        "lan": {"enabled": bool(_TLS_PORT or _ACCESS_TOKEN or lan_open),
                "url": lan_url, "port": lan_port, "scheme": scheme,
                "https": bool(_TLS_PORT), "token_required": bool(_ACCESS_TOKEN),
                "addresses": addrs},
        "local": f"http://127.0.0.1:{CURRENT_PORT}",
    }


def _make_self_signed_cert():
    """گواهیِ خودگواهی‌شده با opensslِ سیستم (stdlib گواهی نمی‌سازد).
    مسیرِ فایل‌ها در ~/pipfound/tls تا بینِ ری‌استارت‌ها ثابت بماند."""
    import subprocess
    d = os.path.join(HOME, "pipfound", "tls")
    os.makedirs(d, exist_ok=True)
    cert, key = os.path.join(d, "cert.pem"), os.path.join(d, "key.pem")
    if not (os.path.isfile(cert) and os.path.isfile(key)):
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", key, "-out", cert, "-days", "825",
             "-subj", "/CN=pipfound-local",
             "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
            check=True, capture_output=True, timeout=60)
    return cert, key


def _check_auth(self, qs):
    """گیتِ توکن: کوکیِ معتبر یا ?token= یا هدرِ Authorization.
    مسیرهای آزاد: ورود (?token=) و سلامتِ سرور."""
    if not _ACCESS_TOKEN:
        return True
    cookies = (self.headers.get("Cookie") or "")
    m = re.search(rf"{ _ACCESS_COOKIE }=([A-Za-z0-9_\-]+)", cookies)
    if m and m.group(1) == _ACCESS_TOKEN:
        return True
    if (qs.get("token", [""])[0]) == _ACCESS_TOKEN:
        return True
    auth = self.headers.get("Authorization") or ""
    if auth.startswith("Bearer ") and auth[7:] == _ACCESS_TOKEN:
        return True
    return False


def _auth_page(self):
    """صفحهٔ ورودِ توکن — بعد از ورود، کوکیِ یک‌ساله ست می‌شود."""
    html = ("<!doctype html><html lang=\"fa\" dir=\"rtl\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>pipfound — ورود</title>"
            "<style>body{margin:0;background:#0b0f17;color:#e8eefc;min-height:100vh;"
            "display:grid;place-items:center;font-family:-apple-system,Vazirmatn,Tahoma,sans-serif}"
            ".c{background:#141a26;border:1px solid #28324a;border-radius:16px;padding:28px;"
            "max-width:360px;width:calc(100% - 40px);text-align:center}"
            "h1{font-size:19px;margin:0 0 6px}p{color:#8a97b3;font-size:13px;margin:0 0 18px}"
            "input{width:100%;padding:12px;border-radius:10px;border:1px solid #28324a;"
            "background:#1b2333;color:#e8eefc;font-size:15px;direction:ltr;text-align:center}"
            "button{margin-top:12px;width:100%;padding:12px;border:0;border-radius:10px;"
            "background:linear-gradient(135deg,#0ea5e9,#6366f1);color:#04121f;font-weight:800;"
            "font-size:14px;cursor:pointer}.err{color:#fca5a5;font-size:13px;margin-top:10px}</style></head>"
            "<body><div class=\"c\"><h1>🔐 ورود به pipfound</h1>"
            "<p>این سرور روی شبکهٔ خانه باز است؛ توکنِ دسترسی که هنگامِ بالا آمدن در ترمینال چاپ شده را وارد کن.</p>"
            "<form method=\"GET\" action=\"/\"><input name=\"token\" placeholder=\"توکنِ دسترسی\" autofocus>"
            "<button>ورود</button></form>"
            "<div class=\"err\">" + ("توکن درست نیست — دوباره تلاش کن" if "token" in (self.path or "") else "") + "</div>"
            "</div></body></html>")
    return self._send(200, html, "text/html; charset=utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # سکوت

    def handle_one_request(self):
        _req_enter()
        try:
            return super().handle_one_request()
        finally:
            _req_leave()

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            # کلاینت وسطِ محاسبه‌ی سنگین اتصال را بست (تایم‌اوت/رفرش) — بی‌صدا رد کن
            pass

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        # گیتِ توکن فقط وقتی فعال است که سرور روی شبکه باز باشد (--lan / --token)
        # فقط /api/health و /api/install آزادند (وضعیتِ اتصال برای پنلِ نصب لازم است)
        if _ACCESS_TOKEN and u.path not in ("/api/health", "/api/install"):
            if (qs.get("token", [""])[0]) == _ACCESS_TOKEN and u.path == "/":
                # ورود موفق → کوکی بده و بدونِ token در URL برو (توکن در هیستوری نمی‌ماند)
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie",
                                 f"{_ACCESS_COOKIE}={_ACCESS_TOKEN}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if not _check_auth(self, qs):
                return _auth_page(self)
        if u.path in ("/", "/index.html"):
            tvmap = {
                "BTCUSDT": "BINANCE:BTCUSDT", "ETHUSDT": "BINANCE:ETHUSDT",
                "SOLUSDT": "BINANCE:SOLUSDT", "BNBUSDT": "BINANCE:BNBUSDT",
                "XRPUSDT": "BINANCE:XRPUSDT", "DOGEUSDT": "BINANCE:DOGEUSDT",
                "XAUUSD": "OANDA:XAUUSD", "XAGUSD": "OANDA:XAGUSD",
                "XPTUSD": "OANDA:XPTUSD", "XPDUSD": "OANDA:XPDUSD",
                "GOLD": "OANDA:XAUUSD", "WTI": "TVC:USOIL", "BRENT": "TVC:UKOIL",
                # ثروتِ بخشِ تازه: اندیکس‌ها و کامودیتی‌های غیرفلزی و استاک‌ها
                "SPX500": "SP:SPX", "NAS100": "NASDAQ:NDX", "US30": "DJ:DJI",
                "GER40": "XETR:DAX", "UK100": "TVC:UKX", "JP225": "TVC:NI225",
                "NATGAS": "NYMEX:NG1!", "COPPER": "COMEX:HG1!",
                "NVDA": "NASDAQ:NVDA", "AAPL": "NASDAQ:AAPL", "MSFT": "NASDAQ:MSFT",
                "TSLA": "NASDAQ:TSLA", "AMZN": "NASDAQ:AMZN",
                "GOOGL": "NASDAQ:GOOGL", "META": "NASDAQ:META",
            }
            page = (HTML
                    .replace("__SUGGESTIONS__", json.dumps(SUGGESTIONS))
                    .replace("__SYMBOL_GROUPS__", json.dumps(SYMBOL_GROUPS,
                                                              ensure_ascii=False))
                    .replace("__TVMAP__", json.dumps(tvmap)))
            return self._send(200, page, "text/html; charset=utf-8")
        if u.path == "/api/analyze":
            q = parse_qs(u.query)
            sym = (q.get("symbol", [""])[0]).strip()
            style = (q.get("style", ["day"])[0]).strip()
            print(f"[analyze] {sym} · {style}", flush=True)   # ردیابیِ موقت
            if not sym:
                return self._send(400, json.dumps({"error": "نماد وارد نشده"}, ensure_ascii=False))
            try:
                r = analyze(sym, style)
                _remember_analysis(sym, style, r)
                return self._send(200, json.dumps(r, ensure_ascii=False))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False))
        if u.path == "/api/health":
            return self._send(200, json.dumps({"ok": True}))
        # اطلاعاتِ نصب روی دستگاه: آدرسِ LAN و وضعیتِ HTTPS/توکن — ارزان و محلی
        if u.path == "/api/install":
            return self._send(200, json.dumps(_install_info(), ensure_ascii=False))
        # وضعیتِ داده: ساعتِ سرور/نیویورک، کیل‌زونِ فعلی، و سنِ آخرین تحلیل.
        # عمداً فقط محاسبه‌ی محلی (بدونِ شبکه) تا این اندپوینت هر ۳۰ ثانیه ارزان باشد.
        if u.path == "/api/data_status":
            q = parse_qs(u.query)
            sym = (q.get("symbol", [""])[0]).strip().upper()
            now = time.time()
            with _last_seen_lock:
                seen = dict(_LAST_SEEN)
            item = None
            if sym and sym in seen:
                item = seen[sym]
            elif seen:
                item = max(seen.values(), key=lambda x: x.get("at", ""))
            out = {
                "ok": True,
                "server_utc": datetime.datetime.fromtimestamp(
                    now, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "et_now": E.et_of(now).strftime("%Y-%m-%d %H:%M"),
                "killzone": E.killzone_now(),
                "silver_bullet": E.silver_bullet_window(),
                "analyzed": item,
            }
            if item and item.get("last_bar_ts") is not None:
                # سنِ داده **همین حالا** دوباره حساب می‌شود (نه مقدارِ یخ‌زده‌ی تحلیلِ قبل)
                out["fresh"] = E.freshness_from(
                    item["last_bar_ts"], item.get("tf") or "15m",
                    item.get("symbol") or sym,
                    src=item.get("source") or "yahoo", now=now)
            return self._send(200, json.dumps(out, ensure_ascii=False))
        # وضعیتِ ریسک: تنظیماتِ کاربر + ضررِ محقق‌شده‌ی امروز + ریسکِ بازِ فعلی.
        # محاسبه‌ی صددرصد محلی (بدونِ شبکه) — مثلِ /api/data_status ارزان است.
        if u.path == "/api/risk":
            try:
                st = _risk_settings()
                rows = _journal_rows(_JR_FILE) or []
                day = RK.daily_state(rows, st) if RK is not None else {}
                return self._send(200, json.dumps({
                    "ok": RK is not None,
                    "settings": st,
                    "daily": day,
                    "journal_file": _JR_FILE,
                    "settings_file": (RK.settings_path() if RK is not None else None),
                }, ensure_ascii=False))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, json.dumps(
                    {"ok": False, "error": str(e)}, ensure_ascii=False))
        # نشانگرِ بازنگری: چه کدی بار شده، دیسک چه دارد، و آیا پروسه کهنه است
        if u.path == "/api/revision":
            try:
                return self._send(200, json.dumps(code_rev(), ensure_ascii=False))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, json.dumps(
                    {"ok": False, "error": str(e)}, ensure_ascii=False))
        if u.path == "/api/fundamental":
            if FUND is None:
                return self._send(200, json.dumps(
                    {"error": "موتورِ فاندمنتال در دسترس نیست"}, ensure_ascii=False))
            try:
                hours = int(parse_qs(u.query).get("hours", ["180"])[0])
            except Exception:
                hours = 180
            try:
                return self._send(200, json.dumps(FUND.build(hours=hours), ensure_ascii=False))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False))
        if u.path == "/fundamental":
            return self._send(200, FUND_PAGE, "text/html; charset=utf-8")
        if u.path == "/api/backtest":
            q = parse_qs(u.query)
            sym = (q.get("symbol", [""])[0]).strip()
            style = (q.get("style", ["day"])[0]).strip()
            grades = (q.get("grades", ["A+,A,B"])[0]).strip()
            side = (q.get("side", ["both"])[0]).strip() or "both"
            # tfs دلخواهِ کاربر (فرکتالی): "4h,1h,15m,5m" — بر style اولویت دارد
            tfs_raw = (q.get("tfs", [""])[0]).strip()
            user_tfs = [t.strip() for t in tfs_raw.split(",") if t.strip()] or None
            # بازه‌ی تاریخیِ انتخابیِ کاربر روی چارت (epoch ثانیه یا رشته‌ی تاریخ)
            df_raw = (q.get("from", [""])[0]).strip()
            dt_raw = (q.get("to", [""])[0]).strip()
            try:
                walk = int(q.get("walk", ["2000"])[0])
            except Exception:
                walk = 2000
            if not sym:
                return self._send(400, json.dumps({"error": "نماد وارد نشده"}, ensure_ascii=False))
            if BT is None:
                return self._send(200, json.dumps({"error": "موتورِ بک‌تست در دسترس نیست"}, ensure_ascii=False))
            try:
                gr = tuple(g.strip() for g in grades.split(",") if g.strip())
                if side not in ("both", "long", "short"):
                    side = "both"
                try:
                    date_from = BT._parse_when(df_raw) if df_raw else None
                    date_to = BT._parse_when(dt_raw) if dt_raw else None
                except ValueError as ex:
                    return self._send(200, json.dumps({"error": str(ex)}, ensure_ascii=False))
                res = BT.backtest(sym.upper(), style=style, grades=gr,
                                  walk=walk, fill_window=48, max_hold=400,
                                  side=side, tfs=user_tfs,
                                  date_from=date_from, date_to=date_to)
                # بازتابِ تنظیماتِ به‌کاررفته برای نمایش در UI
                if isinstance(res, dict) and "error" not in res:
                    res.setdefault("side_used", side)
                    res.setdefault("tfs_used", user_tfs or BT.__dict__.get("tf_map", {}))
                    res["range_from"] = df_raw or None
                    res["range_to"] = dt_raw or None
                    # مورد ۴: اگر نمونه کم بود و کاربر تایم‌فریمِ دلخواه نداده،
                    # سبک‌های دیگر را سریع بسنج و بهترین را پیشنهاد بده.
                    try:
                        smp = res.get("sample") or {}
                        if (not smp.get("ok")) and not user_tfs and not df_raw and not dt_raw:
                            alts = [s for s in ("scalp", "day", "swing") if s != style]
                            best = None
                            for st in alts:
                                a = BT.backtest(sym.upper(), style=st, grades=gr,
                                                walk=walk, fill_window=48,
                                                max_hold=400, side=side)
                                if isinstance(a, dict) and "error" not in a \
                                        and a.get("trades", 0) >= 5 \
                                        and a.get("expectancy_R", -9) > 0:
                                    # اولویت: بیشترین تعدادِ معامله، سپس اکسپکتنسی
                                    cand = (a["trades"], a["expectancy_R"], st)
                                    if best is None or (cand[0], cand[1]) > (best[0], best[1]):
                                        best = cand
                            if best:
                                st_fa = {"scalp": "اسکالپ", "day": "روزانه",
                                         "swing": "سوینگ", "sb_ny": "سیلوربولت نیویورک"}.get(best[2], best[2])
                                res["style_advice"] = (
                                    f"سبکِ «{style}» روی {sym.upper()} کم‌سیگنال است. "
                                    f"سبکِ «{st_fa}» برای همین نماد نمونه‌ی بهتری می‌دهد "
                                    f"({best[0]} معامله، اکسپکتنسی {best[1]}R) — امتحانش کن.")
                    except Exception:
                        pass
                return self._send(200, json.dumps(res, ensure_ascii=False))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False))

        if u.path == "/api/suggest-range":
            # بر اساسِ عمقِ walk و دیتای در دسترس، بازه‌ی پیشنهادیِ معتبر بده
            q = parse_qs(u.query)
            sym = (q.get("symbol", [""])[0]).strip()
            style = (q.get("style", ["day"])[0]).strip()
            tfs_raw = (q.get("tfs", [""])[0]).strip()
            user_tfs = [t.strip() for t in tfs_raw.split(",") if t.strip()] or None
            try:
                walk = int(q.get("walk", ["600"])[0])
            except Exception:
                walk = 600
            if not sym:
                return self._send(400, json.dumps({"error": "نماد وارد نشده"}, ensure_ascii=False))
            if BT is None or not hasattr(BT, "suggest_range"):
                return self._send(200, json.dumps({"error": "موتورِ بک‌تست در دسترس نیست"}, ensure_ascii=False))
            try:
                res = BT.suggest_range(sym.upper(), style=style, tfs=user_tfs, walk=walk)
                return self._send(200, json.dumps(res, ensure_ascii=False))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False))
        if u.path == "/api/alarms":
            with _alarms_lock:
                return self._send(200, json.dumps(_load_alarms(), ensure_ascii=False))
        if u.path == "/api/screenshots":
            with _shots_lock:
                return self._send(200, json.dumps(_load_shots(), ensure_ascii=False))
        if u.path == "/api/screenshot":
            sid = (parse_qs(u.query).get("id", [""])[0])
            with _shots_lock:
                shot = next((s for s in _load_shots() if str(s.get("id")) == str(sid)), None)
            if not shot:
                return self._send(404, json.dumps({"error": "not found"}))
            fp = os.path.join(SHOTS_DIR, shot["file"])
            if not os.path.isfile(fp):
                return self._send(404, json.dumps({"error": "file missing"}))
            try:
                with open(fp, "rb") as f:
                    data = f.read()
                return self._send(200, data, shot.get("ctype", "image/png"))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)}))
        # 🩺 سلامتِ اپ: سینتکس + قراردادِ «هیچ کلیدی گم نشود» + وجودِ اسنپ‌شات
        if u.path == "/api/selfcheck":
            try:
                import selfcheck as SC
                _root = os.path.dirname(os.path.abspath(__file__))
                rep = SC.run_checks(_root)
                rep["snapshot_available"] = os.path.isdir(SC.GOOD)
                rep["log"] = SC.LOG
            except Exception as e:
                rep = {"ok": False, "problems": [f"selfcheck در دسترس نیست: {e}"]}
            return self._send(200, json.dumps(rep, ensure_ascii=False))
        # PWA: مانیفست، سرویس‌ورکر و آیکون‌ها — از روی دیسک، بدونِ وابستگیِ بیرونی
        if u.path in ("/manifest.webmanifest", "/sw.js", "/icon-180.png",
                      "/icon-192.png", "/icon-192-mask.png",
                      "/icon-512.png", "/icon-512-mask.png"):
            ext = os.path.splitext(u.path)[1]
            wctype = {".webmanifest": "application/manifest+json; charset=utf-8",
                      ".js": "application/javascript; charset=utf-8",
                      ".png": "image/png"}.get(ext, "application/octet-stream")
            fp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              os.path.basename(u.path))
            if os.path.isfile(fp):
                try:
                    with open(fp, "rb") as f:
                        return self._send(200, f.read(), wctype)
                except Exception as e:
                    return self._send(500, json.dumps({"error": str(e)}))
            return self._send(404, json.dumps({"error": "not found"}))
        # آرشیوِ اخبارِ اعلام‌شده‌ی N ساعتِ گذشته (پیش‌فرض ۶ ساعت)
        if u.path == "/api/fundamental-archive":
            if FUND is None:
                return self._send(200, json.dumps(
                    {"error": "موتورِ فاندمنتال در دسترس نیست"}, ensure_ascii=False))
            try:
                hours = abs(int(parse_qs(u.query).get("hours", ["6"])[0]))
            except Exception:
                hours = 6
            try:
                if hasattr(FUND, "archive"):
                    res = FUND.archive(hours=hours)
                else:
                    res = {"ok": False, "error": "archive در موتورِ فاندمنتال نیست", "events": []}
                return self._send(200, json.dumps(res, ensure_ascii=False))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False))
        return self._send(404, json.dumps({"error": "not found"}))

    def do_DELETE(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if _ACCESS_TOKEN and not _check_auth(self, qs):
            return self._send(401, json.dumps({"error": "دسترسی لازم است"}, ensure_ascii=False))
        if u.path == "/api/alarm":
            aid = (parse_qs(u.query).get("id", [""])[0])
            with _alarms_lock:
                alarms = [a for a in _load_alarms() if str(a.get("id")) != str(aid)]
                _save_alarms(alarms)
            return self._send(200, json.dumps({"deleted": aid}))
        if u.path == "/api/screenshot":
            sid = (parse_qs(u.query).get("id", [""])[0])
            with _shots_lock:
                shots = _load_shots()
                gone = next((s for s in shots if str(s.get("id")) == str(sid)), None)
                shots = [s for s in shots if str(s.get("id")) != str(sid)]
                _save_shots(shots)
            if gone:
                try:
                    os.remove(os.path.join(SHOTS_DIR, gone["file"]))
                except Exception:
                    pass
            return self._send(200, json.dumps({"deleted": sid}))
        return self._send(404, json.dumps({"error": "not found"}))


    def _handle_upload(self):
        """آپلودِ اسکرین‌شات به‌صورتِ JSON: {symbol, note, dataurl}
        که dataurl یک data:image/...;base64,... است. فقط stdlib."""
        import base64, re as _re
        try:
            ln = int(self.headers.get("Content-Length", 0))
            if ln <= 0:
                return self._send(200, json.dumps({"error": "بدنه خالی است"}, ensure_ascii=False))
            if ln > _MAX_UPLOAD + 200000:
                return self._send(200, json.dumps({"error": "فایل خیلی بزرگ است (سقف ۱۲ مگابایت)"}, ensure_ascii=False))
            body = self.rfile.read(ln)
            d = json.loads(body.decode("utf-8"))
            dataurl = d.get("dataurl", "")
            m = _re.match(r"data:image/(png|jpe?g|webp|gif);base64,(.+)$", dataurl, _re.S)
            if not m:
                return self._send(200, json.dumps({"error": "فرمتِ تصویر نامعتبر است (فقط png/jpg/webp/gif)"}, ensure_ascii=False))
            ext = m.group(1).lower()
            ext = "jpg" if ext in ("jpeg", "jpg") else ext
            raw = base64.b64decode(m.group(2))
            if len(raw) > _MAX_UPLOAD:
                return self._send(200, json.dumps({"error": "فایل خیلی بزرگ است (سقف ۱۲ مگابایت)"}, ensure_ascii=False))
            os.makedirs(SHOTS_DIR, exist_ok=True)
            sid = str(int(time.time() * 1000))
            fname = f"{sid}.{ext}"
            with open(os.path.join(SHOTS_DIR, fname), "wb") as f:
                f.write(raw)
            shot = {
                "id": sid,
                "file": fname,
                "ctype": _ALLOWED_IMG.get(ext, "image/png"),
                "symbol": str(d.get("symbol", "")).strip().upper(),
                "note": str(d.get("note", "")).strip()[:500],
                "size": len(raw),
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with _shots_lock:
                shots = _load_shots()
                shots.insert(0, shot)
                _save_shots(shots)
            return self._send(200, json.dumps({"added": sid, "file": fname}, ensure_ascii=False))
        except Exception as e:
            traceback.print_exc()
            return self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False))

    def do_POST(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if _ACCESS_TOKEN and u.path != "/api/health" and not _check_auth(self, qs):
            return self._send(401, json.dumps({"error": "برای نوشتن باید وارد شوی: صفحه را با توکن باز کن"},
                                              ensure_ascii=False))
        # ذخیره‌ی تنظیماتِ ریسک (سرمایه/درصد/سقف‌ها) — تا در دفترِ ریسک بماند و
        # بعد از هر ری‌استارتِ خودکارِ اپ دوباره از دست نرود.
        if u.path == "/api/risk":
            try:
                if RK is None:
                    return self._send(200, json.dumps(
                        {"error": "ماژولِ ریسک بار نشد"}, ensure_ascii=False))
                ln = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(ln) if ln else b"{}"
                d = json.loads(body.decode("utf-8"))
                cur = RK.load_settings()
                for k in ("balance", "risk_pct", "daily_loss_limit_pct",
                          "max_open_risk_pct"):
                    if d.get(k) is not None and str(d.get(k)).strip() != "":
                        cur[k] = d[k]
                if d.get("account_ccy"):
                    cur["account_ccy"] = str(d["account_ccy"]).upper()[:3]
                if isinstance(d.get("usd_per_quote"), dict):
                    cur["usd_per_quote"] = dict(cur.get("usd_per_quote") or {}, **d["usd_per_quote"])
                RK.save_settings(cur)
                st = RK.load_settings()
                rows = _journal_rows(_JR_FILE) or []
                return self._send(200, json.dumps({
                    "ok": True, "settings": st,
                    "daily": RK.daily_state(rows, st),
                    "settings_file": RK.settings_path(),
                }, ensure_ascii=False))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, json.dumps(
                    {"error": str(e)}, ensure_ascii=False))
        if u.path == "/api/screenshot":
            return self._handle_upload()
        if u.path == "/api/alarm":
            try:
                ln = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(ln) if ln else b"{}"
                d = json.loads(body.decode("utf-8"))
                sym = str(d.get("symbol", "")).strip().upper()
                if not sym:
                    return self._send(200, json.dumps({"error": "نماد خالی است"}, ensure_ascii=False))
                mode = d.get("mode", "ote")
                alarm = {
                    "id": str(int(time.time() * 1000)),
                    "symbol": sym,
                    "mode": mode,
                    "direction": d.get("direction"),
                    "style": d.get("style", "day"),
                    "active": True,
                    "triggered": False,
                    "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "last_price": None,
                }
                if mode == "ote":
                    alarm["low"] = d.get("low")
                    alarm["high"] = d.get("high")
                    if alarm["low"] is None or alarm["high"] is None:
                        return self._send(200, json.dumps({"error": "محدوده‌ی OTE نامعتبر است"}, ensure_ascii=False))
                elif mode == "price":
                    alarm["target"] = d.get("target")
                    alarm["cross"] = d.get("cross", "any")
                with _alarms_lock:
                    alarms = _load_alarms()
                    alarms.append(alarm)
                    _save_alarms(alarms)
                return self._send(200, json.dumps({"added": alarm["id"], "symbol": sym}, ensure_ascii=False))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False))
        if u.path != "/api/journal":
            return self._send(404, json.dumps({"error": "not found"}))
        try:
            ln = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(ln) if ln else b"{}"
            d = json.loads(body.decode("utf-8"))
            p = d.get("plan") or {}
            if not p:
                return self._send(200, json.dumps(
                    {"error": "پلنی برای ثبت نیست"}, ensure_ascii=False))
            # ساختِ آرگومان‌ها مثل namespace برای journal.cmd_add
            bias = d.get("bias_by_tf") or {}
            bias_txt = " · ".join(f"{k}={v}" for k, v in bias.items())
            tfs = d.get("timeframes") or []
            kz = d.get("killzone") or ""
            ns = argparse.Namespace(
                file=_JR_FILE,
                symbol=str(d.get("symbol", "")),
                direction="long" if "صعود" in str(p.get("direction", "")) else "short",
                session=kz,
                tf=str(d.get("entry_tf", "")),
                htf_bias=bias_txt,
                entry=str(p.get("entry", "")),
                sl=str(p.get("sl", "")),
                tp=str(p.get("tp", "")),
                rr=str(p.get("rr", "")),
                risk_pct=str((_risk_settings().get("risk_pct", 1.0))),
                setup=f"{d.get('style','')} · درجه {d.get('grade','')} · "
                      f"امتیاز {d.get('score','')}/{d.get('max_score','')}",
                poi=(p.get("poi") or ""),
                reason=(d.get("verdict") or "")[:300],
                status="open",
                result=None, exit=None, realized_r=None,
                mistake=None, lesson=None, notes="ثبت‌شده از اپلیکیشن pipfound",
                datetime=None,
            )
            import io
            buf = io.StringIO()
            old = sys.stdout
            sys.stdout = buf
            try:
                _JR.cmd_add(ns)
            finally:
                sys.stdout = old
            out = json.loads(buf.getvalue().strip() or "{}")
            return self._send(200, json.dumps(out, ensure_ascii=False))
        except Exception as e:
            traceback.print_exc()
            return self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False))


def main():
    global _ACCESS_TOKEN, _TLS_CERT, _TLS_KEY, _TLS_PORT, lan_open, CURRENT_PORT
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PIPFOUND_PORT", "8787")))
    ap.add_argument("--host", default=os.environ.get("PIPFOUND_HOST", "127.0.0.1"),
                    help="127.0.0.1 = فقط همین دستگاه · 0.0.0.0 = باز برای LAN (برای نصب روی موبایل/دستگاه‌های دیگر)")
    ap.add_argument("--no-autorestart", action="store_true",
                    help="ری‌استارتِ خودکارِ «کدِ کهنه» را خاموش کن (پیش‌فرض: روشن)")
    ap.add_argument("--lan", action="store_true",
                    help="میان‌برِ میزبانیِ شبکه‌ی خانگی: host=0.0.0.0 + HTTPSِ خودگواهی‌شده + توکنِ دسترسی (اگر PIPFOUND_TOKEN ست نباشد یکی می‌سازد)")
    ap.add_argument("--token", default=os.environ.get("PIPFOUND_TOKEN", ""),
                    help="توکنِ دسترسی برای میزبانیِ LAN (بدونِ توکن، هر دستگاهِ داخلِ شبکه می‌تواند همه‌چیز را ببیند و ژورنال را بنویسد)")
    a = ap.parse_args()
    if a.lan:
        a.host = "0.0.0.0"
        if not a.token:
            import secrets
            a.token = secrets.token_urlsafe(12)
    _ACCESS_TOKEN = a.token
    CURRENT_PORT = a.port
    lan_open = (a.host == "0.0.0.0")
    if a.no_autorestart:
        _REV_WATCH["enabled"] = False
    # بدونِ -u خروجیِ ریدایرکتشده به فایل بافر می‌شود و لاگ‌ها (از جمله خطِ
    # ری‌استارت) دیر یا هرگز نمی‌رسند. پس خودِ اپ خط‌بافر می‌کند.
    try:
        if not sys.stdout.isatty():
            sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    # 🩺 نگهبانِ سلامتِ کد — پیش از سرو کردنِ صفحه
    _root = os.path.dirname(os.path.abspath(__file__))
    try:
        import selfcheck as SC
        _rep = SC.run_checks(_root)
        if _rep.get("ok"):
            SC.save_snapshot(_root, _rep)
            print("🩺 سلامتِ کد: ✅ تأیید شد (سینتکس + کلیدها)")
        else:
            print("🩺 سلامتِ کد: ❌ " + " | ".join(_rep.get("problems") or [])[:300])
            _healed = SC.guard(_root)
            if _healed.get("ok"):
                print("♻️ نسخه‌ی سالمِ قبلی برگردانده شد — سرور را دوباره اجرا کن (pipfound.app).")
            else:
                print("   ترمیمِ خودکار نتیجه نداد. بررسی: python3 selfcheck.py")
            return 2
    except Exception as _e:
        print(f"🩺 سلامتِ کد: بررسی نشد ({_e})")

    _moved = f" (+{_JR_MOVED} ردیفِ قدیمی)" if _JR_MOVED else ""
    print(f"   📓 دفترِ معاملات: {_JR_FILE}{_moved}  [{_JR_IMPL}]")
    if _REV_WATCH["enabled"]:
        threading.Thread(target=_rev_watch_worker, daemon=True).start()
        print("   ♻️ ری‌استارتِ خودکارِ کهنه: روشن (بررسیِ هر %.0f ثانیه، بدونِ قطعِ درخواستِ در جریان)"
              % _REV_WATCH["interval"])
    else:
        print("   ♻️ ری‌استارتِ خودکارِ کهنه: خاموش")
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://{a.host}:{a.port}"
    # حالتِ LAN: HTTPSِ خودگواهی‌شده برای نصبِ PWA (سافاریِ iOS فقط روی https نصب می‌کند)
    if a.lan:
        try:
            import ssl as _ssl
            _TLS_CERT, _TLS_KEY = _make_self_signed_cert()
            _TLS_PORT = a.port
            ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(_TLS_CERT, _TLS_KEY)
            srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
            url = f"https://{a.host}:{a.port}  (گواهیِ خودگواهی‌شده — اولین باز، هشدارِ مرورگر را بپذیر)"
            # بوت‌استرپ: یک پورتِ HTTPِ محلی برای «راه‌اندازیِ اولیه» — توکن را بدونِ
            # قبولِ گواهی می‌شود وارد کرد، بعد بقیه از HTTPS می‌رود.
            try:
                bs = ThreadingHTTPServer(("127.0.0.1", a.port + 1), Handler)
                threading.Thread(target=bs.serve_forever, daemon=True).start()
                print(f"   🚪 ورودِ آسان: http://127.0.0.1:{a.port + 1}  (فقط همین دستگاه — بعد از ورود، آدرسِ https را به دستگاه‌های دیگر بده)")
            except OSError:
                pass
        except FileNotFoundError:
            print("⚠️ openssl پیدا نشد — بدونِ HTTPS ادامه می‌دهم (نصب روی سافاریِ iOS کار نمی‌کند)")
            _TLS_PORT = None
        except Exception as e:
            print(f"⚠️ HTTPS برپا نشد ({e}) — بدونِ TLS ادامه می‌دهم")
            _TLS_PORT = None
    start_alarm_worker()
    start_fund_alarm_worker()
    print(f"✅ pipfound روی {url} بالا آمد.")
    if a.lan:
        info = _install_info()
        print("   📲 نصب روی دستگاه‌های دیگر (همان Wi-Fi):")
        for ip in (info["lan"]["addresses"] or ["<ip-of-this-mac>"]):
            print(f"        {info['lan']['scheme']}://{ip}:{_TLS_PORT or a.port}")
        print(f"   🔑 توکنِ دسترسی: {a.token}")
        print("      (در هر دستگاه یک بار با ?token=… باز کن؛ بعد از آن کوکی به یاد می‌سپارد)")
    print("   نمادها: XAUUSD, XAGUSD, EURUSD, BTCUSDT, ... — Ctrl+C برای توقف.")
    print("   🔔 موتورِ آلارم فعال شد (بررسیِ هر ۹۰ ثانیه).")
    print("   📰 آلارمِ فاندمنتال فعال شد (هشدارِ ~۲۴ ساعت پیش از هر خبرِ پرتأثیر).")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 خاموش شد.")
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main() or 0)
