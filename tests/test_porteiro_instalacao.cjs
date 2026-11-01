/* Instalação em iPhone/iPad e Android, sem rede ou dependências de navegador. */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const codigo = fs.readFileSync(path.join(__dirname, "../src/porteiro/web/instalacao.js"), "utf8");

function ambiente({ agente = "iPhone", plataforma = "iPhone", toque = 1, app = false,
                     standalone = false, protocolo = "https:" } = {}) {
  const elementos = new Map();
  function elemento(id) {
    if (!elementos.has(id)) elementos.set(id, {
      hidden: true, disabled: false, atributos: {}, eventos: {},
      addEventListener(nome, acao) { this.eventos[nome] = acao; },
      setAttribute(nome, valor) { this.atributos[nome] = valor; },
      focus() { this.focado = true; },
    });
    return elementos.get(id);
  }
  const eventos = {};
  const media = { matches: app, addEventListener(nome, acao) { this[nome] = acao; } };
  vm.runInNewContext(codigo, {
    document: { getElementById: elemento },
    navigator: { userAgent: agente, platform: plataforma, maxTouchPoints: toque, standalone },
    location: { protocol: protocolo },
    window: { matchMedia: () => media, addEventListener: (nome, acao) => { eventos[nome] = acao; } },
  });
  return { elemento, eventos, media, botao: elemento("botao-instalar"), ajuda: elemento("ajuda-instalar") };
}

test("iPhone mostra instalação sem beforeinstallprompt e permite fechar com teclado", async () => {
  const a = ambiente();
  assert.equal(a.botao.hidden, false);
  await a.botao.eventos.click();
  assert.equal(a.ajuda.hidden, false);
  assert.equal(a.botao.atributos["aria-expanded"], "true");
  assert.equal(a.ajuda.focado, true);
  assert.equal(a.elemento("instalar-http").hidden, true);
  a.ajuda.eventos.keydown({ key: "Escape" });
  assert.equal(a.ajuda.hidden, true);
  assert.equal(a.botao.atributos["aria-expanded"], "false");
  assert.equal(a.botao.focado, true);
});

test("iPad identificado como Mac com toque também recebe ajuda", () => {
  assert.equal(ambiente({ agente: "Macintosh", plataforma: "MacIntel", toque: 5 }).botao.hidden, false);
  assert.equal(ambiente({ agente: "Macintosh", plataforma: "MacIntel", toque: 0 }).botao.hidden, true);
});

test("HTTP local informa a limitação e botão Entendi fecha a ajuda", async () => {
  const a = ambiente({ protocolo: "http:" });
  await a.botao.eventos.click();
  assert.equal(a.elemento("instalar-http").hidden, false);
  a.elemento("botao-fechar-instalar").eventos.click();
  assert.equal(a.ajuda.hidden, true);
});

test("app instalado não mostra convite, por display-mode ou navigator.standalone", () => {
  assert.equal(ambiente({ app: true }).botao.hidden, true);
  assert.equal(ambiente({ standalone: true }).botao.hidden, true);
});

test("Android preserva o convite nativo e fecha após aceitar", async () => {
  const a = ambiente({ agente: "Android", plataforma: "Linux" });
  let prompts = 0;
  assert.equal(a.botao.hidden, true);
  a.eventos.beforeinstallprompt({ preventDefault() {}, prompt: async () => { prompts++; },
    userChoice: Promise.resolve({ outcome: "accepted" }) });
  assert.equal(a.botao.hidden, false);
  await a.botao.eventos.click();
  assert.equal(prompts, 1);
  assert.equal(a.botao.hidden, true);
  assert.equal(a.botao.disabled, false);
});

test("convite invalidado não deixa botão travado e pode receber novo convite", async () => {
  const a = ambiente({ agente: "Android", plataforma: "Linux" });
  a.eventos.beforeinstallprompt({ preventDefault() {}, prompt: async () => { throw new Error("expirou"); } });
  await a.botao.eventos.click();
  assert.equal(a.botao.disabled, false);
  a.eventos.beforeinstallprompt({ preventDefault() {}, prompt: async () => {},
    userChoice: Promise.resolve({ outcome: "dismissed" }) });
  assert.equal(a.botao.hidden, false);
  await a.botao.eventos.click();
  assert.equal(a.botao.disabled, false);
});

test("instalação e mudança para modo app ocultam também uma ajuda aberta", async () => {
  const a = ambiente();
  await a.botao.eventos.click();
  a.eventos.appinstalled();
  assert.equal(a.botao.hidden, true);
  assert.equal(a.ajuda.hidden, true);
  const b = ambiente();
  b.media.matches = true;
  b.media.change();
  assert.equal(b.botao.hidden, true);
});
