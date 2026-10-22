"""Etiquetas de produto e de preço (texto para visualizar/imprimir e CSV), sem hardware obrigatório.

Reutiliza o preço vigente do cadastro (promoções incluídas), as faixas de atacado e a composição
de fardo. Somente leitura: não altera produto, preço nem estoque. Preço em centavos inteiros.
"""
from __future__ import annotations

import csv
import io

from src.controllers.produto_controller import ProdutoController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio

TEMPERATURAS = {"natural": "Natural", "gelada": "Gelada", "ambas": "Natural e gelada"}
MAX_COPIAS_ITEM = 99
MAX_ETIQUETAS = 500
LARGURA = 40


class EtiquetaController:
    def __init__(self, banco):
        self.banco = banco
        self.produtos = ProdutoController(banco)

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
                preco = p["preco_gelada_cent"] if gelada else self.produtos.preco_vigente(p)
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