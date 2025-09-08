self.addEventListener("install", e => {
  console.log("✅ Service Worker installed");
});

self.addEventListener("fetch", e => {
  // For now just passthrough — could add offline caching later
  e.respondWith(fetch(e.request).catch(() => new Response("Offline")));
});

