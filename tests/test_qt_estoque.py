"""Consulta Qt de estoque com controlador real e banco isolado em memória."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QInputDialog, QMessageBox, QPushButton,
)

from src.controllers.estoque_controller import EstoqueController
from src.core import formatacao as fmt
from src.core.erros import ErroNegocio, ErroPermissao
from src.ui.contexto import Contexto
from src.ui_qt.estoque import JanelaEstoque, _DialogoQuantidade
from src.ui_qt.tema import aplicar
from tests.base import BaseTeste


class TestEstoqueQt(BaseTeste):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)
        aplicar(cls.aplicacao)

    def setUp(self):
        super().setUp()
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        self.addCleanup(self._fechar_janelas)
        self.janelas = []

    def _fechar_janelas(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self):
        janela = JanelaEstoque(self.ctx)
        self.janelas.append(janela)
        return janela

    def produtos(self):
        sem = self.novo_produto("SKOL", estoque=True)
        ponto = self.novo_produto("BRAHMA", estoque=True, qt=5)
        normal = self.novo_produto("COCA", estoque=True, qt=30)
        livre = self.novo_produto("AGUA")
        inativo = self.novo_produto("INATIVO", estoque=True)
        self.banco.executar("UPDATE produtos SET ativo = 0 WHERE id = ?", (inativo,))
        for pid, minimo, custo in ((sem, 10, 200), (ponto, 5, 300), (normal, 6, 100)):
            self.banco.executar(
                "UPDATE produtos SET estoque_minimo = ?, ult_preco_cent = ? WHERE id = ?",
                (minimo, custo, pid))
        return sem, ponto, normal, livre

    def filtrar(self, janela, situacao):
        janela.situacao.setCurrentIndex(janela.situacao.findData(situacao))
        janela.btn_atualizar.click()

    def test_banco_vazio_e_historico_sem_selecao(self):
        janela = self.janela()
        self.assertEqual(janela.grade.rowCount(), 0)
        self.assertEqual(janela.linhas, [])
        self.assertIn("0 controlado(s)", janela.resumo.text())
        self.assertIn("R$ 0,00", janela.resumo.text())
        self.assertIn("Nenhum produto", janela.mensagem.text())
        janela.mostrar_historico()
        self.assertEqual(janela.historico.rowCount(), 0)

    def test_consulta_real_reutiliza_painel_resumo_e_grupos(self):
        self.produtos()
        with patch.object(EstoqueController, "painel", autospec=True,
                          side_effect=EstoqueController.painel) as painel:
            janela = self.janela()
        self.assertGreaterEqual(painel.call_count, 2)
        self.assertEqual(janela.linhas, self.ctx.estoque.painel())
        self.assertEqual(janela.grade.rowCount(), 3)
        self.assertEqual(janela.grade.item(0, 2).text(), "BRAHMA")
        self.assertEqual(janela.grade.item(0, 0).text(), "Repor")
        self.assertEqual(janela.grade.item(0, 6).text(), "5,0000")
        self.assertEqual(janela.grade.item(0, 8).text(), "R$ 15,00")
        self.assertIn("R$ 45,00", janela.resumo.text())
        self.assertEqual(
            [janela.grupo.itemData(i) for i in range(1, janela.grupo.count())],
            self.ctx.estoque.grupos())

    def test_filtros_respeitam_situacoes_e_excluem_inativos(self):
        sem, ponto, normal, livre = self.produtos()
        janela = self.janela()
        for situacao, pid in (("sem", sem), ("ponto", ponto), ("normal", normal), ("livre", livre)):
            with self.subTest(situacao=situacao):
                self.filtrar(janela, situacao)
                self.assertEqual([p["id"] for p in janela.linhas], [pid])
                self.assertIn("3 controlado(s)", janela.resumo.text())
        self.assertEqual(janela.grade.item(0, 4).text(), "—")
        self.assertEqual(janela.grade.item(0, 8).text(), "—")

    def test_visao_adega_combina_filtros_e_exibe_prioridade(self):
        sem, ponto, *_ = self.produtos()
        self.banco.executar("UPDATE produtos SET preco_gelada_cent = 1000 WHERE id IN (?, ?)", (sem, ponto))
        janela = self.janela()
        janela.visao.setCurrentIndex(janela.visao.findData(True))
        self.assertEqual([p["id"] for p in janela.linhas], [sem, ponto])
        self.assertIn("Resumo Adega", janela.resumo.text())
        self.assertIn("2 controlado(s)", janela.resumo.text())
        self.assertEqual(janela.grade.item(0, 11).text(), "Alta")
        self.assertEqual(janela.grade.item(1, 11).text(), "Média")
        self.filtrar(janela, "ponto")
        self.assertEqual([p["id"] for p in janela.linhas], [ponto])
        janela.busca.setText("skol")
        janela.atualizar()
        self.assertEqual(janela.linhas, [])
        janela.busca.clear()
        janela.visao.setCurrentIndex(janela.visao.findData(False))
        self.assertIn("3 controlado(s)", janela.resumo.text())

    def test_busca_por_nome_codigo_sem_controle_e_texto_literal(self):
        *_, livre = self.produtos()
        janela = self.janela()
        codigo = self.ctx.produtos.por_id(livre)["codigo"].lstrip("0")
        for busca in ("  agua  ", codigo):
            janela.busca.setText(busca)
            janela.busca.returnPressed.emit()
            self.assertEqual([p["id"] for p in janela.linhas], [livre])
        for busca in ("inexistente", "' OR 1=1 --", "%"):
            janela.busca.setText(busca)
            janela.btn_atualizar.click()
            self.assertEqual(janela.linhas, [])

    def test_filtro_de_grupo_e_busca_combinados(self):
        self.produtos()
        grupo = self.banco.inserir("grupos", {"nome": "BEBIDAS"})
        subgrupo = self.banco.inserir("subgrupos", {"nome": "REFRIGERANTES", "grupo_id": grupo})
        pid = self.novo_produto("SUCO", estoque=True, subgrupo_id=subgrupo)
        janela = self.janela()
        janela.grupo.setCurrentIndex(janela.grupo.findData("BEBIDAS"))
        janela.busca.setText("suco")
        janela.btn_atualizar.click()
        self.assertEqual([p["id"] for p in janela.linhas], [pid])
        self.assertEqual(janela.grupo.currentData(), "BEBIDAS")
        janela.busca.setText("coca")
        janela.busca.returnPressed.emit()
        self.assertEqual(janela.linhas, [])
        self.assertIn("4 controlado(s)", janela.resumo.text())  # Resumo geral, não filtrado.

    def test_saldo_negativo_sem_minimo_e_precisao_de_quatro_casas(self):
        pid = self.novo_produto("FRACIONADO", estoque=True, qt=-0.0001)
        janela = self.janela()
        self.assertEqual(janela.linhas[0]["situacao"], "sem")
        self.assertEqual(janela.grade.item(0, 4).text(), "-0,0001 UN")
        self.assertEqual(janela.grade.item(0, 6).text(), "0,0000")
        self.assertEqual(janela.grade.item(0, 8).text(), "R$ 0,00")
        self.banco.executar(
            "UPDATE produtos SET qt_atual = 1.2345, ult_preco_cent = 100 WHERE id = ?", (pid,))
        janela.btn_atualizar.click()
        self.assertEqual(janela.grade.item(0, 4).text(), "1,2345 UN")
        self.assertEqual(janela.grade.item(0, 8).text(), "R$ 1,23")

    def test_historico_real_mais_recente_primeiro_e_limite_fixo(self):
        pid = self.novo_produto("GELO", estoque=True)
        for _ in range(32):
            self.ctx.estoque.registrar_rapido(pid, "entrada", 0.1234)
        esperado = self.ctx.estoque.historico(pid, limite=30)
        janela = self.janela()
        janela.grade.selectRow(0)
        self.assertEqual(janela.movimentos, esperado)
        self.assertEqual(janela.historico.rowCount(), 30)
        self.assertEqual(janela.historico.item(0, 0).text(), fmt.fmt_datahora(esperado[0]["criado_em"]))
        self.assertEqual(janela.historico.item(0, 1).text(), "Entrada")
        self.assertEqual(janela.historico.item(0, 2).text(), "0,1234")
        self.assertEqual(janela.historico.item(0, 3).text(), "3,9488")
        self.assertIn("até 30 movimentos", janela.detalhe.text())
        janela.grade.clearSelection()
        self.assertEqual(janela.movimentos, [])
        self.assertEqual(janela.historico.rowCount(), 0)

    def test_produto_sem_movimentos_e_atualizacao_limpam_detalhes(self):
        pid = self.novo_produto("GELO", estoque=True)
        janela = self.janela()
        janela.grade.selectRow(0)
        self.assertIn("nenhum movimento", janela.detalhe.text())
        self.ctx.estoque.registrar_rapido(pid, "entrada", 2)
        janela.btn_atualizar.click()
        self.assertEqual(janela.linhas[0]["qt_atual"], 2)
        self.assertEqual(janela.historico.rowCount(), 0)
        janela.grade.selectRow(0)
        self.assertEqual(janela.historico.rowCount(), 1)
        janela.busca.setText("inexistente")
        janela.busca.returnPressed.emit()
        self.assertEqual(janela.movimentos, [])
        self.assertEqual(janela.historico.rowCount(), 0)

    def test_sem_operador_nao_abre(self):
        self.ctx.operador = None
        with self.assertRaises(ErroPermissao):
            self.janela()

    def test_nivel_modulo_e_operador_atual_sao_respeitados(self):
        self.banco.executar("UPDATE operadores SET nivel = 1 WHERE id = ?", (self.ctx.operador_id,))
        with self.assertRaises(ErroPermissao):
            self.janela()
        self.banco.executar("UPDATE acessos SET nivel = 1 WHERE modulo = 'lanc_estoque'")
        self.assertEqual(self.janela().grade.rowCount(), 0)
        self.banco.executar("UPDATE operadores SET nivel = 0 WHERE id = ?", (self.ctx.operador_id,))
        with self.assertRaises(ErroPermissao):
            self.janela()

    def test_operador_inativo_nao_abre(self):
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.ctx.operador_id,))
        with self.assertRaises(ErroPermissao):
            self.janela()

    def test_revogacao_de_acesso_limpa_dados_na_atualizacao(self):
        self.produtos()
        self.banco.executar("UPDATE operadores SET nivel = 2 WHERE id = ?", (self.ctx.operador_id,))
        janela = self.janela()
        self.banco.executar("UPDATE acessos SET nivel = 3 WHERE modulo = 'lanc_estoque'")
        self.assertFalse(janela.atualizar())
        self.assertEqual(janela.linhas, [])
        self.assertEqual(janela.grade.rowCount(), 0)
        self.assertEqual(janela.resumo.text(), "")
        self.assertIn("não permite", janela.mensagem.text())

    def test_desativacao_e_fim_de_sessao_bloqueiam_historico(self):
        self.produtos()
        janela = self.janela()
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.ctx.operador_id,))
        janela.grade.selectRow(0)
        self.assertEqual(janela.linhas, [])
        self.assertEqual(janela.movimentos, [])
        self.assertIn("inativo", janela.mensagem.text())
        self.ctx.operador = None
        self.assertFalse(janela.atualizar())
        self.assertIn("Entre", janela.mensagem.text())

    def test_erro_de_consulta_nao_mantem_dados_antigos(self):
        self.produtos()
        janela = self.janela()
        with patch.object(EstoqueController, "painel", side_effect=ErroNegocio("Consulta indisponível")):
            self.assertFalse(janela.atualizar())
        self.assertEqual(janela.grade.rowCount(), 0)
        self.assertEqual(janela.mensagem.text(), "Consulta indisponível")

    def test_erro_de_historico_limpa_dados_e_informa_limite_da_consulta(self):
        self.produtos()
        janela = self.janela()
        with patch.object(EstoqueController, "historico", side_effect=ErroNegocio("Histórico indisponível")) as historico:
            janela.grade.selectRow(0)
        historico.assert_called_once_with(janela.ctx.estoque.painel()[0]["id"], limite=30)
        self.assertEqual(janela.grade.rowCount(), 0)
        self.assertEqual(janela.historico.rowCount(), 0)
        self.assertEqual(janela.movimentos, [])
        self.assertEqual(janela.mensagem.text(), "Histórico indisponível")

    def test_movimentos_rapidos_entrada_saida_descarte_e_contagem(self):
        pid = self.novo_produto("GELO", estoque=True, qt=2)
        janela = self.janela()
        janela.grade.selectRow(0)
        self.assertTrue(janela.registrar("entrada", 1.2345))
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (pid,)), 3.2345)
        self.assertTrue(janela.registrar("saida", 0.5))
        self.assertTrue(janela.registrar("descarte", 0.25))
        self.assertTrue(janela.registrar("contagem", 4.125))
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (pid,)), 4.125)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM lancamentos_estoque"), 4)
        self.assertEqual(
            [m["tipo"] for m in self.ctx.estoque.historico(pid)],
            ["contagem", "descarte", "saida", "entrada"])
        self.assertEqual(janela.produto["id"], pid)
        self.assertEqual(janela.grade.item(0, 4).text(), "4,1250 UN")

    def test_produto_sem_controle_liga_estoque_com_entrada_e_bloqueia_retiradas(self):
        pid = self.novo_produto("AGUA")
        janela = self.janela()
        self.filtrar(janela, "livre")
        janela.grade.selectRow(0)
        self.assertTrue(janela.botoes["entrada"].isEnabled())
        self.assertTrue(janela.botoes["contagem"].isEnabled())
        self.assertFalse(janela.botoes["saida"].isEnabled())
        self.assertFalse(janela.botoes["descarte"].isEnabled())
        self.assertTrue(janela.registrar("entrada", 2))
        self.assertEqual(self.banco.valor(
            "SELECT qt_atual FROM produtos WHERE id = ?", (pid,)), 2)
        self.assertTrue(self.banco.valor(
            "SELECT controla_estoque FROM produtos WHERE id = ?", (pid,)))
        self.assertIsNone(janela.produto)
        self.assertEqual(janela.grade.rowCount(), 0)
        self.filtrar(janela, None)
        janela.grade.selectRow(0)
        self.assertEqual(janela.produto["situacao"], "normal")
        self.assertTrue(janela.botoes["saida"].isEnabled())

    def test_movimento_recusado_nao_grava_e_cancelar_dialogo_nao_altera_saldo(self):
        pid = self.novo_produto("GELO", estoque=True, qt=2)
        janela = self.janela()
        janela.grade.selectRow(0)
        self.assertFalse(janela.registrar("saida", 3))
        self.assertEqual(janela.mensagem.text(), "Só há 2,000 de 'GELO' em estoque; não dá para tirar 3,000.")
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (pid,)), 2)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM lancamentos_estoque"), 0)
        with patch.object(janela, "_pedir_quantidade", return_value=None):
            self.assertFalse(janela.registrar_dialogo("entrada"))
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (pid,)), 2)
        with patch.object(janela, "_pedir_quantidade", return_value=0.5):
            self.assertTrue(janela.registrar_dialogo("entrada"))
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (pid,)), 2.5)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM lancamentos_estoque"), 1)

    def test_dialogo_quantidade_valida_confirma_cancela_e_preve_saldo(self):
        from PySide6.QtWidgets import QDialog

        produto = {"nome": "GELO", "situacao": "normal", "qt_atual": 2, "unidade": "UN"}
        dialogo = _DialogoQuantidade(produto, "entrada")
        dialogo.entrada.setText("1,2345")
        self.assertEqual(dialogo.previa.text(), "Vai ficar com 3,2345 UN")
        dialogo.confirmar()
        self.assertEqual(dialogo.quantidade, 1.2345)
        with patch.object(dialogo, "exec", return_value=QDialog.DialogCode.Accepted):
            self.assertEqual(dialogo.executar(), 1.2345)
        self.assertIsNone(_DialogoQuantidade(produto, "saida")._quantidade())
        saida = _DialogoQuantidade(produto, "saida")
        saida.entrada.setText("0")
        saida.confirmar()
        self.assertIsNone(saida.quantidade)
        with patch.object(saida, "exec", return_value=QDialog.DialogCode.Rejected):
            self.assertIsNone(saida.executar())
        contagem = _DialogoQuantidade(produto, "contagem")
        contagem.entrada.setText("0")
        contagem.confirmar()
        self.assertEqual(contagem.quantidade, 0)

    def test_definir_minimo_confirma_cancela_e_rejeita_negativo(self):
        pid = self.novo_produto("GELO", estoque=True)
        janela = self.janela()
        janela.grade.selectRow(0)
        with patch.object(QInputDialog, "getText", return_value=("", False)):
            self.assertFalse(janela.definir_minimo())
        self.assertEqual(self.banco.valor("SELECT estoque_minimo FROM produtos WHERE id = ?", (pid,)), 0)
        with patch.object(QInputDialog, "getText", return_value=("-1", True)):
            self.assertFalse(janela.definir_minimo())
        self.assertEqual(self.banco.valor("SELECT estoque_minimo FROM produtos WHERE id = ?", (pid,)), 0)
        with patch.object(QInputDialog, "getText", return_value=("2,3456", True)):
            self.assertTrue(janela.definir_minimo())
        self.assertEqual(self.banco.valor("SELECT estoque_minimo FROM produtos WHERE id = ?", (pid,)), 2.3456)
        self.assertEqual(janela.grade.item(0, 5).text(), "2,3456")

    def test_revogacao_apos_dialogo_de_minimo_impede_gravacao(self):
        pid = self.novo_produto("GELO", estoque=True)
        self.banco.executar(
            "UPDATE operadores SET nivel = 2 WHERE id = ?", (self.ctx.operador_id,))
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        janela = self.janela()
        janela.grade.selectRow(0)

        def revogar(*_args, **_kwargs):
            self.banco.executar(
                "UPDATE acessos SET nivel = 3 WHERE modulo = 'lanc_estoque'")
            return "4", True

        with patch.object(QInputDialog, "getText", side_effect=revogar):
            self.assertFalse(janela.definir_minimo())
        self.assertEqual(
            self.banco.valor(
                "SELECT estoque_minimo FROM produtos WHERE id = ?", (pid,)), 0)

    def test_pedido_sugerido_confirma_com_fornecedor_e_cancelamento_nao_grava(self):
        self.produtos()
        fornecedor = self.banco.inserir("fornecedores", {"nome": "AMBEV"})
        janela = self.janela()
        saldo_antes = self.banco.valor("SELECT qt_atual FROM produtos WHERE nome = 'BRAHMA'")
        with patch.object(QInputDialog, "getItem", return_value=("AMBEV", False)):
            self.assertFalse(janela.gerar_pedido())
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM lancamentos_estoque"), 0)
        with patch.object(QInputDialog, "getItem", return_value=("AMBEV", True)):
            self.assertTrue(janela.gerar_pedido())
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM lancamentos_estoque"), 1)
        pedido = self.ctx.estoque.lancamentos("pedido")[0]
        self.assertEqual(pedido["fornecedor_id"], fornecedor)
        self.assertEqual(
            {item["nome"]: item["quantidade"] for item in self.ctx.estoque.itens(pedido["id"])},
            {"SKOL": 20, "BRAHMA": 5})
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE nome = 'BRAHMA'"), saldo_antes)
        self.assertIn("só muda quando a entrega for confirmada", janela.mensagem.text())
        self.assertEqual(janela._janela_lancamentos.lancamento_id, pedido["id"])
        janela._janela_lancamentos.close()

    def test_revogacao_apos_escolher_fornecedor_impede_criar_pedido(self):
        self.produtos()
        self.banco.inserir("fornecedores", {"nome": "AMBEV"})
        self.banco.executar(
            "UPDATE operadores SET nivel = 2 WHERE id = ?", (self.ctx.operador_id,))
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        janela = self.janela()

        def revogar(*_args, **_kwargs):
            self.banco.executar(
                "UPDATE acessos SET nivel = 3 WHERE modulo = 'lanc_estoque'")
            return "AMBEV", True

        with patch.object(QInputDialog, "getItem", side_effect=revogar):
            self.assertFalse(janela.gerar_pedido())
        self.assertEqual(
            self.banco.valor("SELECT COUNT(*) FROM lancamentos_estoque"), 0)
        self.assertEqual(janela._janela_lancamentos, None)

    def test_pedido_e_lista_de_compras_respeitam_sem_reposicao_ou_fornecedor(self):
        pid = self.novo_produto("GELO", estoque=True, qt=3)
        self.banco.executar("UPDATE produtos SET estoque_minimo = 1 WHERE id = ?", (pid,))
        janela = self.janela()
        self.assertFalse(janela.gerar_pedido())
        self.assertIn("Nenhum produto precisa", janela.mensagem.text())
        self.banco.executar("UPDATE produtos SET estoque_minimo = 4 WHERE id = ?", (pid,))
        with patch.object(self.ctx.cadastros, "opcoes", return_value=[]):
            self.assertFalse(janela.gerar_pedido())
        self.assertIn("Cadastre um fornecedor", janela.mensagem.text())
        self.banco.executar("UPDATE produtos SET estoque_minimo = 0 WHERE id = ?", (pid,))
        self.assertFalse(janela.lista_de_compras())
        self.assertIn("Nenhum produto precisa", janela.mensagem.text())

    def test_lista_de_compras_exibe_saldo_minimo_e_reposicao(self):
        pid = self.novo_produto("GELO", estoque=True, qt=3)
        self.banco.executar(
            "UPDATE produtos SET estoque_minimo = 4, ult_preco_cent = 275 WHERE id = ?", (pid,))
        janela = self.janela()
        with patch.object(QMessageBox, "information") as informar:
            self.assertTrue(janela.lista_de_compras())
        texto_lista = informar.call_args.args[2]
        self.assertIn("GELO", texto_lista)
        self.assertIn("3", texto_lista)
        self.assertIn("4", texto_lista)
        self.assertIn("5", texto_lista)
        self.assertIn(f"{'GELO':<32}{'3':>9}{'4':>9}{'5':>10}", texto_lista)
        self.assertEqual(janela.grade.item(0, 6).text(), "5,0000")
        self.assertEqual(janela.grade.item(0, 7).text(), "R$ 2,75")
        self.assertEqual(janela.grade.item(0, 8).text(), "R$ 8,25")
        self.assertEqual(self.ctx.estoque.resumo()["valor_cent"], 825)

    def test_edicao_e_cadastro_abrem_formulario_qt_com_id_selecionado(self):
        from PySide6.QtWidgets import QDialog

        pid = self.novo_produto("GELO", estoque=True)
        janela = self.janela()
        janela.grade.selectRow(0)
        with patch("src.ui_qt.cadastros.FormularioCadastro") as formulario:
            formulario.return_value.exec.return_value = QDialog.DialogCode.Accepted
            self.assertTrue(janela.editar_cadastro())
            self.assertEqual(formulario.call_args.args[:3], (self.ctx, "produtos", pid))
        with patch("src.ui_qt.cadastros.FormularioCadastro") as formulario:
            formulario.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.assertFalse(janela.cadastrar_produto())
            self.assertEqual(formulario.call_args.args[:3], (self.ctx, "produtos", None))

    def test_formulario_produto_revalida_permissao_antes_e_depois_do_dialogo(self):
        from PySide6.QtWidgets import QDialog

        pid = self.novo_produto("GELO", estoque=True)
        self.banco.executar(
            "UPDATE operadores SET nivel = 2 WHERE id = ?", (self.ctx.operador_id,))
        self.ctx.operador = self.ctx.acesso.operador(self.ctx.operador_id)
        janela = self.janela()
        janela.grade.selectRow(0)

        self.banco.executar(
            "UPDATE acessos SET nivel = 3 WHERE modulo = 'cad_produtos'")
        with patch("src.ui_qt.cadastros.FormularioCadastro") as formulario:
            self.assertFalse(janela.editar_cadastro())
            formulario.assert_not_called()

        self.banco.executar(
            "UPDATE acessos SET nivel = 2 WHERE modulo = 'cad_produtos'")
        def revogar_ao_fechar(*_args, **_kwargs):
            self.banco.executar(
                "UPDATE acessos SET nivel = 3 WHERE modulo = 'cad_produtos'")
            return QDialog.DialogCode.Accepted

        with patch("src.ui_qt.cadastros.FormularioCadastro") as formulario:
            formulario.return_value.exec.side_effect = revogar_ao_fechar
            self.assertFalse(janela.editar_cadastro())
            formulario.return_value.exec.assert_called_once()
        self.assertEqual(janela.produto["id"], pid)

    def test_revogacao_de_acesso_bloqueia_movimento_rapido_e_limpa_tela(self):
        pid = self.novo_produto("GELO", estoque=True, qt=2)
        self.banco.executar("UPDATE operadores SET nivel = 2 WHERE id = ?", (self.ctx.operador_id,))
        janela = self.janela()
        janela.grade.selectRow(0)
        self.banco.executar("UPDATE acessos SET nivel = 3 WHERE modulo = 'lanc_estoque'")
        self.assertFalse(janela.registrar("entrada", 1))
        self.assertEqual(self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (pid,)), 2)
        self.assertEqual(janela.linhas, [])
        self.assertEqual(janela.grade.rowCount(), 0)
        self.assertIn("não permite", janela.mensagem.text())

    def test_tela_funciona_em_banco_somente_leitura_sem_modificar_dados(self):
        sem, *_ = self.produtos()
        self.ctx.estoque.registrar_rapido(sem, "entrada", 2)
        antes = "\n".join(self.banco.conexao.iterdump())
        self.banco.executar("PRAGMA query_only = ON")
        janela = self.janela()
        for tabela in (janela.grade, janela.historico):
            self.assertEqual(tabela.editTriggers(), QAbstractItemView.EditTrigger.NoEditTriggers)
        self.assertEqual(
            [b.text() for b in janela.findChildren(QPushButton)],
            ["Gerar pedido do que falta", "Lista de compras",
             "Lançamentos de estoque",
             "Consultar / atualizar (F5)", "＋ Entrada", "－ Saída",
             "Perda / quebra", "Contei e ajustar", "Definir estoque mínimo",
             "Editar cadastro do produto", "Cadastrar produto", "Fechar"])
        for situacao in (None, "sem", "ponto", "normal", "livre"):
            self.filtrar(janela, situacao)
            if janela.grade.rowCount():
                janela.grade.selectRow(0)
        self.assertEqual("\n".join(self.banco.conexao.iterdump()), antes)
