// سرویس‌ورکرِ pipfound
// قاعده: داده‌ی زنده هرگز کش نمی‌شود (/api/*) · صفحه شبکه‌اول · آیکون‌ها کش‌اول
// نامِ کش **دستی نیست**: جای «__CACHE_REV__» را سرور هنگامِ سرو با بازنگریِ کدِ
// روی دیسک پر می‌کند (SHAِ کوتاه). پس هر بازنگری خودش یک کشِ تازه می‌سازد و
// activate کشِ قبلی را پاک می‌کند — ارتقای کش به یادِ آدم وابسته نمی‌ماند.
const CACHE = "pipfound-__CACHE_REV__";
const SHELL = [
  "/", "/manifest.webmanifest",
  "/icon-180.png", "/icon-192.png", "/icon-512.png",
  "/icon-192-mask.png", "/icon-512-mask.png"
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(SHELL))        .catch(() => {})            // اگر اینترنت نبود، نصب را خراب نکن
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// جانشینیِ نسخهٔ تازه **با تأییدِ کاربر** انجام می‌شود: سرویس‌ورکرِ تازه در حالتِ
// انتظار می‌مانَد تا صفحه بنرِ «نسخهٔ تازه» را نشان دهد و کاربر دکمه را بزند
// (پیامِ SKIP_WAITING). اگر این‌جا خودسر skipWaiting می‌زدیم، بنر هیچ‌وقت معنا
// نداشت و کاربر وسطِ کار بی‌خبر از کدِ قدیم به کدِ تازه پرت می‌شد.
// پیامِ PF_WHO هم یک تشخیصِ کوچک است: صفحه می‌پرسد «چه نسخه‌ای فعال است؟»
self.addEventListener("message", (e) => {
  const d = (e && e.data) || {};
  if (d.type === "SKIP_WAITING") { self.skipWaiting(); return; }
  if (d.type === "PF_WHO" && e.source) e.source.postMessage({ type: "PF_WHO_ACK", cache: CACHE });
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

  // صفحه و اسکریپت‌ها: شبکه‌اول با پشتوانه‌ی کش (آفلاین هم باز می‌شود)
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      })
      .catch(() => caches.match(req).then((hit) => hit || caches.match("/")))
  );
});
