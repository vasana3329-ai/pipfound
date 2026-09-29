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
  D) کامیتی که هیچ فایلِ تعیین‌کننده‌ای را لمس نمی‌کند (فقط SHA) هم ری‌استارت می‌آورد.
  E) **اصلاحِ خودِ نگهبان پذیرفته می‌شود:** `selfcheck.py` روی دیسک عوض شود و
     نسخهٔ کهنه‌ی درونِ حافظه رد کند ⇒ باید نسخهٔ تازه را بپذیرد و ری‌استارت کند
     (باگِ قفلِ خودارجاع: سنجیدنِ رکوردِ تازه با قوانینِ بوت‌شده).

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


# ── D) ری‌استارتِ «فقط SHA عوض شده» (رگرسیونِ نسخه‌ی کهنه‌ای که تا ابد می‌ماند) ──
def _git_env(home):
    env = dict(os.environ)
    env["HOME"] = home
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.path.join(home, "empty.gitconfig")
    open(env["GIT_CONFIG_GLOBAL"], "w").close()
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@example.invalid"),
                 ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@example.invalid")):
        env[k] = v
    return env


def case_sha_drift_restart():
    """کامیتی که هیچ فایلِ تعیین‌کننده‌ی رابط را لمس نمی‌کند.

    باگِ واقعی که این تست قفل می‌کند: محرکِ ری‌استارت فقط mtimeِ فهرستِ ثابتِ فایل‌ها
    بود؛ پس اگر کامیتی فقط مستندات/CI/ابزار را عوض می‌کرد، پروسه تا ابد «کهنه»
    می‌ماند و چیپ می‌گفت «ری‌استارت در راه است» بدونِ اینکه هیچ‌وقت بیاید.
    """
    app_dir, home = copy_tree()
    genv = _git_env(home)
    for args in (["init", "-q", "-b", "main", "."],
                 ["add", "-A"],
                 ["commit", "-q", "-m", "c0: نقطه‌ی شروع"]):
        subprocess.run(["git"] + args, cwd=app_dir, env=genv, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    pr, url, log, _ = start(app_dir, home)
    j0 = rev(url)
    check(j0.get("stale") is False, "SHA-drift: شروعِ سالم stale=false")
    check(not (j0.get("changed_files") or []),
          "SHA-drift: هیچ فایلِ تعیین‌کننده‌ای تازه نشده")
    check((j0.get("disk") or {}).get("sha") == (j0.get("loaded") or {}).get("sha"),
          "SHA-drift: SHAِ بارشده با دیسک یکی است")
    boot0, pid0 = j0["boot_ts"], j0["pid"]
    mtimes0 = {f["file"]: f["mtime_epoch"] for f in (j0.get("tracked_files") or [])}

    # کامیتِ خالی: SHA عوض می‌شود ولی mtimeِ هیچ فایلی تغییر نمی‌کند
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "c1: فقط SHA"],
                   cwd=app_dir, env=genv, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    j1 = wait_restart(url, boot0, timeout=60)
    if check(j1 is not None,
             "SHA-driftِ تنها هم ری‌استارت می‌آورد (باگِ قبلی: تا ابد کهنه می‌ماند)"):
        check(j1["pid"] == pid0, "PID بعد از ری‌استارتِ SHA ثابت ماند")
        check(j1.get("stale") is False, "بعد از ری‌استارت، stale=false شد")
        check(not (j1.get("changed_files") or []),
              "هنوز هیچ فایلِ تعیین‌کننده‌ای تازه نیست (محرک واقعاً SHA بود)")
        check((j1.get("disk") or {}).get("sha") == (j1.get("loaded") or {}).get("sha"),
              "SHAِ بارشده روی دیسک نشست")
        now = {f["file"]: f["mtime_epoch"] for f in (j1.get("tracked_files") or [])}
        check(now == mtimes0, "mtimeِ هیچ فایلِ ردیابی‌شده‌ای عوض نشده بود")
    check("فقط SHA عوض شده" in tail(log),
          "لاگ صریحاً می‌گوید علتِ ری‌استارت «فقط SHA» بود")


