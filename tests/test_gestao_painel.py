"""Relatórios e cadastros em lote do painel: prévia, fila que o caixa antigo já aplica, e exportação."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import unittest
from datetime import date
from decimal import Decimal

from src.core.erros import ErroNegocio

try:
    from backend.gestao_painel import (
        classificar_abc, montar_rede, preco_reajustado, previa_reajuste, sugerir_compra,
    )
except (ImportError, RuntimeError):
    classificar_abc = montar_rede = preco_reajustado = previa_reajuste = sugerir_compra = None

try:
    from src.sync import retaguarda
    from tests.test_notas_dono import _Ponte
    from tests.test_painel_dono import BaseNuvem, TestClient, nuvem
    from tests.test_retaguarda import nuvem_retaguarda
except (ImportError, RuntimeError):
    BaseNuvem = TestClient = nuvem = nuvem_retaguarda = _Ponte = retaguarda = None


def _catalogo_vinho():
    return {
        "tem_cadastro": True, "quando": "2026-10-03 21:00:00",
        "grupos": [{"id": 1, "nome": "Vinhos"}],
        "subgrupos": [{"id": 7, "nome": "Tinto", "grupo_id": 1}],
        "produtos": [
            {"id": 1, "codigo": "10", "nome": "VINHO", "subgrupo_id": 7, "preco_cent": 5000,
             "custo_medio_cent": 2000, "qt_atual": 2, "estoque_minimo": 6, "controla_estoque": 1, "ativo": 1},
            {"id": 2, "codigo": "11", "nome": "LICOR", "subgrupo_id": 7, "preco_cent": 4000,
             "qt_atual": 8, "estoque_minimo": 1, "controla_estoque": 1, "ativo": 1},
        ],
    }


@unittest.skipIf(preco_reajustado is None, "backend indisponível")
class TesteContas(unittest.TestCase):
    def test_reajuste_arredonda_meio_centavo_para_cima(self):
        self.assertEqual(preco_reajustado(800, Decimal("10")), 880)
        self.assertEqual(preco_reajustado(199, Decimal("10")), 219)
        self.assertEqual(preco_reajustado(333, Decimal("-10")), 300)

    def test_abc_corta_em_80_e_95(self):
        linhas = classificar_abc([
            {"nome": "A1", "valor_cent": 50}, {"nome": "A2", "valor_cent": 30},
            {"nome": "B", "valor_cent": 15}, {"nome": "C", "valor_cent": 5},
        ])
        self.assertEqual([l["classe"] for l in linhas], ["A", "A", "B", "C"])
        self.assertEqual(linhas[-1]["acumulado_bp"], 10000)

    def test_reajuste_por_grupo_e_recusa_categoria_ambigua(self):
        previa = previa_reajuste(_catalogo_vinho(), "Vinhos", Decimal("10"))
        por_id = {p["id"]: p["valores"]["preco_cent"] for p in previa}
        self.assertEqual(por_id, {1: 5500, 2: 4400})
        catalogo = _catalogo_vinho()
        catalogo["subgrupos"].append({"id": 8, "nome": "Tinto", "grupo_id": 2})
        catalogo["grupos"].append({"id": 2, "nome": "Outros"})
        with self.assertRaises(ErroNegocio) as ctx:
            previa_reajuste(catalogo, "Tinto", Decimal("5"))
        self.assertIn("Subgrupo - Grupo", str(ctx.exception))

    def test_sugestao_cobre_sete_dias_e_separa_parado(self):
        vendas = [{"status": "fechada", "itens": [
            {"nome": "VINHO", "codigo": "10", "quantidade": 14, "total_cent": 70000, "cancelado": 0, "grupo": "Vinhos"},
        ]}]
        rel = sugerir_compra(_catalogo_vinho(), vendas, date(2026, 10, 1), date(2026, 10, 7))
        self.assertTrue(rel["disponivel"])
        self.assertEqual(rel["sugestao"][0]["comprar"], 12)
        self.assertEqual(rel["baixo"][0]["nome"], "VINHO")
        self.assertEqual(rel["parados"][0]["nome"], "LICOR")
        self.assertEqual(rel["parados"][0]["valor_parado_cent"], 32000)
        curto = sugerir_compra(_catalogo_vinho(), vendas, date(2026, 10, 3), date(2026, 10, 3))
        self.assertEqual(curto["parados"], [])

    def test_rede_traz_ticket_inteiro(self):
        rel = montar_rede([
            {"nome": "Centro", "chave": "A", "vendas": 2, "faturamento_cent": 3000, "lucro_cent": 1000, "margem": "33,33%"},
            {"nome": "Bairro", "chave": "B", "vendas": 0, "faturamento_cent": 0, "lucro_cent": 0, "margem": "—"},
        ], {"faturamento_cent": 3000, "lucro_cent": 1000})
        self.assertEqual(rel["linhas"][0]["ticket_medio_cent"], 1500)
        self.assertEqual(rel["linhas"][1]["ticket_medio_cent"], 0)
        self.assertTrue(all(isinstance(l["ticket_medio_cent"], int) for l in rel["linhas"]))


@unittest.skipIf(TestClient is None or nuvem_retaguarda is None, "fastapi/httpx não instalados")
class TesteApi(BaseNuvem):
    def setUp(self):
        super().setUp()
        from backend.importacao_painel import PainelImportacao, PainelTokenApi
        with nuvem.SessionLocal() as db:
            db.query(PainelImportacao).delete()
            db.query(PainelTokenApi).delete()
            db.query(nuvem_retaguarda.RetaguardaComando).delete()
            db.query(nuvem_retaguarda.RetaguardaEspelho).delete()
            db.commit()
        self.banco.cfg_set("retaguarda_nuvem", "S")
        self.dono = self.entrar()
        self.ponte = _Ponte(self.http)
        retaguarda.sincronizar(self.banco, self.ponte, forcar=True)

    def comandos(self):
        with nuvem.SessionLocal() as db:
            return db.query(nuvem_retaguarda.RetaguardaComando).filter_by(chave_loja="ADEGA-1").count()

    def test_sem_sessao_recusa_e_a_pagina_tem_os_seletores(self):
        self.assertEqual(self.http.get("/v1/painel/gestao/resumo").status_code, 401)
        self.assertEqual(self.http.post("/v1/painel/gestao/precos", json={"itens": []}).status_code, 401)
        pagina = self.http.get("/painel/").text
        for ident in ("bloco-top-dia", "lista-top-dia", "bloco-relatorios-gestao", "lista-gestao-abc",
                      "lista-gestao-operadores", "lista-gestao-sugestao", "exportar-relatorio-csv",
                      "exportar-relatorio-xlsx", "exportar-rede-csv"):
            self.assertIn(ident, pagina)
        js = self.http.get("/retaguarda/app.js").text
        self.assertIn("reajuste-abrir", js)
        self.assertIn("estoque-enviar", js)
        self.assertIn('data-seletor="relatorio-abc"', self.http.get("/painel/").text)

    def test_resumo_abc_e_csv_da_venda_do_dia(self):
        self.venda_fechada((self.skol, 2))
        self.subir()
        resumo = self.http.get("/v1/painel/gestao/resumo", params={"de": "2026-10-03", "ate": "2026-10-03"},
                               headers=self.dono)
        self.assertEqual(resumo.status_code, 200, resumo.text)
        corpo = resumo.json()
        self.assertTrue(corpo["custo_visivel"])
        self.assertEqual(corpo["vendas"], 1)
        self.assertGreater(corpo["faturamento_cent"], 0)
        self.assertEqual(corpo["top_produtos"][0]["nome"], "SKOL")
        self.assertIsInstance(corpo["ticket_medio_cent"], int)
        abc = self.http.get("/v1/painel/gestao/relatorio", params={"tipo": "abc", "de": "2026-10-03", "ate": "2026-10-03"},
                            headers=self.dono)
        self.assertEqual(abc.json()["linhas"][0]["classe"], "A")
        operadores = self.http.get("/v1/painel/gestao/relatorio",
                                   params={"tipo": "operadores", "de": "2026-10-03", "ate": "2026-10-03"},
                                   headers=self.dono)
        self.assertEqual(operadores.status_code, 200, operadores.text)
        self.assertGreaterEqual(operadores.json()["linhas"][0]["vendas"], 1)
        csv = self.http.get("/v1/painel/gestao/relatorio",
                            params={"tipo": "abc", "de": "2026-10-03", "ate": "2026-10-03", "formato": "csv"},
                            headers=self.dono)
        self.assertEqual(csv.status_code, 200, csv.text)
        self.assertIn("Classe", csv.text)
        self.assertIn("SKOL", csv.text)
        xlsx = self.http.get("/v1/painel/gestao/relatorio",
                             params={"tipo": "produtos", "de": "2026-10-03", "ate": "2026-10-03", "formato": "xlsx"},
                             headers=self.dono)
        self.assertEqual(xlsx.status_code, 200)
        self.assertTrue(xlsx.content.startswith(b"PK"))
        outra = self.http.get("/v1/painel/gestao/resumo", params={"loja": "ADEGA-2"}, headers=self.dono)
        self.assertEqual(outra.status_code, 403)
        self.assertEqual(self.http.get("/v1/painel/gestao/relatorio", params={"tipo": "rede"}, headers=self.dono).status_code, 422)

    def test_reajuste_e_estoque_so_gravam_com_dry_run_false_e_o_caixa_aplica(self):
        grupo = self.banco.valor(
            "SELECT g.nome FROM produtos p JOIN subgrupos s ON s.id = p.subgrupo_id "
            "JOIN grupos g ON g.id = s.grupo_id WHERE p.id = ?", (self.skol,))
        antes = self.comandos()
        previa = self.http.post("/v1/painel/gestao/reajuste",
                                json={"categoria": grupo, "percentual": 10}, headers=self.dono)
        self.assertEqual(previa.status_code, 200, previa.text)
        self.assertTrue(previa.json()["dry_run"])
        self.assertEqual(self.comandos(), antes)
        skol = next(a for a in previa.json()["alteracoes"] if a["id"] == self.skol)
        self.assertEqual(skol["valores"]["preco_cent"], 880)
        ruim = self.http.post("/v1/painel/gestao/reajuste", json={"categoria": grupo, "percentual": 0}, headers=self.dono)
        self.assertEqual(ruim.status_code, 422)
        aplicado = self.http.post("/v1/painel/gestao/reajuste",
                                  json={"categoria": grupo, "percentual": 10, "dry_run": False}, headers=self.dono)
        self.assertEqual(aplicado.status_code, 200, aplicado.text)
        self.assertFalse(aplicado.json()["dry_run"])
        self.assertGreaterEqual(aplicado.json()["enviados"], 1)
        with nuvem.SessionLocal() as db:
            comando = db.query(nuvem_retaguarda.RetaguardaComando).filter_by(chave_loja="ADEGA-1").order_by(
                nuvem_retaguarda.RetaguardaComando.id.desc()).first()
            dados = json.loads(comando.dados)
        self.assertEqual(comando.tipo, "cadastro.salvar")
        self.assertEqual(dados["valores"]["preco_cent"], 880)
        self.assertIsInstance(dados["valores"]["preco_cent"], int)
        retaguarda.sincronizar(self.banco, self.ponte, forcar=True)
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (self.skol,)), 880)

        seco = self.http.post("/v1/painel/gestao/estoque",
                              json={"id": self.skol, "tipo": "entrada", "quantidade": 6, "motivo": "Compra da adega"},
                              headers=self.dono)
        self.assertTrue(seco.json()["dry_run"])
        sem_motivo = self.http.post("/v1/painel/gestao/estoque",
                                    json={"id": self.skol, "tipo": "entrada", "quantidade": 6, "motivo": "ok", "dry_run": False},
                                    headers=self.dono)
        self.assertEqual(sem_motivo.status_code, 422)
        movimento = self.http.post("/v1/painel/gestao/estoque", json={
            "id": self.skol, "tipo": "entrada", "quantidade": 6, "motivo": "Compra da adega", "dry_run": False,
        }, headers=self.dono)
        self.assertEqual(movimento.status_code, 200, movimento.text)
        with nuvem.SessionLocal() as db:
            ultimo = db.query(nuvem_retaguarda.RetaguardaComando).filter_by(chave_loja="ADEGA-1").order_by(
                nuvem_retaguarda.RetaguardaComando.id.desc()).first()
        self.assertEqual(ultimo.tipo, "estoque.movimento")
        retaguarda.sincronizar(self.banco, self.ponte, forcar=True)
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.skol,)), 106)

    def test_preco_em_massa_e_token_da_loja(self):
        token = self.http.post("/v1/painel/importacao/tokens", json={"nome": "assistente"}, headers=self.dono)
        self.assertEqual(token.status_code, 200, token.text)
        segredo = token.json()["token"]
        self.assertTrue(segredo.startswith("wpdv_"))
        cabeca = {"Authorization": "Bearer " + segredo}
        consulta = self.http.get("/v1/painel/gestao/produtos", params={"q": "SKOL"}, headers=cabeca)
        self.assertEqual(consulta.status_code, 200, consulta.text)
        self.assertEqual(consulta.json()["produtos"][0]["preco_cent"], 800)
        self.assertTrue(consulta.json()["custo_visivel"])
        outra = self.http.get("/v1/painel/gestao/produtos", params={"loja": "ADEGA-2"}, headers=cabeca)
        self.assertEqual(outra.status_code, 403)
        previa = self.http.post("/v1/painel/gestao/precos", json={"itens": [
            {"id": self.skol, "preco_cent": 990, "estoque_minimo": 4},
        ]}, headers=cabeca)
        self.assertTrue(previa.json()["dry_run"])
        self.assertEqual(previa.json()["alteracoes"][0]["valores"]["preco_cent"], 990)
        aplicado = self.http.post("/v1/painel/gestao/precos", json={
            "dry_run": False, "itens": [{"id": self.skol, "preco_cent": 990, "estoque_minimo": 4, "ativo": 1}],
        }, headers=cabeca)
        self.assertEqual(aplicado.status_code, 200, aplicado.text)
        retaguarda.sincronizar(self.banco, self.ponte, forcar=True)
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (self.skol,)), 990)
        aud = self.http.get("/v1/painel/gestao/auditoria", headers=cabeca)
        self.assertEqual(aud.status_code, 200, aud.text)
        self.assertIn("token:assistente", aud.text)
        self.assertNotIn(segredo, aud.text)
