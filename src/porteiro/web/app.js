/* Porteiro: PIN, número da comanda e o resultado grande. Não grava nada no caixa. */

const AVISO = document.getElementById("aviso");
let pin = "";
let codigo = "";
let mesa = false;
let consultando = false;
let fluxo = null;
let cameraTimer = null;
let modo = "caixa";
let token = "";
let tokenNuvem = "";
let baseNuvem = "";
let chaveNuvem = "";
let urlCaixa = "";
let pinMemoria = "";
let listaTimer = null;
const INTERVALO_LISTA_MS = 20000;
const INTERVALO_LISTA_NUVEM_MS = 60000;
const ESPERA_FLUSH_MS = 35000;

function cabecalhos(extra) {
  const saida = Object.assign({ "Content-Type": "application/json" }, extra || {});
  if (token) saida.Authorization = "Bearer " + token;
  return saida;
}

function buscar(url, opcoes, ms) {
  const ctrl = new AbortController();
  const relogio = setTimeout(() => ctrl.abort(), ms);
  return fetch(url, Object.assign({ credentials: "same-origin" }, opcoes, { signal: ctrl.signal }))
    .finally(() => clearTimeout(relogio));
}

function textoErro(dados) {
  if (!dados) return "";
  if (typeof dados.detail === "string") return dados.detail;
  return dados.erro || "";
}

function mostrarAviso(texto) {
  if (!texto) {
    AVISO.hidden = true;
    AVISO.textContent = "";
    return;
  }
  AVISO.hidden = false;
  AVISO.textContent = texto;
}

function mostrar(id) {
  for (const tela of ["tela-pin", "tela-lista", "tela-consulta", "tela-resultado"]) {
    document.getElementById(tela).hidden = tela !== id;
  }
  document.body.dataset.tela = id;
  if (id !== "tela-resultado") delete document.body.dataset.situacao;
  if (id !== "tela-consulta") pararCamera();
  if (id === "tela-lista") iniciarLista();
  else pararLista();
}

function desenharPin() {
  document.getElementById("pin-mostra").textContent = pin ? "•".repeat(pin.length) : " ";
}

function desenharCodigo() {
  const texto = (mesa ? "M" : "") + codigo;
  document.getElementById("codigo-mostra").textContent = texto || "—";
  document.getElementById("botao-mesa").setAttribute("aria-pressed", mesa ? "true" : "false");
}

function teclaPin(tecla) {
  mostrarAviso("");
  if (tecla === "limpar") pin = "";
  else if (tecla === "apagar") pin = pin.slice(0, -1);
  else if (pin.length < 8) pin += tecla;
  desenharPin();
}

function teclaConsulta(tecla) {
  mostrarAviso("");
  if (tecla === "mesa") mesa = !mesa;
  else if (tecla === "apagar") codigo = codigo.slice(0, -1);
  else if (codigo.length < 5) codigo += tecla;
  desenharCodigo();
}

document.querySelectorAll(".teclado").forEach((teclado) => {
  teclado.addEventListener("click", (evento) => {
    const botao = evento.target.closest("button");
    if (!botao) return;
    if (teclado.dataset.teclado === "pin") teclaPin(botao.dataset.tecla);
    else teclaConsulta(botao.dataset.tecla);
  });
});

function normalizar(bruto) {
  const texto = String(bruto || "").trim();
  const letra = /^[MmCc]/.test(texto) ? texto[0].toUpperCase() : "";
  const digitos = texto.replace(/\D/g, "").replace(/^0+/, "");
  if (!digitos || digitos.length > 5) return null;
  return letra + digitos;
}

async function entrar() {
  if (pin.length < 4) {
    mostrarAviso("O PIN tem de 4 a 8 números.");
    return;
  }
  const corpo = { pin: pin };
  if (modo === "nuvem") {
    corpo.chave = document.getElementById("campo-loja").value.trim();
    if (!corpo.chave) {
      mostrarAviso("Informe a loja (a chave que está no caixa, em Configurações > Nuvem).");
      return;
    }
  }
  mostrarAviso("");
  let resposta;
  try {
    resposta = await buscar("api/entrar", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corpo) }, 20000);
  } catch (_erro) {
    mostrarAviso(modo === "nuvem"
      ? "A nuvem não respondeu. No plano grátis ela demora a acordar: espere e tente de novo."
      : "Sem ligação com o caixa. Confira o Wi-Fi do clube.");
    return;
  }
  const dados = await resposta.json().catch(() => ({}));
  if (!resposta.ok) {
    mostrarAviso(textoErro(dados) || "Não foi possível entrar.");
    if (resposta.status === 401 || resposta.status === 429) pin = "";
    desenharPin();
    return;
  }
  pinMemoria = corpo.pin;
  token = dados.token || "";
  urlCaixa = dados.caixa_url || "";
  if (modo === "caixa") await guardarNuvem();
  pin = "";
  desenharPin();
  codigo = "";
  mesa = false;
  desenharCodigo();
  mostrarAviso("");
  mostrar("tela-lista");
}

