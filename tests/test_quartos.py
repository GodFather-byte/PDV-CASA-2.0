"""Controle de quartos: tempo em blocos, estados pelo relógio, liberação, configuração, campainha e painel Qt."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from unittest import mock

try:
    from PySide6.QtCore import Qt
except ImportError:  # pragma: no cover - sem PySide6 os testes de tela são pulados
    Qt = None

from src.controllers.acesso_controller import AcessoController
from src.controllers.cadastro_controller import CadastroController
from src.controllers.config_controller import ConfigController, modulos_desligados
from src.controllers.contexto import Contexto
from src.controllers.quartos_controller import QuartosController, ler_campainhas
from src.core.erros import ErroNegocio, ErroPermissao, ErroValidacao
from src.database.esquema import VERSAO_ESQUEMA
from src.hardware import campainha
from tests.base import BaseTeste


class BaseQuartos(BaseTeste):
    def setUp(self):
        super().setUp()
        self.banco.cfg_set("usar_quartos", "S")
        self.q = QuartosController(self.banco, self.operador_adm())

    def estado(self, quarto):
        return next(i for i in self.q.situacao() if i["quarto"] == quarto)


class TesteRegrasQuartos(BaseQuartos):
    def test_esquema_e_padroes(self):
        self.assertGreaterEqual(VERSAO_ESQUEMA, 31)
        b = QuartosController(self.banco)
        self.assertEqual(b.config(), {"quartos": 7, "minutos_bloco": 30, "valor_bloco_cent": 9000, "alerta_min": 5})
        self.assertEqual(len(self.q.situacao()), 7)
        self.assertTrue(all(i["estado"] == "livre" for i in self.q.situacao()))

    def test_modulo_nasce_desligado_e_esconde_o_menu(self):
        self.banco.cfg_set("usar_quartos", "N")
        self.assertIn("util_quartos", modulos_desligados(self.banco))
        with self.assertRaises(ErroNegocio):
            self.q.iniciar(1, 1)
        self.banco.cfg_set("usar_quartos", "S")
        self.assertNotIn("util_quartos", modulos_desligados(self.banco))

    def test_comandas_e_historico_sem_cobranca(self):
        self.banco.inserir("garotas", {"numero": 167, "nome": "Rapha"})
        uso = self.q.iniciar(2, 1, "045", "167")
        ativo = self.estado(2)
        self.assertEqual(ativo["comanda_cliente"], "045")
        self.assertEqual(ativo["codigo_profissional"], "167")
        self.assertEqual(ativo["nome_profissional"], "Rapha")
        with self.assertRaises(ErroNegocio):
            self.q.iniciar(3, 1, "055", "167")
        self.assertEqual(self.q.historico(codigo="167")[0]["id"], uso)
        self.q.liberar(2)
        self.assertIsNotNone(self.q.historico(quarto=2)[0]["liberado_em"])
        self.q.iniciar(3, 1, "055", "167")
        self.assertEqual(len(self.q.historico(codigo="167")), 2)

    def test_codigo_invalido_e_identificacao_incompleta(self):
        for cliente, profissional in [("abc", "167"), ("12", "abc"), ("", "167")]:
            with self.assertRaises(ErroValidacao):
                self.q.iniciar(1, 1, cliente, profissional)
        self.assertEqual(self.estado(1)["estado"], "livre")

    def test_tres_horas_sao_seis_blocos_de_90(self):
        self.q.iniciar(1, 6)
        e = self.estado(1)
        self.assertEqual(e["estado"], "uso")
        self.assertEqual(e["minutos"], 180)
        self.assertEqual(e["valor_cent"], 54000)
        self.assertEqual(self.q.rotulo_blocos(6), "3h  —  R$ 540,00")
        self.assertEqual(int(e["restante_seg"]), 180 * 60)

    def test_estados_pelo_relogio(self):
        self.q.iniciar(2, 1)
        self.avancar(minutes=24, seconds=59)
        self.assertEqual(self.estado(2)["estado"], "uso")
        self.avancar(seconds=2)
        self.assertEqual(self.estado(2)["estado"], "alerta")
        self.avancar(minutes=5)
        e = self.estado(2)
        self.assertEqual(e["estado"], "estourou")
        self.assertLess(e["restante_seg"], 0)

    def test_tempo_continua_depois_de_reabrir(self):
        self.q.iniciar(3, 2)
        self.avancar(minutes=40)
        outro = QuartosController(self.banco)       # PDV reaberto: nada em memória
        self.assertEqual(int(next(i for i in outro.situacao() if i["quarto"] == 3)["restante_seg"]), 20 * 60)

    def test_nao_inicia_quarto_ocupado_nem_inexistente(self):
        self.q.iniciar(1, 1)
        with self.assertRaises(ErroNegocio):
            self.q.iniciar(1, 1)
        with self.assertRaises(ErroValidacao):
            self.q.iniciar(8, 1)
        with self.assertRaises(ErroValidacao):
            self.q.iniciar(2, 0)
        with self.assertRaises(ErroValidacao):
            self.q.iniciar(2, 25)

    def test_mais_tempo_soma_blocos(self):
        self.q.iniciar(4, 1)
        self.avancar(minutes=31)
        self.assertEqual(self.estado(4)["estado"], "estourou")
        self.q.adicionar_tempo(4, 1)
        e = self.estado(4)
        self.assertEqual(e["estado"], "uso")
        self.assertEqual(e["valor_cent"], 18000)
        with self.assertRaises(ErroNegocio):
            self.q.adicionar_tempo(5, 1)               # livre
        with self.assertRaises(ErroValidacao):
            self.q.adicionar_tempo(4, 23)              # passaria de 24 blocos

    def test_liberar_guarda_o_excesso_e_libera(self):
        self.q.iniciar(1, 1)
        self.avancar(minutes=10)
        self.assertEqual(self.q.liberar(1)["excedeu_seg"], 0)
        self.q.iniciar(1, 1)
        self.avancar(minutes=37)
        self.assertEqual(self.q.liberar(1)["excedeu_seg"], 7 * 60)
        self.assertEqual(self.estado(1)["estado"], "livre")
        with self.assertRaises(ErroNegocio):
            self.q.liberar(1)
        r = self.q.resumo_noite()
        self.assertEqual((r["usos"], r["minutos"], r["valor_cent"], r["estouros"]), (2, 60, 18000, 1))

    def test_liberar_diz_quantos_blocos_cobrar_depois_da_tolerancia(self):
        self.banco.inserir("garotas", {"numero": 167, "nome": "Rapha"})
        self.q.iniciar(1, 1, codigo_profissional="167")
        self.avancar(minutes=34)                               # passou 4 min: dentro da tolerância de 5
        self.assertEqual(self.q.liberar(1)["blocos_a_mais"], 0)
        self.q.iniciar(1, 1, codigo_profissional="167")
        self.avancar(minutes=42)                               # passou 12 min: cobra 1 bloco
        r = self.q.liberar(1)
        self.assertEqual((r["blocos_a_mais"], r["nome_profissional"], r["codigo_profissional"]), (1, "Rapha", "167"))
        self.banco.cfg_set("quartos_tolerancia_min", "0")
        self.q.iniciar(1, 1)
        self.avancar(minutes=61)                               # passou 31 min sem tolerância: 2 blocos
        self.assertEqual(self.q.liberar(1)["blocos_a_mais"], 2)

    def test_arrumacao_bloqueia_o_inicio_ate_ficar_pronto(self):
        self.q.iniciar(2, 1)
        with self.assertRaisesRegex(ErroNegocio, "em uso"):
            self.q.marcar_arrumacao(2, True)
        self.q.liberar(2, arrumar=True)
        self.assertEqual(self.estado(2)["estado"], "arrumacao")
        with self.assertRaisesRegex(ErroNegocio, "em arrumação"):
            self.q.iniciar(2, 1)
        self.assertNotIn(2, self.q.quartos_livres())
        self.q.marcar_arrumacao(5, True)
        self.assertEqual(self.q.em_arrumacao(), {2, 5})
        self.q.marcar_arrumacao(2, False)
        self.assertEqual(self.estado(2)["estado"], "livre")
        self.q.iniciar(2, 1)
        with self.assertRaises(ErroValidacao):
            self.q.marcar_arrumacao(99, True)

    def test_trocar_de_quarto_leva_tempo_horario_e_shows(self):
        self.banco.inserir("garotas", {"numero": 167, "nome": "Rapha"})
        uso = self.q.iniciar(1, 2, codigo_profissional="167")
        self.avancar(minutes=10)
        antes = self.estado(1)
        self.q.trocar_quarto(1, 4)
        depois = self.estado(4)
        self.assertEqual(self.estado(1)["estado"], "livre")
        self.assertEqual((depois["uso_id"], depois["inicio"], depois["fim"]), (uso, antes["inicio"], antes["fim"]))
        self.assertEqual(self.banco.valor("SELECT SUM(quantidade) FROM shows_quartos WHERE uso_id = ?", (uso,)), 2)
        self.q.iniciar(1, 1)
        self.q.marcar_arrumacao(5, True)
        for origem, destino, trecho in ((4, 1, "em uso"), (4, 5, "arrumação"), (2, 3, "livre"), (4, 4, "outro"),
                                        (4, 99, "inexistente")):
            with self.assertRaisesRegex((ErroNegocio, ErroValidacao), trecho):
                self.q.trocar_quarto(origem, destino)

    def test_garotas_da_noite(self):
        self.banco.inserir("garotas", {"numero": 167, "nome": "Rapha"})
        self.banco.inserir("garotas", {"numero": 180, "nome": "Ana"})
        self.q.iniciar(1, 2, codigo_profissional="167")
        self.q.iniciar(2, 1, codigo_profissional="180")
        self.avancar(minutes=40)
        self.q.liberar(2)
        self.q.iniciar(2, 1, codigo_profissional="180")
        self.q.iniciar(3, 1)                                   # sem garota: não entra na lista
        linhas = {r["codigo"]: r for r in self.q.garotas_da_noite()}
        self.assertEqual(set(linhas), {"167", "180"})
        self.assertEqual((linhas["180"]["entradas"], linhas["180"]["tempo"], linhas["180"]["shows"],
                          linhas["180"]["excedeu_seg"], linhas["180"]["no_quarto"]), (2, "1h", 2, 600, 1))
        self.assertEqual((linhas["167"]["nome"], linhas["167"]["shows"]), ("Rapha", 2))

    def test_quarto_pela_comanda_vem_desligado(self):
        self.assertFalse(self.q.pela_comanda())
        self.banco.cfg_set("quartos_pela_comanda", "S")
        self.assertTrue(self.q.pela_comanda())
        self.banco.cfg_set("usar_quartos", "N")
        self.assertFalse(self.q.pela_comanda())

    def test_valor_gravado_no_inicio_nao_muda_com_a_config(self):
        self.q.iniciar(1, 2)
        self.banco.cfg_set("quartos_valor_bloco", "100")
        self.assertEqual(self.estado(1)["valor_cent"], 18000)

    def test_quarto_em_uso_acima_da_quantidade_continua_visivel(self):
        self.q.iniciar(7, 1)
        self.banco.cfg_set("quartos_qtd", "5")
        self.assertEqual([i["quarto"] for i in self.q.situacao()], [1, 2, 3, 4, 5, 7])
        self.q.liberar(7)
        self.assertEqual(len(self.q.situacao()), 5)

    def test_resumo_da_noite_respeita_a_virada(self):
        self.q.iniciar(1, 1)                       # 21h do dia 3
        self.q.liberar(1)
        self.avancar(hours=6)                       # 3h do dia 4: ainda é a noite do dia 3 (virada às 6h)
        self.q.iniciar(2, 1)
        self.assertEqual(self.q.resumo_noite()["usos"], 2)
        self.avancar(hours=4)                       # 7h: noite nova
        self.assertEqual(self.q.resumo_noite()["usos"], 0)


class TesteConfigQuartos(BaseQuartos):
    def test_ler_campainhas(self):
        self.assertEqual(ler_campainhas(""), {})
        self.assertEqual(ler_campainhas("1=192.168.0.51; 2 = 192.168.0.52\n3=quarto3.local"),
                         {1: "192.168.0.51", 2: "192.168.0.52", 3: "quarto3.local"})
        for ruim in ("192.168.0.51", "x=1.2.3.4", "0=1.2.3.4", "1=http://a/b", "1="):
            with self.assertRaises(ErroValidacao, msg=ruim):
                ler_campainhas(ruim)

    def test_salvar_configuracao_valida(self):
        cfg = ConfigController(self.banco)
        cfg.salvar_config({"quartos_qtd": "10", "quartos_campainhas": "1=192.168.0.51", "quartos_valor_bloco": "95,50"})
        self.assertEqual(self.q.config()["quartos"], 10)
        self.assertEqual(self.q.config()["valor_bloco_cent"], 9550)
        self.assertEqual(self.q.campainhas(), {1: "192.168.0.51"})
        for chave, valor in (("quartos_qtd", "0"), ("quartos_minutos_bloco", "2"), ("quartos_alerta_min", "90"),
                             ("quartos_campainhas", "lixo"), ("quartos_valor_bloco", "abc")):
            with self.assertRaises(ErroValidacao, msg=chave):
                cfg.salvar_config({chave: valor})


class TesteCampainha(unittest.TestCase):
    def test_comando_invalido(self):
        with self.assertRaises(ValueError):
            campainha.enviar("127.0.0.1", "explodir")

    def test_aparelho_fora_do_ar_nao_levanta_erro(self):
        self.assertFalse(campainha.enviar("127.0.0.1:9", "ping", timeout=0.5))

    def test_segundo_plano_chama_o_retorno(self):
        resultados = []
        with mock.patch.object(campainha, "enviar", return_value=True) as enviar:
            campainha.enviar_em_segundo_plano("10.0.0.1", "tocar", resultados.append).join(2)
        enviar.assert_called_once_with("10.0.0.1", "tocar")
        self.assertEqual(resultados, [True])


class TesteQuartosQt(BaseQuartos):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as erro:
            raise unittest.SkipTest(f"PySide6 ausente: {erro}")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from PySide6.QtCore import QCoreApplication, QEvent
        self.addCleanup(lambda: QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete))
        self.baixo = CadastroController(self.banco).salvar("operadores", {"nome": "CAIXA", "senha": "1234", "nivel": "1"})
        self.envios = []
        p = mock.patch("src.hardware.campainha.enviar_em_segundo_plano",
                       side_effect=lambda end, cmd, ao=None: self.envios.append((end, cmd)))
        p.start()
        self.addCleanup(p.stop)
        b = mock.patch("PySide6.QtWidgets.QApplication.beep")
        b.start()
        self.addCleanup(b.stop)

    def janela(self, operador_id=None):
        from src.ui_qt.quartos import JanelaQuartos
        ctx = Contexto(self.banco, AcessoController(self.banco).operador(operador_id or self.operador_adm()))
        j = JanelaQuartos(ctx)
        j.timer.stop()
        j.timer_campainhas.stop()
        self.addCleanup(j.deleteLater)
        return j

    def test_caixa_nivel_1_abre_e_mostra_os_quartos(self):
        j = self.janela(self.baixo)
        self.assertEqual(sorted(j.cartoes), list(range(1, 8)))
        self.assertTrue(all(c.tempo.text() == "LIVRE" for c in j.cartoes.values()))
        self.assertIn("Livres: 7 de 7", j.resumo.text())

    def test_modulo_desligado_nao_abre(self):
        self.banco.cfg_set("usar_quartos", "N")
        with self.assertRaises(ErroPermissao):
            self.janela()

    def test_cartao_acompanha_o_tempo_e_avisa(self):
        self.banco.cfg_set("quartos_campainhas", "2=192.168.0.52")
        self.q.iniciar(2, 1)
        j = self.janela()
        c = j.cartoes[2]
        self.assertEqual(c.tempo.text(), "30:00")
        self.assertTrue(c.b_liberar.isEnabled())
        self.assertFalse(c.b_iniciar.isEnabled())
        self.avancar(minutes=26)
        j.atualizar()
        self.assertIn(("192.168.0.52", "alerta"), self.envios)
        self.avancar(minutes=5)
        j.atualizar()
        self.assertEqual(c.tempo.text(), "+01:00")
        self.assertEqual(self.envios.count(("192.168.0.52", "tocar")), 1)
        self.avancar(seconds=30)
        j.atualizar()
        self.assertEqual(self.envios.count(("192.168.0.52", "tocar")), 1)   # repete só a cada minuto
        self.avancar(seconds=30)
        j.atualizar()
        self.assertEqual(self.envios.count(("192.168.0.52", "tocar")), 2)

    def test_liberar_pela_tela_desliga_a_campainha(self):
        self.banco.cfg_set("quartos_campainhas", "1=192.168.0.51")
        self.q.iniciar(1, 1)
        j = self.janela()
        j.executar(lambda: j.controlador().liberar(1), 1)
        self.assertEqual(j.cartoes[1].tempo.text(), "LIVRE")
        self.assertIn(("192.168.0.51", "parar"), self.envios)

    def test_erro_de_regra_aparece_na_mensagem(self):
        self.q.iniciar(1, 1)
        j = self.janela()
        j.executar(lambda: j.controlador().iniciar(1, 1), 1)
        self.assertIn("já está em uso", j.mensagem.text())

    # ---- cartões no caixa ----
    def painel(self, operador_id=None):
        from src.ui_qt.quartos import PainelQuartosCaixa
        ctx = Contexto(self.banco, AcessoController(self.banco).operador(operador_id or self.operador_adm()))
        f = PainelQuartosCaixa(ctx)
        f.timer.stop()
        f.timer_campainhas.stop()
        self.addCleanup(f.deleteLater)
        return f

    def test_cartoes_mostram_cada_quarto_e_somem_com_o_modulo_desligado(self):
        self.q.iniciar(3, 6)
        f = self.painel(self.baixo)
        self.assertFalse(f.isHidden())
        self.assertEqual(sorted(f.itens), list(range(1, 8)))
        self.assertEqual(f.texto_do_quarto(3), "3 · 3:00:00")
        self.assertEqual(f.texto_do_quarto(1), "1 · livre")
        self.assertEqual(f.resumo.text(), "6 livres\n1 ocupado")
        self.assertEqual((f.grade.colunas, f.grade.height()), (4, 2 * f.grade.ALTURA))   # cartões maiores em duas linhas
        self.avancar(hours=3, minutes=2)
        f.atualizar()
        self.assertEqual(f.texto_do_quarto(3), "3 · +02:00")
        self.assertIn("1 com tempo esgotado", f.resumo.toolTip())
        self.banco.cfg_set("usar_quartos", "N")
        f.atualizar()
        self.assertTrue(f.isHidden())

    def test_cartoes_nao_tiram_o_foco_do_caixa(self):
        f = self.painel()
        self.assertEqual(f.grade.focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertEqual(f.btn_painel.focusPolicy(), Qt.FocusPolicy.NoFocus)

    def test_faixa_diz_quais_estao_livres_e_cartao_mostra_ocupado(self):
        self.banco.cfg_set("quartos_qtd", "4")
        self.q.iniciar(1, 2)
        self.q.iniciar(2, 1)
        self.q.marcar_arrumacao(4, True)
        self.avancar(minutes=27)                               # o 2 está acabando; o 1 usou 45% do tempo
        j = self.janela()
        self.assertEqual(j.faixa.text(), "LIVRES: 3  ·  OCUPADOS: 2 (1 acabando)  ·  ARRUMANDO: 1")
        self.assertEqual([j.cartoes[n].etiqueta.text() for n in (1, 2, 3, 4)],
                         ["OCUPADO", "ACABANDO", "LIVRE", "EM ARRUMAÇÃO"])
        self.assertEqual(j.cartoes[1].barra.value(), 45)
        self.assertTrue(j.cartoes[1].barra.isVisibleTo(j))
        self.assertFalse(j.cartoes[3].barra.isVisibleTo(j))
        self.q.iniciar(3, 1)
        j.atualizar()
        self.assertTrue(j.faixa.text().startswith("LIVRES: nenhum"))
        self.assertIn("#c62828", j.faixa.styleSheet())                  # sem quarto livre: faixa vermelha

    def test_resumo_do_caixa_lista_os_livres_quando_sao_poucos(self):
        self.banco.cfg_set("quartos_qtd", "3")
        self.q.iniciar(2, 1)
        f = self.painel()
        self.assertEqual(f.resumo.text(), "Livres: 1, 3\n1 ocupado")
        self.q.iniciar(1, 1)
        self.q.iniciar(3, 1)
        f.atualizar()
        self.assertEqual(f.resumo.text(), "Nenhum livre\n3 ocupados")

    def test_cartao_arrumacao_pronto_e_troca(self):
        from src.ui_qt import quartos as tela
        j = self.janela()
        c = j.cartoes[3]
        self.assertEqual(c.b_extra.text(), "Pôr em arrumação")
        c.extra()
        self.assertEqual((c.tempo.text(), c.b_extra.text()), ("ARRUMANDO", "Quarto pronto"))
        self.assertFalse(c.b_iniciar.isEnabled())
        c.extra()
        self.assertEqual(c.tempo.text(), "LIVRE")
        self.q.iniciar(3, 1)
        j.atualizar()
        self.assertEqual(c.b_extra.text(), "Trocar de quarto")
        with mock.patch.object(tela.QInputDialog, "getItem", return_value=("6", True)) as escolha:
            c.extra()
        self.assertEqual(escolha.call_args.args[3], ["1", "2", "4", "5", "6", "7"])
        self.assertEqual(self.estado(6)["estado"], "uso")
        self.assertEqual(self.estado(3)["estado"], "livre")

    def test_liberar_com_arrumacao_e_aviso_do_excedido(self):
        from src.ui_qt import quartos as tela
        self.banco.inserir("garotas", {"numero": 167, "nome": "Rapha"})
        self.q.iniciar(2, 1, codigo_profissional="167")
        self.avancar(minutes=45)
        j = self.janela()
        with mock.patch.object(tela, "escolher_liberacao", return_value="arrumar"), \
                mock.patch.object(tela.QMessageBox, "information") as info:
            j.cartoes[2].liberar()
        self.assertIn("passou 15:00 do tempo", info.call_args.args[2])
        self.assertIn("Cobre 1 bloco(s) a mais de Rapha (167)", info.call_args.args[2])
        self.assertEqual(self.estado(2)["estado"], "arrumacao")
        with mock.patch.object(tela, "escolher_liberacao", return_value=None):
            self.assertIsNone(tela.pedir_liberar(j, self.q, 2))

    def test_botao_garotas_da_noite(self):
        from PySide6.QtWidgets import QPushButton
        from src.ui_qt.quartos import DialogoGarotasNoite
        self.banco.inserir("garotas", {"numero": 167, "nome": "Rapha"})
        self.q.iniciar(1, 2, codigo_profissional="167")
        j = self.janela()
        self.assertIn("Garotas da noite", [b.text() for b in j.findChildren(QPushButton)])
        d = DialogoGarotasNoite(self.q, j)
        self.addCleanup(d.deleteLater)
        self.assertEqual(d.tabela.item(0, 1).text(), "Rapha  (no quarto)")
        self.assertEqual(d.tabela.item(0, 4).text(), "2")

    def test_quarto_livre_ja_abre_o_tempo_e_o_ocupado_mostra_opcoes(self):
        from src.ui_qt import quartos as tela
        f = self.painel()
        with mock.patch.object(tela, "pedir_iniciar", lambda pai, ctrl, q: (lambda: ctrl.iniciar(q, 1))):
            f.grade.clicado.emit(2)                                     # clique no cartão livre
        self.assertEqual(self.estado(2)["minutos"], 30)
        self.assertEqual(f.texto_do_quarto(2), "2 · 30:00")
        f.acionar(2)
        self.assertEqual([a.text() for a in f._menu.actions() if a.text()],
                         ["+ Tempo…", "Trocar de quarto…", "Liberar quarto", "Abrir painel dos quartos"])
        with mock.patch.object(tela, "pedir_liberar", lambda pai, ctrl, q: (lambda: ctrl.liberar(q))):
            f._menu.actions()[2].trigger()
        self.assertEqual(f.texto_do_quarto(2), "2 · livre")

    def test_q3_pede_tempo_antes_de_iniciar(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QDialogButtonBox, QPushButton
        from src.ui_qt.caixa import JanelaCaixa
        from src.ui_qt.quartos import DialogoTempo
        from src.controllers.quartos_controller import fmt_duracao
        CadastroController(self.banco).salvar("garotas", {"numero": "167", "nome": "Rapha", "ativo": "S"})
        ctx = Contexto(self.banco, AcessoController(self.banco).operador(self.operador_adm()))
        ctx.turnos.abrir(ctx.operador_id, 1, 0)
        j = JanelaCaixa(ctx)
        self.addCleanup(j.deleteLater)
        j.show()
        for blocos in (1, 2, 3, 4, 6, None):
            with self.subTest(blocos=blocos):
                erros = []

                def escolher():
                    dlg = QApplication.activeModalWidget()
                    try:
                        self.assertIsInstance(dlg, DialogoTempo)
                        self.assertEqual(self.estado(3)["estado"], "livre")
                        confirmar = dlg.botoes.button(QDialogButtonBox.StandardButton.Ok)
                        self.assertFalse(confirmar.isEnabled())
                        dlg.profissional.setText("167")
                        QTest.keyClick(dlg.profissional, Qt.Key.Key_Return)
                        self.assertTrue(dlg.isVisible())
                        if blocos is None:
                            dlg.reject()
                            return
                        botao = next(b for b in dlg.findChildren(QPushButton)
                                     if b.text() == fmt_duracao(blocos * 30))
                        botao.click()
                        self.assertEqual(dlg.tempo.currentData(), blocos)
                        self.assertTrue(confirmar.isEnabled())
                        self.assertEqual(self.estado(3)["estado"], "livre")
                        confirmar.click()
                    except BaseException as erro:
                        erros.append(erro)
                        if dlg is not None:
                            dlg.reject()

                j.ent_pos.setText("Q3")
                QTimer.singleShot(0, escolher)
                QTest.keyClick(j.ent_pos, Qt.Key.Key_Return)
                if erros:
                    raise erros[0]
                if blocos is None:
                    self.assertEqual(self.estado(3)["estado"], "livre")
                else:
                    self.assertEqual(self.estado(3)["minutos"], blocos * 30)
                    self.q.liberar(3)
                    j.painel_quartos.atualizar()

    def test_escolha_de_tempo_respeita_bloco_configurado_e_limite(self):
        from src.ui_qt.quartos import DialogoTempo
        self.banco.cfg_set("quartos_minutos_bloco", "60")
        dlg = DialogoTempo(self.q, "Adicionar tempo — quarto 3", maximo=2)
        self.addCleanup(dlg.deleteLater)
        self.assertEqual([dlg.tempo.itemText(i) for i in range(dlg.tempo.count())], ["1h", "2h"])
        self.assertEqual(dlg.tempo.currentData(), 1)
        dlg.tempo.setCurrentIndex(1)
        self.assertIn("2h", dlg.resumo.text())

    def test_desistir_da_escolha_nao_inicia(self):
        from src.ui_qt import quartos as tela
        f = self.painel()
        with mock.patch.object(tela, "pedir_iniciar", lambda pai, ctrl, q: None):
            f.acionar(4)
        self.assertEqual(self.estado(4)["estado"], "livre")

    def test_atalho_q_no_campo_da_comanda(self):
        from src.ui_qt.quartos import ler_atalho_quarto
        self.assertEqual(ler_atalho_quarto("Q3"), 3)
        self.assertEqual(ler_atalho_quarto(" q 12 "), 12)
        for outro in ("3", "M5", "Q", "QX", "", "Q3A"):
            self.assertIsNone(ler_atalho_quarto(outro), outro)

    def test_caixa_e_painel_abertos_nao_tocam_em_dobro(self):
        self.banco.cfg_set("quartos_campainhas", "1=192.168.0.51")
        self.q.iniciar(1, 1)
        f = self.painel()
        j = self.janela()
        self.avancar(minutes=31)
        f.atualizar()
        j.atualizar()
        self.assertEqual(self.envios.count(("192.168.0.51", "tocar")), 1)

    def test_aviso_na_tela_aos_5_minutos_e_some_ao_liberar(self):
        from PySide6.QtWidgets import QWidget
        from src.ui_qt.quartos import PainelQuartosCaixa
        janela = QWidget()
        janela.resize(1200, 700)
        self.addCleanup(janela.deleteLater)
        ctx = Contexto(self.banco, AcessoController(self.banco).operador(self.operador_adm()))
        self.q.iniciar(3, 1)
        f = PainelQuartosCaixa(ctx, janela)
        f.timer.stop()
        f.timer_campainhas.stop()
        janela.show()
        self.assertTrue(f.aviso_tela.isHidden())
        self.avancar(minutes=25, seconds=1)
        f.atualizar()
        self.assertFalse(f.aviso_tela.isHidden())
        self.assertIn("QUARTO 3", f.aviso_tela.texto.text())
        self.assertIn("faltam 5 minutos", f.aviso_tela.texto.text())
        self.assertEqual(f.aviso_tela.ok.focusPolicy(), Qt.FocusPolicy.NoFocus)   # não rouba o Enter do caixa
        f.atualizar()                                                              # não repete o aviso
        self.assertEqual(f.aviso_tela.texto.text().count("QUARTO 3"), 1)
        self.avancar(minutes=5)
        f.atualizar()
        self.assertIn("TEMPO ESGOTADO", f.aviso_tela.texto.text())
        f.pedir(lambda ctrl: (lambda: ctrl.liberar(3)), 3)
        self.assertTrue(f.aviso_tela.isHidden())

    def test_ok_fecha_o_aviso(self):
        from PySide6.QtWidgets import QWidget
        from src.ui_qt.quartos import PainelQuartosCaixa
        janela = QWidget()
        self.addCleanup(janela.deleteLater)
        ctx = Contexto(self.banco, AcessoController(self.banco).operador(self.operador_adm()))
        self.q.iniciar(1, 1)
        f = PainelQuartosCaixa(ctx, janela)
        f.timer.stop()
        janela.show()
        self.avancar(minutes=26)
        f.atualizar()
        self.assertIn("falta", f.aviso_tela.texto.text())
        f.aviso_tela.ok.click()
        self.assertTrue(f.aviso_tela.isHidden())

    def test_som_diferente_para_aviso_e_esgotado(self):
        from src.ui_qt import quartos as tela
        self.assertNotEqual(tela.SONS["alerta"], tela.SONS["estourou"])
        self.q.iniciar(1, 1)
        f = self.painel()
        with mock.patch.object(tela, "tocar_som") as som:
            self.avancar(minutes=26)
            f.atualizar()
            self.avancar(minutes=5)
            f.atualizar()
        self.assertEqual([c.args[0] for c in som.call_args_list], ["alerta", "estourou"])

    def test_lancar_produto_nao_corta_quartos_em_tela_baixa(self):
        from PySide6.QtCore import QPoint
        from src.ui_qt.caixa import JanelaCaixa
        self.banco.cfg_set("imprimir_cupom", "0")
        self.novo_produto("COCA LATA", 500, codigo="20")
        self.novo_produto("COCA 2L", 900, codigo="21")
        ctx = Contexto(self.banco, AcessoController(self.banco).operador(self.operador_adm()))
        ctx.turnos.abrir(ctx.operador_id, 1, 0)
        j = JanelaCaixa(ctx)
        self.addCleanup(j.deleteLater)
        j.show()

        def conferir_quartos():
            self.app.processEvents()
            self.assertLessEqual(j.height(), altura)
            painel = j.painel_quartos
            pos = painel.mapTo(j.centralWidget(), QPoint(0, 0))
            self.assertTrue(painel.isVisible())
            self.assertGreaterEqual(pos.y(), 0)
            self.assertLessEqual(pos.y() + painel.height(), j.centralWidget().height())
            self.assertGreaterEqual(painel.height(), painel.grade.height())
            self.assertEqual(len(painel.itens), 7)

        for largura, altura in ((1366, 768), (1280, 720)):
            with self.subTest(resolucao=(largura, altura)):
                j.resize(largura, altura)
                conferir_quartos()
                tamanho = j.painel_quartos.size()
                j.ent_codigo.setText("COCA")
                j.lancar_item()
                self.assertTrue(j.lista_produtos.isVisible())
                conferir_quartos()
                self.assertEqual(j.painel_quartos.size(), tamanho)
                j.lancar_item()
                self.assertFalse(j.lista_produtos.isVisible())
                self.assertGreater(j.tabela.rowCount(), 0)
                conferir_quartos()

    def test_tela_do_caixa_tem_os_quartos_e_o_atalho(self):
        from src.ui_qt import quartos as tela
        from src.ui_qt.caixa import JanelaCaixa
        self.banco.cfg_set("imprimir_cupom", "0")
        ctx = Contexto(self.banco, AcessoController(self.banco).operador(self.operador_adm()))
        ctx.turnos.abrir(ctx.operador_id, 1, 10000)
        j = JanelaCaixa(ctx)
        self.addCleanup(j.deleteLater)
        j.painel_quartos.timer.stop()
        self.assertEqual(len(j.painel_quartos.itens), 7)
        self.assertIn("Q3 = quarto 3", j.lbl_dica_pos.text())
        j.ent_pos.setText("Q3")
        with mock.patch.object(tela, "pedir_iniciar", lambda pai, ctrl, q: (lambda: ctrl.iniciar(q, 2))):
            j.chamar_posicao()
        self.assertEqual(self.estado(3)["minutos"], 60)
        self.assertEqual(j.ent_pos.text(), "")
        self.banco.cfg_set("usar_quartos", "N")
        j.painel_quartos.atualizar()
        self.assertTrue(j.painel_quartos.isHidden())


if __name__ == "__main__":
    unittest.main()
