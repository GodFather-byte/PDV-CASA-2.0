"""Shows de quartos: origem persistente, acerto único e apresentação sem duplicar valores."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.controllers.comissao_controller import ComissaoController
from src.controllers.contexto import Contexto
from src.controllers.quartos_controller import QuartosController
from src.database.conexao import BancoDados
from src.database.esquema import VERSAO_ESQUEMA
from src.core.erros import ErroNegocio
from tests.test_comissao_garotas import BaseComissao


class BaseShows(BaseComissao):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("usar_quartos", "S")
        self.garota(180, "ANA")
        self.garota(181, "BIA")
        self.q = QuartosController(self.banco, self.adm)

    def iniciar(self, blocos=1):
        return self.q.iniciar(3, blocos, codigo_profissional="180")

    def pagar(self, valor=5000, **kw):
        return self.com.pagar(180, self.turno, self.adm,
                              shows=self.com.quantidade_shows_quartos(180), valor_show_cent=valor, **kw)


class TestShowsQuartos(BaseShows):
    def test_inicio_acrescimo_liberacao_e_relogio_nao_duplicam(self):
        self.iniciar(2)
        self.assertEqual(self.com.quantidade_shows_quartos(180), 2)
        self.q.adicionar_tempo(3, 1)
        self.q.situacao()
        self.avancar(hours=4)
        self.q.situacao()
        self.q.liberar(3)
        self.assertEqual(self.com.quantidade_shows_quartos(180), 3)
        self.assertEqual(self.com.quantidade_shows_quartos(181), 0)
        self.assertEqual(self.com.pendentes_por_garota()[0]["shows_quartos"], 3)

    def test_meia_hora_real_em_blocos_configurados_e_fracoes(self):
        self.banco.cfg_set("quartos_minutos_bloco", "15")
        self.iniciar(1)
        self.assertEqual(self.com.quantidade_shows_quartos(180), 0)
        self.q.adicionar_tempo(3, 1)
        self.assertEqual(self.com.quantidade_shows_quartos(180), 1)
        self.banco.cfg_set("quartos_minutos_bloco", "60")
        self.q.adicionar_tempo(3, 2)  # usa os 15 min congelados no início, não a configuração nova
        self.assertEqual(self.com.quantidade_shows_quartos(180), 2)

    def test_acerto_comissao_shows_vale_pix_recibo_e_fechamento(self):
        from src.controllers.impressao_controller import ImpressaoController
        self.iniciar(2)
        self.lancar(180, 25)
        p = self.pagar(6000, pix_cent=5000, vale_cent=1000)
        self.assertEqual((p["shows"], p["shows_cent"], p["comissao_cent"], p["total_cent"]),
                         (2, 12000, 2500, 14500))
        self.assertEqual(p["dinheiro_cent"], 8500)
        self.assertEqual(self.com.quantidade_shows_quartos(180), 0)
        self.assertEqual(self.com.shows_do_turno(self.turno)["quantidade"], 2)
        self.assertIn("120,00", ImpressaoController(self.banco).recibo_comissao(p, "ADM"))
        antes = self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa")
        with self.assertRaises(ErroNegocio):
            self.com.pagar(180, self.turno, self.adm)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), antes)

    def test_acerto_somente_shows_e_acrescimo_apos_pagamento(self):
        self.iniciar()
        self.assertEqual(self.pagar()["total_cent"], 5000)
        self.q.adicionar_tempo(3, 2)
        self.assertEqual(self.com.quantidade_shows_quartos(180), 2)
        self.assertEqual(self.pagar(6000)["total_cent"], 12000)
        self.assertEqual(self.com.shows_do_turno(self.turno)["quantidade"], 3)

    def test_falha_do_registro_reverte_inicio_e_acrescimo(self):
        inserir = self.banco.inserir
        def falhar(tabela, valores):
            if tabela == "shows_quartos":
                raise RuntimeError("falha simulada")
            return inserir(tabela, valores)
        with patch.object(self.banco, "inserir", side_effect=falhar):
            with self.assertRaises(RuntimeError):
                self.iniciar()
        self.assertIsNone(self.q._ativo(3))
        self.iniciar()
        with patch.object(self.banco, "inserir", side_effect=falhar):
            with self.assertRaises(RuntimeError):
                self.q.adicionar_tempo(3, 1)
        self.assertEqual(self.q._ativo(3)["blocos"], 1)
        self.assertEqual(self.com.quantidade_shows_quartos(180), 1)

    def test_acerto_invalido_e_tela_desatualizada_preservam_pendencias(self):
        self.iniciar()
        ids = [s["id"] for s in self.com.shows_quartos_pendentes(180)]
        self.q.adicionar_tempo(3, 1)
        with self.assertRaisesRegex(ErroNegocio, "mudaram"):
            self.pagar(shows_quartos_ids=ids)
        with self.assertRaises(ErroNegocio):
            self.pagar(pix_cent=999999)
        with self.assertRaises(ErroNegocio):
            self.com.pagar(180, self.turno, self.adm, shows=1, valor_show_cent=5000)
        self.assertEqual(self.com.quantidade_shows_quartos(180), 2)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM acertos_garotas"), 0)

    def test_repetir_mesmo_acerto_com_ids_nao_paga_duas_vezes(self):
        self.iniciar()
        ids = [s["id"] for s in self.com.shows_quartos_pendentes(180)]
        self.pagar(shows_quartos_ids=ids)
        with self.assertRaisesRegex(ErroNegocio, "mudaram"):
            self.com.pagar(180, self.turno, self.adm, shows=1, valor_show_cent=5000, shows_quartos_ids=ids)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM acertos_garotas"), 1)

    def test_limpar_acerto_antigo_nao_reabre_shows_pagos(self):
        self.iniciar()
        self.pagar()
        self.banco.executar("DELETE FROM acertos_garotas")
        self.assertEqual(self.com.quantidade_shows_quartos(180), 0)

    def test_duas_conexoes_nao_pagam_os_mesmos_shows(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        import sqlite3
        self.iniciar()
        ids = [s["id"] for s in self.com.shows_quartos_pendentes(180)]
        with tempfile.TemporaryDirectory() as pasta:
            caminho = str(Path(pasta) / "loja.db")
            destino = sqlite3.connect(caminho)
            self.banco.conexao.backup(destino)
            destino.close()
            barreira = Barrier(2)
            def pagar():
                b = BancoDados(caminho)
                try:
                    barreira.wait(timeout=10)
                    ComissaoController(b).pagar(180, self.turno, self.adm, shows=1, valor_show_cent=5000,
                                               shows_quartos_ids=ids)
                    return "pago"
                except ErroNegocio:
                    return "recusado"
                finally:
                    b.fechar()
            with ThreadPoolExecutor(max_workers=2) as executor:
                resultados = list(executor.map(lambda _: pagar(), range(2)))
            self.assertEqual(sorted(resultados), ["pago", "recusado"])
            b = BancoDados(caminho)
            try:
                self.assertEqual(b.valor("SELECT COUNT(*) FROM acertos_garotas"), 1)
                self.assertEqual(b.valor("SELECT SUM(valor_cent) FROM movimentos_caixa"), 5000)
            finally:
                b.fechar()

    def test_falha_de_acerto_reverte_movimento_e_consumo_dos_shows(self):
        self.iniciar()
        with patch.object(self.banco, "log", side_effect=RuntimeError("falha simulada")):
            with self.assertRaises(RuntimeError):
                self.pagar()
        self.assertEqual(self.com.quantidade_shows_quartos(180), 1)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM acertos_garotas"), 0)
        self.assertEqual(self.banco.valor("SELECT COUNT(*) FROM movimentos_caixa"), 0)

    def test_reabrir_banco_preserva_pendentes_e_consumidos(self):
        self.iniciar(2)
        with tempfile.TemporaryDirectory() as pasta:
            caminho = str(Path(pasta) / "loja.db")
            import sqlite3
            destino = sqlite3.connect(caminho)
            self.banco.conexao.backup(destino)
            destino.close()
            b = BancoDados(caminho)
            c = ComissaoController(b)
            self.assertEqual(c.quantidade_shows_quartos(180), 2)
            c.pagar(180, self.turno, self.adm, shows=2, valor_show_cent=5000)
            b.fechar()
            b = BancoDados(caminho)
            try:
                self.assertEqual(ComissaoController(b).quantidade_shows_quartos(180), 0)
            finally:
                b.fechar()

    def test_migracao_nao_gera_shows_retroativos(self):
        self.iniciar(2)
        with tempfile.TemporaryDirectory() as pasta:
            caminho = str(Path(pasta) / "antigo.db")
            import sqlite3
            destino = sqlite3.connect(caminho)
            self.banco.conexao.backup(destino)
            destino.execute("DROP TABLE shows_quartos")
            destino.execute("PRAGMA user_version=35")
            destino.commit()
            destino.close()
            b = BancoDados(caminho)
            try:
                self.assertEqual(b.valor("PRAGMA user_version"), VERSAO_ESQUEMA)
                self.assertEqual(b.valor("SELECT blocos FROM quartos_uso"), 2)
                self.assertEqual(ComissaoController(b).quantidade_shows_quartos(180), 0)
                QuartosController(b, self.adm).adicionar_tempo(3, 1)
                self.assertEqual(ComissaoController(b).quantidade_shows_quartos(180), 1)
            finally:
                b.fechar()


class TestShowsQuartosQt(BaseShows):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from PySide6.QtCore import QCoreApplication, QEvent
        # Destrói widgets e timers antes de fechar o SQLite dos testes.
        self.addCleanup(lambda: QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete))

    def test_acerto_preenche_quantidade_e_pede_apenas_tarifa(self):
        from src.ui_qt.comissao import DialogoAcerto
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QPushButton
        self.iniciar(2)
        self.banco.cfg_set("comissao_pede_shows", "N")
        ctx = Contexto(self.banco)
        ctx.operador = ctx.acesso.operador(self.adm)
        for valor in (5000, 6000):
            with self.subTest(valor=valor):
                d = DialogoAcerto(None, ctx, 180, "ANA", 2500, 1)
                self.addCleanup(d.deleteLater)
                d.show()
                self.app.processEvents()
                pagar = next(b for b in d.findChildren(QPushButton) if b.text() == "Pagar")
                pos = pagar.mapTo(d, QPoint(0, 0))
                self.assertLessEqual(d.height(), 650)
                self.assertLessEqual(pos.y() + pagar.height(), d.height())
                self.assertTrue(d.ent_qtd.isReadOnly())
                self.assertEqual(d.ent_qtd.text(), "2")
                d.confirmar()
                self.assertIsNone(d.resultado)
                d.grupo_show.button(valor).click()
                self.assertEqual(d.lbl_total.text(), "R$ 125,00" if valor == 5000 else "R$ 145,00")
                d.confirmar()
                self.assertEqual(d.resultado["shows"], 2)
                self.assertEqual(len(d.resultado["shows_quartos_ids"]), 1)

    def test_tempo_exige_profissional_valida_para_vincular_shows(self):
        from src.ui_qt.quartos import DialogoTempo
        from PySide6.QtWidgets import QDialog
        d = DialogoTempo(self.q, "Iniciar quarto 3")
        self.addCleanup(d.deleteLater)
        d.tempo.setCurrentIndex(1)
        for codigo in ("", "abc", "999"):
            d.profissional.setText(codigo)
            d.accept()
            self.assertEqual(d.result(), QDialog.DialogCode.Rejected)
            self.assertIn("profissional cadastrada", d.mensagem.text())
        d.profissional.setText("180")
        d.accept()
        self.assertEqual(d.result(), QDialog.DialogCode.Accepted)

    def test_comanda_so_com_shows_tem_cartao_aviso_e_acerto(self):
        from src.ui_qt.caixa import JanelaCaixa
        from src.ui_qt.painel_mesas import detalhes
        self.iniciar(2)
        self.banco.cfg_set("num_comandas", "300")
        ctx = Contexto(self.banco)
        ctx.operador = ctx.acesso.operador(self.adm)
        j = JanelaCaixa(ctx)
        self.addCleanup(j.deleteLater)
        j.ent_pos.setText("180")
        j.chamar_posicao()
        self.assertTrue(j._a_pagar_na_comanda())
        self.assertIn("2 show(s)", j.lbl_aviso_venda.text())
        self.assertIn("2 shows", detalhes({"tipo": "garota", "shows_quartos": 2})[0])
        self.assertIn("2 show(s)", j._avisos_turno())

    def test_acerto_pela_tela_paga_shows_uma_vez_e_zera_quantidade(self):
        from src.ui_qt.caixa import JanelaCaixa
        from src.ui_qt.comissao import DialogoAcerto
        from src.ui_qt import quartos as tela_quartos
        self.iniciar(2)
        self.lancar(180, 25)
        ctx = Contexto(self.banco)
        ctx.operador = ctx.acesso.operador(self.adm)
        j = JanelaCaixa(ctx)
        self.addCleanup(j.deleteLater)
        d = DialogoAcerto(j, ctx, 180, "ANA", 2500, 1, True)
        self.addCleanup(d.deleteLater)
        d.grupo_show.button(5000).click()
        d.confirmar()
        with patch.object(j, "_autorizar", return_value=True), patch.object(j, "_emitir"), \
             patch.object(j, "_dialogo_acerto", return_value=d.resultado):
            j.pagar_comissao(180)
        self.assertEqual(self.banco.valor("SELECT total_cent FROM acertos_garotas"), 12500)
        self.assertEqual(self.com.quantidade_shows_quartos(180), 0)
        novo = DialogoAcerto(j, ctx, 180, "ANA", 0, 0)
        self.addCleanup(novo.deleteLater)
        self.assertTrue(novo.ent_qtd.isReadOnly())
        self.assertEqual(novo.ent_qtd.text(), "0")
        # Acréscimo vindo do painel atualiza a comanda visível imediatamente.
        self.banco.cfg_set("num_comandas", "300")
        j.ent_pos.setText("180")
        j.chamar_posicao()
        with patch.object(tela_quartos, "pedir_mais_tempo", return_value=lambda: self.q.adicionar_tempo(3, 1)):
            j.painel_quartos.pedir(lambda ctrl: tela_quartos.pedir_mais_tempo(None, ctrl, {}), 3)
        self.assertIn("1 show(s)", j.lbl_aviso_venda.text())
