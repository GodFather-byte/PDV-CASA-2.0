"""Controle de quartos: tempo em blocos, estados pelo relógio, liberação, configuração, campainha e painel Qt."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from unittest import mock

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


if __name__ == "__main__":
    unittest.main()
