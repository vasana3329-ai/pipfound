#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""آزمونِ لایه‌ی ۴.۱۷ — «کلیدِ بی‌واکنش نداریم» (شکایتِ واقعیِ کاربر).

شکایت: «چک کن خیلی از کلیدا رو از کار انداختی که؟! مثلا فاندمنتال و به‌روزرسانی رو.»
راستی‌آزماییِ زندهٔ اپِ در حالِ اجرا این را نشان داد (نه حدس): کلیدها *سالم* بودند،
اما دو **بی‌صداییِ واقعی** وجود داشت که هر کدام یک کلید را «خراب» جلوه می‌داد:
  ۱) کلیدِ «فاندمنتال» تنها جایی بود که `window.open` می‌زد. در نصبِ PWA
     (`display-mode: standalone`) و با پاپ‌آپ‌بلاکر، `window.open` مقدارِ NULL
     برمی‌گرداند و کد قبلی آن را نمی‌سنجید: نه تبی، نه پیامی، نه حرکتی ⇒ «کلیدِ مرده».
  ۲) پیامِ «چیزی برای بروزرسانی نیست» داخلِ `.rf-live` می‌رفت که عمداً sr-only
     است (`width:1px` برای صفحه‌خوان) ⇒ کاربرِ بینا **هیچ** واکنشی نمی‌دید.

سه بخش:
  ۱) قاعدهٔ نگهبانِ `selfcheck.button_alive_problems` روی مخزنِ سالم صفر خطا می‌دهد.
  ۲) جهش‌آزمایی: برداشتنِ تورِ ایمنیِ هم‌تب / سنجشِ NULL / واکنشِ دیدنیِ کلیدِ
     بروزرسانی باید نام‌دار قرمز شود؛ پاک‌سازی‌های بی‌گناه سبز بمانند.
  ۳) رفتارِ خالص (با node): هندلرِ واقعیِ کلیدِ فاندمنتال استخراج و با سه حالت اجرا
     می‌شود — پاپ‌آپِ مسدود (NULL)، پاپ‌آپِ مجاز، و `window.open` که پرت می‌کند.
     ضمناً «شاهدِ باگ» هم اجرا می‌شود: هندلرِ نسخهٔ *قبل از رفع* در حالتِ مسدود
     هیچ ناوبری‌ای ندارد ⇒ ثابت می‌شود قاعده از هوا ساخته نشده.

آفلاین است. PF_BUTTON_NO_MUT=1 بخشِ جهش را رد می‌کند (فرارِ سریعِ CI محدود).
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import selfcheck as SC  # noqa: E402

# ── ابزارِ جهش (سبکِ مخزن: لنگر باید یکتا باشد وگرنه خطا — نه سبزِ خاموش) ──
CHECKS, FAILS = [], []


def check(name, cond, detail=""):
    CHECKS.append(name)
    if not cond:
        FAILS.append((name, detail))
    return bool(cond)


def copy_repo():
    d = tempfile.mkdtemp(prefix="pf_button_")
    dst = os.path.join(d, "app")
    shutil.copytree(HERE, dst, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", ".ff_cache.json", ".te_actuals.json",
        "*.log", ".DS_Store", "fundamental_report.md"))
    return dst


def drop(d):
    shutil.rmtree(os.path.dirname(d), ignore_errors=True)


def _read(d, name):
    return io.open(os.path.join(d, name), encoding="utf-8").read()


def _write(d, name, txt):
    io.open(os.path.join(d, name), "w", encoding="utf-8").write(txt)


def edit(d, name, old, new, expect=1):
    txt = _read(d, name)
    n = txt.count(old)
    if n != expect:
        raise AssertionError("لنگرِ جهش در %s %d بار پیدا شد (باید %d باشد): %r"
                             % (name, n, expect, old[:60]))
    _write(d, name, txt.replace(old, new))


def scan(d):
    return SC.button_alive_problems(d, SC.page_sources(d))


def run_guard(mutate=None):
    d = copy_repo()
    try:
        if mutate:
            mutate(d)
        return scan(d)
    finally:
        drop(d)


def red(name, needle, mutate):
    """جهش باید قاعده را قرمز کند و پیام باید «سوزن» را داشته باشد (نام‌دار)."""
    d = copy_repo()
    try:
        mutate(d)
        probs, _ = scan(d)
        hit = any(needle in p for p in probs)
        check("قرمز: " + name, hit,
              "قاعده سبز ماند یا پیامِ نام‌دار نداشت! probs=" + str(probs)[:300])
    finally:
        drop(d)


def green(name, mutate, key):
    """جهشِ بی‌گناه نباید قرمز شود و شاخصِ مربوطه باید سبز بمانَد."""
    d = copy_repo()
    try:
        mutate(d)
        probs, st = scan(d)
        check("بی‌گناه: " + name, probs == [] and st.get(key) is True,
              "probs=" + str(probs)[:200] + " stats=" + str(st))
    finally:
        drop(d)


