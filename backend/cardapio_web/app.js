/* Cardápio digital. O preço chega em centavos. Na boate é só consulta; no Will Adega com o pedido online ligado
   (dados.pedido), cada produto ganha o botão de adicionar e o carrinho envia o pedido para o caixa da loja. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  function reais(cent) {
    const n = Math.round(Number(cent) || 0);
    const abs = Math.abs(n);
    const texto = String(Math.floor(abs / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ".") +
      "," + String(abs % 100).padStart(2, "0");
    return (n < 0 ? "-R$ " : "R$ ") + texto;
  }

  function normalizar(texto) {
    return (texto || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  }

  function selo(promocao) {
    if (promocao === "horário") return "Happy hour";
    if (promocao) return "Promoção";
    return "";
  }

  function el(tag, props, ...filhos) {
    const no = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === "class") no.className = v;
        else if (k === "text") no.textContent = v;
        else no.setAttribute(k, v === true ? "" : v);
      }
    }
    for (const filho of filhos) {
      if (filho) no.append(filho);
    }
    return no;
  }

  const carrinho = new Map();     // codigo|temperatura -> {codigo, nome, preco_cent, qtd, temperatura, fracionado, retornavel, cascos}
  let pedidoCfg = null;
  let mesaPedido = null;
  let lojaChave = "";
  let cardapioDados = null;

  function precoDe(p) {
    const base = p._temp === "gelada" && p.preco_gelada_cent ? p.preco_gelada_cent : p.preco_cent;
    return base + (p._escolhas || []).reduce((total, o) => total + o.preco_cent, 0);
  }

  function tempDe(p) {
    return p._temp === "gelada" && p.preco_gelada_cent ? "gelada" : "natural";
  }

  function chaveDe(p) {
    return p.codigo + "|" + tempDe(p) + "|" + (p._escolhas || []).map(o => o.id).sort().join(",");
  }

  function totalCarrinho() {
    let itens = 0, cent = 0;
    for (const i of carrinho.values()) { itens += i.qtd; cent += i.qtd * i.preco_cent; }
    return { itens, cent };
  }

  function mudar(produto, passo) {
    const chave = chaveDe(produto);
    const atual = carrinho.get(chave) || { codigo: produto.codigo, nome: produto.nome,
      preco_cent: precoDe(produto), qtd: 0, temperatura: tempDe(produto),
      fracionado: !!produto.fracionado, retornavel: !!produto.retornavel, cascos: 0,
      opcoes: produto._escolhas || [], chave };
    const delta = produto.fracionado ? passo * 0.1 : passo;
    atual.qtd = Math.max(0, Math.min(99, Math.round((atual.qtd + delta) * 10000) / 10000));
    if (atual.qtd) carrinho.set(chave, atual); else carrinho.delete(chave);
    atualizarBarra();
    const marcador = document.querySelector('[data-qtd="' + chave + '"]');
    if (marcador) marcador.textContent = atual.qtd ? String(atual.qtd) : "";
  }

  function atualizarBarra() {
    const { itens, cent } = totalCarrinho();
    const barra = $("barra-carrinho");
    barra.hidden = !itens;
    $("barra-texto").textContent = itens + (itens === 1 ? " item" : " itens") + " · " + reais(cent);
  }

  function escolherOpcoes(p, confirmar) {
    if (!(p.grupos_opcoes || []).length) { confirmar(); return; }
    const dialogo = el("dialog", { "aria-label": "Opções de " + p.nome });
    dialogo.append(el("h2", { text: p.nome }));
    const campos = [];
    for (const g of p.grupos_opcoes) {
      const quadro = el("fieldset");
      quadro.append(el("legend", { text: g.nome + " — de " + g.minimo + " a " + g.maximo }));
      for (const o of g.opcoes) {
        const campo = el("input", { type: "checkbox" });
        campo.checked = (p._escolhas || []).some(e => e.id === o.id);
        campos.push({ g, o, campo });
        quadro.append(el("label", null, campo, document.createTextNode(o.nome + " · + " + reais(o.preco_cent))));
        quadro.append(el("br"));
      }
      dialogo.append(quadro);
    }
    const erro = el("p", { role: "alert" });
    const cancelar = el("button", { type: "button", text: "Cancelar" });
    const aceitar = el("button", { type: "button", text: "Adicionar ao pedido" });
    const fechar = () => { dialogo.close(); dialogo.remove(); };
    cancelar.addEventListener("click", fechar);
    dialogo.addEventListener("cancel", evento => { evento.preventDefault(); fechar(); });
    aceitar.addEventListener("click", () => {
      for (const g of p.grupos_opcoes) {
        const n = campos.filter(c => c.g.id === g.id && c.campo.checked).length;
        if (n < g.minimo || n > g.maximo) { erro.textContent = g.nome + ": confira a quantidade de escolhas."; return; }
      }
      p._escolhas = campos.filter(c => c.campo.checked).map(c => c.o);
      fechar();
      confirmar();
    });
    dialogo.append(erro, cancelar, aceitar);
    document.body.append(dialogo);
    dialogo.showModal();
  }

  function botoesPedido(p) {
    if (!pedidoCfg || !p.codigo) return null;
    const qtd = carrinho.get(chaveDe(p));
    const menos = el("button", { class: "mais", type: "button", "aria-label": "Tirar " + p.nome, text: "−" });
    const mais = el("button", { class: "mais", type: "button", "aria-label": "Adicionar " + p.nome, text: "+" });
    menos.addEventListener("click", () => mudar(p, -1));
    mais.addEventListener("click", () => escolherOpcoes(p, () => mudar(p, 1)));
    const pedacos = [menos, el("span", { "data-qtd": chaveDe(p), text: qtd ? String(qtd.qtd) : "" }), mais];
    if (p.preco_gelada_cent) {
      const gel = el("button", { class: "mais", type: "button",
        text: tempDe(p) === "gelada" ? "Gelada" : "Natural",
        "aria-label": "Temperatura de " + p.nome });
      gel.addEventListener("click", () => {
        p._temp = tempDe(p) === "gelada" ? "natural" : "gelada";
        if (cardapioDados) desenhar(cardapioDados, $("campo-busca").value);
      });
      pedacos.push(gel);
    }
    return el("div", { class: "qtd" }, ...pedacos);
  }

  function desenhar(dados, filtro) {
    const alvo = $("conteudo");
    alvo.replaceChildren();
    const busca = normalizar(filtro);
    let achou = false;
    for (const grupo of dados.grupos || []) {
      const subs = [];
      for (const sub of grupo.subgrupos || []) {
        const itens = (sub.produtos || []).filter((p) => !busca || normalizar(p.nome).includes(busca) ||
          normalizar(p.descricao).includes(busca));
        if (!itens.length) continue;
        achou = true;
        const lista = el("div");
        if (sub.nome) lista.append(el("h3", { class: "sub", text: sub.nome }));
        for (const p of itens) {
          const marca = selo(p.promocao);
          lista.append(el("article", { class: "item" },
            p.foto ? el("img", { src: p.foto, alt: "" }) : null,
            el("div", null,
              el("div", { class: "nome", text: p.nome }),
              p.descricao ? el("p", { class: "desc", text: p.descricao }) : null
            ),
            el("div", { class: "preco" },
              p.preco_de_cent ? el("span", { class: "de", text: reais(p.preco_de_cent) }) : null,
              el("strong", { text: reais(precoDe(p)) }),
              marca ? el("span", { class: "selo", text: marca }) : null,
              botoesPedido(p)
            )
          ));
        }
        subs.push(lista);
      }
      if (!subs.length) continue;
      alvo.append(el("h2", { class: "grupo", text: grupo.nome }));
      for (const sub of subs) alvo.append(sub);
    }
    if (!achou) {
      alvo.append(el("p", { class: "estado", text: busca ? "Nada com esse nome." : "Nada no cardápio agora." }));
    }
  }

  function params() {
    const q = new URLSearchParams(location.search);
    return { loja: (q.get("loja") || "").trim(), mesa: (q.get("mesa") || "").trim() };
  }

  async function carregar() {
    const { loja, mesa } = params();
    const estado = $("estado");
    if (!loja) {
      estado.textContent = "Este cardápio precisa do QR da mesa.";
      return;
    }
    const consulta = "/v1/cardapio?loja=" + encodeURIComponent(loja) +
      (mesa ? "&mesa=" + encodeURIComponent(mesa) : "");
    let dados;
    try {
      const r = await fetch(consulta, { cache: "no-store", headers: { "X-PDV-Leitura": "1" } });
      const corpo = await r.json().catch(() => ({}));
      if (!r.ok) {
        estado.textContent = corpo.detail || "Não foi possível abrir o cardápio.";
        return;
      }
      dados = corpo;
    } catch (_) {
      estado.textContent = "Sem conexão. Tente de novo em instantes.";
      return;
    }
    const nome = (dados.loja && dados.loja.nome) || "Cardápio";
    $("loja").textContent = nome;
    document.title = nome;
    if (dados.mesa) {
      $("mesa").hidden = false;
      $("mesa").textContent = "Mesa " + dados.mesa;
    }
    if (dados.logo) {
      $("logo").hidden = false;
      $("logo").src = dados.logo;
      $("logo").alt = nome;
    }
    lojaChave = loja;
    cardapioDados = dados;
    if (dados.pedido) prepararPedido(dados.pedido);
    acompanhar();
    desenhar(dados, "");
    $("campo-busca").addEventListener("input", (e) => desenhar(dados, e.target.value));
  }

  // ------------------------------------------------------------------ pedido online (Will Adega)
  function guardado(chave, valor) {
    try {
      if (valor === undefined) return JSON.parse(localStorage.getItem(chave) || "null");
      localStorage.setItem(chave, JSON.stringify(valor));
    } catch (_) { /* navegador sem armazenamento: só não lembra */ }
    return null;
  }

  function prepararPedido(cfg) {
    pedidoCfg = cfg;
    const mesa = Number(params().mesa);
    if (mesa && cfg.mesas) {
      if (!Number.isInteger(mesa) || mesa < 1 || mesa > cfg.mesas) {
        pedidoCfg = null;
        $("aviso-topo").textContent = "Mesa fora da configuração da loja. Peça ajuda ao atendente.";
        return;
      }
      mesaPedido = mesa;
      $("f-retirada").checked = true;
      $("f-endereco").required = false;
    }
    $("aviso-topo").textContent = "Peça por aqui: o pedido vai direto para a loja.";
    const bairro = $("f-bairro");
    for (const b of cfg.bairros || []) {
      bairro.append(el("option", { value: b.nome, text: b.nome + " · entrega " + reais(b.taxa_cent) }));
    }
    bairro.append(el("option", { value: "", text: "Outro bairro · entrega " + reais(cfg.taxa_padrao_cent) }));
    for (const pg of cfg.pagamentos || []) {
      $("f-pagamento").append(el("option", { value: pg.chave, text: pg.nome }));
    }
    $("linha-retirada").hidden = !!mesaPedido || !cfg.retirada;
    if (mesaPedido) {
      $("aviso-topo").textContent = "Pedido para a mesa " + mesaPedido + ". A equipe confirma antes de lançar na conta.";
      $("f-pagamento").replaceChildren(el("option", { value: "na_mesa", text: "Acertar a conta no caixa" }));
    }
    const salvo = guardado("cliente") || {};
    for (const campo of ["nome", "telefone", "endereco"]) if (salvo[campo]) $("f-" + campo).value = salvo[campo];
    $("barra-carrinho").addEventListener("click", abrirCarrinho);
    $("fechar-carrinho").addEventListener("click", () => $("carrinho").close());
    $("f-retirada").addEventListener("change", resumoCarrinho);
    $("f-bairro").addEventListener("change", resumoCarrinho);
    $("f-pagamento").addEventListener("change", resumoCarrinho);
    $("form-pedido").addEventListener("submit", enviar);
  }

  function taxaEscolhida() {
    if ($("f-retirada").checked) return 0;
    const nome = $("f-bairro").value;
    const b = (pedidoCfg.bairros || []).find((x) => x.nome === nome);
    return b ? b.taxa_cent : pedidoCfg.taxa_padrao_cent;
  }

  function resumoCarrinho() {
    const lista = $("itens-carrinho");
    lista.replaceChildren();
    for (const i of carrinho.values()) {
      const nome = i.qtd + "x " + i.nome + (i.temperatura === "gelada" ? " (gelada)" : "");
      const linha = el("li", null, el("span", { text: nome }), el("strong", { text: reais(Math.round(i.qtd * i.preco_cent)) }));
      if ((i.opcoes || []).length) linha.append(el("span", { text: i.opcoes.map(o => o.nome).join(", ") }));
      const remover = el("button", { type: "button", text: "Remover", "aria-label": "Remover " + i.nome });
      remover.addEventListener("click", () => { carrinho.delete(i.chave); atualizarBarra(); resumoCarrinho(); });
      linha.append(remover);
      if (i.fracionado) {
        const campo = el("input", { type: "text", inputmode: "decimal", value: String(i.qtd), maxlength: "8",
          "aria-label": "Quantidade de " + i.nome });
        campo.addEventListener("change", () => {
          const n = parseFloat(String(campo.value).replace(",", "."));
          i.qtd = !n || n <= 0 ? 0 : Math.min(99, Math.round(n * 10000) / 10000);
          if (!i.qtd) carrinho.delete(i.chave);
          atualizarBarra();
          resumoCarrinho();
        });
        linha.append(campo);
      }
      if (i.retornavel) {
        const casco = el("input", { type: "text", inputmode: "numeric", value: String(i.cascos || ""),
          maxlength: "3", placeholder: "cascos", "aria-label": "Cascos devolvidos de " + i.nome });
        casco.addEventListener("change", () => { i.cascos = Math.max(0, parseInt(casco.value, 10) || 0); });
        linha.append(casco);
      }
      lista.append(linha);
    }
    const retirada = $("f-retirada").checked;
    $("bloco-entrega").hidden = retirada;
    $("linha-troco").hidden = $("f-pagamento").value !== "dinheiro";
    const { cent } = totalCarrinho();
    const taxa = taxaEscolhida();
    $("total-carrinho").textContent = (retirada ? "" : "Entrega " + reais(taxa) + " · ") + "Total " + reais(cent + taxa);
    const minimo = pedidoCfg.minimo_cent || 0;
    const bairroOutro = !retirada && !$("f-bairro").value;
    $("aviso-minimo").hidden = cent >= minimo && !bairroOutro;
    $("aviso-minimo").textContent = cent < minimo
      ? "Pedido mínimo de " + reais(minimo) + "."
      : "Bairro não cadastrado: a entrega usa a taxa padrão.";
  }

  function abrirCarrinho() {
    $("resultado").hidden = true;
    $("form-pedido").hidden = false;
    $("erro-pedido").textContent = "";
    resumoCarrinho();
    $("carrinho").showModal();
  }

  function centavos(texto) {
    const limpo = String(texto || "").replace(/[^\d,]/g, "").replace(",", ".");
    return limpo ? Math.round(parseFloat(limpo) * 100) || 0 : 0;
  }

  async function enviar(evento) {
    evento.preventDefault();
    const botao = $("enviar-pedido");
    const retirada = $("f-retirada").checked;
    const corpo = {
      ...(mesaPedido ? { mesa: mesaPedido } : {}),
      loja: lojaChave, nome: $("f-nome").value, telefone: $("f-telefone").value, retirada,
      endereco: retirada ? "" : $("f-endereco").value, bairro: retirada ? "" : $("f-bairro").value,
      pagamento: $("f-pagamento").value, troco_para_cent: centavos($("f-troco").value),
      observacao: $("f-obs").value,
      itens: [...carrinho.values()].map((i) => ({ codigo: i.codigo, qtd: i.qtd,
        temperatura: i.temperatura || "natural", cascos: i.cascos || 0, opcoes_ids: (i.opcoes || []).map(o => o.id) })),
    };
    botao.disabled = true;
    $("erro-pedido").textContent = "";
    try {
      const r = await fetch("/v1/cardapio/pedido", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(corpo) });
      const resposta = await r.json().catch(() => ({}));
      if (!r.ok) {
        $("erro-pedido").textContent = resposta.detail || "Não foi possível enviar o pedido.";
        return;
      }
      guardado("cliente", { nome: corpo.nome, telefone: corpo.telefone, endereco: corpo.endereco });
      guardado("ultimo-pedido", { loja: lojaChave, numero: resposta.numero, telefone: corpo.telefone });
      carrinho.clear();
      atualizarBarra();
      document.querySelectorAll("[data-qtd]").forEach((n) => { n.textContent = ""; });
      $("form-pedido").hidden = true;
      $("resultado").hidden = false;
      $("resultado-texto").textContent = "Pedido #" + resposta.numero + " enviado! Total " + reais(resposta.total_cent) +
        ". A loja vai confirmar.";
      $("abrir-whatsapp").href = resposta.whatsapp_url;
      acompanhar();
    } catch (_) {
      $("erro-pedido").textContent = "Sem conexão. Tente de novo.";
    } finally {
      botao.disabled = false;
    }
  }

  let timerSituacao = null;
  async function acompanhar() {
    const ultimo = guardado("ultimo-pedido");
    if (!ultimo || ultimo.loja !== lojaChave) return;
    const faixa = $("situacao-pedido");
    try {
      const r = await fetch("/v1/cardapio/pedido?loja=" + encodeURIComponent(ultimo.loja) + "&numero=" + ultimo.numero +
        "&telefone=" + encodeURIComponent(ultimo.telefone), { cache: "no-store" });
      if (!r.ok) return;
      const s = await r.json();
      const textos = {
        novo: "aguardando a loja confirmar", aceito: "confirmado pela loja",
        saiu: "saiu para entrega", entregue: "entregue", recusado: "recusado", cancelado: "cancelado pela loja",
      };
      faixa.hidden = false;
      faixa.textContent = "Seu pedido #" + s.numero + ": " + (textos[s.situacao] || s.situacao) +
        (s.motivo ? " (" + s.motivo + ")" : "");
      clearTimeout(timerSituacao);
      if (s.situacao === "novo" || s.situacao === "aceito" || s.situacao === "saiu") {
        timerSituacao = setTimeout(acompanhar, 20000);
      }
    } catch (_) { /* sem rede: tenta na próxima abertura */ }
  }

  function registrar() {
    if (!("serviceWorker" in navigator)) return;
    const escopo = location.pathname.startsWith("/cardapio/") ? "/cardapio/" : new URL("./", location.href).pathname;
    navigator.serviceWorker.register("sw.js", { scope: escopo }).catch(() => {});
  }

  registrar();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", carregar);
  else carregar();
})();
