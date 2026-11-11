"""Notas de compra do painel do dono: a nuvem guarda e entrega, o caixa busca, confere e devolve o desfecho."""
import base64
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest

from src.controllers.importacao_produtos import ImportacaoNFe
from src.controllers.notas_dono_controller import NotasDonoController
from src.core.erros import ErroNegocio
from src.sync import notas_dono, painel_envio
from tests.test_importacao_nfe import xml_nfe
from tests.test_painel_dono import BaseNuvem, TestClient, cabecalho, nuvem

try:
    from backend import notas_dono as nuvem_notas
except (ImportError, RuntimeError):
    nuvem_notas = None


class _Ponte:
    """O `requests` do PDV falando com a API de teste (o TestClient não aceita `timeout`)."""

    def __init__(self, http):
        self._http, self.chamadas = http, []

    def get(self, url, headers=None, timeout=None):
        self.chamadas.append(("GET", url))
        return self._http.get(url, headers=headers)

    def post(self, url, json=None, headers=None, timeout=None):
        self.chamadas.append(("POST", url))
        return self._http.post(url, json=json, headers=headers)


def corpo(xml: str | bytes, nome="nota.xml") -> dict:
    bruto = xml if isinstance(xml, bytes) else xml.encode("utf-8")
    return {"nome": nome, "conteudo_b64": base64.b64encode(bruto).decode("ascii")}


def outra_nota(numero="101") -> str:
    """Outra nota do mesmo fornecedor: chave e número diferentes."""
    return xml_nfe().replace("0000001001000000010", "0000001011000000019").replace("<nNF>100</nNF>", f"<nNF>{numero}</nNF>")


@unittest.skipIf(TestClient is None or nuvem_notas is None, "fastapi/httpx não instalados")
class BaseNotas(BaseNuvem):
    def setUp(self):
        super().setUp()
        with nuvem.SessionLocal() as db:
            db.query(nuvem_notas.PainelNota).delete()
            db.commit()
        self.dono = self.entrar()
        self.ponte = _Ponte(self.http)

    def enviar(self, xml=None, nome="nota.xml", sessao=None):
        return self.http.post("/v1/painel/notas", json=corpo(xml or xml_nfe(), nome), headers=sessao or self.dono)

    def lista(self, sessao=None):
        return self.http.get("/v1/painel/notas", headers=sessao or self.dono).json()["notas"]


