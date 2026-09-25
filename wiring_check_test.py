#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""جهش‌آزماییِ لایه‌ی ۱ نگهبان: «اتصالِ HTML و JS» (شناسه‌ها، هندلرها، استفاده‌نشده‌ها).

چرا لازم است: چکِ «تابعِ صدا زده شده ولی تعریف نشده» فقط کدِ داخلِ <script> را
می‌بیند. چند کلاسِ خرابیِ بی‌صدا بیرونِ آن می‌مانند و این تست خودشان را می‌سنجد:

  ۱) idِ تکراری در یک سند → getElementById فقط اولی را برمی‌گرداند.
  ۲) ارجاعِ JS به idی که در همان صفحه ساخته نمی‌شود → آن کنترل هرگز کاری نمی‌کند.
  ۳) هندلرِ inline در مارک‌آپ (`onclick="..."`) که تابعش در آن صفحه نیست.
  ۴) انتسابِ هندلر/تایمر به «نامِ خالی» بدونِ پرانتز: `x.onclick = foo` —
     همین الگو در این اپ رایج است (`jb.onclick = saveJournal`) و چون پرانتز
     ندارد، چکِ «صدا زده شده» نمی‌بیندش؛ اگر تعریفش پاک شود دکمه بی‌صدا می‌میرد.
  ۵) کلاس/idِ استفاده‌نشده → **هشدارِ اطلاعاتی**، نه خطا (کدِ مرده خرابی نیست و
     اگر خطا شمرده شود، نگهبانِ بازگردان نیم‌کاره‌ی در حالِ ساخت را برمی‌گرداند).
     «استفاده‌نشده» یعنی هیچ‌جا نامش برده نشده — نه در صفحه، نه در دارایی‌های
     وبِ بیرون (هارنسِ بصری/سرویس‌ورکر)؛ وگرنه هشدار، پاک‌کردنِ لنگرِ زنده را
     توصیه می‌کرد و لایهٔ ۳ می‌شکست (تستِ جهشِ همین قاعده در بندِ ۴ می‌آید).

و برعکسش هم سنجیده می‌شود: جهش‌های «ظاهراً مشکوک ولی بی‌گناه» نباید گزارش شوند —
مارک‌آپی که داخلِ رشتهٔ JS ساخته می‌شود (innerHTML)، idِ داخلِ رشته/کامنت،
هندلرِ فلش/متد به‌جای نامِ خالی، کلاسی که فقط JS یا CSS استفاده‌اش می‌کند، و
idِ همنام در سندِ دیگر (HTML و FUND_PAGE دو دامنه‌ی جدا هستند).

روی مخزنِ واقعی هم دو چیز قفل شده: لنگرهایی که هارنسِ بصری لازمشان دارد «مرده»
نام نمی‌گیرند، و هیچ کدِ مردهٔ شناسه‌ای باقی نمانده (بندهای ۱ و ۴).

کاملاً آفلاین و قطعی: هر جهش روی کپیِ موقتِ `app.py` اجرا می‌شود و به سرورِ 8787
دست نمی‌زند.

اجرا:  python3 wiring_check_test.py        (خروجی ۰ = سالم)
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import selfcheck as SC          # noqa: E402

CHECKS, FAILS = [], []


def check(name, cond, detail=""):
    CHECKS.append(name)
    if not cond:
        FAILS.append((name, detail))


APP = os.path.join(HERE, "app.py")
SOURCE = open(APP, encoding="utf-8").read()

# لنگرهای جهش — اگر روزی مارک‌آپِ app.py عوض شود، تست باید **بلند** بشکند،
# نه بی‌صدا سبز شود.
ANCHORS = {
    # صفحه‌ی اصلی (HTML)
    "h_sym_input": '<input id="sym" class="inp"',
    "h_go_btn": '<button id="go" class="go"',
    "h_sp_head": '<div class="sp-head">',
    "h_css_rule": ".sp-head{",
    "h_get_refresh": 'const refreshBtn=document.getElementById("refreshBtn");',
    "h_jb_assign": "if(jb) jb.onclick = saveJournal;",
    "h_leave": 'chips.addEventListener("mouseleave", closePickSoon);',
    "h_boot_fn": "function pipfoundBootWarn(){",
    # صفحه‌ی دوم (FUND_PAGE)
    "f_next": '<div id="nextWrap"></div>',
    "f_refresh_assign": '$("#refresh").onclick=load;',
}


