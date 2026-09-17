#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تستِ ری‌استارتِ خودکارِ «کدِ کهنه» — تا سرور هرگز بی‌صدا نسخه‌ی قدیمی را سرو نکند.

چه چیزی را ثابت می‌کند (فقط stdlib، روی **کپیِ موقتِ** پروژه و پورتِ تصادفی، پس به کد و
سرورِ واقعیِ کاربر دست نمی‌زند):
  A) ری‌استارتِ واقعی: بعد از تغییرِ کدِ روی دیسک، سرور خودش را در **همان PID**
     (`os.execv`) از نو اجرا می‌کند، کدِ تازه واقعاً سرو می‌شود (مارکر در صفحه دیده
     می‌شود) و ری‌استارتِ تکراری/حلقه‌ای رخ نمی‌دهد.
  B) محافظت در برابرِ کدِ خراب: اگر کدِ تازه روی دیسک سالم نباشد (مثلاً SyntaxError)،
     سرورِ سالم **کشته نمی‌شود** و ری‌استارت نمی‌کند؛ به‌محضِ سالم شدنِ فایل، خودش
     ترمیم می‌شود.
  C) ری‌استارتِ تمیز: تا وقتی درخواستی در جریان است صبر می‌کند و وسطِ کار قطع نمی‌کند.

