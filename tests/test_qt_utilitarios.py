"""Utilitários Qt: sessão revalidada, diálogos simulados e banco isolado."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
from unittest.mock import patch
from uuid import uuid4

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QInputDialog

from src.controllers.estoque_controller import EstoqueController
from src.controllers.utilitario_controller import UtilitarioController
from src.core.erros import ErroNegocio, ErroPermissao
from src.database import protecao
from src.controllers.contexto import Contexto
from src.ui_qt.utilitarios import JanelaUtilitarios, MODULOS_UTILITARIOS
from tests.test_caixa import BaseCaixa


class TestUtilitariosQt(BaseCaixa):
    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.pasta = Path(__file__).parent / f".qt-utilitarios-{uuid4().hex}"
        self.pasta.mkdir()
        self.addCleanup(shutil.rmtree, self.pasta)
        self.banco.cfg_set("pasta_backup", str(self.pasta / "Backup"))
        self.banco.cfg_set("pasta_backup_extra", "")
        self.banco.cfg_set("backup_externo_pasta", "")
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.adm)
        self.janelas = []
        self.addCleanup(self._fechar_janelas)

    def _fechar_janelas(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self):
        janela = JanelaUtilitarios(self.ctx)
        self.janelas.append(janela)
        return janela

    def test_contrato_menu_e_reabertura_revalidam_acesso(self):
        janela = self.janela()
        self.assertEqual(set(MODULOS_UTILITARIOS),
                         {acao[2] for acao in janela.ACOES})
        self.assertTrue(janela.exigir_acesso())
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.adm,))
        with self.assertRaisesRegex(ErroPermissao, "inativo"):
            janela.exigir_acesso()

    def test_data_vazia_de_limpeza_informa_erro_sem_apagar(self):
        janela = self.janela()
        with patch.object(QInputDialog, "getText", return_value=("", True)), \
                patch.object(UtilitarioController, "limpar_movimento") as limpar:
            self.assertFalse(janela.limpeza())
        limpar.assert_not_called()
        self.assertIn("data", janela.mensagem.text())

    def test_backup_real_copia_valida_sem_restauracao(self):
        janela = self.janela()
        with patch.object(protecao, "restaurar") as restaurar:
            self.assertTrue(janela.backup())
        restaurar.assert_not_called()
        caminho, = (self.pasta / "Backup").glob("*.db")
        self.assertTrue(protecao.backup_valido(caminho))
        with closing(sqlite3.connect(caminho)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM produtos").fetchone()[0], 2)
        self.assertIn(str(caminho), janela.status.text())
        self.assertIn("Backup local gerado", janela.status.text())
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos"), 2)

    def test_suporte_delega_e_explica_conteudo(self):
        janela = self.janela()
        with patch.object(UtilitarioController, "pacote_suporte", return_value="suporte.zip") as pacote:
            self.assertTrue(janela.suporte())
        pacote.assert_called_once_with()
        for trecho in ("suporte.zip", "log", "nunca as vendas"):
            self.assertIn(trecho, janela.status.text())

    def test_comunicacao_delega_ao_controller_sem_executar_programa(self):
        programa = self.pasta / "comunicacao.exe"
        programa.write_bytes(b"simulado")
        self.banco.cfg_set("programa_comunicacao", str(programa))
        janela = self.janela()
        with patch("src.controllers.utilitario_controller.subprocess.Popen") as abrir:
            self.assertTrue(janela.comunicacao())
        abrir.assert_called_once_with([str(programa)])
        self.assertIn("aberto", janela.status.text())

    def test_comunicacao_programa_ausente_e_falha_do_subprocesso(self):
        janela = self.janela()
        self.banco.cfg_set("programa_comunicacao", str(self.pasta / "ausente.exe"))
        with patch("src.controllers.utilitario_controller.subprocess.Popen") as abrir:
            self.assertFalse(janela.comunicacao())
        abrir.assert_not_called()
        self.assertIn("não encontrado", janela.mensagem.text())
        programa = self.pasta / "comunicacao.exe"
        programa.write_bytes(b"simulado")
        self.banco.cfg_set("programa_comunicacao", str(programa))
        with patch("src.controllers.utilitario_controller.subprocess.Popen",
                   side_effect=OSError("acesso negado")):
            self.assertFalse(janela.comunicacao())
        self.assertIn("Não foi possível abrir", janela.mensagem.text())

    def test_limpeza_cancelamento_data_vazia_invalida_e_confirmacao(self):
        janela = self.janela()
        respostas = (
            [("", False)], [("", True)], [("31/02/2026", True)],
            [("01/10/2026", True), ("APAGAR", False)],
            [("01/10/2026", True), ("SIM", True)],
        )
        for resposta in respostas:
            with self.subTest(resposta=resposta), \
                 patch.object(QInputDialog, "getText", side_effect=resposta), \
                 patch.object(UtilitarioController, "limpar_movimento") as limpar:
                self.assertFalse(janela.limpeza())
            limpar.assert_not_called()
        self.assertEqual(list(self.pasta.iterdir()), [])

    def test_limpeza_encaminha_data_iso_e_exibe_contagens(self):
        janela = self.janela()
        resultado = dict(vendas=3, turnos=2, movimentos_estoque=4, comissoes=1, backup="antes.db")
        with patch.object(QInputDialog, "getText",
                          side_effect=[("01/10/2026", True), (" apagar ", True)]) as pedir, \
             patch.object(UtilitarioController, "limpar_movimento", return_value=resultado) as limpar:
            self.assertTrue(janela.limpeza())
        limpar.assert_called_once_with("2026-10-01")
        self.assertEqual(pedir.call_args_list[0].args[-1], "01/10/2026")
        self.assertIn("dia anterior", pedir.call_args_list[0].args[2])
        for trecho in ("Vendas apagadas: 3", "Turnos apagados: 2",
                       "Movimentos de estoque: 4", "Comissões pagas ou canceladas: 1", "antes.db"):
            self.assertIn(trecho, janela.status.text())

    def test_limpeza_real_preserva_dia_limite_e_vendas_abertas(self):
        self.avancar(days=-10)
        antiga = self.vender((self.skol, 1))
        self.pagar(antiga, "Dinheiro", 800)
        self.caixa.fechar(antiga)
        aberta = self.vender((self.agua, 1), mesa=5)
        self.avancar(days=8)
        limite = self.vender((self.agua, 1))
        self.pagar(limite, "Dinheiro", 350)
        self.caixa.fechar(limite)
        self.avancar(days=2)
        janela = self.janela()
        with patch.object(QInputDialog, "getText",
                          side_effect=[("01/10/2026", True), ("APAGAR", True)]):
            self.assertTrue(janela.limpeza())
        self.assertIsNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (antiga,)))
        for vid in (aberta, limite):
            self.assertIsNotNone(self.banco.um("SELECT id FROM vendas WHERE id = ?", (vid,)))
        self.assertIn("Vendas apagadas: 1", janela.status.text())
        self.assertEqual(len(list((self.pasta / "Backup").glob("*.db"))), 1)

    def test_limpeza_datas_bloqueadas_pelo_controller(self):
        janela = self.janela()
        for data in ("03/10/2026", "04/10/2026"):
            with self.subTest(data=data), \
                 patch.object(QInputDialog, "getText", side_effect=[(data, True), ("APAGAR", True)]):
                self.assertFalse(janela.limpeza())
                self.assertTrue(janela.mensagem.text())
        self.assertEqual(list(self.pasta.iterdir()), [])

    def test_exclusao_real_resumo_backup_e_historico(self):
        venda = self.vender((self.skol, 1))
        self.pagar(venda, "Dinheiro", 800)
        self.caixa.fechar(venda)
        janela = self.janela()
        with patch.object(QInputDialog, "getText", return_value=(" apagar ", True)) as pedir:
            self.assertTrue(janela.excluir_produtos())
        mensagem = pedir.call_args.args[2]
        for trecho in ("Produtos cadastrados: 2", "Serão excluídos: 2", "backup",
                       "códigos ficarão livres", "histórico", "APAGAR"):
            self.assertIn(trecho, mensagem)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos"), 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM itens_venda"), 1)
        self.assertIn("Produtos excluídos: 2", janela.status.text())
        caminho, = (self.pasta / "Backup").glob("*.db")
        with closing(sqlite3.connect(caminho)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM produtos").fetchone()[0], 2)

    def test_exclusao_cancelada_ou_confirmacao_incorreta(self):
        janela = self.janela()
        for resposta in (("", False), ("APAGAR", False), ("SIM", True)):
            with self.subTest(resposta=resposta), \
                 patch.object(QInputDialog, "getText", return_value=resposta), \
                 patch.object(UtilitarioController, "excluir_todos_produtos") as excluir:
                self.assertFalse(janela.excluir_produtos())
            excluir.assert_not_called()
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos"), 2)

    def test_sem_produtos_e_vendas_abertas_bloqueiam_antes_do_dialogo(self):
        janela = self.janela()
        venda = self.vender((self.skol, 1), mesa=5)
        for status in ("aberta", "conta_enviada"):
            self.banco.executar("UPDATE vendas SET status = ? WHERE id = ?", (status, venda))
            with patch.object(QInputDialog, "getText") as pedir:
                self.assertFalse(janela.excluir_produtos())
            pedir.assert_not_called()
            self.assertIn("abertas", janela.mensagem.text())
        self.banco.executar("DELETE FROM vendas")
        self.banco.executar("DELETE FROM produtos")
        with patch.object(QInputDialog, "getText") as pedir:
            self.assertFalse(janela.excluir_produtos())
        pedir.assert_not_called()
        self.assertIn("Não há produtos", janela.mensagem.text())
        self.assertEqual(list(self.pasta.iterdir()), [])

    def test_venda_aberta_durante_dialogo_bloqueia_no_controller(self):
        janela = self.janela()

        def confirmar(*_):
            self.vender((self.skol, 1))
            return "APAGAR", True

        with patch.object(QInputDialog, "getText", side_effect=confirmar):
            self.assertFalse(janela.excluir_produtos())
        self.assertIn("abertas", janela.mensagem.text())
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos"), 2)
        self.assertEqual(list(self.pasta.iterdir()), [])

    def test_pedido_compra_bloqueia_exclusao_real(self):
        estoque = EstoqueController(self.banco, self.adm)
        fornecedor = self.banco.inserir("fornecedores", {"nome": "DISTRIBUIDORA"})
        pedido = estoque.criar_lancamento("pedido", fornecedor_id=fornecedor)
        estoque.adicionar_item(pedido, self.skol, 2)
        janela = self.janela()
        with patch.object(QInputDialog, "getText", return_value=("APAGAR", True)):
            self.assertFalse(janela.excluir_produtos())
        self.assertIn("pedidos de compra", janela.mensagem.text())
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos"), 2)

    def test_construcao_exige_sessao_ativa(self):
        self.ctx.operador = None
        with self.assertRaises(ErroPermissao):
            self.janela()
        self.ctx.operador = self.ctx.acesso.operador(self.adm)
        self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.adm,))
        with self.assertRaises(ErroPermissao):
            self.janela()

    def test_todas_acoes_revalidam_permissao_mesmo_com_botao_habilitado(self):
        janela = self.janela()
        self.banco.executar("UPDATE operadores SET nivel = 1 WHERE id = ?", (self.adm,))
        self.banco.executar("UPDATE acessos SET nivel = 4 WHERE modulo LIKE 'util_%'")
        metodos = ("backup", "pacote_suporte", "limpar_movimento",
                   "resumo_exclusao_produtos", "abrir_programa_comunicacao")
        for (acao, _, _), metodo in zip(janela.ACOES, metodos):
            with self.subTest(acao=acao), patch.object(UtilitarioController, metodo) as executar, \
                 patch.object(QInputDialog, "getText") as pedir:
                self.assertFalse(getattr(janela, acao)())
            executar.assert_not_called()
            pedir.assert_not_called()
            self.assertIn("nível de acesso", janela.mensagem.text())
        outra = self.janela()
        self.assertTrue(all(not b.isEnabled() for b in outra.botoes.values()))

    def test_revogacao_apos_cada_dialogo_impede_execucao(self):
        janela = self.janela()
        for acao, passo, metodo in (
            ("limpeza", 1, "limpar_movimento"), ("limpeza", 2, "limpar_movimento"),
            ("excluir_produtos", 1, "excluir_todos_produtos"),
        ):
            for revogacao in ("permissao", "inativo", "logout"):
                with self.subTest(acao=acao, passo=passo, revogacao=revogacao):
                    self.banco.executar("UPDATE operadores SET ativo = 1, nivel = 4 WHERE id = ?", (self.adm,))
                    self.ctx.operador = self.ctx.acesso.operador(self.adm)
                    chamadas = []

                    def responder(*_):
                        chamadas.append(1)
                        if len(chamadas) == passo:
                            if revogacao == "logout":
                                self.ctx.operador = None
                            elif revogacao == "inativo":
                                self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.adm,))
                            else:
                                self.banco.executar("UPDATE operadores SET nivel = 0 WHERE id = ?", (self.adm,))
                        return ("01/10/2026" if acao == "limpeza" and len(chamadas) == 1 else "APAGAR"), True

                    with patch.object(QInputDialog, "getText", side_effect=responder), \
                         patch.object(UtilitarioController, metodo) as executar:
                        self.assertFalse(getattr(janela, acao)())
                    executar.assert_not_called()
                    self.assertEqual(len(chamadas), passo)
                    self.assertTrue(janela.mensagem.text())
        self.assertEqual(list(self.pasta.iterdir()), [])

    def test_logout_e_inativacao_bloqueiam_todas_acoes(self):
        janela = self.janela()
        for estado in ("logout", "inativo"):
            self.ctx.operador = self.ctx.acesso.operador(self.adm)
            if estado == "logout":
                self.ctx.operador = None
            else:
                self.banco.executar("UPDATE operadores SET ativo = 0 WHERE id = ?", (self.adm,))
            for acao, _, _ in janela.ACOES:
                with self.subTest(estado=estado, acao=acao), \
                     patch.object(QInputDialog, "getText") as pedir:
                    self.assertFalse(getattr(janela, acao)())
                pedir.assert_not_called()
                self.assertTrue(janela.mensagem.text())
        self.assertEqual(list(self.pasta.iterdir()), [])
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos"), 2)

    def test_permissao_modulo_revogada_durante_dialogo(self):
        janela = self.janela()
        self.banco.executar("UPDATE operadores SET nivel = 1 WHERE id = ?", (self.adm,))
        self.banco.executar("UPDATE acessos SET nivel = 1 WHERE modulo = 'util_excluir_produtos'")

        def confirmar(*_):
            self.banco.executar("UPDATE acessos SET nivel = 4 WHERE modulo = 'util_excluir_produtos'")
            return "APAGAR", True

        with patch.object(QInputDialog, "getText", side_effect=confirmar), \
             patch.object(UtilitarioController, "excluir_todos_produtos") as excluir:
            self.assertFalse(janela.excluir_produtos())
        excluir.assert_not_called()
        self.assertIn("nível de acesso", janela.mensagem.text())

    def test_falha_do_resumo_e_backup_nao_apagam_dados(self):
        janela = self.janela()
        with patch.object(UtilitarioController, "resumo_exclusao_produtos",
                          side_effect=sqlite3.OperationalError("resumo indisponível")), \
             patch.object(QInputDialog, "getText") as pedir:
            self.assertFalse(janela.excluir_produtos())
        pedir.assert_not_called()
        self.assertIn("resumo indisponível", janela.mensagem.text())
        for acao, respostas in (
            ("excluir_produtos", [("APAGAR", True)]),
            ("limpeza", [("01/10/2026", True), ("APAGAR", True)]),
        ):
            with self.subTest(acao=acao), \
                 patch.object(QInputDialog, "getText", side_effect=respostas), \
                 patch.object(UtilitarioController, "backup", side_effect=OSError("disco cheio")):
                self.assertFalse(getattr(janela, acao)())
            self.assertIn("disco cheio", janela.mensagem.text())
            self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM produtos"), 2)
            self.assertIn("Nenhuma operação", janela.status.text())

    def test_erros_explicitos_sem_anunciar_sucesso(self):
        janela = self.janela()
        for acao, metodo in (
            ("backup", "backup"), ("suporte", "pacote_suporte"),
            ("comunicacao", "abrir_programa_comunicacao"),
            ("limpeza", "limpar_movimento"), ("excluir_produtos", "excluir_todos_produtos"),
        ):
            for erro in (ErroNegocio("bloqueado"), OSError("sem acesso"),
                         sqlite3.OperationalError("ocupado"), ValueError("inválido")):
                with self.subTest(acao=acao, erro=erro):
                    respostas = ([("01/10/2026", True), ("APAGAR", True)]
                                 if acao == "limpeza" else [("APAGAR", True)])
                    with patch.object(QInputDialog, "getText", side_effect=respostas), \
                         patch.object(UtilitarioController, metodo, side_effect=erro):
                        self.assertFalse(getattr(janela, acao)())
                    self.assertEqual(janela.mensagem.text(), str(erro))
                    self.assertIn("Nenhuma operação", janela.status.text())
