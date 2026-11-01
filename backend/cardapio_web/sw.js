/* Guarda só a página. O cardápio em si (/v1/cardapio) vai sempre à rede: o preço muda no happy hour. */
const VERSAO = "cardapio-v1";
const ARQUIVOS = ["./","./index.html","./app.js","./estilo.css","./manifest.webmanifest","./icone.svg"];

self.addEventListener("install", (evento) => {
  evento.waitUntil(caches.open(VERSAO).then((cache) => cache.addAll(ARQUIVOS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(caches.keys().then((chaves) =>
    Promise.all(chaves.filter((c) => c !== VERSAO).map((c) => caches.delete(c)))
  ).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (evento) => {
  const url = new URL(evento.request.url);
  if (url.pathname.startsWith("/v1/") || evento.request.method !== "GET") return;
  evento.respondWith(
    caches.match(evento.request).then((guardado) => guardado || fetch(evento.request))
  );
});
