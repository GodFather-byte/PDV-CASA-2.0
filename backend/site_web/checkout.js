// Checkout do site: abre o formulário e manda a pessoa ao Mercado Pago.
// O preço não vai neste pedido — o servidor escolhe pelo id do plano.
(function () {
  "use strict";
  const dialog = document.getElementById("checkout");
  const form = document.getElementById("form-checkout");
  if (!dialog || !form) return;
  const titulo = document.getElementById("checkout-titulo");
  const preco = document.getElementById("checkout-preco");
  const aviso = document.getElementById("checkout-aviso");
  const nota = document.getElementById("checkout-nota");
  const zap = document.getElementById("checkout-zap");
  const fechar = document.getElementById("checkout-fechar");

  function periodoAnual() {
    return document.body.classList.contains("periodo-anual");
  }

  function textoPreco(botao) {
    const cartao = botao.closest(".cartao");
    if (!cartao) return "";
    const no = cartao.querySelector(periodoAnual() ? ".preco-ano" : ".preco-mes");
    if (!no) return "";
    const copia = no.cloneNode(true);
    copia.querySelectorAll("small, .selo-gratis").forEach((el) => el.remove());
    return copia.textContent.replace(/\s+/g, " ").trim();
  }

  function abrir(botao) {
    const anual = periodoAnual();
    form.dataset.plano = (botao.dataset.plano || "") + (anual ? "-anual" : "-mensal");
    form.dataset.zap = botao.dataset.zap || "";
    if (titulo) titulo.textContent = (anual ? "Comprar " : "Assinar ") + (botao.dataset.nome || "o plano");
    if (preco) preco.textContent = textoPreco(botao);
    if (nota) {
      nota.textContent = anual
        ? "Pix ou cartão. No cartão, até 10 vezes. A instalação é grátis."
        : "Pix ou cartão, à vista. A instalação é grátis.";
    }
    if (aviso) aviso.textContent = "";
    if (zap && botao.dataset.zap && botao.dataset.zap.indexOf("https://wa.me/") === 0) {
      zap.href = botao.dataset.zap;
    }
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  document.querySelectorAll(".checkout-abrir").forEach((botao) => {
    botao.addEventListener("click", () => abrir(botao));
  });

  if (fechar) fechar.addEventListener("click", () => {
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  });

  function detalhe(corpo) {
    if (corpo && typeof corpo.detail === "string" && corpo.detail) return corpo.detail;
    return "Não deu certo. Chame no WhatsApp.";
  }

  form.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    if (!form.reportValidity()) return;
    const dados = Object.fromEntries(new FormData(form));
    const botao = form.querySelector("button[type=submit]");
    botao.disabled = true;
    if (aviso) aviso.textContent = "Abrindo o pagamento…";
    try {
      const r = await fetch("/v1/pagamentos/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plano: form.dataset.plano,
          nome: dados.nome,
          email: dados.email,
          whatsapp: dados.whatsapp,
          loja: dados.loja
        })
      });
      const corpo = await r.json().catch(() => ({}));
      if (r.status === 503 && form.dataset.zap && form.dataset.zap.indexOf("https://wa.me/") === 0) {
        window.location.href = form.dataset.zap;
        return;
      }
      if (!r.ok) throw new Error(detalhe(corpo));
      const link = corpo.init_point;
      if (typeof link !== "string" || link.indexOf("https://") !== 0) {
        throw new Error("O Mercado Pago não devolveu o link de pagamento.");
      }
      window.location.href = link;
    } catch (erro) {
      if (aviso) aviso.textContent = erro.message;
      botao.disabled = false;
    }
  });
})();