اجرا:  python3 autorestart_test.py     (خروجی: ۰ سالم، ۱ خراب)
"""
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
META = '<meta charset="utf-8">'          # نشانه‌ی ASCII یکتا در HTMLِ صفحه‌ی اصلی
TMPDIRS = []
PROCS = []
problems = []
notes = []

# تنظیماتِ سریع برای تست (در تولید پیش‌فرض: ۵ ثانیه فاصله، ۳ ثانیه settle)
FAST = {
    "PIPFOUND_AUTORESTART": "1",
    "PIPFOUND_AUTORESTART_INTERVAL": "1",
    "PIPFOUND_AUTORESTART_SETTLE": "1",
    "PIPFOUND_AUTORESTART_MAXWAIT": "20",
}


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


def copy_tree():
    """یک کپیِ کاملِ پوشه‌ی اسکریپت‌ها در پوشه‌ی موقت (بدونِ .git) تا بتوان آزادانه خرابش کرد."""
    work = tempfile.mkdtemp(prefix="pf_rev_")
    TMPDIRS.append(work)
    dst = os.path.join(work, "scripts")
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", "*.pyc", "*.log", "browsers", "node_modules"))
    home = os.path.join(work, "home")
    os.makedirs(home)
    return dst, home


def start(app_dir, home, env_extra=None):
    env = dict(os.environ)
    env["HOME"] = home
    env.pop("PIPFOUND_JOURNAL_DIR", None)
    env["PIPFOUND_JOURNAL_CSV"] = os.path.join(home, "journal.csv")
    env.update(FAST)
    if env_extra:
        env.update(env_extra)
    port = free_port()
    log = os.path.join(home, "server.log")
    fh = open(log, "w")
    pr = subprocess.Popen([sys.executable, "-u", os.path.join(app_dir, "app.py"),
                           "--port", str(port)],
                          cwd=app_dir, env=env, stdout=fh, stderr=subprocess.STDOUT)
    PROCS.append(pr)
    url = "http://127.0.0.1:%d" % port
    wait_up(url, pr, log)
    return pr, url, log, port


def tail(log, n=1200):
    try:
        with io.open(log, encoding="utf-8", errors="replace") as f:
            return f.read()[-n:]
    except Exception:
        return "(لاگ خوانده نشد)"


def wait_up(url, pr, log, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if pr.poll() is not None:
            raise RuntimeError("سرور بالا نیامد (خروجِ زودهنگام):\n" + tail(log))
        try:
            if rev(url).get("ok"):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    raise RuntimeError("سرور در مهلتِ مقرر بالا نیامد:\n" + tail(log))


def rev(url, timeout=3):
    with urllib.request.urlopen(url + "/api/revision", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def rev_soft(url):
    """مثلِ rev ولی در پنجره‌ی ری‌استارت (اتصال قطع) None می‌دهد."""
    try:
        return rev(url)
    except Exception:
        return None


def page(url, timeout=5):
    with urllib.request.urlopen(url + "/", timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def wait_restart(url, boot0, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        j = rev_soft(url)
        if j and j.get("boot_ts") and j["boot_ts"] != boot0:
            return j
        time.sleep(0.4)
    return None


def add_marker(app_dir, marker):
    """یک تغییرِ واقعی در کدِ سرو‌شده: کامنتِ HTML در head (سینتکس را خراب نمی‌کند)."""
    fp = os.path.join(app_dir, "app.py")
    with io.open(fp, encoding="utf-8") as f:
        s = f.read()
    if META not in s:
        raise RuntimeError("نشانه‌ی ASCII برای تغییرِ صفحه پیدا نشد")
    with io.open(fp, "w", encoding="utf-8") as f:
        f.write(s.replace(META, META + "<!--" + marker + "-->", 1))
    return fp


def stop_all():
    for pr in PROCS:
        try:
            pr.terminate()
            pr.wait(timeout=8)
        except Exception:
            try:
                pr.kill()
            except Exception:
                pass


# ────────────────────────────── A) ری‌استارتِ واقعی ──────────────────────────────
def case_real_restart():
    app_dir, home = copy_tree()
    pr, url, log, _ = start(app_dir, home)
    j0 = rev(url)
    check(j0.get("stale") is False, "شروعِ سالم: stale=false")
    check(bool((j0.get("autorestart") or {}).get("enabled")),
          "ری‌استارتِ خودکار به‌صورتِ پیش‌فرض روشن است")
    boot0, pid0 = j0["boot_ts"], j0["pid"]

    marker = "REV-A-%d" % int(time.time())
    add_marker(app_dir, marker)

    j1 = wait_restart(url, boot0)
    if not check(j1 is not None, "سرور پس از تغییرِ کد، خودش را از نو اجرا کرد"):
        notes.append("لاگ:\n" + tail(log))
        return
    check(j1["pid"] == pid0,
          "PID عوض نشد (execv) — ثبتِ پیش‌نمایش و جابِ launchd معتبر می‌مانند")
    check(j1.get("stale") is False, "بعد از ری‌استارت، stale=false شد")
    check(marker in page(url), "کدِ تازه واقعاً سرو می‌شود (مارکر در صفحه دیده شد)")
    check(os.path.isfile(os.path.join(home, "pipfound", "autorestart.json")),
          "وضعیتِ آخرین ری‌استارت در فایل ثبت شد")
    last = ((j1.get("autorestart") or {}).get("last") or {})
    check(bool(last.get("at")), "آخرین ری‌استارت از /api/revision گزارش می‌شود")
    check(bool(last.get("files")), "فایلِ عاملِ ری‌استارت در گزارش آمده: %s" % (last.get("files"),))

    # نباید حلقه‌ی ری‌استارت بسازد
    at = last.get("at")
    time.sleep(6)
    j2 = rev(url)
    check((((j2.get("autorestart") or {}).get("last") or {}).get("at")) == at,
          "ری‌استارتِ تکراری/حلقه‌ای رخ نداد (فقط یک‌بار)")
    check(j2.get("stale") is False, "کدِ سرو‌شده پایدار و به‌روز ماند")


# ─────────────────────── B) کدِ خراب: هیچ ری‌استارتی نمی‌شود ───────────────────────
def case_broken_code_stays_alive():
    app_dir, home = copy_tree()
    pr, url, log, _ = start(app_dir, home)
    j0 = rev(url)
    boot0, pid0 = j0["boot_ts"], j0["pid"]
    fp = os.path.join(app_dir, "app.py")
    with io.open(fp, encoding="utf-8") as f:
        original = f.read()

    # یک تغییرِ واقعی ولی **خراب** روی دیسک (همان کلاسی از خرابی که کلِ صفحه را می‌کشد)
    with io.open(fp, "a", encoding="utf-8") as f:
        f.write('\nmarker = "unterminated\n')

    # صبر کن تا watcher ببیند و اعتبارسنجی کند
    blocked = None
    for _ in range(30):
        time.sleep(1)
        j = rev_soft(url)
        if j and ((j.get("autorestart") or {}).get("blocked")):
            blocked = j
            break
    if not check(blocked is not None, "کدِ خرابِ تازه تشخیص داده شد و ری‌استارت متوقف ماند"):
        notes.append("لاگ:\n" + tail(log))
        return
    check(blocked.get("stale") is True, "وضعیت به‌درستی stale=true گزارش شد")
    check(pr.poll() is None, "پروسه‌ی سالم کشته نشد (زنده ماند)")
    check(rev_soft(url) is not None and page(url).count("id=\"go\""),
          "سرور همچنان صفحه‌ی سالم را سرو می‌کند")
    check(rev(url)["boot_ts"] == boot0, "هیچ ری‌استارتی روی کدِ خراب انجام نشد")
    check("ری‌استارت انجام نمی‌شود" in (rev(url).get("note") or ""),
          "پیامِ وضعیت توضیح می‌دهد که چرا ری‌استارت نشد: %s" % rev(url).get("note"))

    # حالا فایل را سالم کن → باید خودش ترمیم شود
    with io.open(fp, "w", encoding="utf-8") as f:
        f.write(original)
    j1 = wait_restart(url, boot0)
    if check(j1 is not None, "پس از سالم شدنِ فایل، خودش را از نو اجرا کرد"):
        check(j1["pid"] == pid0, "PID در ترمیمِ خودکار هم ثابت ماند")
        check(j1.get("stale") is False, "بعد از ترمیم، stale=false شد")
        check(not ((j1.get("autorestart") or {}).get("blocked")),
              "وضعیتِ «متوقف» پاک شد")


# ───────────────── C) وسطِ درخواست قطع نمی‌کند (ری‌استارتِ تمیز) ─────────────────
def case_in_flight_request():
    app_dir, home = copy_tree()
    pr, url, log, port = start(app_dir, home,
                               {"PIPFOUND_AUTORESTART_MAXWAIT": "60"})
    j0 = rev(url)
    boot0, pid0 = j0["boot_ts"], j0["pid"]

    # یک درخواستِ نیمه‌کاره باز نگه دار: بدنه‌ی آن هرگز کامل نمی‌شود،
    # پس سرور تا زمانی که سوکت باز است در حالِ پردازشِ درخواست می‌ماند.
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    s.sendall(b"POST /api/journal HTTP/1.1\r\nHost: 127.0.0.1\r\n"
              b"Content-Type: application/json\r\nContent-Length: 999\r\n\r\n"
              b'{"partial":')
    time.sleep(0.6)

    add_marker(app_dir, "REV-C-%d" % int(time.time()))
    time.sleep(9)   # با interval=1 و settle=1، اگر منتظرِ idle نمی‌ماند تا الان ری‌استارت کرده بود

    j = rev_soft(url)
    check(j is not None and j["boot_ts"] == boot0,
          "تا وقتی درخواستی در جریان است، ری‌استارت انجام نشد (وسطِ کار قطع نمی‌شود)")
    if j:
        check(((j.get("autorestart") or {}).get("waiting")) in (True, False),
              "وضعیتِ «منتظرِ تمام شدنِ درخواست» در /api/revision گزارش می‌شود")

    try:
        s.close()
    except Exception:
        pass
    j1 = wait_restart(url, boot0, timeout=60)
    if check(j1 is not None, "به‌محضِ تمام شدنِ درخواست، ری‌استارت انجام شد"):
        check(j1["pid"] == pid0, "PID بعد از ری‌استارتِ تمیز هم ثابت ماند")


def main():
    try:
        case_real_restart()
        case_broken_code_stays_alive()
        case_in_flight_request()
    finally:
        stop_all()
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)

    for n in notes:
        print("• " + n)
    if problems:
        print("")
        for p in problems:
            print("::error::" + p)
        print("\n❌ تستِ ری‌استارتِ خودکار رد شد — %d مشکل" % len(problems))
        return 1
    print("\n✅ تستِ ری‌استارتِ خودکار پاس شد: ری‌استارتِ واقعی، محافظت از کدِ خراب، "
          "و ری‌استارتِ تمیز (بدونِ قطعِ درخواستِ در جریان)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