async function guardarNuvem() {
  try {
    const resposta = await buscar("api/config", { headers: cabecalhos() }, 4000);
    if (!resposta.ok) return;
    const dados = await resposta.json();
    baseNuvem = (dados.nuvem || "").replace(/\/$/, "");
    chaveNuvem = dados.chave || "";
  } catch (_erro) {
    baseNuvem = "";
  }
}

async function sessaoAtiva() {
  try {
    const resposta = await buscar("api/sessao", { headers: cabecalhos() }, 8000);
    return resposta.ok;
  } catch (_erro) {
    return false;
  }
}

async function consultar() {
  if (consultando) return;
  const q = normalizar((mesa ? "M" : "") + codigo);
  if (!q) {
    mostrarAviso("Não entendi o número. Digite a comanda (até 5 dígitos).");
    return;
  }
  consultando = true;
  mostrarAviso("");
  const caminho = "api/consulta?q=" + encodeURIComponent(q);
  if (urlCaixa && podeTentarCaixa(urlCaixa) && pinMemoria) {
    const noCaixa = await consultarNoCaixa(q);
    if (noCaixa && noCaixa.ok) {
      consultando = false;
      pintar(noCaixa.dados);
      return;
    }
  }
  const aqui = await consultarUrl(caminho, token, modo === "nuvem" ? 20000 : 4000);
  if (aqui && aqui.ok) {
    consultando = false;
    pintar(aqui.dados);
    return;
  }
  if (aqui && aqui.status === 401 && modo === "nuvem") {
    consultando = false;
    mostrarAviso("Entre de novo com o PIN.");
    mostrar("tela-pin");
    return;
  }
  if (aqui && aqui.status && aqui.status !== 401 && modo === "caixa") {
    consultando = false;
    mostrarAviso(aqui.mensagem);
    return;
  }
  if (modo === "caixa" && baseNuvem && chaveNuvem && pinMemoria) {
    const naNuvem = await consultarNuvem(q);
    consultando = false;
    if (naNuvem) {
      pintar(naNuvem);
      return;
    }
  }
  consultando = false;
  if (aqui && aqui.mensagem) mostrarAviso(aqui.mensagem);
  else mostrarAviso("Sem ligação com o caixa nem com a nuvem. Confira o Wi-Fi ou o 4G.");
}

async function consultarNoCaixa(q) {
  const base = urlCaixa.replace(/\/$/, "");
  try {
    const entrada = await buscar(base + "/api/entrar", {
      method: "POST",
      credentials: "omit",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: pinMemoria }),
    }, 1500);
    const sessao = await entrada.json().catch(() => ({}));
    if (!entrada.ok || !sessao.token) return null;
    return consultarUrl(base + "/api/consulta?q=" + encodeURIComponent(q), sessao.token, 1500);
  } catch (_erro) {
    return null;
  }
}

function podeTentarCaixa(url) {
  // Página https não consegue chamar o caixa em http (o navegador bloqueia). Aí vale a nuvem.
  return !(location.protocol === "https:" && url.startsWith("http:"));
}

async function consultarUrl(url, bearer, ms) {
  let resposta;
  try {
    const headers = {};
    if (bearer) headers.Authorization = "Bearer " + bearer;
    headers["X-PDV-Leitura"] = "1";
    resposta = await buscar(url, { headers: headers }, ms);
  } catch (_erro) {
    return null;
  }
  const dados = await resposta.json().catch(() => ({}));
  if (!resposta.ok) {
    return { ok: false, status: resposta.status, mensagem: textoErro(dados) || "Não foi possível consultar." };
  }
  return { ok: true, dados: dados };
}