def run_mutation(text, extra=None):
    """جهش را در پوشه‌ای موقت می‌گذارد و از خودِ گیتِ لایه‌ی ۱ می‌پرسد.

    `extra` = دارایی‌های وبِ همراه (مثلِ هارنسِ بصری) که گیت باید بخواندشان."""
    d = tempfile.mkdtemp(prefix="pf_wiring_")
    try:
        for nm in COMPANION_ASSETS:
            src = os.path.join(HERE, nm)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(d, nm))
        with open(os.path.join(d, "app.py"), "w", encoding="utf-8") as f:
            f.write(text)
        for nm, body in (extra or {}).items():
            with open(os.path.join(d, nm), "w", encoding="utf-8") as g:
                g.write(body)
        rep = SC.run_checks(d)
        return {"ok": rep["ok"], "problems": rep.get("problems") or [],
                "warnings": rep.get("warnings") or [], "w": rep.get("wiring") or {}}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def mutate(**subs):
    out = SOURCE
    for needle, repl in subs.items():
        if ANCHORS[needle] not in out:
            raise SystemExit(f"❌ لنگرِ جهش پیدا نشد: {needle} → {ANCHORS[needle]!r}")
        out = out.replace(ANCHORS[needle], repl, 1)
    return out


# دارایی‌های وبِ واقعیِ همین پوشه. محیطِ جهش باید مثلِ مخزن باشد، وگرنه دو
# خطای کاذب می‌سازد: (۱) لنگرهایی که هارنسِ بصری پین کرده «کدِ مرده» به‌نظر
# می‌رسند؛ (۲) نگهبانِ تازه‌ی «قراردادِ PWA» فایلِ همراهِ app.py را نمی‌بیند و
# «وعده‌ی بی‌فایل» گزارش می‌کند.
COMPANION_ASSETS = ("ui_visual_check.cjs", "sw.js", "manifest.webmanifest",
                    "icon-180.png", "icon-192.png", "icon-192-mask.png",
                    "icon-512.png", "icon-512-mask.png")


def wiring_needles(r):
    w = r["w"] or {}
    return sorted((w.get("dups") or []) + (w.get("missing_ids") or [])
                  + (w.get("bad_handlers") or []))


def unused_needles(r):
    w = r["w"] or {}
    return sorted((w.get("unused_ids") or []) + (w.get("unused_classes") or []))


# ═══════════════════════════════════════════════════════════════════
print("═══ ۰) لنگرهای جهش در app.py موجودند (تست نباید بی‌صدا سبز شود) ═══")
for k, v in ANCHORS.items():
    check(f"لنگرِ «{k}» در app.py هست", v in SOURCE, v)

# ═══════════════════════════════════════════════════════════════════
print("═══ ۱) مخزنِ سالم: گیت سبز، ولی با شمارشِ واقعی (ضدِ ناوَکوم) ═══")
base = run_mutation(SOURCE)
w = base["w"]
check("سنجه‌ی مخزنِ سالم با دارایی‌های وبِ واقعیِ همان‌جا اجرا می‌شود (ضدِ ناوَکوم)",
      {"ui_visual_check.cjs", "sw.js"} <= set(w.get("assets") or []), str(w.get("assets")))
check("گیتِ لایه‌ی ۱ روی کدِ سالم سبز است", base["ok"], str(base["problems"][:3]))
check("هیچ خطای اتصالی گزارش نمی‌شود", wiring_needles(base) == [],
      str(wiring_needles(base)))
check("هر دو سند سنجیده شده‌اند (HTML و FUND_PAGE)", w.get("pages") == 2, str(w.get("pages")))
check("شناسه‌ها واقعاً شمرده شده‌اند (ضدِ ناوَکوم)", w.get("ids", 0) >= 40, str(w.get("ids")))
check("ارجاع‌های JS واقعاً شمرده شده‌اند (ضدِ ناوَکوم)", w.get("refs", 0) >= 40, str(w.get("refs")))
check("کلاس‌ها واقعاً شمرده شده‌اند (ضدِ ناوَکوم)", w.get("classes", 0) >= 30, str(w.get("classes")))
# «استفاده‌نشده»ها هشدارند: نباید گیت را قرمز کنند (وگرنه بازگردانیِ بی‌دلیل).
check("مخزنِ سالم: صفر کلاس/idِ استفاده‌نشده (کدِ مرده‌ای نمانده)",
      unused_needles(base) == [], str(unused_needles(base)))
