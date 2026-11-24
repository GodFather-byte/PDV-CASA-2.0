"""Planilha de produtos no painel: a mesma leitura do caixa, prévia por código de barras e fila para o caixa."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest

from src.controllers.importacao_produtos import (
    ImportacaoProdutos, aviso_ean, classificar_espelho, escrever_xlsx, ler_tabela_dados,
)
from src.controllers.retaguarda_controller import RetaguardaController
from tests.base import BaseTeste

BARRAS = "7891234567895"          # EAN-13 com dígito certo
BARRAS_RUIM = "7891234567890"


def _grupos(*nomes):
    return {ImportacaoProdutos._k(n) for n in nomes}


class TesteParserEPrevia(unittest.TestCase):
    def test_ean_avisa_sem_recusar_o_formato(self):
        self.assertIsNone(aviso_ean(BARRAS))
        self.assertIsNone(aviso_ean("96385074"))
        self.assertIsNone(aviso_ean("12345"))
        self.assertIn("EAN-13", aviso_ean(BARRAS_RUIM))

    def test_csv_e_xlsx_usam_as_mesmas_colunas(self):
        csv = "Produto;Preço de venda;Código de barras;Quantidade;Preço de custo;Grupo\nÁgua;3,50;7891234567895;4;1,20;Bebidas\n"
        do_csv = ler_tabela_dados(csv.encode("utf-8"), "lista.csv")
        do_xlsx = ler_tabela_dados(escrever_xlsx([
            ["Produto", "Preço de venda", "Código de barras", "Quantidade", "Preço de custo", "Grupo"],
            ["Água", "3,50", "7891234567895", "4", "1,20", "Bebidas"],
        ]), "lista.xlsx")
        self.assertEqual(do_csv[0]["nome"], "Água")
        self.assertEqual([(l["nome"], l["preco"], l["codigo_barras"], l["quantidade"], l["custo"], l["grupo"])
                          for l in do_csv],
                         [(l["nome"], l["preco"], l["codigo_barras"], l["quantidade"], l["custo"], l["grupo"])
                          for l in do_xlsx])

    def test_previa_cria_atualiza_por_barras_e_recusa(self):
        produtos = [{
            "id": 5, "codigo": "8", "nome": "SKOL", "cbarra": BARRAS, "ativo": True,
            "preco_cent": 800, "custo_medio_cent": 400, "qt_atual": 10, "grupo": "CERVEJA", "unidade": "UN",
        }, {
            "id": 6, "codigo": "9", "nome": "GELO", "cbarra": "", "ativo": True,
            "preco_cent": 200, "grupo": "GELO", "unidade": "UN",
        }]
        linhas = classificar_espelho([
            {"_linha": 2, "nome": "Skol lata", "preco": "9,00", "codigo_barras": BARRAS, "quantidade": "3"},
            {"_linha": 3, "nome": "Água", "preco": "3,50", "quantidade": "8", "grupo": "Bebidas"},
            {"_linha": 4, "nome": "Sem preço", "preco": "abc"},
            {"_linha": 5, "nome": "Outra skol", "preco": "1,00", "codigo_barras": BARRAS},
            {"_linha": 6, "nome": "Gelo novo", "preco": "2,00", "codigo_barras": BARRAS_RUIM},
        ], produtos, unidades={"UN"}, grupos=_grupos("CERVEJA", "GELO", "DIVERSOS", "BEBIDAS"))
        por_linha = {l["linha"]: l for l in linhas}
        self.assertEqual(por_linha[2]["acao"], "atualizar")
        self.assertEqual(por_linha[2]["codigo"], "8")
        self.assertEqual(por_linha[2]["comando"]["codigo"], "8")
        self.assertEqual(por_linha[2]["anterior"]["preco_cent"], 800)
        self.assertEqual(por_linha[2]["anterior"]["qt_atual"], 10)
        self.assertEqual(por_linha[3]["acao"], "criar")
        self.assertEqual(por_linha[4]["acao"], "recusar")
        self.assertIn("Preço", por_linha[4]["motivo"])
        self.assertEqual(por_linha[5]["acao"], "recusar")
        self.assertIn("aparece de novo", por_linha[5]["motivo"])
        self.assertEqual(por_linha[6]["acao"], "criar")
        self.assertTrue(por_linha[6]["avisos"])


class TesteSeparacaoDoCusto(unittest.TestCase):
    def test_o_custo_vai_num_segundo_lote_sem_repetir_a_quantidade(self):
        from backend.importacao_painel import separar_custo
        sem, com = separar_custo([
            {"nome": "A", "preco": "1,00", "custo": "0,50", "quantidade": "4", "codigo_barras": "1"},
            {"nome": "B", "preco": "2,00", "custo": "", "quantidade": "1"},
        ])
        self.assertEqual([(l["nome"], l["custo"], l["quantidade"]) for l in sem], [("A", "", "4"), ("B", "", "1")])
        self.assertEqual([(l["nome"], l["custo"], l["quantidade"]) for l in com], [("A", "0,50", "")])


class TesteAplicacaoNoCaixa(BaseTeste):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("retaguarda_nuvem", "S")
        self.ctrl = RetaguardaController(self.banco)
        self.pid = self.novo_produto("SKOL", preco=800, cbarra=BARRAS, estoque=True, qt=10)

    def aplicar(self, ident, dados, tipo="produtos.importar"):
        return self.ctrl.aplicar({"id": ident, "tipo": tipo, "dados": dados, "resumo": "teste", "autor": "dono"})

    def test_codigo_de_barras_atualiza_e_a_quantidade_soma_ou_substitui(self):
        soma = self.aplicar(1, {"casar_barras": True, "modo_quantidade": "somar", "linhas": [
            {"nome": "Skol lata", "preco": "9,00", "quantidade": "3", "codigo_barras": BARRAS}]})
        self.assertEqual(soma["situacao"], "aplicado", soma)
        p = self.banco.um("SELECT nome, preco_cent, qt_atual FROM produtos WHERE id = ?", (self.pid,))
        self.assertEqual((p["nome"], p["preco_cent"]), ("SKOL LATA", 900))
        self.assertAlmostEqual(p["qt_atual"], 13)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos WHERE cbarra = ?", (BARRAS,)), 1)
        troca = self.aplicar(2, {"casar_barras": True, "modo_quantidade": "substituir", "linhas": [
            {"nome": "Skol lata", "preco": "9,00", "quantidade": "4", "codigo_barras": BARRAS}]})
        self.assertEqual(troca["situacao"], "aplicado", troca)
        self.assertAlmostEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.pid,)), 4)

    def test_desfazer_desativa_o_novo_e_restaura_o_preco(self):
        criado = self.aplicar(1, {"casar_barras": True, "linhas": [
            {"nome": "Agua", "preco": "3,00", "quantidade": "4", "codigo_barras": "7891000315507"}]})
        self.assertEqual(criado["situacao"], "aplicado", criado)
        desfazer = self.aplicar(2, {"itens": [
            {"acao": "criar", "nome": "AGUA", "codigo_barras": "7891000315507"}]}, "produtos.desfazer")
        self.assertEqual(desfazer["situacao"], "aplicado", desfazer)
        self.assertFalse(self.banco.valor("SELECT ativo FROM produtos WHERE cbarra = ?", ("7891000315507",)))
        self.aplicar(3, {"casar_barras": True, "linhas": [
            {"nome": "SKOL", "preco": "9,50", "codigo_barras": BARRAS}]})
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (self.pid,)), 950)
        codigo = self.banco.valor("SELECT codigo FROM produtos WHERE id = ?", (self.pid,))
        grupo = self.banco.valor(
            "SELECT s.nome FROM produtos p JOIN subgrupos s ON s.id = p.subgrupo_id WHERE p.id = ?", (self.pid,))
        volta = self.aplicar(4, {"itens": [{"acao": "atualizar", "anterior": {
            "codigo": str(int(codigo)) if str(codigo).isdigit() else codigo, "nome": "SKOL", "preco_cent": 800,
            "codigo_barras": BARRAS, "grupo": grupo, "unidade": "UN"}}]}, "produtos.desfazer")
        self.assertEqual(volta["situacao"], "aplicado", volta)
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (self.pid,)), 800)

    def test_custo_entra_mesmo_com_operador_de_caixa_logado(self):
        from src.controllers.cadastro_controller import CadastroController
        from src.core.erros import ErroPermissao
        from src.sync.ociosidade import SONDA_RETAGUARDA_SEG, SONDA_SEG, intervalo_sonda
        caixa = self.banco.inserir("operadores", {"nome": "CAIXA", "senha": "x", "nivel": 1, "cargo_id": 1, "ativo": 1})
        self.banco.definir_operador_auditoria(caixa)
        r = self.aplicar(1, {"casar_barras": True, "linhas": [
            {"nome": "SKOL", "preco": "9,00", "custo": "4,00", "codigo_barras": BARRAS}]})
        self.assertEqual(r["situacao"], "aplicado", r)
        self.assertEqual(self.banco.valor("SELECT custo_medio_cent FROM produtos WHERE id = ?", (self.pid,)), 400)
        self.assertEqual(self.banco._operador_auditoria, caixa)
        with self.assertRaises(ErroPermissao):
            CadastroController(self.banco).salvar("produtos", {"custo_medio_cent": "1,00"}, self.pid)
        self.banco.cfg_set("painel_dono", "S")
        self.banco.cfg_set("api_url", "http://testserver/v1/sincronizar")
        self.banco.cfg_set("api_token", "t")
        self.assertEqual(intervalo_sonda(self.banco), SONDA_RETAGUARDA_SEG)
        self.banco.cfg_set("retaguarda_nuvem", "N")
        self.assertEqual(intervalo_sonda(self.banco), SONDA_SEG)


try:
    from tests.test_notas_dono import _Ponte
    from tests.test_retaguarda import BaseNuvem, TestClient, nuvem, nuvem_retaguarda
    from src.sync import retaguarda
except (ImportError, RuntimeError):
    BaseNuvem = TestClient = nuvem = nuvem_retaguarda = _Ponte = retaguarda = None


@unittest.skipIf(TestClient is None or nuvem_retaguarda is None, "fastapi/httpx não instalados")
class TesteEndpoint(BaseNuvem):
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
        self.pid = self.novo_produto("CERVEJA TESTE", preco=800, cbarra=BARRAS, estoque=True, qt=10)
        retaguarda.sincronizar(self.banco, self.ponte, forcar=True)

    def previa(self, corpo, headers=None):
        return self.http.post("/v1/painel/importacao/previa", json=corpo, headers=headers or self.dono)

    def aplicar(self, corpo, headers=None):
        return self.http.post("/v1/painel/importacao/aplicar", json=corpo, headers=headers or self.dono)

    def test_sem_sessao_nao_entra_e_a_pagina_tem_os_controles(self):
        self.assertEqual(self.http.post("/v1/painel/importacao/previa", json={"texto": "Produto;Preço\nA;1\n"}).status_code, 401)
        self.assertEqual(self.http.get("/v1/painel/importacao/produtos").status_code, 401)
        pagina = self.http.get("/painel/").text
        for ident in ("bloco-importar-produtos", "arquivo-planilha", "texto-planilha", "modo-substituir",
                      "confirmar-importar", "busca-produto", "importar-rede-loja", "baixar-modelo-produtos"):
            self.assertIn(f'id="{ident}"', pagina)
        modelo = self.http.get("/v1/painel/importacao/modelo", headers=self.dono)
        self.assertEqual(modelo.status_code, 200, modelo.text)
        self.assertIn("Produto", modelo.text)
        self.assertIn("Código de barras", modelo.text)

    def test_previa_atualiza_por_barras_recusa_e_so_grava_ao_confirmar(self):
        texto = ("Produto;Preço de venda;Código de barras;Quantidade\n"
                 "Cerveja teste lata;9,00;" + BARRAS + ";3\n"
                 "Agua teste painel;3,50;;8\n"
                 "Ruim;abc;;\n")
        antes = self._comandos()
        previa = self.previa({"texto": texto, "modo_quantidade": "substituir"})
        self.assertEqual(previa.status_code, 200, previa.text)
        corpo = previa.json()
        self.assertEqual((corpo["criados"], corpo["atualizados"], corpo["erros"], corpo["dry_run"]), (1, 1, 1, True))
        self.assertIn("substitui", corpo["quantidade_texto"])
        self.assertEqual(self._comandos(), antes)
        seca = self.http.post("/v1/painel/importacao", json={"texto": texto}, headers=self.dono)
        self.assertTrue(seca.json()["dry_run"])
        self.assertEqual(self._comandos(), antes)
        aplicado = self.aplicar({"texto": texto, "modo_quantidade": "substituir"})
        self.assertEqual(aplicado.status_code, 200, aplicado.text)
        self.assertFalse(aplicado.json()["dry_run"])
        self.assertGreaterEqual(len(aplicado.json()["comandos"]), 1)
        self.assertEqual(self.aplicar({"texto": texto}).status_code, 409)
        retaguarda.sincronizar(self.banco, self.ponte, forcar=True)
        p = self.banco.um("SELECT nome, preco_cent, qt_atual FROM produtos WHERE id = ?", (self.pid,))
        self.assertEqual((p["nome"], p["preco_cent"]), ("CERVEJA TESTE LATA", 900))
        self.assertAlmostEqual(p["qt_atual"], 3)
        agua = self.banco.um("SELECT qt_atual FROM produtos WHERE nome = 'AGUA TESTE PAINEL'")
        self.assertAlmostEqual(agua["qt_atual"], 8)
        self.assertIsNone(self.banco.um("SELECT id FROM produtos WHERE nome = 'RUIM'"))

    def test_soma_json_busca_exportacao_token_e_desfazer(self):
        previa = self.http.post("/v1/painel/importacao", json={
            "dry_run": True, "modo_quantidade": "somar",
            "linhas": [{"nome": "Cerveja teste", "preco": 9.5, "codigo_barras": BARRAS, "quantidade": 2},
                       {"nome": "Gelo teste painel", "preco": 2, "codigo_barras": BARRAS_RUIM, "quantidade": 1}]},
            headers=self.dono)
        self.assertEqual(previa.status_code, 200, previa.text)
        gelo = next(l for l in previa.json()["linhas"] if l["nome"] == "GELO TESTE PAINEL")
        self.assertTrue(gelo["avisos"])
        self.assertEqual(self.aplicar({
            "modo_quantidade": "somar",
            "linhas": [{"nome": "Cerveja teste", "preco": "9,50", "codigo_barras": BARRAS, "quantidade": "2"}]}).status_code, 200)
        retaguarda.sincronizar(self.banco, self.ponte, forcar=True)
        self.assertAlmostEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.pid,)), 12)
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (self.pid,)), 950)
        busca = self.http.get("/v1/painel/importacao/produtos", params={"q": BARRAS}, headers=self.dono)
        self.assertEqual(busca.status_code, 200, busca.text)
        self.assertEqual(busca.json()["produtos"][0]["nome"], "CERVEJA TESTE")
        csv = self.http.get("/v1/painel/importacao/produtos", params={"formato": "csv"}, headers=self.dono)
        self.assertIn("CERVEJA TESTE", csv.text)
        self.assertIn(BARRAS, csv.text)
        xlsx = self.http.get("/v1/painel/importacao/produtos", params={"formato": "xlsx"}, headers=self.dono)
        self.assertEqual(xlsx.status_code, 200)
        self.assertTrue(xlsx.content.startswith(b"PK"))
        outra = self.entrar("ADEGA-2", "senha-forte-2")
        self.assertEqual(self.previa({"loja": "ADEGA-1", "texto": "Produto;Preço\nA;1,00\n"}, outra).status_code, 403)
        token = self.http.post("/v1/painel/importacao/tokens", json={"nome": "assistente"}, headers=self.dono)
        self.assertEqual(token.status_code, 200, token.text)
        segredo = token.json()["token"]
        self.assertTrue(segredo.startswith("wpdv_"))
        lista = self.http.get("/v1/painel/importacao/tokens", headers=self.dono)
        self.assertNotIn(segredo, lista.text)
        with nuvem.SessionLocal() as db:
            from backend.importacao_painel import PainelTokenApi
            guardado = db.query(PainelTokenApi).one().token_hash
        self.assertNotIn(segredo, guardado)
        auth = {"Authorization": "Bearer " + segredo}
        self.assertEqual(self.http.get("/v1/painel/importacao/produtos", params={"q": "cerveja teste"}, headers=auth).status_code, 200)
        self.assertEqual(self.http.post("/v1/painel/importacao/tokens", json={"nome": "outro"}, headers=auth).status_code, 403)
        ident = token.json()["id"]
        self.assertEqual(self.http.delete(f"/v1/painel/importacao/tokens/{ident}", headers=self.dono).status_code, 200)
        self.assertEqual(self.http.get("/v1/painel/importacao/produtos", headers=auth).status_code, 401)
        hist = self.http.get("/v1/painel/importacao/historico", headers=self.dono).json()["importacoes"]
        self.assertTrue(hist[0]["pode_desfazer"])
        self.assertEqual(hist[0]["autor"], "dono")
        desfazer = self.http.post("/v1/painel/importacao/desfazer", json={}, headers=self.dono)
        self.assertEqual(desfazer.status_code, 200, desfazer.text)
        retaguarda.sincronizar(self.banco, self.ponte, forcar=True)
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (self.pid,)), 800)

    def test_rede_escolhe_a_loja(self):
        from backend.grupos import adicionar_loja, criar
        with nuvem.SessionLocal() as db:
            grupo, _ = criar(db, "EA REDE", "EA-REDE", "senha-rede-1", temporaria=False)
            adicionar_loja(db, grupo, "ADEGA-1")
            grupo_id = grupo.id
        self.addCleanup(self._limpar_rede, grupo_id)
        login = self.http.post("/v1/painel/login", json={"loja": "EA-REDE", "senha": "senha-rede-1"})
        self.assertEqual(login.status_code, 200, login.text)
        token = {"Authorization": "Bearer " + login.json()["token"]}
        sem = self.previa({"texto": "Produto;Preço\nAgua teste rede;3,00\n"}, token)
        self.assertEqual(sem.status_code, 422)
        com = self.previa({"loja": "ADEGA-1", "texto": "Produto;Preço\nAgua teste rede;3,00\n"}, token)
        self.assertEqual(com.status_code, 200, com.text)
        self.assertEqual(com.json()["criados"], 1)
        self.assertEqual(self.previa({"loja": "ADEGA-2", "texto": "Produto;Preço\nAgua teste rede;3,00\n"}, token).status_code, 404)

    def test_custo_acorda_o_caixa_e_a_recusa_pode_ser_reenviada(self):
        import json
        from backend.memoria_nuvem import memoria
        from backend.retaguarda import RetaguardaComando
        memoria.lembrar_token("token-da-adega-1", "ADEGA-1")
        token_caixa = {"Authorization": "Bearer token-da-adega-1"}
        antes = self.http.get("/v1/sync/pedido", headers=token_caixa).json()
        r = self.aplicar({"texto": "Produto;Preço de venda;Preço de custo;Código de barras\n"
                          "Cerveja teste;" + "9,00;4,00;" + BARRAS + "\n"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("segunda alteração", r.json()["mensagem"])
        with nuvem.SessionLocal() as db:
            comandos = (db.query(RetaguardaComando).filter_by(chave_loja="ADEGA-1", situacao="pendente")
                        .order_by(RetaguardaComando.id).all())
            corpos = [json.loads(c.dados) for c in comandos]
        self.assertEqual(len(corpos), 2)
        self.assertEqual(corpos[0]["linhas"][0]["custo"], "")
        self.assertEqual(corpos[1]["linhas"][0]["custo"], "4,00")
        self.assertEqual(corpos[1]["linhas"][0]["quantidade"], "")
        caixa = self.banco.inserir("operadores", {"nome": "CAIXA", "senha": "x", "nivel": 1, "cargo_id": 1, "ativo": 1})
        self.banco.definir_operador_auditoria(caixa)
        retaguarda.sincronizar(self.banco, self.ponte, forcar=True)
        self.assertEqual(self.banco.valor("SELECT custo_medio_cent FROM produtos WHERE id = ?", (self.pid,)), 400)
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (self.pid,)), 900)
        self.assertEqual(self.banco._operador_auditoria, caixa)
        depois = self.http.get("/v1/sync/pedido", headers=token_caixa).json()
        self.assertTrue(depois["pedido"])
        self.assertNotEqual(depois.get("id"), antes.get("id"))
        with nuvem.SessionLocal() as db:
            recusado = (db.query(RetaguardaComando).filter_by(chave_loja="ADEGA-1")
                        .order_by(RetaguardaComando.id.desc()).first())
            recusado.situacao = "recusado"
            recusado.detalhe = "Custo e lucro só aparecem para o gerente."
            db.commit()
            ident = recusado.id
        self.assertEqual(self.http.post(f"/v1/painel/retaguarda/comandos/{ident}/reenviar").status_code, 401)
        de_novo = self.http.post(f"/v1/painel/retaguarda/comandos/{ident}/reenviar", headers=self.dono)
        self.assertEqual(de_novo.status_code, 200, de_novo.text)
        self.assertEqual(de_novo.json()["comando"]["situacao"], "pendente")
        self.assertTrue(de_novo.json()["comando"]["resumo"].startswith("Reenvio:"))
        novo_id = de_novo.json()["comando"]["id"]
        self.assertEqual(self.http.post(f"/v1/painel/retaguarda/comandos/{novo_id}/reenviar",
                                        headers=self.dono).status_code, 409)
        pagina = self.http.get("/retaguarda/app.js").text
        self.assertIn("Enviar de novo", pagina)
        self.assertIn("5000", pagina)

    def _limpar_rede(self, grupo_id):
        from backend.grupos import Grupo
        from backend.main import Loja
        from backend.painel import PainelSessao
        with nuvem.SessionLocal() as db:
            db.query(PainelSessao).filter_by(grupo_id=grupo_id).delete()
            db.query(Loja).filter_by(grupo_id=grupo_id).update({Loja.grupo_id: None})
            db.query(Grupo).filter_by(id=grupo_id).delete()
            db.commit()

    def _comandos(self):
        with nuvem.SessionLocal() as db:
            return db.query(nuvem_retaguarda.RetaguardaComando).filter_by(chave_loja="ADEGA-1").count()


if __name__ == "__main__":
    unittest.main()