# ── D2) پرچمِ صداقت در جهتِ *مخالف*: وقتی ری‌استارت خاموش است، باید «کهنه» بماند ──
# موردِ D ثابت می‌کند دریفتِ SHA ری‌استارت می‌آورد. این مورد عمداً **خلافش** را
# قفل می‌کند، چون خطرِ اصلی در آن جهت است، نه این یکی: با `PIPFOUND_AUTORESTART=0`
# چیپ نباید قولِ ری‌استارتِ «به‌زودی» بدهد، نباید SHAِ تازه را بی‌ری‌استارت
# «بپذیرد»، و از همه مهم‌تر **نباید بی‌صدا سبز شود** (کدِ کهنه سرو شود ولی
# stale=false) — آن حالت بدترین شکلِ دروغ است: کاربر فکر می‌کند کدِ تازه را
# می‌بیند. در کلِ پنجره‌ی مشاهده هم ناوردایی باید برقرار بماند:
# ‎stale == (تغییرِ فایلِ ردیابی‌شده یا دریفتِ SHA).
# این مورد با «بالا آوردنِ دوباره» تمام می‌شود تا ثابت شود آن کهنه‌ماندنِ
# عمدی هیچ زهرِ ماندگاری ندارد.
def case_drift_flag_honesty():
    app_dir, home = copy_tree()
    genv = _git_env(home)
    for args in (["init", "-q", "-b", "main", "."], ["add", "-A"],
                 ["commit", "-q", "-m", "c0: نقطه‌ی شروع"]):
        subprocess.run(["git"] + args, cwd=app_dir, env=genv, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    pr, url, log, _ = start(app_dir, home,
                            env_extra={"PIPFOUND_AUTORESTART": "0"})
    j0 = rev(url)
    check(j0.get("stale") is False, "پرچمِ صداقت: شروعِ سالم stale=false")
    check((j0.get("autorestart") or {}).get("enabled") is False,
          "پرچمِ صداقت: ری‌استارتِ خودکار واقعاً خاموش است")
    boot0, pid0 = j0["boot_ts"], j0["pid"]
    sha0 = (j0.get("loaded") or {}).get("sha")

    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "c1: فقط SHA"],
                   cwd=app_dir, env=genv, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # چند نمونه در پنجره‌ای (کوتاه‌ترش) بیشتر از فاصله+settle — و در تمام آن
    # پنجره هیچ‌وقت نباید ری‌استارت/قطعی رخ بدهد.
    samples, dead = [], 0
    end = time.time() + 6
    while time.time() < end:
        s = rev_soft(url)
        if s is None:
            dead += 1
        else:
            samples.append(s)
        time.sleep(0.5)
    check(dead == 0,
          "پرچمِ صداقت: با ری‌استارتِ خاموش هیچ قطعی/ری‌استارتی رخ نداد")
    check(len(samples) >= 5,
          "پرچمِ صداقت: نمونه‌های کافی برای سنجشِ ناوردایی گرفته شد")
    bad_inv, bad_drift, lied_green = [], [], []
    for s in samples:
        changed, reported = bool(s.get("changed_files")), bool(s.get("sha_drift"))
        # حقیقتِ مستقل: از خودِ SHAها حساب می‌شود، نه از فیلدِ گزارش‌شده — وگرنه
        # یک `sha_drift`ِ دروغ از تور رد می‌شود. (همین ضعف را کنترلِ منفیِ موردِ
        # D3 لو داد: با دروغگو کردنِ `sha_drift` آن بررسی سبز می‌ماند.)
        truth = changed or ((s.get("disk") or {}).get("sha")
                            != (s.get("loaded") or {}).get("sha"))
        if bool(s.get("stale")) != (changed or reported):
            bad_inv.append(s)
        if reported != ((s.get("disk") or {}).get("sha")
                        != (s.get("loaded") or {}).get("sha")):
            bad_drift.append(s)
        if truth and s.get("stale") is False:
            lied_green.append(s)
    check(not bad_inv,
          "ناورداییِ پرچم در همه‌ی نمونه‌ها: stale == (تغییرِ فایل یا دریفتِ SHA)")
    check(not bad_drift,
          "ناورداییِ دریفت در همه‌ی نمونه‌ها: sha_drift == (SHAِ دیسک ≠ SHAِ بارشده)")
    check(not lied_green,
          "هرگز سبزِ دروغ نداد: کدِ کهنه سرو شد ولی stale=false نگفت")

    j1 = rev(url)
    check(j1.get("pid") == pid0 and j1["boot_ts"] == boot0,
          "پرچمِ صداقت: پروسه حتی یک بار هم ری‌استارت نشد")
    check((j1.get("autorestart") or {}).get("restarts") == 0,
          "پرچمِ صداقت: شمارنده‌ی ری‌استارت صفر ماند")
    check(j1.get("stale") is True,
          "پرچمِ صداقت: «کهنه» صادقانه true ماند (نه سبزِ دروغ)")
    check(j1.get("sha_drift") is True, "پرچمِ صداقت: دریفتِ SHA گزارش می‌شود")
    check(not (j1.get("changed_files") or []),
          "پرچمِ صداقت: هیچ فایلِ ردیابی‌شده‌ای تازه نشده")
    check((j1.get("loaded") or {}).get("sha") == sha0,
          "پرچمِ صداقت: SHAِ تازه بی‌ری‌استارت «پذیرفته» نشد")
    note = j1.get("note") or ""
    check("خاموش" in note,
          "پرچمِ صداقت: یادداشت می‌گوید ری‌استارتِ خودکار خاموش است")
    check("به‌زودی" not in note,
          "پرچمِ صداقت: یادداشت قولِ «به‌زودی» نمی‌دهد")

    # هیچ زهرِ ماندگاری نباشد: بالا آوردنِ دوباره‌ی همان پوشه (با ری‌استارتِ روشن)
    # باید تمیز باشد و SHAِ دیسک را صادقانه بار کند.
    try:
        pr.terminate()
        pr.wait(timeout=8)
    except Exception:
        try:
            pr.kill()
        except Exception:
            pass
    pr2, url2, log2, _ = start(app_dir, home)
    j2 = rev(url2)
    check(j2.get("stale") is False,
          "پرچمِ صداقت: بالا آوردنِ دوباره تمیز است (stale=false)")
    check((j2.get("loaded") or {}).get("sha") == (j2.get("disk") or {}).get("sha"),
          "پرچمِ صداقت: بعد از بالا آوردنِ دوباره، SHAِ دیسک بار شد")
    check(j2.get("pid") != pid0, "پرچمِ صداقت: پروسه‌ی تازه PIDِ تازه دارد")


