"""Recepção do hotel (Qt): abre só com o módulo ligado, reserva pela tela, check-in com acompanhante, check-out que
abre a conta no caixa, governança, cadastro de tarifas, exportação das fichas e nenhuma aba cortada em 1366x768."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QCoreApplication, QDate, QEvent, QRect
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox

from src.controllers.contexto import Contexto
from src.controllers.perfil_controller import PerfilController
from src.core.erros import ErroPermissao
from src.ui_qt import tema
from src.ui_qt.hotel import DialogoCheckin, DialogoCheckout, DialogoHospede, DialogoReserva, JanelaHotel
from tests.base import BaseTeste
from tools import conferir_telas


class BaseHotelQt(BaseTeste):
    agora = datetime(2026, 11, 23, 15, 0, 0)

    @classmethod
    def setUpClass(cls):
        cls.aplicacao = QApplication.instance() or QApplication([])
        cls.aplicacao.setQuitOnLastWindowClosed(False)
        anterior = cls.aplicacao.styleSheet()
        cls.addClassCleanup(cls.aplicacao.setStyleSheet, anterior)
        tema.aplicar(cls.aplicacao)

    def setUp(self):
        super().setUp()
        PerfilController(self.banco).aplicar("hotel")
        for chave, valor in (("usar_hotel", "S"), ("limite_comanda", "0"), ("num_comandas", "999")):
            self.banco.cfg_set(chave, valor)
        self.ctx = Contexto(self.banco)
        self.ctx.operador = self.ctx.acesso.operador(self.operador_adm())
        h = self.h = self.ctx.hotel
        self.tipo_std = h.salvar_tipo("Standard casal", 2, 15000)
        self.tipo_fam = h.salvar_tipo("Família", 4, 25000, cafe_incluso=False)
        self.q101 = h.salvar_uh("101", self.tipo_std)
        self.q102 = h.salvar_uh("102", self.tipo_std)
        self.q201 = h.salvar_uh("201", self.tipo_fam)
        self.periodo = h.salvar_periodo("2 horas", 120, 6000)
        h.definir_preco_extra("cafe", 2500)
        self.maria = h.salvar_hospede({"nome": "Maria da Silva", "cpf": "529.982.247-25", "documento": "123",
                                       "nascimento": "10/05/1985", "telefone": "(11) 98888-7777"})
        self.joao = h.salvar_hospede({"nome": "Joao da Silva", "documento": "999", "nascimento": "01/01/2015"})
        self.ctx.turnos.abrir(self.ctx.operador_id, 1, 0)
        self.janelas = []
        self.addCleanup(self._fechar)
        area = mock.patch.object(tema, "_area_util", return_value=QRect(0, 0, 1366, 728))
        area.start()
        self.addCleanup(area.stop)

    def _fechar(self):
        for janela in self.janelas:
            janela.close()
            janela.deleteLater()
        self.aplicacao.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def mostrar(self, janela):
        self.janelas.append(janela)
        janela.show()
        tema.ajustar_na_primeira_exibicao(janela)
        for _ in range(3):
            self.aplicacao.processEvents()
        return janela

    def recepcao(self):
        return self.mostrar(JanelaHotel(self.ctx))

    def linha_de(self, tabela, texto):
        for i in range(tabela.rowCount()):
            if any(tabela.item(i, j) and texto in tabela.item(i, j).text() for j in range(tabela.columnCount())):
                tabela.setCurrentCell(i, 0)
                return i
        self.fail(f"{texto} não está na tabela")


class TesteRecepcao(BaseHotelQt):
    def test_so_abre_com_o_modulo_ligado(self):
        self.banco.cfg_set("usar_hotel", "N")
        with self.assertRaises(ErroPermissao):
            JanelaHotel(self.ctx)

    def test_nenhuma_aba_nem_dialogo_cortado_no_notebook(self):
        r = self.h.reservar(self.q101, "Maria", "2026-11-23", "2026-11-25", hospede_id=self.maria)
        self.h.checkin(r)
        self.h.reservar(self.q102, "Carlos Souza", "2026-11-23", "2026-11-24", telefone="11 97777-6666")
        janela = self.recepcao()
        for i in range(janela.abas.count()):
            with self.subTest(aba=janela.abas.tabText(i)):
                janela.abas.setCurrentIndex(i)
                self.aplicacao.processEvents()
                self.assertEqual(conferir_telas.problemas(janela), [])
        self.assertLessEqual(janela.width(), 1366 - tema.RESERVA_LARGURA)
        for dialogo in (DialogoReserva(self.ctx), DialogoReserva(self.ctx, agora=True), DialogoCheckout(self.ctx, r),
                        DialogoCheckin(self.ctx, self.h.estadias(("reservada",))[0]["id"]),
                        DialogoHospede(self.ctx, self.maria)):
            with self.subTest(dialogo=type(dialogo).__name__):
                self.assertEqual(conferir_telas.problemas(self.mostrar(dialogo)), [])

    def test_reserva_pela_tela_mostra_o_valor_e_so_quartos_livres(self):
        self.h.reservar(self.q101, "Outra pessoa", "2026-11-24", "2026-11-26")
        dialogo = self.mostrar(DialogoReserva(self.ctx, entrada="2026-11-24"))
        dialogo.saida.setDate(QDate(2026, 11, 27))
        dialogo.adultos.setValue(2)
        numeros = [dialogo.uh.itemText(i)[:3] for i in range(dialogo.uh.count())]
        self.assertEqual(numeros, ["102", "201"])
        self.assertIn("3 diária(s) × R$ 150,00 = R$ 450,00", dialogo.valor.text())
        dialogo.seletor.escolher(self.maria)
        self.assertEqual((dialogo.nome.text(), dialogo.telefone.text()), ("Maria da Silva", "(11) 98888-7777"))
        dialogo.origem.setCurrentIndex(dialogo.origem.findData("whatsapp"))
        dialogo.confirmar()
        e = self.h.estadia(dialogo.estadia_id)
        self.assertEqual((e["uh"], e["noites"], e["adultos"], e["origem"], e["hospede_id"]),
                         ("102", 3, 2, "whatsapp", self.maria))

    def test_reserva_por_periodo_esconde_as_diarias(self):
        dialogo = self.mostrar(DialogoReserva(self.ctx))
        dialogo.modalidade.setCurrentIndex(1)
        self.assertFalse(dialogo.saida.isVisible() or dialogo.cafe.isVisible())
        self.assertTrue(dialogo.linha_periodo.isVisible())
        self.assertIn("Período 2 horas: R$ 60,00", dialogo.valor.text())

    def test_checkin_com_menor_pede_responsavel_e_mostra_a_conta(self):
        r = self.h.reservar(self.q201, "Maria", "2026-11-23", "2026-11-24", hospede_id=self.maria, criancas=1)
        dialogo = self.mostrar(DialogoCheckin(self.ctx, r))
        self.assertEqual(dialogo.titular.hospede_id(), self.maria)
        dialogo.titular.escolher(self.joao)
        dialogo.incluir_acompanhante()
        dialogo.titular.escolher(self.maria)
        dialogo.confirmar()
        self.assertIn("menor de idade", dialogo.mensagem.text())
        dialogo.acompanhantes.item(0, 2).setText("mãe, Maria da Silva")
        dialogo.motivo.setCurrentText("Lazer ou férias")
        dialogo.confirmar()
        self.assertEqual(dialogo.result(), QDialog.DialogCode.Accepted)
        e = self.h.estadia(r)
        self.assertEqual((e["situacao"], e["conta"], e["motivo_viagem"]), ("hospedada", 500, "Lazer ou férias"))
        self.assertEqual(e["acompanhantes"][0]["responsavel"], "mãe, Maria da Silva")

    def test_checkin_em_quarto_sujo_pergunta_antes(self):
        r = self.h.reservar(self.q101, "Maria", "2026-11-23", "2026-11-24", hospede_id=self.maria)
        self.h.marcar_limpeza(self.q101, "sujo")
        dialogo = self.mostrar(DialogoCheckin(self.ctx, r))
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as pergunta:
            dialogo.confirmar()
        pergunta.assert_called_once()
        self.assertEqual(self.h.estadia(r)["situacao"], "reservada")
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialogo.confirmar()
        self.assertEqual(self.h.estadia(r)["situacao"], "hospedada")

    def test_hoje_lista_chegadas_e_hospedados_e_o_checkout_abre_a_conta_no_caixa(self):
        r = self.h.reservar(self.q101, "Maria", "2026-11-23", "2026-11-24", hospede_id=self.maria)
        janela = self.recepcao()
        self.assertEqual(janela.tab_chegadas.rowCount(), 1)
        with mock.patch.object(DialogoCheckin, "exec", lambda d: (d.confirmar(), d.result())[1]):
            janela.fazer_checkin()
        self.assertIn("conta 500", janela.mensagem.text())
        self.assertEqual((janela.tab_chegadas.rowCount(), janela.tab_hospedados.rowCount()), (0, 1))
        self.avancar(hours=20)                                            # 24/11 11:00
        janela.atualizar()
        self.linha_de(janela.tab_hospedados, "Maria")
        caixa = mock.Mock()
        janela.app = mock.Mock(abrir_caixa=mock.Mock(return_value=caixa))
        with mock.patch.object(DialogoCheckout, "exec", lambda d: (d.confirmar(), d.result())[1]), \
                mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            janela.fazer_checkout()
        self.assertIn("falta receber R$ 150,00", janela.mensagem.text())
        caixa.ent_pos.setText.assert_called_once_with("500")
        caixa.chamar_posicao.assert_called_once()
        self.assertEqual(self.h.estadia(r)["situacao"], "encerrada")

    def test_periodo_estourado_pinta_a_linha(self):
        r = self.h.reservar(self.q102, "Maria", "2026-11-23 15:00", modalidade="periodo", periodo_id=self.periodo,
                            hospede_id=self.maria)
        self.h.checkin(r)
        self.avancar(hours=2, minutes=30)
        janela = self.recepcao()
        linha = self.linha_de(janela.tab_hospedados, "Maria")
        self.assertIn("passou 30:00", janela.tab_hospedados.item(linha, 4).text())
        self.assertEqual(janela.tab_hospedados.item(linha, 0).background().color().name(),
                         janela.palette().window().color().lightness() > 128 and "#f9d9d4" or "#5a2b2b")

    def test_cafe_avulso_e_diarias_vencidas_pela_tela(self):
        r = self.h.reservar(self.q101, "Maria", "2026-11-23", "2026-11-26", hospede_id=self.maria)
        self.h.checkin(r)
        janela = self.recepcao()
        self.linha_de(janela.tab_hospedados, "Maria")
        with mock.patch.object(QInputDialog, "getInt", return_value=(2, True)):
            janela.lancar_cafe()
        self.assertIn("Café de 2 pessoa(s) lançado na conta 500", janela.mensagem.text())
        self.avancar(days=2)
        janela.lancar_diarias_vencidas()
        self.assertIn("2 diária(s) lançada(s)", janela.mensagem.text())

    def test_mapa_mostra_os_blocos_e_dois_cliques_no_livre_reserva(self):
        self.h.reservar(self.q101, "Maria da Silva", "2026-11-24", "2026-11-27")
        janela = self.recepcao()
        janela.abas.setCurrentIndex(1)
        g = janela.grade_mapa
        self.assertEqual(g.rowCount(), 3)
        self.assertEqual((g.item(0, 2).text(), g.columnSpan(0, 2)), ("Maria da Silva", 3))  # o mapa começa ontem
        with mock.patch.object(janela, "nova_reserva") as nova:
            janela._clique_mapa(1, 3)
        nova.assert_called_once_with(self.q102, "2026-11-25")
        janela.mover_mapa(7)
        self.assertEqual(janela.inicio_mapa.isoformat(), "2026-11-29")

    def test_governanca_marca_limpo_e_manutencao(self):
        janela = self.recepcao()
        janela.abas.setCurrentIndex(4)
        self.linha_de(janela.tab_governanca, "102")
        with mock.patch.object(QInputDialog, "getText", return_value=("chuveiro queimado", True)):
            janela.marcar_limpeza("manutencao")
        self.assertEqual(self.h.uh(self.q102)["limpeza"], "manutencao")
        self.linha_de(janela.tab_governanca, "102")
        janela.marcar_limpeza("limpo")
        self.assertEqual(self.h.uh(self.q102)["limpeza"], "limpo")

    def test_cadastro_de_tipo_quarto_e_servicos_pela_tela(self):
        janela = self.recepcao()
        janela.abas.setCurrentIndex(6)
        janela.tipo_nome.setText("Suíte master")
        janela.tipo_capacidade.setValue(3)
        janela.tipo_preco.setText("320,00")
        janela.salvar_tipo()
        tipo = next(t for t in self.h.tipos() if t["nome"] == "Suíte master")
        self.assertEqual(tipo["preco_diaria_cent"], 32000)
        janela.uh_numero.setText("301")
        janela.uh_tipo.setCurrentIndex(janela.uh_tipo.findData(tipo["id"]))
        janela.salvar_uh()
        self.assertIn("301", [u["numero"] for u in self.h.uhs()])
        janela.tipo_preco.setText("abc")
        janela.salvar_tipo()
        self.assertIn("Preço inválido", janela.mensagem.text())
        janela.preco_hora.setText("35,00")
        janela.salvar_extras()
        self.assertEqual(self.h.precos_extras()["hora_extra"], 3500)

    def test_caixa_sem_nivel_de_gerente_nao_ve_o_cadastro(self):
        with mock.patch.object(type(self.ctx), "pode", lambda ctx, modulo: modulo != "cfg_hotel"):
            janela = self.recepcao()
        self.assertFalse(janela.pode_cadastrar)
        self.assertFalse(hasattr(janela, "tab_tipos"))

    def test_exporta_as_fichas(self):
        r = self.h.reservar(self.q101, "Maria", "2026-11-23", "2026-11-24", hospede_id=self.maria)
        self.h.checkin(r)
        janela = self.recepcao()
        janela.abas.setCurrentIndex(5)
        with tempfile.TemporaryDirectory() as pasta:
            destino = janela.exportar_fichas(str(Path(pasta) / "fichas.csv"))
            self.assertIn("Maria da Silva", destino.read_text(encoding="utf-8-sig"))
        self.assertIn("FNRH Digital", janela.mensagem.text())
        self.assertIn("Ocupação", janela.rel_resumo.text())

    def test_hospede_novo_pela_ficha(self):
        dialogo = self.mostrar(DialogoHospede(self.ctx, nome="Pedro Alves"))
        dialogo.campos["cpf"].setText("123")
        dialogo.salvar()
        self.assertIn("CPF inválido", dialogo.mensagem.text())
        dialogo.campos["cpf"].setText("111.444.777-35")
        dialogo.campos["nascimento"].setText("02/02/1990")
        dialogo.campos["uf"].setEditText("mg")
        dialogo.salvar()
        h = self.h.hospede(dialogo.hospede_id)
        self.assertEqual((h["nome"], h["uf"], h["nascimento"]), ("Pedro Alves", "MG", "1990-02-02"))
