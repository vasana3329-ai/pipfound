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

# ماژولِ ژورنال از پوشه‌ی همسایه‌ی trade-journal
_JRN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "trade-journal", "scripts")
sys.path.insert(0, _JRN_DIR)
try:
    import journal as J
except Exception:
    J = None

# سبکِ معامله → تایم‌فریم‌ها (HTF اول). engine از این‌ها پشتیبانی می‌کند:
# 1m 5m 15m 30m 1h 4h 1d 1w
STYLES = {
    "scalp": {"label": "اسکالپ",   "tfs": ["1h", "30m", "15m", "5m"],  "entry_tf": "5m"},
    "day":   {"label": "روزانه",    "tfs": ["1d", "4h", "1h", "15m"],   "entry_tf": "15m"},
    "swing": {"label": "سوینگ",     "tfs": ["1w", "1d", "4h", "1h"],    "entry_tf": "1h"},
}

# نمادهای پیشنهادی برای اتوکامپلیت
SUGGESTIONS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF",
    "EURJPY", "GBPJPY", "EURGBP", "AUDJPY",
    "XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD", "WTI", "BRENT",
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
]


def analyze(symbol, style):
    """اجرای اسکنر برای یک نماد + سبک و برگرداندنِ دیکشنریِ کامل."""
    sty = STYLES.get(style, STYLES["day"])
    tfs = sty["tfs"]
    r = C.score(symbol.strip().upper(), tfs)
    r["style"] = sty["label"]
    r["style_key"] = style if style in STYLES else "day"
    r["entry_tf"] = sty["entry_tf"]
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


HTML = r"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pipfound — تحلیلگرِ اسمارت‌مانی (SMC / ICT)</title>
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
.logo{width:42px;height:42px;border-radius:12px;background:linear-gradient(135deg,var(--accent),var(--accent2));
  display:grid;place-items:center;font-size:22px;box-shadow:0 6px 22px rgba(77,163,255,.35)}
h1{font-size:22px;margin:0;font-weight:700;letter-spacing:.2px}
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
.verdict{margin-top:16px;background:rgba(77,163,255,.08);border-right:3px solid var(--accent);
  padding:12px 14px;border-radius:8px;font-size:14px;line-height:1.7}
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
.tv-box{border-radius:12px;overflow:hidden;border:1px solid var(--line);height:420px;background:var(--panel2)}
.tv-box iframe{width:100%;height:100%;border:0;display:block}
.tv-hint{color:var(--muted);font-size:12px;margin-top:8px}
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
    <div class="logo">📈</div>
    <div>
      <h1>pipfound</h1>
      <div class="sub">تحلیلگرِ اسمارت‌مانی · SMC + ICT · تاپ‌داون · دیتای زنده · فارکس / فلزات / کریپتو</div>
    </div>
  </div>

  <div class="card">
    <div class="searchrow">
      <input id="sym" class="inp" placeholder="نامِ نماد را بنویس… مثل XAUUSD یا BTCUSDT یا EURUSD"
             list="syms" autocomplete="off" autofocus>
      <datalist id="syms"></datalist>
      <div class="styles" id="styles">
        <button data-k="scalp">اسکالپ</button>
        <button data-k="day" class="active">روزانه</button>
        <button data-k="swing">سوینگ</button>
      </div>
      <button id="go" class="go">تحلیل کن</button>
      <button id="bt" class="go" style="background:#334155">بک‌تست</button>
    </div>
    <div class="chips" id="chips"></div>

    <!-- پنلِ تنظیماتِ بک‌تست: کاربر خودش محدوده/تایم‌فریم/جهت را انتخاب می‌کند -->
    <div id="btPanel" class="btpanel">
      <div class="btrow">
        <span class="btlbl">بازه‌ی بک‌تست (تاریخِ روی چارت):</span>
        <input id="btFrom" class="btinp" type="text" placeholder="از — مثل 2026-06-01" autocomplete="off">
        <input id="btTo" class="btinp" type="text" placeholder="تا — مثل 2026-08-13" autocomplete="off">
        <span class="bthint">خالی = خودکار (کندل‌های اخیر)</span>
      </div>
      <div class="btrow">
        <span class="btlbl">تایم‌فریمِ دلخواه (فرکتالی):</span>
        <input id="btTfs" class="btinp wide" type="text" placeholder="مثلاً 4h,1h,15m,5m — خالی = طبقِ سبک">
        <span class="bthint">اولی = بایاسِ بالا، آخری = ورود</span>
      </div>
      <div class="btrow">
        <span class="btlbl">جهتِ مجاز:</span>
        <div class="sideseg" id="btSide">
          <button data-s="both" class="active">هر دو</button>
          <button data-s="long">فقط خرید</button>
          <button data-s="short">فقط فروش</button>
        </div>
        <span class="btlbl" style="margin-inline-start:14px">عمقِ پیمایش:</span>
        <input id="btWalk" class="btinp narrow" type="number" min="100" max="8000" step="100" value="600">
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
      <div class="aempty" style="padding:40px">یک نماد را تحلیل کن یا از دکمه‌های میان‌بر انتخاب کن تا چارتِ زنده‌اش این‌جا بیاید.</div>
    </div>
    <div class="tv-hint">چارتِ زنده از TradingView (فقط برای دیدن؛ امتیاز و پلن از دیتای مستقلِ اپ می‌آید).</div>
  </div>

  <div class="livewrap">
    <h2>🖼️ اسکرین‌شاتِ چارت <span class="jmsg">(آپلود برای بایگانی و مرور)</span></h2>
    <div class="uprow">
      <input type="file" id="shotFile" accept="image/png,image/jpeg,image/webp,image/gif" style="display:none">
      <button class="upbtn" id="shotPick">📤 انتخابِ تصویر</button>
      <input class="upnote" id="shotNote" placeholder="یادداشت (اختیاری) — مثلاً «سوئیپِ لو + چاک روی ۱h»">
      <span id="shotMsg" class="jmsg"></span>
    </div>
    <div class="shotgrid" id="shotGrid"></div>
  </div>

  <div class="lightbox" id="lightbox"><img id="lightboxImg" src="" alt=""></div>

  <div class="foot">
    داده: Binance (کریپتو) + Yahoo (فارکس/فلزات) — رایگان، بدون کلید · تقویمِ اقتصادی: ForexFactory<br>
    ⚠️ ابزارِ کمکی است، نه سیگنالِ تضمینی. تصمیمِ نهایی و مدیریتِ ریسک با خودت.
  </div>