# ── D3) کنترلِ منفی: آیا ادعاهای صداقتِ موردِ D2 واقعاً دندان دارند؟ ─────────────
# قاعدهٔ خودِ این مخزن: گیتی که هرگز نشکسته، گیت نیست. اینجا پرچم را عمداً
# دروغگو می‌کنیم — `sha_drift` را در کدِ سندباکس `False` می‌کنیم، یعنی همان بدترین
# حالت: کدِ کهنه سرو می‌شود ولی چیپ می‌گوید تازه است. اگر موردِ D2 روی همین کدِ
# دروغگو هم سبز می‌مانْد، آن مورد هیچ‌چیز را قفل نکرده بود. (همین کنترل بود که
# فهمید بررسیِ «سبزِ دروغ» باید از حقیقتِ SHAها بسنجد، نه از فیلدِ گزارش‌شده.)
LIE_FROM = '    sha_drift = (disk_git.get("sha") or None) != (loaded.get("sha") or None)'
LIE_TO = '    sha_drift = False  # (جهشِ عمدیِ کنترلِ منفی)'


def case_flag_lie_is_caught():
    app_dir, home = copy_tree()
    fp = os.path.join(app_dir, "app.py")
    with io.open(fp, encoding="utf-8") as f:
        src = f.read()
    n = src.count(LIE_FROM)
    if not check(n == 1, "کنترلِ منفی: نشانه‌ی جهش دقیقاً یک‌بار پیدا شد (%d)" % n):
        return
    with io.open(fp, "w", encoding="utf-8") as f:
        f.write(src.replace(LIE_FROM, LIE_TO, 1))

    genv = _git_env(home)
    for args in (["init", "-q", "-b", "main", "."], ["add", "-A"],
                 ["commit", "-q", "-m", "c0: نقطه‌ی شروع"]):
        subprocess.run(["git"] + args, cwd=app_dir, env=genv, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    pr, url, log, _ = start(app_dir, home,
                            env_extra={"PIPFOUND_AUTORESTART": "0"})
    j0 = rev(url)
    check(not (j0.get("changed_files") or []),
          "کنترلِ منفی: بعد از بوت هیچ فایلِ ردیابی‌شده‌ای تازه نشد")
    check((j0.get("loaded") or {}).get("sha") == (j0.get("disk") or {}).get("sha"),
          "کنترلِ منفی: نقطه‌ی شروع یکدست است")

    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "c1: فقط SHA"],
                   cwd=app_dir, env=genv, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)

    j1 = rev(url)
    disk = (j1.get("disk") or {}).get("sha")
    loaded = (j1.get("loaded") or {}).get("sha")
    check(bool(disk and loaded and disk != loaded),
          "کنترلِ منفی: SHAِ دیسک از SHAِ بارشده جدا شد (کدِ کهنه سرو می‌شود)")
    check(j1.get("loaded") == j0.get("loaded"),
          "کنترلِ منفی: کدِ بارشده همان نسخه‌ی کهنه ماند (بی‌ری‌استارت)")
    check(j1.get("stale") is False,
          "کنترلِ منفی: دروغ واقعاً رخ داد — stale=false با کدِ کهنه‌ی سرو‌شده")
    check("یکی است" in (j1.get("note") or ""),
          "کنترلِ منفی: یادداشت هم دروغ می‌گوید «با دیسک یکی است»")
    check(disk != loaded and j1.get("sha_drift") is False,
          "کنترلِ منفی: پس بررسیِ sha_drift در D2 همان چیزی است که می‌گیرد")


