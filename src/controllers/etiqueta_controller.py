"""Etiquetas de produto e de preço (texto para visualizar/imprimir e CSV), sem hardware obrigatório.

Reutiliza o preço vigente do cadastro (promoções incluídas), as faixas de atacado e a composição
de fardo. Não altera preço nem estoque. Preço em centavos inteiros.

Etiqueta com código de barras (loja de variedades: meia, copo, utilidade importada sem código de fábrica): o produto sem
código ganha um EAN-13 próprio da loja (`gerar_codigos`, a única gravação daqui) e a folha sai em HTML para o navegador
imprimir, em folha A4 de etiquetas adesivas ou em rolo de impressora de etiquetas (`folha_html`). As barras são desenhadas
aqui mesmo (SVG), sem biblioteca nem fonte instalada.
"""
from __future__ import annotations

import csv
import io
from html import escape

from src.controllers.cadastro_controller import CadastroController
from src.controllers.produto_controller import ProdutoController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

TEMPERATURAS = {"natural": "Natural", "gelada": "Gelada", "ambas": "Natural e gelada"}
MAX_COPIAS_ITEM = 99
MAX_ETIQUETAS = 500
LARGURA = 40

# Prefixos 20 a 29 do EAN são reservados pela GS1 para uso interno da loja: nunca batem com código de fabricante.
PREFIXO_INTERNO = "200"
_L = ("0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011")
_G = ("0100111", "0110011", "0011011", "0100001", "0011101", "0111001", "0000101", "0010001", "0001001", "0010111")
_R = ("1110010", "1100110", "1101100", "1000010", "1011100", "1001110", "1010000", "1000100", "1001000", "1110100")
_PARIDADE = ("LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL")
_SILENCIO = 9          # módulos em branco de cada lado (o leitor precisa da margem)

# chave -> (nome na tela, medidas em mm). `rolo`: uma etiqueta por página, do tamanho dela (impressora de etiquetas).
MODELOS = {
    "a4_33": ("Folha A4 com 33 etiquetas (63,5 x 25,4 mm)",
              {"colunas": 3, "linhas": 11, "largura": 63.5, "altura": 25.4, "topo": 8.8, "esquerda": 7.2, "vao": 2.5}),
    "a4_65": ("Folha A4 com 65 etiquetas (38,2 x 21,2 mm)",
              {"colunas": 5, "linhas": 13, "largura": 38.2, "altura": 21.2, "topo": 10.7, "esquerda": 4.5, "vao": 2.5}),
    "rolo_40x25": ("Rolo 40 x 25 mm (impressora de etiquetas)", {"largura": 40.0, "altura": 25.0, "rolo": True}),
    "rolo_50x30": ("Rolo 50 x 30 mm (impressora de etiquetas)", {"largura": 50.0, "altura": 30.0, "rolo": True}),
}


def digito_ean(sem_digito: str) -> str:
    """Dígito verificador do EAN-13 (12 números) ou do EAN-8 (7 números)."""
    if not sem_digito.isdigit() or len(sem_digito) not in (7, 12):
        raise ErroNegocio("Código de barras inválido.")
    soma = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(sem_digito)))
    return str((10 - soma % 10) % 10)


def ean_valido(codigo: str) -> bool:
    codigo = codigo or ""
    return codigo.isdigit() and len(codigo) in (8, 13) and digito_ean(codigo[:-1]) == codigo[-1]


def codigo_interno(produto_id: int) -> str:
    """EAN-13 próprio da loja para o produto: 200 + número do produto + dígito verificador."""
    if type(produto_id) is not int or not 0 < produto_id < 10 ** 9:
        raise ErroNegocio("Produto inválido para gerar o código de barras.")
    base = PREFIXO_INTERNO + str(produto_id).zfill(9)
    return base + digito_ean(base)


def modulos_ean(codigo: str) -> str:
    """As barras do EAN-13 ou EAN-8 como texto de 0 e 1 (1 = barra preta), um caractere por módulo."""
    if not ean_valido(codigo):
        raise ErroNegocio("Só o código de barras EAN de 8 ou 13 números, com o dígito certo, vira barras.")
    if len(codigo) == 8:
        esquerda = "".join(_L[int(d)] for d in codigo[:4])
        direita = codigo[4:]
    else:
        esquerda = "".join((_L if lado == "L" else _G)[int(d)]
                           for d, lado in zip(codigo[1:7], _PARIDADE[int(codigo[0])]))
        direita = codigo[7:]
    return "101" + esquerda + "01010" + "".join(_R[int(d)] for d in direita) + "101"