</div>

<script>
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
  c.onclick=()=>{symIn.value=s;run();};chips.appendChild(c);
});

// style toggle
$("#styles").addEventListener("click",e=>{
  const b=e.target.closest("button");if(!b)return;
  document.querySelectorAll("#styles button").forEach(x=>x.classList.remove("active"));
  b.classList.add("active");style=b.dataset.k;
  if(symIn.value.trim())run();
});

goBtn.onclick=run;
symIn.addEventListener("keydown",e=>{if(e.key==="Enter")run();});

const btBtn = $("#bt"), btRes = $("#btresult");
btBtn.onclick = runBacktest;

// جهتِ مجاز (both/long/short)
let btSide = "both";
$("#btSide").addEventListener("click", e=>{
  const b=e.target.closest("button"); if(!b) return;
  document.querySelectorAll("#btSide button").forEach(x=>x.classList.remove("active"));
  b.classList.add("active"); btSide=b.dataset.s;
});

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
  btRes.innerHTML=`
  <div class="plan" style="margin-top:14px">
    <h3>🔬 نتیجه‌ی بک‌تست — ${d.symbol} · سبک ${d.style} · ${(d.timeframes||[]).join(" ")}</h3>
    <p style="color:var(--muted);font-size:13px;margin:4px 0 4px">
      این وین‌ریت از همان منطقِ ورودی‌ای می‌آید که اپ الان زنده پیشنهاد می‌دهد
      (walk-forward، بدونِ نگاه به آینده). سیگنال‌های هم‌پوشان حذف شده‌اند.</p>
    <p style="color:var(--muted);font-size:12px;margin:0 0 12px">🎯 ${sideTxt} · 📅 ${rangeTxt}</p>
    <div class="pgrid">
      <div class="pcell"><span>تعدادِ معاملات</span><b>${d.trades}</b></div>
      <div class="pcell"><span>برد / باخت</span><b>${d.wins} / ${d.losses}</b></div>
      <div class="pcell"><span>وین‌ریت</span><b style="color:${wrColor}">${wr}٪</b></div>
      <div class="pcell"><span>مجموعِ R</span><b>${d.total_R>0?"+":""}${d.total_R}</b></div>
      <div class="pcell"><span>میانگینِ R</span><b>${d.avg_R_per_trade}</b></div>
      <div class="pcell"><span>اکسپکتنسی</span><b style="color:${expColor}">${d.expectancy_R}R</b></div>
    </div>
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
    planHtml=`<div class="plan">
      <h3>📌 پلنِ پیشنهادی — تایم‌فریمِ ورود: <b>${d.entry_tf}</b> · سبک: ${d.style} &nbsp; ${et}</h3>
      <div class="pgrid">
        <div class="pcell"><div class="k">جهت</div><div class="v">${p.direction}</div></div>
        <div class="pcell"><div class="k">ورود</div><div class="v">${fmt(p.entry)}</div></div>
        <div class="pcell"><div class="k">حدِ ضرر</div><div class="v">${fmt(p.sl)}</div></div>
        <div class="pcell rr"><div class="k">ریسک به ریوارد</div><div class="v">۱:${p.rr}</div></div>
      </div>
      <div class="pgrid" style="margin-top:10px">
        <div class="pcell"><div class="k">هدف (حدِ سود)</div><div class="v">${fmt(p.tp)}</div></div>
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
      <button class="alarm-btn" id="alarmBtn">🔔 آلارم روی این ناحیه بگذار</button>
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
    ${oteHtml}
    <div style="margin-top:14px">${badges}</div>
    ${upcoming}
    <div class="verdict">${d.verdict||""}</div>
    <div class="jrnrow">
      <button id="jbtn" class="jbtn" ${d.plan?"":"disabled"}>💾 ثبت در ژورنال</button>
      <span id="jmsg" class="jmsg"></span>
    </div>
  </div>`;
  window._last = d;
  const jb = document.getElementById("jbtn");
  if(jb) jb.onclick = saveJournal;
  const ab = document.getElementById("alarmBtn");
  if(ab) ab.onclick = setOteAlarm;
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
          <br><button class="sdel" data-id="${s.id}">حذف</button></div>
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
        <button class="adel" data-id="${a.id}">حذف</button>
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
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # سکوت

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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
                walk = int(q.get("walk", ["600"])[0])
            except Exception:
                walk = 600
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
                file=os.path.join(HOME, "pipfound", "journal.csv"),
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
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://{a.host}:{a.port}"
    start_alarm_worker()
    print(f"✅ pipfound روی {url} بالا آمد.")
    print("   نمادها: XAUUSD, XAGUSD, EURUSD, BTCUSDT, ... — Ctrl+C برای توقف.")
    print("   🔔 موتورِ آلارم فعال شد (بررسیِ هر ۹۰ ثانیه).")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 خاموش شد.")
        srv.shutdown()


if __name__ == "__main__":
    main()
