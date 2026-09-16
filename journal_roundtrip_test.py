#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تستِ رفت‌وبرگشتِ ژورنال — تا رفتارِ «مسیرِ دفتر» بی‌صدا نشکند.

چه چیزی را ثابت می‌کند (همه با پایتونِ stdlib و بدونِ دست‌زدن به دفترِ واقعیِ کاربر):
  ۱) ثبتِ معامله از راهِ HTTP (`POST /api/journal`) و **خواندنِ** ردیف از فایلِ CSV،
     شاملِ افزایشِ درستِ شناسه در ثبتِ دوم.
  ۲) `PIPFOUND_JOURNAL_CSV` (فایلِ دقیق) و `PIPFOUND_JOURNAL_DIR` (پوشه، اگر نباشد ساخته شود).
  ۳) با env صریح، هیچ مهاجرتی از دفترِ قدیمی انجام نشود.
  ۴) بدونِ env: ردیفِ دفترِ قدیمی (`~/Desktop/trading-journal/journal.csv`) به دفترِ اپ
     منتقل شود، فایلِ قدیمی **دست‌نخورده** بماند، و اجرای دوباره تکرارپذیر باشد.
  ۵) مسیرِ پیش‌فرض بیرونِ Desktop/Documents باشد (خانواده‌ی TCC که جابِ launchd نمی‌تواند بنویسد).