NO_MUT = os.environ.get("PF_BUTTON_NO_MUT") == "1"

# ═══ ۱) قاعده روی مخزنِ سالم ═══
print("═══ ۱) قاعدهٔ نگهبان روی مخزنِ سالم ═══")
p0, s0 = scan(HERE)
check("قاعده: مخزنِ سالم صفر خطا", p0 == [], str(p0)[:300])
check("قاعده: تنها یک کلیدِ تبِ نو داریم (فاندمنتال)", s0.get("newtab") == 1, str(s0))
check("قاعده: سنجشِ NULL در هندلرِ فاندمنتال سبز", s0.get("fund_guard") is True, str(s0))
check("قاعده: تورِ ایمنیِ هم‌تبِ فاندمنتال سبز", s0.get("fund_fallback") is True, str(s0))
check("قاعده: پیامِ دیدنیِ بروزرسانی سبز", s0.get("rf_visible") is True, str(s0))
check("قاعده: واکنشِ دیدنیِ کلیدِ بروزرسانی سبز", s0.get("rf_flash") is True, str(s0))

# ═══ ۲) جهش‌آزماییِ قاعده ═══
if not NO_MUT:
    print("═══ ۲) جهش‌آزماییِ قاعده (قرمز/بی‌گناه) ═══")
    red("هندلرِ کلیدِ فاندمنتال کاملاً حذف شده",
        "اصلاً هندلر ندارد",
        lambda d: edit(d, "app.py", "fundBtn.onclick=()=>{", "fundBtn.onclick_GONE=()=>{"))
    red("هندلر دیگر هیچ ناوبری‌ای ندارد (نه تبِ نو، نه هم‌تب)",
        "هیچ ناوبری‌ای به صفحهٔ فاندمنتال",
        lambda d: edit(d, "app.py",
                       '    try{ tab=window.open("/fundamental","_blank","noopener"); }catch(e){ tab=null; }\n'
                       '    if(!tab) location.assign("/fundamental");\n',
                       '    void tab;\n'))
    red("نتیجهٔ window.open دیگر سنجیده نمی‌شود (کوتاه‌شدنِ رگرسیونی)",
        "نتیجهٔ window.open را نمی‌سنجد",
        lambda d: edit(d, "app.py", 'if(!tab) location.assign("/fundamental");',
                       'location.assign("/fundamental");'))
    red("تورِ ایمنیِ «همین‌تب» برداشته شده (کلید دوباره بی‌صدا می‌مُرد)",
        "تورِ ایمنیِ «همین‌تب» ندارد",
        lambda d: edit(d, "app.py", 'if(!tab) location.assign("/fundamental");',
                       'void tab;'))
    red("پیامِ دیدنیِ «چیزی برای بروزرسانی نیست» (rf-hint) حذف شده",
        "پیامِ دیدنیِ «چیزی برای بروزرسانی نیست»",
        lambda d: edit(d, "app.py", "rf-hint", "rf-hid", expect=2))
    red("واکنشِ دیدنیِ کلیدِ بروزرسانی از JS برداشته شده (کلاسِ need)",
        "هیچ واکنشِ دیدنی",
        lambda d: edit(d, "app.py", 'classList.add("need")', 'classList.add("needX")'))
    red("استایلِ واکنشِ دیدنیِ کلیدِ بروزرسانی از CSS برداشته شده",
        "هیچ واکنشِ دیدنی",
        lambda d: edit(d, "app.py", ".rf-btn.need{", ".rf-btn.needX{"))

    # بی‌گناه‌ها: نباید قرمز شوند
    green("افزودنِ یک خطِ بی‌اثر پس از ناوبریِ هم‌تب سبز می‌مانَد",
          lambda d: edit(d, "app.py", 'if(!tab) location.assign("/fundamental");',
                         'if(!tab) location.assign("/fundamental");\n    fundBtn.blur();'),
          "fund_fallback")
    green("کشیدنِ زمانِ فلاشِ کلیدِ بروزرسانی سبز می‌مانَد",
          lambda d: edit(d, "app.py",
                         'setTimeout(()=>refreshBtn.classList.remove("need"), 2200);',
                         'setTimeout(()=>refreshBtn.classList.remove("need"), 2600);'),
          "rf_flash")
    green("حذفِ آرگومانِ features از window.open سبز می‌مانَد (تبِ نو سرِ جایش است)",
          lambda d: edit(d, "app.py",
                         'window.open("/fundamental","_blank","noopener")',
                         'window.open("/fundamental","_blank")'),
          "fund_guard")
    green("نامِ کلاسِ نمایشیِ پیام سبز می‌مانَد (متن و جای پیام مهم است)",
          lambda d: edit(d, "app.py", 'st.className="status rf-hint"', 'st.className="status rf-hint rf-hint-top"'),
          "rf_visible")

