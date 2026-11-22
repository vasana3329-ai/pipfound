#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تستِ پشتیبانِ خودکارِ زمان‌بندی‌شده — اسنپ‌شاتِ دوره‌ای + نگه‌داشتِ نسخه‌ها.

چهار چیز را ثابت می‌کند (پایتونِ stdlib، بدونِ دست‌زدن به دادهٔ واقعیِ کاربر):

  ۱) **هستهٔ خالص:** نامِ نسخه، تشخیصِ نامِ پشتیبان، تصمیمِ نگه‌داشت/هرس،
     ریاضیِ نوبت (`due`)، اعتبارسنجی و امن‌سازیِ تنظیمات، و «زمانِ مؤثرِ آخرین
     پشتیبان» (که با گم‌شدنِ حالت، اپ را وادار به ساختنِ نسخهٔ اضافه نمی‌کند).
  ۲) **هرسِ امن + نوشتنِ اتمیک:** فایلِ ناشناخته در پوشهٔ پشتیبان هرگز حذف
     نمی‌شود، دو اسنپ‌شاتِ هم‌ثانیه روی هم نمی‌نویسند، فایلِ موقت باقی نمی‌مانَد،
     و بستهٔ نوشته‌شده **از همان اعتبارسنجِ درون‌بری عبور می‌کند**.
  ۳) **رفت‌وبرگشتِ واقعی روی HTTP:** اپ با HOME/env کنترل‌شده بالا می‌آید و از
     همان بوت یک نسخه می‌سازد؛ `GET /api/autobackup` وضعیت را می‌دهد؛ اجرای
     فوری نسخهٔ تازه می‌سازد؛ نگه‌داشتِ کم، نسخه‌های قدیمی را هرس می‌کند (و
     فایلِ بیگانه را نه)؛ `?file=` همان نسخه را می‌دهد و روی «دستگاهِ تازه»
     درون‌بری می‌شود؛ و `?file=../../…` با ۴۰۰ بسته می‌ماند.
  ۴) **جهش‌آزماییِ قاعدهٔ نگهبان (لایهٔ ۱):** هر خرابیِ عمدی (هرسِ بدونِ فیلترِ
     نام، نوشتنِ غیرِاتمیک، زمان‌بندِ بی‌سنجش/بی‌گیت، حذفِ مسیر، حذفِ کنترل،
     بازکردنِ مسیرِ خواندنِ فایل) باید قاعده را قرمز کند و جهش‌های بی‌گناه سبز
     بمانند.

