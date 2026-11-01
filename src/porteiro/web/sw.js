/* Página do porteiro. Guarda só o visual (HTML, CSS, JS, ícones).
 * A consulta (/porteiro/api/) vai sempre ao caixa e nunca fica no celular:
 * um saldo antigo liberaria quem ainda deve. */

const VERSAO = "porteiro-v3";
const SHELL = [
  "./",
  "./index.html",
  "./app.js",
  "./instalacao.js",
  "./estilo.css",
  "./manifest.webmanifest",
  "./icones/icone-192.png",
  "./icones/icone-512.png",
  "./icones/icone-maskable-192.png",
  "./icones/icone-maskable-512.png",
];

self.addEventListener("install", (evento) => {
  evento.waitUntil(
    caches.open(VERSAO)
      .then((cache) => cache.addAll(SHELL.map((url) => new Request(url, { cache: "reload" }))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches.keys()
      .then((chaves) => Promise.all(chaves.filter((c) => c !== VERSAO).map((c) => caches.delete(c))))
      .then(() => self.clients.claim())
  );
});

function ehApi(url) {
  return url.pathname.includes("/api/");
}

self.addEventListener("fetch", (evento) => {
  const requisicao = evento.request;
  if (requisicao.method !== "GET") return;
  const url = new URL(requisicao.url);
  if (url.origin !== self.location.origin || ehApi(url)) return;

  if (requisicao.mode === "navigate") {
    evento.respondWith(doCache(evento, new Request("./index.html"), requisicao));
    return;
  }
  const base = new URL(self.registration.scope);
  if (!url.pathname.startsWith(base.pathname)) return;
  const relativo = "./" + url.pathname.slice(base.pathname.length);
  if (relativo === "./" || SHELL.includes(relativo)) {
    evento.respondWith(doCache(evento, requisicao, requisicao));
  }
});

async function doCache(evento, chave, rede) {
  const cache = await caches.open(VERSAO);
  const guardado = await cache.match(chave, { ignoreSearch: true });
  const atualizar = fetch(rede, { cache: "no-cache" })
    .then((resposta) => {
      if (resposta && resposta.ok && resposta.type === "basic") cache.put(chave, resposta.clone());
      return resposta;
    })
    .catch(() => null);
  if (guardado) {
    evento.waitUntil(atualizar);
    return guardado;
  }
  const daRede = await atualizar;
  if (daRede) return daRede;
  return new Response("Sem ligação com o caixa e sem cópia da página.", {
    status: 503,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
