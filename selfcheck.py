#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""نگهبانِ سلامتِ pipfound — نمی‌گذارد اپ دوباره با یک ویرایشِ خراب بی‌صدا از کار بیفتد.

چه کار می‌کند:
  ۱) سینتکسِ پایتونِ همه‌ی ماژول‌ها را چک می‌کند (ast.parse — بدونِ اجرای کد).
  ۲) متنِ صفحه‌های HTML/FUND_PAGE را از app.py بیرون می‌کشد، هر بلوکِ <script> را
     با موتورِ JS (node --check) از نظرِ سینتکس اعتبارسنجی می‌کند، و یک چکِ
     استاتیکِ دامنه هم می‌زند: هر تابعی که در صفحه **صدا زده شده ولی هیچ‌جا
     تعریف نشده** را می‌گیرد (همان کلاسی از خرابی که node --check نمی‌بیند و
     فقط سرِ اجرا به ReferenceError می‌رسد — مثلاً حذفِ تعریفِ closePick).
  ۳) چکِ اتصالِ HTML و JS (استاتیک): idِ تکراری در یک سند، ارجاعِ JS به idی که
     ساخته نمی‌شود، هندلرِ inline، و انتسابِ هندلر/تایمر به نامی که تعریف
     نشده (`x.onclick = foo` پرانتز ندارد، پس چکِ بندِ ۲ نمی‌بیندش). کلاس/idِ
     استفاده‌نشده هم شمرده می‌شود، ولی فقط به‌شکلِ «هشدار» — آن هم با احتسابِ
     دارایی‌های وبِ بیرون (هارنسِ بصری، سرویس‌ورکر)، تا لنگرهای زنده «مرده»
     نام نگیرند.
  ۴) چکِ قراردادِ PWA (استاتیک، بدونِ اجرا): سینتکسِ sw.js، هندلرهای install/
     activate/fetch، نامِ کش، آرایهٔ پوستهٔ کش و addAll آن، معافیتِ «/api/» از کش،
     فالبکِ آفلاین، گاردِ «res.ok» قبل از هر cache.put، کش‌اول بودنِ آیکون‌ها، و
     تطابقِ هر وعده (مسیرهای پوستهٔ کش، آیکون‌های مانیفست و آیکون‌های خودِ صفحه،
     start_url) با فایلِ واقعی و مسیرهای سروشده‌ی app.py، به‌علاوهٔ نسخه‌بندیِ
     خودکارِ کش (جای‌گذار ↔ جانشینیِ سرور) و بنرِ «نسخهٔ تازه» با هماهنگیِ
     skipWaiting (پیام ↔ controllerchange ↔ رفرشِ قیدشده به تأییدِ کاربر).
  ۵) چکِ «هیچ کلیدی گم نشود»: هر کنترلی که در نسخه‌ی سالمِ قبلی وجود داشت و
     جاوااسکریپت به آن وصل بود، باید سرِ جایش باشد. همچنین مسیرها (routeها).
  ۶) اسنپ‌شاتِ نسخه‌ی سالم را در ~/pipfound/good نگه می‌دارد و با فلگ --guard
     اگر کد خراب بود، خودکار همان نسخه‌ی سالم را برمی‌گرداند.
کاربرد:
    python3 selfcheck.py                     # گزارشِ سلامت (exit 0 سالم / 1 خراب)
    python3 selfcheck.py --guard             # اگر خراب بود، نسخه‌ی سالم را برگردان
    python3 selfcheck.py --live              # اندپوینت‌های سرورِ در حالِ اجرا را هم صدا بزن
    python3 selfcheck.py --snapshot          # بازتعریفِ مبنای «سالم» (بعد از تغییراتِ عمدیِ UI)
    python3 selfcheck.py --accept-removals --snapshot   # اگر عمداً دکمه‌ای را حذف کرده‌ای
    python3 selfcheck.py --json              # خروجیِ ماشین‌خوان
    python3 selfcheck.py --root /path        # چکِ یک نسخه‌ی دیگر (برای تست)
"""
import argparse
import ast
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

HOME = os.path.expanduser("~")
BASE = os.path.join(HOME, "pipfound")
GOOD = os.path.join(BASE, "good")            # اسنپ‌شاتِ «آخرین نسخه‌ی سالم»
PREV = os.path.join(BASE, "good_prev")       # یک نسلِ قبل‌تر (تورِ دومِ ایمنی)
LOG = os.path.join(BASE, "selfcheck.log")

# فایل‌هایی که در اسنپ‌شات و بازگردانی دخیل‌اند
TRACKED = ["app.py", "fundamental.py", "confluence.py", "smc_engine.py",
           "macro_context.py", "backtest.py", "risk.py",
           "manifest.webmanifest", "sw.js",
           "icon-180.png", "icon-192.png", "icon-192-mask.png",
           "icon-512.png", "icon-512-mask.png"]

PAGE_CONSTS = ("HTML", "FUND_PAGE")

# فایلِ مبنای «هیچ کلیدی گم نشود» که در گیت کامیت می‌شود تا در CI هم کار کند
REPO_BASELINE_NAME = "selfcheck-baseline.json"

# کنترل‌هایی که همیشه باید در صفحه باشند (کلیدهای اصلیِ اپ)
REQUIRED_IDS = ["sym", "go", "bt", "sbBtn", "setupsBtn", "fundBtn",
                "refreshBtn", "archiveBtn", "jbtn"]

LIVE_PATHS = ["/api/health", "/", "/manifest.webmanifest", "/sw.js",
              "/api/fundamental-archive?hours=6"]

PORT = 8787


# ─────────────────────────── ابزارهای کمکی ───────────────────────────
def _strip_block_comments(text):
    """کامنت‌های بلوکیِ `/* … */` را با فاصله می‌پوشاند (هم‌طول). چرا: کامنتِ
    داخلِ آرایهٔ پوستهٔ کش نباید آدرسِ «وعده‌داده‌شده» به‌حساب بیاید."""
    return re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group(0)), text, flags=re.S)


def _log(line):
    try:
        os.makedirs(BASE, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            ts = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{ts}  {line}\n")
    except Exception:
        pass


def js_engine():
    """مسیرِ موتورِ JS برای چکِ سینتکس (node)."""
    cands = [shutil.which("node"), os.path.join(HOME, ".local/bin/node"),
             "/opt/homebrew/bin/node", "/usr/local/bin/node",
             "/opt/homebrew/bin/deno", "/usr/local/bin/deno"]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


# ─────────────────────────── چک‌ها ───────────────────────────
def py_syntax_problems(root):
    """سینتکسِ همه‌ی فایل‌های پایتون را بدونِ اجرا چک می‌کند."""
    bad = []
    try:
        names = sorted(n for n in os.listdir(root) if n.endswith(".py"))
    except Exception as e:
        return [f"پوشه خوانده نشد: {e}"]
    for name in names:
        src = read_text(os.path.join(root, name))
        try:
            ast.parse(src, filename=name)
        except SyntaxError as e:
            bad.append(f"{name}:{e.lineno}: {e.msg}")
        except Exception as e:
            bad.append(f"{name}: {e}")
    return bad


def page_sources(root):
    """متنِ HTML و FUND_PAGE را از app.py بیرون می‌کشد (بدونِ import)."""
    src = read_text(os.path.join(root, "app.py"))
    if not src:
        return {}
    try:
        tree = ast.parse(src, filename="app.py")
    except Exception:
        return {}
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            nm = node.targets[0].id
            if nm not in PAGE_CONSTS:
                continue
            try:
                val = ast.literal_eval(node.value)
            except Exception:
                continue
            if isinstance(val, str) and val:
                out[nm] = val
    return out


def extract_scripts(html):
    return re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.S | re.I)


def js_syntax_problems(pages):
    """سینتکسِ هر بلوکِ <script> را با موتورِ JS چک می‌کند → (خطاها, چک‌شد؟)"""
    engine = js_engine()
    if not engine:
        return ["موتورِ JS پیدا نشد (node) — چکِ سینتکسِ JS رد شد"], False
    probs, tmpd = [], tempfile.mkdtemp(prefix="pf_jscheck_")
    try:
        for pname in sorted(pages):
            for i, code in enumerate(extract_scripts(pages[pname]), 1):
                if not code.strip():
                    continue
                fp = os.path.join(tmpd, f"{pname}_{i}.js")
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(code)
                cmd = [engine, "--check", fp]
                if engine.endswith("deno"):
                    cmd = [engine, "check", fp]
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
                except Exception as e:
                    probs.append(f"{pname} · اسکریپت #{i}: اجرای چک ممکن نشد ({e})")
                    continue
                if r.returncode != 0:
                    blob = [l.strip() for l in ((r.stderr or "") + (r.stdout or "")).strip().splitlines() if l.strip()]
                    detail = next((l for l in blob if l.startswith(("SyntaxError", "ReferenceError", "error:"))), "")
                    if not detail:
                        detail = next((l for l in blob if "SyntaxError" in l), "")
                    if not detail and blob:
                        detail = blob[-1][:160]
                    probs.append(f"{pname} · اسکریپت #{i}: {detail or 'خطای سینتکس'}")
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    return probs, True


# ────────────── چکِ استاتیکِ دامنه: «صدا زده شده ولی تعریف نشده» ──────────────
# چرا لازم است: node --check فقط سینتکس را می‌بیند. اگر تعریفِ یک تابع پاک شود
# ولی فراخوانی‌هایش بمانند، گیتِ سینتکس سبز می‌مانَد و بدنه‌ی صفحه سرِ اجرا با
# ReferenceError بی‌صدا می‌میرد (همان چیزی که یک‌بار مسیرهای بستنِ کرکره را
# بی‌اثر کرد). این چک همان شکاف را می‌بندد، بدونِ اجرای کد.
JS_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "function", "return", "typeof", "new",
    "delete", "void", "instanceof", "in", "of", "do", "else", "case", "throw", "try",
    "finally", "with", "class", "extends", "super", "this", "yield", "await", "async",
    "import", "export", "from", "default", "break", "continue", "var", "let", "const",
    "static", "get", "set", "true", "false", "null", "undefined", "NaN", "Infinity",
    "debugger", "enum", "as",
}

# نام‌هایی که مرورگر/زبان خودش می‌دهد؛ اگر تابعی از اپ نبود، اسمش را همین‌جا
# اضافه کن (اگر جایی مثبتِ کاذب دادی، این تنها جای درست برای اصلاح است).
JS_GLOBALS = {
    "fetch", "setTimeout", "setInterval", "clearTimeout", "clearInterval",
    "requestAnimationFrame", "cancelAnimationFrame", "requestIdleCallback",
    "queueMicrotask", "structuredClone", "postMessage", "open", "close", "focus",
    "print", "scrollTo", "scrollBy", "scroll", "matchMedia", "getComputedStyle",
    "addEventListener", "removeEventListener", "dispatchEvent", "alert", "confirm",
    "prompt", "parseInt", "parseFloat", "isFinite", "isNaN", "encodeURI",
    "encodeURIComponent", "decodeURI", "decodeURIComponent", "escape", "unescape",
    "atob", "btoa", "getSelection", "Intl", "Number", "String", "Boolean", "Array",
    "Object", "Math", "JSON", "Date", "RegExp", "Error", "TypeError", "RangeError",
    "SyntaxError", "EvalError", "URIError", "AggregateError", "Map", "Set", "WeakMap",
    "WeakSet", "Promise", "Symbol", "BigInt", "Proxy", "Reflect", "Function",
    "ArrayBuffer", "SharedArrayBuffer", "DataView", "Int8Array", "Uint8Array",
    "Uint8ClampedArray", "Int16Array", "Uint16Array", "Int32Array", "Uint32Array",
    "Float32Array", "Float64Array", "BigInt64Array", "BigUint64Array", "TextEncoder",
    "TextDecoder", "URL", "URLSearchParams", "Blob", "File", "FileReader",
    "FormData", "Headers", "Request", "Response", "AbortController", "AbortSignal",
    "XMLHttpRequest", "WebSocket", "EventSource", "BroadcastChannel", "Worker",
    "SharedWorker", "MessageChannel", "Notification", "Image", "Audio", "Option",
    "CustomEvent", "Event", "EventTarget", "IntersectionObserver", "ResizeObserver",
    "MutationObserver", "PerformanceObserver", "document", "window", "self",
    "globalThis", "navigator", "location", "history", "localStorage", "sessionStorage",
    "indexedDB", "caches", "crypto", "performance", "console", "screen", "frames",
    "parent", "top", "isSecureContext", "eval",
}

# قالبِ `` ` `` اینجا نیست: خودش شاخه‌ی جداگانه دارد (متنش فاصله می‌شود ولی ${...} کد می‌ماند)
_JS_STRING_OPENERS = {"'", '"'}
_JS_REGEX_BEFORE = set("=(,:[!&|?{};+-*%<>~^")


def strip_js_literals(code):
    """رشته/کامنت/regexِ ادبی را با فاصله جایگزین می‌کند (طول و شمارِ خط حفظ می‌شود)
    تا نام‌های داخلِ متنِ آن‌ها به‌اشتباه «فراخوانی» شمرده نشوند."""
    out = list(code)
    n = len(code)
    frames = [{"kind": "code", "depth": 0}]     # قالبِ `` ` `` هم پشته دارد
    prev, i = "", 0

    def blank(a, b):
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        f = frames[-1]
        c = code[i]
        nxt = code[i + 1] if i + 1 < n else ""

        if f["kind"] == "tpl":                  # داخلِ متنِ template
            if c == "\\":
                blank(i, i + 2)
                i += 2
                continue
            if c == "`":
                out[i] = " "
                frames.pop()
                prev = "`"
                i += 1
                continue
            if c == "$" and nxt == "{":        # ${...} کد است، نه متن
                blank(i, i + 2)
                frames.append({"kind": "expr", "depth": 1})
                i += 2
                continue
            blank(i, i + 1)
            i += 1
            continue

        # حالتِ code/expr
        if c in _JS_STRING_OPENERS:
            j = i + 1
            while j < n:
                if code[j] == "\\":
                    j += 2
                    continue
                if code[j] == c or code[j] == "\n":
                    break
                j += 1
            blank(i, j + 1)
            prev, i = c, min(j + 1, n)
            continue
        if c == "`":
            out[i] = " "
            frames.append({"kind": "tpl", "depth": 0})
            i += 1
            continue
        if c == "/" and nxt == "/":
            j = code.find("\n", i)
            j = n if j == -1 else j
            blank(i, j)
            i = j
            continue
        if c == "/" and nxt == "*":
            j = code.find("*/", i + 2)
            j = n if j == -1 else j
            blank(i, j + 2)
            i = min(j + 2, n)
            continue
        if c == "/" and (prev == "" or prev in _JS_REGEX_BEFORE):
            j, in_class = i + 1, False
            while j < n:
                if code[j] == "\\":
                    j += 2
                    continue
                if code[j] == "[":
                    in_class = True
                elif code[j] == "]":
                    in_class = False
                elif code[j] == "\n" or (code[j] == "/" and not in_class):
                    break
                j += 1
            blank(i, j + 1)
            prev, i = "/", min(j + 1, n)
            continue
        if f["kind"] == "expr":
            if c == "{":
                f["depth"] += 1
            elif c == "}":
                f["depth"] -= 1
                if f["depth"] == 0:
                    out[i] = " "
                    frames.pop()
                    prev, i = "}", i + 1
                    continue
        if not c.isspace():
            prev = c
        i += 1
    return "".join(out)


# تعریف‌ها: اعلانِ تابع/کلاس/متغیر، انتسابِ تابع، متدها و کلیدهای شیء، برچسب‌ها
_JS_DEF_RES = (
    r"function\s*\*?\s*([A-Za-z_$][\w$]*)",
    r"class\s+([A-Za-z_$][\w$]*)",
    r"\b(?:var|let|const)\s+([A-Za-z_$][\w$]*)",
    r"\b(?:var|let|const)\s*[\[{]([^\]}]*)[\]}]",
    r"([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?function",
    r"([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?:\([^()]*\)|[A-Za-z_$][\w$]*)\s*=>",
    r"(?:window|globalThis|self)\s*\.\s*([A-Za-z_$][\w$]*)\s*=",
)
_JS_PARAM_RES = (
    r"function\s*\*?\s*[A-Za-z_$\w$]*\s*\(([^)]*)\)",
    r"\(([^()]*)\)\s*=>",
    r"([A-Za-z_$][\w$]*)\s*=>",
    r"catch\s*\(([^)]*)\)",
)
_JS_MEMBER_DEF_RE = re.compile(
    r"(?:^|[{,;(\n])\s*(?:async\s+)?(?:static\s+)?(?:get\s+|set\s+)?"
    r"([A-Za-z_$][\w$]*)\s*\([^;{}]*\)\s*\{")
_JS_KEY_RE = re.compile(r"(?:^|[{,]\s*)([A-Za-z_$][\w$]*)\s*:")
_JS_LABEL_RE = re.compile(r"(?:^|[\n;{,])\s*([A-Za-z_$][\w$]*)\s*:\s*(?:for|while|do|\{)")
_JS_CALL_RE = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(")
_JS_WORD_BEFORE_RE = re.compile(r"([A-Za-z_$][\w$]*)\s*$")
_IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")


def js_static_names(stripped):
    """نام‌های تعریف‌شده و نام‌هایی که در جای «فراخوانی» آمده‌اند."""
    defined, called = set(), {}
    for rx in _JS_DEF_RES + _JS_PARAM_RES:
        for g in re.findall(rx, stripped):
            defined.update(_IDENT_RE.findall(g))
    defined.update(_JS_MEMBER_DEF_RE.findall(stripped))
    defined.update(_JS_KEY_RE.findall(stripped))
    defined.update(_JS_LABEL_RE.findall(stripped))
    for m in _JS_CALL_RE.finditer(stripped):
        name = m.group(1)
        if name in JS_KEYWORDS:
            continue
        before = stripped[max(0, m.start() - 40):m.start()]
        w = _JS_WORD_BEFORE_RE.search(before)
        if w and w.group(1) in JS_KEYWORDS:      # function foo( · new Foo( · get x(
            continue
        called[name] = called.get(name, 0) + 1
    return defined, called


def undefined_calls(pages):
    """تابع‌های صدا‌زده‌شده‌ای که در همان صفحه تعریف نشده‌اند.
    بلوک‌های <script> یک سند دامنه‌ی سراسریِ مشترک دارند، پس هر **صفحه** جدا
    شمرده می‌شود (تعریفِ هم‌نام در HTML نباید فراخوانیِ نداشته‌ی FUND_PAGE را
    ماست کند). → (خطاها, آمار)"""
    probs = []
    stats = {"defined": 0, "called": 0, "undefined": []}
    for pname in sorted(pages):
        code = "\n;\n".join(c for c in extract_scripts(pages[pname]) if c.strip())
        if not code.strip():
            continue
        defined, called = js_static_names(strip_js_literals(code))
        stats["defined"] += len(defined)
        stats["called"] += len(called)
        unknown = sorted((n for n in called
                          if n not in defined and n not in JS_GLOBALS),
                         key=lambda n: (-called[n], n))
        for n in unknown:
            stats["undefined"].append(n)
            probs.append(f"{pname} · تابعِ «{n}» صدا زده شده ولی هیچ‌جا تعریف نشده"
                         f" (×{called[n]})")
    return probs, stats


# ─────────── چکِ استاتیکِ اتصالِ HTML و JS: شناسه‌ها و هندلرها ───────────
# چرا لازم است: چکِ «تعریف‌نشده» فقط کدِ داخلِ <script> را می‌بیند. چند کلاسِ
# خرابی بیرونِ آن می‌مانند و تا سرِ اجرا بی‌صدا می‌مانند:
#   ۱) idِ تکراری در یک سند → getElementById فقط اولی را برمی‌گرداند و بقیه
#      دست‌نیافتنی می‌شوند.
#   ۲) JS به idی وصل می‌شود که هیچ‌جا ساخته نمی‌شود → آن دکمه هرگز کاری نمی‌کند.
#   ۳) هندلرِ inline در HTML (onclick="...") که تابعش در آن صفحه نیست.
#   ۴) انتسابِ هندلر/تایمر به «نامِ خالی» — x.onclick = foo — که **پرانتز ندارد**،
#      پس چکِ «صدا زده شده» نمی‌بیندش؛ اگر تعریفِ foo پاک شود، دکمه بی‌صدا می‌میرد.
#      (همین الگو در این اپ رایج است: `jb.onclick = saveJournal`.)
# ۵) استفاده‌نشده‌ها (کلاس/idِ مرده) شمرده می‌شوند ولی فقط «هشدار»اند: کدِ مرده
#    خرابی نیست، و اگر خطا شمرده شود نگهبانِ بازگردان، نیم‌کاره‌ی در حالِ ساخت
#    را بی‌دلیل برمی‌گرداند. و «استفاده‌نشده» یعنی هیچ‌جا نامش برده نشده: نه در
#    خودِ صفحه، نه در دارایی/هارنسِ وبِ بیرون (`consumer_assets`) — وگرنه هشدار،
#    پاک‌کردنِ لنگرِ زنده‌ی لایهٔ ۳ را توصیه می‌کرد (خطای هشدارِ دروغ).
# هر دو سند جدا سنجیده می‌شوند (HTML و FUND_PAGE دو دامنه و دو مارک‌آپِ جدا).
_ID_TOKEN = r"[A-Za-z0-9_\-]+"
_ID_DECL_RE = re.compile(r'\bid\s*=\s*["\'](' + _ID_TOKEN + r')["\']')
# ارجاعِ JS به یک id: هم getElementById("x")، هم هر فراخوانی با آرگومانِ "#x"
# (querySelector("#x") و کمکیِ خانگیِ $("#x") که در این اپ همه‌جا هست).
# نکته‌ی مهم: خودِ رشته‌ها با فاصله پوشانده می‌شوند تا نامِ داخلِ رشته «کد»
# شمرده نشود؛ پس «محلِّ فراخوانی» را از متنِ پوشانده‌شده می‌گیریم و «نامِ
# رشته‌ای» را از متنِ خام در همان آفست (این دو متن هم‌طول‌اند).
_GETID_HEAD_RE = re.compile(r"getElementById\s*\(")
_RAW_ID_ARG_RE = re.compile(r'\s*["\'](' + _ID_TOKEN + r')["\']')
# lambda "#x" فقط وقتی ارجاعِ id شمرده می‌شود که آرگومانِ یک انتخاب‌گر باشد
# (querySelector/querySelectorAll یا کمکیِ $) — وگرنه رشته‌ی "#04121f" یک رنگ
# است نه شناسه. نامِ شناسه هم با حرف/خط‌زیر شروع می‌شود (رنگِ شش‌رقمی نه).
_RAW_HASH_ID_RE = re.compile(r'["\']#([A-Za-z_][A-Za-z0-9_\-]*)["\']')
_SELECTOR_CALL_RE = re.compile(
    r"(?:^|[^.\w$])((?:[\w$]+\.)?(?:querySelector|querySelectorAll)|\$\$?)\s*\(\s*$")
# idی که خودِ JS سرِ ساختِ عنصر می‌دهد (قالبِ رشته‌ای یا انتسابِ مستقیم)
_JS_ID_DYN_RES = (
    re.compile(r'\.id\s*=\s*["\'](' + _ID_TOKEN + r')["\']'),
    re.compile(r'setAttribute\(\s*["\']id["\']\s*,\s*["\'](' + _ID_TOKEN + r')["\']'),
)
_HANDLER_ATTR_RE = re.compile(r"""\bon([a-z]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
# x.onclick = foo   (فقط «نامِ خالی»؛ نه فانکشنِ فلش، نه x.y و نه x.y() )
_HANDLER_ASSIGN_RE = re.compile(
    r"\.\s*(on[a-z]+)\s*=\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*(?=[;,)\n}]|$)")
# آرگومانِ نامِ خالی در تایمرها و در addEventListener (اینجا روی متنِ خام)
_TIMER_BARE_RE = re.compile(
    r"(setTimeout|setInterval|requestAnimationFrame|queueMicrotask)\s*\(\s*"
    r"(?:async\s+)?([A-Za-z_$][\w$]*)\s*[,)]")
_LISTENER_HEAD_RE = re.compile(r"addEventListener\s*\(")
_LISTENER_ARG_RE = re.compile(
    r'\s*["\'][^"\']*["\']\s*,\s*([A-Za-z_$][\w$]*)\s*[,)]')
_CLASS_ATTR_RE = re.compile(r'\bclass\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')
# فایل‌های «مصرف‌کننده»ی سمتِ مرورگر: هارنسِ تستِ بصری، سرویس‌ورکر، و هر
# داراییِ وبِ دیگر که به شناسه/کلاسِ صفحه ارجاع می‌دهد. بدونِ این‌ها هشدارِ
# «استفاده‌نشده» دروغ می‌گوید: مثلاً `btPanel` هیچ‌جا در app.py صدا زده
# نمی‌شود ولی تستِ بصری (ui_visual_check.cjs) وجودش را لازم دارد — اگر کسی
# حرفِ هشدار را گوش کند و «کدِ مرده» را پاک کند، لایهٔ ۳ می‌شکند.
_CONSUMER_SUFFIXES = (".cjs", ".js", ".html", ".css")


def consumer_assets(root):
    """(متن, نام‌ها)ی مصرف‌کننده‌های وبِ بیرونِ app.py — برای تفکیکِ «واقعاً
    بی‌ارجاع» از «لنگرِ هارنس/دارایی». اگر این‌ها خوانده نشوند، هشدارِ
    «استفاده‌نشده» بی‌اعتبار می‌شود (پیشنهادِ پاک‌کردنِ یک لنگرِ زنده)."""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        names = []
    kept, out = [], []
    for n in names:
        p = os.path.join(root, n)
        if n.endswith(_CONSUMER_SUFFIXES) and os.path.isfile(p):
            kept.append(n)
            out.append(read_text(p))
    return "\n".join(out), kept


def markup_of(html):
    """فقط «سمتِ مارک‌آپ» را می‌ماند: بلوک‌های <script> و کامنت‌های HTML خالی
    می‌شوند. چرا: مارک‌آپی که داخلِ رشتهٔ JS ساخته می‌شود (innerHTML) HTML نیست،
    و عنصری که کامنت شده هم وجود ندارد — شمردنِ آن‌ها مثبتِ کاذب می‌سازد."""
    out = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    return re.sub(r"<!--.*?-->", " ", out, flags=re.S)


def _token_re(name):
    """تطبیقِ کل‌واژه‌ی یک نام در مارک‌آپ/CSS/JS (خط تیره هم مرز است)."""
    return re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])")


def _class_tokens(page):
    """شمارِ هر کلاس در مقدارِ همهٔ class="..."های یک صفحه."""
    counts = {}
    for m in _CLASS_ATTR_RE.finditer(page):
        for t in (m.group(1) or m.group(2) or "").split():
            counts[t] = counts.get(t, 0) + 1
    return counts


