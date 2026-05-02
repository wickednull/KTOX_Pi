// Minimal service worker for iOS PWA persistence.
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(clients.claim());
});

self.addEventListener('fetch', event => {
  // Let all network requests pass through; the WebUI should stay live-data first.
  event.respondWith(fetch(event.request));
});
