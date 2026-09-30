#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""آزمونِ لایه‌ی ۴.۱۹ — «یادِ وضعیتِ کرکره‌های نمای اصلی بینِ بازدیدها» (خواسته‌ی کاربر).

خواسته: «وضعیتِ باز/بستهٔ کرکره‌های نمای اصلی را بینِ بازدیدها یادت بماند تا هر بخش
همان‌طور که کاربر گذاشته بماند.» ⇒ هر چهار بخشِ نگهداری (آلارم‌ها · بک‌تست · ریسک ·
پشتیبانِ داده) باید باز/بسته‌بودنِ خودشان را در حافظهٔ محلی نگه دارند، ولی «نبودِ یاد»
باید همان نمای تمیزِ پیش‌فرض باشد (همه بسته) — یاد افزودنی است، جانشینِ پیش‌فرض نیست.

سه بخش:
  ۱) قاعده‌ی استاتیکِ `selfcheck.fold_panels_problems` روی مخزنِ سالم؛
  ۲) جهش‌آزمایی — قرمزها باید **نام‌دار** شوند و پاک‌سازی‌های بی‌گناه سبز بمانند؛
  ۳) رفتارِ **واقعی** با node: توابعِ `pfFoldsRead`/`pfFoldsWrite`/`pfFold` از خودِ صفحه
     استخراج و در یک DOMِ جعلی + `localStorage`ِ جعلی اجرا می‌شوند — بارگذاریِ اوّل
     بسته · کلیک ذخیره می‌کند · بارگذاریِ دوباره باز می‌ماند · بستن هم یاد می‌ماند ·
     و حافظهٔ خاموش/پرت‌کن، JSONِ خراب یا مقدارِ نادرست نه صفحه را می‌شکنند و نه بخشی
     را خودسر باز می‌کنند.

آفلاین و چندثانیه‌ای است. PF_FOLD_NO_MUT=1 بخشِ جهش را رد می‌کند.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import selfcheck as SC  # noqa: E402

CHECKS, FAILS = [], []


def check(name, cond, detail=""):
    CHECKS.append(name)
    if not cond:
        FAILS.append((name, detail))
    return bool(cond)


def copy_repo():
    d = tempfile.mkdtemp(prefix="pf_foldmem_")
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
    """جهش با لنگرِ یکتا — اگر لنگر پیدا نشود، **خطا** می‌دهد نه سبزِ خاموش."""
    txt = _read(d, name)
    n = txt.count(old)
    if n != expect:
        raise AssertionError("لنگرِ جهش در %s %d بار پیدا شد (باید %d باشد): %r"
                             % (name, n, expect, old[:60]))
    _write(d, name, txt.replace(old, new))


def scan(d):
    return SC.fold_panels_problems(d, SC.page_sources(d))


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


def green(name, mutate, key="memory"):
    """جهشِ بی‌گناه نباید قرمز شود و شاخصِ مربوطه باید سبز بماند."""
    d = copy_repo()
    try:
        mutate(d)
        probs, st = scan(d)
        check("بی‌گناه: " + name, probs == [] and st.get(key) is True,
              "probs=" + str(probs)[:200] + " stats=" + str(st))
    finally:
        drop(d)


NO_MUT = os.environ.get("PF_FOLD_NO_MUT") == "1"

# ═══ ۱) قاعده روی مخزنِ سالم ═══
print("═══ ۱) قاعده‌ی یادِ وضعیتِ کرکره‌ها روی مخزنِ سالم ═══")
p0, s0 = scan(HERE)
check("قاعده: مخزنِ سالم صفر خطا", p0 == [], str(p0)[:300])
check("قاعده: شاخصِ «یادِ وضعیت» سبز است", s0.get("memory") is True, str(s0))
check("قاعده: هر چهار بخشِ نگهداری هنوز جمعِ پیش‌فرض‌اند",
      s0.get("panels") == len(SC._FOLD_PANELS), str(s0))