اجرا:  python3 autobackup_test.py        (خروجی ۰ = سالم)
"""
import csv
import datetime
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import autobackup as AB      # noqa: E402
import backup as BK          # noqa: E402
import selfcheck as SC       # noqa: E402

SOURCE = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
ABSOURCE = open(os.path.join(HERE, "autobackup.py"), encoding="utf-8").read()
BSOURCE = open(os.path.join(HERE, "backup.py"), encoding="utf-8").read()

CHECKS, FAILS, NOTES = [], [], []
procs = []


def check(name, cond, detail=""):
    CHECKS.append(name)
    if not cond:
        FAILS.append((name, detail))
    return cond


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_app(home, extra_env=None):
    """نمونهٔ اپ با HOME/env کنترل‌شده → (proc, url, logpath)."""
    env = dict(os.environ)
    env["HOME"] = home
    # نوتیفیکیشنِ نیتیوِ مک خفه — وگرنه کارگرِ آلارمِ فاندمنتال سرِ بوت روی
    # دسکتاپِ کاربر نوتیفِ واقعی می‌زند (قاعدهٔ نگهبان: selfcheck.notify_problems).
    env["PIPFOUND_NOTIFY"] = "0"
    for k in ("PIPFOUND_JOURNAL_CSV", "PIPFOUND_JOURNAL_DIR", "PIPFOUND_RISK_FILE",
              "PIPFOUND_TOKEN", "PIPFOUND_HOST", "PIPFOUND_PORT",
              "PIPFOUND_AUTOBACKUP_FILE", "PIPFOUND_BACKUP_DIR",
              "PIPFOUND_AUTOBACKUP_STATE"):
        env.pop(k, None)
    if extra_env:
        env.update(extra_env)
    port = free_port()
    log = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
    log.close()
    fh = open(log.name, "w")
    pr = subprocess.Popen([sys.executable, "-u", os.path.join(HERE, "app.py"),
                           "--port", str(port)],
                          cwd=HERE, env=env, stdout=fh, stderr=subprocess.STDOUT)
    procs.append(pr)
    url = "http://127.0.0.1:%d" % port
    for _ in range(80):
        try:
            urllib.request.urlopen(url + "/api/health", timeout=2).read()
            return pr, url, log.name
        except Exception:
            if pr.poll() is not None:
                raise RuntimeError("سرور بالا نیامد:\n" +
                                   open(log.name, encoding="utf-8", errors="replace").read()[-1200:])
            time.sleep(0.5)
    raise RuntimeError("سرور در مهلتِ مقرر بالا نیامد")


def stop(pr):
    try:
        pr.terminate()
        pr.wait(timeout=10)
    except Exception:
        try:
            pr.kill()
        except Exception:
            pass


def get_json(url, path):
    try:
        with urllib.request.urlopen(url + path, timeout=30) as r:
            return json.loads(r.read().decode("utf-8")), r.getcode()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body), e.code
        except Exception:
            return {"error": body[:200]}, e.code


def post_json(url, path, payload=None, raw=None):
    data = raw if raw is not None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8")), r.getcode()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body), e.code
        except Exception:
            return {"error": body[:200]}, e.code


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if (r.get("symbol") or "").strip()]


def post_trade(url, symbol="XAUUSD", direction="صعودی", entry="2400", sl="2380", tp="2450"):
    payload = {
        "symbol": symbol,
        "plan": {"direction": direction, "entry": entry, "sl": sl, "tp": tp,
                 "rr": "2.5", "poi": "M15 OB"},
        "bias_by_tf": {"1d": direction},
        "timeframes": ["4h", "15m"],
        "killzone": "NY AM",
        "style": "روزانه",
        "grade": "B",
        "score": 8,
        "max_score": 11.5,
        "verdict": "تستِ پشتیبانِ خودکار",
        "entry_tf": "15m",
    }
    return post_json(url, "/api/journal", payload)


FIELDS = ["id", "datetime", "symbol", "direction", "session", "tf", "htf_bias", "entry",
          "sl", "tp", "rr", "risk_pct", "setup", "poi", "reason", "status", "result",
          "exit", "realized_r", "mistake", "lesson", "notes"]


def row(**kw):
    r = {f: "" for f in FIELDS}
    r.update(kw)
    return r


# ══════════════ ۱) هستهٔ خالص ══════════════
check("نامِ نسخه الگوی استاندارد دارد",
      AB.filename(datetime.datetime(2026, 9, 27, 20, 53, 4))
      == "pipfound-backup-20260927-205304.json",
      AB.filename(datetime.datetime(2026, 9, 27, 20, 53, 4)))
check("نامِ نسخه زمان‌پذیر است (ts هم می‌پذیرد)",
      AB.filename(0).startswith("pipfound-backup-") and AB.filename(0).endswith(".json"),
      AB.filename(0))

for good in ("pipfound-backup-20260927-205300.json",
             "pipfound-backup-20260927-205300-2.json",
             "pipfound-backup-19990101-000000.json"):
    check("نامِ پشتیبان پذیرفته می‌شود: " + good, AB.is_backup_name(good), good)
for bad in ("journal.csv", "notes.txt", "pipfound-backup.json",
            "pipfound-backup-20260927.json", "pipfound-backup-20260927-2053.json",
            "pipfound-backup-20260927-205300.json.tmp", "../evil.json",
            "pipfound-backup-20260927-20530.json", "", None,
            "x-pipfound-backup-20260927-205300.json"):
    check("نامِ بیگانه رد می‌شود: " + repr(bad), not AB.is_backup_name(bad), repr(bad))

kept, doomed = AB.plan_prune(
    ["pipfound-backup-20260101-000001.json", "pipfound-backup-20260101-000003.json",
     "x.txt", "pipfound-backup-20260101-000002.json"], 2)
check("plan_prune تازه‌ترین‌ها را نگه می‌دارد",
      kept == ["pipfound-backup-20260101-000003.json",
               "pipfound-backup-20260101-000002.json"], str(kept))
check("plan_prune فایلِ بیگانه را نامزدِ حذف نمی‌کند", "x.txt" not in doomed, str(doomed))
check("plan_prune نسخهٔ قدیمی را نامزدِ حذف می‌کند",
      doomed == ["pipfound-backup-20260101-000001.json"], str(doomed))
kept0, doomed0 = AB.plan_prune(["pipfound-backup-20260101-000001.json",
                                "pipfound-backup-20260101-000002.json"], 0)
check("plan_prune با keep=۰ هم همه را نمی‌بُرد (حداقل ۱)", len(kept0) == 1 and len(doomed0) == 1,
      f"{kept0} / {doomed0}")
check("plan_prune با ورودیِ بدفهم explode نمی‌شود",
      AB.plan_prune(None, None) == ([], []), str(AB.plan_prune(None, None)))

check("due: هرگز پشتیبان نگرفته ⇒ همین حالا", AB.due(None, 1000.0, 24.0) is True, "")
check("due: تازه گرفته ⇒ نه", AB.due(1000.0, 1000.0 + 3600, 24.0) is False, "")
check("due: از فاصله گذشته ⇒ بله", AB.due(1000.0, 1000.0 + 24 * 3600, 24.0) is True, "")
check("due: سرِ مرزِ دقیقِ فاصله ⇒ بله", AB.due(0.0, 6 * 3600.0, 6.0) is True, "")
check("due: خاموش ⇒ هرگز", AB.due(None, 10 ** 9, 1.0, False) is False, "")
check("due: فاصلهٔ خراب به پیش‌فرض برمی‌گردد (نه explode و نه اسپم)",
      AB.due(0.0, 3600.0, "bad") is False and AB.due(0.0, 10 ** 9, None) is True, "")

check("زمانِ مؤثرِ آخرین پشتیبان = بیشینهٔ حالت و تازه‌ترین فایل",
      AB.effective_last_run(None, [{"mtime": 50}, {"mtime": 90}]) == 90.0
      and AB.effective_last_run(120, [{"mtime": 90}]) == 120.0
      and AB.effective_last_run(None, []) is None, "")
check("حالتِ گم‌شده باعثِ نسخهٔ اضافه نمی‌شود (تازه‌ترین فایل ملاک است)",
      AB.due(AB.effective_last_run(None, [{"mtime": time.time()}]),
             time.time(), 24.0) is False, "")

check("validate_settings: تنظیماتِ سالم صفر خطا", AB.validate_settings(
    {"enabled": True, "interval_h": 6, "keep": 3}) == [], "")
check("validate_settings: به‌روزرسانیِ جزئی مجاز است",
      AB.validate_settings({"keep": 5}) == [], "")
check("validate_settings: کلیدِ نامعلوم قرمز نمی‌شود (سازگاریِ آینده)",
      AB.validate_settings({"run_now": True}) == [], "")
check("validate_settings: enabled غیرِبولین رد می‌شود",
      any("enabled" in x for x in AB.validate_settings({"enabled": "yes"})), "")
check("validate_settings: فاصلهٔ زیرِ کمینه رد می‌شود",
      any("interval_h" in x for x in AB.validate_settings({"interval_h": 0.1})), "")
check("validate_settings: فاصلهٔ بالای بیشینه رد می‌شود",
      any("interval_h" in x for x in AB.validate_settings({"interval_h": 99999})), "")
check("validate_settings: فاصلهٔ غیرعددی رد می‌شود",
      any("interval_h" in x for x in AB.validate_settings({"interval_h": "زود"})), "")
check("validate_settings: keep غیرِصحیح رد می‌شود",
      any("صحیح" in x for x in AB.validate_settings({"keep": 2.5})), "")
check("validate_settings: keep صفر رد می‌شود (نگه‌داشتِ صفر = بی‌پشتیبان)",
      any("keep" in x for x in AB.validate_settings({"keep": 0})), "")
check("validate_settings: ورودیِ غیرشیء رد می‌شود",
      AB.validate_settings([1, 2]) == ["تنظیماتِ پشتیبان باید یک شیءِ JSON باشد (بالاترین سطح)"] or
      bool(AB.validate_settings([1, 2])), "")

check("normalize: پیش‌فرضِ سالم", AB.normalize(None) == AB.DEFAULTS, str(AB.normalize(None)))
check("normalize: مقدارِ خراب با پیش‌فرض جایگزین می‌شود (نه استثنا)",
      AB.normalize({"enabled": "بله", "interval_h": -5, "keep": 9999}) == AB.DEFAULTS,
      str(AB.normalize({"enabled": "بله", "interval_h": -5, "keep": 9999})))
check("normalize: مقدارِ معتبر نگه داشته می‌شود",
      AB.normalize({"enabled": False, "interval_h": "9", "keep": 3})
      == {"enabled": False, "interval_h": 9.0, "keep": 3},
      str(AB.normalize({"enabled": False, "interval_h": "9", "keep": 3})))


# ══════════════ ۲) هرسِ امن + نوشتنِ اتمیک (آفلاین) ══════════════
sample_rows = [
    row(id="1", datetime="2026-09-20 10:00", symbol="XAUUSD", direction="long",
        entry="2400", notes="الف"),
    row(id="2", datetime="2026-09-21 10:00", symbol="EURUSD", direction="short",
        entry="1.1000", notes="ب"),
]
sample_alarms = [{"id": "111", "symbol": "XAUUSD", "mode": "price", "target": 2500,
                  "cross": "up"}]
sample_settings = {"balance": 25000, "risk_pct": 0.5, "daily_loss_limit_pct": 2.0,
                   "max_open_risk_pct": 4.5, "account_ccy": "USD", "usd_per_quote": {}}
bundle = BK.build(sample_rows, FIELDS, sample_alarms, sample_settings,
                  now="2026-09-20 10:00:00")

d_io = tempfile.mkdtemp(prefix="pf_ab_io_")
try:
    junk = {"journal.csv": "a,b\n1,2\n", "notes.txt": "یادداشت",
            "pipfound-backup.json": "{}", "keep-me.json": "{}"}
    for n, body in junk.items():
        with open(os.path.join(d_io, n), "w", encoding="utf-8") as f:
            f.write(body)
    res = AB.snapshot(bundle, dir=d_io, keep=3, now=datetime.datetime(2026, 9, 20, 10, 0, 0))
    check("اسنپ‌شات: فایل با نامِ استاندارد ساخته شد",
          os.path.isfile(res["file"]) and AB.is_backup_name(res["name"]), str(res))
    check("اسنپ‌شات: فایلِ موقت باقی نمی‌مانَد",
          not any(n.endswith(".tmp") for n in os.listdir(d_io)), str(os.listdir(d_io)))
    doc = json.load(open(res["file"], encoding="utf-8"))
    check("اسنپ‌شات: محتوای نوشته‌شده از اعتبارسنجِ درون‌بری عبور می‌کند",
          BK.validate(doc, FIELDS) == [], str(BK.validate(doc, FIELDS))[:200])
    check("اسنپ‌شات: همان بستهٔ برون‌بری است (نشان/نسخه/شمارش)",
          doc.get("kind") == "pipfound-backup" and doc.get("version") == 1
          and doc.get("counts") == {"journal": 2, "alarms": 1}, str(doc)[:200])
    rows_back, added, skipped = BK.merge_journal([], doc["journal"], FIELDS)
    check("اسنپ‌شات: ردیف‌ها بی‌کم‌وکاست برمی‌گردند",
          added == 2 and rows_back[0]["symbol"] == "XAUUSD"
          and rows_back[1]["entry"] == "1.1000", str(rows_back)[:180])
    check("اسنپ‌شات: تنظیمات هم در فایلِ خودکار هست",
          abs(float(doc["settings"]["balance"]) - 25000) < 1e-6, str(doc["settings"]))

    p1 = AB.write_snapshot(bundle, dir=d_io, now=datetime.datetime(2026, 9, 20, 11, 0, 0))
    p2 = AB.write_snapshot(bundle, dir=d_io, now=datetime.datetime(2026, 9, 20, 11, 0, 0))
    check("دو اسنپ‌شات در یک ثانیه روی هم نمی‌نویسند",
          p1 != p2 and os.path.isfile(p1) and os.path.isfile(p2), f"{p1} / {p2}")
    check("پسوندِ یکتایی هم نامِ معتبرِ پشتیبان است",
          AB.is_backup_name(os.path.basename(p2)), os.path.basename(p2))

    listing = AB.list_backups(d_io)
    check("فهرستِ نسخه‌ها تازه‌ترین اول است",
          [b["name"] for b in listing] == sorted([b["name"] for b in listing], reverse=True)
          and len(listing) == 3, str([b["name"] for b in listing]))
    check("فهرستِ نسخه‌ها فایلِ بیگانه را گزارش نمی‌کند",
          all(b["name"].startswith("pipfound-backup-") for b in listing), str(listing))
    check("فهرستِ نسخه‌ها اندازهٔ واقعی را می‌دهد",
          all(b["bytes"] > 0 for b in listing), str(listing))

    newest = listing[0]["name"]
    pruned = AB.prune(dir=d_io, keep=1)
    check("هرس: فقط تازه‌ترین نگه داشته می‌شود",
          pruned["kept"] == [newest] and len(pruned["deleted"]) == 2, str(pruned))
    check("هرس: فایلِ ناشناخته دست‌نخورده می‌مانَد",
          all(os.path.isfile(os.path.join(d_io, n)) for n in junk),
          str(os.listdir(d_io)))
    check("هرس: حجمِ آزادشده گزارش می‌شود", pruned["freed"] > 0, str(pruned))
    check("هرس: فایلِ موقتِ نیمه‌کاره همه پاک شده",
          not any(n.endswith(".tmp") for n in os.listdir(d_io)), str(os.listdir(d_io)))
    check("هرس روی پوشهٔ ناموجود خطا نمی‌دهد",
          AB.prune(dir=os.path.join(d_io, "nope"), keep=2)["deleted"] == [], "")
    check("فهرست روی پوشهٔ ناموجود خطا نمی‌دهد",
          AB.list_backups(os.path.join(d_io, "nope")) == [], "")
finally:
    shutil.rmtree(d_io, ignore_errors=True)

d_cfg = tempfile.mkdtemp(prefix="pf_ab_cfg_")
try:
    spath = os.path.join(d_cfg, "autobackup.json")
    check("تنظیماتِ نبوده ⇒ پیش‌فرض", AB.load_settings(spath) == AB.DEFAULTS, "")
    saved = AB.save_settings({"enabled": False, "interval_h": 6, "keep": 2}, path=spath)
    check("ذخیرهٔ تنظیمات: مقادیرِ سالم برمی‌گردند",
          saved["enabled"] is False and saved["interval_h"] == 6.0 and saved["keep"] == 2,
          str(saved))
    check("ذخیرهٔ تنظیمات: مهرِ زمان می‌خورد", bool(saved.get("updated_utc")), str(saved))
    check("ذخیرهٔ تنظیمات: فایلِ موقت باقی نمی‌مانَد",
          not any(n.endswith(".tmp") for n in os.listdir(d_cfg)), str(os.listdir(d_cfg)))
    check("رفت‌وبرگشتِ تنظیمات",
          AB.load_settings(spath) == {"enabled": False, "interval_h": 6.0, "keep": 2},
          str(AB.load_settings(spath)))
    with open(spath, "w", encoding="utf-8") as f:
        f.write("{خراب")
    check("تنظیماتِ خراب روی دیسک ⇒ پیش‌فرض (اپ نمی‌افتد)",
          AB.load_settings(spath) == AB.DEFAULTS, "")
    stpath = os.path.join(d_cfg, "state.json")
    check("حالتِ نبوده ⇒ حالتِ نخستین", AB.load_state(stpath)["runs"] == 0, "")
    AB.save_state({"last_run": "2026-09-27 10:00:00", "last_run_ts": 123.0,
                   "last_file": "pipfound-backup-20260927-100000.json",
                   "last_bytes": 42, "runs": 3, "last_error": None}, path=stpath)
    check("رفت‌وبرگشتِ حالت",
          AB.load_state(stpath)["last_file"] == "pipfound-backup-20260927-100000.json"
          and AB.load_state(stpath)["runs"] == 3, str(AB.load_state(stpath)))
    AB.save_state({"last_error": "خطای آزمایشی"}, path=stpath)
    check("حالت: کلیدِ غایب None می‌شود (نه اینکه کرش کند)",
          AB.load_state(stpath)["last_run"] is None, str(AB.load_state(stpath)))
finally:
    shutil.rmtree(d_cfg, ignore_errors=True)


# ══════════════ ۳) رفت‌وبرگشتِ واقعی روی HTTP ══════════════
home_a = tempfile.mkdtemp(prefix="pfab-a-")
home_b = tempfile.mkdtemp(prefix="pfab-b-")
bdir_a = os.path.join(home_a, "backups")
cfg_a = os.path.join(home_a, "pipfound", "autobackup.json")
state_a = os.path.join(home_a, "pipfound", "autobackup_state.json")
try:
    pr_a, url_a, log_a = start_app(home_a, {
        "PIPFOUND_BACKUP_DIR": bdir_a,
        "PIPFOUND_AUTOBACKUP_FILE": cfg_a,
        "PIPFOUND_AUTOBACKUP_STATE": state_a,
    })
    try:
        # سرِ بوت باید بدونِ هیچ تنظیمی خودش یک نسخه بسازد («هیچ‌وقت بی‌پشتیبان»)
        for _ in range(40):
            if os.path.isdir(bdir_a) and AB.list_backups(bdir_a):
                break
            time.sleep(0.5)
        boot = AB.list_backups(bdir_a)
        check("سرِ بوت: اپ خودش یک نسخه می‌سازد (بدونِ هیچ تنظیمی)",
              len(boot) == 1, str(os.listdir(bdir_a) if os.path.isdir(bdir_a) else "—"))
        if boot:
            bdoc = json.load(open(boot[0]["file"], encoding="utf-8"))
            check("نسخهٔ بوت از اعتبارسنجِ درون‌بری عبور می‌کند",
                  BK.validate(bdoc, FIELDS) == [], str(BK.validate(bdoc, FIELDS))[:160])
        st0, c0 = get_json(url_a, "/api/autobackup")
        check("وضعیت: ۲۰۰ و ok", c0 == 200 and st0.get("ok") is True, f"{c0} {str(st0)[:160]}")
        check("وضعیت: پیش‌فرضِ روشن با ۲۴ ساعت و ۷ نسخه",
              st0["settings"] == {"enabled": True, "interval_h": 24.0, "keep": 7},
              str(st0.get("settings")))
        check("وضعیت: پوشهٔ پشتیبان گزارش می‌شود",
              os.path.realpath(st0.get("dir") or "") == os.path.realpath(bdir_a), str(st0.get("dir")))
        check("وضعیت: فهرستِ نسخه‌ها و شمارش هم‌خوان است",
              st0.get("count") == len(st0.get("backups") or []) == 1, str(st0)[:200])
        check("وضعیت: فاصلهٔ نامشخص نیست (نوبتِ بعدی مشخص است)",
              st0.get("due_now") is False and st0.get("next_in_h") is not None,
              f"{st0.get('due_now')} {st0.get('next_in_h')}")

        # هرس نباید فایلِ بیگانهٔ همان پوشه را ببرد
        with open(os.path.join(bdir_a, "keep-me.txt"), "w", encoding="utf-8") as f:
            f.write("دست نزن")

        r1, c1 = post_trade(url_a, "XAUUSD", "صعودی")
        r2, c2 = post_trade(url_a, "EURUSD", "نزولی", entry="1.1000", sl="1.1050", tp="1.0900")
        ra, _ = post_json(url_a, "/api/alarm", {"symbol": "XAUUSD", "mode": "price",
                                                "target": 2500, "cross": "up"})
        rs, cs = post_json(url_a, "/api/risk", {"balance": 25000, "risk_pct": 0.5,
                                                "daily_loss_limit_pct": 2.0,
                                                "max_open_risk_pct": 4.5})
        check("دستگاهِ مبدأ: ژورنال/آلارم/تنظیمات کاشته شد",
              c1 == 200 and c2 == 200 and bool(ra.get("added")) and cs == 200
              and rs.get("ok") is True, f"{r1} {r2} {ra} {str(rs)[:120]}")

        now_run, cnow = post_json(url_a, "/api/autobackup", {"run_now": True})
        check("اجرای فوری: ۲۰۰ و نسخهٔ تازه ساخته شد",
              cnow == 200 and now_run.get("ran") and os.path.isfile(
                  os.path.join(bdir_a, now_run["ran"]["name"])), str(now_run)[:200])
        check("اجرای فوری: شمارشِ نسخه‌ها بالا رفت",
              now_run.get("count") == 2, str(now_run.get("count")))
        made = json.load(open(os.path.join(bdir_a, now_run["ran"]["name"]), encoding="utf-8"))
        check("اجرای فوری: نسخهٔ تازه دادهٔ کاشته‌شده را دارد",
              made.get("counts") == {"journal": 2, "alarms": 1}, str(made.get("counts")))
        check("اجرای فوری: نسخهٔ تازه از اعتبارسنجِ درون‌بری عبور می‌کند",
              BK.validate(made, FIELDS) == [], str(BK.validate(made, FIELDS))[:160])
        check("اجرای فوری: حالت (state) ثبت شد",
              AB.load_state(state_a)["runs"] >= 2
              and AB.load_state(state_a)["last_file"] == now_run["ran"]["name"],
              str(AB.load_state(state_a)))

        # خواندنِ همان نسخه و برگرداندنش روی «دستگاهِ تازه»
        doc_got, cg = get_json(url_a, "/api/autobackup?file=" + now_run["ran"]["name"])
        check("خواندنِ نسخه: ۲۰۰ و همان بسته",
              cg == 200 and doc_got.get("kind") == "pipfound-backup"
              and doc_got.get("counts") == {"journal": 2, "alarms": 1}, f"{cg} {str(doc_got)[:160]}")
        for evil in ("../../../../etc/passwd", "..%2F..%2Fetc%2Fpasswd", "x.json",
                     "pipfound-backup-20260927-205300.json"):
            ej, ec = get_json(url_a, "/api/autobackup?file=" + evil)
            if evil == "pipfound-backup-20260927-205300.json":
                check("خواندنِ نامِ معتبرِ ناموجود: ۴۰۰ (نه افشا و نه ۵۰۰)", ec == 400, f"{ec} {ej}")
            else:
                check("مسیرِ بیرون‌زدن بسته است: " + evil, ec == 400, f"{ec} {ej}")

        # نگه‌داشت: keep=2 و بعد سه اجرا ⇒ فقط دو نسخه می‌مانَد
        sv, csv_ = post_json(url_a, "/api/autobackup", {"interval_h": 6, "keep": 2})
        check("ذخیرهٔ تنظیمات از راهِ API: ۲۰۰",
              csv_ == 200 and sv["settings"]["keep"] == 2 and sv["settings"]["interval_h"] == 6.0,
              str(sv.get("settings")))
        check("ذخیرهٔ تنظیمات: روی دیسک نوشته شد",
              AB.load_settings(cfg_a)["keep"] == 2, str(AB.load_settings(cfg_a)))
        deleted_any = False
        for i in range(3):
            rr, cc = post_json(url_a, "/api/autobackup", {"run_now": True})
            check(f"اجرای فوریِ {i + 2}: ۲۰۰", cc == 200 and rr.get("ran"), str(rr)[:160])
            if (rr.get("ran") or {}).get("deleted"):
                deleted_any = True
        left = AB.list_backups(bdir_a)
        check("نگه‌داشت: بعد از سه اجرا فقط دو نسخه می‌مانَد", len(left) == 2,
              str([b["name"] for b in left]))
        check("نگه‌داشت: نگه‌داشته‌شده‌ها تازه‌ترین‌ها هستند",
              [b["name"] for b in left] == sorted([b["name"] for b in left], reverse=True))
        check("نگه‌داشت: هرسِ واقعی اتفاق افتاد", deleted_any, "")
        check("نگه‌داشت: فایلِ بیگانهٔ همان پوشه سالم ماند",
              os.path.isfile(os.path.join(bdir_a, "keep-me.txt")), str(os.listdir(bdir_a)))
        check("نگه‌داشت: فایلِ موقت باقی نمی‌مانَد",
              not any(n.endswith(".tmp") for n in os.listdir(bdir_a)), str(os.listdir(bdir_a)))

        bad_keep, bk_code = post_json(url_a, "/api/autobackup", {"keep": 0})
        check("اعتبارسنجی: keep=۰ با ۴۰۰ و فهرستِ خطا رد می‌شود",
              bk_code == 400 and bad_keep.get("ok") is False and bad_keep.get("errors"),
              f"{bk_code} {str(bad_keep)[:160]}")
        check("اعتبارسنجی: رد شدن تنظیماتِ فعلی را خراب نکرد",
              AB.load_settings(cfg_a)["keep"] == 2, str(AB.load_settings(cfg_a)))
        bad2, b2c = post_json(url_a, "/api/autobackup", {"interval_h": "زود"})
        check("اعتبارسنجی: فاصلهٔ غیرعددی با ۴۰۰ رد می‌شود", b2c == 400, f"{b2c} {bad2}")
        bad3, b3c = post_json(url_a, "/api/autobackup", raw=b"{not json")
        check("اعتبارسنجی: بدنهٔ غیرِJSON با ۴۰۰ رد می‌شود", b3c == 400, f"{b3c} {bad3}")

        off, coff = post_json(url_a, "/api/autobackup", {"enabled": False})
        check("خاموش‌کردن: ۲۰۰ و وضعیت گزارش می‌دهد",
              coff == 200 and off["settings"]["enabled"] is False, str(off.get("settings")))
        check("خاموش‌کردن: روی دیسک ماند",
              AB.load_settings(cfg_a)["enabled"] is False, str(AB.load_settings(cfg_a)))
        check("خاموش: نوبتِ بعدی وجود ندارد (بی‌سکوت پشتیبان نمی‌گیرد)",
              off.get("due_now") is False and off.get("next_in_h") is None,
              f"{off.get('due_now')} {off.get('next_in_h')}")

        live_bundle = doc_got
    finally:
        stop(pr_a)

    # «دستگاهِ تازه»: همان فایلِ خودکار باید کامل بربگرداند
    pr_b, url_b, _ = start_app(home_b)
    try:
        jfile_b = os.path.join(home_b, "pipfound", "journal.csv")
        rl, _ = post_trade(url_b, "GBPUSD", "صعودی")
        check("دستگاهِ مقصد: ردیفِ محلی ثبت شد", rl.get("added") == "1", str(rl))
        imp, ci = post_json(url_b, "/api/import",
                            raw=json.dumps(live_bundle).encode("utf-8"))
        check("درون‌بریِ نسخهٔ خودکار: ۲۰۰ و ok",
              ci == 200 and imp.get("ok") is True, f"{ci} {str(imp)[:200]}")
        check("درون‌بریِ نسخهٔ خودکار: هر دو ردیف و هر دو بخش برمی‌گردند",
              imp.get("journal_added") == 2 and imp.get("alarms_added") == 1
              and imp.get("settings_applied") is True, str(imp)[:200])
        rows_b = read_rows(jfile_b)
        check("درون‌بریِ نسخهٔ خودکار: ردیفِ محلی مقصد پاک نشد",
              len(rows_b) == 3 and any(r["symbol"] == "GBPUSD" for r in rows_b),
              str([r["symbol"] for r in rows_b]))
        check("درون‌بریِ نسخهٔ خودکار: مقادیر دست‌نخورده",
              any(r["symbol"] == "EURUSD" and r["entry"] == "1.1000" for r in rows_b),
              str(rows_b)[:200])
    except Exception as e:
        FAILS.append(("اجرای بخشِ دستگاهِ تازه با استثنا متوقف شد", repr(e)))
    finally:
        stop(pr_b)
except Exception as e:
    FAILS.append(("اجرای بخشِ HTTP با استثنا متوقف شد", repr(e)))
finally:
    for pr in procs:
        stop(pr)
    shutil.rmtree(home_a, ignore_errors=True)
    shutil.rmtree(home_b, ignore_errors=True)


# ══════════════ ۴) جهش‌آزماییِ قاعدهٔ نگهبان ══════════════
def run_guard(app_src=None, ab_src=None, backup_src=None):
    d = tempfile.mkdtemp(prefix="pf_ab_mut_")
    try:
        with open(os.path.join(d, "app.py"), "w", encoding="utf-8") as f:
            f.write(app_src if app_src is not None else SOURCE)
        with open(os.path.join(d, "autobackup.py"), "w", encoding="utf-8") as f:
            f.write(ab_src if ab_src is not None else ABSOURCE)
        with open(os.path.join(d, "backup.py"), "w", encoding="utf-8") as f:
            f.write(backup_src if backup_src is not None else BSOURCE)
        pages = SC.page_sources(d)
        probs, stats = SC.autobackup_problems(d, pages)
        return probs, stats, pages
    finally:
        shutil.rmtree(d, ignore_errors=True)


p0, s0, pages0 = run_guard()
check("جهش‌آزمایی: مخزنِ سالم صفر خطا و هر پنج پرچم سبز",
      p0 == [] and all(s0.get(k) for k in ("module", "safe_prune", "atomic",
                                           "scheduler", "controls")),
      f"{p0} {s0}")
check("جهش‌آزمایی: هارنس واقعاً صفحه را می‌خواند", bool(pages0), str(list(pages0)))


def red(name, needle, app_src=None, ab_src=None, backup_src=None):
    probs, _, _ = run_guard(app_src=app_src, ab_src=ab_src, backup_src=backup_src)
    check("جهشِ سرخ | " + name, any(needle in x for x in probs), str(probs)[:240])


def green(name, app_src=None, ab_src=None, backup_src=None):
    probs, _, _ = run_guard(app_src=app_src, ab_src=ab_src, backup_src=backup_src)
    check("جهشِ سبز | " + name, probs == [], str(probs)[:240])


red("برداشتنِ حذف از هرس (نگه‌داشت بی‌اثر)",
    "هیچ نسخه‌ای را حذف نمی‌کند",
    ab_src=ABSOURCE.replace("            os.remove(p)", "            pass  # حذف برداشته شد", 1))
red("برداشتنِ فیلترِ نام از تصمیمِ هرس",
    "plan_prune نامِ فایل را فیلتر نمی‌کند",
    ab_src=ABSOURCE.replace("for n in (names or []) if is_backup_name(n)}",
                            "for n in (names or [])}", 1))
# دقت: عیناً همین الگو در list_backups هم هست؛ جهش باید از روی «for n in doomed»
# که در کلِ ماژول یکتاست لنگر بگیرد، وگرنه جای اشتباهی را عوض می‌کند و
# نگهبانِ سالم بی‌دلیل سبز می‌مانْد (یک بار همین اتفاق افتاد).
red("برداشتنِ نوارِ ایمنیِ دوم پیش از os.remove",
    "پیش از os.remove نام را دوباره نمی‌سنجد",
    ab_src=ABSOURCE.replace("    for n in doomed:\n        if not is_backup_name(n):\n"
                            "            continue\n",
                            "    for n in doomed:\n", 1))
red("غیرِاتمیک‌کردنِ نوشتن",
    "اتمیک نیست",
    ab_src=ABSOURCE.replace("    os.replace(tmp, p)", "    os.rename(tmp, p)", 1))
red("دور زدنِ مسیرِ اتمیک در رونوشتِ اسنپ‌شات",
    "از مسیرِ اتمیکِ _write_json استفاده نمی‌کند",
    ab_src=ABSOURCE.replace("    _write_json(p, bundle if isinstance(bundle, dict) else {})",
                            "    with open(p, \"w\", encoding=\"utf-8\") as f:\n"
                            "        json.dump(bundle, f)", 1))
red("حذفِ تابعِ due از ماژول",
    "autobackup.py ناقص است",
    ab_src=ABSOURCE.replace("def due(last_run_ts", "def due_disabled(last_run_ts", 1))
red("حذفِ کاملِ autobackup.py", "autobackup.py خوانده نشد", ab_src="")
red("زمان‌بند بی‌سنجشِ نوبت (هر دور یک نسخه)",
    "نوبت را نمی‌سنجد",
    app_src=SOURCE.replace('if AB.due(last, time.time(), cfg["interval_h"], True):',
                           "if True:", 1))
red("زمان‌بند بی‌گیتِ روشن/خاموش",
    "کلیدِ روشن/خاموش را نمی‌بیند",
    app_src=SOURCE.replace('            if cfg.get("enabled"):', "            if True:", 1))
red("زمان‌بند بی‌مسیرِ مشترکِ اسنپ‌شات",
    "از مسیرِ مشترکِ اسنپ‌شات استفاده نمی‌کند",
    app_src=SOURCE.replace("                    res = _autobackup_run_now()",
                           "                    res = AB.snapshot({})", 1))
red("پشتیبانِ خودکار بدونِ بستهٔ برون‌بری",
    "از بستهٔ خودِ «برون‌بری» نمی‌سازد",
    app_src=SOURCE.replace('res = AB.snapshot(_backup_bundle(), keep=AB.load_settings()["keep"])',
                           'res = AB.snapshot({}, keep=AB.load_settings()["keep"])', 1))
red("راه‌اندازی‌نشدنِ کارگر سرِ بوت",
    "سرِ بوت راه‌اندازی نمی‌شود",
    app_src=SOURCE.replace("    start_autobackup_worker()\n", "", 1))
red("برداشتنِ مسیرِ POST (فقط وضعیت می‌مانَد)",
    "هم GET (وضعیت/نسخه) و هم",
    app_src=SOURCE.replace('        if u.path == "/api/autobackup":\n'
                           "            # تنظیماتِ زمان‌بندی (+ اجرای فوری با run_now)",
                           '        if u.path == "/api/autobackup-old":\n'
                           "            # تنظیماتِ زمان‌بندی (+ اجرای فوری با run_now)", 1))
red("بازکردنِ مسیرِ خواندنِ نسخه (نام بی‌سنجش)",
    "نام را نمی‌سنجد",
    app_src=SOURCE.replace("if AB is None or not AB.is_backup_name(name):",
                           "if AB is None:", 1))
red("برداشتنِ کنترلِ اجرای فوری از صفحه",
    "کنترلِ «اجرای فوری»",
    app_src=SOURCE.replace('id="abNow"', 'id="abNowX"', 1))
# دقت: این دو نام در صفحه چند جا می‌آیند (خواندن + ذخیره + سیم‌کشی)، پس جهش
# باید **همهٔ** رخدادها را عوض کند وگرنه یک نسخهٔ باقی‌مانده باعثِ سبزِ کاذب می‌شود.
red("قطعِ سیمِ کلیدِ روشن/خاموش",
    "به JS وصل نشده",
    app_src=SOURCE.replace('getElementById("abToggle")', 'getElementById("abToggleX")'))
red("قطعِ خواندنِ وضعیت از سرور",
    "وضعیتِ پشتیبانِ خودکار را از سرور نمی‌خوانَد",
    app_src=SOURCE.replace('fetch("/api/autobackup"', 'fetch("/api/autobackupOld"'))

green("تغییرِ پسوندِ فایلِ موقت (اتمیک می‌مانَد)",
      ab_src=ABSOURCE.replace('tmp = p + ".tmp"', 'tmp = p + ".part"', 1))
green("کامنتِ بی‌گناه در تصمیمِ هرس",
      ab_src=ABSOURCE.replace('    safe = sorted(',
                              "    # یادداشتِ بی‌گناه\n    safe = sorted(", 1))
green("عوض‌کردنِ مقدارِ پیش‌فرضِ فاصله",
      ab_src=ABSOURCE.replace('"interval_h": 24.0,', '"interval_h": 12.0,', 1))
green("افزودنِ تابعِ تازه به ماژول (سازگار)",
      ab_src=ABSOURCE.rstrip() + "\n\n\ndef version():\n    return 1\n")
green("کامنتِ بی‌گناه در زمان‌بند",
      app_src=SOURCE.replace("    while True:\n        try:\n            cfg = AB.load_settings()",
                             "    while True:\n        try:\n            # یادداشتِ بی‌گناه\n"
                             "            cfg = AB.load_settings()", 1))
green("افزودنِ کلیدِ تازه به تنظیمات (سازگاریِ آینده)",
      app_src=SOURCE.replace('json.dumps(_autobackup_status(), ensure_ascii=False))',
                             'json.dumps(dict(_autobackup_status(), schema=2), ensure_ascii=False))', 1))


# ── گزارش ──
for n in NOTES:
    print(n)
print(f"• بررسی‌ها: {len(CHECKS)}")
if FAILS:
    print("")
    for name, detail in FAILS:
        print(f"::error::❌ {name}" + (f" — {detail}" if detail else ""))
    print(f"\n❌ تستِ پشتیبانِ خودکار رد شد — {len(FAILS)} از {len(CHECKS)} بررسی شکست خورد")
    sys.exit(1)
print("✅ تستِ پشتیبانِ خودکار پاس شد — اسنپ‌شاتِ زمان‌بندی‌شده، نگه‌داشتِ امنِ "
      "نسخه‌ها، خواندنِ بی‌خطرِ نام، رونوشتِ خالصِ درست، و جهش‌آزماییِ قاعدهٔ نگهبان")
