/// <reference types="@sveltejs/kit" />
import { build, files, version } from '$service-worker';

const CACHE_NAME = `cache-v${version}`;
const ASSETS = [...build, ...files];

self.addEventListener('install', (event: any) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(ASSETS);
        }).then(() => {
            (self as any).skipWaiting();
        })
    );
});

self.addEventListener('activate', (event: any) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.map((key) => {
                    if (key !== CACHE_NAME) {
                        return caches.delete(key);
                    }
                })
            );
        }).then(() => {
            (self as any).clients.claim();
        })
    );
});

self.addEventListener('fetch', (event: any) => {
    // Only cache GET requests
    if (event.request.method !== 'GET') return;

    const url = new URL(event.request.url);
    // Don't cache API calls or hot-reloading websockets
    if (url.origin === self.location.origin && (url.pathname.startsWith('/api') || url.pathname.startsWith('/status') || url.pathname.startsWith('/models'))) {
        return;
    }

    event.respondWith(
        caches.open(CACHE_NAME).then(async (cache) => {
            const cachedResponse = await cache.match(event.request);
            if (cachedResponse) return cachedResponse;

            try {
                const response = await fetch(event.request);
                if (response.status === 200) {
                    cache.put(event.request, response.clone());
                }
                return response;
            } catch {
                return cachedResponse || new Response('Offline content not cached', { status: 408 });
            }
        })
    );
});