# ── E) اصلاحِ خودِ نگهبان باید پذیرفته شود (نه زندانِ قوانینِ بوت‌شده) ───────────
STRICT_TAIL = '''

# ── (تستِ رگرسیون) قاعدهٔ سخت‌گیرِ اضافه: این نسخه فقط در **حافظه** می‌ماند ──
# اگر پروسه با همین ماژولِ بوت‌شده رکوردِ تازه را قضاوت کند، برداشتنِ این قاعده
# روی دیسک هیچ اثری ندارد و پروسه تا ابد «کدِ تازه خراب است» می‌گوید.
_pf_orig_run_checks = run_checks


def run_checks(root, *a, **k):
    rep = _pf_orig_run_checks(root, *a, **k)
    import os as _os
    if _os.path.exists(_os.path.join(root, ".pf_guard_locked")):
        rep["ok"] = False
        rep["problems"] = list(rep.get("problems") or []) + [
            "قاعدهٔ سخت‌گیرِ آزمایشی: پرچمِ .pf_guard_locked هنوز برداشته نشده"]
    return rep
'''


def case_selfcheck_self_fix():
    """اصلاحِ خودِ نگهبان هم باید مثلِ هر تغییرِ دیگری پذیرفته شود.

    باگِ واقعی (دیده‌شده روی سرورِ زنده): `_rev_validate` با همان ماژولِ
    `selfcheck`ی که موقعِ بوت import شده بود می‌سنجید. پس یک مثبتِ کاذبِ قدیمی
    (نسخهٔ کهنه) رکوردهای **تازه** را با قوانینِ **قدیم** قضاوت می‌کرد و پروسه
    هرگز نمی‌توانست اصلاحِ نگهبان را بپذیرد: چیپ می‌گفت «کدِ تازه خراب است»
    درحالی‌که همان درخت روی دیسک سالم بود → سرور روی نسخهٔ قدیم زندانی می‌شد.
    """
    app_dir, home = copy_tree()
    sc = os.path.join(app_dir, "selfcheck.py")
    with io.open(sc, encoding="utf-8") as f:
        real = f.read()
    # نسخهٔ A (سخت‌گیر) فقط روی دیسک می‌نشیند تا موقعِ بوت در حافظه بار شود.
    # هنوز پرچم نیست، پس خودِ بوت سبز است.
    with io.open(sc, "w", encoding="utf-8") as f:
        f.write(real + STRICT_TAIL)

    pr, url, log, _ = start(app_dir, home)
    j0 = rev(url)
    boot0, pid0 = j0["boot_ts"], j0["pid"]
    check(j0.get("stale") is False,
          "خودترمیمیِ نگهبان: شروع با نسخهٔ A سبز است (stale=false)")

    # اصلاحِ نگهبان روی دیسک: قاعدهٔ سخت‌گیر برداشته می‌شود، ولی شرطی که A رد
    # می‌کند فعال می‌شود (پرچم ساخته می‌شود).
    with io.open(sc, "w", encoding="utf-8") as f:
        f.write(real)
    with io.open(os.path.join(app_dir, ".pf_guard_locked"), "w", encoding="utf-8") as f:
        f.write("x")

    try:
        disk = json.loads(subprocess.run(
            [sys.executable, sc, "--root", app_dir, "--json"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode("utf-8"))
    except Exception as e:
        disk = {}
        notes.append("خودِ selfcheck.py روی دیسک اجرا نشد: %s" % e)
    check(disk.get("ok") is True,
          "قوانینِ روی دیسک (نسخهٔ B) این درخت را سالم می‌دانند — پس هر «رد»ی "
          "یعنی پروسه با قوانینِ کهنه قضاوت کرده")

    j1 = wait_restart(url, boot0, timeout=60)
    if not check(j1 is not None,
                 "اصلاحِ خودِ selfcheck.py پذیرفته شد و ری‌استارت انجام شد "
                 "(باگِ قبلی: نسخهٔ بوت‌شده تا ابد رد می‌کرد)"):
        st = rev_soft(url) or {}
        notes.append("وضعیتِ متوقف: %s" % json.dumps(
            (st.get("autorestart") or {}).get("blocked"), ensure_ascii=False))
        notes.append("لاگ:\n" + tail(log))
        return
    check(j1["pid"] == pid0, "PID در این ری‌استارت هم ثابت ماند (execv)")
    check(j1.get("stale") is False, "بعد از پذیرشِ اصلاحِ نگهبان، stale=false شد")
    check(not ((j1.get("autorestart") or {}).get("blocked")),
          "وضعیتِ «متوقف» پاک شد (%s)" % (j1.get("note"),))
    check("قوانینِ روی دیسک" in tail(log),
          "لاگ صریحاً می‌گوید با قوانینِ روی دیسک سنجیده شد: %s"
          % [l for l in tail(log).splitlines() if "selfcheck" in l][-1:])


def main():
    try:
        case_real_restart()
        case_broken_code_stays_alive()
        case_in_flight_request()
        case_sha_drift_restart()
        case_drift_flag_honesty()
        case_flag_lie_is_caught()
        case_selfcheck_self_fix()
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
          "ری‌استارتِ تمیز (بدونِ قطعِ درخواستِ در جریان)، ری‌استارتِ «فقط SHA"
          " عوض شده»، صداقتِ پرچم وقتی ری‌استارت خاموش است (نه سبزِ دروغ، نه قولِ"
          " دروغ)، و پذیرشِ اصلاحِ خودِ نگهبان (قوانینِ روی دیسک)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