# ═══ ۳) رفتارِ خالصِ هندلرِ کلید (اجرای واقعی با node) ═══
print("═══ ۳) رفتارِ خالصِ کلیدِ فاندمنتال (بدونِ مرورگر، با node) ═══")
NODE = shutil.which("node")

# سوزنِ «شاهدِ باگ»: همان یک‌خطیِ نسخهٔ قبل از رفع (بدونِ سنجشِ NULL و بدونِ هم‌تب)
LEGACY_HANDLER = 'fundBtn.onclick=()=>window.open("/fundamental","_blank","noopener");'

HARNESS = """\"use strict\";
const mode = process.argv[2];
const opened = [], assigned = [];
const window = {
  open: (u, t, f) => {
    opened.push(u);
    if (mode === "block") return null;          // پاپ‌آپ‌بلاکر / نصبِ PWA: NULL
    if (mode === "throw") throw new Error("blocked");
    return {};                                  // تبِ نو واقعاً باز شد
  }
};
const location = { assign: (u) => assigned.push(u) };
const fundBtn = {};
__HANDLER__
fundBtn.onclick();
process.stdout.write(JSON.stringify({ opened: opened, assigned: assigned }));
"""


def run_handler(handler_src, mode):
    """هندلر را در node با استاب‌های window/location اجرا می‌کند → dict خروجی."""
    js = HARNESS.replace("__HANDLER__", handler_src)
    fd, path = tempfile.mkstemp(suffix=".js", prefix="pf_btn_")
    try:
        os.close(fd)
        io.open(path, "w", encoding="utf-8").write(js)
        out = subprocess.run([NODE, path, mode], capture_output=True, text=True,
                             timeout=20)
        if out.returncode != 0:
            return {"error": (out.stderr or "")[-300:]}
        return json.loads(out.stdout or "{}")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


if NODE:
    page = SC.page_sources(HERE).get("HTML") or ""
    m = SC._FUND_ARROW_RE.search(page) if hasattr(SC, "_FUND_ARROW_RE") else None
    handler = m.group(1) if m else ""
    check("رفتار: هندلرِ واقعیِ فاندمنتال از صفحه استخراج شد", bool(handler),
          "الگوی هندلر پیدا نشد")
    if handler:
        r = run_handler(handler, "block")
        check("رفتار: پاپ‌آپِ مسدود ⇒ همان تب به /fundamental می‌رود (کلید نمی‌میرد)",
              r.get("opened") == ["/fundamental"] and r.get("assigned") == ["/fundamental"],
              str(r)[:250])
        r = run_handler(handler, "ok")
        check("رفتار: پاپ‌آپِ مجاز ⇒ تبِ نو باز می‌شود و صفحهٔ جاری جابه‌جا نمی‌شود",
              r.get("opened") == ["/fundamental"] and r.get("assigned") == [],
              str(r)[:250])
        r = run_handler(handler, "throw")
        check("رفتار: window.open که پرت می‌کند هم کلید را بی‌صدا نمی‌گذارد",
              r.get("assigned") == ["/fundamental"], str(r)[:250])
    r = run_handler(LEGACY_HANDLER, "block")
    check("شاهدِ باگ: هندلرِ نسخهٔ قبل در حالتِ مسدود هیچ ناوبری‌ای نداشت "
          "(⇒ شکایتِ کاربر واقعی بود، قاعده از هوا ساخته نشده)",
          r.get("opened") == ["/fundamental"] and r.get("assigned") == [], str(r)[:250])
    r = run_handler(LEGACY_HANDLER, "ok")
    check("شاهدِ باگ: نسخهٔ قبل در حالتِ مجاز فقط تبِ نو باز می‌کرد (سنجشِ NULL نداشت)",
          r.get("assigned") == [] and r.get("opened") == ["/fundamental"], str(r)[:250])
else:
    # CI همیشه node دارد؛ این فقط فرارِ محلیِ بدونِ node است — خاموش و بی‌صدا نه،
    # با هشدارِ صریح رد می‌شود تا کسی توهمِ پوششِ رفتاری نگیرد.
    print("⚠ node در دسترس نیست — بخشِ رفتاری رد شد "
          "(CI گامِ node را دارد؛ اینجا فقط قاعدهٔ استاتیک سنجیده شد)")

# ── جمع‌بندی ──
print("\n• بررسی‌ها: %d" % len(CHECKS))
if FAILS:
    for name, detail in FAILS:
        print("::error::❌ %s — %s" % (name, detail[:220]))
    print("\n❌ آزمونِ «کلیدِ بی‌واکنش نداریم» رد شد — %d از %d بررسی شکست خورد"
          % (len(FAILS), len(CHECKS)))
    sys.exit(1)
print("✅ آزمونِ «کلیدِ بی‌واکنش نداریم» پاس شد — تورِ ایمنیِ هم‌تبِ فاندمنتال "
      "(سنجشِ NULL پاپ‌آپ)، ناوبریِ واقعی در سه حالتِ اجرا، و واکنشِ دیدنیِ کلیدِ "
      "بروزرسانی همه قفل‌اند")