def wiring_problems(pages, consumers=""):
    """اتصالِ HTML و JS را استاتیک می‌سنجد → (خطاها, هشدارها, آمار).

    `consumers` متنِ دارایی‌های وبِ دیگر است (هارنسِ بصری، سرویس‌ورکر) و فقط در
    بندِ ۵ بکار می‌آید: نامی که آن‌ها می‌برند «استفاده‌نشده» نیست."""
    probs, warns = [], []
    stats = {"pages": 0, "ids": 0, "classes": 0, "refs": 0, "handlers": 0,
             "dups": [], "missing_ids": [], "bad_handlers": [],
             "unused_ids": [], "unused_classes": [],
             "consumer_chars": len(consumers)}
    for pname in sorted(pages):
        html = pages[pname]
        if not html.strip():
            continue
        stats["pages"] += 1
        markup = markup_of(html)
        js_raw = "\n;\n".join(extract_scripts(html))
        js = strip_js_literals(js_raw) if js_raw.strip() else ""
        defined, _ = js_static_names(js) if js.strip() else (set(), {})

        # ۱) idِ تکراری در همین سند
        decl = _ID_DECL_RE.findall(markup)
        stats["ids"] += len(set(decl))
        for i in sorted({n for n in decl if decl.count(n) > 1}):
            stats["dups"].append(f"{pname}:{i}")
            probs.append(f"{pname} · idِ «{i}» {decl.count(i)} بار در همین صفحه اعلام "
                         "شده — getElementById فقط یکی را برمی‌گرداند")

        # ۲) JS به idی وصل می‌شود که در همین صفحه ساخته نمی‌شود
        known = set(decl) | set(_ID_DECL_RE.findall(js_raw))
        for rx in _JS_ID_DYN_RES:
            known |= set(rx.findall(js_raw))
        refs = set()
        for m in _GETID_HEAD_RE.finditer(js):
            am = _RAW_ID_ARG_RE.match(js_raw[m.end():m.end() + 120])
            if am:
                refs.add(am.group(1))
        for m in _RAW_HASH_ID_RE.finditer(js_raw):
            head = js[max(0, m.start() - 28):m.start()]
            if _SELECTOR_CALL_RE.search(head):
                refs.add(m.group(1))
        stats["refs"] += len(refs)
        for i in sorted(refs - known):
            stats["missing_ids"].append(f"{pname}:{i}")
            probs.append(f"{pname} · JS به idِ «{i}» وصل می‌شود ولی عنصری با این id "
                         "در این صفحه ساخته نمی‌شود")

        # ۳) هندلرِ inline در مارک‌آپ (تابع باید در همین صفحه تعریف شده باشد)
        for m in _HANDLER_ATTR_RE.finditer(markup):
            body = m.group(2) or m.group(3) or ""
            if not body.strip():
                continue
            stats["handlers"] += 1
            for fn in sorted(set(re.findall(r"([A-Za-z_$][\w$]*)\s*\(", body))):
                if fn not in defined and fn not in JS_GLOBALS:
                    stats["bad_handlers"].append(f"{pname}:on{m.group(1)}:{fn}")
                    probs.append(f"{pname} · هندلرِ «on{m.group(1)}» تابعِ «{fn}» را صدا "
                                 "می‌زند که در این صفحه وجود ندارد")

        # ۴) انتسابِ هندلر/تایمر به نامِ خالیِ تعریف‌نشده (بدونِ پرانتز)
        bare = [(m.group(1), m.group(2)) for m in _HANDLER_ASSIGN_RE.finditer(js)]
        bare += [(m.group(1), m.group(2)) for m in _TIMER_BARE_RE.finditer(js)]
        # addEventListener(event, foo) — نام داخلِ رشته نیست، پس از متنِ خام
        # خوانده می‌شود؛ محّلِ فراخوانی از متنِ پوشانده‌شده می‌آید تا رشته/کامنت
        # به‌عنوانِ کد شمرده نشود (طولِ دو متن یکی است).
        for m in _LISTENER_HEAD_RE.finditer(js):
            am = _LISTENER_ARG_RE.match(js_raw[m.end():m.end() + 160])
            if am:
                bare.append(("addEventListener", am.group(1)))
        for kind, nm in bare:
            if nm not in defined and nm not in JS_GLOBALS:
                stats["bad_handlers"].append(f"{pname}:{kind}:{nm}")
                probs.append(f"{pname} · «{kind}» به نامِ «{nm}» وصل شده که در این "
                             "صفحه وجود ندارد")

        # ۵) استفاده‌نشده‌ها — هشدار، نه خطا (کدِ مرده است، نه خرابی).
        # «استفاده‌نشده» یعنی **هیچ‌جا هم** نامش برده نشده: نه در خودِ صفحه،
        # نه در دارایی/هارنسِ وبِ بیرون. دارایی‌ها فقط همین‌جا بکار می‌آیند.
        for i in sorted(set(decl)):
            own = len(re.findall(r'\bid\s*=\s*["\']' + re.escape(i) + r'["\']', html))
            elsewhere = len(_token_re(i).findall(consumers))
            if len(_token_re(i).findall(html)) + elsewhere <= own:
                stats["unused_ids"].append(f"{pname}:{i}")
                warns.append(f"{pname} · idِ «{i}» جایی استفاده نشده (نه در صفحه، نه در "
                             "دارایی/هارنسِ وب)")
        in_html = _class_tokens(markup)
        everywhere = _class_tokens(html)
        stats["classes"] += len(in_html)
        for c in sorted(in_html):
            if len(_token_re(c).findall(html)) + len(_token_re(c).findall(consumers)) \
                    <= everywhere.get(c, 0):
                stats["unused_classes"].append(f"{pname}:{c}")
                warns.append(f"{pname} · کلاسِ «{c}» جایی استایل/استفاده نشده")
    return probs, warns, stats


def inventory(pages):
    """شناسه‌ی کنترل‌های HTML + کنترل‌هایی که JS به آن‌ها وصل است + مسیرها."""
    ids, js_text = set(), []
    for html in pages.values():
        ids |= set(re.findall(r'id="([A-Za-z0-9_\-]+)"', html))
        js_text.extend(extract_scripts(html))
    js = "\n".join(js_text)
    wired = set(re.findall(r'getElementById\(\s*"([A-Za-z0-9_\-]+)"\s*\)', js))
    wired |= set(re.findall(r'querySelector\(\s*"#([A-Za-z0-9_\-]+)"\s*\)', js))
    return {
        "ids": sorted(ids),
        "wired": sorted(wired & ids),
        "routes": [],   # در inventory_with_routes پر می‌شود
    }


def routes_of(root):
    """مسیرهای سرو‌شده را از متنِ app.py استخراج می‌کند."""
    src = read_text(os.path.join(root, "app.py"))
    found = set(re.findall(r'"(/(?:api/)?[A-Za-z0-9_\-\.]+)"', src))
    # مسیرهای داینامیک مثل /icon-*.png
    for m in re.findall(r'u\.path\.startswith\(\s*"([^"]+)"\s*\)', src):
        found.add(m + "*")
    return sorted(found)


# ────────── چکِ استاتیکِ قراردادِ PWA (سرویس‌ورکر ↔ مانیفست ↔ خودِ اپ) ──────────
# چرا لازم است: `node --check` فقط بلوک‌های <script> صفحه را می‌بیند (نه sw.js)، و
# هیچ لایه‌ای وعده‌های سرویس‌ورکر/مانیفست را با واقعیتِ سرور مقابله نمی‌کرد. چهار
# خرابیِ کاملاً بی‌صدا از همان شکاف می‌آید: (۱) آیکونی که مانیفست اعلام می‌کند ولی
# روی دیسک نیست یا مسیرش سرو نمی‌شود (نصبِ اپ با آیکونِ شکسته، بدونِ هیچ خطا)؛
# (۲) مسیری که در پوستهٔ کش precache می‌شود ولی روی سرور وجود ندارد (نصبِ
# سرویس‌ورکر نیمه‌کاره می‌مانَد)؛ بلندتر از همه (۳) `addAll(نامِ غلط)` یا نامِ
# ناهمخوانِ کش که با ReferenceError/پاک‌شدنِ کش، سرویس‌ورکر را بی‌اثر می‌کند و
# در کنسولِ کاربر هم دیده نمی‌شود؛ و (۴) کش‌کردنِ پاسخِ ناموفق یا `/api/` که
# بعد از یک خطای گذرا، دادهٔ زنده/صفحهٔ خطا را تا ارتقای کش گیر می‌اندازد.
_PWA_ROUTE_TUPLE_RE = re.compile(r"u\.path\s+(?:not\s+)?in\s*\(([^)]*)\)")
_PWA_ROUTE_EQ_RE = re.compile(r'u\.path\s*==\s*"([^"]+)"')
_PWA_STARTSWITH_RE = re.compile(r"u\.path\.startswith\(\s*\"([^\"]+)\"\s*\)")
_PWA_QUOTED_RE = re.compile(r'"([^"\n]*)"')
_PWA_CACHE_CONST_RE = re.compile(
    r"\b(?:const|let|var)\s+[A-Z_]*CACHE[A-Z_]*\s*=\s*\"([^\"\n]*)\"")
_PWA_ARRAY_DECL_RE = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\[([^\]]*)\]", re.S)
_PWA_ADDALL_RE = re.compile(r"\.addAll\(\s*([A-Za-z_$][\w$]*)\s*\)")
_PWA_OPEN_RE = re.compile(r"caches\.open\(\s*([^)]*?)\s*\)")
_PWA_PUT_RE = re.compile(r"\.put\s*\(")
_PWA_REGISTER_RE = re.compile(r"serviceWorker\.register\(\s*\"([^\"]+)\"\s*\)")
_PWA_MANIFEST_LINK_RE = re.compile(r"<link\b[^>]*\brel\s*=\s*[\"']manifest[\"']", re.I)
_PWA_LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.I)
_PWA_REL_RE = re.compile(r"\brel\s*=\s*[\"']([^\"']*)[\"']", re.I)
_PWA_HREF_RE = re.compile(r"\bhref\s*=\s*[\"']([^\"']+)[\"']", re.I)
_PWA_PATHNAME_TEST_RE = re.compile(r"/((?:\\.|[^/\\\n])+)/\s*\.test\(\s*url\.pathname")


def _gated_route_paths(src):
    """مسیرهایی که فقط با `u.path == "…"` شناخته می‌شوند ولی **زیرِ گاردی**
    هستند که آنها را نمی‌پذیرد — یعنی عملاً سرو نمی‌شوند.

    چرا لازم است: یک شرطِ داخلیِ `u.path == "/sw.js"` کافی است تا استخراجِ مسطح
    «سرو‌شده» به‌شمارش بیاید، حتی اگر خودِ دیسپچِ بیرونی `/sw.js` را از فهرستش
    برداشته باشد — و آن‌وقت نگهبان سبز می‌مانَد درحالی‌که `/sw.js` فقط ۴۰۴
    می‌دهد (همین تله در جهش‌آزماییِ همین چک لو رفت). تشخیص با تورفتگی است:
    از خطِ شرط به عقب می‌رویم تا اولین `if`ِ کم‌تورفتگی‌تر که `u.path` دارد
    (واسطه‌هایی مثلِ `if os.path.isfile(fp):` رد می‌شوند).
    """
    lines = src.splitlines()
    gated = set()
    for i, line in enumerate(lines):
        m = _PWA_ROUTE_EQ_RE.search(line)
        if not m:
            continue
        path, indent = m.group(1), len(line) - len(line.lstrip())
        for j in range(i - 1, -1, -1):
            prev = lines[j]
            if not prev.strip():
                continue
            if len(prev) - len(prev.lstrip()) >= indent:
                continue
            head = prev.strip()
            if head.startswith(("def ", "class ")):
                break              # از تابع/کلاس بیرون زدیم؛ گاردی نیست
            if not (head.startswith("if ") and "u.path" in head):
                continue           # واسطه‌ای دیگر مثلِ `if os.path.isfile(fp):`
            window = "\n".join(lines[j:i + 1])
            tm = _PWA_ROUTE_TUPLE_RE.search(window)
            if tm:
                # گاردِ `not in` برعکس عمل می‌کند (مثلِ گیتِ توکن که فقط
                # `/api/health` و `/api/install` را آزاد می‌گذارد).
                neg = bool(re.search(r"u\.path\s+not\s+in\s*\(", window))
                inside = '"%s"' % path in tm.group(1)
                # در گاردِ `in` ورود مشروط به عضویت است، در `not in` مشروط به
                # نبودن؛ پس شاخهٔ داخلی دقیقاً وقتی دست‌نیافتنی است که
                # «ورود» و «بودن در فهرست» یکی نشوند (بررسیِ جهتِ درست).
                if inside == neg:
                    gated.add(path)
                break
            em = _PWA_ROUTE_EQ_RE.search(window)
            if em and em.group(1) != path:
                gated.add(path)
                break
            sm = _PWA_STARTSWITH_RE.search(window)
            if sm:
                if not path.startswith(sm.group(1)):
                    gated.add(path)
                break
            break
    return gated


def _blank_js_comments(text):
    """کامنت‌های JS را با فاصله می‌پوشاند (هم‌طول می‌ماند) تا خطِ کامنت‌شده
    «قرارداد» شمرده نشود. کامنتِ خطی فقط وقتی پاک می‌شود که قبلش فاصله یا
    ابتدای خط باشد، وگرنه `https://...` داخلِ رشته هم کامنت گرفته می‌شد.

    **ترتیب مهم است:** اول کامنتِ خطی، بعد بلوکی. وگرنه یک `/api/*` داخلِ
    کامنتِ خطی (همین سرِ sw.js هست!) شروعِ کامنتِ بلوکیِ جعلی می‌شود و تا اولین
    `*/` همه‌چیز وسط را می‌خورد — از جمله ثابتِ `CACHE` و آرایه‌ی پوسته."""
    def _pad(m):
        return " " * len(m.group(0))
    out = re.sub(r"(?m)(^|[ \t])//[^\n]*", _pad, text)
    return re.sub(r"/\*.*?\*/", _pad, out, flags=re.S)


def _js_spans_ok_guards(text):
    """بازهٔ بدنهٔ هر `if (… .ok …) { … }` در متن → [(شروع, پایان)]."""
    spans = []
    for gm in re.finditer(r"if\s*\(([^)]*)\)\s*\{", text):
        if ".ok" not in gm.group(1):
            continue
        i = text.index("{", gm.start())
        body = _js_block_at(text, i)
        if body is not None:
            spans.append((i, i + len(body) + 1))
    return spans


def _ok_guarded_puts(text):
    """هر کش‌کردن باید **داخلِ** بلوکِ گاردِ پاسخِ سالم باشد (`if (res && res.ok)`).
    پنجرهٔ ثابتِ نویسه‌ای اینجا کار نمی‌کند: کامنت/قالب‌بندی فاصله را جابه‌جا
    می‌کند و منفیِ کاذب می‌سازد؛ پس عضویت در بلوک سنجیده می‌شود."""
    spans = _js_spans_ok_guards(text)
    return all(any(a < m.start() < b for a, b in spans)
               for m in _PWA_PUT_RE.finditer(text))


def _js_if_blocks(text):
    """[(شرط, بدنه, شروع, پایان)] برای هر `if (…) { … }`.

    لازم است چون «داخلِ گارد بودنِ یک عملِ خطرناک» با جست‌وجوی متنیِ ساده قابلِ
    تشخیص نیست: `if (healthy) { … caches.delete(…) }` و همان حذفِ **بی‌قید** در
    متن شبیه‌اند، ولی اولی امن و دومی برگشت‌ناپذیر است."""
    out = []
    for m in re.finditer(r"if\s*\(([^{;]*)\)\s*\{", text):
        i = text.find("{", m.start())
        body = _js_block_at(text, i)
        if body is not None:
            out.append((m.group(1), body, i, i + len(body) + 1))
    return out


