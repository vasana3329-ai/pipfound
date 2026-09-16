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
import sys, os, json, argparse, traceback, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HOME = os.path.expanduser("~")
ALARMS_FILE = os.path.join(HOME, "pipfound", "alarms.json")
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


def _journal_fields():
    return list(getattr(J, "FIELDS", None) or ["id", "datetime", "symbol", "direction"])


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

# نمادهای پیشنهادی برای اتوکامپلیت
SUGGESTIONS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF",
    "EURJPY", "GBPJPY", "EURGBP", "AUDJPY",
    "XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD", "WTI", "BRENT",
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
]


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
    r["is_sb_mode"] = (style == "sb_ny")
    return r


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
    """قیمتِ زنده‌ی نماد را از موتور می‌گیرد (آخرین کندلِ ۵m)."""
    try:
        src, sym, disp, bars = E.fetch(symbol.strip().upper(), "5m", 3)
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
.chips{display:flex;gap:7px;flex-wrap:wrap;margin-top:14px}
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
.spin{display:inline-block;width:18px;height:18px;border:3px solid var(--line);border-top-color:var(--accent);
  border-radius:50%;animation:sp .7s linear infinite;vertical-align:-4px;margin-left:8px}
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
.rf-btn:disabled,.ab-btn:disabled{opacity:.5;cursor:default}
.rf-btn .rf-ico{display:inline-block}
.rf-btn.spin .rf-ico{animation:rfspin .9s linear infinite}
.rf-btn.ok{border-color:var(--good);color:var(--good)}
@keyframes rfspin{to{transform:rotate(360deg)}}
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
  </div>

  <div class="card">
    <div class="searchrow">
      <input id="sym" class="inp" placeholder="نامِ نماد را بنویس… مثل XAUUSD یا BTCUSDT یا EURUSD"
             title="نامِ نماد را این‌جا بنویس (XAUUSD, EURUSD, BTCUSDT …). با انتخاب/تایپِ نماد، سبک و دکمه‌ی تحلیل چشمک می‌زنند؛ هیچ‌چیز خودکار اجرا نمی‌شود."
             list="syms" autocomplete="off" autofocus>
      <datalist id="syms"></datalist>
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
      <button id="refreshBtn" class="rf-btn" title="همان نمادِ آخرین تحلیل را دوباره با دیتای زنده می‌گیرد — بدونِ رفرشِ کلِ صفحه. تا اولین تحلیل غیرفعال است."><span class="rf-ico">↻</span> بروزرسانی</button>
      <button id="archiveBtn" class="ab-btn" title="اخبارِ اقتصادیِ پرتأثیرِ ۶ ساعتِ گذشته — هر خبر با ارز، ساعتِ اعلام و جهتِ موردانتظارش روی جفت‌ارزها و طلا/نقره؛ در همین صفحه به‌شکلِ پنجره باز می‌شود.">📁 آرشیو اقتصادی</button>
    </div>
    <div id="setupsPanel" class="setups-panel">
      <div class="sp-head">📚 سه ستاپِ پیشنهادی <span class="jmsg" id="spState">— اول یک تحلیل بگیر تا چراغ‌ها روشن شوند</span></div>
      <div id="spList"></div>
    </div>
    <div class="chips" id="chips"></div>
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
let style = "day";

const $ = s => document.querySelector(s);
const symIn = $("#sym"), goBtn = $("#go"), res = $("#result");

// datalist + chips
const dl = $("#syms");
SUGGESTIONS.forEach(s=>{const o=document.createElement("option");o.value=s;dl.appendChild(o);});
const chips = $("#chips");
["XAUUSD","XAGUSD","EURUSD","GBPUSD","AUDUSD","USDJPY","BTCUSDT","ETHUSDT"].forEach(s=>{
  const c=document.createElement("span");c.className="chip";c.textContent=s;
  // فقط نماد را پُر کن؛ اجرا نکن. کاربر اول سبک و بازه را انتخاب می‌کند.
  c.onclick=()=>{ symIn.value=s; symIn.focus(); markReady(); };
  chips.appendChild(c);
});

