"""IA no caixa: cliente da nuvem e as telas de importação (foto e nomes da NF-e), com a nuvem simulada."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from src.controllers.contexto import Contexto
from src.core.erros import ErroNegocio
from src.sync import ia
from src.ui_qt.importar_produtos import JanelaImportarNFe, JanelaImportarProdutos
from tests.base import BaseTeste


class Resp:
    def __init__(self, status, corpo):
        self.status_code, self._corpo = status, corpo

    def json(self):
        return self._corpo


class Nuvem:
    def __init__(self, status=200, corpo=None):
        self.status, self.corpo, self.pedidos = status, corpo or {}, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.pedidos.append((url, json, headers))
        return Resp(self.status, self.corpo)

    def get(self, url, headers=None, timeout=None):
        self.pedidos.append((url, None, headers))
        return Resp(self.status, self.corpo)


XML = """<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe321">
  <ide><mod>55</mod><nNF>321</nNF><dhEmi>2026-10-03T10:00:00-03:00</dhEmi></ide>
  <emit><CNPJ>12345678000199</CNPJ><xNome>Distribuidora</xNome></emit>
  <det nItem="1"><prod><cProd>H1</cProd><cEAN>SEM GTIN</cEAN><xProd>CERV HEINEKEN LN 330ML</xProd>
  <uCom>UN</uCom><qCom>12</qCom><vUnCom>4.00</vUnCom><vProd>48.00</vProd></prod></det>
</infNFe></NFe></nfeProc>"""


class TesteIaCaixa(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.banco.cfg_set("api_url", "https://nuvem.exemplo")
        self.banco.cfg_set("api_token", "token-loja")
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.janelas = []
        self.addCleanup(self._fechar)
        self.pasta = Path(tempfile.mkdtemp())

    def _fechar(self):
        for j in self.janelas:
            j.close()
            j.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def foto(self, nome="lista.jpg"):
        caminho = self.pasta / nome
        caminho.write_bytes(b"\xff\xd8\xff" + b"0" * 100)
        return caminho

    def test_sem_nuvem_desligada(self):
        self.banco.cfg_set("api_token", "")
        self.assertEqual(ia.situacao(self.banco)["ativa"], False)
        with self.assertRaisesRegex(ErroNegocio, "nuvem configurada"):
            ia.produtos_da_foto(self.banco, self.foto())

    def test_erro_da_nuvem_vira_mensagem(self):
        nuvem = Nuvem(403, {"detail": "A IA não está contratada nesta loja."})
        with self.assertRaisesRegex(ErroNegocio, "não está contratada"):
            ia.produtos_da_foto(self.banco, self.foto(), http=nuvem)
        self.assertEqual(nuvem.pedidos[0][2]["Authorization"], "Bearer token-loja")

    def test_formato_errado_nem_sobe(self):
        nuvem = Nuvem()
        with self.assertRaises(ErroNegocio):
            ia.produtos_da_foto(self.banco, self.foto("nota.pdf"), http=nuvem)
        self.assertEqual(nuvem.pedidos, [])

    def test_foto_vira_previa_e_so_grava_ao_importar(self):
        nuvem = Nuvem(corpo={"produtos": [
            {"nome": "Cerveja Heineken Long Neck 330ml", "preco_cent": 1200, "quantidade": 12, "grupo": "CERVEJA"},
            {"nome": "Gelo 5kg", "preco_cent": 0}]})
        janela = JanelaImportarProdutos(self.ctx)
        self.janelas.append(janela)
        import requests
        with patch.object(requests, "post", side_effect=nuvem.post):
            self.assertTrue(janela.ler_foto(str(self.foto())) is not False)
        self.assertEqual([l["nome"] for l in janela.tabela], ["Cerveja Heineken Long Neck 330ml", "Gelo 5kg"])
        self.assertEqual(janela.tabela[0]["preco"], "12,00")
        self.assertIsNone(self.banco.um("SELECT 1 FROM produtos WHERE nome LIKE '%HEINEKEN LONG%'"))
        self.assertIn("IA", janela.arquivo.text())

    def test_nomes_da_nfe_trocados_so_nos_novos_e_guarda_o_da_nota(self):
        from src.controllers.importacao_produtos import ImportacaoNFe
        caminho = self.pasta / "nota.xml"
        caminho.write_text(XML, encoding="utf-8")
        janela = JanelaImportarProdutos(self.ctx)
        self.janelas.append(janela)
        previa = ImportacaoNFe(self.banco, self.ctx.operador_id).analisar(caminho)
        dialogo = JanelaImportarNFe(janela, previa)
        self.janelas.append(dialogo)
        nuvem = Nuvem(corpo={"itens": [{"nome": "Cerveja Heineken Long Neck 330ml", "grupo": "Cerveja"}]})
        self.assertEqual(dialogo.arrumar_nomes(http=nuvem), 1)
        self.assertEqual(nuvem.pedidos[0][1], {"itens": [{"nome": "CERV HEINEKEN LN 330ML"}]})
        self.assertIn("Cerveja Heineken Long Neck 330ml", dialogo.associacoes[0].itemText(0))
        dialogo.precos_venda[0].setText("8,00")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                patch.object(QMessageBox, "information"):
            self.assertTrue(dialogo.confirmar())
        self.assertIsNotNone(self.banco.um("SELECT 1 FROM produtos WHERE nome = ?",
                                           ("Cerveja Heineken Long Neck 330ml",)))
        self.assertEqual(self.banco.valor("SELECT nome_xml FROM itens_importacao_nfe"), "CERV HEINEKEN LN 330ML")

    def test_padronizar_em_partes(self):
        class NuvemEco(Nuvem):
            def post(self, url, json=None, headers=None, timeout=None):
                self.pedidos.append(len(json["itens"]))
                return Resp(200, {"itens": [{"nome": i["nome"].title()} for i in json["itens"]]})
        nuvem = NuvemEco()
        nomes = [f"PRODUTO {i}" for i in range(250)]
        saida = ia.padronizar_nomes(self.banco, nomes, http=nuvem)
        self.assertEqual(nuvem.pedidos, [200, 50])
        self.assertEqual(saida[249]["nome"], "Produto 249")