check("قاعده: مکانیکِ بسته‌بودن دست‌نخورده است", s0.get("collapsed") is True, str(s0))
check("قاعده: پیش‌فرضِ مارک‌آپ هنوز «بسته» است (یاد افزودنی است، نه جانشین)",
      'aria-expanded="false"' in (SC.page_sources(HERE).get("HTML") or ""))

# ═══ ۲) جهش‌آزماییِ قاعده ═══
if not NO_MUT:
    print("═══ ۲) جهش‌آزماییِ قاعده (قرمز/بی‌گناه) ═══")
    red("کلیدِ حافظه حذف/تغییرنام شده (یادی نمی‌مانَد)",
        "کلیدِ حافظهٔ کرکره‌ها",
        lambda d: edit(d, "app.py", 'const PF_FOLD_KEY="pf-folds-v1";',
                       'const PF_FOLD_KEYX="pf-folds-v1";'))
    red("بازگردانیِ وضعیتِ یادمانده از pfFold برداشته شده",
        "وضعیتِ یادماندهٔ خودشان را برنمی‌گردانند",
        lambda d: edit(d, "app.py",
                       'if(pfFoldsRead()[boxId]===true) box.classList.add("open");',
                       '/* یاد خاموش شد */'))
    red("بازگردانی بعد از سیم‌کشی/رسم انجام می‌شود (بدنه و aria هم‌گام نمی‌شوند)",
        "بازگردانیِ وضعیت بعد از سیم‌کشی/رسم انجام می‌شود",
        lambda d: (edit(d, "app.py",
                        '  if(pfFoldsRead()[boxId]===true) box.classList.add("open");\n', ""),
                   edit(d, "app.py", "  paint();\n  return true;\n}",
                        '  paint();\n  if(pfFoldsRead()[boxId]===true) box.classList.add("open");\n'
                        "  return true;\n}")))
    red("ذخیره‌ی وضعیت بیرونِ هندلرِ کلیک افتاده (باز گذاشتن بی‌اثر می‌شود)",
        "ذخیره نمی‌شود",
        lambda d: edit(d, "app.py", "tgl.onclick=()=>{", "setTimeout(()=>{"))
    red("خواندنِ حافظه با sessionStorage (یاد تا بازدیدِ بعد نمی‌ماند)",
        "خواندنِ حافظهٔ کرکره‌ها",
        lambda d: edit(d, "app.py",
                       "JSON.parse(window.localStorage.getItem(PF_FOLD_KEY)",
                       "JSON.parse(window.sessionStorage.getItem(PF_FOLD_KEY)"))
    red("خواندنِ حافظه بدونِ try (حریمِخصوصی صفحه را می‌شکند)",
        "خواندنِ حافظهٔ کرکره‌ها",
        lambda d: edit(d, "app.py", "  try{\n    const m=JSON.parse(", "  {\n    const m=JSON.parse("))
    red("نوشتنِ حافظه بدونِ try (حریمِخصوصی کلید را می‌شکند)",
        "نوشتنِ حافظهٔ کرکره‌ها",
        lambda d: edit(d, "app.py", "try{ window.localStorage.setItem(",
                       "window.localStorage.setItem("))

    # بی‌گناه‌ها: نباید قرمز شوند
    green("عوض‌کردنِ نسخه‌ی کلیدِ حافظه (تدبیرِ طبیعیِ آینده) سبز می‌مانَد",
          lambda d: edit(d, "app.py", '"pf-folds-v1"', '"pf-folds-v2"'))
    green("قالب‌بندیِ خروجیِ JSON سبز می‌مانَد",
          lambda d: edit(d, "app.py", "JSON.stringify(m)", "JSON.stringify(m, null, 0)"))
    green("افزودنِ کامنت/مقدارِ پیش‌فرضِ دیگر در خواندن سبز می‌مانَد",
          lambda d: edit(d, "app.py", '    const m=JSON.parse(',
                         '    // یادِ بازدیدِ قبل\n    const m=JSON.parse('))
    green("پیش‌فرضِ رشته‌ی خالی به‌جای «null» سبز می‌مانَد",
          lambda d: edit(d, "app.py", '||"null"', '||"{}"'))

