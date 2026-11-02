const assert = require("node:assert");
const test = require("node:test");
const pdf = require("../backend/painel_web/pdf.js");

test("o PDF abre e o xref aponta para os objetos", () => {
  const bytes = pdf.montarPdf(["Resumo do Bar", "Total R$ 7.875,00", "Diferença R$ 8,00"]);
  const texto = Buffer.from(bytes).toString("latin1");
  assert.ok(texto.startsWith("%PDF-1.4"));
  assert.ok(texto.includes("%%EOF"));
  const inicio = texto.match(/startxref\n(\d+)/)[1];
  assert.equal(texto.slice(Number(inicio), Number(inicio) + 4), "xref");
  assert.ok(texto.includes("(Resumo do Bar)"));
  assert.ok(texto.includes("WinAnsiEncoding"));
});

test("iPhone em app usa aba e o desktop baixa o arquivo", () => {
  assert.equal(pdf.modoDeEntrega({ podeCompartilharArquivo: true, standalone: true }), "share");
  assert.equal(pdf.modoDeEntrega({ podeCompartilharArquivo: false, standalone: true }), "aba");
  assert.equal(pdf.modoDeEntrega({ podeCompartilharArquivo: false, standalone: false }), "download");
});
