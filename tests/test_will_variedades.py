"""Will Variedades (loja de eletrônicos, utilidades e presentes): edição, catálogo e etiqueta com código de barras."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from src.atualizacao import manifesto
from src.controllers import catalogo
from src.controllers.catalogo import CATALOGO_VARIEDADES, CatalogoController, conferir_catalogo
from src.controllers.config_controller import ConfigController
from src.controllers.contexto import Contexto
from src.controllers.etiqueta_controller import (
    MODELOS, EtiquetaController, codigo_interno, digito_ean, ean_valido, modulos_ean, svg_barras)
from src.controllers.primeiros_passos import PrimeirosPassos
from src.controllers.produto_controller import ProdutoController
from src.core import ed25519, edicao, licenca
from src.core.erros import ErroNegocio
from src.database.conexao import BancoDados
from src.fiscal import ncm
from tests.base import BaseTeste

VARIEDADES = {edicao.VARIAVEL: "willvariedades"}
RAIZ = Path(__file__).resolve().parents[1]


def na_edicao(teste):
    contexto = patch.dict(os.environ, VARIEDADES)
    contexto.start()
    teste.addCleanup(contexto.stop)


def indice(nome):
    return next(i for i, item in enumerate(CATALOGO_VARIEDADES) if item.nome == nome)


class TesteEdicao(unittest.TestCase):
    def setUp(self):
        na_edicao(self)
        self.banco = BancoDados(":memory:")
        self.addCleanup(self.banco.fechar)
        self.mudancas = edicao.preparar(self.banco)

    def test_edicao_tem_marca_dados_executavel_e_instalador_proprios(self):
        ed = edicao.atual()
        self.assertEqual((ed.nome, ed.pasta_dados, ed.executavel, ed.script_instalador),
                         ("Will Variedades", "WILL-VARIEDADES", "WillVariedades", "WillVariedades.iss"))
        pasta = edicao.pasta_recursos()
        for arquivo in (ed.icone, ed.logotipo, "willvariedades-assistente.bmp", "willvariedades-assistente-pequena.bmp"):
            self.assertTrue((pasta / arquivo).is_file(), arquivo)
        self.assertIn("willvariedades", manifesto.EDICOES)
        import build_pdv
        self.assertEqual(build_pdv.edicao_escolhida(["--edicao", "willvariedades"]).executavel, "WillVariedades")
        self.assertIn("--edicao willvariedades", (RAIZ / "iniciar_will_variedades.bat").read_text(encoding="utf-8"))

    def test_instalador_usa_o_executavel_a_pasta_e_um_appid_so_dele(self):
        texto = (RAIZ / "instalador" / "WillVariedades.iss").read_text(encoding="utf-8-sig")
        for trecho in ('#define Nome "Will Variedades"', '#define Exe "WillVariedades.exe"',
                       "OutputBaseFilename=WillVariedades-Setup-", "WILL-VARIEDADES", "willvariedades-assistente.bmp"):
            self.assertIn(trecho, texto)
        self.assertNotIn("estaurante", texto)
        appid = re.search(r"^AppId=(.+)$", texto, re.M).group(1)
        for outro in ("WillPDV.iss", "WillAdega.iss", "WillRestaurante.iss", "WillLicencas.iss"):
            self.assertNotIn(appid, (RAIZ / "instalador" / outro).read_text(encoding="utf-8-sig"), outro)

    def test_primeira_entrada_vira_loja_de_balcao_com_as_categorias_da_loja(self):
        self.assertTrue(self.mudancas)
        self.assertEqual((self.banco.cfg("perfil_operacao"), self.banco.cfg("edicao")), ("variedades", "willvariedades"))
        for chave in ("usar_mesas", "usar_garotas", "usar_portaria", "usar_rodizio", "usar_prepago", "usar_quartos",
                      "usar_cozinha_bar", "usar_delivery"):
            self.assertFalse(self.banco.cfg_bool(chave), chave)
        for chave in ("usar_caderneta", "usar_desconto", "agrupar_itens_balcao", "pagamento_direto"):
            self.assertTrue(self.banco.cfg_bool(chave), chave)
        self.assertEqual(self.banco.valor("SELECT acrescimo_cent FROM tipos_pagamento WHERE tipo = 'Cartão Crédito'"), 0)
        subgrupos = {r[0] for r in self.banco.todos("SELECT nome FROM subgrupos")}
        self.assertTrue(set(catalogo.CATALOGOS["variedades"].subgrupos) <= subgrupos)
        self.assertIsNotNone(self.banco.um("SELECT id FROM grupos WHERE nome = 'ELETRÔNICOS'"))

    def test_nada_de_casa_noturna_cozinha_gelada_nem_pedido_online(self):
        ed = edicao.atual()
        self.assertTrue(ed.sem_gelada)
        self.assertTrue({"cozinha", "quartos", "porteiro", "retornaveis"} <= ed.menu_oculto)
        fora = ed.fora_das_configuracoes()
        for chave in ("num_mesas", "usar_garotas", "usar_cozinha_bar", "pedido_online", "quartos_qtd"):
            self.assertIn(chave, fora)
        for chave in ("usar_garotas", "usar_mesas", "usar_cozinha_bar"):
            with self.assertRaises(ErroNegocio):
                ConfigController(self.banco).salvar_config({chave: "S"})
        self.assertTrue(ed.perfil_fixo())                 # não pergunta o tipo de negócio nos primeiros passos
        self.assertNotIn("perfil", {p["chave"] for p in PrimeirosPassos(self.banco).passos()})

    def test_reabrir_mantem_o_ajuste_do_dono_e_desliga_o_que_nao_existe(self):
        ConfigController(self.banco).salvar_config({"usar_caderneta": "N", "pagamento_direto": "N"})
        self.banco.cfg_set("usar_garotas", "S")
        self.assertEqual(edicao.preparar(self.banco), [])
        self.assertFalse(self.banco.cfg_bool("usar_caderneta"))
        self.assertFalse(self.banco.cfg_bool("pagamento_direto"))
        self.assertFalse(self.banco.cfg_bool("usar_garotas"))

    def test_licenca_do_variedades_nao_abre_outra_edicao_e_vice_versa(self):
        semente = bytes(range(32))
        publica = ed25519.chave_publica(semente)
        hoje = date(2026, 11, 17)
        codigo = licenca.gerar_licenca(semente, "LOJA-1", 30, hoje, "willvariedades")
        self.assertTrue(licenca.desta_edicao(licenca.ler_licenca(codigo, publica)))
        self.assertEqual(licenca.nome_da_edicao("willvariedades"), "Will Variedades")
        self.assertFalse(licenca.desta_edicao(licenca.ler_licenca(
            licenca.gerar_licenca(semente, "LOJA-1", 30, hoje, "willadega"), publica)))
        with patch.dict(os.environ, {edicao.VARIAVEL: "willadega"}):
            self.assertFalse(licenca.desta_edicao(licenca.ler_licenca(codigo, publica)))

    def test_central_do_fornecedor_oferece_o_programa(self):
        from backend.central_fornecedor import EDICOES, link_instalador
        self.assertEqual(EDICOES["willvariedades"].nome, "Will Variedades")
        self.assertTrue(link_instalador("willvariedades").endswith(           # o link fixo das Releases de downloads
            "/ultima-versao-variedades/WillVariedades-Instalador.exe"))
        with patch.dict(os.environ, {"PDV_INSTALADOR_WILLVARIEDADES": "https://exemplo/WillVariedades.exe"}):
            self.assertEqual(link_instalador("willvariedades"), "https://exemplo/WillVariedades.exe")


class TesteCatalogo(BaseTeste):
    def setUp(self):
        super().setUp()
        na_edicao(self)
        edicao.preparar(self.banco)
        self.cat = CatalogoController(self.banco, self.operador_adm())

    def produto(self, nome):
        return self.banco.um("SELECT p.*, s.nome AS subgrupo FROM produtos p JOIN subgrupos s ON s.id = p.subgrupo_id "
                             "WHERE p.nome = ?", (nome,))

    def test_catalogo_sem_problemas_com_todos_os_subgrupos_do_perfil(self):
        self.assertEqual(conferir_catalogo("variedades"), [])
        self.assertGreaterEqual(len(CATALOGO_VARIEDADES), 250)
        self.assertEqual({i.subgrupo for i in CATALOGO_VARIEDADES}, set(catalogo.CATALOGOS["variedades"].subgrupos))
        com_ncm = sum(bool(i.ncm) for i in CATALOGO_VARIEDADES)
        self.assertGreaterEqual(com_ncm / len(CATALOGO_VARIEDADES), 0.85)        # sem NCM só onde depende do material

    def test_tem_o_que_a_loja_vende(self):
        nomes = " | ".join(i.nome for i in CATALOGO_VARIEDADES)
        for trecho in ("FONE DE OUVIDO BLUETOOTH", "MEIA SOQUETE", "COPO PERSONALIZADO", "PANELA DE PRESSAO",
                       "CARREGADOR DE CELULAR", "CABO USB TIPO C"):
            self.assertIn(trecho, nomes)

    def test_ncm_bate_com_a_sugestao_do_cadastro_e_a_adega_continua_batendo(self):
        for tipo, cat in catalogo.CATALOGOS.items():
            divergentes = [i.nome for i in cat.itens if (ncm.sugerir(i.nome) or ("",))[0] != i.ncm]
            self.assertEqual(divergentes, [], tipo)

    def test_a_edicao_abre_o_catalogo_dela(self):
        self.assertEqual(catalogo.tipo_da_edicao(), "variedades")
        self.assertEqual(self.cat.catalogo.tipo, "variedades")
        self.assertEqual([i["nome"] for i in self.cat.itens(busca="fone tws")], ["FONE DE OUVIDO BLUETOOTH TWS"])
        self.assertEqual(self.cat.itens(busca="skol"), [])
        with patch.dict(os.environ, {edicao.VARIAVEL: "willpdv"}):
            self.assertEqual(catalogo.tipo_da_edicao(), "adega")
        with self.assertRaises(ErroNegocio):
            catalogo.catalogo("farmacia")

    def test_adiciona_com_preco_subgrupo_e_ncm_e_sem_ncm_quando_o_catalogo_nao_tem(self):
        fone, pilha = indice("FONE DE OUVIDO BLUETOOTH TWS"), indice("PILHA ALCALINA AA 2 UNIDADES")
        self.assertEqual(self.cat.adicionar({fone: 4990, pilha: 1200}), {"criados": 2, "ja_tinha": 0})
        p = self.produto("FONE DE OUVIDO BLUETOOTH TWS")
        self.assertEqual((p["preco_cent"], p["subgrupo"], p["ncm"]), (4990, "FONES E ÁUDIO", "85183000"))
        self.assertFalse(p["cbarra"])
        pilha = self.produto("PILHA ALCALINA AA 2 UNIDADES")
        self.assertEqual((pilha["subgrupo"], pilha["ncm"] or ""), ("PILHAS E LANTERNAS", ""))
        self.assertEqual(self.cat.adicionar({fone: 100}), {"criados": 0, "ja_tinha": 1})
        self.assertEqual(self.produto("FONE DE OUVIDO BLUETOOTH TWS")["preco_cent"], 4990)


class TesteCodigoDeBarras(BaseTeste):
    def setUp(self):
        super().setUp()
        self.etq = EtiquetaController(self.banco)

    def test_digito_verificador_de_codigos_reais(self):
        self.assertEqual(digito_ean("789100031550"), "7")
        self.assertEqual(digito_ean("9638507"), "4")
        self.assertTrue(ean_valido("7891000315507"))
        self.assertTrue(ean_valido("96385074"))
        for ruim in ("7891000315508", "123", "", None, "78910003155A7", "789100031550712"):
            self.assertFalse(ean_valido(ruim), ruim)

    def test_barras_do_ean13_e_do_ean8_seguem_a_tabela(self):
        # 4006381333931: o primeiro dígito (4) manda a paridade LGLLGG dos seis seguintes; depois 01010 e a tabela R.
        self.assertEqual(modulos_ean("4006381333931"),
                         "101" + "0001101" "0100111" "0101111" "0111101" "0001001" "0110011"
                         + "01010" + "1000010" "1000010" "1000010" "1110100" "1000010" "1100110" + "101")
        self.assertEqual(len(modulos_ean("96385074")), 67)
        with self.assertRaises(ErroNegocio):
            modulos_ean("4006381333932")
        svg = svg_barras("4006381333931")
        self.assertIn('viewBox="0 0 113 10"', svg)                        # 95 módulos + 9 de margem de cada lado
        larguras = sum(int(l) for l in re.findall(r'width="(\d+)"', svg))
        self.assertEqual(larguras, modulos_ean("4006381333931").count("1"))

    def test_codigo_proprio_usa_a_faixa_interna_e_nunca_repete(self):
        codigos = [codigo_interno(i) for i in (1, 2, 17, 999_999_999)]
        self.assertEqual(codigos[2], "2000000000176")
        self.assertEqual(len(set(codigos)), 4)
        for codigo in codigos:
            self.assertTrue(codigo.startswith("200") and ean_valido(codigo), codigo)
        for ruim in (0, -1, 10 ** 9, "5", 1.0):
            with self.assertRaises(ErroNegocio):
                codigo_interno(ruim)

    def test_gera_so_para_quem_nao_tem_e_o_caixa_passa_a_ler(self):
        meia = self.novo_produto("MEIA SOQUETE", preco=990)
        fone = self.novo_produto("FONE", preco=4990, cbarra="7891000315507")
        self.assertEqual([p["id"] for p in self.etq.sem_codigo([meia, fone, meia, 9999])], [meia])
        self.assertEqual(self.etq.gerar_codigos([meia, fone], self.operador_adm()), 1)
        codigo = self.banco.valor("SELECT cbarra FROM produtos WHERE id = ?", (meia,))
        self.assertEqual(codigo, codigo_interno(meia))
        self.assertEqual(self.banco.valor("SELECT cbarra FROM produtos WHERE id = ?", (fone,)), "7891000315507")
        self.assertEqual(ProdutoController(self.banco).buscar_codigo(codigo)["id"], meia)       # o leitor do caixa acha
        self.assertEqual(self.etq.gerar_codigos([meia, fone]), 0)                               # repetir não muda nada
        self.assertIsNotNone(self.banco.um("SELECT 1 FROM log_eventos WHERE evento = 'etiqueta_codigos'"))

    def test_codigo_ja_usado_em_outro_produto_recusa_tudo(self):
        a = self.novo_produto("COPO A")
        b = self.novo_produto("COPO B")
        self.novo_produto("COPO C", cbarra=codigo_interno(b))
        with self.assertRaises(ErroNegocio):
            self.etq.gerar_codigos([a, b])
        self.assertFalse(self.banco.valor("SELECT cbarra FROM produtos WHERE id = ?", (a,)))      # tudo ou nada

    def test_folha_tem_nome_barras_numero_e_preco(self):
        meia = self.novo_produto("MEIA <SOQUETE> & CIA", preco=990)
        self.etq.gerar_codigos([meia])
        html = self.etq.folha_html(self.etq.etiquetas([{"produto_id": meia, "copias": 3}]))
        self.assertEqual(html.count("<svg"), 3)
        self.assertEqual(html.count(codigo_interno(meia)), 3)
        self.assertIn("MEIA &lt;SOQUETE&gt; &amp; CIA", html)
        self.assertIn("R$ 9,90", html)
        self.assertIn("size: A4", html)
        self.assertEqual(html.count('<section class="pagina">'), 1)

    def test_folha_pula_usadas_pagina_e_sai_sem_barras_quando_o_codigo_nao_e_ean(self):
        com = self.novo_produto("CABO USB", preco=1500, cbarra="7891000315507")
        sem = self.novo_produto("PANELA", preco=5990, codigo="0000000000777")
        outro = self.novo_produto("CAIXA FECHADA", preco=9000, cbarra="17891000315504")        # 14 números: não é EAN-13
        etiquetas = self.etq.etiquetas([{"produto_id": com, "copias": 30}, {"produto_id": sem}, {"produto_id": outro}])
        html = self.etq.folha_html(etiquetas, "a4_33", pular=3)
        self.assertEqual(html.count("<svg"), 30)
        self.assertEqual(html.count('<div class="etiqueta"></div>'), 3)
        self.assertEqual(html.count('<section class="pagina">'), 2)            # 3 + 32 etiquetas em folhas de 33
        self.assertIn("Cód 0000000000777", html)
        self.assertIn("Cód " + self.banco.valor("SELECT codigo FROM produtos WHERE id = ?", (outro,)), html)
        rolo = self.etq.folha_html(etiquetas[:2], "rolo_40x25")
        self.assertIn("size: 40.0mm 25.0mm", rolo)
        self.assertEqual(rolo.count('<section class="pagina">'), 2)            # uma etiqueta por página
        for modelo, pular in (("a3", 0), ("a4_33", 33), ("a4_33", -1), ("rolo_40x25", 1), ("a4_65", "2")):
            with self.assertRaises(ErroNegocio):
                self.etq.folha_html(etiquetas, modelo, pular)
        with self.assertRaises(ErroNegocio):
            self.etq.folha_html([])

    def test_atacado_aparece_so_na_etiqueta_que_tem_espaco(self):
        pid = self.novo_produto("MEIA", preco=1000)
        self.banco.executar("UPDATE produtos SET atacado_qtd = 3, preco_atacado_cent = 800 WHERE id = ?", (pid,))
        etiquetas = self.etq.etiquetas([{"produto_id": pid}])
        self.assertIn("3+ un: R$ 8,00", self.etq.folha_html(etiquetas, "a4_33"))
        self.assertNotIn("3+ un", self.etq.folha_html(etiquetas, "a4_65"))

    def test_medidas_das_folhas_cabem_no_a4(self):
        for chave, (_nome, m) in MODELOS.items():
            if m.get("rolo"):
                continue
            largura = 2 * m["esquerda"] + m["colunas"] * m["largura"] + (m["colunas"] - 1) * m["vao"]
            altura = 2 * m["topo"] + m["linhas"] * m["altura"]
            self.assertAlmostEqual(largura, 210, delta=0.6, msg=chave)
            self.assertAlmostEqual(altura, 297, delta=0.6, msg=chave)


class TesteTelas(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.janelas = []
        self.addCleanup(self._fechar_janelas)

    def _fechar_janelas(self):
        """Fecha e destrói as janelas ainda com o banco aberto: janela viva na saída do processo derruba o Qt no Windows."""
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.janelas.clear()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def aberta(self, janela):
        self.janelas.append(janela)
        return janela

    def janela_etiquetas(self, *ids):
        from src.ui_qt.etiquetas import JanelaEtiquetas
        produtos = [dict(r) for r in self.banco.todos("SELECT id, codigo, nome FROM produtos WHERE id IN (%s)"
                                                      % ",".join("?" * len(ids)), ids)]
        return self.aberta(JanelaEtiquetas(self.ctx, produtos, list(ids)))

    def test_folha_com_codigo_de_barras_gera_o_codigo_e_grava_o_arquivo(self):
        meia = self.novo_produto("MEIA SOQUETE", preco=990)
        janela = self.janela_etiquetas(meia)
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "etiquetas.html")
            self.assertTrue(janela.folha_barras(caminho, gerar=True, abrir=False), janela.mensagem.text())
            html = Path(caminho).read_text(encoding="utf-8")
        self.assertIn(codigo_interno(meia), html)
        self.assertEqual(html.count("<svg"), 1)
        self.assertEqual(self.banco.valor("SELECT cbarra FROM produtos WHERE id = ?", (meia,)), codigo_interno(meia))

    def test_sem_gerar_imprime_sem_barras_e_nao_mexe_no_cadastro(self):
        meia = self.novo_produto("MEIA SOQUETE", preco=990)
        janela = self.janela_etiquetas(meia)
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "etiquetas.html")
            self.assertTrue(janela.folha_barras(caminho, gerar=False, abrir=False))
            self.assertNotIn("<svg", Path(caminho).read_text(encoding="utf-8"))
        self.assertFalse(self.banco.valor("SELECT cbarra FROM produtos WHERE id = ?", (meia,)))

    def test_desistir_na_pergunta_nao_faz_nada_e_sem_selecao_avisa(self):
        meia = self.novo_produto("MEIA SOQUETE", preco=990)
        janela = self.janela_etiquetas(meia)
        with patch.object(janela, "_perguntar_codigos", return_value=None), tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "etiquetas.html")
            self.assertFalse(janela.folha_barras(caminho, abrir=False))
            self.assertFalse(os.path.exists(caminho))
        janela.grade.clearSelection()
        self.assertFalse(janela.folha_barras(abrir=False))
        self.assertIn("Selecione", janela.mensagem.text())

    def test_pular_so_vale_na_folha_a4(self):
        janela = self.janela_etiquetas(self.novo_produto("MEIA"))
        janela.modelo.setCurrentIndex(janela.modelo.findData("a4_65"))
        self.assertEqual(janela.pular.maximum(), 64)
        janela.modelo.setCurrentIndex(janela.modelo.findData("rolo_40x25"))
        self.assertFalse(janela.pular.isEnabled())
        self.assertEqual(janela.pular.maximum(), 0)

    def test_temperatura_some_so_no_variedades(self):
        pid = self.novo_produto("MEIA")
        self.assertFalse(self.janela_etiquetas(pid).temperatura.isHidden())
        na_edicao(self)
        self.assertTrue(self.janela_etiquetas(pid).temperatura.isHidden())

    def test_cadastro_de_produto_sem_gelada_nem_casco_e_com_a_aba_atacado(self):
        from src.ui_qt.cadastros import FormularioCadastro
        completo = self.aberta(FormularioCadastro(self.ctx, "produtos"))
        self.assertIn("preco_gelada_cent", completo.campos)
        na_edicao(self)
        f = self.aberta(FormularioCadastro(self.ctx, "produtos"))
        for campo in ("preco_gelada_cent", "atacado_gelada_qtd", "preco_atacado_gelada_cent", "casco_produto_id",
                      "promo_gelada_cent"):
            self.assertNotIn(campo, f.campos)
        self.assertIn("atacado_qtd", f.campos)
        from PySide6.QtWidgets import QTabWidget
        abas = f.findChild(QTabWidget)
        titulos = [abas.tabText(i) for i in range(abas.count())]
        self.assertIn("Atacado", titulos)
        self.assertNotIn("Adega", titulos)
        f.campos["nome"].setText("MEIA SOQUETE")
        f.campos["preco_cent"].setText("9,90")
        f.campos["atacado_qtd"].setText("3")
        f.campos["preco_atacado_cent"].setText("8,00")
        f.campos["subgrupo_id"].setCurrentIndex(1)
        f.campos["unidade_id"].setCurrentIndex(1)
        f.salvar()
        self.assertEqual(f.mensagem.text(), "")
        p = self.banco.um("SELECT * FROM produtos WHERE nome = 'MEIA SOQUETE'")
        self.assertEqual((p["preco_cent"], p["preco_gelada_cent"], p["atacado_qtd"], p["preco_atacado_cent"]),
                         (990, 0, 3, 800))

    def test_catalogo_abre_o_de_variedades(self):
        na_edicao(self)
        edicao.preparar(self.banco)
        from src.ui_qt.catalogo import JanelaCatalogo
        janela = self.aberta(JanelaCatalogo(self.ctx))
        self.assertIn("FONES E ÁUDIO", [janela.cmb_subgrupo.itemText(i) for i in range(janela.cmb_subgrupo.count())])
        janela.ent_busca.setText("meia soquete masculina")
        self.assertEqual(janela.tabela.rowCount(), 1)
        janela.tabela.item(0, janela.COL_PRECO).setText("9,9")
        self.assertTrue(janela.adicionar())
        self.assertEqual(self.banco.valor("SELECT ncm FROM produtos WHERE nome = 'MEIA SOQUETE MASCULINA'"), "61159500")


if __name__ == "__main__":
    unittest.main()
