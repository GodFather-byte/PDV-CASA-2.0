/* Cardápio digital: só consulta. O preço chega em centavos. */
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
              el("strong", { text: reais(p.preco_cent) }),
              marca ? el("span", { class: "selo", text: marca }) : null
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
      const r = await fetch(consulta, { cache: "no-store" });
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
    desenhar(dados, "");
    $("campo-busca").addEventListener("input", (e) => desenhar(dados, e.target.value));
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
