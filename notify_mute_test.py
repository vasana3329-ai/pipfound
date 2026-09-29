#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تستِ «خفه‌بودنِ نوتیفیکیشن در تست‌ها» — تست‌ها هرگز روی دسکتاپِ کاربر نوتیف نمی‌زنند.

**شکایتِ واقعیِ کاربر:** «یه ایرادی توو آپ ایجاد شده که پشتِ‌سرِهم یه نوتیف می‌ده
توو دسکتاپ». **ریشه‌یابی (سنجیده‌شده):** خودِ اپِ زنده سالم بود — فایلِ
`~/pipfound/fund_alarms_fired.json` نشان می‌داد اپ فقط **یک‌بار** (درست، طبقِ
طراحی) خبرِ فردا را اطلاع داده. ولی کارگرِ آلارمِ فاندمنتال (`_fund_alarm_worker`)
**سرِ بوت و در همان اولین دور** خبرِ ۲۳–۲۵ ساعتِ آینده را می‌بیند و نوتیفِ
*واقعیِ مک* می‌فرستد؛ و هر تستی که اپ را با **HOMEِ تازه** بالا می‌آورد یعنی
«فایلِ dedupe وجود ندارد» ⇒ نوتیف می‌رود، و هر `execv`ِ ری‌استارت هم دوباره.
شمارشِ `osascript` دقيقاً همان دقایقی را نشان داد که سوییت‌های تست اجرا می‌شدند.
یعنی **تُست‌ها روی دسکتاپِ کاربر نوتیف می‌فرستادند**.

این تست سه چیز را قفل می‌کند:

  ۱) **قاعدهٔ نگهبان (لایهٔ ۱):** `selfcheck.notify_problems` روی مخزنِ سالم
     صفر خطا می‌دهد، دروازهٔ `PIPFOUND_NOTIFY` را در `_notify_mac` (پیش از
     `osascript`) می‌بیند، و هر پرتابِ اپ در تست‌ها/هارنس‌ها/گام‌های CI را
     با `PIPFOUND_NOTIFY=0` خفه‌شده می‌شمارد.
  ۲) **جهش‌آزماییِ خودِ قاعده:** برداشتنِ دروازه، جابه‌جاییِ دروازه به بعد از
     `osascript`، نجوشیدنِ کلید از محیط، خالی‌کردنِ فهرستِ مقادیرِ خاموش،
     برداشتنِ کلید از **هر یک از ۸ نقطهٔ پرتابِ** اپ (۷ فایلِ تست/هارنس — شاملِ
     خودِ همین تست — + گامِ CI)، و «کلید هست ولی روی روشن»
     باید قاعده را **قرمز** کنند (و علت را نام ببرند)؛ جهش‌های بی‌گناه سبز بمانند.
  ۳) **اثباتِ رفتاریِ سرتاسری (بدونِ نوتیفِ واقعی):** یک `osascript`ِ جعلی روی
     PATH می‌نشیند و یک تقویمِ ثابتِ آفلاین (خبرِ High دقیقاً ۲۴ ساعتِ آینده)
     به اپِ سندباکسی داده می‌شود؛ آن‌گاه: (الف) **شاهدِ مثبت** — بدونِ کلید،
     هارنسِ جعلی *باید* صدا زده شود (یعنی مکانیزم واقعاً همین بود که نوتیف
     می‌فرستاد)؛ (ب) با `PIPFOUND_NOTIFY=0` هارنسِ جعلی **صفر بار** صدا زده
     می‌شود، در حالی که فایلِ dedupe نوشته می‌شود (کارگر اجرا شد و فقط خفه شد —
     نه اینکه مرده باشد)؛ (ج) **کنترلِ منفی** — همان کپی با دروازهٔ برداشته‌شده
     دوباره نوتیف می‌زند، پس ادعای (ب) فقط به‌خاطرِ سپرِ تست نبوده است.

