#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تستِ انتقالِ دادهٔ کاربر — برون‌بری/درون‌بریِ JSON (ژورنال، آلارم‌ها، تنظیمات).

سه چیز را ثابت می‌کند (همه با پایتونِ stdlib و بدونِ دست‌زدن به دادهٔ واقعیِ کاربر):

  ۱) **رفت‌وبرگشتِ واقعی روی HTTP:** نمونهٔ اپ با HOME و env کنترل‌شده بالا می‌آید،
     ژورنال/آلارم/تنظیمات کاشته می‌شود، `GET /api/export` بستهٔ کامل را می‌دهد،
     و روی «دستگاهِ تازه» (HOME دومِ خالی) `POST /api/import` همان‌ها را برمی‌گرداند.
     اجرای دوبارهٔ همان بسته «۰ افزوده» می‌دهد (تکرارپذیر) و ردیف/آلارم/تنظیماتِ
     موجود روی دستگاهِ مقصد **پاک نمی‌شود**.
  ۲) **اعتبارسنجیِ پیش از نوشتن:** بستهٔ خراب (نشانِ غلط، نسخهٔ غلط، ردیفِ بی‌نماد،
     فیلدِ ناشناخته، تنظیماتِ منفی…) با ۴۰۰ رد می‌شود و هیچ فایلی نوشته/عوض نمی‌شود.
  ۳) **جهش‌آزماییِ قاعدهٔ نگهبان (لایهٔ ۱):** هر خرابیِ عمدی در کپیِ موقتِ
     `app.py`/`backup.py` باید قاعده را قرمز کند و جهش‌های بی‌گناه سبز بمانند.

