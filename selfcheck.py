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
     استفاده‌نشده هم شمرده می‌شود، ولی فقط به‌شکلِ «هشدار».
  ۴) چکِ «هیچ کلیدی گم نشود»: هر کنترلی که در نسخه‌ی سالمِ قبلی وجود داشت و
     جاوااسکریپت به آن وصل بود، باید سرِ جایش باشد. همچنین مسیرها (routeها).
  ۵) اسنپ‌شاتِ نسخه‌ی سالم را در ~/pipfound/good نگه می‌دارد و با فلگ --guard
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
#    را بی‌دلیل برمی‌گرداند.
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


def wiring_problems(pages):
    """اتصالِ HTML و JS را استاتیک می‌سنجد → (خطاها, هشدارها, آمار)."""
    probs, warns = [], []
    stats = {"pages": 0, "ids": 0, "classes": 0, "refs": 0, "handlers": 0,
             "dups": [], "missing_ids": [], "bad_handlers": [],
             "unused_ids": [], "unused_classes": []}
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

        # ۵) استفاده‌نشده‌ها — هشدار، نه خطا (کدِ مرده است، نه خرابی)
        for i in sorted(set(decl)):
            own = len(re.findall(r'\bid\s*=\s*["\']' + re.escape(i) + r'["\']', html))
            if len(_token_re(i).findall(html)) <= own:
                stats["unused_ids"].append(f"{pname}:{i}")
                warns.append(f"{pname} · idِ «{i}» جایی استفاده نشده (نه CSS، نه JS)")
        in_html = _class_tokens(markup)
        everywhere = _class_tokens(html)
        stats["classes"] += len(in_html)
        for c in sorted(in_html):
            if len(_token_re(c).findall(html)) <= everywhere.get(c, 0):
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
    wp, ww, wstats = wiring_problems(pages) if pages else ([], [], {})
    rep["wiring"] = wstats
    rep["problems"] += [f"اتصالِ HTML/JS → {p}" for p in wp]
    rep["warnings"] += [f"اتصالِ HTML/JS → {w}" for w in ww]

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
                     f" · استفاده‌نشده: {len(wg.get('unused_ids') or [])} id"
                     f" / {len(wg.get('unused_classes') or [])} کلاس")
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
