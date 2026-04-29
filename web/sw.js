// sw.js – minimal service worker for iOS PWA persistence
self.addEventListener('install', event => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(clients.claim());
});

self.addEventListener('fetch', event => {
  // Let all network requests go through; no caching needed.
  event.respondWith(fetch(event.request));
});