اجرا:  python3 backup_test.py        (خروجی ۰ = سالم)
"""
import csv
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

import backup as BK          # noqa: E402
import selfcheck as SC       # noqa: E402

APP = os.path.join(HERE, "app.py")
SOURCE = open(APP, encoding="utf-8").read()
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
    for k in ("PIPFOUND_JOURNAL_CSV", "PIPFOUND_JOURNAL_DIR", "PIPFOUND_RISK_FILE",
              "PIPFOUND_TOKEN", "PIPFOUND_HOST", "PIPFOUND_PORT"):
        env.pop(k, None)
    if extra_env:
        env.update(extra_env)
    port = free_port()
    log = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
    log.close()
    fh = open(log.name, "w")
    pr = subprocess.Popen([sys.executable, "-u", APP, "--port", str(port)],
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
    with urllib.request.urlopen(url + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8")), r.getcode()


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
            j = json.loads(body)
        except Exception:
            j = {"error": body[:200]}
        return j, e.code


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if (r.get("symbol") or "").strip()]


def post_trade(url, symbol="XAUUSD", direction="صعودی", entry="2400", sl="2380",
               tp="2450"):
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
        "verdict": "تستِ انتقالِ داده",
        "entry_tf": "15m",
    }
    return post_json(url, "/api/journal", payload)


# ══════════════ ۱) بررسی‌های خالصِ ماژول (آفلاین) ══════════════
FIELDS = ["id", "datetime", "symbol", "direction", "session", "tf", "htf_bias", "entry",
          "sl", "tp", "rr", "risk_pct", "setup", "poi", "reason", "status", "result",
          "exit", "realized_r", "mistake", "lesson", "notes"]

def row(**kw):
    r = {f: "" for f in FIELDS}
    r.update(kw)
    return r


sample_rows = [
    row(id="1", datetime="2026-09-20 10:00", symbol="XAUUSD", direction="long",
        entry="2400", notes="الف"),
    row(id="2", datetime="2026-09-21 10:00", symbol="EURUSD", direction="short",
        entry="1.1000", notes="ب"),
]
sample_alarms = [
    {"id": "111", "symbol": "XAUUSD", "mode": "price", "target": 2500, "cross": "up",
     "zzz_unknown": "باید پاک شود"},
    {"id": "222", "symbol": "EURUSD", "mode": "ote", "low": 1.08, "high": 1.10},
]
sample_settings = {"balance": 25000, "risk_pct": 0.5, "daily_loss_limit_pct": 2.0,
                   "max_open_risk_pct": 4.5, "account_ccy": "USD", "usd_per_quote": {}}

b = BK.build(sample_rows, FIELDS, sample_alarms, sample_settings, now="2026-09-26 12:00:00")
check("build: نشانِ بسته و نسخه درست است",
      b["kind"] == "pipfound-backup" and b["version"] == 1, str(b)[:120])
check("build: هر سه بخش در بسته هست",
      all(k in b for k in ("journal", "alarms", "settings")), str(sorted(b)))
check("build: شمارش‌ها درست است",
      b["counts"] == {"journal": 2, "alarms": 2}, str(b["counts"]))
check("build: کلیدهای ناشناختهٔ آلارم پاک می‌شود",
      all("zzz_unknown" not in a for a in b["alarms"]), str(b["alarms"]))
check("build: فیلدهای ژورنال به ترتیبِ دفتر می‌آید",
      b["journal_fields"] == FIELDS and b["journal"][0]["symbol"] == "XAUUSD",
      str(b["journal_fields"][:4]))
check("build: مقدارِ None به رشتهٔ خالی تبدیل می‌شود",
      isinstance(b["journal"][0]["sl"], str), repr(b["journal"][0]["sl"]))

v_ok = BK.validate(b, FIELDS)
check("validate: بستهٔ سالم صفر خطا می‌دهد", v_ok == [], str(v_ok))


def bad(mut, needle, name):
    d = json.loads(json.dumps(b))
    mut(d)
    probs = BK.validate(d, FIELDS)
    check(name, any(needle in x for x in probs), str(probs)[:200])


bad(lambda d: d.update(kind="other"), "kind", "validate: نشانِ غلط قرمز می‌شود")
bad(lambda d: d.update(version=99), "version", "validate: نسخهٔ ناسازگار قرمز می‌شود")
bad(lambda d: d.update(version="1"), "version", "validate: نسخهٔ رشته‌ای قرمز می‌شود")
bad(lambda d: d.update(journal="x"), "journal", "validate: ژورنالِ غیرفهرست قرمز می‌شود")
bad(lambda d: d["journal"].append("رشته"), "شیء نیست", "validate: ردیفِ غیرشیء قرمز می‌شود")
bad(lambda d: d["journal"][0].update(symbol=""), "نماد", "validate: ردیفِ بی‌نماد قرمز می‌شود")
bad(lambda d: d["journal"][0].update(unknown_col="x"), "ناشناخته",
    "validate: فیلدِ ناشناختهٔ ژورنال قرمز می‌شود")
bad(lambda d: d["journal"][0].update(notes={"a": 1}), "ساده",
    "validate: مقدارِ شیء در ردیف قرمز می‌شود")
bad(lambda d: d.update(alarms="x"), "alarms", "validate: آلارمِ غیرفهرست قرمز می‌شود")
bad(lambda d: d["alarms"][0].pop("id"), "شناسه", "validate: آلارمِ بی‌شناسه قرمز می‌شود")
bad(lambda d: d["alarms"][0].update(symbol=""), "نماد",
    "validate: آلارمِ بی‌نماد قرمز می‌شود")
bad(lambda d: d["alarms"][0].update(mode=""), "mode", "validate: آلارمِ بی‌نوع قرمز می‌شود")
bad(lambda d: d.update(settings=[]), "settings", "validate: تنظیماتِ غیرشیء قرمز می‌شود")
bad(lambda d: d["settings"].update(balance=-5), "balance",
    "validate: سرمایهٔ منفی قرمز می‌شود")
bad(lambda d: d["settings"].update(account_ccy="US"), "account_ccy",
    "validate: ارزِ حسابِ بد قرمز می‌شود")
bad(lambda d: d["settings"].update(usd_per_quote={"JPY": -1}), "usd_per_quote",
    "validate: نرخِ منفی قرمز می‌شود")
bad(lambda d: d["settings"].update(ghost_key=1), "ناشناخته",
    "validate: کلیدِ ناشناختهٔ تنظیمات قرمز می‌شود")
big = json.loads(json.dumps(b))
big["journal"] = big["journal"] * (BK.MAX_JOURNAL + 1)
check("validate: ژورنالِ بیش از سقف قرمز می‌شود",
      any("سقف" in x for x in BK.validate(big, FIELDS)), "")

rows, added, skipped = BK.merge_journal(sample_rows, sample_rows, FIELDS)
check("merge_journal: اجرای دوباره ردیفِ تکراری نمی‌سازد",
      added == 0 and skipped == 2 and len(rows) == 2, f"{added}/{skipped}/{len(rows)}")
new_row = row(id="9", datetime="2026-09-22 10:00", symbol="GBPUSD", entry="1.27")
rows2, added2, skipped2 = BK.merge_journal(sample_rows, [new_row], FIELDS)
check("merge_journal: شناسهٔ ردیفِ تازه از بیشترین+۱ ادامه می‌یابد",
      added2 == 1 and rows2[2]["id"] == "3" and rows2[2]["symbol"] == "GBPUSD",
      str([r["id"] for r in rows2]))
check("merge_journal: ردیف‌های موجود دست‌نخورده می‌مانند",
      rows2[0]["notes"] == "الف" and rows2[1]["symbol"] == "EURUSD", "")

al2, a_add, a_skip = BK.merge_alarms(sample_alarms, sample_alarms)
check("merge_alarms: تکراریِ شناسه‌ای اضافه نمی‌شود",
      a_add == 0 and a_skip == 2 and len(al2) == 2, f"{a_add}/{a_skip}/{len(al2)}")
al3, a_add3, _ = BK.merge_alarms(sample_alarms, [{"id": "333", "symbol": "BTCUSDT",
                                                  "mode": "price"}])
check("merge_alarms: آلارمِ تازه با پاک‌سازیِ کلیدها می‌آید",
      a_add3 == 1 and al3[2]["id"] == "333" and "zzz_unknown" not in str(al3), str(al3[2]))
al_c, c_add, c_skip = BK.merge_alarms([{"id": "7", "symbol": "AAA", "mode": "price"}],
                                      [{"id": "7", "symbol": "BBB", "mode": "price"}])
check("merge_alarms: برخوردِ شناسه با محتوای متفاوت گم نمی‌شود (پسوند می‌گیرد)",
      c_add == 1 and al_c[1]["id"] == "7-2" and al_c[1]["symbol"] == "BBB", str(al_c))
_, c_add2, c_skip2 = BK.merge_alarms(al_c, [{"id": "7", "symbol": "BBB", "mode": "price"}])
check("merge_alarms: بعد از پسوندگیری هم تکرارپذیری می‌مانَد",
      c_add2 == 0 and c_skip2 == 1, f"{c_add2}/{c_skip2}")

st2 = BK.merge_settings({"balance": 1, "ghost": 9}, {"balance": 2, "risk_pct": 0.25})
check("merge_settings: فقط کلیدهای شناخته‌شده و بقیهٔ فعلی می‌مانَد",
      st2.get("balance") == 2 and st2.get("risk_pct") == 0.25 and st2.get("ghost") == 9,
      str(st2))


# ══════════════ ۲) رفت‌وبرگشتِ واقعی روی HTTP ══════════════
home_a = tempfile.mkdtemp(prefix="pfbk-a-")
home_b = tempfile.mkdtemp(prefix="pfbk-b-")
try:
    pr_a, url_a, _ = start_app(home_a)
    try:
        r1, c1 = post_trade(url_a, "XAUUSD", "صعودی")
        r2, c2 = post_trade(url_a, "EURUSD", "نزولی", entry="1.1000", sl="1.1050",
                            tp="1.0900")
        check("دستگاهِ مبدأ: دو ردیف ژورنال ثبت شد",
              c1 == 200 and c2 == 200 and r1.get("added") == "1" and r2.get("added") == "2",
              f"{r1} {r2}")
        ra1, _ = post_json(url_a, "/api/alarm", {"symbol": "XAUUSD", "mode": "price",
                                                 "target": 2500, "cross": "up"})
        ra2, _ = post_json(url_a, "/api/alarm", {"symbol": "EURUSD", "mode": "ote",
                                                 "low": 1.08, "high": 1.10})
        check("دستگاهِ مبدأ: دو آلارم ثبت شد", bool(ra1.get("added")) and bool(ra2.get("added")),
              f"{ra1} {ra2}")
        check("دستگاهِ مبدأ: شناسهٔ دو آلارم یکتاست (برخوردِ میلی‌ثانیه‌ای رفع شده)",
              ra1.get("added") != ra2.get("added"), f"{ra1.get('added')} / {ra2.get('added')}")
        rs, cs = post_json(url_a, "/api/risk", {"balance": 25000, "risk_pct": 0.5,
                                                "daily_loss_limit_pct": 2.0,
                                                "max_open_risk_pct": 4.5})
        check("دستگاهِ مبدأ: تنظیماتِ ریسک ذخیره شد",
              cs == 200 and rs.get("ok") and abs(rs["settings"]["balance"] - 25000) < 1e-6,
              str(rs)[:160])

        bundle, code = get_json(url_a, "/api/export")
        check("برون‌بری: نشان/نسخه/شمارش درست است",
              code == 200 and bundle.get("kind") == "pipfound-backup"
              and bundle.get("version") == 1
              and bundle.get("counts") == {"journal": 2, "alarms": 2},
              str(bundle)[:200])
        check("برون‌بری: فیلدهای دفتر همراهِ بسته می‌آید",
              bundle.get("journal_fields") == FIELDS, str(bundle.get("journal_fields"))[:120])
        check("برون‌بری: هر دو ردیف با مقادیرشان آمده",
              {r["symbol"] for r in bundle["journal"]} == {"XAUUSD", "EURUSD"}
              and bundle["journal"][0]["entry"] == "2400", str(bundle["journal"])[:200])
        check("برون‌بری: هر دو آلارم آمده",
              {a["symbol"] for a in bundle["alarms"]} == {"XAUUSD", "EURUSD"},
              str(bundle["alarms"])[:200])
        check("برون‌بری: تنظیمات آمده",
              abs(bundle["settings"].get("balance", 0) - 25000) < 1e-6,
              str(bundle["settings"]))
    finally:
        stop(pr_a)

    pr_b, url_b, _ = start_app(home_b)
    try:
        jfile_b = os.path.join(home_b, "pipfound", "journal.csv")
        afile_b = os.path.join(home_b, "pipfound", "alarms.json")
        rfile_b = os.path.join(home_b, "pipfound", "risk.json")
        # یک ردیفِ محلیِ دستگاهِ مقصد — درون‌بری نباید پاکش کند
        rl, _ = post_trade(url_b, "GBPUSD", "صعودی")
        check("دستگاهِ مقصد: ردیفِ محلی ثبت شد", rl.get("added") == "1", str(rl))

        res, code = post_json(url_b, "/api/import", raw=json.dumps(bundle).encode("utf-8"))
        check("درون‌بری: ۲۰۰ و ok با شمارش‌های درست",
              code == 200 and res.get("ok") and res.get("journal_added") == 2
              and res.get("alarms_added") == 2 and res.get("settings_applied") is True,
              f"{code} {str(res)[:200]}")
        rows_b = read_rows(jfile_b)
        check("درون‌بری: ژورنالِ مقصد ۳ ردیف دارد (۱ محلی + ۲ واردشده)",
              len(rows_b) == 3, str([r["symbol"] for r in rows_b]))
        check("درون‌بری: ردیفِ محلی (GBPUSD) پاک نشده",
              any(r["symbol"] == "GBPUSD" for r in rows_b), str([r["symbol"] for r in rows_b]))
        imp = [r for r in rows_b if r["symbol"] in ("XAUUSD", "EURUSD")]
        check("درون‌بری: مقادیرِ ردیف‌های واردشده دست‌نخورده است",
              len(imp) == 2 and imp[0]["entry"] == "2400" and imp[0]["direction"] == "long"
              and imp[1]["entry"] == "1.1000" and imp[1]["direction"] == "short",
              str(imp)[:240])
        check("درون‌بری: شناسه‌ها ادامه یافته‌اند (نه برخورد)",
              sorted(int(r["id"]) for r in rows_b) == [1, 2, 3],
              str([r["id"] for r in rows_b]))
        al_b = json.load(open(afile_b, encoding="utf-8"))
        check("درون‌بری: هر دو آلارم روی مقصد نشسته",
              len(al_b) == 2 and {a["symbol"] for a in al_b} == {"XAUUSD", "EURUSD"},
              str(al_b)[:200])
        st_b = json.load(open(rfile_b, encoding="utf-8"))
        check("درون‌بری: تنظیماتِ ریسک اعمال شد",
              abs(float(st_b.get("balance", 0)) - 25000) < 1e-6
              and abs(float(st_b.get("risk_pct", 0)) - 0.5) < 1e-6, str(st_b))

        res2, code2 = post_json(url_b, "/api/import", raw=json.dumps(bundle).encode("utf-8"))
        check("تکرارپذیری: درون‌بریِ دوباره «۰ افزوده» می‌دهد",
              code2 == 200 and res2.get("journal_added") == 0
              and res2.get("journal_skipped") == 2 and res2.get("alarms_added") == 0
              and res2.get("alarms_skipped") == 2, f"{code2} {str(res2)[:200]}")
        check("تکرارپذیری: شمارِ ردیف‌ها عوض نشده", len(read_rows(jfile_b)) == 3, "")

        bundle_b, _ = get_json(url_b, "/api/export")
        ja = sorted((r["datetime"], r["symbol"], r["direction"], r["entry"])
                    for r in bundle["journal"])
        jb = sorted((r["datetime"], r["symbol"], r["direction"], r["entry"])
                    for r in bundle_b["journal"] if r["symbol"] != "GBPUSD")
        check("رفت‌وبرگشت: ردیف‌های بستهٔ A عیناً در بستهٔ B هست", ja == jb,
              f"A={ja} B={jb}")
        check("رفت‌وبرگشت: آلارم‌های بستهٔ A عیناً در بستهٔ B هست",
              sorted(json.dumps(a, sort_keys=True, ensure_ascii=False) for a in bundle["alarms"])
              == sorted(json.dumps(a, sort_keys=True, ensure_ascii=False) for a in bundle_b["alarms"]),
              "")
        check("رفت‌وبرگشت: تنظیماتِ بستهٔ A در بستهٔ B هست",
              all(bundle_b["settings"].get(k) == v for k, v in bundle["settings"].items()),
              f"A={bundle['settings']} B={bundle_b['settings']}")

        # ── اعتبارسنجیِ پیش از نوشتن: بستهٔ خراب نباید هیچ فایلی را عوض کند ──
        before = {p: open(p, "rb").read() for p in (jfile_b, afile_b, rfile_b)}
        cases = []
        d = json.loads(json.dumps(bundle)); d["kind"] = "other"
        cases.append(("نشانِ غلط", d))
        d = json.loads(json.dumps(bundle)); d["version"] = 99
        cases.append(("نسخهٔ غلط", d))
        d = json.loads(json.dumps(bundle)); d["journal"].append({"symbol": ""})
        cases.append(("ردیفِ بی‌نماد", d))
        d = json.loads(json.dumps(bundle)); d["journal"][0]["new_col"] = "x"
        cases.append(("فیلدِ ناشناخته", d))
        d = json.loads(json.dumps(bundle)); d["settings"]["balance"] = -1
        cases.append(("تنظیماتِ منفی", d))
        ok_reject = True
        for label, payload in cases:
            rj, cd = post_json(url_b, "/api/import", raw=json.dumps(payload).encode("utf-8"))
            if cd != 400 or rj.get("ok") is not False or not rj.get("errors"):
                ok_reject = False
                NOTES.append(f"↳ «{label}» انتظارِ ۴۰۰ نداشت: {cd} {str(rj)[:120]}")
        check("اعتبارسنجی: پنج بستهٔ خراب با ۴۰۰ و فهرستِ خطا رد شدند", ok_reject, "")
        rj, cd = post_json(url_b, "/api/import", raw=b"{not json")
        check("اعتبارسنجی: بدنهٔ غیرِJSON با ۴۰۰ رد می‌شود", cd == 400, f"{cd} {rj}")
        after = {p: open(p, "rb").read() for p in (jfile_b, afile_b, rfile_b)}
        check("اعتبارسنجی: رد شدن‌ها هیچ فایلی را عوض نکرد", before == after, "")
        # بدنهٔ خراب ولی معتبر (سالم) هم باید بی‌خطر بماند؟ نه — اینجا فقط ردِ خراب سنجیده شد.
        check("فایلِ ژورنال روی مقصد هنوز سالم است", len(read_rows(jfile_b)) == 3, "")
    finally:
        stop(pr_b)
except Exception as e:
    FAILS.append(("اجرای رفت‌وبرگشت با استثنا متوقف شد", repr(e)))
finally:
    for pr in procs:
        stop(pr)


# ══════════════ ۳) جهش‌آزماییِ قاعدهٔ نگهبان ══════════════
def run_guard(app_src=None, backup_src=None):
    d = tempfile.mkdtemp(prefix="pf_bk_mut_")
    try:
        with open(os.path.join(d, "app.py"), "w", encoding="utf-8") as f:
            f.write(app_src if app_src is not None else SOURCE)
        with open(os.path.join(d, "backup.py"), "w", encoding="utf-8") as f:
            f.write(backup_src if backup_src is not None else BSOURCE)
        pages = SC.page_sources(d)
        probs, stats = SC.backup_problems(d, pages)
        return probs, stats, pages
    finally:
        shutil.rmtree(d, ignore_errors=True)


p0, s0, pages0 = run_guard()
check("جهش‌آزمایی: مخزنِ سالم صفر خطا و هر چهار پرچم سبز",
      p0 == [] and all(s0.get(k) for k in ("endpoints", "validate_first", "atomic", "controls")),
      f"{p0} {s0}")
check("جهش‌آزمایی: هارنس واقعاً صفحه را می‌خواند", bool(pages0), str(list(pages0)))


def red(name, needle, app_src=None, backup_src=None):
    probs, _, _ = run_guard(app_src=app_src, backup_src=backup_src)
    check("جهشِ سرخ | " + name, any(needle in x for x in probs), str(probs)[:200])


def green(name, app_src=None, backup_src=None):
    probs, _, _ = run_guard(app_src=app_src, backup_src=backup_src)
    check("جهشِ سبز | " + name, probs == [], str(probs)[:200])


red("برداشتنِ مسیرِ برون‌بری", "مسیرِ /api/export",
    app_src=SOURCE.replace('u.path == "/api/export"', 'u.path == "/api/export-old"', 1))
red("برداشتنِ مسیرِ درون‌بری", "مسیرِ /api/import",
    app_src=SOURCE.replace('u.path == "/api/import"', 'u.path == "/api/import-old"', 1))
# دقت: این دو مسیر ممکن است در صفحه **چند صدا‌زن** داشته باشند (مثلاً برگرداندنِ
# نسخهٔ خودکار هم از `/api/import` می‌رود). جهش باید همهٔ رخدادها را بردارد
# وگرنه یک صدا‌زنِ باقی‌مانده قاعده را سبز نگه می‌دارد و جهش بی‌صدا (ناوَکوم) می‌شود.
red("قطع‌کردنِ صدا‌زدنِ برون‌بری از JS", "JS مسیرِ برون‌بری",
    app_src=SOURCE.replace('fetch("/api/export"', 'fetch("/api/exportOld"'))
red("قطع‌کردنِ صدا‌زدنِ درون‌بری از JS", "JS مسیرِ درون‌بری",
    app_src=SOURCE.replace('fetch("/api/import"', 'fetch("/api/importOld"'))
red("برداشتنِ بخشِ settings از build", "settings",
    backup_src=BSOURCE.replace('"settings": st,', '"settingsX": st,', 1))
red("حذفِ بررسیِ KIND از validate", "KIND",
    backup_src=BSOURCE.replace('if doc.get("kind") != KIND:', "if False:", 1))
red("حذفِ فراخوانیِ اعتبارسنجی",
    "اعتبارسنجی نمی‌کند",
    app_src=SOURCE.replace("probs = BK.validate(doc, _journal_fields())",
                           "probs = []  # اعتبارسنجی برداشته شد", 1))
red("نوشتن پیش از اعتبارسنجی", "اول می‌نویسد",
    app_src=SOURCE.replace("probs = BK.validate(doc, _journal_fields())",
                           "_save_alarms(_load_alarms())\n        probs = BK.validate(doc, _journal_fields())", 1))
red("غیرِاتمیک‌کردنِ بازنویسیِ دفتر", "اتمیک نیست",
    app_src=SOURCE.replace("    os.replace(tmp, path)\n    return path",
                           "    os.rename(tmp, path)\n    return path", 1))
red("برداشتنِ هندلرِ درون‌بری", "هندلرِ _handle_import",
    app_src=SOURCE.replace("def _handle_import(self, doc):",
                           "def _handle_import_disabled(self, doc):", 1))
red("برداشتنِ کنترلِ فایلِ درون‌بری", "فایلِ درون‌بری",
    app_src=SOURCE.replace('id="impFile"', 'id="impFileX"', 1))
red("قطع‌کردنِ سیمِ دکمهٔ برون‌بری", "به JS وصل نشده",
    app_src=SOURCE.replace('getElementById("expBtn")', 'getElementById("expBtnGhost")', 1))
red("حذفِ ماژولِ backup.py", "backup.py خوانده نشد", backup_src="")

green("جابه‌جاییِ ترتیبِ کلیدهای بسته",
      backup_src=BSOURCE.replace('"journal": rows,\n        "alarms": al,',
                                 '"alarms": al,\n        "journal": rows,', 1))
green("افزودنِ فیلدِ تازه به بسته (سازگار)",
      backup_src=BSOURCE.replace('"kind": KIND,',
                                 '"kind": KIND,\n        "app": "pipfound",', 1))
green("کامنتِ بی‌گناه در هندلرِ درون‌بری",
      app_src=SOURCE.replace("probs = BK.validate(doc, _journal_fields())",
                             "# یادداشتِ بی‌گناه\n        probs = BK.validate(doc, _journal_fields())", 1))
green("تغییرِ پسوندِ فایلِ موقت (اتمیک می‌مانَد)",
      app_src=SOURCE.replace('tmp = path + ".tmp"', 'tmp = path + ".part"', 1))
green("کامنتِ بی‌گناه در validate",
      backup_src=BSOURCE.replace("    fields = list(fields)\n    p = []",
                                 "    fields = list(fields)\n    p = []  # فهرستِ خطاها", 1))


# ── گزارش ──
for n in NOTES:
    print(n)
print(f"• بررسی‌ها: {len(CHECKS)}")
if FAILS:
    print("")
    for name, detail in FAILS:
        print(f"::error::❌ {name}" + (f" — {detail}" if detail else ""))
    print(f"\n❌ تستِ انتقالِ داده رد شد — {len(FAILS)} از {len(CHECKS)} بررسی شکست خورد")
    sys.exit(1)
print("✅ تستِ انتقالِ داده پاس شد — رفت‌وبرگشتِ ژورنال/آلارم/تنظیمات، اعتبارسنجیِ "
      "پیش از نوشتن، و جهش‌آزماییِ قاعدهٔ نگهبان")
