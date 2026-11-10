/* Cozinha local: nenhuma fila fica operável com leitura antiga ou sem sessão. */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const tv = new URLSearchParams(location.search).get("tv") === "1";
  let timer = null, ocupado = false;
  document.body.classList.toggle("tv", tv);
  function no(tag, texto, classe) {
    const n = document.createElement(tag);
    n.textContent = texto;
    if (classe) n.className = classe;
    return n;
  }
  async function api(caminho, corpo) {
    const controlador = new AbortController();
    const limite = setTimeout(() => controlador.abort(), 10000);
    try {
      const r = await fetch("api/" + caminho, corpo === undefined
        ? { cache: "no-store", signal: controlador.signal }
        : { method: "POST", headers: { "Content-Type": "application/json", "X-Cozinha-Acao": "1" },
            body: JSON.stringify(corpo), signal: controlador.signal });
      const dados = await r.json().catch(() => ({}));
      if (!r.ok) throw Object.assign(new Error(dados.erro || "Não foi possível consultar o caixa."), { status: r.status });
      return dados;
    } finally { clearTimeout(limite); }
  }
  function entrada(erro) {
    clearTimeout(timer);
    $("login").hidden = false;
    $("painel").hidden = true;
    $("sair").hidden = true;
    $("fila").replaceChildren();
    $("aviso").textContent = erro || "";
  }
  function desatualizar(erro) {
    document.body.classList.add("desatualizado");
    for (const b of $("fila").querySelectorAll("button")) b.disabled = true;
    $("aviso").textContent = erro + " A fila exibida é da última leitura; aguarde a reconexão.";
  }
  async function alterar(item) {
    if (ocupado) return;
    ocupado = true;
    for (const b of $("fila").querySelectorAll("button")) b.disabled = true;
    try {
      await api("preparo", { item_id: item.id, de: item.status_preparo,
        para: item.status_preparo === "pendente" ? "em_preparo" : "entregue" });
    } catch (e) {
      $("aviso").textContent = e.message;
    } finally {
      ocupado = false;
      await atualizar();
    }
  }
  async function atualizar() {
    clearTimeout(timer);
    if (ocupado) return;
    ocupado = true;
    try {
      const setor = $("setor").value;
      const dados = await api("fila" + (setor ? "?setor=" + encodeURIComponent(setor) : ""));
      document.body.classList.remove("desatualizado");
      $("login").hidden = true;
      $("painel").hidden = false;
      $("sair").hidden = false;
      $("modo").textContent = dados.modo === "tv" ? "TV — somente leitura" : "Operação da cozinha";
      $("atualizado").textContent = "Última leitura: " + dados.momento;
      $("aviso").textContent = dados.total > dados.itens.length ? "Exibindo os primeiros " + dados.itens.length + " de " + dados.total + " itens. Filtre por setor." : "";
      $("setor").replaceChildren(new Option("Todos", ""));
      for (const s of dados.setores) $("setor").append(new Option(s.nome, String(s.id)));
      $("setor").value = setor;
      $("fila").replaceChildren();
      $("vazio").hidden = !!dados.itens.length;
      for (const i of dados.itens) {
        const artigo = document.createElement("article");
        artigo.className = i.status_preparo;
        artigo.append(no("h2", i.posicao_rotulo), no("p", i.status_preparo === "pendente" ? "Pendente" : "Em preparo"));
        artigo.append(no("h3", String(i.quantidade).replace(".", ",") + " × " + i.produto));
        if (i.observacao) artigo.append(no("p", i.observacao, "obs"));
        artigo.append(no("p", i.minutos + " min", "idade"));
        if (dados.modo !== "tv" && !tv) {
          const botao = no("button", i.status_preparo === "pendente" ? "Iniciar preparo" : "Marcar pronto");
          botao.type = "button";
          botao.addEventListener("click", () => alterar(i));
          artigo.append(botao);
        }
        $("fila").append(artigo);
      }
    } catch (e) {
      if (e.status === 401 || e.status === 403) { entrada(e.message); return; }
      desatualizar(e.message || "Sem comunicação.");
    } finally {
      ocupado = false;
      if (!$("painel").hidden) timer = setTimeout(atualizar, 3000);
    }
  }
  $("login").addEventListener("submit", async evento => {
    evento.preventDefault();
    $("entrar").disabled = true;
    try {
      await api("entrar", { pin: $("pin").value, modo: tv ? "tv" : "operacao" });
      $("pin").value = "";
      await atualizar();
    } catch (e) { $("aviso").textContent = e.message; }
    finally { $("entrar").disabled = false; }
  });
  $("sair").addEventListener("click", async () => {
    try { await api("sair", {}); } finally { entrada(); }
  });
  $("setor").addEventListener("change", atualizar);
  $("tela-cheia").addEventListener("click", async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch (_) { $("aviso").textContent = "Use a opção de tela cheia do navegador."; }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearTimeout(timer);
    else if (!$("painel").hidden) atualizar();
  });
  (async () => {
    try {
      const s = await api("sessao");
      if (s.modo === (tv ? "tv" : "operacao")) await atualizar();
      else entrada("Entre com o PIN para mudar o modo de uso.");
    } catch (_) { entrada(); }
  })();
})();
