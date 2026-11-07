// Service worker mínimo: hace la PWA instalable. Sin handler de fetch a
// propósito: todo depende del PC, no tiene sentido cachear respuestas.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