# این خاصیت را با یک جهشِ عمدی می‌سنجیم، نه با خودِ مخزنِ سالم: حالا که آخرین
# موردِ استفاده‌نشده پاک شده، شرطِ «اگر موجود بود» دیگر هیچ‌وقت اجرا نمی‌شد و
# پوششِ «هشدار ≠ خطا» بی‌صدا از دست می‌رفت.
UNUSED_MUT = mutate(h_sp_head='<div class="sp-head"><i id="ghostUnused"></i>')
unused_r = run_mutation(UNUSED_MUT)
check("idِ استفاده‌نشده گیت را قرمز نمی‌کند (فقط هشدار است)", unused_r["ok"] is True,
      str(unused_r["problems"][:2]))
check("...و در فهرستِ هشدارها با نامِ خودش می‌آید",
      any("ghostUnused" in x and "استفاده نشده" in x for x in unused_r["warnings"]),
      str(unused_r["warnings"][:2]))
check("...و در آمارِ استفاده‌نشده‌ها می‌آید (ضدِ ناوَکوم)",
      "HTML:ghostUnused" in unused_needles(unused_r), str(unused_needles(unused_r)))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۲) جهش‌های واقعی: گیت باید قرمز شود و همان مورد را نام ببرد ═══")
REAL = [
    ("idِ تکراری در صفحه‌ی اصلی",
     mutate(h_sym_input='<input id="sym" class="inp"><input id="sym" class="inp"'),
     "dups", "HTML:sym", "«sym»"),
    ("JS به idی وصل می‌شود که ساخته نمی‌شود",
     mutate(h_get_refresh='const refreshBtn=document.getElementById("refreshBtnGhost");'),
     "missing_ids", "HTML:refreshBtnGhost", "«refreshBtnGhost»"),
    ("هندلرِ inline در مارک‌آپ به تابعِ ناموجود",
     mutate(h_go_btn='<button id="go" class="go" onclick="ghostHandler()"'),
     "bad_handlers", "HTML:onclick:ghostHandler", "«ghostHandler»"),
    ("عیب‌نشانِ اصلیِ این چک: x.onclick = نامِ خالیِ ناموجود",
     mutate(h_jb_assign="if(jb) jb.onclick = saveJournalGhost;"),
     "bad_handlers", "HTML:onclick:saveJournalGhost", "«saveJournalGhost»"),
    ("addEventListener با نامِ خالیِ ناموجود",
     mutate(h_leave='chips.addEventListener("mouseleave", closePickSoonGhost);'),
     "bad_handlers", "HTML:addEventListener:closePickSoonGhost", "«closePickSoonGhost»"),
    ("تایمر با نامِ خالیِ ناموجود",
     mutate(h_boot_fn="function pipfoundBootWarn(){\n  setTimeout(ghostTimerFn, 10);"),
     "bad_handlers", "HTML:setTimeout:ghostTimerFn", "«ghostTimerFn»"),
    ("صفحه‌ی دوم: هندلرِ خالیِ ناموجود",
     mutate(f_refresh_assign='$("#refresh").onclick=loadGhost;'),
     "bad_handlers", "FUND_PAGE:onclick:loadGhost", "«loadGhost»"),
    ("صفحه‌ی دوم: تعریفِ صفحه‌ی دیگر آن را ماست نمی‌کند",
     mutate(f_refresh_assign='$("#refresh").onclick=saveJournal;'),
     "bad_handlers", "FUND_PAGE:onclick:saveJournal", "«saveJournal»"),
    ("صفحه‌ی دوم: ارجاع به idی که ساخته نمی‌شود",
     mutate(f_refresh_assign='$("#refreshGhost").onclick=load;'),
     "missing_ids", "FUND_PAGE:refreshGhost", "«refreshGhost»"),
    ("صفحه‌ی دوم: idِ صفحه‌ی دیگر آن را ماست نمی‌کند",
     mutate(f_refresh_assign='$("#sym").onclick=load;'),
     "missing_ids", "FUND_PAGE:sym", "«sym»"),
    ("صفحه‌ی دوم: idِ تکراری",
     mutate(f_next='<div id="nextWrap"></div><div id="nextWrap"></div>'),
     "dups", "FUND_PAGE:nextWrap", "«nextWrap»"),
]
for label, text, key, needle, phrase in REAL:
    r = run_mutation(text)
    text_probs = " | ".join(r["problems"])
    got = sorted(r["w"].get(key) or [])
    check(f"{label} → گیت قرمز می‌شود", r["ok"] is False, "گیت سبز ماند!")
    check(f"{label} → در آمارِ «{key}» می‌آید ({needle})", needle in got, str(got))
    check(f"{label} → پیامش نامِ همان مورد را می‌گوید", phrase in text_probs,
          text_probs[:160])
    check(f"{label} → فقط همین یک مورد گزارش می‌شود", wiring_needles(r) == [needle],
          str(wiring_needles(r)))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۳) جهش‌های بی‌گناه: گیت نباید قرمز شود و هشدارِ دروغ ندهد ═══")
