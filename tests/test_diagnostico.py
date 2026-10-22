"""Diagnóstico central de equipamentos (controller e Qt) com banco em memória e saídas físicas simuladas.

Nenhum teste aqui fala com impressora, gaveta, balança ou leitor reais: tudo que enviaria comando é trocado por
dublês que falham se forem chamados sem querer. Isto valida regras e telas, não homologa equipamento.
"""
from __future__ import annotations

import gc
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from unittest.mock import patch

from src.controllers.cadastro_controller import CadastroController
from src.controllers.diagnostico_controller import DiagnosticoController, Resultado, gtin_valido
from src.core.erros import ErroNegocio, ErroPermissao
from src.hardware.dispositivos import Balanca, DispositivoIndisponivel, Gaveta
from src.hardware.impressora_termica import ErroImpressao
from src.controllers.contexto import Contexto
from tests.base import BaseTeste

EAN_VALIDO = "4006381333931"


def _proibido(*_a, **_k):
    raise AssertionError("equipamento acionado sem confirmação")


class BaseDiagnostico(BaseTeste):
    def setUp(self):
        super().setUp()
        self.adm = self.operador_adm()
        nivel = self.banco.valor("SELECT nivel FROM operadores WHERE id = ?", (self.adm,))
        self.outro = CadastroController(self.banco).salvar(
            "operadores", {"nome": "SUP", "senha": "1234", "nivel": str(nivel)})
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.adm)
        self.produto = self.novo_produto("GIN", 9000, estoque=True, qt=5, cbarra=EAN_VALIDO)
        self.hw = {}
        for nome, alvo in (("imprimir", (type(self.ctx.impressao), "imprimir_teste")),
                           ("pulso", (type(self.ctx.impressao), "abrir_gaveta")),
                           ("gaveta", (Gaveta, "abrir")), ("peso", (Balanca, "ler_peso")),
                           ("listar", ("src.hardware.impressoras_so", "listar_impressoras")),
                           ("spooler", ("src.hardware.impressoras_so", "servico_spooler_rodando")),
                           ("usb", ("src.hardware.impressoras_so", "listar_portas_usb"))):
            dono, metodo = alvo
            simulacao = patch(f"{dono}.{metodo}") if isinstance(dono, str) else patch.object(dono, metodo)
            self.hw[nome] = simulacao.start()
            self.hw[nome].side_effect = _proibido
            self.addCleanup(simulacao.stop)

    def nada_acionado(self):
        for nome, dubl in self.hw.items():
            self.assertFalse(dubl.called, nome)

    def eventos(self):
        return [r["evento"] for r in self.banco.todos(
            "SELECT evento FROM log_eventos WHERE evento LIKE 'diagnostico_%' ORDER BY id")]

    def revogar(self):
        self.banco.executar("UPDATE operadores SET nivel = 0 WHERE id = ?", (self.adm,))

    def ligar_impressora(self, gaveta=False):
        self.ctx.config.salvar_maquina({
            "modo_impressao": "termica", "impressora_termica_conexao": "arquivo",
            "impressora_termica_endereco": "nao_usado.bin",
            "impressora_termica_gaveta": "S" if gaveta else "N", "gaveta": "S" if gaveta else "N"})

    def contagens(self):
        return (self.banco.valor("SELECT COUNT(*) FROM vendas"),
                self.banco.valor("SELECT qt_atual FROM produtos WHERE id = ?", (self.produto,)))


