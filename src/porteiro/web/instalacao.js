/* O Safari no iPhone/iPad não emite beforeinstallprompt: mostramos o caminho de instalação manual. */
(() => {
  const botao = document.getElementById("botao-instalar");
  const ajuda = document.getElementById("ajuda-instalar");
  const fechar = document.getElementById("botao-fechar-instalar");
  const modoApp = window.matchMedia("(display-mode: standalone)");
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  let convite = null;
  let instalado = false;

  function atualizar() {
    const emApp = instalado || modoApp.matches || navigator.standalone === true;
    botao.hidden = emApp || (!ios && !convite);
    botao.textContent = ios ? "Instalar no iPhone/iPad" : "Instalar";
    if (emApp) {
      ajuda.hidden = true;
      botao.setAttribute("aria-expanded", "false");
    }
  }

  function fecharAjuda() {
    ajuda.hidden = true;
    botao.setAttribute("aria-expanded", "false");
    botao.focus();
  }

  window.addEventListener("beforeinstallprompt", (evento) => {
    evento.preventDefault();
    convite = evento;
    atualizar();
  });
  window.addEventListener("appinstalled", () => {
    instalado = true;
    convite = null;
    atualizar();
  });
  if (modoApp.addEventListener) modoApp.addEventListener("change", atualizar);

  botao.addEventListener("click", async () => {
    if (convite) {
      const evento = convite;
      convite = null;
      botao.disabled = true;
      try {
        await evento.prompt();
        if ((await evento.userChoice).outcome === "accepted") instalado = true;
      } catch (_erro) {
        // O navegador pode invalidar um convite; um próximo beforeinstallprompt habilita novamente.
      } finally {
        botao.disabled = false;
        atualizar();
      }
    } else if (ios) {
      ajuda.hidden = !ajuda.hidden;
      botao.setAttribute("aria-expanded", String(!ajuda.hidden));
      document.getElementById("instalar-http").hidden = location.protocol === "https:";
      if (!ajuda.hidden) ajuda.focus();
    }
  });
  fechar.addEventListener("click", fecharAjuda);
  ajuda.addEventListener("keydown", (evento) => {
    if (evento.key === "Escape") fecharAjuda();
  });
  atualizar();
})();
