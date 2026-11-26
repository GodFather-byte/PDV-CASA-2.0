/* WillPDV Painel do dono: aplicação em JavaScript puro, sem dependências.
 * A API é servida na mesma origem em /v1/painel/. Dinheiro chega em centavos inteiros. */
(function () {
  "use strict";

  const API_BASE = "/v1/painel";
  const ESCOPO = "/painel/";
  const PREFIXO = "willpdv.painel.";
  const CHAVE_TOKEN = PREFIXO + "token";
  const CHAVE_LOJA = PREFIXO + "loja";
  const CHAVE_EXPIRA = PREFIXO + "expira_em";
  const PREFIXO_CACHE = PREFIXO + "cache.";
  // Sessão da rede (um dono, várias lojas): fica fora do PREFIXO de propósito. Ao abrir uma loja o painel apaga o que
  // é da loja anterior (tudo sob PREFIXO); a sessão da rede precisa sobreviver a isso, a recarregar e a fechar o app.
  const REDE_TOKEN = "willpdv.rede.token";
  const REDE_FLAG = "willpdv.rede.ativa";
  const SESSAO_COOKIE = "cookie";
  const REDE_GRUPO = "willpdv.rede.grupo";
  const REDE_EXPIRA = "willpdv.rede.expira_em";
  const REDE_ULTIMA = "willpdv.rede.ultima";            // loja (ou o resumo) que o dono da rede viu por último
  const RESUMO_DA_REDE = "";                            // valor do seletor para "Todas as lojas"
  const INTERVALO_AUTO_MS = 60000;
  const ESPERA_FLUSH_MS = 35000;
  const LIMITE_ATRASO_MIN = 10;

  const NOMES_MODALIDADE = {
    balcao: "Balcão",
    mesa: "Mesa",
    entrega: "Entrega",
    caderneta: "Caderneta",
  };
  const DIAS_SEMANA = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];

  const estado = {
    token: null,
    aguardandoFlush: false,
    _timer: null,
    loja: null,
    aba: "hoje",
    dia: null,            // null = dia operacional atual da loja
    resumo: null,
    historico: null,
    ranking: null,
    periodoProdutos: "hoje",
    periodoComissoes: "hoje",
    diaMovimento: null,
    atalhoPeriodo: "mes",
    periodoDe: "",
    periodoAte: "",
    periodo: null,
    atalhoLucro: "hoje",
    lucroDe: "",
    lucroAte: "",
    vendas: null,
    paginaVendas: 1,
    carregando: false,
    ultimaAtualizacao: 0,
    eventoInstalacao: null,
    lojas: null,           // lojas do dono (null = ainda não consultado)
  };

  // ------------------------------------------------------------------
  // Utilitários de DOM e formatação
  // ------------------------------------------------------------------

  const $ = (id) => document.getElementById(id);

  function el(tag, props, ...filhos) {
    const e = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === "class") e.className = v;
        else if (k === "text") e.textContent = v;
        else if (k === "style") e.style.cssText = v;
        else e.setAttribute(k, v === true ? "" : v);
      }
    }
    for (const f of filhos.flat()) {
      if (f === null || f === undefined || f === false) continue;
      e.append(f instanceof Node ? f : document.createTextNode(String(f)));
    }
    return e;
  }

  function limpar(no) {
    while (no.firstChild) no.removeChild(no.firstChild);
  }

  function formatarCentavos(cent) {
    const n = Math.round(Number(cent) || 0);
    const abs = Math.abs(n);
    const reais = String(Math.floor(abs / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    const centavos = String(abs % 100).padStart(2, "0");
    return (n < 0 ? "-" : "") + "R$ " + reais + "," + centavos;
  }

  // Valor curto para rótulos de gráfico: "350", "1,2 mil".
  function formatarReaisCurto(cent) {
    const reais = (Number(cent) || 0) / 100;
    if (reais >= 1000) {
      return (reais / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " mil";
    }
    return Math.round(reais).toLocaleString("pt-BR");
  }

  function formatarQuantidade(q) {
    return (Number(q) || 0).toLocaleString("pt-BR", { maximumFractionDigits: 4 });
  }

  function formatarInteiro(n) {
    return (Number(n) || 0).toLocaleString("pt-BR");
  }

  // "2026-10-18" -> "18/10/2026"
  function formatarData(iso) {
    if (!iso || iso.length < 10) return "—";
    return iso.slice(8, 10) + "/" + iso.slice(5, 7) + "/" + iso.slice(0, 4);
  }

  // "2026-10-18" -> "sáb 18/10"
  function formatarDiaCurto(iso) {
    if (!iso || iso.length < 10) return "—";
    const d = new Date(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)));
    return DIAS_SEMANA[d.getDay()] + " " + iso.slice(8, 10) + "/" + iso.slice(5, 7);
  }

  // "2026-10-18 17:55:03" -> "17:55"
  function formatarHora(dataHora) {
    if (!dataHora || dataHora.length < 16) return "—";
    return dataHora.slice(11, 16);
  }

  function formatarAtraso(min) {
    const m = Math.max(0, Math.round(Number(min) || 0));
    if (m < 60) return m + " min";
    const h = Math.floor(m / 60);
    const resto = m % 60;
    return h + " h" + (resto ? " " + String(resto).padStart(2, "0") + " min" : "");
  }

  function agoraLocalIso() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
      " " + p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  }

  function nomeModalidade(m) {
    return NOMES_MODALIDADE[m] || (m ? String(m) : "—");
  }

  const SVG_NS = "http://www.w3.org/2000/svg";
  const MESES_CURTOS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

  function datasDoAtalho(ateIso, atalho) {
    if (!ateIso) return ["", ""];
    if (atalho === "hoje") return [ateIso, ateIso];
    if (atalho === "ontem") {
      const ontem = somarDiasIso(ateIso, -1);
      return [ontem, ontem];
    }
    if (atalho === "7d") return [somarDiasIso(ateIso, -6), ateIso];
    if (atalho === "mes-passado") {
      const fim = somarDiasIso(ateIso.slice(0, 8) + "01", -1);
      return [fim.slice(0, 8) + "01", fim];
    }
    return [ateIso.slice(0, 8) + "01", ateIso];
  }

  function marcarAtalho(atalho) {
    document.querySelectorAll("[data-atalho]").forEach((b) => {
      const ativa = b.dataset.atalho === atalho;
      b.classList.toggle("ativa", ativa);
      b.setAttribute("aria-pressed", ativa ? "true" : "false");
    });
  }

  function sincronizarDatasDoAtalho() {
    if (!estado.atalhoPeriodo || !estado.resumo) return;
    const ate = estado.resumo.dia_operacional || estado.resumo.dia;
    const [de, fim] = datasDoAtalho(ate, estado.atalhoPeriodo);
    estado.periodoDe = de;
    estado.periodoAte = fim;
    if ($("periodo-de")) $("periodo-de").value = de;
    if ($("periodo-ate")) $("periodo-ate").value = fim;
  }

  function somarDiasIso(iso, delta) {
    const partes = String(iso || "").split("-").map(Number);
    if (partes.length < 3 || partes.some((n) => !n && n !== 0)) return "";
    const dt = new Date(partes[0], partes[1] - 1, partes[2] + delta);
    const p = (n) => String(n).padStart(2, "0");
    return dt.getFullYear() + "-" + p(dt.getMonth() + 1) + "-" + p(dt.getDate());
  }

  function diasDoPeriodo(ateIso, periodo) {
    const n = periodo === "30d" ? 30 : periodo === "7d" ? 7 : 1;
    const dias = new Set();
    for (let i = 0; i < n; i++) dias.add(somarDiasIso(ateIso, -i));
    return dias;
  }

  function rotuloMes(mes) {
    const n = Number(String(mes || "").slice(5, 7));
    return MESES_CURTOS[n - 1] || String(mes || "");
  }

  function textoResultado(cent) {
    const n = Number(cent) || 0;
    if (!n) return "Caixa conferido";
    return (n > 0 ? "Sobra " : "Falta ") + formatarCentavos(Math.abs(n));
  }

  function marcarFiltro(grupo, periodo) {
    document.querySelectorAll('.filtro[data-grupo="' + grupo + '"]').forEach((b) => {
      const ativa = b.dataset.periodo === periodo;
      b.classList.toggle("ativa", ativa);
      b.setAttribute("aria-pressed", ativa ? "true" : "false");
    });
  }

  // Barras em SVG (sem biblioteca). Tocar numa barra mostra o valor em `detalheId`.
  function desenharGrafico(alvo, pontos, aria, detalheId) {
    limpar(alvo);
    if (!pontos.length) return false;
    const W = 320, H = 148, topo = 6, base = 124, eixoY = 142;
    const maximo = Math.max(...pontos.map((p) => p.valor), 1);
    const largura = (W - 8) / pontos.length;
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", aria);
    svg.setAttribute("class", "grafico-svg");
    for (let i = 0; i < pontos.length; i++) {
      const p = pontos[i];
      const h = p.valor ? Math.max(2, Math.round((p.valor / maximo) * (base - topo))) : 1;
      const x = 4 + i * largura;
      const w = Math.max(largura - 1.6, 1);
      const rect = document.createElementNS(SVG_NS, "rect");
      rect.setAttribute("x", x.toFixed(2));
      rect.setAttribute("y", (base - h).toFixed(2));
      rect.setAttribute("width", w.toFixed(2));
      rect.setAttribute("height", String(h));
      rect.setAttribute("rx", "1.5");
      rect.setAttribute("class", "barra-svg" + (p.valor ? "" : " vazia") + (p.destaque ? " hoje" : ""));
      const title = document.createElementNS(SVG_NS, "title");
      title.textContent = p.titulo;
      rect.append(title);
      rect.addEventListener("click", () => { if (detalheId) $(detalheId).textContent = p.titulo; });
      svg.append(rect);
      if (p.rotulo) {
        const texto = document.createElementNS(SVG_NS, "text");
        texto.setAttribute("x", (x + w / 2).toFixed(2));
        texto.setAttribute("y", String(eixoY));
        texto.setAttribute("text-anchor", "middle");
        texto.textContent = p.rotulo;
        svg.append(texto);
      }
    }
    alvo.append(svg);
    if (detalheId) $(detalheId).textContent = pontos[pontos.length - 1].titulo;
    return true;
  }

  // O core grava a observação de item gelado como "Gelada" ou "Gelada - texto"; o selo já informa isso.
  function limparPrefixoGelada(observacao) {
    const texto = (observacao || "").trim();
    if (!/^gelada\b/i.test(texto)) return texto;
    return texto.replace(/^gelada\b\s*[-–:]?\s*/i, "").trim();
  }

  // ------------------------------------------------------------------
  // Armazenamento local (sessão e cache para uso offline)
  // ------------------------------------------------------------------

  function lerArmazenamento(chave) {
    try { return localStorage.getItem(chave); } catch (_) { return null; }
  }

  function gravarArmazenamento(chave, valor) {
    try { localStorage.setItem(chave, valor); } catch (_) { /* armazenamento cheio ou bloqueado */ }
  }

  function guardarCache(nome, dados) {
    gravarArmazenamento(PREFIXO_CACHE + nome, JSON.stringify({ salvo_em: agoraLocalIso(), dados }));
  }

  function lerCache(nome) {
    const bruto = lerArmazenamento(PREFIXO_CACHE + nome);
    if (!bruto) return null;
    try { return JSON.parse(bruto); } catch (_) { return null; }
  }

  function apagarTudoLocal() {
    try {
      const chaves = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith(PREFIXO)) chaves.push(k);
      }
      chaves.forEach((k) => localStorage.removeItem(k));
    } catch (_) { /* ignorado */ }
  }

  // ------------------------------------------------------------------
  // Cliente da API
  // ------------------------------------------------------------------

  class ErroApi extends Error {
    constructor(status, mensagem) {
      super(mensagem);
      this.status = status;
    }
  }

  class ErroRede extends Error {}

  async function chamarApi(caminho, opcoes = {}) {
    const cabecalhos = { Accept: "application/json", "X-PDV-Painel": "1" };
    if ((opcoes.metodo || "GET") === "GET") cabecalhos["X-PDV-Leitura"] = "1";
    if (opcoes.corpo !== undefined) cabecalhos["Content-Type"] = "application/json";
    if (estado.token && estado.token !== SESSAO_COOKIE && !opcoes.semToken) {
      cabecalhos.Authorization = "Bearer " + estado.token;
    }
    const tokenUsado = estado.token;

    let resposta;
    try {
      resposta = await fetch(API_BASE + caminho, {
        method: opcoes.metodo || "GET",
        headers: cabecalhos,
        body: opcoes.corpo !== undefined ? JSON.stringify(opcoes.corpo) : undefined,
        cache: "no-store",
        credentials: "same-origin",
      });
    } catch (_) {
      throw new ErroRede("Sem conexão com o servidor.");
    }

    let dados = null;
    try { dados = await resposta.json(); } catch (_) { dados = null; }

    if (resposta.status === 401 && !opcoes.semToken) {
      // Resposta atrasada de uma sessão que já foi trocada (outra loja) não derruba a sessão nova.
      if (tokenUsado !== estado.token) throw new ErroApi(401, "Sessão trocada.");
      encerrarSessao(false);
      throw new ErroApi(401, "Sessão expirada. Entre novamente.");
    }
    if (!resposta.ok) {
      const detalhe = dados && dados.detail ? String(dados.detail) : "Erro " + resposta.status + " no servidor.";
      throw new ErroApi(resposta.status, detalhe);
    }
    return dados;
  }

  // ------------------------------------------------------------------
  // Sessão (login / sair)
  // ------------------------------------------------------------------

  function sessaoValida() {
    if (!estado.token) return false;
    const expira = lerArmazenamento(CHAVE_EXPIRA);
    if (expira && expira < agoraLocalIso()) return false;
    return true;
  }

  function mostrarLogin() {
    $("tela-app").hidden = true;
    $("tela-login").hidden = false;
    mostrarCartaoLogin("form-login");
    const loja = estado.loja && estado.loja.chave ? estado.loja.chave : lerArmazenamento(CHAVE_LOJA + ".chave");
    if (loja && !$("campo-loja").value) $("campo-loja").value = loja;
    $("campo-senha").value = "";
    setTimeout(() => (loja ? $("campo-senha") : $("campo-loja")).focus(), 50);
  }

  function mostrarApp() {
    $("tela-login").hidden = true;
    $("tela-app").hidden = false;
    $("nome-loja").textContent = estado.loja && estado.loja.nome ? estado.loja.nome : (estado.loja && estado.loja.chave) || "Loja";
    $("tela-rede").hidden = true;
    mostrarFaixaDaRede();
    atualizarLinkCardapio();
  }

  function atualizarLinkCardapio() {
    const link = $("link-cardapio");
    const chave = estado.loja && estado.loja.chave;
    if (!chave) {
      link.hidden = true;
      return;
    }
    link.hidden = false;
    link.href = "/cardapio/?loja=" + encodeURIComponent(chave);
  }

  function encerrarSessao(avisarServidor) {
    // Loja aberta pela rede cuja sessão venceu: volta para a lista de lojas em vez de pedir a senha de novo.
    if (!avisarServidor && estado.modo === "loja" && redeGuardada()) {
      voltarParaRede();
      return;
    }
    const chaveLoja = estado.loja && estado.loja.chave;
    if (avisarServidor && estado.token) {
      fetch(API_BASE + "/sair", {
        method: "POST",
        headers: { "X-PDV-Painel": "1" },
        credentials: "same-origin",
        keepalive: true,
      }).catch(() => { /* já estamos saindo */ });
    }
    esquecerRede();
    estado.token = null;
    estado.loja = null;
    estado.grupo = null;
    estado.modo = null;
    $("faixa-rede").hidden = true;
    const telaRede = $("tela-rede");
    if (telaRede) telaRede.hidden = true;
    const formSenha = $("form-senha-rede");
    if (formSenha) formSenha.hidden = true;
    estado.lojas = null;
    estado.resumo = null;
    estado.historico = null;
    estado.vendas = null;
    estado.dia = null;
    estado.paginaVendas = 1;
    apagarTudoLocal();
    if (chaveLoja) gravarArmazenamento(CHAVE_LOJA + ".chave", chaveLoja);
    esconderFaixas();
    mostrarLogin();
  }

  /** Depois de qualquer login (loja, rede, e-mail, código ou senha nova): abre a rede ou a loja. */
  function aposLogin(dados, chaveDigitada) {
    if (dados.grupo) {
      entrarNaRede(dados);
      return;
    }
    estado.modo = "loja";
    esquecerRede();                                     // entrou direto numa loja: não há rede para voltar
    guardarSessao(dados, (dados.loja && dados.loja.chave) || chaveDigitada);
    estado.lojas = null;
    estado.dia = null;
    estado.paginaVendas = 1;
    mostrarApp();
    atualizarTudo();
  }

  /** Mostra só um dos cartões da tela de entrada. */
  function mostrarCartaoLogin(id) {
    ["form-login", "form-codigo", "form-esqueci", "form-definir", "form-senha-rede"].forEach((f) => {
      const el = $(f);
      if (el) el.hidden = f !== id;
    });
  }

  async function entrar(evento) {
    evento.preventDefault();
    const digitado = $("campo-loja").value.trim();
    const porEmail = digitado.includes("@");
    const loja = porEmail ? digitado.toLowerCase() : digitado.toUpperCase();
    const senha = $("campo-senha").value;
    const erro = $("erro-login");
    erro.hidden = true;

    if (!loja || !senha) {
      erro.textContent = "Informe o e-mail (ou o código da loja) e a senha.";
      erro.hidden = false;
      return;
    }

    const botao = $("botao-entrar");
    botao.disabled = true;
    botao.textContent = "Entrando…";
    try {
      if (porEmail) {
        const dados = await chamarApi("/login-email", { metodo: "POST", corpo: { email: loja, senha }, semToken: true });
        if (dados.precisa_codigo) {
          estado.desafio = dados.desafio;
          $("codigo-destino").textContent = "Mandamos um código de 6 dígitos para " + (dados.email || "o seu e-mail") +
            ". Confira também a caixa de spam.";
          $("campo-codigo").value = "";
          $("erro-codigo").hidden = true;
          mostrarCartaoLogin("form-codigo");
          setTimeout(() => $("campo-codigo").focus(), 50);
          return;
        }
        aposLogin(dados, "");
        return;
      }
      const dados = await chamarApi("/login", { metodo: "POST", corpo: { loja, senha }, semToken: true });
      aposLogin(dados, loja);
    } catch (e) {
      erro.textContent = e instanceof ErroRede ? "Sem conexão com o servidor. Verifique a internet." : e.message;
      erro.hidden = false;
    } finally {
      botao.disabled = false;
      botao.textContent = "Entrar";
    }
  }

  async function confirmarCodigo(evento) {
    evento.preventDefault();
    const erro = $("erro-codigo");
    erro.hidden = true;
    try {
      const dados = await chamarApi("/login-email/codigo", { metodo: "POST", semToken: true,
        corpo: { desafio: estado.desafio || "", codigo: $("campo-codigo").value } });
      estado.desafio = null;
      mostrarCartaoLogin("form-login");
      aposLogin(dados, "");
    } catch (e) {
      erro.textContent = e instanceof ErroRede ? "Sem conexão com o servidor." : e.message;
      erro.hidden = false;
    }
  }

  async function pedirNovaSenha(evento) {
    evento.preventDefault();
    const msg = $("msg-esqueci");
    const email = $("campo-esqueci").value.trim();
    if (!email.includes("@")) {
      msg.textContent = "Informe o e-mail do seu acesso.";
      msg.hidden = false;
      return;
    }
    try {
      const r = await chamarApi("/senha/esqueci", { metodo: "POST", corpo: { email }, semToken: true });
      msg.textContent = r.mensagem;
    } catch (e) {
      msg.textContent = e instanceof ErroRede ? "Sem conexão com o servidor." : e.message;
    }
    msg.hidden = false;
  }

  /** Link do e-mail (convite ou nova senha): /painel/?senha=TOKEN. */
  async function abrirLinkDeSenha(token) {
    $("tela-app").hidden = true;
    $("tela-login").hidden = false;
    mostrarCartaoLogin("form-definir");
    const erro = $("erro-definir");
    try {
      const info = await chamarApi("/senha/link?token=" + encodeURIComponent(token), { semToken: true });
      $("definir-email").textContent = (info.tipo === "convite" ? "Bem-vindo! " : "") + "Acesso: " + info.email;
    } catch (e) {
      erro.textContent = e instanceof ErroRede ? "Sem conexão com o servidor." : e.message;
      erro.hidden = false;
    }
    $("form-definir").addEventListener("submit", async (evento) => {
      evento.preventDefault();
      erro.hidden = true;
      const nova = $("campo-nova").value;
      if (nova !== $("campo-repetir").value) {
        erro.textContent = "As duas senhas não são iguais.";
        erro.hidden = false;
        return;
      }
      try {
        const dados = await chamarApi("/senha/definir", { metodo: "POST", corpo: { token, senha: nova }, semToken: true });
        try { history.replaceState(null, "", location.pathname); } catch (_) { /* segue */ }
        mostrarCartaoLogin("form-login");
        aposLogin(dados, "");
      } catch (e) {
        erro.textContent = e instanceof ErroRede ? "Sem conexão com o servidor." : e.message;
        erro.hidden = false;
      }
    });
  }

  // ------------------------------------------------------------------
  // Faixas de aviso
  // ------------------------------------------------------------------

  function esconderFaixas() {
    $("faixa-offline").hidden = true;
    $("faixa-atraso").hidden = true;
    $("faixa-erro").hidden = true;
  }

  function mostrarOffline(salvoEm) {
    const f = $("faixa-offline");
    f.textContent = "Sem conexão: mostrando dados de " + formatarHora(salvoEm) + ".";
    f.hidden = false;
  }

  function mostrarErro(mensagem) {
    const f = $("faixa-erro");
    f.textContent = mensagem;
    f.hidden = false;
  }

  function mostrarAtraso(atrasoMin) {
    const f = $("faixa-atraso");
    if (atrasoMin === null || atrasoMin === undefined) {
      f.textContent = "O PDV ainda não enviou dados. Os números não são ao vivo.";
      f.hidden = false;
    } else if (Number(atrasoMin) > LIMITE_ATRASO_MIN) {
      f.textContent = "PDV sem enviar dados há " + formatarAtraso(atrasoMin) + ". Os números não são ao vivo.";
      f.hidden = false;
    } else {
      f.hidden = true;
    }
  }

  // ------------------------------------------------------------------
  // Carregamento de dados
  // ------------------------------------------------------------------

  function parametroDia(primeiro = true) {
    return estado.dia ? (primeiro ? "?" : "&") + "dia=" + encodeURIComponent(estado.dia) : "";
  }

  // Executa uma chamada; em falta de rede cai para o cache local.
  async function carregarComCache(nomeCache, caminho) {
    try {
      const dados = await chamarApi(caminho);
      guardarCache(nomeCache, dados);
      return { dados, offline: false };
    } catch (erro) {
      if (erro instanceof ErroRede) {
        const cache = lerCache(nomeCache);
        if (cache) {
          mostrarOffline(cache.salvo_em);
          return { dados: cache.dados, offline: true };
        }
        mostrarErro("Sem conexão e sem dados guardados. Tente novamente quando a internet voltar.");
        return null;
      }
      if (erro.status !== 401) mostrarErro(erro.message);
      return null;
    }
  }

  async function carregarResumo() {
    const r = await carregarComCache("resumo:" + (estado.dia || "atual"), "/resumo" + parametroDia());
    if (!r) return;
    estado.resumo = r.dados;
    renderizarResumo(r.dados);
  }

  async function carregarHistorico() {
    const r = await carregarComCache("historico", "/historico?dias=30");
    if (!r) return;
    estado.historico = r.dados;
    renderizarHistorico(r.dados);
  }

  async function carregarRanking() {
    const r = await carregarComCache(
      "produtos:" + estado.periodoProdutos,
      "/produtos?periodo=" + encodeURIComponent(estado.periodoProdutos)
    );
    if (!r) return;
    estado.ranking = r.dados;
    renderizarRanking(r.dados);
  }

  function alertasVistos() {
    try { return JSON.parse(localStorage.getItem("pdv-alertas-vistos") || "[]"); }
    catch (_erro) { return []; }
  }

  function marcarAlertasVistos(ids) {
    const atual = alertasVistos();
    ids.forEach((id) => { if (id && atual.indexOf(id) < 0) atual.push(id); });
    localStorage.setItem("pdv-alertas-vistos", JSON.stringify(atual.slice(-200)));
  }

  function renderizarAlertas(alertas) {
    const lista = $("lista-alertas");
    const badge = $("badge-alertas");
    if (!lista || !badge) return;
    const vistos = alertasVistos();
    const grupos = (alertas || []).map((grupo) => {
      const itens = (grupo.itens || grupo.detalhes || []).filter((item) => vistos.indexOf(item.id) < 0);
      return Object.assign({}, grupo, { itens: itens, quantidade: itens.length });
    }).filter((grupo) => grupo.quantidade > 0);
    badge.textContent = String(grupos.length);
    limpar(lista);
    if (!grupos.length) {
      lista.append(el("li", { text: "Nenhum alerta neste recorte." }));
    }
    grupos.forEach((grupo) => {
      const item = el("li", {});
      const resumo = el("details", {});
      const titulo = el("summary", { text: (grupo.titulo || "Alerta") + " (" + grupo.quantidade + ")" });
      resumo.append(titulo);
      grupo.itens.forEach((detalhe) => {
        const valor = detalhe.valor_cent === null || detalhe.valor_cent === undefined
          ? "" : " · " + formatarCentavos(detalhe.valor_cent);
        resumo.append(el("p", { text: (detalhe.data || "") + valor + " — " + (detalhe.detalhe || "") }));
      });
      item.append(resumo);
      const botao = el("button", { type: "button", text: "mandar no WhatsApp" });
      botao.addEventListener("click", () => compartilharWhatsapp(grupo.texto || grupo.titulo));
      const visto = el("button", { type: "button", text: "marcar como visto" });
      visto.addEventListener("click", () => {
        marcarAlertasVistos(grupo.itens.map((d) => d.id));
        renderizarAlertas(alertas);
      });
      item.append(botao);
      item.append(visto);
      lista.append(item);
    });
    const perdas = (estado.resumo && estado.resumo.perdas) || [];
    if (perdas.length) {
      lista.append(el("li", { text: "Perdas na contagem" }));
      perdas.slice(0, 8).forEach((p) => {
        lista.append(el("li", { text: (p.nome || "Produto") + ": " + (p.unidades || 0) + " un · " + formatarCentavos(p.valor_cent || 0) }));
      });
    }
  }

  async function textoDoResumo() {
    const de = estado.aba === "periodo" && estado.periodoDe ? estado.periodoDe : (estado.dia || "");
    const ate = estado.aba === "periodo" && estado.periodoAte ? estado.periodoAte : de;
    if (!de) return null;
    const r = await chamarApi("/whatsapp?de=" + encodeURIComponent(de) + "&ate=" + encodeURIComponent(ate || de));
    return r;
  }

  async function compartilharWhatsapp(texto) {
    let corpo = texto;
    let links = [];
    if (!corpo) {
      const dados = await textoDoResumo();
      if (!dados) return;
      corpo = dados.texto;
      links = dados.links || [];
    }
    if (links.length) links.forEach((item) => window.open(item.url, "_blank", "noopener"));
    else if (corpo) {
      await navigator.clipboard.writeText(corpo).catch(() => {});
      window.open("https://wa.me/?text=" + encodeURIComponent(corpo), "_blank", "noopener");
    }
  }

  function renderizarMesAtual(r) {
    const mes = r.mes || {};
    $("mes-faturamento").textContent = formatarCentavos(mes.faturamento_cent);
    $("mes-periodo").textContent = mes.de && mes.ate
      ? formatarData(mes.de) + " a " + formatarData(mes.ate) : "";
    renderizarMeta(mes);
    const ant = mes.anterior || {};
    if (!ant.de) {
      $("mes-comparacao").textContent = "";
      return;
    }
    let texto = "Mesmo período do mês anterior (" + formatarData(ant.de) + " a " + formatarData(ant.ate) +
      "): " + formatarCentavos(ant.faturamento_cent) + " · diferença " + formatarCentavos(mes.variacao_cent);
    if (mes.parcial) texto += ". A nuvem guarda cerca de 120 dias; o mês anterior pode estar incompleto.";
    $("mes-comparacao").textContent = texto;
  }

  // ------------------------------------------------------------------
  // Minhas lojas: dono com várias lojas no mesmo painel
  // ------------------------------------------------------------------

  function avisar(id, texto, erro) {
    const aviso = $(id);
    aviso.textContent = texto || "";
    aviso.hidden = !texto;
    aviso.classList.toggle("erro", !!erro);
  }

  function situacaoDaLoja(loja) {
    if (!loja.atualizado_em) return "o caixa ainda não enviou dados";
    if (loja.atraso_min !== null && loja.atraso_min !== undefined && Number(loja.atraso_min) > LIMITE_ATRASO_MIN) {
      return "sem enviar há " + formatarAtraso(loja.atraso_min);
    }
    return loja.vendas_hoje + (loja.vendas_hoje === 1 ? " venda hoje" : " vendas hoje");
  }

  function linhaDaLoja(loja) {
    const corpo = el("button", { type: "button", class: "loja-botao", "aria-current": loja.atual ? "true" : null },
      el("span", { class: "loja-nome" }, el("strong", { text: loja.nome || loja.chave }),
        loja.atual ? el("span", { class: "etiqueta-nota lancada", text: "Vendo agora" }) : null),
      el("span", { class: "loja-numeros" },
        el("span", {}, el("span", { class: "sec", text: "Hoje " }), el("strong", { class: "valor", text: formatarCentavos(loja.hoje_cent) })),
        el("span", {}, el("span", { class: "sec", text: "Mês " }), el("strong", { class: "valor", text: formatarCentavos(loja.mes_cent) }))),
      el("span", { class: "sec", text: situacaoDaLoja(loja) }));
    if (!loja.atual) corpo.addEventListener("click", () => trocarLoja(loja, corpo));
    const item = el("li", { class: "loja" + (loja.atual ? " atual" : "") }, corpo);
    if (!loja.atual) {
      const remover = el("button", { type: "button", class: "botao-link perigo", text: "Remover" });
      remover.addEventListener("click", async () => {
        if (remover.dataset.confirma !== "1") {              // dois toques: o primeiro só pede a confirmação
          remover.dataset.confirma = "1";
          remover.textContent = "Remover do painel?";
          return;
        }
        remover.disabled = true;
        try {
          renderizarLojas(await chamarApi("/lojas/" + encodeURIComponent(loja.chave), { metodo: "DELETE" }));
          avisar("aviso-lojas", (loja.nome || loja.chave) + " saiu do seu painel. Os dados dela continuam na loja.");
        } catch (e) {
          avisar("aviso-lojas", e.message || "Não consegui remover a loja.", true);
          remover.disabled = false;
        }
      });
      item.append(remover);
    }
    return item;
  }

  function renderizarLojas(dados) {
    const lojas = (dados && dados.lojas) || [];
    estado.lojas = lojas;
    $("bloco-lojas").hidden = lojas.length < 2;
    const lista = $("lista-lojas");
    limpar(lista);
    lojas.forEach((loja) => lista.append(linhaDaLoja(loja)));
    const total = (dados && dados.total) || {};
    $("lojas-total").textContent = lojas.length + " lojas · hoje " + formatarCentavos(total.hoje_cent || 0) +
      " · mês " + formatarCentavos(total.mes_cent || 0);
  }

  async function carregarLojas() {
    if (!estado.token) return;
    try {
      renderizarLojas(await chamarApi("/lojas"));
    } catch (e) {
      if (e instanceof ErroApi && e.status === 404) {       // nuvem antiga: sem o recurso, nada aparece
        estado.lojas = [];
        $("bloco-lojas").hidden = true;
        $("adicionar-loja").hidden = true;
      }
    }
  }

  // Guarda a sessão recebida no login ou na troca de loja.
  function guardarSessao(dados, chavePadrao) {
    estado.token = SESSAO_COOKIE;
    estado.loja = dados.loja || { chave: chavePadrao, nome: chavePadrao };
    try { localStorage.removeItem(CHAVE_TOKEN); } catch (_) { /* o token fica no cookie */ }
    gravarArmazenamento(CHAVE_LOJA, JSON.stringify(estado.loja));
    gravarArmazenamento(CHAVE_LOJA + ".chave", estado.loja.chave || chavePadrao);
    if (dados.expira_em) gravarArmazenamento(CHAVE_EXPIRA, dados.expira_em);
  }

  async function trocarLoja(loja, botao) {
    if (botao) botao.disabled = true;
    try {
      const dados = await chamarApi("/lojas/trocar", { metodo: "POST", corpo: { loja: loja.chave } });
      // O que está guardado no aparelho é da loja anterior: sai tudo antes de entrar a sessão nova.
      apagarTudoLocal();
      Object.assign(estado, { resumo: null, historico: null, ranking: null, periodo: null, vendas: null, dia: null,
        paginaVendas: 1, lojas: null, mesAtual: null, carregando: false });
      guardarSessao(dados, loja.chave);
      mostrarApp();
      trocarAba("hoje");
      await atualizarTudo();
    } catch (e) {
      avisar("aviso-lojas", e.message || "Não consegui trocar de loja.", true);
      if (botao) botao.disabled = false;
    }
  }

  function configurarLojas() {
    $("form-adicionar-loja").addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const botao = $("botao-adicionar-loja");
      botao.disabled = true;
      avisar("aviso-adicionar-loja", "");
      try {
        const dados = await chamarApi("/lojas/vincular", { metodo: "POST",
          corpo: { loja: $("outra-loja").value.trim(), senha: $("outra-senha").value } });
        renderizarLojas(dados);
        $("outra-loja").value = "";
        $("outra-senha").value = "";
        $("adicionar-loja").open = false;
        avisar("aviso-lojas", "Loja adicionada. Toque nela para ver os números.");
        $("bloco-lojas").scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (e) {
        avisar("aviso-adicionar-loja", e instanceof ErroRede ? "Sem conexão com o servidor." : e.message, true);
      } finally {
        botao.disabled = false;
      }
    });
  }

  // ------------------------------------------------------------------
  // Notas de compra: o dono envia o XML e o caixa da loja busca e confere
  // ------------------------------------------------------------------

  const SITUACOES_NOTA = {
    pendente: "Aguardando o caixa buscar",
    baixada: "No caixa, aguardando conferência",
    lancada: "Lançada no estoque",
    recusada: "Recusada pelo caixa",
  };
  const LIMITE_NOTA_BYTES = 2 * 1024 * 1024;
  const MAXIMO_NOTAS_POR_VEZ = 10;

  function dataCurta(iso) {
    const t = String(iso || "");
    return t.length >= 16 ? t.slice(8, 10) + "/" + t.slice(5, 7) + " " + t.slice(11, 16) : "";
  }

  function avisarNotas(texto, erro) {
    const aviso = $("aviso-notas");
    aviso.textContent = texto || "";
    aviso.hidden = !texto;
    aviso.classList.toggle("erro", !!erro);
  }

  function linhaDaNota(nota) {
    const detalhes = ["NF " + (nota.numero || "s/n")];
    if (nota.itens) detalhes.push(nota.itens + (nota.itens === 1 ? " item" : " itens"));
    if (nota.valor_cent) detalhes.push(formatarCentavos(nota.valor_cent));
    if (nota.enviada_em) detalhes.push("enviada " + dataCurta(nota.enviada_em));
    let situacao = SITUACOES_NOTA[nota.situacao] || nota.situacao;
    if (nota.situacao === "recusada" && nota.detalhe) situacao += ": " + nota.detalhe;
    const item = el("li", { class: "nota" },
      el("div", { class: "nota-texto" },
        el("strong", { text: nota.emitente || "Fornecedor não informado" }),
        el("span", { class: "sec", text: detalhes.join(" · ") }),
        el("span", { class: "etiqueta-nota " + nota.situacao, text: situacao })));
    if (nota.situacao === "pendente" || nota.situacao === "recusada") {
      const excluir = el("button", { type: "button", class: "botao-link perigo", text: "Excluir" });
      excluir.addEventListener("click", async () => {
        excluir.disabled = true;
        try {
          await chamarApi("/notas/" + nota.id, { metodo: "DELETE" });
          avisarNotas("Nota excluída.");
        } catch (e) {
          avisarNotas(e.message || "Não consegui excluir a nota.", true);
        }
        carregarNotas();
      });
      item.append(excluir);
    }
    return item;
  }

  const NOMES_MES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
    "outubro", "novembro", "dezembro"];

  async function carregarXmls() {
    if (!estado.token) return;
    let dados;
    try {
      dados = await chamarApi("/nfce/meses");
    } catch (e) {
      $("bloco-xmls").hidden = true;                      // nuvem antiga ou sem NFC-e própria
      return;
    }
    const meses = Array.isArray(dados && dados.meses) ? dados.meses : [];
    $("bloco-xmls").hidden = meses.length === 0;
    const sel = $("mes-xmls");
    limpar(sel);
    for (const m of meses) {
      const [ano, mes] = String(m.mes).split("-");
      const op = document.createElement("option");
      op.value = m.mes;
      op.textContent = NOMES_MES[Number(mes) - 1] + " de " + ano + " · " + m.nfe + " nota(s)" +
        (m.cancelamento ? ", " + m.cancelamento + " cancelada(s)" : "") +
        (m.inutilizacao ? ", " + m.inutilizacao + " inutilização(ões)" : "");
      sel.append(op);
    }
  }

  async function baixarXmls() {
    const mes = $("mes-xmls").value;
    if (!mes || !estado.token) return;
    const aviso = $("aviso-xmls");
    aviso.hidden = false;
    aviso.textContent = "Preparando o arquivo…";
    try {
      const r = await fetch(API_BASE + "/nfce/xmls?mes=" + encodeURIComponent(mes), {
        headers: { "X-PDV-Painel": "1" }, cache: "no-store", credentials: "same-origin" });
      if (!r.ok) throw new Error(r.status === 404 ? "Nenhum XML neste mês." : "Não consegui baixar (HTTP " + r.status + ").");
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = "nfce-" + mes + ".zip";
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      aviso.textContent = "Arquivo baixado. Mande o ZIP ao contador.";
    } catch (e) {
      aviso.textContent = e.message || "Não consegui baixar.";
    }
  }

  async function carregarNotas() {
    if (!estado.token) return;
    let dados;
    try {
      dados = await chamarApi("/notas");
    } catch (e) {
      if (e instanceof ErroApi && e.status === 404) {       // nuvem antiga: sem o recurso, o bloco some
        $("bloco-notas").hidden = true;
        return;
      }
      avisarNotas(e.message || "Não consegui carregar as notas.", true);
      return;
    }
    const notas = (dados && dados.notas) || [];
    const lista = $("lista-notas");
    limpar(lista);
    notas.forEach((nota) => lista.append(linhaDaNota(nota)));
    $("vazio-notas").hidden = notas.length > 0;
  }

  function paraBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binario = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      binario += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(binario);
  }

  async function enviarNotas(arquivos) {
    const rotulo = $("rotulo-arquivo-nota");
    const lista = Array.from(arquivos || []).slice(0, MAXIMO_NOTAS_POR_VEZ);
    if (!lista.length) return;
    rotulo.classList.add("ocupado");
    let enviadas = 0;
    const falhas = [];
    for (const arquivo of lista) {
      avisarNotas("Enviando " + arquivo.name + "…");
      try {
        if (arquivo.size > LIMITE_NOTA_BYTES) throw new Error("passa de 2 MB");
        const conteudo = paraBase64(await arquivo.arrayBuffer());
        await chamarApi("/notas", { metodo: "POST", corpo: { nome: arquivo.name, conteudo_b64: conteudo } });
        enviadas += 1;
      } catch (e) {
        falhas.push(arquivo.name + ": " + (e.message || "falhou"));
      }
    }
    rotulo.classList.remove("ocupado");
    const partes = [];
    if (enviadas) partes.push(enviadas + (enviadas === 1 ? " nota enviada. O caixa recebe" : " notas enviadas. O caixa recebe") + " na próxima sincronização.");
    if (falhas.length) partes.push("Não enviei: " + falhas.join("; "));
    if (arquivos.length > lista.length) partes.push("Envie no máximo " + MAXIMO_NOTAS_POR_VEZ + " arquivos por vez.");
    avisarNotas(partes.join(" "), falhas.length > 0);
    carregarNotas();
  }

  // ------------------------------------------------------------------
  // Vendas de teste: o dono marca, confirma com a senha de segurança e o caixa apaga
  // ------------------------------------------------------------------

  const SITUACAO_TESTE = { aguardando: "aguardando o caixa", apagada: "apagada", recusada: "o caixa não deixou" };
  let vendasTeste = [];

  function avisarTeste(texto, erro) {
    const aviso = $("aviso-teste");
    aviso.hidden = !texto;
    aviso.textContent = texto || "";
    aviso.classList.toggle("erro", !!erro);
  }

  function totalTeste() {
    const marcadas = vendasTeste.filter((v) => v.marcada);
    const total = marcadas.filter((v) => v.status === "fechada").reduce((s, v) => s + v.total_cent, 0);
    $("teste-total").textContent = marcadas.length
      ? marcadas.length + " venda(s) marcada(s), total " + formatarCentavos(total) : "";
    return { marcadas, total };
  }

  async function carregarVendasTeste() {
    if (!estado.token) return;
    const d = new Date();                                 // dia local (toISOString seria o dia em UTC)
    const hoje = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
    if (!$("teste-de").value) $("teste-de").value = hoje;
    if (!$("teste-ate").value) $("teste-ate").value = hoje;
    let dados;
    try {
      dados = await chamarApi("/vendas-teste?inicio=" + encodeURIComponent($("teste-de").value) +
        "&fim=" + encodeURIComponent($("teste-ate").value));
    } catch (e) {
      if (e instanceof ErroApi && e.status === 404) { $("bloco-vendas-teste").hidden = true; return; }
      avisarTeste(e.message || "Não consegui carregar as vendas.", true);
      return;
    }
    $("bloco-vendas-teste").hidden = false;
    vendasTeste = (dados.vendas || []).map((v) => Object.assign({ marcada: false }, v));
    const lista = $("teste-lista");
    limpar(lista);
    if (!vendasTeste.length) lista.append(el("p", { class: "legenda", text: "Nenhuma venda nesse período." }));
    for (const v of vendasTeste) {
      const caixa = el("input", { type: "checkbox", disabled: !!v.pedido });
      caixa.addEventListener("change", () => { v.marcada = caixa.checked; totalTeste(); });
      const quando = v.fechada_em ? String(v.fechada_em).slice(8, 10) + "/" + String(v.fechada_em).slice(5, 7) +
        " " + String(v.fechada_em).slice(11, 16) : v.dia;
      const situacao = v.pedido ? " · " + (SITUACAO_TESTE[v.pedido] || v.pedido) + (v.motivo ? ": " + v.motivo : "")
        : (v.status === "cancelada" ? " · cancelada" : "");
      lista.append(el("label", { class: "linha-teste", style: "display:block;margin:4px 0" }, caixa,
        " Cupom " + (v.cupom || "-") + " · " + quando + " · " + formatarCentavos(v.total_cent) + situacao));
    }
    const hist = dados.historico || [];
    $("teste-historico-bloco").hidden = hist.length === 0;
    const caixaHist = $("teste-historico");
    limpar(caixaHist);
    for (const h of hist) {
      caixaHist.append(el("p", { class: "legenda" }, "Cupom " + (h.cupom || "-") + " · " + formatarCentavos(h.total_cent) +
        " · " + (SITUACAO_TESTE[h.situacao] || h.situacao) + (h.motivo ? ": " + h.motivo : "") +
        " · pelo " + (h.origem === "painel" ? "painel" : "caixa") + " em " + String(h.pedida_em || "").slice(0, 16)));
    }
    $("teste-apagar").disabled = !dados.senha_configurada;
    if (!dados.senha_configurada) avisarTeste("Crie a senha de segurança no caixa (Utilitários) para apagar por aqui.", false);
    totalTeste();
  }

  async function apagarVendasTeste() {
    const { marcadas, total } = totalTeste();
    if (!marcadas.length) { avisarTeste("Marque as vendas de teste.", true); return; }
    const senha = $("teste-senha").value;
    if (!senha) { avisarTeste("Digite a senha de segurança.", true); return; }
    if (!confirm("Apagar " + marcadas.length + " venda(s), total " + formatarCentavos(total) + "? Não dá para desfazer.")) return;
    try {
      const r = await chamarApi("/vendas-teste/apagar", { metodo: "POST",
        corpo: { uuids: marcadas.map((v) => v.uuid), senha } });
      avisarTeste(r.pedidas + " venda(s) enviada(s) ao caixa para apagar. " + (r.aviso || ""), false);
    } catch (e) {
      avisarTeste(e.message || "Não consegui apagar.", true);
    } finally {
      $("teste-senha").value = "";
    }
    carregarVendasTeste();
  }

  function configurarNotas() {
    const campo = $("arquivo-nota");
    campo.addEventListener("change", () => {
      const arquivos = campo.files;
      enviarNotas(arquivos).finally(() => { campo.value = ""; });
    });
    $("baixar-xmls").addEventListener("click", baixarXmls);
    $("teste-buscar").addEventListener("click", carregarVendasTeste);
    $("teste-apagar").addEventListener("click", apagarVendasTeste);
  }

  // ------------------------------------------------------------------
  // Meta do mês e ocultar valores (preferências deste aparelho)
  // ------------------------------------------------------------------

  function chaveMeta() {
    return "pdv-meta-" + ((estado.loja && estado.loja.chave) || "loja");
  }

  function metaDoMes() {
    const valor = Number(lerArmazenamento(chaveMeta()) || 0);
    return Number.isFinite(valor) && valor > 0 ? Math.round(valor) : 0;
  }

  // "50.000,00", "50000" e "50000.5" viram centavos; texto sem número vale zero (apaga a meta).
  function lerValorEmCentavos(texto) {
    let limpo = String(texto || "").replace(/[^0-9.,]/g, "");
    // Com vírgula, ou só com pontos de milhar ("50.000"), o ponto não é decimal.
    if (limpo.indexOf(",") >= 0 || /^\d{1,3}(\.\d{3})+$/.test(limpo)) limpo = limpo.replace(/\./g, "").replace(",", ".");
    const reais = Number(limpo);
    return Number.isFinite(reais) && reais > 0 ? Math.round(reais * 100) : 0;
  }

  function renderizarMeta(mes) {
    estado.mesAtual = mes || estado.mesAtual || {};
    const dados = estado.mesAtual;
    const meta = metaDoMes();
    const feito = dados.faturamento_cent || 0;
    const medidor = $("meta-medidor");
    $("botao-meta").textContent = meta ? "Alterar meta" : "Definir meta";
    medidor.hidden = !meta;
    // Projeção: média por dia até aqui, aplicada aos dias do mês.
    let projecao = 0;
    const ate = dados.ate ? String(dados.ate).split("-").map(Number) : null;
    if (ate && ate.length === 3 && ate[2] > 0) {
      const diasNoMes = new Date(ate[0], ate[1], 0).getDate();
      projecao = Math.round(feito / ate[2] * diasNoMes);
      $("meta-projecao").textContent = "No ritmo atual o mês fecha em " + formatarCentavos(projecao) +
        (meta ? (projecao >= meta ? ", acima da meta." : ", " + formatarCentavos(meta - projecao) + " abaixo da meta.") : ".") +
        (meta && feito < meta && diasNoMes > ate[2]
          ? " Para bater, faltam " + formatarCentavos(Math.ceil((meta - feito) / (diasNoMes - ate[2]))) + " por dia."
          : "");
    } else {
      $("meta-projecao").textContent = "";
    }
    if (!meta) {
      $("meta-texto").textContent = "Defina uma meta para acompanhar o mês.";
      return;
    }
    const pct = Math.min(100, Math.round(feito * 100 / meta));
    $("meta-barra").style.width = pct + "%";
    medidor.classList.toggle("batida", feito >= meta);
    $("meta-texto").textContent = feito >= meta
      ? "Meta de " + formatarCentavos(meta) + " batida!"
      : pct + "% da meta de " + formatarCentavos(meta);
  }

  function configurarMeta() {
    const form = $("meta-form");
    $("botao-meta").addEventListener("click", () => {
      form.hidden = !form.hidden;
      if (!form.hidden) {
        const meta = metaDoMes();
        $("meta-valor").value = meta ? String(meta / 100).replace(".", ",") : "";
        $("meta-valor").focus();
      }
    });
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      gravarArmazenamento(chaveMeta(), String(lerValorEmCentavos($("meta-valor").value)));
      form.hidden = true;
      renderizarMeta(null);
    });
  }

  function configurarOcultarValores() {
    const botao = $("botao-ocultar");
    const aplicar = (oculto) => {
      document.body.classList.toggle("valores-ocultos", oculto);
      botao.setAttribute("aria-pressed", oculto ? "true" : "false");
      botao.title = oculto ? "Mostrar valores" : "Ocultar valores";
      botao.setAttribute("aria-label", botao.title);
    };
    aplicar(lerArmazenamento("pdv-ocultar-valores") === "1");
    botao.addEventListener("click", () => {
      const oculto = !document.body.classList.contains("valores-ocultos");
      gravarArmazenamento("pdv-ocultar-valores", oculto ? "1" : "0");
      aplicar(oculto);
    });
  }

  async function carregarPeriodo() {
    sincronizarDatasDoAtalho();
    if (!estado.periodoDe || !estado.periodoAte) return;
    const r = await carregarComCache(
      "periodo:" + estado.periodoDe + ":" + estado.periodoAte,
      "/periodo?de=" + encodeURIComponent(estado.periodoDe) + "&ate=" + encodeURIComponent(estado.periodoAte)
    );
    if (!r) return;
    estado.periodo = r.dados;
    renderizarPeriodo(r.dados);
  }

  function datasDoLucro(ateIso, atalho) {
    if (atalho === "semana") {
      const partes = String(ateIso).split("-").map(Number);
      const dt = new Date(partes[0], partes[1] - 1, partes[2]);
      const volta = dt.getDay() === 0 ? 6 : dt.getDay() - 1;
      return [somarDiasIso(ateIso, -volta), ateIso];
    }
    if (atalho === "mes") return [String(ateIso).slice(0, 7) + "-01", ateIso];
    return [ateIso, ateIso];
  }

  function sincronizarDatasDoLucro() {
    if (estado.atalhoLucro) {
      const base = (estado.resumo && (estado.resumo.dia_operacional || estado.resumo.dia))
        || agoraLocalIso().slice(0, 10);
      const faixa = datasDoLucro(base, estado.atalhoLucro);
      estado.lucroDe = faixa[0];
      estado.lucroAte = faixa[1];
    }
    if ($("lucro-de")) $("lucro-de").value = estado.lucroDe || "";
    if ($("lucro-ate")) $("lucro-ate").value = estado.lucroAte || "";
  }

  function dinheiroOuTraco(valor, ok) {
    if (!ok || valor === null || valor === undefined) return "—";
    return formatarCentavos(valor);
  }

  /** Relatório diário por e-mail (aba Relatórios): mostra o que está salvo e o último envio. */
  async function carregarRelatorioDiario() {
    const status = $("relatorio-status");
    try {
      const c = await chamarApi("/relatorio-diario");
      $("relatorio-emails").value = (c.emails || []).join(", ");
      $("relatorio-ativo").checked = !!c.ativo;
      const partes = [];
      if (!c.email_configurado) partes.push("O envio de e-mail ainda não está configurado no servidor: fale com o suporte.");
      if (c.ultimo_status) partes.push("Último envio: " + c.ultimo_status);
      else if (c.ativo) partes.push("Ligado. O primeiro chega amanhã às " + (c.hora || "08:00") + ".");
      status.textContent = partes.join(" ");
    } catch (e) {
      if (e.status !== 401) status.textContent = e.message || "Não consegui carregar o relatório diário.";
    }
  }

  async function salvarRelatorioDiario(evento) {
    evento.preventDefault();
    const status = $("relatorio-status");
    const botao = $("relatorio-salvar");
    botao.disabled = true;
    try {
      const c = await chamarApi("/relatorio-diario", { metodo: "POST", corpo: {
        emails: $("relatorio-emails").value, ativo: $("relatorio-ativo").checked } });
      status.textContent = c.ativo ? "Salvo. O relatório chega todo dia às " + (c.hora || "08:00") + "."
        : "Salvo. O relatório está desligado.";
    } catch (e) {
      if (e.status !== 401) status.textContent = e.message || "Não consegui salvar.";
    } finally {
      botao.disabled = false;
    }
  }

  async function enviarRelatorioAgora() {
    const status = $("relatorio-status");
    const botao = $("relatorio-agora");
    botao.disabled = true;
    status.textContent = "Enviando…";
    try {
      const r = await chamarApi("/relatorio-diario/enviar-agora", { metodo: "POST", corpo: {} });
      status.textContent = r.mensagem || "Enviado.";
    } catch (e) {
      if (e.status !== 401) status.textContent = e.message || "Não consegui enviar.";
    } finally {
      botao.disabled = false;
    }
  }

  async function carregarLucro() {
    sincronizarDatasDoLucro();
    if (!estado.lucroDe || !estado.lucroAte) return;
    const r = await carregarComCache(
      "lucro:" + estado.lucroDe + ":" + estado.lucroAte,
      "/lucro?de=" + encodeURIComponent(estado.lucroDe) + "&ate=" + encodeURIComponent(estado.lucroAte)
    );
    if (!r) return;
    renderizarLucro(r.dados);
    try {
      await carregarGestao();
    } catch (e) {
      if (e.status === 401) throw e;
      const nota = $("nota-gestao");
      if (nota) {
        nota.hidden = false;
        nota.textContent = e.message || "Não consegui carregar o restante dos relatórios.";
      }
    }
  }

  function renderizarLucro(d) {
    $("lucro-faturamento").textContent = formatarCentavos(d.faturamento_cent);
    $("lucro-desconto").textContent = formatarCentavos(d.desconto_cent);
    $("lucro-custo").textContent = dinheiroOuTraco(d.custo_cent, d.cmv_sincronizado);
    $("lucro-valor").textContent = dinheiroOuTraco(d.lucro_cent, d.cmv_sincronizado);
    $("lucro-margem").textContent = d.cmv_sincronizado
      ? "Margem " + (d.margem || "—")
      : "O caixa ainda não enviou o custo.";
    const nota = $("nota-lucro");
    nota.hidden = !d.parcial;
    nota.textContent = d.parcial
      ? "A nuvem guarda cerca de 120 dias. O começo deste intervalo pode estar incompleto." : "";
    const lista = $("lista-lucro-produtos");
    limpar(lista);
    const ranking = Array.isArray(d.ranking) ? d.ranking : [];
    $("vazio-lucro-produtos").hidden = ranking.length > 0;
    ranking.forEach((p) => {
      const valor = d.cmv_sincronizado
        ? formatarCentavos(p.lucro_cent) + " · " + (p.margem || "")
        : formatarCentavos(p.venda_cent);
      lista.append(el("li", null, el("span", { text: p.nome }), el("span", { class: "total", text: valor })));
    });
    const alertas = $("lista-lucro-alertas");
    limpar(alertas);
    const avisos = Array.isArray(d.alertas) ? d.alertas : [];
    $("vazio-lucro-alertas").hidden = avisos.length > 0;
    avisos.forEach((a) => {
      alertas.append(el("li", { text: a.nome + " · " + a.situacao + " · venda " + formatarCentavos(a.venda_cent)
        + " · custo " + formatarCentavos(a.custo_cent) }));
    });
    $("lucro-estoque-custo").textContent = dinheiroOuTraco(d.estoque_custo_cent, d.estoque_sincronizado);
    $("lucro-estoque-venda").textContent = dinheiroOuTraco(d.estoque_venda_cent, d.estoque_sincronizado);
    const notas = $("lista-lucro-notas");
    limpar(notas);
    const listaNotas = Array.isArray(d.notas) ? d.notas : [];
    $("vazio-lucro-notas").hidden = listaNotas.length > 0;
    listaNotas.forEach((n) => {
      notas.append(el("li", { text: (n.data ? formatarData(n.data) + " · " : "") + (n.fornecedor || "Fornecedor")
        + " · NF " + (n.numero || "—") + " · custo " + formatarCentavos(n.custo_cent)
        + " · previsto " + formatarCentavos(n.previsto_cent) + " · realizado " + formatarCentavos(n.realizado_cent) }));
    });
    const formas = $("lista-lucro-formas");
    limpar(formas);
    const listaFormas = Array.isArray(d.formas) ? d.formas : [];
    $("vazio-lucro-formas").hidden = listaFormas.length > 0;
    listaFormas.forEach((f) => {
      formas.append(el("li", null, el("span", { text: f.tipo }), el("span", { class: "total", text: formatarCentavos(f.lucro_cent) })));
    });
  }

  function preencherGestao(idLista, idVazio, itens, montar) {
    const lista = $(idLista);
    const vazio = $(idVazio);
    if (!lista) return;
    limpar(lista);
    const linhas = Array.isArray(itens) ? itens : [];
    if (vazio) vazio.hidden = linhas.length > 0;
    linhas.forEach((item) => lista.append(montar(item)));
  }

  function linhaNomeValor(nome, secundario, valor) {
    return el("li", null,
      el("div", { class: "nome" }, el("strong", { text: nome || "—" }), secundario ? el("span", { class: "sec", text: secundario }) : null),
      el("span", { class: "valor", text: valor }));
  }

  function textoLucro(item) {
    if (item.lucro_cent === null || item.lucro_cent === undefined) return "";
    return " · lucro " + formatarCentavos(item.lucro_cent) + (item.margem ? " (" + item.margem + ")" : "");
  }

  async function carregarGestao() {
    const nota = $("nota-gestao");
    if (nota) { nota.hidden = true; nota.textContent = ""; }
    const q = "de=" + encodeURIComponent(estado.lucroDe) + "&ate=" + encodeURIComponent(estado.lucroAte);
    const dados = await chamarApi("/gestao/painel?" + q);
    const abc = dados.abc || {};
    const notaAbc = $("nota-abc");
    if (notaAbc) notaAbc.textContent = abc.nota || "";
    preencherGestao("lista-gestao-abc", "vazio-gestao-abc", (abc.linhas || []).slice(0, 20), (p) => linhaNomeValor(
      p.nome,
      "Classe " + p.classe + (p.grupo ? " · " + p.grupo : "") + " · " + formatarQuantidade(p.quantidade),
      formatarCentavos(p.valor_cent) + textoLucro(p)));
    preencherGestao("lista-gestao-categorias", "vazio-gestao-categorias", (dados.categorias || {}).linhas, (c) => linhaNomeValor(
      c.categoria, formatarQuantidade(c.quantidade), formatarCentavos(c.valor_cent) + textoLucro(c)));
    preencherGestao("lista-gestao-operadores", "vazio-gestao-operadores", (dados.operadores || {}).linhas, (o) => linhaNomeValor(
      o.operador,
      o.vendas + (o.vendas === 1 ? " venda" : " vendas") + " · ticket " + formatarCentavos(o.ticket_medio_cent),
      formatarCentavos(o.faturamento_cent)));
    preencherGestao("lista-gestao-dias", "vazio-gestao-dias", (dados.vendas || {}).por_dia, (d) => linhaNomeValor(
      formatarData(d.dia), d.vendas + (d.vendas === 1 ? " venda" : " vendas"), formatarCentavos(d.faturamento_cent)));
    const est = dados.estoque || {};
    const notaEst = $("nota-estoque-gestao");
    if (notaEst) notaEst.textContent = est.nota || "";
    preencherGestao("lista-gestao-baixo", "vazio-gestao-baixo", est.baixo, (p) => linhaNomeValor(
      p.nome, (p.grupo ? p.grupo + " · " : "") + "mínimo " + formatarQuantidade(p.estoque_minimo),
      formatarQuantidade(p.qt_atual)));
    preencherGestao("lista-gestao-parados", "vazio-gestao-parados", est.parados, (p) => linhaNomeValor(
      p.nome, formatarQuantidade(p.qt_atual) + " parados", formatarCentavos(p.valor_parado_cent)));
    preencherGestao("lista-gestao-sugestao", "vazio-gestao-sugestao", est.sugestao, (p) => linhaNomeValor(
      p.nome,
      "estoque " + formatarQuantidade(p.qt_atual) + " · vendeu " + formatarQuantidade(p.vendido),
      "comprar " + formatarQuantidade(p.comprar)));
    const situacao = { pendente: "Aguardando o caixa", aplicado: "Aplicada", recusado: "Recusada pelo caixa" };
    preencherGestao("lista-gestao-auditoria", "vazio-gestao-auditoria", dados.auditoria, (c) => linhaNomeValor(
      c.resumo || c.tipo, (c.autor || "dono") + " · " + (c.criado_em || ""), situacao[c.situacao] || c.situacao || ""));
  }

  async function baixarRelatorio(formato, tipo, de, ate) {
    const url = API_BASE + "/gestao/relatorio?tipo=" + encodeURIComponent(tipo)
      + "&de=" + encodeURIComponent(de) + "&ate=" + encodeURIComponent(ate) + "&formato=" + formato;
    const resposta = await fetch(url, {
      headers: { "X-PDV-Painel": "1" }, cache: "no-store", credentials: "same-origin",
    });
    if (resposta.status === 401) {
      encerrarSessao(false);
      throw new ErroApi(401, "Sessão expirada. Entre novamente.");
    }
    if (!resposta.ok) {
      let detalhe = "Não consegui baixar o relatório.";
      try { const dados = await resposta.json(); if (dados && dados.detail) detalhe = String(dados.detail); } catch (_) { /* arquivo */ }
      throw new ErroApi(resposta.status, detalhe);
    }
    const blob = await resposta.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "relatorio-" + tipo + "." + formato;
    document.body.append(link);
    link.click();
    link.remove();
  }

  function renderizarPeriodo(d) {
    $("per-faturamento").textContent = formatarCentavos(d.faturamento_cent);
    $("per-quantidade").textContent = formatarInteiro(d.quantidade);
    $("per-ticket").textContent = formatarCentavos(d.ticket_medio_cent);
    $("per-servico").textContent = d.servico_sincronizado ? formatarCentavos(d.servico_cent) : "—";
    const nota = $("nota-periodo");
    const avisos = [];
    if (!d.servico_sincronizado && d.quantidade) avisos.push("A taxa de serviço separada pede o PDV atualizado.");
    if (d.parcial) avisos.push("A nuvem guarda cerca de 120 dias. O começo deste intervalo pode estar incompleto.");
    nota.hidden = avisos.length === 0;
    nota.textContent = avisos.join(" ");
    const dias = Array.isArray(d.dias) ? d.dias : [];
    const pontos = dias.map((dia, i) => {
      const valor = Number(dia.faturamento_cent) || 0;
      const mostrar = dias.length <= 16 || i === 0 || i === dias.length - 1 || (dia.dia && Number(dia.dia.slice(8, 10)) % 5 === 0);
      return {
        valor,
        rotulo: mostrar && dia.dia ? dia.dia.slice(8, 10) : "",
        titulo: formatarDiaCurto(dia.dia) + ": " + formatarCentavos(valor) + " em " + formatarInteiro(dia.quantidade) + " venda(s)",
      };
    });
    const tem = desenharGrafico($("grafico-periodo"), pontos, "Faturamento por dia no período", "detalhe-periodo");
    $("grafico-periodo").hidden = !tem;
    $("vazio-periodo").hidden = !!tem;
    if (!tem) $("detalhe-periodo").textContent = "";
    const formas = $("lista-formas-periodo");
    limpar(formas);
    const lista = Array.isArray(d.formas) ? d.formas.filter((f) => f && (Number(f.valor_cent) || 0) !== 0) : [];
    $("vazio-formas-periodo").hidden = lista.length > 0;
    const total = lista.reduce((s, f) => s + (Number(f.valor_cent) || 0), 0) || 1;
    for (const f of lista) {
      const pct = Math.round(((Number(f.valor_cent) || 0) / total) * 100);
      formas.append(el("li", null,
        el("span", { class: "nome", text: f.tipo || "—" }),
        el("span", { class: "valor" }, formatarCentavos(f.valor_cent), el("span", { class: "sec", text: " " + pct + "%" }))
      ));
    }
    const corpo = $("corpo-meses-periodo");
    limpar(corpo);
    const meses = Array.isArray(d.meses) ? d.meses : [];
    $("vazio-meses-periodo").hidden = meses.length > 0;
    for (const m of meses) {
      const linha = document.createElement("tr");
      for (const texto of [rotuloMes(m.mes) + "/" + String(m.mes || "").slice(0, 4), formatarInteiro(m.quantidade),
        formatarCentavos(m.servico_cent), formatarCentavos(m.faturamento_cent)]) {
        const celula = document.createElement("td");
        celula.textContent = texto;
        linha.append(celula);
      }
      corpo.append(linha);
    }
  }

  async function carregarVendas() {
    const pagina = estado.paginaVendas || 1;
    const r = await carregarComCache(
      "vendas:" + (estado.dia || "atual") + ":" + pagina,
      "/vendas?pagina=" + pagina + parametroDia(false)
    );
    if (!r) return;
    estado.vendas = r.dados;
    renderizarVendas(r.dados);
  }

  function textoUltimaAtualizacao() {
    const r = estado.resumo;
    if (r && r.atualizado_em) return "última atualização " + formatarHora(r.atualizado_em);
    return "última atualização —";
  }

  async function atualizarAgora() {
    if (!estado.token || estado.aguardandoFlush) return;
    estado.aguardandoFlush = true;
    const status = $("status-atualizacao");
    limpar(status);
    status.append("atualizando...");
    let pedido = {};
    try {
      const r = await fetch("/v1/sync/pedido", {
        method: "POST",
        headers: { Accept: "application/json", "X-PDV-Painel": "1" },
        credentials: "same-origin",
        cache: "no-store"
      });
      pedido = await r.json().catch(() => ({}));
    } catch (_erro) {
      pedido = {};
    }
    if (!pedido.conhecido) {
      estado.aguardandoFlush = false;
      limpar(status);
      status.append(textoUltimaAtualizacao());
      return;
    }
    const inicio = Date.now();
    while (Date.now() - inicio < ESPERA_FLUSH_MS) {
      await new Promise((resolver) => setTimeout(resolver, 2000));
      try {
        const e = await fetch("/v1/sync/estado", {
          headers: { Accept: "application/json", "X-PDV-Painel": "1" },
          credentials: "same-origin",
          cache: "no-store"
        });
        const j = await e.json().catch(() => ({}));
        if (j && j.id && j.id === pedido.id && j.momento) {
          estado.aguardandoFlush = false;
          await atualizarTudo();
          return;
        }
      } catch (_erro) { /* a próxima tentativa ainda é só memória */ }
    }
    estado.aguardandoFlush = false;
    limpar(status);
    status.append(textoUltimaAtualizacao());
  }

  function entrarNaRede(dados) {
    estado.modo = "rede";
    estado.token = SESSAO_COOKIE;
    estado.grupo = dados.grupo;
    estado.loja = null;
    apagarTudoLocal();                                   // nada de uma loja aberta antes neste aparelho
    if (dados.expira_em) gravarArmazenamento(CHAVE_EXPIRA, dados.expira_em);
    guardarRede(dados.grupo, dados.expira_em);
    if (dados.deve_trocar_senha) {
      $("tela-login").hidden = false;
      $("form-login").hidden = true;
      $("form-senha-rede").hidden = false;
      $("tela-app").hidden = true;
      $("tela-rede").hidden = true;
      return;
    }
    abrirInicioDaRede();
  }

  /** Painel único do dono de rede: entra direto na última loja vista (ou na primeira ativa). Só cai no resumo da rede
   *  se foi lá que ele parou, se nenhuma loja estiver ativa ou se a loja não abrir. */
  async function abrirInicioDaRede() {
    const ativas = lojasDaRede();
    const ultima = lerArmazenamento(REDE_ULTIMA);
    if (ultima === "resumo" || !ativas.length) { mostrarRede(); return; }
    const alvo = ativas.some((l) => l.chave === ultima) ? ultima : ativas[0].chave;
    try { await abrirLojaDaRede(alvo); }
    catch (e) { if (e.status !== 401) mostrarRede(); }
  }

  function lojasDaRede() {
    const grupo = estado.grupo || (redeGuardada() || {}).grupo;
    return ((grupo && grupo.lojas) || []).filter((l) => l.ativa !== false);
  }

  /** Preenche os seletores de loja (no topo da loja e no resumo) com as lojas da rede. */
  function montarSeletoresDaRede(atual) {
    const lojas = lojasDaRede();
    [["seletor-loja-rede", true], ["seletor-loja-resumo", false]].forEach(([id, comResumo]) => {
      const seletor = $(id);
      if (!seletor) return;
      limpar(seletor);
      if (comResumo) seletor.append(el("option", { value: RESUMO_DA_REDE, text: "Todas as lojas (resumo da rede)" }));
      else seletor.append(el("option", { value: RESUMO_DA_REDE, text: "Escolha a loja…" }));
      lojas.forEach((l) => seletor.append(el("option", { value: l.chave, text: l.nome || l.chave })));
      seletor.value = comResumo ? (atual || RESUMO_DA_REDE) : RESUMO_DA_REDE;
      const pai = seletor.closest(".seletor-no-resumo");
      if (pai) pai.hidden = !lojas.length;
    });
  }

  async function trocarDeLojaNaRede(chave) {
    if (chave === RESUMO_DA_REDE) { await voltarParaRede(); return; }
    if (estado.modo === "loja" && estado.loja && estado.loja.chave === chave) return;
    try {
      // De uma loja para outra: a nuvem só abre loja pela sessão da rede, então ela volta a valer primeiro.
      if (estado.modo === "loja") await chamarApi("/grupo/voltar", { metodo: "POST", corpo: {} });
      await abrirLojaDaRede(chave);
    }
    catch (e) {
      if (e.status === 401) return;
      if (estado.modo === "rede") { $("erro-rede").textContent = e.message || "Não consegui abrir a loja."; $("erro-rede").hidden = false; }
      else mostrarFaixaDaRede();                        // volta o seletor para a loja que continua aberta
    }
  }

  // ---- sessão da rede guardada no aparelho
  function guardarRede(grupo, expira) {
    gravarArmazenamento(REDE_FLAG, "1");
    gravarArmazenamento(REDE_GRUPO, JSON.stringify(grupo));
    if (expira) gravarArmazenamento(REDE_EXPIRA, expira);
    try { localStorage.removeItem(REDE_TOKEN); } catch (_) { /* o token da rede fica no cookie */ }
  }

  /** Grupo da rede neste aparelho, ou null. O token não fica no navegador. */
  function redeGuardada() {
    if (lerArmazenamento(REDE_FLAG) !== "1") return null;
    const expira = lerArmazenamento(REDE_EXPIRA);
    if (expira && expira < agoraLocalIso()) return null;
    try {
      const grupo = JSON.parse(lerArmazenamento(REDE_GRUPO) || "null");
      return grupo ? { grupo: grupo, expira: expira } : null;
    } catch (_) { return null; }
  }

  function esquecerRede() {
    try { [REDE_TOKEN, REDE_FLAG, REDE_GRUPO, REDE_EXPIRA, REDE_ULTIMA].forEach((k) => localStorage.removeItem(k)); } catch (_) { /* navegador privado */ }
  }

  function mostrarFaixaDaRede() {
    const rede = estado.modo === "loja" ? redeGuardada() : null;
    $("faixa-rede").hidden = !rede;
    if (!rede) return;
    if (!estado.grupo) estado.grupo = rede.grupo;
    $("faixa-rede-nome").textContent = rede.grupo.nome || "Rede";
    montarSeletoresDaRede(estado.loja && estado.loja.chave);
  }

  function mostrarRede() {
    estado.modo = "rede";
    $("tela-login").hidden = true;
    $("form-login").hidden = false;
    $("form-senha-rede").hidden = true;
    $("tela-app").hidden = true;
    $("tela-rede").hidden = false;
    $("nome-rede").textContent = (estado.grupo && estado.grupo.nome) || "Rede";
    if (estado.grupo) aplicarAppDaRede(estado.grupo.chave, estado.grupo.nome);
    gravarArmazenamento(REDE_ULTIMA, "resumo");
    montarSeletoresDaRede(RESUMO_DA_REDE);
    window.scrollTo(0, 0);
    atualizarRede();
  }

  /** Carrega a rede mostrando o erro na tela (sem derrubar nada) e girando o botão de atualizar. */
  async function atualizarRede() {
    const erro = $("erro-rede");
    erro.hidden = true;
    $("botao-atualizar-rede").classList.add("girando");
    try {
      await carregarRede();
      estado.ultimaAtualizacao = Date.now();
    } catch (e) {
      if (e.status !== 401) {
        erro.textContent = e.message || "Não consegui carregar a rede.";
        erro.hidden = false;
      }
    } finally {
      $("botao-atualizar-rede").classList.remove("girando");
    }
  }

  function situacaoNaRede(loja) {
    if (!loja.atualizado_em) return { texto: "o caixa ainda não enviou dados", alerta: true };
    if (loja.atraso_min !== null && loja.atraso_min !== undefined && Number(loja.atraso_min) > LIMITE_ATRASO_MIN) {
      return { texto: "sem enviar há " + formatarAtraso(loja.atraso_min), alerta: true };
    }
    return { texto: "caixa enviando", alerta: false };
  }

  function cartaoDaLojaNaRede(loja, total, temCusto) {
    const parte = total > 0 ? Math.round((loja.faturamento_cent || 0) * 100 / total) : 0;
    const vendas = loja.vendas === undefined || loja.vendas === null ? null
      : loja.vendas + (loja.vendas === 1 ? " venda" : " vendas");
    const lucro = temCusto ? "lucro " + formatarCentavos(loja.lucro_cent) + (loja.margem && loja.margem !== "—" ? " (" + loja.margem + ")" : "") : null;
    const ticket = loja.ticket_medio_cent === undefined || loja.ticket_medio_cent === null
      ? null : "ticket " + formatarCentavos(loja.ticket_medio_cent);
    const situacao = situacaoNaRede(loja);
    const barra = el("span", { class: "rede-barra", "aria-hidden": "true" }, el("span", {}));
    barra.firstChild.style.width = parte + "%";
    const botao = el("button", { type: "button", class: "rede-loja", "data-seletor": "rede-loja", "data-loja": loja.chave || "",
      "aria-label": "Abrir " + (loja.nome || loja.chave) },
      el("span", { class: "rede-loja-topo" },
        el("strong", { text: loja.nome || loja.chave }),
        el("strong", { class: "valor", text: formatarCentavos(loja.faturamento_cent) })),
      barra,
      el("span", { class: "sec", text: [parte + "% da rede", vendas, ticket, lucro].filter(Boolean).join(" · ") }),
      el("span", { class: "rede-loja-rodape" },
        el("span", { class: situacao.alerta ? "sec rede-alerta" : "sec", text: situacao.texto }),
        el("span", { class: "rede-abrir", text: "Abrir ›" })));
    botao.addEventListener("click", async () => {
      botao.disabled = true;
      try { await abrirLojaDaRede(loja.chave); }
      catch (e) {
        botao.disabled = false;
        if (e.status !== 401) { $("erro-rede").textContent = e.message || "Não consegui abrir a loja."; $("erro-rede").hidden = false; }
      }
    });
    return el("li", {}, botao);
  }

  async function carregarRede() {
    const base = new Date();
    const p = (n) => String(n).padStart(2, "0");
    const hoje = base.getFullYear() + "-" + p(base.getMonth() + 1) + "-" + p(base.getDate());
    const atalho = estado.atalhoRede || "hoje";
    let de = estado.redeDe;
    let ate = estado.redeAte;
    if (atalho !== "personalizado") {
      const faixa = datasDoLucro(hoje, atalho === "hoje" ? "dia" : atalho);
      de = faixa[0];
      ate = faixa[1];
      estado.redeDe = de;
      estado.redeAte = ate;
      if ($("rede-de")) $("rede-de").value = de;
      if ($("rede-ate")) $("rede-ate").value = ate;
    }
    if (!de || !ate) return;
    const dados = await chamarApi("/rede?de=" + encodeURIComponent(de) + "&ate=" + encodeURIComponent(ate));
    if (estado.modo !== "rede") return;                   // o dono abriu uma loja enquanto a resposta vinha
    $("rede-faturamento").textContent = formatarCentavos(dados.faturamento_cent);
    $("rede-custo").textContent = dados.cmv_sincronizado ? formatarCentavos(dados.custo_cent) : "—";
    $("rede-lucro").textContent = dados.cmv_sincronizado ? formatarCentavos(dados.lucro_cent) : "—";
    $("rede-margem").textContent = dados.cmv_sincronizado ? "Margem " + (dados.margem || "—") : "";
    const porLoja = (dados.por_loja || []).slice().sort((a, b) => (b.faturamento_cent || 0) - (a.faturamento_cent || 0)
      || String(a.nome).localeCompare(String(b.nome)));
    const parados = porLoja.filter((l) => situacaoNaRede(l).alerta).length;
    $("rede-resumo-lojas").textContent = porLoja.length + (porLoja.length === 1 ? " loja" : " lojas")
      + (parados ? " · " + parados + (parados === 1 ? " sem enviar" : " sem enviar") : " · todas enviando");
    const lojas = $("lista-rede-lojas");
    limpar(lojas);
    porLoja.forEach((loja) => lojas.append(cartaoDaLojaNaRede(loja, dados.faturamento_cent || 0, dados.cmv_sincronizado)));
    if (!porLoja.length) lojas.append(el("li", { class: "vazio", text: "Nenhuma loja ativa nesta rede." }));
    const formas = $("lista-rede-formas");
    limpar(formas);
    (dados.formas || []).forEach((forma) => {
      formas.append(el("li", null, el("span", { text: forma.tipo }),
        el("span", { class: "total", text: formatarCentavos(forma.lucro_cent) })));
    });
    $("bloco-rede-formas").hidden = !(dados.formas || []).length;
    const selectLoja = $("importar-rede-loja");
    if (selectLoja) {
      const atual = selectLoja.value;
      limpar(selectLoja);
      (dados.lojas || porLoja).forEach((loja) => {
        selectLoja.append(el("option", { value: loja.chave, text: (loja.nome || loja.chave) + " (" + loja.chave + ")" }));
      });
      if (atual) selectLoja.value = atual;
    }
    $("rede-atualizado").textContent = "Atualizado às " + p(base.getHours()) + ":" + p(base.getMinutes());
  }

  async function abrirLojaDaRede(chave) {
    const dados = await chamarApi("/grupo/entrar", { metodo: "POST", corpo: { loja: chave } });
    apagarTudoLocal();                                    // o que estiver guardado é de outra loja
    Object.assign(estado, { resumo: null, historico: null, ranking: null, periodo: null, vendas: null, dia: null,
      paginaVendas: 1, lojas: null, mesAtual: null, carregando: false });
    estado.modo = "loja";
    $("tela-rede").hidden = true;
    guardarSessao(dados, chave);
    gravarArmazenamento(REDE_ULTIMA, chave);
    mostrarApp();
    trocarAba("hoje");
    window.scrollTo(0, 0);
    atualizarTudo();
  }

  /** Sai da loja aberta pela rede e volta para a lista de lojas, sem pedir senha de novo. */
  async function voltarParaRede() {
    const rede = redeGuardada();
    if (!rede) { encerrarSessao(true); return; }
    try { await chamarApi("/grupo/voltar", { metodo: "POST", corpo: {} }); }
    catch (_) { encerrarSessao(true); return; }
    apagarTudoLocal();
    Object.assign(estado, { token: SESSAO_COOKIE, grupo: rede.grupo, loja: null, resumo: null, historico: null, ranking: null,
      periodo: null, vendas: null, dia: null, paginaVendas: 1, lojas: null, mesAtual: null, carregando: false });
    guardarRede(rede.grupo, rede.expira);
    $("faixa-rede").hidden = true;
    esconderFaixas();
    mostrarRede();
  }

  async function atualizarTudo() {
    if (!sessaoValida()) {
      encerrarSessao(false);
      return;
    }
    if (estado.modo === "rede") {
      if (estado.carregando) return;
      estado.carregando = true;
      try { await atualizarRede(); }
      finally { estado.carregando = false; }
      return;
    }
    if (estado.carregando) return;
    estado.carregando = true;
    $("botao-atualizar").classList.add("girando");
    $("faixa-offline").hidden = true;
    $("faixa-erro").hidden = true;
    try {
      await carregarResumo();
      sincronizarDatasDoAtalho();
      const tarefas = [carregarHistorico(), carregarRanking()];
      // Dono de uma loja só consulta "Minhas lojas" uma vez; com duas ou mais, os números acompanham cada atualização.
      if (estado.lojas === null || estado.lojas.length > 1) tarefas.push(carregarLojas());
      if (estado.aba === "vendas") tarefas.push(carregarVendas());
      if (estado.aba === "periodo") tarefas.push(carregarPeriodo());
      if (estado.aba === "lucro") tarefas.push(carregarLucro(), carregarRelatorioDiario());
      await Promise.all(tarefas);
      estado.ultimaAtualizacao = Date.now();
    } finally {
      estado.carregando = false;
      $("botao-atualizar").classList.remove("girando");
    }
  }

  // Recarrega se fizer mais de 5 s desde a última atualização (evita duplicar em foco + visibilidade).
  function atualizarSeAntigo() {
    if (document.visibilityState !== "visible" || !estado.token) return;
    if (Date.now() - estado.ultimaAtualizacao > 5000) atualizarTudo();
  }

  // ------------------------------------------------------------------
  // Renderização: aba Hoje
  // ------------------------------------------------------------------

  function renderizarTopDia(produtos) {
    preencherGestao("lista-top-dia", "vazio-top-dia", (produtos || []).slice(0, 5), (p) => linhaNomeValor(
      p.nome, formatarQuantidade(p.quantidade), formatarCentavos(p.valor_cent)));
  }

  function renderizarResumo(r) {
    const v = r.vendas || {};
    const loja = r.loja || estado.loja;
    if (loja && loja.nome) $("nome-loja").textContent = loja.nome;

    // Status de atualização do PDV (relógio da loja no último envio).
    const status = $("status-atualizacao");
    limpar(status);
    if (r.atualizado_em) {
      const nCaixas = Array.isArray(r.caixas) ? r.caixas.length : 0;
      status.append("última atualização " + formatarHora(r.atualizado_em) +
        (r.atraso_min !== null && r.atraso_min !== undefined ? " (há " + formatarAtraso(r.atraso_min) + ")" : ""));
      // "· 3 caixas" não parte no meio: se faltar espaço, vai inteiro para a linha de baixo.
      if (nCaixas > 1) status.append(el("span", { class: "sem-quebra", text: " · " + nCaixas + " caixas" }));
    } else {
      status.append("última atualização —");
    }
    mostrarAtraso(r.atraso_min);
    renderizarAlertas(r.alertas || []);
    renderizarMesAtual(r);
    renderizarTopDia(r.produtos || []);

    $("v-faturamento").textContent = formatarCentavos(v.faturamento_cent);
    $("v-devolucoes").textContent = typeof v.devolucoes_cent === "number" ? formatarCentavos(v.devolucoes_cent) : "—";
    $("v-liquido").textContent = typeof v.liquido_cent === "number" ? formatarCentavos(v.liquido_cent) : "—";
    const devolucoes = r.devolucoes || {};
    const avisoDevolucoes = $("aviso-devolucoes");
    avisoDevolucoes.hidden = r.devolucoes_completas === true;
    avisoDevolucoes.textContent = "Devoluções podem estar incompletas. Atualize os caixas e aguarde o envio de todas as pendências.";
    $("ajustes-devolucoes").textContent = (devolucoes.quantidade || 0) + " devolução(ões). Custo recuperado com retorno ao estoque: " +
      formatarCentavos(devolucoes.custo_recuperado_cent || 0) + ". Ajuste de comissão dos itens a conferir pelo gerente: " +
      formatarCentavos(devolucoes.comissao_ajuste_cent || 0) + "." +
      (devolucoes.custos_incompletos ? " Há devoluções sem custo histórico disponível; os valores de custo são parciais." : "");
    $("v-quantidade").textContent = formatarInteiro(v.quantidade);
    $("v-ticket").textContent = formatarCentavos(v.ticket_medio_cent);
    $("v-canceladas").textContent = formatarInteiro(v.canceladas);
    $("v-canceladas-cent").textContent = v.canceladas ? formatarCentavos(v.canceladas_cent) : "";
    $("v-itens").textContent = formatarQuantidade(v.itens);
    $("v-desconto").textContent = formatarCentavos(v.desconto_cent);

    renderizarSeletorDia(r);
    renderizarPorHora(r.por_hora || []);
    renderizarFormas(r.formas || []);
    renderizarModalidades(r.modalidades || []);
    renderizarCaixa(r);
    renderizarMovimento(r);
    renderizarComandas(r);
    renderizarComissoes(r);
    renderizarAlertaEstoque(r);
    renderizarBar(r);
    renderizarProdutos(r);
    renderizarMeses(r);
    if (estado.historico) renderizarHistorico(estado.historico);
    if (estado.ranking) renderizarRanking(estado.ranking);

    $("vendas-dia").textContent = r.dia ? formatarData(r.dia) : "hoje";
  }

  function renderizarSeletorDia(r) {
    const sel = $("seletor-dia");
    const dias = Array.isArray(r.dias) ? r.dias.slice() : [];
    if (r.dia && !dias.includes(r.dia)) dias.unshift(r.dia);
    if (estado.dia && !dias.includes(estado.dia)) dias.unshift(estado.dia);
    dias.sort().reverse();

    limpar(sel);
    sel.append(el("option", { value: "", text: "Dia atual" + (r.dia && !estado.dia ? " (" + formatarDiaCurto(r.dia) + ")" : "") }));
    for (const d of dias) {
      sel.append(el("option", { value: d, text: formatarDiaCurto(d) + " — " + formatarData(d).slice(6) }));
    }
    sel.value = estado.dia || "";
    if (r.dia) $("data-dia").value = r.dia;
  }

  function renderizarPorHora(porHora) {
    const alvo = $("grafico-horas");
    const vazio = $("vazio-horas");
    limpar(alvo);
    const dados = porHora
      .map((h) => ({ hora: Number(h.hora), valor: Number(h.valor_cent) || 0, qt: Number(h.quantidade) || 0 }))
      .filter((h) => !Number.isNaN(h.hora));
    if (!dados.length) {
      alvo.hidden = true;
      vazio.hidden = false;
      return;
    }
    alvo.hidden = false;
    vazio.hidden = true;

    const porIndice = new Map(dados.map((h) => [h.hora, h]));
    const horas = dados.map((h) => h.hora);
    const inicio = Math.min(...horas);
    const fim = Math.max(...horas);
    const maximo = Math.max(...dados.map((h) => h.valor), 1);
    const total = fim - inicio + 1;
    const mostrarTopo = total <= 12;

    for (let h = inicio; h <= fim; h++) {
      const item = porIndice.get(h) || { valor: 0, qt: 0 };
      const altura = Math.max(2, Math.round((item.valor / maximo) * 100));
      const rotuloHora = String(h).padStart(2, "0") + "h";
      alvo.append(el("div", {
        class: "barra" + (item.valor ? "" : " vazia"),
        title: rotuloHora + ": " + formatarCentavos(item.valor) + " em " + formatarInteiro(item.qt) + " venda(s)",
      },
        mostrarTopo && item.valor ? el("span", { class: "topo", text: formatarReaisCurto(item.valor) }) : null,
        el("div", { class: "preenchimento", style: "height:" + altura + "%" }),
        el("span", { class: "eixo", text: total > 16 && h % 2 ? "" : rotuloHora })
      ));
    }
  }

  function renderizarFormas(formas) {
    const alvo = $("lista-formas");
    const vazio = $("vazio-formas");
    limpar(alvo);
    const itens = formas.filter((f) => f && (Number(f.valor_cent) || 0) !== 0);
    vazio.hidden = itens.length > 0;
    const total = itens.reduce((s, f) => s + (Number(f.valor_cent) || 0), 0) || 1;
    for (const f of itens) {
      const pct = Math.round(((Number(f.valor_cent) || 0) / total) * 100);
      alvo.append(el("li", null,
        el("div", { class: "nome" },
          el("span", { text: f.tipo || "—" }),
          el("div", { class: "medidor" }, el("span", { style: "width:" + pct + "%" }))
        ),
        el("span", { class: "valor" }, formatarCentavos(f.valor_cent), el("span", { class: "sec", text: pct + "%" }))
      ));
    }
  }

  function renderizarModalidades(modalidades) {
    const alvo = $("lista-modalidades");
    const vazio = $("vazio-modalidades");
    limpar(alvo);
    const itens = modalidades.filter((m) => m && (Number(m.quantidade) || 0) > 0);
    vazio.hidden = itens.length > 0;
    for (const m of itens) {
      alvo.append(el("li", null,
        el("div", { class: "nome" },
          el("span", { text: nomeModalidade(m.modalidade) }),
          el("span", { class: "sec", text: formatarInteiro(m.quantidade) + " venda(s)" })
        ),
        el("span", { class: "valor", text: formatarCentavos(m.valor_cent) })
      ));
    }
  }

  function renderizarHistorico(h) {
    const alvo = $("grafico-dias");
    const vazio = $("vazio-historico");
    const dias = Array.isArray(h.dias) ? h.dias : [];
    const diaAtual = estado.resumo && (estado.resumo.dia_operacional || estado.resumo.dia);
    const pontos = dias.map((d, i) => {
      const valor = Number(d.faturamento_cent) || 0;
      const longeDasPontas = i > 1 && i < dias.length - 2;
      const mostrar = i === 0 || i === dias.length - 1 || (longeDasPontas && d.dia && Number(d.dia.slice(8, 10)) % 5 === 0);
      return {
        valor,
        rotulo: mostrar && d.dia ? d.dia.slice(8, 10) : "",
        destaque: d.dia === diaAtual,
        titulo: formatarDiaCurto(d.dia) + ": bruto " + formatarCentavos(valor) + " em " + formatarInteiro(d.quantidade) +
          (typeof d.liquido_cent === "number" ? "; devoluções " + formatarCentavos(d.devolucoes_cent) + "; líquido " + formatarCentavos(d.liquido_cent) : "") +
          " venda(s)" + (d.canceladas ? ", " + formatarInteiro(d.canceladas) + " cancelada(s)" : ""),
      };
    });
    const tem = desenharGrafico(alvo, pontos, "Faturamento bruto dos últimos 30 dias", "detalhe-dias");
    alvo.hidden = !tem;
    vazio.hidden = tem;
    if (!tem) $("detalhe-dias").textContent = "";
  }

  function renderizarMeses(r) {
    const alvo = $("grafico-meses");
    const nota = $("nota-meses");
    const meses = Array.isArray(r.faturamento_meses) ? r.faturamento_meses : [];
    if (!r.atualizado_em) {
      nota.hidden = false;
      nota.textContent = "O PDV ainda não enviou o faturamento por mês.";
    } else if (r.meses_origem === "nuvem") {
      nota.hidden = false;
      nota.textContent = "O caixa ainda não envia o faturamento por mês. O gráfico usa só o que a nuvem guarda (cerca de 120 dias). Atualize o PDV da loja para ver os 12 meses.";
    } else if (r.meses_parcial) {
      nota.hidden = false;
      nota.textContent = "Algum caixa ainda não envia o faturamento por mês. Atualize todos os PDVs da loja.";
    } else {
      nota.hidden = true;
    }
    const atual = r.dia_operacional ? String(r.dia_operacional).slice(0, 7) : "";
    const pontos = meses.map((m) => ({
      valor: Number(m.faturamento_cent) || 0,
      rotulo: rotuloMes(m.mes),
      destaque: m.mes === atual,
      titulo: rotuloMes(m.mes) + "/" + String(m.mes || "").slice(2, 4) + ": " + formatarCentavos(m.faturamento_cent) +
        " em " + formatarInteiro(m.quantidade) + " venda(s)",
    }));
    const tem = desenharGrafico(alvo, pontos, "Faturamento bruto dos últimos 12 meses", "detalhe-meses");
    alvo.hidden = !tem;
    $("vazio-meses").hidden = tem;
    if (!tem) $("detalhe-meses").textContent = "";
  }

  // ------------------------------------------------------------------
  // Renderização: aba Caixa
  // ------------------------------------------------------------------

  // Os caixas da loja. Uma nuvem anterior aos vários caixas manda só `caixa`: vira uma lista de um item, no mesmo formato.
  function caixasDoResumo(r) {
    if (Array.isArray(r.caixas)) return r.caixas;
    if (!r.atualizado_em && !r.caixa) return [];
    return [{ id: "unico", rotulo: "Caixa", computador: "", atualizado_em: r.atualizado_em, atraso_min: r.atraso_min,
              caixa: r.caixa || null }];
  }

  function cartaoValor(rotulo, valor, opcoes = {}) {
    return el("article", { class: "cartao" + (opcoes.destaque ? " destaque" : "") },
      el("span", { class: "rotulo", text: rotulo }),
      el("strong", { class: "valor-grande", text: valor }),
      opcoes.detalhe ? el("small", { class: "detalhe", text: opcoes.detalhe }) : null
    );
  }

  function montarTurno(c) {
    const numero = c.turno_numero !== null && c.turno_numero !== undefined ? "#" + c.turno_numero : "—";
    return [
      el("p", { class: "linha-detalhes" },
        el("span", null, "Turno ", el("strong", { text: numero })),
        el("span", null, "Operador: ", el("strong", { text: c.operador || "—" })),
        el("span", null, "Aberto às ", el("strong", { text: formatarHora(c.aberto_em) }))
      ),
      el("div", { class: "grade-cartoes" },
        cartaoValor("Esperado na gaveta", formatarCentavos(c.esperado_gaveta_cent), { destaque: true }),
        cartaoValor("Valor inicial", formatarCentavos(c.valor_inicial_cent)),
        cartaoValor("Recebido", formatarCentavos(c.recebido_cent)),
        cartaoValor("Sangrias", formatarCentavos(c.sangrias_cent)),
        cartaoValor("Suprimentos", formatarCentavos(c.suprimentos_cent)),
        cartaoValor("Vendas no turno", formatarInteiro(c.tc), { detalhe: "Ticket médio " + formatarCentavos(c.tm_cent) }),
        cartaoValor("Cancelamentos", formatarInteiro(c.cancelamentos))
      ),
    ];
  }

  // Com mais de um caixa cada cartão ganha cabeçalho: nome, aberto/fechado e há quanto tempo o PDV dele não fala.
  function montarCaixa(c, varios) {
    const aberto = !!c.caixa;
    const parado = c.atraso_min !== null && c.atraso_min !== undefined && Number(c.atraso_min) > LIMITE_ATRASO_MIN;
    const origem = [c.computador, c.atualizado_em ? "atualizado às " + formatarHora(c.atualizado_em) : "ainda não enviou"]
      .filter(Boolean).join(" · ");
    return el("div", { class: "caixa-cartao" },
      varios ? el("div", { class: "caixa-titulo" },
        el("strong", { text: c.rotulo || "Caixa" }),
        el("span", { class: "etiqueta " + (aberto ? "etiqueta-aberto" : "etiqueta-fechado"), text: aberto ? "Aberto" : "Fechado" }),
        parado ? el("span", { class: "etiqueta etiqueta-parado", text: "Sem enviar há " + formatarAtraso(c.atraso_min) }) : null,
        el("span", { class: "detalhe", text: origem })
      ) : null,
      aberto ? montarTurno(c.caixa) : el("div", { class: "cartao cartao-neutro" },
        el("strong", { text: "Caixa fechado" }),
        el("p", { class: "detalhe", text: "Nenhum turno aberto no momento." })
      )
    );
  }

  function renderizarCaixa(r) {
    const caixas = caixasDoResumo(r);
    const alvo = $("lista-caixas");
    limpar(alvo);
    $("vazio-caixas").hidden = caixas.length > 0;
    for (const c of caixas) alvo.append(montarCaixa(c, caixas.length > 1));
    $("nota-soma-caderneta").hidden = caixas.length < 2;
    $("nota-soma-entregas").hidden = caixas.length < 2;
    const cad = r.caderneta || {};
    $("cd-receber").textContent = formatarCentavos(cad.a_receber_cent);
    $("cd-clientes").textContent = formatarInteiro(cad.clientes_devendo);
    $("entregas-pendentes").textContent = formatarInteiro(r.entregas_pendentes);
  }

  function renderizarMovimento(r) {
    const nota = $("nota-movimento");
    const sel = $("seletor-movimento");
    const listaF = $("lista-fechamentos");
    const listaS = $("lista-sangrias");
    limpar(listaF);
    limpar(listaS);
    if (!r.movimento_sincronizado) {
      nota.hidden = false;
      nota.textContent = r.atualizado_em
        ? "Atualize o PDV da loja para ver o fechamento e as sangrias de cada dia."
        : "O PDV ainda não enviou dados do caixa.";
      limpar(sel);
      $("vazio-fechamentos").hidden = true;
      $("vazio-sangrias").hidden = true;
      $("sangrias-total").textContent = formatarCentavos(0);
      return;
    }
    nota.hidden = !r.movimento_parcial;
    if (r.movimento_parcial) nota.textContent = "Algum caixa ainda não envia o fechamento. Atualize todos os PDVs da loja.";
    const fechamentos = Array.isArray(r.fechamentos) ? r.fechamentos : [];
    const sangrias = Array.isArray(r.sangrias) ? r.sangrias : [];
    const dias = new Set();
    for (const f of fechamentos) if (f.dia) dias.add(f.dia);
    for (const s of sangrias) if (s.dia) dias.add(s.dia);
    if (r.dia_operacional) dias.add(r.dia_operacional);
    const ordenados = Array.from(dias).sort().reverse();
    const escolhido = estado.diaMovimento && ordenados.includes(estado.diaMovimento)
      ? estado.diaMovimento : (r.dia_operacional && ordenados.includes(r.dia_operacional) ? r.dia_operacional : (ordenados[0] || ""));
    limpar(sel);
    for (const d of ordenados) sel.append(el("option", { value: d, text: formatarDiaCurto(d) }));
    sel.value = escolhido;
    const doDiaF = fechamentos.filter((f) => f.dia === escolhido);
    const doDiaS = sangrias.filter((s) => s.dia === escolhido);
    $("vazio-fechamentos").hidden = doDiaF.length > 0;
    $("vazio-sangrias").hidden = doDiaS.length > 0;
    for (const f of doDiaF) {
      listaF.append(el("div", { class: "caixa-cartao" },
        el("div", { class: "caixa-titulo" },
          el("strong", { text: "Turno #" + (f.turno_numero != null ? f.turno_numero : "—") }),
          el("span", { class: "etiqueta " + ((Number(f.resultado_cent) || 0) === 0 ? "etiqueta-aberto" : "etiqueta-baixo"),
            text: textoResultado(f.resultado_cent) }),
          f.caixa ? el("span", { class: "detalhe", text: f.caixa }) : null
        ),
        el("p", { class: "linha-detalhes" },
          el("span", null, "Operador: ", el("strong", { text: f.operador || "—" })),
          el("span", null, "Fechado às ", el("strong", { text: formatarHora(f.fechado_em) }))
        ),
        el("div", { class: "grade-cartoes" },
          cartaoValor("Contado", formatarCentavos(f.valor_final_cent), { destaque: true }),
          cartaoValor("Esperado", formatarCentavos(f.esperado_cent)),
          cartaoValor("Fundo", formatarCentavos(f.valor_inicial_cent)),
          cartaoValor("Sangrias", formatarCentavos(f.sangrias_cent)),
          cartaoValor("Suprimentos", formatarCentavos(f.suprimentos_cent))
        )
      ));
    }
    let total = 0;
    for (const s of doDiaS) {
      total += Number(s.valor_cent) || 0;
      listaS.append(el("li", null,
        el("div", { class: "nome" },
          el("span", { text: s.descricao || "Sangria" }),
          el("span", { class: "sec", text: formatarHora(s.criado_em) + " · turno #" + (s.turno_numero != null ? s.turno_numero : "—") +
            (s.operador ? " · " + s.operador : "") + (s.caixa ? " · " + s.caixa : "") })
        ),
        el("span", { class: "valor", text: formatarCentavos(s.valor_cent) })
      ));
    }
    $("sangrias-total").textContent = formatarCentavos(total);
  }

  function renderizarBar(r) {
    const bar = r.bar || {};
    const perfil = r.perfil || {};
    const servicoOk = bar.servico_sincronizado;
    $("nota-servico").hidden = servicoOk !== false || !(r.vendas && r.vendas.quantidade);
    $("nota-servico").textContent = "O caixa ainda não separa a taxa de serviço. Atualize o PDV da loja.";
    $("servico-dia").textContent = formatarCentavos(bar.servico_cent);
    $("servico-mes").textContent = bar.servico_mes_sincronizado ? formatarCentavos(bar.servico_mes_cent) : "—";
    $("consumo-dia").textContent = formatarCentavos(bar.consumo_cent);
    const mesas = bar.mesas || {};
    $("bloco-mesa-resumo").hidden = perfil.mostrar_salao === false;
    $("ticket-mesa").textContent = formatarCentavos(mesas.ticket_medio_cent);
    $("ticket-pessoa").textContent = mesas.pessoas ? formatarCentavos(mesas.ticket_pessoa_cent) : "—";
    $("tempo-mesa").textContent = mesas.permanencia_min ? mesas.permanencia_min + " min" : "—";
    $("nota-mesa-resumo").hidden = !(perfil.conhecido === false && mesas.quantidade);
    $("nota-mesa-resumo").textContent = "Tempo, pessoas e garçom completos pedem o PDV atualizado.";
    const antes = bar.semana_anterior;
    const notaPico = $("nota-pico");
    if (antes) {
      notaPico.hidden = false;
      notaPico.textContent = "Mesmo dia da semana passada (" + formatarDiaCurto(antes.dia) + "): " +
        formatarCentavos(antes.faturamento_cent) + " em " + formatarInteiro(antes.quantidade) + " venda(s).";
    } else {
      notaPico.hidden = true;
    }
    preencherLista($("lista-cancelamentos"), $("vazio-cancelamentos"), bar.cancelamentos || [], (c) =>
      el("li", null,
        el("div", { class: "nome" },
          el("span", { text: (c.cupom ? "Cupom " + c.cupom : "Venda") + (c.hora ? " · " + formatarHora(c.hora) : "") }),
          el("span", { class: "sec", text: (c.operador || "—") + (c.motivo ? " · " + c.motivo : "") })
        ),
        el("span", { class: "valor", text: formatarCentavos(c.total_cent) })
      ));
    preencherLista($("lista-descontos"), $("vazio-descontos"), bar.descontos || [], (d) =>
      el("li", null,
        el("div", { class: "nome" },
          el("span", { text: (d.cupom ? "Cupom " + d.cupom : "Venda") + (d.rotulo ? " · " + d.rotulo : "") }),
          el("span", { class: "sec", text: d.operador || "—" })
        ),
        el("span", { class: "valor", text: formatarCentavos(d.desconto_cent) })
      ));
    const mostrarGarotas = perfil.mostrar_garotas === true;
    $("cartao-garotas").hidden = !mostrarGarotas;
    $("tab-garotas").hidden = !mostrarGarotas;
    if (!mostrarGarotas && estado.aba === "garotas") trocarAba("hoje");
    const salao = perfil.mostrar_salao !== false;
    $("tab-abertas").hidden = !salao;
    if (!salao && estado.aba === "abertas") trocarAba("hoje");
    $("nota-garcons").hidden = bar.garcons_sincronizados !== false;
    $("nota-garcons").textContent = "O garçom de cada mesa passa a aparecer depois de atualizar o PDV.";
    preencherLista($("lista-garcons"), $("vazio-garcons"), bar.garcons || [], (g) =>
      el("li", null,
        el("div", { class: "nome" },
          el("span", { text: g.nome || "Sem garçom" }),
          el("span", { class: "sec", text: formatarInteiro(g.vendas) + " mesa(s) · serviço " + formatarCentavos(g.servico_cent) +
            " · comissão " + formatarCentavos(g.comissao_cent) })
        ),
        el("span", { class: "valor", text: formatarCentavos(g.consumo_cent) })
      ));
    const avisoGrupo = "Grupo, setor e custo do item pedem o PDV atualizado. O ranking acima continua com as vendas que já subiram.";
    $("nota-grupos").hidden = bar.grupos_sincronizados !== false;
    $("nota-grupos").textContent = avisoGrupo;
    preencherLista($("lista-grupos"), $("vazio-grupos"), bar.grupos || [], (g) =>
      el("li", null,
        el("span", { class: "nome", text: g.nome }),
        el("span", { class: "valor", text: formatarCentavos(g.valor_cent) })
      ));
    $("bloco-setores").hidden = perfil.modulos && perfil.modulos.usar_cozinha_bar === false && !bar.setores_sincronizados;
    $("nota-setores").hidden = bar.setores_sincronizados !== false;
    $("nota-setores").textContent = avisoGrupo;
    preencherLista($("lista-setores"), $("vazio-setores"), bar.setores || [], (s) =>
      el("li", null,
        el("span", { class: "nome", text: s.nome }),
        el("span", { class: "valor", text: formatarCentavos(s.valor_cent) })
      ));
    $("nota-margem").hidden = bar.cmv_sincronizado !== false;
    $("nota-margem").textContent = "O custo do produto ainda não sobe. Atualize o PDV para ver CMV e margem.";
    $("faturamento-itens").textContent = formatarCentavos(bar.faturamento_itens_cent || 0);
    $("cmv-dia").textContent = bar.cmv_sincronizado ? formatarCentavos(bar.cmv_cent) : "—";
    $("margem-dia").textContent = bar.cmv_sincronizado ? formatarCentavos(bar.margem_cent) : "—";
  }

  function preencherLista(alvo, vazio, itens, montar) {
    limpar(alvo);
    vazio.hidden = itens.length > 0;
    for (const item of itens) alvo.append(montar(item));
  }

  function renderizarComandas(r) {
    const nota = $("nota-comandas");
    const lista = $("lista-comandas");
    limpar(lista);
    const comandas = Array.isArray(r.comandas) ? r.comandas : [];
    if (!r.comandas_sincronizadas) {
      nota.hidden = false;
      nota.textContent = r.atualizado_em
        ? "Atualize o PDV da loja para ver as mesas e comandas abertas."
        : "O PDV ainda não enviou dados.";
      $("comandas-qtd").textContent = "0";
      $("comandas-devido").textContent = formatarCentavos(0);
      $("comandas-garotas").textContent = "0";
      $("vazio-comandas").hidden = true;
      return;
    }
    nota.hidden = !r.comandas_parciais;
    if (r.comandas_parciais) nota.textContent = "Algum caixa ainda não envia as comandas. Atualize todos os PDVs da loja.";
    const devido = comandas.reduce((s, c) => s + (Number(c.devido_cent) || 0), 0);
    const garotas = comandas.filter((c) => c.garota).length;
    $("comandas-qtd").textContent = formatarInteiro(comandas.length);
    $("comandas-devido").textContent = formatarCentavos(devido);
    $("comandas-garotas").textContent = formatarInteiro(garotas);
    $("vazio-comandas").hidden = comandas.length > 0;
    const mostrarGarotas = r.perfil && r.perfil.mostrar_garotas === true;
    for (const c of comandas) {
      const devendo = c.situacao === "devendo";
      const itens = Array.isArray(c.itens) ? c.itens : [];
      const resumoItens = itens.map((i) => formatarQuantidade(i.quantidade) + " " + (i.nome || "")).join(", ");
      lista.append(el("li", null,
        el("div", { class: "nome" },
          el("span", null,
            el("strong", { text: c.rotulo || ((c.comanda === false ? "Mesa " : "Comanda ") + c.numero) }),
            mostrarGarotas && c.garota ? el("span", { class: "etiqueta etiqueta-garota", text: "Comissão lançada" }) : null
          ),
          el("span", { class: "sec", text: (c.aberta_txt ? "Aberta " + c.aberta_txt : "Aberta") +
            (c.garcom ? " · " + c.garcom : "") +
            (c.pessoas ? " · " + c.pessoas + " pessoa(s)" : "") +
            (c.caixa ? " · " + c.caixa : "") + (devendo ? "" : " · nada a cobrar") }),
          resumoItens ? el("span", { class: "sec", text: resumoItens }) : null
        ),
        el("span", { class: "valor", text: formatarCentavos(c.devido_cent) })
      ));
    }
  }

  function renderizarComissoes(r) {
    const nota = $("nota-comissoes");
    const lista = $("lista-comissoes");
    limpar(lista);
    const bloco = r.comissoes || {};
    $("comissoes-pendente").textContent = formatarCentavos(bloco.pendente_total_cent);
    if (!r.comandas_sincronizadas) {
      nota.hidden = false;
      nota.textContent = "As comissões passam a aparecer depois que o PDV da loja for atualizado.";
      $("comissoes-total").textContent = formatarCentavos(0);
      $("comissoes-detalhe").textContent = "";
      $("vazio-comissoes").hidden = true;
      return;
    }
    nota.hidden = !r.comandas_parciais;
    if (r.comandas_parciais) nota.textContent = "Algum caixa ainda não envia as comissões.";
    const ate = r.dia_operacional || r.dia;
    const dias = diasDoPeriodo(ate, estado.periodoComissoes);
    const por = new Map();
    let lancado = 0, pago = 0, aPagar = 0, qtd = 0;
    for (const l of bloco.linhas || []) {
      if (!dias.has(l.dia)) continue;
      qtd += 1;
      const valor = Number(l.valor_cent) || 0;
      lancado += valor;
      if (l.status === "paga") pago += valor;
      else aPagar += valor;
      const chave = (l.caixa ? l.caixa + ":" : "") + l.garota;
      const g = por.get(chave) || { garota: l.garota, nome: l.nome || "", caixa: l.caixa || "", pendente: 0, paga: 0 };
      if (l.nome) g.nome = l.nome;
      if (l.status === "paga") g.paga += valor;
      else g.pendente += valor;
      por.set(chave, g);
    }
    $("comissoes-total").textContent = formatarCentavos(lancado);
    $("comissoes-detalhe").textContent = qtd
      ? formatarInteiro(qtd) + " lançamento(s) · a pagar " + formatarCentavos(aPagar) + " · pago " + formatarCentavos(pago)
      : "";
    const garotas = Array.from(por.values()).sort((a, b) => (b.pendente + b.paga) - (a.pendente + a.paga) || a.garota - b.garota);
    $("vazio-comissoes").hidden = garotas.length > 0;
    for (const g of garotas) {
      const nome = g.nome ? " · " + g.nome : "";
      lista.append(el("li", null,
        el("div", { class: "nome" },
          el("span", { text: "Garota " + g.garota + nome }),
          el("span", { class: "sec", text: "A pagar " + formatarCentavos(g.pendente) + " · pago " + formatarCentavos(g.paga) +
            (g.caixa ? " · " + g.caixa : "") })
        ),
        el("span", { class: "valor", text: formatarCentavos(g.pendente + g.paga) })
      ));
    }
    renderizarPagamentosGarotas(r, dias);
  }

  /** Pagamentos às garotas (acertos) do mesmo período: dinheiro, Pix, vales, consumo descontado e shows. */
  function renderizarPagamentosGarotas(r, dias) {
    const bloco = r.comissoes || {};
    const nota = $("nota-pagamentos-garotas");
    const lista = $("lista-pagamentos-garotas");
    limpar(lista);
    $("garotas-consumo-pendente").textContent = formatarCentavos(bloco.consumo_pendente_cent || 0);
    if (!bloco.acertos_sincronizados) {
      nota.hidden = false;
      nota.textContent = "Os pagamentos às garotas aparecem depois que o caixa for atualizado (1.14.24 ou mais nova).";
    } else {
      nota.hidden = true;
    }
    const acertos = (bloco.acertos || []).filter((a) => dias.has(a.dia));
    const soma = (campo) => acertos.reduce((t, a) => t + (Number(a[campo]) || 0), 0);
    const pago = soma("dinheiro_cent") + soma("pix_cent");
    $("garotas-pago").textContent = formatarCentavos(pago);
    $("garotas-pago-detalhe").textContent = acertos.length
      ? formatarInteiro(acertos.length) + " pagamento(s) · comissão " + formatarCentavos(soma("comissao_cent"))
      : "";
    $("garotas-dinheiro").textContent = formatarCentavos(soma("dinheiro_cent"));
    $("garotas-pix").textContent = formatarCentavos(soma("pix_cent"));
    $("garotas-descontos").textContent = formatarCentavos(soma("vale_cent") + soma("consumo_cent"));
    $("garotas-descontos-detalhe").textContent = "vales " + formatarCentavos(soma("vale_cent")) +
      " · consumo " + formatarCentavos(soma("consumo_cent"));
    $("garotas-shows").textContent = formatarInteiro(soma("shows"));
    $("garotas-shows-detalhe").textContent = formatarCentavos(soma("shows_cent"));
    $("vazio-pagamentos-garotas").hidden = acertos.length > 0;
    for (const a of acertos) {
      const nome = a.nome ? " · " + a.nome : "";
      const partes = [];
      if (a.dinheiro_cent) partes.push("dinheiro " + formatarCentavos(a.dinheiro_cent));
      if (a.pix_cent) partes.push("Pix " + formatarCentavos(a.pix_cent));
      if (a.vale_cent) partes.push("vale " + formatarCentavos(a.vale_cent));
      if (a.consumo_cent) partes.push("consumo " + formatarCentavos(a.consumo_cent));
      if (a.shows) partes.push(a.shows + " show(s)");
      const quando = (a.criado_em || "").slice(8, 10) + "/" + (a.criado_em || "").slice(5, 7) + " " + (a.criado_em || "").slice(11, 16);
      lista.append(el("li", null,
        el("div", { class: "nome" },
          el("span", { text: "Garota " + a.garota + nome }),
          el("span", { class: "sec", text: quando + (partes.length ? " · " + partes.join(" · ") : "") +
            (a.operador ? " · " + a.operador : "") + (a.caixa ? " · " + a.caixa : "") })
        ),
        el("span", { class: "valor", text: formatarCentavos(a.total_cent) })
      ));
    }
  }

  function renderizarAlertaEstoque(r) {
    const { total, itens } = alertasEstoque(r);
    const selo = $("selo-estoque");
    if (total > 0) {
      selo.hidden = false;
      selo.textContent = total > 99 ? "99+" : String(total);
    } else {
      selo.hidden = true;
    }
    const lista = $("lista-alerta-estoque");
    limpar(lista);
    const amostra = itens.slice(0, 5);
    $("vazio-alerta-estoque").hidden = amostra.length > 0;
    $("alerta-estoque-resumo").textContent = total
      ? total + " produto(s) no mínimo ou abaixo. O mínimo é o cadastrado em cada produto."
      : "Nenhum produto no mínimo ou abaixo. O mínimo é o cadastrado em cada produto.";
    for (const li of itensAbaixoDoMinimo({ abaixo_minimo: amostra })) lista.append(li);
    if (total > amostra.length) {
      lista.append(el("li", null, el("span", { class: "sec", text: "e mais " + (total - amostra.length) + " na aba Produtos" })));
    }
  }

  function alertasEstoque(r) {
    const caixas = caixasDoResumo(r);
    const fontes = caixas.length ? caixas : [{ estoque: r.estoque || {} }];
    let total = 0;
    const itens = [];
    for (const f of fontes) {
      const est = f.estoque || {};
      const n = Number(est.abaixo_minimo_total);
      total += Number.isFinite(n) && est.abaixo_minimo_total !== undefined && est.abaixo_minimo_total !== null
        ? n : (Array.isArray(est.abaixo_minimo) ? est.abaixo_minimo.length : 0);
      for (const i of (Array.isArray(est.abaixo_minimo) ? est.abaixo_minimo : [])) itens.push(i);
    }
    itens.sort((a, b) => (Number(a.qt_atual) || 0) - (Number(b.qt_atual) || 0));
    return { total, itens };
  }

  // ------------------------------------------------------------------
  // Renderização: aba Produtos & Estoque
  // ------------------------------------------------------------------

  function renderizarRanking(dados) {
    const alvo = $("lista-produtos");
    const vazio = $("vazio-produtos");
    limpar(alvo);
    const produtos = dados && Array.isArray(dados.produtos) ? dados.produtos : [];
    vazio.hidden = produtos.length > 0;
    const de = dados && dados.de, ate = dados && dados.ate;
    $("ranking-periodo").textContent = de && ate
      ? (de === ate ? formatarData(de) : formatarData(de) + " a " + formatarData(ate))
      : "";
    for (const p of produtos) {
      const nat = Number(p.naturais) || 0;
      const gel = Number(p.geladas) || 0;
      const soma = nat + gel;
      const pctGel = soma ? Math.round((gel / soma) * 100) : 0;
      alvo.append(el("li", null,
        el("div", { class: "nome" },
          el("span", { text: p.nome || "—" }),
          el("span", { class: "sec", text: formatarQuantidade(p.quantidade) + " un · " +
            formatarQuantidade(nat) + " natural · " + formatarQuantidade(gel) + " gelada" }),
          soma ? el("div", { class: "temperatura", title: pctGel + "% gelada" },
            el("span", { class: "nat", style: "width:" + (100 - pctGel) + "%" }),
            el("span", { class: "gel", style: "width:" + pctGel + "%" })
          ) : null
        ),
        el("span", { class: "valor", text: formatarCentavos(p.valor_cent) })
      ));
    }
  }

  function renderizarProdutos(r) {
    $("atacado-economia").textContent = formatarCentavos(r.atacado_economia_cent);
    renderizarEstoque(r);
  }

  // Cada caixa tem o seu banco, então o estoque de dois caixas não se soma: com mais de um controlando estoque, um bloco por caixa.
  function renderizarEstoque(r) {
    const comEstoque = caixasDoResumo(r).filter((c) => c.estoque && (Number(c.estoque.controlados) || 0) > 0);
    const porCaixa = comEstoque.length > 1;
    const alvo = $("estoque-por-caixa");
    limpar(alvo);
    alvo.hidden = !porCaixa;
    $("bloco-estoque").hidden = porCaixa;
    if (porCaixa) {
      for (const c of comEstoque) alvo.append(montarBlocoEstoque(c.rotulo || "Caixa", c.estoque));
      return;
    }
    const est = r.estoque || {};
    $("est-controlados").textContent = formatarInteiro(est.controlados);
    $("est-zerados").textContent = formatarInteiro(est.zerados);
    const listaEst = $("lista-estoque");
    limpar(listaEst);
    const itens = itensAbaixoDoMinimo(est);
    $("vazio-estoque").hidden = itens.length > 0;
    for (const li of itens) listaEst.append(li);
    const listaParados = $("lista-parados");
    limpar(listaParados);
    const parados = itensParados(est);
    $("vazio-parados").hidden = parados.length > 0 || !Array.isArray(est.parados);
    for (const li of parados) listaParados.append(li);
  }

  function itensParados(est) {
    return (Array.isArray(est.parados) ? est.parados : []).map((i) => el("li", null,
      el("div", { class: "nome" },
        el("strong", { text: i.nome || "—" }),
        el("span", { class: "sec", text: formatarQuantidade(i.qt_atual) + " em estoque · " +
          (i.ultima_venda ? "última venda " + i.ultima_venda.split("-").reverse().join("/") : "nunca vendeu") })),
      el("span", { class: "valor", text: formatarCentavos(i.valor_cent) })));
  }

  function itensAbaixoDoMinimo(est) {
    const abaixo = Array.isArray(est.abaixo_minimo) ? est.abaixo_minimo.slice() : [];
    abaixo.sort((a, b) => (Number(a.qt_atual) || 0) - (Number(b.qt_atual) || 0));
    return abaixo.map((i) => {
      const qt = Number(i.qt_atual) || 0;
      const zerado = qt <= 0;
      const unidade = i.unidade ? " " + i.unidade : "";
      return el("li", { class: zerado ? "zerado" : "" },
        el("div", { class: "nome" },
          el("strong", { text: i.nome || "—" }),
          el("span", { class: "sec", text: (i.codigo ? "Cód. " + i.codigo + " · " : "") +
            "mínimo " + formatarQuantidade(i.estoque_minimo) + unidade }),
        ),
        el("span", { class: "valor" },
          el("span", { class: "etiqueta " + (zerado ? "etiqueta-zerado" : "etiqueta-baixo"),
            text: zerado ? "Zerado" : formatarQuantidade(qt) + unidade })
        )
      );
    });
  }

  function montarBlocoEstoque(rotulo, est) {
    const itens = itensAbaixoDoMinimo(est);
    return el("section", { class: "bloco" },
      el("h2", { text: "Estoque · " + rotulo }),
      el("p", { class: "linha-detalhes" },
        el("span", null, "Controlados: ", el("strong", { text: formatarInteiro(est.controlados) })),
        el("span", null, "Zerados: ", el("strong", { text: formatarInteiro(est.zerados) }))
      ),
      el("h3", { text: "Abaixo do mínimo" }),
      itens.length ? el("ul", { class: "lista" }, itens) : el("p", { class: "vazio", text: "Nenhum produto abaixo do mínimo." }),
      ...(itensParados(est).length ? [el("h3", { text: "Parados há 30 dias" }), el("ul", { class: "lista" }, itensParados(est))] : [])
    );
  }

  // ------------------------------------------------------------------
  // Renderização: aba Vendas
  // ------------------------------------------------------------------

  function renderizarVendas(d) {
    const alvo = $("lista-vendas");
    const vazio = $("vazio-vendas");
    limpar(alvo);
    const vendas = Array.isArray(d.vendas) ? d.vendas : [];
    const total = Number(d.total) || 0;
    const pagina = Number(d.pagina) || 1;
    const paginas = Math.max(1, Number(d.paginas) || 1);

    if (d.dia) $("vendas-dia").textContent = formatarData(d.dia);
    $("vendas-total").textContent = total ? formatarInteiro(total) + " venda(s) no dia" : "";
    vazio.hidden = vendas.length > 0;

    for (const v of vendas) alvo.append(el("li", null, montarVenda(v)));

    $("pag-info").textContent = "Página " + pagina + " de " + paginas;
    $("pag-anterior").disabled = pagina <= 1;
    $("pag-proxima").disabled = pagina >= paginas;
    estado.paginaVendas = pagina;
  }

  // Só com mais de um caixa na loja vale dizer de qual saiu a venda.
  function rotuloDoCaixa(id) {
    const caixas = estado.resumo && Array.isArray(estado.resumo.caixas) ? estado.resumo.caixas : [];
    if (caixas.length < 2 || !id) return "";
    const caixa = caixas.find((c) => c.id === id);
    return caixa ? caixa.rotulo || "" : "";
  }

  function montarVenda(v) {
    const cancelada = v.status === "cancelada";
    const titulo = (v.cupom ? "Cupom " + v.cupom : "Venda") + " · " + formatarHora(v.fechada_em);
    const modalidade = nomeModalidade(v.modalidade);
    const posicao = (v.posicao_rotulo || "").trim();
    const sub = [modalidade, posicao.toLowerCase() !== modalidade.toLowerCase() ? posicao : "", v.operador,
      rotuloDoCaixa(v.terminal_id)].filter(Boolean).join(" · ");

    const itens = Array.isArray(v.itens) ? v.itens : [];
    const pagamentos = Array.isArray(v.pagamentos) ? v.pagamentos : [];

    const corpo = el("div", { class: "venda-corpo" });

    if (cancelada) {
      corpo.append(el("p", { class: "motivo", text: "Cancelada" + (v.motivo_cancelamento ? ": " + v.motivo_cancelamento : ".") }));
    }

    corpo.append(el("h4", { text: "Itens" }));
    if (itens.length) {
      corpo.append(el("ul", null, itens.map((i) => {
        const gelada = i.temperatura === "gelada";
        const observacao = gelada ? limparPrefixoGelada(i.observacao) : (i.observacao || "");
        return el("li", { class: Number(i.cancelado) ? "cancelado" : "" },
          el("span", null,
            formatarQuantidade(i.quantidade) + (i.unidade ? " " + i.unidade : "") + " × " + (i.nome || "—") + " ",
            gelada ? el("span", { class: "etiqueta etiqueta-gelada", text: "Gelada" }) : null,
            Number(i.cancelado) ? el("span", { class: "etiqueta etiqueta-cancelada", text: "Cancelado" }) : null,
            observacao ? el("span", { class: "obs", text: observacao }) : null
          ),
          el("span", { class: "valor", text: formatarCentavos(i.total_cent) })
        );
      })));
    } else {
      corpo.append(el("p", { class: "detalhe", text: "Sem itens." }));
    }

    if (Number(v.desconto_cent) > 0) {
      corpo.append(el("ul", null, el("li", null,
        el("span", { text: "Desconto" }),
        el("span", { class: "valor", text: "- " + formatarCentavos(v.desconto_cent) })
      )));
    }

    corpo.append(el("h4", { text: "Pagamentos" }));
    if (pagamentos.length) {
      corpo.append(el("ul", null, pagamentos.map((p) => el("li", null,
        el("span", null, p.tipo || "—",
          Number(p.troco_cent) > 0 ? el("span", { class: "obs", text: "Troco " + formatarCentavos(p.troco_cent) }) : null),
        el("span", { class: "valor", text: formatarCentavos(p.valor_cent) })
      ))));
    } else {
      corpo.append(el("p", { class: "detalhe", text: cancelada ? "Nenhum pagamento." : "Sem pagamentos registrados." }));
    }

    return el("details", { class: "venda" + (cancelada ? " cancelada" : "") },
      el("summary", null,
        el("div", { class: "cabecalho-venda" },
          el("strong", null, titulo, " ",
            cancelada ? el("span", { class: "etiqueta etiqueta-cancelada", text: "Cancelada" }) : null),
          el("span", { class: "sec", text: sub || "—" })
        ),
        el("span", { class: "total", text: formatarCentavos(v.total_cent) })
      ),
      corpo
    );
  }

  // ------------------------------------------------------------------
  // Navegação por abas
  // ------------------------------------------------------------------

  function trocarAba(nome) {
    estado.aba = nome;
    document.querySelectorAll(".aba").forEach((sec) => { sec.hidden = sec.id !== "aba-" + nome; });
    document.querySelectorAll(".aba-botao").forEach((b) => {
      const ativa = b.dataset.aba === nome;
      b.classList.toggle("ativa", ativa);
      b.setAttribute("aria-selected", ativa ? "true" : "false");
    });
    window.scrollTo({ top: 0 });
    if (nome === "vendas" && estado.token) carregarVendas();
    if (nome === "periodo" && estado.token) carregarPeriodo();
    if (nome === "lucro" && estado.token) { carregarLucro(); carregarRelatorioDiario(); }
    if (nome === "produtos" && estado.token) { carregarNotas(); carregarXmls(); carregarVendasTeste(); carregarImportacao(); }
  }

  function mudarDia(novoDia) {
    estado.dia = novoDia || null;
    estado.paginaVendas = 1;
    estado.vendas = null;
    atualizarTudo();
  }

  // ------------------------------------------------------------------
  // Instalação (PWA) e Service Worker
  // ------------------------------------------------------------------

  /** App da rede: a tela inicial do celular ganha o nome da rede e abre direto no login dela
   *  (/painel/rede.webmanifest?grupo=CHAVE). Sem rede, fica o manifesto comum do painel. */
  function aplicarAppDaRede(chave, nome) {
    if (!chave) return;
    const link = document.querySelector('link[rel="manifest"]');
    if (link) link.setAttribute("href", "rede.webmanifest?grupo=" + encodeURIComponent(chave));
    const titulo = document.querySelector('meta[name="apple-mobile-web-app-title"]');
    if (titulo && nome) titulo.setAttribute("content", String(nome).slice(0, 30));
    if (nome) document.title = nome;
  }

  function configurarInstalacao() {
    const botao = $("botao-instalar");
    const botaoRede = $("botao-instalar-rede");
    window.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault();
      estado.eventoInstalacao = e;
      botao.hidden = false;
      if (botaoRede) botaoRede.hidden = false;
    });
    if (botaoRede) botaoRede.addEventListener("click", async () => {
      const ev = estado.eventoInstalacao;
      if (!ev) return;
      botaoRede.hidden = true;
      botao.hidden = true;
      estado.eventoInstalacao = null;
      try { await ev.prompt(); } catch (_) { /* usuário recusou ou navegador bloqueou */ }
    });
    botao.addEventListener("click", async () => {
      const ev = estado.eventoInstalacao;
      if (!ev) return;
      botao.hidden = true;
      estado.eventoInstalacao = null;
      try { await ev.prompt(); } catch (_) { /* usuário recusou ou navegador bloqueou */ }
    });
    window.addEventListener("appinstalled", () => { botao.hidden = true; });
  }

  function registrarServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    // Em produção o app vive em /painel/; fora dele usa o diretório atual para não falhar.
    const escopo = location.pathname.startsWith(ESCOPO) ? ESCOPO : new URL("./", location.href).pathname;
    navigator.serviceWorker.register("sw.js", { scope: escopo }).catch(() => { /* sem SW: app segue funcionando */ });
  }

  // ------------------------------------------------------------------
  // Importar planilha (aba Produtos) e atalho da rede
  // ------------------------------------------------------------------

  let previaImportacao = null;

  function modoQuantidade() {
    const marcado = document.querySelector('input[name="modo-quantidade"]:checked');
    return marcado ? marcado.value : "substituir";
  }

  function avisarImportar(texto, erro) {
    const aviso = $("aviso-importar");
    if (!aviso) return;
    aviso.textContent = texto || "";
    aviso.hidden = !texto;
    aviso.classList.toggle("erro", !!erro);
  }

  function marcarLojaImportacao() {
    const bloco = $("bloco-importar-produtos");
    if (!bloco) return;
    const chave = estado.loja && estado.loja.chave ? estado.loja.chave : "";
    bloco.dataset.loja = chave;
    const rotulo = $("importar-loja-atual");
    if (!rotulo) return;
    rotulo.dataset.chave = chave;
    rotulo.textContent = chave ? "Loja: " + ((estado.loja && estado.loja.nome) || chave) : "";
  }

  async function baixarComSessao(caminho, nome) {
    const resposta = await fetch(API_BASE + caminho, {
      headers: { "X-PDV-Painel": "1" },
      credentials: "same-origin",
      cache: "no-store",
    });
    if (resposta.status === 401) {
      encerrarSessao(false);
      throw new ErroApi(401, "Sessão expirada. Entre novamente.");
    }
    if (!resposta.ok) {
      let detalhe = "Não consegui baixar o arquivo.";
      try {
        const dados = await resposta.json();
        if (dados && dados.detail) detalhe = String(dados.detail);
      } catch (_) { /* resposta sem JSON */ }
      throw new ErroApi(resposta.status, detalhe);
    }
    const blob = await resposta.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = nome;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function lerArquivoPlanilha(arquivo) {
    return new Promise((ok, falha) => {
      const leitor = new FileReader();
      leitor.onload = () => ok(String(leitor.result).split(",")[1] || "");
      leitor.onerror = () => falha(new Error("Não consegui ler o arquivo."));
      leitor.readAsDataURL(arquivo);
    });
  }

  function pintarPrevia(dados) {
    $("previa-importar").hidden = false;
    const criados = dados.criados || 0;
    const atualizados = dados.atualizados || 0;
    const erros = dados.erros || 0;
    $("resumo-importar").textContent = criados + " serão criados, " + atualizados +
      " serão atualizados, " + erros + " com erro.";
    $("nota-quantidade").textContent = dados.quantidade_texto || "";
    const corpo = $("corpo-previa-importar");
    limpar(corpo);
    const linhas = Array.isArray(dados.linhas) ? dados.linhas : [];
    const mostrar = linhas.filter((l) => l.acao === "recusar").concat(linhas.filter((l) => l.acao !== "recusar")).slice(0, 80);
    const rotulo = { criar: "Criar", atualizar: "Atualizar", recusar: "Erro" };
    mostrar.forEach((l) => {
      const motivo = [l.motivo || ""].concat(l.avisos || []).filter(Boolean).join(" ");
      const detalhe = [l.preco ? "R$ " + l.preco : "", l.quantidade ? "qtd " + l.quantidade : "", motivo].filter(Boolean).join(" · ");
      corpo.append(el("li", { class: "linha-" + (l.acao || ""), "data-linha": String(l.linha) },
        el("strong", { text: (rotulo[l.acao] || l.acao || "") + " · linha " + l.linha }),
        el("span", { text: (l.nome || "—") + (l.codigo_barras ? " · " + l.codigo_barras : "") }),
        detalhe ? el("span", { class: "detalhe", text: detalhe }) : null
      ));
    });
    if (linhas.length > mostrar.length) {
      corpo.append(el("li", { class: "vazio", text: "E mais " + (linhas.length - mostrar.length) + " linhas." }));
    }
    $("confirmar-importar").disabled = (criados + atualizados) === 0;
  }

  async function pedirPrevia(corpo) {
    avisarImportar("Conferindo a planilha…");
    const dados = await chamarApi("/importacao/previa", {
      metodo: "POST",
      corpo: Object.assign({ modo_quantidade: modoQuantidade() }, corpo),
    });
    previaImportacao = corpo;
    pintarPrevia(dados);
    avisarImportar("");
  }

  function pintarHistorico(dados) {
    const lista = $("lista-importacoes");
    const itens = (dados && dados.importacoes) || [];
    limpar(lista);
    $("vazio-importacoes").hidden = itens.length > 0;
    itens.forEach((item) => {
      const texto = (item.criado_em || "") + " · " + (item.autor || "dono") + " · " +
        (item.criados || 0) + " criados, " + (item.atualizados || 0) + " atualizados" +
        (item.desfeito_em ? " · desfeita" : "");
      lista.append(el("li", { "data-importacao": String(item.id) }, el("span", { text: texto })));
    });
    $("desfazer-importacao").disabled = !(itens.length && itens[0].pode_desfazer);
  }

  function pintarTokens(dados) {
    const lista = $("lista-tokens");
    limpar(lista);
    ((dados && dados.tokens) || []).forEach((t) => {
      const botao = el("button", { type: "button", class: "botao-secundario", text: "Revogar", "data-revogar": String(t.id) });
      botao.addEventListener("click", async () => {
        botao.disabled = true;
        try {
          await chamarApi("/importacao/tokens/" + t.id, { metodo: "DELETE" });
          await carregarImportacao();
        } catch (e) {
          avisarImportar(e.message, true);
          botao.disabled = false;
        }
      });
      lista.append(el("li", { "data-token": String(t.id) },
        el("span", { text: t.nome + (t.ultimo_uso ? " · usado " + t.ultimo_uso : " · ainda não usado") }),
        botao));
    });
  }

  function pintarBusca(dados) {
    const lista = $("lista-busca-produto");
    limpar(lista);
    const produtos = (dados && dados.produtos) || [];
    $("vazio-busca-produto").hidden = produtos.length > 0;
    produtos.forEach((p) => {
      const qtd = p.quantidade === null || p.quantidade === undefined ? "sem controle de estoque" : "estoque " + p.quantidade;
      lista.append(el("li", { "data-codigo": p.codigo || "", "data-barras": p.codigo_barras || "" },
        el("span", { text: (p.nome || "") + (p.codigo_barras ? " · " + p.codigo_barras : "") }),
        el("span", { class: "total", text: formatarCentavos(p.preco_cent) + " · " + qtd })));
    });
    if (dados && dados.total > produtos.length) {
      lista.append(el("li", { class: "vazio", text: "Mostrando " + produtos.length + " de " + dados.total + ". Exporte para ver todos." }));
    }
  }

  async function carregarImportacao() {
    if (!$("lista-importacoes") || !estado.token || estado.modo === "rede") return;
    marcarLojaImportacao();
    try {
      const hist = await chamarApi("/importacao/historico");
      const tokens = await chamarApi("/importacao/tokens");
      pintarHistorico(hist);
      pintarTokens(tokens);
    } catch (e) {
      if (e.status !== 401) avisarImportar(e.message, true);
    }
  }

  function configurarImportacao() {
    if (!$("arquivo-planilha")) return;
    $("desfazer-importacao").disabled = true;
    $("baixar-modelo-produtos").addEventListener("click", () => {
      baixarComSessao("/importacao/modelo", "modelo-produtos.csv").catch((e) => avisarImportar(e.message, true));
    });
    $("arquivo-planilha").addEventListener("change", async () => {
      const arquivo = $("arquivo-planilha").files && $("arquivo-planilha").files[0];
      if (!arquivo) return;
      try {
        await pedirPrevia({ nome: arquivo.name, conteudo_b64: await lerArquivoPlanilha(arquivo) });
      } catch (e) { avisarImportar(e.message, true); }
      $("arquivo-planilha").value = "";
    });
    $("previa-texto-planilha").addEventListener("click", async () => {
      const texto = $("texto-planilha").value;
      if (!texto.trim()) { avisarImportar("Cole a planilha na caixa de texto.", true); return; }
      try { await pedirPrevia({ texto: texto }); }
      catch (e) { avisarImportar(e.message, true); }
    });
    document.querySelectorAll('input[name="modo-quantidade"]').forEach((radio) => {
      radio.addEventListener("change", () => {
        if ($("previa-importar").hidden) return;
        $("nota-quantidade").textContent = radio.value === "somar"
          ? "A quantidade da planilha soma ao estoque atual. Produto novo começa com essa quantidade."
          : "A quantidade da planilha substitui o estoque atual do produto.";
      });
    });
    $("cancelar-previa").addEventListener("click", () => {
      previaImportacao = null;
      $("previa-importar").hidden = true;
      limpar($("corpo-previa-importar"));
    });
    $("confirmar-importar").addEventListener("click", async () => {
      if (!previaImportacao) return;
      const botao = $("confirmar-importar");
      botao.disabled = true;
      try {
        const dados = await chamarApi("/importacao/aplicar", {
          metodo: "POST",
          corpo: Object.assign({ modo_quantidade: modoQuantidade() }, previaImportacao),
        });
        avisarImportar(dados.mensagem || "Enviado ao caixa.");
        $("previa-importar").hidden = true;
        previaImportacao = null;
        await carregarImportacao();
      } catch (e) {
        avisarImportar(e.message, true);
        botao.disabled = false;
      }
    });
    $("botao-busca-produto").addEventListener("click", async () => {
      try { pintarBusca(await chamarApi("/importacao/produtos?q=" + encodeURIComponent($("busca-produto").value.trim()))); }
      catch (e) { avisarImportar(e.message, true); }
    });
    $("busca-produto").addEventListener("keydown", (evento) => {
      if (evento.key === "Enter") { evento.preventDefault(); $("botao-busca-produto").click(); }
    });
    $("exportar-csv").addEventListener("click", () => {
      baixarComSessao("/importacao/produtos?formato=csv", "produtos.csv").catch((e) => avisarImportar(e.message, true));
    });
    $("exportar-xlsx").addEventListener("click", () => {
      baixarComSessao("/importacao/produtos?formato=xlsx", "produtos.xlsx").catch((e) => avisarImportar(e.message, true));
    });
    $("desfazer-importacao").addEventListener("click", async () => {
      if (!window.confirm("Desfazer a última importação? O caixa aplica na próxima sincronização.")) return;
      try {
        const dados = await chamarApi("/importacao/desfazer", { metodo: "POST", corpo: {} });
        avisarImportar(dados.mensagem || "Desfazer enviado ao caixa.");
        await carregarImportacao();
      } catch (e) { avisarImportar(e.message, true); }
    });
    $("criar-token").addEventListener("click", async () => {
      try {
        const dados = await chamarApi("/importacao/tokens", { metodo: "POST", corpo: { nome: $("nome-token").value } });
        $("token-novo").hidden = false;
        $("token-novo").textContent = dados.token || "";
        $("copiar-token").hidden = !dados.token;
        avisarImportar(dados.aviso || "Token gerado. Copie agora; ele não aparece de novo.");
        await carregarImportacao();
      } catch (e) { avisarImportar(e.message, true); }
    });
    $("copiar-token").addEventListener("click", async () => {
      const texto = $("token-novo").textContent || "";
      try {
        await navigator.clipboard.writeText(texto);
        avisarImportar("Token copiado.");
      } catch (_) { avisarImportar("Não consegui copiar. Selecione o token e copie.", true); }
    });
    const abrirRede = $("importar-rede-abrir");
    if (abrirRede) abrirRede.addEventListener("click", async () => {
      const chave = $("importar-rede-loja").value;
      if (!chave) return;
      abrirRede.disabled = true;
      try {
        await abrirLojaDaRede(chave);
        trocarAba("produtos");
        const bloco = $("bloco-importar-produtos");
        if (bloco) bloco.scrollIntoView({ block: "start" });
      } catch (e) {
        abrirRede.disabled = false;
        if (e.status !== 401 && $("erro-rede")) {
          $("erro-rede").textContent = e.message || "Não consegui abrir a loja.";
          $("erro-rede").hidden = false;
        }
      }
    });
  }

  // ------------------------------------------------------------------
  // Inicialização
  // ------------------------------------------------------------------

  /** Botão "Mostrar" ao lado de cada campo de senha: o dono confere o que digitou. Ao enviar o formulário, volta a esconder. */
  function configurarMostrarSenha() {
    document.querySelectorAll('input[type="password"]').forEach((campo) => {
      if (campo.dataset.olho) return;
      campo.dataset.olho = "1";
      const caixa = el("span", { class: "campo-senha" });
      campo.parentNode.insertBefore(caixa, campo);
      caixa.append(campo);
      const botao = el("button", { type: "button", class: "botao-olho", text: "Mostrar" });
      botao.setAttribute("aria-label", "Mostrar a senha");
      botao.setAttribute("aria-pressed", "false");
      const esconder = () => {
        campo.type = "password";
        botao.textContent = "Mostrar";
        botao.setAttribute("aria-label", "Mostrar a senha");
        botao.setAttribute("aria-pressed", "false");
      };
      botao.addEventListener("click", () => {
        if (campo.type === "password") {
          campo.type = "text";
          botao.textContent = "Ocultar";
          botao.setAttribute("aria-label", "Ocultar a senha");
          botao.setAttribute("aria-pressed", "true");
        } else {
          esconder();
        }
        campo.focus();
      });
      if (campo.form) campo.form.addEventListener("submit", esconder);
      caixa.append(botao);
    });
  }

  function iniciar() {
    configurarMostrarSenha();
    try { localStorage.removeItem(CHAVE_TOKEN); localStorage.removeItem(REDE_TOKEN); } catch (_) { /* token antigo sai do aparelho */ }
    estado.token = null;
    try { estado.loja = JSON.parse(lerArmazenamento(CHAVE_LOJA) || "null"); } catch (_) { estado.loja = null; }

    $("form-login").addEventListener("submit", entrar);
    $("form-codigo").addEventListener("submit", confirmarCodigo);
    $("form-esqueci").addEventListener("submit", pedirNovaSenha);
    $("botao-esqueci").addEventListener("click", () => {
      const digitado = $("campo-loja").value.trim();
      $("campo-esqueci").value = digitado.includes("@") ? digitado : "";
      $("msg-esqueci").hidden = true;
      mostrarCartaoLogin("form-esqueci");
    });
    $("botao-esqueci-voltar").addEventListener("click", () => mostrarCartaoLogin("form-login"));
    $("botao-codigo-voltar").addEventListener("click", () => mostrarCartaoLogin("form-login"));
    $("botao-sair").addEventListener("click", () => encerrarSessao(true));
    $("botao-atualizar").addEventListener("click", () => atualizarAgora());
    configurarMeta();
    configurarNotas();
    configurarLojas();
    configurarOcultarValores();
    const botaoResumo = $("botao-resumo-whatsapp");
    if (botaoResumo) botaoResumo.addEventListener("click", () => compartilharWhatsapp(""));
    const botaoCopiar = $("botao-copiar-resumo");
    if (botaoCopiar) botaoCopiar.addEventListener("click", async () => {
      const dados = await textoDoResumo();
      if (dados && dados.texto) await navigator.clipboard.writeText(dados.texto);
    });
    const botaoPdf = $("botao-pdf");
    if (botaoPdf) botaoPdf.addEventListener("click", async () => {
      const dados = await textoDoResumo();
      if (!dados || !dados.texto || typeof baixarPdf !== "function") return;
      const linhas = dados.texto.replace(/\*/g, "").split("\n");
      baixarPdf("resumo-willpdv.pdf", linhas, []);
    });
    $("seletor-dia").addEventListener("change", (e) => mudarDia(e.target.value));
    $("seletor-movimento").addEventListener("change", (e) => {
      estado.diaMovimento = e.target.value || null;
      if (estado.resumo) renderizarMovimento(estado.resumo);
    });
    document.querySelectorAll(".filtro").forEach((b) => b.addEventListener("click", () => {
      const grupo = b.dataset.grupo;
      const periodo = b.dataset.periodo;
      if (grupo === "produtos") {
        estado.periodoProdutos = periodo;
        marcarFiltro("produtos", periodo);
        if (estado.token) carregarRanking();
      } else if (grupo === "comissoes") {
        estado.periodoComissoes = periodo;
        marcarFiltro("comissoes", periodo);
        if (estado.resumo) renderizarComissoes(estado.resumo);
      }
    }));
    marcarFiltro("produtos", estado.periodoProdutos);
    marcarFiltro("comissoes", estado.periodoComissoes);
    marcarAtalho(estado.atalhoPeriodo);
    document.querySelectorAll("[data-atalho]").forEach((b) => b.addEventListener("click", () => {
      estado.atalhoPeriodo = b.dataset.atalho;
      marcarAtalho(estado.atalhoPeriodo);
      sincronizarDatasDoAtalho();
      if (estado.token) carregarPeriodo();
    }));
    document.querySelectorAll("[data-lucro]").forEach((b) => b.addEventListener("click", () => {
      estado.atalhoLucro = b.dataset.lucro;
      document.querySelectorAll("[data-lucro]").forEach((x) => x.classList.toggle("ativa", x === b));
      if (estado.token) carregarLucro();
    }));
    const botaoLucro = $("botao-lucro");
    if (botaoLucro) botaoLucro.addEventListener("click", () => {
      estado.atalhoLucro = null;
      document.querySelectorAll("[data-lucro]").forEach((x) => x.classList.remove("ativa"));
      estado.lucroDe = $("lucro-de").value;
      estado.lucroAte = $("lucro-ate").value;
      carregarLucro();
    });
    async function baixarDaAba(formato) {
      const nota = $("nota-gestao");
      try {
        await baixarRelatorio(formato, $("exportar-relatorio-tipo").value, estado.lucroDe, estado.lucroAte);
      } catch (e) {
        if (e.status === 401) return;
        if (nota) { nota.hidden = false; nota.textContent = e.message || "Não consegui baixar."; }
      }
    }
    const csvRel = $("exportar-relatorio-csv");
    const xlsxRel = $("exportar-relatorio-xlsx");
    if (csvRel) csvRel.addEventListener("click", () => baixarDaAba("csv"));
    if (xlsxRel) xlsxRel.addEventListener("click", () => baixarDaAba("xlsx"));
    const csvRede = $("exportar-rede-csv");
    if (csvRede) csvRede.addEventListener("click", async () => {
      const erro = $("erro-rede");
      try {
        await baixarRelatorio("csv", "rede", estado.redeDe, estado.redeAte);
      } catch (e) {
        if (e.status === 401) return;
        if (erro) { erro.hidden = false; erro.textContent = e.message || "Não consegui baixar o comparativo."; }
      }
    });
    $("botao-periodo").addEventListener("click", () => {
      estado.atalhoPeriodo = null;
      marcarAtalho(null);
      estado.periodoDe = $("periodo-de").value;
      estado.periodoAte = $("periodo-ate").value;
      carregarPeriodo();
    });
    $("data-dia").addEventListener("change", (e) => { if (e.target.value) mudarDia(e.target.value); });
    $("pag-anterior").addEventListener("click", () => {
      if (estado.paginaVendas > 1) { estado.paginaVendas--; carregarVendas(); }
    });
    $("pag-proxima").addEventListener("click", () => { estado.paginaVendas++; carregarVendas(); });
    document.querySelectorAll(".aba-botao").forEach((b) => b.addEventListener("click", () => trocarAba(b.dataset.aba)));

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        if (estado.token && !estado.aguardandoFlush) atualizarTudo();
        agendarAtualizacao();
      } else if (estado._timer) {
        clearTimeout(estado._timer);
        estado._timer = null;
      }
    });
    window.addEventListener("online", () => {
      if (estado.token && document.visibilityState === "visible") atualizarTudo();
    });
    window.addEventListener("offline", () => {
      const cache = lerCache("resumo:" + (estado.dia || "atual"));
      if (cache && estado.token) mostrarOffline(cache.salvo_em);
    });
    function agendarAtualizacao() {
      if (estado._timer) clearTimeout(estado._timer);
      if (document.visibilityState !== "visible") {
        estado._timer = null;
        return;
      }
      estado._timer = setTimeout(atualizarAutomaticamente, INTERVALO_AUTO_MS);
    }
    async function atualizarAutomaticamente() {
      try {
        if (document.visibilityState === "visible" && estado.token && !estado.aguardandoFlush) await atualizarTudo();
      } finally {
        agendarAtualizacao();
      }
    }
    agendarAtualizacao();

    configurarImportacao();
    configurarInstalacao();
    registrarServiceWorker();

    const grupoUrl = new URLSearchParams(location.search).get("grupo");
    if (grupoUrl) aplicarAppDaRede(grupoUrl, null);
    if (grupoUrl && $("campo-loja") && !$("campo-loja").value) {
      $("campo-loja").value = grupoUrl;
      const rotulo = document.querySelector("label[for=campo-loja]");
      if (rotulo) rotulo.textContent = "Rede";
    }
    try { localStorage.removeItem(PREFIXO + "grupo"); sessionStorage.removeItem(PREFIXO + "redeToken"); } catch (_) { /* navegador privado */ }
    const formSenha = $("form-senha-rede");
    if (formSenha) formSenha.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const erro = $("erro-senha-rede");
      erro.hidden = true;
      try {
        await chamarApi("/grupo/senha", { metodo: "POST", corpo: {
          senha_atual: $("senha-atual").value, senha_nova: $("senha-nova").value } });
        abrirInicioDaRede();
      } catch (e) {
        erro.textContent = e.message;
        erro.hidden = false;
      }
    });
    const botaoRede = $("botao-rede-ver");
    if (botaoRede) botaoRede.addEventListener("click", () => {
      estado.atalhoRede = "personalizado";
      estado.redeDe = $("rede-de").value;
      estado.redeAte = $("rede-ate").value;
      document.querySelectorAll("[data-rede]").forEach((b) => b.classList.remove("ativa"));
      atualizarRede();
    });
    document.querySelectorAll("[data-rede]").forEach((b) => b.addEventListener("click", () => {
      estado.atalhoRede = b.dataset.rede;
      document.querySelectorAll("[data-rede]").forEach((x) => x.classList.toggle("ativa", x === b));
      atualizarRede();
    }));
    const sairRede = $("sair-rede");
    if (sairRede) sairRede.addEventListener("click", () => encerrarSessao(true));
    $("seletor-loja-rede").addEventListener("change", (e) => trocarDeLojaNaRede(e.target.value));
    $("form-relatorio-diario").addEventListener("submit", salvarRelatorioDiario);
    $("relatorio-agora").addEventListener("click", enviarRelatorioAgora);
    $("seletor-loja-resumo").addEventListener("change", (e) => { if (e.target.value) trocarDeLojaNaRede(e.target.value); });
    $("botao-atualizar-rede").addEventListener("click", atualizarRede);
    const linkSenha = new URLSearchParams(location.search).get("senha");
    if (linkSenha) abrirLinkDeSenha(linkSenha);         // link do e-mail: criar senha antes de qualquer coisa
    else retomarPeloCookie();
  }

  async function retomarPeloCookie() {
    let dados = null;
    try { dados = await chamarApi("/eu", { semToken: true }); }
    catch (_) { dados = null; }
    if (!dados) {
      mostrarLogin();
      return;
    }
    estado.token = SESSAO_COOKIE;
    if (dados.expira_em) gravarArmazenamento(CHAVE_EXPIRA, dados.expira_em);
    if (dados.grupo && !dados.loja) {
      estado.modo = "rede";
      estado.grupo = dados.grupo;
      estado.loja = null;
      guardarRede(dados.grupo, dados.expira_em);
      if (dados.deve_trocar_senha) {
        $("tela-login").hidden = false;
        $("form-login").hidden = true;
        $("form-senha-rede").hidden = false;
        $("tela-app").hidden = true;
        $("tela-rede").hidden = true;
        return;
      }
      abrirInicioDaRede();
      return;
    }
    estado.modo = "loja";
    estado.loja = dados.loja || estado.loja;
    if (dados.tem_rede && dados.rede) guardarRede(dados.rede, dados.expira_em);
    else if (!dados.tem_rede) esquecerRede();
    mostrarApp();
    atualizarTudo();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
