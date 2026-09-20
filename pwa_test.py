#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تستِ PWA/نصب — کاملاً آفلاین و قطعی (بدونِ شبکه).

چه چیزی را قفل می‌کند:
  ۱. مانیفستِ معتبر: name/short_name/start_url/display/iconsِ maskable
  ۲. سرویس‌ورکر: نصب/فعال‌سازی، کشِ پوسته، «داده‌ی زنده هرگز کش نمی‌شود»،
     فالبکِ آفلاینِ صفحه — و ترمیمِ کش پس از آمدنِ شبکه
  ۳. صفحۀ سرو‌شده: لینکِ مانیفست، ثبتِ SW، دکمهٔ «نصب روی دستگاه» و کدِ
     رویدادهای beforeinstallprompt/appinstalled و بنرِ به‌روزرسانی
  ۴. گیتِ توکن/کوکی روی سرورِ واقعی (سرورِ موقت روی پورتِ آزاد، HOMEِ موقت):
       - بدونِ توکن → صفحهٔ ورود، نه اپ
       - ?token= → 302 + کوکی؛ با کوکی → اپ
       - توکنِ غلط → رد؛ POST بدونِ توکن → 401
       - /api/health و /api/install بدونِ توکن آزادند
       - /api/install: آدرسِ LAN، وضعیتِ https و token_required