// وقتی نمادی انتخاب/تایپ شد، کاربر را به انتخابِ سبک/بازه هدایت کن (بدونِ اجرای خودکار)
function markReady(){
  const has = symIn.value.trim().length>0;
  $("#styles").classList.toggle("awaiting", has);
  goBtn.classList.toggle("pulse", has);
}
symIn.addEventListener("input", markReady);

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

// دکمه‌ی ↻ بروزرسانی — همان تحلیلِ آخر را با دیتای تازه دوباره می‌گیرد (بدونِ رفرشِ صفحه)
const refreshBtn=document.getElementById("refreshBtn");
if(refreshBtn){
  refreshBtn.disabled=true;
  refreshBtn.onclick=async ()=>{
    const sym=(window._last&&window._last.symbol)||symIn.value.trim();
    if(!sym){ symIn.focus(); return; }
    symIn.value=sym;
    refreshBtn.disabled=true; refreshBtn.classList.add("spin");
    try{
      await run();
      refreshBtn.classList.add("ok");
      setTimeout(()=>refreshBtn.classList.remove("ok"), 1600);
    }finally{
      refreshBtn.classList.remove("spin"); refreshBtn.disabled=false;
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

  let planHtml="";
  if(d.plan){
    const p=d.plan;
    const et = p.entry_type==="market"
      ? `<span class="badge g-green">ورودِ بازار (الان)</span>`
      : `<span class="badge g-amber">لیمیت در OTE — منتظرِ پولبک</span>`;
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
      <span class="price">قیمت: ${fmt(d.last_price)}</span>
      <div class="spacer"></div>
      <div class="grade" style="background:${gradeColor(d.grade)}">${d.grade}</div>
    </div>
    <div class="metaline">
      <span>سبک: <b>${d.style}</b></span>
      <span>تایم‌فریم‌ها: <b>${(d.timeframes||[]).join(" ، ")}</b></span>
      ${biasStrip?`<span>بایاس: <b>${biasStrip}</b></span>`:""}
    </div>
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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # سکوت

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
        if u.path in ("/", "/index.html"):
            tvmap = {
                "BTCUSDT": "BINANCE:BTCUSDT", "ETHUSDT": "BINANCE:ETHUSDT",
                "SOLUSDT": "BINANCE:SOLUSDT", "BNBUSDT": "BINANCE:BNBUSDT",
                "XRPUSDT": "BINANCE:XRPUSDT", "DOGEUSDT": "BINANCE:DOGEUSDT",
                "XAUUSD": "OANDA:XAUUSD", "XAGUSD": "OANDA:XAGUSD",
                "XPTUSD": "OANDA:XPTUSD", "XPDUSD": "OANDA:XPDUSD",
                "GOLD": "OANDA:XAUUSD", "WTI": "TVC:USOIL", "BRENT": "TVC:UKOIL",
            }
            page = (HTML
                    .replace("__SUGGESTIONS__", json.dumps(SUGGESTIONS))
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
                return self._send(200, json.dumps(r, ensure_ascii=False))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False))
        if u.path == "/api/health":
            return self._send(200, json.dumps({"ok": True}))
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
        if J is None:
            return self._send(200, json.dumps(
                {"error": "ماژولِ ژورنال یافت نشد"}, ensure_ascii=False))
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
                risk_pct="1",
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
                J.cmd_add(ns)
            finally:
                sys.stdout = old
            out = json.loads(buf.getvalue().strip() or "{}")
            return self._send(200, json.dumps(out, ensure_ascii=False))
        except Exception as e:
            traceback.print_exc()
            return self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()

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
    print(f"   📓 دفترِ معاملات: {_JR_FILE}{_moved}")
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://{a.host}:{a.port}"
    start_alarm_worker()
    start_fund_alarm_worker()
    print(f"✅ pipfound روی {url} بالا آمد.")
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
