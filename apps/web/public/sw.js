/* Bioverse One service worker: installable app, offline page, and background push notifications.
 *
 * Privacy rules:
 * - Nothing from /api is ever cached or even intercepted. Health information stays out of CacheStorage.
 * - Only the hashed build files (/assets/*), the icons and the offline page are cached.
 * - Pages (navigations) always come from the network; offline, the static offline page is shown.
 *
 * Bump VERSION when the icons or the offline page change: old caches are deleted on activate.
 */
const VERSION = "v1";
const CACHE = `bioverse-static-${VERSION}`;
const OFFLINE_URL = "/offline.html";
const ICONS = ["/favicon.svg", "/icon-192.png", "/icon-512.png", "/icon-maskable-512.png",
  "/apple-touch-icon.png", "/badge-72.png"];
const PRECACHE = [OFFLINE_URL, ...ICONS];
const MAX_ASSETS = 80;   // hashed files pile up across releases; keep the newest
const DEFAULT_LINK = "/notifications";

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(PRECACHE.map((url) => new Request(url, { cache: "reload" })));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((n) => n.startsWith("bioverse-") && n !== CACHE).map((n) => caches.delete(n)));
    await self.clients.claim();
  })());
});

function isApi(url) {
  return url.pathname === "/api" || url.pathname.startsWith("/api/");
}

function isCacheable(url) {
  return url.pathname.startsWith("/assets/") || ICONS.includes(url.pathname) || url.pathname === OFFLINE_URL;
}

async function trim(cache) {
  const keys = await cache.keys();
  const assets = keys.filter((r) => new URL(r.url).pathname.startsWith("/assets/"));
  for (const r of assets.slice(0, Math.max(0, assets.length - MAX_ASSETS))) await cache.delete(r);
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  // Only complete, same-origin, successful responses; never anything sent with a user identity.
  if (response.ok && response.type === "basic" && !request.headers.has("X-Bioverse-User")
      && !request.headers.has("Authorization")) {
    await cache.put(request, response.clone());
    trim(cache);
  }
  return response;
}

async function networkFirstPage(request) {
  try {
    return await fetch(request);
  } catch {
    const offline = await caches.match(OFFLINE_URL);
    return offline || new Response("You're offline.", { status: 503, headers: { "Content-Type": "text/plain" } });
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || isApi(url)) return;   // straight to the network, untouched
  if (request.mode === "navigate") {
    event.respondWith(networkFirstPage(request));
  } else if (isCacheable(url)) {
    event.respondWith(cacheFirst(request));
  }
});

// ---------- push ----------

function safeLink(link) {
  if (typeof link !== "string" || !link.startsWith("/") || link.startsWith("//") || link.includes("\\")) {
    return DEFAULT_LINK;
  }
  return link;
}

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = {};
  }
  const title = typeof data.title === "string" && data.title ? data.title : "Bioverse One";
  const options = {
    body: typeof data.body === "string" && data.body ? data.body : "Open Bioverse One to see the details",
    icon: "/icon-192.png",
    badge: "/badge-72.png",
    tag: typeof data.tag === "string" && data.tag ? data.tag : "bioverse",
    data: { link: safeLink(data.link) },
  };
  event.waitUntil((async () => {
    await self.registration.showNotification(title, options);
    // Open copies of the app refresh their notification bell.
    const windows = await self.clients.matchAll({ type: "window" });
    windows.forEach((c) => c.postMessage({ type: "bioverse:push" }));
  })());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const link = safeLink(event.notification.data && event.notification.data.link);
  const target = new URL(link, self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const existing = windows.find((c) => new URL(c.url).origin === self.location.origin);
    if (existing) {
      await existing.focus();
      try {
        await existing.navigate(target);
      } catch {
        // Not controlled by this worker yet: ask the page to go there itself.
        existing.postMessage({ type: "bioverse:navigate", link });
      }
      return;
    }
    await self.clients.openWindow(target);
  })());
});

// The browser replaced the subscription (expiry or key change). Best effort: subscribe again with the same
// server key and tell the API. If that fails (signed out, demo sign-in), the app re-registers on next open.
self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil((async () => {
    try {
      const old = event.oldSubscription;
      const key = old && old.options && old.options.applicationServerKey;
      if (!key) return;
      const sub = event.newSubscription
        || await self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
      const json = sub.toJSON();
      await fetch("/api/push/subscriptions", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Bioverse-Client": "web" },
        body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys }),
      });
    } catch {
      // ignored: see above
    }
  })());
});