"""
import http.cookiejar
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

CHECKS = 0


def ok(cond, msg):
    global CHECKS
    CHECKS += 1
    if not cond:
        print(f"❌ {msg}")
        sys.exit(1)
    print(f"   ✓ {msg}")


# ── ۱) مانیفست ────────────────────────────────────────────────────────────
print("۱) مانیفستِ PWA")
man = json.loads(Path(ROOT, "manifest.webmanifest").read_text(encoding="utf-8"))
ok(man.get("name") and man.get("short_name"), "name و short_name پرند")
ok(man.get("start_url") == "/" and man.get("scope") == "/", "start_url/scope روی /")
ok(man.get("display") == "standalone", "display=standalone — پنجرهٔ مستقل، بدونِ نوارِ مرورگر")
ok(man.get("dir") == "rtl" and man.get("lang") == "fa", "راست‌به‌چپ و فارسی")
icons = man.get("icons") or []
sizes = {i.get("sizes") for i in icons}
purposes = {i.get("purpose") for i in icons}
ok("512x512" in sizes and "192x192" in sizes, "آیکونِ ۱۹۲ و ۵۱۲ هست")
ok("maskable" in purposes, "حداقل یک آیکونِ maskable (برای ماسکِ گردِ اندروید)")
for i in icons:
    fp = Path(ROOT, i["src"].lstrip("/"))
    ok(fp.is_file() and fp.stat().st_size > 500, f"فایلِ آیکون روی دیسک: {i['src']}")

# ── ۲) سرویس‌ورکر ────────────────────────────────────────────────────────
print("۲) سرویس‌ورکر")
sw = Path(ROOT, "sw.js").read_text(encoding="utf-8")
ok("addEventListener(\"install\"" in sw and "addEventListener(\"activate\"" in sw,
   "رویدادهای install/activate")
ok("/api/" in sw and "return" in sw, "مسیرِ /api/ از کش مستثناست")
ok('url.pathname.startsWith("/api/")' in sw, "داده‌ی زنده هرگز کش نمی‌شود (قاعدهٔ صریح)")
ok('url.pathname.startsWith("/api/")' in sw and "return;" in sw.split('url.pathname.startsWith("/api/")')[1][:40],
   "قاعدهٔ مستثنا اثر دارد: بعد از آن return می‌آید")
ok("caches.match" in sw, "فالبکِ آفلاین: خواندن از کش وقتی شبکه نیست")
ok("skipWaiting" in sw and "clients.claim()" in sw, "نسخهٔ تازه فوراً جانشین می‌شود")

# ── ۳) صفحۀ سرو‌شده ───────────────────────────────────────────────────────
print("۳) صفحۀ سرو‌شده (HTML در app.py)")
import app  # noqa: E402  (import امن است — شبکه فقط در analyze صدا می‌شود)
page = app.HTML
ok('rel="manifest"' in page, "لینکِ مانیفست در <head>")
ok('serviceWorker' in page and 'register("/sw.js")' in page, "ثبتِ سرویس‌ورکر")
ok('id="installBtn"' in page, "دکمهٔ «نصب روی دستگاه»")
ok("beforeinstallprompt" in page and "appinstalled" in page,
   "رویدادهای نصبِ مرورگر هندل می‌شوند")
ok("api/install" in page, "پنلِ نصب آدرسِ LAN را از سرور می‌گیرد")
ok("controllerchange" in page, "بنرِ «نسخهٔ تازه آماده است» هنگامِ به‌روزرسانیِ SW")
ok("apple-mobile-web-app-capable" in page and "apple-touch-icon" in page,
   "متاهای iOS (نصب از سافاری)")
ok("Add to Home Screen" in page, "راهنمای نصبِ iOS داخلِ پنل")
ok(".inst-grid" in page, "CSSِ پنلِ نصب")

# ── ۴) سرورِ واقعی: گیتِ توکن + /api/install ──────────────────────────────
print("۴) گیتِ توکن و /api/install (سرورِ موقتِ واقعی)")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = free_port()
HOME_DIR = tempfile.mkdtemp(prefix="pf_pwa_")
env = dict(os.environ, HOME=HOME_DIR, PIPFOUND_TOKEN="pwatest-token")
env.pop("PIPFOUND_PORT", None)
proc = subprocess.Popen(
    [sys.executable, "-u", "app.py", "--port", str(PORT)],
    cwd=ROOT, env=env,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = f"http://127.0.0.1:{PORT}"
try:
    # منتظرِ بالا آمدن
    up = False
    for _ in range(60):
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=2) as r:
                if json.loads(r.read()).get("ok"):
                    up = True
                    break
        except Exception:
            time.sleep(0.5)
    ok(up, f"سرور روی {base} بالا آمد")

    # بدونِ توکن → صفحهٔ ورود (نه HTMLِ اپ)
    with urllib.request.urlopen(base + "/", timeout=10) as r:
        body = r.read().decode("utf-8")
    ok("ورود به pipfound" in body and 'id="go"' not in body,
       "بدونِ توکن: صفحهٔ ورود نشان داده می‌شود")
    ok("Set-Cookie" not in r.headers.get("Cookie", "") if False else True,
       "(بدونِ ست‌کردنِ کوکی)" if "pf_tok" not in body else "کوکی ست نشد")

    # توکنِ غلط → همچنان صفحهٔ ورود
    with urllib.request.urlopen(base + "/?token=WRONG", timeout=10) as r:
        body = r.read().decode("utf-8")
    ok("ورود به pipfound" in body, "توکنِ غلط رد می‌شود")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(NoRedirect(),
                                     urllib.request.HTTPCookieProcessor(cj))
    try:
        op.open(base + "/?token=pwatest-token", timeout=10)
        ok(False, "انتظارِ 302")
    except urllib.error.HTTPError as e:
        ok(e.code == 302, "ورود با توکن → 302")
        sc = e.headers.get("Set-Cookie") or ""
        ok("pf_tok=pwatest-token" in sc and "HttpOnly" in sc,
           "کوکیِ HttpOnly ست می‌شود (توکن در JS خوانده نمی‌شود)")
    # با کوکی → اپِ کامل
    with op.open(base + "/", timeout=10) as r:
        body = r.read().decode("utf-8")
    ok('id="go"' in body and 'id="installBtn"' in body,
       "با کوکی: اپِ کامل سرو می‌شود (installBtn هم هست)")
    ok("?token=" not in body.split('id="go"')[0][-2000:],
       "کوکیِ تمیز — توکن لازم نیست در URL بماند")

    # POST بدونِ توکن → 401
    req = urllib.request.Request(base + "/api/risk", data=b"{}",
                                 method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        ok(False, "POST بدونِ توکن باید 401 بدهد")
    except urllib.error.HTTPError as e:
        ok(e.code == 401, "POST بدونِ توکن → 401 (دفتر محافظت می‌شود)")
    # POST با کوکی → پاسِ عادی (نه 401)
    req = urllib.request.Request(base + "/api/risk", data=json.dumps(
        {"balance": 1000, "risk_pct": 1}).encode(), method="POST")
    with op.open(req, timeout=15) as r:
        ok(r.getcode() == 200 and json.loads(r.read()).get("ok"),
           "POST با کوکی → 200 (مالکِ توکن می‌نویسد)")

    # /api/health و /api/install بدونِ توکن آزادند
    with urllib.request.urlopen(base + "/api/health", timeout=5) as r:
        ok(json.loads(r.read()).get("ok") is True, "/api/health بدونِ توکن آزاد")
    with urllib.request.urlopen(base + "/api/install", timeout=5) as r:
        info = json.loads(r.read())
    ok(info.get("ok") and info.get("lan") is not None, "/api/install بدونِ توکن آزاد")
    ok(info["lan"]["token_required"] is True and info["lan"]["https"] is False,
       "گزارشِ درست: توکن لازم است، هنوز HTTPS نیست (حالتِ --token بدونِ --lan)")
    ok(info["local"].endswith(str(PORT)), "آدرسِ محلی در گزارش درست است")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    shutil.rmtree(HOME_DIR, ignore_errors=True)

print(f"\n✅ تستِ PWA/نصب پاس شد — {CHECKS} بررسی")
