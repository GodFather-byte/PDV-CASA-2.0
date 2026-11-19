/* Guarda só a página. O cardápio em si (/v1/cardapio) vai sempre à rede: o preço muda no happy hour. */
const VERSAO = "cardapio-v4";
const ARQUIVOS = ["./","./index.html","./app.js","./estilo.css","./manifest.webmanifest","./icone.svg"];

self.addEventListener("install", (evento) => {
  evento.waitUntil(caches.open(VERSAO).then((cache) => cache.addAll(ARQUIVOS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(caches.keys().then((chaves) =>
    Promise.all(chaves.filter((c) => c.startsWith("cardapio-v") && c !== VERSAO).map((c) => caches.delete(c)))
  ).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (evento) => {
  const url = new URL(evento.request.url);
  if (!url.href.startsWith(self.registration.scope) || evento.request.method !== "GET") return;
  // O QR leva a loja e a mesa na consulta. O HTML é o mesmo; os preços e pedidos vão sempre à API.
  const pagina = evento.request.mode === "navigate" && url.pathname === new URL(self.registration.scope).pathname;
  const chave = pagina ? "./index.html" : evento.request;
  evento.respondWith(caches.open(VERSAO).then(cache => cache.match(chave))
    .then(guardado => guardado || fetch(evento.request)));
});
