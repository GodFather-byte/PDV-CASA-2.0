/* WillPDV Retaguarda: JavaScript puro, sem dependências.
 * Serve ao dono (sessão do painel, /v1/painel/retaguarda) e ao fornecedor (/retaguarda/?loja=CHAVE, sessão da
 * central, /v1/fornecedor/lojas/CHAVE/retaguarda). A página só lê o espelho que o caixa subiu e pede alterações:
 * cada uma vira um comando que o caixa aplica na próxima sincronização. Dinheiro trafega em centavos inteiros. */
(function () {
  "use strict";

  const CHAVE_TOKEN = "willpdv.painel.token";
  const $ = (id) => document.getElementById(id);
  const lojaDaCentral = new URLSearchParams(location.search).get("loja");
  const estado = {
    modo: lojaDaCentral ? "fornecedor" : "dono",
    base: lojaDaCentral ? "/v1/fornecedor/lojas/" + encodeURIComponent(lojaDaCentral) + "/retaguarda" : "/v1/painel/retaguarda",
    token: null, csrf: "", esquema: null, visao: null, secao: null, busca: "", pagina: 1, inativos: true, pedido: 0,
  };
  const GRUPOS = [["produtos", "Produtos e estoque"], ["pessoas", "Pessoas"], ["financeiro", "Financeiro"], ["outros", "Outros cadastros"]];
  const TIPOS_ESTOQUE = { entrada: "Entrada", saida: "Saída", contagem: "Contagem (o que há na prateleira)", quebra: "Quebra", descarte: "Descarte" };
  const SITUACOES = { pendente: ["Aguardando o caixa", "espera"], aplicado: ["Aplicada", "ok"], recusado: ["Recusada pelo caixa", "erro"] };

  // ---------------------------------------------------------------- utilidades
  function el(tag, texto, classe) {
    const e = document.createElement(tag);
    if (texto !== undefined && texto !== null) e.textContent = String(texto);
    if (classe) e.className = classe;
    return e;
  }
  function limpar(no) { while (no.firstChild) no.removeChild(no.firstChild); return no; }
  function dinheiro(cent) {
    const v = Number(cent) || 0;
    return (v < 0 ? "-" : "") + "R$ " + (Math.abs(v) / 100).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function reais(cent) {
    return (Number(cent || 0) / 100).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: false });
  }
  function numero(v) { return (Number(v) || 0).toLocaleString("pt-BR", { maximumFractionDigits: 4 }); }
  function dataBr(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
    return m ? m[3] + "/" + m[2] + "/" + m[1] : "";
  }
  function quando(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(String(iso || ""));
    return m ? m[3] + "/" + m[2] + " " + m[4] + ":" + m[5] : "";
  }
  function hoje() {
    const d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }
  /** "1.234,56" ou "12.5" -> centavos inteiros; null se não for número. */
  function paraCentavos(texto) {
    let t = String(texto).trim().replace(/^R\$\s*/, "");
    if (!t) return null;
    if (t.includes(",")) t = t.replace(/\./g, "").replace(",", ".");
    if (!/^-?\d+(\.\d{1,2})?$/.test(t)) return null;
    return Math.round(parseFloat(t) * 100);
  }
  function paraNumero(texto) {
    const t = String(texto).trim().replace(",", ".");
    return /^-?\d+(\.\d+)?$/.test(t) ? parseFloat(t) : null;
  }
  let relogioRecado = 0;
  function recado(texto) {
    const r = $("recado");
    r.textContent = texto;
    r.hidden = false;
    clearTimeout(relogioRecado);
    relogioRecado = setTimeout(() => { r.hidden = true; }, 5000);
  }

  // ---------------------------------------------------------------- API
  class ErroApi extends Error {
    constructor(status, mensagem) { super(mensagem); this.status = status; }
  }
  async function api(caminho, metodo, corpo) {
    const opcoes = { method: metodo || "GET", cache: "no-store", headers: {} };
    if (estado.modo === "dono") opcoes.headers.Authorization = "Bearer " + estado.token;
    else {
      opcoes.credentials = "same-origin";
      if (opcoes.method !== "GET") opcoes.headers["X-Central-CSRF"] = estado.csrf;
    }
    if (corpo !== undefined) {
      opcoes.headers["Content-Type"] = "application/json";
      opcoes.body = JSON.stringify(corpo);
    }
    let resposta;
    try { resposta = await fetch(estado.base + caminho, opcoes); }
    catch (_) { throw new ErroApi(0, "Sem conexão com a nuvem. Tente de novo."); }
    let dados = null;
    try { dados = await resposta.json(); } catch (_) { /* resposta sem JSON */ }
    if (!resposta.ok) {
      if (resposta.status === 401) mostrarEntrada();
      const detalhe = dados && typeof dados.detail === "string" ? dados.detail : "Não foi possível concluir (HTTP " + resposta.status + ").";
      throw new ErroApi(resposta.status, detalhe);
    }
    return dados;
  }
  async function pedir(tipo, dados, resumo) {
    await api("/comandos", "POST", { tipo: tipo, dados: dados, resumo: resumo });
    recado("Alteração enviada. O caixa aplica na próxima sincronização.");
  }

  // ---------------------------------------------------------------- telas de estado
  function mostrarEntrada() {
    $("tela-app").hidden = true;
    $("tela-desligada").hidden = true;
    $("tela-entrada").hidden = false;
    if (estado.modo === "fornecedor") {
      $("entrada-texto").textContent = "Entre na central do fornecedor e abra a retaguarda pela ficha da loja.";
      $("entrada-link").textContent = "Abrir a central";
      $("entrada-link").href = "/central/";
    }
    $("loja-nome").textContent = "";
  }

  $("menu-compacto").addEventListener("change", (evento) => abrir(evento.target.value));

  async function iniciar() {
    if (estado.modo === "fornecedor") {
      $("link-voltar").textContent = "Voltar à central";
      $("link-voltar").href = "/central/";
      try {
        const r = await fetch("/v1/fornecedor/sessao", { credentials: "same-origin", cache: "no-store" });
        if (!r.ok) return mostrarEntrada();
        estado.csrf = (await r.json()).csrf || "";
      } catch (_) { return mostrarEntrada(); }
    } else {
      try { estado.token = localStorage.getItem(CHAVE_TOKEN); } catch (_) { estado.token = null; }
      if (!estado.token) return mostrarEntrada();
    }
    await carregar();
  }

  async function carregar() {
    let visao;
    try { visao = await api(""); }
    catch (erro) {
      if (erro.status !== 401) {
        $("aviso-geral").textContent = erro.message;
        $("aviso-geral").hidden = false;
      }
      return;
    }
    $("aviso-geral").hidden = true;
    estado.visao = visao;
    estado.esquema = visao.esquema;
    $("tela-entrada").hidden = true;
    if (!visao.ligada) {
      $("tela-desligada").hidden = false;
      $("tela-app").hidden = true;
      $("loja-nome").textContent = estado.modo === "fornecedor" ? lojaDaCentral : "";
      return;
    }
    $("tela-desligada").hidden = true;
    $("tela-app").hidden = false;
    const e = estado.esquema;
    $("loja-nome").textContent = (e.loja || lojaDaCentral || "Loja") + (e.programa ? " · " + e.programa : "");
    $("espelho-quando").textContent = visao.atualizado_em ? "caixa enviou em " + quando(visao.atualizado_em) : "";
    montarMenu();
    const existe = estado.secao && (estado.secao.indexOf("cadastro:") !== 0 || entidade(estado.secao.slice(9)));
    await abrir(existe ? estado.secao : "cadastro:produtos", true);
  }

  function entidade(chave) {
    return (estado.esquema.entidades || []).find((e) => e.chave === chave) || null;
  }
  function tituloCurto(ent) {
    return ent.titulo.replace(/^Cadastro de /, "");
  }

  function montarMenu() {
    const menu = limpar($("menu"));
    const compacto = limpar($("menu-compacto"));
    let grupoCompacto;
    const abrirGrupo = (nome) => {
      menu.append(el("h3", nome));
      grupoCompacto = el("optgroup");
      grupoCompacto.label = nome;
      compacto.append(grupoCompacto);
    };
    const botao = (secao, rotulo, contador) => {
      const b = el("button", rotulo);
      b.type = "button";
      b.dataset.secao = secao;
      if (contador) b.append(el("span", contador, "contador"));
      b.addEventListener("click", () => abrir(secao));
      menu.append(b);
      const opcao = el("option", contador ? rotulo + " (" + contador + ")" : rotulo);
      opcao.value = secao;
      grupoCompacto.append(opcao);
    };
    GRUPOS.forEach(([grupo, titulo]) => {
      const itens = estado.esquema.entidades.filter((e) => e.grupo === grupo);
      const extras = grupo === "financeiro" && (estado.esquema.contas || estado.esquema.caderneta);
      if (!itens.length && !extras) return;
      abrirGrupo(titulo);
      if (grupo === "financeiro" && estado.esquema.contas) botao("contas", "Contas a pagar");
      if (grupo === "financeiro" && estado.esquema.caderneta) botao("caderneta", "Caderneta (quem deve)");
      itens.sort((x, y) => (y.chave === "produtos") - (x.chave === "produtos"));       // Produtos primeiro no seu grupo
      itens.forEach((e) => botao("cadastro:" + e.chave, tituloCurto(e)));
    });
    if (estado.modo === "fornecedor") {
      abrirGrupo("Suporte");
      botao("planilha", "Importar planilha de produtos");
      botao("servicos", "Serviços cobrados");
    }
    abrirGrupo("Loja");
    botao("config", "Configurações");
    botao("alteracoes", "Alterações enviadas", estado.visao.pendentes || null);
    if (estado.secao) compacto.value = estado.secao;
  }

  async function abrir(secao, mesmaBusca) {
    if (estado.secao !== secao || !mesmaBusca) { estado.busca = ""; estado.pagina = 1; }
    estado.secao = secao;
    $("menu-compacto").value = secao;
    document.querySelectorAll("#menu button").forEach((b) => {
      if (b.dataset.secao === secao) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    const pedido = ++estado.pedido;
    const alvo = $("conteudo");
    try {
      let no;
      if (secao.indexOf("cadastro:") === 0) no = await telaCadastro(entidade(secao.slice(9)));
      else if (secao === "contas") no = await telaContas();
      else if (secao === "caderneta") no = await telaCaderneta();
      else if (secao === "config") no = telaConfig();
      else if (secao === "planilha") no = telaPlanilha();
      else if (secao === "servicos") no = await telaServicos();
      else no = await telaAlteracoes();
      if (pedido !== estado.pedido) return;
      limpar(alvo).append(no);
    } catch (erro) {
      if (pedido !== estado.pedido) return;
      limpar(alvo).append(el("p", erro.message, "vazio"));
    }
  }
  function recarregar() { return abrir(estado.secao, true); }

  // ---------------------------------------------------------------- cadastros
  function valorDaCelula(campo, valor) {
    if (valor === null || valor === undefined || valor === "") return "";
    if (campo.tipo === "dinheiro") return dinheiro(valor);
    if (campo.tipo === "decimal") return numero(valor);
    if (campo.tipo === "sn") return valor ? "Sim" : "Não";
    if (campo.tipo === "data") return dataBr(valor);
    if (campo.tipo === "lookup") {
      const achado = (estado.esquema.lookups[campo.lookup] || []).find((o) => o[0] === valor);
      return achado ? achado[1] : "#" + valor;
    }
    if (campo.tipo === "escolha") {
      const achado = (campo.opcoes || []).find((o) => String(o[0]) === String(valor));
      return achado ? achado[1] : valor;
    }
    return valor;
  }
  function nomeDaLinha(ent, linha) {
    for (const nome of ["nome", "descricao", "tipo", "texto"]) if (linha[nome]) return String(linha[nome]);
    const primeiro = ent.campos.find((c) => c.tipo === "texto" && linha[c.nome]);
    return primeiro ? String(linha[primeiro.nome]) : "#" + linha.id;
  }

  async function telaCadastro(ent) {
    const parametros = new URLSearchParams({ busca: estado.busca, pagina: String(estado.pagina), inativos: estado.inativos ? "1" : "0" });
    const dados = await api("/cadastro/" + ent.chave + "?" + parametros.toString());
    const raiz = el("section");
    raiz.append(el("h1", tituloCurto(ent)));
    raiz.append(el("p", dados.total + " no caixa" + (dados.atualizado_em ? " · enviado em " + quando(dados.atualizado_em) : ""), "suave"));

    const barra = el("div", null, "barra");
    const busca = el("input");
    busca.type = "search";
    busca.placeholder = "Buscar em " + tituloCurto(ent).toLowerCase();
    busca.value = estado.busca;
    busca.setAttribute("aria-label", "Buscar");
    let espera = 0;
    busca.addEventListener("input", () => {
      clearTimeout(espera);
      espera = setTimeout(async () => {
        estado.busca = busca.value.trim();
        estado.pagina = 1;
        await recarregar();
        const novo = document.querySelector(".barra input[type=search]");
        if (novo) { novo.focus(); novo.setSelectionRange(novo.value.length, novo.value.length); }
      }, 350);
    });
    barra.append(busca);
    if (ent.tem_ativo) {
      const rotulo = el("label", null, "marcar");
      const caixa = el("input");
      caixa.type = "checkbox";
      caixa.checked = estado.inativos;
      caixa.addEventListener("change", () => { estado.inativos = caixa.checked; estado.pagina = 1; recarregar(); });
      rotulo.append(caixa, el("span", "Mostrar inativos"));
      barra.append(rotulo);
    }
    const novo = el("button", "Novo", "botao");
    novo.type = "button";
    novo.addEventListener("click", () => abrirFormulario(ent, null));
    barra.append(novo);
    raiz.append(barra);

    const esperando = {};
    const novosNaFila = [];
    dados.pendentes.forEach((c) => {
      const d = c.dados || {};
      if (c.tipo === "estoque.movimento") {
        if (ent.chave === "produtos") esperando[d.produto_id] = true;
      } else if (d.entidade === ent.chave) {
        if (d.id === undefined || d.id === null) novosNaFila.push(c); else esperando[d.id] = true;
      }
    });
    if (novosNaFila.length) {
      const lista = el("ul", null, "lista");
      novosNaFila.forEach((c) => {
        const li = el("li");
        const principal = el("div", null, "principal");
        principal.append(el("strong", c.resumo), el("span", "Cadastro novo, aguardando o caixa", "suave"));
        li.append(principal);
        lista.append(li);
      });
      raiz.append(lista);
    }

    // Produtos mostram o que mais se consulta de longe (preço, custo e saldo); os outros cadastros, as colunas da grade do PDV.
    const preferidas = ent.chave === "produtos" ? ["codigo", "nome", "subgrupo_id", "preco_cent", "custo_medio_cent", "qt_atual", "ativo"] : null;
    const colunas = preferidas ? preferidas.map((n) => ent.campos.find((c) => c.nome === n)).filter(Boolean)
      : ent.campos.filter((c) => c.na_grade && c.tipo !== "senha").slice(0, 7);
    if (!dados.linhas.length) {
      raiz.append(el("p", estado.busca ? "Nada encontrado para “" + estado.busca + "”." : "Nenhum registro neste cadastro.", "vazio cartao"));
      return raiz;
    }
    const tabela = el("table", null, "tabela-cadastro");
    const cabeca = el("tr");
    const rotuloColuna = (campo) => campo.rotulo.replace(/\s*\(.*\)$/, "");
    const campoTitulo = colunas.find((c) => c.nome === "nome" || c.nome === "descricao") || colunas[0];
    colunas.forEach((c) => cabeca.append(el("th", rotuloColuna(c), ["dinheiro", "decimal", "int"].includes(c.tipo) ? "numero" : "")));
    cabeca.append(el("th", ""));
    const thead = el("thead");
    thead.append(cabeca);
    const corpo = el("tbody");
    dados.linhas.forEach((valores) => {
      const linha = {};
      dados.campos.forEach((nome, i) => { linha[nome] = valores[i]; });
      const tr = el("tr");
      if (ent.tem_ativo && !linha.ativo) tr.className = "inativo";
      colunas.forEach((c) => {
        const celula = el("td", valorDaCelula(c, linha[c.nome]), ["dinheiro", "decimal", "int"].includes(c.tipo) ? "numero" : "");
        celula.dataset.rotulo = rotuloColuna(c);
        if (c === campoTitulo) celula.classList.add("titulo-registro");
        tr.append(celula);
      });
      const fim = el("td");
      if (esperando[linha.id]) fim.append(el("span", "aguardando o caixa", "selo espera"));
      tr.append(fim);
      tr.tabIndex = 0;
      tr.setAttribute("role", "button");
      tr.setAttribute("aria-label", "Editar " + nomeDaLinha(ent, linha));
      tr.addEventListener("click", () => abrirFormulario(ent, linha));
      tr.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); abrirFormulario(ent, linha); } });
      corpo.append(tr);
    });
    tabela.append(thead, corpo);
    const rolagem = el("div", null, "tabela-rolagem");
    rolagem.append(tabela);
    raiz.append(rolagem);

    const paginas = Math.max(Math.ceil(dados.encontradas / dados.por_pagina), 1);
    if (paginas > 1) {
      const nav = el("div", null, "paginas");
      const antes = el("button", "Anterior", "botao secundario pequeno");
      const depois = el("button", "Próxima", "botao secundario pequeno");
      antes.type = depois.type = "button";
      antes.disabled = estado.pagina <= 1;
      depois.disabled = estado.pagina >= paginas;
      antes.addEventListener("click", () => { estado.pagina -= 1; recarregar(); });
      depois.addEventListener("click", () => { estado.pagina += 1; recarregar(); });
      nav.append(antes, el("span", "Página " + estado.pagina + " de " + paginas + " · " + dados.encontradas + " registros", "suave"), depois);
      raiz.append(nav);
    }
    return raiz;
  }

  // ---------------------------------------------------------------- formulário
  /** Cria o controle de um campo e devolve {no, ler()} onde ler() dá o valor no contrato da API ou lança Error. */
  function controle(campo, valor, opcoesExtras) {
    const rotulo = el("label", null, "campo" + (campo.tipo === "sn" ? " sn" : ""));
    const texto = el("span", campo.rotulo + (campo.obrigatorio ? " *" : ""));
    let entrada;
    let ler;
    const tipo = campo.tipo;
    if (tipo === "sn") {
      entrada = el("input");
      entrada.type = "checkbox";
      entrada.checked = valor === null || valor === undefined ? Boolean(campo.padrao) : Boolean(valor) && valor !== "N";
      ler = () => (entrada.checked ? 1 : 0);
      rotulo.append(entrada, texto);
    } else {
      if (tipo === "lookup" || tipo === "escolha") {
        entrada = el("select");
        const opcoes = tipo === "lookup" ? (opcoesExtras || estado.esquema.lookups[campo.lookup] || []) : (campo.opcoes || []);
        if (!campo.obrigatorio || valor === null || valor === undefined) entrada.append(new Option("", ""));
        opcoes.forEach((o, i) => {
          const op = new Option(o[1], String(i));
          if (String(o[0]) === String(valor)) op.selected = true;
          entrada.append(op);
        });
        ler = () => (entrada.value === "" ? null : opcoes[Number(entrada.value)][0]);
      } else {
        entrada = el("input");
        entrada.type = tipo === "senha" ? "password" : tipo === "data" ? "date" : tipo === "hora" ? "time" : "text";
        if (tipo === "senha") entrada.autocomplete = "new-password";
        if (["dinheiro", "decimal"].includes(tipo)) entrada.inputMode = "decimal";
        if (["int", "cod13"].includes(tipo)) entrada.inputMode = "numeric";
        if (campo.tamanho) entrada.maxLength = campo.tamanho;
        if (valor !== null && valor !== undefined && tipo !== "senha") {
          entrada.value = tipo === "dinheiro" ? reais(valor) : tipo === "decimal" ? String(valor).replace(".", ",") : String(valor);
        }
        ler = () => {
          const bruto = entrada.value.trim();
          if (bruto === "") return tipo === "dinheiro" || tipo === "decimal" || tipo === "int" ? null : "";
          if (tipo === "dinheiro") {
            const c = paraCentavos(bruto);
            if (c === null) throw new Error(campo.rotulo + ": valor inválido. Use o formato 12,50.");
            return c;
          }
          if (tipo === "decimal") {
            const n = paraNumero(bruto);
            if (n === null) throw new Error(campo.rotulo + ": número inválido.");
            return n;
          }
          if (tipo === "int") {
            if (!/^-?\d+$/.test(bruto)) throw new Error(campo.rotulo + ": informe um número inteiro.");
            return parseInt(bruto, 10);
          }
          return bruto;
        };
      }
      rotulo.append(texto, entrada);
    }
    if (campo.somente_leitura) entrada.disabled = true;
    return { no: rotulo, entrada: entrada, ler: ler, campo: campo };
  }

  function abrirDialogo(titulo) {
    $("dialogo-titulo").textContent = titulo;
    limpar($("dialogo-corpo"));
    limpar($("dialogo-rodape"));
    $("dialogo-aviso").textContent = "";
    if (!$("dialogo").open) $("dialogo").showModal();
    return { corpo: $("dialogo-corpo"), rodape: $("dialogo-rodape") };
  }
  function fecharDialogo() { if ($("dialogo").open) $("dialogo").close(); }
  async function enviarDoDialogo(botao, acao) {
    $("dialogo-aviso").textContent = "";
    botao.disabled = true;
    try {
      await acao();
      fecharDialogo();
      await atualizarContador();
      await recarregar();
    } catch (erro) {
      $("dialogo-aviso").textContent = erro.message;
    } finally {
      botao.disabled = false;
    }
  }
  function mesmoValor(a, b) {
    const vazio = (v) => v === null || v === undefined || v === "";
    if (vazio(a) && vazio(b)) return true;
    return String(a) === String(b);
  }

  function abrirFormulario(ent, linha) {
    const nome = linha ? nomeDaLinha(ent, linha) : "";
    const { corpo, rodape } = abrirDialogo(linha ? tituloCurto(ent) + ": " + nome : "Novo em " + tituloCurto(ent));
    const controles = [];
    const secoes = [];
    ent.campos.forEach((c) => { if (!secoes.includes(c.secao)) secoes.push(c.secao); });
    secoes.forEach((secao) => {
      const campos = ent.campos.filter((c) => c.secao === secao && !(c.somente_leitura && !linha));
      if (!campos.length) return;
      corpo.append(el("h3", secao));
      const grade = el("div", null, "grade-campos");
      campos.forEach((c) => {
        const ctl = controle(c, linha ? linha[c.nome] : c.padrao);
        if (c.tipo === "senha" && linha) ctl.no.firstChild.textContent = c.rotulo + " (em branco = não muda)";
        controles.push(ctl);
        grade.append(ctl.no);
      });
      corpo.append(grade);
    });

    if (linha && ent.chave === "produtos") {
      corpo.append(el("h3", "Movimentar estoque"));
      const grade = el("div", null, "grade-campos");
      const tipo = controle({ rotulo: "Movimento", tipo: "escolha", obrigatorio: true,
                              opcoes: (estado.esquema.estoque_tipos || []).map((t) => [t, TIPOS_ESTOQUE[t] || t]) }, "entrada");
      const quantidade = controle({ rotulo: "Quantidade", tipo: "decimal" }, null);
      const motivo = controle({ rotulo: "Motivo (aparece no caixa)", tipo: "texto", tamanho: 80 }, null);
      const mover = el("button", "Enviar movimento", "botao secundario");
      mover.type = "button";
      mover.addEventListener("click", () => enviarDoDialogo(mover, async () => {
        const qt = quantidade.ler();
        if (qt === null || qt < 0 || (qt === 0 && tipo.ler() !== "contagem")) throw new Error("Informe a quantidade do movimento.");
        await pedir("estoque.movimento", { produto_id: linha.id, tipo: tipo.ler(), quantidade: qt, descricao: motivo.ler() },
                    "Estoque: " + (TIPOS_ESTOQUE[tipo.ler()] || tipo.ler()).split(" (")[0].toLowerCase() + " de " + numero(qt) + " em " + nome);
      }));
      grade.append(tipo.no, quantidade.no, motivo.no, mover);
      corpo.append(grade);
    }

    if (linha) {
      const excluir = el("button", "Excluir", "botao perigo");
      excluir.type = "button";
      let confirmado = false;
      excluir.addEventListener("click", () => {
        if (!confirmado) { confirmado = true; excluir.textContent = "Confirmar exclusão"; return; }
        enviarDoDialogo(excluir, () => pedir("cadastro.excluir", { entidade: ent.chave, id: linha.id }, tituloCurto(ent) + ": excluir " + nome));
      });
      rodape.append(excluir);
    }
    const salvar = el("button", linha ? "Salvar alterações" : "Cadastrar", "botao");
    salvar.type = "submit";
    $("formulario").onsubmit = (ev) => {
      ev.preventDefault();
      enviarDoDialogo(salvar, async () => {
        const valores = {};
        const rotulos = [];
        controles.forEach((ctl) => {
          const c = ctl.campo;
          if (c.somente_leitura) return;
          const valor = ctl.ler();
          if (c.tipo === "senha") { if (valor) { valores[c.nome] = valor; rotulos.push("senha"); } return; }
          if (linha) {
            if (mesmoValor(valor, linha[c.nome])) return;
          } else if (valor === null || valor === "" || mesmoValor(valor, c.padrao)) return;
          valores[c.nome] = valor;
          rotulos.push(c.rotulo.replace(/\s*\(.*\)$/, "").toLowerCase()
            + (c.tipo === "dinheiro" && valor !== null ? " " + reais(valor) : ""));
        });
        if (!Object.keys(valores).length) throw new Error(linha ? "Nada foi alterado." : "Preencha os campos do cadastro.");
        const faltam = controles.filter((ctl) => {
          const c = ctl.campo;
          if (!c.obrigatorio || c.somente_leitura || c.tipo === "sn" || (c.tipo === "senha" && linha)) return false;
          const v = ctl.ler();
          return v === null || v === "";
        }).map((ctl) => ctl.campo.rotulo.replace(/\s*\(.*\)$/, ""));
        if (faltam.length) throw new Error("Preencha: " + faltam.join(", ") + ".");
        const dados = { entidade: ent.chave, valores: valores };
        if (linha) dados.id = linha.id;
        const alvo = linha ? nome : String(valores.nome || valores.descricao || "novo");
        await pedir("cadastro.salvar", dados, tituloCurto(ent) + ": " + (linha ? "" : "novo ") + alvo + " (" + rotulos.slice(0, 4).join(", ") + (rotulos.length > 4 ? "…" : "") + ")");
      });
    };
    rodape.append(salvar);
  }

  // ---------------------------------------------------------------- financeiro
  function rotuloLookup(nome, id) {
    const achado = (estado.esquema.lookups[nome] || []).find((o) => o[0] === id);
    return achado ? achado[1] : "";
  }

  async function telaContas() {
    const dados = await api("/financeiro");
    const raiz = el("section");
    raiz.append(el("h1", "Contas a pagar"));
    const abertas = dados.contas.filter((c) => !c.dt_quitacao);
    const total = abertas.reduce((s, c) => s + (c.valor_cent || 0), 0);
    raiz.append(el("p", abertas.length + " em aberto, " + dinheiro(total) + (dados.atualizado_em ? " · enviado em " + quando(dados.atualizado_em) : ""), "suave"));
    const barra = el("div", null, "barra");
    const nova = el("button", "Nova conta", "botao");
    nova.type = "button";
    nova.addEventListener("click", abrirNovaConta);
    barra.append(nova);
    raiz.append(barra);
    const esperando = {};
    dados.pendentes.forEach((c) => { if (c.dados && c.dados.id) esperando[c.dados.id] = true; });
    const novas = dados.pendentes.filter((c) => c.tipo === "conta.incluir");
    const lista = el("ul", null, "lista");
    novas.forEach((c) => {
      const li = el("li");
      const principal = el("div", null, "principal");
      principal.append(el("strong", c.resumo), el("span", "Conta nova, aguardando o caixa", "suave"));
      li.append(principal);
      lista.append(li);
    });
    const ordenadas = dados.contas.slice().sort((a, b) => (Boolean(a.dt_quitacao) - Boolean(b.dt_quitacao))
      || String(a.dt_vencimento).localeCompare(String(b.dt_vencimento)));
    const dia = hoje();
    ordenadas.forEach((c) => {
      const li = el("li");
      const principal = el("div", null, "principal");
      principal.append(el("strong", c.descricao + (c.parcela ? " (" + c.parcela + ")" : "")));
      const detalhe = c.dt_quitacao ? "Quitada em " + dataBr(c.dt_quitacao)
        : (c.dt_vencimento < dia ? "Venceu em " : "Vence em ") + dataBr(c.dt_vencimento);
      principal.append(el("span", detalhe + (rotuloLookup("subplanos", c.subplano_id) ? " · " + rotuloLookup("subplanos", c.subplano_id) : ""), "suave"));
      li.append(principal, el("span", dinheiro(c.valor_cent), "valor"));
      const acoes = el("div", null, "acoes");
      if (esperando[c.id]) acoes.append(el("span", "aguardando o caixa", "selo espera"));
      else {
        const acao = (rotulo, classe, tipo, corpo, resumo) => {
          const b = el("button", rotulo, "botao pequeno " + classe);
          b.type = "button";
          let confirmado = tipo !== "conta.excluir";
          b.addEventListener("click", async () => {
            if (!confirmado) { confirmado = true; b.textContent = "Confirmar"; return; }
            b.disabled = true;
            try { await pedir(tipo, corpo, resumo); await atualizarContador(); await recarregar(); }
            catch (erro) { recado(erro.message); b.disabled = false; }
          });
          acoes.append(b);
        };
        if (c.dt_quitacao) acao("Desfazer quitação", "secundario", "conta.desfazer", { id: c.id }, "Contas: desfazer quitação de " + c.descricao);
        else acao("Quitar hoje", "", "conta.quitar", { id: c.id, data: dia }, "Contas: quitar " + c.descricao + " (" + reais(c.valor_cent) + ")");
        acao("Excluir", "perigo", "conta.excluir", { id: c.id }, "Contas: excluir " + c.descricao);
      }
      li.append(acoes);
      lista.append(li);
    });
    if (!lista.children.length) raiz.append(el("p", "Nenhuma conta em aberto nem quitada nos últimos meses.", "vazio cartao"));
    else raiz.append(lista);
    return raiz;
  }

  function abrirNovaConta() {
    const { corpo, rodape } = abrirDialogo("Nova conta a pagar");
    const lookups = estado.esquema.lookups;
    const campos = {
      descricao: controle({ rotulo: "Descrição", tipo: "texto", obrigatorio: true, tamanho: 60 }, null),
      valor_cent: controle({ rotulo: "Valor", tipo: "dinheiro", obrigatorio: true }, null),
      dt_vencimento: controle({ rotulo: "Vencimento", tipo: "data", obrigatorio: true }, hoje()),
      subplano_id: controle({ rotulo: "Sub plano", tipo: "lookup", lookup: "subplanos", obrigatorio: true }, null),
      tipo_pagamento_id: controle({ rotulo: "Forma de pagamento", tipo: "lookup", lookup: "tipos_pagamento", obrigatorio: true }, null),
      fornecedor_id: controle({ rotulo: "Fornecedor", tipo: "lookup", lookup: "fornecedores" }, null, lookups.fornecedores || []),
      documento: controle({ rotulo: "Documento", tipo: "texto", tamanho: 30 }, null),
      meses: controle({ rotulo: "Repetir por quantos meses", tipo: "int" }, 1),
    };
    const grade = el("div", null, "grade-campos");
    Object.values(campos).forEach((c) => grade.append(c.no));
    corpo.append(el("h3", "Conta"), grade);
    const salvar = el("button", "Lançar conta", "botao");
    salvar.type = "submit";
    $("formulario").onsubmit = (ev) => {
      ev.preventDefault();
      enviarDoDialogo(salvar, async () => {
        const dados = {};
        Object.keys(campos).forEach((nome) => { dados[nome] = campos[nome].ler(); });
        if (!dados.descricao) throw new Error("Informe a descrição da conta.");
        if (!dados.valor_cent || dados.valor_cent <= 0) throw new Error("Informe um valor maior que zero.");
        if (dados.subplano_id === null || dados.tipo_pagamento_id === null) throw new Error("Escolha o sub plano e a forma de pagamento.");
        if (dados.fornecedor_id === null) delete dados.fornecedor_id;
        dados.meses = dados.meses || 1;
        await pedir("conta.incluir", dados, "Contas: nova " + dados.descricao + " (" + reais(dados.valor_cent) + ", vence " + dataBr(dados.dt_vencimento) + ")");
      });
    };
    rodape.append(salvar);
  }

  async function telaCaderneta() {
    const dados = await api("/financeiro");
    const raiz = el("section");
    raiz.append(el("h1", "Caderneta: quem deve"));
    const total = dados.devedores.reduce((s, d) => s + Math.abs(d.saldo_cent || 0), 0);
    raiz.append(el("p", dados.devedores.length + " clientes devendo " + dinheiro(total) + ". O recebimento é feito no caixa.", "suave"));
    if (!dados.devedores.length) { raiz.append(el("p", "Ninguém devendo na caderneta.", "vazio cartao")); return raiz; }
    const lista = el("ul", null, "lista");
    dados.devedores.forEach((d) => {
      const li = el("li");
      const principal = el("div", null, "principal");
      principal.append(el("strong", d.nome));
      li.append(principal, el("span", dinheiro(Math.abs(d.saldo_cent)), "valor"));
      lista.append(li);
    });
    raiz.append(lista);
    return raiz;
  }

  // ---------------------------------------------------------------- suporte (só pela central)
  const COLUNAS_LOTE = [["nome", "Produto"], ["preco", "Preço (R$)"], ["quantidade", "Estoque"], ["custo", "Custo (R$)"],
    ["grupo", "Grupo"], ["unidade", "Un."], ["codigo_barras", "Código de barras"]];
  function lerArquivo(arquivo) {
    return new Promise((ok, falha) => {
      const leitor = new FileReader();
      leitor.onload = () => ok(String(leitor.result).split(",")[1] || "");
      leitor.onerror = () => falha(new Error("Não consegui ler o arquivo."));
      leitor.readAsDataURL(arquivo);
    });
  }
  function telaPlanilha() {
    const raiz = el("section");
    raiz.append(el("h1", "Importar planilha de produtos"));
    raiz.append(el("p", "Escolha a planilha (Excel ou CSV, com títulos como Produto, Preço, Quantidade). Confira e corrija " +
      "os preços aqui antes de enviar. O caixa aplica na próxima sincronização, pelas mesmas regras da importação do caixa: " +
      "produto com o mesmo nome ou código é atualizado, os outros são criados.", "suave"));
    const arquivo = el("input");
    arquivo.type = "file";
    arquivo.accept = ".csv,.xlsx,.xlsm,.txt";
    const catalogo = botaoPequeno("Carregar catálogo da adega (274 produtos)", async () => {
      const r = await apiCentral("/catalogo");
      linhas = r.linhas;
      filtro = "";
      desenhar();
    });
    const area = el("div");
    raiz.append(arquivo, catalogo, area);
    let linhas = [], lote = 200, filtro = "";
    const comPreco = (l) => paraCentavos(l.preco) !== null && paraCentavos(l.preco) > 0 && String(l.nome || "").trim();
    function desenhar() {
      limpar(area);
      if (!linhas.length) return;
      const prontos = linhas.filter(comPreco).length;
      area.append(el("p", linhas.length + " produtos na lista; " + prontos + " com preço vão para o caixa. " +
        "Os sem preço ficam de fora.", "suave"));
      const grupos = [...new Set(linhas.map((l) => l.grupo).filter(Boolean))].sort();
      if (grupos.length > 1) {
        const sel = el("select");
        sel.append(new Option("Todos os grupos", ""));
        grupos.forEach((g) => sel.append(new Option(g, g)));
        sel.value = filtro;
        sel.addEventListener("change", () => { filtro = sel.value; desenhar(); });
        area.append(sel);
      }
      const rolagem = el("div", null, "tabela-rolagem");
      const tabela = el("table");
      const cab = el("tr");
      cab.append(el("th", "#"));
      COLUNAS_LOTE.forEach(([, t]) => cab.append(el("th", t)));
      cab.append(el("th", ""));
      tabela.append(el("thead")).firstChild.append(cab);
      const corpo = el("tbody");
      linhas.forEach((l, i) => {
        if (filtro && l.grupo !== filtro) return;
        const tr = el("tr");
        tr.append(el("td", i + 1));
        COLUNAS_LOTE.forEach(([c]) => {
          const td = el("td");
          const campo = el("input");
          campo.value = l[c] || "";
          campo.setAttribute("aria-label", c + " da linha " + (i + 1));
          if (c === "preco" && paraCentavos(campo.value) === null) campo.style.outline = "2px solid var(--vermelho)";
          campo.addEventListener("change", () => {
            l[c] = campo.value.trim();
            if (c === "preco") campo.style.outline = paraCentavos(l.preco) === null ? "2px solid var(--vermelho)" : "";
          });
          td.append(campo);
          tr.append(td);
        });
        const tirar = el("button", "Tirar", "botao pequeno secundario");
        tirar.type = "button";
        tirar.addEventListener("click", () => { linhas.splice(i, 1); desenhar(); });
        tr.append(el("td")).lastChild.append(tirar);
        corpo.append(tr);
      });
      tabela.append(corpo);
      rolagem.append(tabela);
      const enviar = el("button", "Enviar para o caixa", "botao");
      enviar.type = "button";
      enviar.addEventListener("click", async () => {
        const envio = linhas.filter(comPreco);
        if (!envio.length) { recado("Coloque o preço de pelo menos um produto."); return; }
        enviar.disabled = true;
        try {
          for (let i = 0; i < envio.length; i += lote) {
            const parte = envio.slice(i, i + lote);
            await api("/comandos", "POST", { tipo: "produtos.importar", dados: { linhas: parte },
              resumo: "Planilha: " + parte.length + " produtos (" + (i + 1) + " a " + (i + parte.length) + ")" });
          }
          recado(envio.length + " produtos enviados. Acompanhe em Alterações enviadas.");
          linhas = [];
          arquivo.value = "";
          desenhar();
          atualizarContador();
          await oferecerCobranca(area, envio.length);
        } catch (erro) { recado(erro.message); }
        finally { enviar.disabled = false; }
      });
      area.append(rolagem, enviar);
    }
    arquivo.addEventListener("change", async () => {
      const f = arquivo.files && arquivo.files[0];
      if (!f) return;
      limpar(area).append(el("p", "Lendo…", "suave"));
      try {
        const r = await api("/planilha", "POST", { nome: f.name, conteudo: await lerArquivo(f) });
        linhas = r.linhas;
        lote = r.lote || 200;
        desenhar();
      } catch (erro) { limpar(area).append(el("p", erro.message, "aviso")); }
    });
    return raiz;
  }
  async function apiCentral(caminho, metodo, corpo) {
    const base = estado.base;
    estado.base = "/v1/fornecedor/servicos";
    try { return await api(caminho, metodo, corpo); } finally { estado.base = base; }
  }
  function botaoPequeno(texto, acao, classe) {
    const b = el("button", texto, "botao pequeno " + (classe || "secundario"));
    b.type = "button";
    b.addEventListener("click", async () => {
      b.disabled = true;
      try { await acao(); } catch (erro) { recado(erro.message); } finally { b.disabled = false; }
    });
    return b;
  }
  async function copiar(texto) {
    try { await navigator.clipboard.writeText(texto); recado("Copiado."); }
    catch (_) { recado("Não consegui copiar: selecione o texto e copie."); }
  }
  async function oferecerCobranca(area, quantidade) {
    // Depois de um envio: lança a implantação (preço fixo) ou o cadastro por produto com um clique.
    let tabela;
    try { tabela = await apiCentral("/precos"); } catch (_) { return; }
    const opcoes = tabela.precos.filter((p) => /implanta|cadastr/i.test(p.descricao));
    if (!opcoes.length) {
      area.append(el("p", "Dica: cadastre em Serviços cobrados um preço de \"Implantação\" ou \"Cadastro por produto\" " +
        "para lançar a cobrança com um clique depois de cada envio.", "suave"));
      return;
    }
    const caixa = el("div", null, "cartao");
    caixa.append(el("strong", "Cobrar este serviço?"));
    opcoes.forEach((p) => {
      const q = p.por_unidade ? quantidade : 1;
      const descricao = p.por_unidade ? p.descricao + " (" + q + " × " + dinheiro(p.valor_cent) + ")" : p.descricao;
      caixa.append(botaoPequeno("Lançar " + descricao + " · " + dinheiro(p.valor_cent * q), async () => {
        await api("/servicos", "POST", { descricao: descricao, valor_cent: p.valor_cent * q });
        recado("Serviço lançado. Cobre pelo Pix em Serviços cobrados.");
        caixa.remove();
      }, ""));
    });
    area.append(caixa);
  }
  async function telaServicos() {
    const [dados, tabela] = await Promise.all([api("/servicos"), apiCentral("/precos")]);
    const raiz = el("section");
    raiz.append(el("h1", "Serviços cobrados desta loja"));
    raiz.append(el("p", "Cadastros em massa e ajustes feitos por você, cobrados à parte da mensalidade. A receber: " +
      dinheiro(dados.a_receber_cent) + ".", "suave"));

    // lançar: da tabela de preços (com quantidade) ou avulso
    const form = el("div", null, "cartao");
    form.append(el("h2", "Lançar serviço"));
    const escolha = el("select");
    escolha.append(new Option("Avulso (digitar)", ""));
    tabela.precos.forEach((p) => escolha.append(new Option(p.descricao + " · " + dinheiro(p.valor_cent) +
      (p.por_unidade ? " cada" : ""), String(p.id))));
    const quantidade = el("input");
    quantidade.placeholder = "Quantidade";
    quantidade.inputMode = "numeric";
    const descricao = el("input");
    descricao.placeholder = "Descrição (ex.: cadastro de 120 produtos da tabacaria)";
    descricao.maxLength = 200;
    const valor = el("input");
    valor.placeholder = "Valor total (R$)";
    valor.inputMode = "decimal";
    function preencher() {
      const p = tabela.precos.find((x) => String(x.id) === escolha.value);
      quantidade.hidden = !(p && p.por_unidade);
      if (!p) return;
      const q = p.por_unidade ? Math.max(parseInt(quantidade.value, 10) || 0, 0) : 1;
      descricao.value = p.por_unidade ? p.descricao + " (" + q + " × " + dinheiro(p.valor_cent) + ")" : p.descricao;
      valor.value = reais(p.valor_cent * q);
    }
    escolha.addEventListener("change", preencher);
    quantidade.addEventListener("input", preencher);
    quantidade.hidden = true;
    const lancar = botaoPequeno("Lançar", async () => {
      const cent = paraCentavos(valor.value);
      if (!descricao.value.trim() || !cent || cent <= 0) { recado("Informe a descrição e o valor."); return; }
      await api("/servicos", "POST", { descricao: descricao.value, valor_cent: cent });
      recarregar();
    }, "");
    form.append(escolha, quantidade, descricao, valor, lancar);
    raiz.append(form);

    // lista
    if (!dados.servicos.length) raiz.append(el("p", "Nenhum serviço lançado ainda.", "vazio cartao"));
    else {
      const lista = el("ul", null, "lista");
      dados.servicos.forEach((sv) => {
        const li = el("li");
        const principal = el("div", null, "principal");
        principal.append(el("strong", sv.descricao),
          el("span", dataBr(sv.criado_em) + (sv.pago_em ? " · pago em " + dataBr(sv.pago_em) :
            sv.pix_copia_cola ? " · Pix enviado, aguardando" : " · a receber"), "suave"));
        li.append(principal, el("span", dinheiro(sv.valor_cent), "valor"));
        if (!sv.pago_em) {
          li.append(botaoPequeno(sv.pix_copia_cola ? "Pix de novo" : "Cobrar no Pix", async () => {
            const r = await api("/servicos/" + sv.id + "/pix", "POST", {});
            await copiar(r.texto);
            if (r.whatsapp) window.open(r.whatsapp, "_blank", "noopener");
            else recado("Pix copiado. A loja não tem WhatsApp no plano: cole na conversa com o dono.");
            recarregar();
          }, ""));
          if (sv.pix_copia_cola) li.append(botaoPequeno("Conferir pagamento", async () => {
            const r = await api("/servicos/" + sv.id + "/conferir", "POST", {});
            recado(r.servico.pago_em ? "Pago! Baixa feita." : "Ainda não foi pago.");
            recarregar();
          }));
          li.append(botaoPequeno("Recebi", async () => { await api("/servicos/" + sv.id + "/pago", "POST", {}); recarregar(); }));
        }
        lista.append(li);
      });
      raiz.append(lista);
    }

    // tabela de preços (vale para todas as lojas)
    const precos = el("div", null, "cartao");
    precos.append(el("h2", "Sua tabela de preços"), el("p", "Vale para todas as lojas. \"Por unidade\" multiplica pela " +
      "quantidade no lançamento (ex.: R$ 1,50 por produto cadastrado).", "suave"));
    const lp = el("ul", null, "lista");
    tabela.precos.forEach((p) => {
      const li = el("li");
      li.append(el("strong", p.descricao), el("span", dinheiro(p.valor_cent) + (p.por_unidade ? " por unidade" : ""), "valor"),
        botaoPequeno("Excluir", async () => { await apiCentral("/precos/" + p.id + "/excluir", "POST", {}); recarregar(); }, "perigo"));
      lp.append(li);
    });
    const nd = el("input"); nd.placeholder = "Serviço (ex.: Cadastro por produto)"; nd.maxLength = 120;
    const nv = el("input"); nv.placeholder = "Valor (R$)"; nv.inputMode = "decimal";
    const nu = el("label"); const caixa = el("input"); caixa.type = "checkbox"; nu.append(caixa, " por unidade");
    precos.append(lp, nd, nv, nu, botaoPequeno("Adicionar preço", async () => {
      const cent = paraCentavos(nv.value);
      if (!nd.value.trim() || !cent || cent <= 0) { recado("Informe o serviço e o valor."); return; }
      await apiCentral("/precos", "POST", { descricao: nd.value, valor_cent: cent, por_unidade: caixa.checked });
      recarregar();
    }, ""));
    raiz.append(precos);
    return raiz;
  }

  // ---------------------------------------------------------------- configurações
  function telaConfig() {
    const config = estado.esquema.config;
    const raiz = el("section");
    raiz.append(el("h1", "Configurações da loja"));
    raiz.append(el("p", "Endereço da nuvem, tokens, e-mail e pastas do computador só mudam no próprio caixa.", "suave"));
    const controles = [];
    const secoes = [];
    config.campos.forEach((c) => { if (!secoes.includes(c.secao)) secoes.push(c.secao); });
    secoes.forEach((secao) => {
      raiz.append(el("h3", secao));
      const grade = el("div", null, "grade-campos cartao");
      config.campos.filter((c) => c.secao === secao).forEach((c) => {
        const atual = config.valores[c.chave];
        const ctl = controle({ rotulo: c.rotulo, tipo: c.tipo === "sn" ? "sn" : c.tipo === "escolha" ? "escolha" : "texto",
                               opcoes: c.opcoes, obrigatorio: c.tipo === "escolha" }, c.tipo === "sn" ? (atual === "S" ? 1 : 0) : atual);
        ctl.chave = c.chave;
        ctl.atual = c.tipo === "sn" ? (atual === "S" ? "S" : "N") : String(atual === null || atual === undefined ? "" : atual);
        ctl.sn = c.tipo === "sn";
        controles.push(ctl);
        grade.append(ctl.no);
      });
      raiz.append(grade);
    });
    const barra = el("div", null, "barra");
    const salvar = el("button", "Enviar alterações", "botao");
    salvar.type = "button";
    salvar.addEventListener("click", async () => {
      const valores = {};
      const rotulos = [];
      controles.forEach((ctl) => {
        let valor = ctl.ler();
        valor = ctl.sn ? (valor ? "S" : "N") : String(valor === null ? "" : valor);
        if (valor !== ctl.atual) { valores[ctl.chave] = valor; rotulos.push(ctl.chave); }
      });
      if (!rotulos.length) return recado("Nada foi alterado.");
      salvar.disabled = true;
      try {
        await pedir("config.salvar", { valores: valores }, "Configurações: " + rotulos.slice(0, 5).join(", ") + (rotulos.length > 5 ? "…" : ""));
        await atualizarContador();
      } catch (erro) { recado(erro.message); }
      salvar.disabled = false;
    });
    barra.append(salvar);
    raiz.append(barra);
    return raiz;
  }

  // ---------------------------------------------------------------- alterações enviadas
  async function telaAlteracoes() {
    const dados = await api("/comandos");
    const raiz = el("section");
    raiz.append(el("h1", "Alterações enviadas"));
    raiz.append(el("p", "O caixa busca as alterações na sincronização (em geral em até 15 minutos com a loja aberta) e responde se aplicou.", "suave"));
    if (!dados.comandos.length) { raiz.append(el("p", "Nenhuma alteração enviada ainda.", "vazio cartao")); return raiz; }
    const lista = el("ul", null, "lista");
    dados.comandos.forEach((c) => {
      const li = el("li");
      const principal = el("div", null, "principal");
      principal.append(el("strong", c.resumo));
      const quem = c.autor === "fornecedor" ? "fornecedor" : "dono";
      principal.append(el("span", "Pedida por " + quem + " em " + quando(c.criado_em)
        + (c.situacao !== "pendente" ? " · resposta em " + quando(c.situacao_em) : ""), "suave"));
      if (c.detalhe) principal.append(el("span", c.detalhe, "suave"));
      const [rotulo, classe] = SITUACOES[c.situacao] || [c.situacao, "espera"];
      const acoes = el("div", null, "acoes");
      acoes.append(el("span", rotulo, "selo " + classe));
      if (c.situacao === "pendente") {
        const cancelar = el("button", "Cancelar", "botao pequeno secundario");
        cancelar.type = "button";
        cancelar.addEventListener("click", async () => {
          cancelar.disabled = true;
          try { await api("/comandos/" + c.id, "DELETE"); recado("Alteração cancelada."); }
          catch (erro) { recado(erro.message); }
          await atualizarContador();
          await recarregar();
        });
        acoes.append(cancelar);
      }
      li.append(principal, acoes);
      lista.append(li);
    });
    raiz.append(lista);
    return raiz;
  }

  async function atualizarContador() {
    try {
      const visao = await api("");
      estado.visao = visao;
      if (visao.esquema) estado.esquema = visao.esquema;
      montarMenu();
      document.querySelectorAll("#menu button").forEach((b) => {
        if (b.dataset.secao === estado.secao) b.setAttribute("aria-current", "page");
      });
      $("espelho-quando").textContent = visao.atualizado_em ? "caixa enviou em " + quando(visao.atualizado_em) : "";
    } catch (_) { /* o próximo carregamento mostra o erro */ }
  }

  // ---------------------------------------------------------------- partida
  $("dialogo-fechar").addEventListener("click", fecharDialogo);
  $("botao-atualizar").addEventListener("click", async () => {
    $("botao-atualizar").disabled = true;
    await carregar();
    $("botao-atualizar").disabled = false;
  });
  // Com alteração esperando o caixa, olha de novo a cada minuto (aba visível, sem diálogo aberto).
  setInterval(() => {
    if (document.hidden || $("dialogo").open || !estado.visao || !estado.visao.pendentes || $("tela-app").hidden) return;
    if (document.activeElement && document.activeElement.tagName === "INPUT") return;
    atualizarContador().then(recarregar);
  }, 60000);
  iniciar();
})();
