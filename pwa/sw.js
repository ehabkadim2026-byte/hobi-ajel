// الواجهة تُخزَّن للعمل السريع؛ الأخبار تُجلب من الشبكة دائماً ويُعرض المخزن فقط عند انقطاع الإنترنت.
const SHELL = "hobi-ajel-shell-v15";
const FILES = ["./", "./index.html", "./manifest.webmanifest", "./icons/icon-192.png", "./icons/icon-512.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(SHELL).then(c => c.addAll(FILES))); self.skipWaiting(); });
self.addEventListener("activate", e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== SHELL && k !== "hobi-ajel-data").map(k => caches.delete(k))))); self.clients.claim(); });
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.endsWith(".json")) {
    e.respondWith(fetch(e.request, {cache: "no-store"}).then(r => { const copy = r.clone(); caches.open("hobi-ajel-data").then(c => c.put(e.request, copy)); return r; })
      .catch(() => caches.match(e.request)));
    return;
  }
  // الواجهة: الشبكة أولاً حتى يوصل أي إصلاح فوراً، والمخزن عند انقطاع الإنترنت
  e.respondWith(fetch(e.request).then(r => { const copy = r.clone(); caches.open(SHELL).then(c => c.put(e.request, copy)); return r; })
    .catch(() => caches.match(e.request)));
});
