const CACHE_NAME = "ai-gateway-shell-v2";
const SHELL_FILES = [
  "/",
  "/app.js",
  "/style.css",
  "/manifest.json",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Never touch the API stream or any non-GET request — this is a
  // Server-Sent Events POST endpoint and must reach the network untouched.
  if (request.method !== "GET" || new URL(request.url).pathname.startsWith("/api/")) {
    return;
  }

  if (!SHELL_FILES.includes(new URL(request.url).pathname)) {
    return;
  }

  // Network-first keeps deployments from showing an old UI indefinitely,
  // while the cached shell still makes the installed PWA open offline.
  event.respondWith(fetch(request).then((response) => {
    const copy = response.clone();
    caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
    return response;
  }).catch(() => caches.match(request)));
});
