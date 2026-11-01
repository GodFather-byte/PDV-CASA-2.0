/* PDF simples do relatório, sem biblioteca. Texto e barras dos produtos. */
function baixarPdf(nome, linhas, barras) {
  const objetos = [];
  function add(texto) { objetos.push(texto); return objetos.length; }
  const fonte = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
  let conteudo = "BT /F1 11 Tf 40 800 Td 14 TL\n";
  (linhas || []).slice(0, 48).forEach((linha) => {
    const seguro = String(linha || "").replace(/[()\\]/g, " ").slice(0, 90);
    conteudo += "(" + seguro + ") '\n";
  });
  conteudo += "ET\n";
  (barras || []).slice(0, 8).forEach((barra, i) => {
    const largura = Math.max(2, Math.min(400, Number(barra.largura) || 0));
    const y = 200 - i * 18;
    conteudo += "0.2 0.35 0.55 rg " + 40 + " " + y + " " + largura + " 12 re f\n";
  });
  const fluxo = add("<< /Length " + conteudo.length + " >>\nstream\n" + conteudo + "endstream");
  const pagina = add("<< /Type /Page /Parent 4 0 R /MediaBox [0 0 595 842] /Contents " + fluxo +
    " 0 R /Resources << /Font << /F1 " + fonte + " 0 R >> >> >>");
  const paginas = add("<< /Type /Pages /Kids [" + pagina + " 0 R] /Count 1 >>");
  const catalogo = add("<< /Type /Catalog /Pages " + paginas + " 0 R >>");
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  objetos.forEach((obj, i) => {
    offsets.push(pdf.length);
    pdf += (i + 1) + " 0 obj\n" + obj + "\nendobj\n";
  });
  const inicio = pdf.length;
  pdf += "xref\n0 " + (objetos.length + 1) + "\n0000000000 65535 f \n";
  offsets.slice(1).forEach((o) => { pdf += String(o).padStart(10, "0") + " 00000 n \n"; });
  pdf += "trailer << /Size " + (objetos.length + 1) + " /Root " + catalogo + " 0 R >>\nstartxref\n" + inicio + "\n%%EOF";
  const blob = new Blob([pdf], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nome;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
