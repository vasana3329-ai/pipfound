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
  "rkStat", "rkSave", "installBtn", "bkDock", "bkToggle", "bkBody", "bkState",
  "alarmsToggle", "alarmsBody", "btToggle", "btBody", "rkToggle", "rkBody"];
const HANDLER_IDS = new Set(["rkSave", "installBtn"]);   // وایر داخلِ IIFE — با CDP سنجیده می‌شود
/* کنترل‌هایی که اپ با `.onclick =` به آن‌ها هندلر می‌دهد؛ اگر این‌ها تابع نباشند
   یعنی بلوکِ اسکریپت اجرا نشده یا نیمه‌کاره مرده است. */
const WIRED = ["go", "refreshBtn", "bt", "setupsBtn", "fundBtn", "archiveBtn",
  "rkSave", "bkToggle", "alarmsToggle", "btToggle", "rkToggle"];
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

    /* ۹.۰) نسخه‌بندیِ خودکارِ کش + بنرِ «نسخهٔ تازه»، از دیدِ **مرورگر**:
       نامِ کشی که سرور سرو می‌کند نباید جای‌گذارِ خام داشته باشد (وگرنه نامِ کش
       برای همیشه ثابت می‌مانَد و کشِ کهنه هیچ‌وقت ارتقا نمی‌یابد)، و بنر باید
       ساخته شده باشد ولی بدونِ نسخهٔ در انتظار پنهان بماند (بنرِ الکی = بنرِ
       بی‌اعتبار). رفتارِ واقعیِ بنر در بندِ ۹.۱ سنجیده می‌شود. */
    const cacheName = (swText.match(/\bCACHE\s*=\s*"([^"\n]+)"/) || [])[1] || "";
    if (swText.includes("__CACHE_REV__"))
      fail("sw.js سرو‌شده هنوز جای‌گذارِ «__CACHE_REV__» دارد — نامِ کش جانشین نشده");
    else if (!/^pipfound-\S{6,}/.test(cacheName))
      fail(`نامِ کشِ سرو‌شده («${cacheName}») به بازنگریِ کد گره نخورده`);

    const banner = await page.evaluate(() => {
      const b = document.getElementById("pfSwBanner");
      if (!b) return { exists: false };
      return { exists: true, shown: b.classList.contains("show"),
               display: getComputedStyle(b).display,
               btn: !!document.getElementById("pfSwBtn") };
    });
    if (!banner.exists) fail("بنرِ «نسخهٔ تازه» (#pfSwBanner) در صفحه ساخته نشده");
    else if (banner.shown || banner.display !== "none")
      fail("بنرِ «نسخهٔ تازه» بدونِ نسخهٔ در انتظار دیده می‌شود (بنرِ الکی)");
    else if (!banner.btn) fail("دکمهٔ «به‌روزرسانی» بنرِ نسخهٔ تازه وجود ندارد");
    else notes.push(`نسخه‌بندیِ خودکارِ کش: ${cacheName} · بنرِ به‌روزرسانی آماده و پنهان`);

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
    // نامِ کشی که مرورگر در آن می‌نویسد باید همان نامِ سرو‌شدهٔ sw.js باشد:
    // اگر سرور جای‌گذار را عوض کند، کشِ کهنه هیچ‌وقت پاک نمی‌شود.
    const cacheKeys = await page.evaluate(async () => await caches.keys());
    if (cacheName && !cacheKeys.includes(cacheName))
      fail(`کشِ فعال («${(cacheKeys || []).join("، ")}») با نامِ سرو‌شدهٔ sw.js `
        + `(«${cacheName}») نمی‌خواند`);

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

    /* ۹.۱) بنرِ «نسخهٔ تازه» در عمل — در یک زمینهٔ جدای مرورگر (استوریجِ جدا،
       پس هیچ چیزی به پروفایل/کشِ اصلی دست نمی‌زند): نصبِ اول انجام می‌شود،
       بعد همان sw.js با مسیرِ متفاوتی ثبت می‌شود تا یک **نسخهٔ تازه** بسازد که
       چون `skipWaiting` بی‌قید نیست باید در حالتِ انتظار بمانَد. آن‌وقت بنر
       باید دیده شود و کلیکِ کاربر روی «به‌روزرسانی» نسخهٔ تازه را فعال کند.
       این تنها جایی است که خودِ حلقهٔ ارتقا (نه فقط وجودِ عناصر) اجرا می‌شود. */
    const mkCtx = browser.createBrowserContext
      ? () => browser.createBrowserContext()
      : (browser.createIncognitoBrowserContext
        ? () => browser.createIncognitoBrowserContext() : null);
    if (!mkCtx) {
      notes.push("هشدار: این نسخهٔ puppeteer زمینهٔ جدای مرورگر ندارد — "
        + "بنرِ «نسخهٔ تازه» در عمل سنجیده نشد");
    } else {
      const ctx = await mkCtx.call(browser);
      try {
        const p2 = await ctx.newPage();
        await p2.setViewport({ width: 900, height: 1000 });
        await p2.goto(URL, { waitUntil: "load", timeout: 30000 });
        const first = await p2.evaluate(async () => {
          const b = document.getElementById("pfSwBanner");
          await Promise.race([navigator.serviceWorker.ready,
            new Promise((r) => setTimeout(r, 15000))]);
          return { exists: !!b, shown: !!(b && b.classList.contains("show")) };
        });
        if (!first.exists) fail("بنرِ «نسخهٔ تازه» در نصبِ تازهٔ اپ ساخته نشد");
        else if (first.shown) fail("در نصبِ اول (بدونِ نسخهٔ در انتظار) بنر دیده شد");

        const probe = await p2.evaluate(async () => {
          const out = { waiting: false, shown: false };
          try { await navigator.serviceWorker.register("/sw.js?pfprobe=1"); }
          catch (e) { out.err = "ثبتِ نسخهٔ تازه ممکن نشد: " + e; return out; }
          const shown = () => {
            const b = document.getElementById("pfSwBanner");
            if (!b) return false;
            return b.classList.contains("show") ||
                   (getComputedStyle(b).display !== "none" && b.offsetHeight > 0);
          };
          for (let i = 0; i < 120; i++) {
            const regs = await navigator.serviceWorker.getRegistrations();
            out.waiting = regs.some((r) => !!r.waiting);
            out.shown = shown();
            if (out.waiting && out.shown) break;
            await new Promise((r) => setTimeout(r, 250));
          }
          return out;
        });
        if (probe.err) fail(probe.err);
        else {
          if (!probe.waiting)
            fail("نسخهٔ تازهٔ سرویس‌ورکر در حالتِ انتظار نماند — بی‌قید جانشین شد");
          if (!probe.shown)
            fail("با بودنِ نسخهٔ تازهٔ در انتظار، بنرِ «نسخهٔ تازه» دیده نشد");
        }
        if (!probe.err && probe.waiting && probe.shown) {
          const nav = p2.waitForNavigation({ timeout: 20000 }).catch(() => null);
          await p2.click("#pfSwBtn");
          await nav;
          const after = await p2.evaluate(async () => {
            const c = navigator.serviceWorker.controller;
            const regs = await navigator.serviceWorker.getRegistrations();
            return { ctrl: c ? c.scriptURL : null,
                     waiting: regs.some((r) => !!r.waiting) };
          });
          if (!String(after.ctrl || "").includes("pfprobe=1"))
            fail("کلیکِ «به‌روزرسانی» نسخهٔ تازه را فعال نکرد (کنترل‌کنندهٔ صفحه هنوز کدِ کهنه است)");
          else
            notes.push("بنرِ «نسخهٔ تازه» در عمل کار می‌کند: با یک کلیک، نسخهٔ در انتظار "
              + "فعال شد و صفحه با کدِ تازه بالا آمد");
        }

        /* ۹.۲) «بعداً» تا پایانِ همان بازدید یادش می‌مانَد، و با بازدیدِ تازه
           برمی‌گردد. سه‌گانهٔ زیر، «بنرِ مرده» را از «یادِ بعداً» جدا می‌کند:
           (الف) با نسخهٔ در انتظار بنر دیده می‌شود؛ (ب) با «بعداً» پنهان می‌شود و
           چیزی در نشست ذخیره می‌شود، و پس از بارگذاریِ دوباره هم بنر
           برنمی‌گردد (خواستهٔ کاربر: در هر بارگذاری دوباره نپرسد)؛ (ج) با
           پاک‌کردنِ نشست (بازدیدِ تازه) همان بنر برمی‌گردد — پس پنهان‌بودن
           نشانهٔ یادِ «بعداً» است، نه بنرِ خراب. */
        let laterReady = false;
        if (!probe.err && probe.waiting && probe.shown) {
          /* نسخهٔ در انتظارِ *قطعی* برای بندِ ۹.۲: همان کارِ بندِ ۹.۱ تکرار می‌شود
             (`?pfprobe=2`) چون بعد از رفرشِ ۹.۱، نسخهٔ در انتظار از مسیرِ ثبتِ
             خودِ صفحه ساخته می‌شود و ممکن است تا زمانِ تصمیمِ بنر نرسیده باشد.
             بدونِ این، بندِ ۹.۲ روی بنرِ پنهان کلیک می‌کرد (خطای گویا نه — ولی
             سنجش بی‌معنا). */
          const probe2 = await p2.evaluate(async () => {
            const out = { waiting: false, shown: false };
            try { await navigator.serviceWorker.register("/sw.js?pfprobe=2"); }
            catch (e) { out.err = "ثبتِ نسخهٔ دومِ تازه ممکن نشد: " + e; return out; }
            const shown = () => {
              const b = document.getElementById("pfSwBanner");
              return !!(b && b.classList.contains("show") && b.offsetHeight > 0);
            };
            for (let i = 0; i < 120; i++) {
              const regs = await navigator.serviceWorker.getRegistrations();
              out.waiting = regs.some((r) => !!r.waiting);
              out.shown = shown();
              if (out.waiting && out.shown) break;
              await new Promise((r) => setTimeout(r, 250));
            }
            return out;
          });
          if (probe2.err) fail(probe2.err);
          else if (!probe2.waiting || !probe2.shown)
            fail("نسخهٔ دومِ تازه در انتظار نماند یا بنر دیده نشد — یادِ «بعداً» سنجیده نشد");
          else laterReady = true;
        }
        if (laterReady) {
          const ssSnap = () => p2.evaluate(() => {
            const out = {};
            try {
              for (let i = 0; i < sessionStorage.length; i++) {
                const k = sessionStorage.key(i);
                out[k] = sessionStorage.getItem(k);
              }
            } catch (e) { out["__err__"] = String(e); }
            return out;
          });
          const before = await ssSnap();
          const shownNow = () => p2.evaluate(() => {
            const b = document.getElementById("pfSwBanner");
            return !!(b && b.classList.contains("show") && b.offsetHeight > 0);
          });
          await p2.click("#pfSwHide");
          if (await shownNow()) fail("کلیکِ «بعداً» بنرِ «نسخهٔ تازه» را پنهان نکرد");
          else {
            const after = await ssSnap();
            const changed = Object.keys(after).some((k) => before[k] !== after[k]);
            if (!changed)
              fail("«بعداً» هیچ‌جا در نشست یاد نمی‌شود — با هر بارگذاریِ دوباره "
                + "تا پایانِ همان بازدید می‌پرسد");
            else {
              await p2.reload({ waitUntil: "load", timeout: 30000 });
              const still = await p2.evaluate(async () => {
                const b = document.getElementById("pfSwBanner");
                const shown = () => !!(b && b.classList.contains("show") && b.offsetHeight > 0);
                let waiting = false;
                for (let i = 0; i < 60; i++) {
                  const regs = await navigator.serviceWorker.getRegistrations();
                  waiting = regs.some((r) => !!r.waiting);
                  if (waiting) break;
                  await new Promise((r) => setTimeout(r, 250));
                }
                await new Promise((r) => setTimeout(r, 2000));   // فرصتِ مسیرِ بنر
                return { waiting, shown: shown() };
              });
              if (!still.waiting)
                fail("پس از «بعداً» و بارگذاریِ دوباره، نسخهٔ در انتظار در صف نماند "
                  + "— نسخهٔ تازه باید تا تصمیمِ کاربر در انتظار بماند");
              else if (still.shown)
                fail("«بعداً» تا پایانِ همان بازدید یادش نماند — با بارگذاریِ دوباره بنر برگشت");
              else {
                await p2.evaluate(() => { try { sessionStorage.clear(); } catch (e) {} });
                await p2.reload({ waitUntil: "load", timeout: 30000 });
                const fresh = await p2.evaluate(async () => {
                  const b = document.getElementById("pfSwBanner");
                  for (let i = 0; i < 60; i++) {
                    if (b && b.classList.contains("show") && b.offsetHeight > 0) return true;
                    await new Promise((r) => setTimeout(r, 250));
                  }
                  return false;
                });
                if (!fresh)
                  fail("با بازدیدِ تازه (یادِ پاک‌شده) بنرِ «نسخهٔ تازه» دیگر برنگشت "
                    + "— بنرِ مرده به‌جای یادِ «بعداً»");
                else
                  notes.push("«بعداً»ی بنر تا پایانِ همان بازدید یادش می‌مانَد "
                    + "(بارگذاریِ دوباره نمی‌پرسد) و در بازدیدِ تازه برمی‌گردد");
              }
            }
          }
        }
      } catch (e) {
        fail("سنجشِ بنرِ «نسخهٔ تازه» ممکن نشد: " + e.message);
      } finally {
        try { await ctx.close(); } catch (e) { /* زمینهٔ موقت */ }
      }
    }

    /* ۹.۳) شکافِ S10 — نسخهٔ تازه‌ای که **خودِ همین بارگذاری** راهش می‌اندازد هم
       باید بنر بدهد. ریشه: بعد از `register("/sw.js")` سرِ بارگذاری، شنوندهٔ
       `updatefound` بعد از دو `await` وصل می‌شد؛ اگر نصب پیش از آن تمام می‌شد،
       هم `reg.waiting` در چکِ قبلش `null` بود و هم رویداد از دست می‌رفت → کاربر
       بی‌خبر روی کدِ کهنه می‌مانْد.

       وسوسهٔ یک تستِ «امیدوار» این‌جاست: این مسابقه چند میلی‌ثانیه است، پس در
       یک اجرا سبز و در اجرای بعدی قرمز می‌شد. برای همین پنجره را **قطعی** پهن
       می‌کنیم (نه شانسی): پاسخِ `PF_WHO` عمداً ۱.۵ ثانیه دیر می‌رسد، پس با کدِ
       باگ‌دار شنونده دیر وصل می‌شود و نصب پیش از آن تمام شده — و با کدِ سالم
       «دیده‌بان» پیش از هر await وصل است و نصب را از دست نمی‌دهد. */
    if (!mkCtx) {
      notes.push("هشدار: بدونِ زمینهٔ جدای مرورگر، نسخهٔ تازهٔ «سرِ بارگذاری» سنجیده نشد");
    } else {
      const ctx3 = await mkCtx.call(browser);
      try {
        const p3 = await ctx3.newPage();
        await p3.setViewport({ width: 900, height: 1000 });
        await p3.goto(URL, { waitUntil: "load", timeout: 30000 });
        const boot = await p3.evaluate(async () => {
          let active = false, ctrl = false;
          for (let i = 0; i < 80; i++) {          // تا ۲۰ ثانیه
            const regs = await navigator.serviceWorker.getRegistrations();
            active = regs.some((r) => !!r.active);
            ctrl = !!navigator.serviceWorker.controller;
            if (active && ctrl) break;
            await new Promise((r) => setTimeout(r, 250));
          }
          return { active, ctrl };
        });
        if (!boot.active || !boot.ctrl)
          fail("بندِ ۹.۳: نصبِ اول کامل نشد (بدونِ کنترل‌کننده سنجش بی‌معنا است)");
        else {
          // پهن‌کردنِ عمدیِ پنجرهٔ مسابقه: پاسخِ وضعیتِ سرویس‌ورکر دیر می‌رسد.
          await p3.evaluateOnNewDocument(() => {
            try {
              const post = ServiceWorker.prototype.postMessage;
              ServiceWorker.prototype.postMessage = function (msg, ...rest) {
                const m = msg || {};
                if (m.type === "PF_WHO") {
                  return setTimeout(() => post.apply(this, [m, ...rest]), 1500);
                }
                return post.apply(this, [m, ...rest]);
              };
            } catch (e) { /* بی‌اثر */ }
          });
          // آماده‌سازی: یک نسخهٔ تازهٔ *کلیک‌کردنی* تا نسخهٔ فعالِ الان
          // با `/sw.js`ِ سرِ بارگذاری **فرق** داشته باشد.
          const seed = await p3.evaluate(async () => {
            try { await navigator.serviceWorker.register("/sw.js?pfprobe=9"); }
            catch (e) { return { err: "ثبتِ نسخهٔ آماده‌سازی ممکن نشد: " + e }; }
            const shown = () => {
              const b = document.getElementById("pfSwBanner");
              return !!(b && b.classList.contains("show") && b.offsetHeight > 0);
            };
            for (let i = 0; i < 120; i++) {
              const regs = await navigator.serviceWorker.getRegistrations();
              if (regs.some((r) => !!r.waiting) && shown()) return { waiting: true, shown: true };
              await new Promise((r) => setTimeout(r, 250));
            }
            return { waiting: false, shown: false };
          });
          if (seed.err) fail(seed.err);
          else if (!seed.waiting || !seed.shown)
            fail("آماده‌سازیِ بندِ ۹.۳ ممکن نشد (نسخهٔ تازه در انتظار نماند یا بنر نیامد)");
          else {
            const nav = p3.waitForNavigation({ timeout: 25000 }).catch(() => null);
            await p3.click("#pfSwBtn");       // فعال‌سازیِ «?pfprobe=9»
            await nav;
            await new Promise((r) => setTimeout(r, 1500));
            const after = await p3.evaluate(async () => {
              const b = document.getElementById("pfSwBanner");
              const seen = () => !!(b && b.classList.contains("show") && b.offsetHeight > 0);
              const c = navigator.serviceWorker.controller;
              let waiting = false, shown = seen();
              for (let i = 0; i < 80; i++) {           // تا ۲۰ ثانیه
                const regs = await navigator.serviceWorker.getRegistrations();
                waiting = regs.some((r) => !!r.waiting);
                shown = seen();
                if (waiting && shown) break;
                await new Promise((r) => setTimeout(r, 250));
              }
              return { ctrl: c ? c.scriptURL : null, waiting, shown };
            });
            if (!String(after.ctrl || "").includes("pfprobe=9"))
              fail("بندِ ۹.۳: نسخهٔ آماده‌سازی فعال نشد (کنترل‌کننده عوض نشد) — سنجش انجام نشد");
            else if (!after.waiting)
              fail("بندِ ۹.۳: بعد از فعال‌سازی، نسخهٔ تازه‌ای که ثبتِ سرِ بارگذاری راه "
                + "انداخته در صف نماند — سنجش بی‌معنا می‌شد");
            else if (!after.shown)
              fail("نسخهٔ تازه‌ای که خودِ همین بارگذاری راهش انداخته، بنر نداد "
                + "— کاربر بی‌خبر روی کدِ کهنه می‌مانَد (S10)");
            else
              notes.push("نسخهٔ تازهٔ «سرِ بارگذاری» هم بنر می‌دهد: با پاسخِ دیرهنگامِ "
                + "PF_WHO، شنوندهٔ دیرهنگام هم نسخهٔ در صف را از دست نمی‌دهد");
          }
        }
      } catch (e) {
        fail("سنجشِ نسخهٔ تازهٔ «سرِ بارگذاری» ممکن نشد: " + e.message);
      } finally {
        try { await ctx3.close(); } catch (e) { /* زمینهٔ موقت */ }
      }
    }
  } catch (e) {
    fail("بررسیِ سرویس‌ورکر/آفلاین ممکن نشد: " + e.message);
  }

  /* ۶.۹) کرکره‌های نمای اصلی (آلارم‌ها · بک‌تست · ریسک · پشتیبانِ داده) — خواسته‌ی
     کاربر: «این بخش‌ها فقط یه کلید باشن که روش کلیک بشه و کرکره‌شون باز بشه؛
     الان صفحه اصلی رو شلوغ و بچه‌گونه نشون می‌ده». قراردادِ سه‌مرحله‌ای برای هر
     چهار بخش در مرورگرِ واقعی: (۱) در بارگذاری نوار بسته است و محتوای داخل
     **دیده نمی‌شود**؛ (۲) یک کلیک روی نوار بدنه را باز می‌کند و کنترلِ داخلش
     واقعاً کلیک‌پذیر می‌شود (رویش چیزی نمی‌افتد)؛ (۳) کلیکِ دوباره می‌بندد.
     این رفتارِ رندرشده را هیچ چکِ متنی نمی‌بیند. */
  try {
    // پیش از سنجش، یادِ حافظهٔ محلیِ همین مرورگر پاک و صفحه دوباره بارگذاری می‌شود تا
    // «در بارگذاری بسته است» قطعی باشد (پروفایلِ مرورگر ممکن است از اجرای قبلی
    // وضعیتِ باز را نگه داشته باشد). در پایانِ همین بند هم دوباره پاک می‌شود.
    const clearFolds = () => page.evaluate(() => {
      try {
        Object.keys(localStorage)
          .filter((k) => k.indexOf("pf-folds") === 0)
          .forEach((k) => localStorage.removeItem(k));
      } catch (e) { /* حافظهٔ خاموشِ مرورگر */ }
    });
    await clearFolds();
    await page.reload({ waitUntil: "load", timeout: 30000 });
    const FOLDS = [
      { box: "alarmsDock", toggle: "alarmsToggle", body: "alarmsBody", inner: "alarmsList" },
      { box: "btPanel", toggle: "btToggle", body: "btBody", inner: "btFrom" },
      { box: "riskPanel", toggle: "rkToggle", body: "rkBody", inner: "rkSave" },
      { box: "bkDock", toggle: "bkToggle", body: "bkBody", inner: "expBtn" },
    ];
    const folds = await page.evaluate(async (specs) => {
      const wait = (ms) => new Promise((r) => setTimeout(r, ms));
      const disp = (el) => getComputedStyle(el).display;
      const visible = (el) => { const r = el.getBoundingClientRect(); return r.height > 0 && r.width > 0; };
      const out = [];
      for (const s of specs) {
        const box = document.getElementById(s.box), t = document.getElementById(s.toggle),
              b = document.getElementById(s.body), inner = document.getElementById(s.inner),
              st = box ? box.querySelector(".fold-st") : null;
        if (!box || !t || !b || !inner) { out.push({ box: s.box, missing: true }); continue; }
        const rec = { box: s.box, atLoad: { open: box.classList.contains("open"), display: disp(b),
                      innerVisible: visible(inner), aria: t.getAttribute("aria-expanded"),
                      summary: st ? (st.textContent || "").trim() : null } };
        t.click(); await wait(90);
        // ⚠ elementFromPoint با مختصاتِ **ویوپورت** کار می‌کند؛ اگر بخشِ بازشده زیرِ
        // تای صفحه باشد مقدارِ null می‌دهد و ادعای «کلیک‌پذیر» دروغ می‌شود. پس اول
        // خودِ کرکره را وسطِ صفحه می‌آوریم و بعد نقطه‌ی مرکزِ کنترل را می‌سنجیم.
        box.scrollIntoView({ block: "center" });
        await wait(80);
        const r2 = inner.getBoundingClientRect();
        const under = document.elementFromPoint((r2.left + r2.right) / 2, (r2.top + r2.bottom) / 2);
        rec.opened = { open: box.classList.contains("open"), display: disp(b),
                       innerVisible: visible(inner), aria: t.getAttribute("aria-expanded"),
                       inView: r2.top >= 0 && r2.bottom <= innerHeight,
                       clickable: !!under && inner.contains(under) };
        t.click(); await wait(90);
        rec.closedAgain = { open: box.classList.contains("open"), display: disp(b),
                            aria: t.getAttribute("aria-expanded") };
        out.push(rec);
      }
      return out;
    }, FOLDS);
    for (const r of folds) {
      if (r.missing) { fail(`کرکره‌ی «${r.box}» ناقص است: نوار/بدنه/کنترلِ داخلی پیدا نشد`); continue; }
      if (r.atLoad.open) fail(`کرکره‌ی «${r.box}» در بارگذاری باز است — باید جمع باشد`);
      if (r.atLoad.display !== "none")
        fail(`بدنه‌ی کرکره‌ی «${r.box}» در بارگذاری دیده می‌شود (display=${r.atLoad.display})`);
      if (r.atLoad.innerVisible)
        fail(`محتوای کرکره‌ی «${r.box}» در بارگذاری دیده می‌شود — نمای اصلی شلوغ می‌مانَد`);
      if (r.atLoad.aria !== "false")
        fail(`نوارِ «${r.box}» در بارگذاری aria-expanded="false" ندارد (مقدار: ${r.atLoad.aria})`);
      if (!r.opened.open || r.opened.display === "none")
        fail(`با یک کلیک روی نوار، بدنه‌ی کرکره‌ی «${r.box}» باز نشد`);
      if (!r.opened.innerVisible)
        fail(`پس از باز شدن، محتوای کرکره‌ی «${r.box}» دیده نمی‌شود`);
      if (!r.opened.clickable)
        fail(`کنترلِ داخلیِ کرکره‌ی «${r.box}» کلیک‌پذیر نیست (در ویوپورت: ${r.opened.inView})`);
      if (r.opened.aria !== "true")
        fail(`پس از باز شدن، aria-expandedِ «${r.box}» به true به‌روز نشد`);
      if (r.closedAgain.open || r.closedAgain.display !== "none")
        fail(`کلیکِ دوباره کرکره‌ی «${r.box}» را نبست`);
    }
    if (folds.some((r) => !r.missing && r.atLoad.summary && /در حالِ خواندن/.test(r.atLoad.summary)))
      fail("خلاصه‌ی وضعیتِ یکی از کرکره‌ها با اندپوینت پر نشد");
    const ok = folds.filter((r) => !r.missing);
    notes.push(`کرکره‌های نمای اصلی (${ok.length}/${FOLDS.length}): `
      + ok.map((r) => r.box + (r.atLoad.summary ? ` (${r.atLoad.summary})` : "")).join(" · ")
      + " — همه بسته در بارگذاری، باز/بسته با یک کلیک و کنترلِ کلیک‌پذیر ✓");

    // ── یادِ وضعیتِ بینِ بازدیدها (خواستهٔ کاربر: «هر بخش همان‌طور که کاربر
    // گذاشته بماند»). سنجشِ واقعی: حافظهٔ پاک → یک بخش باز/بسته می‌شود → صفحه
    // دوباره بارگذاری می‌شود و باید همان وضعیت بماند. در پایان پاک‌سازی تا
    // پیش‌فرضِ تمیز (همه بسته) برگردد و سنجشِ بعدی از حالتِ پاک شروع کند.
    const memBefore = problems.length;
    const memSpec = FOLDS[0];
    const readMem = () => page.evaluate((s) => {
      const bx = document.getElementById(s.box), tg = document.getElementById(s.toggle),
            bd = document.getElementById(s.body);
      return { open: bx.classList.contains("open"), aria: tg.getAttribute("aria-expanded"),
               display: getComputedStyle(bd).display };
    }, memSpec);
    const clickMem = () => page.evaluate((s) => {
      document.getElementById(s.toggle).click();
    }, memSpec);
    await clearFolds();
    await page.reload({ waitUntil: "load", timeout: 30000 });
    const m0 = await readMem();
    await clickMem();
    await new Promise((r) => setTimeout(r, 150));
    const m1 = await readMem();
    await page.reload({ waitUntil: "load", timeout: 30000 });
    const m2 = await readMem();
    await clickMem();
    await new Promise((r) => setTimeout(r, 150));
    await page.reload({ waitUntil: "load", timeout: 30000 });
    const m3 = await readMem();
    await clearFolds();
    await page.reload({ waitUntil: "load", timeout: 30000 });
    const m4 = await readMem();
    if (m0.open)
      fail(`کرکرهٔ «${memSpec.box}» با حافظهٔ پاک هم در بارگذاری باز است`);
    if (!m1.open || m1.aria !== "true")
      fail(`پیش‌نیازِ سنجشِ یاد برقرار نشد: کلیک، کرکرهٔ «${memSpec.box}» را باز نکرد`);
    if (!m2.open || m2.aria !== "true" || m2.display === "none")
      fail(`بخشِ بازِ «${memSpec.box}» بعد از بارگذاریِ دوباره باز نماند `
        + `— باز/بسته‌بودنِ بینِ بازدیدها یاد نمی‌مانَد`);
    if (m3.open)
      fail(`بخشِ بستهٔ «${memSpec.box}» بعد از بارگذاریِ دوباره باز برگشت `
        + `— بستنِ کاربر یاد نمی‌مانَد`);
    if (m4.open)
      fail("پاک‌کردنِ حافظه، پیش‌فرضِ تمیزِ (همه بسته) را برنگرداند");
    if (problems.length === memBefore)
      notes.push(`یادِ وضعیتِ کرکره‌ها («${memSpec.box}»): باز ماندنِ بخشِ باز و بسته `
        + "ماندنِ بخشِ بسته بعد از بارگذاریِ دوباره ✓ · پاک‌سازی = پیش‌فرضِ تمیز ✓");
  } catch (e) {
    fail("بررسیِ کرکره‌های نمای اصلی ممکن نشد: " + e.message);
  }

  /* ۶.۱۰) آرشیوِ اقتصادی در مرورگرِ واقعی: «فقط نتیجه + تأثیر»، بی‌گزارهٔ شرطی —
     خواسته‌ی کاربر: «می‌خوام توو آرشیو اقتصادی فقط نتیجه بیاد بعلاوهٔ تأثیرش، نه
     گزارهٔ شرطی». چکِ متنی می‌تواند بگوید متنِ کد عوض شده؛ فقط رندرِ واقعی نشان
     می‌دهد که هیچ ردیفِ شرطی‌ای در DOM نیست و خطِ تأثیر زیرِ خطِ نتیجه نشسته است.
     اگر در آن ۶ ساعت خبری نباشد، بند با ادعای بی‌ربط سبز نمی‌شود: فقط «رکوردِ
     خالی» یادداشت می‌شود و ادعاها روی حالتِ «خبر داریم» اجرا می‌شوند. درسِ CI:
     `.arc-v` فقط «نتیجهٔ عدددار» نیست — ردیفِ صادقِ «این خبر عددِ اعلام‌شده
     ندارد» و «منبعِ پاسخ نداد» هم `.arc-v v-fl`‌اند و عمداً خطِ تأثیر ندارند
     (جهت نامعلوم ⇒ اثرِ ساخته‌شده ممنوع). پس ادعای «خطِ تأثیر» فقط روی
     نتیجهٔ عدددارِ **جهت‌دار** اجرا می‌شود؛ وگرنه تست، صداقتِ داده را قرمز می‌کرد. */
  try {
    const arch = await page.evaluate(async () => {
      const wait = (ms) => new Promise((r) => setTimeout(r, ms));
      const btn = document.getElementById("archiveBtn");
      if (!btn) return { missing: true };
      btn.click();
      for (let i = 0; i < 40 && !document.getElementById("pipModal"); i++) await wait(250);
      for (let i = 0; i < 40; i++) {
        const m = document.getElementById("pipModal");
        if (m && (m.querySelector(".arc-ev") || m.querySelector(".arc-empty"))) break;
        await wait(250);
      }
      const m = document.getElementById("pipModal");
      const out = {
        modal: !!m,
        events: m ? m.querySelectorAll(".arc-ev").length : -1,
        rows: m ? m.querySelectorAll(".arc-d").length : -1,
        impacts: m ? m.querySelectorAll(".arc-i").length : -1,
        verdicts: m ? m.querySelectorAll(".arc-v").length : -1,
        // «نتیجهٔ عدددارِ جهت‌دار» — فقط ردیف‌هایی که هم عددِ اعلام‌شده دارند
        // (arc-num) و هم جهتِ قوی‌تر/ضعیف‌ترِ ارز. فقط همین‌ها باید خطِ تأثیر
        // داشته باشند؛ ردیفِ «طبقِ انتظار» (خنثی)، «بی‌عدد» و «منبع در دسترس
        // نبود» عمداً بی‌خطِ تأثیرند و نباید تست را قرمز کنند.
        withDir: m ? Array.from(m.querySelectorAll(".arc-v")).filter(
          (v) => v.querySelector(".arc-num") && /قوی\u200cتر|ضعیف\u200cتر/.test(v.textContent)
        ).length : -1,
        impactText: m && m.querySelector(".arc-i") ? m.querySelector(".arc-i").textContent.trim() : "",
        note: m && m.querySelector(".arc-note") ? m.querySelector(".arc-note").textContent : "",
        text: m ? m.textContent : "",
      };
      if (m) { const c = m.querySelector(".modal-close"); if (c) c.click(); }
      return out;
    });
    const before = problems.length;
    if (arch.missing) fail("کلیدِ 📁 آرشیو اقتصادی در صفحه نیست");
    else if (!arch.modal) fail("پنجرهٔ آرشیوِ اقتصادی با کلیک باز نشد");
    else {
      if (arch.rows !== 0)
        fail(`پنجرهٔ آرشیو ${arch.rows} ردیفِ گزارهٔ شرطی (⬆/⬇) نشان می‌دهد `
          + "— خواستهٔ «فقط نتیجه + تأثیرش، نه گزارهٔ شرطی» نقض شده");
      if (arch.withDir > 0 && arch.impacts === 0)
        fail("خطِ «تأثیرِ همین نتیجه» در پنجرهٔ آرشیو رندر نشد");
      if (arch.impacts > arch.withDir)
        fail("خطِ تأثیر از نتیجهٔ جهت‌دار بیشتر است (ردیفِ بی‌جهت تأثیر گرفته)");
      if (!/تأثیرِ همین نتیجه/.test(arch.note) && !/گزارهٔ شرطی/.test(arch.note))
        fail("یادداشتِ پنجرهٔ آرشیو قراردادِ «نتیجه + تأثیر، بی‌گزارهٔ شرطی» را توضیح نمی‌دهد");
      if (/⬆|⬇/.test(arch.text))
        fail("فلشِ گزارهٔ شرطی (⬆/⬇) هنوز در متنِ پنجرهٔ آرشیو دیده می‌شود");
      if (problems.length === before)
        notes.push(`آرشیوِ اقتصادی (${arch.events} خبر، ${arch.verdicts} ردیفِ نتیجه، `
          + `${arch.withDir} نتیجهٔ عدددارِ جهت‌دار): ردیفِ شرطی: ۰ ✓`
          + (arch.withDir === 0
              ? " — در این پنجره نتیجهٔ عدددارِ جهت‌دار نبود؛ فقط صداقتِ پنجره سنجیده شد"
              : "")
          + (arch.impactText ? ` — نمونه: ${arch.impactText.slice(0, 90)}` : ""));
    }
  } catch (e) {
    fail("بررسیِ پنجرهٔ آرشیوِ اقتصادی ممکن نشد: " + e.message);
  }

  /* ۶.۱۱) فیدِ خبرهای پیش‌رو: سوییچِ خودکارِ «اعلام شد → نتیجه + تأثیر»، نه دو
     سناریوی همیشگی — خواسته‌ی کاربر. صفحهٔ /fundamental در مرورگرِ واقعی:
     کارتِ رویدادِ اعلام‌شده (نشانِ «اعلام شد») نباید هیچ کارتِ شرطی
     (‏scard beat/miss) داشته باشد و باید کارتِ نتیجه (‏scard res) داشته باشد؛
     رویدادِ پیشِ‌رو همچنان دو سناریو دارد. درسِ دورِ قبل: فقط ادعایی سنجیده
     می‌شود که حالتش در این پنجره واقعاً موجود باشد — اگر رویدادِ اعلام‌شده‌ای
     نبود، «رکوردِ خالی» یادداشت می‌شود، نه سبزِ بی‌ادعا. */
  try {
    // توجه: `URL` این‌جا متغیرِ خودِ اسکریپت (آدرسِ پایه) است و سازندهٔ سراسریِ
    // `URL` را سایه می‌اندازد؛ پس آدرس با رشته ساخته می‌شود، نه `new URL(...)`.
    const feedUrl = String(URL).replace(/\/+$/, "") + "/fundamental";
    await page.goto(feedUrl, { waitUntil: "domcontentloaded", timeout: 45000 });
    const fd = await page.evaluate(async () => {
      const wait = (ms) => new Promise((r) => setTimeout(r, ms));
      for (let i = 0; i < 60; i++) {
        const list = document.getElementById("list");
        if (list && (list.querySelector(".ev") || list.querySelector(".empty") || list.querySelector(".err"))) break;
        await wait(250);
      }
      const err = document.querySelector("#list .err");
      const cards = Array.from(document.querySelectorAll(".ev"));
      const out = {
        cards: cards.length, err: err ? err.textContent.slice(0, 80) : "",
        announced: 0, announcedRes: 0, announcedCond: 0, impact: 0, sample: "",
        future: 0, futureWithCond: 0,
      };
      for (const c of cards) {
        const badge = c.querySelector(".cd-badge");
        const past = !!(badge && badge.classList.contains("past"));
        const cond = c.querySelectorAll(".scard.beat, .scard.miss").length;
        const res = c.querySelectorAll(".scard.res").length;
        if (past) {
          out.announced++;
          if (res) out.announcedRes++;
          out.announcedCond += cond;
          const imp = c.querySelector(".res-imp");
          if (imp) { out.impact++; if (!out.sample) out.sample = imp.textContent.trim().slice(0, 90); }
        } else {
          out.future++;
          if (cond > 0) out.futureWithCond++;
        }
      }
      return out;
    });
    const before = problems.length;
    if (fd.err) notes.push(`فیدِ خبرهای پیش‌رو: خطای بارگذاری (${fd.err}) — سنجشِ سوییچ انجام نشد`);
    else if (fd.cards === 0) notes.push("فیدِ خبرهای پیش‌رو: در این پنجره رویدادی نبود — سنجشِ سوییچ انجام نشد");
    else {
      if (fd.announcedCond > 0)
        fail(`فید: ${fd.announcedCond} کارتِ شرطی (⬆/⬇) زیرِ رویدادِ اعلام‌شده — `
          + "«سوییچِ خودکار به نتیجه + تأثیر» نقض شده");
      if (fd.announced > 0 && fd.announcedRes < fd.announced)
        fail(`فید: ${fd.announced - fd.announcedRes} رویدادِ اعلام‌شده کارتِ «نتیجه» ندارد`);
      if (fd.future > 0 && fd.futureWithCond < fd.future)
        fail(`فید: ${fd.future - fd.futureWithCond} رویدادِ پیشِ‌رو سناریوی شرطی ندارد `
          + "— تحلیلِ پیش از خبر نباید حذف شود");
      if (problems.length === before)
        notes.push(`فیدِ خبرهای پیش‌رو (${fd.announced} اعلام‌شده، ${fd.future} پیشِ‌رو): `
          + "رویدادِ اعلام‌شده بی‌گزارهٔ شرطی ✓"
          + (fd.impact ? ` · خطِ تأثیر: ${fd.impact}` : "")
          + (fd.sample ? ` — نمونه: ${fd.sample}` : "")
          + (fd.announced === 0
              ? " — در این پنجره رویدادِ اعلام‌شده نبود؛ فقط ساختارِ پیشِ‌رو سنجیده شد"
              : ""));
    }
  } catch (e) {
    fail("بررسیِ فیدِ خبرهای پیش‌رو ممکن نشد: " + e.message);
  } finally {
    try {
      await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
    } catch (e) {
      notes.push("بازگشت به صفحهٔ اصلی برای اسکرین‌شات ممکن نشد: " + e.message);
    }
  }

  /* ۶.۱۲) فیدِ زنده: پنجرهٔ گذشتهٔ ۶/۱۲/۲۴ + بجِ «N دقیقه پیش» بدونِ رفرشِ صفحه —
     خواسته‌ی کاربر. سه چیز سنجیده می‌شود، همه بدونِ انتظارِ زمانی (رویدادِ
     ساختگی به DATA تزریق می‌شود، پس به تقویمِ واقعی وابسته نیست):
       ۱) انتخابگرِ گذشته سه گزینه دارد و کلیک روی «۲۴ ساعت» واقعاً `?past=24`
          می‌فرستد (شمارشِ درخواست‌ها)؛
       ۲) با گذشتِ زمانِ فرضی، `tickBadges()` متنِ بج را جلو می‌برد بدونِ
          درخواستِ تازه و بدونِ بازساختنِ فهرست (نشانه‌ی جاگذاشته روی کارت
          باید سالم بمانَد)؛
       ۳) کارتِ بازِ کاربر از رندرِ دوره‌ای (که هر ۶۰ ثانیه رخ می‌دهد) جانِ
          سالم می‌برد — همان چیزی که مثلِ «رفرشِ صفحه» حس می‌شد. */
  try {
    const feedUrl2 = String(URL).replace(/\/+$/, "") + "/fundamental";
    await page.goto(feedUrl2, { waitUntil: "domcontentloaded", timeout: 45000 });
    const apiReqs = [];
    const onReq = (r) => {
      const u = r.url();
      if (u.indexOf("/api/fundamental") >= 0) apiReqs.push(u);
    };
    page.on("request", onReq);
    try {
      /* ۱) انتخابگرِ پنجرهٔ گذشته */
      const segInfo = await page.evaluate(async () => {
        const wait = (ms) => new Promise((r) => setTimeout(r, ms));
        for (let i = 0; i < 40; i++) {
          if (document.getElementById("pastSeg")) break;
          await wait(250);
        }
        const seg = document.getElementById("pastSeg");
        const btns = seg ? Array.from(seg.querySelectorAll("button")) : [];
        return {
          ok: !!seg,
          vals: btns.map((b) => b.dataset.p || ""),
          texts: btns.map((b) => b.textContent.trim()),
          active: btns.filter((b) => b.classList.contains("active")).map((b) => b.dataset.p),
        };
      });
      const before = problems.length;
      if (!segInfo.ok)
        fail("فیدِ زنده: انتخابگرِ پنجرهٔ گذشته (‏#pastSeg) در صفحه نیست — «۶/۱۲/۲۴ ساعت» قابلِ انتخاب نیست");
      else {
        const vals = segInfo.vals.slice().sort().join(",");
        if (vals !== "12,24,6")
          fail(`فیدِ زنده: گزینه‌های پنجرهٔ گذشته ${JSON.stringify(segInfo.vals)} است، نه ۶/۱۲/۲۴`);
        if (segInfo.active.length !== 1)
          fail("فیدِ زنده: در انتخابگرِ گذشته دقیقاً یک گزینه باید فعال باشد");
        // کلیک روی «۲۴ ساعت» باید واقعاً پارامترِ past=24 را به سرور بفرستد
        const n0 = apiReqs.length;
        await page.evaluate(() => {
          const b = document.querySelector('#pastSeg button[data-p="24"]');
          if (b) b.click();
        });
        let sent = "";
        for (let i = 0; i < 40; i++) {
          const hit = apiReqs.slice(n0).find((u) => u.indexOf("past=24") >= 0);
          if (hit) { sent = hit; break; }
          await new Promise((r) => setTimeout(r, 250));
        }
        if (!sent)
          fail("فیدِ زنده: کلیکِ «۲۴ ساعت» درخواستی با `past=24` نفرستاد — انتخابگر به سرور وصل نیست");
        else
          notes.push("فیدِ زنده: پنجرهٔ گذشته → " + sent.replace(/^.*\/api/, "api"));
      }

      /* ۲) بجِ زنده بدونِ رفرش + ۳) کارتِ بازِ ماندگار */
      const inject = await page.evaluate(async () => {
        const wait = (ms) => new Promise((r) => setTimeout(r, ms));
        for (let i = 0; i < 40; i++) {
          const l = document.getElementById("list");
          if (l && (l.querySelector(".ev") || l.querySelector(".empty") || l.querySelector(".err"))) break;
          await wait(250);
        }
        const out = { ok: false, before: "", dataM: "", err: "" };
        try {
          // توجه: `DATA`/`T0` با `let` در اسکریپتِ کلاسیک تعریف شده‌اند، پس روی
          // `window` نیستند ولی از همین ریلم با نام قابلِ خواندن/نوشتن‌اند.
          if (!DATA) DATA = { events: [] };
          if (!Array.isArray(DATA.events)) DATA.events = [];
          const iso = new Date(Date.now() - 5 * 60000).toISOString();
          DATA.events.unshift({
            iso, title: "PF TEST ANNOUNCED", title_fa: "آزمونِ اعلام‌شده", country: "USD",
            country_fa: "دلارِ آمریکا", icon: "\u{1F4CA}", cat: "آزمون", impact: "High",
            forecast: "1.0", previous: "0.9", et: "آزمون", tehran: "آزمون",
            passed: true, minutes_ago: 5,
            verdict: { found: true, actual: "1.2", outcome: "\u0635\u0639\u0648\u062f\u06cc",
                       beat: "\u0628\u0627\u0644\u0627\u062a\u0631 \u0627\u0632 \u0627\u0646\u062a\u0638\u0627\u0631",
                       dir: "\u0642\u0648\u06cc\u200c\u062a\u0631",
                       effect: { pairs: [["EUR/USD", "\u2193 \u0646\u0632\u0648\u0644"]],
                                 gold: ["XAU", "\u2193 \u0646\u0632\u0648\u0644", "\u062f\u0644\u0627\u0631\u0650 \u0642\u0648\u06cc"] } },
          });
          render();
          const card = document.querySelector('#list .ev[data-key*="PF TEST ANNOUNCED"]');
          if (!card) { out.err = "کارتِ اعلام‌شدهٔ آزمون رندر نشد"; return out; }
          const badge = card.querySelector(".cd-badge");
          out.before = badge ? badge.textContent.trim() : "";
          out.dataM = badge ? String(badge.getAttribute("data-m")) : "";
          card.setAttribute("data-pf-mark", "1");   // نشانه‌ی «فهرست بازسازی نشد»
          out.ok = true;
          return out;
        } catch (e) {
          out.err = String(e && e.message || e);
          return out;
        }
      });
      // پنجرهٔ باریکِ سنجشِ «بی‌درخواست»: فقط همین دو گام زیر شبکه‌ای ندارند
      const nBeforeTick = apiReqs.length;
      const live = await page.evaluate(() => {
        const out = { after: "", markKept: false, openKept: false, err: "" };
        try {
          const card = document.querySelector('#list .ev[data-key*="PF TEST ANNOUNCED"]');
          if (!card) { out.err = "کارتِ آزمون میانِ دو گام گم شد"; return out; }
          T0 = T0 - 3 * 60000;                        // ۳ دقیقهٔ فرضی گذشته
          tickBadges();
          const card2 = document.querySelector('#list .ev[data-key*="PF TEST ANNOUNCED"]');
          const badge2 = card2 && card2.querySelector(".cd-badge");
          out.after = badge2 ? badge2.textContent.trim() : "";
          out.markKept = !!(card2 && card2.getAttribute("data-pf-mark") === "1");
          // ۳) کارتِ بازِ کاربر نباید با رندرِ دوره‌ای بسته شود
          card2.querySelector(".ev-head").click();
          if (card2.classList.contains("open")) {
            render();
            const card3 = document.querySelector('#list .ev[data-key*="PF TEST ANNOUNCED"]');
            out.openKept = !!(card3 && card3.classList.contains("open"));
            if (card3) card3.querySelector(".ev-head").click();
          }
          // پاک‌سازیِ رویدادِ آزمون تا اسکرین‌شات/ادامهٔ اجرا آلوده نشود
          DATA.events = DATA.events.filter(
            (e) => String(e.title || "").indexOf("PF TEST ANNOUNCED") < 0);
          render();
          return out;
        } catch (e) {
          out.err = String(e && e.message || e);
          return out;
        }
      });
      const nAfterTick = apiReqs.length;
      if (inject.err)
        fail("فیدِ زنده: تزریقِ رویدادِ آزمون ممکن نشد — " + inject.err);
      else if (live.err)
        fail("فیدِ زنده: سنجشِ بجِ اعلام ممکن نشد — " + live.err);
      else {
        if (!/دقیقه پیش/.test(inject.before) || !/اعلام شد/.test(inject.before))
          fail(`فیدِ زنده: بجِ کارتِ اعلام‌شده «${inject.before}» است — متنِ «✅ اعلام شد · N دقیقه پیش» نیست`);
        if (inject.dataM !== "5")
          fail(`فیدِ زنده: minutes_ago سرور روی بج نیست (data-m=${inject.dataM || "—"}) — تیک مبنا ندارد`);
        if (live.after === inject.before)
          fail("فیدِ زنده: با گذشتِ زمان، بجِ «N دقیقه پیش» جلو نرفت — زنده نیست");
        if (!/8 دقیقه پیش/.test(live.after))
          fail(`فیدِ زنده: بج پس از ۳ دقیقهٔ فرضی «${live.after}» شد، نه ۸ دقیقه پیش`);
        if (!live.markKept)
          fail("فیدِ زنده: تیکِ بج فهرست را دوباره ساخت — همان «رفرشِ صفحه»ی ناخواسته");
        if (nAfterTick !== nBeforeTick)
          fail(`فیدِ زنده: تیکِ بج ${nAfterTick - nBeforeTick} درخواستِ /api/fundamental فرستاد — باید فقط متن را عوض کند`);
        if (!live.openKept)
          fail("فیدِ زنده: کارتِ بازِ کاربر با رندرِ دوره‌ای بسته شد — حسِ رفرشِ صفحه");
      }
      if (problems.length === before && !inject.err && !live.err)
        notes.push(`فیدِ زنده: بجِ اعلامی «${inject.before}» → «${live.after}» بدونِ درخواست/بازسازی ✓`
          + ` · کارتِ باز ماند ✓ · پنجرهٔ گذشته ۶/۱۲/۲۴ ✓`);
    } finally {
      try { page.off("request", onReq); } catch (e) { /* نسخه‌ی قدیمی: بی‌خیال */ }
    }
  } catch (e) {
    fail("بررسیِ فیدِ زنده (پنجرهٔ گذشته + بج) ممکن نشد: " + e.message);
  } finally {
    try {
      await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
    } catch (e) {
      notes.push("بازگشت به صفحهٔ اصلی بعد از باندِ فیدِ زنده ممکن نشد: " + e.message);
    }
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
