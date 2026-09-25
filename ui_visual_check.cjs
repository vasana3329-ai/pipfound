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
  "rkStat", "rkSave", "installBtn"];
const HANDLER_IDS = new Set(["rkSave", "installBtn"]);   // وایر داخلِ IIFE — با CDP سنجیده می‌شود
/* کنترل‌هایی که اپ با `.onclick =` به آن‌ها هندلر می‌دهد؛ اگر این‌ها تابع نباشند
   یعنی بلوکِ اسکریپت اجرا نشده یا نیمه‌کاره مرده است. */
const WIRED = ["go", "refreshBtn", "bt", "setupsBtn", "fundBtn", "archiveBtn",
  "rkSave"];
const LISTENER_ONLY = ["sbBtn", "styles", "installBtn"];

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

  /* ۶.۶) دکمه‌ی «↻ بروزرسانی» باید از همان بارگذاری *واکنش* نشان دهد.
     باگِ واقعیِ گزارش‌شده: دکمه disabledبود، پس کلیک روی آن در اپِ تازه‌باز هیچ
     اتفاقی نمی‌انداخت (نه پیام، نه راهنما) و به‌نظرِ «دکمه‌ی خراب» می‌آمد.
     قراردادِ تازه: دکمه فعال است و با کادرِ نمادِ خالی، کاربر را به انتخابِ نماد
     هدایت می‌کند (فوکوس + فهرستِ نمادها + اشاره‌ی ملایم + پیامِ روشن) و هنوز هیچ
     درخواستی نمی‌فرستد. */
  const rfReact = await page.evaluate(async () => {
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    const b = document.getElementById("refreshBtn"), inp = document.getElementById("sym"),
          res = document.getElementById("result"), chips = document.getElementById("chips");
    const prevLast = window._last, prevSeen = window._lastSeen; // بعد از تست برمی‌گردانیم
    // حافظه‌ی سرور (آخرین تحلیلِ ثبت‌شده) نتیجه را تعیین می‌کند: اگر نمادی یادش باشد،
    // دکمه باید *همان* را بازتازه کند؛ اگر نه، فقط پیام بدهد. پس اول خودمان می‌پرسیم.
    let mem = null;
    try {
      const s = await fetch("/api/data_status", { cache: "no-store" });
      mem = (((await s.json()) || {}).analyzed) || null;
    } catch (e) { mem = null; }
    const before = res.innerHTML.trim();
    window._last = null; window._lastSeen = null; inp.value = ""; inp.blur();
    chips.classList.remove("open");          // مستقل از وضعیتِ قبلیِ پنل بسنجیم
    const out = { disabled: b.disabled, wasEmpty: before === "" };
    b.click();
    // تمامِ بازهٔ بعد از کلیک را می‌پاییم (نه فقط یک لحظه): کاربر «باز شدنِ پنجره»
    // را حتی اگر لحظه‌ای باشد می‌بیند و خرابی می‌داند.
    out.focused = false; out.panelOpen = false; out.nudged = false;
    for (let i = 0; i < 16; i++) {
      if (document.activeElement === inp) out.focused = true;
      if (chips.classList.contains("open")) out.panelOpen = true;
      if (inp.classList.contains("nudge")) out.nudged = true;
      await wait(50);
    }
    await wait(300);          // فرصتِ کافی برای یک رفت‌وبرگشتِ محلیِ /api/data_status
    out.hint = res.innerHTML.trim() !== before;
    out.hintText = (res.textContent || "").slice(0, 200);   // کوتاه نکن که وسطِ کلمه بُرده شود
    out.startedWork = /در حالِ تحلیل/.test(res.textContent || "");
    out.busy = b.getAttribute("aria-busy") === "true";
    out.live = (b.querySelector(".rf-live") || {}).textContent || "";
    out.serverMemory = (mem && mem.symbol) ? mem.symbol : null;
    inp.classList.remove("nudge");
    window._last = prevLast; window._lastSeen = prevSeen;
    return out;
  });
  if (rfReact.disabled)
    fail("دکمه‌ی بروزرسانی در بارگذاری غیرفعال است — کلیک روی آن هیچ واکنشی ندارد");
  if (!rfReact.serverMemory && (rfReact.startedWork || rfReact.busy))
    fail("دکمه‌ی بروزرسانی بی‌نماد و بی‌حافظه‌ی سرور، بی‌دلیل تحلیل را شروع کرد");
  if (rfReact.serverMemory && !rfReact.startedWork && !rfReact.busy)
    fail(`حافظه‌ی سرور «${rfReact.serverMemory}» را داشت ولی دکمه‌ی بروزرسانی کاری نکرد`);
  // اثرِ جانبیِ ممنوع: نمی‌شود پنجره/فوکوس را قاپید. یک‌بار همین کار خودِ تجربه‌ی
  // کاربر را خراب کرد («کلیک روی بروزرسانی پنجره‌ی نمادها را باز می‌کند») — الان
  // قرارداد این است که دکمه *فقط پیام بدهد* و هیچ پنجره‌ای باز نکند.
  if (rfReact.panelOpen)
    fail("کلیکِ دکمه‌ی بروزرسانی پنجره‌ی نمادها را باز می‌کند — اثرِ جانبیِ ناخواسته");
  if (rfReact.focused)
    fail("کلیکِ دکمه‌ی بروزرسانی فوکوس را از کاربر می‌قاپد و به کادرِ نماد می‌برد");
  if (rfReact.nudged)
    fail("کلیکِ دکمه‌ی بروزرسانی کادرِ نماد را چشمک می‌زند (باید فقط پیام بدهد)");
  if (!rfReact.serverMemory) {
    if (rfReact.wasEmpty && !rfReact.hint)
      fail("دکمه‌ی بروزرسانی بی‌نماد و بی‌حافظه هیچ پیامی نشان نمی‌دهد (بی‌صدا می‌ماند)");
    if (rfReact.hint && !/نماد/.test(rfReact.hintText))
      fail("پیامِ راهنمای دکمه‌ی بروزرسانی درباره‌ی انتخابِ نماد نیست: " + rfReact.hintText);
  }
  if (!rfReact.live)
    fail("دکمه‌ی بروزرسانی برای صفحه‌خوان‌ها پیامی نمی‌گذارد (ناحیه‌ی زنده خالی است)");
  notes.push("دکمه‌ی بروزرسانی: فعال از بارگذاری · بدونِ باز کردنِ پنجره/قاپیدنِ فوکوس"
    + (rfReact.serverMemory
        ? ` · کادرِ خالی → بازتازه‌سازیِ حافظه‌ی سرور (${rfReact.serverMemory}) ✓`
        : " · کادرِ خالی → پیامِ روشن ✓"));

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
    if (!ds.j.killzone) fail("وضعیتِ کیل‌زون در /api/data_status نیست");
    if (ds.j.fresh && ds.j.fresh.forming)
      fail("سنِ داده روی یک کندلِ **در حالِ تشکیل** حساب شده — تحلیل باید فقط کندلِ بسته را ببیند");
    if (ds.j.analyzed) {
      // ماشینی که قبلاً تحلیل ثبت کرده: چیپ باید با اندپوینت پر شده باشد
      if (!ds.text || ds.text === "داده …" || ds.text === "⚪ داده؟")
        fail("چیپِ داده با اندپوینت پر نشد (متن: " + JSON.stringify(ds.text) + ")");
    } else {
      // رانرِ تازه: هنوز هیچ تحلیلی ثبت نشده، پس «⚪ داده؟» وضعیتِ **درست** است،
      // نه خرابیِ چیپ. چکِ واقعیِ پر شدن چیپ بعد از تحلیل، پایین‌تر (بعد از ۶.۶) می‌آید.
      notes.push("هنوز تحلیلی ثبت نشده — چیپ درست است که «⚪ داده؟» بماند");
    }
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
    // بلافاصله بعد از یک تحلیل، چیپِ داده باید پر شود (نه متنِ جانشین) — این
    // همان چیزی است که روی رانرِ تازه قابلِ سنجیدن است.
    const chipAfter = await page.evaluate(async () => {
      if (typeof loadData === "function") { try { await loadData(); } catch (e) {} }
      const el = document.getElementById("dataChip");
      const r = await fetch("/api/data_status", { cache: "no-store" });
      const j = await r.json();
      return { text: el ? el.textContent.trim() : null, analyzed: !!j.analyzed };
    });
    if (!chipAfter.analyzed)
      fail("بعد از یک تحلیل، /api/data_status وضعیتِ تحلیل را نگه نداشت (data_seen خالی ماند)");
    else if (!chipAfter.text || chipAfter.text === "داده …" || chipAfter.text === "⚪ داده؟")
      fail("بعد از یک تحلیل، چیپِ داده همچنان خالی است (متن: " + JSON.stringify(chipAfter.text) + ")");
    else notes.push("چیپِ داده بعد از تحلیل پر شد: " + chipAfter.text);
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

  /* ۶.۸) دکمه‌ی «بروزرسانی»: حالتِ «در حالِ کار» باید با نشانگرِ ساخته‌شده و
     انیمیشنِ نرم نشان داده شود، نه با گلیفِ متنیِ چرخان (خواسته‌ی کاربر: نمایشِ
     باکلاس، نه چرخشِ بچه‌گانه). در حالتِ عادی هم نشانگر باید پنهان باشد و اندازه‌ی
     دکمه تغییر نکند — وگرنه نوارِ ابزار می‌پرد. */
  try {
    /* قراردادِ سخت‌گیرانه: چرخشِ *خطی* (easing در هر دور تند-و-کند می‌شود و آماتوری
       به‌نظر می‌رسد)، دُمِ نفس‌کش، نبودِ افکت‌های تصویریِ اضافه (نورِ گذری/نوارِ خزنده)،
       روشن‌بودنِ دکمه در حینِ کار (نه محوِ disabled) و اندازه‌ی ثابت.
       عمداً بعد از هر تغییرِ کلاس کمی صبر می‌کنیم تا از پلِ ترنزیشن رد شویم؛ وگرنه
       getComputedStyle مقدارِ *قبل از تغییر* را برمی‌گرداند و تست بی‌دلیل رد می‌شود. */
    // اگر تحلیلِ در جریان یا تیکِ موقتِ پایانِ مرحله‌ی قبل باقی مانده باشد، خواندنِ
    // حالت‌ها را خراب می‌کند (دکمه واقعاً در حالتِ کار یا تأیید است) — پس تا
    // رسیدن به حالتِ تمیز و پایدارِ بی‌کار صبر می‌کنیم.
    try {
      await page.waitForFunction(
        () => { const b = document.getElementById("refreshBtn");
                return b && !b.classList.contains("loading") && !b.classList.contains("ok"); },
        { timeout: 120000 });
    } catch (e) { /* اگر تمام نشد، سنجش‌ها می‌گویند */ }
    const rf = await page.evaluate(async () => {
      const wait = (ms) => new Promise((r) => setTimeout(r, ms));
      const b = document.getElementById("refreshBtn");
      if (!b) return { missing: "دکمه" };
      const spin = b.querySelector(".rf-spin"), ico = b.querySelector(".rf-ico"),
            arc = b.querySelector(".rf-arc"), chk = b.querySelector(".rf-check");
      if (!spin || !ico || !arc || !chk) return { missing: "اسلاتِ نشانگر/گلیف/تیک" };
      await wait(420);   // از پلِ ترنزیشنِ حالتِ قبلی (ok → عادی) رد شویم
      const was = b.disabled;
      const idle = { spin: +getComputedStyle(spin).opacity, ico: +getComputedStyle(ico).opacity,
                     width: Math.round(b.getBoundingClientRect().width),
                     border: getComputedStyle(b).borderTopColor };
      // دکمه در حینِ کار واقعاً disabled است؛ همان مسیر را می‌سنجیم.
      b.disabled = true;
      b.classList.add("loading");
      await wait(340);
      const svg = getComputedStyle(spin.querySelector("svg"));
      const loading = {
        spin: +getComputedStyle(spin).opacity, ico: +getComputedStyle(ico).opacity,
        opacity: +getComputedStyle(b).opacity, cursor: getComputedStyle(b).cursor,
        spinAnim: svg.animationName, spinEase: svg.animationTimingFunction,
        arcAnim: getComputedStyle(arc).animationName,
        bar: getComputedStyle(b, "::before").content,
        sheen: getComputedStyle(b, "::after").content,
        border: getComputedStyle(b).borderTopColor, shadow: getComputedStyle(b).boxShadow,
        width: Math.round(b.getBoundingClientRect().width),
      };
      b.classList.remove("loading");
      b.classList.add("ok");
      await wait(320);
      const ok = { spin: +getComputedStyle(spin).opacity, check: +getComputedStyle(chk).opacity,
                   draw: getComputedStyle(chk.querySelector("path")).animationName };
      b.classList.remove("ok");
      b.disabled = was;
      return { idle, loading, ok };
    });
    if (rf.missing) fail("ساختارِ دکمه‌ی بروزرسانی ناقص است: " + rf.missing + " پیدا نشد");
    else {
      if (rf.idle.spin > 0.05) fail("نشانگرِ دکمه‌ی بروزرسانی در حالتِ عادی دیده می‌شود");
      if (rf.idle.ico < 0.9) fail("گلیفِ دکمه‌ی بروزرسانی در حالتِ عادی دیده نمی‌شود");
      if (rf.loading.spin < 0.9) fail("در حالتِ کار، نشانگرِ دکمه‌ی بروزرسانی دیده نمی‌شود");
      if (rf.loading.ico > 0.05)
        fail("در حالتِ کار، گلیفِ دکمه کنار نمی‌رود (یعنی چرخشِ گلیفِ متنی برگشته)");
      if (!/rfrot/.test(rf.loading.spinAnim))
        fail("حلقه‌ی نشانگرِ دکمه نمی‌چرخد (animationName=" + rf.loading.spinAnim + ")");
      if (!/linear/.test(rf.loading.spinEase))
        fail("چرخشِ حلقه easing دارد و در هر دور تند-و-کند می‌گردد (timingFunction="
          + rf.loading.spinEase + ") — باید linear باشد");
      if (!/rfdash/.test(rf.loading.arcAnim))
        fail("کمانِ نشانگرِ دکمه انیمیشنِ دُمِ نفس‌کش ندارد (animationName=" + rf.loading.arcAnim + ")");
      if (rf.loading.bar && rf.loading.bar !== "none")
        fail("افکتِ نوارِ خزنده به دکمه برگشته — قراردادِ «حالت، نه افکت» شکست");
      if (rf.loading.sheen && rf.loading.sheen !== "none")
        fail("افکتِ عبورِ نور به دکمه برگشته — قراردادِ «حالت، نه افکت» شکست");
      if (rf.loading.opacity < 0.99)
        fail("در حینِ کار دکمه محو می‌شود (opacity=" + rf.loading.opacity
          + ") — وضعیتِ کار باید روشن دیده شود");
      if (rf.loading.border === rf.idle.border)
        fail("در حینِ کار حاشیه‌ی دکمه تغییر نمی‌کند (حالتِ کار از حالتِ عادی جدا نیست)");
      if (!rf.loading.shadow || rf.loading.shadow === "none")
        fail("حالتِ کار هاله/سایه‌ی ملایم ندارد");
      if (rf.loading.width !== rf.idle.width)
        fail(`اندازه‌ی دکمه‌ی بروزرسانی در حالتِ کار عوض می‌شود (${rf.idle.width} → ${rf.loading.width})`);
      if (rf.ok.check < 0.9) fail("در حالتِ تأیید، تیکِ پایانِ دکمه دیده نمی‌شود");
      if (rf.ok.spin > 0.05) fail("در حالتِ تأیید، حلقه‌ی نشانگر کنار نمی‌رود");
      if (!/rfdraw/.test(rf.ok.draw))
        fail("تیکِ تأیید «کشیده» نمی‌شود (animationName=" + rf.ok.draw + ")");
      notes.push(`دکمه‌ی بروزرسانی: حلقه‌ی ${rf.loading.spinAnim} (${rf.loading.spinEase}) + دُمِ `
        + `${rf.loading.arcAnim} · ${rf.loading.cursor} · بدونِ افکتِ اضافه · اندازه ثابت (${rf.loading.width}px)`);
    }

    /* ۶.۸.۱) دسترسی‌پذیری: با «کاهشِ حرکت»، چرخش باید خاموش شود ولی نشانگر *بماند*
       (تپشِ نرم) — نه اینکه کلِ بازخوردِ کار ناپدید شود. */
    if (typeof page.emulateMediaFeatures === "function") {
      await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "reduce" }]);
      const rm = await page.evaluate(async () => {
        const wait = (ms) => new Promise((r) => setTimeout(r, ms));
        const b = document.getElementById("refreshBtn");
        b.classList.add("loading");
        await wait(140);
        const spin = b.querySelector(".rf-spin"), st = document.querySelector(".spin");
        const out = {
          svgAnim: getComputedStyle(spin.querySelector("svg")).animationName,
          spinAnim: getComputedStyle(spin).animationName,
          spinOpacity: +getComputedStyle(spin).opacity,
          statusAnim: st ? getComputedStyle(st).animationName : "n/a",
          statusOpacity: st ? +getComputedStyle(st).opacity : 1,
        };
        b.classList.remove("loading");
        return out;
      });
      await page.emulateMediaFeatures([]);
      if (rm.svgAnim !== "none")
        fail("با «کاهشِ حرکت»، حلقه‌ی دکمه هنوز می‌چرخد (animationName=" + rm.svgAnim + ")");
      if (!/rfsoft/.test(rm.spinAnim))
        fail("با «کاهشِ حرکت»، نشانگرِ دکمه به تپشِ نرم برنمی‌گردد (animationName=" + rm.spinAnim + ")");
      if (rm.spinOpacity < 0.2)
        fail("با «کاهشِ حرکت»، نشانگرِ دکمه کاملاً ناپدید می‌شود (opacity=" + rm.spinOpacity + ")");
      if (rm.statusAnim !== "n/a" && !/rfsoft/.test(rm.statusAnim))
        fail("با «کاهشِ حرکت»، نشانگرِ خطِ وضعیت نمی‌چرخد ولی به تپشِ نرم هم نمی‌رود");
      notes.push(`کاهشِ حرکت: چرخش خاموش · نشانگرها تپشِ نرم (${rm.svgAnim}/${rm.statusAnim}) ✓`);
    }
  } catch (e) {
    fail("بررسیِ حالتِ کارِ دکمه‌ی بروزرسانی ممکن نشد: " + e.message);
  }

  /* ۶.۷) قراردادِ نشانگر روی کرکره‌ی نمادها — سه چیزی که یک‌بار با هم شکستند و
     تجربه‌ی کاربر را خراب کردند:
       (۱) رفتنِ نشانگر روی خودِ کرکره پنل را نبندد (کاربر باید فرصتِ انتخاب داشته باشد؛
           قبلاً عبور از همان ۶px فاصله یا هر حرکتِ نشانگر روی مختصاتِ دکمه‌ها پنل را
           فوری می‌بست)؛
       (۲) پنلِ باز روی هیچ کنترلِ ردیفِ جستجو ننشیند — وگرنه کلیکِ «تحلیل کن» بی‌صدا
           به چیپِ نماد می‌خورد، نماد عوض می‌شود و هیچ تحلیلی اجرا نمی‌شود؛
       (۳) انتخاب (یا دورشدنِ واقعی) پنل را ببندد تا نمای اصلی تمیز بماند. */
  try {
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    const chipText = "GBPUSD";                 // گروهِ دیگر (نه NAS100 که در بندِ ۷ می‌آید)
    const HOLD = 800;                          // بیش از مهلتِ بستنِ پنل (۴۲۰ms)
    await page.mouse.move(10, 10);             // نشانگر را از ناحیه بیرون ببر تا mouseenter دوباره رخ دهد
    await page.evaluate(() => {
      document.getElementById("chips").classList.remove("open");
      document.getElementById("sym").blur();
    });
    await page.hover("#sym");
    await page.waitForSelector("#chips.open", { timeout: 5000 });

    // (۲) هندسه: پنلِ باز نباید روی هیچ کنترلِ ردیفِ جستجو (و نه بیرونِ ویوپورت) باشد.
    const geo = await page.evaluate(() => {
      const chips = document.getElementById("chips");
      const r = chips.getBoundingClientRect();
      const hit = (a, b) => !(a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom);
      const overlap = [...document.querySelectorAll(".searchrow button, .searchrow input")]
        .filter((el) => !chips.contains(el))
        .map((el) => ({ el, b: el.getBoundingClientRect() }))
        .filter((x) => x.b.width && x.b.height)
        .filter((x) => hit(x.b, r))
        .map((x) => (x.el.id || "«" + x.el.textContent.trim().slice(0, 16) + "»"));
      return { top: Math.round(r.top), bottom: Math.round(r.bottom), height: Math.round(r.height),
               overlap, vh: innerHeight };
    });
    if (geo.overlap.length)
      fail("پنلِ نمادها روی کنترل‌های ردیفِ جستجو افتاده است (کلیکِ کاربر دزدیده می‌شود): " + geo.overlap.join(" · "));
    if (geo.height < 120)
      fail(`پنلِ نمادها بی‌دلیل چلاق است (ارتفاع=${geo.height}px) — فضای واقعیِ ویوپورت استفاده نشده`);
    if (geo.top < 0 || geo.bottom > geo.vh)
      fail(`پنلِ نمادها از ویوپورت بیرون زده است (top=${geo.top} bottom=${geo.bottom} vh=${geo.vh})`);
    if (!geo.overlap.length)
      notes.push(`پنلِ نمادها هیچ کنترلی را نپوشاند · ارتفاع ${geo.height}px · داخلِ ویوپورت ✓`);

    // (۱) رفتنِ نشانگر روی وسطِ کرکره (نه روی چیپ) و ماندنِ بیش از مهلتِ بستن.
    const mid = await page.evaluate(() => {
      const r = document.getElementById("chips").getBoundingClientRect();
      return { x: (r.left + r.right) / 2, y: r.top + 6 };
    });
    await page.mouse.move(mid.x, mid.y);
    await wait(HOLD);
    if (!(await page.$eval("#chips", (el) => el.classList.contains("open"))))
      fail("با رفتنِ نشانگر روی خودِ کرکره، پنل بسته شد — کاربر فرصتِ انتخابِ نماد را از دست می‌دهد");

    // و روی خودِ چیپ هم باید باز بماند و همان چیپ زیرِ نشانگر باشد.
    const chipPos = await page.evaluate((t) => {
      const c = document.querySelector(`#chips .chip[data-sym="${t}"]`);
      if (!c) return null;
      const r = c.getBoundingClientRect();
      return { x: (r.left + r.right) / 2, y: (r.top + r.bottom) / 2 };
    }, chipText);
    if (!chipPos) fail(`چیپِ «${chipText}» در پنل پیدا نشد`);
    else {
      await page.mouse.move(chipPos.x, chipPos.y);
      await wait(HOLD);
      const onChip = await page.evaluate((t) => {
        const c = document.querySelector(`#chips .chip[data-sym="${t}"]`);
        const r = c.getBoundingClientRect();
        const under = document.elementFromPoint((r.left + r.right) / 2, (r.top + r.bottom) / 2);
        return { open: document.getElementById("chips").classList.contains("open"),
                 under: under ? (under.className || under.tagName) : "null" };
      }, chipText);
      if (!onChip.open) fail("با ماندنِ نشانگر روی چیپِ نماد، پنل بسته شد");
      if (!/chip/.test(onChip.under))
        fail(`روی چیپِ نماد، عنصرِ زیرِ نشانگر «${onChip.under}» است — کلیک به چیپ نمی‌رسد`);

      // (۳) انتخابِ واقعی با کلیک: کادر پُر، دکمه آماده، پنل بسته.
      await page.click(`#chips .chip[data-sym="${chipText}"]`);
      await page.waitForFunction(
        (t) => document.querySelector("#sym").value === t, { timeout: 5000 }, chipText);
      const after = await page.evaluate(() => ({
        pulse: document.getElementById("go").classList.contains("pulse"),
        open: document.getElementById("chips").classList.contains("open"),
        display: getComputedStyle(document.getElementById("chips")).display,
      }));
      if (!after.pulse) fail("پس از انتخابِ نماد از کرکره، دکمه‌ی «تحلیل کن» آماده (pulse) نشد");
      if (after.open || after.display !== "none") fail("پس از انتخابِ نماد، کرکره بسته نشد");
    }

    // دورشدنِ واقعی: پنل نباید خودسر باز بماند یا باز شود.
    await page.mouse.move(10, 10);
    await wait(HOLD);
    if ((await page.$eval("#chips", (el) => getComputedStyle(el).display)) !== "none")
      fail("با دورشدنِ نشانگر از ناحیه، کرکره بسته نشد");
    notes.push(`کرکره: با رفتنِ نشانگر بسته نشد · روی هیچ کنترلی ننشست · انتخابِ «${chipText}» آن را بست ✓`);
  } catch (e) {
    fail("قراردادِ نشانگر روی کرکره‌ی نمادها رعایت نشد: " + e.message);
  }

  /* ۷) رفتارِ واقعی: انتخاب از داخلِ پنل باید کادر را پُر کند، دکمه را آماده کند و
     پنل را ببندد. عمداً روی نمادِ «اندیکس» می‌چسبیم (نه اولین نماد) تا ثابت شود
     دسته‌های تازه هم واقعاً سیم‌کشی شده‌اند، نه فقط پنل را پر کرده‌اند. */
  try {
    const chipText = "NAS100";
    // اول نشانگر را از کادر بیرون ببر؛ وگرنه اگر نشانگر از قبل روی همان نقطه باشد،
    // رویدادِ mouseenter دوباره رخ نمی‌دهد و تست به حالتِ پنلِ قبلی وابسته می‌شود.
    await page.mouse.move(10, 10);
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

  /* ۹) PWA در عمل: سرویس‌ورکر فعال شود، پوستهٔ کشِ خودش پر شود، و با **قطعِ
     واقعیِ شبکه** اپ از همان کش بالا بیاید. لایهٔ ۱ (`selfcheck.py`) این قرارداد را
     استاتیک می‌سنجد؛ این‌جا در مرورگر اجرا می‌شود — چون «سرویس‌ورکرِ فعال ولی
     خالی» یا «آفلاینِ خراب» دقیقاً همان خرابیِ بی‌صدایی است که هیچ چکِ متنی
     نمی‌بیند. فهرستِ وعده‌های پوسته از **خودِ sw.js** خوانده می‌شود، نه از یک
     فهرستِ دستیِ کنارِ تست — پس اگر کسی پوسته را عوض کند، همین‌جا گرفته می‌شود. */
  try {
    // یادداشتِ پایانی فقط وقتی نوشته می‌شود که همین بند ایرادی نگرفته باشد —
    // وگرنه «آفلاین درست کار می‌کند» کنارِ پیام‌های قرمز می‌نشیند و گزارش را
    // گمراه می‌کند (همین گمراهی در جهش‌آزماییِ همین بند دیده شد).
    const pBefore = problems.length;
    // `page.target().createCDPSession()` روی همهٔ نسخه‌های puppeteer/core هست
    // (`page.createCDPSession` در نسخه‌های تازه deprecate شده).
    const cdp = await page.target().createCDPSession();
    await cdp.send("Network.enable");

    /* چرا روی هدفِ سرویس‌ورکر هم offline اعمال می‌شود: سرویس‌ورکر یک **هدفِ جدای
       CDP** است، پس `Network.emulateNetworkConditions` روی صفحه، شبکهٔ خودِ
       سرویس‌ورکر را نمی‌بندد؛ وگرنه «آفلاین» فقط ظاهری می‌شود: `fetch`ِ داخلِ
       سرویس‌ورکر به اینترنت می‌رسد و تست سبز می‌شود بدونِ اینکه چیزی از کش
       آمده باشد (همین تله در جهش‌آزماییِ همین بند لو رفت). */
    const swSeen = new Set(), swSessions = [];
    const swSessionsSync = async () => {
      for (const t of browser.targets()) {
        if (t.type() !== "service_worker" || swSeen.has(t)) continue;
        swSeen.add(t);
        try {
          const s = await t.createCDPSession();
          await s.send("Network.enable");
          swSessions.push(s);
        } catch (e) { /* هدفِ در حالِ خاموش‌شدن — مهم نیست */ }
      }
    };
    const netOff = async (off) => {
      const args = { offline: off, latency: 0, downloadThroughput: -1, uploadThroughput: -1 };
      await cdp.send("Network.emulateNetworkConditions", args);
      await swSessionsSync();
      for (const s of swSessions) {
        try { await s.send("Network.emulateNetworkConditions", args); } catch (e) { /* هدفِ رفته */ }
      }
    };

    const swText = await page.evaluate(() =>
      fetch("/sw.js", { cache: "no-store" }).then((r) => r.text()));
    const shellMatch = swText.match(/const\s+SHELL\s*=\s*\[([\s\S]*?)\]/);
    if (!shellMatch) fail("آرایهٔ SHELL در sw.js پیدا نشد — پوستهٔ کش قابلِ بازبینی نیست");
    const shell = shellMatch
      ? [...shellMatch[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]) : [];
    if (shell.length < 5) fail(`پوستهٔ کشِ sw.js تنها ${shell.length} مسیر دارد`);

    const swInfo = await page.evaluate(async () => {
      if (!("serviceWorker" in navigator)) return { unsupported: true };
      const reg = await Promise.race([
        navigator.serviceWorker.ready,
        new Promise((r) => setTimeout(() => r(null), 15000)),
      ]);
      if (!reg || !reg.active) return { active: false };
      return { active: true, scope: reg.scope };
    });
    if (swInfo.unsupported) fail("این مرورگر سرویس‌ورکر ندارد — قراردادِ آفلاین سنجیده نشد");
    else if (!swInfo.active) fail("سرویس‌ورکر فعال نشد (ثبت/نصبِ sw.js ناموفق بود)");

    // پوسته باید واقعاً در کشِ مرورگر بنشیند (addAll رد شود = کشِ خالی).
    let cached = [];
    for (let i = 0; i < 30; i++) {
      cached = await page.evaluate(async () => {
        const out = [];
        for (const k of await caches.keys()) {
          const c = await caches.open(k);
          out.push(...(await c.keys()).map((r) => new URL(r.url).pathname));
        }
        return [...new Set(out)];
      });
      if (shell.every((p) => cached.includes(p))) break;
      await wait(500);
    }
    const missingShell = shell.filter((p) => !cached.includes(p));
    if (missingShell.length)
      fail("پوستهٔ کش کامل پیش‌کش نشده (آفلاین ناقص می‌مانَد): " + missingShell.join("، "));

    await netOff(true);
    if (!swSessions.length)
      notes.push("هشدار: هدفِ سرویس‌ورکر برای مهارِ شبکه پیدا نشد — «آفلاین» فقط روی صفحه "
        + "اعمال شد؛ ادعای «از کش» را محتوای کش و کنترلِ سرویس‌ورکر تأیید می‌کند");

    /* آیکون با شبکهٔ قطع باید از **کشِ سرویس‌ورکر** بیاید. `cache: "reload"`
       عمدی است: وگرنه کشِ HTTPِ خودِ مرورگر جواب می‌دهد و تست می‌تواند سبز
       شود درحالی‌که شاخهٔ کش‌اولِ سرویس‌ورکر شکسته است (همین تله در
       جهش‌آزماییِ همین بند لو رفت). */
    const iconOff = await page.evaluate(async () => {
      try {
        const r = await fetch("/icon-192.png", { cache: "reload" });
        return { ok: r.ok, status: r.status, bytes: (await r.blob()).size };
      } catch (e) { return { err: String(e) }; }
    });
    if (iconOff.err) fail("با قطعِ شبکه، آیکونِ /icon-192.png از کش نیامد: " + iconOff.err);
    else if (!iconOff.ok) fail(`آیکون با شبکهٔ قطع وضعیتِ ${iconOff.status} داد`);
    else if (!(iconOff.bytes > 100)) fail("آیکونِ کش‌شده خالی است (bytes=" + iconOff.bytes + ")");

    /* دادهٔ زنده هرگز از کش سرو نشود: queryِ یکتا تا کشِ HTTPِ مرورگر هم در میان
       نباشد — وگرنه تست می‌تواند سبز شود درحالی‌که سرویس‌ورکر /api/ را کش کرده. */
    const apiOff = await page.evaluate(async () => {
      try {
        const r = await fetch("/api/health?offline_probe=" + Date.now(), { cache: "reload" });
        return { ok: r.ok, status: r.status };
      } catch (e) { return { err: String(e) }; }
    });
    if (!apiOff.err)
      fail("با قطعِ شبکه، /api/ جواب داد — دادهٔ زنده نباید از کش سرو شود");

    // ناوبریِ آفلاین: همان صفحه باید از پوستهٔ کش بیاید و اسکریپتش اجرا شود.
    const errsBefore = pageErrors.length;
    await page.reload({ waitUntil: "load", timeout: 30000 });
    const off = await page.evaluate(() => {
      const el = document.getElementById("bootWarn");
      const st = el ? getComputedStyle(el) : null;
      return {
        sym: !!document.getElementById("sym"),
        go: typeof ((document.getElementById("go") || {}).onclick) === "function",
        chips: document.querySelectorAll("#chips .chip").length,
        bootWarn: !!(el && st.display !== "none" && st.visibility !== "hidden" && el.offsetHeight > 0),
        controlled: !!(navigator.serviceWorker && navigator.serviceWorker.controller),
      };
    });
    if (!off.sym || !off.go) fail("صفحهٔ آفلاین بالا آمد ولی کلیدها/سیم‌کشی‌اش زنده نیست");
    if (off.chips < 8)
      fail(`صفحهٔ آفلاین چیپ‌های JS-ساخته را ندارد (${off.chips}) — یعنی از کش نیامده`);
    if (off.bootWarn) fail("در حالتِ آفلاین نوارِ «نگهبانِ بوت» دیده می‌شود");
    if (!off.controlled) fail("صفحهٔ آفلاین زیرِ کنترلِ سرویس‌ورکر نیست (از کش سرو نشده)");
    for (const e of pageErrors.slice(errsBefore))
      fail("خطای زمانِ اجرا در حالتِ آفلاین: " + e);
    if (problems.length === pBefore)
      notes.push(`آفلاین درست کار می‌کند: صفحه از پوستهٔ کش آمد · زیرِ کنترلِ سرویس‌ورکر ✓ · `
        + `آیکون از کش (${iconOff.bytes} بایت) · /api/ عمداً وصل نشد ✓ · `
        + `${shell.length}/${shell.length} مسیرِ پوسته پیش‌کش ✓`);
    else
      notes.push(`آفلاین ایراد گرفت (${problems.length - pBefore} مورد) — جزئیات در پیام‌های خطا`);

    // برگشتِ شبکه: اپ باید بی‌مشکل دوباره از شبکه بالا بیاید.
    await netOff(false);
    await page.reload({ waitUntil: "load", timeout: 30000 });
    const back = await page.evaluate(() => ({
      sym: !!document.getElementById("sym"),
      chips: document.querySelectorAll("#chips .chip").length,
    }));
    if (!back.sym || back.chips < 8)
      fail("بعد از برگشتِ شبکه، اپ دوباره سالم بالا نیامد");
    else notes.push("بعد از برگشتِ شبکه، اپ سالم بالا آمد");
  } catch (e) {
    fail("بررسیِ سرویس‌ورکر/آفلاین ممکن نشد: " + e.message);
  }

  /* ۱۰) اسکرین‌شات برای بازبینیِ انسانی. */
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
