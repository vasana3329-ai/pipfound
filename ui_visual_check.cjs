#!/usr/bin/env node
/**
 * تستِ بصری + «سیم‌کشیِ کلیدها» در مرورگرِ واقعیِ headless.
 *
 * چرا لازم است: یک خطای جاوااسکریپت (مثلِ SyntaxError بک‌اسلشِ اضافه در قالبِ متنی)
 * کلِ <script> صفحه را می‌خشکاند؛ دکمه‌ها در HTML می‌مانند ولی هیچ‌کدام کار نمی‌کنند.
 * چکِ متنیِ HTML این خرابی را نمی‌بیند — این تست صفحه را در مرورگر بالا می‌آورد و
 * می‌سنجد که (۱) اسکریپت اجرا شده، (۲) کلیدها سیم‌کشی شده‌اند، (۳) رفتارِ کلیک درست است.
 *
 * استفاده:
 *   PF_BROWSER="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
 *   PF_PUPPETEER_DIR="/path/to/node_modules" \
 *     node ui_visual_check.cjs --url http://127.0.0.1:8787/ --shot /tmp/pf-ui.png
 *
 * خروجی: ۰ = سالم، ۱ = مشکل (با ::error:: برای نمایش روی PR/کامیت).
 */
const path = require("path");

function arg(name, def) {
  const i = process.argv.indexOf("--" + name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

const URL = arg("url", "http://127.0.0.1:8787/");
const SHOT = arg("shot", "pf-ui.png");
const MODDIR = process.env.PF_PUPPETEER_DIR || "";
const BROWSER = process.env.PF_BROWSER || "";

/* کنترل‌هایی که باید همان لحظه‌ی بار شدن در صفحه باشند.
   توجه: `#jbtn` (ثبت در ژورنال)، `#alarmBtn` و `#pipModal` عمداً فقط بعد از یک تحلیل
   یا باز شدنِ پنجره ساخته می‌شوند و `#bootWarn` هم فقط وقتی _اسکریپتِ اصلی می‌میرد_
   ساخته می‌شود؛ پس این‌ها اینجا نیستند. وجودشان در متنِ سرو‌شده را `selfcheck.py`
   (قراردادِ ۵۳ کلید) و اسموک‌تستِ CI چک می‌کنند — این تست سراغِ رندرِ واقعی می‌رود. */
const REQUIRED = ["go", "bt", "sym", "syms", "styles", "chips", "refreshBtn",
  "archiveBtn", "fundBtn", "sbBtn", "setupsBtn", "result", "btPanel",
  "setupsPanel", "alarmsDock", "tvBox", "shotGrid", "lightbox", "revChip",
  "dataChip", "riskPanel", "rkBalance", "rkRisk", "rkDaily", "rkOpen",
  "rkStat", "rkSave"];
/* کنترل‌هایی که اپ با `.onclick =` به آن‌ها هندلر می‌دهد؛ اگر این‌ها تابع نباشند
   یعنی بلوکِ اسکریپت اجرا نشده یا نیمه‌کاره مرده است. */
const WIRED = ["go", "refreshBtn", "bt", "setupsBtn", "fundBtn", "archiveBtn",
  "rkSave"];
/* این‌ها با addEventListener وصل می‌شوند (نه onclick) — با CDP سنجیده می‌شوند. */
const LISTENER_ONLY = ["sbBtn", "styles"];

const problems = [];
const notes = [];
const fail = (m) => problems.push(m);

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

(async () => {
  const puppeteer = loadPuppeteer();
  const opts = {
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--hide-scrollbars"],
  };
  if (BROWSER) opts.executablePath = BROWSER;
  const browser = await puppeteer.launch(opts);
  const page = await browser.newPage();
  await page.setViewport({ width: 900, height: 1400 });

  const consoleErrors = [];
  const pageErrors = [];
  /* ۴۰۴های بی‌ضررِ مرورگر (مثلِ favicon) نباید PR را رد کنند. */
  const BENIGN = [/favicon\.ico/i];
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const loc = (typeof m.location === "function" && m.location()) || {};
    const txt = ((loc.url || "") + " " + m.text()).trim();
    if (BENIGN.some((re) => re.test(txt))) { notes.push("نادیده گرفته شد (بی‌ضرر): " + txt); return; }
    consoleErrors.push(txt);
  });
  page.on("pageerror", (e) => pageErrors.push(String((e && e.message) || e)));

  await page.goto(URL, { waitUntil: "load", timeout: 30000 });

  /* ۱) نمای اصلی باید تمیز باشد: **هیچ کلیدِ نمادی** نباید بی‌دخالت دیده شود.
     فهرست داخلِ یک پنلِ کشویی است که فقط با ورودِ نشانگر/فوکوس به کادرِ نماد باز می‌شود. */
  try {
    const vis = await page.$eval("#chips", (el) => getComputedStyle(el).display !== "none");
    if (vis) fail("پنلِ انتخابِ نماد در نمای اصلی دیده می‌شود — باید فقط با ورودِ نشانگر/فوکوس باز شود");
    else notes.push("نمای اصلی تمیز است: پنلِ نمادها بسته است");
  } catch (e) {
    fail("عنصرِ پنلِ انتخابِ نماد (#chips) پیدا نشد: " + e.message);
  }

  /* ۱.۱) اسکریپت زنده است؟ پنل فقط با JS ساخته می‌شود؛ با رفتنِ نشانگر داخلِ کادر باید باز شود. */
  let chips = 0;
  try {
    await page.hover("#sym");
    await page.waitForSelector("#chips.open .chip", { timeout: 15000 });
    chips = await page.$$eval("#chips .chip", (els) => els.length);
  } catch (e) {
    fail("با ورودِ نشانگر به کادرِ نماد، فهرستِ انتخاب باز نشد — یعنی بلوکِ <script> اجرا نشده (همان خرابیِ «کلیدها گم شدند»)");
  }
  if (chips && chips < 8) fail(`تعدادِ نمادهای انتخاب کم است: ${chips} (انتظار ≥ ۸)`);
  notes.push(`نمادهای انتخابِ سریع (JS-ساخته): ${chips}`);

  /* ۱.۱) گروه‌بندیِ انتخابِ سریع: چهار دسته در همان کادرِ جستجو.
     اگر کسی یک گروه/برچسب را حذف کند یا فهرستِ نمادها را خالی کند، این‌جا گرفته می‌شود
     — همان کلاسی از تغییرِ رابط که یک‌بار «کلیدها گم شدند» را ساخت. */
  let groups = [];
  try {
    groups = await page.$$eval("#chips .chipgroup", (gs) => gs.map((g) => ({
      label: ((g.querySelector(".chiplbl") || {}).textContent || "").trim(),
      chips: [...g.querySelectorAll(".chip")].map((c) => c.textContent.trim()),
    })));
  } catch (e) {
    fail("خواندنِ گروه‌های چیپ ممکن نشد: " + e.message);
  }
  const WANT_GROUPS = ["جفت‌ارزهای مهم", "کامودیتی", "اندیکس", "استاک"];
  for (const w of WANT_GROUPS) {
    const g = groups.find((x) => x.label === w);
    if (!g) fail(`گروهِ «${w}» در چیپ‌های کادرِ جستجو نیست (موجود: ${groups.map((x) => x.label).join("، ")})`);
    else if (!g.chips.length) fail(`گروهِ «${w}» هیچ نمادی ندارد`);
  }
  const allSyms = groups.flatMap((g) => g.chips);
  for (const n of ["EURUSD", "XAUUSD", "WTI", "SPX500", "NVDA"]) {
    if (!allSyms.includes(n)) fail(`نمادِ «${n}» از انتخابِ سریع حذف شده`);
  }
  notes.push(`گروه‌های چیپ: ${groups.map((g) => `${g.label}(${g.chips.length})`).join(" · ")}`);

  /* ۲) هیچ خطای جاوااسکریپتی در کنسول نباشد. */
  for (const e of pageErrors) fail("خطای زمانِ اجرای جاوااسکریپت: " + e);
  for (const e of consoleErrors) fail("خطای کنسول: " + e);

  /* ۳) نوارِ قرمزِ نگهبانِ بوت نباید دیده شود. */
  const bootWarnVisible = await page.evaluate(() => {
    const el = document.getElementById("bootWarn");
    if (!el) return false;
    const st = getComputedStyle(el);
    return st.display !== "none" && st.visibility !== "hidden" && el.offsetHeight > 0;
  });
  if (bootWarnVisible) fail("نوارِ «نگهبانِ بوت» دیده می‌شود — یعنی اسکریپتِ اصلی خطا داده");

  /* ۴) همه‌ی کلیدهای لازم در صفحه‌ی رندرشده باشند. */
  const missing = await page.evaluate((ids) => ids.filter((i) => !document.getElementById(i)), REQUIRED);
  if (missing.length) fail("کلیدهای غایب در صفحه: " + missing.join(", "));
  notes.push(`کلیدهای سنجیده‌شده: ${REQUIRED.length - missing.length}/${REQUIRED.length}`);

  /* ۵) کلیدها سیم‌کشی شده‌اند؟ */
  const unwired = await page.evaluate((ids) => ids.filter((i) => {
    const el = document.getElementById(i);
    return !el || typeof el.onclick !== "function";
  }), WIRED);
  if (unwired.length) fail("کلیدهای بی‌هندلر (onclick تابع نیست): " + unwired.join(", "));

  /* دکمه‌ی «↻ بروزرسانی» تا اولین تحلیل باید غیرفعال بماند (رفتارِ طراحی‌شده). */
  const refreshDisabled = await page.$eval("#refreshBtn", (el) => el.disabled);
  if (!refreshDisabled) fail("دکمه‌ی «↻ بروزرسانی» از همان ابتدا فعال است (باید تا اولین تحلیل غیرفعال باشد)");

  /* ۶) کنترل‌های addEventListener-محور — با CDP (اگر در دسترس بود). */
  let cdp = null;
  try {
    cdp = typeof page.createCDPSession === "function" ? await page.createCDPSession() : null;
  } catch (e) { cdp = null; }
  if (cdp) {
    for (const id of LISTENER_ONLY) {
      try {
        const { result } = await cdp.send("Runtime.evaluate", {
          expression: `document.getElementById(${JSON.stringify(id)})`,
        });
        if (!result || !result.objectId) { fail(`عنصرِ #${id} برای بررسیِ رویداد پیدا نشد`); continue; }
        const { listeners } = await cdp.send("DOMDebugger.getEventListeners", {
          objectId: result.objectId, depth: 1, pierce: false,
        });
        if (!listeners || listeners.length === 0) fail(`#${id} هیچ رویدادِ کلیکی ندارد`);
        else notes.push(`رویدادهای #${id}: ${listeners.length}`);
      } catch (e) {
        notes.push(`بررسیِ رویدادِ #${id} ممکن نشد (CDP): ${e.message}`);
      }
    }
  } else {
    notes.push("CDP در دسترس نبود؛ بررسیِ رویدادهای addEventListener انجام نشد");
  }

  /* ۶.۵) نشانگرِ بازنگری: باید مسیرِ /api/revision جواب بدهد و چیپ متنِ واقعی
     نشان دهد. اگر پروسه‌ای قدیمی نسخه‌ی کهنه را سرو کند، stale=true می‌شود و
     همین‌جا گرفته می‌شود — دقیقاً همان حالتی که شبیهِ «کلیدها گم شدند» است. */
  try {
    const rev = await page.evaluate(async () => {
      const r = await fetch("/api/revision", { cache: "no-store" });
      const j = await r.json();
      const el = document.getElementById("revChip");
      return { j, text: el ? el.textContent.trim() : null };
    });
    if (!rev.j || rev.j.ok !== true) fail("اندپوینتِ /api/revision جوابِ سالم نداد: " + JSON.stringify(rev.j));
    if (!rev.text || rev.text === "rev …" || rev.text === "rev ?")
      fail("چیپِ بازنگری با اندپوینت پر نشد (متن: " + JSON.stringify(rev.text) + ")");
    if (rev.j && rev.j.stale)
      fail("پروسه‌ی سرو‌کننده نسخه‌ی کهنه است (stale=true) — سرور را از نو بالا بیاور. فایل‌های تازه‌تر: "
        + ((rev.j.changed_files || []).map((c) => c.file).join(", ") || "—")
        + (rev.j.sha_drift ? " · SHA دیسک: " + ((rev.j.disk || {}).sha || "?") : ""));
    const ar = (rev.j && rev.j.autorestart) || {};
    if (!ar.enabled)
      fail("ری‌استارتِ خودکارِ کدِ کهنه خاموش است — پروسه‌ی کهنه بی‌صدا سرو می‌شود (باید پیش‌فرض روشن باشد)");
    if (rev.j && rev.j.ok === true && !rev.j.stale)
      notes.push(`بازنگری: ${(rev.j.loaded || {}).sha || "?"} (دیسک ${(rev.j.disk || {}).sha || "?"}) · چیپ: ${rev.text} · ری‌استارتِ خودکار: ${ar.enabled ? "روشن" : "خاموش"}`);
  } catch (e) {
    fail("بررسیِ نشانگرِ بازنگری ممکن نشد: " + e.message);
  }

  /* ۶.۵) سنِ داده و باز/بسته بودنِ بازار — هم اندپوینت و هم چیپِ رابط.
     این بخش خلافِ رگرسیونِ «تحلیل روی کندلِ ناقص/بازارِ بسته» را می‌گیرد: پاسخِ
     تحلیل باید بلوکِ data داشته باشد، کندلِ تحلیل‌شده **بسته** باشد (forming=false)،
     و چیپِ داده نباید متنِ جانشینِ اولیه بماند. */
  try {
    const ds = await page.evaluate(async () => {
      const r = await fetch("/api/data_status", { cache: "no-store" });
      const j = await r.json();
      const el = document.getElementById("dataChip");
      return { j, text: el ? el.textContent.trim() : null };
    });
    if (!ds.j || ds.j.ok !== true) fail("اندپوینتِ /api/data_status جوابِ سالم نداد: " + JSON.stringify(ds.j));
    if (!ds.text || ds.text === "داده …" || ds.text === "⚪ داده؟")
      fail("چیپِ داده با اندپوینت پر نشد (متن: " + JSON.stringify(ds.text) + ")");
    if (!ds.j.killzone) fail("وضعیتِ کیل‌زون در /api/data_status نیست");
    if (ds.j.fresh && ds.j.fresh.forming)
      fail("سنِ داده روی یک کندلِ **در حالِ تشکیل** حساب شده — تحلیل باید فقط کندلِ بسته را ببیند");
    notes.push(`وضعیتِ داده: ${ds.text} · کیل‌زون: ${ds.j.killzone}`);
  } catch (e) {
    fail("بررسیِ چیپِ سنِ داده ممکن نشد: " + e.message);
  }

  /* ۶.۶) یک تحلیلِ واقعی روی کریپتو (۲۴/۷): بلوکِ data باید در پاسخ باشد و فقط
     کندلِ بسته را تحلیل کرده باشد. حالتِ بازار روی رانرِ CI بسته/باز متفاوت است،
     پس این‌جا روی «باز بودن» چسب نمی‌چسبیم — فقط ساختار و بسته‌بودنِ کندل. */
  try {
    const an = await page.evaluate(async () => {
      const r = await fetch("/api/analyze?symbol=BTCUSDT&style=scalp", { cache: "no-store" });
      const j = await r.json();
      return { err: j.error || null, data: j.data || null, grade: j.grade || null,
               plan: j.plan ? { executable_now: j.plan.executable_now } : null,
               dataByTf: j.data_by_tf || null };
    });
    if (an.err) fail("تحلیلِ BTCUSDT خطا داد: " + an.err);
    else {
      if (!an.data || !an.data.state) fail("پاسخِ تحلیل بلوکِ data (سنِ داده) ندارد");
      else {
        if (an.data.forming) fail("تحلیل روی کندلِ در حالِ تشکیل انجام شده (forming=true)");
        if (!an.data.last_bar_utc) fail("last_bar_utc در بلوکِ data نیست");
        if (an.data.state !== "open" && an.plan && an.plan.executable_now === true)
          fail("بازار بسته/کهنه است ولی پلن «قابلِ اجرا» علامت خورده");
        notes.push(`تحلیلِ کریپتو: درجه ${an.grade} · وضعیتِ داده ${an.data.state} (${an.data.age_human}) · کندلِ آخر ${an.data.last_bar_utc} UTC`);
      }
    }
  } catch (e) {
    fail("تحلیلِ کنترلیِ کریپتو ممکن نشد: " + e.message);
  }

  /* ۶.۷) مدلِ ریسک: پنل باید پر شود (نه متنِ جانشینِ اولیه)، اندپوینت سالم باشد،
     و مسیرِ ذخیره واقعاً کار کند. نوشتنِ تنظیمات **با همان مقادیرِ فعلی** انجام
     می‌شود تا اجرای تست، تنظیماتِ کاربر را عوض نکند — فقط مسیرِ نوشتن را می‌سنجد. */
  try {
    const rk = await page.evaluate(async () => {
      const r = await fetch("/api/risk", { cache: "no-store" });
      const j = await r.json();
      const st = (document.getElementById("rkStat") || {}).textContent || "";
      const bal = (document.getElementById("rkBalance") || {}).value;
      const rp = (document.getElementById("rkRisk") || {}).value;
      const dl = (document.getElementById("rkDaily") || {}).value;
      const op = (document.getElementById("rkOpen") || {}).value;
      return { j, st, bal, rp, dl, op };
    });
    if (!rk.j || rk.j.ok !== true)
      fail("اندپوینتِ /api/risk جوابِ سالم نداد: " + JSON.stringify(rk.j));
    const s = (rk.j && rk.j.settings) || {};
    if (!(Number(s.balance) > 0)) fail("سرمایه‌ی پیش‌فرض در /api/risk عددِ مثبت نیست: " + JSON.stringify(s));
    if (!(Number(s.risk_pct) > 0)) fail("درصدِ ریسکِ پیش‌فرض در /api/risk مثبت نیست: " + JSON.stringify(s));
    if (!(Number(s.daily_loss_limit_pct) > 0)) fail("سقفِ ضررِ روزانه در /api/risk تنظیم نشده: " + JSON.stringify(s));
    if (!rk.j.daily || typeof rk.j.daily !== "object") fail("بلوکِ وضعیتِ روزانه (daily) در /api/risk نیست");
    else {
      for (const k of ["realized_pct", "limit_pct", "remaining_pct", "open_risk_pct", "open_count"])
        if (rk.j.daily[k] === undefined) fail(`کلیدِ «${k}» در بلوکِ روزانه‌ی ریسک نیست`);
    }
    if (!rk.bal || !rk.rp) fail("کادرهای سرمایه/درصدِ ریسک با اندپوینت پر نشدند");
    if (!rk.st || rk.st.includes("در حالِ خواندن"))
      fail("خطِ وضعیتِ ریسک با اندپوینت پر نشد (متن: " + JSON.stringify(rk.st) + ")");
    if (!rk.st.includes("ریسکِ باز")) fail("خطِ وضعیتِ ریسک، ریسکِ باز را نشان نمی‌دهد");
    // نوشتن با همان مقادیرِ فعلی — فقط سالم بودنِ مسیر را ثابت می‌کند
    const wr = await page.evaluate(async (cur) => {
      const r = await fetch("/api/risk", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cur),
      });
      return await r.json();
    }, { balance: s.balance, risk_pct: s.risk_pct,
         daily_loss_limit_pct: s.daily_loss_limit_pct, max_open_risk_pct: s.max_open_risk_pct });
    if (wr.error) fail("ذخیره‌ی تنظیماتِ ریسک خطا داد: " + wr.error);
    else if (!(Number((wr.settings || {}).balance) > 0))
      fail("پاسخِ ذخیره‌ی ریسک تنظیماتِ معتبر برنگرداند: " + JSON.stringify(wr));
    else if (!wr.settings_file) fail("مسیرِ فایلِ تنظیماتِ ریسک در پاسخِ ذخیره نیست");
    else notes.push(`ریسک: سرمایه ${s.balance} · ریسکِ هر معامله ${s.risk_pct}٪ · `
      + `سقفِ روزانه ${s.daily_loss_limit_pct}٪ · ریسکِ باز ${rk.j.daily.open_risk_pct}٪ (${rk.j.daily.open_count} پوزیشن)`);
  } catch (e) {
    fail("بررسیِ پنلِ ریسک ممکن نشد: " + e.message);
  }

  /* ۷) رفتارِ واقعی: انتخاب از داخلِ پنل باید کادر را پُر کند، دکمه را آماده کند و
     پنل را ببندد. عمداً روی نمادِ «اندیکس» می‌چسبیم (نه اولین نماد) تا ثابت شود
     دسته‌های تازه هم واقعاً سیم‌کشی شده‌اند، نه فقط پنل را پر کرده‌اند. */
  try {
    const chipText = "NAS100";
    await page.hover("#sym");
    await page.waitForSelector("#chips.open", { timeout: 5000 });
    await page.click(`#chips .chip[data-sym="${chipText}"]`);
    await page.waitForFunction(
      (t) => document.querySelector("#sym").value === t, { timeout: 5000 }, chipText);
    const pulsed = await page.$eval("#go", (el) => el.classList.contains("pulse"));
    if (!pulsed) fail("پس از انتخابِ نماد، دکمه‌ی «تحلیل کن» حالتِ آماده (pulse) نگرفت");
    const stillOpen = await page.$eval("#chips", (el) => el.classList.contains("open"));
    if (stillOpen) fail("پس از انتخابِ نماد، پنلِ فهرست بسته نشد");
    notes.push(`انتخابِ «${chipText}» از پنل → نماد پُر شد، دکمه آماده شد، پنل بسته شد`);
    // پنل باید به حالتِ بسته برگردد تا نمای اصلیِ کاربر تمیز بماند
    await page.mouse.move(10, 10);
    await page.waitForFunction(() => {
      const el = document.querySelector("#chips");
      return el && getComputedStyle(el).display === "none";
    }, { timeout: 5000 });
    notes.push("پس از کنار رفتنِ نشانگر، پنل بسته می‌ماند");
  } catch (e) {
    fail("انتخاب از پنل اثر نکرد (هندلرها مرده‌اند؟): " + e.message);
  }

  /* ۸) رفتارِ واقعی: کلیک روی سبک، حالتِ active را جابه‌جا کند. */
  try {
    await page.click('#styles button[data-k="scalp"]');
    const st = await page.evaluate(() => ({
      scalp: document.querySelector('#styles button[data-k="scalp"]').classList.contains("active"),
      day: document.querySelector('#styles button[data-k="day"]').classList.contains("active"),
    }));
    if (!st.scalp || st.day) fail(`انتخابِ سبک کار نکرد (scalp=${st.scalp} day=${st.day})`);
    else notes.push("کلیکِ سبک «اسکالپ» → حالتِ active درست جابه‌جا شد");
  } catch (e) {
    fail("کلیکِ دکمه‌ی سبک اثر نکرد: " + e.message);
  }

  /* ۹) اسکرین‌شات برای بازبینیِ انسانی. */
  try {
    await page.screenshot({ path: SHOT });
    notes.push("اسکرین‌شات: " + SHOT);
  } catch (e) {
    notes.push("اسکرین‌شات گرفته نشد: " + e.message);
  }

  await browser.close();

  for (const n of notes) console.log("• " + n);
  if (problems.length) {
    console.log("");
    for (const p of problems) console.log("::error::" + p);
    console.log(`\n❌ تستِ بصری رد شد — ${problems.length} مشکل`);
    process.exit(1);
  }
  console.log("\n✅ تستِ بصری پاس شد: صفحه رندر شد، کلیدها سیم‌کشی‌اند و رفتارها درست‌اند");
})().catch((e) => {
  console.log("::error::تستِ بصری اجرا نشد: " + ((e && e.stack) || e));
  process.exit(1);
});
