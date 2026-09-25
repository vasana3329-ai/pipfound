#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""جهش‌آزماییِ لایه‌ی ۱ نگهبان: «قراردادِ PWA» (سرویس‌ورکر ↔ مانیفست ↔ خودِ اپ).

چرا لازم است: `node --check` فقط بلوک‌های <script> صفحه را می‌بیند، و هیچ لایه‌ای
وعده‌های سرویس‌ورکر و مانیفست را با واقعیتِ سرور مقابله نمی‌کرد. چهار خرابیِ
کاملاً بی‌صدا از همان شکاف می‌آید:

  ۱) آیکونی که مانیفست (یا خودِ صفحه) اعلام می‌کند ولی فایلش نیست یا مسیرش سرو
     نمی‌شود → نصبِ اپ با آیکونِ شکسته، بدونِ هیچ خطایی.
  ۲) مسیری که در پوسته‌ی کش پیش‌کش می‌شود ولی روی سرور وجود ندارد → `addAll`
     رد می‌شود، `catch` خفه‌اش می‌کند و سرویس‌ورکر **هیچ‌چیز** را پیش‌کش نکرده
     بالا می‌آید (آفلاینِ خالی، بدونِ هیچ علامتی).
  ۳) `addAll(نامِ غلط)` یا نامِ ناهمخوانِ کش → ReferenceError سرِ نصب، یا پاک‌شدنِ
     کشی که fetch در آن می‌نویسد؛ در هر دو حالت سرویس‌ورکر بی‌اثر است.
  ۴) کش‌کردنِ پاسخِ ناموفق (بدونِ گاردِ `res.ok`) یا کش‌کردنِ `/api/` → یک ۴۰۴/۵۰۰
     گذرا یا داده‌ی زنده تا ارتقای کش گیر می‌مانَد.

و برعکسش سنجیده می‌شود که این چک بی‌دلیل قرمز نکند: کامنتِ حاویِ مسیر، مرتب‌کردنِ
پوستهٔ کش، افزودنِ آیکونِ **کاملاً سیم‌کشی‌شده**، افزودنِ یک مسیرِ سرو‌شده به
پوسته، و تغییرِ نامِ متغیرهای محلی.

کاملاً آفلاین و قطعی: هر جهش روی کپیِ موقتِ فایل‌های همراهِ app.py اجرا می‌شود و
به سرورِ 8787 دست نمی‌زند.