async function consultarNuvem(q) {
  try {
    if (!tokenNuvem) {
      const entrada = await buscar(baseNuvem + "/api/entrar", {
        method: "POST",
        credentials: "omit",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin: pinMemoria, chave: chaveNuvem }),
      }, 20000);
      const dados = await entrada.json().catch(() => ({}));
      if (!entrada.ok) {
        mostrarAviso(textoErro(dados) || "A nuvem não aceitou o PIN.");
        return null;
      }
      tokenNuvem = dados.token || "";
      if (dados.caixa_url) urlCaixa = dados.caixa_url;
    }
    const resposta = await buscar(baseNuvem + "/api/consulta?q=" + encodeURIComponent(q), {
      credentials: "omit",
      headers: { Authorization: "Bearer " + tokenNuvem },
    }, 20000);
    const dados = await resposta.json().catch(() => ({}));
    if (!resposta.ok) {
      mostrarAviso(textoErro(dados) || "A nuvem não respondeu a consulta.");
      return null;
    }
    return dados;
  } catch (_erro) {
    mostrarAviso("A nuvem não respondeu. No plano grátis ela demora a acordar: espere e tente de novo.");
    return null;
  }
}

function pararLista() {
  if (listaTimer) clearInterval(listaTimer);
  listaTimer = null;
}

function iniciarLista() {
  carregarLista(false);
  pararLista();
  const espera = modo === "nuvem" ? INTERVALO_LISTA_NUVEM_MS : INTERVALO_LISTA_MS;
  listaTimer = setInterval(() => {
    if (document.hidden) return;
    if (document.body.dataset.tela === "tela-lista") carregarLista(true);
  }, espera);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    pararLista();
    return;
  }
  if (document.body.dataset.tela === "tela-lista") iniciarLista();
});

async function carregarLista(silencioso) {
  if (urlCaixa && podeTentarCaixa(urlCaixa) && pinMemoria) {
    const noCaixa = await listaNoCaixa();
    if (noCaixa) {
      pintarLista(noCaixa);
      return;
    }
  }
  const aqui = await consultarUrl("api/abertas", token, modo === "nuvem" ? 20000 : 4000);
  if (aqui && aqui.ok) {
    pintarLista(aqui.dados);
    return;
  }
  if (aqui && aqui.status === 401 && modo === "nuvem") {
    mostrarAviso("Entre de novo com o PIN.");
    mostrar("tela-pin");
    return;
  }
  if (modo === "caixa" && baseNuvem && chaveNuvem && pinMemoria) {
    const naNuvem = await listaNuvem();
    if (naNuvem) {
      pintarLista(naNuvem);
      return;
    }
  }
  if (!silencioso) {
    mostrarAviso((aqui && aqui.mensagem) || "Sem ligação com o caixa nem com a nuvem. Confira o Wi-Fi ou o 4G.");
  }
}

async function listaNoCaixa() {
  const base = urlCaixa.replace(/\/$/, "");
  try {
    const entrada = await buscar(base + "/api/entrar", {
      method: "POST",
      credentials: "omit",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: pinMemoria }),
    }, 1500);
    const sessao = await entrada.json().catch(() => ({}));
    if (!entrada.ok || !sessao.token) return null;
    const resposta = await consultarUrl(base + "/api/abertas", sessao.token, 1500);
    return resposta && resposta.ok ? resposta.dados : null;
  } catch (_erro) {
    return null;
  }
}

async function listaNuvem() {
  try {
    if (!tokenNuvem) {
      const entrada = await buscar(baseNuvem + "/api/entrar", {
        method: "POST",
        credentials: "omit",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin: pinMemoria, chave: chaveNuvem }),
      }, 20000);
      const dados = await entrada.json().catch(() => ({}));
      if (!entrada.ok) return null;
      tokenNuvem = dados.token || "";
      if (dados.caixa_url) urlCaixa = dados.caixa_url;
    }
    const resposta = await consultarUrl(baseNuvem + "/api/abertas", tokenNuvem, 20000);
    return resposta && resposta.ok ? resposta.dados : null;
  } catch (_erro) {
    return null;
  }
}

function horaDaLista(momento) {
  const texto = (momento || "").slice(11, 16);
  return texto ? "última atualização " + texto : "última atualização —";
}

