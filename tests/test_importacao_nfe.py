"""Importação segura de NF-e modelo 55 e bloqueio de preço zerado."""
from pathlib import Path
import tempfile
from unittest.mock import patch

from src.controllers.caixa_controller import CaixaController
from src.controllers.importacao_produtos import ImportacaoNFe
from src.controllers.turno_controller import TurnoController
from src.core.erros import ErroNegocio
from tests.base import BaseTeste


def xml_nfe(modelo="55"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe35261012345678000199550010000001001000000010">
      <ide><mod>{modelo}</mod><nNF>100</nNF><dhEmi>2026-10-03T20:00:00-03:00</dhEmi></ide>
      <emit><CNPJ>12345678000199</CNPJ><xNome>Distribuidora Exemplo</xNome></emit>
      <det nItem="1"><prod><cProd>1</cProd><cEAN>7891234567895</cEAN><xProd>CERVEJA LATA</xProd>
        <uCom>UN</uCom><qCom>2.0000</qCom><vUnCom>3.25</vUnCom><vProd>6.50</vProd></prod></det>
      <det nItem="2"><prod><cProd>2</cProd><cEAN>SEM GTIN</cEAN><xProd>VODKA TESTE</xProd>
        <uCom>UN</uCom><qCom>1.0000</qCom><vUnCom>20.00</vUnCom><vProd>20.00</vProd></prod></det>
    </infNFe></NFe></nfeProc>"""


class TesteImportacaoNFe(BaseTeste):
    def setUp(self):
        super().setUp()
        self.importador = ImportacaoNFe(self.banco, self.operador_adm())
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.arquivo = Path(self.pasta.name) / "nota.xml"
        self.arquivo.write_text(xml_nfe(), encoding="utf-8")

    def test_previa_associa_ean_e_sugere_nome_sem_criar_match_automatico(self):
        id_ean = self.novo_produto("CERVEJA LATA", 500, estoque=True, qt=4, cbarra="7891234567895")
        id_nome = self.novo_produto("VODKA TESTE", 3000, codigo="8")
        previa = self.importador.analisar(self.arquivo)
        self.assertEqual(previa.numero, "100")
        self.assertEqual(previa.itens[0].produto_id, id_ean)
        self.assertIsNone(previa.itens[1].produto_id)
        self.assertEqual([p["id"] for p in previa.itens[1].sugestoes], [id_nome])

    def test_importa_estoque_custo_e_historico_sem_alterar_preco_de_venda(self):
        produto = self.novo_produto("CERVEJA LATA", 500, estoque=True, qt=4, cbarra="7891234567895")
        previa = self.importador.analisar(self.arquivo)
        self.banco.cfg_set("margem_minima_pct", "40")
        resultado = self.importador.importar(previa, "Bar", {2: None})
        cerveja = dict(self.banco.um("SELECT * FROM produtos WHERE id = ?", (produto,)))
        vodka = dict(self.banco.um("SELECT * FROM produtos WHERE nome = 'VODKA TESTE'"))
        self.assertEqual((cerveja["preco_cent"], cerveja["ult_preco_cent"], cerveja["qt_atual"]), (500, 325, 6))
        self.assertEqual((vodka["preco_cent"], vodka["ult_preco_cent"], vodka["qt_atual"]), (0, 2000, 1))
        self.assertEqual(resultado["criados"], 1)
        self.assertEqual(resultado["atualizados"], 1)
        self.assertEqual(resultado["alertas_margem"][0]["produto_id"], produto)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM importacoes_nfe"), 1)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM itens_importacao_nfe"), 2)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_estoque WHERE tipo = 'compra'"), 2)
        self.assertEqual(self.banco.valor("SELECT nome FROM grupos WHERE nome = 'BAR'"), "BAR")

    def test_importa_nota_apenas_uma_vez_e_rejeita_outro_modelo(self):
        previa = self.importador.analisar(self.arquivo)
        self.importador.importar(previa, "Adega")
        with self.assertRaisesRegex(ErroNegocio, "já foi importada"):
            self.importador.importar(previa, "Adega")
        self.arquivo.write_text(xml_nfe("65"), encoding="utf-8")
        with self.assertRaisesRegex(ErroNegocio, "modelo 55"):
            self.importador.analisar(self.arquivo)

    def test_preco_novo_pode_ser_informado_manualmente_em_centavos(self):
        previa = self.importador.analisar(self.arquivo)
        self.importador.importar(previa, "Bar", precos_venda={2: 2599})
        self.assertEqual(self.banco.valor(
            "SELECT preco_cent FROM produtos WHERE nome = 'VODKA TESTE'"), 2599)

    def test_usa_gtin_tributavel_e_recusa_declaracao_de_entidades(self):
        produto = self.novo_produto("CERVEJA LATA", 500, estoque=True, cbarra="7891234567895")
        self.arquivo.write_text(xml_nfe().replace(
            "<cEAN>7891234567895</cEAN>", "<cEAN>SEM GTIN</cEAN><cEANTrib>7891234567895</cEANTrib>"),
            encoding="utf-8")
        self.assertEqual(self.importador.analisar(self.arquivo).itens[0].produto_id, produto)
        self.arquivo.write_text("<!DOCTYPE x [<!ENTITY e 'x'>]><x>&e;</x>", encoding="utf-8")
        with self.assertRaisesRegex(ErroNegocio, "entidades ou DTD"):
            self.importador.analisar(self.arquivo)

    def test_falha_no_meio_nao_deixa_estoque_produtos_ou_historico_parcial(self):
        previa = self.importador.analisar(self.arquivo)
        with patch.object(self.importador.estoque, "adicionar_item", side_effect=ErroNegocio("falhou")):
            with self.assertRaisesRegex(ErroNegocio, "falhou"):
                self.importador.importar(previa, "Bar")
        for tabela in ("produtos", "importacoes_nfe", "itens_importacao_nfe", "lancamentos_estoque", "fornecedores"):
            self.assertEqual(self.banco.valor(f"SELECT COUNT(*) FROM {tabela}"), 0, tabela)

    def test_preco_zerado_e_bloqueado_no_lancamento_e_no_fechamento(self):
        produto = self.novo_produto("SEM PREÇO", 0)
        TurnoController(self.banco).abrir(self.operador_adm(), 1, 0)
        caixa = CaixaController(self.banco, self.operador_adm())
        venda = caixa.abrir_balcao()
        with self.assertRaisesRegex(ErroNegocio, "sem preço de venda"):
            caixa.adicionar_item(venda, produto, 1)
        self.banco.executar(
            """INSERT INTO itens_venda(venda_id, produto_id, quantidade, preco_unit_cent, total_cent, criado_em)
               VALUES (?, ?, 1, 0, 0, '2026-10-03 21:00:00')""", (venda, produto))
        with self.assertRaisesRegex(ErroNegocio, "sem preço de venda"):
            caixa.fechar(venda)

    def test_zip_ipi_st_e_fator_lembrado_por_fornecedor(self):
        import zipfile
        zipado = Path(self.pasta.name) / "notas.zip"
        with zipfile.ZipFile(zipado, "w") as pacote:
            pacote.writestr("nota.xml", xml_nfe())
        pacote = self.importador.analisar_pacote(zipado)
        self.assertEqual(len(pacote), 1)
        self.assertEqual(pacote[0].numero, "100")
        nota = Path(self.pasta.name) / "fardo.xml"
        nota.write_text("""<?xml version="1.0" encoding="UTF-8"?>
        <nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe35261012345678000199550010000001001000000011">
          <ide><mod>55</mod><serie>1</serie><nNF>101</nNF><dhEmi>2026-10-04T10:00:00-03:00</dhEmi></ide>
          <emit><CNPJ>12345678000199</CNPJ><xNome>Distribuidora Exemplo</xNome></emit>
          <det nItem="1"><prod><cProd>FD12</cProd><cEAN>SEM GTIN</cEAN><xProd>FARDO CERVEJA</xProd>
            <NCM>22030000</NCM><uCom>FD</uCom><qCom>2.0000</qCom><vUnCom>30.00</vUnCom><vProd>60.00</vProd></prod>
            <imposto><IPI><IPITrib><vIPI>6.00</vIPI></IPITrib></IPI>
            <ICMS><ICMS10><vICMSST>4.00</vICMSST></ICMS10></ICMS></imposto></det>
        </infNFe></NFe></nfeProc>""", encoding="utf-8")
        previa = self.importador.analisar(nota)
        self.assertEqual(previa.serie, "1")
        self.assertEqual(previa.itens[0].custo_total_cent, 7000)
        self.assertEqual(previa.itens[0].ncm, "22030000")
        previa.itens[0].fator = 12
        self.importador.importar(previa, "Adega", precos_venda={1: 400})
        produto = self.banco.um("SELECT id, qt_atual, ult_preco_cent FROM produtos WHERE nome = 'FARDO CERVEJA'")
        self.assertEqual(produto["qt_atual"], 24)
        self.assertEqual(produto["ult_preco_cent"], 292)
        outra = Path(self.pasta.name) / "fardo2.xml"
        outra.write_text(nota.read_text(encoding="utf-8").replace("00000011", "00000012").replace("<nNF>101</nNF>", "<nNF>102</nNF>"),
                         encoding="utf-8")
        de_novo = self.importador.analisar(outra)
        self.assertEqual(de_novo.itens[0].produto_id, produto["id"])
        self.assertEqual(de_novo.itens[0].fator, 12)

    def test_preco_minimo_configuravel_desligado_nao_gera_alertas(self):
        produto = self.novo_produto("CERVEJA LATA", 500, estoque=True, qt=4, cbarra="7891234567895")
        previa = self.importador.analisar(self.arquivo)
        self.assertEqual(self.importador.importar(previa, "Adega")["alertas_margem"], [])
        self.assertEqual(self.banco.valor("SELECT preco_cent FROM produtos WHERE id = ?", (produto,)), 500)