INNOCENT = [
    ("مارک‌آپِ ساخته‌شده داخلِ رشتهٔ JS + id/hash داخلِ رشته و کامنت",
     mutate(h_boot_fn="function pipfoundBootWarn(){\n"
                      "  const t='<div onclick=\"ghostInline()\"></div>';"
                      " const h='#ghostHash';\n"
                      "  /* onclick=\"ghostCm()\" id=\"ghostCmId\" */"),
     True),
    ("هندلرِ فلش/متد به‌جای نامِ خالی (نباید «نامِ خالی» شمرده شود)",
     mutate(h_jb_assign="if(jb) jb.onclick = ()=>saveJournal();"
                        " document.body.onclick = window.saveJournal;"),
     True),
    ("تایمر با نامِ خالیِ تعریف‌شده",
     mutate(h_boot_fn="function pipfoundBootWarn(){\n  setTimeout(saveJournal, 10);"),
     True),
    ("کلاسی که فقط JS عوضش می‌کند (classList.add)",
     mutate(h_sp_head='<div class="sp-head ghost-js">',
            h_boot_fn='function pipfoundBootWarn(){\n'
                      '  document.body.classList.add("ghost-js");'),
     True),
    ("کلاسی که CSS استایلش می‌کند",
     mutate(h_sp_head='<div class="sp-head ghost-css">',
            h_css_rule=".sp-head,.ghost-css{"),
     True),
    ("idِ همنام در سندِ دیگر تکراری نیست (هر سند جدا)",
     mutate(f_next='<div id="nextWrap"></div><div id="result"></div>'),
     True),
    ("عنصرِ کامنت‌شده: idِ داخلِ کامنت موجود/تکراری شمرده نمی‌شود",
     mutate(h_sym_input='<!-- <input id="sym" class="inp"> --><input id="sym" class="inp"'),
     True),
]
for label, text, expect_green in INNOCENT:
    r = run_mutation(text)
    if expect_green:
        check(f"{label} → گیت سبز می‌مانَد", r["ok"], str(r["problems"][:2]))
        check(f"{label} → هیچ خطای اتصالی گزارش نمی‌شود", wiring_needles(r) == [],
              str(wiring_needles(r)))
    else:
        check(f"{label} → گیت قرمز می‌شود", r["ok"] is False, "گیت سبز ماند!")

# ═══════════════════════════════════════════════════════════════════
print("═══ ۴) داراییِ وبِ بیرون: لنگرهای زنده «کدِ مرده» شمرده نمی‌شوند ═══")
# هارنسِ تستِ بصری وجودِ بعضی idها را لازم دارد ولی خودِ app.py هیچ‌جا صدا‌شان
# نمی‌زند؛ اگر هشدارِ «استفاده‌نشده» شاملِ آن‌ها شود، حرفش همان پاک‌کردنِ لنگرِ
# زنده است و لایهٔ ۳ می‌شکند. پس یک جهش داریم که id/کلاس اضافه می‌کند و با/بی
# دارایی سنجیده می‌شود (جهشِ کنترل ثابت می‌کند قاعده واقعاً کار می‌کند).
PIN_ID = mutate(h_sp_head='<div class="sp-head"><i id="ghostPinned"></i>')
CTL = 'const REQUIRED=["ghostPinned"];\n'
pin_no = run_mutation(PIN_ID)
pin_yes = run_mutation(PIN_ID, extra={"ui_visual_check.cjs": CTL})
check("بدونِ داراییِ وب → idِ بی‌ارجاع هشدار می‌گیرد (جهشِ کنترل)",
      "HTML:ghostPinned" in unused_needles(pin_no), str(unused_needles(pin_no)))