کاملاً آفلاین (تقویمِ ثابت + شبکه بسته)، بدونِ دست‌زدن به دادهٔ واقعیِ کاربر، و
هر پرتاب روی HOME و پورتِ موقتِ خودش.

اجرا:  python3 notify_mute_test.py                  (خروجی ۰ = سالم)
       PF_NOTIFY_NO_MUT=1 python3 notify_mute_test.py  (بدونِ جهش‌آزمایی و کنترلِ منفی)
"""
import datetime
import io
import json
import os
import shutil
import socket as _socket
import subprocess
import sys
import tempfile
import time
import urllib.request as _urllib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ── نگهبانِ هرمتیک: خودِ این تست نباید به شبکه دست بزند ──────────────────
# (نمونه‌های اپِ سندباکسی هم به شبکه نمی‌روند: تقویمِ ثابتِ `.ff_cache.json`
# تازه نگه داشته می‌شود و هیچ آلارمِ قیمتی در HOMEِ خالی وجود ندارد.)
NET_ATTEMPTS = []


def _no_network(*a, **kw):
    NET_ATTEMPTS.append(str(a[0])[:80] if a else "")
    raise OSError("offline-guard: دسترسیِ شبکه در این تست بسته است")


_socket.getaddrinfo = _no_network
_socket.create_connection = _no_network
_urllib.urlopen = _no_network

import selfcheck as SC       # noqa: E402

SOURCE = io.open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
MUTE = "PIPFOUND_NOTIFY"
# خودِ این تست هم اپ را پرتاب می‌کند (سه نمونه: الف/ب/ج)، پس قاعدهٔ نگهبان آن را
# هم می‌شمارد و اعلامِ **صریحِ** خاموش در کدِ همین فایل لازم است (نه فقط ارجاعِ
# متغیر و نه کامنت) — وگرنه دوباره همان تلهٔ «سبزِ تصادفی» برمی‌گردد.
MUTED = {"PIPFOUND_NOTIFY": "0"}
# قاعده در *کلِ کدِ* فایل دنبالِ «کلیدِ خفه» می‌گردد؛ پس لنگرِ جهش و هر رشتهٔ
# کمکی باید از MUTE ساخته شوند تا تنها هم‌خوانیِ کلِ فایل، اعلانِ MUTED در
# سطرِ بالا بمانَد — وگرنه برداشتنِ MUTED هرگز قرمز نمی‌شود (سبزِ تصادفیِ
# خودارجاع؛ همین تله در اجرای نخستِ جهشِ MUTED → {} لو رفت).
MUTED_NEEDLE = "MUTED = {" + '"' + MUTE + '": "0"}'
MUTED_OFF = "MUTED = {" + '"' + MUTE + '": "off"}'
CI_LAUNCH = MUTE + "=0 python3 app.py"
COMMENT_ONLY = "    # " + MUTE + "=0 — فقط یادداشت، بدونِ کد\n"
# دو تکّهٔ لنگرِ یکتا در app.py (شمارشِ needle صریح چک می‌شود تا جهشِ بی‌اثر
# به‌جای «سبزِ خاموش»، خطا بدهد).
GATE = '    if _notify_muted():\n        return\n'
OSA_TAIL = ('             f\'display notification "{m}" with title "{t}" '
            'sound name "Glass"\'],\n            capture_output=True, timeout=5)')
ENV_LINE = '    env["%s"] = "0"\n' % MUTE
OFF_SET = '_NOTIFY_OFF_VALUES = {"0", "off", "false", "no", "خاموش"}'

EXPECTED = ("autobackup_test.py", "autorestart_test.py", "backup_test.py",
            "journal_roundtrip_test.py", "pwa_test.py", "sw_upgrade_check.cjs")
CI_FILE = ".github/workflows/selfcheck.yml"

NO_MUT = os.environ.get("PF_NOTIFY_NO_MUT") == "1"
CHECKS, FAILS, NOTES = [], [], []


def check(name, cond, detail=""):
    CHECKS.append(name)
    if not cond:
        FAILS.append((name, detail))
    return bool(cond)


def free_port():
    s = _socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_for(fn, timeout=30.0, step=0.2):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            v = fn()
        except Exception:                            # noqa: BLE001
            v = None
        if v:
            return v
        time.sleep(step)
    return None


def read(path):
    try:
        with io.open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def notify_lines(path):
    """هر خطی که هارنسِ جعلیِ `osascript` ثبت کرده = یک نوتیفیکیشنِ واقعی."""
    return [ln for ln in read(path).splitlines() if ln.strip()]


# ═══════════════════════ ابزارِ سندباکسِ مخزن ═══════════════════════
def copy_repo(prefix="pf_notify_"):
    """کپیِ کاملِ مخزن (بدونِ گیت/کش) — جهش‌ها روی همین کپی می‌نشینند."""
    d = tempfile.mkdtemp(prefix=prefix)
    dst = os.path.join(d, "app")
    shutil.copytree(HERE, dst, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", ".ff_cache.json", "*.log", ".DS_Store"))
    return dst


def drop(src_dir):
    shutil.rmtree(os.path.dirname(src_dir), ignore_errors=True)


def edit(src_dir, name, old, new):
    """جایگزینیِ لنگرشده؛ اگر لنگر یکتا نباشد **خطا** می‌دهد (نه سبزِ خاموش)."""
    p = os.path.join(src_dir, *name.split("/"))
    txt = io.open(p, encoding="utf-8").read()
    n = txt.count(old)
    if n != 1:
        raise AssertionError("لنگرِ جهش در %s %d بار پیدا شد (باید ۱ باشد): %r"
                             % (name, n, old[:60]))
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(txt.replace(old, new, 1))


def scan(src_dir):
    return SC.notify_problems(src_dir)


def run_guard(mutate=None):
    d = copy_repo()
    try:
        if mutate:
            mutate(d)
        return scan(d)
    finally:
        drop(d)


# ═══════════════════════ ۱) قاعده روی مخزنِ سالم ═══════════════════════
print("═══ ۱) قاعدهٔ نگهبان روی مخزنِ سالم ═══")
p0, s0 = scan(HERE)
check("قاعده: مخزنِ سالم صفر خطا", p0 == [], str(p0)[:240])
check("قاعده: دروازهٔ PIPFOUND_NOTIFY در app.py سبز است", s0.get("gate") is True, str(s0))
present = {n for n in EXPECTED if os.path.exists(os.path.join(HERE, n))}
check("قاعده: همهٔ فایل‌های پرتاب‌کنندهٔ موجود شناخته شدند",
      present and present <= set(s0.get("files") or []),
      "انتظار: %s — دید: %s" % (sorted(present), s0.get("files")))
check("قاعده: هر پرتابِ تست/هارنس خفه است (%d/%d)"
      % (s0.get("muted", 0), s0.get("sites", 0)),
      s0.get("sites") == s0.get("muted") and s0.get("sites", 0) >= len(present),
      str(s0))
# خودِ این تست هم پرتاب‌کننده است و اعلامِ صریحِ خاموش دارد — قاعده باید آن را
# هم ببیند (وگرنه دلیلِ سبزبودنش تصادفی می‌شد، مثلِ آن‌که فقط در رشتهٔ جهش
# کلید دیده شود).
check("قاعده: خودِ این تست را هم به‌عنوانِ پرتاب‌کنندهٔ خفه می‌شمارد",
      "notify_mute_test.py" in (s0.get("files") or []), str(s0.get("files")))
check("قاعده: گامِ CIِ app.py هم خفه است",
      s0.get("ci_sites", 0) >= 1 and s0.get("ci_sites") == s0.get("ci_muted")
      and CI_FILE in (s0.get("files") or []), str(s0))

# اپِ زنده باید **روشن** بماند: لانچرِ واقعیِ کاربر (`make_app.py`) نباید خفه کند.
launcher = io.open(os.path.join(HERE, "make_app.py"), encoding="utf-8").read()
check("لانچرِ واقعی هنوز خفه نمی‌کند (اپِ زنده روشن می‌مانَد)",
      "app.py --port" in launcher and MUTE not in launcher,
      "کلیدِ خفه در make_app.py دیده شد" if MUTE in launcher else "لنگرِ پرتاب نبود")

# ═══════════════════════ ۲) جهش‌آزماییِ قاعده ═══════════════════════
if NO_MUT:
    NOTES.append("• PF_NOTIFY_NO_MUT=1 — بخشِ ۲ (جهش‌آزمایی) و کنترلِ منفیِ ۴ج رد شد.")
else:
    print("═══ ۲) جهش‌آزماییِ قاعده (قرمز/بی‌گناه) ═══")


def red(name, needle, mutate):
    try:
        probs, _ = run_guard(mutate)
    except Exception as ex:                          # noqa: BLE001
        check("جهشِ سرخ | " + name, False, "جهش با استثنا متوقف شد: %r" % (ex,))
        return
    check("جهشِ سرخ | " + name, any(needle in x for x in probs), str(probs)[:240])


def green(name, mutate):
    try:
        probs, _ = run_guard(mutate)
    except Exception as ex:                          # noqa: BLE001
        check("جهشِ بی‌گناه | " + name, False, "جهش با استثنا متوقف شد: %r" % (ex,))
        return
    check("جهشِ بی‌گناه | " + name, probs == [], str(probs)[:240])


if not NO_MUT:
    # ── لنگرها اول شمرده می‌شوند تا جهشِ بی‌اثر به‌جای سبز، خطا بدهد ──
    check("لنگرِ دروازه در app.py یکتاست", SOURCE.count(GATE) == 1, str(SOURCE.count(GATE)))
    check("لنگرِ پرتابِ osascript یکتاست", SOURCE.count(OSA_TAIL) == 1,
          str(SOURCE.count(OSA_TAIL)))
    check("لنگرِ فهرستِ مقادیرِ خاموش یکتاست", SOURCE.count(OFF_SET) == 1,
          str(SOURCE.count(OFF_SET)))

    red("برداشتنِ دروازه از _notify_mac؛ دروازه باش ولی اثری نداشته باشد",
        "دروازهٔ _notify_muted() را صدا نمی‌زند",
        lambda d: edit(d, "app.py", GATE, ""))
    red("نخواندنِ کلید از محیط (return False)",
        "را نمی‌خواند",
        lambda d: edit(d, "app.py",
                       '        return (os.environ.get("%s") or "").strip().lower() '
                       'in _NOTIFY_OFF_VALUES' % MUTE,
                       "        return False"))
    red("خالی‌کردنِ فهرستِ مقادیرِ خاموش",
        "«۰» را ندارد",
        lambda d: edit(d, "app.py", OFF_SET, "_NOTIFY_OFF_VALUES = set()"))
    red("دروازه **بعد** از پرتابِ نوتیف سنجیده شود",
        "نوتیف همان‌جا رفته",
        lambda d: (edit(d, "app.py", GATE, ""),
                   edit(d, "app.py", OSA_TAIL,
                        OSA_TAIL + "\n        _notify_muted()\n        return")))
    red("تستِ خودِ app.py بی‌کلید (autorestart)",
        "autorestart_test.py", lambda d: edit(d, "autorestart_test.py", ENV_LINE, ""))
    red("تستِ خودِ app.py بی‌کلید (autobackup)",
        "autobackup_test.py", lambda d: edit(d, "autobackup_test.py", ENV_LINE, ""))
    red("تستِ خودِ app.py بی‌کلید (backup)",
        "backup_test.py", lambda d: edit(d, "backup_test.py", ENV_LINE, ""))
    red("تستِ خودِ app.py بی‌کلید (journal_roundtrip)",
        "journal_roundtrip_test.py",
        lambda d: edit(d, "journal_roundtrip_test.py", ENV_LINE, ""))
    red("تستِ خودِ app.py بی‌کلید (pwa)",
        "pwa_test.py",
        lambda d: edit(d, "pwa_test.py", ',\n           %s="0")' % MUTE, ")"))
    red("هارنسِ نود بی‌کلید (sw_upgrade_check)",
        "sw_upgrade_check.cjs",
        lambda d: edit(d, "sw_upgrade_check.cjs", ', %s: "0"' % MUTE, ""))
    red("گامِ CI بی‌کلید", CI_FILE,
        lambda d: edit(d, CI_FILE, CI_LAUNCH, "python3 app.py"))
    red("کلید هست ولی روی حالتِ روشن (\"1\")",
        "روی حالتِ خاموش",
        lambda d: edit(d, "pwa_test.py", '%s="0"' % MUTE,
                       '%s="1"' % MUTE))
    # کامنتِ حاویِ کلید نباید کافی باشد: کلید برداشته می‌شود و فقط کامنت می‌ماند.
    red("کلید برداشته شد و فقط کامنتِ درستش ماند (کامنت کافی نیست)",
        "backup_test.py",
        lambda d: edit(d, "backup_test.py", ENV_LINE, COMMENT_ONLY))
    # خودِ این تست هم پرتاب‌کننده است: علامتِ صریحِ خاموش در کدِ همین فایل باید
    # بمانَد، وگرنه قاعده (درست) قرمز می‌شود — پس این هم یک قفلِ واقعی است.
    red("برداشتنِ علامتِ صریحِ خاموش از خودِ این تست (MUTED → {})",
        "notify_mute_test.py",
        lambda d: edit(d, "notify_mute_test.py", MUTED_NEEDLE, "MUTED = {}"))

    green("کامنتِ بی‌گناه در app.py",
          lambda d: edit(d, "app.py", GATE, "    # یادداشتِ بی‌گناه\n" + GATE))
    green("افزودنِ مقدارِ خاموشِ تازه به فهرست",
          lambda d: edit(d, "app.py", OFF_SET,
                         '_NOTIFY_OFF_VALUES = {"0", "off", "false", "no", "خاموش", "nah"}'))
    green("سبکِ متفاوتِ ست‌کردنِ کلید در تست (env.update)",
          lambda d: edit(d, "journal_roundtrip_test.py", ENV_LINE,
                         '    env.update({"%s": "0"})\n' % MUTE))
    green("افزودنِ envِ بی‌ربط به یک تست",
          lambda d: edit(d, "backup_test.py", ENV_LINE, ENV_LINE + '    env["PF_X"] = "1"\n'))
    green("کامنتِ بی‌گناه در گامِ CI",
          lambda d: edit(d, CI_FILE, CI_LAUNCH, CI_LAUNCH + "  # یادداشتِ بی‌گناه"))
    green("سبکِ دیگرِ مقدارِ خاموش در خودِ این تست (off)",
          lambda d: edit(d, "notify_mute_test.py", MUTED_NEEDLE, MUTED_OFF))


# ═══════════════════════ ۳) اثباتِ رفتاریِ سرتاسری ═══════════════════════
# هارنسِ جعلیِ `osascript` روی PATH می‌نشیند: هر فراخوانی = یک نوتیفِ واقعی روی
# دسکتاپ. تقویمِ ثابتِ آفلاین یک خبرِ High دقیقاً ۲۴ ساعتِ آینده دارد، پس کارگرِ
# فاندمنتال در همان اولین دور باید نوتیف بزند (همان چیزی که روی دسکتاپِ کاربر
# رخ می‌داد). اینجا فقط یک شیمِ محلی صدا زده می‌شود — هیچ نوتیفِ واقعی نمی‌رود.
print("═══ ۳) اثباتِ رفتاریِ سرتاسری (osascriptِ جعلی + تقویمِ ثابت) ═══")
SHIM = ("#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$PF_NOTIFY_LOG\"\n")


def make_fakebin():
    d = tempfile.mkdtemp(prefix="pf_notify_bin_")
    p = os.path.join(d, "osascript")
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(SHIM)
    os.chmod(p, 0o755)
    return d


def write_calendar(app_dir):
    """تقویمِ ثابتِ آفلاین: خبرِ High USD دقیقاً ۲۴ ساعتِ آینده."""
    ev = {"title": "Core PCE Price Index m/m", "country": "USD", "impact": "High",
          "date": (datetime.datetime.now(datetime.timezone.utc)
                   + datetime.timedelta(hours=24)).isoformat(),
          "forecast": "0.2%", "previous": "0.3%"}
    with io.open(os.path.join(app_dir, ".ff_cache.json"), "w", encoding="utf-8") as f:
        json.dump([ev], f, ensure_ascii=False)
    return ev


def start(app_dir, fakebin, notify_log, extra_env):
    home = tempfile.mkdtemp(prefix="pf_notify_home_")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PIPFOUND_")}
    env["HOME"] = home
    env["PATH"] = fakebin + os.pathsep + env.get("PATH", "")
    env["PF_NOTIFY_LOG"] = notify_log
    env["PIPFOUND_HOST"] = "127.0.0.1"
    port = free_port()
    env["PIPFOUND_PORT"] = str(port)
    env.update(extra_env or {})
    log = os.path.join(home, "server.log")
    fh = io.open(log, "w")
    pr = subprocess.Popen([sys.executable, "-u", os.path.join(app_dir, "app.py"),
                           "--port", str(port), "--no-autorestart"],
                          cwd=app_dir, env=env, stdout=fh, stderr=subprocess.STDOUT)
    return pr, fh, home, log


def stop(pr, fh, home):
    try:
        pr.terminate()
        pr.wait(timeout=10)
    except Exception:                                # noqa: BLE001
        try:
            pr.kill()
        except Exception:                            # noqa: BLE001
            pass
    try:
        fh.close()
    except Exception:                                # noqa: BLE001
        pass
    shutil.rmtree(home, ignore_errors=True)


def run_case(label, extra_env, mutate=None):
    """یک نمونهٔ اپِ سندباکسی با تقویمِ ثابت → (نوتیف‌ها، لاگِ بوت، خطاهای قاعده).

    روی کپیِ کاملِ مخزن کار می‌کند (نه روی مخزنِ واقعی): نه `.ff_cache.json`ِ
    زنده لمس می‌شود و نه چیزی نوشته می‌شود. توجه: اپ خودش **پیش از سرو کردن**
    `selfcheck.run_checks` را اجرا می‌کند و اگر خراب باشد بالا نمی‌آید — پس
    جهش‌های این بخش باید طوری باشند که اپ واقعاً بتواند بالا بیاید (وگرنه چیزی
    دربارهٔ رفتارِ نوتیف ثابت نمی‌شود).
    """
    app_dir = copy_repo()
    fakebin = make_fakebin()
    ntf = os.path.join(fakebin, "notify.log")
    try:
        probs = None
        if mutate:
            mutate(app_dir)
            probs, _ = scan(app_dir)
        ev = write_calendar(app_dir)
        key = datetime.datetime.fromisoformat(ev["date"]).isoformat() + "|" + ev["title"]
        pr, fh, home, log = start(app_dir, fakebin, ntf, extra_env)
        try:
            fired = os.path.join(home, "pipfound", "fund_alarms_fired.json")
            wait_for(lambda: notify_lines(ntf) or os.path.exists(fired) or None,
                     timeout=40)
            time.sleep(1.0)          # مهلتِ سخاوتمندانه برای هر نوتیفِ دیرهنگام
            boot = read(log)
            check("%s: اپ بالا آمد" % label, "pipfound روی" in boot, boot[-400:])
            check("%s: کارگرِ آلارم واقعاً اجرا شد (فایلِ dedupe با همان خبر)" % label,
                  os.path.exists(fired) and key in read(fired), read(fired)[:200])
            return notify_lines(ntf), boot, probs
        finally:
            stop(pr, fh, home)
    finally:
        shutil.rmtree(app_dir, ignore_errors=True)
        shutil.rmtree(fakebin, ignore_errors=True)


# (الف) شاهدِ مثبت: پیش‌فرضِ اپ **روشن** است ⇒ همان نوتیفِ واقعی پرتاب می‌شود.
got_a, boot_a, _ = run_case("الف (پیش‌فرضِ اپ: روشن)", {})
check("الف: نوتیفِ واقعی پرتاب شد (شاهدِ مثبت — ریشهٔ همان شکایت)", bool(got_a),
      "لاگِ هارنسِ جعلی خالی ماند ⇒ مسیرِ نوتیف اصلاً طی نشد")
check("الف: همان خبرِ فردا اطلاع داده شد",
      bool(got_a) and "فردا" in got_a[0] and "PCE" in got_a[0], str(got_a)[:200])

# (ب) با کلیدِ خفه: کارگر اجرا می‌شود ولی هیچ نوتیفی نمی‌رود.
got_b, boot_b, _ = run_case("ب (%s=0)" % MUTE, MUTED)
check("ب: اپ حالتِ خفه را اعلام کرد", "🔕" in boot_b, boot_b[-400:])
check("ب: صفر نوتیفِ واقعی (هارنسِ جعلی یک بار هم صدا زده نشد)", got_b == [],
      str(got_b)[:200])

if not NO_MUT:
    # (ج) کنترلِ منفیِ دوسطحی: کپی‌ای که **قاعدهٔ استاتیک روی آن سبز است** ولی
    # دروازه‌اش بی‌اثر شده (`in set()`)، با PIPFOUND_NOTIFY=0 باز هم نوتیف می‌زند
    # ⇒ لایهٔ رفتاری چیزی را می‌سنجد که لایهٔ استاتیک نمی‌بیند (و ادعای «ب»
    # فقط به‌خاطرِ سپرِ تست نبوده است).
    GATE_BODY = ('        return (os.environ.get("%s") or "").strip().lower() '
                 "in _NOTIFY_OFF_VALUES" % MUTE)
    got_c, _, probs_c = run_case(
        "ج (دروازهٔ بی‌اثرشده + کلیدِ خفه)", MUTED,
        mutate=lambda d: edit(d, "app.py", GATE_BODY, GATE_BODY.replace("in _NOTIFY_OFF_VALUES",
                                                                       "in set()")))
    check("ج: کنترلِ منفی — قاعدهٔ استاتیک روی این کپی سبز است", probs_c == [],
          str(probs_c)[:200])
    check("ج: ...ولی نوتیفِ واقعی رفت ⇒ لایهٔ رفتاری مستقل از قاعده دندان دارد",
          bool(got_c), "حتی با دروازهٔ بی‌اثر هم نوتیفی نرفت ⇒ ادعای (ب) چیزی را ثابت نمی‌کند")

check("هیچ تلاشِ شبکه‌ای در خودِ تست رخ نداد", NET_ATTEMPTS == [], str(NET_ATTEMPTS)[:200])


# ── گزارش ──
for n in NOTES:
    print(n)
print("• بررسی‌ها: %d" % len(CHECKS))
if FAILS:
    print("")
    for name, detail in FAILS:
        print("::error::❌ %s" % name + (" — %s" % detail if detail else ""))
    print("\n❌ تستِ خفه‌بودنِ نوتیفیکیشن رد شد — %d از %d بررسی شکست خورد"
          % (len(FAILS), len(CHECKS)))
    sys.exit(1)
print("✅ تستِ خفه‌بودنِ نوتیفیکیشن پاس شد — دروازهٔ اپ، خفه‌بودنِ هر ۸ نقطهٔ "
      "پرتاب، جهش‌آزماییِ قاعده، و اثباتِ رفتاریِ «تست‌ها روی دسکتاپِ کاربر "
      "نوتیف نمی‌زنند»")