function pintarLista(dados) {
  mostrarAviso("");
  const hora = document.getElementById("lista-hora");
  if (hora) hora.textContent = horaDaLista(dados.momento);
  window._momentoLista = dados.momento || "";
  document.getElementById("lista-origem").textContent = dados.origem_txt || "";
  const lista = document.getElementById("lista-comandas");
  const vazio = document.getElementById("lista-vazio");
  lista.replaceChildren();
  const comandas = dados.comandas || [];
  vazio.hidden = comandas.length > 0;
  for (const comanda of comandas) {
    const botao = document.createElement("button");
    botao.type = "button";
    botao.className = "cartao-comanda " + (comanda.situacao === "devendo" ? "devendo" : "liberada");
    const numero = document.createElement("span");
    numero.className = "numero";
    numero.textContent = comanda.cabecalho || ("Comanda " + comanda.numero);
    const valor = document.createElement("span");
    valor.className = "valor";
    valor.textContent = comanda.valor_txt || "R$ 0,00";
    const hora = document.createElement("span");
    hora.className = "hora";
    hora.textContent = comanda.aberta_txt ? "Aberta " + comanda.aberta_txt : "";
    const situacao = document.createElement("span");
    situacao.className = "situacao-txt";
    const total = comanda.total_txt && comanda.total_cent !== comanda.devido_cent
      ? " · conta " + comanda.total_txt : "";
    situacao.textContent = (comanda.titulo || "") + total;
    botao.append(numero, valor, hora, situacao);
    botao.addEventListener("click", () => {
      mesa = false;
      codigo = String(comanda.numero);
      desenharCodigo();
      consultar();
    });
    lista.append(botao);
  }
}

function pintar(dados) {
  document.body.dataset.situacao = dados.situacao === "devendo" ? "devendo" : "liberada";
  document.getElementById("res-cabecalho").textContent = dados.cabecalho || "";
  document.getElementById("res-titulo").textContent = dados.titulo || "";
  document.getElementById("res-valor").textContent = dados.valor_txt || "";
  document.getElementById("res-detalhe").textContent = dados.detalhe || "";
  document.getElementById("res-origem").textContent = dados.origem_txt || "";
  const lista = document.getElementById("res-itens");
  lista.replaceChildren();
  for (const item of dados.itens || []) {
    const li = document.createElement("li");
    const nome = document.createElement("span");
    nome.textContent = item.quantidade_txt ? item.quantidade_txt + " × " + item.nome : item.nome;
    const valor = document.createElement("span");
    valor.className = "valor";
    valor.textContent = item.total_txt || "";
    li.append(nome, valor);
    lista.append(li);
  }
  mostrar("tela-resultado");
  if (dados.situacao === "devendo" && navigator.vibrate) navigator.vibrate(180);
}

async function sair() {
  try {
    await buscar("api/sair", { method: "POST", headers: cabecalhos() }, 4000);
  } catch (_erro) {
    /* a tela volta ao PIN mesmo sem o caixa */
  }
  pin = "";
  pinMemoria = "";
  token = "";
  tokenNuvem = "";
  desenharPin();
  mostrarAviso("");
  mostrar("tela-pin");
}

function pararCamera() {
  if (cameraTimer) clearTimeout(cameraTimer);
  cameraTimer = null;
  if (fluxo) fluxo.getTracks().forEach((trilha) => trilha.stop());
  fluxo = null;
  const video = document.getElementById("camera");
  video.hidden = true;
  video.srcObject = null;
  document.getElementById("botao-parar-camera").hidden = true;
}

function aplicarLido(bruto) {
  const q = normalizar(bruto);
  if (!q) {
    mostrarAviso("Não entendi este código. Digite o número da comanda.");
    return;
  }
  mesa = q[0] === "M";
  codigo = q.replace(/\D/g, "");
  desenharCodigo();
  consultar();
}

async function cicloCamera(detector, video) {
  if (!fluxo) return;
  try {
    const codigos = await detector.detect(video);
    if (codigos.length) {
      const lido = codigos[0].rawValue;
      pararCamera();
      aplicarLido(lido);
      return;
    }
  } catch (_erro) {
    pararCamera();
    mostrarAviso("Este navegador não leu o código. Digite o número.");
    return;
  }
  cameraTimer = setTimeout(() => cicloCamera(detector, video), 250);
}

async function abrirCamera() {
  mostrarAviso("");
  if (!window.isSecureContext) {
    mostrarAviso("A câmera do celular só abre em endereço seguro. Digite o número, ou use um leitor que funciona como teclado.");
    return;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    mostrarAviso("Este celular não liberou a câmera. Digite o número da comanda.");
    return;
  }
  try {
    fluxo = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
  } catch (_erro) {
    mostrarAviso("Permita a câmera ou digite o número da comanda.");
    return;
  }
  const video = document.getElementById("camera");
  video.srcObject = fluxo;
  video.hidden = false;
  document.getElementById("botao-parar-camera").hidden = false;
  if (!("BarcodeDetector" in window)) {
    mostrarAviso("A câmera abriu, mas este navegador não lê código sozinho. Digite o número.");
    return;
  }
  let detector;
  try {
    detector = new BarcodeDetector({ formats: ["qr_code", "code_128", "code_39", "ean_13", "ean_8", "itf"] });
  } catch (_erro) {
    mostrarAviso("Este navegador não lê código pela câmera. Digite o número.");
    return;
  }
  cicloCamera(detector, video);
}