def svg_barras(codigo: str) -> str:
    """As barras em SVG que estica até a largura da etiqueta (barras vizinhas viram um retângulo só)."""
    modulos = modulos_ean(codigo)
    total = len(modulos) + 2 * _SILENCIO
    barras, i = [], 0
    while i < len(modulos):
        if modulos[i] == "1":
            fim = i
            while fim < len(modulos) and modulos[fim] == "1":
                fim += 1
            barras.append(f'<rect x="{i + _SILENCIO}" y="0" width="{fim - i}" height="10"/>')
            i = fim
        else:
            i += 1
    return (f'<svg class="barras" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} 10" '
            f'preserveAspectRatio="none" shape-rendering="crispEdges">{"".join(barras)}</svg>')


class EtiquetaController:
    def __init__(self, banco):
        self.banco = banco
        self.produtos = ProdutoController(banco)

    # ------------------------------------------------------- código de barras próprio
    def sem_codigo(self, produto_ids: list[int]) -> list[dict]:
        """Dos produtos escolhidos, os ativos que ainda não têm código de barras."""
        achados = []
        for pid in dict.fromkeys(produto_ids):
            p = self.banco.um("SELECT id, codigo, nome FROM produtos WHERE id = ? AND ativo = 1 "
                              "AND COALESCE(cbarra, '') = ''", (pid,))
            if p:
                achados.append(dict(p))
        return achados

    def gerar_codigos(self, produto_ids: list[int], operador_id: int | None = None) -> int:
        """Dá um código de barras próprio da loja a cada produto escolhido que não tem (quem já tem fica como está).
        Tudo ou nada. Devolve quantos ganharam código."""
        faltando = self.sem_codigo(produto_ids)
        if not faltando:
            return 0
        cadastro = CadastroController(self.banco)
        with self.banco.transacao():
            for p in faltando:
                codigo = codigo_interno(p["id"])
                outro = self.banco.um("SELECT nome FROM produtos WHERE cbarra = ? AND id <> ?", (codigo, p["id"]))
                if outro:
                    raise ErroNegocio(f"O código {codigo} já está em '{outro['nome']}'. Tire-o de lá para gerar o de "
                                      f"'{p['nome']}'.")
                cadastro.salvar("produtos", {"cbarra": codigo}, p["id"])
            self.banco.log("etiqueta_codigos", f"{len(faltando)} código(s) de barras próprios gerados", operador_id)
        return len(faltando)

    def _produto(self, produto_id: int) -> dict:
        r = self.banco.um(
            """SELECT p.*, u.abreviatura AS unidade FROM produtos p
               JOIN unidades u ON u.id = p.unidade_id WHERE p.id = ? AND p.ativo = 1""", (produto_id,))
        if r is None:
            raise ErroNegocio("Produto não encontrado ou inativo.")
        return dict(r)

    def _fardo(self, produto: dict) -> int | None:
        """Unidades por fardo quando o produto é composto por um único insumo (ex.: fardo c/ 12)."""
        comp = self.produtos.composicao(produto["id"])
        if len(comp) == 1 and comp[0]["quantidade"] > 1:
            return int(comp[0]["quantidade"]) if float(comp[0]["quantidade"]).is_integer() else None
        return None

    def etiquetas(self, itens: list[dict]) -> list[dict]:
        """Expande `[{produto_id, copias, temperatura}]` em etiquetas (uma por cópia e temperatura).

        temperatura: 'natural' (padrão), 'gelada' (exige preço gelada) ou 'ambas' (gelada só se houver preço)."""
        if not itens:
            raise ErroNegocio("Selecione ao menos um produto para as etiquetas.")
        saida = []
        for item in itens:
            copias = item.get("copias", 1)
            temp = item.get("temperatura", "natural")
            if type(copias) is not int or not 1 <= copias <= MAX_COPIAS_ITEM:
                raise ErroNegocio(f"Informe de 1 a {MAX_COPIAS_ITEM} cópias por produto.")
            if temp not in TEMPERATURAS:
                raise ErroNegocio("Temperatura inválida.")
            p = self._produto(item["produto_id"])
            tem_gelada = p["preco_gelada_cent"] > 0
            if temp == "gelada" and not tem_gelada:
                raise ErroNegocio(f"'{p['nome']}' não tem preço gelada cadastrado.")
            temps = {"natural": ["natural"], "gelada": ["gelada"],
                     "ambas": ["natural", "gelada"] if tem_gelada else ["natural"]}[temp]
            fardo = self._fardo(p)
            for t in temps:
                gelada = t == "gelada"
                preco = self.produtos.preco_gelada_vigente(p) if gelada else self.produtos.preco_vigente(p)
                qtd_at = p["atacado_gelada_qtd"] if gelada else p["atacado_qtd"]
                preco_at = p["preco_atacado_gelada_cent"] if gelada else p["preco_atacado_cent"]
                tem_atacado = qtd_at > 0 and 0 < preco_at < preco
                for _ in range(copias):
                    saida.append({
                        "produto_id": p["id"], "codigo": p["codigo"], "cbarra": p["cbarra"] or "",
                        "nome": p["nome"], "unidade": p["unidade"], "temperatura": t,
                        "temperatura_rotulo": TEMPERATURAS[t] if tem_gelada else "",
                        "preco_cent": preco, "atacado_qtd": qtd_at if tem_atacado else 0,
                        "atacado_cent": preco_at if tem_atacado else 0, "fardo_qtd": fardo})
                if len(saida) > MAX_ETIQUETAS:
                    raise ErroNegocio(f"Máximo de {MAX_ETIQUETAS} etiquetas por impressão.")
        return saida

    @staticmethod
    def _qtd(q: float) -> str:
        t = fmt.fmt_qtd(q, fmt.CASAS_QTD)
        return t.rstrip("0").rstrip(",") if "," in t else t

    def texto(self, etiquetas: list[dict]) -> str:
        """Prévia/impressão em colunas fixas (cabe em fita de 40 colunas)."""
        blocos = []
        for e in etiquetas:
            nome = e["nome"]
            linhas = [nome[:LARGURA], nome[LARGURA:2 * LARGURA]] if len(nome) > LARGURA else [nome]
            preco = fmt.fmt_brl(e["preco_cent"])
            rotulo = f"  ({e['temperatura_rotulo']})" if e["temperatura_rotulo"] else ""
            linhas.append(f"{preco} / {e['unidade']}{rotulo}")
            if e["atacado_qtd"]:
                linhas.append(f"Atacado: a partir de {self._qtd(e['atacado_qtd'])} un = {fmt.fmt_brl(e['atacado_cent'])}")
            if e["fardo_qtd"]:
                linhas.append(f"Fardo com {e['fardo_qtd']} un")
            linhas.append(f"Cód {e['codigo']}" + (f" | {e['cbarra']}" if e["cbarra"] else ""))
            blocos.append("\n".join(linhas))
        return ("\n" + "-" * LARGURA + "\n").join(blocos)

    def folha_html(self, etiquetas: list[dict], modelo: str = "a4_33", pular: int = 0) -> str:
        """Folha para o navegador imprimir (em 100%, sem "ajustar à página"): nome, barras, número e preço em cada
        etiqueta. Produto sem código EAN sai com o código do cadastro e sem barras. `pular` deixa em branco as primeiras
        etiquetas de uma folha A4 já usada."""
        if modelo not in MODELOS:
            raise ErroNegocio("Modelo de etiqueta desconhecido.")
        if not etiquetas:
            raise ErroNegocio("Selecione ao menos um produto para as etiquetas.")
        m = MODELOS[modelo][1]
        rolo = bool(m.get("rolo"))
        por_folha = 1 if rolo else m["colunas"] * m["linhas"]
        if type(pular) is not int or not 0 <= pular < por_folha:
            raise ErroNegocio(f"Para pular etiquetas já usadas, informe de 0 a {por_folha - 1}.")
        celulas = ['<div class="etiqueta"></div>'] * pular
        for e in etiquetas:
            barras = ean_valido(e["cbarra"])
            numero = e["cbarra"] if barras else f"Cód {e['codigo']}"
            atacado = (f'<span class="atacado">{self._qtd(e["atacado_qtd"])}+ un: {fmt.fmt_brl(e["atacado_cent"])}</span>'
                       if e["atacado_qtd"] and m["altura"] >= 25 else "")
            celulas.append(
                '<div class="etiqueta">'
                f'<div class="nome">{escape(e["nome"])}</div>'
                + (svg_barras(e["cbarra"]) if barras else '<div class="barras"></div>')
                + f'<div class="rodape"><span class="numero">{escape(numero)}</span>{atacado}'
                  f'<span class="preco">{fmt.fmt_brl(e["preco_cent"])}</span></div></div>')
        paginas = [celulas[i:i + por_folha] for i in range(0, len(celulas), por_folha)]
        miolo = "\n".join('<section class="pagina">' + "".join(p) + "</section>" for p in paginas)
        if rolo:
            pagina = f"@page {{ size: {m['largura']}mm {m['altura']}mm; margin: 0; }}"
            grade = f".pagina {{ width: {m['largura']}mm; height: {m['altura']}mm; }}"
        else:
            pagina = "@page { size: A4; margin: 0; }"
            grade = (f".pagina {{ width: 210mm; height: 297mm; padding: {m['topo']}mm 0 0 {m['esquerda']}mm; display: grid; "
                     f"grid-template-columns: repeat({m['colunas']}, {m['largura']}mm); column-gap: {m['vao']}mm; "
                     f"grid-auto-rows: {m['altura']}mm; align-content: start; }}")
        pequena = m["altura"] < 25
        return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Etiquetas com código de barras</title>
