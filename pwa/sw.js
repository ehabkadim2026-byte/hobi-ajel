// الواجهة تُخزَّن للعمل السريع؛ الأخبار تُجلب من الشبكة دائماً ويُعرض المخزن فقط عند انقطاع الإنترنت.
const SHELL = "hobi-ajel-shell-v22";
const FILES = ["./", "./index.html", "./manifest.webmanifest", "./icons/icon-192.png", "./icons/icon-512.png", "./icons/logo-mark.png"];
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
// تنبيهات الهاتف (Web Push): يرسلها المسار السريع بعد كل منشور بالقناة لمن فعّل «🔔 تنبيهات العاجل»
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (x) { d = {body: e.data ? e.data.text() : ""}; }
  const url = /^https:\/\/t\.me\/(akamedia_iq|hassawassal)\/\d+$/.test(d.url || "") ? d.url : self.registration.scope;
  e.waitUntil(self.registration.showNotification(String(d.title || "أكا ميديا").slice(0, 60), {
    body: String(d.body || "").slice(0, 240), icon: "icons/icon-192.png", badge: "icons/icon-192.png", dir: "rtl", lang: "ar",
    tag: d.tag || undefined, renotify: !!d.tag, data: {url}}));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || self.registration.scope;
  e.waitUntil(clients.matchAll({type: "window", includeUncontrolled: true}).then(ws => {
    if (url === self.registration.scope) { for (const w of ws) if ("focus" in w) return w.focus(); }
    return clients.openWindow(url);
  }));
});