اجرا:  python3 pwa_contract_test.py        (خروجی ۰ = سالم)
"""
import json
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


# فایل‌های همراهی که اپِ واقعی در همین پوشه دارد. محیطِ جهش باید مثلِ مخزن
# باشد، وگرنه نگهبان «وعده‌ی بی‌فایل» می‌بیند و شمارِ خطاهای کاذب بالا می‌رود.
COMPANIONS = ("app.py", "sw.js", "manifest.webmanifest",
              "icon-180.png", "icon-192.png", "icon-192-mask.png",
              "icon-512.png", "icon-512-mask.png")

APP = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
SW = open(os.path.join(HERE, "sw.js"), encoding="utf-8").read()
MAN = open(os.path.join(HERE, "manifest.webmanifest"), encoding="utf-8").read()

# لنگرهای جهش — اگر روزی ساختارِ sw.js/مانیفست/app.py عوض شود، تست باید
# **بلند** بشکند نه بی‌صدا سبز شود.
SW_ANCHORS = {
    "cache_const": 'const CACHE = "pipfound-__CACHE_REV__";',
    "skip_handler": 'if (d.type === "SKIP_WAITING") { self.skipWaiting(); return; }',
    "msg_listener": 'self.addEventListener("message", (e) => {',
    "verify_call": "    let healthy = await shellHealthy(CACHE);",
    "verify_body": "    const c = await caches.open(name);\n"
                   "    for (const p of SHELL) {",
    "safe_gate": "    if (healthy) {",
    "cache_pref": '.catch(() => fromCache(req).then((hit) => hit || caches.match("/")))',
    "open_param": "const c = await caches.open(name);",
    "shell_head": '  "/", "/manifest.webmanifest",',
    "shell_icons": '  "/icon-180.png", "/icon-192.png", "/icon-512.png",',
    "addall": ".then((c) => c.addAll(SHELL))",
    "install_listener": 'self.addEventListener("install", (e) => {',
    "api_bypass": 'if (url.pathname.startsWith("/api/")) return;',
    "icon_regex": "/^\\/icon-.*\\.png$/.test(url.pathname) ||",
    "icon_branch_head": "caches.match(req).then((hit) => hit || fetch(req).then((res) => {",
    "icon_guard": ("if (res && res.ok) {\n"
                   "          const copy = res.clone();\n"
                   "          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});\n"
                   "        }\n"
                   "        return res;\n"
                   "      }))"),
    "netfirst_guard": ("fetch(req)\n"
                       "      .then((res) => {\n"
                       "        if (res && res.ok) {\n"
                       "          const copy = res.clone();\n"
                       "          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});\n"
                       "        }\n"
                       "        return res;\n"
                       "      })"),
    "open_icon": "caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});",
    "fallback": '.catch(() => fromCache(req).then((hit) => hit || caches.match("/")))',
}

APP_ANCHORS = {
    "static_tuple": 'if u.path in ("/manifest.webmanifest", "/sw.js", "/icon-180.png",',
    "sw_register": 'navigator.serviceWorker.register("/sw.js")',
    "manifest_link": '<link rel="manifest" href="/manifest.webmanifest">',
    "token_decl": 'CACHE_REV_TOKEN = "__CACHE_REV__"',
    "sw_swap": 'body = f.read().replace(CACHE_REV_TOKEN,',
    "banner_markup": '<div class="updbar" id="pfSwBanner" role="status" aria-live="polite">',
    "skip_msg": 'pfReg.waiting.postMessage({type:"SKIP_WAITING"});',
    "asked_flag": 'pfAsked=true;',
    "cb_gate": 'if(!pfAsked || pfReloading) return;',
    "cb_reload": 'pfReloading=true;\n    location.reload();',
}


def mutate_sw(old, new, count=1):
    if SW_ANCHORS[old] not in SW:
        raise SystemExit(f"❌ لنگرِ sw.js پیدا نشد: {old} → {SW_ANCHORS[old]!r}")
    return SW.replace(SW_ANCHORS[old], new, count)


def mutate_app(old, new):
    if APP_ANCHORS[old] not in APP:
        raise SystemExit(f"❌ لنگرِ app.py پیدا نشد: {old} → {APP_ANCHORS[old]!r}")
    return APP.replace(APP_ANCHORS[old], new, 1)


def manifest(**over):
    man = json.loads(MAN)
    for k, v in over.items():
        if k == "icon":
            man["icons"] = list(man["icons"]) + [v]
        else:
            man[k] = v
    return json.dumps(man, ensure_ascii=False, indent=2)


def run_mutation(app=None, sw=None, man=None, files=None):
    """کپیِ موقتِ اپ + جهش‌ها، و پرسیدنِ نظرِ خودِ گیتِ لایه‌ی ۱.

    `files` = {نام: بایت‌ها} برای افزودن، یا {نام: None} برای حذفِ فایل."""
    d = tempfile.mkdtemp(prefix="pf_pwa_")
    try:
        for nm in COMPANIONS:
            src = os.path.join(HERE, nm)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(d, nm))
        if app is not None:
            with open(os.path.join(d, "app.py"), "w", encoding="utf-8") as f:
                f.write(app)
        if sw is not None:
            with open(os.path.join(d, "sw.js"), "w", encoding="utf-8") as f:
                f.write(sw)
        if man is not None:
            with open(os.path.join(d, "manifest.webmanifest"), "w", encoding="utf-8") as f:
                f.write(man)
        for nm, body in (files or {}).items():
            p = os.path.join(d, nm)
            if body is None:
                if os.path.exists(p):
                    os.remove(p)
            else:
                with open(p, "wb") as f:
                    f.write(body)
        rep = SC.run_checks(d)
        probs = rep.get("problems") or []
        return {"ok": rep["ok"], "problems": probs,
                "pwa": [p for p in probs if p.startswith("PWA →")],
                "warnings": rep.get("warnings") or [],
                "stats": rep.get("pwa") or {},
                "text": " | ".join(probs)}
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════
print("═══ ۰) لنگرهای جهش موجودند (تست نباید بی‌صدا سبز شود) ═══")
for k, v in SW_ANCHORS.items():
    check(f"لنگرِ sw.js «{k}» موجود است", v in SW, v)
for k, v in APP_ANCHORS.items():
    check(f"لنگرِ app.py «{k}» موجود است", v in APP, v)
_missing = [n for n in COMPANIONS if not os.path.exists(os.path.join(HERE, n))]
check("همه‌ی فایل‌های همراهِ اپ سرِ جایشان‌اند (محیطِ جهش مثلِ مخزن است)",
      _missing == [], str(_missing))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۱) مخزنِ سالم: سبز، ولی با شمردنِ واقعی (ضدِ ناوَکوم) ═══")
base = run_mutation()
st = base["stats"]
check("گیتِ لایه‌ی ۱ روی کدِ سالم سبز است", base["ok"], str(base["problems"][:3]))
check("هیچ گزارشی از بندِ PWA نمی‌آید", base["pwa"] == [], str(base["pwa"]))
check("وعده‌ها واقعاً شمرده شده‌اند (ضدِ ناوَکوم)", st.get("promised", 0) >= 4,
      str(st.get("promised")))
check("پوستهٔ کش واقعاً خوانده شده (ضدِ ناوَکوم)", st.get("shell", 0) >= 6,
      str(st.get("shell")))
check("آیکون‌های مانیفست شمرده شده‌اند (ضدِ ناوَکوم)", st.get("icons", 0) >= 3,
      str(st.get("icons")))
check("نامِ کش خوانده شده و جای‌گذارِ بازنگری در آن است",
      st.get("cache") == "pipfound-__CACHE_REV__", str(st.get("cache")))
check("نسخه‌بندیِ خودکارِ کش سنجیده و تأیید شد", st.get("cache_rev") is True, str(st))
check("بنرِ «نسخهٔ تازه» در صفحه پیدا شد", st.get("update_banner") is True, str(st))
check("قراردادِ ارتقای ایمن (سنجش + گاردِ حذف + فالبکِ کشِ فعال) تأیید شد",
      st.get("safe_upgrade") is True, str(st))
check("مسیرهای سرو‌شده‌ی app.py خوانده شده‌اند (ضدِ ناوَکوم)", st.get("served", 0) >= 8,
      str(st.get("served")))
check("«/api/» مستثنا است", st.get("api_bypass") is True, str(st))
check("فالبکِ آفلاین دیده می‌شود", st.get("offline") is True, str(st))
check("شاخهٔ آیکون کش‌اول است", st.get("cache_first_icons") is True, str(st))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۲) جهش‌های واقعی: گیت باید قرمز شود و علت را بگوید ═══")


def expect_red(label, phrase, **kw):
    r = run_mutation(**kw)
    check(f"{label} → گیت قرمز می‌شود", r["ok"] is False, "گیت سبز ماند!")
    check(f"{label} → از بندِ PWA گزارش می‌آید", bool(r["pwa"]), r["text"][:200])
    check(f"{label} → پیامش علت را می‌گوید", phrase in r["text"], r["text"][:220])
    return r


expect_red("مسیرِ ناموجود در پوستهٔ کش",
           "در پوستهٔ کش است ولی app.py سروش نمی‌کند",
           sw=mutate_sw("shell_head", '  "/", "/manifest.webmanifest", "/icon-999.png",'))
r = expect_red("فایلِ پوستهٔ کش روی دیسک نیست (مسیر هست، فایل نیست)",
               "روی دیسک نیست",
               app=mutate_app("static_tuple",
                              'if u.path in ("/icon-777.png", "/manifest.webmanifest", "/sw.js", "/icon-180.png",'),
               sw=mutate_sw("shell_head",
                            '  "/", "/manifest.webmanifest", "/icon-777.png",'))
check("...و همان یک گزارشِ PWA صادر می‌شود", len(r["pwa"]) == 1, str(r["pwa"]))

expect_red("دادهٔ زنده در پوستهٔ کش",
           "دادهٔ زنده هرگز نباید کش شود",
           sw=mutate_sw("shell_head",
                        '  "/", "/manifest.webmanifest", "/api/health",'))

r = expect_red("آیکونِ مانیفست که فایلش نیست",
               "فایلش روی دیسک نیست",
               man=manifest(icon={"src": "/icon-999.png", "sizes": "192x192",
                                  "type": "image/png"}))
check("...و فقط یک گزارش می‌دهد", len(r["pwa"]) == 1, str(r["pwa"]))

expect_red("آیکونِ مانیفست روی دیسک هست ولی سرو نمی‌شود",
           "سرو نمی‌شود — نصبِ اپ با آیکونِ شکسته",
           man=manifest(icon={"src": "/favicon.ico", "sizes": "16x16",
                              "type": "image/png"}),
           files={"favicon.ico": b"\x00\x00\x01\x00"})

expect_red("آیکونِ مانیفست پیش‌کش نشده",
           "در پوستهٔ کش پیش‌کش نشده",
           sw=mutate_sw("shell_icons", '  "/icon-180.png", "/icon-192.png",'))

expect_red("لینکِ مانیفست به فایلی که نیست",
           "فایلش کنارِ app.py نیست",
           man=None, files={"manifest.webmanifest": None})

expect_red("ثبتِ سرویس‌ورکر برای فایلی که نیست",
           "فایلش کنارِ app.py نیست",
           sw=None, files={"sw.js": None})

expect_red("مسیرِ سرویس‌ورکر در app.py سرو نمی‌شود",
           "ثبتِ سرویس‌ورکر ۴۰۴ می‌دهد",
           app=mutate_app("static_tuple",
                          'if u.path in ("/manifest.webmanifest", "/icon-180.png",'))

expect_red("مسیرِ مانیفست در app.py سرو نمی‌شود",
           "لینکِ مانیفست ۴۰۴ می‌دهد",
           app=mutate_app("static_tuple",
                          'if u.path in ("/sw.js", "/icon-180.png",'))

expect_red("ثبتِ سرویس‌ورکر برای مسیری که سرو نمی‌شود",
           "ثبتِ سرویس‌ورکر ۴۰۴ می‌دهد",
           app=mutate_app("sw_register",
                          'navigator.serviceWorker.register("/ghost-sw.js")'))

expect_red("صفحه دیگر سرویس‌ورکر را ثبت نمی‌کند (PWA بی‌صدا خاموش)",
           "هیچ‌جا ثبتش نمی‌کند",
           app=mutate_app("sw_register", "navigator.serviceWorker"))

expect_red("هندلرِ «/api/» از fetch برداشته شده",
           "دادهٔ زنده کش می‌شود",
           sw=mutate_sw("api_bypass", 'if (url.pathname.startsWith("/api-x/")) return;'))

expect_red("فالبکِ آفلاین برداشته شده",
           "پشتوانهٔ کش ندارد",
           sw=mutate_sw("fallback", ".catch(() => {})"))

expect_red("گاردِ res.ok از شاخهٔ شبکه‌اول برداشته شده",
           "بدونِ گاردِ «res.ok»",
           sw=mutate_sw("netfirst_guard",
                        "fetch(req)\n"
                        "      .then((res) => {\n"
                        "        const copy = res.clone();\n"
                        "        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});\n"
                        "        return res;\n"
                        "      })"))

expect_red("گاردِ res.ok از شاخهٔ کش‌اولِ آیکون برداشته شده",
           "بدونِ گاردِ «res.ok»",
           sw=mutate_sw("icon_guard",
                        "const copy = res.clone();\n"
                        "          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});\n"
                        "        return res;\n"
                        "      }))"))

expect_red("نامِ کشِ ناهمخوان در caches.open",
           "با نامِ کشِ اعلام‌شده",
           sw=mutate_sw("open_icon",
                        'caches.open("pipfound-v2").then((c) => c.put(req, copy)).catch(() => {});'))

expect_red("addAll به آرایه‌ای که تعریف نشده",
           "آرایه‌ای اشاره می‌کند که تعریف نشده",
           sw=mutate_sw("addall", ".then((c) => c.addAll(SHELLS))"))

expect_red("شاخهٔ آیکون دیگر کش‌اول نیست",
           "fetch قبل از caches.match",
           sw=mutate_sw("icon_branch_head", "fetch(req).then((res) => {"))

expect_red("هندلرِ install برداشته شده",
           "هندلرِ «install» را ندارد",
           sw=mutate_sw("install_listener",
                        'self.addEventListener("installing", (e) => {'))

expect_red("start_url به مسیری که سرو نمی‌شود",
           "در app.py سرو نمی‌شود",
           man=manifest(start_url="/app"))

expect_red("نامِ کش دستی/ثابت شده (دیگر به بازنگریِ کد گره نخورده)",
           "دستی و ثابت است",
           sw=mutate_sw("cache_const", 'const CACHE = "pipfound-v1";'))

expect_red("جای‌گذار در app.py اعلام نشده (سرور نمی‌داند چه را جانشین کند)",
           "در app.py اعلام نشده",
           app=mutate_app("token_decl", 'CACHE_REV_TOKEN_OLD = "__CACHE_REV__"'))

expect_red("جای‌گذارِ app.py با جای‌گذارِ sw.js نمی‌خواند",
           "نمی‌خواند",
           app=mutate_app("token_decl", 'CACHE_REV_TOKEN = "__CACHE_REV_X__"'))

expect_red("پاسخِ /sw.js بدونِ جانشینیِ نامِ کش سرو می‌شود",
           "بدونِ جانشینیِ",
           app=mutate_app("sw_swap", "body = f.read()"))

expect_red("skipWaiting بی‌قید سرِ نصب (بنر بی‌معنا می‌شود)",
           "سرِ نصب `skipWaiting` می‌زند",
           sw=mutate_sw("addall", ".then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())"))

expect_red("هندلرِ message پیامِ SKIP_WAITING را نمی‌شناسد",
           "به هندلرِ message سرویس‌ورکر نمی‌رسد",
           sw=mutate_sw("skip_handler", 'if (d.type === "SKIP_GO") { self.skipWaiting(); return; }'))

expect_red("هندلرِ message سرویس‌ورکر برداشته شده",
           "به هندلرِ message سرویس‌ورکر نمی‌رسد",
           sw=mutate_sw("msg_listener", 'self.addEventListener("msging", (e) => {'))

expect_red("بنرِ «نسخهٔ تازه» از صفحه برداشته شده",
           "عنصرِ بنرِ «pfSwBanner» را نمی‌سازد",
           app=mutate_app("banner_markup", '<div class="updbar" id="pfSwBannerGhost" role="status">'))

expect_red("صفحه پیامِ SKIP_WAITING را نمی‌فرستد (دکمهٔ بنر بی‌اثر)",
           "پیامِ SKIP_WAITING نمی‌فرستد",
           app=mutate_app("skip_msg", 'pfReg.waiting.postMessage({type:"SKIP_LATER"});'))

expect_red("رفرشِ صفحه پس از جانشینی برداشته شده",
           "خودش را تازه نمی‌کند",
           app=mutate_app("cb_reload", "pfReloading=true;"))

expect_red("قیدِ «تأییدِ کاربر» از رفرشِ جانشینی برداشته شده",
           "هیچ قیدِ «تأییدِ کاربر» ندارد",
           app=mutate_app("cb_gate", "// بی‌قید شد"))

expect_red("نشانِ «کاربر خواسته» هیچ‌وقت ست نمی‌شود (رفرشِ بی‌اجازه)",
           "به نشانِ «کاربر خواسته» گره نخورده",
           app=mutate_app("asked_flag", ""))

expect_red("پاک‌کردنِ کشِ قبلی بی‌قید شد (دیگر به تأییدِ پوستهٔ تازه گره نخورده)",
           "به تأییدِ پوستهٔ تازه گره",
           sw=mutate_sw("safe_gate", "    if (true) {"))

expect_red("هر دو مسیرِ سنجش بی‌سنجش شدند (فقط ترمیم صدا زده می‌شود)",
           "به تأییدِ پوستهٔ تازه گره نخورده",
           sw=mutate_sw("verify_call", "    let healthy = true;")
              .replace("      healthy = await shellHealthy(CACHE);",
                       "      healthy = true;", 1))

# جهشِ «حذفِ کاملِ سنجش از activate» (هم مسیرِ اولیه هم مسیرِ ترمیم): تابعِ
# سنجش سرِ جایش هست ولی هیچ‌جا در activate خوانده نمی‌شود.
expect_red("activate هیچ سنجشگری را صدا نمی‌زند (سنجش و ترمیم هر دو حذف شد)",
           "activate درستیِ پوستهٔ تازه را نمی‌سنجد",
           sw=mutate_sw("verify_call", "    let healthy = true;")
              .replace("      healthy = await shellHealthy(CACHE);",
                       "      healthy = true;", 1)
              .replace("      await healFromOld();", "      void 0;", 1))

expect_red("هیچ تابعی برای سنجشِ درستیِ پوسته نمانده (فقط ترمیم)",
           "به تأییدِ پوستهٔ تازه گره نخورده",
           sw=mutate_sw("verify_body",
                        "    const c = await caches.open(name);\n"
                        "    for (const p of []) {"))

expect_red("هیچ تابعی SHELL را نمی‌سنجد (سنجش و ترمیم هر دو برداشته شده)",
           "تابعی برای سنجشِ درستیِ پوستهٔ کش ندارد",
           sw=SW.replace("for (const p of SHELL) {", "for (const p of []) {"))

expect_red("فالبکِ کش کشِ فعال را در اولویت نمی‌گذارد",
           "کشِ فعالِ همین نسخه را در اولویت نمی‌گذارد",
           sw=mutate_sw("cache_pref",
                        '.catch(() => caches.match(req).then((hit) => hit || caches.match("/")))'))

r = expect_red(
    "caches.open یک ثابتِ رشته‌ایِ *متفاوت* را باز می‌کند",
    "را باز می‌کند که با نامِ کشِ اعلام‌شده",
    sw=mutate_sw("cache_const",
                 'const CACHE = "pipfound-__CACHE_REV__";\nconst OLD_CACHE = "pipfound-v9";')
       .replace(SW_ANCHORS["open_param"], "const c = await caches.open(OLD_CACHE);", 1))
check("...و همان یک گزارش را می‌دهد", len(r["pwa"]) == 1, str(r["pwa"]))

expect_red("خطای سینتکس در sw.js",
           "خطای سینتکس دارد",
           sw=SW.replace(SW_ANCHORS["cache_const"],
                         SW_ANCHORS["cache_const"] + "\nconst broken = ;"))

expect_red("آیکون با نامی که با قاعدهٔ کش‌اول نمی‌خواند",
           "با قاعدهٔ کش‌اولِ آیکون در sw.js نمی‌خواند",
           app=mutate_app("static_tuple",
                          'if u.path in ("/icon-256.webp", "/manifest.webmanifest", "/sw.js", "/icon-180.png",'),
           sw=mutate_sw("shell_head",
                        '  "/", "/manifest.webmanifest", "/icon-256.webp",'),
           man=manifest(icon={"src": "/icon-256.webp", "sizes": "256x256",
                              "type": "image/webp"}),
           files={"icon-256.webp": b"RIFF0000WEBP"})

# ═══════════════════════════════════════════════════════════════════
print("═══ ۳) جهش‌های بی‌گناه: نباید قرمز شوند ══════════════════════════════")


def expect_green(label, **kw):
    r = run_mutation(**kw)
    check(f"{label} → گیت سبز می‌مانَد", r["ok"], str(r["problems"][:2]))
    check(f"{label} → هیچ گزارشِ PWA نمی‌دهد", r["pwa"] == [], str(r["pwa"])[:200])
    return r


CLEAN_ICON = {
    "app": APP.replace(APP_ANCHORS["static_tuple"],
                       'if u.path in ("/icon-256.png", "/manifest.webmanifest", "/sw.js", "/icon-180.png",'),
    "sw": mutate_sw("shell_icons",
                    '  "/icon-256.png",\n' + SW_ANCHORS["shell_icons"]),
    "man": manifest(icon={"src": "/icon-256.png", "sizes": "256x256",
                          "type": "image/png"}),
    "files": {"icon-256.png": b"\x89PNG\r\n\x1a\n"},
}
expect_green("آیکونِ تازه‌ی کاملاً سیم‌کشی‌شده (دیسک + مسیر + مانیفست + پوسته)",
             **CLEAN_ICON)

expect_green("کامنتِ بلوکیِ حاویِ مسیرِ ناموجود داخلِ پوستهٔ کش",
             sw=mutate_sw("shell_icons",
                          '  /* "/ghost.png", */\n' + SW_ANCHORS["shell_icons"]))

expect_green("کامنتِ خطیِ حاویِ مسیرِ ناموجود کنارِ قاعدهٔ fetch",
             sw=mutate_sw("api_bypass",
                          SW_ANCHORS["api_bypass"] + "  // /ghost.png")) 

expect_green("مرتب‌کردنِ ورودی‌های پوستهٔ کش (بدونِ تغییرِ محتوا)",
             sw=mutate_sw("shell_icons",
                          '  "/icon-512.png", "/icon-192.png", "/icon-180.png",'))

expect_green("افزودنِ یک مسیرِ سرو‌شده (صفحهٔ فاندمنتال) به پوستهٔ کش",
             sw=mutate_sw("shell_head",
                          '  "/", "/manifest.webmanifest", "/fundamental",'))

expect_green("فاصله/خطِ خالیِ اضافه در sw.js",
             sw=SW.replace(SW_ANCHORS["cache_const"],
                           "\n" + SW_ANCHORS["cache_const"] + "\n"))

_renamed = (SW.replace("(res) => {", "(resp) => {")
              .replace("res.ok", "resp.ok").replace("res.clone()", "resp.clone()")
              .replace("return res;", "return resp;"))
check("جهشِ «تغییرِ نامِ متغیرِ محلی» واقعاً اعمال شد", _renamed != SW)
expect_green("تغییرِ نامِ متغیرهای محلی (res → resp)", sw=_renamed)

expect_green("دکمهٔ «نصب» و بقیهٔ صفحه دست‌نخورده (فقط یک ویرایشِ بی‌ربط در app.py)",
             app=APP.replace('<h2>📊 چارتِ زنده', '<h2>📈 چارتِ زنده'))

# نامِ متغیرهای محلیِ صفحه و نامِ تابعِ بازنگری در app.py جزوِ قرارداد نیستند؛
# جهشِ تغییرِ نام باید سبز بماند وگرنه نگهبان به «سبکِ کد» گیر می‌دهد.
_ren = (APP.replace("pfReg", "pfReg2").replace("pfReloading", "pfBusy")
           .replace("pfAsked", "pfAskedUser").replace("cache_rev", "sw_cache_rev"))
check("جهشِ «تغییرِ نامِ متغیر» واقعاً اعمال شد", _ren != APP)
expect_green("تغییرِ نامِ متغیرهای محلیِ بنر و تابعِ بازنگری", app=_ren)

expect_green("کامنتِ حاویِ «skipWaiting»/«caches.delete» در sw.js (کامنت قرارداد نیست)",
             sw=mutate_sw("safe_gate",
                          "    // caches.delete(k) عمداً بعد از تأیید\n    if (healthy) {"))

# پارامترِ قابلِ حل نبودن: `caches.open(name)` (خواندنِ کش‌های دیگر برای ترمیم)
# نباید «نامِ ناهمخوان» شمرده شود — این مثبتِ کاذب در توسعه دیده شد.
expect_green("caches.open با پارامترِ متغیر (خواندنِ کش‌های دیگر برای ترمیم)",
             sw=SW)

_hoisted = (SW.replace(SW_ANCHORS["verify_call"], "    let healthy = true;", 1)
               .replace('    if (healthy) {',
                        "    if (await shellHealthy(CACHE)) {", 1))
check("جهشِ «سنجشِ درون‌خطی بدونِ متغیر» واقعاً اعمال شد", _hoisted != SW)
expect_green("سنجشِ درون‌خطی بدونِ متغیرِ واسط (همان قرارداد، سبکِ متفاوت)",
             sw=_hoisted)

expect_green("کامنتِ حاویِ «skipWaiting» در sw.js (کامنت قرارداد نیست)",
             sw=mutate_sw("msg_listener", "// skipWaiting فقط با پیامِ کاربر\n"
                           + SW_ANCHORS["msg_listener"]))

# ═══════════════════════════════════════════════════════════════════
print("═══ ۴) چک بی‌نتیجه (ناوَکوم) نیست و پوشهٔ بی‌PWA را نمی‌ترساند ═══")
_p, _w, _s = SC.pwa_contract_problems("/nonexistent-pf-pwa-root")
check("پوشهٔ ناموجود: نه خطا، نه هشدار، آمارِ صفر",
      _p == [] and _w == [] and _s.get("shell") == 0 and _s.get("promised") == 0,
      str(_s))

d = tempfile.mkdtemp(prefix="pf_pwa_bare_")
try:
    with open(os.path.join(d, "app.py"), "w", encoding="utf-8") as f:
        f.write('PAGE = """<html><body>hi</body></html>"""\n')
    check("پوشهٔ بی‌PWA (نه sw.js نه مانیفست، صفحه هم وعده‌ای نمی‌دهد): سبز می‌مانَد",
          SC.pwa_contract_problems(d)[0] == [], str(SC.pwa_contract_problems(d)[0]))
finally:
    shutil.rmtree(d, ignore_errors=True)

d = tempfile.mkdtemp(prefix="pf_pwa_empty_")
try:
    check("پوشهٔ بدونِ app.py → گیتِ کلِ لایه‌ی ۱ سبز نمی‌مانَد",
          SC.run_checks(d)["ok"] is False, "گیت سبز شد!")
finally:
    shutil.rmtree(d, ignore_errors=True)

# ─────────────────────────────────────────────────────────────
print()
if FAILS:
    print(f"❌ {len(FAILS)} بررسی از {len(CHECKS)} بررسی رد شد:")
    for n, det in FAILS:
        print(f"   • {n}" + (f"  →  {det}" if det else ""))
    sys.exit(1)
print(f"✅ همه‌ی {len(CHECKS)} بررسیِ جهش‌آزماییِ «قراردادِ PWA» سبز شد.")
sys.exit(0)