class TesteDiagnosticoController(BaseDiagnostico):
    def setUp(self):
        super().setUp()
        self.diag = DiagnosticoController(self.ctx)

    def test_gtin(self):
        for codigo in (EAN_VALIDO, "73513537", "036000291452"):
            self.assertTrue(gtin_valido(codigo), codigo)
        for codigo in ("4006381333932", "123", "abcdefgh", ""):
            self.assertFalse(gtin_valido(codigo), codigo)

    def test_resumo_so_le_configuracao(self):
        self.ctx.config.salvar_maquina({"impressora_termica_conexao": "nenhuma", "balanca": "Nenhuma",
                                        "gaveta": "S", "impressora_termica_gaveta": "N"})
        resumo = self.diag.resumo()
        self.assertEqual(set(resumo), {"impressora", "gaveta", "balanca", "leitor"})
        self.assertEqual(resumo["impressora"].estado, "indisponivel")
        self.assertIn("chave", resumo["gaveta"].mensagem)
        self.assertEqual(resumo["balanca"].estado, "indisponivel")
        self.nada_acionado()
        self.assertEqual(self.eventos(), [])

    def test_resumo_avisa_modo_diferente_de_termica(self):
        self.ligar_impressora()
        self.ctx.config.salvar_maquina({"modo_impressao": "tela"})
        r = self.diag.resumo()["impressora"]
        self.assertEqual(r.estado, "configurado")
        self.assertIn("'tela'", r.mensagem)

    def test_impressora_indisponivel_nao_envia(self):
        self.ctx.config.salvar_maquina({"impressora_termica_conexao": "nenhuma"})
        r = self.diag.testar_impressora(self.adm)
        self.assertEqual(r.estado, "indisponivel")
        self.nada_acionado()
        self.assertEqual(self.eventos(), ["diagnostico_impressora_indisponivel"])

    def test_envio_nao_e_confirmacao(self):
        self.ligar_impressora()
        self.hw["imprimir"].side_effect = None
        r = self.diag.testar_impressora(self.adm)
        self.assertEqual(r.estado, "enviado")
        self.assertTrue(r.aguarda_conferencia)
        self.hw["imprimir"].assert_called_once_with()
        ok = self.diag.confirmar(r, True, self.adm)
        self.assertEqual(ok.estado, "confirmado")
        falha = self.diag.confirmar(r, False, self.adm)
        self.assertEqual(falha.estado, "nao_confirmado")
        self.assertEqual(self.eventos(), ["diagnostico_impressora_enviado", "diagnostico_impressora_confirmado",
                                          "diagnostico_impressora_nao_confirmado"])
        with self.assertRaises(ErroNegocio):
            self.diag.confirmar(ok, True, self.adm)

    def test_erros_reais_aparecem_e_vao_para_o_log(self):
        self.ligar_impressora()
        for erro in (ErroImpressao("Impressora offline"), OSError("Porta ocupada")):
            self.hw["imprimir"].side_effect = erro
            r = self.diag.testar_impressora(self.adm)
            self.assertEqual(r.estado, "erro")
            self.assertEqual(r.mensagem, str(erro))
        self.hw["imprimir"].side_effect = RuntimeError("driver quebrou")
        with patch("src.core.registro.registrar_excecao") as registrar:
            r = self.diag.testar_impressora(self.adm)
        self.assertEqual((r.estado, r.mensagem), ("erro", "driver quebrou"))
        registrar.assert_called_once()
        self.assertEqual(self.eventos(), ["diagnostico_impressora_erro"] * 3)
        detalhes = [l["detalhe"] for l in self.banco.todos("SELECT detalhe FROM log_eventos WHERE evento LIKE 'diagnostico_%'")]
        self.assertIn("Impressora offline", detalhes)

    def test_sessao_trocada_ou_revogada_nao_envia(self):
        self.ligar_impressora(gaveta=True)
        with self.assertRaises(ErroPermissao):
            self.diag.testar_gaveta(self.outro)
        self.revogar()
        for teste in (self.diag.testar_impressora, self.diag.testar_gaveta, self.diag.ler_balanca):
            with self.assertRaises(ErroPermissao):
                teste(self.adm)
        self.nada_acionado()
        self.assertEqual(self.eventos(), [])

    def test_gaveta(self):
        r = self.diag.testar_gaveta(self.adm)
        self.assertEqual(r.estado, "indisponivel")
        self.nada_acionado()
        self.ligar_impressora(gaveta=True)
        antes = self.contagens()
        self.hw["gaveta"].side_effect = None
        r = self.diag.testar_gaveta(self.adm)
        self.assertEqual(r.estado, "enviado")
        self.hw["gaveta"].assert_called_once_with()
        self.hw["gaveta"].side_effect = DispositivoIndisponivel("sem resposta")
        self.assertEqual(self.diag.testar_gaveta(self.adm).estado, "erro")
        self.assertEqual(antes, self.contagens())

    def test_balanca(self):
        self.assertEqual(self.diag.ler_balanca(self.adm).estado, "indisponivel")
        self.ctx.config.salvar_maquina({"balanca": "Toledo", "balanca_porta": "COM9"})
        with patch("importlib.util.find_spec", return_value=None):
            r = self.diag.ler_balanca(self.adm)
        self.assertEqual(r.estado, "indisponivel")
        self.assertIn("pyserial", r.mensagem)
        self.nada_acionado()
        antes = self.contagens()
        with patch("importlib.util.find_spec", return_value=object()):
            self.hw["peso"].side_effect = None
            self.hw["peso"].return_value = 1.25
            r = self.diag.ler_balanca(self.adm)
            self.assertEqual((r.estado, r.valor), ("lido", 1.25))
            self.assertIn("1.250 kg", r.mensagem)
            self.hw["peso"].side_effect = DispositivoIndisponivel("Balança não respondeu (timeout).")
            r = self.diag.ler_balanca(self.adm)
        self.assertEqual(r.estado, "erro")
        self.assertIn("timeout", r.mensagem)
        self.assertEqual(antes, self.contagens())
        self.assertIn("diagnostico_balanca_erro", self.eventos())

    def test_leitor_so_consulta_cadastro(self):
        antes = self.contagens()
        r = self.diag.avaliar_leitura(EAN_VALIDO)
        self.assertEqual((r.estado, r.valor), ("lido", EAN_VALIDO))
        self.assertIn("GIN", r.mensagem)
        self.assertIn("Dígito verificador correto", r.mensagem)
        self.assertIn("Nenhuma venda", r.mensagem)
        self.assertIn("NÃO confere", self.diag.avaliar_leitura("4006381333932").mensagem)
        self.assertIn("Nenhum produto", self.diag.avaliar_leitura("999").mensagem)
        self.assertIn("sufixo", self.diag.avaliar_leitura(EAN_VALIDO + "\t").mensagem)
        self.assertEqual(self.diag.avaliar_leitura("  ").estado, "erro")
        self.assertEqual(antes, self.contagens())
        self.nada_acionado()


