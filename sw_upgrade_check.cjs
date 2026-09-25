#!/usr/bin/env node
/**
 * لایه‌ی ۳.۵: **ارتقای ایمنِ نسخه** در مرورگرِ واقعی — ترمیم و برگردان.
 *
 * چرا لازم است: لایه‌ی ۱ قراردادِ ارتقا را استاتیک می‌سنجد (سنجشِ درستیِ پوسته +
 * گاردِ حذف + فالبکِ کشِ فعال) و لایه‌ی ۳ آفلاینِ نسخه‌ی سالم را اجرا می‌کند؛ ولی
 * هیچ‌کدام **مسیرِ خرابیِ زمانِ اجرا** را اجرا نمی‌کنند: نصبِ سرویس‌ورکر می‌تواند
 * نیمه‌کاره بماند (یک ۴۰۴ از سرور، خطای گذرا، شبکه‌ی قطع) و آن‌وقت کشِ سالمِ
 * قبلی اگر بی‌قید پاک شود، آفلاینِ کاربر **برنمی‌گردد**. این تست سه نسخه را
 * پشتِ‌سرِ‌هم روی یک مرورگر اجرا می‌کند:
 *
 *   ۱) نسخه‌ی سالم → کشِ کاملِ مبنا.
 *   ۲) نسخه‌ی ناقصِ **ترمیم‌شدنی**: نصبِ نسخه‌ی تازه رد می‌شود (یک آیکونِ پوسته
 *      ۴۰۴ می‌دهد) و کشِ قبلی سالم است ⇒ باید از کشِ قبلی **ترمیم** شود، بعد
 *      کهنه‌ها پاک شوند و آفلاین کامل بماند.
 *   ۳) نسخه‌ی ناقصِ **ترمیم‌نشدنی**: کشِ فعال حالا همان آیکون را ندارد ⇒ ترمیم
 *      ممکن نیست و باید **برگردان** رخ دهد: کشِ سالمِ قبلی پاک نشود، اپ آفلاین
 *      باز شود و کاربر بفهمد نسخه برگشته است.
 *
 * خرابیِ زمانِ اجرا عمداً «پوسته‌ی غلط در متنِ sw.js» نیست (آن را لایه‌ی ۱
 * می‌گیرد و خودِ اپ هم هنگامِ بوت نسخه‌ی سالم را برمی‌گرداند): یک **۴۰۴ِ زمانِ
 * درخواست** برای یک آیکونِ موجود در کپیِ موقتِ اپ تزریق می‌شود؛ فایل روی دیسک
 * هست، مسیرش سرو می‌شود، پس نگهبانِ استاتیک سبز می‌ماند ولی `addAll` سرِ نصب
 * رد می‌شود — همان کلاسی که فقط در مرورگر معلوم می‌شود.
 *
 * هیچ چیزی به مخزن یا اپِ زنده دست نمی‌زند: همه‌چیز در یک کپیِ موقت با سرورِ
 * جداگانه روی پورتی دیگر اجرا می‌شود. خروجی: ۰ سالم، ۱ خراب.
 *
 * استفاده:
 *   PF_PUPPETEER_DIR=/path/node_modules \
 *   PF_BROWSER="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
 *     node sw_upgrade_check.cjs --port 8795
 */
const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");