اجرا:  python3 journal_roundtrip_test.py       (خروجی: ۰ سالم، ۱ خراب)
"""
import csv
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, "app.py")
FIELDS = ["id", "datetime", "symbol", "direction", "session", "tf", "htf_bias", "entry",
          "sl", "tp", "rr", "risk_pct", "setup", "poi", "reason", "status", "result",
          "exit", "realized_r", "mistake", "lesson", "notes"]

problems = []
notes = []
procs = []


def check(ok, msg):
    if ok:
        notes.append("✓ " + msg)
    else:
        problems.append(msg)
    return ok


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_app(home, extra_env=None, port=None):
    """یک نمونه‌ی اپ را با HOME و env کنترل‌شده بالا می‌آورد و (proc, url, logpath) می‌دهد."""
    env = dict(os.environ)
    env["HOME"] = home
    env.pop("PIPFOUND_JOURNAL_CSV", None)
    env.pop("PIPFOUND_JOURNAL_DIR", None)
    if extra_env:
        env.update(extra_env)
    port = port or free_port()
    log = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
    log.close()
    fh = open(log.name, "w")
    pr = subprocess.Popen([sys.executable, "-u", APP, "--port", str(port)],
                          cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT)
    procs.append(pr)
    url = "http://127.0.0.1:%d" % port
    for _ in range(80):
        try:
            urllib.request.urlopen(url + "/api/health", timeout=2).read()
            return pr, url, log.name
        except Exception:
            if pr.poll() is not None:
                raise RuntimeError("سرور بالا نیامد:\n" + open(log.name, encoding="utf-8",
                                                               errors="replace").read()[-1200:])
            time.sleep(0.5)
    raise RuntimeError("سرور در مهلتِ مقرر بالا نیامد:\n" +
                       open(log.name, encoding="utf-8", errors="replace").read()[-1200:])


def stop(pr):
    try:
        pr.terminate()
        pr.wait(timeout=10)
    except Exception:
        try:
            pr.kill()
        except Exception:
            pass


def post_trade(url, symbol="XAUUSD", direction="صعودی"):
    payload = {
        "symbol": symbol,
        "plan": {"direction": direction, "entry": "2400", "sl": "2380", "tp": "2450",
                 "rr": "2.5", "poi": "M15 OB"},
        "bias_by_tf": {"1d": "صعودی", "4h": "نزولی"},
        "timeframes": ["4h", "15m"],
        "killzone": "NY AM",
        "style": "روزانه",
        "grade": "B",
        "score": 8,
        "max_score": 11.5,
        "verdict": "تستِ رفت‌وبرگشت",
        "entry_tf": "15m",
    }
    req = urllib.request.Request(url + "/api/journal",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if (r.get("symbol") or "").strip()]


def write_legacy(home, row=None):
    """دفترِ قدیمیِ Desktop را در HOME آزمایشی می‌سازد و محتوایش را برمی‌گرداند."""
    d = os.path.join(home, "Desktop", "trading-journal")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "journal.csv")
    data = {f: "" for f in FIELDS}
    data.update(row or {"id": "1", "datetime": "2026-08-10 18:58", "symbol": "EURUSD",
                        "direction": "long", "session": "London close", "tf": "15m",
                        "entry": "1.15344", "sl": "1.15135", "tp": "1.15807", "rr": "2.22",
                        "status": "open", "notes": "ردیفِ آزمایشیِ دفترِ قدیمی"})
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerow(data)
    return path, open(path, encoding="utf-8").read()


# ── ۱) env فایلِ صریح: ثبت + خواندن + شناسه‌ی بعدی ────────────────────────────
home1 = tempfile.mkdtemp(prefix="pfj1-")
legacy1, legacy1_before = write_legacy(home1)
ledger = os.path.join(home1, "ledger.csv")
pr, url, log1 = start_app(home1, {"PIPFOUND_JOURNAL_CSV": ledger})
try:
    out = post_trade(url)
    check(out.get("added") == "1" and out.get("symbol") == "XAUUSD",
          f"ثبتِ اول باید added=1 و symbol=XAUUSD بدهد (گرفتیم: {out})")
    check(os.path.abspath(out.get("file", "")) == os.path.abspath(ledger),
          f"فایلِ برگشتی باید همان PIPFOUND_JOURNAL_CSV باشد (گرفتیم: {out.get('file')})")
    rows = read_rows(ledger) if os.path.exists(ledger) else []
    check(len(rows) == 1, f"پس از یک ثبت باید یک ردیف در فایل باشد (شد: {len(rows)})")
    if rows:
        r = rows[0]
        check(r["symbol"] == "XAUUSD" and r["direction"] == "long",
              "ردیفِ خوانده‌شده باید XAUUSD/long باشد")
        check(r["session"] == "NY AM" and r["tf"] == "15m" and r["rr"] == "2.5",
              "کشورهای زمانی/ریسک باید همان مقادیرِ ارسالی باشند")
        check(r["status"] == "open" and "pipfound" in r["notes"],
              "وضعیتِ ردیف باید open و یادداشتش نشانِ اپ باشد")
    out2 = post_trade(url, symbol="EURUSD", direction="نزولی")
    rows2 = read_rows(ledger)
    check(out2.get("added") == "2" and len(rows2) == 2,
          f"ثبتِ دوم باید added=2 و ردیفِ دوم بسازد (گرفتیم: {out2.get('added')} / {len(rows2)})")
    check(rows2 and rows2[1]["direction"] == "short",
          "جهتِ نزولی باید short ثبت شود")
    # با env صریح، دفترِ قدیمی نباید وارد شود و مسیرِ پیش‌فرض هم ساخته نشود
    check(not os.path.exists(os.path.join(home1, "pipfound", "journal.csv")),
          "با env صریح، مسیرِ پیش‌فرض (~/pipfound/journal.csv) نباید ساخته شود")
    check(read_rows(legacy1)[0]["notes"] == "ردیفِ آزمایشیِ دفترِ قدیمی",
          "دفترِ قدیمی باید دست‌نخورده بماند")
finally:
    stop(pr)

# ── ۲) env پوشه (اگر نباشد ساخته شود) ────────────────────────────────────────
home2 = tempfile.mkdtemp(prefix="pfj2-")
jdir = os.path.join(home2, "state", "nested")
pr, url, log2 = start_app(home2, {"PIPFOUND_JOURNAL_DIR": jdir})
try:
    out = post_trade(url)
    expected = os.path.join(jdir, "journal.csv")
    check(os.path.abspath(out.get("file", "")) == os.path.abspath(expected),
          f"PIPFOUND_JOURNAL_DIR باید به <dir>/journal.csv برسد (گرفتیم: {out.get('file')})")
    check(os.path.exists(expected), "پوشه‌ی ناموجود باید ساخته شود و فایل در آن بیفتد")
finally:
    stop(pr)

# ── ۳) بدونِ env: مهاجرتِ دفترِ قدیمی + تکرارپذیری ───────────────────────────
home3 = tempfile.mkdtemp(prefix="pfj3-")
legacy3, legacy3_before = write_legacy(home3, {"id": "7", "datetime": "2026-08-10 18:58",
                                              "symbol": "GBPUSD", "direction": "short",
                                              "session": "London", "tf": "1h",
                                              "entry": "1.2700", "sl": "1.2750",
                                              "tp": "1.2600", "rr": "2.0", "status": "open",
                                              "notes": "ردیفِ آزمایشیِ دفترِ قدیمی"})
app_ledger = os.path.join(home3, "pipfound", "journal.csv")
pr, url, log3 = start_app(home3)
try:
    rows = read_rows(app_ledger) if os.path.exists(app_ledger) else []
    check(len(rows) == 1 and rows[0]["symbol"] == "GBPUSD",
          f"ردیفِ دفترِ قدیمی باید به دفترِ اپ منتقل شود (گرفتیم: {[r['symbol'] for r in rows]})")
    if rows:
        check(rows[0]["id"] == "1", f"ردیفِ منتقل‌شده باید شناسه‌ی تازه بگیرد (گرفتیم: {rows[0]['id']})")
        check("دفترِ قدیمی" in rows[0]["notes"] and "7" in rows[0]["notes"],
              "یادداشتِ ردیفِ منتقل‌شده باید منبع و شماره‌ی قبلی را نگه دارد")
    check(open(legacy3, encoding="utf-8").read() == legacy3_before,
          "فایلِ دفترِ قدیمی نباید تغییر کند")
    log_txt = open(log3, encoding="utf-8", errors="replace").read()
    check(os.path.abspath(app_ledger) in log_txt,
          "مسیرِ نهاییِ دفتر باید در لاگِ سرور چاپ شود")
    # پیش‌فرضِ دفتر باید بیرونِ Desktop/Documents باشد (جاب‌های launchd در آن‌ها نمی‌توانند بنویسند).
    default_path = ""
    for line in log_txt.splitlines():
        if "📓" in line and ":" in line:
            default_path = line.split(":", 1)[1].strip().split(" ")[0]
    check(bool(default_path), "خطِ مسیرِ دفتر باید در لاگِ استارتاپ چاپ شود")
    check(bool(default_path)
          and not default_path.startswith(os.path.join(home3, "Desktop"))
          and not default_path.startswith(os.path.join(home3, "Documents")),
          f"پیش‌فرضِ دفتر نباید در Desktop/Documents باشد (گرفتیم: {default_path or '—'})")
finally:
    stop(pr)

# نمونه‌ی دوم روی همان HOME: مهاجرت باید تکرارپذیر باشد و ردیفِ تکراری نسازد
pr, url, _ = start_app(home3)
try:
    rows = read_rows(app_ledger)
    check(len(rows) == 1, f"اجرای دوباره نباید ردیفِ تکراری بسازد (شد: {len(rows)})")
    check(read_rows(legacy3)[0]["symbol"] == "GBPUSD",
          "دفترِ قدیمی باید سالم بماند (خوانا)")
finally:
    stop(pr)

for n in notes:
    print(n)
if problems:
    print("")
    for p in problems:
        print("::error::" + p)
    print(f"\n❌ تستِ ژورنال رد شد — {len(problems)} مشکل")
    sys.exit(1)
print("\n✅ تستِ رفت‌وبرگشتِ ژورنال پاس شد: مسیرِ صریح، پوشه، ثبت/خواندن و مهاجرتِ بی‌خطر")
