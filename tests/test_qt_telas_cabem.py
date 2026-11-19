"""Telas que cabem: nada cortado no caixa, nas listas e nos formulários, do monitor de 1024x768 ao de 1366x768.

A medição é a de `tools/conferir_telas.py` (texto maior que o botão, campo para fora da janela, campos sobrepostos,
cabeçalho de tabela cortado, rolagem de lado). O monitor é simulado trocando a área útil que o tema enxerga; os tamanhos
são os da área útil com a barra de tarefas do Windows (40 pontos): 1366x728, 1280x680, 1024x728.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent, QRect
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHeaderView, QLabel, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from src.controllers.cadastro_controller import CadastroController
from src.ui_qt import tema
from tests.test_qt_caixa import BaseCaixaQt
from tools import conferir_telas

NOTEBOOK = (1366, 728)
ESTREITO = (1024, 728)


class BaseTelas(BaseCaixaQt):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        anterior = cls.aplicacao.styleSheet()
        cls.addClassCleanup(cls.aplicacao.setStyleSheet, anterior)
        tema.aplicar(cls.aplicacao)

    def setUp(self):
        super().setUp()
        self.outras = []
        self.addCleanup(self._fechar_outras)
        self.area = QRect(0, 0, *NOTEBOOK)             # o monitor que o tema enxerga neste teste
        troca = mock.patch.object(tema, "_area_util", side_effect=lambda _janela: self.area)
        troca.start()
        self.addCleanup(troca.stop)

    def _fechar_outras(self):
        for janela in reversed(self.outras):
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def eventos(self):
        for _ in range(3):
            self.aplicacao.processEvents()

    def monitor(self, largura: int, altura: int):
        """Faz o tema enxergar um monitor com esta área útil."""
        self.area = QRect(0, 0, largura, altura)

    def abrir(self, janela, tela=NOTEBOOK):
        """Mostra como o PDV mostra: a janela aparece e passa pelo ajuste da primeira exibição."""
        self.monitor(*tela)
        self.outras.append(janela)
        janela.show()
        tema.ajustar_na_primeira_exibicao(janela)
        self.eventos()
        return janela

    def assertNadaCortado(self, janela, nome=None, ignorar=()):
        achados = conferir_telas.por_estado(janela, nome or type(janela).__name__)
        achados = {estado: [a for a in lista if not any(trecho in a for trecho in ignorar)]
                   for estado, lista in achados.items()}
        self.assertEqual({estado: lista for estado, lista in achados.items() if lista}, {})

    def produtos_de_exemplo(self):
        return [self.novo_produto(nome, preco, codigo=codigo) for codigo, nome, preco in (
            ("1", "CERVEJA LATA 350ML", 750), ("2", "REFRIGERANTE LATA", 600),
            ("5", "PORCAO DE FRITAS COM QUEIJO E BACON GRANDE", 3200), ("4", "DOSE WHISKY RED LABEL 12 ANOS", 1800))]


class TesteCaixaCabe(BaseTelas):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("usar_quartos", "S")
        self.banco.cfg_set("caixa_tela_cheia", "N")
        self.produtos_de_exemplo()
        self.abrir_turno()
        self.caixa = self.janela()

    def tamanho(self, largura, altura):
        """O caixa ocupando a tela inteira de um monitor desta área útil. O ajuste do tema vem antes, como ao abrir:
        é ele que deixa a janela ficar menor que o mínimo do layout quando o monitor é pequeno."""
        self.monitor(largura, altura)
        tema.ajustar_janela(self.caixa)
        self.caixa.resize(largura, altura)
        self.eventos()

    def lancar(self, *codigos):
        for codigo in codigos:
            self.caixa.ent_codigo.setText(codigo)
            self.caixa.btn_lancar.click()
        self.eventos()

    def test_nada_cortado_do_monitor_de_1024_ao_de_1600(self):
        self.lancar("1", "5", "4")
        for largura, altura in (ESTREITO, (1280, 680), NOTEBOOK, (1600, 860)):
            with self.subTest(tela=f"{largura}x{altura}"):
                self.tamanho(largura, altura)
                self.assertNadaCortado(self.caixa, "caixa")
                for aba in self.caixa.cartoes._abas.values():            # Todas, Abertas, Parciais, Acerto, Comissões
                    self.assertGreaterEqual(aba.width(), aba.sizeHint().width(), aba.text())
                self.assertGreaterEqual(self.caixa.btn_fechar_venda.width(), 150)

    def test_tela_estreita_troca_codigo_e_unidade_pelo_nome_do_produto(self):
        self.lancar("5")
        tabela, cabecalho = self.caixa.tabela, self.caixa.tabela.horizontalHeader()
        self.tamanho(*ESTREITO)
        self.assertTrue(tabela.isColumnHidden(0) and tabela.isColumnHidden(2))
        self.assertGreaterEqual(cabecalho.sectionSize(1), 120)                # antes sobravam 39 pontos para o nome
        self.assertEqual(self.caixa.lbl_cod_titulo.texto_exibido(), "Código ou nome:")
        self.assertEqual(self.caixa.lbl_cod_titulo.text(), "Código ou nome do produto:")    # o texto guardado não muda
        self.tamanho(*NOTEBOOK)
        self.assertFalse(tabela.isColumnHidden(0) or tabela.isColumnHidden(2))
        self.assertGreaterEqual(cabecalho.sectionSize(1), self.caixa.LARGURA_MINIMA_PRODUTO)
        self.assertEqual(self.caixa.lbl_cod_titulo.texto_exibido(), "Código ou nome do produto:")

    def test_painel_das_mesas_tem_a_largura_dos_cartoes_e_as_abas_quebram_em_duas_linhas(self):
        self.tamanho(*ESTREITO)
        cartoes = self.caixa.cartoes
        self.assertEqual(cartoes.colunas, 1)
        self.assertLessEqual(self.caixa.painel_mesas.width(), cartoes.width() + 20)
        self.assertEqual(len({aba.y() for aba in cartoes._abas.values()}), 2)
        self.tamanho(*NOTEBOOK)
        self.assertEqual(cartoes.colunas, 2)
        self.assertEqual(len({aba.y() for aba in cartoes._abas.values()}), 1)

    def test_atalhos_do_teclado_so_aparecem_os_que_cabem_inteiros(self):
        self.tamanho(*NOTEBOOK)
        self.assertTrue(all(tecla.isVisible() for tecla, _ in self.caixa._dicas_teclas))
        self.tamanho(916, 768)
        visiveis = [tecla.text() for tecla, _ in self.caixa._dicas_teclas if tecla.isVisible()]
        self.assertEqual(visiveis[0], "Enter")
        self.assertLess(len(visiveis), 4)
        for tecla, dica in self.caixa._dicas_teclas:
            if tecla.isVisible():
                self.assertGreaterEqual(tecla.width(), tecla.sizeHint().width() - 2)

    def test_janela_baixa_deixa_os_quartos_numa_fileira_e_a_lista_de_itens_a_vista(self):
        grade = self.caixa.painel_quartos.grade
        self.lancar("1", "5")
        self.tamanho(*NOTEBOOK)
        self.assertEqual(grade.POR_PAGINA, 8)                                 # duas fileiras, como sempre
        self.tamanho(1093, 574)                                               # notebook de 1366x768 com o Windows em 125%
        self.assertEqual(grade.POR_PAGINA, 4)
        self.assertEqual(grade.height(), grade.ALTURA)
        self.assertTrue(self.caixa.painel_quartos.proxima.isVisible())        # os outros quartos ficam nas páginas
        self.assertGreaterEqual(self.caixa.tabela.height(), 90)
        self.assertNadaCortado(self.caixa, "caixa baixo", ignorar=("rótulo cortado na altura",))
        self.tamanho(*NOTEBOOK)
        self.assertEqual(grade.POR_PAGINA, 8)


class TesteJanelasCabem(BaseTelas):
    def test_lista_de_produtos_abre_com_todas_as_colunas_sem_rolar_de_lado(self):
        from src.ui_qt.cadastros import JanelaCadastro
        self.produtos_de_exemplo()
        janela = self.abrir(JanelaCadastro(self.ctx, "produtos"))
        cabecalho = janela.grade.horizontalHeader()
        self.assertLessEqual(janela.width(), NOTEBOOK[0] - tema.RESERVA_LARGURA)
        self.assertGreater(janela.width(), 1000)                              # abria com 1000 e cortava a tabela
        self.assertLessEqual(cabecalho.length(), janela.grade.viewport().width())
        itens = [janela.grade.horizontalHeaderItem(i) for i in range(cabecalho.count())]
        cardapio = next(item for item in itens if item.toolTip() == "Mostrar no cardápio digital")
        self.assertIn("\n", cardapio.text())                                  # o título largo quebrou em linhas...
        self.assertEqual(" ".join(cardapio.text().split()), "Mostrar no cardápio digital")       # ...sem perder palavra
        self.assertEqual([item.text() for item in itens][:2], ["Código", "Produto"])
        self.assertNadaCortado(janela)

    def test_formularios_de_cadastro_nao_rolam_de_lado_em_nenhuma_aba(self):
        from src.controllers.config_controller import MODULOS_OPCIONAIS
        from src.ui_qt.cadastros import FormularioCadastro
        for chave in (*MODULOS_OPCIONAIS, "usar_caderneta", "usar_delivery"):
            self.banco.cfg_set(chave, "S")
        for chave in ("produtos", "tipos_pagamento", "setores_impressao", "fornecedores", "clientes", "operadores"):
            with self.subTest(cadastro=chave):
                self.assertNadaCortado(self.abrir(FormularioCadastro(self.ctx, chave)), f"formulário {chave}")

    def test_fechamento_do_turno_mostra_o_resultado_e_os_botoes_sem_rolar(self):
        from src.ui_qt.fechamento_turno import PainelFechamento
        skol = self.novo_produto("SKOL", 800, codigo="10")
        turno = self.abrir_turno()
        for forma in ("Dinheiro", "Pix"):
            venda = self.ctx.caixa.abrir_balcao()
            self.ctx.caixa.adicionar_item(venda, skol, 1)
            self.ctx.caixa.adicionar_pagamento(venda, self.tipo(forma), 800)
            self.ctx.caixa.fechar(venda)
        declarados = {r["tipo_id"]: 10800 if r["dinheiro"] else 0
                      for r in self.ctx.turnos.formas_conferencia(turno, self.ctx.operador_id)}
        res = self.ctx.turnos.fechar(turno, self.ctx.operador_id, 10800, informados_por_forma=declarados,
                                     justificativa="conferido")
        painel = self.abrir(PainelFechamento(self.ctx, res, vias_impressas=2))
        self.assertLessEqual(painel.height(), NOTEBOOK[1] - tema.RESERVA_ALTURA)
        self.assertIsNone(getattr(painel, "_will_rolagem", None))            # antes só cabia com rolagem
        for parte in (painel.faixa, painel.btn_concluir, painel.btn_imprimir, painel.lbl_impresso):
            self.assertTrue(painel.rect().contains(parte.geometry()), parte.text())
        self.assertNadaCortado(painel)

    def test_comissoes_mostram_os_titulos_e_o_nome_inteiros(self):
        from src.ui_qt.comissao import JanelaComissoes
        self.banco.cfg_set("usar_garotas", "S")
        CadastroController(self.banco).salvar("garotas", {"numero": "180", "nome": "ANA CAROLINA"})
        turno = self.abrir_turno()
        self.ctx.comissoes.lancar(180, 1500, turno, self.ctx.operador_id)
        caixa = self.janela()
        janela = self.abrir(JanelaComissoes(caixa))
        garotas, lancamentos = janela.tabela_garotas, janela.tabela_lancamentos
        self.assertEqual(garotas.horizontalHeader().sectionResizeMode(1), QHeaderView.ResizeMode.Stretch)
        self.assertEqual(lancamentos.horizontalHeader().sectionResizeMode(4), QHeaderView.ResizeMode.Stretch)
        self.assertGreaterEqual(garotas.columnWidth(1), 110)                  # o nome ficava com 48 pontos
        self.assertNadaCortado(janela)

    def test_janelas_de_muitos_botoes_cabem_no_monitor_de_1024(self):
        from src.ui_qt.assistente_impressora import JanelaAssistenteImpressora
        from src.ui_qt.contas import JanelaContas
        from src.ui_qt.estoque import JanelaEstoque
        from src.ui_qt.importar_produtos import JanelaImportarProdutos
        self.banco.cfg_set("usar_contas", "S")
        for classe in (JanelaAssistenteImpressora, JanelaContas, JanelaEstoque, JanelaImportarProdutos):
            with self.subTest(janela=classe.__name__):
                janela = self.abrir(classe(self.ctx), ESTREITO)
                self.assertLessEqual(janela.width(), ESTREITO[0] - tema.RESERVA_LARGURA)
                self.assertIsNone(getattr(janela, "_will_rolagem", None))    # cabia só rolando a janela inteira de lado
                self.assertNadaCortado(janela, ignorar=("tabela com rolagem de lado",))

    def test_telas_do_menu_sem_nada_cortado_no_notebook(self):
        """As telas que abrem direto do menu, uma a uma, no monitor de 1366x768."""
        from src.controllers.config_controller import MODULOS_OPCIONAIS
        for chave in (*MODULOS_OPCIONAIS, "usar_caderneta", "usar_delivery"):
            self.banco.cfg_set(chave, "S")
        self.produtos_de_exemplo()
        self.abrir_turno()
        telas = (
            "acessos.JanelaAcessos", "alertas.JanelaAlertas", "auditoria.JanelaAuditoria", "composicao.JanelaComposicao",
            "configuracoes.JanelaConfiguracoes", "contagem.JanelaContagem", "contas.JanelaContas", "cozinha.JanelaCozinha",
            "devolucoes.JanelaDevolucoes", "diagnostico.JanelaDiagnostico", "estoque.JanelaEstoque",
            "fila_impressao.JanelaFilaImpressao", "importar_produtos.JanelaImportarProdutos", "maquinas.JanelaMaquinas",
            "notas_fiscais.JanelaNotasFiscais", "promocoes.JanelaPromocoes", "quartos.JanelaQuartos",
            "relatorio_vendas.JanelaRelatorioVendas", "relatorios.JanelaRelatorios", "retornaveis.JanelaRetornaveis",
            "utilitarios.JanelaUtilitarios", "restaurar_backup.JanelaVerificarBackup", "vendas_teste.JanelaSenhaSeguranca",
            "catalogo.JanelaCatalogo", "estoque_lancamentos.JanelaLancamentosEstoque",
        )
        import importlib
        for caminho in telas:
            modulo, classe = caminho.split(".")
            with self.subTest(tela=classe):
                janela = getattr(importlib.import_module(f"src.ui_qt.{modulo}"), classe)(self.ctx)
                self.assertNadaCortado(self.abrir(janela))
                janela.close()


class TesteAjudantesDoTema(BaseTelas):
    def botoes(self, layout, *textos):
        criados = []
        for texto in textos:
            botao = QPushButton(texto)
            layout.addWidget(botao)
            criados.append(botao)
        return criados

    def test_linha_fluida_fica_numa_linha_quando_cabe_e_quebra_quando_nao(self):
        janela = QWidget()
        self.outras.append(janela)
        linha = tema.LinhaFluida()
        QVBoxLayout(janela).addLayout(linha)
        botoes = self.botoes(linha, "Configurar e enviar teste", "Atualizar (F5)", "Copiar diagnóstico",
                             "Configurações do Windows", "Fechar")
        natural = linha.sizeHint()
        self.assertEqual(natural.width(), sum(b.sizeHint().width() for b in botoes) + 4 * linha.spacing())
        self.assertEqual(linha.minimumSize().width(), max(b.sizeHint().width() for b in botoes))
        self.assertEqual(linha.heightForWidth(natural.width()), natural.height())
        self.assertGreater(linha.heightForWidth(natural.width() // 2), natural.height())
        janela.resize(natural.width() + 200, 200)
        janela.show()
        self.eventos()
        self.assertEqual(len({b.y() for b in botoes}), 1)                    # tela larga: uma linha, dividindo a sobra
        self.assertGreater(botoes[-1].width(), botoes[-1].sizeHint().width())
        janela.resize(natural.width() // 2, 300)
        self.eventos()
        self.assertGreater(len({b.y() for b in botoes}), 1)
        for botao in botoes:
            self.assertGreaterEqual(botao.width(), botao.sizeHint().width(), botao.text())
            self.assertLessEqual(botao.x() + botao.width(), janela.width())
        self.assertEqual(botoes[-1].width(), botoes[-1].sizeHint().width())   # a última linha fica no tamanho natural

    def test_linha_fluida_ignora_escondidos_e_deixa_a_sobra_com_o_elastico(self):
        janela = QWidget()
        self.outras.append(janela)
        linha = tema.LinhaFluida()
        QVBoxLayout(janela).addLayout(linha)
        primeiro, escondido = self.botoes(linha, "Escolher planilha…", "Só no Windows")
        rotulo = QLabel("Nenhuma planilha escolhida")
        linha.addWidget(rotulo, 1)
        ultimo, = self.botoes(linha, "Exportar produtos…")
        escondido.hide()
        self.assertEqual(linha.sizeHint().width(), primeiro.sizeHint().width() + rotulo.sizeHint().width()
                         + ultimo.sizeHint().width() + 2 * linha.spacing())
        janela.resize(900, 120)
        janela.show()
        self.eventos()
        self.assertEqual(primeiro.width(), primeiro.sizeHint().width())
        self.assertGreater(rotulo.width(), rotulo.sizeHint().width() + 100)
        self.assertEqual(linha.takeAt(0).widget(), primeiro)
        self.assertEqual(linha.count(), 3)
        self.assertIsNone(linha.itemAt(9))

    def test_titulo_de_coluna_largo_demais_quebra_em_linhas_equilibradas(self):
        medir = lambda texto: len(texto) * 7                                  # noqa: E731 - 7 pontos por letra
        self.assertEqual(tema.quebrar_titulo("Mostrar no cardápio digital", medir, 20), "Mostrar no\ncardápio digital")
        self.assertEqual(tema.quebrar_titulo("Produto", medir, 20), "Produto")
        self.assertEqual(tema.quebrar_titulo("Preço de venda", medir, 20), "Preço de venda")       # cabe em 110 pontos
        self.assertEqual(tema.quebrar_titulo("Preço de venda", medir, 20, 80), "Preço de\nvenda")
        self.assertEqual(tema.quebrar_titulo("Sub Grupo - Grupo", medir, 150), "Sub Grupo - Grupo")  # os dados já são largos
        self.assertEqual(tema.quebrar_titulo("Já tem\nquebra feita à mão", medir, 20), "Já tem\nquebra feita à mão")
        longo = tema.quebrar_titulo("Acréscimo cobrado do cliente por venda (ex.: taxa do crédito)", medir, 30)
        self.assertEqual(longo.count("\n"), tema.LINHAS_TITULO - 1)
        self.assertEqual(" ".join(longo.split()), "Acréscimo cobrado do cliente por venda (ex.: taxa do crédito)")

    def tabela(self, titulos, linha, modo):
        janela = QDialog()
        self.outras.append(janela)
        tabela = QTableWidget(1, len(titulos))
        tabela.setHorizontalHeaderLabels(titulos)
        for coluna, texto in enumerate(linha):
            tabela.setItem(0, coluna, QTableWidgetItem(texto))
        tabela.verticalHeader().setVisible(False)
        if modo is not None:
            tabela.horizontalHeader().setSectionResizeMode(modo)
            tabela.horizontalHeader().setStretchLastSection(True)
        QVBoxLayout(janela).addWidget(tabela)
        return janela, tabela

    def test_lista_que_se_mede_pelo_conteudo_deixa_o_nome_elastico_e_o_resto_inteiro(self):
        janela, tabela = self.tabela(
            ["Código", "Produto", "Preço de venda", "Mostrar no cardápio digital", "Ativo"],
            ["0000000000005", "PORCAO DE FRITAS COM QUEIJO E BACON GRANDE TAMANHO FAMILIA", "32,00", "S", "S"],
            QHeaderView.ResizeMode.ResizeToContents)
        janela.resize(720, 300)
        janela.show()
        self.eventos()
        cabecalho = tabela.horizontalHeader()
        self.assertGreater(cabecalho.length(), tabela.viewport().width())    # como abria: rolando de lado
        tema.tirar_rolagem_de_lado(janela, 720)                              # a tela não deixa a janela crescer
        self.eventos()
        self.assertLessEqual(cabecalho.length(), tabela.viewport().width())
        self.assertEqual(cabecalho.sectionResizeMode(1), QHeaderView.ResizeMode.Stretch)
        self.assertIn("\n", tabela.horizontalHeaderItem(3).text())
        self.assertEqual(" ".join(tabela.horizontalHeaderItem(3).text().split()), "Mostrar no cardápio digital")
        self.assertEqual(tabela.horizontalHeaderItem(3).toolTip(), "Mostrar no cardápio digital")
        self.assertEqual(conferir_telas.problemas(janela), [])

    def test_janela_cresce_ate_a_lista_caber_quando_a_tela_deixa(self):
        janela, tabela = self.tabela(
            ["Código", "Produto", "Grupo", "Unidade", "Qt. atual"],
            ["0000000000005", "PORCAO DE FRITAS COM QUEIJO E BACON GRANDE", "DIVERSOS - DIVERSOS", "Unidade", "0"],
            QHeaderView.ResizeMode.ResizeToContents)
        janela.resize(420, 300)
        janela.show()
        self.eventos()
        tema.tirar_rolagem_de_lado(janela, 1350)
        self.eventos()
        self.assertGreater(janela.width(), 420)
        self.assertLessEqual(tabela.horizontalHeader().length(), tabela.viewport().width())
        self.assertEqual(tabela.horizontalHeader().sectionResizeMode(1), QHeaderView.ResizeMode.ResizeToContents)
        self.assertEqual(tabela.horizontalHeaderItem(1).text(), "Produto")   # coube alargando: nenhum título mexido

    def test_colunas_de_largura_livre_cedem_na_mesma_proporcao_sem_passar_do_piso(self):
        janela, tabela = self.tabela(["Nº", "Descrição", "Observação", "Valor"],
                                     ["1", "CONTA DE ENERGIA ELETRICA DO MES DE NOVEMBRO " * 2,
                                      "PAGA COM ATRASO, JUROS NEGOCIADOS COM A CONCESSIONARIA " * 2, "1.234,56"], None)
        janela.resize(700, 300)
        janela.show()
        tema.ajustar_tabelas(janela)                                          # é a tabela que o tema dimensiona
        self.eventos()
        cabecalho = tabela.horizontalHeader()
        antes = [cabecalho.sectionSize(i) for i in range(4)]
        tema.tirar_rolagem_de_lado(janela, 700)
        self.eventos()
        depois = [cabecalho.sectionSize(i) for i in range(4)]
        self.assertLessEqual(cabecalho.length(), tabela.viewport().width())
        self.assertEqual(depois[0], antes[0])                                 # coluna estreita não cede
        self.assertLess(depois[1], antes[1])
        self.assertGreaterEqual(min(depois[1], depois[2]), tema.PISO_COLUNA)

    def test_ultima_coluna_que_estica_entra_na_conta_pelo_que_precisa(self):
        janela, tabela = self.tabela(["Produto", "Preço manual (R$)"], ["CERVEJA", "4,64"],
                                     QHeaderView.ResizeMode.ResizeToContents)
        janela.resize(160, 200)
        janela.show()
        self.eventos()
        cabecalho = tabela.horizontalHeader()
        self.assertGreater(tema._largura_pedida(tabela), cabecalho.length())  # o Qt deixa a última com 100 pontos
        tema.tirar_rolagem_de_lado(janela, 1350)
        self.eventos()
        self.assertGreaterEqual(cabecalho.sectionSize(1), cabecalho.sectionSizeHint(1))
        self.assertEqual(conferir_telas.problemas(janela), [])

    def test_janela_mais_larga_que_a_tela_alivia_listas_e_textos_antes_de_rolar(self):
        class Larga(QDialog):
            pass
        Larga.__module__ = "src.ui_qt.exemplo"
        janela = Larga()
        caixa = QVBoxLayout(janela)
        lista = QComboBox()
        lista.addItem("DESPESAS OPERACIONAIS - MANUTENCAO E CONSERVACAO DE EQUIPAMENTOS DO SALAO PRINCIPAL " * 2)
        aviso = QLabel("Por segurança, instalar driver genérico e limpar ou destravar filas do Windows não estão "
                       "disponíveis nesta janela. Use o driver do fabricante nas configurações do Windows. " * 2)
        caixa.addWidget(lista)
        caixa.addWidget(aviso)
        self.assertGreater(janela.minimumSizeHint().width(), 1008)
        self.abrir(janela, ESTREITO)
        self.assertLessEqual(janela.width(), 1008)
        self.assertIsNone(getattr(janela, "_will_rolagem", None))            # coube sem embrulhar em rolagem
        self.assertTrue(aviso.wordWrap())
        self.assertEqual(lista.sizeAdjustPolicy(), QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.assertLessEqual(lista.width(), janela.width())
        # O item comprido aparece com reticências (aberta, a lista mostra inteiro): é o que cede para não rolar de lado.
        self.assertEqual([a for a in conferir_telas.problemas(janela) if "lista com o item cortado" not in a], [])

    def test_janela_alta_demais_ganha_rolagem_so_para_baixo(self):
        class Alta(QDialog):
            pass
        Alta.__module__ = "src.ui_qt.exemplo"
        janela = Alta()
        caixa = QVBoxLayout(janela)
        for numero in range(60):
            caixa.addWidget(QLabel(f"Linha {numero} do resumo do turno com um valor ao lado: 1.234,56"))
        self.abrir(janela, NOTEBOOK)
        rolagem = janela._will_rolagem
        self.assertIsInstance(rolagem, QScrollArea)
        self.assertGreater(rolagem.verticalScrollBar().maximum(), 0)
        self.assertEqual(rolagem.horizontalScrollBar().maximum(), 0)          # a barra de rolar para baixo já está na conta

    def test_botoes_das_mensagens_tem_largura_minima(self):
        self.assertIn("QDialogButtonBox QPushButton { min-width: 64px; }", tema.ESTILO)


class TesteConferencia(BaseTelas):
    """O medidor acusa o que deve: sem isto, um teste "sem nada cortado" não provaria nada."""

    def janela_com(self, widget, largura=300, altura=120):
        janela = QWidget()
        self.outras.append(janela)
        widget.setParent(janela)
        janela.resize(largura, altura)
        janela.show()
        self.eventos()
        return janela

    def test_acusa_botao_e_rotulo_com_texto_maior_que_o_espaco(self):
        botao = QPushButton("Painel completo dos quartos")
        janela = self.janela_com(botao)
        botao.setGeometry(10, 10, 70, 28)
        self.assertIn("botão com texto cortado", " ".join(conferir_telas.problemas(janela)))
        botao.setGeometry(10, 10, 260, 28)
        self.assertEqual(conferir_telas.problemas(janela), [])
        rotulo = QLabel("Código ou nome do produto:")
        janela = self.janela_com(rotulo)
        rotulo.setGeometry(10, 10, 60, 20)
        self.assertIn("rótulo cortado na largura", " ".join(conferir_telas.problemas(janela)))

    def test_acusa_campo_para_fora_da_janela_e_campos_sobrepostos(self):
        botao = QPushButton("Fechar")
        janela = self.janela_com(botao, 200, 100)
        botao.setGeometry(150, 80, 100, 40)
        self.assertIn("para fora da janela", " ".join(conferir_telas.problemas(janela)))
        outro = QPushButton("Salvar", janela)
        outro.show()
        botao.setGeometry(10, 10, 100, 30)
        outro.setGeometry(60, 15, 100, 30)
        self.assertIn("campos sobrepostos", " ".join(conferir_telas.problemas(janela)))

    def test_acusa_cabecalho_cortado_e_rolagem_de_lado_mas_nao_a_rolagem_para_baixo(self):
        tabela = QTableWidget(40, 3)
        tabela.setHorizontalHeaderLabels(["Shows dos quartos", "Quando", "Observação do lançamento"])
        janela = QWidget()
        self.outras.append(janela)
        QVBoxLayout(janela).addWidget(tabela)
        janela.resize(260, 200)
        janela.show()
        self.eventos()
        tabela.setColumnWidth(0, 60)
        achados = " ".join(conferir_telas.problemas(janela))
        self.assertIn("cabeçalho de tabela cortado: Shows dos quartos", achados)
        self.assertIn("tabela com rolagem de lado", achados)
        janela.resize(700, 200)
        tabela.resizeColumnsToContents()
        self.eventos()
        self.assertGreater(tabela.verticalScrollBar().maximum(), 0)
        self.assertEqual(conferir_telas.problemas(janela), [])


if __name__ == "__main__":
    import unittest
    unittest.main()
