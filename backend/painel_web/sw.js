/* Service Worker do WillPDV Painel.
 * Guarda só o "app shell" (arquivos estáticos) com cache-first e atualização em segundo plano.
 * Chamadas à API (/v1/) vão sempre à rede e NUNCA são guardadas: contêm dados sensíveis e o token. */

const VERSAO = "painel-v6";
const ARQUIVOS_SHELL = [
  "./",
  "./index.html",
  "./app.js",
  "./estilo.css",
  "./manifest.webmanifest",
  "./icones/icone-192.png",
  "./icones/icone-512.png",
  "./icones/icone-maskable-192.png",
  "./icones/icone-maskable-512.png",
];

// "reload": a versão nova do app nasce inteira da rede, nunca com um arquivo antigo que o cache HTTP do navegador ainda
// considere fresco (index.html novo com app.js velho quebraria a primeira abertura).
self.addEventListener("install", (evento) => {
  evento.waitUntil(
    caches.open(VERSAO)
      .then((cache) => cache.addAll(ARQUIVOS_SHELL.map((url) => new Request(url, { cache: "reload" }))))
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

function ehChamadaApi(url) {
  return url.pathname.startsWith("/v1/");
}

function ehArquivoDoShell(url) {
  const base = new URL(self.registration.scope);
  if (!url.pathname.startsWith(base.pathname)) return false;
  const relativo = "./" + url.pathname.slice(base.pathname.length);
  return relativo === "./" || ARQUIVOS_SHELL.includes(relativo);
}

self.addEventListener("fetch", (evento) => {
  const requisicao = evento.request;
  if (requisicao.method !== "GET") return;

  const url = new URL(requisicao.url);
  if (url.origin !== self.location.origin) return;

  // API: só rede. Não intercepta nem guarda.
  if (ehChamadaApi(url)) return;

  // Navegação dentro do escopo: entrega o index do cache e atualiza por trás.
  if (requisicao.mode === "navigate") {
    evento.respondWith(cacheFirstComAtualizacao(evento, new Request("./index.html"), requisicao));
    return;
  }

  if (ehArquivoDoShell(url)) {
    evento.respondWith(cacheFirstComAtualizacao(evento, requisicao, requisicao));
  }
});

// Responde do cache se houver; em paralelo busca na rede e atualiza o cache para a próxima vez.
async function cacheFirstComAtualizacao(evento, chaveCache, requisicaoRede) {
  const cache = await caches.open(VERSAO);
  const emCache = await cache.match(chaveCache, { ignoreSearch: true });

  const atualizacao = fetch(requisicaoRede, { cache: "no-cache" })
    .then((resposta) => {
      if (resposta && resposta.ok && resposta.type === "basic") {
        cache.put(chaveCache, resposta.clone());
      }
      return resposta;
    })
    .catch(() => null);

  if (emCache) {
    // Mantém o SW vivo até a atualização terminar, sem atrasar a resposta.
    evento.waitUntil(atualizacao);
    return emCache;
  }

  const daRede = await atualizacao;
  if (daRede) return daRede;

  return new Response("Sem conexão e sem cópia local do painel.", {
    status: 503,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
