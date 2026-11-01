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
  const INTERVALO_AUTO_MS = 30000;
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
    loja: null,
    aba: "hoje",
    dia: null,            // null = dia operacional atual da loja
    resumo: null,
    historico: null,
    ranking: null,
    periodoProdutos: "hoje",
    periodoComissoes: "hoje",
    diaMovimento: null,
    vendas: null,
    paginaVendas: 1,
    carregando: false,
    ultimaAtualizacao: 0,
    eventoInstalacao: null,
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
    const cabecalhos = { Accept: "application/json" };
    if (opcoes.corpo !== undefined) cabecalhos["Content-Type"] = "application/json";
    if (estado.token && !opcoes.semToken) cabecalhos.Authorization = "Bearer " + estado.token;

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
    const loja = estado.loja && estado.loja.chave ? estado.loja.chave : lerArmazenamento(CHAVE_LOJA + ".chave");
    if (loja && !$("campo-loja").value) $("campo-loja").value = loja;
    $("campo-senha").value = "";
    setTimeout(() => (loja ? $("campo-senha") : $("campo-loja")).focus(), 50);
  }

  function mostrarApp() {
    $("tela-login").hidden = true;
    $("tela-app").hidden = false;
    $("nome-loja").textContent = estado.loja && estado.loja.nome ? estado.loja.nome : (estado.loja && estado.loja.chave) || "Loja";
  }

  function encerrarSessao(avisarServidor) {
    const tokenAnterior = estado.token;
    const chaveLoja = estado.loja && estado.loja.chave;
    if (avisarServidor && tokenAnterior) {
      fetch(API_BASE + "/sair", {
        method: "POST",
        headers: { Authorization: "Bearer " + tokenAnterior },
        keepalive: true,
      }).catch(() => { /* já estamos saindo */ });
    }
    estado.token = null;
    estado.loja = null;
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

  async function entrar(evento) {
    evento.preventDefault();
    const loja = $("campo-loja").value.trim().toUpperCase();
    const senha = $("campo-senha").value;
    const erro = $("erro-login");
    erro.hidden = true;

    if (!loja || !senha) {
      erro.textContent = "Informe a loja e a senha.";
      erro.hidden = false;
      return;
    }

    const botao = $("botao-entrar");
    botao.disabled = true;
    botao.textContent = "Entrando…";
    try {
      const dados = await chamarApi("/login", { metodo: "POST", corpo: { loja, senha }, semToken: true });
      estado.token = dados.token;
      estado.loja = dados.loja || { chave: loja, nome: loja };
      gravarArmazenamento(CHAVE_TOKEN, estado.token);
      gravarArmazenamento(CHAVE_LOJA, JSON.stringify(estado.loja));
      gravarArmazenamento(CHAVE_LOJA + ".chave", estado.loja.chave || loja);
      if (dados.expira_em) gravarArmazenamento(CHAVE_EXPIRA, dados.expira_em);
      estado.dia = null;
      estado.paginaVendas = 1;
      mostrarApp();
      atualizarTudo();
    } catch (e) {
      erro.textContent = e instanceof ErroRede ? "Sem conexão com o servidor. Verifique a internet." : e.message;
      erro.hidden = false;
    } finally {
      botao.disabled = false;
      botao.textContent = "Entrar";
    }
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

  async function atualizarTudo() {
    if (!sessaoValida()) {
      encerrarSessao(false);
      return;
    }
    if (estado.carregando) return;
    estado.carregando = true;
    $("botao-atualizar").classList.add("girando");
    $("faixa-offline").hidden = true;
    $("faixa-erro").hidden = true;
    try {
      const tarefas = [carregarResumo(), carregarHistorico(), carregarRanking()];
      if (estado.aba === "vendas") tarefas.push(carregarVendas());
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

  function renderizarResumo(r) {
    const v = r.vendas || {};
    const loja = r.loja || estado.loja;
    if (loja && loja.nome) $("nome-loja").textContent = loja.nome;

    // Status de atualização do PDV (relógio da loja no último envio).
    const status = $("status-atualizacao");
    limpar(status);
    if (r.atualizado_em) {
      const nCaixas = Array.isArray(r.caixas) ? r.caixas.length : 0;
      status.append("Atualizado às " + formatarHora(r.atualizado_em) +
        (r.atraso_min !== null && r.atraso_min !== undefined ? " (há " + formatarAtraso(r.atraso_min) + ")" : ""));
      // "· 3 caixas" não parte no meio: se faltar espaço, vai inteiro para a linha de baixo.
      if (nCaixas > 1) status.append(el("span", { class: "sem-quebra", text: " · " + nCaixas + " caixas" }));
    } else {
      status.append("PDV ainda não enviou dados");
    }
    mostrarAtraso(r.atraso_min);

    $("v-faturamento").textContent = formatarCentavos(v.faturamento_cent);
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
      const mostrar = i === 0 || i === dias.length - 1 || (d.dia && Number(d.dia.slice(8, 10)) % 5 === 0);
      return {
        valor,
        rotulo: mostrar && d.dia ? d.dia.slice(8, 10) : "",
        destaque: d.dia === diaAtual,
        titulo: formatarDiaCurto(d.dia) + ": " + formatarCentavos(valor) + " em " + formatarInteiro(d.quantidade) +
          " venda(s)" + (d.canceladas ? ", " + formatarInteiro(d.canceladas) + " cancelada(s)" : ""),
      };
    });
    const tem = desenharGrafico(alvo, pontos, "Faturamento dos últimos 30 dias", "detalhe-dias");
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
    const tem = desenharGrafico(alvo, pontos, "Faturamento dos últimos 12 meses", "detalhe-meses");
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

  function renderizarComandas(r) {
    const nota = $("nota-comandas");
    const lista = $("lista-comandas");
    limpar(lista);
    const comandas = Array.isArray(r.comandas) ? r.comandas : [];
    if (!r.comandas_sincronizadas) {
      nota.hidden = false;
      nota.textContent = r.atualizado_em
        ? "Atualize o PDV da loja para ver as comandas abertas e as comissões."
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
    for (const c of comandas) {
      const devendo = c.situacao === "devendo";
      lista.append(el("li", null,
        el("div", { class: "nome" },
          el("span", null,
            el("strong", { text: c.rotulo || ("Comanda " + c.numero) }),
            c.garota ? el("span", { class: "etiqueta etiqueta-garota", text: "Comissão lançada" }) : null
          ),
          el("span", { class: "sec", text: (c.aberta_txt ? "Aberta " + c.aberta_txt : "Aberta") +
            (c.caixa ? " · " + c.caixa : "") + (devendo ? "" : " · nada a cobrar") })
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
      itens.length ? el("ul", { class: "lista" }, itens) : el("p", { class: "vazio", text: "Nenhum produto abaixo do mínimo." })
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

  function configurarInstalacao() {
    const botao = $("botao-instalar");
    window.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault();
      estado.eventoInstalacao = e;
      botao.hidden = false;
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
  // Inicialização
  // ------------------------------------------------------------------

  function iniciar() {
    estado.token = lerArmazenamento(CHAVE_TOKEN);
    try { estado.loja = JSON.parse(lerArmazenamento(CHAVE_LOJA) || "null"); } catch (_) { estado.loja = null; }

    $("form-login").addEventListener("submit", entrar);
    $("botao-sair").addEventListener("click", () => encerrarSessao(true));
    $("botao-atualizar").addEventListener("click", () => atualizarTudo());
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
    $("data-dia").addEventListener("change", (e) => { if (e.target.value) mudarDia(e.target.value); });
    $("pag-anterior").addEventListener("click", () => {
      if (estado.paginaVendas > 1) { estado.paginaVendas--; carregarVendas(); }
    });
    $("pag-proxima").addEventListener("click", () => { estado.paginaVendas++; carregarVendas(); });
    document.querySelectorAll(".aba-botao").forEach((b) => b.addEventListener("click", () => trocarAba(b.dataset.aba)));

    document.addEventListener("visibilitychange", atualizarSeAntigo);
    window.addEventListener("focus", atualizarSeAntigo);
    window.addEventListener("online", () => { if (estado.token) atualizarTudo(); });
    window.addEventListener("offline", () => {
      const cache = lerCache("resumo:" + (estado.dia || "atual"));
      if (cache && estado.token) mostrarOffline(cache.salvo_em);
    });
    async function atualizarAutomaticamente() {
      try {
        if (document.visibilityState === "visible" && estado.token) await atualizarTudo();
      } finally {
        const intervalo = estado.resumo && estado.resumo.atualizacao_seg === 5 ? 5000 : INTERVALO_AUTO_MS;
        setTimeout(atualizarAutomaticamente, intervalo);
      }
    }
    setTimeout(atualizarAutomaticamente, 5000);

    configurarInstalacao();
    registrarServiceWorker();

    if (sessaoValida()) {
      mostrarApp();
      atualizarTudo();
    } else {
      if (estado.token) encerrarSessao(false);
      else mostrarLogin();
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