check("داراییِ وب که نامش را پین کرده → دیگر هشدار نمی‌گیرد",
      "HTML:ghostPinned" not in unused_needles(pin_yes), str(unused_needles(pin_yes)))
check("داراییِ وب واقعاً خوانده شده (ضدِ ناوَکوم)",
      "ui_visual_check.cjs" in (pin_yes["w"].get("assets") or []),
      str(pin_yes["w"].get("assets")))
check("خواندنِ دارایی گیت را قرمز نمی‌کند", pin_yes["ok"], str(pin_yes["problems"][:2]))

PIN_CLS = mutate(h_sp_head='<div class="sp-head ghost-pin-cls">')
cls_no = run_mutation(PIN_CLS)
cls_yes = run_mutation(PIN_CLS, extra={"ui_visual_check.cjs": 'q(".ghost-pin-cls");\n'})
check("بدونِ داراییِ وب → کلاسِ بی‌استایل هشدار می‌گیرد (جهشِ کنترل)",
      "HTML:ghost-pin-cls" in unused_needles(cls_no), str(unused_needles(cls_no)))
check("داراییِ وب که کلاسش را می‌گیرد → هشدار نمی‌گیرد",
      "HTML:ghost-pin-cls" not in unused_needles(cls_yes), str(unused_needles(cls_yes)))

# و روی مخزنِ واقعی: لنگرهای خودِ هارنسِ بصری نباید «مرده» نام بگیرند.
_ctext, _cnames = SC.consumer_assets(HERE)
_real_probs, _real_warns, real_st = SC.wiring_problems(SC.page_sources(HERE), _ctext)
check("مخزنِ واقعی: هارنسِ بصری به‌عنوانِ دارایی خوانده می‌شود (ضدِ ناوَکوم)",
      "ui_visual_check.cjs" in _cnames and "btPanel" in _ctext, str(_cnames))
check("مخزنِ واقعی: لنگرهای هارنس (btPanel/riskPanel/alarmsDock) هشدار نمی‌گیرند",
      not ({"HTML:btPanel", "HTML:riskPanel", "HTML:alarmsDock"}
           & set(real_st.get("unused_ids") or [])), str(real_st.get("unused_ids")))
check("مخزنِ واقعی: گیتِ قائل به دارایی هنوز خطایی گزارش نمی‌کند",
      wiring_needles({"w": real_st}) == [], str(real_st))
# قفلِ پاکیزگی: مخزن نباید کدِ مردهٔ شناسه‌ای داشته باشد. خطِ گیت برای
# «استفاده‌نشده» همچنان هشدار است (کدِ مرده سرور را برنمی‌گرداند)، ولی در
# لایهٔ جهش‌آزمایی بلند می‌شکند تا دوباره هشدارِ بی‌صاحب روی هم تلنبار نشود.
check("مخزنِ واقعی: هیچ id/کلاسِ استفاده‌نشده‌ای نمانده (کدِ مرده صفر)",
      not (real_st.get("unused_ids") or real_st.get("unused_classes")),
      str(list(real_st.get("unused_ids") or []) + list(real_st.get("unused_classes") or [])))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۵) خودِ چک مستقل از مبنای کلیدها و بی‌نتیجه نیست ═══")
probs, warns, st0 = SC.wiring_problems({})
check("بدونِ صفحه → نه خطا، نه هشدار، و آمارِ صفر (سبزِ دروغ نمی‌دهد)",
      probs == [] and warns == [] and st0.get("ids") == 0 and st0.get("refs") == 0,
      str(st0))
empty = tempfile.mkdtemp(prefix="pf_wiring_empty_")
try:
    check("پوشه‌ی بدونِ app.py → گیتِ کلِ لایه‌ی ۱ سبز نمی‌مانَد",
          SC.run_checks(empty)["ok"] is False, "گیت سبز شد!")
finally:
    shutil.rmtree(empty, ignore_errors=True)

# ─────────────────────────────────────────────────────────────
print()
if FAILS:
    print(f"❌ {len(FAILS)} بررسی از {len(CHECKS)} بررسی رد شد:")
    for n, det in FAILS:
        print(f"   • {n}" + (f"  →  {det}" if det else ""))
    sys.exit(1)
print(f"✅ همه‌ی {len(CHECKS)} بررسیِ جهش‌آزماییِ «اتصالِ HTML و JS» سبز شد.")
sys.exit(0)
