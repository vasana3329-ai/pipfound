// سرویس‌ورکرِ pipfound
// قاعده: داده‌ی زنده هرگز کش نمی‌شود (/api/*) · صفحه شبکه‌اول · آیکون‌ها کش‌اول
const CACHE = "pipfound-v1";
const SHELL = [
  "/", "/manifest.webmanifest",
  "/icon-180.png", "/icon-192.png", "/icon-512.png",
  "/icon-192-mask.png", "/icon-512-mask.png"
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(SHELL))
      .catch(() => {})            // اگر اینترنت نبود، نصب را خراب نکن
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
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
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
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
