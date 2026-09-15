#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""نگهبانِ سلامتِ pipfound — نمی‌گذارد اپ دوباره با یک ویرایشِ خراب بی‌صدا از کار بیفتد.

چه کار می‌کند:
  ۱) سینتکسِ پایتونِ همه‌ی ماژول‌ها را چک می‌کند (ast.parse — بدونِ اجرای کد).
  ۲) متنِ صفحه‌های HTML/FUND_PAGE را از app.py بیرون می‌کشد، هر بلوکِ <script> را
     با موتورِ JS (node --check) از نظرِ سینتکس اعتبارسنجی می‌کند.
  ۳) چکِ «هیچ کلیدی گم نشود»: هر کنترلی که در نسخه‌ی سالمِ قبلی وجود داشت و
     جاوااسکریپت به آن وصل بود، باید سرِ جایش باشد. همچنین مسیرها (routeها).
  ۴) اسنپ‌شاتِ نسخه‌ی سالم را در ~/pipfound/good نگه می‌دارد و با فلگ --guard
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
           "macro_context.py", "backtest.py", "manifest.webmanifest", "sw.js",
           "icon-180.png", "icon-192.png", "icon-192-mask.png",
           "icon-512.png", "icon-512-mask.png"]

PAGE_CONSTS = ("HTML", "FUND_PAGE")

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


def read_snapshot_inventory():
    fp = os.path.join(GOOD, "inventory.json")
    try:
        with open(fp, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
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

    inv = inventory(pages)
    inv["routes"] = routes_of(root)
    rep["inventory"] = inv

    # کنترل‌های الزامی
    missing = [i for i in REQUIRED_IDS if i not in inv["ids"]]
    if missing:
        rep["problems"].append("کنترل‌های غایب در صفحه: " + "، ".join(missing))

    # قراردادِ «چیزی گم نشود» بر پایه‌ی نسخه‌ی سالمِ قبلی
    snap = read_snapshot_inventory()
    if snap and enforce_contract and not accept_removals:
        lost_wired = sorted(set(snap.get("wired", [])) - set(inv["ids"]))
        lost_routes = sorted(set(snap.get("routes", [])) - set(inv["routes"]))
        if lost_wired:
            rep["problems"].append("کنترل‌هایی که در نسخه‌ی سالم بود و الان نیست: "
                                   + "، ".join(lost_wired))
        if lost_routes:
            rep["problems"].append("مسیرهایی که در نسخه‌ی سالم بود و الان نیست: "
                                   + "، ".join(lost_routes))
    else:
        if [i for i in REQUIRED_IDS if i not in inv["ids"]]:
            rep["warnings"].append("مبنای مقایسه (اسنپ‌شات) موجود نیست")

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
                 f" · مسیرها: {len(inv.get('routes') or [])}")
    for p in rep.get("problems") or []:
        lines.append(f"   ✗ {p}")
    for w in rep.get("warnings") or []:
        lines.append(f"   ⚠ {w}")
    if rep.get("restored_from"):
        lines.append(f"   ♻️ نسخه‌ی سالمِ قبلی برگردانده شد از: {rep['restored_from']}")
    if rep.get("snapshot"):
        lines.append(f"   💾 اسنپ‌شات: {rep['snapshot']}")
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

    if a.guard:
        rep = guard(root)
        if rep.get("ok"):
            rep.setdefault("snapshot", GOOD)
    else:
        rep = run_checks(root, live=a.live, accept_removals=a.accept_removals)
        if a.snapshot and rep["ok"]:
            rep["snapshot"] = save_snapshot(root, rep)

    print(json.dumps(rep, ensure_ascii=False, indent=2) if a.json else _human(rep))
    sys.exit(0 if rep.get("ok") else 1)


if __name__ == "__main__":
    main()