<style>
  {pagina}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: "Segoe UI", Arial, sans-serif; color: #000; }}
  {grade}
  .pagina {{ overflow: hidden; break-after: page; }}
  .pagina:last-child {{ break-after: auto; }}
  .etiqueta {{ width: {m['largura']}mm; height: {m['altura']}mm; padding: 1.2mm 2mm; overflow: hidden;
               display: flex; flex-direction: column; }}
  .nome {{ font-size: {'6.5' if pequena else '7.5'}pt; line-height: 1.1; max-height: 2.2em; overflow: hidden; font-weight: 600; }}
  .barras {{ display: block; width: 100%; flex: 1 1 auto; min-height: 0; margin: 0.6mm 0; }}
  .rodape {{ display: flex; justify-content: space-between; align-items: baseline; gap: 1mm; white-space: nowrap; }}
  .numero {{ font-size: {'6' if pequena else '7'}pt; letter-spacing: .03em; }}
  .atacado {{ font-size: 6pt; }}
  .preco {{ font-size: {'9' if pequena else '11'}pt; font-weight: 800; }}
  @media screen {{
    body {{ background: #e9edf0; }}
    .pagina {{ margin: 6mm auto; background: #fff; box-shadow: 0 1px 4px #0003; }}
    .etiqueta {{ outline: 1px dashed #c3cad1; }}
  }}
</style>
</head>
<body>
{miolo}
</body>
</html>
"""

    @staticmethod
    def _seguro(valor) -> str:
        t = "" if valor is None else str(valor)
        return "'" + t if t[:1] in ("=", "+", "-", "@") else t

    def csv(self, etiquetas: list[dict]) -> str:
        """CSV (';' e vírgula decimal) para planilha ou gráfica."""
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        w.writerow(["codigo", "nome", "codigo_barras", "unidade", "temperatura", "preco",
                    "atacado_qtd", "preco_atacado", "fardo_qtd"])
        for e in etiquetas:
            w.writerow([self._seguro(e["codigo"]), self._seguro(e["nome"]), self._seguro(e["cbarra"]), e["unidade"],
                        e["temperatura_rotulo"], fmt.fmt_num(e["preco_cent"]),
                        self._qtd(e["atacado_qtd"]) if e["atacado_qtd"] else "",
                        fmt.fmt_num(e["atacado_cent"]) if e["atacado_qtd"] else "", e["fardo_qtd"] or ""])
        return buf.getvalue()