# ═══ ۳) رفتارِ واقعیِ همین توابع (اجرای واقعی با node) ═══
print("═══ ۳) رفتارِ واقعیِ یاد (بدونِ مرورگر، با node) ═══")
NODE = shutil.which("node")

HARNESS = """\"use strict\";
// ── شبیه‌سازِ حداقلیِ مرورگر: فقط همان چیزهایی که pfFolds*/pfFold لازم دارند ──
let store = {};
let readThrows = false, writeThrows = false;
const window = { localStorage: {
  getItem(k){
    if (readThrows) throw new Error("blocked");
    return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null;
  },
  setItem(k, v){ if (writeThrows) throw new Error("blocked"); store[k] = String(v); },
  removeItem(k){ delete store[k]; },
} };
let els = {};
function mkEl(id){
  const el = { id: id, cls: {}, attrs: {}, onclick: null };
  el.classList = {
    add: (c) => { el.cls[c] = true; },
    remove: (c) => { delete el.cls[c]; },
    toggle: (c) => { if (el.cls[c]) delete el.cls[c]; else el.cls[c] = true; },
    contains: (c) => !!el.cls[c],
  };
  el.setAttribute = (k, v) => { el.attrs[k] = String(v); };
  el.getAttribute = (k) => (Object.prototype.hasOwnProperty.call(el.attrs, k) ? el.attrs[k] : null);
  return el;
}
const PANELS = [["alarmsDock", "alarmsToggle", "alarmsBody"], ["btPanel", "btToggle", "btBody"]];
const IDS = { alarmsDock: ["alarmsToggle", "alarmsBody"], btPanel: ["btToggle", "btBody"] };
const document = { getElementById: (id) => els[id] || null };
__BUNDLE__
function load(){                       // «بارگذاریِ تازهٔ صفحه» با همان حافظه
  els = {};
  for (const p of PANELS) for (const id of [p[0], p[1], p[2]]) els[id] = mkEl(id);
  for (const p of PANELS) pfFold(p[0], p[1], p[2]);
}
function click(id){ els[id].onclick(); }
function snap(id){
  return { open: els[id].classList.contains("open"),
           aria: els[IDS[id][0]].getAttribute("aria-expanded"),
           hidden: els[IDS[id][1]].getAttribute("aria-hidden") };
}
function mem(){ return Object.prototype.hasOwnProperty.call(store, PF_FOLD_KEY) ? store[PF_FOLD_KEY] : null; }
function stored(){ try { return JSON.parse(mem()); } catch (e) { return { corrupt: true }; } }
const out = {};
function run(name, fn){ try { out[name] = fn(); } catch (e) { out[name] = { error: String((e && e.message) || e) }; } }

run("firstVisit",   () => { store = {}; load();
                            return { alarms: snap("alarmsDock"), bt: snap("btPanel"), raw: mem() }; });
run("clickStores",  () => { click("alarmsToggle");
                            return { alarms: snap("alarmsDock"), stored: stored(), raw: mem() }; });
run("reloadKeepsOpen", () => { load();
                            return { alarms: snap("alarmsDock"), bt: snap("btPanel") }; });
run("closeRemembers", () => { click("alarmsToggle");
                            const afterClick = stored(); load();
                            return { afterClick: afterClick, alarms: snap("alarmsDock") }; });
run("mergeKeepsOther", () => { store = {}; load();
                            click("btToggle"); click("alarmsToggle");
                            const raw = stored(); load();
                            return { raw: raw, alarms: snap("alarmsDock"), bt: snap("btPanel") }; });
run("privacyReadThrows", () => { store = {}; load(); click("btToggle");
                            readThrows = true; let err = null;
                            try { load(); } catch (e) { err = String(e); }
                            readThrows = false;
                            return { err: err, alarms: snap("alarmsDock") }; });
run("privacyWriteThrows", () => { store = {}; writeThrows = true; let err = null;
                            try { load(); click("alarmsToggle"); } catch (e) { err = String(e); }
                            writeThrows = false;
                            return { err: err, alarms: snap("alarmsDock"), raw: mem() }; });
run("corruptJson",  () => { store = {}; store[PF_FOLD_KEY] = "{oops"; let err = null;
                            try { load(); } catch (e) { err = String(e); }
                            return { err: err, alarms: snap("alarmsDock") }; });
run("truthyNotTrue", () => { store = {}; store[PF_FOLD_KEY] = JSON.stringify({ alarmsDock: 1, btPanel: "yes" });
                            let err = null;
                            try { load(); } catch (e) { err = String(e); }
                            return { err: err, alarms: snap("alarmsDock"), bt: snap("btPanel") }; });
run("nullValue",    () => { store = {}; store[PF_FOLD_KEY] = "null"; let err = null;
                            try { load(); } catch (e) { err = String(e); }
                            return { err: err, alarms: snap("alarmsDock") }; });

process.stdout.write(JSON.stringify(out));
"""


