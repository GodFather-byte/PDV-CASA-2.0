// Teste grátis pelo site: manda o formulário e mostra o instalador, o código e a senha do painel.
(function () {
  "use strict";
  const form = document.getElementById("form-teste");
  if (!form) return;
  const aviso = document.getElementById("teste-aviso");
  const pronto = document.getElementById("teste-pronto");

  function preencher(dados) {
    pronto.querySelectorAll("[data-campo]").forEach((no) => {
      const campo = no.dataset.campo;
      const valor = dados[campo];
      if (campo === "qr_instalacao") {
        // SVG gerado pela própria nuvem (segno): só desenha se for mesmo um <svg>.
        if (typeof valor === "string" && valor.trim().startsWith("<svg")) no.innerHTML = valor;
      } else if (no.tagName === "A") {
        no.href = valor || "#";
        if (campo === "painel") no.textContent = valor || "";
        if (campo === "zap_ajuda" || campo === "instalador") { no.target = "_blank"; no.rel = "noopener"; }
      } else if (no.tagName === "TEXTAREA") {
        no.value = valor || "";
      } else if (campo === "validade" && valor) {
        no.textContent = valor.split("-").reverse().join("/");
      } else {
        no.textContent = valor || "";
      }
    });
  }

  form.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const dados = Object.fromEntries(new FormData(form));
    dados.aceite = form.elements.aceite.checked;
    if (!form.reportValidity()) return;
    const botao = form.querySelector("button[type=submit]");
    botao.disabled = true;
    aviso.textContent = "Criando a sua loja de teste…";
    try {
      const r = await fetch("/v1/site/teste", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(dados) });
      const corpo = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof corpo.detail === "string" ? corpo.detail : "Não deu certo. Chame no WhatsApp.");
      preencher(corpo);
      form.hidden = true;
      pronto.hidden = false;
      pronto.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (erro) {
      aviso.textContent = erro.message;
      botao.disabled = false;
    }
  });

  const copiar = document.getElementById("copiar-codigo");
  if (copiar) copiar.addEventListener("click", async () => {
    const campo = pronto.querySelector('[data-campo="codigo_instalacao"]');
    try { await navigator.clipboard.writeText(campo.value); copiar.textContent = "Copiado!"; }
    catch (_) { campo.select(); }
  });
})();

// Mensal ou anual: troca o preço em destaque. Sem este script, o mensal e a linha do ano continuam visíveis.
(function () {
  "use strict";
  const grupos = document.querySelectorAll(".troca-periodo");
  if (!grupos.length) return;

  function aplicar(periodo) {
    const anual = periodo === "anual";
    document.body.classList.toggle("periodo-anual", anual);
    grupos.forEach((grupo) => {
      grupo.querySelectorAll("button[data-periodo]").forEach((botao) => {
        const ativo = botao.dataset.periodo === periodo;
        botao.classList.toggle("ativo", ativo);
        botao.setAttribute("aria-pressed", ativo ? "true" : "false");
      });
    });
  }

  grupos.forEach((grupo) => {
    grupo.addEventListener("click", (evento) => {
      const botao = evento.target.closest("button[data-periodo]");
      if (!botao) return;
      aplicar(botao.dataset.periodo);
    });
  });
})();