function arg(name, def) {
  const i = process.argv.indexOf("--" + name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

const HERE = __dirname;
const MODDIR = process.env.PF_PUPPETEER_DIR || "";
const BROWSER = process.env.PF_BROWSER || "";
const PY = process.env.PF_PYTHON || "python3";
const PORT = Number(arg("port", "8795"));
const URL = `http://127.0.0.1:${PORT}/`;
const SKIP_DIRS = new Set([".git", "__pycache__", "node_modules"]);
const VICTIM = "/icon-192-mask.png";        // آیکونی که نسخه‌ی تازه سرِ نصب نمی‌گیرد
const INJECT_ANCHOR = '        if u.path in ("/manifest.webmanifest", "/sw.js", "/icon-180.png",';
/* هر «نسخه» باید بازنگریِ *متمایز* داشته باشد؛ وگرنه sw.js سرو‌شده بیت‌به‌بیت
   مثلِ نسخه‌ی قبلی است و مرورگر هیچ به‌روزرسانی‌ای نمی‌بیند (تلاشِ اول همین‌جا
   گیر کرد: نسخه‌ی ۳ عیناً نسخه‌ی ۲ بود و هیچ سرویس‌ورکرِ تازه‌ای نصب نشد). */
const revBump = (tag) =>
  `\n# (تستِ لایه‌ی ۳.۵ — بازنگریِ «${tag}»: تغییرِ بی‌اثر ً فقط برای تازه شدنِ نامِ کش)\n`;

const problems = [];
const notes = [];
const fail = (m) => problems.push(m);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

function loadPuppeteer() {
  const tries = [];
  if (MODDIR) tries.push(path.join(MODDIR, "puppeteer-core"));
  tries.push("puppeteer-core");
  let last;
  for (const t of tries) {
    try { return require(t); } catch (e) { last = e; }
  }
  throw new Error("puppeteer-core در دسترس نیست (PF_PUPPETEER_DIR را ست کن): " + last);
}

function copyApp(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const nm of fs.readdirSync(src)) {
    if (SKIP_DIRS.has(nm)) continue;
    const s = path.join(src, nm), d = path.join(dst, nm);
    if (fs.statSync(s).isDirectory()) copyApp(s, d);
    else fs.copyFileSync(s, d);
  }
}

async function waitFor(fn, ms, what) {
  const t0 = Date.now();
  let last;
  while (Date.now() - t0 < ms) {
    try { last = await fn(); if (last) return last; } catch (e) { last = e; }
    await wait(300);
  }
  fail(`مهلتِ «${what}» تمام شد` +
    (last ? ` (آخرین وضعیت: ${JSON.stringify(last).slice(0, 200)})` : ""));
  return null;
}

(async () => {
  const puppeteer = loadPuppeteer();
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "pf-upgrade-"));
  const home = path.join(work, "home");
  const app = path.join(work, "app");
  fs.mkdirSync(home, { recursive: true });
  copyApp(HERE, app);
  const appPy = path.join(app, "app.py");
  const pristine = fs.readFileSync(appPy, "utf-8");

  /* مدیریتِ سرورِ آزمایشی باید خودشفا باشد: اگر پروسه بی‌دلیل بمیرد یا پورت آزاد
     نشود، تست باید دلیلِ واقعی را بگوید — نه اینکه بی‌صدا معلق بماند یا بیرون
     بیاید. (تلاشِ اولِ همین هارنس دقیقاً همین‌طور خودش را خورد: انتظارِ رویدادِ
     «exit»ی که هیچ‌وقت نمی‌رسد حلقهٔ رویداد را خالی می‌کرد و فرایندِ node با
     کدِ ۰ و بدونِ خروجی تمام می‌شد.) */
  const srvLog = path.join(work, "server.log");
  const portOpen = (p) => new Promise((res) => {
    const s = net.connect({ port: p, host: "127.0.0.1" });
    const fin = (v) => { try { s.destroy(); } catch (e) { /* بسته شد */ } res(v); };
    s.once("connect", () => fin(true));
    s.once("error", () => fin(false));
    setTimeout(() => fin(false), 1500);
  });
  const tailLog = () => {
    try {
      return fs.readFileSync(srvLog, "utf-8").trim().split("\n").slice(-3).join(" / ").slice(0, 300);
    } catch (e) { return "(لاگی نیست)"; }
  };
  const waitPortFree = async () => {
    for (let i = 0; i < 40; i++) {
      if (!(await portOpen(PORT))) return true;
      await wait(300);
    }
    return false;
  };

  let server = null, srvDied = null;
  const startServer = async () => {
    if (!(await waitPortFree()))
      throw new Error(`پورتِ ${PORT} آزاد نشد (سرورِ قبلی روی آن مانده)`);
    const out = fs.openSync(srvLog, "w");
    server = spawn(PY, ["-u", "app.py", "--port", String(PORT), "--no-autorestart"],
      { cwd: app, env: { ...process.env, HOME: home }, stdio: ["ignore", out, out] });
    const s = server;
    srvDied = null;
    s.once("exit", (code, sig) => { srvDied = `code=${code} signal=${sig || "-"}`; });
    const ok = await waitFor(async () => {
      if (srvDied) return null;                       // مرده — انتظارِ بیشتر بی‌فایده است
      if (!(await portOpen(PORT))) return null;
      const r = await fetch(`http://127.0.0.1:${PORT}/api/health`).catch(() => null);
      return r && r.ok ? true : null;
    }, 40000, "بالا آمدنِ سرورِ آزمایشی");
    if (!ok || srvDied)
      throw new Error(`سرورِ آزمایشی بالا نیامد (${srvDied || "زنده ولی ناسالم"}) · لاگ: ${tailLog()}`);
  };
  const stopServer = async () => {
    const s = server;
    server = null;
    if (!s || s.exitCode !== null || s.signalCode) return;
    const done = new Promise((r) => s.once("exit", r));
    s.kill("SIGTERM");
    await Promise.race([done, wait(6000)]);            // هرگز بی‌سبب معلق نمان
    await waitPortFree();
  };
  // استقرارِ یک «نسخه‌ی تازه»: بازنگریِ تازه (کامنتِ بی‌اثر) + اختیاری، ۴۰۴ِ
  // آیکون تا `addAll` سرِ نصب رد شود (خرابیِ زمانِ اجرا، نه استاتیک).
  const deploy = async (tag, icon404) => {
    let src = pristine + revBump(tag);
    if (icon404) {
      if (!pristine.includes(INJECT_ANCHOR)) throw new Error("لنگرِ تزریقِ ۴۰۴ پیدا نشد");
      src = src.replace(INJECT_ANCHOR,
        `        # فقط-تست: این آیکون در نسخه‌ی تازه ۴۰۴ می‌دهد (خرابیِ زمانِ نصب)\n` +
        `        if u.path == "${VICTIM}":\n` +
        `            return self._send(404, b"")\n` + INJECT_ANCHOR, 1);
    }
    fs.writeFileSync(appPy, src, "utf-8");
    await stopServer();
    await startServer();
  };

  let browser = null;
  try {
    await startServer();
    const opts = {
      headless: true,
      args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--hide-scrollbars"],
    };
    if (BROWSER) opts.executablePath = BROWSER;
    browser = await puppeteer.launch(opts);
    const page = await browser.newPage();
    await page.setViewport({ width: 900, height: 1100 });
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String((e && e.message) || e)));

    // ── ابزارهای کاوش ────────────────────────────────────────────────────────
    const swState = () => page.evaluate(async () => {
      const reg = await navigator.serviceWorker.ready;
      const ctrl = navigator.serviceWorker.controller;
      return { active: !!reg.active, ctrl: ctrl ? ctrl.scriptURL : null,
               waiting: !!reg.waiting, keys: await caches.keys() };
    });
    const askWho = () => page.evaluate(() => new Promise((res) => {
      const ctrl = navigator.serviceWorker.controller;
      if (!ctrl) return res(null);
      const on = (ev) => {
        const d = ev.data || {};
        if (d.type === "PF_WHO_ACK") {
          navigator.serviceWorker.removeEventListener("message", on);
          res(d);
        }
      };
      navigator.serviceWorker.addEventListener("message", on);
      ctrl.postMessage({ type: "PF_WHO" });
      setTimeout(() => res({ timeout: true }), 8000);
    }));
    const banner = () => page.evaluate(() => {
      const b = document.getElementById("pfSwBanner");
      if (!b) return { exists: false };
      const t = document.getElementById("pfSwTxt");
      return { exists: true, visible: b.classList.contains("show") && b.offsetHeight > 0,
               text: t ? (t.textContent || "") : "" };
    });
    // زوجِ کلید/مقدارِ نشست — بی‌وابسته به نامِ کلید، تا سنجیدنِ «یادِ بعداً» به
    // نامِ داخلی گره نخورد ولی هم بی‌نتیجه (ناوَکوم) نماند.
    const ssSnapshot = () => page.evaluate(() => {
      const out = {};
      try {
        for (let i = 0; i < sessionStorage.length; i++) {
          const k = sessionStorage.key(i);
          out[k] = sessionStorage.getItem(k);
        }
      } catch (e) { out["__err__"] = String(e); }
      return out;
    });
    const shellPaths = () => page.evaluate(() =>
      fetch("/sw.js", { cache: "no-store" }).then((r) => r.text()).then((txt) => {
        const m = txt.match(/const\s+SHELL\s*=\s*\[([\s\S]*?)\]/);
        return m ? [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]) : [];
      }));
    const cacheFill = (paths) => page.evaluate(async (ps) => {
      const keys = await caches.keys();
      const out = {};
      for (const k of keys) {
        const c = await caches.open(k);
        let n = 0;
        for (const p of ps) { const hit = await c.match(p); if (hit && hit.ok) n++; }
        out[k] = n;
      }
      return { keys, fill: out };
    }, paths);
    const dropFromCache = (name, p) => page.evaluate(async ([n, pp]) => {
      const c = await caches.open(n);
      await c.delete(pp);
      return (await c.keys()).length;
    }, [name, p]);
    const dropFromAllCaches = (p) => page.evaluate(async (pp) => {
      for (const k of await caches.keys()) {
        const c = await caches.open(k);
        await c.delete(pp);
      }
      return true;
    }, p);
    // شبکه را روی صفحه **و** هدفِ سرویس‌ورکر قطع می‌کند (سرویس‌ورکر هدفِ جدای
    // CDP است؛ مهارِ فقط صفحه، «آفلاینِ ظاهری» می‌سازد).
    const cdp = await page.target().createCDPSession();
    await cdp.send("Network.enable");
    const swSessions = new Set();
    const netOff = async (off) => {
      const args = { offline: off, latency: 0, downloadThroughput: -1, uploadThroughput: -1 };
      await cdp.send("Network.emulateNetworkConditions", args);
      for (const t of browser.targets()) {
        if (t.type() !== "service_worker" || swSessions.has(t)) continue;
        swSessions.add(t);
        try {
          const s = await t.createCDPSession();
          await s.send("Network.enable");
          await s.send("Network.emulateNetworkConditions", args);
        } catch (e) { /* هدفِ در حالِ خاموش‌شدن */ }
      }
    };
    const offlineStillWorks = async (label) => {
      await netOff(true);
      await page.reload({ waitUntil: "load", timeout: 30000 }).catch(() => null);
      const off = await page.evaluate(() => ({
        sym: !!document.getElementById("sym"),
        chips: document.querySelectorAll("#chips .chip").length,
      }));
      await netOff(false);
      if (!off.sym || off.chips < 8)
        fail(`${label}: با قطعِ شبکه اپ از کش بالا نیامد (sym=${off.sym} chips=${off.chips})`);
      return off;
    };
    const upgrade = async (label) => {
      const nav = page.waitForNavigation({ timeout: 25000 }).catch(() => null);
      await page.click("#pfSwBtn");
      await nav;
      await waitFor(async () => (await swState()).ctrl, 20000, `${label}: جانشینیِ نسخه`);
      await wait(1500);                     // نشستنِ activate و تصمیمِ آن
    };

    // ── نسخه‌ی ۱: سالم ─────────────────────────────────────────────────────
    await page.goto(URL, { waitUntil: "load", timeout: 30000 });
    const shell = await shellPaths();
    const s1 = await waitFor(async () => {
      const st = await swState();
      return st.active && st.ctrl && st.keys.length ? st : null;
    }, 30000, "نصبِ نسخه‌ی ۱ (فعال + کنترل‌کننده)");
    if (!s1) throw new Error("نسخه‌ی ۱ نصب نشد");
    const v1 = s1.keys[0];
    const who1 = await askWho();
    if (!who1 || who1.shell_ok !== true)
      fail(`نسخه‌ی سالم وضعیتِ «پوسته سالم» گزارش نکرد: ${JSON.stringify(who1)}`);
    const b1 = await banner();
    if (b1.visible) fail("در نسخه‌ی سالم بنر/هشدار دیده شد (هشدارِ الکی)");
    notes.push(`نسخه‌ی ۱ (سالم): کشِ ${v1} با ${shell.length} مسیر · وضعیت: سالم · بنر پنهان`);

    // ── نسخه‌ی ۲: نصبِ ناقص + کشِ قبلی سالم ⇒ باید ترمیم کند ────────────────
    await deploy("۲", true);
    await page.reload({ waitUntil: "load", timeout: 30000 });
    const w2 = await waitFor(async () => (await swState()).waiting, 25000, "نسخه‌ی ۲ در انتظار");
    if (w2) {
      if (!(await banner()).visible)
        fail("با نسخه‌ی تازه‌ی در انتظار، بنرِ «نسخهٔ تازه» دیده نشد");
      await upgrade("نسخه‌ی ۲");
    }
    const s2 = await cacheFill(shell);
    const who2 = await askWho();
    if (s2.keys.length !== 1)
      fail(`بعد از ترمیم، کهنه‌ها پاک نشدند (${s2.keys.join("، ")}) — نسخهٔ ناقص باید از کشِ ` +
           `قبلی ترمیم و بعد جانشین شود`);
    if ((s2.fill[s2.keys[0]] | 0) !== shell.length)
      fail(`پوستهٔ ترمیم‌شده کامل نیست: ${s2.fill[s2.keys[0]]}/${shell.length} مسیر`);
    if (!who2 || who2.shell_ok !== true)
      fail(`پس از ترمیم، وضعیت «سالم» گزارش نشد: ${JSON.stringify(who2)}`);
    const b2 = await banner();
    if (b2.visible) fail("بعد از ترمیمِ کامل، هشدارِ برگردان روی صفحه ماند (هشدارِ الکی)");
    const off2 = await offlineStillWorks("ترمیم‌شده");
    notes.push(`نسخه‌ی ۲ (نصبِ ناموفق · کشِ قبلی سالم): ${s2.fill[s2.keys[0]]}/${shell.length} ` +
      `مسیر از کشِ قبلی ترمیم شد · کهنه‌ها پاک شدند · آفلاین با ${off2.chips} چیپ باز شد`);

    // ── نسخه‌ی ۳: نصبِ ناقص + کشِ فعالِ ناقص ⇒ ترمیم ممکن نیست، باید برگردد ──
    const active = (await swState()).keys[0];
    const left = await dropFromAllCaches(VICTIM);
    if (!left) fail("آماده‌سازیِ نسخه‌ی ۳: حذفِ آیکون از کش‌ها ناموفق بود");
    await deploy("۳", true);
    await page.reload({ waitUntil: "load", timeout: 30000 });
    await waitFor(async () => (await swState()).waiting, 25000, "نسخه‌ی ۳ در انتظار");
    await upgrade("نسخه‌ی ۳");
    const s3 = await swState();
    const who3 = await askWho();
    if (!s3.keys.includes(active))
      fail(`کشِ سالمِ قبلی («${active}») بعد از نصبِ ناقص پاک شد — برگردان انجام نشد ` +
           `(کش‌های باقی‌مانده: ${s3.keys.join("، ") || "هیچ"})`);
    if (!who3 || who3.shell_ok !== false)
      fail(`سرویس‌ورکر ناقص بودنِ پوسته را گزارش نکرد: ${JSON.stringify(who3)}`);
    if (!who3 || !((who3.kept | 0) >= 1))
      fail(`سرویس‌ورکر نگه‌داشتنِ کشِ قبلی را گزارش نکرد: ${JSON.stringify(who3)}`);
    const b3 = await banner();
    if (!b3.visible)
      fail("بعد از برگردانِ نسخه، به کاربر گفته نشد (بنرِ هشدار دیده نمی‌شود)");
    else if (!b3.text.includes("ناقص"))
      fail(`متنِ هشدارِ برگردان گویا نیست: «${b3.text}»`);

    /* «بعداً»ی بنر تا پایانِ همان بازدید یادش می‌مانَد (بارگذاریِ دوباره
       نمی‌پرسد)، ولی پیامِ «برگردانِ نسخه» هر بار دیده می‌شود: روی همان هشدارِ
       برگردان «بعداً» زده می‌شود (یادِ نشست ست می‌شود)، صفحه از نو بالا می‌آید
       و هشدار باید همان‌جا باشد — وگرنه خبرِ «نسخهٔ تازه ناقص بود» بی‌صدا می‌مانَد. */
    const ss0 = await ssSnapshot();
    await page.evaluate(() => {
      const b = document.getElementById("pfSwHide");
      if (b) b.click();
    });
    if ((await banner()).visible)
      fail("کلیکِ «بعداً» هشدارِ برگردان را از صفحه برنداشت");
    const ss1 = await ssSnapshot();
    if (!Object.keys(ss1).some((k) => ss0[k] !== ss1[k]))
      fail("«بعداً» هیچ‌جا در نشست یاد نمی‌شود — بارگذاریِ دوباره تا پایانِ هماین "
        + "بازدید دوباره می‌پرسد");
    await page.reload({ waitUntil: "load", timeout: 30000 });
    const b5 = await waitFor(async () => {
      const b = await banner();
      return b.visible && (b.text || "").includes("ناقص") ? b : null;
    }, 20000, "بازگشتِ هشدارِ برگردان با یادِ «بعداً»");
    if (!b5)
      fail("با یادِ «بعداً» در نشست، پیامِ «برگردانِ نسخه» پس از بارگذاریِ دوباره "
        + "دیده نشد — این پیام باید هر بار به کاربر گفته شود");
    else
      notes.push("پیامِ «برگردانِ نسخه» با وجودِ «بعداً»ی همان بازدید هم دوباره دیده شد");
    const off3 = await offlineStillWorks("برگردانِ نسخه");
    notes.push(`نسخه‌ی ۳ (نصبِ ناموفق · کشِ قبلیِ ناقص): برگردان انجام شد · کشِ قبلی ` +
      `(${active}) نگه داشته شد · رکورد: shell_ok=false, kept=${who3 ? who3.kept : "?"} · ` +
      `آفلاین با ${off3.chips} چیپ باز شد · به کاربر خبر داده شد`);

    for (const e of pageErrors) fail("خطای زمانِ اجرا در تستِ ارتقا: " + e);
  } catch (e) {
    fail("اجرای تستِ ارتقای ایمن ممکن نشد: " + ((e && e.message) || e));
  } finally {
    try { if (browser) await browser.close(); } catch (e) { /* بسته شد */ }
    await stopServer();
    try { fs.rmSync(work, { recursive: true, force: true }); } catch (e) { /* موقت */ }
  }

  for (const n of notes) console.log("• " + n);
  if (problems.length) {
    console.log("");
    for (const p of problems) console.log("::error::" + p);
    console.log(`\n❌ ارتقای ایمنِ نسخه رد شد — ${problems.length} مشکل`);
    process.exit(1);
  }
  console.log("\n✅ ارتقای ایمنِ نسخه تأیید شد: نسخه‌ی ناقص ترمیم می‌شود، ترمیم‌نشدنی برمی‌گردد و آفلاین می‌ماند");
})().catch((e) => {
  console.log("::error::تستِ ارتقای ایمن اجرا نشد: " + ((e && e.stack) || e));
  process.exit(1);
});