class TesteNuvemDasNotas(BaseNotas):
    def test_dono_envia_e_a_lista_mostra_o_cabecalho_sem_o_xml(self):
        r = self.enviar(nome="NFe 100 distribuidora.xml")
        self.assertEqual(r.status_code, 200, r.text)
        nota = r.json()["nota"]
        self.assertEqual((nota["numero"], nota["emitente"], nota["cnpj"], nota["itens"], nota["situacao"]),
                         ("100", "Distribuidora Exemplo", "12345678000199", 2, "pendente"))
        self.assertEqual(nota["data_emissao"], "2026-10-03")
        self.assertEqual(self.lista(), [nota])
        self.assertNotIn("conteudo_b64", nota)
        self.assertNotIn("xml", nota)

    def test_recusa_o_que_nao_e_nfe_de_compra_com_o_motivo(self):
        casos = [(b"%PDF-1.4 danfe", "não é um XML válido"),
                 ("<raiz><outro/></raiz>", "não contém uma NF-e"),
                 (xml_nfe("65"), "modelo 55"),
                 ('<!DOCTYPE x [<!ENTITY a "b">]>' + xml_nfe(), "entidades ou DTD")]
        for xml, trecho in casos:
            r = self.enviar(xml)
            self.assertEqual(r.status_code, 422, r.text)
            self.assertIn(trecho, r.json()["detail"])
        grande = xml_nfe().replace("</nfeProc>", "<!-- " + "x" * nuvem_notas.LIMITE_XML_BYTES + " --></nfeProc>")
        self.assertEqual(self.enviar(grande).status_code, 413)
        self.assertEqual(self.http.post("/v1/painel/notas", json={"nome": "a.xml"}, headers=self.dono).status_code, 422)
        self.assertEqual(self.http.post("/v1/painel/notas", json={"conteudo_b64": "###"}, headers=self.dono).status_code, 422)
        self.assertEqual(self.lista(), [])

    def test_mesma_nota_duas_vezes_e_recusada_e_cada_loja_ve_so_as_suas(self):
        self.assertEqual(self.enviar().status_code, 200)
        repetida = self.enviar()
        self.assertEqual(repetida.status_code, 409)
        self.assertIn("já foi enviada", repetida.json()["detail"])
        outra_loja = self.entrar("ADEGA-2", "senha-forte-2")
        self.assertEqual(self.lista(outra_loja), [])
        self.assertEqual(self.enviar(sessao=outra_loja).status_code, 200)       # a mesma nota em outra loja é outra fila
        self.assertEqual(len(self.lista()), 1)
        do_caixa_2 = self.http.get("/v1/notas-dono", headers=cabecalho("ADEGA-2")).json()["notas"]
        self.assertEqual([n["numero"] for n in do_caixa_2], ["100"])

    def test_rotas_exigem_a_sessao_do_dono_ou_o_token_da_loja(self):
        self.assertEqual(self.http.get("/v1/painel/notas").status_code, 401)
        self.assertEqual(self.http.post("/v1/painel/notas", json=corpo(xml_nfe())).status_code, 401)
        self.assertEqual(self.http.get("/v1/painel/notas", headers=cabecalho()).status_code, 401)   # token do caixa não é sessão
        self.assertEqual(self.http.get("/v1/notas-dono").status_code, 401)
        self.assertEqual(self.http.get("/v1/notas-dono", headers=self.dono).status_code, 401)       # sessão não é token do caixa
        admin = {"Authorization": "Bearer token-de-teste"}
        self.assertEqual(self.http.get("/v1/notas-dono", headers=admin).status_code, 403)

    def test_dono_exclui_enquanto_o_caixa_nao_buscou(self):
        ident = self.enviar().json()["nota"]["id"]
        outra_loja = self.entrar("ADEGA-2", "senha-forte-2")
        self.assertEqual(self.http.delete(f"/v1/painel/notas/{ident}", headers=outra_loja).status_code, 404)
        self.assertEqual(self.http.delete(f"/v1/painel/notas/{ident}", headers=self.dono).status_code, 200)
        self.assertEqual(self.lista(), [])
        ident = self.enviar().json()["nota"]["id"]
        self.http.post("/v1/notas-dono/confirmar", json={"recebidas": [ident]}, headers=cabecalho())
        r = self.http.delete(f"/v1/painel/notas/{ident}", headers=self.dono)
        self.assertEqual(r.status_code, 409)
        self.assertIn("já chegou ao caixa", r.json()["detail"])

    def test_confirmacao_do_caixa_muda_a_situacao_e_apaga_o_xml(self):
        ident = self.enviar().json()["nota"]["id"]
        entregue = self.http.get("/v1/notas-dono", headers=cabecalho()).json()
        self.assertEqual(base64.b64decode(entregue["notas"][0]["conteudo_b64"]).decode("utf-8"), xml_nfe())
        self.assertEqual(entregue["restantes"], 0)
        r = self.http.post("/v1/notas-dono/confirmar", json={"recebidas": [ident, 999999, "x"]}, headers=cabecalho())
        self.assertEqual(r.json()["confirmadas"], [ident])
        self.assertEqual(self.lista()[0]["situacao"], "baixada")
        self.assertEqual(self.http.get("/v1/notas-dono", headers=cabecalho()).json()["notas"], [])   # não entrega de novo
        alheia = self.http.post("/v1/notas-dono/confirmar", headers=cabecalho("ADEGA-2"),
                                json={"situacoes": [{"id": ident, "situacao": "recusada", "detalhe": "x"}]})
        self.assertEqual(self.lista()[0]["situacao"], "baixada")                   # outra loja não mexe na nota
        self.assertEqual(alheia.json()["confirmadas"], [ident])                     # para ela, a nota não existe
        self.http.post("/v1/notas-dono/confirmar", headers=cabecalho(),
                       json={"situacoes": [{"id": ident, "situacao": "lancada", "detalhe": "Entrada registrada."},
                                           {"id": ident, "situacao": "inventada"}]})
        nota = self.lista()[0]
        self.assertEqual((nota["situacao"], nota["detalhe"]), ("lancada", "Entrada registrada."))
        with nuvem.SessionLocal() as db:
            self.assertIsNone(db.get(nuvem_notas.PainelNota, ident).xml)
        self.http.post("/v1/notas-dono/confirmar", headers=cabecalho(),
                       json={"situacoes": [{"id": ident, "situacao": "recusada", "detalhe": "atrasado"}]})
        self.assertEqual(self.lista()[0]["situacao"], "lancada")                    # entrada no estoque não volta atrás

    def test_nota_recusada_pode_ser_reenviada(self):
        ident = self.enviar().json()["nota"]["id"]
        self.http.post("/v1/notas-dono/confirmar", headers=cabecalho(),
                       json={"situacoes": [{"id": ident, "situacao": "recusada", "detalhe": "nota de outra loja"}]})
        self.assertEqual(self.lista()[0]["detalhe"], "nota de outra loja")
        self.assertEqual(self.enviar().status_code, 200)
        self.assertEqual([n["situacao"] for n in self.lista()], ["pendente"])

    def test_fila_cheia_recusa_nota_nova(self):
        from unittest import mock
        with mock.patch.object(nuvem_notas, "LIMITE_PENDENTES", 1):
            self.assertEqual(self.enviar().status_code, 200)
            cheia = self.enviar(outra_nota())
        self.assertEqual(cheia.status_code, 409)
        self.assertIn("notas demais", cheia.json()["detail"])