document.addEventListener("keydown", (evento) => {
  const tela = document.body.dataset.tela;
  if (evento.key === "Enter") evento.preventDefault();
  if (tela === "tela-pin") {
    if (/^\d$/.test(evento.key)) teclaPin(evento.key);
    else if (evento.key === "Backspace") teclaPin("apagar");
    else if (evento.key === "Escape") teclaPin("limpar");
    else if (evento.key === "Enter") entrar();
  } else if (tela === "tela-consulta") {
    if (/^\d$/.test(evento.key)) {
      if (codigo.length < 18) {
        codigo += evento.key;
        desenharCodigo();
      }
    } else if (evento.key === "Backspace") teclaConsulta("apagar");
    else if (evento.key === "Escape") { codigo = ""; mesa = false; desenharCodigo(); }
    else if (evento.key === "m" || evento.key === "M") { mesa = true; desenharCodigo(); }
    else if (evento.key === "c" || evento.key === "C") { mesa = false; desenharCodigo(); }
    else if (evento.key === "Enter") consultar();
  } else if (tela === "tela-lista" && evento.key === "Escape") {
    sair();
  } else if (tela === "tela-resultado" && (evento.key === "Enter" || evento.key === "Escape")) {
    codigo = "";
    desenharCodigo();
    mostrar("tela-lista");
  }
});

document.getElementById("botao-entrar").addEventListener("click", entrar);
async function atualizarAgora() {
  const hora = document.getElementById("lista-hora");
  if (modo !== "nuvem") {
    carregarLista(false);
    return;
  }
  if (hora) hora.textContent = "atualizando...";
  let pedido = {};
  try {
    const r = await buscar("/v1/sync/pedido", {
      method: "POST",
      credentials: "omit",
      headers: cabecalhos(),
    }, 8000);
    pedido = await r.json().catch(() => ({}));
  } catch (_erro) {
    pedido = {};
  }
  if (!pedido.conhecido) {
    if (hora) hora.textContent = horaDaLista("");
    carregarLista(false);
    return;
  }
  const inicio = Date.now();
  while (Date.now() - inicio < ESPERA_FLUSH_MS) {
    await new Promise((resolver) => setTimeout(resolver, 2000));
    try {
      const e = await buscar("/v1/sync/estado", { headers: cabecalhos() }, 8000);
      const j = await e.json().catch(() => ({}));
      if (j && j.id && j.id === pedido.id && j.momento) {
        await carregarLista(false);
        return;
      }
    } catch (_erro) { /* ainda é só a memória do servidor */ }
  }
  if (hora) hora.textContent = horaDaLista(window._momentoLista || "");
}

document.getElementById("botao-atualizar").addEventListener("click", () => atualizarAgora());
document.getElementById("botao-buscar").addEventListener("click", () => {
  codigo = "";
  mesa = false;
  desenharCodigo();
  mostrarAviso("");
  mostrar("tela-consulta");
});
document.getElementById("botao-sair-lista").addEventListener("click", sair);
document.getElementById("botao-consultar").addEventListener("click", consultar);
document.getElementById("botao-camera").addEventListener("click", abrirCamera);
document.getElementById("botao-parar-camera").addEventListener("click", pararCamera);
document.getElementById("botao-sair").addEventListener("click", sair);
document.getElementById("botao-nova").addEventListener("click", () => {
  codigo = "";
  desenharCodigo();
  mostrarAviso("");
  mostrar("tela-lista");
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

preparar();

async function preparar() {
  const params = new URLSearchParams(location.search);
  const campo = document.getElementById("campo-loja");
  if (params.get("loja")) campo.value = params.get("loja");
  try {
    const resposta = await buscar("api/saude", {}, 8000);
    const dados = await resposta.json().catch(() => ({}));
    modo = dados.modo || "caixa";
  } catch (_erro) {
    modo = "caixa";
  }
  const nuvem = modo === "nuvem";
  document.getElementById("rotulo-loja").hidden = !nuvem;
  campo.hidden = !nuvem;
  mostrar(await sessaoAtiva() ? "tela-lista" : "tela-pin");
}
