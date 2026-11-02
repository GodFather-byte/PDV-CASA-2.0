/* PDF do resumo em WinAnsi, com deslocamento em bytes. O download cobre
   Chrome (Android e desktop) e o Safari do iPhone, inclusive o app na tela de início. */
var PDF_WINANSI = {
  "Á": 0xC1, "À": 0xC0, "Â": 0xC2, "Ã": 0xC3, "á": 0xE1, "à": 0xE0, "â": 0xE2, "ã": 0xE3,
  "É": 0xC9, "Ê": 0xCA, "é": 0xE9, "ê": 0xEA, "Í": 0xCD, "í": 0xED, "Ó": 0xD3, "Ô": 0xD4,
  "Õ": 0xD5, "ó": 0xF3, "ô": 0xF4, "õ": 0xF5, "Ú": 0xDA, "ú": 0xFA, "Ç": 0xC7, "ç": 0xE7,
  "º": 0xBA, "ª": 0xAA
};

function pdfEscapar(linha) {
  var bytes = [];
  var texto = String(linha || "").slice(0, 90);
  for (var i = 0; i < texto.length; i++) {
    var ch = texto.charAt(i);
    var cod = PDF_WINANSI[ch] || ch.charCodeAt(0);
    if (cod > 255) cod = 63;
    if (cod === 40 || cod === 41 || cod === 92) bytes.push(92);
    bytes.push(cod);
  }
  return bytes;
}

function montarPdf(linhas) {
  var partes = [];
  function pushStr(s) {
    for (var i = 0; i < s.length; i++) partes.push(s.charCodeAt(i) & 255);
  }
  function pushBytes(lista) { lista.forEach(function (n) { partes.push(n & 255); }); }
  var objetos = [];
  function add(construir) { objetos.push(construir); return objetos.length; }
  var fonte = add(function () { pushStr("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"); });
  var fluxo = add(function () {
    var corpo = [];
    function b(s) { for (var i = 0; i < s.length; i++) corpo.push(s.charCodeAt(i) & 255); }
    b("BT /F1 11 Tf 40 800 Td 14 TL\n");
    (linhas || []).slice(0, 48).forEach(function (linha) {
      b("(");
      pdfEscapar(linha).forEach(function (n) { corpo.push(n); });
      b(") '\n");
    });
    b("ET\n");
    pushStr("<< /Length " + corpo.length + " >>\nstream\n");
    pushBytes(corpo);
    pushStr("\nendstream");
  });
  var pagina = add(function () {
    pushStr("<< /Type /Page /Parent 4 0 R /MediaBox [0 0 595 842] /Contents " + fluxo +
      " 0 R /Resources << /Font << /F1 " + fonte + " 0 R >> >> >>");
  });
  var paginas = add(function () {
    pushStr("<< /Type /Pages /Kids [" + pagina + " 0 R] /Count 1 >>");
  });
  var catalogo = add(function () {
    pushStr("<< /Type /Catalog /Pages " + paginas + " 0 R >>");
  });
  pushStr("%PDF-1.4\n");
  var offsets = [0];
  objetos.forEach(function (construir, indice) {
    offsets.push(partes.length);
    pushStr((indice + 1) + " 0 obj\n");
    construir();
    pushStr("\nendobj\n");
  });
  var inicio = partes.length;
  pushStr("xref\n0 " + (objetos.length + 1) + "\n");
  pushStr("0000000000 65535 f \n");
  offsets.slice(1).forEach(function (o) {
    pushStr(String(o).padStart(10, "0") + " 00000 n \n");
  });
  pushStr("trailer << /Size " + (objetos.length + 1) + " /Root " + catalogo + " 0 R >>\nstartxref\n" + inicio + "\n%%EOF");
  return new Uint8Array(partes);
}

function modoDeEntrega(opcoes) {
  opcoes = opcoes || {};
  if (opcoes.podeCompartilharArquivo) return "share";
  if (opcoes.standalone) return "aba";
  return "download";
}

function baixarPdf(nome, linhas) {
  var bytes = montarPdf(linhas);
  var arquivo = new File([bytes], nome || "resumo-willpdv.pdf", { type: "application/pdf" });
  var standalone = window.navigator.standalone === true ||
    (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches);
  var pode = navigator.canShare && navigator.canShare({ files: [arquivo] });
  var modo = modoDeEntrega({ podeCompartilharArquivo: !!pode, standalone: standalone });
  if (modo === "share") {
    return navigator.share({ files: [arquivo], title: nome || "Resumo" }).catch(function () {
      return abrirPdfNoNavegador(bytes, nome);
    });
  }
  if (modo === "aba") return abrirPdfNoNavegador(bytes, nome);
  return baixarPdfPorLink(bytes, nome);
}

function baixarPdfPorLink(bytes, nome) {
  var blob = new Blob([bytes], { type: "application/pdf" });
  var url = URL.createObjectURL(blob);
  var ancora = document.createElement("a");
  ancora.href = url;
  ancora.download = nome || "resumo-willpdv.pdf";
  ancora.rel = "noopener";
  document.body.appendChild(ancora);
  ancora.click();
  setTimeout(function () {
    ancora.remove();
    URL.revokeObjectURL(url);
  }, 60000);
}

function abrirPdfNoNavegador(bytes, nome) {
  var blob = new Blob([bytes], { type: "application/pdf" });
  var url = URL.createObjectURL(blob);
  var aberto = window.open(url, "_blank");
  if (!aberto) window.location.href = url;
  setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { montarPdf: montarPdf, modoDeEntrega: modoDeEntrega, pdfEscapar: pdfEscapar };
}