class TesteCaixaBuscaAsNotas(BaseNotas):
    def subir_painel(self):
        return painel_envio.enviar(self.banco, self.ponte)

    def test_sem_aviso_da_nuvem_o_caixa_nao_usa_a_rede(self):
        self.assertEqual(notas_dono.sincronizar(self.banco, self.ponte), {"novas": 0, "avisadas": 0})
        self.assertEqual(self.ponte.chamadas, [])
        self.banco.cfg_set("painel_dono", "N")
        self.assertIsNone(notas_dono.sincronizar(self.banco, self.ponte, forcar=True))
        self.assertEqual(self.ponte.chamadas, [])

    def test_envio_do_painel_avisa_e_a_rodada_seguinte_desce_a_nota(self):
        self.subir_painel()
        self.assertNotEqual(self.banco.cfg(notas_dono.CHAVE_AVISO), "S")            # sem nota: sem aviso
        ident = self.enviar().json()["nota"]["id"]
        self.venda_fechada((self.skol, 1))
        self.subir_painel()
        self.assertEqual(self.banco.cfg(notas_dono.CHAVE_AVISO), "S")
        self.assertEqual(notas_dono.sincronizar(self.banco, self.ponte), {"novas": 1, "avisadas": 0})
        pendentes = NotasDonoController(self.banco).pendentes()
        self.assertEqual([(n["id"], n["numero"], n["emitente"]) for n in pendentes], [(ident, "100", "Distribuidora Exemplo")])
        self.assertEqual(self.lista()[0]["situacao"], "baixada")
        self.assertEqual(self.banco.cfg(notas_dono.CHAVE_AVISO), "N")
        chamadas = len(self.ponte.chamadas)
        self.assertEqual(notas_dono.sincronizar(self.banco, self.ponte), {"novas": 0, "avisadas": 0})
        self.assertEqual(len(self.ponte.chamadas), chamadas)                        # nada novo: sem rede

    def test_buscar_agora_desce_em_lotes_sem_duplicar(self):
        from unittest import mock
        self.enviar()
        self.enviar(outra_nota())
        with mock.patch.object(nuvem_notas, "LOTE_ENTREGA", 1):
            self.assertEqual(notas_dono.sincronizar(self.banco, self.ponte, forcar=True)["novas"], 2)
        self.assertEqual(notas_dono.sincronizar(self.banco, self.ponte, forcar=True)["novas"], 0)
        self.assertEqual([n["numero"] for n in NotasDonoController(self.banco).pendentes()], ["100", "101"])

    def test_conferir_lanca_no_estoque_e_o_painel_fica_sabendo(self):
        produto = self.novo_produto("CERVEJA LATA", 500, estoque=True, qt=4, cbarra="7891234567895")
        ident = self.enviar().json()["nota"]["id"]
        notas_dono.sincronizar(self.banco, self.ponte, forcar=True)
        controle = NotasDonoController(self.banco, self.adm)
        previa = controle.previa(ident)
        self.assertEqual((previa.numero, len(previa.itens), previa.itens[0].produto_id), ("100", 2, produto))
        ImportacaoNFe(self.banco, self.adm).importar(previa, "Adega")
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (produto,)), 6)
        self.assertEqual(controle.pendentes(), [])                                  # a chave já está nas importações
        linha = self.banco.um("SELECT situacao, xml, aviso_ok FROM notas_dono WHERE id = ?", (ident,))
        self.assertEqual(tuple(linha), ("lancada", None, 0))
        self.assertEqual(notas_dono.sincronizar(self.banco, self.ponte), {"novas": 0, "avisadas": 1})
        self.assertEqual(self.lista()[0]["situacao"], "lancada")
        self.assertEqual(self.banco.valor("SELECT aviso_ok FROM notas_dono WHERE id = ?", (ident,)), 1)
        with self.assertRaises(ErroNegocio):
            controle.previa(ident)

    def test_recusar_exige_motivo_e_ele_aparece_para_o_dono(self):
        ident = self.enviar().json()["nota"]["id"]
        notas_dono.sincronizar(self.banco, self.ponte, forcar=True)
        controle = NotasDonoController(self.banco, self.adm)
        with self.assertRaises(ErroNegocio):
            controle.recusar(ident, " ")
        controle.recusar(ident, "Nota de outra loja")
        self.assertEqual(controle.quantidade(), 0)
        self.assertEqual([(n["situacao"], n["detalhe"]) for n in controle.recentes()], [("recusada", "Nota de outra loja")])
        notas_dono.sincronizar(self.banco, self.ponte)
        nota = self.lista()[0]
        self.assertEqual((nota["situacao"], nota["detalhe"]), ("recusada", "Nota de outra loja"))
        with self.assertRaises(ErroNegocio):
            controle.recusar(ident, "de novo")

    def test_sem_internet_o_desfecho_fica_guardado_para_a_proxima_rodada(self):
        ident = self.enviar().json()["nota"]["id"]
        notas_dono.sincronizar(self.banco, self.ponte, forcar=True)
        NotasDonoController(self.banco, self.adm).recusar(ident, "Fornecedor errado")

        class SemRede:
            def post(self, *a, **k):
                raise OSError("sem rede")
            get = post

        with self.assertRaises(RuntimeError):
            notas_dono.sincronizar(self.banco, SemRede())
        self.assertEqual(self.banco.valor("SELECT aviso_ok FROM notas_dono WHERE id = ?", (ident,)), 0)
        self.assertTrue(notas_dono.ha_o_que_fazer(self.banco))
        self.assertEqual(notas_dono.sincronizar(self.banco, self.ponte)["avisadas"], 1)
        self.assertFalse(notas_dono.ha_o_que_fazer(self.banco))

    def test_conteudo_estragado_da_nuvem_nao_entra_na_fila(self):
        class Estragada:
            chamadas = []

            def get(self, url, headers=None, timeout=None):
                from tests.test_painel_dono import RespostaFalsa
                return RespostaFalsa(200, {"notas": [{"id": 7, "conteudo_b64": "###"}, {"id": "x"}, "lixo"], "restantes": 0})

            def post(self, url, json=None, headers=None, timeout=None):
                self.chamadas.append(json)
                from tests.test_painel_dono import RespostaFalsa
                return RespostaFalsa(200, {"confirmadas": []})

        self.assertEqual(notas_dono.sincronizar(self.banco, Estragada(), forcar=True)["novas"], 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM notas_dono"), 0)
        self.assertEqual(Estragada.chamadas, [])                                    # nada guardado: nada confirmado

    def test_rodada_do_sincronizador_busca_as_notas(self):
        from src.sync.sincronizador import Sincronizador
        self.enviar()
        self.banco.cfg_set(notas_dono.CHAVE_AVISO, "S")
        Sincronizador(self.banco, self.ponte)._buscar_notas()
        self.assertEqual(NotasDonoController(self.banco).quantidade(), 1)


class TesteTelaDasNotas(BaseNotas):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def tela(self):
        from src.controllers.contexto import Contexto
        from src.ui_qt.notas_dono import JanelaNotasDono
        ctx = Contexto(self.banco)
        ctx.operador = ctx.acesso.operador(self.adm)
        janela = JanelaNotasDono(ctx)
        self.addCleanup(janela.deleteLater)
        self.addCleanup(janela.close)
        return janela

    def test_lista_buscar_agora_e_recusar(self):
        from unittest import mock
        from PySide6.QtWidgets import QInputDialog
        janela = self.tela()
        self.assertFalse(janela.btn_conferir.isEnabled())
        self.assertIn("Nenhuma nota esperando", janela.mensagem.text())
        self.enviar()
        self.assertTrue(janela.buscar_agora(self.ponte))
        self.assertEqual(janela.grade.rowCount(), 1)
        self.assertEqual(janela.grade.item(0, 0).text(), "Distribuidora Exemplo")
        self.assertEqual(janela.grade.item(0, 3).text(), "Esperando conferência")
        self.assertTrue(janela.btn_conferir.isEnabled())
        with mock.patch.object(QInputDialog, "getText", return_value=("Nota de outra loja", True)):
            self.assertTrue(janela.recusar())
        self.assertEqual(janela.grade.item(0, 3).text(), "Recusada: Nota de outra loja")
        self.assertFalse(janela.btn_recusar.isEnabled())

    def test_conferir_abre_a_previa_e_confirmada_tira_a_nota_da_fila(self):
        from unittest import mock
        from PySide6.QtWidgets import QDialog
        from src.ui_qt import importar_produtos
        ident = self.enviar().json()["nota"]["id"]
        janela = self.tela()
        janela.buscar_agora(self.ponte)
        vistas = []

        class PreviaFalsa:
            def __init__(self, tela, previa):
                vistas.append(previa)

            def exec(self):
                return QDialog.DialogCode.Accepted

        with mock.patch.object(importar_produtos, "JanelaImportarNFe", PreviaFalsa):
            self.assertTrue(janela.conferir())
        self.assertEqual([p.numero for p in vistas], ["100"])
        self.assertEqual(self.banco.valor("SELECT situacao FROM notas_dono WHERE id = ?", (ident,)), "lancada")
        self.assertIn("lançada no estoque", janela.mensagem.text())
        self.assertEqual(janela.grade.item(0, 3).text(), "Lançada no estoque")

    def test_sem_permissao_de_custo_nao_confere(self):
        ident = self.enviar().json()["nota"]["id"]
        janela = self.tela()
        janela.buscar_agora(self.ponte)
        with unittest.mock.patch.object(type(janela.ctx), "pode", lambda _s, modulo: modulo != "rel_custo"):
            self.assertFalse(janela.conferir())
        self.assertIn("só o gerente", janela.mensagem.text())
        self.assertEqual(self.banco.valor("SELECT situacao FROM notas_dono WHERE id = ?", (ident,)), "pendente")
