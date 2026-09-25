// سرویس‌ورکرِ pipfound
// قاعده: داده‌ی زنده هرگز کش نمی‌شود (/api/*) · صفحه شبکه‌اول · آیکون‌ها کش‌اول
// نامِ کش **دستی نیست**: جای «__CACHE_REV__» را سرور هنگامِ سرو با بازنگریِ کدِ
// روی دیسک پر می‌کند (SHAِ کوتاه). پس هر بازنگری خودش یک کشِ تازه می‌سازد و
// activate کشِ قبلی را پاک می‌کند — ارتقای کش به یادِ آدم وابسته نمی‌ماند.
//
// ارتقای **ایمن**: پاک‌کردنِ کشِ قبلی بی‌قید نیست. سرِ activate اول درستیِ
// پوستهٔ همین نسخه سنجیده می‌شود (هر مسیرِ SHELL باید در کشِ فعال باشد و پاسخش
// سالم). اگر نصبِ تازه نیمه‌کاره بود (اینترنت قطع شد، مسیری ۴۰۴ داد، addAll رد
// شد): (۱) از تازه‌ترین کشِ **سالمِ** قبلی ترمیم می‌شود؛ (۲) و اگر ترمیم نشد،
// هیچ کشی پاک نمی‌شود و کاربرِ آفلاین روی همان نسخهٔ سالمِ قبلی می‌مانَد
// (برگردانِ نسخه). صفحه با پیامِ PF_WHO وضعیت را می‌پرسد و اگر نسخه برنگشته
// باشد به کاربر می‌گوید.
const CACHE = "pipfound-__CACHE_REV__";
const SHELL = [
  "/", "/manifest.webmanifest",
  "/icon-180.png", "/icon-192.png", "/icon-512.png",
  "/icon-192-mask.png", "/icon-512-mask.png"
];

// درستیِ یک کش: همهٔ مسیرهای پوسته با پاسخِ سالم (۲xx) در آن باشند.
async function shellHealthy(name) {
  try {
    const c = await caches.open(name);
    for (const p of SHELL) {
      const hit = await c.match(p);
      if (!hit || !hit.ok) return false;
    }
    return true;
  } catch (e) {
    return false;
  }
}

// کش‌های دیگرِ همین اپ (به ترتیبِ ساخت — تازه‌ترین آخر است).
async function otherCaches() {
  const keys = await caches.keys();
  return keys.filter((k) => k !== CACHE);
}

// ترمیمِ نصبِ نیمه‌کاره: مسیرهای جامانده از تازه‌ترین کشِ سالمِ قبلی کپی می‌شوند.
// عمداً فقط از کشِ **سالم** برداشته می‌شود؛ یک کشِ نیمه‌کاره منبعِ ترمیم نیست.
async function healFromOld() {
  const keys = await otherCaches();
  for (const k of keys.reverse()) {
    if (!(await shellHealthy(k))) continue;
    const src = await caches.open(k);
    const dst = await caches.open(CACHE);
    for (const p of SHELL) {
      const have = await dst.match(p);
      if (have && have.ok) continue;
      const old = await src.match(p);
      // فقط پاسخِ سالم کپی می‌شود (همان قاعدهٔ هر put در این فایل).
      if (old && old.ok) {
        await dst.put(p, old.clone());
      }
    }
    return;
  }
}

// خواندنِ کش با اولویتِ کشِ فعالِ همین نسخه و بعد هر کشِ دیگری: در حالتِ
// «برگردانِ نسخه» (کشِ تازه ناقص است و کش‌های قبلی نگه داشته شده‌اند) همین
// ترتیب باعث می‌شود نسخهٔ سالمِ قبلی جواب بدهد.
async function fromCache(req) {
  const own = await caches.open(CACHE).then((c) => c.match(req));
  return own || (await caches.match(req));
}

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(SHELL))        .catch(() => {})            // اگر اینترنت نبود، نصب را خراب نکن
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    let healthy = await shellHealthy(CACHE);
    if (!healthy) {
      // نصبِ تازه ناقص بود — اول از نسخهٔ سالمِ قبلی ترمیم کن.
      await healFromOld();
      healthy = await shellHealthy(CACHE);
    }
    if (healthy) {
      // پوستهٔ تازه تأیید شد → حالا (و فقط حالا) کهنه‌ها پاک می‌شوند.
      const keys = await otherCaches();
      await Promise.all(keys.map((k) => caches.delete(k)));
    } else {
      // برگردانِ نسخه: کش‌های قبلی **نگه داشته می‌شوند** تا آفلاین کاربر روی
      // همان نسخهٔ سالمِ قبلی کار کند (پاک‌کردنشان خرابیِ برگشت‌ناپذیر بود).
      console.warn("[pipfound-sw] پوستهٔ نسخهٔ تازه ناقص است؛ کش‌های قبلی نگه داشته شد");
    }
    await self.clients.claim();
  })());
});

// جانشینیِ نسخهٔ تازه **با تأییدِ کاربر** انجام می‌شود: سرویس‌ورکرِ تازه در حالتِ
// انتظار می‌مانَد تا صفحه بنرِ «نسخهٔ تازه» را نشان دهد و کاربر دکمه را بزند
// (پیامِ SKIP_WAITING). اگر این‌جا خودسر skipWaiting می‌زدیم، بنر هیچ‌وقت معنا
// نداشت و کاربر وسطِ کار بی‌خبر از کدِ قدیم به کدِ تازه پرت می‌شد.
// پیامِ PF_WHO هم گزارشِ وضعیتِ پوسته است: «سالم است؟ چند کشِ قبلی نگه داشته
// شده؟» — صفحه با همین می‌فهمد که نسخه برگردانده شده یا نه.
self.addEventListener("message", (e) => {
  const d = (e && e.data) || {};
  if (d.type === "SKIP_WAITING") { self.skipWaiting(); return; }
  if (d.type === "PF_WHO" && e.source) {
    e.waitUntil((async () => {
      const ok = await shellHealthy(CACHE);
      const kept = (await otherCaches()).length;
      e.source.postMessage({ type: "PF_WHO_ACK", cache: CACHE,
                             shell_ok: ok, kept: kept, shell: SHELL.length });
    })());
  }
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;                     // POST/DELETE دست‌نخورده
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;      // فقط همین سرور
  if (url.pathname.startsWith("/api/")) return;         // داده‌ی زنده همیشه از شبکه

  const isIcon = /^\/icon-.*\.png$/.test(url.pathname) ||
                 url.pathname === "/manifest.webmanifest";
  if (isIcon) {                                          // آیکون‌ها: کش‌اول
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        // فقط پاسخِ سالم کش می‌شود: یک ۴۰۴/۵۰۰ گذرا نباید تا ارتقای کش
        // به‌عنوانِ «آیکون» بماند (کشِ کش‌اول ابدی است).
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      }))
    );
    return;
  }

  // صفحه و اسکریپت‌ها: شبکه‌اول با پشتوانه‌ی کش (آفلاین هم باز می‌شود).
  // فالبک از کشِ فعال شروع می‌کند و بعد به هر کشِ دیگری می‌رسد تا در حالتِ
  // برگردانِ نسخه، پوستهٔ سالمِ قبلی جواب بدهد.
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      })
      .catch(() => fromCache(req).then((hit) => hit || caches.match("/")))
  );
});