def js_bundle(page):
    """توابعِ واقعیِ حافظه/کرکره را از خودِ صفحه بیرون می‌کشد (تعریفِ ستونِ ۰)."""
    m = SC._FOLD_MEM_KEY_RE.search(page)
    parts = [m.group(0) + ";"] if m else []
    for fn in ("pfFoldsRead", "pfFoldsWrite", "pfFold"):
        body = SC._fold_fn_body(page, fn)
        if not body:
            return ""
        parts.append(body.rstrip() + "\n}")
    return "\n".join(parts)


def run_scenarios(bundle):
    js = HARNESS.replace("__BUNDLE__", bundle)
    fd, path = tempfile.mkstemp(suffix=".js", prefix="pf_foldmem_")
    try:
        os.close(fd)
        io.open(path, "w", encoding="utf-8").write(js)
        out = subprocess.run([NODE, path], capture_output=True, text=True, timeout=25)
        if out.returncode != 0:
            return {"__node_error__": (out.stderr or "")[-400:]}
        return json.loads(out.stdout or "{}")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


if NODE:
    page = SC.page_sources(HERE).get("HTML") or ""
    bundle = js_bundle(page)
    check("رفتار: توابعِ واقعیِ یاد (pfFoldsRead/pfFoldsWrite/pfFold) استخراج شدند",
          bool(bundle), "استخراجِ تنهٔ توابع شکست خورد")
    if bundle:
        r = run_scenarios(bundle)
        check("رفتار: اجرای سناریوها در node بدونِ خطا تمام شد",
              "__node_error__" not in r, str(r.get("__node_error__"))[:250])

        def sc(name):
            return r.get(name) or {}

        f, ck = sc("firstVisit"), sc("clickStores")
        check("رفتار: بازدیدِ اوّلِ بدونِ یاد = همه بسته (نمای تمیزِ پیش‌فرض)",
              f.get("alarms", {}).get("open") is False
              and f.get("bt", {}).get("open") is False and f.get("raw") is None, str(f)[:250])
        check("رفتار: یک کلیک، بخش را باز می‌کند و وضعیت را در حافظه می‌نویسد",
              ck.get("alarms", {}).get("open") is True
              and ck.get("alarms", {}).get("aria") == "true"
              and ck.get("alarms", {}).get("hidden") == "false"
              and ck.get("stored") == {"alarmsDock": True}, str(ck)[:250])
        rk = sc("reloadKeepsOpen")
        check("رفتار: بعد از بارگذاریِ دوباره همان بخش باز می‌مانَد و بخشِ دیگر خودسر باز نمی‌شود",
              rk.get("alarms", {}).get("open") is True
              and rk.get("alarms", {}).get("aria") == "true"
              and rk.get("bt", {}).get("open") is False, str(rk)[:250])
        cl = sc("closeRemembers")
        check("رفتار: بستنِ کاربر هم یاد می‌مانَد (بعد از بارگذاریِ دوباره بسته است)",
              cl.get("afterClick") == {"alarmsDock": False}
              and cl.get("alarms", {}).get("open") is False
              and cl.get("alarms", {}).get("aria") == "false", str(cl)[:250])
        mg = sc("mergeKeepsOther")
        check("رفتار: باز کردنِ یک بخش، یادِ بخش‌های دیگر را پاک نمی‌کند (read-modify-write)",
              mg.get("raw") == {"btPanel": True, "alarmsDock": True}
              and mg.get("alarms", {}).get("open") is True
              and mg.get("bt", {}).get("open") is True, str(mg)[:250])
        pr = sc("privacyReadThrows")
        check("رفتار: حافظهٔ خوانده‌نشدنی (حریمِخصوصی) صفحه را نمی‌شکند و بخشی را باز نمی‌کند",
              pr.get("err") is None and pr.get("alarms", {}).get("open") is False, str(pr)[:250])
        pw = sc("privacyWriteThrows")
        check("رفتار: حافظهٔ نوشته‌نشدنی کلید را نمی‌شکند (باز/بسته روی صفحه کار می‌کند)",
              pw.get("err") is None and pw.get("alarms", {}).get("open") is True
              and pw.get("raw") is None, str(pw)[:250])
        cj = sc("corruptJson")
        check("رفتار: JSONِ خراب در حافظه نادیده گرفته می‌شود (خطا + پیش‌فرضِ تمیز)",
              cj.get("err") is None and cj.get("alarms", {}).get("open") is False, str(cj)[:250])
        tt = sc("truthyNotTrue")
        check("رفتار: فقط «true»ِ صریح باز می‌کند؛ مقدارِ نادرست (1/‏\"yes\") بخش را خودسر باز نمی‌کند",
              tt.get("err") is None and tt.get("alarms", {}).get("open") is False
              and tt.get("bt", {}).get("open") is False, str(tt)[:250])
        nv = sc("nullValue")
        check("رفتار: مقدارِ «null» در حافظه = یادِ خالی، نه خطا",
              nv.get("err") is None and nv.get("alarms", {}).get("open") is False, str(nv)[:250])
else:
    # CI همیشه node دارد؛ این فقط فرارِ محلیِ بدونِ node است — با هشدارِ صریح رد
    # می‌شود تا کسی توهمِ پوششِ رفتاری نگیرد.
    print("⚠ node در دسترس نیست — بخشِ رفتاری رد شد "
          "(CI گامِ node را دارد؛ این‌جا فقط قاعدهٔ استاتیک سنجیده شد)")

# ── جمع‌بندی ──
print("\n• بررسی‌ها: %d" % len(CHECKS))
if FAILS:
    for name, detail in FAILS:
        print("::error::❌ %s — %s" % (name, detail[:220]))
    print("\n❌ آزمونِ «یادِ وضعیتِ کرکره‌ها» رد شد — %d از %d بررسی شکست خورد"
          % (len(FAILS), len(CHECKS)))
    sys.exit(1)
print("✅ آزمونِ «یادِ وضعیتِ کرکره‌ها» پاس شد — باز/بسته‌بودنِ هر بخش بینِ بازدیدها "
      "یاد می‌مانَد، پیش‌فرضِ تمیز دست‌نخورده است، و حافظهٔ خراب/خاموش نه صفحه را "
      "می‌شکند و نه بخشی را خودسر باز می‌کند")
