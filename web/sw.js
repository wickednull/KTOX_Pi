const CACHE_NAME = 'ktox-v5';
const RUNTIME_CACHE = 'ktox-runtime-v5';

const ASSETS_TO_CACHE = [
  './',
  './index.html',
  './app.js',
  './shared.js',
  './ui.css',
  './device-shell.css',
  './manifest.webmanifest',
  './ktox.png',
];

self.addEventListener('install', (event) => {
  console.log('[SW] Installing service worker');
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[SW] Caching assets');
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
});

self.addEventListener('activate', (event) => {
  console.log('[SW] Activating service worker');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME && cacheName !== RUNTIME_CACHE) {
            console.log('[SW] Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  if (url.pathname === '/api/system/status' || url.pathname.startsWith('/api/')) {
    return event.respondWith(
      fetch(event.request).then((response) => {
        const cache = caches.open(RUNTIME_CACHE);
        cache.then((c) => c.put(event.request, response.clone()));
        return response;
      }).catch(() => {
        return caches.match(event.request);
      })
    );
  }

  if (event.request.method === 'GET') {
    event.respondWith(
      caches.match(event.request).then((response) => {
        if (response) {
          return response;
        }
        return fetch(event.request).then((response) => {
          if (!response || response.status !== 200 || response.type === 'error') {
            return response;
          }
          const responseToCache = response.clone();
          caches.open(RUNTIME_CACHE).then((cache) => {
            cache.put(event.request, responseToCache);
          });
          return response;
        }).catch(() => {
          return caches.match(event.request);
        });
      })
    );
  }
});
