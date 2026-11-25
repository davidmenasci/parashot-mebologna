// Service worker di Parashot MeBologna: permette l'uso senza rete.
// - pagina e icone: salvate all'installazione; la pagina si prende dalla rete se c'è, altrimenti dalla copia
// - dati e testi (cartella data/): si mostra subito la copia salvata e intanto la si aggiorna
// - caratteri di Google Fonts: salvati alla prima visita
const VERSIONE = "v1";
const CACHE = "parashot-" + VERSIONE;
const CACHE_FONT = "parashot-font";
const BASE = [
  "./", "index.html", "manifest.webmanifest",
  "icone/icon-192.png", "icone/icon-512.png", "icone/apple-touch-icon.png",
];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(BASE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(nomi => Promise.all(nomi.filter(n => n.startsWith("parashot-") && n !== CACHE && n !== CACHE_FONT)
        .map(n => caches.delete(n))))
      .then(() => self.clients.claim()));
});

function rete(req, cache){
  return fetch(req).then(r => {
    if(r && (r.ok || r.type === "opaque")) cache.put(req, r.clone());
    return r;
  });
}

self.addEventListener("fetch", e => {
  const req = e.request;
  if(req.method !== "GET") return;
  const url = new URL(req.url);

  // la pagina: rete per prima (così gli aggiornamenti arrivano subito), copia se la rete non risponde
  if(req.mode === "navigate"){
    e.respondWith(caches.open(CACHE).then(cache =>
      Promise.race([
        rete("index.html", cache),
        new Promise((_, no) => setTimeout(no, 4000)),
      ]).catch(() => cache.match("index.html").then(r => r || fetch(req)))));
    return;
  }

  // dati e testi: copia salvata subito, aggiornamento in sottofondo
  if(url.origin === location.origin && /\/data\//.test(url.pathname)){
    e.respondWith(caches.open(CACHE).then(cache =>
      cache.match(req).then(salvata => {
        const aggiorna = rete(req, cache).catch(() => salvata);
        return salvata || aggiorna;
      })));
    return;
  }

  // caratteri
  if(url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com"){
    e.respondWith(caches.open(CACHE_FONT).then(cache =>
      cache.match(req).then(salvata => salvata || rete(req, cache))));
    return;
  }

  // il resto dell'app (icone, manifest)
  if(url.origin === location.origin){
    e.respondWith(caches.match(req).then(salvata => salvata || fetch(req)));
  }
});
