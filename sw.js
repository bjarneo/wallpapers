const CACHE = 'wallpapers-v6';
const CACHEABLE = /\.(jpe?g|png|webp|gif|json|html|css|js)$/i;

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  if (req.headers.has('range')) return;

  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (!CACHEABLE.test(url.pathname)) return;

  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(req);
    if (cached) {
      if (url.pathname.endsWith('.json')) {
        fetch(req).then(res => { if (res.ok) cache.put(req, res.clone()); }).catch(() => {});
      }
      return cached;
    }
    try {
      const res = await fetch(req);
      if (res.ok && res.status === 200) cache.put(req, res.clone());
      return res;
    } catch (err) {
      const fallback = await cache.match(req);
      if (fallback) return fallback;
      throw err;
    }
  })());
});

self.addEventListener('message', (e) => {
  if (e.data === 'clear-cache') {
    caches.delete(CACHE).then(() => e.source && e.source.postMessage('cache-cleared'));
  }
});