class TesteDiagnosticoQt(BaseDiagnostico):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)

    def setUp(self):
        super().setUp()
        self.janelas = []
        self.addCleanup(self._fechar)
        self.perguntas = []
        simulacao = patch("PySide6.QtWidgets.QMessageBox.question", side_effect=_proibido)
        self.caixa_msg = simulacao.start()
        self.addCleanup(simulacao.stop)

    def _fechar(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def janela(self, respostas=()):
        from src.ui_qt.diagnostico import JanelaDiagnostico
        janela = JanelaDiagnostico(self.ctx)
        self.janelas.append(janela)
        fila = list(respostas)

        def perguntar(titulo, pergunta):
            self.perguntas.append(titulo)
            resposta = fila.pop(0)
            return resposta() if callable(resposta) else resposta
        janela._perguntar = perguntar
        return janela

    def test_abrir_nao_aciona_nada_e_sem_permissao_nao_abre(self):
        janela = self.janela()
        janela.show()
        self.aplicacao.processEvents()
        self.assertEqual(set(janela.resultados), {"impressora", "gaveta", "balanca", "leitor"})
        self.assertIn("Nenhum equipamento foi acionado", janela.mensagem.text())
        self.nada_acionado()
        self.caixa_msg.assert_not_called()
        self.assertEqual(self.eventos(), [])
        self.revogar()
        from src.ui_qt.diagnostico import JanelaDiagnostico
        with self.assertRaises(ErroPermissao):
            JanelaDiagnostico(self.ctx)

    def test_teste_exige_confirmacao_padrao_nao(self):
        self.ligar_impressora(gaveta=True)
        janela = self.janela([False, False])
        self.assertIsNone(janela.testar_impressora())
        self.assertIsNone(janela.testar_gaveta())
        self.assertIn("Nada foi enviado", janela.mensagem.text())
        self.nada_acionado()
        from PySide6.QtWidgets import QMessageBox
        from src.ui_qt.diagnostico import JanelaDiagnostico
        real = JanelaDiagnostico(self.ctx)
        self.janelas.append(real)
        self.caixa_msg.side_effect = None
        self.caixa_msg.return_value = QMessageBox.StandardButton.No
        self.assertIsNone(real.testar_gaveta())
        self.assertEqual(self.caixa_msg.call_args.args[4], QMessageBox.StandardButton.No)
        self.nada_acionado()

    def test_permissao_revalidada_depois_do_dialogo(self):
        self.ligar_impressora(gaveta=True)
        janela = self.janela([lambda: (self.revogar(), True)[1]])
        self.assertIsNone(janela.testar_gaveta())
        self.assertFalse(janela.btn_gaveta.isEnabled())
        self.assertFalse(janela.campo_leitor.isEnabled())
        self.nada_acionado()

    def test_troca_de_operador_durante_dialogo(self):
        self.ligar_impressora()
        trocar = lambda: (setattr(self.ctx, "operador", self.ctx.acesso.operador(self.outro)), True)[1]
        janela = self.janela([trocar])
        self.assertIsNone(janela.testar_impressora())
        self.assertIn("sessão mudou", janela.mensagem.text())
        self.nada_acionado()

    def test_envio_depois_conferencia_humana(self):
        self.ligar_impressora()
        self.hw["imprimir"].side_effect = None
        janela = self.janela([True, False])
        r = janela.testar_impressora()
        self.assertEqual(r.estado, "nao_confirmado")
        self.assertEqual(self.perguntas, ["Confirmar teste físico", "Conferir resultado"])
        self.assertIn("Não confirmado", janela.status["impressora"].text())
        self.assertEqual(self.eventos(), ["diagnostico_impressora_enviado", "diagnostico_impressora_nao_confirmado"])
        janela = self.janela([True, True])
        self.assertEqual(janela.testar_impressora().estado, "confirmado")

    def test_erro_real_aparece(self):
        self.ligar_impressora()
        self.hw["imprimir"].side_effect = ErroImpressao("Sem papel")
        janela = self.janela([True])
        self.assertEqual(janela.testar_impressora().estado, "erro")
        self.assertIn("Sem papel", janela.status["impressora"].text())
        self.assertIn("Sem papel", janela.mensagem.text())

    def test_verificar_impressora_nao_imprime(self):
        for nome, valor in (("listar", []), ("spooler", True), ("usb", [])):
            self.hw[nome].side_effect = None
            self.hw[nome].return_value = valor
        janela = self.janela()
        self.assertIsNotNone(janela.verificar_impressora())
        self.assertIn("Nada foi impresso", janela.mensagem.text())
        self.hw["imprimir"].assert_not_called()
        self.hw["listar"].side_effect = RuntimeError("PowerShell indisponível")
        self.assertIsNone(janela.verificar_impressora())
        self.assertIn("PowerShell indisponível", janela.mensagem.text())

    def test_leitor_enter_so_confere(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QPushButton
        janela = self.janela()
        janela.show()
        janela.activateWindow()
        self.aplicacao.processEvents()
        for botao in janela.findChildren(QPushButton):
            self.assertFalse(botao.autoDefault() or botao.isDefault(), botao.text())
        antes = self.contagens()
        QTest.keyClicks(janela.campo_leitor, EAN_VALIDO)
        QTest.keyClick(janela.campo_leitor, Qt.Key.Key_Return)
        self.assertEqual(janela.resultados["leitor"].estado, "lido")
        self.assertIn("GIN", janela.status["leitor"].text())
        self.assertEqual(self.perguntas, [])
        self.assertTrue(janela.isVisible())
        self.assertEqual(antes, self.contagens())
        self.nada_acionado()

    def test_teclado_tab_e_esc(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        janela = self.janela()
        janela.show()
        janela.activateWindow()
        self.aplicacao.processEvents()
        ordem = [janela.btn_verificar, janela.btn_impressora, janela.btn_gaveta, janela.btn_balanca,
                 janela.campo_leitor, janela.btn_leitor, janela.btn_atualizar, janela.btn_fechar]
        for anterior, proximo in zip(ordem, ordem[1:]):
            atual = anterior.nextInFocusChain()
            while atual not in ordem:
                atual = atual.nextInFocusChain()
            self.assertIs(atual, proximo)
        QTest.keyClick(janela, Qt.Key.Key_Escape)
        self.aplicacao.processEvents()
        self.assertFalse(janela.isVisible())
        self.nada_acionado()

    def _dentro(self, janela, widget):
        from PySide6.QtCore import QPoint, QRect
        canto = widget.mapTo(janela, QPoint(0, 0))
        return janela.rect().contains(QRect(canto, widget.size()))

    def test_cabe_em_notebook_e_com_fonte_maior(self):
        janela = self.janela()
        tela = janela.screen().availableGeometry()
        self.assertLessEqual(janela.width(), tela.width())
        self.assertLessEqual(janela.height(), tela.height())
        self.assertLessEqual(janela.minimumWidth(), 640)
        self.assertLessEqual(janela.minimumHeight(), 480)
        janela.show()
        for fator in (1.0, 1.5):
            fonte = janela.font()
            fonte.setPointSizeF(self.aplicacao.font().pointSizeF() * fator)
            janela.setFont(fonte)
            janela.resize(janela.minimumSize())
            self.aplicacao.processEvents()
            dica = janela.minimumSizeHint()
            self.assertLessEqual(dica.width(), 1093, fator)       # 1366x768 a 125%
            self.assertLessEqual(dica.height(), 614, fator)
            for widget in (janela.btn_fechar, janela.btn_atualizar, janela.mensagem, janela.rolagem):
                self.assertTrue(self._dentro(janela, widget), (fator, widget.objectName() or widget))
            if fator == 1.0:
                pagina = janela.rolagem.widget()
                self.assertLessEqual(pagina.minimumSizeHint().width(), janela.rolagem.viewport().width())
                for botao in (janela.btn_verificar, janela.btn_impressora, janela.btn_leitor):
                    canto = botao.mapTo(pagina, botao.rect().topRight())
                    self.assertLessEqual(canto.x(), pagina.width())
        self.nada_acionado()


class TesteResultado(BaseTeste):
    def test_rotulo_distingue_envio_de_confirmacao(self):
        enviado = Resultado("gaveta", "enviado", "x")
        self.assertIn("Comando enviado", enviado.rotulo)
        self.assertNotIn("Confirmado", enviado.rotulo)
        self.assertTrue(enviado.aguarda_conferencia)
        self.assertFalse(Resultado("gaveta", "confirmado", "x").aguarda_conferencia)