def _js_fn_bodies(text):
    """{نامِ تابع: بدنهٔ آکولادی} برای شکل‌های سادهٔ همین پروژه
    (`function f(…){}`، `async function f(…){}` و `const f = (…) => {…}`)."""
    out = {}
    for m in re.finditer(r"(?:^|\n)\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", text):
        i = text.find("{", m.end())
        body = _js_block_at(text, i) if i > 0 else None
        if body is not None:
            out.setdefault(m.group(1), body)
    for m in re.finditer(
            r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{", text):
        i = text.index("{", m.end() - 1)
        body = _js_block_at(text, i)
        if body is not None:
            out.setdefault(m.group(1), body)
    return out


def _js_called_bodies(fns, bodies, rounds=1):
    """متنِ بدنه‌ها + بدنهٔ توابعی که (تا `rounds` پله) در همان متن صدا زده می‌شوند.

    لازم است چون رفتارِ یک مسیر می‌تواند در تابعِ کمکی بنشیند (مثلاً `pfNotice`
    که `pfTrack` صدایش می‌زند): بدونِ بازکردنِ آن پله‌ها، «قیدِ گم‌شده» یا
    «بازخوانیِ گم‌شده» دیده نمی‌شود و نگهبان سبزِ دروغ می‌مانَد.
    """
    txt = "\n".join(bodies)
    seen = set()
    for _ in range(max(1, rounds)):
        more = [n for n in sorted(fns)
                if n not in seen and re.search(r"\b%s\s*\(" % re.escape(n), txt)]
        if not more:
            break
        seen.update(more)
        txt += "\n" + "\n".join(fns[n] for n in more)
    return txt


def _js_block_around(text, i):
    """تنگ‌ترین بلوکِ آکولادی که نقطهٔ `i` را در بر می‌گیرد → (شروع, پایان).

    برای این‌که «بعد از وصل‌کردنِ شنونده» معنای دقیقی داشته باشد: نه کلِ فایل
    (که هر جای دیگری بتواند چک را سبزِ دروغ کند) و نه پنجرهٔ ثابتِ نویسه‌ای (که
    با کامنت/قالب‌بندی می‌شکند). اگر بلوکی نبود، کلِ متن.
    """
    depth, j = 0, i
    while j >= 0:
        c = text[j]
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                break
            depth -= 1
        j -= 1
    if j < 0:
        return 0, len(text)
    close, depth = j, 0            # از خودِ «{»ی بازکننده شمرده می‌شود
    while close < len(text):
        if text[close] == "{":
            depth += 1
        elif text[close] == "}":
            depth -= 1
            if depth == 0:
                break
        close += 1
    return j, close


def _update_watch_problems(page_html):
    """قراردادِ «نسخهٔ تازهٔ در صف بی‌بنر نمی‌مانَد» → [خطاها] (S10).

    چرا: ثبتِ **خودِ** صفحه سرِ بارگذاری (`register("/sw.js")`) هم می‌تواند یک
    نسخهٔ تازهٔ تازه نصب کند. اگر شنوندهٔ `updatefound` بعد از `await`ها وصل شود
    **و** وضعیتِ کنونیِ ثبت یک‌بار دیگر خوانده نشود، نصبِ سریعِ همان لحظه از دست
    می‌رود: `reg.waiting` در چکِ قبلش `null` بوده و رویداد هم پیش از وصل‌شدنِ
    شنونده رخ داده — پس کاربر روی کدِ کهنه می‌ماند **بدونِ این‌که بداند نسخهٔ تازه
    در صف است** (این حالت زنده دیده شد). این قاعده هر دو شرط را می‌سنجد: شنوندهٔ
    `updatefound` در دسترس باشد، و **بعد از** وصل‌کردنش همان مسیر وضعیت را
    دوباره بخواند (`reg.waiting`/`installed`) یا مسیرِ نمایشِ بنر را صدا بزند.
    """
    code = _blank_js_comments(page_html)
    fns = _js_fn_bodies(code)
    shows = {n for n, b in fns.items()
             if "pfSwBanner" in b and re.search(r'classList\.add\(\s*["\']show["\']', b)}
    m = re.search(r"addEventListener\s*(\()\s*[\"']updatefound[\"']", code)
    if not m:
        return ["صفحه روی `updatefound` گوش نمی‌دهد — نسخهٔ تازهٔ در صف هیچ‌وقت به کاربر خبر "
                "داده نمی‌شود و کاربر بی‌خبر روی کدِ کهنه می‌مانَد"]
    # پایانِ **همان فراخوانیِ** addEventListener (نه فقط نامِ رویداد): بدنهٔ
    # کل‌بکِ خودش «قید» نیست، بلکه انتظارِ رویداد است.
    j, depth = m.start(1), 0
    while j < len(code):
        if code[j] == "(":
            depth += 1
        elif code[j] == ")":
            depth -= 1
            if depth == 0:
                break
        j += 1
    after = code[j + 1:_js_block_around(code, m.start(1))[1]]
    reach = _js_called_bodies(fns, [after], rounds=4)
    reread = re.search(r"\.\s*waiting\b|\.\s*state\s*===?\s*[\"']installed[\"']", reach)
    shown = any(re.search(r"\b%s\s*\(" % re.escape(n), reach) for n in shows)
    if not (reread or shown):
        return ["بعد از وصل‌کردنِ شنوندهٔ `updatefound` وضعیتِ کنونیِ ثبت یک‌بار دیگر خوانده "
                "نمی‌شود — نسخهٔ تازه‌ای که خودِ همین بارگذاری راه انداخته (نصبِ سریع، پیش "
                "از وصل‌شدنِ شنونده) بی‌بنر و بی‌صدا در صف می‌مانَد"]
    return []


def _banner_memory_problems(page_html):
    """قراردادِ «بعداً»ی بنرِ نسخهٔ تازه → [خطاها].

    خواسته‌ی کاربر: «بعداً» تا پایانِ **همان بازدید** یاد بمانَد (بارگذاریِ دوباره
    بنر را برنگرداند)، ولی پیامِ «برگردانِ نسخه» هر بار دیده شود. سه خرابیِ
    بی‌صدا این‌جا گرفته می‌شود: (۱) یادِ نداشتن — کاربری که یک‌بار «بعداً» گفته،
    تا آخرِ بازدید در هر بارگذاری همان بنر را می‌بیند (بنرِ آزاردهنده = بنرِ
    بی‌اعتبار)؛ (۲) یادِ **خیلی** بادوام (`localStorage`) — بنر تا ابد خفه
    می‌شود و کاربر هیچ‌وقت خبرِ نسخهٔ تازه را نمی‌گیرد؛ (۳) گره‌خوردنِ پیامِ
    «برگردانِ نسخه» به همان یاد — خبرِ «نسخهٔ تازه ناقص بود» بی‌صدا می‌مانَد.

    مسیرها **ساختاری** پیدا می‌شوند (نه با نامِ ثابتِ تابع): تابع‌هایی که کلاسِ
    `show` را به `#pfSwBanner` می‌دهند = مسیرهای نمایش؛ آن‌که متنِ `#pfSwTxt` را
    عوض می‌کند = پیامِ برگردان؛ و آن‌که کلاسِ `show` را برمی‌دارد = مسیرِ «بعداً».
    """
    code = _blank_js_comments(page_html)
    fns = _js_fn_bodies(code)
    shows = {n: b for n, b in fns.items()
             if "pfSwBanner" in b and re.search(r'classList\.add\(\s*["\']show["\']', b)}
    rollbacks = {n: b for n, b in shows.items() if "pfSwTxt" in b}
    updates = {n: b for n, b in shows.items() if n not in rollbacks}
    hides = {n: b for n, b in fns.items()
             if "pfSwBanner" in b and re.search(r'classList\.remove\(\s*["\']show["\']', b)}
    if not (updates and rollbacks and hides):
        return ["دو مسیرِ بنر (نمایشِ نسخهٔ تازه ↔ پیامِ «برگردانِ نسخه») یا مسیرِ «بعداً» "
                "شناسایی نشد — قراردادِ «بعداً» سنجیده نشد"]
    readers = {n for n, b in fns.items() if re.search(r"sessionStorage\s*\.\s*getItem", b)}
    writers = {n for n, b in fns.items()
               if re.search(r"(?:session|local)Storage\s*\.\s*setItem", b)}

    def _with_helpers(bodies):
        """بدنه‌ها + بدنهٔ توابعِ کمکيِ خواندن/نوشتنِ یاد که در همان مسیر صدا زده می‌شوند."""
        return _js_called_bodies({n: fns[n] for n in (readers | writers)}, bodies)

    def _gated_by_later(txt):
        """آیا این مسیر با «یادِ بعداً» قید شده؟ (`if (<خواننده>) return …`)

        پارانتزِ تودرتو با شمارشِ عمق خوانده می‌شود: `if(pfLaterSaid())` با
        regexِ `[^)]*` شرطِ بریده می‌دهد و قیدِ درست را قید نمی‌شناسد.
        """
        for m in re.finditer(r"if\s*\(", txt):
            j, depth = m.end() - 1, 0
            while j < len(txt):
                if txt[j] == "(":
                    depth += 1
                elif txt[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            cond = txt[m.end():j]
            if not ("getItem" in cond
                    or any(re.search(r"\b%s\b" % re.escape(n), cond) for n in readers)):
                continue
            tail = txt[j + 1:j + 1 + 200]
            if re.match(r"\s*(\{[\s\S]{0,200}?\breturn\b|\breturn\b)", tail):
                return True
        return False

    probs = []
    dismiss = _with_helpers(list(hides.values()))
    if not re.search(r"sessionStorage\s*\.\s*setItem", dismiss):
        probs.append("«بعداً»ی بنر در نشست (`sessionStorage`) ذخیره نمی‌شود — کاربری که "
                     "یک‌بار «بعداً» گفته، تا پایانِ همان بازدید در هر بارگذاریِ دوباره "
                     "همان بنر را می‌بیند")
    if re.search(r"localStorage\s*\.\s*setItem", dismiss):
        probs.append("یادِ «بعداً» روی `localStorage` نشسته — بنر تا ابد خفه می‌شود و کاربر "
                     "هیچ‌وقت خبرِ نسخهٔ تازه را نمی‌گیرد (باید یادِ نشستی/sessionStorage باشد)")
    if not _gated_by_later(_with_helpers(list(updates.values()))):
        probs.append("مسیرِ نمایشِ بنرِ «نسخهٔ تازه» یادِ «بعداً» را نمی‌خواند — با هر "
                     "بارگذاریِ دوباره تا پایانِ همان بازدید بنر برمی‌گردد")
    roll_src = _with_helpers(list(rollbacks.values()))
    if _gated_by_later(roll_src) or any(re.search(r"\b%s\b" % re.escape(n), roll_src)
                                        for n in readers):
        probs.append("پیامِ «برگردانِ نسخه» هم به یادِ «بعداً» گره خورده — خبرِ «نسخهٔ تازه "
                     "ناقص بود» می‌تواند بی‌صدا بمانَد (این پیام باید هر بار دیده شود)")
    return probs


def _js_block_at(text, i):
    """بدنهٔ بلوکِ آکولادی که از جایِ `{`ِ i شروع می‌شود → متنِ درون، وگرنه None."""
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j]
        j += 1
    return None


def _js_listener_body(raw, masked, event):
    """بدنهٔ `self.addEventListener("event", …)` → متنِ خام، یا None.
    محلش از متنِ پوشانده (رشته/کامنت بی‌اثر) و نامِ رویداد از متنِ خام در همان
    آفست خوانده می‌شود — دو متن هم‌طول‌اند."""
    for m in re.finditer(r"addEventListener\s*\(", masked):
        am = re.match(r'\s*["\']([^"\']*)["\']', raw[m.end():m.end() + 80])
        if not am or am.group(1) != event:
            continue
        i = masked.find("{", m.end())
        if i < 0:
            return None
        return _js_block_at(raw, i)
    return None


def pwa_contract_problems(root):
    """وعده‌های سرویس‌ورکر و مانیفست را با خودِ اپ مقابله می‌کند → (خطاها, هشدارها, آمار).

    کاملاً استاتیک: هیچ‌کد و سرویسی اجرا نمی‌شود. اگر پوشه اصلاً PWA نداشته
    باشد (نه sw.js نه مانیفست) چیزی گزارش نمی‌شود — مگر آنکه خودِ صفحه به آن‌ها
    وعده داده باشد (لینکِ مانیفست/ثبتِ سرویس‌ورکر)، چون آن‌وقت وعده‌ی بی‌فایل است."""
    probs, warns = [], []
    stats = {"promised": 0, "shell": 0, "icons": 0, "cache": None, "served": 0,
             "api_bypass": False, "offline": False, "cache_first_icons": False,
             "cache_rev": False, "update_banner": False, "safe_upgrade": False,
             "banner_memory": False, "update_watch": False}
    src = read_text(os.path.join(root, "app.py"))
    sw = read_text(os.path.join(root, "sw.js"))
    man_raw = read_text(os.path.join(root, "manifest.webmanifest"))
    if not src and not sw and not man_raw:
        return probs, warns, stats

    # مسیرهایی که خودِ اپ سرو می‌کند: allowlistِ ثابت + پیشوندهای startswith
    served = set(_PWA_ROUTE_EQ_RE.findall(src))
    for body in _PWA_ROUTE_TUPLE_RE.findall(src):
        served |= set(_PWA_QUOTED_RE.findall(body))
    prefixes = _PWA_STARTSWITH_RE.findall(src)
    gated = _gated_route_paths(src)
    served -= gated          # شاخهٔ داخلیِ زیرِ گاردی که مسیر را نمی‌پذیرد
    stats["served"] = len(served)
    stats["gated"] = sorted(gated)

    def is_served(path):
        return path in served or any(path.startswith(p) for p in prefixes)

    def on_disk(path):
        return os.path.isfile(os.path.join(root, os.path.basename(path)))

    pages = page_sources(root)
    page_html = "\n".join(pages.values())

    # ۱) وعده‌های خودِ صفحه (نقطه‌ای که زنجیره از آن شروع می‌شود)
    has_man_link = bool(_PWA_MANIFEST_LINK_RE.search(page_html))
    reg = _PWA_REGISTER_RE.search(page_html)
    if has_man_link:
        stats["promised"] += 1
        if not man_raw:
            probs.append("صفحه به «manifest.webmanifest» لینک داده ولی فایلش کنارِ app.py نیست")
        if not is_served("/manifest.webmanifest"):
            probs.append("مسیرِ «/manifest.webmanifest» در app.py سرو نمی‌شود (لینکِ مانیفست ۴۰۴ می‌دهد)")
    if reg:
        stats["promised"] += 1
        sw_path = reg.group(1)
        if not sw:
            probs.append(f"صفحه سرویس‌ورکرِ «{sw_path}» را ثبت می‌کند ولی فایلش کنارِ app.py نیست")
        elif not is_served(sw_path):
            probs.append(f"مسیرِ «{sw_path}» در app.py سرو نمی‌شود (ثبتِ سرویس‌ورکر ۴۰۴ می‌دهد)")
    elif sw:
        probs.append("سرویس‌ورکر موجود است ولی خودِ صفحه هیچ‌جا ثبتش نمی‌کند — PWA بی‌صدا خاموش شده")

    if not sw and not man_raw:
        return probs, warns, stats

    shell_list = []
    # ۲) سرویس‌ورکر: سینتکس، هندلرها، نامِ کش، پوستهٔ کش، رفتارِ fetch
    if sw:
        sw_code = _blank_js_comments(sw)
        engine = js_engine()
        if not engine:
            warns.append("موتورِ JS پیدا نشد (node) — سینتکسِ sw.js چک نشد")
        else:
            tmpd = tempfile.mkdtemp(prefix="pf_swcheck_")
            try:
                fp = os.path.join(tmpd, "sw.js")
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(sw)
                cmd = [engine, "check", fp] if engine.endswith("deno") else [engine, "--check", fp]
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
                    if r.returncode != 0:
                        blob = [l.strip() for l in ((r.stderr or "") + (r.stdout or "")).strip().splitlines() if l.strip()]
                        detail = next((l for l in blob if "Error" in l), (blob[-1][:160] if blob else ""))
                        probs.append(f"sw.js خطای سینتکس دارد: {detail or 'بدونِ جزئیات'}")
                except Exception as e:
                    warns.append(f"اجرای چکِ سینتکسِ sw.js ممکن نشد ({e})")
            finally:
                shutil.rmtree(tmpd, ignore_errors=True)

        handlers = set(re.findall(r'addEventListener\s*\(\s*["\']([a-z]+)["\']', sw_code))
        for h in ("install", "activate", "fetch"):
            if h not in handlers:
                probs.append(f"سرویس‌ورکر هندلرِ «{h}» را ندارد")

        m = _PWA_CACHE_CONST_RE.search(sw_code)
        cache_name = m.group(1) if m else None
        stats["cache"] = cache_name
        if not cache_name:
            probs.append('نامِ کش در sw.js تعریف نشده (const CACHE = "…")')
        else:
            # تنها نام‌های **قطعی** خطا هستند: یک رشتهٔ متفاوت با نامِ کش، یا
            # شناسه‌ای که به یک ثابتِ رشته‌ایِ متفاوت می‌رسد. پارامتر/متغیرِ محلی
            # قابلِ حل نیست پس هشدار نمی‌گیرد — وگرنه ترمیمِ عمدیِ
            # `caches.open(name)` (خواندنِ کش‌های دیگر برای برگردانِ نسخه) به‌غلط
            # «نامِ ناهمخوان» شمرده می‌شد (همین مثبتِ کاذب در توسعه دیده شد).
            consts = dict(re.findall(
                r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\"([^\"\n]*)\"", sw_code))
            for raw_arg in _PWA_OPEN_RE.findall(sw_code):
                arg = raw_arg.strip()
                if arg == "CACHE" or arg.strip("\"'") == cache_name:
                    continue
                if re.fullmatch(r"[A-Za-z_$][\w$]*", arg):
                    if arg in consts and consts[arg] != cache_name:
                        probs.append(f"«caches.open({arg})» ثابتِ «{consts[arg]}» را باز می‌کند که "
                                     f"با نامِ کشِ اعلام‌شده («{cache_name}») نمی‌خواند")
                    continue          # پارامتر/متغیرِ محلی — قابلِ حلِ استاتیک نیست
                probs.append(f"«caches.open({arg})» با نامِ کشِ اعلام‌شده («{cache_name}») "
                             "نمی‌خواند — activate آن کش را پاک می‌کند")

        addall = _PWA_ADDALL_RE.search(sw_code)
        arrays = {nm: body for nm, body in _PWA_ARRAY_DECL_RE.findall(sw_code)}
        if not addall:
            probs.append("در sw.js هیچ آرایه‌ای با addAll پیش‌کش نمی‌شود (پوستهٔ آفلاین ساخته نمی‌شود)")
        elif addall.group(1) not in arrays:
            probs.append(f"addAll({addall.group(1)}) به آرایه‌ای اشاره می‌کند که تعریف نشده "
                         "— سرِ نصب ReferenceError می‌دهد و سرویس‌ورکر نصب نمی‌شود")
        else:
            body = _strip_block_comments(arrays[addall.group(1)])
            shell_list = _PWA_QUOTED_RE.findall(body)
            stats["shell"] = len(shell_list)
            if not shell_list:
                probs.append(f"آرایهٔ پوستهٔ کش ({addall.group(1)}) خالی است — آفلاین چیزی برای نمایش نمی‌مانَد")
            for p in shell_list:
                if p.startswith("/api/"):
                    probs.append(f"«{p}» در پوستهٔ کش پیش‌کش شده — دادهٔ زنده هرگز نباید کش شود")
                elif not p.startswith("/"):
                    probs.append(f"«{p}» در پوستهٔ کش مسیرِ مطلقِ همین‌مبدأ نیست")
                elif not is_served(p):
                    probs.append(f"«{p}» در پوستهٔ کش است ولی app.py سروش نمی‌کند "
                                 "— نصبِ سرویس‌ورکر نیمه‌کاره می‌مانَد")
                elif "." in os.path.basename(p) and not on_disk(p):
                    # `addAll` با یک URLِ ناموفق کلّاً رد می‌شود و `catch` خفه‌اش
                    # می‌کند: سرویس‌ورکر نصب می‌شود ولی **هیچ‌چیز** پیش‌کش نشده.
                    probs.append(f"«{p}» در پوستهٔ کش است ولی فایلش روی دیسک نیست — "
                                 "addAll رد می‌شود و کشِ آفلاین خالی می‌مانَد")

        masked = strip_js_literals(sw_code) if sw_code.strip() else ""
        fb = _js_listener_body(sw_code, masked, "fetch") if masked else None
        if fb is None and "fetch" in handlers:
            warns.append("بدنهٔ هندلرِ fetch خوانده نشد — بندهای کشِ داده/آفلاین سنجیده نشد")
        if fb:
            if re.search(r'startsWith\(\s*"/api/"', fb):
                stats["api_bypass"] = True
            else:
                probs.append("هندلرِ fetch مسیرهای «/api/» را مستثنا نمی‌کند — دادهٔ زنده کش می‌شود")
            # فالبکِ آفلاین: پشتِ یکی از catchها باید caches.match( باشد. عمداً
            # بدونِ regexِ تُو‌در‌تُو: هر «شرطی بودن» الگو باعثِ منفیِ کاذب می‌شود
            # (همین تله در توسعهٔ همین چک لو رفت — فاصلهٔ ثابتِ ۲۶۰ نویسه با
            # کامنت‌های فارسیِ وسطِ کد می‌شکست).
            if any("caches.match(" in fb[m.end():m.end() + 220]
                   for m in re.finditer(r"\bcatch\b", fb)):
                stats["offline"] = True
            else:
                probs.append("شاخهٔ شبکه‌ی fetch پشتوانهٔ کش ندارد (آفلاین صفحهٔ خطای مرورگر می‌آید)")
            if not _ok_guarded_puts(fb):
                probs.append("پاسخ بدونِ گاردِ «res.ok» کش می‌شود — یک ۴۰۴/۵۰۰ گذرا تا "
                             "ارتقای کش گیر می‌مانَد")
            im = re.search(r"if\s*\(([^)]*icon[^)]*)\)\s*\{", fb, re.I)
            if not im:
                probs.append("سرویس‌ورکر شاخهٔ کش‌اولِ آیکون ندارد (هر آیکون هر بار از شبکه)")
            else:
                blk = _js_block_at(fb, fb.index("{", im.start()))
                if blk is None:
                    warns.append("بلوکِ شاخهٔ آیکون خوانده نشد — ترتیبِ کش/شبکه سنجیده نشد")
                else:
                    mc, fc = blk.find("caches.match("), blk.find("fetch(")
                    if mc < 0 or (0 <= fc < mc):
                        probs.append("شاخهٔ آیکون کش‌اول نیست (fetch قبل از caches.match) — آفلاین آیکون ندارد")
                    else:
                        stats["cache_first_icons"] = True

    shell_set = set(shell_list)

    # ۳) مانیفست: آیکون‌ها و start_url باید واقعاً وجود داشته و سرو شوند
    man = {}
    if man_raw:
        try:
            man = json.loads(man_raw)
        except Exception as e:
            probs.append(f"manifest.webmanifest JSON نامعتبر است ({e})")
            man = {}
        if not isinstance(man, dict):
            probs.append("manifest.webmanifest باید یک شیءِ JSON باشد")
            man = {}
    if man:
        start = str(man.get("start_url") or "/")
        stats["promised"] += 1
        if not is_served(start):
            probs.append(f"start_urlِ «{start}» در app.py سرو نمی‌شود")
        icons = [str(i.get("src")) for i in (man.get("icons") or [])
                 if isinstance(i, dict) and i.get("src")]
        stats["icons"] = len(icons)
        if not icons:
            probs.append("مانیفست هیچ آیکونی اعلام نکرده — نصبِ اپ بدونِ آیکون می‌شود")
        for ic in icons:
            if not on_disk(ic):
                probs.append(f"آیکونِ «{ic}» در مانیفست اعلام شده ولی فایلش روی دیسک نیست")
            elif not is_served(ic):
                probs.append(f"آیکونِ «{ic}» سرو نمی‌شود — نصبِ اپ با آیکونِ شکسته")
            elif shell_set and ic not in shell_set:
                probs.append(f"آیکونِ «{ic}» در پوستهٔ کش پیش‌کش نشده — نصبِ آفلاینِ اولین‌بار آیکون ندارد")
        if shell_set and "/manifest.webmanifest" not in shell_set:
            probs.append("«/manifest.webmanifest» در پوستهٔ کش نیست — نصبِ آفلاینِ اولین‌بار ممکن نیست")
        if shell_set and not (man.get("start_url") or "/") in shell_set:
            probs.append(f"start_urlِ «{start or '/'}» در پوستهٔ کش نیست — آفلاین صفحهٔ فالبک پیدا نمی‌شود")

    # ۴) آیکون‌های خودِ صفحه (فاوآیکون/اپل‌تاچ): فایل، مسیر و پوششِ کش
    page_icons = []
    for tm in _PWA_LINK_TAG_RE.finditer(page_html):
        tag = tm.group(0)
        rel = _PWA_REL_RE.search(tag)
        if not rel or "icon" not in (rel.group(1) or "").lower():
            continue
        hm = _PWA_HREF_RE.search(tag)
        if not hm:
            continue
        href = hm.group(1)
        if href.startswith(("http:", "https:", "data:", "//")):
            continue
        page_icons.append(href)
        stats["promised"] += 1
        if not on_disk(href):
            probs.append(f"آیکونِ صفحه «{href}» روی دیسک نیست")
        elif not is_served(href):
            probs.append(f"آیکونِ صفحه «{href}» سرو نمی‌شود")
        elif shell_set and href not in shell_set:
            probs.append(f"آیکونِ صفحه «{href}» در پوستهٔ کش پیش‌کش نشده — آفلاین آیکون ندارد")

    # ۵) هم‌خوانیِ قاعدهٔ کش‌اولِ آیکون با نامِ آیکون‌های اعلام‌شده
    if sw and stats["cache_first_icons"] and shell_set:
        pm = _PWA_PATHNAME_TEST_RE.search(sw)
        if not pm:
            warns.append("قاعدهٔ مسیرِ آیکون در sw.js پیدا نشد — هم‌خوانیِ نام‌ها سنجیده نشد")
        else:
            try:
                rx = re.compile(re.sub(r"\\/", "/", pm.group(1)))
            except re.error:
                rx = None
            if rx is None:
                warns.append("قاعدهٔ مسیرِ آیکون در sw.js به regexِ پایتون ترجمه نشد")
            else:
                for ic in [str(i.get("src")) for i in (man.get("icons") or [])
                           if isinstance(i, dict) and i.get("src")] + page_icons:
                    if not rx.search(ic):
                        probs.append(f"آیکونِ «{ic}» با قاعدهٔ کش‌اولِ آیکون در sw.js نمی‌خواند "
                                     "(از شاخهٔ شبکه رد می‌شود)")

    # ۶) نسخه‌بندیِ خودکارِ کش + بنرِ «نسخهٔ تازه» با هماهنگیِ skipWaiting
    # چرا: نامِ کشِ ثابت یعنی ارتقای کش به یادِ آدم وابسته می‌مانَد؛ و بدونِ بنر،
    # کاربری که هفته‌ها از کش سرو می‌شود (به‌ویژه آفلاین) هیچ‌وقت نمی‌فهمد نسخهٔ
    # تازه آمده. سه خرابیِ بی‌صدا این‌جا گرفته می‌شود: (۱) نامِ کشِ دستی/ثابت;
    # (۲) جای‌گذار در sw.js هست ولی سرور جانشینش نمی‌کند → نامِ کش همان
    # `pipfound-__CACHE_REV__` می‌مانَد (ثابتِ ابدی: نه ارتقایی، نه خطایی)؛
    # (۳) `skipWaiting` بی‌قید یا بنرِ صفحهٔ بی‌پیام/بی‌رفرش — که یا کاربر را
    # وسطِ کار از کدِ قدیم به تازه پرت می‌کند یا دکمه‌اش بی‌اثر می‌مانَد.
    cache_literal = stats.get("cache") or ""
    _tm = re.search(r"__[A-Z][A-Z0-9_]*__", cache_literal)
    tok = _tm.group(0) if _tm else None
    if sw and cache_literal and not tok:
        probs.append(f"نامِ کش («{cache_literal}») دستی و ثابت است — با هر تغییرِ کد همان کش "
                     "پوشش داده می‌شود و ارتقای کش فقط به یادِ آدم وابسته می‌مانَد")
    if tok:
        decl = re.search(r"CACHE_REV_TOKEN\s*=\s*\"([^\"\n]+)\"", src)
        tok_srv = decl.group(1) if decl else None
        if not tok_srv:
            probs.append(f"جای‌گذارِ نامِ کش («{tok}») در app.py اعلام نشده (CACHE_REV_TOKEN) "
                         "— سرور نمی‌داند چه چیزی را جانشین کند")
        elif tok_srv != tok:
            probs.append(f"جای‌گذارِ app.py («{tok_srv}») با جای‌گذارِ sw.js («{tok}») نمی‌خواند "
                         "— جانشینی هرگز رخ نمی‌دهد و نامِ کش ثابت می‌مانَد")
        else:
            bm = re.search(r'u\.path\s*==\s*"/sw\.js"', src)
            window = src[bm.start():bm.start() + 900] if bm else ""
            if re.search(r"\.replace\(\s*(?:CACHE_REV_TOKEN|\"%s\")" % re.escape(tok), window):
                stats["cache_rev"] = True
            else:
                probs.append(f"پاسخِ /sw.js بدونِ جانشینیِ «{tok}» سرو می‌شود — نامِ کش برای "
                             "همیشه ثابت می‌مانَد (نه ارتقایی، نه بنری)")

    if sw:
        _swc = _blank_js_comments(sw)
        _swm = strip_js_literals(_swc)
        install_body = _js_listener_body(_swc, _swm, "install") or ""
        msg_body = _js_listener_body(_swc, _swm, "message") or ""
        if "skipWaiting(" in install_body:
            probs.append("سرویس‌ورکر سرِ نصب `skipWaiting` می‌زند — کاربرِ وسطِ کار بی‌خبر از "
                         "کدِ قدیم به تازه پرت می‌شود و بنرِ «نسخهٔ تازه» بی‌معنا می‌مانَد")
        elif "skipWaiting(" in _swc and not msg_body:
            probs.append("`skipWaiting` در سرویس‌ورکر هست ولی از مسیرِ پیامِ کاربر نیست "
                         "— ارتقا زیرِ پای کاربر رخ می‌دهد")
        # عمداً «ساخته شدنِ عنصر» سنجیده می‌شود، نه وجودِ نام در متن: ارجاعِ JS
        # (`getElementById("pfSwBanner")`) هم نام را دارد و اگر پیدا کردنِ عنصر
        # پاک شود، بنر هرگز دیده نمی‌شود ولی چک سبزِ دروغ می‌ماند.
        banner_present = bool(re.search(
            r"(?:\bid\s*=\s*[\"']pfSwBanner[\"']"
            r"|setAttribute\(\s*[\"']id[\"']\s*,\s*[\"']pfSwBanner[\"'])",
            page_html))
        page_asks = bool(re.search(r"postMessage\(\s*\{[^}]*SKIP_WAITING", page_html))
        if not banner_present:
            probs.append("صفحه عنصرِ بنرِ «pfSwBanner» را نمی‌سازد — کاربر (به‌ویژه آفلاین) "
                         "هیچ راهی ندارد بفهمد نسخهٔ تازه آمده")
        else:
            stats["update_banner"] = True
        # بنر یعنی صفحه وعدهٔ «به‌روزرسانی با تأییدِ کاربر» داده؛ پس کلِ زنجیره
        # (پیام → skipWaiting → controllerchange → رفرش) باید کامل باشد، وگرنه
        # دکمهٔ بنر بی‌اثر است یا برعکس، صفحه بی‌اجازه از نو بالا می‌آید.
        # ── ۷) ارتقای ایمن: پاک‌کردنِ کشِ قبلی مشروط به تأییدِ درستیِ پوستهٔ تازه ──
        # چرا: نصبِ نیمه‌کاره (اینترنتِ قطع، یک ۴۰۴، `addAll`ِ ردشده) با پاک‌کردنِ
        # بی‌قید، کشِ سالمِ قبلی را نابود می‌کند و آفلاینِ کاربر **برنمی‌گردد**.
        # سه شرط: (الف) تابعی هست که با SHELL + caches.open درستیِ پوسته را می‌سنجد؛
        # (ب) activate آن را صدا می‌زند و هر `caches.delete(` داخلِ گاردی است که به
        # همان نتیجه گره دارد؛ (ج) فالبکِ کش در fetch اول کشِ فعال را می‌بیند تا در
        # حالتِ «برگردانِ نسخه» پوستهٔ سالمِ قبلی خوانده شود.
        safe_fails = []
        act_body = _js_listener_body(_swc, _swm, "activate") or ""
        fns = _js_fn_bodies(_swc)
        verifiers = sorted(n for n, b in fns.items()
                           if "SHELL" in b and "caches.open(" in b)
        if not verifiers:
            safe_fails.append("سرویس‌ورکر تابعی برای سنجشِ درستیِ پوستهٔ کش ندارد "
                              "(SHELL + caches.open) — ارتقا بدونِ تأیید انجام می‌شود")
        else:
            called = [n for n in verifiers if re.search(r"\b%s\s*\(" % re.escape(n), act_body)]
            if not called:
                safe_fails.append("activate درستیِ پوستهٔ تازه را نمی‌سنجد — کشِ قبلی پیش از "
                                  "تأییدِ سالم بودنِ نسخهٔ تازه پاک می‌شود")
            else:
                aliases = set(re.findall(
                    r"([A-Za-z_$][\w$]*)\s*=\s*(?:await\s+)?(?:%s)\s*\("
                    % "|".join(map(re.escape, verifiers)), act_body))
                trusted = set(called) | aliases
                guards = _js_if_blocks(act_body)
                for dm in re.finditer(r"caches\.delete\s*\(", act_body):
                    inside = [c for c, _b, a, z in guards if a < dm.start() < z]
                    if not any(any(re.search(r"\b%s\b" % re.escape(t), c) for t in trusted)
                               for c in inside):
                        safe_fails.append("پاک‌کردنِ کشِ قبلی در activate به تأییدِ پوستهٔ تازه گره "
                                          "نخورده — نصبِ نیمه‌کاره آفلاینِ کاربر را از بین می‌برد")
                        break
        pref_re = re.compile(r"caches\.open\([^)]*\)[^;]{0,240}\.match\(")
        called_helpers = set(re.findall(r"\b([A-Za-z_$][\w$]*)\s*\(", fb or ""))
        pref_ok = bool(pref_re.search(fb or "")) or any(
            pref_re.search(fns.get(n, "")) for n in called_helpers if n in fns)
        if fb and not pref_ok:
            safe_fails.append("فالبکِ کش در fetch کشِ فعالِ همین نسخه را در اولویت نمی‌گذارد "
                              "— در حالتِ برگردانِ نسخه پوستهٔ سالمِ قبلی خوانده نمی‌شود")
        probs.extend(safe_fails)
        stats["safe_upgrade"] = (not safe_fails) and bool(verifiers)

        if banner_present or page_asks:
            if not page_asks:
                probs.append("بنرِ «نسخهٔ تازه» هست ولی صفحه پیامِ SKIP_WAITING نمی‌فرستد "
                             "— دکمهٔ «به‌روزرسانی» هیچ‌وقت نسخه را جانشین نمی‌کند")
            if "SKIP_WAITING" not in msg_body:
                probs.append("پیامِ SKIP_WAITING صفحه به هندلرِ message سرویس‌ورکر نمی‌رسد "
                             "— دکمهٔ «به‌روزرسانی» بی‌اثر می‌مانَد")
            cb = ""
            for ptext in pages.values():
                _pc = _blank_js_comments(ptext)
                cb = _js_listener_body(_pc, strip_js_literals(_pc), "controllerchange") or ""
                if cb:
                    break
            if not cb:
                probs.append("صفحه `controllerchange` را نمی‌شنود — بعد از جانشینیِ نسخهٔ تازه "
                             "کاربر تا رفرشِ دستی روی کدِ کهنه می‌مانَد")
            else:
                if "location.reload(" not in cb:
                    probs.append("پس از جانشینیِ نسخهٔ تازه صفحه خودش را تازه نمی‌کند "
                                 "— کاربر روی کدِ کهنه می‌مانَد")
                gate = [i for i in set(re.findall(r"[A-Za-z_$][\w$]*", cb))
                        if re.search(r"(?:if\s*\(\s*!|&&\s*!)\s*%s\b" % re.escape(i), cb)]
                if not gate:
                    probs.append("جانشینیِ نسخهٔ تازه هیچ قیدِ «تأییدِ کاربر» ندارد — خودِ "
                                 "نصبِ اول هم صفحه را وسطِ کار از نو بالا می‌آورد")
                elif not any(re.search(r"\b%s\s*=\s*true" % re.escape(i), page_html)
                             for i in gate):
                    probs.append("قیدِ جانشینی به نشانِ «کاربر خواسته» گره نخورده "
                                 "— رفرشِ بی‌قیدِ صفحه احتمالاً نصبِ اول را هم برمی‌گرداند")
            # ── ۸) «بعداً» تا پایانِ همان بازدید یادش می‌مانَد، ولی پیامِ «برگردانِ
            # نسخه» هر بار دیده می‌شود (خواسته‌ی کاربر). یادِ نداشتن = بنرِ
            # آزاردهنده در هر بارگذاری؛ یادِ ابدی (`localStorage`) = بنرِ خفه‌شده
            # تا ابد؛ و گره‌خوردنِ پیامِ برگردان = خبرِ «نسخهٔ تازه ناقص بود»
            # بی‌صدا. هر سه در `_banner_memory_problems` سنجیده می‌شود.
            later_fails = _banner_memory_problems(page_html)
            probs.extend(later_fails)
            stats["banner_memory"] = not later_fails
            # ── ۹) نسخهٔ تازه‌ای که **خودِ همین بارگذاری** راه می‌اندازد هم باید
            # بنر بدهد (S10): فقط منتظرِ رویدادِ `updatefound` ماندن کافی نیست،
            # چون ممکن است نصب پیش از وصل‌شدنِ شنونده تمام شده باشد.
            watch_fails = _update_watch_problems(page_html)
            probs.extend(watch_fails)
            stats["update_watch"] = not watch_fails
    return probs, warns, stats


# ────────── چکِ استاتیکِ انتقالِ دادهٔ کاربر (برون‌بری/درون‌بریِ ژورنال/آلارم/تنظیمات) ──────────
# چرا این قاعده لازم است: بدونِ نگهبان، سه خرابیِ بی‌صدا فقط سرِ «دستگاهِ تازه»
# معلوم می‌شوند: (۱) برون‌بری یک بخش را از قلم بیندازد (مثلاً تنظیمات) و کاربر
# فکر کند پشتیبانِ کامل دارد؛ (۲) درون‌بری پیش از اعتبارسنجی دست به فایل‌ها
# بزند و بستهٔ خراب نیمه‌کاره اعمال شود؛ (۳) بازنویسیِ دفتر غیرِاتمیک باشد و
# خطای وسطِ کار دفترِ کاربر را بریده بگذارد. پنجرهٔ دکمه‌های رابط هم بدونِ قاعده
# بی‌صدا می‌میرد. همهٔ این‌ها استاتیک و بدونِ اجرای کد سنجیده می‌شوند.
_BK_WRITE_RE = re.compile(r"(?:\bsave_settings|_journal_write|_save_alarms|os\.replace)\s*\(")


_PY_TRIPLE_RE = re.compile(r'"""(?:.|\n)*?"""|\'\'\'(?:.|\n)*?\'\'\'')


def _code_only(src):
    """رشته‌های سه‌گانه (متنِ توضیحی) و کامنت‌ها را از کد جدا می‌کند.

    چرا لازم شد: قاعدهٔ «پشتیبانِ خودکار» با تطبیقِ سادهٔ زیررشته نوشته شده بود و
    متنی که در **توضیحات** آمده بود را هم می‌دید — یعنی پاک‌کردنِ یک فراخوانیِ
    واقعی، بی‌صدا سبز می‌مانْد چون همان نام در docstring ذکر شده بود. (همین
    تله یک بار در جهش‌آزماییِ مسیرهای API هم لو رفته بود.) حالا قاعده فقط کدِ
    واقعی را می‌بیند.
    """
    s = _PY_TRIPLE_RE.sub(
        lambda m: "\n" * m.group(0).count("\n") or " ", src or "")
    lines = []
    for ln in s.splitlines():
        lines.append(ln.split("#", 1)[0])
    return "\n".join(lines)


def _py_block(src, head_re):
    """بلوکِ پایتونی از خطِ منطبق با head_re تا اولین خطِ غیرخالیِ کم‌تورفتگی."""
    lines = src.splitlines()
    for i, ln in enumerate(lines):
        if head_re.search(ln):
            indent = len(ln) - len(ln.lstrip())
            out = [ln]
            for ln2 in lines[i + 1:]:
                if ln2.strip() and (len(ln2) - len(ln2.lstrip())) <= indent:
                    break
                out.append(ln2)
            return "\n".join(out)
    return None


def backup_problems(root, pages=None):
    """قراردادِ انتقالِ داده: برون‌بریِ کامل، اعتبارسنجیِ پیش از نوشتن، نوشتنِ اتمیک."""
    probs = []
    stats = {"endpoints": False, "validate_first": False, "atomic": False,
             "controls": False}
    src = read_text(os.path.join(root, "app.py")) or ""
    bsrc = read_text(os.path.join(root, "backup.py")) or ""
    pages = pages or page_sources(root)
    html = "\n".join(pages.values()) if pages else ""

    if not bsrc.strip():
        probs.append("ماژولِ backup.py خوانده نشد — برون‌بری/درون‌بری بی‌هسته می‌مانَد")
    else:
        if not re.search(r"^KIND\s*=\s*[\"']pipfound-backup[\"']", bsrc, re.M):
            probs.append("نشانِ بستهٔ پشتیبان (KIND) در backup.py تعریف نشده")
        if not re.search(r"^VERSION\s*=\s*\d+\s*$", bsrc, re.M):
            probs.append("نسخهٔ بستهٔ پشتیبان (VERSION) در backup.py تعریف نشده")
        blk = _py_block(bsrc, re.compile(r"^def build\("))
        if blk is None:
            probs.append("backup.py · تابعِ build( پیدا نشد")
        else:
            for key in ("journal", "alarms", "settings"):
                if ('"%s"' % key) not in blk:
                    probs.append(f"برون‌بری بخشِ «{key}» را در بسته نمی‌گذارد — "
                                 "پشتیبانِ ناقص بی‌صدا است")
        vblk = _py_block(bsrc, re.compile(r"^def validate\("))
        if vblk is None:
            probs.append("backup.py · تابعِ validate( پیدا نشد — درون‌بری بی‌اعتبارسنجی است")
        else:
            for need in ("KIND", "VERSION"):
                if need not in vblk:
                    probs.append(f"اعتبارسنجی کلیدِ «{need}» را نمی‌بیند — "
                                 "بستهٔ ناسازگار بی‌صدا اعمال می‌شود")

    # دقت: چک با رشتهٔ خالیِ مسیر کافی نیست — همان مسیر در JS هم به‌شکلِ
    # `fetch("/api/export")` می‌آید، پس برداشتنِ روتِ پایتونی می‌توانست «سبزِ دروغ»
    # بدهد (همین تله در جهش‌آزماییِ همین قاعده لو رفت). پس روت را از خودِ شرطِ پایتون
    # می‌شناسیم و صدا‌زدن از JS را جدا می‌سنجیم.
    has_export = 'u.path == "/api/export"' in src
    has_import = 'u.path == "/api/import"' in src
    stats["endpoints"] = has_export and has_import
    if not has_export:
        probs.append("مسیرِ /api/export (برون‌بری) در app.py نیست")
    if not has_import:
        probs.append("مسیرِ /api/import (درون‌بری) در app.py نیست")

    hi = _py_block(src, re.compile(r"^\s*def _handle_import\("))
    if hi is None:
        probs.append("هندلرِ _handle_import در app.py نیست — درون‌بری سرو نمی‌شود")
    else:
        vm = re.search(r"\bBK\.validate\s*\(", hi)
        wm = _BK_WRITE_RE.search(hi)
        if vm is None:
            probs.append("درون‌بری پیش از نوشتن اعتبارسنجی نمی‌کند (BK.validate نیست)")
        elif wm is not None and wm.start() < vm.start():
            probs.append("درون‌بری اول می‌نویسد و بعد اعتبارسنجی می‌کند — بستهٔ خراب "
                         "می‌تواند نیمه‌کاره اعمال شود")
        stats["validate_first"] = bool(vm) and (wm is None or vm.start() < wm.start())

    jw = _py_block(src, re.compile(r"^\s*def _journal_write\("))
    if jw is None:
        probs.append("نوشتارِ اتمیکِ دفتر (_journal_write) در app.py نیست")
    elif "os.replace(" not in jw:
        probs.append("بازنویسیِ دفترِ ژورنال اتمیک نیست (os.replace غایب است) — "
                     "خطای وسطِ درون‌بری دفتر را نیمه‌کاره می‌گذارد")
    else:
        stats["atomic"] = True

    ctrl_ok = True
    for el, what in (("expBtn", "برون‌بری"), ("impBtn", "درون‌بری"),
                     ("impFile", "فایلِ درون‌بری"), ("bkMsg", "پیامِ پشتیبان")):
        if ('id="%s"' % el) not in html:
            probs.append(f"کنترلِ «{what}» (#{el}) در صفحه نیست")
            ctrl_ok = False
        elif ('getElementById("%s")' % el) not in html:
            probs.append(f"کنترلِ «{what}» (#{el}) به JS وصل نشده — دکمه بی‌اثر است")
            ctrl_ok = False
    for spec, what in (('fetch("/api/export"', "برون‌بری"),
                       ('fetch("/api/import"', "درون‌بری")):
        if spec not in html:
            probs.append(f"JS مسیرِ {what} را صدا نمی‌زند — دکمه‌اش بی‌اثر است")
            ctrl_ok = False
    stats["controls"] = ctrl_ok
    return probs, stats


# ────────── چکِ استاتیکِ پشتیبانِ خودکارِ زمان‌بندی‌شده (اسنپ‌شات + نگه‌داشت) ──────────
# چرا این قاعده لازم است: پشتیبانِ خودکار *بی‌صدا* خراب می‌شود و کاربر تازه وقتی
# می‌فهمد که پشتیبان لازمش شده. چهار خرابیِ کشنده: (۱) هرس فایلی را ببرد که
# پشتیبانِ اپ نیست (دفتر/یادداشت/هر چیزی در همان پوشه) — فاجعه‌ی واقعی؛
# (۲) نوشتن غیرِاتمیک باشد و خطای وسطِ راه یک «پشتیبانِ خراب» بگذارد که کاربر
# به آن تکیه کند (بدتر از بی‌پشتیبانی)؛ (۳) زمان‌بند روشن ولی مرده باشد یا
# کلیدِ روشن/خاموش را نبیند؛ (۴) مسیرِ خواندنِ نسخه با نامِ سنجیده‌نشده اجازهٔ
# خواندنِ فایلِ دلخواهِ سیستم بدهد (`?file=../../…`). همه استاتیک سنجیده می‌شوند.
_AB_DELETE_RE = re.compile(r"os\.remove\s*\(")


def autobackup_problems(root, pages=None):
    """قراردادِ پشتیبانِ خودکار: نگه‌داشتِ امن، نوشتنِ اتمیک، زمان‌بندِ زنده، مسیرِ امن."""
    probs = []
    stats = {"module": False, "safe_prune": False, "atomic": False,
             "scheduler": False, "controls": False}
    # کدِ بدونِ توضیحات: قاعده باید *کد* را بسنجد، نه نامی که در docstring آمده
    src = _code_only(read_text(os.path.join(root, "app.py")) or "")
    absrc = _code_only(read_text(os.path.join(root, "autobackup.py")) or "")
    pages = pages or page_sources(root)
    html = "\n".join(pages.values()) if pages else ""

    if not absrc.strip():
        probs.append("ماژولِ autobackup.py خوانده نشد — پشتیبانِ خودکارِ زمان‌بندی‌شده می‌مانَد")
    else:
        needed = (r"^DEFAULTS\s*=", r"^def is_backup_name\(", r"^def plan_prune\(",
                  r"^def due\(", r"^def prune\(", r"^def write_snapshot\(",
                  r"^def snapshot\(", r"^def list_backups\(",
                  r"^def validate_settings\(", r"^def effective_last_run\(")
        miss = [p for p in needed if not re.search(p, absrc, re.M)]
        if miss:
            probs.append("autobackup.py ناقص است — این‌ها پیدا نشد: "
                         + "، ".join(m.lstrip("^").replace("\\(", "(") for m in miss))
        else:
            stats["module"] = True

        pblk = _py_block(absrc, re.compile(r"^def plan_prune\(")) or ""
        rblk = _py_block(absrc, re.compile(r"^def prune\(")) or ""
        if not _AB_DELETE_RE.search(rblk):
            probs.append("prune هیچ نسخه‌ای را حذف نمی‌کند — نگه‌داشتِ نسخه‌ها بی‌اثر "
                         "می‌مانَد (پوشه بی‌نهایت رشد می‌کند)")
        elif "is_backup_name(" not in pblk:
            probs.append("plan_prune نامِ فایل را فیلتر نمی‌کند — هرس می‌تواند "
                         "فایلِ غیرِپشتیبان را نامزدِ حذف کند")
        elif "is_backup_name(" not in rblk:
            probs.append("prune پیش از os.remove نام را دوباره نمی‌سنجد — فایلِ "
                         "ناشناخته در پوشهٔ پشتیبان قربانی می‌شود")
        else:
            stats["safe_prune"] = True

        hblk = _py_block(absrc, re.compile(r"^def _write_json\(")) or ""
        wblk = _py_block(absrc, re.compile(r"^def write_snapshot\(")) or ""
        if "os.replace(" not in hblk:
            probs.append("نوشتنِ فایل‌های پشتیبان اتمیک نیست (_write_json بدونِ os.replace)")
        elif "_write_json(" not in wblk:
            probs.append("write_snapshot از مسیرِ اتمیکِ _write_json استفاده نمی‌کند")
        else:
            stats["atomic"] = True

    w = _py_block(src, re.compile(r"^\s*def _autobackup_worker\("))
    if w is None:
        probs.append("کارگرِ پشتیبانِ خودکار (_autobackup_worker) در app.py نیست")
    else:
        if "AB.due(" not in w:
            probs.append("زمان‌بند نوبت را نمی‌سنجد (AB.due نیست) — یا هرگز پشتیبان "
                         "نمی‌گیرد یا پشتِ‌سرِهم می‌گیرد")
        if "enabled" not in w:
            probs.append("زمان‌بند کلیدِ روشن/خاموش را نمی‌بیند — خاموش‌کردن بی‌اثر می‌مانَد")
        if "_autobackup_run_now(" not in w:
            probs.append("زمان‌بند از مسیرِ مشترکِ اسنپ‌شات استفاده نمی‌کند")
        else:
            stats["scheduler"] = True
    rn = _py_block(src, re.compile(r"^\s*def _autobackup_run_now\(")) or ""
    if "_backup_bundle(" not in rn:
        probs.append("پشتیبانِ خودکار از بستهٔ خودِ «برون‌بری» نمی‌سازد (_backup_bundle "
                     "نیست) — فایلِ تولیدی قابلِ‌درون‌بری نیست")
    if "AB.snapshot(" not in rn:
        probs.append("پشتیبانِ خودکار اسنپ‌شات نمی‌گیرد (AB.snapshot نیست)")
    # دقت: تعریفِ تابع خودش هم شاملِ «start_autobackup_worker()» است، پس شرط
    # باید یک *فراخوانیِ سرِ خط* باشد وگرنه برداشتنِ راه‌اندازی بی‌صدا سبز می‌مانْد.
    if not re.search(r"^\s*start_autobackup_worker\(\)\s*$", src, re.M):
        probs.append("کارگرِ پشتیبانِ خودکار سرِ بوت راه‌اندازی نمی‌شود")
    if src.count('u.path == "/api/autobackup"') < 2:
        probs.append("مسیرِ /api/autobackup باید هم GET (وضعیت/نسخه) و هم "
                     "POST (تنظیمات) داشته باشد")

    bn = _py_block(src, re.compile(r"^\s*def _backup_by_name\(")) or ""
    if "is_backup_name(" not in bn:
        probs.append("خواندنِ نسخه با ?file نام را نمی‌سنجد — مسیرِ بیرون‌زدن از "
                     "پوشهٔ پشتیبان باز است")
    elif "backup_dir(" not in bn:
        probs.append("خواندنِ نسخه از پوشهٔ رسمیِ پشتیبان نمی‌آید")

    ctrl_ok = True
    for el, what in (("abToggle", "روشن/خاموشِ پشتیبانِ خودکار"),
                     ("abEvery", "فاصلهٔ ساعت"),
                     ("abKeep", "تعدادِ نسخه‌های نگه‌داشته"),
                     ("abSave", "ذخیرهٔ تنظیماتِ زمان‌بندی"),
                     ("abNow", "اجرای فوری"),
                     ("abMsg", "پیامِ پشتیبانِ خودکار"),
                     ("abStat", "خطِ وضعیتِ پشتیبانِ خودکار"),
                     ("abList", "فهرستِ نسخه‌های نگه‌داشته")):
        if ('id="%s"' % el) not in html:
            probs.append(f"کنترلِ «{what}» (#{el}) در صفحه نیست")
            ctrl_ok = False
        elif ('getElementById("%s")' % el) not in html:
            probs.append(f"کنترلِ «{what}» (#{el}) به JS وصل نشده — بی‌اثر است")
            ctrl_ok = False
    if 'fetch("/api/autobackup"' not in html:
        probs.append("JS وضعیتِ پشتیبانِ خودکار را از سرور نمی‌خوانَد — پنل مرده است")
        ctrl_ok = False
    stats["controls"] = ctrl_ok
    return probs, stats


# ────────── چکِ استاتیکِ «تست‌ها نوتیفِ دسکتاپِ کاربر را نمی‌زنند» ──────────
# چرا این قاعده لازم است: کارگرِ آلارمِ فاندمنتال (و آلارمِ قیمت) **سرِ بوت** و در
# همان اولین دورِ خود نوتیفِ *واقعیِ مک* می‌فرستد. هر تست/هارنسی که اپ را با HOMEِ
# تازه بالا می‌آورد یعنی «فایلِ dedupe وجود ندارد» ⇒ نوتیف می‌رود، و هر execvِ
# ری‌استارت هم دوباره. نتیجه: تست‌ها بی‌آنکه کسی بفهمد روی دسکتاپِ کاربر
# پشتِ‌سرِهم نوتیف می‌فرستادند — همان شکایتِ واقعیِ کاربر («پشتِ‌سرِهم نوتیف
# می‌دهد»). این قاعده دو چیز را قفل می‌کند: (۱) خودِ `_notify_mac` **پیش از**
# هر `osascript` دروازهٔ `PIPFOUND_NOTIFY` را می‌بیند (و خودِ دروازه آن کلید را
# می‌خواند)؛ (۲) هیچ فایلِ تست/هارنس/گامِ CI اپ را بدونِ آن کلید پرتاب نمی‌کند.
_LAUNCH_VERB_RE = re.compile(
    r"subprocess\.(?:Popen|run|call|check_output)\s*\(|"
    r"\b(?:Popen|spawn|spawnSync|execFile)\s*\(")
_MUTE_KEY = "PIPFOUND_NOTIFY"
# شکلِ موردِانتظار: کلید **به‌صورتِ صریح روی حالتِ خاموش** ست شده باشد
# (`env["PIPFOUND_NOTIFY"] = "0"` / `PIPFOUND_NOTIFY="0"` / `PIPFOUND_NOTIFY: "0"`).
# بودِنِ کلید با مقدارِ روشن ("1") کیفت نمی‌کند — همان روی دسکتاپ نوتیف می‌دهد.
_MUTE_OK_RE = re.compile(r"PIPFOUND_NOTIFY[\s\"'\)\]]{0,4}[:=][\s\"']{0,3}(?:0|off|false|no)\b",
                         re.IGNORECASE)
_MUTE_OFF_SET_RE = re.compile(r"_NOTIFY_OFF_VALUES\s*=\s*\{[^}]*[\"']0[\"']")
_NOTIFY_TEST_SUFFIX = "_test.py"
_NOTIFY_HARNESS_SUFFIX = ".cjs"
_NOTIFY_CI_SUFFIXES = (".yml", ".yaml")


# کامنتِ نود/برگهٔ CI باید از *کدِ* سنجیده‌شده کنار برود، وگرنه یک یادداشتِ
# ساده که نامِ کلید را بگوید، قاعده را سبزِ دروغ می‌کند (همین تله در جهش‌آزماییِ
# همین قاعده لو رفت). در نود `//`ِ داخلِ `http://` کامنت نیست، پس نگاهِ عقب لازم است.
_CJS_COMMENT_RE = re.compile(r"/\*.*?\*/|(?<!:)//[^\n]*", re.S)
_YAML_COMMENT_RE = re.compile(r"#[^\n]*")


def _probe_of(name, text):
    """متنِ *کد* برای سنجشِ کلیدِ خفه‌کردن (بدونِ کامنت/docstring)."""
    if name.endswith(_NOTIFY_TEST_SUFFIX):
        return _code_only(text)
    if name.endswith(_NOTIFY_HARNESS_SUFFIX):
        return _CJS_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n") or " ", text or "")
    return _YAML_COMMENT_RE.sub("", text or "")


def _app_launch_lines(text, name):
    """شمارهٔ خط‌های «پرتابِ اپ» در یک فایلِ تست/هارنس/CI.

    معیار در کدِ پایتون/نود: خطی که به `app.py` اشاره می‌کند و در فاصلهٔ ±۳ خط
    یک فعلِ پرتاب (`subprocess.Popen(`/`spawn(`/…) دارد — چون خودِ فراخوانی و
    آرگومان‌هایش در چند خط می‌آیند و `app.py` روی خطِ دیگری می‌نشیند.
    برگه‌های CI (`.yml`) هر خطی که `app.py` داشته باشد پرتاب شمرده می‌شود، چون
    آن‌جا فقط دستورِ اجرا نوشته می‌شود (نه خواندنِ فایل).
    """
    lines = (text or "").splitlines()
    if name.endswith(_NOTIFY_CI_SUFFIXES):
        return [i + 1 for i, ln in enumerate(lines) if "app.py" in ln]
    # نامِ متغیرهایی که همین فایل به `app.py` گره زده (`APP = os.path.join(…, "app.py")`)
    # تا پرتابی که با آن متغیر انجام می‌شود هم دیده شود (نه فقط اشارهٔ مستقیم).
    aliases = set()
    for ln in lines:
        if "app.py" in ln:
            m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", ln)
            if m:
                aliases.add(m.group(1))
    hits = []
    for i, ln in enumerate(lines):
        if "app.py" in ln:
            if _LAUNCH_VERB_RE.search("\n".join(lines[max(0, i - 3):i + 4])):
                hits.append(i + 1)
            continue
        if _LAUNCH_VERB_RE.search(ln) and any(
                re.search(r"\b%s\b" % re.escape(a), ln) for a in aliases):
            hits.append(i + 1)
    return hits


def notify_problems(root, pages=None):
    """قراردادِ «خفه‌بودنِ نوتیفیکیشن در تست‌ها»: دروازهٔ اپ + خفه‌بودنِ هر پرتاب."""
    probs = []
    stats = {"gate": False, "sites": 0, "muted": 0,
             "ci_sites": 0, "ci_muted": 0, "files": []}
    # کدِ بدونِ توضیحات/docstring: قاعده باید *کد* را بسنجد، نه نامی که در متنِ
    # توضیحی آمده (همین تله یک بار در جهش‌آزماییِ پشتیبانِ خودکار لو رفته بود).
    code = _code_only(read_text(os.path.join(root, "app.py")) or "")

    fblk = _py_block(code, re.compile(r"^def _notify_mac\("))
    hblk = _py_block(code, re.compile(r"^def _notify_muted\("))
    gate_call = re.search(r"\b_notify_muted\s*\(\s*\)", fblk or "")
    os_at = (fblk or "").find("osascript")
    if fblk is None:
        probs.append("app.py · تابعِ _notify_mac پیدا نشد — نوتیفیکیشن بی‌دروازه می‌مانَد")
    elif os_at == -1:
        probs.append("app.py · _notify_mac دیگر osascript را صدا نمی‌زند «؟»")
    elif gate_call is None:
        probs.append("app.py · _notify_mac دروازهٔ _notify_muted() را صدا نمی‌زند — "
                     "هر تستی که اپ را بالا بیاورد روی دسکتاپِ کاربر نوتیف می‌فرستد")
    elif gate_call.start() > os_at:
        probs.append("app.py · دروازهٔ خفه‌کردن **بعد از** osascript سنجیده می‌شود — "
                     "نوتیف همان‌جا رفته است")
    if hblk is None:
        probs.append("app.py · تابعِ _notify_muted پیدا نشد — دروازهٔ خفه‌کردن بی‌هسته است")
    elif _MUTE_KEY not in hblk:
        probs.append("app.py · _notify_muted کلیدِ %s را نمی‌خواند — دروازه همیشه باز است"
                     % _MUTE_KEY)
    elif "environ" not in hblk and "getenv" not in hblk:
        probs.append("app.py · _notify_muted کلیدِ %s را از محیط نمی‌خواند" % _MUTE_KEY)
    elif "return" not in hblk:
        probs.append("app.py · _notify_muted هیچ مقداری برنمی‌گرداند (return ندارد)")
    elif _MUTE_OFF_SET_RE.search(code) is None:
        probs.append("app.py · فهرستِ مقادیرِ خاموش (_NOTIFY_OFF_VALUES) «۰» را ندارد — "
                     "PIPFOUND_NOTIFY=0 دیگر خفه نمی‌کند")
    else:
        stats["gate"] = (fblk is not None and os_at != -1 and gate_call is not None
                         and gate_call.start() <= os_at)

    # هر فایلِ تست/هارنسی که اپ را پرتاب می‌کند باید کلیدِ خفه‌کردن را داشته باشد.
    try:
        names = sorted(os.listdir(root))
    except OSError:
        names = []
    for name in names:
        if not (name.endswith(_NOTIFY_TEST_SUFFIX) or name.endswith(_NOTIFY_HARNESS_SUFFIX)):
            continue
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        text = read_text(path) or ""
        hits = _app_launch_lines(text, name)
        if not hits:
            continue
        stats["sites"] += 1
        stats["files"].append(name)
        # در پایتون فقط کدِ واقعی سنجیده می‌شود تا کامنتِ حاویِ نام کافی نباشد.
        probe = _probe_of(name, text)
        if _MUTE_OK_RE.search(probe):
            stats["muted"] += 1
        else:
            probs.append("%s اپ را پرتاب می‌کند (خطِ %d) بی‌آن‌که %s=0 (روی حالتِ خاموش) "
                         "بگذارد — همین تست روی دسکتاپِ کاربر نوتیف می‌فرستد"
                         % (name, hits[0], _MUTE_KEY))

    # گام‌های CI هم اپ را بالا می‌آورند؛ همان قرارداد آن‌جا هم لازم است.
    wdir = os.path.join(root, ".github", "workflows")
    try:
        wnames = sorted(os.listdir(wdir))
    except OSError:
        wnames = []
    for name in wnames:
        if not name.endswith(_NOTIFY_CI_SUFFIXES):
            continue
        path = os.path.join(wdir, name)
        if not os.path.isfile(path):
            continue
        text = read_text(path) or ""
        hits = _app_launch_lines(text, name)
        if not hits:
            continue
        stats["ci_sites"] += 1
        stats["files"].append(".github/workflows/" + name)
        if _MUTE_OK_RE.search(_probe_of(name, text)):
            stats["ci_muted"] += 1
        else:
            probs.append("گامِ CI «.github/workflows/%s» اپ را پرتاب می‌کند (خطِ %d) "
                         "بی‌آن‌که %s=0 بخفه‌اش کند"
                         % (name, hits[0], _MUTE_KEY))
    return probs, stats


# ═══ قاعدهٔ «آرشیو: نتیجهٔ قطعی، نه گزارهٔ شرطی» ═══
# تقاضای کاربر: آرشیو باید **نتیجه‌ی اعلام‌شده** را مطلق بگوید (عددِ Actual +
# صعودی/نزولی)، نه «اگر بالاتر شد → …». این قاعده زنجیره‌ی سه‌گانه را قفل می‌کند:
# گیرنده‌ی Actual (macro_context) → تزریقِ حکم (fundamental) → رندرِ مطلق (app.py).
_TE_ACTUAL_SPAN = "<span id='actual'>"   # الگوی پارسر — با «in» سنجیده می‌شود، نه regex
_ACTUALS_KEY_RE = re.compile(r"def get_actuals\s*\(")
_VERDICT_CALL_RE = re.compile(r"=\s*_attach_verdicts\s*\(")   # جایِ صدا زدن، نه def
_VERDICT_FN_RE = re.compile(r"def _verdict\s*\(")
_ARC_VERDICT_RE = re.compile(r"v\.found")
_ARC_OUTCOME_RE = re.compile(r"v\.outcome===\"(صعودی|نزولی)\"")
_ARC_ACTUAL_NUM_RE = re.compile(r'arc-num">\$\{v\.actual\}')
_ARC_ABSENT_RE = re.compile(r"منبعِ پاسخ نداد")
_ARCHIVE_NOTE_RE = re.compile(r"نتیجه")
# خواستهٔ کاربر: «توو آرشیو اقتصادی فقط نتیجه بیاد به‌علاوهٔ تأثیرش، نه گزارهٔ شرطی».
# فیدِ خبرهای پیش‌رو عمداً دو سناریوی بدبینانه/خوش‌بینانه دارد؛ این دو regex فقط
# داخلِ *منطقهٔ هندلرِ آرشیو* سنجیده می‌شوند تا آن دو با هم قاطی نشوند.
_ARC_COND_RE = re.compile(r"a\.beat|a\.miss")
_ARC_IMPACT_RE = re.compile(r'arc-i">تأثیر')
# ردیفِ خبرِ بی‌عدد باید صادق باشد، نه خالی (متنِ رندر، نه کامنتِ همان خط).
_ARC_PERROW_RE = re.compile(r"◇ این خبر عددِ اعلام‌شده ندارد")
_ARC_EFFECT_FN_RE = re.compile(r"def _realized_effect\s*\(")
_VERDICT_EFFECT_RE = re.compile(r'res\["effect"\]\s*=\s*_realized_effect\s*\(')

# ── قرار دادِ «سوییچِ خودکارِ فید بعد از اعلام» (لایهٔ ۴.۲۰) ───────────────
# خواستهٔ کاربر: «فیدِ خبرهای پیش‌رو را طوری کن که بعد از اعلامِ عدد، خودکار از
# گزارهٔ شرطی به «نتیجه + تأثیرِ محقق» سوییچ کند — نه دو سناریوی همیشگی.»
# فیدِ پیشِ رو عمداً دو سناریو دارد؛ رویدادِ گذشته باید `passed` + `verdict`
# بگیرد و **بی‌`analysis`** بمانَد تا رندرِ شرطی برایش ممکن نباشد.
_FEED_PAST_FN_RE = re.compile(r"def _feed_past_event\s*\(")
_FEED_PAST_FLAG_RE = re.compile(r'"passed":\s*True')
_FEED_ATTACH_RE = re.compile(r"_attach_verdicts\(past\)")
_FEED_NEXTHIGH_RE = re.compile(r'==\s*"High"\s*and\s*not\s+e\.get\("passed"\)')
_FEED_UI_PASSED_RE = re.compile(r"e\.passed")
_FEED_UI_RES_RE = re.compile(r"resCard\(e,\s*v\)")
_FEED_UI_BRANCH_RE = re.compile(r"(?<!!)past\s*\?\s*resCard\(e,\s*v\)")
_FEED_UI_IMPACT_RE = re.compile(r"تأثیرِ همین نتیجه")
# عبارتِ خودِ ردیفِ رابط لازم است: توضیحِ فارسیِ کنارِ `flipEvent` هم همین
# کلمه‌ها را دارد و با الگویِ کوتاه‌تر، جهشِ «ردیفِ صادقِ انتظار» را می‌پوشانْد.
_FEED_UI_WAIT_RE = re.compile(r"عددِ اعلام‌شده هنوز از منبع نرسیده")
_FEED_UI_SRCFAIL_RE = re.compile(r"منبعِ نتیجه پاسخ نداد")

# قراردادِ «پنجرهٔ گذشته + بجِ زندهٔ اعلام» (خواستهٔ کاربر: بجِ «N دقیقه پیش»
# بدونِ رفرشِ کلِ صفحه زنده باشد و پنجرهٔ گذشتهٔ فید ۶/۱۲/۲۴ ساعته انتخاب شود).
_FW_WINDOWS_RE = re.compile(r"PAST_WINDOWS\s*=\s*\(\s*6\s*,\s*12\s*,\s*24\s*\)")
_FW_FN_RE = re.compile(r"def past_window\s*\(")
_FW_NORM_RE = re.compile(r"return min\(PAST_WINDOWS, key=lambda")
_FW_OFF_RE = re.compile(r"if\s+n\s*<=\s*0:\s*\n\s*return\s+0")
_FW_FEED_RE = re.compile(r"hours=past_window\(past_hours\)")
_FW_BUILD_RE = re.compile(r"past_hours\s*=\s*past_window\(past_hours\)")
_FW_ECHO_RE = re.compile(r'"past_hours":\s*past_hours')
_FW_ROUTE_RE = re.compile(r'get\("past",')
# پاس‌دادنِ پنجره به `build` سنجیده می‌شود، نه هر `past_hours=past_hours`:
# مسیرِ `?event=` هم همین پاس را به `one_event` دارد و با الگویِ باز، خرابیِ
# `build` (انتخابگرِ گذشته) بی‌صدا سبز می‌مانْد.
_FW_ROUTE_PASS_RE = re.compile(r"FUND\.build\([^)]*past_hours=past_hours")
_FW_SEG_RE = re.compile(r'id="pastSeg"')
_FW_SEG_BTN_RE = re.compile(r'data-p="(6|12|24)"')
_FW_STATE_RE = re.compile(r"pastHours=6")
_FW_FETCH_RE = re.compile(r'\+"&past="\+pastHours')
_FW_TICK_FN_RE = re.compile(r"function tickBadges\s*\(\s*\)")
_FW_TICK_SEL_RE = re.compile(r'"#list \.cd-badge\.past\[data-m\]"')
_FW_TICK_BASE_RE = re.compile(r"Date\.now\(\)-T0")
_FW_DATAM_RE = re.compile(r'data-m="\$\{e\.minutes_ago\}"')
_FW_TICK_LOOP_RE = re.compile(r"setInterval\(tickBadges,")
_FW_T0_RE = re.compile(r"T0=Date\.now\(\)")
_FW_T0_INIT_RE = re.compile(r"pastHours=6,\s*T0=Date\.now\(\)")
_FW_FIRSTLOAD_RE = re.compile(r'if\(!DATA\)\s*\$\("#list"\)')

# قراردادِ «سوییچِ لحظه‌ایِ اعلام» (خواستهٔ کاربر: کارتِ پیشِ‌رو دقیقاً در لحظهٔ
# صفر شدنِ شمارشِ معکوس، بدونِ رفرش، به «اعلام شد + نتیجه» سوییچ کند).
_FF_INS_RE = re.compile(r'"in_s":\s*int\(max\(0,')
_FF_ONEEV_RE = re.compile(r"def one_event\s*\(")
_FF_ONEEV_EVENT_RE = re.compile(r'"event":\s*ev,')
_FF_ONEEV_NEXT_RE = re.compile(r'"next_high":')
_FF_ONEEV_FEED_RE = re.compile(r"= build_feed\(")
_FF_ROUTE_RE = re.compile(r'get\("event",')
_FF_FLIP_FN_RE = re.compile(r"async function flipEvent\s*\(")
_FF_PATCH_FN_RE = re.compile(r"function patchEvent\s*\(")
_FF_TICK_CALL_RE = re.compile(r"flipEvent\(c\.dataset\.key\)")
# کلیدِ dataset برای `data-in-s` می‌شود `inS`؛ خواندن با `dataset.in_s` بی‌صدا
# `undefined` می‌دهد و همهٔ کارت‌های پیشِ‌رو «رسیده» حساب می‌شوند.
_FF_INS_READ_RE = re.compile(r'getAttribute\("data-in-s"\)')
_FF_INS_BAD_RE = re.compile(r"dataset\.in_s")
_FF_EVENT_URL_RE = re.compile(r"\?event=\$\{encodeURIComponent\(iso\)\}")
_FF_EARLY_RE = re.compile(r"if\(!ev \|\| ev\.passed!==true\)")
_FF_RETRY_MAX_RE = re.compile(r"FLIP_RETRY_MAX=(\d+)")
_FF_RETRY_USE_RE = re.compile(r"n<=FLIP_RETRY_MAX")
_FF_RETRY_STOP_RE = re.compile(r"delete flipTries\[key\]")
_FF_RETRY_SCHED_RE = re.compile(r"setTimeout\(\(\)=>flipEvent\(nk\), FLIP_RETRY_MS\)")
_FF_FOUND_RE = re.compile(r"\(\(ev\.verdict\|\|\{\}\)\.found\)")
_FF_PATCH_ONLY_RE = re.compile(r"card\.outerHTML=evCard\(ev, idx\)")
_FF_DATA_SYNC_RE = re.compile(r"DATA\.events\[i\]=ev")
_FF_REKEY_RE = re.compile(r"const nk=evKey\(ev\)")
_FF_REKEY_CARD_RE = re.compile(r"findCard\(nk\)")
_FF_NEXT_SYNC_RE = re.compile(r"DATA\.next_high=\(d && d\.next_high\)\|\|null")
_FF_NEXT_FN_RE = re.compile(r"function renderNext\s*\(")
_FF_NEXT_USE_RE = re.compile(r"renderNext\(\)")
_FF_DATAS_RE = re.compile(r'data-in-s="\$\{e\.in_s\}"')
_FF_FRESH_BASE_RE = re.compile(r'nb\.setAttribute\("data-t0", String\(Date\.now\(\)\)\)')
_FF_NUM_MULT_RE = re.compile(r'_NUM_MULT\s*=\s*\{\s*"k":')
_FF_NUM_USE_RE = re.compile(r"mult\s*=\s*_NUM_MULT\[s\[-1:\]\]")
_FF_NUM_EMPTY_RE = re.compile(r"if\s+not\s+s:\s*\n\s*return\s+None")
_FF_NUM_EXACT_RE = re.compile(r"if\s+not\s+s\s+or\s+s\s+in\s+_VERDICT_SKIP_TOKENS:")
_FW_OPEN_KEEP_RE = re.compile(r"openKeys\.has\(evKey\(e\)\)")

# ── قراردادِ «کلیدِ بی‌واکنش نداریم» (لایهٔ ۴.۱۷) ───────────────────────────
# شکایتِ واقعیِ کاربر: «چک کن خیلی از کلیدا رو از کار انداختی — مثلاً فاندمنتال و
# روزرسانی». راستی‌آزماییِ زندهٔ اپ نشان داد دو بی‌صداییِ **واقعی** وجود دارد:
#  (۱) کلیدِ فاندمنتال تنها جایی است که `window.open` می‌زند؛ در نصبِ PWA
#      (display-mode: standalone) یا با پاپ‌آپ‌بلاکر NULL برمی‌گرداند و کلید
#      بی‌صدا می‌مُرد (نه تبی، نه پیامی) ⇒ تورِ ایمنیِ «همین‌تب» اجباری است.
#  (۲) پیامِ «چیزی برای بروزرسانی نیست» داخلِ `.rf-live` می‌رفت که عمداً sr-only
#      است (width:1px برای صفحه‌خوان) ⇒ روی نمایشگر دیده نمی‌شد.
_FUND_HANDLER_RE = re.compile(r"fundBtn\.onclick\s*=\s*\(\)\s*=>\s*\{(.*?)\n\s*\};", re.S)
_FUND_ARROW_RE = re.compile(r"(fundBtn\.onclick\s*=\s*\(\)\s*=>\s*\{.*?\n\s*\};)", re.S)
_NEWTAB_OPEN_RE = re.compile(r"window\.open\s*\(")
_FUND_NULL_GUARD_RE = re.compile(r"if\s*\(\s*!\s*[A-Za-z_$][\w$]*\s*\)")
_FUND_SAME_TAB_RE = re.compile(r"location\.assign\(\s*[\"']/fundamental[\"']\s*\)")
_RF_HINT_DOM_RE = re.compile(r"rf-hint")
_RF_NEED_JS_RE = re.compile(r"classList\.add\(\s*[\"']need[\"']\s*\)")
_RF_NEED_CSS_RE = re.compile(r"\.rf-btn\.need\s*\{")

# ── قراردادِ «پرسشِ تأییدِ شکافِ ارزش منصفانه» (لایهٔ ۴.۲۳) ─────────────────
# خواستهٔ کاربر: «کاربر آدرسِ شکاف را در یک تایم‌فریمِ مشخص می‌دهد و از اپ
# می‌خواهد تأییدِ همان گپ را بررسی کند.» یعنی رابط یک **پرسش** است، نه فهرستِ
# خام. قراردادی که باید سالم بمانَد (هر شکستنش = پرسشِ بی‌جواب یا حکمِ دروغ):
#   ۱) پویشِ گپ‌ها گیتِ دیسپلیسمنت ندارد — گرنه آدرسِ درستِ کاربر «پیدا نشد»
#      می‌گیرد چون گپِ کم‌جان پیش از تطبیق حذف می‌شود؛
#   ۲) آدرسِ کاربر با آستانهٔ ۵۰٪ هم‌پوشانی به گپِ واقعی قفل می‌شود؛
#   ۳) چرخهٔ عمرِ چهارحالته (تازه/لمس‌شده/میتیگیت/پرشده) و سقف‌های اعتبار
#      (بازارِ بسته ⇒ C، گپِ مصرف‌شده ⇒ C) حفظ شوند؛
#   ۴) دوازده بندِ امتیازِ تأیید و فقط درجه‌های A+/A «قابلِ اتکا»؛
#   ۵) اندپوینتِ /api/gap + پنلِ کرکره‌ایِ پرسش که آدرس (lo/hi) را می‌فرستد.
_GQ_DISP_GATE_RE = re.compile(r"^DISP_GATE\s*=\s*([0-9.]+)", re.M)
_GQ_DISP_STRONG_RE = re.compile(r"^DISP_STRONG\s*=\s*([0-9.]+)", re.M)
_GQ_MATCH_MIN_RE = re.compile(r"^MATCH_MIN_OVERLAP\s*=\s*([0-9.]+)", re.M)
_GQ_RELIABLE_RE = re.compile(r"RELIABLE_GRADES\s*=\s*\(([^)]*)\)")
_GQ_ROW_RE = re.compile(r"^\s*row\(", re.M)
_GQ_SCAN_GATE_RE = re.compile(r"DISP_GATE")
_GQ_STATE_RE = re.compile(r'"(fresh|touched|mitigated|filled)"')
_GQ_IMPORT_RE = re.compile(r"^\s*import gap_query as G", re.M)
_GQ_PANEL_IDS = ("gapDock", "gapToggle", "gapBody", "gapSym", "gapTf",
                 "gapLo", "gapHi", "gapGo", "gapList", "gapRes")
_GQ_FOLD_CALL_RE = re.compile(
    r'pfFold\(\s*"gapDock"\s*,\s*"gapToggle"\s*,\s*"gapBody"\s*\)')
_GQ_SEND_LO_RE = re.compile(r'qs\.set\(\s*"lo"\s*,')
_GQ_SEND_HI_RE = re.compile(r'qs\.set\(\s*"hi"\s*,')
_GQ_MODE_FALSE_RE = re.compile(r"pfGapAsk\(\s*false\s*\)")
_GQ_MODE_TRUE_RE = re.compile(r"pfGapAsk\(\s*true\s*\)")
# پیشوندِ دادهٔ گپ عمداً `g` است، نه `v`: قاعدهٔ آرشیو (`archive_problems`)
# نشانگرِ رندرِ حکم را با `v.found` می‌سنجد و در همان صفحهٔ نمای اصلی است؛ اگر
# پنلِ گپ هم `v.found` بنویسد، جهشِ «آرشیو v.found را نمی‌سنجد» بی‌صدا سبز می‌مانَد
# (همین اتفاق یک‌بار افتاد و `archive_actual_test.py` گرفتش).
_GQ_RELIABLE_UI_RE = re.compile(r"g\.reliable")
# کارتِ گپ باید پیشوندِ `g.` بماند و هیچ `v.`ای نداشته باشد:
# (۱) نشانگرِ رندرِ حکمِ آرشیو (`v.found`) در همین صفحه است و نامِ همسان
#     کورش می‌کند (یک‌بار همان اتفاق افتاد و جهشِ آرشیو بی‌صدا سبز ماند)؛
# (۲) `v.` جا‌مانده یعنی `ReferenceError: v is not defined` که هیچ چکِ
#     استاتیکی نمی‌گیرد و فقط در مرورگر و به‌شکلِ کارتِ خالی دیده می‌شود.
_GQ_BARE_V_RE = re.compile(r"(?<![A-Za-z0-9_$.])v\.[A-Za-z_]+")
_GQ_CARD_START = "function gapCardHtml"
_GQ_CARD_END = "function gapStateSet"
# نامِ کوتاهِ دوازده بندِ امتیازِ تأیید (هر حذفِ خاموشِ یک معیار = حکمِ خوش‌بینانه).
# این‌ها همان رشته‌های ثابتِ داخلِ gap_verdict‌اند؛ کوچک‌ترین ویرایشِ معیار
# باید یا رشته را نگه دارد یا این قاعده را عمداً قرمز کند.
_GQ_CRITERIA = (
    "دیسپلیسمنتِ کندلِ میانی",
    "دیسپلیسمنتِ قوی",
    "گپِ دست‌نخورده",
    "هم‌جهتی با بایاسِ",
    "کانفلوئنسِ POIِ",
    "توالیِ سوئیپ→MSS",
    "سوئیپِ لیکوئیدیتی پیش از تولدِ گپ",
    "سمتِ پریمیوم/دیسکانت",
    "تولدِ گپ داخلِ کیل‌زون",
    "هم‌پوشانی با اردر بلاکِ هم‌جهت",
    "اندازهٔ معقولِ گپ",
    "قابلِ اجرا بودن (فاصلهٔ قیمت)",
)

# ── قراردادِ «کرکره‌های جمعِ پیش‌فرض» (لایه‌ی ۴.۱۸) ──────────────────────────
# خواستهٔ کاربر: بخش‌های «نگهداری» در نمای اصلی همیشه‌باز نباشند — آلارم‌ها،
# تنظیماتِ بک‌تست، مدیریتِ ریسک و پشتیبان/انتقالِ داده هر کدام یک نوارِ کلیدپذیر
# باشند و بدنه فقط با کلیک باز شود. سه چیز باید قفل بماند: (۱) مکانیکِ مشترک —
# بدنه پیش‌فرض پنهان است و فقط در حالتِ باز نمایش داده می‌شود؛ (۲) هر نوار
# کلیدپذیر است و حالتِ خودش را به صفحه‌خوان هم می‌گوید؛ (۳) گزینه‌های بخشِ
# پشتیبان (برون‌بری/درون‌بری/پشتیبانِ خودکار/فهرستِ نسخه‌ها) *داخلِ* بدنه بمانند.
_FOLD_PANELS = (
    ("alarmsDock", "alarmsToggle", "alarmsBody"),
    ("btPanel", "btToggle", "btBody"),
    ("riskPanel", "rkToggle", "rkBody"),
    ("bkDock", "bkToggle", "bkBody"),
    ("gapDock", "gapToggle", "gapBody"),
)
_FOLD_TAG_RE = re.compile(r'<(?:div|button|h2)\b[^>]*>', re.S)
_FOLD_BODY_HIDE_RE = re.compile(r'\.fold-body\s*\{[^}]*display\s*:\s*none', re.S)
_FOLD_BODY_SHOW_RE = re.compile(r'\.fold\.open\s+\.fold-body\s*\{[^}]*display\s*:\s*block', re.S)
# تلهٔ واقعیِ همین دور: هر قاعدهٔ نمایشیِ دیگر روی *خودِ* بدنه (هم‌ارزِ انتخاب‌گر و
# بعدتر در فایل) قاعدهٔ پنهان‌بودن را بی‌اثر می‌کند و پنل همیشه‌باز می‌مانَد.
_FOLD_BODY_CLASS_RE = re.compile(r'class="fold-body\s+([A-Za-z][A-Za-z0-9_-]*)"')
_FOLD_BODY_CLASSES = ("alarms-body", "bt-body", "risk-body", "bk-body")
_FOLD_STYLE_RE = re.compile(r'<style[^>]*>(.*?)</style>', re.S)
_FOLD_RULE_RE = re.compile(r'([^{}]+)\{([^{}]*)\}', re.S)
# یادِ وضعیتِ باز/بستهٔ کرکره‌ها بینِ بازدیدها (خواستهٔ کاربر).
_FOLD_MEM_KEY_RE = re.compile(r'const\s+PF_FOLD_KEY\s*=\s*"pf-folds[^"]*"')
_FOLD_MEM_SAVE_RE = re.compile(r'tgl\.onclick\s*=\s*\(\)\s*=>\s*\{[^}]*pfFoldsWrite\(')
_FOLD_JS_INIT_RE = re.compile(r'function\s+pfFold\s*\(')
_FOLD_JS_ARIA_RE = re.compile(r'setAttribute\("aria-expanded"\s*,')
_FOLD_JS_CALL_RE = re.compile(
    r'pfFold\(\s*"([A-Za-z0-9_]+)"\s*,\s*"([A-Za-z0-9_]+)"\s*,\s*"([A-Za-z0-9_]+)"\s*\)')
_BK_OPTION_IDS = ("expBtn", "impBtn", "abToggle", "abList", "abStat")
_BK_STATE_DOM_RE = re.compile(r'id="bkState"')
_BK_STATE_JS_RE = re.compile(r'getElementById\("bkState"\)')


def _fold_tag(page, needles):
    """نخستین تگِ مارک‌آپی که همهٔ رشته‌های لازم را در خود دارد → (اندیس، متنِ تگ)."""
    for m in _FOLD_TAG_RE.finditer(page):
        t = m.group(0)
        if all(n in t for n in needles):
            return m.start(), t
    return -1, ""


def _fold_display_overrides(page, hide_at):
    """قاعده‌های CSSی که بعد از پنهان‌بودنِ پیش‌فرض، روی *خودِ* یک بدنه `display`
    می‌گذارند — انتخاب‌گرِ هم‌ارز + ترتیبِ متن یعنی پنهان‌بودن بی‌اثر می‌شود
    (همان باگی که `.bt-body{display:flex}` زنده ساخت). قاعدهٔ بازکردنِ عمومی
    (`.fold.open .fold-body`) عمداً مستثناست چون قراردادِ خودِ کرکره است.
    فقط داخلِ بلوک‌های `<style>` می‌گردد تا متنِ JS/مارک‌آپ قاطیِ قاعده‌ها نشود.
    """
    hits = []
    classes = sorted(set(_FOLD_BODY_CLASS_RE.findall(page)) or set(_FOLD_BODY_CLASSES))
    for sm in _FOLD_STYLE_RE.finditer(page):
        base = sm.start(1)
        for rm in _FOLD_RULE_RE.finditer(sm.group(1)):
            sel, decls = rm.group(1), rm.group(2)
            if base + rm.start(1) < hide_at or ".fold.open" in sel:
                continue
            if not re.search(r'display\s*:', decls):
                continue
            for cls in classes:
                if re.search(r'\.%s(?![-\w])' % re.escape(cls), sel):
                    hits.append(cls)
    return sorted(set(hits))


def _fold_fn_body(page, name):
    """تنهٔ یک تابعِ سطح‌بالا (توابعِ همین صفحه در ستونِ ۰ شروع می‌شوند)."""
    at = page.find("function %s(" % name)
    if at < 0:
        return ""
    end = page.find("\n}", at)
    return page[at:end] if end > at else page[at:]


def _fold_memory_problems(page):
    """یادِ باز/بسته‌بودنِ کرکره‌ها بینِ بازدیدها: خواندن/نوشتنِ حافظهٔ محلی باید
    داخلِ `try` باشد (حالتِ حریمِخصوصی `localStorage` را می‌پرتاند)، وضعیتِ یادمانده
    باید در `pfFold` پیش از رسم برگردد، و در همان هندلرِ کلیک ذخیره شود.
    عمداً `localStorage` است نه `sessionStorage`: این یاد باید از بازدیدِ بعدی هم بماند.
    """
    probs = []
    rd = _fold_fn_body(page, "pfFoldsRead")
    wr = _fold_fn_body(page, "pfFoldsWrite")
    fb = _fold_fn_body(page, "pfFold")
    if _FOLD_MEM_KEY_RE.search(page) is None:
        probs.append("app.py · کلیدِ حافظهٔ کرکره‌ها (PF_FOLD_KEY) نیست — باز/بسته‌بودنِ "
                     "بخش‌ها بینِ بازدیدها یاد نمی‌ماند")
    if not rd or "localStorage" not in rd or "try" not in rd:
        probs.append("app.py · خواندنِ حافظهٔ کرکره‌ها بدونِ try/localStorage است — "
                     "صفحه در حریمِخصوصی می‌شکند")
    if not wr or "localStorage" not in wr or "try" not in wr:
        probs.append("app.py · نوشتنِ حافظهٔ کرکره‌ها بدونِ try/localStorage است — "
                     "کلید در حریمِخصوصی خطا می‌دهد")
    if not fb or 'classList.add("open")' not in fb:
        probs.append("app.py · کرکره‌ها وضعیتِ یادماندهٔ خودشان را برنمی‌گردانند — هر بخش "
                     "با هر بازدید جمع می‌شود")
    elif fb.find('classList.add("open")') > fb.find("tgl.onclick"):
        probs.append("app.py · بازگردانیِ وضعیت بعد از سیم‌کشی/رسم انجام می‌شود — "
                     "بدنه و aria با یادِ قبلی هم‌گام نمی‌شوند")
    if _FOLD_MEM_SAVE_RE.search(fb) is None:
        probs.append("app.py · کلیکِ کاربر در حافظه ذخیره نمی‌شود (بیرونِ هندلرِ کلیک) — "
                     "باز گذاشتنِ یک بخش تا بازدیدِ بعد نمی‌ماند")
    return (not probs), probs


def fold_panels_problems(root, pages=None):
    """قراردادِ «کرکره‌های جمعِ پیش‌فرض»: بخش‌های نگهداریِ نمای اصلی (آلارم‌ها،
    تنظیماتِ بک‌تست، مدیریتِ ریسک و پشتیبانِ داده) یک نوارِ کلیدپذیر داشته باشند،
    بدنه‌شان پیش‌فرض بسته بماند، و وضعیتشان روی همان نوار دیده شود."""
    probs = []
    stats = {"panels": 0, "collapsed": False, "wired": False,
             "options_inside": False, "state": False, "memory": False}
    page = (pages or {}).get("HTML") or ""
    if not page:
        probs.append("app.py → متنِ APP_PAGE خوانده نشد — کرکره‌های نمای اصلی سنجیده نمی‌شوند")
        return probs, stats

    # مکانیکِ مشترک: پنهان‌بودنِ پیش‌فرضِ بدنه + قاعدهٔ بازشدن + سازندهٔ عمومی
    mech = True
    if _FOLD_BODY_HIDE_RE.search(page) is None:
        probs.append("app.py · بدنهٔ کرکره‌ها پیش‌فرض پنهان نیست (CSS) — "
                     "نمای اصلی دوباره شلوغ می‌شود")
        mech = False
    if _FOLD_BODY_SHOW_RE.search(page) is None:
        probs.append("app.py · قاعدهٔ بازشدنِ کرکره‌ها نیست — کلیدها بی‌اثر می‌مانند")
        mech = False
    if _FOLD_JS_INIT_RE.search(page) is None:
        probs.append("app.py · سازندهٔ کرکره (pfFold) حذف شده — هیچ نواری سیم‌کشی نمی‌شود")
        mech = False
    hm = _FOLD_BODY_HIDE_RE.search(page)
    if hm is not None:
        clobber = _fold_display_overrides(page, hm.end())
        if clobber:
            probs.append("app.py · قاعدهٔ نمایشیِ «.%s» پنهان‌بودنِ پیش‌فرضِ بدنه را "
                         "بی‌اثر می‌کند (هم‌ارز است ولی بعدتر آمده) — پنل همیشه‌باز "
                         "می‌مانَد" % "، ".join(clobber))
            mech = False
    stats["collapsed"] = mech

    calls = set(_FOLD_JS_CALL_RE.findall(page))
    folded, bk_body_at = 0, -1
    for box_id, tgl_id, body_id in _FOLD_PANELS:
        box_at, box_tag = _fold_tag(page, ['id="%s"' % box_id])
        cm = re.search(r'class="([^"]*)"', box_tag) if box_at >= 0 else None
        cls = cm.group(1) if cm else ""
        if box_at < 0 or "fold" not in cls.split():
            probs.append("app.py · بخشِ %s کلاسِ کرکره (fold) ندارد — همیشه‌باز می‌مانَد"
                         % box_id)
            continue
        tgl_at, _ = _fold_tag(page, ['id="%s"' % tgl_id, 'aria-expanded="false"',
                                     'aria-controls="%s"' % body_id])
        if tgl_at < 0:
            probs.append("app.py · نوارِ %s کلیدپذیر نیست (aria-expanded=\"false\" و "
                         "aria-controls لازم است)" % box_id)
            continue
        body_at, _ = _fold_tag(page, ['id="%s"' % body_id, "fold-body"])
        if body_at < 0:
            probs.append("app.py · بدنهٔ کرکرهٔ %s پیدا نشد (کلاسِ fold-body)" % box_id)
            continue
        if body_at < tgl_at:
            probs.append("app.py · بدنهٔ %s قبل از نوار آمده — ساختارِ کرکره خراب است"
                         % box_id)
            continue
        if (box_id, tgl_id, body_id) not in calls:
            probs.append("app.py · کرکرهٔ %s سیم‌کشی نشده (pfFold صدا زده نمی‌شود) — "
                         "کلیک هیچ کاری نمی‌کند" % box_id)
            continue
        folded += 1
        if box_id == "bkDock":
            bk_body_at = body_at

    mem_ok, mem_probs = _fold_memory_problems(page)
    probs += mem_probs
    stats["memory"] = mem_ok

    if _FOLD_JS_ARIA_RE.search(page) is None:
        probs.append("app.py · نوارهای کرکره وضعیتِ خودشان را به صفحه‌خوان نمی‌گویند "
                     "(aria-expanded)")
    stats["panels"] = folded
    stats["wired"] = (folded == len(_FOLD_PANELS)
                       and _FOLD_JS_ARIA_RE.search(page) is not None)

    # گزینه‌های بخشِ پشتیبان باید داخلِ بدنهٔ همان کرکره بمانند
    if bk_body_at < 0:
        probs.append("app.py · بدنهٔ کرکرهٔ پشتیبان (bkBody) پیدا نشد — گزینه‌ها بی‌جا می‌مانند")
    else:
        outside = [i for i in _BK_OPTION_IDS
                   if 0 <= page.find('id="%s"' % i) < bk_body_at]
        if outside:
            probs.append("app.py · این گزینه‌ها بیرونِ بدنهٔ کرکرهٔ پشتیبان‌اند "
                         "(باید جمع شوند): " + "، ".join(outside))
        else:
            stats["options_inside"] = True

    # خلاصهٔ وضعیت باید هم روی نوار باشد و هم JS آن را پر کند؛ عمداً با regexِ
    # دقیق (نه countِ زیررشته‌ای) سنجیده می‌شود — وگرنه نامِ مشابهی مثلِ bkStateX
    # هم زیررشتهٔ bkState را دارد و جهش را سبزِ دروغ می‌گذارد.
    stats["state"] = bool(_BK_STATE_DOM_RE.search(page)) \
        and _BK_STATE_JS_RE.search(page) is not None
    if not stats["state"]:
        probs.append("app.py · خلاصهٔ وضعیتِ پشتیبان روی نوارِ بسته دیده نمی‌شود (bkState) "
                     "— کاربر از روی نوار نمی‌فهمد پشتیبان روشن است یا نه")
    return probs, stats


def _py_region(src, start_marker, end_marker):
    """تکهٔ متنِ پایتونی از `start_marker` تا `end_marker` (خالی یعنی پیدا نشد)."""
    i = src.find(start_marker)
    if i < 0:
        return ""
    j = src.find(end_marker, i)
    return src[i:j] if j > i else src[i:]


def _archive_region(page):
    """متنِ هندلرِ «آرشیو اقتصادی» — تا سنجشِ «گزارهٔ شرطی» فقط همین پنجره را ببیند
    (فیدِ خبرهای پیش‌رو عمداً گزارهٔ شرطی دارد و نباید با آرشیو اشتباه شود)."""
    i = page.find("const archiveBtn=")
    if i < 0:
        return ""
    j = page.find("async function setOteAlarm", i)
    return page[i:j] if j > i else page[i:i + 6000]


def _feed_evcard_region(fund):
    """تکهٔ JSِ سازندهٔ کارتِ رویداد در فید (/fundamental) — سنجشِ «سوییچِ
    اعلام» فقط همین‌جا انجام می‌شود، نه در کلِ صفحه (سناریوها عمداً هستند)."""
    i = fund.find("function evCard(e,idx){")
    if i < 0:
        return ""
    j = fund.find("\nfunction render(){", i)
    return fund[i:j] if j > i else fund[i:i + 4000]


def archive_problems(root, pages=None):
    """قراردادِ «نتیجه + تأثیر در آرشیو، بی‌گزارهٔ شرطی»: زنجیرهٔ
    Actual → حکم (با اثرِ محقَق) → رندرِ مطلقِ بی‌شرط سالم بماند."""
    probs = []
    stats = {"actuals": False, "verdict": False, "render": False,
             "outcomes": 0, "note": False, "effect": False,
             "conditional": False, "impact": False, "lean": False,
             "perrow": False}
    msrc = read_text(os.path.join(root, "macro_context.py")) or ""
    fsrc = read_text(os.path.join(root, "fundamental.py")) or ""
    page = (pages or {}).get("HTML") or ""
    if not msrc:
        probs.append("macro_context.py خوانده نشد — ستونِ Actual بی‌منبع می‌مانَد")
        return probs, stats
    if not _ACTUALS_KEY_RE.search(msrc):
        probs.append("macro_context.py · گیرنده‌ی Actual (get_actuals) حذف شده — "
                     "آرشیو به گزاره‌ی شرطی برمی‌گردد")
    elif _TE_ACTUAL_SPAN not in msrc:
        probs.append("macro_context.py · الگوی ستونِ Actual (id='actual') در پارسر نیست — "
                     "اعداد خوانده نمی‌شوند")
    else:
        stats["actuals"] = True
        if _VERDICT_CALL_RE.search(fsrc) and _VERDICT_FN_RE.search(fsrc) \
                and ("صعودی" in fsrc and "نزولی" in fsrc):
            stats["verdict"] = True
        if _VERDICT_CALL_RE.search(fsrc) is None:
            probs.append("fundamental.py · archive دیگر _attach_verdicts را صدا نمی‌زند — "
                         "حکمِ قطعی به رویدادها تزریق نمی‌شود")
        if _VERDICT_FN_RE.search(fsrc) is None:
            probs.append("fundamental.py · تابعِ حکم (_verdict) حذف شده")
        if _ARC_EFFECT_FN_RE.search(fsrc) and _VERDICT_EFFECT_RE.search(fsrc):
            stats["effect"] = True
        elif _ARC_EFFECT_FN_RE.search(fsrc) is None:
            probs.append("fundamental.py · سازندهٔ تأثیرِ محقَق (_realized_effect) حذف شده — "
                         "آرشیو نمی‌تواند تأثیرِ نتیجه را نشان بدهد")
        else:
            probs.append("fundamental.py · حکم دیگر تأثیرِ خودش را نمی‌سازد "
                         "(res[\"effect\"] = _realized_effect(…)) — تأثیرِ آرشیو خالی می‌مانَد")
        areg = _py_region(fsrc, "def archive(hours=6):", "\ndef build(hours=180):")
        if not areg:
            probs.append("fundamental.py · تابعِ archive پیدا نشد — بارِ آرشیو سنجیده نمی‌شود")
        else:
            if '"analysis"' in areg:
                probs.append("fundamental.py · بارِ آرشیو باز هم شاخهٔ شرطی (analysis) را می‌فرستد — "
                             "«فقط نتیجه بیاد، نه گزارهٔ شرطی» نیمه‌کاره می‌مانَد")
            stats["lean"] = '"analysis"' not in areg
    if not page:
        probs.append("app.py → متنِ APP_PAGE خوانده نشد — رندرِ حکم سنجیده نمی‌شود")
    else:
        if _ARC_VERDICT_RE.search(page) is None:
            probs.append("app.py · آرشیو دیگر v.found را نمی‌سنجد — حکمِ مطلق رندر نمی‌شود")
        if _ARC_OUTCOME_RE.search(page) is None:
            probs.append("app.py · آرشیو صعودی/نزولی را نشان نمی‌دهد — "
                         "خواسته‌ی کاربر («مطلق باشد») نیمه‌کاره می‌مانَد")
        if _ARC_ACTUAL_NUM_RE.search(page) is None:
            probs.append("app.py · عددِ اعلام‌شده (v.actual) در رندر نیست")
        if _ARC_ABSENT_RE.search(page) is None:
            probs.append("app.py · پیامِ شفافِ «منبع در دسترس نبود» حذف شده — "
                         "کاربر حدس به‌جای حکم می‌بیند")
        if _ARC_VERDICT_RE.search(page) and _ARC_OUTCOME_RE.search(page) \
                and _ARC_ACTUAL_NUM_RE.search(page) and _ARC_ABSENT_RE.search(page):
            stats["render"] = True
        stats["outcomes"] = len(re.findall(r"صعودی|نزولی", page))
        stats["note"] = bool(_ARCHIVE_NOTE_RE.search(page))
        # «فقط نتیجه + تأثیرش، نه گزارهٔ شرطی» — سنجیده‌شده فقط داخلِ خودِ آرشیو.
        region = _archive_region(page)
        if not region:
            probs.append("app.py · هندلرِ آرشیوِ اقتصادی (archiveBtn) پیدا نشد — "
                         "پنجرهٔ «نتیجه + تأثیر» سنجیده نمی‌شود")
        else:
            if _ARC_COND_RE.search(region):
                probs.append("app.py · آرشیو باز هم گزارهٔ شرطی (beat/miss) را رندر می‌کند — "
                             "خواستهٔ کاربر («فقط نتیجه بیاد بعلاوهٔ تأثیرش، نه گزارهٔ شرطی») نقض شده")
            stats["conditional"] = _ARC_COND_RE.search(region) is None
            if _ARC_PERROW_RE.search(region) is None:
                probs.append("app.py · خبرِ بدونِ عددِ اعلام‌شده، ردیفِ خالی می‌دهد — "
                             "کاربر فکر می‌کند اپ یادش رفته")
            stats["perrow"] = _ARC_PERROW_RE.search(region) is not None
            if _ARC_IMPACT_RE.search(region) is None:
                probs.append("app.py · آرشیو «تأثیرِ همین نتیجه» را نشان نمی‌دهد — "
                             "نتیجه بی‌تأثیر می‌مانَد")
            stats["impact"] = _ARC_IMPACT_RE.search(region) is not None
    return probs, stats


def feed_switch_problems(root, pages=None):
    """قراردادِ «سوییچِ خودکارِ فید بعد از اعلامِ عدد»: رویدادِ گذشته از
    _feed_past_event می‌آید (passed=True، بی‌analysis)، حکمِ قطعی با
    _attach_verdicts(past) تزریق می‌شود، «نزدیک‌ترین خبرِ پرتأثیر» فقط از
    پیشِ‌روهاست، و رابط برای رویدادِ اعلام‌شده کارتِ «نتیجه + تأثیر» می‌سازد."""
    probs = []
    stats = {"past_fn": False, "lean": False, "verdict": False, "nexthigh": False,
             "ui": False, "impact": False, "wait": False, "scen_future": False}
    fsrc = read_text(os.path.join(root, "fundamental.py")) or ""
    fund = (pages or {}).get("FUND_PAGE") or ""
    if not fsrc:
        probs.append("fundamental.py خوانده نشد — سوییچِ فید سنجیده نمی‌شود")
        return probs, stats
    if _FEED_PAST_FN_RE.search(fsrc) is None:
        probs.append("fundamental.py · سازندهٔ رویدادِ گذشتهٔ فید (_feed_past_event) "
                     "حذف شده — فید برای خبرِ اعلام‌شده دو سناریوی همیشگی را می‌مانَد")
        return probs, stats
    pfn = _py_region(fsrc, "def _feed_past_event", "\ndef build_feed")
    if not pfn:
        probs.append("fundamental.py · بدنهٔ سازندهٔ رویدادِ گذشتهٔ فید پیدا نشد — "
                     "`passed` و بارِ بی‌analysis سنجیده نمی‌شوند")
        return probs, stats
    if _FEED_PAST_FLAG_RE.search(pfn) is None:
        probs.append("fundamental.py · رویدادِ گذشته `passed=True` نمی‌گیرد — "
                     "رابط نمی‌فهمد خبر اعلام شده")
    else:
        stats["past_fn"] = True
    if '"analysis"' in pfn:
        probs.append("fundamental.py · بارِ رویدادِ گذشته باز هم `analysis`ِ دوشاخه‌ای "
                     "می‌فرستد — رندرِ شرطی برای خبرِ اعلام‌شده ممکن می‌مانَد")
    stats["lean"] = '"analysis"' not in pfn
    bfreg = _py_region(fsrc, "def build_feed", "_VERDICT_SKIP_TOKENS")
    if bfreg and _FEED_ATTACH_RE.search(bfreg):
        stats["verdict"] = True
    else:
        probs.append("fundamental.py · build_feed حکمِ قطعی (_attach_verdicts(past)) را "
                     "تزریق نمی‌کند — «نتیجه + تأثیر» نمایش داده نمی‌شود")
    # پنجرهٔ `build` عمداً تا `one_event` بسته می‌شود؛ وگرنه خطوطِ مشترکِ تک‌رویداد
    # می‌توانست خرابیِ `build` را بپوشانَد و جهشِ آزمون بی‌صدا سبز بمانَد.
    breg = _py_region(fsrc, "def build(", "\ndef one_event(")
    if breg and _FEED_NEXTHIGH_RE.search(breg):
        stats["nexthigh"] = True
    else:
        probs.append("fundamental.py · «نزدیک‌ترین خبرِ پرتأثیر» رویدادهای گذشته را "
                     "کنار نمی‌گذارد — خبرِ اعلام‌شده به‌جای خبرِ بعدی نشان داده می‌شود")
    if not fund:
        probs.append("app.py → متنِ FUND_PAGE خوانده نشد — سوییچِ فید در رابط سنجیده نمی‌شود")
        return probs, stats
    if _FEED_UI_PASSED_RE.search(fund) is None:
        probs.append("app.py · فید وضعیتِ اعلام (`e.passed`) را نمی‌سنجد — رویدادِ "
                     "اعلام‌شده باز هم دو سناریوی شرطی می‌گیرد")
        return probs, stats
    evreg = _feed_evcard_region(fund)
    if not evreg:
        probs.append("app.py · سازندهٔ کارتِ رویداد (evCard) در FUND_PAGE پیدا نشد")
        return probs, stats
    if _FEED_UI_RES_RE.search(evreg) is None:
        probs.append("app.py · کارتِ «نتیجه» (resCard) در مسیرِ رویدادِ گذشته نیست — "
                     "سوییچِ اعلام نیمه‌کاره می‌مانَد")
    else:
        stats["ui"] = True
        if _FEED_UI_BRANCH_RE.search(evreg) is None:
            probs.append("app.py · شاخهٔ رویدادِ اعلام‌شده خراب است (‏`past ? resCard…` نیست) — "
                         "فید ممکن است برعکس سوییچ کند")
    if _FEED_UI_IMPACT_RE.search(fund) is None:
        probs.append("app.py · «تأثیرِ همین نتیجه» در فید رندر نمی‌شود")
    else:
        stats["impact"] = True
    wait_ok = bool(_FEED_UI_WAIT_RE.search(fund)) and bool(_FEED_UI_SRCFAIL_RE.search(fund))
    if not wait_ok:
        probs.append("app.py · حالتِ صادقِ انتظارِ نتیجه (عدد نرسیده/منبع پاسخ نداد) "
                     "در فید نیست — کاربر حدس می‌بیند")
    stats["wait"] = wait_ok
    i_res = evreg.find("resCard(e, v)")
    i_scen = evreg.find('scenCard("beat"')
    if i_scen < 0:
        probs.append("app.py · سناریوهای پیشِ‌رو (scenCard) از فید حذف شدند — "
                     "خبرِ اعلام‌نشده باید دو سناریو داشته باشد")
    else:
        stats["scen_future"] = True
        if not (0 <= i_res < i_scen):
            probs.append("app.py · ترتیبِ شاخه‌های فید خراب است (سناریو قبل از نتیجه) — "
                         "برای خبرِ اعلام‌شده هم گزارهٔ شرطی رندر می‌شود")
    return probs, stats


def feed_window_problems(root, pages=None):
    """قراردادِ «پنجرهٔ گذشته + بجِ زندهٔ اعلام» (خواستهٔ کاربر).

    دو چیز باید سالم بماند:
      ۱) پنجرهٔ گذشتهٔ فید فقط ۶/۱۲/۲۴ ساعت باشد و از انتخابگرِ رابط به سرور
         برود (`?past=`) — با `past_window` قطعیِ شود تا ورودیِ دلبخواهیِ URL
         فید را سنگین یا خالی نکند.
      ۲) بجِ «N دقیقه پیش» با یک تیکِ سبکِ سمتِ کاربر (بدونِ فراخوانیِ
         `load()`/`render()`/شبکه) زنده بماند — اگر کسی دوباره خواندنِ کامل
         را جا بگذارد، کاربر دوباره می‌گوید «صفحه دارد رفرش می‌شود».
    """
    probs = []
    stats = {"windows": False, "fn": False, "norm": False, "feed": False,
             "build": False, "echo": False, "route": False, "seg": False,
             "seg_btns": 0, "state": False, "fetch": False, "tick": False,
             "tick_lean": False, "datam": False, "loop": False, "t0": False,
             "off": False, "firstload": False, "keep": False}
    fsrc = read_text(os.path.join(root, "fundamental.py")) or ""
    appsrc = read_text(os.path.join(root, "app.py")) or ""
    fund = (pages or {}).get("FUND_PAGE") or ""
    if not fsrc:
        probs.append("fundamental.py خوانده نشد — پنجرهٔ گذشتهٔ فید سنجیده نمی‌شود")
        return probs, stats
    if _FW_WINDOWS_RE.search(fsrc) is None:
        probs.append("fundamental.py · پنجره‌های مجازِ گذشته (`PAST_WINDOWS = (6, 12, 24)`)"
                     " پیدا نشد — پنجرهٔ گذشتهٔ فید بی‌سقف می‌شود")
        return probs, stats
    stats["windows"] = True
    if _FW_FN_RE.search(fsrc) is None:
        probs.append("fundamental.py · `past_window` حذف شده — مقدارِ `?past=` از "
                     "URL خام به فید می‌رسد")
        return probs, stats
    stats["fn"] = True
    wreg = _py_region(fsrc, "def past_window", "\ndef _feed_past_event")
    if not wreg:
        probs.append("fundamental.py · بدنهٔ `past_window` پیدا نشد — قطعی‌سازیِ "
                     "پنجره سنجیده نمی‌شود")
    else:
        if _FW_NORM_RE.search(wreg) is None:
            probs.append("fundamental.py · `past_window` مقدارِ نامعتبر را به نزدیک‌ترین "
                         "پنجرهٔ مجاز نمی‌برد — ورودیِ عجیب، فید را خالی/سنگین می‌کند")
        else:
            stats["norm"] = True
        if _FW_OFF_RE.search(wreg) is None:
            probs.append("fundamental.py · صفر در `past_window` دیگر «خاموش» نیست — "
                         "قراردادِ پنجرهٔ صفر (فیدِ فقط پیشِ‌رو) بی‌صدا عوض می‌شود")
        else:
            stats["off"] = True
    freg = _py_region(fsrc, "def build_feed", "_VERDICT_SKIP_TOKENS")
    if freg and _FW_FEED_RE.search(freg):
        stats["feed"] = True
    else:
        probs.append("fundamental.py · `build_feed` پنجرهٔ گذشته را از `past_window` "
                     "نمی‌گیرد — انتخابگرِ ۶/۱۲/۲۴ بی‌اثر می‌مانَد")
    # پنجرهٔ `build` عمداً تا `one_event` بسته می‌شود؛ وگرنه خطوطِ مشترکِ تک‌رویداد
    # می‌توانست خرابیِ `build` را بپوشانَد و جهشِ آزمون بی‌صدا سبز بمانَد.
    breg = _py_region(fsrc, "def build(", "\ndef one_event(")
    if breg and _FW_BUILD_RE.search(breg):
        stats["build"] = True
    else:
        probs.append("fundamental.py · `build` پنجرهٔ گذشته را قطعی نمی‌کند — مقدارِ خامِ "
                     "URL به لایهٔ پایین می‌رود")
    if breg and _FW_ECHO_RE.search(breg):
        stats["echo"] = True
    else:
        probs.append("fundamental.py · پنجرهٔ مؤثرِ گذشته (`past_hours`) در پاسخ نمی‌آید — "
                     "رابط نمی‌فهمد سرور کدام پنجره را سرو کرده")
    if not appsrc:
        probs.append("app.py خوانده نشد — مسیرِ /api/fundamental سنجیده نمی‌شود")
    else:
        rreg = _py_region(appsrc, 'if u.path == "/api/fundamental":', 'if u.path == "/fundamental":')
        if rreg and _FW_ROUTE_RE.search(rreg) and _FW_ROUTE_PASS_RE.search(rreg):
            stats["route"] = True
        else:
            probs.append("app.py · مسیرِ /api/fundamental پارامترِ `past` را نمی‌خواند/"
                         "به `build` نمی‌دهد — انتخابگرِ گذشتهٔ رابط کار نمی‌کند")
    if not fund:
        probs.append("app.py → متنِ FUND_PAGE خوانده نشد — رابطِ پنجره/بجِ زنده سنجیده نمی‌شود")
        return probs, stats
    _segopts = set(_FW_SEG_BTN_RE.findall(fund))
    stats["seg_btns"] = len(_segopts)
    if _FW_SEG_RE.search(fund) is None or len(_segopts) < 3:
        probs.append("app.py · انتخابگرِ «گذشته» (‏#pastSeg با ۶/۱۲/۲۴ ساعت) در فید نیست")
    else:
        stats["seg"] = True
    if _FW_STATE_RE.search(fund) is None:
        probs.append("app.py · حالتِ `pastHours` در فید نیست — انتخابگر به درخواست وصل نمی‌شود")
    else:
        stats["state"] = True
    if _FW_FETCH_RE.search(fund) is None:
        probs.append("app.py · درخواستِ فید پارامترِ `&past=` را نمی‌فرستد — انتخابگرِ گذشته بی‌اثر است")
    else:
        stats["fetch"] = True
    if _FW_TICK_FN_RE.search(fund) is None:
        probs.append("app.py · تابعِ زنده‌سازیِ بج (`tickBadges`) در فید نیست — «N دقیقه پیش» "
                     "فقط با بازخوانیِ کاملِ صفحه تازه می‌شود")
        return probs, stats
    treg = _py_region(fund, "function tickBadges(", "\nasync function load(){")
    if not treg:
        probs.append("app.py · بدنهٔ `tickBadges` پیدا نشد — زنده‌بودنِ بج سنجیده نمی‌شود")
    else:
        if "load()" in treg or "render()" in treg or "fetch(" in treg:
            probs.append("app.py · `tickBadges` فهرست را دوباره می‌سازد/می‌خواند — همان "
                         "«رفرشِ صفحه»ی ناخواسته؛ بج باید فقط متنِ خودش را عوض کند")
        else:
            stats["tick_lean"] = True
        if _FW_TICK_SEL_RE.search(treg) is None:
            probs.append("app.py · تیکِ بج فقط کارت‌های اعلام‌شدهٔ عدددار را هدف نمی‌گیرد "
                         "(‏`#list .cd-badge.past[data-m]`)")
        else:
            stats["tick"] = True
        if _FW_TICK_BASE_RE.search(treg) is None:
            probs.append("app.py · محاسبهٔ «دقیقه‌ها» در تیک به زمانِ خواندنِ فید (T0) گره "
                         "نخورده — ساعتِ اشتباهِ دستگاه کاربر عدد را خراب می‌کند")
    if _FW_DATAM_RE.search(fund) is None:
        probs.append("app.py · `minutes_ago` سرور روی خودِ بج (`data-m`) نمی‌نشیند — تیک "
                     "مبنایی برای شمردن ندارد")
    else:
        stats["datam"] = True
    if _FW_TICK_LOOP_RE.search(fund) is None:
        probs.append("app.py · زمان‌بندِ تیکِ بج (`setInterval(tickBadges, …)`) نیست — بج "
                     "هرگز خودش جلو نمی‌رود")
    else:
        stats["loop"] = True
    lreg = _py_region(fund, "async function load(){", '\n$("#impSeg")')
    if _FW_T0_INIT_RE.search(fund) is None or \
            not (_FW_T0_RE.search(lreg) and _FW_T0_RE.search(fund)):
        probs.append("app.py · `T0` با هر خواندنِ فید به‌روز نمی‌شود — مبناِ تیک کهنه "
                     "می‌مانَد و «N دقیقه پیش» عقب می‌افتد")
    else:
        stats["t0"] = True
    if _FW_FIRSTLOAD_RE.search(fund) is None:
        probs.append("app.py · جای‌گیرِ «در حالِ بارگذاری» در هر بازخوانی فهرست را خالی "
                     "می‌کند — همان حسِ «رفرشِ صفحه» که کاربر گفته بود")
    else:
        stats["firstload"] = True
    if _FW_OPEN_KEEP_RE.search(fund) is None:
        probs.append("app.py · کارتِ بازِ کاربر در رندرِ دوره‌ای حفظ نمی‌شود (openKeys) — "
                     "هر ۶۰ ثانیه کارِ باز بسته می‌شود و مثلِ رفرشِ صفحه حس می‌شود")
    else:
        stats["keep"] = True
    return probs, stats


def feed_flip_problems(root, pages=None):
    """قراردادِ «سوییچِ لحظه‌ایِ اعلام» (خواستهٔ کاربر).

    زنجیره‌ای که باید سالم بماند:
      ۱) سرور ثانیه‌های **دقیقِ** باقی‌مانده (`in_s`) را می‌دهد — تنها لنگرِ
         درست برای این‌که کارت در لحظهٔ صفر سوییچ کند و نه با گِردکردنِ ساعتی؛
      ۲) برای یک کارت فقط «همان یک رویداد» پرسیده می‌شود (`?event=` +
         `one_event`) نه فهرستِ کل — یعنی بدونِ بازخوانیِ صفحه/فهرست؛
      ۳) سوییچ فقط وقتی انجام می‌شود که سرور بگوید `passed` (اعلامِ زودرس
         ممنوع)؛ سوییچ درجا روی همان کارت است (نه `render()`ِ کامل)؛
      ۴) تا نیامدنِ عدد، ردیفِ صادقِ انتظار می‌مانَد و پرسش با یک **سقف**
         تکرار می‌شود (نه چرخهٔ بی‌پایان، نه نتیجهٔ ساختگی) — و با رسیدنِ عدد
         تکرار متوقف می‌شود؛
      ۵) «نزدیک‌ترین خبرِ پرتأثیر» و مبنای «N دقیقه پیش» همان لحظه تازه می‌شوند
         تا کارتِ سوییچ‌شده با عددِ کهنه یا کادرِ اشاره به خبرِ گذشته نمانَد.
    """
    probs = []
    stats = {"ins": False, "one_event": False, "route": False, "tick": False,
             "flip_fn": False, "patch_fn": False, "event_url": False,
             "early": False, "retry": False, "patch_only": False, "next": False,
             "datas": False, "fresh_base": False, "num_mult": False,
             "data_sync": False, "num_exact": False, "ins_read": False,
             "rekey": False}
    fsrc = read_text(os.path.join(root, "fundamental.py")) or ""
    appsrc = read_text(os.path.join(root, "app.py")) or ""
    fund = (pages or {}).get("FUND_PAGE") or ""
    if not fsrc:
        probs.append("fundamental.py خوانده نشد — سوییچِ لحظه‌ایِ اعلام سنجیده نمی‌شود")
        return probs, stats
    freg = _py_region(fsrc, "def build_feed", "_VERDICT_SKIP_TOKENS")
    if not _FF_INS_RE.search(freg):
        probs.append("fundamental.py · ثانیه‌های دقیقِ باقی‌مانده (`in_s`) در بارِ رویدادِ "
                     "پیشِ‌رو نیست — رابط نمی‌تواند لحظهٔ اعلام را دقیق بگیرد")
    else:
        stats["ins"] = True
    if _FF_ONEEV_RE.search(fsrc) is None:
        probs.append("fundamental.py · `one_event` (بارِ یک رویداد برای سوییچِ لحظه‌ای) "
                     "حذف شده — برای یک کارت باید فهرستِ کل خوانده شود")
        return probs, stats
    oreg = _py_region(fsrc, "def one_event", "\nif __name__")
    if _FF_ONEEV_EVENT_RE.search(oreg) and _FF_ONEEV_NEXT_RE.search(oreg) \
            and _FF_ONEEV_FEED_RE.search(oreg):
        stats["one_event"] = True
    else:
        probs.append("fundamental.py · `one_event` بارِ رویداد/نزدیک‌ترین خبر را "
                     "از مسیرِ `build_feed` نمی‌دهد — سوییچِ لحظه‌ای دوباره‌کاری می‌کند")
    if not appsrc:
        probs.append("app.py خوانده نشد — مسیرِ تک‌رویداد سنجیده نمی‌شود")
    else:
        rreg = _py_region(appsrc, 'if u.path == "/api/fundamental":', 'if u.path == "/fundamental":')
        if _FF_ROUTE_RE.search(rreg) and "FUND.one_event(" in rreg:
            stats["route"] = True
        else:
            probs.append("app.py · مسیرِ /api/fundamental پارامترِ `event` را نمی‌خواند/"
                         "به `one_event` نمی‌دهد — سوییچِ لحظه‌ای جوابی نمی‌گیرد")
    if not fund:
        probs.append("app.py → متنِ FUND_PAGE خوانده نشد — سوییچِ لحظه‌ای در رابط سنجیده نمی‌شود")
        return probs, stats
    if _FF_DATAS_RE.search(fund) is None:
        probs.append("app.py · `in_s` روی بجِ کارتِ پیشِ‌رو (`data-in-s`) نمی‌نشیند — تیک "
                     "لنگرِ ثانیه‌ای ندارد")
    else:
        stats["datas"] = True
    stats["ins_read"] = bool(_FF_INS_READ_RE.search(fund)) and not _FF_INS_BAD_RE.search(fund)
    treg = _py_region(fund, "function tickBadges(", "\nasync function load(){")
    if _FF_TICK_CALL_RE.search(treg) and "fetch(" not in treg \
            and _FF_INS_READ_RE.search(treg):
        stats["tick"] = True
    else:
        probs.append("app.py · تیکِ ۳۰ثانیه‌ای در لحظهٔ صفر سوییچ نمی‌کند (یا خودش "
                     "شبکه می‌زند/لنگرِ ثانیه‌ای را نمی‌خواند) — کارتِ پیشِ‌رو تا "
                     "پنجرهٔ ۶۰ثانیه‌ای کهنه می‌مانَد")
    if _FF_INS_BAD_RE.search(fund):
        probs.append("app.py · لنگرِ ثانیه‌ای با کلیدِ اشتباهِ dataset خوانده می‌شود "
                     "(`dataset.in_s` وجود ندارد؛ `inS` درست است) — عدد `undefined` "
                     "می‌شود و همهٔ کارت‌های پیشِ‌رو فوراً «رسیده» حساب می‌شوند")
    if _FF_FLIP_FN_RE.search(fund) is None:
        probs.append("app.py · تابعِ سوییچِ لحظه‌ای (`flipEvent`) در فید نیست")
        return probs, stats
    freg2 = _py_region(fund, "async function flipEvent(", "\nfunction patchEvent(")
    if _FF_EVENT_URL_RE.search(freg2):
        stats["flip_fn"] = True
    else:
        probs.append("app.py · `flipEvent` تک‌رویداد (`?event=`) را نمی‌پرسد — می‌خواهد "
                     "کلِ فهرست را بخواند")
    stats["event_url"] = bool(_FF_EVENT_URL_RE.search(freg2))
    if _FF_EARLY_RE.search(freg2) is None:
        probs.append("app.py · گاردِ «هنوز اعلام نشده» در `flipEvent` نیست — اگر ساعتِ "
                     "مرورگر جلو باشد، کارت زودرس «اعلام شد» می‌شود")
    else:
        stats["early"] = True
    m = _FF_RETRY_MAX_RE.search(fund)
    if m and _FF_RETRY_USE_RE.search(freg2) and _FF_RETRY_STOP_RE.search(freg2) \
            and _FF_RETRY_SCHED_RE.search(freg2) and _FF_FOUND_RE.search(freg2) \
            and int(m.group(1)) > 0:
        stats["retry"] = True
    else:
        probs.append("app.py · تکرارِ پرسشِ عددِ اعلام‌شده سقف/شرطِ توقف ندارد — یا "
                     "بی‌سقف می‌پرسد یا بعد از رسیدنِ عدد ادامه می‌دهد")
    if _FF_NEXT_SYNC_RE.search(freg2) is None or _FF_NEXT_FN_RE.search(fund) is None \
            or _FF_NEXT_USE_RE.search(freg2) is None:
        probs.append("app.py · «نزدیک‌ترین خبرِ پرتأثیر» بعد از سوییچ تازه نمی‌شود — "
                     "کادر به خبرِ اعلام‌شده اشاره می‌کند")
    else:
        stats["next"] = True
    if _FF_PATCH_FN_RE.search(fund) is None:
        probs.append("app.py · تابعِ سوییچِ درجا (`patchEvent`) در فید نیست")
        return probs, stats
    preg = _py_region(fund, "function patchEvent(", "\n$(")
    if _FF_PATCH_ONLY_RE.search(preg) and "render()" not in preg:
        stats["patch_only"] = True
    else:
        probs.append("app.py · سوییچِ کارت کلِ فهرست را بازمی‌سازد (`render()` در "
                     "`patchEvent`) — همان حسِ رفرشِ صفحه")
    stats["patch_fn"] = _FF_PATCH_FN_RE.search(fund) is not None
    if _FF_REKEY_RE.search(preg) and _FF_REKEY_CARD_RE.search(preg) \
            and _FF_RETRY_SCHED_RE.search(freg2):
        stats["rekey"] = True
    else:
        probs.append("app.py · وقتی منبع عنوانِ رویداد را عوض کند کلیدِ کارت عوض می‌شود — "
                     "بدونِ دنبال‌کردنِ کلیدِ تازه، کارت گم/سطرِ DATA تکراری می‌مانَد")
    if _FF_DATA_SYNC_RE.search(preg) is None:
        probs.append("app.py · ردیفِ همان رویداد در `DATA.events` به‌روز نمی‌شود — رندرِ "
                     "بعدیِ فهرست کارتِ سوییچ‌شده را به حالتِ پیشِ‌رو برمی‌گرداند")
    else:
        stats["data_sync"] = True
    if _FF_FRESH_BASE_RE.search(preg) is None:
        probs.append("app.py · مبنای «N دقیقه پیش»ِ کارتِ سوییچ‌شده تازه نمی‌شود — "
                     "عددِ بج از T0ِ قبلی جلو می‌زند")
    else:
        stats["fresh_base"] = True
    # عددِ اعلام‌شده در منبع به‌شکلِ «195K»/«1.2M» هم می‌آید؛ اگر خوانندهٔ عدد
    # پسوندِ مقیاس را نفهمد، کارتِ سوییچ‌شده همیشه «عدد در دسترس نیست» می‌مانَد
    # (دقیقاً همان چیزی که این سوییچ برای رفعش ساخته شده).
    nreg = _py_region(fsrc, "def _num(", "\ndef _realized_effect")
    if _FF_NUM_MULT_RE.search(fsrc) and _FF_NUM_USE_RE.search(nreg) \
            and _FF_NUM_EMPTY_RE.search(nreg):
        stats["num_mult"] = True
    else:
        probs.append("fundamental.py · خوانندهٔ عدد پسوندِ مقیاس (K/M/B/T) را نمی‌فهمد "
                     "— «195K» حکمِ «عدد در دسترس نیست» می‌گیرد و کارتِ اعلام‌شده هیچ‌وقت "
                     "نتیجه نمی‌دهد")
    if _FF_NUM_EXACT_RE.search(nreg) is None:
        probs.append("fundamental.py · نشانهٔ «داده نداریم» زیررشته‌ای سنجیده می‌شود — "
                     "همهٔ عددهای منفی («-2.5%») هم «نامعلوم» می‌شوند و آن خبر نتیجه "
                     "نمی‌گیرد")
    else:
        stats["num_exact"] = True
    return probs, stats


def button_alive_problems(root, pages=None):
    """قراردادِ «کلیدِ بی‌واکنش نداریم»: هر کلیدی که تبِ نو باز می‌کند تورِ ایمنیِ
    «همین‌تب» داشته باشد، و پیامِ «کاری نبود» فقط sr-only نباشد."""
    probs = []
    stats = {"newtab": 0, "fund_guard": False, "fund_fallback": False,
             "rf_visible": False, "rf_flash": False}
    page = (pages or {}).get("HTML") or ""
    if not page:
        probs.append("app.py → متنِ APP_PAGE خوانده نشد — کلیدها سنجیده نمی‌شوند")
        return probs, stats

    stats["newtab"] = len(_NEWTAB_OPEN_RE.findall(page))
    m = _FUND_HANDLER_RE.search(page)
    if m is None:
        probs.append("app.py · کلیدِ فاندمنتال (fundBtn) اصلاً هندلر ندارد — "
                     "کلیک هیچ کاری نمی‌کند")
    else:
        blk = m.group(1)
        has_newtab = _NEWTAB_OPEN_RE.search(blk) is not None
        if not has_newtab and _FUND_SAME_TAB_RE.search(blk) is None:
            probs.append("app.py · هندلرِ فاندمنتال هیچ ناوبری‌ای به صفحهٔ فاندمنتال "
                         "ندارد — کلید بی‌اثر است")
        if has_newtab and _FUND_NULL_GUARD_RE.search(blk) is None:
            probs.append("app.py · هندلرِ فاندمنتال نتیجهٔ window.open را نمی‌سنجد — "
                         "با پاپ‌آپ‌بلاکر یا نصبِ PWA کلید بی‌صدا می‌مُرد")
        elif has_newtab:
            stats["fund_guard"] = True
        if _FUND_SAME_TAB_RE.search(blk) is None:
            probs.append("app.py · کلیدِ فاندمنتال تورِ ایمنیِ «همین‌تب» ندارد "
                         "(location.assign(\"/fundamental\")) — در نصبِ PWA کلید از کار می‌افتد")
        else:
            stats["fund_fallback"] = True

    if _RF_HINT_DOM_RE.search(page) is None:
        probs.append("app.py · پیامِ دیدنیِ «چیزی برای بروزرسانی نیست» (rf-hint) حذف شده — "
                     "کلید در این حالت بی‌واکنش به‌نظر می‌رسد")
    else:
        stats["rf_visible"] = True
    if _RF_NEED_JS_RE.search(page) is None or _RF_NEED_CSS_RE.search(page) is None:
        probs.append("app.py · کلیدِ بروزرسانی در حالتِ «کاری نبود» هیچ واکنشِ دیدنی‌ای روی "
                     "خودش ندارد (کلاسِ need در JS/CSS) — کلیک بی‌پاسخ می‌مانَد")
    else:
        stats["rf_flash"] = True
    return probs, stats


def gap_query_problems(root, pages=None):
    """قراردادِ «پرسشِ تأییدِ شکافِ ارزش منصفانه» (لایهٔ ۴.۲۳).

    خواستهٔ کاربر: «آدرسِ گپ را در یک تایم‌فریمِ مشخص می‌دهم و اپ می‌گوید تأییدِ
    همان گپ چقدر است و می‌شود به آن اتکا کرد یا نه.» یعنی رابط یک *پرسش* است،
    نه فهرستِ خام. پنج چیز باید قفل بمانَد، وگرنه پرسش بی‌جواب می‌مانَد یا
    حکمِ دروغ می‌دهد:
      ۱) پویشِ گپ گیتِ دیسپلیسمنت ندارد (وگرنه گپِ کم‌جان پیش از تطبیق حذف
         می‌شود و آدرسِ درستِ کاربر «پیدا نشد» می‌گیرد)؛
      ۲) آستانه‌های تأیید سرجایشان‌اند و مقدارشان معقول است؛
      ۳) همهٔ دوازده بندِ امتیازِ تأیید حاضرند؛
      ۴) فقط A+/A «قابلِ اتکا» شمرده می‌شوند؛
      ۵) اندپوینت + پنلِ کرکره‌ایِ پرسش (آدرس lo/hi، تایم‌فریم و حالتِ فهرست).
    """
    probs, stats = [], {"file": False, "no_scan_gate": False, "consts": False,
                        "criteria": 0, "reliable": False, "import": False,
                        "route": False, "ids": 0, "fold": False, "modes": 0,
                        "ask_addr": False, "reliable_ui": False}
    gq_src = read_text(os.path.join(root, "gap_query.py"))
    if not gq_src:
        probs.append("gap_query.py پیدا نشد — پرسشِ تأییدِ گپ اصلاً موتور ندارد")
        return probs, stats
    stats["file"] = True

    # ۱) پویشِ گپ باید *بی‌گیت* باشد.
    scan = _py_region(gq_src, "def gap_scan(", "def _overlap(")
    if not scan:
        probs.append("gap_query.py · تابعِ gap_scan پیدا نشد — پویشِ گپ سنجیده نمی‌شود")
    elif _GQ_SCAN_GATE_RE.search(scan):
        probs.append("gap_query.py · پویشِ gap_scan گیتِ دیسپلیسمنت گرفت — گپِ کم‌جان "
                     "پیش از تطبیق حذف می‌شود و آدرسِ درستِ کاربر «پیدا نشد» می‌گیرد")
    else:
        stats["no_scan_gate"] = True

    # ۲) ثابت‌های تأیید.
    m_gate = _GQ_DISP_GATE_RE.search(gq_src)
    m_strong = _GQ_DISP_STRONG_RE.search(gq_src)
    m_match = _GQ_MATCH_MIN_RE.search(gq_src)
    cbad = []
    if m_gate is None or m_strong is None or m_match is None:
        cbad.append("ثابت‌های DISP_GATE/DISP_STRONG/MATCH_MIN_OVERLAP ناقص‌اند")
    else:
        gate, strong, match = (float(m_gate.group(1)), float(m_strong.group(1)),
                               float(m_match.group(1)))
        if not (1.0 <= gate <= 2.0):
            cbad.append("گیتِ دیسپلیسمنت از بازهٔ معقول بیرون است (%s)" % gate)
        if strong <= gate:
            cbad.append("آستانهٔ دیسپلیسمنتِ قوی (%s) بزرگ‌تر از گیتِ پایه (%s) نیست" % (strong, gate))
        if not (0 < match <= 1):
            cbad.append("آستانهٔ هم‌پوشانیِ تطبیق بیرونِ بازهٔ (۰،۱] است (%s)" % match)
    if cbad:
        probs.append("gap_query.py · " + "؛ ".join(cbad) + " — آستانه‌های تأیید مبنا ندارند")
    else:
        stats["consts"] = True

    # ۳) دوازده بندِ امتیازِ تأیید.
    verdict = _py_region(gq_src, "def gap_verdict(", "def load(")
    if not verdict:
        probs.append("gap_query.py · حکمِ gap_verdict پیدا نشد — پرسش حکم نمی‌دهد")
    else:
        missing = [a for a in _GQ_CRITERIA if a not in verdict]
        rows = len(_GQ_ROW_RE.findall(verdict))
        stats["criteria"] = len(_GQ_CRITERIA) - len(missing)
        if missing:
            probs.append("gap_query.py · %d بندِ امتیازِ تأیید از حکم افتاده (%s) — حکمِ "
                         "بی‌سندِ خوش‌بینانه می‌شود" % (len(missing), "، ".join(missing)))
        if rows < len(_GQ_CRITERIA):
            probs.append("gap_query.py · حکم فقط %d ردیفِ امتیاز می‌سازد (دست‌کم %d لازم است) "
                         "— معیارِ خاموش‌حذف‌شده" % (rows, len(_GQ_CRITERIA)))

    # ۴) درجه‌های «قابلِ اتکا».
    m_rel = _GQ_RELIABLE_RE.search(gq_src)
    if m_rel is None:
        probs.append("gap_query.py · فهرستِ درجه‌های قابلِ اتکا (RELIABLE_GRADES) پیدا نشد")
    else:
        rels = re.findall(r'"([^"]+)"', m_rel.group(1))
        if "A+" not in rels or "A" not in rels:
            probs.append("gap_query.py · درجه‌های قابلِ اتکا A+ و A را شامل نمی‌شوند — "
                         "گپِ پرتأیید «غیرقابلِ اتکا» خوانده می‌شود")
        elif any(g in rels for g in ("B", "C", "D")):
            probs.append("gap_query.py · درجه‌های میانی به فهرستِ قابلِ اتکا راه پیدا کردند "
                         "(%s) — اتکا بی‌سند می‌شود" % "، ".join(rels))
        else:
            stats["reliable"] = True

    # ۵) سیم‌کشیِ اندپوینت و پنلِ پرسش.
    app_src = read_text(os.path.join(root, "app.py"))
    page = (pages or {}).get("HTML") or ""
    if not app_src:
        probs.append("app.py خوانده نشد — اندپوینت و پنلِ پرسش سنجیده نمی‌شوند")
    else:
        if _GQ_IMPORT_RE.search(app_src) is None:
            probs.append("app.py · موتورِ گپ وارد نشده (import gap_query as G) — "
                         "اندپوینتِ پرسش بی‌پاسخ می‌مانَد")
        else:
            stats["import"] = True
        route = _py_region(app_src, 'if u.path == "/api/gap":', 'if u.path == "/api/health":')
        if not route:
            probs.append("app.py · مسیرِ /api/gap پیدا نشد — پنلِ پرسش بی‌پاسخ می‌مانَد")
        elif "G.query(" not in route:
            probs.append("app.py · مسیرِ /api/gap موتورِ گپ (G.query) را صدا نمی‌زند")
        else:
            stats["route"] = True

    if not page:
        probs.append("app.py · متنِ صفحهٔ اصلی خوانده نشد — پنلِ پرسش سنجیده نمی‌شود")
        return probs, stats
    miss_ids = [i for i in _GQ_PANEL_IDS if ('id="%s"' % i) not in page]
    stats["ids"] = len(_GQ_PANEL_IDS) - len(miss_ids)
    if miss_ids:
        probs.append("app.py · شناسه‌های پنلِ پرسشِ گپ غایب‌اند: " + "، ".join(miss_ids))
    if _GQ_FOLD_CALL_RE.search(page) is None:
        probs.append("app.py · پنلِ پرسشِ گپ به مکانیکِ کرکره وصل نیست "
                     "(pfFold(\"gapDock\",\"gapToggle\",\"gapBody\")) — همیشه‌باز می‌مانَد")
    else:
        stats["fold"] = True
    modes = int(_GQ_MODE_FALSE_RE.search(page) is not None) + \
        int(_GQ_MODE_TRUE_RE.search(page) is not None)
    stats["modes"] = modes
    if modes < 2:
        probs.append("app.py · هر دو حالتِ پرسش (آدرس‌دار و «گپ‌های همین تایم‌فریم») "
                     "سیم‌کشی نشده‌اند — یکی از دو مسیرِ پرسش مرده است")
    if _GQ_SEND_LO_RE.search(page) is None or _GQ_SEND_HI_RE.search(page) is None:
        probs.append("app.py · پنلِ پرسش آدرس (lo/hi) را به سرور نمی‌فرستد — پرسش همیشه "
                     "به حالتِ فهرست می‌افتد")
    else:
        stats["ask_addr"] = True
    if _GQ_RELIABLE_UI_RE.search(page) is None:
        probs.append("app.py · حکمِ «قابلِ اتکا» (g.reliable) در پنل رندر نمی‌شود — "
                     "کاربر نمی‌فهمد می‌شود به گپ اتکا کرد یا نه")
    else:
        stats["reliable_ui"] = True
    greg = _py_region(page, _GQ_CARD_START, _GQ_CARD_END)
    if not greg:
        probs.append("app.py · سازندهٔ کارتِ گپ (gapCardHtml) پیدا نشد — "
                     "رندرِ حکم سنجیده نمی‌شود")
    else:
        badv = sorted(set(_GQ_BARE_V_RE.findall(greg)))
        if badv:
            probs.append("app.py · کارتِ گپ به متغیرِ `v` برمی‌گردد (%s) — "
                         "هم نشانگرِ رندرِ آرشیو را کور می‌کند و هم در مرورگر "
                         "`v is not defined` می‌دهد (کارتِ خالی)"
                         % "، ".join(badv[:3]))
        else:
            stats["prefix"] = True
    return probs, stats


def read_baseline(root=None):
    """مبنای «نسخه‌ی سالم» → (inventory, منبع).
    اول اسنپ‌شاتِ همین ماشین (~/pipfound/good)، بعد فایلِ نسخه‌بندی‌شده‌ی
    ریپو (selfcheck-baseline.json)؛ اگر هیچ‌کدام نبود، (None, None)."""
    fp = os.path.join(GOOD, "inventory.json")
    try:
        with open(fp, encoding="utf-8") as f:
            return json.load(f), "snapshot"
    except Exception:
        pass
    if root:
        try:
            with open(os.path.join(root, REPO_BASELINE_NAME), encoding="utf-8") as f:
                return json.load(f), "repo"
        except Exception:
            pass
    return None, None


def write_repo_baseline(root, rep=None):
    """مبنای کلیدها/مسیرها را در فایلِ نسخه‌بندی‌شده‌ی ریپو می‌نویسد (برای CI)."""
    try:
        inv = dict(((rep or {}).get("inventory") or inventory(page_sources(root))))
        inv["routes"] = inv.get("routes") or routes_of(root)
        inv["saved_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        inv["note"] = ("مبنای «هیچ کلیدی گم نشود» — با "
                       "python3 selfcheck.py --snapshot بازتعریف می‌شود")
        fp = os.path.join(root, REPO_BASELINE_NAME)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(inv, f, ensure_ascii=False, indent=2, sort_keys=True)
        _log(f"BASELINE → {fp} (ids={len(inv.get('ids') or [])}, routes={len(inv.get('routes') or [])})")
        return fp
    except Exception as e:
        _log(f"BASELINE FAILED: {e}")
        return None


def live_problems(port=PORT):
    """اندپوینت‌های سرورِ در حالِ اجرا را صدا می‌زند."""
    probs, base = [], f"http://127.0.0.1:{port}"
    for path in LIVE_PATHS:
        try:
            req = urllib.request.Request(base + path, headers={"User-Agent": "pipfound-selfcheck"})
            with urllib.request.urlopen(req, timeout=30) as r:
                code, body = r.getcode(), r.read(400000)
            if code != 200:
                probs.append(f"{path}: HTTP {code}")
            if path == "/":
                for need in ("refreshBtn", "archiveBtn", "fundBtn", "sbBtn", "setupsBtn"):
                    if f'id="{need}"'.encode() not in body:
                        probs.append(f"/: دکمه‌ی «{need}» در صفحه‌ی سرو‌شده نیست")
        except Exception as e:
            probs.append(f"{path}: {e}")
    return probs


# ─────────────────────────── اجرای کلِ چک ───────────────────────────
def run_checks(root, live=False, enforce_contract=True, accept_removals=False):
    rep = {"ok": True, "root": root, "problems": [], "warnings": [],
           "engine": os.path.basename(js_engine() or "-")}
    pages = page_sources(root)
    py = py_syntax_problems(root)
    rep["problems"] += [f"پایتون → {p}" for p in py]
    if not pages:
        rep["problems"].append("app.py → متنِ صفحه‌های HTML/FUND_PAGE خوانده نشد")
    js, checked = js_syntax_problems(pages) if pages else ([], True)
    if not checked:
        rep["warnings"] += js
    else:
        rep["problems"] += [f"جاوااسکریپت → {p}" for p in js]

    # ── چکِ استاتیکِ دامنه: «صدا زده شده ولی تعریف نشده» ──
    # همان شکافی که node --check (فقط سینتکس) نمی‌بیند و سرِ اجرا به
    # ReferenceError ختم می‌شود. اگر جایی مثبتِ کاذب دیدی، نام را به JS_GLOBALS اضافه کن.
    uc, ustats = undefined_calls(pages) if pages else ([], {})
    rep["static"] = ustats
    rep["problems"] += [f"جاوااسکریپت → {p}" for p in uc]

    # ── چکِ استاتیکِ اتصالِ HTML و JS (شناسه‌ها، هندلرها، استفاده‌نشده‌ها) ──
    # خطاها گیت را قرمز می‌کنند؛ «استفاده‌نشده»‌ها فقط هشدارند (کدِ مرده).
    # دارایی‌های وبِ بیرون (هارنسِ بصری/سرویس‌ورکر) هم خوانده می‌شوند تا نامی که
    # آن‌ها پین کرده‌اند «کدِ مرده» شمرده نشود (وگرنه هشدار، پاک‌کردنِ لنگرِ زنده
    # را توصیه می‌کرد و لایهٔ ۳ می‌شکست).
    ctext, cnames = consumer_assets(root)
    wp, ww, wstats = wiring_problems(pages, ctext) if pages else ([], [], {})
    wstats["assets"] = cnames
    rep["wiring"] = wstats
    rep["problems"] += [f"اتصالِ HTML/JS → {p}" for p in wp]
    rep["warnings"] += [f"اتصالِ HTML/JS → {w}" for w in ww]

    # ── چکِ استاتیکِ قراردادِ PWA (سرویس‌ورکر ↔ مانیفست ↔ اپ) ──
    # نه سینتکسِ sw.js را جایی می‌سنجید و نه وعده‌های مانیفست/پوستهٔ کش را با
    # مسیرهای واقعیِ سرور مقابله می‌کرد: آیکونِ ناموجود، مسیرِ سرو‌نشده در
    # پوستهٔ کش، `addAll(نامِ غلط)` و پاسخِ ناموفقِ کش‌شده — همه بی‌صدا نصب یا
    # حالتِ آفلاین را می‌شکنند و هیچ لایه‌ای قرمز نمی‌شد.
    pw, pn, pstats = pwa_contract_problems(root)
    rep["pwa"] = pstats
    rep["problems"] += [f"PWA → {p}" for p in pw]
    rep["warnings"] += [f"PWA → {p}" for p in pn]

    # ── چکِ استاتیکِ انتقالِ دادهٔ کاربر (برون‌بری/درون‌بریِ ژورنال/آلارم/تنظیمات) ──
    # پشتیبانِ ناقص یا درون‌بریِ بی‌اعتبارسنجی فقط سرِ «دستگاهِ تازه» معلوم می‌شود؛
    # این قاعده همان‌جا جلوی بی‌صدا شدن را می‌گیرد.
    bkp, bstats = backup_problems(root, pages)
    rep["backup"] = bstats
    rep["problems"] += [f"پشتیبان → {p}" for p in bkp]

    # ── چکِ استاتیکِ پشتیبانِ خودکارِ زمان‌بندی‌شده ──
    # زمان‌بندیِ روشن ولی مرده، هرسِ فایلِ اشتباهی، یا اسنپ‌شاتِ غیرِاتمیک همه
    # بی‌صدا هستند تا روزی که به پشتیبان نیاز شود؛ این قاعده همان‌جا می‌گیردش.
    abp, abstats = autobackup_problems(root, pages)
    rep["autobackup"] = abstats
    rep["problems"] += [f"پشتیبانِ خودکار → {p}" for p in abp]

    # ── چکِ استاتیکِ «خفه‌بودنِ نوتیفیکیشن در تست‌ها و CI» ──
    # اپ سرِ بوت آلارمِ فاندمنتال را می‌سنجد؛ بدونِ این قاعده هر تست/هارنس/گامِ
    # تازه‌ای که آن را بالا بیاورد بی‌صدا روی دسکتاپِ کاربر نوتیف می‌فرستد.
    ntp, ntstats = notify_problems(root, pages)
    rep["notify"] = ntstats
    rep["problems"] += [f"نوتیفیکیشنِ تست‌ها → {p}" for p in ntp]

    # ── چکِ استاتیکِ «آرشیو: نتیجهٔ قطعی، نه گزارهٔ شرطی» ──
    # تقاضای کاربر: بعد از اعلامِ خبر، آرشیو باید عددِ Actual و صعودی/نزولی را
    # مطلق بگوید؛ اگر گیرنده/حکم/رندر شکسته شود، بی‌صدا به شرطیِ قدیمی برمی‌گردد.
    arp, arstats = archive_problems(root, pages)
    rep["archive"] = arstats
    rep["problems"] += [f"آرشیوِ اقتصادی → {p}" for p in arp]

    # ── چکِ استاتیکِ «سوییچِ خودکارِ فید بعد از اعلام» ──
    # خواستهٔ کاربر: فیدِ پیش‌رو بعد از اعلامِ عدد خودکار به «نتیجه + تأثیر»
    # سوییچ کند، نه دو سناریوی همیشگی. اگر کسی مسیرِ `passed` یا تزریقِ حکم را
    # بردارد، همین‌جا گرفته می‌شود (پیش از آنکه کاربر دوباره بگوید «چرا باز
    # «اگر» نشان می‌دهد؟»).
    fsp, fsstats = feed_switch_problems(root, pages)
    rep["feed"] = fsstats
    rep["problems"] += [f"فیدِ خبرهای پیش‌رو → {p}" for p in fsp]

    # ── چکِ استاتیکِ «پنجرهٔ گذشته + بجِ زندهٔ اعلام» ──
    # خواستهٔ کاربر: بجِ «N دقیقه پیش» بدونِ رفرشِ کلِ صفحه زنده باشد و پنجرهٔ
    # گذشتهٔ فید با انتخابگرِ ۶/۱۲/۲۴ ساعت عوض شود. اگر کسی تیکِ سبک را با
    # بازخوانیِ کامل عوض کند یا انتخابگر را از درخواست جدا کند، همین‌جا گرفته
    # می‌شود (نه روزی که کاربر دوباره بگوید «باز هم صفحه رفرش می‌شود»).
    fwp, fwstats = feed_window_problems(root, pages)
    rep["feedwin"] = fwstats
    rep["problems"] += [f"فیدِ زندهٔ خبرهای پیش‌رو → {p}" for p in fwp]

    # ── چکِ استاتیکِ «سوییچِ لحظه‌ایِ اعلام» ──
    # خواستهٔ کاربر: کارتِ پیشِ‌رو دقیقاً در لحظهٔ صفر شدنِ شمارشِ معکوس بدونِ
    # رفرش به «اعلام شد + نتیجه» سوییچ کند. اگر کسی لنگرِ ثانیه‌ای، مسیرِ
    # تک‌رویداد، گاردِ اعلامِ زودرس یا سقفِ تکرار را بردارد، همین‌جا گرفته
    # می‌شود (نه روزی که کاربر بگوید «باز یک دقیقه کهنه می‌مانَد»).
    flp, flstats = feed_flip_problems(root, pages)
    rep["feedflip"] = flstats
    rep["problems"] += [f"سوییچِ لحظه‌ایِ اعلام → {p}" for p in flp]

    # ── چکِ استاتیکِ «کلیدِ بی‌واکنش نداریم» ──
    # شکایتِ کاربر («کلیدا از کار افتادن»): کلیدِ تبِ نو و پیامِ sr-only دو
    # بی‌صداییِ واقعی‌اند؛ اگر کسی تورِ ایمنی/واکنشِ دیدنی را بردارد این قاعده
    # همان‌جا می‌گیرد (نه روزی که کاربر دوباره بگوید «کلیک می‌کنم هیچی نمی‌شود»).
    bap, bastats = button_alive_problems(root, pages)
    rep["buttons"] = bastats
    rep["problems"] += [f"کلیدهای بی‌واکنش → {p}" for p in bap]

    # ── چکِ استاتیکِ «کرکره‌های جمعِ پیش‌فرض» ──
    # خواستهٔ کاربر: بخش‌های نگهداریِ نمای اصلی (آلارم‌ها، تنظیماتِ بک‌تست،
    # مدیریتِ ریسک و پشتیبانِ داده) فقط یک نوار باشند و با کلیک باز شوند. اگر کسی
    # بدنه را همیشه‌باز کند یا سیم‌کشی/aria را بردارد، همین‌جا گرفته می‌شود.
    fpp, fstats = fold_panels_problems(root, pages)
    rep["dock"] = fstats
    rep["problems"] += [f"کرکره‌های نمای اصلی → {p}" for p in fpp]

    # ── چکِ استاتیکِ «پرسشِ تأییدِ شکافِ ارزش منصفانه» ──
    # خواستهٔ کاربر: کاربر آدرسِ یک گپ را در تایم‌فریمِ مشخص می‌دهد و اپ باید
    # بگوید تأییدِ همان گپ چقدر است و می‌شود به آن اتکا کرد یا نه. اگر کسی گیتِ
    # دیسپلیسمنت را به پویش برگرداند (پرسش «پیدا نشد» می‌گیرد)، یک بندِ امتیاز
    # را خاموش حذف کند، یا درجه‌های میانی را «قابلِ اتکا» کند، همین‌جا گرفته
    # می‌شود (نه روزی که کاربر بگوید «به گپِ بی‌کیفیت اتکا کردم و ضرر کردم»).
    gqp, gqstats = gap_query_problems(root, pages)
    rep["gapq"] = gqstats
    rep["problems"] += [f"پرسشِ شکافِ ارزش منصفانه → {p}" for p in gqp]

    inv = inventory(pages)
    inv["routes"] = routes_of(root)
    rep["inventory"] = inv

    # ── قراردادِ «هیچ کلیدی گم نشود» ──
    # مبنای مقایسه، آخرین نسخه‌ی سالم است (نه یک فهرستِ ابدی)؛ پس اگر عمداً
    # دکمه‌ای را برداشتی، با یک بار --accept-removals مبنای تازه ثبت می‌شود.
    # فهرستِ REQUIRED_IDS فقط وقتی بکار می‌آید که هنوز هیچ اسنپ‌شاتی نباشد
    # (کلونِ تازه / اولین اجرا).
    snap, snap_src = read_baseline(root)
    rep["baseline"] = snap_src
    missing = [i for i in REQUIRED_IDS if i not in inv["ids"]]

    if accept_removals:
        if missing:
            rep["warnings"].append("کنترل‌های غایب (پذیرفته‌شده با --accept-removals): " + "، ".join(missing))
    elif snap and enforce_contract:
        lost_wired = sorted(set(snap.get("wired", [])) - set(inv["ids"]))
        lost_routes = sorted(set(snap.get("routes", [])) - set(inv["routes"]))
        if lost_wired:
            rep["problems"].append("کنترل‌هایی که در نسخه‌ی سالم بود و الان نیست: "
                                   + "، ".join(lost_wired))
        if lost_routes:
            rep["problems"].append("مسیرهایی که در نسخه‌ی سالم بود و الان نیست: "
                                   + "، ".join(lost_routes))
    else:
        if missing:
            rep["problems"].append("کنترل‌های غایب در صفحه: " + "، ".join(missing))
        if not snap:
            rep["warnings"].append("مبنای مقایسه (اسنپ‌شات/فایلِ مبنا) موجود نیست — با --snapshot ساخته می‌شود")

    if live:
        lp = live_problems()
        rep["live"] = lp
        rep["problems"] += [f"سرور → {p}" for p in lp]

    rep["ok"] = not rep["problems"]
    return rep


# ─────────────────────────── اسنپ‌شات و بازگردانی ───────────────────────────
def save_snapshot(root, rep=None):
    """نسخه‌ی سالمِ فعلی را ذخیره می‌کند (نسخه‌ی قبلی به good_prev می‌رود)."""
    try:
        if os.path.isdir(GOOD):
            shutil.rmtree(PREV, ignore_errors=True)
            shutil.move(GOOD, PREV)
        os.makedirs(GOOD, exist_ok=True)
        for name in TRACKED:
            src = os.path.join(root, name)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(GOOD, name))
        inv = (rep or {}).get("inventory") or inventory(page_sources(root))
        inv = dict(inv)
        inv["routes"] = inv.get("routes") or routes_of(root)
        inv["saved_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        with open(os.path.join(GOOD, "inventory.json"), "w", encoding="utf-8") as f:
            json.dump(inv, f, ensure_ascii=False, indent=2)
        _log(f"SNAPSHOT → {GOOD} (ids={len(inv.get('ids') or [])}, routes={len(inv.get('routes') or [])})")
        return GOOD
    except Exception as e:
        _log(f"SNAPSHOT FAILED: {e}")
        return None


def restore_snapshot(root, where=GOOD):
    """فایل‌های نسخه‌ی سالم را روی نسخه‌ی فعلی برمی‌گرداند."""
    if not os.path.isdir(where):
        return None
    restored = []
    for name in TRACKED:
        src = os.path.join(where, name)
        if os.path.isfile(src):
            try:
                shutil.copy2(src, os.path.join(root, name))
                restored.append(name)
            except Exception as e:
                _log(f"RESTORE FAILED {name}: {e}")
    if restored:
        _log(f"RESTORED از {where}: " + "، ".join(restored))
        return where
    return None


def guard(root):
    """چک کن؛ اگر خراب بود نسخه‌ی سالم را برگردان."""
    rep = run_checks(root)
    if rep["ok"]:
        save_snapshot(root, rep)
        _log("GUARD OK — کد سالم است؛ اسنپ‌شات تازه شد")
        return rep
    _log("GUARD FAIL → " + " | ".join(rep["problems"][:4]))
    for where in (GOOD, PREV):
        if restore_snapshot(root, where):
            rep2 = run_checks(root)
            rep2["restored_from"] = where
            if rep2["ok"]:
                _log(f"GUARD HEALED — بازگردانی از {where} موفق بود")
                return rep2
            _log(f"GUARD: بازگردانی از {where} کافی نبود → " + " | ".join(rep2["problems"][:3]))
            rep = rep2
    rep["restored_from"] = None
    return rep


# ─────────────────────────── CLI ───────────────────────────
def _human(rep):
    lines = []
    mark = "🩺 ✅ سالم" if rep.get("ok") else "🩺 ❌ خراب"
    lines.append(f"{mark} — {rep.get('root')} (موتورِ JS: {rep.get('engine')})")
    inv = rep.get("inventory") or {}
    lines.append(f"   کلیدها: {len(inv.get('ids') or [])} · کلیدهای سیم‌کشی‌شده: {len(inv.get('wired') or [])}"
                 f" · مسیرها: {len(inv.get('routes') or [])} · مبنا: {rep.get('baseline') or '—'}")
    st = rep.get("static") or {}
    if st:
        lines.append(f"   توابعِ صفحه: {st.get('defined', 0)} تعریف · {st.get('called', 0)} صدا"
                     f" · تعریف‌نشده: {len(st.get('undefined') or [])}")
    wg = rep.get("wiring") or {}
    if wg:
        lines.append(f"   اتصالِ HTML/JS: {wg.get('ids', 0)} id · {wg.get('refs', 0)} ارجاع"
                     f" · {wg.get('classes', 0)} کلاس · {wg.get('handlers', 0)} هندلرِ inline"
                     f" · تکراری: {len(wg.get('dups') or [])}"
                     f" · ارجاعِ بی‌عنصر: {len(wg.get('missing_ids') or [])}"
                     f" · هندلرِ بد: {len(wg.get('bad_handlers') or [])}"
                     f" · داراییِ وب: {len(wg.get('assets') or [])}"
                     f" · استفاده‌نشده: {len(wg.get('unused_ids') or [])} id"
                     f" / {len(wg.get('unused_classes') or [])} کلاس")
    pw = rep.get("pwa") or {}
    if pw:
        def _mark(flag):
            return "✓" if flag else "✗"
        lines.append(
            f"   PWA: {pw.get('promised', 0)} وعده · کش: {pw.get('cache') or '—'}"
            f" · پوستهٔ کش: {pw.get('shell', 0)} مسیر · آیکون: {pw.get('icons', 0)}"
            f" · /api/ مستثنا: {_mark(pw.get('api_bypass'))}"
            f" · فالبکِ آفلاین: {_mark(pw.get('offline'))}"
            f" · کش‌اولِ آیکون: {_mark(pw.get('cache_first_icons'))}"
            f" · نسخه‌بندیِ خودکارِ کش: {_mark(pw.get('cache_rev'))}"
            f" · بنرِ به‌روزرسانی: {_mark(pw.get('update_banner'))}"
            f" · یادِ «بعداً» تا پایانِ بازدید: {_mark(pw.get('banner_memory'))}"
            f" · خبرِ نسخهٔ تازهٔ سرِ بارگذاری: {_mark(pw.get('update_watch'))}"
            f" · ارتقای ایمن (تأیید و برگردان): {_mark(pw.get('safe_upgrade'))}")
    bk = rep.get("backup") or {}
    if bk:
        lines.append(
            f"   پشتیبانِ داده: برون‌بری/درون‌بری: {'✓' if bk.get('endpoints') else '✗'}"
            f" · اعتبارسنجیِ پیش از نوشتن: {'✓' if bk.get('validate_first') else '✗'}"
            f" · نوشتنِ اتمیکِ دفتر: {'✓' if bk.get('atomic') else '✗'}"
            f" · کنترل‌های رابط: {'✓' if bk.get('controls') else '✗'}")
    ab = rep.get("autobackup") or {}
    if ab:
        lines.append(
            f"   پشتیبانِ خودکار: نگه‌داشتِ امنِ نسخه‌ها: {'✓' if ab.get('safe_prune') else '✗'}"
            f" · نوشتنِ اتمیکِ اسنپ‌شات: {'✓' if ab.get('atomic') else '✗'}"
            f" · زمان‌بندِ زنده: {'✓' if ab.get('scheduler') else '✗'}"
            f" · کنترل‌های رابط: {'✓' if ab.get('controls') else '✗'}")
    ar = rep.get("archive") or {}
    if ar:
        lines.append(
            f"   آرشیوِ اقتصادی: گیرندهٔ Actual: {'✓' if ar.get('actuals') else '✗'}"
            f" · حکمِ قطعی: {'✓' if ar.get('verdict') else '✗'}"
            f" · رندرِ مطلق: {'✓' if ar.get('render') else '✗'}"
            f" · تأثیرِ نتیجه: {'✓' if ar.get('effect') and ar.get('impact') else '✗'}"
            f" · بی‌گزارهٔ شرطی: {'✓' if ar.get('conditional') and ar.get('lean') else '✗'}"
            f" · ردیفِ بی‌عدد صادق: {'✓' if ar.get('perrow') else '✗'}"
            f" · صعودی/نزولی در صفحه: {ar.get('outcomes', 0)}")
    fs = rep.get("feed") or {}
    if fs:
        lines.append(
            f"   فیدِ خبرهای پیش‌رو: سوییچِ اعلام → نتیجه + تأثیر: "
            f"{'✓' if fs.get('past_fn') and fs.get('ui') and fs.get('verdict') else '✗'}"
            f" · بی‌گزارهٔ شرطی در رویدادِ اعلام‌شده: {'✓' if fs.get('lean') else '✗'}"
            f" · تأثیرِ نتیجه در فید: {'✓' if fs.get('impact') else '✗'}"
            f" · انتظارِ صادق: {'✓' if fs.get('wait') else '✗'}"
            f" · نزدیک‌ترین فقط پیشِ‌رو: {'✓' if fs.get('nexthigh') else '✗'}"
            f" · سناریوی پیشِ‌رو: {2 if fs.get('scen_future') else 0}")
    fw = rep.get("feedwin") or {}
    if fw:
        wsel = fw.get("seg_btns", 0)
        lines.append(
            f"   فیدِ زنده: پنجرهٔ گذشتهٔ مجاز: {3 if fw.get('windows') else 0}"
            f" · قطعی‌سازیِ past_window: "
            f"{'✓' if fw.get('fn') and fw.get('norm') else '✗'}"
            f" · مرزِ خاموشِ صفر: {'✓' if fw.get('off') else '✗'}"
            f" · عبورِ انتخابگر به سرور: "
            f"{'✓' if fw.get('seg') and fw.get('state') and fw.get('fetch') and fw.get('route') else '✗'}"
            f" · گزینه‌های انتخابگر: {wsel}"
            f" · تیکِ زندهٔ بج (بی‌رفرش): {'✓' if fw.get('tick') and fw.get('tick_lean') else '✗'}"
            f" · مبنای دقیقه‌ها: "
            f"{'✓' if fw.get('datam') and fw.get('loop') and fw.get('t0') else '✗'}"
            f" · بارِ اول بی‌خالی: {'✓' if fw.get('firstload') else '✗'}"
            f" · حفظِ کارتِ باز: {'✓' if fw.get('keep') else '✗'}")
    fl = rep.get("feedflip") or {}
    if fl:
        lines.append(
            f"   سوییچِ لحظه‌ایِ اعلام: لنگرِ ثانیه‌ای: {'✓' if fl.get('ins') else '✗'}"
            f" · مسیرِ تک‌رویداد: {'✓' if fl.get('one_event') and fl.get('route') else '✗'}"
            f" · تیکِ لحظهٔ صفر: {'✓' if fl.get('tick') else '✗'}"
            f" · خواندنِ درستِ لنگرِ ثانیه‌ای: {'✓' if fl.get('ins_read') else '✗'}"
            f" · سوییچِ درجا (بی‌بازسازی): {'✓' if fl.get('patch_only') else '✗'}"
            f" · گاردِ اعلامِ زودرس: {'✓' if fl.get('early') else '✗'}"
            f" · صبرِ سقف‌دار تا عدد: {'✓' if fl.get('retry') else '✗'}"
            f" · کلیدِ تازه پس از تغییرِ عنوان: {'✓' if fl.get('rekey') else '✗'}"
            f" · خواندنِ عددِ «۱۹۵K»: {'✓' if fl.get('num_mult') else '✗'}"
            f" · عددهای منفی: {'✓' if fl.get('num_exact') else '✗'}"
            f" · نزدیک‌ترین خبرِ تازه: {'✓' if fl.get('next') else '✗'}")
    ba = rep.get("buttons") or {}
    if ba:
        lines.append(
            f"   کلیدِ بی‌واکنش نداریم: تورِ ایمنیِ فاندمنتال: "
            f"{'✓' if ba.get('fund_fallback') and ba.get('fund_guard') else '✗'}"
            f" · واکنشِ دیدنیِ بروزرسانی: {'✓' if ba.get('rf_visible') and ba.get('rf_flash') else '✗'}"
            f" · کلیدهای تبِ نو: {ba.get('newtab', 0)}")
    bk = rep.get("dock") or {}
    if bk:
        lines.append(
            f"   کرکره‌های نمای اصلی: جمعِ پیش‌فرض: "
            f"{bk.get('panels', 0)}/{len(_FOLD_PANELS)}"
            f" · نوارِ کلیدپذیر: {'✓' if bk.get('wired') else '✗'}"
            f" · گزینه‌های پشتیبان داخلِ بدنه: {'✓' if bk.get('options_inside') else '✗'}"
            f" · خلاصهٔ وضعیت روی نوار: {'✓' if bk.get('state') else '✗'}"
            f" · یادِ وضعیت بینِ بازدیدها: {'✓' if bk.get('memory') else '✗'}")
    gq = rep.get("gapq") or {}
    if gq:
        lines.append(
            f"   پرسشِ تأییدِ شکاف (FVG): بندهای امتیاز: "
            f"{gq.get('criteria', 0)}/{len(_GQ_CRITERIA)}"
            f" · پویشِ بی‌گیت: {'✓' if gq.get('no_scan_gate') else '✗'}"
            f" · آستانه‌های تأیید: {'✓' if gq.get('consts') else '✗'}"
            f" · قابلِ اتکا فقط A+/A: {'✓' if gq.get('reliable') else '✗'}"
            f" · اندپوینتِ /api/gap: {'✓' if gq.get('route') else '✗'}"
            f" · پنلِ پرسش: {gq.get('ids', 0)}/{len(_GQ_PANEL_IDS)}"
            f" · دو حالتِ پرسش: {gq.get('modes', 0)}/2"
            f" · پیشوندِ کارت (بی`v.`): {'✓' if gq.get('prefix') else '✗'}")
    nt = rep.get("notify") or {}
    if nt:
        lines.append(
            f"   نوتیفیکیشنِ تست‌ها: دروازه: {'✓' if nt.get('gate') else '✗'}"
            f" · تست/هارنسِ خفه: {nt.get('muted', 0)}/{nt.get('sites', 0)}"
            f" · گامِ CIِ خفه: {nt.get('ci_muted', 0)}/{nt.get('ci_sites', 0)}")
    for p in rep.get("problems") or []:
        lines.append(f"   ✗ {p}")
    for w in rep.get("warnings") or []:
        lines.append(f"   ⚠ {w}")
    if rep.get("restored_from"):
        lines.append(f"   ♻️ نسخه‌ی سالمِ قبلی برگردانده شد از: {rep['restored_from']}")
    if rep.get("snapshot"):
        lines.append(f"   💾 اسنپ‌شات: {rep['snapshot']}")
    if rep.get("baseline_file"):
        lines.append(f"   📌 فایلِ مبنا: {rep['baseline_file']}")
    lines.append(f"   📝 لاگ: {LOG}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="نگهبانِ سلامتِ pipfound")
    ap.add_argument("--root", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--guard", action="store_true", help="خرابی را با نسخه‌ی سالمِ قبلی ترمیم کن")
    ap.add_argument("--snapshot", action="store_true", help="مبنای «سالم» را به‌روز کن")
    ap.add_argument("--live", action="store_true", help="سرورِ در حالِ اجرا را هم چک کن")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--accept-removals", action="store_true",
                    help="حذفِ عمدیِ کنترل‌ها را بپذیر (برای بازتعریفِ مبنا)")
    a = ap.parse_args()
    root = os.path.abspath(a.root)

    if a.accept_removals:
        _log("ACCEPT-REMOVALS — حذفِ عمدیِ کنترل‌ها پذیرفته شد؛ مبنای «سالم» بازتعریف می‌شود")

    if a.guard:
        rep = guard(root)
        if rep.get("ok"):
            rep.setdefault("snapshot", GOOD)
    else:
        rep = run_checks(root, live=a.live, accept_removals=a.accept_removals)
        if a.snapshot and rep["ok"]:
            rep["snapshot"] = save_snapshot(root, rep)
            rep["baseline_file"] = write_repo_baseline(root, rep)
        elif a.snapshot:
            rep.setdefault("warnings", []).append(
                "اسنپ‌شات گرفته نشد (فقط نسخه‌ی سالم ذخیره می‌شود) — خطاها را رفع کن یا با --accept-removals تایید کن")

    print(json.dumps(rep, ensure_ascii=False, indent=2) if a.json else _human(rep))
    sys.exit(0 if rep.get("ok") else 1)


if __name__ == "__main__":
    main()
