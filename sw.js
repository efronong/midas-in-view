/* Midas in View service worker: shows the daily update notification. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || "Midas in View", {
    body: d.body || "Today's gold prices are updated.",
    icon: "/midas-in-view/icon-192.png",
    badge: "/midas-in-view/favicon-32.png",
    tag: "midas-daily",
    data: { url: d.url || "/midas-in-view/" }
  }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/midas-in-view/";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    for (const c of list) { if (c.url.includes("/midas-in-view/")) { c.navigate(url); return c.focus(); } }
    return self.clients.openWindow(url);
  }));
});
