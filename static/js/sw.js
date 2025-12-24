// static/js/sw.js
self.addEventListener('fetch', (event) => {
    // Esto es necesario para que se considere una PWA instalable
    event.respondWith(fetch(event.request));
});